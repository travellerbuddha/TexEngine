// G-65 / G-95 (ADR-056): the CRM guest profile shows what the guest bought and cancelled at the
// viewer's hotels, and the pricing internals of a stay never leave through REST.
// A guest books two stays at Aurora Beach Resort through the public booking API (Flexible rate,
// paid at the hotel), the first with an airport transfer; staff cancel the second. The
// reservations agent opens the guest in CRM → Guests:
// - the key figures show one cancellation and whether a fee was charged (the server's answer);
// - the Extras tab lists the transfer with the server's amount and a summary per extra;
// - the Stays tab shows the cancelled stay;
// - the loyalty accounts are programs of the agent's own hotels only (the API agrees).
// The revenue manager (price.view_cost) reads the stay's price explanation through the TEX API,
// while REST (/api/resource) withholds the snapshot, cost and margin (a list leaves them out) and
// refuses to filter on them. Both stays are cancelled at the end (free under the Flexible rate).
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e crm-profile
import { expect, test, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test"
import { api, login, pageApi, stayDates, texPath, trackErrors, uniqueRunId } from "./helpers"

const SLUG = "aurora"
const HOTEL = "Aurora Beach Resort"
const AGENT = "agent@demo.tex"
const REVENUE = "revenue@demo.tex"
const TRANSFER = { code: "TRF", name: "Airport transfer" }

interface Booked {
  booking: string
  reservation: string
}
interface ProfileResponse {
  guest: { name: string; full_name: string | null }
  stays: { name: string; status: string }[]
  loyalty: { program: string }[]
  extras: { reservation: string; code: string; name: string; quantity: string; amount: string; currency: string }[]
  extras_summary: { code: string; quantity: string; amount: string; currency: string; stays: number }[]
  cancellations: { count: number; no_shows: number; fees: { currency: string; amount: string }[] }
  hotels: string[]
}

type Offers = { properties: { offers: { refundable: boolean; rooms: { offer_key: string }[] }[] }[] }

/** A Flexible (refundable) stay through the public booking API, paid at the hotel. */
async function bookStay(req: APIRequestContext, run: string, label: string, email: string, phone: string, extras: { code: string; quantity: number }[]): Promise<Booked> {
  const session_id = `e2e-crm-${label}-${run.toLowerCase()}`
  for (let attempt = 0; attempt < 5; attempt++) {
    const { checkIn, checkOut } = stayDates(200, 3)
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
    const q = await api<{ ok: boolean; quote_id: string }>(req, "kamra.tex.api.public.quote", {
      site: SLUG,
      offer_key: offer.rooms[0].offer_key,
      extras,
      session_id,
    })
    expect(q.ok, "quote").toBe(true)
    const b = await api<{ booking: string; rooms: { reservation: string }[] }>(req, "kamra.tex.api.public.book", {
      site: SLUG,
      quote_ids: [q.quote_id],
      guest: { first_name: "Ines", last_name: `Profile ${run}`, email, phone, country: "DE" },
      payment_method: "Pay at Hotel",
      idempotency_key: `e2e-crm-${label}-${run}`,
      session_id,
    })
    return { booking: b.booking, reservation: b.rooms[0].reservation }
  }
  throw new Error(`no Flexible stay free at ${HOTEL} ~200–320 days ahead`)
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

test("the guest profile shows extras and cancellations at the viewer's hotels; REST never shows the pricing internals", async ({ browser, request }) => {
  test.setTimeout(180_000)
  const run = uniqueRunId()
  const email = `ines.${run.toLowerCase()}@example.com`
  // this run's own guest: a phone shared with an earlier run's guest must not matter (the e-mail is
  // the identity, ADR-056 review), but a unique one keeps runs independent on any server
  const phone = `+49 170 ${String(Date.now()).slice(-7)}`
  const first = await bookStay(request, run, "a", email, phone, [{ code: TRANSFER.code, quantity: 1 }])
  const second = await bookStay(request, run, "b", email, phone, [])

  const agent = await staff(browser, AGENT, opened)
  const noErrors = trackErrors(agent)
  const cancelled = new Set<string>()
  const cancel = async (reservation: string) => {
    const r = await pageApi(agent, "kamra.tex.api.crs.cancel", { reservation, reason: "E2E clean-up (CRM profile)" })
    expect(r.ok, JSON.stringify(r.body).slice(0, 300)).toBeTruthy()
    cancelled.add(reservation)
  }
  try {
    await agent.goto(texPath("/tex/crm"))
    await cancel(second.reservation)

    const found = await pageApi<{ total: number; rows: { name: string }[] }>(agent, "kamra.tex.api.crm.guests", { q: email, limit: 5 })
    expect(found.ok).toBeTruthy()
    expect(found.message.total, "one profile for the guest's e-mail").toBe(1)
    const guest = found.message.rows[0].name
    const prof = (await pageApi<ProfileResponse>(agent, "kamra.tex.api.crm.guest", { name: guest })).message
    expect(prof.cancellations.count).toBe(1)
    const bought = prof.extras.find((e) => e.reservation === first.reservation && e.code === TRANSFER.code)
    expect(bought, "the transfer on the first stay").toBeTruthy()

    await test.step("the profile: key figures, extras, stays", async () => {
      await agent.goto(texPath(`/tex/crm/guests/${encodeURIComponent(guest)}`))
      await expect(agent.getByRole("heading", { level: 1, name: `Ines Profile ${run}` })).toBeVisible()
      const kpis = agent.getByRole("region", { name: "Guest key figures" })
      const cxl = kpis.getByText("Cancellations", { exact: true }).locator("..")
      await expect(cxl).toContainText("1")
      await expect(cxl).toContainText(prof.cancellations.fees.length ? /Fees/ : /No fees charged/)

      await agent.getByRole("tab", { name: /^Extras/ }).click()
      const table = agent.getByRole("table", { name: "Extras bought" })
      const row = table.getByRole("row").filter({ hasText: first.reservation })
      await expect(row).toContainText(TRANSFER.name)
      await expect(row).toContainText(bought!.amount)
      await expect(agent.getByRole("list", { name: "Extras by type" })).toContainText(TRANSFER.name)

      await agent.getByRole("tab", { name: /^Stays/ }).click()
      await expect(agent.getByRole("table", { name: "Stays" }).getByRole("row").filter({ hasText: second.reservation })).toContainText("Cancelled")
    })

    await test.step("loyalty: only programs of the agent's hotels", async () => {
      const programs = await pageApi<{ program: string }[]>(agent, "kamra.tex.api.ui_backoffice_crm_payments.loyalty_programs", { guest })
      expect(programs.ok).toBeTruthy()
      const mine = new Set(programs.message.map((p) => p.program))
      for (const a of prof.loyalty) expect(mine.has(a.program), `${a.program} belongs to the agent's hotels`).toBeTruthy()
    })

    await test.step("pricing internals: the TEX API with price.view_cost, never REST", async () => {
      const rm = await staff(browser, REVENUE, opened)
      await rm.goto(texPath("/tex"))
      const tex = await pageApi<{ pricing: { explanation?: unknown[]; totals: Record<string, string> } }>(rm, "kamra.tex.api.crs.reservation", { name: first.reservation })
      expect(tex.ok).toBeTruthy()
      expect(tex.message.pricing.explanation?.length, "the explanation, for price.view_cost").toBeGreaterThan(0)

      const doc = await rm.request.get(`/api/resource/Reservation/${encodeURIComponent(first.reservation)}`)
      expect(doc.ok(), `REST read: ${doc.status()}`).toBeTruthy()
      const data = ((await doc.json()) as { data: Record<string, unknown> }).data
      expect(data.name).toBe(first.reservation)
      expect(data.tex_pricing_snapshot ?? null, "the snapshot is withheld").toBeNull()
      for (const f of ["tex_cost_amount", "tex_margin_amount"]) expect(Number(data[f] ?? 0), `${f} is withheld`).toBe(0)

      // a list leaves the cost out; filtering on it (an oracle) is refused
      const list = await rm.request.get("/api/resource/Reservation", {
        params: { fields: JSON.stringify(["name", "tex_cost_amount"]), filters: JSON.stringify([["name", "=", first.reservation]]) },
      })
      expect(list.ok(), `REST list: ${list.status()}`).toBeTruthy()
      const rows = ((await list.json()) as { data: Record<string, unknown>[] }).data
      expect(rows.map((r) => r.name)).toEqual([first.reservation])
      expect(Number(rows[0].tex_cost_amount ?? 0), "the cost is left out of a list").toBe(0)
      const oracle = await rm.request.get("/api/resource/Reservation", {
        params: { fields: JSON.stringify(["name"]), filters: JSON.stringify([["tex_cost_amount", ">", 0]]) },
      })
      expect(oracle.status(), "a filter on the cost is refused").toBe(403)
    })
    noErrors()
  } finally {
    for (const r of [first.reservation, second.reservation]) if (!cancelled.has(r)) await cancel(r).catch(() => undefined)
  }
})
