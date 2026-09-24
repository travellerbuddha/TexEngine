"""CRM privacy, third review of ADR-056.

1. Indexes: the funnel purge reads old events through ``tex_funnel_time_session`` (it held the whole
   funnel); a redemption reads a balance with a lock through ``tex_ledger_guest_program``; a merge reads
   and moves a profile's records with locking reads through an index on every Link to Guest
   (``tex_booking_guest_prop`` and the others in ``setup.TEX_INDEXES``). Created where missing.
2. The durable erasure marker (``Guest.tex_erased_at``) on profiles erased before it existed, from the
   records an erasure leaves: its ``guest.erase`` audit event (ADR-056 second review) or its
   ``anonymize_guest`` entry in the Agent Action Log (every erasure the legacy endpoint made). A profile
   whose notes say "Profile anonymized on request." without either record is not marked (a merge could
   copy the notes into a live profile): their number is printed for an administrator to check.
3. Every erased profile finishes its erasure as ``kamra.api.anonymize_guest`` does now: no consent, no date
   of birth, gender, tags, preferences or identity documents; its cases and funnel data forgotten; its
   bookings and their payment links keep its alias instead of the booker's name, e-mail and phone; its
   change history removed, and that of its bookings, payment links and stays masked (no copy kept);
   the copies of profiles merged into it removed (``crm.service.erase_traces``). Audited per profile
   (``guest.erase``, source System, reason p48) only when something was left.

Re-runnable: each step touches only what is still to do, and audits nothing when nothing was. Never prints
an e-mail address, a phone number or a name.
"""

import frappe
from frappe.utils import now_datetime

from kamra.tex.crm.service import CONSENT, erase_traces
from kamra.tex.security.audit import audit
from kamra.tex.setup import ensure_indexes, missing_indexes

ERASED_NOTE = "Profile anonymized on request."
# what an erasure clears on the profile besides its name and contact (``kamra.api.anonymize_guest``)
CLEARED = ("date_of_birth", "gender", "tex_tags", "tex_preferences", "id_file", "address_proof_file", "id_type",
           "id_number", "email", "phone", "nationality", "address_line", "city")


def _erasures() -> dict[str, object]:
	"""Profile → when it was erased, from the records an erasure leaves (the earliest)."""
	found: dict[str, object] = {}
	for name, at in frappe.db.sql("""SELECT reference_name, MIN(event_time) FROM `tabTEX Audit Event`
		WHERE action = 'guest.erase' AND reference_doctype = 'Guest' GROUP BY reference_name"""):
		found[name] = at
	if frappe.db.table_exists("Agent Action Log"):
		for name, at in frappe.db.sql("""SELECT reference_name, MIN(COALESCE(executed_at, creation))
			FROM `tabAgent Action Log` WHERE action_type = 'anonymize_guest' AND reference_doctype = 'Guest'
			GROUP BY reference_name"""):
			if name and (name not in found or (at and at < found[name])):
				found[name] = at
	return found


def _mark() -> int:
	marked = 0
	for name, at in sorted(_erasures().items()):
		if frappe.db.get_value("Guest", name, "tex_erased_at", for_update=True) is None \
				and frappe.db.exists("Guest", name):
			frappe.db.set_value("Guest", name, "tex_erased_at", at or now_datetime(), update_modified=False)
			marked += 1
	return marked


def _finish(guest: str) -> bool:
	"""Finish one erased profile's erasure. → whether anything was left."""
	g = frappe.db.get_value("Guest", guest, ["full_name", "first_name", *CONSENT, *CLEARED], as_dict=True)
	withdrawn = [f for f in CONSENT if g.get(f)]
	cleared = [f for f in CLEARED if g.get(f)]
	if withdrawn or cleared:
		frappe.db.set_value("Guest", guest, {**dict.fromkeys(withdrawn, 0), **dict.fromkeys(cleared, None),
		                                     **({"tex_consent_updated_at": now_datetime(), "tex_consent_source": "erasure"}
		                                        if withdrawn else {})}, update_modified=False)
	if withdrawn:
		audit("guest.consent", reference_doctype="Guest", reference_name=guest, new=dict.fromkeys(withdrawn, False),
		      reason="erasure")
	out = erase_traces(guest, g.full_name or g.first_name or "Guest", audit_event=False)
	if withdrawn or cleared or out["changed"]:
		audit("guest.erase", reference_doctype="Guest", reference_name=guest, source="System",
		      reason="p48: an erasure made before the third review of ADR-056, finished",
		      new={**out, "profile_fields_cleared": len(cleared) + len(withdrawn)})
		return True
	return False


def execute():
	missing = [name for _dt, _fields, name in missing_indexes()]
	ensure_indexes()
	marked = _mark()
	finished = sum(_finish(g) for g in frappe.get_all("Guest", filters={"tex_erased_at": ("is", "set")},
	                                                  pluck="name", order_by="name asc"))
	unproven = frappe.db.count("Guest", {"guest_notes": ERASED_NOTE, "tex_erased_at": ("is", "not set")})
	print(f"p48: {len(missing)} TEX index(es) created: {', '.join(missing) or '-'}; {marked} erased profile(s) "
	      f"marked from their erasure records; {finished} erased profile(s) with contact data left, now removed; "
	      f"{unproven} profile(s) with the erasure note but no record of an erasure (not marked; check them)")
