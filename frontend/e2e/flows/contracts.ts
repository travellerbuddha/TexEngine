// R-58 contract administration, as reusable steps: market → contract → version terms
// → publish → price check → rate change on a new version. Every helper drives the TEX
// admin UI (role/label locators only); the API is used for assertions and clean-up.
// Helpers take a Page that is already logged in (see ../helpers.ts `login`).
import { expect, type Locator, type Page } from "@playwright/test"
import { answerOf, byLabel, esc, pageApi, texPath } from "../helpers"
import { type Budget, choose, typeIn } from "./budget"

// shared helpers (moved to ../helpers.ts); re-exported for existing imports
export { APP_PREFIX, byLabel, isoDate, pageApi, texPath, uniqueRunId } from "../helpers"



/** "1234.5" → "1,234.50" (en-GB display of a decimal string; test-side only). */
export function displayAmount(amount: string): string {
  const [i, f = ""] = amount.replace(/^-/, "").split(".")
  return `${amount.startsWith("-") ? "-" : ""}${i.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${(f + "00").slice(0, Math.max(2, f.length))}`
}



/** Wait for a success toast; fail fast with the message if an error toast (or an
 * inline "could not" notice) shows instead. Toasts live in the aria-live region. */
export async function expectSuccess(page: Page, text: string | RegExp) {
  const toasts = page.locator("[aria-live]")
  const ok = toasts.getByRole("status").filter({ hasText: text }).last()
  const err = toasts.getByRole("alert").or(page.getByRole("alert").filter({ hasText: /could not be saved/ })).first()
  await expect(ok.or(err).first()).toBeVisible()
  if (!(await ok.isVisible()) && (await err.isVisible())) throw new Error(`expected "${text}" but got: ${await err.innerText()}`)
}

/** Pick the hotel in the shell (no-op when the user has a single hotel). */
export async function selectHotel(page: Page, hotel: string) {
  const sel = page.getByRole("combobox", { name: "Hotel", exact: true })
  if ((await sel.count()) === 0) return
  if ((await sel.inputValue()) !== hotel) await sel.selectOption(hotel)
  await expect(sel).toHaveValue(hotel)
}

// ─── markets (platform administrator) ────────────────────────────────────

export interface MarketInput {
  code: string
  name: string
  countries: string[]
  currency?: string
}

/** Settings → Markets → New market. Reloads afterwards so the session (boot.markets)
 * offers the market in contract dialogs. Returns the market code. */
export async function createMarket(page: Page, m: MarketInput): Promise<string> {
  await page.goto(texPath("/tex/settings/markets"))
  await page.getByRole("button", { name: "New market", exact: true }).click()
  const drawer = page.getByRole("dialog", { name: "New market" })
  await byLabel(drawer, "Code").fill(m.code)
  await byLabel(drawer, "Name").fill(m.name)
  await byLabel(drawer, "Countries").fill(m.countries.join(", "))
  if (m.currency) await byLabel(drawer, "Default currency").selectOption(m.currency)
  await drawer.getByRole("button", { name: "Save", exact: true }).click()
  await expectSuccess(page, `Market ${m.code} saved`)
  await expect(drawer).toBeHidden()
  const row = page.getByRole("row").filter({ hasText: m.code })
  await expect(row).toBeVisible()
  await expect(row).toContainText(m.name)
  await page.reload()
  return m.code
}

interface MarketRow {
  name: string
  market_code: string
  market_name: string
  is_global: number
  disabled: number
  countries: string | null
  default_currency: string | null
  default_language: string | null
  parent_market: string | null
}

/** Clean-up (API): disable earlier E2E markets that claim any of `countries`, so a new
 * run's market is the only one for those guests (overlaps would make market choice
 * ambiguous). Needs a platform administrator session. Returns the disabled codes. */
export async function retireE2EMarkets(page: Page, countries: string[], prefix = "E2E_"): Promise<string[]> {
  const want = new Set(countries.map((c) => c.toUpperCase()))
  const list = await pageApi<MarketRow[]>(page, "kamra.tex.api.admin.markets")
  expect(list.ok, `markets: ${JSON.stringify(list.body).slice(0, 300)}`).toBeTruthy()
  const retired: string[] = []
  for (const m of list.message) {
    if (!m.name.startsWith(prefix) || m.disabled) continue
    const theirs = (m.countries ?? "").split(/[\s,]+/).filter(Boolean)
    if (!theirs.some((c) => want.has(c.toUpperCase()))) continue
    const r = await pageApi(page, "kamra.tex.api.admin.save_market", {
      data: {
        name: m.name,
        market_code: m.market_code,
        market_name: m.market_name,
        is_global: m.is_global,
        countries: m.countries,
        default_currency: m.default_currency,
        default_language: m.default_language,
        parent_market: m.parent_market,
        disabled: 1,
      },
    })
    expect(r.ok, `disable ${m.name}: ${JSON.stringify(r.body).slice(0, 300)}`).toBeTruthy()
    retired.push(m.name)
  }
  return retired
}

// ─── contracts ────────────────────────────────────────────────────────────

export interface ContractInput {
  /** Hotel (property name), e.g. "Aurora Beach Resort". */
  hotel: string
  code: string
  name?: string
  market: string
  currency: string
  basis?: "PERSON" | "ROOM"
  stayFrom: string
  stayTo: string
  saleFrom?: string
  saleTo?: string
}

/** Rates & Contracts → New contract. Lands on the contract page; returns its name
 * (e.g. "CTR-00031"). The contract comes with an empty draft V1. */
export async function createContract(page: Page, c: ContractInput): Promise<string> {
  await page.goto(texPath("/tex/rates"))
  await selectHotel(page, c.hotel)
  await page.getByRole("button", { name: "New contract", exact: true }).click()
  const dlg = page.getByRole("dialog", { name: "New contract" })
  const title = c.name ?? `${c.code} contract`
  await byLabel(dlg, "Contract code").fill(c.code)
  await byLabel(dlg, "Contract name").fill(title)
  await byLabel(dlg, "Market").selectOption(c.market)
  await byLabel(dlg, "Pricing basis").selectOption(c.basis ?? "PERSON")
  await byLabel(dlg, "Contract currency").selectOption(c.currency)
  if (c.saleFrom) await byLabel(dlg, "Sale from").fill(c.saleFrom)
  if (c.saleTo) await byLabel(dlg, "Sale to").fill(c.saleTo)
  await byLabel(dlg, "Stay from").fill(c.stayFrom)
  await byLabel(dlg, "Stay to").fill(c.stayTo)
  await dlg.getByRole("button", { name: "Create contract", exact: true }).click()
  await expectSuccess(page, `Contract ${c.code} created`)
  await page.waitForURL(/\/tex\/rates\/contracts\/[^/]+$/)
  await expect(page.getByRole("heading", { name: title })).toBeVisible()
  return decodeURIComponent(page.url().split("/tex/rates/contracts/")[1])
}

export async function openContract(page: Page, contract: string) {
  await page.goto(texPath(`/tex/rates/contracts/${encodeURIComponent(contract)}`))
  await expect(page.getByRole("heading", { name: "Versions", exact: true })).toBeVisible()
  await expect(page.getByRole("link", { name: /^V\d+$/ }).first()).toBeVisible()
}

/** A version's entry in the contract page's timeline (by its "V<n>" link). */
export function timelineItem(page: Page, label: string): Locator {
  return page.getByRole("listitem").filter({ has: page.getByRole("link", { name: label, exact: true }) })
}

/** The version shown in the editor (from the URL), e.g. "CTR-00031-V1". */
export function currentVersion(page: Page): string {
  const m = /\/versions\/([^/?#]+)/.exec(page.url())
  if (!m) throw new Error(`not on a version page: ${page.url()}`)
  return decodeURIComponent(m[1])
}

/** Contract page → "Open draft Vn" → version editor. Returns the draft's name. */
export async function openDraft(page: Page, contract: string): Promise<string> {
  await openContract(page, contract)
  await page.getByRole("button", { name: /^Open draft V\d+$/ }).click()
  await page.waitForURL(/\/versions\//)
  await expect(page.getByRole("tablist", { name: "Version sections" })).toBeVisible()
  await expect(page.getByText("Draft", { exact: true }).first()).toBeVisible()
  return currentVersion(page)
}

// ─── version editor ──────────────────────────────────────────────────────

/** The version editor's four sections (PRICING_WORKSPACE_UX.md §2), tablist "Version sections". */
const SECTION_LABEL = {
  pricing: "Pricing",
  rules: "Commercial rules",
  offers: "Offers & promotions",
  preview: "Preview & audit",
} as const
export type VersionSection = keyof typeof SECTION_LABEL

/** The Advanced rule tables under Commercial rules (tablist "Rule tables"): the editors of the
 * former ten tabs, unchanged. "Occupancy" also names the "Occupancy rules" tab. */
const TABLE_LABEL = {
  rooms: "Rooms",
  periods: "Periods",
  rates: "Room prices",
  ages: "Child ages",
  occupancy: "Occupancy",
  boards: "Boards",
  plans: "Rate plans",
  settings: "Settings",
} as const
export type VersionTab = keyof typeof TABLE_LABEL | "offers" | "preview"

/** How a version-editor step runs. By default it drives the Pricing workspace (the room price
 * matrix, the occupancy ladder with the child ages drawer, the Boards section, the Price test
 * drawer) and saves the draft when it is done, as the ten-tab steps did. */
export interface StepOptions {
  /** Use the Advanced rule tables (Commercial rules → Rule tables, the former tab editors) instead
   * of the workspace. */
  advanced?: boolean
  /** Count the step's gestures on this budget (./budget.ts). */
  budget?: Budget
  /** Save the draft at the end of the step (default true). */
  save?: boolean
}

async function selectTab(page: Page, tablist: string, label: string): Promise<Locator> {
  const name = new RegExp(`^${esc(label)}`)
  const t = page.getByRole("tablist", { name: tablist, exact: true }).getByRole("tab", { name })
  await t.click()
  await expect(t).toHaveAttribute("aria-selected", "true")
  return page.getByRole("tabpanel", { name })
}

/** Select a version editor section; returns its panel. */
export async function openSection(page: Page, section: VersionSection): Promise<Locator> {
  return selectTab(page, "Version sections", SECTION_LABEL[section])
}

/** The panel of `section`, switching to it only when another section is shown (a switch the user
 * would make; none when the section is already on screen). */
async function onSection(page: Page, section: VersionSection): Promise<Locator> {
  const name = new RegExp(`^${esc(SECTION_LABEL[section])}`)
  const tab = page.getByRole("tablist", { name: "Version sections", exact: true }).getByRole("tab", { name })
  await expect(tab).toBeVisible()
  if ((await tab.getAttribute("aria-selected")) !== "true") return openSection(page, section)
  return page.getByRole("tabpanel", { name })
}

/** Open what a version editor tab of the ten-tab editor held; returns its panel: "offers" and
 * "preview" are sections of their own (Offers & promotions, Preview & audit), every table is an
 * Advanced rule table under Commercial rules. */
export async function openTab(page: Page, tab: VersionTab): Promise<Locator> {
  if (tab === "offers" || tab === "preview") return openSection(page, tab)
  await openSection(page, "rules")
  return selectTab(page, "Rule tables", TABLE_LABEL[tab])
}

/** Save the draft (Ctrl S button) and wait until the editor has taken the server's answer: the
 * button is out of its busy state and, with nothing left unsaved, disabled. The answer itself is
 * awaited first: a "Draft saved" toast may still be showing from the previous save (toasts stay
 * 4.5 s), and a busy Save button is disabled too, so neither alone says this save is done. */
export async function saveDraft(page: Page) {
  const save = page.getByRole("button", { name: /^Save/ })
  await expect(save).toBeEnabled()
  const answered = answerOf(page, "kamra.tex.api.contracts.save_version")
  await save.click()
  const res = await answered
  if (!res.ok()) throw new Error(`save_version: HTTP ${res.status()} ${(await res.text()).slice(0, 400)}`)
  await expectSuccess(page, "Draft saved")
  await expect(save).not.toHaveAttribute("aria-busy", "true")
  await expect(save).toBeDisabled()
}

const saved = async (page: Page, o: StepOptions) => {
  if (o.save ?? true) await saveDraft(page)
}

/** Click a table editor's add button; returns the new row's 1-based number (controls
 * are labelled "<column> <n>"). */
export async function addRow(panel: Locator, addLabel: string, firstColumn: string): Promise<number> {
  const before = await panel.getByLabel(new RegExp(`^${esc(firstColumn)} \\d+$`)).count()
  await panel.getByRole("button", { name: addLabel, exact: true }).click()
  const n = before + 1
  await expect(byLabel(panel, `${firstColumn} ${n}`)).toBeVisible()
  return n
}

/** Row `n`'s control in `column` of a table editor. */
export const cell = (panel: Locator, column: string, n: number) => byLabel(panel, `${column} ${n}`)

// ─── the Pricing workspace: locators ─────────────────────────────────────

/** The room price matrix (a grid of rooms × "All periods" and the period columns). */
export const priceMatrix = (scope: Page | Locator) => scope.getByRole("grid", { name: "Room prices by period", exact: true })

/** The matrix cell a price or formula is typed into for `room` in `period` (default All periods);
 * never the room's resolved row. */
export const priceCell = (scope: Page | Locator, room: string, period?: string | null) =>
  priceMatrix(scope)
    .getByRole("gridcell", { name: new RegExp(`^${esc(room)} · ${esc(period ?? "All periods")}: (?!resolved)`) })
    .first()

/** The occupancy ladder (adult positions, child bands, the resolved line) under the matrix. */
export const occupancyLadder = (scope: Page | Locator) => scope.getByRole("grid", { name: "Occupancy and child pricing by period", exact: true })

/** A ladder cell: `slot` is the row's name ("3rd adult", a band label, "Resolved · {room}"). */
export const ladderCell = (scope: Page | Locator, slot: string | RegExp, period?: string | null) => {
  const s = typeof slot === "string" ? esc(slot) : slot.source
  return occupancyLadder(scope)
    .getByRole("gridcell", { name: new RegExp(`^(${s}) · ${esc(period ?? "All periods")}: `) })
    .first()
}

/** The boards grid of the Boards section. */
export const boardsGrid = (scope: Page | Locator) => scope.getByRole("grid", { name: "Board supplements by period", exact: true })

/** Opens a collapsible region of the workspace ("Occupancy & child pricing", "Boards") when it is
 * closed; returns the region. */
async function openRegion(page: Page, title: string): Promise<Locator> {
  const region = page.getByRole("region", { name: title, exact: true })
  const toggle = region.getByRole("button", { name: title, exact: true })
  await expect(toggle).toBeVisible()
  if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click()
  await expect(toggle).toHaveAttribute("aria-expanded", "true")
  return region
}

/** Types `text` into a workspace grid cell (a click, then typing starts the cell's editor) and
 * commits it with Enter; the editor must close, i.e. the entry was taken. */
async function typeIntoCell(page: Page, grid: Locator, target: Locator, text: string) {
  await target.click()
  await expect(target).toBeFocused()
  await page.keyboard.type(text)
  await expect(grid.getByRole("textbox")).toBeVisible()
  await page.keyboard.press("Enter")
  await expect(grid.getByRole("textbox"), `the entry "${text}" was not taken`).toHaveCount(0)
}

// ─── pricing basis ───────────────────────────────────────────────────────

const BASIS_LABEL = { PERSON: "Per person", ROOM: "Per room" } as const

/** The context header's pricing basis popover (§3.2.1): the Basis chip → the basis → Apply, saved
 * at once as the contract header (the draft's own edits are untouched). A no-op when the contract
 * already has that basis. Unpublished contracts only (the chip is locked after the first publish). */
export async function setBasis(page: Page, basis: "PERSON" | "ROOM", budget?: Budget) {
  const want = BASIS_LABEL[basis]
  const chip = page.getByRole("button", { name: /^Pricing basis: / })
  await expect(chip).toBeVisible()
  if ((await chip.getAttribute("aria-label")) === `Pricing basis: ${want}`) return
  void budget // the budget counts the clicks from the page
  await chip.click()
  const pop = page.getByRole("dialog", { name: "Pricing basis", exact: true })
  await expect(pop).toBeVisible()
  await pop.getByRole("radio", { name: want, exact: true }).click()
  const answered = answerOf(page, "kamra.tex.api.contracts.save_contract")
  await pop.getByRole("button", { name: "Apply", exact: true }).click()
  const res = await answered
  if (!res.ok()) throw new Error(`save_contract: HTTP ${res.status()} ${(await res.text()).slice(0, 400)}`)
  await expect(pop).toBeHidden()
  await expect(page.getByRole("button", { name: `Pricing basis: ${want}`, exact: true })).toBeVisible()
}

// ─── rooms ───────────────────────────────────────────────────────────────

/** Add the contract's room types (labels as shown, e.g. "Standard Sea View"). The workspace adds
 * each with the matrix's "Add room" and makes the first room of an empty version the base room;
 * `base: true` on another room makes that one the base (Set as base). Saves (StepOptions). */
export async function addRooms(page: Page, rooms: { room: string; base?: boolean }[], opts: StepOptions = {}) {
  if (opts.advanced) return addRoomsAdvanced(page, rooms, opts)
  const panel = await onSection(page, "pricing")
  for (const r of rooms) {
    await choose(opts.budget, panel.getByLabel("Add room", { exact: true }), { label: r.room })
    const menu = panel.getByRole("button", { name: `Room actions: ${r.room}`, exact: true })
    await expect(menu).toBeVisible()
    const header = panel.getByRole("rowheader").filter({ has: page.getByRole("button", { name: `Room actions: ${r.room}`, exact: true }) })
    const isBase = (await header.textContent())?.includes("BASE") ?? false
    if (r.base === true && !isBase) {
      await menu.click()
      await page.getByRole("menuitem", { name: "Set as base" }).click()
      const pop = page.getByRole("dialog", { name: `Set ${r.room} as the base room` })
      await pop.getByRole("button", { name: "Apply", exact: true }).click()
      await expect(pop).toBeHidden()
      await expect(header).toContainText("BASE")
    } else if (r.base === false && isBase) {
      throw new Error(`${r.room} became the base room (the workspace's first room is the base); use {advanced: true} for a version without one`)
    }
  }
  await saved(page, opts)
}

async function addRoomsAdvanced(page: Page, rooms: { room: string; base?: boolean }[], opts: StepOptions) {
  const panel = await openTab(page, "rooms")
  for (const r of rooms) {
    const n = await addRow(panel, "Add room type", "Room type")
    await cell(panel, "Room type", n).selectOption({ label: r.room })
    if (r.base !== undefined) await cell(panel, "Base room", n).setChecked(r.base)
  }
  await saved(page, opts)
}

// ─── periods ─────────────────────────────────────────────────────────────

export interface PeriodInput {
  code: string
  name?: string
  from: string
  to: string
}

/** Add a stay period (dates inclusive). The workspace adds a period column with "+ Period" and
 * types its dates in the column header (a first period asks for both, a later one follows the
 * last period and asks for its end); a start that does not follow the last period is set with
 * Dates…, and a code other than the proposed one (or a name) with Rename…. Saves (StepOptions). */
export async function addPeriod(page: Page, p: PeriodInput, opts: StepOptions = {}) {
  if (opts.advanced) return addPeriodAdvanced(page, p, opts)
  const panel = await onSection(page, "pricing")
  await panel.getByRole("button", { name: "Add period", exact: true }).click()
  // the new column's end date has the focus (its start too, when no dated period comes before)
  const end = panel.getByLabel(/^End date: /)
  await expect(end).toBeVisible()
  const code = ((await end.getAttribute("aria-label")) ?? "").replace(/^End date: /, "")
  const start = panel.getByLabel(`Start date: ${code}`, { exact: true })
  if (await start.count()) await typeIn(opts.budget, start, p.from)
  await typeIn(opts.budget, end, p.to)
  // the start the column takes: the one typed, or the day after the last period (the end's min)
  const startNow = await end.getAttribute("min")
  await end.press("Enter")
  const menu = panel.getByRole("button", { name: `Period actions: ${code}`, exact: true })
  await expect(menu).toBeVisible()
  if (startNow !== p.from) {
    // a start that does not follow the last period: Dates…
    await menu.click()
    await page.getByRole("menuitem", { name: "Dates…" }).click()
    const pop = page.getByRole("dialog", { name: `Dates: ${code}` })
    await byLabel(pop, "From").fill(p.from)
    await byLabel(pop, "To (inclusive)").fill(p.to)
    await pop.getByRole("button", { name: "Apply", exact: true }).click()
    await expect(pop).toBeHidden()
  }
  if (p.code !== code || p.name) {
    await menu.click()
    await page.getByRole("menuitem", { name: "Rename…" }).click()
    const pop = page.getByRole("dialog", { name: `Rename ${code}` })
    await byLabel(pop, "Code").fill(p.code)
    if (p.name) await byLabel(pop, "Name").fill(p.name)
    await pop.getByRole("button", { name: "Apply", exact: true }).click()
    await expect(pop).toBeHidden()
    await expect(panel.getByRole("button", { name: `Period actions: ${p.code}`, exact: true })).toBeVisible()
  }
  await saved(page, opts)
}

async function addPeriodAdvanced(page: Page, p: PeriodInput, opts: StepOptions) {
  const panel = await openTab(page, "periods")
  const n = await addRow(panel, "Add period", "Code")
  await cell(panel, "Code", n).fill(p.code)
  if (p.name) await cell(panel, "Name", n).fill(p.name)
  await cell(panel, "From", n).fill(p.from)
  await cell(panel, "To (inclusive)", n).fill(p.to)
  await saved(page, opts)
}

// ─── room prices ─────────────────────────────────────────────────────────

/** Set the base-person (or room) rate of `room` for `period` (or for all periods): the workspace
 * types the amount into the matrix cell and commits it with Enter. Saves (StepOptions), then checks
 * the amount in the cell. */
export async function setBaseRate(page: Page, r: { room: string; period?: string; amount: string }, opts: StepOptions = {}) {
  if (opts.advanced) return setBaseRateAdvanced(page, r, opts)
  const panel = await onSection(page, "pricing")
  const grid = priceMatrix(panel)
  const target = priceCell(panel, r.room, r.period)
  await target.click()
  await expect(target).toBeFocused()
  await page.keyboard.type(r.amount)
  await expect(grid.getByRole("textbox", { name: `Price: ${r.room} · ${r.period ?? "All periods"}`, exact: true })).toBeVisible()
  await page.keyboard.press("Enter")
  await expect(grid.getByRole("textbox"), `the price "${r.amount}" was not taken`).toHaveCount(0)
  await saved(page, opts)
  await expect(target).toContainText(displayAmount(r.amount))
}

async function setBaseRateAdvanced(page: Page, r: { room: string; period?: string; amount: string }, opts: StepOptions) {
  const panel = await openTab(page, "rates")
  const where = `${r.room} · ${r.period ?? "All periods"}`
  const button = panel.getByRole("button", { name: `Edit price: ${where}`, exact: true })
  await button.click()
  const dlg = page.getByRole("dialog", { name: where })
  await byLabel(dlg, "Rule").selectOption("ABSOLUTE")
  await byLabel(dlg, "Value").fill(r.amount)
  await dlg.getByRole("button", { name: "Apply", exact: true }).click()
  await expect(dlg).toBeHidden()
  await saved(page, opts)
  if (r.period) await expect(button).toContainText(displayAmount(r.amount))
}

// ─── child ages and occupancy ────────────────────────────────────────────

export interface ChildBandInput {
  code: string
  label?: string
  /** Years, e.g. "0"; the band covers [fromAge, toAge). */
  fromAge: string
  toAge: string
  infant?: boolean
  /** Share of the base person rate the child pays; "0" makes the band free. */
  percent: string
}

/** The age bands with one "percentage of base" child rule each, and optionally the 3rd adult
 * (extra bed) at `thirdAdultPercent` %. The workspace creates the bands in the child ages drawer
 * (Up to + Enter per band; a label typed in, the infant switch, a code other than the proposed one
 * under Advanced) and types `n%` into the ladder's All periods cells. Saves (StepOptions). */
export async function addOccupancyRules(page: Page, o: { thirdAdultPercent?: string; bands?: ChildBandInput[] }, opts: StepOptions = {}) {
  if (opts.advanced) return addOccupancyRulesAdvanced(page, o, opts)
  const bands = o.bands ?? []
  const panel = await onSection(page, "pricing")
  await openRegion(page, "Occupancy & child pricing")
  const labels: string[] = []
  if (bands.length) {
    await panel.getByRole("button", { name: "Child ages…", exact: true }).click()
    const drawer = page.getByRole("dialog", { name: "Child age bands", exact: true })
    await expect(drawer).toBeVisible()
    const upTo = drawer.getByLabel(/^Up to \(not incl\.\) age: /)
    const had = await upTo.count()
    await drawer.getByRole("button", { name: "Add age band", exact: true }).click()
    const draft = (field: string) => drawer.getByLabel(`${field}: new band`, { exact: true })
    for (const b of bands) {
      const to = draft("Up to (not incl.) age")
      await expect(to).toBeFocused()
      if ((await draft("From age").inputValue()) !== b.fromAge) await typeIn(opts.budget, draft("From age"), b.fromAge)
      if (b.label) await typeIn(opts.budget, draft("Label"), b.label)
      await typeIn(opts.budget, to, b.toAge)
      await to.press("Enter")
    }
    // the band that Enter started after the last one is dropped when the drawer closes
    await expect(upTo).toHaveCount(had + bands.length + 1)
    let codes = false
    for (const [i, b] of bands.entries()) {
      const k = had + i
      const infant = drawer.getByRole("switch", { name: /^Infant band: / }).nth(k)
      if ((await infant.isChecked()) !== Boolean(b.infant)) await infant.setChecked(Boolean(b.infant))
      labels.push(await drawer.getByLabel(/^Label: /).nth(k).inputValue())
      const code = drawer.getByLabel(/^Code: /).nth(k)
      if (!codes) {
        await drawer.getByLabel("Advanced: show band codes", { exact: true }).check()
        codes = true
      }
      if ((await code.inputValue()) !== b.code.toUpperCase()) {
        await code.fill(b.code)
        await code.press("Enter")
        await expect(code).toHaveValue(b.code.toUpperCase())
      }
    }
    if (codes) await drawer.getByLabel("Advanced: show band codes", { exact: true }).uncheck()
    await drawer.getByRole("button", { name: "Close", exact: true }).click()
    await expect(drawer).toBeHidden()
  }
  const ladder = occupancyLadder(panel)
  if (o.thirdAdultPercent !== undefined)
    await typeIntoCell(page, ladder, ladderCell(panel, /3rd adult|Extra adult \(3rd\)/), `${o.thirdAdultPercent}%`)
  for (const [i, b] of bands.entries()) await typeIntoCell(page, ladder, ladderCell(panel, labels[i]), `${b.percent}%`)
  await saved(page, opts)
}

async function addOccupancyRulesAdvanced(page: Page, o: { thirdAdultPercent?: string; bands?: ChildBandInput[] }, opts: StepOptions) {
  const bands = o.bands ?? []
  if (bands.length) {
    const ages = await openTab(page, "ages")
    for (const b of bands) {
      const n = await addRow(ages, "Add age band", "Code")
      await cell(ages, "Code", n).fill(b.code)
      if (b.label) await cell(ages, "Label", n).fill(b.label)
      await cell(ages, "From age", n).fill(b.fromAge)
      await cell(ages, "Up to (not incl.) age", n).fill(b.toAge)
      await cell(ages, "Infant band", n).setChecked(Boolean(b.infant))
    }
  }
  const occ = await openTab(page, "occupancy")
  if (o.thirdAdultPercent !== undefined) {
    const n = await addRow(occ, "Add rule", "Applies to")
    await cell(occ, "Applies to", n).selectOption("ADULT")
    await cell(occ, "Position", n).fill("3")
    await cell(occ, "Rule", n).selectOption("PERCENT_OF")
    await cell(occ, "Value", n).fill(o.thirdAdultPercent)
  }
  for (const b of bands) {
    const n = await addRow(occ, "Add rule", "Applies to")
    await cell(occ, "Applies to", n).selectOption("CHILD")
    await cell(occ, "Age band", n).selectOption(b.code.toUpperCase())
    await cell(occ, "Rule", n).selectOption("PERCENT_OF")
    await cell(occ, "Value", n).fill(b.percent)
  }
  await saved(page, opts)
}

// ─── boards ──────────────────────────────────────────────────────────────

export type BoardCode = "RO" | "BB" | "HB" | "FB" | "AI" | "UAI"

/** A supplement board (per adult per night, children pay `childPercent` of it). On a version
 * without boards the included base board (`base`, default BB) is added first. The workspace uses
 * the Boards section: "Add board", `+amount` typed into the board's All periods cell (an amount per
 * adult; a bare number would be per room, O1), and the row's terms popover for the children's
 * share and infants. Saves (StepOptions). */
export async function addBoard(
  page: Page,
  b: { board: BoardCode; adultAmount: string; childPercent?: string; infantFree?: boolean; base?: BoardCode },
  opts: StepOptions = {},
) {
  if (opts.advanced) return addBoardAdvanced(page, b, opts)
  await onSection(page, "pricing")
  const region = await openRegion(page, "Boards")
  const grid = boardsGrid(region)
  const add = region.getByRole("combobox", { name: "Add board", exact: true })
  if ((await grid.count()) === 0) {
    await choose(opts.budget, add, b.base ?? "BB")
    await expect(grid).toBeVisible()
    await expect(grid.getByRole("gridcell", { name: /: base board, included/ })).toHaveCount(1)
  }
  await choose(opts.budget, add, b.board)
  const editor = grid.getByRole("textbox")
  await expect(editor).toBeFocused()
  const name = ((await editor.getAttribute("aria-label")) ?? "").replace(/^Supplement: /, "").replace(/ · All periods$/, "")
  await page.keyboard.type(b.adultAmount.startsWith("-") ? b.adultAmount : `+${b.adultAmount}`)
  await page.keyboard.press("Enter")
  await expect(editor, `the supplement "${b.adultAmount}" was not taken`).toHaveCount(0)
  const child = b.childPercent ?? "50"
  const infants = b.infantFree ?? true
  if (child !== "50" || !infants) {
    await region.getByRole("button", { name: `Board terms: ${name}`, exact: true }).click()
    const pop = page.getByRole("dialog", { name: `Board terms: ${name}`, exact: true })
    await typeIn(opts.budget, pop.getByLabel(/^Children pay/), child)
    await pop.getByLabel(/^Infants free/).setChecked(infants)
    await pop.getByRole("button", { name: "Apply", exact: true }).click()
    await expect(pop).toBeHidden()
  }
  await expect(region.locator(`[data-board-row="${b.board}|"]`)).toContainText(`children ${child} %`)
  await saved(page, opts)
}

async function addBoardAdvanced(
  page: Page,
  b: { board: BoardCode; adultAmount: string; childPercent?: string; infantFree?: boolean; base?: BoardCode },
  opts: StepOptions,
) {
  const panel = await openTab(page, "boards")
  if ((await panel.getByLabel(/^Board \d+$/).count()) === 0) {
    const n = await addRow(panel, "Add board", "Board")
    await cell(panel, "Board", n).selectOption(b.base ?? "BB")
    await expect(cell(panel, "Included in price", n)).toBeChecked()
  }
  const n = await addRow(panel, "Add board", "Board")
  await cell(panel, "Board", n).selectOption(b.board)
  await cell(panel, "Supplement type", n).selectOption("ADD")
  await cell(panel, "Adult amount / %", n).fill(b.adultAmount)
  await cell(panel, "Child % of adult", n).fill(b.childPercent ?? "50")
  await cell(panel, "Infants free", n).setChecked(b.infantFree ?? true)
  await saved(page, opts)
}

/** Rate plans (optional; a Commercial rules table): sell the contract under a rate plan (label as
 * shown, e.g. "Flexible"). A version without rate plans sells without one. Saves (StepOptions). */
export async function addRatePlan(page: Page, p: { plan: string; refundable?: boolean }, opts: StepOptions = {}) {
  const panel = await openTab(page, "plans")
  const n = await addRow(panel, "Add rate plan", "Rate plan")
  await cell(panel, "Rate plan", n).selectOption({ label: p.plan })
  await cell(panel, "Refundable", n).setChecked(p.refundable ?? true)
  await saved(page, opts)
}

// ─── published versions ──────────────────────────────────────────────────

/** The version on screen is published and frozen: status, read-only badge, the immutability notice,
 * no save/publish; the workspace's grids are read-only (aria-readonly, typing opens no editor, no
 * "Edit price:" trigger), with no "Add room" and no pricing basis popover trigger. */
export async function expectPublishedReadOnly(page: Page, opts: Pick<StepOptions, "advanced"> = {}) {
  await expect(page.getByText("Published", { exact: true }).first()).toBeVisible()
  await expect(page.getByText("Read-only", { exact: true })).toBeVisible()
  await expect(page.getByText("Published versions are immutable", { exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: /^Save/ })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Publish", exact: true })).toHaveCount(0)
  if (opts.advanced) {
    const rates = await openTab(page, "rates")
    await expect(rates.getByRole("table", { name: "Room prices by period" })).toBeVisible()
    await expect(rates.getByRole("button", { name: /^Edit price:/ })).toHaveCount(0)
    const rooms = await openTab(page, "rooms")
    await expect(rooms.getByRole("button", { name: "Add room type" })).toHaveCount(0)
    await expect(rooms.getByRole("combobox")).toHaveCount(0)
    return
  }
  const panel = await onSection(page, "pricing")
  const grid = priceMatrix(panel)
  await expect(grid).toBeVisible()
  await expect(grid).toHaveAttribute("aria-readonly", "true")
  // typing into a cell opens no editor
  const first = grid.getByRole("gridcell").first()
  await first.click()
  await page.keyboard.type("5")
  await page.keyboard.press("Enter")
  await expect(panel.getByRole("textbox")).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^Edit price:/ })).toHaveCount(0)
  await expect(panel.getByLabel("Add room", { exact: true })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^Pricing basis:/ })).toHaveCount(0)
}

/** Publish the draft open in the editor (server check → change note → Publish) and
 * assert it is published and read-only. Returns the version name. */
export async function publishVersion(page: Page, note = "E2E publish"): Promise<string> {
  const version = currentVersion(page)
  await page.getByRole("button", { name: "Publish", exact: true }).click()
  const dlg = page.getByRole("dialog", { name: /^Publish V\d+ of / })
  await expect(dlg).toBeVisible()
  const verdict = dlg.getByText(/The version can be published|I have reviewed|Fix the errors/).first()
  await expect(verdict).toBeVisible()
  if (await dlg.getByText("Fix the errors in the draft before publishing.").isVisible())
    throw new Error(`server check blocks publishing:\n${await dlg.innerText()}`)
  const ack = dlg.getByRole("checkbox", { name: /^I have reviewed/ })
  if (await ack.isVisible()) await ack.check()
  await byLabel(dlg, "Immediately").check()
  await byLabel(dlg, "Change note").fill(note)
  await dlg.getByRole("button", { name: "Publish", exact: true }).click()
  await expectSuccess(page, /is published$/)
  await expect(dlg).toBeHidden()
  await expectPublishedReadOnly(page)
  return version
}

/** Step 15: new draft from the version on sale, new base rate for `room` (in `period`,
 * or all periods), publish. Returns the new version's name. Pass the period the base
 * rate was set for: a period price beats the "All periods" one. */
export async function changeContractRate(
  page: Page,
  c: { contract: string; room: string; period?: string; newRate: string; note?: string },
): Promise<string> {
  await openContract(page, c.contract)
  const live = page.getByRole("listitem").filter({ has: page.getByRole("link", { name: /^V\d+$/ }) }).filter({ hasText: "Selling now" })
  await expect(live).toHaveCount(1)
  const fromLive = live.getByRole("button", { name: /^New draft from this/ })
  if (await fromLive.isEnabled()) {
    await fromLive.click()
    const dlg = page.getByRole("dialog", { name: "New draft" })
    await dlg.getByRole("button", { name: "Create draft", exact: true }).click()
    await expectSuccess(page, "Draft created")
  } else {
    // a draft already exists (e.g. from the availability grid): continue on it
    await page.getByRole("button", { name: /^Open draft V\d+$/ }).click()
  }
  await page.waitForURL(/\/versions\//)
  await expect(page.getByRole("tablist", { name: "Version sections" })).toBeVisible()
  await expect(page.getByRole("button", { name: /^Save/ })).toBeVisible()
  await setBaseRate(page, { room: c.room, period: c.period, amount: c.newRate })
  return publishVersion(page, c.note ?? `E2E rate change to ${c.newRate}`)
}

// ─── price test ──────────────────────────────────────────────────────────

export interface PreviewInput {
  room: string
  /** Board code, e.g. "HB". */
  board?: BoardCode
  /** Rate plan label, e.g. "Flexible" (required when the version has rate plans). */
  ratePlan?: string
  checkIn: string
  checkOut: string
  adults: number
  /** Children's ages in years on arrival. */
  children?: number[]
}

export interface PreviewResult {
  /** Grand total as a plain decimal string, e.g. "815.00". */
  total: string
  /** The total as displayed, e.g. "€815.00". */
  totalText: string
  /** Explanation steps as shown (stage, text, "Rule applied: <level> <rule>"). */
  steps: string[]
}

/** Prices a stay on the server exactly as the booking engine would, for the version on screen, and
 * returns the total and the explanation. The workspace uses the context header's Price test drawer
 * (non-modal, any section; closed again afterwards); `{advanced: true}` uses Preview & audit. */
export async function previewPrice(page: Page, p: PreviewInput, opts: Pick<StepOptions, "advanced"> = {}): Promise<PreviewResult> {
  let panel: Locator
  if (opts.advanced) {
    await openSection(page, "pricing") // leaving the section resets the calculator
    panel = await openSection(page, "preview")
  } else {
    await page.getByRole("button", { name: "Price test", exact: true }).click()
    panel = page.getByRole("dialog", { name: "Price test", exact: true })
    await expect(panel).toBeVisible()
  }
  await byLabel(panel, "Room type").selectOption({ label: p.room })
  if (p.board) await byLabel(panel, "Board").selectOption(p.board)
  if (p.ratePlan) await byLabel(panel, "Rate plan").selectOption({ label: p.ratePlan })
  await byLabel(panel, "Adults").fill(String(p.adults))
  await byLabel(panel, "Check-in").fill(p.checkIn)
  await byLabel(panel, "Check-out").fill(p.checkOut)
  for (const [i, age] of (p.children ?? []).entries()) {
    await panel.getByRole("button", { name: "Add child", exact: true }).click()
    await byLabel(panel, `Age of child ${i + 1}`).fill(String(age))
  }
  await panel.getByRole("button", { name: /^Calculate/ }).click()
  const result = panel.getByRole("heading", { name: "Result", exact: true })
  const refused = panel.getByText("This stay cannot be sold")
  await expect(result.or(refused).first()).toBeVisible()
  if (await refused.isVisible()) throw new Error(`price check refused the stay:\n${await refused.locator("..").innerText()}`)
  let total = panel.getByRole("status", { name: "Total" })
  // compat: bundles built before the <output> total hook show the figure after the label
  if ((await total.count()) === 0) total = panel.getByText("Total", { exact: true }).first().locator("xpath=following-sibling::*[1]")
  const totalText = (await total.innerText()).trim()
  // the ordered list of explanation steps (named "Explanation" in current bundles)
  const why = panel.getByRole("list").filter({ hasText: "Rule applied:" })
  await expect(why).toHaveCount(1)
  const steps = await why.getByRole("listitem").allInnerTexts()
  if (!opts.advanced) {
    await panel.getByRole("button", { name: "Close", exact: true }).click()
    await expect(panel).toBeHidden()
  }
  return { total: totalText.replace(/[^\d.-]/g, ""), totalText, steps: steps.map((s) => s.replace(/\s+/g, " ").trim()) }
}
