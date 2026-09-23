"""CRUD for commercial policies with capability checks and revision lifecycle.

Only the DocTypes listed in POLICY are reachable here. Records with a property are
checked against that hotel; global records (blank property) need a platform admin.
"""

from __future__ import annotations

import frappe
from frappe import _

from kamra.tex.api._util import doc_dict, parse, text
from kamra.tex.commercial import revisions
from kamra.tex.security import scope
from kamra.tex.security.audit import audit

POLICY = {
	"TEX Markup Rule": "markup.edit",
	"TEX Promotion": "promotion.edit",
	"TEX FX Policy": "fx.edit",
	"TEX Pricing Policy": "contract.edit",
	"TEX Tax Policy": "tax.edit",
	"TEX Cancellation Policy": "contract.edit",
	"TEX Payment Policy": "contract.edit",
	"TEX Extra": "contract.edit",
	"TEX Allotment": "inventory.edit",
	"TEX Payment Method Rule": "payment.refund",
	"TEX Payment Provider Account": "settings.admin",
	"TEX Booking Site": "booking_site.edit",
	"TEX Integration Connection": "connect.admin",
}
READ_CAP = {"TEX Payment Provider Account": "payment.view", "TEX Payment Method Rule": "payment.view",
            "TEX Integration Connection": "connect.admin",
            # markups and contract formulas are cost (G-11)
            "TEX Markup Rule": "price.view_cost", "TEX Pricing Policy": "price.view_cost"}
PROTECTED = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "tex_status", "active_from",
             "active_to", "revision_no", "revision_of", "times_redeemed", "doctype"}


def _check(doctype: str, prop: str | list[str] | None, write: bool) -> None:
	"""``prop`` may be a list (group-level records): the capability is then required
	at every hotel the record reaches."""
	if doctype not in POLICY:
		frappe.throw(_("Not allowed."), frappe.PermissionError)
	cap = POLICY[doctype] if write else READ_CAP.get(doctype, "price.view")
	if isinstance(prop, list):
		if not prop and not scope.is_platform_admin():
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		for p in prop:
			scope.require(cap, p)
	elif prop:
		scope.require(cap, prop)
	elif not scope.is_platform_admin():
		if write:
			frappe.throw(_("Only platform administrators manage global policies."), frappe.PermissionError)
		if not scope.has_capability(cap, None):
			frappe.throw(_("Not permitted."), frappe.PermissionError)


def _prop_of(doctype: str, doc) -> str | list[str] | None:
	if doctype == "TEX Booking Site" and not doc.get("property") and doc.get("hotel_group"):
		return sorted(frappe.get_all("Property", filters={"tex_hotel_group": doc.hotel_group}, pluck="name"))
	return doc.get("property") if doc.meta.has_field("property") else None


def _audit_prop(doctype: str, doc) -> str | None:
	p = _prop_of(doctype, doc)
	return p if isinstance(p, str) else None


@frappe.whitelist()
def list_records(doctype: str, property: str | None = None, include_archived: int = 0):
	_check(doctype, property, write=False)
	meta = frappe.get_meta(doctype)
	filters: dict = {}
	if meta.has_field("property"):
		allowed = sorted(scope.permitted_properties())
		if property:
			filters["property"] = ("in", [property, ""]) if meta.get_field("property").reqd == 0 else property
		else:
			filters["property"] = ("in", [*allowed, ""])
	if meta.has_field("tex_status") and not int(include_archived):
		filters["tex_status"] = ("!=", "Archived")
	fields = ["name", "modified"] + [df.fieldname for df in meta.fields
	                                 if df.in_list_view or df.fieldname in ("property", "tex_status", "revision_no",
	                                                                        "revision_of", "active_from", "active_to")]
	if meta.has_field("hotel_group"):
		fields.append("hotel_group")
	rows = frappe.get_all(doctype, filters=filters, fields=list(dict.fromkeys(fields)), order_by="modified desc",
	                      limit=500)
	allowed = scope.permitted_properties()
	groups = {g for g in frappe.get_all("Property", filters={"name": ("in", list(allowed) or [""])},
	                                    pluck="tex_hotel_group") if g}

	def visible(r) -> bool:
		if r.get("property"):
			return r.property in allowed
		if r.get("hotel_group"):          # group-level record: only for users of that group
			return r.hotel_group in groups or scope.is_platform_admin()
		return True

	return [r for r in rows if visible(r)]


@frappe.whitelist()
def get_record(doctype: str, name: str):
	if doctype not in POLICY:
		frappe.throw(_("Not allowed."), frappe.PermissionError)
	doc = frappe.get_doc(doctype, name)
	_check(doctype, _prop_of(doctype, doc), write=False)
	return doc_dict(doc)


@frappe.whitelist(methods=["POST"])
def save_record(doctype: str, data):
	data = parse(data, {})
	if data.get("name"):
		doc = frappe.get_doc(doctype, data["name"])
		_check(doctype, _prop_of(doctype, doc), write=True)
		before = doc_dict(doc)
	else:
		doc = frappe.new_doc(doctype)
		before = None
	for k, v in data.items():
		if k in PROTECTED or not doc.meta.has_field(k):
			continue
		df = doc.meta.get_field(k)
		if df.fieldtype in ("Table", "Table MultiSelect"):
			doc.set(k, [{kk: vv for kk, vv in (row or {}).items() if kk not in ("name", "parent", "parenttype",
			                                                                     "parentfield", "doctype", "idx")}
			            for row in (v or [])])
		elif df.fieldtype == "Password":
			if v and v != "*****":
				doc.set(k, v)
		else:
			doc.set(k, v)
	_check(doctype, _prop_of(doctype, doc), write=True)
	# authority is the TEX capability checked above (before and after the edit)
	doc.save(ignore_permissions=True) if doc.name and not doc.is_new() else doc.insert(ignore_permissions=True)
	audit(f"{doctype.lower().replace(' ', '_')}.save", reference_doctype=doctype, reference_name=doc.name,
	      property=_audit_prop(doctype, doc), old=before, new=doc_dict(doc))
	return doc_dict(doc)


@frappe.whitelist(methods=["POST"])
def delete_record(doctype: str, name: str):
	doc = frappe.get_doc(doctype, name)
	_check(doctype, _prop_of(doctype, doc), write=True)
	if doc.meta.has_field("tex_status") and doc.tex_status != "Draft":
		frappe.throw(_("Live revisions are archived, not deleted."))
	# audited while the record still exists (same transaction); then the record goes and its audit
	# trail stays (hooks.ignore_links_on_delete); any other link still blocks the delete
	audit(f"{doctype.lower().replace(' ', '_')}.delete", reference_doctype=doctype, reference_name=name,
	      property=_audit_prop(doctype, doc), old=doc_dict(doc))
	frappe.delete_doc(doctype, name, ignore_permissions=True)
	return {"ok": True}


def _rev_doc(doctype: str, name: str):
	if doctype not in revisions.REVISIONED:
		frappe.throw(_("{0} has no revisions.").format(doctype))
	doc = frappe.get_doc(doctype, name)
	_check(doctype, _prop_of(doctype, doc), write=True)
	return doc


@frappe.whitelist(methods=["POST"])
def activate(doctype: str, name: str, at: str | None = None):
	doc = _rev_doc(doctype, name)
	revisions.activate(doctype, name, at)   # never back-dated from here (G-20)
	audit(f"{doctype.lower().replace(' ', '_')}.activate", reference_doctype=doctype, reference_name=name,
	      property=_audit_prop(doctype, doc), new={"active_from": str(frappe.db.get_value(doctype, name, "active_from"))})
	return get_record(doctype, name)


@frappe.whitelist(methods=["POST"])
def revise(doctype: str, name: str):
	_rev_doc(doctype, name)
	return get_record(doctype, revisions.revise(doctype, name))


@frappe.whitelist(methods=["POST"])
def archive(doctype: str, name: str, reason: str | None = None):
	"""Take a live revision out of sale; the reason is kept in the audit trail."""
	reason = text(reason, 500)
	if not reason or len(reason) < 3:
		frappe.throw(_("A reason is required."))
	doc = _rev_doc(doctype, name)
	revisions.archive(doctype, name)
	audit(f"{doctype.lower().replace(' ', '_')}.archive", reference_doctype=doctype, reference_name=name,
	      property=_audit_prop(doctype, doc), reason=reason)
	return {"ok": True}


@frappe.whitelist()
def history(doctype: str, name: str):
	"""All revisions of a record (the chain rooted at its first revision)."""
	if doctype not in revisions.REVISIONED or doctype not in POLICY:
		frappe.throw(_("{0} has no revisions.").format(doctype))
	doc = frappe.get_doc(doctype, name)
	_check(doctype, _prop_of(doctype, doc), write=False)
	root = doc.revision_of or doc.name
	return frappe.get_all(doctype, or_filters={"name": root, "revision_of": root},
	                      fields=["name", "revision_no", "tex_status", "active_from", "active_to", "modified_by",
	                              "modified"], order_by="revision_no asc")


@frappe.whitelist()
def pricing_policy_bands(property: str | None = None, market: str | None = None, exclude: str | None = None):
	"""Age bands a pricing policy of this scope (hotel, market; blank = any) can name: those of
	every live pricing policy it cascades with into some contract (rules cascade by band code,
	ADR-042), so a hotel policy without bands can name the market policy's. ``exclude``: the
	policy being edited (its revision chain is not its own source)."""
	doctype = "TEX Pricing Policy"
	property, market = (property or None), (market or None)
	_check(doctype, property, write=False)
	allowed = scope.permitted_properties()
	root = (frappe.db.get_value(doctype, exclude, "revision_of") or exclude) if exclude else None
	out: dict[str, dict] = {}
	for r in revisions.as_of(doctype, frappe.utils.now_datetime(),
	                         fields=("name", "policy_name", "property", "market", "revision_of")):
		if r.property and (r.property not in allowed or (property and r.property != property)):
			continue   # another hotel's policy never meets this one in a contract
		if r.market and market and r.market != market:
			continue
		if root and (r.revision_of or r.name) == root:
			continue
		for b in frappe.get_all("TEX Child Age Band", filters={"parenttype": doctype, "parent": r.name},
		                        fields=["band_code", "label", "is_infant"], order_by="idx asc"):
			code = (b.band_code or "").strip().upper()
			if not code:
				continue
			entry = out.setdefault(code, {"code": code, "label": b.label or code, "is_infant": bool(b.is_infant),
			                              "policies": []})
			entry["policies"].append(r.policy_name or r.name)
	return list(out.values())


# ─── FX ──────────────────────────────────────────────────────────────────


@frappe.whitelist()
def fx_rates(provider: str = "TCMB", days: int = 14, base: str | None = None):
	scope.require("price.view", None) if not scope.is_platform_admin() else None
	from frappe.utils import add_days, nowdate

	filters = {"provider": provider, "rate_date": (">=", add_days(nowdate(), -int(days)))}
	if base:
		filters["base_currency"] = base
	return frappe.get_all("TEX FX Rate", filters=filters,
	                      fields=["name", "provider", "base_currency", "quote_currency", "rate_type", "rate",
	                              "rate_date", "fetched_at"], order_by="rate_date desc, base_currency asc", limit=500)


@frappe.whitelist(methods=["POST"])
def fetch_fx(provider: str = "TCMB"):
	# FX rates are shared by every hotel: platform administrators only
	if not scope.is_platform_admin():
		frappe.throw(_("Only platform administrators manage shared FX rates."), frappe.PermissionError)
	from kamra.tex.connect import fx_providers

	return fx_providers.fetch(provider)


@frappe.whitelist(methods=["POST"])
def add_manual_rate(base_currency: str, quote_currency: str, rate: str, rate_date: str):
	if not scope.is_platform_admin():
		frappe.throw(_("Only platform administrators manage shared FX rates."), frappe.PermissionError)
	from kamra.tex.money import D_or_none

	value = D_or_none(str(rate))
	if value is None or value <= 0:
		frappe.throw(_("The rate must be a positive number."))
	doc = frappe.get_doc({"doctype": "TEX FX Rate", "provider": "MANUAL", "base_currency": text(base_currency, 3),
	                      "quote_currency": text(quote_currency, 3), "rate": value, "rate_date": rate_date,
	                      "fetched_at": frappe.utils.now_datetime(), "source_ref": frappe.session.user})
	doc.insert(ignore_permissions=True)
	audit("fx.manual_rate", reference_doctype="TEX FX Rate", reference_name=doc.name,
	      new={"pair": f"{doc.base_currency}{doc.quote_currency}", "rate": str(rate), "date": rate_date})
	return {"name": doc.name}
