"""Channel distribution (G-69, ADR-039): ARI comes from TEX's own rules and only changes are
pushed; failures retry and park; the webhook fails closed; channel bookings are applied
once, in order, as the channel's sale (new / modified / cancelled, overbooking accepted
with a warning); reconciliation finds drift; everything stays inside its hotel."""

import json
from datetime import timedelta
from unittest import mock

import frappe
from frappe.utils import getdate, now_datetime

from kamra.tex.api import distribution as dist_api
from kamra.tex.distribution import repository as dist
from kamra.tex.distribution import signing
from kamra.tex.money import D
from kamra.tex.pricing.model import StayRequest
from kamra.tex.security import scope
from kamra.tex.services import modification, quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase
from kamra.tex.tests.integration.test_crm_segments import OTHER, agent, other_tenant

SECRET = "sandbox-secret-1"


def message(ref="OTA-100", status="new", *, room="DBL", rate="BAR", ci=None, co=None, total="450.00", line="L1",
            rooms=None):
	ci, co = ci or fx.d(6, 10), co or fx.d(6, 13)
	return {"provider_ref": ref, "status": status, "channel_name": "Booking.com",
	        "guest": {"first_name": "Mia", "last_name": "Berg", "email": "mia.berg@example.com"},
	        "rooms": rooms if rooms is not None else [
		        {"room_code": room, "rate_code": rate, "check_in": str(ci), "check_out": str(co), "adults": 2,
		         "total": total, "currency": "EUR", "line_ref": line}]}


class DistributionCase(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		self.conn = frappe.get_doc({"doctype": "TEX Integration Connection", "label": "Sandbox CM",
		                            "property": fx.PROPERTY, "category": "Channel Manager",
		                            "adapter": "sandbox_channel", "environment": "Sandbox", "enabled": 1,
		                            "secret": SECRET}).insert(ignore_permissions=True)
		self.std = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		self.flex = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
		self.mapping = frappe.get_doc({"doctype": "TEX Channel Mapping", "connection": self.conn.name,
		                               "room_type": self.std, "external_room_code": "DBL", "external_rate_code": "BAR",
		                               "board": "AI", "market": "DE", "sales_channel": "OTA", "sell_currency": "EUR",
		                               "rate_plan": self.flex, "occupancies": "1,2", "horizon_days": 365}
		                              ).insert(ignore_permissions=True)

	def jobs(self, status="Pending"):
		return frappe.get_all("TEX Integration Outbox", filters={"connection": self.conn.name, "kind": "ARI",
		                                                         "status": status}, pluck="name")

	def send(self, msg):
		return dist_api.sandbox_send(self.conn.name, msg)

	def apply_all(self):
		out = []
		while True:
			names = dist._claim_inbound(20)
			if not names:
				return out
			for n in names:
				out.append(dist.apply_inbound(n))


class TestAri(DistributionCase):
	def test_ari_comes_from_tex_rules(self):
		a, b = fx.d(6, 10), fx.d(6, 12)
		days = dist.build_days(self.mapping, a, b)
		self.assertEqual([d.day for d in days], [a, a + timedelta(days=1), b])
		version = dist._contract_version(self.mapping, now_datetime())[1]
		req = StayRequest(property=fx.PROPERTY, room_type=self.std, board="AI", check_in=a, check_out=a + timedelta(days=1),
		                  adults=2, sale_at=now_datetime(), market="DE", channel="OTA", sell_currency="EUR",
		                  rate_plan=self.flex)
		q, _t = quoting.price_request(version, req, check_capacity=False)
		self.assertEqual(dict(days[0].rates)[2], D(q.totals["total"]))            # TEX's price, to the cent
		from kamra.tex.availability import repository as avail

		count, _d = avail.stay_availability(fx.PROPERTY, self.std, None, a, a + timedelta(days=1), getdate())
		self.assertEqual(days[0].available, count)
		frappe.get_doc({"doctype": "TEX ARI Restriction", "property": fx.PROPERTY, "restriction_date": a,
		                "room_type": self.std, "stop_sell": "STOP"}).insert(ignore_permissions=True)
		self.assertTrue(dist.build_days(self.mapping, a, a)[0].closed)

	def test_only_changes_are_pushed_and_jobs_coalesce(self):
		frappe.db.delete("TEX Integration Outbox", {"connection": self.conn.name})
		a, b = fx.d(6, 10), fx.d(6, 14)
		dist.mark_dirty(fx.PROPERTY, [self.std], a, fx.d(6, 11), reason="t1")
		dist.mark_dirty(fx.PROPERTY, [self.std], fx.d(6, 12), b, reason="t2")      # coalesced into one job
		jobs = self.jobs()
		self.assertEqual(len(jobs), 1)
		p = json.loads(frappe.db.get_value("TEX Integration Outbox", jobs[0], "payload"))
		self.assertEqual((p["from"], p["to"], p["reasons"]), (str(a), str(b), ["t1", "t2"]))
		out = dist.push_job(jobs[0])
		self.assertEqual(out["pushed"], 5)
		self.assertEqual(frappe.db.count("TEX Channel ARI Day", {"mapping": self.mapping.name}), 5)
		dist.mark_dirty(fx.PROPERTY, [self.std], a, b)
		self.assertEqual(dist.push_job(self.jobs()[0])["pushed"], 0)                 # nothing changed
		frappe.get_doc({"doctype": "TEX ARI Restriction", "property": fx.PROPERTY, "restriction_date": fx.d(6, 12),
		                "room_type": self.std, "cta": "Yes"}).insert(ignore_permissions=True)   # the hook queues it
		self.assertEqual(dist.push_job(self.jobs()[0])["pushed"], 1)

	def test_failures_retry_and_a_rejection_parks(self):
		frappe.db.delete("TEX Integration Outbox", {"connection": self.conn.name})
		self.conn.db_set("settings_json", json.dumps({"push": "fail"}))
		dist.mark_dirty(fx.PROPERTY, [self.std], fx.d(6, 10), fx.d(6, 10))
		self.assertEqual(dist.deliver_ari()["failed"], 1)
		job = frappe.db.get_value("TEX Integration Outbox", self.jobs("Failed")[0],
		                          ["attempts", "next_attempt_at", "last_error", "claim_token"], as_dict=True)
		self.assertEqual((job.attempts, job.claim_token), (1, None))
		self.assertGreater(job.next_attempt_at, now_datetime())
		self.assertIn("unreachable", job.last_error)
		self.assertEqual(dist.deliver_ari()["failed"], 0)                          # not due yet
		frappe.db.delete("TEX Integration Outbox", {"connection": self.conn.name})
		self.conn.db_set("settings_json", json.dumps({"push": "reject"}))
		dist.mark_dirty(fx.PROPERTY, [self.std], fx.d(6, 10), fx.d(6, 10))
		dist.deliver_ari()
		self.assertEqual(len(self.jobs("Dead")), 1)                                 # a rejection is not retried as is

	def test_a_claimed_job_is_not_taken_twice(self):
		frappe.db.delete("TEX Integration Outbox", {"connection": self.conn.name})
		dist.mark_dirty(fx.PROPERTY, [self.std], fx.d(6, 10), fx.d(6, 10))
		first = dist.claim("ARI", 10)
		self.assertEqual(len(first), 1)
		self.assertEqual(dist.claim("ARI", 10), [])


class TestInbound(DistributionCase):
	def test_the_webhook_fails_closed(self):
		body = json.dumps(message()).encode()
		for headers in ({}, {"X-TEX-Timestamp": str(int(now_datetime().timestamp())), "X-TEX-Signature": "sha256=00"}):
			with self.assertRaises(frappe.PermissionError):
				dist.receive(self.conn.name, headers, body)
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "channel.webhook_rejected",
		                                                     "reference_name": self.conn.name}))
		self.assertFalse(frappe.db.exists("TEX Channel Inbound", {"connection": self.conn.name}))
		frappe.db.set_value("TEX Integration Connection", self.conn.name, "enabled", 0)
		with self.assertRaises(frappe.PermissionError):
			self.send(message())

	def test_new_modified_cancelled_applied_once(self):
		first = self.send(message())
		self.assertEqual(self.send(message()), {"received": 0, "duplicates": 1})     # the same message, once
		real = frappe.db.exists
		with mock.patch.object(frappe.db, "exists", side_effect=lambda dt, *a, **k: None
		                       if dt == "TEX Channel Inbound" else real(dt, *a, **k)):
			self.assertEqual(self.send(message()), {"received": 0, "duplicates": 1})  # ...even arriving at once
		self.assertEqual(first["received"], 1)
		out = self.apply_all()
		row = frappe.db.get_value("TEX Channel Inbound", {"provider_ref": "OTA-100"}, "name")
		self.assertTrue(dist.apply_inbound(row).get("skipped"))                     # a worker late to it does nothing
		b = frappe.get_doc("TEX Booking", out[0]["booking"])
		self.assertEqual((b.created_via, b.external_ref, b.status, D(str(b.total_amount))),
		                 ("Channel", "OTA-100", "Confirmed", D("450")))
		res = frappe.get_doc("Reservation", b.rooms[0].reservation)
		self.assertEqual((res.tex_pricing_source, res.tex_price_locked, res.tex_sales_channel, res.room_type),
		                 ("Channel", 1, "OTA", self.std))
		self.assertEqual(frappe.db.get_value("TEX Reservation Revision", {"reservation": res.name},
		                                     ["pricing_basis", "source"]), ("EXTERNAL", "Channel"))
		with self.assertRaises(frappe.ValidationError):                             # TEX never reprices it
			modification.propose(res.name, {"adults": 1})
		from kamra.tex.services import addons

		with self.assertRaisesRegex(frappe.ValidationError, "channel"):             # nor sells extras onto it
			addons.options(res.name, guest=False)
		self.send(message(status="modified", co=fx.d(6, 14), total="600.00"))
		self.apply_all()
		res.reload()
		self.assertEqual((str(res.check_out_date), D(str(res.tex_total_amount))), (str(fx.d(6, 14)), D("600")))
		self.send(message(status="modified", rooms=[
			{"room_code": "DBL", "rate_code": "BAR", "check_in": str(fx.d(6, 10)), "check_out": str(fx.d(6, 14)),
			 "adults": 2, "total": "600.00", "currency": "EUR", "line_ref": "L1"},
			{"room_code": "DBL", "rate_code": "BAR", "check_in": str(fx.d(6, 10)), "check_out": str(fx.d(6, 12)),
			 "adults": 1, "total": "200.00", "currency": "EUR", "line_ref": "L2"}]))
		self.apply_all()
		b.reload()
		self.assertEqual((len(b.rooms), D(str(b.total_amount))), (2, D("800")))
		self.send(message(status="cancelled", rooms=[]))
		self.apply_all()
		b.reload()
		self.assertEqual((b.status, {frappe.db.get_value("Reservation", r.reservation, "status") for r in b.rooms}),
		                 ("Cancelled", {"Cancelled"}))

	def test_an_unmapped_room_waits_for_its_mapping(self):
		self.send(message(ref="OTA-200", room="SUITE"))
		dist.process_inbound()
		row = frappe.db.get_value("TEX Channel Inbound", {"provider_ref": "OTA-200"},
		                          ["name", "status", "last_error"], as_dict=True)
		self.assertEqual(row.status, "Failed")
		self.assertIn("not mapped", row.last_error)
		frappe.get_doc({"doctype": "TEX Channel Mapping", "connection": self.conn.name, "room_type": self.std,
		                "external_room_code": "SUITE", "external_rate_code": "BAR", "board": "AI", "market": "DE",
		                "sales_channel": "OTA", "sell_currency": "EUR", "rate_plan": self.flex}).insert(ignore_permissions=True)
		dist_api.retry_inbound(row.name)
		self.assertEqual(dist.process_inbound()["applied"], 1)
		self.assertEqual(frappe.db.get_value("TEX Channel Inbound", row.name, "status"), "Applied")

	def test_an_overbooking_is_accepted_with_a_warning(self):
		from kamra.tex_commercial.doctype.tex_inventory_day.tex_inventory_day import inventory_day_name

		for i in range(3):
			d = fx.d(6, 10) + timedelta(days=i)
			frappe.get_doc({"doctype": "TEX Inventory Day", "name": inventory_day_name(self.std, d),
			                "property": fx.PROPERTY, "room_type": self.std, "inventory_date": d, "closed": 1}
			               ).insert(ignore_permissions=True)
		self.send(message(ref="OTA-300"))
		out = self.apply_all()
		self.assertTrue(out[0]["booking"] and "no room left" in (out[0]["warning"] or ""))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "channel.overbooking",
		                                                     "reference_name": out[0]["booking"]}))

	def test_a_bookings_messages_apply_in_order(self):
		self.send(message(ref="OTA-400"))
		self.send(message(ref="OTA-400", status="modified", total="500.00"))
		first = dist._claim_inbound(20)
		self.assertEqual(len([n for n in first if frappe.db.get_value("TEX Channel Inbound", n, "provider_ref")
		                      == "OTA-400"]), 1)
		self.apply_all()
		b = frappe.db.get_value("TEX Booking", {"external_ref": "OTA-400"}, "total_amount")
		self.assertEqual(D(str(b)), D("500"))
		self.send(message(ref="OTA-401", room="SUITE"))                              # fails: not mapped yet
		dist.process_inbound()
		self.send(message(ref="OTA-401", status="cancelled", rooms=[]))
		self.assertEqual(dist.process_inbound()["applied"], 0)                      # waits behind the failed one
		self.assertEqual(frappe.db.get_value("TEX Channel Inbound", {"provider_ref": "OTA-401", "event": "cancelled"},
		                                     "status"), "Received")

	def test_staff_apply_and_send_now_for_one_connection(self):
		other = frappe.get_doc({"doctype": "TEX Integration Connection", "label": "Sandbox 2", "property": fx.PROPERTY,
		                        "category": "Channel Manager", "adapter": "sandbox_channel", "environment": "Sandbox",
		                        "enabled": 1, "secret": SECRET}).insert(ignore_permissions=True)
		self.send(message(ref="OTA-800"))
		dist_api.sandbox_send(other.name, message(ref="OTA-801"))
		self.assertEqual(dist_api.apply_now(self.conn.name), {"applied": 1, "failed": 0})    # only its own
		self.assertEqual(frappe.db.get_value("TEX Channel Inbound", {"provider_ref": "OTA-801"}, "status"), "Received")
		frappe.get_doc({"doctype": "TEX Channel Mapping", "connection": other.name, "room_type": self.std,
		                "external_room_code": "DBL", "external_rate_code": "BAR", "board": "AI", "market": "DE",
		                "sales_channel": "OTA", "sell_currency": "EUR", "rate_plan": self.flex, "horizon_days": 365}
		               ).insert(ignore_permissions=True)
		frappe.db.delete("TEX Integration Outbox", {"kind": "ARI"})
		dist.mark_dirty(fx.PROPERTY, [self.std], fx.d(6, 10), fx.d(6, 11))
		self.assertEqual(dist_api.send_now(self.conn.name)["pushed"], 1)
		self.assertEqual(frappe.db.get_all("TEX Integration Outbox", filters={"connection": other.name, "kind": "ARI"},
		                                   pluck="status"), ["Pending"])                # the other one waits
		frappe.db.delete("TEX Integration Outbox", {"kind": "ARI"})
		self.assertEqual(dist_api.push_now(self.conn.name)["queued"], 1)              # this connection's mapping only
		self.assertFalse(frappe.db.exists("TEX Integration Outbox", {"connection": other.name, "kind": "ARI"}))

	def test_the_pms_hears_a_new_stay_as_created(self):
		pms = frappe.get_doc({"doctype": "TEX Integration Connection", "label": "PMS log", "property": fx.PROPERTY,
		                      "category": "PMS", "adapter": "log", "environment": "Sandbox", "enabled": 1}
		                     ).insert(ignore_permissions=True)
		self.send(message(ref="OTA-700"))
		self.apply_all()

		def events():
			return frappe.get_all("TEX Integration Outbox", filters={"connection": pms.name}, pluck="event",
			                      order_by="creation asc")

		self.assertEqual(events(), ["reservation.created"])
		self.send(message(ref="OTA-700", status="cancelled", rooms=[]))
		self.apply_all()
		self.assertEqual(events()[-1], "reservation.cancelled")
		self.assertFalse(frappe.db.exists("TEX Integration Outbox", {"connection": self.conn.name,
		                                                             "kind": "Reservation"}))  # a channel gets ARI


class TestReconcileAndTenancy(DistributionCase):
	def test_reconciliation_finds_drift_and_differences(self):
		frappe.db.delete("TEX Integration Outbox", {"connection": self.conn.name})
		self.mapping.db_set("horizon_days", 3)
		dist.mark_dirty(fx.PROPERTY)
		for j in self.jobs():
			dist.push_job(j)
		self.send(message(ref="OTA-500", ci=getdate(), co=getdate() + timedelta(days=2)))
		self.apply_all()
		for j in self.jobs():                                                       # the booking changed availability
			dist.push_job(j)
		self.assertEqual(dist.reconcile(self.conn.name), [])
		res = frappe.db.get_value("Reservation", {"ota_ref": "OTA-500-L1"})
		from kamra.tex.services import booking

		booking.cancel_reservation(res, reason="cancelled at the desk", waive_penalty=True)
		kinds = {m.kind for m in dist.reconcile(self.conn.name)}
		self.assertIn("status_differs", kinds)                                      # the channel still has it
		self.assertIn("ari_drift", kinds)                                           # a room came free, not pushed yet

	def test_everything_stays_inside_its_hotel(self):
		other_tenant()
		there = agent("g69-there@example.com", OTHER, "Hotel Admin")
		frappe.get_doc("User", there).add_roles("Hotel Admin")                      # may read the list in Desk
		frappe.set_user(there)  # nosemgrep: frappe-setuser -- another tenant's admin
		scope.clear_cache()
		for call in (lambda: dist_api.mappings(self.conn.name), lambda: dist_api.inbound(self.conn.name),
		             lambda: dist_api.push_now(self.conn.name), lambda: dist_api.reconcile(self.conn.name),
		             lambda: dist_api.save_mapping({"connection": self.conn.name, "room_type": self.std,
		                                            "external_room_code": "X", "external_rate_code": "Y"}),
		             lambda: dist_api.overview(fx.PROPERTY), lambda: dist_api.lookups(self.conn.name),
		             lambda: dist_api.ari_preview(self.mapping.name), lambda: dist_api.delete_mapping(self.mapping.name),
		             lambda: dist_api.sandbox_send(self.conn.name, message(ref="OTA-X")),
		             lambda: dist_api.apply_now(self.conn.name), lambda: dist_api.send_now(self.conn.name)):
			with self.assertRaises(frappe.PermissionError):
				call()
		self.assertNotIn(self.mapping.name, frappe.get_list("TEX Channel Mapping", pluck="name"))
		self.assertEqual(dist_api.overview(OTHER)["connections"], [])

	def test_a_mapping_is_closed_out_before_it_goes(self):
		frappe.db.delete("TEX Integration Outbox", {"connection": self.conn.name})
		self.mapping.db_set("horizon_days", 3)
		dist.mark_dirty(fx.PROPERTY, [self.std])
		dist.deliver_ari()
		self.assertEqual(frappe.db.count("TEX Channel ARI Day", {"mapping": self.mapping.name}), 3)
		with self.assertRaisesRegex(frappe.ValidationError, "Disable"):             # still selling
			dist_api.delete_mapping(self.mapping.name)
		dist_api.save_mapping({"name": self.mapping.name, "connection": self.conn.name, "enabled": 0})
		with self.assertRaisesRegex(frappe.ValidationError, "close-out"):           # not sent yet
			dist_api.delete_mapping(self.mapping.name)
		self.assertEqual(dist.deliver_ari()["pushed"], 1)
		m = frappe.get_doc("TEX Channel Mapping", self.mapping.name)
		self.assertTrue(all(fp == dist.closed_day(m, d).fingerprint()                # nothing left on sale
		                    for d, fp in dist.pushed_state(m.name, getdate(), getdate() + timedelta(days=2)).items()))
		dist_api.delete_mapping(self.mapping.name)
		self.assertFalse(frappe.db.exists("TEX Channel Mapping", self.mapping.name))
		self.assertFalse(frappe.db.exists("TEX Channel ARI Day", {"mapping": self.mapping.name}))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "channel.mapping_delete",
		                                                     "reference_name": self.mapping.name}))

	def test_connections_are_checked(self):
		look = dist_api.lookups(self.conn.name)
		self.assertTrue("AI" in look["boards"] and look["adapter"]["sandbox"] and look["room_types"])
		base = {"doctype": "TEX Integration Connection", "label": "x", "property": fx.PROPERTY,
		        "category": "Channel Manager", "enabled": 1}
		for bad in ({"adapter": "channex"}, {"adapter": "sandbox_channel", "environment": "Production"},
		            {"adapter": "sandbox_channel", "settings_json": json.dumps({"api_key": "k"})},
		            {"adapter": "sandbox_channel", "property": None},
		            {"adapter": "sandbox_channel", "endpoint_url": "http://insecure.example"}):
			with self.assertRaises(frappe.ValidationError, msg=str(bad)):
				frappe.get_doc({**base, **bad}).insert(ignore_permissions=True)
		conn = frappe.get_doc({**base, "adapter": "sandbox_channel", "api_key": "live-key-123"}
		                      ).insert(ignore_permissions=True)
		self.assertNotIn("live-key-123", str(frappe.db.get_value("TEX Integration Connection", conn.name, "api_key")))
		self.assertEqual(conn.get_password("api_key"), "live-key-123")
		other_tenant()
		self.conn.reload()
		self.conn.property = OTHER
		with self.assertRaisesRegex(frappe.ValidationError, "mappings"):          # its rooms are this hotel's
			self.conn.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):                             # history stays: disable it
			frappe.delete_doc("TEX Integration Connection", self.conn.name, ignore_permissions=True)
		with self.assertRaisesRegex(frappe.ValidationError, "sandbox"):             # simulating is sandbox-only
			conn.db_set("adapter", "log")
			dist_api.sandbox_send(conn.name, message(ref="OTA-Y"))

	def test_signing_helper_matches_the_webhook(self):
		body = json.dumps(message(ref="OTA-600")).encode()
		ts = int(now_datetime().timestamp())
		out = dist.receive(self.conn.name, {"X-TEX-Timestamp": str(ts),
		                                    "X-TEX-Signature": signing.sign(SECRET, ts, body)}, body)
		self.assertEqual(out["received"], 1)
		with mock.patch("kamra.tex.distribution.repository.now_datetime",
		                return_value=now_datetime() + timedelta(minutes=10)):
			with self.assertRaises(frappe.PermissionError):                         # a replayed old request
				dist.receive(self.conn.name, {"X-TEX-Timestamp": str(ts),
				                              "X-TEX-Signature": signing.sign(SECRET, ts, body)}, body)
