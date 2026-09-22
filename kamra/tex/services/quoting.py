"""Search → offers → quotes (ADR-009, R-24, R-45).

``search`` prices every sellable room / rate plan / board for each requested room
party across the permitted hotels and returns offers carrying an HMAC-signed
``offer_key`` — no database writes. ``create_quote`` re-prices an offer
server-side and persists an authoritative ``TEX Quote``; a price that moved since
the search is reported, never hidden.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, getdate, now_datetime

from kamra.tex.availability import repository as avail
from kamra.tex.availability.restrictions import RestrictionScope
from kamra.tex.commercial import context as ctxmod
from kamra.tex.commercial import contracts
from kamra.tex.money import D, to_str
from kamra.tex.pricing import engine, serialize
from kamra.tex.pricing.model import ChildSpec, ExtraRequest, PricingError, StayRequest, Unsellable

MAX_ROOMS = 8


# ─── signing ─────────────────────────────────────────────────────────────


def _secret() -> bytes:
	key = frappe.local.conf.get("encryption_key") or frappe.local.site
	return hashlib.sha256(("tex-offer:" + str(key)).encode()).digest()


def sign(payload: dict) -> str:
	body = serialize.canonical_json(payload).encode()
	mac = hmac.new(_secret(), body, hashlib.sha256).digest()
	return base64.urlsafe_b64encode(body).decode().rstrip("=") + "." + \
		base64.urlsafe_b64encode(mac).decode().rstrip("=")


def verify(token: str) -> dict:
	try:
		body_b64, mac_b64 = token.split(".", 1)
		pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
		body = base64.urlsafe_b64decode(pad(body_b64))
		mac = base64.urlsafe_b64decode(pad(mac_b64))
	except Exception:
		frappe.throw(_("Invalid offer."), frappe.ValidationError)
	if not hmac.compare_digest(hmac.new(_secret(), body, hashlib.sha256).digest(), mac):
		frappe.throw(_("Invalid offer."), frappe.ValidationError)
	data = json.loads(body)
	if data.get("exp") and get_datetime(data["exp"]) < now_datetime():
		frappe.throw(_("This offer has expired — please search again."), frappe.ValidationError)
	return data


# ─── request helpers ─────────────────────────────────────────────────────


@dataclass
class Party:
	adults: int
	children: list[ChildSpec] = field(default_factory=list)

	@classmethod
	def parse(cls, raw) -> Party:
		raw = raw or {}
		adults = int(raw.get("adults") or 0)
		kids = []
		for c in raw.get("children") or []:
			if isinstance(c, dict):
				kids.append(ChildSpec(age=int(c["age"]) if c.get("age") not in (None, "") else None,
				                      dob=getdate(c["dob"]) if c.get("dob") else None))
			else:
				kids.append(ChildSpec(age=int(c)))
		if adults < 1 or adults > 12 or len(kids) > 8:
			frappe.throw(_("Each room needs 1–12 adults and at most 8 children."))
		for k in kids:
			if k.age is None and k.dob is None:
				frappe.throw(_("Each child needs an age."))
			if k.age is not None and not (0 <= k.age <= 17):
				frappe.throw(_("Child ages must be 0–17."))
		return cls(adults, kids)

	def key(self) -> dict:
		return {"adults": self.adults, "children": [{"age": c.age, "dob": c.dob.isoformat() if c.dob else None}
		                                            for c in self.children]}


def parse_rooms(rooms) -> list[Party]:
	if isinstance(rooms, str):
		rooms = json.loads(rooms)
	if not rooms:
		frappe.throw(_("At least one room is required."))
	if len(rooms) > MAX_ROOMS:
		frappe.throw(_("At most {0} rooms per booking.").format(MAX_ROOMS))
	return [Party.parse(r) for r in rooms]


def _dates(check_in, check_out) -> tuple[date, date]:
	ci, co = getdate(check_in), getdate(check_out)
	if co <= ci:
		frappe.throw(_("Check-out must be after check-in."))
	if (co - ci).days > engine.MAX_NIGHTS:
		frappe.throw(_("Stays longer than {0} nights are booked by the reservations team.").format(engine.MAX_NIGHTS))
	if ci < getdate(now_datetime()):
		frappe.throw(_("Check-in cannot be in the past."))
	return ci, co


def _boards_of(terms) -> list[str]:
	return sorted({b.board for b in terms.boards}, key=lambda b: ["RO", "BB", "HB", "FB", "AI", "UAI"].index(b)
	              if b in ("RO", "BB", "HB", "FB", "AI", "UAI") else 99)


def _ttl(field_: str, default: int) -> int:
	try:
		return int(frappe.db.get_single_value("TEX Settings", field_) or default)
	except Exception:
		return default


def build_request(*, property, room_type, board, rate_plan, check_in, check_out, party: Party, sale_at, market,
                  channel, currency, promo_codes=(), member=False, extras=()) -> StayRequest:
	return StayRequest(property=property, room_type=room_type, board=board, rate_plan=rate_plan, check_in=check_in,
	                   check_out=check_out, adults=party.adults, children=tuple(party.children), sale_at=sale_at,
	                   market=market, channel=channel, sell_currency=currency.upper(),
	                   promo_codes=tuple(sorted({c.strip().upper() for c in promo_codes if c and c.strip()})),
	                   member=member, extras=tuple(extras))


# ─── search ──────────────────────────────────────────────────────────────


def _room_content(room_types: list[str]) -> dict[str, dict]:
	if not room_types:
		return {}
	rows = frappe.get_all("Room Type", filters={"name": ("in", room_types)},
	                      fields=["name", "room_type_name", "description", "bed_type", "room_view", "amenities",
	                              "tex_size_sqm", "tex_beds", "image", "adults_capacity", "children_capacity"])
	return {r.name: r for r in rows}


def search_property(property: str, *, check_in: date, check_out: date, parties: list[Party], market: str,
                    channel: str, currency: str | None, promo_codes=(), member=False, sale_at: datetime | None = None,
                    internal: bool = False, room_type: str | None = None) -> dict:
	"""All offers of one hotel. ``internal`` adds cost/margin + explanation."""
	sale_at = sale_at or now_datetime()
	result = {"property": property, "offers": [], "unavailable": [], "messages": []}
	cands = contracts.candidate_contracts(property, market, channel, sale_at)
	if not cands:
		result["messages"].append(_("No contract sells this hotel for market {0} on {1}.").format(market, channel))
		return result
	offer_exp = add_to_date(now_datetime(), minutes=_ttl("offer_ttl_minutes", 20))
	cells = avail.restriction_cells(property, check_in, check_out)
	sale_date = sale_at.date()
	seen_rooms: set[str] = set()
	ctx_cache: dict[tuple, object] = {}

	for contract_row, version in cands:
		terms = contracts.load_terms(version)
		sell_ccy = (currency or contract_row.sell_currency or terms.currency).upper()
		room_types = [room_type] if room_type else sorted(terms.rooms)
		for rt in room_types:
			if rt not in terms.rooms:
				continue
			# the first (market-specific, then highest-priority) contract selling a room wins
			if rt in seen_rooms:
				continue
			count, per_day = avail.stay_availability(property, rt, contract_row.name, check_in, check_out, sale_date)
			rate_plans = sorted(terms.rate_plans) or [None]
			boards = _boards_of(terms)
			for rp in rate_plans:
				scope = RestrictionScope(room_type=rt, contract=contract_row.name, market=market, rate_plan=rp,
				                         channel=channel)
				violations = avail.check_restrictions(property, scope, check_in, check_out, sale_date, cells)
				for board in boards:
					rooms_out = []
					sellable = True
					reasons = []
					for idx, party in enumerate(parties):
						req = build_request(property=property, room_type=rt, board=board, rate_plan=rp,
						                    check_in=check_in, check_out=check_out, party=party, sale_at=sale_at,
						                    market=market, channel=channel, currency=sell_ccy,
						                    promo_codes=promo_codes, member=member)
						key = (version, sell_ccy, rt)
						try:
							if key not in ctx_cache:
								ctx_cache[key] = ctxmod.build_context(terms, req, extras={})
							q = engine.price_stay(ctx_cache[key], req)
						except Unsellable as u:
							sellable, reasons = False, [{"code": u.code, "message": u.message}]
							break
						except PricingError as e:
							sellable, reasons = False, [{"code": "PRICING_ERROR", "message": str(e)}]
							break
						if not q.sellable:
							sellable, reasons = False, q.reasons
							break
						offer = {"v": 1, "property": property, "room_type": rt, "board": board, "rate_plan": rp,
						         "contract": contract_row.name, "version": version, "check_in": check_in.isoformat(),
						         "check_out": check_out.isoformat(), "party": party.key(), "market": market,
						         "channel": channel, "currency": sell_ccy, "promo_codes": list(req.promo_codes),
						         "member": bool(member), "total": to_str(q.total), "room_index": idx,
						         "exp": offer_exp.isoformat()}
						rooms_out.append({"room_index": idx, "offer_key": sign(offer),
						                  "quote": q.to_dict(internal=internal)})
					entry = {
						"room_type": rt, "board": board, "rate_plan": rp, "contract": contract_row.name,
						"contract_code": contract_row.contract_code, "market": terms.market,
						"version": version, "currency": sell_ccy,
						"available": count, "availability": [asdict(d) | {"day": d.day.isoformat()}
						                                     for d in per_day] if internal else None,
						"restrictions": [v.to_dict() for v in violations],
						"rooms": rooms_out,
					}
					bookable = sellable and not violations and count >= len(parties)
					if sellable:
						entry["total"] = to_str(sum(D(r["quote"]["totals"]["total"]) for r in rooms_out))
						rp_info = rooms_out[0]["quote"].get("rate_plan") if rooms_out else None
						entry["refundable"] = bool(rp_info["refundable"]) if rp_info else True
						entry["rate_plan_info"] = rp_info
					entry["bookable"] = bookable
					if not sellable:
						entry["reasons"] = reasons
					elif count < len(parties):
						entry["reasons"] = [{"code": "SOLD_OUT", "message": _("Not enough rooms available")}]
					elif violations:
						entry["reasons"] = [{"code": v.code, "message": v.message} for v in violations]
					(result["offers"] if bookable else result["unavailable"]).append(entry)
			seen_rooms.add(rt)

	content = _room_content(sorted({o["room_type"] for o in result["offers"] + result["unavailable"]}))
	result["rooms"] = {k: {"name": v.room_type_name, "description": v.description, "bed_type": v.bed_type,
	                       "beds": v.tex_beds, "size_sqm": v.tex_size_sqm, "view": v.room_view,
	                       "amenities": [a.strip() for a in (v.amenities or "").replace("\n", ",").split(",")
	                                     if a.strip()], "image": v.image,
	                       "max_adults": v.adults_capacity, "max_children": v.children_capacity}
	                   for k, v in content.items()}
	result["offers"].sort(key=lambda o: (D(o["total"]), o["room_type"], o["board"], o.get("rate_plan") or ""))
	return result


def search(*, properties: list[str], check_in, check_out, rooms, market: str, channel: str,
           currency: str | None = None, promo_codes=(), member=False, internal=False,
           sale_at: datetime | None = None) -> dict:
	ci, co = _dates(check_in, check_out)
	parties = parse_rooms(rooms)
	market = (market or "").upper()
	if not frappe.db.exists("TEX Market", market):
		frappe.throw(_("Unknown market {0}.").format(market))
	if not frappe.db.exists("TEX Sales Channel", channel):
		frappe.throw(_("Unknown sales channel {0}.").format(channel))
	out = []
	for p in properties:
		res = search_property(p, check_in=ci, check_out=co, parties=parties, market=market, channel=channel,
		                      currency=currency, promo_codes=promo_codes, member=member, internal=internal,
		                      sale_at=sale_at)
		prop = frappe.db.get_value("Property", p, ["property_name", "city", "star_category"], as_dict=True) or {}
		res.update({"property_name": prop.get("property_name"), "city": prop.get("city"),
		            "star_category": prop.get("star_category")})
		if res["offers"]:
			res["from_total"] = min(o["total"] for o in res["offers"]) if res["offers"] else None
		out.append(res)
	out.sort(key=lambda r: (not r["offers"], D(r.get("from_total") or 0)))
	return {"check_in": ci.isoformat(), "check_out": co.isoformat(), "nights": (co - ci).days, "market": market,
	        "channel": channel, "rooms": [p.key() for p in parties], "properties": out}


# ─── quotes ──────────────────────────────────────────────────────────────


def request_from_offer(offer: dict, *, sale_at: datetime, extras=(), promo_codes=None) -> StayRequest:
	party = Party.parse(offer["party"])
	return build_request(property=offer["property"], room_type=offer["room_type"], board=offer["board"],
	                     rate_plan=offer.get("rate_plan"), check_in=getdate(offer["check_in"]),
	                     check_out=getdate(offer["check_out"]), party=party, sale_at=sale_at,
	                     market=offer["market"], channel=offer["channel"], currency=offer["currency"],
	                     promo_codes=offer.get("promo_codes") if promo_codes is None else promo_codes,
	                     member=bool(offer.get("member")), extras=extras)


def price_request(version: str, req: StayRequest, *, gkey: str | None = None, extras_catalog=None):
	terms = contracts.load_terms(version)
	ctx = ctxmod.build_context(terms, req, gkey=gkey, extras=extras_catalog)
	return engine.price_stay(ctx, req), terms


def _extras_list(extras) -> tuple[ExtraRequest, ...]:
	if isinstance(extras, str):
		extras = json.loads(extras or "[]")
	out = []
	for e in extras or []:
		qty = int(e.get("quantity") or 1)
		if qty < 1 or qty > 99:
			frappe.throw(_("Invalid extra quantity."))
		out.append(ExtraRequest(code=str(e["code"]).upper(), quantity=qty,
		                        service_dates=tuple(getdate(d) for d in e.get("service_dates") or [])))
	return tuple(out)


def create_quote(offer_key: str, *, extras=None, promo_codes=None, guest_email: str | None = None,
                 session_id: str | None = None) -> dict:
	offer = verify(offer_key)
	now = now_datetime()
	extras_req = _extras_list(extras)
	req = request_from_offer(offer, sale_at=now, extras=extras_req, promo_codes=promo_codes)
	gkey = ctxmod.guest_key(guest_email)
	# the offer's contract version might have been superseded since the search:
	# quotes always price on the version on sale NOW
	live = contracts.active_version_header(offer["contract"], now)
	if not live:
		frappe.throw(_("This rate is no longer on sale — please search again."))
	q, terms = price_request(live.version_id, req, gkey=gkey)
	if not q.sellable:
		return {"ok": False, "reasons": q.reasons}
	avail_count, _days = avail.stay_availability(req.property, req.room_type, offer["contract"], req.check_in,
	                                            req.check_out, now.date())
	if avail_count < 1:
		return {"ok": False, "reasons": [{"code": "SOLD_OUT", "message": _("This room has just sold out.")}]}
	scope = RestrictionScope(room_type=req.room_type, contract=offer["contract"], market=req.market,
	                         rate_plan=req.rate_plan, channel=req.channel)
	violations = avail.check_restrictions(req.property, scope, req.check_in, req.check_out, now.date())
	if violations:
		return {"ok": False, "reasons": [v.to_dict() for v in violations]}

	result = q.to_dict(internal=True)
	doc = frappe.get_doc({
		"doctype": "TEX Quote", "property": req.property, "status": "Open", "sales_channel": req.channel,
		"market": req.market, "currency": q.currency, "total_amount": q.total,
		"contract_version": live.version_id, "payload_hash": terms.payload_hash,
		"expires_at": add_to_date(now, minutes=_ttl("quote_ttl_minutes", 30)),
		"session_hash": hashlib.sha256(session_id.encode()).hexdigest()[:32] if session_id else None,
		"offer_hash": hashlib.sha256(offer_key.encode()).hexdigest()[:32],
		"request_json": json.dumps(serialize.request_to_dict(req), sort_keys=True),
		"result_json": json.dumps(result, sort_keys=True, ensure_ascii=False),
	})
	doc.insert(ignore_permissions=True)
	price_changed = to_str(q.total) != offer.get("total") and not extras_req and promo_codes is None
	return {"ok": True, "quote_id": doc.name, "expires_at": str(doc.expires_at), "price_changed": price_changed,
	        "previous_total": offer.get("total"), "quote": q.to_dict(internal=False),
	        "room_index": offer.get("room_index", 0)}


def load_quote(quote_id: str, *, for_update: bool = False) -> tuple[dict, dict, dict]:
	row = frappe.db.get_value("TEX Quote", quote_id, ["name", "status", "expires_at", "request_json",
	                                                  "result_json", "contract_version", "property"],
	                          as_dict=True, for_update=for_update)
	if not row:
		frappe.throw(_("Quote {0} not found.").format(quote_id), frappe.DoesNotExistError)
	return row, json.loads(row.request_json), json.loads(row.result_json)


def quote_is_usable(row) -> str | None:
	if row.status != "Open":
		return _("This quote was already used.")
	if get_datetime(row.expires_at) < now_datetime():
		return _("This quote has expired — please search again.")
	return None


def default_sale_window(check_in: date) -> timedelta:
	return timedelta(days=max(0, (check_in - getdate(now_datetime())).days))
