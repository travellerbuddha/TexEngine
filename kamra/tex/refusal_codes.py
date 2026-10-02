"""Stable codes of the refusals a guest can meet (G-70, ADR-013 amendment).

The guest API (``kamra/tex/api/public.py``) puts a refusal's code in its error body (``tex_code``, next to
Frappe's ``exc_type`` and message) so the booking app tells refusals apart by code, never by wording, and shows
its own text in the guest's language. A code is UPPER_SNAKE and never changes meaning once released. The list is
the inventory of guest-reachable refusals (HANDOFF_STAGE3 §5f); a new refusal adds its code here.

Pure data — importable without frappe.
"""

from __future__ import annotations

ORDERED: tuple[str, ...] = (
	# the site, the request, the caller (no specific code: what ``refusals.coded`` falls back to)
	"SITE_NOT_FOUND", "SITE_CLOSED", "RATE_LIMITED", "BUSY", "INVALID_REQUEST", "NOT_FOUND", "NOT_PERMITTED",
	"HOTEL_NOT_FOUND", "CURRENCY_NOT_OFFERED",
	# the market of a search or a booking (O-8, ADR-070)
	"MARKET_UNKNOWN", "MARKET_AMBIGUOUS", "MARKET_REQUIRED", "MARKET_NOT_ALLOWED", "MARKET_RESIDENCY",
	# the stay and the party
	"DATES_INVALID", "STAY_TOO_LONG", "CHECKIN_PAST", "ROOMS_COUNT", "PARTY_INVALID", "CHILD_AGE_REQUIRED",
	"CHILD_AGE_INVALID", "CHILD_DOB_INVALID", "CHILD_DOB_FUTURE", "CHILD_TOO_OLD",
	# offers, quotes and the rate
	"OFFER_INVALID", "OFFER_EXPIRED", "EXTRA_NOT_ONLINE", "EXTRAS_INVALID", "SEARCH_AGAIN", "QUOTE_INVALID",
	"QUOTE_EXPIRED", "QUOTE_USED", "NOT_ON_SALE", "CONTRACT_NOT_ON_SALE", "CONTRACT_SUSPENDED", "RATE_UNAVAILABLE",
	"ROOM_NOT_SOLD",
	"BASKET_NOT_TOGETHER", "SOLD_OUT", "STAY_RESTRICTED", "EXTRA_SOLD_OUT", "WEB_TRANSFER_ROOMS",
	"PAY_AT_HOTEL_NOT_ALLOWED",
	# the guest's details and promotions
	"GUEST_FIRST_NAME_REQUIRED", "GUEST_LAST_NAME_REQUIRED", "GUEST_CONTACT_REQUIRED", "GUEST_EMAIL_INVALID",
	"GUEST_NAME_TOO_LONG", "PROMO_EXHAUSTED", "PROMO_NEEDS_CONTACT", "PROMO_ALREADY_USED",
	# payments and holds
	"PAYMENT_METHOD_UNAVAILABLE", "PAYMENT_BUSY", "PAYMENT_UNDER_REVIEW", "NOTHING_DUE", "RETURN_URL_INVALID",
	"PAYMENT_ALREADY_PROCESSED", "PAYMENT_MISMATCH", "PAYMENT_START_FAILED", "CHARGE_SUPERSEDED", "HOLD_EXPIRED",
	"HOLD_EXPIRED_TRANSFER", "BOOKING_CANCELLED",
	# payment links and the sandbox
	"LINK_INVALID", "LINK_EXPIRED", "LINK_PAID", "LINK_CANCELLED", "LINK_CLOSED", "LINK_CURRENCY",
	"LINK_BOOKING_CLOSED", "LINK_BOOKING_PAID", "LINK_OVER_OWED", "LINK_NO_CARD", "LINK_TOO_MANY_ATTEMPTS",
	"SANDBOX_ONLY", "PAYMENT_SIGNATURE_INVALID", "PAYMENT_UNKNOWN",
	# the guest's booking page (manage link)
	"MANAGE_LINK_INVALID", "MANAGE_LINK_EXPIRED", "MANAGE_RESERVATION_INVALID", "MANAGE_REQUEST_INVALID",
	"SELF_SERVICE_OFF", "CANCEL_TOO_LATE", "CHANNEL_BOOKING", "ROOM_NOT_ACTIVE", "CHANGE_REFUSED",
	"PAYMENT_PENDING", "REFUND_PENDING", "CHANGE_APPLYING", "CHANGE_NOT_SELLABLE", "CHANGE_NOT_ONLINE",
	"NOT_TEX_PRICED", "PROPOSAL_INVALID", "PROPOSAL_EXPIRED", "CURRENCY_CHANGED", "RESERVATION_CHANGED",
	"PRICE_MOVED", "CHANGE_NOT_MADE", "EXTRAS_REFUSED",
)

CODES: frozenset[str] = frozenset(ORDERED)

# the refusals of a market link or a market's residency rule (O-8, G-55b): the booking app searches again
# without the link and says why
MARKET_REFUSALS: frozenset[str] = frozenset(
	{"MARKET_UNKNOWN", "MARKET_AMBIGUOUS", "MARKET_REQUIRED", "MARKET_NOT_ALLOWED", "MARKET_RESIDENCY"})
