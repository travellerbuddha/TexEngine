"""CRM, privacy and pricing-internals regressions (ADR-056).

G-65 (R-37) · a guest's loyalty is shown only in the viewer's programs, the other hotels' entries
of a shared (group) program without their bookings; the stored totals over every tenant (points,
stays, value) are never served, by the TEX API or by Desk / REST; the guest list pages and counts in SQL inside the viewer's tenancy; the profile shows the
extras bought and the cancellations (count, fees per currency) at the viewer's hotels.

G-81 (R-38) · a funnel event keeps an e-mail hash only with the visitor's marketing consent, never
contact data a browser sends; p37 purges hashes kept without consent; the consented-contact path
(contact data of a profile that consented, shown while the consent holds) and the recovery paths
(a later booking in the session, a payment made later) work end to end.

G-95 (R-14, R-43) · the price-locked snapshot, cost, margin, FX rate, a quote's result and a
revision's snapshots are never readable through Desk / REST by a business role (Frappe permlevel,
also in a write's response and in the change history); the TEX API serves them with
``price.view_cost`` only.

Review follow-up (ADR-056): the program ledger masks other hotels' entries and guests the viewer
cannot see; a withdrawal of e-mail consent makes a guest's abandoned cases and funnel hashes
anonymous, and the contact fields are withheld from Desk / REST (p40 for older rows); a browser's
funnel event keeps only its allow-listed fields; a consent sent as text means what it says; p40 and
the permission scripts keep platform administrators reading withheld fields on customised role
permissions; a masked change history keeps its values for platform administrators; only a
generic write's response leaves the withheld fields out (never ``db_set`` or code's own saves).
"""

import hashlib
import json
from contextlib import contextmanager
from unittest import mock

import frappe
import frappe.api.v1
import frappe.api.v2
import frappe.client
import frappe.desk.form.load
from frappe.model.base_document import BaseDocument
from frappe.utils import add_to_date, now_datetime
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from kamra.tex.api import admin as admin_api
from kamra.tex.api import crm as crm_api
from kamra.tex.api import crs as crs_api
from kamra.tex.api import loyalty as loyalty_api
from kamra.tex.api import public
from kamra.tex.crm import loyalty
from kamra.tex.crm import service as crm
from kamra.tex.money import D, quantize, to_str
from kamra.tex.security import internals, scope
from kamra.tex.services import booking, modification
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import (
	GUEST,
	SLUG,
	guest_books,
	setup_site_and_payments,
)
from kamra.tex.tests.integration.test_critical_journey import TexTestCase
from kamra.tex.tests.integration.test_crm_segments import OTHER, agent, other_tenant
from kamra.tex.tests.integration.test_patches import migrate, never_ran, rerun_changes

SISTER = "TEX Privacy Sister Hotel"
INTERNAL = {
	"Reservation": ("tex_pricing_snapshot", "tex_cost_amount", "tex_margin_amount", "tex_fx_rate"),
	"TEX Quote": ("result_json",),
	"TEX Reservation Revision": ("snapshot_before", "snapshot_after"),
	"Guest": ("tex_stays", "tex_lifetime_value", "tex_lifetime_currency", "tex_last_stay", "tex_loyalty_points"),
}


P40 = "p40_crm_privacy_review"


@contextmanager
def request_to(path: str, method: str = "POST"):
	"""The request a generic write arrives in (REST, ``frappe.client``), in-process."""
	env = EnvironBuilder(method=method, path=path).get_environ()
	with mock.patch.object(frappe.local, "request", Request(env), create=True):
		yield


def as_user(user: str) -> None:
	frappe.set_user(user)  # nosemgrep: frappe-setuser -- the viewer decides what is shown
	scope.clear_cache()


def sister_hotel(group: str, enterprise: str) -> str:
	"""A second hotel in the test hotel's group (and enterprise)."""
	if not frappe.db.exists("Property", SISTER):
		frappe.get_doc({"doctype": "Property", "property_name": SISTER, "city": "Belek", "country": "Turkey",
		                "currency": "EUR"}).insert(ignore_permissions=True)
	frappe.db.set_value("Property", SISTER, {"tex_hotel_group": group, "tex_enterprise": enterprise})
	return SISTER


class PrivacyCase(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		crm.ensure_system_segments()
		self.other_ent = other_tenant()
		self.ent = frappe.db.get_value("Property", fx.PROPERTY, "tex_enterprise") or self.f["enterprise"]
		self.here = agent("g65-here@example.com", fx.PROPERTY)                 # crm.view / crm.edit, no view_cost
		self.there = agent("g65-there@example.com", OTHER, "Hotel Admin")      # another enterprise
		as_user("Administrator")

	def booked_guest(self, session: str, email: str, **guest) -> tuple[dict, str]:
		b = guest_books(session=session, guest={**GUEST, "email": email, **guest})
		as_user("Administrator")
		return b, frappe.db.get_value("TEX Booking", b["booking"], "booker_guest")

	def program(self, name: str, **scope_) -> str:
		return frappe.get_doc({"doctype": "TEX Loyalty Program", "program_name": name, "enabled": 1, "currency": "EUR",
		                       "point_value": "0.1", **scope_}).insert(ignore_permissions=True).name

	def points(self, program: str, guest: str, points: int, *, booking: str | None = None,
	           entry_type: str = "Adjust", reason: str = "welcome") -> str:
		return frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": program, "guest": guest,
		                       "entry_type": entry_type, "points": points, "status": "Available", "booking": booking,
		                       "reason": reason}).insert(ignore_permissions=True).name


# ─── G-65: loyalty tenancy ───────────────────────────────────────────────


class TestLoyaltyTenancy(PrivacyCase):
	def test_the_profile_shows_only_the_viewers_programs(self):
		_b, guest = self.booked_guest("g65-loy", "g65-loy@example.com")
		mine = self.program("Resort Club", property=fx.PROPERTY)
		theirs = self.program("Other Club", property=OTHER)
		self.points(mine, guest, 120)
		self.points(theirs, guest, 999)
		loyalty._sync_guest(guest)
		self.assertEqual(frappe.db.get_value("Guest", guest, "tex_loyalty_points"), 1119)   # stored: every tenant
		as_user(self.here)
		prof = crm_api.guest(guest)
		self.assertEqual([a["program"] for a in prof["loyalty"]], [mine])           # never the other tenant's
		self.assertEqual(prof["guest"]["tex_loyalty_points"], 120)                  # nor its points in a total
		row = next(r for r in crm_api.guests(q="g65-loy@example.com")["rows"] if r["name"] == guest)
		self.assertEqual(row["tex_loyalty_points"], 120)
		self.assertEqual([a["program"] for a in crm_api.loyalty_summary(guest)], [mine])

	def test_a_viewer_of_another_enterprise_learns_nothing(self):
		_b, guest = self.booked_guest("g65-out", "g65-out@example.com")
		self.points(self.program("Resort Club", property=fx.PROPERTY), guest, 50)
		as_user(self.there)
		for call in (lambda: crm_api.loyalty_summary(guest), lambda: crm_api.guest(guest)):
			with self.assertRaises(frappe.PermissionError):
				call()

	def test_a_group_programs_entries_from_another_hotel_show_points_only(self):
		b, guest = self.booked_guest("g65-grp", "g65-grp@example.com")
		sister = sister_hotel(self.f["group"], self.ent)
		club = self.program("Group Club", hotel_group=self.f["group"])
		elsewhere = frappe.get_doc({"doctype": "TEX Booking", "property": sister, "status": "Confirmed",
		                            "booker_guest": guest, "currency": "EUR"}).insert(ignore_permissions=True).name
		self.points(club, guest, 200, booking=b["booking"], entry_type="Earn", reason="stay here")
		self.points(club, guest, 300, booking=elsewhere, entry_type="Earn", reason="stay 2027-07-01→2027-07-05")
		as_user(self.here)                                # this hotel only, not the sister hotel
		self.assertNotIn(sister, scope.permitted_properties())
		[account] = crm_api.loyalty_summary(guest)
		self.assertEqual((account["program"], account["available"]), (club, 500))   # one balance for the group
		by_points = {e["points"]: e for e in account["entries"]}
		self.assertEqual((by_points[200]["booking"], by_points[200]["reason"]), (b["booking"], "stay here"))
		self.assertEqual((by_points[300]["booking"], by_points[300]["reason"], by_points[300]["other_hotel"]),
		                 (None, None, True))            # the sister hotel's booking and stay stay with it
		self.assertEqual(crm_api.guest(guest)["loyalty"], [account])

	def test_the_program_ledger_shows_another_hotels_entries_as_points_only(self):
		b, guest = self.booked_guest("g65-led", "g65-led@example.com")
		sister = sister_hotel(self.f["group"], self.ent)
		club = self.program("Group Club", hotel_group=self.f["group"])
		elsewhere = frappe.get_doc({"doctype": "TEX Booking", "property": sister, "status": "Confirmed",
		                            "booker_guest": guest, "currency": "EUR"}).insert(ignore_permissions=True).name
		self.points(club, guest, 200, booking=b["booking"], entry_type="Earn", reason="stay here")
		theirs = self.points(club, guest, 300, booking=elsewhere, entry_type="Earn", reason="stay 2027-07-01→2027-07-05")
		frappe.db.set_value("TEX Loyalty Ledger", theirs, {
			"actor": "sister-desk@example.com",
			"explanation": json.dumps({"lines": [{"rule": "MONEY", "rate": "1", "points": "300"}]})})
		# a guest this hotel cannot see (no stay here, no enterprise) who collects in the group's club
		hidden = frappe.get_doc({"doctype": "Guest", "first_name": "Hidden", "last_name": "Collector",
		                         "email": "g65-hidden@example.com"}).insert(ignore_permissions=True).name
		self.points(club, hidden, 50, booking=elsewhere, entry_type="Earn", reason="stay there")
		as_user(self.here)
		rows = {r["points"]: r for r in loyalty_api.ledger(club, limit=200)["rows"]}
		self.assertEqual((rows[200]["booking"], rows[200]["reason"], rows[200]["guest"], rows[200]["other_hotel"]),
		                 (b["booking"], "stay here", guest, False))
		self.assertEqual({k: rows[300][k] for k in ("booking", "reservation", "reason", "actor", "explanation",
		                                            "other_hotel", "guest")},
		                 {"booking": None, "reservation": None, "reason": None, "actor": None, "explanation": None,
		                  "other_hotel": True, "guest": guest})
		self.assertEqual((rows[50]["guest"], rows[50]["guest_name"], rows[50]["booking"]), (None, None, None))
		with self.assertRaises(frappe.PermissionError):              # nor by asking for that guest
			loyalty_api.ledger(club, guest=hidden)

	def test_desk_and_rest_never_show_a_guests_totals_over_every_tenant(self):
		_b, guest = self.booked_guest("g65-desk", "g65-desk@example.com")
		self.points(self.program("Other Club", property=OTHER), guest, 999)
		loyalty._sync_guest(guest)
		frappe.db.set_value("Guest", guest, {"tex_stays": 3, "tex_lifetime_value": 5000, "tex_lifetime_currency": "EUR",
		                                     "tex_last_stay": "2026-01-01"}, update_modified=False)
		totals = INTERNAL["Guest"]
		desk = fx.ensure_user("g65-desk-user@example.com", ["Front Desk"])
		fx.ensure("TEX Access Grant", {"user": desk, "property": fx.PROPERTY},
		          {"user": desk, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Reservations Agent"})
		as_user(desk)
		self.assertTrue(frappe.has_permission("Guest", "read", doc=guest))
		shown = frappe.client.get("Guest", guest)
		self.assertEqual([f for f in totals if shown.get(f) not in (None, "", 0)], [])
		listed = frappe.client.get_list("Guest", fields=["name", *totals], filters={"name": guest})
		self.assertEqual(listed, [{"name": guest}])                          # dropped from the query
		with self.assertRaises(frappe.PermissionError):                      # and never a filter
			frappe.client.get_list("Guest", fields=["name"], filters={"tex_loyalty_points": (">", 500)})
		frappe.clear_messages()
		with request_to("/api/method/frappe.client.set_value"):
			out = frappe.client.set_value("Guest", guest, "guest_notes", "Prefers a sea view")
		self.assertEqual([f for f in totals if out.get(f) not in (None, "", 0)], [])
		as_user("Administrator")                            # kept as they were
		self.assertEqual(frappe.db.get_value("Guest", guest, ["tex_loyalty_points", "tex_stays"]), (999, 3))

	def test_segment_loyalty_facts_count_the_viewers_programs_only(self):
		_b, guest = self.booked_guest("g65-seg", "g65-seg@example.com")
		self.points(self.program("Resort Club", property=fx.PROPERTY), guest, 120)
		self.points(self.program("Other Club", property=OTHER), guest, 999)
		loyalty._sync_guest(guest)
		as_user(self.here)
		seg = crm_api.save_segment({"segment_name": "Point collectors", "rules": {"match": "all", "conditions": [
			{"field": "loyalty_points", "op": "gte", "value": "500"}]}})["name"]
		self.assertNotIn(guest, {r["name"] for r in crm_api.guests(segment=seg, limit=200)["rows"]})


# ─── G-65 / G-81 review: who a booking belongs to ────────────────────────


class TestGuestIdentity(PrivacyCase):
	def test_an_email_is_the_identity_and_a_phone_only_a_fallback(self):
		phone = "+49 170 5550000"
		_b, first = self.booked_guest("g65-id-a", "g65-id-a@example.com", phone=phone)
		_b, second = self.booked_guest("g65-id-b", "g65-id-b@example.com", phone=phone)
		# another e-mail is another person, whoever shares their phone: never their stays, extras or history
		self.assertNotEqual(first, second)
		self.assertEqual(frappe.db.get_value("Guest", second, ["email", "phone"]), ("g65-id-b@example.com", phone))
		as_user(self.here)
		self.assertEqual(crm_api.guests(q="g65-id-a@example.com")["total"], 1)
		self.assertEqual(crm_api.guests(q="g65-id-b@example.com")["total"], 1)
		# no e-mail given: the phone finds the profile (staff take a phone booking)
		_b, only = self.booked_guest("g65-id-c", "g65-id-c@example.com", phone="+49 170 5550001")
		as_user(self.here)
		name, _granted, _asked = booking.resolve_guest({"first_name": "Lena", "last_name": "Kraus",
		                                                 "phone": "+49 170 5550001"}, property=fx.PROPERTY,
		                                                market="DE", language="en", staff=True)
		self.assertEqual(name, only)
		# a profile known by phone alone takes the booking that now gives an e-mail too
		as_user("Administrator")
		phoned = frappe.get_doc({"doctype": "Guest", "first_name": "Lena", "last_name": "Kraus",
		                         "phone": "+49 170 5550002", "tex_enterprise": self.ent}).insert(
			ignore_permissions=True).name
		_b, again = self.booked_guest("g65-id-d", "g65-id-d@example.com", phone="+49 170 5550002")
		self.assertEqual(again, phoned)


# ─── G-65: the guest list pages in SQL ───────────────────────────────────


class GuestRowSpy:
	"""Sizes of the guest-list selects (``FROM `tabGuest` g``) sent through ``frappe.db.sql``."""

	def __enter__(self):
		db = frappe.local.db
		real = db.sql
		self.sizes: list[int] = []

		def sql(query, *args, **kwargs):
			out = real(query, *args, **kwargs)
			q = " ".join(str(query).split())
			if "FROM `tabGuest` g" in q and "COUNT(" not in q.upper():
				self.sizes.append(len(out))
			return out

		self._patch = mock.patch.object(db, "sql", side_effect=sql)
		self._patch.start()
		return self

	def __exit__(self, *exc):
		self._patch.stop()


class TestGuestListPaging(PrivacyCase):
	def guests(self, n: int, enterprise: str, tag: str, consent: int = 0) -> set[str]:
		return {frappe.get_doc({"doctype": "Guest", "first_name": f"Page{i}", "last_name": tag,
		                        "email": f"{tag}-{i}@example.com", "tex_enterprise": enterprise,
		                        "tex_consent_email": consent if i < 2 else 0}).insert(ignore_permissions=True).name
		        for i in range(n)}

	def test_pages_are_read_in_sql_within_the_viewers_tenancy(self):
		mine = self.guests(7, self.ent, "g65page", consent=1)
		theirs = self.guests(3, self.other_ent, "g65page")
		as_user(self.here)
		full = crm_api.guests(q="g65page", limit=200)
		self.assertEqual((full["total"], {r["name"] for r in full["rows"]}), (7, mine))
		seen = []
		with GuestRowSpy() as spy:
			for start in (0, 3, 6):
				page = crm_api.guests(q="g65page", start=start, limit=3)
				self.assertEqual(page["total"], 7)                       # the whole count, whatever the page
				seen += [r["name"] for r in page["rows"]]
		self.assertEqual(seen, [r["name"] for r in full["rows"]])        # stable order: each guest once
		self.assertLessEqual(max(spy.sizes), 3, spy.sizes)               # never more rows than the page
		opt_in = frappe.db.get_value("TEX Guest Segment", {"system_key": "EMAIL_OPT_IN"})
		seg = crm_api.guests(q="g65page", segment=opt_in, start=1, limit=1)
		self.assertEqual((seg["total"], len(seg["rows"])), (2, 1))       # a segment counts over every batch
		as_user(self.there)
		other = crm_api.guests(q="g65page", limit=200)
		self.assertEqual((other["total"], {r["name"] for r in other["rows"]}), (3, theirs))


# ─── G-65: extras and cancellations in the profile ───────────────────────


class TestProfileCompleteness(PrivacyCase):
	def test_the_profile_shows_extras_and_cancellations_at_the_viewers_hotels(self):
		b1, guest = self.booked_guest("g65-x1", "g65-x@example.com")
		b2, _g = self.booked_guest("g65-x2", "g65-x@example.com")
		b3, _g = self.booked_guest("g65-x3", "g65-x@example.com")
		r1, r2, r3 = (b["rooms"][0]["reservation"] for b in (b1, b2, b3))
		booking.cancel_reservation(r2, reason="changed plans", waive_penalty=True)
		frappe.db.set_value("Reservation", r2, "cancellation_fee", 55)
		# another tenant's cancelled stay of the same guest counts there, never here
		frappe.db.set_value("Reservation", r3, {"property": OTHER, "status": "Cancelled", "cancellation_fee": 99})
		trf = next(e for e in json.loads(frappe.db.get_value("Reservation", r1, "tex_pricing_snapshot"))["extras"]
		           if e["code"] == "TRF")
		as_user(self.here)
		prof = crm_api.guest(guest)
		self.assertEqual(prof["cancellations"], {"count": 1, "no_shows": 0,
		                                         "fees": [{"currency": "EUR", "amount": "55.00"}],
		                                         "last_cancelled_on": prof["cancellations"]["last_cancelled_on"]})
		self.assertTrue(prof["cancellations"]["last_cancelled_on"])
		bought = [(e["reservation"], e["code"], D(e["quantity"]), e["amount"], e["currency"]) for e in prof["extras"]]
		self.assertEqual(bought, [(r1, "TRF", D(1), to_str(quantize(D(trf["amount"]), "EUR")), "EUR")])
		self.assertEqual([(s["code"], D(s["quantity"]), s["amount"], s["stays"]) for s in prof["extras_summary"]],
		                 [("TRF", D(1), to_str(quantize(D(trf["amount"]), "EUR")), 1)])


# ─── G-81: abandoned bookings ────────────────────────────────────────────


def funnel(session: str, event: str | None = None) -> list:
	filters = {"session_id": session, **({"event": event} if event else {})}
	return frappe.get_all("TEX Funnel Event", filters=filters, fields=["event", "email_hash", "consent_marketing",
	                                                                    "payload"], order_by="occurred_at asc")


class TestAbandonedPrivacy(PrivacyCase):
	def test_an_email_hash_is_kept_only_with_marketing_consent(self):
		self.booked_guest("g81-no", "g81-no@example.com")
		[ev] = funnel("g81-no", "guest_details")
		self.assertEqual((ev.email_hash, ev.consent_marketing), (None, 0))
		self.booked_guest("g81-yes", "G81-Yes@example.com ", consent_email=1)
		[ev] = funnel("g81-yes", "guest_details")
		self.assertEqual((ev.email_hash, ev.consent_marketing),
		                 (hashlib.sha256(b"g81-yes@example.com").hexdigest(), 1))
		self.assertNotIn("@", "".join(e.payload or "" for e in funnel("g81-yes")))

	def test_browser_events_never_keep_contact_data(self):
		as_user("Guest")
		public.track(site=SLUG, session_id="g81-web", event="abandoned",
		             payload=json.dumps({"quotes": ["q1"], "email": "someone@example.com", "phone": "+49 30 1",
		                                 "first_name": "Some", "last_name": "One"}))
		as_user("Administrator")
		[ev] = funnel("g81-web")
		self.assertEqual(ev.email_hash, None)
		self.assertEqual(json.loads(ev.payload), {"quotes": ["q1"]})

	def test_a_browser_event_keeps_only_its_allow_listed_fields(self):
		as_user("Guest")
		public.track(site=SLUG, session_id="g81-allow", event="room_view", payload=json.dumps({
			"hotel": fx.PROPERTY, "room_type": "STD", "board": "AI", "rate_plan": "FLEX",
			"guest": {"email": "someone@example.com"}, "e_mail": "someone@example.com", "tel": "+49 30 2",
			"note": "call me on +49 30 2", "hotel_extra": ["x"]}))
		public.track(site=SLUG, session_id="g81-allow", event="abandoned", payload=json.dumps({
			"quotes": ["q1", {"email": "someone@example.com"}, "q" * 200, 5], "hotel": {"email": "a@b.c"},
			"contact": ["someone@example.com"]}))
		public.track(site=SLUG, session_id="g81-allow", event="room_view",
		             payload=json.dumps({"hotel": "h" * 500, "room_type": ["STD"]}))
		as_user("Administrator")
		payloads = [json.loads(e.payload) for e in funnel("g81-allow")]
		self.assertEqual(payloads, [{"hotel": fx.PROPERTY, "room_type": "STD", "board": "AI", "rate_plan": "FLEX"},
		                            {"quotes": ["q1"]}, {}])
		self.assertEqual({e.email_hash for e in funnel("g81-allow")}, {None})

	def test_a_consent_sent_as_text_means_what_it_says(self):
		for session, value, meant in (("g81-txt-0", "0", 0), ("g81-txt-f", "false", 0), ("g81-txt-no", "no", 0),
		                              ("g81-txt-t", "TRUE", 1), ("g81-txt-1", 1, 1)):
			_b, guest = self.booked_guest(session, f"{session}@example.com", consent_email=value)
			self.assertEqual(frappe.db.get_value("Guest", guest, "tex_consent_email"), meant, f"{value!r}")
			[ev] = funnel(session, "guest_details")
			self.assertEqual((ev.consent_marketing, bool(ev.email_hash)), (meant, bool(meant)), f"{value!r}")

	def test_p37_purges_hashes_kept_without_consent(self):
		from kamra.patches.tex import p37_crm_privacy

		rows = {}
		for session, consent in (("g81-old-a", 0), ("g81-old-b", 1)):
			rows[session] = frappe.get_doc({
				"doctype": "TEX Funnel Event", "event": "guest_details", "occurred_at": now_datetime(), "site": SLUG,
				"property": fx.PROPERTY, "session_id": session, "consent_marketing": consent,
				"payload": "{}"}).insert(ignore_permissions=True).name
			frappe.db.set_value("TEX Funnel Event", rows[session], "email_hash", "ab" * 32)    # as stored before
		p37_crm_privacy.execute()
		self.assertEqual(frappe.db.get_value("TEX Funnel Event", rows["g81-old-a"], "email_hash"), None)
		self.assertEqual(frappe.db.get_value("TEX Funnel Event", rows["g81-old-b"], "email_hash"), "ab" * 32)

	def test_consented_contact_then_recovery_by_a_later_payment(self):
		b, guest = self.booked_guest("g81-rec", "g81-rec@example.com", consent_email=1, phone="+49 30 1234")
		self.assertTrue(b["payment"])                               # left at the gateway, unpaid
		crm.detect_abandoned(now=add_to_date(now_datetime(), minutes=60))
		row = frappe.db.get_value("TEX Abandoned Booking", {"session_id": "g81-rec"},
		                          ["name", "guest", "email", "phone", "consent_marketing", "stage_reached", "status"],
		                          as_dict=True)
		self.assertEqual((row.guest, row.email, row.phone, row.consent_marketing, row.stage_reached, row.status),
		                 (guest, "g81-rec@example.com", "+49 30 1234", 1, "payment_started", "Open"))
		as_user(self.here)                                          # the hotel sees whom to contact
		listed = next(r for r in crm_api.abandoned(fx.PROPERTY) if r["name"] == row.name)
		self.assertEqual((listed["email"], listed["phone"]), ("g81-rec@example.com", "+49 30 1234"))
		crm_api.set_abandoned_status(row.name, "Contacted", note="called about the payment")
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "abandoned.status",
		                                                     "reference_name": row.name}))
		# the guest pays later (the link in the reminder): the abandoned booking is recovered
		as_user("Guest")
		p = b["payment"]
		public.mock_pay(transaction=p["transaction"], outcome="success", sig=p["fields"]["success_sig"])
		as_user("Administrator")
		self.assertEqual(frappe.db.get_value("TEX Booking", b["booking"], "status"), "Confirmed")
		crm.detect_abandoned(now=add_to_date(now_datetime(), minutes=120))
		self.assertEqual(frappe.db.get_value("TEX Abandoned Booking", row.name, ["status", "recovered_booking"]),
		                 ("Recovered", b["booking"]))

	def test_contact_data_is_shown_only_while_the_consent_holds(self):
		b, guest = self.booked_guest("g81-wd", "g81-wd@example.com", consent_email=1, phone="+49 30 99")
		crm.detect_abandoned(now=add_to_date(now_datetime(), minutes=60))
		name = frappe.db.get_value("TEX Abandoned Booking", {"session_id": "g81-wd"})
		# the case as a hotel sees it before the withdrawal, and a withdrawal the API cannot see: the
		# stored case still names the guest, the listing never does once the consent is gone
		frappe.db.set_value("Guest", guest, "tex_consent_email", 0, update_modified=False)
		as_user(self.here)
		listed = next(r for r in crm_api.abandoned(fx.PROPERTY) if r["name"] == name)
		self.assertEqual((listed["guest"], listed["email"], listed["phone"], listed["consent_marketing"]),
		                 (None, None, None, 0))
		self.assertTrue(b["payment"])

	def test_a_withdrawal_makes_the_cases_and_the_funnel_anonymous(self):
		sessions = {}
		for session in ("g81-wd-crm", "g81-wd-desk"):
			_b, sessions[session] = self.booked_guest(session, f"{session}@example.com", consent_email=1,
			                                          phone="+49 30 55")
		crm.detect_abandoned(now=add_to_date(now_datetime(), minutes=60))
		for session in sessions:
			self.assertTrue(frappe.db.get_value("TEX Abandoned Booking", {"session_id": session}, "email"))
			self.assertTrue([e for e in funnel(session) if e.email_hash])
		as_user(self.here)                                          # withdrawn in the CRM
		crm_api.update_guest(sessions["g81-wd-crm"], {"tex_consent_email": 0}, consent_source="guest asked")
		as_user("Administrator")                                    # and in the Desk form
		g = frappe.get_doc("Guest", sessions["g81-wd-desk"])
		g.tex_consent_email = 0
		g.save()
		for session in sessions:
			case = frappe.db.get_value("TEX Abandoned Booking", {"session_id": session},
			                           ["guest", "email", "phone", "consent_marketing"])
			self.assertEqual(case, (None, None, None, 0), session)
			self.assertEqual({e.email_hash for e in funnel(session)}, {None}, session)
		self.assertTrue(frappe.db.get_value("Guest", sessions["g81-wd-crm"], "email"))    # the profile stays

	def test_case_contacts_and_funnel_hashes_are_withheld_from_desk_and_rest(self):
		self.booked_guest("g81-desk", "g81-desk@example.com", consent_email=1, phone="+49 30 66")
		crm.detect_abandoned(now=add_to_date(now_datetime(), minutes=60))
		case = frappe.db.get_value("TEX Abandoned Booking", {"session_id": "g81-desk"})
		# a Desk user of this hotel who may not even view the CRM
		viewer = fx.ensure_user("g81-viewer@example.com", ["Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": viewer, "property": fx.PROPERTY},
		          {"user": viewer, "scope_level": "Hotel", "property": fx.PROPERTY, "permission_profile": "Viewer"})
		as_user(viewer)
		self.assertFalse(scope.has_capability("crm.view", fx.PROPERTY))
		self.assertTrue(frappe.has_permission("TEX Abandoned Booking", "read", doc=case))
		shown = frappe.client.get("TEX Abandoned Booking", case)
		self.assertEqual([f for f in ("guest", "email", "phone") if shown.get(f)], [])
		listed = frappe.client.get_list("TEX Abandoned Booking", fields=["name", "guest", "email", "phone"],
		                                filters={"name": case})
		self.assertEqual(listed, [{"name": case}])
		with self.assertRaises(frappe.PermissionError):
			frappe.client.get_list("TEX Abandoned Booking", fields=["name"], filters={"email": ("like", "%@%")})
		frappe.clear_messages()
		events = frappe.client.get_list("TEX Funnel Event", fields=["name", "email_hash"],
		                                filters={"session_id": "g81-desk"}, limit_page_length=50)
		self.assertTrue(events)
		self.assertEqual([e for e in events if e.get("email_hash")], [])

	def test_p40_makes_cases_anonymous_where_the_consent_no_longer_holds(self):
		stale = frappe.get_doc({"doctype": "Guest", "first_name": "Stale", "last_name": "Consent",
		                        "email": "g81-stale@example.com", "tex_consent_email": 0}).insert(
			ignore_permissions=True).name
		agreed = frappe.get_doc({"doctype": "Guest", "first_name": "Still", "last_name": "Agrees",
		                         "email": "g81-agrees@example.com", "tex_consent_email": 1}).insert(
			ignore_permissions=True).name
		cases, hashes = {}, {}
		for guest, email in ((stale, "g81-stale@example.com"), (agreed, "g81-agrees@example.com")):
			cases[guest] = frappe.get_doc({
				"doctype": "TEX Abandoned Booking", "property": fx.PROPERTY, "session_id": f"p40-{guest}",
				"stage_reached": "payment_started", "status": "Open", "guest": guest, "email": email,
				"phone": "+49 30 1", "consent_marketing": 1, "last_event_at": now_datetime()}).insert(
				ignore_permissions=True).name
			hashes[guest] = frappe.get_doc({
				"doctype": "TEX Funnel Event", "event": "guest_details", "occurred_at": now_datetime(), "site": SLUG,
				"property": fx.PROPERTY, "session_id": f"p40-{guest}", "consent_marketing": 1,
				"payload": "{}"}).insert(ignore_permissions=True).name
			frappe.db.set_value("TEX Funnel Event", hashes[guest], "email_hash",
			                    hashlib.sha256(email.encode()).hexdigest())
		never_ran(P40)
		migrate(P40)
		self.assertEqual(frappe.db.get_value("TEX Abandoned Booking", cases[stale],
		                                     ["guest", "email", "phone", "consent_marketing"]), (None, None, None, 0))
		self.assertEqual(frappe.db.get_value("TEX Funnel Event", hashes[stale], "email_hash"), None)
		self.assertEqual(frappe.db.get_value("TEX Abandoned Booking", cases[agreed], ["guest", "consent_marketing"]),
		                 (agreed, 1))
		self.assertTrue(frappe.db.get_value("TEX Funnel Event", hashes[agreed], "email_hash"))
		self.assertEqual(rerun_changes(P40), {})

	def test_recovery_by_a_later_booking_in_the_same_session(self):
		detected = {}

		def leave_then_come_back():
			as_user("Administrator")                                   # the scheduler runs while they are away
			frappe.db.sql("UPDATE `tabTEX Funnel Event` SET occurred_at=%s WHERE session_id='g81-back'",
			              add_to_date(now_datetime(), hours=-2))
			crm.detect_abandoned()
			detected.update(frappe.db.get_value("TEX Abandoned Booking", {"session_id": "g81-back"},
			                                    ["name", "status", "email", "stage_reached"], as_dict=True))

		b = guest_books(session="g81-back", method="Pay at Hotel", before_book=leave_then_come_back)
		as_user("Administrator")
		self.assertEqual((detected["status"], detected["email"], detected["stage_reached"]), ("Open", None, "quote"))
		crm.detect_abandoned(now=add_to_date(now_datetime(), minutes=60))
		self.assertEqual(frappe.db.get_value("TEX Abandoned Booking", detected["name"],
		                                     ["status", "recovered_booking"]), ("Recovered", b["booking"]))


# ─── G-95: pricing internals outside the TEX API ─────────────────────────


class TestPricingInternalsOutsideTex(PrivacyCase):
	def setUp(self):
		super().setUp()
		# a Desk user of this hotel (reads reservations, quotes and revisions) without price.view_cost
		self.clerk = fx.ensure_user("g95-clerk@example.com", ["Front Desk", "Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": self.clerk, "property": fx.PROPERTY},
		          {"user": self.clerk, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Reservations Agent"})
		self.revenue = agent("g95-revenue@example.com", fx.PROPERTY, "Revenue Manager")
		self.platform = fx.ensure_user("g95-platform@example.com", ["System Manager"])
		as_user("Administrator")
		b = guest_books(session="g95")
		as_user("Administrator")
		self.res = b["rooms"][0]["reservation"]
		self.quote = frappe.db.get_value("Reservation", self.res, "tex_quote")
		self.rev = frappe.get_all("TEX Reservation Revision", filters={"reservation": self.res}, pluck="name")[0]
		stored = frappe.db.get_value("Reservation", self.res, INTERNAL["Reservation"], as_dict=True)
		self.assertTrue(all(stored.values()), stored)                   # something to hide (no zero)
		self.assertTrue(frappe.db.get_value("TEX Quote", self.quote, "result_json"))
		self.assertTrue(frappe.db.get_value("TEX Reservation Revision", self.rev, "snapshot_after"))

	def leaked(self, doctype: str, out) -> list[str]:
		"""Pricing-internal fields that carry a value in what a read returned (Frappe hands a
		field it withholds back empty: None, or 0 for a number; the stored values are not)."""
		rows = out if isinstance(out, list) else [out]
		found = []
		for r in rows:
			d = r.as_dict() if isinstance(r, BaseDocument) else dict(r)
			found += [f for f in INTERNAL[doctype] if d.get(f) not in (None, "", 0)]
		return found

	def refused_or(self, call):
		try:
			return call()
		except frappe.PermissionError:
			frappe.clear_messages()
			return []

	def desk_form(self, doctype: str, name: str):
		frappe.local.response = frappe._dict({"docs": []})
		frappe.desk.form.load.getdoc(doctype, name)
		return frappe.response.docs[-1], frappe.response.get("docinfo") or {}

	def test_desk_and_rest_reads_never_carry_pricing_internals(self):
		as_user(self.clerk)
		self.assertTrue(frappe.has_permission("Reservation", "read", doc=self.res))
		self.assertFalse(scope.has_capability("price.view_cost", fx.PROPERTY))
		res_fields = ["name", *INTERNAL["Reservation"]]
		reads = {
			"frappe.client.get": lambda: frappe.client.get("Reservation", self.res),
			"GET /api/resource (v1)": lambda: frappe.api.v1.read_doc("Reservation", self.res),
			"GET /api/v2/document": lambda: frappe.api.v2.read_doc("Reservation", self.res),
			"Desk form": lambda: self.desk_form("Reservation", self.res)[0],
			"get_list(fields)": lambda: frappe.client.get_list("Reservation", fields=res_fields,
			                                                   filters={"name": self.res}),
			"get_list(*)": lambda: frappe.client.get_list("Reservation", fields=["*"], filters={"name": self.res}),
			"get_value": lambda: frappe.client.get_value("Reservation", json.dumps(res_fields), self.res),
			"GET /api/resource list": lambda: self.v1_list("Reservation", res_fields),
		}
		for label, call in reads.items():
			self.assertEqual(self.leaked("Reservation", self.refused_or(call)), [], label)
		# no oracle either: filtering, sorting or summing on them is refused
		for label, call in {
			"filter": lambda: frappe.client.get_list("Reservation", fields=["name"],
			                                         filters={"tex_cost_amount": (">", 0)}),
			"order": lambda: frappe.client.get_list("Reservation", fields=["name"], order_by="tex_margin_amount desc"),
			"sum": lambda: frappe.client.get_list("Reservation", fields=[{"SUM": "tex_cost_amount", "as": "total"}],
			                                      filters={"name": self.res}),
		}.items():
			with self.assertRaises(frappe.PermissionError, msg=label):
				call()
			frappe.clear_messages()
		# the legacy string form of an aggregate on them is dropped from the query (only the name comes back)
		rows = self.refused_or(lambda: frappe.client.get_list(
			"Reservation", fields=["sum(tex_cost_amount) as total", "max(tex_margin_amount) as m"],
			filters={"name": self.res}))
		self.assertTrue(all(set(r) <= {"name"} for r in rows), rows)
		for doctype, name in (("TEX Quote", self.quote), ("TEX Reservation Revision", self.rev)):
			fields = ["name", *INTERNAL[doctype]]
			for label, call in {
				"frappe.client.get": lambda: frappe.client.get(doctype, name),
				"GET /api/resource (v1)": lambda: frappe.api.v1.read_doc(doctype, name),
				"get_list(fields)": lambda: frappe.client.get_list(doctype, fields=fields, filters={"name": name}),
				"get_list(*)": lambda: frappe.client.get_list(doctype, fields=["*"], filters={"name": name}),
			}.items():
				self.assertEqual(self.leaked(doctype, self.refused_or(call)), [], f"{doctype} {label}")

	def v1_list(self, doctype: str, fields: list[str]):
		frappe.local.form_dict = frappe._dict({"fields": json.dumps(fields), "filters": {"name": self.res}})
		try:
			return frappe.api.v1.document_list(doctype)
		finally:
			frappe.local.form_dict = frappe._dict()

	def test_a_write_through_rest_returns_no_pricing_internals(self):
		before = frappe.db.get_value("Reservation", self.res, INTERNAL["Reservation"], as_dict=True)
		as_user(self.clerk)
		with request_to("/api/method/frappe.client.set_value"):
			out = frappe.client.set_value("Reservation", self.res, "special_requests", "Late arrival")
		self.assertEqual(self.leaked("Reservation", out), [])
		frappe.local.form_dict = frappe._dict({"data": json.dumps({"special_requests": "Quiet room"})})
		try:
			with request_to(f"/api/resource/Reservation/{self.res}", "PUT"):
				doc = frappe.api.v1.update_doc("Reservation", self.res)        # PUT /api/resource
		finally:
			frappe.local.form_dict = frappe._dict()
		self.assertEqual(self.leaked("Reservation", doc), [])
		self.assertEqual(json.loads(frappe.as_json(doc)).get("tex_pricing_snapshot"), None)   # as the response is sent
		as_user("Administrator")
		self.assertEqual(frappe.db.get_value("Reservation", self.res, "special_requests"), "Quiet room")
		self.assertEqual(frappe.db.get_value("Reservation", self.res, INTERNAL["Reservation"], as_dict=True), before)

	def test_only_a_generic_write_response_leaves_them_out(self):
		as_user(self.clerk)
		doc = frappe.get_doc("Reservation", self.res)
		doc.db_set("special_requests", "Needs a cot")              # code's own write: its object keeps them
		self.assertEqual(self.leaked("Reservation", doc), list(INTERNAL["Reservation"]))
		doc = frappe.get_doc("Reservation", self.res)
		doc.special_requests = "Needs two cots"
		doc.save()                                                 # a permission-checked save by code
		self.assertEqual(self.leaked("Reservation", doc), list(INTERNAL["Reservation"]))
		self.assertEqual(self.leaked("Reservation", frappe.copy_doc(doc)), list(INTERNAL["Reservation"]))
		with request_to("/api/method/frappe.client.save"):         # what REST sends back
			out = frappe.client.save(frappe.get_doc("Reservation", self.res).as_dict())
		self.assertEqual(self.leaked("Reservation", out), [])

	def test_the_withheld_values_stay_on_record_for_platform_admins(self):
		before = frappe.get_doc("Reservation", self.res)
		p = modification.propose(self.res, {"check_out": str(fx.d(6, 14))})
		modification.apply(p["proposal_token"], reason="one more night")
		after = frappe.get_doc("Reservation", self.res)
		version = frappe.new_doc("Version")
		self.assertTrue(version.update_version_info(before, after))
		version.insert(ignore_permissions=True)
		kept = {"action": "version.withheld", "reference_doctype": "Reservation", "reference_name": self.res}
		as_user(self.platform)
		[row] = frappe.get_list("TEX Audit Event", filters=kept, fields=["new_value", "property"])
		self.assertEqual(row.property, None)                       # platform level: no hotel sees it
		held = {r[0]: r[1:] for r in json.loads(row.new_value)["changed"]}
		self.assertEqual(held["tex_pricing_snapshot"][1], after.tex_pricing_snapshot)
		self.assertEqual(json.loads(row.new_value)["version"], version.name)
		as_user(self.clerk)
		self.assertEqual(frappe.get_list("TEX Audit Event", filters=kept, pluck="name"), [])
		trail = admin_api.audit_log(reference_doctype="Reservation", reference_name=self.res, limit=500)
		self.assertTrue(trail)                                     # the stay's own trail, without them
		self.assertNotIn("version.withheld", {r["action"] for r in trail})

	def test_the_change_history_never_shows_pricing_internals(self):
		before = frappe.get_doc("Reservation", self.res)
		p = modification.propose(self.res, {"check_out": str(fx.d(6, 14))})
		modification.apply(p["proposal_token"], reason="one more night")
		after = frappe.get_doc("Reservation", self.res)
		# the change history row Frappe writes on that save (``Document.save_version``; tests skip it)
		version = frappe.new_doc("Version")
		self.assertTrue(version.update_version_info(before, after))
		version.insert(ignore_permissions=True)
		new_snapshot = after.tex_pricing_snapshot
		for user in (self.clerk, self.platform):                         # the history is for everyone
			as_user(user)
			_doc, info = self.desk_form("Reservation", self.res)
			versions = [json.loads(v["data"]) for v in info.get("versions") or []]
			changed = [row for v in versions for row in v.get("changed") or []]
			internal = [row for row in changed if row[0] in INTERNAL["Reservation"]]
			self.assertTrue(internal, changed)                           # the change is recorded ...
			self.assertTrue(all(v in (None, "", "*****") for row in internal for v in row[1:3]), internal)   # masked
			self.assertNotIn(new_snapshot[:60], json.dumps(versions))

	def test_the_tex_api_serves_them_by_capability(self):
		as_user(self.revenue)
		pricing = crs_api.reservation(self.res)["pricing"]
		self.assertIn("explanation", pricing)
		self.assertIn("cost", pricing["totals"])
		as_user(self.clerk)
		pricing = crs_api.reservation(self.res)["pricing"]
		self.assertNotIn("explanation", pricing)
		self.assertNotIn("cost", pricing["totals"])
		as_user(self.platform)                                   # platform administrators keep Desk / REST
		self.assertTrue(frappe.client.get("Reservation", self.res).get("tex_pricing_snapshot"))

	def test_p37_masks_pricing_internals_in_existing_change_history(self):
		from kamra.patches.tex import p37_crm_privacy

		data = {"changed": [["tex_cost_amount", "€ 300.00", "€ 400.00"], ["special_requests", "", "Sea view"],
		                    ["tex_pricing_snapshot", '{"totals": {"cost": "300"}}', '{"totals": {"cost": "400"}}']]}
		v = frappe.get_doc({"doctype": "Version", "ref_doctype": "Reservation", "docname": self.res,
		                    "data": json.dumps(data)})
		v.name = frappe.generate_hash(length=10)
		v.owner = v.modified_by = "Administrator"
		v.creation = v.modified = now_datetime()
		v.db_insert()                                            # as rows written before this change are
		p37_crm_privacy.execute()
		kept = json.loads(frappe.db.get_value("Version", v.name, "data"))["changed"]
		self.assertEqual(kept, [["tex_cost_amount", "*****", "*****"], ["special_requests", "", "Sea view"],
		                        ["tex_pricing_snapshot", "*****", "*****"]])
		# the values are kept for platform administrators (review follow-up)
		[held] = frappe.get_all("TEX Audit Event", filters={"action": "version.withheld", "reference_name": self.res},
		                        fields=["new_value", "property"])
		self.assertEqual(held.property, None)
		self.assertEqual(json.loads(held.new_value), {"version": v.name, "changed": [
			["tex_cost_amount", "€ 300.00", "€ 400.00"],
			["tex_pricing_snapshot", '{"totals": {"cost": "300"}}', '{"totals": {"cost": "400"}}']]})


# ─── withheld fields on customised role permissions (review follow-up) ───

WITHHELD = ("Reservation", "Guest", "TEX Quote", "TEX Reservation Revision", "TEX Abandoned Booking",
            "TEX Funnel Event")


class TestWithheldFieldPermissions(PrivacyCase):
	def setUp(self):
		super().setUp()
		self.platform = fx.ensure_user("g95-platform@example.com", ["System Manager"])

	def tearDown(self):
		super().tearDown()                                         # the rollback
		for dt in WITHHELD:                                        # nothing customised stays cached
			frappe.clear_cache(doctype=dt)

	def custom(self, doctype: str, role: str, permlevel: int = 0, **flags) -> None:
		frappe.get_doc({"doctype": "Custom DocPerm", "parent": doctype, "parenttype": "DocType",
		                "parentfield": "permissions", "role": role, "permlevel": permlevel,
		                "read": 1, **flags}).insert(ignore_permissions=True)
		frappe.clear_cache(doctype=doctype)

	def test_p40_gives_platform_admins_the_withheld_fields_on_customised_permissions(self):
		# a site whose role permissions were customised (Kamra's bootstrap scripts): Frappe then reads
		# only the Custom DocPerm rows, so the JSON's permlevel-1 row for System Manager is gone
		self.custom("Guest", "System Manager", write=1, create=1, delete=1)
		self.custom("Guest", "Front Desk", write=1)
		self.custom("Reservation", "System Manager", write=1)
		self.custom("Reservation", "Front Desk", permlevel=1)       # a business role at permlevel 1
		self.assertFalse(internals.may_read("Guest", self.platform))
		never_ran(P40)
		seen = migrate(P40)
		for dt in ("Guest", "Reservation"):
			self.assertTrue(frappe.db.exists("Custom DocPerm", {"parent": dt, "role": "System Manager",
			                                                    "permlevel": 1, "read": 1}), dt)
			frappe.clear_cache(doctype=dt)
			self.assertTrue(internals.may_read(dt, self.platform), dt)
		self.assertFalse(internals.may_read("Guest", fx.ensure_user("g95-desk@example.com", ["Front Desk"])))
		self.assertEqual(frappe.get_all("TEX Audit Event", filters={"action": "permission.withheld_fields_exposed",
		                                                           "reference_name": "Reservation"},
		                                fields=["property"]), [{"property": None}])
		self.assertIn("Front Desk", " ".join(str(c) for c in seen["print"].call_args_list))
		self.assertEqual(rerun_changes(P40), {})
		self.assertFalse(frappe.db.exists("Custom DocPerm", {"parent": "TEX Quote"}))   # an untouched DocType stays so

	def test_the_permission_scripts_keep_platform_admins_reading_them(self):
		from kamra.scripts import fix_perms_fields

		self.assertFalse(frappe.db.exists("Custom DocPerm", {"parent": "Guest"}))
		fix_perms_fields._grant("Guest", "Front Desk", 1, 1, 1)    # as seed_rbac_v2 / bootstrap_v* do
		frappe.clear_cache(doctype="Guest")
		self.assertTrue(frappe.db.exists("Custom DocPerm", {"parent": "Guest", "role": "System Manager",
		                                                    "permlevel": 1, "read": 1}))
		fix_perms_fields._grant("Guest", "System Manager", 1, 1, 1, delete=1)   # the level-0 row, not level 1
		self.assertEqual(frappe.db.get_value("Custom DocPerm", {"parent": "Guest", "role": "System Manager",
		                                                        "permlevel": 0}, "delete"), 1)
		self.assertEqual(frappe.db.get_value("Custom DocPerm", {"parent": "Guest", "role": "System Manager",
		                                                        "permlevel": 1}, "delete"), 0)
		frappe.clear_cache(doctype="Guest")
		self.assertTrue(internals.may_read("Guest", self.platform))
