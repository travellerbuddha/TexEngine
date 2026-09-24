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
| Pricing | PARTIAL · **money blocker** | Pure Decimal engine `kamra/tex/pricing` (no frappe import, `TestPurity`); 315 unit tests; G-01…G-09, G-17, G-18, G-20, G-30, G-31, G-52, G-56 fixed with fail-first tests (G-30/G-31 closed: occupancy precedence v2, ADR-043, reviewed and the review's 8 findings fixed; `test_pricing_policies` 14; G-56/G-52, ADR-051: every FX rate a price used is in the price-locked snapshot and ORIGINAL_* reprices reuse it, `test_fx_snapshot` 4; age-band gaps refused at publish in months and a child's date of birth accepted and checked, `test_age_bands` 6); G-92 fixed (ADR-052): a TEX hotel's reservation is created only by TEX (booking service, channel sale) or a migration import recorded as "Imported" at its Decimal amount, the legacy auto-price never prices a TEX hotel, and a stay there changes its stay or price only through TEX (`test_legacy_pricing` 15); its review follow-up (ADR-052 review): import amounts are read strictly (never guessed), shown before import and correctable with `price.override`, the legacy check-out bills a locked stay from its locked amount or its TEX booking (G-96), and a hotel joining TEX sells at the Desk until an administrator sets it live (`test_legacy_pricing_review` 23, unit `test_import_amounts` 14); G-51 (ADR-054): modifications and the historical simulator are deterministic (a past sale time selects the contracts Active then and the simulator counts the coupon uses held then), a sale time is used or refused (`test_modification_determinism` 24); G-72 fixed (ADR-055): commercial decimal fields keep 9 places and hold exactly what was typed (more is refused), loaders read the exact Decimal (`money.db_dec`), FX rates keep 10 significant digits (`test_money_fields`) | a snapshot keeps the Decimal rate it used); G-84 min-basket per room; live versions published before ADR-043 keep the legacy occupancy ranking (their sold price) until republished: at deploy run `devtools/precedence_report` (bench execute, read-only) and republish the versions it lists under `precedence` / `rebuild`, revise those under `cannot_rebuild`, archive the second policy of each scope under `ambiguous_policy_scopes` | — | G-72 migrated to Currency |
| Contracts | PARTIAL | Immutable published versions with a verified payload hash (`TestContractImmutability`); selection (`TestContractSelection`); header lock and versioned selling terms, selection from the frozen version, audited status actions, header narrowings made before the upgrade kept and reported (p25), a suspend stops quotes and bookings in flight (G-50, ADR-045, `TestContractHeaderLock`, `TestContractHeaderLockReview`); selection for a past sale time reads the audited status of then, so an archived contract still reprices and simulates the stays it sold (G-51, ADR-054); every saved draft edit (any path) and every publish audited as a compact diff, a publish against the version it replaces (G-74, ADR-053, `TestContractAudit`); e2e `contract-admin`, `policy-revisions` | G-73 snapshot by reference | — | G-73 fixed |
| Inventory | PARTIAL | Row-locked inventory days (`TestConcurrentLastRoom`, `TestConcurrentRoomTypes`); at a TEX hotel TEX inventory is the only capacity rule: oversell, pools and configured inventory sold by TEX are kept, and every reservation written outside TEX (migration imports, status moves; a Desk/REST insert at a hotel live in TEX is refused, ADR-052) takes the TEX lock and is checked against TEX inventory; a change is checked only on the nights it newly takes; a reservation books only its own hotel's room types (G-49 fixed and reviewed, ADR-048; `test_inventory` 31, `TestConcurrentDeskAndTexBooking`); allotment release and cutoff are separate, a cutoff gives the rooms back, channels hear both at the site's midnight (p27); extras capacity (G-19, `TestConcurrentLastExtra`); hold expiry (G-86) | G-41 remainder: one multi-channel contract's allotment cannot be split by channel (a contract per channel or channel-scoped restrictions instead; deferred, ADR-050); G-47, G-48; pools and configured inventory are set only in Desk | — | G-48 fixed; the allotment channel split decided |
| Booking Engine | PARTIAL | `/book/<slug>` SPA, rate-limited public API, `test_public_booking` (17), e2e booking desktop + mobile, post-booking extras (G-22); a guest's change settles its money (G-45 fixed, ADR-044, adversarial review fixed: no refund past a rate's terms, durable refunds that are never repeated after a gateway timeout, refunds capped by what is still over, the change applied by a job after the payment, money for staff explicit; second review fixed: refund runs one at a time and never around their own refund in flight, every unconfirmed refund can be closed from the payment screen and is flagged in the system status, nothing of a refund is dropped after an unanswered one, a paid change not yet applied is set aside, an arrival moved later inside a penalty window goes to the hotel, transient errors retried, lost jobs swept, channel changes in the same lock order; third review fixed: an outcome is recorded only once the refund's answer cannot come and is never overwritten by a late answer (a contradicting answer is an audited, alerted conflict that stops the change's refunds), a run keeps its hold and counts the refunds it made, money refunded outside TEX recorded, G-93; fourth review fixed: money handed back recorded against its own payments on any booking, limits read with locking reads, money being refunded never moves, a conflict stops every run until staff record the gateway's actual outcome) · `test_self_service_money` (75, fail-first), `test_distribution` (+2), unit `test_settlement`, `test_system_checks` | No money gap open. e2e `manage-money.spec.ts` (3) passed on the bench (with an RQ worker) before the second review; extended since, to be re-run; CI never ran | — | CI green including `manage-money.spec.ts` |
| Multi-room | PARTIAL | `TestMultiRoom`, `TestBookingLevelTerms`, unit `test_booking_level`, e2e two-room booking | G-84 can refuse a qualifying coupon (never grants one wrongly) | — | G-84 fixed |
| Payments | **BLOCKED** (certification) · code PARTIAL | Signed, fail-closed callbacks; write-only secrets; row-locked idempotent allocation (G-14); tokenless returns (G-10); payments hardening (ADR-041/042): uncertified providers gated in Production (new money vs settling), no `gateway_url` override in Production, no sandbox gateway on a live site, captured amount/currency checked, one charge per pay-link attempt, refunds take unallocated money first (G-67 code, G-68, G-89 fixed). Tests: `TestPaymentIntegrity`, `TestPaymentLinkTokens`, `TestConcurrentAllocation`, `TestGuestPayment`, payments go-live tests in `test_security_regressions` | iyzico, Sipay and NestPay are **uncertified** (live certification BLOCKED; Sipay refunds and its status answer unconfirmed); provider `api_key` encrypted and write-only (G-83, p22) | Merchant sandbox + production credentials (iyzico, Sipay, NestPay) and each provider's certification run | Providers certified; `production_verified=True` set only after certification |
| Channel distribution | **BLOCKED** (certification) · code PARTIAL | Provider-neutral layer (ADR-039): mappings, ARI computed from TEX and pushed as changes, signed idempotent inbound bookings applied in order, error queue, reconciliation, audit, sandbox adapter. `test_distribution` (17, every guard mutation-checked, per-connection send/apply included) | Staff UI done (Connect → Channels: mappings with close-out on switch-off, ARI preview, queue/send, inbound log with retry, reconciliation, sandbox; e2e `channels.spec.ts`); **no real provider adapter** (Channex, SiteMinder, RateGain, … all BLOCKED); `fetch_reservations` reconciliation needs a real provider | Channel-manager provider API credentials, commercial access, certification | A certified adapter for the chosen provider passes its certification and an end-to-end ARI + booking round trip |
| PMS integration | PARTIAL | Transactional outbox (claims, back-off, dead-letter; PMS connections only); `WebhookPMS` signed, never unsigned (no secret or no https: final refusal, audited; cannot be enabled without a secret, G-83); G-88 created-event fix | No inbound PMS → TEX events (check-in/out, no-show); `fetch_availability` unused; no vendor adapter; no dedicated outbox delivery test; delivery to an uncertified Production adapter is being refused (payments hardening, G-90) | PMS vendor and its API | Vendor adapter + tests; inbound status events |
| CRM | PARTIAL | Segments (G-23), loyalty administration (G-24), portfolio (G-25) backends with tests (`test_crm_segments`, `test_loyalty_admin`, `test_portfolio`) | Screens done (e2e `crm-admin.spec.ts`, `portfolio.spec.ts`); G-65 profile gaps; G-66 loyalty; G-81 e-mail hash stored without consent | — | UIs merged with e2e; G-81 fixed |
| Security | PARTIAL · **security blocker** | Capability + property scope on every TEX endpoint; immutable audit trail: draft and publish diffs, ARI bulk edits with each cell's old value, payment rules audited on every save path with secrets only as set / changed, group and enterprise events seen at the hotels they reached (never another hotel's), each payment outcome's real source (G-74, ADR-053, `test_audit_trail` 15); secret redaction; semgrep ERROR-level; `test_security_regressions` (58); signatures keyed only by `encryption_key` (G-89 fixed); root `SECURITY.md` rewritten for TEX (guest surfaces, severity areas, no PAN/CVV); G-83 hygiene fixed and reviewed (ADR-046 and its review follow-up: links checked, consent needs a proven owner with `crm.edit`, server-side upload checks, the public folder serves an allow-list judged on the stored name, images decoded whole, tokens only in fragments/POST bodies, no unsigned PMS webhook, p24 cleans existing files and versioned keys) · `test_security_hygiene` (14), e2e `pay-link.spec.ts` (2, passes); sales-channel binding (G-41, ADR-050): staff price and book only on their profiles' channels at each hotel (`price.any_channel` for every channel), checked on every CRS pricing and booking endpoint from the offer's or quote's own channel, granted only by someone who sells on it; review follow-up: booking sites sell only on a web channel (staff bookings there flagged), pricing and booking channels come only from the profiles that may price or book, product changes need the reservation's channel · `test_channel_binding` (26), e2e `crs-actions.spec.ts` (3) | `SECURITY.md` names no security contact yet; no dependency/secret scanning in CI; no external penetration test; production nginx must not add its own Referrer-Policy on payment pages (§4); p24 lists public SVG/XML files and site images for the owner to replace | Security contact; pentest | Security contact named in SECURITY.md; pentest done |
| Tenant isolation | PARTIAL | Enterprise → group → hotel grants; permission hooks on every scoped DocType (hooks ↔ perm sync test); legacy endpoint resolution (ADR-027); G-26 fixed (ADR-040); G-94 fixed (ADR-050 review): live grants are the only authority (an ended grant grants nothing, its mirrored User Permissions go at the site's midnight, audited), and the 53 legacy hotel-bound DocTypes follow the TEX scope in Desk/REST. Tests: `TestTenantIsolation`, `TestRestBypass`, `TestLegacyTenancy`, `TestAdminDataTenancy`, distribution tenancy, `test_grant_expiry` (9) | No known open gap. Guest identity is shared inside an enterprise by design (ADR-040). Needs CI evidence and an external test | Pentest | CI green + pentest |
| Custom domain | PARTIAL · infra **BLOCKED** | DNS TXT verification, daily recheck, host → site mapping, pinned public API, guest links on the hotel's host (ADR-035, `test_custom_domains` 9) | Engine served on the hotel's host (pinned SPA, e2e `custom-host.spec.ts`); only operations remain | Per host: `bench setup add-domain <host>`, regenerate nginx, one TLS certificate per host; production `host_name` in `site_config.json` | A verified host serves its engine over TLS on the production site |
| Email | **BLOCKED** (SMTP) · code PARTIAL | Transactional mail in 6 languages through the e-mail queue (`TestNotifications`, `TestSecretsNeverLogged`). Delivery status synced every 5 min from Frappe's queue: each TEX Communication keeps its queue entry and becomes Sent or Failed with a short reason; a mail the queue refused is recorded as Failed; "resend" and the payment-link dialogs say "queued"; guest mail goes out in the hotel's name with the hotel's Reply-To, always from the site's own account (ADR-047). Tests: `test_system_status.TestMailDeliveryStatus` (3) | No SMTP account; SPF/DKIM; "Sent" means accepted by the mail server (bounces after that are not tracked); a per-hotel sending domain is not built | SMTP account, sender domain, SPF/DKIM records | Mail delivered on the production site; status synced (done in code) |
| Monitoring | PARTIAL | TEX system status (ADR-047): `kamra.tex.api.system.status` (`system.monitor`, hotel-scoped; platform checks for platform administrators) covers the scheduler and TEX job freshness, TEX job errors, workers and backlog, `encryption_key`, Dead/late PMS, ARI and inbound queues, connection errors, pending card charges, rejected callbacks and capture mismatches, FX staleness, the outgoing account and e-mail delivery. Guest liveness probe `kamra.tex.api.system.ping` (booleans only, HTTP 503 when down). Alerts every 15 min, once per worsening and once per recovery, to TEX Settings recipients, plus an Error Log entry and an audit event. UI: Settings → System status. Tests: `test_system_status` (12), unit `test_system_checks` (17); e2e `system-status.spec.ts` (4, passes) | No uptime monitor, APM or log shipping yet (owner infrastructure); alert e-mails need SMTP (until then: Error Log + audit trail + status page); `kamra/health.py` stays upstream-only | Uptime monitor on the ping; alert recipients; log shipping/APM | Uptime monitor polling the ping on the production site; a test alert received by the recipients |
| Backups | **BLOCKED** | — (only upstream docs mention `bench backup`) | No schedule, off-site copy, encryption, retention or restore rehearsal. `encryption_key` (site_config) must be kept with the backups: without it every Password field (payment and integration secrets) is lost | Backup storage, retention, RPO/RTO | Nightly encrypted off-site backups + a restore rehearsal within 30 days |
| CI/CD | **BLOCKED** (owner: Actions minutes, registry) · code PARTIAL | `ci.yml`: ruff, frontend build + i18n parity, upstream suites, TEX unit tests and every integration module (discovered), Playwright (MariaDB 11.8); `workflow_dispatch` runs it on any branch; upstream release pipelines guarded to the upstream repository (G-61 fixed) | Never run on GitHub yet (dispatch it once from the Actions tab); no pip/npm audit or secret scanning; no TEX image, registry, staging or deploy pipeline | A base branch or a dispatched run; container registry; TEX release identity | CI green on GitHub for the release commit; a TEX image built and deployed to staging |
| Production secrets | PARTIAL | Payment and integration secrets are Password fields, never returned; channel `api_key` encrypted (p18); payment provider `api_key` encrypted (G-83, p22); secret-like settings refused; redaction in audit and error logs; only token hashes stored | no rotation runbook; demo password in CI/dev docs (test only) | Secret store / rotation policy | Rotation runbook; production posture check |
| Data migration | PARTIAL | Patches p01–p18 listed and idempotent; tested: p05, p06, p10, p12, p15, p16, p17, p21 and p25 (G-50, both re-runnable), p35 (G-72, re-runnable; checks only), p22 and p24 (G-83), p27 (G-49, re-runnable) | Untested: p01–p04, p07–p09, p11, p13, p14, p18 (G-76); no end-to-end upgrade test; no TEX-native importer for future bookings/guests/contracts (the legacy importers write Reservations; at a TEX hotel each is recorded as "Imported" at the file's Decimal amount in the currency the import names, price-locked and audited, and needs `price.override`: ADR-052; amounts are read strictly with an optional decimal mark, previewed per row, each row all or nothing, and an imported amount is corrected with `price.override`: ADR-052 review; format in `MIGRATION_PLAN.md` §5); `MIGRATION_PLAN.md` patch table is stale | Source data and a cut-over date | Upgrade test from a Kamra-shaped DB; importer for open bookings |
| Rollback plan | **BLOCKED** | Commercial rollback exists (new draft from an older version + publish; policy revise/activate/archive) | Patches are forward-only (p07, p10 scrub data; p04, p12, p15, p18 transform rows); `deploy/install.sh` migrates without a backup first; TEX has no release identity (still Kamra 2.6.2) | Staging environment | Rollback rehearsed once on staging (maintenance mode → restore pre-migrate backup → previous commit → build/restart) |

## 2. Launch blockers

- **Money**:
  - ~~G-30 and G-31 (pricing precedence)~~ fixed (ADR-043); at deploy, run `precedence_report` and archive any second live or scheduled pricing policy of a scope; revise any version it lists under `cannot_rebuild` (a republish would be refused, e.g. by a pricing-policy row activated before the policy checks);
  - ~~G-45 (guest change money)~~ fixed and reviewed four times (ADR-044; the fourth review's High in the G-93 path, 3 Medium and 3 Low fixed too); the third review's High (an outcome recorded while the gateway call runs), its Medium and 3 Low are fixed, and G-93 with them; its e2e `manage-money.spec.ts` must pass again;
  - ~~G-50 (contract header editable after publish)~~ fixed (ADR-045); its e2e step in `contract-admin.spec.ts` must pass;
  - ~~G-92 (a Desk/REST reservation at a TEX hotel is priced by the legacy engine, not TEX)~~ fixed (ADR-052): refused at a TEX hotel; migration imports keep their own amount as "Imported";
  - ~~G-92 review (2026-09-24): migration amounts in European/Turkish formats are parsed silently wrong and then price-locked (High); legacy check-out bills TEX-sold and Imported stays at the legacy room rate (G-96, High, pre-existing)~~ fixed (ADR-052 review section, branch `fix-g92`);
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
  - an uptime monitor on the TEX ping, alert recipients and log shipping (the status checks and
    alerts exist, ADR-047);
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
9. Monitoring: an uptime monitor for the ping, the alert recipients (TEX settings →
   Monitoring), and a log-shipping/APM stack.
10. Legacy stays at a hotel that joins TEX (ADR-052 and its review): a stay the legacy engine
    sold before the hotel went live in TEX, or an imported one, cannot change its dates or room type
    outside TEX, and the TEX modification service needs a TEX price snapshot. So staff cancel it and
    rebook it in TEX, or, for a guest in house, book the extra nights as a new TEX reservation (the
    current default; an imported amount can be corrected with `price.override`). Confirm this, or
    ask for a "take over into TEX" action. That action needs a market, channel, contract version,
    board and rate plan chosen per stay, and every later change would be re-priced against that
    contract. The go-live moment itself is now explicit: an administrator sets each hotel live in TEX
    (the Desk sells it until then; existing TEX hotels were set live by p36). Decide when each
    joining hotel goes live.
11. Booking sites stored on a non-web channel (ADR-050 review) sell nothing until the owner sets a
    web channel or disables them; p31 lists them at deploy.

## 4. Platform notes

- **Database**: MariaDB 10.11+ works (dev bench). CI uses 11.8.
  - From 11.6, `innodb_snapshot_isolation` reports changed-row conflicts as deadlocks.
    TEX's booking and modification endpoints retry them (ADR-032).
  - No query needs `SKIP LOCKED`: queue claims are conditional `UPDATE … LIMIT` with a
    token and lease, and inbound messages are row-locked with a status re-check.
- **Scheduler** must be enabled in production. TEX jobs run every minute (channel
  distribution), every 5 minutes (outbox, holds, links, e-mail delivery status), every 15
  minutes (contract status, abandonment, system-status alerts), and daily (FX, DNS recheck,
  channel resync, loyalty maturation).
- **Monitoring** (ADR-047).
  - Point an uptime monitor at `https://<site>/api/method/kamra.tex.api.system.ping` (GET, no
    login). Expect HTTP 200 with `"ok":true` in the body. HTTP 503, or any other answer, means
    the site cannot serve: its database or cache is down.
  - A second keyword check on `"scheduler":true` catches a stopped scheduler: it turns false
    when the every-minute TEX job has not run for 10 minutes.
  - The probe answers booleans only. It is rate limited to 30 requests per minute per IP
    (`tex_ping_limit` in site_config raises it), so poll once a minute.
  - Staff see the checks in TEX → Settings → System status (`system.monitor`; platform checks
    only for platform administrators).
  - Alerts go to TEX settings → Monitoring → recipients, every 15 minutes and only on a change.
    They need SMTP. Without it, each change is in the Error Log (`TEX status alert: …`) and in
    the audit trail (`system.status_changed`).
- **`encryption_key`** in `site_config.json` signs offers, payment callbacks and webhooks,
  and decrypts every Password field. Back it up separately from the database and never
  rotate it without a re-encryption plan.
- **nginx and payment pages** (ADR-046, G-83 review). TEX answers `/book/pay…` (and `/pay…` on a
  hotel's own host) with `Referrer-Policy: no-referrer`, so an old payment link's token never
  leaves in a Referer. bench's nginx template adds `Referrer-Policy "same-origin,
  strict-origin-when-cross-origin"` at server level, which nginx also adds to proxied
  responses; browsers then use the last valid value. The page's own `<meta name="referrer">`
  still wins, but production should not weaken the header. In the site's server block, before
  `location /`, add (a location with its own `add_header` inherits none from the server, so the
  other security headers are repeated; the upstream name is bench's `<bench>-frappe`):

  ```nginx
  # TEX payment pages: keep the app's Referrer-Policy (no-referrer); no server-level policy here
  location ~ ^/(book/)?pay(/|$) {
      add_header X-Frame-Options "SAMEORIGIN";
      add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload";
      add_header X-Content-Type-Options nosniff;
      proxy_http_version 1.1;
      proxy_set_header X-Forwarded-For $remote_addr;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_set_header X-Frappe-Site-Name <site>;
      proxy_set_header Host $host;
      proxy_set_header X-Use-X-Accel-Redirect True;
      proxy_read_timeout 120;
      proxy_redirect off;
      proxy_pass http://<bench>-frappe;
  }
  ```

  Manage pages carry their token only in the fragment, so the server-level policy is harmless
  there. Also keep the template's `location ~* ^/files/.*.(htm|html|svg|xml)` download rule;
  TEX's File guard is what keeps such files out of the public folder in the first place
  (bench serve, used by `deploy/tex-local`, forces no download at all).

## 5. Go-live gates

- [ ] CI green on GitHub for the release commit.
- [ ] No open Critical or High money, security or distribution gap.
- [ ] Payment provider(s) certified; only certified providers enabled in Production.
- [ ] Channel-manager provider certified, or the launch hotels do not need OTA connectivity.
- [ ] SMTP delivering; delivery status visible to staff. The delivery status is synced and
      shown (ADR-047); SMTP remains.
- [ ] Backup + restore rehearsal within the last 30 days; `encryption_key` escrowed.
- [ ] Rollback rehearsed once on staging.
- [ ] Monitoring and alerts live (uptime, TEX jobs, Dead queues, callbacks, mail). The checks
      and alerts exist (ADR-047); an uptime monitor on the ping and SMTP for the alerts remain.
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
- 2026-09-23: operations (ADR-047): TEX system status (hotel-scoped checks, platform checks for
  platform administrators), a guest liveness ping for uptime monitors, alerts on a change every
  15 minutes, Settings → System status; guest e-mail delivery status synced from the e-mail
  queue, "resend" says queued, guest mail in the hotel's name with its Reply-To. Monitoring
  stays PARTIAL (uptime monitor and log shipping are owner infrastructure); Email stays BLOCKED
  on SMTP.
- 2026-09-23: G-45 adversarial review fixed (ADR-044 review follow-up): a shortened stay on a non-refundable rate or inside the cancellation-penalty window waits for the hotel; guests change only confirmed rooms before arrival; refunds are on record before the gateway call and a timeout never refunds twice (staff verify, system status `refund_unknown`); refunds are capped by what is still over; the payment callback only records the charge and a job applies the change (one lock order); money for staff is explicit on the request. Booking Engine stays PARTIAL until CI and `manage-money.spec.ts` run. Not production-ready.
- 2026-09-23: G-83 adversarial review fixed (ADR-046 review follow-up): the public-file guard judges the stored name against an allow-list (images, video, audio, PDF, office documents, fonts, zip) before anything is written; private-by-URL files accepted; inline public SVG refused with a reason; images decoded whole (MPO accepted); site images limited to /files/ images or https on other hosts, judged only when changed; staff consent needs `crm.edit`; the consent history stays in the viewer's hotels; p24 privatises public HTML/script, reports other public active content and invalid site images, masks API keys in the change history; nginx note for payment pages. Not production-ready.
- 2026-09-24: G-50 review follow-up (ADR-045 amended): versions frozen before G-50 keep the header narrowings staff made after publishing (p25 snapshots them and reports every contract whose header differs from its live payload, `contract.header_differs`); a suspend stops quotes and bookings already in flight; the version scheduler isolates each record. At deploy, review the p25 report and publish corrective versions where a difference was not meant to narrow sales. Contracts stay PARTIAL (G-73, G-74). Verdict unchanged: NOT READY.
- 2026-09-24: G-45, G-50 and G-83 review follow-ups and TEX operations integrated and verified together: 18 integration modules (305 tests), 281 unit tests, the upstream suites (76/76, 13/13, banquet 101) and 34 browser tests (incl. manage-money, pay-link, system-status and the G-50 contract step) pass. Verdict unchanged: NOT READY (provider certifications, SMTP, backups, CI run, security contact and pentest remain).
- 2026-09-24: a second review of the G-45 fixes found 2 High (F1: an in-flight refund is not seen by a retried or overlapping settle, so money can be refunded twice; F2: staff refunds left UNKNOWN or stuck Pending cannot be closed) and 6 Medium/Low (F3–F8). Booking Engine is a money blocker again until they are fixed.
- 2026-09-24: G-91 closed in code: staff date defaults (inventory grids, CRS arrival, FX rate date, transactions, reports, dashboards, contract preview, access grants, channel sandbox, segment export) start on the site's day from `session.bootstrap` (`server.today`), not the browser's, and follow the site's midnight; transactions filter on either date bound alone. No area status changes. Verdict unchanged: NOT READY.
- 2026-09-24: G-49 fixed (ADR-048): at a TEX hotel the legacy room-type capacity check no longer
  refuses TEX's oversell, pools or configured inventory; reservations written outside TEX (Desk,
  REST, imports) take TEX's inventory lock and are refused when TEX has no room (closures, manual
  adjustments, withheld allotments apply); hotels outside TEX keep the legacy check. Allotments
  have a cutoff separate from their release (p27; Rates → Allotments). Inventory stays PARTIAL
  (G-41, G-47, G-48). Not production-ready.
- 2026-09-24: G-49 review follow-up (ADR-048 amended): a change is checked only on the nights
  it newly takes (a cutoff, closure or full house on held nights no longer refuses leaving early,
  a same-pool room type or an extension, for staff, guests and desk); a cutoff also gives the
  rooms back; a reservation books only its own hotel's room types; desk writes that meet a
  deadlock are told to try again, imports stop, channel bookings lock every night first;
  channels hear releases and cutoffs at the site's midnight. New money blocker G-92: a
  Desk/REST reservation at a TEX hotel is still priced by the legacy engine. Not production-ready.
- 2026-09-24: G-45 second review fixed (ADR-044 second review section, branch `fix2-g45`): a guest change's refund run holds its refunds one at a time and never plans around its own refund in flight (a stuck or unanswered one goes to staff to verify); staff record any unconfirmed refund's outcome from the payment screen and TEX refunds what the change still owes; every refund Pending over 5 minutes shows in the system status; refunds with no answer and paid changes not yet applied are set aside; moving the arrival later inside a penalty window goes to the hotel; transient database errors are retried; lost apply jobs are swept; channel changes lock the booking first. Booking Engine is no longer a money blocker (PARTIAL until CI and `manage-money.spec.ts` run). Verdict unchanged: NOT READY.
- 2026-09-24: a third review of the G-45 refund fixes found 1 High (a refund's outcome can be recorded by staff while the gateway call is still running; the gateway's answer is then lost and the amount can be refunded again) and 1 Medium (a refund run can lose its lease when its first refund fails before committing). Booking Engine is a money blocker until they are fixed.
- 2026-09-24: G-41 closed in code except the allotment channel split (ADR-050): staff price and book only on the sales channels of their permission profiles at that hotel (blank = the call centre; `price.any_channel` = every channel, held by the admin and revenue defaults); search, quote, quote summary, booking and payment methods check the channel of the offer or quote, never the request; modifications keep the reservation's channel; grants need the profile's channels. p29 keeps admin, revenue and contract-publishing profiles on every channel; nothing widens. The CRS picker offers only allowed channels. Security stays PARTIAL (blocker items unchanged). Verdict unchanged: NOT READY.
- 2026-09-24: G-45 third review fixed (ADR-044 third review section, branch `fix3-g45`): staff record a refund's outcome only once its answer cannot come any more (the server refuses while its gateway call may run and says why); after the gateway answers, the booking, the request, the refund and its charge are locked in one order and a recorded outcome is never overwritten (the same answer counts once, another one is an audited conflict failed in the system status that stops the change's refunds for staff); a refund run keeps its hold when a refund fails early and counts the refunds it made; channel modifications lock their rooms before the nights; the payment job never raises. G-93 fixed: money refunded outside TEX is recorded on the booking. Booking Engine is no longer a money blocker (PARTIAL until CI and `manage-money.spec.ts` run). Verdict unchanged: NOT READY (G-92, certifications, SMTP, backups, CI, security contact and pentest).
- 2026-09-24: G-41 adversarial review fixed (ADR-050 review follow-up): a booking site sells only on a web channel (a site stored with another channel sells nothing; p31 reports it) and a staff booking made on it is flagged and audited; channels serve only the capability of the profile that lists them (pricing vs booking); a change of room, rate plan, board or market needs booking entitlement for the reservation's channel. G-94 (inherited, found by the review): an ended access grant kept its hotel in scope through its mirrored User Permission row, with the user's role defaults; now live grants alone decide, ended grants' rows are removed and audited at the site's midnight, and the legacy hotel-bound DocTypes follow the TEX scope in Desk/REST. Security and Tenant isolation stay PARTIAL (blockers unchanged). Verdict unchanged: NOT READY.
- 2026-09-24: a fourth review of the G-45 refund machinery found 1 High in the new G-93 path (closing staff money as "Refunded outside TEX" records nothing when a guest change's money is handed back on a partly-paid booking, so the hotel under-collects at checkout) and 3 Medium (outside refunds counted against unallocated money; limit reads not locking; a transfer during a gateway refund). Booking Engine is a money blocker until they are fixed. G-94 (an expired grant still granted) is re-rated Critical and is fixed.
- 2026-09-24: G-56 and G-52 closed in code (ADR-051). Every FX conversion a quote makes (room rate and cost, extras, fixed promotions and their minimum-basket thresholds, coupons, fixed levies) is recorded in the quote and so in the reservation's price-locked snapshot, with the exact rate, provider rate and date, adjustment, policy and sale time, and explained step by step; ORIGINAL_VERSION / ORIGINAL_SALE_DATE modifications reprice with those recorded rates, CURRENT and HISTORICAL_SALE_DATE with the tables as of their own time. Age bands are judged in whole months: a gap (e.g. a band ending at 2.95 years next to one from 3) or an overlap is refused at publish and on a pricing-policy save, naming the months; the CRS, Call Center, modification drawer, booking engine and manage page take a child's date of birth, which the server checks and prices in completed months on arrival. Pricing stays PARTIAL and a money blocker (G-72, G-84, deploy-time precedence report). Verdict unchanged: NOT READY.
- 2026-09-24: G-56 / G-52 review follow-up (ADR-051): no Critical or High finding; the FX pinning is sound. Fixed: a child's date of birth no longer reaches funnel analytics, staff notes or error messages, and searches are POST only (it never sits in a URL); a baby born after the pricing reference date is priced as 0 months instead of an HTTP 500; a pricing input error is an unsellable quote; bookings sold before G-56 also reprice their extras and levies on the rates recorded on their lines. New Low gap G-95: pricing internals (cost, margin, FX record) in stored snapshots are readable through Desk/REST within the tenant. FX precision for rates below 1 is added to G-72. Verdict unchanged: NOT READY.
- 2026-09-24: a fourth review of the G-45 refund fixes (the lease and the order of outcome recording held) found 1 High, 3 Medium and 3 Low; all fixed (ADR-044 fourth review section, branch `fix4-g45`): money a guest change handed back to staff and staff gave back at the desk is recorded against the change's own payments on any booking (a deposit-only booking recorded nothing, and the hotel would have collected that much less at checkout); a refund recorded outside TEX for a booking comes off that booking only; refund and allocation limits are locking reads under the payment's lock (patch-free indexes); money being refunded cannot be transferred; a gateway answer contradicting a recorded outcome stops the change for every run until staff record what the gateway actually did (payment screen); p28 names the refunds older changes made. Booking Engine stays PARTIAL without a money blocker (CI and `manage-money.spec.ts` to run). Verdict unchanged: NOT READY.
- 2026-09-24: G-92 fixed (ADR-052, branch `legacy-price-g92`). At a TEX hotel a reservation is
  created only by TEX (the booking service behind the CRS, Call Center and booking engine, or a
  channel's sale) or by a migration import. The Desk form, REST and Frappe's Data Import are
  refused, whatever the status and whoever writes. `import_bookings` / `run_import` record a TEX
  hotel's rows as "Imported" at the file's Decimal amount, price-locked and audited (a live row
  needs an amount; `price.override` needed). The legacy auto-price never prices a TEX hotel. A
  stay there, including one the legacy engine sold before the hotel joined TEX, changes its
  dates, room type, party, board, rate plan, amounts or hotel only through TEX (Desk, REST,
  `set_value`, `amend_stay`, `move_reservation` refused). Hotels outside TEX are unchanged.
  Removed from the money blockers; Pricing and Inventory stay PARTIAL (G-72, G-84, deploy-time
  republish; G-41, G-47, G-48). Verdict unchanged: NOT READY.
- 2026-09-24: the G-92 review found 2 High money defects around it (import amount parsing; G-96 legacy check-out billing TEX stays at legacy rates) plus 3 Medium; money blockers until fixed.
- 2026-09-24: G-51 closed in code (ADR-054). A sale time belongs to the pricing basis: a change
  carrying its own `sale_at`, or a sale date with a basis other than HISTORICAL_SALE_DATE, is
  refused, and the historical sale date and the simulator's sale time are checked on the server.
  A historical-basis change and a manual override need `price.override` when applied as well as
  when proposed, and are recorded end to end (revision, audit with the computed total). The
  simulator, ORIGINAL_SALE_DATE, HISTORICAL_SALE_DATE and a guest's paid change select the
  contracts Active at their sale time (from the audited status changes); the simulator also
  counts the coupon uses held then (new `released_at`, patch p34). Proposal tokens are bound to
  their proposer, hotel and booking; guest self-service is unchanged. R-21 and R-22 are
  COMPLETE; Pricing stays PARTIAL and a money blocker (G-72, G-84, G-92, deploy-time precedence
  report). At deploy, run the migration (p34). Verdict unchanged: NOT READY.
- 2026-09-24: G-51 review follow-up (ADR-054 review section): no Critical or High finding. The
  Medium is fixed: approving a guest's waiting request no longer sells on a contract suspended or
  archived since. The approval is refused with the reason, and the request card shows the
  contract's status and disables Approve; requests still do not expire, and the paid path keeps
  its 90-minute window. Also fixed: a sale time with a UTC offset is read in the site's time zone
  (it was an HTTP 500); the channel re-check on apply is tested; an override's revision shows the
  basis and total the engine computed. No migration. Verdict unchanged: NOT READY.
- 2026-09-24: G-92 review fixed (ADR-052 review section, branch `fix-g92`), with G-96. Import
  amounts are read strictly: "150,00" is 150.00, "1.500" is refused unless the import gives its
  decimal mark, and negatives and garbage are refused per row. The preview shows each row's
  amount and currency. A TEX hotel's import names its currency. Each row is all or nothing. An
  imported amount is corrected with `price.override`, a reason, a revision and an audit event.
  The legacy check-out never bills a locked stay at the legacy rate: a TEX-sold stay is billed
  on its TEX booking, and an imported one posts its locked amount split over its nights. Its
  cancellation fee comes from that amount. The legacy cancel refuses a stay billed in TEX. A
  hotel joining TEX is onboarding, and the Desk sells it until an administrator sets it live
  (audited; p36 keeps today's TEX hotels live; banners in the TEX shell, the legacy shell and the
  Desk form). The modification flag covers one save. Removed from the money blockers. At deploy,
  run the migration (p36) and set each joining hotel live when it is ready (owner input 10).
  Verdict unchanged: NOT READY.
- 2026-09-24: G-74 closed in code (ADR-053, branch `audit-g74`): every saved draft contract edit is audited on every path as a compact, bounded diff (settings old → new, table rows by natural key) and a publish records the commercial difference against the version it replaces; ARI and limited-extras bulk edits keep each cell's old value; payment policies, provider accounts and method rules are audited on the TEX API, Desk and REST paths, secrets only as set / changed booleans; group and enterprise grant events name their group / enterprise and the hotels they reached (`TEX Audit Scope`, p33), so each hotel's administrators see them and no hotel reads another's name; payment outcomes record their real source (gateway return, gateway notification, staff, scheduler) and expired payment links are audited. The audit trail screen shows row changes, hotels reached and sources. Contracts' open item is G-73; Security stays PARTIAL (blockers unchanged). Verdict unchanged: NOT READY.
- 2026-09-24: G-72 closed in code (ADR-055, branch `float-g72`). The generic rule values of the commercial DocTypes were Float fields of precision 6, which Frappe v16 stores as DECIMAL(21,6): a 7th decimal was rounded away on save. They keep 9 places now (DECIMAL(21,9); percentages are Percent, the loyalty point value is Currency in the program's currency with 9 places); a typed value is stored exactly or refused, naming the field; loaders read the exact Decimal (`money.db_dec`) and the TEX API returns strings. FX rates keep at least 10 significant digits (TRY → EUR 0.02941176471, was 0.029412); a rate recorded before at 6 places reads back as recorded, so price-locked reservations reprice ORIGINAL_* to their sold totals; new quotes and CURRENT/HISTORICAL reprices use the new precision (a cent can differ where a rate below 1 or a cross rate converts). At deploy, run the migration (the DocType sync widens the columns; p35 checks them and verifies every published payload's hash, nothing is rewritten). R-02 and R-03 are COMPLETE. Pricing stays PARTIAL and a money blocker for G-84, G-96 and the deploy-time precedence report. Verdict unchanged: NOT READY.
