// A draft save refused because someone changed the draft after the editor read it (O-10, ADR-069):
// the editor tells the user to reload instead of showing a generic save error. Run with
// `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { isDraftChanged } from "../../src/tex/screens/rates/lib/draftToken.ts"

test("the server's DraftChanged is a changed draft; anything else is not", () => {
  assert.equal(isDraftChanged({ type: "DraftChanged", status: 417, message: "changed by Ada" }), true)
  for (const e of [
    { type: "ValidationError", status: 417 },
    { type: "TimestampMismatchError", status: 417 },
    new Error("network"),
    null,
    undefined,
    "DraftChanged",
  ])
    assert.equal(isDraftChanged(e), false)
})
