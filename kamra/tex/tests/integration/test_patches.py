"""G-76 (R-56): every TEX patch is tested, and so is the upgrade of a Kamra database (ADR-058).

For every patch that ``kamra/patches.txt`` lists (``kamra.patches.tex.*``):

(a) it does what it says on representative pre-patch data: a test in this module, or in the module
    of its feature (``BEHAVIOUR``; the registry is checked, so a new patch without a test fails);
(b) running it again changes nothing, whether it runs twice in one migration attempt or is forced
    again later over what administrators changed since: every TEX table and the legacy rows the
    patches write are compared between the runs;
(c) it never changes a published payload or its hash, nor a sold stay's amounts, currency,
    snapshot, revisions or price lock;
(d) it runs on an empty site.

``TestUpgradeFromKamra`` runs the whole chain in ``patches.txt`` order on a Kamra-shaped database
(legacy hotels, users with and without property restrictions, legacy reservations, vouchers and
experiences, no TEX structures) and checks what the upgrade leaves behind.

Safety: the dev site is shared. A patch's DDL (``reload_doc``, index creation, the custom-field
sync, any ALTER, CREATE or DROP) makes MariaDB commit the open transaction, which would leak the
test's rows and, in the empty-site tests, make their deletions real. ``sandbox()`` stubs those calls
(the schema is migrated already), refuses any commit, DDL or transaction statement, and keeps File
from moving files on disk. Everything runs in the test's transaction, which tearDown rolls back;
the documents cached meanwhile are dropped from the cache after it.
"""

import hashlib
import json
import os
from contextlib import ExitStack, contextmanager
from importlib import import_module
from unittest import mock

import frappe
from frappe.database.utils import get_query_type
from frappe.utils import add_days, add_to_date, get_datetime, getdate, now_datetime, nowdate

import kamra
from kamra.tex import legacy
from kamra.tex.money import D
from kamra.tex.security import scope
from kamra.tex.security.capabilities import DEFAULT_PROFILES
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_critical_journey import TexTestCase, pick, search_std

PREFIX = "kamra.patches.tex."

# (a): where each patch's behaviour is tested
BEHAVIOUR = {
	"p01_foundation": "test_patches.TestP01Foundation",
	"p02_access_grants": "test_patches.TestP02AccessGrants",
	"p03_indexes": "test_patches.TestP03Indexes",
	"p04_lock_legacy_prices": "test_patches.TestP04LegacyPriceLock",
	"p05_vouchers_to_promotions": "test_migrations_notify.TestLegacyMigrations.test_vouchers_and_experiences_are_copied_once",
	"p06_experiences_to_extras": "test_migrations_notify.TestLegacyMigrations.test_vouchers_and_experiences_are_copied_once",
	"p07_forget_payment_link_urls": "test_patches.TestSmallPatches.test_p07_forgets_payment_link_urls",
	"p08_confirm_unpaid_capability": "test_patches.TestCapabilityPatches",
	"p09_guest_stats_completed_stays": "test_patches.TestP09GuestStats",
	"p10_scrub_link_return_urls": "test_security_regressions.TestPaymentLinkTokens.test_old_transactions_are_scrubbed",
	"p11_allocation_idempotency": "test_patches.TestSmallPatches.test_p11_p20_only_sync_their_doctypes",
	"p12_effective_dated_extras_and_taxes": "test_migrations_notify.TestEffectiveDatingMigration",
	"p13_extra_inventory": "test_patches.TestP13ExtraInventory",
	"p14_post_booking_extras": "test_patches.TestSmallPatches.test_p14_gives_extras_an_order_cutoff",
	"p15_booking_hosts": "test_custom_domains.TestBookingHostMigration.test_a_path_domain_is_unverified_and_hosts_are_kept",
	"p16_crm_segments": "test_crm_segments.TestSegmentMigration.test_presets_are_seeded_and_renamed",
	"p17_loyalty_admin": "test_loyalty_admin.TestLoyaltyMigration.test_old_meanings_are_kept",
	"p18_channel_distribution": "test_patches.TestP18ChannelDistribution",
	"p19_payments_go_live_check": "test_security_regressions.TestGoLivePaymentsReview."
	                              "test_g67_a_gated_account_still_settles_money_the_gateway_holds",
	"p20_guest_change_requests": "test_patches.TestSmallPatches.test_p11_p20_only_sync_their_doctypes",
	"p21_contract_header_lock": "test_critical_journey.TestContractHeaderLock."
	                            "test_p21_gives_drafts_of_published_contracts_their_header_terms",
	"p22_payment_api_key_password": "test_security_hygiene.TestSecurityHygieneG83."
	                                "test_g83_p22_moves_plain_api_keys_into_the_encrypted_store",
	"p23_system_status_alerts": "test_patches.TestP23MailStatus",
	"p24_g83_review": "test_security_hygiene.TestSecurityHygieneG83Review."
	                  "test_r3_p24_privatises_public_html_reports_the_rest_and_masks_versioned_keys",
	"p25_contract_header_snapshot": "test_critical_journey.TestContractHeaderLockReview."
	                                "test_the_upgrade_keeps_header_narrowings_fixed_and_reports_them",
	"p27_inventory_cutoff_release": "test_inventory.TestAllotments.test_the_upgrade_keeps_allotments_selling_as_before",
	"p28_guest_change_refund_rows": "test_self_service_money.TestFourthReview.test_p28_names_the_refunds_each_change_made",
	"p29_channel_binding": "test_channel_binding.TestGrantsAndProfiles."
	                       "test_p29_keeps_revenue_and_admin_profiles_on_every_channel",
	"p31_g41_review": "test_channel_binding.TestBookingSitesSellOnTheWeb."
	                  "test_p31_reports_sites_on_another_channel_and_leaves_them_to_the_owner",
	"p33_audit_scope": "test_patches.TestSmallPatches.test_p33_gives_group_grant_events_their_hotels",
	"p34_redemption_released_at": "test_patches.TestSmallPatches.test_p34_dates_released_coupon_uses",
	"p35_money_field_types": "test_money_fields.TestPublishedAndSoldTermsAreUnchanged."
	                         "test_a_published_payload_keeps_its_hash_through_the_migration",
	"p36_g92_review": "test_patches.TestUpgradeFromKamra",
	"p37_crm_privacy": "test_crm_privacy.TestAbandonedPrivacy.test_p37_purges_hashes_kept_without_consent",
	"p38_restriction_scope": "test_restrictions.TestGridCells.test_p38_keeps_every_key_and_rekeys_only_a_wrong_one",
	"p39_lookup_indexes": "test_patches.TestP03Indexes.test_p39_creates_the_lookup_indexes_that_survive_a_sync",
}


def listed_patches() -> list[str]:
	"""The TEX patches in migration order, as ``patches.txt`` lists them."""
	with open(os.path.join(os.path.dirname(kamra.__file__), "patches.txt")) as fh:
		lines = [ln.split("#", 1)[0].strip() for ln in fh]
	return [ln[len(PREFIX):] for ln in lines if ln.startswith(PREFIX)]


# ─── running a patch inside the test's transaction ──────────────────────

# statements that commit or end the transaction (MariaDB commits before DDL)
REFUSED = frozenset({"alter", "create", "drop", "truncate", "rename", "commit", "start", "begin", "lock", "unlock",
                     "grant", "revoke"})


@contextmanager
def sandbox():
	"""Patches run inside the test's transaction. Their DDL is stubbed and recorded (the schema is
	migrated already), a commit or a DDL / transaction statement is refused (and recorded, in case
	a patch swallows the error), File moves nothing on disk, output is captured."""
	db = frappe.local.db
	real_sql = db.sql
	seen = {"reload_doc": [], "add_index": [], "custom_fields": [], "refused": []}

	def refuse(what):
		seen["refused"].append(what)
		raise AssertionError(f"a patch tried to {what} inside a test: it would commit the shared site")

	def sql(query, *args, **kwargs):
		text = str(query)
		kind = get_query_type(text)
		if kind in REFUSED or (kind == "rollback" and "savepoint" not in text.lower()):
			refuse(f"run `{text.strip()[:80]}`")
		return real_sql(query, *args, **kwargs)

	with ExitStack() as st:
		st.enter_context(mock.patch.object(db, "sql", sql))
		st.enter_context(mock.patch.object(db, "commit", side_effect=lambda *a, **k: refuse("commit")))
		st.enter_context(mock.patch.object(db, "sql_ddl", side_effect=lambda *a, **k: refuse("run DDL")))
		st.enter_context(mock.patch.object(db, "add_unique", side_effect=lambda *a, **k: refuse("add a constraint")))
		st.enter_context(mock.patch.object(
			db, "add_index", side_effect=lambda dt, fields, name=None: seen["add_index"].append((dt, tuple(fields), name))))
		st.enter_context(mock.patch.object(frappe, "reload_doc",
		                                   side_effect=lambda *a, **k: seen["reload_doc"].append(tuple(a[:3]))))
		st.enter_context(mock.patch("frappe.custom.doctype.custom_field.custom_field.create_custom_fields",
		                            side_effect=lambda fields, **k: seen["custom_fields"].append(fields)))
		st.enter_context(mock.patch("frappe.core.doctype.file.file.File.handle_is_private_changed"))
		seen["print"] = st.enter_context(mock.patch("builtins.print"))
		st.enter_context(mock.patch.dict(frappe.local.flags, {"in_patch": True, "in_migrate": True}))
		yield seen


def log_patch(patch: str) -> None:
	"""What Frappe does after a patch succeeds: its Patch Log row."""
	if not frappe.db.exists("Patch Log", {"patch": PREFIX + patch}):
		put("Patch Log", patch=PREFIX + patch)


def migrate(patch: str, *, log: bool = True) -> dict:
	"""Run a patch as ``bench migrate`` does (then log it), in the sandbox. → what the sandbox saw."""
	module = import_module(PREFIX + patch)
	with sandbox() as seen:
		module.execute()
	assert not seen["refused"], f"{patch}: {seen['refused']}"
	if log:
		log_patch(patch)
	return seen


def never_ran(*patches: str) -> None:
	"""The site as it was before these patches: no Patch Log row (in this transaction only)."""
	for p in patches:
		frappe.db.delete("Patch Log", {"patch": PREFIX + p})


def put(doctype: str, name: str | None = None, **values) -> str:
	"""A row as an older release stored it: written below the controllers (no hooks, no checks)."""
	now = now_datetime()
	doc = frappe.get_doc({"doctype": doctype, "name": name or frappe.generate_hash(length=12), "creation": now,
	                      "modified": now, "owner": "Administrator", "modified_by": "Administrator", **values})
	doc.db_insert()
	return doc.name


# ─── what a patch may never change, and what a second run may not change ─


def sold_state() -> dict:
	"""(c): published payloads and hashes; each stay's amounts, currency, commercial record,
	snapshot and lock; each revision."""
	sql = frappe.db.sql
	return {
		"payloads": {r[0]: r[1:] for r in sql(
			"SELECT name, payload_hash, SHA2(payload, 256) FROM `tabTEX Contract Version` WHERE status != 'Draft'")},
		"stays": {r[0]: r[1:] for r in sql(
			"""SELECT name, amount_before_tax, tax_amount, amount_after_tax, discount_amount, tex_total_amount,
			          tex_extras_amount, tex_cost_amount, tex_margin_amount, tex_currency, tex_fx_rate,
			          tex_payload_hash, tex_contract, tex_contract_version, cancellation_fee,
			          SHA2(tex_pricing_snapshot, 256) FROM tabReservation""")},
		"locked": {r[0] for r in sql("SELECT name FROM tabReservation WHERE tex_price_locked = 1")},
		"revisions": {r[0]: r[1:] for r in sql(
			"""SELECT name, old_amount, new_amount, override_amount, SHA2(snapshot_before, 256),
			          SHA2(snapshot_after, 256) FROM `tabTEX Reservation Revision`""")},
	}


def assert_sold_unchanged(case, before: dict, after: dict, what: str) -> None:
	for key in ("payloads", "stays", "revisions"):
		changed = sorted(k for k in set(before[key]) | set(after[key]) if before[key].get(k) != after[key].get(k))
		case.assertFalse(changed, f"{what} changed {key}: {changed[:5]}")
	case.assertFalse(before["locked"] - after["locked"], f"{what} unlocked a sold stay")


# the legacy rows patches write, and which of them
LEGACY_ROWS = {"tabProperty": "", "tabReservation": "", "tabGuest": "", "tabUser Permission": "",
               "tabDiscount Voucher": "", "tabExperience": "", "tabFile": "",
               "tabVersion": "WHERE ref_doctype LIKE 'TEX %%' OR ref_doctype IN ('Reservation', 'Guest')",
               "tabSingles": "WHERE doctype = 'TEX Settings' AND field NOT IN ('modified', 'modified_by')",
               "__Auth": "WHERE doctype LIKE 'TEX %%'"}
IGNORED_COLUMNS = frozenset({"modified", "modified_by"})
_COLUMNS: dict[str, list[str]] = {}


def tex_tables() -> list[str]:
	return sorted(t for (t,) in frappe.db.sql(
		"""SELECT table_name FROM information_schema.tables
		   WHERE table_schema = DATABASE() AND table_name LIKE 'tabTEX %%'"""))


def _columns(table: str) -> list[str]:
	if table not in _COLUMNS:
		_COLUMNS[table] = [c for (c,) in frappe.db.sql(
			"""SELECT column_name FROM information_schema.columns WHERE table_schema = DATABASE()
			   AND table_name = %s ORDER BY ordinal_position""", table) if c not in IGNORED_COLUMNS]
	return _COLUMNS[table]


def site_digest() -> dict[str, dict]:
	"""(b): every row of every TEX table and of the legacy rows patches write (its content, not when
	it was last written), keyed by table and row."""
	out = {}
	for table, where in [(t, "") for t in tex_tables()] + list(LEGACY_ROWS.items()):
		cols = _columns(table)
		if not cols:
			continue
		rows = frappe.db.sql("SELECT {} FROM `{}` {}".format(", ".join(f"`{c}`" for c in cols), table, where))
		key = cols.index("name") if "name" in cols and table != "__Auth" else None
		out[table] = {(row[key] if key is not None else repr(row)): hashlib.sha1(repr(row).encode()).hexdigest()
		              for row in rows}
	return out


def digest_changes(a: dict, b: dict) -> dict:
	out = {}
	for t in sorted(set(a) | set(b)):
		x, y = a.get(t, {}), b.get(t, {})
		if x != y:
			out[t] = {"added": sorted(set(y) - set(x))[:5], "removed": sorted(set(x) - set(y))[:5],
			          "changed": sorted(k for k in set(x) & set(y) if x[k] != y[k])[:5]}
	return out


def rerun_changes(patch: str) -> dict:
	"""(b): what running ``patch`` once more changes (a forced re-run: its Patch Log row stays)."""
	before = site_digest()
	migrate(patch)
	return digest_changes(before, site_digest())


def empty_site() -> None:
	"""No hotel, stay, guest, legacy voucher or experience and no TEX record, as a site that never
	ran TEX, in this transaction only (tearDown rolls it back; nothing here may commit)."""
	with sandbox():
		for t in tex_tables():
			frappe.db.sql(f"DELETE FROM `{t}`")
		for t in ("tabProperty", "tabReservation", "tabGuest", "tabDiscount Voucher", "tabExperience",
		          "tabRoom Type", "tabPOS Order", "tabHousekeeping Task"):
			frappe.db.sql(f"DELETE FROM `{t}`")
		frappe.db.sql("DELETE FROM `tabUser Permission` WHERE allow = 'Property'")
		frappe.db.sql("DELETE FROM `tabFile` WHERE is_folder = 0")
		frappe.db.sql("DELETE FROM `tabVersion` WHERE ref_doctype LIKE 'TEX %%' OR ref_doctype IN ('Reservation', 'Guest')")
		frappe.db.sql("DELETE FROM `tabSingles` WHERE doctype = 'TEX Settings'")
		frappe.db.sql("DELETE FROM `__Auth` WHERE doctype LIKE 'TEX %%'")
		frappe.db.sql("DELETE FROM `tabPatch Log` WHERE patch LIKE 'kamra.patches.tex.%%'")
	frappe.local.db.value_cache.clear()
	scope.clear_cache()


def run_chain(case) -> None:
	"""Every TEX patch in migration order, as one ``bench migrate`` runs them; (c) after each."""
	for patch in listed_patches():
		before = sold_state()
		migrate(patch)
		assert_sold_unchanged(case, before, sold_state(), patch)


class PatchCase(TexTestCase):
	def tearDown(self):
		super().tearDown()                       # the rollback
		frappe.local.db.value_cache.clear()
		# documents read while the patches ran may have been cached from this transaction
		frappe.cache.delete_keys("document_cache::")
		from kamra.tex.services import sites

		sites.clear_host_cache()

	def first_run(self, patch: str) -> dict:
		"""The patch on a site where it never ran (its Patch Log row removed in this transaction);
		(c) checked; (b): running it again at once changes nothing."""
		never_ran(patch)
		before = sold_state()
		seen = migrate(patch, log=False)
		assert_sold_unchanged(self, before, sold_state(), patch)
		self.assertEqual(rerun_changes(patch), {}, f"{patch}: a second run changed the site")
		return seen

	def assertRerunChangesNothing(self, patch: str) -> None:
		self.assertEqual(rerun_changes(patch), {}, f"{patch}: a forced re-run changed the site")


def kamra_hotel(name: str, currency: str = "EUR") -> str:
	"""A hotel as Kamra stored it: no hotel group, enterprise, contract or go-live."""
	return put("Property", name, property_name=name, currency=currency, city="Antalya", country="Turkey", disabled=0)


def kamra_stay(property: str, status: str, amount, *, days=(10, 13), guest: str | None = None, **values) -> str:
	"""A reservation the legacy engine priced (no TEX pricing source, lock or currency)."""
	ci = add_days(nowdate(), days[0])
	return put("Reservation", f"G76-{frappe.generate_hash(length=8)}", property=property, status=status,
	           guest=guest or "G76 Guest", room_type=values.pop("room_type", None) or f"{property}-STD",
	           check_in_date=ci, check_out_date=add_days(nowdate(), days[1]), adults=2, children=0,
	           amount_before_tax=D(amount), tax_amount=D(0), amount_after_tax=D(amount),
	           **{"tex_price_locked": 0, **values})


def caps(profile: str) -> list[str]:
	return sorted(frappe.get_all("TEX Profile Capability", filters={"parent": profile,
	                                                                  "parenttype": "TEX Permission Profile"},
	                             pluck="capability"))


def grants(user: str) -> list[tuple]:
	return sorted((g.scope_level, g.property, g.permission_profile) for g in frappe.get_all(
		"TEX Access Grant", filters={"user": user}, fields=["scope_level", "property", "permission_profile"]))


# ─── every patch ─────────────────────────────────────────────────────────


class TestEveryPatch(PatchCase):
	def test_every_patch_is_listed_once_and_has_a_behaviour_test(self):
		listed = listed_patches()
		files = sorted(f[:-3] for f in os.listdir(os.path.dirname(import_module("kamra.patches.tex").__file__))
		               if f.startswith("p") and f.endswith(".py"))
		self.assertEqual(sorted(listed), files)                        # no patch file left out, none listed twice
		self.assertEqual(listed, sorted(listed))                        # migration order is patch order
		self.assertEqual(set(BEHAVIOUR), set(listed))
		for patch, where in BEHAVIOUR.items():
			module, cls, *test = where.split(".")
			klass = getattr(import_module(f"kamra.tex.tests.integration.{module}"), cls)
			if test:
				self.assertTrue(callable(getattr(klass, test[0], None)), f"{patch}: {where}")

	def test_each_patch_reruns_as_a_no_op_and_never_touches_what_was_sold(self):
		"""(b) and (c) on this site's data: every patch forced again, in order."""
		for patch in listed_patches():
			before = sold_state()
			migrate(patch)
			self.assertEqual(rerun_changes(patch), {}, f"{patch}: a second run changed the site")
			assert_sold_unchanged(self, before, sold_state(), patch)

	def test_the_chain_runs_on_an_empty_site(self):
		"""(d): a site with nothing to migrate; and again, as a forced re-run."""
		empty_site()
		run_chain(self)
		self.assertEqual(frappe.db.count("Property"), 0)
		self.assertFalse(frappe.get_all("TEX Enterprise"))                # nothing to put in one
		self.assertEqual(set(frappe.get_all("TEX Permission Profile", pluck="name")),
		                 set(DEFAULT_PROFILES) | {"Scope Only"})
		self.assertTrue(frappe.db.get_single_value("TEX Settings", "strict_tenancy"))
		before = site_digest()
		run_chain(self)
		self.assertEqual(digest_changes(before, site_digest()), {})


# ─── the upgrade of a Kamra database ─────────────────────────────────────


class TestUpgradeFromKamra(PatchCase):
	def test_a_kamra_database_upgrades_to_tex(self):
		empty_site()
		beach, city = kamra_hotel("G76 Kamra Beach", "EUR"), kamra_hotel("G76 Kamra City", "TRY")
		for p in (beach, city):
			put("Room Type", f"{p}-STD", property=p, room_type_code="STD", room_type_name="Standard", base_price=100)
		put("Guest", "G76 Guest", guest_name="G76 Guest", first_name="G76", last_name="Guest")
		desk = fx.ensure_user("g76-desk@example.com", ["Front Desk"])          # restricted to the beach
		admin = fx.ensure_user("g76-admin@example.com", ["Hotel Admin"])       # no restriction: every hotel
		gone = fx.ensure_user("g76-gone@example.com", ["Front Desk"])
		frappe.db.set_value("User", gone, "enabled", 0)
		put("User Permission", user=desk, allow="Property", for_value=beach, apply_to_all_doctypes=1, tex_managed=0)
		stays = {
			"confirmed": kamra_stay(beach, "Confirmed", "300.00"),
			"in_house": kamra_stay(city, "Checked In", "4500.00", days=(-1, 2)),
			"checked_out": kamra_stay(city, "Checked Out", "6000.00", days=(-10, -7)),
			"no_show": kamra_stay(beach, "No Show", "120.00", days=(-5, -4)),
			"cancelled": kamra_stay(beach, "Cancelled", "250.00"),
			"requested": kamra_stay(beach, "Requested", "180.00"),
		}
		voucher = put("Discount Voucher", property=beach, voucher_code="kamra10", discount_type="Percent", value=10,
		              max_uses=50, times_used=4)
		boat = put("Experience", property=beach, experience_name="Boat tour", category="Tour", price=55,
		           show_on_booking_page=1)
		amounts = {k: frappe.db.get_value("Reservation", v, ["amount_after_tax", "tax_amount"]) for k, v in stays.items()}
		# before TEX: legacy (non-strict) tenancy opens every hotel to a user without restrictions
		self.assertEqual(scope.permitted_properties(admin), {beach, city})

		run_chain(self)

		# p01: one enterprise and group for every hotel; masters and profiles seeded; the PMS stays visible
		ent = frappe.get_all("TEX Enterprise", pluck="name")
		self.assertEqual(len(ent), 1)
		for p in (beach, city):
			self.assertEqual(frappe.db.get_value("Property", p, "tex_enterprise"), ent[0])
			self.assertTrue(frappe.db.get_value("Property", p, "tex_hotel_group"))
		self.assertTrue(frappe.db.exists("TEX Market", "DE") and frappe.db.exists("TEX Sales Channel", "CALL_CENTER"))
		for name, defaults in DEFAULT_PROFILES.items():
			self.assertEqual(set(caps(name)), set(defaults), name)
		self.assertTrue(frappe.db.get_single_value("TEX Settings", "show_legacy_pms"))   # a stay is in house
		# p02: access made explicit, then strict tenancy: nobody gains or loses a hotel
		self.assertTrue(frappe.db.get_single_value("TEX Settings", "strict_tenancy"))
		self.assertEqual(grants(desk), [("Hotel", beach, "Scope Only")])
		self.assertEqual(grants(admin), [("Hotel", beach, "Scope Only"), ("Hotel", city, "Scope Only")])
		self.assertEqual(grants(gone), [])
		scope.clear_cache()
		self.assertEqual(scope.permitted_properties(desk), {beach})
		self.assertEqual(scope.permitted_properties(admin), {beach, city})
		later = fx.ensure_user("g76-later@example.com", ["Front Desk"])
		self.assertEqual(scope.permitted_properties(later), set())               # strict: a new user sees nothing
		# p04: what the legacy engine sold and still stands is price-locked at its amount
		for k, name in stays.items():
			row = frappe.db.get_value("Reservation", name, ["tex_price_locked", "tex_pricing_source",
			                                                "amount_after_tax", "tax_amount"], as_dict=True)
			self.assertEqual((row.amount_after_tax, row.tax_amount), amounts[k], k)
			locked = k in ("confirmed", "in_house", "checked_out", "no_show")
			self.assertEqual((row.tex_price_locked, row.tex_pricing_source), (1, "Legacy") if locked else (0, None), k)
		from kamra.tex import hooks

		doc = frappe.get_doc("Reservation", stays["confirmed"])
		doc._doc_before_save = frappe.get_doc("Reservation", stays["confirmed"])
		doc.amount_after_tax = D("1.00")
		self.assertEqual(hooks.locked_changes(doc), ["amount_after_tax"])        # the lock holds
		# p05, p06, p12: the voucher is a draft promotion; the experience an extra live since it was copied
		promo = frappe.get_all("TEX Promotion", filters={"legacy_voucher": voucher},
		                       fields=["code", "tex_status", "usage_limit", "times_redeemed"])
		self.assertEqual([(p.code, p.tex_status, p.usage_limit, p.times_redeemed) for p in promo],
		                 [("KAMRA10", "Draft", 50, 4)])
		extra = frappe.get_all("TEX Extra", filters={"legacy_experience": boat},
		                       fields=["tex_status", "revision_no", "amount", "currency"])
		self.assertEqual([(e.tex_status, e.revision_no, D(e.amount), e.currency) for e in extra],
		                 [("Active", 1, D(55), "EUR")])
		# p09: the guest's completed stays, in their hotel's currency (never summed across currencies)
		stats = frappe.db.get_value("Guest", "G76 Guest", ["tex_stays", "tex_lifetime_value",
		                                                   "tex_lifetime_currency"], as_dict=True)
		self.assertEqual((stats.tex_stays, D(stats.tex_lifetime_value), stats.tex_lifetime_currency),
		                 (1, D("6000"), "TRY"))
		# p16: the CRM presets
		self.assertTrue(frappe.db.exists("TEX Guest Segment", {"system_key": "FAMILY"}))
		# p36: hotels that joined TEX in this upgrade are onboarding: the Desk sells them until an
		# administrator sets them live (ADR-052); nothing was ever sold through TEX there
		for p in (beach, city):
			self.assertFalse(frappe.db.get_value("Property", p, "tex_live_from"), p)
			self.assertEqual(legacy.tex_mode(p), "onboarding")
		self.assertFalse(frappe.db.exists("TEX Audit Event", {"action": "hotel.go_live"}))

		# (b) the whole chain again, as an operator forcing it: nothing changes
		before = site_digest()
		run_chain(self)
		self.assertEqual(digest_changes(before, site_digest()), {})


# ─── one patch at a time ─────────────────────────────────────────────────


class TestP01Foundation(PatchCase):
	def test_hotels_masters_profiles_and_settings(self):
		orphan = kamra_hotel("G76 Orphan Hotel")
		frappe.db.delete("TEX Profile Capability", {"parent": "Viewer", "parenttype": "TEX Permission Profile"})
		frappe.db.delete("TEX Permission Profile", "Viewer")
		frappe.db.delete("TEX Market", "PL")
		frappe.db.delete("TEX Sales Channel", "META")
		frappe.db.set_single_value("TEX Settings", {"brand_name": None, "default_sales_channel": None})
		seen = self.first_run("p01_foundation")
		self.assertEqual(set(caps("Viewer")), set(DEFAULT_PROFILES["Viewer"]))
		self.assertTrue(frappe.db.exists("TEX Market", "PL") and frappe.db.exists("TEX Sales Channel", "META"))
		self.assertEqual((frappe.db.get_single_value("TEX Settings", "brand_name"),
		                  frappe.db.get_single_value("TEX Settings", "default_sales_channel")),
		                 ("TEX Engine", "DIRECT_WEB"))
		self.assertEqual([f["User Permission"][0]["fieldname"] for f in seen["custom_fields"]], ["tex_managed"])
		self.assertTrue(frappe.get_meta("User Permission").has_field("tex_managed"))   # synced on this site
		# several tenants: a hotel without a group is never given to one of them by guess
		self.assertGreater(frappe.db.count("TEX Enterprise"), 1)
		self.assertEqual(frappe.db.get_value("Property", orphan, ["tex_hotel_group", "tex_enterprise"]),
		                 (None, None))
		self.assertIn(orphan, str(seen["print"].call_args_list))
		# one tenant with one hotel group: that is where it belongs
		for ent in frappe.get_all("TEX Enterprise", filters={"name": ("!=", fx.ENTERPRISE)}, pluck="name"):
			frappe.db.delete("TEX Hotel Group", {"enterprise": ent})
			frappe.db.delete("TEX Enterprise", ent)
		frappe.db.delete("TEX Hotel Group", {"name": ("!=", fx.GROUP)})
		migrate("p01_foundation")
		self.assertEqual(frappe.db.get_value("Property", orphan, ["tex_hotel_group", "tex_enterprise"]),
		                 (fx.GROUP, fx.ENTERPRISE))


class TestP02AccessGrants(PatchCase):
	def test_access_is_made_explicit_then_tenancy_is_strict(self):
		legacy_hotel = kamra_hotel("G76 Legacy Hotel")
		frappe.db.set_single_value("TEX Settings", "strict_tenancy", 0)
		desk = fx.ensure_user("g76-p02-desk@example.com", ["Front Desk"])
		admin = fx.ensure_user("g76-p02-admin@example.com", ["Hotel Admin"])
		gone = fx.ensure_user("g76-p02-gone@example.com", ["Front Desk"])
		frappe.db.set_value("User", gone, "enabled", 0)
		put("User Permission", user=desk, allow="Property", for_value=legacy_hotel, apply_to_all_doctypes=1,
		    tex_managed=0)
		every = set(frappe.get_all("Property", pluck="name"))
		scope.clear_cache()
		self.assertEqual(scope.permitted_properties(admin), set(scope._all_properties()))   # legacy: every hotel
		self.first_run("p02_access_grants")
		self.assertTrue(frappe.db.get_single_value("TEX Settings", "strict_tenancy"))
		self.assertEqual(grants(desk), [("Hotel", legacy_hotel, "Scope Only")])
		self.assertEqual({g[1] for g in grants(admin)}, every)
		self.assertEqual(grants(gone), [])
		scope.clear_cache()
		self.assertEqual(scope.permitted_properties(desk), {legacy_hotel})
		self.assertEqual(scope.permitted_properties(admin), set(scope._all_properties()))
		# after the upgrade a new user gets access through grants only; a forced re-run of the
		# migration never opens every hotel to them
		log_patch("p02_access_grants")
		later = fx.ensure_user("g76-p02-later@example.com", ["Front Desk"])
		self.assertRerunChangesNothing("p02_access_grants")
		scope.clear_cache()
		self.assertEqual((grants(later), scope.permitted_properties(later)), ([], set()))


class TestP03Indexes(PatchCase):
	def test_the_indexes_exist_and_are_created_only_when_missing(self):
		from kamra.tex import setup

		for doctype, fields, name in setup.TEX_INDEXES:
			for f in fields:
				self.assertTrue(frappe.db.has_column(doctype, f), f"{name}: {doctype}.{f}")
			# Frappe's schema sync drops a single-column index on a field without search_index
			# (``get_column_index``); a composite one it leaves alone
			self.assertGreaterEqual(len(fields), 2, name)
		self.assertEqual(setup.missing_indexes(), [])                   # this site's migration made them all
		self.assertEqual(self.first_run("p03_indexes")["add_index"], [])   # nothing to create: no DDL
		real = frappe.local.db.has_index
		with mock.patch.object(frappe.local.db, "has_index",
		                       side_effect=lambda table, index: index != "tex_inv_rt_date" and real(table, index)):
			seen = migrate("p03_indexes")
		self.assertEqual(seen["add_index"], [("TEX Inventory Day", ("room_type", "inventory_date"), "tex_inv_rt_date")])

	def test_p39_creates_the_lookup_indexes_that_survive_a_sync(self):
		from kamra.tex import setup

		new = {"tex_booking_room", "tex_xalloc_res_status", "tex_comm_queue_status"}
		for doctype, fields, name in setup.TEX_INDEXES:
			if name in new:                     # not the single-column index a sync would drop
				idx = frappe.db.get_column_index(f"tab{doctype}", fields[0])
				self.assertNotEqual(idx.Key_name if idx else None, name)
		self.assertEqual(self.first_run("p39_lookup_indexes")["add_index"], [])   # migrated: nothing missing
		real = frappe.local.db.has_index
		with mock.patch.object(frappe.local.db, "has_index",
		                       side_effect=lambda table, index: index not in new and real(table, index)):
			seen = migrate("p39_lookup_indexes")
		self.assertEqual(seen["add_index"], [("Reservation", ("tex_booking", "tex_room_index"), "tex_booking_room"),
		                                     ("TEX Extra Allocation", ("reservation", "status"), "tex_xalloc_res_status"),
		                                     ("TEX Communication", ("email_queue", "status"), "tex_comm_queue_status")])


class TestP04LegacyPriceLock(PatchCase):
	def test_standing_legacy_stays_are_locked_at_their_amount(self):
		hotel = kamra_hotel("G76 Legacy Hotel")
		stays = {s: kamra_stay(hotel, s, "210.00") for s in ("Confirmed", "Checked In", "Checked Out", "No Show",
		                                                       "Cancelled", "Pending Payment", "Requested")}
		manual = kamra_stay(hotel, "Confirmed", "99.00", tex_pricing_source="Manual")
		self.first_run("p04_lock_legacy_prices")
		for status, name in stays.items():
			row = frappe.db.get_value("Reservation", name, ["tex_price_locked", "tex_pricing_source",
			                                                "amount_after_tax"], as_dict=True)
			locked = status in ("Confirmed", "Checked In", "Checked Out", "No Show")
			self.assertEqual((row.tex_price_locked, row.tex_pricing_source, row.amount_after_tax),
			                 (1, "Legacy", D("210.00")) if locked else (0, None, D("210.00")), status)
		self.assertEqual(frappe.db.get_value("Reservation", manual, ["tex_price_locked", "tex_pricing_source"]),
		                 (0, "Manual"))
		# a stay the legacy engine sells after the upgrade (a hotel outside TEX) stays the Desk's
		log_patch("p04_lock_legacy_prices")
		later = kamra_stay(hotel, "Confirmed", "150.00")
		self.assertRerunChangesNothing("p04_lock_legacy_prices")
		self.assertEqual(frappe.db.get_value("Reservation", later, "tex_price_locked"), 0)


CAPABILITY_PATCHES = {"p08_confirm_unpaid_capability": ("reservation.confirm_unpaid",),
                      "p12_effective_dated_extras_and_taxes": ("tax.edit",),
                      "p17_loyalty_admin": ("loyalty.edit",),
                      "p18_channel_distribution": ("channel.view", "channel.manage"),
                      "p23_system_status_alerts": ("system.monitor",),
                      "p29_channel_binding": ("price.any_channel",)}


class TestCapabilityPatches(PatchCase):
	"""p08, p12, p17, p18, p23, p29 give a new capability to the seeded profiles that carry it
	(p29: also to custom profiles that publish contracts), once, at the upgrade that brings it. A
	capability an administrator removed since is not given back by a forced re-run."""

	def test_each_capability_reaches_its_profiles_once(self):
		custom = frappe.get_doc({"doctype": "TEX Permission Profile", "profile_name": "G76 Custom Desk",
		                         "capabilities": [{"capability": "reservation.view"}]}).insert(ignore_permissions=True)
		for patch, added in CAPABILITY_PATCHES.items():
			frappe.db.delete("TEX Profile Capability", {"capability": ("in", added)})
			self.first_run(patch)
			for name, defaults in DEFAULT_PROFILES.items():
				for cap in added:
					self.assertEqual(caps(name).count(cap), 1 if cap in defaults else 0, f"{patch}: {name} {cap}")
			self.assertEqual(caps(custom.name), ["reservation.view"], patch)
			# an administrator takes it away again after the upgrade: a forced re-run keeps it away
			log_patch(patch)
			holder = next(n for n, d in DEFAULT_PROFILES.items() if added[0] in d)
			frappe.db.delete("TEX Profile Capability", {"parent": holder, "capability": added[0]})
			self.assertRerunChangesNothing(patch)
			self.assertNotIn(added[0], caps(holder), patch)


class TestP09GuestStats(PatchCase):
	def test_completed_stays_in_their_own_currency(self):
		eur, tl = fx.PROPERTY, kamra_hotel("G76 Istanbul Legacy", "TRY")
		guest = put("Guest", "G76 Stats Guest", guest_name="G76 Stats Guest", first_name="G76", last_name="Stats",
		            tex_stays=99, tex_lifetime_value=D("1"), tex_lifetime_currency="USD")
		kamra_stay(eur, "Checked Out", "300.00", days=(-30, -27), guest=guest, tex_currency="EUR",
		           tex_total_amount=D("300.00"))
		for amount in ("4000.00", "2500.50"):                            # legacy stays: the hotel's currency
			kamra_stay(tl, "Checked Out", amount, days=(-60, -58), guest=guest)
		kamra_stay(tl, "Confirmed", "900.00", days=(20, 22), guest=guest)       # not a stay yet
		kamra_stay(tl, "Inquiry", "999.00", days=(-50, -48), guest=guest)       # never sold
		kamra_stay(tl, "Cancelled", "700.00", days=(-9, -8), guest=guest)
		kamra_stay(tl, "No Show", "800.00", days=(-7, -6), guest=guest)
		self.first_run("p09_guest_stats_completed_stays")
		row = frappe.db.get_value("Guest", guest, ["tex_stays", "tex_lifetime_value", "tex_lifetime_currency",
		                                           "tex_last_stay"], as_dict=True)
		self.assertEqual((row.tex_stays, D(row.tex_lifetime_value), row.tex_lifetime_currency),
		                 (3, D("6500.50"), "TRY"))
		self.assertEqual(getdate(row.tex_last_stay), getdate(add_days(nowdate(), -27)))


class TestP13ExtraInventory(PatchCase):
	def test_stays_sold_before_an_extra_was_limited_hold_their_units(self):
		fx.create_contract(self.f, code="G76X")
		from kamra.tex.services import booking, quoting

		offer = pick(search_std(fx.d(6, 10), fx.d(6, 12), [{"adults": 2}]))
		q = quoting.create_quote(offer["rooms"][0]["offer_key"], extras=[{"code": "TRF"}])
		self.assertTrue(q["ok"], q)
		b = booking.create_booking(quote_ids=[q["quote_id"]], guest={"first_name": "Gee", "last_name": "Seventysix",
		                                                             "email": "g76x@example.com"},
		                           payment_method="Card", confirm_without_payment=True)     # staff: confirmed
		res = b["rooms"][0]["reservation"]
		self.assertFalse(frappe.db.exists("TEX Extra Allocation", {"reservation": res}))   # not limited when sold
		trf = frappe.db.get_value("TEX Extra", {"property": fx.PROPERTY, "extra_code": "TRF", "tex_status": "Active"})
		frappe.db.set_value("TEX Extra", trf, {"inventory_tracked": 1, "daily_capacity": 5})    # limited since
		seen = self.first_run("p13_extra_inventory")
		self.assertEqual({r[1] for r in seen["reload_doc"]}, {"doctype"})
		held = frappe.get_all("TEX Extra Allocation", filters={"reservation": res},
		                      fields=["extra_code", "units", "status", "service_date"])
		self.assertEqual([(a.extra_code, a.units, a.status) for a in held], [("TRF", 1, "Confirmed")])
		self.assertEqual(frappe.db.get_value("TEX Extra Inventory Day", {"property": fx.PROPERTY, "extra_code": "TRF",
		                                                                 "service_date": held[0].service_date}, "sold"), 1)


class TestP18ChannelDistribution(PatchCase):
	def test_keys_are_encrypted_and_channel_managers_get_no_reservation_events(self):
		from frappe.utils.password import get_decrypted_password, remove_encrypted_password

		pms = frappe.get_doc({"doctype": "TEX Integration Connection", "label": "G76 PMS", "property": fx.PROPERTY,
		                      "category": "PMS", "adapter": "webhook", "enabled": 0}).insert(ignore_permissions=True)
		cm = frappe.get_doc({"doctype": "TEX Integration Connection", "label": "G76 CM", "property": fx.PROPERTY,
		                     "category": "Channel Manager", "adapter": "sandbox_channel", "enabled": 0}).insert(
			ignore_permissions=True)
		remove_encrypted_password("TEX Integration Connection", pms.name, "api_key")
		frappe.db.sql("UPDATE `tabTEX Integration Connection` SET api_key=%s WHERE name=%s", ("g76-plain-key", pms.name))
		to_pms = put("TEX Integration Outbox", connection=pms.name, property=fx.PROPERTY, event="reservation.created",
		             status="Pending")
		to_cm = put("TEX Integration Outbox", connection=cm.name, property=fx.PROPERTY, event="reservation.created",
		            status="Pending")
		seen = self.first_run("p18_channel_distribution")
		self.assertEqual(frappe.db.get_value("TEX Integration Connection", pms.name, "api_key"), "*" * 13)
		self.assertEqual(get_decrypted_password("TEX Integration Connection", pms.name, "api_key"), "g76-plain-key")
		self.assertNotIn("g76-plain-key", str(seen["print"].call_args_list))
		self.assertEqual(frappe.db.get_value("TEX Integration Outbox", to_pms, ["kind", "status"]),
		                 ("Reservation", "Pending"))
		self.assertEqual(frappe.db.get_value("TEX Integration Outbox", to_cm, ["kind", "status"]),
		                 ("Reservation", "Dead"))


class TestP23MailStatus(PatchCase):
	def test_queued_mails_are_linked_where_exactly_one_queue_row_fits(self):
		now = now_datetime()
		sent = put("Email Queue", reference_doctype="TEX Booking", reference_name="G76-BK-1", status="Sent",
		           creation=add_to_date(now, seconds=-10), modified=add_to_date(now, seconds=-5))
		for _ in range(2):
			put("Email Queue", reference_doctype="TEX Booking", reference_name="G76-BK-2", status="Sent",
			    creation=add_to_date(now, seconds=-10))
		one = put("TEX Communication", channel="Email", direction="Outbound", status="Queued", booking="G76-BK-1",
		          template="booking_confirmed", property=fx.PROPERTY)
		two = put("TEX Communication", channel="Email", direction="Outbound", status="Queued", booking="G76-BK-2",
		          template="booking_confirmed", property=fx.PROPERTY)
		self.first_run("p23_system_status_alerts")
		self.assertEqual(frappe.db.get_value("TEX Communication", one, ["email_queue", "status"]), (sent, "Sent"))
		self.assertEqual(frappe.db.get_value("TEX Communication", two, ["email_queue", "status"]), (None, "Queued"))


class TestReportingPatches(PatchCase):
	"""p19 and p24 report what an owner must fix (audited, so the list outlives the migration
	output): once, however often the patch runs; again only when what they report changed."""

	def test_p19_reports_a_gated_account_once(self):
		acc = put("TEX Payment Provider Account", label="G76 mock in production", property=fx.PROPERTY,
		          provider="Mock", environment="Production", enabled=1)
		self.first_run("p19_payments_go_live_check")
		self.assertRerunChangesNothing("p19_payments_go_live_check")
		events = frappe.get_all("TEX Audit Event", filters={"action": "payment_account.gated", "reference_name": acc},
		                        pluck="new_value")
		self.assertEqual(len(events), 1)
		self.assertEqual(json.loads(events[0])["open_charges"], 0)

	def test_p24_reports_public_active_content_and_site_images_once(self):
		svg = put("File", file_name="g76-logo.svg", file_url="/files/g76-logo.svg", is_private=0, is_folder=0,
		          folder="Home")
		site = put("TEX Booking Site", site_slug="g76-site", site_name="G76", property=fx.PROPERTY, enabled=0,
		           logo="/files/g76-logo.svg")
		self.first_run("p24_g83_review")
		self.assertRerunChangesNothing("p24_g83_review")
		self.assertEqual(frappe.db.count("TEX Audit Event", {"action": "file.public_active_content",
		                                                      "reference_name": svg}), 1)
		self.assertEqual(frappe.db.count("TEX Audit Event", {"action": "booking_site.invalid_image",
		                                                      "reference_name": site}), 1)
		self.assertEqual(frappe.db.get_value("File", svg, "is_private"), 0)       # reported, left to the owner


class TestSmallPatches(PatchCase):
	def test_p07_forgets_payment_link_urls(self):
		link = put("TEX Payment Link", property=fx.PROPERTY, status="Active", amount=D("80"), currency="EUR",
		           public_url="https://example.com/book/pay/secret-token-g76", token_hash="x" * 64)
		self.first_run("p07_forget_payment_link_urls")
		self.assertIsNone(frappe.db.get_value("TEX Payment Link", link, "public_url"))
		self.assertEqual(frappe.db.get_value("TEX Payment Link", link, "token_hash"), "x" * 64)

	def test_p11_p20_only_sync_their_doctypes(self):
		for patch, synced, field in (
				("p11_allocation_idempotency", [("tex_payments", "doctype", "tex_payment_allocation")],
				 ("TEX Payment Allocation", "idempotency_key")),
				("p20_guest_change_requests", [("tex_booking", "doctype", "tex_guest_change_request"),
				                               ("kamra", "doctype", "property")],
				 ("Property", "tex_lower_price_refund"))):
			self.assertEqual(self.first_run(patch)["reload_doc"], synced, patch)
			self.assertTrue(frappe.db.has_column(*field), patch)            # synced on this site

	def test_p14_gives_extras_an_order_cutoff(self):
		# the synced column is NOT NULL with 0 (existing extras: until the day they are used), so the
		# patch's NULL → 0 is a safety net; a cutoff someone set is kept
		col = frappe.db.sql("""SELECT is_nullable, column_default FROM information_schema.columns
		                       WHERE table_schema = DATABASE() AND table_name = 'tabTEX Extra'
		                         AND column_name = 'order_cutoff_hours'""")[0]
		self.assertEqual((col[0], str(col[1]).strip("'")), ("NO", "0"))
		kept = put("TEX Extra", property=fx.PROPERTY, extra_code="G76CUT", extra_name="Cut", currency="EUR",
		           amount=D(10), pricing_mode="UNIT", order_cutoff_hours=24, tex_status="Draft")
		plain = put("TEX Extra", property=fx.PROPERTY, extra_code="G76NOC", extra_name="No cutoff", currency="EUR",
		            amount=D(10), pricing_mode="UNIT", tex_status="Draft")
		seen = self.first_run("p14_post_booking_extras")
		self.assertEqual(seen["reload_doc"], [("tex_commercial", "doctype", "tex_extra"),
		                                      ("tex_booking", "doctype", "tex_reservation_revision")])
		self.assertEqual(frappe.db.get_value("TEX Extra", kept, "order_cutoff_hours"), 24)
		self.assertEqual(frappe.db.get_value("TEX Extra", plain, "order_cutoff_hours"), 0)

	def test_p33_gives_group_grant_events_their_hotels(self):
		group = put("TEX Audit Event", event_time=now_datetime(), action="grant.create",
		            reference_doctype="TEX Access Grant", reference_name="G76-GRANT-1", actor="Administrator",
		            new_value=json.dumps({"scope_level": "Hotel Group", "hotel_group": fx.GROUP, "user": "x@e.com"}))
		hotel = put("TEX Audit Event", event_time=now_datetime(), action="grant.create", property=fx.PROPERTY,
		            reference_doctype="TEX Access Grant", reference_name="G76-GRANT-2", actor="Administrator",
		            new_value=json.dumps({"scope_level": "Hotel", "property": fx.PROPERTY, "user": "x@e.com"}))
		self.first_run("p33_audit_scope")
		self.assertEqual(frappe.db.get_value("TEX Audit Event", group, "hotel_group"), fx.GROUP)
		self.assertEqual(set(frappe.get_all("TEX Audit Scope", filters={"event": group}, pluck="property")),
		                 set(frappe.get_all("Property", filters={"tex_hotel_group": fx.GROUP, "disabled": 0},
		                                    pluck="name")))
		self.assertEqual(frappe.db.get_value("TEX Audit Event", hotel, ["hotel_group", "property"]),
		                 (None, fx.PROPERTY))
		self.assertFalse(frappe.db.exists("TEX Audit Scope", {"event": hotel}))

	def test_p34_dates_released_coupon_uses(self):
		at = get_datetime("2026-03-01 10:00:00")
		released = put("TEX Promotion Redemption", promotion="G76-PROMO", status="Released", modified=at)
		held = put("TEX Promotion Redemption", promotion="G76-PROMO", status="Committed", released_at=at)
		self.first_run("p34_redemption_released_at")
		self.assertEqual(get_datetime(frappe.db.get_value("TEX Promotion Redemption", released, "released_at")), at)
		self.assertIsNone(frappe.db.get_value("TEX Promotion Redemption", held, "released_at"))
