"""Distribution: Frappe glue (G-69, ADR-039).

- ``build_days``: what a mapped room/rate may sell, per day, from TEX's own inventory,
  restrictions and prices (the same functions selling uses).
- ``mark_dirty`` → ARI jobs in ``TEX Integration Outbox`` (kind ARI), coalesced per mapping;
  ``deliver_ari`` claims jobs, pushes only what changed since the channel last accepted it
  (``TEX Channel ARI Day``), retries with back-off and parks a job as Dead after
  ``MAX_ATTEMPTS`` or on a rejection.
- ``receive`` (the webhook) verifies the signature (fail closed), stores each booking
  message once (idempotency key) in ``TEX Channel Inbound``; ``process_inbound`` applies
  them in order through ``channel_booking``.
- ``reconcile``: ARI drift and booking differences, audited.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import add_to_date, getdate, now_datetime

from kamra.tex.distribution import ari as ari_math
from kamra.tex.distribution import signing
from kamra.tex.distribution.adapters import REGISTRY, AdapterError, ChannelAdapter
from kamra.tex.distribution.model import AriDay, Mismatch
from kamra.tex.money import D
from kamra.tex.security.audit import audit, redact_text

CATEGORY = "Channel Manager"
MAX_ATTEMPTS = 8
CLAIM_MINUTES = 10
MAX_HORIZON = 365


def _commit() -> None:
	"""A queue item is its own unit of work in production; tests keep one transaction."""
	if not frappe.flags.in_test:
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- background worker unit-of-work boundary


def _each(names: list[str], work, on_fail) -> tuple[int, int]:
	ok = bad = 0
	for name in names:
		sp = "tex_dist_" + frappe.generate_hash(length=8)
		frappe.db.savepoint(sp)
		try:
			work(name)
			_commit()
			ok += 1
		except Exception as e:
			frappe.db.rollback(save_point=sp)
			on_fail(name, e)
			_commit()
			bad += 1
	return ok, bad


# ─── connections ─────────────────────────────────────────────────────────


def adapter_for(conn) -> ChannelAdapter:
	cls = REGISTRY.get(conn.adapter)
	if cls is None:
		frappe.throw(_("No channel adapter '{0}' is installed.").format(conn.adapter))
	if conn.environment == "Production" and not cls.certified:
		frappe.throw(_("{0} is not certified for production.").format(cls.label))
	return cls(conn, secret=conn.get_password("secret", raise_exception=False),
	           api_key=conn.get_password("api_key", raise_exception=False))


def channel_connections(property: str) -> list[str]:
	return frappe.get_all("TEX Integration Connection", filters={"property": property, "enabled": 1,
	                                                             "category": CATEGORY}, pluck="name")


# ─── ARI ─────────────────────────────────────────────────────────────────


def _occupancies(m) -> list[int]:
	out = sorted({int(x) for x in str(m.occupancies or "2").replace(" ", "").split(",") if x.isdigit() and 0 < int(x) < 10})
	return out or [2]


def _contract_version(m, at) -> tuple[str | None, str | None]:
	from kamra.tex.commercial import contracts

	cands = contracts.candidate_contracts(m.property, m.market, m.sales_channel, at)
	if m.contract:
		cands = [c for c in cands if c[0].name == m.contract]
	return (cands[0][0].name, cands[0][1]) if cands else (None, None)


def build_days(mapping, start: date, end: date) -> list[AriDay]:
	"""ARI of one mapping for ``start``..``end`` (inclusive), from TEX's own rules: the
	pool's availability for the mapping's contract (allotments included), the effective
	restrictions for its room/contract/market/rate plan/channel, and TEX's price of one
	night per occupancy. A day TEX cannot price is sent closed."""
	from kamra.tex.availability import inventory_math as inv
	from kamra.tex.availability import repository as avail
	from kamra.tex.availability import restrictions as rs
	from kamra.tex.pricing.model import PricingError, StayRequest
	from kamra.tex.services import quoting

	m = frappe.get_cached_doc("TEX Channel Mapping", mapping) if isinstance(mapping, str) else mapping
	days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
	if not days:
		return []
	if not m.enabled:
		return [closed_day(m, d) for d in days]
	now = now_datetime()
	contract, version = _contract_version(m, now)
	pdays, allot = avail.pool_days(m.property, m.room_type, days)
	cells = avail.restriction_cells(m.property, days[0], days[-1])
	eff = rs.effective(cells, avail.scope_for(m.room_type, contract, m.market, m.rate_plan, m.sales_channel), days)
	out = []
	for p in pdays:
		a = inv.day_availability(p, allot, contract, now.date())
		e = eff.get(p.day)
		rates = []
		if version:
			for adults in _occupancies(m):
				req = StayRequest(property=m.property, room_type=m.room_type, board=m.board, check_in=p.day,
				                  check_out=p.day + timedelta(days=1), adults=adults, sale_at=now, market=m.market,
				                  channel=m.sales_channel, sell_currency=m.sell_currency, rate_plan=m.rate_plan)
				try:
					q, _terms = quoting.price_request(version, req, check_capacity=False)
				except PricingError:
					continue                          # e.g. a rate plan the mapping must name: the day is sent closed
				if q.sellable:
					rates.append((adults, D(q.totals["total"])))
		# the sale-date rules as of today's sale (G-48): a night outside its booking window is not
		# sold; an arrival inside its release or outside its advance window is closed to arrival
		closed = bool(p.closed or not version or not rates or (e and (e.stop_sell or e.sale_closed(now.date()))))
		cta = bool(e and (e.cta or e.arrival_closed(now.date())))
		out.append(AriDay(p.day, max(0, a.available), closed, cta, bool(e and e.ctd),
		                  e.min_los if e else None, e.max_los if e else None, tuple(rates), m.sell_currency))
	return out


def closed_day(m, day: date) -> AriDay:
	"""What a disabled mapping sends: nothing left to sell (the close-out, G-69)."""
	return AriDay(day, 0, True, currency=m.sell_currency)


def closed_out(m) -> bool:
	"""Has the channel accepted the close-out of every day TEX ever sent it for this mapping?"""
	return all(fp == closed_day(m, d).fingerprint() for d, fp in pushed_state(m.name, date.min, date.max).items())


def queue_mapping(m, reason: str = "mapping") -> None:
	"""A mapping was created, changed, enabled or disabled: compare its whole horizon again."""
	if frappe.db.get_value("TEX Integration Connection", m.connection, "enabled"):
		lo, hi = _horizon(m)
		_queue(m, lo, hi, reason)


def _horizon(m) -> tuple[date, date]:
	today = getdate()
	return today, today + timedelta(days=max(1, min(int(m.horizon_days or 90), MAX_HORIZON)) - 1)


def pushed_state(mapping: str, start: date, end: date) -> dict[date, str]:
	return {getdate(r.ari_date): r.fingerprint for r in frappe.get_all(
		"TEX Channel ARI Day", filters={"mapping": mapping, "ari_date": ("between", [start, end])},
		fields=["ari_date", "fingerprint"])}


def _ari_day_name(mapping: str, d: date) -> str:
	return "ARI-" + hashlib.sha1(f"{mapping}|{d.isoformat()}".encode()).hexdigest()[:24]


def _accept(m, days: list[AriDay]) -> None:
	now = now_datetime()
	for d in days:
		frappe.db.sql(
			"""INSERT INTO `tabTEX Channel ARI Day` (name, creation, modified, owner, modified_by, docstatus, connection,
			     mapping, property, ari_date, fingerprint, pushed_at, payload)
			   VALUES (%(n)s, %(t)s, %(t)s, 'Administrator', 'Administrator', 0, %(c)s, %(m)s, %(p)s, %(d)s, %(f)s, %(t)s,
			     %(j)s)
			   ON DUPLICATE KEY UPDATE fingerprint=%(f)s, pushed_at=%(t)s, payload=%(j)s, modified=%(t)s""",
			{"n": _ari_day_name(m.name, d.day), "t": now, "c": m.connection, "m": m.name, "p": m.property, "d": d.day,
			 "f": d.fingerprint(), "j": json.dumps(d.to_dict())})


def mark_dirty(property: str, room_types=None, date_from=None, date_to=None, *, reason: str = "",
               connection: str | None = None) -> int:
	"""Queue an ARI sync for every enabled mapping of the hotel's channel connections (or of
	one ``connection``) that covers these room types (their pools) and dates. Jobs are
	coalesced per mapping while they wait. Returns the number of jobs touched."""
	conns = [c for c in channel_connections(property) if connection is None or c == connection]
	if not conns:
		return 0
	from kamra.tex.availability import repository as avail

	pools = None
	if room_types:
		pools = set()
		for rt in {r for r in room_types if r}:
			pools |= set(avail.pool_of(rt)[1])
	touched = 0
	for m in frappe.get_all("TEX Channel Mapping", filters={"connection": ("in", conns), "enabled": 1},
	                        fields=["name", "connection", "property", "room_type", "horizon_days"]):
		if pools is not None and m.room_type not in pools:
			continue
		lo, hi = _horizon(m)
		a = max(getdate(date_from), lo) if date_from else lo
		b = min(getdate(date_to), hi) if date_to else hi
		if a > b:
			continue
		_queue(m, a, b, reason)
		touched += 1
	return touched


# a waiting job takes in a new range this close to its own; a range further away is a job of its
# own, so two far-apart days never make one job of every day between them (G-48 review L5)
COALESCE_GAP_DAYS = 7


def _near(p: dict, a: date, b: date) -> bool:
	lo, hi = p.get("from"), p.get("to")
	if not lo or not hi:
		return True
	gap = timedelta(days=COALESCE_GAP_DAYS)
	return a <= getdate(hi) + gap and getdate(lo) - gap <= b


def _queue(m, a: date, b: date, reason: str) -> None:
	waiting = frappe.db.sql(
		"""SELECT name, payload FROM `tabTEX Integration Outbox`
		   WHERE kind='ARI' AND connection=%(c)s AND status='Pending' AND claim_token IS NULL
		     AND reference_name=%(m)s ORDER BY creation ASC FOR UPDATE""", {"c": m.connection, "m": m.name},
		as_dict=True)
	waiting = [w for w in waiting if _near(json.loads(w.payload or "{}"), a, b)]
	if waiting:
		p = json.loads(waiting[0].payload or "{}")
		p["from"] = min(p.get("from", a.isoformat()), a.isoformat())
		p["to"] = max(p.get("to", b.isoformat()), b.isoformat())
		p["reasons"] = sorted(set(p.get("reasons") or []) | ({reason} if reason else set()))[:20]
		frappe.db.set_value("TEX Integration Outbox", waiting[0].name, "payload", json.dumps(p), update_modified=False)
		return
	frappe.get_doc({"doctype": "TEX Integration Outbox", "kind": "ARI", "connection": m.connection,
	                "property": m.property, "event": "ari.sync", "status": "Pending", "attempts": 0,
	                "next_attempt_at": now_datetime(), "reference_doctype": "TEX Channel Mapping",
	                "reference_name": m.name, "idempotency_key": f"ari|{m.name}|{frappe.generate_hash(length=16)}",
	                "payload": json.dumps({"mapping": m.name, "from": a.isoformat(), "to": b.isoformat(),
	                                       "reasons": [reason] if reason else []})}).insert(ignore_permissions=True)


def claim(kind: str, limit: int, connection: str | None = None) -> list[str]:
	"""Take due jobs for this worker: no two workers process the same row."""
	token = frappe.generate_hash(length=16)
	now = now_datetime()
	frappe.db.sql(
		"""UPDATE `tabTEX Integration Outbox` SET claim_token=%(t)s, claimed_until=%(u)s
		   WHERE kind=%(k)s AND status IN ('Pending', 'Failed') AND next_attempt_at <= %(n)s
		     AND (claim_token IS NULL OR claimed_until < %(n)s)
		     AND (%(c)s IS NULL OR connection=%(c)s)
		   ORDER BY creation ASC LIMIT %(l)s""",
		{"t": token, "u": add_to_date(now, minutes=CLAIM_MINUTES), "k": kind, "n": now, "l": int(limit),
		 "c": connection})
	_commit()                                    # the claim must be visible to other workers at once
	return frappe.get_all("TEX Integration Outbox", filters={"claim_token": token}, pluck="name",
	                      order_by="creation asc")


def _finish(row, *, ok: bool, error: str | None = None, retryable: bool = True) -> None:
	values = {"claim_token": None, "claimed_until": None}
	if ok:
		values.update(status="Sent", sent_at=now_datetime(), last_error=None)
	else:
		attempts = int(row.attempts or 0) + 1
		values.update(attempts=attempts, last_error=redact_text(error or "")[:500],
		              status="Dead" if (not retryable or attempts >= MAX_ATTEMPTS) else "Failed",
		              next_attempt_at=add_to_date(now_datetime(), minutes=min(2 ** attempts, 720)))
	frappe.db.set_value("TEX Integration Outbox", row.name, values, update_modified=False)


def push_job(name: str) -> dict:
	"""Push one claimed ARI job (the days that changed since the channel last accepted)."""
	row = frappe.get_doc("TEX Integration Outbox", name)
	p = json.loads(row.payload or "{}")
	conn = frappe.get_doc("TEX Integration Connection", row.connection)
	if not conn.enabled or not frappe.db.exists("TEX Channel Mapping", p.get("mapping")):
		_finish(row, ok=True)                    # nothing to do any more: the connection or mapping is gone
		return {"skipped": True}
	m = frappe.get_doc("TEX Channel Mapping", p["mapping"])
	lo, hi = _horizon(m)
	a, b = max(getdate(p["from"]), lo), min(getdate(p["to"]), hi)
	days = build_days(m, a, b) if a <= b else []
	todo = ari_math.changed(days, pushed_state(m.name, a, b)) if not p.get("force") else days
	if not todo:
		_finish(row, ok=True)
		return {"pushed": 0}
	runs = ari_math.runs(m.external_room_code, m.external_rate_code, todo)
	result = adapter_for(conn).push_ari(runs)
	if not result.ok:
		raise AdapterError(result.message or "the channel refused the update", retryable=result.retryable)
	_accept(m, todo)
	_finish(row, ok=True)
	conn.db_set({"last_sync_at": now_datetime(), "last_status": "Sent", "last_error": None}, update_modified=False)
	audit("channel.ari_push", reference_doctype="TEX Channel Mapping", reference_name=m.name, property=m.property,
	      new={"days": len(todo), "runs": len(runs), "from": str(a), "to": str(b), "ref": result.provider_ref},
	      source="Scheduler")
	return {"pushed": len(todo), "runs": len(runs)}


def _push_failed(name: str, e: Exception) -> None:
	row = frappe.get_doc("TEX Integration Outbox", name)
	_finish(row, ok=False, error=str(e), retryable=getattr(e, "retryable", True))
	frappe.db.set_value("TEX Integration Connection", row.connection,
	                    {"last_sync_at": now_datetime(), "last_status": "Failed",
	                     "last_error": redact_text(str(e))[:500]}, update_modified=False)


def deliver_ari(limit: int = 20, connection: str | None = None) -> dict:
	"""Scheduler: push claimed ARI jobs, one unit of work per job."""
	done, failed = _each(claim("ARI", limit, connection), push_job, _push_failed)
	return {"pushed": done, "failed": failed}


def channel_properties() -> list[str]:
	"""Hotels with an enabled channel-manager connection."""
	return sorted({c.property for c in frappe.get_all("TEX Integration Connection", filters={
		"category": CATEGORY, "enabled": 1}, fields=["property"]) if c.property})


def daily_resync() -> int:
	"""Scheduler (daily): changes no event reports — an allotment released by time, a new day
	entering the horizon, FX, markups, a scheduled contract going live — reach the
	channels because the whole horizon is compared again (only differences are pushed)."""
	n = 0
	for prop in channel_properties():
		n += mark_dirty(prop, reason="daily resync")
	return n


def allotment_boundaries(today: date | None = None) -> int:
	"""Scheduler (just after the site's midnight): the nights whose allotment release or cutoff
	starts today are queued for the channels at once, instead of waiting for the daily resync
	(G-49 review). A night is released from the day ``night - max(release, cutoff) + 1`` and cut
	off from ``night - cutoff + 1`` (``inventory_math.Allotment``), both on the site's day."""
	today = getdate(today or now_datetime())
	n = 0
	for prop in channel_properties():
		for a in frappe.get_all("TEX Allotment", filters={"property": prop, "disabled": 0,
		                                                   "date_to": (">=", today)},
		                        fields=["room_type", "date_from", "date_to", "release_days", "cutoff_days"]):
			release, cutoff = int(a.release_days or 0), int(a.cutoff_days or 0)
			for days in {max(release, cutoff), cutoff} - {0}:
				night = today + timedelta(days=days - 1)
				if getdate(a.date_from) <= night <= getdate(a.date_to):
					n += mark_dirty(prop, [a.room_type], night, night, reason="allotment boundary")
	return n


def restriction_boundaries(today: date | None = None) -> int:
	"""Scheduler (just after the site's midnight): the days whose sale-date restrictions change
	today are queued for the channels at once (G-48): a booking window opening today
	(``book_from``) or closed since yesterday (``book_to``), and an arrival entering its release
	or minimum-advance period or its maximum-advance window today. The daily resync compares the
	whole horizon later anyway; this sends the change at midnight. Days close together are one
	range; days far apart are queued each on their own, never every day between them (review L5)."""
	today = getdate(today or now_datetime())
	n = 0
	for prop in channel_properties():
		# only the cells with a sale-date rule
		rows = frappe.get_all("TEX ARI Restriction", filters={"property": prop, "restriction_date": (">=", today)},
		                      or_filters={"book_from": ("is", "set"), "book_to": ("is", "set"),
		                                  "release_days": (">", 0), "min_advance": (">", 0), "max_advance": (">", 0)},
		                      fields=["room_type", "restriction_date", "book_from", "book_to", "release_days",
		                              "min_advance", "max_advance"])
		due: dict[str | None, set[date]] = {}
		for r in rows:
			day = getdate(r.restriction_date)
			lead = (day - today).days
			if ((r.book_from and getdate(r.book_from) == today)
			        or (r.book_to and getdate(r.book_to) == today - timedelta(days=1))
			        or any(v and lead == int(v) - 1 for v in (r.release_days, r.min_advance))
			        or (r.max_advance and lead == int(r.max_advance))):
				due.setdefault(r.room_type or None, set()).add(day)
		for room_type, days in sorted(due.items(), key=lambda kv: kv[0] or ""):
			for lo, hi in clusters(days):
				n += mark_dirty(prop, [room_type] if room_type else None, lo, hi, reason="restriction boundary")
	return n


def clusters(days, gap: int = COALESCE_GAP_DAYS) -> list[tuple[date, date]]:
	"""Days as ranges: a day at most ``gap`` days after the previous one joins its range."""
	out: list[list[date]] = []
	for d in sorted(days):
		if out and (d - out[-1][1]).days <= gap:
			out[-1][1] = d
		else:
			out.append([d, d])
	return [(lo, hi) for lo, hi in out]


# ─── inbound ─────────────────────────────────────────────────────────────


def _key(conn: str, r) -> str:
	body = json.dumps(_normalised(r), sort_keys=True, default=str)
	return hashlib.sha256(f"{conn}|{r.provider_ref}|{r.status}|{body}".encode()).hexdigest()[:40]


def _normalised(r) -> dict:
	return {"provider_ref": r.provider_ref, "status": r.status, "channel_name": r.channel_name, "notes": r.notes,
	        "version": r.version,
	        "guest": ({"first_name": r.guest.first_name, "last_name": r.guest.last_name, "email": r.guest.email,
	                   "phone": r.guest.phone, "country": r.guest.country} if r.guest else None),
	        "rooms": [{"room_code": x.room_code, "rate_code": x.rate_code, "check_in": x.check_in.isoformat(),
	                   "check_out": x.check_out.isoformat(), "adults": x.adults, "children_ages": list(x.children_ages),
	                   "total": str(x.total), "currency": x.currency, "line_ref": x.line_ref} for x in r.rooms]}


def receive(connection: str, headers: dict, body: bytes) -> dict:
	"""The webhook: authentic messages are stored once, applied later by the queue."""
	conn = frappe.db.get_value("TEX Integration Connection", connection,
	                           ["name", "category", "enabled", "property", "adapter", "environment", "settings_json"],
	                           as_dict=True)
	if not conn or conn.category != CATEGORY or not conn.enabled:
		frappe.throw(_("Unknown channel connection."), frappe.PermissionError)
	doc = frappe.get_doc("TEX Integration Connection", conn.name)
	adapter = adapter_for(doc)
	try:
		adapter.verify_webhook(headers, body, int(now_datetime().timestamp()))
	except signing.SignatureError as e:
		audit("channel.webhook_rejected", reference_doctype="TEX Integration Connection", reference_name=conn.name,
		      property=conn.property, reason=str(e), source="Webhook")
		_commit()                                # keep the refusal on record; the request then fails
		frappe.throw(_("Invalid signature."), frappe.PermissionError)
	try:
		items = adapter.parse_webhook(body)
	except AdapterError as e:
		frappe.throw(_("Invalid booking message: {0}").format(str(e)))
	stored = dup = 0
	for r in items:
		key = _key(conn.name, r)
		if frappe.db.exists("TEX Channel Inbound", {"idempotency_key": key}):
			dup += 1
			continue
		try:
			frappe.get_doc({"doctype": "TEX Channel Inbound", "connection": conn.name, "property": conn.property,
			                "provider_ref": r.provider_ref, "event": r.status, "status": "Received", "attempts": 0,
			                "next_attempt_at": now_datetime(), "received_at": now_datetime(), "idempotency_key": key,
			                "payload": json.dumps(_normalised(r), sort_keys=True)}).insert(ignore_permissions=True)
		except frappe.UniqueValidationError:     # the same message arriving twice at once (unique key)
			frappe.clear_last_message()
			dup += 1
			continue
		stored += 1
	audit("channel.webhook", reference_doctype="TEX Integration Connection", reference_name=conn.name,
	      property=conn.property, new={"stored": stored, "duplicates": dup}, source="Webhook")
	return {"received": stored, "duplicates": dup}


def _claim_inbound(limit: int, connection: str | None = None) -> list[str]:
	now = now_datetime()
	filters = {"status": ("in", ["Received", "Failed"])}
	if connection:
		filters["connection"] = connection
	# a message stored without a next attempt (every TEX path sets one) is due now
	rows = frappe.get_all("TEX Channel Inbound", filters=filters,
	                      or_filters=[["next_attempt_at", "is", "not set"], ["next_attempt_at", "<=", now]],
	                      fields=["name", "connection", "provider_ref"], order_by="creation asc", limit=limit)
	out, blocked = [], set()
	for r in rows:
		key = (r.connection, r.provider_ref)
		if key in blocked:
			continue
		# a booking's messages apply in the order received: an older one still pending blocks it
		older = frappe.db.sql(
			"""SELECT name FROM `tabTEX Channel Inbound` WHERE connection=%s AND provider_ref=%s
			   AND status IN ('Received', 'Failed') AND creation < (SELECT creation FROM `tabTEX Channel Inbound`
			   WHERE name=%s) LIMIT 1""", (r.connection, r.provider_ref, r.name))
		if older:
			blocked.add(key)
			continue
		out.append(r.name)
		blocked.add(key)                         # one message per booking per run
	return out


def apply_inbound(name: str) -> dict:
	from kamra.tex.distribution import channel_booking

	# a second worker holding the same message waits here, then finds it done: applied once
	state = frappe.db.sql("SELECT status FROM `tabTEX Channel Inbound` WHERE name=%s FOR UPDATE", name)
	if not state or state[0][0] not in ("Received", "Failed"):
		return {"status": state[0][0] if state else None, "skipped": True}
	row = frappe.get_doc("TEX Channel Inbound", name)
	out = channel_booking.apply(row)
	frappe.db.set_value("TEX Channel Inbound", name, {
		"status": out.get("status", "Applied"), "applied_at": now_datetime(), "booking": out.get("booking"),
		"warning": out.get("warning"), "last_error": None}, update_modified=False)
	return out


def _inbound_failed(name: str, e: Exception) -> None:
	attempts = int(frappe.db.get_value("TEX Channel Inbound", name, "attempts") or 0) + 1
	retryable = getattr(e, "retryable", True)
	frappe.db.set_value("TEX Channel Inbound", name, {
		"attempts": attempts, "last_error": redact_text(str(e))[:500],
		"status": "Dead" if (not retryable or attempts >= MAX_ATTEMPTS) else "Failed",
		"next_attempt_at": add_to_date(now_datetime(), minutes=min(2 ** attempts, 720))}, update_modified=False)


def process_inbound(limit: int = 20, connection: str | None = None) -> dict:
	"""Scheduler: apply received channel bookings, one unit of work each, in order."""
	applied, failed = _each(_claim_inbound(limit, connection), apply_inbound, _inbound_failed)
	return {"applied": applied, "failed": failed}


# ─── reconciliation ──────────────────────────────────────────────────────


def reconcile(connection: str) -> list[Mismatch]:
	"""Compare what the channel has with what TEX has: ARI drift (TEX now vs last accepted)
	and bookings (the channel's view — asked from the provider when it can answer, else the
	latest message received — vs TEX's bookings for this connection)."""
	conn = frappe.get_doc("TEX Integration Connection", connection)
	out: list[Mismatch] = []
	for m in frappe.get_all("TEX Channel Mapping", filters={"connection": connection, "enabled": 1}, pluck="name"):
		doc = frappe.get_doc("TEX Channel Mapping", m)
		lo, hi = _horizon(doc)
		pushed = pushed_state(m, lo, hi)
		for d in build_days(doc, lo, hi):
			if pushed.get(d.day) != d.fingerprint():
				out.append(Mismatch("ari_drift", f"{doc.external_room_code}/{doc.external_rate_code}/{d.day}",
				                    {"mapping": m, "date": str(d.day), "pushed": bool(pushed.get(d.day))}))
	channel_view = adapter_for(conn).fetch_reservations(None)
	latest: dict[str, dict] = {}
	if channel_view is not None:
		latest = {r.provider_ref: _normalised(r) for r in channel_view}
	else:
		for r in frappe.get_all("TEX Channel Inbound", filters={"connection": connection},
		                        fields=["provider_ref", "payload", "status"], order_by="creation asc"):
			if r.status != "Ignored":
				latest[r.provider_ref] = {**json.loads(r.payload or "{}"), "_inbound_status": r.status}
	tex = {b.external_ref: b for b in frappe.get_all("TEX Booking", filters={"channel_connection": connection},
	                                                  fields=["name", "external_ref", "status", "total_amount",
	                                                          "currency"])}
	for ref, c in latest.items():
		b = tex.get(ref)
		if not b:
			if c.get("status") != "cancelled":
				out.append(Mismatch("missing_in_tex", ref, {"inbound_status": c.get("_inbound_status")}))
			continue
		if (c.get("status") == "cancelled") != (b.status == "Cancelled"):
			out.append(Mismatch("status_differs", ref, {"channel": c.get("status"), "tex": b.status, "booking": b.name}))
		elif c.get("status") != "cancelled":
			total = sum((D(x["total"]) for x in c.get("rooms") or []), D(0))
			if total != D(str(b.total_amount or 0)):
				out.append(Mismatch("total_differs", ref, {"channel": str(total), "tex": str(b.total_amount),
				                                           "booking": b.name}))
	for ref, b in tex.items():
		if ref not in latest:
			out.append(Mismatch("missing_in_channel", ref, {"booking": b.name, "status": b.status}))
	audit("channel.reconcile", reference_doctype="TEX Integration Connection", reference_name=connection,
	      property=conn.property, new={"mismatches": len(out),
	                                   "kinds": sorted({x.kind for x in out})})
	return out
