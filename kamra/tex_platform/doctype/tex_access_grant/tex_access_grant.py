# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class TEXAccessGrant(Document):
	def validate(self):
		need = {"Hotel": "property", "Hotel Group": "hotel_group", "Enterprise": "enterprise"}.get(self.scope_level)
		if need and not self.get(need):
			frappe.throw(_("{0} scope needs {1}.").format(self.scope_level, self.meta.get_label(need)))
		for f in ("property", "hotel_group", "enterprise"):
			if f != need:
				self.set(f, None)
		if self.scope_level == "Platform" and "System Manager" not in frappe.get_roles():
			frappe.throw(_("Only platform administrators grant platform scope."), frappe.PermissionError)
		from kamra.tex.security import grants

		grants.assert_can_manage(self)

	def on_update(self):
		from kamra.tex.security import grants

		grants.sync_user_permissions(self.user)
		grants.audit_grant(self, "grant.update")

	def on_trash(self):
		from kamra.tex.security import grants

		grants.audit_grant(self, "grant.delete")

	def after_delete(self):
		from kamra.tex.security import grants

		grants.sync_user_permissions(self.user)
