"""G-83 security hygiene (R-53, ADR-046). Each test reproduced its defect before the fix.

- a CRM communication links only this guest's records at the caller's hotels;
- an anonymous booker cannot grant marketing consent on an existing profile;
- uploads are checked on the server (magic bytes, size, no public HTML/SVG);
- bearer tokens stay out of URL paths, query strings and Referer headers;
- a PMS webhook is never delivered unsigned;
- a payment provider's API key is a write-only encrypted secret.
"""

import base64
import hashlib
import hmac
import io
import json
import os
from unittest import mock

import frappe
from frappe.utils import add_to_date, now_datetime
from frappe.utils.password import remove_encrypted_password
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from kamra.tex.api import admin as admin_api
from kamra.tex.api import crm as crm_api
from kamra.tex.api import payments as pay_api
from kamra.tex.api import policies as policy_api
from kamra.tex.api import public
from kamra.tex.crm import service as crm
from kamra.tex.payments import service as pay
from kamra.tex.security import scope
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import (
	GUEST,
	SLUG,
	guest_books,
	setup_site_and_payments,
)
from kamra.tex.tests.integration.test_critical_journey import TexTestCase
from kamra.tex.tests.integration.test_security_regressions import OTHER, other_hotel_with_mock


def png_bytes(size=(4, 4)) -> bytes:
	from PIL import Image

	buf = io.BytesIO()
	Image.new("RGB", size, (200, 30, 30)).save(buf, format="PNG")
	return buf.getvalue()


SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><script>alert(document.cookie)</script></svg>'
HTML = b"<!doctype html><html><body><script>fetch('/api/method/frappe.auth.get_logged_user')</script></body></html>"


class TestSecurityHygieneG83(TexTestCase):
	def setUp(self):
		super().setUp()
		self.p = setup_site_and_payments(self.f)
		other_hotel_with_mock()
		self.agent = fx.ensure_user("g83-agent@example.com", ["Front Desk"])
		fx.ensure("TEX Access Grant", {"user": self.agent, "property": fx.PROPERTY},
		          {"user": self.agent, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Reservations Agent"})
		self.editor = fx.ensure_user("g83-editor@example.com", ["Revenue Manager"])
		fx.ensure("TEX Access Grant", {"user": self.editor, "property": fx.PROPERTY},
		          {"user": self.editor, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Revenue Manager"})
		self.outsider = fx.ensure_user("g83-outsider@example.com", ["Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": self.outsider, "property": OTHER},
		          {"user": self.outsider, "scope_level": "Hotel", "property": OTHER,
		           "permission_profile": "Hotel Admin"})
		scope.clear_cache()

	def as_user(self, user: str):
		frappe.set_user(user)  # nosemgrep: frappe-setuser -- test context switch
		scope.clear_cache()

	# ── 1. CRM communication links ────────────────────────────────────────

	def test_g83_a_communication_links_only_this_guests_records_at_my_hotels(self):
		mine = guest_books(session="g83-comm-a", guest={**GUEST, "email": "g83-comm@example.com"})
		theirs = guest_books(session="g83-comm-b", guest={**GUEST, "email": "g83-someone@example.com"})
		self.as_user("Administrator")
		guest = frappe.db.get_value("TEX Booking", mine["booking"], "booker_guest")
		foreign = frappe.get_doc({"doctype": "TEX Booking", "property": OTHER, "status": "Confirmed",
		                          "booker_guest": guest, "currency": "EUR"}).insert(ignore_permissions=True)
		self.as_user(self.agent)
		ok = crm_api.log_communication(guest=guest, channel="Phone", subject="Call about the transfer",
		                               booking=mine["booking"], reservation=mine["rooms"][0]["reservation"])
		row = frappe.db.get_value("TEX Communication", ok["name"], ["property", "booking", "reservation"],
		                          as_dict=True)
		self.assertEqual((row.property, row.booking), (fx.PROPERTY, mine["booking"]))
		for bad in ({"booking": foreign.name},                                   # another hotel's booking
		            {"booking": theirs["booking"]},                              # another guest's booking
		            {"reservation": theirs["rooms"][0]["reservation"]},          # another guest's stay
		            {"booking": "TEX-NOPE-00001"}, {"reservation": "RES-NOPE"},  # no such record
		            {"booking": theirs["booking"], "reservation": mine["rooms"][0]["reservation"]},
		            {"booking": mine["booking"], "property": OTHER},             # a hotel that is not mine
		            {"direction": "Sideways"}, {"consent_basis": "marketing"}):
			with self.assertRaises((frappe.PermissionError, frappe.ValidationError), msg=str(bad)):
				crm_api.log_communication(guest=guest, channel="Phone", **bad)
		self.as_user(self.outsider)                     # the other hotel's staff do not see this guest at all
		with self.assertRaises(frappe.PermissionError):
			crm_api.log_communication(guest=guest, channel="Phone", booking=foreign.name)

	# ── 2. marketing consent from an anonymous booking ────────────────────

	def test_g83_an_anonymous_booker_cannot_grant_consent_on_an_existing_profile(self):
		self.as_user("Administrator")
		existing = frappe.get_doc({"doctype": "Guest", "first_name": "Ada", "last_name": "Existing",
		                           "email": "g83-ada@example.com", "tex_enterprise": self.f["enterprise"]}
		                          ).insert(ignore_permissions=True)
		booked = guest_books(session="g83-consent-a", guest={**GUEST, "email": "g83-ada@example.com",
		                                                     "consent_email": 1, "consent_sms": 1})
		self.as_user("Administrator")
		self.assertEqual(frappe.db.get_value("TEX Booking", booked["booking"], "booker_guest"), existing.name)
		g = frappe.db.get_value("Guest", existing.name, ["tex_consent_email", "tex_consent_sms"], as_dict=True)
		self.assertEqual((g.tex_consent_email, g.tex_consent_sms), (0, 0))       # typing an e-mail grants nothing
		asked = frappe.get_all("TEX Audit Event", filters={"action": "guest.consent_requested",
		                                                   "reference_name": existing.name}, pluck="new_value")
		self.assertEqual(len(asked), 1)                                          # the request is on record
		self.assertIn(booked["booking"], asked[0])
		self.assertIn("tex_consent_email", asked[0])
		self.as_user(self.agent)                        # and the hotel sees it, to confirm on a verified channel
		history = crm.profile(existing.name)["consent_history"]
		self.assertEqual([(h["action"], h["booking"]) for h in history],
		                 [("guest.consent_requested", booked["booking"])])
		self.assertEqual(json.loads(history[0]["new_value"]), {"tex_consent_email": True, "tex_consent_sms": True})
		# a profile the booking creates records the booker's own consent, on the record
		fresh = guest_books(session="g83-consent-b", guest={**GUEST, "email": "g83-new@example.com",
		                                                    "consent_email": 1})
		self.as_user("Administrator")
		new_guest = frappe.db.get_value("TEX Booking", fresh["booking"], "booker_guest")
		self.assertNotEqual(new_guest, existing.name)
		self.assertEqual(frappe.db.get_value("Guest", new_guest, ["tex_consent_email", "tex_consent_source"]),
		                 (1, "booking"))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "guest.consent", "reference_name": new_guest}))
		# abandoned-payment recovery follows the profile's consent, not the anonymous tick
		crm.detect_abandoned(now=add_to_date(now_datetime(), minutes=60))
		left = {r.session_id: r for r in frappe.get_all(
			"TEX Abandoned Booking", filters={"session_id": ("in", ["g83-consent-a", "g83-consent-b"])},
			fields=["session_id", "guest", "email", "consent_marketing"])}
		self.assertEqual((left["g83-consent-a"].guest, left["g83-consent-a"].email,
		                  left["g83-consent-a"].consent_marketing), (None, None, 0))
		self.assertEqual((left["g83-consent-b"].guest, left["g83-consent-b"].consent_marketing), (new_guest, 1))
		# staff, who took the guest's word and are accountable for it, still record it on a known profile
		from kamra.tex.services import booking as booking_svc

		self.as_user(self.agent)
		name, granted, requested = booking_svc.resolve_guest(
			{**GUEST, "email": "g83-ada@example.com", "consent_email": True}, property=fx.PROPERTY, market="DE",
			language="en", staff=True)
		self.assertEqual((name, granted, requested), (existing.name, ["tex_consent_email"], []))
		# withdrawing stays one step: staff record it in the CRM
		crm_api.update_guest(existing.name, {"tex_consent_email": 0}, consent_source="guest asked by phone")
		self.assertEqual(frappe.db.get_value("Guest", existing.name, "tex_consent_email"), 0)

	# ── 3. uploads ────────────────────────────────────────────────────────

	def upload(self, name: str, content: bytes, **kw):
		"""The endpoint as a browser's multipart POST reaches it."""
		env = EnvironBuilder(method="POST", path="/api/method/kamra.tex.api.admin.upload_site_image",
		                     data={"file": (io.BytesIO(content), name)}).get_environ()
		with mock.patch.object(frappe.local, "request", Request(env), create=True):
			return admin_api.upload_site_image(**kw)

	def test_g83_uploads_are_checked_on_the_server(self):
		self.as_user(self.editor)
		out = self.upload("hotel logo.PNG", png_bytes(), site=SLUG)
		f = frappe.db.get_value("File", {"file_url": out["file_url"]},
		                        ["is_private", "attached_to_doctype", "attached_to_name", "file_name"], as_dict=True)
		self.assertEqual((f.is_private, f.attached_to_doctype, f.attached_to_name), (0, "TEX Booking Site", SLUG))
		self.assertTrue(f.file_name.endswith(".png"), f.file_name)
		# the bytes decide, never the name: markup named .png, SVG, a broken image, too big, empty
		for name, content in (("logo.png", HTML), ("logo.svg", SVG), ("logo.gif", SVG),
		                      ("logo.png", png_bytes()[:40]), ("logo.png", png_bytes() + b"\0" * (2 * 1024 * 1024)),
		                      ("logo.png", b"")):
			with self.assertRaises(frappe.ValidationError, msg=f"{name} {content[:20]!r}"):
				self.upload(name, content, site=SLUG)
		self.as_user(self.outsider)                     # another hotel's admin cannot brand this site
		with self.assertRaises(frappe.PermissionError):
			self.upload("logo.png", png_bytes(), site=SLUG)
		with self.assertRaises(frappe.PermissionError):
			self.upload("logo.png", png_bytes(), property=fx.PROPERTY)
		# the generic Frappe upload path never serves active content from the public folder
		self.as_user(self.editor)
		for name, content in (("page.html", HTML), ("logo.svg", SVG), ("x.xhtml", HTML), ("x.js", b"alert(1)")):
			with self.assertRaises(frappe.ValidationError, msg=name):
				frappe.get_doc({"doctype": "File", "file_name": name, "content": content, "is_private": 0}
				               ).insert(ignore_permissions=True)
			self.assertFalse(os.path.exists(frappe.get_site_path("public", "files", name)), name)   # never written
		kept = frappe.get_doc({"doctype": "File", "file_name": "kept.svg", "content": SVG, "is_private": 1}
		                      ).insert(ignore_permissions=True)          # private: served as a download only
		self.assertTrue(kept.file_url.startswith("/private/files/"))
		kept.is_private = 0
		with self.assertRaises(frappe.ValidationError):                   # and it cannot be made public later
			kept.save(ignore_permissions=True)
		# a booking site's images are image addresses, never script or active content
		self.as_user("Administrator")
		site = frappe.get_doc("TEX Booking Site", SLUG)
		for bad in ("javascript:alert(1)", "/files/evil.svg", "http://insecure.example/logo.png",
		            'https://x.example/a.png" onerror="alert(1)', "/files/page.html"):
			site.logo = bad
			with self.assertRaises(frappe.ValidationError, msg=bad):
				site.save(ignore_permissions=True)
		site.reload()
		site.logo, site.hero_image = out["file_url"], "https://images.example.com/hero.webp"
		site.save(ignore_permissions=True)

	# ── 4. tokens in URLs ─────────────────────────────────────────────────

	def test_g83_bearer_tokens_stay_out_of_url_paths_and_referers(self):
		self.as_user("Administrator")
		link = pay.create_link(property=fx.PROPERTY, amount="10", currency="EUR", description="deposit")
		self.assertNotIn(f"/pay/{link['token']}", link["url"])
		self.assertTrue(link["url"].endswith(f"/book/pay#token={link['token']}"), link["url"])
		again = pay.reissue_link(link["link"])
		self.assertTrue(again["url"].endswith(f"/book/pay#token={again['token']}"), again["url"])
		# guest reads that take a bearer token accept it in a POST body only, never in a query string
		for fn in (public.booking_status, public.payment_link, public.manage_extras):
			self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func.get(fn), ["POST"], fn.__name__)
		# payment pages send no Referer: an old e-mailed /book/pay/<token> link never leaks through it
		from kamra.tex import booking_host
		from kamra.www import book

		page = '<html><head><meta name="referrer" content="strict-origin-when-cross-origin" /></head></html>'
		frappe.local.response_headers = {}
		try:
			with mock.patch("kamra.www.book.booking_html", return_value=page):
				frappe.form_dict.app_path = f"pay/{again['token']}"
				ctx = book.get_context(frappe._dict())
				self.assertEqual(frappe.local.response_headers["Referrer-Policy"], "no-referrer")
				self.assertIn('content="no-referrer"', ctx.spa_html)
				self.assertNotIn("strict-origin-when-cross-origin", ctx.spa_html)
				frappe.local.response_headers = {}
				frappe.form_dict.app_path = f"{SLUG}/manage"                 # the other pages are unchanged
				book.get_context(frappe._dict())
				self.assertEqual(frappe.local.response_headers["Referrer-Policy"], "strict-origin-when-cross-origin")
		finally:
			frappe.form_dict.pop("app_path", None)
		self.assertEqual(booking_host.referrer_policy("pay/abc"), "no-referrer")          # a hotel's own host
		self.assertEqual(booking_host.referrer_policy("manage"), "strict-origin-when-cross-origin")
		# an existing link keeps working: the page reads its token and posts it
		self.as_user("Guest")
		self.assertEqual(public.payment_link(token=again["token"])["status"], "Active")

	# ── 5. PMS webhook signing ────────────────────────────────────────────

	def test_g83_a_pms_webhook_is_never_sent_unsigned(self):
		from kamra.tex.connect import outbox
		from kamra.tex.distribution import repository as dist

		self.as_user("Administrator")
		base = {"doctype": "TEX Integration Connection", "label": "PMS hook", "property": fx.PROPERTY,
		        "category": "PMS", "adapter": "webhook", "environment": "Production", "enabled": 1,
		        "endpoint_url": "https://pms.example.com/tex"}
		for env in ("Production", "Sandbox"):
			with self.assertRaises(frappe.ValidationError, msg=env):          # no signing secret: refused on save
				frappe.get_doc({**base, "environment": env}).insert(ignore_permissions=True)
		frappe.get_doc({**base, "enabled": 0, "label": "draft"}).insert(ignore_permissions=True)   # a draft may wait
		secret = "g83-signing-secret-0123456789"
		conn = frappe.get_doc({**base, "secret": secret}).insert(ignore_permissions=True)
		guest_books(session="g83-pms")
		self.as_user("Administrator")
		queued = frappe.get_all("TEX Integration Outbox", filters={"connection": conn.name}, pluck="name")
		self.assertEqual(len(queued), 1)
		with mock.patch("kamra.tex.connect.adapters.requests.post") as post:
			dist._each(dist.claim("Reservation", 50, connection=conn.name), outbox._deliver, outbox._failed)
		sent = post.call_args.kwargs
		self.assertEqual(sent["headers"]["X-TEX-Signature"],
		                 "sha256=" + hmac.new(secret.encode(), sent["data"], hashlib.sha256).hexdigest())
		# the secret removed behind the controller's back: nothing leaves, the event is dead at once
		remove_encrypted_password("TEX Integration Connection", conn.name, "secret")
		frappe.db.set_value("TEX Integration Connection", conn.name, "secret", "")
		frappe.db.set_value("TEX Integration Outbox", queued[0], {"status": "Pending", "attempts": 0,
		                                                         "next_attempt_at": now_datetime()})
		with mock.patch("kamra.tex.connect.adapters.requests.post") as post:
			dist._each(dist.claim("Reservation", 50, connection=conn.name), outbox._deliver, outbox._failed)
		post.assert_not_called()
		row = frappe.db.get_value("TEX Integration Outbox", queued[0], ["status", "attempts", "last_error"],
		                          as_dict=True)
		self.assertEqual((row.status, row.attempts), ("Dead", 1), row)
		self.assertIn("signing secret", row.last_error)
		refused = frappe.get_all("TEX Audit Event", filters={"action": "connect.delivery_refused",
		                                                     "reference_name": queued[0]}, pluck="new_value")
		self.assertEqual(len(refused), 1)
		self.assertNotIn(secret, refused[0])

	# ── 6. payment provider API key ───────────────────────────────────────

	def test_g83_a_payment_api_key_is_a_write_only_secret(self):
		self.as_user("Administrator")
		key = "ak-live-g83-0123456789"
		name = pay_api.save_account(property=fx.PROPERTY, data={
			"label": "iyzico g83", "provider": "iyzico", "environment": "Sandbox", "enabled": 1,
			"currencies": "EUR", "api_key": key, "secret_key": "sk-g83"})["name"]
		self.assertNotIn(key, str(frappe.db.get_value("TEX Payment Provider Account", name, "api_key")))
		self.assertEqual(frappe.get_doc("TEX Payment Provider Account", name).get_password("api_key"), key)
		listed = pay_api.accounts(property=fx.PROPERTY)
		self.assertNotIn(key, json.dumps(listed, default=str))
		self.assertTrue(next(a for a in listed["accounts"] if a["name"] == name)["secrets_set"]["api_key"])
		self.assertNotIn(key, json.dumps(policy_api.get_record("TEX Payment Provider Account", name), default=str))
		pay_api.save_account(property=fx.PROPERTY, data={"name": name, "label": "iyzico g83 renamed"})
		acc = frappe.get_doc("TEX Payment Provider Account", name)
		self.assertEqual(acc.get_password("api_key"), key)                       # blank keeps the stored key
		for v in frappe.get_all("TEX Audit Event", filters={"reference_name": name}, pluck="new_value"):
			self.assertNotIn(key, v or "")
		# the gateway call is signed with the decrypted key, not the masked column
		from kamra.tex.payments.providers import turkey

		with mock.patch.object(turkey.requests, "post") as post:
			post.return_value.json.return_value = {"status": "success"}
			turkey.IyzicoProvider(acc)._post(turkey.IyzicoProvider.DETAIL, {"token": "t"})
		auth = post.call_args.kwargs["headers"]["Authorization"].split(" ", 1)[1]
		self.assertTrue(base64.b64decode(auth).decode().startswith(f"apiKey:{key}&"))

	def test_g83_p22_moves_plain_api_keys_into_the_encrypted_store(self):
		from kamra.patches.tex import p22_payment_api_key_password as p22

		self.as_user("Administrator")
		name = frappe.get_doc({"doctype": "TEX Payment Provider Account", "label": "legacy iyzico",
		                       "property": fx.PROPERTY, "provider": "iyzico", "environment": "Sandbox",
		                       "enabled": 0}).insert(ignore_permissions=True).name
		remove_encrypted_password("TEX Payment Provider Account", name, "api_key")
		frappe.db.sql("UPDATE `tabTEX Payment Provider Account` SET api_key=%s WHERE name=%s",
		              ("plain-key-g83", name))                                   # as stored before p22
		with mock.patch("builtins.print") as printed:
			p22.execute()
			p22.execute()                                                        # idempotent
		self.assertNotIn("plain-key-g83", str(printed.call_args_list))
		self.assertEqual(frappe.db.get_value("TEX Payment Provider Account", name, "api_key"), "*" * 13)
		self.assertEqual(frappe.get_doc("TEX Payment Provider Account", name).get_password("api_key"),
		                 "plain-key-g83")
