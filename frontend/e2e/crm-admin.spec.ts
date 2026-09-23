// G-23 / G-24 (ADR-036, ADR-037): guest segments and loyalty programs administered in TEX.
// Segments: the revenue manager (crm.view, no crm.edit) sees the shared presets and counts
// one for the selected hotel (the same count as the server's); presets are read-only and
// they cannot create a segment. A reservations agent (crm.edit) creates a segment with a
// money condition in EUR and a new fact (travels with children), sees its count, opens its
// guests, and deletes it. Loyalty: the revenue manager (loyalty.edit) creates a disabled
// program for Aurora City Hotel with a MONEY earn rule, a tier and a redemption blackout;
// reopened, every value is as saved (and the API agrees). The agent (crm.view, no
// loyalty.edit) sees it read-only. The program is deleted at the end.
// Names are unique per run; whatever a test created is removed even when it fails.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e crm-admin
import { expect, request as pwRequest, test, type Browser, type BrowserContext, type Locator, type Page } from "@playwright/test"
import { ADMIN_PASSWORD, byLabel, esc, isoDate, login, pageApi, texPath, trackErrors, uniqueRunId } from "./helpers"
import { expectSuccess } from "./flows/contracts"

const REVENUE = "revenue@demo.tex"
const AGENT = "agent@demo.tex"
const CITY = "Aurora City Hotel"
/** The presets every tenant shares (ADR-036), as the UI names them in English. */
const PRESETS = [
  "Repeat guests",
  "VIP",
  "Email opt-in",
  "No stay in 12 months",
  "Families",
  "Last-minute bookers",
  "Cancelled in the last 90 days",
  "Abandoned a booking (30 days)",
  "Birthday in the next 30 days",
]

interface Segment {
  name: string
  segment_name: string
  system_key: string | null
  rules_json: string
}
interface Program {
  name: string
  program_name: string
  property: string | null
  hotel_group: string | null
  enabled: number
  currency: string | null
  point_value: string
  min_redeem_points: number
  max_redeem_percent: string
  pending_days: number
  expiry_months: number
  can_edit: boolean
  earn_rules: { basis: string; rate: string; date_from: string | null; date_to: string | null }[]
  tiers: { tier_name: string; min_points: number; earn_multiplier: string }[]
  blackouts: { date_from: string; date_to: string; applies_to: string; note: string | null }[]
}

async function english(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex-lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
}

/** A logged-in staff page in its own browser context (English, desktop). */
async function staff(browser: Browser, user: string, opened: BrowserContext[]) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "en-US", baseURL: test.info().project.use.baseURL })
  opened.push(ctx)
  const page = await ctx.newPage()
  await english(page)
  await login(page, user)
  return page
}

const opened: BrowserContext[] = []
test.afterEach(async () => {
  for (const c of opened.splice(0)) await c.close()
})

/** The hotel selected in the shell. */
const shellHotel = (page: Page) => page.getByRole("banner").getByRole("combobox", { name: "Hotel", exact: true }).inputValue()

/** A segment's count line ("12 members", "1 member") once counted. */
async function countLine(page: Page): Promise<number> {
  const line = page.getByText(/^\d[\d,]* members?$/)
  await expect(line).toBeVisible()
  return Number(((await line.textContent()) ?? "").replace(/\D/g, ""))
}

/** Exactly this decimal value as text: "50" matches "50" and "50.0", "0.05" matches "0.050"
 * (the server returns stored decimals as it reads them; the value must not change). */
function decimalOf(v: string) {
  const [i, f = ""] = v.split(".")
  const frac = f.replace(/0+$/, "")
  return new RegExp(`^${i}${frac ? `\\.${frac}0*` : "(\\.0*)?"}$`)
}

/** Clean-up of what a run created: through the TEX API as the user, else (when that very
 * delete is what failed) by the platform administrator, so demo data is left as found. */
async function removeCreated(page: Page, method: string, args: Record<string, string>, doctype: string, name: string) {
  const r = await pageApi(page, method, args)
  if (r.ok) return
  const ctx = await pwRequest.newContext({ baseURL: test.info().project.use.baseURL })
  try {
    const ok = await ctx.post("/api/method/login", { data: { usr: "Administrator", pwd: ADMIN_PASSWORD } })
    if (ok.ok()) await ctx.post("/api/method/frappe.client.delete", { data: { doctype, name } })
  } finally {
    await ctx.dispose()
  }
}

/** Confirm a dialog and expect the success toast; a refusal the dialog shows fails the step
 * with the server's message instead of a timeout. */
async function confirmIn(page: Page, dialog: Locator, button: string, toast: string) {
  await dialog.getByRole("button", { name: button, exact: true }).click()
  const refused = dialog.getByRole("alert")
  const done = page.locator("[aria-live]").getByRole("status").filter({ hasText: toast })
  await expect(done.or(refused).first()).toBeVisible()
  if (await refused.isVisible()) throw new Error(`${button} refused: ${(await refused.innerText()).trim()}`)
}

/** A numbered row (earn rule, tier, blackout) of the program editor. */
const row = (page: Page, title: string) =>
  page.getByRole("listitem").filter({ has: page.getByRole("heading", { level: 3, name: title, exact: true }) })

test("segments: presets are shared and read-only; a segment with a money condition and a new fact is created, used and deleted", async ({
  page,
  browser,
}) => {
  test.setTimeout(180_000)
  const run = uniqueRunId()
  const segName = `E2E segment ${run}`
  let created = ""
  const noErrors = trackErrors(page)
  await english(page)

  await test.step("revenue manager: CRM → Segments shows the presets; one is counted", async () => {
    await login(page, REVENUE)
    await page.goto(texPath("/tex"))
    await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "CRM", exact: true }).click()
    await page.getByRole("navigation", { name: "CRM sections" }).getByRole("link", { name: "Segments", exact: true }).click()
    await expect(page).toHaveURL(/\/tex\/crm\/segments/)
    await expect(page.getByRole("heading", { level: 1, name: "Segments" })).toBeVisible()

    const presets = page.getByRole("region", { name: "Presets" })
    for (const p of PRESETS) await expect(presets.getByRole("button", { name: new RegExp(`^${esc(p)}`) }), p).toBeVisible()
    // no crm.edit: nothing can be created or copied
    await expect(page.getByRole("button", { name: "New segment" })).toHaveCount(0)

    await presets.getByRole("button", { name: /^Families/ }).click()
    await expect(page.getByRole("heading", { level: 2, name: "Families", exact: true })).toBeVisible()
    await expect(page.getByText("Preset: read-only. Copy it to your segments to change it.")).toBeVisible()
    await expect(page.getByRole("button", { name: "Copy to my segments" })).toHaveCount(0)
    // the preset's rule is shown, not editable
    await expect(page.getByRole("combobox", { name: "Field of condition 1" })).toBeDisabled()

    const hotel = await shellHotel(page)
    await page.getByRole("button", { name: "Count members", exact: true }).click()
    const shown = await countLine(page)
    await expect(page.getByText("at the selected hotel", { exact: true })).toBeVisible()
    const segs = await pageApi<{ segments: Segment[] }>(page, "kamra.tex.api.crm.segments")
    const families = segs.message.segments.find((s) => s.system_key === "FAMILY")
    expect(families, "the Families preset").toBeTruthy()
    const server = await pageApi<{ members: number }>(page, "kamra.tex.api.crm.evaluate_segment", { segment: families!.name, property: hotel })
    expect(server.ok).toBeTruthy()
    expect(shown).toBe(server.message.members)
    // the list badge shows the same count
    await expect(presets.getByRole("button", { name: /^Families/ })).toContainText(String(shown))
  })

  const sp = await staff(browser, AGENT, opened)
  const noAgentErrors = trackErrors(sp)
  try {
    await test.step("reservations agent: a new segment with a EUR money condition and a new fact", async () => {
      await sp.goto(texPath("/tex/crm/segments"))
      await sp.getByRole("button", { name: "New segment", exact: true }).click()
      await expect(sp.getByRole("heading", { level: 2, name: "New segment" })).toBeVisible()
      await byLabel(sp, "Name").fill(segName)
      await byLabel(sp, "Description").fill("Big spenders in EUR or families (E2E)")
      await sp.getByRole("radiogroup", { name: "Combine conditions" }).getByRole("radio", { name: "Any (or)" }).click()

      // condition 1: lifetime value ≥ 1500.50 EUR (money is typed as text, never a float)
      await sp.getByRole("combobox", { name: "Field of condition 1" }).selectOption({ label: "Lifetime value" })
      await sp.getByRole("combobox", { name: "Operator of condition 1" }).selectOption({ label: "is at least" })
      await sp.getByRole("textbox", { name: "Value for Lifetime value" }).fill("1500.50")
      await sp.getByRole("combobox", { name: "Currency for Lifetime value" }).selectOption("EUR")
      // condition 2: a new fact (ADR-036)
      await sp.getByRole("button", { name: "Add condition", exact: true }).click()
      await sp.getByRole("combobox", { name: "Field of condition 2" }).selectOption({ label: "Travels with children" })
      await expect(sp.getByRole("combobox", { name: "Operator of condition 2" })).toHaveValue("is")
      await sp.getByRole("combobox", { name: "Value for Travels with children" }).selectOption({ label: "Yes" })
      await expect(sp.getByText("At least one booked or completed stay at your hotels included children.")).toBeVisible()

      const hotel = await shellHotel(sp)
      await sp.getByRole("button", { name: "Create segment", exact: true }).click()
      await expectSuccess(sp, "Segment saved")
      await expect(sp).toHaveURL(/[?&]s=[^&]+/)
      created = decodeURIComponent(new URL(sp.url()).searchParams.get("s") ?? "")
      expect(created).not.toBe("")
      await expect(sp.getByRole("heading", { level: 2, name: segName })).toBeVisible()
      await expect(sp.getByRole("region", { name: "My segments" }).getByRole("button", { name: new RegExp(`^${esc(segName)}`) })).toBeVisible()

      // stored exactly as entered: a decimal string with its currency, a boolean fact
      const segs = await pageApi<{ segments: Segment[] }>(sp, "kamra.tex.api.crm.segments")
      const mine = segs.message.segments.find((s) => s.name === created)
      expect(mine?.segment_name).toBe(segName)
      expect(JSON.parse(mine!.rules_json)).toEqual({
        match: "any",
        conditions: [
          { field: "lifetime_value", op: "gte", value: "1500.50", currency: "EUR" },
          { field: "has_children", op: "is", value: true },
        ],
      })

      // counted right after saving, for the selected hotel, as the server counts it
      const shown = await countLine(sp)
      const server = await pageApi<{ members: number }>(sp, "kamra.tex.api.crm.evaluate_segment", { segment: created, property: hotel })
      expect(shown).toBe(server.message.members)

      // its guests: the guest list filtered by the segment shows the same members
      await sp.getByRole("link", { name: "View guests", exact: true }).click()
      await expect(sp).toHaveURL(new RegExp(`/tex/crm\\?segment=${esc(encodeURIComponent(created))}`))
      await expect(byLabel(sp, "Segment")).toHaveValue(created)
      const table = sp.getByRole("table", { name: "Guests" })
      if (shown === 0) {
        await expect(sp.getByText("No guests match these filters")).toBeVisible()
      } else {
        await expect(table.locator("tbody tr")).toHaveCount(Math.min(shown, 25))
        if (shown > 25) await expect(sp.getByRole("navigation", { name: "Pages" })).toContainText(`of ${shown}`)
      }
    })

    await test.step("the agent deletes the segment", async () => {
      await sp.goto(texPath(`/tex/crm/segments?s=${encodeURIComponent(created)}`))
      await expect(sp.getByRole("heading", { level: 2, name: segName })).toBeVisible()
      await sp.getByRole("button", { name: "Delete", exact: true }).click()
      const dialog = sp.getByRole("dialog", { name: "Delete this segment?" })
      await expect(dialog).toContainText(segName)
      await confirmIn(sp, dialog, "Delete", "Segment deleted")
      await expect(sp.getByRole("region", { name: "My segments" }).getByRole("button", { name: new RegExp(`^${esc(segName)}`) })).toHaveCount(0)
      const segs = await pageApi<{ segments: Segment[] }>(sp, "kamra.tex.api.crm.segments")
      expect(segs.message.segments.some((s) => s.name === created)).toBe(false)
      created = ""
    })
    noAgentErrors()
  } finally {
    if (created) await removeCreated(sp, "kamra.tex.api.crm.delete_segment", { segment: created }, "TEX Guest Segment", created)
  }
  noErrors()
})

test("loyalty: a program with a money earn rule, a tier and a redemption blackout; read-only without loyalty.edit", async ({ page, browser }) => {
  test.setTimeout(180_000)
  const run = uniqueRunId()
  const progName = `E2E loyalty ${run}`
  const blackout = { from: isoDate(200), to: isoDate(207) }
  let created = ""
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, REVENUE)

  try {
    await test.step("revenue manager: CRM → Loyalty → New program for Aurora City Hotel (disabled)", async () => {
      await page.goto(texPath("/tex/crm"))
      await page.getByRole("navigation", { name: "CRM sections" }).getByRole("link", { name: "Loyalty", exact: true }).click()
      await expect(page.getByRole("heading", { level: 1, name: "Loyalty programs" })).toBeVisible()
      await page.getByRole("button", { name: "New program", exact: true }).click()
      await expect(page).toHaveURL(/\/tex\/crm\/loyalty\/new$/)
      await expect(page.getByRole("heading", { level: 1, name: "New loyalty program" })).toBeVisible()

      await byLabel(page, "Name").fill(progName)
      const scope = page.getByRole("group", { name: "Belongs to" })
      const oneHotel = scope.getByRole("radio", { name: "One hotel" })
      if (await oneHotel.count()) await oneHotel.click()
      await scope.getByRole("combobox", { name: "Hotel", exact: true }).selectOption({ label: CITY })
      // disabled, so the demo hotels' selling is unaffected
      const enabled = page.getByRole("switch", { name: "Enabled" })
      if ((await enabled.getAttribute("aria-checked")) === "true") await enabled.click()
      await expect(enabled).toHaveAttribute("aria-checked", "false")
      await byLabel(page, "Currency").selectOption("EUR")
      await byLabel(page, "Value of one point").fill("0.05")
      await byLabel(page, "Minimum points to redeem").fill("100")
      await byLabel(page, "Max. share of a stay payable with points").fill("50")
      await byLabel(page, "Pending days").fill("2")
      await byLabel(page, "Expiry (months)").fill("36")

      // earn rule 1 (a new program starts with one): points per EUR spent
      const rule = row(page, "Earn rule 1")
      await expect(byLabel(rule, "Earn on")).toHaveValue("MONEY")
      await byLabel(rule, "Points").fill("1.5")
      await expect(rule.getByText("Points per unit of the program currency spent; stays in another currency earn nothing.")).toBeVisible()

      await page.getByRole("button", { name: "Add tier", exact: true }).click()
      const tier = row(page, "Tier 1")
      await byLabel(tier, "Tier name").fill("Gold")
      await byLabel(tier, "From points earned in total").fill("1000")
      await byLabel(tier, "Earn multiplier").fill("1.25")

      await page.getByRole("button", { name: "Add blackout", exact: true }).click()
      const bo = row(page, "Blackout 1")
      await byLabel(bo, "From").fill(blackout.from)
      await byLabel(bo, "To").fill(blackout.to)
      await byLabel(bo, "Applies to").selectOption({ label: "Redemption" })
      await byLabel(bo, "Note").fill(`E2E ${run}`)

      await page.getByRole("button", { name: "Create program", exact: true }).click()
      await expectSuccess(page, "Program created")
      await expect(page).toHaveURL(/\/tex\/crm\/loyalty\/(?!new$)[^/?]+$/)
      created = decodeURIComponent(new URL(page.url()).pathname.split("/").pop() ?? "")
      expect(created).not.toBe("")
    })

    await test.step("reopened, the program shows what was saved (and the API agrees)", async () => {
      await page.reload()
      await expect(page.getByRole("heading", { level: 1, name: progName })).toBeVisible()
      await expect(page.getByText(CITY, { exact: true }).first()).toBeVisible()
      await expect(page.getByText("Disabled", { exact: true }).first()).toBeVisible()
      await expect(byLabel(page, "Name")).toHaveValue(progName)
      await expect(page.getByRole("group", { name: "Belongs to" }).getByRole("combobox", { name: "Hotel", exact: true })).toHaveValue(CITY)
      await expect(byLabel(page, "Currency")).toHaveValue("EUR")
      await expect(byLabel(page, "Value of one point")).toHaveValue(decimalOf("0.05"))
      await expect(byLabel(page, "Minimum points to redeem")).toHaveValue("100")
      await expect(byLabel(page, "Max. share of a stay payable with points")).toHaveValue(decimalOf("50"))
      await expect(byLabel(page, "Pending days")).toHaveValue("2")
      await expect(byLabel(page, "Expiry (months)")).toHaveValue("36")
      const rule = row(page, "Earn rule 1")
      await expect(byLabel(rule, "Earn on")).toHaveValue("MONEY")
      await expect(byLabel(rule, "Points")).toHaveValue(decimalOf("1.5"))
      await expect(row(page, "Earn rule 2")).toHaveCount(0)
      const tier = row(page, "Tier 1")
      await expect(byLabel(tier, "Tier name")).toHaveValue("Gold")
      await expect(byLabel(tier, "From points earned in total")).toHaveValue("1000")
      await expect(byLabel(tier, "Earn multiplier")).toHaveValue(decimalOf("1.25"))
      const bo = row(page, "Blackout 1")
      await expect(byLabel(bo, "From")).toHaveValue(blackout.from)
      await expect(byLabel(bo, "To")).toHaveValue(blackout.to)
      await expect(byLabel(bo, "Applies to")).toHaveValue("Redemption")
      await expect(byLabel(bo, "Note")).toHaveValue(`E2E ${run}`)
      // nothing to save after a reload
      await expect(page.getByRole("button", { name: "Save program", exact: true })).toBeDisabled()

      const p = await pageApi<Program>(page, "kamra.tex.api.loyalty.program", { name: created })
      expect(p.ok, JSON.stringify(p.body).slice(0, 300)).toBeTruthy()
      expect(p.message).toMatchObject({
        program_name: progName,
        property: CITY,
        enabled: 0,
        currency: "EUR",
        point_value: expect.stringMatching(decimalOf("0.05")),
        min_redeem_points: 100,
        max_redeem_percent: expect.stringMatching(decimalOf("50")),
        pending_days: 2,
        expiry_months: 36,
        can_edit: true,
      })
      expect(p.message.earn_rules).toEqual([expect.objectContaining({ basis: "MONEY", rate: expect.stringMatching(decimalOf("1.5")) })])
      expect(p.message.tiers).toEqual([
        expect.objectContaining({ tier_name: "Gold", min_points: 1000, earn_multiplier: expect.stringMatching(decimalOf("1.25")) }),
      ])
      expect(p.message.blackouts).toEqual([
        expect.objectContaining({ date_from: blackout.from, date_to: blackout.to, applies_to: "Redemption", note: `E2E ${run}` }),
      ])

      // the list shows it disabled
      await page.getByRole("navigation", { name: "CRM sections" }).getByRole("link", { name: "Loyalty", exact: true }).click()
      const listRow = page.getByRole("table", { name: "Loyalty programs" }).locator("tbody tr").filter({ hasText: progName })
      await expect(listRow).toHaveCount(1)
      await expect(listRow).toContainText("Disabled")
      await expect(listRow).toContainText(CITY)
    })

    await test.step("reservations agent (no loyalty.edit): the program is read-only", async () => {
      const ap = await staff(browser, AGENT, opened)
      const noAgentErrors = trackErrors(ap)
      await ap.goto(texPath("/tex/crm/loyalty"))
      await expect(ap.getByRole("heading", { level: 1, name: "Loyalty programs" })).toBeVisible()
      await expect(ap.getByRole("button", { name: "New program" })).toHaveCount(0)
      const listRow = ap.getByRole("table", { name: "Loyalty programs" }).locator("tbody tr").filter({ hasText: progName })
      await expect(listRow).toContainText("View only")
      await listRow.click()
      await expect(ap.getByRole("heading", { level: 1, name: progName })).toBeVisible()
      await expect(ap.getByText("You can view this program. Changing it needs “Edit loyalty programs” at every hotel it covers.")).toBeVisible()
      await expect(byLabel(ap, "Name")).toBeDisabled()
      await expect(byLabel(ap, "Name")).toHaveValue(progName)
      await expect(byLabel(ap, "Value of one point")).toBeDisabled()
      await expect(byLabel(row(ap, "Earn rule 1"), "Points")).toBeDisabled()
      await expect(byLabel(row(ap, "Tier 1"), "Tier name")).toBeDisabled()
      await expect(byLabel(row(ap, "Blackout 1"), "Applies to")).toBeDisabled()
      for (const b of ["Save program", "Create program", "Add earn rule", "Add tier", "Add blackout", "Enable", "Disable", "Delete"])
        await expect(ap.getByRole("button", { name: b, exact: true }), b).toHaveCount(0)
      await expect(ap.getByRole("button", { name: /^Remove / })).toHaveCount(0)
      // the server refuses a save too
      const refused = await pageApi(ap, "kamra.tex.api.loyalty.save_program", { data: { name: created, program_name: `${progName} (agent)` } })
      expect(refused.ok).toBe(false)
      expect(refused.status).toBe(403)
      noAgentErrors()
    })

    await test.step("revenue manager deletes the program", async () => {
      await page.goto(texPath(`/tex/crm/loyalty/${encodeURIComponent(created)}`))
      await expect(page.getByRole("heading", { level: 1, name: progName })).toBeVisible()
      await page.getByRole("button", { name: "Delete", exact: true }).click()
      await confirmIn(page, page.getByRole("dialog", { name: "Delete this program?" }), "Delete", "Program deleted")
      await expect(page).toHaveURL(/\/tex\/crm\/loyalty$/)
      await expect(page.getByRole("table", { name: "Loyalty programs" }).locator("tbody tr").filter({ hasText: progName })).toHaveCount(0)
      const gone = await pageApi(page, "kamra.tex.api.loyalty.program", { name: created })
      expect(gone.ok).toBe(false)
      created = ""
    })
  } finally {
    if (created) await removeCreated(page, "kamra.tex.api.loyalty.delete_program", { name: created }, "TEX Loyalty Program", created)
  }
  noErrors()
})
