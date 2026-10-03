"""TEX CRM API (R-35–R-39). Tenancy and consent rules live in kamra.tex.crm.service."""

from __future__ import annotations

import frappe

from kamra.tex.api._util import as_int, parse, text
from kamra.tex.crm import loyalty
from kamra.tex.crm import service as crm
from kamra.tex.services.txn import retry_on_deadlock


@frappe.whitelist()
def guests(q: str | None = None, segment: str | None = None, vip=None, consent: str | None = None,
           property: str | None = None, start=0, limit=50):
	return crm.list_guests(q=text(q, 80), segment=segment, vip=None if vip in (None, "") else bool(int(vip)),
	                       consent=consent, property=property, start=as_int(start, 0, lo=0),
	                       limit=as_int(limit, 50, lo=1, hi=200))


@frappe.whitelist()
def guest(name: str):
	return crm.profile(name)


@frappe.whitelist(methods=["POST"])
def update_guest(name: str, data, consent_source: str | None = None, consent_text_version: str | None = None):
	return crm.update_profile(name, parse(data, {}) or {}, consent_source=text(consent_source, 140) or "staff",
	                          consent_text_version=text(consent_text_version, 140))


@frappe.whitelist(methods=["POST"])
@retry_on_deadlock
def merge_guests(source: str, target: str):
	"""Merge the duplicate profile ``source`` into ``target`` (``crm.edit`` at every hotel either has
	records at, one enterprise; rules in ``crm.service.merge_guests``)."""
	return crm.merge_guests(text(source, 140) or "", text(target, 140) or "")


@frappe.whitelist(methods=["POST"])
def log_communication(guest: str, channel: str, direction: str = "Outbound", subject: str | None = None,
                      body: str | None = None, consent_basis: str = "Transactional", booking: str | None = None,
                      reservation: str | None = None, property: str | None = None):
	return {"name": crm.log_communication(guest, channel=channel, direction=direction, subject=text(subject, 140),
	                                      body=text(body, 5000), consent_basis=consent_basis, booking=booking,
	                                      reservation=reservation, property=property)}


@frappe.whitelist()
def segments():
	"""Presets and this tenant's segments, the rule vocabulary, and the currencies and
	enterprises a new segment can use (G-23)."""
	from kamra.tex.crm import segments as seg
	from kamra.tex.security import scope

	scope.require("crm.view", None)
	props = {p for p in scope.permitted_properties() if scope.has_capability("crm.view", p)}
	rows = crm.visible_segments(props)
	for r in rows:
		r["last_evaluated"] = str(r["last_evaluated"]) if r["last_evaluated"] else None
		if r.get("system_key"):
			r["member_count"] = None                       # a preset's count depends on who looks
	ents = sorted(crm._enterprises({p for p in props if scope.has_capability("crm.edit", p)}))
	currencies = sorted({c for c in frappe.get_all("Property", filters={"name": ("in", list(props) or [""])},
	                                               pluck="currency") if c} | {"EUR"})
	return {"segments": rows, "fields": seg.FIELDS, "ops": {k: sorted(v) for k, v in seg.OPS.items()},
	        "currencies": currencies,
	        "enterprises": [{"name": e, "label": frappe.db.get_value("TEX Enterprise", e, "enterprise_name") or e}
	                        for e in ents]}


@frappe.whitelist(methods=["POST"])
def save_segment(data):
	return {"name": crm.save_segment(parse(data, {}) or {})}


@frappe.whitelist(methods=["POST"])
def delete_segment(segment: str):
	crm.delete_segment(segment)
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def evaluate_segment(segment: str, property: str | None = None):
	return crm.evaluate_segment(segment, property=property)


@frappe.whitelist(methods=["POST"])
def export_segment(segment: str, channel: str, property: str | None = None):
	return crm.export_segment(segment, channel=channel, property=property)


@frappe.whitelist()
def abandoned(property: str, status: str | None = None, days=30):
	return crm.abandoned(property, status=status, days=as_int(days, 30, lo=1, hi=365))


@frappe.whitelist(methods=["POST"])
def set_abandoned_status(name: str, status: str, note: str | None = None):
	crm.set_abandoned_status(name, status, text(note, 300))
	return {"ok": True}


@frappe.whitelist()
def loyalty_summary(guest: str):
	via = crm.require_guest(guest)
	return loyalty.summary(guest, loyalty.visible_programs(via), hotels=via)     # this tenant's programs only


def _guests_program(guest: str, program: str) -> None:
	"""Staff who may edit the guest act on a program of the hotels they edit the guest through: never another
	enterprise's, even where they may edit guests there too (C-04 review round 1)."""
	via = crm.require_guest(guest, "crm.edit")
	if program not in loyalty.visible_programs(via):
		frappe.throw(frappe._("Program not found."), frappe.DoesNotExistError)


@frappe.whitelist(methods=["POST"])
@retry_on_deadlock
def loyalty_adjust(guest: str, program: str, points, reason: str, property: str | None = None):
	_guests_program(guest, program)
	return {"name": loyalty.adjust(guest, program, as_int(points, 0), text(reason, 500) or "",
	                               property=text(property, 140) or None)}


@frappe.whitelist(methods=["POST"])
@retry_on_deadlock
def loyalty_join(guest: str, program: str, property: str | None = None):
	_guests_program(guest, program)
	return loyalty.join(guest, program, property=text(property, 140) or None)


@frappe.whitelist(methods=["POST"])
@retry_on_deadlock
def loyalty_leave(guest: str, program: str, reason: str, property: str | None = None):
	_guests_program(guest, program)
	return loyalty.leave(guest, program, reason=text(reason, 500) or "", property=text(property, 140) or None)


@frappe.whitelist(methods=["POST"])
@retry_on_deadlock
def loyalty_redeem(guest: str, booking: str, points, idempotency_key: str):
	crm.require_guest(guest)
	return loyalty.redeem(guest, booking, as_int(points, 0), idempotency_key=text(idempotency_key, 140) or "")
