# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import validate_email_address

from kamra.tex.ops.checks import MAX_ALERT_RECIPIENTS, parse_recipients


class TEXSettings(Document):
	def validate(self):
		self.validate_alert_recipients()

	def validate_alert_recipients(self):
		"""System-status alert recipients (ADR-047): valid addresses, one per line, at most 20."""
		emails = parse_recipients(self.status_alert_recipients)
		bad = [e for e in emails if not validate_email_address(e)]
		if bad:
			frappe.throw(_("Not an e-mail address: {0}").format(", ".join(bad[:5])))
		if len(emails) > MAX_ALERT_RECIPIENTS:
			frappe.throw(_("At most {0} alert recipients.").format(MAX_ALERT_RECIPIENTS))
		self.status_alert_recipients = "\n".join(emails) or None
