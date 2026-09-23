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
| TEX pure unit tests | `python -m pytest kamra/tex/tests/unit -q` | **197 passed** |
| TEX integration tests (14 modules) | `bench --site test.localhost run-tests --module kamra.tex.tests.integration.<m>` | **214 OK**: admin_markets 4, commercial_flows 41, concurrency 7 (threaded), critical_journey 10, crm_segments 7, custom_domains 9, distribution 16, extras_inventory 17, loyalty_admin 7, migrations_notify 7, portfolio 2, post_booking_extras 12, public_booking 17, security_regressions 58 (re-run for the payments go-live follow-up, ADR-042) |
| Browser E2E (Playwright) | `cd frontend && npx playwright test -c e2e` | **14 passed**: critical-journey (R-58, 19 steps), contract-admin, crs ×2, shell, policy-revisions (G-20), booking ×4 desktop + ×4 mobile (Pixel 7) |
| Upstream Kamra suites | `run_baseline.sh` | eval harness **76/76**, front-desk journey **13/13**, banquet **101 OK** |
| TypeScript / build / i18n parity | `npx tsc -b`, `npm run build`, `npm run i18n:tex` | clean; the rebuild is identical to the committed bundles (the payments follow-up re-ran `tsc` only: clean) |
| Lint / static security | `ruff check kamra/tex kamra/patches/tex`; semgrep (Frappe rules, ERROR) | clean / 0 findings (semgrep 1.177, frappe/semgrep-rules + r/python.lang.correctness, ERROR) |

**Coverage gaps.** Green tests do not prove absence of the defects below. The audit reproduced
several critical defects with probes and scratch tests that the suite does not contain yet
(see FINAL_GAP_AUDIT §1).

**CI.** `.github/workflows/ci.yml` runs all of the above including Playwright. It has never
run on GitHub, because the repository has no base branch (BLOCKED, owner).

**Resumed (2026-09-23).** G-30/G-31 (occupancy precedence v2) and G-45 (self-service money flows) are being finished on their own branches (snapshots and designs in [`wip/`](wip/README.md) until merged); G-50 and G-83 are in progress. Root `SECURITY.md` rewritten for TEX (security contact still an owner input).

**Go-live.** Launch readiness per area (READY / PARTIAL / BLOCKED), the blockers and the owner inputs are in
[`GO_LIVE_READINESS.md`](GO_LIVE_READINESS.md). Verdict: NOT READY.

## 2. Summary

| Status | Count | Requirements |
|---|---|---|
| COMPLETE | 10 | R-06, R-10, R-26, R-38, R-45, R-46, R-57, R-58, R-60 (process), R-61 (process) |
| PARTIAL | 52 | all others; the gaps are listed per row |
| NOT STARTED | 0 whole requirements | sub-items not started: CRM Campaigns (R-35/R-37), SMS / WhatsApp adapters (R-44), booking-window restriction (R-16), bundled extras (R-19), package coupons (R-20) |
| BLOCKED | 0 whole requirements | blocked sub-items: production certification of iyzico / Sipay / NestPay (R-40, merchant credentials); channel-manager provider certification (R-44, provider credentials); outgoing e-mail delivery (SMTP account); PR + CI on GitHub (base branch) |

**Open gaps by severity:** 0 Critical, 5 High, 33 Medium, 7 Low (+3 blocked items), counted from the FINAL_GAP_AUDIT tables. All nine Critical
gaps (G-01…G-09) were fixed after the audit; G-84 (Medium) was found while fixing G-06 (FINAL_GAP_AUDIT, "Resolved since the audit"). Details are in
FINAL_GAP_AUDIT. Critical means wrong money or a security hole.

## 3. Phases (derived from the requirement rows below)

| Phase | Status | Why |
|---|---|---|
| 0 Audit + docs | COMPLETE | spec, architecture, ADR-001…033, this audit |
| 1 Foundation (shell, nav, design system, hide PMS) | PARTIAL | TEX shell and design system work; the legacy booking engine no longer sells TEX hotels (G-03 fixed); the legacy night audit leaves TEX-sold stays alone (G-04 fixed); the legacy PMS is closed in backend and SPA while switched off (G-16 fixed, ADR-030). Open: the login page, browser title and Desk tile still say "Kamra PMS" (G-60) |
| 2 Commercial data model | PARTIAL | 62 DocTypes + patches p01–p13; extras and taxes are effective-dated revisions (G-20 fixed, ADR-031); money fields still partly Float (G-72) |
| 3 Pricing engine | PARTIAL | pure engine correct on every spec example; booking-level extras and fixed coupons priced once per booking, min basket in the sell currency (G-05, G-06, G-08 fixed); per-guest limits enforced at booking and modifications keep redemptions right (G-07, G-09 fixed); min basket per room (G-84) |
| 4 Contract admin | PARTIAL | editor, publish, price check work (E2E); the first contract that can sell a stay wins (G-17 fixed); contract cost hidden from agents (G-11 fixed) |
| 5 Rate/inventory grid | PARTIAL | grid + bulk edit exist; no backend/E2E tests, no copy period, rows are room types only (G-47) |
| 6 CRS | PARTIAL | works incl. multi-room; no destination/group inputs (G-40) |
| 7 Call Center | PARTIAL | keyboard-first flow tested; channel not bound to the agent (G-41) |
| 8 Booking + widget | PARTIAL | full flow tested desktop+mobile; custom domains not served (G-21), no inline widget mode (G-44) |
| 9 Payments | PARTIAL | sandbox end to end; link tokens never stored or leaked, allocations locked and idempotent (G-10, G-14 fixed); production certification BLOCKED |
| 10 CRM | PARTIAL | guests, consent, segments, abandoned; 5 named segments not expressible (G-23), no loyalty admin UI (G-24) |
| 11 Self-service | PARTIAL | view/pay/change/cancel; no extras after booking (G-22), credit/refund policies do nothing (G-45) |
| 12 Reports | PARTIAL | production report; missing views/filters, margin does not reconcile (G-46) |
| 13 Hardening | PARTIAL | this audit; all Critical items and G-10…G-20, G-85, G-86 fixed with regression tests; High G-21…G-25 open |

## 4. Requirements

| ID | Requirement | Status | Evidence (files · tests) | Gaps (→ FINAL_GAP_AUDIT) |
|---|---|---|---|---|
| R-01 | Source & identity | PARTIAL | AGPL notices, `NOTICE.md`, baseline 418ed1a in history; TEX shell branding | The legacy PMS is closed to hotel users while switched off (G-16 fixed, ADR-030); the legacy booking engine refuses TEX hotels and the legacy night audit leaves TEX stays alone (G-03, G-04 fixed, ADR-028). Login/tab/Desk still say "Kamra PMS" (G-60). Release/nightly workflows ship upstream Kamra images (G-61). |
| R-02 | Architecture principles | PARTIAL | `kamra/tex/pricing` has no frappe import (`TestPurity`); no import cycles; the frontend only formats decimal strings | Loyalty uses Float money fields (G-72). The legacy float pricing path remains only for hotels outside TEX (ADR-028; G-03 fixed). |
| R-03 | Pricing engine | PARTIAL | modular resolvers in `kamra/tex/pricing/*`; Decimal (`money.calc`); explanation trace; extras and taxes as of the sale time, every EXTRA/TAX step names its revision (G-20 fixed, ADR-031) · `test_engine.py`, `TestPayload`, `TestEffectiveDatedSources`, `TestEffectiveDatedExtrasAndTaxes` | Several rate/money DocType fields are still Float (G-72, Low). |
| R-04 | Contract management | PARTIAL | `api/contracts.py`, `commercial/contracts.py`, `screens/rates/contracts/*` · e2e `contract-admin` | Header fields editable after publish (G-50). (Fixed: contract selection G-17, cost visibility G-11; `TestContractSelection`.) |
| R-05 | Versioning & snapshot | PARTIAL | immutable versions, frozen payload + hash verified on load (`tex_contract_version.py`, `revisions.py`) · `TestContractImmutability`, `test_payload_integrity_is_checked`, e2e | Snapshot keeps periods/rules by reference only; no explicit quote timestamp (G-73). (The REST lock bypass G-01 is fixed, `TestPriceLock`.) |
| R-06 | Base pricing modes | **COMPLETE** | `occupancy.py` PERSON/ROOM · `TestRoomBasis`, `TestPersonBasis`; basis select in `ContractDialogs.tsx` | — |
| R-07 | Occupancy formula engine | PARTIAL | slot model, combinations not hardcoded (`occupancy.py`, `contracts.parse_combination`) · spec examples reproduced (270; 2A+1C 250 vs 1A+1C 200) | Global/hotel/market policy rules do not cascade (single `_policy_for`) (G-30). Band-less position/combination rules silently outrank band rules incl. infant ×0; no publish warning (G-31). |
| R-08 | Child age engine | PARTIAL | integer months, DOB-at-arrival (`ages.py`) · `test_boundaries_in_months`, `TestChildrenAtBoundaries` (35/36, 83/84, 143/144 months) | Per-hotel/market bands untested; band gaps not detected at publish; no DOB input in UI (G-52). |
| R-09 | Rule hierarchy | PARTIAL | `Level` precedence; winning + overridden rules in the price check (`PreviewTab.tsx`) · markup/occupancy precedence tests, e2e asserts explanation | Policy cascade (G-30). Same-scope markup ties resolved silently. Markup explanation level ignores channel (G-53). |
| R-10 | Derived rooms | **COMPLETE** | `rooms.py` (derivation, cycle guard, absolute override) · `test_derived_rooms`, `test_base_change_propagates`, `test_absolute_override_wins_in_its_period`; `RatesTab.tsx` | — |
| R-11 | Stay periods | PARTIAL | unlimited periods, weekday/priority, grid bulk rate change into a draft | No copy period; no bulk edit of occupancy/child/board across periods; `apply_rate_change` untested (G-47). |
| R-12 | Sale vs stay date | PARTIAL | sale/stay windows, promotion booking-date/arrival/departure/LOS/through rules; extras and taxes effective-dated by sale time (G-20 fixed) · `test_sale_date_outside_eb_window`, `TestEligibility`, `TestEffectiveDatedExtrasAndTaxes` | Base rates/markups have no arrival/LOS/booking-date rules (G-54). |
| R-13 | Markets | PARTIAL | `resolve_market` never guesses; Settings → Markets · `test_admin_markets`, market tests | Booking app silently drops a refused market link; guest country not reconciled with pricing market (G-55). |
| R-14 | Contract vs selling price | PARTIAL | markup types/scopes/STACK; cost & margin stored; cost, rates and markups only with `price.view_cost` (G-11 fixed) · `TestMarkup` (1000+8%=1080), `test_g11_agents_never_see_contract_cost` | Margin % understated and untested (G-46). |
| R-15 | Currency engine | PARTIAL | FX modes, TCMB/ECB adapters, as-of rates, room-rate FX snapshot · `TestFx` (50+2%→51) | FX used for extras and fixed promotions not snapshotted; no cross-currency booking integration test (G-56). |
| R-16 | Restrictions | PARTIAL | stop-sell modes, LOS, CTA/CTD, release, advance; enforced on search/quote/book · `TestRestrictions` | No booking-window restriction; no hotel/market-level cells; modifications treat restrictions as warnings (incl. guest path); no integration test of enforcement (G-48). |
| R-17 | Inventory | PARTIAL | pools, allotments, oversell limit, manual adjustment, row locks; simultaneous bookings of different room types never deadlock, a deadlock victim is re-run (G-85 fixed, ADR-032) · `test_concurrency` (last room, room types side by side, retry) | Legacy `validate_type_capacity` blocks TEX oversell/pools; non-TEX reservations skip TEX locks; allotment/oversell untested (G-49). |
| R-18 | Promotions | PARTIAL | all kinds/values/combination rules, reason per rejection · `test_promotions_extras.py` | Member discount unreachable (G-57). (Fixed: value guards in engine and on save G-18, min-basket currency G-08; `test_value_guards`, `TestCommercialValues`.) |
| R-19 | Extras | PARTIAL | 12 pricing modes, service dates, mandatory; effective-dated revisions with Revise/Activate in Rates → Extras (G-20 fixed); limited daily capacity end to end, concurrency-safe, with Inventory → Extras, CRS and guest availability (G-19 fixed, ADR-033) · `TestExtras`, `TestEffectiveDatedExtrasAndTaxes`, `test_extras_inventory` (unit + integration), `TestConcurrentLastExtra`, e2e `policy-revisions` | Not bookable after booking (G-22). No bundles (G-58). |
| R-20 | Coupons | PARTIAL | code promotions, scopes, usage and per-guest limits counted under the promotion's row lock with a current read (G-07 regression fixed) · `TestConcurrentCouponLimit` | `min_basket` is evaluated per room on multi-room bookings (G-84). No package scope (G-58). (Fixed: per-guest limit at booking G-07, min-basket currency G-08, modification redemptions G-09; redemption tests `TestBookingLevelTerms`, `TestCouponLimits`.) |
| R-21 | Modification & repricing | PARTIAL | OLD vs PROPOSED, 4 bases, signed proposals, override needs permission + reason (`modification.py`, `ModifyDrawer.tsx`); repricing ignores the booking's own coupon use and redemptions follow the modification (G-09 fixed) · e2e crs + critical-journey, `TestCouponLimits` | `sale_at` accepted but ignored; ORIGINAL_SALE_DATE/HISTORICAL bases and override untested (G-51). |
| R-22 | Historical simulator | PARTIAL | as-of markups/promotions/FX/extras/taxes, version by effective date; activation can't be back-dated (G-20 fixed) · `TestHistoricalSimulator`, `TestEffectiveDatedExtrasAndTaxes` | Reads live contract status/market/channels and coupon usage → not fully deterministic (G-51). |
| R-23 | Revision history | PARTIAL | actor, time, change, old/new values and amounts, reason, snapshots, immutable · e2e step 19 | Approval never recorded (`approval_status` always "Not Required"); guest lower-price requests stored as notes, not pending revisions (G-59). |
| R-24 | TEX CRS | PARTIAL | `api/crs.py`, `ui_crs.py`, `screens/crs/*`; multi-hotel search, per-room placement | No destination/hotel-group inputs in UI; group search untested (G-40). |
| R-25 | Call Center | PARTIAL | keyboard-first page, all actions incl. resend confirmation · e2e keyboard booking | Agents can switch to any channel's prices; inventory has no channel dimension; cancel/extras/link/resend untested in UI (G-41). |
| R-26 | Booking guest experience | **COMPLETE** | original design, SEARCH→ROOMS→EXTRAS→GUEST→PAY→CONFIRM with context visible · e2e booking desktop+mobile | (Low visual items in G-80) |
| R-27 | Booking search | PARTIAL | dates, rooms, child ages, promo, currency, language, hotel | No destination for group sites (G-40). |
| R-28 | Room/rate results | PARTIAL | size, occupancy, beds, amenities, board, policies, inclusions, promotions, truthful scarcity | No per-room gallery; tax line only when tax is added; no rate comparison view (G-42). |
| R-29 | Multi-room | PARTIAL | each room priced independently; Booking → Reservations links; booking-level extras and fixed coupons priced once, on room 1, one redemption per booking (ADR-029, G-05/G-06 fixed) · `TestMultiRoom`, `test_each_room_is_placed_on_its_own`, `TestBookingLevelTerms`, `test_booking_level`, e2e two rooms | A coupon's minimum basket is checked per room, not per booking (G-84). |
| R-30 | Embeddable booking | PARTIAL | `<tex-booking-widget>` Shadow DOM (isolation verified live), modal/redirect, CSP frame-ancestors | No inline full-booking mode; `modal` = `search`; no widget tests; 1 room only (G-44). |
| R-31 | Custom domains | PARTIAL | DNS TXT verification with daily recheck; host → site mapping, pinned engine and API; guest links on the hotel's host; Domains tab (ADR-035, G-21 fixed) · `test_custom_domains` (9), e2e `custom-host.spec.ts` | TLS certificate and `add-domain` per host are operations (GO_LIVE_READINESS). |
| R-32 | White label | PARTIAL | validated tokens only (no CSS/JS injection); BrandingTab + preview | No automated tests; analytics ids validated client-side only (G-62). |
| R-33 | Admin UI direction | PARTIAL | compact TEX shell and screens | Kamra-branded entry screens; dashboard not commercial enough (G-60, G-25). |
| R-34 | Design system | PARTIAL | `frontend/src/tex/ui/*` tokens and components | No date picker, tooltip, dropdown or calendar components; contrast failures (G-63). |
| R-35 | Admin navigation | PARTIAL | 11 areas + Call Center | Missing sub-sections: Versions, Periods, Occupancy, Rate Plans, Restrictions/Bulk under Rates & Contracts; BE Rooms/Analytics; CRM Campaigns (not started), Loyalty, Communications (G-64). |
| R-36 | Rates & inventory grid | PARTIAL | `screens/inventory/*`, `commercial/grid.py` | Rows are room types (not room × rate); no copy period; rate cell ignores rate plan/markup; no backend/E2E tests (G-47). |
| R-37 | CRM | PARTIAL | `crm/service.py`, `segments.py`, `screens/crm/*`; typed segments over per-tenant facts, 9 presets, enterprise-owned segments (ADR-036, G-23 fixed; tenancy G-26 fixed) · `test_crm_segments`, consent/export/stats tests, e2e `crm-admin.spec.ts` | Profile lacks extras/cancellation totals (G-65); campaigns not started. |
| R-38 | Abandoned booking | **COMPLETE** | funnel events, detection, workflow, consent, purge · `test_abandoned_booking_detection` | (Low: email hash stored without consent — G-81) |
| R-39 | Loyalty | PARTIAL | earn/mature/redeem/reverse/expire, ledger, manual adjustment; programs, rules, tiers and blackouts administered in TEX; frozen earnings; redemption cap and blackouts (ADR-037, G-24 fixed) · `test_loyalty_admin` (7), e2e `crm-admin.spec.ts` | Redemption only as money (G-66). |
| R-40 | Payments | PARTIAL (production certification **BLOCKED**) | provider abstraction, hosted/3D flows, no PAN/CVV, fail-closed callbacks, method rules; Production gated on certification at save and run time, no gateway URL override in Production, a Sandbox override only on the provider's sandbox host, no sandbox gateway on a live site (`tex_production`); new money and settling gated apart, so captured money is always recorded and refundable (patch p19 lists gated accounts); captured amount and currency verified, a refused capture audited and refundable (G-67, ADR-041, ADR-042) · `TestGuestPayment`, `TestPaymentIntegrity`, `TestGoLivePayments`, `TestGoLivePaymentsReview`, unit `TestProviderRegistry` | Sipay refund missing and live certification BLOCKED (merchant credentials); Sipay's status answer is not yet a recorded sandbox response; bookings paid in Sandbox on a non-live site carry no per-booking flag (schema field). |
| R-41 | Payment links | PARTIAL | create/reissue/pay/expire, allocation, refund, transfer; one charge per link at a time (`NOWAIT` link lock, locking reads after locks), an iyzico charge has one checkout and another tab or a refused restart supersedes it, captured money on superseded, Failed or closed-link charges recorded and flagged, refunds take unallocated money first and then the booking holding the money (G-68, ADR-041, ADR-042) · `test_payment_link_pays_and_allocates`, `test_refund_transfer_and_idempotency`, `TestPaymentLinkTokens` (G-10 fixed), `TestGoLivePayments`, `TestGoLivePaymentsReview` | Two tabs paying through different gateways, or two iyzico tabs, can still pay twice (kept and flagged for refund); `pay_booking` starts a new charge per call; simultaneous staff refunds/allocations of one payment rely on snapshot totals (needs indexes); no e2e for the link page. |
| R-42 | Guest self-service | PARTIAL | per-hotel toggle, hashed magic link, view/cancel/change with price shown first, pending staff state; extras after booking (G-22 fixed, ADR-034) · `TestSelfService`, `test_post_booking_extras`, e2e `post-booking-extras.spec.ts` | Higher price not collected as part of the change; "refund"/"credit" policies do nothing (G-45). |
| R-43 | Enterprise / user model | PARTIAL | Enterprise→Group→Hotel grants, 14+ capabilities, anti-escalation (also on update and delete of a grant), backend enforcement; tenant structure scoped (G-26 fixed, ADR-040) · `TestTenantIsolation`, `TestAdminDataTenancy`, `test_security_regressions` | Guest identity shared inside an enterprise by design (ADR-040). |
| R-44 | TEX Connect | PARTIAL | adapter interface, signed webhook PMS, sandbox, outbox with claim/retry/dead-letter (PMS connections only; an uncertified adapter never delivers in Production, G-90), FX adapters; channel distribution (ADR-039): mappings, ARI computed from TEX and pushed as changes, signed idempotent inbound bookings applied in order, error queue, reconciliation, audit, sandbox channel adapter (`test_distribution` 16); staff UI Connect → Channels (`channel.view` / `channel.manage`): connections with queue/inbound counts and webhook, mappings editor, ARI preview with queue/send/resend, inbound log with retry/apply, reconciliation, sandbox booking simulator (e2e `channels.spec.ts`, not yet run on a bench) | Real channel-manager providers BLOCKED on credentials/certification; no e-mail/SMS/WhatsApp adapters; `fetch_availability` unused. Mappings: switching a mapping off sends a close-out; a switched-off mapping is deleted once the channel accepted it (`distribution.delete_mapping`). |
| R-45 | Quote engine | **COMPLETE** | persisted TEX Quote (id, expiry, version, hash, request, breakdown, extras, promotions, tax, total); full internal explanation · `TestSpecExplanationExample`, `test_guest_quotes_never_carry_cost` | (multi-room charges tracked under R-19/R-20) |
| R-46 | Price lock | COMPLETE | snapshot at booking; contract edits don't touch sold reservations; stored-value lock over the whole commercial record; only TEX services change a sold stay, the legacy night audit leaves it alone (G-01, G-04 fixed) · critical journey step 16 (UI shows the locked price), `TestPriceLock`, `TestLegacyNightAudit` | — |
| R-47 | Dashboard | PARTIAL | `reports/service.dashboard`; portfolio across enterprise/group/hotels with sales, payment, abandonment KPIs per currency and inventory/restriction alerts (ADR-038, G-25 fixed) · `test_portfolio`, e2e `portfolio.spec.ts` | Per-hotel time zones; no reporting-currency conversion. |
| R-48 | Reports | PARTIAL | production by stay/booking date, 11 groupings, CSV · 1 test | Missing views/filters; margin does not reconcile; N+1 on country (G-46). |
| R-49 | i18n | PARTIAL | 6-language UI catalogs (parity in CI), guest e-mails, hotel content translations | Server messages (226 `_()`) untranslated and UI language not sent; login page en/ar only; some hard-coded English (G-70). |
| R-50 | Responsive | PARTIAL | no page overflow at 320–1920 on 11 screens; booking mobile e2e | Content clipped at 320 px (inventory, reports); no admin responsive tests (G-80). |
| R-51 | Accessibility | PARTIAL | skip link, focus, labels, dialogs, keyboard e2e | Contrast failures (sidebar 2.62:1, grid, weekend headers); no automated a11y tests (G-63). |
| R-52 | Performance | PARTIAL | lazy areas/languages, caches on immutable terms | 295 KB legacy shell in admin bundle; per-room-type availability queries; guest quotes carry contract internals; no budgets (G-71). |
| R-53 | Security | PARTIAL | TEX endpoints scoped (115, 34 probed), legacy record arguments resolved to their hotel (G-02 fixed, ADR-027), REST/Desk isolation, CSRF, parameterised SQL, escaped e-mail, rate limits, hashed tokens, fail-closed callbacks | (G-10…G-16 fixed.) Medium: G-26. |
| R-54 | Audit trail | PARTIAL | immutable `TEX Audit Event` (actor, roles, hotel, source, old/new, reason) | Draft/rate edits, grid bulk old values, payment rules not audited; group grant events lack hotel (G-74). |
| R-55 | UX productivity | PARTIAL | Ctrl+K, shortcuts, quick booking, duplicate contract, bulk edit, quick payment link | No global search, recent reservations, copy period/restrictions, saved filters (G-75). |
| R-56 | Migrations | PARTIAL | p01–p09 idempotent, in `patches.txt` · p05/p06 tested | p01–p04, p07–p09 untested; no end-to-end upgrade test (G-76). |
| R-57 | Testing | **COMPLETE** | every category in the spec list maps to tests (occupancy, bands, boundaries, combinations, precedence, overrides, versions, historical, periods, FX, markup, promotions, restrictions, concurrency, revisions, permissions, tenancy, payments) | New regression tests are required with each gap fix (FINAL_GAP_AUDIT §4). |
| R-58 | E2E (Playwright) | **COMPLETE** | `frontend/e2e/critical-journey.spec.ts` (19 steps via UI), `booking.spec.ts` desktop + mobile | Low: step 17 changes dates, not occupancy (G-82). |
| R-59 | Visual QA | PARTIAL | manual QA at 320–1920 in tr/en/de | Contrast, 320 px clipping, blank `/`, Kamra login, English system segment names; no visual regression tests (G-80). |
| R-60 | Implementation order | **COMPLETE** (process) | phases followed pricing-first | — |
| R-61 | Process rules | **COMPLETE** (process) | docs + ADRs + this single-state status | — |
| R-62 | Definition of done | PARTIAL | — | FINAL_GAP_AUDIT §1 (Critical) is closed; priorities 1 (pricing) and 9 (security) still have High items open (§2), so not done. |
