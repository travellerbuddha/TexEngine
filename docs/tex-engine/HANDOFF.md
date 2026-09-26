Branch: `claude/inspiring-ptolemy-i6wdu2` on origin (integrated: merge 93acf09 of `pricing-workspace` b80ef86 into 7f621de).

# TEX Engine — Handoff (2026-09-26 06:1x UTC)

Facts only. Checked with the commands in §6 on 2026-09-26.

## 1. Branch map

Remote (`git ls-remote origin`): exactly one branch, `claude/inspiring-ptolemy-i6wdu2`. Every commit below is reachable from it except `worktree-wf_957bf605-4e5-1`.

| Ref | SHA | Content | Merge? |
|---|---|---|---|
| origin `claude/inspiring-ptolemy-i6wdu2` | 93acf09 + this doc fix | 1575c8b (main line up to G-46/G-60/G-64/fix-*) + HANDOFF copy 7f621de + merge 93acf09 of `pricing-workspace` | Integrated; tree = `pricing-workspace` |
| local `pricing-workspace` (/home/user/tex-pricing-ws) | b80ef86 | 1575c8b + Pricing Workspace S1–S16 (ADR-061) + review fixes + go-green groups (security-cost, workspace-ux, main-side) + HANDOFF | Merged (93acf09); on origin via `claude/inspiring-ptolemy-i6wdu2` history |
| local `pw-backend` (/home/user/tex-pw-backend) | b9135e0 | Backend slices S2–S5 | No. 0 commits outside `pricing-workspace` |
| local `worktree-wf_957bf605-4e5-1` | 23ec794 | G-69 UI (badc5fa, 23ec794); not on origin | No. Same change is already in main as 511784f, f03a0ef |
| ~40 other local branches (`fix-*`, `g*`, …) | — | Earlier gap waves | No. 0 commits outside 1575c8b |

Source of truth: origin `claude/inspiring-ptolemy-i6wdu2` (its tree equals `pricing-workspace` b80ef86 plus this doc fix). Pushed 2026-09-26 on the owner's direct instruction.

## 2. Current state

- Integrated branch last code/doc commit: b7f435a (docs: ADR-061 final follow-up, main-side group).
- Unit tests, run 2026-09-26 on b7f435a in /home/user/tex-pricing-ws:
  - `/home/user/bench/frappe-bench/env/bin/python -m unittest discover -s kamra/tex/tests/unit -t .` → **530/530 OK** (13.2 s)
  - `cd frontend && npm run test:unit` → **316/316 pass**
  - `cd frontend && npm run test:dom` → **42/42 passed**
- Integration (agent run in this session, `migrate_test.sh`, all 40 modules, code = 59ef45a): **868 tests OK**, 11 skipped. Evidence: `/home/user/bench/scratch/pw-mainside/full/summary`.
- Red tests on b7f435a: none known.
  - Caveat: the independent verifier of the main-side group (a18a3b5..b7f435a) was stopped before its verdict.
  - The re-review of commits 5bb7d7b..b7f435a and the Final run (full regression + E2E ×2 + flaky specs ×5) were not run.
  - Workspace status: PARTIAL (IMPLEMENTATION_STATUS R-04).
- Red tests on origin 1575c8b (both fixed only on `pricing-workspace`):
  - `kamra/tex/tests/integration/test_system_status.py:138` `test_an_old_fx_rate_warns_and_a_stale_one_fails`.
    - Root cause: the test's 3-calendar-day rate warns only Wed–Fri, so it is red Sat–Tue.
    - Fix: a18a3b5 pins "now" to all 7 weekdays.
  - `frontend/e2e/entry-branding.spec.ts:238` and `:356` (navigation tests).
    - Root cause: `kamra/tex/api/lists.py` `version_rows` counts archived contracts' drafts toward the 2,000 cap, so the lists come back empty on a site with >2,000 archived E2E drafts.
    - Fix: edcb424.

## 3. In-flight work

No `wip:` commits. Every worktree was clean (`git status --porcelain` empty) at 06:0x UTC.

The go-green workflow was stopped at this point:

| Step | State | Next concrete step |
|---|---|---|
| Verify main-side group (a18a3b5, edcb424, f2f6a4b, 59ef45a, c051b1c, b7f435a) | Stopped mid-run. entry-branding 3/3 runs passed before the stop | Rerun: `migrate_test.sh` all modules, `disposable_test.sh <tree> <out> test_crm_third_review test_crm_privacy_review`, entry-branding ×5 |
| Re-review of 5bb7d7b..b7f435a (3 lenses) | Not started | Fix the findings below first |
| Final (all suites, E2E ×2, matrix/rereview/entry-branding ×5, acceptance counts) | Not started | Then rebuild bundles (eb897e1 is stale) and fast-forward the main branch |

Open verifier findings, not fixed (file:line at b7f435a):

1. `frontend/src/tex/screens/rates/workspace/OccupancySection.tsx:125`
   - `inherited` is `[]` until `price_matrix` answers, and stays `[]` if it fails.
   - The single-use switch's "outranked" refusal (`occupancy.ts` `singleWriteRefusal`) then misses policy rules, so 1A+0C can change price silently.
   - Orchestrator rating: MEDIUM. Next: refuse or disable the switch while `matrix` is loading or errored.
2. `frontend/src/tex/screens/rates/workspace/occupancy.ts:896` `singleCardPrices`
   - Ignores non-card Always-wins Adult 1 rules, so the single-use row can name a card that does not decide single use.
   - Rating: LOW/MEDIUM.
3. German "Zeitraum" still appears inside the workspace, contrary to the ADR-061 text, which says "Periode" throughout.
   - Locations: `PriceMatrix.tsx:1166` (`aria-label` `rates.rates.caption`) and the period popover hints.
   - Rating: MEDIUM unless the ADR text is corrected.
4. `frontend/src/tex/ui/grid.ts:344` `focusHeaderLane`
   - The ArrowUp/ArrowDown round trip is asymmetric when periods exist.
   - Rating: LOW.
5. `kamra/tex/api/contracts.py:103,161` `payload_hash`
   - Returned to callers without `price.view_cost`; it is a sha256 of the frozen payload, which lets a caller confirm guesses of hidden policy-rule ops offline.
   - Rating: LOW per verifier, pre-existing.
6. `kamra/tex/pricing/validate.py:666` `visible_issues`
   - A slot-less `OCC_AMBIGUOUS` is shown as an ERROR to a viewer without cost, while the full check passes and the version publishes.
   - Rating: LOW.

Source files for 5–6: `/tmp/claude-0/.../scratchpad/pw/security_cost_lows.json`. For 1–4: `.../pw/workspace_ux_lows.json`. These files are container-local.

## 4. Open items

Open gaps (FINAL_GAP_AUDIT.md §3–§5; severity = section):

| ID | Open part | Severity |
|---|---|---|
| G-67 | Payment providers: Sipay refund; live certification BLOCKED | Medium (PARTIAL) |
| G-47 | Rate/inventory grid: rows are room types; no copy period; rate cell ignores rate plan/markup | Medium |
| G-59 | Revision approval never recorded; guest lower-price request only a note | Medium |
| G-40 | CRS/booking: no destination or hotel-group search in UI; untested | Medium |
| G-42 | Results: no per-room gallery; no inclusive-tax line; no rate comparison | Medium |
| G-44 | Widget: no inline full booking; `modal` = `search`; no widget tests | Medium |
| G-54 | Base rates/markups have no arrival/LOS/booking-date rules | Medium |
| G-55 | Refused market link dropped silently; guest country not reconciled | Medium |
| G-57 | MEMBER promotions never apply (`member` never set) | Medium |
| G-58 | No bundles, no package coupon scope, no redemption integration tests | Medium |
| G-62 | No white-label token/theme tests; analytics ids validated client-side only | Medium |
| G-63 | No date picker/tooltip/dropdown/calendar; contrast failures; no a11y CI | Medium |
| G-66 | Loyalty redemption only as money; tier/blackout/expiry untested | Medium |
| G-69 | No e-mail/SMS/WhatsApp adapters (channel backend done); go-live blocker | Medium |
| G-70 | 226 server `_()` messages untranslated; UI language not sent | Medium |
| G-71 | 295 KB legacy shell in admin bundle; per-room-type availability queries | Medium |
| G-75 | No global search, recent reservations, saved filters | Medium |
| G-41 | Remainder: allotment not splittable by channel (ADR-050) | Medium (remainder) |
| G-64 | Remainder: CRM Campaigns not started | Medium (remainder) |
| G-53 | Same-scope markup/board ties resolved silently | Low |
| G-80 | 320 px clipping, 1440 px list scroll, English segment names | Low |
| G-82 | E2E journey step 17 changes dates only, not occupancy | Low |
| G-83 | Remainder: double opt-in e-mail; old payment links until expiry | Low (remainder) |
| G-97 | Contract version rates readable in Desk by Hotel Admin whatever the profile | Low |

Blocked on owner input: payment production certification, SMTP, channel-manager certification, a GitHub base branch for PR/CI.

Requirements not COMPLETE (IMPLEMENTATION_STATUS.md:1362–1423), with the linked gap:

| ID | Open part | Severity |
|---|---|---|
| R-04 | Pricing Workspace PARTIAL (§3) | Medium |
| R-09 | G-53 | Low |
| R-11, R-36 | G-47 | Medium |
| R-12 | G-54 | Medium |
| R-13 | G-55 | Medium |
| R-14 | G-97 | Low |
| R-17 | Pools/configured inventory only in Desk | Medium |
| R-18 | G-57 | Medium |
| R-19, R-20 | G-58 | Medium |
| R-23 | G-59 | Medium |
| R-24, R-27 | G-40 | Medium |
| R-25 | G-41 remainder | Medium |
| R-28 | G-42 | Medium |
| R-29 | Two lost min-basket promos forfeited one by one; no-show not a cancellation | Medium |
| R-30 | G-44 | Medium |
| R-31 | TLS / `add-domain` per host are operations | Ops |
| R-32 | G-62 | Medium |
| R-34, R-51 | G-63 | Medium |
| R-35, R-37 | CRM Campaigns not started | Medium |
| R-39 | G-66 | Medium |
| R-40 | G-67; certification BLOCKED | Blocked |
| R-41 | Two tabs on different gateways can pay twice (flagged for refund) | Medium |
| R-43 | Guest identity shared in an enterprise (by design, ADR-040) | Owner |
| R-44 | Providers/SMTP BLOCKED; no SMS/WhatsApp | Blocked |
| R-47 | Per-hotel time zones; no reporting-currency conversion | Medium |
| R-49 | G-70 | Medium |
| R-50, R-59 | G-80 | Low |
| R-52 | G-71 | Medium |
| R-53 | G-83 remainder | Low |
| R-55 | G-75 | Medium |
| R-62 | Definition of done not met | — |

## 5. Known traps

- **Container restart kills MariaDB, Redis, `bench serve` and running workflows.** Run the §6 start commands, then `git status` in each worktree, and continue from the last commit.
- **Resuming a workflow with parallel lanes re-runs agents instead of replaying its cache.** Write a new sequential script from the last finished step.
- **`redis-server` without a dir writes `dump.rdb` into the cwd.** Run `redis-cli config set dir /tmp` (`dump.rdb` is gitignored).
- **One shared bench/site: `/home/user/bench/scratch/bench-tests.lock`.** Run integration tests only through `migrate_test.sh` / `benchtest.sh`. Never SIGINT a bench test run; never DDL or commit inside tests.
- **`disposable_test.sh` needs `developer_mode=1` and an `encryption_key` in the throwaway site config**, otherwise the booking-flow tests fail.
- **Committed bundles go stale** (eb897e1, `kamra/public/frontend`). Rebuild with `npm run build` at merge; never commit bundles in feature commits.
- **Changing `singleWriteRefusal` / `switchSingleUnchecked` breaks the fixture pairing.** Regenerate with `UPDATE_SWITCH_PAIRS=1 npm run test:unit`, then run `kamra.tex.tests.unit.test_single_use_switch`.
- **Existing pricing semantics must not change.** `kamra/tex/tests/unit/test_main_parity.py` (2,906 quotes byte-identical to 6b0102c) and `test_existing_semantics` must stay green. Workspace additions are opt-in via `workspace=1`.
- **Review loops on ADR-061 did not converge:** 5 re-review rounds, each finding new medium/low items. Cap the rounds and triage by severity before rerunning.
- **The auto-mode classifier refuses `git push` of non-designated branches and repeated `git ls-remote`** unless the user asks directly in the session.
- **Formerly flaky specs `pricing-workspace-matrix` :107 and `pricing-workspace-rereview` :208** were fixed by the workspace-ux group 62cde1e..9fd9474 (10/10 runs each, agent report). Rerun ×5 in Final.
- **Playwright:** `PW_CHROMIUM=/opt/pw-browsers/chromium`; never `playwright install`. `test.localhost` must resolve to 127.0.0.1.
- **Scratch scripts and evidence (`/home/user/bench/scratch`, `/tmp/claude-0/...`) are not in the repo** and are lost with the container.

## 6. Environment (verified in this session, 2026-09-26)

Services (as root, after a container restart):
```bash
mysqld_safe > /dev/null 2>&1 &
redis-server --daemonize yes; redis-cli config set dir /tmp
grep -q test.localhost /etc/hosts || echo "127.0.0.1 test.localhost" >> /etc/hosts
su frappe -s /bin/bash -c "source /home/user/bench/env.sh; cd /home/user/bench/frappe-bench; \
  nohup bench serve --port 8000 >> /home/user/bench/serve.log 2>&1 &"
curl -s -o /dev/null -w "%{http_code}\n" http://test.localhost:8000/api/method/ping   # 200
```

Tests (run in /home/user/tex-pricing-ws):
```bash
/home/user/bench/frappe-bench/env/bin/python -m unittest discover -s kamra/tex/tests/unit -t .   # 530 OK
cd frontend && export PATH=/opt/node24/bin:$PATH
npm run test:unit    # 316/316
npm run test:dom     # 42 passed
```

Run by this session's agents (evidence in `/home/user/bench/scratch/pw-mainside/`):
- `/home/user/bench/scratch/migrate_test.sh <worktree> <outdir> [modules]` → 40 modules, 868 OK.
- `/home/user/bench/scratch/disposable_test.sh <tree> <outdir> <modules>` → `test_crm_third_review` 22/22.

The bench (`/home/user/bench/frappe-bench`, site `test.localhost`, Frappe v16, Python 3.14, MariaDB 10.11, Node 24 at `/opt/node24`) exists only in this container. For a new container, see DEV_ENVIRONMENT.md (not re-verified in this session).

## 7. Reading list (besides CLAUDE.md and this file)

1. `docs/tex-engine/ARCHITECTURE_DECISIONS.md:4126` ADR-061 — the decisions, deviations and provisional O1–O5 behaviour that the §3 findings touch.
2. `docs/tex-engine/DEV_ENVIRONMENT.md` (§ "After a container restart", line 90) — how to rebuild the bench in a new container.
3. `docs/tex-engine/FINAL_GAP_AUDIT.md` §3–§5 — each open gap's affected files and evidence.
