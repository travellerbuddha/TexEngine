"""TEX Connect distribution API (G-69, ADR-039).

``webhook`` is the only guest-reachable endpoint: rate limited, signature-verified by the
connection's adapter (fail closed), stores messages once and answers fast; bookings are
applied by the queue. Everything else needs ``channel.view`` / ``channel.manage`` at the
connection's hotel.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import getdate, now_datetime

from kamra.tex.api._util import as_int, parse, text
from kamra.tex.distribution import repository as dist
from kamra.tex.security import scope
from kamra.tex.security.audit import audit

MAPPING_FIELDS = ("connection", "enabled", "room_type", "external_room_code", "external_rate_code", "board",
                  "rate_plan", "market", "sales_channel", "contract", "sell_currency", "occupancies", "horizon_days")


def _conn(name: str, cap: str):
	conn = frappe.get_doc("TEX Integration Connection", name)
	if conn.category != dist.CATEGORY:
		frappe.throw(_("{0} is not a channel connection.").format(name))
	scope.require(cap, conn.property)
	return conn


# ─── webhook ─────────────────────────────────────────────────────────────


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=120, seconds=60)
def webhook(connection: str):
	"""Booking messages from a channel manager: /api/method/kamra.tex.api.distribution.webhook?connection=CON-…"""
	req = frappe.request
	headers = {k: v for k, v in req.headers.items()} if req else {}
	body = req.get_data() if req else b""
	if len(body) > 1_000_000:
		frappe.throw(_("The message is too large."))
	frappe.flags.tex_source = "Webhook"
	out = dist.receive(text(connection, 40) or "", headers, body)
	return {"ok": True, **out}


# ─── connections overview ────────────────────────────────────────────────


@frappe.whitelist()
def overview(property: str):
	scope.require("channel.view", property)
	conns = frappe.get_all("TEX Integration Connection", filters={"property": property, "category": dist.CATEGORY},
	                       fields=["name", "label", "adapter", "enabled", "environment", "last_sync_at",
	                               "last_status", "last_error"], order_by="label asc")
	from kamra.tex.distribution.adapters import REGISTRY

	for c in conns:
		cls = REGISTRY.get(c.adapter)
		c["certified"] = bool(cls and cls.certified)
		c["mappings"] = frappe.db.count("TEX Channel Mapping", {"connection": c.name})
		c["queue"] = {s: frappe.db.count("TEX Integration Outbox", {"connection": c.name, "kind": "ARI", "status": s})
		              for s in ("Pending", "Failed", "Dead")}
		c["inbound"] = {s: frappe.db.count("TEX Channel Inbound", {"connection": c.name, "status": s})
		                for s in ("Received", "Failed", "Dead")}
		c["webhook_url"] = frappe.utils.get_url(
			f"/api/method/kamra.tex.api.distribution.webhook?connection={c.name}", allow_header_override=False)
		for k in ("last_sync_at",):
			c[k] = str(c[k]) if c[k] else None
	return {"connections": conns, "can_manage": scope.has_capability("channel.manage", property)}


# ─── mappings ────────────────────────────────────────────────────────────


@frappe.whitelist()
def mappings(connection: str):
	_conn(connection, "channel.view")
	rows = frappe.get_all("TEX Channel Mapping", filters={"connection": connection},
	                      fields=["name", "property", *MAPPING_FIELDS], order_by="external_room_code asc")
	return rows


@frappe.whitelist()
def lookups(connection: str):
	conn = _conn(connection, "channel.view")
	p = conn.property
	return {
		"room_types": frappe.get_all("Room Type", filters={"property": p, "disabled": 0},
		                             fields=["name", "room_type_name"], order_by="room_type_name asc"),
		"rate_plans": frappe.get_all("Rate Plan", filters={"property": p}, fields=["name", "rate_plan_name"]),
		"markets": frappe.get_all("TEX Market", filters={"disabled": 0}, fields=["name", "market_name"]),
		"channels": frappe.get_all("TEX Sales Channel", filters={"disabled": 0},
		                           fields=["name", "channel_name", "channel_group"]),
		"contracts": frappe.get_all("TEX Contract", filters={"property": p, "status": ("in", ["Active", "Draft"])},
		                            fields=["name", "contract_code", "contract_name", "market", "status"]),
		"currency": frappe.db.get_value("Property", p, "currency"),
		"boards": [b for b in (frappe.get_meta("TEX Board Rule").get_field("board").options or "").split("\n") if b],
		"adapter": {"key": conn.adapter, "environment": conn.environment,
		            "sandbox": conn.adapter == "sandbox_channel" and conn.environment == "Sandbox"},
	}


@frappe.whitelist(methods=["POST"])
def save_mapping(data):
	data = parse(data, {}) or {}
	conn = _conn(data.get("connection") or "", "channel.manage")
	if data.get("name"):
		doc = frappe.get_doc("TEX Channel Mapping", data["name"])
		if doc.connection != conn.name:
			frappe.throw(_("A mapping cannot move to another connection."))
		old = {f: str(doc.get(f)) if doc.get(f) is not None else None for f in MAPPING_FIELDS}
	else:
		doc = frappe.new_doc("TEX Channel Mapping")
		old = None
	for f in MAPPING_FIELDS:
		if f in data:
			doc.set(f, data[f] if data[f] not in ("",) else None)
	doc.property = conn.property
	doc.save(ignore_permissions=True)
	audit("channel.mapping_save", reference_doctype="TEX Channel Mapping", reference_name=doc.name,
	      property=conn.property, old=old, new={f: str(doc.get(f)) if doc.get(f) is not None else None
	                                           for f in MAPPING_FIELDS})
	return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
def delete_mapping(name: str):
	"""Only a disabled mapping whose close-out the channel accepted: otherwise the channel
	would keep selling the last availability TEX sent for it."""
	doc = frappe.get_doc("TEX Channel Mapping", name)
	_conn(doc.connection, "channel.manage")
	if doc.enabled:
		frappe.throw(_("Disable the mapping first: TEX then closes this room and rate on the channel."))
	if not dist.closed_out(doc):
		frappe.throw(_("The channel has not accepted the close-out yet. Send it (Send now) and delete the "
		               "mapping once it is accepted."))
	# its pushed-day state and its ARI jobs mean nothing without it (the audit keeps the record)
	frappe.db.delete("TEX Channel ARI Day", {"mapping": name})
	frappe.db.delete("TEX Integration Outbox", {"kind": "ARI", "reference_doctype": "TEX Channel Mapping",
	                                            "reference_name": name})
	frappe.delete_doc("TEX Channel Mapping", name, ignore_permissions=True)
	audit("channel.mapping_delete", reference_doctype="TEX Channel Mapping", reference_name=name,
	      property=doc.property, old={"room": doc.external_room_code, "rate": doc.external_rate_code})
	return {"ok": True}


# ─── ARI ─────────────────────────────────────────────────────────────────


@frappe.whitelist()
def ari_preview(mapping: str, date_from: str | None = None, days=14):
	"""What TEX would send for a mapping, next to what the channel last accepted."""
	m = frappe.get_doc("TEX Channel Mapping", mapping)
	_conn(m.connection, "channel.view")
	a = getdate(date_from) if date_from else getdate()
	b = frappe.utils.add_days(a, as_int(days, 14, lo=1, hi=62) - 1)
	pushed = dist.pushed_state(m.name, a, getdate(b))
	return {"mapping": m.name, "days": [{**d.to_dict(), "in_sync": pushed.get(d.day) == d.fingerprint(),
	                                     "sent": d.day in pushed} for d in dist.build_days(m, a, getdate(b))]}


@frappe.whitelist(methods=["POST"])
def push_now(connection: str, full=0):
	"""Queue the whole horizon of every mapping; ``full`` sends every day again."""
	conn = _conn(connection, "channel.manage")
	n = dist.mark_dirty(conn.property, reason="manual")
	if as_int(full, 0):
		for row in frappe.get_all("TEX Integration Outbox", filters={"connection": connection, "kind": "ARI",
		                                                             "status": "Pending"}, fields=["name", "payload"]):
			p = json.loads(row.payload or "{}")
			p["force"] = True
			frappe.db.set_value("TEX Integration Outbox", row.name, "payload", json.dumps(p), update_modified=False)
	audit("channel.push_now", reference_doctype="TEX Integration Connection", reference_name=connection,
	      property=conn.property, new={"jobs": n, "full": bool(as_int(full, 0))})
	return {"queued": n}


@frappe.whitelist(methods=["POST"])
def send_now(connection: str):
	"""Send this connection's due ARI jobs now instead of waiting for the queue (a few per call)."""
	conn = _conn(connection, "channel.manage")
	out = dist.deliver_ari(limit=5, connection=conn.name)
	audit("channel.send_now", reference_doctype="TEX Integration Connection", reference_name=conn.name,
	      property=conn.property, new=out)
	return {**out, "waiting": frappe.db.count("TEX Integration Outbox", {"connection": conn.name, "kind": "ARI",
	                                                                      "status": ("in", ["Pending", "Failed"])})}


# ─── inbound ─────────────────────────────────────────────────────────────


@frappe.whitelist()
def inbound(connection: str, status: str | None = None, start=0, limit=50):
	_conn(connection, "channel.view")
	filters = {"connection": connection}
	if status in ("Received", "Applied", "Failed", "Dead", "Ignored"):
		filters["status"] = status
	rows = frappe.get_all("TEX Channel Inbound", filters=filters,
	                      fields=["name", "provider_ref", "event", "status", "attempts", "received_at", "applied_at",
	                              "booking", "warning", "last_error", "payload"],
	                      order_by="creation desc", start=as_int(start, 0, lo=0),
	                      page_length=as_int(limit, 50, lo=1, hi=200))
	see_guest = scope.has_capability("crm.view", frappe.db.get_value("TEX Integration Connection", connection,
	                                                                  "property"))
	for r in rows:
		p = json.loads(r.pop("payload") or "{}")
		r["rooms"] = [{k: x.get(k) for k in ("room_code", "rate_code", "check_in", "check_out", "adults", "total",
		                                     "currency", "line_ref")} for x in p.get("rooms") or []]
		r["guest_name"] = (" ".join(x for x in ((p.get("guest") or {}).get("first_name"),
		                                        (p.get("guest") or {}).get("last_name")) if x)
		                   if see_guest else None)
		for k in ("received_at", "applied_at"):
			r[k] = str(r[k]) if r[k] else None
	return {"rows": rows, "total": frappe.db.count("TEX Channel Inbound", filters)}


@frappe.whitelist(methods=["POST"])
def retry_inbound(name: str):
	row = frappe.get_doc("TEX Channel Inbound", name)
	_conn(row.connection, "channel.manage")
	if row.status not in ("Failed", "Dead"):
		frappe.throw(_("Only failed messages can be retried."))
	frappe.db.set_value("TEX Channel Inbound", name, {"status": "Received", "attempts": 0,
	                                                  "next_attempt_at": now_datetime()}, update_modified=False)
	audit("channel.inbound_retry", reference_doctype="TEX Channel Inbound", reference_name=name, property=row.property)
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def apply_now(connection: str):
	"""Apply this connection's received booking messages now instead of waiting for the queue."""
	conn = _conn(connection, "channel.manage")
	out = dist.process_inbound(limit=50, connection=conn.name)
	audit("channel.apply_now", reference_doctype="TEX Integration Connection", reference_name=conn.name,
	      property=conn.property, new=out)
	return out


@frappe.whitelist(methods=["POST"])
def sandbox_send(connection: str, message):
	"""Sandbox only: sign ``message`` (TEX's neutral booking format) with the connection's
	secret and receive it as the channel would send it — to try the flow without a channel."""
	conn = _conn(connection, "channel.manage")
	if conn.adapter != "sandbox_channel" or conn.environment != "Sandbox":
		frappe.throw(_("Only a sandbox channel connection can simulate bookings."))
	from kamra.tex.distribution import signing

	body = json.dumps(parse(message, {}) or {}, sort_keys=True).encode()
	ts = int(now_datetime().timestamp())
	secret = conn.get_password("secret", raise_exception=False)
	if not secret:
		frappe.throw(_("Set the connection's secret first: messages are verified with it."))
	out = dist.receive(conn.name, {"X-TEX-Timestamp": str(ts), "X-TEX-Signature": signing.sign(secret, ts, body)},
	                   body)
	return out


# ─── reconciliation ──────────────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def reconcile(connection: str):
	_conn(connection, "channel.view")
	found = dist.reconcile(connection)
	return {"mismatches": [{"kind": m.kind, "key": m.key, **m.detail} for m in found[:500]], "total": len(found)}
