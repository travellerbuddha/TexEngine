"""Capability registry and default role profiles (ADR-011, SECURITY_MODEL §3).

Pure data — importable without frappe.
"""

from __future__ import annotations

CAPABILITIES: dict[str, str] = {
	"price.view": "View selling prices and quotes",
	"price.view_cost": "View contract cost, markup and margin",
	"price.override": "Override a price manually (with reason)",
	"price.any_channel": "Price and book on every sales channel, not only the profile's own channels",
	"contract.edit": "Create and edit contracts and draft versions",
	"contract.publish": "Publish, schedule and withdraw contract versions",
	"promotion.edit": "Manage promotions and coupons",
	"markup.edit": "Manage markup rules",
	"fx.edit": "Manage FX policies and manual rates",
	"tax.edit": "Manage the hotel's tax policy (VAT, accommodation tax, levies)",
	"inventory.edit": "Edit inventory, allotments and closures",
	"restriction.edit": "Edit restrictions (stop sell, LOS, CTA/CTD…)",
	"reservation.view": "View reservations",
	"reservation.create": "Create reservations and bookings",
	"reservation.modify": "Modify reservations",
	"reservation.cancel": "Cancel reservations",
	"reservation.confirm_unpaid": "Confirm a booking before its deposit is paid",
	"payment.view": "View payments",
	"payment.link": "Create and send payment links",
	"payment.refund": "Refund and reallocate payments",
	"crm.view": "View guest profiles",
	"crm.edit": "Edit guest profiles, notes, consent",
	"guest.export": "Export guest data",
	"loyalty.edit": "Edit loyalty programs: earn rules, tiers, point value, blackouts",
	"channel.view": "See channel distribution: mappings, ARI sent, bookings received, reconciliation",
	"channel.manage": "Manage channel distribution: mappings, pushes, retries",
	"report.view": "View commercial reports",
	"booking_site.edit": "Configure booking engine sites and widgets",
	"connect.admin": "Configure integrations",
	"settings.admin": "Hotel settings",
	"user.admin": "Manage users and access grants",
	"system.monitor": "See system status: background jobs, queues, payment callbacks, FX rates and e-mail delivery",
}

ALL = frozenset(CAPABILITIES)

_SALES = {"price.view", "reservation.view", "reservation.create", "reservation.modify", "reservation.cancel",
          "payment.view", "payment.link", "crm.view", "crm.edit"}

ROLE_DEFAULTS: dict[str, frozenset[str]] = {
	"Hotel Admin": ALL,
	"Revenue Manager": frozenset({
		"price.view", "price.view_cost", "price.override", "price.any_channel", "contract.edit", "contract.publish",
		"promotion.edit", "markup.edit", "fx.edit", "inventory.edit", "restriction.edit", "reservation.view",
		"reservation.create", "reservation.modify", "reservation.confirm_unpaid", "report.view", "booking_site.edit", "crm.view",
		"loyalty.edit", "channel.view", "channel.manage"}),
	"Front Desk": frozenset(_SALES),
	"Call Center Agent": frozenset(_SALES),
	# tax rules are a legal/finance setting: Finance and Hotel Admin, not revenue management
	"Finance": frozenset({"price.view", "price.view_cost", "reservation.view", "reservation.confirm_unpaid",
	                      "payment.view", "payment.link", "payment.refund", "report.view", "crm.view", "tax.edit"}),
	"Kamra Agent": frozenset({"price.view", "reservation.view", "reservation.create", "reservation.modify"}),
}

# Default permission profiles seeded on install (patch T1); grants reference them.
DEFAULT_PROFILES: dict[str, frozenset[str]] = {
	"Hotel Admin": ALL,
	"Group Admin": ALL,
	"Enterprise Admin": ALL,
	"Revenue Manager": ROLE_DEFAULTS["Revenue Manager"],
	"Reservations Agent": ROLE_DEFAULTS["Call Center Agent"],
	"Finance": ROLE_DEFAULTS["Finance"],
	"Viewer": frozenset({"price.view", "reservation.view", "report.view"}),
}

PLATFORM_ROLES = ("System Manager", "Administrator")

# ─── sales-channel entitlement (ADR-050) ─────────────────────────────────
# A staff user prices and books only on the channels they are entitled to at a hotel: those
# of their permission profiles there, the call centre for a profile that names none, every
# channel with ``price.any_channel``. The request never decides. A profile's channels serve
# only what that profile allows (review follow-up): pricing channels come from profiles that
# may see prices, booking channels from profiles that may book.
ANY_CHANNEL = "price.any_channel"
PRICE = "price.view"
BOOK = "reservation.create"
STAFF_DEFAULT_CHANNELS = frozenset({"CALL_CENTER"})
# what a booking site sells on: the channels a guest may book on (ADR-050 review)
WEB_CHANNELS = frozenset({"DIRECT_WEB", "META"})


def profile_channels(caps, listed, every_channel, *, for_cap: str) -> frozenset[str]:
	"""Channels one permission profile (or a user's Frappe role defaults, ``listed`` empty)
	lets its holder use for ``for_cap`` (``PRICE`` or ``BOOK``). ``every_channel``: all channel
	codes known to the site. A profile without ``for_cap`` adds no channel for it."""
	every = frozenset(every_channel)
	caps = frozenset(caps)
	if for_cap not in caps:
		return frozenset()
	if ANY_CHANNEL in caps:
		return every
	return (frozenset(listed) or STAFF_DEFAULT_CHANNELS) & every


def validate_capability(cap: str) -> None:
	if cap not in CAPABILITIES:
		raise ValueError(f"unknown capability {cap!r}")
