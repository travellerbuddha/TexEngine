// The booking engine's session on the platform's origin (audit Part 2G-1, ADR-046 note).
// O-28: a staff member who opened the admin app (/kamra) holds a session with a CSRF token, which
// Frappe asks every POST to echo; the booking engine sent none, so the site did not even load for
// them. The page now carries the token for a signed-in user, and on such a page no third-party
// tracker loads: the hotel's tag container would run with that session on the platform's origin.
// O-27: the confirmation page linked to manage#token=…, so the manage token reached the address
// bar and the link's href, where a tag container reads it. The link now carries no token; the
// manage page reads it from the tab's storage.
// The site gets GA4, GTM and Meta pixel ids for the run (put back after it); the tracker hosts are
// answered by a stub that reports the page's address on load and on every history change, and
// every request to them is recorded. Stays are cancelled at the end (fee waived).
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e guest-session
import { expect, request as pwRequest, test, type APIRequestContext, type Page } from "@playwright/test"
import { ADMIN_PASSWORD, api, esc, login, PASSWORD, stayDates, texPath, trackErrors, uniqueRunId } from "./helpers"
import { bookPayAtHotel, fillGuest, guestSearch, pickRoom, readConfirmation } from "./flows/booking"

const BASE = process.env.TEX_E2E_BASE || "http://test.localhost:8000"
const SLUG = "aurora"
const HOTEL = "Aurora Beach Resort"
/** Staff who may cancel and waive the fee (clean-up). */
const HOTEL_ADMIN = "beach.gm@demo.tex"
/** Valid ids for the engine, the admin form and the server (G-62). */
const IDS = { ga4_measurement_id: "G-TEXE2E0001", gtm_container_id: "GTM-TEXE2E1", meta_pixel_id: "1234567890" }
const TRACKER_HOST = /(^|\.)(googletagmanager\.com|google-analytics\.com|connect\.facebook\.net|facebook\.com)$/

// what the tracker scripts get: report the address on load and on every history change, as a
// tag container's page-view and history triggers do
const STUB = `(function () {
  if (window.__texTrackerStub) return
  window.__texTrackerStub = true
  var send = function () { new Image().src = "https://www.google-analytics.com/g/collect?dl=" + encodeURIComponent(location.href) }
  ;["pushState", "replaceState"].forEach(function (k) {
    var orig = history[k]
    history[k] = function () { var r = orig.apply(this, arguments); send(); return r }
  })
  addEventListener("popstate", send)
  addEventListener("hashchange", send)
  send()
})()`

/** Answer every tracker host with the stub (scripts) or an empty reply, and record each request
 * (decoded, body included). */
async function stubTrackers(page: Page) {
  const seen: string[] = []
  await page.route(
    (url) => TRACKER_HOST.test(url.hostname),
    async (route) => {
      const req = route.request()
      let url = req.url()
      try {
        url = decodeURIComponent(url)
      } catch {
        /* keep it as sent */
      }
      seen.push(`${url} ${req.postData() ?? ""}`)
      if (req.resourceType() === "script") await route.fulfill({ status: 200, contentType: "application/javascript", body: STUB })
      else await route.fulfill({ status: 204, body: "" })
    },
  )
  return seen
}

/** The guest has accepted the site's trackers (the demo site asks first: consent_banner). */
async function consentGiven(page: Page) {
  await page.addInitScript((slug) => {
    try {
      localStorage.setItem(`tex.consent.${slug}`, "granted")
    } catch {
      /* storage blocked */
    }
  }, SLUG)
}

/** Administrator API context (settings of the shared demo site). */
async function admin(): Promise<APIRequestContext> {
  const ctx = await pwRequest.newContext({ baseURL: BASE })
  const r = await ctx.post("/api/method/login", { data: { usr: "Administrator", pwd: ADMIN_PASSWORD } })
  expect(r.ok(), "login Administrator").toBeTruthy()
  return ctx
}

type SiteIds = Record<keyof typeof IDS, string | null>

/** Give the site tracker ids for `body`, and put the site's own values back after it. */
async function withTrackers(body: () => Promise<void>) {
  const ctx = await admin()
  try {
    const before = await api<SiteIds & { consent_banner: number }>(ctx, "frappe.client.get_value", {
      doctype: "TEX Booking Site",
      filters: SLUG,
      fieldname: [...Object.keys(IDS), "consent_banner"],
    })
    await api(ctx, "frappe.client.set_value", { doctype: "TEX Booking Site", name: SLUG, fieldname: IDS })
    try {
      await body()
    } finally {
      const back = Object.fromEntries(Object.keys(IDS).map((k) => [k, before[k as keyof SiteIds] ?? ""]))
      await api(ctx, "frappe.client.set_value", { doctype: "TEX Booking Site", name: SLUG, fieldname: back })
    }
  } finally {
    await ctx.dispose()
  }
}

/** Dates and a rate plan of the hotel that lets guests pay at the hotel (as the public API reports it,
 * asked without any session). */
async function payAtHotelStay(offsetDays: number) {
  const { checkIn, checkOut } = stayDates(offsetDays, 2)
  const guest = await pwRequest.newContext({ baseURL: BASE })
  try {
    const found = await api<{ properties: { offers: { rate_plan_info?: { name?: string; payment_policy?: { allow_pay_at_hotel?: boolean } } }[] }[] }>(
      guest,
      "kamra.tex.api.public.search",
      { site: SLUG, hotel: HOTEL, check_in: checkIn, check_out: checkOut, rooms: [{ adults: 2, children: [] }] },
    )
    const plans = new Set(
      found.properties.flatMap((p) => p.offers.filter((o) => o.rate_plan_info?.payment_policy?.allow_pay_at_hotel).map((o) => o.rate_plan_info?.name ?? "")),
    )
    expect(plans.size, `a rate plan payable at ${HOTEL}`).toBeGreaterThan(0)
    return { checkIn, checkOut, plans }
  } finally {
    await guest.dispose()
  }
}

/** Search, pick a rate payable at the hotel, fill the guest and book: the confirmation. */
async function bookAtHotel(page: Page, offsetDays: number, lastName: string) {
  const { checkIn, checkOut, plans } = await payAtHotelStay(offsetDays)
  const found = await guestSearch(page, { checkIn, checkOut, rooms: [{ adults: 2 }], hotel: HOTEL })
  const rate = found.rates.find((r) => plans.has(r.ratePlan))
  expect(rate, `a rate payable at the hotel among ${found.rates.map((r) => r.ratePlan).join(", ")}`).toBeTruthy()
  await pickRoom(page, { roomName: rate!.room, ratePlan: rate!.ratePlan, board: rate!.board })
  await fillGuest(page, { firstName: "Deniz", lastName, email: "deniz.session@example.com", phone: "+49 170 5551234", country: "DE" })
  await bookPayAtHotel(page)
  return readConfirmation(page)
}

/** The guest's manage token, from the booking response itself: the stay is cleaned up even when a
 * later step fails. */
function manageTokenOf(page: Page) {
  const got = { token: "" }
  page.on("response", async (r) => {
    if (new URL(r.url()).pathname !== "/api/method/kamra.tex.api.public.book" || !r.ok()) return
    const b = (await r.json().catch(() => null)) as { message?: { manage_token?: string } } | null
    if (b?.message?.manage_token) got.token = b.message.manage_token
  })
  return got
}

/** Cancel every room of the booking (fee waived) so the demo inventory is left as found. */
async function cancelBooking(token: string) {
  const ctx = await pwRequest.newContext({ baseURL: BASE })
  try {
    const st = await api<{ rooms: { reservation: string }[] }>(ctx, "kamra.tex.api.public.booking_status", { token })
    const ok = await ctx.post("/api/method/login", { data: { usr: HOTEL_ADMIN, pwd: PASSWORD } })
    expect(ok.ok(), `login ${HOTEL_ADMIN}`).toBeTruthy()
    for (const r of st.rooms)
      await api(ctx, "kamra.tex.api.crs.cancel", { reservation: r.reservation, reason: "E2E clean-up (guest session)", waive_penalty: 1 })
    const after = await api<{ status: string }>(ctx, "kamra.tex.api.public.booking_status", { token })
    expect(after.status).toBe("Cancelled")
  } finally {
    await ctx.dispose()
  }
}

test("O-28: a signed-in staff member books on the booking site, and no tracker loads meanwhile", async ({ page }) => {
  test.setTimeout(180_000)
  const noErrors = trackErrors(page)
  const seen = await stubTrackers(page)
  await consentGiven(page)
  const manage = manageTokenOf(page)
  await withTrackers(async () => {
    try {
      await login(page, "agent@demo.tex")
      // the admin app gives the session its CSRF token; the cookies stay for the booking site
      await page.goto(texPath("/tex"))
      const done = await bookAtHotel(page, 240, `Staff ${uniqueRunId()}`)
      const booking = done.booking
      expect(done.status).toBe("Confirmed")
      // a staff booking on a public site is reportable (ADR-050 review)
      const ctx = await admin()
      try {
        const row = await api<{ created_via: string }>(ctx, "frappe.client.get_value", { doctype: "TEX Booking", filters: booking, fieldname: "created_via" })
        expect(row.created_via).toBe("Desk")
        const events = await api<{ name: string }[]>(ctx, "frappe.client.get_list", {
          doctype: "TEX Audit Event",
          filters: { action: "booking.staff_on_site", reference_name: booking },
          fields: ["name"],
        })
        expect(events).toHaveLength(1)
      } finally {
        await ctx.dispose()
      }
      expect(seen, "no request reached a tracker host").toEqual([])
      noErrors()
    } finally {
      if (manage.token) await cancelBooking(manage.token)
    }
  })
})

test("O-27: the manage token never reaches a URL, a link or a tracker", async ({ page }) => {
  test.setTimeout(180_000)
  const noErrors = trackErrors(page)
  const seen = await stubTrackers(page)
  await consentGiven(page)
  const manage = manageTokenOf(page)
  await withTrackers(async () => {
    try {
      const done = await bookAtHotel(page, 280, `Guest ${uniqueRunId()}`)
      expect(done.status).toBe("Confirmed")
      expect(manage.token, "the booking response carried a manage token").not.toBe("")
      // the guest's trackers run on this page (consent given): the stub reported it
      await expect.poll(() => seen.filter((s) => s.includes("/g/collect")).length).toBeGreaterThan(0)

      const link = page.getByRole("link", { name: "Manage booking", exact: true })
      await expect(link).toHaveAttribute("href", `/book/${SLUG}/manage`)
      await link.click()
      await expect(page.getByRole("heading", { level: 1, name: "Manage your booking" })).toBeVisible({ timeout: 30_000 })
      await expect(page.getByText(done.booking, { exact: true }).first()).toBeVisible()
      // the tag container saw the manage page (history trigger), without any token
      await expect.poll(() => seen.some((s) => new RegExp(`/book/${esc(SLUG)}/manage`).test(s))).toBe(true)
      expect(page.url()).not.toContain(manage.token)
      for (const s of seen) {
        expect(s).not.toContain("token=")
        expect(s).not.toContain(manage.token)
      }
      noErrors()
    } finally {
      if (manage.token) await cancelBooking(manage.token)
    }
  })
})
