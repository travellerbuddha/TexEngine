"""O-31: a promotion code is stored by its key (``promotions.code_key``).

A code saved before was upper-cased with ``str.upper``, which keeps the Turkish dotted İ ("wİnter" was
stored as WİNTER) while a guest typing "winter" is keyed WINTER: the code never matched. Every TEX
Promotion with a code (whatever its status) whose code is not its key gets its key, without touching
``modified``. Redemptions, frozen payloads and pricing snapshots keep what they recorded.

Reported for the owner (audited once, G-76): a promotion changed by this run whose code's key another
draft or live promotion of the same hotel scope (a different record) already has,
``promotion.code_clash``: the save refuses such a pair, so one of them needs another code. A second run
changes nothing and reports nothing.

The key is O-31's, as this patch was written (``o31_key``): C-12 (2026-10-03) later made Ş, Ğ, Ü, Ö, Ç
S, G, U, O, C in ``promotions.code_key``. A stored code is keyed again on every read (the engine, the
contract's offers, a promotion's save and its clash check), so a code this patch stored as KIŞ matches KIS.
"""

import unicodedata

import frappe

from kamra.tex.security.audit import audit, recorded

OPEN = ("Draft", "Active")


def o31_key(code: str | None) -> str | None:
	"""``promotions.code_key`` as O-31 made it: the Turkish dotted and dotless i as I, upper-cased, a
	combining dot above an I dropped, to a fixed point; Ş, Ğ, Ü, Ö, Ç kept (before C-12)."""
	if code is None:
		return None
	key = unicodedata.normalize("NFC", str(code).strip())
	for _pass in range(len(key) + 2):
		step = unicodedata.normalize(
			"NFC", key.replace("\u0130", "I").replace("\u0131", "I").upper().replace("I\u0307", "I"))
		if step == key:
			break
		key = step
	return key or None


def execute():
	rows = frappe.get_all("TEX Promotion", filters={"trigger": "Code"},
	                      fields=["name", "code", "tex_status", "property", "revision_of"], order_by="name asc")
	changed = []
	for r in rows:
		key = o31_key(r.code)
		if r.code and key and key != r.code:
			frappe.db.set_value("TEX Promotion", r.name, "code", key, update_modified=False)
			r.code = key
			changed.append(r.name)
	clashes = _clashes([r for r in rows if r.tex_status in OPEN], set(changed))
	print(f"p60: {len(changed)} promotion code(s) set to their key"
	      + (": " + ", ".join(changed) if changed else "")
	      + f"; {len(clashes)} clash(es) with another draft or live promotion of the same hotel"
	      + (": " + ", ".join(f"{a} = {b} ({code})" for a, b, code in clashes) if clashes else ""))


def _clashes(rows, changed: set[str]) -> list[tuple[str, str, str]]:
	"""(a record with a revision changed by this run, another record with a draft or live revision of
	the same key in the same hotel scope, the key), by their roots (a record's id): each pair once,
	audited on the changed record."""
	root = {r.name: r.revision_of or r.name for r in rows}
	scope: dict[tuple[str, str], list] = {}
	for r in rows:
		scope.setdefault((r.property or "", r.code), []).append(r)
	out, seen = [], set()
	for (_prop, code), same in sorted(scope.items()):
		for r in same:
			if r.name not in changed:
				continue
			me, others = root[r.name], []
			for other in sorted({root[o.name] for o in same} - {me}):
				pair = frozenset((me, other))
				if pair not in seen:
					seen.add(pair)
					others.append(other)
			if not others:
				continue
			out.extend((me, o, code) for o in others)
			new = {"code": code, "clashes_with": others}
			if recorded("promotion.code_clash", reference_doctype="TEX Promotion", reference_name=me, new=new):
				continue
			audit("promotion.code_clash", reference_doctype="TEX Promotion", reference_name=me,
			      property=r.property or None, source="System", new=new,
			      reason="Its code, stored by its key (Turkish İ as I), is the code of another draft or live "
			             "promotion of the same hotel: give one of them another code (O-31).")
	return out
