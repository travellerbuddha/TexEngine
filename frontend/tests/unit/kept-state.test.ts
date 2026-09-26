// The workspace input kept above the section switch (S16 review; workspace/keptState.ts): what the
// version editor asks before the tab closes. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { KEPT, keptInput, type KeptStore } from "../../src/tex/screens/rates/workspace/keptState.ts"

test("error drafts of any grid and an open combination builder are input not in the version yet", () => {
  const store: KeptStore = new Map()
  assert.equal(keptInput(store), false)
  assert.equal(keptInput(null), false)
  store.set(KEPT.drafts("matrix"), {})
  store.set(KEPT.drafts("ladder", "STD"), {})
  store.set(KEPT.comboOpen, null)
  store.set(KEPT.comboDraft, { adults: 2 })
  assert.equal(keptInput(store), false, "empty drafts, a closed builder and a stale builder draft are nothing")
  store.set(KEPT.drafts("ladder", "STD"), { "adult3|P2": { text: "abc", code: "UNREADABLE" } })
  assert.equal(keptInput(store), true)
  store.set(KEPT.drafts("ladder", "STD"), {})
  store.set(KEPT.comboOpen, { mode: "add" })
  assert.equal(keptInput(store), true)
  store.set(KEPT.comboOpen, null)
  store.set(KEPT.drafts("boards"), { "HB|": { text: "x" } })
  assert.equal(keptInput(store), true)
  // the ladder's drafts are kept per rooms scope
  assert.notEqual(KEPT.drafts("ladder", "STD"), KEPT.drafts("ladder", ""))
})
