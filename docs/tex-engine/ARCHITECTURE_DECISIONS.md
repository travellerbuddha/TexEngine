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
(ADR-057 adds room-less hotel/market-level cells, Booking Engine / Call Center channel scopes
ranked between a sales channel and all channels, the booking window, and the rules a change is
checked by.)

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
on a multi-room booking whose total would qualify (never the reverse; G-84 — fixed by ADR-057:
a minimum basket is now the whole booking's). Snapshots
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
another booking's insert under rare index layouts; the retry absorbs that. Only the endpoints
wrapped in `retry_on_deadlock` are run again. MariaDB snapshot isolation
(`innodb_snapshot_isolation`, ON by default from 11.6.2) is kept OFF (corrected by ADR-063).
A new write endpoint that locks inventory must use the decorator.

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

**G-51 review follow-up (ADR-054).** A request waiting for the hotel (Requested) still has no
expiry, and staff still approve it at the price the guest was shown, re-derived as of its
pricing time. But the approval is refused while the contract that priced it does not sell
(suspended or archived): staff reject the request, or change the reservation themselves on a
basis they choose. The request card shows that contract and its status now, and disables
Approve while it does not sell. The paid path keeps its bounded window (the proposal's 30
minutes plus 60).

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

**Note (audit Part 2G-1, 2026-09-27): session tokens, manage links and trackers.**
- *O-28.* A signed-in user's booking-engine page (`/book/…` and a hotel's pinned host) carries the
  session's CSRF token (`booking_host.with_session_token`); the engine sends it with every public
  call (header; `csrf_token` form field for `sendBeacon`). A guest's page has none.
- *Tracker rule.* A page that carries a session token loads no third-party tracker and shows no
  consent banner: the hotel's tag container is arbitrary script, and on the platform's origin
  (shared with `/kamra` and `/app`) it would run with the staff session and could call any
  `/api/method` as that user; a staff booking is also no web conversion. ADR-050's staff flag
  (`created_via` Desk, `booking.staff_on_site`) is unchanged.
- *O-27.* The confirmation page links to `/<site>/manage` without the token; the click stores this
  booking's token as the tab's site token, which the manage page reads (the fragment first, as for
  the e-mailed magic link). No address, href or tracker request carries a manage token.
- *Operations (remaining risk).* A tracker already loaded in another tab of the platform's origin
  (a guest page before sign-in) keeps running and could act with a session opened later in that
  browser. A site with trackers should be served on its own verified host (ADR-035), never on the
  platform's origin; GO_LIVE_READINESS should say so.

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
*Amended by ADR-052 (G-92): a Desk or REST insert at a TEX hotel is refused, and so is a change of
a TEX hotel stay's nights, room type or hotel outside TEX. The writes outside TEX that still take
the inventory lock are migration imports and status moves into a live status.*

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
- *Note (audit Part 2I, 2026-09-27; NEW-8).* The Agent Action Log is no longer among them: a row
  without a hotel was read by every tenant's roles in Desk / REST and returned by `activity_detail`.
  It is in `perm.STRICT_DOCTYPES` (a blank hotel = platform only; `hooks._TEX_SCOPED` unchanged);
  `activity_detail` refuses such a row and `activity_feed` leaves it out for non-platform users;
  `front_desk_snapshot` sums minutes saved over its own hotels. New rows take the hotel of the
  record they are about (`savings.hotel_of`: a Property; a record with `property`; a guest's or a
  user's one hotel); p65 does the same for the rows written before, the rest stay platform level.
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

## ADR-052 A TEX hotel's reservation is created and changed only by TEX; a migration import keeps the amount it carries
**Context.** G-92 (R-01, R-02, R-05), found by the G-49 review.
- Front Desk, Hotel Admin and Kamra Agent have create and write permission on Reservation (the
  legacy PMS needs it). ADR-028 refused the legacy selling endpoints for a TEX hotel, but not the
  generic insert: the Desk form, REST (`POST /api/resource/Reservation`, `frappe.client.insert`)
  and Frappe's data import still wrote a TEX hotel's reservation. Since ADR-048 it took TEX's
  inventory lock, but its price came from the legacy auto-price (`Reservation.apply_pricing`,
  float `Room Type.base_price`), not from TEX contracts, markups, taxes or payments, and it had
  no TEX price lock.
- An existing stay that TEX did not price had the same hole. A stay the legacy engine sold before
  its hotel joined TEX is unlocked (patch p04 locked only the stays that existed when TEX was
  installed). A Desk, REST or legacy PMS change of its dates or room type (`amend_stay`,
  `move_reservation`) was re-priced by the legacy engine.
- Two options: refuse such writes (keeping migration imports, ADR-028), or price them through
  TEX. Pricing needs a market, a channel, a contract, a board, a rate plan and a party with child
  ages. The Desk form holds none of them in TEX's terms, and TEX never picks a market or contract
  silently. TEX already has a staff booking path (CRS / Call Center) with capabilities, channel
  entitlement (ADR-050), payments and audit. A second, weaker path would duplicate it.

**Decision.** Refuse; keep the migration importers, with the amount they carry.
- *New reservations* (`Reservation.before_insert` → `kamra.tex.legacy.guard_new_reservation`).
  At a TEX hotel (`is_tex_hotel`) only these may insert a reservation:
  - the TEX booking service (`flags.tex_sale`);
  - a channel's sale (`flags.tex_channel_accept`, ADR-039);
  - a migration import (`legacy.flag_import`).

  Every other insert is refused, whatever its status, with a message that points to TEX
  (Reservations → CRS or Call Center). This covers the Desk form (and its Duplicate), REST,
  Frappe's Data Import and legacy code.
  - *Every status is refused*, not only live ones. A quote or waitlist entry would become a sale
    later. A history record counts in reports, guest statistics, segments and loyalty. History
    comes in through the importers.
  - *When the check runs.* It runs before the inventory lock (ADR-048) and before naming. It also
    runs for `ignore_validate` inserts.
  - *The flags cannot be forged.* They live only in the process: Frappe drops `flags` from a
    payload, and pricing source or lock fields in a payload change nothing. The controller pops
    each flag on the insert it was set for (the G-49 pattern).
  - *Roles are unchanged.* The roles keep their Frappe permissions, which hotels outside TEX
    need. The refusal is the hotel's rule, so platform administrators are refused too.
- *Migration imports.* `kamra.api.import_bookings` and `kamra.migrate.run_import` (live and
  history rows) call `flag_import(doc, final status)`. At a TEX hotel the row:
  - needs `price.override` at the hotel, because it sets a price;
  - is never auto-priced (`auto_price` 0);
  - keeps the amount the file carries, as a Decimal quantized to the hotel's currency
    (`amount_after_tax`, `tex_total_amount`, `tex_currency`). `migrate` now reads the amount as a
    Decimal (it was a float). A live row needs a positive amount. A history row (Checked Out,
    Cancelled, No Show) may come without one;
  - is recorded with pricing source `Imported`. This is a new Select option, synced from the
    DocType JSON. No patch is needed: existing rows keep their source;
  - is price-locked (`tex_price_locked`, `tex_locked_at`);
  - is audited (`reservation.import`: final status, amount, currency, room type, dates).

  At a hotel outside TEX both importers behave as before (a row without an amount is
  auto-priced).
- *The legacy auto-price never runs at a TEX hotel.* `apply_pricing` returns for a stay that is
  at a TEX hotel, or was until this save.
- *Existing stays* (`kamra.tex.hooks.guard_commercial_change`). A stay that is at a TEX hotel, or
  was until this save, changes these fields only through the TEX services
  (`flags.tex_modification`: modification, cancellation, confirmation, add-ons, channel updates):
  - its dates, room type and party (adults, children, child ages);
  - its board or meal plan, rate plan, market and voucher;
  - its amounts;
  - its commercial record (`tex_*`, lock included);
  - its hotel. A stay moved into a TEX hotel would be a sale outside TEX; one moved out would be
    re-priced by the legacy engine.

  The guard covers every save: the Desk form, REST `PUT`, `frappe.client.set_value`,
  `amend_stay`, a `move_reservation` to another room type, and group or other legacy actions.
  - *A TEX-priced stay* keeps the ADR-010 lock and its message ("use Modify reservation").
  - *A stay TEX did not price* (sold by the legacy engine before the hotel joined TEX, or
    imported) cannot be re-priced by TEX: the modification service needs a TEX snapshot. The
    guard refuses it with "keep the stay as it is, or cancel it and book the new stay in TEX".
  - `Reservation.validate` calls the guard first, so nothing is locked or priced for a refused
    save. The `validate` doc event checks the values the save will write again.
  - *Other edits still work:* notes, the booker, a room of the same type, check-in and
    check-out. So do status moves: a waitlisted legacy stay is confirmed under TEX inventory
    (ADR-048), and a stay TEX did not price is cancelled with the legacy fee (ADR-010).
- *Hotels outside TEX are unchanged:* the legacy auto-price, the legacy import, and the ADR-010
  lock of stays locked by p04.

**Consequences.**
- Staff book a TEX hotel's stays in TEX. The Desk form still shows and annotates them.
- A stay TEX did not price is not extended, shortened or moved to another room type outside TEX.
  Staff cancel it (legacy cancellation) and book the new stay in TEX. A departure through the
  legacy check-out does not change the dates and still works.
- *ADR-048.* Outside TEX, only two kinds of write still take TEX's inventory lock at a TEX hotel:
  a migration import, and a status move into a live status. A Desk or REST insert, or a change of
  nights, room type or hotel, is refused before the inventory guard. The guard, and its rule that
  a stay keeps the nights it holds, stay as defense in depth. The G-49 tests were adapted: their
  outside-TEX writer is an import, and "leaving early over closed nights" (M1) is now a staff
  modification.
- Imported stays are price-locked, so the legacy scheduled jobs leave them to TEX
  (`is_tex_reservation`, ADR-028: no legacy night audit), like p04's legacy-locked stays.
- Frappe's generic Data Import cannot create a reservation at a TEX hotel. The migration
  importers can. A TEX-native importer for open bookings (priced by contract) is still a
  data-migration gap.
- Writes that bypass validation (`db_set`, SQL, `ignore_validate` saves of an existing stay)
  bypass the change guard, as they bypass every rule. A new reservation is guarded in
  `before_insert`, which such inserts still run.
- Tests: `test_legacy_pricing` (15; the 10 that the fix covers fail first):
  - Desk inserts by Front Desk, Hotel Admin and Kamra Agent users, and by a platform
    administrator, refused;
  - every status refused;
  - a forged REST payload refused;
  - `apply_pricing` never prices a TEX hotel;
  - imports (`import_bookings`, and `run_import` with history rows): recorded as Imported, at a
    Decimal amount, audited; a live row without an amount refused; `price.override` required;
  - changes of TEX-priced and legacy stays through the Desk form, REST `PUT`, `set_value`,
    `amend_stay` and `move_reservation` refused; a move into or out of a TEX hotel refused;
  - other edits still work;
  - the TEX CRS booking unaffected;
  - a hotel outside TEX keeps the legacy auto-price and import.

  G-49 tests were adapted in `test_inventory`, `test_concurrency` and the G-04 night-audit
  fixture.

**Review follow-up (2026-09-24; G-96).** An independent review found no way to forge a flag or
get around the guard. It found 2 High, 3 Medium and 3 Low issues around it, fixed as follows.
- *H1 Amounts are read strictly, shown before import, and correctable.* The importers stripped
  everything but digits and dots, so "150,00" became 15000.00, "1.250,50" became 1.25, "TL 1.500"
  became 1.50 and "-120" became 120. At a TEX hotel such a row is price-locked, so nobody could
  correct it.
  - One pure reader (`kamra.tex.importing`) serves `import_bookings`, `run_import` and
    `preview_import`. The decimal mark is the last `,` or `.` when one or two digits follow it (or
    four or more). A separator that appears more than once groups thousands, and so do spaces,
    apostrophes and the Indian 2-2-3 grouping. A single separator followed by exactly three digits
    ("1.500", "1,500") is ambiguous and is refused, unless the import says its decimal mark
    (`decimal`: "." or ","). A cell that contradicts that setting is refused, never reinterpreted.
  - Currency symbols and codes are stripped and reported ("$", "¥" and "kr" report every currency
    they may be). Negatives, several currencies and anything else are refused, with the reason on
    the row. An amount with more decimals than its currency has is refused, never rounded.
  - The preview lists each row's parsed amount (a string) and currency before anything is
    written; the Setup import screen shows them. "10,500.50" reads the same in both importers
    (L2: `import_bookings` used to refuse it).
  - `crs.correct_imported_amount` corrects an Imported stay's amount and currency. It needs
    `price.override` at the hotel and a reason, and writes a `Price Override` revision (basis
    MANUAL) and a `reservation.import_correct` audit event. It is refused once the folio has billed
    the stay's nights, and for a stay TEX sold (that one changes through Modify reservation). The
    reservation page offers it for Imported stays.
- *H2 / G-96 The legacy folio never bills a price-locked stay at the legacy Room Type rate.* The
  gap predates G-92. The legacy check-out, a Desk status change to Checked Out, and
  `force_advance_bill` all posted every night at `Room Type` rates through `post_room_night`, the
  same for a TEX-sold or an imported stay. `kamra.tex.legacy.locked_bill` now decides for a stay
  that `is_tex_reservation`:
  - *Sold through TEX (a TEX booking, a channel sale included): the folio posts none of its
    nights.* No room, board, discount or cleaning lines, and advance billing is refused. We chose
    "nothing" over posting the locked amount per night: TEX represents such a stay's money on its
    TEX booking. The booking holds the total, the payments (card, link, pay at hotel recorded in
    TEX) and the balance (`booking_summary`); cancellation penalties come from the frozen
    rate-plan policy. The night audit already leaves these stays alone (ADR-028). Folio lines as
    well would bill the guest twice and disagree with TEX's payments. The folio stays open for
    incidentals (POS, minibar).
  - *Price-locked without a TEX booking (Imported, or a legacy stay p04 locked at the upgrade):
    the locked amount is split evenly over its nights.* The split is Decimal, with the remainder on
    the last night (`money.split_evenly`). TEX holds no booking or payments for such a stay, so
    the folio is its only bill. A stay that recorded its tax split posts the pre-tax share with
    its own effective rate. An imported amount carries no split, so it is posted tax included
    (rate 0). No board, discount or cleaning line is added: they are inside the locked price.
  - *Locked in another currency than the hotel's:* the folio is in the hotel's currency and TEX
    never converts a locked price silently. One zero line says so ("not billed here: locked at
    250.00 USD").
- *M1 An import row is all or nothing.* Each row of `import_bookings` and `run_import` runs in its
  own savepoint (`legacy.import_savepoint`). The row's guest, reservation, audit event and
  inventory rows roll back together, and a deadlock still stops the import. History rows
  (Checked Out, Cancelled, No Show) are records: inserted without live validation, their status
  stamped, holding no room. Checked In rows are checked as live stays (TEX inventory; the arrival
  may be past, `allow_past_check_in`) and stamped Checked In without check-in side effects. Before,
  an `import_bookings` Cancelled or Checked In row failed after its insert and left a €0 Confirmed
  stay holding TEX inventory. The audit event records the final status.
- *M2 The fee of a stay TEX did not price comes from its locked amount.* Before, the legacy
  "Full Stay" fee used the empty `amount_before_tax`, "First Night" used the legacy rate, and the
  TEX cancel found no snapshot and charged nothing.
  - The legacy `policy_fee` of a price-locked stay uses `locked_fee`: the whole locked price, or
    the first night's share, posted like its nights.
  - `booking.cancellation_penalty` of a stay without a TEX snapshot applies the hotel's own
    policy (free days, fee basis) to the locked amount after tax (`hotel_policy_penalty`).
  - The legacy cancellation refuses a stay billed in TEX (TEX booking, or another currency):
    "Cancel it in TEX", where its policy applies.
- *M3 A hotel goes live in TEX when an administrator says so.* `is_tex_hotel` was true as soon as
  a hotel had a group, an enterprise or any contract, even a draft, so the Desk stopped at once,
  before the CRS could sell.
  - New `Property.tex_live_from` (read-only), set by `admin.set_hotel_live` (`settings.admin`,
    reason, audited `hotel.go_live` / `hotel.go_live_undo`; reversible for a rollback). The
    Property controller refuses the field from the Desk form, REST or data import (in-process
    flag, popped). `legacy.tex_live` = in TEX and live; `tex_mode` = live / onboarding / None.
  - *What follows go-live:* the Desk / REST insert refusal, the change guard for stays TEX did not
    price, and the legacy auto-price skip. While onboarding, the Desk sells the hotel at the
    legacy price. TEX inventory still applies, and TEX may already sell with a live contract.
  - *What keeps `is_tex_hotel` from the first moment* (nothing that protects TEX waits for
    go-live): the ADR-028 refusal of the legacy online engine, staff dialog and channel manager;
    TEX inventory as the only capacity rule (ADR-048); imports recorded as Imported with their
    currency; the ADR-010 lock of what TEX sold; ARI; tax-policy seeding. The legacy night audit
    and billing follow the stay (`is_tex_reservation`), not the hotel.
  - Patch p36 sets every hotel already in TEX live (audited, reason "upgrade"), so nothing changes
    for them.
  - The TEX shell shows a "TEX live" / "Onboarding" badge, and a banner with "Go live" for
    onboarding hotels. The legacy app shell and the Desk Reservation form (`session.hotel_mode`,
    scoped) say when a hotel is sold through TEX or joining it.
  - An in-house stay TEX did not price is told to "book the extra nights as a new TEX
    reservation".
  - *Not built: a "take over into TEX" action* that would give such a stay a TEX snapshot so the
    modification service can serve it. A snapshot needs a market, channel, contract version, board
    and rate plan chosen for a stay TEX never priced, and every later change would re-price
    against that contract, not against the amount it was sold at. That is a commercial decision
    for the owner (GO_LIVE_READINESS owner input 10), not a mechanical conversion.
- *L1* `flags.tex_modification` covers one save: the `validate` doc event uses it up. The
  request-wide `frappe.flags.tex_modification` bypass (nothing set it) is gone.
- *L3 An import at a TEX hotel names its currency:* a Currency column, else the currency chosen
  for the import. An unknown currency, or an amount naming another one, is refused.
  `Property.currency` (default INR) is no longer assumed. A hotel outside TEX keeps its amounts
  in the hotel's currency, and a row naming another currency is refused there too.
- *Consequences.*
  - Rolling a row back to its savepoint undoes its database writes, not callbacks already
    queued for after the commit (realtime refresh, the WhatsApp confirmation). Such a callback
    finds no reservation and does nothing.
  - The folio invoice of an imported stay shows its amount tax included, because the file carried
    no tax split.
  - Only one field was added (`Property.tex_live_from`, p36); no money field changed type.
  - Tests: `test_legacy_pricing_review` (23; 22 fail first on `45993df`: 16 errors, 6 failures)
    and unit `test_import_amounts` (14, new module). The existing import tests now pass a
    currency, and the fixture hotel is live.

## ADR-053 The audit trail records what changed (compact diffs), for which hotels, and how it arrived
**Context.** G-74 (R-54): the audit trail missed changes and context. Draft contract edits
(`save_version`) were not audited and a publish recorded only its payload hash; ARI bulk edits
recorded only the values set; payment method rules were never audited, provider accounts only
through the TEX API and without old values, and Desk / REST edits of payment rules not at all;
a hotel-group or enterprise grant event had no hotel, so only platform administrators saw who
was given access to a hotel; every payment outcome was recorded as coming from a "Webhook".

**Decision.**
- *Diff format.* Values are canonical before they are compared or stored
  (`kamra.tex.security.changes.canon`, pure; `audit.field_value` by DocType field type):
  decimals as plain strings (never float, "100" not "100.0"), Int as int, Check as bool,
  dates ISO, blank = null, long text clipped at 300 characters. Single values keep the existing
  shape: `old_value = {field: old}`, `new_value = {field: new}`, only the fields that changed.
  Sets of rows go under `new_value.collections.<name>` as a *collection diff*: rows are known by
  a natural key (`"<room type> · LOW"`, trailing blank key parts dropped, a duplicate key as
  `"… #2"`), never by a row id (a draft's rows get new ids on every save):
  `{count: [before, after], totals: {added, removed, changed}, added: [key…], removed: [key…],
  changed: {key: {field: [old, new]}}, changed_keys: [key…], fields: {field: [old, new]}}`.
  Everything is bounded: 50 keys per list, 25 rows (50 cells for the grid) recorded field by
  field, the other changed rows by key only, the totals always complete. The keys per table are
  `kamra.tex.commercial.diffs.DRAFT_TABLES` / `PAYLOAD_TABLES`.
- *Draft edits* (`contract.version.save`) are audited by the TEX Contract Version controller
  (`on_update` of a draft that stays a draft), so every path is covered: the contract editor,
  a grid rate change (reason "ARI grid rate change"), Desk, REST. Settings and selling terms
  old → new, each table as a collection. A save that changes nothing writes nothing. The editor
  saves on demand (Save, Ctrl+S, only when dirty), never per keystroke, so no coalescing: one
  event per save that changed something.
- *Publish* (`contract.publish`) keeps the hash, effective time, warnings and selling terms and
  adds `previous` (`{version, payload_hash}` of the version selling at the effective time, else
  the latest version published before; null for a first publish) and `collections`: the frozen
  payloads compared section by section (contract and settings as `fields`; rooms, periods, room
  rates, occupancy rules, age bands, boards, rate plans, offers as collections; row ids
  ignored). A first publish lists what it froze.
- *ARI bulk edits* (`grid.bulk_update`) keep the summary they had and add `collections`
  `restrictions`, `inventory`, `rates`: cells keyed `"<room type or pool> · <date>"` (rates:
  `"<room type> · <from>/<to>"`, the draft's unit before and after), `unchanged` (cells already
  at the new value) and `old_values`: per field, how many cells had each old value (10 values,
  the rest as "…"), so the prior state is known beyond the 50 detailed cells. The limited-extras
  grid (`extra_inventory.update`) records its days the same way (`"<extra> · <date>"`).
- *Payment rules* (TEX Payment Policy, TEX Payment Provider Account, TEX Payment Method Rule)
  are audited by record hooks (`kamra.tex.security.record_audit`, `doc_events`): one
  `<payment_policy|payment_account|payment_rule>.<create|update|delete>` per change, whatever
  path saved it; the TEX API no longer writes its own event for them. Password fields are never
  read into the audit, not even masked (a mask gives the length away): secrets appear only as
  `<field>_set` (create / delete, and on a change old and new) and `<field>_changed: true`. A
  secret entered again unchanged is compared with the stored one (decrypted in memory, never
  kept) and is no change. `redact()` still masks secret-like keys as a second line.
- *Scope of group and enterprise events.* An audit event has a hotel (`property`) when it
  belongs to one hotel. An event of a hotel group or an enterprise names it (`hotel_group`,
  `enterprise` on TEX Audit Event) and the hotels it reached *when it happened*: one
  `TEX Audit Scope` row (event, hotel) per hotel, written with the event
  (`audit(..., hotels=…)`). Chosen over the group's current membership (a hotel that joins
  later would see events that never concerned it; one that left would lose events that did) and
  over one event per hotel (one action stays one event; an enterprise grant would multiply).
  The rows are a separate DocType, not a child table, so Desk / REST scope them per hotel: a
  hotel's staff read their own hotel's row and never another hotel's name. Visibility: a
  non-platform user sees an event when its hotel or one of its scope rows is theirs
  (`perm.query_conditions`, `has_permission`); an event with neither stays platform-level.
  Cost events (G-97, 2026-09-27; `reference_doctype` in `perm.COST_DOCTYPES`: a contract, its
  versions and rate tables, markup rules, pricing policies) are read in Desk / REST by platform
  administrators only. In the TEX audit log they are read with `price.view_cost`; contract events
  (`perm.CONTRACT_COST_DOCTYPES`), as in the record's own trail, also with `contract.edit` — the
  hotel view (`settings.admin`) leaves the others out in its query, the group / enterprise events
  that reached the hotel too (fix round 1 of Part 2I). The other events (grants, payments,
  bookings) keep the rule above. The
  audit viewer's hotel filter includes the events that reached the hotel and returns `hotels`
  (the reached hotels the viewer may see) and `other_hotels` (a count), like the users screen
  shows a grant's foreign hotels only as a count.
  - Grant events: a hotel grant belongs to its hotel; a group or enterprise grant to its group
    / enterprise and its hotels; a change reaches the hotels of the grant before and after (a
    grant moved from group A to B is seen at both); create, change, delete and expiry alike
    (`grants.grant_scope`). A platform grant stays platform-level.
  - Group-level policy records (a group booking site or promotion) are audited with their
    group and its hotels (`policies._audit_scope`); a global record stays platform-level.
  - Patch p33 gives existing group / enterprise grant events their group / enterprise and the
    hotels those have now (their membership at the time was not recorded); recorded old / new
    values are not changed.
- *Sources* (`audit.SOURCES`): Desk = a signed-in staff session (the TEX app), API = a
  token-authenticated call, Guest = an anonymous visitor, Gateway Return = the guest's browser
  coming back from a payment page, Webhook = a server-to-server notification (payment gateway,
  channel manager), Scheduler = a scheduled job, System = a queued background job, a migration
  or the console, Agent = the AI assistant. An entry point that knows how an action arrived sets
  it for everything audited inside (`audit_source()`, restoring the previous value); otherwise
  the request decides (`source_of_request`: a background job is Scheduler / System before the
  session user is looked at).
  - The gateway gets two callback addresses to the same endpoint, `via=return` (the browser:
    iyzico `callbackUrl`, Sipay `return_url`, virtual POS `okUrl` / `failUrl`) and `via=notify`
    (the virtual POS server `callbackUrl`, `Intent.notify_url`). `via` is signed with the
    transaction (`callback_signature(txn, via)`), so a return address never passes for a
    notification; the `via` parameter is not part of the provider's verified parameters. An
    address issued before G-74 (no `via`, the old signature) is still accepted: a GET is the
    guest's browser, a POST is taken as the gateway's notification.
  - Staff re-verification records the staff request (Desk / API), the sandbox payment page
    (`mock_pay`) a gateway return, TEX scheduled jobs Scheduler (`scheduler._run`). Payment
    links that expire are audited (`payment_link.expire`).

**Consequences.**
- Audit payloads stay small: a 1,000-row draft edit records its counts and at most a few
  hundred keys; no full payload is ever stored per save.
- A new hotel-group or enterprise action passes `hotels=` / `hotel_group=` / `enterprise=` to
  `audit()`; a new DocType whose every save path must be audited is added to
  `record_audit.TRACKED` (with its secret fields) instead of auditing in each endpoint.
- The audit trail screen renders collections row by row, the hotels reached (the viewer's,
  the others as a count) and the source labels; the raw JSON stays one click away.
- Residual: a hotel grant moved between two hotels names both hotels in its old / new values,
  which the staff of either hotel see (whoever moved it administers both).
- Tests: `test_audit_trail` (15: grant scope and visibility in the viewer, Desk / REST and
  `has_permission`, expiry; draft saves, bounded summaries, publish diff; grid restrictions,
  bounds, inventory and rates, limited extras; payment rules on API and Desk paths, no secret in any event,
  one event per change; payment sources for gateway return, notification, a forged channel,
  staff, sandbox page and scheduler), unit `test_audit_changes` (11).

## ADR-054 Modifications and the simulator are deterministic: a sale time belongs to the basis, the past is read as it was then, a proposal belongs to whoever made it
*Amended by the review follow-up (end of this ADR): a staff approval of a guest's request is
refused while the contract that priced it does not sell; a sale time with a UTC offset is read in
the site's time zone.*

**Context.** G-51 (R-21, R-22).
- *Sale times ignored.* `sale_at` was an editable field of a change and was dropped without a
  word. `basis_sale_at` was accepted with every basis and used only by HISTORICAL_SALE_DATE. The
  simulator accepted any `sale_at`: a future one priced "what it will cost", an empty one failed
  with an HTTP 500.
- *Untested money paths.* HISTORICAL_SALE_DATE and the manual override had no end-to-end test.
  `apply()` checked `price.override` for an override amount but not for the HISTORICAL basis,
  which only `propose()` checked: a user whose right was withdrawn between the two still applied
  a price no longer on sale.
- *The simulator read two things live.* Extras and taxes (G-20), markups, promotions and FX
  (revisions and rate tables as of the sale time) and the market, channels and sale window of the
  version live then (G-50) were already as of the sale time. The contract status was not:
  `candidate_contracts` kept only contracts Active now, so a contract archived since could not be
  simulated for a time it sold, and one suspended at that time was simulated as selling. Coupon
  usage was not either: a use given back later made a code apply that did not apply then, and a
  use made later made it fail. The same status problem hit the ORIGINAL_SALE_DATE basis: after a
  stop sale or an archive, the contract that sold the stay was no longer a candidate.
- *Proposal tokens were bearer tokens.* Any user with `reservation.modify` at the hotel could
  apply another user's proposal. Staff could apply a guest's proposal. A guest could submit a
  staff proposal on the manage page, where it was re-derived on its own basis. With
  HISTORICAL_SALE_DATE, that meant a price no longer on sale, paid online, with no
  `price.override` check on the guest's side.

**Decision.**
- *A sale time belongs to the basis.* A change carries none: `sale_at` is not in `EDITABLE`, and a
  change naming one is refused with the way to do it (choose the historical sale date basis).
  `basis_sale_at` is refused with any basis but HISTORICAL_SALE_DATE. The historical sale date
  and the simulator's sale time are checked on the server (`modification.past_sale_time`): given,
  a valid date and time, not in the future. "Modify the sale date" (R-21) is therefore a change
  priced on HISTORICAL_SALE_DATE. Its revision is of type *Sale Date* (or *Multiple* with other
  changes), and it records the basis and its sale time. The reservation's own `tex_sale_at` (when
  it was sold) never moves.
- *Who may price as of another time.* Pricing a change as if sold at another moment sets what the
  guest pays at a price that is not on sale today. That is an override, so it needs
  `price.override` at the hotel, on propose and again on apply: a token carries the change, not
  the right (as ADR-050 does for product changes). A manual amount also needs `price.override` on
  apply, and a reason. No new capability: the spec ties the historical basis to the override
  right, and a separate capability would be granted to the same revenue managers. The simulator
  writes nothing: it needs `price.view` and, because it shows the reservation's actual total and
  sale time, `reservation.view` (new). It does not need `price.override`.
- *A contract's status at a past moment* comes from the audit trail. `TEXContract.on_update`
  audits every status change as `contract.status` (old and new status), on every path (publish,
  the status actions, any save), in the same transaction, and has done so since the first
  release. Audit events are immutable: they cannot be edited or deleted. `versions.status_at`
  (pure) reads them:
  - the new status of the last change at or before the moment;
  - before every change, the old status of the first one (what it replaced);
  - with no change recorded, the current status.

  A status-history table would duplicate these rows and need a backfill from them, so none was
  added. `contracts.statuses_at` loads the changes of a hotel's contracts in one query.
- *Where the past status applies.* `candidate_contracts(historical=True)` keeps the contracts that
  were Active at the sale time (a never-published Draft never sold). It is used by:
  - the simulator;
  - ORIGINAL_SALE_DATE and HISTORICAL_SALE_DATE;
  - CURRENT re-derived at the moment it was priced (a guest's paid or approved change, ADR-044).

  Live selection keeps the live status (search, quotes, bookings, channels, a staff CURRENT
  change): a stop sale acts now (ADR-045, unchanged). A guest who accepted a price and paid by its
  deadline therefore gets the change even if the contract was suspended in between. ADR-045 keeps
  modifications of sold stays out of a stop sale; availability and restrictions are still checked
  live under the locks.
- *Coupon uses at a past moment* (simulator only): a limited promotion's uses are those held
  then. That is every redemption made by then and not released by then; the booking's own uses
  are still excluded (G-09). `TEX Promotion Redemption.released_at` is new (patch p34). The
  controller writes it once, when a use is released, and refuses to take a released use again (a
  new use is a new redemption). p34 copies `modified` into it for uses released before, because
  nothing writes a released row. A row without it falls back to `modified`. Modifications count
  uses as they are now: a code a change keeps or adds is recorded under today's limits by
  `sync_redemptions` (G-09), so pricing it on a past count would promise a discount the apply then
  refuses.
- *What "as of the sale time" covers in the simulator:*
  - the contracts Active then; the version live then, its frozen payload and selling terms (G-50);
  - markups, promotions and their limits, extras, the tax policy, FX policies and provider rates
    (G-20, ADR-031);
  - coupon uses held then.

  Not as of then:
  - the stay itself: the reservation's current request, channel and guest (the booking's coupon
    key, else the guest's e-mail or phone now);
  - the hotel's group, which decides whether group-wide promotions apply;
  - availability, restrictions and the capacity of limited extras, which are not checked (the
    stay is sold already).

  The answer names the contract that sold then and its status now; the simulator dialog says when
  that contract no longer sells.
- *A proposal belongs to whoever made it.* A proposal token names:
  - its `origin` (`staff`, or `guest` for the manage page);
  - its proposer (`by`);
  - its hotel and booking.

  Staff apply only their own proposals (`require_proposer`), at the hotel and booking named:
  another user's is refused, a guest's too, and so is a token re-pointed at another reservation.
  The manage page accepts only a guest's proposal (`guest_changes.submit`, after the booking's own
  guards, so a booking waiting for its payment still says so first), and its booking is proven by
  the manage token (`_own_reservation`, and `submit` checks the reservation's booking).
  The guest path applies only CURRENT proposals. Stored proposals (`TEX Guest Change Request`:
  verified and stored by the server when the guest submitted) apply on payment or staff approval
  as before. A token made before this change names nobody and is refused. It expires within
  `PROPOSAL_TTL_MINUTES` (30) anyway. ADR-044's lock order (booking → reservation → inventory) is
  unchanged: the proposer check needs no lock, and the hotel and booking check reads the locked
  reservation.
- *Explained.* The `reservation.modify` audit adds the pricing sale time. For an override it also
  records the computed total next to the amount set (`computed_total`, `override`).

**Consequences.**
- Historical selection depends on the `contract.status` audit rows. A status written behind the
  controller (a direct DB write) is invisible to it, as it is to the audit: such writes are not
  supported. The G-74 audit work must keep `contract.status` as it is (action, reference, old and
  new status).
- The simulator's answer for a past moment no longer changes with later archives, stop sales or
  coupon uses. Its answer for "now" is the live one.
- Staff cannot hand a proposal to a colleague. The colleague proposes again, at the same price if
  nothing moved.
- Not changed: add-on proposals (ADR-034) are bound to guest or staff but not to the staff user.
  They price at today's rates and need `reservation.modify`, so the risk is lower; binding them
  the same way is a follow-up.
- The simulator refuses a future sale time. `test_pricing_policies` simulated one hour after a
  version scheduled for tomorrow; it now publishes that version now and simulates the present.
- Tests: integration `test_modification_determinism` (24; 21 fail on the base commit), unit
  `TestStatusAt` (4). All 24 integration modules pass (465 tests), among them `TestCouponLimits`,
  `TestHistoricalSimulator`, the G-41 product-change test (a colleague's token is now refused
  before its channel re-check), `test_fx_snapshot` HISTORICAL and the self-service suites.

**Review follow-up (independent review of G-51).** No Critical or High finding. One Medium and
three Low, fixed as follows.
- *A staff approval never sells a stopped contract (Medium).* The status "as of the pricing
  time" was used for every stored guest proposal, including a staff approval of a Requested
  change. Such a request does not expire, so an extension priced at 13:30 and approved days
  after a 14:00 suspend sold new nights on the stopped contract. Before G-51 the live status
  made that approval fail.
  - `apply()` still re-derives a stored proposal as of its pricing time and finds the contract
    that priced it: that is the price the guest was shown (ADR-044).
  - For a staff approval (stored, not paid), `apply()` then refuses while that contract is not
    Active. It reads the status under the shared row lock a booking takes
    (`modification.approval_refusal`, `ContractSuspended` / `ContractNotOnSale`). The message
    reads "<code> no longer sells (Suspended): this change cannot be approved at the price the
    guest was shown. Reject the request, or change the reservation yourself".
  - The paid path keeps the status of the pricing time, bounded by the payment deadline (30 +
    60 minutes, ADR-044).
  - *Decision: requests do not expire,* and an approval is not re-priced live. Approving at the
    price shown is a deliberate staff decision (ADR-044). The approver now sees the contract and
    its status on the request card (`staff_row.contract`, `approve_blocked`; Approve disabled,
    six languages), and a stopped contract blocks it.
  - A shortening is refused the same way: one rule, as before G-51. Staff can still make the
    change themselves with the basis they choose (ORIGINAL_VERSION needs no contract on sale)
    and reject the request.
- *A sale time with an offset (Low).* `past_sale_time` read "…Z" or "…+03:00" as an aware
  datetime, and comparing it with the site's naive clock raised an HTTP 500. Such a time is now
  converted to the site's time zone, the one every sale time is kept in: it is the same moment.
- *The channel re-check on apply is tested (Low).* A B2B seller whose profile no longer sells
  B2B cannot apply their own room-upgrade proposal (`test_channel_binding`). The proposer check
  comes first, so this is the path where the check still decides.
- *p34 is approximate by construction (Low).* A use released before p34 gets `modified` as its
  release time. A row written after its release but before p34 (a Desk or data-import edit; TEX
  never does it) is therefore counted a little longer in the simulator's coupon history. Uses
  released since p34 carry their exact time.
- *An override's revision says what was computed (minor).* The revision stays MANUAL at the
  amount set, with `basis_sale_at` the sale time of the basis used. Its `changes.priced` now
  holds that basis and the engine's total (the audit already did), and the revision list shows
  "computed on <basis>: <total>". No schema change: `pricing_basis` keeps meaning "how the
  amount charged was set".
- Tests (fail-first commit `0326a55`): `test_approving_a_request_on_a_contract_stopped_since_is_refused`,
  `test_an_archived_contract_blocks_approval_but_not_rejection`,
  `test_a_sale_time_with_a_utc_offset_is_read_in_the_hotels_time_zone`, the override-on-a-historical-date
  test extended (`priced`), and `test_the_proposer_needs_the_channel_again_when_applying`. All fail
  on main 178d53c except the channel test, which covers a check that was already there.

## ADR-055 TEX decimal fields keep 9 places and hold what was typed; FX rates keep 10 significant digits
**Context.** G-72 (R-02, R-03).
- The generic rule values of the commercial DocTypes were `Float` fields of precision 6. Frappe
  v16 sizes a Float/Currency/Percent column by its precision (`DECIMAL(21, precision)`), so these
  columns were `DECIMAL(21,6)`, not `DECIMAL(21,9)` as the gap assumed. A 7th decimal typed in the
  TEX screens (an occupancy factor of a third, 0.333333333; a loyalty point worth 0.004999999)
  was rounded away on save without a word.
- Frappe hands a DECIMAL column to Python as a binary float (`CONVERSION_MAP`: NEWDECIMAL →
  float), and writes a float through its `repr`. The loaders turned floats into Decimals with
  `D()` in one place and `D(str())` in another; the TEX API returned these fields as JSON
  floats.
- An FX sell rate was rounded to 6 decimal places (`money.FX_PLACES`): TRY → EUR 1/34 became
  0.029412, 5 significant digits. On 150,000 TRY that is 4,411.80 EUR instead of 4,411.76.

**Decision.**
- *Field types.* Frappe has no Decimal fieldtype: Float, Currency and Percent are all DECIMAL
  columns and differ only in how Desk formats them. The type says what the value is; the
  precision says how many places the column keeps, and it is 9 for every TEX commercial input:

  | Field | Before | After | Why |
  |---|---|---|---|
  | TEX Price Period `adjustment_value` | Float p6 | Float p9 | %, factor or money by `adjustment_op` |
  | TEX Period Rate `value` | Float p6 | Float p9 | money (ABSOLUTE/ADD) or factor/% by `op` |
  | TEX Occupancy Rule `value` | Float p6 | Float p9 | factor, % or money by `op` |
  | TEX Board Rule `adult_amount` | Float p6 | Float p9 | money (ADD/ABSOLUTE) or % (ADJUST_PERCENT) |
  | TEX Board Rule `child_percent` | Float p6 | **Percent** p9 | always a percentage |
  | TEX Contract Rate Plan `value` | Float p6 | Float p9 | % or factor or money by `op` |
  | TEX Contract Offer `value` | Float p6 | Float p9 | %, money, multiplier by `value_type` |
  | TEX Markup Rule `value` | Float p6 | Float p9 | % / factor / money by `op` |
  | TEX Promotion `value` | Float p6 | Float p9 | %, money, multiplier by `value_type` |
  | TEX Promotion `min_basket` | Currency | Currency, `options: currency` | money in the promotion's currency (column unchanged) |
  | TEX FX Rate `rate`, TEX FX Policy `manual_rate` | Float p9 | unchanged | FX rates (already 9 places) |
  | TEX FX Policy `adjustment` | Float p6 | Float p9 | % or fixed by `mode` |
  | TEX Cancellation Rule `penalty_value`, Policy `no_show_value` | Float p6 | Float p9 | %, nights or money by type |
  | TEX Payment Policy `deposit_value` | Float p6 | Float p9 | %, nights or money by type |
  | TEX Tax Rule `rate` | Float p6 | **Percent** p9 | always a percentage |
  | TEX Tax Rule `amount`, TEX Extra Price Rule amounts | Currency | Currency, `options: currency` (the parent's) | money (column unchanged) |
  | TEX Loyalty Tier `earn_multiplier` | Float p6 | Float p9 | factor |
  | TEX Loyalty Earn Rule `rate` | Float p6 | Float p9 | points per unit (a factor, not money) |
  | TEX Loyalty Program `point_value` | Float p6 | **Currency** p9, `options: currency` | money in the program's currency; 9 places so a sub-cent point (0.005 EUR) is not rounded to 2 |
  | TEX Loyalty Program `max_redeem_percent` | Percent | Percent p9 (explicit) | percentage |
  | TEX Child Age Band `from_age`, `to_age` | Float p2 | unchanged | years, judged in whole months (ADR-051); not money |

  A value whose meaning depends on its rule's operation stays Float: Currency would make Desk
  format a factor or a percentage as money and round it to the currency's places. Money fields
  get an explicit precision where the default (the system's currency precision, often 2) would
  round a legitimate value (the loyalty point value). The DocType JSON is generated from
  `devtools/doctype_specs.py` (`V = {"precision": "9"}`).
- *Write: what is typed is what is stored, or it is refused.* `commercial.decimals.check_inputs`
  runs `before_validate` on every TEX DocType users type decimals into (contract versions and
  their tables, pricing policies, markups, promotions, FX rates and policies, cancellation,
  payment and tax policies, extras, loyalty programs), whoever saves: the TEX API, Desk, a data
  import or a script. Each decimal field of the record and its rows goes through
  `money.db_input`:
  - typed text is refused, naming the field and row, when it has more places than the field
    keeps (trailing zeros aside), more than 15 significant digits (it would not survive the
    binary float Frappe writes it through) or more than 12 integer digits;
  - a binary float or Decimal from code has no typed digits: it is rounded half-up to the
    field's places, as the column would round it, and refused only when it does not fit.

  Every value of up to 15 significant digits crosses Python float → `repr` → MariaDB unchanged
  (measured on the bench's MariaDB 10.11: a double is stored at its shortest round-trip text).
  The manual FX rate endpoint checks the rate as typed the same way.
- *Read: one helper.* Loaders read these fields with `money.db_dec` (pure): the shortest repr of
  the float Frappe hands over is the stored decimal for every value of up to 15 significant
  digits; anything a float carries beyond the column's 9 places (binary noise) is rounded off.
  A clean value keeps the representation `D()` gave it (`"0.3"`, `"12.0"`), so payload text,
  explanations and API output do not change for existing values. Used by the contract loaders
  (`build_terms`, occupancy rules, cancellation and payment policies), the pricing context
  (markups, promotions, FX policies and provider rates, tax rules, extras) and loyalty earning
  and redemption.
- *API: strings.* The TEX screens get these fields as exact decimal strings (`decimals.api_value`
  in `doc_dict`/`rows`, policy lists, FX rates, loyalty programs), never JSON floats. The screens
  already carried them as typed strings; they now accept 9 places (`DECIMAL_PLACES`).
- *FX precision: significant digits, recorded as they are.* `money.quantize_rate` keeps at least
  `FX_SIGNIFICANT` (10) significant digits and never fewer than 6 places: TRY → EUR
  0.02941176471, GBP → USD via EUR 1.294117647, EUR → TRY 51.00000000. Storing sub-1 pairs as
  their inverse was rejected: it would change the meaning of `sell_rate` ("1 from = rate to") in
  every recorded snapshot. A quote records every digit (`money.to_str_rate`: at least 6 places,
  no trailing zeros beyond): a rate recorded before at 6 places serialises byte-identically
  ("51.000000", "0.029412"), so its pin, its explanation step and its record are the same text.
  `Reservation.tex_fx_rate` is informational (DECIMAL(21,9)); the price-locked snapshot holds the
  exact rate.
- *Explanations.* A rule value is shown as stored (`describe_op` up to 9 places: "× 0.333333333";
  params `to_str_param`: at least 6, exactly to 9). A value of up to 4 places (text) or 6 places
  (params) explains exactly as before.
- *Migration.* The DocType sync widens the columns from DECIMAL(21,6) to DECIMAL(21,9): every
  stored value is kept (none has more than 6 places) and no stored value carries binary noise (a
  DECIMAL column rounds what is written to it), so nothing is rewritten. p35 checks every column
  is DECIMAL(21,9) (re-syncing a DocType left narrower) and that every published payload still
  hashes to its recorded hash; payloads are never changed. On the dev bench: 20 fields at 9
  places, 193 published payloads verified, none failed.

**Consequences.**
- Published payloads keep their bytes and hash: canonical serialisation is value-based
  (`dec_str` normalises), and widening a column changes no value. A version rebuilt from its own
  rows after the migration hashes to its frozen hash (`test_money_fields`).
- Price-locked reservations reprice on their sold terms to their sold totals: ORIGINAL_VERSION
  and ORIGINAL_SALE_DATE pin the rates their sale recorded (ADR-051), read back exactly as
  recorded, 6 places or not. New quotes, CURRENT and HISTORICAL_SALE_DATE reprices and the
  simulator resolve rates at the new precision, so a stay sold before and repriced on today's (or
  a historical date's) terms can differ by a cent where a rate below 1 or a cross rate converts.
  A quote made before the deploy books at its stored price and rate; an offer searched before
  and quoted after is repriced, and a changed total is reported (`price_changed`).
- More than 9 decimals, or a 16th significant digit, is now an error where it was silently
  rounded (also an age band typed with 3 decimals). Scripts writing floats are unaffected.
- Not changed: age bands stay 2-place years; the legacy Kamra PMS money fields and the legacy
  pricing path of hotels outside TEX (ADR-028) are not TEX inputs.
- Tests: unit `test_money_fields` (11: column round trips incl. 20,000 random 9-place and
  money values, typed-input refusals, 10-significant-digit TRY → EUR, a 6-place pin reproducing
  its old total 4,411.80 against 4,411.76 at the new precision, the explanation of a 9-place
  factor; 11 failed or errored on the base commit); integration `test_money_fields` (9: the
  schema, every G-72 field saved through the TEX API with 7+ decimals kept in the column, the
  API and the loaders, refusals, a published payload through p35, a reservation sold at 6 places
  repriced ORIGINAL_* to its total and CURRENT at 10 significant digits, a stay sold at 10
  significant digits repriced and extended on its recorded rate; the first 8 all failed or
  errored on the base commit and schema). `Reservation.tex_fx_rate` is written at its 9 places
  (`money.db_dec`), so the record in memory is the stored one. `test_markup_fx_tax` cross rate now 1.294117647 (was 1.294118).

## ADR-056 CRM data follows the viewer's hotels; the funnel keeps no identity without consent; withheld fields never leave through Desk or REST
**Context.** Three gaps of the 2026-09-23 audit.
- G-65 (R-37). The guest profile called `loyalty.summary(guest)` over every program: another
  tenant's program, its balance and its ledger (bookings, stay dates) were shown to anyone who
  could see the guest. `Guest.tex_loyalty_points` (and `tex_stays`, `tex_lifetime_value`,
  `tex_last_stay`) are totals over every tenant's programs and stays: the list and profile served
  the stored points, the `loyalty_points` segment fact used them (a segment's membership told a
  tenant another tenant's points), and Desk / REST showed all of them to whoever could read the
  guest. `list_guests` read every visible guest and paged in Python. The profile had no extras
  and no cancellation count or fees.
- G-81 (R-38). A funnel event stored an e-mail hash (a pseudonymous identifier: personal data under
  GDPR/KVKK) whether or not the visitor consented; a browser's funnel payload kept whatever
  contact fields it carried. A case left at payment was never recovered when the guest paid later
  (only a `booked` event in the same session recovered it), so staff could chase a guest who had
  paid. The consented-contact and recovery paths had no test.
- G-95 (R-14, R-43). The price-locked snapshot and related fields hold what only
  `price.view_cost` may see in the TEX API (rule explanation, cost, margin, FX record with provider
  rate and row, FX margin, policy): `Reservation.tex_pricing_snapshot`, `tex_cost_amount`,
  `tex_margin_amount`, `tex_fx_rate`, `TEX Quote.result_json`,
  `TEX Reservation Revision.snapshot_before` / `snapshot_after`. Desk and REST scoped them by
  tenant only: any role with read on those DocTypes at the hotel read them.

**Decision.**
- *Loyalty follows the viewer's hotels* (`loyalty.summary(guest, programs, hotels=)`):
  - a viewer sees only the programs that reach their hotels: a hotel's own program, or its
    group's (`visible_programs`). Another hotel's own program is not shown, even inside the same
    enterprise: guest identity is shared inside an enterprise (ADR-040), a hotel's program is not;
  - a visible program's balance is shown whole (a group program is one balance, redeemable at the
    viewer's hotel), tier and value included;
  - a ledger entry tied to a booking or stay at a hotel outside the viewer's scope shows its points,
    status and dates, never that booking or its reason (`other_hotel`), as consent entries made at
    another hotel (ADR-046 review). Manual adjustments of the program (no booking) stay visible;
  - `programs` is required: no caller can ask for "every program" by leaving it out;
  - the stored totals are never served by the TEX API: the list, the profile and the segment facts
    compute points from the viewer's programs (one grouped SQL per page), stays and value from the
    viewer's hotels (as before, ADR-036).
- *The guest list is read in SQL* inside the viewer's tenancy: `COUNT(*)` for the total and one
  `LIMIT/OFFSET` page, in a stable order (`modified DESC, name DESC`), search typed literally
  (`%`/`_` escaped). A segment filter is evaluated on the viewer's facts over the matching guests
  read in batches of 500, keeping only the page: memory stays bounded, the work is still linear in
  the tenant's guests (a stored fact table remains the next step, ADR-036).
- *Profile completeness* (R-37), all at the viewer's hotels:
  - `extras`: the extras on stays that were not cancelled or no-shows, from each stay's price-locked
    snapshot (those sold with it and those added later), with quantity, amount and currency; only
    what the guest pays is read, never cost, margin or rules. `extras_summary`: per extra and
    currency, quantity, value and number of stays (never summed across currencies);
  - `cancellations`: count, no-shows, fees per currency (the stay's currency, else the hotel's),
    last cancellation day; each closed stay shows its fee.
- *The funnel keeps no identity without consent* (G-81):
  - `_track` keeps an e-mail hash only when the visitor ticked marketing consent in that same step;
    contact fields (`email`, `phone`, names) never stay in any payload, whoever sent it;
  - no legitimate-interest basis per hotel is built: the spec asks for funnel events "where legally
    permitted" and keeps transactional apart from marketing consent (R-38), and ADR-046 makes
    abandoned-payment contact depend on the profile's own consent. A per-hotel legitimate-interest
    setting is a legal decision for the owner (recorded as an open item), not a default;
  - contact data of a case is stored only with the profile's own e-mail consent (ADR-046) and
    shown only while that consent holds: withdrawn later, the case stays, anonymous;
  - a case is recovered when its session books, or when the booking it left at payment is paid
    later (`Confirmed` / `Partially Cancelled`): at detection for sessions still in the window, and
    by a sweep of open payment-stage cases of the last 60 days (a payment link's life);
  - p37 removes hashes kept without consent.
- *Withheld fields never leave through Desk / REST* (G-95, and the guest totals of G-65):
  - the fields are at Frappe permlevel 1 in the DocType JSON (Reservation: snapshot, cost, margin,
    FX rate; TEX Quote: result; TEX Reservation Revision: both snapshots; Guest: stays, lifetime
    value and currency, last stay, loyalty points). Only System Manager (the platform
    administrators) holds permlevel 1. Frappe then leaves them out of every generic read path for
    everyone else (`frappe.client.get` / `get_list` / `get_value`, `/api/resource` and
    `/api/v2/document` reads, the Desk form, report view, export, print, link fetches) and refuses a
    filter, sort or aggregate on them (a legacy string aggregate is dropped from the query). A
    withheld text field reads as empty and a withheld number as 0;
  - two Frappe paths ignore field-level read permissions and are closed in
    `kamra.tex.security.internals`: the change history (`Version`, shown in the Desk form to anyone
    who may read the record) masks these fields' values when a row is written (`mask_version`;
    which field changed stays on record; p37 masks older rows), and the document a generic write
    returns (`frappe.client.set_value` / `save` / `insert`, `POST` / `PUT /api/resource`) leaves them
    out when the save was checked against a user who may not read them (`hide_after_write` marks the
    document on `on_change`, `HideInternalsAfterWrite.as_dict` honours the mark; TEX services save
    with `ignore_permissions` and are never marked);
  - the TEX API is the only way business users read them, by capability at the hotel:
    `crs.reservation` with `price.view_cost` shows the explanation, cost and FX record, without it
    `quoting.strip_internal` removes them (unchanged); reports show cost and margin with
    `price.view_cost` only (unchanged).
  - Why not a per-hotel read hook: a permlevel is role-based and cannot follow a per-hotel
    capability, but a hook that strips values from `onload` / `as_dict` does not reach `get_list`
    with fields, filters, sorting or aggregates, report views, exports, print or the change history,
    each of which Frappe resolves in SQL or outside the document. Withholding the fields from every
    business role is the only option Frappe enforces on every path. Moving the internals into a
    separate record was rejected: every TEX service reads the snapshot, and the price-lock guard
    (ADR-010) protects it where it is.

**Consequences.**
- Hotel staff, `price.view_cost` or not, no longer read snapshots, cost, margin or FX in Desk /
  REST; the TEX reservation screen and reports show them with the capability. Scripts and
  integrations that read these fields over REST need a platform (System Manager) account.
- A save through Desk / REST by a user without permlevel 1 cannot change these fields (Frappe
  resets them to the stored values), which the price lock (ADR-010) already required.
- A site whose role permissions for these DocTypes were customised (Custom DocPerm) uses its own
  rows instead of the JSON's: p37 lists such DocTypes so an administrator can check permlevel 1.
- Not changed, open: `TEX Contract Version` (payload and rate tables, i.e. contract cost) is still
  readable in Desk by the Hotel Admin role at its hotels whatever the granted profile (G-11 covered
  the TEX API only); a group program's ledger is readable in Desk by the group's Hotel Admins
  (`VIA_PARENT`), other hotels' bookings included; a very large tenant's segment filter scans its
  guests in batches.
- Tests: `test_crm_privacy` (18: loyalty programs, a group program's other-hotel entries, the
  guest totals in the TEX API and in Desk / REST, segment facts, SQL paging and totals, extras and
  cancellations, no hash without consent, browser payloads, p37 hashes, consented contact and its
  withdrawal, recovery by a later payment and by a later booking, Desk / REST reads, a write's
  response, the change history, the TEX API by capability, p37 history). Fail-first on the base
  commit and schema: 15 of 18 failed or errored; the other three pin behaviour that was already
  right (another enterprise's viewer is refused, recovery by a later booking in the session, the
  TEX API's capability rule). E2E `crm-profile.spec.ts` (written and type-checked).

**Review follow-up (independent review of ADR-056, 2026-09-25; 2 Medium, 5 Low; patch p40).**
- *The program ledger followed the program, not the viewer (Medium).* `loyalty.ledger` needed
  `crm.view` at any hotel of a group program and then returned every row of the group: the guest and
  their name, the booking and stay, the reason (stay dates), the actor and the explanation (rate ×
  points gives the stay's value). It now applies the profile's rule: an entry tied to a booking or
  stay at a hotel outside the viewer's `crm.view` scope shows its points, status and dates only
  (`other_hotel`; booking, reservation, reason, actor and explanation left out), a guest the viewer
  may not see (the `require_guest` rule) is not named, and asking for such a guest's entries is
  refused. The CRM → Loyalty ledger says "A guest of another hotel" / "At another hotel of the
  program".
- *A withdrawal left the case identifiable (Medium).* The TEX API masked e-mail and phone but kept
  the profile link, which leads to the same contact data; Desk / REST showed a case's profile,
  e-mail and phone to the Hotel Admin role without `crm.view` and whatever the consent; funnel
  hashes stored with consent survived a withdrawal. Now:
  - a withdrawal of marketing e-mail consent (1 → 0), on every path (the CRM, the Desk form, REST:
    `Guest.on_update`), makes the guest's cases anonymous (no profile, e-mail or phone; consent 0)
    and removes the e-mail hashes of the cases' sessions and of the guest's addresses
    (`crm.forget_contact`); the profile, its stays and its consent history stay;
  - the CRM listing leaves the profile link out too whenever it masks the contact;
  - `TEX Abandoned Booking.guest` / `email` / `phone` and `TEX Funnel Event.guest` / `email_hash` are
    withheld fields (permlevel 1, System Manager only), like the pricing internals;
  - p40 makes older cases anonymous where the profile no longer consents and removes the funnel
    hashes of profiles without e-mail consent.
- *The browser's funnel payload was a denylist (Low).* Nested contact data and other spellings
  (`e_mail`, `tel`) were stored. `public.track` now keeps an allow-list per event: `room_view`
  hotel, room type, board, rate plan; `abandoned` its quote ids (at most 10, 64 characters each) and
  hotel; text of at most 140 characters; nothing else, at any depth.
- *A consent sent as text read as yes (Low).* `bool("0")` is true. A consent flag means yes only for
  `True`, `1`, `"1"` or `"true"` (any case): `booking.consent_given`, used by the booking engine and
  by `resolve_guest` for every booking path (CRS included).
- *Customised role permissions dropped System Manager's permlevel-1 row (Low).* Frappe reads a
  DocType's Custom DocPerm rows instead of its JSON rows once one exists, and Kamra's permission
  scripts write them (`fix_perms_fields._grant`, used by `seed_rbac_v2` and `bootstrap_v4/8/9/10`;
  `seed_users`): the withheld fields then failed closed for platform administrators too.
  `internals.ensure_custom_perms` adds System Manager's permlevel-1 row where a DocType with withheld
  fields has custom rows; the scripts call it after writing theirs (and `_grant` now updates the
  role's document-level row, never its field-level one); p40 adds it once, at the upgrade
  (`setup.ran_before`: a forced re-run never undoes an administrator's change). A business role
  holding permlevel ≥ 1 of such a DocType is printed on every p40 run and audited once
  (`permission.withheld_fields_exposed`, platform level) for an administrator to remove.
- *Masking destroyed the change history for everyone (Low).* Of the two options (keep the values in
  a record only platform administrators read, or mask at read time), the first is simpler and
  robust: the Desk form's history comes from `frappe.desk.form.load.get_docinfo`, which several
  endpoints call (form load, save, docinfo reload) and no hook reaches. `mask_version` masks the
  values when a Version row is written and `keep_withheld_values` keeps them in a platform-level
  audit event (`version.withheld`: the Version's name and each withheld field's old and new value;
  no hotel, group or enterprise, so only platform administrators read it in Desk and the TEX audit
  log, which now leaves the platform-only actions out of a record's own trail for everyone else).
  p37 does the same for older rows; rows p37 masked before this change (dev sites) kept no copy.
- *`db_set` marked documents (Low, latent).* Frappe runs `on_change` from `db_set`, so a non-System
  Manager session's `db_set` marked the document and its `as_dict` (webhooks, `as_json`,
  `copy_doc`) lost the fields. The mark is now set on `on_update` (a save or an insert, never a
  `db_set`) and only while the request is a generic write that answers with the document
  (`frappe.client.set_value / save / insert / submit / cancel`, `POST` / `PUT /api/resource`, `POST`
  / `PUT` / `PATCH /api/v2/document`); code's own saves keep their document whole.
- *Whose profile a booking joins (found by the E2E run on main).* `resolve_guest` fell back to the
  phone whenever no profile had the booking's e-mail, so a booking with e-mail B and the phone of
  profile A (a family member, a colleague, a travel agent's desk, a reused test number) joined A:
  another person's stays, extras and cancellations in A's history, shown to staff as A's, and B
  unfindable by their own e-mail. The e-mail is now the identity when one is given; the phone finds
  a profile only for a booking without an e-mail, or a profile known by phone alone (no e-mail).
  A returning guest who books with a new e-mail gets a second profile (staff may merge the two,
  `merge_guests`, which needs every stay of both in their scope, ADR-027); that duplicate is the
  lesser harm than one person's data in another's profile, and
  consent stays tied to the address that gave it (ADR-046). Per-guest coupon limits are keyed by the
  booking's own e-mail or phone, not the profile, and are unchanged.
- *G-97 (contract cost in Desk) stays open.* It is not small: the rate tables are child tables whose
  fields a direct child query reads unless each child field is withheld too; `TEX Occupancy Rule` and
  `TEX Child Age Band` are shared with `TEX Pricing Policy`, whose parent would need the permlevel-1
  row as well; a contract version tracks changes, so its Version rows carry child rows (added,
  removed, row_changed) that `mask_diff` does not cover; `contract.version.save` audit events hold
  compact rate diffs at the hotel, read by its Hotel Admins in Desk and by `settings.admin` in the
  TEX audit log; markup rules are in the same position. Recorded in FINAL_GAP_AUDIT (#70a).
  - *Closed (audit Part 2I, 2026-09-27).* Instead of withholding fields, the records are closed as a
    whole: TEX Contract Version, TEX Markup Rule and TEX Pricing Policy give System Manager alone
    Desk / REST access (`doctype_specs.COST`; the version's rate tables, child tables, follow it), p66
    takes every flag from other roles' Custom DocPerm rows, and the audit events about cost
    (`perm.COST_DOCTYPES`, one list with the audit trail's `TRAIL_COST`) are hidden from non-platform
    users in Desk / REST. The TEX API is the one reader: with `price.view_cost`, a contract and its
    events also with `contract.edit` (G-11, the record's own trail). The TEX audit log's hotel view
    (`settings.admin`) leaves out, in its query, the cost events its viewer could not read by the
    record's trail, the group / enterprise events that reached the hotel too (fix round 1). The
    Version rows of a contract version stay as Frappe keeps them (read with the version, now System
    Manager's).
- Tests: `test_crm_privacy` 29 (11 new; 2 extended: the listing drops the profile link, p37 keeps
  the values) and the p40 registry entry in `test_patches`; on the merged base (main `665b6b9`) and
  its schema the 12 review tests fail or error, one for each finding; the identity test fails on the
  branch before its fix (the second e-mail joined the first profile). E2E `crm-profile.spec.ts`
  books with a unique phone per run and passes twice in a row.

**Second review follow-up (second independent review of ADR-056, 2026-09-25; 1 High, 3 Medium, 9 Low;
patch p45).**
- *A withdrawal scanned the funnel under locks, and tracking swallowed deadlocks (High).* `forget_contact`
  ran `UPDATE tabTEX Funnel Event … WHERE IFNULL(email_hash, '') != '' AND (email_hash IN … OR session_id
  IN …)` inside the withdrawal's transaction: no index serves it, so InnoDB locked every funnel row (and
  the gaps) until commit, and every booking in that window writes funnel events. `_track` caught every
  exception, a `QueryDeadlockError` included: InnoDB had already rolled the booking's whole transaction
  back, `retry_on_deadlock` never saw the error, and `book` answered with a booking that no longer
  existed. Now:
  - the rows a withdrawal clears are read through indexes and written by primary key
    (`CASES_OF_GUEST`, `FUNNEL_BY_HASH`, `FUNNEL_BY_SESSION`, `FORGET_CASES`, `FORGET_EVENTS`: no
    `IFNULL`, no `OR`); new composite indexes `(email_hash, session_id)`, `(session_id, occurred_at)` on
    the funnel and `(session_id, status)` on cases (`setup.TEX_INDEXES`, p45); the funnel reads are
    plain consistent reads, so the only rows locked are those cleared; the cases are read `FOR UPDATE`
    so a case written while the withdrawal runs is seen once written. p40 reads the funnel once, without
    locks, and writes by primary key (it no longer calls `forget_contact` per guest);
  - `_track` re-raises `QueryDeadlockError` and `QueryTimeoutError` (`txn.TRANSACTION_LOST`): the booking
    is retried by `retry_on_deadlock` or fails, never reported. The other best-effort steps inside a
    booking's transaction do the same: the booking and payment e-mails (`notify._deliver`,
    `booking_mail`, `booking_confirmed`, `payment_link`: each queues an Email Queue row and a TEX
    Communication), a payment start (`payments.service.start_payment`, which records a failed gateway
    call on the transaction) and the channel-manager push trigger on Reservation. `realtime.notify`
    publishes after commit and writes nothing.
- *An erasure left the person behind (Medium).* `kamra.api.anonymize_guest` blanked e-mail and phone but
  kept `tex_consent_email` = 1, so no clean-up ran: cases kept their contact, funnel hashes stayed, and the
  Desk form's history (Version rows) kept the old name, e-mail and phone. An erasure now withdraws every
  consent (stamped and audited, source `erasure`), clears date of birth, gender, tags, preferences and the
  identity documents (the attached files are deleted), forgets the cases and funnel data, replaces the
  booker's name, e-mail and phone on the guest's TEX bookings and their payment links with the alias,
  removes the profile's Version rows and masks those values in the Version rows of its bookings, payment
  links and stays (no copy kept), and audits `guest.erase` (counts only). Clearing an e-mail or a phone in
  any save (the CRM, the Desk form, REST) forgets the contact data it leaves behind, like a withdrawal.
  p45 applies this to profiles erased before (every consent withdrawn, cases and funnel forgotten,
  history removed). Audit events are immutable and keep what they recorded (a consent change names no
  address; `guest.update` events keep the old and new values of an edit: a retention decision for the
  owner, recorded in GO_LIVE_READINESS).
- *Duplicates nothing could merge (Medium).* The identity rule (first review) creates a second profile
  for a returning guest with a new e-mail, and the only merge was the legacy PMS endpoint: it repointed a
  fixed list of legacy links, failed with `LinkExistsError` on `TEX Booking.booker_guest`, `TEX Loyalty
  Ledger.guest`, `TEX Communication.guest` and `TEX Abandoned Booking.guest`, and left the points behind.
  `crm.merge_guests(source, target)` (`kamra.tex.api.crm.merge_guests`, POST; the legacy endpoint now
  calls it):
  - who: staff who may edit both profiles (`crm.edit`, `require_guest`) and may edit guests at every
    hotel either profile has any record at (every DocType linking to Guest whose rows name a hotel);
    platform administrators; the legacy PMS endpoint keeps its own guard (ADR-027: an administrator
    role, every stay of both profiles in the caller's scope, the PMS open to the caller) and then runs
    this merge (a walk-in profile with no stay and no enterprise included, as the upstream eval harness
    does); both profiles belong to one enterprise (or to none; a legacy profile without one takes the
    other's);
  - what moves: every Link to the duplicate found in the meta (TEX and legacy DocTypes, custom fields,
    child tables), read and then written by primary key; its comments and other dynamic links, its
    attachments and its change history. The audit trail is immutable and keeps the duplicate's name:
    the merged profile's consent history includes the consent events of the profiles merged into it
    (followed through the `guest.merge` events);
  - loyalty: the ledger entries move, so a program has one balance and the tier follows the merged
    lifetime (both computed from the ledger); the stored points and stay totals are recomputed;
  - the profile that stays keeps its data and takes the duplicate's where it has none (names, e-mail,
    phone, nationality, date of birth, gender, ID, address, language, country, market, notes,
    preferences, documents); tags are joined; VIP and blacklist are kept if either has them;
  - consent is the stricter of the two, per channel: it stays only where both profiles consented (a
    withdrawal on either side wins; ADR-046 ties consent to a proven owner); a change is stamped
    (`merge`) and audited, and without e-mail consent the moved cases lose their contact data;
  - both Guest rows are locked in name order first; the duplicate is deleted without a Deleted Document
    copy, and a link written by a concurrent booking after the move makes the delete fail (Frappe's link
    check), so the merge rolls back rather than leave a dangling link;
  - audited as `guest.merge` on the kept profile, seen at every hotel either profile had records at
    (old: the duplicate's name and both consent states; new: what moved per DocType, which fields were
    filled, the resulting consent; no contact data).
  The profile lists *possible duplicates*: other profiles the viewer may see, of the same enterprise (or
  none), with the same phone or e-mail (`possible_duplicates`, through the new `Guest (email,
  tex_enterprise)` and `(phone, tex_enterprise)` indexes); the CRM profile shows them with a "Merge into
  this profile" action, and a "Merge a duplicate" action takes any profile ID.
- *The ledger in Desk / REST followed the program (Medium).* `perm.VIA_PARENT` scoped `TEX Loyalty
  Ledger` by its program, so every Hotel Admin of a group read every entry of a group program, with its
  booking, reason and actor. An entry now belongs to a hotel (`property`, new field): its stay's or
  booking's, the program's hotel in a hotel's program, or for a manual adjustment the hotel it was made
  for (`loyalty.adjust(property=)`; the only hotel of the program where the user may edit guests, else
  the user chooses: the adjustment dialog asks). Desk / REST read an entry at its hotel only; an entry
  of no hotel is its program's hotel's in a hotel's program and platform level in a group's. p45 gives
  older entries their hotel (the stay's or booking's; for a manual adjustment of a group program, the
  one hotel of the program where its author may edit guests, when there is exactly one).
- *Low.*
  - L1: the CRM read a consent sent as text with `bool()` (`"0"` was yes): `update_profile` uses
    `booking.consent_given`.
  - L2: a masked change history of a case or funnel event kept a copy of the e-mail and phone in a
    `version.withheld` event, one more place contact data outlived a withdrawal: contact DocTypes
    (`internals.CONTACT_DOCTYPES`) are masked without a copy; p45 removes the copies kept and masks the
    Version rows written before (p37 masked fewer fields). Copies of pricing internals and of a guest's
    totals stay.
  - L3: an "anonymous" case at the payment step could be re-identified: its session (funnel events, whose
    `payment_started` payload names the booking) and its quote (`TEX Quote.booking` → the booker) were
    readable in Desk / REST, and the CRM listing showed the booking that recovered it. The case's
    session, quote and recovery booking and the funnel event's session and payload are withheld (permlevel
    1); a case keeps a quote only with contact data (the scheduler, the controller, a withdrawal and p45
    clear it); the CRM listing shows the recovery booking only with the contact. "Anonymous" in this ADR
    means: no contact data, and no link to the person in the CRM or in Desk / REST; the hotel's own
    booking records of that stay are not changed.
  - L4: another hotel's ledger entries showed their stay's maturity and expiry dates, and a manual
    adjustment of another hotel its author and free-text reason. For another hotel's entry the profile and
    the program ledger now show points, status and the month it was written only (no booking, stay,
    reason, actor, explanation, maturity or expiry date); an entry of no known hotel in a group program
    counts as another hotel's.
  - L5: the browser's funnel fields were an allow-list of names, not of values: the hotel must be one of
    the site's hotels, the room type and rate plan that hotel's, the board a known code, and each quote one
    of the site's hotels made in the visitor's own session; anything else is dropped.
  - L6: a phone found a profile even when several profiles shared it, and for anonymous booking-engine
    bookers, whose phone nobody verified. The phone now finds a profile only for staff, and only when
    exactly one profile of the enterprise has it (and no e-mail was given, or the profile has none);
    otherwise a new profile is made and shown with its possible duplicates.
  - L7: a withdrawal in the Desk form or REST wrote no `guest.consent` audit and left
    `tex_consent_updated_at` / `source` as they were: `Guest.validate` stamps a consent change made
    outside the CRM and the booking flows (source: `Desk`, `API`, `merge`, `erasure` …) and `on_update`
    audits it; the CRM and the booking flows record their own (no double event).
  - L8: the scheduler read the profile's consent and wrote the case later; a withdrawal committing in
    between left a case with contact data. `TEX Abandoned Booking.validate` re-reads the consent with a
    lock as the case is written (no consent: no profile, e-mail, phone or quote), and `forget_contact`
    reads the cases with a lock, so either order ends anonymous.
  - L9 (tests): the permission-script test checks that a platform administrator actually reads the
    withheld values; p40 is covered on its own paths (a hash of a profile that never consented, with no
    case; a case with contact data and no profile); a shared phone stays in the identity tests.
- Tests: `test_crm_privacy_review` (28: H1 6, M1 2, M2 6, M3 and L4 4, L1–L8 8, p40 and p45 2; the patch
  tests refuse commits until their rollback, as the G-76 review asks) and changes to `test_crm_privacy`
  (the funnel allow-list and identity tests follow L5 and L6; p40's cases are written below the new
  controller; the p40 tests refuse commits; L9); the p45 registry entry in `test_patches`. H1 is tested
  on its statements (each uses its index, checked with `EXPLAIN` on tables given the rows of a live
  funnel; no `IFNULL`, no `OR`), on two connections (a second connection writes funnel events as a
  booking does, not committed, before and while the withdrawal runs; each side waits at most 2 s for a
  lock) and on the booking (a deadlock while tracking is re-raised below the retry; through `book`, the
  first attempt is the victim and the retry books once, for "booked" and for "payment_started"). On main
  `b72b2a8` and its schema 27 of the 28 fail or error, each on its finding (the booking test: "booked:
  reported a rolled-back booking"; the two-connection test: "Lock wait timeout exceeded", although the
  new indexes were on the site: the old withdrawal's `UPDATE` is a locking read, which reaches the
  booking's uncommitted event of the same address and waits for it, where the new plain read does not
  see it; the others on the missing behaviour);
  p40's own paths (L9, coverage) pass. Before the two-connection test, 26 of 27 failed on `9215991` and
  on `b074527`. The three `test_crm_privacy` tests changed for L5 and L6 fail on the old code. E2E:
  `crm-profile.spec.ts`, the new `crm-merge.spec.ts` (a shared phone shown as a possible duplicate,
  merged from the profile), `crm-admin.spec.ts` and `booking.spec.ts` pass twice in a row on a server
  running this tree.

**Third review follow-up (focused review of the guest merge and the H1 fix, 2026-09-25; 1 High, 6
Medium, 3 Low; patch p48).**
- *M-6 (a regression of the H1 fix): a lock wait timeout failed bookings.* The second review made
  `_track`, the guest e-mails, the payment start and the channel-push trigger re-raise
  `QueryTimeoutError` as well as `QueryDeadlockError`, and `retry_on_deadlock` retries deadlocks only;
  meanwhile `purge_funnel` deleted `WHERE occurred_at < …` with no index on `occurred_at`, holding
  next-key locks on every funnel row until the daily job ended. A booking whose funnel event waited
  more than `innodb_lock_wait_timeout` (50 s) failed; before H1 it went through without that event.
  The two errors are not alike: a deadlock ends the whole transaction (InnoDB rolls the victim back),
  a lock wait timeout ends only its statement (`innodb_rollback_on_timeout` is off by default; the
  server setting is read on the first timeout, and where it is on a timeout is treated as a deadlock).
  Now:
  - `txn.transaction_lost(e)` says which, and `txn.undo_step(e, savepoint)` raises when the transaction
    is gone and otherwise undoes the step's own writes to its savepoint. `_track` (savepoint
    `tex_funnel_event`) and `notify._deliver` (`tex_mail_send`, `tex_mail_log`) use it: a timeout drops
    the event, or records the mail as failed, and the booking goes on; a deadlock is raised and the
    booking retried or refused, never reported. A payment start (`tex_checkout`) treats a timeout as a
    failed start (the request answers "could not be started") and raises a deadlock. The channel-push
    trigger writes nothing: it logs a timeout and raises a deadlock. The e-mails' rendering reads only:
    a deadlock is raised. `txn.TRANSACTION_LOST` is gone.
  - the purge reads old events through the new index `(occurred_at, session_id)` without a lock
    (`PURGE_OLD`) and deletes them by primary key (`PURGE_EVENTS`), 500 at a time, each batch committed
    by the job (`_commit`, skipped in tests). A new event (at the end of that index) never waits for it.
    (Since ADR-061's final follow-up, main-side group: one statement per event, `PURGE_EVENT`; one
    `name IN` statement for a batch that is most of a small funnel was read as a scan and locked it.)
- *H-1: the merge locked the profiles but read a stale snapshot.* Under REPEATABLE READ (and
  `innodb_snapshot_isolation` off on MariaDB 10.11) the request's read view is made by its first read,
  long before the merge takes its locks; every plain read after that (`_records_hotels`, the profiles,
  `_repoint`'s SELECT, `delete_doc`'s link check) missed rows committed meanwhile, and bookings never
  locked a profile before linking to it. A booking of the duplicate committed during the merge was left
  pointing at a deleted profile (its points lost, its hotel never checked); a concurrent withdrawal or
  erasure of the duplicate was ignored (and MERGE_FILL copied the erased contact); two merges of one
  duplicate into two profiles both "succeeded", the second moving rows off the first's target (the lock
  query returned one row, never counted); and `loyalty.redeem` read the balance from its snapshot after
  waiting for the profile's lock, so two redemptions could spend the same points (also before the
  merge existed). Now:
  - `_lock_pair` locks both profiles in name order and requires both rows back, named as stored (a
    name in another case or with spaces is the same profile and is refused; a duplicate merged elsewhere
    meanwhile is "not found"); both are loaded `FOR UPDATE`;
  - `_records_hotels` (`LOCK IN SHARE MODE`), `_repoint` (`SELECT … FOR UPDATE`, then by primary key)
    and `_assert_unlinked` (a shared-lock check per link table before the delete: anything still naming
    the duplicate fails the merge, which rolls back) read what is committed now. Every Link to Guest has
    an index that starts with it (`TEX Booking.booker_guest`, `TEX Communication.guest`, `TEX Funnel
    Event.guest` and the legacy Folio, Security Deposit, Service Ticket, Lost And Found Item, Exchange
    Transaction, Venue Booking, WhatsApp Message: `setup.TEX_INDEXES`, p48), so these reads lock the two
    profiles' rows, not the tables; a test fails when a new Link to Guest has none;
  - whoever writes a link to a profile locks it first (`crm.lock_guest` / `require_live_guest`):
    `booking.resolve_guest` (`FOR UPDATE`; a profile gone since the request began is looked up again
    with a locking read, which finds the profile it was merged into by e-mail, or none), a new loyalty
    entry (`FOR UPDATE`), a new TEX Communication (shared), a Reservation's save (`FOR UPDATE`, before
    the stay's totals are written: a stay read before a merge and saved after it is refused, never left
    on a deleted profile). The exclusive lock where the same transaction writes the profile next (the
    stay totals, the points) avoids a shared-to-exclusive upgrade, which deadlocks two bookings of one
    guest; `resolve_guest` runs after the inventory locks, so the lock order (nights, then the profile)
    is the one a modification already takes;
  - `loyalty.redeem` requires its `FOR UPDATE` to return the profile and reads the balance with a lock
    (`balances(lock=True)`, through the new `(guest, program)` index); so do `adjust`, the earn tier,
    a reversal, the daily expiry and the stored points total (`_sync_guest`).
  Remaining: a legacy PMS write of a record the merge moved (a Folio, a Security Deposit …) that was
  read before the merge and saved after it puts the duplicate back into that link; `modified` is not
  changed by the merge, so Frappe's own check does not catch it (a Reservation's save does, above).
- *M-1: the duplicate's comments, mail, tasks, shares and activity were deleted.* `_repoint` skipped
  every DocType in `ignore_links_on_delete`, and `delete_doc` then deleted the duplicate's Comments,
  ToDos and DocShares and unlinked its Communications and Activity Log. The merge now moves, with
  locking reads, Frappe's own dynamic links (`DYNAMIC_LINKS`: Comment, Communication and Communication
  Link, ToDo, Activity Log (reference and timeline), DocShare, Document Follow, Notification Log, View
  Log, Email Unsubscribe, Tag Link, File, Version) and any other Dynamic Link found in the meta; only the
  audit trail (TEX Audit Event, TEX Audit Scope) keeps the duplicate's name.
- *M-2: a merge could undo an erasure.* An erased duplicate merged into a live profile re-attached the
  erased stays to a person (and `guest_name` was rewritten with the real name); an erased target took
  live contact data. An erasure now sets a durable marker, `Guest.tex_erased_at` (read-only, no copy),
  and a merge refuses when either profile has it. p48 sets it on profiles erased before, from their
  `guest.erase` audit event or their `anonymize_guest` entry in the Agent Action Log; the notes text
  ("Profile anonymized on request.") is not proof (a merge could copy it), so profiles with the text
  and no record are counted, not marked. p45 now selects erased profiles by the marker too.
- *M-3: a merge could not be reconstructed.* The duplicate was deleted permanently and the audit held
  counts. The `guest.merge` event now names every record moved, per DocType (names are not contact
  data), and the duplicate is deleted into a Deleted Document (Frappe's own record, readable by System
  Manager only), holding the duplicate as it was committed when locked. It is kept `MERGE_COPY_DAYS` (90;
  owner decision to confirm, GO_LIVE_READINESS), then the daily job removes it (`purge_merge_copies`);
  an erasure of the profile it went into removes it at once (`erase_traces`). The copy holds the
  duplicate's contact data (a second e-mail or phone): kept for a period and platform administrators
  only, rather than lost, so a wrong merge can be undone by hand.
- *M-4: the legacy endpoint bypassed the hotel rule.* `kamra.api.merge_guests` passed `checked=True`,
  and its guard (`authz._guest_allowed`) checks the Hotel Admin role and Reservation hotels only. `checked`
  now skips only the TEX visibility check (`require_guest`): for anyone but a platform administrator the
  merge requires `crm.edit` at every hotel of every record of both profiles, whichever endpoint calls it.
- *M-5: p45 missed most earlier erasures.* It chose erased profiles still holding a consent; the rest
  kept old Version rows with name, e-mail, phone and ID number, and their bookings' `booker_*`, their
  payment links' `guest_*` and those records' Version rows were never scrubbed. p48 finishes every
  erased profile (marker set): consent withdrawn, date of birth, gender, tags, preferences and identity
  fields cleared, `erase_traces` run (now re-runnable, reporting what it changed); `guest.erase` is
  audited (reason p48) only for a profile where something was left.
- *Low:* the `source == target` check compared strings (`g-00001` passed against `G-00001`, and the
  profile merged into itself): canonical names (`_lock_pair`). p45 found erased profiles by their notes
  text: the marker. `_records_hotels` ignored a linking DocType without a `property` column: a record of
  such a DocType now refuses the merge for anyone but a platform administrator.
- Tests: `test_crm_third_review` (21) and changes to `test_crm_privacy_review` (the tracking and mailing
  tests follow M-6: a timeout undoes only the step, a deadlock is raised, with the server setting mocked
  both ways; p45's erased profile has the marker, a look-alike with the notes text is left alone); the
  p48 registry entry in `test_patches`. The concurrency tests of H-1 need a second connection that
  commits what another request would commit meanwhile, after this transaction's snapshot: they run only
  on a disposable site (`tex_disposable_test_site`: CI's throwaway site, `disposable_test.sh`) and are
  skipped on the shared one. Fail-first on main `f855850` and its schema (the new tests added): on the
  shared site 13 of the 14 that run there fail or error, each on its finding (a booking while the funnel
  is held: "Lock wait timeout exceeded" out of `search`; the comments: "Comment was deleted with the
  duplicate"; the legacy merge and the record naming no hotel: "PermissionError not raised"; the erased
  profile: never marked; the purge, the records, the merge copies and p48: missing); the index test
  passes there only because the site kept the indexes of an earlier migrate with the fix. On a
  disposable site made with main, all 7 concurrency tests fail: the booking committed during the merge
  stays on the deleted duplicate; its hotel is not checked; a duplicate merged elsewhere meanwhile is
  merged again; a redemption spends points spent meanwhile ("ValidationError not raised"); a profile
  gone meanwhile is redeemed against as "Not enough points"; `resolve_guest` and a ledger insert take no
  lock; a booking for a profile merged meanwhile gets the deleted profile. In `test_crm_privacy_review`
  the tracking and mailing tests (a timeout raised) and p45 (the look-alike loses its consent) fail. E2E:
  `crm-profile`, `crm-merge`, `crm-admin` and `booking` pass twice in a row on a server running this
  tree.

## ADR-057 Restrictions refuse a change as they refuse a sale, for what it newly takes; a minimum basket is the whole booking's
**Context.** G-48 (R-16) and G-84 (R-20, R-29).
- A modification — staff, a guest on the manage page, a paid or approved guest change — only
  *warned* about restrictions: an extension into a stop sell, a shortening below the minimum
  stay or a move of the arrival onto a closed-to-arrival day was sold. A guest could book a long
  stay and then shorten it below the minimum.
- R-16 lists a booking window next to the minimum and maximum advance (days before arrival,
  already modelled and editable). Cells needed a room type (no hotel- or market-level cell) and
  could name one sales channel only: no "Booking Engine", "Call Center" or "both" scope.
- A coupon's `min_basket` was compared with each room's basket. Rooms of 802.50 and 321.00 EUR
  both missed a 1,000 EUR minimum they reach together (1,123.50); a change of room 2 of a
  booking that had the coupon lost it on room 2 as soon as room 2 alone was below the minimum.

**Decision — restrictions (G-48).**
- *Booking window.* `book_from` / `book_to` on a cell are sale dates: the night is sold only on a
  booking made inside them. It is checked per night, like a stop sell (a sale-date window on the
  arrival alone would let a stay that starts before the window sell the window's nights). The
  minimum / maximum advance and release stay arrival rules counted from the sale date.
- *Levels.* A cell without a room type is hotel-level, or market-level with a market; the grid
  shows it on a first row, "All room types", and edits it (`hotel_level`: restrictions only;
  inventory and rates stay per room type). Every room row shows what applies to it, whatever the
  level it is set at.
- *Channel scope.* A cell names one sales channel or a `channel_scope`: "Booking Engine", "Call
  Center" or "Booking Engine + Call Center", never both. A sales channel belongs to the Booking
  Engine when a booking site sells on it (`WEB_CHANNELS`: DIRECT_WEB, META) or its channel group
  is "Booking Engine"; to the Call Center when its group is "Call Center"; API, B2B and OTA
  channels are neither, so a surface cell never restricts them. Specificity weights never tie:
  contract 32, room 16, rate plan 8, market 4, then the channel dimension — a sales channel 3,
  one surface 2, both surfaces 1, all channels 0. For cells stored before, the order is the same
  as ADR-008's. The scope key appends the channel scope only when it is set, so every stored cell
  keeps its key (p38 verifies them: 0 re-keyed on the dev site).
- *A change is checked like a new booking, for what it newly takes* (`restrictions.evaluate_change`),
  as G-49 checks inventory only on the nights a change newly takes (ADR-048):
  - with the same product (room type, contract, market, rate plan; the channel never changes)
    the nights the stay already holds are its own: a stop sell or a booking window on them never
    refuses the change; a new night is checked;
  - arrival rules (closed to arrival, arrival stop sell, release, minimum / maximum advance) apply
    when the arrival changes; departure rules (closed to departure, departure stop sell) when the
    departure changes;
  - the length of stay (minimum / maximum) is judged on the new stay when its dates change: a
    shortening below the minimum is refused;
  - another product (room type, rate plan, market or, on the CURRENT basis, another contract) is
    a new sale of the stay: every night, its arrival, departure and length are checked;
  - the past is not sold again: a night before the sale date is never judged, and neither is the
    arrival of a stay under way — an in-house guest moved to another room or rate is judged on
    the nights still to come (and on the length only when the dates change);
  - a change of neither dates nor product (occupancy, extras, a code) is not checked.
  The sale date is today's; a guest's stored change (paid, or approved by staff later) is judged
  as of the time it was priced, like its price. The proposal lists the `restrictions` it breaks
  and is not `sellable`. The guest's manage page, a guest's submit, a paid guest change applied by
  the job (then Failed and refunded, like a stay sold out since) and a staff approval of a guest's
  request are all refused.
- *Override.* Staff applying their own proposal may sell it anyway with `override_restrictions`
  when they hold `restriction.edit` at the hotel — who may lift the restriction for every guest
  may lift it for one stay; no new capability. The reason is required, the revision's changes
  record `restrictions_overridden` and `reservation.restriction_override` is audited with the
  restrictions and the revision. Never on a guest's path, never on a staff approval of a guest's
  request. New bookings keep no override (as before).
- *Channels.* A channel's booking or change that breaks a restriction is accepted with a warning
  and the `channel.overbooking` audit event (ADR-039: the guest holds the channel's
  confirmation); a change is checked for what it newly takes. The ARI a channel gets closes a
  night outside its booking window as of today's sale and closes to arrival a day that release
  or the advance days refuse today; `restriction_boundaries` queues those days at the site's
  midnight (the daily resync compares the horizon later anyway). The portfolio's restriction
  alerts name a cell's channel scope.
- Legacy PMS writes at a TEX hotel stay outside restrictions (ADR-048, ADR-052: they are refused
  or imports).

**Decision — minimum basket (G-84).**
- *Basket.* A room's basket is its accommodation before promotions plus its extras, in the sell
  currency, as before; its quote records it to 6 places (`basket`). A SELL-stage promotion or
  coupon compares its minimum (converted into the sell currency and FX-recorded, ADR-051) with the
  booking's basket — the sum of the rooms' recorded baskets — when the room is priced in a booking
  of several rooms, else with the room's own (exactly as before, so a single room's price never
  changes). COST-stage contract offers stay per room: they are supplier terms in the contract's
  currency and the rooms of one booking may be on different contracts, so their refusal never
  asks for the rooms to be priced together.
- *Booking-level quote step.* `engine.price_together` / `booking_pass` (pure; the one rule the
  engine and the quoting service use): every room is priced alone; when a minimum refused a
  SELL promotion (`rule` MIN_BASKET, `minimum` recorded) and every room is sellable in one
  currency, every room is priced again with the booking's basket, recorded in its request
  (`booking_basket`, `booking_rooms`) and explained (`BOOKING_BASKET`); those quotes are the
  answer. The basket is taken before promotions, so the second pass is final. ADR-029 still
  holds: a fixed booking discount is granted once, on room 1; a percentage is the same share of
  every room.
- *Where.* The booking engine and the CRS quote the rooms of a booking together
  (`public.quote_rooms`, `crs.quote_rooms` → `quoting.create_quotes`; a room that cannot be sold,
  or whose rate is no longer on sale, answers with its reasons). A search prices an offer that
  holds every requested room on the booking's basket; its "from" price is one that can be booked:
  such an offer's total, or the cheapest room of each party priced on its own (a mixed choice,
  quoted together, can only cost less). `create_booking` sells only the price
  the rooms have together (`booking.check_booking_basket`): rooms priced together are booked with
  exactly those rooms (their baskets must add up to the recorded one), and rooms priced alone (a
  client quoting one room at a time) are refused when a promotion their own basket missed would
  qualify on the booking's basket — "quote the rooms of this booking together". A price is never
  booked other than the one shown.
- *Changes.* A change of a room is judged on the booking it makes: the room's new basket plus the
  other live rooms' as they are priced now (their locked snapshots; `modification.booked_price`,
  also used by the simulator). A change that keeps the booking above the minimum keeps the
  discount; one that takes it below loses it on the changed room. Rooms that are not changed keep
  their locked price, discount included: a change never reprices another room (price lock,
  ADR-010), so cancelling or shortening room 2 never takes room 1's discount away. The historical
  simulator judges a room with the other rooms as recorded with it when it was last priced, so its
  answer for a past moment never changes (ADR-054). Add-ons sold after the booking are priced on
  their own (ADR-034) and are not part of a basket.

**Consequences.**
- A change the restrictions refuse now needs `restriction.edit` and a reason; a change the
  restrictions allow is unchanged. Proposals carry `restrictions`,
  `sellable_ignoring_restrictions` and `restriction_override` (the modify drawer offers "Sell
  despite the restrictions").
- A multi-room booking made from room quotes of an older client (one quote per room) books as
  before unless a refused minimum would qualify on the booking; then it is refused with the
  reason. Quotes made before the deploy carry no `basket`: their basket is read from their totals.
- The channel ARI fingerprint changes where release or the advance days closed an arrival: those
  days are pushed once as closed to arrival.
- Tests: unit `test_restriction_rules` (20: booking window, levels, channel scopes and their
  ranking, the changed-stay rules, a product change and a stay under way, the ARI helpers; the
  17 written first fail first on `b2011bc`, the two added by the review error on the code before
  it) and `test_booking_level.TestBookingBasket` (12; all fail first, the cost-stage one on the
  code before the review); integration `test_restrictions` (25: booking engine, CRS / Call
  Center, each rule, the booking window, the scopes, staff changes, an upgrade of a stay under
  way, the override and its audit, guest self-service, channel bookings and changes, the ARI and
  its midnight queue, the grid, the portfolio alert, p38; 18 of the first 22 fail first on
  `b2011bc` — the other 4 cover enforcement that already held — and the review's two fail on the
  code before it) and `test_commercial_flows.TestBookingBasket` (10: quoted together, below the
  minimum, the search, rooms quoted alone or booked apart refused, changes keeping or losing the
  discount, the unchanged room keeping it, the simulator's recorded booking, the Call Center; the
  first 9 fail first on `b2011bc`, the simulator's on the code before the review). E2E
  `restrictions-grid.spec.ts` (hotel-level booking-window cell for the Booking Engine + Call
  Center).
- Review (a code review of the branch before merge): a product change for an in-house guest was
  judged on its past (fixed: the past is not sold again); a stored guest change was judged on the
  day it was applied (fixed: as of its pricing time); a cost-stage minimum was treated as
  booking-level (fixed); the search's "from" price could assume a basket no mixed choice reaches
  (fixed); the simulator read the other rooms as they are now (fixed: as recorded); grid
  keyboard and empty-state details and the portfolio alert's scope (fixed). Kept by decision: a
  multi-room booking of rooms quoted one by one is refused when a refused minimum would qualify
  (clients quote the rooms of a booking together); staff approving a guest's request cannot
  override restrictions (they make the change themselves).

**Review follow-up (an independent review of G-48 / G-84 after merge; branch `fix-restr`).**
The review found one High (money), two Medium and five Low findings; all are fixed, each with a
test written first. No schema change: no patch (p44 unused).
- *H1 — a discount kept on untouched rooms after the booking drops below the minimum.* Shortening
  or cancelling room 2 (or removing an extra its basket counted) took the booking below a
  promotion's minimum; room 2 lost the discount, room 1 kept it under its price lock, so the
  booking was sold at a price its rooms do not have together (the old test asserted it).
  **Decision: clawback, by default** (staff approval routing was considered: it leaves the same
  question to a person, delays the guest's change and still needs the amount; the clawback is
  deterministic, explained and shown before the guest confirms, and never reprices a locked room).
  - A room granted a promotion only on the booking's basket (its own basket is below the minimum)
    records what it would cost without it: `minimum_baskets[].forfeit` (total), `forfeit_net`
    (before added tax) and `forfeit_tax`, priced by the engine without that one promotion,
    everything else the same, never below zero (an exclusive promotion replaced by a better one
    forfeits nothing), and explained (`BASKET_FORFEIT`).
  - A change or a cancellation judges each promotion again on the basket of the live rooms it
    covers after it. The untouched rooms keep their locked price; the changed (or cancelled) room
    carries the forfeits of the rooms whose discount is no longer earned (`pricing.basket.clawback`,
    pure): an explicit `BASKET` line naming the promotion, `totals.basket_clawback` (in total,
    subtotal, tax and margin), one `BASKET_CLAWBACK` explanation step per promotion naming its
    minimum and the covered basket before and after, the revision's `changes.basket_clawback` and
    the audit event `reservation.basket_clawback`. A cancellation's charge is the rate's penalty on
    the room's own price plus that share (`booking.cancellation_penalty`, its basis says so);
    waiving the penalty does not waive the share.
  - Every path: staff / CRS modifications, the manage page (`manage_propose` returns
    `basket_clawback`, shown above the settlement; the cancel dialog shows it in the fee), guest
    changes paid or approved later (they re-derive the proposal, so what is paid, or the refund,
    includes it: a refund shrinks), an extras change counted in the basket, staff and guest
    cancellations (the CRS cancel dialog says it is not waived). Add-ons are not in a basket. A
    channel's booking is priced by the channel (ADR-039, G-69): not affected. The "rate's terms"
    rule for a guest's lower price (`penalty_applies`) reads the rate's penalty only.
  - A ledger keeps the booking whole: what a room carries per promotion is recorded with it
    (`basket_clawback` in its snapshot; a cancelled room's with its cancellation charge), so each
    promotion's forfeits are owed once per booking. A later change of any room charges what is owed
    less what other rooms — live or cancelled — carry, and credits what they carry that is no longer
    owed: the booking reaches the minimum again, the room paid for now pays its own full price, or
    it is cancelled. A cancellation can therefore be a credit (a negative charge): cancelling both
    rooms of a booking whose first cancellation carried the other's discount owes nothing.
  - Limits, recorded: two minimum-basket promotions lost at once are each priced without that one
    promotion (the other kept), so their sum can differ from the room priced without both (two
    sequential percentages overlap); a no-show is not a change (the room leaves the
    live rooms without a share of its own); a staff price override on a change keeps the share as
    computed in the room's record.
- *M1 — the "from" price could not be booked.* Priority and exclusivity decide which promotions
  apply, so pricing the rooms together can raise a price: 5 % exclusive (priority 10) from 250 and
  15 % (priority 1) cost 255 alone and 285 together. **The booking pass can raise a price** (the
  hotel's promotion ranking decides, as for one room). The search's "from" price is the sum of the
  cheapest room of each party priced alone only when no promotion's minimum refused any of those
  rooms and their room types have that many rooms free; else the cheapest offer holding every room
  at its total together, when its room type has that many rooms free (`quoting._from_total`).
- *M2 — rooms a promotion does not cover counted in its minimum.* A minimum is now the last check
  of a promotion (refused for its basket means eligible on every other check), and each promotion
  is compared with the basket of the booking's rooms eligible for it
  (`engine.eligible_baskets`): the request records it per promotion (`booking_baskets`, next to
  the whole booking's `booking_basket` / `booking_rooms`), the explanation names it
  (`BOOKING_BASKET_PROMOTION`), each quote lists its `minimum_baskets` (the promotions with a
  minimum it is eligible for: minimum, basket judged, rooms, qualified, applied, forfeit), and the
  booking check, the change path and the clawback use the same baskets.
- *L1 — length rules refused changes toward compliance.* With the same product and arrival (or a
  stay under way) a minimum stay refuses a change only when it shortens the stay, a maximum only
  when it lengthens it; a minimum stay counted through a night the stay did not hold is that
  night's rule, newly taken. Leaving early is not a sale: an in-house guest is never kept by a
  minimum stay. A new arrival or another product not begun is judged in full, as before.
- *L2 — `quote_rooms` input.* The rooms and their extras are checked for their shape
  (`quoting.room_items`, `extra_items`): anything else is a clean validation error, never an HTTP
  500 with an Error Log (also `public.quote` and `crs.quote_rooms`). Each room quoted together
  counts as a quote against a per-visitor budget of `WRITE_LIMIT` rooms per window, besides the
  request's own limit.
- *L3 — "as recorded" depended on whether a second pass happened.* Every room of a booking of
  several rooms records the booking in its request (total, rooms and per promotion), priced again
  with it whenever a promotion with a minimum could see it, so a recorded request always prices to
  its quote; the simulator reads the per-promotion baskets (a snapshot recorded before counts the
  other rooms for every promotion, as it did).
- *L4 — old snapshots counted add-ons in the basket.* A price recorded before G-84 has no
  `basket`; its fallback now subtracts the extras of add-ons sold after booking.
- *L5 — oversized ARI ranges.* `restriction_boundaries` queues boundary days in clusters (days at
  most 7 apart), and a waiting ARI job takes in a new range only within 7 days of its own; a range
  further away is a job of its own (`push_job` still pushes only days that changed).
- *Test gaps closed:* restrictions on a staff approval of a guest's request (`_proposal`), on a
  paid guest change applied by the job (`_from_payment`: Failed and refunded) and the `_sale_at`
  pin (a stored proposal judged on the day it was priced); the H1 cases (shortened below the
  minimum, a cancelled room, an extra removed, the fixed discount on room 1 charged to the cancelled
  room 2, a change staying above the minimum charging nothing, the refund of a paid booking).
- *E2E `restrictions-grid.spec.ts` on main:* clearing a cell that did not exist inserted an empty
  scope-less duplicate, and a site whose table lacked a G-48 column dropped the value silently. A
  clear now updates or deletes the existing cell (an all-empty cell is deleted, never left), the
  scope key is computed from the document, and a value the table cannot hold is refused ("run
  bench migrate"); the spec picks a free night and cleans up, so it can run again on a shared site.
- Kept by the reviewer: server-only baskets, currency and market mixing, Decimal throughout, the
  booked-apart refusal, ADR-029's room-1 rule, price locks, step splitting, override gating, the
  site's day, channel-scope sources, grid tenancy, precedence, p38 and the ARI boundary maths.

## ADR-058 A sold stay's contract terms are a verified reference; every TEX patch is tested and converts or grants once
**Context.** G-73 (R-05) and G-76 (R-56).
- G-73. A reservation's price-locked snapshot is the quote's result. It names its contract
  version and the version's payload hash (`contract.version`, `contract.payload_hash`, also
  `Reservation.tex_payload_hash`) and holds the explanation, night by night. It does not copy
  the periods and occupancy rules that priced the stay. Nothing compared the recorded hash when
  the version was loaded again. `load_terms` only checked that a payload hashes to its own row's
  hash, so a payload edited below the controller with its hash recomputed (a hand edit, a restore
  of another backup) repriced a sold stay on other terms. Probe on the base commit: a stay sold
  at 400.00, its version's room prices doubled and rehashed; the ORIGINAL_VERSION reprice and
  the simulator priced it at 800.00. The quote's sale time was known only as `request.sale_at`.
- G-76. Only p05/p06 and later feature patches had tests. p01–p04, p07–p09, p11, p13, p14, p18,
  p20, p23, p33 and p34 had none, and no test ran the chain from a Kamra database. Patches run on
  a shared dev site in tests. DDL there (`reload_doc`, `add_index`, the custom-field sync)
  commits the open transaction and leaked test rows once.

**Decision (G-73).**
- *References, not copies.* Measured on the dev bench: 202 published payloads average 2.8 KB
  (largest 8.2 KB); 705 snapshots average 14.4 KB (largest 22.6 KB), most of it the explanation.
  - The explanation already records, for each night, the period (code, name) and every rule
    that won (id, level, source, label, values). The sold price is re-explained from the snapshot
    alone.
  - A copy would add only the definitions (period dates and weekdays; a rule's target, position,
    band and combination). Repricing a changed stay (other nights, room or party) needs the rest
    of the payload anyway.
  - Copying whole payloads would add 3–8 KB per reservation here, far more for large contracts,
    and duplicate an immutable record. A copy would still need the hash to show it is the
    published one.
  - So the snapshot keeps the reference, and the reference is made safe:
    - published versions cannot be edited or deleted (controller);
    - `load_terms` refuses a payload that does not hash to its row's hash;
    - `load_terms(version, expected_hash=…)` now refuses one that is not the payload the sale
      recorded.
- *Where the recorded hash is required.* Whatever loads the snapshot's own version for a sold
  stay passes the recorded hash (`services/sold_terms.py`: the snapshot's `payload_hash`, else the
  reservation's column for the same version):
  - a reprice on any basis (ORIGINAL_VERSION and ORIGINAL_SALE_DATE; CURRENT and
    HISTORICAL_SALE_DATE while the version picked is still the sold one), on propose and on apply;
  - the historical simulator;
  - extras added after booking.
  A new version is not the sold one. It has no recorded hash to match and prices on its own
  frozen, integrity-checked payload.
- *Refusal.*
  - `contracts.PayloadMismatch` (a `ValidationError`). The message names the reservation, the
    version and both hashes, and says the price stays as sold. The locked price never moves.
  - A payload failing its own integrity check is the same refusal. Before, it was a plain
    `ValidationError`, never audited.
  - Each refusal is audited as `reservation.reprice_refused`: use, basis, version, sold version,
    recorded hash, found hash, reason.
  - The refused request is rolled back (Frappe rolls back on an exception; a GET never commits),
    and an event written in its transaction would go with it. So `audit.audit_refusal` queues a
    job at once (not after a commit that never comes). The job writes the event in its own
    transaction, as the refused user. Tests run it inline.
- *The sale time is explicit.*
  - A booking snapshot records `priced_at` (the quote's sale time, when the engine priced it)
    next to `accepted_at` (when the booking took it).
  - A modification's snapshot records its basis's sale time as `priced_at`, next to
    `original_priced_at`.
  - The Original revision keeps the same record. Its `basis_sale_at` is the quote's sale time
    (before: the booking time), like every later revision's, whose basis time is its pricing
    time.
  - `priced_at()` and `original_priced_at()` read the key first. A snapshot written before falls
    back to its request's sale time.
- *No schema change and no data change for G-73.* Existing snapshots keep repricing unchanged. Their hashes are checked the same way (every TEX snapshot has always
  carried `contract.payload_hash`). A channel's snapshot names no TEX contract; it is not
  repriced by TEX (unchanged).

**Decision (G-76).**
- *Every patch, four properties.* `test_patches` checks each patch `patches.txt` lists:
  - (a) its behaviour on representative pre-patch data. The `BEHAVIOUR` registry names the test,
    here or in the patch's feature module. A meta-test fails for a patch without one, a patch
    file not listed, or a list out of order.
  - (b) running it again changes nothing, whether at once (a failed migration retried) or forced
    later over what administrators changed since. Every TEX table, and the legacy rows patches
    write, is digested between runs; `modified` is ignored.
  - (c) it never changes a published payload or hash, nor a sold stay's amounts, currency,
    commercial record, snapshot, revisions or lock.
  - (d) the whole chain runs on an empty site, twice.
- *The upgrade test.* `TestUpgradeFromKamra` builds a Kamra-shaped database inside the test's
  transaction: two legacy hotels (EUR, TRY) with no group, users with and without a property
  restriction and a disabled one, legacy stays in six statuses, a voucher and an experience. It
  runs the chain in order and checks what the upgrade leaves:
  - one Default Enterprise and hotel group; seeded masters; profiles equal to their defaults;
  - access made explicit, then strict tenancy: nobody gains or loses a hotel, and a new user
    sees none;
  - the standing legacy stays locked at their amounts, and the lock holds;
  - the voucher a draft promotion, the experience a live extra;
  - guest stats in the hotel's currency;
  - both hotels onboarding;
  - a second chain run changes nothing.
- *Safety.* The patches' DDL never runs in a test. `sandbox()` stubs `reload_doc`, `add_index`
  and the custom-field sync. It refuses (and records, in case a patch swallows the error) any
  commit, DDL or transaction statement. File is kept from moving files on disk. The empty-site
  deletes run under the same guard inside the test's transaction. After the rollback, cached
  documents are dropped.
- *Patch changes: once, never by guess.* Found by the tests, each fixed:
  - First-run-only steps (`setup.ran_before(__name__)`; Frappe writes the Patch Log row after a
    patch succeeds and never re-runs a logged one unless an operator forces it). A forced re-run
    no longer changes what administrators changed since. The first run is unchanged.
    - p02: a re-run gave every hotel to a user added after the upgrade without a property
      restriction.
    - p04: a re-run locked stays that hotels outside TEX sold at their Desk after the upgrade.
    - p08, p12, p17, p18, p23, p29: a re-run gave back a capability an administrator had
      removed. p29 also gave back `price.any_channel`, which binds staff to channels (ADR-050).
    - p17: a re-run turned a loyalty program set to "cannot redeem" (0) into 100 %.
    - p12's extras step was guarded already.
  - p01 (`setup.ensure_enterprise`) attached a hotel without a hotel group to whichever
    enterprise the database returned first. On the dev bench that was the demo tenant's group.
    Now the backfill never guesses:
    - no enterprise: Default Enterprise and Default Hotel Group;
    - one enterprise with at most one group: that group;
    - otherwise the hotel is printed and stays outside TEX until an administrator adds it to its
      group.
  - p09 (`crm.refresh_guest_stats`) counted the legacy stays of a TRY hotel as EUR and summed
    them with EUR money. It also counted inquiries, quotes and waitlist entries as stays. A stay
    now counts as the CRM facts count it (not Inquiry, Waitlist, Quoted, Cancelled or No Show).
    A legacy stay's amount is in its hotel's currency.
  - p19 and p24 audited their reports again on every run. A report is now written once per record
    and values (`audit.recorded`).
  - p36 set every hotel in TEX live, including every hotel of a Kamra database that p01 puts in
    a hotel group in the same migration. That stopped their Desk before TEX could sell anything,
    what ADR-052 M3 set out to avoid. p36 now sets live only the hotels TEX sold (a published
    contract version, or a TEX booking). A hotel in TEX that TEX never sold is onboarding until
    an administrator sets it live. This amends ADR-052's "every hotel already in TEX": p36 ran
    already on the sites that had TEX, so it changes nothing there.
  - p03, restructured for testing, same behaviour: `setup.TEX_INDEXES`, `missing_indexes()` (a
    read) and `ensure_indexes()`, which creates only the missing ones. `add_index` skipped
    existing indexes before too. A test checks every index's columns exist and that this
    migrated site has them all.
  - That test found two indexes gone from the dev bench and a third about to go:
    - `tex_booking_idx` (`Reservation.tex_booking`, from p03): gone;
    - `tex_comm_email_queue` (`TEX Communication.email_queue`, from p23): gone;
    - `tex_xalloc_res` (`TEX Extra Allocation.reservation`, from p13): still there only because
      that DocType has not been synced since.
    - Cause: Frappe drops a single-column index on a field without `search_index` whenever it
      syncs that DocType again. `add_index` keeps no property setter during a migration. So
      p18's reload of Reservation, and every later migration that synced these DocTypes, removed
      them.
    - Fix: the three are composite now: `tex_booking` + `tex_room_index` (`tex_booking_room`),
      `reservation` + `status` (`tex_xalloc_res_status`), `email_queue` + `status`
      (`tex_comm_queue_status`). Frappe's sync leaves a composite index alone. The new patch p39
      creates them where missing.
    - Every entry of `TEX_INDEXES` has at least two columns (tested). An old single-column index
      still present is left to Frappe's next sync.
    - Checked on the dev bench after the migration:
      - p39 forced again created only the index still missing (`tex_xalloc_res_status`);
      - a forced sync of Reservation, TEX Extra Allocation and TEX Communication
        (`reload_doc(force=True)`) dropped `tex_xalloc_res` and kept every composite index.
- *Not changed.* Patch order and names (p39 is new: three indexes, no DocType change). p05 and p35
  still write an Error Log line on each run for a voucher they cannot copy or a payload that
  fails its hash: a log, not data.

**Consequences.**
- A payload that no longer hashes to what a sale recorded stops repricing, simulating and
  add-ons for that stay, audited, until an administrator restores it. New sales on a version
  whose row hash was recomputed are not affected by this check. A published version's payload
  cannot be changed through the application.
- An operator can force a TEX patch again safely. A first run still does everything it did.
- A Kamra site upgrading to TEX keeps selling at its Desk; each hotel goes live in TEX when an
  administrator says so. A site with several tenants reports hotels without a group instead of
  placing them.
- `MIGRATION_PLAN.md` lists every patch with what it does, whether it runs once and where it is
  tested.
- Tests:
  - G-73: `test_snapshot_integrity` (9; on the base commit 3 fail, 4 error and 2 pass, the
    back-compat and new-version cases);
  - G-76: `test_patches` (21). On the original patches 8 failed and 1 errored (the p03
    restructure). With the fixes, the p03 test then found the missing and fragile indexes (fixed
    by p39);
  - updated: the p29 and p17 tests start from a site where the patch never ran, and p36's test
    expects a TEX hotel that TEX never sold to stay onboarding.

### ADR-058 review follow-up (branch `fix-mig`)
An independent review of G-73 and G-76 found 1 Critical, 1 High, 4 Medium and 6 Low issues. All
are fixed, each with a test that fails first.

- *C1 (Critical): an interrupted migration test could commit a wiped site.*
  - The failure: on Ctrl-C, unittest skips tearDown and the cleanups, and Frappe's `run-tests`
    then commits the connection (`_cleanup_after_tests`). The empty-site tests had deleted every
    TEX table, hotel, stay and guest in that transaction, and the per-patch tests had deleted
    profiles, markets and Patch Log rows. All of it would have been committed to the shared site
    (the review found the site data intact: it never happened).
  - Fix, part 1 (`test_patches.refuse_commits`): every migration test (`PatchCase`) refuses to
    commit from its setUp until its own rollback, whoever asks:
    - `commit()` raises, and so do `sql_ddl` and `add_index`, which commit first;
    - a bare COMMIT statement raises;
    - DDL or START TRANSACTION after a write raises already (Frappe's `ImplicitCommitError`).
    A cleanup lifts the refusal after the rollback. An interrupted run never reaches it: it ends
    on the refused commit, and MariaDB rolls the dropped connection back.
  - Fix, part 2: the tests that change the whole site (empty it, run every patch over it, the
    Kamra upgrade) run only on a disposable site. This also fixes M4.
    - The site config must set `tex_disposable_test_site`, and `empty_site()` refuses to run
      anywhere else.
    - On the dev bench, `/home/user/bench/scratch/disposable_test.sh` creates a site (38 s),
      runs the modules there and drops it. CI's site is made for the run, so CI sets the flag.
  - Proof: `/home/user/bench/scratch/c1_sigint.sh` writes one harmless marker ToDo row in a
    `PatchCase` test and sends SIGINT to the run's Python process.
    - Before the fix, the marker was committed; the script deleted it again.
    - After the fix, it was not committed: the run ended with `CommitRefused` in
      `_cleanup_after_tests`.
- *H1: `setup.ran_before` read the Patch Log differently from Frappe.*
  - `bench migrate --skip-failing` logs a failed patch as `skipped`, and Frappe runs it again next
    time. `ran_before` saw that row, so the re-run did nothing, and Frappe then logged it as a
    success. p02's grants, p04's locks, the capability grants, p12's extras and p17's conversion
    were silently never done.
  - A patch line re-issued with a suffix (`<module> #<date>`) is logged under that line, and
    `ran_before` missed it.
  - Now a run is a row with `skipped = 0` whose patch is the module or the module followed by a
    space (`LIKE` with `_` and `%` escaped).
- *M1: p36 runs once.* A hotel an administrator put back to onboarding (`legacy.set_live`,
  audited `hotel.go_live_undo`) stays there on a forced re-run.
- *M2: p01's data steps run once.* These are the profiles, markets and channels, TEX Settings,
  the enterprise backfill and the PMS visibility. On a re-run only the custom field is ensured.
  A forced re-run had recreated deleted markets and channels (which changes market resolution),
  reset the brand name and the PMS visibility, and on a single-tenant site pulled a hotel kept
  outside TEX into the tenant's group, giving that group's and enterprise's grants access to it.
- *M3: no test runs a real DocType sync.* The p28 and p29 tests ran `reload_doc` for real. When
  a DocType's JSON differs from its `migration_hash`, that sync runs DDL and commits the test's
  rows. Both now run in `sandbox()`. A static test (`test_no_test_runs_a_patchs_schema_sync_for_real`)
  finds any test that runs a patch with a schema step outside `sandbox()`, `migrate()` or a
  mocked `reload_doc`.
- *M4: whole-site tests on a disposable site only* (see C1). On a shared site, even rolled back,
  their deletes and whole-table updates held next-key locks that other sessions' saves waited on.
  The per-patch tests stay on the shared site: each is a short transaction on the rows it needs.
- *L1:* the migration digest names `__Auth` rows by (doctype, name, fieldname) and Singles rows by
  (doctype, field). A value, such as an encrypted password, is only hashed; failure messages
  print names.
- *L2: guests get a guest-safe refusal.*
  - Guests reach the refusal through the manage page's change and extras. It is also stored as
    the error of a guest's change applied later (`guest_changes._fail`).
  - They are now told "This booking cannot be changed online right now. Please contact the
    hotel."
  - Staff (the permission-checked propose, their own proposal's apply, the simulator, staff
    extras) and the audit event keep the version, the hashes and "ask an administrator".
  - A staff approval of a guest's stored request gets the guest-safe text; the detail is in the
    audit trail.
- *L3: `PayloadMismatch` names the version that failed and its row hash.* Contract selection
  loads every contract on sale, so the version that failed can be another contract's. The audit
  records it (`version`, `found_hash`) next to the stay's `sold_version`.
- *L4: the refusal audit is resilient and throttled.*
  - A queue that cannot be reached (Redis down) no longer replaces the refusal with a 500. It is
    logged (the action and the record only, in the file log and the Error Log).
  - The same refusal (stay, use, basis, version, hash) is audited once an hour. This is checked
    before queueing and again in the job, so repeated clicks on a refused stay are not one job
    and one event each.
- *L5:* `payments.gated_accounts` lists open charges by name, so p19 does not report an account
  again when a charge is touched.
- *L6:* `setup.missing_indexes` logs and skips an index whose table cannot be read. One broken
  table no longer stops p03, p12, p13, p16, p18, p23, p39 or `after_install`.
- *Unchanged.* No schema change and no new patch (p43 not needed). p40, from main, uses
  `ran_before` and keeps its re-run test.
- *First run on a fresh site:* it found one test relying on the shared site's data (the p01
  multi-tenant test assumed two enterprises; it now creates its second tenant).
- *Tests (fail first on `aa742c0`):*
  - `test_patches`: 8 fail, 1 error (H1 ×3, M1, M2, M3, L1, L5; L6);
  - `test_snapshot_integrity`: 5 fail, 1 error (L2; L3 ×2; L4 ×3: the throttle twice, the queue error);
  - C1: the SIGINT simulation, before and after.

## ADR-059 Reports reconcile: contract cost against the accommodation it was marked up to, money per currency, one selection for every view
**Context.** G-46 (R-14, R-48). The production report set gross revenue (the stay's total:
accommodation, extras and taxes added on top) against the margin the engine stores, which covers
the accommodation only, and divided that margin by gross revenue: a stay with cost 750.00, an
accommodation price of 802.50 (+7 % markup), a 40.00 transfer and 80.25 VAT on top showed a margin
of 5.69 % (52.50 / 922.75) instead of 6.54 % (52.50 / 802.50), and "cost + margin" matched no column
the report showed. The totals had no cost or margin. There were no promotion, cancellation, payment,
extras or conversion views, no hotel or group view over several hotels, no market, channel, room or
rate filter, and a stay and a sale window could not be combined. Grouping by guest country read each
guest in its own query. One test covered the report.

**Decision.**
- *The margin, per stay TEX priced from a contract* (`tex_pricing_source = TEX`; channel, imported,
  legacy and manual stays have no contract cost and are kept out of it):
  - contract cost `C` = `tex_cost_amount`: the contract's accommodation cost after COST-stage
    offers, converted into the selling currency at the rate the sale recorded (the same rate as the
    selling price, ADR-051), so both sides are in one currency;
  - accommodation selling price `A` = `C + tex_margin_amount` = the price-locked snapshot's
    `totals.accommodation`: what the markup made of that cost, after accommodation promotions and
    the room's share of booking-level coupons. A modification's manual override is part of it (its
    difference is stored on the margin);
  - margin `M = A − C`; margin % = `M / A × 100` (2 places, half up): over the selling net, never
    over gross revenue;
  - taxes: both sides are on the contract's price basis. The contract's rates, the markup and `A`
    all include the VAT the contract's prices include (`prices_include_tax`, the default), or all
    exclude it; taxes added on top of an exclusive price and fixed levies (always on top) are on
    neither side. No side ever carries a tax the other lacks. Taking VAT out of an inclusive
    contract's cost would need the tax on the cost, which no sale records; a percentage tax scales
    both sides alike, so the margin % is the same on either basis;
  - extras have no contract cost in TEX and are never in the margin; they are reported beside it:
    extras `E` = the snapshot's `subtotal − accommodation` (after coupons, add-ons included);
  - revenue `R` (what guests pay, `tex_total_amount`) = `A + E + T + N`: taxes added on top
    `T = R − A − E` for a priced stay, and `N` the revenue of the stays without a contract cost.
- *Rounding.* A row adds up its stays' exact amounts (prorated to the nights inside the stay
  window: amount × nights inside ÷ nights) and is rounded once to its currency: `R` and `C` half up;
  `A`, `E`, `T`, `N` by largest remainder so that they add up to the rounded `R`; `M = A − C` of the
  rounded figures. A total is the sum of its rows. Every row and every total therefore satisfies
  `C + M = A` and `A + E + T + N = R` to the cent. The database sums DECIMAL columns exactly and
  returns text (`CAST(SUM(…) AS CHAR)`), read with `money.db_dec`; no float anywhere; the API
  returns strings.
- *Currency: grouped, never converted.* Each row has its selling currency (the stay's, else its
  hotel's); totals are per currency and amounts in different currencies are never added. Converting
  with each booking's FX snapshot was rejected: the snapshot records the contract → selling
  currency rate, not a rate into a reporting currency, so a one-currency total would use rates no
  sale recorded. ADR-051 applies where it holds: the cost is already in the selling currency at the
  recorded rate.
- *One selection for every view.*
  - Hotels: one hotel, or a scope (enterprise, hotel group, all) narrowed to the hotels where the
    viewer holds `report.view` (`portfolio.hotels_in`): a group or enterprise never widens the
    scope, and a scope with none of the viewer's hotels is refused without confirming it exists.
  - Dates: a stay window (the nights inside it), a sale window (the TEX sale time, else creation),
    or both at once; at most 800 days each.
  - Filters: market, channel, room type, rate plan, currency (at most 50 values each, always SQL
    parameters, never formatted into SQL), and whether cancelled stays count. A filter a view
    cannot apply is refused, never ignored.
  - Results longer than 1000 rows fold their tail into one row per currency, so the rows still add
    up to the totals.
- *Views.*
  - Production and contract vs selling (`margin`): prorated room nights and money, by any stay
    dimension, the hotel, its group, the stay night (a row is the nights of that day or month; a stay
    counts once, in the row of its first night in the window) or the sale day / month.
  - Promotion: per applied promotion (the snapshot's applied `promotions`): applications, room
    nights and revenue of those stays, and the discount given (the rounded DISCOUNT / COUPON lines).
    A stay with two promotions counts under both, so only applications and discount are totalled.
  - Extras: per extra (the snapshot's EXTRA lines, add-ons included): stays, quantity and amount as
    sold, before booking-level coupons.
  - Cancellation: every booked stay of the selection: cancelled and no-show stays, their nights and
    value, the fees kept, net lost, the cancelled share and the days before arrival.
  - Payment: the bookings with a stay in the selection, whatever that stay's status: value
    (cancellation fees included), paid, balance = value − paid, and the succeeded, refunded and
    pending transactions in the booking's currency; the succeeded payments by method and provider,
    per currency.
  - Conversion: booking-engine sessions in the sale window at the report's hotels: searched,
    quoted, guest details, booked (a booking was made: payment started or booked) and confirmed (its
    booking is Confirmed or Partially Cancelled now); conversion % = booked ÷ searched. It needs a
    sale window; stay, channel, room, rate and currency filters are refused.
  - Promotion, extras and cancellation count each selected stay whole; only production and
    contract vs selling prorate.
- *Permissions.* Every report endpoint declares `report.view` (`require_capability`). Cost, margin
  and the accommodation / extras / taxes split are computed only when the viewer holds
  `price.view_cost` at every hotel of the report: the SQL does not select them otherwise, the keys
  are absent, and the contract-vs-selling view is refused. The fields stay at permlevel 1 (ADR-056);
  reports read them on the server, in aggregate only.
- *Performance.* Each view is one to three parameterised aggregate queries, whatever the number of
  stays: `JSON_TABLE` over the price-locked snapshot for promotions and extras, a recursive calendar
  for stay nights (bounded by the 800-day window, below MariaDB's default
  `max_recursive_iterations` of 1000), the guest's country as a join. The portfolio's scope labels
  and its restriction alerts' room names are read in one query each.

**Consequences.**
- A report's margin is the engine's margin of each stay, and for one stay its margin % is the
  engine's `margin_percent`.
- A hotel whose contracts differ in tax basis adds inclusive and exclusive accommodation prices in
  one row. The margin % is unaffected; the amounts are each stay's own contract basis.
- There is no one-currency (converted) total.
- By stay date, a stay spanning two months is split by night between them (before, it was filed
  under its arrival month).
- Reports scan the report's hotels' reservations: `tabReservation` has no index that starts with
  `property`. An index `(property, check_in_date)` is the next step for large tenants (a schema
  change, not made here; no patch, no schema change in this ADR).
- The dashboard's funnel (R-47) still counts only `booked` events, so bookings that started a
  payment are not in its conversion %; the conversion view counts both.
- Tests: `test_reports` (22). On the base commit 21 fail: margin % 5.69 instead of 6.54, the
  country grouping ran 6 queries for 3 stays against 4 for 1, no endpoint declared a capability, and
  18 errors because the views and filters did not exist. The old production endpoint's test passed
  before and after. E2E `reports.spec.ts`: filters, a view switch, reconciled totals, cancellations
  and 375 px without sideways scroll.

**Review follow-up (2026-09-24, branch `fix-reports`, patch p46).** An independent review of
G-46 found one High issue outside the reports, which predates them, and Medium and Low issues in
the reports. Some claims above were stronger than the tests behind them. All are fixed as follows.
- *High, pre-existing (G-98): contract cost leaked to guests and agents through cost-stage offers.*
  A cost-stage offer lowers the contract cost, so its discount is a cost figure. Example: 49.50 is
  15 % of a contract cost of 330.00. So is the basket it is compared with ("basket 330.00 EUR below
  minimum …"). The guest view (`RoomQuote.to_dict(internal=False)`) kept applied cost-stage
  outcomes. `quoting.strip_internal(staff=True)`, used by the CRS search and reservation for staff
  without `price.view_cost`, kept them all, refused ones included.
  - Every promotion outcome now carries its `stage` (`COST` / `SELL`).
  - The guest view and `strip_internal` (guests and staff alike) drop cost-stage outcomes, applied
    or not. A snapshot written before `stage` existed is judged by its explanation: steps of stage
    `cost_offer` name them.
  - Nothing else in the non-internal payload derives from cost. The nights show the selling price;
    the lines hold only selling-stage discounts; the explanation, `fx` and the internal totals were
    already stripped.
  - A reservation's `tex_promotions` (permlevel 0: read in Desk by every role that reads
    reservations, Front Desk, Finance, Housekeeping included) named the cost-stage offer too. It now
    lists the promotions of the selling price only (`quoting.sold_promotions`, the same test as
    `strip_internal`), at booking and after a change. Reservations written before keep what they
    recorded (no data patch: an offer's id is not a figure, and no site is live).
  - Staff with `price.view_cost` see every outcome with its stage.
  - Paths checked: booking-engine search, quote, rooms quoted together, booking, manage page and
    e-mails; the CRS search (also `ui_crs.search`), quote, rooms quoted together, reservation (also
    `ui_crs.reservation`), a proposed change and the historical simulator; `quotes_summary`, the
    audit trail and revisions carry no promotion outcome.
- *M1 Totals did not depend on the stays alone.* Each row was rounded from exact prorated shares,
  so the totals changed with the grouping, and a fold changed them again. For example, a stay of
  100.00 over 3 nights gave 100.00 by channel but 99.99 by day; over 800 days the drift could reach
  a few currency units. The "rounded once, largest remainder" rule above is withdrawn:
  - each stay's amounts are split over its nights in whole minor units, as the folio bills a
    locked stay (`money.split_evenly`: equal shares, the remainder on the last night);
  - a row adds up whole units, so every grouping and every fold gives the same totals;
  - the database does the split (integer `DIV` per stay, a numbers table as long as the longest
    stay in the window for rows by night);
  - revenue per night is that split of what the guest pays, so it equals the folio's night;
  - extras, taxes, stays without a contract cost, fees and cost are split the same way;
  - the accommodation of a night is revenue less the others, and margin = accommodation − cost.
- *L6 Taxes are the reservation's own.* A manual price scales the reservation's tax
  (`tax_amount`), but it adds the whole difference, tax included, to the stored margin. The report
  took taxes from the snapshot, so an override from 1100 to 990 showed accommodation 890 and taxes
  100 while the reservation holds 90. Now:
  - taxes on top = the reservation's `tax_amount` (its added part, when the snapshot says only part
    of it was added);
  - accommodation = revenue − extras − taxes; margin = accommodation − cost;
  - for an overridden stay this margin differs from the stored `tex_margin_amount`. The stored one
    still holds the tax part of the override; the modification service is unchanged.
- *L5 A cancelled stay counts only the fee it kept* (with cancelled stays included): as revenue
  and as `cancellation_fees`, never as accommodation, cost or margin. The cancellation view shows
  the fees too.
- *M2 Cost-stage offers in the promotion view* are listed only with `price.view_cost` (the
  outcome's `stage`, or the explanation for older snapshots), with their `cost_reduction`: the cost
  discount converted at the rate the sale recorded, rounded per stay. `discount` stays the selling
  discount.
- *M3 Group booking sites.* A hotel-group site records its sessions without a hotel, so the
  conversion view never counted them. Their sessions now count when the report covers every
  enabled hotel of that group. So a viewer who reports on only some of its hotels does not see them,
  and nothing leaks. By hotel, a session is filed under its booking's hotel, or "not set" before a
  booking. The dashboard funnel (R-47) still counts only the hotel's own sites.
- *L7 Conversion counts each session once.* A session counts in the window of its first event
  (its events up to `SESSION_DAYS` = 2 around the window are read). A later stage implies the
  earlier ones (a guest who quoted searched), so no stage exceeds the one before and conversion
  never exceeds 100 %. A sale window starting more than 180 days back
  (`crm.FUNNEL_RETENTION_DAYS`, the funnel's retention) is refused.
- *M5 Full scans.*
  - p46 adds `tex_res_prop_ci` (Reservation: property, check_in_date), `tex_funnel_prop_time`
    (TEX Funnel Event: property, occurred_at) and `tex_funnel_site_time` (site, occurred_at) to
    `TEX_INDEXES`. They are composite, so Frappe's sync keeps them, and a forced re-run creates
    nothing.
  - The by-night rows join a numbers table as long as the longest stay in the window, not an
    800-day calendar per stay.
  - Each user may run 60 reports a minute over HTTP (`report`, `production`, `portfolio`, and
    since the final check of this branch the dashboard and `pace`, which also aggregate stays; one
    budget, `RATE_LIMIT`).
  - The query count per view stays fixed.
- *L2 Payments per transaction currency.* A payment in another currency than its booking, or of
  a booking without a currency, is in the row of its own currency, as in the payments by method.
  The two now agree.
- *L3 The payment view needs `payment.view` at every hotel of the report*, as the margin view
  needs `price.view_cost`. The Payments tab is offered only with it.
- *L4 Refused, not ignored:*
  - `basis` outside production, contract vs selling and cancellations;
  - cancelled stays outside production, contract vs selling, promotions and extras;
  - a grouping for promotions and extras.

  The booking-date help text now says that a stay window also set prorates the value.
- *L1* A scope change clears the room-type and rate-plan filters (they belong to hotels). Found
  by the branch's E2E run: a date typed while the report loaded was sent with the render's other
  date (a filter change re-renders as a router transition that waits for the report), so "from"
  went back to the start of the month once "to" was typed (`reports.spec` failed 2 of 3 runs). A
  typed date now changes that date only; the other is read from the live URL.
  *L8* `filter_options` says when a list was cut at `MAX_OPTIONS` (2000), and the UI says so.
- *Corrections to the claims above:*
  - rows are no longer rounded once by largest remainder: see M1;
  - "every total reconciles" held only by construction: the first tests checked identities the
    code built, and the month test passed only because a 3-night stay split 2 + 1 always rounds
    back. The new tests compare with an independent whole-cent computation, several stays with odd
    cents, every grouping and a fold;
  - the payment view needed only `report.view` (now `payment.view`);
  - "a filter a view cannot apply is refused" was not true for `basis` and cancelled stays
    (now it is).
- *Still open:*
  - production by sale date files a stay, whole, on its original sale day, so a later modification
    or add-on changes that past period;
  - the dashboard funnel does not attribute group-site sessions to a hotel;
  - `portfolio._inventory_alerts` still reads each room pool per hotel (optional L9, not done: it
    needs a batched pool read in the availability repository; a portfolio is bounded by the
    viewer's hotels);
  - a cost-stage *managed* promotion (TEX Promotion, stage COST) with a code or limit records its
    redemption `amount` as the cost discount, in the contract's currency, under the booking's
    currency (`booking._promotions_used`); only Hotel Admin and System Manager read redemptions,
    and limits count redemptions, not amounts.
- *Tests:*
  - unit `test_cost_stage_privacy` (6, one for `sold_promotions`);
  - integration `test_cost_stage_privacy` (4: the booking engine search, quote, rooms quoted
    together, booking, manage page and e-mail; an agent's CRS and `ui_crs` search, quote, rooms
    quoted together, reservation, proposed change and simulator; `tex_promotions` after booking and
    after a change; the revenue manager);
  - `test_reports` review classes (14 new, one for the dashboard and pace throttle; the L2 test also
    covers a booking and payment with no currency; the existing ones updated for L3);
  - `test_patches.TestP03Indexes.test_p46_creates_the_report_indexes`;
  - e2e `reports.spec.ts` (a scope change clears the room filter).
- *Run (branch with main `23767cb` merged; patches p45–p48 in order):* 37 integration modules,
  783 OK (the 3 whole-site patch tests pass on a disposable site, `test_patches` 33/33); 425 unit
  tests; upstream suites 76/76, 13/13, banquet 101; Playwright `reports`, `portfolio`, `booking`,
  `crs`, `manage-money` 16/16 (after `demo_seed.release_test_bookings` released 645 test-run stays
  that had sold the shared demo hotel out on the specs' random dates).

## ADR-060 The entry screens say TEX Engine and offer the source; "/" leads to the admin app or sign-in; the navigation carries R-35's sub-sections
*Amended by the review follow-up (end of this ADR): guests and Desk users are offered the source
too, always of the running version; the sign-in page reads Frappe's answer (two-factor accounts);
a booking site opens under `/tex/booking-engine/sites/`.*

**Context.** Two gaps of the 2026-09-23 audit.
- G-60 (R-01, R-33). The sign-in page said "kamra PMS" and offered English and Arabic only. The
  browser tab said "Kamra PMS", the Desk apps tile "Kamra", and `hooks.py` `app_title` /
  `app_description` described a PMS. `/` was blank: the site's home page is the SPA boot page
  (`kamra`, set by `kamra.install`), whose router is mounted at `/kamra`, so at `/` it rendered
  nothing.
- AGPL-3.0 section 13. TEX Engine is a network service derived from Kamra PMS. Users who
  interact with it remotely must be offered its complete corresponding source. No screen did.
- G-64 (R-35). The navigation had the eleven areas only. Missing: Contract versions, Price
  periods, Occupancy rules, Rate plans, Restrictions and Bulk editor under Rates & Contracts;
  Rooms and Analytics under Booking Engine; Loyalty and Communications as CRM sections;
  Campaigns does not exist.

**Decision.**
- *Names (ADR-001 kept).* Unchanged: the app name `kamra`, the Python package, the Frappe
  modules, DocTypes, the routes (`/kamra`, `/book`), `app_publisher`, the apps-screen route
  `/kamra` (`marketplace_install_check`), `license.txt`, `NOTICE.md` and every copyright header.
  Only display strings change:
  - `app_title` "TEX Engine"; a description of the commercial platform "derived from Kamra
    (AGPL-3.0)";
  - the Desk logo and the apps-screen tile: the TEX mark (`/assets/kamra/tex-mark.svg`), titled
    "TEX Engine";
  - `index.html`: title and description; the favicons are the TEX mark.
- *The name shown* is TEX Settings > Brand name (default "TEX Engine"), a platform setting read
  on the server (`kamra.tex.entry.brand_name`: whitespace collapsed, at most 60 characters).
  - `kamra/www/kamra.py` writes it, escaped, into the page `<title>`.
  - The sign-in page gets it from `kamra.tex.api.session.entry`: guest, GET only, 60 requests a
    minute per IP. It returns the product, the brand, the source URL, the upstream and the
    licence, and nothing about the site's hotels or users.
  - `session.bootstrap` returns the same brand and the source URL for the admin app.
  - No user-supplied CSS or JS anywhere.
- *Sign-in page.* A TEX page (`tex/screens/login`) built from the TEX design system.
  - The six TEX languages (en, tr, de, ru, ro, pl). The choice is the admin app's language
    (`tex-lang`).
  - Arabic is not offered: the TEX UI has no Arabic catalogs. The legacy PMS keeps its own
    language switch, and the legacy housekeeping app keeps its own login (`screens/Login.tsx`).
  - Kamra's public-playground demo buttons stay behind `kamra_demo_mode`, translated.
- *Source offer (section 13).* The sign-in footer and the foot of the admin navigation (every
  admin screen) show "Based on Kamra PMS · AGPL-3.0 · Source code".
  - "Kamra PMS" links the upstream repository; "AGPL-3.0" the licence text.
  - "Source code" links `kamra.tex.entry.source_url()`: the site config's `tex_source_url` when
    it is an https URL (an operator who offers the source elsewhere, e.g. a tag of the release
    they run), else the TEX repository (`https://github.com/travellerbuddha/TexEngine`).
  - The operator keeps that URL serving the source of the version they run (GO_LIVE_READINESS
    §3).
  - ~~The guest booking engine shows no such link: it is white-labelled per hotel. Whether and
    how guests are offered the source is an owner decision.~~ Wrong (review M2): section 13 covers
    every user who interacts with the program remotely, guests included, and white-labelling is no
    exception; the engine's footer already said "Booking engine by TEX Engine". Guests are offered
    the source (review follow-up).
- *"/".* `kamra/www/kamra.py` answers any request outside its mount with a 302 (the page is
  never cached):
  - a Desk (System) user → `/kamra/tex`;
  - a visitor → `/kamra/login`;
  - a signed-in user without Desk access → `/me` (Frappe's portal).

  This applies only while the site's home page is the SPA (as `kamra.install` sets it); a home
  page a hotelier chose is never overridden. A verified custom booking host is unaffected:
  `BookingHostRenderer` is a page renderer and claims `/` before the page is rendered (tested).
  Rejected:
  - `website_redirects`: they run before page renderers (a custom host's `/` would be
    redirected), they are cached, and they cannot depend on the user;
  - a `get_website_user_home_page` hook: it would override a hotelier's home page.
- *Navigation (G-64).* Each area in `nav.ts` lists its sub-sections. The sidebar opens them while
  the user is in the area, or with the area's toggle. The command palette reaches them, and each
  area keeps its own tab strip. Every entry opens a working screen, or a real part of one:
  - Rates & Contracts:
    - Contracts (the list);
    - Contract versions, Price periods, Occupancy rules and Rate plans: new lists across
      contracts (`lists.versions`, `lists.version_rows`), from the current versions (drafts
      and published) or all; a row opens its version on the matching tab;
    - Markets (Settings → Markets), Promotions (the policy list), Currency (FX rates);
    - Restrictions: a new list (`lists.restrictions`); consecutive days of one scope with the
      same values read as one range, with the G-48 fields when the schema has them; a row
      opens the grid on its first day (`/tex/inventory?start=`);
    - Bulk editor: the grid with its bulk editor open (`/tex/inventory?bulk=1`).
  - Booking Engine:
    - Sites (configuration; a site's branding, widgets, domains and policies are its tabs);
    - Rooms: new (`lists.rooms`), each room as the engine shows it, gaps flagged (no picture,
      no description, no live contract), the live contracts that sell it and its translations;
      texts are translated in Content (`content?kind=rooms`);
    - Content;
    - Analytics: a new screen on the existing `reports.dashboard` funnel, with tracking ids per site
      and a link to Reports › Conversion (G-46, ADR-059).
  - CRM: Guests, Segments, Loyalty, Abandoned bookings, Communications (new,
    `lists.communications`: paged and filtered; no message body, which stays on the profile).
  - Campaigns is not started. The sidebar lists it as "Not available yet": not a link, and not
    in the command palette. This was chosen over leaving it out, so that R-35's structure and
    the missing piece stay visible.
- *Capabilities.* An entry is shown when the user holds, at the selected hotel, what its screen's
  endpoints require. The endpoints enforce it:
  - Each list declares its capability with `require_capability`. It then covers the named hotel
    (checked) or every hotel where the capability is held; another hotel's rows never leave.
  - Versions, rate plans and restrictions: `price.view`, as `contracts.get_contract` and the
    grid.
  - Periods and occupancy rules are cost: `price.view` and `price.view_cost` or `contract.edit`,
    as `contracts.get_version`. A rate plan's adjustment is returned only where cost is seen
    (G-11).
  - Rooms: `booking_site.edit` at the hotel. Communications: `crm.view`, and the
    communication's hotel must be one of the viewer's.
  - Analytics: `report.view` (its endpoint's). The bulk editor: the grid's `price.view` and
    `restriction.edit` or `inventory.edit`.
  - A list offers "this hotel / all my hotels" when more than one hotel qualifies.

**Consequences.**
- `/` leads somewhere for everyone; links to `/kamra` keep working.
- Existing sites keep their Website Settings favicon (`kamra-mark.svg`) on the pages Frappe
  renders (Desk); an administrator changes it there. Frappe's own `/login` says "Login to
  Frappe" (System Settings) with the TEX logo; TEX users are sent to `/kamra/login`.
- Kept on purpose (legacy PMS, hidden while it is switched off): the housekeeping app's login,
  and the AI assistant and MCP server texts that name Kamra PMS.
- Sidebar group labels now meet 4.5:1 (part of G-63's contrast finding; G-63 stays open).
- Tests:
  - `test_entry_branding` (15). On the base commit `665b6b9`, 3 fail and 9 error. The 3 that
    pass guard what must not change: the custom host's `/`, the SPA below its mount, and the
    existing endpoints' refusals.
  - e2e `entry-branding.spec` (5): sign-in page, site root, every new entry for revenue, the
    agent's hidden entries and 403s, 375 px.
- Open:
  - CRM Campaigns (R-37, not started);
  - ~~the guest-facing source offer (owner decision)~~ done by the review follow-up;
  - `tex_source_url`, or a public repository, kept reachable (owner).

**Follow-up: editor saves (branch `fix-editor`, 2026-09-24).** A decision on how the admin
editors treat a save; recorded here as the latest admin-UI ADR.
- *Discard returns to the last save.* The contract version editor's Discard reloaded the version
  as the page first fetched it. After a save it showed the pre-save tables and took them as the
  base, so the next edit and Save sent them and silently undid the earlier save on the server.
  Discard now returns to the copy the last load or save produced. The other editors' Discard
  or Reset already did.
- *A save's answer does not overwrite what the user changed while it was in flight.* The saved
  copy becomes the base. What the user changed meanwhile stays on top of it, still unsaved, and
  goes out with the next save. The unit is a field: a policy's, a booking site's or a loyalty
  program's fields, a version's settings and its selling terms. For a version's tables the unit
  is the whole table. There is no row-level merge, because rows have no identity on the client
  (their keys are made anew at every load). Everything the user did not change takes the
  server's copy, with its normalised and server-filled values.
  (`frontend/src/tex/lib/edits.ts` `overSaved`; `VersionEditor`, `PolicyEditor` for every policy
  kind, `SiteEditor`, `ContentTranslations`, loyalty `ProgramPage`.)
- *One save at a time* in the version and policy editors: Ctrl+S or Enter while a save is in
  flight does nothing.
- *Why.* Before this, a save's answer replaced the whole editor. This also caused a flaky
  `contract-admin.spec`: `saveDraft` could return while `save_version` was still in flight. It
  waited for a "Draft saved" toast, and the previous save's toast was still showing (toasts stay
  4.5 s). It also waited for a disabled Save button, and a busy button is disabled too. The late
  answer then wiped the board row that `addBoard` had just added. `saveDraft` now waits for the
  save's answer, and the editor would keep the row anyway.
- Tests: e2e `editor-edits.spec` (3). All three fail on main `b72b2a8`'s frontend.
- Open: the TEX settings form still takes the saved copy whole (and reloads it after a save).
  The booking site editor remounts after a create, so text typed while the create is in flight
  is dropped.

### ADR-060 review follow-up (branch `fix-shell`)
An independent review of G-60 and G-64 found 3 Medium and 9 Low issues. All are fixed or answered;
each fix has a test written first (the fail-first counts are at the end).

- *M1: the sign-in page took any answer for a session.*
  - The failure: Frappe answers `/api/method/login` with 200 without a session too
    (`frappe/auth.py`). A two-factor account gets `verification` and `tmp_id`; an expired password
    gets `message: "Password Reset"` and `redirect_to`. The page reloaded on any 200: the user
    stayed a visitor, saw no error, and each try sent another code.
  - Now only `message: "Logged In"` signs in to the admin app. A two-factor account gets a code
    step: the code is posted with the `tmp_id`, a wrong or expired code is told, "Back" returns to
    the form. The prompt follows Frappe's method (app, SMS, e-mail; an authenticator app's first
    sign-in is answered as e-mail, with the set-up instructions).
  - An expired password follows `redirect_to` only when it is on this site, else the page says so.
    A website user ("No App") goes to the portal (`/me`), as `/` sends them. Anything else is told.
  - "Forgot password?" (`/login#forgot`) and "Other sign-in options"
    (`/login?redirect-to=/kamra/tex`, where single sign-on or LDAP live) lead to Frappe's page. The
    legacy housekeeping sign-in hands any answer without a session to that page.
  - Tests: `TestSignInContract` pins Frappe's answers with a second factor on for one test user only
    (a role of its own in the test's transaction; the site switch read as on, never written; commits
    refused; the step that makes a session is recorded, not run, because it commits). The e2e runs
    against a real second factor for one user: `kamra.tex.devtools.e2e_two_factor.enable` marks a
    role of its own and sets the site switch directly (saving System Settings would mark the role
    "All", i.e. everyone), refuses when another role is marked, and `disable` restores both; run
    under the bench-test lock.
- *M2: guests were not offered the source, and nobody got the running version's.*
  - The offer is now the source of the version that runs. It is the TEX repository at the running
    commit (`/tree/<sha>`), or the site config's `tex_source_url`, whose `{commit}` is replaced by
    that commit. An operator's address without `{commit}` is shown as it is (for a release tag).
  - The running commit: the site config's `tex_source_commit` (an install without its git
    checkout), else the app checkout's HEAD, read from `.git` without running git (a worktree's
    `gitdir:` file and `packed-refs` included), once per process. With neither: the repository.
  - The bundles carry their build commit (a Vite `define`), for a page that has no other address.
  - Guests: "Booking engine by TEX Engine · AGPL-3.0 · Source code" on every booking-engine page
    (the site, booking, confirmation, manage, payment and error pages) and in the widget's modal
    (the framed page shows it without the hotel footer). It comes from TEX, not from the site's
    settings: no site setting removes it.
  - The legacy guest pages still served (`/kamra/book`, `stay`, `checkin`, `menu`, the housekeeping
    app) show the admin app's notice.
  - Desk: Help › About adds a TEX Engine row with Kamra PMS, the licence and the source
    (`public/js/tex_source.js`, loaded by `app_include_js`; the address comes with the boot,
    `extend_bootinfo`). Opened again, the dialog is reused and the row is not repeated. Frappe's own
    `/login` page and Desk's footer carry no offer (Desk users reach About from every page).
- *M3: a booking site named like an admin page opened that page.*
  - A site opened at `/tex/booking-engine/<name>`, next to the area's pages `new`, `content`,
    `rooms` and `analytics`. The server reserved only `pay`, `api`, `assets`, `manage`, `widget`.
  - A site now opens at `/tex/booking-engine/sites/<name>`, whatever its name. An old link
    `/tex/booking-engine/<name>` is redirected there (query and hash kept). The new-site form
    stays at `/tex/booking-engine/new`, and "Sites" is the current entry on both.
  - `new`, `sites`, `content`, `rooms` and `analytics` are refused as the slug of a new site (its
    name is its first slug) or of a site moved to another slug, on the server and in the form. A
    site that has one keeps it and stays savable.
  - p47 reports each existing site named like an admin page (`booking_site.admin_slug`, audited
    once). It never renames one: the name is the site's first slug, which guests, widgets and
    campaigns may use. The owner decides whether to create the site again under another slug.
- *L1: `session.entry` over HTTP.* A guest's GET through Frappe's WSGI application (its own
  thread and connection) answers the five keys only; POST, PUT and DELETE are refused; one
  address gets 60 answers a minute, then 429, while another address still gets its own.
- *L2:* `tex_source_url` is offered only as an https URL with a host, no spaces, at most 300
  characters, and no user name or password (an operator's token would reach every visitor).
- *L3: the pages carry the offer.* The pages the server renders (the admin app's page, the booking
  engine's, a booking site's own host) carry the source address and the brand as `<meta>`, escaped.
  The sign-in page and every notice read them first, so a rate-limited or failing `session.entry`
  never falls back to another address (or the brand to "TEX Engine"). A page served without them
  (the dev server) asks `session.entry` once.
- *L4:* CRM › Communications and the guest profile name the actor by one rule
  (`crm.service.actor_name`): an online booking's visitor ("Guest") and the system (Administrator:
  the scheduler, a migration) are TEX itself, staff by their full name (the profile showed the
  user id).
- *L5:* `lists.version_rows` reads the versions most recently changed first (it was unordered)
  and their rows in that order (a join on the version), so a cut keeps the recent ones; `truncated`
  is set when the 2000-version cap is hit too, not only the 5000-row cap. (Since ADR-061's final
  follow-up, main-side group: "current" leaves out archived contracts' versions, and the cap counts
  only versions with a row in the table.)
- *L6:* a Communications row links its guest's profile only when the viewer may open it, as
  `require_guest` judges (a booking at one of their hotels, or a profile of their enterprise:
  `crm.service.openable_guests`). The other rows say "No booking at your hotels: the profile is not
  shared with you" and are plain rows (`DataTable.rowClickable`).
- *L7:* Rates' tab strip shows Restrictions only with `price.view`, as the navigation and the
  endpoint; an area toggle names its list (`aria-controls`) only while the list exists; the sign-in
  page starts in its form; its error is tied to the fields (`aria-describedby`) and marks them
  invalid when they hold the fault (not for an expired password).
- *L8:* the FINAL_GAP_AUDIT G-60 row said "3 fail, 4 error": on `665b6b9` the 8 G-60 tests gave 3
  failures, 3 errors and 2 passes (as this ADR's 15-test count already said).
- *L9:* tests for the portal branch of `/` (a website user goes to `/me`) and for mixed per-hotel
  cost (`price.view` at two hotels, cost at one: the cost tables cover that hotel only, and only its
  rate plans carry an adjustment).
- *Found by the e2e: an area opened while a navigation loads.* The sidebar forgets areas opened by
  hand when the user moves to another area. The router keeps the old location until the new
  screen's code is in (a React transition), so an area opened in that time closed again when the
  navigation landed. `entry-branding.spec`'s navigation test failed this way on the Vite dev server
  (slow chunks), on the base commit too. A toggle now belongs to the areas of the location the
  browser is already at, and is forgotten only when the user moves on from there.
- *Unchanged:* no DocType change. p47 only reports (audit rows). p47 follows p45 (main).
- *Tests, fail first on the base `9215991` with the new tests (`36e3fd7`, corrected in `79a9800`):*
  - `test_entry_branding` (15 → 34 tests): on the base, 8 failures and 3 errors (M3 ×2, L4, L5,
    L6, and six of the source offer: the running commit, credentials, the served meta, Desk,
    reading `.git`, and the https test's new default), 1 skipped (the base copy has no git
    checkout), 22 pass. Those that pass on the base pin behaviour that was right but untested:
    `session.entry` over HTTP (L1, 3), the portal branch and mixed per-hotel cost (L9, 2), and
    Frappe's sign-in answers the page must read (M1, 3).
  - `test_patches`: on the base, the registry test fails and the p47 test errors (p47 missing).
  - e2e `entry-branding.spec` on the base (its code and frontend): 7 of 10 fail. They are the two
    sign-in tests (M1: no code step; an answer without a session taken for one), the sign-in
    page's focus and error wiring (L7), the source offer for guests and for Desk (M2), the admin
    site URL (M3), and the navigation test (the race above). The site root, the restricted user
    and 375 px pass.
- *Verification (main `9642228` merged):* 35 integration modules, 743 tests OK (3 skipped in
  `test_patches`: the whole-site tests, which passed on a disposable site, `test_patches` 32/32 with
  every patch through p47); the upstream suites 76/76, 13/13,
  banquet 101; 419 unit tests; ruff; semgrep (Frappe rules, ERROR) 0 findings on the branch's
  Python files; `npx tsc -b`, `npm run build` (bundles not committed) and `npm run i18n:tex`.
  Playwright:
  - 51/51 against the branch's Vite dev server and bench server (every spec but custom-host and
    pay-link, desktop and mobile), with a real second factor for one test user
    (`e2e_two_factor`) and a `tex_source_url` with `{commit}` set;
  - 8/8 against the bench itself (custom-host, pay-link, manage-money). The dev bench serves
    `/assets/kamra` from main's checkout, so these ran the branch's server code with main's
    bundles.

## ADR-061 Pricing Workspace
*The Pricing Workspace is a UX over the existing contract-version tables. The server prices,
validates and quotes the editor's unsaved state in memory (a read-only overlay) and never saves it;
the client does no arithmetic on money. Design: `PRICING_WORKSPACE_UX.md` (revision 3). This ADR
grows with the slices S1–S16; the implemented parts are marked (all sixteen are implemented on
branch `pricing-workspace`; S16 is the last section).*

**Context.** Entering an ORS-style contract in the version editor took about 100 clicks, 7 tab
switches, 7 modal dialogs and a forced save before any price could be checked
(`PRICING_WORKSPACE_UX.md` §1.3). The engine and the payload can already express every part of
the target model. Missing were a workspace that matches how a revenue manager works and a few API
gaps (§4 GAP-1…GAP-12). `price_matrix`, `validate_version` and `preview_price` read only the saved
draft, so the rates grid hid every resolved price as soon as anything was unsaved (GAP-1). A blank
rule value was saved as 0 and priced as 0 (GAP-8). The version said only `editable`: nothing about
preview or publish rights, the basis lock or the currency's minor units (GAP-10).

**Decision (the workspace; §0 of the design).**
- *D1 Projection.* The workspace is a projection over the existing `EditorState` (settings, the
  eight tables, selling). Every gesture becomes ordinary `period_rates`, `occupancy_rules`,
  `age_bands`, `rooms`, `periods` or `boards` rows. The save payload, `payloadOf`, the fingerprint
  and `save_version` stay as they are. No DocType, payload (`tex.contract.v1`), op, precedence or
  lifecycle change.
- *D2 No client money arithmetic.* Resolved prices, occupancy totals, price-test subtotals, bulk
  adjustments and adjustments of entered base prices are computed by the server: the read-only
  overlay (GAP-1), `apply_op_values` (GAP-7, S5) and the quote's `nights[]` subtotals (GAP-12, S5).
  The client only parses, normalises and compares decimal strings; the only numbers it computes
  are integers (counts, positions, capacity loops, date offsets).
- *D3 No autosave.* Save stays explicit (button, Ctrl/Cmd+S), sends the whole payload, is audited
  and keeps `settle()` / `overSaved`. Live feedback comes from the overlay, so the forced save
  before a price check goes away. The pricing basis is a contract-header field, saved by its own
  explicit Apply.
- *D4* The shorthand parser is pure, deterministic and locale-independent (both decimal marks, no
  grouping separators, currency-aware refusal of ambiguous input), tested with `node --test`.
- *D5* Four sections (Pricing · Commercial rules · Offers & promotions · Preview & audit). The old
  row editors stay as Advanced rule tables, so no capability is lost.
- *D6* The base room stays a UI concept (`TEX Contract Room.is_base`), made exclusive by the UI and
  used as the default `base_room_type` of new formulas; the engine follows each rule's
  `base_room_type`.
- *D7* A period cell replaces the room's all-periods rule for that period and never stacks on it
  (ADR-006).
- *D8* Special combinations are ordinary `TEX Occupancy Rule` rows (`combination`, `position`,
  `age_band`); valid combinations come from room capacity, as in the publish sweep.
- *D9* Validation issues gain an optional, additive `ref` (room, period, rule, band(s), party,
  board); codes and messages do not change (GAP-4, S4).
- *D10* Shorthand maps to ops by the owner's fixed table in every grid; the only per-context
  differences are forced by the DocType op lists (O2, O3).
- *D11 The row decides a relative entry in the room matrix, never the cell's state.* On the base
  room (which derives from nothing) the server applies the entry once to the entered price and it
  is stored as ABSOLUTE; on every other room it always writes a formula from the room's default
  base.
- *D12* Engine defaults are shown where no rule exists: "Adult ×1.00 (default)" from the server's
  `occupancy_defaults`; a child band without a rule is "No rule · not sellable" (ADR-007).
- *D13* Band codes never reach the screen where a label exists: labels are saved with the band,
  and codes in server text are replaced by labels on display.
- *D14 The Explain ladder follows the engine's order* (Base → Period (identification) → Room →
  Occupancy (adults) → Child → Special combination → Board → Period adjustment → Rate plan → Night
  cost → Cost offers → Markup → FX → Promotion → Tax) and is a before → after chain in which every
  value is a server field.

**Owner sign-off (O1–O5): provisional, pending the owner's sign-off** (owner input 13 in
`GO_LIVE_READINESS.md`; corrected in S3, which said "implemented as proposed" before any of them
was). The workspace is built with the proposed behaviour below; each is a small, isolated change in
`shorthand.ts` / `model.ts` if the owner decides otherwise. Where each lands: the parse of O1–O3
and O5 is S1's `shorthand.ts` (branch `pricing-workspace`, not merged with `pw-backend`); the board
cells that apply O1–O3 are S13; O4's apply-once needs S5 (`apply_op_values`) and S9. None of them
is on branch `pw-backend` after S3 (S2–S3 are backend read models and guards). Each is marked
implemented when its slice lands, and its implemented behaviour is reported before the final run.
(The lanes are now merged; the state after the merge is "O1–O5 after the lane merge", at the end
of this ADR.)
- *O1* Board cell, bare `100` → ABSOLUTE 100, i.e. 100 per room per night (`boards.py`); the
  reading line says so before commit. Alternative: a bare number is ADD (per adult).
- *O2* Board cell, `-20` → ADD −20 (SUBTRACT is not a board op).
- *O3* Board cell, `50%` → ADJUST_PERCENT 50 (PERCENT_OF is not a board op; the engine treats both
  alike). Alternative: refuse and require `+50%`.
- *O4* Base room, relative entry → parsed by the owner's table, applied once by the server to the
  entered price and stored as ABSOLUTE (D11). Alternative: refuse (OP_NOT_ALLOWED, "use Adjust…").
- *O5* Currency-aware AMBIGUOUS: in 0- and 2-decimal currencies an amount with 1–3 integer digits
  and exactly 3 fraction digits (`1.500`) is refused with what to type; accepted in 3-decimal
  currencies (KWD, BHD, OMR, JOD, TND). Alternative: drop the guard.

**Decision (implemented in S2: GAP-1, GAP-8, GAP-10).**
- *The read-only overlay* (`api/contracts.py _overlay(name, data)`). `price_matrix(version,
  adults, data=None)`, `validate_version(name, data=None)` and `preview_price(..., data=None)` take
  the payload `save_version` takes. With `data`:
  - the same gates as before, plus `contract.edit` at the version's hotel and Draft status (a
    published version is refused: "Only draft versions can be previewed with unsaved changes.");
  - the payload is applied to the loaded draft in memory exactly as `save_version` applies it: the
    same row cleaning (`_clean_rows`, shared), `_set_selling`, the settings, each table replaced;
  - it is then checked as a save checks it, with the same messages: blank values (below), the
    DocType defaults (`_set_defaults`), the decimal check (`decimals.check_inputs`, the 9-place
    refusal), and Frappe's own side-effect-free checks (`_validate_mandatory`, and per document
    `_validate_data_fields`, `_validate_selects`, `_validate_non_negative`, `_validate_length`).
    Two checks of the save are not run (S2 review, recorded in S3): Frappe's link validation
    (`_validate_links`: a row naming a rate plan, board or room type that does not exist) and the
    version controller's window order ("Sale window ends before it starts."). The overlay prices,
    validates and quotes such a draft as `build_terms` reads it (a missing rate plan validated
    without an issue in the review's probe; a reversed sale window is reported as SALE_WINDOW),
    and `save_version` refuses it. No figure differs from what the engine computes for those
    values; the UI must not read "no issues" as "saves";
  - values are then normalised as a save stores and a load reads them (checks 0/1, integers,
    decimals as exact Decimals with blank = 0, blank dates none), so the overlay prices exactly what
    a save followed by a load would (tested by saving the same payload and comparing);
  - at most 5,000 rows over all tables;
  - nothing is saved, inserted, `db_set` or audited (tested: `modified`, the audit events and the
    child rows are unchanged).
- *Rule ids.* Each overlaid row is named `~<_key>` (its client key), else `~<table>-<position>`, so
  the rule ids in explanations, issues and (S3) matrix sources point back to the editor's row.
  Tables the payload does not carry keep their saved row names; the client maps those by `_name`.
- *Errors.* A refusal of the overlay (rights, status, blank value, decimals, mandatory, select,
  row cap) is raised. A draft that cannot be built (e.g. an unknown room type) answers
  `{build_error, rooms: [], periods: []}` from `price_matrix`, the existing `BUILD` issue from
  `validate_version` (the body moved into `svc.validate_doc(version)`; `svc.validate_version` keeps
  its gate and calls it) and the existing `BUILD` reason from `preview_price`.
- *Blank values (GAP-8).* `_require_values(v)` runs in `save_version` (after the tables are set,
  before the save) and in the overlay: a `period_rates` or `occupancy_rules` row whose op is not
  INHERIT, or a non-base `boards` row, with a blank value is refused with "<table>, row <n>: a value
  is required; clear the cell to remove the price." Rows already stored as 0 load as "0" and are
  unaffected; the UI deletes a row when its cell is cleared.
- *Flags (GAP-10).* `get_version` adds `can_preview` (`price.view_cost`), `can_publish`
  (`contract.publish`), `can_edit_contract` (`contract.edit`, whatever the version's status), all
  at the version's hotel; `basis_locked` (`svc.is_published(contract)`, the predicate the contract
  controller's header lock uses) and `contract_doc.minor_units` (`money.minor_units` of the contract
  currency). The catalogue answer (agents) carries the three capability flags as false. They only
  tell the UI what to offer; every endpoint checks again.
- *Pricing basis.* No backend change: `save_contract({name, pricing_basis})` changes only the basis
  before the first publish, and the controller refuses it afterwards ("… cannot change"); an
  integration test pins both.
- *No rate limit* on the overlay endpoints: they are staff-only (`contract.edit`), called debounced
  (300 ms matrix, 1,200 ms validation), and bounded by the row cap; the existing endpoints had none.

**Consequences.**
- Pricing semantics, the payload, `save_version`'s results and the endpoints' answers without
  `data` are unchanged (the existing suites guard them). `save_version` is stricter in one way: a
  blank rule value is refused instead of being stored as 0.
- The client may show resolved prices, validation and quotes for unsaved edits without a save;
  every figure is the server's.
- Two users editing one draft is still last-writer-wins (`save_version` has no version token), as
  before; out of scope (design §6).

**Rejected.**
- Saving a scratch copy of the draft to price it: it writes, audits and races the real draft.
- Autosave: every keystroke would be an audited save and would break `settle()`.
- Client-side pricing or arithmetic for live figures: two engines drifting apart, and float money.
- `Document.run_method("validate")` in the overlay: wildcard `doc_events` hooks may have side
  effects; only the side-effect-free checks named above run.

**Tests (S2).** `kamra/tex/tests/integration/test_pricing_workspace_api.py` (17): the overlay's
matrix, validation and quote of unsaved data with nothing written or audited; `~key` rule ids in
the explanation; the overlay prices what a save stores (defaults, text-typed checks, INHERIT
blanks); refusals (published version, no `contract.edit`, another hotel, blank values in save and
overlay, 10 places with the save's message, the row cap, a build error answered); Finance reads
the saved matrix but cannot validate; the flags per viewer (Revenue Manager, a contract.edit-only
profile, Finance, an agent's catalogue), `basis_locked` before and after publish, `minor_units`
2 (EUR) and 3 (KWD); the basis change alone before publish and its refusal after. On the base
`1575c8b` 14 of the 17 fail (unknown `data` argument, missing flags, a blank value saved); the
basis tests and Finance's saved-matrix read pass there and pin existing behaviour. Removing the
overlay's defaults step or its stored-value normalisation makes the save-equivalence test fail
(checked). `test_security_regressions` G-11 now allows the three flags in an agent's catalogue
answer and asserts they are false. Verification on branch `pw-backend`: all 38 integration modules
800 OK (10 skipped, as on main), 425 unit tests, ruff.

**Decision (implemented in S3: GAP-2, GAP-2b, GAP-3).**
- *Pure read models* (`kamra/tex/pricing/matrix.py`, no frappe). Both call the engine's own
  resolvers, so nothing is priced twice in two ways:
  - `unit_source(terms, room, period)` runs `rooms.room_unit` with an `Explanation`. The last
    `room` step is the requested room (the derivation recurses first). The winning rule is taken
    among the room's rules in the order `room_unit` takes them (period rule first, then the rule for
    all periods; INHERIT skipped), so two rows sharing an id still resolve to the right one. It
    returns `{rule_id, scope: PERIOD | ALL, op, value, base_room_type, chain, overridden}`: `chain`
    is the room and the rooms it is derived from (room first), `base_room_type` the next room in it
    (none for an entered price), `overridden` the room's other rules including INHERIT rows.
    `Unsellable` propagates (no price, a cycle).
  - `party_total(terms, room, period, adults, band_codes)` builds the party as the publish sweep
    does (`validate._sweep`): each child at its band's `from_months`, numbered in the contract's
    child order (`ages.child_slots_in_order`, the ordering `classify_party` used inline, now
    shared), reference date the period's start. It then runs the engine's own steps for a night:
    `occupancy.check_capacity`, `rooms.room_unit`, `occupancy.price_occupancy`. It returns the
    total and the slots `{target, position, age_band, amount, rule_id, included}`. An unknown band
    code or a room outside the contract raises `PricingError`.
  - `rule_value(v)`: a rule value as exact decimal text without trailing zeros (`to_str_min(v, 0)`:
    `"1"`, `"1.15"`, `"245"`, `"0.333333333"`).
- *`price_matrix` additions* (the existing keys are unchanged; a test compares them with the
  pre-S3 computation for a draft, with `adults`, with parties and for a published version):
  - `rooms[].sources{period: unit_source}`, none for a cell with an error;
  - `rooms[].capacity{max_adults, max_children, max_occupants, min_adults, included_adults}` from the
    built terms, i.e. the effective values (the room type's where the contract room sets 0);
  - `age_bands[{code, label, from_months, to_months, is_infant, source}]` from the built terms
    (the label equals the code when blank, as `age_bands_of` builds it). `source` is `version` when
    the version has band rows, else the inherited policy's source (`policy:<id>/r<rev>/<scope>`)
    from `svc.band_source`: the policy `inherit.band_layer` picks (the most specific one defining
    bands, the choice `cascade` makes) among the policies live when the terms were built (now for a
    draft, `effective_from` for a published version). If those policies no longer give the same
    band set, it says `policy`;
  - `inherited_rules`: the terms' occupancy rules whose source is not `version`, with `rule_id,
    target, position, age_band, adults, children, room_type, period, op, value, is_override,
    source`;
  - `occupancy_defaults`: `adult` from `occupancy.GLOBAL_ADULT_DEFAULT` (`GLOBAL:ADULT`, ADULT,
    MULTIPLY, `"1"`, `global-default`, its note); `child: null` (ADR-007);
  - with `parties` (JSON, at most 12, each 1–12 adults and at most 8 band codes, upper-cased) and
    `party_room` (a room of the built terms, else "… is not a room of this contract"): `party_cells`,
    one per party in order, `{cells{period: total | null}, slots{period: […]}, errors{period:
    message}}`. `Unsellable` and `PricingError` (an unknown band, over capacity, no price, no child
    rule) are errors of their cell, not refusals.
  - `adults` stays accepted and unused. The gates are unchanged (`price.view` + `_sees_cost`, the
    overlay's with `data`). No rate limit: staff only, bounded (12 parties × the periods), called
    debounced.
- *Deviations from the slice text, with reasons.*
  - Values use `rule_value` (`"1"`), not `to_str_rate` (`"1.000000"`): the design and the slice's
    own test fix `value "1"`; both are exact, and the client compares decimals canonically.
  - `party_total` runs the engine's capacity check first. The sweep only prices combinations the
    room holds; a sample party the room cannot hold would otherwise get a total the engine never
    charges. For a party the room holds the result is the sweep's.
  - The frontend `PriceMatrix` type is split: `PriceMatrix` (the S3 keys) and
    `PriceMatrixBuildError` (`{build_error, rooms: [], periods: []}`), union
    `PriceMatrixResponse`, because the build-error answer has none of the other keys.

**Rejected (S3).**
- Recording each band's origin in the frozen payload: a payload and hash change for a display
  need; the version's own rows and the policy revisions say it.
- Summing slots or deriving the chain in the client: the engine already knows both.

**Tests (S3).** Unit `test_matrix.py` (18): the fixture contract's sources (generic ×1.15 → ALL
with chain [SUP, STD]; SUITE P3A 245 → PERIOD overriding the generic rule; the base room's own
price; an INHERIT period row overridden while the generic rule wins; a chained derivation; two rows
sharing an id; a cycle and a missing price unsellable); party totals equal to
`engine.price_stay`'s occupancy for 2A + CHB, for both child orders, a derived room, a period
override and ROOM basis; the sample party's children at the lower edge of their bands, in the
contract's order, with its infants (added in S3's re-verification: a mutant placing them at the
upper edge priced the same and survived the other tests); an unknown band, over capacity and a band
without a rule refused; `band_layer`; `rule_value`. Integration `test_pricing_workspace_api` (+14,
31 in all): sources with saved row names and with `~key` ids, errored cells without a source,
effective capacity (room type fallback, overlay values), the version's bands and the engine default, a band without a label
(overlay and saved), bands and rules inherited from a live global policy (draft and published),
the policy's rules cascading into a version with its own, sample parties (totals, slots and rule
ids, the same total as a quote, an unknown band and over-capacity as cell errors, a period without
a price), no `party_cells` without parties, the party room refused when not in the (unsaved)
contract, malformed parties refused, Finance allowed and an agent refused, the old keys identical.
On the S2 tip `19c6b72` `test_matrix` cannot import `pricing.matrix`, and the 14 new integration
tests all fail (25 errors counting sub-tests: the unknown `parties` argument, the missing keys)
while the 17 S2 tests pass; the old-keys test's draft and `adults` sub-tests pass there too, which
pins the baseline. Verification on branch `pw-backend` (main `1575c8b` already merged), migrated
with it: all 38 integration modules 814 OK (10 skipped, as before), 442 unit tests, ruff; eval
harness 76/76, front-desk journey 13/13, banquet 101 OK; `tsc -b`, `npm run build`, `i18n:tex`.
Re-verified after the benchmark, the unit test for the sample party and the documentation
corrections below (tip `404a3e4`, main `1575c8b` merged, migrated with it): all 38 integration
modules 814 OK (10 skipped), 443 unit tests, ruff; eval 76/76, journey 13/13, banquet 101 OK;
`tsc -b`, `npm run build`, `i18n:tex`; `bench_pricing_workspace` 2 OK.

**Performance of the server side (measured in S3; the pre-Final measurement asked for).**
`kamra/tex/tests/integration/bench_pricing_workspace.py` is opt-in: it is not a `test_*` module, so
the regression run leaves it out (`bench --site test.localhost run-tests --module
kamra.tex.tests.integration.bench_pricing_workspace`). It saves a large ORS-shaped draft inside the
test transaction (the base room priced per period; every other room derived by a formula, with its
own price in every fourth period; occupancy rules and board supplements per room and period) and
times each call the workspace makes, best of three, on the shared development bench, in seconds:

| Call | Realistic: 12 rooms × 26 periods, 1,406 rows, 346 KB | Near the row cap: 12 × 40, 4,539 rows, 1.13 MB |
|---|---|---|
| `save_version` (once) | 0.86 | 2.93 |
| the overlay alone (`_overlay`) | 0.17 | 0.52 |
| `price_matrix`, saved draft: the pre-S3 keys / with the S3 keys | 0.06 / 0.08 | 0.15 / 0.16 |
| `price_matrix`, unsaved data | 0.25 | 0.70 |
| `price_matrix` + 12 sample parties, saved / unsaved | 0.15 / 0.33 | 0.42 / 0.93 |
| `preview_price` (7 nights), saved / unsaved | 0.07 / 0.24 | 0.16 / 0.69 |
| `validate_version`, saved / unsaved | 2.25 / 2.30 | 10.0 / 9.9 |

The benchmark also asserts that the unsaved data answers what the same data saved answers (cells,
sources with each row name mapped to its `~key`, party totals and errors, issue codes, quote
totals), and loose ceilings (6–12 times these figures) that catch a change of order, not a slower
machine. Reading: the overlay adds 0.2–0.5 s (parsing, cleaning and checking the payload); the S3
sources add about 0.02 s to a matrix, twelve sample parties 0.1–0.3 s. `validate_version` is the
cost, with or without data: its publish sweep prices every combination of every room and period,
2.3 s on the realistic contract and 10 s near the row cap. So the "no rate limit" decision holds
for the matrix and the preview (live, 300 ms debounce), and the UI slices (S8, S9, S15) must keep
validation bounded: at most one `validate_version` in flight per editor, a stale answer dropped,
and a debounce that grows with the draft (1.2 s suits the realistic size, not the cap). A
server-side concurrency guard for validation is not built (open).

**Decision (implemented in S4: GAP-4, GAP-5).**
- *Anchored issues (D9).* `validate.Issue` gains `ref: dict | None` as its last field. It is not
  part of the issue's identity (`compare=False`), so issues compare and hash as before. `to_dict`
  adds `"ref"` only when there is one. `_err` / `_warn` take the parts as keywords and keep only the
  known ones (0 adults or children is known). What each issue names:
  - `ROOM_CAPACITY`, `INCLUDED_ADULTS`: `room_type`;
  - `PERIOD_DUPLICATE`, `PERIOD_RANGE`: `period`; `PERIOD_OVERLAP`: `period`, `other_period`;
  - `ROOM_RULE_DUPLICATE`: `rule_id`, `rule_ids`, `room_type`, `period` (none for "all");
    `ROOM_RULE_UNKNOWN_ROOM` / `_UNKNOWN_PERIOD` / `_NO_BASE`: the rule's `rule_id`, `room_type`,
    `period`;
  - `ROOM_NEGATIVE` and the `room_unit` errors (`NO_ROOM_PRICE`, `ROOM_DERIVATION_*`): the cell's
    `room_type` and `period`, and `rule_id` of the rule that prices the cell (the first non-INHERIT
    rule `room_unit` takes; none when the room has no rule there). A derived room whose base has no
    price names its own formula;
  - `AGE_BANDS`: `age_bands` = every band code of the terms, in their order (the message names
    bands by code; `ages.band_problems` returns text, so the client replaces the codes it is
    given), and `age_band` when the problem is about one band (an invalid range), not for an
    overlap or gap between two. `ages.band_findings` is `band_problems` with the codes of each
    problem; `band_problems` is now built from it, text unchanged;
  - `OCC_UNKNOWN_*`, `OCC_INHERITED_*_UNUSED`, `OCC_COMBINATION_QUALIFIER`, `OCC_ADULT_BAND`,
    `OCC_INHERITED_ADULT_BAND_UNUSED`, `OCC_NO_VALUE`: the rule's own scope (`rule_id`,
    `room_type`, `period`, `age_band`, `adults`, `children`); `OCC_DUPLICATE`: the twins'
    signature, `rule_id` + `rule_ids`; `OCC_AMBIGUOUS` and `OCC_POLICY_OVERRIDE_OUTRANKED`: both
    rules (`rule_ids`) and the slot the message names (`room_type`, `period`, `age_band`,
    `adults`, `children`), without a pricing policy's placeholders (`policy_issues`);
    `OCC_INFANT_GENERIC`: the infant `age_band` and the band-less rules (`rule_ids`);
  - the publish sweep (`NO_CHILD_RULE`, `AMBIGUOUS_OCCUPANCY_RULES`, …): `room_type`, `period`,
    `adults`, `children`, `age_band`, and for a tie the tied rules (`Unsellable.params["rules"]`).
    The sweep reports a combination once, so `period` is the first period it fails in;
  - `BOARD_*` (below): `rule_id`, `board`, `room_type`, `period`; `BOARD_DUPLICATE` also `rule_ids`.
  - None: `CURRENCY`, `NO_ROOMS`, `NO_PERIODS`, `SALE_WINDOW`, `STAY_WINDOW`, `AGE_BANDS_MIN_AGE`,
    `NO_AGE_BANDS`, `NO_BASE_BOARD`, `RATE_PLAN_BOARD`, `OFFER_*` and `BUILD` (about the contract,
    the selling terms, a rate plan or an offer, not a cell).

  Rule ids are the saved row names, or `~<_key>` for rows sent unsaved (S2). Codes, levels, order
  and every message are unchanged: 80 scenarios (223 issues, every code that gained a ref) give the same
  `(level, code, message)` lists on the S3 tip and on S4, apart from the new BOARD_* codes. The
  frontend `Issue` type gains `ref?: IssueRef`. `issueTab` is unchanged until S8, so BOARD_* issues
  count under the default ("settings") group and are listed in the editor's issue list.
- *Board rules (GAP-5).* After `NO_BASE_BOARD`, three new ERRORs, mirroring the room-rule checks:
  `BOARD_UNKNOWN_ROOM` ("board rule {id} ({board}) names unknown room {room}"),
  `BOARD_UNKNOWN_PERIOD` ("… names unknown period {period}") and `BOARD_DUPLICATE` ("board {board}
  has {n} rules for the same room and period": one board, room and period, base rows included).
  The engine is unchanged: `boards.board_rule` still breaks a tie by the greatest row name, but a
  draft that has one can no longer be published.
- *Unique row names in the overlay* (an open item of the S2 and S3 reviews, taken here because S4's
  `rule_id` / `rule_ids` anchor on them). The overlay refuses a table in which two rows would get
  the same name: the same `_key` twice, a key equal to a keyless row's `~<table>-<position>`, or two
  keys equal after the 100-character cut. "<table>: two rows have the key <key>; each row needs its
  own key." One key in two tables is allowed (the issue code says which table); `save_version`
  drops the keys and is unchanged.

**Deviations from the slice text, with reasons.**
- `rule_ids` (not in the slice's key list) on the issues about several rules (`ROOM_RULE_DUPLICATE`,
  `OCC_DUPLICATE`, `OCC_AMBIGUOUS`, `OCC_POLICY_OVERRIDE_OUTRANKED`, `OCC_INFANT_GENERIC`,
  `BOARD_DUPLICATE`, the sweep's ties): `rule_id` can mark one row only; the twins all need fixing.
  `rule_id` is the first of them (table order), so a client that reads only `rule_id` still anchors.
- Occupancy-rule refs also carry the rule's `adults` / `children` (its combination) where it has
  them, and `BOARD_UNKNOWN_ROOM` / `_PERIOD` carry the rule's other scope part: the whole scope of
  the row, as the design's anchoring (§3.15) reads it.
- `OCC_POLICY_OVERRIDE_OUTRANKED` gets a ref (the slice listed the other OCC_* codes; the design's
  GAP-4 says OCC_*).
- The duplicate-key refusal above (an overlay behaviour change, S2 code).

**Consequences.**
- Drafts with an orphan or duplicate board row can no longer be published; they were priced by
  the row name's order or not at all. Published versions are frozen and price as before; a new
  draft based on one with such rows has to be fixed before it publishes. A read-only scan of the
  shared development site found none among its 273 contract versions with board rows. This
  behaviour change is announced in `GO_LIVE_READINESS.md` (change log).
- A published version's `validation_report` and `publish`'s `warnings` now carry the refs too
  (additive; not part of the payload or its hash).

**Rejected (S4).**
- Server-side band labels in messages: the label's language is the viewer's, and the client
  already has the labels; codes stay machine-readable.
- Parsing band codes out of message text: `band_findings` returns them from the check itself.
- Settling duplicate board rules in the engine: a pricing change for frozen versions; validation
  makes new ones unpublishable instead.
- Falling back to `~<table>-<position>` for a repeated key: the client could not map it back to the
  row it meant; a refusal names the table and key.

**Tests (S4).** Unit `test_validate_refs.py` (37, pure): the Issue shape (`ref` optional and last,
`to_dict` without an empty or missing ref, still hashable); header issues without a ref; missing
parts left out and 0 kept; the messages of `ROOM_RULE_DUPLICATE`, `OCC_DUPLICATE` and
`PERIOD_OVERLAP` byte for byte (the `test_contracts_restrictions` scenarios); the reference contract
still clean; the refs of every code listed above (room and period checks, the cell's rule for a
negative, unpriced, derived-without-base and cyclic cell, an INHERIT row not taken as the cell's
rule, age bands with every code and the single band, each OCC_* code, a tie's slot in the period it
decides, a policy checked on its own without its placeholders, the sweep's party and tied rules);
`BOARD_UNKNOWN_ROOM`, `BOARD_UNKNOWN_PERIOD` and `BOARD_DUPLICATE` (unscoped, scoped with three
rows, two base rows) with messages and refs; the fixture boards (AI base, UAI) and one board's rules
for different scopes clean; board errors after `NO_BASE_BOARD`. On the S3 tip `4575818` 31 of the
37 fail (27 errors: no `ref`; 4 failures: no board issue); the 6 that pass pin the unchanged
messages and the clean fixture. Nine mutants are killed (board twins keyed by board only, ref
compared, 0 dropped, a band named for a pair, an INHERIT row as the cell's rule, a policy
placeholder in a slot, no unknown-period check, the sweep's tie without rule ids, `to_dict` always
adding `ref`). Integration `test_pricing_workspace_api` (+6, 37 in all): `validate_version`'s JSON
anchors a duplicated room rule (`~key` ids unsaved, row names once saved); an issue about the
contract as a whole has no ref; board rules for a room the draft no longer sells, an unknown period
and a twin, with refs; publish refused for an orphan board period (the version stays Draft); the
`create_contract` fixture still publishes, its warnings and stored `validation_report` in the new
shape; the overlay refuses a key used twice and a key equal to a keyless row's name, in all three
endpoints, allows one key in two tables, and a save of the same payload succeeds. On the S3 tip 3
of the first 5 fail (no `ref`; board rows reported clean; publish not refused) and 2 pass (pinning
the ref-less issue and the fixture's publish); the key test fails before the guard. Verification on
branch `pw-backend` (main `1575c8b` already merged; no newer main), migrated with it: all 38
integration modules 820 OK (10 skipped, as before); 480 unit tests; ruff; eval harness 76/76,
front-desk journey 13/13, banquet 101 OK; `tsc -b`, `npm run build`, `i18n:tex`;
`bench_pricing_workspace` 2 OK.

**Performance after S4** (the same benchmark, best of three, seconds; S3's figures in brackets).
Realistic 12 × 26: `validate_version` 1.92 saved / 2.14 unsaved (2.25 / 2.30), `price_matrix`
unsaved 0.24 (0.25), `preview_price` unsaved 0.22 (0.24), the overlay alone 0.16 (0.17). Near the
cap 12 × 40: validation 9.48 / 9.50 (10.0 / 9.9), matrix unsaved 0.68 (0.70). The refs cost nothing
measurable (the realistic draft's 125 warnings all carry one); the duplicate-key check is one set
per table. The S3 reading stands: validation is the cost, and the UI must keep one in flight.

**O1–O5 after S4.** Unchanged: S4 is validation only. None of O1–O5 is implemented on `pw-backend`;
they land in S1 (O1–O3, O5 parse), S5 + S9 (O4) and S13 (board cells), and stay owner input 13.

**Decision (implemented in S5: GAP-6, GAP-7, GAP-12).** The last backend slice.
- *Price-test ages (GAP-6).* `preview_price` reads `children` with `_child_specs(children,
  check_in)` (`api/contracts.py`). Each child is one of:
  - an age in whole years 0–17: an int, a digit-only string (surrounding spaces allowed, as `int()`
    allowed them) or an integral float (`8.0`) → `ChildSpec(age=n)`, exactly as before;
  - `{"age_months": n}`, an int 0–215 → `ChildSpec(age_months=n)`: the exact month a band starts or
    ends at (95 months is 7y11m, in a 7–11.99 band);
  - `{"dob": "YYYY-MM-DD"}` → checked as a booking checks one (`ages.check_child_dob` against
    check-in and the site's today: not in the future, under 18 on arrival) → `ChildSpec(dob=…)`,
    priced by the engine in completed months on its age basis.

  Anything else is refused with "Child <n>: Child ages are whole years (0–17), {age_months} or
  {dob}." (the braces are literal: the client shows its own localised hint), a date-of-birth
  refusal with "Child <n>: <the check's message>"; no refusal repeats the date (the quote's
  `request` records it for the staff user who typed it, as a booking quote does). More than 12
  children: "A price test takes at most 12 children."
- *`apply_op_values` (GAP-7, D2, O4's server half).* `POST contracts.apply_op_values(version,
  values, op, value)`: `contract.edit` at the version's hotel, Draft only (the save's message),
  `op` one of ABSOLUTE, MULTIPLY, PERCENT_OF, ADJUST_PERCENT, ADD, SUBTRACT, `value` typed as a TEX
  decimal (`decimals.typed`, 9 places; blank refused), `values` a list of at most 500 items, each
  None / "" or a TEX decimal. Each price goes through the pure `matrix.adjust_amount(current, op,
  value, currency)`: ABSOLUTE is the value itself, any other op is `ops.apply_op` with the current
  price as reference and running amount, exactly as the ARI grid's rate change computes a new unit
  (`grid.py`), then `money.quantize` HALF_UP to the contract currency. → `[{value, error}]` in
  order: the new price as exact text ("77.00", "1155", "13.580"), or None with `NO_VALUE` (no
  price given, whatever the op) or `NEGATIVE` (the exact result is below zero). It reads the
  version's status and contract and the contract's currency (no document or terms are loaded),
  writes and audits nothing. No rate limit: staff only, 500 values at most, 7 ms for 500 on the
  benchmark's drafts.
- *Reported subtotals (GAP-12).* `occupancy.OccupancyResult` gains the keyword fields
  `after_adults` (the base, i.e. the room price on ROOM basis, plus the adult slots) and
  `after_children` (plus the child slots: the total before a whole-combination rule), both
  defaulting to ZERO. `engine.NightPrice` gains `subtotal_adults`, `subtotal_children` and
  `subtotal_board` (occupancy + board, the amount the period adjustment starts from), filled from
  values the engine already held through the existing `partial` tuple; `to_dict` adds them with
  `to_str6`. No price, total, explanation step, explanation text or `engine_version` changes (the
  spec example's summary lines, steps, totals and night keys are pinned as captured before). The
  guest view (`to_dict(internal=False)`) and `quoting.strip_internal` reduce `nights[]` to date and
  amount, so only staff with cost access see them. A child above the child bands priced as an adult
  is an adult slot, so it is in `subtotal_adults`; a child filling an included ROOM-basis place
  adds 0. The Explain ladder's chain holds by construction and is tested per night: the
  combination step's before is `subtotal_children` and its after `occupancy`; without one they
  are equal; `subtotal_board` = `occupancy` + `board` and is the period adjustment's before (else
  the rate plan's, else the night cost).

**Deviations from the slice text, with reasons (S5).**
- A whole-year age outside 0–17 is now refused (the slice's range). Before, `-1` was answered as a
  pricing error and 18 or more priced as an adult or answered "no age band"; a guest's booking
  already refuses them (`quoting.Party.parse`), and the price test should not price what cannot
  be booked. Within 0–17 the quote is identical (tested against the pre-S5 body, published and
  draft).
- A child object must carry exactly one of `age_months` or `dob` (`{age}`, both keys or none are
  refused): the slice lists the two shapes; a mixed one would be ambiguous.
- The refusal names the child ("Child <n>: …"), so the drawer can mark the input.
- The children are read before the terms are built, so a malformed child is refused even for a
  draft that cannot be built (before, the BUILD answer came first).
- `values` items are typed as TEX decimals (text; a JSON number is taken as `decimals.typed` takes
  it; a JSON list or object is refused before it, as it would otherwise surface as a server
  error); a malformed item refuses the call ("Price <n>: … is not a number."), not only its item:
  it is a client error, not a per-cell outcome.

**Consequences (S5).**
- Quote snapshots of bookings priced after S5 carry the three keys in their internal `nights[]`;
  older snapshots do not, and the ladder leaves those stages blank (design §3.13.1). A snapshot
  refers to its contract by payload hash, not by the quote's bytes, so reprices and the integrity
  check are unaffected.
- The existing Preview tab still sends whole years and is unaffected; the months / date-of-birth
  toggle and the ladder are S14, the base room's relative entry S9 and the bulk Adjust… S10.

**Rejected (S5).**
- Computing the adjusted price or the ladder's subtotals in the client (D2).
- Reusing `grid.apply_rate_change`: it splits periods and saves the draft; the workspace needs the
  number only, before anything is saved.
- A new explanation step per subtotal: it would change the explanation (text, count, snapshots);
  the values are fields of the night.

**Tests (S5).** Unit `test_engine.TestReportedSubtotals` (7): the spec example unchanged (summary
lines, steps, totals, night keys, engine version) and its subtotals (120 → 240 → 300 → 300); every
night of four scenarios (a period adjustment, a supplement board, two periods with a rate plan and
an infant, adults only) chains as above; a 2A+2C combination starts from the children's 275 and
ends at 247.50; ROOM basis (room 200, 3 adults: 270; single use: 200 → 160); `OccupancyResult`'s
running totals; the guest view and `strip_internal` without them. `test_matrix.TestAdjustAmount`
(4): the owner's examples (70 +10 % = 77.00, 80.55 +10 % = 88.61 HALF_UP, 100 × 1.155 = 115.50,
JPY 1155, KWD 13.580, −100 % = 0.00, 0 %, 50 %, ± amounts), ABSOLUTE, NEGATIVE, equality with
`ops.apply_op` + `quantize`. Integration `test_pricing_workspace_api` (+11, 48 in all): whole
years (`[8]`, `"[8]"`, `["8"]`, `[8.0]`) give the pre-S5 body's quote on a published fixture and
on the draft (`[1]`, `[4]`, `[8, 1]`, `[11, 3]`), 96 months the same price; 95 and 83 months in
their bands; a date of birth 8 years ago priced, the future and 18 on arrival refused, malformed
dates refused without echo; 22 malformed children refused, 13 children refused, 12 answered;
`apply_op_values` results (EUR, KWD 13.580), NO_VALUE, NEGATIVE, nothing written; a contract.edit-only
profile allowed, an agent, Finance and another hotel's Revenue Manager refused; a published version
refused; 500 values allowed, 501 and 16 malformed calls refused (lists and objects as prices
included); the base room's 100 "+10 %" →
110.00 saved as ABSOLUTE (matrix 110, the derived room 148.5); nights' 6-dp subtotals (2A + child 8
on UAI: 100 → 200 → 250 = occupancy, board 50 → 300), equal from the unsaved draft, absent after
`strip_internal`. Fail-first on the S4 tip `564014a`: 10 of the 11 new unit tests fail (the spec
example's pin passes and pins the baseline), 10 of the 11 integration tests fail (the guest-view
pin passes). Mutants killed: 7 in the unit tests (after-children taken after the combination,
subtotal_board after the adjustment, HALF_EVEN, the adults' subtotal counting children,
subtotal_adults = unit, no NEGATIVE, a missing key) and 4 in the integration tests (7.5 truncated,
`price.view` as the gate, no Draft check, no date-of-birth check). Verification on branch
`pw-backend` (main `1575c8b` already merged; no newer main), migrated with it: all 38 integration
modules 831 OK (10 skipped, as before; `test_snapshot_integrity` 13, `test_modification_determinism`
27, `test_security_regressions` 59, `test_pricing_workspace_api` 48); 491 unit tests; ruff; eval
harness 76/76, front-desk journey 13/13, banquet 101 OK; `tsc -b`, `npm run build`, `i18n:tex`;
`bench_pricing_workspace` 2 OK.

**Performance after S5** (`bench_pricing_workspace`, which now also times `apply_op_values` at its
cap and compares the nights' subtotals of the unsaved and saved quotes; best of three, seconds; S4
in brackets). Realistic 12 × 26 (1,406 rows): the overlay alone 0.18 (0.16), `price_matrix`
unsaved 0.24 (0.24), with 12 parties 0.30, `preview_price` unsaved 0.23 (0.22), `validate_version`
2.06 saved / 2.12 unsaved (1.92 / 2.14), `apply_op_values` 500 prices 0.007, `save_version` 0.71.
Near the cap 12 × 40 (4,539 rows): 0.50 (0.51), 0.70 (0.68), 0.93, 0.70 (0.64), 9.50 / 9.60
(9.48 / 9.50), 0.007, 2.63. GAP-12 costs nothing measurable; validation remains the cost, and the
UI must keep one `validate_version` in flight.

**O1–O5 after S5.** O4's server half is implemented on `pw-backend`: `apply_op_values` changes the
base room's entered price once by the parsed op and value (HALF_UP to the contract currency), and
the workspace stores the result as ABSOLUTE (the integration test above saves it that way). The
client half — the base-row cell committing `ABSOLUTE <server result>`, "70.00 → …" while pending,
Ctrl/Cmd+Enter over a selection — is S9 and not built; if the owner chooses O4's alternative
(refuse relative entries on the base room), the endpoint stays for the bulk Adjust… (§3.10, S10),
which does not depend on O4. O1–O3 and O5 are unchanged: their parse is only in S1's `shorthand.ts` on
branch `pricing-workspace`, not merged here, and the board cells are S13. All five stay owner
input 13.

**Decision (implemented on the frontend lane: S1, S7, S6; recorded at the lane merge).** The
frontend slices ran on branch `pricing-workspace`, which had no ADR-061 until `pw-backend` was
merged into it, so their decisions are recorded here, next to the backend's.
- *S1: the shorthand parser (D4, D10; the parse of O1–O3 and O5).*
  `frontend/src/tex/screens/rates/lib/shorthand.ts` is pure (no runtime imports, erasable syntax
  only, no `parseFloat` / `Number` / `parseInt`). `parseShorthand(input, ctx, {minorUnits})` for the
  contexts `room`, `occupancy`, `board` and `period_adjust` answers `{kind: "rule", op, value}`,
  `{kind: "clear"}`, `{kind: "base"}` (boards only) or `{ok: false, code, op?}`; the value is
  canonical decimal text, never `-0`. The points the design left open are read as follows:
  - the checks run in the order SYNTAX, OP_NOT_ALLOWED (an op outside the context's
    `OPS_BY_CONTEXT`), the number limits PLACES (9), RANGE (12 integer digits), DIGITS (15
    significant), then AMBIGUOUS; so `1234567890123` in `period_adjust` is OP_NOT_ALLOWED(ABSOLUTE),
    not RANGE. Every error except SYNTAX carries the op;
  - AMBIGUOUS (O5) applies to amount ops in currencies with fewer than 3 minor units; the integer
    part is judged by its value (`001.500` and `0001.500` are refused like `1.500`), the fraction
    as typed;
  - the 40-character limit counts after character mapping and trimming ASCII spaces; tabs and line
    breaks are refused on the raw input;
  - `AMOUNT_OPS.occupancy` includes FIXED (a fixed slot price is an amount), with `isAmountOp(ctx,
    op)`; the parser never produces FIXED or INHERIT (advanced popover only);
  - `editText(op | "BASE", value, ctx, {decimalMark, minorUnits})` canonicalises the stored value
    (`245.000000000` → `245`) and adds one trailing zero where the stored value has the ambiguous
    shape (`12.345` in a 2-decimal currency → `12.3450`), so every value's edit text parses back to
    it; `displayText` never pads, so its text parses back only in 3-decimal currencies or without
    that shape. The clipboard (S10) copies `editText`, never `displayText` (the doc comment on
    `displayText` says otherwise: open);
  - stored pairs the parser cannot produce never read back as a different calculation: room ADD −5
    edits as `-5` (read back as SUBTRACT 5: the same arithmetic, another op label, so S9 must not
    re-commit an unchanged edit text), and a negative ABSOLUTE, FIXED, MULTIPLY or PERCENT_OF edits
    as text the parser refuses (SYNTAX), not as another op;
  - `normaliseDecimal` also takes a leading sign, for S14's comparison of server strings; exponent
    notation is SYNTAX; a server string beyond the limits is an error, which S14 must treat as
    unreadable, not as a mismatch.
- *S7: design-system primitives* (`frontend/src/tex/ui`: `grid-model.ts`, `grid.ts`,
  `placement.ts`, `keys.ts`, `popover.tsx`; AriGrid and ExtrasGrid unchanged; no new dependency):
  - no positioning library: `placement.ts` (pure) flips and clamps; below 640 px a Popover is a
    bottom sheet;
  - the overlays form one layer stack: Escape closes the innermost layer first (a shown tooltip is
    a layer), a pointerdown in a child layer does not close its parent, and panels are portaled
    into an `aria-modal` ancestor (a Menu inside a Drawer);
  - Tab past a Popover's last field (Shift+Tab before its first) closes it and continues from its
    trigger;
  - tooltips show only on hover or keyboard focus (`:focus-visible`) after 300 ms, never on touch or
    after a click, and never carry essential information. Known: after an icon-only Menu is closed
    from the keyboard, focus put back on its button matches `:focus-visible` in Chromium, so the
    button's label tooltip shows (it repeats the accessible name; the code comment says it does
    not: open);
  - Ctrl/Cmd+letter shortcuts read `shortcutLetter(e)` (the physical key), so they work on every
    keyboard layout;
  - the keyboard grid (`useGridSelection`, `useGridNavigation`) has one tab stop, selects only
    editable cells, and Escape clears only a multi-cell selection. Caveat: inside a Drawer or
    Dialog, `useModal` takes Escape first (document capture phase), so a grid placed there could
    not clear its selection with Escape; no planned view puts one there, and one that does must
    register the selection as a layer.
- *S6: the pure workspace model* (`frontend/src/tex/screens/rates/workspace/{model, occupancy,
  periods, bands, history, rows}.ts`, `lib/keys.ts`; runtime imports only among themselves and
  `shorthand.ts`, pinned by a test). Every edit writes ordinary rows (D1) and computes no money:
  - a cell entry leaves the cell with exactly one row: the first is updated in place and keeps its
    `_key` / `_name`, its twins are removed, and clear removes every row of the cell (the design's
    "at most one row per identity"; ROOM_RULE_DUPLICATE, OCC_DUPLICATE and BOARD_DUPLICATE stay the
    server's backstop);
  - a room's period row equal to its All-periods rule (canonical decimal comparison) is dropped,
    because `rooms._candidates` then falls back to exactly that rule (the same price). Never for
    occupancy: under occupancy precedence v2 (ADR-043) a PERIOD rule outranks room-scoped rules,
    so dropping one could change a price;
  - D11 and O4's client half: a relative op on the base room returns `needsServer {room,
    targetPeriod, op, value, current}` (the entered ABSOLUTE or FIXED price the cell resolves to)
    and computes nothing; `applyAdjustResults` writes the server's `apply_op_values` answer as
    ABSOLUTE; without an entered price the answer is BASE_NO_PRICE. On any other room a relative op
    writes a formula from the room's default base (NO_BASE_ROOM without one);
  - boards: a priced entry clears `is_base` (the engine ignores a base row's amount, so the typed
    value would be lost); a new period- or room-scoped row copies `child_percent` and `infant_free`
    from the row it overrides; BASE is exclusive across boards; a previous base board without an
    amount is left blank and non-base, and the save's blank-value guard (GAP-8) then asks for its
    price instead of storing 0;
  - `setBaseRoom` is exclusive (D6) and keeps the new base room's own formulas: the engine prices
    them as before, but the matrix then shows a formula on the base row and a relative entry there
    answers BASE_NO_PRICE (S9 warns or offers to convert: open);
  - the occupancy ladder is scope-local ("All rooms" shows the rules without a room, a room scope
    that room's rules) and does not re-rank across scopes or precedence levels; the server's
    resolved line is the truth;
  - `nextBandCode` skips codes that orphan occupancy rules still name, so a new band never picks
    them up;
  - `toRow` keeps the saved row name as `_name` (the saved rule id); `keepKeys` keeps client keys
    across a save (`tables.settleState`: `keepKeys`, then `overSaved`, then the selling terms, the
    logic `VersionEditor` had, now shared); `overlayPayloadOf` is `payloadOf` plus `_key` on every
    row, the fingerprint unchanged.

  Client model timings (node, 40 rooms × 40 periods, 859 rates, 480 occupancy rules): `matrixModel`
  with all 1,640 cells 1–2 ms, `ladderModel` 2–3 ms, `groupCombinations` ≤ 2 ms, `boardModel`
  0.3 ms, `applyRoomEntry` 0.1 ms.

**Tests (S1, S7, S6).** `npm run test:unit` (`node --test`, Node ≥ 22.18; CI runs it on Node 24):
`shorthand` (23: every accepted, refused and AMBIGUOUS example of the design, the §3.4.4 table in
all four contexts, the round trip of every parser-producible pair with both decimal marks and
minor units 0, 2 and 3), `grid-selection`, `placement`, `keys` (24 together), `workspace-model` (37),
`workspace-occupancy` (14), `bands` (10), `history` (8), `edits` (5): 121. `npm run test:dom`
(Playwright on a harness page, in CI): 24 checks of the overlays and the keyboard behaviour of
Popover, Menu, Tooltip and the grid hooks, at 1200 × 800 and on a 375 × 700 touch phone.

**The lane merge.** `pw-backend` (S2–S5) merged into `pricing-workspace` (S1, S7, S6); both lanes
start from main `1575c8b` (no newer main). The lanes touch disjoint files, so there were no textual
conflicts; this section is where their decisions meet. The contract between them, checked on the
merged tree:
- the overlay payload: `overlayPayloadOf` sends `_key` on every row of every table; the server
  names each overlaid row `~<_key>` and refuses a key used twice in one table (S4); `newKey()` is
  unique per page load, and `keepKeys` and `copyRow` never repeat a key;
- rule ids: `~<_key>` for unsaved data, the saved row name (`_name`, kept by `toRow`) otherwise;
- O4 end to end: the model's `needsServer {op, value, current}` is `apply_op_values(values:
  [current], op, value)`, and its answer is written back as ABSOLUTE. On the merged tree, the base
  room STD with an entered 100 and `+10%` in P1 gives `needsServer {op: "ADJUST_PERCENT", value:
  "10", current: "100"}`; the S5 integration test answers `110.00` for that call and saves it as
  ABSOLUTE; `applyAdjustResults` writes P1 = ABSOLUTE `110.00` and leaves the All-periods 100;
- the frontend types of S2–S5 (`lib/types.ts`) type-check with the S6 model and the S1 parser
  (`tsc -b`).

**Verification of the merged tree** (merge `37a400b`, migrated with it): all 38 integration modules
**831 OK** (10 skipped, as before the merge; among them `test_pricing_workspace_api` 48,
`test_commercial_flows` 63, `test_critical_journey` 31, `test_security_regressions` 59,
`test_age_bands` 11, `test_money_fields` 9, `test_snapshot_integrity` 13,
`test_modification_determinism` 27); 491 Python unit tests; ruff; `npm run test:unit` 121;
`npm run test:dom` 24; `tsc -b`, `npm run build`, `i18n:tex`; eval harness 76/76, front-desk
journey 13/13, banquet 101 OK; Playwright against the merged tree's own servers: `contract-admin`,
`editor-edits`, `critical-journey`, `policy-revisions`, `booking` (desktop and mobile) and
`restrictions-grid`, 15/15. The editor E2E is the first run of the existing version editor against
the S2 blank-value guard; it passes (its flows always type a value).

**Performance of the server-side draft overlay on the merged tree** (`bench_pricing_workspace`,
best of three, seconds; the same large ORS-shaped drafts as in S3–S5):

| Call | Realistic: 12 rooms × 26 periods, 1,406 rows, 346 KB | Near the row cap: 12 × 40, 4,539 rows, 1.13 MB |
|---|---|---|
| `save_version` (once) | 0.71 | 2.52 |
| the overlay alone (`_overlay`) | 0.16 | 0.49 |
| `price_matrix`, saved draft: the pre-S3 keys / all keys | 0.05 / 0.07 | 0.14 / 0.16 |
| `price_matrix`, unsaved data | 0.23 | 0.66 |
| `price_matrix` + 12 sample parties, saved / unsaved | 0.13 / 0.29 | 0.39 / 0.96 |
| `preview_price` (7 nights), saved / unsaved | 0.06 / 0.22 | 0.16 / 0.69 |
| `validate_version`, saved / unsaved | 2.03 / 2.11 | 9.36 / 9.80 |
| `apply_op_values`, 500 prices | 0.007 | 0.007 |

The benchmark's equivalence checks pass (the unsaved data answers what the same data saved
answers: cells, sources, party totals and errors, issue codes, quote totals and the nights'
subtotals). The figures match S5's: the frontend lane adds no server work. The reading stands: the
overlay costs 0.2–0.5 s per call; the matrix and the price test answer within a 300 ms debounce's
budget on the realistic contract (0.2–0.3 s) and within a second near the cap; validation is the
cost (2.1 s realistic, 9.8 s near the cap, with or without data), so the workspace (S8, S9, S15)
must keep at most one `validate_version` in flight per editor, drop stale answers and lengthen the
debounce with the draft. No server-side concurrency guard exists (open).

**O1–O5 after the lane merge** (all five provisional, owner input 13 in `GO_LIVE_READINESS.md`;
none changes how the engine prices: each maps an entry onto an op the engine already has). Checked
on the merged tree by the unit suites and a probe of `parseShorthand` + the model:
- *O1*, implemented in the parser and the model: a board cell's bare `100` or `=100` →
  ABSOLUTE 100, stored in the board row's `adult_amount` with `is_base` 0; the engine
  (`boards.py`) reads an ABSOLUTE board amount as a price per room per night. Not built: the board
  cells and the reading line that says so before commit (S13).
- *O2*, implemented in the parser and the model: a board cell's `-20` → ADD −20 (per adult).
  Not built: the board cells (S13).
- *O3*, implemented in the parser and the model: a board cell's `50%` → ADJUST_PERCENT 50 (`+5%`
  → ADJUST_PERCENT 5). Not built: the board cells (S13).
- *O4*, implemented in all three layers that exist: the parser reads `+10%` in a room cell as
  ADJUST_PERCENT 10; the model turns a relative entry on the base room into `needsServer` with the
  entered price it resolves to (BASE_NO_PRICE without one) and never computes; `apply_op_values`
  applies it once, HALF_UP to the contract currency; the model writes the answer as ABSOLUTE for
  that period only. Not built: the base-row cell commit, the pending "70.00 → …" and
  Ctrl/Cmd+Enter over a selection (S9).
- *O5*, implemented in the parser: an amount with the shape `1.500` (`1.500`, `+1.500`, `-1.500`:
  the ops of `AMOUNT_OPS` in each context) is refused as AMBIGUOUS, with the op, in 0- and
  2-decimal currencies and read as 1.5 in 3-decimal ones; a factor (`x1.500`) or a percentage is
  not an amount and is unaffected, as are `1500` and `1,5`; the model passes the error back and
  stores nothing. Not built: the message "Is this 1500 or 1.5? …" in the six languages (S9 / S15).

**Open after the merge** (none introduced by it): the overlay does not run `_validate_links` or the
sale/stay window-order check, so "no issues" does not mean "saves"; the cross-hotel rate plan /
policy gap in `build_terms` (tenant isolation, needs its own fix and a `test_security_regressions`
case); party cells are full-precision decimal strings while the quote uses 6 places; no
server-side concurrency guard for validation; `VersionDoc.validation_report` is typed as an object
while the server stores a list; `issueTab` counts BOARD_* under settings until S8; the S1, S6 and
S7 review items noted above (`displayText`'s comment, the restored-focus tooltip, four no-op edits
that return new tables, the base room keeping its own formulas, the missing test of a formula base
cell answering BASE_NO_PRICE, `npm run test:unit` needing Node ≥ 22.18).

**Decision (implemented in S8: the four sections, the context header, the live preview).** Branch
`pricing-workspace`, frontend only; no endpoint, payload, price or rule changes.
- *Sections and hashes (D5, §2).* The version editor's outer tablist keeps its name "Version
  sections" and holds Pricing (default), Commercial rules, Offers & promotions and Preview & audit.
  The pure `workspace/sections.ts` parses a hash into a place: the new `#pricing`, `#rules`,
  `#rules/<table>`, `#offers`, `#preview`, and the old tab ids as aliases (`#rooms`, `#periods`,
  `#rates` → Pricing; `#ages`, `#occupancy`, `#boards` → Pricing with that region named, so S11 and
  S13 can open it; `#plans`, `#settings` → Commercial rules with that inner tab). A hash that names
  nothing leaves the default. Loading never rewrites the hash (a `#plans` link stays `#plans`); the
  tabs write the canonical hash with `replaceState` (`#pricing`, `#rules/<table>`, …), and
  Commercial rules remembers its inner tab. The cross-contract lists open `#pricing`,
  `#occupancy` and `#plans`.
- *Commercial rules* is an inner tablist "Rule tables" with the ten-tab editor's own editors,
  unchanged: rate plans, settings, rooms, periods, room prices, child ages, occupancy rules (label
  `rates.tab.occupancy_rules`; `rates.tab.*` are kept for the policy editor) and boards, each with
  its row count and the issues its editor lists. *Offers & promotions* is the OffersTab. *Preview &
  audit* is the price test, the price matrix, every issue (the live check, or the report stored at
  publish) and the version's facts. *Pricing* hosts the existing room price grid until S9; for a
  viewer without cost (`doc.cost_hidden`) it lists rooms, boards and rate plans under "Amounts are
  not shown to your role".
- *Issue sections.* `issueTab` now answers the section (`sections.issueSection`, §2): Pricing for
  ROOM_*, PERIOD_*, NO_PERIODS, NO_ROOMS, INCLUDED_ADULTS, AGE_BANDS*, OCC_*, NO_BASE_BOARD and
  BOARD_* (the S4 review's open item); Offers for OFFER_*; Commercial rules for RATE_PLAN_BOARD,
  SALE_WINDOW, STAY_WINDOW, CURRENCY, BUILD and anything else. Two cases §2 does not name are read
  as Pricing because the user fixes them there: NO_AGE_BANDS (about the bands, though it does not
  start with AGE_BANDS) and an issue whose `ref` names a party (the publish sweep reports under the
  engine's own codes, e.g. NO_CHILD_RULE, AMBIGUOUS_OCCUPANCY_RULES). The Rule tables keep the old
  per-table lists (`issueTable`), with BOARD_* on Boards, NO_AGE_BANDS on Child ages and a sweep
  party on Occupancy rules; each table's issues lie in its section's count (tested).
- *The live preview, `useDraftPreview(doc, state, {fingerprint?, parties?, partyRoom?})`* (§3.14).
  The request policy is the pure `workspace/draftPreview.ts`; the hook binds it to React. The mode
  comes from the server's flags only: *overlay* when `doc.editable` (POST `price_matrix` and
  `validate_version` with `data = overlayPayloadOf(state)`), *saved* when not editable and not
  `cost_hidden` (one GET of `price_matrix` per `doc.modified`, never `validate_version`; the issues
  are `validation_report`, "Checked when published"), *catalogue* when `cost_hidden` (no request
  at all). In overlay mode:
  - the matrix is asked 300 ms after the last edit (the first at once), and a newer edit aborts the
    call it makes stale;
  - at most one `validate_version` runs (`latestOnly`): an edit made while one runs waits, only the
    newest waits, and it is sent after the running one ends; the running call is not aborted (the
    server would finish it anyway). Validation waits ≥ 1.2 s after the last edit and at least as
    long as the previous one took (at most 10 s), so a large draft is not checked more often than
    it can be; the first check of a draft runs at once;
  - results are tagged with the fingerprint of the state they were computed for (`forKey`,
    `issuesForKey`); `stale` / `issuesStale` say they describe another state, a refresh is on its
    way or the contract header changed (`refetch`). The request key also holds the rows' client
    keys, because the rule ids of an overlay answer are `~<_key>` and the fingerprint ignores keys:
    a reload of the version (new keys, same content) asks again; a save (keys kept) does not;
  - a save no longer triggers its own validation: the overlay answer for the saved content stands,
    and the next edit is checked as usual.
  Nothing is computed from the answers: cells, totals and counts are the server's strings and
  lists.
- *The Check button* runs the live check at once (`validateNow`), through the same single flight.
  It stays enabled only when nothing is unsaved ("Save your changes first"), so what it checks is
  exactly the saved draft; it sends the payload like the live check, so its issues carry the same
  `~<_key>` rule ids. Publish runs its own server check, as before.
- *The context header* (§3.2, `workspace/ContextHeader.tsx`) is sticky under the shell header from
  768 px (on phones it scrolls, and its chips fold behind "Details" so the page never scrolls
  sideways). It shows the version and status (with "Read-only" and "Unsaved changes"), the live
  check chip (counts; a click lists the issues in a Popover; hidden in catalogue mode and for a
  frozen version without a stored report), contract, market, contract and selling currency, pricing
  basis, base room, base occupancy (PERSON: per person; ROOM: the base room's effective
  `included_adults` from the matrix's capacity), and the sale and stay windows. The page header's
  actions moved here with their names and states (Price test, Discard, Check, Publish, Save with
  Ctrl S and `aria-busy`; on a frozen version "Open draft Vn" / "Create new draft from this
  version"). The selling windows and selling currency are edited in a Popover when the draft owns
  them (`selling_editable`); they are ordinary draft state, saved with Save. The section tablist
  sits in the sticky header.
- *The basis popover* (§3.2.1, `workspace/BasisPopover.tsx`): the chip is a button
  (`aria-haspopup="dialog"`, "Pricing basis: Per person") only while `can_edit_contract &&
  !basis_locked`; locked, it is a read-only chip with a lock and the description "Fixed after the
  first publish"; without the right, plain text; an agent's catalogue carries no basis, so no chip.
  The Popover (non-modal) has a Segmented Per person / Per room, the consequence line and the notice
  that it saves the contract header at once; Apply calls `save_contract({name, pricing_basis})`
  (which re-checks `contract.edit` and the publish lock); the answer patches
  `doc.contract_doc.pricing_basis` without touching `EditorState` or the save base, then the
  preview refreshes; a refusal shows the server's message in the Popover.
- *The price test* (`PriceTestPanel`, the existing calculator) is shown when `doc.can_preview`
  (else `can('price.view_cost', <the version's hotel>)`, no longer the shell's hotel), full size in
  Preview & audit and in a Drawer from the header's "Price test". With unsaved edits it sends
  `data` and says "Priced with your unsaved changes."; no save is made. Its result view is S14's.
- *One matrix call per page.* The room price grid (Pricing and the Rule tables) and the Preview &
  audit matrix read the live preview instead of fetching `price_matrix` themselves; the grid still
  hides resolved prices while there are unsaved edits (S9 replaces it).
- *Types.* `VersionDoc.cost_hidden`; `validation_report` is typed as the list the server stores
  (an older `{issues}` object is still read: `storedIssues`), the S4 review's open item.

**Deviations from the slice text, with reasons (S8).**
1. NO_AGE_BANDS and sweep-party issues count on Pricing (above): §2 does not name them, and
   Commercial rules would send the user to the wrong section, the S4 review's objection to BOARD_*.
2. The Check button sends the payload (the saved draft's own, since it is enabled only without
   unsaved changes) instead of validating by name, so there is one kind of issue and one flight.
3. The room price grid (`RatesTab`, not in the slice's file list) takes the preview's matrix
   through `TabProps.preview` and fetches only without it. Otherwise the page would make a second
   `price_matrix` call ("once per doc.modified") and an agent's Rule tables would make a refused
   one (the catalogue check).
4. The Price test drawer is the existing `Drawer`, which is modal; §3.13 wants it non-modal on
   desktop. S14 rebuilds the drawer and must make it non-modal for S16's zero-modal budget.
5. The workspace import guard (S6's test) leaves out React bindings named `use<Name>.ts`
   (`useDraftPreview.ts` is in the slice's file list, and S9's `useWorkspaceHistory.ts` will be
   too); they are not in its allowed set either, so no pure module can import one. The request
   policy the hook applies is the pure, guarded and unit-tested `draftPreview.ts`.
6. The E2E flow `openTab` keeps its ids and gains `openSection`; its panel is found by name
   (the section and the Rule table are both tab panels). `entry-branding`'s server-rendered source
   check needs `TEX_E2E_BENCH` set to the tree's own bench when it runs against a Vite dev server
   (its default is the :8000 server, which runs another commit); no spec was changed.

**Tests (S8).** `npm run test:unit` 143 (121 + 22): `sections.test.ts` (10: the sections and
Rule tables, new hashes, `#rules/<table>`, the aliases, hashes that name nothing, the canonical
hash round trip, §2's code map with BOARD_*, NO_AGE_BANDS and sweep parties, the per-table map,
each table's issues inside its section's count) and `draft-preview.test.ts` (12: the three modes,
the requests of each (overlay POSTs with data, saved a GET and no validation, catalogue none,
parties only with a room), the stored report as a list or an object, the debounces, and the single
flight: one call at a time, only the newest waiting, the running key not queued again, a refused
call freeing the flight, cancel, a late cancelled call). Fail-first: both files fail on the
unchanged tree (`ERR_MODULE_NOT_FOUND`: 123 tests, 121 pass, 2 fail). The S6 import guard failed on
the new hook (runtime import of `react`) until it left out React bindings.

**Verification (S8).** `tsc -b`, `npm run build`, `npm run i18n:tex` (43 new keys in the six
languages), `npm run test:unit` 143, `npm run test:dom` 24, Python unit 491, ruff. The pricing,
contract, booking and security integration modules, migrated with this tree (S8 changes no server
code): `test_pricing_workspace_api` 48, `test_commercial_flows` 63, `test_critical_journey` 31,
`test_security_regressions` 59, `test_age_bands` 11, `test_money_fields` 9,
`test_snapshot_integrity` 13, `test_audit_trail` 15, `test_concurrency` 8, `test_pricing_policies`
14: 271 OK. The full regression and the upstream suites were last run at the lane merge (831 OK;
76/76, 13/13, banquet 101) and are due again at the final slice. Playwright
against the tree's own servers (bench :8016, Vite :5186): `contract-admin`, `critical-journey`,
`editor-edits` (3, with the Discard and in-flight-save tests), `entry-branding` (9, #plans selects
"Rate plans"; 1 skipped as before, no two-factor user), `policy-revisions`, `restrictions-grid`:
all pass, with no spec changed. The slice's manual checks were run as a browser script against the
same servers (not committed; S16 owns the workspace specs), 7/7: old hashes land on their section
and the tabs write canonical hashes; the basis popover switches a ROOM contract to PERSON and back
with no modal, `get_contract` agrees, the chip and the grid's unit badge follow, the draft stays
clean, and an unsaved price survives the switch, with no `save_version`; the Price test drawer
prices an unsaved price (the quote's night unit is the unsaved 300) with `data` and no save; two
twin HB board rows count an error on the Pricing badge and on the Boards table, not on Commercial
rules, and the live check lists BOARD_DUPLICATE; after publish the basis chip has no trigger and a
lock described "Fixed after the first publish", nothing is editable, one GET `price_matrix` and no
`validate_version` are made, and the page does not scroll sideways at 375 px; with `can_preview`
false there is no Price test button and Preview & audit shows the permission notice; an agent sees
the catalogue with no `price_matrix`, `validate_version` or `preview_price` request and no 403.

**Performance after S8** (the first slice whose screen calls the overlay while the user types).
- *In the browser*, on a large draft saved in the shared site (3 rooms × 52 weekly periods, 6
  occupancy rules and 3 board supplements per room and period: 1,543 rows, a 296 KB payload),
  through the Vite proxy to the tree's bench, times from request start to response end, three runs:
  on opening the version `price_matrix` with data 0.49–0.53 s and the first `validate_version`
  1.39–1.45 s; a burst of 20 keystrokes 80 ms apart (3.0–3.2 s) made exactly one `price_matrix`
  (0.24–0.27 s) and one `validate_version` (1.09–1.12 s) after the pause, and everything had
  answered 2.45–2.48 s after the last key; 7 keystrokes typed while a validation ran made two
  validations in all (the running one, then one for the newest state, started after the first
  ended) and never two at once. `save_version` of that draft: 0.92–0.98 s.
- *On the server* (`bench_pricing_workspace` on this tree, best of three, seconds; realistic 12
  rooms × 26 periods, 1,406 rows, 346 KB / near the row cap 12 × 40, 4,539 rows, 1.13 MB): the
  overlay alone 0.16 / 0.54; `price_matrix` with unsaved data 0.24 / 0.67 (0.29 / 0.92 with 12
  sample parties); `preview_price` with unsaved data 0.23 / 0.64; `validate_version` saved /
  unsaved 2.00 / 2.21 and 9.53 / 9.90; `apply_op_values` (500 prices) 0.007; `save_version` 0.74 /
  2.40. The equivalence checks pass. The figures match the lane merge's: S8 changes no server code.
- Reading: the matrix answers well inside the time a user pauses; validation stays the cost, and
  the client now bounds it (one in flight, the debounce as long as the last check took). The server
  still has no guard of its own against several editors (or tabs) validating at once (open).

**O1–O5 after S8** (all five provisional, owner input 13): unchanged by S8, which builds no entry
cell and parses no shorthand. As after the lane merge: O1–O3 are in the parser and the model (the
board cells are S13), O4 in the parser, the model and `apply_op_values` (the base-row cell commit is
S9), O5 in the parser (its message in the six languages is S9 / S15).

**Open after S8.** The Price test drawer is modal until S14 (deviation 4). `#ages`, `#occupancy`
and `#boards` land on Pricing without opening anything until S11 and S13, so the "Occupancy rules"
list opens the room price grid meanwhile. §3.2's base room select and ROOM base-occupancy stepper
are read-only chips (the "Set as base" action is S9's; no slice builds the stepper yet). The live
check lists issues without anchoring them (S15). `rates.preview.unsaved` is no longer used (kept
in the catalogues). Still open from before: the overlay skips `_validate_links` and the window
order; the cross-hotel rate plan / policy gap in `build_terms`; party cells in full precision; no
server-side validation concurrency guard; the S1, S6 and S7 review items listed above.

**S8 review follow-up (2026-09-25).** Two verifier findings on S8, both fixed; one more fault of the
same kind found while fixing them.
1. *Drafts above the overlay's row cap lost all feedback.* S8 sent every editor request through
   the overlay, which refuses more than 5,000 rows, while `save_version` has no cap. A realistic
   weekly contract has more (12 rooms × 52 periods with 6 occupancy rules and 3 board supplements
   per room and period: 5,892 rows). For such a draft the Check button, the check on opening and
   the room price grid's resolved prices all got the refusal, contrary to §3.15 ("The Validate
   button still validates the saved draft").
2. *"Could not run" never showed.* After a refused check, `issuesStale` stayed true, so the chip
   showed its spinner and older counts indefinitely, and nothing retried. The Preview & audit
   matrix showed "Updating…" over a dimmed older matrix in the same way.

**Decision (S8 review follow-up).**
- *The saved draft by name* (`draftPreview.previewSource`). In overlay mode the saved draft is
  asked for by name, with no payload and so no row cap (`price_matrix` by GET without `data`,
  `validate_version` by GET with `name` only, as the Check button asked before S8), in three
  cases:
  - the state on screen is the save base (`useDraftPreview(…, {base})`: the fingerprint equals the
    editor's save base);
  - the Check button asked (`validateNow`);
  - the overlay does not take the draft.

  Only unsaved changes the overlay takes are POSTed with `data`. By-name answers name rows by
  their server names, which §3.15's anchoring already accepts (`_name`). S8's deviation 2 ("the
  Check button sends the payload") is withdrawn.
- *The cap, from the server* (additive).
  - `get_version` gives an editor of an editable draft `overlay_max_rows` (5,000).
  - The overlay's refusal above it is typed, `OverlayTooLarge(frappe.ValidationError)`: the same
    417 and the same message, and still caught as a ValidationError.
  - The client counts the rows it would send (`overlayRows`, an integer count over the eight
    tables, as the server counts them) and does not send the overlay above the cap.
  - If a refusal arrives anyway (the field is missing), the client stops sending the overlay for
    that version at that row count or above (`overlayFits`). A blank value's refusal is not
    mistaken for the cap (`isTooLarge`).
- *Answer keys* (`previewKeys`).
  - While the overlay takes the draft, answers are keyed by the content on screen (fingerprint
    and row keys), however they were asked. A save of what is on screen therefore keeps them: no
    re-check after a save, as in S8.
  - Above the cap they are keyed by the saved revision (`doc.modified`). Edits ask nothing; a
    save or Check asks again.
- *Above the cap with unsaved changes* (`savedOnly`). The answers are the saved draft's, and each
  view says so:
  - the Preview & audit matrix shows "Saved draft only" and a notice ("This draft has more than
    {max} rows, too many to preview unsaved changes: the prices and checks shown are the saved
    draft's. Save to include your changes.");
  - the live check popover and the Live check card show the same notice;
  - the Price test prices the saved draft without `data`, under its pre-S8 notice ("You have
    unsaved changes. The price check uses the saved draft.");
  - the room price grid hides resolved prices, as it does for any unsaved change.

  Nothing is refused or shown as an error.
- *The call state* (`callState`: ready, busy or failed). It is derived from the key of the answer
  wanted, the key of the last answer, the key of the last failure (failures are now stored with
  their key) and whether a call is in flight. A failure for the state on screen is "failed", not
  "busy":
  - the chip shows its warning mark, named "The live check could not run", with no spinner and no
    older counts;
  - its popover and the Live check card give the server's reason and Try again (`refetch`);
  - the preview hands out no issues while the check has failed, so the section badges and the
    lists do not count older issues as current;
  - the matrix card shows the error and Try again instead of "Updating…" over an older matrix;
  - `error` and `issuesError` are those of the current state only (the room grid's legend reads
    `error`).

  Nothing retries on its own. An edit or Try again asks again.
- *Found while fixing* (`alreadyChecked`). Undoing to the last checked state while a check of
  another state was in flight skipped the re-check. The other state's answer then replaced the
  issues, and the chip stayed stale for good. A state already checked is now asked again when a
  check is in flight.

**Tests (S8 review follow-up).**
- *Frontend unit tests:* `npm run test:unit` 148 (143 + 5, all in `draft-preview.test.ts`). They
  cover:
  - a clean state and the Check button give by-name requests with no data, and unsaved changes
    the overlay takes give the POST with data;
  - the row count, the cap and the typed refusal;
  - the answer keys (a save keeps them while the overlay takes the draft; above the cap edits do
    not change them and a save or Check does);
  - the call state (a refused check for the current key is "failed", not "busy");
  - the re-check guard.
- *Integration tests:* `test_pricing_workspace_api` 50 (48 + 2):
  - `test_above_the_row_cap_the_saved_draft_still_answers_by_name`: with the cap patched to the
    payload's rows − 1, `price_matrix`, `validate_version` and `preview_price` with `data` raise
    `OverlayTooLarge` with the unchanged message; `save_version` takes the draft, and the saved
    draft is priced (the new price), validated and quoted by name; a blank value still raises a
    plain ValidationError;
  - `test_an_editor_is_told_the_overlay_row_cap`: a Revenue Manager and a contract editor get
    5,000, Finance and an agent nothing.
- *Benchmark:* `bench_pricing_workspace` gains `test_above_the_row_cap`.
- *Fail-first:*
  - `draft-preview.test.ts` fails on the unfixed tree (missing exports: 132 tests, 131 pass,
    1 fail), and so does the guard's test before the guard;
  - on the unfixed server, `test_pricing_workspace_api` ran 50 tests with 2 failures (the
    Revenue Manager and editor subtests, `None != 5000`) and 1 error (`KeyError:
    'overlay_max_rows'`).

**Verification (S8 review follow-up).**
- *Build and unit tests:* `tsc -b`, `npm run build`, `npm run i18n:tex` (2 new keys in the six
  languages), `npm run test:unit` 148, `npm run test:dom` 24, Python unit 491, ruff.
- *Integration:* the full regression on this tree, migrated with it: 38 modules, 833 tests OK (10
  skipped, as before), `test_pricing_workspace_api` 50 among them. The opt-in
  `bench_pricing_workspace` ran 3 OK.
- *Upstream suites:* 76/76, 13/13, banquet 101.
- *Playwright:* `contract-admin`, `critical-journey`, `editor-edits` (3), `entry-branding` (9, 1 skipped
  as before: no two-factor user), `policy-revisions` and `restrictions-grid` all pass (16 passed),
  against the tree's own servers, with no spec changed.

The fixes were checked in the browser against the tree's own servers (bench :8016, Vite :5186),
with a scratch script that is not committed, 4/4:
1. *A clean draft:*
   - opening it makes only GET `price_matrix` calls without `data` and one GET
     `validate_version` by name (200);
   - Check makes one GET `validate_version` by name and no `price_matrix` call;
   - an edit POSTs both with `data`.
2. *A blank value (a new HB board row, its amount left empty):*
   - one 417 comes back. The chip is named "The live check could not run", with no `aria-busy`,
     no spinner and no counts, and the Pricing section badge counts nothing. It is unchanged 3 s
     later, with no retry;
   - the popover gives the reason and Try again, which asks once more (a second 417);
   - in Preview & audit the matrix card is an alert with the reason and Try again (no "Updating…",
     no table), and the Live check card says the check could not run;
   - typing the amount recovers the chip, the badge (as before) and the table.
3. *Above the cap (3 rooms × 354 two-day periods, 6,024 rows; `save_version` 3.1–3.2 s):*
   - on opening Preview & audit, the matrix is shown after 3.2–3.4 s and the live check after
     5.6 s. No request carries `data` and every answer is 200;
   - after an unsaved edit, no `price_matrix` or `validate_version` call is made for 3 s and the
     chip is not failed. The popover, the matrix card ("Saved draft only") and the Live check
     card say the answers are the saved draft's;
   - the Price test sends no `data` and says so;
   - Discard, then Check: `validate_version` by name, 200.
4. *The same draft with `overlay_max_rows` removed from `get_version`'s answer:*
   - the first edit makes exactly one POST `price_matrix` (417, `OverlayTooLarge`), then one GET
     `price_matrix` by name (200) and one `validate_version` by name;
   - the matrix card says "Saved draft only", with no alert;
   - a further edit asks nothing.

**Performance above the cap** (`bench_pricing_workspace` `test_above_the_row_cap` on this tree,
best of three, seconds; validation run once). The draft is 12 rooms × 52 periods with 6 occupancy
rules and 3 board supplements per room and period: 5,892 rows, a 1,469 KB payload.

| Call | Seconds |
|---|---|
| `save_version` | 3.09 |
| `get_version` | 0.27 |
| Overlay refusal: `price_matrix` with `data` | 0.24 |
| Overlay refusal: `validate_version` with `data` | 0.13 |
| `price_matrix` by name | 0.23 |
| `price_matrix` by name, 12 sample parties | 0.62 |
| `preview_price` by name | 0.18 |
| `validate_version` by name | 16.0 |

In the same run, for comparison:
- *realistic 12 × 26 (1,406 rows):* the overlay 0.155, `price_matrix` with data 0.23 and
  `validate_version` 1.99 (saved) / 2.16 (unsaved);
- *near the cap 12 × 40 (4,539 rows):* the overlay 0.52, `price_matrix` with data 0.68 and
  `validate_version` 10.0 (saved) / 9.5 (unsaved).

Reading:
- For such a contract the workspace shows the saved draft's prices at once. Its check (16 s) runs
  on opening, after each save and on Check.
- Its unsaved changes are not previewed until they are saved.
- The refusal is never made while the cap is known. When it is made, it costs 0.1–0.25 s, because
  the draft is loaded before its rows are counted.

**O1–O5 after the S8 review follow-up** (all five provisional, owner input 13): unchanged. The
follow-up builds no entry cell and parses no shorthand, so the parser, the model and
`apply_op_values` behave as after S8.

**Open after the S8 review follow-up.**
- A realistic weekly contract is above the overlay's cap, so its unsaved changes are not
  previewed. Two remedies need a decision, and neither is taken here:
  - raise `OVERLAY_MAX_ROWS`. The overlay's matrix scales well (0.68 s at 4,539 rows); its
    validation does not (9.5 s at 4,539 rows, 16 s for 5,892 by name);
  - make the overlay incremental.
- The row count in the notice is not formatted for the locale ("5000").
- Still open from S8: the modal Price test drawer until S14; no server-side validation
  concurrency guard; the items listed under "Open after S8".

**Decision (implemented in S9: the room price matrix).** Branch `pricing-workspace`, frontend
only (no server file changes). Pricing shows the workspace matrix; the Advanced "Room prices"
table stays under Commercial rules.
- *Grid.* `workspace/PriceMatrix.tsx`: `role="grid"` named "Room prices by period" (the caption
  the helpers use), rows of `columnheader` / `rowheader` / `gridcell`, `aria-rowcount` and
  `aria-colcount`, `aria-multiselectable` when editable and `aria-readonly` when not. Every row
  is its own CSS grid on one column template, `matrixView.columnTemplate(periods)` with
  `MATRIX_WIDTHS`: row header `clamp(9rem, 38vw, 16rem)`, All periods and each period `7.5rem`,
  "+ Period" `7rem`. The widths depend on the viewport only, so separate grids (the rows, and the
  ladder and boards of S11 and S13) line their period columns up exactly. Sticky header row and
  first column in the matrix's own scroll box; the page does not scroll sideways at 375 px.
- *Rows and labels* come from `model.matrixModel` (§3.3.1, §3.11): the base row ("Base person
  price" / "Base room price · N adults included"), Formula + Resolved for a derived room, Manual
  price (+ Resolved with an All-periods price). N is the effective `included_adults` the server
  priced with (`price_matrix` capacity), else the room row's, else the room type's. The row
  header shows ★ and BASE, or the default derivation in words ("Formula · Standard ×1.15").
- *Cells* (`MatrixCell.tsx`) render `cellState` with a glyph and a screen-reader state (entered
  price, formula for all periods, ↳ follows all periods, ◆ period override with the "P4 replaces
  the default ×1.15: Standard ×1.2" tooltip, the pin of a fixed price, ↳ inherit, a dashed "no
  price"). Resolved rows show `useDraftPreview().matrix` with `Money` in the contract currency,
  "Not sellable" with the server's reason, and the stale style while the answer is for another
  state. Read-only cells carry a tooltip with their reason. The accessible name is the full
  sentence ("Family Suite · P4: period override, Standard Sea View ×1.2").
- *Editing* uses the S7 grid hooks: typing starts an edit with the character, F2 / Enter /
  double-click edit with everything selected; Enter / Shift+Enter commit and move to the next
  editable row (resolved rows are skipped), Tab / Shift+Tab commit and move sideways; Escape
  reverts (and drops an error draft). Leaving a cell commits a valid entry and keeps an invalid
  one as an error draft (⚠, `aria-invalid`, the message by `aria-describedby`; Escape on the cell
  drops it). The input is named "Price: {room} · {period}"; its reading line (`readingOf`, no
  arithmetic) says what the commit does: "Superior · P2 = Standard ×1.2 (replaces the fixed price
  245.00)", "Standard · P1: adjust 70.00 by +10% (calculated on commit)", a price, "a fixed price
  instead of the formula", "the same as all periods …", a removal, or the refusal. An edit text
  that did not change is never committed again (S1: ADD −5 edits as "-5"). Edit text uses the
  viewer's decimal mark (Intl); the parser takes both.
- *Commit.* `parseShorthand(text, "room", {minorUnits: contract_doc.minor_units})`, then
  `matrixView.planEntry` over the cell, or over every selected editable cell with Ctrl/Cmd+Enter:
  all or nothing; each cell by its row's rule (D11). The base-room cells of one gesture go to
  `apply_op_values` in one call (the cells show "70.00 → …"), and the whole gesture is committed
  as one history entry when the server answers: `finishEntry` plans it again on the tables as they
  are then and writes the answers as ABSOLUTE. It is refused with CHANGED when a price sent was
  edited meanwhile, with the server's NEGATIVE / NO_VALUE, or with the server's message; the entry
  then stays as an error draft. An answer for a draft that was reloaded or discarded meanwhile is
  dropped (`useWorkspaceHistory().generation`). Errors read `rates.sh.err.<CODE>`: the parser's
  codes, BASE_NO_PRICE, NO_BASE_ROOM, and BASE_FORMULA (new: a base-room cell priced by a formula,
  which "Set as base" keeps; S6 review item) and CHANGED / NEGATIVE / NO_VALUE.
- *Rule popover* (`RuleEditorPopover.tsx`, the S7 Popover, not modal), named "Edit price: {room} ·
  {period}": Rule (the room ops, INHERIT included, `rates.op.*` with their help), Value
  (`DecimalInput`, 9 places; the AMBIGUOUS guard applies to amounts here too), Derived from
  (relative ops), Applies to: this period / All periods (the All-periods rule) / selected periods
  (one row each). Apply and Remove are one history entry; the op chosen is the op stored (on the
  base room too: the popover is the explicit way to store a formula there). Opened with Alt+Enter
  (from an edit it starts with the typed rule, unless that is a relative entry on the base room),
  the ▾ trigger (shown on focus or hover, absent when read-only), Shift+F10, the ContextMenu key and
  the `contextmenu` event (right click, long press). An inherited cell's popover starts from the
  rule it follows. Focus returns to the cell, also when the edit re-rendered it.
- *Rooms* (`RoomRowHeader.tsx`): "+ Add room" (the hotel's room types not in the contract; the
  first becomes base); the room menu: Set as base (re-point formulas, on by default; a warning
  when the new base keeps formulas of its own), Derive from… (the All-periods formula and, on by
  default, the single periods'), Capacity… (a Drawer; the server's effective capacity as
  placeholders), Move up / down, Remove (a confirmation with the prices, occupancy and board rules
  it removes, and a warning for formulas of other rooms that derive from it).
- *Periods* (`PeriodHeader.tsx`): the header shows the code, name, a compact range ("1–30 Apr",
  `Intl.DateTimeFormat.formatRange`), weekday and night-adjustment badges. "+ Period" adds the next
  period (`addPeriod`) and focuses its end date (and its start, when no dated period precedes it).
  The period menu: Rename… (code and name; the three tables follow; errors inline; an unchanged
  rename records nothing), Dates… (from / to, `WeekdayPicker`, priority), Night adjustment… (the
  `period_adjust` shorthand with its reading and the note that it applies to occupancy + board,
  after the board supplement), Duplicate, Copy previous period's prices, Move left / right ("no
  effect on prices"), Delete… (a confirmation with the dependent rows). A thin PeriodStrip shows
  the periods without weekdays against the stay window and counts gaps and overlaps in text.
- *History.* `workspace/useWorkspaceHistory.ts` wraps `history.ts`: `commit(label, before, after)`
  records the tables whose arrays changed and writes them with `setTable`; `apply(label, edit)` does
  the same from the tables as last written (answers that arrive later); `undo` / `redo` put the
  recorded arrays back (their buttons, keys and toast are S10's). It lives in `VersionEditor`, which
  clears it whenever a version is loaded and on Discard, and passes it and a load epoch to the
  sections (`TabProps.history`, `TabProps.epoch`; the matrix is keyed on the epoch, so Discard also
  drops edits in progress and error drafts). Every matrix, room and period change is one entry.
- *Read-only and catalogue.* A published version (or a draft without `contract.edit`) has no
  inputs, no "Edit price:" triggers, no room or period menus and no "+ Add room" / "+ Period"; the
  grid has `aria-readonly`. An agent's catalogue does not render the matrix (S8's catalogue view).
- *Rendering cost.* What a cell shows is computed once per change of the draft, the server's
  answers, the entries in flight or the language (`cellViews`), not when the active cell moves;
  rows and cells are memoised on it, on the active cell and on the row's selection. A memoised
  cell may keep handlers older than the latest render, which is safe: only a focused cell gets
  keys, focusing a cell makes it the active cell, and the active cell re-renders with every new
  selection state. Typing re-renders only the editor. `decText` caches its Intl formatters (it runs
  for every cell).

**Deviations from the slice text, with reasons (S9).**
1. Files beyond the list: `workspace/matrixView.ts` (the screen logic, pure and unit-tested);
   `contracts/VersionEditor.tsx` and `contracts/tabs/shared.tsx` (the history must survive section
   changes and be cleared on load and Discard, so it lives in the editor); `lib/util.ts` (the
   `decText` formatter cache: the same output; alone it took an arrow key on 265 cells from 171 to
   115 ms); `tests/unit/workspace-matrix.test.ts`.
2. Delete / Backspace clear the selected cells in one entry (§3.4.1's navigation mode). S10's text
   lists it too; S10 keeps it as it is.
3. Enter / Shift+Enter skip resolved rows when they move after a commit; arrow keys still visit
   them.
4. New entry errors BASE_FORMULA and CHANGED (above); the AMBIGUOUS message is the slice's text,
   without the design's "Thousands separators are not used."
5. The popover also opens on `contextmenu` (right click, long press: §3.19's touch gesture), and
   applies the AMBIGUOUS guard to amounts (its `DecimalInput` turns "," into ".").
6. The row header puts the room name and BASE on its first line and the row label with the
   derivation on its second (the design's mock-up shows them on one line; long room names do not
   fit 16rem).
7. The Capacity… Drawer is the existing modal Drawer, as the slice says. It is not on the
   acceptance path, so S16's zero-modal budget is unaffected.
8. Column-header selection (§3.9) is left to S10 with the other range gestures.
9. The dev-server smoke is a scratch Playwright spec (as the slice allows): committed workspace
   specs are S16's, and CI runs Playwright against the committed bundles, which S16 rebuilds.

**Tests (S9).** `tests/unit/workspace-matrix.test.ts` (18): the column template; the grid rows;
a price on a base cell stored at once; Ctrl+Enter with base cells in one server list and formulas
elsewhere, completed as one result; O4 `+10%` on 70 → the server's 77.00 as ABSOLUTE; NEGATIVE,
NO_VALUE and CHANGED; all or nothing (NO_BASE_ROOM, SYNTAX, AMBIGUOUS); BASE_FORMULA after "Set as
base" and BASE_NO_PRICE for a blank price (S6 review item: that mutant now dies); `x1.20` over
`=245` restores the formula; Delete; the reading line (formula over a fixed price, adjust, fixed
price, same as default, clear, unchanged, refusals, `1.500` accepted in a 3-decimal currency);
edit text in both decimal marks (`ADD −5` → "-5", `12.345` → "12.3450"); the popover (one row per
period, the op as chosen, INHERIT without a value, All periods, Remove, unchanged); rooms (first is
base, added once, move, capacity); periods (dates, weekdays, priority, night adjustment).
Fail-first: before `matrixView.ts` existed the file failed to load (`ERR_MODULE_NOT_FOUND`).

**Verification (S9).** `tsc -b`, `npm run build`, `npm run i18n:tex` (153 new keys in the six
catalogues), `npm run test:unit` 166/166, `npm run test:dom` 24/24, Python unit tests 491 OK (no
server change). Playwright on the tree's own servers (bench :8016, Vite :5186): the scratch smoke
8/8 — 70⇥80⇥100⇥130↵ and x1.15 / x1.35 give the resolved rows 80.50 / 92.00 / 115.00 / 149.50 and
94.50 / 108.00 / 135.00 / 175.50 without a save; Superior P4 `x1.20` shows ◆ and 156.00; Deluxe
P3:P4 `x1.40` + Ctrl+Enter; Escape reverts; `abc` and `1.500` show their messages and an invalid
entry stays as an error draft; `+10%` on the base P1 becomes 77.00 through `apply_op_values`, and a
base + formula selection makes one call; Superior P2 `=245` then `x1.20` restores the formula and
renaming P2 → MAY rewrites it (`get_version` after the save: `MAY` MULTIPLY 1.2 from Standard, no
`P2` rule left); the popover (Alt+Enter, Shift+F10, the op stored, focus back); + Period with its
end date, Remove room and Add room; Delete over a selection and after Ctrl+A; a published version
read-only — and 2 more checks (Set as base with the formula warning and BASE_FORMULA, Derive from,
Capacity, Night adjustment, Dates, Duplicate and Delete with counts; no sideways scroll at 375 px).
The existing `contract-admin`, `critical-journey`, `editor-edits` and `entry-branding` specs pass
on the tree (14, one skipped for want of a 2FA user, as before).

**Performance after S9** (the Vite dev server, i.e. development React; keydown to the next
painted frame, measured in the page; demo hotels have at most three room types, so large grids
were made with many periods):
- 3 rooms × 52 weekly periods (265 cells): arrow keys median 32 ms (max 40), typing 4 ms; before
  the memoisation 171 ms. 3 rooms × 200 periods (1,005 cells): 72 ms (max 121), typing 6 ms; before
  922 ms.
- A committed formula reached the resolved rows through the overlay with `price_matrix` answering
  in 55–59 ms (3 × 52) and 122–137 ms (3 × 200) after the 300 ms debounce.
- The server-side figures of S8 (realistic 12 × 26: overlay 0.16 s, matrix with unsaved data
  0.24 s, validation 2.0–2.2 s; near the cap 12 × 40: 0.54 / 0.67 / 9.5–9.9 s; `apply_op_values`
  with 500 prices 0.007 s) still hold: S9 changes no server code. Final re-measures them on the
  merged tree.

**O1–O5 after S9** (all five provisional, owner input 13):
- *O4 (base room, relative entry) is now built end to end.* In a base-room cell that resolves to an
  entered price, `x1.1`, `+10%`, `-5`, `+5` or `50%` is parsed as the owner's table says; the reading
  line says "adjust 70.00 by +10% (calculated on commit)"; on commit `apply_op_values` applies it
  once (one call for every base cell of a Ctrl/Cmd+Enter) and the answer is stored as ABSOLUTE
  (`+10%` on 70 → 77.00, verified in the browser). Without an entered price: BASE_NO_PRICE; with a
  formula: BASE_FORMULA. The rule popover stores what it is told (the explicit way to put a
  formula on the base room).
- *O5 (AMBIGUOUS)* now reaches the screen: "Is this 1500 or 1.5? …" in the six languages, for
  amounts in 0- and 2-decimal currencies, in the cells and in the rule popover, where `12.345` is
  accepted in 3-decimal currencies. Factors and percentages are exempt. *Corrected by the S9
  review follow-up:* O5 also covers the period night adjustment (`period_adjust` ADD / SUBTRACT
  are amount ops, §3.4.3), and as built in S9 the Night adjustment popover was not
  currency-aware: it parsed without the contract's minor units, so `+12.345` and `+2.500` were
  refused as AMBIGUOUS in 3-decimal currencies too, and a stored ADD 12.345 re-opened as text that
  could not be applied. Fixed by the follow-up below.
- *O1–O3 (boards)* are unchanged: in the parser and the model; their cells are S13.

**Open after S9.**
- `Money` (the existing helper) cuts a resolved amount to the currency's decimals instead of
  rounding it: a derived unit of 108.675 reads "108.67". The exact server text is in the cell's
  tooltip and accessible name. Round half-up for display, or show the exact digits: a decision for
  the owner.
- Ctrl/Cmd+S while a cell is being edited saves the draft without the text in the editor; the text
  is committed when the edit ends, and the draft is unsaved again.
- An answer of the server re-renders every cell (1,005 cells: a few hundred ms in development
  React); not measured beyond 1,005 cells.
- Issues are not anchored in cells yet (S15); fill, paste, Adjust…, column selection and the undo
  UI are S10; occupancy and boards S11 and S13, so `#occupancy` / `#boards` still land on the
  matrix.
- Still open from S8: the modal Price test drawer until S14; no server-side validation concurrency
  guard; the overlay skips `_validate_links` and the window order; the cross-hotel rate plan /
  policy gap in `build_terms`; a weekly contract above the overlay's row cap is not previewed
  unsaved.

**S9 review follow-up (2026-09-25).** One medium and five low verifier findings on S9. The medium
one and three low ones are fixed; the fifth low one is the owner decision already listed under
"Open after S9". One more fault was found while verifying and is fixed too.
1. *(medium) The night adjustment was not currency-aware.* The Night adjustment popover
   (`PeriodHeader.tsx`) called `parseShorthand(text, "period_adjust")` without the contract's minor
   units, so the parser used its default, 2. O5 (§3.4.3) lists the period adjustment's ADD /
   SUBTRACT as amount ops, with the guard only below 3 decimals. As built, a KWD, BHD, OMR, JOD or
   TND contract had `+2.500` or `+12.345` refused as "Is this 1500 or 1.5?". The start text of an
   existing adjustment (`displayText` with no minor units) re-opened ADD 12.345 as `+12.345`, which
   was refused as it stood; that happened in a 2-decimal contract too. The O1–O5 report after S9
   said the night adjustment was covered by no O item, which was wrong.
2. *(low) A late `apply_op_values` answer could overwrite an edit.* Only the base-room cells of a
   Ctrl/Cmd+Enter entry were pending. Its other cells could be edited while the call was out, and
   the answer re-planned the entry and overwrote them. The open editor was kept by row index: when
   the answer turned a manual room into a formula room, that room gained a Resolved row, and an
   editor below it re-mounted in another room's row with its start text and committed there
   (reproduced in the browser: the editor of Garden Villa P2 holding `x1.5` became "Price: Family
   Suite · P2" holding `x`).
3. *(low) "50%" and "+50%" read alike on the base room*: "adjust 70.00 by 50%" (PERCENT_OF, 35.00)
   and "adjust 70.00 by +50%" (ADJUST_PERCENT, 105.00).
4. *(low) Stale resolved cells* were only dimmed; their accessible name gave the older value as
   current (§3.3.3 names the state "updating").
5. *(low) The cell editor asked for the decimal keypad* (`inputMode="decimal"`), which has no x, %,
   + or =; a formula could not be typed into a cell on a phone (§3.21), and iOS Safari does not open
   the popover on a long press.
6. *(low, not changed) `Money` cuts resolved amounts* to the currency's decimals (108.675 shows
   108.67). Pre-existing and already under "Open after S9" as an owner decision; if the owner
   chooses rounding, it must be half-up on the decimal string, never a float.
7. *(found while verifying) The refocus frame after Escape could take the focus from a new edit.*
   Under load (animation frames 400 ms late in the check below), Escape, then a click on another
   cell and typing, let the late frame move the focus back to the old cell: the new editor lost
   focus and its text was committed as it stood.

**Decision (S9 review follow-up).** Frontend only; no endpoint, payload, price or rule change, and
no change to what an entry stores.
- *Night adjustment (O5).* `PeriodHeader` gets the contract's minor units from `PriceMatrix`
  (`contract_doc.minor_units`, else the currency's). The popover parses with
  `matrixView.parsePeriodAdjust(text, {minorUnits})` and starts from
  `matrixView.periodAdjustEditText(tables, code, {decimalMark, minorUnits})`, which is `editText`
  in the `period_adjust` context. That text parses back to the stored adjustment with the same
  minor units: `+12.345` in a 3-decimal currency, `+12.3450` below (as the cells already do,
  ADR-061 S1).
- *Late answers (O4's commit).*
  - Every cell of the entry is pending until the answer (`matrixView.gestureCells`): the base-room
    ones show the price sent ("70.00 → …"), the others what they hold, with the spinner. None
    opens an editor or the popover, or takes Delete.
  - An entry over a selection that includes a pending cell is refused as a whole with PENDING
    ("This cell is still being calculated. Enter it when the calculation is done.").
  - `finishEntry` takes the tables the entry was sent from. It completes nothing, with CHANGED at
    that cell, when a cell of the entry has other own rows now (op, canonical value, base room) or
    its room or period is gone (renamed, deleted, removed). This covers the paths the pending state
    cannot block: the popover's "selected periods", the room and period menus, and undo. Edits of
    other cells made meanwhile are kept. CHANGED now reads "This cell changed while the entry was
    being calculated. Enter it again."; the entry stays in the cell as an error draft, as before.
  - The editor is kept by its cell (room, period), not by a row index. `matrixView.cellPosition`
    finds the room's entry row and the period's column on each render; rows that come and go
    above it do not move it. A commit re-checks that each cell still exists and takes entries
    (CHANGED otherwise).
- *Reading.* A base-room PERCENT_OF entry reads "{cell}: 50% of 70.00 (calculated on commit)"
  (`rates.sh.read.adjust_pct`); the other relative ops keep "adjust 70.00 by +50%".
- *Stale.* A resolved cell older than the draft on screen is named "{state}, updating"
  (`rates.ws.cell.stale_state`), e.g. "Garden Villa · P1: resolved price, updating, EUR 94.50".
- *Keyboard.* The cell editor uses `inputMode="text"`, with no autocapitalise or autocorrect.
- *Focus.* The refocus frame after Escape does nothing while an editor is open.
- New strings, in the six languages: `rates.sh.err.PENDING`, `rates.sh.read.adjust_pct`,
  `rates.ws.cell.stale_state`; `rates.sh.err.CHANGED` reworded.

**Tests (S9 review follow-up).** `tests/unit/workspace-matrix.test.ts` 23 (18 + 5):
- the night adjustment's `+12.345` is AMBIGUOUS at 2 and 0 decimals (and with no minor units) and
  ADD 12.345 at 3; `+2.500` and `-2,500` are ADD / SUBTRACT 2.5 at 3; percentages and factors are
  exempt;
- the start text of ADD 12.345 is `+12.345` / `+12,345` at 3 decimals and `+12.3450` at 2, and at
  0, 2 and 3 decimals with either mark it applies back to the same tables; SUBTRACT, MULTIPLY,
  ADJUST_PERCENT, no adjustment and an unknown period;
- every cell of an entry is pending, the base ones with the price sent;
- a late answer completes nothing (CHANGED at that cell) after a price typed into a non-base cell
  of the entry, a period rule of the entry removed, its period renamed or deleted, or its room
  removed; it completes around an edit of another cell; the same price retyped (`70.00`) is not a
  change;
- `cellPosition` follows Garden Villa P2 from row 2 to row 3 when Family Suite gains its Resolved
  row, and is null for an unknown room or period.

The existing `finishEntry` tests pass the tables the entry was sent from (the new argument), and
their answers are unchanged.

Fail-first:
- with the new tests on the unfixed tree, the file does not load (`SyntaxError: … does not provide
  an export named 'cellPosition'`);
- a scratch test of the unfixed code paths fails three times:
  - the popover's parse of `+12.345` gives `{ok: false, code: "AMBIGUOUS", op: "ADD"}` where a
    3-decimal contract needs ADD 12.345;
  - the re-opened `+12.345` gives `{error: "AMBIGUOUS"}`;
  - the late answer overwrites Deluxe P3's typed 150 with ADJUST_PERCENT 10.
- the browser checks below were run on the unfixed sources as well: the KWD night adjustment, the
  PERCENT_OF reading, the keyboard, the stale name, the pending cells and the editor's cell all
  failed there; the EUR check passed, as it should.

**Verification (S9 review follow-up).**
- *Build and unit tests:* `tsc -b`, `npm run build`, `npm run i18n:tex` (3 new keys, one reworded, in
  the six languages), `npm run test:unit` 171, `npm run test:dom` 24, Python unit 491, ruff (no
  Python change).
- *Integration, on the tree migrated with it:* `test_pricing_workspace_api` 50 OK. The opt-in
  `bench_pricing_workspace` ran 3 OK.
- *Browser:* a scratch Playwright check on the tree's own servers (bench :8016, Vite :5186), 8/8:
  1. a KWD contract (`minor_units` 3): the night adjustment takes `+12.345` ("P3: occupancy +
     board +12.345", Apply enabled), the header shows "◆ +12.345", the popover re-opens with
     `+12.345`, and after a save `get_version` has ADD 12.345;
  2. a EUR contract: `+12.345` shows the AMBIGUOUS message with Apply disabled; `+12.5` is taken;
  3. the base room: "Standard Sea View · P1: 50% of 70.00 (calculated on commit)" and "…: adjust
     70.00 by +50% …"; the editor has `inputmode="text"`;
  4. with the live preview held back 2.5 s: "Garden Villa · P1: resolved price, updating, EUR
     94.50", then "…: resolved price, EUR 108.00";
  5. with `apply_op_values` held back, one entry `x1.2` over Standard P1 and Family Suite All
     periods:
     - both cells are "being calculated", and F2 and typing open no editor on Family Suite;
     - an entry over a selection with Standard P1 is refused with "… still being calculated";
     - an editor opened on Garden Villa P2 with `x1.5` keeps its cell, its text and the focus when
       the answer lands (84.00; Family Suite ×1.2, its Resolved row with 96.00);
     - Enter stores Garden Villa P2 ×1.5 (120.00), and Family Suite P2 still follows all periods;
  6. the reading and the editor checks on their own (both also run on the unfixed sources, where
     both failed);
  7. with animation frames 400 ms late: Escape, a click on Garden Villa P3 and `15` keep the
     editor, its text and the focus, with nothing committed. Without the guard the frame took the
     focus and committed 15.
- *S9's own scratch smoke* passed 8/8 three times in a row. One earlier run failed while Vite
  recompiled the restored sources: the keys typed at once after Escape went nowhere until the
  delayed refocus frame. That is item 1 under "Open after the S9 review follow-up".
- *Existing specs:* `contract-admin`, `critical-journey` and `editor-edits` (3) pass on the tree's
  own servers (5 passed).

**Performance of the server-side draft overlay** (`bench_pricing_workspace` on this tree, best of
three, seconds; validation run once; no server code changed since S8):

| Draft | Rows | Overlay alone | `price_matrix` with data (saved) | 12 sample parties with data | `preview_price` with data | `validate_version` with data (saved) |
|---|---|---|---|---|---|---|
| Realistic 12 rooms × 26 periods | 1,406 | 0.164 | 0.247 (0.074) | 0.286 | 0.226 | 2.03 (1.89) |
| Near the cap, 12 × 40 | 4,539 | 0.514 | 0.683 (0.162) | 0.896 | 0.699 | 9.72 (9.55) |
| Above the cap, 12 × 52 | 5,892 | refused in 0.266 | by name 0.241 | by name 0.645 | by name 0.201 | by name 16.0 |

`apply_op_values` with 500 prices: 0.007–0.008 s. `save_version`: 0.77 / 2.27 / 3.14 s. These are
within 10 % of the S8 review follow-up's figures.

**O1–O5 after the S9 review follow-up** (all five provisional, owner input 13; none changes how the
engine prices, since each maps an entry onto an op the engine already has):
- *O1 (board `100` → ABSOLUTE, per room per night):* in the parser and the model only; the board
  cells and their reading line are S13. Unchanged.
- *O2 (board `-20` → ADD −20 per adult):* parser and model only (S13). Unchanged.
- *O3 (board `50%` → ADJUST_PERCENT 50):* parser and model only (S13). Unchanged.
- *O4 (base room, relative entry):* built end to end.
  - In a base-room cell whose price is an entered one, `x1.1`, `+10%`, `-5`, `+5` and `50%` are
    parsed as the owner's table says.
  - The reading line says what will be stored, before commit: "adjust 70.00 by +10% (calculated
    on commit)", or for PERCENT_OF "50% of 70.00 (calculated on commit)".
  - On commit, one `apply_op_values` call adjusts every base cell of the entry once, HALF_UP to the
    contract currency, and the answers are stored as ABSOLUTE (`+10%` on 70 → 77.00).
  - Meanwhile every cell of the entry is pending. An answer for a cell changed meanwhile stores
    nothing (CHANGED).
  - Without an entered price: BASE_NO_PRICE; with a formula: BASE_FORMULA. The rule popover
    stores the op it is given.
- *O5 (currency-aware AMBIGUOUS):* on screen in every context built so far, in the six languages.
  - It applies to amounts only: room ABSOLUTE / ADD / SUBTRACT, in the cells and the rule popover,
    and period night adjustment ADD / SUBTRACT, in its popover.
  - An amount with 1–3 integer digits and exactly 3 fraction digits is refused in 0- and 2-decimal
    currencies and accepted in 3-decimal ones (KWD, BHD, OMR, JOD, TND).
  - Factors and percentages are exempt.
  - Occupancy and board cells (S11, S13) will use the same parser, whose tests cover those
    contexts.

**Open after the S9 review follow-up.**
- Keys typed before the refocus frame after Escape, Enter or Tab (one frame, longer under load) go
  nowhere. Pre-existing, and harmless: nothing is committed.
- `Money` cuts resolved amounts to the currency's decimals (item 6): the owner decides; if
  rounding, half-up on the decimal string.
- The other items under "Open after S9" are unchanged.

**Decision (implemented in S10: the matrix's bulk tools).** Branch `pricing-workspace`, frontend
only (no server file changes), commits `a2722ec` (pure modules and unit tests), `e5b70c7` (the
history's React binding and the editor) and `05e18e8` (the screen). This section was written with
the S10 review follow-up below: the build's own report was lost, so the review's verification is
recorded here.
- *Selection* is S7's `useGridSelection`, as S9 wired it (Shift+Arrow / Shift+Click extend,
  Ctrl/Cmd+Click adds, Ctrl/Cmd+A, Escape clears, `aria-selected`). New: a click on a room's row
  header, or on a period's or All periods' column header, selects that row's or column's editable
  cells (resolved rows are passed over) and focuses the first of them; Ctrl/Cmd adds to the
  selection. `RoomRowHeader.headerPick` ignores clicks on the header's own controls (its menu, an
  input) and prevents the mousedown's text selection. For the keyboard, the room and period menus
  have "Select prices".
- *Fill → / Fill ↓* (toolbar; Ctrl/Cmd+R and Ctrl/Cmd+D while a grid cell has focus, with
  `preventDefault`, so the browser neither reloads nor bookmarks) take S7's `fillRightPlan` /
  `fillDownPlan` over the selected editable cells, then the pure `bulk.planFill`, all or nothing:
  - the source cell's own rule is copied as it is (as built; see deviation 7 and the follow-up);
  - a formula keeps the room it derives from, unless that is the target room (then the target's
    default base; NO_BASE_ROOM when there is none);
  - a formula is never copied into a price row (the base room, where a relative entry would change
    the price once (O4), or a manual room): the whole fill is refused at that cell (FILL_FORMULA,
    "A formula is copied only into formula rows; this row holds entered prices …");
  - a price copied into a formula row is a fixed price override. The fill waits for an inline, non-modal
    "Set a fixed price override?" line (`BulkToolbar.FillConfirm`); its button takes the focus,
    and Escape or Cancel drop the fill;
  - a period copy equal to the target room's All-periods rule is not stored (the period follows it);
  - a cell still being calculated (S9's pending cells) refuses the fill (PENDING);
  - one history entry, "Fill right (N cells)" / "Fill down (N cells)"; "Nothing changed." when the
    fill changes nothing.
- *Copy* (Ctrl/Cmd+C): `clipboard.copyBlock` over the selection's ranges gives the rows and
  columns that hold a selected cell, with "" for the others. A column selected by its header
  passes over the resolved rows, so it pastes back onto the same rows. `encodeTSV` joins it. An
  entry cell gives the canonical edit text of its rule ("." as the decimal mark); a resolved row
  gives the server's exact amount. "Copied N cells" is announced.
- *Paste* (Ctrl/Cmd+V):
  - `decodeTSV` trims one trailing line break, splits lines on CRLF, LF or CR, and keeps empty
    cells (they clear).
  - `planPaste`: one value fills every selected editable cell. A block runs from its anchor
    (deviation 2) down the editable rows (resolved rows passed over) and right along the columns;
    otherwise SHAPE ("The pasted block is 1×3 but only 3×2 editable cells are available here.").
  - Every cell is parsed with `parseShorthand(text, "room", {minorUnits})`. Any failure refuses the
    whole paste, naming at most three cells ("P3 · Standard Sea View: “1.500”: Is this 1500 or
    1.5? …") and counting the rest ("and N more cells").
  - NO_TARGET on a resolved row or a read-only cell; an empty clipboard is announced.
  - The cells are one entry with a text each (`matrixView.planItems` / `finishItems`; each cell
    by its row's rule, D11). Base-room relative entries go to `apply_op_values`, one call per op
    and value with at most 500 prices each (`bulk.serverCalls`, `answersInOrder`). The paste is
    committed when the answers land, under S9's pending and CHANGED rules.
  - No clipboard permission is asked: the browser's copy and paste events carry the data
    (deviation 1).
- *Adjust…* (`AdjustPopover.tsx`, a non-modal Popover "Adjust prices" at the toolbar button):
  - The op is a Segmented control: +%, −%, +amount, −amount, ×. `bulk.adjustRule` maps them to
    ADJUST_PERCENT v, ADJUST_PERCENT −v, ADD, SUBTRACT and MULTIPLY. A typed sign is SYNTAX.
    Amounts are currency-aware (O5). The value is a `DecimalInput`, focused on open.
  - The targets (`adjustTargets`) are the selected entered prices: an own ABSOLUTE or FIXED row
    with a value, in any row. Formula cells are counted as skipped. The other cells (no price,
    INHERIT, a period following an All-periods price) are counted separately.
  - The preview is the server's. 250 ms after the last keystroke, `apply_op_values` is asked
    with the prices as they are now (at most 500 per call); a newer request aborts the older one.
    The popover lists the first 8 "Standard Sea View · P1: 70.00 → 77.00" lines of the prices that
    change, "+N more", the prices the server refuses and the unchanged count, in a polite status
    region.
  - Apply is disabled while the preview is pending, when nothing changes, or when a price is
    refused (deviation 3). It writes the server's amounts as ABSOLUTE in one entry ("Adjust N
    prices"). It is refused with CHANGED when a target no longer holds the price that was
    previewed. The client computes no amount.
- *Undo and redo*: the toolbar's Undo and Redo, and while a grid cell has focus Ctrl/Cmd+Z,
  Ctrl/Cmd+Shift+Z and Ctrl/Cmd+Y. `ui/keys.editShortcut` matches them by letter on every layout
  (`shortcutLetter`, so Russian я, н, к and в work) and never with Alt, which is AltGr on Windows.
  In a cell editor, Ctrl/Cmd+Z is the field's own text undo. Each step is announced ("Undone:
  {label}", "Redone: {label}") in the matrix's polite live region. Undo puts recorded arrays back
  and calls no server (S9).
- *The toast.* A bulk operation shows "Applied to N cells · Undo" for 10 s (`useUndoToast`,
  `UndoToastView`, bottom centre). Bulk operations are Ctrl/Cmd+Enter or Delete over several
  cells, a paste of several, a fill and Adjust…. The text is also announced in the live region;
  the toast is not a live region itself. It goes with any later commit, undo or redo, and its Undo
  undoes its own entry only. It is held while hovered or focused (deviation 4).
- *History* (`history.ts`, `useWorkspaceHistory`): `record(table, rows, label)` (deviation 5).
  `VersionEditor` hands the sections a recording `setTable`, so every Advanced rule table and
  Offers edit is a history entry, "Rule table: {table}". Commits with the same merge key within
  1.5 s (`MERGE_WINDOW_MS`) join one entry: one per table and burst of typing, never across an
  undo. `seq()` gives the log's change counter at once, `version` as rendered. The log is still
  cleared on load and on Discard (S9).
- *The toolbar* (`BulkToolbar.tsx`) is memoised, so an arrow key does not re-render it. It is a
  labelled group of ordinary buttons, not an ARIA toolbar, which would promise one tab stop with
  arrow keys. Fill →, Fill ↓ and Adjust… are hidden below 768 px (deviation 9); Undo and Redo stay.
  A Keyboard shortcuts popover (hidden below 768 px) lists every key of §3.10 and Ctrl/Cmd+S,
  19 rows, with a note for Mac.
- *Save*: Ctrl/Cmd+S matches by letter on every layout and not with AltGr (deviation 6).
- 89 new keys in the six catalogues (`rates.ws.bulk.*`, `rates.ws.fill.*`, `rates.ws.paste.*`,
  `rates.ws.adjust.*`, `rates.kbd.*`, the history labels).

**Deviations from the slice text, with reasons (S10).** The build's report was lost; the review
listed these deviations, and the reasons are taken from the code, its comments and commit
messages.
1. *Clipboard events are taken at the document*, filtered to this grid's focused gridcell and
   read through a ref, not on the grid element as the slice says. A gridcell is focusable but not
   editable, and the browser does not always deliver copy and paste to it. The document listeners
   act only when the focused element is a `gridcell` inside this matrix, so other fields and
   other grids keep their own clipboard.
2. *A pasted block is anchored at the top-left of the range that holds the active cell*
   (`pasteOrigin`), not at the active cell. Shift+Arrow moves the active cell to the far corner of
   the range; anchoring there would paste P1:P4 copied from a spreadsheet at P4 and fail with
   SHAPE. A single active cell is its own range, so the slice's case is unchanged.
3. *Adjust…'s Apply is also disabled when any price is refused* (NEGATIVE, NO_VALUE). Apply is all
   or nothing and would refuse anyway; the preview lists the refused prices.
4. *The undo toast is held while hovered or focused*, so it can stay longer than 10 s. A keyboard
   or pointer user who reaches its Undo must not lose it mid-way (in the spirit of WCAG 2.2.1,
   timing adjustable). Released, it gets a fresh 10 s. A new toast always starts unheld.
5. *The Advanced rule tables and Offers write through the history* (`record`), merged per table
   within 1.5 s. This changes S8's sections: before, their `setTable` bypassed the log, and undoing
   a matrix entry put back an older whole `period_rates` array, which silently dropped a Rule table
   edit made after it (an S9 review finding). Now their edits are entries like any other and are
   undone in order. They have no Undo button of their own (open item).
6. *Ctrl/Cmd+S matches by letter on every layout and ignores AltGr* (`VersionEditor`). On a
   Russian layout Ctrl + the key marked S gives `e.key` "ы" and did not save; Polish AltGr+S types
   "ś" and must not save.
7. *Fill of a source with no rule of its own cleared the target.* A period that follows All
   periods has no row, so filling it copied "nothing". Within a row that is harmless (the targets
   then follow the same All-periods rule). Across rooms it gave the target its own room's
   All-periods rule, not what the source showed. **Changed by the S10 review follow-up** (below).
8. *Files beyond the slice list:*
   - `workspace/bulk.ts`: fill, Adjust… and the server calls, pure and unit-tested;
   - `workspace/matrixView.ts`: `planItems` / `finishItems`, because a paste is one entry with a
     text per cell;
   - `workspace/history.ts`: the merge key;
   - `ui/keys.ts`: `editShortcut`;
   - `RoomRowHeader.tsx` and `PeriodHeader.tsx`: header selection and "Select prices";
   - `contracts/VersionEditor.tsx`: `record` and Ctrl/Cmd+S;
   - `tests/unit/workspace-bulk.test.ts`.
9. *Fill and Adjust… (and the shortcuts popover) are hidden below 768 px.* The slice text lists
   the toolbar without a breakpoint; §3.21 says bulk tools are hidden on phones. Undo and Redo
   stay, because single-cell edits on phones are undoable too.

**Tests (S10).** `npm run test:unit` 201 (171 + 30):
- `tests/unit/clipboard.test.ts` (13): the TSV round trip; the trailing line break, CRLF and CR;
  a cell's own tab or line break; the copied block of one and of several ranges; the paste anchor;
  one value fills the selection; a 2×2 block at the active cell; an overflowing block → SHAPE;
  an invalid cell applies nothing and names "P3 · Superior"; at most three named, all counted;
  resolved rows are never targets; `1.500` is AMBIGUOUS with 2 minor units and a price with 3;
  an empty clipboard.
- `tests/unit/workspace-bulk.test.ts` (13): Fill → and Fill ↓; a price into a formula row listed
  for the confirmation; a formula never into a price row; an empty or inherited source; a formula
  never derived from its own room; a fill that changes nothing; the Adjust… ops, O5 on amounts,
  targets, preview and Apply (ABSOLUTE, CHANGED, refusals); a paste as one entry of different texts
  with base-room entries for the server, and its calls.
- `history.test.ts` (+2): merged bursts per table; a pause, another table or an undo starts a new
  entry. `keys.test.ts` (+2): the editing shortcuts on every layout; none without Ctrl/Cmd, with
  Alt or with Shift on R, D and Y.
- Fail-first: with the tests on the tree before S10, four files failed to load (163 tests, 159
  passed, 4 failed): `clipboard.ts` and `bulk.ts` with `ERR_MODULE_NOT_FOUND`, and `history.ts`
  (`MERGE_WINDOW_MS`) and `ui/keys.ts` (`editShortcut`) with "does not provide an export named".

**Verification (S10)**, measured by the review on `05e18e8`:
- *Build and checks:* `tsc -b` clean; `vite build` clean (built outside the tree); `npm run
  i18n:tex` complete, and every literal and dynamic `t()` key the S10 files use exists in the six
  catalogues; `npm run test:unit` 201/201; `npm run test:dom` 24/24.
- *Browser:* the scratch S10 dev-server spec, 6/6 against this tree:
  1. Garden Villa P3:P4 `x1.40` with Ctrl+Enter, then Ctrl+Z, Ctrl+Y and Ctrl+Shift+Z;
  2. the toast's Undo within 10 s, and the toast gone by itself at about 10 s;
  3. Adjust +10 % on Standard P1:P4: the preview 70.00 → 77.00 …, Apply, Undo;
  4. a 1×4 spreadsheet block pasted into Standard; SHAPE, INVALID and NO_TARGET;
  5. header selection; Fill with its confirmation; the Russian layout;
  6. Discard clears the history; the phone toolbar.
- *Existing specs:* `editor-edits` and `contract-admin`, 4/4 against this tree.
- No server change: Python tests unaffected.

**Performance after S10** (the Vite dev server, i.e. development React, measured with S10's
scratch perf check on the tree of the S10 review follow-up; keydown to the next painted frame in
the page; the bulk timings are wall clock from the test until the cell shows the result, so they
include Playwright's polling):
- 3 rooms × 52 periods (265 cells): arrow keys median 35 ms (max 56), typing 5 ms (S9: 32 and
  4 ms). Ctrl+A 0.22 s, Ctrl+C of everything 0.09 s, a 1×52 paste 0.27 s, Fill → across 52
  periods 0.45 s, its undo 0.20 s, the Adjust… preview of 52 prices 0.35 s (250 ms debounce
  included), Apply 0.39 s.
- 3 rooms × 200 periods (1,005 cells): arrow keys median 76 ms (max 102), typing 7 ms (S9: 72 and
  6 ms). Ctrl+A 0.54 s, Ctrl+C 0.17 s, a 1×200 paste 0.58 s, Fill → 0.80 s, its undo 0.96 s, the
  preview of 200 prices 0.62 s, Apply 0.95 s.
- `price_matrix` with the unsaved draft answered in 56–58 ms (3 × 52) and 128–170 ms (3 × 200),
  as in S9.

**O1–O5 after S10** (all five provisional, owner input 13):
- *O4:* a paste, like a typed entry, sends base-room relative entries to `apply_op_values`, one
  call per op and value. Adjust… is the explicit tool for relative changes of entered prices in
  any row, through the same server path. Fill never copies a formula into the base room.
- *O5:* pasted cells and Adjust…'s amounts (+amount, −amount) are parsed with the contract's minor
  units; `1.500` is refused in 0- and 2-decimal currencies and accepted in 3-decimal ones.
  Percentages and factors are exempt.
- *O1–O3 (boards):* unchanged; S13.

**S10 review follow-up (2026-09-25).** One medium and two low verifier findings on S10, all
addressed.
1. *(medium) S10 had no documentation*: no ADR section, the R-04 row still said the bulk tools
   were not built, and no go-live change-log line. Written now: the sections above, the status
   row, and the change log.
2. *(low) Fill copied only a cell's own rule.* Family Suite P1 showed "follows all periods, ×1.15".
   Filled down onto Garden Villa P1, which held an override ×1.5, it gave Garden Villa P1 "follows
   all periods, ×1.35": the user copied ×1.15, got ×1.35, and lost the override. The toast still
   said "Applied to 1 cell". A row-header click and Ctrl+R filled the empty All-periods cell across
   and silently cleared every period price of the row. Ctrl/Cmd+C copied "" for following cells
   and INHERIT rows.
3. *(low) The React-bound behaviour had no committed test*: `useUndoToast` (10 s, hold, its own
   entry only, hidden after a later change), `record()`'s merging, and the document-level
   clipboard listeners were exercised only by the scratch spec.

**Decision (S10 review follow-up).** Frontend only; no endpoint, payload, price or rule change.
- *Fill takes the rule the source shows* (`bulk.planFill`):
  - Within a room (Fill →) the source's own rule is copied as it is, INHERIT included. A source
    without a rule of its own removes the target's rule, so the target follows the same
    All-periods rule and shows what the source shows (unchanged).
  - Into another room (Fill ↓), a source that follows All periods (no rule of its own, or its own
    INHERIT row, which the engine skips) copies the All-periods rule it follows, as if it were its
    own, under the same rules: a formula keeps its base unless that is the target room; a formula
    never goes into a price row (FILL_FORMULA, now also for a following formula); a price into a
    formula row asks first.
  - A source that shows no rule at all still removes the target's rule, as a spreadsheet's fill
    of an empty cell does. The plan lists those cells (`cleared`, only where something was
    removed), and the toast and live region say so: "Applied to 4 cells · 4 cells cleared (copied
    from empty cells)" (`rates.ws.fill.cleared`, six languages).
- *Ctrl/Cmd+C copies what a cell shows* (`matrixView.cellCopyText`): the edit text of its own rule,
  else of the All-periods rule it follows (also for an INHERIT row); "" only when it shows no rule.
  A spreadsheet gets what the screen shows. Pasted back into the same cells it stores nothing new
  (a period rule equal to the All-periods rule is not stored); pasted into another room it is a
  typed entry there (D11: the row decides, so a formula derives from that room's default base).
  An INHERIT row pasted back becomes "no row", with the same price. F2 on a following cell still
  starts empty (§3.4.6).
- *A committed DOM-harness test* (`tests/dom/history.{html,tsx,spec.ts}`, Playwright's clock) now
  covers the undo toast and `record()` with the real hooks and the toast's view. The document-level
  clipboard listeners and the grid's shortcuts remain covered by the scratch specs only (open item).

**Tests (S10 review follow-up).**
- `tests/unit/workspace-bulk.test.ts` 16 (13 + 3; one test reworded for Fill → within a row):
  - Fill ↓ from Superior P1 (follows ×1.15) onto Deluxe P1 (×1.5 override) gives
    `P1 MULTIPLY 1.15 from STD`;
  - an INHERIT source filled into another room gives the All-periods rule it resolves by;
  - a following price into a formula row is a fixed override; a following formula into a price
    row is FILL_FORMULA;
  - an empty All periods filled right clears P1–P4 and lists them in `cleared`; filled down onto
    Deluxe's All periods it clears and lists it; a target that held nothing is not listed;
  - `cellCopyText` for own, following, INHERIT and empty cells, and the copied text pasted back
    stores nothing.
  `npm run test:unit` 204.
- `tests/dom/history.spec.ts` (3):
  - the toast stays 10 s, is held while hovered or focused and restarts its 10 s when released;
    its Undo undoes its own entry; a new toast starts unheld;
  - the toast goes with another entry, a Rule table keystroke or an undo;
  - Rule table keystrokes within 1.5 s are one entry, a later one its own, and one after an undo
    never joins the undone entry; undo walks back through them before the earlier matrix entry.
  `npm run test:dom` 27.
- Fail-first:
  - the new unit file does not load on `05e18e8` ("does not provide an export named
    'cellCopyText'");
  - with that export stubbed as `cellEditText`, 4 of 16 fail: `cleared` is undefined, and Deluxe
    keeps `["*:MULTIPLY:1.35:STD"]` where `P1:MULTIPLY:1.15:STD` is expected;
  - the DOM spec was written against the S10 code; each test fails under a mutation of the code it
    covers (no hold; 5 s instead of 10 s; the toast kept after later changes; `record` bypassing
    the log as before S10; no merge).

**Verification (S10 review follow-up).**
- *Build and unit tests:* `tsc -b`, `vite build` (to scratch), `npm run i18n:tex` (one new key in
  the six catalogues), `npm run test:unit` 204/204, `npm run test:dom` 27/27. The new harness page
  and spec also type-check.
- *Integration, on the tree migrated with it:* `test_pricing_workspace_api` 50 OK.
- *Browser, on the tree's own servers* (bench :8026, Vite :5196):
  - the scratch S10 spec, 6/6;
  - a scratch review check, 3/3: R1, the Family Suite → Garden Villa fill above (Garden Villa P1
    "period override, Standard Sea View ×1.15", resolved 80.50, toast without "cleared", Ctrl+Z
    back to ×1.5); R2, the Standard row header and Ctrl+R (toast and live region "Applied to 4
    cells · 4 cells cleared (copied from empty cells)", Ctrl+Z restores 70.00 … 130.00); R3,
    Ctrl+C of Family Suite P1:P2 gives `x1.15⇥x1.15`, pasted onto Garden Villa P1 it gives ×1.15
    in P1 and P2, and pasted back onto Family Suite they still follow all periods;
  - R1, R2 and R3 each fail on the S10 sources (`05e18e8`): Garden Villa P1 never shows ×1.15;
    the toast reads "Applied to 4 cells" only; the clipboard holds a single tab;
  - `contract-admin`, `critical-journey` and `editor-edits`: 5/5.

**O1–O5 after the S10 review follow-up:** unchanged from "O1–O5 after S10". A following formula
filled down into the base room is refused like any formula (O4).

**S10 second review follow-up (2026-09-25).** One high and three low verifier findings on S10
and its first follow-up, all addressed.
1. *(high) Copy and paste mapped rows differently.* A Shift+Arrow or Shift+Click range over a
   resolved row copied that row's server amount (`copyBlock` took the whole rectangle). A paste
   writes entry rows only and passes over the resolved ones (`planPaste`). Each resolved row in
   the block therefore moved every row below it one room down. The verifier's case: the owner
   grid with resolved rows shown, Standard P1 to Deluxe P1 copied and pasted at Standard P2. Deluxe
   P2 got Superior's resolved price as a fixed price (ABSOLUTE 80.5), Family P2 got Deluxe's
   formula (a manual room became a formula room), and the toast read "Applied to 4 cells". With
   no entry row below, the same gesture failed with a confusing SHAPE. Ctrl/Cmd+A and header
   selections leave resolved rows out, so they were not affected.
2. *(low) The TSV round trip lost a last row of one empty cell.* `encodeTSV` wrote no final line
   break and `decodeTSV` trims one. A copied column whose last cell shows no rule did not clear
   that target, and one copied empty cell pasted as "nothing to paste".
3. *(low) Ctrl/Cmd+R and Ctrl/Cmd+D in a cell editor reached the browser* (reload, bookmark). The
   grid's key handler ignores the editor's events, and the editor handled only Escape, Enter and
   Tab.
4. *(low) The undo toast's Undo dropped the focus to the page.* The toast unmounts while its
   button holds the focus, so a keyboard user lost their place in the grid.

**Decision (S10 second review follow-up).** Frontend only; no endpoint, payload, price or rule
change.
- *Copy leaves out the resolved rows when the selection also holds entry rows*
  (`clipboard.copyBlock(ranges, textAt, entryRow)`; PriceMatrix passes the grid rows'
  `editable`). The copy and the paste now map rows the same way, so a block pastes back onto the
  same rooms wherever it is pasted, and a spreadsheet round trip keeps that alignment. The
  columns are then the ones that hold a selected cell of a kept row. Resolved cells selected on
  their own still copy the server's exact amounts (§3.10), for example to paste them into a
  manual room.
  - *Deviation from §3.10:* "resolved rows copy the exact server amounts" now holds only for a
    selection of resolved cells alone. In a mixed selection a spreadsheet gets the entry rows,
    as Ctrl/Cmd+A and a column-header selection already gave it.
  - *Rejected alternative:* an app-specific clipboard type naming each row's kind, with the
    resolved rows dropped only on an in-app paste. The type does not survive a spreadsheet: a
    block copied from the matrix, edited in a spreadsheet and pasted back would shift again.
- *`encodeTSV` ends every row with a line break*, as spreadsheets do; `decodeTSV` trims exactly
  that one. An empty last row and a single empty cell survive the round trip, so they clear
  where they are pasted.
- *A cell editor keeps Ctrl/Cmd+R and Ctrl/Cmd+D from the browser*
  (`ui/keys.editorSwallowsShortcut`, on every layout; PriceMatrix's `onEditorKey` prevents the
  default). No fill runs while a cell is being edited. Ctrl/Cmd+Z and Ctrl/Cmd+Y stay the field's
  own undo and redo; Ctrl/Cmd+Shift+R (hard reload) is not a grid shortcut and is left alone.
- *The undo toast gives the focus back* (`UndoToastView` `onFocusBack`). When its Undo or close
  button takes the toast away while the toast holds the focus, the matrix puts the focus on the
  grid's active cell, as the fill confirmation does. A toast that goes without holding the focus
  leaves the focus where it is.

**Tests (S10 second review follow-up).**
- `tests/unit/clipboard.test.ts` 15 (13 + 2), with the real selection reducer:
  - on the owner grid (Standard, Superior, Superior resolved, Deluxe, Deluxe resolved, Family,
    Family resolved), Shift+ArrowDown ×3 from Standard P1 copies `70⏎x1.15⏎x1.35⏎`. Pasted at
    Standard P2 it writes Standard, Superior and Deluxe P2, each with its own row's text, and
    leaves Family alone. Pasted back in place it writes the same cells. A Shift+Click from
    Superior's resolved P1 to Deluxe P2 copies Deluxe's row. A Ctrl/Cmd+Click mix drops the
    resolved cell's column;
  - resolved cells alone copy the server amounts and paste onto Family as its prices;
  - the TSV round trip of `[["70"],[""]]` and `[[""]]`; every row ends with a line break.
- `tests/unit/keys.test.ts` 7 (6 + 1): `editorSwallowsShortcut` for Ctrl and Cmd+R and +D (the
  Russian layout too). It is false for undo, redo, copy, paste, plain letters, Ctrl+Shift+R and
  AltGr.
- `tests/dom/history.spec.ts` 4 (3 + 1): the toast's Undo (Enter) and close button (Space) put the
  focus on the harness's active cell; a click that does not focus the toast leaves the focus where
  it was.
- `npm run test:unit` 207, `npm run test:dom` 28.
- Fail-first, on `0f1e863`:
  - clipboard: 3 of 15 fail. The mixed range copies `[["70"],["x1.15"],["80.5"],["x1.35"]]`,
    and `encodeTSV` gives `…\t\t\t` and `a b\tc d` without the final line break;
  - keys: the file does not load ("does not provide an export named 'editorSwallowsShortcut'");
  - DOM: the new test fails, because the focus is not on the active cell after the toast's Undo.

**Verification (S10 second review follow-up).**
- *Build and unit tests:* `tsc -b`, `vite build` (bundles not committed), `npm run i18n:tex`
  complete (no new key), `npm run test:unit` 207/207, `npm run test:dom` 28/28.
- *Integration, on the tree migrated with it:* `test_pricing_workspace_api` 50 OK.
- *Browser, on the tree's own servers* (bench :8026, Vite :5196):
  - a scratch check `s10v2-review.spec.ts`, 5/5. V1: Shift+ArrowDown ×3 from Standard P1 over
    Family Suite's resolved row to Garden Villa copies `70⏎x1.15⏎90⏎`; pasted at P2 it gives
    Standard 70.00, Family Suite still following ×1.15 and Garden Villa 90.00, "Applied to 3
    cells", and Ctrl+Z puts them back. V2: a range ending on the resolved row, pasted at P3,
    never writes Garden Villa; Family Suite's resolved P1:P2 alone copies `80.5⇥92` and pastes
    onto Garden Villa. V3: an empty All-periods cell copies `⏎` and clears Garden Villa P4.
    V4: in a cell editor Ctrl+R and Ctrl+D are default-prevented, Ctrl+Z is not, and no fill
    runs. V5: the toast's Undo (Enter and click) and its close button leave the focus on the
    grid's active cell;
  - each of V1–V5 fails on the `0f1e863` sources: the clipboard holds `…80.5…`, or `""` for the
    empty cell; Ctrl+R and Ctrl+D are not prevented; the focus is on BODY;
  - the S10 checks (6/6) and the first review check R1–R3 (3/3) pass, with their clipboard
    expectations given the final line break;
  - `contract-admin`, `critical-journey` and `editor-edits`: 5/5.

**O1–O5 after the S10 second review follow-up:** unchanged.

**Open after S10 and its review follow-up.**
- *S16 must carry the scratch scenarios into the committed workspace specs*:
  - from `s10-bulk.spec.ts`: Ctrl/Cmd+Enter with the undo and redo keys; the toast's Undo and
    expiry on the real screen; Adjust… preview, Apply and Undo; paste and copy (SHAPE, INVALID,
    NO_TARGET, resolved rows); header selection; Fill with the confirmation; the Rule table undo
    interleaved with matrix entries; the Russian-layout shortcuts; Discard clearing the history;
    the phone toolbar;
  - from the review check: R1–R3;
  - from the second review check: V1–V5 (a copied range over a resolved row, a resolved row
    alone, an empty cell, Ctrl+R and Ctrl+D in the editor, the toast's focus).
  The DOM harness covers `useUndoToast`, the toast's focus return and `record()` only. The
  document-level clipboard listeners and the grid's shortcuts have no committed test until then.
- A spreadsheet gets only the entry rows of a selection that mixes entry and resolved rows
  (second review follow-up); the resolved amounts are copied when they are selected alone.
- Undo and Redo are only on Pricing's matrix toolbar (and Ctrl/Cmd+Z with a grid cell focused).
  Entries made in a Rule table or in Offers are undone from there; inside a text field
  Ctrl/Cmd+Z is the field's own text undo.
- The toast can stay beyond 10 s while hovered or focused (deviation 4).
- A fill from a cell that shows no rule clears its targets. That can be undone and is now named,
  but it is not refused.
- Not measured beyond 1,005 cells. Undoing a 200-period fill takes about 1 s in development React.
- Still open from S9: `Money` cuts resolved amounts to the currency's decimals (the owner decides;
  if rounding, half-up on the decimal string); keys typed before the refocus frame go nowhere;
  Ctrl/Cmd+S while a cell is being edited saves without the editor's text. Still open from S8:
  the modal Price test drawer until S14; no server-side validation concurrency guard; the overlay
  skips `_validate_links` and the window order; the cross-hotel rate plan / policy gap in
  `build_terms`; a weekly contract above the overlay's row cap is not previewed unsaved. Issues
  are not anchored in cells yet (S15); occupancy and boards are S11 and S13.

**Decision (implemented in S11: Occupancy & child pricing, the child ages drawer, band labels).**
Branch `pricing-workspace`, frontend only (no server file changes), commits `2f155eb` (pure
modules and unit tests), `ae96a90` (the non-modal Drawer and `tOrdinal`), `72fe4c5` (the
screens) and `26a3f5d` (closing the drawer drops an uncommitted band). Pricing shows the region under the room price matrix; the Advanced "Child ages" and
"Occupancy rules" tables stay under Commercial rules.
- *The section* (`workspace/OccupancySection.tsx`, §3.6.1) is a disclosure, "Occupancy & child
  pricing" (a button in the `h2`, `aria-expanded`). Its open state is kept per viewer in
  `localStorage` (`tex.rates.ws.occupancy_open`, read and written in try/catch); without a stored
  choice a draft without occupancy rules opens it. `#occupancy` opens it and scrolls to it;
  `#ages` opens the drawer. Its header holds:
  - the rooms scope: All rooms or one contract room; a scope with rules of its own is marked "•",
    explained to screen readers by `aria-describedby`;
  - child 1 ordering (`child_ordering`);
  - under ROOM basis, the extra-adult unit (`room_basis_extra_unit`) and "Children fill empty
    included places" (`room_basis_children_fill_included`, a Switch);
  - "Child ages…".
  Closed, it reads as one line from `occupancy.ladderSummary`: "Adults: 1A ×1.50 · 3rd ×0.70 |
  Children: Infant 0–2.99 ×0.00 · … | 1 special combination · 1 period override". The
  single-use rule is a ladder row, not a special combination.
- *The ladder* (`workspace/OccupancyLadder.tsx`, §3.6.2) is a keyboard grid named "Occupancy and
  child pricing by period", on the matrix's `columnTemplate` (the "+ Period" column is an empty
  filler, so the period columns line up while neither grid is scrolled sideways). Its rows come
  from `ladderModel(tables, scope, basis, …)`:
  - `maxAdults` and `includedAdults` come from the server's `price_matrix` capacity: the largest
    `max_adults` of the scope's rooms, and the included adults of the scoped room or else the base
    room. Before the first answer, the rows' own values (else the room type's) are used;
  - `bands` are the version's `age_bands`, or `price_matrix.age_bands` when it has none
    (`bands.effectiveBands`; months become years with `monthsToYears`);
  - `inherited` is `price_matrix.inherited_rules`. The served shape (`period`, `adults` /
    `children`) is read as rows by `occupancy.fromInheritedRule`;
  - `defaults` is `price_matrix.occupancy_defaults`;
  - `extraUnit` is the version's `room_basis_extra_unit`.
  The model now also gives each row a `unit`, the thing its relative rules and the adult default
  are applied to: the base person price (PERSON); under ROOM the per-person share (room ÷ included
  adults, the default) or the room price (`ROOM_PRICE`, and always for the single-use combination,
  which replaces the room price). It also gives `basis` and `includedAdults`. Row labels:
  - single use: "1 Adult (single use)" (PERSON), "Single use (1 adult)" (ROOM), "1 Adult (also
    with children)" for an `ADULT 1` `1+*` rule;
  - "2 Adults" BASE (PERSON, no rule for positions 1–2), whose header reads "×1.00 each
    (default) = 2 × base person price";
  - ordinal adults ("3rd adult"; under ROOM "Extra adult (3rd)", and "1st adult · included in
    the room price (2 adults per room)"), by `tOrdinal`;
  - one row per band by its label, and child position rows "Child 2 · Child 7–11.99";
  - under each label, the unit in words ("from the base person price", "from the per-person
    share (room ÷ 2)", "from the room price").
  A band code is never rendered where a label exists; an undefined code (OCC_UNKNOWN_BAND) is
  shown as "Band ZZZ (not defined)" with a warning.
- *Cells* use `parseShorthand(text, "occupancy", {minorUnits})` and `occupancy.planOccEntries` /
  `applyOccEntry`: every relative entry is a rule of the row's slot (never adjusted once, unlike
  the base room, O4). The editing model is the matrix's (S9):
  - typing, F2, Enter and a double click edit; Enter / Shift+Enter commit and move to the next
    editable row, Tab moves sideways; Escape reverts;
  - an invalid entry stays as an error draft (`aria-invalid`, the message by
    `aria-describedby`);
  - Ctrl/Cmd+Enter writes every selected cell, Delete clears them, as one entry with the undo
    toast;
  - Ctrl/Cmd+Z / Shift+Z / Y undo and redo; Alt+Enter, Shift+F10, the ContextMenu key, a right
    click or the ▾ trigger open the rule popover.
  The reading line says what the commit stores, without arithmetic: "3rd adult · All periods
  pays ×0.70 of the base person price", "… pays the base person price +10%", "… pays a fixed
  25.00", for single use "one adult alone pays ×1.50 of the base person price (replaces the
  total)", a removal, or the refusal (AMBIGUOUS in 0- and 2-decimal currencies for amounts).
  The states render as follows (a glyph or a word, never colour alone):
  - `rule`: ×0.70;
  - `inherited`: ↳ ×0.70;
  - `period-override`: ◆ ×0.80 over an OVERRIDE tag, amber, with the tip "P4 replaces the
    all-periods rule ×0.70: ×0.80";
  - `inherit-rule`: ↳ inherit;
  - `general`: ↳ and the scope's rule for every adult or child;
  - `policy`: the value in italics with a "policy" tag; the tooltip names the source
    ("Hotel policy · PP-1 r2", parsed by `occupancy.policySource`);
  - `default`: "×1.00 default" (the BASE pair: "×1.00 each") in muted italics, the server's
    value formatted for display, with "Engine default: every adult pays the full base person
    price. Type a value to set a rule." (under ROOM: "an extra adult pays ×1.00 of the
    per-person share (room ÷ 2)");
  - `missing`: "No rule · not sellable" on two small lines, dashed red;
  - `included`: "included". A rule stored for an included place says it has no effect.
  "Always wins" and FIXED rules carry a small tag. The ⓘ precedence note
  (`occupancy.combinationNotes`, from `groupCombinations`, no ranking re-implemented) marks the
  cells that a special combination outranks for some party: same target, positions and bands
  equal or "any", and a room and period the cell covers. It is not shown on "Always wins" rules,
  included places or the single-use row. The note is the cell's tooltip and part of its
  accessible name: "Special combinations win over period rules unless the rule is marked Always
  wins: 2 Adults + 2 Children".
- *The rule popover* (`OccRulePopover` in `RuleEditorPopover.tsx`, §3.5), named "Edit rule:
  {slot} · {period}". The guest and the band are fixed by the row. It offers:
  - the rule (the `occupancy` ops, FIXED and INHERIT included) and its value (the AMBIGUOUS guard
    for amounts);
  - Rooms: all rooms, or chosen rooms, one row each;
  - "Always wins (override)" with its help text;
  - Note;
  - Applies to: this period, All periods, or selected periods.
  `occupancy.applyOccRule` writes one row per room × period, keeps the row a cell shows (its
  key) and drops its twins. The op chosen is the op stored. Remove deletes the cell's own rows in
  the ladder's scope. Focus returns to the cell. The applies-to control is shared with the room
  popover (`AppliesToField`).
- *The resolved line* (§3.6.2, GAP-2b): "Resolved · {room}" with a "Sample party" select of the
  room's valid combinations (`occupancy.partyOptions`: `validCombinations` of the room's
  capacity × the bands as multisets, at most 60; two adults by default). The room is the scoped
  one, else the base room. The chosen party goes into the page's one live preview:
  `TabProps.setSampleParty` → `VersionEditor` → `useDraftPreview({parties, partyRoom})` →
  `price_matrix(parties, party_room)`. Its cells show `party_cells[0]` per period (Money in the
  contract currency; "Not sellable" with the server's reason, band codes replaced). An answer
  for another party is never shown for the chosen one ("…" until it comes). Nothing is summed on
  the client. Parties are asked only while the section is open. A party room that the page's
  state does not hold is not sent. An answer about the saved draft (a clean draft, a draft above
  the overlay's cap, a published version) carries the party only for a room the saved draft
  holds (`draftPreview.matrixRequest(savedRooms)`), because `price_matrix` refuses the whole
  call for a party room outside the contract. The line then says to save.
- *The child ages drawer* (`workspace/ChildAgesDrawer.tsx`, §3.8) is `Drawer` md with the new
  `modal={false}`: a side panel with `role="dialog"` and no `aria-modal`, no backdrop, trap or
  scroll lock. Focus moves in on open and back to the opener on close; Escape inside it closes it
  (a Popover or tooltip in it first). The page beside it stays usable, which is the design's
  "non-blocking drawer" for the zero-modal acceptance budget. It holds:
  - *Bands:* one line each, with Label, From, Up to (not incl.), Infant and remove. "Add band"
    starts a new band from the previous end (`bands.nextBandFrom`: 2.99 → 3) and focuses its Up
    to. The new band is a draft row rendered under the key it will have, so the focus stays in
    it when it is committed. Committing a valid Up to adds it (`bands.addBand`: the next free
    code, INF only for an infant band, then CHA, CHB …). Enter there starts the next band;
    Escape or Close drop an empty one. The label shows the generated label (in the viewer's
    language and decimal mark) until the user types one; a band committed with a blank label is
    saved with the generated label (`addBand` / `updateBand`), and a generated label follows the
    ages when they change, while a typed one stays. A first band from 0 up to at most 3 years
    (`bands.defaultInfant`, whole months) is an infant band unless the user unticks it. Bands
    saved without a name (blank, or the code) are only named on "Name them"
    (`bands.nameBands`, one entry); nothing is renamed silently. Removing a band whose code
    occupancy rules name asks inline ("2 occupancy rules name this band; they are removed with
    it") and removes them in the same entry (`bands.removeBand`). Each commit is one history
    entry.
  - *Advanced: show band codes:* a Code column; a rename goes through `renameBandCode` (the
    rules follow), errors inline.
  - *AgeStrip* (`bands.bandCoverage`, on the months scale the server check uses, neighbours
    compared as `ages.band_findings` does): segments by label, gaps striped, overlaps amber, a
    minimum child age, and the counts in words ("No gaps or overlaps", "1 gap · 1 overlap").
    AGE_BANDS stays the authority.
  - *Inherited bands:* when the version has none, the served bands are listed read-only with
    their source ("Inherited from Hotel policy") and "Customise for this contract"
    (`bands.customiseBands`: the same codes, so inherited rules keep matching; a label equal to
    its code becomes the generated label; one entry).
  - *Child rules:* `age_basis`, `children_over_max_as_adults`, `infants_count_as_occupants`.
  Read-only viewers see everything disabled.
- *Band labels* (`workspace/useBandLabels.ts`) bind the pure `bands.ts` to `t()`: `gen(band)`,
  `labelOf(code)` (the code itself when no band has it) and `display(text, codes?)`
  (`displayBandCodes`: `[CODE]` always, bare codes when named). The ladder, the drawer, the
  popover, the party names and the resolved line's reasons use them; S12, S14 and S15 will too.
- *Ages* are read and written with integer maths on the typed digits only (`bands.ageMonths`:
  years → whole months, rounded half up as `ages.years_to_months`; `monthsToYears`: at most two
  decimals that give the same months back, 36 → "3", 35 → "2.92"). Ages are not money (§3.14 (f));
  nothing is computed in binary floating point.
- *Ordinals:* `i18n.translateOrdinal` / `useTexT().tOrdinal(key, n)` pick the entry's form by
  `Intl.PluralRules(locale, {type: "ordinal"})` (en one/two/few/other, ro one/other, the others
  other), falling back to `other`; plural entries may now carry `two`.
- *Strings:* 168 new keys in the six catalogues (`rates.occ.ladder.*`, `rates.occ.cell` states,
  `rates.occ.read.*`, `rates.occ.pop.*`, `rates.occ.sum.*`, `rates.occ.party.*`, `rates.occ.h.*`,
  `rates.bands.*` including `label_infant` / `label_child`, and `rates.combo.*` for the card
  names S12 will reuse).

**Deviations from the slice text, with reasons (S11).**
1. *Files beyond the slice list:*
   - `ui/overlay.tsx`, with a DOM harness check: the non-modal Drawer (deviation 2);
   - `MatrixCell.tsx`: the `wrap` and `stack` view options, for the two-line missing and
     override cells;
   - `draftPreview.ts` and `useDraftPreview.ts`: the saved rooms guard and `SampleRequest`;
   - `contracts/VersionEditor.tsx` and `contracts/tabs/shared.tsx`: the sample party must reach
     the page's single `useDraftPreview` ("one matrix call per page", S8);
   - `RuleEditorPopover.tsx`: the popover variant;
   - `bands.ts` and `occupancy.ts`: the pure helpers;
   - `tests/unit/bands.test.ts` and `draft-preview.test.ts`.
2. *The drawer is not modal.* The slice says "Drawer md", and the existing Drawer is modal. §1.3
   and S16 budget zero modal dialogs ("2 non-blocking drawers"), so `Drawer` gained
   `modal={false}` instead. S14 can use it for the Price test drawer (S8 deviation 4).
3. *ROOM basis: each included adult position is a row of its own* ("1st adult · included in the
   room price (2 adults per room)"), not one "Adults included: 2 (per room)" row as in §3.6.2.
   A rule stored for an included position stays visible, marked as having no effect: the
   engine skips it, and it may have been entered under PERSON before a basis switch.
4. *Engine defaults are shown in every cell* ("×1.00 default", the BASE pair "×1.00 each"). The
   full sentence "×1.00 each (default) = 2 × base person price" is on the BASE row's header,
   not one text across the period columns as in the §3.1 mock-up, because every column stays a
   grid cell for the keyboard and for screen readers.
5. *The version settings the region and the drawer edit are not in the undo history.* These are
   `child_ordering`, the two ROOM-basis options, `age_basis` and the two child switches. They are
   written with `setSetting`, as the Settings table does, and saved with Save; the history holds
   tables only (§3.10). The drawer says so.
6. *The resolved line prices the chosen party only*, one party per matrix call, instead of every
   offered party (up to 12 are allowed): choosing another party asks again (the server's
   figures: 0.24 s unsaved on the realistic contract, 0.29 s with 12 parties). The saved-draft
   guard of deviation 1 is new behaviour.
7. *Removing a band also removes the occupancy rules that name its code*, after an inline
   confirmation with their count. The slice does not say; such rules could never apply again
   (OCC_UNKNOWN_BAND).
8. *The ladder has the matrix's editing model, not S10's bulk tools* (Fill, copy and paste,
   Adjust…, header selection), which the slice does not ask for. Ctrl/Cmd+R and Ctrl/Cmd+D are
   kept from the browser while a ladder cell has the focus and do nothing there.
9. *The ⓘ note does not link to the combination card yet*: the cards are S12's. The tooltip and
   the accessible name name the combinations.
10. *Generated labels use the viewer's decimal mark* ("Kind 3–6,99" in German): §3.8 asks for the
    editor's language, and the mark is part of it. They are saved as typed data.

**Tests (S11).** `npm run test:unit` 226 (207 + 19):
- `workspace-occupancy.test.ts` (+11): the ROOM ladder rows (included positions not editable,
  extra adults and children priced from the per-person share or the room price, single use
  from the room price, PERSON all from the person price); default cells carry the server's
  value string (`"1.000000000"`, `"0.9"`, a child default if one were served); served inherited
  rules read as ladder rules (and `policySource`); the summary; the scopes with rules;
  `applyOccRule` (rooms × periods, Always wins and note, in place with twins dropped, unchanged,
  Remove); `planOccEntries` all or nothing (AMBIGUOUS); `occReadingOf`; `occEditText` (FIXED
  as `=25`); `combinationNotes` (periods, room scopes, Always wins, single use); `partyOptions`
  / `defaultParty`;
- `bands.test.ts` (+7): `ageMonths` / `monthsToYears` (round trip 0–216 months),
  `nextBandFrom` / `defaultInfant`, inherited bands shown and customised (a label equal to the
  code becomes the generated one), `addBand`, `updateBand` (generated labels follow, typed ones
  stay, blank ones are written), `nameBands` / `removeBand`, `bandCoverage`;
- `draft-preview.test.ts` (+1): the saved rooms guard.
Fail-first: before the pure additions, both files failed to load (`SyntaxError: … does not
provide an export named 'addBand'` / `'PARTY_OPTIONS_MAX'`); the draft-preview case failed on
the unchanged `matrixRequest` (the party was sent for a room the saved draft does not hold).
`npm run test:dom` 29 (28 + 1: the non-modal Drawer: no `aria-modal`, the page takes clicks
beside it, Escape outside leaves it open, a Popover in it closes first, focus back to the
opener).

**Verification (S11).**
- Frontend: `tsc -b`, `npm run build` and `npm run i18n:tex` (168 new keys in the six
  catalogues), `npm run test:unit` 226/226, `npm run test:dom` 29/29.
- Integration, migrated with this tree (S11 changes no server file):
  `test_pricing_workspace_api` 50, `test_age_bands` 11 and `test_pricing_policies` 14, all OK.
- Browser, on the tree's own servers (bench :8016, Vite :5186), a scratch Playwright spec 4/4
  (S16 owns the committed workspace specs):
  - (1–7) ×0.70 for all periods and ×0.80 in P4 give "◆ ×0.80 OVERRIDE", with the reading line
    "3rd adult · All periods pays ×0.70 of the base person price";
  - the 4th adult shows "×1.00 default";
  - the drawer, which opens no `aria-modal` dialog, creates 2.99 / 6.99 / 11.99 with Enter. The
    From fields pre-fill 0 / 3 / 7, the first band is an infant band, and "No gaps or overlaps"
    is shown;
  - the band rows show "No rule · not sellable", and no INF / CHA / CHB text is on the page;
  - x0 / x0.25 / x0.5 go down the band rows with Enter;
  - the resolved line for Standard with 2 adults + 1 child (Child 7–11.99) reads 175.00 /
    200.00 / 250.00 / 325.00. `price_matrix` got `party_room` with children `["CHB"]`, and no
    `save_version` was made;
  - after Save, `get_version` shows INF "Infant 0–2.99" (infant), CHA "Child 3–6.99" and CHB
    "Child 7–11.99", and the five rules;
  - switching the unpublished contract to ROOM in the basis popover gives "Single use (1 adult)",
    "Extra adult (3rd) · from the per-person share (room ÷ 2)", "1st adult: included", "Extra
    adult (4th): ×1.00 default" and no "2 Adults" row, and the extra-adult unit select turns it
    into "from the room price";
  - (8) `#ages` opens the drawer. Two bands saved without names get the notice and are named by
    "Name them"; the code is hidden until Advanced, and a rename cascades. The closed section
    reads "Adults: 3rd ×0.70 | Children: Child 3–11.99 50% | 1 special combination".
    `#occupancy` opens it, and the band's cells carry the ⓘ note naming "2 Adults + 2 Children";
  - (9) Alt+Enter opens "Edit rule: 4th adult · P2". ×0.9 for Family Suite with Always wins
    stays out of the All rooms scope and shows "◆ ×0.90 WINS OVERRIDE" in the Family Suite
    scope (marked •); Ctrl+Z restores the default. `abc` stays as an error draft with the parser's
    message, and Escape drops it;
  - (10) a published version: the ladder is `aria-readonly` with no textbox and no "Edit rule:"
    trigger, and the resolved line is priced from the frozen version (325.00 in P4) with no
    `validate_version`. The drawer's fields are disabled, with no "Add age band". At 375 px the
    page does not scroll sideways.
- The existing editor specs run on the tree unchanged: `contract-admin`, `critical-journey`,
  `editor-edits` (3), `entry-branding` (9; the two-factor case skipped as before) and
  `policy-revisions`: 15 passed.

**Performance after S11.** The ladder has at most a few dozen cells (positions up to the largest
`max_adults`, bands, child positions) × the period columns. Its model (`ladderModel`, 2–3 ms at
40 rooms × 40 periods with 480 rules, S6) and cell views are recomputed when the draft, the
server's answer or the language change, and the cells are memoised as in the matrix. On the
server, the open section adds one sample party to the page's `price_matrix` call (S3–S8
figures: 0.24 s unsaved on the realistic contract, 0.29 s with 12 parties; one party costs
less). No new endpoint and no new call kind.

**O1–O5 after S11** (all five provisional, owner input 13):
- *O5 (AMBIGUOUS)* now also covers the occupancy ladder and its popover: an amount (`=1.500`,
  `+1.500`, FIXED) is refused in 0- and 2-decimal currencies and read as 1.5 in 3-decimal ones;
  factors and percentages are exempt (unit test `planOccEntries`);
- *O4* does not apply to the ladder: every relative occupancy entry is stored as a rule;
- *O1–O3 (boards)* are unchanged; the board cells are S13's.

**Open after S11.**
- *S16 must carry the scratch scenarios (1–10 above) into the committed workspace specs*, with
  S10's.
- The ladder and the matrix scroll sideways separately; their period columns line up only while
  neither is scrolled.
- The ⓘ note's link to its card (S12). The ladder has no fill, copy and paste or Adjust….
- The version settings of the region and the drawer are not undoable (deviation 5).
- Still open from S10 (not changed by S11): the five low review items of the S10 verdict (a
  Ctrl/Cmd+Click selection copied as its bounding block, the paste anchor on a resolved row,
  WebKit copy/paste events, the focus after Adjust…, and the missing committed coverage of the
  clipboard, shortcuts and Adjust…). Still open from S8 and S9: the modal Price test drawer until
  S14, no server-side validation concurrency guard, the overlay skipping `_validate_links` and
  the window order, the cross-hotel rate plan / policy gap in `build_terms`, a weekly contract
  above the overlay's row cap not previewed unsaved, `Money` cutting resolved amounts, and
  issues not anchored in cells (S15).

**S11 review follow-up (2026-09-25).** One medium and four low verifier findings on S11, all
addressed.
1. *(medium) A room scope's ladder made false claims about the engine.* `ladderModel` read only the
   rules naming the scoped room (version and policy), so in a room scope a slot priced only by an
   All-rooms rule read "×1.00 default" ("every adult pays the full base person price") or "No rule
   · not sellable" ("a party with such a child cannot be sold"). The engine applies All-rooms
   rules to every room (`qualifiers_match`: a blank room matches any), and the resolved line
   under the grid priced such a party. The verifier's probe: All-rooms rules for adult 3 (×0.7),
   INF (×0) and CHA (×0.5), seen from SUP, gave default / missing / missing. This hit every row in
   the usual workflow (rules for All rooms, then one room for an override). An S6 unit test
   asserted the behaviour.
2. *(low) The resolved line could show another party's totals.* The ladder marked a party as
   answered during render. The first render after a party change still saw the previous answer,
   so the old party's totals showed, dimmed, under the new party until the new answer came (for
   good, if that call failed).
3. *(low) Sample parties ignored the server's limits* (12 adults, 8 children): a room above them
   could make `price_matrix` refuse the whole call, the room matrix preview included. In a large
   room with many bands, the 60-party cap cut off common parties with children.
4. *(low) The ⓘ note* was shown on an infant band row from a band-less combination rule, which
   the infant's band rule beats (G-31).
5. *(low) Wording and details:* "included" (§3.6.2: "included in the room price"); the policy
   source only in the tooltip; the single-use default without "(no single-use rule)"; a party
   change, or opening or closing the section, dimmed the whole room matrix as "updating"; the
   sample party was not cleared when the section unmounted.

**Decision (S11 review follow-up).** Frontend only; no endpoint, payload, price or rule change.
- *A cell without an own rule shows the rule the engine would use* (`occupancy.ts` `fallback` and
  `engineRank`). A room scope now reads its own rules and the All-rooms rules, both version and
  inherited policy rules. The All rooms scope still reads only its own. The candidates are the
  plain rules (no combination) of the slot and of its general slots: every adult; a band-less
  child; for a child position row, also the position row and the band row. They must hold in the
  column's period. The cell shows the one `occupancy.specificity` (CASCADE) would pick: an
  infant's band first (G-31), then origin (version > hotel + market > market > hotel > global,
  read from the source `policy:<id>/r<rev>/<scope>`), level (override > combination > period >
  room > none), qualifiers and slot. The winner is shown by where it comes from:
  - `inherited`: the slot's All-periods rule of the scope;
  - `general`: a general rule of the scope;
  - `all-rooms` (new): "↳ ×0.70" over "All rooms". The tooltip says "Family Suite has no rule of
    its own for this guest: the All rooms rule ×0.70 applies. Type a value to set one for Family
    Suite.";
  - `policy`.
  "×1.00 default" and "No rule · not sellable" remain only for slots that no applicable rule
  prices, as D12 and §3.6.2 intend. Other consequences, in the All rooms scope too:
  - a period rule of All rooms shows in a room's period column over the room's All-periods rule
    (level PERIOD > ROOM);
  - a general period rule beats the slot's All-periods rule;
  - an infant band's rule beats band-less rules, and a policy rule naming the band beats a
    version rule without one.
  Limits: the own cell still shows its own rule, because it is what the cell edits. An "Always
  wins" rule of another scope that beats it is not shown there. Special combinations stay in the
  ⓘ note. A version frozen before occupancy precedence v2 (LEGACY) is ranked as CASCADE in its
  read-only ladder; its resolved line uses the frozen ranking. All-rooms rules also shape a room
  scope's rows:
  - a rule for adult 1 or 2 splits the BASE pair;
  - an every-adult rule or a child position rule gets its row;
  - an All-rooms "also with children" single-use rule is the room's single-use row, unless the
    room has one of its own.
  *Rejected alternative:* looking up the All rooms scope only before a cell falls back to the
  default (the verifier's render-time option). It removes the false default. But it still shows
  a room's All-periods rule where an All-rooms period rule wins, and it ignores origin and G-31.
  The S6 unit test "the all-rooms rule belongs to the All rooms scope" is changed on purpose.
- *The resolved line takes a party's totals only from an answer that priced that party.*
  `useDraftPreview` tags each matrix answer with the parties it was asked for (`partiesFor`,
  `draftPreview.sampleKey` of the request's `parties` / `party_room`), and the ladder compares that
  tag with the chosen party. Another party's totals are never shown. The line reads "…" until the
  answer comes, and "—" ("The server could not calculate this party…") when that call failed. An
  answer for the same party about an older state stays, dimmed "updating".
- *A party change no longer dims the room matrix.* `stale` now compares the answer's `pricesKey`
  (the matrix key without the parties) with the state's, because the rooms' prices do not depend
  on the sample party. `pricesLoading` (a call for other room prices is in flight) drives the
  matrix's "Updating…". The call itself is still made again (deviation 6).
- *Sample parties stay within the server's limits.* `partyOptions` offers at most 12 adults and 8
  children (`PARTY_ADULTS_MAX` and `PARTY_CHILDREN_MAX`, mirroring `api/contracts.py`). Above the
  60-party cap it keeps the common parties: adults only first, then by party size (two adults
  first, then fewer children). It lists them in the usual order.
- *The ⓘ note* no longer takes a band-less combination rule on an infant row whose cell a rule
  naming the band prices (`LadderRow.infant`).
- *Wording (§3.6.2):* included places read "included in the room price". Policy cells show their
  source in the cell ("×0.40" over "from Hotel policy"); in a room scope, the tooltip adds "· All
  rooms" for a policy rule without a room. The single-use default reads "×1.00 default" over "(no
  single-use rule)".
- *Leaving the section clears the party.* OccupancySection sets the sample party to null when it
  unmounts, so later matrix calls go without it.
- *Strings:* 6 new keys in the six catalogues (`cell.all_rooms_tip`, `cell.policy_from`,
  `cell.default_single_sub`, `party_failed`, `state.all-rooms`, `state.failed`); `cell.included`
  now holds the full wording; `cell.policy_tag` is removed.

**Tests (S11 review follow-up).**
- `npm run test:unit` 235 (226 + 9):
  - `workspace-occupancy.test.ts` (+7; one S6 assertion changed on purpose):
    - the verifier's SUP probe: all-rooms ×0.7, ×0 and ×0.5 in All periods and P1; CHB missing;
      adult 4 and single use default; the All rooms scope unchanged;
    - the owner's example seen from Superior: the All-rooms P4 rule, rows shaped by All-rooms
      rules, the "also with children" variant;
    - ranking in a room scope: period > room > All rooms, general rules, an own INHERIT row, an
      All-rooms Always wins rule;
    - policy rules: version before policy, All-rooms policy rules reach a room, market over
      global;
    - G-31: an infant's band rule over a room's band-less rule, and a policy band rule over a
      version band-less one;
    - the ⓘ note on infant rows;
    - sample parties within 12 / 8, with the common ones kept in the usual order;
  - `draft-preview.test.ts` (+2): `sampleKey` (as sent vs. as chosen, field order, nothing sent)
    and `pricesKey` (ignores the party, follows edits, refreshes and saves).
- Fail-first: with the new exports stubbed to the S11 behaviour, 10 of the 52 tests in the two
  files failed. Examples: 3rd adult in SUP expected `all-rooms`, got `default`; SUP P4 expected
  all-rooms ×0.8, got inherited ×0.9; `infant` was undefined; the ⓘ note appeared on INF; a
  14-adult room gave parties that `price_matrix` refuses; the party key and prices key failed.
- `npm run test:dom` 29/29, unchanged.

**Verification (S11 review follow-up).**
- Frontend: `tsc -b`, `npm run build`, `npm run i18n:tex`, `test:unit` 235/235, `test:dom` 29/29.
- Integration, migrated with this tree (no server change): `test_pricing_workspace_api` 50,
  `test_age_bands` 11 and `test_pricing_policies` 14, all OK.
- Browser, on the tree's own servers (bench :8016, Vite :5186): a scratch spec, 3/3, and each check
  fails on the S11 sources (`4d91520`):
  1. The verifier's rules seen from Family Suite show "↳ ×0.70", "↳ ×0.00" and "↳ ×0.50", each
     over "All rooms". Child 7–11.99 reads "No rule · not sellable", the 4th adult "×1.00
     default", and single use "×1.00 default (no single-use rule)". The resolved line for 2 adults
     and an infant reads 161.00 / 184.00 / 230.00 / 299.00. Typing x0.1 writes a Family Suite rule,
     and the scope gets its •. On S11 the cells read "×1.00 default".
  2. While the answer for "3 adults" is held, the line reads "…" (not 161.00), no room-matrix
     cell is "updating" and "Updating…" is not shown; then it reads 241.50. A failed call for "1
     adult" reads "—" ("could not be calculated"). After leaving Pricing, the next `price_matrix`
     call has no `party_room`. On S11, "3 adults" showed "resolved occupancy total, updating, EUR
     161.00".
  3. Under ROOM basis, "1st adult" reads "included in the room price". On S11 it read "included".
  The S11 scratch spec passes 4/4 (its "included" expectation updated). `contract-admin`,
  `critical-journey` and `editor-edits` (3) pass: 5 passed.

**O1–O5 after the S11 review follow-up:** unchanged.

**Open after the S11 review follow-up.** Everything open after S11, plus:
- the own cell is not re-ranked against another scope's "Always wins" rule;
- a LEGACY-frozen version's ladder uses the CASCADE ranking (its resolved line is the truth);
- a sample-party change still asks for the whole `price_matrix` again (deviation 6).

**Decision (implemented in S12: the special combination cards and the structured builder).**
Branch `pricing-workspace`, frontend only (no server file changes), commits `1a67dfb` (pure
modules and unit tests), `c2f39c1` (the screens), then `32e698a`, `e984f64`, `6cefc80` and
`7dc1608` (fixes found in the browser checks, and the twin lookup). The cards and the builder sit
under the occupancy ladder, in the open "Occupancy & child pricing" region. The Advanced
"Occupancy rules" table stays under Commercial rules.
- *The cards* (`workspace/CombinationCards.tsx`, §3.7.4) list `occupancy.groupCombinations(tables)`
  under "Special combinations (n)". The single-use cards (`1+0` whole-party rules, the `1+*`
  adult-1 variant) are left out: they are the ladder's first row, as in `ladderSummary`
  (`occupancy.isSingleUseCard`, now exported). Each card shows:
  - the main text "2 Adults + 2 Children → Child 1 ×0.50 · Child 2 ×0.25" (`rates.combo.*`
    plurals; rules in card order: adults, children, whole party);
  - a second line with the children's age bands by label, the rooms and the periods: "Child 1:
    Child 7–11.99 · Child 2: Child 3–6.99 · All rooms · All periods". A band code appears only
    when no band has it (D13);
  - "◆ by period" when it holds for some periods only, and "Always wins" for an override card;
  - Edit and Remove. Remove is one history entry with the undo toast ("Combination removed: …"),
    and the focus moves to the next card's Edit. A card the builder cannot show gets "Edit in rule
    tables" (`#rules/occupancy`) instead of Edit (deviation 7);
  - `data-card` (the card's id, compared and never put into a selector) and `data-combination`
    ("2+2"), for the ⓘ link, "Show in grid" (S14) and issue anchoring (S15).
  `occupancy.cardOfRow(cards, key)` names the card that holds a rule row.
- *The ⓘ note links to its cards* (S11 deviation 9 closed). When the ladder's active cell carries
  the note, a line under the grid repeats it with one button per card ("Show combination 2 Adults
  + 2 Children"). The button brings that card into view, focuses it and outlines it for 2 s.
  `CombinationCards` takes the request as `show = {id, n}`; a remount does not replay it.
- *The builder* (`workspace/CombinationBuilder.tsx`, §3.7.1–§3.7.3) is an inline panel: a `form`
  with `role="group"`, never a modal. It opens under the cards for "Add combination" (Rooms
  preset to the ladder's rooms scope), or in place of the card for Edit. The focus starts in
  Adults. The combination is never free text:
  - *Adults and Children* are number fields, bounded by the rooms' largest capacity.
  - *Quick chips* come from `occupancy.combinationChips(capacities, scopedRooms)`: the union of
    the contract rooms' `validCombinations`. The capacities are the page's `price_matrix`
    capacities (the rows' values before the first answer), so no extra call is made. A chip no
    room in scope can host is greyed (`aria-disabled`, dashed). Its Tooltip names the rooms that
    can ("2 Adults + 2 Children: no room in scope can host it. Rooms that can: Family Suite,
    Garden Villa."). An enabled chip's Tooltip gives the full name. A combination no room in scope
    can host gets an amber warning and can still be saved.
  - *Rooms and Periods*: All, or chosen ones (checkboxes). One rule row is written for each
    room × period.
  - *One line per child*, named by `child_ordering` (`occupancy.childQualifier`): "Child 1
    (oldest)", "Child 2 (youngest)"; under YOUNGEST_FIRST the other way round; under AS_ENTERED
    "Child 1 (first in the booking)". Each line has an age band select (labels, "Any age"), a Rule
    select (the occupancy ops, FIXED and INHERIT included) and a Value. "Another age band for
    Child 1" adds a line for the same child (deviation 3). A blank line writes nothing: that child
    keeps the ladder's rules. With any children, "Rule for another child" adds child positions,
    and removing the last one takes it away again.
  - *The Value field* reads `occupancy` shorthand (`occupancy.readBuilderValue`). A form sets the
    Rule: x0.5 Multiply, 50% Percentage of, ±10% Plus/minus %, +25 Add, -25 Subtract, =25 Set
    price (and "=25" keeps FIXED when FIXED is chosen). A number alone takes the Rule chosen
    (deviation 2). Choosing another Rule keeps the number typed: the op chosen is the op stored.
    Leaving the field shows the value as stored (`builderValueText`: "0.5", a negative Plus/minus
    % as "-5"), beside a ×, % or currency suffix. Amount rules keep the AMBIGUOUS guard (O5).
    Refusals are shown on the line (`aria-invalid`, `aria-describedby`).
  - *"Adult rule"* adds an adult line with a position select (1…adults). *"Price for the whole
    party"* adds the COMBINATION line (deviation 4). Its hint says, without arithmetic, whether it
    replaces the guests' sum per night ("pays ×2.50 of the base person price in total") or adjusts
    it ("what its guests pay together changes by −5%").
  - *More* (it opens by itself for a card that uses it): any number of children ("a+*"), any
    number of adults ("*+c"; the two exclude each other), and Always wins (deviation 5).
  - *The help text* says each child's band condition is checked on its own and that a combination
    wins over period rules unless a rule is marked Always wins. It is shown in the open builder;
    otherwise under the cards heading.
  - *The reading line* (a polite live region) shows "Reads: 2 Adults + 2 Children → Child 1 ×0.50
    · Child 2 ×0.25", the bands, rooms and periods, and why Save is not possible yet (deviation 6).
  - *Save combination* (also Enter in a field) plans against the tables as last written
    (`history.current`) and writes `persistCombination(spec)` as one history entry ("Add
    combination: …" / "Edit combination: …"), replacing exactly the edited card's rows. An edited
    card saved unchanged records nothing. The toast says "Combination applied: …" and the focus
    goes to the saved card. Cancel returns the focus to Add or to the card's Edit.
- *Pure logic* (`workspace/occupancy.ts`), with no arithmetic on values:
  - `BuilderDraft` / `BuilderLine`, `newBuilderDraft`, `shownChildPositions`, `ensureChildLines`;
  - `readBuilderValue` / `builderValueText`;
  - `builderCanEdit` (now also `CombinationCard.expressible`), `builderFromCard`;
  - `planCombination`, whose `issues` are VALUE, DUPLICATE (a second rule for one guest and band),
    POSITION (an adult the combination lacks), NO_RULES, NO_ROOMS, NO_PERIODS, ANY_BOTH (the
    server's OCC_COMBINATION_QUALIFIER) and TWIN (the same guest, band, combination, room, period
    and flag as a row of another card: the server's OCC_DUPLICATE, naming that card);
  - `combinationChips`, `childQualifier`, `cardOfRow`.
- *Strings:* 77 new keys in the six catalogues (`rates.combo.*`, `rates.occ.ladder.note_line` /
  `note_show`). The chip letters are localised ("2Y+2Ç", "2E+2K", …).

**Deviations from the slice text, with reasons (S12).**
1. *Files beyond the slice list:* `occupancy.ts` (the pure builder logic above) and
   `OccupancyLadder.tsx` (the ⓘ note's links, which the S12 notes of S11 ask for).
2. *A number alone in a Value field takes the Rule chosen.* The slice says the Value field takes
   occupancy shorthand and syncs the Rule select, where a bare number is a price (the owner's
   table, D10). §3.7.1's mock shows "Rule [Multiply] Value [0.50]". Reading "0.5" there as a fixed
   price of 0.50 would store a price nobody meant. Every shorthand form still chooses the Rule;
   only an unsigned number (signed under Plus/minus %) follows the select. The ladder's cells have
   no Rule select and keep the owner's table. The reading line always says what is stored.
3. *A child can have lines for several bands* ("Child 2 3–6.99 ×0.25" and "Child 2 7–11.99 ×0.50"
   in one combination). §3.7.1 shows one line per child. ORS contracts price "2nd child 0–6.99
   free, 7–11.99 50 %", and without this such a card could not be edited in the builder.
4. *"Whole-stay price" reads "Price for the whole party" / "Whole party".* The COMBINATION rule
   prices the party's occupancy total for each night (`occupancy.price_occupancy`,
   `_REPLACING_COMBINATION_OPS`), not the stay. The hint says "Per night, …".
5. *Always wins is offered under More.* §3.7.3 writes `is_override 0`, and so does a new
   combination. Without the option, saving an edited override card would silently drop the flag.
6. *The builder refuses what the server would refuse or ignore*, with the reason shown and Save
   disabled: TWIN (OCC_DUPLICATE on validation), ANY_BOTH (OCC_COMBINATION_QUALIFIER), a second
   rule for one guest and band, an adult position the combination does not have, no rule, and no
   room or period chosen. A combination no room in scope can host only gets the amber warning:
   rooms' capacities may change later.
7. *Cards the builder cannot show are edited in the rule tables*, not "in the popover" (§3.7.4).
   These are cards with a note, a rule for every child or adult of the combination (position 0),
   a guest the combination does not have, two rules for one slot, or a non-occupancy op. The
   ladder's popover edits plain slot rules only.
8. *No committed Playwright spec* (S16 owns them); the slice's three dev-server checks and more
   ran as a scratch spec (below).

**Tests (S12).** `npm run test:unit` 244 (235 + 9), all in `workspace-occupancy.test.ts`:
- builder values: forms set the rule, a number alone takes the chosen one, FIXED stays FIXED,
  AMBIGUOUS for amounts only, and the field's text reads back to the stored rule;
- the builder writes 2A+2C (Child 1 CHB ×0.5, Child 2 CHA ×0.25) as exactly the two CHILD rows;
- editing a card replaces exactly its rows. Saved unchanged, it gives the same card back; other
  rows are untouched and in order. `cardOfRow` names the card of a row;
- the any-children card "2+*" (and back into the builder), any adults "*+1", and any + any
  refused;
- rooms {STD, DLX} × periods {P1, P2}: 4 rows per rule (child, adult 3, whole party) in table
  order, grouped back into one ◆ card that opens in the builder as saved;
- refusals: values, two rules for one child and band (a band rule next to an Any rule is fine),
  adult 3 in 2 adults, two adult-2 rules, no room or period, the twin of another card's row (an
  Always-wins twin is another rule), and hidden child lines are not saved;
- cards the builder cannot express (note, every child, adult 3 in 2 adults) and the single-use
  cards;
- quick chips: the union, and 2A+2C greyed for a room with `max_children` 1, naming the room that
  can host it;
- child positions named by OLDEST_FIRST, YOUNGEST_FIRST and AS_ENTERED.
Fail-first: before the pure additions the file failed to load (`SyntaxError: The requested module
'…/occupancy.ts' does not provide an export named 'builderFromCard'`). Three expectations were
corrected while implementing:
- a refused value no longer also reports "no rule";
- the untouched-rows check compared the wrong slice (a test bug);
- a negative Plus/minus % shows as "-5", not "-5%". The browser check showed "-5% %" beside the
  field's suffix.
`npm run test:dom` 29 (unchanged).

**Verification (S12).**
- Frontend: `tsc -b`, `npm run build`, `npm run i18n:tex` (77 new keys in the six catalogues),
  `test:unit` 244/244, `test:dom` 29/29.
- Integration, migrated with this tree (S12 changes no server file): `test_pricing_workspace_api`
  50 OK.
- Browser, on the tree's own servers (bench :8016, Vite :5186), a scratch spec 5/5
  (`scratchpad/s12/e2e/s12-combinations.spec.ts`; S16 owns the committed specs):
  1. Add combination opens no `aria-modal` dialog, and the focus is in Adults. Chip 2A+2C; Child 1
     (oldest) Child 7–11.99 `x0.5` (the Rule becomes Multiply); Child 2 (youngest) Child 3–6.99
     `0.25`. The reading line reads "Reads: 2 Adults + 2 Children → Child 1 ×0.50 · Child 2 ×0.25".
     After Save combination, the focused card reads "2 Adults + 2 Children → Child 1 ×0.50 · Child
     2 ×0.25" over "Child 1: Child 7–11.99 · Child 2: Child 3–6.99 · All rooms · All periods". No
     INF / CHA / CHB text is on the page, and there was no `save_version` before Save. After Save,
     `get_version` has exactly CHILD 1 CHB "2+2" MULTIPLY 0.5 and CHILD 2 CHA "2+2" MULTIPLY 0.25
     (all rooms, all periods, not override). The Child 7–11.99 · P2 cell names the combination in
     its label; its "Show combination 2 Adults + 2 Children" button focuses the card.
  2. Edit, saved unchanged: no toast, and the focus is back on Edit. Child 2 `x0.3` gives "… Child
     2 ×0.30" (still 2 cards), and the toast's Undo restores ×0.25. Remove moves the focus to the
     next card's "Edit in rule tables" (the 3+0 card with a note, "3 Adults → Whole party ×2.50",
     links to `#rules/occupancy`). Undo brings the card back.
  3. Standard with `max_children` 1: with All rooms 2A+2C is enabled; with Rooms = Standard it is
     `aria-disabled`, with the tooltip "2 Adults + 2 Children: no room in scope can host it. Rooms
     that can: Family Suite, Garden Villa.", and a forced click selects nothing. Standard + Garden
     Villa × P1, P2 as 3A+1C, with Child 1 50% (the Rule becomes Percentage of), Adult 3 0.6 and
     the whole party Plus/minus % -5 ("Per night, what its guests pay together changes by −5%."),
     gives one card "◆ by period" over "Child 1: Any age · Standard Sea View, Garden Villa · P1,
     P2". At 375 px the open builder does not make the page scroll sideways, and Enter in a Value
     saves "… Child 1 40% …".
  4. Under More, any number of children disables the Children field. "Rule for another child"
     and its removal work. `x0.4` saves "2 Adults + any children → Child 1 ×0.40". A new 2A+2C
     with Child 1 7–11.99 `x0.45` is refused, naming "2 Adults + 2 Children" (Save disabled).
     Cancel returns the focus to Add combination.
  5. A published version shows the card without Add, Edit or Remove. At 375 px there is no
     sideways scroll.
- The S11 scratch spec passes 4/4 on this tree (its "included" expectation updated for the S11
  follow-up wording). The committed `editor-edits`, `contract-admin`, `critical-journey`,
  `entry-branding` and `policy-revisions` give 15 passed and 1 skipped (the two-factor case, as
  before). Run against a worktree's Vite server, `entry-branding`'s source-offer case needs
  `TEX_E2E_BENCH=http://test.localhost:8016`: otherwise it compares with main's server on :8000,
  whose source hash differs.

**Performance after S12.** The builder plans on every keystroke. `planCombination` looks twins up
by signature: 6.1 ms per plan at 5,000 occupancy rules with 40 rooms × 40 periods in scope (Node,
the unit-test runtime). `groupCombinations` takes 9.6 ms at 5,000 rules and runs once per table
change (it did in S11). The chips read the page's existing `price_matrix` capacities, so there is
no new call or endpoint.

**O1–O5 after S12** (all five provisional, owner input 13):
- *O5* also covers the builder's amount values (Set price, Fixed amount, Add, Subtract), bare
  numbers included;
- *O4* does not apply: combination rules are stored as rules;
- *O1–O3* are unchanged.

**Open after S12.**
- *S16 must commit the S12 scratch scenarios 1–5* with S10's and S11's.
- *S14 "Show in grid" and S15 anchoring* can use `data-card` / `data-combination` and
  `occupancy.cardOfRow`. The request that brings a card into view (`show`) lives in
  OccupancySection today, so S14 must lift it (e.g. with the `#occupancy` region).
- The builder has no note field. Notes stay in the rule tables, and a card with a note is edited
  there.
- An adult rule for a place included in a ROOM-basis price has no effect, and the builder does
  not warn about it (the ladder does).
- Still open from S10 and S11: their low review items.

**S12 review follow-up (2026-09-25).** The verifier reported one medium finding and four low
ones on S12. Three low findings are fixed. The fourth low finding is answered with a reason and
a wording fix.
1. *(medium) An unchanged Edit and Save of a mixed-scope card deleted rows.* `groupCombinations`
   merged cells with the same signature over rooms {All, Standard} (or periods {All, P1}) into one
   card. `builderCanEdit` accepted that card. `builderFromCard` then set `roomsAll` and hid
   `['STD']`, and `planCombination` wrote All rooms only. An Edit and Save with nothing changed
   therefore dropped the STD rows and recorded "Edit combination". The builder alone could reach
   this: save 2A+2C Child 1 7–11.99 ×0.5 for All rooms, then the same for Standard, and the
   Standard card seemed to vanish. That can change prices. In the engine's CASCADE rank a room
   qualifier outranks exactness, so after the STD "2+2" row is gone, a STD "2+*" rule beats the
   All-rooms "2+2" row. The card's second line also read "All rooms · All periods" and hid
   Standard.
2. *(low) A negative value outside Plus/minus % did not read back.* ADD -5 showed as "-5" and read
   back as SUBTRACT 5, which is another row. MULTIPLY -1 showed as "x-1", which the parser
   refuses.
3. *(low) INHERIT twins were refused*, although the server's OCC_DUPLICATE (`validate._duplicates`)
   ignores INHERIT rules.
4. *(low) The value hint* said that "+25, -25 … choose the rule themselves", but under Plus/minus %
   they stay Plus/minus % (deviation 2).
5. *(low) The fail-first evidence* was a module-load error only.

**Decision (S12 review follow-up).** Frontend only. No endpoint, payload, price or rule semantics
change. Commit `fadfe8a`.
- *All rooms and named rooms are never one card, and neither are All periods and named periods*
  (`groupCombinations`). Before §3.7.4 step 3 (the cross product, else a split by room), a
  group's cells are split by scope kind: all or named rooms × all or named periods. The builder
  offers exactly these scope choices. The engine ranks them as different rules too: a named room
  or period outranks All. The verifier's scenario therefore gives two cards, "… · All rooms · All
  periods" and "… · Standard Sea View · All periods". Each opens in the builder, and saved
  unchanged, each writes back exactly its rows and records nothing. This refines §3.7.4 (step 2
  merges cells by signature only). It is the verifier's second option ("split such groups into an
  All card and a named-scope card"). *Rejected:* only marking such cards non-expressible. With
  that alone, two cards made in the builder would merge into one card that the builder cannot
  open.
- *`builderCanEdit` is the builder's invariant, whatever the grouping.* It also refuses a card
  whose rooms or periods mix All with named ones: the draft has "All" or chosen ones, so Save
  would write All only. It also refuses a negative value on any rule but Plus/minus % (and
  INHERIT). `-0` is 0. Such cards get "Edit in rule tables", whose tooltip now names "a negative
  value outside Plus/minus %". The builder never writes such a value itself: "=-25", "x-1" and
  "+-5" are SYNTAX errors, and "-25" is SUBTRACT 25. `builderValueText`'s docstring no longer
  promises a read-back for these values.
- *The card's scope line never hides named rooms or periods* (`useComboText.scope`). For a mixed
  list it reads "All rooms + Standard Sea View". The grouping no longer produces one, so this only
  guards the text.
- *INHERIT twins stay refused (finding 3, not changed, for these reasons).* A twin always has the
  same combination, room, period and flag as the new rule, so the two rows form one cell. That
  cell holds two rules for one guest and band, and its card cannot be opened in the builder. Only
  "Edit in rule tables" would remain. The engine also skips the INHERIT one
  (`occupancy.py`: "INHERIT defers"). A new INHERIT line next to a non-INHERIT rule would be
  ignored: deviation 6 refuses what the server would ignore. A new rule next to an INHERIT row
  leaves that row dead. The refusal's advice ("Edit that combination instead") leads to a card
  the builder can open, where the INHERIT line can be changed. The message now says "{cards}
  already has a rule for {line}", not "this rule": the other rule may be an INHERIT or have
  another value. The code comments of `TWIN` and `planCombination` say that TWIN goes beyond
  OCC_DUPLICATE here.
- *The value hint names the exception* (six languages): "In Value, a number alone takes the rule
  chosen, and so does a signed number under Plus/minus %. Otherwise x0.5, 50%, +10%, -10%, +25,
  -25 or =25 choose the rule themselves." No visible cue was added next to a plain number. The
  reading line already says what is stored.

**Tests (S12 review follow-up).** `npm run test:unit` 249 (244 + 5), all in
`workspace-occupancy.test.ts`:
- the verifier's scenario through the builder: All rooms, then Standard. There are two cards and
  no twin. For each card, `builderFromCard`, `planCombination` and `persistCombination` write back
  the same row set (removed 1, added 1), and the card id is unchanged ("saved unchanged records
  nothing");
- All periods and P1 give two cards, and both save back unchanged. A split by room no longer
  keeps STD's All and P1 cells together. Rooms {All, STD} × periods {All, P1} give four cards, all
  expressible;
- `builderCanEdit` / `builderFromCard` on a card whose rooms are ['', 'STD'] or whose periods are
  ['', 'P1']: false / null;
- negative values: ADD -5, MULTIPLY -1 and SUBTRACT -10 are not expressible. ADJUST_PERCENT -5 and
  ADD -0 are expressible and plan back to their rules;
- an INHERIT twin is refused. Written anyway, it forms one card with two rules for Child 1 7–11.99
  that the builder cannot open (this documents the decision; it passes on S12 too).
One existing assertion message changed (the negative ADD).
Fail-first on the S12 head `044ed20`: 4 of the 46 tests in the file failed on assertions, not at
load time:
- "the Standard card does not vanish into the All rooms card": one card instead of two;
- the periods case: one card instead of two;
- `{"rooms":["","STD"]}`: `builderCanEdit` was true;
- "ADD -5 would read back as SUBTRACT 5, another row": `expressible` was true.
`npm run test:dom` 29/29.

**Verification (S12 review follow-up).**
- Frontend: `tsc -b`, `npm run build`, `npm run i18n:tex` (3 keys reworded in the six catalogues;
  none added), `test:unit` 249/249, `test:dom` 29/29.
- Integration, migrated with this tree: `test_pricing_workspace_api` 50 OK.
- Browser, on the tree's own servers (bench :8016, Vite :5186), a scratch spec 2/2
  (`scratchpad/s12/e2e/s12-review.spec.ts`). R1 fails on the S12 sources (1 card instead of 2):
  1. R1: in the builder, 2A+2C Child 1 7–11.99 `x0.5` for All rooms, then for Standard. Two cards
     read "Child 1: Child 7–11.99 · All rooms · All periods" and "… · Standard Sea View · All
     periods". Each is opened with Edit (value "0.5") and saved unchanged: no toast, still two
     cards. After Save, `get_version` holds both CHILD 1 CHB "2+2" rows, All rooms and STD.
  2. R2: the 2+1 card with ADD -5 links to the rule tables and has no Edit. The 2+2 card with
     Plus/minus % -5 has Edit. The builder shows the new hint. A 2A+1C Child 1 `x0.4` is refused
     with "2 Adults + 1 Child already has a rule for Child 1 (oldest) in these rooms and periods."
  The S12 scratch spec passes 5/5, with its twin message updated to "a rule".
- Performance: `groupCombinations` takes 8.7 ms at 5,000 rules and `planCombination` 6.0 ms at 40
  rooms × 40 periods (as after S12).

**O1–O5 after the S12 review follow-up:** unchanged. Deviation 2 (a number alone follows the
Rule select) is for the owner to confirm with owner input 13. The ladder and matrix cells read a
plain number as a price (D10).

**Open after the S12 review follow-up.** Everything open after S12, plus:
- The ⓘ note line names cards by combination only. Two cards of one combination, e.g. All rooms
  and Standard, give two buttons with the same name. Their `data-card` targets differ.
- The builder's scope is All or chosen rooms and periods. A card that mixes both cannot come from
  the grouping any more. A scope that mixes both still cannot be written in one save.

**Decision (implemented in S13: Boards in the workspace).** Branch `pricing-workspace`, frontend
only (no server file changes), commits `7464160` (pure logic and unit tests), `0714848` (the
screen), `83dfa0f` (the grid reads the board rules once; wording), `d56302a` (a cell's context
menu opens its row's terms) and `275a261` (a board's name wraps in its row header on phones instead
of being cut to "U…"). Boards sit under Occupancy & child pricing in Pricing
(`workspace/BoardsSection.tsx`, §3.12). The Advanced "Boards" table stays under Commercial rules.
- *The section* is collapsible. Collapsed, it shows chips in `boards` order: "UAI BASE · AI −5 % ·
  HB −20.00 per adult", plus "+N period or room rules" when there are any. A board with no rule for
  all rooms and periods reads "{board}: some rooms or periods only". The open state is remembered
  per viewer (localStorage). Without a stored choice, a draft without boards opens the section and
  a draft with boards shows the chips. `#boards` opens the section and scrolls to it. "Add board"
  is in the section header, so it can be used while the section is collapsed.
- *The grid* ("Board supplements by period") is a keyboard grid on the matrix's column template
  (All periods and the period columns, in line with the matrix and the ladder). It has one row
  per board in `boards` order: the board's name, its code, a BASE badge and a line with its terms
  ("per adult per night; children 30 %, infants free", the label first when there is one). Under
  it, an indented row for each room with rules of its own ("HB · Garden Villa only"). It has the
  ladder's editing model: type, F2 / Enter, Enter / Shift+Enter and Tab to move, Escape, error
  drafts kept in the cell, Ctrl/Cmd+Enter over the selection, Delete / Backspace, Ctrl/Cmd+Z / Y
  and the undo toast. Every change is one `useWorkspaceHistory` entry.
- *Cells* read the `board` shorthand with the contract's minor units, through
  `model.planBoardEntries` → `applyBoardEntry`:
  - a bare `20` or `=20` is ABSOLUTE, 20 per room per night (O1);
  - `+20` is ADD 20 per adult; `-20` is ADD −20 per adult (O2);
  - `5%`, `+5%` and `-5%` are ADJUST_PERCENT (O3);
  - `BASE` makes the board the base board. It sets is_base on its row and takes is_base from every
    other board's rows (the radio behaviour). NO_BASE_BOARD stays the server's check, and the
    section shows the Rule tables' "no board is marked as included" warning.
  A new row takes child % and infants free from the rule it overrides, else the table defaults
  (50 %, infants free). The cell shows the amount with its unit on a second line ("−20.00 / per
  adult", "100.00 / per room", "−5% / of occupancy", "BASE / included"). A period rule has ◆ and
  the amber tint. An inherited cell shows "↳ −20.00". A cell no rule reaches reads "—" with "not
  offered". Tooltips say "Applies to {rooms} in {period}." and what an inherited cell follows.
  Each cell has `data-cellid` = `board:{board}|{room}|{period}` ("" for All rooms / All
  periods), and each row has `data-board-row` = `{board}|{room}`, for S14 and S15.
- *The reading line always names the unit* (`model.boardReadingOf`, from the same plan as the
  commit):
  - "Half board · All periods: 100.00 per room per night (fixed)";
  - "Half board · All periods: −20.00 per adult per night; children 50 %, infants free" (the child
    share of the row that will be written);
  - "All inclusive · All periods: −5% of the night's occupancy price";
  - "…: AI becomes the base board, included in the room price; UAI is no longer included and needs
    a supplement";
  - a price typed into the base board adds "; UAI is then no longer the base board";
  - a clear reads "remove this rule; it then follows {rule} ({row} · {period})" or "…; HB is then
    not offered here";
  - clearing a board's own All periods cell reads "Removes Half board and its 3 rules; you are
    asked first".
  A new row's empty editor explains the forms. Syntax errors and multipliers get board wording
  ("Boards take no multiplier. Type 20 (per room per night), +20 or -20 (per adult), 5% or -5%,
  or BASE.").
- *Clear:* Delete, or an empty entry, on a period or room cell removes that cell's row. On a
  board's own All periods cell (its rule for all rooms and periods), the whole board goes after an
  inline confirmation: "Remove Half board from this version? 3 rules are removed." It has Remove
  and Cancel, the focus on Remove, and Escape cancels. It is one history entry with the undo toast
  ("Removed: Half board").
- *Add board:* a select of RO / BB / HB / FB / AI / UAI that are not yet in the version. The
  version's first board is written at once as the base board, with the new-row defaults (ADD, no
  value, 50 %, infants free). A later board appears as a "new" row, and its All periods cell is
  edited at once. It becomes rows of the table with its first value (deviation 2). × discards it.
- *The row popover* ("Board terms: {row}", non-modal) opens from the row header's terms button, or
  from a cell with Alt+Enter, Shift+F10, the ContextMenu key or a right-click. The focus returns to
  where it came from. It has:
  - children pay (% of the adult amount), infants free and the label, written to every rule of
    the row ("These terms go to the row's 2 rules (All periods, P2)"; a note says when they differ
    now);
  - Rooms: all rooms or one contract room. It moves the row's rules, and is refused when the board
    already has rules for that scope ("HB already has rules for Family Suite: edit that row
    instead.");
  - on a board's row, "Add a rule for one room": a new indented row whose All periods cell is
    edited at once;
  - Remove board (or Remove these rules on a room row), with an inline confirmation in the popover.
  Apply is one history entry.
- *The matrix's active period is highlighted.* When a matrix cell (or its editor) gets the focus,
  `PriceMatrix`'s new `onActivePeriod` reports its column. `usePeriodChannel`, a small store read
  with `useSyncExternalStore`, carries it to the boards grid only, so the rest of Pricing does not
  re-render. The column's cells get inner side lines and its header a bar (`data-matrix-period`).
  `MatrixRowCells` / `MatrixCell` gained an optional `hlC` / `highlight`, and only the cells whose
  highlight changes re-render.
- *Pure logic* (`workspace/model.ts`, no arithmetic on values): `planBoardEntries` (all or
  nothing; `removes` names the boards a gesture removes; `BASE_SCOPE`); `boardReadingOf`;
  `boardEditText` (20, +20, -20, +5%, BASE in the viewer's decimal mark, parsing back to the same
  rule); `addBoard`; `boardModel(tables, pending)` (rows waiting for a value; the table is read
  once); `boardCellOf`; `boardTermsOf` / `setBoardTerms`; `moveBoardRows`; `removeBoardRow`;
  `boardSummary`.
- *Strings:* 91 new keys (`rates.brd.*`) in the six catalogues.

**Deviations from the slice text, with reasons (S13).**
1. *Files beyond the slice list:*
   - `model.ts`: the pure board logic above, next to S6's `applyBoardEntry`;
   - `MatrixCell.tsx`: the column highlight;
   - `PriceMatrix.tsx`: `onActivePeriod`;
   - `sections.ts`: a comment only.
2. *A board added after the first one is a pending row until its first value.* It is not a table
   row with the new-row defaults, for two reasons. The server refuses a non-base board row without
   a value (GAP-8: "a value is required; clear the cell to remove the price"). The overlay makes
   the same check, so such a row would also stop the live preview until a value was typed. The
   client never invents a value such as 0. The first board is base and needs no value, so it is
   written at once. A pending row is screen state: it is not in the undo history, and it is dropped
   by a reload or Discard.
3. *BASE is taken only in a board's own All periods cell, and in one cell per gesture*
   (`BASE_SCOPE`: "Type BASE in one board's All periods cell: the base board is included in every
   room and period."). S6's `applyBoardEntry` accepts BASE in any cell. In a period or room cell,
   BASE would take is_base from every other board's rows, which leaves the contract with a base
   board for one period or room only. Ctrl/Cmd+Enter of BASE over several cells would leave only
   the last one as base.
4. *Clearing a board's own All periods cell removes the whole board* (its room and period rules
   too), as the slice's confirmation says. A board with room rules only has no such rule, and
   clearing its empty cell removes nothing. Removing just the rule for all rooms, and keeping a
   room's rules, is done in the Rule tables.
5. *Room scope in the row popover is two controls.* Rooms moves the row's rules to another scope.
   "Add a rule for one room" adds an indented row. Without the second, room rules could only be
   created in the Rule tables. The terms (child %, infants free, label) go to every rule of the
   row, All periods and its period rules alike. The popover counts them and says when their terms
   differ now. Period-specific terms stay in the Rule tables.
6. *When the base moves to another board, the previous base keeps its stored value.* A board added
   in this session has no value: its cell reads "— no supplement yet", and the server would refuse
   the save until one is typed. A board loaded from the server has 0 (a blank value is stored as
   0, GAP-8), so it reads "+0.00 per adult", which is what the engine prices. In both cases the
   reading line says that the board "is no longer included and needs a supplement". Nothing is
   filled in automatically.
7. *No ▾ trigger in board cells.* The popover belongs to the row, not the cell (§3.12). It opens
   from the row header's button, Alt+Enter, Shift+F10, the ContextMenu key or a right-click, so
   each cell has no hidden button of its own.
8. *No fill, copy, paste or Adjust… in the boards grid.* It has Ctrl/Cmd+Enter and Delete over a
   selection, as the ladder does. Ctrl/Cmd+R / D are kept from the browser and do nothing there.
9. *The highlight is a visual cue* (§3.12 "highlights"), taken from the matrix cell that last had
   the focus. It is not announced. The matrix cell's own name already says its period.
10. *No committed Playwright spec* (S16 owns them). The slice's checks ran as a scratch spec
    (below).

**Tests (S13).** `npm run test:unit` 257 (249 + 8), all in `workspace-model.test.ts` (37 → 45):
- the slice's mappings through the grid's plan: HB `-20` → ADD "-20", `+20` → ADD "20", `20` →
  ABSOLUTE "20"; AI `-5%` → ADJUST_PERCENT "-5", `5%` → "5"; UAI `base` while AI is base → UAI 1
  and every other row 0; a period-scoped HB P4 row with the terms of the rule it overrides;
- the plan: BASE refused in a period cell, in a room row and in two cells; clearing HB's own All
  periods cell removes HB (`removes` ["HB"]); a period or room cell removes that row only; a board
  with room rules only removes nothing; the second cell's error writes nothing; AMBIGUOUS `1.500`;
  an unchanged entry gives the same tables;
- the reading: the unit and the child share of the row that will be written (HB P4 30 %, HB ·
  DLX 40 % without infants free, a new board 50 %), ABSOLUTE, `wasBase`, BASE naming the previous
  base, unchanged, remove-board with 3 rules, clear following the All periods rule, BASE_SCOPE,
  OP_NOT_ALLOWED;
- the edit text of every board op parses back to the same rule; a base board that lost its base
  starts empty;
- Add board: the first board is base with the new-row defaults, a later one is pending, an
  existing one is not added again; the owner's example typed as BASE, -5%, -20 and its chips;
- pending rows in place (a new board last, a new room rule under its board);
- `boardModel`'s cells equal the per-cell scan (`boardCellOf`) for four tables, including a
  duplicate rule and a board with room rules only;
- terms applied to every rule of the row (not to its room row), unchanged terms give the same
  tables, `mixed`; Rooms moves a room rule and refuses a taken scope; `removeBoardRow`; the
  summary.
Fail-first: before the pure additions the file failed to load (`SyntaxError: The requested module
'…/model.ts' does not provide an export named 'addBoard'`). With stub exports, 7 of 44 tests failed
on assertions (all seven S13 tests), e.g. `+ '*/*:ADD:-20' - '*/*:ADD:20'` for HB `+20`, and
`{kind: 'unchanged'}` for the reading. The equivalence test was added with the index (`83dfa0f`).
It guards the index against the scan. `npm run test:dom` 29 (unchanged).

**Verification (S13).**
- Frontend: `tsc -b`, `npm run build`, `npm run i18n:tex` (91 new keys in the six catalogues),
  `test:unit` 257/257, `test:dom` 29/29.
- Integration, migrated with this tree (S13 changes no server file): `test_pricing_workspace_api`
  50 OK.
- Browser, on the tree's own servers (bench :8016, Vite :5186), a scratch spec 6/6
  (`scratchpad/s13/e2e/s13-boards.spec.ts`):
  1. On a draft without boards, `#boards` opens the section. Add board UAI gives the base board.
     `BASE` typed into it reads "No change.". Add board AI opens its editor: `-5%` reads "All
     inclusive · All periods: −5% of the night's occupancy price". Add board HB: `-20` reads "Half
     board · All periods: −20.00 per adult per night; children 50 %, infants free". BASE moved to
     AI shows UAI "no supplement yet", and Ctrl+Z restores it. The chips read "UAI BASE", "AI −5
     %", "HB −20.00 per adult". There was no `save_version` before Save. After Save, `get_version`
     has UAI base, AI ADJUST_PERCENT −5 and HB ADD −20 (50 %, infants free). In the Price test
     (Standard, 2 adults, 3 nights in P1), board HB gives €324.00 with "board HB supplement -40.00"
     per night, and UAI gives €453.60 with "board UAI included in the price".
  2. `100` in HB reads "Half board · All periods: 100.00 per room per night (fixed)". `base` in a
     period cell is refused with the BASE_SCOPE text (`aria-invalid`), and `x2` with "Boards take
     no multiplier.". On a saved version, BASE moved to AI makes UAI read "+0.00 per adult per
     night" (deviation 6), and Ctrl+Z restores it.
  3. HB P2 `-25` reads "… children 50 %, infants free" and shows "◆ −25.00", with `data-cellid`
     `board:HB||P2`. Delete removes that row only. Delete on HB's own All periods cell asks
     "Remove Half board from this version? 1 rule is removed." (focus on Remove; Escape returns the
     focus to the cell). Remove, then the toast's Undo, brings HB back.
  4. The popover sets children 30 % (the focus returns to its button, and the row line reads "…
     children 30 %, infants free"). "Add a rule for one room" → Garden Villa opens the new row's
     editor: `-10` reads "… children 30 %, infants free". Clicking the matrix's Standard · P3
     highlights P3 in the boards grid, and ArrowRight moves the highlight to P4. Rooms moves the
     Garden Villa row to Family Suite (the focus goes to its All periods cell). Moving HB's rules
     for all rooms onto Family Suite is refused. A right-click and Alt+Enter open the row's terms.
     No `aria-modal` dialog appears.
  5. A version with boards opens collapsed with the chips. `#boards` opens the section and scrolls
     to it. At 375 px the page does not scroll sideways.
  6. On a published version the grid is `aria-readonly`: no Add board, no terms button, and typing
     or Delete opens no editor.
- Earlier scratch specs on this tree: S11 4/4 and S12 5/5 + review 2/2
  (`scratchpad/s12/e2e`); S10 review 3/3 and v2 review 5/5. S10 bulk passed 3/6. Its test 4
  clicks `getByRole("columnheader").filter({hasText: "P2"})` on the whole page, which since S11
  also matches the occupancy ladder's P2 header (the boards grid is collapsed in that draft).
  With the locator scoped to the matrix grid, S10 bulk passes 6/6
  (`scratchpad/s13/e2e-s10/s10-bulk-scoped.spec.ts`).
- Committed specs: `editor-edits`, `contract-admin`, `critical-journey`, `entry-branding` (with
  `TEX_E2E_BENCH=http://test.localhost:8016`) and `policy-revisions`: 15 passed, 1 skipped (the
  two-factor case, as before).

**Performance after S13.** `boardModel` reads the board rules once into a map, as `matrixModel`
does. A per-cell scan took 885 ms at 4,800 rules (3 boards × 40 rooms × 40 periods: 123 grid rows
× 41 columns, Node). The map takes 18 ms. A usual contract has a few board rules, and the model is
built once per table change. The reading line plans each keystroke over the board rules (linear).
Moving in the matrix re-renders only the boards grid, and in it only the cells of the old and the
new highlighted column. No new call or endpoint: the boards grid uses no server data. The Price
test prices board supplements as before.

**O1–O5 after S13** (all five provisional, owner input 13):
- *O1* is implemented in the board cells: a bare `100` is ABSOLUTE 100 per room per night, and
  the reading line says "100.00 per room per night (fixed)" before commit (browser check 2).
- *O2* is implemented: `-20` is ADD −20 per adult. The Price test shows "board HB supplement
  -40.00" per night for 2 adults (browser check 1).
- *O3* is implemented: `5%` / `-5%` is ADJUST_PERCENT, read as "% of the night's occupancy price".
- *O5* covers the board amounts (ABSOLUTE, ADD): `1.500` is refused in 0- and 2-decimal
  currencies (unit test). Percentages are exempt.
- *O4* does not apply to boards.

**Open after S13.**
- *S16 must commit the S13 scratch scenarios 1–6* with S10's, S11's and S12's. S10 bulk test 4's
  column-header locator must be scoped to the matrix grid ("Room prices by period").
- *S14 and S15* can find board cells by `data-cellid` `board:{board}|{room}|{period}` (exported
  as `BoardsSection.boardCellId`) and rows by `data-board-row`. The section opens with `#boards`.
  As with `#occupancy` (S11 review), following the same hash again does not reopen it.
- Pending rows (a new board, a new room rule) are screen state: not in the undo history, and gone
  after a reload or Discard.
- One `localStorage` key keeps the open state for every version, as with Occupancy (S11 review).
- Period-specific board terms (child %, infants free, label per period) and removing a board's
  rule for all rooms while keeping its room rules stay in the Rule tables.
- Still open from S10–S12: their low review items.

**Decision (implemented in S14: the Price test drawer and the Explain ladder).** Branch
`pricing-workspace`, frontend only (no server file changes), commits `812e7f0` (pure logic, recorded
fixtures and unit tests), `3c7949c` (design system: `ContextMenu`, `revealElement`), `25e6c77` (the
screens) and `7669bd8` (`contract-admin.spec.ts`).
- *The drawer* ("Price test", `PriceTestPanel` in the existing `Drawer` with `modal={false}`: no
  `aria-modal`, the matrix stays usable beside it; this closes S8 deviation 4). It opens from the
  header's Price test (starting from the matrix cell that last had the focus) and from a matrix
  cell's context menu "Test this price" (starting from that cell). Another "Test this price" while
  it is open starts it again there. Preview & audit keeps the full-size panel. Both are shown only
  when `doc.can_preview`; the request carries `data` when the draft is editable and dirty (below
  the overlay's row cap), with "Priced with your unsaved changes."; no save is made.
- *Prefill* (pure `priceTest.prefillOf`): the active row's room (else the base room, else the
  first); 3 nights from the active period's start (All periods or no active cell: the first period
  that has not ended), clamped to the stay window so that the 3 nights fit in it (the engine refuses
  a night after `stay_to`); the base board; 2 adults. Without periods, the former default (two weeks
  after today, or the first stay day).
- *Children:* whole years by default ("Age of child {n}", unchanged for the E2E helpers). A select
  per child ("Child {n}: age given in": years / months (exact) / date of birth (exact)) sends
  `{age_months}` (0–215) or `{dob}` (GAP-6). Switching carries whole months (×12, or the completed
  years; integers only); a date of birth starts empty. An entry the server would refuse keeps
  Calculate off and the field invalid.
- *Calculate / Enter* prices the stay. After the first result, *Live* re-prices a settled edit of
  the form or of the draft: the key is the request plus the draft's fingerprint (`preview.key`,
  or the saved draft and `doc.modified`), debounced 300 ms (`MATRIX_DEBOUNCE_MS`); a newer call
  aborts the older one. A result for older inputs is dimmed with "The stay or the contract changed
  since this price. Calculate again to update it." ("Updating the price…" with Live).
- *The Explain ladder* (pure `explainLadder(quote)`, `ExplainLadder.tsx`): the final price, then
  one table per block of nights and one for the whole stay, each named by its caption ("Nights 1–3 ·
  P2", "Whole stay"), with a row header per stage, "Before" and "After" columns, the explanation
  steps as detail lines under their stage (with their own served before/after), and the caption
  "Stages are shown in the order the engine applies them." Stages per night, in engine order
  (§3.13.1): Base (the night's first ROOM_ABSOLUTE after), Period (the PERIOD step's code and name
  and the period's dates; "no amount (period used to choose rules)"), Room (the ROOM_DERIVED steps'
  first before → last after; an entered price reads "entered price, no derivation" with
  `nights[].unit`), Occupancy (adults) (`unit` → `subtotal_adults`; ROOM_BASIS, ADULT_SLOT), Children
  (only with children: `subtotal_adults` → `subtotal_children`; CHILD_SLOT, CHILD_INCLUDED,
  CHILD_AS_ADULT), Special combination (only with a COMBINATION_RULE step: its before → after), Board
  (`occupancy` → `subtotal_board`; "included" or "supplement {nights[].board}"), Period {code}
  adjustment (applied to occupancy + board) and Rate plan (only with their steps), Night cost
  (`cost`), Cost offers (only when `cost` ≠ `cost_net` or the stay has cost-offer steps), Markup
  (`cost_net` → `sell_contract`), Currency conversion (`sell_contract` → `sell`, "1 EUR = 1.000000
  EUR"), Promotion (`sell` → `final`). The stay: Cost offers and Promotion (when the stay has such
  steps: the applied offers' first before → last after, rejected ones as lines), Tax
  (`totals.subtotal` → `totals.total`, "tax {totals.tax}" or "{amount} included in the prices") and
  the Final price (`totals.total`, the TOTAL step). A quote without the GAP-12 keys leaves Occupancy,
  Children and Board blank ("not recorded in this quote"); nothing is computed. Consecutive nights
  whose stages are string-identical form one block; the night selector ("Nights shown") defaults to
  All nights, and one night shows its block alone ("Night 2 · P2"). Amounts are the served strings
  formatted with the currency's minor units (`decText`; the currency code is added when the contract
  and sell currencies differ).
- *The chain check* (`chainBreaks`): per night, and within the stay block. Values are compared as
  `normaliseDecimal` canonical strings; an unreadable string is never a mismatch. A break is logged
  with `console.warn` in dev builds only.
- *"Why this price"* keeps its DOM ("Rule applied:", the level badge, the label, "overrode"). Rule
  labels, overridden labels and the step sentences pass through `useBandLabels.display` in every
  language (the bracket rule, plus a child step's band printed bare when the band has no label); an
  unsellable NO_CHILD_RULE reason is shown with every band code mapped. A step whose rule id names a
  row of the draft (`~<_key>` unsaved, the saved row's name otherwise; pure `showTargetOf`) has
  "Show in grid" ("Show in grid: {rule}"): the drawer closes, Pricing opens (from Preview & audit
  too) and the target is brought into view, focused and outlined for a moment (`revealElement`):
  the matrix cell (`data-cellid` `{room}|{period}`); for an occupancy rule its combination card
  (single-use rows stay in the ladder), else its ladder cell in the rule's room scope (ladder cells
  now carry `data-cellid` `occ:{row}|{period}`, `OccupancyLadder.ladderCellId`); a board cell
  (`board:{board}|{room}|{period}`). The section opens for the request. A request is consumed once
  (`show` / `onShown` in `VersionEditor`), so a remount never replays it.
- *Localisation:* `ExplainStep` gains `message` and `params` (the server always sent them). A
  non-English viewer gets `rates.explain.<CODE>` with the step's params when the catalogue has the
  template (24 codes: CONTRACT, PERIOD, ROOM_ABSOLUTE, ROOM_DERIVED, ROOM_BASIS, ADULT_SLOT,
  CHILD_SLOT, CHILD_INCLUDED, CHILD_AS_ADULT, COMBINATION_RULE, OCCUPANCY_TOTAL, BOARD_BASE,
  BOARD_SUPPLEMENT, PERIOD_ADJUSTMENT, RATE_PLAN_ADJUSTMENT, NIGHT_COST, NO_MARKUP, MARKUP,
  MARKUP_STACK, PROMO_APPLIED, PROMO_REJECTED, COUPON_REJECTED, TAX, TOTAL), else the server's
  sentence as English viewers read it. Params: room ids become room names, a child's label
  ("Child 1 (8y, CHB)", pure `parseChildLabel`) becomes "Kind 1 (8 J., {band label})", describe_op
  strings (pure `parseOpText`) keep their number in the viewer's decimal mark ("× 1,30", "50 %
  von"), decimals go through `decText`, boards and the basis get their names, a rate plan its name.
  English viewers read the server text after the band-code mapping only. Stage labels are
  `rates.pt.stage.*`. `useTexT()` gains `has(key)` (`hasTexKey`).
- *The matrix cell's context menu* (`ContextMenu`, new in `ui/popover.tsx`: a role="menu" opened by
  the page with the Menu's keys; the focus returns to the cell): "Edit rule…" (Alt+↵) on an editable
  cell and "Test this price" when the viewer may use the Price test; resolved and read-only cells get
  the menu too. It opens from a right-click (a long press), Shift+F10 and the ContextMenu key.
  Alt+Enter and the ▾ trigger still open the rule popover directly.
- *`contract-admin.spec.ts`* (lines 109-110) now reads `Child \[Child\] 50(\.00)?% of` and `Child
  \[Infant\] 0(\.00)?% of`, the labels that spec gives the bands CHD and INF.
- *Strings:* 83 new keys (`rates.pt.*`, `rates.explain.*`, `rates.ws.cell.menu*`) in the six
  catalogues.

**Deviations from the slice text, with reasons (S14).**
1. *Files beyond the slice list:* `explainText.ts` and `priceTest.ts` (pure helpers, tested), the
   design system (`ui/popover.tsx` `ContextMenu`, `ui/grid.ts` `revealElement`, the DOM harness
   case), `i18n/index.ts` (`has`), `VersionEditor.tsx` (the non-modal drawer, the prefill request,
   the Show in grid request), `tabs/shared.tsx` (the new TabProps), `PriceMatrix.tsx` (the cell
   menu, the active cell, its show request), `OccupancySection.tsx` / `OccupancyLadder.tsx` and
   `BoardsSection.tsx` (their show requests; ladder cell ids).
2. *The context-menu gestures open a menu* on a matrix cell when the viewer may use the Price test.
   S9 opened the rule popover directly from Shift+F10, the ContextMenu key and a right-click; now the
   popover is one Enter away ("Edit rule…" is first and focused), and Alt+Enter and ▾ are unchanged.
   Without `can_preview` the gestures open the popover as before. The menu is the only way to reach
   "Test this price" from a resolved or read-only cell by keyboard. S9's scratch scenario "Shift+F10
   opens it too" must press Enter first (the adapted copy passes, below).
3. *Stay stages appear with only rejected offers.* Fixture (a) holds the demo market's rejected
   "Early booker 10%", so its stay stages are Promotion (a line, no amounts), Tax and Final price. A
   stage shown only for a step the ladder does not place (g) has no amounts and does not break the
   chain.
4. *The chain check's reading of "the previous amount-bearing stage":* a stage with only a value
   (Base, Night cost, the final price, an entered Room) is compared by that value; a stage whose
   night field is missing (e) resets the chain instead of reporting a break; at stay level Cost
   offers, Promotion and Tax each start a chain (contract cost, the sell price and the subtotal with
   extras and rounding are different quantities), each applied offer inside them starts from the
   previous one's after, and the final price is compared with Tax's after.
5. *Where detail lines go:* OCCUPANCY_TOTAL closes the last of Occupancy / Children / Special
   combination; CHILD_AS_ADULT (a stay-level step) goes under every night's Children; the FX steps of
   the accommodation go under every night's Currency conversion (identity conversions have none);
   cost-offer and promotion steps are stay lines (the night stages show `cost` → `cost_net` and
   `sell` → `final` only). Only consecutive identical nights are grouped, so blocks stay in date
   order.
6. *Two night selectors:* the ladder's ("Nights shown", All nights by default) and the Why list's
   own ("Night", first night by default, as before, which keeps a long stay's list short).
7. *The exact-age "toggle" is a select per child* (years / months / date of birth), which also names
   the unit of the field; the form still takes at most 6 children (the server takes 12).
8. *Templates exist for 24 codes;* FX, COUPON_APPLIED, EXTRA*, BOOKING_BASKET*, BASKET_FORFEIT and
   any new code keep the server's sentence. Free text in params (promotion reasons, markup and rule
   labels, tax categories, period names) stays as served; rule labels are identities and are only
   band-mapped.
9. *Show in grid* is offered for rules that are rows of this draft (room prices, occupancy rules,
   board rules). A pricing policy's rule, the engine's adult default, markups, promotions and rate
   plans have none. A ladder rule switches the ladder to its room scope.
10. *No committed Playwright spec* (S16 owns them); only `contract-admin.spec.ts` changed. The
    slice's checks ran as a scratch spec (below).

**Tests (S14).** `npm run test:unit` 272 (257 + 15, `tests/unit/explain-ladder.test.ts` on the
recorded fixtures `tests/fixtures/quote-deluxe-2a1c.json`, `quote-combination-2a2c.json`,
`quote-period-adjust.json`, `quote-room-basis.json`: `preview_price` with the unsaved overlay on this
tree's bench, trimmed to the keys the ladder reads):
- (a) Deluxe 2A + child 8, 3 nights in P2, BB: the stage order; Base after `80.000000`; Period
  without amount; Room `80.000000` → `108.000000`; Occupancy `108.000000` → `216.000000`; Children
  `216.000000` → `270.000000` with the CHILD_SLOT line `54.000000`; Board `270.000000` →
  `270.000000` (included); Night cost `270.000000`; no Special combination, Period adjustment or Rate
  plan; one block "Nights 1–3"; no chain break; every value a served string;
- (b) 2A+2C with a whole-party rule: Special combination's before is `subtotal_children`, its after
  `occupancy`;
- (c) a P2 night adjustment and a rate plan: Period adjustment after Board, before Rate plan and
  Night cost, its before `subtotal_board`;
- (d) ROOM basis: Occupancy starts from the room price, with the ROOM_BASIS line;
- (e) without `subtotal_*`: Occupancy, Children and Board blank, missing, lines kept, no break;
- (f) a night's `unit` edited: one break (`occupancy`, 109 after `room` 108) on that night, and the
  night is a block of its own; canonical comparison (`216.000000` = `216`, unreadable → null);
- (g) unknown codes: a board-stage step under Board, a rate-plan step shows an optional stage
  without amounts, a stay tax step under Tax, a contract-stage step nowhere in the ladder;
- stay promotions and cost offers (applied chain, a break inside), an unsellable quote;
- `parseOpText`, `parseChildLabel`, `bareBandCodes`; `prefillOf` (active cell, All periods, no
  cell, clamping to the stay window, the first period not ended, no periods); `childPayload` /
  `withChildMode`; `showTargetOf` (`~key`, `~table-n`, a saved name, the engine default, a markup,
  a removed row).
`npm run test:dom` 30 (29 + the ContextMenu case: right-click, Shift+F10, the ContextMenu key,
arrows, typeahead, Enter/Space, Escape and Tab back to the cell, an outside click).
Fail-first: without the three pure modules the unit file fails to load (`ERR_MODULE_NOT_FOUND:
…/workspace/explainLadder.ts`); `contract-admin.spec.ts` with its old regexes fails on this tree
(`Expected pattern: /Rule applied: Version Child \[CHD\] 50(\.00)?% of/`; the list reads "Child
[Child] 50% of" and "Child [Infant] 0% of"), and passes with the new ones.

**Verification (S14).**
- Frontend: `tsc -b`, `npm run build`, `npm run i18n:tex` (83 new keys in the six catalogues),
  `test:unit` 272/272, `test:dom` 30/30. Python unit 491 OK (no server change).
- Integration, migrated with this tree: `test_pricing_workspace_api` 50 OK.
- Browser, on the tree's own servers (bench :8016, Vite :5186), a scratch spec 5/5
  (`scratchpad/s14/e2e/s14-price-test.spec.ts`):
  1. Deluxe ×1.35 typed unsaved; the right-click menu on Deluxe's resolved P2 cell has "Test this
     price"; the drawer has no `aria-modal` and is prefilled (Deluxe, 1–4 May, BB, 2 adults, "Priced
     with your unsaved changes."). Child 8, Calculate: the table "Nights 1–3 · P2" reads Base price
     80.00; Period "no amount (period used to choose rules)"; Room 80.00 → 108.00; Occupancy (adults)
     108.00 → 216.00; Children 216.00 → 270.00 with the child line 54.00; Board 270.00 → 270.00
     "included"; Night cost 270.00; no Special combination, Period adjustment or Rate plan; the
     served `nights[0]` fields are those strings; the order caption and "Whole stay" are shown; no
     `save_version` request; one night selected shows "Night 2 · P2".
  2. `{age_months: 143}` is sent and priced "Child 1 (11y11m, Child 7–11.99)"; 144 reads "child 1 is
     above the oldest child band: priced as adult"; a date of birth is sent as `{dob}`.
  3. With Superior · P4 focused, the header's Price test starts from Superior and 1 July. The Why
     list reads "Child 1 [Child 7–11.99] @2A+2C" and "Child 2 [Child 3–6.99] @2A+2C" and no band
     code. "Show in grid" on the Superior P4 rule closes the drawer and focuses Superior · P4; on the
     2A+2C child rule it focuses the 2+2 card; on the band rule of a 2A+1C test it focuses the ladder
     cell "Child 7–11.99 · All periods".
  4. Live: 3 adults re-prices without Calculate; Standard P1 typed 75 in the matrix beside the open
     drawer re-prices it; no `save_version`. Preview & audit prices with the ladder, and its "Show in
     grid" opens Pricing (`#pricing`) on Standard · P1. Escape closes the drawer and the focus
     returns to the Price test button.
  5. German: the stage labels (Basispreis, Zeitraum, Zimmer, Belegung (Erwachsene), Kinder,
     Verpflegung, Kosten der Nacht, Aufschlag, Währungsumrechnung, Aktion), the caption, and the
     sentences "Garden Villa = Standard Sea View × 1,30 → 104,00", "Kind 1 (8 J., Child 7–11.99) ×
     0,50 104,00 = 52,00", "Zeitraum P2 (May)", "Übernachtung mit Frühstück: im Preis enthalten".
  At 375 px the drawer's body does not scroll sideways.
- Committed specs: `contract-admin` (with the new regexes), `critical-journey`, `editor-edits`,
  `entry-branding` (`TEX_E2E_BENCH=http://test.localhost:8016`) and `policy-revisions`: 15 passed, 1
  skipped (the two-factor case, as before).
- Earlier scratch specs on this tree: S11 rerun 4/4, S12 5/5 + review 2/2, S13 6/6, S10 bulk
  (scoped) 6/6. S9's matrix spec passes 4/8 as it stands: its fifth test expects Shift+F10 to open
  the popover (deviation 2), and the three after it did not run. A copy with that step reading "the
  cell menu, Enter on Edit rule…" passes 8/8 (`scratchpad/s14/e2e-s9/s9-matrix-menu.spec.ts`).

**Performance after S14.** `explainLadder` maps a 90-night quote (993 steps) in 4.6 ms (Node). The
Why list looks each rule id up once per table state (a 5,000-row draft took 68.5 ms for 993
uncached lookups; the cache leaves one per distinct rule). Live makes one `preview_price` call per
settled edit (300 ms), aborting the older one; the drawer adds no other call.

**O1–O5 after S14** (all five provisional, owner input 13): unchanged. The Price test prices what
O1–O5 stored; the ladder shows the board supplement (O1–O3) and the base room's adjusted price (O4)
as the server priced them.

**Open after S14.**
- *S16 must commit the S14 scratch scenarios 1–5* with those of S10–S13, and change S9's "Shift+F10
  opens it too" step to the cell menu (Enter on "Edit rule…").
- *S15* can reuse `revealElement`, the ladder's `data-cellid` (`occ:{row}|{period}`,
  `ladderCellId`) and the `show` / `onShown` request of `TabProps` for issue anchoring.
- Useful names for tests: dialog "Price test"; tables named by their captions ("Nights 1–3 · P2",
  "Night 2 · P2", "Whole stay"), row headers per stage, detail rows `tr[data-line="<CODE>"]`, stage
  rows `tr[data-stage]`; select "Nights shown"; "Child {n}: age given in", "Age of child {n} in
  months", "Date of birth of child {n}"; switch "Live"; buttons "Show in grid: {rule}"; menu "Cell
  actions: {room} · {period}" with "Edit rule…" and "Test this price".
- The `#occupancy` / `#boards` hash still does not reopen a section followed a second time (S11 and
  S13 review items); Show in grid always opens it.
- Still open from S10–S13: their low review items.

**Decision (implemented in S15: validation anchored in the workspace, band labels in every issue
list, the literal i18n key scan).** Branch `pricing-workspace`, frontend only (no server file
changes), commits `716e51f` (pure `issues.ts` and its tests), `665efd0` (the screens), `6ee38ef`
(the i18n check) and `c716e90` (`data-issue` on period headers).
- *Anchoring* (pure `workspace/issues.ts`, `anchorIssues(issues, tables, {bands})` → `byCell`
  (anchor id → issues), `anchors` (per issue) and `unanchored`). The anchor ids are the grids'
  `data-cellid`: matrix `{room}|{period}`, board `board:{board}|{room}|{period}`, ladder
  `occ:{row}|{period}` in All rooms and `occ:{row}|{period}@{room}` in a room scope, a period
  header `period:{code}`, a card `card:{id}` (matched on `data-card`, never put in a selector).
  Precedence, first match wins:
  1. `ref.rule_ids` (all of them) and `ref.rule_id`: `~<_key>` (and `~<table>-<n>`, as `ruleRowOf`)
     or a saved row's `_name`. A room price row marks its matrix cell; an occupancy rule its
     combination card (single use: the ladder's first row) or its ladder cell in the rule's own rooms
     scope (`ladderRowIdOf`: `adult:{n}:`, `adult_any:0:`, `band:0:{BAND}`, `child:{n}:{BAND}`,
     `child_any:0:`, `single:0:`); a board rule its board cell. A named row whose room or period the
     contract does not have (ROOM_RULE_UNKNOWN_*, OCC_UNKNOWN_ROOM/PERIOD) is not on screen: the
     issue stays in the lists.
  2. Only when no rule id names a row of the draft (a pricing policy's rule, a row removed since),
     the ref's fields: a board (+ room, period) → the board cell; a party (adults + children) → the
     combination card that takes it (a "*" card too; exact counts, then a named room, then a named
     period win; a single-use card → the ladder's first row); an age band the ladder shows (the
     effective bands, or a band a plain rule of the scope names) → its band row in the ref's room
     scope and period; room + period → the matrix cell, but never for an issue about guests (a party,
     a band or OCC_*); a period alone → its header (PERIOD_OVERLAP: both headers).
  3. Otherwise unanchored: the header and selling terms, rate plans, offers, AGE_BANDS about two
     bands, a room alone (ROOM_CAPACITY, INCLUDED_ADULTS), NO_BASE_BOARD.
- *Where it shows:* `useCellIssues` gives a cell its issues' level and text ("Error: …" / "Warning:
  …", errors first, at most three and "+N more", band labels). `MatrixCell` (the matrix, the ladder
  and the boards grid) draws a glyph (an octagon for an error, a triangle for a warning) and an
  underline (rose / amber), sets `aria-invalid` for an error, and puts the cell's tooltip text, a
  draft error and the issue text in one hidden description (`aria-describedby`); the tooltip shows
  the messages too. Period headers (PERIOD_*) get the glyph, a bottom line, `aria-invalid` for an
  error, the description and a Tooltip, and can take the focus while they carry an issue. A
  combination card gets a coloured border and its messages as a visible line under it
  (`aria-describedby`). Issues older than the state on screen (`issuesStale`) are dimmed. Every
  element carries `data-issue` (error / warning).
- *The live check's list* (the chip's popover, `IssueNav` in `ContextHeader`): issues grouped by
  section (`issuesBySection`, section order, errors first, each section named "{Section}: N
  issues"), at most 50 per section. Each is a button: a click closes the popover and shows the
  issue (`issuePlace`): its first anchor through the "Show in grid" request of S14 (`showInGrid`:
  Pricing opens, the Occupancy or Boards section opens, the ladder switches to the anchor's rooms
  scope, and the cell, card or header is brought into view and focused with `revealElement`);
  without an anchor, the Pricing region that holds its subject (the child ages drawer for AGE_BANDS*
  and NO_AGE_BANDS, Boards for BOARD_* and NO_BASE_BOARD, Occupancy for OCC_* and sweep parties, the
  matrix for the rest), the Advanced rule table that lists it (Commercial rules, `issueTable`) or
  Offers. `ShowTarget` gains `ladder`, `card`, `period` and `region`. The "saved" mode lists the
  report stored at publish (anchored by saved row names; no `validate_version` call); in catalogue
  mode the chip stays hidden.
- *Band labels in every issue list* (D13): `issueMessage(issue, display)` passes the message through
  `useBandLabels.display` with `ref.age_bands`, else `[ref.age_band]` (the bracket rule for the
  sweep's "STD 2A+2C [CHB]: …" always applies). `VersionEditor` computes the labels once
  (`effectiveBands` of the draft and the served bands), the anchors once per issues and tables, and
  hands `issueText` to the cells, the chip, Preview & audit, the Publish dialog's check and, through
  `IssueFormatContext`, to the Advanced rule tables' `TabIssues`. `IssueList` gains `format`
  (the server's message by default, so the policy editor is unchanged).
- *The i18n check* (`scripts/tex-i18n-check.mjs`) also scans `src/tex/**/*.{ts,tsx}` for `t("…")`,
  `t('…')` and `tOrdinal("…")` string literals (not template literals, not a concatenation) and
  fails when a key is missing from the English catalogue of its area (the area whose keys share its
  first segment). Parity and placeholder checks are unchanged. The tree passes (5,038 literal keys).
- *Strings:* 7 new `rates.ws.issue.*` keys in the six catalogues.

**Deviations from the slice text, with reasons (S15).**
1. *Files beyond the slice list:* `useCellIssues.ts` (new: a cell's issue state and text),
   `MatrixCell.tsx` (the `issue` view field), `PeriodHeader.tsx` (period anchors), `OccupancySection.tsx`
   (the new show requests; passes the issues on), `priceTest.ts` (`ShowTarget` kinds),
   `VersionEditor.tsx` (labels, anchors and routing once per editor; the formatter context),
   `tabs/shared.tsx` (TabProps `anchored`, `issueText`, `issuesStale`; `TabIssues` formats),
   `tabs/PreviewTab.tsx` and `VersionActions.tsx` (Preview & audit's list and the Publish dialog's
   check with labels), and the six catalogues.
2. *A warning is described, not invalid:* a cell whose issues are only warnings shows the amber glyph
   and line and has the description, but no `aria-invalid` (a warning does not refuse the value or
   the publish). Errors set `aria-invalid`, as the slice says.
3. *Cards are list items*, where ARIA 1.2 does not allow `aria-invalid`; a card shows its messages as
   a visible line referenced by `aria-describedby` instead. A period header (columnheader) takes
   `aria-invalid`.
4. *Precedence where the slice's rules overlap* (a ref usually has several fields): rule ids first
   (all of `rule_ids`), then board, party, band, room + period, period; a party or band issue never
   marks a room price; a rule id that names a row off screen leaves the issue unanchored rather than
   falling back to that rule's own ref; a room alone is not anchored. A rule id wins over the ref's
   period: ROOM_NEGATIVE and the room_unit errors name the rule that prices the cell, which may be the
   room's All periods rule, so that cell is marked (the resolved row already shows "Unsellable" in
   the period).
5. *Ladder ids in room scopes* gain `@{room}` (S14's `occ:{row}|{period}` is unchanged for All
   rooms), so a room's cell is never taken for the All-rooms one. A sweep party is anchored in its
   room's scope, which shows the rules the engine uses for that room (S11 review).
6. *A click on an unanchored issue* opens the region, rule table or section that holds its subject
   (the slice only says "focuses its cell").
7. *"A duplicate SUP P4 row created through the Advanced tables":* the Advanced Room prices table is
   a room × period grid that keeps one row per cell (it cannot create a twin), so the SUP P4 twin was
   stored with `save_version` (as an import would) and loaded; the Advanced-tables path was checked
   with the Boards table's "Duplicate row" (BOARD_DUPLICATE), which marks its board cell and adds to
   the chip's count.
8. *The chip's list shows 50 issues per section* ("+N more"): the sweep can report 200 warnings.
   Preview & audit keeps `IssueList` (50 per level).
9. *The literal scan also reads `tOrdinal("…")` and `x.t("…")`*, and ignores a literal without a dot.
10. *No committed Playwright spec* (S16 owns them). The slice's checks ran as a scratch spec (below).

**Tests (S15).** `npm run test:unit` 287 (272 + 15, `tests/unit/workspace-issues.test.ts`): anchor
ids; `ladderRowIdOf` per target; `~key`, `~table-n` and `_name` anchoring (a SUP P4 twin marks one
cell once); room + period, and a rule id the draft does not hold falling back to it; unknown room,
unknown period and a room alone unanchored; occupancy rules in their scope, a combination row on its
card, single use on the ladder's first row; `age_band` → the band row (All rooms, a sweep party's
room, inherited bands, an unknown band not anchored); a party → the All-rooms 2+2 card, the room's
own card first, a "2+*" card; board refs, period headers (PERIOD_OVERLAP both); unanchored header
issues; `issuePlace` for every kind; `issuesBySection`; `issueBandCodes`; "age bands CHA and CHB
overlap at …" → "age bands Child 3–6.99 and School age overlap at …"; "STD 2A+2C [CHB]: … (CHB)" →
"STD 2A+2C [School age]: … (School age)", and only the bracket without a ref.
Fail-first: without `issues.ts` the file fails to load (`ERR_MODULE_NOT_FOUND:
…/workspace/issues.ts`). The scratch spec's five checks against the S14 head (`ee8de20`'s frontend
exported with `git archive`, served by Vite :5186 on the same bench) fail: (1) the SUP · P4 cell
has no `aria-invalid` (the chip already counted "1 error"); (2) the chip's popover has no issue
button to find the AGE_BANDS message in; (3) the 2+2 card has no `data-issue`; (4) there is no
`period:P2` header anchor. The i18n check fails on injected keys (`rates.ws.issue.nav_hint_typo`,
`core.nope.missing`, `zzz.unknown`: "3 i18n problem(s)", exit 1) and passes on the tree.

**Verification (S15).**
- Frontend: `tsc -b`, `npm run build` (bundles not committed), `npm run i18n:tex` (7 new keys; 5,038
  literal keys found), `test:unit` 287/287, `test:dom` 30/30 (TEX_DOM_PORT 5186). Python unit 491 OK
  and ruff clean (no server change).
- Integration, migrated with this tree: `test_pricing_workspace_api` 50 OK.
- Browser, on the tree's own servers (bench :8016, Vite :5186), a scratch spec 5/5
  (`scratchpad/s15/e2e/s15-issues.spec.ts`):
  1. A draft with two SUP P4 rows: the chip reads "1 error"; the Family Suite · P4 cell has
     `aria-invalid`, `data-issue="error"` and the description "Error: room … has two rules for period
     P4"; P3 is clean. The popover's "Pricing: 1 issue" lists ROOM_RULE_DUPLICATE; its click closes
     the popover and focuses the cell. Commercial rules → Rule tables → Boards → "Duplicate row 3":
     the chip reads "2 errors", the Boards table lists BOARD_DUPLICATE, and its click in the popover
     opens Pricing (`#pricing`) and focuses "Half board · Family Suite only · P2" (`aria-invalid`).
     Delete on the SUP P4 cell removes both rows: "1 error", the cell is clean.
  2. Bands CHA "Small kids" 3–6.99 and CHB (no label) 6–11.99: the popover reads "age bands Small
     kids and Child 6–11.99 overlap at …" and no INF, CHA or CHB; a click opens the child ages drawer.
     The Advanced Child ages table and Preview & audit read the labels too.
  3. Without an infant rule: the 2+2 card has `data-issue="warning"` and "[Infant 0–2.99]"; the
     popover has no "[INF]"; "… STD 2A+1C [Infant 0–2.99]" switches the ladder to Standard and
     focuses "Infant 0–2.99 · P1" (a warning: described, not invalid); the All rooms scope's Infant
     row is not marked; from a collapsed section, the 2A+2C issue opens it and focuses the card.
  4. P2 and P3 overlapping and twin 3rd-adult rules: both headers `aria-invalid` (P1 clean) with
     "Error: periods P2 and P3 overlap with equal priority"; "3rd adult · All periods" invalid ("…
     share the same scope …"); the popover focuses the P2 header, then the ladder cell.
  5. A published version with OCC_INFANT_GENERIC in its stored report: "Checked when published"
     reads a warning, "Every child (any age band) · All periods" is marked by the saved rule's name
     and described with "Warning: no rule names infant band Infant 0–2.99 …", the popover focuses it,
     and no `validate_version` request is made.
  Screenshots (desktop and 390 px, the popover as a sheet, no sideways page scroll) are in the
  scratch directory.
- Committed specs `contract-admin`, `critical-journey`, `editor-edits`, `entry-branding`
  (`TEX_E2E_BENCH=http://test.localhost:8016`) and `policy-revisions`: 15 passed, 1 skipped (the
  two-factor case, as before). Earlier scratch specs on this tree: S14 5/5, S13 6/6, S12 5/5 +
  review 2/2, S11 rerun 4/4, S10 bulk (scoped) 6/6, S9 with the cell menu 8/8.

**Performance after S15.** `anchorIssues` over 3,380 rows (1,800 occupancy rules, half in
combinations) with 200 issues: 26 ms the first call, 14 ms after (Node), mostly `groupCombinations`,
which runs only when an issue names a combination row or a party; it runs again when the issues or
the tables change, and not at all without issues. A cell looks its issues up in a map; the grids'
cell views are recomputed when the issues change, as when the tables do.

**O1–O5 after S15** (all five provisional, owner input 13): unchanged.

**Open after S15.**
- *S16 must commit the S15 scratch scenarios 1–5* with those of S10–S14. Useful names: the chip
  (button whose name starts "Live check" or "Checked when published") and its dialog of the same
  name; regions "{Section}: N issue(s)"; buttons named by code and message; `data-issue` on cells,
  cards and headers (`error` / `warning`), `aria-invalid` for errors; period headers
  `data-cellid="period:{code}"`; ladder cells `occ:{row}|{period}` (All rooms) and
  `occ:{row}|{period}@{room}`.
- Messages keep the server's other identifiers: room type ids ("Aurora Beach Resort-FAM") and rule
  ids (`~r…` in the overlay, saved row names); only band codes are shown as labels (D13).
- A room alone (ROOM_CAPACITY, INCLUDED_ADULTS) has no anchor; its click goes to the matrix. An
  AGE_BANDS issue about two bands goes to the drawer, whose bands are not marked.
- Still open from S10–S14: their low review items; `#occupancy` / `#boards` followed a second time
  still do not reopen a collapsed section (an issue's click always opens it).

**Decision (implemented in S16: the committed acceptance specs, the E2E helpers on the workspace,
the scenario specs of S9–S15, the bundles).** Branch `pricing-workspace`, tests, documentation and
the rebuilt bundles only (no source file of the app or the server changes): commits `22a0fe7` (the
flows and the budget), `f3aa4bf` (the acceptance and mobile specs), `5aaa8be` (the S9–S15 specs),
the documentation, and the bundles in a separate "build:" commit.
- *`e2e/flows/contracts.ts` drives the workspace.* Every exported name and signature is kept; each
  version-editor step takes an optional third argument `StepOptions` `{advanced?, budget?, save?}`.
  By default a step uses the Pricing workspace and saves the draft when it is done, as the ten-tab
  steps did:
  - `addRooms` chooses each room in the matrix's "Add room" select (the first room of an empty
    version is the base room; `base: true` on another room uses Set as base);
  - `addPeriod` clicks "+ Period" and types the dates in the new column's header (a first period
    asks for both dates, a later one follows the last period and asks for its end); a start that
    does not follow the last period (read from the end field's `min`) is set with Dates…, and a code
    other than the proposed `P{n}`, or a name, with Rename…;
  - `setBaseRate` clicks the matrix cell "{room} · {period | All periods}: …", types the amount
    (the "Price: {room} · {period}" editor opens), presses Enter and, after the save, expects
    `displayAmount(amount)` in the cell;
  - `addOccupancyRules` creates the bands in the child ages drawer (Up to + Enter per band, a label
    typed in, the infant switch set, a code other than the proposed one renamed under "Advanced:
    show band codes") and types `n%` (PERCENT_OF) into the ladder's All periods cells of the 3rd
    adult ("Extra adult (3rd)" under ROOM) and of each band;
  - `addBoard` uses the Boards section: "Add board" (the base board first on a version without
    boards), `+amount` typed into the board's All periods cell (per adult; a bare number is per room,
    O1), and the row's terms popover when the children's share or infants differ from the new-row
    defaults (50 %, free);
  - `previewPrice` uses the context header's Price test drawer (any section, no section switch), still
    reads role=status "Total" and the one list containing "Rule applied:", and closes the drawer;
  - `expectPublishedReadOnly` asserts "Published", "Read-only" and the notice "Published versions are
    immutable", no Save or Publish, the matrix "Room prices by period" with `aria-readonly`, typing
    into a cell opens no editor (no textbox), no "Edit price:" trigger, no "Add room" and no pricing
    basis popover trigger;
  - the new `setBasis(page, "PERSON" | "ROOM", budget?)` drives the basis popover (chip → basis →
    Apply, saved at once as the header; a no-op when the contract already has that basis);
  - `{advanced: true}` keeps the Rule tables path of every step (and Preview & audit for
    `previewPrice`); `openTab`, `openSection`, `addRow` and `cell` are unchanged; `addRatePlan` stays
    a Rule tables step (rate plans are not in the workspace); locators `priceMatrix`, `priceCell`,
    `occupancyLadder`, `ladderCell` and `boardsGrid` are exported for the specs.
- *`e2e/flows/budget.ts` (new): the interaction budget, counted in the page.* A capture listener
  counts every trusted primary `pointerdown` (so a click made outside the wrappers is counted too); a
  MutationObserver counts every change of the selected tab of "Version sections" and every modal
  dialog that appears (`[aria-modal="true"]`, `role="alertdialog"`, `dialog:modal`); browser dialogs
  count as modal. Playwright gestures without a pointer event are counted by the wrappers the flows
  use: a native `<select>` choice is two clicks (open, pick) and a field filled without the focus is
  one. Keyboard keys are never clicks. `Budget.attach(page)`, `start()`, `stop()`, `counts()`,
  `log()` and `expectWithin(testInfo, limits)` (annotations and an attachment with the log);
  `choose` / `typeIn` take an optional budget.
- *`e2e/pricing-workspace.spec.ts` (new), desktop.* The contract is made through the API with
  `pricing_basis: "ROOM"`; its draft is opened by URL and the budget starts. The 13 steps of §5.3 run
  as `test.step`s with the assertions of §5.3 (the resolved rows 80.50 / 92.00 / 115.00 / 156.00 and
  94.50 / 108.00 / 140.00 / 182.00, the OVERRIDE markers, "×1.00 default", band labels and no
  visible `\b(INF|CHA|CHB)\b`, the combination card's two lines, the base board BB). Step 12 opens
  the Price test with "Test this price" on Deluxe's resolved P2 cell (prefilled: Deluxe, 1–4 May,
  BB, 2 adults), adds a child of 8, captures the `preview_price` answer, and asserts the ladder
  "Nights 1–3 · P2" (the only table of nights): Base 80.00; Period "no amount (period used to choose
  rules)" naming P2; Room 80.00 → 108.00; Occupancy (adults) 108.00 → 216.00; Children 216.00 →
  270.00 with the CHILD_SLOT line 54.00; Board 270.00 → 270.00 "included"; Night cost 270.00; no
  Special combination, Period adjustment or Rate plan row; and that the displayed Room / Occupancy /
  Children / Board / Night cost values equal the answer's `nights[0]` `unit`, `subtotal_adults`,
  `subtotal_children`, `occupancy`, `subtotal_board` and `cost` (GAP-12) cut to two decimals, with
  no `save_version` request. Step 13 checks the order caption, "Whole stay", "Rule applied:" and
  "Child 7–11.99" (no code). Then Save, and `get_version` must hold exactly "1.15", "1.2", "1.35",
  "1.4" (P3 and P4), "0.7", "0.8", the combination "2+2" at positions 1 (CHB "0.5") and 2 (CHA
  "0.25"), the band rules "0" / "0.25" / "0.5", the bands 2.99 / 6.99 / 11.99 with non-empty labels
  and BB as the base board. A second test runs the edge checks on an API-made draft of the example:
  `abc` (error draft, the parser's message), Escape reverting a typed price, `1.500` (AMBIGUOUS),
  Ctrl+Z after the P3:P4 bulk entry (×1.35 back), a 2×2 TSV block with Windows line breaks, `+10%`
  on the base P1 (one `apply_op_values`, 77.00 stored as a price) and `x1.20` over Superior's `=245`
  (a formula again, 120.00). A third test checks the budget itself: the Publish dialog, a cell click,
  a native select and two section switches count exactly `{clicks: 6, sectionSwitches: 2, modals: 1}`,
  so the acceptance's zeros cannot come from a counter that does not count.
- *`e2e/pricing-workspace-mobile.spec.ts` (new), desktop and Pixel 7* (the `mobile` project picks
  it up by name). A version published through the API: `expectPublishedReadOnly`, the ladder
  `aria-readonly` without a textbox or "Add combination", the resolved prices of the frozen version,
  no sideways page scroll at the device's width and at 375 px, and no `validate_version` request and
  no 403 answer. An agent (price.view only) on the same version: "Amounts are not shown to your
  role.", the three rooms, no amount (`\d+[.,]\d\d`) in the page's main area, no resolved cell, no
  Price test or basis chip, no page error, no sideways scroll, no request to `price_matrix`,
  `validate_version` or `preview_price`, and no 403.
- *`editor-edits.spec.ts`:* the Discard test adds the base board BB in the Boards section, Discards,
  and expects Save disabled and no board row; the in-flight-save test adds a period column ("+
  Period", its dates) while `save_version` is held: the column survives and stays unsaved, Save stays
  enabled, `get_version` has no period, and the next save sends P1. *`entry-branding.spec.ts`:* a
  Rate plans list row opens its version with "Commercial rules" selected in "Version sections" and
  "Rate plans" selected in "Rule tables".
- *The S9–S15 scenarios as committed specs* (the S10–S15 notes): `pricing-workspace-matrix` (S9,
  8 tests; the published check publishes its own version instead of the demo CTR-00019),
  `pricing-workspace-bulk` (S10 1–6, its review R1–R3 and second review V1–V5; the column-header
  locators scoped to the matrix), `pricing-workspace-occupancy` (S11 1–10 as 4 tests, "included in
  the room price"), `pricing-workspace-combinations` (S12 1–5 and its review R1–R2),
  `pricing-workspace-boards` (S13 1–6), `pricing-workspace-price-test` (S14 1–5 and the 375 px
  drawer check, without screenshots; S9's Shift+F10 step meets the cell menu first) and
  `pricing-workspace-issues` (S15 1–5). They share `e2e/flows/workspace.ts` (new): the demo hotel's
  rooms, the owner's example rows, API-made contracts and drafts, publish, `watchContracts`,
  `archiveAll` (each spec archives the contracts it made) and `twoDecimals`. No spec writes files.
- *Bundles:* `npm run build`; `kamra/public/frontend` rebuilt and committed on its own ("build:"
  commit), `kamra/public/tex/tex-widget.js` rebuilt unchanged.

**Deviations from the slice text, with reasons (S16).**
1. *Files beyond the slice list:* `e2e/flows/workspace.ts` and the seven scenario specs above, which
   the S10–S15 reports asked S16 to commit (with S9's). ARCHITECTURE_DECISIONS.md and
   GO_LIVE_READINESS.md record the slice.
2. *The rooms:* the design's Standard / Superior / Deluxe are the demo hotel's Standard Sea View
   (base) / Family Suite / Garden Villa, so the specs run on the shared demo data.
3. *Step 1's "base row 'Base person price'"* is asserted with step 2: a version without rooms has
   no base row. Step 1 asserts the matrix's unit "Base person rate per night · EUR" instead, besides
   the chip, `get_contract` PERSON, Save disabled and no modal.
4. *Step 12's "Child" row* is labelled "Children" on screen (S14); the assertion accepts either.
5. *The helpers keep saving after each step* (as the ten-tab steps did, so `contract-admin` and
   `critical-journey` run unchanged); `{save: false}` leaves the draft unsaved (the acceptance spec
   saves once, after step 13). `addRooms` with `base: false` on the workspace's first room throws
   (the workspace makes the first room the base room): use `{advanced: true}`.
6. *`setBaseRate` "focuses the gridcell 'Price: …'":* the gridcell is named "{room} · {period}: …";
   "Price: {room} · {period}" is the editor the typing opens. The helper clicks the cell, types,
   checks that editor and presses Enter.
7. *The budget counts clicks in the page* rather than only in the wrappers (trusted pointer presses,
   plus the wrapped selects and fills), so a helper cannot click uncounted.
8. *Bundles are committed* as the slice asks (CI runs Playwright against them), in their own
   "build:" commit on top, although the lane's general rule is that the bundles are rebuilt on
   merge; the commit can be dropped and rebuilt without touching the rest.
9. *The acceptance ran against the tree's Vite dev server* (bench :8016 with the tree's code, Vite
   :5186), not the bench's :8000: the dev bench serves `/assets/kamra` from the main checkout, so the
   committed bundles of this branch can only be exercised there after the merge.

**Tests (S16).** Browser only (no unit, integration or source change):
- new: `pricing-workspace` 3 (the 13 steps with the budget, the edge checks, the budget's own
  check), `pricing-workspace-mobile` 2 × 2 projects, and the scenario specs `-matrix` 8, `-bulk` 14,
  `-occupancy` 4, `-combinations` 7, `-boards` 6, `-price-test` 6, `-issues` 5;
- changed: `editor-edits` (the two contract tests), `entry-branding` (`#plans`), and every contract
  step of `contract-admin` and `critical-journey` through the rewritten flows.
Fail-first:
- against main `1575c8b` (the ten-tab editor, bench :8000, its bundles), `pricing-workspace`,
  `pricing-workspace-mobile` and the two changed `editor-edits` tests fail, 9 of 9: the matrix
  "Room prices by period" (a grid) is not found (5), the section tab "Pricing" is not found (2), and
  the agent's "Amounts are not shown to your role." is not found (2);
- S15's scenario 5 (a published version's stored report anchored by the saved rule's name), which
  had no fail-first run in S15, fails against the S14 head's frontend (`ee8de20`, exported with `git
  archive` and served by Vite :5186 on the same bench): "Every child (any age band) · All periods" has
  no `data-issue` (expected "warning");
- the budget's own check passes only when the counter counts: `{clicks: 6, sectionSwitches: 2,
  modals: 1}` exactly.

**Verification (S16).**
- Frontend: `tsc -b`, `npm run build`, `npm run i18n:tex` (5,038 literal keys), `npm run test:unit`
  287/287, `npm run test:dom` 30/30 (TEX_DOM_PORT 5186). The e2e folder type-checks with a scratch tsconfig
  (`noUnusedLocals`; the committed `tsconfig` covers `src` only). Python unit 491 OK, ruff clean (no
  Python change).
- Integration, migrated with this tree (`migrate_test.sh`): `test_pricing_workspace_api` 50, `test_critical_journey` 31,
  `test_money_fields` 9, `test_age_bands` 11, `test_audit_trail` 15, `test_security_regressions` 59,
  `test_commercial_flows` 63, `test_concurrency` 8, `test_pricing_policies` 14 and
  `test_snapshot_integrity` 13: 273 OK.
- Upstream suites with this tree: eval harness 76/76, front-desk journey 13/13, banquet 101 OK.
- Browser, on the tree's own servers (bench :8016 with the tree's code, Vite :5186), the whole
  Playwright suite (113 tests, desktop and Pixel 7): against Vite 105 passed and 1 skipped (the
  two-factor sign-in, without a second factor configured, as before); the 7 failures were the specs
  written for the bench (custom-host 3, pay-link 2: the booking engine served by the bench; manage-money
  2: a job applies the change), which then passed against the bench :8016 with an RQ worker of the
  tree (custom-host, pay-link and manage-money: 8 passed; the committed bundles restored, since the
  bench serves `/assets` from the main checkout). The acceptance test measured 41 clicks, 0 section
  switches and 0 modal dialogs in each of its four runs.

**Performance (S16).** No app change. The acceptance test takes about 20–25 s, the nine workspace spec
files (57 tests with the mobile project) about 5 min of the suite's 16.

**O1–O5 after S16** (all five provisional, owner input 13): unchanged, and now covered by committed
browser checks: O1 (board `100` read "per room per night", `pricing-workspace-boards` 2), O2 (`-20`
stored as ADD −20 and priced "board HB supplement -40.00" for 2 adults, boards 1), O3 (`-5%` stored
as ADJUST_PERCENT, boards 1), O4 (`+10%` on the base P1 adjusted once by `apply_op_values` to 77.00,
`pricing-workspace` edge checks and `-matrix` 3) and O5 (`1.500` refused in a EUR price cell,
`pricing-workspace` edge checks, `-matrix` 2 and `-bulk` 2 and 3).

**Open after S16.**
- The committed bundles of this branch run on the dev bench (:8000) only after the merge (it serves
  `/assets/kamra` from the main checkout); the acceptance and the workspace specs should run once
  against the bench then (`TEX_E2E_BASE=http://test.localhost:8000`).
- The in-app keyboard help still says "Shift+F10" opens the rule editor; with `can_preview` it opens
  the cell menu first (S14 review item).
- Still open from S10–S15: their low review items (none changed by S16); `#occupancy` / `#boards`
  followed a second time do not reopen a collapsed section.
- Only Chromium was run (the container has no WebKit or Firefox).
- CI had not run on GitHub yet (then an owner item; resolved 2026-09-26: PR #2 and PR #1 green).

**S16 review follow-up (2026-09-25).** The review of the finished workspace reported one high, seven
medium and fifteen low findings. All are fixed except three low ones, which are recorded as open
below (the §3.18 fit target, the full extraction of the grids' inline editing, and the optional
publish error for a zeroing rate plan). Branch `pricing-workspace`; main `1575c8b` has no newer
commit, so no merge was needed.

**Decision (S16 review follow-up).**
1. *Inherited policy formulas are cost (medium).* The policies API shows a TEX Pricing Policy only
   with `price.view_cost` (READ_CAP, G-11). `price_matrix` now follows the same rule. A viewer
   without `price.view_cost` (an editor with `contract.edit` only) still gets each inherited
   occupancy rule's `rule_id`, `source`, target and scope, but `op` and `value` are null and
   `hidden` is true. A sample party whose total uses such a rule gets no total, slots or error for
   that period; the period is listed in the cell's new `hidden` list. Both fields are additive
   (`hidden: false` / `[]` for everyone else). The ladder shows such a cell as "Policy rule · from
   <scope>", with a tooltip that says the formula is shown only to users who may see cost, and the
   resolved line shows "—" for a hidden total.
2. *GAP-8 covers every value an op needs (low).* `_VALUE_REQUIRED` also refuses a blank
   `periods.adjustment_value` when an adjustment op is set, and a blank `rate_plans.value` when an
   op is set, in `save_version` and in the overlay. Frappe stored both as 0, and the draft then
   priced every night, or every stay of that rate plan, at 0.00. A value of 0 typed by the user
   stays a value.
3. *Another hotel's rate plan or terms (low).* `build_terms`, which a save, the overlay, the price
   test and publish all run, refuses a `rate_plans` row whose Rate Plan, explicit
   `cancellation_policy` or explicit `payment_policy` belongs to another hotel ("… belongs to another
   hotel"), as it already did for room types. A policy with no hotel is shared and stays allowed.
   The overlay answers `build_error`, the live check reports BUILD, and the price test returns
   unsellable with no rate plan block, so no other hotel's terms are read back.
4. *Heavy reads are bounded per user (low; closes the open "server-side concurrency guard").*
   `validate_version` (with or without `data`) and `price_matrix` with `data` or `parties` run under
   `_heavy`. Each user has a budget per minute and a cap on calls running at once:
   `HEAVY_LIMITS = {"validate": (60, 3), "matrix": (120, 6)}`. The counts are kept in redis, a
   crashed call's slot is freed after 300 s, and a refusal is `RateLimitExceededError` (429). Only
   web requests are counted; a job, the console or a test calling the function is not. The client
   already keeps one validation in flight and debounces the matrix (300 ms), so an editor stays far
   below the budget. A scripted client, or aborted fetches whose workers keep running, can no longer
   hold more than three 10–16 s validations at once.
5. *The three grids scroll sideways together (medium).* A `ScrollSyncGroup` (`ui/scroll-sync.ts`)
   around the Pricing section keeps the `scrollLeft` of the matrix, the ladder and the boards grid
   in step. Scrolling any one of them, including the scroll the browser makes to show a focused
   cell, scrolls the other two, and a grid mounted later starts at the group's position. So P1…Pn
   stay lined up, and the boards grid's highlight of the matrix's active period (§3.12) is on screen
   whenever the matrix cell is. One shared scroll box was not used, because section headers,
   notices and the combination cards sit between the grids, and each grid keeps its own vertical
   scroll and sticky header.
6. *The header's Base room and Base occupancy (medium).* §3.2 is now built:
   - *Base room* is a popover with a select of the contract's rooms, the "Re-point formulas that use
     X to Y" checkbox (on by default) and "Set as base". It calls the same `setBaseRoom` as the row
     menu, through the workspace history.
   - With the ROOM basis, *Base occupancy* is a popover stepper for the base room's
     `included_adults`. It starts from the room's own value, else from the effective value the
     server priced with. Typing 0 goes back to the room type's default. The hint names the value
     the prices on screen include.
   - Both are read-only text on a frozen version or for a viewer who cannot edit.
7. *Dark theme contrast (high).* Every text and background shade the workspace uses is one that
   index.css or tex.css remaps for `.dark`:
   - override and fixed cells, and the Fill and Boards confirmation bars: amber-900 on amber-50;
   - formula-default cells: zinc-700;
   - the row header's derivation: zinc-600;
   - the no-host warning and the fixed-price pin: amber-800;
   - the undo toast's Undo: tex-300 (hover tex-200);
   - the issue underline: amber-600;
   - the overlap stripe: amber-600/40;
   - the ladder note's hover: sky-900.
   The cell tones moved to `workspace/cellTone.ts`. `tests/unit/contrast.test.ts` reads the palette
   the app builds with (Tailwind's theme.css in oklch, the app's `@theme` and `.dark` blocks), checks
   each tone and the other state texts at 4.5:1 in both themes and the selection outline at 3:1, and
   fails on any unmapped text or background shade in the workspace.
8. *A selection is not colour alone (medium), and read-only ranges are shown (low).* A selected
   cell of a range has an inset 2 px tex-400 outline besides the sky-50 tint. The outline is also
   drawn in forced-colors, which drops backgrounds. `useGridSelection.isSelected` (aria-selected and
   the cue) now covers every cell of the ranges. `selected` (what fill, paste, clear and Adjust…
   change) stays the editable cells. All three grids are `aria-multiselectable`, because Ctrl/Cmd+C
   copies a range on a read-only version too.
9. *Ctrl/Cmd+S saves what is typed (medium).* A cell editor routes Ctrl/Cmd+S (any layout) to
   "commit and stay on the cell". The version editor's save then sends the tables that commit wrote
   (`history.current()`, updated at once, before React renders). A refused entry keeps its editor
   and refusal, and the save goes on without it. The tab asks before closing when the draft is
   dirty, and also when a cell editor holds a changed entry, a grid holds an error draft, or a
   combination builder is open. One case is not covered: a relative entry on the base room waits
   for `apply_op_values`, so it is not part of a save made while it is pending. It is committed when
   the answer comes, and the draft is then unsaved again.
10. *Input survives a section switch (low).* The three grids' error drafts (the ladder's per rooms
    scope) and the open combination builder, with its draft and "More", now live in a store the
    version editor owns: `keptState.ts` holds the keys and the check, and `useKeptState.ts` the
    context and the hook. There is one store per loaded version, so Discard and loading another
    version start empty. A grid or builder mounted again takes its state back, and a builder that is
    shown again does not take the focus.
11. *Focus after Remove room / Delete period (medium).* The matrix moves the focus to the nearest
    cell that is left: the same column in the next room (else the previous one), or the same row in
    the next period (else the previous one). With no cell left it goes to "Add room" or "+ Period".
    Ctrl/Cmd+Z then works where the user was.
12. *The Price test panel (medium).*
    - Below `sm`, `Drawer modal={false}` renders the modal drawer: it covers the page there, so the
      page under it is taken out of reach (aria-modal, focus trap).
    - On larger screens the side panel stays non-modal and is in the Tab order right after its
      opener: Shift+Tab from its first control goes to the opener, and Tab from its last control
      goes to what follows the opener.
13. *Settings are in the undo history (low).* `useWorkspaceHistory` also records the version's
    settings and its selling terms as two more recorded "tables", merged per field while the user
    types, as the Advanced rule tables are. Child ordering, the ROOM extra unit and children fill,
    the Advanced settings fields and the header's selling popover are undone in order with every
    other edit. The pricing basis, a contract header field, stays outside the log (§3.10). The child
    ages drawer's note now says that Undo puts these settings back.
14. *The rest (low):*
    - The five ladder strings with `{count}` are plural objects in all six languages, and the TEX
      i18n check fails on a workspace string with a `{count}` that is not one.
    - English Explain sentences name rooms instead of room type ids (`withRoomNames`; the server
      text is otherwise unchanged).
    - Duplicate leaves the copy unnamed and opens Rename… on it, with the focus in the name.
    - A weekday-limited period has a real dotted top border (`[border-top-style:dotted]!`; the
      bundle has the rule).
    - The ladder's and the boards grid's `aria-colcount` is `cols + 1`.
    - The ladder's before amounts are zinc-500.
    - The Pricing section sits on the page surface without the Card; each grid is in its own white
      hairline box (§3.18: no card-in-card). The other sections keep their card.
    - The three grids route their cell-editor keys through one pure, unit-tested `editorKeyAction`.

**Deviations from the findings' fixes, with reasons.**
- *Rate limit:* a budget and a running-call cap per user, as the finding suggests. Two things differ:
  - `frappe.rate_limiter.rate_limit` is not used, because it is per IP and endpoint and cannot tell
    a plain matrix read from one with data;
  - the saved-draft validation is bounded too, because it is as slow as the overlay's.
- *No publish error for a rate plan or period adjustment that zeroes the price* (MULTIPLY /
  PERCENT_OF 0; the finding marks it optional). The blank value, which was the reported fault, is
  refused. An explicit 0 is a value the user typed, and refusing it would change what publish
  accepts.
- *`useInlineGridEditor` is not extracted.* Only the key routing is shared (`editorKeyAction`, the
  part the Ctrl+S fix touched). The editing state, drafts, commit on blur, refocus and undo keys stay
  in each grid (open below). A full extraction rewrites three 900–1,300 line components, which is
  too much for a review follow-up.
- *§3.18's fit target (the owner example and the ladder on one 1440×900 screen) is not met* (open
  below). Removing the card saves its padding and border, but the rows stay taller than 28 px
  because of the two-line row headers.
- *No F6 shortcut* between the Price test panel and the grid (the finding says "consider").

**Tests (S16 review follow-up).** Fail-first output is kept in the report.
- *Integration, `test_pricing_workspace_api`, 55 (50 + 5):*
  - an editor without cost gets the inherited rules without op or value, and the parties that use
    them without a total (saved, unsaved and published); the policies API refuses the same user;
  - a blank night adjustment and a blank rate plan value are refused on save and in the three
    overlay calls, while no op and an explicit 0 pass;
  - another hotel's rate plan, cancellation policy or payment policy is refused by the matrix, the
    live check, the price test and publish, while a shared policy passes;
  - the heavy-read budget per user and kind;
  - the running-call cap, with its slot freed after a failure.
  Fail-first: 2 failures and 8 errors on the unfixed code (the missing `hidden` key, `_in_request`
  and `HEAVY_LIMITS`, `build_error`, and "ValidationError not raised" for the blank adjustment and
  for publish).
- *Unit, `npm run test:unit` 296 (287 + 9):*
  - `contrast.test.ts` 4 (palette, tones, other states, the unmapped-shade scan: 13 hits on the
    S16 tree);
  - `keys.test.ts` +2 (the save shortcut and the editor key routing);
  - `kept-state.test.ts` 1;
  - `workspace-occupancy.test.ts` +1 (a hidden policy rule ranks without a value; fails on the S16
    `occupancy.ts`);
  - `explain-ladder.test.ts` +1 (room names in English sentences);
  - `workspace-model.test.ts`: duplicatePeriod leaves the copy unnamed.
- *i18n check:* on the S16 catalogue it fails with the five plain `{count}` strings.
- *DOM, `npm run test:dom` 31 (30 + 1):*
  - `history`: a setting is undone in order with a table entry;
  - `keyboard`: a read-only cell in a range is aria-selected.
- *E2E, `pricing-workspace-review.spec.ts`, 10 tests:* 10 periods scroll together at 1440×900 with
  P8 aligned and on screen; Ctrl+S in an open editor (the save body, the stored 120, the focus); an
  error draft across a section switch and the beforeunload prompt; the focus after Remove room and
  Delete period, and Ctrl+Z; the header's Base room and the ROOM stepper (3 adults sent); the Price
  test's Shift+Tab and Tab, and aria-modal at 375 px; a read-only range's outline and aria-selected;
  Duplicate's unnamed copy with Rename…, and the dotted border; dark-theme contrast of override,
  fixed and formula cells; the child ordering undone with Ctrl+Z. Fail-first: all 10 fail on the
  S16 frontend (`ae5e7db`, served by Vite :5187 on the same bench).

**Verification (S16 review follow-up).**
- *Python:* unit 491 OK, ruff clean.
- *Frontend:* `tsc -b`, `npm run build` (the bundle has the dotted-border and outline-solid
  rules; the bundles were not committed), `npm run i18n:tex` (5,060 literal keys), `npm run
  test:unit` 296/296, `npm run test:dom` 31/31 (TEX_DOM_PORT 5187).
- *Integration:* all 38 modules migrated with this tree (`migrate_test.sh`), 838 OK (10 skipped, as
  before). `test_pricing_workspace_api` 55, `test_critical_journey` 31, `test_commercial_flows` 63,
  `test_security_regressions` 59, `test_pricing_policies` 14, `test_patches` 33 (3 skipped).
- *Upstream suites with this tree:* eval harness 76/76, front-desk journey 13/13, banquet 101 OK.
- *Browser, on the tree's own servers (bench :8016 with this tree, Vite :5186):*
  - the nine workspace specs, `editor-edits`, `contract-admin` and `critical-journey`, desktop and
    Pixel 7: 72 tests, 71 passed;
  - the failing one was `pricing-workspace-bulk` V1, whose assertion "aria-selected marks the
    editable cells only" was the behaviour the review asked to change. It now expects the four cells
    of the range, the resolved one aria-selected too; `-bulk` then passed 14/14;
  - `pricing-workspace-review` passed 10/10 twice.
- *Measured at 1440×900 after the change* (above): matrix at y=332 to 605, ladder at 802 to 1,219.
- Main `1575c8b` had no newer commit: nothing to merge.

**Measured for §3.18 after the follow-up** (the owner example, 1440×900, scrollY 0, Occupancy
open): the matrix grid runs from y=332 to 605, the ladder from 802 to 1,219, and the page is
1,676 px high. The matrix rows are 74/48/48/28/48/28 px and the ladder rows 41–58 px.

**O1–O5 after the S16 review follow-up** (all five provisional, owner input 13): unchanged. No
parser, op mapping or `apply_op_values` change.

**Open after the S16 review follow-up.**
- §3.18's fit target is not met (measured above). It needs a design change for the rows (28 px data
  rows, single-line row headers or a sub-line shown only on hover), not a spacing fix.
- The grids' inline editing is still written three times (PriceMatrix, OccupancyLadder,
  BoardsSection). Only its key routing is shared (`editorKeyAction`). A `useInlineGridEditor` hook is
  open.
- A relative entry on the base room that is waiting for `apply_op_values` is not in a Ctrl/Cmd+S
  made meanwhile. It is committed when the answer comes, and the draft is then unsaved again.
- An error draft kept for a room or period that was then removed stays in the store until Discard
  or reload, so the tab may still ask before it closes.
- `HEAVY_LIMITS` are constants, not site settings.
- There is no F6 shortcut between the Price test panel and the grid, and no publish error for an
  explicit rate plan or period adjustment of MULTIPLY 0.
- The E2E dark-theme check reads `rgb()` colours only. Every remapped shade is hex, so an
  unremapped (oklch) colour reads as a failure there, which is what the check wants.
- Still open from S16: the committed bundles run on the dev bench only after the merge; the
  keyboard help's Shift+F10 wording; the S10–S15 low items; only Chromium was run; CI had not run
  on GitHub yet (resolved 2026-09-26).

**S16 re-review follow-up (2026-09-25).** A second review of the finished workspace reported nine
medium and twelve low findings. All nine medium ones are fixed. Of the low ones, eleven are fixed
and one is recorded as open (the shared inline-editing hook). Branch `pricing-workspace`; main
`1575c8b` has no newer commit, so no merge was needed.

**Decision (S16 re-review follow-up).**
1. *No formula of a hidden policy rule can be worked back from a sample party (medium).* S16 hid a
   party's total only when a slot's winning rule was hidden. Two leaks were left:
   - a whole-party (COMBINATION) rule of a policy is not a slot rule, so a total it priced still
     showed next to its slots (180 beside 100 + 100);
   - a party that could not be priced reported its error (for example "occupancy rules produce a
     negative price") before the hidden check ran. With an overlay probe "2A+1C SUBTRACT X" per
     period, one `price_matrix` call bisected the policy's value.

   `matrix.party_rules` (pure; `occupancy.rules_taking_part`) returns every rule that takes part in
   pricing the party: each slot's winner and the whole-combination rule, also when the party fails.
   For a failure these are the rules resolved before it (all of them for a negative total) and the
   rules an ambiguity names. A party fails before its occupancy is priced (no room, an unknown band,
   over capacity, no unit)? Then no rule takes part. `_party_cells` now decides "hidden" first,
   before it reports a total or an error. A hidden period has no total, slots or error text.
2. *The live check no longer answers such a probe either (low).* `validate_terms(hidden=…)`, which
   `validate_version` passes for a viewer without `price.view_cost` (saved or unsaved draft):
   - reports no sweep warning for a party a hidden rule takes part in (NEGATIVE_OCCUPANCY_PRICE was
     a threshold oracle: about 20 calls found a total);
   - reports no OCC_POLICY_OVERRIDE_OUTRANKED for a hidden override (it showed only while the
     version's rule differed from the override's op and value: an equality oracle).
   AMBIGUOUS_OCCUPANCY_RULES stays an error. It names rule ids, not values, and in the cascade
   precedence a version rule never ties a policy rule. The report stored at publish is unchanged.
3. *The heavy-read budget is atomic, and a leaked slot ages out (low).* SET NX EX and then INCR as
   two steps left a counter without a TTL when the window ran out between them. That user was then
   refused for good. Now:
   - the budget is one Lua step: INCR, then EXPIRE when the key has no TTL. A counter left without
     a TTL heals on its next use;
   - running calls are their start times in a sorted set (`…:slots:…`, a new key name). Entries
     older than 300 s are dropped before counting, so a killed worker's slot ages out 300 s after
     its call started, however often the user retries. Before, every call pushed the TTL back.
4. *`preview_price` with data is bounded (low).* It builds the same overlay as the matrix, so it
   runs under `_heavy("preview")`, with its own budget: `HEAVY_LIMITS["preview"] = (120, 6)`.
   Without data it is not counted.
5. *The explanation after a second result (medium).* "Why this price" and the Explain ladder keep a
   picked night only while the result has it. Otherwise they show All nights. "Why this price"
   starts on All nights, as the ladder does.
6. *Child position rows and "also when children travel" come from the ladder popover (medium;
   §3.6.2).*
   - A band row's popover has "Child position": every child in the band (the row itself), or
     Child 1…n, where n is the most children a room in scope holds. A position writes
     `{CHILD, position n, age_band}` rules, a row of their own, and the band's rule stays.
   - Under the PERSON basis, the single-use row has "Also when children travel". It switches the
     cells written between COMBINATION 1+0 and ADULT 1 in 1+*, removing the other form's rows of
     those cells in the same history entry (`occupancy.applyOccRuleAs`).
   - It is not offered under ROOM: adult 1 is then included in the room price and takes no rule.
7. *Every run-time state key exists (medium).* `workspace/stateKeys.ts` lists each grid's cell
   states and the entry error codes. The three grids type their views' `state` from these lists,
   and a type check makes the error list complete. `tests/unit/state-keys.test.ts` checks every
   `rates.ws.state.*`, `rates.occ.state.*`, `rates.brd.state.*` and `rates.sh.err.*` key in the six
   catalogues. `rates.occ.state.cost_hidden` ("total not shown") was missing.
8. *Add room and Add board are menus (medium).* The matrix's Add room, the Boards section's Add
   board and the terms popover's Add room are menu buttons (`workspace/AddMenu.tsx`). Arrow keys
   move between the items; Enter, Space or a click adds one. On Chromium, a native select fired
   `change` on each ArrowDown and added rooms one by one. A menu is two clicks, as the select was,
   so the acceptance budget is unchanged.
9. *"Updating" only while something is on its way (medium, and the stale cells' contrast, low).*
   `draftPreview.resolvedStatus` says what the resolved prices are, compared with the screen:
   - current;
   - updating (an answer for this state is in flight or asked for after the pause);
   - failed (its call failed);
   - as saved (above the overlay cap with unsaved changes).
   The matrix and the ladder show:
   - the spinner and "Updating…" only while a price call is in flight;
   - "Prices not updated" after a failure;
   - nothing extra when as saved (the "Saved draft only" badge is there).
   A stale cell's name ends ", updating", ", not updated: the last calculation failed" or ", as
   saved (without your unsaved changes)". The visible status is no longer in the live region that
   bulk and undo messages use. Stale cells are italic zinc-600 instead of 55 % opacity (4.5:1 in
   both themes; `contrast.test.ts` checks it).
10. *Ctrl/Cmd+S and closing the tab cover every typed field (medium).* The child-age band fields
    (CommitInput) and a new period's inline dates (FreshDates):
    - commit on Ctrl/Cmd+S before the version editor's save reads the tables;
    - mark typed text (`data-uncommitted` + `data-changed`).
    The tab asks before it closes while such a field, a changed cell editor, or a base-room entry
    waiting for `apply_op_values` is on the page (`keptState.UNCOMMITTED_INPUT`).
11. *Alt+Enter in a boards cell keeps what was typed (medium).* It commits the entry as Enter does,
    or keeps a refused one as the cell's error draft, then opens the row's terms. When the entry
    removes a board, the removal's confirmation comes instead.
12. *One tab stop per grid (medium, §3.19).* The headers' controls are a "header lane"
    (`ui/grid.ts`):
    - They have `tabIndex={-1}` and say which header they belong to (`data-lane-col`,
      `data-lane-rows`). These are the Room and Period actions, "+ Period", a board row's terms or
      discard button, and the sample party select.
    - ArrowUp on the first row or ArrowLeft on the first column goes to them. On them, the arrows
      move along the header, and ArrowDown or ArrowRight goes back into the cells. Enter or Space
      opens a menu, and a select keeps its own ArrowUp and ArrowDown.
    - While a grid has no cell (no room yet), its header controls stay Tab stops.
13. *The rest (low):*
    - Shift+click on a row or column header selects every row or column from the anchor's
      (`grid-model` `extend`); the keyboard help lists it.
    - On a desktop (from `lg`) the non-modal side panels sit beside the page. The shell's content
      column gives up their width (`html[data-side-panel-open]`, `.tex-page`). The Price test panel is
      `md` (28 rem): at 1440×900 the matrix, Save and Publish stay uncovered beside it.
    - Ctrl/Cmd+C, V, R and D on a ladder or boards cell show where copy, paste and fill work, and
      what to use instead (`useMatrixOnlyBulk`).
    - Their Delete refusals are toasts, as in the matrix.
    - A weekday-limited period names its days in the viewer's language.
    - The Price test result is no longer one live region; a short status announces the total.
    - A board's row header and messages use its name.
    - German "+ Zeitraum" matches its accessible name "Zeitraum hinzufügen".

**Deviations from the findings' fixes, with reasons.**
- *`party_total` is unchanged.* The finding suggests returning the combination rule from it. One
  function, `party_rules`, now answers both cases (a party that prices and one that fails), and it
  runs only for a viewer without cost.
- *No clipboard or fills in the ladder and the boards grid.* S11 deviation 8 and S13 deviation 8
  stand. The finding's interim fix is built: the keys say where those work instead of doing nothing.
- *`useInlineGridEditor` is still not extracted* (open, as after S16). Two of the divergences
  the finding names are closed: Alt+Enter in the boards grid, and Delete refusals shown only to
  screen readers.
- *Validation for a viewer without cost also leaves those issues out for the saved draft*, not only
  for the overlay. The saved check is the same oracle, only audited through the save.

**Tests (S16 re-review follow-up).**
- *Integration, `test_pricing_workspace_api`, 61 (55 + 6):*
  - a whole-party policy rule hides the party's total (saved and unsaved);
  - a failure of a party that a hidden rule takes part in says nothing, for probes X = 200, 238 and
    300, and the live check leaves out the sweep's issue, while a capacity error is still said;
  - the live check leaves out OCC_POLICY_OVERRIDE_OUTRANKED (saved and unsaved);
  - the budget window always expires (a race and a counter without a TTL);
  - a leaked slot ages out while the user retries;
  - `preview_price` with data is bounded.
  Fail-first: 8 failures and 1 error on the unfixed code.
- *Unit (Python), 496 (491 + 5):* `test_matrix.TestPartyRules` 3 and
  `test_policy_cascade.TestHiddenPolicyRules` 2. Fail-first: 8 errors (`party_rules` and
  `hidden` missing).
- *Unit (frontend), `npm run test:unit` 303 (296 + 7):* `state-keys.test.ts` 3 (it fails with
  "en: missing rates.occ.state.cost_hidden" on the unfixed catalogue), `resolvedStatus`, the stale
  contrast, the header range and the popover's slot switch. Fail-first on the unfixed frontend: 5
  of 5 files fail.
- *DOM, `npm run test:dom` 32 (31 + 1):* the header lane (Tab leaves the grid, ArrowUp/ArrowLeft
  reach the header buttons, the arrows move along and back). Fail-first: it fails on the unfixed
  harness.
- *E2E, `pricing-workspace-rereview.spec.ts`, 11 tests:*
  - the explanation after a second result with other dates, and no live region around the result;
  - a Child 2 position row and "also when children travel" from the ladder popover (the rows sent);
  - Add room by keyboard (arrows add nothing, Enter adds one);
  - the matrix after a failed `price_matrix` call ("Prices not updated", no "Updating…", stale
    cells italic at full opacity);
  - Ctrl+S in a child-age field (the save body) and the beforeunload prompt for a typed one;
  - Alt+Enter in a boards cell keeps "+25" and opens the terms, and a board row header says "Half
    board · Garden Villa only";
  - one tab stop in the matrix and its header lane;
  - Shift+click from P3 to P4;
  - at 1440×900 the Price test panel is at most 450 px wide, the matrix and Publish end left of it,
    and a right-click on a matrix cell beside it still reaches the cell;
  - Ctrl+V and Ctrl+R on a ladder cell;
  - German weekday names and "+ Zeitraum".
  Fail-first: all 11 fail on the unfixed frontend (the S16-review tree, served by Vite :5187 on the
  same bench).
- *Changed specs:* Add room and Add board are picked from their menus (`flows/budget.pickFrom`, two
  clicks as the select was: the acceptance still counts 41 clicks). The boards spec reads board
  names where it read codes ("All inclusive becomes the base board …", "Half board · Garden Villa
  only", "Half board already has rules …").

**Verification (S16 re-review follow-up).**
- *Python:* unit 496 OK, ruff clean.
- *Frontend:* `tsc -b`, `npm run build` (the bundles were not committed), `npm run i18n:tex` (5,065
  literal keys), `npm run test:unit` 303/303, `npm run test:dom` 32/32 (TEX_DOM_PORT 5188).
- *Integration:* all 38 modules migrated with this tree (`migrate_test.sh`): 844 OK (10 skipped, as
  before). `test_pricing_workspace_api` 61 of them. `test_entry_branding` failed once in that run
  (1 of 34): the tree's HEAD moved by a commit during the run, and the test compares the source
  link's commit with HEAD. It passed 34/34 on its own afterwards.
- *Upstream suites with this tree:* eval harness 76/76, front-desk journey 13/13, banquet 101 OK.
- *Browser, on the tree's own servers (bench :8016 with this tree, Vite :5186):* the eleven
  workspace specs, `editor-edits`, `contract-admin` and `critical-journey`, desktop and Pixel 7: 83
  tests, 83 passed on the final run. The acceptance counted 41 clicks, 0 section switches and 0
  modal dialogs. The first run had 6 failures, all fixed before the final run:
  - five came from two regressions of this follow-up, fixed in `8a76b52`: the matrix's live region
    had lost its inner `.sr-only` (four bulk tests read it), and the page marker `data-side-panel`
    was also set on `<html>` (the S16 review test finds the panel by it);
  - one came from the boards spec expecting board codes.
- Main `1575c8b` had no newer commit: nothing to merge.

**O1–O5 after the S16 re-review follow-up** (all five provisional, owner input 13): unchanged. No
parser, op mapping or `apply_op_values` change.

**Open after the S16 re-review follow-up.**
- The grids' inline editing is still written three times (PriceMatrix, OccupancyLadder,
  BoardsSection). A `useInlineGridEditor` hook (a pure reducer and a thin hook) is open, as after
  S16.
- The ladder and the boards grid have no clipboard or fills of their own. They say where those
  work.
- A relative entry on the base room that is waiting for `apply_op_values` is still not in a
  Ctrl/Cmd+S made meanwhile. The tab now asks before it closes while one is waiting.
- Between `sm` and `lg` a non-modal side panel still covers the page's right side. From `lg` the
  page makes room for it.
- Still open from S16: the §3.18 one-screen fit, `HEAVY_LIMITS` as constants, no F6 shortcut, an
  error draft of a removed room or period kept until Discard, only Chromium run, CI not yet run on
  GitHub (resolved 2026-09-26).

**S16 re-review 2 follow-up (2026-09-25).** A third review of the workspace reported one high, four
medium and eight low findings. All thirteen are fixed. Branch `pricing-workspace`; main `1575c8b`
has no newer commit, so no merge was needed.

**Decision (S16 re-review 2 follow-up).**
1. *Hide only what depends on a hidden value (medium; corrects re-review decisions 1 and 2).* The
   re-review hid every sample party and sweep warning that a hidden policy rule took part in, failures
   included. For a failure, the rules that take part are all the rules resolved before it. So a
   NO_CHILD_RULE failure ("no occupancy rule for child 1 in band CHD (2A+1C)", with no amount) was
   hidden whenever a policy rule priced an adult before the child. An editor without
   `price.view_cost` then lost every unsellable-combination warning and saw "total not shown" instead
   of the error. `occupancy.depends_on` (pure) now says whether what `price_occupancy` answers for a
   party depends on the op or value of a hidden rule:
   - a total, or a negative total (NEGATIVE_OCCUPANCY_PRICE), that a hidden rule takes part in:
     yes, as before;
   - a child that no rule prices (NO_CHILD_RULE): only when a hidden rule defers (INHERIT) for that
     child, since its op is hidden too. A band without any rule is said, whoever priced the adults;
   - any other failure (an ambiguity; a failure before the occupancy is priced): no. Under
     `CASCADE` a version rule never ties a policy rule.

   `validate._sweep` asks it for NEGATIVE_OCCUPANCY_PRICE and NO_CHILD_RULE only. `_party_cells` asks
   `matrix.party_hidden` (the same answer for a sample party) and reports every other error.
   `party_rules` stays, and its docstring now says it returns an empty set, not None.
2. *The report stored at publish is filtered the same way (low).* `get_version` gave an editor
   without `price.view_cost` (contract.edit is enough to read a version) the report that
   `validate_terms(terms)` stored at publish with nothing hidden. The workspace's saved mode shows it
   as "Checked when published". `contracts.stored_report(version, formula=…)` now gives that viewer
   `validate.visible_issues(frozen terms, report, policy rules)`:
   - no OCC_POLICY_OVERRIDE_OUTRANKED (the override is always a policy rule);
   - no sweep issue whose party and period, as its `ref` names them, `depends_on` a policy rule;
   - a row that does not say which override or party it is about is left out.
   If the frozen terms cannot be read, every issue of those codes is left out. The stored report
   itself is unchanged, and whoever sees cost gets it as stored.
3. *The single-use row switches form as a whole (high and medium, §3.6.2).* The popover wrote the new
   form (ADULT 1 in 1+*, or COMBINATION 1+0) only in the cells it wrote. The ladder showed one form
   per row, and the combination cards left out both forms, so the rule just written could show
   nowhere while it priced. Two changes:
   - `applyOccRuleAs` with a form switch rewrites every row of the old form in the rooms written
     (All periods and each period), keeping its key, op, value, "Always wins" and note, then writes
     the rule to the periods chosen, in one history entry. A cell that already has a row of the new
     form keeps it. Switching P4 of "1+0 ×1.50 for All periods" to ×1.60 gives "1+* ×1.50 for All
     periods, P4 ×1.60". The popover says "The whole row switches: its rules for every period, in
     the rooms chosen, keep their values."
   - `ladderModel` shows a row for each form that a rule reaching the scope has: "1 Adult (single
     use)" (`single:0:`) and "1 Adult (also with children)" (`single:1:`). With no rule it shows the
     first. Both rows show when both forms reach, for example from a draft saved before this change,
     or from All rooms' 1+0 and a room's own 1+*, where the engine applies both. Each row then edits
     its own form, and the switch is not offered. Issue anchors follow (`ladderRowIdOf`, a party's
     single-use card), and the summary names the second form "1A (also with children)".
4. *The header lane is said (medium, §3.19).* The Keyboard shortcuts popover has a row for it
   ("ArrowUp on the first row, ArrowLeft on the first column": a column's or row's actions; Enter
   opens a menu, and ArrowDown or ArrowRight goes back to the cells). The matrix, ladder and boards
   hints end with the same sentence, and each grid carries it as its accessible description
   (`aria-describedby`, for a read-only viewer too). Six languages.
5. *A child-age field shows what was stored (medium).* CommitInput resynced its text only when the
   stored value changed. A cleared band name is stored as the generated name, which is the old value,
   so the field stayed blank and marked changed, and the tab asked before closing until a reload.
   A commit the version takes now shows the stored value at once, focused or not. A refused code
   (`onCommit` returns false) keeps the typed text, which stays a change.
6. *The rest (low):*
   - Add room focuses the new room's first cell, as Add board does. The menu's button that the
     focus returned to is disabled once nothing is left to add. It focuses the cell element itself:
     the grid's `focusCell`, called from an effect, focused the active cell of the render before.
   - The Price test's status region is always rendered, empty until a result. It says the total,
     "unsellable", or that the result is out of date. A live region inserted with its text already
     in it is not announced. The visible out-of-date line is `aria-hidden`.
   - Unused keys and the terms popover: `rates.ws.room.add_placeholder`, `rates.brd.add_placeholder`
     and `rates.brd.pop.add_room_placeholder` are gone from the six catalogues. The terms popover's
     "Add a rule for one room" is described by its help (`Menu` `buttonProps` takes
     `aria-describedby`, `AddMenu` `describedBy`).
   - A read-only viewer's Ctrl/Cmd+C or V on a ladder or boards cell says only "Copy works in the
     room price matrix." (`useMatrixOnlyBulk(gridEl, canEdit)`).
   - Adding a board records "Add board: Half board" in the history, not the code.

**Deviations from the findings' fixes, with reasons.**
- *NO_CHILD_RULE is hidden where a hidden rule defers (INHERIT) for that child.* The finding
  suggests reporting it always. The op of a policy rule is hidden as its value is (`_rule_dict`), so
  the missing rule would say that a "Policy rule" in the ladder is INHERIT. Where no hidden rule is a
  candidate for the child, it is reported, as the finding asks.
- *Both single-use forms, and a whole-row switch.* The findings offer either. The switch rewrites
  the row, so a switch never splits it by period. The two-row model covers the drafts and room scopes
  where both forms reach, which no switch makes.

**Tests (S16 re-review 2 follow-up).**
- *Unit (Python), 504 (496 + 8):*
  - `test_policy_cascade.TestHiddenPolicyRules` + 3: a missing child rule is said whoever priced the
    adults, while a negative total goes (the finding's case: 29 NO_CHILD_RULE warnings kept); a
    missing child rule where a hidden rule defers is left out; a stored report is filtered as the live
    check is;
  - `test_matrix.TestPartyHidden` 5: a total, a negative total, a missing child rule, an ambiguity
    and a failure before the occupancy is priced.
  Fail-first: 1 failure and 8 errors (`party_hidden` and `visible_issues` missing; the finding's
  case: `[] != [29 NO_CHILD_RULE warnings]`).
- *Integration, `test_pricing_workspace_api`, 63 (61 + 2):* a child band without a rule is said to an
  editor without cost (the cell's error in both periods, saved and unsaved; the live check's
  NO_CHILD_RULE issues) while a party the policy's adult rules price stays hidden; and `get_version`'s
  report for that editor leaves out the 2A+1C negative total and OCC_POLICY_OVERRIDE_OUTRANKED, which
  a Revenue Manager still gets. Fail-first: 3 failures (`['LOW', 'HIGH'] != []` hidden for the
  NO_CHILD_RULE party, saved and unsaved; `(2, 1)` in the editor's report).
- *Unit (frontend), `npm run test:unit` 306 (303 + 3):* switching one period's form in both
  directions, switching All periods with a P4 override (and a room's own rows, and a cell that
  already has the new form), and both forms as a row each (the summary, a room scope). Changed:
  `ladderRowIdOf` of ADULT 1 in 1+* is `single:1:`, and a 1A+1C issue of a 1+* card anchors there.
  Fail-first: 5 of the 66 occupancy and issue tests fail on the unfixed frontend.
- *E2E, `pricing-workspace-rereview2.spec.ts`, 10 tests:* single use switched in P4 (the rules sent,
  the cells, the focus), switched in All periods with a P4 override, both forms of a saved draft as a
  row each, a cleared band name (the generated name shown, the tab closes without asking), the
  header lane in the shortcuts and each grid's description, Add room's focus, the Price test's
  status region before the first result, the terms popover's description, "Undone: Add board: Bed &
  breakfast", and a published ladder's Ctrl+C notice. Fail-first: 10 of 10 fail on the unfixed
  frontend (commit `47ae057`'s frontend served by Vite :5186). The two single-use tests fail on the
  rules sent: `COMBINATION:1+0:ALL:1.5` is left beside `ADULT:1+*:P4:1.6`, and
  `COMBINATION:1+0:P4:1.6` beside `ADULT:1+*:ALL:1.5`.
- *Changed tests:* `test_matrix.TestPartyRules` is unchanged (`party_rules` still answers the same);
  `workspace-issues.test.ts` expects `single:1:` for ADULT 1 in 1+*.

**Verification (S16 re-review 2 follow-up).**
- *Python:* unit 504 OK (the tracked suite), ruff clean. The worktree also holds three untracked files
  of other work (`test_main_parity.py` with `parity_data/`, and
  `integration/test_existing_semantics.py`). They are not part of this branch and are left out of
  the counts below. The parity test fails 3 of 4 on this tree and the same 3 on the tree before
  this follow-up (`47ae057`). The other module (7 tests, 35 failures and 20 errors in the full run)
  fails on `preview_price`'s night keys and child ages, which this follow-up does not touch; it was
  not re-run on the earlier tree.
- *Frontend:* `tsc -b`, `npm run build` (the bundles were not committed), `npm run i18n:tex` (5,072
  literal keys), `npm run test:unit` 306/306, `npm run test:dom` 32/32 (TEX_DOM_PORT 5186, with the
  workspace's Vite stopped).
- *Integration:* all 38 modules migrated with this tree (`migrate_test.sh`): 846 OK (10 skipped, as
  before), `test_pricing_workspace_api` 63 of them.
- *Upstream suites with this tree:* eval harness 76/76, front-desk journey 13/13, banquet 101 OK.
- *Browser, on the tree's own servers (bench :8016 with this tree, Vite :5186):* the twelve
  `pricing-workspace*` specs (desktop, and the mobile spec on Pixel 7 too): 88 of 88; `editor-edits`,
  `contract-admin` and `critical-journey`: 5 of 5.

**O1–O5 after the S16 re-review 2 follow-up** (all five provisional, owner input 13): unchanged. No
parser, op mapping or `apply_op_values` change.

**Open after the S16 re-review 2 follow-up.** As after the S16 re-review follow-up: the grids' inline
editing written three times (`useInlineGridEditor` open), no clipboard or fills in the ladder and the
boards grid, a base-room entry waiting for `apply_op_values` not in a Ctrl/Cmd+S made meanwhile,
side panels covering the page between `sm` and `lg`, and S16's open items (the §3.18 one-screen fit,
`HEAVY_LIMITS` as constants, no F6 shortcut, an error draft of a removed room or period kept until
Discard, only Chromium run, CI not yet run on GitHub, resolved 2026-09-26). New: a single-use rule of the other form that a
room scope inherits from All rooms is switched only in the rooms the popover writes, so the room scope
then shows both rows (by design: switching All rooms' rows from a room scope would change other
rooms).

**S16 re-review 3 follow-up (2026-09-25).** A fourth review of the workspace reported four medium
and fourteen low findings. Two of the low ones are context, not defects of this branch: untracked
parity files of other work in the worktree, and a reviewer's own scratch clean-up. The other
sixteen are fixed. Branch `pricing-workspace`; main `1575c8b` has no newer commit, so no merge was
needed.

**Decision (S16 re-review 3 follow-up).**
1. *A special combination's rules are the card's, not the single-use row's (medium, D8, §3.7.4).*
   The combination builder can make "1 adult + any children" with an Adult 1 line and a Child 1
   line: an ADULT position 1 rule in 1+*, the single-use row's "also with children" form. The row
   counted it as its own. Switching the row's form then rewrote the card's Adult 1 into a 1+0
   combination rule, so a 1A+children party lost its ×1.20 without a word. Now:
   - `occupancy.cardRows` marks the rows of every combination cell (combination, room, period,
     "Always wins", and for a policy's rules their source) that is not a single-use card
     (`isSingleUseCard`), as `groupCombinations` groups them.
   - `ladderModel` leaves those rows out of the single-use rows. It neither shows nor counts them
     for the row's form, and `slotRows` never edits or removes them.
   - `singleWriteRefusal` refuses a write into a cell that a card holds (`"card"`), from the
     popover, from a form switch (the rows it converts, the cells it writes) and from a typed entry
     (`applyOccEntry` gives `CARD`, "A special combination prices 1 adult in this cell…"). The rule
     would join the card or rewrite its rule. `applyOccRule` and `applyOccRuleAs` then return the
     tables unchanged, and the popover says why and keeps Apply disabled.
2. *Only the scope's own rules switch form (medium).* In a room scope the single-use row often
   shows a rule of All rooms, or a policy's. The switch then converted nothing, added the new form
   for the room, and left the All-rooms 1+0 applying. MULTIPLY replaces the party total, so 1A+0C
   still cost the All-rooms price. `LadderRow.foreign` says that a rule of the row's form reaching
   the scope is not the scope's own: a policy rule, or an All-rooms rule seen from a room, outranked
   or not. The switch is then not offered. The popover says instead: "This row's rule comes from
   All rooms or a pricing policy and would still apply, so its form is not switched here. Switch it
   where that rule is set."
3. *No relative rule is carried into the other form (low).* A whole combination's ADJUST_PERCENT,
   ADD or SUBTRACT applies to the party total, and an adult's to the slot unit. Converting such a
   row of another period or room changed its price silently (1+0 −20 % gave 118.80, after the
   switch 108.00). `singleWriteRefusal` gives `"relative"` when a converted row that the new rule
   does not overwrite has one of those ops. The popover says "Not switched: another period or room
   of this row has a rule that adds, subtracts or changes by a percentage…". Replacing ops (ABSOLUTE,
   FIXED, MULTIPLY, PERCENT_OF) and INHERIT price the same in either form, so the popover's "keep
   their values" holds.
4. *Undo and redo from the keyboard keep the focus in the grid (medium, §3.19).* Ctrl/Cmd+Z after
   Add room removed the focused row, and so did Ctrl/Cmd+Z after a single-use switch (the row's id
   changes). The focus fell to the page, where the grid's keys no longer reach. `ui.refocusIfLost`
   runs after a keyboard undo or redo in the matrix, the ladder and the boards grid. Once the change
   is rendered, it focuses the active cell by position, if the focus is on the body or on an element
   no longer in the page. The toolbar's buttons keep their own focus. The toast's Undo already had
   `onToastFocusBack`.
5. *A refused or partly typed new child-age band keeps the tab from closing silently (medium).*
   `onCommit` of a draft band returned true even when `commitDraft` refused the range. `setDraft`
   made the field's value the typed text, so nothing was marked changed. A refused range now
   returns false. The drawer renders a hidden `[data-uncommitted][data-changed]` marker while the
   draft band holds anything typed (label, From, Up to or Infant), so the tab asks before it closes
   (`keptState.UNCOMMITTED_INPUT`).
6. *What a viewer without cost learns of a hidden policy rule's op (low; corrects re-review 2's
   "the op of a policy rule is hidden as its value is").*
   - OCC_INFANT_GENERIC named every non-INHERIT band-less child rule, hidden ones included, and
     left INHERIT ones out. `validate._infant_generic(t, hidden)` names no hidden rule. It says
     nothing for an infant band that a hidden rule names. The stored report
     (`visible_issues`) gives the live check's row in place of the stored one, and
     OCC_INFANT_GENERIC is in `HIDEABLE_CODES`.
   - `occupancy.depends_on` counted only hidden rules that won a slot. A hidden rule that defers
     (INHERIT) where it would otherwise win decides the winner too. The finding's example: a policy
     rule naming an infant band over the version's band-less rule, G-31. So the sample party (shown
     or "total not shown") and NEGATIVE_OCCUPANCY_PRICE still told the op apart.
     `_defers_where_it_would_win` tries each such hidden INHERIT rule with a pricing op in its
     place. If it would then take part, the answer depends on it, for a total and a negative total
     alike.
7. *The rest (low):*
   - *Header lane, per grid (§3.19).* The matrix keeps "ArrowUp on the first row or ArrowLeft on
     the first column reaches the headers' actions (Enter opens a menu)", for an editor only; a
     read-only matrix has no header controls. The ladder says "ArrowLeft on the first column of the
     resolved line reaches its sample party.", while the resolved line is shown. The boards grid
     says "ArrowLeft on the first column reaches the row's board terms (Enter opens them).", for an
     editor with boards. Each grid's `aria-describedby` points at the visible hint's note, not at a
     second, screen-reader-only copy, and is left off where the grid has no lane.
   - *The single-use checkbox:* its help and the consequence line ("The whole row switches…") are
     its description. The consequence line is a polite live region, there from the start, so ticking
     the box says what Apply will now do.
   - *A new period's dates:* committing them (Enter, Ctrl/Cmd+S) or keeping them (Escape) unmounts
     the focused input. The period's first cell then takes the focus (its menu button when there
     are no rooms). The cell element is focused itself: the grid's `focusCell`, called from a
     frame, focused the previous active cell.
   - *i18n:* the TEX i18n check also reads both keys of `t(cond ? "a" : "b")`. `stateKeys()` lists
     `cellTone.STALE_STATE`'s keys and `rates.sh.err.CARD`.
   - *Toasts* stay about 60 ms per character, 4.5 s at least (8 s for an error) and 15 s at most.
     The ladder's 190-character German copy/paste notice now stays 11 s.
   - *Side panels:* a panel sits beside the page only where a few price columns still fit (md from
     80rem, lg from 96rem, xl from 120rem), and while it does, the grids' sticky row header is
     `clamp(9rem, 12vw, 12rem)` (`--tex-row-header`). Below those widths it lies over the page as
     before the S16 re-review. At 1280 px the matrix keeps All periods and two periods beside the
     Price test, at 1440 px three.
   - *The Price test panel's nightly table* shows the night, cost (with `price.view_cost`),
     selling and final price. The steps between them are in the Explain ladder above. The table's
     columns hid by the viewport's width, so in the md panel it was 784 px wide in a 405 px
     scroller.
   - *Docs:* the re-review 2 verification ran twelve `pricing-workspace*` spec files, not
     thirteen.

**Deviations from the findings' fixes, with reasons.**
- *A room or policy rule: no switch, and the rooms default is unchanged.* The finding offers "say
  that the All-rooms or policy rule still applies and default its rooms to All rooms". Defaulting
  to All rooms from a room scope would convert All rooms' rows for every room from a popover opened
  on one room. The popover says why the switch is not there and where to make it.
- *The whole-row switch refuses any relative op it would carry.* It does not also check whether
  adult 1 of a 1A+0C party is priced at exactly the unit. That would make the switch depend on
  another row's rule. The finding lists this restriction as an option.
- *A card-held cell is refused for every single-use write, not only a switch.* With the card's rows
  out of the row, a typed entry or a popover rule in that cell would have rewritten or joined the
  card unseen.
- *The copy/paste notice stays a toast, longer.* The finding also suggests a notice kept until
  dismissed. A longer toast is also one of its options, and the change applies to every toast.

**Tests (S16 re-review 3 follow-up).**
- *Unit (Python), 506 (504 + 2), `test_policy_cascade.TestHiddenPolicyRules`:*
  - the infant warning names no hidden rule, live and stored, and says nothing where a hidden rule
    names the band, INHERIT or not;
  - a hidden infant-band rule that defers hides the 2A+[INF] party as one that prices does, in
    `depends_on` and in the live check's NEGATIVE_OCCUPANCY_PRICE; a hidden INHERIT that a more
    specific version rule outranks takes no part.
  Fail-first: 2 failures (the INHERIT subtest's `depends_on` is False; the viewer without cost gets
  "…priced by the band-less child rules (G-ANY-A)").
- *Unit (frontend), `npm run test:unit` 310 (306 + 4):* the builder's "1 adult + any children" card
  through a switch both ways, with a refused All-periods switch, a refused typed entry and a Remove
  that leaves the card (`workspace-occupancy.test.ts`); `foreign` for All rooms, a room's own rule,
  both, and a policy's; the relative-op refusal both ways; the state keys picked from a map
  (`state-keys.test.ts`). Fail-first: with a stub `singleWriteRefusal` export the three occupancy
  tests fail on the unfixed model (`['single1', 'adults_base']`, `foreign` undefined, `null !==
  'relative'`); without it the module does not load.
- *E2E, `pricing-workspace-rereview3.spec.ts`, 9 tests:* the card through a switch both ways (the
  rules sent) and its refused All-periods switch, a room scope without the switch, the
  relative-op refusal, keyboard undo after Add room and after the switch, a refused new band that
  makes the tab ask, each grid's own lane note, read-only grids without one, a new period's focus,
  and the Price test panel's nightly table and page padding at 1440 and 1100 px. Changed:
  `pricing-workspace-rereview2.spec.ts` expects each grid's own note.
  Fail-first: 9 of 9 fail on the re-review 2 frontend (`2776ba5`'s frontend served by Vite :5186
  against this tree's bench). The card test fails on the "1 Adult (also with children)" row the
  card's rule made (1, expected 0). The switch is offered in a room scope (1, expected 0). Apply is
  enabled for a relative rule. The focus is on `body` after Ctrl+Z. No uncommitted marker for the
  refused band. Each grid carries the matrix's note, also read-only. The new period's cell is not
  focused. The nightly table overflows the panel.

**Verification (S16 re-review 3 follow-up).**
- *Python:* unit 506 OK (the tracked suite), ruff clean. The worktree's untracked files of other
  work (`test_main_parity.py` with `parity_data/`, `integration/test_existing_semantics.py`) are not
  part of this branch. The parity test fails the same 3 of 4 as before this follow-up. It is not
  counted here.
- *Frontend:* `tsc -b`, `npm run build` (the bundles were not committed), `npm run i18n:tex` (5,100
  literal and conditional keys), `npm run test:unit` 310/310, `npm run test:dom` 32/32.
- *Integration:* all 38 tracked modules migrated with this tree (`migrate_test.sh`): 846 OK (10
  skipped, as before), `test_pricing_workspace_api` 63 of them.
- *Upstream suites with this tree:* eval harness 76/76, front-desk journey 13/13, banquet 101 OK.
- *Browser, on the tree's own servers (bench :8016 with this tree, Vite :5186):* the thirteen
  `pricing-workspace*` spec files (the new `rereview3`; desktop, and the mobile spec on Pixel 7 too).
  The first full run gave 96 of 97. `bulk` test 1 applied a Ctrl+Enter to one cell of a three-cell
  selection under load, and passed in both runs of `--repeat-each 2` of the bulk spec (28 of 28).
  The final run of the thirteen files with `editor-edits`, `contract-admin`, `critical-journey` and
  `policy-revisions` passed 103 of 103 (97 workspace tests). Measured beside the Price test: at
  1280 px the matrix keeps All periods, P1 and P2 in view; at 1440 px also P3. At 1024 px the panel
  lies over the page.

**O1–O5 after the S16 re-review 3 follow-up** (all five provisional, owner input 13): unchanged. No
parser, op mapping or `apply_op_values` change.

**Open after the S16 re-review 3 follow-up.** As after the S16 re-review 2 follow-up: the grids'
inline editing is written three times (`useInlineGridEditor` open); the ladder and the boards grid
have no clipboard or fills; a base-room entry waiting for `apply_op_values` is not in a Ctrl/Cmd+S
made meanwhile. S16's open items remain: the §3.18 one-screen fit, `HEAVY_LIMITS` as constants, no
F6 shortcut, an error draft of a removed room or period kept until Discard, only Chromium run, CI
not yet run on GitHub (resolved 2026-09-26). Changed:
- Side panels now lie over the page below 80rem (md) instead of below `lg`. At 1024–1279 px the
  Price test covers the matrix's right side again, rather than leaving it no columns.
- The re-review 2 item "a single-use rule of the other form that a room scope inherits from All
  rooms is switched only in the rooms the popover writes" is gone: the switch is no longer offered
  there.

New:
- A special combination's cell refuses the single-use row's writes. To change the row there, edit
  the card, or write other periods.
- The switch refuses a relative rule in another period or room, even where adult 1 of 1A+0C is
  priced at exactly the unit and the price would not change.
- The copy/paste notice is still a timed toast, not one kept until dismissed.

**Existing semantics kept, the workspace's additions opt-in (2026-09-25).** The owner's rule for the
workspace: it changes the UX only, and no existing pricing semantics change silently (O1–O5 stay
provisional owner decisions). A check of the branch against main found that several of its changes
altered what existing callers get, workspace or not: every internal quote (the price test, a TEX
Quote's `result_json`, a reservation's pricing snapshot) carried three more keys per night
(`subtotal_*`); `validate_version` and `publish` reported board rows main published as ERRORs and
refused to publish them, gave each issue a `ref` key and stored it in the report frozen at publish;
`save_version` refused a blank rule value that main stored as 0; `preview_price` refused children
main priced (`7.5`, `"7.5"`, 18, 13 children) and read `{age_months}` / `{dob}`; `validate_version`
of a saved draft was rate limited; `price_matrix`, `get_version` (also an agent's catalogue) and
`save_version`'s answer had more keys. Branch `pricing-workspace`; main `1575c8b` has no newer
commit (it adds only the design document to `6b0102c`, the branch's base).

**Decision (existing semantics kept).**
1. *Existing callers get main's answers.* An existing caller is one that sends what main takes. The
   workspace's additions are opt-in: the flag `workspace` (`1`/`true`), or an argument only the
   workspace sends (`data`, the read-only overlay; `parties`, the sample parties), turns them on
   (`api/contracts.py _workspace`). Without them every contract endpoint answers as main did:
   - `preview_price` runs main's body (`_mains_preview`): each child `int()` of what was sent,
     main's night keys;
   - `price_matrix` runs main's body (`_mains_matrix`): cells, errors, periods, basis, currency;
   - `get_version` (and `save_version`'s answer, and an agent's catalogue) has main's keys;
   - `save_version` stores a blank rule value as 0, as main does;
   - `validate_version` has no board checks, gives each issue main's three keys and is not bounded
     per user; `publish_version` decides, stores and returns exactly what main did.
2. *The pure layer's defaults are main's:* `validate_terms(board_checks=False)` (the board checks
   are `_board_issues`), `Issue.to_dict(ref=False)` (main's three keys; `ref=True` adds `ref` when
   there is one), `RoomQuote.to_dict(subtotals=False)` and `NightPrice.to_dict(subtotals=False)`.
   The engine still computes the subtotals and the validation still computes each `ref`; they reach
   a dict only when asked for. `commercial.contracts.validate_version/validate_doc/publish` take
   `workspace` and pass it on.
3. *What the flag turns on (the workspace sends it).* `get_version`: `can_preview`, `can_publish`,
   `can_edit_contract`, `basis_locked`, `overlay_max_rows`, `contract_doc.minor_units` (GAP-10; the
   catalogue's three `can_*` as false). `save_version`: the blank-value refusal (GAP-8), and the
   workspace's `get_version` answer. `validate_version`: the board checks (GAP-5), each issue's
   `ref` (D9) and the per-user budget (`_heavy`). `publish_version`: the board checks block the
   publish, and the stored report and the warnings carry each `ref`. `preview_price`: exact child
   ages (GAP-6) and each night's subtotals (GAP-12). `price_matrix`: cell sources, capacity, age
   bands with their origin, inherited rules and the engine's defaults (GAP-2/3). `data` and
   `parties` imply the flag; `apply_op_values` is new and has no existing caller.
4. *Security and tenancy fixes hold for every caller, never opt-in* (the deliberate, reported
   differences from main; the list for the owner below): another hotel's rate plan, cancellation
   policy or payment policy is refused wherever a draft's terms are built (`build_terms`), and an
   editor without `price.view_cost` is not told what a pricing policy's formula decides (the live
   check and the report stored at publish). The previous agent's draft test asserted main's
   behaviour for the first; it now asserts the refusal.
5. *The workspace sends the flag* (`WORKSPACE` in `draftPreview.ts`): `get_version` and
   `save_version` in the version editor, `price_matrix` and `validate_version` in both preview modes
   (`matrixRequest`, `validationRequest`), `preview_price` from the Price test, and the version
   editor's publish dialog (`PublishDialog workspace`). The contract detail page and the ARI grid
   open the same dialog without it and publish as main did. The rates tab's fallback `price_matrix`
   (no live preview) reads main's keys only and sends no flag.

**Every behaviour difference from main for an existing caller (the owner's list).**
- *Kept, security and tenancy (deliberate, for every caller):*
  1. A draft whose rate plan row names another hotel's rate plan, or whose rate plan row names
     another hotel's cancellation or payment policy (a policy of no hotel is shared), is refused
     wherever its terms are built: `validate_version` answers `ok: false` with one BUILD issue
     ("… belongs to another hotel"), `preview_price` of the draft answers `sellable: false` with
     reason BUILD, `price_matrix` of the draft and `publish` raise a ValidationError, and the ARI
     grid on the draft (`grid.py`) refuses it. Main priced, validated, showed and published it.
     Saving such a row is accepted, as on main (a save builds no terms). A version already
     published is priced from its frozen payload and is not affected.
  2. `validate_version` for an editor with `contract.edit` but without `price.view_cost` leaves out
     each issue whose presence depends on an inherited pricing-policy rule's op or value:
     OCC_POLICY_OVERRIDE_OUTRANKED about a policy override; the sweep's NEGATIVE_OCCUPANCY_PRICE of
     a party a policy rule takes part in and NO_CHILD_RULE where a policy rule defers; and
     OCC_INFANT_GENERIC names no policy rule and is not said for an infant band a policy rule names.
     All four are WARNINGs, so `ok` and the publish decision do not change. Main told that editor
     (an equality and threshold oracle on the policy formulas, which are cost, G-11).
  3. `get_version`'s `validation_report` for that editor is the report stored at publish, filtered
     the same way. A stored row that does not say what it is about (every report an existing
     caller's publish stores, and every report published before the branch, has main's three keys)
     is left out when its code is one of the four above. Who sees cost gets the report as stored.
- *Opt-in (an existing caller gets main's behaviour; the workspace sends the flag):* the board
  checks (GAP-5) in the live check and at publish; each issue's `ref` (D9), live and stored; the
  blank-value refusal on save (GAP-8); the per-user budget of `validate_version`; exact child ages
  in the price test (GAP-6); each night's subtotals (GAP-12); the matrix's and the version's
  workspace keys (GAP-2/3/10); the overlay (`data`, GAP-1) and the sample parties (`parties`,
  GAP-2b), which are new arguments; `apply_op_values` (GAP-7), a new endpoint.
- *Consequence of the opt-in:* a draft with a board row for an unknown room or period, or two rows
  of one board for the same scope, is refused by the workspace's publish and published by the
  contract detail page's or the ARI grid's publish, as on main. Whether the board checks (or the
  blank-value refusal) should hold for every caller is the owner's decision (owner input 14).

**Tests (existing semantics kept).**
- *Unit, `test_main_parity.py` with `parity_data/`* (the previous agent's untracked draft, checked
  and completed). The corpus: 14 fixture payloads in every shape main accepts and 11 payloads
  published on the dev site (10 of them still there with the same hash), 2,906 quotes (2,615
  sellable) byte for byte (the sha256 of the internal dict and of the guest view), each payload's
  issues, frozen hash and room units, and 97 drafts made from three of the payloads, each broken or
  unusual in one way and together reaching every issue code main's validation reports (but the
  sweep's AMBIGUOUS_OCCUPANCY_RULES, which an OCC_AMBIGUOUS error always precedes). The expected
  results were recorded as the docstring says (`git archive 6b0102c kamra`, the file run as a script
  with that `PYTHONPATH`, so every import is main's); the recording of the draft's file was
  reproduced byte for byte, and the drafts' recording is identical on main and on the fixed branch.
  `TestMainParity` (5) passes against main's code and this branch's; `TestWorkspaceOptIn` (3) checks
  the switches. Fixed in the draft: the dev payload count (11, not 16); issues must be identical
  (the draft let the board checks come on top as WARNINGs); the corpus's issues must have main's
  keys. Fail-first on the branch before the fix: 2,615 of 2,906 quotes differ (the night keys), the
  orphan-board payload's issues differ (three board ERRORs instead of main's warnings) and three
  payloads' issues carry `ref`; 87 of the 97 drafts differ.
- *Unit, updated:* `test_validate_refs` (+2: the board checks and `ref` are off by default; the rest
  asks for them), `test_engine.TestReportedSubtotals` (main's night by default, the subtotals when
  asked for, never in the guest view), `test_policy_cascade` (a stored report as the workspace
  stores it, with refs, and as an existing caller's publish stores it, without). 516 OK.
- *Integration, `test_existing_semantics`* (13; the previous agent's draft, completed): `preview_price`
  against main's own body (a draft and a published version, every room, board and plan; children
  `[]`, `[8]`, `["8"]`, `[8.0]`, `"[8, 1]"`, `[7.5]`, `[11.9]`, `[18]`, 13 children, `None`; `7.5`
  priced as 7; `"seven"` refused by `int()`); `price_matrix`, `get_version` (Administrator, a
  Revenue Manager, an agent's catalogue) and `save_version`'s answer against main's bodies; a blank
  value saved and priced as 0 (the draft compared the quotes with their row names, which a save
  renews: it failed on main too); board rows main published publish, unreported; main's issue keys
  live, in publish's warnings and in the stored report; no rate limit on a saved draft's check; a
  TEX Quote and a reservation snapshot with main's night keys; and `TestSecurityChanges` (3), the
  deliberate differences. Run against main's code (`git archive 6b0102c` with this module, migrated
  with it): 10 of 13 pass, the 3 security tests fail as designed. On the branch before the fix: 12
  of 13 fail (68 failures and errors in subtests); after it, 13 of 13 pass.
- *Integration, updated:* `test_pricing_workspace_api` calls as the workspace does (`wapi`: every
  call with `workspace=1`; `publish(..., workspace=True)`); `bench_pricing_workspace` too;
  `test_security_regressions` is main's again (the catalogue without the flag has main's keys).
- *Frontend:* `npm run test:unit` (`draft-preview.test.ts`: every request of both modes and sources
  carries `workspace: 1`; fail-first: the module had no `WORKSPACE` export). E2E
  `pricing-workspace-optin.spec.ts`: opening a draft, an unsaved edit's live price and check, the
  Price test, Save and Publish all send `workspace=1`. `pricing-workspace-issues` test 5 and
  `flows/workspace.ts publish` publish as the workspace does (their read-only view anchors the
  stored report by `ref`). Fail-first: `pricing-workspace-optin` against the frontend before it sent
  the flag (`2a13fd3` served by Vite :5187 against this tree's bench) fails: without the flag
  `get_version` has no `can_preview`, so the workspace does not offer the Price test.

**Verification (existing semantics kept).**
- *Python:* unit 516 OK (`test_main_parity` 8), ruff clean. `TestMainParity` also against main's
  code (`git archive 6b0102c` with the test and its data): 5 OK.
- *Frontend:* `tsc -b`, `npm run build` (the bundles were not committed), `npm run i18n:tex` (5,100
  keys), `npm run test:unit` 311/311.
- *Integration, migrated with this tree (`migrate_test.sh`):* `test_existing_semantics` 13,
  `test_pricing_workspace_api` 63, `test_commercial_flows` 63, `test_age_bands` 11,
  `test_money_fields` 9, `test_critical_journey` 31, `test_security_regressions` 59,
  `test_pricing_policies` 14: all OK. `test_existing_semantics` against main's code (migrated with
  it): 10 OK, the 3 of `TestSecurityChanges` fail as designed.
- *Browser, on the tree's own servers (bench :8016 with this tree, Vite :5186):* the fourteen
  `pricing-workspace*` spec files (desktop, and the mobile spec on Pixel 7 too) 98/98, and
  `editor-edits`, `contract-admin`, `critical-journey` and `policy-revisions` 6/6: 104 passed.
- *Full integration regression, migrated with this tree:* all 39 modules, 859 tests: 858 OK (10
  skipped, as before) and 1 error, `test_system_status.test_an_old_fx_rate_warns_and_a_stale_one_fails`,
  run at 21:2x UTC (just after midnight on the site's Europe/Istanbul clock). It fails the same way
  against main's code (`6b0102c`) run at the same time and passed in this branch's earlier full runs:
  it depends on the time of day, not on this change.
- Not run for this follow-up: the upstream suites (eval, journey, banquet).

**O1–O5 after the existing-semantics follow-up** (all five provisional, owner input 13): unchanged.
No parser, op mapping or `apply_op_values` change.

**Open after the existing-semantics follow-up.**
- Owner input 14: confirm the three security differences; decide whether the board checks and the
  blank-value refusal should hold for every caller (today the contract detail page's and the ARI
  grid's publish still publish a draft with orphan or twin board rows, and a caller other than the
  workspace still saves a blank value as 0).
- A report stored by a publish without the flag (and every report published before the branch) has
  no `ref`: the workspace's read-only view lists its issues but anchors none of them to a cell, and
  an editor without cost is not given its rows of the four policy-dependent codes at all.
- `preview_price` and `price_matrix` keep main's bodies as separate functions (`_mains_preview`,
  `_mains_matrix`) beside the workspace's, so either can be read against main line for line.

**Draft overlay performance (2026-09-25).** Measured by the regression module
`kamra/tex/tests/integration/test_pricing_workspace_perf.py` (about 3.5 minutes). The opt-in
`bench_pricing_workspace` stays for best-of-three figures near and above the row cap.
- *The draft* (saved in the test transaction, rolled back): 15 room types, the base room priced per
  period and 14 derived by a formula for all periods with their own price in every fourth season;
  26 periods (22 seasons over 1 May–31 Oct and 4 Fri/Sat periods, June–September); PERSON basis;
  adult positions 1–4 with the 3rd adult per period and per room and period, the 4th per room and
  period; 4 child bands (INF, CH1, CH2, CH3) with band, first-child, per-period and per-room-period
  rules; 11 special combinations (1+0 … 4+2, 2A+2C also per peak period and per family room);
  6 boards with rules per room, period and room and period; 3 rate plans; 4 offers. That is 1,320
  rows (129 room, 902 occupancy, 237 board rules) and 390 cells. It validates with no issue, so each
  check runs the whole publish sweep (11,076 parties).
- *The calls*, as the workspace makes them (`workspace=1`): the unsaved state is posted as the
  278.5 KB JSON text the browser sends, with a one-cell edit; the same calls on the saved draft by
  name are the baseline. Each starts from a fresh request's caches (redis warm), after three
  warm-up calls (one for a call over a second): 20 timed runs, then one counted run. The response
  size is the body Frappe sends. HTTP, session and auth are not included.

| Call | Overlay p50 / p95 / max, ms | Saved draft p50 / p95 / max, ms | Response KB, overlay / saved | Queries, overlay / saved |
|---|---|---|---|---|
| `price_matrix`, whole matrix | 241.6 / 252.6 / 256.6 | 80.7 / 87.3 / 90.2 | 82.1 / 79.2 | 58 / 46 |
| … + 1 sample party (the ladder) | 247.6 / 284.9 / 287.2 | 89.3 / 97.6 / 98.1 | 94.5 / 90.8 | 58 / 46 |
| … + 12 sample parties (the cap) | 311.0 / 378.0 / 402.3 | 156.8 / 207.0 / 208.0 | 195.4 / 185.3 | 58 / 46 |
| `preview_price`, 3 nights, 2A (the prefill) | 224.5 / 263.6 / 281.8 | 65.3 / 78.7 / 81.2 | 13.8 / 13.7 | 63 / 51 |
| `preview_price`, 14 nights, 2A+2C | 231.1 / 247.2 / 280.6 | 75.1 / 98.6 / 108.3 | 73.4 / 71.9 | 63 / 51 |
| `validate_version` | 2,664 / 2,808 / 2,984 | 2,536 / 2,652 / 2,658 | 0.03 / 0.03 | 48 / 48 |
| `apply_op_values`, 26 / 500 prices | 5.3 / 6.0 / 6.4 and 9.3 / 9.8 / 10.0 | — | 0.8 and 15.6 | 7 and 7 |

`save_version` of the draft: 741 ms, once.

*Budget: met.* The whole-matrix overlay's p95 is 253 ms (285 ms with the ladder's party; budget
800 ms). A draft quote's p95 is 264 ms for 3 nights and 247 ms for 14 nights with 2A+2C (budget
500 ms). The module fails only above the budget × 3 (`TEX_PERF_FACTOR`), so a busy CI host does not
fail it; a p95 over the budget itself prints the call's cProfile (as `TEX_PERF_PROFILE=1` does).

*Queries: no growth with cells*, asserted exactly. Every overlay and saved call asks the same
number of queries for 26 periods as for 13 (half the cells and period rules). 15 rooms ask exactly
one query per room more than 8 rooms (the module allows at most one). A 14-night quote asks what a
3-night one asks. `apply_op_values` asks 7 for 26 prices and for 500.

*Where the time goes* (cProfile; the overlay and saved query sets diffed):
1. The overlay is about 160 ms of each 240 ms call and grows with the rows posted, not the cells.
   About 60 % of `_overlay` is Frappe's per-row field checks (`_validate_length`,
   `_validate_data_fields`, `_validate_selects`, `_validate_mandatory`, `_validate_non_negative`),
   each filtering the child DocType's fields again per row (`BaseDocument._filter`, 6,605 calls for
   1,321 documents). The rest is building the 1,320 child documents, loading the saved draft,
   `_as_stored` and the decimal check. `build_terms` and pricing the 390 cells take under 20 %.
2. The overlay path loads the draft twice: `price_matrix` and `preview_price` load it for their
   gate, then `_overlay` loads it again and repeats `scope.property_of`. These are the 12 extra
   queries against the saved path (the version row, its nine tables, two property lookups).
   `validate_version` loads it once, so its overlay asks what its saved path asks.
3. `build_terms` reads each room type's capacity with its own query: one per contract room on every
   path (overlay, by name, publish, selling), never per period or rule.
4. `validate_version` (2.7 s, with or without data; not budgeted): about 95 % is the publish sweep.
   For each of its 11,076 parties `occupancy.price_occupancy` filters all 902 occupancy rules:
   10.0 million `qualifiers_match` calls and as many `Party.child_count` property reads. So its time
   grows with cells × party sizes × rules; its queries do not. The client keeps one check in flight,
   debounced by the last check's duration (S8), and the server bounds it per user (`_heavy`).

No application code was changed. Open (possible optimisations, none needed for the budget): pass
the loaded draft to `_overlay` (item 2); read the contract's room types in one query (item 3);
filter the rules once per room and period in the sweep, and read `child_count` once per party
(item 4).

**Final verification (2026-09-25).** On `ebf6631`; main `1575c8b` is contained, so nothing was
merged. Unit 516 OK, ruff clean, `npm run test:unit` 311/311, `npm run test:dom` 32/32, `tsc -b`,
`npm run build` (bundles not committed) and `npm run i18n:tex` clean. All 40 integration modules
(migrated with the tree): 861 tests, 860 OK (10 skipped) and 1 error. On a disposable site:
`test_patches` 33/33 and the 7 second-connection tests of `test_crm_third_review` OK. Upstream:
76/76, 13/13, banquet 101 OK. Playwright on the tree's own servers (bench :8016 serving the tree and
its own build, RQ worker, Vite :5186; a second factor for one test user and a `tex_source_url`, so
nothing is skipped): run 1, 148 of 149 through Vite and custom-host, pay-link and manage-money 8/8
against :8016; the acceptance spec 3/3 twice in a row; run 2, 139 passed, 4 failed, 6 not run;
reruns as listed in IMPLEMENTATION_STATUS, ending with every `pricing-workspace*` spec 98/98. The
acceptance measured **41 clicks, 0 section switches, 0 modal dialogs** in each of its five runs.
- *In the workspace, intermittent:* `pricing-workspace-matrix` "Escape reverts; 'abc' and '1.500' …"
  failed in 2 of 6 runs: keys typed at once after Escape closed the invalid editor were lost (the
  editor held `.500`, or nothing opened). Likely cause: `finish` returns the focus to the cell only
  on the next animation frame (`focusAt`), so keys in between reach `body`. And
  `pricing-workspace-rereview` "one tab stop per grid …" failed once in 6 runs (ArrowDown on the
  first room's header menu did not reach the next room's menu; cause not found). Open.
- *Outside the workspace:* `test_system_status.test_an_old_fx_rate_warns_and_a_stale_one_fails`
  warns only on a site date of Wednesday to Friday (two business days against a rate three calendar
  days old); the run was on a Saturday (Europe/Istanbul) and main's code errors the same way in the
  same hold. Correction to "Verification (existing semantics kept)" above: it depends on the site's
  weekday, not the time of day. `entry-branding` "navigation: every new sub-section …" clicked a Rate
  plans row while the table showed its loading placeholders (run 1); from run 2 on, that test and
  "a restricted user sees only …" fail because `lists.version_rows` cuts at 2,000 versions and the
  shared site's hotel now has 2,114 Draft or Published versions, nearly all archived E2E contracts'
  drafts, so the demo contracts' rows are cut (answer: no row, `truncated`). On a disposable site
  the other 14 tests of `test_crm_third_review` need the shared site's `developer_mode` and
  `encryption_key`; with both, `test_new_events_never_wait_for_a_purge` still waits out its lock on
  the near-empty site.
- The lane's rule records the workspace as COMPLETE only when every suite is green: it is PARTIAL in
  IMPLEMENTATION_STATUS.

**S16 re-review 4 follow-up, security and cost group (2026-09-26).** Two findings of the fifth
review: the medium "`depends_on` leak" and the low "publish_version warnings". Branch
`pricing-workspace`.

*Finding (medium).* `occupancy.depends_on` was to guarantee that a viewer without `price.view_cost`
learns nothing of a hidden policy rule's op (S16 re-review 3, item 6). It did not. On NO_CHILD_RULE it
checked only the failing child, not rules that priced earlier children; on AMBIGUOUS_OCCUPANCY_RULES
it answered "not hidden" without looking. Two reproductions: (a) a policy rule G-C1 (child 1, CHD)
and no rule for child 2 — with G-C1 pricing, 2A+[CHD,CHD] said "no occupancy rule for child 2" in the
matrix and in 16 live-check warnings, with G-C1 = INHERIT it was hidden; (b) a policy rule G-INF (the
infant band, which outranks the version's band-less rules, G-31) over two tied version rules — with
G-INF = INHERIT the matrix said "rules V-X and V-Y both define child 1 band INF" and OCC_AMBIGUOUS
named the INF slot, with G-INF pricing the party was hidden and OCC_AMBIGUOUS named the CHD slot.

*Finding (low).* `publish_version` returned the report it stores, unfiltered, as `warnings`. A
publisher with `contract.publish` but without `price.view_cost` read in it what `get_version` leaves
out of the same report: an outranked policy override, a negative total a hidden rule takes part in.

**Decision (S16 re-review 4 follow-up, security and cost group).**
1. *`depends_on` decides without the hidden ops.* It no longer prices the party with the hidden rules
   (nor tries them with another op). It walks the slots in `price_occupancy`'s order: priced adults,
   the children after the included places, then the whole combination. The walk uses only which
   rules match, their ranks and the ops of the rules the viewer reads. So its answer is the same
   whatever the hidden ops, INHERIT included. A hidden rule "may decide" a slot when it matches
   there and no readable rule that prices ranks above it. The party is hidden:
   - when such a slot may fail or not by a hidden op: a child only hidden rules may price
     (NO_CHILD_RULE if they all defer), or two rules of one rank that may both price (a tie under a
     hidden rule, or between hidden rules);
   - otherwise, when the party gets through every slot: its total, its slots and a negative total
     then depend on the hidden rule.

   A failure no hidden rule decides is said, also after a hidden rule priced an earlier slot that
   cannot fail. This keeps the S16 re-review decision: a child band without a rule is said after
   policy-priced adults. `unit` is kept in the signature but no amount is computed.
   `_defers_where_it_would_win` is gone. `rules_taking_part` stays for `matrix.party_rules`.
2. *The live check's other op-dependent issues (`validate_terms(hidden=…)`).*
   - OCC_AMBIGUOUS depended on hidden ops through the rules ranked above the tie and through
     `_reached` (whether the children before the slot are priced). A tie of the viewer's own rules
     is now named at the first slot where no hidden rule ranked above it matches and the viewer's
     rules price the children before it. That slot holds whatever the hidden ops.
   - If there is no such slot, but some ops of the hidden rules would let the tie decide a price,
     the tie is reported without a slot: "…both price any child of 2A+1C at the same precedence
     with different values wherever the pricing policy's rules leave it to them…". Its ref is the
     pair's own scope. It is still an ERROR.
   - A tie involving a hidden rule is left out, and so is OCC_NO_VALUE of a hidden rule. A policy
     cannot go live with either (`policy_issues`); both would say the rule does not defer.
3. *The sweep and the stored report.*
   - The sweep leaves out AMBIGUOUS_OCCUPANCY_RULES too when it can depend on a hidden op
     (`_SWEEP_HIDEABLE`).
   - A combination the sweep skips for that reason is reported in the next period where it fails
     the same way independently of the hidden rules. This was already so, and it is now documented.
   - `visible_issues` no longer filters a stored report's sweep rows one by one. That was not the
     same whatever the ops. The sweep stores a combination only in its first failing period, so a
     period decided by a hidden rule hid a later, independent failure in one op and not in another.
     And the 200-issue limit, filled by hidden-dependent failures in one op, cut different later
     rows.
   - It now gives the stored sweep exactly as the live check's sweep gives it (`_visible_sweep`). A
     stored row is kept when its failure cannot depend on a hidden op. Otherwise it moves to the
     next period the live sweep would name (priced again from the frozen terms), or it is left out.
     A stored sweep at its limit is run again. `HIDEABLE_CODES` adds AMBIGUOUS_OCCUPANCY_RULES,
     OCC_AMBIGUOUS and OCC_NO_VALUE. The last two are ERRORs, which a published version's report
     never holds, so they are left out if met.
4. *Publish answers what `get_version` gives the caller.* The report is stored whole, as before.
   The `warnings` returned are `stored_report(version, formula=has price.view_cost)`, for every
   caller: the workspace's publish and an existing caller's alike. For an existing caller the rows
   have main's keys, so every row of a hideable code is left out. This is the same security fix as
   the stored report's (owner input 14, difference 3). Who sees cost gets the full report, unchanged.

**Deviations (S16 re-review 4 follow-up, security and cost group).**
- *The fix for item 1 is not the one the finding suggested.* The suggestion was: on any failure,
  also hide when `rules_taking_part & rules` or `_defers_where_it_would_win`. That would hide a child
  band without a rule after policy-priced adults. It contradicts the S16 re-review decision and its
  tests (`test_a_missing_child_rule_is_said_whoever_priced_the_adults`, unit and integration). And it
  would still decide from priced results with the actual ops, so it is not op-blind by construction.
  The walk above hides everything that fix hides whose answer can depend on a hidden op, and says the
  rest.
- *More than the two reproductions.* Rule sets generated from a fixed seed (the new
  `TestGeneratedRuleSets`) found the same class of leak in places the finding does not name:
  - `_reached` in OCC_AMBIGUOUS;
  - the stored report's first-period dedup and its limit;
  - OCC_NO_VALUE of a hidden rule.

  All are fixed here. Beyond the committed seed, 900 more sets (seeds 1–3, up to three hidden rules,
  five ops) and 500 with LEGACY precedence and larger rooms (seeds 7, 8) found no leak.

**Tests (S16 re-review 4 follow-up, security and cost group).**
- *Unit (Python), 523 (516 + 7), new `test_hidden_policy_ops`:*
  - `TestTheReportedLeaks`:
    - reproduction (a), with G-C1 INHERIT and MULTIPLY 0.5;
    - reproduction (b) in two variants (partial combinations; twins), with G-INF INHERIT and
      MULTIPLY 0;
    - a tie only a hidden rule may decide, named without its slot;
    - a stored party moved to the period the live check names, under three ops;
    - a stored sweep at its limit;
    - a hidden rule without a value.

    Each asserts that the live check, the matrix's sample parties (as `_party_cells` answers them)
    and the stored report are identical whatever the op.
  - `TestGeneratedRuleSets`: 160 generated rule sets, each run with every combination of the hidden
    rules' ops. The rule sets vary the version's rules (any op, some naming a period), one or two
    hidden rules in one or two policies, and PERSON or ROOM basis with or without included places.
  - Fail-first, on the code before the fix: 309 failures, all six reproduction tests and 47 of the
    250 rule sets then generated. The limit test was added after and failed there too (a patched
    limit of 3: the stored rows shown were `[(1,1,TEEN)]` against the live `[(1,1,TEEN), (1,2,TEEN),
    (1,3,TEEN)]`).
- *Integration, `test_pricing_workspace_api`
  `TestInheritedTerms.test_a_publisher_without_cost_is_told_the_warnings_get_version_gives_it`:*
  - a publisher with `price.view`, `contract.edit` and `contract.publish`, without
    `price.view_cost`, through the workspace's publish and an existing caller's: the answer's
    warnings equal what `get_version` gives that user, with no OCC_POLICY_OVERRIDE_OUTRANKED and no
    negative 2A+1C CHD total;
  - the stored report is the full one;
  - a Revenue Manager's warnings equal the stored report.

  Fail-first: 2 failures (both of the publisher's subtests) on the code before item 4.

**Verification (S16 re-review 4 follow-up, security and cost group).** On `3b2196f`. Main `1575c8b`
is contained, so nothing was merged.
- *Unit:* 523 OK. ruff is clean.
- *Integration:* all 40 modules, migrated with the tree (`migrate_test.sh`; migrate rc 0).
  - 862 tests: 861 OK (10 skipped, as before) and 1 error.
  - The error is `test_system_status.test_an_old_fx_rate_warns_and_a_stale_one_fails`. The site date
    was a Saturday, and this test depends on the weekday (see "Final verification"). It is not this
    group's.
  - `test_pricing_workspace_api` passed 64 tests, `test_existing_semantics` 13.
  - The perf module's p95s are within budget: whole-matrix overlay 273 ms, 12 parties 334 ms,
    quotes 253 / 236 ms.
- *Upstream with the tree:* eval harness 76/76, front-desk journey 13/13, banquet 101 OK.
- *Not run:* no frontend change, so no `tsc`, build, i18n or Playwright run.

**Open after the S16 re-review 4 follow-up, security and cost group.**
- *A refused publish still names every ERROR to any publisher.* `publish` throws "Cannot publish: …"
  with the full check's error messages before anything is written or audited. For a publisher
  without cost, an ERROR whose presence depends on a hidden rule's op is therefore still an unaudited
  probe of whether that rule defers. Examples: OCC_AMBIGUOUS at a slot a hidden rule decides; the
  sweep's tie under a hidden rule. A probe that does not refuse publishes the draft, which is
  audited.
  - Filtering the messages alone would not close the channel: the refusal itself is the answer.
    That needs an owner decision on publish semantics for such publishers.
  - *Corrected in the S16 re-review 5 follow-up (below).* This reasoning was wrong. A publisher
    can add an error that no op decides, for example a rule naming an unknown band. Then every
    publish is refused, and only the message carries the bit. The message is now filtered. What
    remains is described there.
- *The publish audit* records `warnings: len(issues)`, the full count.
- `test_existing_semantics.HIDEABLE` mirrors the old `HIDEABLE_CODES` and was left unchanged. The
  three codes added here are ERRORs, which a published version's report never holds, so its
  assertions are unaffected.

**S16 re-review 5 follow-up, security and cost group (2026-09-26).** The sixth review raised one
medium and three low findings for this group. Branch `pricing-workspace`.

*Finding (medium).* A refused publish named every ERROR of the full check.
- `publish` throws "Cannot publish: …" before anything is written or audited, and nothing limits
  how often `publish_version` is called.
- Take a publisher with `contract.edit` and `contract.publish` but without `price.view_cost`. They
  add an error that no op decides, for example a version rule naming an unknown band (`save_version`
  does not validate). Now every publish is refused.
- The other errors then carry the hidden rule's op. Two version rules V-X and V-Y tie on the child
  of 2A+1C, under a policy rule G-INF that names the infant band. With G-INF = INHERIT, the refusal
  named the tie at "child 1 (INF)". With G-INF pricing, it named "child 1 (CHD)".
- The re-review 4 follow-up had kept this open, because "the refusal itself is one bit". That was
  wrong here: the refusal is forced, so only the message carries the bit.

*Findings (low).*
1. Take a caller with `contract.publish` but neither `contract.edit` nor `price.view_cost` (no
   default profile is like this). Publish answered them the filtered report. `get_version` gives
   the same caller the catalogue, with no report.
2. The publish audit records the full warning count.
3. For a viewer without cost, `get_version` ran the whole sweep again whenever the stored sweep had
   reached its limit (200 rows). It did so on every call, with no bound.

**Decision (S16 re-review 5 follow-up, security and cost group).**
1. *A refused publish names, to a publisher without cost, only the errors of their own live check.*
   - The refusal itself is unchanged: a publish is refused whenever the full check has an ERROR.
     Who sees cost is told the full check's errors, as before.
   - A caller without `price.view_cost` is told the ERRORs of `validate_terms(terms,
     hidden=policy_rules(terms), board_checks=workspace)` (`validate.refusal_errors`). That is what
     the caller's own live check shows, and none of it depends on a hidden op.
   - If that list is empty, every error depends on a hidden rule. The message then names none:
     "Cannot publish: the rules this draft inherits from a pricing policy make it unpublishable;
     someone who may see cost can say why" (`UNEXPLAINED_REFUSAL`).
   - This holds for every caller, the workspace's publish and an existing caller's alike. It is a
     security fix: owner input 14, difference 4.
   - What remains: the refusal still says that the full check failed.
     - If the viewer's check shows an error that no op decides, the publish is refused whatever the
       ops. The refusal then says nothing.
     - Otherwise, whether it is refused can depend on a hidden op. This is the case when the
       viewer's check is clean, or shows only a tie that a hidden rule may decide (named without
       its slot). Not being refused is then a real, audited publish that puts the draft on sale.
       This is the same one-shot exposure the re-review 4 follow-up accepted for the publish's
       warnings.
2. *Publish's warnings are exactly what `get_version` gives the caller.* It uses the same predicate
   (`_sees_cost`):
   - who has `price.view_cost` gets the full report;
   - an editor without it gets the filtered report (`stored_report(formula=False)`);
   - a caller with neither `price.view_cost` nor `contract.edit` gets None. `get_version` gives that
     caller the catalogue.
3. *The stored report is worked out once, and running the sweep again is bounded.*
   - `stored_report(formula=False)` is kept per process, as the frozen terms are (`_TERMS`). The
     key is (payload hash, report hash, sweep limit); a published version's payload and report
     never change. It holds at most 256 reports and drops the oldest first. It returns a deep copy.
   - When the stored sweep reached its limit (`validate.reruns_sweep`), the work runs inside the
     caller's bound. `get_version` passes `_heavy("validate")`: 60 a minute and 3 at once per
     user, web requests only.
   - A publish, which already runs the full check, stays unbounded as before. Its answer fills the
     cache for the `get_version` that follows.
4. *The publish audit counts the warnings a viewer without cost is shown.*
   - The `contract.publish` entry recorded `warnings: len(issues)`, the full count. That count says
     how many warnings a hidden rule's op decides. It is readable by whoever reads the audit trail,
     and `audit_log` by reference needs only `reservation.view`.
   - The entry now records `len(stored_report(version, formula=False))`: the report as a viewer
     without `price.view_cost` reads it, the same whatever those ops.
   - That report is worked out once. It is also the answer to an editor without cost, and it fills
     the cache for `get_version`.
   - The full report stays stored on the version for those who see cost.

**Deviations (S16 re-review 5 follow-up, security and cost group).**
- *Low 2: the count of the filtered report,* the first of the finding's three options. There is no
  per-field redaction in `audit_log`, so recording both counts "behind the cost capability" would
  have needed one.
- *Low 3 takes both suggestions:* the cache, and the bound on a miss that runs the sweep again. The
  cache is per process, not in redis. A process entry cannot outlive a deploy that changes the
  filter, and each worker works a report out once.
- *`validate.refusal_errors` is new and pure.* The medium finding's fix is `contracts._refusal`,
  but which errors are named is `refusal_errors`, so a unit test can check it without a bench.

**Tests (S16 re-review 5 follow-up, security and cost group).**
- *Integration, `test_pricing_workspace_api` (`TestInheritedTerms`): four new tests, one extended.*
  - `test_a_refused_publish_tells_a_publisher_without_cost_what_its_live_check_tells`: the
    reproduction on one draft. The draft has the V-X/V-Y tie and a rule naming band NOPE, under a
    global policy whose infant rule is INHERIT in one run and MULTIPLY 0 in the other. It runs
    through the workspace's publish and an existing caller's.
    - The publisher without cost is told the same both times: "Cannot publish: " and their
      `validate_version` errors (NOPE, and the tie at the CHD child).
    - A Revenue Manager is told the INF slot in one run and the CHD slot in the other, as before.
    - The draft stays a draft without a payload.
  - `test_a_refusal_the_publishers_live_check_does_not_explain_names_nothing`: the viewer's check's
    errors are removed (patched). The publisher without cost is told `UNEXPLAINED_REFUSAL`; a
    Revenue Manager is told the tie.
  - `test_a_stored_report_is_worked_out_once_and_its_sweep_run_again_bounded`, with a sweep limit
    of 1 and an editor without cost:
    - `get_version` is refused (429) while another check of theirs runs;
    - it is then worked out once (`visible_issues` is called once);
    - it is served again from the cache inside a running check;
    - its sweep is the live one: the 1A+0C row only.
  - `test_a_publisher_without_cost_is_told_the_warnings_get_version_gives_it`: two new subtests for
    a publish-only profile (`price.view`, `contract.publish`), via the workspace and an existing
    caller. The warnings are None, and `get_version` has no `validation_report`.
  - `test_the_publish_audit_counts_the_warnings_a_viewer_without_cost_is_shown`: two identical
    drafts, published under a global policy that prices the CHD child at 50 % (one more negative
    total) and at 500 %. The stored reports hold 4 and 3 warnings. An editor without cost is shown 3
    both times, and the audit entry records 3 both times. Fail-first, on the code before that fix:
    `counted {50: 4, 500: 3}`, "4 != 3". This test was written after the others, when the audit's
    reach was checked (see Open).
  - Fail-first on the code before the fix (`5c3dfee` plus the tests): 4 tests, 5 failures and
    1 error.
    - Both refusal subtests failed: "…child 1 (INF) of TEX Test Resort-DLX 2A+1C…" != "…child 1
      (CHD)…".
    - Both publish-only subtests failed: the filtered rows, and `[]` is not None.
    - The bound test failed: "RateLimitExceededError not raised".
    - The no-error test errored: `UNEXPLAINED_REFUSAL` was missing, and the publisher had been
      told the tie.
- *Unit, 525 (523 + 2), `test_hidden_policy_ops.TestRefusals`:*
  - the reproduction, with G-INF INHERIT and MULTIPLY 0;
  - 160 generated rule sets. Each has a rule naming an unknown band, and most have two tied
    version rules, so every op is refused. Every combination of the hidden rules' ops is tried, and
    the message must be the same each time.
  - Against the old behaviour (`refusal_errors` patched to return the full check's errors): 19
    failures. The stored-sweep limit test also asserts `reruns_sweep`.
- *Beyond the committed seeds (a script, not committed):*
  - 1,500 generated sets (seeds 200–224), every one refused: no set was told differently under
    different ops. With the old message, 50 sets were.
  - 600 sets without a forced refusal (seeds 100–109): 189 were refused, none told differently.
    4 refusals got the no-error message; each was a tie between two hidden rules of one policy,
    which `policy_issues` keeps from going live.

**Verification (S16 re-review 5 follow-up, security and cost group).** Main `1575c8b` is contained,
so nothing was merged.
- *Unit:* 525 OK. ruff is clean.
- *Integration, all 40 modules, on the final code (`52fe929`),* migrated with the tree:
  - 866 tests: 865 OK (10 skipped) and 1 error.
  - The error is `test_system_status.test_an_old_fx_rate_warns_and_a_stale_one_fails`. The site date
    was a Saturday, and this test depends on the weekday; it is not this group's.
  - `test_pricing_workspace_api` passed 68, `test_existing_semantics` 13, the perf module 2.
  - An earlier full run on `0283f86`, before the audit count fix, gave 865 tests: 864 OK and the
    same error.
- *Upstream with the tree (`52fe929`):* eval harness 76/76, front-desk journey 13/13, banquet 101 OK.
- *Not run:* there is no frontend change, so no `tsc`, build, i18n or Playwright run. The frontend
  never reads publish's `warnings`.

**Open after the S16 re-review 5 follow-up, security and cost group.**
- *The audit trail shows contract-rate changes to anyone who may view reservations.* This is
  pre-existing on main `1575c8b` (ADR-053) and was checked with a probe that was not committed.
  - `admin.audit_log`, filtered by a reference (`reference_doctype`, `reference_name`), needs only
    `reservation.view` on the hotel. It returns each event's `new_value`.
  - A Reservations Agent, who has no cost capability, read these entries for a republished
    version:
    - the `contract.publish` entry's `collections.room_rules.changed`: `{"value": ["100",
      "123.45"]}`;
    - the draft save's `collections.period_rates.changed`: the same.
  - Changed occupancy rules, boards and offers of the version would show the same way.
  - Pricing-policy rules appear by key only: a revised policy is a new source, so its rules show as
    removed and added. A first publish lists row keys only.
  - Contract rates are cost (G-11). Who may read which audit values is for the owner to decide
    (ADR-053, ADR-056; GO_LIVE owner input 14).
- *Refused publishes are neither audited nor limited.* A refusal still says that the full check
  failed. Where the viewer's own check shows no error that no op decides, that can depend on a
  hidden op, and a probe that is not refused publishes the draft, which is audited (decision 1).
  A limit on refused publishes for callers without cost is possible if the owner wants one.
- *`get_version` can answer 429.* For a viewer without cost, while three of that viewer's checks
  run, it answers 429 on a published version whose stored sweep reached its limit and that this
  process has not worked out yet.
- *The report cache is per process.* Each worker works a report out once and keeps at most 256.

**Final follow-up, workspace UX and keyboard group (2026-09-26).** The workspace findings still open
after the final verification and the sixth review: the single-use switch that can change a price
silently (low in the review; treated as must-fix, because a published price moves without a word),
"+ Period" out of reach of the keyboard, the single-use row against special combinations and the
Keyboard shortcuts table (medium), the side panel narrowing the shell's top bar, the focus after a
new period's dates and the German "Zeitraum"/"Periode" (low), and the two intermittent failures of
the final verification (`pricing-workspace-matrix:107`, `pricing-workspace-rereview:208`). A first
agent on this group was stopped by a container restart; its uncommitted work (a DOM harness, the
single-use checks, the side panel, part of the focus change) was reviewed, kept where right,
finished and committed in pieces. Frontend only, plus one pure unit test; main `1575c8b` is
contained, so nothing was merged.

**Decision (final follow-up, workspace UX and keyboard group).**
1. *The single-use switch never changes what one adult pays (must-fix).* "Also when children
   travel" moves the row's rules between the whole 1+0 combination and Adult 1 of 1+*. The review's
   case: Adult 1 ×1 "Always wins" and single use ×0.8. As the whole 1+0 the combination replaces the
   total (1A+0C = 0.8 of the unit); as Adult 1 of 1+* the rule is a COMBINATION-level adult rule and
   loses to the OVERRIDE-level Adult 1, so 1A+0C paid the full unit after a switch the popover
   called value-keeping. `singleWriteRefusal` now also answers `"outranked"`: it writes the rule
   both ways (in the row's form, and switched with the row's other rules moved) and compares, per
   room and period, what prices one adult without children as `price_occupancy` resolves it (the
   whole-stay winner if it replaces the total, else Adult 1's winner, then a relative whole-stay
   rule; `engineRank` is `occupancy.specificity`, INHERIT defers, a tie of two values is the
   engine's ambiguity). Only ops and values are compared, never amounts. Any difference refuses:
   an Always-wins Adult 1 (of every room or one), a card's exact 1+0 Adult 1 in some period, a
   `*+0` whole-stay rule the old form outranked, a pricing policy's rule (the ladder passes
   `inherited_rules`; a rule served without its formula counts as one that prices, so the refusal
   does not depend on a hidden op), a room's switch under an All-rooms whole 1+0, and Always wins
   on both sides (the engine refuses the party). The check uses the op and "Always wins" chosen in
   the popover. The popover says why in six languages (`rates.occ.pop.refused_outranked`) and
   Apply waits, as for `card` and `relative`. Carrying `is_override` over instead was not taken: an
   Always-wins single-use rule outranks special combinations too, which changes other parties'
   prices; the refusal names the rule to change first.
2. *"+ Period" by keyboard with rooms and no period (medium).* It stays a Tab stop while the matrix
   has no period column (`cols` is only All periods), and `focusHeaderLane("top")` falls back from a
   column without a header control (All periods) to the next column control after it, so ArrowUp
   from All periods reaches "+ Period" (with periods, the first period's menu).
3. *The single-use row names a special combination that prices one adult (medium).*
   `combinationNotes` gives the single-use row's cells the precedence note where a card's whole-stay
   or Adult 1 rule prices the row's party in that room and period (children = any includes none):
   everywhere the row has no rule of its own, and where it has one, when the card's rule for the
   same slot ranks at or above it, or the card's other rule still applies (an Adult 1 under a
   relative whole 1+0, a whole-stay rule after "also when children travel"). An "Always wins" row
   rule has no note. Where such a card holds the cell's whole column (`cardCovers`: every room of
   the scope, that period), the cell reads "special combination" with the card's name, not "×1.00
   default (no single-use rule)"; where it holds only some rooms, the default stays and its tooltip
   says "except where a special combination prices one adult". The note names and links the card.
4. *The Keyboard shortcuts table fits its popover (medium).* One chip per key or gesture (the
   catalogue's ", "-separated keys), wrapping, in a fixed-layout table (keys 44 %). The chips are
   hidden from screen readers; each row is named by the keys as the catalogue writes them
   ("Ctrl+Shift+Z, Ctrl+Y Redo"), which `pricing-workspace-bulk` and `-rereview2` read.
5. *The shell's top bar keeps its width beside a side panel (low).* In the TEX shell a side panel
   starts under the bar (`html[data-tex-shell] [data-side-panel] { top: 3.5rem }` from 40 rem), and
   the bar takes back the page's panel padding (`margin-right: -28rem` / `-42rem` / `-56rem`), so
   the hotel selector, search and badges keep their places at 1280 and 1440 px.
6. *A new period's dates hand the focus on only when a key closed them (low).* Enter, Ctrl/Cmd+S
   or Escape focus the period's first cell at once; leaving the fields by a click or Tab leaves the
   focus where it went, and the page does not scroll back to the matrix. Checked in the browser: a
   click on a text inside the main region focuses the region itself (`main#tex-main` has
   `tabIndex=-1`), so the old refocus did not fire there; a click on a text outside it (the side
   navigation's group label, the top bar's background) left the focus on `body`, and the old code
   then focused the new period's first cell and scrolled the page back to the matrix.
7. *German says "Periode" throughout the workspace (low).* "+ Periode" named "Periode hinzufügen"
   (`rates.ws.period.add_label`, so the name contains the text), "Alle Perioden" for the grids'
   first column and the popovers' choice (`rates.ws.all_periods`), the lane help and the
   single-use popover's texts. The rule tables keep "Zeitraum" with their own keys.
8. *`pricing-workspace-matrix:107` (keys lost after Escape).* The cause was as the final
   verification suspected: `finish` closed the invalid editor and focused the cell a frame later
   (`focusAt` in `requestAnimationFrame`), so the keys typed before that frame reached `body`
   ("1.500" became ".500", or no editor opened). `focusCellNow` (ui/grid.ts) focuses at once and
   once more a frame later only if the focus was lost and no edit began; the matrix, the ladder and
   the boards grid use it (their editors' blur is guarded by `closing`, so nothing is committed).
9. *`pricing-workspace-rereview:208` (one header-lane ArrowDown step).* The trace
   (`pw-final/e2e2/failures`) shows Home at +0 ms and ArrowLeft 6 ms later; the room's menu was
   focused and the check passed; the failure screenshot has the focus in Family Suite · All periods.
   Home had asked a frame to focus the active cell (`focusActive`); ArrowLeft, before that frame,
   focused the room's menu; the late frame took the focus back to cell 0:0, and the next ArrowDown
   moved within the cells. `useGridNavigation` now focuses the cell a key moves to at once, and its
   frame refocuses the latest active cell only while the focus is in the cells or lost, never from a
   header control.

**Deviations (final follow-up, workspace UX and keyboard group).**
- *The engine pairing is through a fixture.* The frontend cannot run the engine: the node test
  writes each scenario's rows to `kamra/tex/tests/unit/parity_data/single_use_switch.json` and fails
  when the switch writes other rows; the Python test prices them. After a change to the switch:
  `UPDATE_SWITCH_PAIRS=1 npm run test:unit`, then the unit test.
- *The refusal is conservative.* It compares the winning rules' ops and values, not amounts, so a
  switch that would give the same amount through another op (×0.8 against 80 %) is refused too, as
  is one where a hidden policy rule defers.
- *The single-use row without a rule does not always read "×1.00 default (no single-use rule)"
  (§3.6.2).* Where a special combination prices one adult in the whole column, the engine default
  is not what one adult pays, so the cell reads "special combination" (with the card's name and
  note); the design's line assumes no card prices single use.
- *"Zeitraum" stays in the Price test's stage names and the engine's explanation* (`rates.pt.*`,
  `rates.explain.*`, shared with screens outside the workspace; a committed German Price test check
  reads them).
- *The first agent's work:* kept as written: the DOM harness, `focusCellNow`, the lane fallback,
  the side-panel CSS, the `byKey` flag and the `"outranked"` model with its unit tests; added: the
  popover's message and inputs (op, Always wins, inherited rules), the ladder's "special
  combination" reading, the engine-paired test, the German wording and the Playwright checks.

**Tests (final follow-up, workspace UX and keyboard group).** Fail-first output is from the code
before each fix (the pre-follow-up frontend `830b79f` for Playwright).
- DOM harness `tests/dom/lanes.spec.ts` (10): ArrowUp from All periods reaches "+ Period" and adds
  P1, and the first period's menu with periods; Home then ArrowLeft before the frame keeps the room's
  menu; arrows and Shift+arrows with frames held; the shortcuts popover in six languages. Fail
  first: 10 of 10 fail (`"0:0"` instead of "Add period"; `"0:2"` instead of `"0:0"`; sideways
  scroll 65 / 243 / 165 / 163 / 112 / 70 px in en / de / pl / ru / tr / ro).
- Unit `workspace-occupancy.test.ts` (3 new, 2 changed) and `single-use-switch.test.ts` (2):
  refusals for the reviewer's case and the other outranking rules, the note and `cardCovers`; the
  20 scenarios' rows. Fail first: 5 tests fail (`null` instead of `"outranked"`, no note).
- Unit (Python) `test_single_use_switch` (4): every allowed switch prices 1A+0C as the rule written
  without it (and as before, for a switch of form only) in 3 rooms × 4 periods; every refused one
  writes nothing and would have changed a price. Fail first (rows written by the code before):
  12 failures, e.g. the reviewer's case 56.00 before, 70.00 after the switch.
- Playwright `pricing-workspace-final.spec.ts` (9): keyboard only "+ Period" → P1 → a price;
  the dates left by a click; typing after Escape with frames held in the matrix, ladder and boards;
  the top bar at 1280 and 1440; the refused switch; the single-use row with a card of all rooms and
  of one room. Fail first: 9 of 9 fail on `830b79f`. `rereview` German "+ Periode" and `rereview3`'s
  single-use cell under a card updated (the expectation was the wrong reading).

**Verification (final follow-up, workspace UX and keyboard group).** On `7e3b857` (docs after it);
main `1575c8b` is contained, so nothing was merged.
- *Unit:* 529 OK (the 4 new), ruff clean. `npm run test:unit` 316/316, `npm run test:dom` 42/42,
  `tsc -b`, `npm run build` (bundles not committed) and `npm run i18n:tex` clean.
- *Playwright* on this group's own servers (bench :8016 with the tree, `serve_tree.py`, an RQ
  worker, Vite :5186; the site migrated with the tree in each lock hold; the pre-follow-up frontend
  `830b79f` on Vite :5187 for the fail-first runs):
  - `pricing-workspace-matrix` 10 runs in a row: 8/8 each; `pricing-workspace-rereview` 10 runs in
    a row: 11/11 each (on `501721c`; the later commits change the shortcuts popover and tests only).
  - `pricing-workspace-final` 9/9; `pricing-workspace-bulk` and `-rereview2` 24/24 after the
    shortcuts rows got their names back (the first full run on `501721c` had failed those two
    checks, 105 of 107).
  - Every `pricing-workspace*` spec on `7e3b857`: 107/107, the acceptance at 41 clicks, 0 section
    switches, 0 modal dialogs.
- *Integration, all 40 modules, on `ee03be1`* (migrated with the tree): 866 tests, 865 OK (10
  skipped) and 1 error, `test_system_status.test_an_old_fx_rate_warns_and_a_stale_one_fails` (the
  site date was a Saturday; the weekday-dependent test of the final verification, not this group's).
  `test_pricing_workspace_api` 68, `test_existing_semantics` 13, the perf module 2 all OK.
- *Upstream with the tree:* eval harness 76/76, front-desk journey 13/13, banquet 101 OK.

**Open after the final follow-up, workspace UX and keyboard group.**
- A green whole run still needs the FX test on a Wednesday-to-Friday site date (or the test fixed)
  and the `entry-branding` navigation tests on a site without the accumulated E2E drafts (or a
  version list that leaves archived contracts out); neither is the workspace's.
- As before: the §3.18 one-screen fit of the owner example with the ladder, one shared inline-edit
  hook for the three grids, O1–O5 (owner input 13).

**Final follow-up, main-side group (2026-09-26).** The final verification's failures outside the
workspace, which kept "every suite green" from this branch as from main: the FX status test's
weekday, the version tables' cap on the shared site's archived E2E drafts, `entry-branding`'s
placeholder-row race, and the disposable site's missing config with the funnel purge's lock wait
there. Main `1575c8b` is contained, so nothing was merged.

**Decision (final follow-up, main-side group).**
1. *The FX status test pins the site's day and says what every weekday gives.* The product is
   right (ADR-047): the warning counts business days (more than `FX_WARN_BUSINESS_DAYS`, 2), so a
   Monday morning before the fetch is no alarm; the failure counts calendar days (the policy's
   `max_age_days`). The test wrote a rate three calendar days old under a 4-day policy and expected
   the warning, which exists only from Wednesday to Friday (three days then hold three weekdays).
   It now pins `system.status`'s "now" to each day of the coming week, Monday to Sunday (a subtest
   and a savepoint each), under a 7-day policy, and asserts for each day: no rate fails
   `fx_missing`; 8 days old fails `fx_stale` (8 of 7); 7 days warns `fx_old` (the policy's age
   itself is not stale); the newest date with 3 business days warns with its calendar age (3 from
   Wednesday to Friday, 4 on Saturday, 5 from Sunday to Tuesday); the oldest date with 2 business
   days says nothing; today's rate says nothing. The per-weekday ages are a table written by hand,
   not `business_days`; the same table is a pure unit test (`test_system_checks`).
2. *The current version tables leave out archived contracts, and the cap counts only versions
   with a row in the table.* `lists.version_rows` counted the Draft and Published versions of
   archived contracts as current. The shared site's hotel had 2,498 archived contracts' drafts and
   252 of their Published versions (E2E runs archive what they make), each changed after every
   live version, so the 2,000-version cap was nearly all theirs (1,979 of the 2,000, checked on
   the site): the Price periods and Occupancy rules tables showed archived rows, and Rate plans none
   (none of those 2,000 has a rate plan), `truncated` for every user. "current" is now the Draft and Published versions of the
   contracts that are not archived (an archived contract sells nothing and is drafted no more);
   "all" and a version status still list the archived contracts' versions. The cap counts only
   versions with a row in the table (`EXISTS` on the child table; an empty version shows nothing),
   read the most recently changed first; `truncated` still says when either cap cut something. The
   tables' "current" hint says archived contracts are under All versions (six languages).
3. *`entry-branding` counts and opens the rows of the lists' answers.* While a list loads,
   `DataTable` shows five placeholder rows without a click handler; the step counted them
   (`rows.count() > 0` held before any answer) and clicked the first one about 70 ms before
   `lists.version_rows` answered (the final verification's run 1). The step now waits for each
   list's answer (`lists.versions`, or `lists.version_rows` with its section), checks that it has
   rows, then waits for rows with `tabindex="0"` (a data row that opens its version) and requires
   every row to be one before it clicks. No product change: a placeholder row is correct while
   loading.
4. *The disposable site is configured as the shared one, and the funnel purge deletes each old
   event alone by its primary key.* `disposable_test.sh` (a scratch script outside the repo) now
   sets `developer_mode` (a payment's `http://` return URL is allowed as on a development site)
   and, where the new site has none, an `encryption_key` (a Fernet key, as Frappe makes one;
   `SigningKeyMissing` otherwise), and records both in its summary. There
   `test_new_events_never_wait_for_a_purge` still waited out its lock (1205): the purge deleted a
   batch in one statement, `DELETE … WHERE name IN (…)`, and on a funnel where the batch is most of
   the table the optimizer reads that as a scan, which locks every row and gap until the batch
   commits. Reproduced on a copy of the table (MariaDB 10.11, REPEATABLE READ; a second session
   inserting with a 2 s lock wait): 5 rows, 3 deleted: plan `ALL`, every primary-key record locked
   (`X`), the insert times out; 500 rows, 400 deleted: `ALL`, times out; 1,000 rows, 500 deleted,
   and 10 to 100 rows, 3 deleted: `range` on `PRIMARY`, no wait. `FORCE INDEX` in the multi-table
   form did not help on the small tables (still `ALL`). An equality on the primary key is read
   through it at every size (`range`, 1 row), so `PURGE_EVENT` deletes one event per statement
   (`PURGE_EVENTS` is gone); a new or quiet site's first purge no longer holds the funnel for its
   batch. The shared site's funnel (5,680 rows) never showed it, which is why only the near-empty
   disposable site did.

**Deviations (final follow-up, main-side group).**
- *The FX test's policy is 7 days, not 4.* A rate three business days old is 5 calendar days old
  from Sunday to Tuesday, stale under 4 days: only a 7-day policy lets every weekday show the
  warning, the failure, the quiet case and their boundaries. The 4-day case is still in the unit
  tests (`test_old_warns_stale_and_missing_fail`).
- *`lists.versions` (Contract versions) is unchanged.* It lists every version by default (its
  subtitle: "what sells now, what is scheduled, drafts and history"), the 500 most recently changed
  first, archived contracts' included, and says when it cut; its status filter is explicit. On the
  shared site its first 500 are archived E2E drafts; the E2E step needs only rows.
- *The withdrawal's `FORGET_CASES` and `FORGET_EVENTS` keep `name IN`.* They have the purge's
  shape, but they name one guest's events, never most of a live funnel, and
  `test_crm_privacy_review` passes 28/28 on the disposable site; left as is (open below).
- *The purge runs one statement per event* (500 per batch): slower than one statement, and bounded
  by the batch; it is a daily job.

**Tests (final follow-up, main-side group).** Fail-first output is from the tests on the code before
the fixes (`a18a3b5`: the new tests, the old product).
- Integration `test_system_status.test_an_old_fx_rate_warns_and_a_stale_one_fails` (rewritten, 7
  pinned days) and unit `test_every_weekday_warns_after_two_business_days`. Fail first: the old
  test errors on this Saturday site date (`TypeError: 'NoneType' object is not subscriptable`, the
  final verification and every run after it); its 3-day rate under the 4-day policy reads `ok`, not
  `warn`, on Saturday, Sunday, Monday and Tuesday (`checks.fx_check` for the pinned week). The new
  test passes on the old product (the product was right).
- Integration `test_entry_branding.test_archived_contracts_never_crowd_the_current_versions_out`:
  2,020 archived contracts' versions (one Published) changed after every other version, each with a
  period, an occupancy rule and a rate plan; the current table of each section lists the live
  version and a draft, nothing archived, the most recently changed first, not cut; "all" lists the
  2,000 most recent, archived ones, in that order, and says it cut. Fail first: 3 failures, one per
  section, `Items in the first set but not the second: 'CTR-03756-V1', 'CTR-03757-V1'` (the live
  version and the draft missing).
- Integration `test_crm_third_review.test_each_old_event_is_deleted_alone_by_its_primary_key`:
  each DELETE of the purge names one event and its plan reads one row through `PRIMARY`. Fail
  first: `AssertionError: 1 != 3 : one DELETE per event` (`DELETE … WHERE name IN %(names)s` with
  three names). `test_the_purge_reads_through_an_index_and_deletes_by_primary_key` explains
  `PURGE_EVENT`. On a disposable site with the new config and the old product,
  `test_new_events_never_wait_for_a_purge` errors with 1205 (20 of 21 pass, the other 7
  second-connection tests included).
- E2E `entry-branding.spec.ts` "navigation: every new sub-section …" waits for the answers. A
  scratch proof (not committed; the lists' answers held back 2.5 s by `page.route`): the old step,
  marked expected to fail, failed (it clicked a placeholder row and the page stayed on the list);
  the new step passed.

**Verification (final follow-up, main-side group).** On `59ef45a` (the group's code; docs after it);
main `1575c8b` is contained, so nothing was merged.
- *Unit:* 530 OK (the new weekday table), ruff clean. `npm run test:unit` 316/316,
  `npm run test:dom` 42/42, `tsc -b`, `npm run build` (bundles not committed) and
  `npm run i18n:tex` clean.
- *Integration, all 40 modules* (migrated with the tree, from an archived copy of it): 868 tests,
  all OK, 11 skipped: the 3 whole-site patch tests, the 7 second-connection tests of
  `test_crm_third_review`, and `test_entry_branding`'s git-checkout test (the copy is not a
  checkout); from the worktree `test_entry_branding` is 35/35, none skipped.
- *Disposable site* (`disposable_test.sh` with the new config: made, tested, dropped):
  `test_crm_third_review` 22/22 (none skipped), `test_patches` 33/33, `test_crm_privacy_review`
  28/28.
- *Upstream with the tree:* eval harness 76/76, front-desk journey 13/13, banquet 101 OK.
- *Playwright* on this group's servers (bench :8021 with the tree, `serve_tree.py`, an RQ worker,
  Vite :5191; the site migrated with the tree; a second factor for one test user and a
  `tex_source_url`, put back afterwards): the scratch race proof 2/2 (the old step failed as
  expected, the new one passed); `entry-branding.spec.ts` five runs in a row, 10/10 each, "every
  new sub-section …" (238) and "a restricted user …" (357) included.

**Open after the final follow-up, main-side group.**
- A whole green run of every suite on one commit (the whole Playwright suite included) is still to
  be recorded before the workspace can be COMPLETE; this group ran the suites above.
- In "all", an archived contract's active version still reads "live" (and a suspended one's too):
  `_state` does not look at the contract's status, and there is no "archived" state to show
  (pre-existing).
- The withdrawal's `FORGET_CASES` / `FORGET_EVENTS` name their rows with `name IN`; on a funnel
  where one guest's rows are most of the table (a new site) the optimizer could read them as a
  scan, as the purge's was. Not reproduced (`test_crm_privacy_review` 28/28 on the disposable site).
- `lists.versions` lists archived contracts' versions by default (by design); on the shared site
  its 500 most recent are archived E2E drafts.

## ADR-062 Payment holds and late payments (audit K-2, 1b)

- The TEX Booking row decides a hold. Expiry locks the booking, then its rooms (name order), and
  cancels them together; the PMS job never touches TEX rooms. A never-confirmed booking with a
  room cancelled on purpose keeps waiting for its payment with the rest (B1).
- An attempt keeps the rooms until its own deadline: a card's at most 5 min (3DS) past the hold, a
  transfer's the hold; a new one starts before the hold ends or while one is open (C1); stale ones hold none. A payment
  link sent for the booking holds its rooms for the link hold (default 24 h), never past the end of the
  arrival day, and expires with it (B6, D7); a cancelled link's extension goes back, never below the
  other links' expiry (open or paid) nor now + the booking's own hold (E3).
- A transfer booked on the web holds 24 h (a hotel may change it), at most 2 rooms; staff 48 h (C2, user).
- Money for a booking (user decision, B3): a) its rooms still held for it, however late: confirm
  at the locked price — its rooms, extra units and coupon uses are still held for it, so nothing is
  judged again; b) late money, rooms given back and still free: `Action Required`;
  c) late money, rooms sold: `Refund Queued` when the gateway refunds via TEX, else `Action Required` — and
  `Action Required` whenever the gateway states no capture time on a booking that ended by its expiry (D-7, P1-1: it
  may have been paid in time; the hotel decides, never an automatic refund). In b)/c)
  the charge stays Succeeded, off the booking, with today's availability and price in its note; a
  booking that expires with money on it puts that money in `Action Required`, always (B2).
- Late is by the gateway's clock (`captured_at`, p53; B4, D3): the virtual POS's `EXTRA.TRXDATE` (Istanbul
  time) and the mock's server clock, ±5 min; a transfer's value date by day (the hold's last day is in time);
  iyzico and Sipay state none: judged when the news arrives. Paid in time, news after the expiry (D4, user):
  revived and confirmed only when its rooms are free, this money plus what it held at the expiry covers
  `amount_due_now` and its limited extras and coupons are still free; else, or when the guest has another
  live booking for the stay, `Action Required`, team told, no auto refund.
- Locks: money coming in (callback, link, transfer, manual, allocation, revival): link → charges → booking →
  rooms; the expiry job and money going out (refund phase 2, outside TEX, finish/resolve): booking, then charges.
- A booking never confirmed owes no cancellation penalty (a room still carries the basket discount the
  others keep, E1) and nothing once it ends; money on its way is never kept as a fee (C6, user).
- Seen (B5): status check `payments.reconciliation` with ages; e-mail to the hotel and the payer.
- *Fraud review (D-8, O-18, Part 2E-2).* A payment the gateway holds in its fraud review (iyzico fraudStatus 0; absent or
  unknown is read so, never approved on doubt) keeps its booking waiting: its rooms are held once for the link hold (never
  past the arrival day, never shortened, not extended again), audited `payment.under_review`; a 1 then confirms it. A
  rejection (-1) fails it, ends that hold (back to the deadline before it, or the booking's other open charges'), is
  audited `payment.fraud_rejected` and tells the team; TEX holds none of its money, so nothing goes to reconciliation.
- *Refused after the hold (P1-9, Part 2E-2).* A retry or a link refused because the hold is over, with no attempt open,
  expires the booking and commits before the refusal (its rooms go at once); a link inside a card's 3-D Secure margin
  is still sent; a transfer is never started past the hold.

## ADR-063 MariaDB snapshot isolation stays OFF
**Context.** From 11.6.2 MariaDB turns `innodb_snapshot_isolation` ON (CI and the local package run 11.8). A locking
read or UPDATE of a row changed after the snapshot then fails with 1020 and rolls back, so a booking that waited for
the last room's lock (ADR-032) got an error instead of "sold out": 5 of 8 `test_concurrency` tests red. No double sale.
**Decision.** OFF everywhere. The double-selling guard is TEX's explicit locks and the locked recount, never snapshot
isolation; the code and every race test assume OFF (10.11's default).
- CI sets and checks it; the Docker package passes `--innodb-snapshot-isolation=0`; NATIVE.md's cnf carries
  `loose-innodb_snapshot_isolation = 0`; `setup-local.sh` warns when it is ON.
- Every request and job sets it OFF for its connection (`kamra.tex.ops.snapshot_isolation`, `before_request` /
  `before_job`): a managed host may not allow the server setting. No variable (MariaDB < 10.6.18): nothing to do.
- The status page's platform check `db.snapshot_isolation` fails while `@@GLOBAL` or `@@SESSION` is 1.
**Consequences.** ADR-032's retries cover only the endpoints wrapped in `retry_on_deadlock`. Working with it ON would
need retries around about 20 endpoints, callbacks, jobs and Frappe's naming-series inserts, and series locks held
across a gateway call would still fail under load: not done.

## ADR-064 A nullable date filter says what NULL means (audit Part 2A)
**Context.** `frappe.get_all`/`get_list` compare a nullable Date/Datetime as `IFNULL(field, '0001-01-01')` for `<`/`<=`: a row
without the date is "long past" (NEW-1: the roll superseded every version without an end; points, grants and payment links
without an expiry expired). `>`/`>=`, `frappe.db.get_value`/`count`/`exists`/`delete` and query-builder comparisons are plain SQL.
**Decision.** A TEX filter comparing a nullable date says what NULL means in the same call: `[field, "is", "set"|"not set"]` or
the field with `is` in `or_filters`; kept readings are written out (an FX rate without a fetch time was always known). p56 gives
the versions the roll superseded the state their contract's later publishes would have given them.
- Guard `unit/test_nullable_date_filters.py` (AST): get_all/get_list/db.get_value/get_values/count/exists/delete/set_value/
  qb.get_query calls and `frappe.qb.DocType` comparisons in `kamra/`, field types from the DocType JSON; not raw SQL, Frappe-core
  doctypes or run-time doctypes; a filter or qb table it cannot read fails it; exceptions only in reviewed `ALLOWED`/`UNREADABLE`.
- Smoke `integration/test_scheduler_smoke.py`: each `kamra.tex.scheduler` entry point once over seeded data, clock frozen
  (freezegun, a kamra dev dependency), providers and network stubbed; a new "TEX …" Error Log or a broken seed fails it.
- The Playwright run keeps the site scheduler off: wall-clock jobs (hold expiry, alerts) would act mid-spec; the smoke test
  covers them deterministically.
- O-16 (user): a guest cancels online only before the arrival day, but may still start a change on it (`room_changeable`).

## ADR-065 The stored price and a booking's money (audit Part 2B)
- A room's stored price is `Reservation.tex_total_amount` (= `amount_after_tax`, `tex_currency`; set by hand: also
  `snapshot.override_amount`; `totals.total` is the engine's, to explain); a booking's, `TEX Booking(.Room)` amounts after
  `_refresh_booking_after_change`. Money reads the stored price; the snapshot gives only the terms, never the price.
- `required_now` = each live room's `amount_due_now` (its frozen policy, its stored price) + the cancelled rooms' fees.
- Extras add to the stored price; a price set by hand stays one. A later stay change needs staff's choice (keep it, or the
  change's price, audited); a guest cannot change such a stay online (D-9).
- A booking cancelled never confirmed holds no money: on its cancellation and on every refund outcome it goes to
  reconciliation (keys `cancelled:`, `refund:`, `refund-fix:`; `expired:` stays B2/D4's). Gateway, link and transfer money is
  allocated up to what the booking owes, the rest stays on the charge (`OVERPAID`); status check `payments.overpaid`.
- A link is in its booking's currency (D-10); money that came in another is recorded, kept off, `Action Required`, never undone.
- One link per idempotency key (unique; p57). One `payment_status` formula ("Refunded" included).
- Points ≤ min(total × max % − points on it, total − paid); a refund plan never pays points back as cash.
- A transfer is confirmed with the amount that came (the staff API requires its value date); one that no longer covers the
  deposit leaves the booking Pending, and it expires with its hold. New reconciliation reasons tell the team only.

## ADR-066 No lock is held through a gateway call (audit Part 2E-1, NEW-6)
- Invariant: no row, gap or naming-series lock is held while a gateway is asked over HTTP. Frappe keeps `tabSeries` rows
  (TEX-, RES-, REV-, AUD-, COM-, G-, PTX-) locked to the commit: across a 20–40 s checkout every write of the site waited.
- `start_payment`: (a) checks, the reused charge locked, `open_attempt`, the insert, a checkout lease (`checkout_started_at`,
  p68), the signed intent, commit; (b) `create_checkout`, nothing locking before or in it; (c) the charge locked by name,
  `provider_ref` written or merged, status never changed, its own lease cleared, commit; (c′) a gateway error: a new
  Pending charge Failed, a reused one superseded, committed before the caller hears.
- A lease younger than 100 s (5 × the gateway timeout: Sipay's 2 calls × (connect + read) + margin) makes another start
  of the charge `PaymentBusy`; a lapsed one is a start that died (its checkout never reached the guest): the charge is
  reused. Two first starts of one key: the unique key lets one insert, the other is `PaymentBusy`.
- A failed start leaves the booking on record (Pending Payment, mails sent, charge Failed, rooms ≤ hold + 5 min); the
  engine's retry replays it by its key and offers `pay_booking`. Before, all of it was rolled back.
- Commits (`_commit_step`) also end what the request did before (a booking just made); skipped in tests (one transaction).
- Payment paths lock link → payment(s) → booking → rooms (→ nights → extras → promotions → Guest), series rows last, never
  across a gateway call (ADR-062 "Locks"); Part 2F (P1-4) adds the full order and the reversed orders it fixes.
- *Addendum (Part 2E-2).* `complete_retrying` runs `complete` again on a deadlock or a lock wait timeout, after a full
  rollback (a timeout undoes only its statement), 3 tries, then raises the error (`mock_pay`'s own wrapper: ≤ 3 × 3);
  3 × `innodb_lock_wait_timeout` may outlast a web worker: the safety net is the re-verify job (P1-8).
- The re-verify job (NEW-2) is first in the 5-minute group: a plain SELECT of askable Pending charges (enabled account,
  no live lease), one charge per transaction, committed before the next gateway question (and between two questions
  of one charge when the first changed it). A request that committed a step (`_commit_step` counts it) is never run
  again on a deadlock: it rolls back and answers "very busy" (P1-8 e); a durable refund's or a guest change's commit,
  replayed by its key, does not count.

## ADR-067 Policy money: fixed amounts' currency, non-refundable policies, infants (audit Part 2C-1)
- *Refunds (Y-4).* A price is refundable only when its rate plan row and its cancellation policy both say so
  (`pricing/policy_money.refundable`); the engine writes that into every quote's `rate_plan.refundable`. No payload key:
  a payload frozen before is read so. A refundable row on a non-refundable policy is refused (`RATE_PLAN_REFUNDABLE`
  ERROR, every caller); a non-refundable row on a refundable policy with rules is a WARNING.
- *Policy currency (Y-3 A, D-1).* A payment or cancellation policy may name the currency of its fixed amounts; empty is
  the contract's. It is frozen (upper-cased) only on a policy with a FIXED deposit, rule or no-show; a payload without it
  reads the contract's (the K-1 pattern). A fixed policy in another currency is refused (`POLICY_CURRENCY`).
- *Conversion (done: Part 2E-1, Y-3 B, booking.py).* A fixed amount × the quote's recorded contract → sell rate,
  half-up to the sale currency's minor unit (`fixed_in_sell`); a snapshot whose policy has no currency keeps the amount as
  sold; a fixed penalty's basis names the conversion (`fx`). A fixed deposit is taken once per booking and payment policy
  (rooms of different FIXED policies each take their own), at its first room's rate, room by room in room order (room
  index, ADR-029), each room at most its own stored price: min(deposit, those rooms' total) (`deposit_shares`). p59 syncs
  the policies and reports what to review; no backfill.
- *No backfill (Y-3 B).* Every computation after the release takes the deposit per booking and policy; a pending booking's
  stored `amount_due_now` is not rewritten: only multi-room bookings with a fixed deposit differ, and theirs drops at the
  first refresh.
- *Infants (O-2, D-2).* Version setting `infants_count_as_children`: off, combination rules and max_children count
  children without infants and infants are numbered last; max_occupants follows `infants_count_as_occupants`. DocType
  default 1 (every existing version prices as before); a brand-new contract's first draft 0. Frozen only when 0.
- A sold stay keeps its snapshot's terms. Schema `tex.contract.v1`, no payload rewritten (G-73), parity corpus and ENGINE_VERSION unchanged.

## ADR-068 Promotion selection, codes and markup ties (audit Part 2C-2)
- *Usable first (O-1).* `promotions.select` refuses, after eligibility and before exclusive/group/stacking, what the room
  cannot use: a fixed amount without an FX rate (PROMO_NO_FX), on the total or the extras a value type other than PERCENT
  or FIXED_STAY, an extras discount without extras, a fixed booking discount on a later room (COUPON_REJECTED), with the
  reasons the apply step gave. Everything else is unchanged (parity corpus). The save refuses those type/scope pairs and a
  cost-stage offer that is not on the accommodation.
- *Group rule (D-3).* Of one group the highest priority applies, on equal priority the lowest id (the older promotion), not
  the better offer; texts say so in 6 languages; save and activation warn (`_warnings`, PROMO_GROUP_TIE) on a live tie.
- *Minimum basket (D-18).* Accommodation before discounts plus extras, of the booking's rooms it covers, in the promotion's
  currency; a minimum requires that currency.
- *Codes (O-31).* Compared by `code_key` (İ and ı are I); p60 rewrites stored codes and reports clashes, never payloads.
- *Members only (G-57).* Refused until a sale carries a membership signal.
- *Markups (G-53).* A REPLACE markup tying a live one (scope, priority, stay dates) is refused on activation (serialised);
  publishing from the contract page runs the workspace's board checks. `level()` and server defaults are unchanged.
- New save refusals apply to drafts and activations only; a live record stays archivable. ENGINE_VERSION, schema unchanged.
