"""G-73 (R-05): a price-locked snapshot refers to the frozen payload that priced it (ADR-058).

The snapshot keeps its contract version's periods and rules as a reference (version and payload
hash), not as a copy. The reference is safe only if it is checked: every reprice, simulation or
add-on that loads the snapshot's version refuses, audited, unless the payload still hashes to what
the sale recorded. The snapshot says when it was priced (``priced_at``, the quote's sale time),
next to when it was accepted. Snapshots written before these keys keep repricing.
"""

import json
from unittest import mock

import frappe
from frappe.utils import get_datetime

from kamra.tex.commercial import contracts
from kamra.tex.money import D
from kamra.tex.pricing import serialize
from kamra.tex.security import audit as audit_mod
from kamra.tex.services import addons as addon_svc
from kamra.tex.services import booking, modification, quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_critical_journey import TexTestCase, pick, search_std

REFUSED = "reservation.reprice_refused"


def sell(code: str = "G73") -> tuple[str, dict]:
	"""A guest books STD / AI / Flexible for 2 adults, 6/10–6/12 on a fresh contract. → the
	reservation and its snapshot."""
	frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
	offer = pick(search_std(fx.d(6, 10), fx.d(6, 12), [{"adults": 2}]))
	q = quoting.create_quote(offer["rooms"][0]["offer_key"])
	assert q["ok"], q
	b = booking.create_booking(quote_ids=[q["quote_id"]], guest={"first_name": "Gee", "last_name": "Seventythree",
	                                                             "email": f"{code.lower()}@example.com"},
	                           payment_method="Card")
	frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff reprice the sold stay
	res = b["rooms"][0]["reservation"]
	return res, json.loads(frappe.db.get_value("Reservation", res, "tex_pricing_snapshot"))


def change_payload(version: str, *, rehash: bool = True) -> str:
	"""Double every absolute room price of a published version below its controller, as a restore
	of another backup or a hand-edit would. ``rehash``: the row's hash is recomputed, so the
	version still passes its own integrity check. → the version's hash now."""
	row = frappe.db.get_value("TEX Contract Version", version, ["payload", "payload_hash"], as_dict=True)
	payload = json.loads(row.payload)
	for r in payload["room_rules"]:
		if r["op"] == "ABSOLUTE":
			r["value"] = serialize.dec_str(D(r["value"]) * 2)
	digest = serialize.payload_hash(payload) if rehash else row.payload_hash
	frappe.db.set_value("TEX Contract Version", version, {"payload": serialize.canonical_json(payload),
	                                                     "payload_hash": digest}, update_modified=False)
	contracts.clear_terms_cache()
	return digest


def refusals(res: str) -> list[dict]:
	return [json.loads(v or "{}") for v in frappe.get_all(
		"TEX Audit Event", filters={"action": REFUSED, "reference_name": res}, pluck="new_value",
		order_by="creation asc, name asc")]


class SnapshotCase(TexTestCase):
	def setUp(self):
		super().setUp()
		self.c = fx.create_contract(self.f, code="G73")
		self.res, self.snap = sell()
		self.sold = frappe.db.get_value("Reservation", self.res, ["amount_after_tax", "tex_total_amount",
		                                                          "tex_pricing_snapshot", "tex_payload_hash"],
		                                as_dict=True)

	def assertRefused(self, fn, pattern: str = "not the terms it was sold on", msg=None):
		"""A refusal, never a silent reprice on other terms."""
		with self.assertRaisesRegex(frappe.ValidationError, pattern, msg=msg) as cm:
			out = fn()
			print(f"not refused ({msg}): {json.dumps(out, default=str)[:300]}")
		self.assertEqual(type(cm.exception).__name__, "PayloadMismatch", msg)

	def assertStillSold(self):
		now = frappe.db.get_value("Reservation", self.res, ["amount_after_tax", "tex_total_amount",
		                                                    "tex_pricing_snapshot", "tex_payload_hash"], as_dict=True)
		self.assertEqual(now, self.sold)


class TestPayloadHashChecked(SnapshotCase):
	def test_a_changed_payload_is_refused_on_the_original_bases_and_audited(self):
		self.assertEqual(modification.propose(self.res, {}, basis="ORIGINAL_VERSION")["proposed"]["totals"]["total"],
		                 "400.00")
		early = modification.propose(self.res, {"check_out": fx.d(6, 13)}, basis="ORIGINAL_VERSION")
		recorded = self.snap["contract"]["payload_hash"]
		found = change_payload(self.c["version"])
		for basis in ("ORIGINAL_VERSION", "ORIGINAL_SALE_DATE", "CURRENT"):
			# CURRENT: the version on sale now is still the one the stay was sold on
			self.assertRefused(lambda b=basis: modification.propose(self.res, {}, basis=b)["proposed"]["totals"],
			                   msg=basis)
		# a proposal made before the change
		self.assertRefused(lambda: modification.apply(early["proposal_token"], reason="guest extends"), msg="apply")
		seen = refusals(self.res)
		self.assertEqual([r["basis"] for r in seen], ["ORIGINAL_VERSION", "ORIGINAL_SALE_DATE", "CURRENT",
		                                             "ORIGINAL_VERSION"])
		self.assertEqual({(r["version"], r["recorded_hash"], r["found_hash"]) for r in seen},
		                 {(self.c["version"], recorded, found)})
		self.assertStillSold()                                    # the locked price never moved

	def test_a_payload_failing_its_integrity_check_is_refused_and_audited(self):
		change_payload(self.c["version"], rehash=False)
		self.assertRefused(lambda: modification.propose(self.res, {}, basis="ORIGINAL_VERSION"), "integrity")
		self.assertEqual([r["basis"] for r in refusals(self.res)], ["ORIGINAL_VERSION"])
		self.assertStillSold()

	def test_the_simulator_and_add_ons_check_the_hash_too(self):
		change_payload(self.c["version"])
		sold_at = modification.original_priced_at(frappe.get_doc("Reservation", self.res), self.snap)
		self.assertRefused(lambda: modification.simulate(self.res, str(sold_at))["simulated"]["totals"],
		                   msg="simulate")
		self.assertRefused(lambda: addon_svc.propose(self.res, [{"code": "TRF"}], guest=False)["new_total"],
		                   msg="add-on")
		self.assertEqual(len(refusals(self.res)), 2)
		self.assertStillSold()

	def test_a_new_version_prices_current_and_the_sold_version_still_reprices(self):
		v2 = contracts.new_draft(self.c["contract"])
		doc = frappe.get_doc("TEX Contract Version", v2)
		for r in doc.period_rates:
			if r.period_code == "LOW":
				r.value = 150
		doc.save()
		contracts.publish(v2)
		self.assertEqual(modification.propose(self.res, {}, basis="ORIGINAL_VERSION")["proposed"]["totals"]["total"],
		                 "400.00")                              # the sold version, its hash verified
		self.assertEqual(modification.propose(self.res, {}, basis="ORIGINAL_SALE_DATE")["proposed"]["totals"]["total"],
		                 "400.00")
		self.assertEqual(modification.propose(self.res, {}, basis="CURRENT")["proposed"]["totals"]["total"],
		                 "600.00")                              # a new version is not the sold one
		self.assertFalse(refusals(self.res))

	def test_the_references_resolve_in_the_verified_payload(self):
		# the snapshot names its periods and rules; the payload they name is the one it was sold on
		version, digest = self.snap["contract"]["version"], self.snap["contract"]["payload_hash"]
		terms = contracts.load_terms(version, expected_hash=digest)
		periods = {p.code: p for p in terms.periods}
		for n in self.snap["nights"]:
			self.assertTrue(periods[n["period"]].covers(get_datetime(n["date"]).date()), n)
		rules = {r.rule_id for r in terms.room_rules} | {r.rule_id for r in terms.occupancy_rules} \
			| {b.rule_id for b in terms.boards}
		named = {s["rule"]["rule_id"] for s in self.snap["explanation"]
		         if s.get("rule") and s["rule"].get("kind") in ("room_rule", "occupancy_rule", "board_rule")
		         and s["rule"].get("source") == "version"}
		self.assertTrue(named)
		self.assertLessEqual(named, rules)
		with self.assertRaises(contracts.PayloadMismatch):
			contracts.load_terms(version, expected_hash="0" * 64)

	def test_a_refusal_is_recorded_outside_the_refused_transaction(self):
		# the request that is refused rolls back: its audit is written by a job of its own
		with mock.patch.object(frappe, "enqueue") as enqueue, mock.patch.dict(frappe.flags, {"in_test": False}):
			audit_mod.audit_refusal(REFUSED, reference_doctype="Reservation", reference_name=self.res,
			                        property=fx.PROPERTY, new={"basis": "ORIGINAL_VERSION"}, reason="test")
		enqueue.assert_called_once()
		args, kw = enqueue.call_args
		self.assertEqual(args[0], "kamra.tex.security.audit.record_refusal")
		self.assertFalse(kw.get("now"))
		self.assertFalse(kw.get("enqueue_after_commit"))       # queued now: no commit is coming
		self.assertEqual((kw["action"], kw["reference_name"], kw["source"]), (REFUSED, self.res, "System"))
		audit_mod.record_refusal(**{k: v for k, v in kw.items() if k not in ("queue", "now", "enqueue_after_commit")})
		self.assertEqual(len(refusals(self.res)), 1)


class TestSaleTimeRecorded(SnapshotCase):
	def test_the_snapshot_records_when_it_was_priced(self):
		quote = frappe.db.get_value("TEX Quote", self.snap["quote_id"], ["creation", "request_json"], as_dict=True)
		self.assertEqual(get_datetime(self.snap["priced_at"]),
		                 get_datetime(json.loads(quote.request_json)["sale_at"]))
		self.assertLessEqual(get_datetime(self.snap["priced_at"]), get_datetime(self.snap["accepted_at"]))
		first = json.loads(frappe.db.get_value("TEX Reservation Revision",
		                                       {"reservation": self.res, "change_type": "Original"}, "snapshot_after"))
		self.assertEqual((first["priced_at"], first["accepted_at"]), (self.snap["priced_at"], self.snap["accepted_at"]))

	def test_a_modification_records_when_it_was_priced(self):
		p = modification.propose(self.res, {"check_out": fx.d(6, 13)}, basis="CURRENT")
		out = modification.apply(p["proposal_token"], reason="guest extends")
		snap = json.loads(frappe.db.get_value("Reservation", self.res, "tex_pricing_snapshot"))
		rev = frappe.db.get_value("TEX Reservation Revision", out["revision"], ["basis_sale_at", "snapshot_after"],
		                          as_dict=True)
		# CURRENT is re-derived when applied: priced at the apply's sale time, the revision's basis time
		self.assertEqual(get_datetime(snap["priced_at"]), get_datetime(rev.basis_sale_at))
		self.assertEqual(get_datetime(snap["priced_at"]), get_datetime(snap["request"]["sale_at"]))
		self.assertLessEqual(get_datetime(p["pricing_sale_at"]), get_datetime(snap["priced_at"]))
		self.assertLessEqual(get_datetime(snap["priced_at"]), get_datetime(snap["accepted_at"]))
		self.assertEqual(get_datetime(snap["original_priced_at"]), get_datetime(self.snap["priced_at"]))
		self.assertEqual(json.loads(rev.snapshot_after)["priced_at"], snap["priced_at"])
		# the modification's hash is checked in turn, on its own version
		self.assertEqual(snap["contract"]["payload_hash"], frappe.db.get_value("Reservation", self.res,
		                                                                        "tex_payload_hash"))

	def test_a_snapshot_without_the_new_keys_still_reprices(self):
		old = {k: v for k, v in self.snap.items() if k != "priced_at"}       # as written before G-73
		frappe.db.set_value("Reservation", self.res, "tex_pricing_snapshot", json.dumps(old, sort_keys=True),
		                    update_modified=False)
		res = frappe.get_doc("Reservation", self.res)
		self.assertEqual(modification.original_priced_at(res, old), get_datetime(old["request"]["sale_at"]))
		for basis in ("ORIGINAL_VERSION", "ORIGINAL_SALE_DATE"):
			p = modification.propose(self.res, {}, basis=basis)
			self.assertEqual(p["proposed"]["totals"]["total"], "400.00", basis)
			self.assertEqual(get_datetime(p["pricing_sale_at"]), get_datetime(old["request"]["sale_at"]), basis)
		p = modification.propose(self.res, {"check_out": fx.d(6, 13)}, basis="ORIGINAL_VERSION")
		modification.apply(p["proposal_token"], reason="guest extends")
		snap = json.loads(frappe.db.get_value("Reservation", self.res, "tex_pricing_snapshot"))
		self.assertEqual(get_datetime(snap["original_priced_at"]), get_datetime(old["request"]["sale_at"]))
		self.assertEqual(snap["totals"]["total"], "600.00")
