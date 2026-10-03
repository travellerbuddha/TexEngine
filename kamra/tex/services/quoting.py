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
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, getdate, now_datetime

from kamra.tex.availability import repository as avail
from kamra.tex.commercial import context as ctxmod
from kamra.tex.commercial import contracts
from kamra.tex.money import D, quantize, to_str
from kamra.tex.pricing import ages, engine, promotions, serialize
from kamra.tex.pricing.model import ChildSpec, ExtraRequest, PricingError, StayRequest, Unsellable
from kamra.tex.security.keys import site_secret
from kamra.tex.services.refusals import Refusal, refusal

MAX_ROOMS = 8


# ─── signing ─────────────────────────────────────────────────────────────


def _secret() -> bytes:
	# the site key, never the public site name (G-89): same value as before for a keyed site
	return hashlib.sha256(site_secret("tex-offer").encode()).digest()


def sign(payload: dict) -> str:
	body = serialize.canonical_json(payload).encode()
	mac = hmac.new(_secret(), body, hashlib.sha256).digest()
	return base64.urlsafe_b64encode(body).decode().rstrip("=") + "." + \
		base64.urlsafe_b64encode(mac).decode().rstrip("=")


def verify(token: str, kind: str = "offer", *, allow_expired: bool = False) -> dict:
	"""Check signature, expiry and token kind (an offer key can never be replayed as a
	modification proposal or the other way round). ``allow_expired``: the caller checks
	``require_fresh`` itself, after recognising a replay of what the token already did."""
	invalid = "OFFER_INVALID" if kind == "offer" else "PROPOSAL_INVALID"     # a guest's change or extras (G-70b)
	try:
		body_b64, mac_b64 = token.split(".", 1)
		pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
		body = base64.urlsafe_b64decode(pad(body_b64))
		mac = base64.urlsafe_b64decode(pad(mac_b64))
	except Exception:
		frappe.throw(_("Invalid offer."), refusal(invalid))
	if not hmac.compare_digest(hmac.new(_secret(), body, hashlib.sha256).digest(), mac):
		frappe.throw(_("Invalid offer."), refusal(invalid))
	data = json.loads(body)
	if (data.get("kind") or "offer") != kind:
		frappe.throw(_("Invalid offer."), refusal(invalid))
	if not allow_expired:
		require_fresh(data)
	return data


def require_fresh(data: dict) -> None:
	if data.get("exp") and get_datetime(data["exp"]) < now_datetime():
		frappe.throw(_("This offer has expired — please search again."),
		             refusal("OFFER_EXPIRED" if (data.get("kind") or "offer") == "offer" else "PROPOSAL_EXPIRED"))


# ─── request helpers ─────────────────────────────────────────────────────


def parse_dob(value) -> date:
	"""A child's date of birth as the API receives it (ISO date)."""
	try:
		return date.fromisoformat(str(value).strip()[:10])
	except ValueError:
		frappe.throw(_("Invalid date of birth."), refusal("CHILD_DOB_INVALID"))       # never echoed: personal data


def checked_dob(dob: date, arrival: date, n: int) -> int:
	"""A child's date of birth checked server-side (G-52): not in the future, the child under
	18 on arrival. → the child's age in whole years on arrival (display; pricing uses the
	date of birth itself, in completed months)."""
	try:
		months = ages.check_child_dob(dob, arrival, today=getdate(now_datetime()))
	except PricingError:
		if dob > getdate(now_datetime()):
			frappe.throw(_("Child {0}: the date of birth cannot be in the future.").format(n),
			             refusal("CHILD_DOB_FUTURE", child=n))
		frappe.throw(_("Child {0} is {1} or older on arrival: add them as an adult.").format(
			n, ages.MAX_CHILD_AGE + 1), refusal("CHILD_TOO_OLD", child=n, age=ages.MAX_CHILD_AGE + 1))
	return months // 12


@dataclass
class Party:
	adults: int
	children: list[ChildSpec] = field(default_factory=list)

	@classmethod
	def parse(cls, raw, *, arrival: date | None = None) -> Party:
		"""Each child has an age in whole years (0–17) or a date of birth. A date of birth is
		checked against ``arrival`` (when the stay is known) and gives the child's age on
		arrival for display; pricing counts completed months from it (G-52)."""
		raw = raw or {}
		adults = int(raw.get("adults") or 0)
		kids = []
		for n, c in enumerate(raw.get("children") or [], start=1):
			if isinstance(c, dict):
				dob = parse_dob(c["dob"]) if c.get("dob") else None
				age = int(c["age"]) if c.get("age") not in (None, "") else None
				if dob is not None and arrival is not None:
					age = checked_dob(dob, arrival, n)
				kids.append(ChildSpec(age=age, dob=dob))
			else:
				kids.append(ChildSpec(age=int(c)))
		if adults < 1 or adults > 12 or len(kids) > 8:
			frappe.throw(_("Each room needs 1–12 adults and at most 8 children."), refusal("PARTY_INVALID"))
		for k in kids:
			if k.age is None and k.dob is None:
				frappe.throw(_("Each child needs an age."), refusal("CHILD_AGE_REQUIRED"))
			if k.age is not None and not (0 <= k.age <= ages.MAX_CHILD_AGE):
				frappe.throw(_("Child ages must be 0–17."), refusal("CHILD_AGE_INVALID"))
		return cls(adults, kids)

	def key(self) -> dict:
		return {"adults": self.adults, "children": [{"age": c.age, "dob": c.dob.isoformat() if c.dob else None}
		                                            for c in self.children]}

	def summary(self) -> dict:
		"""The party without dates of birth, for analytics and notes: each child's age in whole
		years (on arrival, for one given by date of birth)."""
		return {"adults": self.adults, "children": [c.age for c in self.children]}


def parse_rooms(rooms, *, arrival: date | None = None) -> list[Party]:
	if isinstance(rooms, str):
		rooms = json.loads(rooms)
	if not rooms:
		frappe.throw(_("At least one room is required."), refusal("ROOMS_COUNT", max=MAX_ROOMS))
	if len(rooms) > MAX_ROOMS:
		frappe.throw(_("At most {0} rooms per booking.").format(MAX_ROOMS), refusal("ROOMS_COUNT", max=MAX_ROOMS))
	return [Party.parse(r, arrival=arrival) for r in rooms]


def _dates(check_in, check_out) -> tuple[date, date]:
	ci, co = getdate(check_in), getdate(check_out)
	if co <= ci:
		frappe.throw(_("Check-out must be after check-in."), refusal("DATES_INVALID"))
	if (co - ci).days > engine.MAX_NIGHTS:
		frappe.throw(_("Stays longer than {0} nights are booked by the reservations team.").format(engine.MAX_NIGHTS),
		             refusal("STAY_TOO_LONG", max=engine.MAX_NIGHTS))
	if ci < getdate(now_datetime()):
		frappe.throw(_("Check-in cannot be in the past."), refusal("CHECKIN_PAST"))
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
                  channel, currency, promo_codes=(), member=False, extras=(), room_index: int = 0) -> StayRequest:
	return StayRequest(property=property, room_type=room_type, board=board, rate_plan=rate_plan, check_in=check_in,
	                   check_out=check_out, adults=party.adults, children=tuple(party.children), sale_at=sale_at,
	                   market=market, channel=channel, sell_currency=currency.upper(),
	                   promo_codes=tuple(sorted({k for c in promo_codes if (k := promotions.code_key(c))})),
	                   member=member, extras=tuple(extras), room_index=room_index)


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
	# a disabled room type is not sold (Y-9); it keeps counting in its pool (``avail.pool_of``). Read once per hotel
	disabled_types = set(frappe.get_all("Room Type", filters={"property": property, "disabled": 1}, pluck="name"))
	# why a room cannot be sold, from the first contract that tried: shown only when no
	# later contract can price the room either (G-17)
	fallback: dict[str, list[dict]] = {}
	ctx_cache: dict[tuple, object] = {}
	# the hotel's mandatory extras are priced in every offer, as the quote prices them (Y-5): the
	# engine adds them to each room (a per-booking one to room 1 only); optional ones are the
	# guest's choice at the quote. Loaded with the first context: an ambiguous catalog stops each
	# room of this hotel as the quote does (``Unsellable``), never the search. Read once per hotel
	# per search: its refusal is remembered and raised again, not read (and logged) again (2D-1)
	mandatory: dict | None = None
	catalog_refused: Unsellable | None = None

	for contract_row, version in cands:
		terms = contracts.load_terms(version)
		sell_ccy = (currency or contract_row.sell_currency or terms.currency).upper()
		room_types = [room_type] if room_type else sorted(terms.rooms)
		for rt in room_types:
			if rt not in terms.rooms or rt in disabled_types:
				continue
			# the first (market-specific, then highest-priority) contract selling a room wins
			if rt in seen_rooms:
				continue
			count, per_day = avail.stay_availability(property, rt, contract_row.name, check_in, check_out, sale_date)
			rate_plans = sorted(terms.rate_plans) or [None]
			priced_here = False   # this contract can price this room for this stay (G-17)
			pending: list[tuple[bool, dict]] = []
			boards = _boards_of(terms)
			for rp in rate_plans:
				scope = avail.scope_for(rt, contract_row.name, market, rp, channel)
				violations = avail.check_restrictions(property, scope, check_in, check_out, sale_date, cells)
				for board in boards:
					# R-29: every party is priced on its own, so a room type that fits room 1
					# but not room 2 is still offered for room 1 (``room_indexes``)
					room_reasons = []
					key = (version, sell_ccy, rt)
					priced: list[tuple[int, Party, StayRequest, object]] = []
					for idx, party in enumerate(parties):
						req = build_request(property=property, room_type=rt, board=board, rate_plan=rp,
						                    check_in=check_in, check_out=check_out, party=party, sale_at=sale_at,
						                    market=market, channel=channel, currency=sell_ccy,
						                    promo_codes=promo_codes, member=member, room_index=idx)
						try:
							if key not in ctx_cache:
								if catalog_refused is not None:
									raise catalog_refused
								if mandatory is None:
									try:
										catalog = ctxmod.extras_catalog(property, at=sale_at)
									except Unsellable as refused:
										catalog_refused = refused
										raise
									mandatory = {code: d for code, d in catalog.items() if d.mandatory}
								ctx_cache[key] = ctxmod.build_context(terms, req, extras=mandatory)
							q = engine.price_stay(ctx_cache[key], req)
						except Unsellable as u:
							room_reasons.append({"room_index": idx, "code": u.code, "message": u.message})
							continue
						except PricingError as e:
							room_reasons.append({"room_index": idx, "code": "PRICING_ERROR", "message": str(e)})
							continue
						if not q.sellable:
							room_reasons.extend({"room_index": idx} | dict(r) for r in q.reasons)
							continue
						priced.append((idx, party, req, q))
					alone = {i: q.total for i, _pa, _r, q in priced}      # each room priced on its own
					# a room a promotion's minimum basket refused alone: quoted with other rooms, its
					# price may be another (``_from_total``, review M1)
					limited = {i: engine.basket_limited(q) for i, _pa, _r, q in priced}
					if len(priced) == len(parties):
						# every requested room in this offer: priced as one booking, so a minimum basket
						# is the booking's (G-84, ADR-057); the quote step prices the rooms chosen together
						quotes, _total = engine.price_together([r for _i, _pa, r, _q in priced], [q for *_x, q in priced],
						                                       lambda _i, r: engine.price_stay(ctx_cache[key], r),
						                                       record=False)
						kept = []
						for (i, pa, _r, _q), q in zip(priced, quotes, strict=True):
							if q.sellable:
								kept.append((i, pa, q.request, q))
							else:
								room_reasons.extend({"room_index": i} | dict(x) for x in q.reasons)
						priced = kept
					rooms_out = []
					for idx, party, req, q in priced:
						offer = {"v": 1, "property": property, "room_type": rt, "board": board, "rate_plan": rp,
						         "contract": contract_row.name, "version": version, "check_in": check_in.isoformat(),
						         "check_out": check_out.isoformat(), "party": party.key(), "market": market,
						         "channel": channel, "currency": sell_ccy, "promo_codes": list(req.promo_codes),
						         "member": bool(member), "total": to_str(q.total), "room_index": idx,
						         "exp": offer_exp.isoformat()}
						rooms_out.append({"room_index": idx, "offer_key": sign(offer),
						                  "quote": q.to_dict(internal=internal), "_alone": alone[idx],
						                  "_limited": limited[idx]})
					sellable = bool(rooms_out)
					complete = len(rooms_out) == len(parties)
					entry = {
						"room_type": rt, "board": board, "rate_plan": rp, "contract": contract_row.name,
						"contract_code": contract_row.contract_code, "market": terms.market,
						"version": version, "currency": sell_ccy,
						"available": count, "availability": [asdict(d) | {"day": d.day.isoformat()}
						                                     for d in per_day] if internal else None,
						"restrictions": [v.to_dict() for v in violations],
						"rooms": rooms_out,
						"room_indexes": [r["room_index"] for r in rooms_out],
						"complete": complete,
					}
					if room_reasons:
						entry["room_reasons"] = room_reasons
					# a room type with at least one free room can take any party it fits; how many
					# of the requested rooms it can take at once is ``available`` (checked again,
					# atomically, when the booking is made)
					bookable = sellable and not violations and count > 0
					if sellable:
						if complete:
							entry["total"] = to_str(sum(D(r["quote"]["totals"]["total"]) for r in rooms_out))
						rp_info = rooms_out[0]["quote"].get("rate_plan")
						entry["refundable"] = bool(rp_info["refundable"]) if rp_info else True
						entry["rate_plan_info"] = rp_info
					entry["bookable"] = bookable
					if not sellable:
						entry["reasons"] = [{k: v for k, v in r.items() if k != "room_index"}
						                    for r in room_reasons if r["room_index"] == room_reasons[0]["room_index"]]
					elif count < 1:
						entry["reasons"] = [{"code": "SOLD_OUT", "message": _("Not enough rooms available")}]
					elif violations:
						entry["reasons"] = [{"code": v.code, "message": v.message} for v in violations]
					elif not complete:
						entry["reasons"] = [{"code": r["code"], "room_index": r["room_index"],
						                     "message": _("Room {0}: {1}").format(r["room_index"] + 1, r["message"])}
						                    for r in room_reasons]
					priced_here = priced_here or sellable
					pending.append((bookable, entry))
			# the room belongs to the first contract that can price it; a contract closed for this
			# sale date or stay (or that cannot price the room) hides nothing from the next one
			if priced_here:
				for bookable, entry in pending:
					(result["offers"] if bookable else result["unavailable"]).append(entry)
				seen_rooms.add(rt)
			else:
				fallback.setdefault(rt, [entry for _b, entry in pending])

	for rt, entries in fallback.items():
		if rt not in seen_rooms:
			result["unavailable"].extend(entries)

	content = _room_content(sorted({o["room_type"] for o in result["offers"] + result["unavailable"]}))
	result["rooms"] = {k: {"name": v.room_type_name, "description": v.description, "bed_type": v.bed_type,
	                       "beds": v.tex_beds, "size_sqm": v.tex_size_sqm, "view": v.room_view,
	                       "amenities": [a.strip() for a in (v.amenities or "").replace("\n", ",").split(",")
	                                     if a.strip()], "image": v.image,
	                       "max_adults": v.adults_capacity, "max_children": v.children_capacity}
	                   for k, v in content.items()}
	result["offers"].sort(key=lambda o: (not o["complete"], _offer_sort_total(o), o["room_type"], o["board"],
	                                     o.get("rate_plan") or ""))
	result["from_total"], result["from_currency"] = _from_total(result["offers"], len(parties))
	for o in result["offers"] + result["unavailable"]:
		for r in o["rooms"]:
			r.pop("_alone", None)
			r.pop("_limited", None)
	unplaced = [i for i in range(len(parties))
	            if not any(i in o["room_indexes"] for o in result["offers"])]
	if result["offers"] and unplaced:
		result["unplaced_rooms"] = unplaced
		result["messages"].append(_("No available room type fits room {0}.").format(
			", ".join(str(i + 1) for i in unplaced)))
	return result


def _offer_sort_total(o: dict):
	return D(o["total"]) if o.get("total") else min(D(r["quote"]["totals"]["total"]) for r in o["rooms"])


def _from_total(offers: list[dict], n_rooms: int) -> tuple[str | None, str | None]:
	"""Cheapest way to place every requested room, in the currency of the first offer, at a price
	that can be booked (review M1):
	- an offer holding every room at its total (priced as one booking, G-84), when its room type
	  has that many rooms free;
	- the cheapest offer of each party priced on its own, summed (rooms may be of different
	  types), only when no promotion's minimum basket refused any of those rooms — quoted together
	  their price could be another, higher too: an exclusive promotion granted on the booking's
	  basket can replace a better one — and when each room type has that many rooms free.
	(None, None) when a party fits nowhere or no such price is known."""
	if not offers:
		return None, None
	ccy = offers[0]["currency"]
	mine = [o for o in offers if o["currency"] == ccy]
	best: dict[int, tuple] = {}
	for o in mine:
		for r in o["rooms"]:
			t = D(r["_alone"])
			if r["room_index"] not in best or t < best[r["room_index"]][0]:
				best[r["room_index"]] = (t, o, r)
	if len(best) < n_rooms:
		return None, None
	totals = []
	per_type = Counter(o["room_type"] for _t, o, _r in best.values())
	if not any(r.get("_limited") for _t, _o, r in best.values()) \
			and all(int(o.get("available") or 0) >= per_type[o["room_type"]] for _t, o, _r in best.values()):
		totals.append(sum((t for t, _o, _r in best.values()), D(0)))
	totals += [D(o["total"]) for o in mine
	           if o.get("complete") and o.get("total") and int(o.get("available") or 0) >= n_rooms]
	return (to_str(min(totals)), ccy) if totals else (None, None)


def search(*, properties: list[str], check_in, check_out, rooms, market: str, channel: str,
           currency: str | None = None, promo_codes=(), member: bool | set[str] = False, internal=False,
           sale_at: datetime | None = None) -> dict:
	"""``member``: the guest is a member of every hotel's program (True), of none (False), or of the programs of
	the hotels in the set (C-04): a member's offers are priced with the members-only promotions."""
	ci, co = _dates(check_in, check_out)
	parties = parse_rooms(rooms, arrival=ci)
	market = (market or "").upper()
	if not frappe.db.exists("TEX Market", market):
		frappe.throw(_("Unknown market {0}.").format(market), refusal("MARKET_UNKNOWN", market=market))
	if not frappe.db.exists("TEX Sales Channel", channel):
		frappe.throw(_("Unknown sales channel {0}.").format(channel), refusal("SITE_CLOSED"))
	out = []
	for p in properties:
		here = (p in member) if isinstance(member, set | frozenset) else bool(member)
		res = search_property(p, check_in=ci, check_out=co, parties=parties, market=market, channel=channel,
		                      currency=currency, promo_codes=promo_codes, member=here, internal=internal,
		                      sale_at=sale_at)
		prop = frappe.db.get_value("Property", p, ["property_name", "city", "star_category"], as_dict=True) or {}
		res.update({"property_name": prop.get("property_name"), "city": prop.get("city"),
		            "star_category": prop.get("star_category")})
		out.append(res)
	out.sort(key=lambda r: (not r.get("from_total"), D(r.get("from_total") or 0)))
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
	                     member=bool(offer.get("member")), extras=extras, room_index=int(offer.get("room_index") or 0))


def price_request(version: str, req: StayRequest, *, gkey: str | None = None, extras_catalog=None,
                  exclude_booking: str | None = None, check_capacity: bool = True,
                  exclude_reservation: str | None = None, fx_pins=None, usage_at=None, expected_hash=None):
	"""``fx_pins``: rates recorded at the original sale, reused for their pairs (G-56).
	``usage_at``: coupon uses counted as held at that moment (the historical simulator, G-51).
	``expected_hash``: the payload hash a sold stay recorded for ``version`` (G-73): anything else
	is refused (``contracts.PayloadMismatch``)."""
	terms = contracts.load_terms(version, expected_hash=expected_hash)
	try:
		ctx = ctxmod.build_context(terms, req, gkey=gkey, extras=extras_catalog, exclude_booking=exclude_booking,
		                           check_capacity=check_capacity, exclude_reservation=exclude_reservation,
		                           fx_pins=fx_pins, usage_at=usage_at)
	except Unsellable as u:          # no FX rate, an ambiguous or missing tax policy…
		return engine.unsellable_quote(terms, req, u), terms
	try:
		return engine.price_stay(ctx, req), terms
	except PricingError as e:
		# an input the engine refuses (a missing rate plan, a stay too long…): a reason on the
		# quote, never an HTTP 500 whose Error Log would hold the request's guest data
		return engine.unsellable_quote(terms, req, Unsellable("PRICING_ERROR", str(e))), terms


MAX_EXTRAS = 30


def _json(value, default):
	if isinstance(value, str):
		try:
			return json.loads(value or "null") or default
		except ValueError:
			frappe.throw(_("Invalid JSON payload."), refusal("INVALID_REQUEST"))
	return default if value is None else value


def extra_items(extras) -> list[dict]:
	"""Extras as a caller sends them — [{"code", "quantity", "service_dates"}] — checked for their
	shape: anything else is a clean refusal, never a server error with a log (G-84 review L2)."""
	extras = _json(extras, [])
	if not isinstance(extras, list) or len(extras) > MAX_EXTRAS:
		frappe.throw(_("Invalid extras."), refusal("EXTRAS_INVALID"))
	for e in extras:
		if not isinstance(e, dict) or not isinstance(e.get("code"), str) or not e["code"].strip() \
				or not isinstance(e.get("quantity", 1), int | str | None) \
				or not isinstance(e.get("service_dates") or [], list) \
				or not all(isinstance(d, str) for d in e.get("service_dates") or []):
			frappe.throw(_("Invalid extras."), refusal("EXTRAS_INVALID"))
	return extras


def room_items(rooms) -> list[dict]:
	"""The rooms of one booking as a caller sends them — [{"offer_key", "extras"}], 1 to
	``MAX_ROOMS`` — checked for their shape (G-84 review L2)."""
	rooms = _json(rooms, [])
	if not isinstance(rooms, list) or not rooms or len(rooms) > MAX_ROOMS:
		frappe.throw(_("Select between 1 and {0} rooms.").format(MAX_ROOMS), refusal("ROOMS_COUNT", max=MAX_ROOMS))
	out = []
	for r in rooms:
		if not isinstance(r, dict) or not isinstance(r.get("offer_key"), str) or not r["offer_key"]:
			frappe.throw(_("Invalid rooms."), refusal("INVALID_REQUEST"))
		out.append({"offer_key": r["offer_key"], "extras": extra_items(r.get("extras"))})
	return out


def _extras_list(extras) -> tuple[ExtraRequest, ...]:
	out = []
	for e in extra_items(extras):
		try:
			qty = int(e.get("quantity") or 1)
			days = tuple(getdate(d) for d in e.get("service_dates") or [])
		except (TypeError, ValueError):
			frappe.throw(_("Invalid extras."), refusal("EXTRAS_INVALID"))
		if qty < 1 or qty > 99:
			frappe.throw(_("Invalid extra quantity."), refusal("EXTRAS_INVALID"))
		out.append(ExtraRequest(code=str(e["code"]).upper(), quantity=qty, service_dates=days))
	return tuple(out)


def _offer_request(offer_key: str, *, extras, promo_codes, now) -> tuple[dict, StayRequest, tuple]:
	offer = verify(offer_key)
	extras_req = _extras_list(extras)
	return offer, request_from_offer(offer, sale_at=now, extras=extras_req, promo_codes=promo_codes), extras_req


def _on_sale(offer: dict, now, *, refuse: bool = True) -> tuple[object | None, dict | None]:
	"""(the contract version on sale now, None) or (None, the refusal). The offer's version might
	have been superseded since the search: quotes always price on the version on sale NOW.
	``refuse``: no version on sale is an error (one room's quote), else that room's refusal."""
	live = contracts.active_version_header(offer["contract"], now)
	if not live:
		if refuse:
			frappe.throw(_("This rate is no longer on sale — please search again."), refusal("NOT_ON_SALE"))
		return None, {"ok": False, "reasons": [{"code": "NOT_ON_SALE",
		                                        "message": _("This rate is no longer on sale — please search again.")}]}
	stopped = contracts.not_on_sale(offer["contract"])        # suspended since the search (ADR-045)
	if stopped:
		return None, {"ok": False, "reasons": [{"code": stopped.code, "message": str(stopped)}]}
	return live, None


def _stay_refusal(offer: dict, req: StayRequest, now) -> dict | None:
	"""Why the stay cannot be sold now: its room type no longer sold, no room left, or a restriction of its scope."""
	if frappe.db.get_value("Room Type", req.room_type, "disabled"):
		# disabled after the offer was made (LO-03, ADR-048): search no longer shows it, its old offers sell nothing
		return {"ok": False, "reasons": [{"code": "ROOM_NOT_SOLD",
		                                  "message": _("This room is no longer sold — please search again.")}]}
	avail_count, _days = avail.stay_availability(req.property, req.room_type, offer["contract"], req.check_in,
	                                            req.check_out, now.date())
	if avail_count < 1:
		return {"ok": False, "reasons": [{"code": "SOLD_OUT", "message": _("This room has just sold out.")}]}
	scope = avail.scope_for(req.room_type, offer["contract"], req.market, req.rate_plan, req.channel)
	violations = avail.check_restrictions(req.property, scope, req.check_in, req.check_out, now.date())
	if violations:
		return {"ok": False, "reasons": [v.to_dict() for v in violations]}
	return None


def _persist(offer_key: str, offer: dict, req: StayRequest, q, terms, live, now, *, session_id, changed_inputs) -> dict:
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
	# a withdraw committed while this was priced closes it (O-13): its range lock on the version's open
	# quotes held this insert back, and this read under a shared lock sees it; a quote inserted before
	# the withdraw scanned is found and expired by it. Superseded still books (as before)
	row = frappe.db.sql("SELECT status FROM `tabTEX Contract Version` WHERE name=%s LOCK IN SHARE MODE",
	                    live.version_id)
	if row and row[0][0] == "Withdrawn":
		frappe.throw(_("This rate is no longer on sale. Please search again."),
		             refusal("NOT_ON_SALE", contracts.ContractNotOnSale))
	price_changed = to_str(q.total) != offer.get("total") and not changed_inputs
	return {"ok": True, "quote_id": doc.name, "expires_at": str(doc.expires_at), "price_changed": price_changed,
	        "previous_total": offer.get("total"), "quote": q.to_dict(internal=False),
	        "room_index": offer.get("room_index", 0)}


def create_quote(offer_key: str, *, extras=None, promo_codes=None, guest_email: str | None = None,
                 session_id: str | None = None) -> dict:
	"""One room priced on its own. The rooms of a booking are quoted together (``create_quotes``):
	a minimum basket is the whole booking's (G-84)."""
	now = now_datetime()
	offer, req, extras_req = _offer_request(offer_key, extras=extras, promo_codes=promo_codes, now=now)
	gkey = ctxmod.guest_key(guest_email)
	live, refused = _on_sale(offer, now)
	if refused:
		return refused
	q, terms = price_request(live.version_id, req, gkey=gkey)
	if not q.sellable:
		return {"ok": False, "reasons": q.reasons}
	refused = _stay_refusal(offer, req, now)
	if refused:
		return refused
	return _persist(offer_key, offer, req, q, terms, live, now, session_id=session_id,
	                changed_inputs=bool(extras_req) or promo_codes is not None)


def create_quotes(rooms: list[dict], *, promo_codes=None, guest_email: str | None = None,
                  session_id: str | None = None) -> dict:
	"""The rooms of one booking quoted together (G-84, ADR-057): each ``{"offer_key", "extras"}``
	is an offer of the same search (one hotel, currency, market and channel, distinct rooms).
	Every room is priced alone, then as one booking (``engine.price_together``): each promotion's
	minimum basket is compared with the basket of the rooms it covers, and each quote records the
	booking in its request (review L3); the booking checks that its rooms are the ones priced
	together. → {"ok", "rooms": one ``create_quote`` answer per room, in order, "booking_basket"}.
	A room that cannot be sold answers with its reasons; the others are quoted (priced alone when
	the booking cannot be)."""
	rooms = room_items(rooms)
	now = now_datetime()
	gkey = ctxmod.guest_key(guest_email)
	items = []
	for r in rooms:
		key = r["offer_key"]
		offer, req, extras_req = _offer_request(key, extras=r.get("extras"), promo_codes=promo_codes, now=now)
		items.append({"key": key, "offer": offer, "req": req, "changed": bool(extras_req) or promo_codes is not None})
	keys = {(i["offer"]["property"], i["offer"]["currency"], i["offer"]["market"], i["offer"]["channel"]) for i in items}
	indexes = [int(i["offer"].get("room_index") or 0) for i in items]
	if len(keys) != 1 or len(set(indexes)) != len(indexes):
		frappe.throw(_("The rooms of one booking must come from one search. Please search again."),
		             refusal("SEARCH_AGAIN"))
	for i in items:
		i["live"], i["out"] = _on_sale(i["offer"], now, refuse=False)
		if i["out"] is None:
			i["q"], i["terms"] = price_request(i["live"].version_id, i["req"], gkey=gkey)
			if not i["q"].sellable:
				i["out"] = {"ok": False, "reasons": i["q"].reasons}
	total = None
	if all(i["out"] is None for i in items):
		quotes, total = engine.price_together(
			[i["req"] for i in items], [i["q"] for i in items],
			lambda n, r: price_request(items[n]["live"].version_id, r, gkey=gkey)[0])
		for i, q in zip(items, quotes, strict=True):
			i["q"], i["req"] = q, q.request
			if not q.sellable:
				i["out"] = {"ok": False, "reasons": q.reasons}
	for i in items:
		if i["out"] is None:
			i["out"] = _stay_refusal(i["offer"], i["req"], now) or _persist(
				i["key"], i["offer"], i["req"], i["q"], i["terms"], i["live"], now, session_id=session_id,
				changed_inputs=i["changed"])
	return {"ok": all(i["out"]["ok"] for i in items), "rooms": [i["out"] for i in items],
	        "booking_basket": to_str(total) if total is not None else None}


def load_quote(quote_id: str, *, for_update: bool = False) -> tuple[dict, dict, dict]:
	row = frappe.db.get_value("TEX Quote", quote_id, ["name", "status", "expires_at", "request_json",
	                                                  "result_json", "contract_version", "property"],
	                          as_dict=True, for_update=for_update)
	if not row:
		frappe.throw(_("Quote {0} not found.").format(quote_id), frappe.DoesNotExistError)
	return row, json.loads(row.request_json), json.loads(row.result_json)


def quote_refusal(row) -> Refusal | None:
	"""Why a stored quote cannot be booked (coded, G-70b), or None."""
	if row.status == "Expired":
		# its version was withdrawn (``contracts.withdraw``, O-13): the rate is gone, not used
		return Refusal(_("This rate is no longer on sale. Please search again."), code="NOT_ON_SALE")
	if row.status != "Open":
		return Refusal(_("This quote was already used."), code="QUOTE_USED")
	if get_datetime(row.expires_at) < now_datetime():
		return Refusal(_("This quote has expired — please search again."), code="QUOTE_EXPIRED")
	return None


def quote_is_usable(row) -> str | None:
	"""``quote_refusal``'s text (a basket's ``problem``)."""
	why = quote_refusal(row)
	return str(why) if why else None


def default_sale_window(check_in: date) -> timedelta:
	return timedelta(days=max(0, (check_in - getdate(now_datetime())).days))


INTERNAL_TOTALS = engine.INTERNAL_TOTALS


def _night_amount(n: dict, ccy: str) -> str | None:
	if n.get("amount") is not None:
		return n["amount"]
	return to_str(quantize(D(n["final"]), ccy)) if n.get("final") not in (None, "") and ccy else None


def cost_stage_outcomes(q: dict) -> set[tuple[str, str]]:
	"""(promotion id, source) of a quote dict's cost-stage outcomes, from its explanation: a
	snapshot priced before outcomes named their stage (ADR-059 review) is told by it."""
	out = set()
	for step in q.get("explanation") or []:
		rule = (step.get("rule") or {}) if isinstance(step, dict) else {}
		if step.get("stage") == "cost_offer" and rule.get("rule_id"):
			out.add((rule["rule_id"], rule.get("source") or ""))
	return out


def _cost_stage(pr: dict, cost_stage: set[tuple[str, str]]) -> bool:
	"""A promotion outcome of a quote dict is cost-stage: its stage says so, or (no stage recorded)
	``cost_stage`` (``cost_stage_outcomes`` of its quote) names it."""
	if "stage" in pr:
		return pr.get("stage") == engine.COST
	return (pr.get("promo_id"), pr.get("source") or "") in cost_stage


def sold_promotions(q: dict) -> list[dict]:
	"""The promotions a quote dict granted on the selling price: applied, never a cost-stage offer
	(it lowered the contract cost, a cost figure; ADR-059 review). What a reservation records as
	its promotions (``tex_promotions``, read in Desk by every role that reads reservations)."""
	cost_stage = cost_stage_outcomes(q)
	return [pr for pr in q.get("promotions") or [] if pr.get("applied") and not _cost_stage(pr, cost_stage)]


def strip_internal(q: dict | None, *, staff: bool = False) -> dict | None:
	"""Remove cost, margin, per-night cost and the rule explanation from a quote dict
	(for users without price.view_cost and for guests). ``staff`` keeps the list of
	promotions that did not apply (an agent may offer those codes to the caller); a cost-stage
	offer, applied or not, is a cost figure and never kept (ADR-059 review)."""
	if not q:
		return q
	if isinstance(q.get("promotions"), list):
		cost_stage = cost_stage_outcomes(q)
		q["promotions"] = [pr for pr in q["promotions"] if not _cost_stage(pr, cost_stage)]
	q.pop("explanation", None)
	if isinstance(q.get("contract"), dict):
		q["contract"].pop("payload_hash", None)   # the frozen payload's digest: confirms a guess of its rates (G-99)
	q.pop("fx", None)
	q.pop("fx_rates", None)                       # rates, providers and FX margins (G-56)
	q.pop("original_fx_rates", None)
	if isinstance(q.get("nights"), list):
		ccy = q.get("currency") or ""
		q["nights"] = [{"date": n.get("date"), "amount": _night_amount(n, ccy)} for n in q["nights"]
		               if isinstance(n, dict)]
	for k in INTERNAL_TOTALS:
		(q.get("totals") or {}).pop(k, None)
	for a in q.get("addons") or []:               # extras added after booking keep their own quote (G-22)
		if isinstance(a, dict) and isinstance(a.get("quote"), dict):
			strip_internal(a["quote"], staff=True)
	if staff:
		return q
	q["promotions"] = [pr for pr in q.get("promotions") or [] if pr.get("applied")]
	return q

