"""NEW-1 (audit Part 2A, ADR-064): one tick of every TEX scheduler entry point over seeded data.

``kamra.tex.scheduler`` every_minute, every_5_minutes, outbox_every_5_minutes (the PMS outbox, its own job
since NEW-7), every_15_minutes, site_midnight, daily and fx_daily run once each, in that order, with the
clock frozen (``freeze_time``: a Wednesday in June, before the fixtures' season) and no outside world:

* FX provider HTTP (the ``requests.get`` of ``connect.fx_providers.fetch``) answers a canned TCMB
  and ECB file;
* the PMS / webhook adapters (``connect.adapters.get``, the outbox) and the channel adapter
  (``distribution.repository.adapter_for``: deliver_ari, process_inbound, daily_resync) are stubs
  that record and accept;
* payment providers (``payments.service.provider_for``, called as it is: ``(account_name, *,
  purpose, transaction)``) are a stub that records a refund or a status query (``handle_callback``,
  answered "still pending") and refuses anything else. The seed holds one iyzico charge still Pending
  ten minutes after it started (NEW-2): the re-verification job asks the stub about it once, by its
  token, and leaves it as it was. It holds no queued refund and no guest change awaiting payment, so
  ``late_payments.refund_queued`` and ``guest_changes.expire_awaiting`` run with nothing to do: their
  refund paths are not exercised here (``test_hold_payment_race`` and ``test_self_service_money``
  cover them); the stub only guarantees no real provider is called;
* the domain check's DNS-over-HTTPS lookup (``services.sites.txt_records``) answers the token;
* e-mail is only queued: ``EmailQueue.send`` records and delivers nothing;
* any other connection to a host that is not this machine is refused and recorded (``socket``);
* the worker of the outbox's own RQ queue (LO-08): ``outbox_every_5_minutes`` only queues
  ``deliver_outbox`` there, so the stub runs what it queued in this tick, and records the queue.

The test fails when a job logs a new "TEX …" Error Log (``scheduler._run`` turns a job's exception
into "TEX job <path>"; a job's isolated steps log "TEX …" too; the alerts job's own "TEX status alert:
…" record is its output, ADR-047), when anything tried the network, or
when the seed is not what it must be afterwards. The job boundary's commit is a no-op: the test's
rollback undoes the tick. It tests TEX's orchestration and the database transitions, not providers.
"""

from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest import mock

import frappe
from frappe.utils import add_days, add_to_date, get_datetime, getdate, now_datetime, nowdate

from kamra.tex.api import lists, public
from kamra.tex.commercial import contracts
from kamra.tex.connect import adapters as pms_adapters
from kamra.tex.connect import fx_providers
from kamra.tex.distribution import repository as dist
from kamra.tex.distribution.model import PushResult
from kamra.tex.payments import service as pay
from kamra.tex.payments.providers.base import Outcome
from kamra.tex.services import sites
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import SLUG, guest_books, setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase

ENTRY_POINTS = ("every_minute", "every_5_minutes", "outbox_every_5_minutes", "every_15_minutes", "site_midnight",
                "daily", "fx_daily")
LOCAL_HOSTS = ("localhost", "test.localhost", "::1")
TOKEN = "tex-smoke-token"
# the alerts job records a worsened status check as an Error Log by design (ADR-047): not a failure
ALERT_RECORD = "TEX status alert: "


def tick_time() -> datetime:
	"""A fixed instant: the first Wednesday of June before the fixtures' season, 10:30:00.250000 (a
	whole second is stored as "…:00" and read back as "…:00.000000": Frappe's check_if_latest trips)."""
	day = date(fx.YEAR - 1, 6, 1)
	return datetime.combine(day + timedelta(days=(2 - day.weekday()) % 7), datetime.min.time()) + \
		timedelta(hours=10, minutes=30, microseconds=250000)


def _local(host) -> bool:
	host = str(host or "")
	return host in LOCAL_HOSTS or host.startswith("127.") or host.startswith("/")


class _Response:
	def __init__(self, text: str):
		self.text, self.status_code = text, 200

	def raise_for_status(self):
		return None


@contextmanager
def outside_world(day: date):
	"""The stubs named in the module docstring. → what each was asked."""
	calls: dict[str, list] = {"network": [], "fx": [], "pms": [], "channel": [], "provider": [], "dns": [],
	                          "mail": [], "queued": []}
	tcmb = (f'<Tarih_Date Tarih="{day:%d.%m.%Y}" Date="{day:%m/%d/%Y}"><Currency CurrencyCode="EUR" Kod="EUR">'
	        "<Unit>1</Unit><ForexBuying>34.10</ForexBuying><ForexSelling>34.20</ForexSelling></Currency>"
	        "</Tarih_Date>")
	ecb = ('<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" '
	       'xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref"><Cube>'
	       f'<Cube time="{day:%Y-%m-%d}"><Cube currency="USD" rate="1.0800"/></Cube></Cube></gesmes:Envelope>')

	def http_get(url, *a, **kw):
		if url == fx_providers.TCMB_URL:
			calls["fx"].append("TCMB")
			return _Response(tcmb)
		if url == fx_providers.ECB_URL:
			calls["fx"].append("ECB")
			return _Response(ecb)
		calls["network"].append(("http", url))
		raise ConnectionError(f"smoke test: no network ({url})")

	class Pms:
		def __init__(self, connection):
			self.connection = connection

		def deliver(self, event, payload, idempotency_key=None):
			calls["pms"].append((self.connection.name, event, payload.get("reservation")))

	class Channel:
		def __init__(self, connection):
			self.connection = connection

		def push_ari(self, runs):
			calls["channel"].append((self.connection.name, len(runs)))
			return PushResult(ok=True, accepted=len(runs), provider_ref="smoke")

		def fetch_reservations(self, since):
			return None

	class Provider:
		"""Stands in for ``payments.service.provider_for(account_name, *, purpose, transaction)``."""

		def __init__(self, account_name, *, purpose="new", transaction=None, **kw):
			self.account, self.purpose, self.transaction = account_name, purpose, transaction

		def refund(self, provider_ref, amount, currency, *, reference=None):
			calls["provider"].append(("refund", provider_ref, str(amount), currency))
			return Outcome(status="Succeeded", provider_ref=f"smoke-{provider_ref}", amount=Decimal(amount),
			               currency=currency)

		def handle_callback(self, transaction, params, headers, body, *, provider_ref=None):
			calls["provider"].append(("handle_callback", transaction, dict(params), provider_ref))
			return Outcome(status="Pending")

		def __getattr__(self, name):
			calls["provider"].append((name,))
			raise AssertionError(f"smoke test: payment provider {name} called")

	def txt_records(name):
		calls["dns"].append(name)
		return [TOKEN]

	import socket

	real_getaddrinfo, real_connect = socket.getaddrinfo, socket.socket.connect

	def getaddrinfo(host, *a, **kw):
		if not _local(host):
			calls["network"].append(("dns", host))
			raise OSError(f"smoke test: no network ({host})")
		return real_getaddrinfo(host, *a, **kw)

	def connect(sock, address):
		if isinstance(address, tuple) and not _local(address[0]):
			calls["network"].append(("connect", address[0]))
			raise OSError(f"smoke test: no network ({address[0]})")
		return real_connect(sock, address)

	real_enqueue = frappe.enqueue

	def enqueue(method, *a, **kw):
		if method == "kamra.tex.scheduler.deliver_outbox":
			calls["queued"].append((method, kw.get("queue")))
			return frappe.get_attr(method)()
		return real_enqueue(method, *a, **kw)

	from frappe.email.doctype.email_queue.email_queue import EmailQueue

	with ExitStack() as st:
		st.enter_context(mock.patch("requests.get", http_get))
		st.enter_context(mock.patch.object(pms_adapters, "get", Pms))
		st.enter_context(mock.patch.object(dist, "adapter_for", Channel))
		st.enter_context(mock.patch.object(pay, "provider_for", Provider))
		st.enter_context(mock.patch.object(sites, "txt_records", txt_records))
		st.enter_context(mock.patch.object(EmailQueue, "send", lambda self, *a, **kw: calls["mail"].append(self.name)))
		st.enter_context(mock.patch.object(socket, "getaddrinfo", getaddrinfo))
		st.enter_context(mock.patch.object(socket.socket, "connect", connect))
		st.enter_context(mock.patch.object(frappe, "enqueue", enqueue))
		st.enter_context(mock.patch.object(frappe.db, "commit"))    # the job boundary: the test rolls back
		yield calls


def status(version: str) -> str:
	return frappe.db.get_value("TEX Contract Version", version, "status")


class TestSchedulerTick(TexTestCase):
	def test_one_tick_of_every_entry_point_keeps_the_seed(self):
		with self.freeze_time(tick_time()):
			seed = self.seed()
			before = set(frappe.get_all("Error Log", pluck="name"))
			with outside_world(getdate(nowdate())) as calls:
				for entry in ENTRY_POINTS:
					frappe.get_attr(f"kamra.tex.scheduler.{entry}")()
			errors = frappe.get_all("Error Log", filters=[["method", "like", "TEX %"]], fields=["name", "method", "error"])
			self.assertEqual([(e.method, (e.error or "")[-1500:]) for e in errors
			                  if e.name not in before and not e.method.startswith(ALERT_RECORD)], [])
			self.assertEqual(calls["network"], [])
			self.check(seed, calls)

	def test_the_provider_stub_takes_what_provider_for_takes(self):
		# review round 1: refunds call provider_for(account, purpose="settle", transaction=...)
		import inspect

		real = inspect.signature(pay.provider_for)
		with outside_world(getdate(nowdate())) as calls:
			stub = inspect.signature(pay.provider_for)
			for name in real.parameters:
				self.assertTrue(name in stub.parameters or any(
					p.kind is inspect.Parameter.VAR_KEYWORD for p in stub.parameters.values()), name)
			provider = pay.provider_for("ACC-SMOKE", purpose="settle", transaction="TXN-SMOKE")
			out = provider.refund("ref-1", Decimal("10.00"), "EUR", reference="late:TXN-SMOKE")
		self.assertEqual((out.status, calls["provider"]), ("Succeeded", [("refund", "ref-1", "10.00", "EUR")]))

	# ─── the seed ────────────────────────────────────────────────────────

	def seed(self) -> dict:
		s: dict = {}
		for code, symbol in (("TRY", "₺"), ("USD", "$")):
			fx.ensure_currency(code, symbol)
		pay_account = setup_site_and_payments(self.f)["account"]           # contract PAY: V1 live, no end
		s["live"] = frappe.db.get_value("TEX Contract", {"contract_code": "PAY", "property": fx.PROPERTY},
		                                "active_version")
		sched = fx.create_contract(self.f, code="SMOKE-SCHED")               # V1 live, V2 from next month
		s["sched_contract"], s["sched_v1"] = sched["contract"], sched["version"]
		s["scheduled"] = contracts.new_draft(sched["contract"])
		contracts.publish(s["scheduled"], effective_from=add_to_date(now_datetime(), days=30))

		# a PMS and a channel manager, so the outbox and the ARI queue have work
		s["pms"] = frappe.get_doc({"doctype": "TEX Integration Connection", "label": "Smoke PMS", "property": fx.PROPERTY,
		                           "category": "PMS", "adapter": "log", "environment": "Sandbox", "enabled": 1}
		                          ).insert(ignore_permissions=True).name
		s["channel"] = frappe.get_doc({"doctype": "TEX Integration Connection", "label": "Smoke CM",
		                               "property": fx.PROPERTY, "category": "Channel Manager",
		                               "adapter": "sandbox_channel", "environment": "Sandbox", "enabled": 1,
		                               "secret": "smoke-secret"}).insert(ignore_permissions=True).name
		frappe.get_doc({"doctype": "TEX Channel Mapping", "connection": s["channel"],
		                "room_type": frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"}),
		                "rate_plan": frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"}),
		                "external_room_code": "DBL", "external_rate_code": "BAR", "board": "AI", "market": "DE",
		                "sales_channel": "OTA", "sell_currency": "EUR", "occupancies": "1,2", "horizon_days": 365}
		               ).insert(ignore_permissions=True)

		# a club whose points never expire; a paid stay earns in it
		s["club"] = frappe.get_doc({"doctype": "TEX Loyalty Program", "program_name": "Smoke Club",
		                            "property": fx.PROPERTY, "enabled": 1, "currency": "EUR", "point_value": 0.1,
		                            "min_redeem_points": 50, "max_redeem_percent": 50, "pending_days": 0,
		                            "earn_rules": [{"basis": "STAY", "rate": 25}]}).insert(ignore_permissions=True).name
		b = guest_books(session="smoke-tick")
		p = b["payment"]
		public.mock_pay(transaction=p["transaction"], outcome="success", sig=p["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the scheduler runs as Administrator
		s["booking"], s["reservation"] = b["booking"], b["rooms"][0]["reservation"]
		s["guest"] = frappe.db.get_value("TEX Booking", b["booking"], "booker_guest")
		s["stay_points"] = frappe.db.get_value("TEX Loyalty Ledger", {"guest": s["guest"], "entry_type": "Earn",
		                                                              "status": "Pending"}, "name")

		def points(n, expires_on=None):
			return frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": s["club"], "guest": s["guest"],
			                       "entry_type": "Earn", "points": n, "status": "Available", "property": fx.PROPERTY,
			                       "expires_on": expires_on, "reason": "smoke"}).insert(ignore_permissions=True).name

		s["open_points"] = points(100)                                        # no expiry
		s["old_points"] = points(40, add_days(nowdate(), -1))                 # expired yesterday

		# access: one grant without an end, one that ended yesterday
		def grant(email):
			user = fx.ensure_user(email, ["Call Center Agent"])
			return frappe.get_doc({"doctype": "TEX Access Grant", "user": user, "scope_level": "Hotel",
			                       "property": fx.PROPERTY, "permission_profile": "Reservations Agent"}
			                      ).insert(ignore_permissions=True).name

		s["open_grant"] = grant("smoke-open@example.com")
		s["ended_grant"] = grant("smoke-ended@example.com")
		frappe.db.set_value("TEX Access Grant", s["ended_grant"], "valid_until", add_days(nowdate(), -1))

		# payment links: without an expiry, past it, and live
		def link(name):
			return pay.create_link(property=fx.PROPERTY, amount="25", currency="EUR", description=name,
			                       provider_account=pay_account, guest_name=name)["link"]

		s["open_link"], s["stale_link"], s["live_link"] = link("open"), link("stale"), link("live")
		frappe.db.set_value("TEX Payment Link", s["open_link"], "expires_at", None)
		frappe.db.set_value("TEX Payment Link", s["stale_link"], "expires_at", add_days(now_datetime(), -1))

		# an iyzico charge still Pending ten minutes after it started: the re-verification job asks (NEW-2)
		iyzico = fx.ensure("TEX Payment Provider Account", {"property": fx.PROPERTY, "provider": "iyzico"},
		                   {"label": "Smoke iyzico", "property": fx.PROPERTY, "provider": "iyzico",
		                    "environment": "Sandbox", "enabled": 1, "currencies": "EUR"})
		s["iyzico_charge"] = pay._new_txn(property=fx.PROPERTY, txn_type="Charge", method="Card", amount=Decimal("50"),
		                                  currency="EUR", provider_account=iyzico, provider="iyzico",
		                                  provider_ref="tok-smoke", idempotency_key="smoke-iyzico").name
		frappe.db.sql("UPDATE `tabTEX Payment Transaction` SET creation = %s WHERE name = %s",
		              (add_to_date(now_datetime(), minutes=-10), s["iyzico_charge"]))

		# a verified booking-site domain the daily check looks up
		s["domain"] = frappe.get_doc({"doctype": "TEX Booking Domain", "parent": SLUG, "parenttype": "TEX Booking Site",
		                              "parentfield": "domains", "domain": "smoke.example.com", "verified": 1,
		                              "verification_token": TOKEN, "check_failures": 0})
		s["domain"].db_insert()
		s["pms_events"] = frappe.get_all("TEX Integration Outbox", filters={"connection": s["pms"],
		                                                                    "kind": "Reservation"}, pluck="name")
		self.assertTrue(s["pms_events"])
		return s

	# ─── after one tick ──────────────────────────────────────────────────

	def check(self, s: dict, calls: dict) -> None:
		now = now_datetime()
		# contracts: the live version without an end and the scheduled one are still published
		self.assertEqual(status(s["live"]), "Published")
		self.assertEqual((status(s["sched_v1"]), status(s["scheduled"])), ("Published", "Published"))
		self.assertEqual(frappe.db.get_value("TEX Contract", s["sched_contract"], "active_version"), s["sched_v1"])
		later = add_to_date(get_datetime(frappe.db.get_value("TEX Contract Version", s["scheduled"], "effective_from")),
		                    minutes=1)
		self.assertEqual(contracts.active_version_header(s["sched_contract"], later).version_id, s["scheduled"])
		# the current lists still show them (entry-branding, b0522d92)
		current = {r["name"] for r in lists.versions(property=fx.PROPERTY, status="current")["rows"]}
		self.assertTrue({s["live"], s["sched_v1"], s["scheduled"]} <= current)
		periods = {r["version"] for r in lists.version_rows(section="periods", property=fx.PROPERTY)["rows"]}
		self.assertTrue({s["live"], s["sched_v1"]} <= periods)

		# loyalty: points without an expiry stay; the stay's points wait for the stay; expired ones go
		self.assertEqual(frappe.db.get_value("TEX Loyalty Ledger", s["open_points"], "status"), "Available")
		self.assertFalse(frappe.db.exists("TEX Loyalty Ledger", {"entry_type": "Expire",
		                                                          "reason": f"expiry of {s['open_points']}"}))
		self.assertTrue(frappe.db.exists("TEX Loyalty Ledger", {"entry_type": "Expire",
		                                                         "reason": f"expiry of {s['old_points']}"}))
		self.assertEqual(frappe.db.get_value("TEX Loyalty Ledger", s["stay_points"], "status"), "Pending")

		# access grants: the open one is not "expired"; the ended one is, once
		expired = set(frappe.get_all("TEX Audit Event", filters={"action": "grant.expired"}, pluck="reference_name"))
		self.assertNotIn(s["open_grant"], expired)
		self.assertIn(s["ended_grant"], expired)
		self.assertTrue(frappe.db.exists("User Permission", {"user": "smoke-open@example.com", "allow": "Property",
		                                                     "for_value": fx.PROPERTY, "tex_managed": 1}))

		# payment links: no expiry is not expired; past it is; a live one is untouched
		self.assertEqual([frappe.db.get_value("TEX Payment Link", s[k], "status")
		                  for k in ("open_link", "stale_link", "live_link")], ["Active", "Expired", "Active"])

		# the booking is still confirmed and paid
		self.assertEqual(frappe.db.get_value("Reservation", s["reservation"], "status"), "Confirmed")

		# the iyzico charge was asked about once, by its token, and is as it was (the gateway: still pending)
		self.assertEqual(calls["provider"], [("handle_callback", s["iyzico_charge"], {"token": "tok-smoke"}, "tok-smoke")])
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", s["iyzico_charge"], ["status", "provider_ref"]),
		                 ("Pending", "tok-smoke"))

		# the stubs were reached and what they answered was stored
		self.assertEqual(sorted(calls["fx"]), ["ECB", "TCMB"])
		for provider, base, quote in (("TCMB", "EUR", "TRY"), ("ECB", "EUR", "USD")):
			fetched = frappe.db.get_value("TEX FX Rate", {"provider": provider, "base_currency": base,
			                                              "quote_currency": quote, "rate_date": getdate(now)},
			                              "fetched_at")
			self.assertEqual(get_datetime(fetched), now, provider)
		# the cron entry queued the delivery on the outbox's own queue (LO-08); the stub worker ran it
		self.assertEqual(calls["queued"], [("kamra.tex.scheduler.deliver_outbox", "long")])
		self.assertEqual({r for _c, _e, r in calls["pms"]}, {s["reservation"]})
		self.assertEqual({frappe.db.get_value("TEX Integration Outbox", n, "status") for n in s["pms_events"]},
		                 {"Sent"})
		self.assertTrue(calls["channel"])
		self.assertEqual(calls["dns"], ["_tex-verify.smoke.example.com"])
		self.assertEqual(frappe.db.get_value("TEX Booking Domain", s["domain"].name, ["verified", "check_failures"]),
		                 (1, 0))
		# nothing else reached a provider (the one status query is checked above), no e-mail was sent
		self.assertEqual(([c for c in calls["provider"] if c[0] != "handle_callback"], calls["mail"]), ([], []))
