# Handover appendix: 2Z release hygiene — work cards

Companion to `docs/tex-engine/HANDOFF.md` (read that first). 2Z is the **last** batch: it rebuilds the committed
frontend bundles once, after every frontend change of the other batches has merged.

**Status (2026-10-03): done in Part 2Z (PR #29, IMPLEMENTATION_STATUS §6Z, ADR-073)**, items 1 and 3–6; item 2 (the
Frappe upgrade) is its own PR after 2Z (owner). Corrections found while doing it: Semgrep was 1.179.0 by then, the
reviewed advisories were 61, the next free patch and ADR were p76 and ADR-073, and the rates contract page's
`RuleDialog` (item 5's list) is another component, already mounted per opening.

Re-verified on 2026-10-01 at base `claude/inspiring-ptolemy-i6wdu2` @ **aac444a4** (merge of PR #16; its tree
equals PR #16's tested head, so CI run #160 — run id 36877813099 — gives the current numbers). Facts checked on GitHub:
the repository is **public**, and its **default branch is the base branch** (scheduled workflows run on it). Method:
static reading, `git log`/`git show`, GitHub job logs and one failing run's artifact (run 36315774106, still
downloadable), the Frappe / payments / bench / Semgrep repositories and the PyPI JSON API read-only, real frontend
builds (Node 22, `npm ci` from the lockfile) and a React 19.2.7 replica in Chromium — all in a throw-away
environment, nothing in the repository changed. **Re-verify each card before you change code.**

**Numbers.** This card was written when p71 and ADR-072 were free. Stage 3 runs first and takes p71 (O-8) and p72
(G-55b); the leftover batches may take more. **Use the next free patch and ADR numbers when you write 2Z**
(`TestEveryPatch` needs sorted order within `[post_model_sync]`; never p67).

Abbreviations:
- **CI #160** = the CI workflow on PR #16's last head. Linters #159 and Supply chain #40 belong to the same push.

## 0. Verdict per item

| # | Item | Status @aac444a4 | Change | Size | Order in 2Z |
|---|---|---|---|---|---|
| 1 | NEW-4 bundles + CI drift check | **OPEN, worse than recorded.** 69 source commits since the last bundle. The build stamps the git HEAD into the bundle, so a plain `git diff` check would fail on every PR. A bench install also leaves the app checkout dirty. | Make the committed build a pure function of the source; add 2 CI checks; rebuild; fix `.gitignore` | M | 5 (last code commit) |
| 2 | Frappe upgrade vs the PR #11 advisories | No v16 release can close the 14 PyJWT/oauthlib ones. v16.36.1 closes **32 other** reviewed advisories. | Optional: upgrade to v16.36.1 | M | separate PR, or 4 |
| 3 | Frappe OAuth dynamic client registration | OPEN. On by default. TEX never uses Frappe's provider. | `after_install` + p71 + tests + GO_LIVE line | S | 1 |
| 4 | Semgrep / CI hygiene | Semgrep rules, CLI and registry pack unpinned. `--verbose` note and allowlist-reason note **ALREADY DONE**. payments unpinned in ci.yml and supply-chain.yml. | Pin with a weekly drift run; pin payments | S | 2 |
| 5 | Flaky `channels.spec.ts` ("already mapped") | **Root cause found, and it is not the network.** A product race in `MappingDrawer`, proven by the CI trace. 8 sibling components share the pattern. | Mount the drawer per opening; add a first-frame e2e check | S–M | 3 |
| 6 | DOC refresh | ~45 stale statements (list in §6). Part 2 statuses to record. | Docs only | M | 6 (last) |

Numbers: see the note at the top (next free patch and ADR when you write it; ADR-070 is Stage 3's).

---

## 1. NEW-4 · The committed bundles equal a fresh build, and CI enforces it

### Evidence

**The bundles are stale.**
- Last commit touching `kamra/public/frontend`: **eb897e19** (2026-09-25 12:12 UTC), "build: bundles for the Pricing Workspace (S1-S16)".
- `kamra/public/tex/tex-widget.js` was last changed by 59399ce3 (2026-09-23).
- Commits on aac444a4 after eb897e19:
  - 93 commits touch `frontend/` (79 non-merge);
  - 69 non-merge commits touch build inputs (`frontend/src`, `index.html`, `booking.html`, `vite*.ts`, `package*.json`, `public/`);
  - the old card said 34.
- What is missing from the served UI:
  - the Pricing Workspace re-review fixes;
  - PR #1's guest notices (K2 d4da0603, B5, D5, E3);
  - every Part 2 frontend fix: O-16, Y-4, Y-7b, O-28, Y-3 A/B, P1-7, O-2/O-2b, P1-11/NEW-3, O-27, G-62, **G-44 (widget)**, O-32, O-29, O-30, O-1, O-4, O-7, O-31, G-57, G-53, Y-2/O-13, O-10, P1-8, O-26, O-33, O-12, O-20, O-24, O-15, Y-8.
- Content checks:
  - no committed JS contains `late_payment`; 5 source files use it;
  - a fresh build's `tex-widget.js` is 20.18 kB, the committed one 19.58 kB.
- f063ae44 (G-53) says it itself: "on the committed bundle the dialog said 'No errors or warnings'; passes on a build".

**Who serves the committed bundles.**
- `deploy/tex-local/Dockerfile:108-117` copies the repository and links `kamra/public`. It runs no npm build.
- `setup-local.sh:1040-1047` runs `bench build --apps frappe,payments` only.
- `bench get-app --skip-assets` installs serve them too.
- Frappe serves `kamra/public` at `/assets/kamra/`. The pages read the built HTML at request time:
  - `kamra/www/kamra.py:34-53` reads `index.html` and injects the CSRF token and `entry.source_meta()`;
  - `kamra/tex/booking_host.py:27-36` does the same for `booking.html`.

**Why CI never noticed.**
- In the backend job, `bench get-app kamra` (`ci.yml:129`, no `--skip-assets`) runs Frappe's `bench build --app kamra`. That runs the app root's `yarn build`:
  - frappe `build.py:252-255` adds `--run-build-command`;
  - `esbuild/esbuild.js:88,142,511-540` runs it;
  - root `package.json:6` is `cd frontend && npm install && npm run build`.
- CI #160's log shows "Running build command for kamra … vite v6.4.3 building for production". So Playwright always ran on bundles built from the PR source.
- The comment at `ci.yml:227-229` ("--skip-assets: link the app's committed bundles") is wrong: bench already rebuilt and linked them.
- The existing "bundle checks" (`ci.yml:52-59`) grep the files the `frontend` job has just rebuilt. They never look at the committed ones.

**Build commands and their outputs.**
- `frontend/package.json:7`: `npm run build` = `tsc -b && vite build && vite build -c vite.widget.config.ts`.
  - `tsc -b` only type-checks (`noEmit`; `tsconfig.tsbuildinfo` is gitignored).
  - `vite build`, configured in `vite.config.ts:43-61`, writes `kamra/public/frontend/`: `index.html`, `booking.html`, `assets/*` (180 files at aac444a4) and copies `frontend/public/*` (6 icons). `emptyOutDir: true`, `sourcemap: false`, content-hashed names, `manualChunks` per admin language.
  - The widget build, configured in `vite.widget.config.ts:5-17`, writes `kamra/public/tex/tex-widget.js`: lib mode, fixed name, no Tailwind, no stamp.
- Not produced by the build:
  - `kamra/public/js/tex_source.js`, hand-written and loaded by `hooks.py:122` `app_include_js`;
  - the logos;
  - `.gitkeep`.

**Determinism (measured, not assumed).**
1. The build is reproducible.
   - I rebuilt the source of **33612e77** (eb897e19's parent) with `TEX_BUILD_COMMIT=33612e77…`.
   - Result: **byte-identical** to the bundles committed in eb897e19 (`diff -r` empty).
   - It was built on another machine, with Node 22 here and CI's Node 24.21.0.
   - The admin CSS hash `index-hrn9tvxA.css` is also identical between my build and CI #160's bench build.
   - Two builds in a row, same stamp: identical.
2. **The build is not a function of the source alone.**
   - `vite.config.ts:9-18,26` `define`s `__TEX_BUILD_COMMIT__` = `TEX_BUILD_COMMIT`, else `git rev-parse HEAD`.
   - The committed bundle carries `z1="33612e77…"` in `assets/source-DSx9lSeY.js`, its *parent* commit.
   - Changing only the stamp renames **162 of 180** asset files and changes both HTML entries: the `source-*` chunk's hash cascades through every importer.
   - In CI the checkout is the ephemeral PR merge commit; Linters #159 checked out "315e344 Merge ebf5e42 into 0edb11ce". So **`npm run build && git diff --exit-code` would fail on every PR, whatever the source**.
   - On a production bench, every `bench build` / `bench update` re-stamps the bundles with the deployed HEAD. The kamra checkout is then dirty.
   - bench v5.31.0's `pull_apps` (`bench/app.py:977-1001`) then refuses the next update: "Cannot proceed with update: You have local changes in app "kamra"…". `NATIVE.md:227-230` already warns "never run a plain `bench build`".
3. The stamp is used only as a last fallback.
   - `frontend/src/lib/source.ts:26-31`: the page's `tex-source-url` meta, then the API, then the stamp.
   - Every page the server serves carries the meta (kamra.py:53, booking_host.py:36). So only the Vite dev server ever falls back.
4. **Tailwind scans tests.**
   - `src/index.css:1` `@import "tailwindcss";` uses automatic source detection from `frontend/`, so it includes `e2e/`, `tests/`, `scripts/` and `widget-demo.html`.
   - Probe: one class-like string in a new e2e file changed `index-*.css`, which renamed **93 asset files** (the CSS and 92 JS chunks that reference it) plus `index.html`.
   - With a drift check, a test-only PR would have to commit 94 renamed or changed files.
   - `src/booking/booking.css:4-5` already uses `source(none)` + `@source "./"`.
   - Restricting the admin CSS to `src/` drops exactly 5 utilities, all referenced only outside `src/`:
     - `aria-selected:bg-sky-100`, `aria-selected:bg-zinc-100`, `select-all` (tests/dom harness);
     - `opacity-55` (unit contrast test);
     - `transform` (`widget-demo.html`).
5. **A bench install dirties the checkout even without the stamp.**
   - bench's `install_app` (`bench/app.py:961`) runs `yarn install --check-files` in the app root. That writes an untracked **`yarn.lock`** (reproduced: 86 bytes).
   - Frappe links `{app}/node_modules` to `assets/kamra/node_modules` (`frappe/build.py:325-338`). Since `assets/kamra` is a symlink to `kamra/public`, this creates a **symlink `kamra/public/node_modules`**.
   - `.gitignore:16` `kamra/public/node_modules/` has a trailing slash and does not match a symlink. Reproduced: `?? kamra/public/node_modules`.
6. Platform independence: the lockfile carries native packages for linux-x64 (gnu/musl), darwin-arm64 and win32-x64 (rollup, esbuild, lightningcss, tailwind oxide, sharp).
   - Tool versions: vite 6.4.3, rollup 4.62.2, esbuild 0.25.12, tailwindcss 4.3.2, React 19.2.7.
   - Node major does not matter (22 = 24, verified).
   - macOS output was not verified; the CI check is the arbiter.

### Change (recommended: "the committed build has no stamp")

1. `frontend/vite.config.ts:7-18`. `buildCommit()` returns `TEX_BUILD_COMMIT` only when it is set and valid, else `""`. Drop the `git rev-parse` fallback and the `execFileSync` import.
   - Amend ADR-060 ("The bundles carry their build commit…", `ARCHITECTURE_DECISIONS.md:4141`) and write **ADR-072**. A build carries a commit only when told (e.g. an image build). The committed and bench builds carry none, so they are a pure function of the source. The served pages still offer the exact running commit via `source_meta`.
   - No test reads the git fallback (`frontend/tests/dom/vite.config.ts:12` defines `""`).
2. `frontend/src/index.css:1` becomes:
   ```css
   @import "tailwindcss" source(none);
   @source "./";
   ```
   - The DOM harness pages (`tests/dom/{history,keyboard,lanes,overlays}.tsx`, which import `../../src/index.css`) import a new `tests/dom/harness.css` instead:
     ```css
     @import "../../src/index.css";
     @source "./";
     ```
   - Verify `npm run test:dom` still gives 42 passed, and that the harness CSS contains `select-all`.
   - Fallback if `@source` in the importing file is not honoured: add `@source "../tests/dom";` to `src/index.css`.
3. `.gitignore`:
   - replace `kamra/public/node_modules/` (`:16`) with `/kamra/public/node_modules` (no trailing slash);
   - either commit the root `yarn.lock` that bench writes (header only), or add `/yarn.lock`. Committing it is the usual Frappe-app practice and keeps `yarn install --check-files` a no-op.
4. Root `package.json:6`: `cd frontend && npm ci && npm run build`, so a bench never rewrites `frontend/package-lock.json`. The cost is a clean `node_modules` per `bench build`, about 5–10 s.
5. **CI, `frontend` job** (`ci.yml:27-59`): a new step directly after `npm run build` (`:39-40`). `TEX_BUILD_COMMIT` must not be set in this job.
   ```yaml
      - name: Committed bundles equal this build (NEW-4, ADR-072)
        # kamra/public/frontend and kamra/public/tex are what tex-local, --skip-assets installs and a bench
        # without node serve: a source change must commit its rebuilt bundles
        run: |
          changes=$(git status --porcelain --untracked-files=all -- kamra/public)
          if [ -n "$changes" ]; then
            echo "::error::kamra/public differs from a fresh build: run 'cd frontend && npm ci && npm run build' and commit kamra/public"
            echo "$changes" | head -60
            exit 1
          fi
   ```
   - Use `git status --porcelain --untracked-files=all`, not `git diff --exit-code`: `git diff` misses the new, untracked hashed files.
   - Comparing only the entry hashes is weaker: it misses orphaned files and `public/` copies. With a deterministic build it is not needed.
6. **CI, backend job**: a new step after "Install app & site" (`ci.yml:125-136`). It is the production `bench get-app` / `bench build` path:
   ```yaml
      - name: A bench install leaves the app checkout clean (NEW-4)
        # bench get-app ran kamra's root build and linked its assets; `bench update` refuses a dirty app checkout
        run: |
          changes=$(git -C frappe-bench/apps/kamra status --porcelain --untracked-files=all)
          if [ -n "$changes" ]; then echo "::error::bench left changes in apps/kamra"; echo "$changes" | head -60; exit 1; fi
   ```
   - Also correct the comment at `ci.yml:227-229`.
7. **Rebuild and commit** `kamra/public/frontend` and `kamra/public/tex` with `cd frontend && npm ci && npm run build` (no `TEX_BUILD_COMMIT`).
   - This is the **last code commit** of the 2Z PR, after the item-5 frontend fix.
   - Expected at aac444a4 (measured, stamp-free): 176 asset files added, 173 removed, 3 modified (`index.html`, `booking.html`, `tex-widget.js`).
8. Docs that describe the bundle workflow:
   - `.github/PULL_REQUEST_TEMPLATE.md:12-13`: commit `kamra/public/frontend` **and** `kamra/public/tex`; CI fails otherwise. Line 7 still says "PR targets develop": the base and default branch is `claude/inspiring-ptolemy-i6wdu2`.
   - `CONTRIBUTING.md:42`.
   - `README.md:155-161` (Turkish, the owner's text): its out-of-repo build is fine for checking, but a PR that changes frontend sources must run `npm run build` in `frontend/` and commit `kamra/public`.
   - `RELEASING.md:102-104`.
   - `.gitleaks.toml:20-21`: "regenerated in Part 2Z" becomes "kept equal to a fresh build by CI (ADR-072)".
   - `deploy/tex-local/NATIVE.md:227-230`: a plain `bench build` now rewrites nothing when the bundles are current.
   - HANDOFF "Committed bundles go stale" trap.

Alternative (only if the owner wants to keep a commit in the bundle):
- Record the stamp in `kamra/public/frontend/build-commit.txt` (a small Vite `generateBundle` plugin).
- CI rebuilds with `TEX_BUILD_COMMIT=$(cat …)` and compares.
- Costs:
  - every bench `bench build` still re-stamps, so `bench update` refuses;
  - every rebuild renames about 160 files;
  - the stamp can point at an older commit.
- Not recommended.

### Fail-first

- With changes 1–6 committed and before the rebuild (7): the new frontend step is **red** with ~352 porcelain lines, and the bench-path step is red (`?? yarn.lock`, `?? kamra/public/node_modules`, bundle drift).
- After 3 and 7 both are green.
- Locally: `cd frontend && npm ci && npm run build && git status --porcelain -- kamra/public` is non-empty before and empty after.
- For change 2, put a class-like token in a throw-away e2e file, rebuild, and check that `kamra/public` is unchanged. Today it changes 94 files.

### Risks and pitfalls

- **Ordering with later frontend work.**
  - Stage 3 (O-8 → G-55b → G-71 → G-70) and every later frontend PR must commit rebuilt bundles.
  - Two parallel PRs conflict in `index.html` / `booking.html` / `tex-widget.js`. Resolve by merging the base and **rebuilding** (`git add -A kamra/public`), never by hand.
  - Merge 2Z first, or make Stage 3 merge it before opening.
- `ci.yml:3-8` runs on `pull_request` and on pushes to `main` / `develop` only. Nothing re-checks the base after a merge, so a merge that combines two PRs' bundles goes unseen. Add `claude/inspiring-ptolemy-i6wdu2` to `push.branches` (item 4), or require "up to date before merging".
- Repository growth: about 5.7 MB of new hashed files per rebuild commit (accepted upstream practice, RELEASING.md).
- Node: `setup-node` `node-version: 24` floats (24.21.0 in CI #160). The output did not depend on the major. A pin is optional.
- The lockfile must stay in sync. `npm ci` fails otherwise, which is good.
- Windows `autocrlf` and macOS were not verified; the CI check decides.

**Size:** M. Mostly mechanical, plus one large generated commit.

**Done when:**
- both CI checks are green;
- the committed bundles equal a stamp-free build of the PR head;
- `git -C apps/kamra status` is clean after `bench get-app`.

---

## 2. Frappe upgrade and the reviewed dependency advisories

### Evidence

**Frappe version in use: v16.25.0 (tag dated 2026-07-01).** Pinned in:

| Kind | Locations |
|---|---|
| Code | `ci.yml:118` (comment `:115-116`: the version-16 branch tip once had an UnboundLocalError in `frappe/locale.py`), `supply-chain.yml:119,124`, `deploy/tex-local/Dockerfile:1,23`, `setup-local.sh:7,27,76` |
| Docs | `DEV_ENVIRONMENT.md:4,17`, `README.md:138`, `deploy/tex-local/NATIVE.md:178,198`, `deploy/tex-local/README.md:78,81,203`, `docs/self-hosting.md:49,66`, `docs-site/self-hosting/bench.md:15`, `SECURITY.md:93`, `pip-audit-ignore.txt:2,4,55,60` |
| Bench | `frappe-bench` is unpinned in `ci.yml:114` and `supply-chain.yml:123`; the Dockerfile pins 5.31.0 (`:26`), the latest on PyPI |

**Newer v16 releases exist** (`git ls-remote`):
- v16.26.0 … **v16.36.1 (2026-09-30)**;
- branches `version-16` and `version-16-hotfix` have the same pins as v16.36.1.

**Pins per tag** (raw `pyproject.toml`):

| Package | v16.25.0 | v16.31.0 | v16.32.0 … v16.36.1, version-16(-hotfix) | develop (v17-dev) |
|---|---|---|---|---|
| **PyJWT** | ~=2.13.0 | ~=2.13.0 | **~=2.13.0** | ~=2.15.0 |
| **oauthlib** | ~=3.3.1 | ~=3.3.1 | **~=3.3.1** | ~=4.0.0 |
| cryptography | ~=46.0.3 | ~=50.0.0 | ~=50.0.0 | ~=50.0.0 |
| Pillow | ~=12.2.0 | ~=12.2.0 | ~=12.3.0 | ~=12.3.0 |
| pypdf | ==6.13.3 | ==6.13.3 | ==6.15.0 | ==6.16.1 |
| sqlparse | ~=0.5.5 | ~=0.5.5 | ~=0.6.0 | ~=0.6.0 |
| bleach | ~=6.3.0 | ~=6.3.0 | **removed** (`bleach-allowlist`, which has no dependencies, stays) | — |
| WeasyPrint | ==68.0 | ==68.0 | ==68.0 | (gone) |
| pdfkit | ~=1.0.0 | | ~=1.0.0 | ~=1.0.0 |

- PyPI has **no PyJWT 2.13.x and no oauthlib 3.3.x patch release**. The fixes are PyJWT 2.14.0/2.15.0 (2.15.1 is current) and oauthlib 4.0.0 (2026-09-28).

**Verdict:**
- The **14 advisories added in PR #11 (1 oauthlib + 13 PyJWT) cannot be closed by any v16 upgrade today**. Only Frappe develop (v17) moves.
- Their reasoning still holds and is stronger once item 3 lands: with no guest-registered clients, the oauthlib PKCE case has no attacker client.
- Keep them. Re-check when Frappe tags a v16 with PyJWT ≥2.14 / oauthlib ≥4, or when TEX moves to v17.
- Do not force-install PyJWT 2.15 into the bench: it breaks Frappe's declared pin, and `bench setup requirements` puts it back.

**An upgrade to v16.36.1 closes 32 of the 53 listed findings.** Supply chain #40: "53 reviewed finding(s) listed", all still reported.

| Closed by v16.36.1 | Count |
|---|---|
| bleach | 3 |
| cryptography | 4 |
| Pillow | 13 |
| sqlparse | 5 |
| pypdf (3610, 3611, 3612, 3613, 3655, 3656, 3912) | 7 |
| **Total** | **32** |

| Still listed after v16.36.1 | Count |
|---|---|
| pypdf 3910, 3911, 3913 (need 6.16.x) | 3 |
| pdfkit | 1 |
| WeasyPrint | 2 |
| setuptools (payments pins ==80.9.0 on develop **and** version-16) | 1 |
| oauthlib | 1 |
| PyJWT | 13 |
| **Total** | **21** |

- pip-audit does not audit `gunicorn` and `pypika` (URL requirements; pip-audit #40 log "not audited"). That stays true.

### What an upgrade requires (procedure for a "2Z-F" PR)

1. Change the tag to `v16.36.1` everywhere listed above, code first, then the docs.
   - Do it in the **same PR as the payments pin** (item 4). payments `develop` (86fefa9f, the commit pinned today) declares `frappe >=17.0.0-dev,<18`, and bench warns "might not work as expected" (CI #160 and pip-audit #40 logs).
   - payments `version-16` (cca07d9f, 2026-05-26) declares `>=16.0.0,<17.0.0` and differs from develop only by Razorpay webhook additions (12 files).
   - kamra uses nothing of the payments app beyond `required_apps` (`hooks.py:71`).
2. What it brings:
   - 6 new framework patches (notification types/logs backfills, Contact Us Settings, SMS Settings roles). None touches TEX tables.
   - New deps **duckdb ~=1.4.3, pyarrow ~=25.0.0** (cp314 manylinux/aarch64/macOS wheels exist: duckdb 1.4.5, pyarrow 25.0.1; a bigger image).
   - sql_metadata 3.x, Click 8.4, pyOpenSSL 26.4.
   - `frappe.database.utils.get_query_type`, imported by `test_patches.py:29`, still exists in v16.36.1.
3. A dev/production bench, in order:
   1. backup;
   2. in `apps/frappe`, fetch the tag and check it out;
   3. `bench setup requirements`;
   4. `bench build --app frappe`;
   5. `bench --site <site> migrate`;
   6. restart.
   - Docker: change `FRAPPE_BRANCH` and rebuild.
   - An in-place pip upgrade leaves the old `bleach` installed. A local pip-audit still lists it until it is uninstalled.
4. Tests:
   - full CI: eval 76/76, banquet, TEX unit (parity corpus unchanged), **every** integration module on a disposable site (`test_patches`), journey 13/13, fresh install, all Playwright;
   - Linters;
   - Supply chain: remove each ID the gate reports as `::notice::… is no longer reported`. Review any **new** finding from the new dependencies (the gate fails on them). Update the PyJWT/oauthlib comment lines to "v16.36.1 still pins…".
5. Risk: medium (framework). Size **M**.
   - Recommended as its own PR right after 2Z, or inside 2Z before the bundle commit and the docs, so the docs carry the final versions.
   - Owner choice. It closes 32 findings; it does not close the PR #11 ones.

**Fail-first:** none. It is an upgrade. The check is pip-audit's notices (32 IDs no longer reported) and the full suite.

---

## 3. Frappe's OAuth provider: no dynamic client registration on TEX sites

### Evidence (Frappe v16.25.0; unchanged in v16.36.1)

**The setting.**
- `OAuth Settings` (Single, module Integrations, System Manager only) has the Check `enable_dynamic_client_registration`, **default 1**.
- Its siblings are `show_auth_server_metadata`=1, `show_protected_resource_metadata`=1, `skip_authorization`=0 and `show_social_login_key_as_authorization_server`=0.

**What a guest can do with it** (`frappe/integrations/oauth2.py`):
- `register_client` (`:335-345`) is `@frappe.whitelist(allow_guest=True, methods=["POST"])` with no rate limit. When the setting is on, any guest creates an `OAuth Client`.
- `utils.create_new_oauth_client` (`:225-258`): scopes "all" by default; any https `redirect_uri` (any scheme in developer_mode); `save(ignore_permissions=True)`.
- The metadata advertises the endpoint (`:329-330`).

**Risk.**
- Unauthenticated row creation.
- **Consent phishing.** A staff member who clicks "Allow" on `/api/method/frappe.integrations.oauth2.authorize?client_id=<attacker's>` sends a code to the attacker's https URL. That code becomes a bearer token with scope "all": API access as that user, after their sign-in and second factor. TEX's capability checks still apply.

**TEX never uses Frappe's provider.**
- No reference anywhere in `kamra/`, `frontend/src/` or `deploy/` to `OAuth Client`, `OAuth Bearer Token`, `OAuth Settings`, `integrations.oauth2` or `Social Login Key`.
- The legacy MCP login is kamra's own code: `kamra/mcp_oauth.py`, `MCP OAuth Client` / `MCP OAuth Grant`, under `/mcp/oauth/*` (`mcp_http.py:60-95`). It is unaffected.
- PR #11's pip-audit review says the same (`pip-audit-ignore.txt:56-58`).

**Pitfall: write it with `get_single().save()`, not `set_single_value`.**
- `Document.load_from_db` (`frappe/model/document.py:259-266`) applies the defaults only when the Single has **no** row in `tabSingles`.
- `frappe.db.set_single_value("OAuth Settings", "enable_dynamic_client_registration", 0)` on a never-saved Single stores one row. The other fields then read as None, which silently switches off both metadata endpoints and blanks `resource_name`.
- `frappe.get_single(...)` + `.save(ignore_permissions=True)` persists every field with its current effective value. It also clears the document cache.

### Change

1. `kamra/tex/setup.py`: add the helper and call it at the end of `after_install()` (`:258-268`):
   ```python
   def close_oauth_registration() -> None:
       """Frappe's OAuth provider registers no client for a guest on a TEX site (ADR-072): TEX has no OAuth
       client of its own on it; an administrator may switch it on for a reviewed integration."""
       if not frappe.db.exists("DocType", "OAuth Settings"):
           return
       settings = frappe.get_single("OAuth Settings")
       if settings.enable_dynamic_client_registration:
           settings.enable_dynamic_client_registration = 0
           settings.save(ignore_permissions=True)
   ```
2. Patch **`kamra.patches.tex.p71_oauth_registration_off`** in `[post_model_sync]`, after p70. It follows the "once" style of p70:
   - `if ran_before(__name__): return`. A forced re-run never undoes an administrator's choice (G-76, `setup.py:161-172`).
   - Then `close_oauth_registration()`.
   - Then print the number of `OAuth Client` rows whose `owner = "Guest"`, for review. Delete nothing; print no names.
3. Tests:
   - **(a) Integration, fail-first**, `test_security_hygiene.py`, new class. The module already imports `EnvironBuilder`, `Request` at `:21-22`.
     - As Guest, call `frappe.integrations.oauth2.register_client()` with `frappe.local.request` built by `EnvironBuilder(method="POST", json={"client_name": "x", "redirect_uris": ["https://example.com/cb"]})`.
     - Expect `werkzeug.exceptions.NotFound` and the `OAuth Client` count unchanged.
     - `_get_authorization_server_metadata()` (with a request) has no `registration_endpoint`.
     - On aac444a4 the call returns 201 and creates a client: red.
     - Do not assert `frappe.db.get_single_value(...)`: it is None (falsy) on a site that never saved the Single, so it would pass on the base.
   - **(b) Patch**, `test_patches`:
     - a `BEHAVIOUR` entry for `p71_oauth_registration_off`;
     - a test: the flag on, first run, off, guest-client count printed;
     - re-enable, forced re-run, stays on (`ran_before`);
     - `assertRerunChangesNothing`.
   - **(c) Fresh install**, `ci.yml:191-201` `fresh_check.py`: add `assert not frappe.get_cached_value("OAuth Settings", "OAuth Settings", "enable_dynamic_client_registration"), "OAuth dynamic client registration is on"`.
   - **(d) Optional e2e**: `request.post('/api/method/frappe.integrations.oauth2.register_client', {data: {...}})` expects 404.
4. Docs:
   - ADR-072 (one paragraph);
   - `SECURITY_MODEL.md` / `SECURITY.md` hardening line;
   - `MIGRATION_PLAN.md` §2 row p71.
   - **GO_LIVE_READINESS** §4 platform note and §5 gate:
     > Frappe OAuth provider: dynamic client registration is off on TEX sites (OAuth Settings → "Enable Dynamic Client Registration", set by install and p71). Before go-live, review Desk → OAuth Client (and OAuth Bearer Token) and delete or revoke any client not created by an administrator — p71 prints how many a guest registered. Switch registration on only for a reviewed integration.
   - Optional: switch off the two `show_*_metadata` flags. TEX serves no Frappe OAuth.

**Size:** S. **Risk:** none for TEX users. A third party that relied on self-registration on a TEX site would need an admin-created client.

**Adjacent observations (LOW; not part of this card; for the owner):**
- The legacy Kamra MCP `/mcp/oauth/register` (`mcp_oauth.py:146-176`) also lets a guest register, with no rate limit, and commits each row. Its redirect URIs are limited to claude.ai / claude.com / loopback.
- `protected_resource_url()` (`mcp_oauth.py:60`, `/mcp/oauth/resource`) is not routed by `mcp_http.dispatch`, which serves only `mcp/.well-known/oauth-protected-resource`. An MCP client may then fall back to Frappe's root `/.well-known` metadata.
- The `/mcp` surface is not gated by `show_legacy_pms`.

---

## 4. Semgrep and CI hygiene

### Evidence

**Semgrep is unpinned.**
- `linters.yml:25-26` does `git clone --depth 1` of `frappe/semgrep-rules` HEAD.
  - Upstream added `whitelisted-side-effect-on-get` on 2026-09-30 (8afbb8a; merge **81a6e3d47a328249e8ddf04c586e493dd5553002**, plus fix e640bcd). That turned the base red on b9fcc700. PR #11 answered with a reasoned `nosemgrep` at `kamra/tex/api/payments.py:86`.
- `linters.yml:33` `pip install semgrep` is unpinned. Linters #159 used **1.178.0**: 35 ERROR rules, 1,357 files, 0 findings.
- `linters.yml:36` `--config r/python.lang.correctness` fetches the registry pack from semgrep.dev at run time, also unpinned. Its source is `semgrep/semgrep-rules/python/lang/correctness` (24 YAML rules at a84ff9cc2453ca91d581380de4b8b3f272f6f4be, 2026-09-22).

**The two notes from the 2I review are already done.**
- "No --verbose in scan step": `supply-chain.yml:81,83` pass `--verbose` (e14c5d86).
- "kamra/public allowlist reason wrong (tex_source.js hand-written)": `.gitleaks.toml:19-25` now names the bundles, the logos and "one hand-written Desk script (js/tex_source.js)", `targetRules = ["generic-api-key"]` (473362b3).
- Only a wording nit is left after item 1 ("regenerated in Part 2Z").

**payments is unpinned in CI.**
- `ci.yml:128` `bench get-app payments` and `supply-chain.yml:126` `bench get-app --skip-assets payments` take payments' default branch, develop. It declares `frappe >=17.0.0-dev,<18.0.0`.
- Both CI logs print "Installed frappe-dependency 'frappe' version '16.25.0' does not satisfy required version '>=17.0.0-dev,<18.0.0'".
- develop is at 86fefa9f today. That is the commit `Dockerfile:79-83` and `setup-local.sh:30-32` pin, so CI equals Docker only by luck.
- `DEV_ENVIRONMENT.md:21` clones develop unpinned.

**Other unpinned or deprecated pieces.**
- `pip install frappe-bench` (`ci.yml:114`, `supply-chain.yml:123`; Dockerfile pins 5.31.0).
- `npm install -g yarn` (`ci.yml:96`, `supply-chain.yml:122`).
- CI #160 warns "Node.js 20 is deprecated … forced to run on Node.js 24: actions/checkout@v4, actions/setup-node@v4, actions/setup-python@v5, actions/upload-artifact@v4". Current majors are v7 (`git ls-remote`).

### Change

1. `linters.yml`:
   - Add `schedule: - cron: "41 4 * * 1"` (Monday).
   - Add `env: FRAPPE_SEMGREP_RULES_REF: 81a6e3d47a328249e8ddf04c586e493dd5553002`, `SEMGREP_RULES_REF: a84ff9cc2453ca91d581380de4b8b3f272f6f4be` and `SEMGREP_VERSION: "1.178.0"`, each with a "reviewed 2026-10-01" comment.
   - Fetch the rules **outside the workspace**. Today the clone sits in the workspace and is skipped only because it is an untracked nested repository:
     ```bash
     ref="$FRAPPE_SEMGREP_RULES_REF"; [ "${{ github.event_name }}" = "schedule" ] && ref=develop   # Monday: the newest rules
     git init -q "$RUNNER_TEMP/frappe-rules" && git -C "$RUNNER_TEMP/frappe-rules" fetch -q --depth 1 https://github.com/frappe/semgrep-rules "$ref" && git -C "$RUNNER_TEMP/frappe-rules" checkout -q FETCH_HEAD
     # same for semgrep/semgrep-rules at $SEMGREP_RULES_REF (sparse: python/lang/correctness)
     pip install "semgrep==$SEMGREP_VERSION"
     semgrep --error --severity=ERROR --config "$RUNNER_TEMP/frappe-rules/rules" --config "$RUNNER_TEMP/semgrep-rules/python/lang/correctness"
     ```
   - A red Monday run means upstream added a rule. Review it, fix or `nosemgrep` with a reason, then bump the SHA in a PR. Pull requests stay on the reviewed pin.
   - Keep `r/python.lang.correctness` only if the owner prefers the registry. It is the same rules, unpinned.
   - The header comment ("Mirrors frappe/semgrep-rules#how-to-use") then says "pinned; weekly drift run".
2. payments, pinned at one SHA everywhere.
   - `ci.yml:128` and `supply-chain.yml:126`: mirror `Dockerfile:85-93`. Run `get-app` with `--branch develop`; if `HEAD != $PAYMENTS_REF`, fetch the SHA with `--depth 1`, check it out detached, `pip install -e apps/payments`, then (ci.yml only) `bench build --app payments`.
   - Workflow-level `env: PAYMENTS_REF: 86fefa9faf8ad825fe6f08c4753acfe44817900b`.
   - Fix `DEV_ENVIRONMENT.md:21`.
   - Add a pure unit test `kamra/tex/tests/unit/test_pins.py` (runs in CI's unit step). It reads `ci.yml`, `supply-chain.yml`, `Dockerfile` and `setup-local.sh` and asserts that they name **one** Frappe tag and **one** payments SHA.
   - Move to payments `version-16` with the Frappe upgrade (item 2).
3. `pip install frappe-bench==5.31.0` in both workflows (Dockerfile parity).
4. Add the base branch to `ci.yml:4-5` `push.branches`, so the merged base is re-checked. That gives the item-1 drift check its post-merge run. `linters.yml` and `supply-chain.yml` should get the same.
5. Optional, LOW: bump the actions to the current majors after reading their release notes.

**Fail-first / checks:**
- `test_pins.py` is red if one pin is changed alone.
- The Linters PR run stays green on the pinned rules.
- A `workflow_dispatch` of the new Linters workflow shows the pinned SHAs in its log.

**Size:** S.

---

## 5. The flaky `frontend/e2e/channels.spec.ts` ("already mapped")

### Evidence (the only CI failure: run 36315774106, head 48dc1bd, PR #10; the artifact is still downloadable)

**Failure.**
- `expect(again.getByRole("alert").filter({ hasText: "already mapped" })).toBeVisible()` was at `:127` then; it is `:129` today, in the step `:110-132`.
- Message: "element(s) not found" after 15 s.
- The page snapshot in `error-context.md` shows the "Add mapping" dialog with **"Channel room code" empty and `[invalid]`, alert "Required."**. Every later field is filled: rate code `BARMUJQXAJ31I`, Standard Sea View, BB, Flexible, DE, OTA, EUR.
- So no request was sent. It is **not a network error**.

**Trace timeline** (`trace.zip`, times from the test start):

| Time | Event |
|---|---|
| 6.407 s | "Add mapping" click done |
| 6.413 s | `fill("RMUJQXAJ31I")` resolves the room-code input as **`<input … value="RMUJQXAJ31I" data-autofocus>`**: the drawer is showing the **previous session's form**, so the fill of the same value is a no-op |
| 6.423 s | The rate-code input resolves as `value=""`: the reset has happened in between and wiped the room code |
| 6.55–11.0 s | The Save click waits behind the "Mapping saved." toast, then submits a form with the room code empty |

**Root cause (product race, LOW, also hits a fast typist).**
- `MappingsTab.tsx:140-151` keeps `<MappingDrawer>` mounted while closed (`mapping={editing}`, `editing` null when closed). Its `form` state (`MappingDrawer.tsx:92`) keeps the last session's values.
- On reopen it is reset by a passive effect `useEffect(() => { setForm(toForm(...)) }, [mapping])` (`:100-106`). An update scheduled from a passive effect renders in a later task.
- So the drawer's first frame shows the old values, with the caret autofocused in the room code. Anything typed before that render is lost.
- **Replica**, React 19.2.7 in Chromium (throw-away), 3 runs out of 3:
  - with this pattern, the first committed frame after the click and its microtask shows the stale value;
  - with a fresh instance per opening, it shows `""`.
- On an idle machine Playwright's next command usually lands after the reset. That is why the failure is rare.

**Correction of the record.**
- PR #12 (0d) and `IMPLEMENTATION_STATUS.md:1553` (§6D2) call the flake "a server-load network error".
- That was a different behaviour, seen under synthetic CPU starvation on a local bench: "Can't reach the server", which `api.ts:113-130` shows only when `fetch` itself rejects (there is no client-side timeout).
- The CI failure at :127 was the race above.
- In CI Frappe sets the werkzeug logger to ERROR (frappe `app.py:517-519`, `CI` env), so `serve.log` in the artifact was **0 bytes**. There were no server diagnostics either way.

**8 sibling components share the pattern** (always mounted, form reset in a passive effect on open). Found by AST-free grep; check each:

| File:line | Effect deps |
|---|---|
| `screens/connect/Connections.tsx:325-343` | `[name]` and `[doc.data, isNew]`. This is the "New connection" drawer that `channels.spec.ts:80-87` types into right after opening; the same loss can fail the "Saved" toast step. |
| `screens/payments/setup/RuleDialog.tsx:62` | `[open, rule]` (mounted at `Setup.tsx:230`, `RatesTab.tsx:176`) |
| `screens/payments/setup/AccountDrawer.tsx:73` | `[open, account]` (`Setup.tsx:229`) |
| `screens/reservations/components/ModifyDrawer.tsx:169` | `[open, initial]` (`ReservationDetail.tsx:407`) |
| `screens/crm/profile/EditGuestDrawer.tsx:68` | `[open, guest]` (`GuestProfile.tsx:298`) |
| `screens/rates/workspace/ChildAgesDrawer.tsx:90` | `[p.open]` (`OccupancySection.tsx:394`) |
| `screens/rates/components/pickers.tsx:38` | `[open, value]` (the popover's draft) |
| `screens/crm/Segments.tsx:109` | `[selected, isNew, …]` |

### Change (no retries, no skip)

1. `MappingsTab.tsx:140-151`: render the drawer only while open, one instance per opening: `{lookups.data && editing && <MappingDrawer key={editing === "new" ? "new" : editing.name} mapping={editing} … />}`.
   - Delete the reset effect `MappingDrawer.tsx:100-106`. The `useState` initialiser (`:92`) and fresh hook state on mount do the reset.
   - `useModal`'s cleanup (`overlay.tsx:15-50`) still restores focus on unmount.
2. The same structural fix for the 8 siblings: mount per opening with a key, or set the form in the **same event handler** that opens.
   - Priority: `Connections.tsx` (the same spec), then the payments setup dialogs, `ModifyDrawer` and `EditGuestDrawer` (their specs type right after opening), then the rest.
   - `useLayoutEffect` is an acceptable minimal fix where remounting is awkward, e.g. `pickers.tsx`.
3. **Fail-first e2e**, `channels.spec.ts`. It replaces the plain click at `:125` and goes before `fillMapping(again, codes)`:
   ```ts
   // a new mapping starts blank in its first frame: nothing typed into it is lost to a late reset
   const firstFrame = await page.evaluate(async () => {
     const add = [...document.querySelectorAll<HTMLButtonElement>('[role="tabpanel"] button')].find((b) => b.textContent?.trim() === "Add mapping")
     add?.click()
     await Promise.resolve() // React commits the click's update in a microtask
     return document.querySelector<HTMLInputElement>('[role="dialog"] input[data-autofocus]')?.value ?? null
   })
   expect(firstFrame).toBe("")
   const again = page.getByRole("dialog", { name: "Add mapping" })
   ```
   - It returns the previous room code on aac444a4 and `""` after the fix. This is deterministic, per the replica.
   - Do the same right after "New connection" (the Name input).
4. Diagnostics for the network family. They do not hide anything.
   - Extend `helpers.trackErrors` (`helpers.ts:32-36`) with `page.on("requestfailed", r => …)`, recording `r.failure()?.errorText` and the URL. The next transport failure then names itself, e.g. `net::ERR_EMPTY_RESPONSE`.
   - Optional: start `bench serve` in CI with `CI= ` for that process only, so `serve.log` gets request lines. It also turns the werkzeug debugger on, so keep it optional.
   - Infrastructure changes (more than one web process) only on evidence.

**Size:** S for MappingDrawer, the e2e check and diagnostics. S–M with the sweep. **Risk:** low (UI state lifetime). Run `npm run test:unit`, `test:dom`, and the specs that open these drawers twice.

---

## 6. DOC refresh

### Final CI numbers (until the 2Z PR's own green run replaces them)

**CI #160** = run 36877813099, on aac444a4's tree, Node 24.21.0, MariaDB 11.8.9 with `innodb_snapshot_isolation` OFF:

| Check | Result |
|---|---|
| ruff | clean |
| Frontend build (tsc + vite) | clean |
| Node unit tests | **360/360** |
| Design-system DOM checks | **42 passed** |
| i18n | 6 languages complete |
| Eval harness | **76/76** |
| Banquet | **101 OK** |
| TEX unit | **659 OK** |
| TEX integration | **44/44 modules, 1,193 tests OK** (`test_patches` 52) |
| Front-desk journey | **13/13** |
| Fresh-install checks | passed |
| Playwright | **177 passed, 2 skipped** (`booking.spec.ts:63,101` run on desktop only, by design); 43 spec files, incl. `manage-money` 3, `crs-actions` 7, `crm-profile` 1, `channels` 1, `widget` 1 |

| Workflow | Result |
|---|---|
| Linters #159 | Semgrep 1.178.0: 35 ERROR rules, 1,357 files, 0 findings; marketplace simulation passed |
| Supply chain #40 | gitleaks clean; audit-ci clean; pip-audit "no new finding (53 reviewed)" over 135 packages |

### Stale statements (file:line → correct fact)

**IMPLEMENTATION_STATUS.md**

| Line | Stale | Correct fact |
|---|---|---|
| :18 | "§1 … (GitHub CI on 0669c51e, 2026-09-26)" | CI #160 on aac444a4's tree, 2026-10-01 |
| :22 | 547 | **659 OK** |
| :23 | "42 modules … 969 tests" | **44/44, 1,193 tests**. Drop the long "Before: …" history or move it to a history note. |
| :24 | 163 passed | **177 passed, 2 skipped by design**, 43 spec files, against the bench with an RQ worker, site scheduler off |
| :25-26 | | 76/76, 13/13, 101 (CI #160); node unit 360/360, DOM 42, i18n 6 languages |
| :27 | | ruff 0.15.8; Semgrep 1.178.0 numbers above; add a supply-chain row (gitleaks, audit-ci, pip-audit 53 reviewed) |
| :33-35 | "PR #2 … PR #1 merged with it green" | PRs #1–#16 merged with CI green (last: #16, 2026-10-01) |
| :37 | "Resumed (2026-09-24)… Open gaps: 0 Critical, 0 High, 24 Medium, 6 Low" | Historical. Delete, or label as history; the counts live in §2. |
| §2 :1327-1336 | the counts | Recount after the FINAL_GAP_AUDIT update. Expected: R-32 → COMPLETE (G-62 fixed); R-14 → COMPLETE **if** HANDOFF §3 #5 below is accepted or fixed, else it stays PARTIAL with that note. Add the line "Open audit findings: O-8 HIGH, G-55b, G-71 guest payload, G-70 guest codes — NOT STARTED (Stage 3, owner decision D-5, ADR-070)". |
| :1349 | Phase 5 "no backend/E2E tests, no copy period" | `pricing/ratesplit.py` + `test_ratesplit`, `test_inventory` (O-9 + G-47, 2D-1); copy period in the Pricing Workspace (Duplicate, "Copy previous period's prices", `PeriodHeader.tsx:4`); `bulk_update` tested (`test_inventory`, `test_audit_trail`, `test_extras_inventory`, `test_restrictions`). Open: rows are room types only. |
| :1352 | Phase 8 "custom domains not served (G-21)" | G-21 RESOLVED (FINAL_GAP_AUDIT:152; e2e `custom-host` ×3 in CI). Open: inline widget mode (G-44 modes). |
| :1371 | R-09 "Same-scope markup ties resolved silently" | Refused on activation (G-53, 2C-2, f063ae44). Open: markup explanation level ignores channel (`level()` unchanged). |
| :1373 | R-11 | Copy period exists; `apply_rate_change` tested. Open: bulk edit of occupancy/child/board across periods (G-47). |
| :1376 | R-14 "G-97" | G-97 fixed (p66, 2I) |
| :1380 | R-18 | Members-only promotions refused on save/activation until a sale knows members (G-57 guard, 2C-2). Open: no membership signal. |
| :1381 | R-19 "Not bookable after booking (G-22)" | G-22 RESOLVED (FINAL_GAP_AUDIT:153). Open: bundles (G-58). |
| :1385 | R-23 G-59 "guest lower-price requests stored as notes" | Guest changes are TEX Guest Change Requests approved by staff (ADR-044). Open: the revision's approval fields are unused. |
| :1387 | R-25 "`crs-actions.spec.ts` not yet run in CI" | Passes in CI (7 tests) |
| :1392 | R-30 "no widget tests" | e2e `widget.spec.ts`; scroll lock and theme fixed (G-44, 2G-1). Open: inline mode, `modal` = `search`, 1 room. |
| :1394 | R-32 | G-62 fixed (2G-1: one rule on the server, the admin form and the engine; `test_security_hygiene` G-62, unit `analytics-ids`) → COMPLETE |
| :1396 | R-34 "No date picker, tooltip, dropdown or calendar" | Tooltip, Menu/ContextMenu, Popover exist (`tex/ui/popover.tsx`, ADR-061). Open: date picker, calendar, contrast (G-63). |
| :1398 | R-36 | Backend tests exist; copy period exists. Open: room × rate rows; rate cell ignores rate plan/markup (G-47). |
| :1401 | R-39 | Add: G-66 tests (2H-1), lots FIFO/expiry (Y-11/O-22), O-21, O-20 points returned. Open: redemption only as money. |
| :1411 | R-49 "226 `_()`" | **~665 `_()` literals in `kamra/tex` (+127 in `tex_*` controllers)** (count at aac444a4), no server catalogs. Guest error codes are Stage 3 (G-70). |
| :1413 | R-51 "sidebar 2.62:1" | Re-measure. Per the P2E pass the sidebar is fixed. Open: zinc-400 text ~2.5:1, ARI weekend header 4.2:1, no axe (a contrast unit test exists for the Pricing Workspace only). |
| :1417 | R-55 | Copy period exists. Open: global search, recent reservations, copy restrictions, saved filters, a `duplicate_contract` test. |
| :1421 | R-59 "blank `/`, Kamra login" | Remove (G-60 fixed, ADR-060) |
| :1424 | R-62 "priorities 1 and 9 still have High items open (§2)" | §1 Critical and §2 High gaps closed. Open: audit O-8 (HIGH, Stage 3), Medium gaps, certification and operations blockers. |
| :1553 | §6D2 "the channels.spec.ts:127 flake is a server-load network error" | The CI failure was the MappingDrawer stale-form race ("Required."), fixed in 2Z. The network error was seen only under synthetic CPU starvation. |
| new | | §6Z for the 2Z items |

**GO_LIVE_READINESS.md**

| Line | Stale | Correct fact |
|---|---|---|
| :6 | "As of: 2026-09-23" | "2026-10-01, base aac444a4 (Part 2A–2F-2 merged, PRs #3–#16)", later the 2Z head |
| :10-11 | | CI #160 numbers |
| :24 | Pricing "315 unit tests" | TEX unit 659. Add Part 2 evidence (Y-3, Y-4, Y-5, O-1, O-2, O-4, O-7, O-31, NEW-1, Y-2/O-13, O-11/O-12) and the open **O-8 (HIGH, Stage 3)**. It stays a money blocker. |
| :25 | "GitHub CI green on 0669c51e" | CI #160 |
| :27 | Booking Engine "manage-money … to be re-run; CI never ran" | Passes in CI (3); exit met. Add O-15, O-16, O-27, O-28, O-30. |
| :28 | Multi-room "no CI evidence yet" | CI runs `TestMultiRoom`, `TestBookingBasket` and the two-room e2e; exit met |
| :29 | Payments | Add NEW-2 (job re-verifies Pending iyzico/Sipay charges), O-18 (fraud review), P1-1 (unknown capture time → Action Required), NEW-6 (no lock through a gateway call), P1-5, O-15. Certification stays BLOCKED. |
| :32 | CRM "`crm-profile.spec.ts` written, not yet run" | Passes in CI. G-66 tests, O-20, O-21, O-23, O-24, O-26, O-33 done. Exit met for the specs. |
| :34 | Security "no dependency/secret scanning in CI" | Done: `supply-chain.yml`, NEW-5 |
| :34 | Security "G-97" | Fixed (p66) |
| :34 | Security, to add | Frappe OAuth registration (item 3); 53 reviewed advisories pinned by Frappe (32 close with v16.36.1) |
| :35 | Tenant isolation "G-97 …; Needs CI evidence" | G-97 fixed; isolation suites run in CI; NEW-8 and Y-12 fixed; pentest stays |
| :40 | CI/CD row | CI #160 + Linters + Supply chain. Open: TEX image, registry, staging, deploy pipeline; base branch push CI (item 4). |
| :42 | Data migration "Patches p01–p40 … `test_patches` 21" | p01–p70: 62 patches; p26, p30, p32, p41–p44 and p67 never released; `test_patches` 52 |
| :49, :50 | "must pass again" / "must pass" | They pass in CI |
| :64 | "CI/CD remainder: dependency and secret scanning, …" | Remove the scanning; keep image, registry, staging, deploy |
| §2 | | Add **O-8 market arbitrage, HIGH, open (Stage 3, D-5)** under Money |
| :109-118 (§3 item 12) | | The repository is public (verified 2026-10-01). What remains: deploy only pushed commits, or set `tex_source_url` / `tex_source_commit`. |
| :120 (item 13) | "branch `pricing-workspace` … PARTIAL until its final verification is green" | Merged (93acf09); its 15 spec files pass in CI #160. O1–O5 still need the owner. |
| :138 (item 14) | "today `reservation.view` is enough" | A contract version's audit entries need `price.view_cost` or `contract.edit` (Y-1, 2A) |
| :142 (item 14) | "the contract detail page's … publish still publish such a draft" | The contract page publishes with the board checks (G-53, f063ae44). The ARI-grid part is not re-verified. |
| §3 | | Add owner decisions D-5 (markets/residency, blocks O-8), D-13 (UTC+7 hotels, O-6), D-14 (upgrade of an existing database: O-34…O-39, P1-12), D-15 (PMS per hotel, G-69r). List the defaults applied to confirm: D-1…D-12, D-16…D-18 (PART2_PLAN §5b) and the controller defaults for D-8 (fraud review) and manual FX. |
| :152-153 | "No query needs `SKIP LOCKED`" | One query uses `FOR UPDATE SKIP LOCKED`: `payments/service.py:1890` `close_links_of` (E4). MariaDB ≥10.6 supports it. |
| §4 | | Add the OAuth note (item 3); the pins (Frappe v16.25.0 or the upgrade, payments SHA); bundles = fresh build (item 1); bench-update hygiene |
| §5 | | Add gates: "committed bundles equal a fresh build of the release commit (CI)"; "Frappe OAuth dynamic client registration off; OAuth Clients reviewed"; "no open HIGH audit finding (O-8)" |
| §6 | | Add a change-log entry for Part 2 (PRs #3–#16) and 2Z |

**FINAL_GAP_AUDIT.md**

| Line | Stale | Correct fact |
|---|---|---|
| :1 | "(2026-09-23)" | Add "updated 2026-10-01 (Part 2)" |
| :62 | G-69 resolved row "`channels.spec.ts` … written, not yet run on a bench" | Runs in CI |
| :172 | #33 G-47 | Copy period exists (Pricing Workspace); write-path tests (O-9 + G-47, 2D-1); `ari_grid`/`bulk_update`/`apply_rate_change` tested. Open: room × rate rows, rate cell, occupancy/child/board bulk edit. |
| :176 | #37 G-59 | As R-23 above |
| :180 | #41 G-44 | Smoke test (e2e `widget`) and the 2 bugs fixed (2G-1, PR #6). Open: modes (inline, modal, multi-room, promo, currency). |
| :186 | #47 G-57 | Guard added (2C-2). Open: membership signal. |
| :187 | #48 G-58 "No integration test of redemptions/limits" | Stale (`TestCouponLimits`, `TestBookingLevelTerms`). Open: bundles, package scope. |
| :190 | #51 G-62 | RESOLVED (2G-1) |
| :191 | #52 G-63 | As R-34 / R-51 |
| :194 | #55 G-66 "Blackouts don't block redemption … no tests" | Tests added (2H-1); blackouts block redemption. Open: redemption modes. |
| :195 | #56 G-69 "(e-mail uses `frappe.sendmail` directly)… Outbox and PMS adapters untested. The outbox does not claim rows" | E-mail goes through Frappe's queue with status sync (ADR-047). The outbox claims rows (token + lease, first per connection and reservation, NEW-7) and is tested (`test_a_claimed_job_is_not_taken_twice`, `test_a_bookings_messages_apply_in_order`, `test_a_message_another_worker_reclaimed_is_not_sent`, G-88/G-90/G-83 PMS tests). Open: SMS/WhatsApp, a vendor PMS, inbound PMS events, `fetch_availability`. |
| :196 | #57 G-70 "226" | ~665 + 127; guest codes are Stage 3 |
| :197 | #58 G-71 "`load_terms` re-reads cached payloads" | Fixed: `contracts.py:879-882` reads the hash and uses the cached terms on a match. Open: legacy shell in the admin bundle, per-room-type queries, guest payload (Stage 3), budgets. |
| :199 | #60 G-75 | As R-55 |
| :207 | #62 G-53 | Ties refused (2C-2). Open: explanation level ignores channel. |
| :216 | #70a G-97 | RESOLVED (2I, p66) |
| :233 | §6 "post-booking extras and custom domains next" | Done (G-21, G-22) |
| §6 | | Add a Part 2 line (PRs #3–#16) |
| "Resolved since the audit" | | Add G-53, G-62, G-97 and the partial G-44/G-47/G-57/G-66 |
| §4 | | Add HANDOFF §3 #5 as a LOW gap if not fixed: `api/contracts.py:104` returns `payload_hash` to `price.view` callers (a sha256 of the frozen payload: offline confirmation of guessed hidden rule values) |

**HANDOFF.md (rewrite; everything in it is from 2026-09-26)**

| Line | Stale | Correct fact |
|---|---|---|
| :1-4 | 0669c51e / "Handoff (2026-09-26 06:1x UTC)" | aac444a4 (later the 2Z merge) |
| :9-20 | Branch map | The pre-PR state and container-local worktrees, gone. Replace with: base plus the PR branches `claude/new-session-*`. |
| :22-49 | §2 numbers (b7f435a: 530 unit, 868 integration, node 316) and red tests on 1575c8b | Replace with CI #160 |
| :51-56 | §3 in-flight work; "Then rebuild bundles (eb897e1 is stale)" | Done by 2Z |
| :57-79 | Verifier findings 1–6 at b7f435a | #3 is fixed (501721ca, "Periode"); #1 and #4 were addressed by e47c44e5 / 7e39f502 (verify); **#5 is still open** (`api/contracts.py:104`); #6 reworked (`validate.py:735-747`). Move open ones to FINAL_GAP_AUDIT and drop the section. |
| :83-108 | Open-gap table | G-44, G-53, G-57, G-62, G-66, G-97 changed; G-70 count |
| :112-150 | Requirements table | R-14, R-25, R-30, R-32 … as above |
| :152-166 | Traps | "Committed bundles go stale … never commit bundles in feature commits" is reversed by item 1: feature PRs commit rebuilt bundles; CI enforces it |
| new | | Add what is next: Stage 3 (O-8 → G-55b → G-71 → G-70, needs D-5, ADR-070); 2Z-F (Frappe v16.36.1) if deferred; the LOW leftovers |

LOW leftovers to list (the full, verified list is `HANDOFF_LEFTOVERS.md`; list whatever is still open when 2Z runs):
- Money:
  - O-19b;
  - `resend_confirmation` offers the manage link for channel bookings;
  - refusals show the connection name "CON-####" instead of its label;
  - ARI does not close disabled room types;
  - `refund_queued` budget;
  - the legacy `kamra.api.cancel_reservation` path is not verified against the channel guard;
  - the checkout fallback offers card at a hotel without card.
- CRM:
  - a Loyalty charge moved by transfer: burn lookup by the charge's own booking;
  - `loyalty.redeem` has no channel guard;
  - no points back on No Show, a lower price or a channel cancellation.
- 2A:
  - legacy `housekeeping.escalate_overdue_tasks` has the same NULL-date pattern;
  - p56 edge on sites upgraded after V2's start.
- Pricing Workspace / UI:
  - "Deposit of 100 EUR" shown on every room of a multi-room booking (cosmetic);
  - O-30 LOWs (compares with the search result, not the last quote seen).
- Others:
  - HANDOFF #5 (`payload_hash`);
  - p58 test `assertGreaterEqual` on a tuple (weak).

**Other files**

| File:line | Stale | Correct fact |
|---|---|---|
| `MIGRATION_PLAN.md` §2 (:31-86) | No rows for **p47, p49–p70** | Add them (22 patches) and p71. "Never released" becomes p26, p30, p32, **p41–p44, p67**. |
| `DEV_ENVIRONMENT.md:78-81` | "Specs: shell, contract-admin, booking, crs, critical-journey" | 43 spec files; point to `frontend/e2e/` |
| `DEV_ENVIRONMENT.md:21` | | Payments pin (item 4) |
| `DEV_ENVIRONMENT.md:4,17` | | If Frappe is upgraded |
| `README.md:155-161` | | Bundle note (item 1) |
| `README.md:138` | | If Frappe is upgraded |
| `.github/PULL_REQUEST_TEMPLATE.md:7,12-13` | | Base branch; bundles |
| `CONTRIBUTING.md:42`, `RELEASING.md:102-104`, `.gitleaks.toml:20-21` | | Item 1 |
| `SECURITY.md:93` | | Frappe version; add the OAuth line |
| `ARCHITECTURE_DECISIONS.md` | | ADR-060 amendment (`:4141`); ADR-072 (bundles = source, CI checks, OAuth registration off, pins) |

**Done-checks** (each `grep -rn docs/ README.md` should find nothing):
- "0669c51e" outside history/change-log lines;
- "not yet run in CI";
- "CI never ran";
- "No query needs `SKIP LOCKED`";
- "226 `_()`";
- "p01–p40";
- "no dependency/secret scanning".

### Part 2 items to show COMPLETE (IMPLEMENTATION_STATUS §6*, GO_LIVE §6, FINAL_GAP_AUDIT)

| Batch | PR | Items |
|---|---|---|
| 2A | #3 | DOC-0, NEW-1 (+ the nullable-date sweep, the scheduler smoke test, p56), Y-1, Y-10, O-16 (D-6), Y-12 (p48 rule, p64) |
| 2B | #4 | P1-6, Y-7, Y-7b (D-9), P1-3, P1-7, P1-5 (D-10), O-38 (p57), P1-10, O-19, P1-11 + NEW-3 |
| 2C-1 | #5 | Y-4, Y-3 A (p59), O-2 (D-2) |
| 2G-1 | #6 | O-28, O-27, G-62, G-44 (smoke test + 2 bugs), O-32, O-29, O-30 |
| 2C-2 | #7 | O-2b, Y-5, O-1, O-4 (+O-3, D-3), O-7 (D-18), O-31 (p60), G-57 (guard), G-53 |
| 2I | #8 | 2G-1 leftovers (O-30, O-29), NEW-8 (verified, then fixed; p65), G-97 (p66), O-37 (p63), NEW-5 |
| 2E-1 | #9 | Y-3 B (D-1), NEW-6 (p68) |
| 2D-1 | #10 | 2C-2 leftovers, Y-2 + O-13 (p69), O-10, O-9 + G-47 (write path) |
| 2E-2 | #11 | P1-8, NEW-2, O-18 (D-8, code part), P1-1 (D-7, rule part), P1-9, plus the CI fix (semgrep exception, 14 reviewed advisories) |
| 2D-2 | #12 | 2D-1 leftovers (0a–0c; **0d corrected** as above), O-11, O-12 (D-4, p70) |
| 2H-1 | #13 | Y-11 + O-22 (p61), O-21, G-66 (tests), O-23, O-26 (D-17), O-33 |
| 2H-2 | #14 | 2H-1 leftover, O-20 (D-16), O-24 (p62) |
| 2F-1 | #15 | P1-4, 1b restarted Pending charge, NEW-7, P1-2 |
| 2F-2 | #16 | O-15, Y-9 (p58), Y-8 (D-11) |
| 2Z | this PR | NEW-4, DOC; plus OAuth registration off (p71), CI pins, the channels.spec race fix |

Not complete:
- **Stage 3, NOT STARTED:** O-8 (HIGH), G-55b, G-71 guest strip, G-70 guest codes. Needs D-5 and ADR-070.
- **Conditional, not in Part 2:** O-6 (D-13); O-34, O-35, O-36, O-39, P1-12 (D-14); G-69r (D-15); G-41r; G-54.
- **Part 1 rows still PARTIAL:** K-2a…d, B4 and D3. iyzico and Sipay state no capture time; the time field is a certification matter. Their rule part is P1-1, done.

---

## 7. Suggested order inside 2Z (one PR; merge the base first; no rebase)

1. Item 3: OAuth, with its patch (the next free number), its tests and the fresh-install assertion. Backend; independent.
2. Item 4: pins, the weekly Semgrep drift run, `test_pins.py`, base-branch push CI.
3. Item 5: MappingDrawer, the Connections drawer and the other siblings, the e2e first-frame checks, `requestfailed` diagnostics.
4. Optional: item 2 (Frappe v16.36.1 plus payments `version-16`), here or as its own PR right after.
5. Item 1: vite stamp change, Tailwind source, `.gitignore` / `yarn.lock`, root build `npm ci`, the 2 CI checks. Commit them **red** first (fail-first evidence in the PR body), then the rebuilt bundles as the **last code commit**.
6. Item 6: docs, with the PR's own final CI numbers. ADR-072. IMPLEMENTATION_STATUS §6Z.

Gate: the PR head is green in all three workflows (CI, Linters, Supply chain), with both new NEW-4 steps and the bench-path cleanliness step.
