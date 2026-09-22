"""Guest e-mails (no secrets stored), payment-link reissue and the legacy data
migrations T6 (vouchers → promotions), T7 (experiences → extras), T8 (legacy contract)."""

import email

import frappe

from kamra.patches.tex import p05_vouchers_to_promotions, p06_experiences_to_extras
from kamra.tex.commercial import contracts, legacy
from kamra.tex.payments import service as pay
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import guest_books, setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase


def ensure_test_outbox():
	"""A default outgoing account so mails reach the Email Queue (nothing is sent in tests)."""
	if frappe.db.exists("Email Account", {"default_outgoing": 1, "enable_outgoing": 1}):
		return
	acc = frappe.get_doc({"doctype": "Email Account", "email_account_name": "TEX test outbox",
	                      "email_id": "tex-test@example.com", "enable_outgoing": 1, "default_outgoing": 1,
	                      "smtp_server": "localhost", "smtp_port": 2525, "no_smtp_authentication": 1,
	                      "awaiting_password": 0, "enable_incoming": 0})
	acc.flags.ignore_validate = True
	acc.insert(ignore_permissions=True)


class TestNotifications(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		ensure_test_outbox()

	def test_booking_email_carries_link_but_nothing_stores_the_token(self):
		b = guest_books(session="sess-mail")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- inspect queue
		mails = frappe.get_all("Email Queue", filters={"reference_doctype": "TEX Booking",
		                                               "reference_name": b["booking"]}, pluck="name")
		self.assertEqual(len(mails), 1)
		msg = email.message_from_string(frappe.get_doc("Email Queue", mails[0]).message)
		body = "".join(part.get_payload(decode=True).decode("utf-8", "replace") for part in msg.walk()
		               if part.get_content_type() == "text/html")
		self.assertIn(f"#token={b['manage_token']}", body)
		self.assertIn("842.50 EUR", body)          # in the mail, in the URL fragment
		comm = frappe.get_all("TEX Communication", filters={"booking": b["booking"]}, fields=["body", "template"])
		self.assertEqual(comm[0].template, "booking_pending")
		self.assertNotIn(b["manage_token"], str(comm))              # the log never holds the secret
		self.assertFalse(frappe.db.exists("TEX Booking", {"manage_token_hash": b["manage_token"]}))

	def test_payment_link_url_is_returned_once_and_can_be_reissued(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- call-centre agent
		out = pay.create_link(property=fx.PROPERTY, amount="80", currency="EUR", description="Deposit",
		                      guest_email="guest@example.com", guest_name="Guest", send_email=True)
		self.assertTrue(out["emailed"])
		self.assertIsNone(frappe.db.get_value("TEX Payment Link", out["link"], "public_url"))
		self.assertEqual(pay.link_by_token(out["token"]).name, out["link"])
		again = pay.reissue_link(out["link"])
		self.assertNotEqual(again["token"], out["token"])
		with self.assertRaises(frappe.DoesNotExistError):
			pay.link_by_token(out["token"])                         # the old URL is dead
		link = frappe.get_doc("TEX Payment Link", out["link"])
		link.amount = 1
		with self.assertRaises(frappe.ValidationError):
			link.save(ignore_permissions=True)                    # amount is immutable


class TestLegacyMigrations(TexTestCase):
	def test_vouchers_and_experiences_are_copied_once(self):
		v = frappe.get_doc({"doctype": "Discount Voucher", "property": fx.PROPERTY, "voucher_code": "summer15",
		                    "discount_type": "Percent", "value": 15, "max_uses": 40, "times_used": 3}).insert(
			ignore_permissions=True)
		bad = frappe.get_doc({"doctype": "Discount Voucher", "property": fx.PROPERTY, "voucher_code": "ZERO",
		                      "discount_type": "Percent", "value": 0}).insert(ignore_permissions=True)
		e = frappe.get_doc({"doctype": "Experience", "property": fx.PROPERTY, "experience_name": "Boat tour",
		                    "category": "Tour", "price": 55, "show_on_booking_page": 1}).insert(ignore_permissions=True)
		p05_vouchers_to_promotions.execute()
		p06_experiences_to_extras.execute()
		p05_vouchers_to_promotions.execute()
		p06_experiences_to_extras.execute()
		promo = frappe.get_all("TEX Promotion", filters={"legacy_voucher": v.name},
		                       fields=["code", "value", "usage_limit", "times_redeemed", "tex_status", "trigger"])
		self.assertEqual(len(promo), 1)
		self.assertEqual((promo[0].code, promo[0].trigger, promo[0].tex_status), ("SUMMER15", "Code", "Draft"))
		self.assertEqual((promo[0].usage_limit, promo[0].times_redeemed), (40, 3))
		self.assertFalse(frappe.db.exists("TEX Promotion", {"legacy_voucher": bad.name}))   # logged, not copied
		extra = frappe.get_all("TEX Extra", filters={"legacy_experience": e.name},
		                       fields=["extra_code", "category", "pricing_mode", "bookable_online"])
		self.assertEqual(len(extra), 1)
		self.assertEqual((extra[0].category, extra[0].pricing_mode, extra[0].bookable_online),
		                 ("Excursion", "UNIT", 1))

	def test_legacy_contract_draft_is_valid_and_unpublished(self):
		rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		frappe.db.set_value("Room Type", rt, {"extra_adult_price": 30, "child_price": 15,
		                                      "single_occupancy_price": 80})
		frappe.get_doc({"doctype": "Season", "property": fx.PROPERTY, "season_name": "Peak", "start_date": fx.d(7, 1),
		                "end_date": fx.d(8, 31), "adjustment_type": "Percent", "adjustment_value": 20,
		                "priority": 5}).insert(ignore_permissions=True)
		out = legacy.draft_from_legacy(fx.PROPERTY)
		v = frappe.get_doc("TEX Contract Version", out["version"])
		self.assertEqual(v.status, "Draft")
		self.assertEqual(frappe.db.get_value("TEX Contract", out["contract"], "pricing_basis"), "ROOM")
		peak = next(p for p in v.periods if p.period_name == "Peak")
		std_peak = next(r for r in v.period_rates if r.room_type == rt and r.period_code == peak.period_code)
		self.assertEqual(frappe.utils.flt(std_peak.value), 120.0)   # 100 base × 1.20
		check = contracts.validate_version(v.name)
		self.assertTrue(check["ok"], check["issues"])
		with self.assertRaises(frappe.ValidationError):
			legacy.draft_from_legacy(fx.PROPERTY)                    # never twice


class TestSecretsNeverLogged(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)

	def test_failed_mail_logs_no_link_or_token(self):
		for acc in frappe.get_all("Email Account", filters={"enable_outgoing": 1}, pluck="name"):
			frappe.db.set_value("Email Account", acc, {"enable_outgoing": 0, "default_outgoing": 0})
		frappe.local.outgoing_email_account = {}           # drop the per-process account cache
		started = frappe.utils.now_datetime()
		b = guest_books(session="sess-nomail")                  # booking still succeeds
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- read error log
		logs = frappe.get_all("Error Log", filters={"method": f"TEX booking e-mail {b['booking']}",
		                                             "creation": (">=", started)}, fields=["error"])
		self.assertEqual(len(logs), 1)
		self.assertNotIn(b["manage_token"], logs[0].error)
		self.assertNotIn("#token=", logs[0].error)
		self.assertIn("OutgoingEmailError", logs[0].error)
