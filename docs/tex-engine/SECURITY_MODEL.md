# TEX Engine — Security Model & Threat Review

## 1. Assets
Guest PII (identity, contact, DOB, ID docs), commercial secrets (contract costs, markups,
margins), money movements (payments, refunds, links), availability/inventory integrity,
credentials (provider keys, API keys, webhook secrets), audit trail integrity.

## 2. Actors and trust boundaries
| Actor | Surface | Trust |
|---|---|---|
| Anonymous guest | `/book`, widget, public booking API, manage-booking token | Untrusted |
| Authenticated staff | TEX SPA / Desk, `/api/method/kamra.tex.api.*` | Trusted within granted scope |
| Enterprise/group admins | Same, wider scope | Trusted within scope |
| Integrations (PMS, CM, payment providers) | Webhooks, outbox deliveries | Authenticated by signature/secret |
| AI agents (MCP) | MCP tools | Role-gated; never compute prices |
| Platform operator | System Manager | Full |

## 3. Tenancy & authorisation (ADR-011)
- Hierarchy: Platform → Enterprise → Hotel Group → Hotel (Property).
- **Capabilities** (code registry `kamra/tex/security/capabilities.py`): `price.view`,
  `price.view_cost`, `price.any_channel`, `contract.edit`, `contract.publish`, `price.override`,
  `promotion.edit`, `markup.edit`, `fx.edit`, `reservation.create`, `reservation.modify`, `reservation.cancel`,
  `payment.view`, `payment.link`, `payment.refund`, `inventory.edit`, `restriction.edit`,
  `crm.view`, `crm.edit`, `guest.export`, `report.view`, `booking_site.edit`, `connect.admin`,
  `settings.admin`, `user.admin`.
- Sources: `TEX Access Grant` (user × scope × profile, live only: `valid_until` today or later,
  not disabled); a user's own (hand-made) Frappe User Permissions on Property are the legacy
  scope, where the Frappe role defaults apply. The User Permission rows TEX mirrors from grants
  (`tex_managed`) are never read as scope: an ended grant grants nothing, and its rows are
  removed just after the site's midnight (`grants.remove_expired_grants`, audited
  `grant.expired`) (G-94). Legacy non-strict mode opens every hotel only to users TEX never
  granted anything.
- **Sales channels** (ADR-050): staff price and book only on the channels they are entitled to
  at a hotel: the channel list of each profile granted there (blank = the call centre), every
  channel with `price.any_channel`. A profile's channels serve only its own capabilities:
  pricing channels come from profiles with `price.view`, booking channels from profiles with
  `reservation.create`. `scope.require_channel(channel, property, to=…)` checks the channel a
  search asks for (pricing), and on quote, quote summary and booking the channel of the signed
  offer or stored quote itself (booking), in every CRS call and in `create_booking` for staff.
  Modifications keep the reservation's channel; a change of room, rate plan, board or market
  needs booking entitlement for it. A booking site sells only on a web channel (DIRECT_WEB,
  META), for guests and signed-in staff alike (staff bookings there are flagged and audited).
  Granting a profile needs its channels.
- `require_capability(cap, property)` on every TEX endpoint; list endpoints filter by
  `permitted_properties()`; document endpoints resolve the document's property first.
- Legacy `require_roles` resolves `property` / `reservation` / `folio` / `room` / `room_type` /
  `group_booking` arguments to a hotel and refuses hotels outside the caller's scope (ADR-019).
- `permission_query_conditions` + `has_permission` on every hotel-bound DocType
  (`kamra/tex/security/perm.py`) — Desk lists, reports and `frappe.get_list` follow TEX scope.
- Guest self-service is authorised by the manage token and ownership check, never by
  impersonating a staff user (ADR-020).
- TEX DocTypes are written only through TEX services; business roles have no generic
  Desk/REST write access, and every hotel-bound TEX DocType (incl. parent-scoped ones and
  `Guest`) is read-scoped (ADR-022).
- `strict_tenancy` (default on): a non-admin user without any scope sees nothing.
- Grants sync Frappe `User Permission` (Property, apply to all doctypes). Isolation does not rely
  on them: every hotel-bound TEX DocType and the 53 legacy Kamra DocTypes bound to a hotel by a
  `property` link (`perm.LEGACY_PROPERTY_DOCTYPES`) have the TEX permission hooks, so Desk lists,
  REST and `frappe.get_list` follow the TEX scope even for a user without any row (Frappe itself
  does not restrict such a user).

## 4. Threats and controls
| Threat | Control |
|---|---|
| Cross-tenant read/write (IDOR) | Capability + property scope on every endpoint; document→property resolution; integration tests per endpoint family |
| Price tampering from client | Server prices from signed offer inputs; client totals ignored; HMAC offer keys with expiry; quotes persisted server-side |
| Selling at another channel's prices | Channel entitlement per profile, capability and hotel (ADR-050): the searched channel, and the offer's or quote's own channel on quote and book, are checked; a Booking Engine quote cannot be booked from the CRS; a booking site sells only on a web channel; a modification never switches the channel and a change to another product needs the reservation's channel |
| Access kept after a grant ends | Live grants are the only authority; mirrored User Permissions are ignored by the TEX scope and removed at the site's midnight; legacy hotel-bound DocTypes follow the TEX scope (G-94) |
| Promotion/coupon abuse | Server-side eligibility; usage limits enforced with row locks; per-guest limits keyed by normalised email hash; rate limit on code checks |
| Inventory race / double sell | `TEX Inventory Day` row locks + recount under lock; idempotency keys |
| Replay / duplicate payments | Caller-namespaced idempotency keys (no cross-caller replay); `FOR UPDATE` on transactions and bookings |
| Forged webhooks / callbacks | Signed callback URL; provider verification (HMAC hash, stored checkout token, server-to-server status); unverifiable → unchanged, non-final → Pending (ADR-023) |
| Gateway substitution | Payments only through a provider account of the same hotel; payment links keep their fixed gateway |
| Card data exposure | Hosted/tokenised checkout only; never receive PAN/CVV; store brand + last4 only; log scrubber |
| Token theft (manage booking, payment links) | 32-byte random tokens, only sha256 stored, expiry, rate limits, rotation for sensitive actions |
| XSS | React escaping; no `dangerouslySetInnerHTML` for user/admin content in TEX screens; branding restricted to tokens (validated colours/fonts/radii); CSP for booking pages |
| CSRF | Frappe CSRF token on session-authenticated POSTs; public booking endpoints are stateless (no cookies trusted) and rate limited |
| SQL injection | Parameterised queries only (`%(name)s`); no string-built SQL with user input |
| Brute force / scraping | `frappe.rate_limiter.rate_limit` on public search/quote/book/token endpoints |
| Secret leakage | Frappe `Password` fields (encrypted at rest); never returned by APIs; never logged |
| Audit tampering | `TEX Audit Event` has no write/delete permission for any role; inserted only by server code |
| Embedding abuse (clickjacking) | Booking iframe allowed only for `allowed_embed_origins` via CSP `frame-ancestors` |
| Uploads | Checked on the server (ADR-046 and review): TEX branding images by their bytes (PNG/JPEG/GIF/WebP, every frame decoded, 2 MB) through `admin.upload_site_image`; the public folder serves only an allow-list (images, video, audio, PDF, office documents, fonts, zip) judged on the name File stores, on every path, before anything is written (File controller extension); everything else is private |
| Bearer tokens in URLs | Guest links carry tokens in the URL fragment (never sent to a server); token endpoints take POST bodies only; payment pages send no Referer (ADR-046); only token hashes are stored |
| PII over-exposure | `crm.view` / `guest.export` capabilities; masked ID numbers (existing `_mask_id`); exports audited |
| Open redirect through payment return URLs | Browser-supplied return URLs accepted only for the TEX host or a DNS-verified booking domain (ADR-021) |
| Custom-domain takeover | `verified` set only by the DNS TXT check; editing a row resets it; a domain can belong to one site only |
| Group-level records edited from one hotel | Booking sites serving a hotel group need the capability at every hotel of the group |
| Marketing without consent (GDPR/KVKK) | Separate consent fields with timestamp/source/text version; transactional ≠ marketing; abandoned-booking contact only with the profile's own consent; an anonymous booking never grants consent on an existing profile, it is recorded as a request (ADR-046) |

## 5. Logging rules
Never log passwords, CVV, PAN, secrets or raw tokens. `kamra.tex.security.redact()` scrubs
known keys (`password`, `secret`, `token`, `card`, `cvv`, `pan`, `authorization`) before any
audit payload. TEX code logs exceptions only through `audit.log_exception()`, which writes the
traceback **without frame variables** (Frappe's default traceback includes locals, which can
hold guest data, callback headers or magic-link URLs) and masks token-like values; a test
asserts that a failed booking e-mail leaves no token in the Error Log.

Bearer links: manage-booking and payment-link tokens are stored only as sha256 hashes. The
clear URL exists in the API response that created it and in the outgoing e-mail; Frappe's
Email Queue keeps the rendered message until its retention purge (System Manager access only).
Staff who lose a payment link reissue it (new token; the old URL stops working).
A retried guest booking request (same session and idempotency key) gets a signed 24-hour
resume token instead of the manage token (ADR-025); staff re-sending a confirmation rotate
the manage token. Neither is stored in clear. Agent-facing booking responses never contain
the guest's manage token.

## 6. Review log
- 2026-09-22 adversarial review: 4 High, 7 Medium, 5 Low findings — all fixed with regression
  tests in `kamra/tex/tests/integration/test_security_regressions.py` (ADR-022, ADR-023).
  Accepted as designed: audit trail of one reservation readable with `reservation.view`;
  loyalty redemption gated by `payment.link` (bounded to the booking's own guests and the
  program's max-% cap).

## 7. Known gaps (tracked)

The authoritative list is `FINAL_GAP_AUDIT.md` (2026-09-23 audit). The security-relevant items
G-26 and G-83 are fixed (ADR-040, ADR-046), as are the Critical G-01…G-03 and the High
G-10…G-16. From G-83, two owner decisions remain: a double opt-in e-mail for consent asked for
on a known profile (needs SMTP), and payment links e-mailed before 2026-09-23 keep their token
in the path until they expire. The notes below predate that audit.
- Legacy PMS endpoints resolve every record argument (`order`, `outlet`, `task`, `function`,
  `guest`, generic `name` ...) to its hotel through `kamra.authz.RECORD_ARGS` (ADR-027). On Desk
  and REST, legacy DocTypes with a Property link (POS, laundry, housekeeping, banquet) follow
  the TEX scope through the permission hooks (G-94; before, only the User Permissions that grants
  mirror filtered them, which a user without any row escapes; probed 2026-09-23: a hotel GM reads
  its own POS orders and action logs, not another hotel's).
- iyzico / Sipay / NestPay adapters follow the public integration documents but are **not
  production-verified**; enabling a Production account requires the provider's sandbox
  certification with real merchant credentials.
- Legacy Kamra endpoints use `frappe.throw` text without `_()` in places (upstream style).
