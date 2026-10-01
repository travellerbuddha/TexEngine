# TEX Engine — engineering rules (persistent)

TEX Engine is a hotel **commercial platform** (CRS, contracts, pricing, booking,
call centre, CRM, payments, integrations) forked from Kamra PMS (AGPL-3.0).
It is **not a PMS**. Full requirements: `docs/tex-engine/PRODUCT_SPEC.md`.

## Recover state from (in this order)
`CLAUDE.md` → `docs/tex-engine/HANDOFF.md` (the work left and how to do it) →
`docs/tex-engine/IMPLEMENTATION_STATUS.md` →
`docs/tex-engine/TARGET_ARCHITECTURE.md` → `docs/tex-engine/ARCHITECTURE_DECISIONS.md`
→ `docs/tex-engine/PRODUCT_SPEC.md` → `git log`. Never ask the owner to restate requirements.

## Layout
- Frappe app name stays `kamra` (ADR-001). Do not rename the Python package/app.
- `kamra/tex/` — TEX domain code. **`kamra/tex/pricing/` must not import frappe**
  (pure, deterministic, unit-testable). Frappe glue lives in `*/repository.py`,
  `*/loader.py` and `kamra/tex/api/*.py`.
- TEX DocTypes live in Frappe modules `TEX Commercial`, `TEX Booking`, `TEX CRM`,
  `TEX Payments`, `TEX Connect`, `TEX Platform` (`kamra/tex_*/doctype/`).
- Legacy Kamra PMS code is KEPT but hidden from TEX navigation; do not delete it
  when something still depends on it.

## Money & pricing (non-negotiable)
- Money is `decimal.Decimal` end to end; never `float`. Use `kamra.tex.money`.
  DB money fields are `Currency`/decimal. Convert to `str` in JSON, never float.
- No LLM ever computes a price. Pricing is deterministic and explainable: every
  step appends an explanation entry naming the rule and scope that won.
- Published contract versions are immutable; prices are computed from the frozen
  published payload, never from mutable tables. Confirmed reservations are
  price-locked; changes go through modification → revision → audit.
- Rule precedence (most specific wins unless the rule declares otherwise):
  GLOBAL < HOTEL < MARKET < CONTRACT < VERSION < ROOM < PERIOD < COMBINATION < OVERRIDE.
- Child age: integer months from DOB+arrival (or declared age); never float compare.
- Never silently assign a market when ambiguous; fail with a clear error.

## Security
- Every whitelisted endpoint declares capability + property scope via
  `kamra.tex.security` (`require_capability(cap, property)`); frontend hiding is
  never sufficient. Tenant isolation: Enterprise → Hotel Group → Hotel.
- Never log passwords, CVV, PAN, secrets or raw tokens. Store only token hashes.
- Public endpoints: rate limited, validate everything server-side, idempotency keys
  on writes, signed webhooks.

## Process
- Small coherent commits; run tests before committing a milestone; update
  `docs/tex-engine/IMPLEMENTATION_STATUS.md` (COMPLETE/PARTIAL/NOT STARTED/BLOCKED).
- Record architectural decisions in `ARCHITECTURE_DECISIONS.md` (ADR-NNN).
- Schema changes: DocType JSON + patch in `kamra/patches/` listed in `patches.txt`.
- Keep AGPL notices and upstream copyright headers.

## Testing
- Pure pricing tests: `python -m pytest kamra/tex/tests/unit -q` (no bench needed).
- Integration tests (bench): `bench --site test.localhost run-tests --module kamra.tex.tests.integration.<mod>`.
- Upstream suites: eval harness (76/76), frontdesk journey (13/13), banquet tests.
- Frontend: `cd frontend && npm run build` (tsc + vite). E2E: Playwright in `frontend/e2e`.
- Local bench used in cloud sessions: `/home/user/bench/frappe-bench` (user `frappe`,
  `source /home/user/bench/env.sh`); see `docs/tex-engine/DEV_ENVIRONMENT.md`.

## Style
- Python: tabs, ruff config in `pyproject.toml`. TS/React: existing conventions,
  TEX design-system components in `frontend/src/tex/ui`, strings via i18n `t()`.
