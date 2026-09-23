# TEX Engine — Go-live readiness

**Verdict: NOT READY for production.** TEX Engine is not production-ready while any money,
security or distribution blocker remains (owner rule). Several remain (§2).

- As of: 2026-09-23, branch `claude/inspiring-ptolemy-i6wdu2`.
- Evidence comes from code, the local bench test runs and the gap register
  ([`FINAL_GAP_AUDIT.md`](FINAL_GAP_AUDIT.md)). Requirement status is in
  [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md).
- CI has never run on GitHub because the repository has no base branch. No area is READY
  without CI evidence.

**Statuses**
- **READY**: nothing known blocks launch; evidence is automated.
- **PARTIAL**: works and is tested, but known gaps remain (listed).
- **BLOCKED**: it cannot be finished inside the repository; owner input or infrastructure is
  needed.

## 1. Areas

| Area | Status | Evidence (code · tests) | Open items (gap ids) | Owner input | Exit criterion |
|---|---|---|---|---|---|
| Pricing | PARTIAL · **money blocker** | Pure Decimal engine `kamra/tex/pricing` (no frappe import, `TestPurity`); 239 unit tests; G-01…G-09, G-17, G-18, G-20, G-30, G-31 fixed with fail-first tests (G-30/G-31 closed: occupancy precedence v2, ADR-043, reviewed and the review's 8 findings fixed; `test_pricing_policies` 14) | G-56 promotion FX not recorded; G-72 Float money fields; G-84 min-basket per room; live versions published before ADR-043 keep the legacy occupancy ranking (their sold price) until republished: at deploy run `devtools/precedence_report` (bench execute, read-only) and republish the versions it lists under `precedence` / `rebuild`, revise those under `cannot_rebuild`, archive the second policy of each scope under `ambiguous_policy_scopes` | — | G-72 migrated to Currency |
| Contracts | PARTIAL | Immutable published versions with a verified payload hash (`TestContractImmutability`); selection (`TestContractSelection`); header lock and versioned selling terms, selection from the frozen version, audited status actions (G-50, ADR-045, `TestContractHeaderLock`); e2e `contract-admin`, `policy-revisions` | G-73 snapshot by reference; G-74 draft edits not audited (publish now records the selling terms) | — | G-74 audited |
| Inventory | PARTIAL | Row-locked inventory days (`TestConcurrentLastRoom`, `TestConcurrentRoomTypes`); extras capacity (G-19, `TestConcurrentLastExtra`); hold expiry (G-86) | G-49 legacy `validate_type_capacity` still applies to TEX oversell and pools (channel bookings excepted); G-41 no channel dimension on allotments; G-47, G-48 | — | G-49 fixed |
| Booking Engine | PARTIAL | `/book/<slug>` SPA, rate-limited public API, `test_public_booking` (17), e2e booking desktop + mobile, post-booking extras (G-22); a guest's change settles its money (G-45 fixed, ADR-044): paid before it applies, refunds and credit per the hotel's policy, staff decisions · `test_self_service_money` (19, fail-first), unit `test_settlement` | No money gap open. e2e `manage-money.spec.ts` written, not yet run against a bench serving this code; CI never ran | — | CI green including `manage-money.spec.ts` |
| Multi-room | PARTIAL | `TestMultiRoom`, `TestBookingLevelTerms`, unit `test_booking_level`, e2e two-room booking | G-84 can refuse a qualifying coupon (never grants one wrongly) | — | G-84 fixed |
| Payments | **BLOCKED** (certification) · code PARTIAL | Signed, fail-closed callbacks; write-only secrets; row-locked idempotent allocation (G-14); tokenless returns (G-10); payments hardening (ADR-041/042): uncertified providers gated in Production (new money vs settling), no `gateway_url` override in Production, no sandbox gateway on a live site, captured amount/currency checked, one charge per pay-link attempt, refunds take unallocated money first (G-67 code, G-68, G-89 fixed). Tests: `TestPaymentIntegrity`, `TestPaymentLinkTokens`, `TestConcurrentAllocation`, `TestGuestPayment`, payments go-live tests in `test_security_regressions` | iyzico, Sipay and NestPay are **uncertified** (live certification BLOCKED; Sipay refunds and its status answer unconfirmed); provider `api_key` encrypted and write-only (G-83, p22) | Merchant sandbox + production credentials (iyzico, Sipay, NestPay) and each provider's certification run | Providers certified; `production_verified=True` set only after certification |
| Channel distribution | **BLOCKED** (certification) · code PARTIAL | Provider-neutral layer (ADR-039): mappings, ARI computed from TEX and pushed as changes, signed idempotent inbound bookings applied in order, error queue, reconciliation, audit, sandbox adapter. `test_distribution` (17, every guard mutation-checked, per-connection send/apply included) | Staff UI done (Connect → Channels: mappings with close-out on switch-off, ARI preview, queue/send, inbound log with retry, reconciliation, sandbox; e2e `channels.spec.ts`); **no real provider adapter** (Channex, SiteMinder, RateGain, … all BLOCKED); `fetch_reservations` reconciliation needs a real provider | Channel-manager provider API credentials, commercial access, certification | A certified adapter for the chosen provider passes its certification and an end-to-end ARI + booking round trip |
| PMS integration | PARTIAL | Transactional outbox (claims, back-off, dead-letter; PMS connections only); `WebhookPMS` signed, never unsigned (no secret or no https: final refusal, audited; cannot be enabled without a secret, G-83); G-88 created-event fix | No inbound PMS → TEX events (check-in/out, no-show); `fetch_availability` unused; no vendor adapter; no dedicated outbox delivery test; delivery to an uncertified Production adapter is being refused (payments hardening, G-90) | PMS vendor and its API | Vendor adapter + tests; inbound status events |
| CRM | PARTIAL | Segments (G-23), loyalty administration (G-24), portfolio (G-25) backends with tests (`test_crm_segments`, `test_loyalty_admin`, `test_portfolio`) | Screens done (e2e `crm-admin.spec.ts`, `portfolio.spec.ts`); G-65 profile gaps; G-66 loyalty; G-81 e-mail hash stored without consent | — | UIs merged with e2e; G-81 fixed |
| Security | PARTIAL · **security blocker** | Capability + property scope on every TEX endpoint; immutable audit trail; secret redaction; semgrep ERROR-level; `test_security_regressions` (58); signatures keyed only by `encryption_key` (G-89 fixed); root `SECURITY.md` rewritten for TEX (guest surfaces, severity areas, no PAN/CVV); G-83 hygiene fixed (ADR-046: links checked, consent needs a proven owner, server-side upload checks and no public active content, tokens only in fragments/POST bodies, no unsigned PMS webhook) · `test_security_hygiene` (7) | `SECURITY.md` names no security contact yet; no dependency/secret scanning in CI; no external penetration test | Security contact; pentest | Security contact named in SECURITY.md; pentest done |
| Tenant isolation | PARTIAL | Enterprise → group → hotel grants; permission hooks on every scoped DocType (hooks ↔ perm sync test); legacy endpoint resolution (ADR-027); G-26 fixed (ADR-040). Tests: `TestTenantIsolation`, `TestRestBypass`, `TestLegacyTenancy`, `TestAdminDataTenancy`, distribution tenancy | No known open gap. Guest identity is shared inside an enterprise by design (ADR-040). Needs CI evidence and an external test | Pentest | CI green + pentest |
| Custom domain | PARTIAL · infra **BLOCKED** | DNS TXT verification, daily recheck, host → site mapping, pinned public API, guest links on the hotel's host (ADR-035, `test_custom_domains` 9) | Engine served on the hotel's host (pinned SPA, e2e `custom-host.spec.ts`); only operations remain | Per host: `bench setup add-domain <host>`, regenerate nginx, one TLS certificate per host; production `host_name` in `site_config.json` | A verified host serves its engine over TLS on the production site |
| Email | **BLOCKED** (SMTP) · code PARTIAL | Transactional mail in 6 languages through the e-mail queue (`TestNotifications`, `TestSecretsNeverLogged`) | No SMTP account; TEX Communication stays "Queued" (delivery status never synced); "resend" reports queued as sent; no per-hotel sender/reply-to; SPF/DKIM | SMTP account, sender domain, SPF/DKIM records | Mail delivered on the production site; status synced |
| Monitoring | PARTIAL | Audit trail UI, outbox monitor, per-connection last status/error, TEX jobs logged to Error Log without frame locals | No TEX system-status endpoint; `kamra/health.py` is upstream-only (checks Kamra-PMS releases, refused to hotel users while the PMS is off); no alerting on Dead jobs, stale FX, mail errors or failed callbacks; no uptime/APM/log shipping | Monitoring stack (uptime, logs, alerts) | TEX status checks + alerts wired |
| Backups | **BLOCKED** | — (only upstream docs mention `bench backup`) | No schedule, off-site copy, encryption, retention or restore rehearsal. `encryption_key` (site_config) must be kept with the backups: without it every Password field (payment and integration secrets) is lost | Backup storage, retention, RPO/RTO | Nightly encrypted off-site backups + a restore rehearsal within 30 days |
| CI/CD | **BLOCKED** (owner: Actions minutes, registry) · code PARTIAL | `ci.yml`: ruff, frontend build + i18n parity, upstream suites, TEX unit tests and every integration module (discovered), Playwright (MariaDB 11.8); `workflow_dispatch` runs it on any branch; upstream release pipelines guarded to the upstream repository (G-61 fixed) | Never run on GitHub yet (dispatch it once from the Actions tab); no pip/npm audit or secret scanning; no TEX image, registry, staging or deploy pipeline | A base branch or a dispatched run; container registry; TEX release identity | CI green on GitHub for the release commit; a TEX image built and deployed to staging |
| Production secrets | PARTIAL | Payment and integration secrets are Password fields, never returned; channel `api_key` encrypted (p18); payment provider `api_key` encrypted (G-83, p22); secret-like settings refused; redaction in audit and error logs; only token hashes stored | no rotation runbook; demo password in CI/dev docs (test only) | Secret store / rotation policy | Rotation runbook; production posture check |
| Data migration | PARTIAL | Patches p01–p18 listed and idempotent; tested: p05, p06, p10, p12, p15, p16, p17, p21 (G-50), p22 (G-83) | Untested: p01–p04, p07–p09, p11, p13, p14, p18 (G-76); no end-to-end upgrade test; no TEX-native importer for future bookings/guests/contracts (the legacy CSV importer writes plain Reservations); `MIGRATION_PLAN.md` patch table is stale | Source data and a cut-over date | Upgrade test from a Kamra-shaped DB; importer for open bookings |
| Rollback plan | **BLOCKED** | Commercial rollback exists (new draft from an older version + publish; policy revise/activate/archive) | Patches are forward-only (p07, p10 scrub data; p04, p12, p15, p18 transform rows); `deploy/install.sh` migrates without a backup first; TEX has no release identity (still Kamra 2.6.2) | Staging environment | Rollback rehearsed once on staging (maintenance mode → restore pre-migrate backup → previous commit → build/restart) |

## 2. Launch blockers

- **Money**:
  - ~~G-30 and G-31 (pricing precedence)~~ fixed (ADR-043); at deploy, run `precedence_report` and archive any second live or scheduled pricing policy of a scope; revise any version it lists under `cannot_rebuild` (a republish would be refused, e.g. by a pricing-policy row activated before the policy checks);
  - ~~G-45 (guest change collects nothing)~~ fixed (ADR-044); its e2e `manage-money.spec.ts` must pass;
  - ~~G-50 (contract header editable after publish)~~ fixed (ADR-045); its e2e step in `contract-admin.spec.ts` must pass;
  - payment provider certification.
- **Security**:
  - ~~G-83 hygiene and the payment `api_key` field~~ fixed (ADR-046);
  - a security contact in SECURITY.md;
  - no CI run and no external test yet.
- **Distribution**: channel-manager provider certification (the TEX layer and sandbox exist).
- **Operations**:
  - backups and a restore rehearsal;
  - a rollback rehearsal;
  - CI/CD on GitHub (base branch);
  - an SMTP account;
  - monitoring and alerts;
  - TLS and add-domain for each custom host.

## 3. Owner inputs needed

1. Payment merchant credentials (iyzico, Sipay, NestPay: sandbox and production) and the
   certification run with each provider.
2. Channel-manager provider: choice, API credentials, commercial access, certification.
3. SMTP account, sender domain and SPF/DKIM records.
4. Hosting:
   - production site and `host_name`;
   - backup storage, retention and RPO/RTO;
   - a staging environment;
   - TLS and `add-domain` per custom booking host.
5. GitHub: a base branch (`main`) and Actions enabled, so CI can run and a PR can be opened.
6. A container registry and a TEX release identity (G-61).
7. A security contact for `SECURITY.md`, and an external penetration test.
8. Consent (ADR-046): whether returning guests who tick marketing consent online should get a
   double opt-in e-mail (needs item 3), or stay "requested, not applied" until staff confirm.

## 4. Platform notes

- **Database**: MariaDB 10.11+ works (dev bench). CI uses 11.8.
  - From 11.6, `innodb_snapshot_isolation` reports changed-row conflicts as deadlocks.
    TEX's booking and modification endpoints retry them (ADR-032).
  - No query needs `SKIP LOCKED`: queue claims are conditional `UPDATE … LIMIT` with a
    token and lease, and inbound messages are row-locked with a status re-check.
- **Scheduler** must be enabled in production. TEX jobs run every minute (channel
  distribution), every 5 and 15 minutes (outbox, holds, links, contract status,
  abandonment), and daily (FX, DNS recheck, channel resync, loyalty maturation).
- **`encryption_key`** in `site_config.json` signs offers, payment callbacks and webhooks,
  and decrypts every Password field. Back it up separately from the database and never
  rotate it without a re-encryption plan.

## 5. Go-live gates

- [ ] CI green on GitHub for the release commit.
- [ ] No open Critical or High money, security or distribution gap.
- [ ] Payment provider(s) certified; only certified providers enabled in Production.
- [ ] Channel-manager provider certified, or the launch hotels do not need OTA connectivity.
- [ ] SMTP delivering; delivery status visible to staff.
- [ ] Backup + restore rehearsal within the last 30 days; `encryption_key` escrowed.
- [ ] Rollback rehearsed once on staging.
- [ ] Monitoring and alerts live (uptime, TEX jobs, Dead queues, callbacks, mail).
- [ ] Custom-domain TLS live for each hotel that uses one.
- [x] SECURITY.md rewritten for TEX (2026-09-23).
- [ ] Security contact named in SECURITY.md; external penetration test done.

## 6. Change log

- 2026-09-23: first version. G-69 (distribution layer) and G-26 (tenant structure) are
  closed in code; payments hardening and the CRM, domain and channel screens are in progress.
- 2026-09-23: CRM (segments, loyalty), portfolio, custom-domain and channel screens merged with e2e; a disabled channel mapping sends a close-out before it can be deleted.
- 2026-09-23: payments hardening merged (G-67 code, G-68, G-89, G-90); root `SECURITY.md` rewritten for TEX (contact still an owner input); CI runs on demand (G-61). Open money/security work: G-30/G-31, G-45, G-50, G-83.
- 2026-09-23: occupancy precedence v2 merged (G-30, G-31 closed; ADR-043, reviewed, 8 findings fixed). Live contract versions keep their sold (legacy) occupancy ranking until republished; `precedence_report` lists the ones to republish at deploy. Open money/security work: G-45, G-50, G-83.
- 2026-09-23: G-50 closed in code (ADR-045): a published contract's hotel, market, currency and pricing basis are fixed; sale and stay windows, channels, priority and sell currency change only with a new version; selection reads the frozen version, not the header; the status moves only through audited actions (suspend, resume, archive, restore). Contracts stay PARTIAL (G-73, G-74). Verdict unchanged: NOT READY.
- 2026-09-23: G-83 security hygiene fixed (ADR-046): CRM communication links, consent on a known profile from an anonymous booking, server-side upload checks and a public-file guard, payment-link tokens in the URL fragment with no Referer from payment pages, no unsigned PMS webhook, payment `api_key` encrypted (p22). Owner decisions left: double opt-in e-mail (needs SMTP); old payment links keep their token in the path until they expire. Security stays a blocker (G-89, SECURITY.md, CI, pentest). Not production-ready.
