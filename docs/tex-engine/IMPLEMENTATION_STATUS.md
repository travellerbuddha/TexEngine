# TEX Engine — Implementation Status (authoritative)

This file holds **one current state only**. It was rewritten on 2026-09-23 from a fresh
audit of the code, the tests and the running UI. It does not carry over claims from earlier
milestones. Every gap named here is itemised with severity, files and implementation order in
[`FINAL_GAP_AUDIT.md`](FINAL_GAP_AUDIT.md) (gap ids `G-xx`).

**Classification rule (R-61).** A requirement is **COMPLETE** only when all of these exist
for every bullet of `PRODUCT_SPEC.md`:
- the real backend;
- validation and security;
- the UI, where the requirement implies one;
- automated tests.

Otherwise it is **PARTIAL** (the missing parts are named), **NOT STARTED**, or **BLOCKED**
(it needs something only the owner can provide). Placeholder UI or API stubs never count.

## 1. Verified test and build state (CI #191 on 000d806, PR #28, 2026-10-03)

| Check | Command | Result |
|---|---|---|
| TEX pure unit tests | `python -m unittest discover -s kamra/tex/tests/unit -t .` (bench Python) | **694 passed** (CI #191) |
| TEX integration tests (49 modules) | `bench --site test.localhost run-tests --module kamra.tex.tests.integration.<m>` | **49 modules, 1,301 tests OK** (CI #191, a disposable site: the whole-site patch tests run too). History: 969 tests in 42 modules (2026-09-26), 1,193 in 44 on aac444a4 (CI #160, 2026-10-01); git keeps the per-branch runs |
| Browser E2E (Playwright) | `cd frontend && npx playwright test -c e2e` | **202 passed, 9 skipped** (211; CI #191; 51 spec files in `frontend/e2e/`, 52 with 2Z's `payments-setup`, against the bench with an RQ worker, site scheduler off). History: 163 passed (2026-09-26), 177 on aac444a4 (CI #160); git keeps the per-branch runs |
| Upstream Kamra suites | `run_baseline.sh` | eval harness **76/76**, front-desk journey **13/13**, banquet **101 OK** (CI #191) |
| TypeScript / build / i18n parity | `npx tsc -b`, `npm run build`, `npm run test:unit`, `npm run test:dom`, `npm run i18n:tex` | clean; node unit **435**, design-system DOM checks **42**, i18n complete in 6 languages, the booking catalogs included since G-70b (CI #191) |
| Lint / static security | `ruff check kamra/tex kamra/patches/tex` (ruff 0.15.8, `ci.yml`); Semgrep (frappe/semgrep-rules + python.lang.correctness, ERROR) | clean / 0 findings (Linters #190 with Semgrep 1.179.0, CI #191's head) |
| Supply chain | `supply-chain.yml` (NEW-5) | gitleaks clean, audit-ci clean, pip-audit no new finding (61 reviewed advisories in `.github/supply-chain/pip-audit-ignore.txt`) (Supply chain #71, CI #191's head) |

**Coverage gaps.** Green tests do not prove absence of the defects below. The audit reproduced
several critical defects with probes and scratch tests that the suite does not contain yet
(see FINAL_GAP_AUDIT §1).

**CI.** `.github/workflows/ci.yml` runs all of the above including Playwright on every pull request to the
base branch `claude/inspiring-ptolemy-i6wdu2`; PRs #1–#28 merged with it green (last: PR #28, merge 6d888b6, 2026-10-03).
**CI baseline (2026-09-26, PARTİ 1.5, ADR-063, PR #2).** GitHub CI runs on MariaDB 11.8 with `innodb_snapshot_isolation` OFF (set and checked; TEX also turns it off per request and job, and the status page fails while it is ON); every integration module runs and the red ones are listed at the end; Semgrep ERROR 6 → 0; the marketplace simulation passes. Local 11.8.9: `test_concurrency` 10/10 with it OFF (ON: 5 of 8 red, error 1020), 40/40 integration modules, 531 unit tests.

History (2026-09-24): after a pause at the owner's request the work resumed on `3a5cc03`; the gap counts of that day are superseded by §2.

**2026-09-23.** The work paused at the owner's request is merged: G-30/G-31 occupancy precedence v2 (ADR-043) and G-45 self-service money flows (ADR-044). G-50 contract header lock (ADR-045) and G-83 security hygiene (ADR-046) are merged too, and TEX operations monitoring (ADR-047). Root `SECURITY.md` is rewritten for TEX (the security contact is still an owner input).

**G-74 audit gaps (2026-09-24, branch `audit-g74`, main `178d53c` merged in).** Closed in code
(ADR-053, patch p33, new DocType `TEX Audit Scope`). On the branch: all 26 integration modules
**495 OK** (admin_markets 4, age_bands 11, audit_trail 15, channel_binding 26, commercial_flows 43,
concurrency 8, critical_journey 31, crm_segments 7, custom_domains 9, distribution 21,
extras_inventory 17, fx_snapshot 5, grant_expiry 9, inventory 31, legacy_pricing 15, loyalty_admin 7,
migrations_notify 7, modification_determinism 24, portfolio 2, post_booking_extras 12,
pricing_policies 14, public_booking 17, security_hygiene 14, security_regressions 59,
self_service_money 75, system_status 12; the 15 `test_audit_trail` tests fail on `db47abb`),
343 unit tests, ruff clean, semgrep ERROR rules add no finding in the changed files, `npx tsc -b` and
`npm run i18n:tex` clean (bundles not rebuilt on the branch).

**G-45 fourth review (2026-09-24, branch `fix4-g45`).** The fourth review's High (G-93 path), three
Medium and three Low findings are fixed (ADR-044 fourth review section; patch p28; four indexes). On
the branch: all 20 integration modules **406 OK** (admin_markets 4, channel_binding 16,
commercial_flows 43, concurrency 8, critical_journey 31, crm_segments 7, custom_domains 9,
distribution 21, extras_inventory 17, inventory 31, loyalty_admin 7, migrations_notify 7,
portfolio 2, post_booking_extras 12, pricing_policies 14, public_booking 17, security_hygiene 14,
security_regressions 59, self_service_money 75, system_status 12; the 10 new tests fail on
`b8e8ccd`), 293 unit tests, ruff and semgrep clean, `npx tsc -b`, `npm run build` and
`npm run i18n:tex` clean.

**G-45 third review (2026-09-24, branch `fix3-g45`, with main at G-41 merged).** The third
review's High, Medium and three Low findings and G-93 are fixed (ADR-044 third review section).
On the branch: all 20 integration modules **396 OK** (admin_markets 4, channel_binding 16,
commercial_flows 43, concurrency 8, critical_journey 31, crm_segments 7, custom_domains 9,
distribution 21, extras_inventory 17, inventory 31, loyalty_admin 7, migrations_notify 7,
portfolio 2, post_booking_extras 12, pricing_policies 14, public_booking 17, security_hygiene 14,
security_regressions 59, self_service_money 65, system_status 12; the 12 new tests fail on
`09a2389`), 293 unit tests, ruff and semgrep clean, `npx tsc -b`, `npm run build` and
`npm run i18n:tex` clean; `manage-money.spec.ts` extended and type-checked, not re-run.

**G-45 second review (2026-09-24, branch `fix2-g45`).** The eight findings of the second
review (F1–F8) are fixed (ADR-044 second review section). On the branch: all 18 integration
modules **333 OK** (the table above plus 13 new `test_self_service_money` tests, 54 in all, and
one new `test_distribution` test, 20 in all; the 14 new tests fail on `0dc0920`), 282 unit tests,
ruff and semgrep clean, `npx tsc -b`, `npm run build` and `npm run i18n:tex` clean;
`manage-money.spec.ts` extended and type-checked, not re-run.

**Operations (2026-09-23, ADR-047).** System status, guest ping, alerts and the e-mail delivery
status were added on branch `ops-monitoring`: `test_system_status` 12 OK (11 failed first on the
base commit, one more for the hotel sender), unit `test_system_checks` 17 OK (214 unit tests in
total with `python -m unittest discover`), migration p23 run on the dev bench, `npm run build`
and `npm run i18n:tex` clean. All 15 integration modules re-run on the branch: **227 OK**
(admin_markets 4, commercial_flows 41, concurrency 7, critical_journey 10, crm_segments 7,
custom_domains 9, distribution 17, extras_inventory 17, loyalty_admin 7, migrations_notify 7,
portfolio 2, post_booking_extras 12, public_booking 17, security_regressions 58,
system_status 12). `system-status.spec.ts` (4) passes.

**G-56 / G-52 (2026-09-24, ADR-051, branch `pricing-g56-g52`, merged with main 9ef07e4, review follow-up included).** New tests: unit `test_fx_record` 14 and `test_age_bands` 20 (327 unit tests in total), integration `test_fx_snapshot` 5 and `test_age_bands` 11 (fail-first on the base commit: 8/11, 8/17, 4/4, 4/6; the review's tests on the unreviewed branch: 6/6 unit, 5/5 + 1/1 integration). All 22 integration modules OK (400 tests): admin_markets 4, age_bands 11, channel_binding 16, commercial_flows 43, concurrency 8, critical_journey 31, crm_segments 7, custom_domains 9, distribution 20, extras_inventory 17, fx_snapshot 5, inventory 31, loyalty_admin 7, migrations_notify 7, portfolio 2, post_booking_extras 12, pricing_policies 14, public_booking 17, security_hygiene 14, security_regressions 59, self_service_money 54, system_status 12; `npx tsc -b`, `npm run i18n:tex`, ruff clean.

**G-92 (2026-09-24, ADR-052, branch `legacy-price-g92` on main `98d0967`).** A TEX hotel's reservation is created only by TEX or a migration import (recorded as "Imported" at its Decimal amount), the legacy auto-price never prices a TEX hotel, and a stay there changes commercially only through TEX. New integration module `test_legacy_pricing` 15 (10 fail first on `98d0967`, the other 5 guard unchanged behaviour); the G-49 tests' outside-TEX writer is now an import. All 24 integration modules OK (446 tests): admin_markets 4, age_bands 11, channel_binding 26, commercial_flows 43, concurrency 8, critical_journey 31, crm_segments 7, custom_domains 9, distribution 21, extras_inventory 17, fx_snapshot 5, grant_expiry 9, inventory 31, legacy_pricing 15, loyalty_admin 7, migrations_notify 7, portfolio 2, post_booking_extras 12, pricing_policies 14, public_booking 17, security_hygiene 14, security_regressions 59, self_service_money 65, system_status 12. 328 unit tests; upstream suites with the branch: eval harness 76/76, front-desk journey 13/13, banquet 101 OK. ruff clean (`kamra/tex`, `kamra/patches/tex`; the touched legacy files have no new warning); semgrep ERROR rules on the changed files: 0 findings. No schema patch: the new "Imported" pricing source is synced from the DocType JSON (migrated on the dev bench). No frontend change.

**G-51 (2026-09-24, ADR-054, branch `determinism-g51` on main `db47abb`).** New tests: integration `test_modification_determinism` 24 (fail-first commit `fbaa151`: 21 fail on the base commit, the 3 that pass cover behaviour already right) and unit `TestStatusAt` 4 (error on the base commit); 332 unit tests in total. `test_pricing_policies` now simulates a past sale time only (a future one is refused). Patch p34 (`TEX Promotion Redemption.released_at`) migrated on the dev bench. All 24 integration modules OK (**465** tests): modification_determinism 24, admin_markets 4, age_bands 11, channel_binding 26, commercial_flows 43, concurrency 8, critical_journey 31, crm_segments 7, custom_domains 9, distribution 21, extras_inventory 17, fx_snapshot 5, grant_expiry 9, inventory 31, loyalty_admin 7, migrations_notify 7, portfolio 2, post_booking_extras 12, pricing_policies 14, public_booking 17, security_hygiene 14, security_regressions 59, self_service_money 75, system_status 12; `npx tsc -b`, `npm run i18n:tex` and ruff clean; semgrep (Frappe rules + python correctness, ERROR) on the changed files: no new finding (one pre-existing in `contracts.build_terms`, an exception passed to `.format()`). Browser tests not re-run (the simulator dialog change is type-checked).

**G-51 review follow-up (2026-09-24, ADR-054 review section, branch `fix-g51` on main `178d53c`).** The Medium (a staff approval of a guest's waiting change sold on a contract suspended or archived since) and three Low findings are fixed. New tests: 3 in `test_modification_determinism` (27 in all) and one extended, and 1 in `test_channel_binding` (27 in all). Fail-first commit `0326a55`: the new `test_modification_determinism` tests fail on 178d53c (KeyError 'contract' / 'priced', a TypeError on an offset time, ContractNotOnSale not raised); the channel test covers a check that was already there. No schema change; 332 unit tests, `npx tsc -b`, `npm run i18n:tex` and ruff clean. Integration on the branch: 25 modules, 484 tests; 23 modules OK, and `test_inventory` (3) and `test_pricing_policies` (1) failed only because a contract another branch's test run left committed in the shared test hotel (`G72P`, Active, DE) sold their stays (every failing assertion names it).

**G-92 review follow-up and G-96 (2026-09-24, ADR-052 review section, branch `fix-g92` on main `45993df`, with main `178d53c` merged).** Import amounts are read strictly (never guessed), previewed per row with their currency, imported row by row all or nothing, and corrected with `price.override`. The legacy folio bills a price-locked stay from its TEX booking (nothing on the folio) or its locked amount (G-96), never the legacy Room Type rate; so do cancellation fees. A hotel joining TEX is onboarding until an administrator sets it live (p36 keeps today's TEX hotels live). New tests: integration `test_legacy_pricing_review` 23 (22 fail first on `45993df`: 16 errors on the new API, 6 failures), unit `test_import_amounts` 14. All 26 integration modules OK (508 tests): admin_markets 4, age_bands 11, channel_binding 26, commercial_flows 43, concurrency 8, critical_journey 31, crm_segments 7, custom_domains 9, distribution 21, extras_inventory 17, fx_snapshot 5, grant_expiry 9, inventory 31, legacy_pricing 15, legacy_pricing_review 23, loyalty_admin 7, migrations_notify 7, modification_determinism 24, portfolio 2, post_booking_extras 12, pricing_policies 14, public_booking 17, security_hygiene 14, security_regressions 59, self_service_money 75, system_status 12. `legacy_pricing_review` passed when migrate and test ran under one hold of the bench lock. In the plain full run its 3 go-live tests failed, because a parallel worktree's migrate had re-synced `Property` without `tex_live_from` in between. 346 unit tests. Upstream suites with the branch: eval harness 76/76, front-desk journey 13/13, banquet 101 OK. ruff clean (touched legacy files keep their warning counts); semgrep ERROR rules on the changed Python files: one finding, in `kamra/tex/commercial/contracts.py` (from main's G-51 merge, not this branch). `npx tsc -b`, `npm run build` (bundles not committed) and `npm run i18n:tex` clean.

**G-72 (2026-09-24, ADR-055, branch `float-g72` on main `178d53c`).** The commercial decimal fields keep 9 places (they were DECIMAL(21,6)), hold exactly what was typed or refuse it, are read as the exact Decimal (`money.db_dec`) and returned as strings; FX rates keep 10 significant digits. New tests: unit `test_money_fields` 11 (all fail or error on the base commit; 343 unit tests in total, `test_markup_fx_tax` cross rate now 1.294117647) and integration `test_money_fields` 9 (the first 8 fail or error on the base commit and schema). Patch p35 migrated on the dev bench: 20 decimal fields at 9 places, 193 published payloads verified, none failed. All 26 integration modules OK (**488** tests): money_fields 8, fx_snapshot 5, pricing_policies 14, age_bands 11, loyalty_admin 7, commercial_flows 43, critical_journey 31, modification_determinism 24, admin_markets 4, channel_binding 26, concurrency 8, crm_segments 7, custom_domains 9, distribution 21, extras_inventory 17, grant_expiry 9, inventory 31, legacy_pricing 15, migrations_notify 7, portfolio 2, post_booking_extras 12, public_booking 17, security_hygiene 14, security_regressions 59, self_service_money 75, system_status 12. After the last code commit (`a426ef2`) money_fields 9, fx_snapshot 5, commercial_flows 43 and loyalty_admin 7 were re-run OK. On that re-run, pricing_policies (1 of 14) and age_bands (1 of 11) failed on any tree: an earlier run of the G-72 test had left its contract `CTR-00624` (G72P) on the shared site, and those two tests then selected it. The test is fixed (`f182577`); removing that record is an owner action. Upstream suites with the branch: eval harness 76/76, front-desk journey 13/13, banquet 101 OK. `npx tsc -b`, `npm run i18n:tex` and ruff clean; semgrep ERROR rules on the changed files: no new finding (the pre-existing one in `contracts.build_terms`). Browser tests not run: the dev server serves main, not this branch.

**G-65, G-81, G-95 (2026-09-24, branch `crm-privacy` on main `b2011bc`, ADR-056, patch p37).**
CRM tenancy and completeness: a guest's loyalty shows only the programs of the viewer's hotels
(another hotel's bookings in a shared program as points only), the stored totals over every
tenant are never served by the TEX API nor readable in Desk / REST, the guest list counts and pages
in SQL, the profile shows extras bought and cancellations with fees. Funnel: an e-mail hash only
with marketing consent, no contact field in a payload, contact of an abandoned case only while the
profile's consent holds, recovery by a later payment. Pricing internals (snapshot, cost, margin,
FX, quote result, revision snapshots) at permlevel 1 for System Manager only, masked in the change
history, left out of a generic write's response. On the branch with its schema: all 29 integration
modules **549 OK** (admin_markets 4, age_bands 11, audit_trail 15, channel_binding 27,
commercial_flows 43, concurrency 8, critical_journey 31, crm_privacy 18, crm_segments 7,
custom_domains 9, distribution 21, extras_inventory 17, fx_snapshot 5, grant_expiry 9, inventory 31,
legacy_pricing 15, legacy_pricing_review 23, loyalty_admin 7, migrations_notify 7,
modification_determinism 27, money_fields 9, portfolio 2, post_booking_extras 12,
pricing_policies 14, public_booking 17, security_hygiene 14, security_regressions 59,
self_service_money 75, system_status 12; 15 of the 18 `test_crm_privacy` tests fail on `b2011bc`
and its schema), the upstream suites with the branch's code and schema (eval harness 76/76,
front-desk journey 13/13, banquet 101 OK), 368 unit tests, ruff clean, `npx tsc -b` and `npm run i18n:tex` clean, e2e
`crm-profile.spec.ts` type-checked (not run here; bundles not rebuilt on the branch). G-97
(contract cost readable in Desk by the Hotel Admin role whatever the profile, Low) found.

**G-73 and G-76 (2026-09-24, branch `migrations-snapshot` on main `b2011bc`, main `f3fcd33` merged in, ADR-058, patch p39).**
- *G-73.* A sold stay's snapshot keeps its periods and rules as a reference to its version's
  payload (version and hash). Every reprice, the simulator and extras added after booking refuse,
  audited, a payload that is not the one the sale recorded. The snapshot records when it was
  priced (`priced_at`) next to when it was accepted.
- *G-76.* Every TEX patch is tested: its behaviour, a second run, published payloads and sold
  prices untouched, and an empty site. The upgrade of a Kamra database runs the whole chain. The
  tests found and fixed defects in p01, p02, p04, p08, p09, p12, p17, p18, p19, p23, p24, p29 and
  p36, and three lookup indexes that Frappe's schema sync drops (composite now, created by p39).
- *Fail-first.* `test_snapshot_integrity`: 3 fail and 4 error on `b2011bc`; a stay sold at 400.00
  repriced at 800.00 after its payload was changed. `test_patches`: 8 fail and 1 errors on the
  original patches.
- *Runs.* Migrate with p39 (p37 merged); p39 forced again created only the missing index; a
  forced sync of the three DocTypes kept the composite indexes and dropped the single-column one.
  Then all 31 integration modules **579 OK**: admin_markets 4, age_bands 11, audit_trail 15,
  channel_binding 27, commercial_flows 43, concurrency 8, critical_journey 31, crm_privacy 18,
  crm_segments 7, custom_domains 9, distribution 21, extras_inventory 17, fx_snapshot 5,
  grant_expiry 9, inventory 31, legacy_pricing 15, legacy_pricing_review 23, loyalty_admin 7,
  migrations_notify 7, modification_determinism 27, money_fields 9, patches 21, portfolio 2,
  post_booking_extras 12, pricing_policies 14, public_booking 17, security_hygiene 14,
  security_regressions 59, self_service_money 75, snapshot_integrity 9, system_status 12.
  The upstream suites with the branch's code: eval harness 76/76, front-desk journey 13/13,
  banquet 101 OK. Also 368 unit tests and ruff (clean); semgrep is not installed in this session.

**G-48 and G-84 (2026-09-24, branch `restrictions-basket` on main `b2011bc`, main `665b6b9` merged in, ADR-057, patch p38).**
Restrictions: a change of a booked stay (staff, the guest's manage page, a guest change paid or
approved later) is refused by the restrictions of its scope, checked like a new booking for what it
newly takes (new nights, a new arrival or departure, the new length, or the whole stay of another
product, never the past of a stay under way); staff with `restriction.edit` override with a reason,
audited. The booking window (sale dates per night), hotel- and market-level cells and the Booking
Engine / Call Center / both scopes exist, in the grid too; a channel's booking breaking a
restriction is accepted with a warning; the channels' ARI hears the booking window and the advance
days (queued at the site's midnight). Minimum basket: the booking engine and the CRS quote the rooms
of a booking together, the minimum is the whole booking's at search, quote, booking and in changes,
(corrected below: a change below the minimum left the untouched rooms' discount unpaid). A code review of the branch
found 6 correctness items and 9 smaller ones; all fixed but two kept by decision (ADR-057 review
note). On the branch with its schema: all 32 integration modules **614 OK** (admin_markets 4,
age_bands 11, audit_trail 15, channel_binding 27, commercial_flows 53, concurrency 8,
critical_journey 31, crm_privacy 18, crm_segments 7, custom_domains 9, distribution 21,
extras_inventory 17, fx_snapshot 5, grant_expiry 9, inventory 31, legacy_pricing 15,
legacy_pricing_review 23, loyalty_admin 7, migrations_notify 7, modification_determinism 27,
money_fields 9, patches 21, portfolio 2, post_booking_extras 12, pricing_policies 14,
public_booking 17, restrictions 25, security_hygiene 14, security_regressions 59,
self_service_money 75, snapshot_integrity 9, system_status 12; 18 of the first 22
`test_restrictions` tests and the 9 first `TestBookingBasket` tests fail on `b2011bc`, the review's
tests on the code before it), the upstream suites with the branch's code and schema (eval harness
76/76, front-desk journey 13/13, banquet 101 OK), 400 unit tests (32 new), ruff clean, `npx tsc -b`, `npm run build` and
`npm run i18n:tex` clean, e2e `restrictions-grid.spec.ts` type-checked (not run here; bundles not
rebuilt on the branch).

**ADR-056 review follow-up (2026-09-25, branch `fix-crmp` on main `665b6b9`, patch p40).** The
independent review of the CRM privacy work found no Critical issue and no money bug; its 2 Medium and
5 Low findings are fixed: the program ledger shows another hotel's entries as points only and never
names a guest the viewer may not see; a withdrawal of e-mail consent makes the guest's cases and
funnel hashes anonymous on every path, case contacts and funnel identity are withheld from Desk /
REST, and p40 cleans older rows; browser funnel events keep an allow-list of fields; consent flags
sent as text are read strictly; customised role permissions keep System Manager's permlevel-1 row
(p40, the permission scripts) and a business role at permlevel 1 is reported; a masked change
history keeps its values for platform administrators (and the TEX audit log keeps them out of a
record's trail for everyone else); only a generic write's response is trimmed, never a `db_set`.
Found by the E2E run on main: a booking joins a profile by its e-mail, the phone only for a booking
without one or a profile without one (a shared phone had merged two people).
G-97 stays open (not small, ADR-056 review). On the branch (main `84cf85a` merged in) with its
schema: all 32 integration modules **625 OK** (admin_markets 4, age_bands 11, audit_trail 15,
channel_binding 27, commercial_flows 53, concurrency 8, critical_journey 31, crm_privacy 29,
crm_segments 7, custom_domains 9, distribution 21, extras_inventory 17, fx_snapshot 5, grant_expiry 9,
inventory 31, legacy_pricing 15, legacy_pricing_review 23, loyalty_admin 7, migrations_notify 7,
modification_determinism 27, money_fields 9, patches 21, portfolio 2, post_booking_extras 12,
pricing_policies 14, public_booking 17, restrictions 25, security_hygiene 14,
security_regressions 59, self_service_money 75, snapshot_integrity 9, system_status 12; the 12
review tests fail or error on `665b6b9` and its schema, the identity test on the branch before its
fix), the upstream suites with the branch's code and schema (eval harness 76/76, front-desk journey
13/13, banquet 101 OK), 400 unit tests, ruff clean, `npx tsc -b` and `npm run i18n:tex` clean,
e2e `crm-profile.spec.ts` passed twice in a row against the branch (own bench server and vite dev
server; bundles not rebuilt on the branch).

**G-46 (2026-09-24, ADR-059, branch `reports-g46` on main `665b6b9`, main `5e47867` merged in; no
schema change).** Contract vs selling reconciles: per stay priced from a contract, contract cost +
margin = the accommodation selling price the cost was marked up to (same currency at the recorded
rate, same tax basis), and margin % is over that price (it was over gross revenue: 5.69 % instead of
6.54 % on the test stay); revenue = accommodation + extras + taxes on top + stays without a contract
cost; each row is rounded once, a total is the sum of its rows, per currency, never converted (the
review follow-up below replaces the rounding: each stay is split over its nights in whole cents). New
views: hotel, hotel group, promotion, cancellation, payment (with payments by method), extras,
conversion; stay dates by night. New filters: scope (a hotel, a group, an enterprise or all,
narrowed to the viewer's `report.view` hotels), market, channel, room, rate, currency, a stay and a
sale window together. Every report endpoint declares `report.view`; cost and margin need
`price.view_cost` at every hotel of the report (the payment view needed only `report.view`; since the
review follow-up it needs `payment.view` at every hotel). Each view is a fixed number of parameterised SQL
aggregates (the guest-country N+1 is gone); the portfolio's scope labels and alert room names are read
in one query each. Reports UI: one filter card kept in the URL across the views. New tests:
integration `test_reports` 22 (on `665b6b9` 21 fail: 3 assertions (margin % over gross, 6 queries
for 3 stays against 4 for 1, no endpoint declaring a capability) and 18 errors for the missing views
and filters; the old production endpoint's test passes before and after); e2e `reports.spec.ts`. On
the branch with its schema: all 33 integration modules **647 OK** (admin_markets 4, age_bands 11,
audit_trail 15, channel_binding 27, commercial_flows 53, concurrency 8, critical_journey 31,
crm_privacy 29, crm_segments 7, custom_domains 9, distribution 21, extras_inventory 17, fx_snapshot 5,
grant_expiry 9, inventory 31, legacy_pricing 15, legacy_pricing_review 23, loyalty_admin 7,
migrations_notify 7, modification_determinism 27, money_fields 9, patches 21, portfolio 2,
post_booking_extras 12, pricing_policies 14, public_booking 17, reports 22, restrictions 25,
security_hygiene 14, security_regressions 59, self_service_money 75, snapshot_integrity 9,
system_status 12), the upstream suites with the branch's code and schema (eval harness 76/76,
front-desk journey 13/13, banquet 101 OK), 400 unit tests, ruff clean, semgrep (Frappe rules, ERROR)
0 findings on the changed Python files, `npx tsc -b`, `npm run build` (bundles not committed) and
`npm run i18n:tex` clean; e2e `reports.spec.ts` and `portfolio.spec.ts` (3 tests) passed against the
branch (own bench server and vite dev server, after a migrate with the branch).

**G-60 and G-64 (2026-09-24, ADR-060, branch `shell-g60-g64` on main `665b6b9`, main `b074527`
merged in; no schema change).** The entry screens say TEX Engine: a TEX sign-in page in the six TEX
languages with the brand from TEX Settings, the tab title, favicons, Desk logo and apps tile, and
`hooks.py` (the app stays `kamra`, ADR-001). `/` sends a Desk user to `/kamra/tex` and a visitor to
`/kamra/login`; a verified custom booking host keeps serving its engine at `/`. The sign-in page and
the admin navigation show "Based on Kamra PMS · AGPL-3.0 · Source code" (the source URL from
`tex_source_url`, https only, else the TEX repository). The navigation carries R-35's sub-sections;
new read-only lists (`kamra.tex.api.lists`: contract versions, price periods, occupancy rules, rate
plans, restrictions as ranges, booking-engine rooms, communications) declare their capability and
return only granted hotels; Booking Engine › Analytics is built on `reports.dashboard` and links
Reports › Conversion; CRM Campaigns is listed as "Not available yet". New tests:
`test_entry_branding` 15 (on `665b6b9`: 3 fail and 9 error; the 3 that pass guard the custom host's
`/`, the SPA mount and the existing endpoints' refusals), e2e `entry-branding.spec` 5. On the
branch with its schema: all 34 integration modules **662 OK** (admin_markets 4, age_bands 11,
audit_trail 15, channel_binding 27, commercial_flows 53, concurrency 8, critical_journey 31,
crm_privacy 29, crm_segments 7, custom_domains 9, distribution 21, entry_branding 15,
extras_inventory 17, fx_snapshot 5, grant_expiry 9, inventory 31, legacy_pricing 15,
legacy_pricing_review 23, loyalty_admin 7, migrations_notify 7, modification_determinism 27,
money_fields 9, patches 21, portfolio 2, post_booking_extras 12, pricing_policies 14,
public_booking 17, reports 22, restrictions 25, security_hygiene 14, security_regressions 59,
self_service_money 75, snapshot_integrity 9, system_status 12), the upstream suites with the
branch's code (76/76, 13/13, banquet 101), 400 unit tests, ruff and semgrep (ERROR) clean on the
changed files, `npx tsc -b`, `npm run build` and `npm run i18n:tex` clean; Playwright as in the
table above.

**ADR-058 review follow-up (2026-09-25, branch `fix-mig` on main `84cf85a`, main `5e47867` merged in).**
An independent review of G-73 / G-76 found 1 Critical, 1 High, 4 Medium and 6 Low issues. All are
fixed, with tests that fail first.
- *C1:* an interrupted migration test run could commit an emptied site. Every migration test now
  refuses commits until its own rollback; the SIGINT simulation's marker row was committed before
  and not after. The tests that empty the site or run every patch over it run only on a disposable
  site (M4 as well).
- *H1:* `ran_before` reads skipped and suffixed Patch Log rows as Frappe does.
- *M1–M3:* p01 and p36 run once; no test runs a real DocType sync.
- *L1–L6:* the digest names passwords by record; guests get a guest-safe refusal; refusals name
  the version that failed, survive a queue outage and are audited once an hour; p19 lists charges
  by name; one unreadable index table stops nothing.
- *Fail-first on `aa742c0`:* `test_patches` 8 fail and 1 error; `test_snapshot_integrity` 5 fail and
  1 error.
- *Runs:*
  - Migrate, then all 32 integration modules on the shared site: **639 OK** (the 3 whole-site tests
    skipped there): admin_markets 4, age_bands 11, audit_trail 15, channel_binding 27,
    commercial_flows 53, concurrency 8, critical_journey 31, crm_privacy 29, crm_segments 7,
    custom_domains 9, distribution 21, extras_inventory 17, fx_snapshot 5, grant_expiry 9,
    inventory 31, legacy_pricing 15, legacy_pricing_review 23, loyalty_admin 7,
    migrations_notify 7, modification_determinism 27, money_fields 9, patches 31, portfolio 2,
    post_booking_extras 12, pricing_policies 14, public_booking 17, restrictions 25,
    security_hygiene 14, security_regressions 59, self_service_money 75, snapshot_integrity 13,
    system_status 12.
  - `test_patches` and `test_snapshot_integrity` on a disposable site, the whole-site tests
    included (`disposable_test.sh`: site made, tested, dropped): patches **31 OK** (none skipped),
    snapshot_integrity **13 OK**.
  - Upstream suites after the migrate, with the branch's code and with the shared tree's: eval
    harness 76/76, front-desk journey 13/13, banquet 101 OK (both).
  - 400 unit tests; ruff clean.

**ADR-056 second review follow-up (2026-09-25, branch `fix-crmp2` on main `b074527`, mains `9215991` and
`b72b2a8` merged in, patch p45).** A second independent review of the CRM privacy work found 1 High, 3 Medium and
9 Low issues. All are fixed, with tests that fail first (ADR-056, second review follow-up).
- *H1:* a consent withdrawal read the funnel through `IFNULL`/`OR` (no index) inside its transaction,
  locking every funnel row a booking writes; tracking swallowed deadlocks, so a booking InnoDB had rolled
  back could be reported. The rows are read through new indexes and written by primary key; a deadlock
  or lock timeout while tracking, mailing, starting a payment or triggering the channel push is re-raised
  (the booking is retried or fails).
- *M1:* an erasure kept the e-mail consent and left contact data in cases, funnel hashes, bookings'
  booker fields and the change history; now it withdraws every consent and removes them (p45 for older
  erasures). Clearing an e-mail or phone does the same for what it leaves behind.
- *M2:* duplicate profiles are merged in the CRM (and by the legacy endpoint through it): every link from
  the meta, the loyalty ledger (one balance, tier from the merged lifetime), stricter consent, audited;
  a profile lists its possible duplicates (same phone or e-mail).
- *M3:* the loyalty ledger in Desk / REST is read at each entry's hotel (new `property`), not the program's.
- *L1–L9:* consent text read strictly in the CRM; no copies of contact data from the change history;
  a case's session, quote and recovery booking and a funnel event's session and payload withheld; another
  hotel's ledger entries without dates, reason or author; browser funnel values checked against what the
  site sells; the phone finds a profile only for staff and only when one profile has it; a Desk / REST
  consent change stamped and audited; a case written after a withdrawal anonymous; p40 on its own paths.
- *Fail-first on main `b72b2a8` (its code and schema, the new tests added):* `test_crm_privacy_review`
  27 of 28 fail or error (p40's own paths pass: coverage), among them the booking reported after its
  rollback ("booked: reported a rolled-back booking") and the withdrawal waiting for a booking's funnel
  event on a second connection ("Lock wait timeout exceeded", with the new indexes already on the site);
  the three `test_crm_privacy` tests changed for L5 and L6 fail. Before the two-connection test was
  added: 26 of 27 on `9215991` and on `b074527`.
- *Runs (2026-09-24, main `b72b2a8` merged in, one hold of the bench-test lock):*
  - Migrate, then all 35 integration modules on the shared site: **723 OK**, 3 skipped (the whole-site
    tests): admin_markets 4, age_bands 11, audit_trail 15, channel_binding 27, commercial_flows 63,
    concurrency 8, critical_journey 31, crm_privacy 29, crm_privacy_review 28, crm_segments 7,
    custom_domains 9, distribution 21, entry_branding 15, extras_inventory 17, fx_snapshot 5,
    grant_expiry 9, inventory 31, legacy_pricing 15, legacy_pricing_review 23, loyalty_admin 7,
    migrations_notify 7, modification_determinism 27, money_fields 9, patches 31, portfolio 2,
    post_booking_extras 12, pricing_policies 14, public_booking 17, reports 22, restrictions 33,
    security_hygiene 14, security_regressions 59, self_service_money 76, snapshot_integrity 13,
    system_status 12.
  - `test_patches` on a disposable site, the whole-site tests included (site made, tested, dropped):
    **31 OK** (none skipped).
  - Upstream suites with the branch's code and schema: eval harness 76/76, front-desk journey 13/13,
    banquet 101 OK.
  - E2E against the branch (its own bench server on :8014 and Vite dev server on :5184, base
    `http://test.localhost:5184`): `crm-profile`, the new `crm-merge` (a shared phone shown as a possible
    duplicate, merged from the profile), `crm-admin` (loyalty programs and ledger) and `booking` (desktop
    and mobile, 5 each) passed twice each.
  - 419 unit tests; ruff clean; `tsc`, `npm run build` and `npm run i18n:tex` clean (bundles not
    committed on the branch).
  - Main `e78ba7b` merged after these runs (editor save fixes: frontend, e2e and docs, no Python): `tsc`,
    build and i18n clean again; migrate, then `crm-profile`, `crm-merge`, `crm-admin` and `editor-edits`
    passed twice each against the branch's servers.

**ADR-056 third review follow-up (2026-09-25, branch `fix-crmp3` on main `9642228`, main `f855850`
merged in, patch p48).** A focused review of the guest merge and of the second review's H1 fix found 1
High, 6 Medium and 3 Low issues. All are fixed, with tests that fail first (ADR-056, third review
follow-up).
- *M-6 (a regression of H1):* a lock wait timeout in tracking or a guest e-mail failed the booking; now
  it undoes that step only (a savepoint) and the booking goes on; a deadlock is still raised. The funnel
  purge deletes in small committed batches through a new index.
- *H-1:* the merge read a stale snapshot; now it locks both profiles and reads what it moves with
  locking reads; bookings, loyalty entries, communications and stays lock the profile they link to; a
  redemption reads its balance with a lock (two could spend the same points).
- *M-1–M-5:* the duplicate's comments, mail, tasks and activity move; an erased profile is never merged
  (`Guest.tex_erased_at`); the merge event names every record moved and the duplicate is kept 90 days
  as a Deleted Document; the legacy endpoint checks every record's hotel; p48 marks earlier erasures
  from their records and removes what they left.
- *Low:* names compared as stored; p45 reads the marker; a record naming no hotel needs a platform
  administrator.
- *Fail-first on main `f855850`:* `test_crm_third_review` 13 of the 14 that run on the shared site, and
  all 7 concurrency tests on a disposable site made with main, fail or error; in `test_crm_privacy_review`
  the 3 tests changed for M-6 and the Low fail.
- *Runs (2026-09-25, one hold of the bench-test lock):*
  - Migrate, then all 36 integration modules on the shared site: **754 OK**, 10 skipped (the 3
    whole-site patch tests and the 7 concurrency tests): admin_markets 4, age_bands 11, audit_trail 15,
    channel_binding 27, commercial_flows 63, concurrency 8, critical_journey 31, crm_privacy 29,
    crm_privacy_review 28, crm_segments 7, crm_third_review 21 (7 skipped), custom_domains 9,
    distribution 21, entry_branding 34, extras_inventory 17, fx_snapshot 5, grant_expiry 9, inventory 31,
    legacy_pricing 15, legacy_pricing_review 23, loyalty_admin 7, migrations_notify 7,
    modification_determinism 27, money_fields 9, patches 32 (3 skipped), portfolio 2,
    post_booking_extras 12, pricing_policies 14, public_booking 17, reports 22, restrictions 33,
    security_hygiene 14, security_regressions 59, self_service_money 76, snapshot_integrity 13,
    system_status 12.
  - On a disposable site made with the branch (made, tested, dropped): the concurrency tests **7 OK**,
    `test_patches` **32 OK** (none skipped).
  - Upstream suites with the branch's code and schema: eval harness 76/76, front-desk journey 13/13,
    banquet 101 OK.
  - E2E against the branch (its own bench server on :8014 and Vite dev server on :5184, base
    `http://test.localhost:5184`): `crm-profile`, `crm-merge`, `crm-admin` and `booking` (desktop and
    mobile) passed twice each.
  - 419 unit tests; ruff clean; `tsc`, `npm run build` and `npm run i18n:tex` clean (bundles not
    committed on the branch).

**Go-live.** Launch readiness per area (READY / PARTIAL / BLOCKED), the blockers and the owner inputs are in
[`GO_LIVE_READINESS.md`](GO_LIVE_READINESS.md). Verdict: NOT READY.

**G-60 / G-64 review follow-up (2026-09-25, branch `fix-shell` on main `9215991`, mains `b72b2a8`, `e78ba7b` and `9642228` merged in; ADR-060 review section; p47).**
An independent review found 3 Medium and 9 Low issues; all are fixed or answered, each with a test
written first. M1: the sign-in page took any answer of `/api/method/login` for a session; now only
"Logged In" signs in, a two-factor account gets a code step, an expired password goes to Frappe's
reset page (same site only), "Forgot password?" and "Other sign-in options" lead to Frappe's page.
M2: guests (every booking-engine page, the widget's modal, the legacy guest pages) and Desk (Help ›
About) are offered the source too, and every offer is the running version's (`/tree/<commit>` from
`tex_source_commit` or the checkout's HEAD, or `tex_source_url` with `{commit}`); ADR-060's
"white label" reason was wrong. M3: a booking site opens under `/tex/booking-engine/sites/`; admin
page names are refused as new slugs; p47 reports older sites named so (never renamed). L1 an HTTP
test of `session.entry`; L2 no source address with credentials; L3 the served pages carry the offer
and the brand; L4 one actor rule; L5 version tables ordered and their cut told; L6 only openable
guests are links; L7 Restrictions tab needs `price.view`, `aria-controls` only when open, sign-in
focus and error wiring; L8 the G-60 fail-first counts corrected; L9 portal and mixed-cost tests.
The e2e found a race in the sidebar (an area opened while a navigation loads closed when it landed),
fixed. Fail first on `9215991` with the new tests: `test_entry_branding` 8 failures, 3 errors (22 of
34 pass: the tests that pin behaviour already right but untested), `test_patches` 1 failure and 1
error, e2e `entry-branding.spec` 7 of 10 fail. On the branch with its schema: all 35 integration
modules **743 OK**, 3 skipped (admin_markets 4, age_bands 11, audit_trail 15, channel_binding 27,
commercial_flows 63, concurrency 8, critical_journey 31, crm_privacy 29, crm_privacy_review 28,
crm_segments 7, custom_domains 9, distribution 21, entry_branding 34, extras_inventory 17,
fx_snapshot 5, grant_expiry 9, inventory 31, legacy_pricing 15, legacy_pricing_review 23,
loyalty_admin 7, migrations_notify 7, modification_determinism 27, money_fields 9, patches 32 (3
skipped; 32/32 on a disposable site), portfolio 2, post_booking_extras 12, pricing_policies 14, public_booking 17, reports 22,
restrictions 33, security_hygiene 14, security_regressions 59, self_service_money 76,
snapshot_integrity 13, system_status 12), the upstream suites (76/76, 13/13, banquet 101), 419 unit
tests, ruff and semgrep (ERROR) clean on the branch's Python files, `npx tsc -b`, `npm run build`
and `npm run i18n:tex` clean; Playwright as in the table above. No requirement status changes.

**G-48 / G-84 review follow-up (2026-09-24, branch `fix-restr` on main `84cf85a`, main `9215991` merged in; ADR-057 review follow-up; no patch).**
The restrictions grid's E2E on main failed: a clear inserted an empty scope-less duplicate cell and a
site whose table lacked a G-48 column dropped the value (`5462677`, `e8ad67e`; the leftover cell
`3f9otn5e8f` was removed through the fixed clear path). An independent review then found H1 (High):
a change or cancellation taking a booking below a promotion's minimum basket left the untouched
rooms' discount unpaid, so "a booking is never sold at a price other than its rooms' together" was
untrue. Decision: clawback by default — the changed or cancelled room carries the discount the other
rooms keep (explicit line, explanation, revision, audit, shown to the guest before confirming, a
ledger so each discount is owed once), on every staff and guest path. Also fixed: M1 (the search's
"from" price was not always bookable; the booking pass can raise a price), M2 (a minimum counts only
the rooms its promotion covers), L1 (length rules refused changes toward compliance, kept in-house
guests), L2 (`quote_rooms` input and cost), L3 (every multi-room quote records its booking), L4 (old
snapshots counted add-ons), L5 (oversized ARI ranges); the stored-proposal restriction paths are
tested. R-29 goes back to PARTIAL (recorded limits). Fail first on `78eda06`: 12 unit tests fail and
the new `test_basket_clawback` module errors; 11 `test_commercial_flows` tests, 1
`test_self_service_money` test and 1 `test_restrictions` test fail or error (the 3 stored-proposal
tests cover enforcement that already held). With the branch's code and schema (main `9215991` merged, migrated, one hold of the bench lock):
all 34 integration modules **695 OK** (3 whole-site patch tests skipped: they run on a disposable site
only) — admin_markets 4, age_bands 11, audit_trail 15, channel_binding 27, commercial_flows 63,
concurrency 8, critical_journey 31, crm_privacy 29, crm_segments 7, custom_domains 9, distribution 21,
entry_branding 15, extras_inventory 17, fx_snapshot 5, grant_expiry 9, inventory 31, legacy_pricing 15,
legacy_pricing_review 23, loyalty_admin 7, migrations_notify 7, modification_determinism 27,
money_fields 9, patches 31, portfolio 2, post_booking_extras 12, pricing_policies 14, public_booking 17,
reports 22, restrictions 33, security_hygiene 14, security_regressions 59, self_service_money 76,
snapshot_integrity 13, system_status 12; the upstream suites with the branch's code and schema (eval
harness 76/76, front-desk journey 13/13, banquet 101 OK); 419 unit tests; ruff clean; `npx tsc -b`,
`npm run build` (bundles not committed) and `npm run i18n:tex` clean. Playwright against the branch
(its own bench server, RQ worker and Vite dev server): `restrictions-grid.spec.ts` twice in a row
(1/1, 1/1), then `booking.spec.ts`, `crs.spec.ts` and `manage-money.spec.ts` 13/13 (desktop and
Pixel 7).

**G-46 review follow-up and G-98 (2026-09-24, branch `fix-reports` on main `b074527`, main `b72b2a8`,
`e78ba7b`, `9642228`, `f855850` and `23767cb` merged in; ADR-059 review follow-up; patch p46, between p45 and p47).** The review's High, older than the reports
(G-98): contract cost reached guests and agents through cost-stage offers (their discount and a basket
compared with the cost). Every promotion outcome now carries its stage; the guest view and the staff
view without `price.view_cost` drop cost-stage outcomes (older snapshots judged by their explanation);
a reservation's Desk-visible `tex_promotions` lists only the promotions of the selling price. Reports
(M1–M5, L1–L8): whole-cent night splits (every grouping and fold gives the same totals), the
reservation's own taxes, cancelled stays count only their fee, cost-stage offers in the promotion view
only with cost access, group-site sessions in conversion for the whole group only, sessions counted
once (never above 100 %), payments per transaction currency and only with `payment.view`, refused
filters, cut option lists said, indexes by hotel and date (p46), 60 report runs a minute per user
(views, dashboard, pace, portfolio). L9 (portfolio alerts N+1) not done. The reports' date filter
lost "from" when "to" was typed while the report loaded (router transition): fixed. Fail first: on
`b074527` unit `test_cost_stage_privacy` 3 failures and 3 errors of 6, integration
`test_cost_stage_privacy` 2 of 3 and `test_reports` 17 of 35 failed, `test_patches` 2 (p46 missing);
on the merged branch before their fixes, the `tex_promotions` test (1 of 4) and the dashboard / pace
throttle test (1 of 36) failed. With the branch's code and schema (main `23767cb` merged, migrated, one
hold of the bench lock): all 37 integration modules **783 OK** (skipped: 3 whole-site patch tests and 7
second-connection tests of `crm_third_review`, which run on a disposable site only; there `test_patches`
33/33 OK with p45–p48 in order, while `crm_third_review` errors on the disposable site for want of a
signing key in its site config, `SigningKeyMissing`, not a code fault) — admin_markets 4, age_bands 11,
audit_trail 15, channel_binding 27, commercial_flows 63, concurrency 8, cost_stage_privacy 4,
critical_journey 31, crm_privacy 29, crm_privacy_review 28, crm_segments 7, crm_third_review 21,
custom_domains 9,
distribution 21, entry_branding 34, extras_inventory 17, fx_snapshot 5, grant_expiry 9, inventory 31,
legacy_pricing 15, legacy_pricing_review 23, loyalty_admin 7, migrations_notify 7,
modification_determinism 27, money_fields 9, patches 33,
portfolio 2, post_booking_extras 12, pricing_policies 14, public_booking 17, reports 36,
restrictions 33, security_hygiene 14, security_regressions 59, self_service_money 76,
snapshot_integrity 13, system_status 12; upstream suites with the branch (eval harness 76/76,
front-desk journey 13/13, banquet 101 OK); 425 unit tests; ruff clean; `npx tsc -b`, `npm run build`
(bundles not committed) and `npm run i18n:tex` clean. Playwright against the branch (its own bench
server, RQ worker and Vite dev server): `reports`, `portfolio`, `booking`, `crs` and `manage-money`
specs 16/16 (desktop and Pixel 7) on the final tree. Earlier runs on the shared site found the demo
hotel sold out on the specs' random stay dates (a search without rates, `booking.spec`); the dev tool
`demo_seed.release_test_bookings` released 645 future test-run stays under the bench lock (and 10
more before the last run).

**Pricing Workspace, slice S2 (2026-09-24, ADR-061, branch `pw-backend` on main `1575c8b`).**
Backend only: `price_matrix`, `validate_version` and `preview_price` take the editor's unsaved
`data` and work on the draft in memory (the read-only overlay: `contract.edit` and Draft only, the
save's own checks, `~<_key>` rule ids, at most 5,000 rows, nothing saved or audited); a blank rule
value is refused by `save_version` (it was stored and priced as 0); `get_version` adds
`can_preview`, `can_publish`, `can_edit_contract`, `basis_locked` and `contract_doc.minor_units`.
New `test_pricing_workspace_api` (17; on the base, 14 fail and 3 pass: the basis change before and
after publish and Finance's saved-matrix read pin existing behaviour); `test_security_regressions`
G-11 allows the three flags in an agent's catalogue answer (false). On the branch, migrated with
it: all 38 integration modules **800 OK**, 10 skipped (the 3 whole-site patch tests and the 7
concurrency tests of the ADR-056 third review, as before); 425 unit tests; ruff clean. No frontend
change in this slice. The workspace UI and the other backend slices are not built yet (R-04).

**Pricing Workspace, slice S3 (2026-09-24, ADR-061, branch `pw-backend`).** Backend and frontend
types: `price_matrix` keeps its keys and adds, from the engine's own resolvers (pure
`pricing/matrix.py`), the rule behind each cell (`rooms[].sources`: scope, derivation chain,
overridden rules), each room's effective capacity, the age bands with their origin (the version or
the pricing policy), the occupancy rules inherited from policies, the engine's adult default, and,
with `parties` and `party_room`, each sample party's occupancy total per period (after the engine's
capacity check). New `test_matrix` (18, pure); `test_pricing_workspace_api` 31 (+14; on the S2 tip
all 14 fail). On the branch, migrated with it: all 38 integration modules **814 OK**, 10 skipped (as
before); 443 unit tests; ruff; eval 76/76, journey 13/13, banquet 101 OK; `tsc -b` and the build
pass. No screen changes. Performance measured with the opt-in `bench_pricing_workspace` (ADR-061):
on 12 rooms × 26 periods (1,406 rows) the unsaved-data matrix takes 0.25 s (0.33 s with 12 sample
parties), the preview 0.24 s, validation 2.3 s; near the 5,000-row cap 0.70 s, 0.69 s and 10 s
(validation costs the same without data; the UI slices must keep one validation in flight). O1–O5
are provisional owner decisions (GO_LIVE_READINESS owner input 13), none implemented on this
branch. The workspace UI (S6–S16) and backend slices S4–S5 are not built yet (R-04 stays PARTIAL).

**Pricing Workspace, slice S4 (2026-09-24, ADR-061, branch `pw-backend`).** Backend and frontend
types: each validation issue says what it is about in an optional `ref` (the rule or rules, room,
period, other period, age band(s), party and board; row names, or `~<_key>` for unsaved rows), so
the workspace can mark the cell or row and show band labels; codes and messages are unchanged
(80 scenarios compared). New publish errors for board rules: an unknown room or period, and two
rules of one board for the same room and period (`BOARD_UNKNOWN_ROOM`, `BOARD_UNKNOWN_PERIOD`,
`BOARD_DUPLICATE`); drafts with such rows can no longer be published (announced in
GO_LIVE_READINESS; none on the development site). The draft overlay refuses two rows of one table
with the same key (S2/S3 review item). New `test_validate_refs` (37, pure; 31 fail on the S3 tip);
`test_pricing_workspace_api` 37 (+6; 4 fail on the S3 tip, 2 pin existing behaviour). On the
branch, migrated with it: all 38 integration modules **820 OK**, 10 skipped (as before); 480 unit
tests; ruff; eval 76/76, journey 13/13, banquet 101 OK; `tsc -b`, the build and `i18n:tex` pass. `bench_pricing_workspace`: validation with refs 1.9 s saved / 2.1 s unsaved on 12 rooms × 26 periods, 9.5 s near the cap (S3: 2.3 s, 10 s), so no slowdown. O1–O5 are unchanged by S4
(none on this branch; owner input 13). The workspace UI (S6–S16) and backend slice S5 are not built
yet (R-04 stays PARTIAL).

**Pricing Workspace, slice S5 (2026-09-24, ADR-061, branch `pw-backend`).** The last backend slice,
with frontend types. The price test (`preview_price`) takes each child as an age in whole years
(unchanged quotes: compared with the pre-S5 code on a published and a draft version), in months or
by date of birth (checked as a booking checks it), and refuses anything else instead of failing or
truncating (`7.5`, adult ages, more than 12 children). `apply_op_values` changes up to 500 entered
prices of a draft once by an op, as the ARI grid's rate change does (HALF_UP to the contract
currency; read-only; `contract.edit`): the server half of O4 and of the bulk Adjust…. **GAP-12:**
each night of an internal quote reports `subtotal_adults`, `subtotal_children` and `subtotal_board`,
running totals the engine already held (reported only, internal only: no price, total,
explanation or engine version changes; the guest view and `strip_internal` never carry them).
Tests: `test_engine` `TestReportedSubtotals` (7) and `test_matrix` `TestAdjustAmount` (4), 10 of the
11 failing on the S4 tip; `test_pricing_workspace_api` 48 (+11, 10 failing on the S4 tip); 11
mutants killed. On the branch, migrated with it: all 38 integration modules **831 OK**, 10 skipped
(as before); 491 unit tests; ruff; eval 76/76, journey 13/13, banquet 101 OK; `tsc -b`, the build and `i18n:tex` pass. `bench_pricing_workspace`: `apply_op_values`
0.007 s for 500 prices; the overlay, matrix, preview and validation as after S4 (validation 2.1 s
realistic, 9.6 s near the cap). O4's server half is on this branch (its cell commit is S9); O1–O3 and
O5 are unchanged (S1, S13); all five stay owner input 13. The backend slices S2–S5 are done; the
workspace UI (S6–S16) is not built yet (R-04 stays PARTIAL).

**Pricing Workspace, lane merge (2026-09-24, ADR-061, branch `pricing-workspace`).** The backend
lane (`pw-backend`, S2–S5) is merged into the frontend lane (S1 shorthand parser, S7 design-system
Popover / Menu / Tooltip and keyboard grid hooks, S6 pure workspace model); no textual conflicts, and
the S1, S7 and S6 decisions are recorded in ADR-061 with the backend's. On the merged tree:
all 38 integration modules **831 OK**, 10 skipped (as before); 491 unit tests; ruff; `npm run
test:unit` 121 and `npm run test:dom` 24; `tsc -b`, the build and `i18n:tex`; eval 76/76, journey
13/13, banquet 101 OK; Playwright against the tree's own servers (`contract-admin`,
`editor-edits`, `critical-journey`, `policy-revisions`, `booking` desktop and mobile,
`restrictions-grid`) 15/15. `bench_pricing_workspace` on the merged tree (seconds, realistic 12 × 26
/ near the row cap 12 × 40): the overlay 0.16 / 0.49, `price_matrix` with unsaved data 0.23 / 0.66,
`preview_price` 0.22 / 0.69, `validate_version` 2.1 / 9.8, `apply_op_values` 0.007; as after S5.
O1–O5 after the merge (all provisional, owner input 13): the parse of O1–O3 and O5
(S1) and the model's storage of O1–O3 board entries and of O4's base-room adjustment (S6) are on the
branch, and O4's server half (S5) with them; no workspace screen that uses them is built yet (S8–S16).
R-04 stays PARTIAL.

**Pricing Workspace, slice S8 (2026-09-24, ADR-061, branch `pricing-workspace`).** The version
editor has four sections (Pricing, Commercial rules, Offers & promotions, Preview & audit) under a
sticky commercial context header; old tab links still land (`#rates`, `#occupancy`, `#plans` …).
Commercial rules keeps every former editor as the "Rule tables". The header shows the contract's
terms, the live check and the actions (Save, Discard, Check, Publish, and Price test for who may
see cost); the pricing basis is switched there in a non-modal popover before the first publish.
The server prices and checks what is on screen while it is edited, without a save (`useDraftPreview`:
an editable draft through the read-only overlay, with one validation in flight; other cost viewers
the saved version, never a validation; agents a catalogue with no cost call). BOARD_* issues count
on Pricing. Frontend only. Verification: `npm run test:unit` 143, `test:dom` 24, build, i18n, 491
Python unit tests, ruff; the pricing, contract, booking and security integration modules on this
tree (see ADR-061); Playwright `contract-admin`, `critical-journey`, `editor-edits`,
`entry-branding`, `policy-revisions`, `restrictions-grid` pass unchanged; the slice's manual checks
pass (7/7). O1–O5 unchanged by S8 (owner input 13). The matrix, occupancy, boards, price-test and
anchoring screens are S9–S15; R-04 stays PARTIAL.

**Pricing Workspace, S8 review follow-up (2026-09-25, ADR-061, branch `pricing-workspace`).**
- *Drafts above the overlay's row cap.* The Check button validates the saved draft by name, as
  the design says; so does a draft with nothing unsaved. A draft above the overlay's 5,000-row
  cap (a realistic weekly contract has 5,892 rows) is priced and checked by name too, with no
  cap. Its unsaved changes are not previewed until they are saved, and the matrix, the live check
  and the Price test say so ("Saved draft only").
- *Server change (additive).* `get_version` says `overlay_max_rows`, and the overlay's refusal
  is typed `OverlayTooLarge`: the same 417 and the same message.
- *Failures are shown.* A refused live check or matrix now shows the server's reason and Try
  again, where before it showed a spinner and older counts indefinitely. Undoing while a check
  ran no longer leaves the chip stale.
- *Verification.* `npm run test:unit` 148, `test_pricing_workspace_api` 50 (fail-first
  recorded), the regression, upstream and Playwright runs in ADR-061, and four browser checks.
  The benchmark above the cap is in ADR-061.

R-04 stays PARTIAL.

**Pricing Workspace, slice S9 (2026-09-25, ADR-061, branch `pricing-workspace`).** Pricing shows
the room price matrix: rooms × All periods and the period columns, typed into with the shorthand
(prices and formulas, a reading line, Enter / Tab / Escape, error drafts that are never lost),
priced live by the server without a save. A relative entry on the base room changes its entered
price once on the server and stores the result (O4); on any other room it writes a formula;
Ctrl/Cmd+Enter applies an entry to a selection as one change. A rule popover (Alt+Enter) stores
any op as chosen. Rooms are added, made base, derived, sized, moved and removed, and periods added
(with their end date), renamed (their rules follow), dated, adjusted per night, duplicated,
copied, moved and deleted from the matrix's own menus; each change is one entry of the workspace
undo history (its buttons are S10). Published versions are read-only. Frontend only. Verification:
`npm run test:unit` 166, `test:dom` 24, build, i18n (153 keys), Python unit 491; a dev-server
Playwright smoke 10/10 and `contract-admin`, `critical-journey`, `editor-edits`, `entry-branding`
unchanged (ADR-061). O4 is now built end to end and O5's message is on screen (owner input 13).
R-04 stays PARTIAL.

**Pricing Workspace, S9 review follow-up (2026-09-25, ADR-061, branch `pricing-workspace`).**
- *O5 in the night adjustment.* The period night adjustment's +/- amounts are parsed with the
  contract currency's decimals, as O5 says. A KWD, BHD, OMR, JOD or TND contract takes `+12.345`,
  and a stored adjustment re-opens as text that applies again. Before, both were refused as "Is
  this 1500 or 1.5?".
- *Late server adjustments.* While the server adjusts the base room's prices of an entry, every
  cell of the entry waits: none can be edited, and an answer for a cell changed meanwhile stores
  nothing ("This cell changed …"). An open editor stays on its own cell when rows above it change.
- *Screen text.* On the base room, "50%" now reads "50% of 70.00", not like "+50%". Older resolved
  prices are announced as "updating". Cells open the full keyboard on phones.
- *Verification.* `npm run test:unit` 171 (fail-first recorded), `test:dom` 24,
  `test_pricing_workspace_api` 50, a browser check 8/8 (also run on the unfixed sources, where it
  failed), and `contract-admin`, `critical-journey` and `editor-edits` unchanged. The overlay's
  performance on a realistic contract was measured again (12 rooms × 26 periods: overlay 0.16 s,
  priced unsaved 0.25 s, checked unsaved 2.0 s; ADR-061).

Frontend only. R-04 stays PARTIAL.

**Pricing Workspace, slice S10 (2026-09-25, ADR-061, branch `pricing-workspace`).** The room price
matrix gets its bulk tools. A click on a row or column header selects its price cells. Fill → and
Fill ↓ (toolbar, Ctrl/Cmd+R, Ctrl/Cmd+D) copy across periods and down rooms; a price copied into
a formula row asks "Set a fixed price override?" first, and a formula is never copied into a
price row. Ctrl/Cmd+C and Ctrl/Cmd+V exchange tab-separated text with spreadsheets, all or
nothing, with the currency-aware parser (O5). Adjust… changes the selected entered prices by
+%, −%, +amount, −amount or ×, with the server's preview before Apply. Undo and Redo (toolbar,
Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z, Ctrl/Cmd+Y, on every keyboard layout) are announced, and a bulk
operation shows "Applied to N cells · Undo" for 10 s. Edits in the Advanced rule tables and
Offers are now undo entries too, so an undo in the matrix never drops them. Ctrl/Cmd+S saves on
every layout. Frontend only. Verification by the review: `npm run test:unit` 201, `test:dom` 24,
build, i18n (89 keys); a dev-server check 6/6 and `contract-admin` and `editor-edits` unchanged.
The documentation was added by the review follow-up. R-04 stays PARTIAL.

**Pricing Workspace, S10 review follow-up (2026-09-25, ADR-061, branch `pricing-workspace`).**
- *Fill down copies what a cell shows.* A period that follows its room's All-periods rule, filled
  into another room, now copies that rule. Before, the target got its own room's rule: Family
  Suite ×1.15 filled onto Garden Villa gave ×1.35 and dropped Garden Villa's override. Ctrl/Cmd+C
  copies the rule such a cell shows instead of an empty text.
- *A fill from an empty cell says what it cleared* ("Applied to 4 cells · 4 cells cleared (copied
  from empty cells)"); it can be undone.
- *Documentation:* ADR-061 now records S10 (decision, nine deviations with reasons, tests,
  verification, performance) and the follow-up.
- *Tests:* `npm run test:unit` 204 (fail-first recorded), `test:dom` 27 (a new harness test of
  the undo toast and of the Rule tables' undo entries), `test_pricing_workspace_api` 50, a
  browser check 3/3 (each fails on the S10 sources) with the S10 check 6/6, and
  `contract-admin`, `critical-journey` and `editor-edits` unchanged.

Frontend only. R-04 stays PARTIAL.

**Pricing Workspace, S10 second review follow-up (2026-09-25, ADR-061, branch `pricing-workspace`).**
- *A copied range over a resolved row pastes back onto the same rooms.* Copy now leaves out the
  resolved rows when the selection also holds rooms' entry rows, as the paste does. Before, a
  Shift+Arrow range from Standard to Deluxe over Superior's resolved row, pasted one period to
  the right, put Superior's resolved price on Deluxe as a fixed price and Deluxe's formula on
  Family, with a success toast. Resolved cells selected on their own still copy the server's
  amounts.
- *Copied text ends every row with a line break*, as spreadsheets do, so a copied empty cell
  clears where it is pasted.
- *Ctrl/Cmd+R and Ctrl/Cmd+D typed in a cell editor* no longer reload the page or open the
  bookmark dialog.
- *The undo toast's Undo and close button return the focus to the grid's active cell.*
- *Tests:* `npm run test:unit` 207 and `test:dom` 28 (fail-first recorded),
  `test_pricing_workspace_api` 50, a browser check 5/5 (each fails on the previous sources) with
  the S10 checks 9/9, and `contract-admin`, `critical-journey` and `editor-edits` unchanged.

Frontend only. R-04 stays PARTIAL.

**Pricing Workspace, slice S11 (2026-09-25, ADR-061, branch `pricing-workspace`).** Pricing
shows "Occupancy & child pricing" under the room price matrix. It is a collapsible region that
remembers its state per viewer and opens by default on a draft without occupancy rules; it
opens for `#occupancy`, and `#ages` opens its drawer. Its header holds the rooms scope, child 1
ordering, under ROOM basis the extra-adult unit and whether children fill included places, and
"Child ages…".
- *The ladder* has one row per guest: single use, the adults (the "2 Adults" BASE pair under
  PERSON, the included places and extra adults under ROOM) and the child bands by their labels,
  over the matrix's period columns. Its cells take the occupancy shorthand with the matrix's
  editing model: Enter moves down, and every change is one undo entry. Engine defaults are
  shown ("×1.00 default", the server's value). A band without a rule reads "No rule · not
  sellable", a period rule "◆ OVERRIDE", and policy values show their source. A special
  combination that outranks a cell is noted.
- *The rule popover* "Edit rule: {slot} · {period}" sets rooms, Always wins, a note and periods.
- *The resolved line* shows the server's occupancy total per period for a chosen sample party.
- *The child ages drawer* is a side panel that is not modal. "Add band" starts where the last
  band ends, Enter adds the next one, and generated labels are saved. Bands without names are
  named only on "Name them", and codes stay under Advanced (a rename follows into the rules). An
  age strip marks gaps and overlaps. Inherited policy bands are read-only, with "Customise for
  this contract", and the child rules are there too.
- Band codes are shown as labels everywhere in the region.

Verification: `npm run test:unit` 226 and `test:dom` 29 (fail-first recorded), build, i18n (168
keys); `test_pricing_workspace_api` 50, `test_age_bands` 11 and `test_pricing_policies` 14; a
browser check 4/4 (the slice's seven checks and more); and `contract-admin`, `critical-journey`,
`editor-edits`, `entry-branding` and `policy-revisions` unchanged (15 passed). Frontend only.
R-04 stays PARTIAL.

**Pricing Workspace, S11 review follow-up (2026-09-25, ADR-061, branch `pricing-workspace`).**
- *A room's ladder shows the rules that price it.* In a room scope, a guest priced only by an All
  rooms rule used to read "×1.00 default" or "No rule · not sellable", though the engine applies
  All rooms rules to every room and the resolved line priced the party. A cell without a rule of
  its own now shows the rule the engine would use: "↳ ×0.70 / All rooms", a policy rule with its
  source, or the room's own general rule, ranked as the engine ranks them (an infant's band first,
  version before policy, period before room before All rooms). The default and "not sellable"
  remain only where no rule applies.
- *The resolved line never shows another party's totals*: "…" until the chosen party's answer
  comes, "—" when that call fails. Changing the party no longer dims the room price matrix, and
  leaving Pricing stops asking for the party.
- *Sample parties stay within what the server accepts* (12 adults, 8 children); large rooms keep
  the common parties.
- *Wording:* "included in the room price" and "from Hotel policy" in the cells, and "(no
  single-use rule)" under the single-use default. The special-combination note no longer appears
  on an infant priced by its band's rule.
- *Tests:* `npm run test:unit` 235 (fail-first recorded) and `test:dom` 29;
  `test_pricing_workspace_api` 50, `test_age_bands` 11 and `test_pricing_policies` 14; a browser
  check 3/3 (each check fails on the S11 sources) with the S11 checks 4/4; and `contract-admin`,
  `critical-journey` and `editor-edits` unchanged.

Frontend only. R-04 stays PARTIAL.

**Pricing Workspace, slice S12 (2026-09-25, ADR-061, branch `pricing-workspace`).** Special
combinations are built on Pricing, under the occupancy ladder, without typing "2+2".
- *Cards:* each special combination reads "2 Adults + 2 Children → Child 1 ×0.50 · Child 2 ×0.25",
  over its age bands by label, rooms and periods. A card for some periods only is marked "◆ by
  period". Edit opens the builder in place of the card, and Remove can be undone. A card the
  builder cannot show (e.g. one with a note) links to the rule tables. The single-use rule stays
  the ladder's first row. The ladder's ⓘ note now links to the cards that outrank a cell.
- *Builder:* an inline panel, not a dialog. It has:
  - Adults and Children, and quick chips of the combinations the rooms can host. A chip no room in
    scope can host is greyed, and its tooltip names the rooms that can;
  - Rooms and Periods (all, or chosen);
  - one line per child ("Child 1 (oldest)", by the contract's child ordering), with an age band,
    a rule and a value in the ladder's shorthand; a child can have lines for several bands;
  - adult rules and a price for the whole party, and, under More, any children, any adults and
    Always wins;
  - a reading line, and Save combination.
  Save writes ordinary occupancy rules as one undo entry, replacing the edited card's rows. Twins
  of another card's rules are refused, as are other rules the server would refuse or ignore.

Verification: `npm run test:unit` 244 (fail-first recorded) and `test:dom` 29; build and i18n (77
keys); `test_pricing_workspace_api` 50. A browser check passed 5/5: the slice's three checks,
including `get_version` after Save showing CHILD 1 CHB "2+2" ×0.5 and CHILD 2 CHA ×0.25, and a
room with one child place greying 2A+2C. The S11 checks passed 4/4. `editor-edits`,
`contract-admin`, `critical-journey`, `entry-branding` and `policy-revisions` are unchanged (15
passed). Frontend only. R-04 stays PARTIAL.

**Pricing Workspace, S12 review follow-up (2026-09-25, ADR-061, branch `pricing-workspace`).**
- *A combination for All rooms and the same one for a room are two cards.* They used to merge into
  one card that read "All rooms". Editing it and saving it unchanged deleted the room's rows,
  which could change that room's price. All rooms / All periods and named rooms / periods are
  now always separate cards, and each one saved unchanged keeps exactly its rows.
- *The builder does not open a card it cannot save back as it is.* This covers a card that mixes
  All with named rooms or periods, and a negative value outside Plus/minus % (ADD -5 would come
  back as SUBTRACT 5). Such cards link to the rule tables.
- *Wording:* the value hint says that a signed number stays Plus/minus % under Plus/minus %. The
  twin refusal says "already has a rule for". A twin with an Inherit rule stays refused, for the
  reasons in ADR-061.
- *Tests:* `npm run test:unit` 249 (4 fail on the S12 head on assertions) and `test:dom` 29;
  `test_pricing_workspace_api` 50; a browser check 2/2 (the verifier's scenario fails on the S12
  sources), with the S12 checks 5/5.

Frontend only. R-04 stays PARTIAL.

**Pricing Workspace, slice S13 (2026-09-25, ADR-061, branch `pricing-workspace`).** Boards are
entered on Pricing, under Occupancy & child pricing.
- *Collapsed,* the section reads as chips: "UAI BASE · AI −5 % · HB −20.00 per adult".
- *Expanded,* it is a grid on the matrix's period columns. There is one row per board, and an
  indented row for a room with rules of its own ("HB · Garden Villa only"). A cell takes `20`
  (per room per night), `+20` / `-20` (per adult; children pay their share), `5%` / `-5%` (of the
  night's occupancy price) or `BASE` (the board the room price includes; one board). The reading
  line always names the unit, e.g. "Half board · All periods: −20.00 per adult per night;
  children 50 %, infants free".
- *Clearing:* a period or room cell removes that rule. Clearing a board's own All periods cell
  removes the board after an inline confirmation.
- *The row's terms popover* sets children's %, infants free, the label and the rooms, and adds a
  rule for one room.
- *Add board:* the first board added is the base board.
- The column of the matrix's active period is highlighted, and `#boards` opens the section. Every
  change is one undo entry.

Verification: `npm run test:unit` 257 (fail-first recorded) and `test:dom` 29; build and i18n (91
keys); `test_pricing_workspace_api` 50. A browser check passed 6/6, including the owner's example
typed as BASE, -5%, -20: after Save, `get_version` has UAI base, AI ADJUST_PERCENT −5 and HB ADD
−20, and the Price test with board HB shows "board HB supplement -40.00" per night for 2 adults.
The S11 and S12 checks pass. S10's pass with one scratch locator scoped to the matrix. The committed
`editor-edits`, `contract-admin`, `critical-journey`, `entry-branding` and `policy-revisions`
specs are unchanged (15 passed). Frontend only. R-04 stays PARTIAL.

**Pricing Workspace, slice S14 (2026-09-25, ADR-061, branch `pricing-workspace`).** The Price test
opens in a side drawer that is not modal, from the header (starting from the matrix cell that last
had the focus) or from a matrix cell's context menu "Test this price". It starts with that room,
3 nights from that period's start (within the stay window), the base board and 2 adults.
- *Children* can be given exactly, in months or by date of birth, besides whole years.
- *Live* re-prices each settled edit of the stay or of the draft, which is priced unsaved.
- *The Explain ladder* shows the final price, then the stages in the order the engine applies
  them (Base, Period without an amount, Room, Occupancy (adults), Children, Special combination,
  Board, Period adjustment, Rate plan, Night cost, Cost offers, Markup, Currency conversion,
  Promotion, then Tax and the final price for the stay), each with its server values before and
  after and its explanation lines. Identical nights form one block ("Nights 1–3 · P2"). Nothing is
  computed in the browser; a quote without the running subtotals leaves those stages blank.
- *"Why this price"* shows band labels instead of band codes in every language, says the
  sentences in the viewer's language where a template exists, and links each rule of the draft to
  its matrix cell, ladder cell, combination card or board cell ("Show in grid").

Verification: `npm run test:unit` 272 (15 new on four recorded quotes; fail-first recorded),
`test:dom` 30; build and i18n (83 keys); `test_pricing_workspace_api` 50. A browser check passed
5/5, including the owner's Deluxe example priced unsaved (Room 80.00 → 108.00, Occupancy 108.00 →
216.00, Children 216.00 → 270.00 with the child line 54.00, Board 270.00 → 270.00, Night cost
270.00, no `save_version`), a child of 143 months in Child 7–11.99 and one of 144 months priced
as an adult, Show in grid, Live and German. `contract-admin` now expects the band labels in the
price check's rule labels; with the other committed contract specs: 15 passed. The S10–S13 checks
pass; S9's "Shift+F10 opens the popover" step now meets the cell menu first (ADR-061, S14
deviation 2). Frontend only. R-04 stays PARTIAL.

**Pricing Workspace, slice S15 (2026-09-25, ADR-061, branch `pricing-workspace`).** Validation
issues are shown where they are.
- *In the grids:* an issue marks the matrix cell, period header, occupancy ladder cell (in its
  rooms scope), special combination card or board cell it is about, found from the rule it names
  (the unsaved row's key, or a saved row's name) or from its room, period, band, party or board. A
  marked cell has a glyph and an underline (an error in rose, a warning in amber), and the message in
  its tooltip and its screen-reader description; an error also makes the cell invalid. Issues about
  the header, the selling terms, rate plans or offers stay in the lists.
- *The live check* lists the issues by section. A click shows the issue: the section opens, the
  ladder switches to the right rooms scope, and the cell, card or header is focused. An issue
  without a cell opens the child ages drawer, Occupancy, Boards, the matrix, its rule table or
  Offers. A published version's stored report works the same way, with no check call.
- *Band labels:* every issue list (the cells, the live check, Preview & audit, the Advanced rule
  tables and the Publish dialog's check) shows band labels instead of band codes, including the
  publish sweep's "STD 2A+2C [Child 7–11.99]: …".
- *The i18n check* also fails when a `t("…")` key used in the code is missing from its area's
  English catalogue.

Verification: `npm run test:unit` 287 (15 new; fail-first recorded), `test:dom` 30; build and
i18n (7 keys; 5,038 literal keys found); `test_pricing_workspace_api` 50. A browser check passed
5/5 (each check fails on the S14 frontend): a saved duplicate P4 rule of a derived room marks its P4
cell and the chip's count (the Advanced room prices table keeps one rule per cell, so it cannot make
one), a duplicate board row made in the Advanced Boards table marks its board cell, and the list's
clicks focus them; an overlapping band reads labels, not codes, in the live check, the
Advanced table and Preview & audit; the sweep's parties mark the 2A+2C card and the Infant row in the
room's ladder scope; overlapping periods mark both headers; a published version anchors its stored
report. The S9–S14 checks and the committed contract specs (15 passed) are unchanged. Frontend only.

**Pricing Workspace, slice S16 (2026-09-25, ADR-061, branch `pricing-workspace`).** The committed
browser specs of the workspace, and the rebuilt bundles.
- *`pricing-workspace.spec.ts`:* the owner's 13-step contract on a contract made with the ROOM basis:
  PERSON chosen in the basis popover (the header saved at once, the draft still clean), three rooms,
  four periods, `70⇥80⇥100⇥130↵`, the formulas and the P3:P4 bulk entry with their resolved rows,
  the 3rd adult and its P4 override, the bands in the drawer with labels and no codes on the page,
  the band rules, the 2A+2C card from the builder, the base board BB, then the Price test from
  Deluxe's P2 cell (2 adults and a child of 8, 3 nights, no save) with its ladder compared with the
  served `preview_price` answer (GAP-12 subtotals), then Save and the stored strings. The measured
  budget is **41 clicks, 0 section switches, 0 modal dialogs** (limits 50 / 0 / 0; recorded in the
  test's annotations). Edge checks (`abc`, `1.500`, Escape, Ctrl+Z after the bulk entry, a TSV
  paste, `+10%` on the base room priced once by the server, `x1.20` over a fixed price) and a check
  that the budget counts clicks, a native select, section switches and a modal dialog.
- *`pricing-workspace-mobile.spec.ts`* (desktop and Pixel 7): a published version is read-only, fits
  375 px without sideways scroll and is never sent to `validate_version`; an agent sees the catalogue
  without amounts, page errors, cost calls or a 403.
- *The contract flows* (`e2e/flows/contracts.ts`) drive the workspace by default, with `{advanced:
  true}` for the Rule tables and the new `setBasis`; `contract-admin` and `critical-journey` run
  through them unchanged. `editor-edits` uses the Boards section and a period column, and
  `entry-branding` checks "Commercial rules" with its "Rate plans" table.
- *The S9–S15 dev-server checks* are committed as seven `pricing-workspace-*.spec.ts` files (matrix,
  bulk, occupancy, combinations, boards, price test, issues; 50 tests).

Verification: unit 491 OK, ruff clean; `npm run build`, `npm run i18n:tex`, `npm run test:unit` 287,
`npm run test:dom` 30; the ten integration modules of the slice (273 OK, migrated with the tree); the
upstream suites 76/76, 13/13 and banquet 101. The whole Playwright suite on the tree's own servers
(113 tests, desktop and Pixel 7): 105 passed and 1 skipped (two-factor, as before) against Vite, and
the 7 others (custom-host, pay-link, manage-money, written for the bench) passed against the bench
with an RQ worker (8 passed). Fail-first: against main's ten-tab editor the new specs and the two
changed editor tests fail (9 of 9); S15's scenario 5 fails on the S14 frontend. Tests, docs and
bundles only.

**Pricing Workspace, S16 review follow-up (2026-09-25, ADR-061, branch `pricing-workspace`).** The
review found 1 high, 7 medium and 15 low items. All are fixed except three low ones, which ADR-061
lists as open.
- *Server:*
  - `price_matrix` shows an inherited pricing-policy formula (op, value, and a sample party total
    priced with it) only to a viewer with `price.view_cost`, as the policies API does; an editor
    with `contract.edit` alone gets the rule's source and scope (`hidden`).
  - A blank night adjustment or rate plan value with an op set is refused on save and in the
    overlay (GAP-8; it was stored and priced as 0).
  - `build_terms` refuses another hotel's rate plan, cancellation policy or payment policy.
  - `validate_version`, and `price_matrix` with unsaved data or sample parties, are bounded per
    user: a budget a minute and at most 3 / 6 calls running at once (429).
- *Workspace:*
  - The three grids scroll sideways together.
  - The header has the Base room select and, for the ROOM basis, the included-adults stepper.
  - The dark theme uses only remapped shades (a unit test checks the contrast).
  - A selected cell has an outline, not only a tint, and a read-only range is shown.
  - Ctrl/Cmd+S in a cell editor saves the typed entry; the tab asks before closing with unsaved
    input.
  - Error drafts and an open combination builder survive a section switch.
  - The focus stays in the matrix after Remove room and Delete period.
  - The Price test panel follows its opener in the Tab order and is modal on phones.
  - Settings and selling terms are in the undo history.
  - Also: plural strings, room names in English Explain sentences, Duplicate's unnamed copy with
    Rename…, the dotted weekday border, aria-colcount, and no card around Pricing.

Verification: unit 491 OK, ruff clean; `tsc -b`, `npm run build`, `npm run i18n:tex` (5,060 literal
keys), `npm run test:unit` 296, `npm run test:dom` 31. All 38 integration modules migrated with the
tree: 838 OK (10 skipped, as before), `test_pricing_workspace_api` 55 of them. Upstream suites:
eval 76/76, journey 13/13, banquet 101 OK. Playwright on the tree's own servers (bench :8016, Vite
:5186): the nine workspace specs, `editor-edits`, `contract-admin` and `critical-journey` (desktop
and Pixel 7), 72 tests. 71 passed on the first run. The failing one was `-bulk` V1, which asserted
the old rule that a read-only cell in a range is not aria-selected; it was updated, and `-bulk`
passed again with 14 of 14. The new `pricing-workspace-review.spec.ts` passed 10 of 10. Fail-first:
see ADR-061 (the backend tests, the i18n check, the unit tests, and the review spec, 10 of 10 on the
S16 frontend).

**Pricing Workspace, S16 re-review follow-up (2026-09-25, ADR-061, branch `pricing-workspace`).** A
second review found 9 medium and 12 low items. All are fixed except one low item, the shared
inline-editing hook, which ADR-061 lists as open.
- *Server:*
  - A sample party that a hidden policy rule takes part in has no total and no error text for an
    editor without `price.view_cost`. This covers a whole-party rule and a party that cannot be
    priced (`matrix.party_rules`).
  - That editor's live check leaves out the issues that depend on a hidden rule's value.
  - The heavy-read budget is one atomic step, and a leaked slot ages out after 300 s.
  - `preview_price` with unsaved data is bounded per user.
- *Workspace:*
  - The Price test's explanation is complete after a second result.
  - The ladder popover adds child position rows and the "also when children travel" single use.
  - Add room and Add board are menus.
  - "Prices not updated" or "as saved" is shown instead of a spinner that never stops, and stale
    values are italic, not faded.
  - Ctrl/Cmd+S and closing the tab cover the child-age fields and new period dates.
  - Alt+Enter in the boards grid keeps the typed entry.
  - Each grid is one tab stop, with its header controls on the arrow keys.
  - Shift+click selects header ranges.
  - The Price test sits beside the matrix on a desktop.
  - Also: every run-time state key is in the six languages, board names are used, and weekday
    names are in the viewer's language.

Verification: unit 496 OK, ruff clean; `tsc -b`, `npm run build`, `npm run i18n:tex` (5,065
literal keys), `npm run test:unit` 303, `npm run test:dom` 32. All 38 integration modules migrated
with the tree: 844 OK (10 skipped, as before), `test_pricing_workspace_api` 61 of them.
`test_entry_branding` failed once because a commit moved HEAD during the run; it passed 34/34 when
re-run. Upstream suites: eval 76/76, journey 13/13, banquet 101 OK. Playwright on the tree's own servers (bench :8016, Vite
:5186): the eleven workspace specs, `editor-edits`, `contract-admin` and `critical-journey`
(desktop and Pixel 7), 83 tests. The final run passed all 83; the acceptance counted 41 clicks.
Fail-first: see ADR-061 (the backend tests, the unit tests, the DOM test, and the new
`pricing-workspace-rereview.spec.ts`, which fails 11 of 11 on the S16-review frontend).

**Pricing Workspace, S16 re-review 2 follow-up (2026-09-25, ADR-061, branch `pricing-workspace`).**
A third review found 1 high, 4 medium and 8 low items. All 13 are fixed.
- *Server:*
  - An editor without `price.view_cost` is again told when a child band has no rule, in the
    live check and in the sample-party cells, also when a policy rule priced the adults. Only
    what depends on a hidden rule's op or value stays hidden: a total or negative total it takes
    part in, and a missing child rule where it defers (`occupancy.depends_on`).
  - `get_version` gives that editor the report stored at publish filtered the same way
    (`contracts.stored_report`).
- *Workspace:*
  - "Also when children travel" switches the whole single-use row, every period keeping its
    value.
  - A draft with both single-use forms shows a row for each.
  - The header lane is in the keyboard shortcuts, the grid hints and each grid's description.
  - A cleared child-age name no longer leaves the tab asking before it closes.
  - Also: Add room focuses the new room; the Price test's status region is announced on the
    first result; the terms popover's Add a rule for one room carries its help; a read-only copy
    notice; board names in the history; three unused keys removed.

Verification: unit 504 OK, ruff clean; `tsc -b`, `npm run build`, `npm run i18n:tex` (5,072 literal
keys), `npm run test:unit` 306, `npm run test:dom` 32. All 38 integration modules migrated with the
tree: 846 OK (10 skipped, as before), `test_pricing_workspace_api` 63 of them. Upstream suites: eval
76/76, journey 13/13, banquet 101 OK. Playwright on the tree's own servers (bench :8016, Vite :5186):
the twelve `pricing-workspace*` specs 88/88, and `editor-edits`, `contract-admin` and
`critical-journey` 5/5. Fail-first: see ADR-061 (the backend tests, the unit tests, and the new
`pricing-workspace-rereview2.spec.ts`, which fails 10 of 10 on the re-review frontend). Untracked
test files of other work in the worktree are not counted (ADR-061).

**Pricing Workspace, S16 re-review 3 follow-up (2026-09-25, ADR-061, branch `pricing-workspace`).**
A fourth review found 4 medium and 14 low items. Sixteen are fixed. The other two are context: other
work's untracked parity files in the worktree, and a reviewer's scratch clean-up.
- *Server:*
  - An editor without `price.view_cost` no longer learns whether a hidden policy rule is INHERIT.
    OCC_INFANT_GENERIC names no hidden rule and is not said for an infant band a hidden rule names,
    live and in the stored report.
  - A hidden rule that defers where it would otherwise win a slot hides the party as one that
    prices it (`occupancy.depends_on`).
- *Workspace:*
  - The single-use row leaves a special combination's rules alone: a builder's "1 adult + any
    children" card keeps its Adult 1 through a form switch, and a write into its cell is refused.
  - The switch is offered only for the scope's own rules, and never carries a relative rule into
    the other form.
  - Keyboard undo or redo that removes the focused row puts the focus back on the grid.
  - A refused or partly typed new child-age band makes the tab ask before it closes.
  - Also: each grid's header-lane note says its own controls, and only where it has them; the
    single-use checkbox is described; a new period's dates hand the focus to its first cell; the
    i18n check reads conditional keys; toasts stay long enough to read; side panels sit beside the
    page only from 80rem, with a narrower row header; the Price test panel's nightly table fits it;
    the re-review 2 notes counted twelve spec files, not thirteen.

Verification: unit 506 OK, ruff clean; `tsc -b`, `npm run build`, `npm run i18n:tex` (5,100 keys),
`npm run test:unit` 310, `npm run test:dom` 32. All 38 integration modules migrated with the tree: 846
OK (10 skipped, as before). Upstream suites: eval 76/76, journey 13/13, banquet 101 OK. Playwright on
the tree's own servers (bench :8016, Vite :5186): the thirteen `pricing-workspace*` spec files 97/97,
and `editor-edits`, `contract-admin`, `critical-journey` and `policy-revisions` 6/6 (one bulk test
failed once under load in an earlier full run and passed on every rerun). Fail-first: see ADR-061 (2
Python tests, 3 frontend unit tests, and the new `pricing-workspace-rereview3.spec.ts`, which fails 9
of 9 on the re-review 2 frontend). Untracked test files of other work in the worktree are not counted.

**Pricing Workspace, existing semantics kept (2026-09-25, ADR-061, branch `pricing-workspace`).**
The owner's rule: the workspace changes the UX only; no existing pricing semantics change silently.
- *Existing callers get main's answers again.* Before, every internal quote (so every TEX Quote and
  reservation snapshot) had three more night keys; the live check and publish reported and refused
  board rows main published and gave each issue a `ref`; a save refused a blank value main stored
  as 0; the price test refused children main priced; a saved draft's check was rate limited; the
  matrix and the version had more keys. Now each of these is the workspace's opt-in (`workspace=1`,
  or `data` / `parties`, which only the workspace sends), and the workspace sends the flag
  (`WORKSPACE`; the version editor's publish dialog too, not the contract detail page's or the ARI
  grid's).
- *Kept for every caller (security and tenancy, reported):* a draft naming another hotel's rate
  plan, cancellation policy or payment policy is refused wherever its terms are built; an editor
  without `price.view_cost` is not told what a pricing policy's formula decides, live or in the
  report stored at publish. GO_LIVE owner input 14.
- *Tests:* unit `test_main_parity` (8: 2,906 quotes byte for byte, 25 payloads' issues, frozen
  hashes and units, 97 broken drafts' issues, recorded against main `6b0102c`; the opt-in switches),
  integration `test_existing_semantics` (13; against main's code 10 pass and the 3 security tests
  fail as designed), e2e `pricing-workspace-optin` (the flag on every call).

Verification: unit 516 OK, ruff clean; `tsc -b`, `npm run build` (bundles not committed), `npm run
i18n:tex`, `npm run test:unit` 311. Integration with the tree migrated: `test_existing_semantics` 13,
`test_pricing_workspace_api` 63, `test_commercial_flows` 63, `test_age_bands` 11, `test_money_fields`
9, `test_critical_journey` 31, `test_security_regressions` 59, `test_pricing_policies` 14, all OK; then
all 39 modules: 859 tests, 858 OK (10 skipped) and 1 error, `test_system_status`'s FX-age test run just
after the site's midnight (it fails the same way against main's code at that time; not this change).
Playwright on the tree's own servers (bench :8016, Vite :5186): the fourteen `pricing-workspace*`
spec files 98/98 (with the new `pricing-workspace-optin`) and `editor-edits`, `contract-admin`,
`critical-journey` and `policy-revisions` 6/6: 104 passed. Fail-first: `pricing-workspace-optin` fails
on the frontend before it sent the flag (`2a13fd3`, Vite :5187): without `workspace=1`, `get_version`
answers no `can_preview`, so the Price test is not offered.

**Pricing Workspace, draft overlay performance (2026-09-25, ADR-061, branch `pricing-workspace`).**
The new regression module `test_pricing_workspace_perf` (2 tests) measures the overlay's calls on a
draft of 15 rooms × 26 periods (1,320 rows, 902 occupancy rules, 11 special combinations, 6 boards):
20 runs each from a fresh request, p50 / p95 / max, response size and `frappe.db.sql` count, against
the saved draft by name. Within budget on the development bench: whole-matrix overlay p95 253 ms
(285 ms with the ladder's sample party; budget 800 ms), draft quote p95 264 ms for 3 nights and
247 ms for 14 nights 2A+2C (budget 500 ms). Validation takes 2.7 s (not budgeted); `apply_op_values`
takes 10 ms at 500 prices. Query counts do not grow with cells, and the module asserts it: the same
for 13 and 26 periods, exactly one per room, the same for 3 and 14 nights. The overlay adds about
160 ms and 12 queries (the draft is loaded twice). The table and the profile are in ADR-061. No app
code changed.

**Pricing Workspace, final verification (2026-09-25, ADR-061, branch `pricing-workspace` at `ebf6631`).**
Main (`claude/inspiring-ptolemy-i6wdu2`, `1575c8b`) has no commit the branch lacks, so nothing was
merged. Every run used this tree; the shared site was migrated with it before each run against it
(migrate rc 0 each time).

| Suite | How | Result |
|---|---|---|
| Unit | `python -m unittest discover -s kamra/tex/tests/unit -t .` | 516 OK |
| Lint | `ruff check kamra/tex kamra/patches/tex` | clean |
| Frontend unit | `npm run test:unit` (`node --test`) | 311/311 |
| Frontend DOM harness | `npm run test:dom` (Playwright, no bench) | 32/32 |
| Types, build, i18n | `npx tsc -b`, `npm run build`, `npm run i18n:tex` | clean; built (bundles not committed); 5,100 keys, the six languages complete |
| Integration, all 40 modules | `migrate_test.sh` with no module | 861 tests: 860 OK (10 skipped, the whole-site and second-connection tests) and **1 error**, `test_system_status` (failure 1) |
| Whole-site tests | `disposable_test.sh` (a site made, tested, dropped) | `test_patches` 33/33, none skipped; `test_crm_third_review`'s 7 second-connection tests OK. Its other 14 tests (they pass on the shared site) error on the new site for want of the shared site's config (`developer_mode`: an `http://` return URL is refused; `encryption_key`: `SigningKeyMissing`); with both set, 20 of 21 pass and `test_new_events_never_wait_for_a_purge` waits out its lock (1205) on the near-empty site |
| Upstream | `run_baseline.sh` with the tree | eval harness 76/76, front-desk journey 13/13, banquet 101 OK |
| Browser E2E, whole suite, run 1 | Playwright on the tree's own servers: bench :8016 with the tree (its `kamra/public` served at `/assets/kamra`), an RQ worker, Vite :5186; one test user with a second factor and a `tex_source_url`, so no test is skipped | through Vite, every spec but custom-host and pay-link, desktop and mobile: 148 passed, **1 failed** (failure 2); against :8016, custom-host, pay-link and manage-money: 8/8 |
| Acceptance, `pricing-workspace.spec.ts` | twice in a row after run 1 | 3/3 and 3/3 |
| Browser E2E, whole suite, run 2 | the same servers and settings, again | 139 passed, **4 failed** (failures 2, 3, 4), 6 not run (the rest of the matrix spec's serial group) |
| Reruns | the same servers and settings | `entry-branding` ×3: 8 passed, 2 failed each (failure 2); `pricing-workspace-matrix` ×3: 1 failed (failure 3), then 8/8 twice; `pricing-workspace-rereview` ×3: 11/11 each; every `pricing-workspace*` spec together: 98/98 |

*Acceptance counts, measured in the browser:* **41 clicks, 0 section switches, 0 modal dialogs** in
each of its five runs (limits 50 / 0 / 0) for the owner's 13 steps in one draft, with no save before
the price test.

*Failures:*
1. `test_system_status.test_an_old_fx_rate_warns_and_a_stale_one_fails` errors (not the workspace).
   The FX check warns when the latest rate is more than two business days old
   (`FX_WARN_BUSINESS_DAYS`, `ops/checks.py business_days`). The test writes a rate three calendar
   days old and expects that warning, which exists only when those three days hold three weekdays:
   a site date of Wednesday, Thursday or Friday. This run was on Saturday 26 September by the site's
   clock (Europe/Istanbul), so no issue came back (`TypeError: 'NoneType' object is not
   subscriptable`). Main's code (`1575c8b`, same schema, same hold of the lock) errors identically.
   Correction to the existing-semantics entry above: it depends on the site's weekday (it errors
   Saturday to Tuesday), not on the time of day; that run fell just after midnight into Saturday.
2. E2E `entry-branding.spec.ts`, "navigation: every new sub-section opens its screen …" and, from
   run 2 on, "navigation: a restricted user sees only what their capabilities open …" (not the
   workspace). Run 1: the first test clicked a Rate plans row while the table still showed its
   loading placeholders (`DataTable` renders five skeleton rows without a click handler; in the
   trace the click came about 70 ms before `lists.version_rows` answered), so the page stayed on the
   list. From run 2 on: `lists.version_rows` answers no row and `truncated: true` for every user,
   because Aurora Beach Resort now has 2,114 versions in Draft or Published (1,739 and 375), over
   the list's 2,000-version cap; the 2,000 most recently modified are E2E contracts' drafts
   (browser runs archive their contracts, but the versions stay Draft) with no rate plan row, so
   the demo contracts' rows fall outside the cut. `lists.py` is main's, unchanged by the branch; on
   this shared site every tree fails these two tests now.
3. E2E `pricing-workspace-matrix.spec.ts`, "Escape reverts; 'abc' and '1.500' are refused …" failed
   in 2 of its 6 runs (the workspace). The test types `1.500` at once after Escape closes the
   invalid `abc` editor. Once the editor held `.500` (the first key lost), once nothing (no editor
   opened). Likely cause, from the code: `finish` closes the editor and returns the focus to the cell
   only on the next animation frame (`focusAt`, `requestAnimationFrame`), so keys that arrive in
   between reach `body`. Not fixed here.
4. E2E `pricing-workspace-rereview.spec.ts`, "one tab stop per grid: … the headers' menus are on the
   arrow keys" failed once in 6 runs (the workspace): ArrowDown on the first room's header menu did
   not move the focus to the next room's menu. Passed in the other five runs; cause not found.

Recorded as **PARTIAL** below: the lane's rule allows COMPLETE only when every suite is green.

**Pricing Workspace, S16 re-review 4 follow-up, security and cost group (2026-09-26, ADR-061, branch `pricing-workspace`).**
Two findings of the fifth review. The fixes:
- An editor without `price.view_cost` learns nothing of a hidden pricing-policy rule's op, not even
  whether it defers (INHERIT). `occupancy.depends_on` now decides from which rules exist, their
  ranks and the viewer's own rules' ops only. The same holds in the matrix's sample parties, the live
  check (a tie is named at a slot no hidden rule may decide, else without its slot; a tie with a
  hidden rule and a hidden rule's missing value are left out) and the report stored at publish
  (its sweep is given exactly as the live check's).
- `publish_version` answers its caller the warnings `get_version` gives that caller, not the whole
  stored report.

Tests with fail-first output are in ADR-061:
- unit `test_hidden_policy_ops`: the two reproductions, each with INHERIT and a pricing op, four
  more cases, and 160 generated rule sets under every combination of hidden ops;
- integration: a publisher with `contract.publish` without `price.view_cost`.

Verification:
- Unit 523 OK, ruff clean.
- Integration, all 40 modules: 862 tests, 861 OK (10 skipped) and 1 error. The error is
  `test_system_status`'s weekday-dependent FX test; the site date was a Saturday.
- Upstream: 76/76, 13/13, banquet 101.

Open: a refused publish still names every ERROR to a publisher without cost (ADR-061).

Status unchanged (PARTIAL): the final verification's open failures are not this group's.

**Pricing Workspace, S16 re-review 5 follow-up, security and cost group (2026-09-26, ADR-061, branch `pricing-workspace`).**
One medium and three low findings of the sixth review. The fixes:
- A refused publish names, to a publisher without `price.view_cost`, only the errors that
  publisher's own live check shows (`validate.refusal_errors`). Those are the same whatever a
  hidden policy rule's op. If there are none, the refusal names nothing. Who sees cost is told the
  full check's errors, as before.
- Publish answers the warnings `get_version` gives the caller, to the letter: None to a caller with
  neither `price.view_cost` nor `contract.edit`.
- For a viewer without cost, the stored report is worked out once per report and process. Running
  a stored sweep at its limit again is bounded, as `validate_version` is.
- The publish audit counts the warnings that a viewer without cost is shown. The audit trail is read
  with `reservation.view`, and the full count said how many warnings a policy's formulas decide.

Tests with fail-first output are in ADR-061:
- integration: the reproduction (INHERIT and MULTIPLY 0, same message), the no-error message, the
  bounded and cached report, a publish-only profile, and the audit count under two policy values;
- unit `TestRefusals`: the reproduction and 160 generated rule sets, each refused under every op.

Verification:
- Unit 525 OK, ruff clean.
- Integration, all 40 modules: 866 tests, 865 OK (10 skipped) and 1 error. The error is
  `test_system_status`'s weekday-dependent FX test; the site date was a Saturday.
- Upstream: 76/76, 13/13, banquet 101.
- Details in ADR-061.

Open:
- `admin.audit_log` by reference needs only `reservation.view`. A republish's or a draft save's
  audit entry shows changed contract rates old → new to a Reservations Agent. This is pre-existing
  (ADR-053).
- Refused publishes are neither audited nor limited.

Status unchanged (PARTIAL).

**Pricing Workspace, final follow-up, workspace UX and keyboard group (2026-09-26, ADR-061, branch `pricing-workspace`).**
The workspace findings left after the final verification and the sixth review, and its two
intermittent failures. Frontend only (and one pure unit test). The fixes:
- The single-use switch ("Also when children travel") never changes what one adult pays. It is
  refused (`outranked`, said in the popover in six languages) where, in the other form, another
  rule would decide 1A+0C: an Always-wins Adult 1, a special combination's rule, a pricing policy's
  rule, an All-rooms whole 1+0 under a room's switch. Paired with the engine: the rows of 20
  scenarios are priced by `price_occupancy` in `test_single_use_switch` (allowed: the same price;
  refused: the unchecked switch would have changed it, e.g. 56.00 → 70.00 in the review's case).
- "+ Period" is a Tab stop while the matrix has no period column, and ArrowUp from All periods
  reaches it: a draft with rooms and no period gets P1 by keyboard.
- The single-use row names a special combination that prices one adult (the precedence note;
  "special combination" instead of the engine default where the card holds the column).
- The Keyboard shortcuts table wraps its keys (no overflow in any of the six languages).
- A side panel starts under the shell's top bar, which keeps its width at 1280 and 1440 px.
- A new period's dates hand the focus to its first cell only when a key closed them.
- German says "Periode" throughout the workspace ("+ Periode", "Alle Perioden").
- `pricing-workspace-matrix:107`: a closing cell editor focused its cell a frame later, so keys
  typed at once after Escape reached the page; the three grids now focus at once.
- `pricing-workspace-rereview:208`: Home's late frame took the focus back from the room's menu
  that ArrowLeft had focused (the trace and screenshot show it); the grid now focuses the cell a key
  moves to at once, and a late frame never takes the focus from a header control.

Tests with fail-first output are in ADR-061: DOM harness `lanes.spec.ts` (10), node
`workspace-occupancy` (3 new, 2 changed) and `single-use-switch` (2), Python
`test_single_use_switch` (4), Playwright `pricing-workspace-final.spec.ts` (9; all 9 fail on the
frontend before the follow-up), two committed expectations corrected (German "+ Periode",
rereview3's single-use cell under a card).

Verification (details in ADR-061):
- `pricing-workspace-matrix` 10 of 10 runs green and `pricing-workspace-rereview` 10 of 10.
- Every `pricing-workspace*` spec: 107/107 (acceptance 41 clicks, 0 section switches, 0 modal
  dialogs).
- Unit 529 OK, ruff clean, `npm run test:unit` 316/316, `npm run test:dom` 42/42, `tsc -b`,
  `npm run build` (bundles not committed) and `npm run i18n:tex` clean.
- Integration, all 40 modules: 866 tests, 865 OK (10 skipped) and 1 error, the weekday-dependent
  FX test (a Saturday site date). Upstream: 76/76, 13/13, banquet 101.

Status unchanged (PARTIAL): the workspace's own suites are green now, but not every suite is (the
FX test's weekday and the `entry-branding` tests on the shared site's data are not this group's).

**Pricing Workspace, final follow-up, main-side group (2026-09-26, ADR-061, branch `pricing-workspace`).**
The final verification's failures outside the workspace, which blocked "every suite green" on this
branch as on main. The fixes:
- `test_system_status`'s FX test no longer depends on the weekday: it pins the site's "now" to each
  day of a week, Monday to Sunday, and checks there what the check says (no rate, stale, old after
  more than two business days with the calendar age, quiet at two, today). The product was right;
  the test's rate three calendar days old warns only from Wednesday to Friday.
- `lists.version_rows`: "current" leaves out archived contracts' versions (they sell nothing and are
  drafted no more), and the 2,000-version cap counts only versions with a row in the table, the
  most recent first; `truncated` stays honest. On the shared site, 1,979 of the cap's 2,000 were
  archived E2E contracts' versions, so the Price periods / Occupancy rules / Rate plans lists came
  back cut (Rate plans empty) for everyone. The lists' hint says archived contracts are under All
  versions (six languages).
- `entry-branding.spec.ts` "navigation: every new sub-section …" counts and opens the rows of the
  lists' answers, not the loading placeholders (no product change).
- The funnel purge deletes each old event alone by its primary key: one `DELETE … WHERE name IN`
  for a batch that is most of a small funnel was read as a scan and locked every row and gap, so
  `test_new_events_never_wait_for_a_purge` timed out on the near-empty disposable site.
- `disposable_test.sh` (scratch, outside the repo) sets `developer_mode` and an `encryption_key` on
  the new site, as the shared site has them.

Tests with fail-first output are in ADR-061: the FX test rewritten over 7 pinned days and a unit
twin (the old test errors on a Saturday site date; its 3-day rate reads `ok` from Saturday to
Tuesday), `test_archived_contracts_never_crowd_the_current_versions_out` (2,020 archived drafts;
fail first: the live version and a draft missing from all three tables),
`test_each_old_event_is_deleted_alone_by_its_primary_key` (fail first: `1 != 3 : one DELETE per
event`), and a scratch Playwright proof with the lists' answers held back 2.5 s (the old step
clicks a placeholder row and fails; the new one passes).

Verification (on `59ef45a`, the code of this group; docs after it):
- Unit 530 OK, ruff clean, `npm run test:unit` 316/316, `npm run test:dom` 42/42, `tsc -b`,
  `npm run build` (bundles not committed) and `npm run i18n:tex` clean.
- Integration, all 40 modules (migrated with the tree): **868 tests, all OK** (11 skipped: the 3
  whole-site patch tests, the 7 second-connection tests, and `test_entry_branding`'s git-checkout
  test, which skips on the archived copy the run used; from the worktree that module is 35/35, none
  skipped). `test_system_status` 12, `test_entry_branding` 35, `test_crm_third_review` 22 OK.
- Disposable site (`disposable_test.sh`, made, tested, dropped): `test_crm_third_review` **22/22**,
  none skipped (with the old purge: 21 of 22, `test_new_events_never_wait_for_a_purge` 1205);
  `test_patches` 33/33; `test_crm_privacy_review` 28/28.
- Upstream with the tree: eval harness 76/76, front-desk journey 13/13, banquet 101 OK.
- Playwright on this group's servers (bench :8021 with the tree, `serve_tree.py`, an RQ worker,
  Vite :5191; a second factor for one test user and a `tex_source_url`, so nothing is skipped):
  `entry-branding.spec.ts` 5 runs in a row, **10/10 each** (238 and 357 included).

Status unchanged (PARTIAL): the four failures outside the workspace are fixed, and every suite
this group ran is green, but a whole run of every suite (the whole Playwright suite included) on
one commit is still to be recorded.

**Pricing Workspace status (R-04): PARTIAL (built: S1–S16, the S16 review, three re-review follow-ups, the existing-semantics follow-up and the final follow-ups, branch `pricing-workspace`; the final verification above is not green in every suite: its two intermittent failures in the workspace's own specs are fixed by the final follow-up's workspace group (each spec 10 of 10 runs green), the ones outside it by the main-side group (`test_system_status`'s FX test pinned to every weekday; the version tables without archived contracts and `entry-branding` waiting for the lists' answers; the purge's lock on a small funnel); a whole green run of every suite on one commit is still to be recorded).** Backend S2–S5 (opt-in: `workspace=1`; existing callers get main's answers)
(the draft overlay for `price_matrix`, `validate_version` and `preview_price`, cell sources, issue
refs, exact child ages, `apply_op_values` and **GAP-12**: each night of the price test's internal quote
reports its running subtotals after the adults, the children and the board, reported only, which the Explain
ladder shows and the acceptance spec compares with the served answer); the workspace S1, S6–S15; the
committed specs and bundles S16. The acceptance budget measured in the browser: **41 clicks, 0
section switches, 0 modal dialogs** for the 13 steps (limit 50 / 0 / 0; §1.3 designed ≈41 / 0 / 0,
against ≈112 clicks, 7 switches and 10 dialogs in the ten-tab editor); measured again in the final
verification: 41 / 0 / 0 in five runs. Owner sign-off (GO_LIVE owner input 13, ADR-061 §0.1): O1–O5
are implemented as proposed and stay provisional until the owner confirms each or chooses its
alternative.

*O1–O5 as implemented: PROVISIONAL owner decisions* (GO_LIVE owner input 13; `PRICING_WORKSPACE_UX.md`
§0.1). Each is a mapping from typed text onto an op the DocTypes and the engine already had, in
`shorthand.ts` and `model.ts`; `boards.py`, `ops.py`, `rooms.py` and the DocTypes are unchanged from
main, and a probe prices the same board rows identically on the branch and on main `6b0102c`.
- **O1 (provisional).** A bare `100` (or `=100`) in a board cell is stored as one board rule
  `{op: ABSOLUTE, adult_amount: "100"}` for the cell's board, room and period. Before commit the
  reading line says "Half board · All periods: 100.00 per room per night (fixed)"; the cell then
  shows "100.00" over "per room". It is priced once per room and night whatever the party (1A, 2A,
  3A and 2A+1C: 100 a night). Risk: the DocType's default board op is ADD (per adult), so the
  reading line and the "per room" unit are the only guard against a per-adult reading. Alternative:
  a bare number is ADD and `=100` is ABSOLUTE.
- **O2 (provisional).** `-20` (or `−20`) in a board cell is stored as `{op: ADD, adult_amount: "-20"}`
  (SUBTRACT is not a board op). It reads "−20.00 per adult per night; children 50 %, infants free"
  and is priced −20 per adult plus each paying child's share (2A: −40; 2A+1C at 50 %: −50).
- **O3 (provisional).** `50%` in a board cell is stored as `{op: ADJUST_PERCENT, adult_amount: "50"}`
  (PERCENT_OF is not a board op; the engine prices both alike). It reads "+50% of the night's
  occupancy price", is shown back as `+50%`, and adds half the night's occupancy total. In the room
  matrix `50%` stays PERCENT_OF (half of the base room's price). Alternative: refuse `50%` on boards
  and require `+50%`.
- **O4 (provisional).** A relative entry (`x1.1`, `+10%`, `+5`, `-5`, `50%`) in a base-room cell
  whose price is an entered price is sent to `apply_op_values` (read-only, `contract.edit`, drafts
  only, at most 500 values), which applies it once as the ARI grid's rate change does (HALF_UP to the
  currency); the answer is stored as an ABSOLUTE period rate (70.00 `+10%` → 77.00). The reading line
  says "adjust 70.00 by +10% (calculated on commit)" first. Refused: no entered price, a formula on
  the base cell, a negative result, a cell edited while the call was out. On the other rooms a
  relative entry is a formula from the base (D11). Alternative: refuse relative entries on the base
  room.
- **O5 (provisional).** In a 0- or 2-decimal currency an amount with 1–3 integer digits and exactly
  three decimals (`1.500`, `12.345`, `=1.500`, `-1.500`) is refused ("Is this 1500 or 1.5? Type 1500
  for one thousand five hundred, or 1.5 for one and a half."), in cells, popovers, paste and bulk
  Adjust…; nothing is stored. Accepted: `0.500`, `1.5`, `1500`, `1000.500`, factors, percentages, and
  every amount in KWD, BHD, OMR, JOD and TND. The guard is the workspace's only: the server still
  stores `1.500` from any other caller as before. Alternative: drop the guard and rely on the
  reading line.

*Draft overlay performance* (`test_pricing_workspace_perf`, a draft of 15 rooms × 26 periods,
1,320 rows, 390 cells; 20 timed runs from a fresh request; server time without HTTP; the recorded
run of ADR-061, and the p95 of this final run):

| Call (`workspace=1`) | Overlay p50 / p95 / max, ms | Saved draft p50 / p95 / max, ms | Final run p95 overlay / saved, ms | Queries overlay / saved | Budget (p95) |
|---|---|---|---|---|---|
| `price_matrix`, whole matrix | 241.6 / 252.6 / 256.6 | 80.7 / 87.3 / 90.2 | 287.4 / 95.5 | 58 / 46 | 800 ms: met |
| … + 1 sample party (the ladder) | 247.6 / 284.9 / 287.2 | 89.3 / 97.6 / 98.1 | 283.3 / 111.8 | 58 / 46 | 800 ms: met |
| … + 12 sample parties (the cap) | 311.0 / 378.0 / 402.3 | 156.8 / 207.0 / 208.0 | 339.7 / 182.5 | 58 / 46 | — |
| `preview_price`, 3 nights, 2A | 224.5 / 263.6 / 281.8 | 65.3 / 78.7 / 81.2 | 239.1 / 84.7 | 63 / 51 | 500 ms: met |
| `preview_price`, 14 nights, 2A+2C | 231.1 / 247.2 / 280.6 | 75.1 / 98.6 / 108.3 | 261.0 / 102.0 | 63 / 51 | 500 ms: met |
| `validate_version` (the publish sweep, 11,076 parties) | 2,664 / 2,808 / 2,984 | 2,536 / 2,652 / 2,658 | 2,871 / 2,658 | 48 / 48 | not budgeted |
| `apply_op_values`, 26 / 500 prices | 5.3 / 6.0 / 6.4 and 9.3 / 9.8 / 10.0 | — | 5.4 and 10.7 | 7 and 7 | — |

Query counts do not grow with cells (asserted: the same for 13 and 26 periods, one per room, the
same for 3 and 14 nights, the same for 26 and 500 prices).

Open after the review follow-up (ADR-061): the §3.18 one-screen fit of the owner example with the
ladder is not met (the rows are taller than 28 px), and the three grids' inline editing is not
one shared hook yet (only the key routing is shared).
Open after the final verification: a green whole run (the FX test on a site date Wednesday to
Friday or fixed; the version lists on a site without the accumulated E2E drafts, or a list that
leaves archived contracts out). The two intermittent workspace failures it found (keys typed at
once after Escape lost; one header-lane ArrowDown step) are fixed (final follow-up, workspace UX
and keyboard group).

R-04 itself stays PARTIAL: its classification is not otherwise changed by this lane (see its row).

## 2. Summary

| Status | Count | Requirements |
|---|---|---|
| COMPLETE | 27 | R-01, R-02, R-03, R-05, R-06, R-07, R-08, R-10, R-13, R-15, R-16, R-21, R-22, R-26, R-32, R-33, R-38, R-42, R-45, R-46, R-48, R-54, R-56, R-57, R-58, R-60 (process), R-61 (process) |
| PARTIAL | 35 | all others; the gaps are listed per row (R-29 back to PARTIAL: the ADR-057 review follow-up records its limits; R-14 stays PARTIAL for G-99) |
| NOT STARTED | 0 whole requirements | sub-items not started: CRM Campaigns (R-35/R-37), SMS / WhatsApp adapters (R-44), bundled extras (R-19), package coupons (R-20) |
| BLOCKED | 0 whole requirements | blocked sub-items: production certification of iyzico / Sipay / NestPay (R-40, merchant credentials); channel-manager provider certification (R-44, provider credentials); outgoing e-mail delivery (SMTP account) |

**Open gaps by severity:** 0 Critical, 0 High, 15 Medium, 4 Low (+3 blocked items), counted from the FINAL_GAP_AUDIT tables on 2026-10-03 after audit Part 2 (G-55, G-62 and G-97 resolved; G-99 found; git keeps the earlier recounts). All nine Critical
gaps (G-01…G-09) were fixed after the audit; G-84 (Medium) was found while fixing G-06 (FINAL_GAP_AUDIT, "Resolved since the audit"). Details are in
FINAL_GAP_AUDIT. Critical means wrong money or a security hole.

## 3. Phases (derived from the requirement rows below)

| Phase | Status | Why |
|---|---|---|
| 0 Audit + docs | COMPLETE | spec, architecture, ADR-001…033, this audit |
| 1 Foundation (shell, nav, design system, hide PMS) | PARTIAL | TEX shell and design system work; the legacy booking engine no longer sells TEX hotels (G-03 fixed), nor does a Desk/REST reservation (G-92 fixed, ADR-052); the legacy night audit leaves TEX-sold stays alone (G-04 fixed); the legacy PMS is closed in backend and SPA while switched off (G-16 fixed, ADR-030); entry screens say TEX Engine, offer the source and `/` leads to the admin app or sign-in (G-60 fixed); the navigation carries R-35's sub-sections (G-64 fixed, ADR-060). Open: design-system components and contrast (G-63), CRM Campaigns not started |
| 2 Commercial data model | PARTIAL | 62 DocTypes + patches p01–p76 (68 patches; p26, p30, p32, p41–p44 and p67 never used), each tested, and the upgrade of a Kamra database tested end to end (G-76 fixed, ADR-058); extras and taxes are effective-dated revisions (G-20 fixed, ADR-031); commercial decimal fields keep 9 places and hold what was typed, money Currency, percentages Percent (G-72 fixed, ADR-055) |
| 3 Pricing engine | PARTIAL | pure engine correct on every spec example; booking-level extras and fixed coupons priced once per booking, min basket in the sell currency (G-05, G-06, G-08 fixed); per-guest limits enforced at booking and modifications keep redemptions right (G-07, G-09 fixed); every FX rate recorded in the snapshot and reused by ORIGINAL_* reprices, band gaps refused in months, a child's date of birth (G-56, G-52 fixed, ADR-051); modifications and the historical simulator deterministic, sale times checked, proposals bound to their proposer (G-51 fixed, ADR-054); a minimum basket is the whole booking's (G-84 fixed, ADR-057) |
| 4 Contract admin | PARTIAL | editor, publish, price check work (E2E); the first contract that can sell a stay wins (G-17 fixed); contract cost hidden from agents (G-11 fixed) |
| 5 Rate/inventory grid | PARTIAL | grid + bulk edit; grid rate edits with the server's preview and a Sell price row (§6UX); copy period in the Pricing Workspace (`PeriodHeader.tsx`); tested by unit `test_ratesplit`, `test_inventory.TestGridRates`, `test_grid_rate_changes`, `test_grid_sell_prices`, e2e `rates-availability`. Open: rows are room types only (G-47) |
| 6 CRS | PARTIAL | works incl. multi-room; no destination/group inputs (G-40) |
| 7 Call Center | PARTIAL | keyboard-first flow tested; agents sell only on their entitled channels (G-41 fixed, ADR-050); allotments have no channel split within one contract |
| 8 Booking + widget | PARTIAL | full flow tested desktop+mobile; custom domains served (G-21 fixed, e2e `custom-host` ×3); widget smoke tests (e2e `widget`, G-44 partly fixed). Open: no inline widget mode (G-44) |
| 9 Payments | PARTIAL | sandbox end to end; link tokens never stored or leaked, allocations locked and idempotent (G-10, G-14 fixed); production certification BLOCKED |
| 10 CRM | PARTIAL | guests, consent, segments (G-23 fixed), loyalty administration (G-24 fixed), abandoned bookings. Open: CRM Campaigns not started; redemption only as money (G-66) |
| 11 Self-service | COMPLETE | view/pay/change/cancel; extras after booking (G-22 fixed); a change pays, then applies, refunds or keeps credit per the hotel's policy (G-45 fixed, ADR-044) |
| 12 Reports | PARTIAL | reports complete (R-48): every view and filter, contract vs selling reconciles in whole cents for every grouping (G-46 fixed, ADR-059, review follow-up); the dashboard (R-47) has no per-hotel time zones or reporting-currency conversion, and its funnel does not attribute group-site sessions; production by sale date moves a past period when a stay changes later |
| 13 Hardening | PARTIAL | this audit; every Critical and High gap fixed with regression tests (FINAL_GAP_AUDIT §1, §2); audit Part 2 in §6 … §6K6. Open: the Medium and Low gaps (§2) |

## 4. Requirements

| ID | Requirement | Status | Evidence (files · tests) | Gaps (→ FINAL_GAP_AUDIT) |
|---|---|---|---|---|
| R-01 | Source & identity | **COMPLETE** | AGPL notices, `NOTICE.md`, baseline 418ed1a in history; TEX shell branding; entry screens say TEX Engine: sign-in page in the six TEX languages with the brand from TEX Settings, tab title, favicons, Desk logo and apps tile, `hooks.py` title and description (app name, package, modules and routes unchanged, ADR-001); every entry screen offers the source, "Based on Kamra PMS · AGPL-3.0 · Source code" (G-60 fixed, ADR-060); review follow-up: guests (every booking-engine page, the widget's modal, the legacy guest pages) and Desk (Help › About) are offered it too, always the running version's source (`/tree/<commit>` or `tex_source_url` with `{commit}`, never with credentials), carried by the served pages; the sign-in page asks a two-factor account for its code and takes no other answer for a session; release pipelines guarded to the upstream repository (G-61 fixed) · `test_entry_branding` (G-60: 8; review follow-up: `TestSourceOffer`, `TestEntryOverHttp`, `TestSignInContract`), e2e `entry-branding.spec`, `shell.spec` | The legacy PMS is closed to hotel users while switched off (G-16 fixed, ADR-030); the legacy booking engine refuses TEX hotels and the legacy night audit leaves TEX stays alone (G-03, G-04 fixed, ADR-028); a Desk, REST or data-import reservation at a TEX hotel is refused, migration imports keep their amount as "Imported" (G-92 fixed, ADR-052); a hotel joining TEX is onboarding, and its Desk sells until an administrator sets it live in TEX (audited; TEX-mode banners in the TEX shell, the legacy shell and the Desk form; ADR-052 review). Kept on purpose (legacy PMS, hidden while off): the housekeeping app's login, AI assistant / MCP texts. Owner items (not spec bullets, GO_LIVE_READINESS §3, input 12): the repository public with every deployed commit pushed, or `tex_source_url` (and `tex_source_commit` for an install without its git checkout). |
| R-02 | Architecture principles | **COMPLETE** | `kamra/tex/pricing` has no frappe import (`TestPurity`); no import cycles; the frontend only formats decimal strings, and the TEX API returns decimal fields as exact strings, never floats; loyalty money is Decimal from a Currency field read exactly (G-72 fixed, ADR-055) · `TestPurity`, unit and integration `test_money_fields` | — (the legacy float pricing path remains only for hotels outside TEX, ADR-028: `Reservation.apply_pricing` never runs for a TEX hotel, G-92 fixed, ADR-052, `test_legacy_pricing`) |
| R-03 | Pricing engine | **COMPLETE** | modular resolvers in `kamra/tex/pricing/*`; Decimal (`money.calc`); explanation trace; extras and taxes as of the sale time, every EXTRA/TAX step names its revision (G-20 fixed, ADR-031); decimal DB fields of 9 places that hold what was typed (refused otherwise) and are read as the exact Decimal (`money.db_dec`), FX rates to 10 significant digits, rule values explained as stored (G-72 fixed, ADR-055) · `test_engine.py`, `TestPayload`, `TestEffectiveDatedSources`, `TestEffectiveDatedExtrasAndTaxes`, unit `test_money_fields` (11), integration `test_money_fields` (9) | — |
| R-04 | Contract management | PARTIAL | `api/contracts.py`, `commercial/contracts.py`, `tex_contract.py`, `screens/rates/contracts/*`; the version editor's Discard returns to the last save, and a save's answer keeps what was edited while it was in flight (ADR-060 follow-up, branch `fix-editor`; also the policy, booking-site, content and loyalty editors) · `TestContractSelection`, `TestContractHeaderLock`, e2e `contract-admin`, `editor-edits` (3; all fail on main `b72b2a8`); Pricing Workspace backend (every addition of S2–S5 below is the workspace's opt-in, `workspace=1`, since the existing-semantics follow-up: existing callers get main's answers, ADR-061), slice S2 (ADR-061, branch `pw-backend`): `price_matrix`, `validate_version` and `preview_price` price, validate and quote the editor's unsaved draft in memory (a read-only overlay: `contract.edit` and Draft only, the save's own checks except link validation and the window order, `~<_key>` rule ids, at most 5,000 rows, nothing saved or audited), a blank rule value is refused on save instead of being stored as 0, `get_version` says `can_preview` / `can_publish` / `can_edit_contract` / `basis_locked` and the currency's `minor_units`; slice S3: `price_matrix` names the rule behind each cell (scope, derivation chain, overridden rules; pure `pricing/matrix.py`), the effective room capacity, the age bands with their origin, the rules inherited from pricing policies and the engine's adult default, and prices sample parties per period (`parties`, `party_room`); slice S4: validation issues carry a `ref` to the rule(s), room, period, band(s), party and board they are about (messages unchanged), board rules for an unknown room or period and twin board rules are publish errors, the overlay refuses a row key used twice; slice S5: the price test takes a child's age in whole years, months or by date of birth (checked as a booking checks it) and refuses anything else, `apply_op_values` changes entered prices of a draft once by an op as the ARI grid does (read-only; the base room's relative entry, O4, and the bulk Adjust…), and each night of an internal quote reports its running subtotals after the adults, the children and the board (GAP-12, reported only: no price, explanation or engine version change; never in the guest view) ; frontend lane, merged with the backend lane on branch `pricing-workspace`: the currency-aware shorthand parser (S1), the design-system Popover, Menu, Tooltip and keyboard grid hooks (S7) and the pure workspace model that turns cell entries into ordinary rows (S6); slice S8: the version editor in four sections (Pricing, Commercial rules with the former editors as "Rule tables", Offers & promotions, Preview & audit) under a sticky context header with the pricing basis popover and the Price test, the server's live prices and checks of unsaved edits (one validation in flight; no cost call for agents), BOARD_* issues on Pricing; S8 review follow-up: a clean draft, the Check button and a draft above the overlay's row cap are priced and checked by name (no cap; `overlay_max_rows` and the typed `OverlayTooLarge` refusal, additive), and a refused check or matrix reads "could not run" with Try again; slice S9: the room price matrix on Pricing (inline shorthand cells with a reading line, the base room's relative entries adjusted once by the server and stored as prices (O4), formulas on the other rooms, Ctrl/Cmd+Enter over a selection, the rule popover, the room and period menus, the workspace undo history); S9 review follow-up: the night adjustment's amounts are currency-aware (O5), and a late server adjustment never overwrites a cell edited meanwhile; slice S10: the matrix's bulk tools (row and column header selection, Fill → / Fill ↓ with the fixed price confirmation, spreadsheet copy and paste, Adjust… with the server's preview, undo and redo with the "Applied to N cells · Undo" toast; the Rule tables' and Offers' edits are undo entries too); S10 review follow-up: Fill ↓ and copy take the rule a cell shows, a fill from an empty cell names what it cleared; S10 second review follow-up: a copied range over a resolved row pastes back onto the same rooms, copied text ends every row with a line break, Ctrl/Cmd+R and D never reach the browser from a cell editor, the undo toast returns the focus to the grid; slice S11: Occupancy & child pricing under the matrix (the ladder with engine defaults, band labels, period overrides, the rule popover and the server's resolved line for a sample party) and the non-modal child ages drawer (bands with saved labels, codes under Advanced, inherited bands, the child rules); S11 review follow-up: a room's ladder cells show the All-rooms and policy rules the engine uses instead of a false default or "not sellable", and the resolved line never shows another party's totals; slice S12: special combination cards under the ladder and the structured builder (steppers and quick chips of the rooms' valid combinations, rooms and periods, per-child band, rule and shorthand value, adult and whole-party rules, one undo entry replacing the edited card's rows; twins refused); S12 review follow-up: All-rooms / All-periods and named-scope rules are separate cards, so an unchanged Edit and Save keeps a room's rows, and the builder does not open a card it cannot save back as it is; slice S13: Boards on Pricing (chips when collapsed; a grid of the boards and their room rules on the matrix's period columns with board shorthand cells whose reading names the unit (O1–O3), BASE for one board, clearing a board's own cell removes it after a confirmation, the row's terms popover, Add board, the matrix's active period highlighted); slice S14: the Price test in a non-modal drawer (from the header or a matrix cell's "Test this price", prefilled from that cell; exact child ages in months or by date of birth; Live) with the Explain ladder (the engine's stages in its order, server values only, a chain check) and "Why this price" with band labels, localised sentences and Show in grid; slice S15: validation issues anchored in the workspace (the matrix cell, period header, ladder cell in its rooms scope, combination card or board cell an issue names; errors invalid, warnings described), the live check listed by section with each issue's click showing its cell, region or rule table, band labels in every issue list, and the i18n check's literal-key scan; slice S16: the committed acceptance (the owner's 13 steps in one draft, 41 clicks, 0 section switches, 0 modal dialogs, the Price test's ladder compared with the served answer), the read-only phone and agent checks, the contract E2E flows on the workspace and the S9–S15 checks as committed specs, the bundles rebuilt · `test_pricing_workspace_api` (50), `test_matrix` (22), `test_validate_refs` (37), `test_engine` `TestReportedSubtotals` (7), `npm run test:unit` (287), `npm run test:dom` (30), e2e `pricing-workspace` (3), `pricing-workspace-mobile` (2, desktop and Pixel 7), `pricing-workspace-matrix` (8), `-bulk` (14), `-occupancy` (4), `-combinations` (7), `-boards` (6), `-price-test` (6), `-issues` (5), `contract-admin` and `critical-journey` through the workspace, `editor-edits` (3) | The Pricing Workspace is built on branch `pricing-workspace` (ADR-061, slices S1–S16) and PARTIAL: its final verification was not green in every suite; the two intermittent failures in its own specs are fixed by the final follow-up's workspace group, and `test_system_status`'s weekday-dependent FX test and the two `entry-branding` navigation tests on the shared site's data by its main-side group; a whole green run of every suite on one commit is still to be recorded (its entries in §1); the owner's sign-off on the provisional shorthand decisions O1–O5 is owner input 13 (GO_LIVE_READINESS), and the committed bundles run on the dev bench only after the merge (ADR-061, open after S16). The e2e step for the header lock and status actions (G-50) passes in `contract-admin.spec.ts`. (Fixed: header lock G-50, ADR-045: a published contract's hotel, market, currency and basis are fixed, windows, channels, priority and sell currency are versioned, selection reads the frozen version, status moves through audited actions; review follow-up: versions frozen before G-50 keep their header narrowings (p25 snapshot and report), a suspend stops quotes and bookings in flight, the scheduler isolates each record, `TestContractHeaderLockReview`; contract selection G-17; cost visibility G-11.) |
| R-05 | Versioning & snapshot | **COMPLETE** | immutable versions, frozen payload + hash verified on load (`tex_contract_version.py`, `revisions.py`); the price-locked snapshot keeps its periods and rules as a verified reference (version + payload hash): every reprice, the simulator and add-ons refuse, audited, a payload that is not the one the sale recorded, and the locked price never moves; the snapshot records when it was priced (`priced_at`, the quote's sale time) and accepted (G-73 fixed, ADR-058) · `TestContractImmutability`, `test_payload_integrity_is_checked`, `test_snapshot_integrity` (9), e2e | — (The REST lock bypass G-01 is fixed, `TestPriceLock`. At a TEX hotel every stay, TEX-priced or not, changes its stay or price only through the TEX services, and imported stays are price-locked: G-92 fixed, ADR-052.) |
| R-06 | Base pricing modes | **COMPLETE** | `occupancy.py` PERSON/ROOM · `TestRoomBasis`, `TestPersonBasis`; basis select in `ContractDialogs.tsx` | — |
| R-07 | Occupancy formula engine | **COMPLETE** | slot model, combinations not hardcoded (`occupancy.py`, `contracts.parse_combination`); every live pricing policy (global, hotel, market, hotel + market) cascades into a contract at publish, rule origin ranked before qualifiers, an infant priced by its band rule first, ambiguous rules refused at publish where the tie decides a price, a pricing policy checked on its own before it goes live, legacy payloads priced as sold (occupancy precedence v2, ADR-043, G-30/G-31 fixed and reviewed); policy and contract occupancy editors (`screens/rates`; a policy rule can name the bands of the policies it cascades with) · spec examples reproduced (270; 2A+1C 250 vs 1A+1C 200), `TestPrecedenceV2`, `test_policy_cascade`, `test_pricing_policies` (14) | — |
| R-08 | Child age engine | **COMPLETE** | integer months, DOB-at-arrival (`ages.py`); bands judged on that month scale: every gap or overlap refused at publish and on a pricing-policy save, naming the months; a set starting above 0 months warns (G-52 fixed, ADR-051); bands per hotel, market and hotel + market (ADR-043: the version's, else the most specific policy's); a child's date of birth in the CRS / Call Center, modification drawer, booking engine and manage page, checked on the server (not in the future, under 18 on arrival) and priced in completed months · `test_boundaries_in_months`, `TestChildrenAtBoundaries` (35/36, 83/84, 143/144 months), unit `test_age_bands` (17), integration `test_age_bands` (6); review follow-up: a date of birth never reaches funnel analytics, a URL (searches are POST only), a staff note or an error message, a baby born after the pricing reference date is 0 months old (`TestDateOfBirthPrivacy`, `TestDateOfBirthAfterTheReference`) | — (no browser test of the date-of-birth pickers yet; type-checked) |
| R-09 | Rule hierarchy | PARTIAL | `Level` precedence; occupancy rules rank origin (version > hotel + market > market > hotel > global) then level (ADR-043, G-30 fixed); a policy's "specific override" ranks within its policy (publish warns where that changed a price, `OCC_POLICY_OVERRIDE_OUTRANKED`); one live pricing policy per scope, activations serialised; winning + overridden rules and the policy scope in the price check (`PreviewTab.tsx`) · markup/occupancy precedence tests, `test_policy_cascade`, `test_pricing_policies`, e2e asserts explanation | Markup explanation level ignores channel (`pricing/markup.py` `level()`, G-53). (Fixed: a same-scope markup tie is refused on activation, f063ae4, 2C-2, and on archive, LO-42b, 2K-6; `TestMarkupTies`.) |
| R-10 | Derived rooms | **COMPLETE** | `rooms.py` (derivation, cycle guard, absolute override) · `test_derived_rooms`, `test_base_change_propagates`, `test_absolute_override_wins_in_its_period`; `RatesTab.tsx` | — |
| R-11 | Stay periods | PARTIAL | unlimited periods, weekday/priority, grid bulk rate change into a draft | No bulk edit of occupancy/child/board across several periods; a period's prices, rules and boards are copied from one other period (§6UX) (G-47). (Fixed: copy period in the Pricing Workspace, `PeriodHeader.tsx`; `apply_rate_change` tested, `test_inventory.TestGridRates`, `test_grid_rate_changes`.) |
| R-12 | Sale vs stay date | PARTIAL | sale/stay windows, promotion booking-date/arrival/departure/LOS/through rules; extras and taxes effective-dated by sale time (G-20 fixed) · `test_sale_date_outside_eb_window`, `TestEligibility`, `TestEffectiveDatedExtrasAndTaxes` | Base rates/markups have no arrival/LOS/booking-date rules (G-54). |
| R-13 | Markets | COMPLETE | `resolve_market` never guesses; Settings → Markets; markets per booking site, residents-only markets checked at booking (O-8, ADR-070); a refused market link is shown and counted (G-55b) · `test_admin_markets`, market tests, `TestMarketIntegrity`, `TestMarketLinks` | — |
| R-14 | Contract vs selling price | PARTIAL | markup types/scopes/STACK; cost & margin stored; cost, rates and markups only with `price.view_cost` (G-11 fixed); the stored pricing internals (snapshot with explanation and FX record, cost, margin, FX rate, a quote's result, a revision's snapshots) never leave through Desk / REST: permlevel 1 for System Manager only, masked in the change history, left out of a generic write's response; the TEX API serves them by `price.view_cost` (G-95 fixed, ADR-056); margin reporting: per stay priced from a contract, contract cost + margin = the accommodation selling price it was marked up to (same currency, same tax basis), margin % over that price, extras and taxes on top reported beside it, per currency, only with `price.view_cost` at every hotel of the report (G-46 fixed, ADR-059); a cost-stage offer lowers the contract cost, so its outcome (applied or refused, its discount, a basket compared with the cost) reaches only staff with `price.view_cost`: every outcome carries its stage, the guest view and the staff view without cost drop cost-stage ones, and a reservation's Desk-visible `tex_promotions` lists only the promotions of the selling price (G-98 fixed, ADR-059 review follow-up) · `TestMarkup` (1000+8%=1080), `test_g11_agents_never_see_contract_cost`, `test_crm_privacy.TestPricingInternalsOutsideTex` (5), `test_reports.TestContractVsSelling` (3), unit `test_cost_stage_privacy` (6), integration `test_cost_stage_privacy` (4: booking engine, CRS and `ui_crs`, rooms quoted together, reservation, proposed change, simulator, manage page, e-mail, `tex_promotions`), e2e `reports.spec.ts` | `get_contract` returns each version's `payload_hash` to `price.view` callers (`api/contracts.py:105`): a sha256 of the frozen payload confirms guessed hidden rule values offline (G-99, Low). (Fixed: a contract version's rates are no longer readable in Desk by the Hotel Admin role, G-97, p66, 2I.) |
| R-15 | Currency engine | **COMPLETE** | FX modes, TCMB/ECB adapters, as-of rates; every conversion a quote makes (room rate and cost, extras, fixed promotions and their thresholds, coupons, fixed levies) is recorded in the price-locked snapshot (`fx_rates`: exact rate, provider rate and date, adjustment, policy, sale time) and explained; ORIGINAL_* reprices reuse the recorded rates (G-56 fixed, ADR-051); rates keep at least 10 significant digits (TRY → EUR 0.02941176471) and a rate recorded at 6 places reads back as recorded (G-72 fixed, ADR-055) · `TestFx` (50+2%→51), unit `test_fx_record` (11), integration `test_fx_snapshot` (5: EUR contract sold in TRY with EUR/USD extras and a fixed EUR promotion; a pre-G-56 snapshot pins its line rates too, review follow-up) | — |
| R-16 | Restrictions | **COMPLETE** | stop sell / open sale with check-in, check-out and stay-through modes, min/max LOS, CTA/CTD, release, min/max advance and the booking window (sale dates per night); scopes hotel, market, room, contract, rate plan, one sales channel or the Booking Engine / Call Center / both (G-48 fixed, ADR-057); calendar bulk editing in the Inventory grid with a hotel-level row; enforced on search, quote and booking (booking engine, CRS / Call Center) and on every change of a booked stay for what it newly takes (staff, guest self-service, paid or approved guest changes), overridable only with `restriction.edit`, a reason and an audit event; channel bookings accepted with a warning (ADR-039) and the booking window / advance days in the channels' ARI · unit `TestRestrictions`, `test_restriction_rules` (22), integration `test_restrictions` (33), e2e `restrictions-grid.spec.ts` (a change toward the length rule is not refused, an in-house guest never kept by a minimum stay: ADR-057 review L1) | — (grid rows are room types, not room × rate plan: R-36, G-47) |
| R-17 | Inventory | PARTIAL | pools, configured inventory, allotments with separate release and cutoff (a cutoff also gives the rooms back; Rates → Allotments; channels hear both at the site's midnight), explicit oversell limit, manual adjustment and closures (Inventory grid, audited), row locks; at a TEX hotel TEX inventory is the only capacity rule and every reservation write outside TEX (migration imports and status moves; a Desk/REST insert or change of nights is refused, G-92, ADR-052) takes the TEX lock and is checked against it; a change is checked only on the nights it newly takes; a reservation books only its own hotel's room types; hotels outside TEX keep the legacy check (G-49 fixed and reviewed, ADR-048); simultaneous bookings of different room types never deadlock, a deadlock victim is re-run or told to try again (G-85 fixed, ADR-032) · `test_inventory` (oversell, pools, configured, imports, held nights on staff and guest changes, allotment consumption, release, cutoff, room type ownership, deadlock handling, channel lock order), `test_concurrency` (last room, import vs TEX, room types side by side, retry), unit `TestInventoryMath` | Pools and configured inventory are set only in Desk (Room Type / Property), no TEX screen; inventory grid edits audit no old values (G-74); allotments have no channel dimension (G-41 remainder, deferred: ADR-050). |
| R-18 | Promotions | PARTIAL | all kinds/values/combination rules, reason per rejection · `test_promotions_extras.py` | No sale identifies a member, so a member discount cannot apply (G-57); a members-only promotion is refused on save (`tex_promotion.py:23-26`, 2C-2) and the MEMBER kind reads "Member (label only)" (LO-42a, 2K-6). (Fixed: value guards in engine and on save G-18, min-basket currency G-08; `test_value_guards`, `TestCommercialValues`.) |
| R-19 | Extras | PARTIAL | 12 pricing modes, service dates, mandatory; effective-dated revisions with Revise/Activate in Rates → Extras (G-20 fixed); limited daily capacity end to end, concurrency-safe, with Inventory → Extras, CRS and guest availability (G-19 fixed, ADR-033) · `TestExtras`, `TestEffectiveDatedExtrasAndTaxes`, `test_extras_inventory` (unit + integration), `TestConcurrentLastExtra`, e2e `policy-revisions` | No bundles (G-58). (Fixed: extras bookable after booking, G-22.) |
| R-20 | Coupons | PARTIAL | code promotions, scopes, usage and per-guest limits counted under the promotion's row lock with a current read (G-07 regression fixed); the minimum basket is the basket of the booking's rooms the promotion covers, at search, quote, booking and in changes, and a change below it charges the changed room what the others keep (G-84 fixed, ADR-057 and its review follow-up) · `TestConcurrentCouponLimit`, `TestBookingBasket` (unit and integration), `test_basket_clawback` | No package scope (G-58). (Fixed: per-guest limit at booking G-07, min-basket currency G-08, modification redemptions G-09; redemption tests `TestBookingLevelTerms`, `TestCouponLimits`.) |
| R-21 | Modification & repricing | **COMPLETE** | OLD vs PROPOSED with the explanation, 4 bases (`modification.py`, `ModifyDrawer.tsx`); the sale date is changed by pricing on HISTORICAL_SALE_DATE (a *Sale Date* revision; a change carrying its own `sale_at`, or a sale date with another basis, is refused; the date is checked on the server); the historical basis and a manual override need `price.override` on propose and again on apply, with a reason, and the audit records the computed total next to the amount set; a past sale time selects the contracts Active then; proposals are bound to their proposer, hotel and booking (G-51 fixed, ADR-054); repricing ignores the booking's own coupon use and redemptions follow the modification (G-09 fixed) · `test_modification_determinism` (24), e2e crs + critical-journey, `TestCouponLimits`, `test_fx_snapshot` | — (the drawer's historical and override paths are type-checked, not browser-tested) |
| R-22 | Historical simulator | **COMPLETE** | deterministic as of the sale time (ADR-054): the contracts Active then (audited status), the version live then with its frozen market, channels and sale window (G-50), markups, promotions, FX, extras and taxes as of then (G-20), coupon uses held then (G-51 fixed); a future or invalid sale time is refused; `price.view` + `reservation.view`; the dialog names a contract that no longer sells · `TestHistoricalSimulator`, `TestEffectiveDatedExtrasAndTaxes`, `TestSimulatorAsOfTheSaleTime` | — (the stay simulated is the reservation's current one; the hotel's group, which decides group-wide promotions, is read now) |
| R-23 | Revision history | PARTIAL | actor, time, change, old/new values and amounts, reason, snapshots, immutable · e2e step 19 | Approval never recorded on a revision: `approval_status` is always "Not Required" (`_record_revision` defaults it, `services/booking.py:408`, and no caller passes one) (G-59). A guest's change, a lower price included, is a TEX Guest Change Request that staff approve (ADR-044). |
| R-24 | TEX CRS | PARTIAL | `api/crs.py`, `ui_crs.py`, `screens/crs/*`; multi-hotel search, per-room placement | No destination/hotel-group inputs in UI; group search untested (G-40). |
| R-25 | Call Center | PARTIAL | keyboard-first page, all actions incl. resend confirmation; channel binding (G-41 fixed, ADR-050): staff price and book only on the channels of their profiles at that hotel (blank = call centre, `price.any_channel` = every channel), checked on search, quote, quote summary, booking and payment methods; modifications keep the reservation's channel, and a change of room, rate plan, board or market needs booking entitlement for it (review); pricing and booking channels come only from profiles holding `price.view` / `reservation.create` (review); a booking site sells only on a web channel and a staff booking there is flagged (review); the picker offers only allowed channels; Booking Engine and call centre price the same stay differently by configuration · `test_channel_binding` (26), unit `test_channel_entitlement` (7), e2e keyboard booking + `crs-actions` (8 tests, in CI #191; channel picker; add extras, payment link, resend, cancel from the reservation screen) | Allotments stay per contract: one multi-channel contract's allotment cannot be split by channel (use a contract per channel or channel-scoped restrictions; ADR-050). |
| R-26 | Booking guest experience | **COMPLETE** | original design, SEARCH→ROOMS→EXTRAS→GUEST→PAY→CONFIRM with context visible · e2e booking desktop+mobile | (Low visual items in G-80) |
| R-27 | Booking search | PARTIAL | dates, rooms, child ages, promo, currency, language, hotel | No destination for group sites (G-40). |
| R-28 | Room/rate results | PARTIAL | size, occupancy, beds, amenities, board, policies, inclusions, promotions, truthful scarcity | No per-room gallery; tax line only when tax is added; no rate comparison view (G-42). |
| R-29 | Multi-room | PARTIAL | each room priced independently; Booking → Reservations links; booking-level extras and fixed coupons priced once, on room 1, one redemption per booking (ADR-029, G-05/G-06 fixed); the rooms of a booking are quoted together and a minimum basket is the basket of the rooms each promotion covers (G-84 fixed, ADR-057); a change or cancellation that takes the booking below it charges the changed room the discount the other rooms keep, shown to the guest first, with a ledger so each is owed once (review H1) · `TestMultiRoom`, `test_each_room_is_placed_on_its_own`, `TestBookingLevelTerms`, `TestBookingBasket`, `TestBasketReviewInputs`, `TestBasketClawbackMoney`, `test_booking_level`, `test_basket_clawback`, e2e two rooms | Two minimum-basket promotions lost at once are forfeited one by one (their overlap is not charged); a no-show is not a change (ADR-057 review follow-up). Was marked COMPLETE before the review found H1. |
| R-30 | Embeddable booking | PARTIAL | `<tex-booking-widget>` Shadow DOM (isolation verified live), modal/redirect, CSP frame-ancestors | No inline full-booking mode; `modal` = `search`; 1 room only (G-44). (Fixed: e2e `widget.spec.ts`, 3 tests; scroll lock and theme, 2G-1; the old site's name, LO-31; the dialog's own close event, LO-49.) |
| R-31 | Custom domains | PARTIAL | DNS TXT verification with daily recheck; host → site mapping, pinned engine and API; guest links on the hotel's host; Domains tab (ADR-035, G-21 fixed) · `test_custom_domains` (9), e2e `custom-host.spec.ts` | TLS certificate and `add-domain` per host are operations (GO_LIVE_READINESS). |
| R-32 | White label | COMPLETE | validated tokens only (no CSS/JS injection); BrandingTab + preview; branding images checked on the server by their bytes, logo/hero URLs validated on save (G-83); analytics ids judged by one rule on the server, the admin form and the engine (G-62 fixed, c670af4, 2G-1) · unit `branding`, `analytics-ids`, `test_security_hygiene.TestAnalyticsIdsG62` | — |
| R-33 | Admin UI direction | **COMPLETE** | compact TEX shell and screens; rate & availability grid with bulk editing; portfolio dashboard (G-25 fixed, ADR-038); TEX entry screens: sign-in page, `/` to the admin app, brand title (G-60 fixed, ADR-060) · e2e `shell.spec`, `portfolio.spec`, `restrictions-grid.spec`, `entry-branding.spec` | No open gap in the audit. Related gaps belong to other requirements: design-system components and contrast (G-63, R-34), grid rows by rate plan (G-47, R-36), visual QA leftovers (G-80, R-50). |
| R-34 | Design system | PARTIAL | `frontend/src/tex/ui/*` tokens and components | No date picker or calendar component; contrast failures (G-63). (Tooltip, Menu, ContextMenu and Popover exist: `ui/popover.tsx`, ADR-061.) |
| R-35 | Admin navigation | PARTIAL | 11 areas + Call Center; each area's R-35 sub-sections in the sidebar (open while in the area or with its toggle) and the command palette: Rates & Contracts (Contracts, Contract versions, Price periods, Occupancy rules, Rate plans, Markets, Promotions, Restrictions, Currency, Bulk editor), Booking Engine (Sites, Rooms, Content, Analytics), CRM (Guests, Segments, Loyalty, Abandoned bookings, Communications); new cross-record lists return only granted hotels (G-64 fixed, ADR-060); review follow-up: a booking site opens under `/tex/booking-engine/sites/` whatever its name (admin page names refused as new slugs, p47 reports older sites), version tables ordered with their cut told, Restrictions in the rates tab strip needs `price.view` · `test_entry_branding` (G-64: 7; review follow-up: `TestBookingSiteSlugs`, lists), `test_patches` (p47), e2e `entry-branding.spec` | CRM Campaigns not started (R-37): listed as "Not available yet", never a link. |
| R-36 | Rates & inventory grid | PARTIAL | `screens/inventory/*`, `commercial/grid.py` | Rows are room types (not room × rate); the rate cell is the contract's base unit and the Sell price row prices one rate plan (G-47). (Fixed: copy period; tests `test_inventory.TestGridRates`, `test_grid_rate_changes`, `test_grid_sell_prices`, e2e `rates-availability`; the Sell price row applies markups, promotions, FX and taxes, `crs.ari_sell_prices`, §6UX.) |
| R-37 | CRM | PARTIAL | `crm/service.py`, `segments.py`, `screens/crm/*`; typed segments over per-tenant facts, 9 presets, enterprise-owned segments (ADR-036, G-23 fixed; tenancy G-26 fixed); consent granted only by a proven owner: an anonymous booking on a known profile is recorded as a request, shown in the consent history (ADR-046, G-83); the communications timeline shows each guest e-mail's real delivery status (Queued / Sent / Failed with reason, ADR-047) ; the profile shows the extras bought and the cancellations (count, no-shows, fees per currency) at the viewer's hotels, loyalty only in the programs of the viewer's hotels (another hotel's entries of a shared program as points only), totals over the viewer's hotels and programs (never the stored cross-tenant totals, also withheld from Desk / REST); the guest list counts and pages in SQL (G-65 fixed, ADR-056); review follow-up: the program ledger shows another hotel's entries as points only and names only guests the viewer may see; a booking joins a profile by its e-mail, the phone only without one (ADR-056 review); second review: duplicate profiles are merged in the CRM (`crm.edit` at every hotel of either profile's records, one enterprise, ledger moved, stricter consent, audited) and a profile shows its possible duplicates; the phone finds a profile only for staff and only when one profile has it; an erasure leaves no contact data behind (ADR-056 second review, p45); guest communications across guests at the viewer's hotels (CRM › Communications, `lists.communications`, no message body; G-64, ADR-060), the list and the profile naming the actor by one rule and linking only guests the viewer may open (ADR-060 review) · `test_crm_segments`, `test_crm_privacy` (G-65: 8), `test_entry_branding` (communications), consent/export/stats tests, e2e `crm-admin.spec.ts`, `crm-profile.spec.ts` (written, type-checked) | Campaigns not started; a segment filter scans the tenant's guests in batches (a stored fact table later). |
| R-38 | Abandoned booking | **COMPLETE** | funnel events, detection, workflow, consent, purge; an e-mail hash only with the visitor's marketing consent and no contact field in any funnel payload (p37 purged older hashes); contact data of a case only with the profile's own consent and shown while it holds; a case recovered by a later booking in its session or a later payment of its booking (G-81 fixed, ADR-056); review follow-up (p40): a withdrawal of e-mail consent, on every path, makes the guest's cases and funnel hashes anonymous; case contacts and funnel identity withheld from Desk / REST; browser events keep an allow-list of fields; consent flags sent as text are read strictly; second review (p45): a withdrawal reads and writes only the rows it clears (indexes, primary keys), a deadlock while tracking re-raises (a booking is retried, never reported after its rollback), a case's links to the person are withheld from Desk / REST and an anonymous case keeps no quote, a case written after a withdrawal is anonymous, browser funnel values are checked against the site · `test_crm_privacy_review`, `test_abandoned_booking_detection`, `test_crm_privacy.TestAbandonedPrivacy` (6) | — (a per-hotel legitimate-interest basis for recovery contact is an owner/legal decision) |
| R-39 | Loyalty | PARTIAL | earn/mature/redeem/reverse/expire, ledger, manual adjustment; programs, rules, tiers and blackouts administered in TEX; frozen earnings; redemption cap and blackouts (ADR-037, G-24 fixed); a guest's summary shows the programs of the viewer's hotels only (G-65 fixed, ADR-056); the program ledger too (ADR-056 review); each entry belongs to a hotel (the stay's or booking's, or the hotel a manual adjustment was made for), read in Desk / REST at that hotel only, and another hotel's entries show no dates, reason or author (ADR-056 second review) · `test_loyalty_admin` (7), `test_crm_privacy`, e2e `crm-admin.spec.ts` | Redemption only as money (G-66). (Fixed in Part 2: the earn matrix and flows pinned, G-66 tests, `TestEarnMatrix`; first to expire, first used, Y-11/O-22, p61, ADR-071; changes of a spent stay, O-21; points given back, O-20, LO-01, LO-02; the burn row found by the charge, LO-06, p73.) |
| R-40 | Payments | PARTIAL (production certification **BLOCKED**) | provider abstraction, hosted/3D flows, no PAN/CVV, fail-closed callbacks, method rules; every credential write-only and encrypted, the API key / app id too (G-83, patch p22); Production gated on certification at save and run time, no gateway URL override in Production, a Sandbox override only on the provider's sandbox host, no sandbox gateway on a live site (`tex_production`); new money and settling gated apart, so captured money is always recorded and refundable (patch p19 lists gated accounts); captured amount and currency verified, a refused capture audited and refundable (G-67, ADR-041, ADR-042) · `TestGuestPayment`, `TestPaymentIntegrity`, `TestGoLivePayments`, `TestGoLivePaymentsReview`, unit `TestProviderRegistry` | Sipay refund missing and live certification BLOCKED (merchant credentials); Sipay's status answer is not yet a recorded sandbox response; bookings paid in Sandbox on a non-live site carry no per-booking flag (schema field). |
| R-41 | Payment links | PARTIAL | create/reissue/pay/expire, allocation, refund, transfer; one charge per link at a time (`NOWAIT` link lock, locking reads after locks), an iyzico charge has one checkout and another tab or a refused restart supersedes it, captured money on superseded, Failed or closed-link charges recorded and flagged, refunds take unallocated money first and then the booking holding the money (G-68, ADR-041, ADR-042) · `test_payment_link_pays_and_allocates`, `test_refund_transfer_and_idempotency`, `TestPaymentLinkTokens` (G-10 fixed), `TestGoLivePayments`, `TestGoLivePaymentsReview` | Two tabs paying through different gateways, or two iyzico tabs, can still pay twice (kept and flagged for refund); `pay_booking` starts a new charge per call; simultaneous staff refunds/allocations of one payment rely on snapshot totals (needs indexes); no e2e for the link page. |
| R-42 | Guest self-service | **COMPLETE** | per-hotel toggle, hashed magic link, view/cancel/change with price shown first, pending staff state; extras after booking (G-22 fixed, ADR-034); a change settles its money (G-45 fixed, ADR-044): a higher price is paid (deposit share of the new price) before the server applies it, pay at hotel and covered bookings apply at once and say what is due later, a lower price follows the hotel's policy (staff approval, automatic refund of the true overpayment after commit, or credit on the booking); staff decide requests on the reservation screen; after the adversarial review a lower price the rate's terms would charge for waits for the hotel, only Confirmed rooms before arrival change, refunds are durable before the gateway call and an unanswered one waits for staff, refunds are capped by what is still over, the payment callback only records the charge and a job applies the change, money for staff is explicit; after the second review (F1–F8) a refund run holds the request's refunds one at a time and never plans around its own refund in flight (fresh: it waits; unanswered or stuck: staff verify it), staff record any unconfirmed refund's outcome from the payment screen and TEX then refunds what the change still owes, refunds with no answer yet are set aside, a paid change not yet applied is set aside and blocks new changes, moving the arrival later inside a penalty window goes to the hotel, transient database errors are retried, lost apply jobs are swept, and channel changes take the same lock order; after the third review a refund's outcome is recorded only once its answer cannot come any more and a late gateway answer never overwrites it (a contradicting one is an audited conflict that stops the change's refunds for staff), a refund run keeps its hold and counts the refunds it made, and money refunded outside TEX is recorded on the booking (G-93); after the fourth review money handed back is recorded against its own payments, limits are locking reads, money being refunded never moves and a conflict stops every run until staff record the truth · `test_self_service_money` (75), `TestSelfService`, unit `test_settlement`, `test_post_booking_extras`, e2e `post-booking-extras.spec.ts`, `manage-money.spec.ts` (3, passes; extended by the second and third reviews, not yet re-run) | (A credit belongs to its booking: no ledger across stays. Magic-link e-mails need SMTP, BLOCKED.) |
| R-43 | Enterprise / user model | PARTIAL | Enterprise→Group→Hotel grants, 14+ capabilities, anti-escalation (also on update and delete of a grant), backend enforcement; tenant structure scoped (G-26 fixed, ADR-040); sales channels per permission profile, granted only by someone who sells on them (G-41, ADR-050); live grants are the only authority: an ended grant grants nothing, its mirrored rows go at the site's midnight, and the legacy hotel-bound DocTypes follow the TEX scope too (G-94 fixed); fields a role-based permission cannot scope per hotel (pricing internals, a guest's totals over every tenant) are withheld from every business role in Desk / REST (G-95 fixed, ADR-056); on customised role permissions platform administrators keep them (p40 and the permission scripts add System Manager's permlevel-1 row; a business role holding permlevel 1 is reported), and a masked change history keeps its values for platform administrators (ADR-056 review) · `TestTenantIsolation`, `TestAdminDataTenancy`, `test_security_regressions`, `test_channel_binding`, `test_grant_expiry`, `test_crm_privacy` | Guest identity shared inside an enterprise by design (ADR-040). |
| R-44 | TEX Connect | PARTIAL | adapter interface, signed webhook PMS (never unsigned: no secret or no https is a final, audited refusal and a signing connection cannot be enabled without a secret, G-83), sandbox, outbox with claim/retry/dead-letter (PMS connections only; an uncertified adapter never delivers in Production, G-90), FX adapters; channel distribution (ADR-039): mappings, ARI computed from TEX and pushed as changes, signed idempotent inbound bookings applied in order, error queue, reconciliation, audit, sandbox channel adapter (`test_distribution` 16); staff UI Connect → Channels (`channel.view` / `channel.manage`): connections with queue/inbound counts and webhook, mappings editor, ARI preview with queue/send/resend, inbound log with retry/apply, reconciliation, sandbox booking simulator (e2e `channels.spec.ts`, passes); operations (ADR-047): system status of the queues, connections, callbacks, FX, mail and jobs (`system.monitor`, hotel-scoped), guest liveness ping, alerts on change, Settings → System status; e-mail goes through Frappe's queue and each TEX Communication follows it (Sent / Failed with reason), guest mail in the hotel's name with its Reply-To · `test_system_status` (12), unit `test_system_checks` (17) | Real channel-manager providers BLOCKED on credentials/certification; e-mail delivery BLOCKED on SMTP; no SMS/WhatsApp adapters; `fetch_availability` unused. Mappings: switching a mapping off sends a close-out; a switched-off mapping is deleted once the channel accepted it (`distribution.delete_mapping`). |
| R-45 | Quote engine | **COMPLETE** | persisted TEX Quote (id, expiry, version, hash, request, breakdown, extras, promotions, tax, total); full internal explanation · `TestSpecExplanationExample`, `test_guest_quotes_never_carry_cost` | (multi-room charges tracked under R-19/R-20) |
| R-46 | Price lock | COMPLETE | snapshot at booking; contract edits don't touch sold reservations; stored-value lock over the whole commercial record; only TEX services change a sold stay, the legacy night audit leaves it alone (G-01, G-04 fixed); the legacy check-out and cancellation fees never bill a locked stay at the legacy rate: a TEX-sold stay is billed on its TEX booking, an imported one posts its locked amount (G-96 fixed, ADR-052 review) · critical journey step 16 (UI shows the locked price), `TestPriceLock`, `TestLegacyNightAudit`, `TestLegacyCheckOut`, `TestImportedCancellationFee` | — |
| R-47 | Dashboard | PARTIAL | `reports/service.dashboard`; portfolio across enterprise/group/hotels with sales, payment, abandonment KPIs per currency and inventory/restriction alerts (ADR-038, G-25 fixed) · `test_portfolio`, e2e `portfolio.spec.ts` | Per-hotel time zones; no reporting-currency conversion. |
| R-48 | Reports | **COMPLETE** | `kamra/tex/reports/service.py`, `api/reports.py` (`report`, `filter_options`), `screens/reports/*` (ADR-059): booking production by stay night or by sale date; by hotel, hotel group, room, market, channel, rate plan, board, contract, agency, guest country, status, day, month; promotion, cancellation, payment (with payments by method), extras and conversion views; contract vs selling and margin reconciling to the cent (cost + margin = accommodation; accommodation + extras + the reservation's taxes on top + stays without a contract cost + fees of cancelled stays = revenue; each stay split over its nights in whole cents as the folio bills it, so totals are row sums and the same for every grouping and fold); filters: one hotel or a hotel group / enterprise / all scope narrowed to the viewer's hotels, market, currency, channel, sale date and stay date together, room, rate (cleared on a scope change); a filter a view cannot apply is refused; money per currency, never added across currencies, payments per transaction currency; cost and margin (and cost-stage offers) only with `price.view_cost` at every hotel, payments only with `payment.view` at every hotel; every endpoint declares `report.view`; conversion counts group booking sites when the report covers the whole group, each session once, never above 100 %; a fixed number of SQL aggregates per view, indexes by hotel and date (p46), 60 reports a minute per user, 800-day windows, long results folded; CSV per view (G-46 fixed, ADR-059 review follow-up) · `test_reports` (35), `test_portfolio`, `test_commercial_flows`, e2e `reports.spec.ts` | — (no one-currency converted total, by decision: ADR-059) |
| R-49 | i18n | PARTIAL | 6-language UI catalogs (parity in CI), the sign-in page in the six languages (G-60), guest e-mails, hotel content translations | Staff-side server messages (`_()`) untranslated and UI language not sent; some hard-coded English. Guest refusals carry a code and are shown in the guest's language since G-70b (§6G3). |
| R-50 | Responsive | PARTIAL | no page overflow at 320–1920 on 11 screens; booking mobile e2e; staff date defaults start on the site's day in any browser time zone, and follow the site's midnight while a tab stays open (G-91 fixed: `session.bootstrap` `server.today`, `frontend/src/tex/lib/siteDay.ts` · `TestSessionSiteDay`, e2e `site-day`) | Content clipped at 320 px (inventory, reports); no admin responsive tests (G-80). |
| R-51 | Accessibility | PARTIAL | skip link, focus, labels, dialogs, keyboard e2e | Contrast failures: zinc-400 text (about 2.6:1 on white, e.g. shortcut hints in `ui/popover.tsx:588`), grid muted values, weekend headers; no automated a11y tests: a contrast unit test covers the Pricing Workspace colours only (`tests/unit/contrast.test.ts`) (G-63). The sidebar group labels are `text-zinc-500` now (`TexShell.tsx:294`, about 4.8:1 by calculation, not measured on screen). |
| R-52 | Performance | PARTIAL | lazy areas/languages, caches on immutable terms | 295 KB legacy shell in admin bundle; per-room-type availability queries; no budgets. Guest quotes no longer carry contract internals (G-71, §6G3). |
| R-53 | Security | PARTIAL | TEX endpoints scoped (115, 34 probed), legacy record arguments resolved to their hotel (G-02 fixed, ADR-027), REST/Desk isolation, CSRF, parameterised SQL, escaped e-mail, rate limits, hashed tokens, fail-closed callbacks; G-83 hygiene fixed and reviewed (ADR-046 with its review follow-up): communication links checked for guest and hotel, no consent granted on a known profile by an anonymous booking or by staff without `crm.edit`, the consent history kept to the viewer's hotels, uploads checked on the server with images decoded whole, the public folder serving only an allow-list judged on the stored name, bearer tokens only in URL fragments and POST bodies (payment pages send no Referer), the PMS webhook never sends unsigned, payment API keys encrypted and masked in the change history (p22, p24) · `test_security_regressions`, `test_security_hygiene` (14), unit `test_filetypes`, e2e `pay-link.spec.ts` (2, passes); the system status is capability- and hotel-scoped and the guest ping answers booleans only, with no secret in either payload (ADR-047, `test_system_status`) | (G-10…G-16, G-26, G-83 fixed.) Owner decisions left from G-83: a double opt-in e-mail for consent asked for on a known profile (needs SMTP); payment links e-mailed before G-83 keep their token in the path on their first request until they expire. SECURITY.md, pentest (GO_LIVE_READINESS). |
| R-54 | Audit trail | **COMPLETE** | immutable `TEX Audit Event` (actor, roles, hotel, source, old/new, reason); compact bounded diffs (ADR-053): every saved draft contract edit on every path (settings old → new, table rows by natural key), a publish's commercial difference against the version it replaces, ARI and limited-extras bulk edits with each cell's old value, payment policies / provider accounts / method rules on the TEX API, Desk and REST paths (secrets only as set / changed booleans); group and enterprise events name their group / enterprise and the hotels they reached (`TEX Audit Scope`, p33), seen by each of those hotels' staff and by no other hotel (viewer, Desk, REST); each payment outcome's real source (gateway return, gateway notification, staff, scheduler); Settings → Audit trail renders row changes, hotels reached and sources (G-74 fixed) · `test_audit_trail` (15), unit `test_audit_changes` (11) | — |
| R-55 | UX productivity | PARTIAL | Ctrl+K, shortcuts, quick booking, duplicate contract, bulk edit, quick payment link | No recent reservations, copy restrictions or saved filters; global search covers reservations only (the palette finds one in every hotel, §6UX) (G-75). (Fixed: copy period; a new season from Duplicate, e2e `contract-season`.) |
| R-56 | Migrations | **COMPLETE** | p01–p76 in `patches.txt` (68 patches), each listed with what it does in `MIGRATION_PLAN.md`; a patch skipped by a failing migration runs whole next time, one-time steps (p01, p02, p04, p36, the capability grants, p12, p17) never undo an administrator's change on a forced re-run, and the migration tests commit nothing even when interrupted, with the whole-site tests on a disposable site (ADR-058 review); every patch tested for its behaviour on pre-patch data, a second run that changes nothing (at once or forced later: conversions and capability grants run once), no change to published payloads or sold prices, and an empty site; the upgrade of a Kamra database runs the whole chain (G-76 fixed, ADR-058: `test_patches` 21); the tests found and fixed re-run hazards in p02, p04, p08, p12, p17, p18, p23, p29, a guessed tenant in p01, legacy stays summed in the wrong currency by p09, repeated reports in p19/p24, Kamra hotels set live by p36 and indexes dropped by Frappe's schema sync (p39); the booking importers read amounts strictly (decimal mark, currency, never guessed), preview each row's amount, import each row all or nothing, and an imported amount is corrected with `price.override` (ADR-052 review, `test_legacy_pricing_review`, unit `test_import_amounts`); p36 (today's TEX hotels stay live) tested; p37 (funnel e-mail hashes kept without consent removed, withheld fields masked in the change history; re-runnable) tested in `test_crm_privacy` | — (A TEX-native importer for future bookings, guests and contracts is a go-live item: GO_LIVE_READINESS "Data migration".) |
| R-57 | Testing | **COMPLETE** | every category in the spec list maps to tests (occupancy, bands, boundaries, combinations, precedence, overrides, versions, historical, periods, FX, markup, promotions, restrictions, concurrency, revisions, permissions, tenancy, payments) | New regression tests are required with each gap fix (FINAL_GAP_AUDIT §4). |
| R-58 | E2E (Playwright) | **COMPLETE** | `frontend/e2e/critical-journey.spec.ts` (19 steps via UI), `booking.spec.ts` desktop + mobile; the flows' `saveDraft` waits for `save_version`'s answer (a toast left from the previous save let it return early: the cause of `contract-admin`'s intermittent failure, branch `fix-editor`) | Low: step 17 changes dates, not occupancy (G-82). |
| R-59 | Visual QA | PARTIAL | manual QA at 320–1920 in tr/en/de | Contrast, 320 px clipping, English system segment names; no visual regression tests (G-80). (Fixed: `/` and the sign-in page, G-60, ADR-060.) |
| R-60 | Implementation order | **COMPLETE** (process) | phases followed pricing-first | — |
| R-61 | Process rules | **COMPLETE** (process) | docs + ADRs + this single-state status | — |
| R-62 | Definition of done | PARTIAL | — | FINAL_GAP_AUDIT §1 (Critical) and §2 (High) are closed, and audit Part 2 with Stage 3 (O-8, G-55b, G-71, G-70b) is done (§6G2, §6G3). Medium and Low gaps, provider certification and the operations blockers (GO_LIVE_READINESS §2) remain, so not done. |

## 5. Independent audit fixes (2026-09-26)

- K-1 **COMPLETE**: a contract fixed offer is in the contract currency (frozen payload; legacy payload read so), converted to the sell currency via `promo_fx`, not applied without a rate (`PROMO_NO_FX`) · `unit/test_contract_offer_currency`, `integration/test_contract_offer_currency`.
- K-2a **PARTIAL** (audits 1b, 1c, 1c-son done; open: B4/D3 PARTIAL, iyzico and Sipay state no capture time): a TEX booking and all its rooms expire together under the booking lock; a payment attempt started within the hold keeps them only until its finite deadline (`expires_at`, p49) · `integration/test_hold_payment_race.TestAtomicExpiry`.
- K-2b **PARTIAL** (audits 1b, 1c, 1c-son done; open: B4/D3 PARTIAL, iyzico and Sipay state no capture time): money for a booking whose rooms are still held confirms it however late (B3 a); money whose rooms were given back is kept off the booking in `reconciliation` unless paid in time (B4) (p50; refund queue when the rooms are gone), audited, nothing sent (ADR-062) · `test_hold_payment_race.TestLatePayment`.
- K-2c **PARTIAL** (audits 1b, 1c, 1c-son done; open: B4/D3 PARTIAL, iyzico and Sipay state no capture time): every money path (callback, link, bank transfer, manual, staff allocate/transfer) keeps to the booking lifecycle; money a cancelled/expired booking cannot take goes to reconciliation (staff are refused explicitly), cancellation fees still allocate · `test_hold_payment_race.TestMoneyForBookingsThatCannotTakeIt`, `TestLastRoomRace` (threads).
- K-2d **PARTIAL** (audits 1b, 1c, 1c-son done; open: B4/D3 PARTIAL, iyzico and Sipay state no capture time): one resolver `holds.resolve_hold_minutes(property, method)` (card 20 min, link 24 h, transfer 48 h in TEX Settings; per-hotel `tex_hold_minutes_*`, blank = global, p51); a booking-bound payment link never outlives its hold, a standalone one keeps its validity · `test_hold_payment_race.TestHoldPolicy`.
- B1 (audit 1b) **COMPLETE**: a never-confirmed booking with a room cancelled keeps waiting for its payment (expires with its hold, confirmed by its payment, late money reconciled); p52 restores stuck ones · `TestPartialCancellation`.
- B2 (audit 1b) **COMPLETE**: money a waiting booking held when it expired comes off it into reconciliation (never a negative balance), amount audited · `TestExpiryWithMoney`.
- B3 (audit 1b) **COMPLETE**: a payment for a booking whose rooms are still held confirms it at the locked price, however late; released-and-free rooms → Action Required, sold rooms → refund or Action Required (ADR-062) · `TestLatePayment`.
- B4 (audit 1b) **PARTIAL** (iyzico, Sipay state no capture time): lateness by the gateway's capture time when stated (`captured_at`, p53); a delayed notification or reverify of money paid in time revives the expired booking while its rooms are free, else Action Required · `TestPaidInTime`.
- B5 (audit 1b) **COMPLETE**: reconciliation is visible — status check with ages (FAIL after 24 h / queued refund 1 h), e-mail to the hotel's address (else status-alert recipients) and to the payer, staff API/list/detail/dialogs and guest pages say what happened (never "payment received") · `TestReconciliationVisible`, unit `test_money_in_reconciliation_is_shown_with_its_age`.
- B6 (audit 1b) **COMPLETE**: sending a payment link for a booking awaiting payment (booked by card) holds its rooms for the link hold (hotel → TEX Settings → 24 h) and the link expires with it; response, e-mail and both link dialogs show the real expiry · `TestPaymentLinkHold`.
- Audit 1b tests & small fixes **COMPLETE**: real thread races (expiry job × late payment × last-room guest, `TestLastRoomRace`), expiry after a link part-payment, p49 docstring corrected; `attempt_deadline`/`expires_at` now used by B4.
- D1 (audit 1c) **COMPLETE**: a never-confirmed booking recomputes what it owes now (`required_now`, up or down, never above its total) after every change — room cancel, dates, extras, coupon, price override (1c-son E2) — and is confirmed when already paid; p52 confirms stuck bookings whose payment was taken (pre-C6 fees void, no mail, E6) · `TestPartialCancellation`, `TestChangesOfABookingWaitingForItsPayment`.
- D2 (audit 1c) **COMPLETE**: a never-confirmed "Partially Cancelled" booking takes no money as a confirmed one; p54 cancels such leftovers, parks their money (audited, no mail) · `TestNeverConfirmedLeftovers`.
- D3 (audit 1c) **PARTIAL**: capture time wired for the virtual POS (`EXTRA.TRXDATE`, Istanbul → site time), the mock (server clock) and bank transfers (staff's value date); iyzico/Sipay state none (fallback) · unit `test_gateways_state_when_they_captured_the_money`, `TestPaidInTime`.
- D4 (audit 1c) **COMPLETE**: paid in time → revived only while its rooms are free, this money plus its B2 money covers `amount_due_now` and its limited extras/coupons are free; else, or another live booking of the same booker (profile or e-mail) overlaps the stay → Action Required (no auto refund); a revival locks the B2 charges before the booking · `TestPaidInTime`.
- D5 (audit 1c) **COMPLETE**: no payment link for a booking neither waiting nor confirmed (clear error); CRS "send link" hidden for it · `TestPaymentLinkHold.test_no_link_for_a_booking_that_expired`.
- D6 (audit 1c) **COMPLETE**: a link made for a TEX reservation records its booking, so it holds its rooms and its payment is allocated to it · `TestPaymentLinkHold.test_a_link_for_a_reservation_pays_its_booking`.
- D7 (audit 1c) **COMPLETE**: a link hold ends at the latest at the end of the arrival day (1c-son E3); cancelling a link gives its extension back, never below the other links' expiry (open or paid) nor now + the method's hold · `TestPaymentLinkHold`.
- D8 (audit 1c) **COMPLETE**: the two free thread races accept either order (A confirmed, or expired by the job — never by its payment — its money in reconciliation); a forced-order race (the job starts once the payment holds A's lock) accepts only A Confirmed, pinning B3 a) (1c-son E7); tests for guest manage_cancel, part-paid T1 + late T2 flagged once each · `test_hold_payment_race.TestLastRoomRace`.
- D9 (audit 1c) **COMPLETE**: status check `holds.overdue` (bookings still holding rooms 20 min after their hold, FAIL) and booking-expiry failures counted in TEX job errors · `TestExpiryFailureVisible`, unit `test_holds_past_their_deadline_fail`.
- C1 (audit 1c) **COMPLETE**: a card attempt runs at most 5 min (3DS margin) past the hold (no fixed 30 min); a new attempt may start before the hold ends, or after it while an earlier attempt is still open (a declined card retries), never past that attempt's deadline · `TestAtomicExpiry`.
- C2 (audit 1c) **COMPLETE**: a bank transfer booked on the web holds 24 h (`hold_minutes_transfer_web`, hotel override, p55) and takes at most 2 rooms; call centre/staff keep 48 h · `TestHoldPolicy`.
- C3 (audit 1c) **COMPLETE**: a payment outcome chosen as a deadlock victim is applied again (`complete_retrying`: callback, sandbox, reverify); pay_booking/pay_link/manage_cancel/crs.cancel and staff payment endpoints retry · `TestDeadlockRetries`.
- C4 (audit 1c) **COMPLETE**: reconciliation follows the money — a refund in flight settles nothing; refund_outside, finish_unknown_refund and correct_refund update it (a refund found not made reopens it) · `TestReconciliationStates`.
- C5 (audit 1c) **COMPLETE**: staff recording a manual payment or redeeming points on a booking that cannot take the money are refused with the reason (nothing recorded, no points burned) · `TestMoneyForBookingsThatCannotTakeIt`.
- C6 (audit 1c) **COMPLETE**: a room of a booking never confirmed owes no cancellation penalty but still carries the basket discount the other rooms keep (1c-son E1); a booking that ends never confirmed owes nothing (its fees void, audited; p52/p54 void pre-C6 fees, E6); money on its way is never kept as a fee · `TestMoneyForBookingsThatCannotTakeIt`, `TestBookingBasket`.
- C7 (audit 1c) **COMPLETE**: the payment report counts a late payment's refund (a payment's booking via its charge or link); a link whose money was parked is closed, not "Paid"; nothing owed and nothing paid is "Unpaid" · `TestMoneyShownRight`.
- E1 (audit 1c-son) **COMPLETE**: cancelling a room of a booking not paid yet charges the basket clawback (G-84) with no penalty; ending never confirmed voids every fee; a revival charges the clawback again · `test_commercial_flows.TestBookingBasket`.
- E2 (audit 1c-son) **COMPLETE**: `modification.apply` and add-ons recompute a waiting booking's due and call `confirm_if_paid` (shortened after a paid half → confirmed once; a higher price is not confirmed by the old amount) · `TestChangesOfABookingWaitingForItsPayment`.
- E3 (audit 1c-son) **COMPLETE**: a cancelled link never pulls the hold into the past (floor now + method hold; Paid/Partially Paid links count); `cancel_link` returns the hold end, shown in the cancel toast; arrival cap 23:59:59 · `TestPaymentLinkHold`.
- E4 (audit 1c-son) **COMPLETE**: a booking paid in full, cancelled or expired closes its open links (audited, `SKIP LOCKED`); `pay_link`/`reissue_link` refuse a link its booking cannot take or that asks more than it owes · `TestPaymentLinkHold`.
- E5 (audit 1c-son) **COMPLETE**: `late_payments.settled` reads the charge's reconciliation with a locking read · `TestLastRoomRace.test_a_charge_leaves_reconciliation_by_its_state_as_it_is_now` (threads).
- E6 (audit 1c-son) **COMPLETE**: p52/p54 void pre-C6 fees of never-confirmed bookings (p52 keeps a basket clawback); p52 expires with no mail · `TestPartialCancellation`, `TestNeverConfirmedLeftovers`.
- K1–K4 (audit 1c-son) **COMPLETE**: payment report leaves out a refused capture and its refund together; a parked/refunded link page shows only the late notice; `providers/simple.py` loads without frappe; `hold_minutes_transfer_web` in the settings API · `TestMoneyShownRight`, unit `paylink-notices`, `TestProvidersWithoutBench`, `TestHoldSettings`.

## 6. Audit Part 2A (2026-09-26)

- DOC-0 **COMPLETE**: the docs no longer say GitHub PR/CI is blocked (CI green on PR #2, PR #1; CI/CD PARTIAL: scanning, image, registry, staging, deploy open) · `git grep`.
- NEW-1 **COMPLETE**: scheduled jobs never read a missing date as past (contract roll, loyalty expiry, grant expiry, payment links); every nullable date filter says what NULL means; p56 repairs the roll (ADR-064) · `test_null_dates`, `test_patches` p56, `unit/test_nullable_date_filters`, `test_scheduler_smoke`.
- Y-1 **COMPLETE**: `admin.audit_log` by reference needs the record's own read capability (contract, version and rate tables: `price.view_cost` or `contract.edit`; markups and pricing policies `price.view_cost` as their API; payments `payment.view`; stays `reservation.view`; other policies their read capability; else `settings.admin`) · `test_audit_trail.TestTrailByReference`.
- Y-10 **COMPLETE**: an EXTRA-based loyalty rule reads the snapshot quantity ("2.000000") as Decimal (`loyalty.extra_units`); a quantity that is not whole earns nothing and says so, never breaking the confirmation · `test_loyalty_admin.TestExtraEarning`.
- O-16 **COMPLETE**: a guest cancels a room online only before the arrival day (site's day; `public.manage_cancel` refuses with ChangeRefused, `can_cancel` hides the manage page's button); a change may still start on the arrival day (unchanged, ADR-064) · `test_commercial_flows.TestSelfService.test_no_online_cancellation_from_the_arrival_day`, `frontend/tests/unit/manage-actions.test.ts`.
- Y-12 **COMPLETE**: p48 marks a profile erased only on a `guest.erase` event, or an Executed/Approved `anonymize_guest` log row on a profile showing the legacy erasure's traces (alias, no last name/e-mail/phone, its note); other rows are only counted; business roles read the Agent Action Log only: its JSON, and p64 on sites whose seeds wrote Custom DocPerm rows (`seed_rbac_v2.ensure_hotel_admin` now grants it read-only) · `test_patches.TestP48Evidence`, `TestP64AgentLogReadOnly`, `test_crm_third_review.TestP48`.

## 6B. Audit Part 2B (2026-09-27)

- P1-6 **COMPLETE**: `required_now` prices every room's deposit on its stored price (`booking.at_stored_price`), so a price staff set is what the booking owes now (ADR-065) · `TestChangesOfABookingWaitingForItsPayment`.
- Y-7 **COMPLETE**: extras add to the stored price; a price set by hand stays one (snapshot `override_amount`, revision `manual_price`, audit `total_before/after`) · `test_post_booking_extras.TestPostBookingExtras`.
- Y-7b **COMPLETE** (D-9): a later change of a stay priced by hand needs a choice (keep it: `override_amount`; or `reprice=1`: audited `manual_price_dropped`), else refused; guests cannot change it online; ModifyDrawer shows both amounts · `TestManualOverride`, `TestGuards`.
- P1-3 **COMPLETE**: a refund's outcome on a booking that ended never confirmed takes what it still holds into reconciliation (`late_payments.after_refund`, keys `refund:`/`refund-fix:`), team told · `TestReconciliationStates`.
- P1-7 **COMPLETE**: a never-confirmed booking cancelled with money parks it (`cancelled:`); system money is allocated up to what a booking owes, the rest `OVERPAID`; status check `payments.overpaid` · `TestMoneyForBookingsThatCannotTakeIt`, `TestPaymentLinkHold`, `TestOverpaidBookings`, unit `test_system_checks`.
- P1-5 **COMPLETE** (D-10): a link is in its booking's currency (create, pay, reissue refused otherwise); money that came in another currency is recorded and kept off the booking (`CURRENCY_MISMATCH`), the link closed · `TestPaymentLinkHold`.
- O-38 **COMPLETE**: `TEX Payment Link.idempotency_key` unique (p57 `[pre_model_sync]` renames duplicates, empty keys → NULL); a racing `create_link` replays the other's link, one e-mail · `TestConcurrentPaymentLink`, `test_patches` p57, unit `test_p57_plan`.
- P1-10 **COMPLETE**: one `booking.payment_status` formula for payments and refreshes, "Refunded" included · `TestMoneyShownRight`.
- O-19 **COMPLETE**: points pay at most min(share of the total − points on it, total − paid), read under the booking's lock; refund plans take an overpayment off the points first, never cash for points · `TestEarningsAndRedemption`, `TestLowerPrice`, unit `test_settlement`.
- P1-11 + NEW-3 **COMPLETE**: a bank transfer is confirmed with the amount that came (≤ asked, audited); the API requires the value date; the dialog asks the amount · `TestPaidInTime`.

## 6C1. Audit Part 2C-1 (2026-09-27)

- Y-4 **COMPLETE**: a price is refundable only when its rate plan row and its cancellation policy both are (quote `rate_plan.refundable`, search, fee); publish refuses `RATE_PLAN_REFUNDABLE`; new rows take the plan's/policy's flag (ADR-067) · unit `TestRefundableByPolicy`/`TestRefundableIssues`, `test_commercial_flows.TestNonRefundablePolicy`.
- Y-3 A **COMPLETE** (Y-3 B, booking.py, is the payments session's Part 2E): policies' fixed amounts have a currency, frozen only on fixed policies, contract's when empty; `POLICY_CURRENCY`; helpers `fixed_in_sell`/`first_rooms_per_policy`; p59 reports, no backfill · unit `test_policy_money`, `TestPolicyCurrency`, `test_patches` p59.
- O-2 **COMPLETE**: version setting `infants_count_as_children` (default 1, a new contract's first draft 0): off, infants neither count for combinations/max_children nor take a child's position; frozen only when 0 · unit `TestInfantsNotChildren`, `test_commercial_flows.TestInfantsNotChildren`, e2e `pricing-infants`.

## 6C2. Audit Part 2C-2 (2026-09-27)

- O-2b **COMPLETE**: with infants not children the publish check numbers them as the runtime does; a new row's refundable flag reads the plan's default policy; ladder text; plan issues listed under their rate plan · unit `TestInfantsNotChildren`, `TestPlanIssueRefs`, frontend `plan-refundable`.
- Y-5 **COMPLETE**: a search prices the hotel's mandatory extras as the quote does (an ambiguous catalog stops the hotel's rooms, not the search) · `test_public_booking.TestMandatoryExtrasInSearch`.
- O-1 **COMPLETE**: a promotion the room cannot use is refused before the combination step; unsupported type/scope pairs and non-accommodation cost offers refused on save (ADR-068) · unit `TestUnusableNeverWins`, `TestPromotionSaveChecks`.
- O-4 (+O-3) **COMPLETE**: group rule (highest priority, then the older) and cancellation-row texts in 6 languages; `group_ties` and a PROMO_GROUP_TIE warning on save/activation · unit `TestGroupRule`, `TestPromotionGroupTies`.
- O-7 **COMPLETE**: a minimum basket requires its currency (drafts and activations; the editor shows it); help text · `test_a_minimum_basket_needs_its_currency`, unit pin at 51.
- O-31 **COMPLETE**: codes compared by `code_key` (Turkish İ/ı), CRS inputs keep letters; p60 rewrites stored codes, reports clashes · unit `TestCodeKey`, `test_patches` p60, frontend `promo-code`.
- G-57 **COMPLETE**: members-only promotions refused on save/activation until a sale knows members; box hidden · `test_a_member_only_promotion_is_refused_until_a_sale_knows_members`.
- G-53 **COMPLETE**: a markup tying a live one is refused on activation (serialised); the contract page publishes with the workspace's board checks · unit `test_same_scope_markup_tie_is_flagged`, `TestMarkupTies`, e2e `contract-publish-boards`.

## 6G1. Audit Part 2G-1 (2026-09-27)

- O-28 **COMPLETE**: a signed-in user's booking-engine page (/book and a pinned host) carries the session CSRF token, sent by `pub` (header) and `beacon` (form field); such a page loads no third-party tracker and shows no consent banner (ADR-046 note) · `test_security_hygiene` O-28, e2e `guest-session` O-28.
- O-27 **COMPLETE**: the confirmation's manage link carries no token (`/<site>/manage`; the click stores this booking's token for the tab); no URL, href or tracker request carries it · e2e `guest-session` O-27, `custom-host`.
- G-62 **COMPLETE**: GA4/GTM/pixel ids judged by one rule (`booking/lib/analyticsIds.ts`) on the server (new or changed values, trimmed), the admin form and the engine · `test_security_hygiene` G-62, unit `analytics-ids`, `branding`.
- G-44 **COMPLETE**: the widget restores the host's scrolling on close, removal and re-render, and keeps the site's theme across re-renders · e2e `widget`.
- O-32 **COMPLETE**: Call Center shortcuts (`crs/lib/shortcuts.ts`): on a Mac ⌃⌥ always, ⌥ alone not where it types a character in a field; elsewhere Alt without Ctrl/Meta/AltGr; labels ⌃⌥ on a Mac · unit `callcenter-shortcuts`, e2e `crs` O-32.
- O-29 **COMPLETE**: CRS search, quote and quote summary apply only the latest request's answer · e2e `crs-actions` O-29 (summary and search races).
- O-30 **COMPLETE**: checkout books the quotes it just made again (older than 25 min), with a new idempotency key · e2e `booking` O-30.

## 6D1. Audit Part 2D-1 (2026-09-27)

- 2C-2 leftovers **COMPLETE**: group rule text (0a), the publish check skips an infant slot the room cannot hold (0b), an ambiguous extras catalog read once per hotel (0c), `code_key` idempotent (0d) and used for a change's codes (0e), markup tie message (0f) · unit `TestGroupRule`/`TestCodeKey`, `test_commercial_flows`, `test_modification_determinism`.
- Y-2 + O-13 **COMPLETE**: withdrawing a scheduled version gives the previous one its window back, a live one ends now; the version's open quotes become Expired under lock order quote → contract → version; p69 index; ops check `contracts.live` (ADR-069) · `test_null_dates.TestVersionLifecycle`, `test_concurrency.TestConcurrentWithdraw`, `test_patches` p69, unit `TestContractsLive`.
- O-10 **COMPLETE**: `save_version(expected_modified)` refuses a stale editor save (`DraftChanged`); the editor sends the token and offers Reload · `test_pricing_workspace_api.TestDraftToken`, frontend `draft-token`.
- O-9 + G-47 **COMPLETE**: grid rate edits planned by pure `pricing/ratesplit.py` (in place, else one clone per part above every overlapping period of its kind); an edit adding an ERROR is refused · unit `test_ratesplit`, `test_inventory.TestGridRates`.

## 6E1. Audit Part 2E-1 (2026-09-27)

- Y-3 B **COMPLETE**: a fixed deposit or penalty is converted from its policy's currency at the quote's recorded rate (a snapshot without one keeps the amount); a fixed deposit is taken once per booking and policy, room by room, each room at most its stored price; the fee's basis says `fx`; the guest's change preview settles the internal quote; offers write the policy's own currency (ADR-067) · `TestPolicyCurrency`, `test_existing_semantics.TestPolicyMoneyChanges`, unit `policy-currency`.
- NEW-6 **COMPLETE**: `start_payment` commits the charge with a checkout lease (p68, 100 s) before the gateway call and records its answer after, so no row, gap or series lock is held through it; `PaymentBusy` for a second start (ADR-066) · `test_hold_payment_race.TestNoLockHeldThroughTheGateway`, `TestGuestPayment`, `test_patches` p68.

## 6I. Audit Part 2I (2026-09-27)

- 2G-1 leftovers **COMPLETE**: a new price found by checkout's re-quote stops the booking until the guest submits again (O-30); a stale CRS search no longer moves the cursor, a quote of the previous search is never current, a failed summary leaves no amount (O-29) · e2e `booking`, `crs-actions`.
- NEW-8 **COMPLETE**: an Agent Action Log row without a hotel is platform level (Desk / REST, `activity_detail`, `activity_feed`); new rows take their record's hotel; p65 fills the old ones; minutes saved per own hotels · `TestLegacyTenancy` NEW-8, `TestP65AgentLogHotel`.
- G-97 **COMPLETE**: TEX Contract Version, Markup Rule and Pricing Policy are System Manager's in Desk / REST (spec `COST`, p66); cost audit events hidden from non-platform users in Desk / REST and, by capability, in the TEX audit log's hotel view · `TestCostRecordsInDesk`, `TestP66CostDocTypesSystemOnly`, `test_audit_trail`.
- O-37 **COMPLETE**: p63 masks every Password field in the change history (changed, child row_changed) · `TestP63VersionedPasswords`.
- NEW-5 **COMPLETE**: `supply-chain.yml` — gitleaks (self-tested), npm audit-ci, pip-audit with a reviewed ignore list · the workflow's three jobs.

## 6E2. Audit Part 2E-2 (2026-09-27)

- P1-8 **COMPLETE**: `complete_retrying` retries lock wait timeouts too (full rollback); `reissue_link`, `loyalty_redeem`, `merge_guests` retried on deadlocks; re-verify keeps no message of a failed try; `payments.pending` FAILs for Virtual POS charges 10 min past their deadline; a request that committed a step is not run again (ADR-066) · `TestDeadlockRetries`, unit `test_system_checks`, `TestUnverifiedPayments`.
- NEW-2 **COMPLETE**: job `payments.service.reverify_pending`, first of the 5-minute jobs, asks iyzico/Sipay about Pending charges (`status_query`, `status_params`), one per transaction · `TestPaymentsVerifiedByTheJob`, `test_scheduler_smoke`, unit `test_payments_fx_segments`.
- O-18 **COMPLETE**: iyzico `fraudStatus` read (1 served; 0/absent/unknown review; -1 rejected); review holds the booking once for the link hold, rejection ends it and tells the team (ADR-062) · unit `test_payments_fx_segments`, `TestIyzicoFraudReview`.
- P1-1 **COMPLETE** (D-7): late money without a gateway time on an expired booking goes to Action Required, never refunded by itself (ADR-062 c) · `TestReconciliationVisible`.
- P1-9 **COMPLETE**: a refused retry or link after the hold expires the booking and commits first; links inside the 3-D Secure margin; no transfer past the hold (ADR-062) · `TestRefusedAfterTheHold`.
- Fix round 1 **COMPLETE**: NEW-2's job asks by urgency (still holding rooms, nearest deadline first; holding none, oldest first; deadline gone by, latest first) so abandoned iyzico checkouts cannot fill the 20 of a tick; a failed token's half-written try is undone before the next token, and a lost savepoint rolls back whole (ADR-066) · `TestPaymentsVerifiedByTheJob`, `TestAFailedTryLeavesNothing`. Open: Pending candidates without a question (an iyzico charge with no token) still take a place; a `last_reverified_at` field (schema + patch) for a fair order → later.

## 6H1. Audit Part 2H-1 (2026-10-01)

- Y-11 + O-22 **COMPLETE**: points are used first-to-expire first and an expiry takes only what is left of its lot (`crm/lots.py`, `settle`, ADR-071; p61 closes lots that expired before) · unit `test_loyalty_lots`, `TestExpiry`, `test_patches` p61.
- O-21 **COMPLETE**: changing a spent stay is exact (no re-minted points, the new lot keeps the old one's state, a reversal takes the lot's expiry rows) and the stay does not raise its own tier · `TestModification`.
- G-66 **COMPLETE** (tests only): the earn matrix (every basis, with and without a tier multiplier) and the earn / pending / expiry / redemption flows are pinned · `TestEarnMatrix`.
- O-23 **COMPLETE**: the CRM counts visits (the rooms of one booking are one stay and not a repeat guest) · unit `test_segments`, `test_crm_segments`.
- O-26 **COMPLETE**: the abandoned list keeps and shows a phone only with SMS or WhatsApp consent (`phone_channels`), never as a `tel:` call link · `TestAbandonedPrivacy`.
- O-33 **COMPLETE**: the CRM phone export keeps international numbers as they are (`lib/csv.ts`) · unit `csv-cell`.

## 6D2. Audit Part 2D-2 (2026-10-01)

- 2D-1 leftovers **COMPLETE**: withdraw reads only under its locks, a version without a start is on sale not scheduled, the quote endpoints retry a deadlock; the `channels.spec.ts:127` CI failure was the MappingDrawer's stale-form race ("Required."), fixed in Part 2Z (§6Z); the network error was seen only under synthetic CPU starvation · `test_concurrency.TestConcurrentWithdrawLocks`, `test_null_dates`, `test_hold_payment_race.TestDeadlockRetries`.
- O-11 **COMPLETE**: one live or scheduled FX policy per scope and pair (activation refused, `SERIAL_ACTIVATION`); `fx.choose_policy` raises `FX_POLICY_AMBIGUOUS` for two in one scope · `test_fx_snapshot.TestOnePolicyPerPair`, unit `TestChoosePolicy`.
- O-12 **COMPLETE**: a dated manual rate bridges a stale or missing provider rate (policy margin on top), entered per hotel with `fx.manual_rate` (p70), audited, recorded as `bridged_from`, WARN `fx_bridged` · unit `TestManualBridge`/`TestFxBridged`, `test_fx_snapshot.TestManualBridge`, `test_system_status`, e2e `fx-manual-rate`.

## 6F1. Audit Part 2F-1 (2026-10-01)

- P1-4 **COMPLETE**: one lock order (ADR-066 "Locks"): `reissue_link` / `cancel_link` lock the link first, `addons.apply` and `acknowledge_guest_change` the booking, then the room under its lock, `create_booking` its quotes by name, `lock_expiry_money` reads the releases with a locking read; `resend_confirmation`, `acknowledge_guest_change`, `loyalty_adjust` retry a deadlock · `TestPaymentLinkLockOrder`, `TestLastRoomRace`, `TestDeadlockRetries`, sniffs in `test_post_booking_extras`, `test_commercial_flows`, `test_self_service_money`.
- 1b restarted Pending payment **COMPLETE**: `start_payment`'s reuse branch asks `open_attempt` (refused after the hold, deadline moved to the new attempt's, never back; ADR-062) · `TestPaymentLinkHold`, `TestRefusedAfterTheHold`.
- NEW-7 **COMPLETE**: the expiry job reads the due bookings lock-free; the PMS outbox is its own 5-minute job (`outbox_every_5_minutes`, `JOB_MAX_AGE` 20) with a 120 s budget and per-reservation order, `_each` survives a lost savepoint, `retry_outbox` takes only the latest message (ADR-015) · `TestAtomicExpiry`, `TestPmsDelivery`, `test_system_status`, `test_scheduler_smoke`, unit `test_system_checks`.
- P1-2 **COMPLETE**: a revival's duplicate is the guest's (profile, e-mail, phone), never the booker's (ADR-062 D4 c) · `TestPaidInTime`.

## 6H2. Audit Part 2H-2 (2026-10-01)

- 2H-1 leftover **COMPLETE**: the daily loyalty job commits the rows it matured before it asks for a guest (no deadlock with an adjustment or a redemption), and a lost savepoint (1305) rolls back whole, is logged, the job goes on · `TestExpiryLockOrder`, `TestExpiry`.
- O-20 **COMPLETE**: a cancelled or expired booking gives its Loyalty charges' share beyond its new cost back as points (`loyalty.return_points`, `pay.points_back`, pro rata half-up; a closed lot's share expires at once, ADR-071 §4), before the stay's own earning is reversed; a Loyalty payment is never refunded as money (`refund`, `refund_outside` refuse it) · unit `TestPointsOf`, `TestPointsBack`.
- O-24 **COMPLETE**: a hold that ran out of time (`Reservation.tex_hold_expired`, p62 for the old ones) is no cancellation and no sale in reports, the dashboard, the portfolio and the CRM; counted apart as `expired_holds` (ADR-059) · `TestExpiredHolds`, `test_portfolio`, `test_crm_segments`, `test_patches` p62.
- **Not done:** No Show, a lower price (O-19 credit) and a channel's cancellation do not give points back; a revived hold whose points were returned may fall to Action Required; O-19b (Money session): `gc._record_outside` meets the new refusal; old Loyalty payments in reconciliation are allocated by staff (D-14, no patch).

## 6F2. Audit Part 2F-2 (2026-10-01)

- O-15 **COMPLETE**: the hotel's payment method rules bind every booking: an unknown method is never stored, a method the hotel does not offer for the sale is refused (`pay.method_offered`), "Payment Link" is a staff method offered where a link can be paid, no rule or no method behaves as before; the checkout's fallback offers the card only (ADR-041) · `TestPaymentMethodRules`, node `checkout-fallback`.
- Y-9 **COMPLETE**: a disabled room type stays in its inventory pool (count and key: the first member by name, disabled included), is not sold, and disabling one says how many stays keep counting; p58 moves the rows kept under the slid key (ADR-048) · `TestPoolKeyWithDisabledMembers`, `test_patches` p58.
- Y-8 **COMPLETE**: a room the channel brings back is reactivated, not failed; a channel's booking is cancelled at the desk only with `channel.manage`, a reason and an audit (guest manage page refused), `retry_inbound` takes only the latest message; the screen hides Cancel without `channel.manage` and warns with it (ADR-039) · `TestChannelBookings`, e2e `channels`.


## 6G2. Audit Part 2G-2 (2026-10-01)

- G-70a **COMPLETE** (transport only; G-70b codes every guest refusal, catalogs, classification by code): a guest refusal's stable code (`kamra/tex/refusal_codes.py`) and guest-safe params reach the error body (`tex_code`, `tex_params`) through `@refusals.coded` on every guest endpoint; class codes on the existing guest refusals; the booking app reads `ApiError.code` / `params` and lets a code decide the kind (ADR-013 addendum) · unit `test_guest_refusal_codes`, `TestRefusalCodes`, node `refusal-codes`.
- O-8 **COMPLETE**: a link sells only the site's markets (`allowed_markets`, blank = every enabled market); a residents-only market (TR, p71) is booked on the web only by a guest whose declared country of residence or nationality is among its countries, refused and audited otherwise (after the quote locks, before any contract, night or guest lock); the Call Center books anyway with a reason, audited; checkout and the Call Center ask residence and nationality; editors for both settings (ADR-070, D-5) · unit `TestMarket`, `TestMarketIntegrity`, `test_patches` p71, node `market-residency`.
- G-55b **COMPLETE**: only a market refusal sends a linked search on without the link; the results say why; the browser funnel event `market_refused` (p72) and the analytics event count it (ADR-056 addendum, ADR-070) · `TestMarketLinks.test_a_refused_link_is_a_funnel_event`, `test_patches` p72, node `market-link`, e2e `booking`.

## 6K1. Audit Part 2K-1 (2026-10-01)

- LO-04 **COMPLETE**: a reused charge that a callback settled while the gateway made its new checkout never hands that checkout out; the start answers "already processed" (`PAYMENT_ALREADY_PROCESSED`), the reference recorded as before; a replayed `book` answers with no payment (ADR-066 addendum) · `TestAChargeSettledDuringItsCheckout`, `TestGuestPayment.test_the_answer_of_a_gateway_never_changes_a_charge_settled_meanwhile`.
- LO-05 **COMPLETE**: while the gateway reviews a Pending charge of the booking (its own or one of its links') or of the link, no other payment of it starts and the reviewed charge is never superseded (`PaymentBusy`, `PAYMENT_UNDER_REVIEW`; a replayed `book` answers with no payment; ADR-062 fraud review addendum) · `TestIyzicoFraudReview` (two tests), `TestAChargeSettledDuringItsCheckout`.
- LO-07 **COMPLETE**: queued late refunds run last in the 5-minute group, oldest first, at most 20 refunds asked a run (a charge with nothing to refund takes no place), none started after 90 s (`refund_queued(limit, budget_seconds)`) · `TestReconciliationStates` (three tests).
- LO-16 **COMPLETE**: `_flag` reads the charge with a locking read; a charge another request put in reconciliation meanwhile is flagged, audited and told once, its note gains the new cause · `TestRefundOutcomeOnABookingThatExpiredMeanwhile` (two connections).
- LO-17 **COMPLETE**: `payments.overpaid` leaves out the credit kept on purpose (the latest guest change settled "Credit on booking": each stores the whole excess); its text says a refund on its way counts as paid until the gateway answers · `TestOverpaidBookings`.
- LO-19 **COMPLETE**: staff re-verify commits each try before the next token is asked (`step_commit`, now before every next question, also for a Failed charge) · `TestAFailedTryLeavesNothing` (two lock sniffs).
- LO-21 **COMPLETE**: a gateway asked by a stored reference (`status_by_ref`, iyzico) gives a charge with none no place in the re-verify tick · `TestPaymentsVerifiedByTheJob`.
- LO-18 **COMPLETE**: "Not paid (checked with the bank)" closes a Pending charge of a gateway TEX cannot ask (the Virtual POS) Failed (`CLOSED_UNPAID`, `payment.refund`, a reason, audited `payment.closed_unpaid`); the pending-payments check stops counting it; payments screen action in six languages (ADR-062 addendum) · `TestUnverifiedPayments`.
- **Not done:** a duplicate capture of a settled charge is not audited apart in `complete` (LO-04's optional part); a review recorded after LO-05's check while a new charge starts still pays twice (flagged OVERPAID); money staff kept on the booking when closing a guest change's money ("Kept on the booking", G-93) still counts as overpaid; no e2e for the not-paid dialog.

## 6K2. Audit Part 2K-2 (2026-10-02)

D-12: loyalty is live at go-live (the default). LO-47: the owner's choice (a).

- LO-01 **COMPLETE** (O-19b): a lower price settled as a refund gives the points' share back as points first (`loyalty.give_back(limit=…)`, counted in the request's refunds), then cards; staff's "Refunded outside TEX" never records points as money (all points: refused; beside cash: the cash recorded, the points kept on the booking); the approve dialog says so (ADR-071 §4 amendment). Review round 1: under "refund automatically" the settlement carries `points_back` (given back when the change applies, no gateway), so the points' share is never a hotel refund nor the card's share points; the guest's page tells each part (`manage.settle.points`, `manage.done.points`). Review round 2: a points' share that does not come back by itself waits for staff · `TestPointsBack` (four tests), `TestLowerPrice` (three), unit `TestPointsOfALowerPrice`.
- LO-02 **COMPLETE**: points never pay a channel's booking (`redeem`, `allocate`, so `transfer`, refuse it); a channel's cancellation or a room it removes gives the points spent before back, then reverses the stays' earning (D-11, D-16) · `TestChannelBookings` (three tests: the room-removal path added in review round 1).
- LO-06 **COMPLETE**: a charge's burn row is found by the charge (the booking it was redeemed for, the burner wherever they are now; `tex_ledger_booking_type`, p73) · `TestPointsBack` (two tests), `test_patches` p73.
- LO-23 **COMPLETE**: a revival short of the points given back at its expiry says so in the staff note (the rule is kept), only when money is why it stays off (its rooms free, no other booking for the stay; review round 1) · `TestPointsBack` (two tests).
- LO-24 **COMPLETE**: the profile's stays tab marks an expired hold ("Hold expired") · `TestProfileStays`.
- LO-25 **COMPLETE**: a balance below zero is shown as points owed (`debt`), valued at zero · `TestPointsBack`.
- LO-26 **COMPLETE** (reachable: a past stay still Confirmed can be changed): an earning whose points had expired passes its expiry on; the new lot is settled at once (ADR-071 §6 amendment); the expired lot is read on the earning's own guest (review round 1) · `TestModification` (three tests).
- LO-47 **COMPLETE** (option a): a failing earning or reversal is undone alone under its savepoint, logged, and `loyalty.earnings` warns ("earn or take back"); the reservation's save is kept · `TestAnEarningNeverUndoesTheStay` (two tests), unit `test_system_checks`.
- **Not done:** the CRM "Redeem" button still shows on a channel's booking (the server refuses it); No Show still gives no points back (C-01); the points of a stay changed into the future stay Available (O-21's state rule).

## 6UX. Admin UX revision (2026-10-02)

The owner's brief: make the admin panel easier for the daily commercial work without a rewrite; the guest booking engine,
the pricing engine, the data model, permissions, audit and the draft → publish lifecycle are unchanged (ADR-072).

- Navigation by the work **COMPLETE**: Daily work (dashboard, reservations, new booking, call centre, Rates & availability,
  promotions) / Contracts & pricing (contracts, selling rules) / Guests & money / Reports / Setup & system; every route kept;
  in-page tabs show only the area's own pages (`shell/nav.ts`, `RULE_SLUGS`) · e2e `shell`, `entry-branding`.
- Hotel scope and unsaved work **COMPLETE**: the header names the hotel worked on, a switch is confirmed (toast, highlight)
  and an open record of the old hotel gives way to its list; unsaved edits are protected on in-app links, the hotel switch, the command
  palette and reload (`lib/unsaved.tsx`); the contract editor and the grid use it; Discard asks first · e2e
  `rates-availability`, `editor-edits`.
- Rates & availability **COMPLETE**: daily view (price, rooms left, sale), the scope in words (hotel, contract, market,
  currency, basis, On sale / Draft), select rooms × nights (drag, Shift, row and day headers), type a price or `+10%`, paste
  from a spreadsheet, Ctrl+C/Z/Y, the server's preview (each room's price before → after), one save to the draft or
  save & publish; close/open sale with its contract scope chosen in the confirmation, applied at once, Undo
  (`crs.ari_rate_changes`) · `test_grid_rate_changes` (6), unit `inventory-edits`, e2e `rates-availability` (3).
- Contracts **COMPLETE**: "Saved to the draft · not on sale until published" / what is on sale now; a new season from the
  contract on sale (Duplicate → "A new season", windows and every period and offer date a year on as one unsaved, listed,
  undoable edit); a period's prices, rules and boards copied from any period; occupancy and child rules read as sentences
  (free, % off, % more); the Price test keeps its party · unit `season-copy`, `shorthand`, e2e `contract-season` (3).
- Promotions **COMPLETE**: one workspace: what it gives, when it is booked and stayed, where it applies (warns while it
  applies to everything), advanced fields folded, back-to-front dates refused; "Check the price" prices one stay with and
  without the draft before it is activated (`policies.promotion_check`); "Create similar" makes a new draft (never a
  revision); the list says what each gives, covers and where it stands · `test_promotion_check` (5), unit `promotions`,
  e2e `promotion-workspace`.
- Finding a reservation **COMPLETE**: the list searches the header's hotel, "All my hotels (n)" is an explicit choice and
  is offered in one click when nothing is found; the channel's own booking number is searched and shown; the breadcrumb
  returns to the list as it was left; the palette finds a reservation in every hotel · `test_reservation_search`, e2e
  `reservation-find`.
- Shorthand reads the Turkish percentage form (`%30`, `+%10`, `-%30`) · unit `shorthand`.

Measured (one-off spec run on the base build and on this branch, same fixtures; `e2e/flows/budget.ts` counts pointer
presses, a `<select>` as 2, a field filled without focus as 1, modal dialogs; values typed counted by the spec). Task time
was not measured.

| Task | Before: clicks / dialogs / values typed | After |
|---|---|---|
| 1. +10 % for two rooms on five nights, saved to the draft | 6 / 1 / 3 (no per-room preview) | 5 / 0 / 1 (server preview) |
| 2. July takes May's room prices and child rules, then Standard → 85 | 7 / 0 / 6 | 7 / 0 / 1 |
| 3a. 15 % for DE, July stays, booked until 31 May | 17 / 3 / 5 | 17 / 3 / 5 |
| 3b. The same for the UK | 18 / 3 / 5 (made again) | 7 / 1 / 1 ("Create similar") |
| 4. Next season's contract from the one on sale | 25 / 2 / 12 | 4 / 1 / 0 |
| 5. Change the 3rd adult and a child rule, sample price after each | 12 / 0 / 4 | 10 / 0 / 3 |

Task 2's typed values grow with the rooms and rules of a period before, and stay one after. A reservation of another hotel
takes one click more than before by design (the list no longer searches every hotel silently; the palette does).

- Follow-up (2026-10-02) **COMPLETE**:
  - the grid's daily view has a "Sell price" row under each contract price: one night for the party chosen, the base
    board and the rate plan named (else the contract's first, said back), priced by the engine with the markups,
    automatic promotions, FX, taxes and mandatory extras in force now, as the search prices an offer; the promotions
    in it or why the night is not sold (`crs.ari_sell_prices`) · `test_grid_sell_prices` (5), e2e `rates-availability`;
  - the browser's Back and Forward buttons ask before unsaved edits are lost (`lib/backGuard.ts`) · e2e `back-guard`;
  - the dashboard's arrivals and departures today open the list of exactly those reservations
    (`crs.reservations(arriving, departing)`, one status definition) · `test_dashboard_links`, e2e `dashboard-links`.
- **Not done:** bundles not rebuilt (2Z). The sell price row assumes no coupon code and no children; a mandatory
  limited extra sold out still shows a price there (the search refuses the night).
- Local testing fixes (2026-10-02) **COMPLETE**:
  - Windows and macOS: every Contracts & pricing page broke in `npm run dev` ("does not provide an export named
    'ExplainLadderView'"): `ExplainLadder.tsx` and `explainLadder.ts` share a name on disks that ignore case, so the
    import without an extension loaded the pure module. The view is now `ExplainLadderView.tsx` · unit `file-names`
    (fails when two modules in a folder differ only in case or extension); reproduced on Linux with a case alias:
    17 of the revenue manager's 55 menu pages (every page under /tex/rates) broke before, none after;
  - a role without `price.view_cost` (call centre) was offered the markups and contract formulas, which the server
    refuses to it (403): the side navigation and the rules' tabs hide them, and Selling rules opens on the first rule
    the role may read (`ruleVisible`, `areaEntry`; server unchanged) · unit `nav`; every menu page opened as the five
    demo roles: no broken screen, no failed call.

## 6K3. Audit Part 2K-3 (2026-10-02)

No owner decision was needed. LO-11: refused (TEX never e-mails a channel's booking), the card's first option.

- LO-03 **COMPLETE**: a disabled room type is not sold anywhere: ARI sends its days closed and disabling or enabling it queues its mappings' sync (a Room Type `on_update` hook); a quote of an offer key made before, a booking of a quote made before, and a staff change into it are refused (`ROOM_NOT_SOLD`, read as "search again" by the booking app); its own stays still change, and it keeps counting in its pool (ADR-048 and ADR-039 addenda). Review round 1: a channel's booking of a disabled type (or a room moved or brought back into one, round 2) is accepted with a warning; the modify drawer offers only the types still sold · `TestADisabledRoomTypeIsNotSold` (four tests), `TestAri`, `TestChannelBookings`, node `refusal-codes`.
- LO-13 **COMPLETE**: the channel is named by its connection's label (`channel_of` → `label`) in the "Sold by …" refusal, the cancel dialog and the reservation; the audit keeps the id · `TestChannelBookings`.
- LO-11 **COMPLETE**: `resend_confirmation` refuses a channel's booking before any manage token is minted; the staff booking view carries `channel_booking` and both detail screens hide the resend button · `TestChannelBookings`.
- LO-09 **COMPLETE**: the revival's duplicate check reads the guest's stays at the hotel with a locking read of Reservation alone, by `Reservation(guest, property)` (forced when present), under the booking's lock; a stay live now is its booking's (a booking revived meanwhile counts, round 2); a booking being made for the guest meanwhile waits or deadlocks and is retried (ADR-062 D4 c, ADR-066) · `TestLastRoomRace` (two two-connection tests; the plan's index).
- LO-15 **COMPLETE**: the p58 and p61 tests assert each count against its own floor · `test_patches`.
- **Not done:** the guest's manage view still says a channel's booking can be cancelled and changed, which the server refuses (LO-12, Stage 3); the "Sold by …" refusal has no guest code yet (G-70b codes it, `CHANNEL_BOOKING`); a channel mapping of a disabled type can still be saved enabled (it sends closed days); LO-09 does not find a duplicate made on a profile created after the read view began (another e-mail on the same phone: the CRM shows it as a possible duplicate).

## 6G3. Audit Part 2G-3 (2026-10-02)

No owner decision was needed. LO-30 (optional here) is left to batch 7 (2K-5), as the HANDOFF allows.

- G-71 **COMPLETE**: no guest answer names the contract, its version, its payload hash, the market or the channel: `public.search`, `quote` and `quote_rooms` strip an offer's `contract`/`contract_code`/`version`/`market` and a room quote's `contract` block, `request` and `engine_version` (after the localizer), keep promotions by name and amount and reasons by code (never the engine's text); an extra refused for a market, channel or room type says "not available"; `book` and `booking_status` drop `market`/`channel` (after the payment started with them), `site` drops `default_market`; staff answers, the stored quote and snapshots keep everything; the signed offer key is a documented residual (ADR-026 addendum, ADR-009 note) · `TestPublicBooking.test_guest_answers_name_no_contract` (a recursive scan of seven guest answers, a refusal included; staff keep them).
- G-70b **COMPLETE**: every refusal a guest can meet carries a stable code (HANDOFF_STAGE3 §5f: `public.py` and the service functions it reaches; `with_code` for refusals raised without `frappe.throw`; `quote_refusal` / `link_refusal` answer coded), the market and the version id are no longer told to a guest, a room cancelled meanwhile is `ROOM_NOT_ACTIVE`, a forged sandbox signature a coded 417; the booking app classifies by code only (`lib/refusals.ts`: kinds `payment_method`, `retry`, `hold_expired` added) and shows `refusal.<CODE>` with its params on every page; 99 texts in six catalogs; `npm run i18n:tex` checks the booking catalogs (its root was wrong) (ADR-013 addendum) · unit `test_guest_refusal_codes` (AST check of the guest paths, `CODES` = en.json), `TestRefusalCodes` (six new tests), `TestChannelBookings`, `TestExtrasCapacity`, `TestRefusedAfterTheHold`, `TestNoLockHeldThroughTheGateway`, `TestSelfService`, node `refusal-codes`, e2e `guest-refusals`.
- Review round 1 (one reviewer): a guest's change that cannot be sold no longer tells the engine's reasons (S1); a guest's error body names no market and an extra's refusal never its market, channel or room type (S2); the audit of a refusal a guest met keeps the staff detail (S2); a transfer too late says pay by card, a reviewed payment is not "try again" · `TestSelfService.test_a_change_the_engine_refuses_never_tells_the_guest_its_reasons`, `TestMarketIntegrity.test_a_guest_error_body_names_no_market`, `TestRefusalReview.test_a_refusal_a_guest_met_keeps_the_staff_detail_in_its_audit`, unit `TestGuestReason`.
- LO-12 **COMPLETE**: the manage view of a channel's booking answers `can_change` and `can_cancel` false and `sold_by {label}` (the channel's label, never its id; not `channel`, which G-71 keeps out); the page offers no change, cancel or extras and says where to change it · `TestSelfService.test_the_manage_view_of_a_channels_booking_offers_no_change_or_cancel`, node `manage-actions`.
- **Not done:** the basket's `problem_code` (§5b; the app does not read `rooms[].problem`); the room and extra names in SOLD_OUT / EXTRA_SOLD_OUT params are the hotel's own, not localised; a misconfigured extra (tax policy, ambiguous price) is an uncoded 500 on the add-extras dialog; a paid guest change that fails when applied keeps the guest's text in its request's error (staff see the engine's reasons by proposing it again); `channel_of` names a connection without a label by its id (the label is required: only a direct database write leaves it blank); the market codes keep the kinds G-55b gave them (no separate "market" kind: the search and checkout act on the code); an extra's own refusal reasons in a quote stay text (`lib/extras.ts` parses capacity reasons; an engine `reason_code` is a later pricing change); a malformed rooms JSON or a non-numeric child age in a search is still a 500, not a refusal; the manage page may still offer to pay a channel's booking's balance online (`can_pay_online` follows the hotel's card rules: an owner question, not LO-12's); LO-30 (batch 7).

## 6K4. Audit Part 2K-4 (2026-10-02)

D-13 answered no: the UTC+7 hotels (Cam Ranh, Phuket) are not in wave 1. O-6 is not opened and LO-37 is deferred with
C-05 (a documented limitation).

- LO-08 **COMPLETE**: the 5-minute cron entry `outbox_every_5_minutes` only queues `scheduler.deliver_outbox` on the RQ
  `long` queue (job id `tex_pms_outbox`, deduplicated: one still queued or running is not queued again; 300 s limit), so a
  worker of the default queue never runs a slow PMS ahead of the holds, payments and links; `deploy/tex-local` runs a
  worker for `short,default` and one for `long` (Procfile, `setup-local.sh`; frappe_docker has `queue-long`); System status
  names a TEX queue no running worker listens on (`queue_unserved`, six staff catalogs) (ADR-015 addendum) · unit
  `test_scheduler_queues` (three), `test_system_checks`, `test_scheduler_smoke` (the long worker stubbed: setup only),
  `test_system_status`. Review round 1: the delivery still waiting in its queue past its limit is `job_waiting` (the RQ
  job's own state: no worker for `long`, or one busy with a long job); `short` is watched too (guest changes, refusal
  audits); `queue_unserved` names any queue · unit `TestQueueProbe` (two), `test_a_queued_job_no_worker_takes_is_late`.
- LO-10 **COMPLETE**: a claim reads only the first undelivered message of each reservation and connection that is due and
  free, oldest first, at most the round's cap (`NOT EXISTS` an earlier Pending or Failed one, index
  `tex_outbox_ref_order`, p74); order and the conditional claim are unchanged (ADR-015 addendum) ·
  `TestPmsDelivery.test_a_round_reads_at_most_its_cap_however_many_wait_in_back_off` (2,000 in back-off, a SQL sniff),
  the order tests, `test_patches` p74.
- LO-28 **COMPLETE**: the hotel view of the audit log leaves out, in its query, the events of every record whose own trail
  refuses the viewer: payments without `payment.view`, stays and bookings without `reservation.view`, a commercial policy
  without what its API reads it with, and cost as before (`admin._trail_caps`, one rule with `_require_trail`) ·
  `TestTrailByReference.test_a_hotels_trail_leaves_out_payments_stays_and_policies_its_viewer_may_not_read` (`limit=1`
  still pages). Review round 1: a guest's profile, loyalty ledger and abandoned bookings need `crm.view` (there and in the
  record's own trail) · `test_a_hotels_trail_leaves_out_guest_records_without_crm_view`.
- LO-39 **COMPLETE**: `fx_rates` names who entered a manual rate only to holders of `fx.manual_rate` or `settings.admin` at
  its hotel (a rate of every hotel: at one of theirs) and to platform administrators; the audit trail keeps it ·
  `TestManualBridge.test_who_entered_a_manual_rate_is_shown_only_to_who_manages_rates`.
- LO-37 **DEFERRED** (D-13 = no): a MANUAL-mode pair (VND) still shows WARN `fx_bridged`; it returns with O-6.
- LO-22 **COMPLETE**: `TEX Payment Transaction.last_reverified_at` (p75, sync only) is written for each charge the job
  asks, whatever the answer; within an urgency the least recently asked goes first, one never asked before any (ADR-066
  addendum) · `TestPaymentsVerifiedByTheJob.test_more_candidates_than_a_tick_asks_are_each_asked_within_two_ticks`, the
  urgency tests, `test_patches` p75. Review round 1: a charge whose deadline comes before the next tick is its own first
  group, nearest first, however recently asked; the write is guarded like the question ·
  `test_a_charge_whose_deadline_comes_before_the_next_tick_is_asked_first_however_recently_asked`.
- LO-20 **COMPLETE** (verified first: the card was not re-verified): a gated account's `settled_while_gated` audit is
  written once per charge and site day for a question about it (a callback, a re-verification: `provider_for(question=True)`);
  a refund is written every time (review round 1) (ADR-042 addendum) ·
  `TestGoLivePaymentsReview.test_a_gated_accounts_charge_the_job_keeps_asking_is_on_record_once_a_day`,
  `test_a_refund_on_a_gated_account_is_on_record_however_often_its_charge_was_asked`.
- LO-48 **COMPLETE**: stored counts are read as Decimal whole numbers (`money.whole_number`, as `loyalty.extra_units`): an
  old snapshot's extra quantity that is not whole is refused by name, never cut; the backfill leaves such a stay out and
  logs it ("TEX job extras backfill …"), the others still hold their units; the localised quote keeps a line's own text
  when its nights are not whole; a count of 18 digits or more is none (review round 1) · unit `test_whole_units` (six),
  `TestExtrasAdministration.test_a_stay_whose_old_snapshot_has_no_whole_quantity_is_left_out_of_the_backfill`.
- **Not done:** a delivery that a worker started but never finishes is not watched apart (RQ ends it at its 300 s limit;
  the late PMS messages show it); other `long` jobs (Frappe backups, imports) can still delay the outbox on a
  one-`long`-worker deploy (then `job_waiting` says so); a stay whose old quantity is not whole is logged on each daily
  backfill until its check-out;
  a settle call without a charge is audited each time; staff re-verification does not write `last_reverified_at`; the
  GO_LIVE_READINESS worker setup is 2Z's docs refresh.

## 6K5. Audit Part 2K-5 (2026-10-02)

No owner decision was needed. LO-30 (left to this batch by Part 2G-3) is done here.

- LO-35 **COMPLETE**: a fixed deposit is named once per booking and policy, as the server takes it (`deposit_shares`):
  at checkout, where two rooms or more carry a FIXED policy, the first says "for the whole booking", the others that it
  is taken with that room; a room alone with its policy reads as on its own (review: the other rooms pay their own
  deposit) (`policy.bookingPaymentTerms`); a search of several rooms says "for the whole booking"; two keys in six
  booking catalogs (ADR-067 note) · node `booking-deposit` (four).
- LO-14 **COMPLETE**: a basket that could not be read offers no guessed method: the payment step says the options could
  not be loaded and why (a rate limit asks to wait, a coded refusal is told in its own words, else the connection and
  that nothing is booked or charged), and offers "Try again" (`methods.checkoutChoices`, `basketFailureText`; while it
  is not read yet the card stays as before) · node `checkout-fallback` (three new; the existing two unchanged), e2e
  `booking` (desktop: the alert and Try again).
- LO-32 **COMPLETE**: a re-quote (O-30) is compared with the last quote the guest has seen the price of, per room
  (kept in the flow through an extras change, dropped when the room is chosen again; a quote whose price is a change
  not yet accepted does not replace it, "OK, continue" does: review round 2), else with the search's offer and the
  server's flag (`lib/priceChange.ts`). With a quote seen the server's `price_changed`/`previous_total` are not used
  (they compare with the search: review BLOCKER); the totals are compared, extras included, so an accepted change is
  not announced again and a new price of an extra or one back to the search's is; where the two quotes add other
  extras (the guest changed them, or the new quote refuses one, which has its own notice) the room's own price is.
  The notice says which ("Room price was …" or "The total was …", one key in six booking catalogs) and focuses
  again when quotes made again find a change still not accepted · node `price-change` (seven), e2e `booking`
  (desktop: the server's flag, an extra added after, a refused extra, a change found on the extras step).
- LO-33 **COMPLETE**: the price-change notice focuses itself and scrolls into view when it appears · e2e `booking`
  (mobile).
- LO-31 **COMPLETE** (verified first): a widget whose site changes drops the old site's name with its theme; the modal
  says "Booking" until the new name arrives · e2e `widget`.
- LO-49 **COMPLETE** (each nit verified in code first; no review text beyond the card's line exists):
  - an analytics id is stripped exactly as the server strips it (Python's whitespace set) · node `analytics-ids`;
  - "?" opens the Call Center help with Ctrl or AltGr too, never with ⌘ · node `callcenter-shortcuts`;
  - Turkish-F: ı and İ are the I key on both Turkish layouts; a letter with a diacritic is its base letter only on that
    letter's key (Mac ⌥C types ç on C), else none, so Alt+ı and Alt+ü run no other letter's shortcut; on a Mac,
    Option types its own layer (⌥⇧S "Í"), so the Call Center takes the letter typed or the physical key there, as
    before (review) · node `keys`, `callcenter-shortcuts`;
  - the admin form finds an analytics id blank as the server strips it (review) · node `analytics-ids`;
  - the widget unlocks the host page on its dialog's own close event · e2e `widget`;
  - on a Mac the shortcuts help says that ⌃⌥ is VoiceOver's key and ⌥+letter outside a field still works (no logic
    change); six staff catalogs · e2e `crs` (Mac and Windows).
- LO-30 **COMPLETE**: back from the gateway the payment-link page shows no address with its token: the tab keeps it for
  the charge, the return is `/pay` with no fragment (ADR-046 addendum) · e2e `pay-link`.
- **Not done:** bundles not rebuilt (2Z); the checkout's deposit text names no per-room share (the server's
  `due_now` per method gives the amount; a first room whose total is below the deposit leaves the rest to the next
  room, which "taken with room 1" does not say); Turkish-F letters other than ı/İ are no letter shortcut at all (the
  page's buttons and the other keys stay); on a Mac Turkish-F, ⌥+letter is the physical key's, as before LO-49 (the
  Option layer names no letter); a basket refused as expired offers Try again, not the expired flow's "Refresh
  prices"; a guest who leaves the price notice unaccepted for 25 minutes and books is stopped once more by the same
  notice (focused again), and the next submit books.

## 6K6. Audit Part 2K-6 (2026-10-03)

No owner decision was needed. Batches F (staff frontend) and G (tests, guards and tooling) of HANDOFF_LEFTOVERS §2, in
one PR. Each card was verified in code first.

- LO-34 **COMPLETE**: the CRS booking summary shows no "Due now" while the current method's summary loads (the
  payment panel and the Call Center already did, O-29) · e2e `crs-actions` (the summary held after a method change).
- LO-38 **COMPLETE**: a reservation's exchange-rate hint adds "bridging {provider}" when a manual rate stood in for a
  stale or missing provider rate (`bridged_from`, ADR-069 manual rate bridge); the hint is
  `reservations/lib/fxHint.ts`; one key in six staff catalogs · node `fx-hint`.
- LO-40 **COMPLETE** (was not re-verified; verified STILL OPEN: the note only): the occupancy ladder's sample parties
  count infants as `occupancy.check_capacity` does, from the version's `infants_count_as_children` and
  `infants_count_as_occupants` (`workspace/occupancy.ts` `partyOptions`); with both on (the default) the parties are
  the same as before; the note says the parties count that way (six catalogs) · node `workspace-occupancy`.
- LO-45 **COMPLETE**: `minusAmount` and `isPositiveAmount` take any number of decimals (VND gave ".1000" and an
  invalid pattern; KWD's third digit was refused); the bank-transfer, refund, allocate, transfer, manual-payment and
  payment-link dialogs pass their currency's `minorUnits` to the input and the checks; the pure helpers are
  `payments/amounts.ts` (`lib.ts` re-exports them); review: both apps' minor-unit tables say what the server's
  `MINOR_UNITS` says (CLP and ISK were 0 on the screens, 2 on the server, so a dialog refused the server's own
  amount; node `minor-units` reads `money.py`), and with no decimals the input takes no point (`ui/decimal.ts`)
  · node `payment-amounts` (EUR, VND, KWD), `minor-units`, `decimal-input`.
- LO-42(a) **COMPLETE** (was not re-verified; no written review text exists, each nit was verified in code): the
  markup priority help says the higher priority wins within one scope, stacking rules apply lowest first and two
  replacing rules of one scope and priority whose stays meet cannot both be live (G-53); the promotion kind MEMBER
  reads "Member (label only)" and both kind selects (promotion policy, contract offer) say a kind never limits who
  gets it (G-57); six rates catalogs · node `rates-copy`.
- LO-27 **COMPLETE** (test only): `crm-abandoned.spec.ts` checks the abandoned list's contact links on rows in the
  server's shape: `sms:` and `wa.me` (opened apart, no referrer, international numbers only) for the channels the
  guest agreed to, no `tel:` link on any row (O-26), no contact on an anonymous row; red against the page made to
  offer a call.
- LO-46 **COMPLETE** (was not re-verified; verified STILL OPEN, the docstring listed the gaps): the nullable-date
  guard reads the third and fourth positional filters (Frappe's `execute(fields, filters, or_filters)`, swapped when
  the second is filters-shaped), scopes a query-builder `isnull()`/`notnull()` exemption to its own statement, and
  lists (UNREADABLE) a call with a run-time doctype whose filters compare a nullable date with no `is` (review: a
  call whose doctype is in a `**` mapping is named `api(**)`, not a crash) · unit `test_nullable_date_filters` (two
  probe tests, red before; the repository has no such call, the guard stays green).
- LO-36 **COMPLETE**: the concurrency cleanup deletes each child table's rows by parent before the versions and the
  property's records (`_delete_children`); before, seven child tables of a version stayed on the site · integration
  `test_concurrency.TestCleanupLeavesNoOrphans` (red with exactly those seven).
- LO-44 **COMPLETE** (card corrected: nine specs were behind their JSON, not only TEX Payment Link, and
  TEX Payment Transaction's spec lacked `last_reverified_at`, added to the JSON alone by Part 2K-4): the specs carry
  each JSON's `modified` stamp and that field · unit `test_doctype_specs` (no bench: every spec is stamped at least as
  late as its JSON and generates the JSON's content; red for both before).
- LO-29 **COMPLETE**: p63 also masks a child table's Password fields in the rows a Version keeps whole (`added`,
  `removed`; Frappe's `as_dict`). Latent: no child table has a Password field today, so p63 is not re-run. The live
  Version hook needs no change: Frappe stores a Password field's dummy value before the Version is made
  (`_save_passwords`, children too), and `mask_version` masks withheld fields, none in a child table · integration
  `test_patches.TestP63` (a synthetic child Password field, a Custom Field row; red before).
- LO-41 **COMPLETE**: of one group on equal priority the lowest id applies; a TEX Promotion's `PRM-` id now compares by its number
  (`promotions.id_order`), so the older promotion still wins from PRM-100000 on; a contract offer's code compares as
  text, as before, also when it reads `PRM-…` (review N3), and every id up to PRM-99999 keeps its text order
  (ADR-068 addendum) · unit `test_promotions_extras`; `test_main_parity` unchanged (8/8).
- LO-42(b) **COMPLETE** (was not re-verified; each nit verified in code; ADR-068 addendum):
  - archiving a scheduled markup revision that hands a window back to the revision it replaced runs the tie check
    on that window only (from the reopened markup's old end to its new one; review S1: not its whole window,
    open-ended) and is refused naming the revision, the markup it would reopen and the one it would tie with;
    archive takes activation's serialising lock · integration `test_commercial_flows.TestMarkupTies` (red: the
    archive went through; review S1: red, a markup scheduled after the new end was taken for a tie);
  - the tie check's locking read matches the hotel as is (blank: NULL or '') and reads in no order, so it is a range
    of `tex_markup_prop_status` (property, tex_status) and locks that hotel's markups only (`tie_candidates`) · EXPLAIN
    test, for a hotel and for none (red: PRIMARY, no possible key);
  - a test for a tie on a scheduled activation (inside a live markup's window refused, after its end allowed); test
    only, red with the check made to compare with now;
  - the contract page's publish check has its own per-user budget (`HEAVY_LIMITS["publish"]`, 20 a minute, 2 at
    once), not the workspace's live checks' (60, 3): `validate_version(purpose="publish")` with no unsaved data;
    with data a call is a live check whatever it says · integration `test_pricing_workspace_api.TestHeavyReads`.
- LO-43 **COMPLETE** (was not re-verified; verified STILL OPEN): a grid rate edit (one cell or several) on a room with
  no price of its own in a period it touches is refused "<room> has no price in period <code>; add one first." (the
  engine's `Unsellable` NO_ROOM_PRICE was raised raw); another `Unsellable` keeps its own message · integration
  `test_inventory.TestGridRates`.
- **Not done:** bundles not rebuilt (2Z); the nullable-date guard still lists, not reads, filters it cannot build
  statically (from a parameter, a helper or a comprehension), as before; a payments dialog in a currency TEX has no
  minor units for takes two decimals (`minorUnits`), and CLP and ISK are 2 on the server (ISO 4217 says 0: a
  money-engine change, not made); the occupancy ladder's sample parties walk every band combination of a party size
  that does not fit (inside a memo; about 20 ms for five bands, 400 ms for ten); the promotion kind stays a label,
  no member-only price exists (G-57).

## 6Z. Audit Part 2Z — release hygiene (2026-10-03)

The owner decided two things on 2026-10-03: the Frappe v16.36.1 upgrade is its own PR after 2Z (2Z-F), and the
committed build carries no commit stamp. Cards: `HANDOFF_RELEASE.md` (each re-verified first); ADR-073.

- NEW-4 **COMPLETE**: the committed bundles equal a fresh build of the source, and CI enforces it.
  - A build carries a commit only when told (`TEX_BUILD_COMMIT`; ADR-060 amended): a build with git and one without
    differed in 163 files, now in none.
  - Tailwind reads `src/` only: a class-like string in an e2e file changed 93 files, now none. The DOM test pages use
    `tests/dom/harness.css`; test:dom 42/42.
  - The root build runs `npm ci` (it had rewritten `frontend/package-lock.json`); `/yarn.lock` and
    `/kamra/public/node_modules` are ignored.
  - Two CI checks: the frontend job's fresh build leaves `kamra/public` unchanged (red before: 354 porcelain lines),
    and a bench install leaves `apps/kamra` clean (red before, on a clone: `?? yarn.lock`, `?? kamra/public/node_modules`,
    `M frontend/package-lock.json` and the bundle drift).
  - The bundles were rebuilt as the last code commit (178 added, 173 removed, 3 changed; a second build is identical;
    Node 22 locally and Node 24 in CI give the same files).
- Frappe OAuth dynamic client registration **COMPLETE**:
  - switched off at install (`setup.close_oauth_registration`, written with `get_single().save()`) and by p76, once (an
    administrator's later choice stands); p76 prints how many clients a guest registered, never a name;
  - CI's fresh-install check asserts it is off;
  - tests: integration `test_security_hygiene.TestFrappeOAuthRegistrationClosed` (red before: a guest's
    `register_client` created a client) and `test_patches` (p76).
- CI pins **COMPLETE**:
  - Semgrep's rules (frappe/semgrep-rules, semgrep/semgrep-rules `python/lang/correctness`) and CLI (1.179.0) are pinned
    and fetched outside the workspace, with a Monday drift run on the newest rules; the pinned rules run the same 35
    rules as the registry pack, with 0 findings;
  - payments is pinned at 86fefa9 and frappe-bench at 5.31.0 in CI and the supply-chain check, as in the Dockerfile;
  - CI, Linters and Supply chain also run on pushes to the base;
  - test: unit `test_pins` (red before: 3 of 4).
- channels.spec flake **COMPLETE** (it was not the network; the §6D2 explanation is corrected):
  - The MappingDrawer stayed mounted and reset its form in a passive effect after opening, so its first frame showed
    the last mapping's codes and the typed code was lost. The connection drawer had the same pattern.
  - Both drawers are now mounted per opening.
  - The siblings were swept:
    - the payment account drawer, the payment rule dialog and the guest edit drawer are mounted per opening;
    - the reservation modify drawer, the multi-select picker and the segment editor reset in a layout effect;
    - ChildAgesDrawer was not affected.
  - e2e first-frame checks: `channels.spec` (red: "RMUS76OPQ5G", no hotel) and the new `payments-setup.spec` (red:
    "Bank transfer").
  - `trackErrors` logs a request the browser could not complete, with its transport error (diagnostics only).
- Docs **COMPLETE**:
  - every stale statement of HANDOFF_RELEASE §6, re-verified against today's code and corrected in
    IMPLEMENTATION_STATUS, GO_LIVE_READINESS, FINAL_GAP_AUDIT, MIGRATION_PLAN (p47, p49–p76) and DEV_ENVIRONMENT;
  - the bundle workflow in the PR template, CONTRIBUTING, README, RELEASING, `.gitleaks.toml` and NATIVE.md;
  - SECURITY_MODEL's threat table; HANDOFF.md rewritten;
  - G-99 (the `payload_hash` LOW gap) recorded.
- Frappe upgrade **NOT STARTED** (owner: its own PR after 2Z; `HANDOFF_RELEASE.md` §2).
- **Not done:**
  - the legacy MCP `/mcp/oauth/register` still lets a guest register a client without a rate limit (its redirects are
    limited to claude.ai and loopback; LOW, for the owner);
  - the GitHub actions' Node 20 deprecation warnings (bump to the current majors, optional);
  - contrast is not re-measured (R-51);
  - about thirty more dialogs reset their form in a passive effect after they open and show the last session's values
    for one frame (review S2: e.g. the payment refund dialog, `payments/detail/Actions.tsx` `RefundDialog`, whose amount
    typed in that frame would be replaced by the full refundable amount; the user invite and contract dialogs; a scan of
    `useEffect` resets keyed on `open` lists them). LOW: one frame. Proposed: one fix in the design system's
    Dialog/Drawer (ADR-073), not a sweep of each.
