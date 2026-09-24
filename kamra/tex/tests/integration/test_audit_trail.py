"""G-74 (R-54, ADR-053): the audit trail says what changed, for which hotels, and how it arrived.

The 2026-09-23 audit found: draft contract edits were not audited and a publish recorded only
the payload hash; ARI bulk edits recorded no old values; payment rules were audited only on
some API paths; group and enterprise grant events carried no hotel, so only platform
administrators saw them; every payment outcome was recorded as coming from a "Webhook".
Each class below reproduces one of these first.
"""

import json
from types import SimpleNamespace
from unittest import mock

import frappe
from frappe.utils import add_days, now_datetime, nowdate

from kamra.tex.api import admin, public
from kamra.tex.api import contracts as contracts_api
from kamra.tex.api import payments as pay_api
from kamra.tex.api import policies as policies_api
from kamra.tex.commercial import contracts, grid
from kamra.tex.payments import service as pay
from kamra.tex.security import grants, scope
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import guest_books, setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase
from kamra.tex.tests.integration.test_security_regressions import FakeIyzico, _return_url

OTHER_HOTEL = "TEX Audit Other Hotel"
OTHER_GROUP = "TEST Audit Other Group"
OTHER_ENTERPRISE = "TEST Audit Other Enterprise"
# never stored anywhere readable: the audit may say a secret was set or changed, never what it is
SECRETS = ("ak-G74-never-logged", "sk-G74-never-logged", "sk-G74-rotated-never-logged")


def as_user(user: str) -> None:
	frappe.set_user(user)  # nosemgrep: frappe-setuser -- the test acts as each user in turn
	scope.clear_cache()


def events(action: str, reference_name: str | None = None, property: str | None = None) -> list[dict]:
	filters: dict = {"action": action}
	if reference_name:
		filters["reference_name"] = reference_name
	if property:
		filters["property"] = property
	rows = frappe.get_all("TEX Audit Event", filters=filters,
	                      fields=["name", "action", "source", "property", "reference_name", "reason", "old_value",
	                              "new_value"], order_by="creation asc, name asc")
	for r in rows:
		r["old"] = json.loads(r.pop("old_value") or "null")
		r["new"] = json.loads(r.pop("new_value") or "null")
	return rows


def last_event(action: str, reference_name: str | None = None, property: str | None = None) -> dict:
	rows = events(action, reference_name, property)
	if not rows:
		raise AssertionError(f"no {action} event for {reference_name or property}")
	return rows[-1]


def scope_hotels(event: str) -> set[str]:
	return set(frappe.get_all("TEX Audit Scope", filters={"event": event}, pluck="property"))


class AuditCase(TexTestCase):
	def setUp(self):
		super().setUp()
		frappe.flags.tex_source = None           # a flag another test module left behind


# ─── group / enterprise grant scope ──────────────────────────────────────


class TestGrantScope(AuditCase):
	"""A group or enterprise grant gives access to hotels: its events name them, so each hotel's
	administrators see who was given access to their hotel, and only that."""

	def setUp(self):
		super().setUp()
		ent2 = fx.ensure("TEX Enterprise", {"enterprise_name": OTHER_ENTERPRISE}, {"enterprise_name": OTHER_ENTERPRISE})
		self.group2 = fx.ensure("TEX Hotel Group", {"group_name": OTHER_GROUP},
		                        {"group_name": OTHER_GROUP, "enterprise": ent2})
		if not frappe.db.exists("Property", OTHER_HOTEL):
			frappe.get_doc({"doctype": "Property", "property_name": OTHER_HOTEL, "city": "Fethiye", "country": "Turkey",
			                "currency": "EUR", "tex_hotel_group": self.group2}).insert(ignore_permissions=True)
		self.gm = fx.ensure_user("g74-gm@example.com", ["Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": self.gm, "property": fx.PROPERTY},
		          {"user": self.gm, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Hotel Admin"})
		self.mine = fx.ensure_user("g74-group-agent@example.com", ["Call Center Agent"])
		self.theirs = fx.ensure_user("g74-other-agent@example.com", ["Call Center Agent"])
		self.wide = fx.ensure_user("g74-enterprise-agent@example.com", ["Call Center Agent"])
		scope.clear_cache()

	def grant(self, user: str, level: str, **where) -> str:
		as_user("Administrator")
		return frappe.get_doc({"doctype": "TEX Access Grant", "user": user, "scope_level": level,
		                       "permission_profile": "Reservations Agent", **where}).insert(ignore_permissions=True).name

	def test_group_and_enterprise_grant_events_name_their_hotels(self):
		mine = self.grant(self.mine, "Hotel Group", hotel_group=self.f["group"])
		theirs = self.grant(self.theirs, "Hotel Group", hotel_group=self.group2)
		wide = self.grant(self.wide, "Enterprise", enterprise=self.f["enterprise"])

		e = last_event("grant.update", mine)
		self.assertIsNone(e["property"])                                 # not one hotel's event...
		self.assertEqual(frappe.db.get_value("TEX Audit Event", e["name"], "hotel_group"), self.f["group"])
		self.assertIn(fx.PROPERTY, scope_hotels(e["name"]))               # ...but it reaches this hotel
		self.assertNotIn(OTHER_HOTEL, scope_hotels(e["name"]))
		self.assertEqual(scope_hotels(last_event("grant.update", theirs)["name"]), {OTHER_HOTEL})
		e = last_event("grant.update", wide)
		self.assertEqual(frappe.db.get_value("TEX Audit Event", e["name"], "enterprise"), self.f["enterprise"])
		self.assertIn(fx.PROPERTY, scope_hotels(e["name"]))

		# moved to another group: the hotels it left and the hotels it reaches are both told
		doc = frappe.get_doc("TEX Access Grant", mine)
		doc.hotel_group = self.group2
		doc.save(ignore_permissions=True)
		self.assertLessEqual({fx.PROPERTY, OTHER_HOTEL}, scope_hotels(last_event("grant.update", mine)["name"]))
		frappe.delete_doc("TEX Access Grant", theirs, ignore_permissions=True)
		self.assertEqual(scope_hotels(last_event("grant.delete", theirs)["name"]), {OTHER_HOTEL})

	def test_a_hotel_admin_sees_group_grant_events_of_their_hotel_only(self):
		mine = self.grant(self.mine, "Hotel Group", hotel_group=self.f["group"])
		theirs = self.grant(self.theirs, "Hotel Group", hotel_group=self.group2)
		wide = self.grant(self.wide, "Enterprise", enterprise=self.f["enterprise"])
		ev_mine, ev_theirs = last_event("grant.update", mine)["name"], last_event("grant.update", theirs)["name"]

		as_user(self.gm)
		rows = admin.audit_log(property=fx.PROPERTY, reference_doctype="TEX Access Grant")
		seen = {r["reference_name"] for r in rows}
		self.assertLessEqual({mine, wide}, seen)
		self.assertNotIn(theirs, seen)
		row = next(r for r in rows if r["reference_name"] == mine)
		self.assertEqual(row["hotels"], [fx.PROPERTY])                   # other hotels only as a count
		self.assertEqual(row["hotel_group"], self.f["group"])

		# Desk / REST follow the same scope
		listed = set(frappe.get_list("TEX Audit Event", filters={"reference_doctype": "TEX Access Grant"},
		                             pluck="reference_name"))
		self.assertIn(mine, listed)
		self.assertNotIn(theirs, listed)
		self.assertTrue(frappe.has_permission("TEX Audit Event", "read", doc=ev_mine, user=self.gm))
		self.assertFalse(frappe.has_permission("TEX Audit Event", "read", doc=ev_theirs, user=self.gm))
		self.assertEqual(set(frappe.get_list("TEX Audit Scope", filters={"event": ev_mine}, pluck="property")),
		                 {fx.PROPERTY})
		self.assertFalse(frappe.get_list("TEX Audit Scope", filters={"event": ev_theirs}, pluck="property"))

	def test_an_ended_group_grant_is_audited_with_its_hotels(self):
		g = self.grant(self.mine, "Hotel Group", hotel_group=self.f["group"], valid_until=nowdate())
		frappe.db.set_value("TEX Access Grant", g, "valid_until", add_days(nowdate(), -1))
		grants.remove_expired_grants()
		e = last_event("grant.expired", g)
		self.assertEqual(e["source"], "Scheduler")
		self.assertEqual(frappe.db.get_value("TEX Audit Event", e["name"], "hotel_group"), self.f["group"])
		self.assertIn(fx.PROPERTY, scope_hotels(e["name"]))


# ─── contract drafts and publishing ──────────────────────────────────────


class TestContractAudit(AuditCase):
	"""Every saved draft edit is on record as old → new (rows by their natural key); a publish
	says what it froze and how it differs from the version that sold before."""

	TABLES = ("rooms", "periods", "period_rates", "age_bands", "occupancy_rules", "boards", "rate_plans", "offers")

	def setUp(self):
		super().setUp()
		self.c = fx.create_contract(self.f, code="AUD")
		self.v2 = contracts.new_draft(self.c["contract"])
		self.std, self.dlx = self.f["room_types"]["STD"], self.f["room_types"]["DLX"]

	def draft(self) -> dict:
		v = contracts_api.get_version(self.v2)
		return {t: v[t] for t in self.TABLES}

	def uplift(self) -> dict:
		data = self.draft()
		for r in data["period_rates"]:
			if r["room_type"] == self.std and r["period_code"] == "LOW":
				r["value"] = 110
		data["boards"].append({"board": "HB", "op": "ADD", "adult_amount": 15, "child_percent": 50})
		data["prices_include_tax"] = 1
		data["change_note"] = "summer uplift"
		return data

	def test_a_draft_save_records_what_changed(self):
		data = self.uplift()
		contracts_api.save_version(self.v2, data)
		e = last_event("contract.version.save", self.v2)
		self.assertEqual(e["property"], fx.PROPERTY)
		self.assertEqual((e["old"]["prices_include_tax"], e["new"]["prices_include_tax"]), (False, True))
		self.assertEqual((e["old"]["change_note"], e["new"]["change_note"]), (None, "summer uplift"))
		rates = e["new"]["collections"]["period_rates"]
		self.assertEqual(rates["changed"], {f"{self.std} · LOW": {"value": ["100", "110"]}})
		self.assertEqual(rates["totals"], {"added": 0, "removed": 0, "changed": 1})
		self.assertEqual(rates["count"], [3, 3])
		self.assertEqual(e["new"]["collections"]["boards"]["added"], ["HB"])
		self.assertNotIn("rooms", e["new"]["collections"])               # untouched tables are not repeated
		n = len(events("contract.version.save", self.v2))
		again = {**self.draft(), "prices_include_tax": 1, "change_note": "summer uplift"}
		contracts_api.save_version(self.v2, again)                      # the same draft again: nothing changed
		self.assertEqual(len(events("contract.version.save", self.v2)), n)

	def test_a_large_edit_is_summarised(self):
		data = self.draft()
		data["periods"] += [{"period_code": f"X{i:02d}", "period_name": f"Extra {i}", "start_date": str(fx.d(5, 1)),
		                     "end_date": str(fx.d(5, 2))} for i in range(60)]
		contracts_api.save_version(self.v2, data)
		p = last_event("contract.version.save", self.v2)["new"]["collections"]["periods"]
		self.assertEqual(p["count"], [2, 62])
		self.assertEqual(p["totals"]["added"], 60)
		self.assertEqual(len(p["added"]), 50)                            # keys listed up to a bound
		self.assertEqual(p["added"][0], "X00")

	def test_publish_records_the_commercial_difference(self):
		first = last_event("contract.publish", self.c["version"])
		self.assertIsNone(first["new"]["previous"])
		self.assertEqual(first["new"]["collections"]["rooms"]["totals"]["added"], 2)
		contracts_api.save_version(self.v2, self.uplift())
		out = contracts.publish(self.v2, change_note="summer uplift")
		e = last_event("contract.publish", self.v2)
		self.assertEqual(e["new"]["payload_hash"], out["payload_hash"])
		self.assertEqual(e["new"]["effective_from"], out["effective_from"])
		self.assertEqual(e["new"]["previous"], {"version": self.c["version"], "payload_hash": self.c["payload_hash"]})
		cols = e["new"]["collections"]
		self.assertEqual(cols["room_rules"]["changed"], {f"{self.std} · LOW": {"value": ["100", "110"]}})
		self.assertEqual(cols["boards"]["added"], ["HB"])
		self.assertEqual(cols["settings"]["fields"], {"prices_include_tax": [False, True]})
		for untouched in ("rooms", "periods", "age_bands", "occupancy_rules", "rate_plans", "offers"):
			self.assertNotIn(untouched, cols)
