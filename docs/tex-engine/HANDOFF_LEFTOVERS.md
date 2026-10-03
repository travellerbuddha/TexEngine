# Handover appendix: functional leftovers of audit Part 2

Companion to `docs/tex-engine/HANDOFF.md` (read that first: method, rules, order of the batches). This file lists every
functional leftover of Part 2 that is still open, de-duplicated from the "Kalanlar / Remaining / Not done" sections of
PRs #3–#16, from `IMPLEMENTATION_STATUS.md` §6 and from the audit's review notes. Each row was checked statically at
`aac444a4` (2026-10-01; no bench run): file:line, a fix sketch and the fail-first test. **Re-verify each row before
you change code** — line numbers drift, and a few rows say "not re-verified".

Status words: **STILL OPEN** (verified at file:line, or "not re-verified" when only PR text backs it), **FIXED LATER**
(a later PR closed it), **NOT REPRODUCIBLE** (the code already prevents it). Severity is operational risk: HIGH =
likely wrong money, double sale or data exposure; MED = the same but rare, flagged for staff, or only once loyalty or a
channel connection is live; LOW = UX, tests, scale, tooling, text.

`api/public.py` is reserved for the Stage 3 chain (HANDOFF.md §2): an item that needs it is a Stage 3 add-on.

## 0. Counts

| | Count |
|---|---|
| Open leftovers (LO-01…LO-49) | **49**: **HIGH 0**, **MED 5**, **LOW 44** (8 of the LOW rows are not re-verified in code) |
| FIXED LATER | 21 rows (§1b) |
| NOT REPRODUCIBLE | 1: PR #16 "legacy `kamra.api.cancel_reservation` vs the channel guard" |
| Not planned, informational | 5 (§1d) |
| CONDITIONAL, waiting for an owner decision or an external party | 16 (§3) |
| Proposed batches | 7 (A–G) plus 1 Stage 3 add-on (§2) |

**The MED items:**
- LO-01: O-19b, the points' share of a lower price.
- LO-02: channel bookings and points.
- LO-03: a disabled room type is still sold.
- LO-04: a reused charge settled during the checkout call.
- LO-05: a second payment during an iyzico fraud review.

No HIGH item was found. Three conditions change the picture:
- LO-01, LO-02 and LO-06 assume loyalty is live at go-live (D-12; the audit's default is that it is).
- The ARI part of LO-03 and all of LO-02 matter once a channel-manager connection is live (§5a certification).
- LO-04's chance depends on whether the gateway accepts a duplicate order. iyzico starts a new charge instead (`providers/turkey.py:135-141`); Sipay and NestPay are not certified yet.

## 1. Leftover table

### 1a. STILL OPEN

**How to read the "Files / touches" column**
- **Shared files:** `services/booking.py`, `payments/service.py`, `services/late_payments.py`, `services/guest_changes.py`, `crm/loyalty.py`, `distribution/*` and `api/public.py`.
- **`api/public.py` is reserved for Stage 3.** An item that needs it is an add-on to the Stage 3 list.

| ID | Origin | Problem (one line) | Sev | Status, evidence | Fix sketch | Fail-first test | Files / touches |
|---|---|---|---|---|---|---|---|
| **LO-01** | O-19b (PR #14 Remaining; §6H2 Not done). Same root as PR #4 Kalan ("staff close builds `settlement.Charge` without `points`") and the "lower price gives no points back" line of PR #14 | When the price of a booking paid partly with points goes down, the points' share is never given back as points. The settle job hands it to staff. Staff's "Refunded outside TEX" then either fails (the Loyalty charge is the newest: "Points are given back as points…") or records it as a cash refund off a card, which turns points into cash. This is the default flow: lower price → Staff approval → "Refund" | MED (loyalty live) | **FIXED in Part 2K-2** (IMPLEMENTATION_STATUS §6K2); was STILL OPEN, verified:<br>• `services/guest_changes.py:1569-1606` `_record_outside` builds `st.Charge(...)` with no `points=` (:1588, :1592), although `pay.booking_charges` returns `points` (`payments/service.py:1159-1185`).<br>• In `settle()`'s Refund branch (`guest_changes.py:1018-1046`), `refundable_now` (:372-383) is points-first, so the points' share ends up in `short`, which goes to `_give_to_staff` (:1097-1099).<br>• The guard `_refuse_cash_for_points` (`payments/service.py:1215-1219`) is called from `refund_outside` (:1470) | 1. In `settle()`'s Refund branch, before planning cash, give back min(points held, `left`) as points: `loyalty.return_points(booking, reason=…, limit=left)` with a new `limit` parameter (same pro-rata Reverse rows and `pay.points_back`). Count it in `refunded_amount`.<br>2. In `_record_outside`, pass `points=c["points"]` and cap cash at the overpayment less the points held.<br>3. The staff dialog says the points went back. Doing it automatically also prevents a manual +adjust followed by a second return at cancellation | `test_self_service_money` / `test_loyalty_admin.TestPointsBack`:<br>• Setup: 1000 paid as 300 pts (newest charge) + 700 card; a guest change to 800 is approved as "Refund".<br>• Expect: points worth 200 come back (Reverse row, POINTS RETURNED refund) and nothing is left to staff.<br>• Red: staff_open 200, and close with REFUNDED_OUTSIDE raises.<br>• Card-newest variant: no Manual refund on the card (red: 200 recorded as cash) | `services/guest_changes.py`, `crm/loyalty.py` (`return_points` limit). Touches LO-02, LO-06 (`return_points`) and Stage 3 G-70 (G-70 rewrites throw sites in `guest_changes.py`) |
| **LO-02** | PR #16 Kalanlar ("`loyalty.redeem` has no channel guard…"). PR #14 Remaining / §6H2: "a channel's cancellation does not give points back" | Staff can redeem points on an OTA booking, and can allocate or transfer a Loyalty charge onto one. When the channel cancels, `channel_booking` neither gives the points back nor waits until the money is settled before reversing the stay's points (an O-20-class Adjust is possible). The points are lost and their money stays on the cancelled booking | MED (loyalty and a channel live) | **FIXED in Part 2K-2** (IMPLEMENTATION_STATUS §6K2); was STILL OPEN, verified:<br>• `crm/loyalty.py:464-535` `redeem` checks scope, guest, program, currency, blackout and `refuse_if_it_cannot_take` (:502), but not `booking.channel_of`.<br>• `distribution/channel_booking.py:320-342` `_cancel_one` and `:345-355` `_cancel_all` have no `return_points` and no `tex_loyalty_after_money`.<br>• `payments/service.py:936-1020` `allocate` and `:1058-1065` `transfer` have no Loyalty → channel check | 1. `redeem` refuses `channel_of(booking)` bookings: "its price and payment are the channel's", as `addons._open` and `modification.propose` already refuse.<br>2. `allocate` (staff and `_system`) refuses a Loyalty charge for a channel booking.<br>3. `_cancel_one` sets `res.flags.tex_loyalty_after_money`. `_cancel_all` and `_update` call `loyalty.return_points` after `_refresh_booking_after_change`, then `loyalty.on_reservation_change`, mirroring `booking.cancel_reservation` (`services/booking.py:1177-1194`). This follows D-16 (points come back on a cancellation) | `test_distribution.TestChannelBookings`:<br>• Redeem on a channel booking → ValidationError (red: succeeds).<br>• Allocate a Loyalty charge to it → refused (red: allowed).<br>• A channel booking holding a Loyalty charge (fixture), cancelled by an inbound "cancelled" message → points back as a Reverse row, paid 0, no Adjust (red: balance unchanged, paid stays) | `crm/loyalty.py`, `distribution/channel_booking.py`, `payments/service.py` (`allocate` only). Touches LO-01, LO-06 and LO-13 (`channel_of`) |
| **LO-03** | PR #16 Kalanlar ("ARI does not send a disabled room type closed"), plus the same class found in verification | A disabled room type is still sold:<br>• ARI keeps pushing it as open, with pool availability and rates, and disabling it queues no ARI sync.<br>• Quoting an offer key minted before it was disabled still works.<br>• A staff modification into a disabled type is not refused | MED (the ARI part needs a live channel) | **FIXED in Part 2K-3** (IMPLEMENTATION_STATUS §6K3); was STILL OPEN, verified:<br>• `distribution/repository.py:112-156` `build_days` checks only the mapping's `enabled` (:127).<br>• `kamra/hooks.py:311`: Room Type has only a `validate` hook, no ARI queue.<br>• `services/quoting.py:210-229` makes search skip disabled types, but `_on_sale` (:535-548) and `_stay_refusal` (:551-562) do not.<br>• `services/modification.py` has no disabled check (grep) | 1. `build_days`: for a disabled room type, `closed_day` on every day, as for a disabled mapping.<br>2. A Room Type `on_update` hook: when `disabled` changes, `queue_mapping` each of its mappings.<br>3. The quote (`_stay_refusal`) and `modification.propose` (room-type change) refuse a disabled type ("no longer sold").<br>4. The pool keeps counting it (Y-9 unchanged) | • `test_distribution`: a disabled type with an enabled mapping → every day closed, availability 0 (red: open with rates); toggling `disabled` queues an ARI job (red: nothing queued).<br>• `test_public_booking`: an offer key minted before disabling, then quoted → refused (red: ok).<br>• Modification test: staff change to a disabled type → refused (red: allowed) | `distribution/repository.py`, `kamra/tex/hooks.py`, `kamra/hooks.py`, `services/quoting.py`, `services/modification.py`. Touches Stage 3 G-71 (`quoting.py`) and G-70 (the new guest refusal needs a code) |
| **LO-04** | PR #9 Kalanlar ("for a reused charge settled during (b), step (c) still returns a new checkout URL") | A reused Pending charge that a callback settles while step (b) creates a new checkout still hands that new checkout URL to the guest. If the guest pays it, `complete` answers "replay" for the now Succeeded charge, so the second capture is never recorded in TEX | MED (silent money; a rare race; depends on the gateway) | **FIXED in Part 2K-1** (IMPLEMENTATION_STATUS §6K1); was STILL OPEN, verified:<br>• Step (c) of `start_payment` (`payments/service.py:451-462`) writes the ref and returns `checkout.url` whatever `txn.status` is.<br>• `complete` returns replay for a charge outside `SETTLEABLE` (`service.py:86`, Pending/Failed/Cancelled) at :500-501 | 1. In (c): if the locked charge is no longer Pending, commit and raise the existing refusal "This payment was already processed ({0})" (`service.py:368`). The answer shape is unchanged, so `api/public.py` is not touched.<br>2. Optional: in `complete`, a verified success that names another provider ref on a Succeeded charge is audited and sent to reconciliation (Action Required, a new cause such as `DUPLICATE_CAPTURE`) instead of a silent replay | `test_hold_payment_race` (style of `TestNoLockHeldThroughTheGateway`): the reused charge's fake `create_checkout` commits Succeeded from another connection → `start_payment` raises "already processed" and returns no URL (red: a new URL is returned) | `payments/service.py`. G-70 already plans a code for this text family |
| **LO-05** | PR #11 Kalanlar ("A second payment can be started during a fraud review") | While iyzico holds a charge in fraud review, the guest can pay again:<br>• With a new key, a second charge starts.<br>• With the same key, the reviewed charge is superseded, because iyzico cannot add a checkout.<br>If the review is approved, both are captured. The excess is caught only as OVERPAID → Action Required, and staff must refund it | MED | **FIXED in Part 2K-1** (IMPLEMENTATION_STATUS §6K1); was STILL OPEN, verified:<br>• `services/holds.py:250-280` `open_attempt` has no review check.<br>• `payments/service.py:389-390`: the reuse branch calls `_supersede` when `can_add_checkout` is False. `FRAUD_REVIEW` is at :550 | 1. Refuse a new start for a booking or link that has a Pending charge with `raw_status IN FRAUD_REVIEW` (PaymentBusy-like: "your bank is reviewing your payment").<br>2. Never supersede a charge under review in the reuse branch | `TestIyzicoFraudReview`:<br>• Under review → `pay_booking` with a new key → refused, one charge (red: a second charge).<br>• Same key → the reviewed charge is not superseded (red: Cancelled or superseded) | `payments/service.py`, `services/holds.py`. G-70 must code the new refusal |
| LO-06 | PR #14 Remaining (transfer line; "a guest who changed since the redemption"); PR #14 review | `return_points` looks for a Loyalty charge's burn row only among this booking's current guests, with `booking = this booking`. Two cases give no points back: a charge staff moved to another booking (`transfer`), and a burner no longer on the booking. Only an Error Log is written; the money is left to staff and can never go out as cash | LOW (points lost; visible in `payments.overpaid` and the Error Log) | **FIXED in Part 2K-2** (IMPLEMENTATION_STATUS §6K2); was STILL OPEN, verified:<br>• `crm/loyalty.py:545-548` `BURNS_OF` filters `booking=%(b)s`; guests come from this booking (:574).<br>• Skip plus `log_error` at :596.<br>• `payments/service.py:1058-1065` `transfer` accepts Loyalty charges | 1. Guests = this booking's ∪ the booker and room guests of the charge's own booking (`t.booking`).<br>2. `BURNS_OF` uses `booking IN (b, t.booking)` and `reason = 'redeemed as {t}'`; the index (guest, program) still applies.<br>3. Lock order unchanged: guests (sorted) → charges → burns.<br>Alternative (decide): refuse `transfer` or `release` of a Loyalty charge | `TestPointsBack`:<br>• Redeem 300 on A, staff transfer the charge to B, cancel B → 300 points back (red: Error Log "Loyalty points not returned", balance unchanged).<br>• Burner replaced on the room → points back to the burner (red) | `crm/loyalty.py` (`payments/service.py` if the alternative is chosen). Touches LO-01, LO-02 |
| LO-07 | PR #15 Kalanlar | `late_payments.refund_queued` has no time budget and no limit. During a gateway outage each queued refund waits the provider's timeout, and the job runs before `expire_links` and `mail_status.sync` in the same RQ job (300 s) | LOW (ops; a link is still expired on read: `link_by_token`, `payments/service.py:1901-1911`) | **FIXED in Part 2K-1** (IMPLEMENTATION_STATUS §6K1); was STILL OPEN, verified:<br>• `services/late_payments.py:433-471` loops over every queued charge with no budget.<br>• `kamra/tex/scheduler.py:28-33`: `refund_queued` runs before `expire_links` and `mail_status.sync` | `refund_queued(limit=20, budget_seconds=90)`:<br>• uses `time.monotonic`;<br>• starts no refund past the budget;<br>• takes the oldest first;<br>• runs last in `EVERY_5_MINUTES`.<br>This mirrors `deliver_pending` | Three Refund Queued charges, each refund advancing a fake clock 50 s, budget 60 → two refunded, the third still queued (red: all three attempted). A static order test: `expire_links` and `mail_status` come before `refund_queued` | `services/late_payments.py`, `scheduler.py` |
| LO-08 | PR #15 Kalanlar | With a single RQ worker, the PMS outbox job (≤ 120 s budget + one 30 s call) and the 5-minute group run one after the other. A slow PMS still delays holds, payments and links by up to about 150 s | LOW (ops / deploy) | **FIXED in Part 2K-4** (IMPLEMENTATION_STATUS §6K4); was STILL OPEN, verified:<br>• `kamra/hooks.py:59`: both jobs share one `*/5` cron entry on the default queue.<br>• `deploy/tex-local/Procfile:3`: one `bench worker` | Two options:<br>• the cron entry only enqueues `deliver_pending` (queue `long`, a `job_id`, deduplicate) and the deploy runs a worker for that queue;<br>• or document at least two workers.<br>The status page keeps watching the job | Unit: `outbox_every_5_minutes` enqueues on the dedicated queue (red: runs inline) | `scheduler.py`, `kamra/hooks.py`, `deploy/*`. 2Z docs follow |
| LO-09 | PR #15 Kalanlar | The revival's duplicate check is a plain read. A duplicate committed after the callback's read view began (during the gateway call) is missed, so both bookings go live and the guest is charged twice | LOW (narrow race) | **FIXED in Part 2K-3** (IMPLEMENTATION_STATUS §6K3); was STILL OPEN, verified:<br>• `services/booking.py:1388-1425` `live_duplicate` uses a plain `frappe.db.sql`.<br>• It is called after the booking lock in `late_payments.revive` (`late_payments.py:167`) | Under the booking lock:<br>1. Resolve the matching guest profiles with a plain read.<br>2. Re-check `Reservation` by (guest, property) with `LOCK IN SHARE MODE` on the index `Reservation(guest, property)`, never an OR across three indexes | Two-connection test, in the pattern of PR #4 round 2: the callback's read view is open, the other connection commits B3 for the same guest, then revive → not revived, Action Required naming B3 (red: revived) | `services/booking.py` (`late_payments.py` unchanged) |
| LO-10 | PR #15 Kalanlar | `outbox._claim` reads every undelivered Reservation message (all connections) on each round to find the first per reservation | LOW (scale: a long outage leaves thousands in back-off) | **FIXED in Part 2K-4** (IMPLEMENTATION_STATUS §6K4); was STILL OPEN, verified: `connect/outbox.py:133-137` | Bound the read:<br>• `LIMIT` per round on a `(kind, status, creation)` index (DocType index plus patch);<br>• or a per-(connection, reference) `MIN` subquery.<br>Keep FIFO | With 2,000 rows in back-off, one round reads at most the cap (count via a sniff); `TestPmsDelivery`'s order tests stay green | `connect/outbox.py` (plus a patch if an index is added) |
| LO-11 | PR #16 Kalanlar (`resend_confirmation`), service part | `resend_confirmation` mints a manage token and e-mails a manage link for a channel booking. The guest then sees Cancel and Change, which the server refuses | LOW | **FIXED in Part 2K-3** (IMPLEMENTATION_STATUS §6K3); was STILL OPEN, verified:<br>• `services/booking.py:1285-1310`: no channel check.<br>• `api/crs.py:237-245` | For `channel_of(booking)`, either refuse ("the channel sends the confirmation") or send without a manage link. Never mint a token | `TestChannelBookings`: resend on a channel booking → refused, or no new `manage_token_hash` (red: the token changes) | `services/booking.py`, `services/notify.py`. Pairs with LO-12 |
| LO-12 | PR #16 Kalanlar, guest-page part. **Stage 3 add-on (`api/public.py`)** | The manage view returns `can_cancel` and `can_change` as true for a channel booking; the server refuses both | LOW | **FIXED in Part 2G-3** (IMPLEMENTATION_STATUS §6G3; the view says `sold_by {label}`, not `channel`, which G-71 keeps out of guest answers); was STILL OPEN, verified:<br>• `api/public.py:792-831` `_guest_booking` (`can_change` :811, `can_cancel` :813).<br>• `_cancellable_online` :833-839.<br>• `services/guest_changes.py:222-226` `room_changeable` | Both flags false for `channel_of(b)`. Add `channel: {label}` and a notice. G-70 gives the refusals a code (for example `CHANNEL_BOOKING`) | `test_commercial_flows.TestSelfService`: the manage view of a channel booking has `can_cancel` and `can_change` False (red: True) | `api/public.py` (Stage 3), `services/guest_changes.py` |
| LO-13 | PR #16 review (LOW) | Refusals and the cancel dialog name the connection by its internal id ("Sold by CON-0001: …"), also on the guest's manage page | LOW | **FIXED in Part 2K-3** (IMPLEMENTATION_STATUS §6K3); was STILL OPEN, verified:<br>• `services/booking.py:1095-1100` `channel_of` returns `channel_connection` (autoname `CON-.####`, title field `label`); the message is at :1127.<br>• `api/crs.py:209, :279`.<br>• `frontend/src/tex/screens/reservations/components/ActionDialogs.tsx:271` uses `connection` in `res.cancel.channel` | `channel_of` also returns `label` (fallback: the name). Messages and the dialog use it; the audit keeps the id | `TestChannelBookings`: the refusal names the label and contains no "CON-" (red); the preview returns `label` | `services/booking.py`, `api/crs.py`, reservations UI, i18n ×6 |
| LO-14 | PR #16 Kalanlar ("checkout's basket failure at a hotel that has no Card method") | When the basket cannot be read, checkout offers Card only, also at a hotel that does not sell cards. The server refuses it and the guest has no way on | LOW | **FIXED in Part 2K-5** (IMPLEMENTATION_STATUS §6K5); was STILL OPEN, verified:<br>• `frontend/src/booking/lib/methods.ts:14-22` `fallbackChoices`.<br>• `Checkout.tsx:19` | On a basket failure, show the error with a retry instead of guessing a method; or the site payload carries the offered methods | Node `checkout-fallback`: a failure gives no choice and a retry state (red: Card) | `frontend/src/booking` (`Checkout.tsx` is also edited by G-70) |
| LO-15 | PR #16 review; same pattern found in p61 | `assertGreaterEqual` on tuples compares lexicographically: `(2, 0, 0) >= (1, 3, 1)` passes | LOW (test) | **FIXED in Part 2K-3** (IMPLEMENTATION_STATUS §6K3); was STILL OPEN, verified: `kamra/tex/tests/integration/test_patches.py:1502` (p58) and `:1397` (p61) | Assert each component | Mutation: a p58 printing "2 pools, 0 rows, 0 kept" must fail (red: passes) | tests only |
| LO-16 | PR #4 Kalanlar (round 2, `late_payments._flag`); PR #4 review ("stale reconciliation note on a second flag") | `_flag` reads `reconciliation` without a lock. In the expiry-versus-refund race the charge gets two `payment.reconciliation_required` events and the team a second notice. A second cause never reaches the note | LOW | **FIXED in Part 2K-1** (IMPLEMENTATION_STATUS §6K1); was STILL OPEN, verified: `services/late_payments.py:313-326` (plain `get_value` at :316) | Read it `for_update=True` (most callers already hold the charge). When it is already open, append the new cause to the note | PR #4's two-connection test: exactly one audit event and one notice (red: two) | `services/late_payments.py` |
| LO-17 | PR #11 Kalanlar ("a refund on its way still counts as paid"; "`payments.overpaid` counts guest-change credits"); 2B review notes | `payments.overpaid` counts bookings that hold a guest-change credit kept on purpose (a false WARN). A refund still on its way counts as paid, so new money may be parked as OVERPAID until it resolves | LOW | **FIXED in Part 2K-1** (IMPLEMENTATION_STATUS §6K1); was STILL OPEN, verified: `kamra/tex/ops/status.py:313-322` `_bookings_overpaid` (`paid_amount > total_amount`, credits not excluded) | Leave out the credit kept on purpose (`guest_changes.guest_credit`, requests settled as "Credit on booking"). The check's text mentions refunds in flight | `test_system_status.TestOverpaidBookings`: a booking with a kept change credit is not counted (red: counted) | `ops/status.py`, `ops/checks.py` |
| LO-18 | PR #11 Kalanlar ("No staff action closes or records a stale Virtual POS charge") | A Pending charge of a gateway TEX cannot ask (Virtual POS) cannot be closed by staff. It stays Pending, and `payment_pending_unverified` FAILs until it ages out (48 h) | LOW (the real fix is NestPay's order query, which needs certification, §5a) | **FIXED in Part 2K-1** (IMPLEMENTATION_STATUS §6K1); was STILL OPEN, verified: no close action among the `kamra/tex/api/payments.py` endpoints (:112-412) | A staff action "Not paid (checked with the bank)": Failed with a reason, audited, `payment.refund`; the status check clears. "Paid" uses the existing manual or allocate path | API test plus `test_system_status.TestUnverifiedPayments`: close → Failed, audit, FAIL cleared (red: no endpoint) | `payments/service.py`, `api/payments.py`, payments UI |
| LO-19 | PR #11 Kalanlar ("Staff `reverify`'s token loop still holds a lock…") | Staff re-verify keeps the charge's lock from a Failed answer through the next token's gateway call (old iyzico charges with several tokens) | LOW | **FIXED in Part 2K-1** (IMPLEMENTATION_STATUS §6K1); was STILL OPEN, verified:<br>• `kamra/tex/api/payments.py:185` calls `pay.reverify` without `step_commit`.<br>• `payments/service.py:626-668` commits between tries only with `step_commit` | Use `step_commit=True` on the staff path too (nothing uncommitted comes before it; `_commit_step` counts for `retry_on_deadlock`) | Lock sniff: the second token's HTTP call runs with no `FOR UPDATE` held on the charge (red: held) | `payments/service.py`, `api/payments.py` |
| LO-20 | PR #11 Kalanlar | On a gated account each question the job asks may write a `payment_account.settled_while_gated` audit | LOW | **FIXED in Part 2K-4** (IMPLEMENTATION_STATUS §6K4); was not re-verified, then verified STILL OPEN: `payments/service.py` `provider_for` audits every settle call of a gated account, and `reverify_pending` asks a Pending charge every 5 minutes | At most one per charge per day | Job test on a gated account: one audit (red: several) | `payments/service.py` |
| LO-21 | PR #11 Kalanlar; §6E2 "Open" | The job's candidates include iyzico charges with no token, which have nothing to ask but take places in the tick's 20 | LOW | **FIXED in Part 2K-1** (IMPLEMENTATION_STATUS §6K1); was STILL OPEN, verified:<br>• `payments/service.py:696-707`: no condition on `provider_ref`.<br>• `providers/turkey.py:85-87` returns `[]` for a charge without a token | Filter by `status_params` before the limit (fetch twice the batch, keep the askable ones), or exclude iyzico rows with an empty `provider_ref` in SQL | `TestPaymentsVerifiedByTheJob`, `REVERIFY_BATCH=1`: a tokenless charge ahead in urgency → the next askable charge is asked (red: the tick is wasted) | `payments/service.py` |
| LO-22 | PR #11 Kalanlar; §6E2 ("→ later") | There is no `last_reverified_at`, so ordering by urgency alone can ask the same charges on every tick while others wait | LOW | **FIXED in Part 2K-4** (IMPLEMENTATION_STATUS §6K4); was STILL OPEN, verified: the field does not exist (grep) | Field plus patch (DocType JSON, `patches.txt`). Ties ordered by `last_reverified_at`, never-asked first; written for each question | Job test with more candidates than the batch: each is asked within two ticks (red) | `payments/service.py`, DocType, patch |
| LO-23 | PR #14 Remaining; §6H2 Not done | A hold whose points were given back at expiry, then revived by money paid in time, is not revived when the card money alone no longer covers what it owes. It goes to Action Required (points are never burned again, the 2H-2 default) | LOW | **FIXED in Part 2K-2** (IMPLEMENTATION_STATUS §6K2); was STILL OPEN (by design), verified:<br>• `services/late_payments.py:151-188` `revive`: coverage at :170 counts only Release money (`_held_when_expired` :189-208).<br>• `money_off` gives points back first (:227) | Keep the rule and say it in the Action Required note: "points were given back; ask the guest to pay the rest or redeem again". Burning again needs an owner decision | `TestPointsBack`: an expired hold with points, then late card money → the note mentions the returned points (red: generic note) | `services/late_payments.py` |
| LO-24 | PR #14 Remaining ("The guest's stays tab…") | The CRM profile's stays tab lists an expired hold as an ordinary cancelled reservation | LOW | **FIXED in Part 2K-2** (IMPLEMENTATION_STATUS §6K2); was STILL OPEN, verified: `kamra/tex/crm/service.py:233-282` `profile`; the stays query (:245-249) has no `tex_hold_expired` | Return `hold_expired` for each stay (or leave them out); the UI shows a "Hold expired" badge; i18n | `test_crm_privacy`/`test_crm_segments`: the profile's expired-hold stay has `hold_expired: true` (red: absent) | `crm/service.py`, CRM UI |
| LO-25 | PR #13 Remaining | A profile can show negative points after a changed stay, with nothing to explain it | LOW | **FIXED in Part 2K-2** (IMPLEMENTATION_STATUS §6K2); was STILL OPEN, partly verified: no negative-balance handling in `frontend/src/tex/screens/crm` (grep); UI not run | Show "points owed (spent before the stay changed)" when below zero; the summary returns `debt` | DOM or unit test of the profile summary | `crm/loyalty.py` (summary), CRM UI |
| LO-26 | PR #13 Remaining | A changed stay whose points had expired earns the full new amount again, with a fresh expiry | LOW (reachability not verified; a stay is normally changed before arrival) | **FIXED in Part 2K-2** (IMPLEMENTATION_STATUS §6K2); was STILL OPEN (ADR-071 §5), verified: `crm/loyalty.py:188-210` (new lot, `expires_on` from the new `available_on`) and `_reverse` :213-236 | If it is reachable: the new lot keeps the old lot's expiry, or the share that had expired expires again | `TestModification`: changing a stay whose lot expired gives back no expired points (red) | `crm/loyalty.py` |
| LO-27 | PR #13 Remaining | No browser test covers the abandoned list's `sms:` and `wa.me` links, or the absence of `tel:` | LOW (test) | **FIXED in Part 2K-6** (IMPLEMENTATION_STATUS §6K6); was STILL OPEN, verified: no spec under `frontend/e2e` covers `Abandoned.tsx` (`crm-admin.spec.ts` only uses the segment rule) | New Playwright spec | new e2e | `frontend/e2e` |
| LO-28 | PR #8 Kalanlar ("TEX audit log hotel view, other record types") | The hotel view of the TEX audit log filters only cost events by capability. A custom profile with `settings.admin` but without `payment.view` or `reservation.view` reads payment and stay events there | LOW (custom profiles only; default profiles with `settings.admin` hold every capability) | **FIXED in Part 2K-4** (IMPLEMENTATION_STATUS §6K4); was STILL OPEN, verified: `kamra/tex/api/admin.py:481-492` `_cost_hidden`; :510-516 property branch; `TRAIL_CAPABILITY` (:442-444) is not applied to the hotel view | Add the `TRAIL_CAPABILITY` doctypes to the hidden list when their capability is missing, filtered in the query as today | `test_audit_trail`: a custom profile with `settings.admin` only sees no payment or stay events in the hotel view; `limit=1` still pages (red) | `api/admin.py` |
| LO-29 | PR #8 Kalanlar; PR #8 review | p63 masks Password values in Version `changed` and `row_changed`, but not in child rows under `added` or `removed` | LOW (latent: no child table has a Password field today) | **FIXED in Part 2K-6** (IMPLEMENTATION_STATUS §6K6; the hook needs no change: Frappe stores a Password's dummy value before the Version, children too); was STILL OPEN, verified for p63: `kamra/patches/tex/p63_versioned_passwords.py` handles no `added`/`removed` (grep). `security/internals.mask_version` not re-verified | Mask the Password fields of child rows in `added`/`removed`, in the patch and the hook | A synthetic child Password field (Custom Field) is masked in `added`/`removed` (red) | `patches/tex/p63`, `security/internals.py` |
| LO-30 | PR #6 Remaining ("payment-link return token", LOW); PR #8 Kalanlar ("→ Part 2E", never done) | The payment-link token is put back into the address bar (fragment) when the guest returns from the gateway, and is there on first open. This is the pattern O-27 removed from the manage link | LOW (no tracker loads on `/pay`: `PayLinkPage` is outside the site context, `BookingApp.tsx:57-60`; the exposure is the address bar and history) | **FIXED in Part 2K-5** (IMPLEMENTATION_STATUS §6K5); was STILL OPEN, verified:<br>• `frontend/src/booking/lib/mount.ts:59-68` (`payLinkRoute`/`payLinkPath`).<br>• `pages/PayLinkPage.tsx:16-37` (`takeLinkToken`) and :85 (`rememberReturn(…, payLinkPath(token))`) | Keep the token in `sessionStorage`, keyed by the transaction. Return to `/pay` without a fragment and read the stored token. E-mailed links are unchanged (fragment, stripped on load) | `pay-link.spec.ts`: after the mock gateway's return, no recorded URL (history or pushState) contains `token=` (red) | `frontend/src/booking`. `PayLinkPage` is also touched by G-70's pay-link codes, so do it after G-70 or as a Stage 3 add-on. **Left to batch 7 (2K-5) by Part 2G-3**: G-70b's pay-link codes are in |
| LO-31 | PR #6 Remaining (widget, minor) | When the widget's `site` attribute changes, the modal title keeps the previous site's name until the new theme arrives | LOW | **FIXED in Part 2K-5** (IMPLEMENTATION_STATUS §6K5); was not re-verified, then verified STILL OPEN: `frontend/src/widget/index.ts` `attributeChangedCallback` dropped the theme but kept `siteName` | Replace the title when `site` changes, before the fetch | `widget.spec.ts` step | widget |
| LO-32 | PR #8 Kalanlar (2G-1 leftovers); PR #8 review | Checkout's re-quote compares the new price with the search's offer, not with the last quote the guest saw. An accepted change shows the notice again, and an extras-only change or a price going back to the search price is missed | LOW | **FIXED in Part 2K-5** (IMPLEMENTATION_STATUS §6K5); was STILL OPEN, verified: `frontend/src/booking/flow/BookingContext.tsx:442-445` (`before = (base[i] ?? sels[i]).quote…`) | Compare with the last quote shown (`flow.quotes[i]`) when there is one | `booking.spec.ts` (desktop): accept a change, re-quote at the same price → no notice (red) | `frontend/src/booking` |
| LO-33 | PR #8 Kalanlar (2G-1 leftovers) | On a phone the price-change notice is neither focused nor scrolled into view | LOW | **FIXED in Part 2K-5** (IMPLEMENTATION_STATUS §6K5); was STILL OPEN, verified: `frontend/src/booking/flow/useContinue.tsx:152-175` (`PriceChangeNotice` has no focus and no scroll) | Focus it and `scrollIntoView` the first time it shows | Playwright, mobile project | `frontend/src/booking` |
| LO-34 | PR #8 Kalanlar (2G-1 leftovers) | The CRS shows the previous method's "Due now" while the new method's summary loads (Book is disabled meanwhile) | LOW | **FIXED in Part 2K-6** (IMPLEMENTATION_STATUS §6K6); was STILL OPEN, verified: `frontend/src/tex/screens/crs/CrsPage.tsx:369-374` (renders `flow.summary.due_now` with no loading guard) | Hide "Due now" while the current method's summary is loading | `crs-actions.spec.ts`: hold the summary (O-29 pattern) | `frontend/src/tex/screens/crs` |
| LO-35 | PR #9 Kalanlar; PR #9 review | The booking engine writes "Deposit of 100 EUR" on every room of a multi-room offer, while the server takes it once per booking and policy | LOW | **FIXED in Part 2K-5** (IMPLEMENTATION_STATUS §6K5); was STILL OPEN, verified: `frontend/src/booking/lib/policy.ts:41-52` (`policy.depositFixed` for each quote) | Write it once per booking and policy (the first room carrying it, as `deposit_shares` does), or say "per booking" | Node test: three rooms → one deposit line (red) | `frontend/src/booking` |
| LO-36 | PR #9 Kalanlar | The shared concurrency `_cleanup` deletes CONC versions but not their child rows (rates, periods, boards, occupancy rules, rooms) | LOW (test hygiene) | **FIXED in Part 2K-6** (IMPLEMENTATION_STATUS §6K6); was STILL OPEN, verified: `kamra/tex/tests/integration/test_concurrency.py:29-44` | Delete the child tables by parent first (or use `delete_doc`) | After a race class, no orphan child rows remain (red) | tests |
| LO-37 | PR #12 Kalanlar | A manual rate also "bridges" a pair the provider never publishes (VND); the status page then shows that pair as WARN `fx_bridged` all the time | LOW | **DEFERRED** (D-13 answered no on 2026-10-02: the UTC+7 hotels are not in wave 1): a documented limitation with C-05; not re-verified. It returns with O-6 when those hotels are planned | Pairs served by a MANUAL-mode policy are not "bridged": WARN only for a pair the provider publishes. Tie to C-05 | `test_system_checks.TestFxBridged` | `ops/checks.py`, fx |
| LO-38 | PR #12 Kalanlar | The reservation detail's FX hint does not show `bridged_from` | LOW | **FIXED in Part 2K-6** (IMPLEMENTATION_STATUS §6K6); was STILL OPEN, verified: no `bridged_from` anywhere in `frontend/src` (grep) | Show "bridging {provider}" in the FX hint | DOM or unit test | reservations UI |
| LO-39 | PR #12 Kalanlar | `fx_rates` returns who entered a manual rate (a user e-mail) to anyone who may read prices at the hotel | LOW | **FIXED in Part 2K-4** (IMPLEMENTATION_STATUS §6K4); was STILL OPEN, verified: `kamra/tex/api/policies.py:321-330` (`source_ref` for MANUAL rows) and :363 (`source_ref = session.user`) | Return `source_ref` only to holders of `fx.manual_rate` or `settings.admin` (the audit trail keeps it) | `test_fx_snapshot`: a user with `price.view` only gets `source_ref` None (red) | `api/policies.py` |
| LO-40 | PR #5 Remaining | The workspace occupancy ladder does not model `infants_count_as_children`; a note is shown instead | LOW | **FIXED in Part 2K-6** (IMPLEMENTATION_STATUS §6K6; verified STILL OPEN: the note only); was **not re-verified** (PR #7 rewrote only the note) | Model the flag in `workspace/occupancy.ts` | Frontend unit test | rates workspace UI |
| LO-41 | PR #7 Kalanlar | Group ties go to the lowest promotion id compared as text, so from `PRM-100000` on, "the older promotion" is no longer the one with the lower id | LOW (a time bomb) | **FIXED in Part 2K-6** (IMPLEMENTATION_STATUS §6K6); was STILL OPEN, verified:<br>• `kamra/tex/pricing/promotions.py:285` (`key=(-priority, promo_id)`).<br>• `tex_promotion.json:399` (autoname `PRM-.#####`) | Key `(-priority, len(id), id)` for `PRM-` ids (pure); contract offers keep the code order. The parity corpus does not change (no PRM id ≥ 100000) | Unit `TestGroupRule`: PRM-99999 versus PRM-100000 → PRM-99999 applied (red) | `kamra/tex/pricing/promotions.py` (pure; run the parity suite) |
| LO-42 | (PR #7 review "for later") | Six 2C-2 nits:<br>(a) UI: the `markup_priority` help text, the MEMBER kind label.<br>(b) Backend:<br>• `revisions.archive`'s restore can re-create a markup tie;<br>• the tie check's `IFNULL(property)` locks every markup row;<br>• no test for a tie on a scheduled activation;<br>• the contract page's publish shares the rate limit | LOW | **FIXED in Part 2K-6** (IMPLEMENTATION_STATUS §6K6; no written review text exists, each nit verified STILL OPEN in code); was **not re-verified** | One by one | One per nit | (a) rates UI; (b) `commercial/revisions.py`, markup controller |
| LO-43 | PR #10 Kalanlar | A grid rate edit on a room with no current price in that period raises the engine's `Unsellable`, with no clear message | LOW | **FIXED in Part 2K-6** (IMPLEMENTATION_STATUS §6K6; verified STILL OPEN: the `Unsellable` came from `ratesplit.plan`, uncaught); was **not re-verified** (`kamra/tex/commercial/grid.py:163` catches `Unsellable` on one path) | Translate it to "room X has no price in this period; add one first" | `test_inventory.TestGridRates` | `commercial/grid.py` |
| LO-44 | PR #4 Kalanlar; PR #5 review ("TEX Payment Link spec lacks `modified`") | Regenerating the DocType JSON from the specs would move TEX Payment Link's `modified` back to 2026-09-24: the spec has no stamp, while its JSON says 2026-09-30 | LOW (tooling) | **FIXED in Part 2K-6** (IMPLEMENTATION_STATUS §6K6; card corrected: nine specs were behind, and TEX Payment Transaction's spec lacked `last_reverified_at`); was STILL OPEN, verified:<br>• `kamra/tex/devtools/doctype_specs.py:1093-1117` has no `extra={"modified": …}`.<br>• `doctype_gen.py:17, :89` (TIMESTAMP).<br>• `tex_payment_link.json` `modified` is 2026-09-30 00:00:57 | Add the stamp, plus a unit check that every spec's stamp is at least its JSON's `modified` | Unit test without a bench: compare spec and JSON (red for TEX Payment Link) | `devtools` |
| LO-45 | PR #4 Kalanlar (no `minusAmount` test); PR #4 review ("dialog 2-decimals") | `minusAmount` has no unit test, and the transfer dialog assumes 2 decimals (wrong for VND with 0 and KWD with 3) | LOW | **FIXED in Part 2K-6** (IMPLEMENTATION_STATUS §6K6); was STILL OPEN, verified:<br>• `frontend/src/tex/screens/payments/lib.ts:43` (`decimals = 2`).<br>• `detail/Actions.tsx:293`.<br>• no test under `frontend/tests` | Pass the currency's decimals; add unit tests | Node test for the VND and KWD cases (red) | payments UI |
| LO-46 | 2A review notes "for later" | The nullable-date guard does not cover third positional filters, the `isnull()` column-wide exemption, or doctypes known only at run time | LOW (test tooling) | **FIXED in Part 2K-6** (IMPLEMENTATION_STATUS §6K6; verified STILL OPEN); was **not re-verified** (the docstring of `kamra/tex/tests/unit/test_nullable_date_filters.py` lists what it does not cover) | Extend the AST guard | The guard's own probe tests | tests |
| LO-47 | 2A review notes ("loyalty hook catches nothing (2H)"); 2H did not take it | Any exception in the loyalty earning hook rolls back the reservation save it runs in: a confirmation, a payment callback or a cancellation | LOW (design; the Y-10 class) | **FIXED in Part 2K-2** (IMPLEMENTATION_STATUS §6K2); was STILL OPEN, verified: `kamra/tex/hooks.py:134-151` (`loyalty.on_reservation_change` is not guarded) | Decide whether to keep it (consistency) or run the earning (never the O-20 return) under a savepoint, log it, and add a status check "earnings missing" | Fault injection: a raising rule → booking confirmed, Error Log, WARN (red: rollback) | `tex/hooks.py`, `crm/loyalty.py` |
| LO-48 | PR #3 Remaining | `extras_repository` and `content` read snapshot quantities with `int(float(...))` | LOW (not money; CLAUDE.md says never float) | **FIXED in Part 2K-4** (IMPLEMENTATION_STATUS §6K4); was STILL OPEN, verified: `kamra/tex/availability/extras_repository.py:97`, `kamra/tex/services/content.py:139` | Decimal whole units, as `loyalty.extra_units` does | Unit: "2.000000" → 2; "2.5" → refused or explained | availability, `services/content.py` |
| LO-49 | PR #6 review nits | Five 2G-1 nits:<br>• the strip/trim whitespace sets differ;<br>• the widget does not unlock on the dialog's own close event;<br>• VoiceOver and ⌃⌥;<br>• "?" with Ctrl no longer opens help;<br>• the Turkish-F ı/ü fallback | LOW | **FIXED in Part 2K-5** (IMPLEMENTATION_STATUS §6K5); was not re-verified (no written review text exists beyond this row: PR #6 has no review comments), then each verified STILL OPEN in code: `booking/lib/analyticsIds.ts` vs `TEXBookingSite.validate`; `widget/index.ts` `wireModal`; `crs/lib/shortcuts.ts` (⌃⌥, `?`); `ui/keys.ts` `shortcutLetter` | One by one | One per nit | frontend |

### 1b. FIXED LATER / NOT REPRODUCIBLE

| Origin item | Status | Evidence at aac444a4 |
|---|---|---|
| PR #3 Remaining: Agent Action Log rows without a hotel readable across tenants (MED) | FIXED LATER, PR #8 NEW-8 (dff2030, p65) | `kamra/tex/security/perm.py:35` (Agent Action Log in `STRICT_DOCTYPES`); `kamra/agents_api.py:57-60` |
| 2A review: the hotel trail shows cost to a custom `settings.admin` profile | FIXED LATER, PR #8 round 1 (b22ef38) | `kamra/tex/api/admin.py:481-492`, :514 |
| 2A review: Y-12 PARTIAL (Custom DocPerm rows) | FIXED LATER, PR #3 round 1 (4d42222, p64) | p64 present; §6 Y-12 COMPLETE |
| PR #5 Remaining: static occupancy analysis counts infants | FIXED LATER, PR #7 O-2b (7c53651) and PR #10 0b (7664630) | §6C2, §6D1 |
| PR #5 review: the editor row flag ignores the plan's default policy; ladder and POLICY_CURRENCY texts | FIXED LATER, PR #7 (7c53651) | §6C2 O-2b |
| PR #6 Remaining: the O-30 follow-up (a changed price booked at once) | FIXED LATER, PR #8 (a92be0c) | §6I |
| 2G-1 review: O-29 gaps (focus jump, stale quote counters, summary error) | FIXED LATER, PR #8 (4bfeb94) | §6I |
| PR #7 review (MED `promo_group` text; catalog logged 16 times; `code_key` idempotency; `code_key` in modification; tie message) | FIXED LATER, PR #10 item 0 (530f4de, c5ca86d, 180f8a2, 62d2184, 4ea08b7) | §6D1 |
| PR #9 review: the guest change preview failed; deposit room priced 0; lease shorter than Sipay's worst case | FIXED LATER, PR #9 round 1 (5abe845, 5959b24, e62d48f) | §6E1 |
| PR #9 Kalanlar: a keyless `book` retried after step (a); the `retry_on_deadlock` docstring | FIXED LATER, PR #11 P1-8 e (84e3023) | `kamra/tex/services/txn.py:67-104` |
| PR #10 Kalanlar: `create_booking` locks its quotes in the caller's order | FIXED LATER, PR #15 (a8f6abe) | `services/booking.py:602` (`sorted(quote_ids)`) |
| PR #10 Kalanlar: withdraw's plain reads; NULL `effective_from` audited as scheduled; the quote endpoints not retried | FIXED LATER, PR #12 (7e4ccb2, 8a6f283) | `commercial/contracts.py:758`; `api/public.py:263, :288`; `api/crs.py:63, :73` |
| PR #11 Kalanlar: a restarted Pending charge skips `open_attempt` | FIXED LATER, PR #15 (eb2c533) | `payments/service.py:389-396` (`open_attempt` at :394) |
| 2E-2 review F1/F2: the re-verify job's order; half-written tries | FIXED LATER, PR #11 round 1 (22ce4f8, b9fcc70) | `payments/service.py:626-735` |
| Pre-2A review X1: no automatic re-verify of Pending iyzico/Sipay charges | FIXED LATER, PR #11 NEW-2 (7b4a16f) | `kamra/tex/scheduler.py:28` |
| 2H-1 review: `mature_and_expire` loses its savepoint after a deadlock | FIXED LATER, PR #14 item 0 (e54f9edc) | `crm/loyalty.py:289-323` (`undo_to`) |
| PR #13 Remaining: lock order between a changed stay and the daily job | FIXED LATER, PR #14 item 0 (e54f9edc), by reading only | The job commits matured rows before `settle`. `tex/hooks.py:141` (`require_live_guest`) locks the guest before the loyalty hook: guest, then ledger, everywhere |
| 2H-2 review: duplicate `loyalty._undo_to` | FIXED LATER, PR #14 (26956e08) | `txn.undo_to` is used |
| 2B review: P1-3 residual race; `after_refund` order and stale read; O-19 full-scan locking; NaN amounts | FIXED LATER, PR #4 rounds 1–2 (99cbf09, 0a7299b, 4d08a67, 3d90b48, c9aeb9e, d4ca730) | §6B |
| 2I review: a history leak finding; the test-directory allowlist silenced every rule | FIXED LATER, PR #8 (e14c5d8, 473362b) | `.gitleaksignore`, `.gitleaks.toml` |
| 2D-1 review: the flaky null-dates test; ADR-069 wording | FIXED LATER, PR #10 round 1 (73fb86b, 087e079) | §6D1 |
| **PR #16 Kalanlar: the legacy `kamra.api.cancel_reservation` path against the channel guard** | **NOT REPRODUCIBLE** | `kamra/api.py:2646-2653` `_do_cancel` calls `refuse_legacy_cancel`, which refuses any reservation with a `tex_booking` (`kamra/tex/legacy.py:331-339`; `locked_bill` :302-303). Channel bookings have `tex_booking`. A direct Desk or REST change to "Cancelled" is refused by `Reservation.validate_cancellation_path` (`kamra/kamra/doctype/reservation/reservation.py:159-169`) |

### 1c. Cross-references to the Stage 3 and 2Z cards (HANDOFF.md §2)

**Stage 3 (O-8 → G-55b → G-71 → G-70)**

Add-ons from this list:
- **LO-12**: the manage view's channel flags, in `api/public.py`.
- **LO-30**: optional; `PayLinkPage` is also edited by G-70's pay-link codes.

New or changed refusal texts that G-70 must give codes to, from batches A–C:
- "payment under review" (LO-05);
- "already processed" on a settled restart (LO-04; existing text);
- "room type no longer sold" (LO-03): coded ROOM_NOT_SOLD in Part 2K-3 (quote, booking, modification); G-70b gives it
  the catalogs' text;
- channel-booking refusals (LO-12, LO-13).

The Part 2 plan says G-70 "rewrites throw sites in `public.py`, `guest_changes.py` and `payments/service.py`, so it comes after all money-path edits". **Batches A, B and C must therefore merge before G-70b starts.** (HANDOFF.md §2 splits G-70: the small coded-refusal transport G-70a comes first, in batch 3A, and every new refusal written in A–C uses it; G-70b codes everything left.)

**2Z (release hygiene)**
- The NEW-4 bundle rebuild. It must come after batches A, B, C, E and F, which all carry frontend changes.
- The CI build-diff check.
- The Frappe upgrade and the pip-audit ignore lists (39 + 14 IDs).
- Pinning `payments` (pip-audit audits its develop branch; PR #8 Kalan).
- Switching OAuth dynamic client registration off (PR #11 note).
- Pinning the Semgrep rules.
- The docs refresh:
  - GO_LIVE_READINESS:
    - tracked booking sites served on their own host;
    - connection keys from before 09-23 rotated;
    - the outbox job (`bench migrate`);
    - hotels that sell pay-at-the-hotel need a Pay at Hotel rule (O-15);
    - at most one live FX policy per pair (O-11);
    - LO-08's worker setup.
  - DEV_ENVIRONMENT recipe gaps (PRs #6 and #8).
  - Two ADR-068 lines: live rows without a basket currency; booking-level exclusive promotions are now per room.
- The flaky `channels.spec.ts:127` (PRs #10 and #12).

### 1d. Not planned (informational, no action)
- PR #7 Kalan: contract offers have no save-time check of their own. O-1 already handles FX at pricing.
- PR #3: legacy PMS `housekeeping.escalate_overdue_tasks` escalates tasks with a NULL `due_by` (a reviewed ALLOWED entry; legacy code, hidden).
- PR #14 and PR #15: the accepted lock inversions of ADR-066 "Locks". They end in clean rollbacks and are retried.
- 2B review: `booking.at_stored_price`'s `stored is None` guard is dead code (`services/booking.py:284-291`).
- PR #7 review: the O-1 explanation order changes only when an unusable promotion is present.

## 2. Proposed follow-up batches

Every batch follows CLAUDE.md:
- a failing test first, one commit per item;
- money as `Decimal`;
- a patch in `patches.txt` for any schema change;
- a dated ADR addendum where a rule changes;
- an IMPLEMENTATION_STATUS §6x section.

The committed bundles are **not** regenerated in these batches; 2Z does that once.

**Order.** The binding order is HANDOFF.md §2 (one session, sequential: 3A → B → A → C → 3B → D → E → F/G → 2Z). A, B and C must be merged before Stage 3's G-70b; the notes below on parallel work apply only if several sessions run at once.
- **A (loyalty) and B (payments) can start now, in parallel.** Both edit `payments/service.py`, but in different functions: A touches `allocate`, B touches `start_payment`, `reverify` and `reverify_pending`. Merge one, then merge the base into the other (never rebase).
- **C can run beside them.** It edits `services/booking.py` (`channel_of`, `resend_confirmation`, `live_duplicate`), not `create_booking`, which O-8 will change. It edits `services/quoting.py` (`_stay_refusal`), which G-71 may also change; merge the base into whichever lands second.
- **D after B.** They share `payments/service.py` and the ops checks.
- **E after Stage 3 has merged.** G-70 edits `booking/lib/api.ts`, `Checkout.tsx` and the pay-link page. E must still come before 2Z.
- **F and G any time before 2Z.**
- **2Z last.**

### Batch A: points always come back as points (MED, 8 items; loyalty session)
- **Items:**
  - LO-01 (O-19b): the points' share of a lower price.
  - LO-02: channel bookings and points: the `redeem` guard, the `allocate` guard, and the return on a channel cancellation.
  - LO-06: find the burn row by the charge (staff transfer, guest replaced).
  - LO-23: the Action Required note for a revived hold whose points were given back.
  - LO-24: the stays tab marks expired holds.
  - LO-25: a negative balance is explained.
  - LO-26: verify reachability first; it may need no change.
  - LO-47: decide first; it is optional.
- **Files:**
  - `crm/loyalty.py`, `services/guest_changes.py` (`settle`, `_record_outside`), `distribution/channel_booking.py`, `payments/service.py` (`allocate` only), `crm/service.py`.
  - CRM UI with i18n ×6.
- **Tests:**
  - `test_loyalty_admin.TestPointsBack`, `test_self_service_money`, `test_distribution.TestChannelBookings`.
  - `test_crm_privacy` and `test_crm_segments`; unit `test_loyalty_lots`.
- **ADR:** an ADR-071 §4 addendum (lower price, channel cancellation, finding the burn).
- **Preconditions:** D-12 (default: loyalty is live). The default for LO-02 follows D-11/D-16: points never pay a channel booking, and a cancellation gives them back.

### Batch B: payment starts, reviews and the 5-minute group (MED, 8 items; money session)
- **Items:**
  - LO-04: a reused charge settled during (b) gets no new checkout. Optionally, audit a duplicate capture.
  - LO-05: no second payment during a fraud review; a reviewed charge is never superseded.
  - LO-07: `refund_queued` gets a budget and a limit, and runs last in the group.
  - LO-16: `_flag` uses a locking read.
  - LO-17: the overpaid check leaves out kept credits.
  - LO-19: staff re-verify releases its locks between tokens.
  - LO-21: tokenless iyzico charges no longer take places in a tick.
  - LO-18: a staff close for an unverifiable Pending charge, with a small payments UI change.
- **Files:** `payments/service.py`, `services/holds.py`, `services/late_payments.py`, `scheduler.py`, `ops/status.py`, `ops/checks.py`, `api/payments.py`, payments UI.
- **Tests:**
  - `test_hold_payment_race` (`TestNoLockHeldThroughTheGateway`, `TestIyzicoFraudReview`, `TestPaymentsVerifiedByTheJob`, `TestReconciliationStates`).
  - `test_system_status`; unit `test_system_checks`.
- **ADR:** ADR-062 and ADR-066 addenda.
- **Order:** before G-70b. Write LO-05's new refusal with G-70a's coded `Refusal`.

### Batch C: channels and disabled room types (MED, 5 items; money/distribution session)
- **Items:**
  - LO-03: ARI closes a disabled type, and disabling one queues an ARI sync. A quote of a pre-disable offer, and a staff modification into a disabled type, are refused.
  - LO-13: the channel's label in refusals and in the cancel dialog.
  - LO-11: `resend_confirmation` for a channel booking.
  - LO-09: the revival's duplicate check under a lock.
  - LO-15: tuple assertions in the p58 and p61 tests.
- **Files:**
  - `distribution/repository.py`, `kamra/tex/hooks.py`, `kamra/hooks.py`.
  - `services/quoting.py`, `services/modification.py`, `services/booking.py`, `api/crs.py`.
  - Reservations UI with i18n ×6; `test_patches.py`.
- **Tests:** `test_distribution`, `test_public_booking`, `test_commercial_flows` (modification), `test_hold_payment_race` (LO-09), `test_patches`.
- **ADR:** ADR-048 and ADR-039 addenda.
- **Order:**
  - Before G-70b: write the new "no longer sold" refusal with G-70a's coded `Refusal`.
  - Merge the base if `quoting.py` conflicts with G-71.
  - LO-12 (the guest manage view) goes to Stage 3 as an add-on.

### Batch D: operations, scale and staff-visible data (LOW, 8 items) — done in Part 2K-4 (§6K4; LO-37 deferred, D-13 = no)
- **Items:**
  - LO-08: the outbox gets its own queue or worker.
  - LO-10: a bounded `_claim` read.
  - LO-28: the audit-log hotel view filters payment and stay events.
  - LO-39: `fx_rates` shows who entered a rate only to holders of `fx.manual_rate` or `settings.admin`.
  - LO-37: the `fx_bridged` WARN for pairs on a MANUAL-mode policy.
  - LO-22: `last_reverified_at` (field and patch).
  - LO-20: gated-account audit spam.
  - LO-48: Decimal quantities.
- **Files:** `scheduler.py`, `kamra/hooks.py`, `deploy/*`, `connect/outbox.py`, `api/admin.py`, `api/policies.py`, `ops/checks.py`, `payments/service.py`, DocType JSON plus a patch, `availability/extras_repository.py`, `services/content.py`.
- **Order:** after B. Independent of Stage 3. Before the 2Z docs refresh, so GO_LIVE_READINESS describes the worker setup.

### Batch E: guest booking frontend (LOW, 7 items) — done in Part 2K-5 (§6K5)
- **Items:**
  - LO-30: the pay-link token stays out of the URL after the return, unless Stage 3 takes it.
  - LO-35: one deposit line per booking and policy.
  - LO-14: the checkout fallback offers a retry instead of a guessed method.
  - LO-32: O-30 compares with the last quote shown.
  - LO-33: the notice is focused on a phone.
  - LO-31: the widget's title follows a `site` change.
  - LO-49: the 2G-1 nits; verify first.
- **Files:** `frontend/src/booking/*`, `widget`.
- **Tests:** node unit tests; Playwright `booking`, `pay-link`, `widget`, `guest-session` (desktop and mobile).
- **Order:** after Stage 3's G-70, which edits `booking/lib/api.ts`, `Checkout.tsx` and the pay-link refusals. Before 2Z.

### Batch F: staff frontend (LOW, 6 items) — done in Part 2K-6 (§6K6)
- **Items:**
  - LO-34: the CRS hides "Due now" while the summary loads.
  - LO-38: the FX hint shows `bridged_from`.
  - LO-40: the occupancy ladder models the infants flag.
  - LO-45: currency decimals in the transfer dialog, and `minusAmount` tests.
  - LO-42(a): the `markup_priority` help text and the MEMBER label.
  - LO-27: the abandoned-list e2e test.
- **Files:** `frontend/src/tex/screens/{crs,reservations,rates,payments}`, `frontend/e2e`, i18n.
- **Order:** any time before 2Z; independent of Stage 3.

### Batch G: tests, guards, tooling and a pure-pricing nit (LOW, 7 items) — done in Part 2K-6 (§6K6)
- **Items:**
  - LO-46: gaps in the nullable-date guard.
  - LO-36: the concurrency cleanup also removes child rows.
  - LO-44: a `modified` stamp in the doctype specs, and a spec-versus-JSON check.
  - LO-29: masking child rows in p63 and `mask_version`.
  - LO-41: promotion tie order beyond PRM-99999. It is pure; run the parity suite.
  - LO-42(b): the backend nits from the 2C-2 review.
  - LO-43: the grid's `Unsellable` message.
- **Files:** tests, `devtools`, `patches/tex/p63` and `security/internals.py`, `pricing/promotions.py`, `commercial/revisions.py`, `commercial/grid.py`.
- **Order:** any time. LO-41 needs `test_main_parity` to stay byte for byte.

### Stage 3 add-on
- **LO-12**: the manage view's `can_cancel` and `can_change` are false for channel bookings, with a `CHANNEL_BOOKING` code. Ideally inside G-70, which already codes the manage and cancel refusals.
- **LO-30**: optional here instead of batch E.

## 3. CONDITIONAL: waiting for an owner decision or an external party (not planned)

| ID | Item (origin) | Decision needed | Default today / note |
|---|---|---|---|
| C-01 | No Show and points or fees:<br>• "No Show … do not give points back" (PR #14, §6H2);<br>• "A FIXED no-show amount is frozen … but no service charges no-shows" (PR #5) | Does a no-show forfeit burned points (as a fee keeps the points it took) or return them, and who charges the no-show fee? Also where a TEX no-show comes from:<br>• TEX sets none;<br>• the legacy night audit skips TEX stays (`kamra/folio.py:799-809`, `legacy_only`);<br>• Front Desk and Hotel Admin can switch Confirmed → No Show in Desk or REST (`kamra/reservation_state.py:40`; Reservation perms);<br>• inbound PMS events are G-69r | **Answered 2026-10-03 (2M, ADR-076): no return.** A no-show keeps the points the stay was paid with, as a fee does; a cancellation gives them back (O-20). Pinned by `test_c01_a_no_show_keeps_the_points_it_was_paid_with`. Who charges a no-show fee and where a no-show comes from stay with D-15 / G-69r |
| C-02 | D-9 follow-up (2B review) | Who may drop a Revenue Manager's manual price? Today an agent with `reservation.modify` can reprice (`reprice=1`) but cannot keep it (`override_amount` needs `price.override`): `services/modification.py:554-579` | **Answered 2026-10-03 (2M, ADR-076): only `price.override`.** Keeping the price set by hand or taking the change's price both need it; an agent is refused and the drawer sends them to a revenue manager |
| C-03 | D-17b (PR #13) | Should guests with only SMS or WhatsApp consent stay anonymous in the abandoned list? | **Answered 2026-10-03 (2M, ADR-076): no, show the phone.** Such a guest is listed with the phone and the channels they agreed to, never the e-mail; each contact follows its channel's consent. İYS registration is the hotel's side until C-10 |
| C-04 | G-57 membership signal (PR #7) | Members-only promotions stay refused until public and CRS search know the signed-in loyalty member. Product decision first, then the feature | **Answered 2026-10-03 (ADR-077): a member joined or stayed and earned points; web and call centre; "Member price" shown to a guest not signed in; sign-in by a one-time e-mail link.** 2N-1: membership, staff join / leave, members-only promotions live, the Call Center prices the caller as a member, a member's price books for a member only. 2N-2: the web |
| C-05 | D-13 / D-4: O-6 hotel-local time for UTC+7 hotels (also the DST remark in PR #9's review); VND for Cam Ranh (PR #12: use a MANUAL-mode FX policy) | Do Cam Ranh and Phuket go live in wave 1? **Answered no (2026-10-02)** | Documented limitation until they are planned; LO-37 is deferred with it |
| C-06 | D-14, the migration / pre-upgrade package (Part 2 plan: not in Part 2). **Answered 2026-10-03: no.** No Kamra or TEX pilot database with data to keep exists; every hotel starts from a fresh install, so none of the items below apply (closed in 2L). The current systems' data reaches TEX by import at cut-over, a separate go-live item | Will an existing Kamra or pilot database be upgraded? If yes, a pre-upgrade package. If no, these do not apply:<br>• O-34, O-35, O-36, O-39 and P1-12, including the p56 edge where a site upgraded after V2's start re-selects V3 (2A review);<br>• Loyalty payments already in reconciliation, which staff now allocate (PR #14);<br>• points the old expiry job took, not restored (PR #13);<br>• no `amount_due_now` backfill for pending manual-price or multi-room bookings (PR #9, 2B review);<br>• drafts broken by the old grid code (PR #10);<br>• Deleted Document rows holding a plain `api_key` from 22–23 Sep, plus key rotation (PR #8) | Fresh installs never run these |
| C-07 | D-15 / G-69r | Which PMS runs each go-live hotel? This settles the SMS and WhatsApp providers, the vendor PMS and inbound PMS events, including no-show and check-in/out | — |
| C-08 | G-41r allotment × channel (Part 2 plan: not in Part 2) | Are channel-scoped allotments needed, beyond a contract per channel? | Not needed (nothing is oversold) |
| C-09 | G-54 surcharges by length of stay or arrival day | Only if a live contract needs them | A rate-plan workaround exists |
| C-10 | G-64 CRM campaigns | Legal basis and İYS brand code (§5a), messaging adapters | Segment export in the meantime |
| C-11 | Product scope or priority, no decision needed now: G-40, G-42, G-75, G-80, G-63; G-44 modes; G-58 bundles (its doc row goes to 2Z); G-59; G-66 redemption depth; G-70 staff side and G-71 performance budgets; G-82; the G-97 permlevel redesign | Prioritise after go-live | — |
| C-12 | Folding promotion codes such as ŞEKER/SEKER (PR #7 review) | Should Turkish letters other than İ/ı (Ş, Ğ, Ü, Ö, Ç) be folded in `code_key`? | **Answered 2026-10-03 (2M, ADR-076): yes, fold them.** Ş, Ğ, Ü, Ö, Ç are S, G, U, O, C in `code_key` and the CRS input; ŞEKER and SEKER are one code |
| C-13 | D-12: is loyalty live at go-live? | Sets the priority of batch A | Default: yes, do all loyalty work |
| C-14 | Channel-manager go-live (§5a: provider credentials and certification) | Sets the priority of LO-02 and LO-03's ARI part | — |
| C-15 | External §5a items:<br>• iyzico and Sipay capture time (K-2 / B4 / D3 PARTIAL, §5);<br>• NestPay's order query (LO-18's real fix);<br>• Sipay refund and field names;<br>• SECURITY.md contact and an external pen test;<br>• SMTP, backups, staging | Owner, banks and IT | — |
| C-16 | Stays sold before Y-3/Y-4 are repriced under today's terms when modified (PR #9 breaking notes, "the owner's Y-4 note") | Already accepted by the owner | No action |
