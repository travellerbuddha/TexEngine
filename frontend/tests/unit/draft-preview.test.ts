// Unit tests for the live draft preview's request policy (PRICING_WORKSPACE_UX.md §3.14, slice S8):
// which calls each viewer makes, the stored publish report, the validation debounce and the
// single validation in flight. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import {
  latestOnly,
  matrixRequest,
  MATRIX_DEBOUNCE_MS,
  previewMode,
  storedIssues,
  validateDelay,
  VALIDATE_DEBOUNCE_MAX_MS,
  VALIDATE_DEBOUNCE_MS,
  validationRequest,
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
