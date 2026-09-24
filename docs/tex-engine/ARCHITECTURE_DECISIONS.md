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
  (`perm.query_conditions`, `has_permission`); an event with neither stays platform-level. The
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
    Communication) and the channel-manager push trigger on Reservation. `realtime.notify` publishes
    after commit and writes nothing.
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
- Tests: `test_crm_privacy_review` (27: H1 5, M1 2, M2 6, M3 and L4 4, L1–L8 8, p40 and p45 2; the patch
  tests refuse commits until their rollback, as the G-76 review asks) and changes to `test_crm_privacy`
  (the funnel allow-list and identity tests follow L5 and L6; p40's cases are written below the new
  controller; the p40 tests refuse commits; L9); the p45 registry entry in `test_patches`. On main
  `9215991` and its schema 26 of the 27 fail or error, each on its finding (the booking test: "booked:
  reported a rolled-back booking"; the others on the missing behaviour); p40's own paths (L9, coverage)
  pass; on `b074527` also 26 of 27. The three `test_crm_privacy` tests changed for L5 and L6 fail on the
  old code. E2E: `crm-profile.spec.ts` and the new `crm-merge.spec.ts` (a shared phone shown as a
  possible duplicate, merged from the profile) pass twice in a row on a server running this tree.

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

## ADR-060 The entry screens say TEX Engine and offer the source; "/" leads to the admin app or sign-in; the navigation carries R-35's sub-sections
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
  - The guest booking engine shows no such link: it is white-labelled per hotel. Whether and
    how guests are offered the source is an owner decision.
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
  - the guest-facing source offer (owner decision);
  - `tex_source_url`, or a public repository, kept reachable (owner).
