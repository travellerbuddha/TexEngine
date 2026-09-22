# TEX Engine — Architecture Decision Records

Format: context → decision → consequences. Status: Accepted unless noted.
Add new ADRs at the end; never rewrite an accepted ADR — supersede it.

---

## ADR-001 Keep the Frappe app name `kamra`; brand the product as TEX Engine
**Context.** Renaming a Frappe app changes the Python package, module paths, DocType
`module` values, `tabModule Def`, patches and every installed site; it breaks
upstream cherry-picks and existing data.
**Decision.** The app/package stays `kamra`. All customer-facing surfaces (SPA shell,
navigation, booking engine, emails, docs) say **TEX Engine**. New code lives under
`kamra/tex/` (domain) and `kamra/tex_*` (Frappe modules). Upstream copyright headers stay.
**Consequences.** Zero migration risk; internal identifiers still say "kamra" in places.

## ADR-002 Pure-Python pricing core
**Context.** `kamra/pricing.py` mixes DB reads with arithmetic, returns floats, and cannot
be tested without a live site. TEX pricing is the product's core and must be deterministic,
reproducible and heavily tested.
**Decision.** `kamra/tex/pricing/` contains only immutable dataclasses and pure functions
over `Decimal`. It never imports `frappe` (a unit test enforces this). A loader in
`kamra/tex/commercial/` converts DocTypes/frozen payloads into those dataclasses.
**Consequences.** Hundreds of fast unit tests run with plain `pytest`; the same engine prices
live quotes, historical simulations and modification proposals.

## ADR-003 Money = Decimal; strings on the wire
**Decision.** `kamra.tex.money` provides `D()`, `Money`, minor-unit table (TRY/EUR/GBP/USD 2,
JPY 0, KWD 3 …), `quantize()` with ROUND_HALF_UP. Intermediate values keep full precision; each
output line is rounded once; totals are the sum of rounded lines. APIs serialise money as decimal
strings. DB columns are Frappe `Currency` (decimal(21,9)); values read back through
`money.from_db()` which re-quantizes. FX rates are stored with 6+ decimal places.
**Consequences.** No float arithmetic in TEX code paths; legacy Kamra float paths remain for
legacy screens only.

## ADR-004 Immutable, published contract versions with frozen payloads
**Context.** Pricing edits must never alter sold reservations; historical prices must be
reproducible.
**Decision.** Contract → Contract Version (Draft → Published → Superseded/Withdrawn). Child
tables are editable only in Draft. `publish` validates, resolves inherited defaults (hotel/market
pricing policy, room capacities) and stores canonical JSON `payload` + `payload_hash` (sha256 of
the canonical serialisation). The engine prices from the payload only. `effective_from` defines the
sale time from which the version is active; resolution for sale time *T* picks the latest version
with `effective_from <= T` not superseded before *T*. Hotel-policy changes reach a contract only via
re-publishing (the UI flags stale versions).
**Consequences.** Reservations store `(contract_version, payload_hash)`; re-pricing a historical
reservation re-runs the engine on the same payload.

## ADR-005 Effective-dated revisions for selling policies
**Decision.** Markup rules, promotions/coupons, FX policies and pricing policies use a revision
pattern: `tex_status`, `active_from`, `active_to`, `revision_of`, `revision_no`. An Active record is
never edited in place (controller blocks it); `revise()` clones to Draft; activation stamps the
predecessor's `active_to`. As-of queries reconstruct the rule set at any past sale time.
**Consequences.** The historical simulator is deterministic. Restrictions and inventory are
operational data (not effective-dated); simulations evaluate price, not historical availability
(documented limitation).

## ADR-006 Pricing pipeline, rule operations and precedence
**Decision.** Pipeline and stage order as in TARGET_ARCHITECTURE §3 (cost → COST offers → markup
→ FX → SELL promotions → extras → coupons → tax → rounding). Operations are an explicit enum:
`INHERIT, ABSOLUTE, MULTIPLY, PERCENT_OF, ADJUST_PERCENT, ADD, SUBTRACT, FIXED`.
- `PERCENT_OF v`: result = reference × v/100 (a share: "child pays 50 %").
- `ADJUST_PERCENT v`: result = input × (1 + v/100) ("+10 %", "−15 %").
- `MULTIPLY v`: result = reference × v. `ADD/SUBTRACT v`: ± money. `ABSOLUTE/FIXED v`: set money.
- `INHERIT`: no value at this scope; defer to the next less specific scope.
Occupancy, room-derivation and markup rules are **most-specific-wins (REPLACE)**. Markup rules
may explicitly declare `STACK`; periods/weekday adjustments and rate-plan adjustments are
distinct pipeline steps, never hidden stacking. Scope levels (low→high):
`GLOBAL, HOTEL, MARKET, CONTRACT, VERSION, ROOM, PERIOD, COMBINATION, OVERRIDE`; a rule's level is
derived from which qualifiers it sets, and every explanation step records the winning rule, its
level and the rules it overrode.
**Consequences.** "Which rule won" is always answerable; tests pin precedence.

## ADR-007 Occupancy slot model and child ages in integer months
**Decision.** Occupancy is priced as slots (adult positions 1..n, child positions 1..n ordered by
the version's `child_ordering`, default OLDEST_FIRST). PERSON basis: all slots priced against the
base-person unit. ROOM basis: the room price covers `included_adults`; extra slots priced against
`unit / included_adults`; combination rules handle under-occupancy. Combination rules key on exact
`(adults, children)` counts; valid combinations derive from room capacities (never a hardcoded
list). No global child default exists — an unconfigured child band makes the offer unsellable with
an explicit reason (financial safety). Ages are integer months: DOB+reference date → completed
months; declared age *N* → 12N; bands are `[from_months, to_months)`; band `0–2.99` is stored as
`from_age 0, to_age 3` (exclusive). Reference date = arrival unless the version's `age_basis`
is BOOKING_DATE. Children above the top band count as adults (configurable).
**Consequences.** No float comparisons; 2.99/3.00 boundaries are exact.

## ADR-008 Restrictions as scoped daily cells; inventory lock rows
**Decision.** `TEX ARI Restriction` stores one row per (property, room_type, contract, market,
rate_plan, channel, date) with tri-state/zero-means-inherit fields. Effective value = most specific
non-null cell (weights contract 16, room 8, rate plan 4, market 2, channel 1). Inventory is guarded
by locking `TEX Inventory Day` rows per night (ascending date order) and recounting live
reservations under the lock; allotments cap per contract, guaranteed allotments withhold rooms until
release.
**Consequences.** Grid editing = upserting cells; double-selling prevented at DB level.

## ADR-009 Signed offers, persisted quotes, multi-room TEX Booking
**Decision.** Search returns HMAC-signed `offer_key`s (no DB writes). Selecting an offer persists a
`TEX Quote` (server re-prices; price change is surfaced). A `TEX Booking` parent owns 1..n
`Reservation`s (one per room). Each reservation stores the pricing snapshot, contract version,
payload hash, FX snapshot, sale timestamp; confirmation sets `tex_price_locked`.
**Consequences.** Cheap searches, authoritative quotes, clear parent/child booking structure.

## ADR-010 Modification = proposal + revision; legacy auto-price neutralised for TEX
**Decision.** Reservation changes go through `propose_modification` (read-only OLD vs PROPOSED) and
`apply_modification` (writes `TEX Reservation Revision`). The legacy `Reservation.apply_pricing`
(auto_price) no longer runs for TEX-priced or price-locked reservations, and for legacy
reservations only when pricing inputs change.
**Consequences.** Kamra's legacy behaviour of silently re-pricing on every save is removed for TEX.

## ADR-011 Capability-based authorisation with hierarchical scope
**Decision.** A code registry of capabilities (`price.view`, `contract.publish`, …). Users get
capabilities from (a) default profiles mapped to their Frappe roles and (b) `TEX Access Grant`s
(user × scope level Platform/Enterprise/Hotel Group/Hotel × `TEX Permission Profile`). Grants sync
Frappe `User Permission`s on Property so Desk/list queries stay isolated. Every TEX endpoint calls
`require_capability(cap, property)`. The legacy `require_roles` decorator is upgraded to enforce
property scope for any `property`/document argument it can resolve. `TEX Settings.strict_tenancy`
(default on) denies property access to users without explicit scope.
**Consequences.** Backend-enforced, per-hotel permissions; legacy endpoints gain tenant checks.

## ADR-012 Guest booking as a separate bundle; widget via Shadow DOM + iframe
**Decision.** The guest booking engine is its own Vite entry (`booking.html`, served at
`/book/<site>`), mobile-first, independent of the admin bundle. The embeddable search widget is a
custom element `<tex-booking-widget>` rendered into a Shadow DOM with CSS custom properties from
the site's branding tokens (no host CSS leakage either way); "Book" opens the full flow in a modal
iframe (payment isolation, CSP) or redirects. Branding is limited to safe tokens (no arbitrary CSS/JS).
**Consequences.** Fast guest pages; works in WordPress/HTML/React/CMS hosts.

## ADR-013 TEX i18n catalogs
**Decision.** TEX screens use `frontend/src/tex/i18n` with JSON catalogs for `en, tr, de, ru, ro,
pl`, `t(key, params)` with plural support and `Intl` number/date/currency formatting. Server-side
guest-facing strings use Frappe `_()`. Legacy Kamra screens keep the existing en/ar mechanism.

## ADR-014 Hide, don't delete, PMS modules
**Decision.** TEX navigation omits housekeeping, laundry, POS, banquet, night audit, maintenance
tickets and cashier screens. Routes stay reachable only when `TEX Settings.show_legacy_pms` is on.
Schedulers that are PMS-only keep running only when their module is enabled.

## ADR-015 Transactional outbox for integrations
**Decision.** Reservation create/modify/cancel writes `TEX Integration Outbox` rows in the same DB
transaction; a scheduled worker delivers them through adapters with exponential backoff and
dead-lettering. Core reservation code never calls vendors directly.

## ADR-016 Payments: provider interface, no card data at rest
**Decision.** `PaymentProvider` interface (`create_checkout`, `handle_callback`, `refund`,
`capabilities`). Providers: Mock (deterministic sandbox), Bank Transfer, Pay at Hotel, iyzico,
Sipay, Turkish virtual POS (3D Secure). Hosted/tokenised flows only; TEX stores at most card brand +
last4. Transactions are idempotent (`idempotency_key` unique). Without real credentials the
iyzico/Sipay/POS adapters run only in sandbox mode and are marked NOT production-verified.

## ADR-017 Signed guest self-service tokens
**Decision.** Manage-booking magic links carry a random 32-byte token; only its sha256 is stored
with expiry; tokens are rotated on use for sensitive actions; rate limited. Lower-price changes never
auto-refund unless the property policy explicitly allows it; they create a pending staff task.

## ADR-018 Test environment
**Decision.** Development/CI bench: Frappe v16.25.0, Python 3.14, Node 24, MariaDB, Redis, apps
`payments` + `kamra`. Pure tests run without a bench. See `DEV_ENVIRONMENT.md`.
