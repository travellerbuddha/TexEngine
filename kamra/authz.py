"""Endpoint authorization - Frappe checks doctype permissions on ORM
paths, but raw-SQL reads and db.set_value writes sail past them. Every
whitelisted Kamra endpoint therefore declares who may call it."""

import inspect
from functools import wraps

import frappe
from frappe import _
from frappe.utils import now_datetime, add_to_date

ADMIN = ("System Manager", "Administrator", "Hotel Admin")

# IT / site admins only - deliberately EXCLUDES the Hotel Admin business role.
# For user management, developer settings and API keys.
IT_ADMIN = ("System Manager", "Administrator")

PIN_MAX_ATTEMPTS = 5
PIN_LOCK_MINUTES = 15


def require_it_admin(fn):
	"""Stricter than require_roles: System / site administrators only, not the
	Hotel Admin (GM) business role. Place below @frappe.whitelist()."""

	@wraps(fn)
	def guarded(*args, **kwargs):
		if not set(IT_ADMIN) & set(frappe.get_roles()):
			frappe.throw(
				"Needs a System / site administrator (IT).", frappe.PermissionError)
		return fn(*args, **kwargs)

	return guarded


# TEX tenancy (ADR-011): arguments that pin an endpoint to one hotel. A role alone
# is not enough - the hotel behind the argument must be in the caller's scope.
SCOPED_ARGS = (("property", None), ("reservation", "Reservation"), ("folio", "Folio"),
               ("room", "Room"), ("room_type", "Room Type"), ("group_booking", "Group Booking"))

# Record arguments beyond SCOPED_ARGS (G-02). Legacy modules reuse argument names for
# different records (`order` is a POS order in pos.py and a laundry order in
# laundry.py), so they are declared per module, and per endpoint where one module
# reuses a name. The record's `property` must be in the caller's scope.
GUEST = "Guest"  # visible to the caller (kamra.tex.security.perm)
GUEST_OWNED = "Guest (owned)"  # destructive: every stay of the guest in the caller's scope
USER = "User"  # a colleague: shares a hotel with the caller, never a platform admin

RECORD_ARGS = {
	"kamra.api": {"task": "Housekeeping Task", "ticket": "Service Ticket", "from_folio": "Folio",
	              "to_folio": "Folio", "new_room": "Room", "rate_plan": "Rate Plan",
	              "meal_plan": "Meal Plan", "venue": "Venue", "guest": GUEST},
	"kamra.agents_api": {"name": "Agent Action Log"},
	"kamra.assistant": {"name": "Copilot Conversation"},
	"kamra.banquet": {"function": "Venue Booking", "venue": "Venue", "menu": "Banquet Menu",
	                  "service_item": "Banquet Service Item", "outlet": "POS Outlet", "guest": GUEST},
	"kamra.banquet_ops": {"function": "Venue Booking", "task": "Banquet Function Task"},
	"kamra.cashier": {"session": "Cashier Session"},
	"kamra.channel_manager": {"connection": "Channel Manager Connection"},
	"kamra.inventory": {"name": "Ingredient", "ingredient": "Ingredient", "outlet": "POS Outlet",
	                    "menu_item": "Menu Item"},
	"kamra.laundry": {"name": "Laundry Rate", "order": "Laundry Order"},
	"kamra.ledger": {"account": "City Ledger Account", "folios": "Folio", "group": "Group Booking",
	                 "guest": GUEST},
	"kamra.marketplace": {"connection": "Channel Provider Connection"},
	"kamra.menu_import": {"outlet": "POS Outlet"},
	"kamra.pos": {"order": "POS Order", "outlet": "POS Outlet"},
}
ENDPOINT_RECORD_ARGS = {
	"kamra.api.save_hurdle_rate": {"name": "Hurdle Rate"},
	"kamra.api.delete_hurdle_rate": {"name": "Hurdle Rate"},
	"kamra.api.release_room_block": {"name": "Room Block"},
	"kamra.api.merge_guests": {"source": GUEST_OWNED, "target": GUEST_OWNED},
	"kamra.api.anonymize_guest": {"guest": GUEST_OWNED},
	"kamra.api.hk_assign_task": {"user": USER},
	"kamra.api.reset_cashier_pin": {"user": USER},
	"kamra.banquet.save_banquet_menu": {"name": "Banquet Menu"},
	"kamra.banquet.delete_banquet_menu": {"name": "Banquet Menu"},
	"kamra.banquet.save_service_item": {"name": "Banquet Service Item"},
	"kamra.banquet.delete_service_item": {"name": "Banquet Service Item"},
	"kamra.banquet.save_dish": {"name": "Banquet Dish"},
	"kamra.banquet.delete_dish": {"name": "Banquet Dish"},
}


def record_args(fn) -> dict:
	"""The record arguments an endpoint takes, with the DocType behind each."""
	module = getattr(fn, "__module__", "")
	return {**RECORD_ARGS.get(module, {}),
	        **ENDPOINT_RECORD_ARGS.get(f"{module}.{getattr(fn, '__name__', '')}", {})}


def _values(value) -> list[str]:
	"""An argument's record names: one name, or a JSON / list of names (batch endpoints)."""
	if isinstance(value, str) and value.lstrip().startswith("["):
		try:
			value = frappe.parse_json(value)
		except Exception:
			return [value]
	if isinstance(value, (list, tuple)):
		return [v for v in value if isinstance(v, str) and v]
	return [value] if isinstance(value, str) and value else []


def _guest_allowed(name: str, permitted: set[str], owned: bool) -> bool:
	guest = frappe.db.get_value("Guest", name, ["name", "tex_enterprise"], as_dict=True)
	if not guest:
		return True  # the endpoint reports the missing profile
	from kamra.tex.security.perm import _guest_visible
	if not _guest_visible(guest, frappe.session.user):
		return False
	if not owned:
		return True
	stays = set(frappe.get_all("Reservation", filters={"guest": name}, pluck="property", distinct=True))
	return stays <= permitted


def _user_allowed(user: str, permitted: set[str]) -> bool:
	from kamra.tex.security import scope
	if not frappe.db.exists("User", user):
		return True
	if scope.is_platform_admin(user):
		return False
	return bool(scope.permitted_properties(user) & permitted)


def assert_scope(sig, args, kwargs, records=None):
	"""Refuse a call whose hotel argument, or a record argument (reservation, folio,
	POS order, banquet function, guest ...), belongs to a hotel outside the user's
	TEX scope. A record without a hotel (platform-wide) or not found is left to the
	endpoint."""
	try:
		bound = sig.bind_partial(*args, **kwargs).arguments if sig else kwargs
	except TypeError:
		bound = kwargs
	checks = [(doctype, value) for arg, doctype in (*SCOPED_ARGS, *(records or {}).items())
	          for value in _values(bound.get(arg))]
	if not checks:
		return
	from kamra.tex.security import scope
	if scope.is_platform_admin():
		return
	permitted = scope.permitted_properties()
	for doctype, value in checks:
		_check(doctype, value, permitted)


def _check(doctype, value: str, permitted: set[str]) -> None:
	if doctype in (GUEST, GUEST_OWNED):
		if not _guest_allowed(value, permitted, doctype == GUEST_OWNED):
			frappe.throw(_("You don't have access to this guest."), frappe.PermissionError)
		return
	if doctype == USER:
		if not _user_allowed(value, permitted):
			frappe.throw(_("You don't have access to this user."), frappe.PermissionError)
		return
	prop = value if doctype is None else frappe.db.get_value(doctype, value, "property")
	if prop and prop not in permitted:
		frappe.throw(_("You don't have access to {0}.").format(prop), frappe.PermissionError)


def assert_record(doctype: str, name: str) -> None:
	"""assert_scope for a record named at run time (e.g. linked_records(doctype, name))."""
	from kamra.tex.security import scope
	if not name or scope.is_platform_admin():
		return
	_check(GUEST if doctype == "Guest" else doctype, name, scope.permitted_properties())


def property_scope() -> list[str] | None:
	"""The hotels a list endpoint may read: None for platform administrators (all),
	else the caller's hotels (never empty - [""] matches nothing)."""
	from kamra.tex.security import scope
	if scope.is_platform_admin():
		return None
	return sorted(scope.permitted_properties()) or [""]


def legacy_pms_enabled() -> bool:
	"""TEX Settings > Show legacy PMS modules. Off, the PMS (front desk, housekeeping,
	POS, laundry, banquet, cashier...) is closed to hotel users - in the backend, not
	only in the navigation (G-16). Sites without TEX Settings are plain Kamra sites."""
	try:
		return bool(frappe.db.get_single_value("TEX Settings", "show_legacy_pms", cache=True))
	except Exception:
		return True


def legacy_pms_open_to_user() -> bool:
	from kamra.tex.security import scope

	return legacy_pms_enabled() or scope.is_platform_admin()


def require_roles(*roles):
	"""Allow the listed roles (plus admins), at hotels in the caller's scope.
	Usage - below the whitelist decorator so the registered function is the
	guarded one:

	    @frappe.whitelist()
	    @require_roles("Front Desk", "Kamra Agent")
	    def check_in(...): ...
	"""
	allowed = set(roles) | set(ADMIN)

	def deco(fn):
		try:
			sig = inspect.signature(fn)
		except (TypeError, ValueError):
			sig = None
		records = record_args(fn)

		@wraps(fn)
		def guarded(*args, **kwargs):
			if not allowed & set(frappe.get_roles()):
				frappe.throw(
					f"Not permitted - needs one of: {', '.join(sorted(roles))}.",
					frappe.PermissionError)
			if not legacy_pms_open_to_user():
				frappe.throw(_("The PMS modules are switched off on this site."), frappe.PermissionError)
			assert_scope(sig, args, kwargs, records)
			return fn(*args, **kwargs)
		# introspectable RBAC: Kamra Agent filters its tool list by this
		guarded._kamra_roles = allowed
		return guarded
	return deco


def _pin_locked(doc) -> bool:
	if not doc.get("locked_until"):
		return False
	return now_datetime() < doc.locked_until


def require_cashier_pin(property: str, pin=None):
	"""The walk-up-to-an-unlocked-terminal guard: money actions re-confirm
	WHO is acting with a personal PIN, even inside a valid session.

	Skipped for agents (Kamra Agent role, the copilot's in-process tool calls,
	and gated replays) - their identity and accountability come from the
	autonomy gate + action log, not a keypad. Off unless the property enables
	require_cashier_pin.

	Supports a short unlock window via frappe.cache (set by verify_cashier_pin).
	"""
	if not property or not frappe.db.get_value(
			"Property", property, "require_cashier_pin"):
		return
	if getattr(frappe.flags, "kamra_agent_call", False) or \
	   getattr(frappe.flags, "kamra_gate_bypass", False):
		return
	if "Kamra Agent" in frappe.get_roles():
		return
	user = frappe.session.user
	if user == "Administrator":
		return

	# Sliding unlock window (set after a successful PinPad entry)
	cache_key = f"kamra_cashier_unlock:{user}"
	if frappe.cache.get_value(cache_key):
		# refresh sliding window
		frappe.cache.set_value(cache_key, 1, expires_in_sec=PIN_LOCK_MINUTES * 60)
		return

	if not frappe.db.exists("Cashier PIN", user):
		frappe.throw("PIN_NOT_SET: set your cashier PIN first (ask for it on "
		             "this screen), then retry.")
	doc = frappe.get_doc("Cashier PIN", user)
	if doc.get("must_reset"):
		frappe.throw("PIN_MUST_RESET: your PIN was reset by an admin - "
		             "enroll a new PIN first.")
	if _pin_locked(doc):
		frappe.throw("PIN_LOCKED: too many wrong attempts - try again later.")
	if not pin:
		frappe.throw("PIN_REQUIRED: this action needs your cashier PIN.")
	from frappe.utils.password import get_decrypted_password
	stored = get_decrypted_password("Cashier PIN", user, "pin",
	                                raise_exception=False)
	if not stored or str(pin).strip() != str(stored):
		attempts = int(doc.pin_attempts or 0) + 1
		doc.pin_attempts = attempts
		if attempts >= PIN_MAX_ATTEMPTS:
			doc.locked_until = add_to_date(now_datetime(),
			                               minutes=PIN_LOCK_MINUTES)
			doc.pin_attempts = 0
			doc.save(ignore_permissions=True)
			frappe.throw("PIN_LOCKED: too many wrong attempts - locked for "
			             f"{PIN_LOCK_MINUTES} minutes.")
		doc.save(ignore_permissions=True)
		frappe.throw("Wrong cashier PIN.")
	# success
	if doc.pin_attempts or doc.locked_until:
		doc.pin_attempts = 0
		doc.locked_until = None
		doc.save(ignore_permissions=True)
	frappe.cache.set_value(cache_key, 1, expires_in_sec=PIN_LOCK_MINUTES * 60)


def unlock_cashier_session(property: str, pin: str) -> dict:
	"""Explicit PinPad verify: validates PIN and opens the unlock window."""
	# Clear any existing unlock so we always re-validate
	frappe.cache.delete_value(f"kamra_cashier_unlock:{frappe.session.user}")
	require_cashier_pin(property, pin)
	return {"ok": True, "unlocked_minutes": PIN_LOCK_MINUTES}


def cashier_unlock_status(property: str) -> dict:
	required = bool(property and frappe.db.get_value(
		"Property", property, "require_cashier_pin"))
	user = frappe.session.user
	has_pin = bool(frappe.db.exists("Cashier PIN", user))
	must_reset = False
	locked = False
	if has_pin:
		doc = frappe.get_doc("Cashier PIN", user)
		must_reset = bool(doc.get("must_reset"))
		locked = _pin_locked(doc)
	unlocked = bool(frappe.cache.get_value(f"kamra_cashier_unlock:{user}"))
	return {
		"required": required,
		"has_pin": has_pin,
		"must_reset": must_reset,
		"locked": locked,
		"unlocked": unlocked or not required or user == "Administrator",
	}
