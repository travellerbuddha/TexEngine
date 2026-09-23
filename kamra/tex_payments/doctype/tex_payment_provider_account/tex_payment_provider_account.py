# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

from frappe.model.document import Document


class TEXPaymentProviderAccount(Document):
	"""An account is checked whoever saves it — TEX API, Desk or REST (G-67, ADR-041): the
	mock runs only in Sandbox, Production needs a provider certified against the live gateway,
	and a gateway URL override is refused on a Production account. ``provider_for`` checks
	the same rules again before every use."""

	def validate(self):
		from kamra.tex.payments.service import check_account

		check_account(self)
