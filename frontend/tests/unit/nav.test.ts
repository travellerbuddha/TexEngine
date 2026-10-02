// The side navigation grouped by the work staff come to do (UX revision 2026-10; shell/nav.ts):
// every route stays where it was, and an area is current only on its own pages, so Contracts is
// not current on a promotion's page although both live under /tex/rates. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { areaEntry, areaHome, childActive, childVisible, inArea, NAV, NAV_GROUPS, ruleVisible } from "../../src/tex/shell/nav.ts"

const area = (id: string) => {
  const n = NAV.find((x) => x.id === id)
  assert.ok(n, id)
  return n
}

test("every area sits in a known group, and daily work comes first", () => {
  const groups = new Set(NAV_GROUPS.map((g) => g.id))
  for (const n of NAV) assert.ok(groups.has(n.group), n.id)
  assert.equal(NAV_GROUPS[0].id, "sell")
  assert.deepEqual(
    NAV.filter((n) => n.group === "sell").map((n) => n.id),
    ["dashboard", "reservations", "crs", "call-center", "inventory", "promotions"],
  )
})

test("Contracts is current on contracts and their versions, never on a promotion or a selling rule", () => {
  const contracts = area("rates")
  for (const p of ["/tex/rates", "/tex/rates/", "/tex/rates/contracts/C-1", "/tex/rates/contracts/C-1/versions/V-2"]) assert.equal(areaHome(contracts, p), true, p)
  for (const p of ["/tex/rates/policies/promotions", "/tex/rates/policies/markup/M-1", "/tex/rates/restrictions", "/tex/rates/fx-rates"])
    assert.equal(areaHome(contracts, p), false, p)
  assert.equal(areaHome(area("promotions"), "/tex/rates/policies/promotions/PR-1"), true)
  assert.equal(areaHome(area("promotions"), "/tex/rates/policies/markup"), false)
})

test("the selling rules open on every rule kind, the currency rates and the markets", () => {
  const rules = area("rules")
  const kids = rules.children ?? []
  for (const p of ["/tex/rates/policies/markup", "/tex/rates/policies/cancellation/C-9", "/tex/rates/fx-rates", "/tex/settings/markets"])
    assert.equal(inArea(rules, kids, p), true, p)
  assert.equal(inArea(rules, kids, "/tex/rates/policies/promotions"), false)
  assert.equal(kids.some((c) => c.to.endsWith("/promotions")), false)
})

test("markups and contract formulas are cost: without price.view_cost the selling rules open on the first rule one may read", () => {
  const rules = area("rules")
  const kids = rules.children ?? []
  const agent = (cap: string) => cap === "price.view"
  const revenue = (cap: string) => cap === "price.view" || cap === "price.view_cost"
  const shown = (can: (cap: string) => boolean) => kids.filter((c) => childVisible(c, can))
  assert.deepEqual(
    shown(agent).filter((c) => c.to.startsWith("/tex/rates/policies/")).map((c) => c.to.split("/").pop()),
    ["cancellation", "payment", "taxes", "extras", "allotments", "fx-policies"],
  )
  assert.equal(ruleVisible("markup", agent), false)
  assert.equal(ruleVisible("pricing-policies", agent), false)
  assert.equal(ruleVisible("cancellation", agent), true)
  assert.equal(areaEntry(rules, shown(agent)), "/tex/rates/policies/cancellation")
  // with the cost right nothing changes: every rule, and the area opens on the markups
  assert.equal(shown(revenue).length, kids.length)
  assert.equal(ruleVisible("markup", revenue), true)
  assert.equal(areaEntry(rules, shown(revenue)), "/tex/rates/policies/markup")
  // an area whose own page is not a sub-section keeps its link
  assert.equal(areaEntry(area("promotions"), []), "/tex/rates/policies/promotions")
})

test("Rates & availability holds the calendar, the restrictions list and the limited extras", () => {
  const inv = area("inventory")
  const kids = inv.children ?? []
  for (const p of ["/tex/inventory", "/tex/inventory/extras", "/tex/rates/restrictions"]) assert.equal(inArea(inv, kids, p), true, p)
  const calendar = kids.find((c) => c.id === "inv-calendar")
  assert.ok(calendar)
  assert.equal(childActive(calendar, inv, "/tex/inventory"), true)
  assert.equal(childActive(calendar, inv, "/tex/inventory/extras"), false)
  // the bulk editor opens part of a screen: never shown as the current page
  const bulk = kids.find((c) => c.id === "rates-bulk")
  assert.ok(bulk)
  assert.equal(childActive(bulk, inv, "/tex/inventory"), false)
})

test("no route was lost: the old areas' pages are all still in the navigation", () => {
  const routes = new Set(NAV.flatMap((n) => [n.to, ...(n.children ?? []).map((c) => c.to.split("?")[0])]))
  for (const r of [
    "/tex", "/tex/crs", "/tex/crs/call-center", "/tex/reservations", "/tex/rates", "/tex/rates/versions", "/tex/rates/periods",
    "/tex/rates/occupancy", "/tex/rates/rate-plans", "/tex/settings/markets", "/tex/rates/policies/promotions", "/tex/rates/restrictions",
    "/tex/rates/fx-rates", "/tex/inventory", "/tex/inventory/extras", "/tex/booking-engine", "/tex/crm", "/tex/payments", "/tex/reports",
    "/tex/connect", "/tex/settings",
  ])
    assert.ok(routes.has(r), r)
})
