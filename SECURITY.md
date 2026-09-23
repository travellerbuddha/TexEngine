# Security Policy — TEX Engine

TEX Engine is a hotel commercial platform (CRS, contracts, pricing, booking, call centre,
CRM, payments, integrations) built on a fork of Kamra PMS (AGPL-3.0). This policy covers
this fork. Vulnerabilities in upstream Kamra PMS code that also affect upstream should be
reported to the Kamra project as well (see its own SECURITY.md); do not send TEX data to
the upstream project.

## Reporting a vulnerability

**Do not open a public issue, pull request or discussion for a security problem.**

- Security contact: **not yet set** — the owner must name a monitored security contact
  before go-live (tracked in `docs/tex-engine/GO_LIVE_READINESS.md`, owner inputs). Until
  then, report privately to the repository owner through GitHub.
- Include: affected URL or endpoint, the role/hotel you were logged in as, steps to
  reproduce, and the impact you observed. Do **not** include real guest data, full card
  numbers, CVV, passwords or live tokens in a report; redact them.
- Test only against a non-production site or data you own. Do not run denial-of-service,
  spam, social-engineering or physical tests, and never test against a live payment
  provider or channel manager account.

The response target (proposed: acknowledgement within 3 working days) is confirmed when the
security contact is named. We agree a fix and a disclosure date with the reporter; security
fixes are released on the deployed line first.

## Supported versions

Only the currently deployed version of this fork receives security fixes. Upstream Kamra
PMS releases are **not** merged automatically (a deliberate decision); an upstream
security fix is reviewed and ported by hand.

## Highest-severity areas

Reports in these areas are treated as highest priority:

- **Tenant isolation** — reading or changing data of another enterprise, hotel group or
  hotel (enforced server-side by `kamra.tex.security`: every TEX endpoint declares a
  capability and a hotel scope; hiding something in the UI is never the control).
- **Money** — changing a price, a confirmed reservation's locked price, a payment, refund,
  allocation or credit without the right capability, or making a guest-facing flow charge
  or refund a wrong amount. Prices are computed only by the deterministic pricing engine
  from frozen published contract versions.
- **Payments** — TEX never stores a full card number (PAN) or CVV; card entry happens at
  the payment provider. Anything that stores, logs or returns PAN/CVV is critical.
- **Secrets** — passwords, API keys, webhook secrets and raw tokens must never be logged
  or returned by an API; only token hashes are stored. Webhooks (payments, channel
  distribution) must be signature-checked and fail closed.
- **Authentication and capabilities** — a bypass of `require_capability`, of the access
  grants model, or of the guest self-service (manage-booking) token checks.

## Surfaces reachable without a login

The following are intentionally reachable without a session; anything else reachable
without one is a bug:

- `kamra/tex/api/public.py` — the TEX booking engine and guest self-service (rate limited,
  validated server-side, idempotency keys on writes);
- `kamra/tex/api/payments.py` — payment provider callbacks (signature-checked);
- `kamra/tex/api/distribution.py` — channel-distribution webhook (HMAC-signed, time window,
  replay-safe);
- `kamra/tex/api/system.py` `ping` — liveness for uptime monitors (rate limited, read-only,
  answers four booleans: `ok`, `db`, `cache`, `scheduler`; ADR-047);
- legacy Kamra guest surfaces kept from upstream (`kamra/public_api.py`, self check-in, QR
  menu, legacy payment/channel callbacks). They refuse to sell or change TEX hotels
  (ADR-028).

## Scope notes

- The AI/agent surfaces inherited from upstream (MCP server, copilot tools) run as the
  calling Frappe user; a permission bypass there is in scope and high severity. No LLM
  ever computes a TEX price.
- TEX booking sites accept no custom CSS or JavaScript: branding is limited to
  server-validated `#RRGGBB` colours and a font allow-list. Any path that injects markup,
  style or script into a booking site or a guest e-mail is in scope.
- Findings in third-party services (payment providers, channel managers, SMTP, hosting)
  should go to those vendors; tell us too if TEX handles their output unsafely.

## License

TEX Engine is distributed under the GNU Affero General Public License v3.0, like the
upstream Kamra PMS it is derived from. See `license.txt` and `NOTICE.md`.
