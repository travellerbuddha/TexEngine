"""Rates & Contracts API (R-04, R-05, R-10, R-11, Phase 4)."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime

from kamra.tex.api._util import as_int, doc_dict, parse, text
from kamra.tex.commercial import context as ctxmod
from kamra.tex.commercial import contracts as svc
from kamra.tex.pricing import engine
from kamra.tex.pricing.model import ChildSpec, PricingError, StayRequest, Unsellable
from kamra.tex.security import scope
from kamra.tex.security.audit import audit

CONTRACT_FIELDS = ("contract_code", "contract_name", "market", "status", "pricing_basis", "contract_currency",
                   "sell_currency", "priority", "is_bar", "sale_from", "sale_to", "stay_from", "stay_to", "notes")
VERSION_SETTINGS = ("child_ordering", "age_basis", "children_over_max_as_adults", "infants_count_as_occupants",
                    "prices_include_tax", "stacking", "room_basis_extra_unit", "room_basis_children_fill_included",
                    "change_note")
VERSION_TABLES = ("rooms", "periods", "period_rates", "age_bands", "occupancy_rules", "boards", "rate_plans",
                  "offers")


@frappe.whitelist()
def list_contracts(property: str | None = None, status: str | None = None, market: str | None = None):
	props = [property] if property else sorted(scope.permitted_properties())
	for p in props:
		scope.require("price.view", p)
	filters = {"property": ("in", props or ["__none__"])}
	if status:
		filters["status"] = status
	if market:
		filters["market"] = market
	rows = frappe.get_all("TEX Contract", filters=filters,
	                      fields=["name", "property", "contract_code", "contract_name", "market", "status",
	                              "pricing_basis", "contract_currency", "sale_from", "sale_to", "stay_from", "stay_to",
	                              "active_version", "latest_version_no", "priority", "modified"],
	                      order_by="property asc, status asc, contract_code asc")
	drafts = {r.contract for r in frappe.get_all("TEX Contract Version",
	                                             filters={"status": "Draft", "contract": ("in", [r.name for r in rows]
	                                                                                      or ["__none__"])},
	                                             fields=["contract"])}
	for r in rows:
		r["has_draft"] = r.name in drafts
	return rows


@frappe.whitelist()
def get_contract(name: str):
	c = frappe.get_doc("TEX Contract", name)
	scope.require("price.view", c.property)
	versions = frappe.get_all("TEX Contract Version", filters={"contract": name},
	                          fields=["name", "version_no", "status", "effective_from", "active_to", "published_at",
	                                  "published_by", "change_note", "payload_hash", "based_on"],
	                          order_by="version_no desc")
	return {"contract": doc_dict(c), "versions": versions,
	        "can_edit": scope.has_capability("contract.edit", c.property),
	        "can_publish": scope.has_capability("contract.publish", c.property)}


@frappe.whitelist(methods=["POST"])
def save_contract(data):
	data = parse(data, {})
	prop = data.get("property")
	if data.get("name"):
		doc = frappe.get_doc("TEX Contract", data["name"])
		prop = doc.property
	else:
		doc = frappe.new_doc("TEX Contract")
		doc.property = prop
	scope.require("contract.edit", prop)
	before = {f: doc.get(f) for f in CONTRACT_FIELDS}
	for f in CONTRACT_FIELDS:
		if f in data:
			doc.set(f, data[f])
	if "channels" in data:
		doc.set("channels", [{"sales_channel": c} for c in (data.get("channels") or [])])
	doc.save(ignore_permissions=True)
	audit("contract.save", reference_doctype="TEX Contract", reference_name=doc.name, property=prop,
	      old=before if not doc.is_new() else None, new={f: doc.get(f) for f in CONTRACT_FIELDS})
	if not frappe.db.exists("TEX Contract Version", {"contract": doc.name}):
		svc.new_draft(doc.name)
	return get_contract(doc.name)


@frappe.whitelist(methods=["POST"])
def duplicate_contract(name: str, contract_code: str, contract_name: str | None = None, market: str | None = None):
	"""Copy a contract and its latest version into a new draft contract (R-55)."""
	src = frappe.get_doc("TEX Contract", name)
	scope.require("contract.edit", src.property)
	new = frappe.copy_doc(src)
	new.contract_code = text(contract_code, 40)
	new.contract_name = text(contract_name, 140) or f"{src.contract_name} (copy)"
	new.market = market or src.market
	new.status = "Draft"
	new.active_version = None
	new.latest_version_no = 0
	new.insert(ignore_permissions=True)
	latest = frappe.db.get_value("TEX Contract Version", {"contract": name}, "name", order_by="version_no desc")
	if latest:
		v = frappe.copy_doc(frappe.get_doc("TEX Contract Version", latest))
		for f in ("status", "published_at", "published_by", "active_to", "effective_from", "payload", "payload_hash",
		          "validation_report", "change_note", "based_on"):
			v.set(f, None)
		v.contract = new.name
		v.status = "Draft"
		v.insert(ignore_permissions=True)
	audit("contract.duplicate", reference_doctype="TEX Contract", reference_name=new.name, property=src.property,
	      new={"from": name})
	return get_contract(new.name)


@frappe.whitelist()
def get_version(name: str):
	v = frappe.get_doc("TEX Contract Version", name)
	prop = scope.property_of("TEX Contract Version", name)
	scope.require("price.view", prop)
	out = doc_dict(v, exclude=("payload",))
	out["validation_report"] = json.loads(v.validation_report) if v.validation_report else None
	out["editable"] = v.status == "Draft" and scope.has_capability("contract.edit", prop)
	c = frappe.get_doc("TEX Contract", v.contract)
	out["contract_doc"] = {f: c.get(f) for f in ("name", "property", "contract_code", "contract_name", "market",
	                                             "pricing_basis", "contract_currency", "status")}
	out["room_types"] = frappe.get_all("Room Type", filters={"property": c.property, "disabled": 0},
	                                   fields=["name", "room_type_name", "adults_capacity", "children_capacity",
	                                           "max_total_occupants", "base_occupancy"], order_by="room_type_name")
	out["rate_plan_options"] = frappe.get_all("Rate Plan", filters={"property": c.property, "disabled": 0},
	                                          fields=["name", "rate_plan_name", "code", "tex_refundable"])
	return out


@frappe.whitelist(methods=["POST"])
def save_version(name: str, data):
	"""Replace the draft's settings and child tables in one call (autosave-friendly)."""
	data = parse(data, {})
	v = frappe.get_doc("TEX Contract Version", name)
	prop = scope.property_of("TEX Contract Version", name)
	scope.require("contract.edit", prop)
	if v.status != "Draft":
		frappe.throw(_("Only draft versions can be edited — create a new draft."))
	for f in VERSION_SETTINGS:
		if f in data:
			v.set(f, data[f])
	for t in VERSION_TABLES:
		if t in data:
			clean = []
			for row in data[t] or []:
				row = {k: val for k, val in row.items() if not k.startswith("_") and k not in
				       ("name", "parent", "parenttype", "parentfield", "doctype", "idx", "creation", "modified",
				        "owner", "modified_by", "docstatus")}
				clean.append(row)
			v.set(t, clean)
	v.save(ignore_permissions=True)
	return get_version(name)


@frappe.whitelist()
def validate_version(name: str):
	return svc.validate_version(name)


@frappe.whitelist(methods=["POST"])
def publish_version(name: str, effective_from: str | None = None, change_note: str | None = None):
	return svc.publish(name, effective_from=effective_from or None, change_note=text(change_note, 500))


@frappe.whitelist(methods=["POST"])
def new_draft(contract: str, based_on: str | None = None):
	return {"version": svc.new_draft(contract, based_on)}


@frappe.whitelist(methods=["POST"])
def withdraw_version(name: str, reason: str):
	svc.withdraw(name, text(reason, 500))
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def preview_price(version: str, room_type: str, board: str, check_in: str, check_out: str, adults: int = 2,
                  children=None, rate_plan: str | None = None, market: str | None = None, channel: str = "DIRECT_WEB",
                  currency: str | None = None, sale_at: str | None = None, promo_codes=None):
	"""Price a stay on any version — including an unpublished draft — with the full
	explanation (contract editor 'test price' panel; also answers 'which rule won')."""
	v = frappe.get_doc("TEX Contract Version", version)
	prop = scope.property_of("TEX Contract Version", version)
	scope.require("price.view_cost", prop)
	at = frappe.utils.get_datetime(sale_at) if sale_at else now_datetime()
	try:
		terms = svc.load_terms(version) if v.status != "Draft" else svc.build_terms(v, at=at)
	except frappe.ValidationError as e:
		return {"sellable": False, "reasons": [{"code": "BUILD", "message": str(e)}]}
	kids = tuple(ChildSpec(age=int(a)) for a in (parse(children, []) or []))
	req = StayRequest(property=prop, room_type=room_type, board=board, rate_plan=rate_plan or None,
	                  check_in=getdate(check_in), check_out=getdate(check_out), adults=as_int(adults, 2, lo=1, hi=12),
	                  children=kids, sale_at=at, market=(market or terms.market).upper(), channel=channel,
	                  sell_currency=(currency or terms.currency).upper(),
	                  promo_codes=tuple(parse(promo_codes, []) or ()))
	try:
		ctx = ctxmod.build_context(terms, req)
		q = engine.price_stay(ctx, req)
	except (Unsellable, PricingError) as e:
		return {"sellable": False, "reasons": [{"code": getattr(e, "code", "PRICING_ERROR"), "message": str(e)}]}
	return q.to_dict(internal=True)


@frappe.whitelist()
def price_matrix(version: str, adults: int = 2):
	"""Nightly unit (base person / room price) per room × period for the editor grid."""
	v = frappe.get_doc("TEX Contract Version", version)
	prop = scope.property_of("TEX Contract Version", version)
	scope.require("price.view", prop)
	terms = svc.load_terms(version) if v.status != "Draft" else svc.build_terms(v)
	from kamra.tex.pricing import rooms as room_math

	out = []
	for rt in sorted(terms.rooms):
		row = {"room_type": rt, "name": terms.rooms[rt].name, "cells": {}}
		for p in terms.periods:
			try:
				row["cells"][p.code] = str(room_math.room_unit(terms, rt, p))
			except Unsellable as u:
				row["cells"][p.code] = None
				row.setdefault("errors", {})[p.code] = u.message
		out.append(row)
	return {"periods": [{"code": p.code, "name": p.name, "start": str(p.start), "end": str(p.end)}
	                    for p in terms.periods], "rooms": out, "basis": terms.basis.value, "currency": terms.currency}


@frappe.whitelist(methods=["POST"])
def legacy_draft(property: str, market: str = "GLOBAL", contract_code: str = "LEGACY-BAR"):
	"""MIGRATION T8 (opt-in): draft a contract from the hotel's legacy Kamra prices."""
	from kamra.tex.commercial import legacy

	return legacy.draft_from_legacy(property, market=market, contract_code=(contract_code or "LEGACY-BAR")[:40])

