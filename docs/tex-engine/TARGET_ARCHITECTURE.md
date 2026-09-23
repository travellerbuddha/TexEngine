# TEX Engine — Target Architecture

Status: authoritative design. Decisions and their rationale are in
`ARCHITECTURE_DECISIONS.md` (ADR-NNN references below).

```
                               TEX ENGINE
        ┌───────────────┬──────────────┼──────────────┬───────────────┐
     TEX CRS     TEX Call Center   TEX Booking      TEX CRM      Admin (Rates,
   (group search)  (agent desk)   (guest + widget) (profiles,    Contracts, Grid,
        │               │              │           segments,     Reports, Settings)
        └───────────────┴──────┬───────┴───────────loyalty)──────────┘
                               │  kamra/tex/api/*  (whitelisted, capability-checked)
                    ┌──────────┴───────────┐
                    │  TEX services layer  │  quotes · bookings · modifications ·
                    │  (Frappe glue)       │  revisions · simulator · payments
                    └──────────┬───────────┘
           ┌───────────────────┼──────────────────────────┐
   TEX PRICING ENGINE    AVAILABILITY / INVENTORY     TEX PAYMENTS
   kamra/tex/pricing     kamra/tex/availability       kamra/tex/payments
   (pure Python, no      (pure evaluation +           (provider abstraction,
    frappe imports)       locked Frappe queries)       links, ledger)
                               │
                          TEX CONNECT  kamra/tex/connect (outbox + adapters)
                ┌──────────────┼──────────────┬──────────────┐
               PMS      Channel Manager     FX (TCMB/ECB)   Email/SMS/WhatsApp
```

## 1. Layers and boundaries

| Layer | Location | Rules |
|---|---|---|
| Money primitives | `kamra/tex/money.py` | `Decimal` only; currency minor units; rounding policy. No frappe. |
| Pricing domain | `kamra/tex/pricing/` | Pure functions over immutable dataclasses. **No frappe import** (enforced by a unit test). Deterministic: same inputs → same `Quote`, byte-identical explanation. |
| Availability domain | `kamra/tex/availability/` | `restrictions.py` and `inventory_math.py` are pure; `repository.py` does Frappe queries and row locks. |
| Commercial repository | `kamra/tex/commercial/` | Loads DocTypes into pricing dataclasses; contract publishing (freeze + hash); effective-dated revision helpers. |
| Services | `kamra/tex/services/` | Quote, booking, modification, revision, simulator, self-service. Owns transactions and locks. |
| Security | `kamra/tex/security/` | Capability registry, scope resolution (Platform → Enterprise → Group → Hotel), decorators, audit events. |
| Payments | `kamra/tex/payments/` | Provider interface + providers (mock, bank transfer, pay-at-hotel, iyzico, Sipay, virtual POS), links, ledger, webhooks. |
| CRM | `kamra/tex/crm/` | Segments DSL, funnel/abandoned tracking, loyalty ledger, consent. |
| Connect | `kamra/tex/connect/`, `kamra/tex/distribution/` | Transactional outbox + adapter registry (PMS, FX, messaging); channel distribution (ADR-039). |
| API | `kamra/tex/api/*.py` | Thin whitelisted endpoints: parse → authorise → call service → serialise (money as strings). |
| DocTypes | `kamra/tex_platform`, `kamra/tex_commercial`, `kamra/tex_booking`, `kamra/tex_payments`, `kamra/tex_crm`, `kamra/tex_connect` | Frappe modules; controllers only validate/guard, logic lives in services. |
| Frontend admin/CRS/Call Center | `frontend/src/tex/` | TEX design system (`tex/ui`), TEX shell/nav, screens. Never computes authoritative prices. |
| Guest booking + widget | `frontend/src/booking/`, `frontend/src/widget/` | Separate Vite entries (small bundles); widget = Shadow DOM web component. |

Dependency direction: `api → services → (pricing | availability | payments | crm | connect) → money`.
`pricing` depends only on `money` and the standard library.

## 2. Commercial data model

```
TEX Enterprise ─< TEX Hotel Group ─< Property (hotel)
                                         │
TEX Market (global master) ──────────────┤
TEX Sales Channel (global master) ───────┤
                                         ├─< TEX Contract (property, market, currency, basis, sale/stay window, channels)
                                         │        └─< TEX Contract Version (Draft → Published → Superseded)
                                         │               ├─ Contract Rooms (base/derived, capacities)
                                         │               ├─ Price Periods (stay date ranges, adjustments)
                                         │               ├─ Period Rates (room × period price / override)
                                         │               ├─ Occupancy Rules (adult/child slots, combinations)
                                         │               ├─ Child Age Bands (or inherited policy, frozen)
                                         │               ├─ Board Rules (base board + supplements)
                                         │               ├─ Contract Rate Plans (NRF/flex adjustments, policies)
                                         │               ├─ Contract Offers (EB, long stay… stage COST|SELL)
                                         │               └─ payload (frozen JSON) + payload_hash (sha256)
                                         ├─< TEX Pricing Policy (hotel/market defaults; revisioned)
                                         ├─< TEX Markup Rule (scope: market/contract/room/dates/channel; revisioned)
                                         ├─< TEX Promotion (automatic or code/coupon; revisioned) ─< Redemption
                                         ├─< TEX FX Policy (revisioned) ── TEX FX Rate (immutable provider rows)
                                         ├─< TEX ARI Restriction (daily cell, scoped, tri-state)
                                         ├─< TEX Inventory Day (pool × date; lock row) · TEX Allotment
                                         ├─< TEX Extra (+ price rules) · TEX Cancellation Policy · TEX Payment Policy
                                         └─< TEX Booking Site (white label, domains, widget origins)
```

### 2.1 Contract versioning (ADR-004)
- A version is edited only in **Draft**. `publish` validates it, resolves every
  inherited default (hotel/market Pricing Policy, room capacities) and writes the
  canonical `payload` JSON + `payload_hash`. From then on the version is read-only.
- `effective_from` (datetime) = sale time from which it is the active version.
  Resolver for sale time *T*: latest Published/Superseded version of the contract
  with `effective_from <= T` and (`superseded_at` is null or `> T`).
- Pricing always runs on the frozen payload, never on the child tables.
- "Edit" of a published version = `new_draft_from(version)` (copy) → publish V+1.

### 2.2 Effective-dated selling policies (ADR-005)
Markup rules, promotions, FX policies and pricing policies carry
`tex_status (Draft/Active/Superseded/Archived)`, `active_from`, `active_to`,
`revision_of`, `revision_no`. Active records are never edited in place: `revise`
clones → Draft; `activate` stamps `active_to=now` on the predecessor. As-of
queries (`active_from <= T < active_to`) power the historical simulator.

## 3. Pricing pipeline (ADR-006)

Per requested room: `QuoteRequest(property, room_type, board, rate_plan,
check_in, check_out, adults, children[age|dob], market, channel, sale_at,
sell_currency, promo_codes, extras)`.

Per night *n*:
1. **StayPeriodResolver** — period containing *n* (weekday-filtered). None → unsellable.
2. **RoomPricingResolver** — `unit` for (room, period): most specific of
   (room, period) > (room, *) rule; ops ABSOLUTE / MULTIPLY / ADJUST_PERCENT / ADD /
   SUBTRACT relative to the referenced base room (recursive, cycle-checked) / INHERIT.
3. **ChildAgeResolver** — each child → band via integer months at arrival (or booking date per policy).
4. **OccupancyResolver** — slot model:
   - PERSON basis: every occupant is a slot priced against `unit` (base person rate).
   - ROOM basis: `unit` covers the first `included_adults` adults; further adults and
     children are extra slots priced against `unit / included_adults`; under-occupancy
     via combination rules (e.g. 1A = 80 % of room).
   - Rule lookup per slot by specificity: OVERRIDE(combination+room+period) >
     COMBINATION > PERIOD > ROOM > VERSION > MARKET/HOTEL policy (frozen) > GLOBAL default
     (adult ×1.00; children have **no** global default → unsellable with a clear reason).
   - Combination-level ABSOLUTE sets the whole room-night occupancy amount.
5. **Board** — base board included; supplements per adult/child (child % by band, infants free unless set).
6. **Period / weekday adjustment** on the night amount.
7. **Rate plan adjustment** (e.g. NRF −10 %).
   → night **contract cost** (contract currency).

Stay level:
8. **COST-stage offers** (contract offers flagged COST).
9. **MarkupResolver** per night (scope: channel, room, contract, market, hotel, global; REPLACE by
   default, STACK only when the rule says so) → contract-currency **selling** amount.
10. **CurrencyResolver** — FX policy as of sale time: manual / provider / provider+% / provider+fixed →
    snapshot `{provider, rate_date, provider_rate, adjustment, sell_rate}`.
11. **PromotionResolver** — eligibility (sale window, stay window with ANY/ALL/ARRIVAL/DEPARTURE
    matching, lead time, LOS, market, channel, room, board, rate plan, member, code, min basket);
    combination (exclusive → priority → incompatible groups → stackable; SEQUENTIAL or ADDITIVE
    stacking); every candidate gets an `applied` or `rejected: reason` record.
12. **ExtrasPricingResolver** — per extra pricing mode (reservation/room/person/adult/child/infant/
    night/stay/service date/unit/usage), market/room/date price rules, inventory check hook.
13. **Coupons** — code promotions on accommodation/extras/package/total basket.
14. **TaxResolver** — per line tax rules (inclusive or exclusive, compound flag).
15. **Rounding** — lines quantized to currency minor unit (ROUND_HALF_UP); totals = Σ rounded lines.
16. **PriceExplanationBuilder / QuoteBuilder** — typed `Quote` with nightly breakdown, lines,
    promotions applied/rejected, margin (cost vs sell in sell currency), full explanation.

## 4. Availability & inventory (ADR-008)
- **Restrictions**: daily `TEX ARI Restriction` cells scoped by
  (property, room_type, contract, market, rate_plan, channel). Effective value per field = the
  non-null value of the most specific cell; specificity weights contract 16, room 8, rate plan 4,
  market 2, channel 1 (unique sums → no ties). Stop sell is tri-state (inherit/Stop/Open) with mode
  (stay-through/arrival/departure). MinLOS/MaxLOS arrival-based by default.
- **Inventory**: pool per room type (or shared pool). Capacity per date = physical sellable rooms
  (or configured count) + manual adjustment + explicit oversell limit − closed.
  Allotments cap per-contract sales and, when *guaranteed*, withhold rooms from the free pool until
  release (arrival − release_days).
- **Concurrency**: booking locks `TEX Inventory Day` rows (`SELECT … FOR UPDATE`) for every night in
  ascending date order (deadlock-free), recounts live reservation nights under the lock, then inserts.
  Rows are created lazily with `INSERT IGNORE` before locking.

## 5. Quote → Hold → Book → Pay → Confirm (ADR-009)
- **Search** returns offers with an `offer_key` (HMAC-SHA256 signed compact reference + expiry);
  no DB writes on search.
- **Quote** (`TEX Quote`) persisted when an offer is selected: re-priced server-side from the
  signed inputs; price change vs. the offer is reported, never hidden.
- **Hold** (optional): reservations in `Held` with `hold_expires_on` (existing expiry cron).
- **Book**: `TEX Booking` parent + one `Reservation` per room; each reservation stores the full
  pricing snapshot, contract version, payload hash, FX snapshot, sale timestamp.
- **Pay**: payment intent via provider; on success → `Confirmed`, `tex_price_locked=1`,
  `tex_accepted_at`.
- Idempotency keys on book/pay endpoints and webhooks.

## 6. Modification, revisions, simulator (ADR-010)
- `propose_modification(reservation, changes, basis)` → OLD vs PROPOSED + difference + explanation;
  bases: ORIGINAL_VERSION, ORIGINAL_SALE_DATE, HISTORICAL_SALE_DATE(date), CURRENT.
- `apply_modification(proposal_token, reason, override?)` → availability re-check under lock →
  `TEX Reservation Revision` (actor, time, field diffs, old/new amount, basis, reason, approval) →
  reservation + snapshot updated. Manual override needs `price.override` + reason.
- Legacy `auto_price` never reprices a TEX-priced or locked reservation.
- **Simulator**: rebuild the request, resolve the contract version and selling policies as of the
  chosen sale time, run the engine; read-only.

## 7. Security model
See `SECURITY_MODEL.md`. Capabilities checked in the backend per property scope; tenancy
Enterprise → Hotel Group → Hotel; audit events for every commercial action.

## 8. Frontend
- Admin SPA (`/tex/*`, `/kamra/*` kept as alias): TEX shell with the spec navigation; PMS screens
  hidden unless the site enables legacy PMS modules.
- TEX design system in `frontend/src/tex/ui` (tokens as CSS variables, components).
- Guest booking: separate entry `booking.html` served at `/book/<site>`; mobile-first.
- Widget: `tex-widget.js` web component `<tex-booking-widget site="…">` rendering into Shadow DOM;
  full flow opens in a modal iframe or redirects (ADR-012).
- i18n: TEX catalogs `tr, en, de, ru, ro, pl` with `Intl` formatting (ADR-013).

## 9. Integrations (TEX Connect)
- Transactional outbox (`TEX Integration Outbox`) written in the reservation transaction; worker
  delivers via adapters with retries/backoff; adapter registry per category
  (PMS: `push_reservation`, `modify_reservation`, `cancel_reservation`, `fetch_availability`).
- Channel distribution is TEX's own, provider-neutral layer (`kamra/tex/distribution/`, ADR-039):
  mappings, ARI computed from TEX and pushed as changes, signed idempotent inbound bookings, error
  queue, reconciliation. The legacy Kamra channel-manager adapters (Channex, STAAH, AioSell) are
  NOT used for TEX hotels and refuse them (ADR-028, G-15, G-87); a real provider is a new
  `ChannelAdapter` subclass, certified before it may run in Production.

## 10. Testing
- Unit (pure): `kamra/tex/tests/unit` — pricing, restrictions, inventory math, FX, promotions,
  child ages, precedence, determinism, no-frappe import guard.
- Integration (bench): `kamra/tex/tests/integration` — DocTypes, publishing/immutability,
  booking + concurrency, revisions, simulator, permissions/tenant isolation, payments (mock).
- Upstream suites kept: eval harness, front-desk journey, banquet tests.
- E2E: Playwright `frontend/e2e` critical journey + mobile booking.
