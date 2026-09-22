# TEX Engine — Upstream Baseline

TEX Engine is a transformation (fork) of **Kamra PMS**, not a greenfield rewrite.

| Item | Value |
|---|---|
| Upstream repository | https://github.com/Kamra-PMS/kamra-pms |
| Upstream branch used | `develop` |
| Baseline commit SHA | `418ed1a70eef4d4625cf48eec8539925b4f01e3b` |
| Baseline commit date | 2026-09-16 22:16:13 +0530 |
| Baseline commit title | Merge pull request #80 from Kamra-PMS/fix/season-room-type-scope |
| Upstream version at baseline | 2.6.2 train + Unreleased (`kamra/__init__.py`) |
| Upstream licence | AGPL-3.0 (`license.txt`), copyright HeyKoala and contributors |
| Fork repository | https://github.com/travellerbuddha/TexEngine |
| Fork recorded on | 2026-09-22 |

## Why `develop` and not `main`

At fork time `upstream/main` (`31f0bb7`, 2026-09-19) contained `develop` plus
only release metadata (release-please 2.6.3 version bump in
`.release-please-manifest.json`, `CHANGELOG.md`, `kamra/__init__.py`). No code
difference existed, so `develop` @ `418ed1a` is the functional baseline, as the
directive requires.

## History

The full upstream Git history (370 commits reachable from `418ed1a`) is
preserved: the TEX branch was created directly on top of `upstream/develop`.

## Upstream synchronisation policy

- The `upstream` git remote points at Kamra PMS. **Do not** automatically
  pull or merge future upstream changes.
- Upstream changes must be reviewed individually (security fixes first) and
  cherry-picked or merged deliberately, with the review recorded in
  `ARCHITECTURE_DECISIONS.md`.
- TEX keeps the Frappe app name `kamra` (see ADR-001), which keeps upstream
  cherry-picks mechanically possible for the PMS layers TEX still uses.

## Licence obligations (AGPL-3.0)

- `license.txt` (AGPL-3.0 full text) must remain in the repository root.
- Upstream copyright headers (`# Copyright (c) 2026, HeyKoala and contributors`)
  must remain on upstream files, including files TEX modifies.
- TEX Engine is distributed/hosted under AGPL-3.0 as a derivative work; users
  interacting with it over a network must be able to obtain the corresponding
  source (AGPL §13). The admin "About" screen links to the source repository.
- `NOTICE.md` in the repository root records the attribution.
