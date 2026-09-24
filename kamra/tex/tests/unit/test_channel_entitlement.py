"""Sales-channel entitlement of a permission profile (G-41, ADR-050). Pure: runs without frappe."""

import unittest

from kamra.tex.security import capabilities as caps

EVERY = frozenset({"DIRECT_WEB", "CALL_CENTER", "API", "B2B", "META", "OTA"})
SELLER = {"price.view", "reservation.view", "reservation.create"}


class TestProfileChannels(unittest.TestCase):
	def test_a_profile_without_a_channel_list_sells_on_the_call_centre(self):
		self.assertEqual(caps.profile_channels(SELLER, (), EVERY), frozenset({"CALL_CENTER"}))

	def test_a_channel_list_admits_exactly_its_channels(self):
		self.assertEqual(caps.profile_channels(SELLER, ("B2B", "OTA"), EVERY), frozenset({"B2B", "OTA"}))
		# a channel the site does not know (deleted since) admits nothing
		self.assertEqual(caps.profile_channels(SELLER, ("B2B", "GONE"), EVERY), frozenset({"B2B"}))

	def test_price_any_channel_admits_every_channel_whatever_the_list(self):
		self.assertEqual(caps.profile_channels(SELLER | {caps.ANY_CHANNEL}, (), EVERY), EVERY)
		self.assertEqual(caps.profile_channels(SELLER | {caps.ANY_CHANNEL}, ("B2B",), EVERY), EVERY)

	def test_a_profile_that_cannot_price_adds_no_channel(self):
		self.assertEqual(caps.profile_channels({"system.monitor"}, (), EVERY), frozenset())
		self.assertEqual(caps.profile_channels({caps.ANY_CHANNEL}, ("B2B",), EVERY), frozenset())
		self.assertEqual(caps.profile_channels({"reservation.create"}, (), EVERY), frozenset({"CALL_CENTER"}))

	def test_the_default_needs_the_call_centre_to_exist(self):
		self.assertEqual(caps.profile_channels(SELLER, (), EVERY - {"CALL_CENTER"}), frozenset())


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


if __name__ == "__main__":
	unittest.main()
