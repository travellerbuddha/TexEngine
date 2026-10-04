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
- **Withheld fields** (ADR-056): pricing internals (`Reservation.tex_pricing_snapshot`,
  `tex_cost_amount`, `tex_margin_amount`, `tex_fx_rate`, `tex_payload_hash`, `TEX Quote.result_json`,
  `payload_hash` (the frozen payload's digest confirms a guess of its cost, G-99, ADR-075; a refused reprice's audit
  event, which records two digests, is served in Desk / REST to platform administrators only, 2P),
  `TEX Reservation Revision.snapshot_before` / `snapshot_after`) and a guest's stored totals over
  every tenant (`Guest.tex_stays`, `tex_lifetime_value`, `tex_lifetime_currency`, `tex_last_stay`,
  `tex_loyalty_points`) are at Frappe permlevel 1, which only System Manager reads. Desk and REST
  leave them out for every business role and refuse filters, sorting and aggregates on them (a
  legacy string aggregate is dropped from the query); the
  change history masks their values and a generic write's response leaves them out
  (`kamra/tex/security/internals.py`). The TEX API serves pricing internals by `price.view_cost`
  at the hotel, and guest totals computed over the viewer's hotels and loyalty programs only.
  Also withheld (ADR-056 reviews): an abandoned case's profile, e-mail and phone, and what leads to
  the person (its session, quote and recovery booking); a funnel event's profile, e-mail hash, session
  and payload. On customised role permissions (Custom DocPerm) System Manager keeps its
  permlevel-1 row (p40, `ensure_custom_perms` in the permission scripts); a business role at
  permlevel ≥ 1 is printed and audited by p40. A masked change history keeps the values of pricing
  internals and guest totals in a platform-level audit event (`version.withheld`) that the TEX audit
  log never shows in a record's trail to anyone else; contact data is masked without a copy (p45
  removed the copies kept before). Only a generic write request's response is trimmed (never a
  `db_set`).
- **CRM tenancy** (ADR-036, ADR-040, ADR-056): stays, value, extras, cancellations, segment facts and
  loyalty come from the viewer's hotels; a guest's loyalty, in the profile and in the program
  ledger, shows only the programs that reach the viewer's hotels (their own or their group's),
  another hotel's entries in a shared program only as points, status and month (no booking, stay,
  dates, reason or author), and never a guest the viewer may not see. In Desk / REST a loyalty entry
  is read at its own hotel only (`TEX Loyalty Ledger.property`: the stay's or booking's, or the hotel
  a manual adjustment was made for; ADR-056 second review).
- **Guest identity and duplicates** (ADR-056 reviews): a booking joins a profile by its e-mail; a phone
  finds one only for staff, only when exactly one profile has it. The e-mail is the exact address, in any case:
  an accented look-alike is another guest, though the database compares accents away (owner, 2P; ADR-080,
  `booking.profile_of_email`, also a member link's), and a typed address must be one plain ASCII address
  (`booking.plain_email`; a channel's other address is left out), on every path that stores a profile's (2Q,
  ADR-081: `Guest.validate` for the Desk form, REST, imports and the legacy paths, a changed address only; the
  legacy direct writes refuse it or leave it out). A booking made for someone else follows the address entered
  (owner, 2Q). Duplicates are merged by
  `crm.merge_guests` (`crm.edit` at every hotel either profile has records at, one enterprise, consent
  the stricter of the two, audited); an erasure withdraws every consent and removes contact data from
  cases, funnel, bookings' booker fields and the change history. A merge locks both profiles and reads
  what it moves with locking reads; whoever links a record to a profile locks it first; an erased
  profile (`tex_erased_at`) is never merged; the legacy merge endpoint checks the hotel of every record
  too; the duplicate is kept 90 days as a Deleted Document, System Manager only (ADR-056 third review).
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
| Selling a TEX hotel outside TEX (Desk form, REST, Data Import) at the legacy price | The Reservation controller refuses a new reservation at a TEX hotel unless the TEX booking service, a channel's sale or a migration importer wrote it. Their marks are in-process flags (REST drops `flags`; pricing-source or lock fields in a payload change nothing), popped on the insert they cover. An import needs `price.override` at the hotel, keeps the file's amount as "Imported", is price-locked and audited. A stay at a TEX hotel changes its stay, price, commercial record or hotel only through the TEX services, TEX-priced or not. Roles keep their Frappe permissions; the rule is the hotel's, platform administrators included (ADR-052, G-92). The rule applies once the hotel is live in TEX: `Property.tex_live_from` is set only through `admin.set_hotel_live` (`settings.admin` at the hotel, reason, audited, in-process flag; the Property controller refuses it from Desk, REST or data import). An imported amount is corrected only with `price.override` and a reason (revision and audit). The TEX modification flag covers one save; there is no request-wide bypass (ADR-052 review) |
| Selling at another channel's prices | Channel entitlement per profile, capability and hotel (ADR-050): the searched channel, and the offer's or quote's own channel on quote and book, are checked; a Booking Engine quote cannot be booked from the CRS; a booking site sells only on a web channel; a modification never switches the channel and a change to another product needs the reservation's channel |
| Access kept after a grant ends | Live grants are the only authority; mirrored User Permissions are ignored by the TEX scope and removed at the site's midnight; legacy hotel-bound DocTypes follow the TEX scope (G-94) |
| Promotion/coupon abuse | Server-side eligibility; usage limits enforced with row locks; per-guest limits keyed by normalised email hash; rate limit on code checks; a members-only price only for a member of the hotel's loyalty program: the search prices a member as one only for a caller the agent sees (`crm.view`), the offer key signs it, and a booking of a member's price is refused unless the profile it joins is a member, checked before anything is written and again under the profile's lock (C-04, ADR-077) |
| Inventory race / double sell | `TEX Inventory Day` row locks + recount under lock; idempotency keys |
| Replay / duplicate payments | Caller-namespaced idempotency keys (no cross-caller replay); `FOR UPDATE` on transactions and bookings |
| Forged webhooks / callbacks | Signed callback URL; provider verification (HMAC hash, stored checkout token, server-to-server status); unverifiable → unchanged, non-final → Pending (ADR-023) |
| Gateway substitution | Payments only through a provider account of the same hotel; payment links keep their fixed gateway |
| Card data exposure | Hosted/tokenised checkout only; never receive PAN/CVV; store brand + last4 only; log scrubber |
| Token theft (manage booking, payment links) | 32-byte random tokens, only sha256 stored, expiry, rate limits, rotation for sensitive actions |
| A web member's sign-in link or session taken or guessed (C-04, ADR-078) | The link: a 32-byte random token in the URL fragment of the mail, taken out of the address bar before the booking app starts, opened with a click; its sha256 kept in the cache for 30 minutes and read-and-deleted in one step (used once, on its own site only). The session: another 32-byte token, only its sha256 stored (`TEX Member Session`), revoked on sign-out and by a new sign-in on the device, worthless for an erased profile, deleted by an erasure, purged 30 days after it ended; staff who may read the guest (`crm.view`) see where and until when a guest is signed in, never a token, and staff who may edit them (`crm.edit`) sign them out of one device or all, audited (2O, ADR-079). An erasure also drops the links mailed to its address and not opened yet (2O). A link is sent only to the one plain ASCII address typed (no display name, list or look-alike accented domain), and a join link joins only the profile of that e-mail in the site's enterprise (the link proves the address); a signed-in guest's join is also confirmed by a link, never by the session. Rate limits: 10 link requests per client per 10 minutes, 3 mails per address and site an hour, an idempotency key per request; the session endpoints use the public write / search limits |
| Another hotel's tag container reading a member's session on the platform's shared host (review round 1 B1) | On a hotel's own host only that hotel's pages run, and the session stays on the device for 30 days (owner, 2026-10-03); on the platform's shared host (`/book/<site>`) it is kept in the tab only, and a site's page removes every other site's member data before any of its scripts run. A same-origin script of the same hotel can still use its own guest's session (as it can a manage token): the hotel's own tags are the hotel's responsibility |
| Learning from the site who is a guest or a member (enumeration) | A link request answers the same whatever the e-mail (an address without a profile gets a mail saying so, not a different answer), and the same when an address's limit is reached; a session shows the guest only their own name, e-mail and membership |
| A membership staff ended for abuse made active again from the web | Staff who end it may block a rejoin on the web (`rejoin_blocked`); a web join then changes nothing and answers as for any address, the mail (to the address's owner only) says to ask the hotel; only staff joining the guest lift it (C-04h, 2O, ADR-079) |
| A member's price booked by someone else | The booking checks the membership of the profile it joins (its e-mail), not the session: anyone else gets `MEMBERS_ONLY`; the "Member price" a visitor sees is the totals of a member's search only (its offer keys never reach the visitor, so every key a visitor holds is anyone's price) (ADR-078) |
| XSS | React escaping; no `dangerouslySetInnerHTML` for user/admin content in TEX screens; branding restricted to tokens (validated colours/fonts/radii); CSP for booking pages |
| CSRF | Frappe CSRF token on session-authenticated POSTs; public booking endpoints are stateless (no cookies trusted) and rate limited |
| SQL injection | Parameterised queries only (`%(name)s`); no string-built SQL with user input |
| Brute force / scraping | `frappe.rate_limiter.rate_limit` on public search/quote/book/token endpoints |
| Secret leakage | Frappe `Password` fields (encrypted at rest); never returned by APIs; never logged |
| A guest-registered OAuth client (consent phishing) | Frappe's OAuth provider registers no client for a guest on a TEX site: dynamic client registration is off at install and by p76 (ADR-073); TEX uses no Frappe OAuth client; an administrator may switch it on for a reviewed integration |
| A new upstream lint rule or an unpinned dependency changing CI overnight | Semgrep's rules and CLI, payments and frappe-bench pinned (`test_pins`); a Monday drift run scans with the newest rules (ADR-073) |
| Audit tampering | `TEX Audit Event` has no write/delete permission for any role; inserted only by server code |
| Embedding abuse (clickjacking) | Booking iframe allowed only for `allowed_embed_origins` via CSP `frame-ancestors` |
| Uploads | Checked on the server (ADR-046 and review): TEX branding images by their bytes (PNG/JPEG/GIF/WebP, every frame decoded, 2 MB) through `admin.upload_site_image`; the public folder serves only an allow-list (images, video, audio, PDF, office documents, fonts, zip) judged on the name File stores, on every path, before anything is written (File controller extension); everything else is private |
| Bearer tokens in URLs | Guest links carry tokens in the URL fragment (never sent to a server); token endpoints take POST bodies only; payment pages send no Referer (ADR-046); only token hashes are stored |
| PII over-exposure | `crm.view` / `guest.export` capabilities; a loyalty membership belongs to the hotel it was made at (Desk / REST by `property`, as a ledger entry), a sister hotel of a group program sees that the guest is a member and when they joined by month only (C-04, ADR-077); masked ID numbers (existing `_mask_id`); exports audited; a booking joins a guest profile by its e-mail, the phone only for a booking or profile without one, so one person's stays never land in another's profile (ADR-056 review); the phone only for staff and only when one profile has it; duplicates merged by staff who may edit every hotel's records of both, audited; an erasure leaves no contact data in cases, funnel, booker fields or history (ADR-056 second review) |
| Open redirect through payment return URLs | Browser-supplied return URLs accepted only for the TEX host or a DNS-verified booking domain (ADR-021) |
| Custom-domain takeover | `verified` set only by the DNS TXT check; editing a row resets it; a domain can belong to one site only |
| Group-level records edited from one hotel | Booking sites serving a hotel group need the capability at every hotel of the group |
| Marketing without consent (GDPR/KVKK) | Separate consent fields with timestamp/source/text version; transactional ≠ marketing; abandoned-booking contact only with the profile's own consent, and shown only while it holds, each contact with its channel's consent (the e-mail with e-mail consent, the phone with SMS or WhatsApp; C-03, ADR-076); an anonymous booking never grants consent on an existing profile, it is recorded as a request (ADR-046); a funnel event keeps an e-mail hash only with the visitor's marketing e-mail tick (its consent mark is any channel's tick, C-03) and never keeps contact fields (ADR-056, p37 purged older hashes); a browser's funnel event keeps an allow-list of fields per event; a withdrawal of e-mail consent, on every path, makes the guest's abandoned cases and funnel hashes anonymous (p40 for older rows), or, while SMS or WhatsApp consent holds, takes the e-mail and the hashes off and keeps the phone (C-03; a guest merge keeps what the merged consent allows); a consent flag is yes only for true / 1 / "1" / "true" (ADR-056 review); a withdrawal reads and writes only the rows it clears (indexes, primary keys) and a case written after it is anonymous; a consent change in Desk / REST is stamped and audited; a browser's funnel values must be the site's own hotels, room types, rate plans, boards and the session's quotes (ADR-056 second review) |
| Pricing internals and cross-tenant totals through Desk / REST | Permlevel 1 (System Manager only) on the snapshot, cost, margin, FX rate, quote result, revision snapshots and a guest's stored totals; masked in the change history; left out of a generic write's response; the TEX API serves them by capability and scope (ADR-056) |

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
- 2026-09-24 G-65 / G-81 / G-95 (ADR-056): another tenant's loyalty in the guest profile, stored
  cross-tenant totals served and used as a segment fact, funnel e-mail hashes without consent, and
  pricing internals readable through Desk / REST (reads, filters, the change history, a write's
  response) closed with regression tests in `test_crm_privacy`.
- 2026-09-25 independent review of ADR-056: no Critical, no money bug; 2 Medium (the program ledger
  showed a group's other hotels' entries and guests; a withdrawn consent left the case linked to the
  profile and its contact readable in Desk / REST) and 5 Low (a denylist funnel payload, consent
  text read as yes, customised permissions dropping System Manager's permlevel-1 row, masking that
  destroyed the history, `db_set` marking documents) fixed with fail-first tests (ADR-056 review
  follow-up, p40).
- 2026-09-25 second independent review of ADR-056: 1 High (a withdrawal's locking scan of the funnel,
  and deadlocks swallowed by tracking, so a rolled-back booking could be reported), 3 Medium (an
  erasure that kept consent and contact data; duplicates nothing could merge; the loyalty ledger in
  Desk / REST scoped by program) and 9 Low fixed with fail-first tests (ADR-056 second review
  follow-up, p45).
- 2026-09-25 third review of ADR-056 (the guest merge and the H1 fix): 1 High (the merge's stale
  snapshot: bookings committed during a merge left on a deleted profile, their hotel unchecked;
  concurrent redemptions spending the same points), 6 Medium (lock timeouts in best-effort steps
  failing bookings behind the funnel purge; comments and mail deleted with the duplicate; an erasure
  undone by a merge; a merge not reconstructible; the legacy endpoint's hotel check; p45 missing most
  earlier erasures) and 3 Low fixed with fail-first tests (ADR-056 third review follow-up, p48).

- 2026-10-03 C-04 web members (ADR-078): one-time e-mail links and device sessions designed against
  enumeration, link reuse, cross-site use and a member's price booked by another. Independent review
  round 1: 1 High (a 30-day session readable by other hotels' tag containers on the shared platform
  host: kept in the tab there, owner's decision), 7 Medium (display-name addresses, a link lost to a
  deadlock retry, typed names in mails, a group site's join with no hotel, a signed-in join without
  the link, …) and Low items fixed with fail-first tests; round 2: an accented look-alike domain matched
  an ASCII member's profile (refused now: ASCII addresses only) and apostrophes were refused (PR #34).

- 2026-10-04 batch 2O (ADR-079): a web rejoin staff may block; an erasure drops the member links mailed and not
  opened yet; staff see and end a guest's web sessions. Independent review round 1: 2 Medium (the erasure missed the
  links of a profile of no enterprise, which matches every enterprise's site: the pending links are the address's
  now; a staff-approved credit ordered by its request's creation in the overpaid check) and Low items fixed with
  fail-first tests (PR #35).

- 2026-10-04 batch 2P (ADR-080): a booking joins only the profile of its exact address (an accented look-alike
  joined another person's stays, points and member price check); a typed address must be one plain address (an
  invisible character made a look-alike profile); a refused reprice's audit event, which holds the payload digests,
  is served in Desk and REST to platform administrators only (§6L); a paid change's engine reasons stay with staff,
  never in the guest's error body. Independent review round 1: 1 High (CI's static guest-refusal check), 3 Low
  (the apps' address checks, a channel's display-name address, the call centre's booker and the CRM's profile
  address: one plain address, so `İNFO@…` typed with caps lock on a Turkish keyboard is refused, not a second
  profile) and NITs fixed with fail-first tests; round 2: 2 Low (the CRM drawer checks only an address typed now;
  the call centre's guest and booker checks) and NITs (Python's trim in the apps; a stored KELVIN SIGN address is
  never joined) (PR #36).

- 2026-10-04 batch 2Q (ADR-081): one plain address on every path that stores a profile's (the Desk form, REST and
  the legacy writers; the pre-arrival check-in no longer clears an address); staff block an ended membership's
  online rejoin (`crm.loyalty_block_rejoin`, `crm.edit` through the guest and at a hotel of the program, audited);
  a member link filed after an erasure by a request that read before it is dropped; sold-out names reach the guest
  in their language, never in the exception's params. Review rounds: see PR #37.

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
- ADR-056 leaves open: `TEX Contract Version` (frozen payload and rate tables, i.e. contract
  cost) is readable in Desk by the Hotel Admin role at its hotels whatever the granted profile
  (G-11 covered the TEX API; G-97: child tables, shared child DocTypes, child-row history and
  contract-edit audit diffs make it more than a permlevel change); no per-hotel legitimate-interest
  basis for abandoned-booking contact exists (owner/legal decision). (The group loyalty ledger in Desk
  is scoped by each entry's hotel since the ADR-056 second review.) Audit events are immutable:
  `guest.update` events keep the old and new values of a profile edit after an erasure (retention is
  an owner decision). A legacy PMS write of a record a merge moved (a Folio, a Security Deposit …),
  read before the merge and saved after it, puts the duplicate back into that link (the merge does not
  change `modified`; a Reservation's save and the TEX writers lock the profile and are refused).
- The legacy pre-arrival check-in (`public_api.precheckin_submit`, public, by the stay's 24-character token) is not
  fenced for TEX hotels: its token holder writes ID data and an address to the stay's profile with direct writes and
  no audit. Since 2Q it takes one plain address only and never clears one; whether TEX hotels use it (the legacy
  outreach sends its link only where a hotel turned it on) is the owner's, with D-15.
- iyzico / Sipay / NestPay adapters follow the public integration documents but are **not
  production-verified**; enabling a Production account requires the provider's sandbox
  certification with real merchant credentials.
- Legacy Kamra endpoints use `frappe.throw` text without `_()` in places (upstream style).
