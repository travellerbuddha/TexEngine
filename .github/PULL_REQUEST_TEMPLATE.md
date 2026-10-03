## What & why

<!-- One or two sentences. Link the issue if there is one: Fixes #123 -->

## Checklist

- [ ] PR targets the default branch **`claude/inspiring-ptolemy-i6wdu2`** (not `main`)
- [ ] Title / commits follow [Conventional Commits](https://www.conventionalcommits.org/)
      (`feat:` / `fix:` / `docs:` / `chore:` …) — this drives the changelog.
      Releases default to **PATCH** (`2.6.x`); a `feat:` commit does **not**
      auto-bump to the next minor. See [`RELEASING.md`](../RELEASING.md).
- [ ] `cd frontend && npm ci && npm run build` passes (if frontend touched; commit the
      rebuilt `kamra/public/frontend` **and** `kamra/public/tex`: CI fails when the committed
      bundles differ from a fresh build, ADR-073)
- [ ] Eval harness still green (if Python touched):
      `from kamra.scripts.eval_harness import execute; execute()`
- [ ] Anything removed/renamed that a self-hoster could depend on (doctype,
      whitelisted method, config key) is called out below as **breaking**

## Breaking changes

<!-- "None" or the list -->
