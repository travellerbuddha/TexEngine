# Work in progress — paused 2026-09-23 (owner request)

A snapshot of a go-live money fix that was in progress when work was paused. It is
**not applied** to the code on this branch; it is kept here so nothing is lost if the
development container is recycled. Re-apply it on a branch, then finish and verify
(full integration suite, E2E), before merging.

| Gap | Files | State when paused |
|---|---|---|
| G-45 self-service money flows (pay the difference before a change applies, automatic refund, credit) | `DESIGN-G45.md`, `g45-guest-change-money-uncommitted.diff` (on top of `7b5ad85`; `git apply`) | Backend partly written, not tested, no migration run. The new DocType `TEX Guest Change Request` and patch p20 are part of the design. |

G-30/G-31 ("occupancy precedence v2", ADR-043) were finished and merged; their snapshot was
removed. Delete this folder once G-45 is merged.
