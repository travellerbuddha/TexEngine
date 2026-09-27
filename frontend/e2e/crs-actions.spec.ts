// G-41 (R-25, ADR-050): the call-centre agent sells on the call centre only, and works a booked
// stay from the reservation screen.
// - The channel picker of the Call Center and the CRS offers the agent the call centre only;
//   the server refuses a search on the web or OTA channel whatever the page sends. The revenue
//   manager (price.any_channel) is offered every channel.
// - On a call-centre booking (pay at the hotel, far ahead) the agent adds an airport transfer
//   after booking, sends a payment link for the balance, re-sends the confirmation with a new
//   manage link and cancels the reservation inside the free-cancellation window: every action
//   through the reservation screen, every figure from the server.
// - O-29: an answer that comes back late (an earlier search, the quote summary of a payment method
//   left meanwhile) never replaces the current one on the Call Center page.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e crs-actions
import { expect, test, type Page } from "@playwright/test"
import { byLabel, holdNext, login, pageApi, stayDates, texPath, trackErrors, uniqueRunId } from "./helpers"
import { openReservation, readLockedPrice, readRevisions } from "./flows/reservations"

const AGENT = "agent@demo.tex"
const REVENUE = "revenue@demo.tex"
const HOTEL = "Aurora Beach Resort"
/** A demo extra staff may add to a booked stay (G-22). */
const TRF = { code: "TRF", name: "Airport transfer" }

// typed dates follow the browser locale; the UI language is pinned per page
test.use({ locale: "en-US" })

async function english(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex-lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
}

/** Exact decimal strings as cents (no floats for money); signed. */
const cents = (amount: string) => {
  const s = amount.trim()
  const [whole, frac = ""] = s.replace(/^[-+]/, "").split(".")
  const v = BigInt(whole + frac.padEnd(2, "0").slice(0, 2))
  return s.startsWith("-") ? -v : v
}

/** The pathname of a response ends with this whitelisted method (crs.cancel ≠ crs.cancellation_preview). */
const isMethod = (url: string, method: string) => new URL(url).pathname.endsWith(`/api/method/${method}`)

const stay = (checkIn: string, checkOut: string, channel: string) => ({
  check_in: checkIn,
  check_out: checkOut,
  rooms: [{ adults: 2, children: [] }],
  market: "DE",
  channel,
  properties: [HOTEL],
})

test("Channel binding: the agent is offered the call centre only; other channels are refused", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, AGENT)

  // the Call Center: one channel, already chosen
  await page.goto(texPath("/tex/crs/call-center"))
  await expect(page.getByRole("heading", { level: 1, name: "Call Center" })).toBeVisible()
  const picker = byLabel(page, "Sales channel")
  await expect(picker).toHaveValue("CALL_CENTER")
  await expect(picker.locator("option")).toHaveText(["Call center"])

  // the CRS page offers the same
  await page.goto(texPath("/tex/crs"))
  await expect(byLabel(page, "Sales channel")).toHaveValue("CALL_CENTER")
  await expect(byLabel(page, "Sales channel").locator("option")).toHaveText(["Call center"])

  // the server decides, whatever the page sends: the web and OTA channels are refused (403)
  const { checkIn, checkOut } = stayDates(120, 2)
  for (const channel of ["DIRECT_WEB", "OTA"]) {
    const r = await pageApi(page, "kamra.tex.api.ui_crs.search", stay(checkIn, checkOut, channel))
    expect(r.status, `${channel}: ${JSON.stringify(r.body).slice(0, 300)}`).toBe(403)
  }
  const cc = await pageApi<{ channel: string; properties: { property: string }[] }>(page, "kamra.tex.api.ui_crs.search", stay(checkIn, checkOut, "CALL_CENTER"))
  expect(cc.ok, JSON.stringify(cc.body).slice(0, 300)).toBeTruthy()
  expect(cc.message.channel).toBe("CALL_CENTER")
  expect(cc.message.properties.map((p) => p.property)).toEqual([HOTEL])
  noErrors()
})

test("Channel binding: the revenue manager may price every channel", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, REVENUE)
  await page.goto(texPath("/tex/crs/call-center"))
  await expect(page.getByRole("heading", { level: 1, name: "Call Center" })).toBeVisible()
  const picker = byLabel(page, "Sales channel")
  await expect(picker).toHaveValue("CALL_CENTER")
  const offered = await picker.locator("option").evaluateAll((os) => os.map((o) => (o as HTMLOptionElement).value))
  expect(offered).toEqual(expect.arrayContaining(["CALL_CENTER", "DIRECT_WEB", "OTA"]))
  noErrors()
})

test("Reservation actions from the CRS: add extras, payment link, re-send confirmation, cancel", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, AGENT)
  await page.goto(texPath("/tex/reservations"))

  // a call-centre booking paid at the hotel (nothing due now), set up through the API as the agent
  const run = uniqueRunId()
  const email = `mia.${run.toLowerCase()}@example.com`
  const { checkIn, checkOut } = stayDates(140, 2)
  const s = await pageApi<{ properties: { offers: { refundable?: boolean; rooms: { offer_key: string }[] }[] }[] }>(
    page,
    "kamra.tex.api.ui_crs.search",
    stay(checkIn, checkOut, "CALL_CENTER"),
  )
  expect(s.ok, JSON.stringify(s.body).slice(0, 300)).toBeTruthy()
  const offer = s.message.properties[0].offers.find((o) => o.refundable)
  expect(offer, "a refundable call-centre offer").toBeTruthy()
  const q = await pageApi<{ ok: boolean; quote_id: string }>(page, "kamra.tex.api.crs.quote", { offer_key: offer!.rooms[0].offer_key })
  expect(q.ok && q.message.ok, JSON.stringify(q.body).slice(0, 300)).toBeTruthy()
  const bk = await pageApi<{ booking: string; status: string }>(page, "kamra.tex.api.ui_crs.book", {
    quote_ids: [q.message.quote_id],
    guest: { first_name: "Mia", last_name: `Actions ${run}`, email },
    payment_method: "Pay at Hotel",
    idempotency_key: `e2e-crs-actions-${run}`,
  })
  expect(bk.ok, JSON.stringify(bk.body).slice(0, 300)).toBeTruthy()
  expect(bk.message.status).toBe("Confirmed")
  const booking = bk.message.booking

  let res = ""
  let link = ""
  let cancelled = false
  try {
    res = await openReservation(page, { booking })
    const locked = (await readLockedPrice(page)).amount ?? ""
    expect(locked).toMatch(/^\d+\.\d{2}$/)
    let total = locked

    await test.step("add an airport transfer after booking", async () => {
      await page.getByRole("button", { name: "Add extras", exact: true }).click()
      const drawer = page.getByRole("dialog", { name: `Add extras to ${res}` })
      await expect(drawer).toBeVisible()
      await drawer.locator(`li[data-extra="${TRF.code}"]`).getByRole("button", { name: `More: ${TRF.name}`, exact: true }).click()
      await expect(drawer.getByLabel(TRF.name, { exact: true })).toHaveValue("1")
      const [pr] = await Promise.all([
        page.waitForResponse((r) => isMethod(r.url(), "kamra.tex.api.crs.addon_propose")),
        drawer.getByRole("button", { name: /^Price extras/ }).click(),
      ])
      const pBody = (await pr.json().catch(() => ({}))) as {
        message?: { ok: boolean; reasons: unknown; old_total: string; new_total: string; addon: { totals: { total: string }; explanation?: unknown } }
      }
      expect(pr.ok(), `addon_propose ${pr.status()}: ${JSON.stringify(pBody).slice(0, 300)}`).toBeTruthy()
      const p = pBody.message!
      expect(p.ok, JSON.stringify(p.reasons)).toBe(true)
      expect(p.old_total).toBe(locked)
      expect(cents(p.new_total)).toBe(cents(locked) + cents(p.addon.totals.total))
      // the agent does not hold price.view_cost: no pricing explanation
      expect(p.addon.explanation).toBeUndefined()
      await expect(drawer.getByRole("group", { name: "With the extras", exact: true }).locator("data[value]")).toHaveAttribute("value", p.new_total)

      await drawer.getByLabel("Note (optional)", { exact: true }).fill(`Pick-up at the airport (${run})`)
      const [ar] = await Promise.all([
        page.waitForResponse((r) => isMethod(r.url(), "kamra.tex.api.crs.addon_apply")),
        drawer.getByRole("button", { name: /^Add to reservation/ }).click(),
      ])
      const aBody = (await ar.json().catch(() => ({}))) as { message?: { total: string; balance: string } }
      expect(ar.ok(), `addon_apply ${ar.status()}: ${JSON.stringify(aBody).slice(0, 300)}`).toBeTruthy()
      expect(aBody.message).toMatchObject({ total: p.new_total, balance: p.new_total })
      await expect(drawer).toBeHidden()
      await expect.poll(async () => (await readLockedPrice(page)).amount).toBe(p.new_total)
      const revs = await readRevisions(page)
      expect(revs[0]).toMatchObject({ changeType: "Extras", oldAmount: locked, newAmount: p.new_total })
      expect(revs[0].text).toContain(`Added: ${TRF.name} × 1`)
      total = p.new_total
    })

    await test.step("send a payment link for the balance", async () => {
      await page.getByRole("button", { name: "Send payment link", exact: true }).click()
      const dlg = page.getByRole("dialog", { name: "Send a payment link" })
      await expect(dlg).toBeVisible()
      // the amount starts at the server's balance: nothing is paid yet, the transfer included
      await expect(byLabel(dlg, "Amount")).toHaveValue(total)
      // shown once on screen, not e-mailed (the bench may have no outgoing e-mail account)
      await dlg.getByRole("checkbox", { name: "E-mail the link to the guest" }).uncheck()
      const [lr] = await Promise.all([
        page.waitForResponse((r) => isMethod(r.url(), "kamra.tex.api.payments.create_link")),
        dlg.getByRole("button", { name: "Create link", exact: true }).click(),
      ])
      const lBody = (await lr.json().catch(() => ({}))) as { message?: { link: string; url: string } }
      expect(lr.ok(), `create_link ${lr.status()}: ${JSON.stringify(lBody).slice(0, 300)}`).toBeTruthy()
      link = lBody.message!.link
      expect(lBody.message!.url).toContain("/pay#token=")
      await expect(byLabel(dlg, "Payment link")).toHaveValue(lBody.message!.url)
      await dlg.getByRole("button", { name: "Close", exact: true }).last().click()
      await expect(dlg).toBeHidden()
      // the booking's payments card lists the new link
      await expect(page.locator("li", { hasText: link }).first()).toBeVisible()
      const b = await pageApi<{ payment_links: { name: string; status: string; amount: string }[] }>(page, "kamra.tex.api.crs.booking", { name: booking })
      expect(b.message.payment_links.find((l) => l.name === link)).toMatchObject({ status: "Active", amount: total })
    })

    await test.step("re-send the confirmation with a new manage link", async () => {
      await page.getByRole("button", { name: "Re-send confirmation", exact: true }).click()
      const dlg = page.getByRole("dialog", { name: "Re-send the confirmation e-mail?" })
      await expect(dlg).toBeVisible()
      await expect(dlg.getByText("The previous manage link stops working immediately.", { exact: false })).toBeVisible()
      const [rr] = await Promise.all([
        page.waitForResponse((r) => isMethod(r.url(), "kamra.tex.api.crs.resend_confirmation")),
        dlg.getByRole("button", { name: "Re-send with new link", exact: true }).click(),
      ])
      const rBody = (await rr.json().catch(() => ({}))) as { message?: { booking: string; queued: boolean; email: string } }
      expect(rr.ok(), `resend_confirmation ${rr.status()}: ${JSON.stringify(rBody).slice(0, 300)}`).toBeTruthy()
      expect(rBody.message).toMatchObject({ booking, email })
      // the guest's link goes to the guest only, never to the agent's screen
      expect(JSON.stringify(rBody)).not.toMatch(/manage_token|token=/)
      // queued when the site sends e-mail, else said plainly: the new link was still made
      await expect(dlg.getByText(rBody.message!.queued ? `Confirmation queued for ${email}` : "The e-mail could not be queued").first()).toBeVisible()
      await dlg.getByRole("button", { name: "Close", exact: true }).last().click()
      await expect(dlg).toBeHidden()
    })

    await test.step("cancel the reservation inside the free-cancellation window", async () => {
      await page.getByRole("button", { name: "Cancel reservation", exact: true }).click()
      const dlg = page.getByRole("dialog", { name: `Cancel ${res}?` })
      await expect(dlg).toBeVisible()
      // the server's preview: nothing to pay this far ahead, and the agent cannot waive anyway
      await expect(dlg.getByText("Within the free cancellation window", { exact: false })).toBeVisible()
      await expect(dlg.getByRole("checkbox", { name: /Waive the penalty/ })).toHaveCount(0)
      const preview = await pageApi<{ penalty: string }>(page, "kamra.tex.api.crs.cancellation_preview", { reservation: res })
      expect(preview.message.penalty).toBe("0.00")
      await byLabel(dlg, "Reason").fill(`Guest cancelled by phone (${run})`)
      const [cr] = await Promise.all([
        page.waitForResponse((r) => isMethod(r.url(), "kamra.tex.api.crs.cancel")),
        dlg.getByRole("button", { name: "Cancel reservation", exact: true }).click(),
      ])
      expect(cr.ok(), `cancel ${cr.status()}`).toBeTruthy()
      cancelled = true
      await expect(dlg).toBeHidden()
      // a cancelled stay offers no more actions
      await expect(page.getByRole("button", { name: "Cancel reservation", exact: true })).toHaveCount(0)
      await expect(page.getByRole("button", { name: "Add extras", exact: true })).toHaveCount(0)
      const r = await pageApi<{ status: string; channel: string; revisions: { change_type: string }[] }>(page, "kamra.tex.api.crs.reservation", { name: res })
      expect(r.message.status).toBe("Cancelled")
      expect(r.message.channel).toBe("CALL_CENTER")
    })
    noErrors()
  } finally {
    // whatever happened above: the stay goes back to the demo inventory and the link closes
    if (res && !cancelled)
      await pageApi(page, "kamra.tex.api.crs.cancel", { reservation: res, reason: `E2E clean-up (${run})`, waive_penalty: 0 })
    if (link) await pageApi(page, "kamra.tex.api.payments.cancel_link", { name: link, reason: `E2E clean-up (${run})` })
  }
})

// ─── O-29: late answers (Call Center) ───────────────────────────────────────

const mdy = (iso: string) => `${iso.slice(5, 7)}${iso.slice(8, 10)}${iso.slice(0, 4)}`
const addDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}
/** Two animation frames: whatever a delivered answer changes is on screen. */
const frames = (page: Page) => page.evaluate(() => new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r()))))

/** The Call Center with the market (DE) and a check-in set; check-out follows (2 nights). */
async function callCenterSearchForm(page: Page, offsetDays: number) {
  await english(page)
  await login(page, AGENT)
  await page.goto(texPath("/tex/crs/call-center"))
  await expect(page.getByRole("heading", { level: 1, name: "Call Center" })).toBeVisible()
  await page.keyboard.press("Alt+KeyS")
  const market = byLabel(page, "Market")
  await expect(market).toBeFocused()
  await page.keyboard.type("Germ")
  await expect(market).toHaveValue("DE")
  const { checkIn } = stayDates(offsetDays, 2)
  await byLabel(page, "Check-in").focus()
  await page.keyboard.type(mdy(checkIn))
  await expect(byLabel(page, "Check-out")).toHaveValue(addDays(checkIn, 2))
  return checkIn
}

const results = (page: Page) => page.getByText(/ · market DE$/)

test("O-29: a search answered late never replaces the newer search's results", async ({ page }) => {
  const noErrors = trackErrors(page)
  const checkIn = await callCenterSearchForm(page, 150)
  // the first search (2 nights) is answered after the second (3 nights)
  const first = await holdNext(page, "kamra.tex.api.ui_crs.search")
  await page.keyboard.press("Alt+KeyS")
  await first.held
  await byLabel(page, "Check-out").fill(addDays(checkIn, 3))
  await Promise.all([page.waitForResponse((r) => isMethod(r.url(), "kamra.tex.api.ui_crs.search") && r.ok()), page.keyboard.press("Alt+KeyS")])
  await expect(results(page)).toContainText("3 nights")
  const late = page.waitForResponse((r) => isMethod(r.url(), "kamra.tex.api.ui_crs.search"))
  first.release()
  await late
  await frames(page)
  await expect(results(page)).toContainText("3 nights")
  noErrors()
})

test("O-29: the quote summary of a payment method left meanwhile never shows", async ({ page }) => {
  const noErrors = trackErrors(page)
  await callCenterSearchForm(page, 160)
  await Promise.all([page.waitForResponse((r) => isMethod(r.url(), "kamra.tex.api.ui_crs.search") && r.ok()), page.keyboard.press("Alt+KeyS")])
  await expect(page.getByRole("listbox", { name: "Offers" })).toBeFocused()
  await page.keyboard.press("ArrowDown")
  await Promise.all([page.waitForResponse((r) => isMethod(r.url(), "kamra.tex.api.ui_crs.quote_summary") && r.ok()), page.keyboard.press("Enter")])

  // the card's summary is held, and marked: its amount due now reads 987.65
  let release!: () => void
  const gate = new Promise<void>((r) => (release = r))
  let arrived!: () => void
  const held = new Promise<void>((r) => (arrived = r))
  await page.route(
    (url) => isMethod(url.href, "kamra.tex.api.ui_crs.quote_summary"),
    async (route) => {
      const response = await route.fetch()
      const body = (await response.json()) as { message: { due_now: string | null } }
      body.message.due_now = "987.65"
      arrived()
      await gate
      await route.fulfill({ response, json: body })
    },
    { times: 1 },
  )
  await page.getByRole("radio", { name: /Card/ }).check()
  await held
  // the agent moves on to bank transfer, whose summary answers first
  await Promise.all([
    page.waitForResponse((r) => isMethod(r.url(), "kamra.tex.api.ui_crs.quote_summary") && r.ok()),
    page.getByRole("radio", { name: /Bank transfer/ }).check(),
  ])
  await expect(page.getByText(/Due now/).first()).toBeVisible()
  const late = page.waitForResponse((r) => isMethod(r.url(), "kamra.tex.api.ui_crs.quote_summary"))
  release()
  await late
  await frames(page)
  await expect(page.getByText(/987\.65/)).toHaveCount(0)
  await expect(page.getByRole("radio", { name: /Bank transfer/ })).toBeChecked()
  noErrors()
})
