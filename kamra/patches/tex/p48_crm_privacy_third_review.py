"""CRM privacy, third review of ADR-056.

1. Indexes: the funnel purge reads old events through ``tex_funnel_time_session`` (it held the whole
   funnel); a redemption reads a balance with a lock through ``tex_ledger_guest_program``; a merge reads
   and moves a profile's records with locking reads through an index on every Link to Guest
   (``tex_booking_guest_prop`` and the others in ``setup.TEX_INDEXES``). Created where missing.
2. The durable erasure marker (``Guest.tex_erased_at``) on profiles erased before it existed, from what
   only an erasure leaves (Y-12, audit Part 2A): A) its ``guest.erase`` audit event (ADR-056 second
   review; TEX code writes it, nobody edits it); or B) the legacy endpoint's ``anonymize_guest`` row in the
   Agent Action Log for that Guest, in a state of an action that ran (Executed, or Approved: the gate
   writes it just before it runs the action) *and* the profile showing what that erasure left (its
   "Guest XXXXXX" alias, no last name, e-mail or phone, its note). A log row alone never proves one:
   business roles could write the log, any status, pointing at any profile (another tenant's
   ``G-#####``); such rows, and a profile whose notes say "Profile anonymized on request." without
   either record (a merge could copy the notes into a live profile), are only counted and printed for
   an administrator to check.
3. Every erased profile finishes its erasure as ``kamra.api.anonymize_guest`` does now: no consent, no date
   of birth, gender, tags, preferences or identity documents; its cases and funnel data forgotten; its
   bookings and their payment links keep its alias instead of the booker's name, e-mail and phone; its
   change history removed, and that of its bookings, payment links and stays masked (no copy kept);
   the copies of profiles merged into it removed (``crm.service.erase_traces``). Audited per profile
   (``guest.erase``, source System, reason p48) only when something was left.

Re-runnable: each step touches only what is still to do, and audits nothing when nothing was. Never prints
an e-mail address, a phone number or a name.
"""

import re

import frappe
from frappe.utils import now_datetime

from kamra.tex.crm.service import CONSENT, erase_traces
from kamra.tex.security.audit import audit
from kamra.tex.setup import ensure_indexes, missing_indexes

ERASED_NOTE = "Profile anonymized on request."
# what an erasure clears on the profile besides its name and contact (``kamra.api.anonymize_guest``)
CLEARED = ("date_of_birth", "gender", "tex_tags", "tex_preferences", "id_file", "address_proof_file", "id_type",
           "id_number", "email", "phone", "nationality", "address_line", "city")


# the legacy endpoint's alias: "Guest " + frappe.generate_hash(length=6).upper()
ALIAS = re.compile(r"^Guest [0-9A-Z]{6}$")
# an Agent Action Log row of an action that ran (``kamra.savings``: log_action writes Executed; the
# approval gate marks a row Approved just before it runs the deferred action; Rejected never runs)
RAN = ("Executed", "Approved")


def _looks_erased(guest: str) -> bool:
	"""The profile shows what the legacy erasure left (``kamra.api.anonymize_guest``, every version): its
	alias as its name, no last name, e-mail or phone, and its note."""
	g = frappe.db.get_value("Guest", guest, ["first_name", "full_name", "last_name", "email", "phone", "guest_notes"],
	                        as_dict=True)
	if not g:
		return False
	alias = (g.first_name or "").strip()
	return bool(ALIAS.match(alias)) and (g.full_name or "").strip() in ("", alias) \
		and not any((g.get(f) or "").strip() for f in ("last_name", "email", "phone")) \
		and (g.guest_notes or "").strip() == ERASED_NOTE


def _erasures() -> tuple[dict[str, object], int]:
	"""Profile → when it was erased (the earliest record), from A) its ``guest.erase`` event or B) a
	legacy log row of an erasure that ran on a profile showing it (module docstring). → (that, the log
	rows not taken as proof)."""
	found: dict[str, object] = {}
	for name, at in frappe.db.sql("""SELECT reference_name, MIN(event_time) FROM `tabTEX Audit Event`
		WHERE action = 'guest.erase' AND reference_doctype = 'Guest' GROUP BY reference_name"""):
		found[name] = at
	unproven = 0
	if frappe.db.table_exists("Agent Action Log"):
		erased: dict[str, bool] = {}
		for name, status, at in frappe.db.sql("""SELECT reference_name, approval_status, COALESCE(executed_at, creation)
			FROM `tabAgent Action Log` WHERE action_type = 'anonymize_guest' AND reference_doctype = 'Guest'
			ORDER BY creation, name"""):
			if not name or status not in RAN:
				unproven += 1
				continue
			if name not in erased:
				erased[name] = _looks_erased(name)
			if not erased[name]:
				unproven += 1
			elif name not in found or (at and (found[name] is None or at < found[name])):
				found[name] = at
	return found, unproven


def _mark() -> tuple[int, int]:
	marked = 0
	found, unproven = _erasures()
	for name, at in sorted(found.items()):
		if frappe.db.get_value("Guest", name, "tex_erased_at", for_update=True) is None \
				and frappe.db.exists("Guest", name):
			frappe.db.set_value("Guest", name, "tex_erased_at", at or now_datetime(), update_modified=False)
			marked += 1
	return marked, unproven


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
	marked, unproven_logs = _mark()
	finished = sum(_finish(g) for g in frappe.get_all("Guest", filters={"tex_erased_at": ("is", "set")},
	                                                  pluck="name", order_by="name asc"))
	unproven = frappe.db.count("Guest", {"guest_notes": ERASED_NOTE, "tex_erased_at": ("is", "not set")})
	print(f"p48: {len(missing)} TEX index(es) created: {', '.join(missing) or '-'}; {marked} erased profile(s) "
	      f"marked from their erasure records; {finished} erased profile(s) with contact data left, now removed; "
	      f"{unproven} profile(s) with the erasure note but no record of an erasure (not marked; check them); "
	      f"{unproven_logs} Agent Action Log erasure row(s) not taken as proof (not run, or the profile shows no "
	      f"erasure)")
