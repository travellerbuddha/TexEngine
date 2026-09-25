// The keys the workspace builds at run time (S16 review; workspace/stateKeys.ts): every cell state of
// the three grids and every entry error code is in all six rates catalogues. The TEX i18n check scans
// literal keys only, so "rates.occ.state.cost_hidden" was missing and a hidden sample party read
// "rates.occ.state.cost_hidden" in every language. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { LADDER_CELL_STATES, SH_ERROR_CODES, stateKeys } from "../../src/tex/screens/rates/workspace/stateKeys.ts"
import { STALE_STATE } from "../../src/tex/screens/rates/workspace/cellTone.ts"

const LANGS = ["en", "tr", "de", "ru", "ro", "pl"]
const catalogue = (lang: string): Record<string, unknown> => JSON.parse(readFileSync(new URL(`../../src/tex/i18n/locales/rates/${lang}.json`, import.meta.url), "utf8"))

test("every state and error key the grids build is in all six catalogues", () => {
  const keys = stateKeys()
  assert.ok(keys.length > 50)
  for (const lang of LANGS) {
    const cat = catalogue(lang)
    const missing = keys.filter((k) => typeof cat[k] !== "string" || !(cat[k] as string).trim())
    assert.deepEqual(missing, [], `${lang}: missing ${missing.join(", ")}`)
  }
})

test("a hidden sample party's total has its own state", () => {
  assert.ok(LADDER_CELL_STATES.includes("cost_hidden"))
})

test("the grids' state literals are the listed ones", () => {
  // each grid types its View's state from these lists; a literal outside them fails to compile, and
  // this checks the reverse: no list holds a state no grid uses any more
  const read = (f: string) => readFileSync(new URL(`../../src/tex/screens/rates/workspace/${f}`, import.meta.url), "utf8")
  const used = (text: string) => new Set([...text.matchAll(/state: (?:[^"\n]*\? )?"([a-z_-]+)"(?: : "([a-z_-]+)")?/g)].flatMap((m) => [m[1], m[2]]).filter(Boolean))
  const ladder = used(read("OccupancyLadder.tsx"))
  for (const s of LADDER_CELL_STATES) assert.ok(ladder.has(s), `ladder state ${s} is not used`)
})

test("the keys picked from a map are listed too: a resolved value's stale state, the ladder's CARD refusal (S16 re-review 3)", () => {
  const keys = new Set(stateKeys())
  for (const k of Object.values(STALE_STATE)) assert.ok(keys.has(k), k)
  assert.ok(keys.has("rates.ws.cell.failed_state") && keys.has("rates.ws.cell.saved_state"))
  assert.ok((SH_ERROR_CODES as readonly string[]).includes("CARD"))
})
