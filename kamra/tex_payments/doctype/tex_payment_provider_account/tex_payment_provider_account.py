# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

from frappe.model.document import Document


class TEXPaymentProviderAccount(Document):
	"""An account is checked whoever saves it — TEX API, Desk or REST (G-67, ADR-041). An
	enabled account must be able to take new money: the mock runs only in Sandbox, Production
	needs a provider certified against the live gateway and takes no gateway URL override, a
	Sandbox override stays on the provider's sandbox host, and a live site (tex_production)
	runs no sandbox gateway. A disabled account can always be saved (switched off, its secrets
	rotated): it runs nothing until it is enabled again. ``provider_for`` checks the same rules
	again before every use."""

	def validate(self):
		from kamra.tex.payments.service import check_account

		check_account(self, purpose="new" if self.enabled else "keep")
