# Work in progress — paused 2026-09-23 (owner request)

Snapshots of two go-live money fixes that were in progress when work was paused. They are
**not applied** to the code on this branch; they are kept here so nothing is lost if the
development container is recycled. Re-apply them on a branch, then finish and verify
(full integration suite, E2E), before merging.

| Gap | Files | State when paused |
|---|---|---|
| G-30 pricing-policy cascade + G-31 infant-band precedence ("occupancy precedence v2") | `DESIGN-G30-G31.md`, `g30-g31-occupancy-precedence-commits.patch` (8 commits on top of `02a0085`; `git am`), `g30-g31-occupancy-precedence-uncommitted.diff` (then `git apply`) | Implemented and adversarially reviewed; the review-fix step was mid-way. Its final full test run did not complete (a lock bug in the local test runner stalled the shared bench). The snapshot's own ADR is numbered 042 — renumber it (041/042 are taken by the payments ADRs). |
| G-45 self-service money flows (pay the difference before a change applies, automatic refund, credit) | `DESIGN-G45.md`, `g45-guest-change-money-uncommitted.diff` (on top of `7b5ad85`; `git apply`) | Backend partly written, not tested, no migration run. The new DocType `TEX Guest Change Request` and patch p20 are part of the design. |

Delete this folder once both are merged.
