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
**Consequences.** "Which rule won" is always answerable; tests pin precedence. Occupancy
rules rank their origin (version, hotel + market, market, hotel, global policy) before these
levels since ADR-043.

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

## ADR-019 Legacy endpoints inherit TEX tenancy
**Decision.** `kamra.authz.require_roles` (used by ~300 legacy endpoints) now also resolves the
`property`, `reservation`, `folio`, `room`, `room_type` and `group_booking` arguments to a hotel
and refuses hotels outside the caller's TEX scope. `kamra.crs.permitted_properties` and
`kamra.api.my_properties` delegate to `kamra.tex.security.scope`. Frappe
`permission_query_conditions` / `has_permission` hooks (`kamra.tex.security.perm`) filter the
hotel-bound DocTypes, so under strict tenancy an unscoped user sees no hotel data in Desk either.
**Consequence.** Service/test accounts that work across all hotels need an explicit scope
(`ensure_all_hotels_scope`); upstream fixtures were updated accordingly, assertions unchanged.

## ADR-020 Guest actions are authorised by token, not by impersonation
**Decision.** Self-service endpoints verify the manage token and its ownership of the target
reservation, then call the service with `_guest_authorized=True`. Services skip the staff
capability check only under that flag and refuse staff-only options (fee waiver, price override).
`frappe.set_user("Administrator")` is never used to run guest actions.

## ADR-021 Payment callbacks and redirects
**Decision.** Gateways return to `kamra.tex.api.payments.callback`, which verifies the outcome
through the adapter (signature or server-to-server status query), commits, then redirects to the
transaction's stored `return_url`. Return URLs supplied by the browser are accepted only for the
TEX host or a DNS-verified domain of the booking site (no open redirects). A forged callback
leaves the transaction unchanged; an unreachable gateway leaves it Pending for staff `reverify`.

## ADR-022 TEX records are written only through TEX services
**Context.** An adversarial review showed Frappe's generic Desk/REST endpoints
(`/api/resource`, `frappe.client`, `desk.form.load`) bypassed TEX capability checks,
revision lifecycles and cost hiding for DocTypes whose role permissions allowed it.
**Decision.** DocType permissions give business roles no write/create/delete on TEX
DocTypes: System Manager keeps platform operations, Hotel Admin reads, master data (markets,
channels, FX rates) stays readable. Every hotel-bound TEX DocType — including those whose
hotel is known through a parent (revisions, contract versions, loyalty ledger) — plus `Guest`
has `permission_query_conditions` + `has_permission` (`kamra/tex/security/perm.py`);
platform-level audit rows are visible to platform admins only. New revisioned rows are always
Drafts. The TEX API writes with `ignore_permissions` after its own capability + scope check.
**Consequences.** Desk list views of TEX records are read-only for hotel admins; uploads for
TEX records go through public files + TEX API. A test asserts the hook list covers every
scoped DocType.

## ADR-023 Payment callbacks fail closed; secrets and replays are caller-bound
**Decision.** Providers return the outcome the gateway authenticated for *this* transaction:
an unverifiable callback raises (transaction unchanged), a non-final gateway answer stays
Pending; only authenticated failures mark Failed. Gateway return URLs carry an HMAC of the
transaction id. Staff can re-verify Pending **and** Failed charges. A payment is started
only through a provider account of the same hotel, and only with a return URL on the TEX host
or a DNS-verified booking domain. Idempotency keys are namespaced (booking: staff user or
guest site+session; payments: hotel + purpose), so a replay can never return another
caller's record. Offer keys and modification proposals are distinct signed token kinds;
proposals expire after 30 minutes. Cost, margin and rule explanations are stripped from
proposals and simulations unless the caller holds `price.view_cost`.


## ADR-024 Multi-room search places every room on its own
**Context.** A search for several rooms priced every party against each room type and
dropped the room type as soon as one party did not fit, so "2 adults + 1 adult with 2
children" could return nothing although each room had a match (R-29).
**Decision.** `quoting.search_property` prices each party separately. An offer lists only
the rooms it fits (`rooms[].room_index`, `room_indexes`), says whether it fits all of them
(`complete`) and why not (`room_reasons`). A grand `total` exists only for complete offers.
The hotel's `from_total` is the cheapest placement of every room — the cheapest offer per
room, summed, possibly across room types — in one currency; a room that fits nowhere is
reported (`unplaced_rooms`) and leaves `from_total` empty. `bookable` means at least one
room fits, no restriction applies and a room is free; how many requested rooms a type can
take at once is `available`, re-checked atomically at booking. Clients look rooms up by
`room_index`, never by position.
**Consequences.** Booking engine and CRS let each room pick its own room type; the server
remains the only source of totals (`public.basket`, `ui_crs.quote_summary`, both through
`booking.quotes_summary`).

## ADR-025 Lost booking responses and re-sent confirmations
**Context.** Manage tokens exist in clear only once (ADR-017). A guest whose `book`
response was lost, or who lost the e-mail, had no way back to the booking or its payment.
**Decision.** A retried `public.book` from the same session and idempotency key returns a
signed resume token (`kind=booking-resume`, 24 h, HMAC with the site secret) that the
guest endpoints accept like a manage token, and restarts the original payment attempt only
while it is still Pending. The emailed manage link stays the only long-lived secret. Staff
re-send the confirmation with `crs.resend_confirmation`, which rotates the manage token (the
old link stops working) and is audited. Confirming a booking before its deposit is paid is
a credit decision guarded by `reservation.confirm_unpaid` (not held by agents by default).

## ADR-026 Guest-facing hotel content is localised after pricing
**Context.** Room, rate plan, extra and policy names came from the hotel's records in one
language; German, Russian or Polish guests saw them untranslated (R-49).
**Decision.** `TEX Content Translation` stores one text per (record, field, language),
hotel-scoped and written only through `content.save` (`booking_site.edit`). Guest API
responses (`public.site/search/quote`, manage view) are localised by
`services/content.Localizer` from the request language, after pricing: codes, amounts and
the frozen contract payload never change, and missing texts fall back to the hotel's own.
Rate-plan and policy dicts are shared with cached contract terms, so the localiser works on
copies. Translations are cached per hotel in Redis and invalidated on every change.
**Consequences.** Staff screens keep the hotel's own texts; guest e-mails do not name rooms.
Promotion names (group-level) are not yet translatable.

## ADR-027 Legacy endpoints declare the record behind every id argument
**Context.** `require_roles` scoped legacy Kamra endpoints only through the arguments
`property`, `reservation`, `folio`, `room`, `room_type` and `group_booking` (ADR-011/019).
Endpoints that take a POS order, a banquet function, a guest, an action log or a generic
`name` read and changed other tenants' records, and some list endpoints returned every
hotel when no hotel was given (G-02).
**Decision.** `kamra.authz.RECORD_ARGS` declares, per legacy module, the DocType behind each
record argument; `ENDPOINT_RECORD_ARGS` covers endpoints that reuse a name (`name`,
`source`, `user`). `require_roles` resolves each record's `property` and refuses a hotel
outside the caller's scope. Guests are checked with the TEX guest visibility rule; merging
and erasing a guest (`GUEST_OWNED`) also require every stay of the guest to be in scope.
Legacy list endpoints restrict to the caller's hotels (`authz.property_scope()`), and guest
lists and stats use the Guest query condition. `linked_records` checks its record with
`authz.assert_record`. A static test (`test_every_legacy_record_argument_is_scoped`)
fails when a guarded legacy endpoint takes a record argument without a declaration.
**Consequences.** Records without a hotel (platform-wide) and unknown names are left to the
endpoint. A new legacy endpoint with a new record-argument name needs a declaration, or it
must check the record in its body and be listed in the test's exceptions.

## ADR-028 A TEX hotel is never sold through a legacy selling path
**Context.** The legacy booking engine (`/kamra/book`, `kamra.public_api.showcase /
search_stay / book / check_voucher`) and the legacy staff booking dialog
(`kamra.api.get_quote / create_booking / create_group_booking`) price from the float
`Room Type.base_price` and create reservations outside TEX contracts, inventory locks and
payments. They sold TEX hotels at wrong prices (G-03).
**Decision.** `kamra.tex.legacy.is_tex_hotel(property)` is true for a hotel inside the
TEX hierarchy (enterprise or hotel group set) or with TEX contracts. The legacy selling
endpoints call `refuse_legacy_sale(property)` first and refuse such a hotel, naming its TEX
booking site. `catalog_index` and `default_property` skip TEX hotels; when no other hotel
is left, `catalog_index` returns `mode: "tex"` and the legacy page redirects to the TEX
booking site. Hotels outside TEX keep the legacy engine (the upstream suites use it).
**Consequences.** Admin data imports (`import_bookings`, `migrate.run_import`) still write
reservations directly; they are migrations, not sales. Legacy channel-manager OTA inbound
bookings are refused for TEX hotels too, and the hourly legacy ARI push skips them (G-15).
Legacy scheduled jobs apply the same boundary per reservation: the night audit leaves a
TEX-sold stay (`is_tex_reservation`: TEX booking, price lock or TEX pricing source) alone —
no legacy room nights, no-show flags or no-show fees (G-04). The legacy hold expiry still
cancels expired Pending Payment holds for TEX bookings, by design (ADR-006).

## ADR-029 Booking-level terms are priced once, on the booking's first room
**Context.** R-29 prices every room of a booking on its own, and every reservation keeps
its own locked snapshot. Terms that belong to the whole booking were priced inside every
room: a per-booking (RESERVATION-mode) extra, including a mandatory one, was charged once
per room; a fixed coupon on the complete reservation (TOTAL) or its extras (EXTRAS) was
granted once per room; each room consumed one coupon redemption (G-05, G-06).
**Decision.** `StayRequest.room_index` is the room's position in its search (0-based). The
search stamps it into each room's signed offer, the quote keeps it in its request and the
reservation snapshot keeps it for repricing. The engine prices booking-level terms only on
room 0: mandatory per-booking extras are added there only; a per-booking extra requested
on another room is refused ("charged once per booking, on room 1"); a fixed TOTAL/EXTRAS
discount is granted there only (a percentage is the same share of every room, so it applies
to each). `create_booking` requires exactly one room 0 and distinct room indexes (the rooms
of one booking come from one search) and books room 0 as reservation 1. A promotion used on
a booking is recorded as one redemption with the discount over all rooms. The guest and
CRS extras pickers list per-booking extras on room 1 only.
**Consequences.** A minimum basket is still evaluated per room, so a coupon can be refused
on a multi-room booking whose total would qualify (never the reverse; G-84). Snapshots
made before this change have no room index and reprice as room 1. Cancelling room 1 alone
cancels the per-booking extra with it.

## ADR-030 The legacy PMS switch is enforced in the backend
**Context.** TEX Settings > "Show legacy PMS modules" only hid the sidebar link. Every
legacy route (front desk, POS, housekeeping, cashier, laundry, tape chart…) loaded for any
user, and the legacy endpoints answered: finance@ got a working restaurant POS, a Hotel
Admin the whole front desk (G-16).
**Decision.** `kamra.authz.require_roles` (the guard of every legacy PMS endpoint) refuses
hotel users while the setting is off (`legacy_pms_open_to_user`); platform administrators
keep access to operate and migrate. `kamra.api.whoami` reports `legacy_pms`, and the SPA's
legacy shell is mounted behind a gate that sends such users to `/tex`. The upstream suites,
which test the PMS itself, switch the modules on for their run (inside their savepoint, or
restored in tearDown).
**Consequences.** A site that runs the PMS turns the setting on (upgraded sites with PMS data
default to on, ADR-014). Guest-facing legacy pages (`/kamra/book`, self check-in, QR menu)
are not behind `require_roles` and keep their own rules (ADR-028, G-15).

## ADR-031 Extras and taxes are effective-dated revisions; history is never rewritten
**Context.** Extras and tax rules were read live when a stay was priced. Nothing recorded
which definition sold a stay. A price or tax change therefore also changed historical
simulation and ORIGINAL_* repricing, and a quote could not be reproduced as of its sale
time (G-20). A fixed levy's amount had no currency, so "2" was charged as 2 of whatever
the stay was sold in. Any user who could activate a selling-policy revision could also
back-date it and so rewrite what `as_of` reports for the past.
**Decision.**
- `TEX Extra` and a new `TEX Tax Policy` (one per hotel, holding `TEX Tax Rule` rows and a
  currency for fixed levies) use the ADR-005 revision lifecycle: Draft → Active →
  Superseded/Archived. A live revision is immutable; a change is a new revision.
- They are not frozen into the contract payload. They are hotel-level and change
  independently of contracts, so freezing them would force a republish per tax change.
- Pricing at sale time T reads the extras (`context.live_extras` / `extras_catalog`) and
  the tax policy (`context.tax_policy` / `tax_rules`) live at T. Every reader outside
  pricing uses the same helper: the public site, quote checks, CRS, content and
  translations (keyed by the revision root).
- Two live definitions at T stop selling with a clear error; a price is never picked
  silently. Two live extras with one code, or two live tax policies, are refused on save
  and activation.
- The quote and the reservation snapshot name what was used. Extra lines carry `revision`
  and `fx_rate`; tax lines carry `source` (`tax_policy:<rev>`, `property:<hotel>` or
  `pack:<pack>`) and `fx_rate`. The EXTRA and TAX explanation steps carry a `RuleRef` with
  the same source.
- A fixed levy is charged in its policy's currency. It is converted with the sale time's
  FX snapshot, or the stay is unsellable (`TAX_FX`); it is never reread as the sell
  currency.
- `revisions.activate` refuses a time in the past (a 5-minute tolerance for client clocks
  and minute pickers is clamped to now). It also refuses a time before an already
  scheduled revision. Every sibling still live at the activation time ends there, so one
  revision of a record is live at any instant. Only trusted code (migrations, test
  fixtures) passes `backdate=True`. The API and UI never do.
- Archiving takes a revision off sale from now, whatever its status (a superseded revision
  stays live until its successor starts). Archiving a revision whose window has not begun
  cancels it, whether it is Active or already superseded by a later schedule: the revision
  it was to replace takes its window over. An archived revision is therefore never live
  after it is archived, and archiving never leaves a gap nobody chose.
- A hotel's live tax policy cannot be archived; it is revised instead (a revision without
  rules charges no tax).
- Once a hotel's tax policy has really begun (a non-empty live window; a cancelled schedule
  does not count), a sale time with no policy in force makes that hotel's stays unsellable
  (`TAX_POLICY`) instead of falling back to older settings.
- Checks for "one live record" look at live windows, not statuses.
- Two live definitions and gaps are `Unsellable` for that hotel only: a search over several
  hotels goes on. Lists outside pricing (booking site, CRS pickers, content) show no extras
  for an ambiguous hotel rather than failing the page.
- A scheduled time is an instant: the browser sends it with its offset, and the server
  converts it to the site's time zone before the back-dating check.
- A revision keeps its record's hotel and, for an extra, its code (bookings, loyalty
  rules, translations and capacity know an extra by its code).
- An audit trail never blocks deleting a draft (`hooks.ignore_links_on_delete` = TEX Audit
  Event); every other link still does.
- ORIGINAL_* repricing uses the time the booking was priced (its quote's `sale_at`,
  carried as `original_priced_at` across modifications), not the booking time. An
  unchanged reprice therefore reproduces the sold price even when a revision went live
  between quote and booking.
- Tax policies need the new `tax.edit` capability (Finance and Hotel Admin, not Revenue
  Manager). Once a hotel has a tax policy, its old `Property.tex_tax_rules` table can no
  longer be edited.
- Migration p12:
  - existing extras become live from their creation (disabled ones are archived);
  - every TEX hotel gets a tax policy holding exactly the taxes it was sold with (its custom
    table or its localization pack), live from the hotel's creation;
  - Finance and the admin profiles get `tax.edit`;
  - a hotel whose rules a policy cannot hold is logged and skipped; the migration never
    stops for one hotel.
- A hotel that becomes a TEX hotel later gets its policy then: on the Property save that makes it one
  (from the stored values, before that save's edits), or when its first TEX contract is
  created (`tax_policies.ensure`). Two tax-policy drafts activated at once run one after the
  other (the hotel row is locked). Seeded fixed levies take the currency the hotel's contracts sell in
  (else the hotel's currency), and the policy description says so. A hotel without a policy
  keeps the old meaning of a fixed amount (the sell currency).
- Once a hotel's policy has begun, its old tax table cannot be edited, and a change to a
  pack's inputs (country, GST rates) warns that TEX prices are not affected.
- The p12 extras step runs on the patch's first execution only; a forced re-run never puts
  live a draft made since.
**Consequences.**
- History before the migration is reproduced with the definitions as of the migration; the
  price-locked snapshot stays the record.
- Some hotels cannot be expressed as a policy yet and stay on their pack, which is not
  effective-dated. These are hotels on a slab pack (India) and hotels whose pack rates
  differ by room type. Their tax lines name the pack (`pack:india`), and the Error Log says
  why.
- Once seeded, a fixed levy has one currency and is converted for sales in other currencies,
  where before the number was reread as whatever the stay was sold in.
- A hotel whose pack takes a room type's tax % is not seeded when those rates differ by room
  type. Once its policy has begun, a change to a room type's tax % warns that TEX prices are
  not affected (the legacy folio still reads it).
- Extras capacity (G-19) must key on the extra's code or root, never on a revision name.

## ADR-032 Locked rows are re-read by primary key; a deadlock victim is run again
**Context.** Two problems showed up in threaded tests (G-07 regression, G-85).
- The coupon limit was checked under the promotion's row lock with a plain count. Under
  REPEATABLE READ that count sees the transaction's earlier snapshot, so two simultaneous
  bookings could both use a code limited to one.
- Two bookings of different room types at the same instant deadlocked. The availability
  recount after `lock_nights` read `TEX Inventory Day` with a `LOCK IN SHARE MODE` range.
  Its next-key locks reach into the neighbouring pool's rows, which the other booking holds.
**Decision.**
- After taking a lock, a count that decides a limit is a locking (current) read. A plain
  read is never used for that decision.
- Rows the transaction already holds are re-read by primary key (`name IN …`), which takes
  no gap locks.
- Write endpoints whose whole work is one request transaction run again when MariaDB
  chooses them as a deadlock victim: a clean rollback, then up to 3 attempts with jitter
  (`kamra.tex.services.txn.retry_on_deadlock`). They are `public.book`, `manage_apply`,
  `crs.book`, `ui_crs.book` and `crs.apply_modification`.
- Idempotency keys and the rolled-back naming series make the rerun write everything
  exactly once.
**Consequences.** Other locking range reads (the reservation recount) can still meet
another booking's insert under rare index layouts; the retry absorbs that. MariaDB ≥ 11.6
(`innodb_snapshot_isolation`) reports changed-row conflicts as deadlocks too, and they are
retried the same way. A new write endpoint that locks inventory must use the decorator.

## ADR-033 Limited extras: a day counter keyed by code, an allocation ledger, locks by primary key
**Context.** An extra could be marked *Limited daily inventory* with a daily capacity, but
nothing read it, so spa slots and dinners never sold out (G-19). Capacity is operational
(like room inventory, ADR-005's note) and must survive the extra's price revisions (G-20).
**Decision.**
- *What a sale takes* is pure (`pricing.extras.usage`):
  - a service-date extra takes each chosen date;
  - a nightly extra takes every night;
  - a per-person extra takes one unit per guest (children and infants included);
  - every other extra takes one day, its chosen day or else the arrival day.

  The quote records it per extra line (`usage`).
- *Is it limited?* The revision on sale **now** decides (`inventory_tracked` and
  `daily_capacity` ≥ 1), not the revision that priced an older sale. A limited extra cannot
  be mandatory.
- *Counter and ledger.*
  - `TEX Extra Inventory Day` holds one row per (hotel, extra code, day), with a capacity
    override, a closed flag and `sold`. The row name is deterministic, so it can be
    created and locked in one statement.
  - `TEX Extra Allocation` holds one row per (reservation, code, day), Held → Confirmed →
    Released.
  - Keyed by code, so a capacity spans revisions.
  - `sold` is written only by the service; a Desk edit restores it.
- *Quotes* see what is left, excluding the reservation being modified. A refused optional
  extra is `ok=false` with "sold out / only N left / closed on <date>" and is not charged.
  A historical simulation does not check capacity.
- *Bookings* aggregate the demand of all rooms and lock the day rows by primary key,
  sorted, after the room nights (global order: quotes → room days → extra days →
  promotions → booking). They re-read the rows `FOR UPDATE`, refuse with `ExtraSoldOut`,
  then allocate: Held while payment is pending, Confirmed otherwise. Confirming the booking
  confirms the units.
- A cancelled or no-show reservation releases its units through the Reservation hook,
  whichever path cancelled it. A checked-out stay keeps them.
- A modification takes the new units and gives back the old ones under the same locks. What
  the reservation held counts as available to it.
- Stays sold before an extra became limited get their allocations from their snapshots:
  when a limited revision goes live, at migration (p13), and daily, which covers scheduled
  revisions. A daily job rebuilds every counter from the ledger and audits any drift.
  Inventory → Extras can also run it (Recount).
- Staff see and edit per-day capacity and closures in Inventory → Extras (`inventory.edit`)
  and the holders of a day (`reservation.view`). Guests see available / few left, never
  counts.
**Consequences.**
- A multi-room quote checks each room alone; the booking step can still refuse on the
  aggregate, and the UIs re-quote.
- An extra switched to limited by a revision scheduled for later is backfilled by the next
  daily run, so it may oversell until then.
- Applying a modification that makes a limited extra unavailable drops that extra, which
  the proposal shows (`EXTRA_SOLD_OUT` warning).

## ADR-034 Extras added after booking are priced on their own; the stay stays price-locked
**Context.** Guests could only choose extras while booking. Staff could add one through a
modification, which re-prices the whole stay on a chosen basis (G-22). A guest who books a
massage a week later must not see the room price move, and the hotel must not re-open a
confirmed price to sell a dinner.
**Decision.**
- *Pricing is pure and separate* (`pricing.addons.price_addons`):
  - the requested extras are priced against the booked stay as sold (its request, room,
    party and dates, from the frozen snapshot);
  - they use the extra revision on sale **now** (ADR-031) and the hotel's tax rules now,
    restricted to the EXTRA categories;
  - the room, board, promotions and contract terms are untouched. No promotion or coupon
    applies to an add-on (an `ADDON_NO_PROMOTIONS` explanation step says so).
- *Refusals are explicit*:
  - `ADDON_EMPTY` / `ADDON_PARTY`;
  - `ADDON_NOT_AVAILABLE` — unknown, mandatory, not eligible, or a per-booking extra on a
    room other than the first;
  - `ADDON_QUANTITY` — over the maximum with what is already booked;
  - `ADDON_TOO_LATE` — a usage day before today or before the extra's order cut-off
    (`order_cutoff_hours`, new field);
  - `ADDON_SOLD_OUT` — a limited extra (ADR-033).
- *Guests* see only extras sold online **and** after booking, with available / few left,
  never counts, and no explanation. Staff (`reservation.modify`) see everything on sale; the
  explanation is shown only with `price.view_cost`.
- *Propose → apply*: the proposal is a signed, 30-minute token bound to the reservation's
  `modified`, the requests, the total and who proposed it (guest or staff). Apply:
  - locks the reservation row;
  - replays the same token once (the id is a hash of the token);
  - refuses if the reservation changed or the price moved;
  - takes limited units under the day locks (G-19);
  - merges the add-on into the snapshot — EXTRA lines before the first TAX line, its TAX
    lines at the end, totals summed, and an `addons[]` entry `{id, at, quote, requests,
    source}`;
  - records a `TEX Reservation Revision` (`change_type=Extras`, `pricing_basis=ADD_ON`),
    refreshes the booking and audits `reservation.addon`.

  A guest's add-on flags the reservation and the booking for staff attention.
- *Payment is apply-then-pay*: the booking's balance grows by the add-on and is paid like any
  balance — online from the manage page (Pay now) or at the hotel. No card is charged by
  the add-on itself.
- *Later changes carry it over*: a modification re-prices the stay on its basis, then merges
  each earlier add-on's frozen quote back. It warns `ADDON_OUTSIDE_STAY` when a usage day
  falls outside the new dates; a guest cannot apply such a change themselves.
- Cancellation penalties, refunds, reports and loyalty read the reservation's total, which
  includes add-ons.
**Consequences.**
- An add-on keeps the price it was sold at even if the stay is later re-priced; removing an
  add-on is a staff modification.
- A limited extra added after booking is Held while the booking's payment is pending, and
  Confirmed otherwise.

## ADR-035 A booking site's own host: verified by DNS, pinned to its site, used in every guest link
**Context.** A booking site could list custom domains and verify them by DNS, but nothing
served them (G-21). Guest links were built from the request's Host header. A domain could
be "reserved" by any site before verification, and paths such as `hotel.com/book` were
accepted although TEX cannot serve a path on a hotel's own web server.
**Decision.**
- *A custom domain is a host name* (`book.hotel.com`) that the hotel points at TEX (CNAME).
  Paths are refused. p15 un-verifies existing path rows so no guest link points at them;
  the hotel must replace them with a host.
- *Ownership*:
  - A TXT record `_tex-verify.<host>` must hold the row's token, resolved over
    DNS-over-HTTPS. The answer's `Status` is checked: NXDOMAIN means no record, any other
    error is a lookup failure.
  - Several sites may claim a host while it is unverified; only one site can hold it
    verified.
  - `verified`, `verified_at`, `last_checked_at` and `check_failures` are written only by
    the DNS check. An edit, including the admin UI sending the rows back, keeps the stored
    values.
  - A daily job checks every verified host again. The record missing on three consecutive
    checks un-verifies the host and audits it. A resolver failure does not count.
- *Serving*:
  - A `page_renderer` (`kamra.tex.booking_host`) claims website paths on a verified host of
    an enabled site. It renders the booking engine pinned to that site through
    `<meta name="tex-booking-site">`, with the site's CSP frame-ancestors.
  - Platform paths pass through: assets, files, API, `.well-known` and `/book/pay/…`.
    `/book/<another site>` redirects to `/`.
  - The host → site map is cached and cleared on every site change.
- *Binding*: on a pinned host, the public API answers for that site only.
- *Links*:
  - Manage links in e-mails, payment links, default payment return pages and the embed
    link use the site's primary verified host (`https://<host>/…`), else the platform's
    `/book/<slug>/…`.
  - Platform links and gateway callbacks use `get_url(allow_header_override=False)`:
    `host_name` from the site config, never the request's Host header.
  - Payment return URLs may point only at the platform or at the verified hosts of the
    hotel's enabled sites.
- *Operations* (outside TEX): the host must be added to the Frappe site (`bench setup
  add-domain`), the web server config regenerated and a TLS certificate issued. Production
  sets `host_name`. These steps are listed in GO_LIVE_READINESS.md.
**Consequences.**
- A site without a verified host behaves exactly as before.
- Staff log in on the platform host; a hotel's booking host only serves its engine.

## ADR-036 Guest segments are per tenant; facts come from the viewer's hotels
**Context.** R-37 names segments TEX could not express: families, last-minute bookers,
cancellations, abandoned bookings, birthdays (G-23). Segment facts were global per guest (a
guest's stays at another enterprise's hotels counted), money was compared without a
currency, values were not typed, segments had one global namespace and any user could
list, count or edit another tenant's segment (G-26).
**Decision.**
- *Facts* (`segments.derive_facts`, pure) are derived from the reservations and abandoned
  bookings at the hotels the viewer may see (`crm.view`), never from other tenants' data.
  The guest list and profile show those same in-scope stays and value.
- New facts:
  - `has_children`;
  - `last_lead_days`: arrival minus sale day of the latest sale;
  - `cancellations` and `last_cancel_days_ago`;
  - `abandoned_days_ago`;
  - `days_to_birthday`, where 29 February counts on 28 February in other years.

  "Upcoming" means Confirmed, Pending Payment, Held, Requested or Checked In; an inquiry is
  not a stay.
- *Money* is per currency. A lifetime-value condition names its currency and is compared
  with the guest's value in that currency. A legacy condition without one matches nobody
  until edited (p16 reports it).
- *Typing*: saving validates every value (integers, decimals, yes/no, text, 3-letter
  currency). An unknown fact never equals anything (`ne` is true).
- *Presets* (`SYSTEM_SEGMENTS`, seeded by install and p16, kept in sync by key) are shared
  and read-only: Repeat, VIP, Email opt-in, No stay in 12 months, Families, Last-minute,
  Cancelled in 90 days, Abandoned in 30 days, Birthday in 30 days. Their counts depend on
  who looks, so none is stored.
- *Tenancy*:
  - A custom segment belongs to an enterprise; its name is unique there.
  - Listing, counting, exporting, editing and deleting check it.
  - Another tenant's segment is "not found".
  - Desk/REST follow the same rule (`perm.ENTERPRISE_DOCTYPES`).
  - Counting needs `crm.view`; saves and deletes are audited.
  - A platform administrator may keep a segment at platform level.
**Consequences.**
- Segment evaluation reads the tenant's reservations per guest list: indexed on
  (guest, property). Very large lists will need a stored fact table later.

## ADR-037 Loyalty programs are administered in TEX; earnings are never rewritten by a rule change
**Context.** Loyalty programs could only be edited in Desk by a System Manager, with no
validation (G-24). Every save of a reservation recomputed its points with the current rules,
so editing a rate rewrote past earnings (G-66). A 0 % redemption cap meant 100 %. Blackouts
were labelled for redemption but applied to earning. A guest's summary showed every tenant's
programs (G-65).
**Decision.**
- *Administration* (`kamra.tex.api.loyalty`):
  - Reading needs `crm.view` at a hotel the program reaches. Changing it needs the new
    `loyalty.edit` at every enabled hotel it reaches (Revenue Manager and admins; p17 adds it
    to the default profiles).
  - Another tenant's program is "not found".
  - Every save, enable, disable and delete is audited with old and new values.
  - Program statistics include members, available and pending points, and the liability
    (available points × point value, program currency).
- *Validation* (the controller, whoever saves):
  - A program has exactly one hotel or one group.
  - Its name is unique there, and only one program is enabled per scope.
  - Values are non-negative, the redemption share is 0–100 %, and a currency is required
    when points are earned on or worth money.
  - Rules have a positive rate; a ROOM or EXTRA rule must reference its own hotels.
  - Tier names and floors are unique, and multipliers are above zero.
  - Blackouts must be ordered.
  - A program with points cannot move to another hotel or group, or be deleted (disable it).
- *Earnings are frozen*:
  - An earning records its stay fingerprint (dates, room, value and currency, extras) and
    its explanation.
  - It is recomputed only when the stay itself changes, never because the rules changed.
  - p17 fingerprints earlier earnings with their stay as it is.
- *Redemption*:
  - 0 % now means "cannot redeem"; p17 turns stored 0 into 100 to keep old behaviour.
  - Blackouts have a purpose (Redemption, Earning or Both). Redemption refuses any stay night
    in a redemption blackout. Old rows become Both.
- A guest's summary lists only the viewer's programs.
**Consequences.** Point value stays a 6-decimal Float read through Decimal (G-72 open).

## ADR-038 The portfolio dashboard reports on the hotels a user may see, money per currency
**Context.** The dashboard covered one hotel and lacked most of R-47's sales figures: booking
value, direct and call-centre revenue, pending payments, market and room performance,
abandoned bookings with their value, and inventory and restriction alerts. There was no
enterprise or group view (G-25).
**Decision.**
- `reports.portfolio(level, name, from, to)` covers All my hotels, an Enterprise, a Hotel
  Group or one Hotel.
  - Only hotels where the user holds `report.view` are included.
  - A scope with none of them is refused, without confirming that it exists.
  - `portfolio_scopes` lists what the picker may offer.
- Figures come from SQL aggregates read as text and summed with Decimal, per currency, never
  across currencies:
  - Sales count on their sale day (TEX sale time, else creation): count, today's sales and
    value, booking value, direct (Booking Engine channel group) and call-centre (Call
    Center group) value, markets, and room types with room nights.
  - Cancellations count on the day they were cancelled.
  - Bookings waiting for payment and open balances come from TEX Booking balances.
  - Open abandoned bookings of the last 30 days are shown with their value.
- Alerts cover the next 14 days:
  - room pools that are closed, oversold, sold out, or at 10 % or less left (from the same
    pool/inventory math as selling);
  - stop-sell, closed-to-arrival and closed-to-departure restrictions.
- SQL aliases never shadow a column: MariaDB resolves a GROUP BY name to a column first, and
  Reservation has a legacy `channel` column.
**Consequences.**
- "Today" is the server date; per-hotel time zones are still open.
- No reporting-currency conversion: totals stay per currency.

## ADR-039 TEX distributes through its own provider-neutral channel layer; certification gates production
**Context.** TEX had no channel distribution of its own (G-69, a go-live blocker).
- The legacy Kamra channel manager prices from `Room Type.base_price` and books outside TEX
  (ADR-028, G-15). A TEX hotel must not use it.
- No channel-manager provider credentials or certification are available, so no real
  provider can be implemented honestly.
**Decision.**
- *Structure.* `kamra/tex/distribution/` is split into two kinds of module:
  - Pure modules, with no frappe import: `model`, `ari`, `signing`, `adapters`.
  - Frappe glue: `repository` and `channel_booking`.
- *Adapters.* An adapter (`ChannelAdapter`) only translates and transports:
  - `push_ari(runs)`, `verify_webhook`, `parse_webhook` and optionally
    `fetch_reservations`.
  - Only adapters in `REGISTRY` can be chosen.
  - An adapter with `certified = False` is refused in the Production environment, both by
    the connection controller and at run time.
  - The only adapter is the `sandbox_channel` (uncertified), which accepts, fails or rejects
    pushes on request and receives signed bookings in TEX's neutral format. **Real providers
    are BLOCKED on credentials and certification.**
- *Mapping.* `TEX Channel Mapping` maps one external room/rate code to TEX's room type,
  board, rate plan, market, sales channel, currency, contract (optional), occupancies and a
  horizon of up to 365 days.
- *ARI is computed, never typed.* For each day, availability comes from the same pool and
  inventory math that selling uses. Restrictions come from the effective TEX ARI
  restrictions. The price per occupancy comes from `quoting.price_request` on the mapping's
  published contract version. A day that cannot be priced goes out closed.
- *Only changes are pushed.* `TEX Channel ARI Day` stores the fingerprint the channel
  last accepted, and a push sends only the days that differ, grouped into runs.
- *Change detection.* These edits mark the affected mapping-days dirty:
  - TEX Inventory Day, ARI Restriction, Allotment and Channel Mapping;
  - a contract version's status;
  - a reservation's status, room type, dates or hotel (on insert, whatever Frappe has
    loaded as "before").
  Dirty days become one coalesced `TEX Integration Outbox` job (`kind = ARI`) per mapping.
- *Job claims and retries.* Workers claim jobs with a token and a lease, so no two
  workers take the same row. A failure retries with exponential back-off. A rejection
  (`retryable = False`), or eight attempts, parks the job as Dead. Errors are redacted.
- *Inbound bookings.* The webhook is guest-reachable and rate limited to 120/min.
  - It verifies the adapter's signature and fails closed: `X-TEX-Timestamp` +
    `X-TEX-Signature` HMAC-SHA256 over "<ts>.<body>", with a 300 s replay window.
  - Each message is stored once in `TEX Channel Inbound`, keyed by a unique idempotency
    key, and the webhook answers fast. The queue applies messages later.
  - A booking's messages apply in the order received, one per booking per run.
  - Each message is applied once: its row is locked and its status re-checked.
- *Channel bookings.* A channel booking is the channel's sale.
  - The TEX Booking is created with `created_via = Channel`, `external_ref` and
    `channel_connection`.
  - Its reservations carry the channel's total, with `tex_pricing_source = Channel`,
    price-locked, and an `EXTERNAL` revision.
  - New, modified and cancelled messages carry the full state of each line (`line_ref`).
  - An overbooking is accepted, with a warning and a `channel.overbooking` audit event: the
    channel has already sold it.
  - TEX never reprices such a stay and never sells add-ons onto it. Changes arrive from the
    channel.
- *Reconciliation* reports two kinds of mismatch:
  - ARI drift: TEX's current fingerprint differs from the one the channel last accepted.
  - Booking differences: the channel's view, taken from the provider when it can answer
    and otherwise from the latest message, compared with TEX's bookings.
- *The PMS outbox* (`kind = Reservation`) goes to PMS connections only. A channel gets ARI,
  not reservation events.
- *Legacy guards.* The legacy channel-manager paths refuse TEX hotels:
  - webhook, ARI push, queued jobs and room import;
  - AioSell's reservation webhook (G-87).
- *Security.*
  - `channel.view` / `channel.manage` are checked at the connection's hotel.
  - `api_key` and `secret` are Password fields.
  - Secret-like keys are refused in `settings_json`, and endpoints must be `https://`.
  - A connection with mappings cannot move to another hotel, and a connection with history
    cannot be deleted.
**Consequences.**
- Certification with a real provider (Channex, SiteMinder, …) is the remaining go-live
  step. It needs that provider's credentials and a new adapter subclass.
- The sandbox proves the full flow end to end without pretending to reach a channel.
- Reconciliation against a provider's own booking list waits for an adapter that
  implements `fetch_reservations`.

## ADR-040 The tenant structure is itself tenant data; guest identity is shared inside an enterprise
**Context.** G-26: Desk/REST exposed the tenant structure across tenants.
- `TEX Access Grant`: Hotel Admin had full Desk rights and there was no permission hook. Any
  tenant's grants could be listed, and a grant of another tenant could be deleted (the
  controller checked only saves), or moved to one's own hotel (it checked only the new state).
- `TEX Enterprise` and `TEX Hotel Group` names were listable by every hotel admin.
- Funnel events and abandoned bookings of a *group* booking site have no hotel yet. They were
  read as platform-wide rows, so every tenant saw them (abandoned bookings carry e-mails).
- `admin.profiles` answered any logged-in user.
**Decision.**
- *Tenant structure.* `TEX Access Grant`, `TEX Enterprise` and `TEX Hotel Group` are scoped
  (`perm.TENANT_DOCTYPES`):
  - an enterprise or group is visible only to users with a hotel in it;
  - a grant is visible to its own user, and otherwise when it covers a hotel the viewer may
    see. A platform-scope grant is visible only to its user and to platform administrators.
- *Who may change a grant* is decided by the controller on every path, including trusted code
  that ignores permissions:
  - an update must be allowed on the grant *as it stands* and as it will be;
  - a delete must be allowed on the grant as it stands (anti-escalation, ADR-020).
- *Site activity.* `TEX Funnel Event` and `TEX Abandoned Booking` rows without a hotel belong to
  their booking site's hotel or hotel group (`perm.SITE_DOCTYPES`). A row with neither is
  platform-level.
- *Permission profiles* are listed only to user administrators (and platform administrators).
- *Guest identity* stays shared inside an enterprise, by design (ADR-018). A hotel admin of any
  hotel of the enterprise sees and edits the enterprise's guest profiles, which is what a
  chain-wide CRM needs. Every profile change is audited, and nothing crosses enterprises.
**Consequences.** A hotel-only CRM view, where one hotel cannot see another hotel's guests
inside the same enterprise, would need a per-enterprise setting. It is not built.

## ADR-041 Payments go live fail-closed: certification gates Production, a charge is exactly one charge
*Amended by ADR-042: settling is gated apart from new money, a Sandbox override stays on the
sandbox host, a live site runs no sandbox gateway, and iyzico keeps one checkout per charge.*
**Context.** The go-live review of payments (G-67, G-68) and two related findings (G-89, G-90):
- A Production account could use an uncertified gateway (iyzico, Sipay, NestPay) or override
  its `gateway_url`. Only the TEX API refused the mock in Production; Desk/REST refused nothing.
- `complete()` skipped the amount check when a gateway returned 0 or nothing, and never compared
  the currency.
- `pay_link` added a random suffix to its idempotency key, so two tabs started two charges and a
  link could be paid twice. A refund was booked on `txn.booking` even after the money had been
  transferred to another booking.
- Signatures fell back to the public site name without an `encryption_key` (G-89). The PMS
  outbox delivered through an uncertified adapter to a Production connection changed behind the
  controller's back (G-90).
**Decision.**
- *One registry, one rule set.* `payments.providers.REGISTRY` maps a provider name to its class.
  `account_problem` states the rules:
  - the mock runs only in Sandbox;
  - Production needs `production_verified` on the class. Bank Transfer and Pay at Hotel have no
    gateway, so they are verified; the three gateways are not;
  - a `gateway_url` override is for sandbox and test hosts. It is refused on a Production
    account, whose live host comes from the provider code.
  The account controller applies the rules on every save, `provider_for` again before every
  use (fail closed), and `payment_methods` never offers an account that could not run.
- *A success is exactly this charge.* A gateway with `reports_amount` must state the captured
  amount: missing, 0 or different fails the charge (`AMOUNT_MISMATCH`). A stated currency must
  be the charge's (`CURRENCY_MISMATCH`).
- *One charge per link at a time.* `pay_link` locks the link row and keys the charge on link,
  gateway, amount due and the number of earlier Failed/Cancelled attempts:
  - a second tab or a double click reuses the Pending charge; a retry after a failure is new;
  - a reused charge is never re-routed or re-priced, and a failed re-checkout leaves it Pending;
  - iyzico keeps every checkout token issued for the charge, newest first, so a guest who pays
    on the older tab is still recognised; staff re-verification tries each token;
  - a verified success turns a Failed charge into Succeeded: the gateway has the money, and
    one checkout failing must not hide another one paid;
  - lock order is the link, then the payment;
  - a success on an already paid link is recorded (money is never dropped) and audited as
    `payment_link.overpaid` for finance to refund.
- *Refunds come from where the money is.* The net allocation per booking is Allocate − Release −
  Refund. Without a booking, the refund comes from the one booking holding money. When several
  hold money, staff must choose; when none does, the refund is of unallocated money and has no
  allocation. A named booking refunds at most what it holds plus the unallocated remainder.
- *Signing keys* come only from `encryption_key` (`security.keys.site_secret`): a missing key is
  an error, never the site name. The derived values are unchanged, so issued offers and
  callbacks stay valid.
- *PMS delivery* refuses an uncertified adapter for a Production connection at run time. The
  refusal is not retryable, so the event goes Dead with the redacted error.
**Consequences.**
- Going live with a card gateway needs its certification and then `production_verified = True`
  in code. NestPay's production host must come from a per-bank table, because overrides are
  refused in Production.
- A guest who pays in two tabs through *different* gateways can still pay twice. The second
  payment is kept and flagged for a refund.
- A second start that waited on the link lock can still meet the first start's charge after its
  own read snapshot. It then gets a unique-key error instead of a second charge.
- Bookings paid in Sandbox are not flagged yet: that needs a schema field.

## ADR-042 Payments: new money and settled money are gated apart; one iyzico checkout per charge
**Context.** The review of ADR-041 found that the go-live gates still had holes, and that some
of them stranded money a gateway had already captured:
- a Sandbox account could point its `gateway_url` at a live gateway (real money through an
  uncertified integration), and on a live site a sandbox mock payment still confirmed bookings;
- the run-time gate also refused to record, re-verify or refund captures on a Production account
  created before certification was required, and such an account could not even be disabled;
- a capture refused for an amount or currency mismatch was marked Failed with no record of what
  the gateway held and no refund path;
- locks were followed by snapshot reads (MariaDB REPEATABLE READ), and callbacks held the link
  and payment locks through gateway HTTP calls;
- iyzico kept several checkout tokens on one charge: tokens could be dropped, and a guest paying
  two forms of one charge would have been captured twice while TEX counted once;
- a refund took a booking's money before the payment's unallocated remainder.
**Decision.**
- *Two purposes.* `account_rule(acc, purpose)`:
  - `new` (start a charge, offer a method, save an enabled account) applies every rule;
  - `settle` (record a capture, re-verify, refund) skips only the certification rule. Settling
    on an account that could not take new money is audited (`payment_account.settled_while_gated`);
  - `keep` (save a disabled account) refuses only an unknown provider.
  A disabled account runs nothing, settling included: disabling is the hotel's stop switch.
  Patch p19 lists every gated account with its open charges; `accounts()` reports the reason.
- *Sandbox means sandbox.* An override on a Sandbox account must be https on the provider's own
  `sandbox_hosts` (localhost too in developer mode). On a site with `tex_production` no sandbox
  gateway runs (`gateway = True` providers, the mock included); offline methods are unaffected.
- *Captured money is never dropped.* A verified success is recorded on a Pending, Failed or
  Cancelled charge. A refused capture keeps the charge's checkout references, is audited as
  `payment.capture_mismatch` with the gateway's reference, amount and currency, and `refund()`
  refunds it (in that currency, against that reference, touching no booking). iyzico compares
  the basket `price` (instalment interest in `paidPrice` is not a mismatch). Sipay does not
  require an amount until a recorded sandbox answer confirms its field names.
- *One checkout per iyzico charge; supersede, don't stack.* A provider says whether a Pending
  charge may take another checkout (`can_add_checkout`): iyzico never (every form is its own
  payment at iyzico, and a form's page cannot be shown again: TEX keeps its token, not its URL).
  A charge that cannot take another checkout, or whose re-checkout the gateway refuses, is
  superseded: Cancelled (`payment.superseded`), and `pay_link` starts the next charge. Its late
  payment is still recorded and flagged if it overpays; a late payment on a Cancelled or Expired
  link is audited (`payment_link.paid_after_close`).
- *Locks.* `complete()` asks the gateway before taking any lock, then locks link then payment
  and reads both with `for_update`; every read after a lock that feeds a write is a locking read
  by primary key (`_after_charge`, `allocate`, `refund`, `mark_transfer_received`,
  `booking.apply_payment`). `pay_link` locks the link with `NOWAIT`. The link's charge key is
  found by looking keys up (no lock) and re-reading a found charge by name with a lock: a locking
  count would lock the whole payments table (no index on `payment_link`), and a locking read of a
  missing unique key would lock an index gap through the gateway call.
- *Refunds.* Unallocated money is refunded first; only the rest comes off a booking (the named
  one, or the one holding money). A refund that takes nothing off a booking names none. The
  refund screen lists only bookings holding money and defaults to none.
- *Guests* hear a generic reason for an account or signing-key refusal; staff get the detail and
  the error log has it.
**Consequences.**
- A second iyzico tab starts a second charge: a guest who pays both pays twice. Both payments are
  recorded and the second is flagged `payment_link.overpaid` for a refund.
- `allocated_of` / `refunded_of` are still snapshot aggregates: two staff members refunding or
  allocating the same payment at the same moment could both pass the limit check. Locking them
  needs indexes on `transaction` / `parent_transaction` (a schema change, not made here).
- Bookings paid in Sandbox on a site without `tex_production` carry no per-booking flag.

## ADR-043 Occupancy precedence v2: every pricing policy cascades; origin ranks first; an infant's band first
(Written as ADR-042 on its branch, whose commit messages say so; renumbered at the merge, as
ADR-041 and ADR-042 are the payments hardening.)

**Context.** Two defects in how occupancy rules were ranked (R-07, R-09).
- G-30: `contracts._policy_for` inherited ONE live pricing policy, ranked hotel + market >
  hotel > market > global. So a hotel-only policy beat a market one (the spec says MARKET
  above HOTEL), and nothing cascaded: a hotel+market policy without bands left the contract
  without bands, and every child was then priced as an adult. A policy rule and a version
  rule with the same qualifiers tied (`AMBIGUOUS_OCCUPANCY_RULES` at runtime, publish only
  warned). Nothing stopped two live policies of one scope (the loader took the first by
  name).
- G-31: a band-less position/combination rule outranked a band rule, including the infant
  ×0 rule: the reference fixture charged an infant 25 % as "child 2 of 2A+2C".
Old payloads must keep their sold semantics: prices are computed from the frozen payload
(ADR-004), and the ranking is part of how a payload is read.

**Decision.**
- *Cascade.* Publish loads EVERY pricing policy live at the version's effective time that
  applies to the hotel and market (global, hotel, market, hotel + market) — pure
  `pricing/inherit.py`, Frappe glue `contracts._policy_layers`. Each inherited rule keeps its
  origin: `base_level` (GLOBAL/HOTEL/MARKET) and `scope_weight` (hotel 1 | market 2, as
  `markup.weight`: global 0, hotel 1, market 2, hotel + market 3). The explanation source
  names it, e.g. `policy:POL-00004/r2/hotel+market`.
- *Ranking* (`occupancy.specificity`, v2 = `CASCADE`), for one slot:
  1. infant slots only: a rule naming the infant's band beats every band-less rule, at any
     origin or level (band-less rules still price an infant when no rule names its band);
  2. origin: contract version > hotel + market > market > hotel > global;
  3. level: OVERRIDE > COMBINATION > PERIOD > ROOM > none;
  4. period > room > exact combination; 5. position + band > position > band > neither.
  This reads R-09's chain in two dimensions: GLOBAL … CONTRACT VERSION say where a rule is
  defined, ROOM … SPECIFIC OVERRIDE what it qualifies. Qualifiers rank within an origin, so
  a policy's override or combination rule never beats a contract's own rule (policy rules
  are defaults "overridden by any rule in a contract version", as the policy screen says).
  Two matching rules with the same rank and different values stay unsellable at runtime.
  INHERIT passes to the next rule in this order, so rules cascade by band code (an INHERIT
  infant-band rule falls back to a less specific infant-band rule first).
- *Bands are replaced, not merged*: the version's bands if any, else the band set of the most
  specific policy that defines one. An inherited rule for a band, room or period the contract
  lacks never applies: a WARNING (`OCC_INHERITED_*_UNUSED`), not an ERROR.
- *One live policy per scope.* The `TEX Pricing Policy` controller refuses activating a second
  live or scheduled policy with the same (hotel, market), under a locking read
  (`revisions.live_or_scheduled_roots(for_update=True)`; its None filter now matches a blank
  scope, so the global scope is a scope). `revisions.activate` serialises pricing-policy
  activations first (a lock on the DocType's own row, taken before `Document.save` locks the
  draft's row), so two activations at the same instant wait for each other instead of
  deadlocking on each other's rows; the second then sees the first and is refused with the
  check's message. If two live policies exist anyway, the build fails
  (`inherit.PolicyAmbiguous`, PRICING_POLICY_AMBIGUOUS): publish refuses, validate reports
  BUILD. The controller also upper-cases band codes and checks them (`ages.validate_bands`),
  refuses period codes (periods belong to contracts) and a room type of another hotel.
- *A policy is checked on its own.* It cascades into every contract of its scope, so rows no
  contract could publish are refused when the draft is saved (an adult rule naming a band, a
  combination rule without adults/children), and on activation `validate.policy_issues`
  refuses twin rules and rules that tie in some party (rooms and periods unknown: any party
  the rules name, any band). The policy screen offers the band codes of the live policies a
  policy cascades with (`policies.pricing_policy_bands`), so a hotel (+ market) policy
  without bands of its own can name the market's.
- *Versioned precedence.* New payloads carry `settings.occupancy_precedence = 2` and
  `scope_weight` per rule. A payload without the key reads as 1 (`LEGACY`) and uses exactly
  the old ranking, so sold and live versions price as sold until republished. The payload
  schema string stays `tex.contract.v1`: the keys are optional (no patch, no DocType change).
- *Publish validation* (pure `pricing/validate.py`): `OCC_AMBIGUOUS` ERROR when two
  non-INHERIT rules of equal rank price the same slot with different values in a sellable
  room/party where the tie decides the price: no higher-ranked rule prices that slot (e.g.
  "child 1 at 2+*" and "child 1 at *+2" meet at 2A+2C, unless an exact "2+2" rule prices child
  1 there), the runtime gets to it (every child before it has a rule), and it is priced at all
  (a child filling an included ROOM-basis place is free). So a policy tie that the contract's
  own rules always outrank does not block publishing; one that prices a slot does. A fuzz of
  4,200 random rule sets (PERSON and ROOM basis, children filling places or not, infants
  counted or not) found the static check and the runtime in exact agreement. The sweep's
  `AMBIGUOUS_OCCUPANCY_RULES` is an ERROR; `OCC_INFANT_GENERIC` WARNING when an infant band is
  priced only by band-less rules; `NO_AGE_BANDS` WARNING when a room takes children but no
  bands exist; `scope_weight` joins the duplicate signature. Twin rules of the version are an
  ERROR (`OCC_DUPLICATE`); twins inherited from one policy only where they decide a price
  (`OCC_AMBIGUOUS`); an inherited adult rule naming a band never applies
  (`OCC_INHERITED_ADULT_BAND_UNUSED` WARNING); an inherited combination rule without
  adults/children stays an ERROR (it would reprice every combination).
- *Policy overrides.* A pricing policy's "specific override" ranks within its policy only: a
  contract's own rule, a more specific policy's rule and (for an infant) a rule naming its
  band beat it, although the legacy ranking let it win. Publishing warns where that changes a
  price (`OCC_POLICY_OVERRIDE_OUTRANKED`), and the policy screen says so next to the checkbox.

**Consequences.**
- A policy change reaches a contract only when it is republished (ADR-004); the simulator and
  ORIGINAL_* repricing use the payload of the version on sale at the sale time.
- Live versions keep v1 until republished. `devtools/precedence_report.py` (bench execute,
  read-only) lists versions whose grid prices differ under v2, or when rebuilt with every
  policy live at the version's start (a scheduled version at its `effective_from`), versions
  a republish would refuse (the build fails, or the publish check reports an ERROR, e.g. a
  policy row activated before the policy checks), and scopes with two policies live now or
  scheduled (they cannot publish until one is archived: list them at deploy). The grid prices
  a child at the start of every age band of either side, so a version frozen without bands
  (its children sold as adults) shows its child cells.
- `parent_market` chains are not walked: a policy for a parent market does not reach a
  contract of a child market.
- An infant still counts toward the child count and takes a position (YOUNGEST_FIRST pushes
  the older child to position 2); changing that is a separate product decision.

## ADR-044 A guest's own change settles its money: pay, then apply; refund or credit what is over
**Context.** G-45: on the manage page a higher price was applied at once and the difference was
only "payable online afterwards" (the prompt was even hidden for pay-at-hotel bookings). The
"Refund automatically" and "Keep as credit" policies both just applied the change: the booking
kept a negative balance, nothing was refunded and no credit was recorded. A booking still waiting
for its own payment could be changed, the currency of the new price was never compared, and
the deposit due was never recomputed.
**Decision.**
- *Pure settlement.* `payments.settlement.settle(old, new, paid, required_now(new), …)` decides
  for the booking as a whole:
  - a higher price collects `max(0, min(difference, required_now(new) − paid))` before the change
    applies. `required_now` is each room's frozen deposit rule on the new price (a whole prepayment
    collects the whole difference, a 30 % deposit the deposit share not paid yet, pay at hotel
    nothing). Arrears the booking already had are never charged by a change;
  - nothing to collect: the change applies now and the guest is told what is due later
    (`pay_at_hotel` or `balance`); a credit on the booking is used first;
  - a lower price follows `Property.tex_lower_price_refund`: staff approval (default), a refund
    of the true overpayment `paid − new total` (a deposit-only booking just owes less), or a
    credit kept on the booking;
  - money due now without a card method goes to staff.
  `plan_refunds` takes a refund from the charges holding the booking's money, newest first, each
  capped by its net allocation to this booking, skipping charges TEX cannot refund (manual
  payments, bank transfers, a disabled or non-refunding account, a charge that also holds
  unallocated money). The remainder stays as credit for staff.
- *A request per change.* `TEX Guest Change Request` (schema p20) records what the guest accepted
  (the verified proposal with its pricing time), the booking totals, what to collect, the payment
  attempts, the settlement and its outcome. It is keyed by the proposal: a second submit answers
  what the first did (`payment_required` with the same open charge, `applied`, `requested`, or
  `processing` when another tab is on it). A new request supersedes an open one of the same
  reservation; cancelling the room (guest or staff) voids it. Only outcome fields change after
  insert; no delete.
- *Pay, then apply, server-side.* The charge is started with the key `change:{request}:{attempt}`
  and the reservation is left untouched. `payments.service._after_charge` (after the allocation)
  calls `guest_changes.on_charge_succeeded`, which applies the change as of the proposal's
  pricing time (`modification.apply(_proposal=…, _from_payment=True)`, reservation read with a
  lock, a bounded window of the proposal's 30 minutes plus 60). A change that can no longer apply
  (reservation changed, sold out, window passed) is Failed and its payment refunded; a payment for
  a request that no longer waits (superseded, expired, already paid) is refunded. The hook runs in
  a savepoint and never raises into `complete()`, except a deadlock (the transaction is gone).
  `public.manage_change_pay` pays a waiting change again (the open charge, or a new attempt once
  the still-fresh proposal was priced again at the accepted price); the manage page stops
  offering it once the reservation changed. Staff acknowledging the guest-change flag no longer
  saves the reservation (its `modified` is what a waiting proposal is checked against).
- *Locks.* The booking, then the request, then the reservation: the guest's submit, the payment
  callback (it holds the booking once the money is allocated), the refund job and staff all take
  them in that order. *Amended by the review follow-up below: the change is applied by a job
  after the payment's commit, and staff modifications and cancellations lock the booking first.*
- *Refunds after commit.* Refunds are made by `guest_changes.settle`, queued with
  `enqueue_after_commit` (inline in tests), keyed per request, charge and step, each step
  committed before the next, so a request retried after a deadlock never refunds twice.
  `payments.service.refund(_system=True)` skips the capability check for this trusted caller
  only and always names the booking. What cannot be refunded goes to staff (settlement "Staff",
  audit `guest_change.refund_incomplete`, the booking flagged). *Superseded by the review
  follow-up below: the settlement stays, the money is on `staff_open` / `staff_amount`, and the
  audit is `guest_change.refund_by_staff`.*
- *Credit.* "Keep as credit" keeps `paid − total` on the booking (`booking_summary.credit`); later
  changes use it automatically, because they collect against what is paid. There is no ledger
  across stays.
- *Guards.* No guest change while the booking is Pending Payment or Held (`PaymentPending`,
  `changes_blocked`), and none priced in another currency (`CURRENCY_CHANGED`, `CurrencyChanged`).
- *Staff.* `crs.guest_change_requests` (reservation.view) lists requests, with what approving a
  lower price would leave paid above the new total (`overpaid_after`);
  `crs.resolve_guest_change` approves one at the price the guest was shown (reservation.modify),
  settling an overpayment as a refund (payment.refund) or as credit, rejects one
  (reservation.modify), or closes money staff settled themselves (payment.refund). The reservation
  screen lists the requests of the reservation with these actions. The scheduler expires requests
  whose payment never came and retries refunds that were queued but did not run.
- *Audit.* `guest_change.request`, `.applied`, `.credit`, `.failed`, `.late_payment`,
  `.superseded`, `.expired`, `.refund_by_staff`, `.refund_unknown`, `.refund_capped`, `.resolve`,
  besides the payment events (`payment.refund_unknown`, `payment.refund_verified`).
**Consequences.**
- Inventory is not held while the guest pays: a change can fail after the payment and is then
  refunded automatically.
- The accepted price is honoured for up to 90 minutes after the proposal. Pricing as of that
  moment is deterministic, except that coupon usage limits are counted as they are now.
- The deposit share of the new total is one reading of "what is due now"; a per-hotel choice
  (e.g. the whole difference) would be a later option.
- A refund is on record (Pending) before the gateway is asked: a crash or a timeout after the
  gateway acted leaves an unconfirmed refund for staff to verify, never a second refund.
- A credit belongs to its booking only: moving it to another stay is a staff transfer.
- Any save of the reservation between the proposal and the payment (a staff change, a room
  assignment) makes the paid change fail and its payment be refunded: the guest proposes again.

**Review follow-up (adversarial review of G-45).**
- *Terms the rate would keep are never given back (H1).* A lower price on a non-refundable rate,
  or while cancelling the room now would cost a fee (`booking.cancellation_penalty` > 0), goes
  to the hotel (`staff_approval`) whatever the refund policy: shortening a stay can no longer
  undo a non-refundable rate or a penalty, as a refund or as credit. Guests change a room only
  while it is Confirmed and before arrival (`guard_room`: `manage_propose`, submit, the retry
  and the paid job); an arrived room is not cancelled online either.
- *A refund is never made twice (H2).* `payments.service.refund(durable=True)` (the refund job
  and the staff endpoint) commits the refund as Pending with its idempotency key before the
  gateway is asked, and passes TEX's refund id to a gateway that keeps one (iyzico
  `conversationId`). `ProviderError` or a Failed outcome is a definite "no"; any other error
  (timeout, connection, server) leaves the refund Pending with error `UNKNOWN`
  (`RefundUnknown`, audit `payment.refund_unknown`): TEX never asks again for that key, a
  Pending refund counts against what is refundable and makes its charge unsupported for
  automatic refunds. The refund job stops for that request: nothing moves to another charge;
  the money waits for staff as "Verify refund at gateway" (queue, system status
  `payments.callbacks` `refund_unknown`). Staff close it with what the gateway did
  (`finish_unknown_refund`: Succeeded takes it off the booking, Failed leaves it). Only a
  definite failure moves on to the next charge.
- *A refund is what is still over when it is made (H3).* The job re-reads the booking under
  its lock and refunds at most `paid − total − money set aside for other refunds`: a later
  change or a refund staff made by hand is never refunded again (audit
  `guest_change.refund_capped`). Charges another request must give back (a payment of a change
  that did not apply) are left out of every other refund plan. Money set aside for refunds is
  not the guest's credit (`earmarked`; the guest view shows `credit` and `refund_due` apart)
  and pays for no change; while a refund is being made the booking takes no new guest change
  (`RefundPending`, `changes_blocked: REFUND_PENDING`).
- *The payment callback only records the charge (M1).* `on_charge_succeeded` queues
  `apply_paid(request, charge)` after the payment's commit: a job with its own unit of work and
  deadlock retries that applies the change (or fails it and refunds the payment). A paid change
  left waiting is applied by the scheduler; the payment deadline is judged by when the gateway
  confirmed the charge, not by when the job runs. **Lock order**, everywhere: the booking row,
  then the request, the reservation and the inventory days (`modification.apply` and
  `booking.cancel_reservation` now lock the booking first); the payment callback holds the
  payment row, then the booking, and nothing more.
- *Money for staff is explicit (M2).* `staff_open`, `staff_amount`, `staff_reason` ("Refund by
  staff", "Verify refund at gateway") and `unknown_refund` on the request, set wherever money
  is left to staff (a refund TEX cannot make, a duplicate payment it cannot refund, an approved
  refund that came up short, a refund the gateway never confirmed); `needs_staff` is a
  Requested request or `staff_open`. The settlement stays what it was (`Refund`, `Online
  payment`, …).
- *Guest wording (L1).* The proposal splits a refund into what a card can take back
  (`refund`, planned from the charges holding the money) and what the hotel refunds
  (`hotel_refund`); the answer says whether the card part is back already (`refund_done`); a
  change not made says what became of the guest's payment (`money_back`: none, refunded,
  refunding, hotel), so a declined checkout is never announced as a refund.
- *One request per proposal (L2)* is keyed by the decoded body and signature of the token (the
  raw string let junk appended to it open a second request); the old key is still looked up.
- *No row lock through a checkout (L3).* The first submit commits the request before the
  gateway is asked for a checkout; the request is locked again after the gateway answered.
- Schema: four fields on TEX Guest Change Request (no patch: migrate adds them, nothing to
  backfill before release).

**Second review follow-up (G-45 re-review F1–F8).** The first follow-up made each refund
durable, but a refund run could still act around its own refund in flight, two runs could
overlap, and some money could be left with no one to settle it.
- *A refund run never plans around its own refund in flight, and runs one at a time (F1).*
  `payments.service.refund(on_record=…)` names the new refund on the request
  (`refund_in_flight`) in the same commit as the Pending refund row, before the gateway is
  asked. Every refund run (`guest_changes.settle`) starts, and re-checks before each refund,
  with that refund: still Pending and fresh, the run stops and a later run looks again;
  unanswered (`UNKNOWN`) or older than `REFUND_STUCK_MINUTES` (5; the worker that asked died),
  it goes to staff as "Verify refund at gateway" with `unknown_refund`, and the request waits.
  Nothing is ever planned around it: its charge is not swapped for an older one, and a single
  charge is never handed to staff as "Refund by staff" while its refund may have been made.
  One run per request at a time: the run holds the request's refunds (`settle_claim`,
  `settle_claimed_until`, a lease of `SETTLE_LEASE_MINUTES` = 10 renewed with each refund,
  committed with the first refund's record); a second run meanwhile does nothing, and a run
  that died is taken over once its lease lapsed. `apply_paid` run twice for one payment (the
  job and the scheduler) does nothing the second time: a payment already given back
  (`returned_charges`) or a request whose refund run is pending is never a new late payment.
  Refunds that come off a booking and have no answer yet (a staff refund, a guest change's
  refund) are set aside from what the booking holds (`earmarked`): they reduce what is still
  over, what a change may use and the guest's credit.
- *Every unconfirmed refund can be closed, and is seen (F2).* `payments.finish_refund`
  (payment.refund on the refund's hotel, reason required, POST, audited
  `payment.refund_verified`) records what the gateway did with any Pending refund, from the
  payment screen ("Record gateway outcome"); a guest change the refund was made for is settled
  with it (`guest_changes.verify_refund`, the same path as closing it on the guest change
  card). The system status (`payments.callbacks` `refund_unknown`) counts every refund left
  Pending for more than `REFUND_STUCK_MINUTES`, not only `UNKNOWN` ones. A replay of an
  unanswered refund is announced as not confirmed, never as done; what is refundable leaves
  refunds in flight out.
- *Nothing of a refund is dropped after an unanswered one (F3).* When a refund is not
  answered, the request keeps `settle_pending` (the rest stays owed, set aside and blocks new
  changes); closing the refund with its outcome takes it off `staff_amount` (and adds it to
  `refunded_amount` when it was made) and queues the run again: TEX refunds what the change
  still owes from the other charges, or hands it to staff. A "Failed" outcome is a definite
  no: that charge is skipped, as for any refusal. `refund_done` is true only once nothing of
  the refund is still being made; a refund to verify is shown as a card refund, not a hotel
  refund.
- *A paid change still to be applied is set aside and blocks new changes (F4).* The payment
  of a change waiting for `apply_paid` (and a payment to give back not given back yet) is not
  the booking's to use: no refund plan takes it, no change counts it, and the booking takes no
  new guest change until it is applied (`ChangeApplying`, `changes_blocked:
  CHANGE_APPLYING`).
- *The rate's terms are judged on an arrival moved later too (F5).* Chosen: a change that
  moves the arrival later while cancelling now would cost a fee goes to the hotel
  (`staff_approval`, `settlement.settle(terms_review=True)`), whatever its price: moved out of
  its penalty window the stay could then be shortened (refund) or cancelled (no fee) without
  the fee. A later check-out (an extension), fewer or more guests, and an earlier arrival do
  not move the window and stay self-service. The request records `penalty_terms`; staff see
  it. (Not chosen: judging every later change on the terms held at the first change; it
  would need the original terms carried on the reservation and would still leave the
  cancellation path open.)
- *Transient errors are retried, never judged (F6).* `apply_paid` retries a deadlock, a lock
  wait or statement timeout and a lost connection (MariaDB 1205, 1213, 1969; client 2003,
  2006, 2013; `pymysql.InterfaceError`) a few times, then leaves the change waiting for the
  scheduler; only an error of the change itself fails it and refunds the payment.
- *A queued refund cannot be lost (F7).* `apply_paid` registers the refund job before its
  own commit, so that commit sends it and a later rollback in the same scheduler run cannot
  drop it. The scheduler also sweeps succeeded payments of requests no longer waiting (30
  days back) that were neither the change's payment nor given back and that no refund run
  holds, and hands them to `apply_paid` (the apply job was lost).
- *One lock order, the channel's flows included (F8).* A channel modification or
  cancellation locks the booking, then each reservation, then its nights, and voids a guest
  change still waiting for a room the channel changed or cancelled (`close_open`), as staff
  and guest cancellations do.
- Schema: five fields on TEX Guest Change Request (`refund_in_flight`, `returned_charges`,
  `settle_claim`, `settle_claimed_until`, `penalty_terms`; no patch: migrate adds them).
- Consequences: a request whose refund the gateway did not answer blocks new guest changes of
  its booking until staff record the outcome (they see it in the queue, on the payment screen
  and in the system status). A stay inside its penalty window cannot be moved later online.

**Third review follow-up (G-45 re-review 3).** Recording an outcome could race the gateway
call it was meant to replace, a run could lose its hold, and what a request refunded was a
counter that a lost run never increased.
- *An outcome is recorded only once no answer can come, and never overwritten (High).*
  `payments.finish_refund` and the guest change card record a refund's outcome only when it is
  Pending, stuck (`UNKNOWN`, or older than `REFUND_STUCK_MINUTES`) and no refund run holds the
  request it was made for (`guest_changes.finish_block`, enforced under the locks; the payment
  screen and the card show `can_finish` / `can_close` and the reason from the server). After
  the gateway answered, `payments.service.refund` takes the locks again in **one order: the
  booking (with the caller's request), the refund, its charge**, the order `verify_refund` and
  `finish_unknown_refund` take, and reads the refund again: an outcome recorded meanwhile is
  never overwritten. The same answer is taken as it stands (nothing applied twice; what was
  refunded is counted from the refund rows); another answer, or none, is a `RefundConflict`,
  audited `payment.refund_outcome_conflict` with the gateway's actual answer and failed in
  the system status (`refund_conflict`). A refund run never takes a conflict as a failure: it
  stops refunding that change for good, and what its books say the change still owes goes to
  staff ("Verify refund at gateway", naming the refund) to reconcile. The payment callback's
  order (the payment, then the booking) does not meet this one: a charge is refunded only once
  it succeeded, and a replayed callback takes no booking lock.
- *A run keeps its hold (Medium).* The hold is committed as soon as it is taken, and every
  outcome (a refusal, money left to staff) is committed before the next refund: a refund that
  fails before its own commit (a lock wait, a refusal) rolls back its work, not the hold, so
  the run goes on to the next charge and ends with staff, never "busy" forever.
- *What a request refunded is counted from the refunds it made (Low).* Every refund a request
  asks for is named on it (`refund_rows`, on record with the refund); `refunded_amount` is the
  sum of those that succeeded. A refund made by a run that lost its hold, or recorded by staff
  during the call, is counted once. The lease is renewed before every gateway call.
- *The channel's lock order (Low).* A channel modification locks the booking, its
  reservations (by name), then the nights: a desk or PMS save of a reservation locks it, then
  its nights, so they cannot wait on each other; a new room still takes no name before all
  the nights are held (G-49).
- *The payment job never raises (Low).* A transient error while marking a change failed leaves
  it waiting ("retry"); the scheduler's sweep goes on.
- *Money refunded outside TEX is recorded (G-93).* Closing money left to staff says what became
  of it: "Refunded outside TEX" records Manual refunds of the payments holding the booking's
  money (at most what it still holds over its total, `payments.refund_outside`, audited
  `payment.refund_outside`), so it is no longer counted as paid nor offered as credit; "Kept on
  the booking" leaves it as credit (`staff_settled` keeps what staff settled). The payment
  screen records a refund made outside TEX for any payment (a payment entered by hand is
  refunded that way only).
- Schema: `refund_rows`, `staff_settled` on TEX Guest Change Request (no patch).

**Fourth review follow-up (G-45 re-review 4).** The lease and the order of outcome recording
held; the defects were in the money given back outside TEX and in reads and moves around a
refund in flight. The fixes remove paths rather than add states.
- *Money given back outside TEX comes off where it came from (High, G-93).* A guest change's
  own payments handed back to staff (a change that did not apply, a late or second payment)
  are recorded as given back against exactly those payments, at most what the booking still
  holds of them, on any booking (a deposit-only booking holds no money over its total, and
  the old cap recorded nothing). A lower price refunded by staff is recorded, as before, from
  the payments holding the booking's money, at most what it holds over its total.
  `payments.refund_outside` with a booking named takes the money off that booking only, never
  the payment's unallocated money, and says what came off (`from_booking`); nothing more is
  counted.
- *Limits are locking reads (Medium).* Once a payment is locked, every amount deciding a limit
  (refunded, in flight, allocated, what a booking holds, the idempotency key) is read with a
  locking read (`LOCK IN SHARE MODE`), never from a snapshot taken before the lock (ADR-032's
  rule). Every writer of those rows holds the payment's lock, and the columns are indexed
  (`parent_transaction`, `booking` on TEX Payment Transaction; `transaction`, `booking` on TEX
  Payment Allocation), so the reads lock only the payment's own rows.
- *Money being refunded never moves (Medium).* `release` (and so a transfer) and `allocate`
  leave out money that refunds still waiting for their answer take; after the gateway answered,
  the refund decides again under the locks where the money comes off. A refund can no longer
  leave one booking negative and another holding money already back on the card.
- *A conflict stops the change, not the run (Low).* The payments service calls the guest
  change back while it holds the booking, the request, the refund and its charge: whichever
  run got the contradicting answer, the request stops (`settle_pending` 0, any run's hold
  taken away), names the refund and moves no money; closing is refused. Staff check the refund
  at the gateway and record what it actually did (`payments.resolve_refund_conflict`, audited
  `payment.refund_conflict_resolved`): the refund and the booking are put right (a refund's
  allocation is keyed to it, so it can be taken back), the change goes on from the truth, and
  money left to staff is never more than the change still owes. The system status fails on
  unresolved conflicts only, at any age. (A second run started by a verification recorded
  while the first run's call was still going — possible only once a worker stalled past its
  lease — can still have refunded from another payment first; the conflict then shows it to
  staff, and nothing refunds on that change until they put it right.)
- *Refunds made, named on old requests (Low).* Patch p28 fills `refund_rows` from the refunds
  on record: the gateway refunds reasoned `Guest change <request>: …` (the idempotency keys
  are hashed and cannot be matched by prefix) and the request's refund in flight or to
  verify; refunds recorded as made outside TEX are left out. It can run again.
- *One lock order (Low).* `refund_outside` locks the booking(s) holding the payment before the
  payment, as every refund does; the staff refund endpoint runs a deadlock victim again (its
  key replays a refund already on record).
- Schema: four indexes (above); patch p28.

## ADR-045 A published contract's commercial terms are fixed; selling terms are versioned and selection reads the frozen version
*Amended by the G-50 review follow-up: header narrowings made before the upgrade survive it (p25),
a suspend stops quotes and bookings in flight, and the scheduler isolates each record.*

**Context.** G-50 (R-04). After a publish, the contract header stayed editable through the TEX
API, Desk and REST: market, channels, sale and stay windows, priority, sell currency and status.
- Selection (`candidate_contracts`) read the live header, while pricing read the version's frozen
  payload. A header edit could:
  - make a contract a candidate for a market or channel its payload refuses;
  - hide a contract that still sells.
- Priority and sell currency were not frozen at all, so a header edit changed which contract
  wins and the offer's currency, with no new version.
- Historical selection (a modification priced at the original sale date, the simulator) used
  today's header.
- The `save_contract` audit had no channels. Desk and REST header saves were not audited, except
  for status.
- The first idea was "lock the header; publish a new version". It had a gap: a new version froze
  the header's values, so with a locked header no version could ever change a window or a
  channel. Only a new contract could, and a new contract loses everything linked to the contract
  (allotments, restrictions, markups, channel mappings).

**Decision.**
- *Fixed terms.* Once any version was published (Published, Superseded or Withdrawn: it may have
  sold), the hotel, market, contract currency and pricing basis never change. Another market or
  currency is another contract; Duplicate lets the user pick the market.
- *Selling terms are versioned.* The sale window, stay window, channels, priority and default sell
  currency belong to each version:
  - they are new fields on `TEX Contract Version`, frozen into the payload at publish;
  - `priority` and `sell_currency` are new payload keys; the sell currency is frozen resolved
    (the contract currency when blank);
  - until the contract's first publish, the header is their source (new-contract dialog,
    `save_contract`);
  - after that, `new_draft` gives the draft the terms its source version froze (read from the
    payload, not from the version's fields), `save_version` edits them (`selling`), and the version
    editor shows them (Settings → Selling terms);
  - they change only by publishing a new version. A shorter window (a narrowing) is also a new
    version, published now, validated and audited. There is no free narrowing edit.
- *The header mirrors the live version.* It is updated by the publish when the version takes
  effect now, and by the 15-minute job when a scheduled version goes live (audited
  `contract.version_live`). Lists, Desk and REST readers therefore still show what is on sale.
  Nothing reads the mirror to sell.
- *The controller enforces it*, so the TEX API, Desk and REST are all covered:
  - After the first publish, a change of a fixed field or a selling term is refused. The message
    names the fields and says what to do: duplicate the contract, or change the terms in a draft
    version and publish it.
  - The hotel never changes after creation.
  - `status`, `active_version` and `latest_version_no` move only through the lifecycle (publish,
    withdraw, the scheduler; flag `tex_lifecycle`) or a status action.
  - A new contract always starts as Draft.
  - Code, name, notes and the BAR flag stay editable. Selection and pricing do not read them.
- *Status actions.* `contracts.set_contract_status(name, action, reason)`:
  - suspend: Active → Suspended, selling stops at once;
  - resume: Suspended → Active, needs a Published version;
  - archive: Draft, Active or Suspended → Archived;
  - restore: Archived → Suspended, or Draft if the contract was never published.

  Each action needs `contract.publish` at the contract's hotel and a reason. It takes a row lock
  and is audited as `contract.status` with the reason. Status is not versioned on purpose: a stop
  sale must act now.
- *A suspend stops what is in flight.* Offers (20 minutes) and quotes (30 minutes) taken before a
  suspend no longer sell: `create_quote` answers `CONTRACT_SUSPENDED` (or `CONTRACT_NOT_ON_SALE`
  for an archived or draft contract), and `create_booking` raises `ContractSuspended` /
  `ContractNotOnSale`. The booking reads the status under a shared row lock, so a suspend (which
  takes the row's exclusive lock) waits for bookings in flight and every later booking sees it.
  Guests hear only "This rate is no longer on sale". Modifications of stays already sold are not
  new bookings and are unaffected.
- *Channel bookings* are the channel's sale, and the guest holds the channel's confirmation. A
  stay on a mapping whose contract is not Active (or, without a mapped contract, where no contract
  sells the market and channel) is accepted with a warning and a `channel.overbooking` audit, like
  an overbooking. The ARI TEX pushes already closes the contract, so this covers only the time
  until the channel applies it.
- *Selection reads the frozen version.* `candidate_contracts` takes only the hotel and the status
  from the header. Everything else comes from the payload of the version live at the sale time,
  the same terms pricing runs on:
  - the market (or GLOBAL);
  - the channels and the sale window;
  - the priority and the sell currency.

  A header changed behind the controller (DB, data import) therefore changes nothing, and
  historical selection is reproducible: it depends only on versions and their stored terms.
  `load_terms` reads the payload hash first and reads the payload only on a cache miss.
- *Versions frozen before G-50 keep their header narrowings.* Before G-50, selection read the
  header and pricing the payload, so a contract sold only where both allowed. A header narrowed
  after publish (a channel removed, the sale window closed, the market changed) was a working stop
  sale. Reading only the payload would have reopened it on deploy. So:
  - such a payload (no `priority` key; `ContractTerms.priority` is `None`) sells only where both
    it and the header allow (`selling_terms`): both markets must admit the request (a GLOBAL
    payload under a DE header sells DE only; a DE payload under a UK header sells nowhere, as
    before), the sale windows and the channels are intersected, and priority and sell currency
    are the header's. The header's stay window never narrowed anything and still does not;
  - patch p25 copies the header's selling terms and market onto every published version frozen
    before G-50: the version's own selling-term columns, `header_market` and `header_snapshot_at`.
    From then on the narrowing is fixed; later header changes no longer move it, so historical
    selection over these versions is reproducible too. Before p25 has run, the live header stands
    in;
  - p25 prints and audits (`contract.header_differs`: payload values as old, header values as
    new) every contract whose header differs from its live payload, so staff can publish a
    corrective version where a difference was not meant to narrow sales;
  - a draft based on such a version (`new_draft`, or a version inserted in Desk/REST with or
    without `based_on`) starts from what it sold. Where it sold nothing (header and payload
    windows or channels do not overlap), the draft takes the header's value, the terms staff last
    set. A new version is built with the header's market, which is locked;
  - the scheduler does not mirror such a version onto the header (the header is where its
    narrowing came from); the contract page and the version editor show its effective terms
    and say that the header still narrows it.

  No published payload or hash is rewritten. Patch p21 gives every existing draft of an
  already-published contract without selling terms of its own the header's terms, which is what
  its publish would have frozen before G-50 (audited `contract.version.selling_backfill`); a
  draft that has terms is left alone, so p21 and p25 can run again safely. Drafts of unpublished
  contracts need nothing.
- *The scheduler isolates each record.* Each version flip and each contract going live runs in a
  savepoint; a record that fails (e.g. a legacy header that no longer validates) is rolled back to
  it and logged, and every other hotel's contracts still roll.
- *Audit.* The controller audits every header change on every path:
  - `contract.save` holds the old and new value of each changed field, with channels as a sorted
    list; creation holds the full header;
  - `contract.status` holds the reason;
  - `contract.publish` holds the frozen selling terms (new) and the header's before (old).

**Consequences.**
- A version frozen before G-50 is selected on the header terms snapshotted at the upgrade, not on
  the terms of the day it was sold (the header was not versioned then). Sites where p21 ran
  before p25 existed (dev and test sites) get the snapshot from p25 on their next migrate.
- Selection loads the live version of every Active contract of the hotel (one hash read each;
  payloads are cached per process) instead of filtering markets in SQL; a version frozen before
  G-50 costs one more read for its snapshot.
- Status stays live, not versioned: the simulator still cannot select an Archived or Suspended
  contract for a past sale time (G-51).
- Extending a sale window or adding a channel now needs a new version and a publish (with
  `contract.publish`); `contract.edit` alone prepares the draft.

## ADR-046 Consent needs a proven owner; bearer tokens never travel in a URL path; public files never carry active content
**Context.** G-83 (security hygiene, R-53) found four behaviours that trusted what a browser
sends:
- An anonymous booker who typed the e-mail or phone of an *existing* guest profile set that
  profile's marketing consent (`booking.find_or_create_guest`). Anyone could opt a stranger in,
  and abandoned-payment recovery then used the profile's contact data on the same tick.
- A payment link was `/book/pay/<token>`. The bearer token sat in the URL path, so it reached
  web-server access logs and the `Referer` of every request the page made. Manage links
  already used the fragment (`#token=`).
- Booking-site images were validated only in the browser, through Frappe's generic
  `upload_file`, which lets any Desk user store HTML or SVG in the public folder, served in the
  platform's origin.
- The PMS webhook adapter refused an empty signing key only as a retryable error, and a webhook
  connection could be enabled without a secret.
**Decision.**
- *Consent needs a proven owner.* Marketing consent is only ever granted explicitly, by someone
  who owns or is accountable for the profile:
  - a booking that *creates* the profile records the booker's consent (source `booking`);
  - staff (CRS) record it on an existing profile (source `booking (staff)`): they took the
    guest's word and are accountable for it;
  - an anonymous booking that *matches* an existing profile changes nothing on it. The request
    is audited (`guest.consent_requested`, with the booking) and the CRM consent history shows
    it as "requested, not applied". The hotel records it once the guest confirms on a verified
    channel (CRM, with the source).
  - Every consent granted through a booking is audited (`guest.consent`). Nothing in a booking
    withdraws consent; withdrawal stays one CRM step. Abandoned-payment recovery keeps contact
    data only when the profile itself has e-mail consent.
- *Bearer tokens never travel in a URL path or query string.* Guest links carry their token in
  the fragment (`manage#token=…`, now also `pay#token=…`), which browsers never send to a
  server. The page moves it out of the address bar, keeps it for the tab and posts it in a JSON
  body; endpoints that take a token accept POST only. Links issued before (`/book/pay/<token>`)
  keep working until they expire (at most 60 days): the page moves the token into the fragment
  before the app starts, and payment pages answer with `Referrer-Policy: no-referrer` (header
  and `<meta>`, both mounts). Tokens are stored only as hashes.
- *Public files never carry active content.* A File controller extension
  (`hooks.extend_doctype_class`, `kamra.tex.security.uploads.PublicFileGuard`) refuses HTML, SVG,
  XML and script as a public file on every path, before anything is written, and refuses making
  such a private file public. TEX images go through `admin.upload_site_image`: the bytes decide
  (PNG, JPEG, GIF or WebP, decoded by Pillow, 2 MB, 8000 px), never the name. A booking site's
  logo and hero image are an image of the platform or an https address.
- *A signing adapter never sends unsigned.* An adapter that signs (`requires_secret`) cannot be
  enabled without a secret; at run time a missing secret or a non-https endpoint is a final
  refusal (`AdapterRefused`: Dead at once, audited as `connect.delivery_refused`, reason only),
  in every environment. The Connect screen's retry sends it once fixed.
- Payment provider API keys are Password fields like every other credential (p22).
**Consequences.**
- A returning guest who ticks marketing consent in the booking engine is not opted in until the
  hotel confirms it. A double opt-in e-mail (a signed confirmation link sent to the profile's own
  address) would close that loop without staff; it needs outgoing e-mail (BLOCKED, SMTP) and is
  an owner decision.
- The first request of a payment link e-mailed before this change still carries its token in the
  path, so it can appear once in an access log until the link expires or is reissued (reissuing
  gives a fragment link and voids the old token). Removing that needs log scrubbing at the proxy,
  an operations decision.
- Frappe's e-mail queue keeps the message body, link included, until the queue is cleared;
  TEX never stores or logs the raw token itself.
- An SVG logo can no longer be uploaded (TEX or legacy screens); an https URL still works.

**Review follow-up (G-83 adversarial review, 2026-09-23).** Corrections to the decision above:
- *The stored name decides, against an allow-list.* The guard judged the name a client sent:
  `x.png?.html` was stored as `x.png_.html`, a `file_url` of `/files/e%2Ehtml` as `e.html`, and
  XML types browsers render (`.rss`, `.atom`, `.rdf`, `.mml`, `.kml`, `.xsd`) were not on the
  block list. It now judges every name File can store the bytes under (URL-decoded, then
  Frappe's `[/\%?#] → _`): before File's own `before_insert`, again on the final name right
  before the bytes are written (`save_file_on_filesystem`), and on the final URL when a file is
  created, made public or moved. The public folder serves only an allow-list
  (`filetypes.PUBLIC_EXTENSIONS`): images (png, jpg/jpeg, gif, webp, avif, bmp, ico, tif/tiff,
  heic/heif), video (mp4, m4v, mov, webm, ogv, 3gp), audio (mp3, m4a, aac, oga/ogg, opus, wav,
  weba), PDF and office documents (pdf, txt, csv, tsv, doc/docx, xls/xlsx, ppt/pptx, odt, ods,
  odp, rtf), fonts (woff/woff2, ttf, otf, eot) and zip, and never a type whose MIME type is HTML,
  XML or script. That is what upstream Kamra and TEX store publicly (room and housekeeping
  photos and video, logos, brochures); anything else is stored private, where Frappe checks
  access and forces a download. A file whose URL is under `/private/` is private without the
  flag, as Frappe decides. With a storage hook (`write_file`, e.g. S3) the final-URL check
  still refuses the record, after the upload.
- *Inline images.* A public inline SVG (`extract_images_from_html`: Print Format HTML, doctypes
  with public attachments) is refused with the reason, stopping the save visibly; it is not
  stored private silently (a web page would then show a broken image). Use a PNG or WebP.
- *Images decode whole.* `verify()` checks only PNG. Every frame is now decoded with
  `LOAD_TRUNCATED_IMAGES` off (Frappe turns it on globally); an iPhone multi-picture JPEG (Pillow
  reports `MPO`) is a JPEG.
- *Site images.* A new logo or hero is a PNG/JPEG/GIF/WebP under `/files/` (no `..`, no
  `/private/` or `/assets/`) or an https address on another host, never the platform's or a
  booking domain (an image request carries the viewer's session to whatever path it names).
  Only a changed image is judged, so a site with an older image stays savable; patch p24 lists
  those sites.
- *Existing data (p24).* Public HTML, XHTML and script files are made private; other public
  files the allow-list no longer serves (SVG logos, XML) are reported one by one
  (`file.public_active_content`), since a page may still show them. Plain API keys kept in the
  change history (Version) of payment provider accounts before p22 are masked; a Password field
  reaches the history only as asterisks.
- *Consent needs `crm.edit`.* Staff who may only sell (`reservation.create`) record a request,
  like an anonymous booker; only staff who may edit guest profiles at the hotel apply consent to
  an existing profile. The CRM consent history shows entries of the viewer's hotels and
  profile-level changes only, never another hotel's bookings or staff.
- *Referrer-Policy behind nginx.* bench's nginx adds `Referrer-Policy: same-origin,
  strict-origin-when-cross-origin` to every response, proxied ones included, and browsers use
  the last valid value, which would weaken the payment pages' `no-referrer` header. The page's
  `<meta name="referrer">` still wins, so the pages are safe; production nginx should not add
  its own policy on `/book/pay`, `/pay` (GO_LIVE_READINESS §4 has the snippet).

## ADR-047 Operations: a scoped system status, a boolean guest ping, alerts on change; guest e-mail status follows Frappe's queue
**Context.** GO_LIVE_READINESS listed two operations gaps.
- *Monitoring.* TEX had no status endpoint. `kamra/health.py` is upstream Kamra diagnostics: it
  checks Kamra-PMS releases and is refused to hotel users while the PMS is off. Nothing alerted
  on dead jobs, stale FX, mail errors or failed callbacks, and an uptime monitor had nothing to
  poll.
- *E-mail.* A TEX Communication stayed "Queued" for ever: TEX never learnt what the e-mail queue
  did. "Resend" reported a queued mail as sent. A mail the queue refused (no outgoing account)
  left no record, and every guest mail carried the outgoing account's name.
**Decision.**
- *Status service.* The checks live in `kamra/tex/ops`:
  - `checks.py` is pure (no frappe import). It holds the thresholds as named constants, the
    verdicts, the transition rule and the alert text;
  - `status.py` is the Frappe glue: counts and timestamps from the database, Redis and the site
    config;
  - a check is `{key, title, scope, status: ok|warn|fail, detail, count, since, issues:
    [{reason, status, params}], properties?}`. `detail` is English for mails and logs; the UI
    translates `reason` with `params`.
- *Scopes.*
  - Hotel checks count only the viewer's hotels and name the hotels with a problem:
    `outbox.pms`, `outbox.channel`, `channel.inbound`, `connections`, `payments.pending`,
    `payments.callbacks`, `fx.rates`, `mail.delivery`.
  - `mail.account` (is there a default outgoing account) is shared configuration, shown to every
    monitor.
  - Platform checks go to platform administrators only: `scheduler`, `scheduler.jobs` (last run
    of each TEX job from `Scheduled Job Type.last_execution`), `scheduler.errors` (Error Log
    "TEX job …"), `workers` (RQ workers and backlog of this bench), `encryption_key`
    (presence only) and `mail.queue` (the whole Email Queue).
  - A probe that raises becomes a failed check (logged without frame locals). An unreachable
    Redis is a finding (one connection attempt), never a crash.
- *Thresholds* (`checks.py`):
  - a TEX job is late after 10 / 20 / 45 min (every minute / 5 / 15 min) or 26 h (daily jobs),
    and fails at 3× that;
  - an outbox or inbound message is late after 30 min (fail at 4 h); any Dead message fails
    (Dead ARI and PMS messages count only for enabled connections; a dead channel booking always
    counts);
  - a card charge still Pending after 60 min, started in the last 48 h, warns;
  - a rejected or failed gateway callback in the last 24 h warns, and so does a link paid twice
    in 7 days; a capture that did not match its charge in 7 days fails;
  - FX: for each provider pair an active FX policy uses (hotel or global), the latest rate as
    pricing would find it warns when older than 2 business days (weekends do not count, so a
    Monday morning before the fetch is not an alarm) and fails past the policy's own
    `max_age_days`, where pricing refuses it; a missing rate fails;
  - guest e-mail: a failure in 24 h warns (fail from 5); an unsent mail after 30 min warns (fail
    at 4 h); the queue backlog warns at 500 jobs (fail at 5000);
  - things the owner must set up fail a live site and warn a developer one: the scheduler off
    (live = `tex_production` or not `developer_mode`), no default outgoing e-mail account (fail
    only with `tex_production`), no worker.
- *Endpoints* (`kamra/tex/api/system.py`):
  - `status(property?)` (GET) needs the new capability `system.monitor` (every admin profile;
    p23 grants it to the seeded Hotel, Group and Enterprise Admin profiles). Without `property`
    it covers every hotel where the caller holds it. The payload has counts, ages, job names,
    currency pairs and hotel names: never a secret, token, guest data, connection error text or
    stack trace. The overall status is the worst check.
  - `ping` (guest, GET, 30 requests/min per IP, `tex_ping_limit` may raise it) answers
    `{ok, db, cache, scheduler}` booleans only. It returns HTTP 503 when the database or the cache
    cannot be reached. `scheduler` is true when the every-minute TEX job ran within 10 minutes.
    There are no counts, versions, host or hotel names, so an uptime monitor can poll it without
    a credential.
- *Alerts.* `ops.alerts.evaluate` is the last job of `every_15_minutes` and sees what a platform
  administrator sees.
  - What is remembered is the status of every check that is not ok. It lives in the audit trail:
    a `system.status_changed` event is written only when that state changes.
  - A check that gets worse (ok→warn, ok→fail, warn→fail) writes an Error Log entry
    (`TEX status alert: …`) and is mailed once to TEX Settings `status_alert_recipients` (at
    most 20, validated) through the normal e-mail queue.
  - A recovery to ok is mailed once. A check that stays bad, or improves from fail to warn,
    sends nothing.
  - All changes of a run go out in one message, so there is at most one mail per 15 minutes
    and only when something changed.
  - Other stores were rejected. Global defaults reach every Desk session's boot. Redis state is
    lost on a restart, and every restart would re-alert. A field on TEX Settings could be
    overwritten by a concurrent settings save.
- *E-mail delivery status.*
  - Every guest mail's TEX Communication keeps its Email Queue row (`email_queue`).
    `services.mail_status.sync` runs every 5 minutes: one indexed join, batches of 500,
    idempotent. It moves Queued to Sent (setting `sent_at` to when the queue sent it) or Failed
    (Error; Expired on older Frappe).
  - It is a scheduled job, not an Email Queue `on_update` hook, because Frappe changes the
    queue's status with `set_value`: no document hook ever runs.
  - "Sent" means the mail server accepted the message. TEX never claims "Delivered".
    Not Sent, Sending and Partially Sent (a single-recipient TEX mail being retried) stay Queued.
  - A failure keeps a short, address-free reason (`delivery_error`, e.g.
    `SMTPRecipientsRefused (550)`).
  - A mail the queue refused is recorded as Failed with the exception name, and its message no
    longer reaches the response.
  - `resend_confirmation` returns `queued` and `status` ("Queued" / "Failed") instead of
    `sent`, and the UI says "queued". The payment-link dialogs say the same.
  - p23 links older Queued communications to their queue row only where exactly one row fits
    (same booking or payment link, queued up to 60 s before the log, unclaimed). The others stay
    Queued and are never judged by the status check.
  - `mail.delivery` reads these same rows.
- *Hotel sender.* Guest mail goes out with the hotel's name as the From display name. The From
  address is always the default outgoing account's own address: an address of the hotel's
  domain would be spoofing through this mail server, and Frappe would send it through the
  default account anyway. Reply-To is the hotel's e-mail, else its booking site's contact
  e-mail, when valid. These fields exist already, so the design needs no new field.
- *UI.* TEX → Settings → System status is shown to platform administrators and to anyone with
  `system.monitor` at some hotel; the server re-checks. It groups the checks (Platform /
  Operations) with badge, translated issues, hotels and since-time, and has a refresh button.
  Platform administrators also get the ping address. The alert recipients are part of the TEX
  settings.
**Consequences.**
- An abandoned card checkout looks like a lost callback: it shows as a `payments.pending`
  warning for up to 48 hours. Telling the two apart needs a status query to the gateway.
- Alerts need SMTP, which is an owner input. Without SMTP, every change is still in the Error
  Log and the audit trail, and the status page shows it.
- Nothing leaves the site: an external uptime monitor, log shipping and APM are owner
  infrastructure. The ping is what the uptime monitor should poll.
- `kamra/health.py` is unchanged and remains upstream diagnostics, not TEX monitoring.
- A per-hotel sending address (the hotel's own domain) needs an outgoing account per domain
  with SPF/DKIM. That is an owner input and is not built.
- Bounces after the mail server accepted a message are not tracked.

## ADR-048 A TEX hotel's rooms are TEX inventory, whoever writes the reservation; an allotment's release and cutoff are separate
*Amended by the G-49 review follow-up: a change is checked only on the nights it newly takes; a
cutoff also gives the rooms back; a reservation books only its own hotel's room types; a service
flag covers one save; deadlocks of desk writes, channel bookings and imports; channels hear
allotment deadlines at the site's midnight.*

**Context.** G-49 (R-17).
- The legacy `Reservation.validate_type_capacity` (physical rooms of the room type times the
  overbooking allowance) ran on every save, TEX's own stays included. It refused what TEX had
  allowed: an explicit oversell, a shared pool (a Deluxe sold from the Standard rooms of its
  pool) and configured inventory above the physical rooms. It also refused later saves of such a
  stay (a note, a check-in). Only channel bookings were excepted (`tex_channel_accept`, G-69).
- A reservation written outside the TEX services (the Desk form, REST, `import_bookings`,
  `migrate.run_import`, legacy PMS actions by platform administrators) took no TEX inventory
  lock. It was checked only against its own snapshot, by the legacy rule. TEX's counts included
  it once it existed, but closures, manual adjustments and guaranteed allotments did not stop
  it, and a desk stay and a TEX booking could both take the last room.
- R-17 lists "allotment, cutoff, release"; an allotment had one field, `release_days`.
- ADR-028 keeps admin imports writing reservations directly (migrations, not sales).

**Decision.**
- *At a TEX hotel TEX inventory is the only capacity rule.* `validate_type_capacity` asks
  `kamra.tex.legacy.is_tex_hotel` first. For a TEX hotel it hands over to
  `availability.repository.guard_reservation` and the legacy rule never runs. Hotels outside TEX
  keep the legacy rule unchanged (the upstream suites rely on it).
- *Who checked it.* A stay written by the TEX booking or modification service carries
  `flags.tex_inventory_checked`: the service locked the nights and recounted for its contract
  (allotments included) before writing. A channel's sale keeps `flags.tex_channel_accept` and is
  accepted as sold. Document flags live only in the process: a REST payload cannot set them, so
  a forged `tex_booking` or price lock gains nothing.
- *Every other write takes the lock.* A save "takes rooms" when it creates a live stay, moves a
  stay into a live status (Waitlist → Confirmed), or changes the hotel, room type or nights of a
  live stay. Such a save takes the same `TEX Inventory Day` locks as a TEX booking
  (`lock_nights`) and recounts under them with a locking read. A new reservation takes them in
  `before_insert`, before its naming-series row lock: a TEX booking locks inventory days first
  and names after, so the two never wait on each other in a cycle. It is refused when TEX has no room
  left, with the night, the sold count and the capacity: closures, manual adjustments, the
  oversell limit, pools, configured inventory and guaranteed allotments all apply. It sells from
  general sale (no contract), so it never uses a contract's allotment. A day-use stay holds its
  day. Restrictions (stop sell, LOS, CTA …) are selling rules of TEX's channels and do not apply
  to it.
- *Saves that take no room are never refused* (a note, a room assignment, check-in, a payment,
  cancellation), so an oversold stay stays editable.
- *A change is checked only on the nights it newly takes* (review H1, M1). The nights a stay
  already holds in the pool (`repository.held_nights`) are its own: a cutoff, a closure or a
  full house on them never refuses a change. Leaving early, a room type of the same pool, or an
  extension is checked only on its new nights; a change that takes none is never refused. A
  move to another pool (or hotel) takes every night again. This applies to TEX modifications
  (`modification.propose`, staff and guest self-service alike) and to writes outside TEX (the
  guard locks and recounts only the new nights). A night held under one contract and kept after
  repricing under another is not re-checked against the new contract's allotment.
- *A reservation books only its own hotel's room types* (review M3). `Reservation.validate`
  refuses another hotel's room type (without naming that hotel), for every hotel, TEX or not;
  it is checked when the stay is written or its hotel or room type changes, so legacy rows are
  never blocked. The guard and the lock before naming work on the room type's own hotel, so no
  inventory row of one hotel is created under another and no figure leaks.
- *A service's flag covers one save* (review L3). The guard pops `tex_inventory_checked`, so a
  later save of the same document object is checked again.
- *We chose to take the lock rather than refuse.* The model cannot tell a Desk sale from a
  migration import or a legacy PMS action (an extension, a waitlist confirmation). ADR-028 keeps
  imports. Refusing would strand the existing stays of a hotel that joins TEX. With the lock, no
  write can hold a TEX hotel's rooms outside TEX's rules. The legacy selling endpoints stay
  refused (ADR-028).
- *Release and cutoff are two deadlines*, both in days before each night of the allotment:
  - release (`release_days`, unchanged): the hotel's side. Unsold rooms go back to general sale:
    a guaranteed allotment stops being withheld, the contract's cap ends and it sells from
    general sale;
  - cutoff (`cutoff_days`, new): the partner's side, the contract's booking deadline. From then on
    the contract sells nothing more for that night, from its allotment or from general sale.
    Other sales are unaffected. 0 = no cutoff.
  - *The cutoff also gives the rooms back* (review L2). Once the contract can no longer book its
    rooms, nobody could, so they return to general sale at the cutoff at the latest: the
    effective release is `max(release, cutoff)`. We chose this over letting privileged staff book
    under the contract after its cutoff: that would need a new capability and an audited
    override in the booking service, while the rooms simply went unsold. A rooming list for rooms
    already booked needs no inventory.

  Release 7 / cutoff 2: the rooms return 7 days out and the partner books from general sale until
  2 days out. Cutoff 10 / release 3: the partner stops 10 days out and the rooms return then.
  The pure `inventory_math` reports a cut-off night as `cutoff`. Search, quotes, bookings,
  modifications, the ARI grid and channel ARI all read it. Both deadlines count days on the
  site's day (System Settings time zone), not a hotel's own time zone.
- *Channels hear a deadline when it starts* (review L4). A job just after the site's midnight
  (`distribution.repository.allotment_boundaries`, cron `1 0 * * *`, which Frappe evaluates on
  the site's clock) queues an ARI push for the nights whose release or cutoff starts that day.
  The 02:30 daily resync remains the safety net.
- The controller keeps both within 0 to 365 days. A disabled allotment always saves, so one
  whose release is above 365 (possible before p27) can be switched off; to edit it otherwise,
  bring the value into range. The allotment editor (Rates → Allotments) sets both.
- *Patch p27.* Every existing allotment gets cutoff 0 and sells exactly as before. A negative
  release behaved like 0 and becomes 0. A release above 365 days is printed for review.
- The ARI restriction field `release_days` (R-16) is a separate thing: a booking-window rule
  on any scope ("stop selling N days before arrival", violation `RELEASE`). It keeps its name
  and meaning.

**Consequences.**
- A reservation at a TEX hotel written through Desk, REST or an import now waits for TEX
  bookings of the same nights, and may be refused where the legacy rule accepted it. A TEX
  hotel's reservations are sold through TEX. To sell above capacity, staff set a manual
  adjustment or an oversell limit in Inventory.
- *Deadlocks* (review M2, L1). Lock orders that can still meet:
  - `modification.apply` locks the booking, then the reservation (`FOR UPDATE`), then the
    nights (G-45 order, kept). Every recount (`create_booking`, the guard, a channel booking)
    locks the nights, then reads the pool's live reservations `LOCK IN SHARE MODE`. That read
    locks every live reservation of the pool arriving before the stay ends, not only the
    overlapping ones: the index is `(room_type, status, check_in_date)`, and a
    `check_out_date > start` condition would only filter rows after they are locked. A lower
    bound on arrival would need a maximum stay length, which neither TEX nor the legacy PMS
    enforces, so the read is left as it is. An `apply` holding its reservation and a recount
    holding the nights can therefore deadlock; one of them is the victim.
  - Every TEX endpoint into a booking or a change re-runs a victim (`retry_on_deadlock`:
    `public.book`, `manage_apply`, `manage_change_pay`, `crs.book`, `crs.apply_modification`,
    `crs.resolve_guest_change`, `ui_crs.book`; a test keeps the list complete). Payment-driven
    guest changes retry from their job.
  - A desk or REST write cannot be re-run for its user. When it is the victim it is refused with
    "please try again" (`InventoryBusy`, a `ValidationError` that is also a
    `QueryDeadlockError`): nothing of it was saved.
  - Imports (`import_bookings`, `run_import`) stop on a deadlock instead of reporting the rows
    InnoDB has already undone as created.
  - A channel booking takes every room's nights before its guest, booking or rooms take a name,
    in the order of a TEX booking and of a desk write.
  - Remaining risk: an edit of an existing desk stay holds its own row (`check_if_latest`)
    before the nights, and a multi-row import holds the naming series from its first row on.
    These are rare and end as "please try again".
- A Desk/REST insert at a TEX hotel still prices through the legacy auto-price. It is not a TEX
  sale and carries no TEX price lock. Only its inventory is governed here (G-92, open).
- Writes that bypass validation (`db_set`, SQL, history imports with `ignore_validate`) also
  bypass this guard, as they bypass every other rule.
- An allotment's cutoff is per contract. Allotments still have no channel dimension (G-41).

## ADR-049 The staff app's "today" is the site's day, from the server; the browser's clock only measures
**Context.** G-91 (R-50): staff date pickers and default ranges started on the browser's day
(`isoDay(new Date())`). The hotel's day is the server's day in the System Settings time zone:
the server refuses a past arrival on it (`quoting._dates`), expires grants on it
(`scope._grants`), dates FX rates and reports with it. Just after the site's midnight a browser
in an earlier zone was still on yesterday (a grid starting yesterday, a refused arrival, a
transactions list closed a day early); one in a later zone was already on tomorrow and refused
the site's today as "in the past". The channel ARI preview had been fixed alone by asking the
server for its first day.
**Decision.**
- `session.bootstrap` returns `server: {time_zone, now, today}` read from one instant, last,
  just before the response leaves.
- `frontend/src/tex/lib/siteDay.ts` is the only source of a business "today" in the staff app:
  `useSiteToday()` for what is shown (re-renders at the site's midnight), `useSiteClock()`
  (`today()`, `dayAfter(ms)`) for handlers and resets; `serverClock.today` delegates to it.
- The site's wall clock is `Intl.DateTimeFormat({ timeZone: server.time_zone })` of the
  browser clock plus a skew measured once: `server.now` minus that zone's wall clock read in
  the browser when the bootstrap arrived. Chosen over "server day + elapsed time" alone because
  Intl follows the site's own DST changes while a tab stays open for days, and over Intl alone
  because the skew cancels a browser clock that is off (and zone data that disagrees with the
  server's by a fixed offset). A browser that does not know the zone counts the time elapsed
  since `server.now`. The result is never before `server.today`.
- A default that should follow the day while the page stays open is kept as `null` = "site's
  today" in state (inventory grids, FX rate date), not copied into state at mount.
- The browser's clock stays in use only for what means "now, here": durations and timers
  (countdown TTLs, call timer), instants shown in the viewer's zone (call log, "checked at"),
  and a datetime-local value that is sent as an absolute instant.
- Endpoints never need the client to supply "today": an open-ended date filter is open
  (`payments.transactions` filters on either bound alone).
**Consequences.**
- New staff screens take "today" from `lib/siteDay`; `isoDay(new Date())` in `screens/**` is a
  defect. The public booking engine is guest-facing and out of this decision.
- `presetRange(preset, today)` and `defaultSearchForm(today, …)` take the day as an argument.
- Tests: `TestSessionSiteDay`, `test_transactions_filter_on_either_date_bound`, e2e `site-day`
  (browser in Pacific/Honolulu pinned just after the site's midnight).

## ADR-050 Staff price and book only on the sales channels they are entitled to at a hotel
**Context.** G-41 (R-25): the sales channel is a pricing dimension (markups, promotions,
restrictions and contracts can differ per channel), but the CRS took it from the request. Any
agent with `reservation.create` could search, quote and book on DIRECT_WEB, OTA or API prices
from the call centre, and a Booking Engine quote could be booked from the CRS. Nothing bound a
user to a channel.
**Decision.**
- *Entitlement.* A user's channels at a hotel are the union, over the permission profiles
  granted to them there, of the profile's channel list (`TEX Permission Profile.sales_channels`,
  child `TEX Profile Channel`); a profile without a list sells on the call centre
  (`STAFF_DEFAULT_CHANNELS`). The capability `price.any_channel` admits every channel. A
  profile that holds neither `price.view` nor `reservation.create` adds no channel. Where a user
  has no granted profile (legacy User Permission scope) the Frappe role defaults decide, as for
  capabilities. Platform administrators sell on every channel. The pure rule is
  `capabilities.profile_channels`; `scope.sales_channels(property)`, `may_sell_on` and
  `require_channel` apply it.
- *Per-grant vs per-profile.* The list lives on the profile, like capabilities: a grant stays
  "user × scope × profile", and a desk that sells on other channels (a B2B desk) is a profile.
  A per-grant list was rejected: it would split what a profile allows across grants and make
  the anti-escalation check two-dimensional.
- *Enforcement: the channel comes from what is sold, never from who asks.* `crs.search` /
  `ui_crs.search`: hotels where the requested channel is not the user's are left out, and a
  channel the user may sell at none of the chosen hotels is refused (PermissionError).
  `crs.quote`: the signed offer's channel. `crs.book`, `ui_crs.book`, `ui_crs.quote_summary`:
  each quote's own `sales_channel` (a Booking Engine quote is not the agent's to book).
  `crs.payment_methods`: the channel asked about. `booking.create_booking`: for staff outside
  a booking site (defence in depth; a booking site sells on its own web channel, also for a
  signed-in staff member browsing it: see the review follow-up).
- *Modifications keep the reservation's channel.* A change is priced on the channel the stay
  was sold on (its snapshot request), whoever makes it: a call-centre agent changing a web
  booking changes it at web prices, as the guest could through self-service. The channel is
  never switched by a modification, for anyone (the channel is not an editable field): selling the stay on another
  channel is a cancellation and a new booking by someone entitled to that channel. Simulation
  and extras added after booking also use the reservation's channel.
- *Anti-escalation.* Granting a profile requires, at every hotel of the grant, the profile's
  capabilities (as before) and its channels.
- *Not selling, so not bound.* The contract editor's test price (`contracts.preview_price`,
  `price.view_cost`) prices any channel for revenue work; it returns no offer key, so nothing it
  prices can be quoted or booked. The public Booking Engine sells on its site's channel.
- *Defaults and upgrade (p29).* `price.any_channel` is in the Hotel/Group/Enterprise Admin
  (every capability) and Revenue Manager defaults; Reservations Agent, Finance, Viewer, Front
  Desk, Call Center Agent and Kamra Agent sell on the call centre. p29 adds `price.any_channel`
  to the existing seeded profiles whose defaults carry it and to custom profiles holding
  `contract.publish` (they already set every channel's prices); every other profile keeps its
  capabilities and sells on the call centre. Nothing widens: before G-41 every price viewer
  priced on every channel.
- *UI.* `session.bootstrap` returns each hotel's `sales_channels`; the CRS / Call Center
  channel picker lists only the channels allowed at the chosen hotels and starts on the call
  centre when it is allowed. Settings → Permission profiles shows and edits each profile's
  channels (`price.any_channel` is marked sensitive); the grant form says where a profile sells.
- *Inventory stays per contract.* Allotments are not given a channel dimension now. Channel-bound
  selling does not need one for correctness: allotments are consumed per contract, a contract
  sells only on its own channels (`CHANNEL_NOT_ALLOWED`), and restrictions already have a
  channel scope. "Inventory rules differ by channel by configuration" (R-25) is expressed today
  with a contract per channel and its own (guaranteed) allotment, or with channel-scoped stop
  sells. A per-channel split of one multi-channel contract's allotment needs sold counts per
  channel in `availability/repository.py`; it stays a remaining item of G-41.
**Consequences.**
- A profile created in Desk without a channel list sells on the call centre; an administrator
  adds channels (or `price.any_channel`) for desks that sell elsewhere.
- A group search on a channel silently leaves out the hotels where the user may not sell it;
  the picker only offers channels allowed at one of the chosen hotels.
- Tests: `test_channel_binding` (16), unit `test_channel_entitlement` (6), e2e `crs-actions`.

**Review follow-up (adversarial review of G-41; G-94).**
- *A booking site sells on a web channel only.* A booking site is the public Booking Engine:
  anyone may book there, so there is no "B2B portal" or "OTA site" product. `TEXBookingSite.
  validate` accepts only DIRECT_WEB or META (blank = DIRECT_WEB) whoever edits the site, so a
  desk with `booking_site.edit` can no longer open a site on B2B/OTA/API prices. A site stored
  with another channel before (possible until now) sells nothing: `public._channel` refuses its
  search, quote and basket (PermissionError), so its prices never reach the public; p31 reports
  and audits such sites (`booking_site.non_web_channel`) and leaves them to the owner (a web
  channel or disabling it) rather than putting them on sale at web prices. B2B, OTA and API
  prices are sold by entitled staff in the CRS and by channel connections.
- *Whoever books on a site books its web channel.* `create_booking` with a booking site accepts
  only a web channel for everyone (the guest rule now also applies to staff); a signed-in staff
  member may book there, at the price any guest gets, because refusing them would only make them
  sign out. Such a booking is reportable: `created_via` "Desk", the staff member as owner, and
  an audit event `booking.staff_on_site` (actor, hotel, site, channel, total). Staff outside a
  site need booking entitlement for the quote's channel, as before.
- *A profile's channels serve only what the profile allows.* Channels are no longer pooled
  across a user's profiles: pricing channels come from the profiles that hold `price.view`,
  booking channels from those that hold `reservation.create` (`profile_channels(..., for_cap)`;
  `scope.pricing_channels` / `booking_channels`, `may_price_on` / `may_book_on`,
  `require_channel(..., to="price"|"book")`). Search and payment methods use the pricing set;
  quote, quote summary, book and `create_booking` the booking set. A price-only profile listing
  OTA next to a call-centre profile lets its holder see OTA prices, not sell them. The session
  returns both sets (`sales_channels` = pricing, `booking_channels`) and the picker offers the
  channels that are in both. Granting a profile needs both of its sets.
- *A change to another product needs the reservation's channel.* Dates, occupancy, extras,
  promotion codes and dropping add-ons are servicing: `reservation.modify` suffices and the
  change is priced on the reservation's channel. A change of room type, rate plan, board or
  market (`PRODUCT_FIELDS`, compared with the sold request) sells another product at that
  channel's prices, so staff need booking entitlement for the reservation's channel at its
  hotel, on propose and again on apply (a proposal token carries the change, not the right to
  make it): a call-centre agent cannot turn a B2B booking into another stay at the B2B rate, nor
  move a web guest to another room (a web-entitled user or an administrator can). Guests change
  only dates and occupancy; staff approving a guest's request are not bound. The explicit
  "channel" refusal of the first version was redundant (the channel was never in `EDITABLE`)
  and is removed; the test now pins `EDITABLE`.
- *Payment methods for setup are not bound.* `payments.methods` (`payment.view`, the payment
  setup screen and the link dialog) lists which payment methods apply for a hotel, market,
  currency and channel: configuration, no price, no offer, nothing bookable. `crs.payment_methods`,
  used while selling, checks the pricing channel.
- *G-94: grants are the only authority for the rows mirrored from them.* `scope._scope` never
  reads `tex_managed` User Permission rows: live grants decide (an ended grant whose mirrored
  row had not been re-synced left the hotel in scope without a profile, so the user's Frappe
  role defaults applied there: a Hotel Admin kept every capability). Rows an administrator made
  by hand stay the legacy scope. Legacy (non-strict) tenancy opens every hotel only to users TEX
  never granted anything. `grants.remove_expired_grants` runs just after the site's midnight
  (`scheduler.SITE_MIDNIGHT`) and in p31: it re-syncs the mirrored rows of users with ended grants
  and audits each ended grant once (`grant.expired`).
- *Legacy hotel-bound DocTypes follow the TEX scope.* 53 legacy Kamra DocTypes bound to a hotel by
  a `property` link (POS, cashier, city ledger, banquet, housekeeping, laundry, …) were isolated
  in Desk/REST only by Frappe's User Permission filter, which a user with no row at all escapes
  (Frappe then does not restrict): removing an ended grant's rows would have opened every hotel's
  records to that user's roles. They are now under the TEX permission hooks
  (`perm.LEGACY_PROPERTY_DOCTYPES`, hooks `_TEX_SCOPED`): their lists and documents follow the
  TEX scope like TEX's own DocTypes (a blank `property` stays readable, as for TEX policies).
- Tests: `test_channel_binding` (26: + web-only sites, staff on a site, p31, per-capability
  channels, product changes), `test_grant_expiry` (9), unit `test_channel_entitlement` (7).

## ADR-051 Every FX rate a price used is recorded with it; ORIGINAL_* reprices reuse the record; child ages are judged in months (bands and dates of birth)
**Context.** Two pricing gaps.
- G-56 (R-15): a quote kept only the contract → sell currency rate (`fx`). Extras in another
  currency (`extra_fx`), fixed promotions and their minimum-basket thresholds (`promo_fx`),
  coupons and fixed levies (`tax_fx`) were converted with rates nobody recorded, so a sold
  price could not be re-explained without reading the FX tables, and the ORIGINAL_* bases
  re-read those tables as of the sale time. The tables can say something else about the past
  than what the sale saw: a provider rate imported after the sale but stamped with an earlier
  publication time (`fetched_at`) wins the as-of lookup.
- G-52 (R-08): bands are entered in years and priced in whole months. `validate_bands` checked
  overlaps only, so "INF 0–2.95, CHA 3–6.99" published, and a child of 2y11m (35 months) matched
  no band: unsellable. Neither the CRS nor the booking engine took a date of birth.

**Decision.**
- *The record.* The engine logs every conversion in a pure `fx.FxLog`: each rate once, in the
  order first used, with what it converted (`accommodation`, `cost`, `extra:<code>`,
  `promotion:<id>`, `promotion:<id>:min_basket`, `tax:<code>`). The quote carries it as
  `fx_rates` (internal: stripped with `fx` for viewers without `price.view_cost` and for
  guests): per rate the pair, the exact `sell_rate` (6 dp, as converted), the mode, provider,
  provider rate and its row id, rate date, adjustment, policy and the sale time it was resolved
  for. Each conversion is also an explanation step (`fx` / `FX`, one per use, the policy as the
  rule): "extra:SPA: 1 USD = 40.000000 TRY (manual rate, policy FXP-0002)". Same-currency
  "conversions" are not recorded. Add-on quotes record theirs the same way.
- *The snapshot.* A reservation's price-locked snapshot is the accepted quote, so it and the
  Original revision hold the record. A modification's snapshot carries the original sale's
  record on as `original_fx_rates` (like `original_priced_at`); for a modification made before
  this ADR it is read from the Original revision. A snapshot priced before this ADR has only
  `fx`: its room rate is the record (`fx.recorded`).
- *Repricing.* `build_context(fx_pins=…)` uses a pinned snapshot for its pair instead of the
  tables. ORIGINAL_VERSION and ORIGINAL_SALE_DATE pin the original sale's record
  (`modification.fx_pins`, origin `reservation:<name>`, shown in the explanation as "recorded
  at sale"); a pair the sale did not convert (another contract currency, a new extra's
  currency) is resolved as of the original sale time. HISTORICAL_SALE_DATE ("as if sold then")
  and CURRENT resolve every rate from the tables as of their own sale time. The simulator is a
  HISTORICAL-style what-if and pins nothing. Extras added after booking are a new sale at the
  rates of their day (ADR-034) and record them in their own block.
- *Bands in months.* `ages.band_problems` judges a band set on the month scale pricing uses:
  every overlap and every gap between two bands is an ERROR naming the months ("INF and CHA
  leave a gap at 35 months (2y11m)… end INF where CHA starts"); publish (`validate_terms`, on the
  cascaded set, so a policy's set is checked where it applies) and the pricing-policy
  controller (draft save) refuse them. A set starting above 0 months is a minimum child age
  (children that young cannot be booked): a WARNING (`AGE_BANDS_MIN_AGE`), not an error. The
  year → month conversion (`years_to_months`) and frozen payloads are unchanged.
- *Which set applies* is ADR-043's: the version's bands, else those of the most specific live
  pricing policy that defines bands (hotel + market > market > hotel > global), frozen at publish.
- *Date of birth.* A child is an age in whole years (0–17) or `{dob}`. The server checks a date
  of birth (`quoting.Party.parse(arrival=…)`, `ages.check_child_dob`): not in the future, under
  18 on arrival (`ages.MAX_CHILD_AGE` = 17, the ceiling a declared age has; there is no per-hotel
  setting — above a contract's top band a child is priced as that contract says). It fills the
  child's age on arrival for display; pricing counts completed months from the date of birth at
  the contract's reference date (arrival or booking date). Modifications check a new party the
  same way against the new arrival. The CRS / Call Center and the modification drawer send
  `{dob}`; the booking engine keeps a date of birth out of the URL (the `rooms` parameter says
  `b`; the date stays in the tab's session storage and in the search key), so shared links and
  analytics never carry it.

**Consequences.**
- A confirmed booking is re-explained from its snapshot alone, and an ORIGINAL_* reprice
  reproduces the sold conversions even after the FX tables changed (`test_fx_snapshot`: a EUR
  contract sold in TRY with EUR and USD extras and a fixed EUR promotion; a late TCMB import and
  a revised manual rate change CURRENT and HISTORICAL_SALE_DATE, not the snapshot or the
  ORIGINAL_* reprices).
- Versions published with a band gap still sell as frozen; they cannot be republished until the
  gap is closed (`devtools/precedence_report` lists a refused rebuild under `cannot_rebuild`).
- The FX rate table's `rate` is still a Float column (G-72); the record keeps the 6-dp Decimal
  rate the price used, so a reprice never re-reads it.
- A shared booking-engine link with a child given by date of birth asks for that child's age
  again in another tab or device.

**Review follow-up (2026-09-24).** An independent review found no Critical or High issue and
the FX pinning sound; it found two Medium privacy leaks and Low items, fixed as follows.
- *A date of birth stays where the price needs it* (the quote's request, the reservation's
  `tex_child_ages` and snapshot, its revisions) *and nowhere else.* The funnel `search` event
  stores each party as adults and ages on arrival (`quoting.Party.summary`); every funnel payload
  loses `dob` / `date_of_birth` keys at any depth, a browser-sent one included
  (`public._no_dob`). A guest change waiting for staff notes children as ages. No age message
  names a date of birth, and an invalid one is not echoed.
- *Searches are POST only* (`crs.search`, `ui_crs.search`, `public.search`): a party may carry
  a date of birth, which must never sit in a URL or an access log. The CRS posts its search;
  the booking engine already did. Modifications and the contract preview were POST already;
  the simulator carries no party.
- *A baby born after the pricing reference date* (the sale date of a BOOKING_DATE contract
  repriced later on ORIGINAL_* or HISTORICAL terms, the arrival of a stay already in house) is
  0 months old there (`ages.child_months`, `check_child_dob`), not an error and not "18 or
  older". `quoting.price_request` turns any `PricingError` into an unsellable quote
  (`PRICING_ERROR`) instead of an HTTP 500 whose Error Log would hold the request.
- *Pre-G-56 snapshots pin their line rates too.* Besides the room rate (`fx`), such a snapshot
  recorded each converted extra's rate (`extras[].fx_rate`, the currency is the extra
  revision's) and a fixed levy's (`taxes[].fx_rate`, the tax policy's currency):
  `fx.recorded(…, extra_currency, tax_currency)` makes them record entries of mode `RECORDED`
  (no policy; "rate recorded on the sold line"), so ORIGINAL_* reprices of old bookings no
  longer re-read the tables for extras and levies. A fixed promotion in a third currency
  recorded no rate before G-56: it is still resolved as of the sale.
- *Not changed:* the record's provider row, adjustment (the FX margin) and policy are readable
  through Desk/REST wherever the snapshot is (with cost and margin, which were already there):
  a field-level permission cannot express a per-hotel capability (`price.view_cost`), so this
  is gap G-95 (Low). Rates below 1 keep 6 decimals, 4–5 significant digits for TRY → EUR: a
  significant-digit (or inverse-rate) precision belongs to G-72.
- Tests: integration `TestDateOfBirthPrivacy` (2), `TestDateOfBirthAfterTheReference` (3),
  `test_a_snapshot_sold_before_g56_pins_its_line_rates`; unit
  `TestDateOfBirthAfterTheReference` (3), `TestLegacySnapshotLinePins` (3).
