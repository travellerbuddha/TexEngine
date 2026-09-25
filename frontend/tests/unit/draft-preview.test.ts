// Unit tests for the live draft preview's request policy (PRICING_WORKSPACE_UX.md §3.14, slice S8):
// which calls each viewer makes, the stored publish report, the validation debounce and the
// single validation in flight. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import {
  alreadyChecked,
  callState,
  isTooLarge,
  latestOnly,
  matrixRequest,
  MATRIX_DEBOUNCE_MS,
  overlayFits,
  overlayRows,
  previewKeys,
  previewMode,
  previewSource,
  pricesKey,
  resolvedStatus,
  sampleKey,
  storedIssues,
  validateDelay,
  VALIDATE_DEBOUNCE_MAX_MS,
  VALIDATE_DEBOUNCE_MS,
  validationRequest,
  type KeyInput,
} from "../../src/tex/screens/rates/workspace/draftPreview.ts"

test("the mode follows the server's flags: overlay for an editable draft, saved for other cost viewers, catalogue otherwise", () => {
  assert.equal(previewMode({ editable: true }), "overlay")
  assert.equal(previewMode({ editable: false }), "saved")
  assert.equal(previewMode({ editable: false, cost_hidden: false }), "saved")
  assert.equal(previewMode({ editable: false, cost_hidden: true }), "catalogue")
  // an agent's catalogue answer never carries editable: true; if it did, no cost call is made
  assert.equal(previewMode({ editable: true, cost_hidden: true }), "catalogue")
})

test("overlay: price_matrix is a POST with the unsaved payload, validation too", () => {
  const data = { rooms: [{ room_type: "STD", _key: "k1" }] }
  assert.deepEqual(matrixRequest("overlay", { version: "V-1", data }), { args: { version: "V-1", data }, post: true })
  assert.deepEqual(
    matrixRequest("overlay", { version: "V-1", data, parties: [{ adults: 2, children: ["CHB"] }], partyRoom: "STD" }),
    { args: { version: "V-1", data, parties: [{ adults: 2, children: ["CHB"] }], party_room: "STD" }, post: true },
  )
  assert.deepEqual(validationRequest("overlay", { version: "V-1", data }), { args: { name: "V-1", data }, post: true })
})

test("saved: a GET without data, and never a validation", () => {
  assert.deepEqual(matrixRequest("saved", { version: "V-1", data: { rooms: [] } }), { args: { version: "V-1" }, post: false })
  assert.equal(validationRequest("saved", { version: "V-1", data: { rooms: [] } }), null)
})

test("sample parties go with the saved draft only when its rooms hold the party room (S11)", () => {
  const parties = [{ adults: 2, children: ["CHB"] }]
  // the saved draft asked for by name (clean, over the overlay's cap) or a published version: a
  // room added since the last save is not a room of the answer, and price_matrix would refuse
  // the whole call for it; the ladder then shows no total for that room instead of losing the matrix
  assert.deepEqual(matrixRequest("overlay", { version: "V-1", source: "saved", parties, partyRoom: "SUP", savedRooms: ["STD"] }), { args: { version: "V-1" }, post: false })
  assert.deepEqual(matrixRequest("overlay", { version: "V-1", source: "saved", parties, partyRoom: "STD", savedRooms: ["STD"] }), {
    args: { version: "V-1", parties, party_room: "STD" },
    post: false,
  })
  assert.deepEqual(matrixRequest("saved", { version: "V-1", parties, partyRoom: "SUP", savedRooms: ["STD", "DLX"] }), { args: { version: "V-1" }, post: false })
  // the overlay prices what is on screen: its rooms are the caller's to check
  assert.deepEqual(matrixRequest("overlay", { version: "V-1", data: {}, parties, partyRoom: "SUP", savedRooms: ["STD"] }), {
    args: { version: "V-1", data: {}, parties, party_room: "SUP" },
    post: true,
  })
})

test("catalogue: no request at all", () => {
  assert.equal(matrixRequest("catalogue", { version: "V-1", data: {} }), null)
  assert.equal(validationRequest("catalogue", { version: "V-1", data: {} }), null)
})

test("parties without a room are not sent (the server would refuse them)", () => {
  assert.deepEqual(matrixRequest("saved", { version: "V-1", parties: [{ adults: 2, children: [] }] }), { args: { version: "V-1" }, post: false })
  assert.deepEqual(matrixRequest("saved", { version: "V-1", parties: [], partyRoom: "STD" }), { args: { version: "V-1" }, post: false })
})

test("the report stored at publish: a list of issues (as the server stores it), or an object with issues", () => {
  const issues = [{ level: "WARNING", code: "NO_CHILD_RULE", message: "STD 2A+1C [CHB]: no rule", ref: { room_type: "STD" } }]
  assert.deepEqual(storedIssues(issues), issues)
  assert.deepEqual(storedIssues({ ok: true, issues }), issues)
  assert.deepEqual(storedIssues([]), [])
  assert.equal(storedIssues(null), undefined)
  assert.equal(storedIssues(undefined), undefined)
  assert.equal(storedIssues(0), undefined)
  assert.equal(storedIssues("[]"), undefined)
  // anything that is not an issue is left out rather than shown half
  assert.deepEqual(storedIssues([issues[0], { code: 3 }, null]), issues)
})

test("debounces: 300 ms for the matrix; validation waits at least 1.2 s and as long as the last one took, at most 10 s", () => {
  assert.equal(MATRIX_DEBOUNCE_MS, 300)
  assert.equal(VALIDATE_DEBOUNCE_MS, 1200)
  assert.equal(validateDelay(null), 1200)
  assert.equal(validateDelay(undefined), 1200)
  assert.equal(validateDelay(80), 1200)
  assert.equal(validateDelay(2100.4), 2100)
  assert.equal(validateDelay(9800), 9800)
  assert.equal(validateDelay(60_000), VALIDATE_DEBOUNCE_MAX_MS)
  assert.equal(VALIDATE_DEBOUNCE_MAX_MS, 10_000)
  assert.equal(validateDelay(Number.NaN), 1200)
})

/** A run whose calls finish when the test says so. */
function controlled() {
  const calls: { key: string; signal: AbortSignal; finish: (ok?: boolean) => void }[] = []
  let inFlight = 0
  let maxInFlight = 0
  const run = (job: { key: string }, signal: AbortSignal) =>
    new Promise<void>((resolve, reject) => {
      inFlight += 1
      maxInFlight = Math.max(maxInFlight, inFlight)
      calls.push({
        key: job.key,
        signal,
        finish: (ok = true) => {
          inFlight -= 1
          if (ok) resolve()
          else reject(new Error("417"))
        },
      })
    })
  return { calls, run, max: () => maxInFlight }
}

const tick = () => new Promise((r) => setTimeout(r, 0))

test("one validation in flight: what is asked meanwhile waits, and only the newest", async () => {
  const c = controlled()
  const f = latestOnly(c.run)
  f.want({ key: "a" })
  assert.deepEqual(c.calls.map((x) => x.key), ["a"])
  assert.equal(f.busy(), true)
  f.want({ key: "b" })
  f.want({ key: "c" })
  assert.equal(c.calls.length, 1, "nothing starts while one runs")
  assert.equal(f.waiting(), "c")
  c.calls[0].finish()
  await tick()
  assert.deepEqual(c.calls.map((x) => x.key), ["a", "c"], "b was replaced by c before it started")
  c.calls[1].finish()
  await tick()
  assert.equal(f.busy(), false)
  assert.equal(c.max(), 1)
})

test("asking again for what is running queues nothing; asking for it after something else drops the other", async () => {
  const c = controlled()
  const f = latestOnly(c.run)
  f.want({ key: "a" })
  f.want({ key: "a" })
  assert.equal(f.waiting(), null)
  f.want({ key: "b" })
  f.want({ key: "a" })
  assert.equal(f.waiting(), null, "back to the state being checked: nothing more to check")
  c.calls[0].finish()
  await tick()
  assert.deepEqual(c.calls.map((x) => x.key), ["a"])
})

test("a refused validation still frees the flight for the next", async () => {
  const c = controlled()
  const f = latestOnly(c.run)
  f.want({ key: "a" })
  f.want({ key: "b" })
  c.calls[0].finish(false)
  await tick()
  assert.deepEqual(c.calls.map((x) => x.key), ["a", "b"])
  c.calls[1].finish()
  await tick()
  assert.equal(f.busy(), false)
})

test("cancel aborts the running call and drops the waiting one; the flight can be used again", async () => {
  const c = controlled()
  const f = latestOnly(c.run)
  f.want({ key: "a" })
  f.want({ key: "b" })
  f.cancel()
  assert.equal(c.calls[0].signal.aborted, true)
  assert.equal(f.waiting(), null)
  c.calls[0].finish(false)
  await tick()
  assert.equal(c.calls.length, 1, "the dropped job never starts")
  assert.equal(f.busy(), false)
  f.want({ key: "d" })
  assert.deepEqual(c.calls.map((x) => x.key), ["a", "d"])
  assert.equal(c.calls[1].signal.aborted, false)
})

test("a cancelled call that finishes late does not start what was asked after the cancel twice", async () => {
  const c = controlled()
  const f = latestOnly(c.run)
  f.want({ key: "a" })
  f.cancel()
  f.want({ key: "b" })
  assert.deepEqual(c.calls.map((x) => x.key), ["a", "b"], "after a cancel the next call starts at once")
  c.calls[0].finish(false)
  await tick()
  assert.equal(c.calls.length, 2)
  assert.equal(f.busy(), true, "b is still running")
  c.calls[1].finish()
  await tick()
  assert.equal(f.busy(), false)
})

// ─── review follow-up: the saved draft by name (§3.15), the row cap and the call state ──────────

test("the Check button and a clean state ask about the saved draft by name, with no data (§3.15)", () => {
  const data = { rooms: [{ room_type: "STD", _key: "k1" }] }
  // clean: what is on screen is the saved draft, so no payload (and no overlay row cap)
  const clean = previewSource("overlay", { clean: true, rows: 3 })
  assert.equal(clean, "saved")
  assert.deepEqual(matrixRequest("overlay", { version: "V-1", data, source: clean! }), { args: { version: "V-1" }, post: false })
  assert.deepEqual(validationRequest("overlay", { version: "V-1", data, source: clean! }), { args: { name: "V-1" }, post: false })
  // the Check button (validateNow) validates the saved draft, whatever the editor shows
  const now = previewSource("overlay", { clean: false, rows: 3, now: true })
  assert.equal(now, "saved")
  assert.deepEqual(validationRequest("overlay", { version: "V-1", data, source: now! }), { args: { name: "V-1" }, post: false })
  // unsaved changes the overlay takes: the payload, as before
  const dirty = previewSource("overlay", { clean: false, rows: 3 })
  assert.equal(dirty, "overlay")
  assert.deepEqual(matrixRequest("overlay", { version: "V-1", data, source: dirty! }), { args: { version: "V-1", data }, post: true })
  assert.deepEqual(validationRequest("overlay", { version: "V-1", data, source: dirty! }), { args: { name: "V-1", data }, post: true })
  // the other modes are unchanged: saved never validates, the catalogue asks nothing
  assert.equal(previewSource("saved", { clean: false, rows: 3 }), "saved")
  assert.equal(validationRequest("saved", { version: "V-1", source: "saved" }), null)
  assert.equal(previewSource("catalogue", { clean: true, rows: 3 }), null)
})

test("above the overlay's row cap the saved draft is asked by name; the server's typed refusal counts too", () => {
  assert.equal(overlayRows({ rooms: [1, 2], periods: [1], period_rates: [], boards: [1, 2, 3] }), 6)
  assert.equal(overlayRows({}), 0)
  // the cap the server reports (get_version overlay_max_rows): up to it, the overlay
  assert.equal(overlayFits({ rows: 5000, maxRows: 5000 }), true)
  assert.equal(overlayFits({ rows: 5001, maxRows: 5000 }), false)
  assert.equal(overlayFits({ rows: 6200 }), true, "no cap reported: the server decides")
  assert.equal(previewSource("overlay", { clean: false, rows: 6200, maxRows: 5000 }), "saved")
  // a refusal (OverlayTooLarge) of a state of n rows: no overlay again until it has fewer
  assert.equal(overlayFits({ rows: 6200, refusedRows: 6200 }), false)
  assert.equal(overlayFits({ rows: 6300, refusedRows: 6200 }), false)
  assert.equal(overlayFits({ rows: 4000, refusedRows: 6200 }), true)
  assert.equal(previewSource("overlay", { clean: false, rows: 6201, refusedRows: 6200 }), "saved")
  assert.equal(isTooLarge({ type: "OverlayTooLarge", status: 417 }), true)
  assert.equal(isTooLarge({ type: "ValidationError", status: 417 }), false, "a blank value is not a row cap")
  assert.equal(isTooLarge(undefined), false)
  assert.equal(isTooLarge(new Error("OverlayTooLarge")), false)
})

const K: KeyInput = { version: "V-1", modified: "m1", tick: 0, vtick: 0, parties: "", rowKeys: "a,b", key: "fp1", fits: true }

test("answer keys: the content on screen while the overlay takes it, the saved revision when it does not", () => {
  const k = previewKeys("overlay", K)
  assert.ok(k.matrix && k.valid)
  // a save of what is on screen (a new revision, same content and row keys) keeps the answers
  assert.deepEqual(previewKeys("overlay", { ...K, modified: "m2" }), k)
  // an edit, a reload (new row keys), a refresh or the Check button asks again
  assert.notEqual(previewKeys("overlay", { ...K, key: "fp2" }).matrix, k.matrix)
  assert.notEqual(previewKeys("overlay", { ...K, rowKeys: "c,d" }).valid, k.valid)
  assert.notEqual(previewKeys("overlay", { ...K, tick: 1 }).matrix, k.matrix)
  assert.notEqual(previewKeys("overlay", { ...K, vtick: 1 }).valid, k.valid)
  assert.equal(previewKeys("overlay", { ...K, vtick: 1 }).matrix, k.matrix, "Check does not re-price")
  // above the cap the answers are the saved draft's: edits do not ask again, a save does
  const big = previewKeys("overlay", { ...K, fits: false })
  assert.deepEqual(previewKeys("overlay", { ...K, fits: false, key: "fp2", rowKeys: "c,d" }), big)
  assert.notEqual(previewKeys("overlay", { ...K, fits: false, modified: "m2" }).matrix, big.matrix)
  assert.notEqual(previewKeys("overlay", { ...K, fits: false, modified: "m2" }).valid, big.valid)
  assert.notEqual(previewKeys("overlay", { ...K, fits: false, vtick: 1 }).valid, big.valid)
  assert.notEqual(big.matrix, k.matrix)
  // saved mode: one matrix per revision, never a validation; the catalogue asks nothing
  const saved = previewKeys("saved", K)
  assert.equal(saved.valid, "")
  assert.deepEqual(previewKeys("saved", { ...K, key: "fp2" }), saved)
  assert.notEqual(previewKeys("saved", { ...K, modified: "m2" }).matrix, saved.matrix)
  assert.deepEqual(previewKeys("catalogue", K), { matrix: "", valid: "" })
})

test("the call state: a refused call for the current key is failed, not busy", () => {
  // the finding: an older answer, the current key refused, nothing running
  assert.equal(callState({ key: "k2", answered: "k1", failed: "k2", running: false }), "failed")
  assert.equal(callState({ key: "k2", failed: "k2", running: false }), "failed")
  // waiting for the debounce, or a call in flight: busy
  assert.equal(callState({ key: "k2", answered: "k1", running: false }), "busy")
  assert.equal(callState({ key: "k2", answered: "k1", running: true }), "busy")
  assert.equal(callState({ key: "k2", answered: "k1", failed: "k2", running: true }), "busy")
  // an older failure says nothing about the current key
  assert.equal(callState({ key: "k3", answered: "k1", failed: "k2", running: false }), "busy")
  assert.equal(callState({ key: "k2", answered: "k2", failed: "k1", running: false }), "ready")
  // nothing asked (catalogue, a published version's issues)
  assert.equal(callState({ key: "", running: false }), "ready")
})

test("a state already checked is not checked again, unless a check of another state is in flight", () => {
  assert.equal(alreadyChecked("k0", "k0", false), true)
  assert.equal(alreadyChecked("k1", "k0", false), false)
  assert.equal(alreadyChecked("k0", null, false), false)
  // back to k0 while k1 is checked: k1's answer would replace k0's, so k0 is asked again after it
  assert.equal(alreadyChecked("k0", "k0", true), false)
})

test("sample parties: an answer is known by the parties it priced, as sent (S11 review)", () => {
  const party = [{ adults: 2, children: ["CHB"] }]
  const sent = matrixRequest("overlay", { version: "V-1", data: {}, parties: party, partyRoom: "STD" })
  assert.ok(sent)
  const key = sampleKey(sent.args.parties, sent.args.party_room)
  assert.notEqual(key, "")
  // the ladder's chosen party, built afresh, has the same key; another party or room does not
  assert.equal(sampleKey([{ adults: 2, children: ["CHB"] }], "STD"), key)
  assert.equal(sampleKey([{ children: ["CHB"], adults: 2 }], "STD"), key, "field order does not matter")
  assert.notEqual(sampleKey([{ adults: 2, children: [] }], "STD"), key)
  assert.notEqual(sampleKey([{ adults: 2, children: ["CHA"] }], "STD"), key)
  assert.notEqual(sampleKey(party, "SUP"), key)
  // nothing sent (no party, or a room the saved draft does not hold): no key
  const none = matrixRequest("saved", { version: "V-1", parties: party, partyRoom: "SUP", savedRooms: ["STD"] })
  assert.equal(sampleKey(none?.args.parties, none?.args.party_room), "")
  assert.equal(sampleKey(undefined, "STD"), "")
  assert.equal(sampleKey([], "STD"), "")
  assert.equal(sampleKey(party, ""), "")
})

test("the rooms' prices of an answer do not depend on the sample party (S11 review)", () => {
  const a = { ...K, parties: sampleKey([{ adults: 2, children: [] }], "STD") }
  const b = { ...K, parties: sampleKey([{ adults: 3, children: [] }], "STD") }
  for (const mode of ["overlay", "saved"] as const) {
    for (const fits of [true, false]) {
      // another party asks again…
      assert.notEqual(previewKeys(mode, { ...a, fits }).matrix, previewKeys(mode, { ...b, fits }).matrix, `${mode} ${fits}`)
      // …but the rooms' prices it answers are those of the same state
      assert.equal(pricesKey(mode, { ...a, fits }), pricesKey(mode, { ...b, fits }), `${mode} ${fits}`)
      assert.equal(pricesKey(mode, { ...a, fits }), pricesKey(mode, { ...K, fits }), "no party")
    }
  }
  assert.notEqual(pricesKey("overlay", { ...a, key: "fp2" }), pricesKey("overlay", a), "an edit")
  assert.notEqual(pricesKey("overlay", { ...a, tick: 1 }), pricesKey("overlay", a), "a refresh")
  assert.notEqual(pricesKey("saved", { ...a, modified: "m2" }), pricesKey("saved", a), "a save")
  assert.equal(pricesKey("catalogue", a), "")
})

test("the resolved prices are updating only while this state's answer is on its way (S16 re-review)", () => {
  const at = { key: "k2", forKey: "k1", stale: true, savedOnly: false }
  assert.equal(resolvedStatus({ ...at, matrixState: "busy" }), "updating")
  // the call failed: an older state's prices, and nothing on its way
  assert.equal(resolvedStatus({ ...at, matrixState: "failed" }), "failed")
  // above the overlay's cap with unsaved changes: the saved draft's prices until a save
  assert.equal(resolvedStatus({ ...at, forKey: "base", matrixState: "ready", savedOnly: true }), "as_saved")
  assert.equal(resolvedStatus({ ...at, forKey: "base", matrixState: "busy", savedOnly: true }), "updating")
  // this state's prices, a refetch for another sample party or a failed refetch of the same state
  for (const matrixState of ["ready", "busy", "failed"] as const) assert.equal(resolvedStatus({ key: "k2", forKey: "k2", stale: false, savedOnly: false, matrixState }), "current")
  // no answer yet
  assert.equal(resolvedStatus({ key: "k1", stale: true, savedOnly: false, matrixState: "busy" }), "updating")
})
