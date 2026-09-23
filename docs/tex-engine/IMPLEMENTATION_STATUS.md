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

## 1. Verified test and build state (re-run 2026-09-23 on the dev bench)

| Check | Command | Result |
|---|---|---|
| TEX pure unit tests | `python -m pytest kamra/tex/tests/unit -q` | **138 passed** |
| TEX integration tests (7 modules) | `bench --site test.localhost run-tests --module kamra.tex.tests.integration.<m>` | **73 OK**: admin_markets 3, commercial_flows 16, concurrency 1, critical_journey 9, migrations_notify 5, public_booking 17, security_regressions 22 |
| Browser E2E (Playwright) | `cd frontend && npx playwright test -c e2e` | **13 passed**: critical-journey (R-58, 19 steps), contract-admin, crs ×2, shell, booking ×4 desktop + ×4 mobile (Pixel 7) |
| Upstream Kamra suites | `run_baseline.sh` | eval harness **76/76**, front-desk journey **13/13**, banquet **101 OK** |
| TypeScript / build / i18n parity | `npx tsc -b`, `npm run build`, `npm run i18n:tex` | clean; the rebuild is identical to the committed bundles |
| Lint / static security | `ruff check kamra/tex kamra/patches/tex`; semgrep (Frappe rules, ERROR) | clean / 0 findings |

**Coverage gaps.** Green tests do not prove absence of the defects below. The audit reproduced
several critical defects with probes and scratch tests that the suite does not contain yet
(see FINAL_GAP_AUDIT §1).

**CI.** `.github/workflows/ci.yml` runs all of the above including Playwright. It has never
run on GitHub, because the repository has no base branch (BLOCKED, owner).

## 2. Summary

| Status | Count | Requirements |
|---|---|---|
| COMPLETE | 10 | R-06, R-10, R-26, R-38, R-45, R-46, R-57, R-58, R-60 (process), R-61 (process) |
| PARTIAL | 52 | all others; the gaps are listed per row |
| NOT STARTED | 0 whole requirements | sub-items not started: CRM Campaigns (R-35/R-37), channel-manager / SMS / WhatsApp adapters (R-44), booking-window restriction (R-16), bundled extras (R-19), package coupons (R-20), enterprise dashboard (R-47) |
| BLOCKED | 0 whole requirements | blocked sub-items: production certification of iyzico / Sipay / NestPay (R-40, merchant credentials); outgoing e-mail delivery (SMTP account); PR + CI on GitHub (base branch) |

**Open gaps by severity:** 5 Critical, 16 High, 35 Medium, 7 Low (+3 blocked items). G-01 to G-04
were fixed after the audit (FINAL_GAP_AUDIT, "Resolved since the audit"). Details are in
FINAL_GAP_AUDIT. Critical means wrong money or a security hole.

## 3. Phases (derived from the requirement rows below)

| Phase | Status | Why |
|---|---|---|
| 0 Audit + docs | COMPLETE | spec, architecture, ADR-001…026, this audit |
| 1 Foundation (shell, nav, design system, hide PMS) | PARTIAL | TEX shell and design system work; the legacy booking engine no longer sells TEX hotels (G-03 fixed); the legacy night audit leaves TEX-sold stays alone (G-04 fixed); the legacy PMS SPA is still reachable for TEX users (G-16) |
| 2 Commercial data model | PARTIAL | 59 DocTypes + patches p01–p09; extras/taxes are not versioned (G-20) |
| 3 Pricing engine | PARTIAL | pure engine correct on every spec example; booking-level extras/coupons are multiplied per room, and coupon limits are not enforced (G-05…G-09) |
| 4 Contract admin | PARTIAL | editor, publish, price check work (E2E); an unsellable contract can hide others (G-17); cost is visible to agents (G-11) |
| 5 Rate/inventory grid | PARTIAL | grid + bulk edit exist; no backend/E2E tests, no copy period, rows are room types only (G-47) |
| 6 CRS | PARTIAL | works incl. multi-room; no destination/group inputs (G-40) |
| 7 Call Center | PARTIAL | keyboard-first flow tested; channel not bound to the agent (G-41) |
| 8 Booking + widget | PARTIAL | full flow tested desktop+mobile; custom domains not served (G-21), no inline widget mode (G-44) |
| 9 Payments | PARTIAL | sandbox end to end; token leak (G-10), allocation locking (G-14); production certification BLOCKED |
| 10 CRM | PARTIAL | guests, consent, segments, abandoned; 5 named segments not expressible (G-23), no loyalty admin UI (G-24) |
| 11 Self-service | PARTIAL | view/pay/change/cancel; no extras after booking (G-22), credit/refund policies do nothing (G-45) |
| 12 Reports | PARTIAL | production report; missing views/filters, margin does not reconcile (G-46) |
| 13 Hardening | PARTIAL | this audit; the Critical/High items in FINAL_GAP_AUDIT are open |

## 4. Requirements

| ID | Requirement | Status | Evidence (files · tests) | Gaps (→ FINAL_GAP_AUDIT) |
|---|---|---|---|---|
| R-01 | Source & identity | PARTIAL | AGPL notices, `NOTICE.md`, baseline 418ed1a in history; TEX shell branding | Legacy PMS SPA still reachable for TEX users (G-16); the legacy booking engine refuses TEX hotels and the legacy night audit leaves TEX stays alone (G-03, G-04 fixed, ADR-028). Login/tab/Desk still say "Kamra PMS" (G-60). Release/nightly workflows ship upstream Kamra images (G-61). |
| R-02 | Architecture principles | PARTIAL | `kamra/tex/pricing` has no frappe import (`TestPurity`); no import cycles; the frontend only formats decimal strings | Loyalty uses Float money fields (G-72). The legacy float pricing path remains only for hotels outside TEX (ADR-028; G-03 fixed). |
| R-03 | Pricing engine | PARTIAL | modular resolvers in `kamra/tex/pricing/*`; Decimal (`money.calc`); explanation trace · `test_engine.py`, `TestPayload` | Extras and tax rules are neither in the frozen payload nor effective-dated, so a quote is not reproducible as of its sale time (G-20). |
| R-04 | Contract management | PARTIAL | `api/contracts.py`, `commercial/contracts.py`, `screens/rates/contracts/*` · e2e `contract-admin` | A higher-priority contract whose sale/stay window does not apply hides lower/GLOBAL contracts (G-17). Contract cost readable with `price.view` (G-11). Header fields editable after publish (G-50). |
| R-05 | Versioning & snapshot | PARTIAL | immutable versions, frozen payload + hash verified on load (`tex_contract_version.py`, `revisions.py`) · `TestContractImmutability`, `test_payload_integrity_is_checked`, e2e | Snapshot keeps periods/rules by reference only; no explicit quote timestamp (G-73). (The REST lock bypass G-01 is fixed, `TestPriceLock`.) |
| R-06 | Base pricing modes | **COMPLETE** | `occupancy.py` PERSON/ROOM · `TestRoomBasis`, `TestPersonBasis`; basis select in `ContractDialogs.tsx` | — |
| R-07 | Occupancy formula engine | PARTIAL | slot model, combinations not hardcoded (`occupancy.py`, `contracts.parse_combination`) · spec examples reproduced (270; 2A+1C 250 vs 1A+1C 200) | Global/hotel/market policy rules do not cascade (single `_policy_for`) (G-30). Band-less position/combination rules silently outrank band rules incl. infant ×0; no publish warning (G-31). |
| R-08 | Child age engine | PARTIAL | integer months, DOB-at-arrival (`ages.py`) · `test_boundaries_in_months`, `TestChildrenAtBoundaries` (35/36, 83/84, 143/144 months) | Per-hotel/market bands untested; band gaps not detected at publish; no DOB input in UI (G-52). |
| R-09 | Rule hierarchy | PARTIAL | `Level` precedence; winning + overridden rules in the price check (`PreviewTab.tsx`) · markup/occupancy precedence tests, e2e asserts explanation | Policy cascade (G-30). Same-scope markup ties resolved silently. Markup explanation level ignores channel (G-53). |
| R-10 | Derived rooms | **COMPLETE** | `rooms.py` (derivation, cycle guard, absolute override) · `test_derived_rooms`, `test_base_change_propagates`, `test_absolute_override_wins_in_its_period`; `RatesTab.tsx` | — |
| R-11 | Stay periods | PARTIAL | unlimited periods, weekday/priority, grid bulk rate change into a draft | No copy period; no bulk edit of occupancy/child/board across periods; `apply_rate_change` untested (G-47). |
| R-12 | Sale vs stay date | PARTIAL | sale/stay windows, promotion booking-date/arrival/departure/LOS/through rules · `test_sale_date_outside_eb_window`, `TestEligibility` | Base rates/markups have no arrival/LOS/booking-date rules (G-54). Extras/taxes not effective-dated (G-20). |
| R-13 | Markets | PARTIAL | `resolve_market` never guesses; Settings → Markets · `test_admin_markets`, market tests | Booking app silently drops a refused market link; guest country not reconciled with pricing market (G-55). |
| R-14 | Contract vs selling price | PARTIAL | markup types/scopes/STACK; cost & margin stored · `TestMarkup` (1000+8%=1080) | Cost exposed to agents via get_version/price_matrix/ari_grid/policies (G-11). Markup values not validated (−100% → 0) (G-18). Margin % understated and untested (G-46). |
| R-15 | Currency engine | PARTIAL | FX modes, TCMB/ECB adapters, as-of rates, room-rate FX snapshot · `TestFx` (50+2%→51) | FX used for extras and fixed promotions not snapshotted; no cross-currency booking integration test (G-56). |
| R-16 | Restrictions | PARTIAL | stop-sell modes, LOS, CTA/CTD, release, advance; enforced on search/quote/book · `TestRestrictions` | No booking-window restriction; no hotel/market-level cells; modifications treat restrictions as warnings (incl. guest path); no integration test of enforcement (G-48). |
| R-17 | Inventory | PARTIAL | pools, allotments, oversell limit, manual adjustment, row locks · `test_concurrency` | Legacy `validate_type_capacity` blocks TEX oversell/pools; non-TEX reservations skip TEX locks; allotment/oversell untested (G-49). |
| R-18 | Promotions | PARTIAL | all kinds/values/combination rules, reason per rejection · `test_promotions_extras.py` | Values not validated (multiplier > 1 raises price as a "discount") (G-18). `min_basket` ignores currency (G-08). Member discount unreachable (G-57). |
| R-19 | Extras | PARTIAL | 12 pricing modes, service dates, mandatory · `TestExtras` | Per-booking extras charged once per room (G-05, Critical). Inventory/daily capacity offered in UI but not implemented (G-19). No bundles; not effective-dated (G-20, G-58). |
| R-20 | Coupons | PARTIAL | code promotions, scopes, usage limit under row lock | Booking-level coupons applied per room + one redemption per room (G-06). Per-guest limit never enforced (G-07). `min_basket` currency (G-08). Modification self-counts/skips redemptions (G-09). No package scope; no redemption integration test (G-58). |
| R-21 | Modification & repricing | PARTIAL | OLD vs PROPOSED, 4 bases, signed proposals, override needs permission + reason (`modification.py`, `ModifyDrawer.tsx`) · e2e crs + critical-journey | Coupon self-count (G-09). `sale_at` accepted but ignored; ORIGINAL_SALE_DATE/HISTORICAL bases and override untested (G-51). |
| R-22 | Historical simulator | PARTIAL | as-of markups/promotions/FX, version by effective date · `TestHistoricalSimulator` (version only) | Reads live contract status/market/channels, taxes, extras catalog, coupon usage → not deterministic (G-20, G-51). |
| R-23 | Revision history | PARTIAL | actor, time, change, old/new values and amounts, reason, snapshots, immutable · e2e step 19 | Approval never recorded (`approval_status` always "Not Required"); guest lower-price requests stored as notes, not pending revisions (G-59). |
| R-24 | TEX CRS | PARTIAL | `api/crs.py`, `ui_crs.py`, `screens/crs/*`; multi-hotel search, per-room placement | No destination/hotel-group inputs in UI; group search untested (G-40). |
| R-25 | Call Center | PARTIAL | keyboard-first page, all actions incl. resend confirmation · e2e keyboard booking | Agents can switch to any channel's prices; inventory has no channel dimension; cancel/extras/link/resend untested in UI (G-41). |
| R-26 | Booking guest experience | **COMPLETE** | original design, SEARCH→ROOMS→EXTRAS→GUEST→PAY→CONFIRM with context visible · e2e booking desktop+mobile | (Low visual items in G-80) |
| R-27 | Booking search | PARTIAL | dates, rooms, child ages, promo, currency, language, hotel | No destination for group sites (G-40). |
| R-28 | Room/rate results | PARTIAL | size, occupancy, beds, amenities, board, policies, inclusions, promotions, truthful scarcity | No per-room gallery; tax line only when tax is added; no rate comparison view (G-42). |
| R-29 | Multi-room | PARTIAL | each room priced independently; Booking → Reservations links · `TestMultiRoom`, `test_each_room_is_placed_on_its_own`, e2e two rooms | Booking-level extras and coupons are multiplied per room (G-05, G-06, Critical). |
| R-30 | Embeddable booking | PARTIAL | `<tex-booking-widget>` Shadow DOM (isolation verified live), modal/redirect, CSP frame-ancestors | No inline full-booking mode; `modal` = `search`; no widget tests; 1 room only (G-44). |
| R-31 | Custom domains | PARTIAL | DNS TXT verification, verified flag protected · `test_domain_verified_flag_cannot_be_set_by_editing` | No Host → site mapping; all guest links use the platform host; path domains cannot verify; no DNS tests (G-21). |
| R-32 | White label | PARTIAL | validated tokens only (no CSS/JS injection); BrandingTab + preview | No automated tests; analytics ids validated client-side only (G-62). |
| R-33 | Admin UI direction | PARTIAL | compact TEX shell and screens | Kamra-branded entry screens; dashboard not commercial enough (G-60, G-25). |
| R-34 | Design system | PARTIAL | `frontend/src/tex/ui/*` tokens and components | No date picker, tooltip, dropdown or calendar components; contrast failures (G-63). |
| R-35 | Admin navigation | PARTIAL | 11 areas + Call Center | Missing sub-sections: Versions, Periods, Occupancy, Rate Plans, Restrictions/Bulk under Rates & Contracts; BE Rooms/Analytics; CRM Campaigns (not started), Loyalty, Communications (G-64). |
| R-36 | Rates & inventory grid | PARTIAL | `screens/inventory/*`, `commercial/grid.py` | Rows are room types (not room × rate); no copy period; rate cell ignores rate plan/markup; no backend/E2E tests (G-47). |
| R-37 | CRM | PARTIAL | `crm/service.py`, `segments.py`, `screens/crm/*` · consent/export/stats tests | Family, Last Minute, Cancelled, Abandoned, Birthday segments not expressible (G-23). Segments not tenant-scoped (G-26). Profile lacks extras/cancellation totals (G-65). |
| R-38 | Abandoned booking | **COMPLETE** | funnel events, detection, workflow, consent, purge · `test_abandoned_booking_detection` | (Low: email hash stored without consent — G-81) |
| R-39 | Loyalty | PARTIAL | earn/mature/redeem/reverse/expire, ledger, manual adjustment · 1 integration test | No admin UI for programs/rules/tiers/blackouts (G-24). Redemption only as money; blackouts not applied to redemption; thin tests (G-66). |
| R-40 | Payments | PARTIAL (production certification **BLOCKED**) | provider abstraction, hosted/3D flows, no PAN/CVV, fail-closed callbacks, method rules · `TestGuestPayment`, `TestPaymentIntegrity` | gateway_url overridable in production; sandbox payments unflagged; Sipay refund missing; iyzico/Sipay callbacks untested (G-67). Legacy Razorpay webhook unauthenticated (G-15). |
| R-41 | Payment links | PARTIAL | create/reissue/pay/expire, allocation, refund, transfer · `test_payment_link_pays_and_allocates`, `test_refund_transfer_and_idempotency` | Raw link tokens leak through mock_pay/transaction return_url (G-10). Allocation/transfer without lock or idempotency (G-14). Link can be paid twice; refund after transfer hits wrong booking (G-68). |
| R-42 | Guest self-service | PARTIAL | per-hotel toggle, hashed magic link, view/cancel/change with price shown first, pending staff state · `TestSelfService` | Guests cannot add extras after booking (G-22). Higher price not collected as part of the change; "refund"/"credit" policies do nothing; no manage-page e2e (G-45). |
| R-43 | Enterprise / user model | PARTIAL | Enterprise→Group→Hotel grants, 14+ capabilities, anti-escalation, backend enforcement · `TestTenantIsolation`, `test_security_regressions` | Role defaults override per-hotel profiles (G-12). Cross-tenant `new_draft` (G-13). Grants/segments/blank-property rows readable across tenants (G-26). |
| R-44 | TEX Connect | PARTIAL | adapter interface, signed webhook PMS, sandbox, outbox with retry/dead-letter, FX adapters | No channel-manager/email/SMS/WhatsApp adapters (not started); `fetch_availability` unused; outbox/PMS adapters untested (G-69). |
| R-45 | Quote engine | **COMPLETE** | persisted TEX Quote (id, expiry, version, hash, request, breakdown, extras, promotions, tax, total); full internal explanation · `TestSpecExplanationExample`, `test_guest_quotes_never_carry_cost` | (multi-room charges tracked under R-19/R-20) |
| R-46 | Price lock | COMPLETE | snapshot at booking; contract edits don't touch sold reservations; stored-value lock over the whole commercial record; only TEX services change a sold stay, the legacy night audit leaves it alone (G-01, G-04 fixed) · critical journey step 16 (UI shows the locked price), `TestPriceLock`, `TestLegacyNightAudit` | — |
| R-47 | Dashboard | PARTIAL | `reports/service.dashboard` | No enterprise/portfolio view; missing KPIs (reservations today, booking value, direct/call-centre revenue, market/room performance, inventory/restriction alerts) (G-25). |
| R-48 | Reports | PARTIAL | production by stay/booking date, 11 groupings, CSV · 1 test | Missing views/filters; margin does not reconcile; N+1 on country (G-46). |
| R-49 | i18n | PARTIAL | 6-language UI catalogs (parity in CI), guest e-mails, hotel content translations | Server messages (226 `_()`) untranslated and UI language not sent; login page en/ar only; some hard-coded English (G-70). |
| R-50 | Responsive | PARTIAL | no page overflow at 320–1920 on 11 screens; booking mobile e2e | Content clipped at 320 px (inventory, reports); no admin responsive tests (G-80). |
| R-51 | Accessibility | PARTIAL | skip link, focus, labels, dialogs, keyboard e2e | Contrast failures (sidebar 2.62:1, grid, weekend headers); no automated a11y tests (G-63). |
| R-52 | Performance | PARTIAL | lazy areas/languages, caches on immutable terms | 295 KB legacy shell in admin bundle; per-room-type availability queries; guest quotes carry contract internals; no budgets (G-71). |
| R-53 | Security | PARTIAL | TEX endpoints scoped (115, 34 probed), legacy record arguments resolved to their hotel (G-02 fixed, ADR-027), REST/Desk isolation, CSRF, parameterised SQL, escaped e-mail, rate limits, hashed tokens, fail-closed callbacks | High: G-10, G-11, G-12, G-13, G-15, G-16. Medium: G-26. |
| R-54 | Audit trail | PARTIAL | immutable `TEX Audit Event` (actor, roles, hotel, source, old/new, reason) | Draft/rate edits, grid bulk old values, payment rules not audited; group grant events lack hotel (G-74). |
| R-55 | UX productivity | PARTIAL | Ctrl+K, shortcuts, quick booking, duplicate contract, bulk edit, quick payment link | No global search, recent reservations, copy period/restrictions, saved filters (G-75). |
| R-56 | Migrations | PARTIAL | p01–p09 idempotent, in `patches.txt` · p05/p06 tested | p01–p04, p07–p09 untested; no end-to-end upgrade test (G-76). |
| R-57 | Testing | **COMPLETE** | every category in the spec list maps to tests (occupancy, bands, boundaries, combinations, precedence, overrides, versions, historical, periods, FX, markup, promotions, restrictions, concurrency, revisions, permissions, tenancy, payments) | New regression tests are required with each gap fix (FINAL_GAP_AUDIT §4). |
| R-58 | E2E (Playwright) | **COMPLETE** | `frontend/e2e/critical-journey.spec.ts` (19 steps via UI), `booking.spec.ts` desktop + mobile | Low: step 17 changes dates, not occupancy (G-82). |
| R-59 | Visual QA | PARTIAL | manual QA at 320–1920 in tr/en/de | Contrast, 320 px clipping, blank `/`, Kamra login, English system segment names; no visual regression tests (G-80). |
| R-60 | Implementation order | **COMPLETE** (process) | phases followed pricing-first | — |
| R-61 | Process rules | **COMPLETE** (process) | docs + ADRs + this single-state status | — |
| R-62 | Definition of done | PARTIAL | — | Priority 1 (pricing correctness) and 9 (security) still have open Critical items; not done until FINAL_GAP_AUDIT §1 is closed. |
