"""Sales-channel entitlement of a permission profile (G-41, ADR-050 and its review follow-up).
Pure: runs without frappe."""

import unittest

from kamra.tex.security import capabilities as caps

EVERY = frozenset({"DIRECT_WEB", "CALL_CENTER", "API", "B2B", "META", "OTA"})
SELLER = {"price.view", "reservation.view", "reservation.create"}
PRICE, BOOK = caps.PRICE, caps.BOOK


def channels(held, listed=(), every=EVERY):
	"""(pricing channels, booking channels) of one profile."""
	return (caps.profile_channels(held, listed, every, for_cap=PRICE),
	        caps.profile_channels(held, listed, every, for_cap=BOOK))


class TestProfileChannels(unittest.TestCase):
	def test_a_profile_without_a_channel_list_sells_on_the_call_centre(self):
		self.assertEqual(channels(SELLER), (frozenset({"CALL_CENTER"}),) * 2)

	def test_a_channel_list_admits_exactly_its_channels(self):
		self.assertEqual(channels(SELLER, ("B2B", "OTA")), (frozenset({"B2B", "OTA"}),) * 2)
		# a channel the site does not know (deleted since) admits nothing
		self.assertEqual(channels(SELLER, ("B2B", "GONE"))[1], frozenset({"B2B"}))

	def test_price_any_channel_admits_every_channel_whatever_the_list(self):
		self.assertEqual(channels(SELLER | {caps.ANY_CHANNEL}), (EVERY, EVERY))
		self.assertEqual(channels(SELLER | {caps.ANY_CHANNEL}, ("B2B",)), (EVERY, EVERY))

	def test_channels_serve_only_the_capability_the_profile_holds(self):
		# review finding 3: a price-only profile's channels are priced, never booked, and the other way round
		self.assertEqual(channels({"price.view"}, ("OTA",)), (frozenset({"OTA"}), frozenset()))
		self.assertEqual(channels({"reservation.create"}, ("B2B",)), (frozenset(), frozenset({"B2B"})))
		self.assertEqual(channels({"price.view", caps.ANY_CHANNEL}), (EVERY, frozenset()))
		self.assertEqual(channels({"system.monitor"}), (frozenset(), frozenset()))
		self.assertEqual(channels({caps.ANY_CHANNEL}, ("B2B",)), (frozenset(), frozenset()))

	def test_the_default_needs_the_call_centre_to_exist(self):
		self.assertEqual(channels(SELLER, (), EVERY - {"CALL_CENTER"}), (frozenset(), frozenset()))


class TestDefaults(unittest.TestCase):
	def test_admin_and_revenue_profiles_price_on_every_channel_sellers_do_not(self):
		self.assertIn(caps.ANY_CHANNEL, caps.CAPABILITIES)
		for name in ("Hotel Admin", "Group Admin", "Enterprise Admin", "Revenue Manager"):
			self.assertIn(caps.ANY_CHANNEL, caps.DEFAULT_PROFILES[name], name)
		for name in ("Reservations Agent", "Finance", "Viewer"):
			self.assertNotIn(caps.ANY_CHANNEL, caps.DEFAULT_PROFILES[name], name)
		for role in ("Front Desk", "Call Center Agent", "Kamra Agent", "Finance"):
			self.assertNotIn(caps.ANY_CHANNEL, caps.ROLE_DEFAULTS[role], role)
		self.assertEqual(caps.STAFF_DEFAULT_CHANNELS, frozenset({"CALL_CENTER"}))

	def test_a_booking_site_sells_on_the_web_channels(self):
		self.assertEqual(caps.WEB_CHANNELS, frozenset({"DIRECT_WEB", "META"}))


if __name__ == "__main__":
	unittest.main()
