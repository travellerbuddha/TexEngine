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
