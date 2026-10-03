// 2K-6 review S2: the server keeps each currency's money in its minor units (kamra/tex/money.py MINOR_UNITS,
// anything missing: 2) and sends amounts so. Where the screens' table gave a currency fewer decimals (CLP and
// ISK: 0, the server 2), a payments dialog (LO-45) refused the server's own "15000.00" and its input could not
// edit it. Both apps' tables say what the server says. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8")

function serverUnits(): Record<string, number> {
  const block = /MINOR_UNITS[^{]*\{([^}]*)\}/.exec(read("../../../kamra/tex/money.py"))?.[1] ?? ""
  return Object.fromEntries([...block.matchAll(/"([A-Z]{3})":\s*(\d)/g)].map((m) => [m[1], Number(m[2])]))
}

function screenUnits(path: string): Record<string, number> {
  const block = /const MINOR: Record<string, number> = \{([^}]*)\}/.exec(read(path))?.[1] ?? ""
  return Object.fromEntries([...block.matchAll(/([A-Z]{3}):\s*(\d)/g)].map((m) => [m[1], Number(m[2])]))
}

const server = serverUnits()
const units = (table: Record<string, number>, ccy: string) => table[ccy] ?? 2

test("the server's table is read", () => {
  assert.equal(server.EUR, 2)
  assert.equal(server.VND, 0)
  assert.equal(server.KWD, 3)
})

for (const [app, path] of [
  ["staff", "../../src/tex/lib/format.ts"],
  ["guest", "../../src/booking/lib/format.ts"],
] as const) {
  test(`the ${app} screens give every currency the server's decimals`, () => {
    const table = screenUnits(path)
    assert.ok(Object.keys(table).length > 0, `${path} has its MINOR table`)
    for (const ccy of new Set([...Object.keys(table), ...Object.keys(server)])) {
      assert.equal(units(table, ccy), units(server, ccy), `${app} ${ccy}`)
    }
  })
}
