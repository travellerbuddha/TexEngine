import { expect, test, type Page } from "@playwright/test"
import { answerOf, holdNext, login, pageApi, texPath, trackErrors } from "./helpers"
import { addPeriod, addRooms, boardsGrid, createContract, isoDate, openDraft, priceMatrix, saveDraft, uniqueRunId } from "./flows/contracts"

// Editors never lose what the user typed: Discard returns to the last save (not to the version
// as first opened), and an edit made while a save is in flight survives the save's answer and
// goes out with the next save. The contracts are drafts for the DE market, unique per run and
// archived after each test; the tax policy stays a draft and is deleted.

const HOTEL = "Aurora Beach Resort"
const ROOM = "Standard Sea View"
const ROOM_ID = `${HOTEL}-STD`

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

interface VersionRows {
  rooms: { room_type: string }[]
  periods: { period_code: string }[]
  boards: { board: string }[]
}

async function readVersion(page: Page, version: string) {
  const r = await pageApi<VersionRows>(page, "kamra.tex.api.contracts.get_version", { name: version })
  expect(r.ok, JSON.stringify(r.body).slice(0, 300)).toBeTruthy()
  return r.message
}

// clean-up of what a test created, run after it whether it passed or not
let cleanUp: (() => Promise<unknown>)[] = []
test.afterEach(async () => {
  for (const fn of cleanUp.reverse()) await fn().catch(() => undefined)
  cleanUp = []
})

async function newDraft(page: Page, run: string) {
  const contract = await createContract(page, {
    hotel: HOTEL,
    code: `E2E-${run}`,
    market: "DE",
    currency: "EUR",
    stayFrom: isoDate(1),
    stayTo: isoDate(365),
  })
  cleanUp.push(() => pageApi(page, "kamra.tex.api.contracts.set_contract_status", { name: contract, action: "archive", reason: "e2e clean-up" }))
  return openDraft(page, contract)
}

test("contract version: Discard returns to the last save, and the next save keeps it", async ({ page }) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  await login(page, "revenue@demo.tex")
  const version = await newDraft(page, uniqueRunId())

  await addRooms(page, [{ room: ROOM, base: true }])
  // a board added in the workspace's Boards section (the first one is the base board, written at once)
  const boards = page.getByRole("region", { name: "Boards", exact: true })
  await boards.getByRole("combobox", { name: "Add board", exact: true }).selectOption("BB")
  await expect(boardsGrid(page).getByRole("rowheader").filter({ hasText: "Bed & breakfast" })).toBeVisible()
  const discard = page.getByRole("button", { name: "Discard", exact: true })
  await expect(discard).toBeEnabled()
  await discard.click()

  // back to the saved version: the room saved a moment ago is there, the unsaved board is not
  await expect(page.getByRole("button", { name: /^Save/ })).toBeDisabled()
  await expect(boardsGrid(page)).toHaveCount(0)
  await expect(boards.locator("[data-board-row]")).toHaveCount(0)
  await expect(page.getByRole("button", { name: `Room actions: ${ROOM}`, exact: true })).toBeVisible()

  // another edit and save: the server still has the room
  await addPeriod(page, { code: "S1", from: isoDate(7), to: isoDate(60) })
  const saved = await readVersion(page, version)
  expect(saved.rooms.map((r) => r.room_type)).toEqual([ROOM_ID])
  expect(saved.periods.map((p) => p.period_code)).toEqual(["S1"])
  expect(saved.boards).toEqual([])

  noErrors()
})

test("contract version: an edit made while a save is in flight is kept and saved next", async ({ page }) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  await login(page, "revenue@demo.tex")
  const version = await newDraft(page, uniqueRunId())

  await addRooms(page, [{ room: ROOM }], { save: false })

  // the save reaches the server; its answer is held while the user adds a period column
  const flight = await holdNext(page, "kamra.tex.api.contracts.save_version")
  const save = page.getByRole("button", { name: /^Save/ })
  await save.click()
  await flight.held
  await page.getByRole("button", { name: "Add period", exact: true }).click()
  await page.getByLabel("Start date: P1", { exact: true }).fill(isoDate(7))
  await page.getByLabel("End date: P1", { exact: true }).fill(isoDate(60))
  await page.getByLabel("End date: P1", { exact: true }).press("Enter")
  const column = page.getByRole("button", { name: "Period actions: P1", exact: true })
  await expect(column).toBeVisible()
  flight.release()
  await expect(page.locator("[aria-live]").getByRole("status").filter({ hasText: "Draft saved" })).toBeVisible()

  // the period added meanwhile is still there and still unsaved; the saved room too
  await expect(save).not.toHaveAttribute("aria-busy", "true")
  await expect(column).toBeVisible()
  await expect(priceMatrix(page).getByRole("columnheader").filter({ has: page.getByRole("button", { name: "Period actions: P1" }) })).toHaveCount(1)
  await expect(save).toBeEnabled()
  expect((await readVersion(page, version)).periods).toEqual([])
  await expect(page.getByRole("button", { name: `Room actions: ${ROOM}`, exact: true })).toBeVisible()

  // the next save sends both
  await saveDraft(page)
  const saved = await readVersion(page, version)
  expect(saved.rooms.map((r) => r.room_type)).toEqual([ROOM_ID])
  expect(saved.periods.map((p) => p.period_code)).toEqual(["P1"])

  noErrors()
})

test("policy editor: what is typed while a create or a save is in flight is kept", async ({ page }) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  const run = uniqueRunId()
  const names = [`E2E taxes ${run} A`, `E2E taxes ${run} B`, `E2E taxes ${run} C`]
  await login(page, "finance@demo.tex")
  await page.goto(texPath("/tex/rates/policies/taxes"))
  await page.getByRole("button", { name: "New tax policy" }).first().click()
  const policyName = page.getByLabel("Policy name")
  await policyName.fill(names[0])
  await page.getByRole("main").getByLabel("Hotel").selectOption({ label: HOTEL })
  await page.getByRole("button", { name: "Add row" }).click()
  const row = page.getByRole("row").last()
  await row.getByLabel("Code").fill("VAT")
  await row.getByLabel("Rate %").fill("10")

  // create: the name changes while the create is in flight
  const create = await holdNext(page, "kamra.tex.api.policies.save_record")
  await page.getByRole("button", { name: "Create draft" }).click()
  await create.held
  await policyName.fill(names[1])
  create.release()
  await page.waitForURL(/\/tex\/rates\/policies\/taxes\/(?!new$)[^/]+$/)
  const policy = decodeURIComponent(page.url().split("/tex/rates/policies/taxes/")[1])
  cleanUp.push(() => pageApi(page, "kamra.tex.api.policies.delete_record", { doctype: "TEX Tax Policy", name: policy }))
  // the created record has loaded (a draft of it can be deleted); the name typed meanwhile stays
  await expect(page.getByRole("button", { name: "Delete draft" })).toBeVisible()
  await expect(policyName).toHaveValue(names[1])
  await expect(page.getByLabel("Currency of fixed amounts")).toHaveValue("EUR") // filled in by the server
  const save = page.getByRole("button", { name: "Save", exact: true })
  await expect(save).toBeEnabled()

  // save: the name changes again while the save is in flight (the create's toast gone first, so
  // the next "Saved" is this save's)
  const savedToast = page.locator("[aria-live]").getByRole("status").filter({ hasText: "Saved" })
  await expect(savedToast).toHaveCount(0, { timeout: 10_000 })
  const flight = await holdNext(page, "kamra.tex.api.policies.save_record")
  await save.click()
  await flight.held
  await policyName.fill(names[2])
  flight.release()
  await expect(savedToast).toBeVisible()
  await expect(save).not.toHaveAttribute("aria-busy", "true")
  await expect(policyName).toHaveValue(names[2])
  await expect(save).toBeEnabled()

  // the next save sends it
  const answered = answerOf(page, "kamra.tex.api.policies.save_record")
  await save.click()
  expect((await answered).ok()).toBeTruthy()
  await expect(save).toBeDisabled()
  const stored = await pageApi<{ policy_name: string; tex_status: string }>(page, "kamra.tex.api.policies.get_record", { doctype: "TEX Tax Policy", name: policy })
  expect(stored.message.policy_name).toBe(names[2])
  expect(stored.message.tex_status).toBe("Draft")

  await page.getByRole("button", { name: "Delete draft" }).click()
  await page.getByRole("dialog").getByRole("button", { name: /Delete/ }).click()
  await expect(page).toHaveURL(/\/tex\/rates\/policies\/taxes$/)
  noErrors()
})
