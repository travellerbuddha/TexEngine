"""CRM privacy review follow-up (ADR-056 review).

1. Abandoned cases: a case keeps its guest, e-mail and phone only while the profile's own marketing
   e-mail consent holds. A withdrawal now makes the guest's cases and funnel data anonymous at
   once (``crm.service.guest_on_update``); cases whose consent was withdrawn before this change
   lose their contact data here (profile, e-mail, phone; consent 0), with the e-mail hashes of their
   sessions, and every funnel e-mail hash of a profile without e-mail consent is removed.
2. Customised role permissions: a DocType with Custom DocPerm rows (Kamra's permission scripts write
   them) uses those rows instead of its JSON's, so System Manager lost the permlevel-1 row that lets
   platform administrators read the withheld fields (``kamra.tex.security.internals``). The row is
   added where missing, once, at the upgrade that brings this patch (a forced re-run never undoes
   what an administrator changed since).
3. A role other than System Manager that holds permlevel 1 of such a DocType reads fields TEX
   withholds from every business role: each is printed on every run and audited once
   (``permission.withheld_fields_exposed``, platform level) for an administrator to remove.

Re-runnable. Never prints an e-mail address, a hash or a phone number.
"""

import frappe

from kamra.tex.crm.service import email_hash, forget_contact
from kamra.tex.security import internals
from kamra.tex.setup import ran_before

PATCH = "kamra.patches.tex.p40_crm_privacy_review"
BATCH = 1000


def _stale_cases() -> int:
	"""Cases still holding contact data (or a consent) whose profile no longer consents."""
	rows = frappe.db.sql("""SELECT a.name, a.guest, a.session_id, g.email
		FROM `tabTEX Abandoned Booking` a LEFT JOIN `tabGuest` g ON g.name = a.guest
		WHERE (IFNULL(a.guest, '') != '' OR IFNULL(a.email, '') != '' OR IFNULL(a.phone, '') != ''
		       OR IFNULL(a.consent_marketing, 0) = 1)
		  AND IFNULL(g.tex_consent_email, 0) = 0""", as_dict=True)
	for guest in {r.guest for r in rows if r.guest}:
		forget_contact(guest, emails=[r.email for r in rows if r.guest == guest])
	loose = [r.name for r in rows if not r.guest]
	if loose:
		sessions = tuple(r.session_id for r in rows if not r.guest and r.session_id) or ("",)
		frappe.db.sql("""UPDATE `tabTEX Abandoned Booking` SET email = NULL, phone = NULL, consent_marketing = 0
			WHERE name IN %(n)s""", {"n": tuple(loose)})
		frappe.db.sql("""UPDATE `tabTEX Funnel Event` SET email_hash = NULL
			WHERE IFNULL(email_hash, '') != '' AND session_id IN %(s)s""", {"s": sessions})
	return len(rows)


def _hashes_without_consent() -> int:
	"""Funnel e-mail hashes of profiles that do not (or no longer) consent to marketing e-mail."""
	stored = set(frappe.db.sql_list("""SELECT DISTINCT email_hash FROM `tabTEX Funnel Event`
		WHERE IFNULL(email_hash, '') != ''"""))
	if not stored:
		return 0
	stale, offset = set(), 0
	while True:
		emails = frappe.get_all("Guest", filters={"tex_consent_email": 0, "email": ("is", "set")}, pluck="email",
		                        order_by="name asc", offset=offset, limit=BATCH)
		stale |= {h for h in (email_hash(e) for e in emails) if h in stored}
		if len(emails) < BATCH:
			break
		offset += BATCH
	if stale:
		frappe.db.sql("UPDATE `tabTEX Funnel Event` SET email_hash = NULL WHERE email_hash IN %(h)s",
		              {"h": tuple(stale)})
	return len(stale)


def _report_exposed() -> list[dict]:
	from kamra.tex.security.audit import audit

	exposed = internals.exposed_roles()
	for r in exposed:
		print(f"p40: WARNING: role {r['role']} reads the withheld fields of {r['doctype']} (permlevel {r['permlevel']}, "
		      f"{r['source']}); remove that permission row")
		marker = f'%"role": "{r["role"]}"%'
		if not frappe.db.exists("TEX Audit Event", {"action": internals.EXPOSED_ACTION, "reference_name": r["doctype"],
		                                            "new_value": ("like", marker)}):
			audit(internals.EXPOSED_ACTION, reference_doctype="DocType", reference_name=r["doctype"], new=r,
			      reason="a business role reads fields TEX withholds (ADR-056)")
	return exposed


def execute():
	cases = _stale_cases()
	hashes = _hashes_without_consent()
	added = [] if ran_before(PATCH) else internals.ensure_custom_perms()
	exposed = _report_exposed()
	print(f"p40: {cases} abandoned case(s) made anonymous (consent no longer held), {hashes} funnel e-mail "
	      f"hash(es) of profiles without consent removed; System Manager's permlevel-1 row added on customised "
	      f"permissions of: {', '.join(added) or '-'}; business roles reading withheld fields: {len(exposed)}")
