import { expect, test } from "@playwright/test"
import { ADMIN_PASSWORD, login, trackErrors } from "./helpers"
import {
  addBoard,
  addOccupancyRules,
  addPeriod,
  addRooms,
  changeContractRate,
  createContract,
  createMarket,
  currentVersion,
  isoDate,
  openContract,
  openDraft,
  pageApi,
  previewPrice,
  publishVersion,
  retireE2EMarkets,
  setBaseRate,
  timelineItem,
  uniqueRunId,
} from "./flows/contracts"

// R-58 (contract administration part): a platform admin opens a market, the revenue
// manager contracts Aurora Beach Resort for it, publishes the terms (frozen), checks
// the price with its explanation, then changes the rate through a new version.
// Codes are unique per run, so repeated runs never collide.

const HOTEL = "Aurora Beach Resort"
const ROOM = "Standard Sea View"
const ROOM_ID = `${HOTEL}-STD`
const COUNTRIES = ["IS"]

// fail a step quickly instead of waiting for the whole test timeout
test.use({ actionTimeout: 15_000, navigationTimeout: 30_000 })

test("contract admin: market → contract → publish (frozen) → price check → rate change", async ({ page }) => {
  test.setTimeout(300_000)
  const noErrors = trackErrors(page)
  const run = uniqueRunId()
  const market = `E2E_${run}`
  const code = `E2E-${run}`
  const season = { code: "SEASON", name: "E2E season", from: isoDate(7), to: isoDate(400) }
  const stay = { checkIn: isoDate(30), checkOut: isoDate(32) }
  const party = { adults: 3, children: [8, 1] } // 3rd adult on the extra bed, a child and an infant
  let contract = ""
  let v1 = ""

  await test.step("platform admin creates the market", async () => {
    await login(page, "Administrator", ADMIN_PASSWORD)
    // earlier runs' markets must not claim the same country (ambiguous market)
    await retireE2EMarkets(page, COUNTRIES)
    await createMarket(page, { code: market, name: `E2E ${run}`, countries: COUNTRIES, currency: "EUR" })
  })

  await test.step("revenue manager creates the contract with a draft V1", async () => {
    await login(page, "revenue@demo.tex")
    contract = await createContract(page, {
      hotel: HOTEL,
      code,
      market,
      currency: "EUR",
      basis: "PERSON",
      saleFrom: isoDate(0),
      stayFrom: season.from,
      stayTo: season.to,
    })
    // exactly one contract carries this run's code
    const list = await pageApi<{ contract_code: string }[]>(page, "kamra.tex.api.contracts.list_contracts", { property: HOTEL })
    expect(list.ok).toBeTruthy()
    expect(list.message.filter((r) => r.contract_code === code)).toHaveLength(1)
    v1 = await openDraft(page, contract)
    expect(v1).toMatch(/-V1$/)
  })

  await test.step("terms: room, season, base rate, occupancy, board", async () => {
    await addRooms(page, [{ room: ROOM, base: true }])
    await addPeriod(page, season)
    await setBaseRate(page, { room: ROOM, period: season.code, amount: "100" })
    await addOccupancyRules(page, {
      thirdAdultPercent: "70",
      bands: [
        { code: "INF", label: "Infant", fromAge: "0", toAge: "2", infant: true, percent: "0" },
        { code: "CHD", label: "Child", fromAge: "2", toAge: "12", percent: "50" },
      ],
    })
    await addBoard(page, { board: "HB", adultAmount: "25", childPercent: "50", infantFree: true })
  })

  await test.step("publish V1: published versions are frozen", async () => {
    expect(await publishVersion(page, `E2E ${run}: first terms`)).toBe(v1)
    // the server refuses edits too, not only the UI
    const r = await pageApi(page, "kamra.tex.api.contracts.save_version", { name: v1, data: { period_rates: [] } })
    expect(r.ok).toBeFalsy()
    expect(JSON.stringify(r.body)).toContain("Only draft versions can be edited")
    await page.reload()
    expect(currentVersion(page)).toBe(v1)
    await expect(page.getByText("Read-only", { exact: true })).toBeVisible()
  })

  await test.step("price check explains which rules won", async () => {
    // per night: adults 100 + 100 + 70 (3rd adult 70 %), child 50 %, infant 0 → 320
    // half board: 3 × 25 + child 50 % of 25, infant free → 87.50; 2 nights → 815.00
    const p = await previewPrice(page, { room: ROOM, board: "HB", ...stay, ...party })
    expect(p.total).toBe("815.00")
    const why = p.steps.join("\n")
    expect(why).toMatch(new RegExp(`Rule applied: Period ${ROOM_ID} @SEASON = 100\\.00`))
    expect(why).toMatch(/Rule applied: Version Adult 3 70(\.00)?% of/)
    expect(why).toMatch(/Rule applied: Version Child \[CHD\] 50(\.00)?% of/)
    expect(why).toMatch(/Rule applied: Version Child \[INF\] 0(\.00)?% of/)
    expect(why).toMatch(/Rule applied: Version HB/)
    expect(p.steps.at(-1)).toContain("total 815.00 EUR")
  })

  await test.step("rate change goes through a new version", async () => {
    const v2 = await changeContractRate(page, { contract, room: ROOM, period: season.code, newRate: "120" })
    expect(v2).toMatch(/-V2$/)
    // adults 120 + 120 + 84, child 60, infant 0 → 384 + board 87.50 → 471.50 × 2
    const p = await previewPrice(page, { room: ROOM, board: "HB", ...stay, ...party })
    expect(p.total).toBe("943.00")
    await openContract(page, contract)
    const item = (v: string) => timelineItem(page, v)
    await expect(item("V2")).toContainText("Selling now")
    await expect(item("V1")).toContainText("Superseded")
    await expect(item("V1")).not.toContainText("Selling now")
    // V1 keeps its frozen price
    await page.getByRole("button", { name: "View V1", exact: true }).click()
    const again = await previewPrice(page, { room: ROOM, board: "HB", ...stay, ...party })
    expect(again.total).toBe("815.00")
  })

  noErrors()
})

