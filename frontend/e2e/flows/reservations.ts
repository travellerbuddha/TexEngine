// R-21–R-23 reservation steps, reusable in journeys (R-58): open a reservation, read its
// locked price, propose a change (OLD vs NEW shown before applying), apply it with an
// audited reason, read the revision history. Every step drives the TEX UI with role/label
// locators; figures come from the page's <data value> (the server's decimal string), never
// recomputed. The English UI is assumed; pass a Page that is already logged in.
import { expect, type Locator, type Page } from "@playwright/test"
import { byLabel, texPath } from "../helpers"

export type Basis = "CURRENT" | "ORIGINAL_VERSION" | "ORIGINAL_SALE_DATE" | "HISTORICAL_SALE_DATE"

/** A figure as the page shows it: the server's decimal (`amount`) and the formatted text. */
export interface ShownAmount {
  amount: string | null
  text: string
}

export interface ProposedChange {
  old: ShownAmount
  proposed: ShownAmount
  difference: ShownAmount
}

export interface AppliedChange {
  reservation: string
  revision: string
  old_total: string
  new_total: string
  difference: string
  currency: string
}

export interface RevisionRow {
  revision: number
  changeType: string
  oldAmount: string | null
  newAmount: string | null
  currency: string | null
  text: string
}

const BASIS_LABEL: Record<Basis, RegExp> = {
  CURRENT: /^Current prices/,
  ORIGINAL_VERSION: /^Original contract version/,
  ORIGINAL_SALE_DATE: /^Original sale date/,
  HISTORICAL_SALE_DATE: /^Chosen sale date/,
}

const clean = (s: string) => s.replace(/\s+/g, " ").trim()

/** The figure in a labelled group: its <data value> and the text shown (without the caption). */
async function shown(group: Locator): Promise<ShownAmount> {
  const data = group.locator("data[value]").first()
  if (await data.count()) return { amount: await data.getAttribute("value"), text: clean(await data.innerText()) }
  const lines = (await group.innerText()).split("\n").map(clean).filter(Boolean)
  return { amount: null, text: lines.slice(1).join(" ") }
}

const modifyDrawer = (page: Page) => page.getByRole("dialog", { name: /^Modify / })

/**
 * Open a reservation's detail page, by name or through its booking (`room`: the booking's
 * n-th room, 0-based). Returns the reservation name.
 */
export async function openReservation(page: Page, opts: { reservation?: string; booking?: string; room?: number }): Promise<string> {
  let name = opts.reservation
  if (name) {
    await page.goto(texPath(`/tex/reservations/${encodeURIComponent(name)}`))
  } else {
    if (!opts.booking) throw new Error("openReservation needs a reservation or a booking")
    await page.goto(texPath(`/tex/reservations/booking/${encodeURIComponent(opts.booking)}`))
    const rows = page.getByRole("table", { name: /^\d+ rooms?$/ }).getByRole("row").filter({ hasText: /RES-/ })
    await expect(rows.first()).toBeVisible()
    const row = rows.nth(opts.room ?? 0)
    name = (await row.innerText()).match(/RES-[\w-]+/)?.[0]
    if (!name) throw new Error(`no reservation in room ${opts.room ?? 0} of ${opts.booking}`)
    await row.click()
  }
  await expect(page.getByRole("heading", { level: 1, name: new RegExp(name) })).toBeVisible()
  await expect(page.getByRole("region", { name: "Locked price" })).toBeVisible()
  return name
}

/** The reservation's stored (price-locked) total. */
export async function readLockedPrice(page: Page): Promise<ShownAmount> {
  const total = page.getByRole("region", { name: "Locked price" }).locator("data[value]").first()
  await expect(total).toBeVisible()
  return { amount: await total.getAttribute("value"), text: clean(await total.innerText()) }
}

/**
 * Open "Modify" (unless it is open), change what is given, pick the pricing basis and
 * calculate. Returns the OLD (locked) and PROPOSED totals and the difference exactly as
 * shown before anything is applied; the drawer stays open for `applyChange`.
 * `saleAt` ("YYYY-MM-DDTHH:mm", server clock) goes with basis HISTORICAL_SALE_DATE.
 */
export async function proposeChange(
  page: Page,
  change: { checkIn?: string; checkOut?: string; adults?: number; childrenAges?: number[]; basis?: Basis; saleAt?: string },
): Promise<ProposedChange> {
  const drawer = modifyDrawer(page)
  if (!(await drawer.isVisible())) {
    await page.getByRole("button", { name: "Modify", exact: true }).click()
    await expect(drawer).toBeVisible()
  }
  if (change.checkIn) await byLabel(drawer, "Check-in").fill(change.checkIn)
  if (change.checkOut) await byLabel(drawer, "Check-out").fill(change.checkOut)
  if (change.adults !== undefined) await byLabel(drawer, "Adults").fill(String(change.adults))
  if (change.childrenAges) {
    await byLabel(drawer, "Children").fill(String(change.childrenAges.length))
    for (const [i, age] of change.childrenAges.entries()) await byLabel(drawer, `Child ${i + 1} age`).selectOption(String(age))
  }
  if (change.basis) await drawer.getByRole("radio", { name: BASIS_LABEL[change.basis] }).check()
  if (change.saleAt) await byLabel(drawer, "Sale date and time").fill(change.saleAt)

  const [resp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("crs.propose_modification")),
    drawer.getByRole("button", { name: /^(Calculate new price|Recalculate)$/ }).click(),
  ])
  expect(resp.ok(), `propose_modification ${resp.status()}`).toBeTruthy()

  const result = drawer.getByRole("region", { name: "Old vs new price" })
  const old = result.getByRole("group", { name: "Current (price-locked)" })
  await expect(old).toBeVisible()
  return {
    old: await shown(old),
    proposed: await shown(result.getByRole("group", { name: "Proposed" })),
    difference: await shown(result.getByRole("group", { name: "Difference" })),
  }
}

/**
 * Apply the open proposal with an audited reason. Returns the server's answer and waits
 * until the detail page shows the new revision, so `readLockedPrice` / `readRevisions`
 * read the result.
 */
export async function applyChange(page: Page, reason: string): Promise<AppliedChange> {
  const drawer = modifyDrawer(page)
  const revisions = page.getByRole("list", { name: "Revision history" }).locator("li[data-revision]")
  const before = await revisions.count()
  await byLabel(drawer, "Reason").fill(reason)
  const [resp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("crs.apply_modification")),
    drawer.getByRole("button", { name: "Apply change", exact: true }).click(),
  ])
  const body = (await resp.json().catch(() => ({}))) as { message?: AppliedChange }
  expect(resp.ok(), `apply_modification ${resp.status()}: ${JSON.stringify(body).slice(0, 300)}`).toBeTruthy()
  await expect(drawer).toBeHidden()
  await expect(revisions).toHaveCount(before + 1)
  return body.message!
}

/** Revision history entries, newest first (the last one is "Original"). */
export async function readRevisions(page: Page): Promise<RevisionRow[]> {
  const list = page.getByRole("list", { name: "Revision history" })
  await expect(list).toBeVisible()
  // one entry per revision; each nests its own list of changed fields
  const items = list.locator("li[data-revision]")
  const out: RevisionRow[] = []
  for (let i = 0; i < (await items.count()); i++) {
    const li = items.nth(i)
    out.push({
      revision: Number(await li.getAttribute("data-revision")),
      changeType: (await li.getAttribute("data-change-type")) ?? "",
      oldAmount: (await li.getAttribute("data-old-amount")) || null,
      newAmount: (await li.getAttribute("data-new-amount")) || null,
      currency: (await li.getAttribute("data-currency")) || null,
      text: clean(await li.innerText()),
    })
  }
  return out
}
