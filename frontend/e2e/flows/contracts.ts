// R-58 contract administration, as reusable steps: market → contract → version terms
// → publish → price check → rate change on a new version. Every helper drives the TEX
// admin UI (role/label locators only); the API is used for assertions and clean-up.
// Helpers take a Page that is already logged in (see ../helpers.ts `login`).
import { expect, type Locator, type Page } from "@playwright/test"

const BASE = process.env.TEX_E2E_BASE || "http://test.localhost:8000"
/** The admin SPA lives under /kamra on the bench and at / on a Vite dev server (51xx). */
export const APP_PREFIX = process.env.TEX_E2E_APP_PREFIX ?? (/:51\d\d(\/|$)/.test(BASE) ? "" : "/kamra")
export const texPath = (path: string) => `${APP_PREFIX}${path}`

/** Upper-case id unique per run (base-36 time + 2 random chars), e.g. "MFX3K2QA7Z". */
export function uniqueRunId(): string {
  const rnd = Math.floor(Math.random() * 1296)
    .toString(36)
    .padStart(2, "0")
  return `${Date.now().toString(36)}${rnd}`.toUpperCase()
}

/** Local calendar date `offsetDays` from today as YYYY-MM-DD (what date inputs take). */
export function isoDate(offsetDays: number, from = new Date()): string {
  const d = new Date(from)
  d.setDate(d.getDate() + offsetDays)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

/** "1234.5" → "1,234.50" (en-GB display of a decimal string; test-side only). */
export function displayAmount(amount: string): string {
  const [i, f = ""] = amount.replace(/^-/, "").split(".")
  return `${amount.startsWith("-") ? "-" : ""}${i.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${(f + "00").slice(0, Math.max(2, f.length))}`
}

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")

/** Control by its label; required fields show "Label*", so an optional marker is accepted. */
export const byLabel = (scope: Page | Locator, label: string) => scope.getByLabel(new RegExp(`^${esc(label)}\\s*\\*?$`))

/** API call in the page's session (assertions and clean-up only). Once the bench has
 * rendered the SPA the session holds a CSRF token, which POSTs must echo. */
export async function pageApi<T = unknown>(page: Page, method: string, args: Record<string, unknown> = {}) {
  const csrf = await page.evaluate(() => (window as unknown as { csrf_token?: string }).csrf_token).catch(() => undefined)
  const r = await page.request.post(`/api/method/${method}`, {
    data: args,
    headers: csrf ? { "X-Frappe-CSRF-Token": csrf } : {},
  })
  const body = (await r.json().catch(() => ({}))) as { message?: T }
  return { ok: r.ok(), status: r.status(), body, message: body.message as T }
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

const TAB_LABEL = {
  rooms: "Rooms",
  periods: "Periods",
  rates: "Room prices",
  ages: "Child ages",
  occupancy: "Occupancy",
  boards: "Boards",
  plans: "Rate plans",
  offers: "Offers",
  settings: "Settings",
  preview: "Price check",
} as const
export type VersionTab = keyof typeof TAB_LABEL

/** Select a version editor tab; returns its panel. */
export async function openTab(page: Page, tab: VersionTab): Promise<Locator> {
  const t = page.getByRole("tablist", { name: "Version sections" }).getByRole("tab", { name: new RegExp(`^${esc(TAB_LABEL[tab])}`) })
  await t.click()
  await expect(t).toHaveAttribute("aria-selected", "true")
  return page.getByRole("tabpanel")
}

/** Save the draft (Ctrl S button) and wait for the server to accept it. */
export async function saveDraft(page: Page) {
  const save = page.getByRole("button", { name: /^Save/ })
  await expect(save).toBeEnabled()
  await save.click()
  await expectSuccess(page, "Draft saved")
  await expect(save).toBeDisabled()
}

/** Click a table editor's add button; returns the new row's 1-based number (controls
 * are labelled "<column> <n>"). */
async function addRow(panel: Locator, addLabel: string, firstColumn: string): Promise<number> {
  const before = await panel.getByLabel(new RegExp(`^${esc(firstColumn)} \\d+$`)).count()
  await panel.getByRole("button", { name: addLabel, exact: true }).click()
  const n = before + 1
  await expect(byLabel(panel, `${firstColumn} ${n}`)).toBeVisible()
  return n
}

const cell = (panel: Locator, column: string, n: number) => byLabel(panel, `${column} ${n}`)

/** Rooms tab: add room types (labels as shown, e.g. "Standard Sea View"). The first
 * room added to an empty version becomes the base room. Saves. */
export async function addRooms(page: Page, rooms: { room: string; base?: boolean }[]) {
  const panel = await openTab(page, "rooms")
  for (const r of rooms) {
    const n = await addRow(panel, "Add room type", "Room type")
    await cell(panel, "Room type", n).selectOption({ label: r.room })
    if (r.base !== undefined) await cell(panel, "Base room", n).setChecked(r.base)
  }
  await saveDraft(page)
}

export interface PeriodInput {
  code: string
  name?: string
  from: string
  to: string
}

/** Periods tab: add a stay period (dates inclusive). Saves. */
export async function addPeriod(page: Page, p: PeriodInput) {
  const panel = await openTab(page, "periods")
  const n = await addRow(panel, "Add period", "Code")
  await cell(panel, "Code", n).fill(p.code)
  if (p.name) await cell(panel, "Name", n).fill(p.name)
  await cell(panel, "From", n).fill(p.from)
  await cell(panel, "To (inclusive)", n).fill(p.to)
  await saveDraft(page)
}

/** Room prices tab: set the base-person (or room) rate of `room` for `period` (or for
 * all periods). Saves, then checks the server-resolved nightly price in the grid. */
export async function setBaseRate(page: Page, r: { room: string; period?: string; amount: string }) {
  const panel = await openTab(page, "rates")
  const where = `${r.room} · ${r.period ?? "All periods"}`
  const button = panel.getByRole("button", { name: `Edit price: ${where}`, exact: true })
  await button.click()
  const dlg = page.getByRole("dialog", { name: where })
  await byLabel(dlg, "Rule").selectOption("ABSOLUTE")
  await byLabel(dlg, "Value").fill(r.amount)
  await dlg.getByRole("button", { name: "Apply", exact: true }).click()
  await expect(dlg).toBeHidden()
  await saveDraft(page)
  if (r.period) await expect(button).toContainText(displayAmount(r.amount))
}

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

/** Child ages + Occupancy tabs: the age bands with one "percentage of base" child rule
 * each, and optionally the 3rd adult (extra bed) at `thirdAdultPercent` %. Saves. */
export async function addOccupancyRules(page: Page, o: { thirdAdultPercent?: string; bands?: ChildBandInput[] }) {
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
  await saveDraft(page)
}

export type BoardCode = "RO" | "BB" | "HB" | "FB" | "AI" | "UAI"

/** Boards tab: a supplement board (per adult per night, children pay `childPercent`
 * of it). On an empty version the included base board (`base`, default BB) is added
 * first. Saves. */
export async function addBoard(
  page: Page,
  b: { board: BoardCode; adultAmount: string; childPercent?: string; infantFree?: boolean; base?: BoardCode },
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
  await saveDraft(page)
}

/** Rate plans tab (optional): sell the contract under a rate plan (label as shown,
 * e.g. "Flexible"). A version without rate plans sells without one. Saves. */
export async function addRatePlan(page: Page, p: { plan: string; refundable?: boolean }) {
  const panel = await openTab(page, "plans")
  const n = await addRow(panel, "Add rate plan", "Rate plan")
  await cell(panel, "Rate plan", n).selectOption({ label: p.plan })
  await cell(panel, "Refundable", n).setChecked(p.refundable ?? true)
  await saveDraft(page)
}

/** The version on screen is published and frozen: status, read-only badge, the
 * immutability notice, no save/publish, and no editable price cells. */
export async function expectPublishedReadOnly(page: Page) {
  await expect(page.getByText("Published", { exact: true }).first()).toBeVisible()
  await expect(page.getByText("Read-only", { exact: true })).toBeVisible()
  await expect(page.getByText("Published versions are immutable")).toBeVisible()
  await expect(page.getByRole("button", { name: /^Save/ })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Publish", exact: true })).toHaveCount(0)
  const rates = await openTab(page, "rates")
  await expect(rates.getByRole("table", { name: "Room prices by period" })).toBeVisible()
  await expect(rates.getByRole("button", { name: /^Edit price:/ })).toHaveCount(0)
  const rooms = await openTab(page, "rooms")
  await expect(rooms.getByRole("button", { name: "Add room type" })).toHaveCount(0)
  await expect(rooms.getByRole("combobox")).toHaveCount(0)
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

/** Price check tab of the version on screen: prices a stay on the server exactly as
 * the booking engine would and returns the total and the explanation. */
export async function previewPrice(page: Page, p: PreviewInput): Promise<PreviewResult> {
  await openTab(page, "rooms") // leaving the tab resets the calculator
  const panel = await openTab(page, "preview")
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
  return { total: totalText.replace(/[^\d.-]/g, ""), totalText, steps: steps.map((s) => s.replace(/\s+/g, " ").trim()) }
}
