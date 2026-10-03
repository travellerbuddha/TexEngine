# TEX Engine — Migration Plan

Principles (R-56): preserve usable data, one patch per schema change, safe transforms,
preserve IDs, keep compatibility, test the migration path, never casually delete data.

## 1. Mechanics
- Schema: DocType JSON under `kamra/tex_*/doctype/` (new modules registered in
  `kamra/modules.txt`) and field additions to existing Kamra DocTypes' JSON.
  `bench migrate` syncs them before the patches run (`[post_model_sync]`).
- Data: patches under `kamra/patches/tex/`, listed in `kamra/patches.txt` in number order. Frappe
  runs each once and writes its Patch Log row after it succeeds.
- A patch must be safe to run again. A failed migration is retried from the start of the patch
  that failed, and an operator can force a patch (`bench run-patch --force`). So:
  - every step is idempotent;
  - a step that converts data or grants a capability once, at the upgrade that brings it, checks
    `kamra.tex.setup.ran_before(__name__)`. A forced re-run then never undoes what administrators
    changed since (ADR-058).
  - `ran_before` reads the Patch Log as Frappe does (ADR-058 review, H1):
    - a row `skipped` by `bench migrate --skip-failing` is a failed attempt, which Frappe runs
      again, so that run is a first run;
    - a patch line re-issued with a suffix (`<module> #<date>`) counts as run.
- A patch never changes a published contract payload or its hash, nor a sold stay's amounts,
  currency, commercial record, snapshot, revisions or price lock.
- A patch never guesses a tenant, a market or a currency. When it cannot tell, it reports the
  record and leaves it for an administrator.
- A report a patch writes for the owner (an audit event) is written once per record and values.
- No destructive DDL. Legacy columns stay; TEX fields are additive (`tex_` prefix on existing
  DocTypes to avoid collisions with upstream).
- Tests: every patch has a behaviour test and is covered by `test_patches` (see §4).

## 2. Patches

T1–T10 are the original migration tasks. p38 (restriction scope, G-48) came from a parallel branch. T5 was not needed (TEX boards are contract-level codes
RO/BB/HB/FB/AI/UAI, independent of legacy Meal Plans). T8 is the opt-in API
`kamra.tex.api.contracts.legacy_draft` (`kamra/tex/commercial/legacy.py`): a Draft "Legacy BAR"
contract per hotel from its Room Type prices and Seasons, never auto-published. Numbers p26, p30,
p32, p41–p44 and p67 were never released.

"Once" means a forced re-run skips that step (§1). "Tested" names the behaviour test. Every patch
is also covered by `test_patches.TestEveryPatch`: a second run changes nothing, sold prices and
payloads are untouched, and the chain runs on an empty site. `TestUpgradeFromKamra` runs the
whole chain on a Kamra database.

| Patch | What it does | Runs again | Tested |
|---|---|---|---|
| `p01_foundation` (T1–T3) | Adds the `User Permission.tex_managed` custom field. Seeds the permission profiles, markets and sales channels, and the TEX Settings defaults. Puts every hotel without a group in one: the Default Enterprise and Default Hotel Group when there is no enterprise, else the only group of the only enterprise; never on a guess (several tenants: reported). Shows the legacy PMS when it is in use. | data steps once (a re-run ensures the custom field only) | `test_patches.TestP01Foundation` |
| `p02_access_grants` (T4) | Makes property access explicit: a manual User Permission becomes a Hotel grant, and a user with a Kamra role and no restriction gets a grant per hotel ("Scope Only"). Then switches strict tenancy on. | once | `TestP02AccessGrants` |
| `p03_indexes` (T10) | Creates the composite indexes of `setup.TEX_INDEXES` that are missing. | idempotent | `TestP03Indexes` |
| `p04_lock_legacy_prices` (T9) | Price-locks what the legacy engine sold that still stands (Confirmed, Checked In, Checked Out, No Show; pricing source Legacy) at its amount. | once | `TestP04LegacyPriceLock` |
| `p05_vouchers_to_promotions` (T6) | Copies each legacy Discount Voucher to a Draft TEX Promotion (code, validity, limits, usage count; `legacy_voucher`). The voucher is kept. | idempotent (once per voucher) | `test_migrations_notify.TestLegacyMigrations` |
| `p06_experiences_to_extras` (T7) | Copies each legacy Experience to a TEX Extra (unit price, category; `legacy_experience`). The Experience is kept. | idempotent (once per experience) | `test_migrations_notify.TestLegacyMigrations` |
| `p07_forget_payment_link_urls` | Clears payment-link URLs, which carried the bearer token (ADR-017). | idempotent | `TestSmallPatches` |
| `p08_confirm_unpaid_capability` | Gives `reservation.confirm_unpaid` to the seeded profiles that hold it (ADR-025). | once | `TestCapabilityPatches` |
| `p09_guest_stats_completed_stays` | Recomputes guest stats: completed stays (sold, not cancelled or no-show, checked out) and the lifetime value in the guest's main currency; a legacy stay's currency is its hotel's. | idempotent | `TestP09GuestStats` |
| `p10_scrub_link_return_urls` | Drops the payment-link token from transactions' return URLs (G-10). | idempotent | `test_security_regressions.TestPaymentLinkTokens` |
| `p11_allocation_idempotency` | Syncs TEX Payment Allocation (idempotency key, G-14). | schema only | `TestSmallPatches` |
| `p12_effective_dated_extras_and_taxes` | Makes extras live first revisions and gives `tax.edit` to its profiles, both on the first run only. Gives each TEX hotel a tax policy with the taxes it sells with today (G-20). | extras and capability once; policies idempotent | `test_migrations_notify.TestEffectiveDatingMigration`, `TestCapabilityPatches` |
| `p13_extra_inventory` | Limited extras: stays already sold hold their units, and the day counters are rebuilt from the ledger (G-19). | idempotent | `TestP13ExtraInventory` |
| `p14_post_booking_extras` | Gives extras without an order cut-off one of 0 hours; adds the ADD_ON revision basis (G-22). | idempotent | `TestSmallPatches` |
| `p15_booking_hosts` | Booking domains are host names; a domain with a path is un-verified (G-21). | idempotent | `test_custom_domains.TestBookingHostMigration` |
| `p16_crm_segments` | Seeds the CRM presets; gives each segment its enterprise when the site has one (G-23). | idempotent | `test_crm_segments.TestSegmentMigration` |
| `p17_loyalty_admin` | Gives `loyalty.edit` to its profiles and turns a max-redeem share of 0 into 100 (0 now means "cannot redeem"), both on the first run only. Makes blackouts apply to both; fingerprints earlier earnings (G-24). | partly once | `test_loyalty_admin.TestLoyaltyMigration`, `TestCapabilityPatches` |
| `p18_channel_distribution` | Moves connection API keys to the encrypted store; gives outbox rows a kind; marks channel-manager reservation events Dead; gives the channel capabilities to their profiles on the first run only (G-69). | capabilities once | `TestP18ChannelDistribution`, `TestCapabilityPatches` |
| `p19_payments_go_live_check` | Reports each payment account that may not take new money, with its open charges listed by name (audited once per report). Changes nothing (G-67). | report once | `test_security_regressions.TestGoLivePaymentsReview`, `TestReportingPatches` |
| `p20_guest_change_requests` | Syncs TEX Guest Change Request and the Property setting for a cheaper change (G-45). | schema only | `TestSmallPatches` |
| `p21_contract_header_lock` | Gives drafts of published contracts the header's selling terms (G-50). | idempotent | `test_critical_journey.TestContractHeaderLock` |
| `p22_payment_api_key_password` | Moves payment-provider API keys to the encrypted store (G-83). | idempotent | `test_security_hygiene.TestSecurityHygieneG83` |
| `p23_system_status_alerts` | Gives `system.monitor` to its profiles on the first run only; links queued guest mails to their e-mail queue row; syncs their status (ADR-047). | capability once | `TestP23MailStatus`, `TestCapabilityPatches` |
| `p24_g83_review` | Makes public HTML/script files private; reports other public active content and invalid booking-site images (audited once); masks API keys in the change history (G-83). | report once | `test_security_hygiene.TestSecurityHygieneG83Review`, `TestReportingPatches` |
| `p25_contract_header_snapshot` | Versions frozen before G-50 take the header's selling terms; reports each contract whose header differs from its live payload (G-50 review). | idempotent | `test_critical_journey.TestContractHeaderLockReview` |
| `p27_inventory_cutoff_release` | Allotment cutoff 0 and negative release days 0; reports release days above 365 (G-49). | idempotent | `test_inventory.TestAllotments` |
| `p28_guest_change_refund_rows` | Names the refunds each guest change made (G-45). | idempotent | `test_self_service_money.TestFourthReview` |
| `p29_channel_binding` | Gives `price.any_channel` to the seeded admin and revenue profiles and to custom profiles that publish contracts (G-41). | once | `test_channel_binding.TestGrantsAndProfiles`, `TestCapabilityPatches` |
| `p31_g41_review` | Reports booking sites on a non-web channel (audited once); removes the mirrored rows of ended grants (G-41 review, G-94). | idempotent | `test_channel_binding.TestBookingSitesSellOnTheWeb` |
| `p33_audit_scope` | Gives group and enterprise grant events their group or enterprise and the hotels they reach (G-74). | idempotent | `TestSmallPatches` |
| `p34_redemption_released_at` | Dates each released coupon use from its last write (G-51). | idempotent | `TestSmallPatches` |
| `p35_money_field_types` | Checks the 9-place decimal columns and every published payload's hash; changes nothing (G-72). | checks only | `test_money_fields.TestPublishedAndSoldTermsAreUnchanged` |
| `p36_g92_review` | Sets live the TEX hotels TEX already sold (a published contract or a TEX booking); any other TEX hotel is onboarding until an administrator sets it live (G-92 review, ADR-058). | once (a hotel set back to onboarding stays there) | `TestUpgradeFromKamra`, `TestP36GoLive`, `test_legacy_pricing_review.TestGoLive` |
| `p37_crm_privacy` | Removes funnel e-mail hashes kept without marketing consent. Masks the pricing internals and guest totals in the change history, keeping the values for platform administrators (`version.withheld` audit events, ADR-056 review). Lists the DocTypes whose role permissions were customised, to check who reads permlevel 1 (G-81, G-95, ADR-056). | idempotent | `test_crm_privacy.TestAbandonedPrivacy`, `test_crm_privacy.TestPricingInternalsOutsideTex` |
| `p38_restriction_scope` | Restriction cells gain a channel scope (Booking Engine, Call Center or both) and a booking window; the DocType sync adds the columns blank. Checks that every stored cell keeps its scope key (a key appends the channel scope only when set) and re-keys a wrong one (G-48, ADR-057). | idempotent | `test_restrictions.TestGridCells.test_p38_keeps_every_key_and_rekeys_only_a_wrong_one` |
| `p39_lookup_indexes` | Creates the composite indexes that replace the single-column ones on `Reservation.tex_booking`, `TEX Extra Allocation.reservation` and `TEX Communication.email_queue`, which Frappe's schema sync drops (ADR-058). | idempotent | `TestP03Indexes` |
| `p40_crm_privacy_review` | Makes abandoned cases anonymous where the profile no longer consents to marketing e-mail (profile, e-mail, phone; consent 0) and removes funnel e-mail hashes of profiles without that consent. Where a DocType with withheld fields has customised role permissions (Custom DocPerm), adds System Manager's permlevel-1 row, once, at the upgrade. Prints on every run, and audits once, any business role holding permlevel 1 of such a DocType (ADR-056 review). | idempotent; the permission row only on the first run (`ran_before`) | `test_crm_privacy.TestAbandonedPrivacy`, `test_crm_privacy.TestWithheldFieldPermissions` |
| `p45_crm_privacy_second_review` | Creates the indexes a consent withdrawal and the guest lookups read through (funnel `(email_hash, session_id)` and `(session_id, occurred_at)`, cases `(session_id, status)`, Guest `(email, tex_enterprise)` and `(phone, tex_enterprise)`); masks the contact fields and the links to a person in older Version rows of cases and funnel events without keeping a copy, and removes the copies of contact data kept before (`version.withheld`); gives loyalty entries their hotel (stay, booking, the program's hotel, or the one hotel of a group program where the adjustment's author may edit guests); withdraws every consent of profiles erased before, forgets their cases and funnel data and removes their history; clears the quote of anonymous cases (ADR-056 second review). | idempotent: each step touches only what is still to do | `test_crm_privacy_review.TestP45` |
| `p46_report_indexes` | Creates the composite indexes the reports read by: `Reservation` (property, check_in_date), `TEX Funnel Event` (property, occurred_at) and (site, occurred_at), from `setup.TEX_INDEXES` (ADR-059 review). | idempotent: only a missing index is created | `TestP03Indexes.test_p46_creates_the_report_indexes` |
| `p47_g64_site_slugs` | Reports booking sites named like one of the admin area's pages (`new`, `content`, `rooms`, `analytics`, `sites`; `booking_site.admin_slug`, audited once). Never renames a site: its name is its first slug, which guests, widgets and campaigns may use (G-64 review, ADR-060). | report once | `TestReportingPatches.test_p47_reports_sites_named_like_an_admin_page_once` |
| `p48_crm_privacy_third_review` | Creates the indexes of the third review (funnel `(occurred_at, session_id)` for the purge, loyalty ledger `(guest, program)` for a locked balance, and one per Link to Guest that had none: TEX Booking, TEX Communication, TEX Funnel Event, Folio, Security Deposit, Service Ticket, Lost And Found Item, Exchange Transaction, Venue Booking, WhatsApp Message). Marks profiles erased before `Guest.tex_erased_at` existed, from their `guest.erase` audit event or `anonymize_guest` Agent Action Log entry (the notes text alone is not proof: counted, printed, not marked), and finishes their erasure (consent, date of birth, gender, tags, preferences, identity fields; cases, funnel, bookings' booker fields, payment links, change history, merge copies), auditing `guest.erase` only where something was left (ADR-056 third review). | idempotent: each step touches only what is still to do | `test_crm_third_review.TestP48` |
| `p49_payment_attempt_deadline` | Syncs TEX Payment Transaction (`expires_at`) and TEX Booking (`payment_attempt_until`): a payment attempt has a deadline and keeps its booking's rooms until then. Existing rows stay empty (K-2a). | schema only | `TestSmallPatches.test_p11_p20_only_sync_their_doctypes` |
| `p50_payment_reconciliation` | Syncs TEX Payment Transaction (`reconciliation`, `reconciliation_note`): captured money that could not safely confirm its booking is kept in reconciliation. No earlier charge is put there (K-2b). | schema only | `TestSmallPatches.test_p11_p20_only_sync_their_doctypes` |
| `p51_hold_minutes_per_payment_method` | Syncs TEX Settings and Property: a hold per payment method (card as before, payment link 24 hours, bank transfer 48 hours), each with a per-hotel override. Gives the new settings their defaults when blank and keeps an administrator's value; no hotel gets an override (K-2d). | idempotent | `TestSmallPatches.test_p51_gives_each_payment_method_its_hold` |
| `p52_partly_cancelled_awaiting_payment` | A booking left "Partially Cancelled" while it waited for its payment (no room ever confirmed) waits for its payment again; one whose payment was taken is confirmed (audited); one whose hold is over expires with its rooms, owing nothing. A fee its cancelled room was charged is void. No e-mail (B1, audit 1b). | idempotent: a second run finds none | `test_hold_payment_race.TestPartialCancellation` |
| `p53_payment_captured_at` | Syncs TEX Payment Transaction (`captured_at`): a payment is late by the gateway's capture time, not by when its news reached TEX. Earlier charges are judged as before (B4). | schema only | `TestSmallPatches.test_p11_p20_only_sync_their_doctypes` |
| `p54_never_confirmed_leftovers` | Cancels each booking that was never confirmed and has every room cancelled ("Partially Cancelled"), owing nothing; the money it held goes to reconciliation for staff; `booking.leftover_cancelled` is audited; no e-mail (D2, audit 1c). | idempotent: a second run finds none | `test_hold_payment_race.TestNeverConfirmedLeftovers` |
| `p55_web_transfer_hold` | Syncs TEX Settings and Property: a bank transfer booked on the web keeps its rooms 24 hours (`hold_minutes_transfer_web`, with a per-hotel override). Gives the setting its default when blank (C2, audit 1c). | idempotent | `TestSmallPatches.test_p55_gives_web_transfers_their_hold` |
| `p56_open_ended_versions` | Gives back their state to the published versions without an end that the contract roll set Superseded by mistake: Published again, or ended or withdrawn as the later publishes decide; audited (`contract.version_restored`). Payloads, hashes and sold stays are untouched (NEW-1, ADR-064). | idempotent: a second run finds nothing | `TestSmallPatches.test_p56_gives_versions_the_roll_superseded_their_state` |
| `p57_payment_link_unique_key` | Runs before the model sync (`[pre_model_sync]`): each idempotency key stays on its oldest payment link, a later duplicate becomes `{key}:dup:{name}` (audited `payment_link.key_deduplicated`), an empty key becomes NULL; then the unique index can be added (O-38, ADR-065). | idempotent: a second run finds nothing | `TestSmallPatches.test_p57_keeps_one_payment_link_per_key` |
| `p58_pool_key_with_disabled_members` | Keys each inventory pool by its first room type by name, a disabled one included: the rows kept under the old key move to the new key, and the disabled member's stale rows are dropped. Prints counts only (Y-9, ADR-048). | idempotent: a second run moves nothing | `TestSmallPatches.test_p58_rekeys_pools_whose_first_member_is_disabled` |
| `p59_policy_currency` | Syncs the payment and cancellation policies (`currency` of their fixed amounts; blank = the contract's). Reports a fixed policy used in several currencies (`policy.fixed_currency_ambiguous`) and live or future stays sold in another currency than their contract's (`reservation.fixed_policy_currency`). Changes no row (Y-3 A, ADR-067, D-1). | report once | `TestReportingPatches.test_p59_syncs_the_policies_and_reports_fixed_amounts_to_review` |
| `p60_promotion_code_key` | Stores every promotion code by its O-31 key (`o31_key`: "wİnter" is WINTER; Ş, Ğ, Ü, Ö, Ç kept: C-12's folding came later, ADR-076, and a stored code is keyed again on every read). Reports a changed code whose key another promotion of the same hotel scope has (`promotion.code_clash`, audited once) (O-31). | idempotent | `TestReportingPatches.test_p60_stores_codes_by_their_key_and_reports_a_clash_once` |
| `p61_loyalty_lots` | Closes the loyalty lots that expired before the lot model (marked by the old job, or spent in full first-to-expire); points left of a lot are for the daily job. Prints counts only (Y-11, O-22, ADR-071). | idempotent: a second run closes none | `TestSmallPatches.test_p61_closes_lots_that_expired_before_the_lot_model` |
| `p62_expired_hold_flag` | Sets `Reservation.tex_hold_expired` on cancelled reservations whose hold ran out (the expiry note and no Cancellation revision), so reports and the CRM leave them out. Prints counts only (O-24, ADR-059). | idempotent: a second run flags none | `TestSmallPatches.test_p62_flags_holds_that_expired_before_the_flag` |
| `p63_versioned_passwords` | Masks every Password field (a child table's too, LO-29) in the change history (Version rows) of each DocType that has one. Prints the count only, never a value (O-37). | idempotent: a second run masks none | `TestP63VersionedPasswords` |
| `p64_agent_log_read_only` | Where the Agent Action Log has Custom DocPerm rows, every role but System Manager keeps read, report, export, print and e-mail only; where it has none, nothing is done (Y-12). | idempotent | `TestP64AgentLogReadOnly` |
| `p65_agent_log_hotel` | Gives each Agent Action Log row written before NEW-8 its hotel where one is known (`savings.hotel_of`); a row with none stays platform level. Prints counts only (NEW-8). | idempotent | `TestP65AgentLogHotel` |
| `p66_cost_doctypes_system_only` | Where TEX Contract Version, TEX Markup Rule or TEX Pricing Policy has Custom DocPerm rows, every role's row but System Manager's loses every flag, read included; the TEX API serves them by `price.view_cost` (G-97). | idempotent | `TestP66CostDocTypesSystemOnly` |
| `p68_payment_checkout_lease` | Syncs TEX Payment Transaction (`checkout_started_at`): a charge's checkout is asked of the gateway under a lease, with no lock held (NEW-6, ADR-066). | schema only | `TestSmallPatches.test_p11_p20_only_sync_their_doctypes` |
| `p69_quote_version_index` | Creates the composite index `tex_quote_version_open` (contract_version, status, expires_at) that a withdraw's locking read of the open quotes uses (O-13, ADR-069). | idempotent: only a missing index is created | `TestP03Indexes.test_p69_creates_the_quote_version_index` |
| `p70_manual_fx_rate` | Syncs TEX FX Rate (`property`: a manual rate is for one hotel; blank = every hotel, as before). Gives `fx.manual_rate` to the seeded profiles that carry it (O-12, ADR-069). | capability once (`ran_before`) | `TestCapabilityPatches` |
| `p71_market_integrity` | Syncs TEX Market (`residency_required`) and TEX Booking Site (`allowed_markets`). Makes the domestic market TR residents-only. Reports a booking site whose default market is TR (`booking_site.residents_only_default`, audited once) (O-8, ADR-070, D-5). | the TR rule once (`ran_before`) | `TestSmallPatches.test_p71_makes_the_domestic_market_residents_only_once` |
| `p72_market_refused_funnel_event` | Syncs TEX Funnel Event: its `event` gets the option `market_refused` (G-55b). | schema only | `TestSmallPatches.test_p11_p20_only_sync_their_doctypes` |
| `p73_ledger_booking_index` | Creates the composite index `tex_ledger_booking_type` (booking, entry_type) that a points return reads the burn rows by (LO-06, ADR-071 §4 addendum). | idempotent: only a missing index is created | `TestP03Indexes.test_p73_creates_the_ledger_booking_index` |
| `p74_outbox_order_index` | Creates the composite index `tex_outbox_ref_order` (connection, reference_name, status, creation) that the PMS outbox claim reads through (LO-10, ADR-015 addendum). | idempotent: only a missing index is created | `TestP03Indexes.test_p74_creates_the_outbox_order_index` |
| `p75_payment_last_reverified` | Syncs TEX Payment Transaction (`last_reverified_at`): the re-verification job asks the least recently asked charge first (LO-22, ADR-066 addendum). | schema only | `TestSmallPatches.test_p11_p20_only_sync_their_doctypes` |
| `p76_oauth_registration_off` | Switches Frappe's OAuth dynamic client registration off on a site installed before (new sites get it off at install). Deletes nothing; prints how many OAuth Clients a guest registered, the count only (Part 2Z, ADR-073). | once (`ran_before`) | `TestSmallPatches.test_p76_switches_frappe_oauth_registration_off_once` |

## 3. Compatibility shims
- `kamra.pricing.quote` remains for legacy callers (folio night posting, channel push, legacy
  desk). TEX reservations never use it (guard in `Reservation.apply_pricing`).
- `create_booking` keeps its signature; TEX bookings go through `kamra.tex.api.booking`.
- `/kamra/*` routes stay valid; `/tex/*` is the TEX alias; `/book` routes to the new engine when a
  `TEX Booking Site` exists for the property, else the legacy page.

## 4. Verification
1. Fresh install: `bench new-site` + `install-app kamra`. `after_install` seeds, and Frappe marks
   every patch as run.
2. Upgrade path: `test_patches.TestUpgradeFromKamra` builds a Kamra database in the test's
   transaction and runs the whole chain in order. It has legacy hotels in two currencies, users
   with and without a property restriction and a disabled one, legacy stays in six statuses, a
   voucher and an experience, and no TEX structures. It checks what the upgrade leaves:
   - one enterprise and hotel group;
   - seeded masters and profiles;
   - explicit access under strict tenancy;
   - the legacy stays locked at their amounts;
   - the copies;
   - guest stats in their hotel's currency;
   - the hotels onboarding;
   - a second run that changes nothing.
3. Every patch: `test_patches` (ADR-058):
   - (a) its behaviour test (the `BEHAVIOUR` registry, checked);
   - (b) a second run, at once or forced later, changes nothing;
   - (c) no published payload, hash or sold price changes;
   - (d) the chain runs on an empty site.
   Tests never run a patch's DDL: `sandbox()` stubs it, and a static test checks every test that
   runs a patch.
4. Safety on a shared bench (ADR-058 review):
   - Every migration test refuses commits until its own rollback, so a run interrupted with
     Ctrl-C (Frappe's `run-tests` commits on the way out) commits nothing.
   - The tests that empty the site or run every patch over it, including the upgrade test, run
     only on a disposable site (`tex_disposable_test_site` in its site config).
   - CI's site is made for the run.
   - On the dev bench, `/home/user/bench/scratch/disposable_test.sh <tree> <outdir> [modules]`
     creates a site, runs the modules and drops it. On the shared site these tests are skipped.
5. Upstream suites (eval harness, journey, banquet) stay green after migration.

## 5. Booking imports (switch-over from another PMS)

Two importers write reservations from another system: `kamra.migrate.preview_import` /
`run_import` (a CSV export, Setup → import) and `kamra.api.import_bookings` (JSON rows, API /
agent). ADR-028, ADR-052 and its review govern them.

**Columns (CSV).** Headers are matched by synonyms, whatever the vendor calls them. Required:
guest name, room type (code or name), arrival and departure dates. Optional: phone, e-mail,
adults, children, amount (grand total, total amount, amount after tax…), currency (currency,
currency code, ccy), status, channel. Dates are read day-first or month-first as detected
(`preset`: `auto`, `ezee` day-first, `cloudbeds` month-first). JSON rows use `guest_name`,
`phone`, `room_type_code`, `check_in`, `check_out`, `adults`, `children`, `amount_after_tax`,
`currency`, `channel`, `status`.

**Amounts are read strictly and never guessed** (`kamra.tex.importing`):
- The decimal mark is the last `,` or `.` when one or two digits follow it: "150,00" is 150.00,
  "1.250,50" and "1,250.50" are 1250.50, "10,500.50" is 10500.50.
- Thousands may be grouped by the other mark, spaces or apostrophes, in groups of three (or the
  Indian 2-2-3).
- A single separator followed by exactly three digits is ambiguous ("1.500", "1,500") and the row
  is refused. Give the file's decimal mark (`decimal` = "." or ",") and it is read.
- Currency symbols and codes in the cell (€, £, ₺, TL, ₹, Rs., USD …) are stripped and must match
  the row's currency.
- The row is refused, with the reason, for:
  - negative amounts, "-120" and "(120)" alike;
  - more decimals than the currency has;
  - anything else that is not an amount.
- `preview_import` lists each row's parsed amount and currency before anything is written.

**Currency.**
- At a TEX hotel every row names its currency: a Currency column, else the currency chosen for
  the whole import (`currency`). An unknown currency is refused.
- At a hotel outside TEX, amounts are in the hotel's currency, and a row naming another currency
  is refused.

**What a row becomes.**
- At a TEX hotel it is recorded as pricing source `Imported`, at the file's amount in its
  currency, never auto-priced. It is price-locked and audited (`reservation.import`), and the
  import needs `price.override` at the hotel. A live row (Confirmed, Checked In) needs an amount;
  a history row may have none.
- At a hotel outside TEX a row without an amount is priced by the legacy engine, as before.
- Each row runs in its own savepoint. It is imported whole or not at all, and a failed row is
  listed with its reason; a deadlock stops the whole import.
- History rows (Checked Out, Cancelled, No Show) are records: stored without live validation,
  holding no room.
- Checked In rows are checked as live stays (TEX inventory at a TEX hotel; the arrival may be
  past) and stamped Checked In.

**Afterwards.**
- A wrong imported amount or currency is corrected on the reservation page ("Correct imported
  amount", `crs.correct_imported_amount`). The correction needs `price.override` and a reason and
  is recorded as a revision and an audit event. It is refused once the folio has billed the
  nights.
- At check-out the legacy folio posts an imported stay's locked amount, split over its nights
  (tax included; G-96).
- A hotel joining TEX is onboarding until an administrator sets it live (`admin.set_hotel_live`;
  patch p36 set every hotel already in TEX live). Import before or after going live: the rows are
  recorded as Imported either way.
