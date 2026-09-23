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
