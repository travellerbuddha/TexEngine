// G-45 (ADR-044): a guest's own change on the manage page settles its money. On the demo
// "aurora" site (Aurora Beach Resort, Flexible rate: 30 % deposit, pay at the hotel allowed,
// the sandbox card gateway):
// - a card-deposit booking is extended by a night: the dialog asks for the deposit share of
//   the new price first ("Pay … and confirm"); the guest pays it on the sandbox page and is
//   brought back to the manage page, where the server has made the change;
// - a pay-at-hotel booking is extended: nothing is charged, the dialog and the notice say how
//   much more is payable at the hotel;
// - a fully paid booking is shortened while the hotel refunds lower prices automatically (the
//   policy is set through the API as Administrator and restored afterwards): the dialog and
//   the notice announce the refund, and the refund job gives the money back to the card.
// Every stay is cancelled at the end (free under the Flexible rate) so the demo inventory is
// left as found. Amounts are compared as decimal strings (cents), never as floats.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_ADMIN_PASSWORD=… npx playwright test -c e2e manage-money
import { expect, request as pwRequest, test, type APIRequestContext, type Locator, type Page } from "@playwright/test"
import { ADMIN_PASSWORD, api, esc, stayDates, trackErrors, uniqueRunId } from "./helpers"
import { moneyAmount } from "./flows/booking"

const SLUG = "aurora"
const HOTEL = "Aurora Beach Resort"
const BASE = process.env.TEX_E2E_BASE || "http://test.localhost:8000"

interface PaymentStart {
  transaction: string
  kind: string
  url?: string | null
  fields?: { success_sig?: string; fail_sig?: string } | null
}
interface Booked {
  booking: string
  reservation: string
  total: string
  token: string
  checkIn: string
  checkOut: string
  payment: PaymentStart | null
}
interface Settlement {
  kind: string
  amount: string
  collect: string
  refund: string
  credit: string
  currency: string
}
interface Proposal {
  sellable: boolean
  old_total: string
  new_total: string | null
  difference: string | null
  settlement: Settlement | null
  proposal_token: string | null
}
interface ChangeResult {
  status: string
  request?: string
  amount?: string
  settlement?: Settlement
  payment?: PaymentStart
  balance?: string
  credit?: string
}
interface GuestBooking {
  status: string
  total: string
  paid: string
  balance: string
  credit: string
  due_now: string
  payment_status: string
  rooms: {
    reservation: string
    check_in: string
    check_out: string
    status: string
    pending_change: { status: string } | null
    last_change: { request: string; status: string; settlement: string | null; amount: string; refunded: string } | null
  }[]
}

/** Exact decimal strings as cents (no floats for money); signed. */
const cents = (amount: string) => {
  const s = amount.trim()
  const [whole, frac = ""] = s.replace(/^[-+]/, "").split(".")
  const v = BigInt(whole + frac.padEnd(2, "0").slice(0, 2))
  return s.startsWith("-") ? -v : v
}

const addDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

/** Value next to a <dt> term in a description list. */
const dd = (scope: Page | Locator, term: string) => scope.locator("dt", { hasText: new RegExp(`^${esc(term)}$`) }).locator("xpath=following-sibling::dd[1]")

async function english(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex.book.lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
}

/** Book the Flexible rate (refundable, 30 % deposit) through the public booking API. */
async function bookStay(req: APIRequestContext, run: string, label: string, method: "Card" | "Pay at Hotel", nights = 3): Promise<Booked> {
  const session_id = `e2e-money-${label}-${run.toLowerCase()}`
  for (let attempt = 0; attempt < 5; attempt++) {
    const { checkIn, checkOut } = stayDates(200, nights)
    // one more night must be sellable too: the guest extends the stay
    const s = await api<{ properties: { offers: { refundable: boolean; rate_plan: string; rooms: { offer_key: string }[] }[] }[] }>(req, "kamra.tex.api.public.search", {
      site: SLUG,
      hotel: HOTEL,
      check_in: checkIn,
      check_out: addDays(checkOut, 1),
      rooms: [{ adults: 2, children: [] }],
      session_id,
    })
    if (!(s.properties[0]?.offers ?? []).some((o) => o.refundable)) continue
    const stay = await api<{ properties: { offers: { refundable: boolean; rooms: { offer_key: string }[] }[] }[] }>(req, "kamra.tex.api.public.search", {
      site: SLUG,
      hotel: HOTEL,
      check_in: checkIn,
      check_out: checkOut,
      rooms: [{ adults: 2, children: [] }],
      session_id,
    })
    const offer = (stay.properties[0]?.offers ?? []).find((o) => o.refundable)
    if (!offer) continue
    const q = await api<{ ok: boolean; quote_id: string }>(req, "kamra.tex.api.public.quote", { site: SLUG, offer_key: offer.rooms[0].offer_key, session_id })
    expect(q.ok, "quote").toBe(true)
    const b = await api<{ booking: string; total: string; manage_token: string; rooms: { reservation: string }[]; payment: PaymentStart | null }>(req, "kamra.tex.api.public.book", {
      site: SLUG,
      quote_ids: [q.quote_id],
      guest: { first_name: "Nora", last_name: `Money ${label} ${run}`, email: `nora.${label}.${run.toLowerCase()}@example.com`, phone: "+49 170 5551234", country: "DE" },
      payment_method: method,
      idempotency_key: `e2e-money-${label}-${run}`,
      session_id,
    })
    expect(b.manage_token, "the guest's manage token").toBeTruthy()
    return { booking: b.booking, reservation: b.rooms[0].reservation, total: b.total, token: b.manage_token, checkIn, checkOut, payment: b.payment }
  }
  throw new Error(`no Flexible stay with one more night free at ${HOTEL} ~200–320 days ahead`)
}

/** The sandbox gateway confirms a payment (what its page's "success" button does). */
async function sandboxPaid(req: APIRequestContext, p: PaymentStart | null | undefined) {
  expect(p?.fields?.success_sig, "a sandbox card payment").toBeTruthy()
  const r = await api<{ status: string }>(req, "kamra.tex.api.public.mock_pay", { transaction: p!.transaction, outcome: "success", sig: p!.fields!.success_sig })
  expect(r.status).toBe("Succeeded")
}

const status = (req: APIRequestContext, token: string) => api<GuestBooking>(req, "kamra.tex.api.public.booking_status", { token })

async function openManage(page: Page, b: Booked) {
  await page.goto(`/book/${SLUG}/manage?lang=en#token=${encodeURIComponent(b.token)}`)
  await expect(page.getByRole("heading", { level: 1, name: "Manage your booking" })).toBeVisible()
  await expect(page.getByText(b.booking, { exact: true }).first()).toBeVisible()
}

/** Open "Change dates or guests", pick new dates in the calendar and check the price: → the
 * server's proposal (with its settlement) and the dialog. */
async function proposeDates(page: Page, checkIn: string, checkOut: string): Promise<{ dlg: Locator; p: Proposal }> {
  const room = page.getByRole("listitem").filter({ has: page.getByRole("button", { name: "Change dates or guests", exact: true }) })
  await expect(room).toHaveCount(1)
  await room.getByRole("button", { name: "Change dates or guests", exact: true }).click()
  const dlg = page.getByRole("dialog", { name: /^Change / })
  await expect(dlg).toBeVisible()
  await dlg.getByRole("button", { name: /^Dates/ }).click()
  const cal = page.getByRole("dialog", { name: "Select dates" })
  await expect(cal).toBeVisible()
  for (const d of [checkIn, checkOut]) {
    const label = await page.evaluate(
      (iso) => new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" }).format(new Date(`${iso}T12:00:00`)),
      d,
    )
    const day = cal.getByRole("button", { name: new RegExp(`^${esc(label)}(,|$)`) })
    for (let i = 0; i < 24 && !(await day.count()); i++) {
      const next = cal.getByRole("button", { name: "Next month" })
      if (!(await next.isVisible()) || (await next.isDisabled())) break
      await next.click()
    }
    await expect(day, `calendar day ${d}`).toHaveCount(1)
    await day.click()
  }
  await cal.getByRole("button", { name: "Done", exact: true }).click()
  await expect(cal).toBeHidden()
  const [r] = await Promise.all([
    page.waitForResponse((x) => x.url().includes("kamra.tex.api.public.manage_propose")),
    dlg.getByRole("button", { name: "Check availability and price", exact: true }).click(),
  ])
  const body = (await r.json().catch(() => ({}))) as { message?: Proposal }
  expect(r.ok(), `manage_propose ${r.status()}: ${JSON.stringify(body).slice(0, 300)}`).toBeTruthy()
  const p = body.message!
  expect(p.sellable, JSON.stringify(p).slice(0, 300)).toBe(true)
  expect(p.settlement, "the server says how the change is settled").toBeTruthy()
  expect(moneyAmount(await dd(dlg, "New price").innerText())).toBe(p.new_total)
  return { dlg, p }
}

/** Confirm in the dialog → the manage_apply answer. */
async function confirmChange(page: Page, dlg: Locator, button: string | RegExp): Promise<ChangeResult> {
  const [r] = await Promise.all([
    page.waitForResponse((x) => x.url().includes("kamra.tex.api.public.manage_apply")),
    dlg.getByRole("button", { name: button }).click(),
  ])
  const body = (await r.json().catch(() => ({}))) as { message?: ChangeResult }
  expect(r.ok(), `manage_apply ${r.status()}: ${JSON.stringify(body).slice(0, 300)}`).toBeTruthy()
  return body.message!
}

/** Whatever happened: cancel the stay (free under the Flexible rate), as the guest. */
async function cancelStay(req: APIRequestContext, b: Booked | undefined) {
  if (!b) return
  const r = await req.post("/api/method/kamra.tex.api.public.manage_cancel", { data: { token: b.token, reservation: b.reservation, reason: "E2E clean-up" } })
  expect(r.ok(), `cancel ${b.reservation}: ${(await r.text()).slice(0, 300)}`).toBeTruthy()
}

test("a card-deposit booking is extended: the guest pays the difference first, then the change is made", async ({ page }) => {
  test.setTimeout(180_000)
  const noErrors = trackErrors(page)
  await english(page)
  const run = uniqueRunId()
  let b: Booked | undefined
  try {
    b = await bookStay(page.request, run, "deposit", "Card")
    await sandboxPaid(page.request, b.payment)
    const before = await status(page.request, b.token)
    expect(before.status).toBe("Confirmed")
    expect(cents(before.paid)).toBeGreaterThan(0n)

    await openManage(page, b)
    const longer = addDays(b.checkOut, 1)
    const { dlg, p } = await proposeDates(page, b.checkIn, longer)
    expect(cents(p.difference!)).toBeGreaterThan(0n)
    // the deposit share of the new price, not the whole difference, is paid before the change
    expect(p.settlement!.kind).toBe("pay_now")
    expect(cents(p.settlement!.amount)).toBeGreaterThan(0n)
    expect(cents(p.settlement!.amount)).toBeLessThan(cents(p.difference!))
    const title = dlg.getByText(/^Pay .+ now to confirm$/)
    await expect(title).toBeVisible()
    expect(moneyAmount(await title.innerText())).toBe(p.settlement!.amount)
    await expect(dlg).toContainText("Until then your booking stays as it is.")

    const out = await confirmChange(page, dlg, /^Pay .+ and confirm$/)
    expect(out.status).toBe("payment_required")
    expect(out.amount).toBe(p.settlement!.amount)
    // nothing changed yet: the change waits for the payment
    const waiting = await status(page.request, b.token)
    expect(waiting.rooms[0].check_out).toBe(b.checkOut)
    expect(waiting.total).toBe(before.total)

    // the sandbox gateway's page: the amount is the change's, and paying it brings the guest back
    await page.waitForURL(/\/book\/pay\/mock\//, { timeout: 30_000 })
    await expect(page.getByRole("heading", { name: "Sandbox payment page" })).toBeVisible()
    expect(moneyAmount((await dd(page, "Test amount").innerText()) ?? "")).toBe(p.settlement!.amount)
    await page.getByRole("button", { name: "Simulate successful payment" }).click()
    await page.waitForURL(new RegExp(`/book/${SLUG}/manage\\?.*status=succeeded`), { timeout: 30_000 })
    const notice = page.getByRole("status").filter({ hasText: "Your change is confirmed" })
    await expect(notice).toBeVisible()
    expect(moneyAmount((await notice.innerText()).replace(/^Your change is confirmed/, ""))).toBe(p.settlement!.amount)

    // the server made the change when the gateway confirmed the payment
    const after = await status(page.request, b.token)
    expect(after.rooms[0].check_out).toBe(longer)
    expect(after.total).toBe(p.new_total)
    expect(cents(after.paid)).toBe(cents(before.paid) + cents(p.settlement!.amount))
    expect(after.due_now).toBe(after.paid) // the deposit of the new price is paid
    expect(after.rooms[0].last_change).toMatchObject({ status: "applied", settlement: "pay_now", amount: p.settlement!.amount })
    const hotel = page.getByRole("region", { name: HOTEL })
    expect(moneyAmount(await dd(hotel, "Total").innerText())).toBe(p.new_total)
    noErrors()
  } finally {
    await cancelStay(page.request, b)
  }
})

test("a pay-at-hotel booking is extended: nothing is charged, the page says what more is due at the hotel", async ({ page }) => {
  test.setTimeout(150_000)
  const noErrors = trackErrors(page)
  await english(page)
  const run = uniqueRunId()
  let b: Booked | undefined
  try {
    b = await bookStay(page.request, run, "hotel", "Pay at Hotel")
    expect(b.payment?.kind ?? "none").toBe("none")
    await openManage(page, b)
    const longer = addDays(b.checkOut, 1)
    const { dlg, p } = await proposeDates(page, b.checkIn, longer)
    expect(p.settlement!.kind).toBe("pay_at_hotel")
    expect(p.settlement!.amount).toBe(p.difference)
    const text = dlg.getByText(/ more is payable at the hotel\. Nothing is charged now\.$/)
    await expect(text).toBeVisible()
    expect(moneyAmount(await text.innerText())).toBe(p.difference)

    const out = await confirmChange(page, dlg, "Confirm change")
    expect(out.status).toBe("applied")
    expect(out.settlement).toMatchObject({ kind: "pay_at_hotel", amount: p.difference })
    await expect(dlg).toBeHidden()
    const notice = page.getByRole("status").filter({ hasText: "The change is confirmed." })
    await expect(notice).toBeVisible()
    expect(moneyAmount((await notice.innerText()).replace(/^Your booking was updated/, ""))).toBe(p.difference)
    const atHotel = page.getByRole("status").filter({ hasText: "To pay at the hotel" })
    await expect(atHotel).toBeVisible()
    expect(moneyAmount((await atHotel.innerText()).replace(/^To pay at the hotel/, ""))).toBe(p.new_total)

    const after = await status(page.request, b.token)
    expect(after.rooms[0].check_out).toBe(longer)
    expect(after.total).toBe(p.new_total)
    expect(after.paid).toBe("0.00")
    expect(after.balance).toBe(p.new_total) // nothing charged: all of it at the hotel
    noErrors()
  } finally {
    await cancelStay(page.request, b)
  }
})

test("a fully paid booking is shortened under the refund policy: the page announces the refund and it is made", async ({ page }) => {
  test.setTimeout(180_000)
  const noErrors = trackErrors(page)
  await english(page)
  const run = uniqueRunId()
  const admin = await pwRequest.newContext({ baseURL: BASE })
  const login = await admin.post("/api/method/login", { data: { usr: "Administrator", pwd: ADMIN_PASSWORD } })
  expect(login.ok(), "login Administrator").toBeTruthy()
  const policy = await api<{ tex_lower_price_refund: string | null }>(admin, "frappe.client.get_value", {
    doctype: "Property",
    filters: HOTEL,
    fieldname: "tex_lower_price_refund",
  })
  let b: Booked | undefined
  try {
    await api(admin, "frappe.client.set_value", { doctype: "Property", name: HOTEL, fieldname: "tex_lower_price_refund", value: "Refund automatically" })
    b = await bookStay(page.request, run, "refund", "Card")
    await sandboxPaid(page.request, b.payment)
    // the rest paid online too: the booking is fully paid
    const rest = await api<PaymentStart>(page.request, "kamra.tex.api.public.pay_booking", { token: b.token, payment_method: "Card" })
    await sandboxPaid(page.request, rest)
    const before = await status(page.request, b.token)
    expect(before.paid).toBe(before.total)

    await openManage(page, b)
    const shorter = addDays(b.checkOut, -1)
    const { dlg, p } = await proposeDates(page, b.checkIn, shorter)
    expect(cents(p.difference!)).toBeLessThan(0n)
    // what was paid above the new total goes back to the card
    expect(p.settlement!.kind).toBe("refund")
    expect(cents(p.settlement!.amount)).toBe(cents(before.paid) - cents(p.new_total!))
    const text = dlg.getByText(/ will be refunded to your card once the change is made\.$/)
    await expect(text).toBeVisible()
    expect(moneyAmount(await text.innerText())).toBe(p.settlement!.amount)

    const out = await confirmChange(page, dlg, "Confirm change")
    expect(out.status).toBe("applied")
    expect(out.settlement?.kind).toBe("refund")
    await expect(dlg).toBeHidden()
    const notice = page.getByRole("status").filter({ hasText: "is being refunded to your card" })
    await expect(notice).toBeVisible()
    expect(moneyAmount((await notice.innerText()).replace(/^Your booking was updated/, ""))).toBe(p.settlement!.amount)

    const after = await status(page.request, b.token)
    expect(after.rooms[0].check_out).toBe(shorter)
    expect(after.total).toBe(p.new_total)
    // the refund runs in a job queued after the change was committed (the bench's short queue)
    await expect
      .poll(async () => (await status(page.request, b!.token)).paid, { timeout: 90_000, message: "the refund job gave the overpayment back" })
      .toBe(p.new_total)
    const done = await status(page.request, b.token)
    expect(done.credit).toBe("0.00")
    expect(done.rooms[0].last_change).toMatchObject({ status: "applied", settlement: "refund", refunded: p.settlement!.amount })
    noErrors()
  } finally {
    await cancelStay(page.request, b)
    await api(admin, "frappe.client.set_value", {
      doctype: "Property",
      name: HOTEL,
      fieldname: "tex_lower_price_refund",
      value: policy.tex_lower_price_refund || "Staff approval",
    })
    await admin.dispose()
  }
})
