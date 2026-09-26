"""NEW-1 (audit Part 2A, ADR-064): the versions the contract roll superseded by mistake get their state back.

The roll (every 15 minutes) read a published version without an end (``active_to`` NULL) as over:
``frappe.get_all`` compares ``IFNULL(active_to, '0001-01-01') <= now``. It set such a version
``Superseded`` and left ``active_to`` empty: the live version of every contract and every scheduled
one. Nothing else writes that: a publish sets a version's ``active_to`` before it supersedes it, a
withdraw sets it, and the roll now takes only versions with an end. ``Superseded`` without
``active_to`` is exactly the roll's mistake.

Such a version gets the state it would have had. A publish sees only Published versions, so none of
the publishes made after it on its contract touched it: they are replayed as ``publish`` does. A later
version starting at or before its start withdraws it (V2 scheduled for July, V3 published for June: V2
never sells); one starting after it ends it there, superseded once that start has passed. Otherwise it
is Published again. Each change is audited (``contract.version_restored``) and the contract's live
version follows at once (as the roll would). Payloads, hashes and sold stays are not touched; a second
run finds nothing."""

import frappe
from frappe.utils import get_datetime, now_datetime

from kamra.tex.commercial import contracts
from kamra.tex.security.audit import audit

ACTION = "contract.version_restored"
REASON = "NEW-1: the contract roll had superseded a version without an end"


def execute():
	now = now_datetime()
	broken = frappe.get_all("TEX Contract Version", filters=[["status", "=", "Superseded"],
	                                                         ["active_to", "is", "not set"]],
	                        fields=["name", "contract", "version_no", "effective_from"], order_by="name asc")
	touched = set()
	for v in broken:
		status, active_to = restored_state(v, now)
		frappe.db.set_value("TEX Contract Version", v.name, {"status": status, "active_to": active_to},
		                    update_modified=False)
		audit(ACTION, reference_doctype="TEX Contract Version", reference_name=v.name,
		      property=frappe.db.get_value("TEX Contract", v.contract, "property"),
		      old={"status": "Superseded", "active_to": None},
		      new={"status": status, "active_to": str(active_to) if active_to else None},
		      reason=REASON, source="System")
		touched.add(v.contract)
	for c in sorted(touched):
		if frappe.db.get_value("TEX Contract", c, "status") != "Active":
			continue
		live = contracts.active_version_header(c, now)
		new = live.version_id if live else None
		if frappe.db.get_value("TEX Contract", c, "active_version") != new:
			contracts._isolated(c, lambda c=c, new=new: contracts._go_live(c, new))
	if touched:
		contracts.clear_terms_cache()


def restored_state(version, now) -> tuple[str, object]:
	"""(status, active_to) after the publishes made later on its contract, replayed as ``publish``
	treats another Published version (``contracts.publish``); the roll ends it once its end passed.
	One draft at a time per contract, so a higher version number was published later."""
	if not version.effective_from:
		return "Published", None                            # never on sale: nothing to replay
	start = get_datetime(version.effective_from)
	active_to = None
	later = frappe.get_all("TEX Contract Version",
	                       filters=[["contract", "=", version.contract], ["version_no", ">", version.version_no],
	                                ["status", "!=", "Draft"], ["effective_from", "is", "set"]],
	                       fields=["effective_from", "published_at"], order_by="version_no asc")
	for p in later:
		eff = get_datetime(p.effective_from)
		at = get_datetime(p.published_at) if p.published_at else eff
		if active_to is not None and active_to <= at:
			return "Superseded", active_to                  # the roll ended it before this publish
		if start >= eff:
			return "Withdrawn", start
		if active_to is None or active_to > eff:
			active_to = eff
			if eff <= at:
				return "Superseded", active_to
	if active_to is not None and active_to <= now:
		return "Superseded", active_to
	return "Published", active_to
