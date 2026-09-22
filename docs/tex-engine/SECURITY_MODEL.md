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
  `price.view_cost`, `contract.edit`, `contract.publish`, `price.override`, `promotion.edit`,
  `markup.edit`, `fx.edit`, `reservation.create`, `reservation.modify`, `reservation.cancel`,
  `payment.view`, `payment.link`, `payment.refund`, `inventory.edit`, `restriction.edit`,
  `crm.view`, `crm.edit`, `guest.export`, `report.view`, `booking_site.edit`, `connect.admin`,
  `settings.admin`, `user.admin`.
- Sources: default profile per Frappe role + `TEX Access Grant` (user × scope × profile).
- `require_capability(cap, property)` on every TEX endpoint; list endpoints filter by
  `permitted_properties()`; document endpoints resolve the document's property first.
- Legacy `require_roles` upgraded to resolve `property` / `reservation` / `folio` / `group_booking` /
  `guest`-style arguments to a property and call `assert_property_access`.
- `strict_tenancy` (default on): a non-admin user without any scope sees nothing.
- Grants sync Frappe `User Permission` (Property, apply to all doctypes) so Desk lists and
  `frappe.get_list` are isolated too.

## 4. Threats and controls
| Threat | Control |
|---|---|
| Cross-tenant read/write (IDOR) | Capability + property scope on every endpoint; document→property resolution; integration tests per endpoint family |
| Price tampering from client | Server prices from signed offer inputs; client totals ignored; HMAC offer keys with expiry; quotes persisted server-side |
| Promotion/coupon abuse | Server-side eligibility; usage limits enforced with row locks; per-guest limits keyed by normalised email hash; rate limit on code checks |
| Inventory race / double sell | `TEX Inventory Day` row locks + recount under lock; idempotency keys |
| Replay / duplicate payments | Unique `idempotency_key` on transactions; webhook event ids stored; state machine on links |
| Forged webhooks | HMAC signature verification (provider-specific), constant-time compare, reject when secret missing in production mode |
| Card data exposure | Hosted/tokenised checkout only; never receive PAN/CVV; store brand + last4 only; log scrubber |
| Token theft (manage booking, payment links) | 32-byte random tokens, only sha256 stored, expiry, rate limits, rotation for sensitive actions |
| XSS | React escaping; no `dangerouslySetInnerHTML` for user/admin content in TEX screens; branding restricted to tokens (validated colours/fonts/radii); CSP for booking pages |
| CSRF | Frappe CSRF token on session-authenticated POSTs; public booking endpoints are stateless (no cookies trusted) and rate limited |
| SQL injection | Parameterised queries only (`%(name)s`); no string-built SQL with user input |
| Brute force / scraping | `frappe.rate_limiter.rate_limit` on public search/quote/book/token endpoints |
| Secret leakage | Frappe `Password` fields (encrypted at rest); never returned by APIs; never logged |
| Audit tampering | `TEX Audit Event` has no write/delete permission for any role; inserted only by server code |
| Embedding abuse (clickjacking) | Booking iframe allowed only for `allowed_embed_origins` via CSP `frame-ancestors` |
| Uploads | Existing Frappe file handling; TEX branding images restricted to image MIME types and size |
| PII over-exposure | `crm.view` / `guest.export` capabilities; masked ID numbers (existing `_mask_id`); exports audited |
| Marketing without consent (GDPR/KVKK) | Separate consent fields with timestamp/source/text version; transactional ≠ marketing; abandoned-booking contact only with consent or legitimate transactional basis |

## 5. Logging rules
Never log passwords, CVV, PAN, secrets or raw tokens. `kamra.tex.security.redact()` scrubs
known keys (`password`, `secret`, `token`, `card`, `cvv`, `pan`, `authorization`) before any
`frappe.log_error`/audit payload.

## 6. Known legacy gaps (tracked)
See GAP_ANALYSIS §1: legacy PMS endpoints historically lacked property checks. Hardening
status is tracked in IMPLEMENTATION_STATUS (R-53).
