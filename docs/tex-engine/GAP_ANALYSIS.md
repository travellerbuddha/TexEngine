# TEX Engine — Gap Analysis (Phase 0 audit)

Audit of Kamra PMS `develop` @ `418ed1a` against `PRODUCT_SPEC.md`. Every claim below
was verified in code (file:line references), not taken from README text.

## 1. Baseline facts

| Area | What exists (verified) | Location |
|---|---|---|
| Framework | Frappe v16 app `kamra`, 95 DocTypes, one module `Kamra` | `kamra/modules.txt`, `kamra/kamra/doctype/` |
| Backend size | ~21.5k lines Python in `kamra/*.py`; `api.py` alone 4,254 lines, 120 whitelisted endpoints | `kamra/api.py` |
| Pricing | `kamra/pricing.py` (363 lines): room-type occupancy price → season adjust → hurdle/demand premium → rate-plan modifier → meal plan → voucher → tax. Returns **floats**; reads DB inside the loop; no contracts, markets, versions, FX, child bands, markup, promotions engine | `kamra/pricing.py:19-363` |
| Occupancy | `base_price`, `base_occupancy`, `single_occupancy_price`, `extra_adult_price`, single `child_price`, `free_child_age`, `child_age_limit` on Room Type. Children priced flat; ages only used to drop "free" children in `Reservation.apply_pricing` | `pricing.py:19-35`, `reservation.py:183-216` |
| Seasons | `Season` (date range, % / amount / absolute, weekdays, priority, optional room type, most-specific-wins) | `pricing.py:111-151` |
| Price snapshot | `quote_snapshot` JSON written on **every save** while `auto_price=1` — the price is recomputed from current tables on any edit | `reservation.py:171-229` |
| Reservation lifecycle | Status machine (Inquiry→Quoted→Requested/Held/Pending Payment→Confirmed→Checked In/Out, Cancelled, No Show, Waitlist), idempotency key, hold expiry cron | `kamra/reservation_state.py` |
| Concurrency | Room-row lock + `FOR UPDATE` overlap check for **assigned** rooms; SIU row locks; room-type capacity check (`validate_type_capacity`) is an **unlocked** read → race for unassigned bookings | `reservation.py:41-85, 311-353` |
| CRS | `crs_search`: loops permitted properties × room types, calls `quote` per type (N+1), no market/currency/channel/child ages/rooms count | `kamra/crs.py` |
| Public booking | `search_stay` + `book` (single room, single room type, rate-limited 10/h, pay at hotel / advance % / full), runs as `agent@kamra.local`, writes status with `db.set_value` (bypasses validation) | `kamra/public_api.py:298-782` |
| Multi-room | Only `Group Booking` (desk groups); no generic booking parent; public engine single-room | `api.py:3651-3729` |
| Vouchers | `Discount Voucher` percent/amount, validity, min nights, max uses | `pricing.py:162-186` |
| Add-ons | `Experience` (flat price + GST) → `Stay Addon` rows | `api.py:3500-3517` |
| Payments | Razorpay payment links for folios only (INR hardcoded), webhook HMAC only when secret set and not test mode; frappe/payments dependency | `kamra/payments.py` |
| FX | `Exchange Rate` used only by cashier currency desk; no FX in pricing; no provider | `kamra/ledger.py:763-905` |
| Tax | Localization packs (India GST slabs, Indonesia, Thailand, Malaysia, UAE, generic flat). No Türkiye pack | `kamra/localization/` |
| RBAC | Role decorator `require_roles` (roles: Front Desk, Housekeeping, Finance, Revenue Manager, Hotel Admin, Kamra Agent). No granular capabilities, no enterprise/group hierarchy | `kamra/authz.py` |
| Tenant isolation | `assert_property_access` used by only **3 of 156** property-/document-scoped endpoints; reads bypass User Permissions; `front_desk_snapshot` without property returns all properties; realtime broadcasts to everyone | audit, `crs.py:27`, `api.py:2041`, `realtime.py:17` |
| Audit | `Agent Action Log` via `savings.log_action`; `track_changes` on Reservation/Rate Plan/Season/Room Type/Property/Folio/Guest; many `db.set_value` writes skip Version | `kamra/savings.py` |
| Channel manager | Adapters Channex/STAAH/AioSell: push availability + 1 rate/day, parse webhooks; no restrictions pushed | `kamra/channel_manager.py`, `kamra/channels/` |
| Frontend | React 19 + Vite 6 + Tailwind 4, custom i18n (en/ar), ~70 authenticated routes, 9 "apps" in nav incl. HK/POS/laundry/banquet, hand-rolled UI kit (7 components) | `frontend/src/` |
| Tests | Eval harness 76 checks (live site), front-desk journey 13 checks, banquet IntegrationTestCase 101 tests, 4 pure-python test files | `kamra/scripts/eval_harness.py`, `kamra/tests/` |
| Migrations | `patches.txt` v23–v33 + legacy `bootstrap_*` scripts | `kamra/patches/` |

Baseline test run on the TEX dev bench (2026-09-22, unmodified upstream):
eval harness **76/76 passed**; front-desk journey **13/13 passed**; banquet tests
101 run — 2 errors caused by missing frappe asset bundle (`email.bundle.css`, environment
only, see IMPLEMENTATION_STATUS "Baseline").

## 2. Module classification

| Kamra area | Decision | Reason / TEX action |
|---|---|---|
| Reservation DocType + state machine | **MODIFY** | Core of TEX reservations. Add TEX fields (booking parent, contract/version, market, channel, board, FX, snapshot, lock, revision no). Neutralise legacy auto-reprice for TEX (ADR-010). |
| `pricing.py` | **KEEP (legacy) → REPLACE for TEX** | Keep as compatibility path for legacy callers (folio night posting, legacy screens, channel push). TEX quotes use `kamra/tex/pricing`. |
| Season, Hurdle Rate, Rate Guardrail | **KEEP (legacy) / DECOUPLE LATER** | Demand pricing (hotel occupancy %) is not the TEX occupancy engine; kept only for legacy path. |
| Rate Plan | **MODIFY** | Reused as sellable rate plan; add refundable/cancellation/payment policy links. |
| Meal Plan | **MODIFY** | Add board codes RO/BB/HB/FB/AI/UAI alongside legacy EP/CP/MAP/AP. |
| Room Type / Room | **KEEP** | Capacities/content used by contracts and booking engine. Physical rooms feed inventory pools. |
| Property | **MODIFY** | Add enterprise/group links, TEX settings (default market, self-service, tax profile). |
| Guest | **MODIFY** | Extend into CRM profile (language, country, market, consent, tags, preferences, loyalty). |
| Discount Voucher | **KEEP (legacy) → REPLACE** | Migrated into `TEX Promotion` (trigger = code) by patch; legacy path kept. |
| Experience / Stay Addon | **KEEP → REPLACE** | Migrated into `TEX Extra`; `Stay Addon` kept for folio posting. |
| CRS (`crs.py`) | **MODIFY/REPLACE** | New TEX CRS service on the TEX pricing/availability engine; keep `assert_property_access` API. |
| Public booking (`public_api.py`, `PublicBooking.tsx`) | **REPLACE** | New guest engine (multi-room, markets, currencies, extras, payments) + widget. Legacy endpoints kept until sites migrate. |
| Group Booking / blocks | **KEEP** | Desk group business; TEX Booking handles generic multi-room. |
| Folio, invoices, cashier, ledger, night audit | **HIDE / DECOUPLE LATER** | PMS accounting; hidden from TEX nav; TEX Payments ledger is independent. |
| Payments (Razorpay) | **KEEP (legacy) → REPLACE** | TEX Payments provider abstraction; Razorpay remains a legacy folio path. |
| Exchange Rate (cashier) | **KEEP** | Cashier desk only; TEX FX engine is separate (policies + provider rates). |
| Localization packs | **KEEP + extend** | Add Türkiye pack; TEX tax resolver reads data-driven tax rules. |
| Channel manager adapters | **KEEP / MODIFY** | Moved behind TEX Connect "Channel Manager" category. |
| RBAC (`authz.py`) | **MODIFY** | Upgrade decorator with property-scope enforcement; add capability model. |
| Housekeeping, laundry, POS, kitchen, banquet, tickets, lost & found, turnover, night audit, cashier till, petty cash, inventory (F&B stock) | **HIDE** | Not in TEX navigation (ADR-014). Code and schedulers untouched unless module enabled. |
| MCP tools / AI assistant | **KEEP / DECOUPLE LATER** | Must never compute prices (already deterministic); gated by roles. |
| Frontend shell/nav (`AppShell.tsx`, `lib/apps.ts`) | **REPLACE** | TEX shell + spec navigation + design system. |
| Frontend i18n | **MODIFY** | Add TEX catalogs (tr/en/de/ru/ro/pl). |
| Eval harness / tests | **KEEP** | Must stay green; TEX adds unit + integration + E2E suites. |

## 3. Gaps vs spec (summary)

| Spec | Gap | Severity |
|---|---|---|
| R-03/R-05 pricing engine, contracts, versions | Entirely missing | Critical |
| R-06/R-07/R-08 person/room basis, occupancy formulas, child bands | Missing (flat child price) | Critical |
| R-09/R-10/R-11/R-12 precedence, derived rooms, periods, sale vs stay | Missing (seasons only) | Critical |
| R-13/R-14/R-15 markets, markup/margin, FX | Missing | Critical |
| R-16 restrictions | Only property `minimum_nights`; no MinLOS/MaxLOS/CTA/CTD/stop sell | High |
| R-17 inventory pools/allotment + concurrency | Partial; unlocked capacity check | High |
| R-18/R-20 promotions/coupons | Voucher only | High |
| R-19 extras | Flat add-ons | High |
| R-21/R-22/R-23/R-46 modification, simulator, revisions, price lock | Missing; legacy silently reprices | Critical |
| R-24 CRS | Basic, N+1, no market/channel/children | High |
| R-25 Call Center | Missing | High |
| R-26–R-32 booking UX, multi-room, widget, domains, white label | Single-room legacy page; accent colour only | High |
| R-37–R-39 CRM, abandoned, loyalty | Guest list/journey only | Medium |
| R-40/R-41 payments, links | Razorpay folio links only | High |
| R-42 self-service | Pre-check-in token only | Medium |
| R-43 enterprise/user model | Missing; roles only | Critical (security) |
| R-44 TEX Connect | Channel adapters only | Medium |
| R-47/R-48 dashboards/reports | PMS-centric | Medium |
| R-49 i18n | en/ar only | Medium |
| R-53 security/tenant isolation | 153/156 endpoints without property checks | Critical |
