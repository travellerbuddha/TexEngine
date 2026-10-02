# Handover appendix: Stage 3 work cards — the `api/public.py` chain (O-8, G-55b, G-71, G-70)

Companion to `docs/tex-engine/HANDOFF.md` (read that first: method, rules, order of the batches, open owner
decisions D-5 and the CRS override capability). **Re-verify every card against the current code before you
change it**: the line numbers are those of `aac444a4`.

Re-verified 2026-10-01 against `claude/inspiring-ptolemy-i6wdu2` @ aac444a4 (every Part 2 batch merged:
PRs #3–#16). Static analysis only (no bench). Line numbers below are **current** (the
original Part 2 plan cards were written at 0669c51e and are stale).

Legend: **verified** = read in the code / run here; **assumed** = not checkable without a bench, reason given.

**Status (2026-10-02):** O-8, G-55b and G-70a merged (Part 2G-2, PR #18); G-71 and G-70b done in Part 2G-3
(IMPLEMENTATION_STATUS §6G3). Where 2G-3 departed from these cards: the market codes keep G-55b's kinds (no "market"
kind); the booking app's text helper is `refusalMessage` (`lib/extras.ts` already has a `refusalText`); a channel's
booking is `CHANNEL_BOOKING` with `params.sold_by` (its label, since LO-13 the text names it); LO-12's view key is
`sold_by`; a forged sandbox signature is a `ProviderError` that is also a coded 417.

---

## 0. What changed versus the original Part 2 plan (read this first)

1. **Order changes (material).** G-55b needs to know *that a refusal is a market refusal* and O-8's booking
   app handling needs the refusal *code*. Today the booking app can only tell refusals apart by English
   wording — exactly what G-70 removes. So the small G-70 **transport** (a coded `Refusal` exception, a
   decorator that copies the code into the error body, `ApiError.code` in the booking app) lands **first**
   (step "G-70a"), then O-8 → G-55b → G-71 → G-70b (all remaining throw sites + catalogs + classification).
   The original reason for "G-70 last" (money-path files still moving in 2B/2E/2F) no longer applies: all of
   Part 2 is merged.
2. **O-8 is M, not S–M.** "Staff may override in the CRS" cannot work today: the CRS guest form has **no
   country field** (verified: `frontend/src/tex/screens/crs/components/CheckoutParts.tsx` has first/last
   name, e-mail, phone, language, requests only), so every CRS booking on TR would be a "mismatch". O-8 needs:
   CRS guest country/nationality + override UI, `crs.book`/`ui_crs.book` params, booking-app checkout
   (residence required, nationality), two staff editors (site markets, market "residents only"), seeds +
   p71. Decision taken for "search may show/refuse" (§2b).
3. **G-71 is bigger than the card.** `public.search` already pops `contract`/`version` from offers, but
   still sends `contract_code` and `market` per offer **and the full `contract` block (id, code, name,
   version, version_no, payload_hash, market, currency, basis) inside every room quote** of search, `quote`
   and `quote_rooms`; also `request.market/channel/sale_at`, top-level `market`/`channel`, `market`/`channel`
   in `book` and `booking_status`, `default_market` in `site`, engine reason texts. `basket` is already clean
   (verified). The signed `offer_key` is base64 JSON carrying contract id, version id and market: residual,
   documented, not fixed (ADR note).
4. **G-55b needs a schema change.** `TEX Funnel Event.event` is a Select (`search, room_view, quote,
   guest_details, payment_started, abandoned, booked`); a new event value fails validation and `_track`
   swallows the error (`log_exception`) — the event would be silently lost. Needs the option + patch p72 +
   a browser-event allow-list entry.
5. **Y-8 guest refusal leaks an internal id** — *fixed in Part 2K-3 (LO-13)*: `cancel_reservation` now names the
   connection's label (`Sold by Sandbox CM: …`), never its docname. It still has no code (row 101).
6. **i18n check gap.** `npm run i18n:tex` is meant to check the booking catalogs but its root
   `src/booking/i18n/locales` does not exist, so it silently skips them (verified by running it). The
   booking catalogs are only checked by `src/booking/i18n/check.ts` (same keys, plural forms) — **not
   placeholders**. Fix the root to `src/booking/i18n` (verified with a probe: the current 537 keys × 6 pass
   key and placeholder parity, so the fix is green today).
7. **DocType generator pitfall (verified by running it in a throw-away copy).** `python -m
   kamra.tex.devtools.doctype_gen` rewrites every TEX JSON from the specs and rolls back 9 hand-bumped
   `modified` stamps (TEX Funnel Event, TEX Quote, TEX Reservation Revision, TEX ARI Restriction, TEX
   Promotion Redemption, TEX Abandoned Booking, TEX Loyalty Ledger, TEX Payment Link, TEX Payment Provider
   Account). Commit only the JSONs you changed. TEX Market and TEX Booking Site are in sync with their specs.

Recommended order and sizes: **G-70a (S) → O-8 (M) → G-55b (S) → G-71 (S) → G-70b (M–L)**. One commit per
item, fail-first test in each. **Binding split (HANDOFF.md §2):** batch 3A = G-70a → O-8 → G-55b (PR
"2G-2", first of all remaining work); then the money/loyalty/channel leftover batches (their new refusals use G-70a);
then batch 3B = G-71 → G-70b (PR "2G-3"). Patches: **p71** (O-8), **p72** (G-55b); p67 stays unused.
ADR: **ADR-070** (O-8 + G-55b); G-70 amends **ADR-013**, G-71 amends **ADR-026** (+ a note on ADR-009);
G-55b adds one line to **ADR-056**.

---

## 1. Shared facts (verified unless marked)

### 1.1 The guest API (`kamra/tex/api/public.py`, 996 lines)
Endpoints (decorators): `site` 121 (GET), `search` 202, `extras_availability` 242, `quote` 261 (+retry),
`quote_rooms` 286 (+retry), `basket` 355, `book` 386 (+retry), `booking_status` 489, `pay_booking` 497
(+retry), `mock_pay` 535 (+retry), `payment_link` 562, `pay_link` 596 (+retry), `track` 735,
`manage_cancel` 847 (+retry), `manage_propose` 869, `manage_extras` 906, `manage_extras_propose` 928,
`manage_extras_apply` 942 (+retry), `manage_apply` 957 (+retry), `manage_change_pay` 982 (+retry).
Order on each: `@frappe.whitelist(...)` → `@rate_limit(...)` → (`@retry_on_deadlock`) → def.
Rate limits: `SEARCH_LIMIT` 60/60 s, `WRITE_LIMIT` 20/600 s per IP (public.py:36-37); `track` 120/60 s;
`quote_rooms` also charges each room against the write budget (`_charge_rooms`, :45-57).

### 1.2 How an error reaches the booking app today (Frappe v16 source fetched from GitHub `version-16`)
- `frappe.throw(msg, exc)` → `msgprint(..., raise_exception=exc)`; if `exc` is an **instance** Frappe
  raises **that instance** with `exc.args = (msg,)` (`frappe/utils/messages.py:48-59`). Repo evidence: the
  `ContractNotOnSale` instance thrown at `services/booking.py:649` keeps its class `code`
  (`test_critical_journey.py:666-668` asserts `caught.exception.code == "CONTRACT_SUSPENDED"`). So
  instance attributes (`code`, `params`) survive `frappe.throw` — **verified** (source) / repo test.
- On an exception, `report_error` (`frappe/utils/response.py:39-65`) adds `exc_type` to
  `frappe.local.response` and `as_json` serialises **the whole `frappe.local.response`** (`:146-156`);
  `frappe.local.response` is created once per request in `frappe.init` (`frappe/__init__.py`, `local.response
  = _dict({"docs": []})`) and is not reset before `handle_exception` (`frappe/app.py:181-184`). So a key set on
  `frappe.local.response` before the exception escapes is in the JSON error body — **verified (source)**.
- `raise X(...)` without `frappe.throw` puts **no** message in `_server_messages`: the guest gets only
  `exc_type` (the traceback text is only for system users). Today this is the case for `HoldExpired`
  (`services/holds.py:203, 270`), `ExtraSoldOut` (`availability/extras_repository.py:155,158`) and
  `ChargeSuperseded` (`payments/service.py:480`).
- `inspect.signature` follows `__wrapped__`, and Frappe builds call args from it (`frappe/__init__.py:1151-1190`),
  so a `functools.wraps` decorator keeps the endpoint's parameters — **verified (source)**.
- The booking app (`frontend/src/booking/lib/api.ts`) reads `exc_type`, `_server_messages`, `exception`,
  `message`, then `classify()` (:42-52) decides the kind **by English wording** for sold out / expired
  (`SOLD_OUT = /sold out|no longer available|not enough rooms/i`, `EXPIRED = /expired|search again|no longer
  on sale|already used|invalid offer|invalid quote/i`, :39-40). Probe run here
  (a throw-away node test that fed `classify()` real server texts): a Turkish server text for a sold-out room classifies as
  `invalid`; `PaymentBusy`/`HoldExpired` classify as `invalid`; "This payment link is expired." as `expired`.
- Other wording-based decisions: `Checkout.tsx:584` `res.error.kind === "invalid" && /payment|pay|hotel/i
  .test(message)` (also matches "All rooms of a booking must be at the same hotel."); `BookingContext.tsx:294-300`
  falls back without the market link on **any** non-network ApiError; `PayLinkPage.tsx:90` picks a gateway
  on any `invalid`; `ManagePage.tsx:354, 618` rely on `kind === "expired"` (EXPIRED regex) for an expired
  proposal; pages print `e.message` verbatim (ManagePage 246, 327, 361, 593, 618, 633; ConfirmationPage
  122, 135; PayLinkPage 94, 111; MockPayPage 49; AddExtrasDialog 117-121; Results 561; useContinue 97, 114).

### 1.3 Booking app i18n
- Catalogs: `frontend/src/booking/i18n/{en,tr,de,ru,ro,pl}.json` (flat key → string | plural object;
  537 keys each); provider `frontend/src/booking/i18n/index.tsx` (en bundled, others lazy; `t(key, vars)` with
  `{name}` interpolation; Intl formatters `day`, `money`, …).
- Completeness: `frontend/src/booking/i18n/check.ts` — compile-time (`tsc -b` inside `npm run build`): every
  catalog has exactly en's keys, plural entries carry their categories. **Not** placeholders.
- `npm run i18n:tex` (`frontend/scripts/tex-i18n-check.mjs`): roots `["admin","src/tex/i18n/locales"]` and
  `["booking","src/booking/i18n/locales"]`; the second does not exist → skipped (ran it: "TEX i18n catalogs
  complete", admin only). Change it to `src/booking/i18n` (no sub-folders → `flat = ["."]`, works as is).
- CI (`.github/workflows/ci.yml:30-50`): `npm run build`, `npm run test:unit` (node --test
  `tests/unit/**/*.test.ts`), `npm run test:dom`, `npm run i18n:tex`. Staff app catalogs:
  `frontend/src/tex/i18n/locales/<area>/<lang>.json` (checked by `i18n:tex`, incl. literal keys used in `src/tex`).

### 1.4 Schema mechanics
- TEX DocTypes come from `kamra/tex/devtools/doctype_specs.py` via `doctype_gen.py`. `dt(..., extra={"modified":
  "…"})` sets the JSON stamp; without it the stamp is `2026-09-24 00:00:00.000000`. Frappe re-syncs a DocType on
  migrate only when its JSON `modified` is newer — **bump it** (latest stamp in the repo: TEX FX Rate
  `2026-10-03 00:00:00.000000`; use `2026-10-04 …` or later).
- `SB()`, `CB()`, `TAB()` number their fieldnames with **one global counter** (`doctype_gen.py:38-56`): adding
  one renames every later section/column of every later DocType. Add plain `F(...)` fields only (or a
  named break as TEX Settings does at `doctype_specs.py:107`).
- Generator drift: see §0.7. Commit only the changed JSONs (`git checkout --` the 9 unrelated ones), or add
  `extra={"modified": <their current stamp>}` to those specs (out of scope).
- Patches: `kamra/patches.txt` `[post_model_sync]` ends with `p68, p69, p70` (sorted per section, enforced by
  `test_patches.TestEveryPatch`); every patch needs a `BEHAVIOUR` entry in
  `kamra/tex/tests/integration/test_patches.py:48-125`. Next free: **p71**; p67 unused. `ran_before(__name__)`
  (`kamra/tex/setup.py:161`) makes a one-time data step skip on a forced re-run. Fresh installs mark patches as
  run → seeds must carry new defaults (`kamra/tex/setup.py` `MARKETS`, `ensure_masters`).

### 1.5 Test helpers to reuse
- Integration: `test_commercial_flows.setup_site_and_payments(f, **contract)` (DE contract "PAY", Mock card rule,
  Pay-at-Hotel rule, site `SLUG="tex-test-resort"` default market DE, currency EUR), `guest_books(session,
  method, guest, before_book, extras)`, `GUEST` (country "Germany"); `test_public_booking._search(rooms,
  session)`; `fx.create_contract(f, code=…, market=…)`, `fx.ensure`, `fx.ensure_user`, TEX Access Grant pattern
  (`test_public_booking.py:331-335`); `TestSelfService._paid_booking`, `freeze_time`
  (`test_commercial_flows.py:466-490`); `test_hold_payment_race`: `HoldCase.book/start_payment/passes`,
  `TestRefusedAfterTheHold` (HoldExpired), `TestNoLockHeldThroughTheGateway` (PaymentBusy, threads);
  `test_distribution.TestChannelBookings.booked/staff` (Y-8); `test_patches.PatchCase.first_run`,
  `assertRerunChangesNothing`, `TestSmallPatches`.
- Static wrapper checks: `test_hold_payment_race.TestDeadlockRetries.test_the_payment_endpoints_run_again_on_a_deadlock`
  and `test_the_quote_endpoints_run_again_on_a_deadlock` walk `__wrapped__` to find the retry wrapper — a new
  decorator **must** use `functools.wraps` or these fail.
- Frontend: node unit tests import pure modules from `src/booking/lib/*.ts` (pattern:
  `tests/unit/manage-actions.test.ts`, `paylink-notices.test.ts`, `checkout-fallback.test.ts`; verified they run
  with node 22 here). E2E (Playwright, `frontend/e2e`): `flows/booking.ts` (`guestSearch`, `bookingPath`,
  `fillGuest`, `pickRoom`), `helpers.ts` (`api`, `pageApi`, `pageApiOk`, `stayDates`, `trackErrors`),
  `manage-money.spec.ts` (`bookStay` via `public.book`, `openManage(page, b)` = `/book/aurora/manage?lang=en#token=…`).
  Demo site `aurora` (group site, default market GLOBAL, contracts DE and GLOBAL, no TR contract —
  `kamra/tex/devtools/demo_seed.py:195-213`).

---

## 2. Card O-8 · Market arbitrage (HIGH) — ADR-070, D-5

### 2a. Problem (verified)
- **Any market by link.** `public._market` (public.py:187-196) builds `MarketDef`s from **all** TEX Markets and
  calls `versions.resolve_market(explicit=market, country=country, markets=markets, default=site.default_market)`
  **without `allowed`**:
  ```python
  markets = [versions.MarketDef(m.name, frozenset(_csv(m.countries)), bool(m.is_global), bool(m.disabled))
             for m in frappe.get_all("TEX Market", fields=["name", "countries", "is_global", "disabled"])]
  code, _how = versions.resolve_market(explicit=market, country=country, markets=markets,
                                       default=site.default_market)
  ```
  `resolve_market` (`pricing/versions.py:75-107`) accepts any enabled explicit market (`:87-91`), so `?market=TR`
  (booking app `lib/criteria.ts:118`) or `<tex-booking-widget market="TR">` (`frontend/src/widget/index.ts:211-214`,
  copied into the booking URL) prices the domestic market for anyone. `allowed` exists in the pure function but
  is never passed.
- **Country never checked against the market.** `search(..., market="TR", country="DE")`: the explicit market
  wins (`versions.py:87-91`), the country is ignored.
- **`book` never checks.** `public.book` (386-433) cleans `country`/`nationality` into Frappe Country **names**
  (`_country`, 343-352; 397-398) and passes them on; `create_booking` (`services/booking.py:574-802`) takes the
  market from the quotes (`markets = {r[1]["market"] for r in rows}`, :620-624) and only checks web channel
  (:626-630), O-15 method (:636-643), contract status (:644-649). Nothing compares guest residence/nationality
  with the market. Staff (CRS: `api/crs.py:86-100` `book`, `api/ui_crs.py:97-115` `book`) the same.
- **Schema today:** TEX Market has `market_code, market_name, is_global, disabled, countries, default_currency,
  default_language, parent_market` (`doctype_specs.py:207-218`); TEX Booking Site has `default_market` but no
  market list (`:969-1014`). Seed: `setup.MARKETS` TR = countries "TR" (`kamra/tex/setup.py:11-23`).
- **Data facts:** the booking app sends ISO alpha-2 `country` (`checkout/countries.json`, `Checkout.tsx:374-375`),
  no `nationality`; country is optional ("Country of residence", en.json `details.country`).
  `Guest.nationality` is a free `Data` field with default `"Indian"` (upstream Kamra `guest.json`) — never use
  it for this check. Frappe `Country.code` is lowercase ISO.
- No existing test or e2e uses market TR (grep) — the residents-only default does not break current tests.

### 2b. Fix design
**Decision (search vs book, consistent with the code).** Search refuses only what it *knows*: (a) an explicit
market the site does not sell → `MARKET_NOT_ALLOWED`; (b) a residents-only market requested together with a
link `country` outside it → `MARKET_RESIDENCY`. A residents-only market without a country (or picked from a
matching country) is **priced** and the answer says `residency: {"countries": [...]}`; the guest declares
residence at checkout and **`create_booking` enforces**. Reason: the search `country` is only a link hint, the
booking's declared residence is the guest's statement (and the hotel can check ID at check-in); refusing every
domestic link without a country would break genuine domestic campaigns; showing a price sells nothing.
`allowed_markets` blank = every enabled market (unchanged behaviour until a site is configured; the residents-only
rule protects TR regardless).

**Schema (one commit with p71).**
- `TEX Market.residency_required` — `F("residency_required", "Check", "Residents only (web)", description="Web
  bookings need a country of residence or a nationality among this market's countries. Staff may override in the
  Call Center, audited (ADR-070).")` after `countries` in `doctype_specs.py` (no new CB), and
  `extra={"modified": "2026-10-04 00:00:00.000000"}` on the TEX Market `dt(...)`.
- `TEX Booking Site.allowed_markets` — `F("allowed_markets", "Small Text", "Markets this site sells",
  description="Market codes, comma-separated. Blank: every enabled market. A link's market outside them is
  refused; the default market must be one of them.")` after `default_market`; `extra={"modified": …}`.
  (Small Text CSV like `currencies`/`languages`; read with `public._csv`.)
- Regenerate, keep only `tex_market.json` and `tex_booking_site.json` (§1.4).
- Controllers: `TEXBookingSite.validate` (`kamra/tex_booking/doctype/tex_booking_site/tex_booking_site.py:32-79`):
  upper-case/trim the list, every code an existing enabled TEX Market, `default_market` in the list when the list
  is set. TEX Market controller `TEXMarket.validate` (`kamra/tex_commercial/doctype/tex_market/tex_market.py:9-17`,
  already normalises ISO-2 countries and refuses countries on the global market): add — `residency_required`
  refused with `is_global` or with no countries (Desk/REST and `api/admin.save_market` both hit it; add the field to
  `admin.MARKET_FIELDS`, admin.py:163).
- Seed: `setup.MARKETS` gets a residency column (TR = 1); `ensure_masters` sets it on create only.
- **p71** `kamra/patches/tex/p71_market_integrity.py`:
  ```python
  def execute():
      frappe.reload_doc("tex_commercial", "doctype", "tex_market")
      frappe.reload_doc("tex_booking", "doctype", "tex_booking_site")
      if ran_before(__name__):
          return
      if frappe.db.exists("TEX Market", "TR"):            # D-5: the domestic market is residents-only, once
          frappe.db.set_value("TEX Market", "TR", "residency_required", 1, update_modified=False)
          audit("market.save", reference_doctype="TEX Market", reference_name="TR",
                new={"residency_required": 1}, reason="p71 (O-8, D-5)")
  ```
  Listed after `p70_manual_fx_rate` in `[post_model_sync]`; BEHAVIOUR
  `"p71_market_integrity": "test_patches.TestSmallPatches.test_p71_makes_the_domestic_market_residents_only_once"`.

**Pure layer (`kamra/tex/pricing/versions.py`, no frappe).**
- `MarketDef` gets `residency_required: bool = False`.
- `resolve_market`: an explicit code that is enabled but not in `allowed` raises
  `MarketResolutionError("MARKET_NOT_ALLOWED", …)` (today it says `MARKET_UNKNOWN`, :88-90).
- New `residency_refusal(market: MarketDef, *, country: str | None, nationality: str | None) -> str | None`:
  `None` when not residents-only, or when `country` or `nationality` (ISO, upper) is in `market.countries`;
  else `"MARKET_RESIDENCY"`.

**Search (`public._market`, `public.search`).** `_market` returns `(code, MarketDef)`; reads
`residency_required` too; passes `allowed=set(_csv(site.allowed_markets)) or None`; after resolution, when the
market is residents-only and a link `country` was given: `residency_refusal(...)` → refuse. Throw a coded
exception (G-70a): `frappe.throw(msg, MarketRefused(code=e.code, params={...}))` — `MarketRefused(Refusal)` so
`exc_type == "MarketRefused"` (the CRS uses it, §CRS). `search` adds `res["residency"] = {"countries":
sorted(m.countries)} if m.residency_required else None` (and G-71 later drops `res["market"]`). `_track("search",
{... "market": mkt})` unchanged (reports use it, `reports/service.py:841`).

**Booking (`services/booking.py:create_booking`).** New kwargs `market_override: bool = False,
market_override_reason: str | None = None`. Right after the web-channel check (:626-630), before the O-15
method check (:636-643) and before any contract/night lock:
1. web path (`booking_site or not staff`): if the site lists markets and `market` is not among them →
   `MARKET_NOT_ALLOWED` (a quote of another site of the same hotel; cheap).
2. `m = TEX Market(market)`; if `m.residency_required`: `country = iso(guest.country)`, `nat =
   iso(guest.nationality)` (new helper `iso_country(value)`: ISO alpha-2 or a Country name → upper ISO; Frappe
   `Country.code` is lowercase); `why = versions.residency_refusal(...)`.
   - web (guest, or staff on a booking site): `audit_refusal("booking.market_refused", reference_doctype="TEX
     Quote", reference_name=first quote, property=property, new={"market", "countries", "country", "nationality",
     "site"}, once_per=("market", "country", "nationality"))` (the existing outside-the-transaction refusal audit,
     `security/audit.py:150-177`; inline in tests) then refuse `MARKET_RESIDENCY` (guest text: "These prices are
     for residents of {countries} …"); never an override.
   - staff without booking site (CRS): refuse `MARKET_RESIDENCY` (staff text names market, countries, the
     guest's country/nationality and the override) unless `market_override`; with it a reason is required;
     after `booking.insert` (next to `booking.staff_on_site`, :730-735) `audit("booking.market_override",
     reference_doctype="TEX Booking", reference_name=booking.name, property=property, new={"market", "countries",
     "country", "nationality"}, reason=market_override_reason)`. Capability: `reservation.create` (already
     required) + reason — D-5 says "staff may override"; the stricter alternative is `price.override` (Revenue
     Manager/admins; owner may choose, no patch needed either way).
   Eligibility is read from the **current** TEX Market at booking (not from the frozen payload): it is not a
   price (ADR-070). Channel bookings (`distribution/channel_booking.py`) are not checked (the channel's sale).
- `api/crs.py:book` and `api/ui_crs.py:book`: params `market_override: int = 0, market_override_reason:
  str | None = None` → `create_booking(...)`; `text(reason, 300)`.
- `public.book`: also pass ISO codes (keep `_country` names for `resolve_guest`), e.g. `guest_clean["country_code"]`
  — or let `iso_country` accept names (simplest; both work).

**Booking app (`frontend/src/booking`).**
- `types.ts`: `SearchResult.residency?: { countries: string[] } | null`; `Basket.residency?` (see below).
- Results: an info banner when `search.data.residency` ("Prices for residents of {countries}; you will confirm
  your country of residence when booking").
- Checkout `DetailsStep` (`Checkout.tsx:347-390`): when the basket/search says residency, the country select is
  required (`details.errResidence`), a note explains, and an optional **Nationality** select appears (ISO,
  same `countries` list); `Guest` gets `nationality` (BookingContext.tsx:38-48, EMPTY_GUEST :95-105, book payload
  :554-564). Pre-fill country from `criteria.country` when empty.
- `public.basket` adds `residency` from `out["market"]` (quotes_summary returns it) so checkout reads the market
  of the quotes actually booked (more robust than search state after O-30's re-quote).
- A `MARKET_RESIDENCY` refusal at book → inline error on the country field + action "See our standard prices"
  (re-run the search without the link: reuse `refusedMarket` in BookingContext).
- New keys in all 6 catalogs (`details.residenceNote`, `details.errResidence`, `details.nationality`,
  `results.residencyBanner`, …); widget unchanged (it only forwards `market`/`country`).

**Staff app (`frontend/src/tex`).**
- Boot markets (`api/session.py:57-59`) add `residency_required` → CRS knows it per market.
- CRS guest form (`screens/crs/components/CheckoutParts.tsx`, `lib/useBookingFlow.ts:655-700`): "Country of
  residence" + "Nationality" inputs (Country-name datalist like `crm/profile/EditGuestDrawer.tsx:171-172`),
  pre-filled from the CRM lookup row (`tex_country`; ignore a `nationality` of "Indian"), marked required when
  the market is residents-only. On `err.type === "MarketRefused"` show "Book on this market anyway" + reason →
  resend with `market_override=1, market_override_reason`.
- Settings → Markets (`screens/settings/Markets.tsx`, `api/admin.py:163-247` `MARKET_FIELDS`): the
  "Residents only (web)" checkbox. Booking Engine → General (`screens/booking-engine/tabs/GeneralTab.tsx:133-166`,
  `site.ts:30-31,97-98`): "Markets this site sells" checkbox group (pattern of `currencies`); saved through the
  generic `policies.save_record` (any meta field is accepted, `api/policies.py:132-160`; validation in the
  controller). Staff catalogs: `src/tex/i18n/locales/{crs,settings,be?}/*.json`.

### 2c. Fail-first tests
- Unit (pure) `kamra/tex/tests/unit/test_contracts_restrictions.py::TestMarket` (:165-194):
  `test_an_explicit_market_the_site_does_not_sell_is_not_allowed` (today `MARKET_UNKNOWN` → fails);
  `test_residency` (residents-only: country match, nationality match, neither, none; other market → None).
- Integration `kamra/tex/tests/integration/test_public_booking.py`, new `class TestMarketIntegrity(TexTestCase)`;
  `setUp`: `setup_site_and_payments(self.f)`, `fx.create_contract(self.f, code="TR-DOM", market="TR")`,
  `frappe.db.set_value("TEX Market", "TR", "residency_required", 1)`:
  1. `test_a_market_the_site_does_not_sell_is_refused_in_search` — site `allowed_markets="DE,GLOBAL"`:
     `public.search(market="TR")` raises with `.code == "MARKET_NOT_ALLOWED"` (today prices TR); `country="TR"`
     falls back to DE (assert `residency` is None and DE prices).
  2. `test_a_residents_only_market_is_refused_for_another_link_country` — `search(market="TR", country="DE")`
     → `MARKET_RESIDENCY`.
  3. `test_the_guest_declares_residence_at_booking` — `search(market="TR")` → `res["residency"] == {"countries":
     ["TR"]}`; quote; `public.book(guest=GUEST)` (Germany) → `MARKET_RESIDENCY`, no TEX Booking, a
     `booking.market_refused` TEX Audit Event; `book(guest={**GUEST, "country": "TR"})` → booked;
     `{**GUEST, "nationality": "TR"}` → booked (new session/quotes per attempt; quotes are single use).
  4. `test_staff_override_in_the_crs_is_audited` — staff user with a Reservations Agent grant: `crs.search(market=
     "TR", channel="CALL_CENTER")` → `crs.quote` → `crs.book(guest country DE)` → `MarketRefused`; with
     `market_override=1` and no reason → refused; with a reason → booked + `booking.market_override` event
     (market, country, reason).
  5. `test_staff_on_a_booking_site_follow_the_site` — staff calling `public.book` on the site → refused, no
     override parameter exists there.
  6. `test_markets_and_sites_are_validated` — unknown/disabled code in `allowed_markets`, default market not in
     the list, `residency_required` on GLOBAL or without countries → ValidationError.
- `test_patches.TestSmallPatches.test_p71_makes_the_domestic_market_residents_only_once`: `seen =
  self.first_run("p71_market_integrity")`; `seen["reload_doc"] == [("tex_commercial","doctype","tex_market"),
  ("tex_booking","doctype","tex_booking_site")]`; TR flag 1; an administrator sets it 0 →
  `assertRerunChangesNothing` keeps 0; `has_column` on both fields. Plus the BEHAVIOUR entry (else
  `TestEveryPatch` fails).
- Frontend unit `tests/unit/market-residency.test.ts` for a pure helper in `src/booking/lib/residency.ts`
  (country required, note text inputs, ISO matching). No O-8 e2e (demo has no TR contract); optional later.

### 2d. Pitfalls / interactions
- Put the check **before** O-15's `pay.method_offered` (booking.py:639-643) and before `contracts.not_on_sale(...,
  lock=True)` (:646-649): the quotes are already locked `FOR UPDATE` in name order (:602-607, P1-4); a refusal
  rolls back cleanly (no step commit yet; NEW-6's `_commit_step` happens later in `start_payment`). Idempotent
  replay (:579-585) runs before every check — keep it so.
- `retry_on_deadlock` on `book`: the check reads TEX Market only (no locks); the `audit_refusal` job is queued
  (inline in tests) — no request commit, consistent with `txn.retry_on_deadlock` committed-step rules.
- The refused booking does not consume the idempotency key (rolled back): the booking app re-submits with the
  same `bookKey` after the guest fixes the country; CRS likewise (`bookKey.current`).
- Never read `Guest.nationality`/`tex_country` of an existing profile for the check (default "Indian";
  `resolve_guest` only fills empty fields, booking.py:159-163); use the request's values only.
- `iso_country`: accept ISO-2 or a Country name; compare upper-case; Frappe Country names vary ("Turkey"/"Türkiye").
- `_site()` uses `get_cached_doc("TEX Booking Site")` — saving the site clears it (standard), fine.
- Group sites: one list for all their hotels. The default market is always allowed (validated).
- `market` stays on the quote/booking (`TEX Quote.market`, `TEX Booking.market`): staff reports keep it; only guest
  answers lose it (G-71).
- O-15 payment-method rules per market are unchanged; Y-8 channel bookings untouched.
- A staff *modification* that changes a stay's market to a residents-only one is not checked here (staff,
  audited by its revision); note as LOW follow-up.
- Rate limits: the extra refused `book` costs one write call (20/10 min/IP) — acceptable.

### 2e. Size / order
**M** (backend S–M + booking app S + CRS/editors S). After G-70a, first of the chain.

---

## 3. Card G-55b · A refused market link is shown and counted (LOW) — R-13, G-55

### 3a. Problem (verified)
`BookingContext.tsx:288-300`:
```ts
if (linked && refusedMarket.current !== linked) {
  try { data = await pub<SearchResult>("search", { ...args, market: criteria.market || undefined, country: ... }) }
  catch (e) {
    if (!(e instanceof ApiError) || e.kind === "network" || e.kind === "rate_limit") throw e
    console.warn(`[tex-booking] market link ignored (...)`)      // the only trace
    refusedMarket.current = linked
    data = await pub<SearchResult>("search", args)
  }
}
```
- The guest is never told; no funnel event; and **any** refusal (bad dates, unknown hotel …) triggers the
  fallback, not only market ones. The e2e pins the silence: `frontend/e2e/booking.spec.ts:184-206` "…an unknown
  market falls back quietly" expects the console warning.
- Funnel: `public.track` accepts only `BROWSER_EVENT_FIELDS = {"room_view": …, "abandoned": …}` (public.py:656,
  737-742; allow-listed and value-checked by `_browser_payload` :667-693, ADR-056 L5); `TEX Funnel
  Event.event` options (`doctype_specs.py:1031-1046`) have no market event, and a failed insert in `_track` is
  swallowed (:727-732) — a new value without the option would be lost silently.

### 3b. Fix design
- Backend (`public.py`): `BROWSER_EVENT_FIELDS["market_refused"] = ("reason", "market", "country")`;
  `_browser_payload` for it: `reason` ∈ `MARKET_REFUSALS = {"MARKET_UNKNOWN", "MARKET_AMBIGUOUS",
  "MARKET_REQUIRED", "MARKET_NOT_ALLOWED", "MARKET_RESIDENCY"}`; `market` kept only if `_text()` and
  `frappe.db.exists("TEX Market", v)` (an unknown string is never stored); `country` kept only if 2 ASCII letters
  (upper-cased). Nothing else (contact keys dropped as today).
- Schema: TEX Funnel Event `event` options + `"market_refused"`; `extra={"modified": "2026-10-04 00:00:01.000000"}`
  on its `dt` (its JSON stamp is a hand-bumped `2026-09-26 10:00:00`, the spec has none — §0.7). **p72**
  `p72_market_refused_funnel_event.py`: `frappe.reload_doc("tex_booking", "doctype", "tex_funnel_event")`.
  BEHAVIOUR: add a row to `TestSmallPatches.test_p11_p20_only_sync_their_doctypes` (reload list
  `[("tex_booking","doctype","tex_funnel_event")]`) and assert `"market_refused" in
  frappe.get_meta("TEX Funnel Event").get_field("event").options.split("\n")` (has_column alone proves nothing
  for a Select option).
- Reports/CRM: `reports/service.py` STAGES (:803-807) and `crm/service.py` STAGES (:631) ignore unknown events;
  `detect_abandoned` opens cases only on quote/guest_details/payment_started (:664) — safe. Optionally count
  refused links in the conversion report later (not required).
- Booking app: a pure `src/booking/lib/marketLink.ts`: `marketRefusal(e: ApiError): { reason } | null` (by
  `e.code` ∈ the five codes, G-70a) and `marketNotice(reason)` → catalog key. BookingContext: only a market
  refusal falls back; it sets `marketNotice` in context, sends `beacon("track", {site, session_id, event:
  "market_refused", payload: JSON.stringify({reason, market, country})})` (new `trackMarketRefused` in
  `lib/track.ts`) and `analyticsEvent("market_link_refused", { reason })`; other errors surface as search errors.
  Results page shows an Alert (tone warn, `role="status"`): `market.refused.unavailable` (NOT_ALLOWED/UNKNOWN),
  `market.refused.residency` ({countries} via `Intl.DisplayNames`), `market.refused.other`. Keys × 6 catalogs.
- No widget change (verified: `frontend/src/widget/index.ts` only calls `public.site` for the theme, :160-176,
  and forwards `market`/`country` into the booking URL).

### 3c. Fail-first tests
- Integration `test_public_booking.TestMarketLinks` (:341-368): `test_a_refused_link_is_a_funnel_event` —
  `frappe.set_user("Guest")`; `public.track(site=SLUG, session_id="mk-1", event="market_refused", payload=
  {"reason": "MARKET_NOT_ALLOWED", "market": "TR", "country": "de", "email": "x@example.com"})` → one TEX Funnel
  Event `market_refused` with payload exactly `{"reason": "MARKET_NOT_ALLOWED", "market": "TR", "country": "DE"}`
  (today: "Unknown event."); `{"reason": "<script>", "market": "NOPE"}` → stored `{}`.
- p72 behaviour (above).
- Frontend unit `tests/unit/market-link.test.ts`: a market code → notice + payload; a non-market refusal (e.g.
  code `DATES_INVALID`) → no fallback (today any error falls back).
- E2E `booking.spec.ts:184-206`: rename to "… an unknown market falls back with a notice"; `?market=
  E2E_NO_SUCH_MARKET` → the notice text (en catalog) visible, rates equal the standard ones; optionally
  `page.waitForRequest(r => r.url().includes("kamra.tex.api.public.track") && (r.postData() ?? "").includes(
  "market_refused"))` — **assumed** Playwright reports `sendBeacon` requests with their body; if not, read the
  TEX Funnel Event through the admin `api(...)` context instead. Keep `trackErrors` (no console error).

### 3d. Pitfalls
- O-27: payloads and notices never carry the manage token; the beacon body has only reason/market/country.
  O-28: `beacon()` already adds `csrf_token` for signed-in staff (lib/api.ts:130-135).
- `track` limit 120/min/IP; one event per page life per link (`refusedMarket` ref).
- The fallback search can itself fail with a market code when the site's default market is bad — then show the
  normal search error (no loop).

### 3e. Size / order
**S**, after O-8 (uses its codes and `residency` countries).

---

## 4. Card G-71 · No contract identity in guest payloads (LOW) — R-52, R-53

### 4a. Problem (verified)
- `public.search` (public.py:220-228) strips only:
  ```python
  for p in res["properties"]:
      p.pop("messages", None)
      for o in p["unavailable"]: o.pop("contract", None); o.pop("version", None)
      for o in p["offers"]:      o.pop("contract", None); o.pop("version", None)
  res["market"] = mkt
  ```
  but each entry also carries `"contract_code": contract_row.contract_code, "market": terms.market`
  (`services/quoting.py:306-309`), and every `rooms[].quote` is `q.to_dict(internal=False)`
  (`quoting.py:302`), which always includes `"contract": self.contract` (`pricing/engine.py:184`) =
  `_contract_info(t)` = `{"contract", "code", "name", "version", "version_no", "payload_hash", "market",
  "currency", "basis"}` (`engine.py:263-266`) and `"request": request_to_dict(...)` with `market`, `channel`,
  `sale_at`, `member`, `booking_baskets` (`pricing/serialize.py:324-341`). Top level: `market`, `channel`
  (`quoting.py:435-436`).
- `public.quote` / `quote_rooms` return `_persist`'s `"quote": q.to_dict(internal=False)` (`quoting.py:585-587`)
  — the same `contract` block and `request`; refusal answers `{"ok": False, "reasons": q.reasons}` carry engine
  messages such as `"{room_type} is not sold under {contract_code}"` (`engine.py:246`, e.g. a room dropped by a
  version published after the search) or `"contract stays end on <date>"`.
- `public.book` returns `booking_summary` (`services/booking.py:1313-1330`) with `"market"`, `"channel"`;
  `booking_status` (`_guest_booking`, public.py:792-830) spreads the same summary. `site()` returns
  `"default_market"` (public.py:148). Guest-reachable texts that name internals: `modification._resolve`
  "No contract sold this stay for market {0} at {1}." (`services/modification.py:248`), `contracts.load_terms`
  "Contract version {0} is not published." / integrity (`commercial/contracts.py:886, 890`), extras reasons
  `"not available for market {market}"` (`pricing/extras.py:109`).
- `basket` is clean: it returns `currency, total, usable, expires_at, pay_at_hotel_allowed, rooms[{quote_id,
  room_type, total, due_now, deposit_type, pay_at_hotel_allowed, expires_at, problem}], methods` (public.py:
  379-383; `payment_policy` popped) — no contract id/code/version/hash/market.
- The booking app uses none of these fields (grep: no `contract`, `request`, `payload_hash`, `.market` use in
  `src/booking`; `types.ts:233 market: string` and `:66 default_market?` are declared but unused). The widget reads
  only branding/texts from `site()`.
- Staff keep everything: `crs.search` (`api/crs.py:25-59`, `internal=True`), `crs.quote`, `ui_crs.*`.
- Residual: `offer_key` = base64(JSON) + HMAC (`quoting.py:43-47`); its body has `contract` (CTR-#####),
  `version` (hash id) and `market` (`quoting.py:295-300`). Signed, not encrypted.

### 4b. Fix design
- `public.py` helpers (guest only; staff paths untouched):
  - `_guest_quote(q)`: pop `contract`, `request`, `engine_version`; promotions keep `promo_id` (React key in
    `Results.tsx:177`), `name`, `applied`, `discount`, `code`, `value_added`, drop `source`/`stage`/`rule`;
    reasons → `_guest_reasons`.
  - `_guest_reasons(rs)`: keep `code`, `room_index` and the numeric `max_*` (used by `lib/policy.ts:77-95`), drop
    `message` (the app maps codes; `Reason.message` becomes optional in `types.ts`).
  - `_guest_offer(o)`: pop `contract`, `contract_code`, `version`, `market`; `rooms[].quote` → `_guest_quote`;
    `reasons`/`room_reasons` → `_guest_reasons`.
- `search`: move the strip loop **after** `content.Localizer(...).search(res)` (public.py:229) — the localizer
  reads `quote.request.room_type/board` (`services/content.py:134-142`); pop top-level `market`, `channel`; add
  O-8's `residency`.
- `quote` / `quote_rooms`: after `loc.quote(...)` (:279, :315) → `_guest_quote(out["quote"])`; refusal answers →
  `_guest_reasons`.
- `book` (both return paths, after `_start_booking_payment` used `result["market"]`, :441) and `booking_status`:
  pop `market`, `channel`. `site()`: drop `default_market`.
- Guest-safe texts for the leaking refusals (done with G-70b codes): `_resolve` → `CHANGE_NOT_SELLABLE`;
  `load_terms` on the guest quote path → `NOT_ON_SALE`. Optional: in guest quotes keep an extra's `reason` only
  for capacity reasons (sold out / not enough left / closed on D — what `lib/extras.ts:80-104` parses), else
  `"unavailable"`.
- Frontend: types only (`SearchResult` without `market`, `Reason.message?`).

### 4c. Fail-first tests
- `test_public_booking.TestPublicBooking.test_guest_answers_name_no_contract` — helper `identity_leaks(payload,
  version, contract)`: recursive scan; fails on any key in `{"contract", "contract_code", "contract_name",
  "version", "version_no", "payload_hash", "market", "channel"}` (except inside staff answers) or any string equal
  to the version id, payload hash or contract docname (`CTR-…`). Applied to `public.search`, `quote`,
  `quote_rooms` (incl. a refusal answer: quote a room after `frappe.db.set_value` makes it unsellable),
  `basket`, `book`, `booking_status`, `site`. Today it fails on `contract_code`/`market`/`quote.contract`.
- Same test: staff keep them — `crs.search(..., market="DE", channel="CALL_CENTER")` offers have `contract`,
  `contract_code`, `version`; `crs.quote(...)["quote"]["contract"]["payload_hash"]` present.
- Existing `guest_books` assert (`"contract" not in offer`, test_commercial_flows.py:104) stays.

### 4d. Pitfalls
- Strip **after** localization and after `_track`/`_start_booking_payment` read the values.
- `guest_safe()` (extras) still runs on the result; order does not matter.
- Do not touch `quoting.strip_internal` (staff use) or `q.to_dict` (stored `TEX Quote.result_json` and
  reservation snapshots need everything — `_persist` stores `internal=True`).
- The offer key stays as is (changing it touches CRS and `verify` everywhere): document as accepted residual.

### 4e. Size / order
**S**, after G-55b (shares `search`), before G-70b.

---

## 5. Card G-70 · Stable codes on guest refusals (MED) — R-49

### 5a. Problem (verified)
- Guest refusals are `frappe.throw` English texts (226 untranslated `_()` messages, FINAL_GAP_AUDIT row 57) or bare
  `raise`s; no code reaches the booking app; the app classifies by wording (§1.2) and prints `e.message`
  verbatim (English, sometimes empty). Three classes already carry a code attribute: `ContractNotOnSale`
  (`CONTRACT_NOT_ON_SALE`), `ContractSuspended` (`CONTRACT_SUSPENDED`) (`commercial/contracts.py:1017-1023`);
  quote/search *answers* (not refusals) already use codes (`SOLD_OUT`, `NOT_ON_SALE`, restriction and engine
  codes; `manage_propose` warnings; `ADDON_*`; `changes_blocked`).
- Notes required by the plan: `PaymentBusy` (`payments/service.py:41`, thrown :325, :822), `HoldExpired`
  (`services/holds.py:179`, raised :203, :270), the Expired-quote refusal "no longer on sale" (`quoting.py:668`
  via `booking.py:604-606`; also `quoting.py:542, 583`), O-15 "This payment method is not available."
  (`booking.py:594, 643`), Y-8 "Sold by …: cancel it on the channel." (`booking.py:1127`), O-16 arrival-day cancel
  (`public.py:858`).

### 5b. Fix design
**G-70a — transport (first commit of the chain, S).**
- Pure registry `kamra/tex/refusal_codes.py` (no frappe, like `security/capabilities.py`): `CODES: frozenset[str]`
  (the codes of §5f) — importable by pure unit tests.
- `kamra/tex/services/refusals.py` (frappe):
  ```python
  class Refusal(frappe.ValidationError):
      """A refusal a guest can act on: a stable ``code`` (refusal_codes.CODES) and guest-safe ``params`` (ISO dates,
      decimal strings, ISO currency/country codes, hotel content in the guest's language) — never a token, an
      e-mail, a contract, version or connection id (G-70, ADR-013)."""
      code = "REFUSED"
      def __init__(self, message: str = "", *, code: str | None = None, params: dict | None = None): ...

  class MarketRefused(Refusal): ...                       # O-8; exc_type the CRS reads

  def refusal(code, base=Refusal, **params) -> Exception:   # frappe.throw(msg, refusal("SOLD_OUT", room=…, date=…))
      e = base(); e.code = code; e.params = params; return e  # base may be frappe.PermissionError / DoesNotExistError

  def code_of(e) -> str | None:                            # only a str in CODES (werkzeug errors have int .code)
      ...

  def coded(fn):                                           # guest endpoints
      @functools.wraps(fn)
      def wrapper(*args, **kwargs):
          resp = getattr(frappe.local, "response", None)
          if resp is not None: resp.pop("tex_code", None); resp.pop("tex_params", None)
          try:
              return fn(*args, **kwargs)
          except Exception as e:
              code = code_of(e) or FALLBACK.get(type(e))   # DoesNotExistError→NOT_FOUND, PermissionError→NOT_PERMITTED
              if code and resp is not None:
                  resp["tex_code"] = code
                  if getattr(e, "params", None): resp["tex_params"] = e.params
              raise
      return wrapper
  ```
  Every public endpoint gets `@refusals.coded` **between `@rate_limit` and `@retry_on_deadlock`** (so it sees the
  final exception, incl. the "very busy" one); `functools.wraps` keeps `__wrapped__` (static retry tests) and the
  signature (Frappe arg filtering). Class codes on existing exceptions: `PaymentBusy` PAYMENT_BUSY, `HoldExpired`
  HOLD_EXPIRED, `ChargeSuperseded` CHARGE_SUPERSEDED, `AccountRefused` PAYMENT_METHOD_UNAVAILABLE, `ExtraSoldOut`
  EXTRA_SOLD_OUT, `PaymentPending`/`RefundPending`/`ChangeApplying` (same strings as `changes_blocked`),
  `ChangeRefused` CHANGE_REFUSED, `CurrencyChanged` CURRENCY_CHANGED, `PayloadMismatch` RATE_UNAVAILABLE.
- Booking app `lib/api.ts`: `ApiError` gets `code: string | null` and `params: Record<string, unknown>`;
  `parseError` reads `tex_code` (`/^[A-Z][A-Z0-9_]{1,63}$/`) and `tex_params` (object); `classify(code, status,
  type)` = 429 → rate_limit; code → `KIND_BY_CODE[code] ?? (404 → not_found, 403 → permission, else invalid)`;
  no code → by status/type only (`ExtraSoldOut` type kept) — **no wording regexes**. `FlowError` carries
  `code`/`params` (`toFlowError`, BookingContext.tsx:195-198).

**G-70b — every guest throw site, the catalogs, the pages (M–L).**
- Rewrite each row of §5f: `frappe.throw(msg, refusal("CODE", ...))` (keep the English text — staff/API and tests
  match it); bare raises get class/instance codes; messages that leak internals get a guest variant (Y-8
  connection id, `_resolve` market, `load_terms` version). Helpers returning text become coded:
  `quoting.quote_refusal(row) -> Refusal | None` (keep `quote_is_usable` = its text, used by `quotes_summary`
  `problem` for staff; the public basket adds `problem_code`), `payments.link_refusal(...) -> Refusal | None`
  (callers `public._link_due` :589-592 and `reissue_link` :1827-1830: `frappe.throw(str(why), why)`),
  `quoting.require_fresh(data)` / `verify(kind=…)` choose OFFER_* vs PROPOSAL_* by `kind`. `txn.retry_on_deadlock`
  (`services/txn.py:101`) throws `refusal("BUSY")`.
- Catalogs: one key per code `refusal.<CODE>` in all 6 `src/booking/i18n/*.json` (texts may repeat; params
  `{room}`, `{date}`, `{max}`, `{countries}`, `{amount}`, `{owed}`, `{status}`, `{child}`, `{age}`,
  `{promotion}`, `{extra}`) + new `errors.retryTitle/Body`, `errors.holdExpiredTitle/Body`. Fix `i18n:tex`'s booking
  root (§1.3).
- `src/booking/lib/refusals.ts` (pure): `KIND_BY_CODE` (SOLD_OUT→sold_out; EXTRA_SOLD_OUT→extra_sold_out;
  OFFER_INVALID, OFFER_EXPIRED, QUOTE_INVALID, QUOTE_EXPIRED, QUOTE_USED, NOT_ON_SALE, CONTRACT_NOT_ON_SALE,
  CONTRACT_SUSPENDED, SEARCH_AGAIN, BASKET_NOT_TOGETHER, PROPOSAL_EXPIRED → expired; MARKET_* → market (new kind);
  PAYMENT_METHOD_UNAVAILABLE, PAY_AT_HOTEL_NOT_ALLOWED, WEB_TRANSFER_ROOMS, PAYMENT_START_FAILED → payment_method
  (new); PAYMENT_BUSY, BUSY, CHARGE_SUPERSEDED → retry (new); HOLD_EXPIRED, HOLD_EXPIRED_TRANSFER → hold_expired
  (new); SITE_NOT_FOUND, LINK_INVALID → not_found; MANAGE_LINK_* → permission; RATE_LIMITED → rate_limit) and
  `refusalText(i18n, e)` = `t("refusal." + code, formatted params)` (dates via `i18n.day`, money via
  `i18n.money`), falling back to the server message, then `errors.generic`.
- Pages: replace every `e.message` (§1.2 list) with `refusalText`; `Checkout.tsx:584` → `res.error.kind ===
  "payment_method"` (+ `reloadBasket()`); `PayLinkPage.tsx:90` → code `LINK_NO_CARD`/`PAYMENT_METHOD_UNAVAILABLE`;
  `useContinue.tsx` gets `retry` and `hold_expired` branches; BookingContext uses `kind === "market"` (G-55b).
- Out of scope (note): extras *reasons* in quote answers stay free text parsed by `lib/extras.ts:80-104` (an engine
  `reason_code` on `ExtraOutcome` is a pure-engine change — later); staff-side codes (G-70 staff part, plan §4).

### 5c. Fail-first tests
- Unit (pure) `kamra/tex/tests/unit/test_guest_refusal_codes.py`:
  1. `CODES` == the `refusal.*` keys of `frontend/src/booking/i18n/en.json` (path `Path(__file__).resolve()
     .parents[4] / "frontend/src/booking/i18n/en.json"`; works in CI's `apps/kamra` layout);
  2. AST over `kamra/tex/api/public.py`: every `@frappe.whitelist(allow_guest=True…)` function is decorated with
     `refusals.coded`; every `frappe.throw` passes a coded exception (`refusal(...)` call or a class in an
     allow-list of coded classes) — a new uncoded guest throw fails;
  3. codes are UPPER_SNAKE and unique.
- Integration `test_public_booking.TestRefusalCodes` (new), each asserting `cm.exception.code` and
  `frappe.local.response["tex_code"]`:
  `test_an_expired_payment_link_says_LINK_EXPIRED` (create a link with `pay.create_link`, set `expires_at` in the
  past, `public.pay_link`) — the plan's named test; used / expired / withdrawn quote at `book` → QUOTE_USED /
  QUOTE_EXPIRED / NOT_ON_SALE; method not offered → PAYMENT_METHOD_UNAVAILABLE; last room gone →
  SOLD_OUT with `params == {"room": …, "date": "…"}`; arrival-day cancel → CANCEL_TOO_LATE (reuse
  `TestSelfService.test_no_online_cancellation_from_the_arrival_day` setup); OTA booking on the manage page →
  CHANNEL_BOOKING and the message does not contain the connection name (reuse `test_distribution` booked
  channel fixture); `ExtraSoldOut` raised without `frappe.throw` still gives `tex_code`.
  Extend existing scenario tests rather than duplicating them: `TestRefusedAfterTheHold` (:2176-2237) →
  `.code` HOLD_EXPIRED / HOLD_EXPIRED_TRANSFER; `TestNoLockHeldThroughTheGateway` (:2970) → PAYMENT_BUSY.
- Keep passing: every `assertRaisesRegex(...English...)` (messages unchanged for staff), the static retry tests
  (`functools.wraps`), `TestMarketLinks.test_unknown_market_link_is_a_clean_validation_error` (message still
  contains the market code; now also `.code == "MARKET_UNKNOWN"`), `test_distribution` "cancel it on the channel"
  (staff path keeps the text).
- Frontend unit `tests/unit/refusal-codes.test.ts`: `parseError` reads `tex_code/tex_params`; a Turkish message +
  `SOLD_OUT` → `sold_out`; an English "sold out" text **without** code → not `sold_out`; `PAYMENT_BUSY` → retry;
  `refusalText` formats params; every `KIND_BY_CODE` key has a `refusal.` entry in en.json.
- E2E `frontend/e2e/guest-refusals.spec.ts` (new): book a Pay-at-Hotel stay via `api(req, "kamra.tex.api.public.
  book", …)` (as `manage-money.spec.ts` `bookStay`), open `/book/aurora/manage?lang=tr#token=…`, cancel the room
  as staff through `api(adminReq, "kamra.tex.api.crs.cancel", …)`, then the guest clicks the (stale) cancel →
  the Turkish `refusal.ROOM_NOT_ACTIVE` text is visible and the English server text is not; second case on
  `/book/aurora/pay/<token>?lang=tr` after staff cancel the link (`payments.cancel_link`) → `refusal.LINK_CANCELLED`.

### 5d. Pitfalls
- Decorator outside `retry_on_deadlock`, inside `rate_limit`; `functools.wraps` (static tests walk
  `__wrapped__`: `test_hold_payment_race.py:1827-1860`); clear `tex_code` at entry (tests call endpoints in one
  process).
- Committed steps: `_expire_and_refuse` commits the expiry before raising `HoldExpired` (P1-9, holds.py:186-204);
  `start_payment` commits the failed checkout before "could not be started" (NEW-6, service.py:430-450) — the
  decorator only annotates and re-raises; never catch-and-convert there.
- Same English text, different codes: "This room can no longer be changed online…" is CANCEL_TOO_LATE at
  public.py:858 and CHANGE_REFUSED at guest_changes.py:231; "This payment method is not available." at 7 sites is
  one code.
- Codes must not depend on HTTP status: keep `PermissionError` (403) / `DoesNotExistError` (404) bases where they are
  today (tests assert the classes).
- `tex_params` never contain tokens (O-27), e-mails, booking-unrelated ids; names are already localised hotel
  content (ADR-026: `Localizer.room_type_name`), dates ISO, money decimal strings.
- `ExtraSoldOut` text uses `frappe.format(d, "Date")` (site format) — pass ISO `date` in params.
- `i18n:tex` root fix may surface placeholder mismatches in new keys only (current catalogs pass).

### 5e. Size / order
G-70a **S** (first); G-70b **M–L** (last): ~105 throw-site rows (§5f), ~85 codes × 6 catalogs, ~12 page edits.

### 5f. Inventory of guest-reachable refusals

Complete for the 20 public endpoints: verified by an AST listing of every `frappe.throw`/`raise` per function
(a throw-away AST walk over the `frappe.throw`/`raise` sites) and by following each endpoint's call graph.

Endpoints abbreviations: S=search, Si=site, XA=extras_availability, Q=quote, QR=quote_rooms, Ba=basket, B=book,
BS=booking_status, PB=pay_booking, MP=mock_pay, PL=payment_link, PLk=pay_link, T=track, MC=manage_cancel,
MPr=manage_propose, MX=manage_extras, MXP=manage_extras_propose, MXA=manage_extras_apply, MA=manage_apply,
MCP=manage_change_pay. "VE" = ValidationError (417). "(unreach.)" = guarded earlier, listed for completeness.

| # | Endpoint(s) | Raise site (file:line, function) | Exception (HTTP) | Current English message | Proposed code (params) |
|---|---|---|---|---|---|
| 1 | Si S XA Q QR Ba B T | api/public.py:71, 74, 78 `_site` | DoesNotExist (404) | Booking site not found. | SITE_NOT_FOUND |
| 2 | S Q QR Ba B | api/public.py:94 `_channel` | Permission (403) | This booking site is not open for online booking. | SITE_CLOSED |
| 3 | S | services/quoting.py:424 `search` | VE | Unknown sales channel {0}. | SITE_CLOSED |
| 4 | QR | api/public.py:56 `_charge_rooms` | RateLimitExceeded (429) | You hit the rate limit because of too many requests… | RATE_LIMITED |
| 5 | Q QR B PB MP PLk MC MXA MA MCP | services/txn.py:101 `retry_on_deadlock` | VE | The hotel is very busy right now. Please try again in a moment. | BUSY |
| 6 | B MPr MXP (+Q QR) | api/_util.py:19 `parse`; services/quoting.py:482 `_json` | VE | Invalid JSON payload. | INVALID_REQUEST |
| 7 | T | api/public.py:739 `track` | VE | Unknown event. | INVALID_REQUEST |
| 8 | S | api/public.py:211 `search` | VE | Hotel not found. | HOTEL_NOT_FOUND |
| 9 | XA | api/public.py:247 | VE | Invalid hotel. | HOTEL_NOT_FOUND |
| 10 | S | api/public.py:215 | VE | Currency not offered. | CURRENCY_NOT_OFFERED |
| 11 | S | api/public.py:195 `_market` ← pricing/versions.py:90 | VE (title "Market") | market {code} is not available | MARKET_UNKNOWN (market) |
| 12 | S | api/public.py:195 ← versions.py:99-101 | VE | country {cc} belongs to markets {a, b}; choose one | MARKET_AMBIGUOUS (country) |
| 13 | S | api/public.py:195 ← versions.py:107 | VE | the market could not be determined; choose one explicitly | MARKET_REQUIRED |
| 14 | S B (O-8 new) | `_market`, `create_booking` | MarketRefused (417) | (new) | MARKET_NOT_ALLOWED; MARKET_RESIDENCY (countries) |
| 15 | S | services/quoting.py:422 `search` (unreach.) | VE | Unknown market {0}. | MARKET_UNKNOWN |
| 16 | S | services/quoting.py:155 `_dates` | VE | Check-out must be after check-in. | DATES_INVALID |
| 17 | XA | api/public.py:250 | VE | Invalid dates. | DATES_INVALID |
| 18 | S | services/quoting.py:157 | VE | Stays longer than {0} nights are booked by the reservations team. | STAY_TOO_LONG (max) |
| 19 | S | services/quoting.py:159 | VE | Check-in cannot be in the past. | CHECKIN_PAST |
| 20 | S | services/quoting.py:146, 148 `parse_rooms` | VE | At least one room is required. / At most {0} rooms per booking. | ROOMS_COUNT (max) |
| 21 | S MPr | services/quoting.py:124 `Party.parse` | VE | Each room needs 1–12 adults and at most 8 children. | PARTY_INVALID |
| 22 | S MPr | services/quoting.py:127 | VE | Each child needs an age. | CHILD_AGE_REQUIRED |
| 23 | S MPr | services/quoting.py:129 | VE | Child ages must be 0–17. | CHILD_AGE_INVALID |
| 24 | S MPr | services/quoting.py:84 `parse_dob` | VE | Invalid date of birth. | CHILD_DOB_INVALID |
| 25 | S MPr | services/quoting.py:95 `checked_dob` | VE | Child {0}: the date of birth cannot be in the future. | CHILD_DOB_FUTURE (child) |
| 26 | S MPr | services/quoting.py:96 | VE | Child {0} is {1} or older on arrival: add them as an adult. | CHILD_TOO_OLD (child, age) |
| 27 | Q QR | services/quoting.py:60, 62, 65 `verify` (kind offer) | VE | Invalid offer. | OFFER_INVALID |
| 28 | Q QR | services/quoting.py:73 `require_fresh` (kind offer) | VE | This offer has expired — please search again. | OFFER_EXPIRED |
| 29 | Q / QR | api/public.py:269 / :306 | VE | Invalid offer. | OFFER_INVALID |
| 30 | Q / QR | api/public.py:275 / :309 | VE | This extra cannot be booked online. | EXTRA_NOT_ONLINE |
| 31 | Q QR | services/quoting.py:491, 497, 522 `extra_items`/`_extras_list` | VE | Invalid extras. | EXTRAS_INVALID |
| 32 | Q QR | services/quoting.py:524 | VE | Invalid extra quantity. | EXTRAS_INVALID |
| 33 | QR | services/quoting.py:506 `room_items` | VE | Select between 1 and {0} rooms. | ROOMS_COUNT (max) |
| 34 | QR | services/quoting.py:510 | VE | Invalid rooms. | INVALID_REQUEST |
| 35 | Q | services/quoting.py:542 `_on_sale(refuse=True)` | VE | This rate is no longer on sale — please search again. | NOT_ON_SALE |
| 36 | Q QR | services/quoting.py:583 `_persist` | ContractNotOnSale | This rate is no longer on sale. Please search again. | NOT_ON_SALE |
| 37 | QR | services/quoting.py:631 `create_quotes` | VE | The rooms of one booking must come from one search. Please search again. | SEARCH_AGAIN |
| 38 | Q QR (race) | commercial/contracts.py:886, 890 `load_terms` | VE / PayloadMismatch | Contract version {0} is not published. / … failed its integrity check. (names the version) | NOT_ON_SALE / RATE_UNAVAILABLE (guest text without id) |
| 39 | Ba B | api/public.py:331 `_site_quotes` | VE | Select between 1 and {0} rooms. | ROOMS_COUNT (max) |
| 40 | Ba B | api/public.py:337, 339 | VE | Invalid quote. | QUOTE_INVALID |
| 41 | Ba / B | services/booking.py:344 `quotes_summary` / :610 `create_booking` | VE | All rooms of a booking must be at the same hotel. | SEARCH_AGAIN |
| 42 | Ba / B | services/booking.py:347 / :623 | VE | All rooms must share currency, market and channel. | SEARCH_AGAIN |
| 43 | B | services/booking.py:615 | VE | The rooms of one booking must come from one search, including its first room. Please search again. | SEARCH_AGAIN |
| 44 | B | services/booking.py:587, 589 (unreach.) | VE | Select at least one room. / Too many rooms. | ROOMS_COUNT |
| 45 | B (+Ba `problem`) | services/booking.py:606 ← quoting.py:668 `quote_is_usable` | VE | This rate is no longer on sale. Please search again. (quote Expired by a withdraw, O-13) | NOT_ON_SALE |
| 46 | B | booking.py:606 ← quoting.py:670 | VE | This quote was already used. | QUOTE_USED |
| 47 | B | booking.py:606 ← quoting.py:672 | VE | This quote has expired — please search again. | QUOTE_EXPIRED |
| 48 | B | services/booking.py:630 (unreach.) | Permission (403) | Not permitted. | SITE_CLOSED |
| 49 | B | services/booking.py:594 (O-15 unknown method), :643 (O-15 not offered) | VE | This payment method is not available. | PAYMENT_METHOD_UNAVAILABLE |
| 50 | B | services/booking.py:649 ← contracts.not_on_sale | ContractNotOnSale / ContractSuspended | This rate is no longer on sale. Please search again. | CONTRACT_NOT_ON_SALE / CONTRACT_SUSPENDED (existing class codes) |
| 51 | B | services/booking.py:668 | VE (title "Sold out") | Sorry — {0} has just sold out for {1}. | SOLD_OUT (room, date) |
| 52 | B | services/booking.py:678 | VE | This stay is no longer bookable: {0} | STAY_RESTRICTED (reason = restriction code) |
| 53 | B | services/booking.py:448, 458 `check_booking_basket` | VE | The rooms of this booking were not priced together… | BASKET_NOT_TOGETHER |
| 54 | B MXA MA | availability/extras_repository.py:155, 158 `check` (raised, no message) | ExtraSoldOut (417) | {0} is not available on {1}. / Sorry — {0} has just sold out for {1}. / Sorry — there is not enough {0} left for {1}. | EXTRA_SOLD_OUT (extra, date, closed) |
| 55 | B | services/booking.py:697 | VE | A bank transfer booking made online can hold at most {0} rooms… | WEB_TRANSFER_ROOMS (max) |
| 56 | B | services/booking.py:259 `amount_due_now` | VE | This rate cannot be paid at the hotel. | PAY_AT_HOTEL_NOT_ALLOWED |
| 57 | B Ba BS | services/booking.py:211 `_fixed` (rare) | VE | This rate's fixed amount cannot be converted: {0} | RATE_UNAVAILABLE |
| 58 | B | services/booking.py:72, 74 `_clean_guest` | VE | Guest first name is required. / Guest last name is required. | GUEST_FIRST_NAME_REQUIRED / GUEST_LAST_NAME_REQUIRED |
| 59 | B | services/booking.py:76 | VE | An email or phone number is required. | GUEST_CONTACT_REQUIRED |
| 60 | B | services/booking.py:80 | VE | Invalid email address. | GUEST_EMAIL_INVALID |
| 61 | B | services/booking.py:83 | VE | Name is too long. | GUEST_NAME_TOO_LONG |
| 62 | B | services/booking.py:905 `_check_redemption_limits` | VE | Promotion {0} has just been fully redeemed. | PROMO_EXHAUSTED (promotion) |
| 63 | B | services/booking.py:908 | VE | Promotion {0} needs the guest's e-mail address or phone number. | PROMO_NEEDS_CONTACT (promotion) |
| 64 | B | services/booking.py:910 | VE | Promotion {0} has already been used by this guest. | PROMO_ALREADY_USED (promotion) |
| 65 | B | api/public.py:449 `_start_booking_payment` | VE | This payment method is not available. | PAYMENT_METHOD_UNAVAILABLE |
| 66 | B PB PLk MA MCP | payments/service.py:325 `_busy` | PaymentBusy | A payment is being started. Please wait a moment and try again. | PAYMENT_BUSY |
| 67 | B PB PLk MA MCP | payments/service.py:352 `start_payment` | VE | Nothing to pay. | NOTHING_DUE |
| 68 | B PB PLk MA MCP | payments/service.py:356 | Permission (403) | This payment method is not available. | PAYMENT_METHOD_UNAVAILABLE |
| 69 | B PB PLk MA MCP | payments/service.py:159 `check_return_url` | VE | Invalid return address. | RETURN_URL_INVALID |
| 70 | B PB PLk MA MCP | payments/service.py:368 | VE | This payment was already processed ({0}). | PAYMENT_ALREADY_PROCESSED (status) |
| 71 | B PB PLk MA MCP | payments/service.py:378 | VE | This payment was started with another method or amount. | PAYMENT_MISMATCH |
| 72 | B PB PLk MA MCP | payments/service.py:184 `_refuse` (guest) ← `provider_for`/`check_account` | AccountRefused | This payment method is not available. | PAYMENT_METHOD_UNAVAILABLE |
| 73 | B PB PLk MA MCP | payments/service.py:450 (failed checkout, committed first — NEW-6) | VE | The payment could not be started. Please try another method. | PAYMENT_START_FAILED |
| 74 | B (re-raised public.py:468-469) PLk (2nd attempt :633-634) MA MCP (2nd try) | payments/service.py:480 `_supersede` (raised, no message) | ChargeSuperseded | The payment could not be started. Please try again. | CHARGE_SUPERSEDED |
| 75 | B(replay) PB PLk MA MCP | services/holds.py:203 `_expire_and_refuse` (raised; expiry committed first, P1-9) | HoldExpired | The time to pay for booking {0} is over; its rooms are no longer held. Please book again. | HOLD_EXPIRED |
| 76 | PB (transfer) | services/holds.py:270 `open_attempt` | HoldExpired | The time to pay for booking {0} by bank transfer is over. Please pay by card, or book again. | HOLD_EXPIRED_TRANSFER |
| 77 | PB | api/public.py:512 | VE | Nothing is due on this booking. | NOTHING_DUE |
| 78 | PB | api/public.py:514 | VE | This booking is cancelled. | BOOKING_CANCELLED |
| 79 | PB | api/public.py:519 | VE | This payment method is not available. | PAYMENT_METHOD_UNAVAILABLE |
| 80 | PL PLk | payments/service.py:1904 `link_by_token` | DoesNotExist (404) | This payment link is not valid. | LINK_INVALID |
| 81 | PLk | payments/service.py:822 `lock_link(nowait)` | PaymentBusy | A payment for this link is being started. Please wait a moment and try again. | PAYMENT_BUSY |
| 82 | PLk | payments/service.py:824 `lock_link` | DoesNotExist (404) | This payment link is not valid. | LINK_INVALID |
| 83 | PLk | api/public.py:587 `_link_due` | VE | This payment link is {0}. (expired / paid / cancelled / draft) | LINK_EXPIRED / LINK_PAID / LINK_CANCELLED / LINK_CLOSED (status) |
| 84 | PLk | api/public.py:592 ← payments/service.py:1858 `link_refusal` | VE | This payment link cannot be paid online. Please contact the hotel. | LINK_CURRENCY |
| 85 | PLk | public.py:592 ← service.py:1863 | VE | This payment link can no longer be paid: its booking cannot take payments any more… | LINK_BOOKING_CLOSED |
| 86 | PLk | public.py:592 ← service.py:1870 | VE | This payment link can no longer be paid: its booking is paid in full. | LINK_BOOKING_PAID |
| 87 | PLk | public.py:592 ← service.py:1871 | VE | This payment link asks {0} {1}, more than its booking still owes ({2} {1})… | LINK_OVER_OWED (amount, owed, currency) |
| 88 | PLk | api/public.py:609 | VE | This payment method is not available. | PAYMENT_METHOD_UNAVAILABLE |
| 89 | PLk | api/public.py:614 | VE | No card payment is configured for this link. | LINK_NO_CARD |
| 90 | PLk | payments/service.py:845 `link_charge_key` | VE | This payment link has had too many attempts. Please contact the hotel. | LINK_TOO_MANY_ATTEMPTS |
| 91 | MP | api/public.py:547 | VE | Not a sandbox payment. | SANDBOX_ONLY |
| 92 | MP | api/public.py:551 | ProviderError (500) | invalid mock signature | PAYMENT_SIGNATURE_INVALID (make it a coded VE) |
| 93 | MP | payments/service.py:499 `complete` | DoesNotExist (404) | Unknown payment. | PAYMENT_UNKNOWN |
| 94 | BS PB MC MPr MX MXP MXA MA MCP | api/public.py:750, 756, 760 `_booking_by_token` | Permission (403) | Invalid link. | MANAGE_LINK_INVALID |
| 95 | same | api/public.py:763 | Permission (403) | This link has expired. | MANAGE_LINK_EXPIRED |
| 96 | MC MPr MX MXP MXA MA | api/public.py:844 `_own_reservation`; services/guest_changes.py:453 `submit` | Permission (403) | Invalid reservation. | MANAGE_RESERVATION_INVALID |
| 97 | MCP | services/guest_changes.py:730 `pay_again` | Permission (403) | Invalid link. | MANAGE_REQUEST_INVALID |
| 98 | MC | api/public.py:854 | VE | Please contact the hotel to cancel. | SELF_SERVICE_OFF |
| 99 | MPr MX MXP MXA MA MCP | api/public.py:877, 913, 934, 950, 975, 992 | VE | Please contact the hotel to change your booking. | SELF_SERVICE_OFF |
| 100 | MC | api/public.py:858 (O-16) | ChangeRefused | This room can no longer be changed online. Please contact the hotel. | CANCEL_TOO_LATE |
| 101 | MC | services/booking.py `cancel_reservation` (Y-8; names the connection's label since 2K-3, LO-13) | VE | Sold by {0}: cancel it on the channel. | CHANNEL_BOOKING (guest text without the label) |
| 102 | MC | services/booking.py:1130 | VE | Reservation {0} is already {1}. | ROOM_NOT_ACTIVE (status) |
| 103 | MC | services/booking.py:1123, 1132 (unreach.: no waive, default reason) | Permission / VE | Guests cannot waive… / A cancellation reason is required. | INVALID_REQUEST |
| 104 | MPr MA | services/guest_changes.py:200 `guard` | PaymentPending | Please complete the payment of your booking before changing it. | PAYMENT_PENDING |
| 105 | MPr MA | services/guest_changes.py:203 | RefundPending | A refund of your earlier change is being processed… | REFUND_PENDING |
| 106 | MPr MA | services/guest_changes.py:206 | ChangeApplying | Your payment for an earlier change is being applied… | CHANGE_APPLYING |
| 107 | MPr MA MCP | services/guest_changes.py:231 `guard_room` (+ `_derive` :498) | ChangeRefused | This room can no longer be changed online. Please contact the hotel. | CHANGE_REFUSED |
| 108 | MPr | services/modification.py:346 `propose` (unreach. after guard_room) | VE | A {0} reservation cannot be modified. | ROOM_NOT_ACTIVE (status) |
| 109 | MPr | services/modification.py:349 | VE | This booking came from a channel: change it in the channel… | CHANNEL_BOOKING |
| 110 | MPr MA | services/modification.py:248 `_resolve` (names the market) | VE | No contract sold this stay for market {0} at {1}. | CHANGE_NOT_SELLABLE (guest text without market) |
| 111 | MPr MXP MXA | services/sold_terms.py:75 `refuse(guest=True)` | PayloadMismatch | This booking cannot be changed online right now. Please contact the hotel. | CHANGE_NOT_ONLINE |
| 112 | MPr | services/modification.py:65 `_snapshot` (rare) | VE | Reservation {0} was not priced by TEX; it cannot be re-priced here. | NOT_TEX_PRICED |
| 113 | MPr | services/modification.py:110 `build_changed_request` (unreach.: keys filtered at public.py:881-882) | VE | Cannot change: {0} | INVALID_REQUEST |
| 114 | MA MXA | services/quoting.py:60-65 `verify(kind="proposal"/"addon")` | VE | Invalid offer. | PROPOSAL_INVALID |
| 115 | MA MCP MXA | services/quoting.py:73 `require_fresh` (proposal/addon) | VE | This offer has expired — please search again. | PROPOSAL_EXPIRED |
| 116 | MA | services/modification.py:493 `require_proposer` | Permission (403) | This change was not proposed on your booking page. | PROPOSAL_INVALID |
| 117 | MA | services/guest_changes.py:463, 468 `submit` | CurrencyChanged | This change cannot be priced in the currency of your booking… | CURRENCY_CHANGED |
| 118 | MA MCP | services/guest_changes.py:500 `_derive`; services/modification.py:574 `apply` | VE | The reservation changed since this proposal was made — review it again. | RESERVATION_CHANGED |
| 119 | MA MCP | services/guest_changes.py:505; services/modification.py:598 | VE | The modified stay cannot be sold: {0} | CHANGE_NOT_SELLABLE |
| 120 | MA MCP | services/guest_changes.py:507; services/modification.py:610 | VE | The price moved since this proposal was made — review it again. | PRICE_MOVED |
| 121 | MA MCP | services/guest_changes.py:703 `_not_made` | VE | This change was not made: {0}. Please look at your booking and try again. | CHANGE_NOT_MADE (status) |
| 122 | MA MCP | services/guest_changes.py:758 `_start_payment` | VE | This payment method is not available. | PAYMENT_METHOD_UNAVAILABLE |
| 123 | MA | services/modification.py:551 (unreach. for guests) / :558 | Permission (403) | This proposal was made for another reservation… / This change cannot be made online. Please contact the hotel. | PROPOSAL_INVALID / CHANGE_NOT_ONLINE |
| 124 | MX MXP MXA | services/addons.py:34 `_snapshot` (rare) | VE | Reservation {0} was not priced by TEX; extras cannot be added here. | NOT_TEX_PRICED |
| 125 | MX MXP MXA | services/addons.py:40 `_open` | VE | This booking came from a channel: its price is the channel's. | CHANNEL_BOOKING |
| 126 | MX MXP MXA | services/addons.py:42 | VE | Extras can no longer be added to a {0} reservation. | ROOM_NOT_ACTIVE (status) |
| 127 | MXP | services/addons.py:62 `_requests` | VE | Choose the extras and how many. | EXTRAS_INVALID |
| 128 | MXA | services/addons.py:163 `apply` | VE | Invalid proposal. | PROPOSAL_INVALID |
| 129 | MXA | services/addons.py:177 | VE | The reservation changed since these extras were priced — please check them again. | RESERVATION_CHANGED |
| 130 | MXA | services/addons.py:181 (`q.reasons` already carry ADDON_* codes) | VE | "<reasons joined>" | EXTRAS_REFUSED (reasons: [ADDON_* codes]) |
| 131 | MXA | services/addons.py:183 | VE | The price moved since these extras were priced — please check them again. | PRICE_MOVED |

Already coded (Part 2K-3, LO-03): ROOM_NOT_SOLD, a room type disabled since the search — the quote's reason
(`quoting._stay_refusal`), `create_booking` and `modification.propose` (a change into it); the booking app reads it as
"expired" (`KIND_BY_CODE`). G-70b only gives it the catalogs' text.

Not refusals (already coded answers, unchanged): `quote`/`quote_rooms` `{ok: False, reasons:[{code}]}`
(`quoting.py:543-560`, engine codes), `manage_propose` `warnings` (`modification.py:392-418`, CURRENCY_CHANGED
public.py:894), `manage_extras_propose` `reasons` (ADDON_*), `booking_status.changes_blocked`.
Not guest-reachable (checked): `InventoryBusy` (`availability/repository.py:213-288`, writes outside TEX only),
`holds.hold_for_link` (:64, staff link creation), `extras_repository.bulk_update` (staff).

Proposed registry (≈85 codes): SITE_NOT_FOUND, SITE_CLOSED, RATE_LIMITED, BUSY, INVALID_REQUEST, NOT_FOUND,
NOT_PERMITTED, HOTEL_NOT_FOUND, CURRENCY_NOT_OFFERED, MARKET_UNKNOWN, MARKET_AMBIGUOUS, MARKET_REQUIRED,
MARKET_NOT_ALLOWED, MARKET_RESIDENCY, DATES_INVALID, STAY_TOO_LONG, CHECKIN_PAST, ROOMS_COUNT, PARTY_INVALID,
CHILD_AGE_REQUIRED, CHILD_AGE_INVALID, CHILD_DOB_INVALID, CHILD_DOB_FUTURE, CHILD_TOO_OLD, OFFER_INVALID,
OFFER_EXPIRED, EXTRA_NOT_ONLINE, EXTRAS_INVALID, SEARCH_AGAIN, QUOTE_INVALID, QUOTE_EXPIRED, QUOTE_USED,
NOT_ON_SALE, CONTRACT_NOT_ON_SALE, CONTRACT_SUSPENDED, RATE_UNAVAILABLE, ROOM_NOT_SOLD, BASKET_NOT_TOGETHER, SOLD_OUT,
STAY_RESTRICTED, EXTRA_SOLD_OUT, WEB_TRANSFER_ROOMS, PAY_AT_HOTEL_NOT_ALLOWED, GUEST_FIRST_NAME_REQUIRED,
GUEST_LAST_NAME_REQUIRED, GUEST_CONTACT_REQUIRED, GUEST_EMAIL_INVALID, GUEST_NAME_TOO_LONG, PROMO_EXHAUSTED,
PROMO_NEEDS_CONTACT, PROMO_ALREADY_USED, PAYMENT_METHOD_UNAVAILABLE, PAYMENT_BUSY, NOTHING_DUE,
RETURN_URL_INVALID, PAYMENT_ALREADY_PROCESSED, PAYMENT_MISMATCH, PAYMENT_START_FAILED, CHARGE_SUPERSEDED,
HOLD_EXPIRED, HOLD_EXPIRED_TRANSFER, BOOKING_CANCELLED, LINK_INVALID, LINK_EXPIRED, LINK_PAID, LINK_CANCELLED,
LINK_CLOSED, LINK_CURRENCY, LINK_BOOKING_CLOSED, LINK_BOOKING_PAID, LINK_OVER_OWED, LINK_NO_CARD,
LINK_TOO_MANY_ATTEMPTS, SANDBOX_ONLY, PAYMENT_SIGNATURE_INVALID, PAYMENT_UNKNOWN, MANAGE_LINK_INVALID,
MANAGE_LINK_EXPIRED, MANAGE_RESERVATION_INVALID, MANAGE_REQUEST_INVALID, SELF_SERVICE_OFF, CANCEL_TOO_LATE,
CHANNEL_BOOKING, ROOM_NOT_ACTIVE, CHANGE_REFUSED, PAYMENT_PENDING, REFUND_PENDING, CHANGE_APPLYING,
CHANGE_NOT_SELLABLE, CHANGE_NOT_ONLINE, NOT_TEX_PRICED, PROPOSAL_INVALID, PROPOSAL_EXPIRED, CURRENCY_CHANGED,
RESERVATION_CHANGED, PRICE_MOVED, CHANGE_NOT_MADE, EXTRAS_REFUSED.

---

## 6. ADR texts

### ADR-070 (new; insert between ADR-069 and ADR-071 in ARCHITECTURE_DECISIONS.md)
> ## ADR-070 Market integrity: markets per site, residents-only markets (audit Part 2G-2: O-8, G-55b; D-5)
> - *Markets per site.* `TEX Booking Site.allowed_markets` lists the markets a link may choose there (blank: every
>   enabled market, as before; the default market is always among them). A link's market outside the list is
>   refused (`MARKET_NOT_ALLOWED`, never "unknown"); a link's country picks among them, else the default.
> - *Residents-only markets.* `TEX Market.residency_required` (TR by the seed and p71, D-5). A web booking on such a
>   market needs a country of residence or a nationality among the market's countries, else it is refused
>   (`MARKET_RESIDENCY`) before any lock, and the refusal is audited outside the request (`booking.market_refused`,
>   once per quote and answer). Search refuses only a mismatch it already knows (the link's own country);
>   otherwise it prices and answers `residency`, and the guest declares residence at checkout. Eligibility is read
>   from the market when booking, never from the frozen payload, and never changes a price.
> - *Staff.* In the Call Center a mismatch is refused unless the agent books anyway with a reason
>   (`market_override`), audited `booking.market_override` (market, its countries, the guest's country and
>   nationality, reason). Staff booking on a booking site follow the site's rules (ADR-050). Channel bookings are
>   the channel's; a staff modification into a residents-only market is not checked (its revision is the record).
> - *Refused links (G-55b).* The booking app searches again without the link, says so, and sends the browser
>   funnel event `market_refused` (refusal code, an existing market code, an ISO country; ADR-056 allow-list).
> - p71 syncs TEX Market and TEX Booking Site and makes TR residents-only once (`ran_before`); p72 adds the funnel
>   event option. Owner choice left: the override capability (`reservation.create` + reason, or `price.override`).

### ADR-013 amendment (G-70) — "TEX i18n catalogs"
> *Guest refusals (audit Parts 2G-2 and 2G-3, G-70a/G-70b).* Every refusal of the guest API carries a stable code
> (`kamra/tex/refusal_codes.py`; `Refusal.code`, guest-safe `params`) that `refusals.coded` puts in the error
> body (`tex_code`, `tex_params`) next to Frappe's `exc_type` and message. The booking app classifies by code
> (never by wording) and shows `refusal.<CODE>` from its six catalogs; the English server text stays for staff,
> API clients and logs. Params never carry a token, an e-mail or an internal id. A new guest refusal without a code
> fails `unit/test_guest_refusal_codes`; catalog parity is `check.ts` (keys) and `i18n:tex` (placeholders).

### ADR-026 amendment (G-71) — "Guest-facing hotel content is localised after pricing" (+ note on ADR-009)
> *Guest answers name no contract (audit Part 2G-3, G-71).* After localisation, guest answers drop the contract
> block, the pricing request, the offer's contract code and market, engine reason texts (codes and limits stay),
> and `market`/`channel` from search, quote, booking and the manage view; staff answers are unchanged. The signed
> `offer_key` still carries contract, version and market in its readable body (ADR-009): accepted (signed, not
> secret; encrypting it would change every offer path).

### ADR-056 amendment (G-55b)
> `public.track` also takes `market_refused`: `reason` one of the five market codes, `market` only an existing
> market code, `country` two letters; nothing else.

---

## 7. Docs and status to update (per item commit)
- `docs/tex-engine/IMPLEMENTATION_STATUS.md`: new "§6G2. Audit Part 2G-2" (G-70a, O-8, G-55b) and later "§6G3. Audit Part 2G-3" (G-71, G-70b), with tests;
  rows R-13 (:1375, G-55 closed), R-49 (:1411, guest refusals coded; staff/server catalogs remain), R-52 (:1414,
  guest payloads; bundle budgets remain).
- `docs/tex-engine/FINAL_GAP_AUDIT.md` rows 45 (G-55), 57 (G-70 guest part), 58 (G-71 guest payload part).
- `docs/tex-engine/GO_LIVE_READINESS.md`: configuration line — set each site's allowed markets; confirm the
  residents-only markets (TR by default, D-5).
- `docs/tex-engine/ARCHITECTURE_DECISIONS.md`: §6 texts.

## 8. Commands (from CLAUDE.md / CI)
- `python -m pytest kamra/tex/tests/unit -q` (pure: TestMarket, test_guest_refusal_codes).
- `bench --site test.localhost run-tests --module kamra.tex.tests.integration.test_public_booking` (+
  `test_patches`, `test_commercial_flows`, `test_hold_payment_race`, `test_distribution`, `test_channel_binding`,
  `test_security_regressions`, `test_self_service_money`, `test_post_booking_extras` — they call the public API).
- `cd frontend && npm run build && npm run test:unit && npm run i18n:tex`; Playwright `booking.spec.ts`,
  `guest-refusals.spec.ts`, `guest-session.spec.ts` (O-27 no token in URLs), `pay-link.spec.ts`, `manage-money.spec.ts`.

## 9. Verified vs assumed (summary)
Verified: every file:line above (at aac444a4); public payload shapes; `resolve_market`'s unused `allowed`; no TR use
in tests; Guest.nationality default "Indian"; booking app classification by wording (node probe); i18n:tex skips the
booking catalogs and the current catalogs pass parity (probe); generator drift of 9 JSON stamps (ran in a copy);
Frappe v16 `msgprint` instance semantics, `report_error`/`as_json` serialising `frappe.local.response`, per-request
`local.response`, `inspect.signature` arg filtering, `rate_limit` uses `functools.wraps` (GitHub `version-16`
sources). Assumed: the bench runs Frappe matching that branch; Playwright exposes `sendBeacon` bodies; Frappe fills
`Guest.nationality`'s default on insert when TEX passes `None` (affects only the "never read it" pitfall).
