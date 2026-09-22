# TEX UI workstreams — conventions and file ownership

The core architecture (backend services + API, TEX shell, design system, i18n) is
stable, so the UI areas are built in parallel. Each workstream owns disjoint files;
shared files change only through the integrator.

## Ownership

| Workstream | Owns (create/edit freely) |
|---|---|
| Integrator (shared) | `frontend/src/tex/ui/**`, `tex/lib/**`, `tex/shell/**`, `tex/TexApp.tsx`, `tex/i18n/index.ts`, `tex/i18n/locales/{core,dashboard}/**`, `tex/screens/dashboard/**`, `frontend/src/App.tsx`, `vite*.config.ts`, `package.json`, all backend files outside `kamra/tex/api/ui_*.py` |
| A — Rates & Inventory | `tex/screens/rates/**`, `tex/screens/inventory/**`, `tex/i18n/locales/{rates,inventory}/**`, `kamra/tex/api/ui_rates.py` (new, only if an endpoint is missing) |
| B — CRS, Call Center, Reservations | `tex/screens/crs/**`, `tex/screens/reservations/**`, `tex/i18n/locales/{crs,reservations}/**`, `kamra/tex/api/ui_crs.py` (new, only if needed) |
| C — Guest booking + widget | `frontend/src/booking/**`, `frontend/src/widget/**`, `frontend/booking.html` |
| D — Back office | `tex/screens/{crm,payments,reports,connect,settings,booking-engine}/**`, `tex/i18n/locales/{crm,payments,reports,connect,settings,booking-engine}/**`, `kamra/tex/api/ui_backoffice.py` (new, only if needed) |

Each area's `routes.tsx` is mounted by `TexApp.tsx` at `/tex/<area>/*`; the area
defines its own sub-routes there. A component needed by several areas is first built
inside the area (`screens/<area>/components/`) and promoted to `tex/ui` by the
integrator.

## Rules every screen follows

- **Prices come from the server.** Never compute, round or sum money client-side
  except for display grouping. Amounts are decimal strings: render with `<Money>`
  / `money()`; edit with `<DecimalInput>` (string in, string out).
- **API**: `tex(module, method, args, {post})`, `useTexQuery`, `useTexMutation`
  (`tex/lib/api.ts`). Signatures: `kamra/tex/api/<module>.py`. Writes use POST.
  One `idempotencyKey()` per user intent for bookings, payments, refunds, links.
- **Permissions**: hide actions the user cannot take (`useSession().can(cap)`),
  but always handle a `PermissionError` from the server (`<ErrorState>`).
  Audited actions (cancel, withdraw, refund, override, archive) ask for a reason
  (`<ConfirmDialog requireReason>`).
- **i18n**: `const { t } = useTexT()`; keys namespaced by area (`rates.*`);
  catalogs `tex/i18n/locales/<area>/<lang>.json` for **en, tr, de, ru, ro, pl** with
  every key present in all six. Plurals: `{ "one": …, "other": … }` + `{count}`.
  Dates/numbers only through `tex/lib/format.ts`.
- **Accessibility (WCAG 2.2 AA)**: one `<PageHeader>` (h1) per page; every control
  inside `<Field>` or with an `aria-label`; keyboard operable (no click-only
  divs); visible focus (inherited); tables have a `caption`; status never by
  colour alone (text badges); dialogs via `<Dialog>`/`<Drawer>` (focus trap).
- **Responsive**: usable at 375 px; secondary table columns `hideBelow`.
- **States**: loading (skeleton/spinner), empty (`<EmptyState>`), error
  (`<ErrorState onRetry>`), success toast (`useToast`).

## Dev loop

```
ln -s /home/user/TexEngine/frontend/node_modules frontend/node_modules   # in a worktree
cd frontend && npx tsc -b                                                  # typecheck
npx vite build --outDir /tmp/<area>-build --emptyOutDir                    # build check (never commit kamra/public)
KAMRA_API_TARGET=http://127.0.0.1:8000 KAMRA_API_HOST=test.localhost npx vite --port 51xx
```

The dev server serves the SPA at `http://localhost:51xx/tex` (basename `/`) and
proxies `/api` to the bench (`bench serve --port 8000`, site `test.localhost`,
seeded by `kamra.tex.devtools.demo_seed`). Demo users: `revenue@demo.tex`,
`agent@demo.tex`, `finance@demo.tex`, `beach.gm@demo.tex` (Hotel Admin at Aurora
Beach Resort); guest booking site slug `aurora`.
