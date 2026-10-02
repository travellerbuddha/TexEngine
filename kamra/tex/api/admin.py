"""TEX administration API: access grants, permission profiles, TEX settings, booking
site domains, integrations and the audit trail (R-47, R-48, R-50).

Grants are validated by the TEX Access Grant controller (anti-escalation: nobody
grants a scope or capability they do not hold); profiles and settings are platform
level and need a platform administrator.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from kamra.tex.api._util import as_int, parse, text
from kamra.tex.security import perm, scope
from kamra.tex.security.audit import audit
from kamra.tex.security.capabilities import CAPABILITIES


def _require_platform() -> None:
	if not scope.is_platform_admin():
		frappe.throw(_("Only platform administrators can do this."), frappe.PermissionError)


def _user_admin_props() -> list[str]:
	return sorted(p for p in scope.permitted_properties() if scope.has_capability("user.admin", p))


# ─── users & grants ──────────────────────────────────────────────────────


@frappe.whitelist()
def users():
	"""Users holding a grant that touches a hotel I administer (platform admins: all)."""
	props = set(_user_admin_props())
	if not props:
		frappe.throw(_("Not permitted: {0}.").format("user.admin"), frappe.PermissionError)
	grants = frappe.get_all("TEX Access Grant", fields=["name", "user", "scope_level", "property", "hotel_group",
	                                                     "enterprise", "permission_profile", "valid_until",
	                                                     "disabled", "notes"], order_by="user asc")
	visible = []
	platform = scope.is_platform_admin()
	for g in grants:
		covered = set(scope._grant_properties(g))
		if platform or (covered and covered & props):
			g["valid_until"] = str(g["valid_until"]) if g["valid_until"] else None
			# hotels outside the viewer's own scope are counted, never named
			g["properties"] = sorted(covered if platform else covered & props)
			g["other_hotels"] = 0 if platform else len(covered - props)
			refusal = grants_mod().manage_refusal(frappe._dict(g))
			g["can_manage"] = refusal is None
			g["manage_refusal"] = refusal[0] if refusal else None
			visible.append(g)
	names = sorted({g["user"] for g in visible})
	info = {u.name: u for u in frappe.get_all("User", filters={"name": ("in", names or [""])},
	                                         fields=["name", "full_name", "enabled", "last_login", "user_type"])}
	return {"users": [{"user": u, "full_name": info[u].full_name if u in info else u,
	                   "enabled": info[u].enabled if u in info else 0,
	                   "last_login": str(info[u].last_login) if u in info and info[u].last_login else None,
	                   "grants": [g for g in visible if g["user"] == u]} for u in names],
	        "profiles": frappe.get_all("TEX Permission Profile", fields=["name", "profile_name", "is_system"],
	                                   order_by="profile_name asc")}


@frappe.whitelist(methods=["POST"])
def save_grant(data):
	d = parse(data, {}) or {}
	doc = frappe.get_doc("TEX Access Grant", d["name"]) if d.get("name") else frappe.new_doc("TEX Access Grant")
	if d.get("name"):
		grants_mod().assert_can_manage(doc)    # may I touch the grant as it stands?
	for f in ("user", "scope_level", "property", "hotel_group", "enterprise", "permission_profile", "valid_until",
	          "disabled", "notes"):
		if f in d:
			doc.set(f, d[f] or (0 if f == "disabled" else None))
	if not frappe.db.exists("User", doc.user):
		frappe.throw(_("User {0} does not exist.").format(doc.user))
	doc.save(ignore_permissions=True)     # controller re-validates the new state (anti-escalation)
	return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
def delete_grant(name: str):
	doc = frappe.get_doc("TEX Access Grant", name)
	grants_mod().assert_can_manage(doc)
	frappe.delete_doc("TEX Access Grant", name, ignore_permissions=True)
	return {"ok": True}


def grants_mod():
	from kamra.tex.security import grants

	return grants


@frappe.whitelist(methods=["POST"])
def invite_user(email: str, first_name: str, last_name: str | None = None):
	"""Create a disabled-password Desk user a grant can then be attached to (the user
	sets a password through Frappe's standard reset e-mail)."""
	if not _user_admin_props():
		frappe.throw(_("Not permitted: {0}.").format("user.admin"), frappe.PermissionError)
	email = (text(email, 140) or "").lower()
	if "@" not in email:
		frappe.throw(_("Invalid email address."))
	if frappe.db.exists("User", email):
		return {"user": email, "existing": True}
	u = frappe.get_doc({"doctype": "User", "email": email, "first_name": text(first_name, 80) or email,
	                    "last_name": text(last_name, 80), "user_type": "System User", "send_welcome_email": 1})
	u.insert(ignore_permissions=True)
	audit("user.invite", reference_doctype="User", reference_name=email)
	return {"user": email, "existing": False}


# ─── permission profiles (platform) ──────────────────────────────────────


@frappe.whitelist()
def profiles():
	if not (scope.is_platform_admin() or _user_admin_props()):
		frappe.throw(_("Not permitted: {0}.").format("user.admin"), frappe.PermissionError)
	rows = frappe.get_all("TEX Permission Profile", fields=["name", "profile_name", "description", "is_system"],
	                      order_by="profile_name asc")
	for r in rows:
		r["capabilities"] = sorted(frappe.get_all("TEX Profile Capability", filters={"parent": r["name"]},
		                                          pluck="capability"))
		# blank = the call centre only; price.any_channel = every channel (ADR-050)
		r["sales_channels"] = sorted(scope._profile_listed_channels(r["name"]))
	return {"profiles": rows, "capabilities": CAPABILITIES}


@frappe.whitelist(methods=["POST"])
def save_profile(data):
	_require_platform()
	d = parse(data, {}) or {}
	caps = sorted(set(d.get("capabilities") or []))
	unknown = [c for c in caps if c not in CAPABILITIES]
	if unknown:
		frappe.throw(_("Unknown capabilities: {0}").format(", ".join(unknown)))
	channels = sorted({str(c) for c in d.get("sales_channels") or []})
	unknown = [c for c in channels if not frappe.db.exists("TEX Sales Channel", c)]
	if unknown:
		frappe.throw(_("Unknown sales channels: {0}").format(", ".join(unknown)))
	doc = frappe.get_doc("TEX Permission Profile", d["name"]) if d.get("name") else frappe.new_doc(
		"TEX Permission Profile")
	before = {"capabilities": sorted(r.capability for r in doc.get("capabilities") or []),
	          "sales_channels": sorted(r.sales_channel for r in doc.get("sales_channels") or [])}
	doc.profile_name = text(d.get("profile_name"), 140) or doc.profile_name
	doc.description = text(d.get("description"), 500)
	doc.set("capabilities", [{"capability": c} for c in caps])
	if "sales_channels" in d:
		doc.set("sales_channels", [{"sales_channel": c} for c in channels])
	doc.save(ignore_permissions=True)
	scope.clear_cache()
	audit("profile.save", reference_doctype="TEX Permission Profile", reference_name=doc.name,
	      old=before, new={"capabilities": caps,
	                       "sales_channels": sorted(r.sales_channel for r in doc.get("sales_channels") or [])})
	return {"name": doc.name}


# ─── markets (platform master data, R-13) ────────────────────────────────

MARKET_FIELDS = ("market_code", "market_name", "is_global", "disabled", "countries", "residency_required",
                 "default_currency", "default_language", "parent_market")


def _countries(value) -> set[str]:
	return {c.strip().upper() for c in (value or "").replace("\n", ",").split(",") if c.strip()}


def market_overlaps(code: str, countries: set[str], *, is_global: bool = False) -> list[dict]:
	"""Countries this market shares with another enabled market of the same size: a
	guest from there would get no market automatically (``resolve_market`` refuses to
	guess), so staff must choose — worth knowing before saving."""
	if is_global or not countries:
		return []
	out = []
	for m in frappe.get_all("TEX Market", filters={"disabled": 0, "is_global": 0, "name": ("!=", code)},
	                        fields=["name", "countries"]):
		theirs = _countries(m.countries)
		if len(theirs) != len(countries):
			continue
		shared = sorted(countries & theirs)
		if shared:
			out.append({"market": m.name, "countries": shared})
	return out


@frappe.whitelist()
def markets():
	"""All markets, with the countries each one claims (anyone who works with prices)."""
	if not (scope.is_platform_admin() or scope.has_capability("price.view", None)):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	rows = frappe.get_all("TEX Market", fields=["name", *MARKET_FIELDS, "modified"],
	                      order_by="is_global desc, market_code asc")
	used = {r.market: r.n for r in frappe.db.sql(
		"SELECT market, COUNT(*) AS n FROM `tabTEX Contract` WHERE market IS NOT NULL GROUP BY market",
		as_dict=True)}
	for r in rows:
		r["contracts"] = int(used.get(r["name"], 0))
		r["overlaps"] = market_overlaps(r["name"], _countries(r["countries"]), is_global=bool(r["is_global"])) \
			if not r["disabled"] else []
	return rows


@frappe.whitelist(methods=["POST"])
def save_market(data):
	"""Create or edit a market (platform administrators). The code is fixed once created."""
	_require_platform()
	d = parse(data, {}) or {}
	name = text(d.get("name"), 20)
	doc = frappe.get_doc("TEX Market", name) if name else frappe.new_doc("TEX Market")
	before = {f: doc.get(f) for f in MARKET_FIELDS} if name else None
	if not name:
		code = (text(d.get("market_code"), 20) or "").upper()
		if not code or not code.replace("_", "").isalnum():
			frappe.throw(_("Market code: letters, digits and _ only."))
		if frappe.db.exists("TEX Market", code):
			frappe.throw(_("Market {0} already exists.").format(code))
		doc.market_code = code
	doc.market_name = text(d.get("market_name"), 140) or doc.market_name
	if not doc.market_name:
		frappe.throw(_("Market name is required."))
	doc.is_global = 1 if d.get("is_global") else 0
	doc.disabled = 1 if d.get("disabled") else 0
	doc.countries = text(d.get("countries"), 2000) or ""
	if "residency_required" in d:
		# residents only on the web (O-8, ADR-070); a client that does not send it keeps the market's rule
		doc.residency_required = 1 if d.get("residency_required") else 0
	ccy = text(d.get("default_currency"), 3)
	if ccy and not frappe.db.exists("Currency", ccy):
		frappe.throw(_("Unknown currency {0}.").format(ccy))
	doc.default_currency = ccy or None
	lang = text(d.get("default_language"), 10)
	doc.default_language = lang or None
	parent = text(d.get("parent_market"), 20)
	if parent and (parent == doc.market_code or not frappe.db.exists("TEX Market", parent)):
		frappe.throw(_("Invalid parent market."))
	doc.parent_market = parent or None
	if doc.disabled and not doc.is_new():
		default = frappe.db.get_single_value("TEX Settings", "default_market")
		if default == doc.name:
			frappe.throw(_("The default market cannot be disabled."))
	doc.save(ignore_permissions=True)
	audit("market.save", reference_doctype="TEX Market", reference_name=doc.name, old=before,
	      new={f: doc.get(f) for f in MARKET_FIELDS})
	return {"name": doc.name, "overlaps": market_overlaps(doc.name, _countries(doc.countries),
	                                                      is_global=bool(doc.is_global)) if not doc.disabled else []}


# ─── settings (platform) ─────────────────────────────────────────────────

SETTINGS_FIELDS = ("strict_tenancy", "show_legacy_pms", "brand_name", "support_email", "default_market",
                   "default_sales_channel", "offer_ttl_minutes", "quote_ttl_minutes", "hold_minutes",
                   "hold_minutes_link", "hold_minutes_transfer", "hold_minutes_transfer_web", "manage_link_days",
                   "fx_provider_default", "fx_max_age_days", "status_alert_recipients")


@frappe.whitelist(methods=["POST"])
def set_hotel_live(property: str, live: int = 1, reason: str | None = None):
	"""A TEX hotel goes live in TEX (the Desk stops selling it) or back to onboarding: needs
	``settings.admin`` at the hotel and a reason; audited (ADR-052 review)."""
	from kamra.tex.legacy import set_live

	return set_live(property, bool(as_int(live, 1)), text(reason, 500) or "")


@frappe.whitelist()
def settings():
	_require_platform()
	s = frappe.get_single("TEX Settings")
	return {f: s.get(f) for f in SETTINGS_FIELDS}


@frappe.whitelist(methods=["POST"])
def save_settings(data):
	_require_platform()
	d = parse(data, {}) or {}
	s = frappe.get_single("TEX Settings")
	before = {f: s.get(f) for f in SETTINGS_FIELDS}
	for f in SETTINGS_FIELDS:
		if f in d:
			s.set(f, d[f])
	s.save(ignore_permissions=True)
	after = {f: s.get(f) for f in SETTINGS_FIELDS}
	audit("settings.save", reference_doctype="TEX Settings", reference_name="TEX Settings",
	      old={k: v for k, v in before.items() if before[k] != after[k]},
	      new={k: v for k, v in after.items() if before[k] != after[k]})
	return after


# ─── booking sites ───────────────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def verify_domain(site: str, domain: str):
	from kamra.tex.services import sites

	return sites.verify_domain(site, domain)


@frappe.whitelist()
def embed_snippet(site: str):
	from kamra.tex.services import sites

	s = sites.require_site(site, "price.view")
	base = sites.platform_url()
	return {
		"script": f'<script type="module" src="{base}/assets/kamra/tex/tex-widget.js" defer></script>',
		"element": f'<tex-booking-widget site="{s.site_slug}" api="{base}" mode="{s.widget_mode or "search"}">'
		           f"</tex-booking-widget>",
		# the hotel's own booking host when it has one (G-21)
		"link": sites.guest_url(s).rstrip("/"),
		"allowed_origins": (s.allowed_embed_origins or "").splitlines(),
	}


@frappe.whitelist(methods=["POST"])
def upload_site_image(site: str | None = None, property: str | None = None, hotel_group: str | None = None):
	"""A booking site's logo or hero image, checked on the server (G-83): the bytes must be a
	PNG, JPEG, GIF or WebP image of at most 2 MB (``kamra.tex.security.uploads``). It is public,
	since the site shows it to anonymous guests. ``site`` names a saved site; a site being
	created names the hotel or hotel group it will serve. Needs ``booking_site.edit`` there."""
	from kamra.tex.security import uploads
	from kamra.tex.security.filetypes import MAX_IMAGE_BYTES
	from kamra.tex.services import sites

	site, property, hotel_group = text(site, 140), text(property, 140), text(hotel_group, 140)
	if site:
		hotels = sites.site_properties(sites.require_site(site))
	elif property:
		scope.require("booking_site.edit", property)
		hotels = [property]
	elif hotel_group:
		hotels = frappe.get_all("Property", filters={"tex_hotel_group": hotel_group}, pluck="name")
		if not hotels and not scope.is_platform_admin():
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		for p in hotels:
			scope.require("booking_site.edit", p)
	else:
		if not scope.is_platform_admin():
			frappe.throw(_("Name the booking site, hotel or hotel group the image is for."), frappe.PermissionError)
		hotels = []
	upload = (getattr(frappe.request, "files", None) or {}).get("file") if frappe.request else None
	if not upload:
		frappe.throw(_("No file was uploaded."))
	content = upload.stream.read(MAX_IMAGE_BYTES + 1)            # never more than the limit into memory
	out = uploads.save_public_image(upload.filename, content,
	                                attached_to=("TEX Booking Site", site) if site else None)
	audit("booking_site.image_upload", reference_doctype="TEX Booking Site" if site else "File",
	      reference_name=site or out["name"], property=hotels[0] if len(hotels) == 1 else None,
	      new={"file_url": out["file_url"], "bytes": len(content)})
	return {"file_url": out["file_url"], "file_name": out["file_name"]}


# ─── integrations ────────────────────────────────────────────────────────


@frappe.whitelist()
def outbox(property: str, status: str | None = None, limit=100):
	scope.require("connect.admin", property)
	filters: dict = {"property": property}
	if status:
		filters["status"] = status
	rows = frappe.get_all("TEX Integration Outbox", filters=filters,
	                      fields=["name", "connection", "kind", "event", "status", "attempts", "next_attempt_at", "sent_at",
	                              "last_error", "reference_doctype", "reference_name", "creation"],
	                      order_by="creation desc", limit_page_length=as_int(limit, 100, lo=1, hi=500))
	for r in rows:
		for k in ("next_attempt_at", "sent_at", "creation"):
			r[k] = str(r[k]) if r[k] else None
	return rows


@frappe.whitelist(methods=["POST"])
def retry_outbox(name: str):
	row = frappe.get_doc("TEX Integration Outbox", name)
	scope.require("connect.admin", row.property)
	if row.status not in ("Failed", "Dead"):
		frappe.throw(_("Only failed deliveries can be retried."))
	if row.kind == "Reservation" and frappe.db.sql(
			"""SELECT name FROM `tabTEX Integration Outbox`
			   WHERE kind='Reservation' AND connection=%(c)s AND reference_name=%(r)s
			     AND (creation > %(t)s OR (creation = %(t)s AND name > %(n)s)) LIMIT 1""",
			{"c": row.connection, "r": row.reference_name, "t": row.creation, "n": row.name}):
		# messages go in order (NEW-7): an old one sent now would put the stay back as it was; the latest message
		# carries the full state
		frappe.throw(_("A newer message exists for this reservation: retry the latest one, it carries the full "
		               "state."))
	# a fresh start: a dead row gets its full number of attempts again
	frappe.db.set_value("TEX Integration Outbox", name, {"status": "Pending", "attempts": 0, "claim_token": None,
	                                                    "claimed_until": None,
	                                                    "next_attempt_at": frappe.utils.now_datetime()},
	                    update_modified=False)
	audit("outbox.retry", reference_doctype="TEX Integration Outbox", reference_name=name, property=row.property)
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def test_connection(name: str):
	from kamra.tex.connect import adapters

	conn = frappe.get_doc("TEX Integration Connection", name)
	if not conn.property and not scope.is_platform_admin():
		frappe.throw(_("Only a platform administrator can test a platform-wide connection."), frappe.PermissionError)
	scope.require("connect.admin", conn.property)
	try:
		if conn.category == "Channel Manager":
			from kamra.tex.distribution import repository as dist

			result = dist.adapter_for(conn).test()
		else:
			result = adapters.get(conn).test()
		conn.db_set({"last_status": "OK", "last_error": None}, update_modified=False)
		return {"ok": True, **(result or {})}
	except Exception as e:
		from kamra.tex.security.audit import redact_text

		conn.db_set({"last_status": "Error", "last_error": redact_text(str(e))[:500]}, update_modified=False)
		return {"ok": False, "error": redact_text(str(e))[:300]}


@frappe.whitelist()
def adapters():
	"""The installed adapters per category, and whether each may run in Production."""
	scope.require("connect.admin", None)
	from kamra.tex.connect import adapters as reg
	from kamra.tex.distribution import adapters as channels

	out = [{"key": k, "category": c.category, "label": c.label, "certified": c.certified}
	       for k, c in sorted(reg.REGISTRY.items())]
	out += [{"key": k, "category": "Channel Manager", "label": c.label, "certified": c.certified}
	        for k, c in sorted(channels.REGISTRY.items())]
	return out


# ─── audit trail ─────────────────────────────────────────────────────────

# A record's trail, read by reference, needs what reading the record itself needs (Y-1): a contract's
# events carry its rates (a publish's collections, a draft's edits) and are cost (G-11: who sees cost
# or edits contracts, ``contracts._sees_cost``); a payment's carry amounts, the provider and the bank
# reference. Markups and pricing policies are read by their own API with price.view_cost alone
# (``policies.READ_CAP``), so their trail takes that path.
TRAIL_COST = perm.CONTRACT_COST_DOCTYPES     # one list with Desk / REST's cost (G-97)
TRAIL_CAPABILITY = {"TEX Payment Transaction": "payment.view", "TEX Payment Link": "payment.view",
                    "TEX Payment Allocation": "payment.view", "Reservation": "reservation.view",
                    "TEX Booking": "reservation.view", "TEX Reservation Revision": "reservation.view",
                    # a guest's profile (personal data, consent, merges), points and abandoned bookings: the CRM's
                    # (2K-4 review round 1, LO-28)
                    "Guest": "crm.view", "TEX Loyalty Ledger": "crm.view", "TEX Abandoned Booking": "crm.view"}
VERSION_TABLES = TRAIL_COST - {"TEX Contract", "TEX Contract Version"}


def _trail_property(doctype: str, name: str) -> str | None:
	"""The hotel a record belongs to: as ``scope.property_of``, else its own ``property``, a
	revision's stay, a rate table's version. None (a group or global record, one deleted since):
	its trail is the platform administrators'."""
	prop = scope.property_of(doctype, name)
	if prop or not frappe.db.exists("DocType", doctype):
		return prop
	if doctype in VERSION_TABLES:
		parent = frappe.db.get_value(doctype, name, "parent")
		return scope.property_of("TEX Contract Version", parent) if parent else None
	if doctype == "TEX Reservation Revision":
		res = frappe.db.get_value(doctype, name, "reservation")
		return scope.property_of("Reservation", res) if res else None
	meta = frappe.get_meta(doctype)
	return frappe.db.get_value(doctype, name, "property") if meta.has_field("property") and not meta.istable else None


def _trail_caps(doctype: str) -> tuple[str, ...]:
	"""What reads a record's trail, any one of these capabilities: contract cost ``price.view_cost`` or
	``contract.edit`` (G-11); payments ``payment.view``; a stay ``reservation.view``; a guest's profile, points and
	abandoned bookings ``crm.view``; a commercial policy what the policies API reads it with (markups and pricing
	policies: ``price.view_cost``); anything else ``settings.admin``."""
	from kamra.tex.api import policies

	if doctype in TRAIL_COST:
		return ("price.view_cost", "contract.edit")
	cap = TRAIL_CAPABILITY.get(doctype)
	if not cap:
		cap = policies.READ_CAP.get(doctype, "price.view") if doctype in policies.POLICY else "settings.admin"
	return (cap,)


def _require_trail(doctype: str, prop: str) -> None:
	caps = _trail_caps(doctype)
	if len(caps) > 1:
		if not any(scope.has_capability(c, prop) for c in caps):
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		return
	scope.require(caps[0], prop)


def _trail_hidden(prop: str) -> list[str]:
	"""The records whose events a hotel's trail leaves out for this viewer, by each record's own trail rule
	(``_trail_caps``): cost without ``price.view_cost`` (contracts: or ``contract.edit``), payments without
	``payment.view``, stays and bookings without ``reservation.view``, guest records without ``crm.view``, a policy
	without what its own API reads it with (LO-28). Anything else needs ``settings.admin``, which the hotel view needs itself. None for platform
	administrators."""
	from kamra.tex.api import policies

	if scope.is_platform_admin():
		return []
	held: dict[str, bool] = {}

	def has(cap: str) -> bool:
		if cap not in held:
			held[cap] = scope.has_capability(cap, prop)
		return held[cap]

	known = TRAIL_COST | set(TRAIL_CAPABILITY) | set(policies.POLICY)
	return sorted(d for d in known if not any(has(c) for c in _trail_caps(d)))


@frappe.whitelist()
def audit_log(property: str | None = None, reference_doctype: str | None = None,
              reference_name: str | None = None, action: str | None = None, actor: str | None = None,
              date_from: str | None = None, date_to: str | None = None, start=0, limit=100):
	"""The audit trail, newest first. A hotel's trail holds its own events and the events of its
	hotel group or enterprise that reached it (a group grant, ADR-053); such an event names only
	the hotels the viewer may see, the others as a count. The events of a record whose own trail would refuse
	the viewer (cost, payments, stays, policies) are left out of it (``_trail_hidden``)."""
	from frappe.query_builder import Order
	from frappe.query_builder.functions import IfNull

	E, S = frappe.qb.DocType("TEX Audit Event"), frappe.qb.DocType("TEX Audit Scope")
	q = frappe.qb.from_(E).select(E.name, E.event_time, E.action, E.actor, E.actor_roles, E.source, E.property,
	                              E.hotel_group, E.enterprise, E.reference_doctype, E.reference_name, E.reason,
	                              E.old_value, E.new_value)
	if property:
		scope.require("settings.admin", property)
		q = q.where((E.property == property)
		            | E.name.isin(frappe.qb.from_(S).select(S.event).where(S.property == property)))
		if hidden := _trail_hidden(property):
			# in the query, so a page is filled with what the viewer may read (G-97, audit Part 2I)
			q = q.where(IfNull(E.reference_doctype, "").notin(hidden))
	elif reference_doctype and reference_name:
		if not scope.is_platform_admin():
			prop = _trail_property(reference_doctype, reference_name)
			if not prop:
				frappe.throw(_("Not permitted."), frappe.PermissionError)
			_require_trail(reference_doctype, prop)
	else:
		_require_platform()
	if reference_doctype:
		q = q.where(E.reference_doctype == reference_doctype)
	if reference_name:
		q = q.where(E.reference_name == reference_name)
	if not scope.is_platform_admin():
		# values withheld from every business role, kept for platform administrators (ADR-056 review)
		from kamra.tex.security.internals import PLATFORM_ONLY_ACTIONS

		q = q.where(E.action.notin(list(PLATFORM_ONLY_ACTIONS)))
	if action:
		q = q.where(E.action.like(f"{text(action, 60)}%"))
	if actor:
		q = q.where(E.actor == actor)
	if date_from and date_to:
		q = q.where(E.event_time.between(date_from, f"{date_to} 23:59:59"))
	q = (q.orderby(E.event_time, order=Order.desc).orderby(E.name, order=Order.desc)
	     .limit(as_int(limit, 100, lo=1, hi=500)).offset(as_int(start, 0, lo=0)))
	rows = q.run(as_dict=True)
	reached: dict[str, list[str]] = {}
	wide = [r.name for r in rows if not r.property]
	for s in frappe.get_all("TEX Audit Scope", filters={"event": ("in", wide)}, fields=["event", "property"],
	                        order_by="property asc") if wide else ():
		reached.setdefault(s.event, []).append(s.property)
	visible = None if scope.is_platform_admin() else scope.permitted_properties()
	for r in rows:
		r["event_time"] = str(r["event_time"])
		for k in ("old_value", "new_value"):
			try:
				r[k] = json.loads(r[k]) if r[k] else None
			except ValueError:
				pass
		hotels = reached.get(r.name, [])
		r["hotels"] = hotels if visible is None else [h for h in hotels if h in visible]
		r["other_hotels"] = len(hotels) - len(r["hotels"])
	return rows
