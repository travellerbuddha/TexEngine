// C-04 (owner, 2026-10-03; ADR-077): a loyalty member gets the program's members-only prices in the call centre.
// The revenue manager runs a loyalty program at Aurora Beach Resort (this run's, or one already enabled there)
// and puts a members-only promotion live. A guest books a stay through the public booking API (their profile).
// The reservations agent opens the guest in CRM → Loyalty: not a member; "Join program" makes them one. In the
// Call Center the agent names the guest as the caller and searches: Aurora's offers say "Member price" and the
// hotel says the caller is a member. Clearing the caller prices them again for nobody: no member price. Back in
// CRM the agent ends the membership with a reason. Clean-up: the stay is cancelled, the promotion archived and a
// program this run created disabled.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e crm-membership
import { expect, test, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test"
import { api, byLabel, login, pageApi, stayDates, texPath, trackErrors, uniqueRunId } from "./helpers"

test.use({ locale: "en-US" })

const SLUG = "aurora"
const HOTEL = "Aurora Beach Resort"
const AGENT = "agent@demo.tex"
const REVENUE = "revenue@demo.tex"

type Offers = { properties: { offers: { refundable: boolean; rooms: { offer_key: string }[] }[] }[] }
interface Program {
  name: string
  program_name: string
  property: string | null
  enabled: number
}
interface StaffSearch {
  properties: { property: string; member?: boolean; offers: { member_price?: boolean }[] }[]
}

const mdy = (iso: string) => `${iso.slice(5, 7)}${iso.slice(8, 10)}${iso.slice(0, 4)}`

/** A Flexible (refundable) stay through the public booking API, paid at the hotel: the guest's profile. */
async function bookStay(req: APIRequestContext, run: string, email: string) {
  const session_id = `e2e-member-${run.toLowerCase()}`
  for (let attempt = 0; attempt < 5; attempt++) {
    const { checkIn, checkOut } = stayDates(230 + attempt * 7, 2)
    const s = await api<Offers>(req, "kamra.tex.api.public.search", {
      site: SLUG,
      hotel: HOTEL,
      check_in: checkIn,
      check_out: checkOut,
      rooms: [{ adults: 2, children: [] }],
      session_id,
    })
    const offer = (s.properties[0]?.offers ?? []).find((o) => o.refundable)
    if (!offer) continue
    const q = await api<{ ok: boolean; quote_id: string }>(req, "kamra.tex.api.public.quote", { site: SLUG, offer_key: offer.rooms[0].offer_key, session_id })
    expect(q.ok, "quote").toBe(true)
    const b = await api<{ booking: string; rooms: { reservation: string }[] }>(req, "kamra.tex.api.public.book", {
      site: SLUG,
      quote_ids: [q.quote_id],
      guest: { first_name: "Mila", last_name: `Member ${run}`, email, phone: `+49 171 ${String(Date.now()).slice(-7)}`, country: "DE" },
      payment_method: "Pay at Hotel",
      idempotency_key: `e2e-member-${run}`,
      session_id,
    })
    return b.rooms[0].reservation
  }
  throw new Error(`no Flexible stay free at ${HOTEL} ~230–260 days ahead`)
}

/** A logged-in staff page in its own browser context (English, desktop). */
async function staff(browser: Browser, user: string, opened: BrowserContext[]): Promise<Page> {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "en-US", baseURL: test.info().project.use.baseURL })
  opened.push(ctx)
  const page = await ctx.newPage()
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex-lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
  await login(page, user)
  return page
}

const opened: BrowserContext[] = []
test.afterEach(async () => {
  for (const c of opened.splice(0)) await c.close()
})

test("a member joined in CRM gets the member price in the Call Center; the membership ends with a reason", async ({ browser, request }) => {
  test.setTimeout(240_000)
  const run = uniqueRunId()
  const email = `mila.${run.toLowerCase()}@example.com`
  const revenue = await staff(browser, REVENUE, opened)
  await revenue.goto(texPath("/tex/crm"))

  // the hotel's program: one enabled at Aurora already (an earlier run's), or this run's
  const listed = await pageApi<{ programs: Program[] }>(revenue, "kamra.tex.api.loyalty.programs")
  expect(listed.ok, JSON.stringify(listed.body).slice(0, 300)).toBeTruthy()
  let program = listed.message.programs.find((p) => p.property === HOTEL && p.enabled)?.name
  let created = false
  if (!program) {
    const saved = await pageApi<{ name: string }>(revenue, "kamra.tex.api.loyalty.save_program", {
      data: {
        program_name: `E2E members ${run}`,
        property: HOTEL,
        enabled: 1,
        currency: "EUR",
        point_value: "0.1",
        min_redeem_points: 50,
        max_redeem_percent: "50",
        pending_days: 0,
        expiry_months: 24,
        earn_rules: [{ basis: "STAY", rate: "25" }],
        tiers: [{ tier_name: "Silver", min_points: 0, earn_multiplier: "1" }],
        blackouts: [],
      },
    })
    expect(saved.ok, JSON.stringify(saved.body).slice(0, 300)).toBeTruthy()
    program = saved.message.name
    created = true
  }
  const promo = await pageApi<{ name: string }>(revenue, "kamra.tex.api.policies.save_record", {
    doctype: "TEX Promotion",
    data: {
      promotion_name: `E2E members 10 ${run}`,
      property: HOTEL,
      trigger: "Automatic",
      value_type: "PERCENT",
      value: 10,
      applies_to: "ACCOMMODATION",
      member_only: 1,
    },
  })
  expect(promo.ok, JSON.stringify(promo.body).slice(0, 300)).toBeTruthy()
  const live = await pageApi(revenue, "kamra.tex.api.policies.activate", { doctype: "TEX Promotion", name: promo.message.name })
  expect(live.ok, JSON.stringify(live.body).slice(0, 300)).toBeTruthy()

  const reservation = await bookStay(request, run, email)
  const agent = await staff(browser, AGENT, opened)
  const noErrors = trackErrors(agent)
  try {
    await agent.goto(texPath("/tex/crm"))
    const found = await pageApi<{ rows: { name: string }[] }>(agent, "kamra.tex.api.crm.guests", { q: email, limit: 5 })
    expect(found.ok).toBeTruthy()
    const guest = found.message.rows[0].name
    const memberships = agent.getByRole("list", { name: "Loyalty membership" })
    const row = memberships.getByRole("listitem").first()

    await test.step("CRM: the agent joins the guest to the program", async () => {
      await agent.goto(texPath(`/tex/crm/guests/${encodeURIComponent(guest)}`))
      await expect(agent.getByRole("heading", { level: 1, name: `Mila Member ${run}` })).toBeVisible()
      await agent.getByRole("tab", { name: /^Loyalty/ }).click()
      await expect(row).toContainText("Not a member")
      await row.getByRole("button", { name: "Join program" }).click()
      const dialog = agent.getByRole("dialog")
      await expect(dialog).toContainText("only with their agreement")
      await Promise.all([
        agent.waitForResponse((r) => r.url().includes("kamra.tex.api.crm.loyalty_join") && r.ok()),
        dialog.getByRole("button", { name: "Join program" }).click(),
      ])
      await expect(dialog).toBeHidden()
      await expect(row).toContainText("Member")
      await expect(row).toContainText(/since /)
      await expect(row.getByRole("button", { name: "End membership" })).toBeVisible()
    })

    await test.step("Call Center: the caller named is priced as a member", async () => {
      await agent.goto(texPath("/tex/crs/call-center"))
      await expect(agent.getByRole("heading", { level: 1, name: "Call Center" })).toBeVisible()
      const caller = agent.getByRole("combobox", { name: "Find caller" })
      await caller.fill(`Member ${run}`)
      await agent.getByRole("option", { name: new RegExp(`Member ${run}`) }).first().click()
      await expect(agent.getByRole("button", { name: "Clear caller" })).toBeVisible()
      const market = byLabel(agent, "Market")
      await market.focus()
      await agent.keyboard.type("Germ")
      await expect(market).toHaveValue("DE")
      const { checkIn } = stayDates(120, 2)
      await byLabel(agent, "Check-in").focus()
      await agent.keyboard.type(mdy(checkIn))
      const [answer] = await Promise.all([
        agent.waitForResponse((r) => r.url().includes("ui_crs.search") && r.ok()),
        agent.keyboard.press("Alt+KeyS"),
      ])
      const res = ((await answer.json()) as { message: StaffSearch }).message
      const aurora = res.properties.find((p) => p.property === HOTEL)
      expect(aurora?.member, "the caller is a member at Aurora").toBe(true)
      expect(aurora?.offers.some((o) => o.member_price), "a member price at Aurora").toBe(true)
      const offers = agent.getByRole("listbox", { name: "Offers" })
      await expect(offers.getByText("caller is a member: member prices").first()).toBeVisible()
      await expect(offers.getByText("Member price", { exact: true }).first()).toBeVisible()

      // no caller: the offers are priced again for nobody
      const [again] = await Promise.all([
        agent.waitForResponse((r) => r.url().includes("ui_crs.search") && r.ok()),
        agent.getByRole("button", { name: "Clear caller" }).click(),
      ])
      const plain = ((await again.json()) as { message: StaffSearch }).message
      expect(plain.properties.some((p) => p.member || p.offers.some((o) => o.member_price))).toBe(false)
      await expect(offers.getByText("Member price", { exact: true })).toHaveCount(0)
    })

    await test.step("CRM: the agent ends the membership with a reason", async () => {
      await agent.goto(texPath(`/tex/crm/guests/${encodeURIComponent(guest)}`))
      await agent.getByRole("tab", { name: /^Loyalty/ }).click()
      await row.getByRole("button", { name: "End membership" }).click()
      const dialog = agent.getByRole("dialog")
      const end = dialog.getByRole("button", { name: "End membership" })
      await expect(end).toBeDisabled()                                  // a reason first
      await byLabel(dialog, "Reason").fill("Guest asked to leave (E2E)")
      await Promise.all([agent.waitForResponse((r) => r.url().includes("kamra.tex.api.crm.loyalty_leave") && r.ok()), end.click()])
      await expect(dialog).toBeHidden()
      await expect(row).toContainText("Left")
      await expect(row.getByRole("button", { name: "Join program" })).toBeVisible()
    })
    noErrors()
  } finally {
    await pageApi(agent, "kamra.tex.api.crs.cancel", { reservation, reason: "E2E clean-up (membership)" })
    await pageApi(revenue, "kamra.tex.api.policies.archive", { doctype: "TEX Promotion", name: promo.message.name, reason: "E2E clean-up (membership)" })
    if (created) await pageApi(revenue, "kamra.tex.api.loyalty.set_enabled", { name: program, enabled: 0 })
  }
})
