"""G-41 call-centre channel binding (R-25, ADR-050).

A staff user prices and books only on the sales channels they are entitled to at that hotel:
the channels of their permission profiles there (the call centre when a profile names none),
or every channel with ``price.any_channel``. Every CRS endpoint that prices or books checks
the channel against that entitlement, never trusting the request; a reservation is modified
on its own channel, which nobody switches through a modification. The Booking Engine and the
call centre sell the same stay at different prices when a markup tells them apart.
"""

import frappe

from kamra.tex.api import crs, public, ui_crs
from kamra.tex.commercial import revisions
from kamra.tex.money import D
from kamra.tex.security import scope
from kamra.tex.services import booking as booking_svc
from kamra.tex.services import modification
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import GUEST, SLUG, setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase

OTHER = "TEX Channel Other Hotel"
SELLER_CAPS = ("price.view", "reservation.view", "reservation.create", "reservation.modify", "reservation.cancel",
               "payment.view", "payment.link", "crm.view", "crm.edit")
ANY = "G41 Any Channel Seller"
B2B_DESK = "G41 B2B Desk"
CC_DESK = "G41 Call Centre Desk"
DESK_ADMIN = "G41 Desk Admin"


def as_user(user: str) -> None:
	frappe.set_user(user)  # nosemgrep: frappe-setuser -- the test acts as each staff user in turn
	scope.clear_cache()


def profile(name: str, caps, channels=()) -> str:
	if not frappe.db.exists("TEX Permission Profile", name):
		frappe.get_doc({"doctype": "TEX Permission Profile", "profile_name": name,
		                "capabilities": [{"capability": c} for c in caps],
		                "sales_channels": [{"sales_channel": c} for c in channels]}).insert(ignore_permissions=True)
	return name


def grant(user: str, prop: str, prof: str) -> None:
	fx.ensure("TEX Access Grant", {"user": user, "property": prop},
	          {"user": user, "scope_level": "Hotel", "property": prop, "permission_profile": prof})


def channel_markup(channel: str, value) -> str:
	doc = frappe.get_doc({"doctype": "TEX Markup Rule", "label": f"{channel} markup", "property": fx.PROPERTY,
	                      "market": "DE", "sales_channel": channel, "op": "ADJUST_PERCENT",
	                      "value": value}).insert(ignore_permissions=True)
	revisions.activate("TEX Markup Rule", doc.name)
	return doc.name


def std_offer(res: dict, prop: str = fx.PROPERTY) -> dict:
	"""The STD / AI / Flexible offer of ``prop`` in a search result."""
	rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
	rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
	p = next(x for x in res["properties"] if x["property"] == prop)
	return next(o for o in p["offers"] if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == rp)


STAY = {"check_in": str(fx.d(6, 10)), "check_out": str(fx.d(6, 13)), "rooms": [{"adults": 2, "children": []}],
        "market": "DE"}


def search(channel: str, properties=(fx.PROPERTY,), via=crs) -> dict:
	return via.search(**STAY, channel=channel, properties=list(properties) if properties else None)


class ChannelCase(TexTestCase):
	def setUp(self):
		super().setUp()
		try:
			setup_site_and_payments(self.f)
			# the Booking Engine and the call centre price the same stay differently (R-25)
			self.web_markup = channel_markup("DIRECT_WEB", 5)
			self.cc_markup = channel_markup("CALL_CENTER", 12)
			if not frappe.db.exists("Property", OTHER):
				frappe.get_doc({"doctype": "Property", "property_name": OTHER, "city": "Kemer", "country": "Turkey",
				                "currency": "EUR", "tex_hotel_group": self.f["group"]}).insert(ignore_permissions=True)
			self.agent = fx.ensure_user("g41-agent@example.com", ["Call Center Agent"])
			grant(self.agent, fx.PROPERTY, "Reservations Agent")
			scope.clear_cache()
		except Exception:
			self.tearDown()                   # a failed set-up leaves nothing behind for the next test
			raise

	@property
	def seller(self) -> str:
		"""Every channel (``price.any_channel``) at the test hotel."""
		as_user("Administrator")               # grants are made by an administrator
		profile(ANY, (*SELLER_CAPS, "price.any_channel"))
		user = fx.ensure_user("g41-seller@example.com", ["Call Center Agent"])
		grant(user, fx.PROPERTY, ANY)
		return user

	@property
	def b2b(self) -> str:
		"""The B2B channel only, from the profile's channel list."""
		as_user("Administrator")               # grants are made by an administrator
		profile(B2B_DESK, ("price.view", "reservation.view", "reservation.create"), ("B2B",))
		user = fx.ensure_user("g41-b2b@example.com", ["Call Center Agent"])
		grant(user, fx.PROPERTY, B2B_DESK)
		return user

	@property
	def split(self) -> str:
		"""Every channel at the other hotel, only the call centre at the test hotel."""
		as_user("Administrator")               # grants are made by an administrator
		profile(ANY, (*SELLER_CAPS, "price.any_channel"))
		user = fx.ensure_user("g41-split@example.com", ["Call Center Agent"])
		grant(user, fx.PROPERTY, "Reservations Agent")
		grant(user, OTHER, ANY)
		return user

	def web_quote(self) -> str:
		"""A DIRECT_WEB quote made by someone entitled to it (a platform administrator)."""
		as_user("Administrator")
		q = crs.quote(offer_key=std_offer(search("DIRECT_WEB"))["rooms"][0]["offer_key"])
		self.assertTrue(q["ok"], q)
		return q["quote_id"]


class TestAgentIsBoundToTheCallCentre(ChannelCase):
	def test_entitlement_defaults_to_the_call_centre(self):
		as_user(self.agent)
		self.assertEqual(scope.sales_channels(fx.PROPERTY), frozenset({"CALL_CENTER"}))
		self.assertTrue(scope.may_sell_on("CALL_CENTER", fx.PROPERTY))
		self.assertFalse(scope.may_sell_on("DIRECT_WEB", fx.PROPERTY))
		self.assertEqual(scope.sales_channels(OTHER), frozenset())            # no access there at all
		as_user(self.b2b)
		self.assertEqual(scope.sales_channels(fx.PROPERTY), frozenset({"B2B"}))
		as_user(self.seller)
		self.assertTrue({"DIRECT_WEB", "CALL_CENTER", "OTA", "API", "B2B", "META"} <= scope.sales_channels(fx.PROPERTY))
		as_user("Administrator")
		self.assertIn("OTA", scope.sales_channels(fx.PROPERTY))

	def test_search_on_another_channel_is_refused_on_every_crs_endpoint(self):
		as_user(self.agent)
		for channel in ("DIRECT_WEB", "OTA", "API", "B2B", "META"):
			for via in (crs, ui_crs):
				with self.assertRaises(frappe.PermissionError, msg=f"{via.__name__} {channel}"):
					search(channel, via=via)
				with self.assertRaises(frappe.PermissionError, msg=f"{via.__name__} {channel} (all hotels)"):
					search(channel, properties=None, via=via)
		# the call centre is the agent's own channel
		self.assertTrue(std_offer(search("CALL_CENTER"))["total"])
		self.assertTrue(std_offer(search("CALL_CENTER", via=ui_crs))["per_night"])

	def test_quote_of_an_offer_on_another_channel_is_refused(self):
		as_user("Administrator")
		web = std_offer(search("DIRECT_WEB"))["rooms"][0]["offer_key"]
		ota = std_offer(search("OTA"))["rooms"][0]["offer_key"]
		as_user(self.agent)
		for key in (web, ota):
			with self.assertRaises(frappe.PermissionError):
				crs.quote(offer_key=key)
		cc = std_offer(search("CALL_CENTER"))["rooms"][0]["offer_key"]
		self.assertTrue(crs.quote(offer_key=cc)["ok"])

	def test_a_quote_on_another_channel_cannot_be_summed_or_booked(self):
		web = self.web_quote()
		# also a Booking Engine quote made anonymously on the public site
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
		res = public.search(site=SLUG, **STAY, session_id="g41-pub")
		pub = public.quote(site=SLUG, offer_key=std_offer(res)["rooms"][0]["offer_key"], session_id="g41-pub")
		self.assertTrue(pub["ok"], pub)
		as_user(self.agent)
		for qid in (web, pub["quote_id"]):
			with self.assertRaises(frappe.PermissionError):
				ui_crs.quote_summary(quote_ids=[qid], payment_method="Card")
			with self.assertRaises(frappe.PermissionError):
				crs.book(quote_ids=[qid], guest=GUEST, payment_method="Card")
			with self.assertRaises(frappe.PermissionError):
				ui_crs.book(quote_ids=[qid], guest=GUEST, payment_method="Card")
			with self.assertRaises(frappe.PermissionError):       # the service refuses it too
				booking_svc.create_booking(quote_ids=[qid], guest=GUEST, payment_method="Card")
		self.assertFalse(frappe.db.exists("TEX Booking", {"sales_channel": "DIRECT_WEB", "owner": self.agent}))

	def test_payment_methods_follow_the_channel_entitlement(self):
		as_user(self.agent)
		with self.assertRaises(frappe.PermissionError):
			crs.payment_methods(property=fx.PROPERTY, market="DE", currency="EUR", channel="DIRECT_WEB")
		self.assertTrue(crs.payment_methods(property=fx.PROPERTY, market="DE", currency="EUR", channel="CALL_CENTER"))

	def test_the_session_tells_the_screens_which_channels_to_offer(self):
		from kamra.tex.api import session

		as_user(self.agent)
		props = {p["name"]: p for p in session.bootstrap()["properties"]}
		self.assertEqual(props[fx.PROPERTY]["sales_channels"], ["CALL_CENTER"])
		as_user(self.split)
		props = {p["name"]: p for p in session.bootstrap()["properties"]}
		self.assertEqual(props[fx.PROPERTY]["sales_channels"], ["CALL_CENTER"])
		self.assertIn("DIRECT_WEB", props[OTHER]["sales_channels"])


class TestEntitledUsers(ChannelCase):
	def test_price_any_channel_prices_and_books_on_the_web_channel(self):
		as_user(self.seller)
		offer = std_offer(search("DIRECT_WEB"))
		q = crs.quote(offer_key=offer["rooms"][0]["offer_key"])
		self.assertTrue(q["ok"], q)
		self.assertEqual(ui_crs.quote_summary(quote_ids=[q["quote_id"]], payment_method="Card")["total"],
		                 offer["total"])
		out = crs.book(quote_ids=[q["quote_id"]], guest=GUEST, payment_method="Card")
		self.assertEqual(frappe.db.get_value("TEX Booking", out["booking"], "sales_channel"), "DIRECT_WEB")
		self.assertTrue(search("OTA"))

	def test_a_channel_list_admits_only_its_channels(self):
		as_user(self.b2b)
		self.assertTrue(std_offer(search("B2B"))["total"])
		for channel in ("CALL_CENTER", "DIRECT_WEB"):
			with self.assertRaises(frappe.PermissionError):
				search(channel)

	def test_entitlement_at_one_hotel_does_not_reach_another(self):
		as_user(self.split)
		with self.assertRaises(frappe.PermissionError):
			search("DIRECT_WEB")                                   # this hotel: call centre only
		# a group search on the web channel covers only the hotel where the user may sell it
		self.assertEqual([p["property"] for p in search("DIRECT_WEB", properties=None)["properties"]], [OTHER])
		as_user("Administrator")
		web = std_offer(search("DIRECT_WEB"))["rooms"][0]["offer_key"]
		as_user(self.split)
		with self.assertRaises(frappe.PermissionError):
			crs.quote(offer_key=web)
		self.assertTrue(std_offer(search("CALL_CENTER"))["total"])


class TestChannelPrices(ChannelCase):
	def test_booking_engine_and_call_centre_prices_differ(self):
		# 2 adults × 100 × 3 nights = 600.00 contract price; the channel markup decides
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
		be = std_offer(public.search(site=SLUG, **STAY, session_id="g41-be"))
		as_user(self.agent)
		cc = std_offer(search("CALL_CENTER"))
		self.assertEqual((be["total"], cc["total"]), ("630.00", "672.00"))
		as_user(self.seller)
		self.assertEqual(std_offer(search("DIRECT_WEB"))["total"], be["total"])
		self.assertEqual(std_offer(search("CALL_CENTER"))["total"], cc["total"])
		# the explanation names the channel's rule
		as_user("Administrator")
		expl = std_offer(search("CALL_CENTER"))["rooms"][0]["quote"]["explanation"]
		self.assertIn(self.cc_markup, str(expl))
		self.assertNotIn(self.web_markup, str(expl))
		# the call-centre booking keeps the call-centre price and channel
		as_user(self.agent)
		q = crs.quote(offer_key=cc["rooms"][0]["offer_key"])
		out = crs.book(quote_ids=[q["quote_id"]], guest=GUEST, payment_method="Card")
		b = frappe.db.get_value("TEX Booking", out["booking"], ["sales_channel", "created_via", "total_amount"],
		                        as_dict=True)
		self.assertEqual((b.sales_channel, b.created_via, D(b.total_amount)), ("CALL_CENTER", "Call Center",
		                                                                        D("672.00")))


class TestModificationKeepsTheChannel(ChannelCase):
	def _cc_reservation(self) -> str:
		as_user(self.agent)
		q = crs.quote(offer_key=std_offer(search("CALL_CENTER"))["rooms"][0]["offer_key"])
		out = crs.book(quote_ids=[q["quote_id"]], guest=GUEST, payment_method="Card")
		return out["rooms"][0]["reservation"]

	def test_a_change_is_priced_on_the_reservations_own_channel(self):
		res = self._cc_reservation()
		p = modification.propose(res, {"check_out": str(fx.d(6, 14))}, basis="CURRENT")
		self.assertEqual(p["proposed"]["request"]["channel"], "CALL_CENTER")
		self.assertEqual(p["proposed"]["totals"]["total"], "896.00")    # 800.00 + 12 % (call centre)
		out = crs.apply_modification(proposal_token=p["proposal_token"], reason="one more night")
		self.assertEqual(out["new_total"], "896.00")
		self.assertEqual(frappe.db.get_value("Reservation", res, "tex_sales_channel"), "CALL_CENTER")

	def test_the_channel_cannot_be_switched_by_a_modification(self):
		res = self._cc_reservation()
		for user in (self.agent, self.seller, "Administrator"):
			as_user(user)
			with self.assertRaises(frappe.ValidationError, msg=user):
				crs.propose_modification(reservation=res, changes={"channel": "DIRECT_WEB"})
		self.assertEqual(frappe.db.get_value("Reservation", res, "tex_sales_channel"), "CALL_CENTER")

	def test_a_web_booking_is_changed_at_web_prices(self):
		# the guest booked on the web; the call centre changes it on the web channel it was sold on
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
		res = public.search(site=SLUG, **STAY, session_id="g41-mod")
		q = public.quote(site=SLUG, offer_key=std_offer(res)["rooms"][0]["offer_key"], session_id="g41-mod")
		b = public.book(site=SLUG, quote_ids=[q["quote_id"]], guest=GUEST, payment_method="Card",
		                session_id="g41-mod", idempotency_key="idem-g41-mod")
		as_user(self.agent)
		p = modification.propose(b["rooms"][0]["reservation"], {"check_out": str(fx.d(6, 14))}, basis="CURRENT")
		self.assertEqual(p["proposed"]["request"]["channel"], "DIRECT_WEB")
		self.assertEqual(p["proposed"]["totals"]["total"], "840.00")    # 800.00 + 5 % (web)


class TestGrantsAndProfiles(ChannelCase):
	def test_nobody_grants_a_channel_they_are_not_entitled_to(self):
		profile(ANY, (*SELLER_CAPS, "price.any_channel"))
		profile(B2B_DESK, ("price.view", "reservation.view", "reservation.create"), ("B2B",))
		profile(CC_DESK, ("price.view", "reservation.view", "reservation.create"), ("CALL_CENTER",))
		profile(DESK_ADMIN, ("user.admin", "price.view", "reservation.view", "reservation.create"))
		admin = fx.ensure_user("g41-desk-admin@example.com", ["Hotel Admin"])
		grant(admin, fx.PROPERTY, DESK_ADMIN)
		newbie = fx.ensure_user("g41-newbie@example.com", ["Call Center Agent"])
		as_user(admin)
		for prof in (B2B_DESK, ANY):
			with self.assertRaises(frappe.PermissionError, msg=prof):
				frappe.get_doc({"doctype": "TEX Access Grant", "user": newbie, "scope_level": "Hotel",
				                "property": fx.PROPERTY, "permission_profile": prof}).insert()
		frappe.get_doc({"doctype": "TEX Access Grant", "user": newbie, "scope_level": "Hotel",
		                "property": fx.PROPERTY, "permission_profile": CC_DESK}).insert()

	def test_profiles_carry_their_channels(self):
		from kamra.tex.api import admin

		b2b = self.b2b                                            # the B2B desk and its user
		rows = {p["name"]: p for p in admin.profiles()["profiles"]}
		self.assertEqual(rows[B2B_DESK]["sales_channels"], ["B2B"])
		self.assertEqual(rows["Reservations Agent"]["sales_channels"], [])
		self.assertIn("price.any_channel", admin.profiles()["capabilities"])
		with self.assertRaises(frappe.ValidationError):
			admin.save_profile(data={"name": B2B_DESK, "profile_name": B2B_DESK, "capabilities": ["price.view"],
			                         "sales_channels": ["B2B", "NOPE"]})
		admin.save_profile(data={"name": B2B_DESK, "profile_name": B2B_DESK, "capabilities": ["price.view"],
		                         "sales_channels": ["OTA", "B2B"]})
		self.assertEqual({p["name"]: p for p in admin.profiles()["profiles"]}[B2B_DESK]["sales_channels"],
		                 ["B2B", "OTA"])
		as_user(b2b)
		self.assertEqual(scope.sales_channels(fx.PROPERTY), frozenset({"B2B", "OTA"}))

	def test_p29_keeps_revenue_and_admin_profiles_on_every_channel(self):
		from kamra.patches.tex import p29_channel_binding

		as_user("Administrator")
		publisher = profile("G41 Publisher", ("price.view", "contract.publish"))
		plain = profile("G41 Plain Seller", ("price.view", "reservation.create"))
		for name in ("Revenue Manager", "Hotel Admin"):
			frappe.db.delete("TEX Profile Capability", {"parent": name, "capability": "price.any_channel"})
		for _run in range(2):                                     # re-runnable
			p29_channel_binding.execute()

		def caps(name):
			return set(frappe.get_all("TEX Profile Capability", filters={"parent": name}, pluck="capability"))

		for name in ("Revenue Manager", "Hotel Admin", "Group Admin", "Enterprise Admin", publisher):
			self.assertIn("price.any_channel", caps(name), name)
		for name in ("Reservations Agent", "Finance", "Viewer", plain):
			self.assertNotIn("price.any_channel", caps(name), name)
		self.assertEqual(len([c for c in frappe.get_all("TEX Profile Capability", filters={"parent": publisher},
		                                                pluck="capability") if c == "price.any_channel"]), 1)
