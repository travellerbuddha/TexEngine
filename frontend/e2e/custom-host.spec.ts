// G-21 (ADR-035): a booking site served on its own verified host. The demo seed verifies
// book.aurora.test for the "aurora" site (demo_seed.demo_host; ".test" never resolves
// publicly). Chromium resolves that name to the bench (--host-resolver-rules) and every
// request names the Frappe site (X-Frappe-Site-Name), so the bench serves the host exactly
// as it would a hotel's own domain: the engine at "/", pinned to its site, without the
// platform's /book/<slug> prefix. Another site's pages redirect home and its public API is
// refused on this host (while the platform host still answers for it). A guest books with
// pay at the hotel; the confirmation and manage pages stay on the host. The stay is
// cancelled at the end (fee waived) so the demo inventory is left as found.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e custom-host
import { expect, request as pwRequest, test, type APIRequestContext, type Page } from "@playwright/test"
import { ADMIN_PASSWORD, api, esc, PASSWORD, stayDates, trackErrors, uniqueRunId } from "./helpers"
import { bookPayAtHotel, fillGuest, guestSearch, pickRoom, readConfirmation } from "./flows/booking"

const PLATFORM = new URL(process.env.TEX_E2E_BASE || "http://test.localhost:8000")
const HOST = "book.aurora.test"
const HOST_PORT = PLATFORM.port ? `${HOST}:${PLATFORM.port}` : HOST
const ORIGIN = `${PLATFORM.protocol}//${HOST_PORT}`
const SLUG = "aurora"
const HOTEL = "Aurora Beach Resort"
/** Staff who may cancel and waive the fee (clean-up). */
const HOTEL_ADMIN = "beach.gm@demo.tex"

test.use({
  baseURL: ORIGIN,
  // the bench is one Frappe site reached under another host name
  extraHTTPHeaders: { "X-Frappe-Site-Name": PLATFORM.hostname },
  launchOptions: async ({ launchOptions }, use) =>
    use({ ...launchOptions, args: [...(launchOptions.args ?? []), `--host-resolver-rules=MAP ${HOST} ${PLATFORM.hostname}`] }),
})

/** API context on the platform host (not the custom one). */
const platform = () => pwRequest.newContext({ baseURL: PLATFORM.origin })

/** A public API call made by the page itself, i.e. from the custom host. */
async function hostApi(page: Page, method: string, args: Record<string, string>, post = false) {
  return page.evaluate(
    async ({ method, args, post }) => {
      const url = `/api/method/kamra.tex.api.public.${method}`
      const r = post
        ? await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(args), credentials: "include" })
        : await fetch(`${url}?${new URLSearchParams(args)}`, { credentials: "include" })
      const body = await r.json().catch(() => ({}))
      return { status: r.status, body: body as { message?: { slug?: string; name?: string }; exc_type?: string } }
    },
    { method, args, post },
  )
}

/** Where the page is: host and path (the address bar). */
const where = (page: Page) => {
  const u = new URL(page.url())
  return { host: u.host, path: u.pathname }
}

async function english(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex.book.lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
}

/** Another enabled booking site on this bench (a temporary one when there is none). */
async function otherSite(admin: APIRequestContext, run: string): Promise<{ slug: string; temporary: boolean }> {
  const rows = await api<{ site_slug: string }[]>(admin, "frappe.client.get_list", {
    doctype: "TEX Booking Site",
    filters: { enabled: 1, site_slug: ["!=", SLUG] },
    fields: ["site_slug"],
    limit_page_length: 1,
  })
  if (rows.length) return { slug: rows[0].site_slug, temporary: false }
  const slug = `e2e-${run.toLowerCase()}`
  await api(admin, "frappe.client.insert", {
    doc: { doctype: "TEX Booking Site", site_name: `E2E ${run}`, site_slug: slug, property: "Aurora City Hotel", enabled: 1 },
  })
  return { slug, temporary: true }
}

test("the site's own host serves its engine at / and a search stays on the host", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  const ctx = await platform()
  const site = await api<{ slug: string; name: string }>(ctx, "kamra.tex.api.public.site", { slug: SLUG })
  await ctx.dispose()

  await page.goto("/?lang=en")
  // the aurora group site: its name in the header, both of its hotels on the home page
  await expect(page.getByRole("banner")).toContainText(site.name)
  for (const hotel of ["Aurora Beach Resort", "Aurora City Hotel"])
    await expect(page.getByRole("heading", { level: 3, name: hotel, exact: true })).toBeVisible()
  await expect(page.getByRole("search", { name: "Search for a stay" })).toBeVisible()
  expect(where(page)).toEqual({ host: HOST_PORT, path: "/" })

  const { checkIn, checkOut } = stayDates(150, 2)
  const found = await guestSearch(page, { path: "/?lang=en", slug: SLUG, checkIn, checkOut, rooms: [{ adults: 2 }], hotel: HOTEL })
  expect(found.view).toBe("rooms")
  expect(found.rates.length, "rates on offer").toBeGreaterThan(0)
  for (const r of found.rates) expect(r.amount).toMatch(/^\d+\.\d{2}$/)
  // the address bar stays on the hotel's host, without the platform's /book/<slug>
  expect(where(page)).toEqual({ host: HOST_PORT, path: "/" })
  noErrors()
})

test("another site is not served on this host: its pages redirect home, its API is refused", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  const run = uniqueRunId()
  const admin = await platform()
  const login = await admin.post("/api/method/login", { data: { usr: "Administrator", pwd: ADMIN_PASSWORD } })
  expect(login.ok(), "login Administrator").toBeTruthy()
  const other = await otherSite(admin, run)
  try {
    // the platform host answers for that site …
    const onPlatform = await api<{ slug: string }>(admin, "kamra.tex.api.public.site", { slug: other.slug })
    expect(onPlatform.slug).toBe(other.slug)

    // … this host sends its pages home, to its own site's engine
    await page.goto(`/book/${other.slug}?lang=en`)
    await expect(page).toHaveURL(`${ORIGIN}/`)
    await expect(page.getByRole("search", { name: "Search for a stay" })).toBeVisible()

    // … and its public API answers for its own site only
    const own = await hostApi(page, "site", { slug: SLUG })
    expect(own.status).toBe(200)
    expect(own.body.message?.slug).toBe(SLUG)
    const refused = await hostApi(page, "site", { slug: other.slug })
    expect(refused.status, JSON.stringify(refused.body).slice(0, 300)).toBe(404)
    expect(refused.body.exc_type).toBe("DoesNotExistError")
    expect(refused.body.message).toBeUndefined()
    const stay = stayDates(150, 1)
    const search = await hostApi(page, "search", {
      site: other.slug,
      check_in: stay.checkIn,
      check_out: stay.checkOut,
      rooms: JSON.stringify([{ adults: 2, children: [] }]),
    }, true)                                   // search is POST only (a party may carry a date of birth)
    expect(search.status, JSON.stringify(search.body).slice(0, 300)).toBe(404)
    expect(search.body.exc_type).toBe("DoesNotExistError")
  } finally {
    if (other.temporary) await api(admin, "frappe.client.delete", { doctype: "TEX Booking Site", name: other.slug })
    await admin.dispose()
  }
  noErrors()
})

test("a guest books with pay at the hotel; confirmation and manage pages stay on the host", async ({ page }) => {
  test.setTimeout(180_000)
  const noErrors = trackErrors(page)
  await english(page)
  const { checkIn, checkOut } = stayDates(220, 2)
  // the guest's manage token, from the booking response itself: the stay is cleaned up even
  // when a later step fails
  let token = ""
  page.on("response", async (r) => {
    if (new URL(r.url()).pathname !== "/api/method/kamra.tex.api.public.book" || !r.ok()) return
    const b = (await r.json().catch(() => null)) as { message?: { manage_token?: string } } | null
    if (b?.message?.manage_token) token = b.message.manage_token
  })
  try {
    await page.goto("/?lang=en")
    // rate plans the hotel lets guests pay at the hotel (as the public API reports them)
    const offers = await page.evaluate(
      async (args) => {
        const r = await fetch("/api/method/kamra.tex.api.public.search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(args),
        })
        return ((await r.json()) as { message: { properties: { offers: { rate_plan_info?: { name?: string; payment_policy?: { allow_pay_at_hotel?: boolean } } }[] }[] } })
          .message
      },
      { site: SLUG, hotel: HOTEL, check_in: checkIn, check_out: checkOut, rooms: [{ adults: 2, children: [] }] },
    )
    const atHotel = new Set(
      offers.properties.flatMap((p) => p.offers.filter((o) => o.rate_plan_info?.payment_policy?.allow_pay_at_hotel).map((o) => o.rate_plan_info?.name ?? "")),
    )
    expect(atHotel.size, `a rate plan payable at ${HOTEL}`).toBeGreaterThan(0)

    const found = await guestSearch(page, { path: "/?lang=en", slug: SLUG, checkIn, checkOut, rooms: [{ adults: 2 }], hotel: HOTEL })
    const rate = found.rates.find((r) => atHotel.has(r.ratePlan))
    expect(rate, `a rate payable at the hotel among ${found.rates.map((r) => r.ratePlan).join(", ")}`).toBeTruthy()
    await pickRoom(page, { roomName: rate!.room, ratePlan: rate!.ratePlan, board: rate!.board })
    await fillGuest(page, {
      firstName: "Deniz",
      lastName: `Host ${uniqueRunId()}`,
      email: "deniz.host@example.com",
      phone: "+49 170 5551234",
      country: "DE",
    })
    expect(where(page).host).toBe(HOST_PORT)
    await bookPayAtHotel(page)

    // the confirmation is on the hotel's host, at /confirmation/<booking>
    const done = await readConfirmation(page, { url: new RegExp(`^${esc(ORIGIN)}/confirmation/[^/?#]+$`) })
    expect(done.heading).toBe("Your booking is confirmed")
    expect(done.status).toBe("Confirmed")
    expect(done.paymentStatus).toBe("Pay at the hotel")
    expect(where(page)).toEqual({ host: HOST_PORT, path: `/confirmation/${encodeURIComponent(done.booking)}` })
    await expect(page.getByRole("link", { name: /— home$/ })).toHaveAttribute("href", "/")

    // manage link: /manage on the same host, without the token (O-27): the manage page takes it
    // from the tab's storage, so no address or href a tag container reads carries it
    const manage = page.getByRole("link", { name: "Manage booking", exact: true })
    await expect(manage).toHaveAttribute("href", "/manage")
    expect(token, "the booking response carried a manage token").not.toBe("")
    await manage.click()
    await expect(page.getByRole("heading", { level: 1, name: "Manage your booking" })).toBeVisible({ timeout: 30_000 })
    expect(where(page)).toEqual({ host: HOST_PORT, path: "/manage" })
    await expect(page.getByText(done.booking, { exact: true }).first()).toBeVisible()
    noErrors()
  } finally {
    // whatever happened above: cancel the stay (fee waived) so the demo inventory is left as found
    if (token) {
      const ctx = await platform()
      try {
        const st = await api<{ rooms: { reservation: string }[] }>(ctx, "kamra.tex.api.public.booking_status", { token })
        const ok = await ctx.post("/api/method/login", { data: { usr: HOTEL_ADMIN, pwd: PASSWORD } })
        expect(ok.ok(), `login ${HOTEL_ADMIN}`).toBeTruthy()
        for (const r of st.rooms)
          await api(ctx, "kamra.tex.api.crs.cancel", { reservation: r.reservation, reason: "E2E clean-up (custom host)", waive_penalty: 1 })
        const after = await api<{ status: string }>(ctx, "kamra.tex.api.public.booking_status", { token })
        expect(after.status).toBe("Cancelled")
      } finally {
        await ctx.dispose()
      }
    }
  }
})
