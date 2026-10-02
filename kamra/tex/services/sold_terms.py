"""The contract terms a sold stay was priced on (G-73, ADR-058).

A reservation's price-locked snapshot keeps its contract version's periods, room, occupancy and
board rules by reference, not as a copy: the version (``contract.version``) and the sha256 of its
frozen payload (``contract.payload_hash``, also ``Reservation.tex_payload_hash``). The explanation in
the snapshot already names, night by night, the period and each rule that won with its values;
the definitions stay in the payload, which is immutable (the version controller), refused when it
does not hash to its own recorded hash (``contracts.load_terms``), and bound to the snapshot here:
whatever loads the snapshot's version for a sold stay (a reprice on any basis, the historical
simulator, extras added after booking) passes the recorded hash, and a payload that no longer
hashes to it is refused, audited, and the locked price never moves.
"""

from __future__ import annotations

import frappe
from frappe import _

from kamra.tex.commercial import contracts
from kamra.tex.security.audit import audit_refusal
from kamra.tex.services.refusals import with_code

REFUSED = "reservation.reprice_refused"


def sold_version(snap: dict) -> str | None:
	return (snap.get("contract") or {}).get("version")


def recorded_hash(res, snap: dict) -> str | None:
	"""The payload hash the sale recorded for the snapshot's version: the snapshot's own, else the
	reservation's column when it names the same version (both are price-locked, ADR-010)."""
	digest = (snap.get("contract") or {}).get("payload_hash")
	if digest:
		return digest
	if res.get("tex_contract_version") and res.get("tex_contract_version") == sold_version(snap):
		return res.get("tex_payload_hash") or None
	return None


def expected_hash(res, snap: dict, version: str | None) -> str | None:
	"""What ``version``'s payload must hash to when it prices this stay: the recorded hash when it
	is the version the stay was sold on (or last repriced on), else None (another version has no
	recorded hash to match: a new version is not the sold one)."""
	return recorded_hash(res, snap) if version and version == sold_version(snap) else None


# an audit of the same refusal (stay, use, basis, version and hash) at most once an hour: every
# click on such a stay is refused, the audit trail says it once (review of G-73, L4)
ONCE_PER = ("use", "basis", "version", "found_hash")


def refuse(res, snap: dict, error: Exception, *, use: str, basis: str | None = None,
           version: str | None = None, guest: bool = False):
	"""Refuse to price a sold stay on terms that are not the ones it was sold on: audited
	(``reservation.reprice_refused``, written outside the refused transaction), never a silent
	price on other terms. ``use``: reprice, simulate or add-on. ``version``: the version that
	failed; the error names it when it knows better (selection may fail on another contract's
	version, review L3).

	``guest``: the reason goes to a guest (the manage page, a guest's change applied later, whose
	error is kept on the request, a guest's extras): "contact the hotel", never the version, its
	hashes or what an administrator should do (review L2). Staff get the detail; so does the audit."""
	version = getattr(error, "version", None) or version
	found = getattr(error, "found_hash", None) or (
		frappe.db.get_value("TEX Contract Version", version, "payload_hash") if version else None)
	audit_refusal(REFUSED, reference_doctype="Reservation", reference_name=res.name, property=res.property,
	              new={"use": use, "basis": basis, "version": version, "sold_version": sold_version(snap),
	                   "recorded_hash": recorded_hash(res, snap), "found_hash": found},
	              reason=str(error)[:500], once_per=ONCE_PER)
	if guest:
		msg = _("This booking cannot be changed online right now. Please contact the hotel.")
	else:
		msg = _("Reservation {0} cannot be priced: {1} Its price stays as sold. Ask an administrator to check "
		        "the contract version before re-pricing it.").format(res.name, str(error))
	# a guest is told it cannot be changed online; staff get the class's RATE_UNAVAILABLE (G-70b)
	frappe.throw(msg, with_code(contracts.PayloadMismatch(version=version, found_hash=found),
	                            "CHANGE_NOT_ONLINE" if guest else None))


def load(res, snap: dict, version: str, *, use: str, guest: bool = False):
	"""``contracts.load_terms`` for a sold stay: the recorded hash is required of the version it
	was sold on (``expected_hash``); a refusal is ``refuse``d."""
	try:
		return contracts.load_terms(version, expected_hash=expected_hash(res, snap, version))
	except contracts.PayloadMismatch as e:
		refuse(res, snap, e, use=use, version=version, guest=guest)
