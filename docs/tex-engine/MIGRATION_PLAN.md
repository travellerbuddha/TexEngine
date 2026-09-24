# TEX Engine — Migration Plan

Principles (R-56): preserve usable data, one patch per schema change, safe transforms,
preserve IDs, keep compatibility, test the migration path, never casually delete data.

## 1. Mechanics
- Schema: DocType JSON under `kamra/tex_*/doctype/` (new modules registered in
  `kamra/modules.txt`) and field additions to existing Kamra DocTypes' JSON.
  `bench migrate` syncs them.
- Data: patches under `kamra/patches/tex/` listed in `kamra/patches.txt` (`[post_model_sync]`),
  each idempotent (`if frappe.db.exists(...)` / `has_column` guards), each with a test in
  `kamra/tex/tests/integration/test_migrations.py`.
- No destructive DDL. Legacy columns stay; TEX fields are additive (`tex_` prefix on existing
  DocTypes to avoid collisions with upstream).

## 2. Ordered patches

Implemented as: `p01_foundation` (T1–T3), `p02_access_grants` (T4), `p03_indexes` (T10),
`p04_lock_legacy_prices` (T9), `p05_vouchers_to_promotions` (T6), `p06_experiences_to_extras`
(T7), `p07_forget_payment_link_urls` (security clean-up), `p08_confirm_unpaid_capability` (adds
`reservation.confirm_unpaid` to the seeded admin/revenue/finance profiles, ADR-025) and
`p09_guest_stats_completed_stays` (recomputes guest stats: completed stays only, lifetime value
with its currency in the new `Guest.tex_lifetime_currency`). T8 is the opt-in API
`kamra.tex.api.contracts.legacy_draft` (`kamra/tex/commercial/legacy.py`). T5 is not needed:
TEX boards are contract-level codes (RO/BB/HB/FB/AI/UAI), independent of legacy Meal Plans.
Tests: `kamra/tex/tests/integration/test_migrations_notify.py`.


| # | Patch | What it does | Reversible? |
|---|---|---|---|
| T1 | `tex.p01_settings_and_roles` | Creates `TEX Settings` singleton defaults (strict tenancy on, legacy PMS nav hidden), roles `Call Center Agent`, default `TEX Permission Profile`s | Yes (records only) |
| T2 | `tex.p02_masters` | Seeds `TEX Market` (GLOBAL, TR, DE, UK, RO, PL, RU, CIS, DACH, EU with ISO country lists) and `TEX Sales Channel` (DIRECT_WEB, CALL_CENTER, API, B2B, META, OTA) | Yes |
| T3 | `tex.p03_enterprise_backfill` | Creates one default `TEX Enterprise` + `TEX Hotel Group` and links every existing Property (keeps names) | Yes |
| T4 | `tex.p04_access_grants_from_user_permissions` | For each existing `User Permission (Property)` creates a Hotel-level `TEX Access Grant` with the profile matching the user's roles — preserves current access exactly | Yes |
| T5 | `tex.p05_board_codes` | Adds RO/BB/HB/FB/AI/UAI to Meal Plan options (JSON) — existing EP/CP/MAP/AP rows untouched | n/a |
| T6 | `tex.p06_vouchers_to_promotions` | Copies each `Discount Voucher` to `TEX Promotion` (trigger=Code, same code, validity, limits, usage count); stores `legacy_voucher` link; legacy voucher kept | Yes |
| T7 | `tex.p07_experiences_to_extras` | Copies `Experience` → `TEX Extra` (pricing mode Unit, same price/tax, `legacy_experience` link) | Yes |
| T8 | `tex.p08_legacy_contracts` *(opt-in, per property)* | Generates a Draft "Legacy BAR" contract per property from Room Type base prices + Seasons (period per season range) so hotels can review and publish; never auto-published | Yes |
| T9 | `tex.p09_reservation_lock_backfill` | Marks existing Confirmed/Checked In/Checked Out reservations `tex_price_locked=1` with `tex_pricing_source='legacy'` so later edits never reprice them | Yes (flag) |
| T10 | `tex.p10_inventory_days` | No data creation needed (lazy); adds DB indexes for `TEX Inventory Day (room_type, date)` and `Reservation (room_type, status, check_in_date, check_out_date)` | Yes |

## 3. Compatibility shims
- `kamra.pricing.quote` remains for legacy callers (folio night posting, channel push, legacy
  desk). TEX reservations never use it (guard in `Reservation.apply_pricing`).
- `create_booking` keeps its signature; TEX bookings go through `kamra.tex.api.booking`.
- `/kamra/*` routes stay valid; `/tex/*` is the TEX alias; `/book` routes to the new engine when a
  `TEX Booking Site` exists for the property, else the legacy page.

## 4. Verification
1. Fresh install: `bench new-site` + `install-app kamra` → all patches no-op or seed.
2. Upgrade path: site with upstream data (eval harness seed) → `bench migrate` → counts preserved;
   `test_migrations.py` asserts voucher/extra copies and lock backfill.
3. Upstream suites (eval harness, journey, banquet) stay green after migration.

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
