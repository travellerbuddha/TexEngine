# TEX Engine — Handover after audit Part 2 and C-04 (2026-10-04)

**Read this whole file before changing anything.** It replaces the 2026-10-01 handoff (that version is in git history).
Audit Part 2 is finished: every planned batch is done, Part 2Z (PR #29) the last; the Frappe v16.36.1 upgrade followed
as 2Z-F (PR #30), the LOW leftovers that need no decision as 2L (PR #31), four owner decisions as 2M (PR #32), members-only prices
in the call centre as 2N-1 (C-04, first half, PR #33) and on the web as 2N-2 (C-04's second half, PR #34). What is
left waits for an owner decision, an external party, or is a LOW leftover listed below; the next batch is chosen with
the owner (§2, §10). The session that takes over implements, verifies its own work and
opens one pull request per batch; the owner, who writes in Turkish, reviews and merges. Never merge, never push to the
base branch, never rebase or force-push a shared branch.

Recover state in this order (CLAUDE.md): `CLAUDE.md` → this file → `IMPLEMENTATION_STATUS.md` (§6 sections, newest
last) → `TARGET_ARCHITECTURE.md` → `ARCHITECTURE_DECISIONS.md` (ADR-062 … ADR-078) → `PRODUCT_SPEC.md` → `git log` and
the descriptions of PRs #3–#34 (each has its items, fail-first evidence, review rounds and "Kalanlar").

## 1. Where things stand

- Base branch (and the repository's default branch): `claude/inspiring-ptolemy-i6wdu2`. Every change reaches it through
  a pull request with GitHub CI; since 2Z, CI, Linters and Supply chain also run on every push to it.
- The repository is **public**: never commit secrets, credentials, real guest data or anything private.
- Audit Part 1 (PRs #1, #2) and audit Part 2 are complete:

| Batch | PR | Contents (status section) |
|---|---|---|
| 2A critical & quick safety | #3 | DOC-0, NEW-1, Y-1, Y-10, O-16, Y-12 (§6) |
| 2B money on bookings | #4 | P1-6, Y-7(+b), P1-3, P1-7, P1-5 + O-38, P1-10, O-19, P1-11 + NEW-3 (§6B) |
| 2C-1 policy money | #5 | Y-4, Y-3 A, O-2 (§6C1) |
| 2G-1 guest-facing | #6 | O-28, O-27, G-62, G-44, O-32, O-29/O-30 (§6G1) |
| 2C-2 pricing engine | #7 | Y-5, O-1, O-4, O-7, O-31, G-57, G-53 (§6C2) |
| 2I security & supply chain | #8 | NEW-8, G-97, O-37, NEW-5 (§6I) |
| 2E-1 payment start | #9 | Y-3 B, NEW-6 (§6E1) |
| 2D-1 contract lifecycle | #10 | Y-2 + O-13, O-10, O-9 + G-47 (§6D1) |
| 2E-2 providers & recovery | #11 | P1-8, NEW-2, O-18, P1-1, P1-9 (§6E2) |
| 2D-2 FX | #12 | O-11, O-12 (§6D2) |
| 2H-1 loyalty lots & CRM | #13 | Y-11 + O-22, O-21, G-66, O-23, O-26, O-33 (§6H1) |
| 2H-2 points back, expired holds | #14 | O-20, O-24 (§6H2) |
| 2F-1 locks, expiry, PMS queue | #15 | P1-4, restarted payment, NEW-7, P1-2 (§6F1) |
| 2F-2 methods, pool, channels | #16 | O-15, Y-9, Y-8 (§6F2) |
| 2G-2 market integrity (Stage 3A) | #18 | G-70a, O-8 (HIGH), G-55b; D-5 (§6G2, ADR-070) |
| 2K-1 payments | #19 | LO-04, LO-05, LO-07, LO-16, LO-17, LO-19, LO-21, LO-18 (§6K1) |
| 2K-2 points come back as points | #20 | LO-01, LO-02, LO-06, LO-23 … LO-26, LO-47 (§6K2) |
| 2K-3 channels, disabled room types | #21 | LO-03, LO-13, LO-11, LO-09, LO-15 (§6K3) |
| Admin UX revision (owner's session) | #22, #23, #25 | work-based navigation, grid rate edits, sell prices, contract pages (§6UX, ADR-072) |
| 2G-3 guest payloads and codes (Stage 3B) | #24 | G-71, G-70b, LO-12 (§6G3) |
| 2K-4 operations | #26 | LO-08, LO-10, LO-28, LO-39, LO-22, LO-20, LO-48; LO-37 deferred (§6K4) |
| 2K-5 guest booking frontend | #27 | LO-35, LO-14, LO-32, LO-33, LO-31, LO-49, LO-30 (§6K5) |
| 2K-6 staff frontend, tests and tooling | #28 | LO-34, LO-38, LO-40, LO-45, LO-42, LO-27, LO-46, LO-36, LO-44, LO-29, LO-41, LO-43 (§6K6) |
| 2Z release hygiene | #29 | reproducible committed bundles + 2 CI checks, Frappe OAuth registration off (p76), CI pins, the drawer first-frame race (§6Z, ADR-073) |
| 2Z-F Frappe v16.36.1 | #30 | Frappe v16.36.1 + payments `version-16`, pip-audit list 61 → 29, the sign-in contract of an expired password (§6ZF, ADR-074) |
| 2L LOW leftovers | #31 | G-99 (the payload digest only with cost, also in Desk / REST and the trail), overlays hidden until a pass after they open, D-14 recorded (§6L, ADR-075) |
| 2M owner decisions | #32 | C-12 ŞEKER is SEKER, C-02 a price set by hand only with `price.override`, C-03 SMS / WhatsApp-only guests listed with the phone, C-01 a no-show keeps the points (§6M, ADR-076) |
| 2N-1 members-only prices (call centre) | #33 | C-04: `TEX Loyalty Member`, who a member is, staff join / leave, members-only promotions live, the Call Center prices the caller as a member, a member's price books for a member only (§6N1, ADR-077) |
| 2N-2 members on the web | #34 | C-04: sign-in and join on the booking site by a one-time e-mail link, `TEX Member Session` (30 days on a hotel's own host, the tab on the shared host), member prices on the web, "Member price" for anyone else, `MEMBERS_ONLY`, the booking app in six languages (§6N2, ADR-078) |

- Last full CI before 2Z: CI #191 on 000d806 (PR #28), Linters #190, Supply chain #71, all green; 2Z's own final
  runs are in PR #29's description. Numbers to keep green (2Z's head, local runs): TEX unit 698; TEX integration 49
  modules, 1,305 tests (`test_scheduler_smoke` differs only locally, on the demo booking domain's DNS); Playwright
  203 passed, 9 skipped by design (212; 52 spec files); node unit 435; DOM 42; i18n complete in 6 languages; eval
  76/76; banquet 101; front-desk journey 13/13; pip-audit 61 reviewed advisories. After 2Z-F (Frappe v16.36.1, local
  runs): TEX unit 699; integration 49 modules, 1,306 tests; pip-audit 29 reviewed advisories; PR #30's description
  has its CI runs. After 2N-2 (PR #34, local runs on its head): TEX unit 702; integration 51 modules, 1,380 tests
  (`test_member_web` 35; `test_scheduler_smoke` differs only locally); node unit 446; DOM 45; Playwright 215 tests in
  54 spec files (9 skipped by design); eval 76/76; banquet 101; front-desk journey 13/13. PR #34's description has its
  CI runs.

## 2. What is left

Nothing planned remains. In order of likely need:

| # | Item | Needs | Where |
|---|---|---|---|
| 1 | ~~2Z-F: Frappe v16.25.0 → v16.36.1~~ **done** (PR #30). Left: the 29 reviewed advisories (PyJWT and oauthlib move on Frappe's `develop` only); re-check them when Frappe tags a newer v16 | none | §6ZF, ADR-074, `pip-audit-ignore.txt` |
| 2 | ~~Pre-upgrade migration package (O-34, O-35, O-36, O-39, P1-12)~~ **not needed**: D-14 answered no (2026-10-03), every hotel starts from a fresh install | none | §6L, `HANDOFF_LEFTOVERS.md` §3 C-06 |
| 3 | PMS adapters, SMS/WhatsApp providers, inbound PMS events (G-69r) | **D-15**: which PMS runs each go-live hotel? | C-07 |
| 4 | O-6 deadlines in hotel-local time for UTC+7 hotels; LO-37 (the `fx_bridged` WARN of a MANUAL-mode pair) | D-13 answered **no** for wave 1; ask again when Cam Ranh / Phuket are planned | C-05, LO-37 |
| 5 | ~~Points policy for No Show~~ **answered** (PR #32, C-01): a no-show keeps the points the stay was paid with; who charges a no-show fee stays with D-15 | none | §6M, ADR-076 |
| 6 | Smaller owner questions with defaults: C-02, C-03, C-12 **done** (PR #32); C-04 **done** (call centre 2N-1, PR #33; web 2N-2, PR #34); C-08 … C-11, C-13 … C-15 open (C-16 accepted) | owner | `HANDOFF_LEFTOVERS.md` §3 |
| 6b | C-04 follow-up question (2N-2): a web join makes a membership staff ended active again; should one ended for a reason such as abuse stay ended (a "blocked" flag staff set)? | owner | §6N2 "Not done", ADR-078 |
| 6c | C-04 LOW leftovers that need no decision: staff see and end a guest's web sessions in the CRM; a pending link dropped by an erasure; a signed-in join for a profile whose stored e-mail is not a plain ASCII address says so | none (LOW) | §6N2 "Not done" |
| 7 | CLP and ISK: the server keeps them in 2 decimals (`money.MINOR_UNITS`), ISO 4217 says 0; the screens now follow the server (2K-6) | owner: a money-engine rounding change | §6K6 "Not done" |
| 8 | ~~G-99: `get_contract` returns `payload_hash` to `price.view` callers~~ **done** (PR #31) | none | §6L, ADR-075 |
| 9 | ~~About thirty dialogs reset their form in a passive effect after opening~~ **done** (PR #31): the design system's overlays keep their content hidden until a pass after they open | none | §6L, ADR-075 |
| 10 | Each batch's "Not done" line in its IMPLEMENTATION_STATUS §6* section and its PR's "Kalanlar" | none (LOW) | §6 … §6N2 |

Not in scope unless the owner asks: G-41r allotment × channel, G-54 surcharges by LOS/arrival, G-64 CRM campaigns.

## 3. How to work — the method that kept Part 2 free of regressions

Per batch:
1. **Re-verify every card against the current code before you change it.** Cards carry the commit they were
   verified at; line numbers drift — find code by function name. If a card's "today" value or premise is no longer
   true, stop and correct the card (and tell the owner in one line) instead of forcing the fix.
2. Bring your branch onto the base: `git fetch origin claude/inspiring-ptolemy-i6wdu2` and
   `git merge --ff-only origin/claude/inspiring-ptolemy-i6wdu2` (if your branch carries already-merged history only).
   Push and open a **draft** PR into the base using `.github/PULL_REQUEST_TEMPLATE.md`.
3. Per item: **write the failing test first and run it** (keep the red output: it goes in the PR body), then fix,
   run the targeted modules locally, **one commit per item** (Conventional Commits), push, go on. Do not wait for
   GitHub CI on intermediate heads (the workflow cancels them). A frontend change commits its rebuilt bundles
   (`cd frontend && npm ci && npm run build`, then `git add -A kamra/public`): CI fails otherwise (ADR-073).
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
- **Frontend:** strings through i18n `t()` in 6 languages (de, en, pl, ro, ru, tr; `npm run i18n:tex` checks the
  admin and the booking app's catalogs since G-70b), TEX design-system components in
  `frontend/src/tex/ui`. **Bundles (since 2Z, ADR-073):** every frontend change commits its rebuilt bundles
  (`kamra/public/frontend`, `kamra/public/tex`); CI fails when they differ from a fresh build, and when a bench install
  leaves the app checkout dirty. The build carries no commit stamp unless `TEX_BUILD_COMMIT` is set. Two PRs that both
  rebuilt them: merge the base and rebuild, never resolve the bundles by hand.
- Legacy Kamra PMS code stays (hidden from TEX navigation). Keep AGPL notices and upstream headers.

## 5. Environment and CI

- Local bench: `docs/tex-engine/DEV_ENVIRONMENT.md` (Frappe v16.36.1, Python 3.14, Node 24 in CI / 22 locally — the
  build does not depend on the major, CI's drift check is the arbiter — MariaDB 11.x with `innodb_snapshot_isolation`
  OFF, Redis, payments `version-16` at commit cca07d9). Pure tests: `python -m pytest kamra/tex/tests/unit -q`. Integration: `bench
  --site test.localhost run-tests --module kamra.tex.tests.integration.<mod>`.
- GitHub workflows on every PR and every push to the base:
  - **CI**: "Python lint (ruff)"; "Frontend typecheck & build" (build, **committed bundles equal this build**, node unit,
    DOM checks, i18n, bundle checks); "Backend eval harness" (~35–40 min: bench install, **a bench install leaves the
    app checkout clean**, eval 76/76, banquet, TEX unit, every TEX integration module, front-desk journey, fresh install
    incl. the OAuth assertion, Playwright E2E).
  - **Linters**: "Semgrep Rules" (frappe/semgrep-rules and semgrep/semgrep-rules `python/lang/correctness` at reviewed
    commits, Semgrep pinned; a Monday run scans with the newest rules), "Marketplace install simulation".
  - **Supply chain**: "Secrets (gitleaks)", "npm dependencies (audit-ci)", "Python dependencies (pip-audit)" with
    reviewed ignores in `.github/supply-chain/pip-audit-ignore.txt` (one reason per advisory; 29 since 2Z-F); also Mondays.
- Pins live in four files (`ci.yml`, `supply-chain.yml`, `deploy/tex-local/Dockerfile`, `setup-local.sh`):
  `kamra/tex/tests/unit/test_pins.py` keeps one Frappe tag, one payments commit and one bench CLI across them.
- A red Monday Linters run means upstream added a rule: review it, fix or `nosemgrep` with a reason, then move the pin
  in a PR. A new pip-audit advisory: review it by the file's convention (one line with reason and date), upgrade when
  the pin allows. A check red on the base too is not your PR's: say so; never skip, disable or quarantine a test, never
  push an empty commit to re-run CI.

## 6. Numbers

- Patches up to **p78** (p57 sits in `[pre_model_sync]`). p26, p30, p32, p41–p44 and **p67** were never used — do not
  use them. **Next free: p79.**
- ADRs up to **ADR-078**. **Next free: ADR-079.**
- `IMPLEMENTATION_STATUS.md` sections: 6, 6B, 6C1, 6C2, 6G1, 6D1, 6E1, 6I, 6E2, 6H1, 6D2, 6F1, 6H2, 6F2, 6G2, 6K1, 6K2,
  6UX, 6K3, 6G3, 6K4, 6K5, 6K6, 6Z, 6ZF, 6L, 6M, 6N1, 6N2. A new batch adds its own section at the END of the file.

## 7. Owner decisions

Taken: D-1 … D-4, D-6 … D-11, D-16 … D-18 (applied in Part 2, see the 2026-10-01 handoff in git history for the
wording); **D-5** markets per site and residents-only TR (ADR-070) with the CRS override `reservation.create` + a reason;
**D-12** loyalty is live at go-live; **D-13** no — the UTC+7 hotels do not go live in wave 1 (O-6 and LO-37 deferred);
2Z (2026-10-03): the Frappe upgrade is its own PR after 2Z (done: PR #30), and the committed build carries no commit
stamp.

**D-14** (2026-10-03): no existing Kamra or pilot database is upgraded; every hotel starts from a fresh install.

**2M** (2026-10-03): **C-01** a no-show keeps the points the stay was paid with (as a fee does); **C-02** only
`price.override` drops a price set by hand; **C-03** a guest who agrees to SMS or WhatsApp only is listed in the
abandoned bookings with the phone; **C-12** a promotion code's Turkish letters are their Latin base (ADR-076).

**C-04** (2026-10-03): a member is a guest who joined the hotel's loyalty program or who stayed and earned points;
members get the members-only prices on the web and in the call centre; a guest not signed in on the web sees the
member price as "Member price" (applied only when signed in); the web sign-in is a one-time link sent by e-mail
(ADR-077; the call centre in 2N-1, the web in 2N-2). For the web (2N-2, ADR-078): a member stays signed in **on the
device for 30 days on a hotel's own host, and only while the tab is open on the platform's shared host** (after
review round 1 B1: another hotel's tag container runs on that origin); a guest joins on the web with **e-mail and
name, confirmed by the link** (a signed-in guest's join too).

Open (ask the owner when the work needs it; never guess): **D-15** (PMS per hotel; also who charges a no-show fee),
C-08 … C-11, C-13 … C-15 with their defaults in `HANDOFF_LEFTOVERS.md` §3, and CLP/ISK minor units (§2 item 7).

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
- Since 2Z the committed bundles must equal a fresh build: rebuild after every frontend change, and after merging a
  base that rebuilt them. Tailwind reads `src/` only; a class used only in a test page goes in that page's own CSS
  (`tests/dom/harness.css`).
- A form kept mounted while closed and reset by a passive effect shows the last session's values for a frame and
  loses what is typed then: mount it per opening (keyed) or reset in a layout effect (ADR-073).
- The local and CI benches have no outgoing Email Account, so `frappe.sendmail` writes no Email Queue row (the
  failure is only an Error Log). An e2e that reads a mail turns on an outbox of its own and turns it off after
  (`member-web.spec`); integration tests use `ensure_test_outbox` or mock `notify._send`.
- **Never run a DB test (bench run-tests) while Playwright runs**: both use the one site, and the integration
  tests then die of real deadlocks (2N-2 lost a run this way). Run them one after the other.
- **Never edit a Python file of the app while Playwright runs**: `bench serve` reloads on a change and the request
  in flight ends with "socket hang up" (a spec then fails for nothing). Markdown and frontend sources are safe; build
  the bundles only after the run (they are what the server serves).
- The booking app's shared host: every hotel's `/book/<site>` page runs on one origin with its own tag containers.
  Anything a guest's browser keeps there (tokens, member data) is readable by another hotel's scripts: keep it in
  the tab and remove other sites' data at start (ADR-078, `lib/member.isolateMemberData`), or keep it on the server.
- A Frappe tag move can change a contract TEX relies on: v16.36.1 stopped answering an expired password with the
  reset link (ADR-074). Run every suite on a Frappe move, and read the diff of `frappe/auth.py`, `frappe/oauth.py` and
  `frappe/integrations/oauth2.py` between the tags.

## 10. First steps for the session that takes over

1. Read `CLAUDE.md`, this file and the newest §6* sections of `IMPLEMENTATION_STATUS.md` (§6N1, §6N2); skim the
   descriptions of PRs #31–#34 (the latest complete batches).
2. Check on GitHub that PR #34 (2N-2) is merged. If it is still open, ask the owner first; never start the next batch
   on an unmerged base, and never merge it yourself.
3. Set up the bench (`docs/tex-engine/DEV_ENVIRONMENT.md`; after a container restart the services must be started
   again, its "Cloud containers can restart" section) and run the pure unit tests and one integration module.
4. Agree the next batch with the owner, in Turkish, with the options of §2 and the consequence of each (plain
   questions worked best, D-14): D-15 (which PMS per hotel: the PMS adapters, SMS / WhatsApp, inbound events), the
   C-04 follow-up (6b), the open C-items (C-08 … C-11, C-13 … C-15), CLP / ISK, or a LOW batch (6c and the "Not done"
   lines of §6*). Never start an item that waits for an answer.
5. Work as in §3; keep this file current: when a batch merges, mark it in §1 in your next batch's docs commit.

The owner's opening message for a new session is kept in `NEXT_SESSION_PROMPT.md` (Turkish): the same steps and
rules, to paste into the session that takes over.
