"""Payment-link transactions stored the link page, bearer token included, as their return
address; the token is only kept as a hash (ADR-017, G-10)."""

import frappe


def execute():
	if not frappe.db.table_exists("TEX Payment Transaction"):
		return
	frappe.db.sql(
		"""UPDATE `tabTEX Payment Transaction` SET return_url = %s
		WHERE ifnull(payment_link, '') != '' AND return_url LIKE %s
		AND return_url NOT LIKE %s AND return_url NOT LIKE %s""",
		(frappe.utils.get_url("/book/pay/return"), "%/book/pay/%", "%/book/pay/return%", "%/book/pay/mock/%"),
	)
