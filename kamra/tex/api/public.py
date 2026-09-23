"""Guest-facing TEX Booking API (R-26–R-33, R-38, R-42). The only allow_guest surface
of TEX besides payment callbacks.

Every endpoint: resolves the booking site (and so the hotels it may sell), is rate
limited, validates input server-side and returns guest-safe data only (no cost,
margin or rule explanation). Prices always come from the server.
"""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import get_datetime, getdate, now_datetime

from kamra.tex.api._util import parse, text
from kamra.tex.money import D, from_db, to_str
from kamra.tex.pricing import versions
from kamra.tex.security.audit import log_exception
from kamra.tex.services import booking as booking_svc
from kamra.tex.services import content, modification, quoting
from kamra.tex.services.txn import retry_on_deadlock


def _limit(default: int, key: str):
	"""Per-IP request limit; ``site_config.json`` may raise it (``tex_public_search_limit``,
	``tex_public_write_limit``) for load tests and E2E benches, never below the default."""
	return lambda: max(default, int(frappe.conf.get(key) or 0))


SEARCH_LIMIT = {"limit": _limit(60, "tex_public_search_limit"), "seconds": 60}
WRITE_LIMIT = {"limit": _limit(20, "tex_public_write_limit"), "seconds": 600}


# ─── site ────────────────────────────────────────────────────────────────


def _site(slug: str | None = None, domain: str | None = None):
	name = None
	if slug:
		name = frappe.db.get_value("TEX Booking Site", {"site_slug": slug.strip().lower(), "enabled": 1})
	elif domain:
		d = domain.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
		name = frappe.db.get_value("TEX Booking Domain", {"domain": d, "verified": 1}, "parent")
	if not name:
		frappe.throw(_("Booking site not found."), frappe.DoesNotExistError)
	site = frappe.get_cached_doc("TEX Booking Site", name)
	if not site.enabled:
		frappe.throw(_("Booking site not found."), frappe.DoesNotExistError)
	return site


def _site_properties(site) -> list[str]:
	if site.property:
		return [site.property]
	return frappe.get_all("Property", filters={"tex_hotel_group": site.hotel_group, "disabled": 0}, pluck="name",
	                      order_by="property_name asc")


def _channel(site) -> str:
	return site.sales_channel or "DIRECT_WEB"


def _csv(v) -> list[str]:
	return [x.strip() for x in (v or "").replace("\n", ",").split(",") if x.strip()]


def _safe_return_url(site, url: str | None, booking: str | None = None) -> str | None:
	"""Only redirect back to this TEX host or one of the site's verified domains
	(no open redirects through the payment flow). ``{booking}`` in the URL becomes the
	booking number (a custom-domain site returns to its own host)."""
	if not url:
		return None
	from urllib.parse import quote, urlparse

	if booking:
		url = url.replace("{booking}", quote(booking, safe=""))
	if "{" in url or "}" in url:
		return None

	u = urlparse(url)
	if u.scheme != "https" and not (u.scheme == "http" and frappe.conf.get("developer_mode")):
		return None
	allowed = {urlparse(frappe.utils.get_url()).hostname}
	allowed |= set(frappe.get_all("TEX Booking Domain", filters={"parent": site.name, "verified": 1},
	                              pluck="domain"))
	return url if u.hostname in allowed else None


@frappe.whitelist(allow_guest=True)
@rate_limit(**SEARCH_LIMIT)
def site(slug: str | None = None, domain: str | None = None):
	s = _site(slug, domain)
	# the widget on a hotel's own website reads its theme from here: allow exactly the
	# origins the hotel listed for embedding (Frappe adds the CORS headers)
	origins = [o.strip().rstrip("/") for o in (s.allowed_embed_origins or "").splitlines()
	           if o.strip().startswith("https://")]
	if origins:
		frappe.local.allow_cors = origins
	props = _site_properties(s)
	loc = content.Localizer(content.guest_language())
	hotels = []
	for p in props:
		d = frappe.db.get_value("Property", p, ["property_name", "city", "star_category", "address_line", "phone",
		                                        "email", "checkin_time", "checkout_time", "hero_image", "logo_url",
		                                        "showcase_description", "latitude", "longitude", "currency"],
		                        as_dict=True)
		gallery = frappe.get_all("Property Photo", filters={"parent": p, "parenttype": "Property"},
		                         fields=["url", "caption"], order_by="idx asc", limit=12)
		hotels.append(loc.hotel(p, {"name": p, **{k: (str(v) if k.endswith("_time") and v else v)
		                                           for k, v in d.items()}, "gallery": gallery}))
	texts = json.loads(s.custom_texts) if s.custom_texts else {}
	return {
		"slug": s.site_slug, "name": s.site_name, "hotels": hotels, "group": bool(s.hotel_group and not s.property),
		"default_language": s.default_language or "en", "languages": _csv(s.languages) or ["en"],
		"default_currency": s.default_currency, "currencies": _csv(s.currencies),
		"default_market": s.default_market,
		"branding": {"logo": s.logo, "primary": s.primary_color, "accent": s.accent_color,
		             "background": s.background_color, "font": s.font_family, "radius": s.radius,
		             "card_radius": s.card_radius, "button_style": s.button_style, "header": s.header_layout,
		             "search_style": s.search_style, "hero_image": s.hero_image},
		"contact": {"phone": s.contact_phone, "email": s.contact_email, "whatsapp": s.whatsapp,
		            "address": s.address},
		"texts": texts, "policies": s.policies, "self_service": bool(s.self_service_enabled),
		"analytics": {"ga4": s.ga4_measurement_id, "gtm": s.gtm_container_id, "meta_pixel": s.meta_pixel_id,
		              "consent_banner": bool(s.consent_banner)},
		"extras": _strip_names({p: loc.extras(p, rows) for p, rows in _public_extras(props).items()}),
	}


def _public_extras(props: list[str]) -> dict:
	from kamra.tex.commercial.context import listed_extras

	out = {}
	for p in props:
		# the revision on sale now (G-20)
		rows = listed_extras(p, online_only=True, fields=("extra_name", "category", "description", "image",
		                                                "pricing_mode", "currency", "amount", "max_quantity",
		                                                "is_mandatory", "service_from", "service_to"))
		out[p] = [{k: r.get(k) for k in ("name", "extra_code", "extra_name", "category", "description", "image",
		                                  "pricing_mode", "currency", "amount", "max_quantity", "is_mandatory",
		                                  "service_from", "service_to")}
		          for r in sorted(rows, key=lambda r: (r.category or "", r.extra_name or ""))]
		for e in out[p]:
			e["amount"] = to_str(from_db(e["amount"], e["currency"]))
	return out


def _strip_names(rows: dict) -> dict:
	for extras in rows.values():
		for e in extras:
			e.pop("name", None)   # internal record id, used only to find translations
	return rows


def _market(site, market: str | None, country: str | None) -> str:
	markets = [versions.MarketDef(m.name, frozenset(_csv(m.countries)), bool(m.is_global), bool(m.disabled))
	           for m in frappe.get_all("TEX Market", fields=["name", "countries", "is_global", "disabled"])]
	try:
		code, _how = versions.resolve_market(explicit=market, country=country, markets=markets,
		                                     default=site.default_market)
	except versions.MarketResolutionError as e:
		# a clean 417 the booking app can act on (it retries without the deep link)
		frappe.throw(str(e), frappe.ValidationError, title=_("Market"))
	return code


# ─── search / quote / book ───────────────────────────────────────────────


@frappe.whitelist(allow_guest=True)
@rate_limit(**SEARCH_LIMIT)
def search(site: str, check_in: str, check_out: str, rooms, currency: str | None = None,
           promo_code: str | None = None, market: str | None = None, country: str | None = None,
           hotel: str | None = None, session_id: str | None = None):
	s = _site(site)
	props = _site_properties(s)
	if hotel:
		if hotel not in props:
			frappe.throw(_("Hotel not found."))
		props = [hotel]
	allowed_ccy = _csv(s.currencies)
	if currency and allowed_ccy and currency not in allowed_ccy:
		frappe.throw(_("Currency not offered."))
	mkt = _market(s, market, country)
	res = quoting.search(properties=props, check_in=check_in, check_out=check_out, rooms=rooms, market=mkt,
	                     channel=_channel(s), currency=currency or s.default_currency or None,
	                     promo_codes=[promo_code] if promo_code else (), internal=False)
	for p in res["properties"]:
		p.pop("messages", None)
		for o in p["unavailable"]:
			o.pop("contract", None)
			o.pop("version", None)
		for o in p["offers"]:
			o.pop("contract", None)
			o.pop("version", None)
	res["market"] = mkt
	content.Localizer(content.guest_language()).search(res)
	_track(s, session_id, "search", {"check_in": check_in, "check_out": check_out, "rooms": parse(rooms, []),
	                                  "market": mkt})
	return res


# a guest sees whether a limited extra can still be booked on a day, and "few left", never
# exact counts (G-19)
LOW_STOCK = 3


@frappe.whitelist(allow_guest=True)
@rate_limit(**SEARCH_LIMIT)
def extras_availability(site: str, hotel: str, check_in: str, check_out: str, session_id: str | None = None):
	s = _site(site)
	if hotel not in _site_properties(s):
		frappe.throw(_("Invalid hotel."))
	ci, co = getdate(check_in), getdate(check_out)
	if co <= ci or (co - ci).days > 60:
		frappe.throw(_("Invalid dates."))
	from kamra.tex.availability import extras_repository as xinv
	from kamra.tex.commercial.context import listed_extras

	online = {e.extra_code for e in listed_extras(hotel, online_only=True)}
	avail = xinv.availability(hotel, online & set(xinv.tracked(hotel)), ci, co)
	return {code: {str(d): {"available": a.remaining > 0 and not a.closed,
	                        "low": 0 < a.remaining <= LOW_STOCK and not a.closed} for d, a in days.items()}
	        for code, days in avail.items()}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(**WRITE_LIMIT)
def quote(site: str, offer_key: str, extras=None, promo_code: str | None = None, session_id: str | None = None):
	s = _site(site)
	offer = quoting.verify(offer_key)
	if offer["property"] not in _site_properties(s) or offer["channel"] != _channel(s):
		frappe.throw(_("Invalid offer."))
	from kamra.tex.commercial.context import listed_extras

	online = {e.extra_code for e in listed_extras(offer["property"], online_only=True)}
	requested = parse(extras, []) or []
	if any(str(e.get("code", "")).upper() not in online for e in requested):
		frappe.throw(_("This extra cannot be booked online."))
	out = quoting.create_quote(offer_key, extras=requested,
	                           promo_codes=[promo_code] if promo_code else None, session_id=session_id)
	if out.get("quote"):
		content.Localizer(content.guest_language()).quote(offer["property"], out["quote"])
	if out.get("ok"):
		_track(s, session_id, "quote", {"quote": out["quote_id"], "total": out["quote"]["totals"]["total"],
		                                "currency": out["quote"]["currency"]})
	return out


def _session_hash(session_id: str | None) -> str | None:
	return hashlib.sha256(session_id.encode()).hexdigest()[:32] if session_id else None


def _site_quotes(s, quote_ids, session_id: str | None) -> list[str]:
	"""Quote ids of this site's hotels and channel, made in the caller's session."""
	ids = [str(q) for q in (parse(quote_ids, []) or [])]
	if not ids or len(ids) > quoting.MAX_ROOMS:
		frappe.throw(_("Select between 1 and {0} rooms.").format(quoting.MAX_ROOMS))
	props = set(_site_properties(s))
	session_hash = _session_hash(session_id)
	for qid in ids:
		row = frappe.db.get_value("TEX Quote", qid, ["property", "session_hash", "sales_channel"], as_dict=True)
		if not row or row.property not in props or row.sales_channel != _channel(s):
			frappe.throw(_("Invalid quote."))
		if row.session_hash and row.session_hash != session_hash:
			frappe.throw(_("Invalid quote."))
	return ids


def _country(value) -> str | None:
	"""A Frappe Country name from a country name or an ISO 3166-1 alpha-2 code."""
	v = text(value, 140)
	if not v:
		return None
	if frappe.db.exists("Country", v):
		return v
	if len(v) == 2 and v.isalpha():
		return frappe.db.get_value("Country", {"code": v.lower()}, "name")
	return None


@frappe.whitelist(allow_guest=True)
@rate_limit(**SEARCH_LIMIT)
def basket(site: str, quote_ids, session_id: str | None = None):
	"""Server total of the selected rooms and, for every payment method the guest may
	choose, the amount due now (each rate plan's deposit rule) — before booking."""
	from kamra.tex.payments import service as pay

	s = _site(site)
	loaded = [quoting.load_quote(qid) for qid in _site_quotes(s, quote_ids, session_id)]
	out = booking_svc.quotes_summary(loaded, None)
	methods = []
	for m in pay.payment_methods(out["property"], market=out["market"], currency=out["currency"],
	                             channel=_channel(s)):
		if m["method"] == "Pay at Hotel" and not out["pay_at_hotel_allowed"]:
			per = None
		else:
			per = booking_svc.quotes_summary(loaded, m["method"])
			# anything due now needs a gateway / bank account behind the method (as in book)
			if per["payment_required"] and not m["provider_account"]:
				per = None
		methods.append({"method": m["method"], "provider_account": m["provider_account"], "label": m["label"],
		                "provider": m["provider"], "sandbox": m["sandbox"], "available": per is not None,
		                "due_now": per["due_now"] if per else None,
		                "balance_after": per["balance_after"] if per else None})
	for r in out["rooms"]:
		r.pop("payment_policy", None)
	return {"currency": out["currency"], "total": out["total"], "usable": out["usable"],
	        "expires_at": out["expires_at"], "pay_at_hotel_allowed": out["pay_at_hotel_allowed"],
	        "rooms": out["rooms"], "methods": methods}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(**WRITE_LIMIT)
@retry_on_deadlock
def book(site: str, quote_ids, guest, payment_method: str | None = None, provider_account: str | None = None,
         idempotency_key: str | None = None, language: str | None = None, session_id: str | None = None,
         return_url: str | None = None):
	s = _site(site)
	ids = _site_quotes(s, quote_ids, session_id)
	g = parse(guest, {})
	guest_clean = {k: text(g.get(k), 140) for k in ("first_name", "last_name", "email", "phone")}
	guest_clean["special_requests"] = text(g.get("special_requests"), 1000)
	guest_clean["country"] = _country(g.get("country"))
	guest_clean["nationality"] = _country(g.get("nationality"))
	guest_clean.update({k: bool(g.get(k)) for k in ("consent_email", "consent_sms", "consent_whatsapp")})
	_track(s, session_id, "guest_details", {"email": g.get("email")}, consent=bool(g.get("consent_email")))
	method = payment_method or "Card"
	# a retry key only counts within the visitor's own session (no cross-visitor replay)
	result = booking_svc.create_booking(quote_ids=ids, guest=guest_clean, payment_method=method,
	                                    idempotency_key=text(idempotency_key, 140) if session_id else None,
	                                    language=text(language, 10),
	                                    booking_site=s.name, session_id=session_id)
	result["payment"] = None
	if result.get("idempotent_replay"):
		# the first response was lost: the same session gets a short-lived link to its
		# booking (the emailed manage link stays the only long-lived one) and the
		# payment it has not completed yet
		result["manage_token"] = resume_token(result["booking"])
		b = frappe.get_doc("TEX Booking", result["booking"])
		due = from_db(b.amount_due_now, b.currency) - from_db(b.paid_amount, b.currency)
		if b.status == "Pending Payment" and due > 0:
			result["payment"] = _start_booking_payment(
				s, result, due=due, method=method, provider_account=provider_account, language=language,
				customer={"name": b.booker_name, "email": b.booker_email, "phone": b.booker_phone},
				return_url=return_url, replay=True)
		return result
	due = D(result["due_now"])
	if due > 0:
		_track(s, session_id, "payment_started", {"booking": result["booking"]})
		result["payment"] = _start_booking_payment(
			s, result, due=due, method=method, provider_account=provider_account, language=language,
			customer={"name": f"{guest_clean['first_name']} {guest_clean['last_name']}",
			          "email": guest_clean.get("email"), "phone": guest_clean.get("phone"),
			          "country": guest_clean.get("country")},
			return_url=return_url)
	else:
		_track(s, session_id, "booked", {"booking": result["booking"], "total": result["total"]})
	return result


def _start_booking_payment(s, result: dict, *, due, method: str, provider_account: str | None,
                           language: str | None, customer: dict, return_url: str | None,
                           replay: bool = False) -> dict | None:
	from kamra.tex.payments import service as pay

	methods = pay.payment_methods(result["property"], market=result["market"], currency=result["currency"],
	                              channel=_channel(s))
	chosen = next((m for m in methods if m["method"] == method and (not provider_account or
	                                                                 m["provider_account"] == provider_account)),
	              None)
	if not chosen or not chosen["provider_account"]:
		if replay:
			return None
		frappe.throw(_("This payment method is not available."))
	key = f"book:{result['booking']}:{to_str(due)}"
	if replay:
		# restart the original attempt only while it is still open; after a failed or
		# finished one the confirmation page offers pay_booking
		status = frappe.db.get_value("TEX Payment Transaction",
		                             {"idempotency_key": pay.ns_key(result["property"], key, "charge")}, "status")
		if status and status != "Pending":
			return None
	return pay.start_payment(
		property=result["property"], amount=due, currency=result["currency"],
		provider_account=chosen["provider_account"], booking=result["booking"],
		description=_("Booking {0}").format(result["booking"]), locale=language or "en",
		customer={**customer, "ip": getattr(frappe.local, "request_ip", None)},
		return_url=_safe_return_url(s, return_url, result["booking"]) or frappe.utils.get_url(
			f"/book/{s.site_slug}/confirmation/{result['booking']}"),
		idempotency_key=key, method=method)


RESUME_TTL_HOURS = 24


def resume_token(booking: str) -> str:
	"""Signed, short-lived stand-in for the manage token (only ever handed to the
	session that made the booking, on a retried request)."""
	from frappe.utils import add_to_date

	return quoting.sign({"kind": "booking-resume", "booking": booking,
	                     "exp": add_to_date(now_datetime(), hours=RESUME_TTL_HOURS).isoformat()})


@frappe.whitelist(allow_guest=True)
@rate_limit(**SEARCH_LIMIT)
def booking_status(token: str):
	"""Confirmation page / manage link: guest view of a booking by its manage token."""
	b = _booking_by_token(token)
	return _guest_booking(b)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(**WRITE_LIMIT)
def pay_booking(token: str, payment_method: str = "Card", provider_account: str | None = None,
                return_url: str | None = None):
	"""Start (or retry after a failed attempt) the payment still due on a booking,
	authorised by the guest's manage token."""
	from kamra.tex.payments import service as pay

	b = _booking_by_token(token)
	ccy = b.currency
	paid = from_db(b.paid_amount, ccy)
	due = (from_db(b.amount_due_now, ccy) if b.status in ("Pending Payment", "Held") else from_db(b.total_amount, ccy))
	due -= paid
	if due <= 0:
		frappe.throw(_("Nothing is due on this booking."))
	if b.status == "Cancelled":
		frappe.throw(_("This booking is cancelled."))
	methods = pay.payment_methods(b.property, market=b.market, currency=ccy, channel=b.sales_channel)
	chosen = next((m for m in methods if m["method"] == payment_method and m["provider_account"]
	               and (not provider_account or m["provider_account"] == provider_account)), None)
	if not chosen:
		frappe.throw(_("This payment method is not available."))
	site = frappe.get_cached_doc("TEX Booking Site", b.booking_site) if b.booking_site else None
	default_return = frappe.utils.get_url(f"/book/{site.site_slug}/manage" if site else "/book")
	attempt = frappe.db.count("TEX Payment Transaction", {"booking": b.name, "txn_type": "Charge"}) + 1
	return pay.start_payment(
		property=b.property, amount=due, currency=ccy, provider_account=chosen["provider_account"], booking=b.name,
		description=_("Booking {0}").format(b.name), locale=b.language or "en",
		customer={"name": b.booker_name, "email": b.booker_email, "phone": b.booker_phone,
		          "ip": getattr(frappe.local, "request_ip", None)},
		return_url=(_safe_return_url(site, return_url, b.name) if site else None) or default_return,
		idempotency_key=f"book:{b.name}:{to_str(due)}:{attempt}", method=payment_method)


# ─── payment callbacks & links ───────────────────────────────────────────


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=30, seconds=60)
def mock_pay(transaction: str, outcome: str, sig: str):
	"""Sandbox payment page action (only Mock provider accounts reach this)."""
	import hmac

	from kamra.tex.payments import service as pay
	from kamra.tex.payments.providers.base import ProviderError
	from kamra.tex.payments.providers.simple import mock_signature

	if frappe.db.get_value("TEX Payment Transaction", transaction, "provider") != "Mock":
		frappe.throw(_("Not a sandbox payment."))
	# the signature first: a replay of a finished payment tells nothing to whoever cannot sign it (G-10)
	if outcome not in ("success", "fail") or not hmac.compare_digest(
			mock_signature(pay._mock_secret(), transaction, outcome), str(sig or "")):
		raise ProviderError("invalid mock signature")
	out = pay.complete(transaction, params={"outcome": outcome, "sig": sig})
	txn = frappe.db.get_value("TEX Payment Transaction", transaction, ["booking", "payment_link", "return_url"],
	                          as_dict=True)
	return {**out, "booking": txn.booking, "return_url": txn.return_url}


@frappe.whitelist(allow_guest=True)
@rate_limit(**SEARCH_LIMIT)
def payment_link(token: str):
	from kamra.tex.payments import service as pay

	link = pay.link_by_token(token)
	methods = pay.payment_methods(link.property, market=None, currency=link.currency, channel="DIRECT_WEB")
	return {"description": link.description, "amount": to_str(from_db(link.amount, link.currency)),
	        "paid": to_str(from_db(link.paid_amount, link.currency)), "currency": link.currency,
	        "status": link.status, "expires_at": str(link.expires_at), "guest_name": link.guest_name,
	        "hotel": frappe.db.get_value("Property", link.property, "property_name"),
	        "methods": [m for m in methods if m["method"] == "Card"]}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(**WRITE_LIMIT)
def pay_link(token: str, provider_account: str | None = None):
	from kamra.tex.payments import service as pay

	link = pay.link_by_token(token)
	if link.status not in ("Active", "Partially Paid"):
		frappe.throw(_("This payment link is {0}.").format(link.status.lower()))
	due = from_db(link.amount, link.currency) - from_db(link.paid_amount, link.currency)
	methods = {m["provider_account"] for m in pay.payment_methods(link.property, market=None, currency=link.currency,
	                                                               channel="DIRECT_WEB") if m["method"] == "Card"}
	if link.provider_account:
		# the hotel fixed the gateway for this link; the guest cannot choose another
		if provider_account and provider_account != link.provider_account:
			frappe.throw(_("This payment method is not available."))
		account = link.provider_account
	else:
		account = provider_account or (sorted(methods)[0] if len(methods) == 1 else None)
		if not account or account not in methods:
			frappe.throw(_("No card payment is configured for this link."))
	return pay.start_payment(property=link.property, amount=due, currency=link.currency, provider_account=account,
	                         payment_link=link.name, booking=None, description=link.description or link.name,
	                         customer={"name": link.guest_name, "email": link.guest_email,
	                                   "ip": getattr(frappe.local, "request_ip", None)},
	                         # never the link's bearer token: the guest's tab remembers its link page (G-10)
	                         return_url=frappe.utils.get_url("/book/pay/return"),
	                         idempotency_key=f"link:{link.name}:{to_str(due)}:{frappe.generate_hash(length=6)}")


# ─── funnel ──────────────────────────────────────────────────────────────


def _track(site, session_id: str | None, event: str, payload: dict, *, consent: bool = False) -> None:
	if not session_id:
		return
	email = (payload or {}).pop("email", None) if isinstance(payload, dict) else None
	try:
		frappe.get_doc({
			"doctype": "TEX Funnel Event", "event": event, "occurred_at": now_datetime(), "site": site.name,
			"property": site.property, "session_id": text(session_id, 64),
			"email_hash": hashlib.sha256(email.strip().lower().encode()).hexdigest() if email else None,
			"consent_marketing": 1 if consent else 0,
			"payload": json.dumps(payload or {}, default=str)[:4000]}).insert(ignore_permissions=True)
	except Exception:
		log_exception("TEX funnel event")


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=120, seconds=60)
def track(site: str, session_id: str, event: str, payload=None):
	if event not in ("room_view", "abandoned"):
		frappe.throw(_("Unknown event."))
	_track(_site(site), session_id, event, parse(payload, {}) or {})
	return {"ok": True}


# ─── self-service (R-42) ─────────────────────────────────────────────────


def _booking_by_token(token: str):
	if not token or len(token) < 20 or len(token) > 1000:
		frappe.throw(_("Invalid link."), frappe.PermissionError)
	if "." in token:   # manage tokens are url-safe base64 (no dots); resume tokens are signed
		try:
			name = quoting.verify(token, kind="booking-resume")["booking"]
		except frappe.ValidationError:
			frappe.clear_messages()
			frappe.throw(_("Invalid link."), frappe.PermissionError)
	else:
		name = frappe.db.get_value("TEX Booking", {"manage_token_hash": booking_svc.token_hash(token)})
	if not name:
		frappe.throw(_("Invalid link."), frappe.PermissionError)
	b = frappe.get_doc("TEX Booking", name)
	if b.manage_token_expires and get_datetime(b.manage_token_expires) < now_datetime():
		frappe.throw(_("This link has expired."), frappe.PermissionError)
	return b


def _self_service_allowed(b) -> bool:
	site_ok = not b.booking_site or bool(frappe.db.get_value("TEX Booking Site", b.booking_site,
	                                                          "self_service_enabled"))
	return site_ok and bool(frappe.db.get_value("Property", b.property, "tex_self_service"))


def _guest_booking(b) -> dict:
	summary = booking_svc.booking_summary(b.name)
	loc = content.Localizer(content.guest_language() or content.guest_language(b.language))
	rooms = []
	for r in summary["rooms"]:
		res = frappe.get_doc("Reservation", r["reservation"])
		snap = loc.quote(b.property, json.loads(res.tex_pricing_snapshot or "{}")) or {}
		penalty, _basis = booking_svc.cancellation_penalty(res) if res.status not in ("Cancelled",) else (D(0), {})
		rooms.append({**r, "room_type_name": loc.room_type_name(
			b.property, res.room_type, frappe.db.get_value("Room Type", res.room_type, "room_type_name")),
		              "board": res.tex_board, "child_ages": json.loads(res.tex_child_ages or "[]"),
		              "rate_plan": (snap.get("rate_plan") or {}).get("name"),
		              "refundable": (snap.get("rate_plan") or {}).get("refundable", True),
		              "lines": snap.get("lines"), "extras": [e for e in snap.get("extras") or [] if e.get("ok")],
		              "cancellation_fee_now": to_str(penalty), "pending_change": bool(res.tex_guest_change_pending)})
	return {**summary, "rooms": rooms, "hotel": frappe.db.get_value("Property", b.property, "property_name"),
	        "self_service": _self_service_allowed(b)}


def _own_reservation(b, reservation: str) -> None:
	if reservation not in [r.reservation for r in b.rooms]:
		frappe.throw(_("Invalid reservation."), frappe.PermissionError)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(**WRITE_LIMIT)
def manage_cancel(token: str, reservation: str, reason: str | None = None):
	b = _booking_by_token(token)
	_own_reservation(b, reservation)
	if not _self_service_allowed(b):
		frappe.throw(_("Please contact the hotel to cancel."))
	frappe.flags.tex_source = "Guest"
	out = booking_svc.cancel_reservation(reservation, reason=text(reason, 300) or "Cancelled by guest online",
	                                     source="Guest", _guest_authorized=True)
	frappe.db.set_value("Reservation", reservation, {"tex_guest_change_pending": 1,
	                                                  "tex_guest_change_note": "Guest cancelled online"})
	frappe.db.set_value("TEX Booking", b.name, "guest_change_pending", 1)
	return out


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(**WRITE_LIMIT)
def manage_propose(token: str, reservation: str, changes):
	b = _booking_by_token(token)
	_own_reservation(b, reservation)
	if not _self_service_allowed(b):
		frappe.throw(_("Please contact the hotel to change your booking."))
	allowed = {"check_in", "check_out", "adults", "children", "extras", "board"}
	ch = {k: v for k, v in (parse(changes, {}) or {}).items() if k in allowed}
	p = modification.propose(reservation, ch, basis="CURRENT", _check_permission=False)
	return {"sellable": p["sellable"], "old_total": p["old"]["total"], "new_total": p["proposed"]["totals"].get(
		"total"), "difference": p["difference"], "currency": p["proposed"]["currency"], "warnings": p["warnings"],
	        "lines": p["proposed"].get("lines"), "proposal_token": p["proposal_token"]}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(**WRITE_LIMIT)
@retry_on_deadlock
def manage_apply(token: str, proposal_token: str, note: str | None = None):
	"""Guest accepts a proposal. Higher price → applied, difference collected; lower
	price → per hotel policy: staff approval (default, NOT applied until staff act),
	credit, or automatic refund. Every guest change is flagged for staff attention."""
	b = _booking_by_token(token)
	p = quoting.verify(proposal_token, kind="proposal")
	_own_reservation(b, p["reservation"])
	if not _self_service_allowed(b):
		frappe.throw(_("Please contact the hotel to change your booking."))
	res = frappe.get_doc("Reservation", p["reservation"])
	old = from_db(res.tex_total_amount, res.tex_currency or "EUR")
	new = D(p["new_total"] or 0)
	policy = frappe.db.get_value("Property", b.property, "tex_lower_price_refund") or "Staff approval"
	frappe.flags.tex_source = "Guest"
	if new < old and policy == "Staff approval":
		res.flags.tex_modification = True
		res.tex_guest_change_pending = 1
		res.tex_guest_change_note = (f"Guest requests change (−{to_str(old - new)} {res.tex_currency}); "
		                             f"proposal: {json.dumps(p['changes'], default=str)} {text(note, 300) or ''}")
		res.save(ignore_permissions=True)
		frappe.db.set_value("TEX Booking", b.name, "guest_change_pending", 1)
		return {"status": "requested", "message": _("Your request was sent to the hotel for approval.")}
	out = modification.apply(proposal_token, reason=text(note, 300) or "Guest self-service change", source="Guest",
	                         _guest_authorized=True)
	frappe.db.set_value("Reservation", p["reservation"], {"tex_guest_change_pending": 1,
	                                                       "tex_guest_change_note": "Guest changed online"})
	frappe.db.set_value("TEX Booking", b.name, "guest_change_pending", 1)
	summary = booking_svc.booking_summary(b.name)
	return {"status": "applied", **out, "balance": summary["balance"]}

