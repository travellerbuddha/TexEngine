# TEX Engine — Implementation Status

Legend: **COMPLETE** (backend + validation + UI where applicable + tests agree) ·
**PARTIAL** · **NOT STARTED** · **BLOCKED**. Requirement IDs refer to `PRODUCT_SPEC.md`.
"Backend ✔" means the server side (model, service, API, permission checks, tests) is done;
the requirement stays PARTIAL until its UI exists and passes its tests.

_Last updated: 2026-09-22 — backend milestone (Phases 2, 3, 6–12 server side + legacy tenancy)._

## Test status (TEX dev bench, Frappe v16.25.0, Python 3.14)

| Suite | Result |
|---|---|
| TEX pure unit tests (`pytest kamra/tex/tests/unit`) | 138 passed |
| TEX critical journey R-58, services level (`kamra.tex.tests.integration.test_critical_journey`) | 9 tests OK |
| TEX real concurrency (`…test_concurrency`, two DB connections race for the last room) | OK (8/8 repeated runs) |
| TEX commercial flows (`…test_commercial_flows`: payments, self-service, CRM, loyalty, reports, tenancy) | 16 tests OK |
| Upstream eval harness | 76/76 |
| Upstream front-desk journey | 13/13 |
| Upstream banquet tests | 101 OK |
| Semgrep (Frappe rules + python.lang.correctness, ERROR) on `kamra/` | 0 findings |
| Ruff on TEX code | clean |
| Frontend build / Playwright | not run yet (UI phases pending) |

Upstream test fixtures changed only to give their persona users an explicit all-hotels
scope (`kamra.tex.setup.ensure_all_hotels_scope`) — required by strict tenancy; no assertion
was changed.

## Phases

| Phase | Status | Notes |
|---|---|---|
| 0 Audit + docs | COMPLETE | |
| 1 Foundation (shell, nav, design system) | NOT STARTED | next |
| 2 Commercial data model | COMPLETE | 57 DocTypes (generator `kamra/tex/devtools`), controllers with immutability/revision guards, patches p01–p04 |
| 3 Pricing engine | COMPLETE (backend) | pure `kamra/tex/pricing`, Frappe loader, quote/booking/modification services |
| 4 Contract admin | PARTIAL | API `kamra.tex.api.contracts` done; UI pending |
| 5 Rate/inventory grid | PARTIAL | `kamra/tex/commercial/grid.py` + API done; UI pending |
| 6 CRS | PARTIAL | API `kamra.tex.api.crs` done; UI pending |
| 7 Call Center | PARTIAL | uses CRS API; keyboard-first UI pending |
| 8 Booking + widget | PARTIAL | guest API `kamra.tex.api.public` done; booking app + widget pending |
| 9 Payments | PARTIAL | service, providers, API done; UI pending; real gateways not production-verified (no credentials) |
| 10 CRM | PARTIAL | service/API done; UI pending |
| 11 Self-service | PARTIAL | guest API done; manage-booking pages pending |
| 12 Reports | PARTIAL | service/API done; UI pending |
| 13 Hardening | PARTIAL | legacy tenancy guard + permission hooks done; E2E/visual QA pending |

## Requirements

| ID | Requirement | Status | Behaviour / files / tests / gaps |
|---|---|---|---|
| R-01 | Source & identity | PARTIAL | Fork of Kamra develop @418ed1a with history, AGPL notices kept (`NOTICE.md`). TEX branding in UI pending. |
| R-02 | Architecture principles | PARTIAL | Pure pricing core (no frappe import, enforced by test), services, API, outbox. UI pending. |
| R-03 | TEX Pricing Engine | PARTIAL (backend ✔) | `kamra/tex/pricing/engine.py` — Decimal only, deterministic, explanation trace, payload hash. 127 unit tests. Admin "why this price" view pending. |
| R-04 | Contract management | PARTIAL (backend ✔) | `TEX Contract`/`Version`, `kamra/tex/commercial/contracts.py`, API `contracts.py` (list/get/save/duplicate/validate/publish/withdraw/preview/matrix). UI pending. |
| R-05 | Contract versioning | PARTIAL (backend ✔) | Draft→Published→Superseded/Withdrawn, frozen payload + sha256 integrity check, scheduled `effective_from`; tests `TestContractImmutability`. |
| R-06 | Base pricing modes | PARTIAL (backend ✔) | ROOM and PERSON bases (`occupancy.py`); unit tests. |
| R-07 | Occupancy formula engine | PARTIAL (backend ✔) | Slot model, most-specific-wins, combinations; unit tests. |
| R-08 | Child age engine | PARTIAL (backend ✔) | Integer-month ages, exact band edges, `Unsellable(NO_AGE_BAND)`. |
| R-09 | Rule hierarchy | PARTIAL (backend ✔) | GLOBAL→…→OVERRIDE precedence in engine; unit tests. |
| R-10 | Derived rooms | PARTIAL (backend ✔) | `rooms.py` derivation with cycle detection. |
| R-11 | Stay periods | PARTIAL (backend ✔) | Per-night period resolution; grid `apply_rate_change` splits periods into a draft. |
| R-12 | Sale vs stay date | PARTIAL (backend ✔) | `sale_at` drives version/markup/promo/FX selection; simulator. |
| R-13 | Markets | PARTIAL (backend ✔) | `resolve_market` — explicit > country > default, ambiguity refused, never silent. |
| R-14 | Contract vs selling price | PARTIAL (backend ✔) | Markup REPLACE/STACK with specificity; cost/margin only with `price.view_cost`. |
| R-15 | Currency engine | PARTIAL (backend ✔) | FX policies manual/TCMB/ECB/provider ± adjustment, snapshot per booking; TCMB/ECB parsers unit-tested; scheduler fetch 15:45/17:45. |
| R-16 | Restrictions | PARTIAL (backend ✔) | Stop-sell modes, Min/MaxLOS, CTA/CTD, release, advance windows (`availability/restrictions.py`). |
| R-17 | Inventory | PARTIAL (backend ✔) | Pools + allotments, row locks + locking recount; real two-connection race test. |
| R-18 | Promotions | PARTIAL (backend ✔) | Exclusive/priority/groups/stackable, SEQUENTIAL/ADDITIVE, usage limits with locks. |
| R-19 | Extras | PARTIAL (backend ✔) | 12 pricing modes (`extras.py`), online-bookable filter in guest API. |
| R-20 | Coupons | PARTIAL (backend ✔) | Code promotions with per-guest limits (email hash). Legacy voucher migration (T6) NOT STARTED. |
| R-21 | Modification & repricing | PARTIAL (backend ✔) | OLD vs PROPOSED, 4 bases, signed proposal, re-check under lock (`services/modification.py`). |
| R-22 | Historical simulator | PARTIAL (backend ✔) | `modification.simulate`; read-only. |
| R-23 | Revision history | PARTIAL (backend ✔) | `TEX Reservation Revision` per change + audit event. |
| R-24 | TEX CRS | PARTIAL (backend ✔) | `api/crs.py` multi-hotel search/quote/book/modify/cancel within scope. UI pending. |
| R-25 | Call Center | NOT STARTED (UI) | Backend = CRS API; keyboard-first screen pending. |
| R-26 | Booking guest experience | PARTIAL (backend ✔) | `api/public.py`; guest booking app pending. |
| R-27 | Booking search | PARTIAL (backend ✔) | Rate-limited search, market resolution, currency whitelist. |
| R-28 | Room/rate results | PARTIAL (backend ✔) | Offers without internals (no contract ids, cost or explanation). |
| R-29 | Multi-room | PARTIAL (backend ✔) | Multi-quote booking, per-pool per-night demand check. |
| R-30 | Embeddable booking | PARTIAL | `admin.embed_snippet`, `allowed_embed_origins`; web component pending. |
| R-31 | Custom domains | PARTIAL (backend ✔) | DNS TXT verification over DoH (`services/sites.py`); `verified` cannot be set by editing (test). |
| R-32 | White label | PARTIAL (backend ✔) | Validated tokens only (#RRGGBB, enums); no CSS/JS injection field. |
| R-33 | Admin UI direction | NOT STARTED | |
| R-34 | Design system | NOT STARTED | |
| R-35 | Admin navigation | NOT STARTED | `TEX Settings.show_legacy_pms` exists for hiding PMS modules. |
| R-36 | Rates & inventory grid | PARTIAL (backend ✔) | `commercial/grid.py` read + bulk update; UI pending. |
| R-37 | CRM | PARTIAL (backend ✔) | `crm/service.py` scoped guests, audited consent, whitelisted segments, consent-gated export. |
| R-38 | Abandoned booking | PARTIAL (backend ✔) | Funnel events → `detect_abandoned` (anonymous without consent), recovery marking, 180-day purge. |
| R-39 | Loyalty | PARTIAL (backend ✔) | `crm/loyalty.py` earn (money/nights/stay/room/extra, tiers, blackouts), pending→available, redeem as payment, reversal floor at 0, expiry. |
| R-40 | Payments | PARTIAL (backend ✔) | Mock/bank transfer/pay-at-hotel/iyzico/Sipay/NestPay adapters; hosted flows only; verified callback; idempotent. **iyzico/Sipay/NestPay not production-verified** (needs merchant sandbox credentials). |
| R-41 | Payment links | PARTIAL (backend ✔) | Create/replay/pay/expire/cancel, allocation to booking; tests. |
| R-42 | Guest self-service | PARTIAL (backend ✔) | Manage token (sha256 at rest); cancel/propose/apply; lower price → staff approval by default; payment retry. Pages pending. |
| R-43 | Enterprise / user model | PARTIAL (backend ✔) | Enterprise→Group→Hotel, grants with anti-escalation, profiles, strict tenancy; admin UI pending. |
| R-44 | TEX Connect | PARTIAL (backend ✔) | Transactional outbox, adapter registry (webhook PMS, sandbox), retry/dead-letter, admin endpoints. No vendor-specific adapters yet. |
| R-45 | Quote engine | PARTIAL (backend ✔) | HMAC offer keys, persisted quotes with TTL. |
| R-46 | Price lock | PARTIAL (backend ✔) | Reservation snapshot + lock guard; legacy prices locked by patch p04. |
| R-47 | Dashboard | PARTIAL (backend ✔) | `reports/service.dashboard`; UI pending. |
| R-48 | Reports | PARTIAL (backend ✔) | Production by stay/booking date, prorated, per currency, 11 groupings; pace. |
| R-49 | i18n | NOT STARTED | tr/en/de/ru/ro/pl catalogs pending with UI. |
| R-50 | Responsive | NOT STARTED | |
| R-51 | Accessibility | NOT STARTED | |
| R-52 | Performance | PARTIAL | Indexes (p03), per-request scope cache, terms cache. Load testing pending. |
| R-53 | Security | PARTIAL | Capability checks on all TEX endpoints; legacy `require_roles` now enforces hotel scope for property/reservation/folio/room/room_type/group_booking args; permission hooks for Desk lists; open-redirect guard; semgrep clean. Remaining: see SECURITY_MODEL §6. |
| R-54 | Audit trail | PARTIAL (backend ✔) | `TEX Audit Event` for commercial, payment, consent, grant and settings actions; viewer API. |
| R-55 | UX productivity | NOT STARTED | |
| R-56 | Migrations | PARTIAL | p01–p04 done (foundation, access grants, indexes, lock legacy prices). T6 vouchers, T7 experiences, T8 legacy contracts NOT STARTED. |
| R-57 | Testing | PARTIAL | Unit + integration as above. Frontend tests pending. |
| R-58 | E2E (Playwright) | PARTIAL | 19-step journey proven at service level; browser E2E pending UI. |
| R-59 | Visual QA | NOT STARTED | |
| R-60 | Implementation order | — | Followed: pricing → contracts → CRS → booking → payments → CRM (backend first). |
| R-61 | Process rules | — | Small commits, docs updated per milestone. |
| R-62 | Definition of done | — | Tracked here. |
