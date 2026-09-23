"""Channel distribution, pure parts (G-69): ARI change detection and runs, webhook
signatures (fail closed), the neutral booking format and the sandbox adapter."""

import json
import unittest
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from kamra.tex.distribution import ari, signing
from kamra.tex.distribution.adapters import REGISTRY, AdapterError, SandboxChannel, parse_neutral
from kamra.tex.distribution.model import AriDay

D = Decimal
DAY = date(2027, 6, 1)


def day(i, available=5, price="100.00", **kw):
	return AriDay(DAY + timedelta(days=i), available, rates=((2, D(price)),), currency="EUR", **kw)


class TestAri(unittest.TestCase):
	def test_only_changed_days_are_pushed(self):
		days = [day(0), day(1), day(2, available=0)]
		pushed = {days[0].day: days[0].fingerprint(), days[1].day: day(1, price="90").fingerprint()}
		self.assertEqual([d.day for d in ari.changed(days, pushed)], [days[1].day, days[2].day])
		self.assertEqual(day(0, price="100").fingerprint(), day(0, price="100.00").fingerprint())

	def test_equal_consecutive_days_become_one_run(self):
		days = [day(0), day(1), day(2), day(3, closed=True), day(5), day(4)]
		runs = ari.runs("DBL", "BAR", days)
		self.assertEqual([(r.date_from, r.date_to) for r in runs],
		                 [(DAY, DAY + timedelta(days=2)), (DAY + timedelta(days=3),) * 2,
		                  (DAY + timedelta(days=4), DAY + timedelta(days=5))])
		self.assertEqual(len(ari.expand(runs[0])), 3)
		self.assertEqual(runs[0].to_dict()["rates"], [{"adults": 2, "price": "100.00"}])


class TestSigning(unittest.TestCase):
	def test_fail_closed(self):
		body, now = b'{"a":1}', 1_800_000_000
		good = signing.sign("s3cret", now, body)
		signing.verify("s3cret", str(now), good, body, now + 10)
		for secret, ts, sig, b, t in (("", str(now), good, body, now), (None, str(now), good, body, now),
		                              ("s3cret", None, good, body, now), ("s3cret", str(now), None, body, now),
		                              ("s3cret", str(now), good, b'{"a":2}', now),
		                              ("s3cret", str(now), good, body, now + signing.TOLERANCE_SECONDS + 1),
		                              ("other", str(now), good, body, now), ("s3cret", "x", good, body, now)):
			with self.assertRaises(signing.SignatureError):
				signing.verify(secret, ts, sig, b, t)


MSG = {"provider_ref": "OTA-1", "status": "new", "channel_name": "Booking.com",
       "guest": {"first_name": "Mia", "last_name": "Berg", "email": "mia@example.com"},
       "rooms": [{"room_code": "DBL", "rate_code": "BAR", "check_in": "2027-06-01", "check_out": "2027-06-04",
                  "adults": 2, "children_ages": [7], "total": "450.00", "currency": "EUR", "line_ref": "L1"}]}


class TestNeutralFormat(unittest.TestCase):
	def test_parse(self):
		r = parse_neutral(MSG)
		self.assertEqual((r.provider_ref, r.status, r.rooms[0].total, r.rooms[0].children_ages), ("OTA-1", "new",
		                                                                                           D("450.00"), (7,)))
		self.assertEqual(parse_neutral({"provider_ref": "OTA-1", "status": "cancelled"}).rooms, ())

	def test_bad_messages_are_rejected_for_good(self):
		room = MSG["rooms"][0]
		for bad in ({**MSG, "status": "maybe"}, {**MSG, "provider_ref": ""}, {**MSG, "rooms": []},
		            {**MSG, "rooms": [{**room, "check_out": "2027-06-01"}]}, {**MSG, "rooms": [{**room, "adults": 0}]},
		            {**MSG, "rooms": [{**room, "total": "abc"}]}, {**MSG, "rooms": [{**room, "total": "-5"}]},
		            {**MSG, "rooms": [{**room, "check_in": "someday"}]}):
			with self.assertRaises(AdapterError) as e:
				parse_neutral(bad)
			self.assertFalse(e.exception.retryable)


class TestSandbox(unittest.TestCase):
	def adapter(self, **settings):
		conn = SimpleNamespace(settings_json=json.dumps(settings), get=lambda k, d=None: json.dumps(settings)
		                       if k == "settings_json" else d)
		return SandboxChannel(conn, secret="s3cret")

	def test_push_and_simulated_failures(self):
		runs = ari.runs("DBL", "BAR", [day(0), day(1)])
		self.assertTrue(self.adapter().push_ari(runs).ok)
		with self.assertRaises(AdapterError) as e:
			self.adapter(push="fail").push_ari(runs)
		self.assertTrue(e.exception.retryable)
		for settings in ({"push": "reject"}, {"unknown_rooms": ["DBL"]}):
			with self.assertRaises(AdapterError) as e:
				self.adapter(**settings).push_ari(runs)
			self.assertFalse(e.exception.retryable)

	def test_webhook_is_verified_and_parsed(self):
		a = self.adapter()
		body = json.dumps([MSG, {**MSG, "provider_ref": "OTA-2"}]).encode()
		now = 1_800_000_000
		a.verify_webhook({"X-TEX-Timestamp": str(now), "X-TEX-Signature": signing.sign("s3cret", now, body)}, body, now)
		self.assertEqual([r.provider_ref for r in a.parse_webhook(body)], ["OTA-1", "OTA-2"])
		with self.assertRaises(signing.SignatureError):
			a.verify_webhook({}, body, now)

	def test_only_honest_adapters_are_installed(self):
		self.assertEqual(set(REGISTRY), {"sandbox_channel"})
		self.assertFalse(any(cls.certified for cls in REGISTRY.values()))       # no production channel yet


class TestPmsAdapters(unittest.TestCase):
	"""G-90: an uncertified PMS adapter is refused for a Production connection at run time."""

	def conn(self, adapter, environment):
		return SimpleNamespace(adapter=adapter, environment=environment, settings_json=None, get=lambda k, d=None: d)

	def test_uncertified_adapters_never_run_in_production(self):
		from kamra.tex.connect import adapters as pms

		self.assertIsInstance(pms.get(self.conn("log", "Sandbox")), pms.LogOnlyPMS)
		self.assertIsInstance(pms.get(self.conn("webhook", "Production")), pms.WebhookPMS)   # certified
		with self.assertRaisesRegex(pms.AdapterRefused, "not certified for production") as e:
			pms.get(self.conn("log", "Production"))
		self.assertFalse(e.exception.retryable)
