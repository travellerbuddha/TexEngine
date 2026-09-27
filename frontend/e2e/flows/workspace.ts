// Fixtures of the Pricing Workspace specs (pricing-workspace*.spec.ts): contracts and drafts made
// through the API for the demo hotel Aurora Beach Resort, the owner's example terms of
// PRICING_WORKSPACE_UX.md §5.3 (Standard as the base room; Family Suite and Garden Villa stand for
// the design's "Superior" and "Deluxe"), the contracts API calls a page makes, and clean-up.
// The UI is driven by the specs and ./contracts.ts; the API only sets up, checks and cleans up.
import { expect, type Browser, type Page, type Request } from "@playwright/test"
import { login, pageApiOk, texPath, uniqueRunId } from "../helpers"

export const HOTEL = "Aurora Beach Resort"
/** Room type ids of the demo hotel. */
export const STD = `${HOTEL}-STD`
export const SUP = `${HOTEL}-FAM`
export const DLX = `${HOTEL}-VIL`
/** Their names as the workspace shows them. */
export const ROOM_NAME = { [STD]: "Standard Sea View", [SUP]: "Family Suite", [DLX]: "Garden Villa" } as Record<string, string>
export const N = { STD: "Standard Sea View", SUP: "Family Suite", DLX: "Garden Villa" } as const
/** The stay year of the fixtures (next year: every period is still to come). */
export const Y = new Date().getFullYear() + 1
/** Room capacity of the fixtures (two children fit, four adults, five guests). */
export const CAP = { max_adults: 4, max_children: 2, max_occupants: 5, min_adults: 1 }

export type Data = Record<string, Record<string, unknown>[]>

/** An occupancy rule row with every field (the save payload's shape). */
export const occ = (f: Record<string, unknown>) => ({
  target: "ADULT",
  position: 0,
  age_band: null,
  combination: null,
  room_type: null,
  period_code: null,
  op: "MULTIPLY",
  value: null,
  is_override: 0,
  note: null,
  ...f,
})

/** P1–P4: April to July of next year, one month each. */
export const periods = () => [
  { period_code: "P1", period_name: "Apr", start_date: `${Y}-04-01`, end_date: `${Y}-04-30` },
  { period_code: "P2", period_name: "May", start_date: `${Y}-05-01`, end_date: `${Y}-05-31` },
  { period_code: "P3", period_name: "Jun", start_date: `${Y}-06-01`, end_date: `${Y}-06-30` },
  { period_code: "P4", period_name: "Jul", start_date: `${Y}-07-01`, end_date: `${Y}-07-31` },
]

/** The three rooms, Standard the base room. */
export const rooms = (cap: Record<string, number> = CAP) => [
  { room_type: STD, is_base: 1, ...cap },
  { room_type: SUP, is_base: 0, ...cap },
  { room_type: DLX, is_base: 0, ...cap },
]

/** Standard 70 / 80 / 100 / 130 (entered), Family Suite ×1.15 and Garden Villa ×1.35 for all periods. */
export const ownerRates = () => [
  { room_type: STD, period_code: "P1", op: "ABSOLUTE", value: "70" },
  { room_type: STD, period_code: "P2", op: "ABSOLUTE", value: "80" },
  { room_type: STD, period_code: "P3", op: "ABSOLUTE", value: "100" },
  { room_type: STD, period_code: "P4", op: "ABSOLUTE", value: "130" },
  { room_type: SUP, period_code: "", op: "MULTIPLY", value: "1.15", base_room_type: STD },
  { room_type: DLX, period_code: "", op: "MULTIPLY", value: "1.35", base_room_type: STD },
]

/** The child bands of the example, with their labels. */
export const ownerBands = () => [
  { band_code: "INF", label: "Infant 0–2.99", from_age: "0", to_age: "2.99", is_infant: 1 },
  { band_code: "CHA", label: "Child 3–6.99", from_age: "3", to_age: "6.99", is_infant: 0 },
  { band_code: "CHB", label: "Child 7–11.99", from_age: "7", to_age: "11.99", is_infant: 0 },
]

/** The occupancy rules of the example: 3rd adult ×0.70, the bands ×0 / ×0.25 / ×0.50. */
export const ownerOccupancy = () => [
  occ({ target: "ADULT", position: 3, value: "0.7" }),
  occ({ target: "CHILD", age_band: "INF", value: "0" }),
  occ({ target: "CHILD", age_band: "CHA", value: "0.25" }),
  occ({ target: "CHILD", age_band: "CHB", value: "0.5" }),
]

/** The base board BB, included in the room price. */
export const baseBoard = () => [{ board: "BB", is_base: 1, op: "ADD", adult_amount: null, child_percent: "50", infant_free: 1, room_type: "", period_code: "" }]

/** The draft of the owner's example: rooms, P1–P4, the rates, bands and occupancy rules, BB. */
export const ownerDraft = (): Data => ({
  rooms: rooms(),
  periods: periods(),
  period_rates: ownerRates(),
  age_bands: ownerBands(),
  occupancy_rules: ownerOccupancy(),
  boards: baseBoard(),
})

export interface NewContract {
  contract: string
  version: string
}

/** A contract for the DE market in EUR (stay April–July of next year) with its empty draft V1,
 * made through the API. A brand-new contract's draft does not count infants as children (O-2,
 * ADR-067); the specs' parties and sweep warnings were written for a draft that does, so it is set
 * back on unless `infantsAsChildren` is 0. */
export async function newContract(
  page: Page,
  o: { prefix: string; basis?: "PERSON" | "ROOM"; currency?: string; infantsAsChildren?: 0 | 1 },
): Promise<NewContract> {
  const run = uniqueRunId()
  const c = await pageApiOk<{ contract: { name: string } }>(page, "kamra.tex.api.contracts.save_contract", {
    data: {
      property: HOTEL,
      contract_code: `${o.prefix}-${run}`,
      contract_name: `${o.prefix} ${run}`,
      market: "DE",
      pricing_basis: o.basis ?? "PERSON",
      contract_currency: o.currency ?? "EUR",
      stay_from: `${Y}-04-01`,
      stay_to: `${Y}-07-31`,
    },
  })
  const contract = c.contract.name
  const b = await pageApiOk<{ versions: { name: string }[] }>(page, "kamra.tex.api.contracts.get_contract", { name: contract })
  const version = b.versions[0].name
  if (o.infantsAsChildren !== 0) {
    await pageApiOk(page, "kamra.tex.api.contracts.save_version", { name: version, data: { infants_count_as_children: 1 } })
  }
  return { contract, version }
}

/** A new contract whose draft holds `data` (saved through the API). */
export async function newDraft(page: Page, prefix: string, data: Data, basis: "PERSON" | "ROOM" = "PERSON"): Promise<NewContract> {
  const d = await newContract(page, { prefix, basis })
  await pageApiOk(page, "kamra.tex.api.contracts.save_version", { name: d.version, data })
  return d
}

/** Publish a draft through the API as the workspace publishes it (its terms must pass the publish
 * check; `workspace: 1`, ADR-061: its board checks, and a stored report anchored by each issue's ref). */
export async function publish(page: Page, version: string) {
  await pageApiOk(page, "kamra.tex.api.contracts.publish_version", { name: version, workspace: 1 })
}

export const versionPath = (d: NewContract, hash = "") =>
  texPath(`/tex/rates/contracts/${encodeURIComponent(d.contract)}/versions/${encodeURIComponent(d.version)}`) + hash

/** Open a version in the editor and wait for the room price matrix. */
export async function openVersion(page: Page, d: NewContract, hash = "#pricing") {
  await page.goto(versionPath(d, hash))
  await expect(page.getByRole("grid", { name: "Room prices by period", exact: true })).toBeVisible()
}

export interface Rows {
  period_rates: Record<string, unknown>[]
  occupancy_rules: Record<string, unknown>[]
  age_bands: Record<string, unknown>[]
  boards: Record<string, unknown>[]
  periods: Record<string, unknown>[]
  rooms: Record<string, unknown>[]
}

/** The saved rows of a version. */
export const readVersion = (page: Page, version: string) => pageApiOk<Rows>(page, "kamra.tex.api.contracts.get_version", { name: version })

/** The contracts API calls the page makes (by method name), with their request bodies. */
export function watchContracts(page: Page) {
  const seen: { m: string; body: unknown }[] = []
  page.on("request", (r: Request) => {
    const m = /kamra\.tex\.api\.contracts\.(\w+)/.exec(r.url())
    if (m) seen.push({ m: m[1], body: r.method() === "POST" ? r.postDataJSON() : null })
  })
  return {
    count: (m: string) => seen.filter((x) => x.m === m).length,
    bodies: (m: string) => seen.filter((x) => x.m === m).map((x) => x.body),
    reset: () => seen.splice(0, seen.length),
  }
}

/** Archives the contracts a spec made (after its tests, passed or not). */
export async function archiveAll(browser: Browser, contracts: string[], reason: string) {
  if (!contracts.length) return
  const page = await browser.newPage()
  await login(page, "revenue@demo.tex")
  for (const name of contracts)
    await page.request.post("/api/method/kamra.tex.api.contracts.set_contract_status", { data: { name, action: "archive", reason } }).catch(() => undefined)
  contracts.splice(0, contracts.length)
  await page.close()
}

/** "80.500000" → "80.50": a served decimal string shown with two decimals, the way the workspace
 * shows EUR amounts (only exact values; anything else is left as served, so a comparison fails). */
export const twoDecimals = (s: unknown) => String(s).replace(/^(-?\d+)\.(\d\d)0*$/, "$1.$2").replace(/^(-?\d+)$/, "$1.00")

export const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
