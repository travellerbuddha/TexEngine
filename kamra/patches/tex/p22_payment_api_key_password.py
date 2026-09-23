"""A payment provider account's API key is a Password field (G-83).

The DocType change (Data → Password) is synced before this patch (post_model_sync); the
column still holds the plain keys. Each one moves to Frappe's encrypted store and the column
keeps asterisks, like every Password field. A column that is already all asterisks was moved
before (the patch is idempotent). Nothing about a key is printed or logged: only how many.
"""

import frappe
from frappe.utils.password import set_encrypted_password

DOCTYPE = "TEX Payment Provider Account"


def execute():
	moved = 0
	for r in frappe.db.sql(f"SELECT name, api_key FROM `tab{DOCTYPE}` WHERE IFNULL(api_key, '') != ''", as_dict=True):
		if set(r.api_key) == {"*"}:
			continue                              # already in the encrypted store
		set_encrypted_password(DOCTYPE, r.name, r.api_key, "api_key")
		frappe.db.sql(f"UPDATE `tab{DOCTYPE}` SET api_key=%s WHERE name=%s", ("*" * len(r.api_key), r.name))
		moved += 1
	if moved:
		print(f"TEX payments: moved {moved} provider API key(s) into the encrypted store")
