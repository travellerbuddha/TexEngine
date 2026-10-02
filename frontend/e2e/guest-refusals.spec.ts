// G-70b (ADR-013 amendment): a guest refusal reaches the page by its stable code, and the page says it in the guest's
// language — never the server's English text. On the demo "aurora" site, in Turkish:
// - the guest's booking page is open when the hotel cancels the room: the guest's (stale) "Cancel room" is refused
//   with ROOM_NOT_ACTIVE, and the dialog says so in Turkish;
// - a payment link's page is open when the hotel cancels the link: "Pay" is refused with LINK_CANCELLED, said in
//   Turkish.
// The stay is booked through the guest API (pay at the hotel: nothing is charged) and cancelled by staff in the test;
// the link is cancelled in the test. Nothing is left behind.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_ADMIN_PASSWORD=… npx playwright test -c e2e guest-refusals
import { readFileSync } from "node:fs"
import { expect, request as pwRequest, test, type APIRequestContext } from "@playwright/test"
import { ADMIN_PASSWORD, api, stayDates, trackErrors, uniqueRunId } from "./helpers"

/** The booking app's Turkish catalog: the texts the guest must see. */
const tr: Record<string, string> = JSON.parse(readFileSync(new URL("../src/booking/i18n/tr.json", import.meta.url), "utf8"))

const SLUG = "aurora"
const HOTEL = "Aurora Beach Resort"
const BASE = process.env.TEX_E2E_BASE || "http://test.localhost:8000"

let admin: APIRequestContext

test.beforeAll(async () => {
  admin = await pwRequest.newContext({ baseURL: BASE })
  const login = await admin.post("/api/method/login", { data: { usr: "Administrator", pwd: ADMIN_PASSWORD } })
  expect(login.ok(), "login Administrator").toBeTruthy()
})

test.afterAll(async () => {
  await admin.dispose()
})

/** A pay-at-the-hotel stay booked as a guest: → the booking, its room and the manage token. */
async function bookStay(req: APIRequestContext, run: string) {
  const session_id = `e2e-refusals-${run.toLowerCase()}`
  for (let attempt = 0; attempt < 5; attempt++) {
    const { checkIn, checkOut } = stayDates(230 + attempt * 7, 2)
    const s = await api<{ properties: { offers: { refundable: boolean; rooms: { offer_key: string }[] }[] }[] }>(req, "kamra.tex.api.public.search", {
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
    const b = await api<{ booking: string; manage_token: string; rooms: { reservation: string }[] }>(req, "kamra.tex.api.public.book", {
      site: SLUG,
      quote_ids: [q.quote_id],
      guest: { first_name: "Ayşe", last_name: `Refusal ${run}`, email: `ayse.refusal.${run.toLowerCase()}@example.com`, phone: "+90 532 5551234", country: "TR" },
      payment_method: "Pay at Hotel",
      idempotency_key: `e2e-refusals-${run}`,
      session_id,
    })
    expect(b.manage_token, "the guest's manage token").toBeTruthy()
    return { booking: b.booking, reservation: b.rooms[0].reservation, token: b.manage_token }
  }
  throw new Error(`no Flexible stay free at ${HOTEL} ~230–260 days ahead`)
}

test("a room the hotel cancelled while the guest's page was open: the stale cancel says why, in Turkish", async ({ page }) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  const b = await bookStay(page.request, uniqueRunId())
  await page.goto(`/book/${SLUG}/manage?lang=tr#token=${encodeURIComponent(b.token)}`)
  await expect(page.getByRole("heading", { level: 1, name: tr["manage.title"] })).toBeVisible()
  // the hotel cancels the room meanwhile; the guest's page still offers "Cancel room"
  await api(admin, "kamra.tex.api.crs.cancel", { reservation: b.reservation, reason: "E2E: the hotel cancels (G-70b)" })
  await page.getByRole("button", { name: tr["manage.cancel"], exact: true }).click()
  const dlg = page.getByRole("dialog")
  await expect(dlg).toBeVisible()
  const [r] = await Promise.all([
    page.waitForResponse((x) => x.url().includes("kamra.tex.api.public.manage_cancel")),
    dlg.getByRole("button", { name: tr["manage.confirmCancel"], exact: true }).click(),
  ])
  const body = (await r.json().catch(() => ({}))) as { tex_code?: string }
  expect(r.status()).toBe(417)
  expect(body.tex_code).toBe("ROOM_NOT_ACTIVE")
  const alert = dlg.getByRole("alert").filter({ hasText: tr["manage.cancelFailed"] })
  await expect(alert).toContainText(tr["refusal.ROOM_NOT_ACTIVE"])
  await expect(dlg).not.toContainText("already cancelled")              // the server's English text
  noErrors()
})

test("a payment link the hotel cancelled while its page was open: Pay says why, in Turkish", async ({ page }) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  const link = await api<{ link: string; token: string }>(admin, "kamra.tex.api.payments.create_link", {
    property: HOTEL,
    amount: "12.50",
    currency: "EUR",
    description: `E2E refusal link ${uniqueRunId()}`,
    expires_hours: 2,
  })
  try {
    await page.goto(`/book/pay?lang=tr#token=${encodeURIComponent(link.token)}`)
    await expect(page.getByRole("heading", { level: 1, name: tr["paylink.heading"] })).toBeVisible()
    await api(admin, "kamra.tex.api.payments.cancel_link", { name: link.link, reason: "E2E: the hotel cancels the link (G-70b)" })
    const [r] = await Promise.all([
      page.waitForResponse((x) => x.url().includes("kamra.tex.api.public.pay_link")),
      page.getByRole("button", { name: / öde$/ }).click(),
    ])
    const body = (await r.json().catch(() => ({}))) as { tex_code?: string }
    expect(r.status()).toBe(417)
    expect(body.tex_code).toBe("LINK_CANCELLED")
    const alert = page.getByRole("alert").filter({ hasText: tr["confirm.retryFailed"] })
    await expect(alert).toContainText(tr["refusal.LINK_CANCELLED"])
    await expect(page.getByText("This payment link is cancelled.")).toHaveCount(0)
    noErrors()
  } finally {
    // already cancelled by the test; a failure before that leaves no open link either
    await admin.post("/api/method/kamra.tex.api.payments.cancel_link", { data: { name: link.link, reason: "e2e clean-up" } })
  }
})
