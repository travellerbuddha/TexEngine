"""CRM privacy, second review of ADR-056.

1. Indexes: a consent withdrawal reads the funnel events and cases it clears through
   ``tex_funnel_hash_session``, ``tex_funnel_session_time`` and ``tex_abandoned_session`` (never a locking
   scan of the funnel inside the withdrawal); a booking finds its guest, and a profile its possible
   duplicates, through ``tex_guest_email_ent`` and ``tex_guest_phone_ent``. Created where missing.
2. The change history of abandoned cases and funnel events: their contact fields, and what leads to the
   person (a case's session, quote and recovery booking; an event's session and payload), are masked in
   rows written before (p37 masked fewer fields); no copy is kept, and the copies of contact data p37 and
   the Version hook kept (``version.withheld`` of those DocTypes) are removed. Copies of pricing internals
   and of a guest's totals stay.
3. Loyalty entries name their hotel (``property``): a stay's or booking's; the program's hotel in a hotel's
   program; for a manual adjustment of a group's program, the one hotel of the program where its author may
   edit guests, when there is exactly one. Others stay without (platform level in Desk / REST; shown to
   hotels as another hotel's entry). Only entries without a hotel are touched.
4. Profiles erased before an erasure withdrew consent (``kamra.api.anonymize_guest``): every consent is
   withdrawn, their cases and funnel data forgotten, their change history removed.
5. Anonymous abandoned cases keep no quote (it leads to the booking and its booker).

Re-runnable: each step touches only what is still to do. Never prints an e-mail address, a hash or a phone
number.
"""

import json

import frappe
from frappe.utils import now_datetime

from kamra.tex.crm.service import CONSENT, forget_contact
from kamra.tex.security import internals, scope
from kamra.tex.security.audit import audit
from kamra.tex.setup import ensure_indexes, missing_indexes

BATCH = 500
ERASED_NOTE = "Profile anonymized on request."


def _mask_contact_history() -> int:
	masked = 0
	for doctype in sorted(internals.CONTACT_DOCTYPES):
		fields = internals.INTERNAL_FIELDS[doctype]
		like = " OR ".join(["data LIKE %s"] * len(fields))
		last = ""
		while True:
			rows = frappe.db.sql(  # nosemgrep -- static condition, values bound
				f"""SELECT name, data FROM `tabVersion` WHERE ref_doctype = %s AND name > %s AND ({like})
				ORDER BY name LIMIT {BATCH}""", (doctype, last, *(f'%"{f}"%' for f in fields)), as_dict=True)
			if not rows:
				break
			for v in rows:
				try:
					data = json.loads(v.data or "{}")
				except ValueError:
					continue
				if isinstance(data, dict) and internals.mask_diff(doctype, data):
					frappe.db.set_value("Version", v.name, "data",
					                    frappe.as_json(data, indent=None, separators=(",", ":")), update_modified=False)
					masked += 1
			last = rows[-1].name
	return masked


def _drop_contact_copies() -> int:
	"""The kept copies of contact data: platform-level audit rows holding a person's e-mail or phone,
	which a withdrawal or an erasure could not reach (audit events are immutable to the application)."""
	names = frappe.get_all("TEX Audit Event", filters={"action": internals.KEPT_ACTION,
	                                                   "reference_doctype": ("in", sorted(internals.CONTACT_DOCTYPES))},
	                       pluck="name")
	for i in range(0, len(names), BATCH):
		chunk = tuple(names[i:i + BATCH])
		frappe.db.sql("DELETE FROM `tabTEX Audit Scope` WHERE event IN %(n)s", {"n": chunk})
		frappe.db.sql("DELETE FROM `tabTEX Audit Event` WHERE name IN %(n)s", {"n": chunk})
	return len(names)


def _program_hotels(program: str, cache: dict) -> tuple[str | None, set[str]]:
	if program not in cache:
		p = frappe.db.get_value("TEX Loyalty Program", program, ["property", "hotel_group"], as_dict=True) or {}
		hotels = {p.get("property")} if p.get("property") else set(frappe.get_all(
			"Property", filters={"tex_hotel_group": p.get("hotel_group")}, pluck="name")) if p.get("hotel_group") else set()
		cache[program] = (p.get("property"), hotels)
	return cache[program]


def _author_hotel(actor: str | None, hotels: set[str], cache: dict) -> str | None:
	"""The one hotel of ``hotels`` where ``actor`` may edit guests (a platform administrator: none)."""
	if not actor or not frappe.db.exists("User", actor) or scope.is_platform_admin(actor):
		return None
	if actor not in cache:
		cache[actor] = {p for p in scope.permitted_properties(actor) if scope.has_capability("crm.edit", p, actor)}
	mine = cache[actor] & hotels
	return next(iter(mine)) if len(mine) == 1 else None


def _ledger_hotels() -> int:
	rows = frappe.db.sql("""SELECT l.name, l.program, l.actor, b.property booking_hotel, r.property stay_hotel
		FROM `tabTEX Loyalty Ledger` l
		LEFT JOIN `tabTEX Booking` b ON b.name = l.booking
		LEFT JOIN `tabReservation` r ON r.name = l.reservation
		WHERE IFNULL(l.property, '') = ''""", as_dict=True)
	programs, authors, placed = {}, {}, 0
	for r in rows:
		own, hotels = _program_hotels(r.program, programs)
		hotel = r.booking_hotel or r.stay_hotel or own or _author_hotel(r.actor, hotels, authors)
		if hotel:
			frappe.db.set_value("TEX Loyalty Ledger", r.name, "property", hotel, update_modified=False)
			placed += 1
	scope.clear_cache()
	return placed


def _erased_profiles() -> int:
	consented = " OR ".join(f"IFNULL(`{f}`, 0) = 1" for f in CONSENT)
	guests = frappe.db.sql(  # nosemgrep -- static condition, values bound
		f"SELECT name FROM `tabGuest` WHERE guest_notes = %s AND ({consented})", ERASED_NOTE, pluck=True)
	for g in guests:
		was = frappe.db.get_value("Guest", g, list(CONSENT), as_dict=True)
		frappe.db.set_value("Guest", g, {**dict.fromkeys(CONSENT, 0), "tex_consent_updated_at": now_datetime(),
		                                 "tex_consent_source": "erasure"}, update_modified=False)
		audit("guest.consent", reference_doctype="Guest", reference_name=g, new={f: False for f in CONSENT if was[f]},
		      reason="erasure")
		forget_contact(g)
		frappe.db.delete("Version", {"ref_doctype": "Guest", "docname": g})
	return len(guests)


def _anonymous_quotes() -> int:
	names = frappe.get_all("TEX Abandoned Booking", filters={"consent_marketing": 0, "quote": ("is", "set")},
	                       pluck="name")
	for i in range(0, len(names), BATCH):
		frappe.db.sql("UPDATE `tabTEX Abandoned Booking` SET quote = NULL WHERE name IN %(n)s",
		              {"n": tuple(names[i:i + BATCH])})
	return len(names)


def execute():
	missing = [name for _dt, _fields, name in missing_indexes()]
	ensure_indexes()
	masked = _mask_contact_history()
	dropped = _drop_contact_copies()
	placed = _ledger_hotels()
	erased = _erased_profiles()
	quotes = _anonymous_quotes()
	print(f"p45: {len(missing)} TEX index(es) created: {', '.join(missing) or '-'}; {masked} change-history row(s) of "
	      f"cases and funnel events masked, {dropped} kept copies of contact data removed; {placed} loyalty entr(y/ies) "
	      f"given their hotel; {erased} erased profile(s) without consent now; {quotes} anonymous case(s) without "
	      f"their quote")
