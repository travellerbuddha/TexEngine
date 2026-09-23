# TEX Engine — Implementation Status

Legend: **COMPLETE** (backend + validation + UI where applicable + tests agree) ·
**PARTIAL** (usable; named gaps remain) · **NOT STARTED** · **BLOCKED** (needs something
only the owner can provide). Requirement IDs refer to `PRODUCT_SPEC.md`.

_Last updated: 2026-09-23 — UI workstreams merged, R-58 browser journey green._

## Test status (dev bench: Frappe v16.25.0, Python 3.14, MariaDB, Node 24)

| Suite | Result |
|---|---|
| TEX pure unit tests (`pytest kamra/tex/tests/unit`) | 138 passed |
| TEX integration (`bench run-tests --module kamra.tex.tests.integration.<m>`) | 62 tests OK: `test_critical_journey` 9, `test_concurrency` 1 (two DB connections race for the last room), `test_commercial_flows` 16, `test_migrations_notify` 5, `test_security_regressions` 11, `test_public_booking` 17, `test_admin_markets` 3 |
| Browser E2E (Playwright, `frontend/e2e`) | 13 passed: `critical-journey` (R-58, 19 steps), `contract-admin`, `booking` ×4 on desktop **and** 390 px mobile, `crs` (keyboard-only call-centre booking; reservation change OLD vs NEW), `shell` |
| Upstream eval harness / front-desk journey / banquet tests | 76/76 · 13/13 · 101 OK (re-run 2026-09-23 after all merges) |
| Semgrep (Frappe rules, ERROR) on `kamra/tex`, `kamra/www`, `kamra/patches/tex` | 0 findings |
| Ruff (TEX code) · `tsc -b` · TEX i18n parity (en, tr, de, ru, ro, pl) · `npm run build` | clean |

CI (`.github/workflows/ci.yml`) runs all of the above, including the Playwright suite against
a seeded bench. The repository has no base branch yet, so CI has not run on GitHub.

## Phases

| Phase | Status | Notes |
|---|---|---|
| 0 Audit + docs | COMPLETE | |
| 1 Foundation (shell, nav, design system) | COMPLETE | TEX shell (sidebar per spec nav, hotel switcher, Ctrl+K palette, language, dark mode), `tex/ui` design system, key-based i18n (6 languages, lazy per language), PMS navigation hidden |
| 2 Commercial data model | COMPLETE | 59 DocTypes (generator `kamra/tex/devtools`), controllers with immutability/revision guards, patches p01–p09 |
| 3 Pricing engine | COMPLETE | pure `kamra/tex/pricing` (Decimal, deterministic, explained), Frappe loader, quote/booking/modification services |
| 4 Contract admin | COMPLETE | contract list/detail/version editor (rooms, periods, rates, child bands, occupancy, boards, rate plans, offers), validate/publish/withdraw, price check with explanation, policies (markup, promotions, FX, tax, pricing), E2E |
| 5 Rate/inventory grid | COMPLETE | inventory grid (availability, stop-sell, LOS, CTA/CTD, release, rates; keyboard; bulk update into drafts) |
| 6 CRS | COMPLETE | multi-hotel search, per-room placement, quote, extras, promo, guest, payment, booking, payment links |
| 7 Call Center | COMPLETE | keyboard-first single screen, caller lookup + history, call notes, quote text, E2E keyboard-only booking |
| 8 Booking + widget | COMPLETE | guest booking app (`/book/<site>`), multi-room, basket with due-now per method, sandbox payment, manage page, `<tex-booking-widget>`, market deep links, localised hotel content |
| 9 Payments | PARTIAL | full flow with the sandbox provider; iyzico / Sipay / NestPay adapters **not production-verified** (BLOCKED on merchant credentials) |
| 10 CRM | COMPLETE | guest list/profile, audited consent, segments + consent-gated export, abandoned bookings, loyalty |
| 11 Self-service | COMPLETE | manage link: view, pay, change dates/guests (lower price → staff approval), cancel with penalty shown first |
| 12 Reports | COMPLETE | dashboard, production (stay/booking date, prorated, 11 groupings), pace & pick-up, CSV |
| 13 Hardening | PARTIAL | security reviews fixed, tenancy hooks, E2E + visual QA done; open items in "Known gaps" |

## Requirements

| ID | Requirement | Status | Behaviour / files / tests / gaps |
|---|---|---|---|
| R-01 | Source & identity | COMPLETE | Fork of Kamra develop @418ed1a, AGPL notices kept (`NOTICE.md`), TEX branding in the shell. |
| R-02 | Architecture principles | COMPLETE | Pure pricing core (no frappe import, test-enforced), services, API, outbox, per-area UI modules. |
| R-03 | TEX Pricing Engine | COMPLETE | `kamra/tex/pricing/engine.py`; explanation trace shown in the contract price check and CRS (cost users). |
| R-04 | Contract management | COMPLETE | `screens/rates/contracts/*`, API `contracts.py`; E2E `contract-admin`. |
| R-05 | Contract versioning | COMPLETE | Draft→Published→Superseded/Withdrawn, frozen payload + sha256; server refuses edits of published versions (E2E asserts). |
| R-06 | Base pricing modes | COMPLETE | ROOM and PERSON bases. |
| R-07 | Occupancy formula engine | COMPLETE | Slots, most-specific-wins, combinations; editor tab. |
| R-08 | Child age engine | COMPLETE | Integer months, band edges, children above the bands priced as adults (explained, capacity text says so). |
| R-09 | Rule hierarchy | COMPLETE | GLOBAL→…→OVERRIDE; the price check names the rule and scope that won. |
| R-10 | Derived rooms | COMPLETE | Derivation with cycle detection; editor rows. |
| R-11 | Stay periods | COMPLETE | Per-night periods; grid changes split periods into a draft. |
| R-12 | Sale vs stay date | COMPLETE | `sale_at` drives version/markup/promo/FX; historical simulator. |
| R-13 | Markets | COMPLETE | `resolve_market` never guesses; Settings → Markets (platform admins; overlap warning); booking deep links `?market=` / `?country=`; CRS market is always chosen. |
| R-14 | Contract vs selling price | COMPLETE | Markup REPLACE/STACK; cost/margin only with `price.view_cost` (stripped everywhere else, test-covered). |
| R-15 | Currency engine | PARTIAL | FX policies, TCMB/ECB parsers, daily fetch, per-booking snapshot, FX rates screen. Live TCMB/ECB fetch not verified from this sandbox (egress). |
| R-16 | Restrictions | COMPLETE | Stop-sell modes, LOS, CTA/CTD, release, advance windows; grid editing. |
| R-17 | Inventory | COMPLETE | Pools + allotments, row locks; race test; inventory grid. |
| R-18 | Promotions | COMPLETE | Policy editor; exclusive/priority/stacking; usage limits. |
| R-19 | Extras | COMPLETE | 12 pricing modes; online-bookable extras in the booking app; CRS extras picker. |
| R-20 | Coupons | COMPLETE | Code promotions, per-guest limits; legacy vouchers migrated (p05). |
| R-21 | Modification & repricing | COMPLETE | OLD vs PROPOSED with 4 bases, signed 30-min proposals, re-check under lock; Reservations → Modify; E2E. |
| R-22 | Historical simulator | COMPLETE | Reservation simulator panel (read-only). |
| R-23 | Revision history | COMPLETE | `TEX Reservation Revision` + audit; timeline on the reservation; E2E asserts. |
| R-24 | TEX CRS | COMPLETE | `screens/crs`, `api/crs.py` + `ui_crs.py`; per-room placement (ADR-024). |
| R-25 | Call Center | COMPLETE | Keyboard-first screen; re-send confirmation (rotates the manage link, audited). |
| R-26 | Booking guest experience | COMPLETE | Booking app, 6 languages, WCAG checks (axe) on key steps, mobile-first. |
| R-27 | Booking search | COMPLETE | Rate limited (raisable per site), market resolution, currency whitelist. |
| R-28 | Room/rate results | COMPLETE | No internals exposed; localised content (ADR-026). |
| R-29 | Multi-room | COMPLETE | Each room placed on its own, mixed room types, availability guard across rooms, server basket totals. |
| R-30 | Embeddable booking | COMPLETE | `<tex-booking-widget>` (7 kB gz), CSP frame-ancestors + CORS from `allowed_embed_origins`. Real card gateway inside the iframe untested (sandbox only). |
| R-31 | Custom domains | PARTIAL | DNS TXT verification + `{booking}` return URLs; TLS/serving on the customer domain is an infrastructure step (not in the app). |
| R-32 | White label | COMPLETE | Validated tokens only; no CSS/JS injection. |
| R-33 | Admin UI direction | COMPLETE | TEX shell and screens replace PMS navigation. |
| R-34 | Design system | COMPLETE | `frontend/src/tex/ui` (primitives, forms, tables, overlays, feedback, money). |
| R-35 | Admin navigation | COMPLETE | Dashboard, CRS, Call Center, Reservations, Rates & Contracts, Inventory, Booking Engine, CRM, Payments, Reports, Connect, Settings; capability-driven. |
| R-36 | Rates & inventory grid | COMPLETE | See phase 5. |
| R-37 | CRM | COMPLETE | Stays = completed stays; lifetime value with its currency (p09). |
| R-38 | Abandoned booking | COMPLETE | Detection, recovery marking, consent-aware, purge. |
| R-39 | Loyalty | COMPLETE | Earn/mature/redeem/reverse/expire; profile view. |
| R-40 | Payments | PARTIAL | Sandbox end to end (card, decline, retry, links, refunds, transfers). **BLOCKED:** production verification of iyzico / Sipay / NestPay needs merchant credentials. |
| R-41 | Payment links | COMPLETE | Create/reissue/pay/expire; token hash only. |
| R-42 | Guest self-service | COMPLETE | Manage page; resume token for lost responses (ADR-025). |
| R-43 | Enterprise / user model | COMPLETE | Grants with anti-escalation; users & access screen hides grants beyond the viewer's scope. |
| R-44 | TEX Connect | PARTIAL | Outbox, adapters (webhook PMS, sandbox), delivery monitor. No vendor-specific PMS/channel-manager adapter yet. |
| R-45 | Quote engine | COMPLETE | HMAC offer keys, persisted quotes with TTL, countdown on the server clock. |
| R-46 | Price lock | COMPLETE | Snapshot + guard; E2E asserts the locked price survives a contract change. |
| R-47 | Dashboard | COMPLETE | |
| R-48 | Reports | COMPLETE | |
| R-49 | i18n | COMPLETE | UI catalogs in 6 languages (parity check in CI), guest e-mails in 6 languages, hotel content translations (Booking Engine → Content & languages). Server error texts are English where Frappe has no translation. |
| R-50 | Responsive | COMPLETE | Visual QA at 375/390/1440 px; no horizontal page overflow on any admin screen. |
| R-51 | Accessibility | PARTIAL | Keyboard paths, labelled controls, focus traps, axe on booking steps with no violations. No full WCAG audit of every admin screen. |
| R-52 | Performance | PARTIAL | Indexes, caches, lazy area chunks, lazy languages (admin chunk 204 kB / 58 kB gz). No load test. |
| R-53 | Security | PARTIAL | Capability + scope checks on every TEX endpoint, tenancy hooks on all hotel-bound DocTypes, fail-closed callbacks, namespaced idempotency, no secrets logged; see `SECURITY_MODEL.md` §7. |
| R-54 | Audit trail | COMPLETE | `TEX Audit Event` + Settings → Audit trail. |
| R-55 | UX productivity | COMPLETE | Ctrl+K palette, call-centre shortcuts, grid keyboard editing, bulk updates. |
| R-56 | Migrations | COMPLETE | p01–p09 (see `MIGRATION_PLAN.md`); T8 legacy contract drafts opt-in. |
| R-57 | Testing | COMPLETE | Unit, integration, E2E as above. |
| R-58 | E2E (Playwright) | COMPLETE | `frontend/e2e/critical-journey.spec.ts` — all 19 steps through the UI; mobile booking in `booking.spec.ts` (390 px). |
| R-59 | Visual QA | COMPLETE | Screens reviewed at phone/desktop widths in tr/en/de; defects fixed (see git log "visual QA"). |
| R-60 | Implementation order | — | Followed. |
| R-61 | Process rules | — | Small commits, ADR-001…026, docs per milestone. |
| R-62 | Definition of done | — | Tracked here. |

## Known gaps (owner decisions or credentials needed)
1. **Payment gateways:** iyzico / Sipay / NestPay adapters follow the public docs but are not
   production-verified — needs merchant sandbox + production credentials.
2. **Outgoing e-mail:** no SMTP account on the bench; booking e-mails are queued/logged but
   not delivered (`sent: false` is shown honestly in the UI).
3. **Base branch for the PR:** the repository only has the working branch; a `main` (or other
   base) branch is needed to open the pull request and run CI on GitHub.
4. Vendor-specific PMS / channel-manager adapters (TEX Connect) are not built.
5. Booking fonts load from Bunny Fonts; self-hosting is safer for GDPR-strict markets.
6. Promotion names (group-level records) are not yet translatable.
