// O-2 (ADR-067, D-2): whether infants are children for a version's combination rules and maximum
// children is a version setting. A brand-new contract's first draft says they are not: an infant
// leaves the other children's price alone. Switched on (what every earlier version says), the infant
// is a child again and the one-adult-one-child rule no longer applies. Through the API, as the
// workspace's price test asks the server.
import { expect, test } from "@playwright/test"
import { login, pageApiOk } from "./helpers"
import { archiveAll, newContract, occ, ownerDraft, STD, Y } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const made: string[] = []

test.afterAll(async ({ browser }) => archiveAll(browser, made, "infants e2e clean-up"))

type Preview = { sellable: boolean; totals: { accommodation: string } }

test("a new contract's draft does not count infants as children; switched on, it does", async ({ page }) => {
  await login(page, "revenue@demo.tex")
  const d = await newContract(page, { prefix: "E2E-O2", infantsAsChildren: 0 })
  made.push(d.contract)
  const doc = await pageApiOk<{ infants_count_as_children: number }>(page, "kamra.tex.api.contracts.get_version", { name: d.version })
  expect(doc.infants_count_as_children).toBe(0)

  // the owner's example and a 1+1 rule: the only child of one adult pays like an adult
  const data = ownerDraft()
  data.occupancy_rules = [...data.occupancy_rules, occ({ target: "CHILD", position: 1, age_band: "CHB", combination: "1+1", value: "1" })]
  await pageApiOk(page, "kamra.tex.api.contracts.save_version", { name: d.version, data })
  const price = async (children: number[]) => {
    const q = await pageApiOk<Preview>(page, "kamra.tex.api.contracts.preview_price", {
      version: d.version,
      room_type: STD,
      board: "BB",
      check_in: `${Y}-04-10`,
      check_out: `${Y}-04-11`,
      adults: 1,
      children: JSON.stringify(children),
    })
    expect(q.sellable, JSON.stringify(q)).toBeTruthy()
    return Number(q.totals.accommodation)
  }
  // (the hotel's market markup is on every price; the ratios are the occupancy rules')
  const alone = await price([8]) // 70 + the 8-year-old at 100 %: 140
  expect(await price([8, 1])).toBe(alone) // the infant changes nothing

  await pageApiOk(page, "kamra.tex.api.contracts.save_version", { name: d.version, data: { infants_count_as_children: 1 } })
  expect(await price([8])).toBe(alone)
  expect(await price([8, 1])).toBeCloseTo((alone * 105) / 140, 2) // 1A+2C: the 8-year-old at 50 %, the infant free
})
