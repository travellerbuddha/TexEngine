# TEX Engine — Product Specification

This file is the **complete, authoritative requirements record** for TEX Engine.
It was transcribed from the Master Implementation Directive (2026-09-22).
Never ask the product owner to restate anything recorded here. Requirement IDs
(`R-xx`) are referenced from `IMPLEMENTATION_STATUS.md`.

---

## R-01 Source and identity

- TEX Engine is developed **from the Kamra PMS repository**
  (https://github.com/Kamra-PMS/kamra-pms, `develop`), preserving history and
  AGPL-3.0 licence/copyright notices. Baseline SHA is in `UPSTREAM_BASELINE.md`.
- Future upstream Kamra changes are **not** pulled automatically; they are reviewed first.
- Product name: **TEX Engine**. Modules: **TEX CRS, TEX Pricing, TEX Booking,
  TEX CRM, TEX Call Center, TEX Payments, TEX Connect**.
- TEX Engine is **not a PMS**. Commercial focus: CRS, advanced hotel contract
  management, advanced pricing, direct booking, reservation management,
  call-centre sales, CRM, payments, integrations.
- PMS functions (housekeeping, laundry, restaurant POS, maintenance, night-audit
  operations, physical front-desk cleaning workflows) must **not appear in standard
  TEX navigation**. Strategy: KEEP / MODIFY / REPLACE / HIDE / DECOUPLE LATER.
  Do not aggressively delete PMS code others depend on.
- Do not spend effort renaming low-level historical identifiers where that
  creates migration risk. Customer-facing product, navigation and design = TEX Engine.

## R-02 Architecture principles

- Conceptual stack: TEX CRS / TEX Booking / TEX CRM → **TEX Pricing Engine** →
  Availability/Inventory → **TEX Connect** → PMS / Channel Manager / Payments.
- API-first where practical. Business-critical rules live in backend/domain code.
- Frontend **never** authoritatively determines price, availability, discounts,
  restrictions, payment amounts or permissions. Frontend displays and requests; backend owns truth.
- No giant service. Clear domain boundaries: pricing, contracts, availability,
  inventory, reservations, payments, CRM, integrations. No circular deps.
  Explicit interfaces, typed structures. No authoritative pricing logic in React.

## R-03 TEX Pricing Engine (highest priority)

- Do not grow `pricing.py` into a giant conditional file. Modular pricing domain
  with clean separation, conceptually: ContractResolver, ContractVersionResolver,
  MarketResolver, CurrencyResolver, StayPeriodResolver, SalePeriodResolver,
  RoomPricingResolver, OccupancyResolver, ChildAgeResolver, MarkupResolver,
  PromotionResolver, ExtrasPricingResolver, RestrictionResolver, TaxResolver,
  PriceExplanationBuilder, QuoteBuilder (names may differ).
- All financial calculations **deterministic**. **Never** use an LLM to calculate
  prices. **Never** binary floating point for money — Decimal + decimal DB fields.
- Every price reproducible and explainable.

## R-04 Hotel contract management

- Contracts are first-class. Hierarchy: Hotel → Market → Contract → Contract
  Version → Stay Period → Room Pricing → Occupancy Rules → Restrictions → Promotions.
- Examples: Germany Summer 2027, United Kingdom Summer 2027, Türkiye Domestic 2027,
  Romania Early Booking 2027.
- A contract can contain: property, market, currency, booking/sale validity,
  stay validity, room types, board/meal plan, cancellation terms, payment rules,
  price periods, occupancy rules, markup, promotions, restrictions, sales channels.

## R-05 Contract versioning (mandatory)

- Pricing edits must never silently change existing reservations. Immutable/versioned
  contracts (V1, V2, V3, V4…). New reservations use the active version; a reservation
  sold on V2 keeps its original commercial snapshot.
- Never calculate historical reservations purely from today's mutable tables.
- Reservation pricing snapshot preserves: contract, contract version, market,
  booking date, stay dates, room, adults, children, child ages, currency, applied
  FX rate, pricing periods, occupancy rules, markup, promotions, extras, tax, final
  amount, quote timestamp, accepted timestamp. Historical decisions auditable.

## R-06 Base pricing modes

- ROOM-BASED (e.g. Standard €200 per room per night) and PERSON-BASED (base person
  €100; 2 adults = €200). Hotel selects the model.

## R-07 Occupancy formula engine (critical)

- Means **people occupying the room** — NOT hotel occupancy % / demand pricing.
- Calculation types: multiplier, percentage, fixed amount, absolute price, inherit, override.
- Example: base person €100; Adult1 ×1.00, Adult2 ×1.00, Adult3 ×0.70 → 3 adults €270.
  Children: 0–2.99 ×0.00; 3–6.99 ×0.25; 7–11.99 ×0.50.
- Rules may depend on the complete combination: 2A+1C(8y) child 50%, 1A+1C(8y)
  child 100%; 2A+2C child1 50%, child2 25%.
- Explicit combinations supported (1A…4A, 1A+1C, 1A+2C, 2A+1C, 2A+2C, 2A+3C, 3A+1C,
  3A+2C…) — **not hardcoded**; room capacities define valid combinations.
- Rules at: hotel, market, contract, room, price period, occupancy combination.
  More specific overrides general by explicit precedence.

## R-08 Child age engine

- Multiple configurable bands (Infant 0–2.99, Child A 3–6.99, Child B 7–11.99,
  Teen 12–15.99). Bands may differ by hotel, market, contract.
- Age evaluated at arrival/check-in unless policy explicitly chooses another basis.
- Aggressive boundary tests (2.99/3.00, 6.99/7.00, 11.99/12.00). No floating-age bugs.
  Prefer DOB + arrival date when DOB available.

## R-09 Price rule hierarchy

- GLOBAL → HOTEL → MARKET → CONTRACT → CONTRACT VERSION → ROOM → STAY PERIOD →
  OCCUPANCY COMBINATION → SPECIFIC OVERRIDE.
- Rules explicitly declare: inherit, replace, multiply, add, subtract, apply
  percentage, set absolute price. No ambiguous hidden stacking. Admin UI explains
  which rule won.

## R-10 Derived room pricing

- Base room priced; others derived (Superior ×1.15, Deluxe ×1.35, Suite ×1.80);
  base change propagates. Direct overrides win (Suite 01–15 Aug = €245 absolute).
  Supports multiplier, percentage, fixed adjustment, absolute value.

## R-11 Stay price periods

- Unlimited stay periods; periods may affect base price, room formula, occupancy
  rules, child rules, markup, promotions, restrictions. Efficient bulk editing;
  professional calendar/grid editing.

## R-12 Sale date vs stay date

- Separate concepts (stay 01 Jul–31 Aug; sale 01 Jan–31 Mar; EB −15%). Rules support
  booking date, check-in date, checkout date, stay-through dates, arrival date,
  departure date, length of stay.

## R-13 Markets

- First-class (TR, DE, UK, RO, PL, RU, CIS, DACH, EU, GLOBAL). Each may have
  independent contract, currency, markup, promotion, cancellation rules, payment
  methods, booking rules.
- Market source: user selection, residency/country, campaign/deep link, call-centre
  selection, API, configured business rules. **Do not silently assign a market where
  ambiguity creates financial risk.**

## R-14 Contract price vs selling price

- Keep both (contract cost €1,000 + markup 8% = selling €1,080). Markup types:
  percentage, multiplier, fixed. Varies by hotel, market, contract, room, period,
  channel. Margin reporting.

## R-15 Currency engine

- TRY, EUR, GBP, USD + extensible. FX modes: manual; external provider; provider +
  % adjustment; provider + fixed adjustment. Adapters: TCMB/CBRT, ECB, manual.
- Example: EURTRY provider 50, policy +2% → 51; or provider + 1.50 TRY.
- Cross-currency selling (EUR→TRY, GBP→EUR, USD→TRY…). Every accepted booking
  snapshots the exact FX rate used.

## R-16 Restrictions

- Stop Sell, Open Sale, MinLOS, MaxLOS, CTA, CTD, release days, booking window,
  minimum advance, maximum advance. Stop-sell modes: check-in, check-out, stay-through.
- Scope: hotel, room, market, contract, rate, Booking Engine, Call Center, both.
- Calendar-based bulk editing.

## R-17 Inventory

- Room-type inventory pools (Deluxe = 10). Allotment, cutoff, release, shared
  inventory, oversell limit (explicit), manual adjustment, audit history.
- Concurrency safety mandatory; prevent double-selling transactionally; never rely
  only on frontend checks.

## R-18 Promotion engine

- Early Booking, Last Minute, Long Stay, Member Discount, Promo Code, Market
  Promotion, Room Promotion, Package Promotion, booking-date, stay-date,
  arrival-based, departure-based.
- Values: percentage, fixed, multiplier, value-added.
- Combination: stackable, exclusive, priority, incompatible groups.
- Explain why each promotion was / was not applied.

## R-19 Extras / ancillaries

- Airport transfer, pavilion, à-la-carte, spa, late checkout, early check-in,
  birthday/honeymoon packages, room decoration, VIP service, excursion…
- Pricing modes: reservation, room, person, adult, child, infant, night, stay,
  service date, unit, usage.
- Vary by sale date, stay date, service date, market, currency, property, room, occupancy.
- Inventory, sell-out, open/close dates, mandatory, optional, bundled.
- Guests add eligible extras during and after booking.

## R-20 Coupons

- Apply to accommodation, extras, package, complete reservation. Percentage, fixed,
  usage limit, per-user limit, validity dates, market, room, hotel, minimum stay,
  minimum basket, channel, stacking rules.

## R-21 Reservation modification and repricing

- Authorised users modify sale date, check-in, checkout, room, adults, children,
  child ages, market, meal plan, extras, discount.
- Never silently rewrite price: show OLD vs PROPOSED and difference (+€520) with
  pricing explanation.
- Calculation bases (where permitted): original contract/version; original sale-date
  rules; selected historical sale-date rules; current active rules.
- Manual financial override requires permission + reason; audited.

## R-22 Historical pricing simulator

- "What would this reservation have cost if sold on 15 January?" Reconstruct
  historical contract version, market, booking-date promotions, stay pricing,
  occupancy rules, FX rules. Deterministic.

## R-23 Reservation revision history

- Revisions (1 original, 2 dates changed, 3 room upgraded, 4 extra added). Store
  actor, timestamp, change, old/new value, old/new amount, reason, approval where
  required. Never destroy historical state.

## R-24 TEX CRS

- Keep/improve Kamra CRS. Inputs: hotel/group, destination, check-in, checkout,
  rooms, adults, children, child ages, market, currency, sales channel.
- Results: hotel, room, meal plan, availability, cancellation, final selling price,
  promotion, restrictions, extras. Group search across all properties the user may sell.

## R-25 TEX Call Center

- Dedicated high-speed desktop/keyboard interface (not the guest booking engine).
  Flow: Search → Results → Select room/rate → Guest → Extras → Payment → Confirmation.
- Agent sees availability, rate, market, cancellation, promotion, restrictions,
  payment, guest history (where permitted), notes.
- Actions: create, edit, cancel reservation; add extras; send payment link; resend confirmation.
- Sales channel is a first-class pricing dimension (DIRECT_WEB, CALL_CENTER, API, B2B, META).
  Booking Engine and Call Center can share or differ in price, discounts,
  promotions, restrictions, inventory rules by configuration.

## R-26 TEX Booking — guest experience

- Complete redesign (not a reskin); premium current-generation hotel commerce.
  SiteMinder Direct Booking as UX inspiration only — **no cloning** of code,
  assets, icons, exact layouts or visual design. Original TEX design system.
- Flow: SEARCH → ROOMS/RATES → EXTRAS → GUEST DETAILS → PAYMENT → CONFIRMATION.
  Keep booking context visible; minimise steps.

## R-27 Booking search

- Check-in, checkout, rooms, adults, children, child ages (dynamic fields), promo
  code, currency, language; for groups: destination, hotel.

## R-28 Room/rate results

- Per room: gallery, name, size, occupancy, beds, amenities, cancellation policy,
  meal plan, promotion, taxes, total stay price, **truthful** scarcity.
- View room, compare rates, choose rate. Rates show refundable/non-refundable,
  board, payment policy, cancellation, inclusions, final total. No dark patterns.

## R-29 Multi-room booking

- Several rooms per booking, each priced independently (Room 1: 2A + child 5;
  Room 2: 1A + children 3 and 8). Booking → Reservation A/B/C with clear parent-child links.

## R-30 Embeddable booking (mandatory)

- Per-hotel integration: search widget, full booking where suitable, modal, button,
  redirect. Works in WordPress, plain HTML, React sites, common CMS.
- Avoid host CSS collisions (evaluate Shadow DOM, scoped CSS, isolated root, safe
  CSS variables). Responsive inside embedded contexts.

## R-31 Custom domains

- booking.texengine…, booking.hotel.com, hotel.com/book. No hardcoded domain
  assumptions in booking logic.

## R-32 White label

- Per hotel: logo, primary, secondary/accent colour, safe font, border radius, card
  radius, button style, header layout, search appearance, background, images,
  contact info, custom texts, policies. Safe design tokens; **no unrestricted
  CSS/JS injection by default**.

## R-33 Admin UI direction

- Modern professional hospitality-commerce feel, not generic ERP. SiteMinder admin as
  UX benchmark (navigation clarity, compact density, rate/availability grids, bulk
  editing, contextual controls, commercial dashboards) — original TEX identity.
- Avoid giant dashboard cards, empty whitespace, excessive gradients, toy UI, huge
  controls, modal-heavy workflows. Aim: compact, modern, premium, fast, clear,
  enterprise-ready, hotel-appropriate.

## R-34 TEX design system

- Reusable tokens/components: typography, spacing, colour, semantic status colours,
  borders, radius, elevation, tables, forms, inputs, selects, date pickers, buttons,
  tabs, chips, tooltips, drawers, dialogs, dropdowns, command palette, calendars,
  grids, loading, empty states, error states. Coherent system; accessible contrast.

## R-35 Admin navigation

- Dashboard · CRS · Reservations · Rates & Contracts · Inventory · Booking Engine ·
  CRM · Payments · Reports · Connect · Settings.
- Rates & Contracts: Contracts, Contract Versions, Price Periods, Occupancy Rules,
  Rate Plans, Markets, Promotions, Restrictions, Currency, Bulk Editor.
- Booking Engine: Configuration, Rooms, Content, Branding, Widgets, Domains,
  Policies, Analytics.
- CRM: Guests, Segments, Campaigns, Loyalty, Abandoned Bookings, Communications.
- Avoid unnecessary nesting depth.

## R-36 Rates & inventory grid

- Columns = dates; rows = room/rate combinations. Cells: rate, availability, MinLOS,
  Stop Sell, promotion indicator. Inline edit, date-range selection, bulk edit, copy
  period, weekday selection, multiple room/rates (e.g. 01–15 Jul Standard+Deluxe
  price +5%, MinLOS 4, Stop Sell false → Apply). Optimised; virtualise if needed.

## R-37 TEX CRM

- Guest profile: identity/contact, language, country, market, consent, stays,
  reservations, cancellations, revenue, extras, notes, tags, preferences, loyalty,
  communications.
- Dynamic segments: Repeat Guest, High Value, Family, German Market, Last Minute,
  Cancelled, Abandoned, VIP, Birthday, No Stay in 12 Months.

## R-38 Abandoned booking

- Funnel events where legally permitted: search, room view, quote, guest details,
  payment started, abandoned, booked. CRM event/workflow for abandoned bookings;
  future email/WhatsApp/SMS. Respect GDPR/KVKK; transactional ≠ marketing consent.

## R-39 Loyalty

- Optional per hotel: earn, burn, pending, available, expiry, manual adjustment,
  ledger. Earn/redeem by money, nights, services, room, period, tier. Redemption
  limits and blackout policies.

## R-40 Payments

- Provider abstraction. Initial targets: iyzico, Sipay, Turkish bank virtual POS,
  bank transfer, pay at hotel (where enabled).
- Never store full PAN or CVV. Prefer hosted/tokenised flows.
- Options vary by hotel, market, currency, channel (TR: card + bank transfer; DE: card;
  Market X: bank transfer only).
- Without real secrets: sandbox/mock interfaces; never fake production success.

## R-41 Payment links

- First-class objects, with or without a reservation: amount, currency, description,
  expiry, provider, status. Later allocation to a reservation. Allocation, partial
  allocation, transfer, refund, partial refund. All movements audited; idempotency.

## R-42 Guest self-service

- Per-hotel toggle. Secure access via magic link/token or equivalent.
- View; cancel where allowed; request date modification; modify eligible stay
  details; add extras. Before modification: availability, restrictions, new price.
- Higher → collect difference. Lower → **no automatic refund** unless policy permits;
  contact/support workflow or explicit approval.
- Changes needing staff attention create a prominent pending state until acknowledged.

## R-43 Enterprise / user model

- TEX PLATFORM → ENTERPRISE → HOTEL GROUP → HOTEL. Enterprise users access assigned
  groups/hotels; Group Admin manages permitted group properties; Hotel Admin only
  permitted hotel.
- Granular permissions: view price, edit contract, publish contract, override price,
  reserve, modify reservation, cancel, refund, payment link, inventory, restriction,
  CRM, guest export, user administration.
- Enforced in backend; frontend hiding alone never sufficient.

## R-44 TEX Connect

- Adapter-based integrations: PMS, Channel Manager, Payments, FX, Email, SMS, WhatsApp.
- PMS adapter: pushReservation(), modifyReservation(), cancelReservation(),
  fetchAvailability() where supported. Core reservation code not coupled to a vendor.

## R-45 Quote engine

- Authoritative server-side quotes. SEARCH → AVAILABILITY → QUOTE → OPTIONAL HOLD →
  BOOK → PAY → CONFIRM.
- Quote contains: id, expiry, hotel, room, rate, occupancy, child ages, market,
  currency, contract version, nightly breakdown, extras, promotions, tax, final total.
- Internal admin receives full explanation (Base person €100 / Adult1 ×1.00 /
  Adult2 ×1.00 / Child(8) ×0.50 / Room ×1.20 / Stay-period +10% / Germany markup
  +7% / Early Booking −15% / Final).

## R-46 Reservation price lock

- After confirmation, accepted terms are locked/snapshotted. Contract edits never alter
  confirmed reservations. Modification creates proposed price + revision + audit.

## R-47 Dashboard

- Sales-focused: reservations today, booking value, direct revenue, call-centre
  revenue, cancellations, pending payments, market performance, room performance,
  abandoned-booking opportunities, inventory alerts, restriction alerts.
  Enterprise/portfolio view.

## R-48 Reports

- Booking production; by booking date; by stay date; hotel; group; room; market;
  channel; promotion; cancellation; payment; extras; conversion; contract vs selling
  price; margin. Filters: hotel, group, market, currency, channel, sale date, stay
  date, room, rate.

## R-49 Internationalisation

- Proper i18n, no scattered hard-coded strings. At least Turkish, English, German,
  Russian, Romanian, Polish. Booking may detect browser language; manual selector.

## R-50 Responsive

- Booking: mobile-first. Admin: desktop-first, tablet-capable. Call Center: desktop.
  Breakpoints ≈ 320, 375, 390, 768, 1024, 1280, 1440, 1920 without broken layout.

## R-51 Accessibility

- WCAG 2.2 AA where practical: keyboard, focus states, labels, forms, dialogs,
  contrast, screen readers, error announcements.

## R-52 Performance

- Booking extremely responsive: initial JS, payloads, images, DB queries, caching,
  pricing lookups, availability queries. No N+1. Cache only when correctness is
  guaranteed; invalidate on contract/rate/inventory/promotion/restriction changes.

## R-53 Security

- Real threat model. Protect public booking, admin, API, CRM/PII, payments, webhooks,
  multi-tenancy. RBAC, tenant & property isolation, CSRF, XSS/output escaping, SQL
  safety, server validation, rate limiting, authentication, secure expiring tokens,
  secret management, webhook signatures, idempotency, audit logging, safe uploads.
- Never log passwords, CVV, full card numbers, secrets, raw auth tokens.

## R-54 Audit trail

- Actor, role, timestamp, hotel, source, old/new value, reason. Audit contract
  changes, publishing, rate changes, inventory, restrictions, reservation edits,
  manual overrides, refunds, payment movements, permission changes.

## R-55 UX productivity

- Command menu, global search, keyboard shortcuts, quick reservation, recent
  reservations, duplicate contract, copy period, copy restrictions, bulk edit, saved
  filters, quick payment link. Low click depth.

## R-56 Migrations

- Preserve usable data. Migration per schema change; safe transforms; preserve IDs;
  compatibility; tested migration path. Never casually delete production-shaped data.

## R-57 Testing

- Preserve existing tests unless intentionally obsolete (documented).
- Automated tests for: occupancy, child bands, age boundaries, explicit combinations,
  precedence, overrides, contract versions, historical pricing, stay periods, sale
  periods, FX, markup, promotions, restrictions, MinLOS, MaxLOS, CTA, CTD, Stop Sell,
  inventory concurrency, reservation revisions, permissions, tenant isolation,
  payments. Deterministic fixtures.

## R-58 E2E (Playwright)

Critical journey: (1) enterprise/hotel exists (2) admin creates market (3) contract
(4) price period (5) base-person rate (6) adult/child formulas (7) publishes version
(8) guest searches (9) correct availability (10) correct price (11) selects room
(12) adds extra (13) pays via test/mock provider (14) reservation confirms (15) admin
changes contract (16) existing reservation unchanged (17) dates/occupancy modified
(18) system proposes correct difference (19) revision history records it.
Also mobile booking.

## R-59 Visual QA

- Inspect major screens: alignment, spacing, responsive, overflow, large numbers,
  long property/room names, date grids, currency format, translations, empty,
  error, loading states. Repair defects.

## R-60 Implementation order

Phase 0 audit → 1 foundation (shell, routes, nav, design system, module boundaries,
hide PMS nav) → 2 commercial data model → 3 pricing engine (extensively tested; do not
start large UI work while core pricing tests are unreliable) → 4 contract admin →
5 rate/inventory grid → 6 CRS → 7 Call Center → 8 Booking + embeddable widget →
9 Payments → 10 CRM → 11 Self-service → 12 Reports → 13 Hardening (backend tests,
frontend tests, TS checks, build, lint, Playwright, security checks).

## R-61 Process rules

- Persistent memory: `CLAUDE.md` + `docs/tex-engine/*`. Recover state from them and git.
- Git: small coherent commits; checkpoint per milestone; update IMPLEMENTATION_STATUS.
- Parallel agents only after core architecture/interfaces are stable; never two agents
  on the same core pricing/domain files; define ownership; review subagent work; run tests.
- Status per requirement: COMPLETE / PARTIAL / NOT STARTED / BLOCKED with behaviour,
  files, tests, gaps. Not COMPLETE because a UI placeholder exists.
- Stop and ask only for: real production secrets; irreversible destructive decisions
  without safe default; materially contradictory requirements.

## R-62 Definition of done / priorities

Not done when "Kamra has a TEX logo". Priorities: 1 pricing correctness, 2
contract/version architecture, 3 CRS, 4 Booking Engine, 5 Call Center, 6 CRM,
7 Payments, 8 UX/UI, 9 Security, 10 Integrations. Never sacrifice financial
correctness for visual speed, nor tenant security for convenience.
