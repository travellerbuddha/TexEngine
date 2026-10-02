"""Several rate edits of the rates & availability grid as one draft edit (UX revision 2026-10,
``grid.rate_changes`` / ``crs.ari_rate_changes``).

The grid now lets staff type prices into cells, paste a block from a spreadsheet or raise a
selection by a percentage, and saves them together. These tests pin what that must keep:

* a preview writes nothing (no draft is made, no row is touched) and says each room's price
  before and after, worked out by the server;
* a relative change is worked out from the prices before ANY of the changes: a derived room
  (DLX = STD × 1.35) selected with its base is raised once, not on top of its raised base;
* the edits are written to the draft in one transaction: an edit that adds an ERROR refuses the
  whole batch and nothing is saved; nothing is sold at the new prices until the draft is published;
* each night is changed once per batch; dates are never assumed (a missing date is not today);
* the same permission as every rate edit (``contract.edit``), and an audit event.
"""

from datetime import timedelta

import frappe

from kamra.tex.api import crs as crs_api
from kamra.tex.commercial import contracts, grid
from kamra.tex.security import scope
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_inventory import InventoryCase


class TestGridRateChanges(InventoryCase):
	def setUp(self):
		super().setUp()
		self.contract = self.c["contract"]
		self.sat = next(fx.d(6, 1) + timedelta(days=i) for i in range(7) if (fx.d(6, 1) + timedelta(days=i)).weekday() == 5)
		self.sun = self.sat + timedelta(days=1)
		self.mon = self.sat + timedelta(days=2)

	def change(self, room_types, start, end, op, value) -> dict:
		return {"room_types": room_types, "start": str(start), "end": str(end), "op": op, "value": value}

	def run_changes(self, changes, apply=0):
		return crs_api.ari_rate_changes(property=fx.PROPERTY, contract=self.contract, changes=changes, apply=apply)

	def draft(self) -> str | None:
		return frappe.db.get_value("TEX Contract Version", {"contract": self.contract, "status": "Draft"}, "name")

	def cells(self, room_type: str) -> dict:
		out = crs_api.ari_grid(property=fx.PROPERTY, start=str(self.sat), days=3, contract=self.contract)
		row = next(r for r in out["rows"] if r["room_type"] == room_type)
		return {c["date"]: c for c in row["cells"]}

	def test_a_preview_writes_nothing_and_raises_a_derived_room_once(self):
		self.assertIsNone(self.draft())
		modified = frappe.db.get_value("TEX Contract", self.contract, "modified")
		out = self.run_changes([self.change([self.std, self.dlx], self.sat, self.sun, "ADJUST_PERCENT", "10")])
		self.assertFalse(out["applied"])
		self.assertTrue(out["creates_draft"])
		self.assertIsNone(self.draft())                                   # nothing written
		self.assertEqual(frappe.db.get_value("TEX Contract", self.contract, "modified"), modified)
		got = {(c["room_type"], c["start"], c["end"]): (c["current"], c["new"]) for c in out["cells"]}
		self.assertEqual(got, {(self.std, str(self.sat), str(self.sun)): ("100.00", "110.00"),
		                       # DLX follows STD × 1.35: 135.00 + 10 % once, never 110.00 × 1.35 × 1.1
		                       (self.dlx, str(self.sat), str(self.sun)): ("135.00", "148.50")})
		self.assertEqual((out["currency"], out["errors"]), ("EUR", []))
		self.assertGreaterEqual(out["new_periods"], 1)                    # two nights cut out of their period

	def test_apply_writes_the_draft_once_and_sells_nothing_until_published(self):
		out = self.run_changes([self.change([self.std, self.dlx], self.sat, self.sun, "ADJUST_PERCENT", "10")], apply=1)
		self.assertTrue(out["applied"])
		self.assertEqual(out["draft"], self.draft())
		std, dlx = self.cells(self.std), self.cells(self.dlx)
		self.assertEqual([(std[str(d)]["rate"], std[str(d)]["draft_rate"]) for d in (self.sat, self.sun, self.mon)],
		                 [("100.00", "110.00"), ("100.00", "110.00"), ("100.00", "100.00")])
		self.assertEqual([dlx[str(d)]["draft_rate"] for d in (self.sat, self.mon)], ["148.50", "135.00"])
		event = frappe.get_all("TEX Audit Event", filters={"action": "grid.rate_changes"}, fields=["name"],
		                       order_by="creation desc", limit=1)
		self.assertTrue(event)
		contracts.publish(self.draft())                                   # the draft stays publishable
		std = self.cells(self.std)
		self.assertEqual((std[str(self.sat)]["rate"], std[str(self.mon)]["rate"]), ("110.00", "100.00"))

	def test_typed_cells_each_night_its_own_price(self):
		self.run_changes([self.change([self.std], self.sat, self.sat, "ABSOLUTE", "150"),
		                  self.change([self.std], self.sun, self.sun, "ABSOLUTE", "160")], apply=1)
		std = self.cells(self.std)
		self.assertEqual([std[str(d)]["draft_rate"] for d in (self.sat, self.sun, self.mon)], ["150.00", "160.00", "100.00"])
		# a second batch edits the first one's periods in place
		before = len(frappe.get_doc("TEX Contract Version", self.draft()).periods)
		self.run_changes([self.change([self.std], self.sat, self.sat, "ABSOLUTE", "155")], apply=1)
		self.assertEqual(len(frappe.get_doc("TEX Contract Version", self.draft()).periods), before)
		self.assertEqual(self.cells(self.std)[str(self.sat)]["draft_rate"], "155.00")

	def test_an_error_refuses_the_whole_batch(self):
		draft = contracts.new_draft(self.contract)
		v = frappe.get_doc("TEX Contract Version", draft)
		for r in v.period_rates:
			if r.room_type == self.dlx:
				r.update({"op": "SUBTRACT", "value": 50})                # DLX = STD − 50
		v.save(ignore_permissions=True)
		periods = len(frappe.get_doc("TEX Contract Version", draft).periods)
		batch = [self.change([self.std], self.mon, self.mon, "ABSOLUTE", "120"),
		         self.change([self.std], self.sat, self.sat, "ABSOLUTE", "30")]   # DLX would be −20
		preview = self.run_changes(batch)
		self.assertTrue(preview["errors"], preview)
		with self.assertRaisesRegex(frappe.ValidationError, "errors"):
			self.run_changes(batch, apply=1)
		self.assertEqual(len(frappe.get_doc("TEX Contract Version", draft).periods), periods)
		std = self.cells(self.std)
		self.assertEqual([std[str(d)]["draft_rate"] for d in (self.sat, self.mon)], ["100.00", "100.00"])

	def test_each_night_once_and_no_assumed_dates(self):
		with self.assertRaisesRegex(frappe.ValidationError, "changed twice"):
			self.run_changes([self.change([self.std], self.sat, self.sun, "ABSOLUTE", "150"),
			                  self.change([self.std], self.sun, self.mon, "ADD", "5")])
		with self.assertRaisesRegex(frappe.ValidationError, "dates"):
			self.run_changes([{"room_types": [self.std], "end": str(self.sat), "op": "ABSOLUTE", "value": "150"}])
		with self.assertRaisesRegex(frappe.ValidationError, "number"):
			self.run_changes([self.change([self.std], self.sat, self.sat, "ABSOLUTE", "abc")])
		with self.assertRaisesRegex(frappe.ValidationError, "absolute"):
			self.run_changes([self.change([self.std], self.sat, self.sat, "MULTIPLY", "1.1")])
		with self.assertRaisesRegex(frappe.ValidationError, "negative"):
			self.run_changes([self.change([self.std], self.sat, self.sat, "SUBTRACT", "500")])
		self.assertIsNone(self.draft())

	def test_contract_edit_is_required_and_the_hotel_must_match(self):
		with self.assertRaisesRegex(frappe.ValidationError, "another hotel"):
			grid.rate_changes("Some Other Hotel", self.contract, [self.change([self.std], self.sat, self.sat, "ABSOLUTE", "1")])
		viewer = fx.ensure_user("ux-rate-viewer@example.com", ["Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": viewer, "property": fx.PROPERTY},
		          {"user": viewer, "scope_level": "Hotel", "property": fx.PROPERTY, "permission_profile": "Viewer"})
		frappe.set_user(viewer)  # nosemgrep: frappe-setuser -- a viewer without contract.edit
		scope.clear_cache()
		for apply in (0, 1):
			with self.assertRaises(frappe.PermissionError):
				self.run_changes([self.change([self.std], self.sat, self.sat, "ABSOLUTE", "1")], apply=apply)
