"""O-38 (audit 2B, ADR-065): one payment link per idempotency key, enforced by the database.

``TEX Payment Link.idempotency_key`` becomes unique. Two ``create_link`` calls with the same key at
the same moment both passed the check-then-insert and made two links (and two e-mails). The unique
index the model sync adds would stop on keys already duplicated, so this patch runs before it
(``[pre_model_sync]``), with DML and raw SQL only:
- each key's oldest link (creation, name) keeps it; every later one gets ``{key}:dup:{name}``, its
  status untouched, and ``payment_link.key_deduplicated`` names the link that kept the key;
- an empty key becomes NULL (a unique index takes any number of NULLs, a single empty string).
A second run finds nothing."""

KEY_LENGTH = 140          # the column's (a Data field)


def plan(rows) -> tuple[list[tuple[str, str, str]], list[str]]:
	"""``rows``: (name, key, creation) of every link, in any order. → (renames: [(name, new key, the link
	keeping the key)] for every later link of a key, oldest first by (creation, name); blanks: the names
	whose key is an empty string). Pure: no database."""
	by_key: dict[str, list[tuple]] = {}
	blanks = []
	for name, key, creation in rows:
		if key is None:
			continue
		if not str(key).strip():
			blanks.append(name)
			continue
		by_key.setdefault(key, []).append((creation, name))
	renames = []
	for key in sorted(by_key):
		links = sorted(by_key[key])
		kept = links[0][1]
		for _creation, name in links[1:]:
			suffix = f":dup:{name}"
			renames.append((name, key[:KEY_LENGTH - len(suffix)] + suffix, kept))
	return renames, sorted(blanks)


def rows() -> list[tuple]:
	import frappe

	return frappe.db.sql("""SELECT name, idempotency_key, creation FROM `tabTEX Payment Link`
	                        WHERE idempotency_key IS NOT NULL""")


def execute():
	import frappe

	from kamra.tex.security.audit import audit

	if not frappe.db.table_exists("TEX Payment Link"):
		return
	renames, blanks = plan(rows())
	for name, key, kept in renames:
		old = frappe.db.sql("SELECT idempotency_key, property FROM `tabTEX Payment Link` WHERE name=%s", name)
		frappe.db.sql("UPDATE `tabTEX Payment Link` SET idempotency_key=%s WHERE name=%s", (key, name))
		audit("payment_link.key_deduplicated", reference_doctype="TEX Payment Link", reference_name=name,
		      property=old[0][1] if old else None, old={"idempotency_key": old[0][0] if old else None},
		      new={"idempotency_key": key, "kept_by": kept}, reason="p57: one payment link per idempotency key")
	if blanks:
		frappe.db.sql("UPDATE `tabTEX Payment Link` SET idempotency_key=NULL WHERE name IN %(names)s",
		              {"names": tuple(blanks)})
