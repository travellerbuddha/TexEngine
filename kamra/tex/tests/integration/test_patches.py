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
	"p40_crm_privacy_review": "test_crm_privacy.TestAbandonedPrivacy."
	                          "test_p40_makes_cases_anonymous_where_the_consent_no_longer_holds",
	"p45_crm_privacy_second_review": "test_crm_privacy_review.TestP45."
	                                 "test_p45_indexes_history_ledger_hotels_erased_profiles_and_anonymous_cases",
	"p46_report_indexes": "test_patches.TestP03Indexes.test_p46_creates_the_report_indexes",
	"p47_g64_site_slugs": "test_patches.TestReportingPatches.test_p47_reports_sites_named_like_an_admin_page_once",
	"p48_crm_privacy_third_review": "test_crm_third_review.TestP48."
	                                "test_p48_marks_earlier_erasures_and_removes_what_they_left",
	"p49_payment_attempt_deadline": "test_patches.TestSmallPatches.test_p11_p20_only_sync_their_doctypes",
	"p50_payment_reconciliation": "test_patches.TestSmallPatches.test_p11_p20_only_sync_their_doctypes",
	"p51_hold_minutes_per_payment_method": "test_patches.TestSmallPatches.test_p51_gives_each_payment_method_its_hold",
	"p52_partly_cancelled_awaiting_payment": "test_hold_payment_race.TestPartialCancellation."
	                                         "test_p52_puts_stuck_bookings_back_to_waiting_for_their_payment",
	"p53_payment_captured_at": "test_patches.TestSmallPatches.test_p11_p20_only_sync_their_doctypes",
	"p54_never_confirmed_leftovers": "test_hold_payment_race.TestNeverConfirmedLeftovers."
	                                 "test_p54_cancels_leftovers_and_parks_their_money_without_mail",
	"p55_web_transfer_hold": "test_patches.TestSmallPatches.test_p55_gives_web_transfers_their_hold",
	"p56_open_ended_versions": "test_patches.TestSmallPatches.test_p56_gives_versions_the_roll_superseded_their_state",
	"p59_policy_currency": "test_patches.TestReportingPatches.test_p59_syncs_the_policies_and_reports_fixed_amounts_to_review",
	"p60_promotion_code_key": "test_patches.TestReportingPatches.test_p60_stores_codes_by_their_key_and_reports_a_clash_once",
	"p64_agent_log_read_only": "test_patches.TestP64AgentLogReadOnly",
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
ROW_KEYS = {"__Auth": ("doctype", "name", "fieldname"), "tabSingles": ("doctype", "field")}
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
		# a row is named by its key, never by a value (an encrypted password, a setting): the value
		# is only hashed, and a failure message prints names (review of G-76, L1)
		key = [cols.index(c) for c in ROW_KEYS.get(table, ("name",))]
		out[table] = {(tuple(row[i] for i in key) if len(key) > 1 else row[key[0]]):
		              hashlib.sha1(repr(row).encode()).hexdigest() for row in rows}
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


DISPOSABLE = "tex_disposable_test_site"


def disposable_site() -> bool:
	"""A site made for this test run and dropped after it (its site config says so)."""
	return bool(frappe.conf.get(DISPOSABLE))


def empty_site() -> None:
	"""No hotel, stay, guest, legacy voucher or experience and no TEX record, as a site that never
	ran TEX, in this transaction only (tearDown rolls it back; nothing may commit, ``refuse_commits``).
	Only ever on a disposable site."""
	if not disposable_site():
		raise AssertionError(f"empty_site() runs only on a disposable site ({DISPOSABLE}); this is {frappe.local.site}")
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


def representative_site(case) -> None:
	"""What the whole-site tests run the patches over: a published contract and a stay TEX sold
	(price-locked, its snapshot and revisions), legacy stays, a voucher and an experience."""
	from kamra.tex.services import booking, quoting

	fx.create_contract(case.f, code="G76W")
	offer = pick(search_std(fx.d(6, 10), fx.d(6, 12), [{"adults": 2}]))
	q = quoting.create_quote(offer["rooms"][0]["offer_key"], extras=[{"code": "TRF"}])
	assert q["ok"], q
	booking.create_booking(quote_ids=[q["quote_id"]], guest={"first_name": "Gee", "last_name": "Whole",
	                                                         "email": "g76w@example.com"},
	                       payment_method="Card", confirm_without_payment=True)
	hotel = kamra_hotel("G76 Whole Legacy", "TRY")
	for status in ("Confirmed", "Checked Out", "Cancelled"):
		kamra_stay(hotel, status, "900.00", days=(-9, -7) if status == "Checked Out" else (10, 12))
	put("Discount Voucher", property=hotel, voucher_code="whole5", discount_type="Percent", value=5)
	put("Experience", property=hotel, experience_name="Hamam", category="Spa", price=40)


def run_chain(case) -> None:
	"""Every TEX patch in migration order, as one ``bench migrate`` runs them; (c) after each."""
	for patch in listed_patches():
		before = sold_state()
		migrate(patch)
		assert_sold_unchanged(case, before, sold_state(), patch)


class CommitRefused(AssertionError):
	"""A commit while a migration test holds its changes: it would make them (and the empty-site
	tests' deletions) permanent on the site."""


def refuse_commits(case) -> None:
	"""From now until ``case`` has rolled back, this connection refuses to commit, whoever asks: a
	patch, the test, or Frappe's ``run-tests`` after a Ctrl-C (C1, review of G-76). On
	KeyboardInterrupt unittest skips tearDown and the cleanups, and ``_cleanup_after_tests`` then
	commits the connection. So:
	- ``commit()`` raises, and so do ``sql_ddl`` and ``add_index``, which commit first;
	- a bare COMMIT statement raises;
	- DDL or START TRANSACTION after a write raises already (Frappe's ``ImplicitCommitError``).
	The refusal is lifted by a cleanup that runs after the test's rollback. An interrupted run never
	reaches it: it ends on the refused commit, and MariaDB rolls the dropped connection back."""
	db = frappe.local.db
	real_sql = db.sql

	def commit(*args, **kwargs):
		raise CommitRefused("a migration test holds its changes: nothing is committed until it rolled back")

	def sql(query, *args, **kwargs):
		if get_query_type(str(query)) == "commit":
			commit()
		return real_sql(query, *args, **kwargs)

	patches = [mock.patch.object(db, "commit", commit), mock.patch.object(db, "sql", sql)]
	for p in patches:
		p.start()
	case.addCleanup(lambda: [p.stop() for p in reversed(patches)])
	case.addCleanup(db.rollback)              # cleanups run last-in first-out: the rollback comes first


class PatchCase(TexTestCase):
	def setUp(self):
		refuse_commits(self)                     # before anything is written (C1)
		super().setUp()

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

	def test_no_test_runs_a_patchs_schema_sync_for_real(self):
		"""M3 (review of G-76): a test that runs a patch whose first steps sync a DocType or create
		an index stubs them (``sandbox()``, ``migrate()`` or a mocked ``reload_doc``): a real sync can
		commit the test's rows into the site."""
		import ast
		import re

		here = os.path.dirname(__file__)
		ddl = {p for p in listed_patches()
		       if re.search(r"reload_doc|ensure_indexes|add_index|create_custom_fields",
		                    open(import_module(PREFIX + p).__file__).read())}
		stubbed = ("sandbox(", "migrate(", "first_run(", "reload_doc")
		offenders = []
		for fname in sorted(f for f in os.listdir(here) if f.startswith("test_") and f.endswith(".py")):
			src = open(os.path.join(here, fname)).read()
			for cls in [n for n in ast.parse(src).body if isinstance(n, ast.ClassDef)]:
				setup_src = "".join(ast.get_source_segment(src, f) for f in cls.body
				                    if isinstance(f, ast.FunctionDef) and f.name == "setUp")
				for fn in [f for f in cls.body if isinstance(f, ast.FunctionDef)]:
					body = ast.get_source_segment(src, fn)
					alias = {m.group(2) or m.group(1): m.group(1)
					         for m in re.finditer(r"import (p\d\d_\w+)(?: as (\w+))?", body + src)}
					ran = {alias.get(a, a) for a in re.findall(r"(\w+)\.execute\(", body)} & set(listed_patches())
					if ran & ddl and not any(x in body or x in setup_src for x in stubbed):
						offenders.append(f"{fname}::{cls.name}.{fn.name}: {sorted(ran & ddl)}")
		self.assertEqual(offenders, [])

	def test_the_digest_names_passwords_by_record_never_by_their_value(self):
		"""L1 (review of G-76): an encrypted password is compared, never printed as a key."""
		from frappe.utils.password import set_encrypted_password

		conn = frappe.get_doc({"doctype": "TEX Integration Connection", "label": "G76 digest", "category": "PMS",
		                       "adapter": "webhook", "enabled": 0}).insert(ignore_permissions=True)
		set_encrypted_password("TEX Integration Connection", conn.name, "g76-digest-secret", "api_key")
		stored = frappe.db.sql("SELECT password FROM `__Auth` WHERE doctype=%s AND name=%s AND fieldname='api_key'",
		                       ("TEX Integration Connection", conn.name))[0][0]
		before = site_digest()
		self.assertIn(("TEX Integration Connection", conn.name, "api_key"), before["__Auth"])
		self.assertNotIn(stored, repr(list(before["__Auth"])))
		set_encrypted_password("TEX Integration Connection", conn.name, "g76-digest-other", "api_key")
		self.assertEqual(digest_changes(before, site_digest()),
		                 {"__Auth": {"added": [], "removed": [],
		                             "changed": [("TEX Integration Connection", conn.name, "api_key")]}})



# ─── tests that change the whole site: a disposable site only ────────────


class WholeSiteCase(PatchCase):
	"""Tests that run patches over the whole site or empty it. They run only on a disposable site
	(``tex_disposable_test_site`` in its site config: CI's, or one made for the run by
	``/home/user/bench/scratch/disposable_test.sh``), never on a shared one: even rolled back, their
	deletes and whole-table updates hold locks other sessions wait on (M4, review of G-76), and they
	must never be one commit away from wiping a site that others use (C1)."""

	def setUp(self):
		if not disposable_site():
			self.skipTest(f"changes the whole site: runs only on a site with {DISPOSABLE} set")
		super().setUp()


class TestWholeSite(WholeSiteCase):
	def test_each_patch_reruns_as_a_no_op_and_never_touches_what_was_sold(self):
		"""(b) and (c): every patch forced again, in order, over a site with a published contract, a
		price-locked stay TEX sold, legacy stays, a voucher and an experience."""
		representative_site(self)
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


class TestUpgradeFromKamra(WholeSiteCase):
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
		if frappe.db.count("TEX Enterprise") < 2:                  # a site of several tenants, on any site
			ent = frappe.get_doc({"doctype": "TEX Enterprise", "enterprise_name": "G76 Second Tenant"}).insert(
				ignore_permissions=True).name
			frappe.get_doc({"doctype": "TEX Hotel Group", "group_name": "G76 Second Group",
			                "enterprise": ent}).insert(ignore_permissions=True)
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
		never_ran("p01_foundation")                                  # a first run on such a site
		migrate("p01_foundation")
		self.assertEqual(frappe.db.get_value("Property", orphan, ["tex_hotel_group", "tex_enterprise"]),
		                 (fx.GROUP, fx.ENTERPRISE))

	def test_a_forced_rerun_leaves_what_administrators_changed(self):
		"""M2 (review of G-76): after the upgrade, markets and channels deleted, the brand name
		cleared, the legacy PMS hidden and a hotel kept outside TEX stay as administrators left
		them, whether the site has one tenant or several."""
		log_patch("p01_foundation")
		kamra_stay(fx.PROPERTY, "Checked In", "100.00", days=(-1, 1))     # the PMS is in use
		kept_out = kamra_hotel("G76 Kept Outside")
		for ent in frappe.get_all("TEX Enterprise", filters={"name": ("!=", fx.ENTERPRISE)}, pluck="name"):
			frappe.db.delete("TEX Hotel Group", {"enterprise": ent})
			frappe.db.delete("TEX Enterprise", ent)
		frappe.db.delete("TEX Hotel Group", {"name": ("!=", fx.GROUP)})     # one tenant, one group
		frappe.db.delete("TEX Market", "PL")
		frappe.db.delete("TEX Sales Channel", "META")
		frappe.db.set_single_value("TEX Settings", {"brand_name": None, "show_legacy_pms": 0})
		self.assertRerunChangesNothing("p01_foundation")
		self.assertFalse(frappe.db.exists("TEX Market", "PL") or frappe.db.exists("TEX Sales Channel", "META"))
		self.assertEqual((frappe.db.get_single_value("TEX Settings", "brand_name") or None,
		                  frappe.db.get_single_value("TEX Settings", "show_legacy_pms")), (None, 0))
		self.assertEqual(frappe.db.get_value("Property", kept_out, ["tex_hotel_group", "tex_enterprise"]),
		                 (None, None))
		self.assertFalse(legacy.is_tex_hotel(kept_out))


class TestRanBefore(PatchCase):
	"""H1 (review of G-76): a run is a Patch Log row that is not ``skipped``, whether the line carries
	a suffix or not. ``bench migrate --skip-failing`` logs a failed patch as skipped and runs it again
	next time: that run is a first run."""

	def test_the_patch_log_decides(self):
		from kamra.tex import setup

		name = PREFIX + "p04_lock_legacy_prices"
		never_ran("p04_lock_legacy_prices")
		frappe.db.delete("Patch Log", {"patch": ("like", name + "%")})
		self.assertFalse(setup.ran_before(name))
		put("Patch Log", patch=name, skipped=1)                                  # failed, skipped
		put("Patch Log", patch=PREFIX + "p04XlockXlegacyXprices #x", skipped=0)  # "_" is no wildcard
		put("Patch Log", patch=name + "X", skipped=0)                             # another patch
		self.assertFalse(setup.ran_before(name))
		put("Patch Log", patch=name + " #2026-10-01", skipped=0)                  # re-issued with a suffix
		self.assertTrue(setup.ran_before(name))

	def test_a_patch_skipped_by_a_failing_migration_runs_whole_next_time(self):
		never_ran("p04_lock_legacy_prices")
		put("Patch Log", patch=PREFIX + "p04_lock_legacy_prices", skipped=1)
		stay = kamra_stay(kamra_hotel("G76 Skipped Once"), "Confirmed", "210.00")
		migrate("p04_lock_legacy_prices")
		self.assertEqual(frappe.db.get_value("Reservation", stay, ["tex_price_locked", "tex_pricing_source"]),
		                 (1, "Legacy"))

	def test_a_suffixed_patch_line_counts_as_run(self):
		never_ran("p04_lock_legacy_prices")
		put("Patch Log", patch=PREFIX + "p04_lock_legacy_prices #2026-10-01", skipped=0)
		stay = kamra_stay(kamra_hotel("G76 Suffixed"), "Confirmed", "210.00")
		migrate("p04_lock_legacy_prices", log=False)
		self.assertEqual(frappe.db.get_value("Reservation", stay, "tex_price_locked"), 0)


class TestP36GoLive(PatchCase):
	def test_a_forced_rerun_leaves_a_hotel_set_back_to_onboarding(self):
		"""M1 (review of G-76): an administrator put a hotel back to onboarding after the upgrade
		(``legacy.set_live``, audited ``hotel.go_live_undo``): a forced re-run keeps it there."""
		fx.create_contract(self.f, code="G76P36")                   # TEX sells the hotel
		never_ran("p36_g92_review")
		frappe.db.set_value("Property", fx.PROPERTY, "tex_live_from", None)
		self.first_run("p36_g92_review")                            # the upgrade sets it live
		self.assertTrue(frappe.db.get_value("Property", fx.PROPERTY, "tex_live_from"))
		log_patch("p36_g92_review")
		legacy.set_live(fx.PROPERTY, False, "cut-over postponed")
		self.assertRerunChangesNothing("p36_g92_review")
		self.assertFalse(frappe.db.get_value("Property", fx.PROPERTY, "tex_live_from"))
		self.assertEqual(legacy.tex_mode(fx.PROPERTY), "onboarding")


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

	def test_one_unreadable_index_does_not_stop_the_others(self):
		"""L6 (review of G-76): an index whose table cannot be read is logged and skipped; the other
		missing ones are still created (as before ``missing_indexes``)."""
		from kamra.tex import setup

		real = frappe.local.db.has_index

		def has_index(table, index):
			if index == "tex_ari_day_lookup":
				raise frappe.db.ProgrammingError(1146, f"Table '{table}' doesn't exist")
			return index != "tex_inv_rt_date" and real(table, index)

		logged = frappe.db.count("Error Log", {"method": "TEX index tex_ari_day_lookup"})
		with mock.patch.object(frappe.local.db, "has_index", side_effect=has_index):
			self.assertEqual([i[2] for i in setup.missing_indexes()], ["tex_inv_rt_date"])
			seen = migrate("p03_indexes")
		self.assertEqual(seen["add_index"], [("TEX Inventory Day", ("room_type", "inventory_date"), "tex_inv_rt_date")])
		self.assertEqual(frappe.db.count("Error Log", {"method": "TEX index tex_ari_day_lookup"}), logged + 2)

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


	def test_p46_creates_the_report_indexes(self):
		"""G-46 review (M5): reports read reservations by hotel and arrival, funnel events by hotel or
		booking site and time, instead of scanning every tenant's rows."""
		from kamra.tex import setup

		new = {"tex_res_prop_ci": ("Reservation", ("property", "check_in_date")),
		       "tex_funnel_prop_time": ("TEX Funnel Event", ("property", "occurred_at")),
		       "tex_funnel_site_time": ("TEX Funnel Event", ("site", "occurred_at"))}
		have = {name: (dt, tuple(fields)) for dt, fields, name in setup.TEX_INDEXES}
		self.assertEqual({k: have.get(k) for k in new}, new)
		for name, (doctype, _fields) in new.items():
			self.assertTrue(frappe.db.has_index(f"tab{doctype}", name), name)       # the migration made them
		self.assertEqual(self.first_run("p46_report_indexes")["add_index"], [])     # nothing missing: no DDL
		real = frappe.local.db.has_index
		with mock.patch.object(frappe.local.db, "has_index",
		                       side_effect=lambda table, index: index not in new and real(table, index)):
			seen = migrate("p46_report_indexes")
		self.assertEqual(sorted(seen["add_index"]), sorted((dt, f, n) for n, (dt, f) in new.items()))
		self.assertRerunChangesNothing("p46_report_indexes")


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

	def test_p19_does_not_report_an_account_again_when_a_charge_is_touched(self):
		"""L5 (review of G-76): the open charges are listed by name, not by when they were last
		written, so touching one does not make the same report look new."""
		acc = put("TEX Payment Provider Account", label="G76 mock charges", property=fx.PROPERTY,
		          provider="Mock", environment="Production", enabled=1)
		older, newer = add_to_date(now_datetime(), hours=-2), add_to_date(now_datetime(), hours=-1)
		for name, at in (("G76-TXN-A", older), ("G76-TXN-B", newer)):
			put("TEX Payment Transaction", name, provider_account=acc, property=fx.PROPERTY, txn_type="Charge",
			    status="Pending", amount=D("10"), currency="EUR", modified=at)
		self.first_run("p19_payments_go_live_check")
		frappe.db.set_value("TEX Payment Transaction", "G76-TXN-A", "modified", now_datetime(),
		                    update_modified=False)                  # a charge is touched after the report
		self.assertRerunChangesNothing("p19_payments_go_live_check")
		events = frappe.get_all("TEX Audit Event", filters={"action": "payment_account.gated", "reference_name": acc},
		                        pluck="new_value")
		self.assertEqual([json.loads(e)["open_charge_names"] for e in events], [["G76-TXN-A", "G76-TXN-B"]])

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


	def test_p47_reports_sites_named_like_an_admin_page_once(self):
		"""G-64 review M3: a booking site named like one of the admin area's pages (an old link to it
		opened that page) is reported for the owner, never renamed (its name is its first slug)."""
		clash = put("TEX Booking Site", "rooms", site_slug="rooms", site_name="Rooms Hotel", property=fx.PROPERTY,
		            enabled=1)
		moved = put("TEX Booking Site", "Analytics", site_slug="analytics-beach", site_name="Moved",
		            property=fx.PROPERTY, enabled=0)                     # named so, its slug changed since
		slug_only = put("TEX Booking Site", "g47-slug", site_slug="content", site_name="Slug only",
		                property=fx.PROPERTY, enabled=1)                # opens at its name: no clash
		fine = put("TEX Booking Site", "g47-fine", site_slug="g47-fine", site_name="Fine", property=fx.PROPERTY,
		           enabled=1)
		self.first_run("p47_g64_site_slugs")
		self.assertRerunChangesNothing("p47_g64_site_slugs")
		for site, slug in ((clash, "rooms"), (moved, "analytics-beach")):
			self.assertEqual(frappe.db.count("TEX Audit Event", {"action": "booking_site.admin_slug",
			                                                      "reference_name": site}), 1, site)
			self.assertEqual(frappe.db.get_value("TEX Booking Site", site, "site_slug"), slug)   # never renamed
		for site in (slug_only, fine):
			self.assertFalse(frappe.db.exists("TEX Audit Event", {"action": "booking_site.admin_slug",
			                                                      "reference_name": site}), site)


	def test_p59_syncs_the_policies_and_reports_fixed_amounts_to_review(self):
		"""Y-3 A (ADR-067, D-1): the policies' currency is synced, never filled in (empty is the
		contract's currency). A fixed policy without one used by contracts in several currencies, and
		a live or future stay with a fixed deposit or fee sold in another currency than its contract's,
		are reported once each; nothing is changed."""
		def plan_row(contract: dict, **values):
			row = frappe.db.get_value("TEX Contract Rate Plan", {"parent": contract["version"],
			                                                     "rate_plan": self.f["rate_plans"]["FLEX"]})
			frappe.db.set_value("TEX Contract Rate Plan", row, values)

		eur = fx.create_contract(self.f, code="P59-EUR", publish=False)
		try_ = fx.create_contract(self.f, code="P59-TRY", publish=False)
		frappe.db.set_value("TEX Contract", try_["contract"], "contract_currency", "TRY")
		shared = put("TEX Payment Policy", policy_name="P59 100 now", property=fx.PROPERTY, deposit_type="FIXED",
		             deposit_value=D(100))
		fee = put("TEX Cancellation Policy", policy_name="P59 fee", property=fx.PROPERTY, refundable=1,
		          no_show_type="FIXED", no_show_value=D(80))
		named = put("TEX Payment Policy", policy_name="P59 in EUR", property=fx.PROPERTY, deposit_type="FIXED",
		            deposit_value=D(100), currency="EUR")
		one = put("TEX Payment Policy", policy_name="P59 one contract", property=fx.PROPERTY, deposit_type="FIXED",
		          deposit_value=D(50))
		plan_row(eur, payment_policy=shared, cancellation_policy=fee)
		plan_row(try_, payment_policy=shared, cancellation_policy=fee)
		for contract in (eur, try_):
			frappe.db.set_value("TEX Contract Rate Plan", frappe.db.get_value(
				"TEX Contract Rate Plan", {"parent": contract["version"], "rate_plan": self.f["rate_plans"]["NRF"]}),
				"payment_policy", named)
		plan_row(fx.create_contract(self.f, code="P59-ONE", publish=False), payment_policy=one)

		def stay(status, sold, days=(10, 13)):
			snap = {"currency": sold, "contract": {"currency": "EUR"},
			        "rate_plan": {"payment_policy": {"id": shared, "deposit_type": "FIXED", "deposit_value": "100"}}}
			return kamra_stay(fx.PROPERTY, status, 300, days=days, tex_pricing_snapshot=json.dumps(snap))

		in_try = stay("Confirmed", "TRY")
		quiet = (stay("Confirmed", "EUR"), stay("Cancelled", "TRY"), stay("Checked Out", "TRY", days=(-5, -2)))
		policies_before = {n: frappe.db.get_value(dt, n, "modified") for dt, n in (
			("TEX Payment Policy", shared), ("TEX Cancellation Policy", fee), ("TEX Payment Policy", one))}

		seen = self.first_run("p59_policy_currency")
		self.assertEqual(seen["reload_doc"], [("tex_commercial", "doctype", "tex_payment_policy"),
		                                      ("tex_commercial", "doctype", "tex_cancellation_policy")])
		self.assertIn("p59: 2 fixed polic(ies)", seen["print"].call_args.args[0])
		self.assertIn("; 1 live or future stay(s)", seen["print"].call_args.args[0])
		self.assertRerunChangesNothing("p59_policy_currency")
		reported = {e.reference_name: json.loads(e.new_value) for e in frappe.get_all(
			"TEX Audit Event", filters={"action": "policy.fixed_currency_ambiguous"},
			fields=["reference_name", "new_value"])}
		self.assertEqual(set(reported), {shared, fee})
		self.assertEqual(reported[shared], {"currencies": ["EUR", "TRY"],
		                                    "contracts": sorted([eur["contract"], try_["contract"]])})
		stays = frappe.get_all("TEX Audit Event", filters={"action": "reservation.fixed_policy_currency"},
		                       fields=["reference_name", "new_value"])
		self.assertEqual([s.reference_name for s in stays], [in_try])
		self.assertEqual(json.loads(stays[0].new_value)["sold_in"], "TRY")
		self.assertFalse(set(quiet) & {s.reference_name for s in stays})
		for doctype, name in (("TEX Payment Policy", shared), ("TEX Cancellation Policy", fee),
		                      ("TEX Payment Policy", one)):
			self.assertIsNone(frappe.db.get_value(doctype, name, "currency"))       # nothing filled in (D-1)
			self.assertEqual(frappe.db.get_value(doctype, name, "modified"), policies_before[name])

	def test_p60_stores_codes_by_their_key_and_reports_a_clash_once(self):
		"""O-31: every code promotion (whatever its status) whose code is not its key gets it, ``modified``
		kept; a changed one whose key another draft or live record of the hotel has is reported once.
		Redemptions keep the code they recorded; a second run changes nothing."""
		def promo(code: str, status: str = "Active", **kw) -> str:
			return put("TEX Promotion", promotion_name=f"P60 {code}", property=fx.PROPERTY, trigger="Code",
			           code=code, value_type="PERCENT", value=D(10), tex_status=status, revision_no=1, **kw)

		dotted = promo("WİNTER")                                   # WINTER: the draft below has it
		plain = promo("WINTER", status="Draft")
		archived = promo("YAZİ", status="Archived")                # YAZI, never live again: no clash
		dotless = promo("KIŞ", status="Draft")                     # KIŞ is its key already
		revision = promo("WİNTER", status="Draft", revision_of=dotted)   # the same record: no clash
		red = put("TEX Promotion Redemption", promotion=dotted, code="WİNTER", booking="P60-BOOKING")
		before = {n: frappe.db.get_value("TEX Promotion", n, "modified") for n in (dotted, archived, revision)}

		seen = self.first_run("p60_promotion_code_key")
		self.assertIn("p60: 3 promotion code(s) set to their key", seen["print"].call_args.args[0])
		self.assertIn("; 1 clash(es)", seen["print"].call_args.args[0])
		self.assertRerunChangesNothing("p60_promotion_code_key")
		codes = dict(frappe.get_all("TEX Promotion", filters={"name": ("in", [dotted, plain, archived, dotless,
		                                                                        revision])},
		                            fields=["name", "code"], as_list=True))
		self.assertEqual(codes, {dotted: "WINTER", plain: "WINTER", archived: "YAZI", dotless: "KIŞ",
		                         revision: "WINTER"})
		for name, modified in before.items():
			self.assertEqual(frappe.db.get_value("TEX Promotion", name, "modified"), modified)
		self.assertEqual(frappe.db.get_value("TEX Promotion Redemption", red, "code"), "WİNTER")
		events = frappe.get_all("TEX Audit Event", filters={"action": "promotion.code_clash"},
		                        fields=["reference_name", "new_value"])
		self.assertEqual([(e.reference_name, json.loads(e.new_value)) for e in events],
		                 [(dotted, {"code": "WINTER", "clashes_with": [plain]})])


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
				 ("Property", "tex_lower_price_refund")),
				("p49_payment_attempt_deadline", [("tex_payments", "doctype", "tex_payment_transaction"),
				                                  ("tex_booking", "doctype", "tex_booking")],
				 ("TEX Booking", "payment_attempt_until")),
				("p50_payment_reconciliation", [("tex_payments", "doctype", "tex_payment_transaction")],
				 ("TEX Payment Transaction", "reconciliation")),
				("p53_payment_captured_at", [("tex_payments", "doctype", "tex_payment_transaction")],
				 ("TEX Payment Transaction", "captured_at"))):
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

	def test_p51_gives_each_payment_method_its_hold(self):
		frappe.db.sql("""DELETE FROM `tabSingles` WHERE doctype='TEX Settings'
		                 AND field IN ('hold_minutes_link', 'hold_minutes_transfer')""")
		frappe.db.set_single_value("TEX Settings", "hold_minutes", 25)
		seen = self.first_run("p51_hold_minutes_per_payment_method")
		self.assertEqual(seen["reload_doc"], [("tex_platform", "doctype", "tex_settings"),
		                                      ("kamra", "doctype", "property")])
		self.assertEqual([frappe.db.get_single_value("TEX Settings", f) for f in
		                  ("hold_minutes", "hold_minutes_link", "hold_minutes_transfer")], [25, 1440, 2880])
		frappe.db.set_single_value("TEX Settings", "hold_minutes_link", 600)     # an administrator's value
		self.assertRerunChangesNothing("p51_hold_minutes_per_payment_method")
		self.assertEqual(frappe.db.get_single_value("TEX Settings", "hold_minutes_link"), 600)
		self.assertTrue(frappe.db.has_column("Property", "tex_hold_minutes_transfer"))

	def test_p55_gives_web_transfers_their_hold(self):
		frappe.db.sql("""DELETE FROM `tabSingles` WHERE doctype='TEX Settings' AND field='hold_minutes_transfer_web'""")
		seen = self.first_run("p55_web_transfer_hold")
		self.assertEqual(seen["reload_doc"], [("tex_platform", "doctype", "tex_settings"),
		                                      ("kamra", "doctype", "property")])
		self.assertEqual(frappe.db.get_single_value("TEX Settings", "hold_minutes_transfer_web"), 1440)
		frappe.db.set_single_value("TEX Settings", "hold_minutes_transfer_web", 720)   # an administrator's value
		self.assertRerunChangesNothing("p55_web_transfer_hold")
		self.assertEqual(frappe.db.get_single_value("TEX Settings", "hold_minutes_transfer_web"), 720)
		self.assertTrue(frappe.db.has_column("Property", "tex_hold_minutes_transfer_web"))

	def test_p56_gives_versions_the_roll_superseded_their_state(self):
		# NEW-1: the roll set every published version without an end Superseded and left active_to empty
		from kamra.tex.commercial import contracts

		def as_the_old_roll(version):
			frappe.db.set_value("TEX Contract Version", version, "status", "Superseded")

		def state(version):
			return tuple(frappe.db.get_value("TEX Contract Version", version, ["status", "active_to"]))

		def publish(contract, at=None):
			version = contracts.new_draft(contract)
			contracts.publish(version, effective_from=at)
			return version

		now = now_datetime()
		live = fx.create_contract(self.f, code="P56-LIVE")                  # live, no end, nothing after it
		as_the_old_roll(live["version"])
		fixed = fx.create_contract(self.f, code="P56-FIX")                  # V2 scheduled, then corrected by V3
		start = add_to_date(now, days=30)
		v2 = publish(fixed["contract"], start)
		as_the_old_roll(v2)
		v3 = publish(fixed["contract"], add_to_date(now, days=10))
		self.assertEqual(state(v2), ("Superseded", None))                 # the publish never saw it
		self.assertEqual(contracts.active_version_header(fixed["contract"], start).version_id, v2)
		replaced = fx.create_contract(self.f, code="P56-NEW")               # live, then a version from now on
		as_the_old_roll(replaced["version"])
		r2 = publish(replaced["contract"])
		right = fx.create_contract(self.f, code="P56-OK")                   # superseded the right way
		publish(right["contract"])
		kept = state(right["version"])
		self.assertEqual(kept[0], "Superseded")

		self.first_run("p56_open_ended_versions")                           # a second run changes nothing
		self.assertEqual(state(live["version"]), ("Published", None))
		self.assertEqual(frappe.db.get_value("TEX Contract", live["contract"], "active_version"), live["version"])
		self.assertEqual(state(v2), ("Withdrawn", get_datetime(frappe.db.get_value(
			"TEX Contract Version", v2, "effective_from"))))
		self.assertEqual(contracts.active_version_header(fixed["contract"], start).version_id, v3)
		self.assertEqual(state(replaced["version"]), ("Superseded", get_datetime(frappe.db.get_value(
			"TEX Contract Version", r2, "effective_from"))))
		self.assertEqual(state(right["version"]), kept)
		restored = frappe.get_all("TEX Audit Event", filters={"action": "contract.version_restored"},
		                          fields=["reference_name", "new_value"])
		self.assertEqual(sorted(e.reference_name for e in restored), sorted([live["version"], v2, replaced["version"]]))
		self.assertEqual(json.loads(next(e.new_value for e in restored if e.reference_name == v2))["status"],
		                 "Withdrawn")

	def test_p34_dates_released_coupon_uses(self):
		at = get_datetime("2026-03-01 10:00:00")
		released = put("TEX Promotion Redemption", promotion="G76-PROMO", status="Released", modified=at)
		held = put("TEX Promotion Redemption", promotion="G76-PROMO", status="Committed", released_at=at)
		self.first_run("p34_redemption_released_at")
		self.assertEqual(get_datetime(frappe.db.get_value("TEX Promotion Redemption", released, "released_at")), at)
		self.assertIsNone(frappe.db.get_value("TEX Promotion Redemption", held, "released_at"))


class TestP48Evidence(PatchCase):
	"""Y-12 (audit Part 2A): p48 took every ``anonymize_guest`` row of the Agent Action Log as proof that
	a profile had been erased, whatever its status, whoever wrote it, whatever the profile looks like;
	a Hotel Admin could add such a row by REST for another tenant's guest, and p48 then erased that
	guest for good. Proof is now a ``guest.erase`` event, or a row of an erasure that ran on a profile
	that shows what the erasure left; and business roles only read the log."""

	P48 = "p48_crm_privacy_third_review"

	def guest(self, first: str) -> str:
		return frappe.get_doc({"doctype": "Guest", "first_name": first, "last_name": "Kraus", "phone": "+49 30 1234",
		                       "email": f"y12-{first.lower()}@example.com", "tex_consent_email": 1,
		                       "date_of_birth": "1980-01-02"}).insert(ignore_permissions=True).name

	def erased_by_the_old_endpoint(self, first: str) -> str:
		"""What ``kamra.api.anonymize_guest`` left before the marker existed: its alias, no last name,
		e-mail or phone, its note; the date of birth and consent it did not clear then are left."""
		from kamra.patches.tex.p48_crm_privacy_third_review import ERASED_NOTE

		g = self.guest(first)
		alias = f"Guest {frappe.generate_hash(length=6).upper()}"
		frappe.db.set_value("Guest", g, {"first_name": alias, "full_name": alias, "last_name": "", "email": "",
		                                 "phone": "", "guest_notes": ERASED_NOTE})
		return g

	def log(self, guest: str, status: str, **values) -> str:
		return put("Agent Action Log", action_type="anonymize_guest", reference_doctype="Guest", reference_name=guest,
		           approval_status=status, **{"actor": "Administrator", **values})

	def state(self, guest: str) -> dict:
		return frappe.db.get_value("Guest", guest, ["tex_erased_at", "first_name", "last_name", "email", "phone",
		                                            "tex_consent_email", "date_of_birth", "guest_notes"], as_dict=True)

	def test_a_log_row_proves_an_erasure_only_with_what_the_erasure_left(self):
		from kamra.patches.tex import p48_crm_privacy_third_review as p48
		from kamra.tex.tests.integration.test_crm_segments import OTHER, other_tenant

		_found, before = p48._erasures()
		kept = {}
		for status in ("Rejected", "Suggested", "Pending", "Executed"):       # no traces on the profile
			g = self.guest(f"Kept{status}")
			self.log(g, status, executed_at=now_datetime() if status in ("Executed", "Rejected") else None)
			kept[g] = self.state(g)
		# a Hotel Admin of another tenant added an Executed row for this tenant's guest (REST, before Y-12)
		other_tenant()
		intruder = fx.ensure_user("y12-intruder@example.com", ["Hotel Admin"])
		victim = self.guest("Victim")
		self.log(victim, "Executed", actor=intruder, owner=intruder, property=OTHER, executed_at=now_datetime())
		kept[victim] = self.state(victim)
		# real legacy erasures: an executed one, and one approved (the gate runs it right after)
		real = self.erased_by_the_old_endpoint("Real")
		self.log(real, "Executed", executed_at=now_datetime())
		approved = self.erased_by_the_old_endpoint("Approved")
		self.log(approved, "Approved", approver="Administrator", executed_at=now_datetime())

		never_ran(self.P48)
		seen = migrate(self.P48)
		for g, was in kept.items():
			self.assertEqual(self.state(g), was, g)
			self.assertFalse(frappe.db.exists("TEX Audit Event", {"action": "guest.erase", "reference_name": g}), g)
		for g in (real, approved):
			now = self.state(g)
			self.assertTrue(now.tex_erased_at, g)                              # marked
			self.assertEqual((now.tex_consent_email, now.date_of_birth), (0, None), g)   # and finished
			self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "guest.erase", "reference_name": g}), g)
		printed = " ".join(str(c) for c in seen["print"].call_args_list)
		self.assertIn(f"{before + 5} Agent Action Log erasure row(s) not taken as proof", printed)
		self.assertEqual(rerun_changes(self.P48), {})

	def test_business_roles_only_read_the_log_and_logging_goes_on(self):
		from kamra.savings import log_action

		guest = self.guest("Logged")
		for role in ("Hotel Admin", "Kamra Agent"):
			user = fx.ensure_user(f"y12-{role.lower().replace(' ', '-')}@example.com", [role])
			frappe.set_user(user)  # nosemgrep: frappe-setuser -- the test acts as each role
			try:
				with self.assertRaises(frappe.PermissionError, msg=role):
					frappe.client.insert({"doctype": "Agent Action Log", "action_type": "anonymize_guest",
					                      "reference_doctype": "Guest", "reference_name": guest,
					                      "approval_status": "Executed"})
				name = log_action("guest_note", "Guest", guest, rationale="Y-12")   # the normal path writes
				self.assertTrue(name and frappe.db.exists("Agent Action Log", name), role)
				with self.assertRaises(frappe.PermissionError, msg=role):
					frappe.client.set_value("Agent Action Log", name, "approval_status", "Approved")
				with self.assertRaises(frappe.PermissionError, msg=role):
					frappe.client.delete("Agent Action Log", name)
				self.assertTrue(frappe.has_permission("Agent Action Log", "read"), role)
			finally:
				frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back


class TestP64AgentLogReadOnly(PatchCase):
	"""Y-12 (audit Part 2A, review round 1): once a DocType has one Custom DocPerm row Frappe ignores its
	JSON permissions, and the seed scripts wrote such rows for the Agent Action Log (Hotel Admin rwcd from
	``seed_rbac_v2.ensure_hotel_admin``, Kamra Agent from ``ensure_agent_user``, Front Desk from
	``seed_users``). p64 makes those rows read-only for every role but System Manager."""

	P64 = "p64_agent_log_read_only"
	DT = "Agent Action Log"
	ROLES = ("Hotel Admin", "Kamra Agent", "Front Desk")

	def tearDown(self):
		super().tearDown()                       # the rollback takes the rows this test wrote
		frappe.clear_cache(doctype=self.DT)

	def custom_rows(self) -> list[dict]:
		return frappe.get_all("Custom DocPerm", filters={"parent": self.DT}, order_by="role asc, permlevel asc",
		                      fields=["role", "permlevel", "read", "write", "create", "delete", "share", "report",
		                              "export", "print", "email"])

	def seeded(self) -> None:
		"""The rows the old seeds left: Hotel Admin rwcd, Kamra Agent r/w/c, Front Desk r/c, System Manager all."""
		from kamra.scripts.fix_perms_fields import _grant

		for role, (r, w, c, d) in (("System Manager", (1, 1, 1, 1)), ("Hotel Admin", (1, 1, 1, 1)),
		                           ("Kamra Agent", (1, 1, 1, 0)), ("Front Desk", (1, 0, 1, 0))):
			_grant(self.DT, role, r, w, c, delete=d)
		frappe.clear_cache(doctype=self.DT)

	def user(self, role: str) -> str:
		user = fx.ensure_user(f"p64-{role.lower().replace(' ', '-')}@example.com", [role])
		fx.ensure("TEX Access Grant", {"user": user, "property": fx.PROPERTY},
		          {"user": user, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Hotel Admin" if role == "Hotel Admin" else "Reservations Agent"})
		return user

	def as_role(self, role: str):
		frappe.set_user(self.user(role))  # nosemgrep: frappe-setuser -- the test acts as each role
		scope.clear_cache()

	def back(self) -> None:
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		scope.clear_cache()

	def insert(self) -> str:
		return frappe.client.insert({"doctype": self.DT, "action_type": "p64_probe", "property": fx.PROPERTY,
		                             "approval_status": "Executed"})["name"]

	def test_p64_makes_the_seeded_rows_read_only(self):
		from kamra.savings import log_action

		self.seeded()
		self.as_role("Hotel Admin")
		try:
			row = self.insert()                                            # the seeded rows let it write
			self.assertTrue(frappe.db.exists(self.DT, row))
		finally:
			self.back()
		system_manager = [r for r in self.custom_rows() if r.role == "System Manager"]
		never_ran(self.P64)
		seen = migrate(self.P64)
		self.assertIn("3 Custom DocPerm row(s)", " ".join(str(c) for c in seen["print"].call_args_list))
		self.assertEqual([r for r in self.custom_rows() if r.role == "System Manager"], system_manager)
		for r in self.custom_rows():
			if r.role != "System Manager":
				self.assertEqual((r.read, r.write, r.create, r.delete, r.share), (1, 0, 0, 0, 0), r.role)
				self.assertEqual((r.report, r.export, r.print, r.email), (1, 1, 1, 1), r.role)
		for role in self.ROLES:
			self.as_role(role)
			try:
				with self.assertRaises(frappe.PermissionError, msg=role):
					self.insert()
				with self.assertRaises(frappe.PermissionError, msg=role):
					frappe.client.set_value(self.DT, row, "approval_status", "Approved")
				with self.assertRaises(frappe.PermissionError, msg=role):
					frappe.client.delete(self.DT, row)
				self.assertTrue(frappe.has_permission(self.DT, "read"), role)
				logged = log_action("p64_normal", "Property", fx.PROPERTY, property=fx.PROPERTY)
				self.assertTrue(logged and frappe.db.exists(self.DT, logged), role)
			finally:
				self.back()
		rows = self.custom_rows()
		again = migrate(self.P64)                                          # a second run changes nothing
		self.assertEqual(self.custom_rows(), rows)
		self.assertIn("0 Custom DocPerm row(s)", " ".join(str(c) for c in again["print"].call_args_list))

	def test_p64_never_adds_a_row_to_a_log_without_custom_rows(self):
		self.assertEqual(self.custom_rows(), [])
		never_ran(self.P64)
		migrate(self.P64)
		self.assertEqual(self.custom_rows(), [])

	def test_the_seed_gives_hotel_admin_the_log_read_only(self):
		from kamra.scripts import seed_rbac_v2

		fx.ensure_user("admin@kamra.local", ["System Manager"])           # the seed's demo admin (rolled back)
		with mock.patch.object(seed_rbac_v2, "_grant") as grant:
			seed_rbac_v2.ensure_hotel_admin()
		calls = {c.args[0]: (c.args[1:], c.kwargs) for c in grant.call_args_list}
		self.assertEqual(calls[self.DT], (("Hotel Admin", 1, 0, 0), {}))
		for doctype, (args, kwargs) in calls.items():
			if doctype != self.DT:
				self.assertEqual((args, kwargs), (("Hotel Admin", 1, 1, 1), {"delete": 1}), doctype)


class TestCommitGuard(PatchCase):
	"""C1 (review of G-76): nothing a migration test holds can be committed until it rolled back."""

	def test_commits_are_refused_until_the_test_rolled_back(self):
		for attempt in (frappe.db.commit, lambda: frappe.db.sql("COMMIT"),
		                lambda: frappe.db.sql_ddl("ALTER TABLE `tabToDo` COMMENT ''")):
			with self.assertRaises(CommitRefused):
				attempt()
		put("ToDo", description="C1 check", status="Open")               # a write: DDL would commit it
		with self.assertRaises(frappe.exceptions.ImplicitCommitError):
			frappe.db.sql("ALTER TABLE `tabToDo` COMMENT ''")             # refused before it runs (Frappe)


if os.environ.get("TEX_C1_MARKER"):
	class TestInterruptedRun(PatchCase):
		"""C1: a run interrupted with Ctrl-C commits nothing. unittest skips tearDown and the
		cleanups on KeyboardInterrupt, and Frappe's ``run-tests`` then commits the connection
		(``_cleanup_after_tests``). Only the SIGINT simulation defines it
		(``/home/user/bench/scratch/c1_sigint.sh`` sets ``TEX_C1_MARKER``): it writes one harmless
		marker row and waits for the interrupt."""

		def test_an_interrupted_run_commits_nothing(self):
			import sys
			import time

			marker = os.environ["TEX_C1_MARKER"]
			put("ToDo", marker, description=f"C1 marker {marker}", status="Open")
			sys.__stdout__.write(f"C1-MARKER-READY {marker}\n")
			sys.__stdout__.flush()
			time.sleep(120)
