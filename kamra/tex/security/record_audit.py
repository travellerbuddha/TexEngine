"""Audit of records whatever path saves them: TEX API, Desk, REST, a patch (G-74, ADR-053).

Wired as ``doc_events`` in ``kamra/hooks.py`` for the DocTypes in ``TRACKED``. Each create,
change and delete is one event: the non-secret fields old → new, child tables as collection
diffs, and secrets only as booleans (``<field>_set``, ``<field>_changed``): a secret's value,
its length or its hash never reaches the audit trail.
"""

from __future__ import annotations

import frappe

from kamra.tex.security.audit import audit, doc_values
from kamra.tex.security.changes import field_changes

# DocType → (action prefix, secret fields)
TRACKED = {
	"TEX Payment Policy": ("payment_policy", ()),
	"TEX Payment Provider Account": ("payment_account",
	                                 ("api_key", "secret_key", "merchant_key", "store_key", "webhook_secret")),
	"TEX Payment Method Rule": ("payment_rule", ()),
}


def _prefix(doc) -> tuple[str, tuple[str, ...]]:
	return TRACKED[doc.doctype]


def _stored_secret(doc, field: str) -> str | None:
	if doc.is_new() or not doc.name:
		return None
	from frappe.utils.password import get_decrypted_password

	return get_decrypted_password(doc.doctype, doc.name, field, raise_exception=False)


def capture_secrets(doc, method=None) -> None:
	"""``validate``: before Frappe stores a new secret (and puts asterisks in its place), note
	which secrets are set, set anew, replaced or removed. Values are compared, never kept."""
	secrets = _prefix(doc)[1]
	before = None if doc.is_new() else doc.get_doc_before_save()
	state = {}
	for f in secrets:
		value = doc.get(f)
		had = bool(before and before.get(f))
		fresh = bool(value) and not doc.is_dummy_password(value)
		has = bool(value)
		changed = (fresh and (not had or value != _stored_secret(doc, f))) or (had and not has)
		state[f] = {"had": had, "has": has, "changed": changed}
	doc.flags.tex_secret_state = state


def _secrets_now(doc) -> dict:
	return {f"{f}_set": s["has"] for f, s in (doc.flags.tex_secret_state or {}).items()}


def _values(doc) -> dict:
	return doc_values(doc, exclude=("amended_from",))


def after_insert(doc, method=None) -> None:
	prefix = _prefix(doc)[0]
	audit(f"{prefix}.create", reference_doctype=doc.doctype, reference_name=doc.name,
	      property=doc.get("property") or None, new={**_values(doc), **_secrets_now(doc)},
	      reason=doc.flags.tex_audit_reason)


def on_update(doc, method=None) -> None:
	if doc.flags.in_insert:
		return                                    # audited by after_insert
	prefix = _prefix(doc)[0]
	before = doc.get_doc_before_save()
	old, new = field_changes(_values(before) if before else {}, _values(doc))
	for f, s in (doc.flags.tex_secret_state or {}).items():
		if s["changed"]:
			old[f"{f}_set"], new[f"{f}_set"] = s["had"], s["has"]
			new[f"{f}_changed"] = True
	if not old and not new:
		return                                    # saved as it was
	audit(f"{prefix}.update", reference_doctype=doc.doctype, reference_name=doc.name,
	      property=doc.get("property") or (before.get("property") if before else None) or None, old=old, new=new,
	      reason=doc.flags.tex_audit_reason)


def on_trash(doc, method=None) -> None:
	prefix, secrets = _prefix(doc)
	audit(f"{prefix}.delete", reference_doctype=doc.doctype, reference_name=doc.name,
	      property=doc.get("property") or None,
	      old={**_values(doc), **{f"{f}_set": bool(doc.get(f)) for f in secrets}},
	      reason=doc.flags.tex_audit_reason)
