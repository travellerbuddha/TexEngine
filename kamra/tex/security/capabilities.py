"""Capability registry and default role profiles (ADR-011, SECURITY_MODEL §3).

Pure data — importable without frappe.
"""

from __future__ import annotations

CAPABILITIES: dict[str, str] = {
	"price.view": "View selling prices and quotes",
	"price.view_cost": "View contract cost, markup and margin",
	"price.override": "Override a price manually (with reason)",
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
	"report.view": "View commercial reports",
	"booking_site.edit": "Configure booking engine sites and widgets",
	"connect.admin": "Configure integrations",
	"settings.admin": "Hotel settings",
	"user.admin": "Manage users and access grants",
}

ALL = frozenset(CAPABILITIES)

_SALES = {"price.view", "reservation.view", "reservation.create", "reservation.modify", "reservation.cancel",
          "payment.view", "payment.link", "crm.view", "crm.edit"}

ROLE_DEFAULTS: dict[str, frozenset[str]] = {
	"Hotel Admin": ALL,
	"Revenue Manager": frozenset({
		"price.view", "price.view_cost", "price.override", "contract.edit", "contract.publish", "promotion.edit",
		"markup.edit", "fx.edit", "inventory.edit", "restriction.edit", "reservation.view", "reservation.create",
		"reservation.modify", "reservation.confirm_unpaid", "report.view", "booking_site.edit", "crm.view",
		"loyalty.edit"}),
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


def validate_capability(cap: str) -> None:
	if cap not in CAPABILITIES:
		raise ValueError(f"unknown capability {cap!r}")
