# TEX Engine — Handover: the work left after audit Part 2 (2026-10-01)

**Read this whole file before changing anything.** It replaces the 2026-09-26 handoff (that version is in git
history). It is written for the session that finishes the remaining work: you implement, verify your own work (there
is no separate controller session any more) and open one pull request per batch. The owner, who writes in Turkish,
reviews and merges. You never merge, never push to the base branch, never rebase or force-push a shared branch.

Recover state in this order (CLAUDE.md): `CLAUDE.md` → this file → `IMPLEMENTATION_STATUS.md` (§6 sections) →
`TARGET_ARCHITECTURE.md` → `ARCHITECTURE_DECISIONS.md` (ADR-062 … ADR-071) → `PRODUCT_SPEC.md` → `git log` and the
descriptions of PRs #3–#16 (each has the batch's items, its fail-first evidence and its leftovers).

## 1. Where things stand

- Base branch: `claude/inspiring-ptolemy-i6wdu2`. At handover it is `aac444a4` (merge of PR #16) plus the pull
  request that adds this file. Every change reaches it through a pull request with GitHub CI.
- Audit Part 1 is complete (PR #1, PR #2). Audit Part 2, stages 1 and 2, are complete — 14 batches, all merged:

| Batch | PR | Contents |
|---|---|---|
| 2A critical & quick safety | #3 | DOC-0, NEW-1 (+ nullable-date guard, scheduler smoke test), Y-1, Y-10, O-16, Y-12 |
| 2B money on bookings | #4 | P1-6, Y-7(+b), P1-3, P1-7, P1-5 + O-38, P1-10, O-19, P1-11 + NEW-3 |
| 2C-1 policy money | #5 | Y-4, Y-3 A, O-2 |
| 2G-1 guest-facing (no public.py) | #6 | O-28, O-27, G-62, G-44, O-32, O-29/O-30 |
| 2C-2 pricing engine | #7 | Y-5, O-1, O-4, O-7, O-31, G-57, G-53 |
| 2I security & supply chain | #8 | NEW-8, G-97, O-37, NEW-5 |
| 2E-1 payment start | #9 | Y-3 B, NEW-6 |
| 2D-1 contract lifecycle | #10 | Y-2 + O-13, O-10, O-9 + G-47 |
| 2E-2 providers & recovery | #11 | P1-8, NEW-2, O-18, P1-1, P1-9 |
| 2D-2 FX | #12 | 2D-1 leftovers, O-11, O-12 |
| 2H-1 loyalty lots & CRM | #13 | Y-11 + O-22, O-21, G-66, O-23, O-26, O-33 |
| 2H-2 points back, expired holds | #14 | 2H-1 leftover, O-20, O-24 |
| 2F-1 locks, expiry, PMS queue | #15 | P1-4, restarted payment (1b), NEW-7, P1-2 |
| 2F-2 methods, pool, channels | #16 | O-15, Y-9, Y-8 |

- Last full CI (PR #16 head `ebf5e420`, CI run #160, Linters #159, Supply chain #40): green on all three workflows.
  Numbers to keep green: eval harness 76/76, banquet 101, TEX unit 659, TEX integration 44/44 modules (1,193 tests),
  front-desk journey 13/13, Playwright 177 passed / 2 skipped (by design), frontend node unit 360, DOM 42, i18n
  complete in 6 languages.
- The repository is **public** and its default branch is the base branch: never commit secrets, credentials, real
  guest data or anything private.
- Three implementing sessions ran in parallel (Money, Pricing, Guest/Security/CRM) under a controller. From now on one
  session does the rest, batch by batch, as below.

## 2. The remaining work, in order

One session, one batch at a time, one pull request per batch. The owner merges; the next batch starts from the new
base. The cards, with current file:line, fix design, fail-first tests and pitfalls, are in three appendices:

- `docs/tex-engine/HANDOFF_STAGE3.md` — Stage 3, the `api/public.py` chain (O-8, G-55b, G-71, G-70), with a
  131-row inventory of guest-reachable refusals and the ADR texts;
- `docs/tex-engine/HANDOFF_LEFTOVERS.md` — every functional leftover of Part 2 still open (LO-01 … LO-49), what later
  PRs already fixed, the proposed batches A–G and the items that wait for an owner decision (C-01 … C-16);
- `docs/tex-engine/HANDOFF_RELEASE.md` — 2Z, release hygiene (bundles, Frappe upgrade, OAuth, CI pins, the flaky
  channels spec, the docs refresh with ~45 stale statements listed).

Everything was verified statically at `aac444a4` on 2026-10-01 (three independent read-only passes, key claims
spot-checked) — re-verify each card before you change code (§3).

| # | Batch → PR name | Items, in order | Severity | Needs |
|---|---|---|---|---|
| 1 | **3A market integrity** → "2G-2" — **merged (PR #18)** | G-70a (the coded refusal transport) → O-8 (+ p71, ADR-070) → G-55b (+ p72) | HIGH | D-5 and the CRS override capability (§7) |
| 2 | **K-B payments** → "2K-1" — **merged (PR #19)** | LO-04, LO-05, LO-07, LO-16, LO-17, LO-19, LO-21, LO-18 | MED | — |
| 3 | **K-A points always come back as points** → "2K-2" — **done (2K-2 PR, §6K2)** | LO-01 (O-19b), LO-02, LO-06, LO-23, LO-24, LO-25, LO-26 (verify first), LO-47 (decide first) | MED | D-12 (default: loyalty is live) |
| 4 | **K-C channels and disabled room types** → "2K-3" | LO-03, LO-13, LO-11, LO-09, LO-15 | MED | — |
| 5 | **3B guest payloads and codes** → "2G-3" | G-71 → G-70b (+ LO-12; LO-30 optional) | MED | — |
| 6 | **K-D operations** → "2K-4" | LO-08, LO-10, LO-28, LO-39, LO-37, LO-22, LO-20, LO-48 | LOW | LO-37 ties to D-13 |
| 7 | **K-E guest booking frontend** → "2K-5" | LO-35, LO-14, LO-32, LO-33, LO-31, LO-49 (+ LO-30 if 3B left it) | LOW | after 3B |
| 8 | **K-F staff frontend + K-G tests and tooling** → "2K-6" (or two PRs) | LO-34, LO-38, LO-40, LO-45, LO-42a, LO-27; LO-46, LO-36, LO-44, LO-29, LO-41, LO-42b, LO-43 | LOW | — |
| 9 | **2Z release hygiene** → "2Z" | §2.3 | MED | **last** |
| — | Conditional | O-6 hotel-local time (D-13), the pre-upgrade migration package (D-14), G-69r PMS adapters (D-15), the no-show points policy (C-01) and C-02 … C-16 | — | the owner |

Order rules:
- **Severity first:** the one HIGH item (O-8) goes first; G-70a is its small prerequisite (the booking app can only
  recognise a refusal by its English wording today, so a market refusal could not be shown or counted).
- **Every new guest-reachable refusal written in batches 2–4 uses G-70a's coded `Refusal` from the start** (codes:
  `HANDOFF_STAGE3.md` §5f). Batch 5 (G-70b) then codes everything left and switches the booking app to classify by
  code. That is why G-70b comes after the money batches.
- Batch 7 edits files G-70b rewrites (`booking/lib/api.ts`, `Checkout.tsx`, the pay-link page): after batch 5.
- **All frontend work lands before 2Z**, which rebuilds the committed bundles once.
- IMPLEMENTATION_STATUS sections: 6G2, 6K1, 6K2, 6K3, 6G3, 6K4, 6K5, 6K6, 6Z.

### 2.1 Stage 3 in short (details: `docs/tex-engine/HANDOFF_STAGE3.md`)
- **G-70a (S):** a coded `Refusal` exception (code + params), a `functools.wraps` decorator that copies the code into
  the JSON error body (Frappe v16 serialises `frappe.local.response`), `ApiError.code` in the booking app. Keep the
  static retry-wrapper tests green (they walk `__wrapped__`).
- **O-8 (M, HIGH):** `TEX Booking Site.allowed_markets` (blank = every enabled market) and
  `TEX Market.residency_required` (TR = 1 by p71); search refuses only a market the site does not sell
  (`MARKET_NOT_ALLOWED`) or a residents-only market with a contradicting link country (`MARKET_RESIDENCY`), otherwise
  prices and says `residency`; `create_booking` enforces the guest's declared country of residence or nationality
  before any contract/night lock; web refusals are audited; the CRS gets country and nationality fields and an
  override with a reason, audited. ADR-070.
- **G-55b (S):** a refused market link is shown to the guest and counted as a funnel event (the event field is a
  Select: new option + p72, else `_track` swallows the validation error).
- **G-71 (S):** no contract identity (id, code, name, version, payload hash, market) in public search / quote /
  quote_rooms / book / booking_status answers; staff APIs keep it; the signed `offer_key` stays (documented residue).
- **G-70b (M–L):** a stable code on every guest-reachable refusal (inventory of 131 sites), messages in the booking
  app's 6 catalogs, classification by code. Fix `npm run i18n:tex` first: its booking root
  (`src/booking/i18n/locales`) does not exist, so it silently checks nothing there.

### 2.2 The leftovers in short (details: `docs/tex-engine/HANDOFF_LEFTOVERS.md`)
No HIGH item. Five MED: LO-01 (a lower price on a booking paid with points never gives the points' share back as
points), LO-02 (points can be redeemed on, or moved onto, an OTA booking; a channel cancellation never returns them),
LO-03 (a disabled room type is still sold through ARI, old offer keys and staff modifications), LO-04 (a reused charge
settled during its checkout call still hands out a new checkout URL; a second capture would be silent), LO-05 (a
second payment can start during an iyzico fraud review) — LO-04 and LO-05 are fixed in Part 2K-1. The legacy `kamra.api.cancel_reservation` path already
refuses TEX bookings (not reproducible). 21 earlier leftovers were fixed by later PRs.

### 2.3 Release hygiene (2Z) in short (details: `docs/tex-engine/HANDOFF_RELEASE.md`)
- **NEW-4 bundles (M):** the committed bundles (`kamra/public`) are 69 source commits behind, so deployments serve none
  of Part 2's frontend fixes. The build stamps the git commit into the bundle (`frontend/vite.config.ts`), so a plain
  "build and `git diff`" check would fail on every PR: stamp only when `TEX_BUILD_COMMIT` is set (ADR-060 amendment),
  let Tailwind scan `src/` only, fix `.gitignore` (`yarn.lock`, the `kamra/public/node_modules` link), add two CI checks
  (frontend job and bench path), then rebuild as the **last** code commit. From then on every frontend change commits
  its rebuilt bundles and CI enforces it.
- **Frappe upgrade (M, optional):** no Frappe v16 release closes the 14 PyJWT/oauthlib advisories of PR #11 (only v17
  moves those pins); v16.36.1 would close 32 of the other 53 reviewed advisories. Own PR or inside 2Z.
- **OAuth (S):** Frappe's dynamic client registration is on by default and TEX never uses Frappe's OAuth provider:
  switch it off at install and with a one-time patch, written with `get_single().save()` (`set_single_value` silently
  blanks the other OAuth settings); tests; a GO_LIVE line. Also LOW: the legacy MCP `/mcp/oauth/register` lets a guest
  register a client without a rate limit.
- **CI hygiene (S):** pin the Semgrep rules, CLI and registry pack (weekly drift run against the newest rules); pin the
  `payments` app to one commit in CI and supply-chain (a test keeps the pins in sync); run CI on pushes to the base
  (nothing re-checks the base after a merge today).
- **`channels.spec.ts` flake (S–M):** not the network — a product race: a reopened drawer shows the previous form for
  a frame and loses the first keystrokes (8 sibling drawers share the pattern). Mount the drawer per opening, add a
  first-frame e2e check, correct PR #12's / §6D2's explanation.
- **Docs (M):** ~45 stale statements with file:line and the correct fact; every Part 2 status; the final CI numbers;
  rewrite this HANDOFF.md last.

## 3. How to work — the method that kept Part 2 free of regressions

Per batch:
1. **Re-verify every card against the current code before you change it.** The cards below were verified at
   `aac444a4`; line numbers drift — find code by function name. If a card's "today" value or premise is no longer
   true, stop and correct the card (and tell the owner in one line) instead of forcing the fix.
2. Bring your branch onto the base: `git fetch origin claude/inspiring-ptolemy-i6wdu2` and
   `git merge --ff-only origin/claude/inspiring-ptolemy-i6wdu2` (if your branch carries already-merged history only).
   Push and open a **draft** PR into the base using `.github/PULL_REQUEST_TEMPLATE.md` (its "develop" checkbox does not
   apply: the target is the audit base).
3. Per item: **write the failing test first and run it** (keep the red output: it goes in the PR body), then fix,
   run the targeted modules locally, **one commit per item** (Conventional Commits), push, go on. Do not wait for
   GitHub CI on intermediate heads (the workflow cancels them).
4. Docs in the same batch: an addendum to the relevant ADR (or the reserved/new ADR), a section
   `## 6<X>. Audit Part <batch> (date)` at the END of `IMPLEMENTATION_STATUS.md`, at most one line per item, with
   COMPLETE / PARTIAL / NOT STARTED / BLOCKED.
5. **Self-review before you call it ready** (there is no controller): give an independent read-only reviewer (a
   subagent) only the card text and `git diff origin/<base>...HEAD`, and ask it to check every bullet, hunt for
   regressions on shared paths (lock order, money, nullable dates, permissions, tenant scope) and confirm each
   fail-first claim. Fix what it finds; at most two review rounds per item; list the rounds in the PR body.
6. Before "ready": fetch the base; if it moved, MERGE it (never rebase), keep both sides (end-of-file conflicts in
   `IMPLEMENTATION_STATUS.md` are normal: keep both sections), rerun the targeted tests, push.
7. The **last head must be fully green**: CI + Linters + Supply chain. Quote the run numbers. Never call CI green
   without the run.
8. PR body: per item — commit, problem, fix, test with the fail-first evidence; "Breaking changes / notes";
   "Kalanlar" (what you found and did not fix); CI section (run numbers of the final head, local numbers).
9. Tell the owner, in Turkish and briefly, what is ready, and give explicit GitHub steps:
   "PR #N → Ready for review → Merge pull request → Confirm merge". Ask only for real decisions.
10. After the merge, start the next batch from the new base.

## 4. Rules that are not negotiable (CLAUDE.md + what Part 2 learned)

- **Money:** `decimal.Decimal` end to end (`kamra.tex.money`); `str` in JSON, never float. Prices come from the frozen
  published payload; confirmed reservations are price-locked; `ENGINE_VERSION` is never bumped (`test_main_parity`).
  No LLM computes a price.
- **No lock is held through a gateway call** (ADR-066). **One lock order** (ADR-066 "Locks", Part 2F-1): quote(s) →
  contract → contract version → payment link → charge(s) → booking(s) → reservations → nights → extra days → Guest →
  promotions → allocation / ledger / redemption rows (locking reads). Money going out (expiry, refunds, the points
  return) takes booking → charges: an accepted inversion, retried.
- **Deadlocks:** every write endpoint that takes these locks is wrapped with `retry_on_deadlock`
  (`kamra/tex/services/txn.py`); a request that committed a step (`note_committed_step`) is never run again; a
  savepoint lost to a deadlock or a step commit is undone with `txn.undo_to` (MariaDB 1305 → whole rollback, nothing
  else). Never a bare `except`.
- **MariaDB:** REPEATABLE READ with `innodb_snapshot_isolation` OFF (ADR-063; CI sets it). The first plain read fixes
  the read view; state you decide on after taking a lock must be read with a locking read.
- **Nullable dates** (ADR-064): Frappe v16 renders a nullable Date/Datetime filter as `IFNULL(col,'0001-01-01')`. Never
  filter a nullable date through `get_all`/`get_value` without saying what NULL means; use raw SQL with explicit NULL
  semantics and a comment. `kamra/tex/tests/unit/test_nullable_date_filters.py` guards it.
  `frappe.utils.get_datetime(None)` returns *now*.
- **Security:** every whitelisted endpoint checks capability + property scope (`scope.require(cap, property)`);
  hiding in the frontend is never enough; tenant isolation Enterprise → Hotel Group → Hotel. Never log passwords,
  CVV, PAN, secrets or raw tokens. Public endpoints: rate limited, validated server-side, idempotency keys on writes.
- **Schema:** TEX DocTypes are generated from `kamra/tex/devtools/doctype_specs.py`. Kamra DocTypes (Reservation,
  Room Type, Property …) get TEX fields through `kamra/tex/devtools/extend_kamra.py` `EXT`, and the DocType JSON
  `"modified"` must be bumped past its current stamp, or migrate skips the field.
- **Patches:** `kamra/patches/tex/pNN_<name>.py`, listed in `kamra/patches.txt` in **sorted order within its
  section** (`[pre_model_sync]` / `[post_model_sync]`), plus a `BEHAVIOUR` entry in
  `kamra/tex/tests/integration/test_patches.py`; test with `first_run` and a second run that changes nothing. Patch
  tests run only on a disposable site (`docs/tex-engine/DEV_ENVIRONMENT.md`).
- **Tests:** fail-first; never change an existing assertion (setup or call changes only, declared in the PR body).
  Fixtures that commit (thread tests) must clean up: CI runs every integration module alphabetically on ONE site, so
  committed rows leak into later modules (`test_concurrency.PROPERTY_TABLES` cleans them). The scheduler smoke test
  (`test_scheduler_smoke`) must stay green. Check the real "today" value before you write a fail-first assertion.
- **Frontend:** strings through i18n `t()` in 6 languages (de, en, pl, ro, ru, tr; `npm run i18n:tex` — note that it
  does not check the booking app's catalogs until G-70b fixes its path), TEX design-system components in
  `frontend/src/tex/ui`. **Bundles:** until 2Z, never commit `kamra/public` (CI's Playwright builds from the PR's
  source); 2Z makes the build reproducible, rebuilds once and adds a drift check — from then on every frontend change
  commits its rebuilt bundles.
- `kamra/tex/api/public.py` is changed only by the Stage 3 chain, in its order.
- Legacy Kamra PMS code stays (hidden from TEX navigation). Keep AGPL notices and upstream headers.

## 5. Environment and CI

- Local bench: `docs/tex-engine/DEV_ENVIRONMENT.md` (Frappe v16.25.0, Python 3.14, Node 24, MariaDB 11.x with
  `innodb_snapshot_isolation` OFF, Redis, `payments` app develop). Pure tests: `python -m pytest kamra/tex/tests/unit -q`.
  Integration: `bench --site test.localhost run-tests --module kamra.tex.tests.integration.<mod>`.
- GitHub workflows on every PR:
  - **CI**: "Python lint (ruff)", "Frontend typecheck & build" (build, node unit, DOM checks, i18n, bundle checks),
    "Backend eval harness" (~35–40 min: eval 76/76, banquet, TEX unit, every TEX integration module, front-desk
    journey, fresh install, Playwright E2E).
  - **Linters**: "Semgrep Rules" (frappe/semgrep-rules cloned unpinned: a new upstream rule can turn the base red),
    "Marketplace install simulation".
  - **Supply chain**: "Secrets (gitleaks)", "npm dependencies (audit-ci)", "Python dependencies (pip-audit)" with
    reviewed ignores in `.github/supply-chain/pip-audit-ignore.txt` (one reason per advisory).
- A check that is red on the base too is not your PR's: say so in the PR, fix it only if it is in scope or the owner
  agrees; never skip, disable or quarantine a test, never push an empty commit to re-run CI.
- New advisories appear without any code change: on 2026-10-01, 16:38–16:44 UTC, eight pypdf advisories turned
  pip-audit red for every PR; PR #17 reviewed them by the file's convention (a fix outside Frappe's pin, TEX code does
  not import pypdf). Do the same for the next ones — one line per advisory with its reason and a review date — and
  upgrade instead whenever the pin allows it.

## 6. Numbers

- Patches are numbered up to p70 (p57 sits in `[pre_model_sync]`). **p67 was never
  used — do not use it. Next free: p71.**
- ADRs used up to ADR-071. **ADR-070 is reserved for O-8 (market integrity).** Next free: ADR-072.
- The appendices were verified independently and both propose p71 (O-8 in STAGE3, the OAuth patch in RELEASE). In the
  batch order of §2: O-8 = p71, G-55b = p72, then any leftover patch (e.g. LO-22's `last_reverified_at`), the OAuth
  patch of 2Z last. **Always take the next free number at the moment you write the patch or the ADR.**
- `IMPLEMENTATION_STATUS.md` sections so far: 6, 6B, 6C1, 6C2, 6G1, 6D1, 6E1, 6I, 6E2, 6H1, 6D2, 6F1, 6H2, 6F2.
  Suggested next: 6G2 / 6G3 (Stage 3), 6K1… (leftover batches), 6Z (release hygiene).

## 7. Owner decisions

Taken (applied in Part 2): D-1 FIXED deposit per booking, a policy without currency = the contract's; D-2 infants are
not children for new contracts; D-3 promotion group text fixed, engine unchanged; D-4 a dated manual FX rate (Finance /
Revenue, audited) bridges a stale provider; D-6 no guest online cancel from the arrival day; D-7 money without a
gateway time → Action Required, never an automatic refund; D-8 iyzico fraud review keeps the booking pending
(rejection → team notice + audit; a missing fraudStatus counts as under review); D-9 a later change keeps a manual
price override; D-10 an EUR booking cannot be paid in TRY; D-11 an OTA booking is cancelled on the channel (override:
`reservation.cancel` + `channel.manage` + reason, audited); D-16 burned points come back on cancellation, as points
(D-16a: a returned point whose lot expired expires at once); D-17 the abandoned-booking phone only with SMS/WhatsApp
consent; D-18 the minimum basket includes extras and needs a currency. Defaults the audit applied as well: P1-2
identity = profile / guest e-mail / guest phone, never the booker's e-mail; O-15 rules bind where a rule matches,
"Payment Link" is staff-only, a `None` method stays unchecked; a restarted Pending charge is a new attempt; manual FX
= the provider's reference rate, the policy margin on top; O-20: points first and only beyond the new total, a kept
fee keeps its points, a revival never spends returned points again; pilot Loyalty payments in reconciliation are
allocated by staff (no patch).

Open (ask the owner when the batch needs it; never guess):
- **D-5** (Stage 3, O-8): which markets are residency-restricted and what a mismatch does. Recommended default:
  per-site allowed markets (blank = every enabled market); the TR (domestic) market only for a guest whose declared
  country of residence or nationality is TR; a mismatch is refused at web booking and audited; staff may override in
  the CRS with a reason, audited.
- **The CRS override capability** (O-8): default `reservation.create` + a reason (every call-centre agent, audited);
  the stricter option is `price.override` (revenue managers and admins only).
- **D-13**: do the UTC+7 hotels (Cam Ranh, Phuket) go live on this site in wave 1?
  If yes, O-6 (deadlines in hotel-local time; today they close 4 h late there) becomes a batch.
- **D-14**: will an existing Kamra or pilot database be upgraded? If yes, the pre-upgrade migration package (O-34,
  O-35, O-36, O-39, P1-12) becomes a batch.
- **D-15**: which PMS runs each go-live hotel (G-69r adapters).
- Points policy for No Show, a lower price (O-19 credit) and a channel's cancellation (today: no points back).
- Smaller open questions, listed with their defaults in `HANDOFF_LEFTOVERS.md` §3: who may drop a revenue manager's
  manual price (C-02), SMS/WhatsApp-only guests in the abandoned list (C-03, default anonymous), members-only
  promotions (C-04), folding Ş/Ğ/Ü/Ö/Ç in promotion codes (C-12, default no).
- Not in scope unless the owner asks: G-41r allotment × channel, G-54 surcharges by LOS/arrival, G-64 CRM campaigns.

## 8. Go-live work outside the code (owner / IT; runs in parallel)

Payment providers (iyzico, Sipay, NestPay) sandbox + production credentials and a certification run (unblocks
`production_verified`, P1-1's time field, O-18's notification URL, Sipay refunds, the half-3D policy, a NestPay
status query); SMTP account and sender domain with SPF/DKIM; a channel-manager provider and its certification (Y-8 goes
live); the PMS of each hotel; backups and a restore rehearsal, a rollback rehearsal on staging, the deploy pipeline and
registry, uptime monitoring and alert recipients, log shipping, TLS for custom hosts; a security contact in
`SECURITY.md` and an external penetration test; the legal basis for abandoned-booking contact and the İYS brand code;
the source data and a cut-over date. `GO_LIVE_READINESS.md` tracks them.

## 9. Pitfalls that cost a cycle in Part 2 (avoid them)

- Line numbers in a card are hints; the function name is the address.
- "Today" values in fail-first tests must be checked against the real code (a pool key that sorts first, a profile
  that lacks a capability: Revenue Manager has `channel.manage` but not `reservation.cancel`).
- `public.book` defaults the method to "Card"; `HoldCase.book` calls `create_booking` directly as Administrator.
- `fx.ensure` is get-or-create: a generic rule added to a shared fixture shadows a class's own rule with an account.
- Thread tests commit: clean what they commit, or later modules see it (seven unrelated tests once failed this way).
- `get_all` with a nullable date filter; `get_datetime(None)`; a plain read after a lock (stale view).
- A savepoint does not survive a deadlock or a commit (`txn.undo_to`).
- A new upstream Semgrep rule or a new CVE advisory can turn the base red overnight: handle it in its own small PR
  with a reviewed reason, not by weakening the check.
- `python -m kamra.tex.devtools.doctype_gen` rewrites every TEX DocType JSON from the specs and rolls back 9
  hand-bumped `modified` stamps: commit only the JSONs you meant to change. `SB()`/`CB()`/`TAB()` share one global
  counter: adding a section or column break renames every later one — add plain fields.
- Frappe Singles: `frappe.db.set_single_value` on a never-saved Single stores one row and blanks the others' defaults;
  use `frappe.get_single(...)` + `.save()`.
- `frappe.throw(msg, exc_instance)` raises that instance (its attributes survive); a bare `raise X()` sends the guest
  no message at all (only `exc_type`).

## 10. First steps for the session that takes over

1. Read `CLAUDE.md`, this file, then the appendix of the batch you start; skim the PR #16 description (the latest
   example of a complete batch PR).
2. Set up the bench (`docs/tex-engine/DEV_ENVIRONMENT.md`) and run the pure unit tests and one integration module to
   prove it works.
3. Ask the owner, in Turkish, the questions batch 1 needs (D-5 and the CRS override capability) — unless the prompt
   that started you already answers them. Use the recommended defaults only if the owner says so.
4. Start batch 1 (3A) as in §3. Keep this file current: when a batch merges, mark it in §2 (PR number) in your next
   batch's docs commit.
