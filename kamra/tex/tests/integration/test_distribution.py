"""Channel distribution (G-69, ADR-039): ARI comes from TEX's own rules and only changes are
pushed; failures retry and park; the webhook fails closed; channel bookings are applied
once, in order, as the channel's sale (new / modified / cancelled, overbooking accepted
with a warning); reconciliation finds drift; everything stays inside its hotel."""

import json
from datetime import datetime, timedelta
from unittest import mock

import frappe
from frappe.utils import add_to_date, getdate, now_datetime

from kamra.tex.api import distribution as dist_api
from kamra.tex.availability import repository as avail
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

	def test_a_disabled_room_type_is_sent_closed_and_disabling_it_queues_a_sync(self):
		"""LO-03 (audit 2K-3, ADR-039): a disabled room type is no longer sold, so its enabled mapping sends every day
		closed with nothing available (before: open, with the pool's availability and rates), and disabling or
		enabling it queues its mappings' sync (before: nothing queued, the channel kept selling it)."""
		a, b = fx.d(6, 10), fx.d(6, 12)
		frappe.db.delete("TEX Integration Outbox", {"connection": self.conn.name})
		doc = frappe.get_doc("Room Type", self.std)
		doc.disabled = 1
		doc.save(ignore_permissions=True)
		self.assertEqual(len(self.jobs()), 1)
		self.assertEqual({(d.closed, d.available, d.rates) for d in dist.build_days(self.mapping, a, b)},
		                 {(True, 0, ())})
		frappe.db.delete("TEX Integration Outbox", {"connection": self.conn.name})
		doc.reload()
		doc.room_type_name = doc.room_type_name + " (renamed)"                          # no change of sale: no sync
		doc.save(ignore_permissions=True)
		self.assertEqual(self.jobs(), [])
		doc.disabled = 0
		doc.save(ignore_permissions=True)
		self.assertEqual(len(self.jobs()), 1)
		self.assertFalse(dist.build_days(self.mapping, a, a)[0].closed)

	def test_2o_a_mapping_of_a_disabled_room_type_is_not_saved_enabled(self):
		"""§6K3 "Not done" (batch 2O): a mapping of a room type TEX no longer sells could be saved enabled (it then sends
		every day closed). Making one enabled is refused; one enabled before its type was disabled stays editable (it
		keeps sending the close-out, LO-03), and disabling one is always allowed."""
		frappe.db.set_value("Room Type", self.std, "disabled", 1)
		try:
			new = {"connection": self.conn.name, "room_type": self.std, "external_room_code": "2O-DBL",
			       "external_rate_code": "2O-BAR", "board": "AI", "market": "DE", "sales_channel": "OTA",
			       "sell_currency": "EUR", "rate_plan": self.flex}
			with self.assertRaisesRegex(frappe.ValidationError, "no longer sold"):
				dist_api.save_mapping(new)
			self.assertTrue(dist_api.save_mapping({**new, "enabled": 0})["name"])                # saved disabled
			dist_api.save_mapping({"name": self.mapping.name, "connection": self.conn.name, "horizon_days": 30})
			dist_api.save_mapping({"name": self.mapping.name, "connection": self.conn.name, "enabled": 0})
			with self.assertRaisesRegex(frappe.ValidationError, "no longer sold"):
				dist_api.save_mapping({"name": self.mapping.name, "connection": self.conn.name, "enabled": 1})
			dlx = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "DLX"})
			dist_api.save_mapping({"name": self.mapping.name, "connection": self.conn.name, "room_type": dlx,
			                       "enabled": 1})
			with self.assertRaisesRegex(frappe.ValidationError, "no longer sold"):         # moved onto the disabled one
				dist_api.save_mapping({"name": self.mapping.name, "connection": self.conn.name, "room_type": self.std})
		finally:
			frappe.db.set_value("Room Type", self.std, "disabled", 0)

	def test_the_preview_starts_on_the_sites_day(self):
		# the push horizon starts on the site's day, so the preview does too: a browser in an earlier
		# time zone just after the site's midnight must not show yesterday as a day never sent
		out = dist_api.ari_preview(self.mapping.name, days=3)
		self.assertEqual(out["date_from"], str(getdate()))
		self.assertEqual([d["date"] for d in out["days"]],
		                 [str(getdate() + timedelta(days=i)) for i in range(3)])
		self.assertEqual(dist_api.ari_preview(self.mapping.name, date_from=str(fx.d(6, 10)), days=1)["date_from"],
		                 str(fx.d(6, 10)))

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

	def test_a_booking_for_a_suspended_contract_is_accepted_with_a_warning(self):
		# ADR-045: the channel sold the stay before the closed ARI reached it and the guest holds its
		# confirmation, so TEX accepts it like an overbooking: with a warning and an audit event
		from kamra.tex.commercial import contracts

		contract = frappe.db.get_value("TEX Contract", {"property": fx.PROPERTY, "contract_code": "PAY"})
		frappe.db.set_value("TEX Channel Mapping", self.mapping.name, "contract", contract)
		frappe.clear_document_cache("TEX Channel Mapping", self.mapping.name)
		contracts.set_status(contract, "suspend", "Overbooked")
		self.send(message(ref="OTA-310"))
		out = self.apply_all()
		self.assertTrue(out[0]["booking"])
		self.assertIn("suspended", (out[0]["warning"] or "").lower())
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "channel.overbooking",
		                                                     "reference_name": out[0]["booking"]}))

	def test_a_booking_for_a_disabled_room_type_is_accepted_with_a_warning(self):
		"""LO-03 (review round 1): a channel that sold a room type TEX no longer sells (before the closed ARI reached
		it, or while its connection is off) is accepted like an overbooking, with a warning and an audit event; so is a
		change moving a room into it (before: accepted silently)."""
		frappe.db.set_value("Room Type", self.std, "disabled", 1)
		self.send(message(ref="OTA-320"))
		out = self.apply_all()
		self.assertTrue(out[0]["booking"])
		self.assertIn("room type is no longer sold", out[0]["warning"] or "")
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "channel.overbooking",
		                                                     "reference_name": out[0]["booking"]}))
		frappe.db.set_value("Room Type", self.std, "disabled", 0)
		dlx = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "DLX"})
		frappe.get_doc({"doctype": "TEX Channel Mapping", "connection": self.conn.name, "room_type": dlx,
		                "external_room_code": "DLXC", "external_rate_code": "BAR", "board": "AI", "market": "DE",
		                "sales_channel": "OTA", "sell_currency": "EUR", "rate_plan": self.flex, "occupancies": "1,2",
		                "horizon_days": 365}).insert(ignore_permissions=True)
		self.send(message(ref="OTA-321"))
		self.assertTrue(self.apply_all()[0]["booking"])
		frappe.db.set_value("Room Type", dlx, "disabled", 1)
		self.send(message(ref="OTA-321", status="modified", room="DLXC"))   # the channel moves the room into it
		moved = self.apply_all()
		self.assertIn("room type is no longer sold", moved[0]["warning"] or "")

	def test_a_channel_change_locks_the_booking_first_and_voids_a_waiting_guest_change(self):
		"""G-45 re-review F8: the channel's modification and cancellation take the booking, then the
		reservation, then the nights (the order every change to a TEX booking takes), and a guest
		change still waiting for the room is void (a payment of it arriving later is refunded)."""
		from kamra.tex.tests.integration.test_self_service_money import locks_during

		self.send(message(ref="OTA-900"))
		b = frappe.get_doc("TEX Booking", self.apply_all()[0]["booking"])
		res = b.rooms[0].reservation

		def waiting(key):
			return frappe.get_doc({"doctype": "TEX Guest Change Request", "property": fx.PROPERTY, "booking": b.name,
			                       "reservation": res, "status": "Awaiting Payment", "proposal_hash": key,
			                       "proposal": "{}", "currency": "EUR", "attempt": 0}).insert(ignore_permissions=True)

		for msg in (message(ref="OTA-900", status="modified", co=fx.d(6, 14), total="600.00"),
		            message(ref="OTA-900", status="cancelled", rooms=[])):
			with self.subTest(status=msg["status"]):
				gcr = waiting(f"gcm-channel-{msg['status']}")
				self.send(msg)
				seen = locks_during(self.apply_all)
				booking_at = seen.index("tabTEX Booking")
				for table in ("tabReservation", "tabTEX Inventory Day"):
					if table in seen:
						self.assertLess(booking_at, seen.index(table), f"{table} locked before the booking: {seen}")
				self.assertEqual(frappe.db.get_value("TEX Guest Change Request", gcr.name, "status"), "Superseded")
		self.assertEqual(frappe.db.get_value("Reservation", res, "status"), "Cancelled")

	def test_a_channel_change_locks_its_rooms_before_their_nights(self):
		"""G-45 re-review 3: a desk or PMS save of a reservation locks the reservation, then its
		nights; the channel's modification takes them in the same order (after the booking)."""
		from kamra.tex.tests.integration.test_self_service_money import locks_during

		self.send(message(ref="OTA-910"))
		self.apply_all()
		self.send(message(ref="OTA-910", status="modified", co=fx.d(6, 14), total="600.00"))
		seen = locks_during(self.apply_all)
		self.assertLess(seen.index("tabTEX Booking"), seen.index("tabReservation"), seen)
		self.assertLess(seen.index("tabReservation"), seen.index("tabTEX Inventory Day"), seen)

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


class TestChannelBookings(DistributionCase):
	"""Y-8 (audit 2F-2, D-11, ADR-039): a room the channel brings back is applied; an OTA booking is the channel's, so
	it is cancelled at the desk only by someone who manages the channel, with a reason, on record."""

	def line(self, ref: str, check_out=None, total="450.00") -> dict:
		return {"room_code": "DBL", "rate_code": "BAR", "check_in": str(fx.d(6, 10)),
		        "check_out": str(check_out or fx.d(6, 13)), "adults": 2, "total": total, "currency": "EUR",
		        "line_ref": ref}

	def process(self) -> dict:
		"""The queue as the scheduler runs it: a failed message is counted, never raised."""
		return dist.process_inbound(connection=self.conn.name)

	def free(self, night) -> int:
		count, _per = avail.stay_availability(fx.PROPERTY, self.std, None, night, night + timedelta(days=1), getdate())
		return count

	def booked(self, *refs: str):
		"""The channel's booking OTA-100 with the lines ``refs``, applied: → (booking, {line: reservation})."""
		self.send(message(rooms=[self.line(r) for r in refs]))
		self.assertEqual(self.process(), {"applied": 1, "failed": 0})
		b = frappe.get_doc("TEX Booking", {"external_ref": "OTA-100"})
		return b.name, {r: frappe.db.get_value("Reservation", {"ota_ref": f"OTA-100-{r}"}) for r in refs}

	def staff(self, email: str, role: str, profile: str | None = None) -> str:
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- grants are made by an administrator
		user = fx.ensure_user(email, [role])
		if profile:
			fx.ensure("TEX Access Grant", {"user": user, "property": fx.PROPERTY},
			          {"user": user, "scope_level": "Hotel", "property": fx.PROPERTY, "permission_profile": profile})
		scope.clear_cache()
		return user

	def test_a_room_the_channel_brings_back_is_applied(self):
		"""The channel takes a room off and puts it back (and moves the other): the cancelled room is a live
		stay again, its cancellation cleared, the booking Confirmed, a night less free — and nothing fails."""
		booking_name, rooms = self.booked("L1", "L2")
		l1, l2 = rooms["L1"], rooms["L2"]
		self.send(message(status="modified", rooms=[self.line("L1")]))                  # the channel removes L2
		self.assertEqual(self.process(), {"applied": 1, "failed": 0})
		self.assertEqual(frappe.db.get_value("Reservation", l2, "status"), "Cancelled")
		free_without = self.free(fx.d(6, 10))
		self.send(message(status="modified", rooms=[self.line("L1", check_out=fx.d(6, 14), total="600.00"),
		                                            self.line("L2")]))                  # ... and brings it back
		self.assertEqual(self.process(), {"applied": 1, "failed": 0})
		back = frappe.db.get_value("Reservation", l2, ["status", "cancellation_reason", "cancellation_note",
		                                               "cancelled_on", "cancellation_fee", "tex_hold_expired"],
		                           as_dict=True)
		self.assertEqual((back.status, back.cancellation_reason, back.cancellation_note, back.cancelled_on,
		                  back.cancellation_fee, back.tex_hold_expired), ("Confirmed", None, None, None, 0, 0))
		self.assertEqual(str(frappe.db.get_value("Reservation", l1, "check_out_date")), str(fx.d(6, 14)))
		self.assertEqual(frappe.db.get_value("TEX Booking", booking_name, "status"), "Confirmed")
		self.assertEqual(self.free(fx.d(6, 10)), free_without - 1)
		audit = frappe.get_all("TEX Audit Event", filters={"action": "channel.booking_modified",
		                                                   "reference_name": booking_name}, pluck="new_value",
		                       order_by="creation desc")
		self.assertEqual(json.loads(audit[0])["reactivated"], [l2])
		revision = frappe.get_all("TEX Reservation Revision", filters={"reservation": l2}, pluck="changes_json",
		                          order_by="creation desc")
		self.assertEqual(json.loads(revision[0])["status"], ["Cancelled", "Confirmed"])

	def test_a_room_the_channel_brings_back_into_a_disabled_type_is_warned(self):
		"""LO-03 review round 2: a room the channel had taken off and brings back is a new sale: in a type disabled
		meanwhile it is accepted with the warning (before: only a change of room type warned)."""
		self.booked("L1", "L2")
		self.send(message(status="modified", rooms=[self.line("L1")]))                  # the channel removes L2
		self.assertEqual(self.process(), {"applied": 1, "failed": 0})
		frappe.db.set_value("Room Type", self.std, "disabled", 1)
		self.send(message(status="modified", rooms=[self.line("L1"), self.line("L2")]))  # ... and brings it back
		back = self.apply_all()
		self.assertIn("room type is no longer sold", back[0]["warning"] or "")
		self.assertEqual(back[0]["warning"].count("room type is no longer sold"), 1)   # L1 was never off: no warning

	def test_an_ota_booking_is_cancelled_at_the_desk_only_by_someone_who_manages_the_channel(self):
		from kamra.tex.api import crs as crs_api

		_booking, rooms = self.booked("L1")
		res = rooms["L1"]
		with self.assertRaisesRegex(frappe.ValidationError, "cancel it on the channel"):
			crs_api.cancel(reservation=res, reason="the guest phoned")
		self.assertEqual(frappe.db.get_value("Reservation", res, "status"), "Confirmed")
		desk = self.staff("y8-desk@example.com", "Call Center Agent", "Reservations Agent")  # may cancel, not the channel
		frappe.set_user(desk)  # nosemgrep: frappe-setuser -- a call-centre agent
		with self.assertRaises(frappe.PermissionError):
			crs_api.cancel(reservation=res, reason="the guest phoned", channel_override=1)
		self.assertEqual(frappe.db.get_value("Reservation", res, "status"), "Confirmed")
		admin = self.staff("y8-admin@example.com", "Hotel Admin", "Hotel Admin")
		frappe.set_user(admin)  # nosemgrep: frappe-setuser -- the hotel's administrator
		preview = crs_api.cancellation_preview(reservation=res)
		self.assertEqual(preview["channel"], {"connection": self.conn.name, "label": "Sandbox CM", "ref": "OTA-100"})
		crs_api.cancel(reservation=res, reason="the guest phoned the hotel", channel_override=1)
		self.assertEqual(frappe.db.get_value("Reservation", res, "status"), "Cancelled")
		warned = frappe.get_all("TEX Audit Event", filters={"action": "reservation.channel_cancel_override",
		                                                    "reference_name": res}, pluck="new_value")
		self.assertEqual(len(warned), 1)
		self.assertIn("OTA-100", warned[0])

	def test_the_channel_is_named_by_its_label_never_its_id(self):
		"""LO-13 (audit 2K-3): a refusal, the cancel dialog and the reservation name the channel connection by its
		label (before: "Sold by CON-0001", also on the guest's manage page); the audit keeps its id."""
		from kamra.tex.api import crs as crs_api

		_booking, rooms = self.booked("L1")
		res = rooms["L1"]
		with self.assertRaises(frappe.ValidationError) as caught:
			crs_api.cancel(reservation=res, reason="the guest phoned")
		self.assertIn("Sold by Sandbox CM", str(caught.exception))
		self.assertNotIn(self.conn.name, str(caught.exception))
		named = {"connection": self.conn.name, "label": "Sandbox CM", "ref": "OTA-100"}
		self.assertEqual(crs_api.cancellation_preview(reservation=res)["channel"], named)
		self.assertEqual(crs_api.reservation(res)["channel_booking"], named)
		self.conn.db_set("label", "")                                                  # no label: its name
		self.assertEqual(crs_api.cancellation_preview(reservation=res)["channel"]["label"], self.conn.name)

	def test_the_booking_e_mail_of_a_channels_booking_is_never_sent_again(self):
		"""LO-11 (audit 2K-3, D-11): the channel sends its booking's confirmation, and TEX never e-mails it (its price
		is the channel's): staff's "resend" is refused and no manage link is minted (before: a new manage token and
		an e-mail whose page offered Cancel and Change, which the server then refuses)."""
		from kamra.tex.api import crs as crs_api

		booking_name, _rooms = self.booked("L1")
		before = frappe.db.get_value("TEX Booking", booking_name, "manage_token_hash")
		with self.assertRaisesRegex(frappe.ValidationError, "Sandbox CM sends"):
			crs_api.resend_confirmation(booking_name)
		self.assertEqual(frappe.db.get_value("TEX Booking", booking_name, "manage_token_hash"), before)
		self.assertFalse(frappe.db.exists("TEX Audit Event", {"action": "booking.confirmation_resent",
		                                                      "reference_name": booking_name}))

	def test_a_guest_booking_has_no_channel(self):
		"""Only an OTA booking is the channel's: the preview of a TEX booking names none."""
		from kamra.tex.api import crs as crs_api
		from kamra.tex.tests.integration.test_commercial_flows import guest_books

		res = guest_books(session="y8-own")["rooms"][0]["reservation"]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff
		self.assertIsNone(crs_api.cancellation_preview(reservation=res)["channel"])
		self.assertIsNone(crs_api.reservation(res)["channel_booking"])

	def test_the_guest_page_of_a_channels_booking_refuses_by_code(self):
		"""G-70b: the guest's page refuses to cancel, change or add extras to a channel's booking with CHANNEL_BOOKING,
		and names the channel by its label (params ``sold_by``), never the connection's id."""
		from kamra.tex.api import public

		booking_name, rooms = self.booked("L1")
		res = rooms["L1"]
		token = public.resume_token(booking_name)        # a guest who still holds a link to the booking
		saved, frappe.local.response = frappe.local.response, frappe._dict({"docs": []})
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest's booking page
		try:
			for call in (lambda: public.manage_cancel(token=token, reservation=res),
			             lambda: public.manage_propose(token=token, reservation=res,
			                                           changes={"check_out": str(fx.d(6, 14))}),
			             lambda: public.manage_extras(token=token, reservation=res)):
				with self.assertRaises(frappe.ValidationError) as cm:
					call()
				self.assertEqual((cm.exception.code, frappe.local.response["tex_code"]),
				                 ("CHANNEL_BOOKING", "CHANNEL_BOOKING"))
				self.assertEqual(frappe.local.response["tex_params"], {"sold_by": "Sandbox CM"})
				self.assertNotIn(self.conn.name, str(cm.exception))
				frappe.clear_messages()
		finally:
			frappe.local.response = saved
		self.assertEqual(frappe.db.get_value("Reservation", res, "status"), "Confirmed")

	def test_staff_retry_only_the_latest_message_of_a_booking(self):
		"""A dead old message retried after a newer one was applied would put the booking back as it was."""
		self.send(message())
		self.process()
		self.send(message(status="modified", co=fx.d(6, 14), total="600.00"))
		self.process()
		old, newer = frappe.get_all("TEX Channel Inbound", filters={"connection": self.conn.name,
		                                                          "provider_ref": "OTA-100"},
		                            pluck="name", order_by="creation asc")
		frappe.db.set_value("TEX Channel Inbound", old, "status", "Dead", update_modified=False)
		with self.assertRaisesRegex(frappe.ValidationError, "newer message"):
			dist_api.retry_inbound(old)
		self.assertEqual(frappe.db.get_value("TEX Channel Inbound", old, "status"), "Dead")
		frappe.db.set_value("TEX Channel Inbound", newer, "status", "Failed", update_modified=False)
		self.assertEqual(dist_api.retry_inbound(newer), {"ok": True})            # the latest one may be retried

	def club(self) -> str:
		from kamra.tex.api import loyalty as loyalty_api
		from kamra.tex.tests.integration.test_loyalty_admin import CLUB

		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the hotel's loyalty program
		return loyalty_api.save_program({**CLUB, "property": fx.PROPERTY})["name"]

	def holding(self, guest: str, program: str, points: int = 1000) -> None:
		frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": program, "guest": guest, "entry_type": "Adjust",
		                "points": points, "status": "Available", "reason": "lo02"}).insert(ignore_permissions=True)

	def test_points_never_pay_a_channel_booking(self):
		"""LO-02 (audit 2K-2, D-11): an OTA booking's price and payment are the channel's: points are never redeemed
		on it, and a payment made with points is never moved onto it."""
		from kamra.tex.crm import loyalty
		from kamra.tex.payments import service as pay

		program = self.club()
		booking, _rooms = self.booked("L1")
		guest = frappe.db.get_value("TEX Booking", booking, "booker_guest")
		self.holding(guest, program)
		with self.assertRaisesRegex(frappe.ValidationError, "channel"):
			loyalty.redeem(guest, booking, 300, idempotency_key="lo02-redeem")
		self.assertFalse(frappe.db.exists("TEX Payment Transaction", {"booking": booking, "provider": "Loyalty"}))
		self.assertEqual(loyalty.balances(guest, program)["available"], 1000)
		points = pay._new_txn(property=fx.PROPERTY, txn_type="Charge", method="Manual", amount=30, currency="EUR",
		                      provider="Loyalty", idempotency_key="lo02-points")
		frappe.db.set_value("TEX Payment Transaction", points.name, "status", "Succeeded", update_modified=False)
		with self.assertRaisesRegex(frappe.ValidationError, "channel"):
			pay.allocate(points.name, booking=booking, amount="30", reason="move the points")
		self.assertFalse(frappe.db.exists("TEX Payment Allocation", {"transaction": points.name}))

	def test_2o_the_crm_says_which_stay_is_a_channels(self):
		"""§6K2 "Not done" (batch 2O): the CRM offered "Redeem" on a channel's booking, which the server refuses
		(LO-02). Each stay the profile lists says whether its booking is a channel's, so the screen leaves it out."""
		from kamra.tex.api import crm as crm_api

		booking, _rooms = self.booked("L1")
		guest = frappe.db.get_value("TEX Booking", booking, "booker_guest")
		stays = crm_api.guest(name=guest)["stays"]
		self.assertTrue(stays)
		self.assertEqual({(s["tex_booking"], s["channel_booking"]) for s in stays}, {(booking, True)})

	def test_a_channel_cancellation_gives_the_points_back(self):
		"""LO-02 (D-16): points spent on a booking a channel later cancels come back as points (before: lost, their
		money left on the cancelled booking). Spent before the guard (an older booking)."""
		from kamra.tex.crm import loyalty
		from kamra.tex.money import from_db

		program = self.club()
		booking, _rooms = self.booked("L1")
		guest = frappe.db.get_value("TEX Booking", booking, "booker_guest")
		self.holding(guest, program)
		conn = frappe.db.get_value("TEX Booking", booking, "channel_connection")
		frappe.db.set_value("TEX Booking", booking, "channel_connection", None, update_modified=False)
		spent = loyalty.redeem(guest, booking, 300, idempotency_key="lo02-old")
		frappe.db.set_value("TEX Booking", booking, "channel_connection", conn, update_modified=False)
		self.assertEqual(loyalty.balances(guest, program)["available"], 700)
		self.send(message(status="cancelled"))
		self.assertEqual(self.process(), {"applied": 1, "failed": 0})
		self.assertEqual(frappe.db.get_value("TEX Booking", booking, "status"), "Cancelled")
		self.assertEqual(loyalty.balances(guest, program)["available"], 1000)
		self.assertEqual(from_db(frappe.db.get_value("TEX Booking", booking, "paid_amount"), "EUR"), D("0.00"))
		back = frappe.get_all("TEX Payment Transaction", filters={"parent_transaction": spent["transaction"]},
		                      fields=["amount", "raw_status"])
		self.assertEqual([(D(r.amount), r.raw_status) for r in back], [(D("30.00"), "POINTS RETURNED")])
		self.assertEqual(frappe.db.count("TEX Loyalty Ledger", {"guest": guest, "entry_type": "Adjust"}), 1)

	def test_a_room_the_channel_removes_gives_the_points_over_back(self):
		"""LO-02 (D-16, review round 1): the channel takes one of two rooms off: what the booking now holds over its
		price comes back as points first (20.00 of the 30.00 points), the cash paid stays, the stay kept."""
		from kamra.tex.crm import loyalty
		from kamra.tex.money import from_db
		from kamra.tex.payments import service as pay

		program = self.club()
		booking, rooms = self.booked("L1", "L2")                                       # 900.00
		guest = frappe.db.get_value("TEX Booking", booking, "booker_guest")
		self.holding(guest, program)
		conn = frappe.db.get_value("TEX Booking", booking, "channel_connection")
		frappe.db.set_value("TEX Booking", booking, "channel_connection", None, update_modified=False)
		spent = loyalty.redeem(guest, booking, 300, idempotency_key="lo02-two")      # 30.00, spent before the guard
		frappe.db.set_value("TEX Booking", booking, "channel_connection", conn, update_modified=False)
		pay.record_manual(booking=booking, amount="440.00", method="Cash", reference="desk",
		                  idempotency_key="lo02-two-cash")                            # 470.00 paid
		self.send(message(status="modified", rooms=[self.line("L1")]))                  # the channel removes L2: 450.00
		self.assertEqual(self.process(), {"applied": 1, "failed": 0})
		self.assertEqual((frappe.db.get_value("Reservation", rooms["L1"], "status"),
		                  frappe.db.get_value("Reservation", rooms["L2"], "status")), ("Confirmed", "Cancelled"))
		self.assertEqual(loyalty.balances(guest, program)["available"], 900)
		back = frappe.get_all("TEX Payment Transaction", filters={"parent_transaction": spent["transaction"]},
		                      fields=["amount", "raw_status"])
		self.assertEqual([(D(r.amount), r.raw_status) for r in back], [(D("20.00"), "POINTS RETURNED")])
		total, paid = frappe.db.get_value("TEX Booking", booking, ["total_amount", "paid_amount"])
		self.assertEqual((from_db(total, "EUR"), from_db(paid, "EUR")), (D("450.00"), D("450.00")))


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

		booking.cancel_reservation(res, reason="cancelled at the desk", waive_penalty=True, channel_override=True)
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


class TestPmsDelivery(TexTestCase):
	"""G-90: the PMS outbox never delivers through an uncertified adapter to a Production
	connection, even one whose environment was changed behind the controller's back."""

	def test_an_uncertified_adapter_never_delivers_in_production(self):
		from kamra.tex.connect import adapters, outbox
		from kamra.tex.tests.integration.test_commercial_flows import guest_books

		setup_site_and_payments(self.f)
		pms = frappe.get_doc({"doctype": "TEX Integration Connection", "label": "PMS log", "property": fx.PROPERTY,
		                      "category": "PMS", "adapter": "log", "environment": "Sandbox", "enabled": 1}
		                     ).insert(ignore_permissions=True)
		pms.db_set("environment", "Production")                 # e.g. changed in SQL: the controller never saw it
		booked = guest_books(session="g90-pms")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the scheduler
		queued = frappe.get_all("TEX Integration Outbox", filters={"connection": pms.name, "kind": "Reservation"},
		                        pluck="name")
		self.assertTrue(queued)
		adapters.LogOnlyPMS.delivered.clear()
		dist._each(dist.claim("Reservation", 50, connection=pms.name), outbox._deliver, outbox._failed)
		for name in queued:
			row = frappe.db.get_value("TEX Integration Outbox", name, ["status", "last_error", "attempts"], as_dict=True)
			self.assertEqual((row.status, row.attempts), ("Dead", 1), row)          # no retry would ever help
			self.assertIn("not certified for production", row.last_error)
		reservations = {r for _e, r in adapters.LogOnlyPMS.delivered}
		self.assertFalse(reservations & {x["reservation"] for x in booked["rooms"]})  # nothing was delivered
		self.assertEqual(frappe.db.get_value("TEX Integration Connection", pms.name, "last_status"), "Dead")

	# ─── NEW-7 (2F-1): a time budget, and order per reservation ──────────────

	def pms(self):
		setup_site_and_payments(self.f)
		return frappe.get_doc({"doctype": "TEX Integration Connection", "label": "PMS order", "property": fx.PROPERTY,
		                       "category": "PMS", "adapter": "log", "environment": "Sandbox", "enabled": 1}
		                      ).insert(ignore_permissions=True)

	def rows(self, conn, reservation: str | None = None) -> list:
		"""The connection's reservation messages, oldest first."""
		filters = {"connection": conn.name, "kind": "Reservation"}
		if reservation:
			filters["reference_name"] = reservation
		return frappe.get_all("TEX Integration Outbox", filters=filters, order_by="creation asc, name asc",
		                      fields=["name", "event", "status", "attempts", "claim_token", "claimed_until",
		                              "next_attempt_at", "reference_name"])

	def booked_and_cancelled(self, session: str):
		"""→ (connection, reservation, its messages oldest first: created … cancelled)."""
		from kamra.tex.api import crs as crs_api
		from kamra.tex.tests.integration.test_commercial_flows import guest_books

		conn = self.pms()
		res = guest_books(session=session)["rooms"][0]["reservation"]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff cancel it, the scheduler delivers
		crs_api.cancel(reservation=res, reason="the guest phoned")
		rows = self.rows(conn, res)
		self.assertEqual((rows[0].event, rows[-1].event), ("reservation.created", "reservation.cancelled"))
		return conn, res, rows

	def test_a_run_stops_starting_messages_when_its_time_budget_is_used(self):
		"""A PMS that answers slowly cannot hold a run past its budget: the messages it did not start are given
		back (no claim, still Pending, no attempt counted) for the next run."""
		from kamra.tex.connect import adapters, outbox
		from kamra.tex.tests.integration.test_commercial_flows import guest_books

		conn = self.pms()
		for n in range(3):
			guest_books(session=f"p20-budget-{n}")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the scheduler
		self.assertEqual([r.event for r in self.rows(conn)], ["reservation.created"] * 3)

		class Clock:                                            # every delivery takes 50 seconds
			now = 1000.0

			def monotonic(self):
				return self.now

		clock, real = Clock(), outbox._deliver

		def slow_deliver(name, token=None):
			real(name, token)
			clock.now += 50

		adapters.LogOnlyPMS.delivered.clear()
		with mock.patch.object(outbox, "time", clock), mock.patch.object(dist, "time", clock), \
				mock.patch.object(outbox, "_deliver", slow_deliver):
			out = outbox.deliver_pending(limit=50, budget_seconds=60)
		self.assertEqual((out["sent"], out["failed"]), (2, 0))
		first, second, third = self.rows(conn)
		self.assertEqual((first.status, second.status), ("Sent", "Sent"))
		self.assertEqual((third.status, third.attempts, third.claim_token, third.claimed_until),
		                 ("Pending", 0, None, None))
		with mock.patch.object(outbox, "time", clock), mock.patch.object(dist, "time", clock):   # a new run, a new budget
			self.assertEqual(outbox.deliver_pending(limit=50, budget_seconds=60)["sent"], 1)
		self.assertEqual(self.rows(conn)[2].status, "Sent")

	def test_a_failed_message_holds_back_the_later_ones_of_its_reservation(self):
		"""A "modified" waiting in back-off must never be sent after a "cancelled" that came later (a phantom
		arrival at the PMS): the cancellation waits for it, and both go in order once it may be sent."""
		from kamra.tex.connect import adapters, outbox

		conn, res, rows = self.booked_and_cancelled("p20-order")
		frappe.db.set_value("TEX Integration Outbox", rows[0].name, {
			"status": "Failed", "attempts": 1, "next_attempt_at": add_to_date(now_datetime(), minutes=10)},
			update_modified=False)
		adapters.LogOnlyPMS.delivered.clear()
		self.assertEqual(outbox.deliver_pending()["sent"], 0)
		self.assertEqual(adapters.LogOnlyPMS.delivered, [])      # nothing: the later messages wait for the first
		frappe.db.set_value("TEX Integration Outbox", rows[0].name, "next_attempt_at",
		                    add_to_date(now_datetime(), minutes=-1), update_modified=False)
		self.assertEqual(outbox.deliver_pending()["sent"], len(rows))
		self.assertEqual(adapters.LogOnlyPMS.delivered, [(r.event.split(".")[1], res) for r in rows])
		self.assertEqual({r.status for r in self.rows(conn, res)}, {"Sent"})

	def test_a_dead_message_never_blocks_the_next_ones(self):
		from kamra.tex.connect import adapters, outbox

		conn, res, rows = self.booked_and_cancelled("p20-dead")
		frappe.db.set_value("TEX Integration Outbox", rows[0].name, {"status": "Dead", "attempts": outbox.MAX_ATTEMPTS},
		                    update_modified=False)
		adapters.LogOnlyPMS.delivered.clear()
		self.assertEqual(outbox.deliver_pending()["sent"], len(rows) - 1)
		self.assertEqual(adapters.LogOnlyPMS.delivered, [(r.event.split(".")[1], res) for r in rows[1:]])
		self.assertEqual(self.rows(conn, res)[0].status, "Dead")

	def test_a_round_reads_at_most_its_cap_however_many_wait_in_back_off(self):
		"""LO-10 (2K-4): a long PMS outage leaves thousands of messages in back-off, and a round read every
		undelivered message (all connections) to find each reservation's first. It now reads only the first messages
		that are due and free, at most the round's cap, oldest first; a later message of a reservation whose first
		waits in back-off is still never claimed."""
		from kamra.tex.connect import outbox

		conn = self.pms()
		now, start = now_datetime(), datetime(2000, 1, 1)
		later, earlier = add_to_date(now, minutes=30), add_to_date(now, minutes=-1)
		fields = ["name", "creation", "modified", "owner", "modified_by", "docstatus", "kind", "connection", "property",
		          "event", "status", "attempts", "next_attempt_at", "reference_doctype", "reference_name",
		          "idempotency_key", "payload"]

		def row(name, n, status, due_at, reservation):
			at = start + timedelta(seconds=n)
			return (name, at, at, "Administrator", "Administrator", 0, "Reservation", conn.name, fx.PROPERTY,
			        "reservation.modified", status, 1 if status == "Failed" else 0, due_at, "Reservation", reservation,
			        f"lo10-{name}", "{}")

		# 1,000 reservations whose first message waits in back-off and whose second is due (held back by the first)
		values = []
		for i in range(1000):
			values.append(row(f"lo10-wait-{i}", 2 * i, "Failed", later, f"LO10-RES-{i}"))
			values.append(row(f"lo10-held-{i}", 2 * i + 1, "Pending", earlier, f"LO10-RES-{i}"))
		# three reservations whose only message is due, written after them
		due = [f"lo10-due-{i}" for i in range(3)]
		values += [row(name, 5000 + i, "Pending", earlier, f"LO10-DUE-{i}") for i, name in enumerate(due)]
		frappe.db.bulk_insert("TEX Integration Outbox", fields, values)

		reads, real_sql = [], frappe.db.sql

		def sniff(query, *a, **kw):
			out = real_sql(query, *a, **kw)
			if query.lstrip().upper().startswith("SELECT") and "tabTEX Integration Outbox" in query:
				reads.append(len(out))
			return out

		with mock.patch.object(frappe.db, "sql", sniff):
			claimed = outbox._claim(2, "lo10-round")
		self.assertEqual(claimed, due[:2])                      # FIFO: the two oldest that may go
		self.assertTrue(reads)
		self.assertLessEqual(max(reads), 2, reads)              # never the 2,000 in back-off
		with mock.patch.object(frappe.db, "sql", sniff):
			self.assertEqual(outbox._claim(50, "lo10-next"), due[2:])   # the held-back ones stay unclaimed

	def test_a_message_another_worker_reclaimed_is_not_sent(self):
		"""Each message is read again just before it is sent: one that is no longer this run's (its claim lapsed
		and another worker took it) or that is already sent is skipped."""
		from kamra.tex.connect import adapters, outbox
		from kamra.tex.tests.integration.test_commercial_flows import guest_books

		conn = self.pms()
		guest_books(session="p20-claim")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the scheduler
		row = self.rows(conn)[0]
		frappe.db.set_value("TEX Integration Outbox", row.name, {
			"claim_token": "worker-b", "claimed_until": add_to_date(now_datetime(), minutes=10)}, update_modified=False)
		adapters.LogOnlyPMS.delivered.clear()
		outbox._deliver(row.name, token="worker-a")
		self.assertEqual(adapters.LogOnlyPMS.delivered, [])
		self.assertEqual(frappe.db.get_value("TEX Integration Outbox", row.name, ["status", "claim_token"]),
		                 ("Pending", "worker-b"))
		outbox._deliver(row.name, token="worker-b")             # the one that holds it sends it
		self.assertEqual(len(adapters.LogOnlyPMS.delivered), 1)
		outbox._deliver(row.name)                                # already sent: never again, whoever asks
		self.assertEqual(len(adapters.LogOnlyPMS.delivered), 1)

	def test_staff_retry_only_the_latest_message_of_a_reservation(self):
		"""A dead "created" retried after a newer message was sent would put the stay back as it was: staff retry
		the latest, which carries the full state."""
		from kamra.tex.api import admin

		_conn, _res, rows = self.booked_and_cancelled("p20-retry")
		old, latest = rows[0], rows[-1]
		for r in rows:
			frappe.db.set_value("TEX Integration Outbox", r.name, {"status": "Dead", "attempts": 8}, update_modified=False)
		frappe.db.set_value("TEX Integration Outbox", latest.name, "status", "Sent", update_modified=False)
		with self.assertRaisesRegex(frappe.ValidationError, "newer message"):
			admin.retry_outbox(old.name)
		self.assertEqual(frappe.db.get_value("TEX Integration Outbox", old.name, "status"), "Dead")
		frappe.db.set_value("TEX Integration Outbox", latest.name, "status", "Dead", update_modified=False)
		self.assertEqual(admin.retry_outbox(latest.name), {"ok": True})
		self.assertEqual(frappe.db.get_value("TEX Integration Outbox", latest.name, ["status", "attempts"]), ("Pending", 0))

	def test_a_run_goes_on_after_a_deadlock_ended_its_savepoint(self):
		"""A deadlock rolls the transaction back whole, and the item's savepoint with it: the rollback to it fails
		(MariaDB 1305) and used to end the loop, leaving the claimed rows to wait out their lease. The loop now
		rolls back whole, records the failure and goes on (this also holds for ``apply_now`` and the ARI push)."""
		seen, failed = [], []

		def work(name):
			if name == "first":
				frappe.db.rollback()                              # a deadlock victim's transaction is gone
				raise frappe.QueryDeadlockError("Deadlock found when trying to get lock")
			seen.append(name)

		done = dist._each(["first", "second"], work, lambda name, e: failed.append((name, type(e).__name__)))
		self.assertEqual((done, seen, failed), ((1, 1), ["second"], [("first", "QueryDeadlockError")]))
