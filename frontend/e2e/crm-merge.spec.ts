// ADR-056 second review: a shared phone never joins two people's profiles by itself; the profile shows
// the other as a possible duplicate, and staff who may edit the guest merge them.
// Two stays at Aurora Beach Resort are booked through the public booking API (Flexible rate, paid at
// the hotel) with two e-mail addresses and one phone number: two profiles. The reservations agent
// opens the first in CRM → Guests, sees the second under "Possible duplicates" (same phone), merges it
// into the first, and the profile then holds both stays; the duplicate is gone. Both stays are
// cancelled at the end (free under the Flexible rate).
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e crm-merge
import { expect, test, type APIRequestContext, type BrowserContext } from "@playwright/test"
import { api, login, pageApi, stayDates, texPath, trackErrors, uniqueRunId } from "./helpers"

const SLUG = "aurora"
const HOTEL = "Aurora Beach Resort"
const AGENT = "agent@demo.tex"

type Offers = { properties: { offers: { refundable: boolean; rooms: { offer_key: string }[] }[] }[] }

/** A Flexible (refundable) stay through the public booking API, paid at the hotel. */
async function bookStay(req: APIRequestContext, run: string, label: string, email: string, phone: string) {
  const session_id = `e2e-merge-${label}-${run.toLowerCase()}`
  for (let attempt = 0; attempt < 5; attempt++) {
    const { checkIn, checkOut } = stayDates(210 + attempt * 7, 2)
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
      guest: { first_name: "Mara", last_name: `Merge ${run}`, email, phone, country: "DE" },
      payment_method: "Pay at Hotel",
      idempotency_key: `e2e-merge-${label}-${run}`,
      session_id,
    })
    return b.rooms[0].reservation
  }
  throw new Error(`no Flexible stay free at ${HOTEL} ~210–250 days ahead`)
}

const opened: BrowserContext[] = []
test.afterEach(async () => {
  for (const c of opened.splice(0)) await c.close()
})

test("a shared phone is shown as a possible duplicate, and staff merge the two profiles", async ({ browser, request }) => {
  test.setTimeout(180_000)
  const run = uniqueRunId()
  const phone = `+49 171 ${String(Date.now()).slice(-7)}`
  const first = await bookStay(request, run, "a", `mara.a.${run.toLowerCase()}@example.com`, phone)
  const second = await bookStay(request, run, "b", `mara.b.${run.toLowerCase()}@example.com`, phone)

  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "en-US", baseURL: test.info().project.use.baseURL })
  opened.push(ctx)
  const agent = await ctx.newPage()
  await agent.addInitScript(() => {
    try {
      localStorage.setItem("tex-lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
  await login(agent, AGENT)
  const noErrors = trackErrors(agent)
  const cancel = (reservation: string) => pageApi(agent, "kamra.tex.api.crs.cancel", { reservation, reason: "E2E clean-up (CRM merge)" })
  try {
    await agent.goto(texPath("/tex/crm"))
    const profileOf = async (reservation: string) => {
      const r = await pageApi<{ guest: { name: string } | null }>(agent, "kamra.tex.api.crs.reservation", { name: reservation })
      expect(r.ok, `reservation ${reservation}`).toBeTruthy()
      expect(r.message.guest, "the agent sees the guest").toBeTruthy()
      return r.message.guest!.name
    }
    const kept = await profileOf(first)
    const dup = await profileOf(second)
    expect(dup, "another e-mail on the same phone is another profile").not.toBe(kept)

    await agent.goto(texPath(`/tex/crm/guests/${encodeURIComponent(kept)}`))
    await expect(agent.getByRole("heading", { level: 1, name: `Mara Merge ${run}` })).toBeVisible()
    const dups = agent.getByRole("list", { name: "Possible duplicates" })
    const row = dups.getByRole("listitem").filter({ hasText: dup })
    await expect(row).toContainText("Same phone")
    await row.getByRole("button", { name: "Merge into this profile" }).click()

    const dialog = agent.getByRole("dialog")
    await expect(dialog.getByLabel(/Duplicate profile/)).toHaveValue(dup)
    await expect(dialog).toContainText("Consent becomes the stricter of the two")
    await dialog.getByRole("button", { name: "Merge and delete the duplicate" }).click()
    await expect(agent.getByText(`${dup} merged into this profile`)).toBeVisible()
    await expect(dialog).toBeHidden()

    // the profile now holds both stays; the duplicate is gone
    await expect(agent.getByRole("list", { name: "Possible duplicates" })).toHaveCount(0)
    const stays = agent.getByRole("table", { name: "Stays" })
    for (const r of [first, second]) await expect(stays.getByRole("row").filter({ hasText: r })).toHaveCount(1)
    expect(await profileOf(second), "the second stay is the kept profile's").toBe(kept)
    const gone = await pageApi(agent, "kamra.tex.api.crm.guest", { name: dup })
    expect(gone.ok, "the duplicate no longer exists").toBeFalsy()
    noErrors()
  } finally {
    for (const r of [first, second]) await cancel(r).catch(() => undefined)
  }
})
