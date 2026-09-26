// G-60 / G-64 (ADR-060): the entry screens say TEX Engine and offer the source, the site root
// leads somewhere, and every navigation sub-section opens a working screen for a user who
// holds its capability, while a restricted user does not see the gated ones (and the server
// refuses them).
//   TEX_E2E_BASE=http://test.localhost:5182 TEX_E2E_BENCH=http://test.localhost:8012 \
//   TEX_E2E_PASSWORD=… npx playwright test -c e2e entry-branding
// TEX_E2E_BENCH is the Frappe server behind the SPA ("/" is a server redirect); it defaults to
// TEX_E2E_BASE when that is the bench itself.
//
// Review follow-up (ADR-060):
// - two-factor sign-in (M1) runs against a real second factor when the bench has one for a test
//   user: `bench --site <site> execute kamra.tex.devtools.e2e_two_factor.enable --kwargs
//   "{'password': '…'}"` prints the user and its authenticator secret; pass them as
//   TEX_E2E_2FA_USER / TEX_E2E_2FA_SECRET (and `…e2e_two_factor.disable` afterwards);
// - TEX_E2E_SOURCE_PREFIX: what the site config's `tex_source_url` starts with, when the run sets
//   one (the offer must then show it, not the default repository).
import { createHmac } from "node:crypto"
import { fileURLToPath } from "node:url"
import { expect, request, test, type Page } from "@playwright/test"
import { ADMIN_PASSWORD, APP_PREFIX, isoDate, login, PASSWORD, pageApi, texPath, trackErrors } from "./helpers"

const BASE = process.env.TEX_E2E_BASE || "http://test.localhost:8000"
const BENCH = process.env.TEX_E2E_BENCH || (APP_PREFIX ? BASE : "http://test.localhost:8000")
const HOTEL = "Aurora Beach Resort"
const SITE = "aurora"
const LANGS = ["English", "Türkçe", "Deutsch", "Русский", "Română", "Polski"]
const TWO_FACTOR_USER = process.env.TEX_E2E_2FA_USER || ""
const TWO_FACTOR_SECRET = process.env.TEX_E2E_2FA_SECRET || ""
const SOURCE_PREFIX = process.env.TEX_E2E_SOURCE_PREFIX || ""
/** The Desk script as this tree ships it (the dev bench serves /assets/kamra from another checkout). */
const DESK_SCRIPT = fileURLToPath(new URL("../../kamra/public/js/tex_source.js", import.meta.url))

/** The authenticator app's code for a base32 secret (RFC 6238: SHA-1, 30 s, 6 digits). */
function totp(secret: string, at = Date.now()): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
  const bits = [...secret.replace(/=+$/, "").toUpperCase()].map((c) => alphabet.indexOf(c).toString(2).padStart(5, "0")).join("")
  const key = Buffer.from((bits.match(/.{8}/g) ?? []).map((b) => parseInt(b, 2)))
  const counter = Buffer.alloc(8)
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 30_000)))
  const h = createHmac("sha1", key).update(counter).digest()
  const o = h[h.length - 1] & 0xf
  const n = ((h[o] & 0x7f) << 24) | (h[o + 1] << 16) | (h[o + 2] << 8) | h[o + 3]
  return String(n % 1_000_000).padStart(6, "0")
}

/** The signed-in user of the page's session, or null for a visitor. */
async function sessionUser(page: Page): Promise<string | null> {
  const r = await page.request.get("/api/method/frappe.auth.get_logged_user")
  if (!r.ok()) return null
  const user = ((await r.json()) as { message?: string }).message
  return user && user !== "Guest" ? user : null
}

/** What the server offers as the running version's source (the pages must show exactly this). */
async function offered(page: Page): Promise<string> {
  const r = await page.request.get("/api/method/kamra.tex.api.session.entry")
  expect(r.ok()).toBeTruthy()
  const url = ((await r.json()) as { message: { source_url: string } }).message.source_url
  expect(url).toMatch(/^https:\/\//)
  if (SOURCE_PREFIX) expect(url.startsWith(SOURCE_PREFIX), url).toBe(true)
  else expect(url).toMatch(/^https:\/\/github\.com\/travellerbuddha\/TexEngine\/tree\/[0-9a-f]{40}$/)
  return url
}

test.use({ locale: "en-US" })

async function english(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex-lang", "en")
      localStorage.setItem("tex-list-scope", "hotel")
    } catch {
      /* storage blocked: English is the default */
    }
  })
}

const noHorizontalScroll = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)

/** The sidebar's sub-sections of an area, opened with its toggle when closed. */
async function openArea(page: Page, area: string) {
  const nav = page.getByRole("navigation", { name: "Main navigation" })
  const toggle = nav.getByRole("button", { name: `${area}: sections` })
  if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click()
  await expect(toggle).toHaveAttribute("aria-expanded", "true")
  return nav
}

async function pickHotel(page: Page) {
  const select = page.getByRole("banner").getByRole("combobox", { name: "Hotel" })
  if (await select.count()) await select.selectOption(HOTEL)
}

test("sign-in page: TEX Engine brand, the six TEX languages, the source offer", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  await page.goto(texPath("/login"))
  await expect(page.getByRole("heading", { level: 1, name: "TEX Engine" })).toBeVisible()
  await expect(page).toHaveTitle("Sign in · TEX Engine")
  // the upstream wordmark ("kamra" + "PMS") is gone; Kamra PMS is credited in the source notice only
  await expect(page.getByText("PMS", { exact: true })).toHaveCount(0)
  await expect(page.getByRole("img", { name: "Kamra" })).toHaveCount(0)
  const lang = page.getByRole("combobox", { name: "Language" })
  await expect(lang.locator("option")).toHaveText(LANGS)

  const notice = page.getByTestId("tex-source-notice")
  await expect(notice).toContainText("Based on Kamra PMS · AGPL-3.0 · Source code")
  await expect(notice.getByRole("link", { name: "Kamra PMS" })).toHaveAttribute("href", "https://github.com/Kamra-PMS/kamra-pms")
  await expect(notice.getByRole("link", { name: "AGPL-3.0" })).toHaveAttribute("href", /gnu\.org\/licenses\/agpl-3\.0/)
  await expect(notice.getByRole("link", { name: "Source code" })).toHaveAttribute("href", /^https:\/\//)

  await lang.selectOption("tr")
  await expect(page.getByRole("heading", { name: "Giriş yap" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Giriş yap" })).toBeVisible()
  await expect(page.getByLabel("Şifre")).toBeVisible()
  await expect(page).toHaveTitle("Giriş yap · TEX Engine")
  await expect(notice.getByRole("link", { name: "Kaynak kod" })).toBeVisible()
  await page.getByRole("combobox", { name: "Dil" }).selectOption("de")
  await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible()
  await page.getByRole("combobox", { name: "Sprache" }).selectOption("en")

  // the page starts in its form (L7); the other ways in are Frappe's page (M1)
  await expect(page.getByLabel("Email or username")).toBeFocused()
  await expect(page.getByRole("link", { name: "Forgot password?" })).toHaveAttribute("href", "/login#forgot")
  await expect(page.getByRole("link", { name: "Other sign-in options" })).toHaveAttribute("href", "/login?redirect-to=%2Fkamra%2Ftex")

  // a refusal is told, and tied to the fields it concerns (L7)
  await page.getByLabel("Email or username").fill("revenue@demo.tex")
  await page.getByLabel("Password").fill("not the password")
  await page.getByRole("button", { name: "Sign in" }).click()
  const alert = page.getByRole("alert")
  await expect(alert).toHaveText("Wrong email, username or password.")
  const alertId = await alert.getAttribute("id")
  expect(alertId).toBeTruthy()
  for (const label of ["Email or username", "Password"]) {
    await expect(page.getByLabel(label)).toHaveAttribute("aria-invalid", "true")
    await expect(page.getByLabel(label)).toHaveAttribute("aria-describedby", new RegExp(`(^| )${alertId}( |$)`))
  }

  // the page signs in
  await page.getByLabel("Password").fill(PASSWORD)
  await page.getByRole("button", { name: "Sign in" }).click()
  await expect(page).toHaveURL(/\/tex$/)
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible()
  await expect(page).toHaveTitle("TEX Engine")
  noErrors()
})

test("sign-in: a two-factor account gives its code before it is signed in", async ({ page }) => {
  test.skip(!TWO_FACTOR_USER || !TWO_FACTOR_SECRET, "needs a bench user with a second factor (TEX_E2E_2FA_USER / TEX_E2E_2FA_SECRET)")
  const noErrors = trackErrors(page)
  await english(page)
  await page.goto(texPath("/login"))
  await page.getByLabel("Email or username").fill(TWO_FACTOR_USER)
  await page.getByLabel("Password").fill(PASSWORD)
  await page.getByRole("button", { name: "Sign in" }).click()

  // the password was right, but Frappe made no session: the page asks for the code (M1)
  await expect(page.getByRole("heading", { name: "Verification code" })).toBeVisible()
  await expect(page.getByText("Enter the code your authenticator app shows.")).toBeVisible()
  const code = page.getByRole("textbox", { name: "Code" })
  await expect(code).toBeFocused()
  expect(await sessionUser(page)).toBeNull()
  await expect(page).toHaveURL(/\/login$/)

  // a wrong code is refused and leaves the step open
  const right = totp(TWO_FACTOR_SECRET)
  await code.fill(String((Number(right) + 1) % 1_000_000).padStart(6, "0"))
  await page.getByRole("button", { name: "Verify" }).click()
  await expect(page.getByRole("alert")).toHaveText("That code is wrong or has expired.")
  await expect(code).toHaveAttribute("aria-invalid", "true")
  expect(await sessionUser(page)).toBeNull()

  // the right one signs in (a code near the end of its 30 s is not risked)
  if (Date.now() % 30_000 > 25_000) await page.waitForTimeout(30_000 - (Date.now() % 30_000) + 500)
  await code.fill(totp(TWO_FACTOR_SECRET))
  await page.getByRole("button", { name: "Verify" }).click()
  await expect(page).toHaveURL(/\/tex$/)
  expect(await sessionUser(page)).toBe(TWO_FACTOR_USER)
  noErrors()
})

test("sign-in: an answer without a session is never taken for one", async ({ page }) => {
  // Frappe's other answers (frappe/auth.py), played to the page: an expired password names the
  // reset page, a website user has no admin app; a reset page on another site is not followed
  const noErrors = trackErrors(page)
  await english(page)
  let answer: Record<string, unknown> = {}
  await page.route("**/api/method/login", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(answer) }))
  await page.route("**/update-password**", (route) => route.fulfill({ status: 200, contentType: "text/html", body: "<title>Set a new password</title>" }))
  await page.route("**/me", (route) => route.fulfill({ status: 200, contentType: "text/html", body: "<title>My account</title>" }))
  const signIn = async () => {
    await page.goto(texPath("/login"))
    await page.getByLabel("Email or username").fill("someone@example.com")
    await page.getByLabel("Password").fill("whatever")
    await page.getByRole("button", { name: "Sign in" }).click()
  }

  answer = { message: "Password Reset", redirect_to: "https://evil.example/update-password?key=x" }
  await signIn()
  await expect(page.getByRole("alert")).toHaveText('Your password has expired. Set a new one with "Forgot password?".')
  await expect(page).toHaveURL(/\/login$/)

  answer = { message: "Something else" }
  await signIn()
  await expect(page.getByRole("alert")).toHaveText("Signing in did not complete. Try the other sign-in options.")
  await expect(page).toHaveURL(/\/login$/)

  answer = { message: "Password Reset", redirect_to: `${new URL(BASE).origin}/update-password?key=e2e&password_expired=true` }
  await signIn()
  await expect(page).toHaveURL(/\/update-password\?key=e2e&password_expired=true$/)

  answer = { message: "No App", home_page: "/me" }
  await signIn()
  await expect(page).toHaveURL(/\/me$/)
  noErrors()
})

test("site root: a visitor goes to sign-in, a desk user to the TEX admin app", async () => {
  const visitor = await request.newContext({ baseURL: BENCH })
  let r = await visitor.get("/", { maxRedirects: 0 })
  expect(r.status()).toBe(302)
  expect(new URL(r.headers().location, BENCH).pathname).toBe("/kamra/login")
  r = await visitor.get("/kamra/login")
  expect(r.status()).toBe(200)
  expect(await r.text()).toContain("<title>TEX Engine</title>")
  await visitor.dispose()

  const staff = await request.newContext({ baseURL: BENCH })
  expect((await staff.post("/api/method/login", { data: { usr: "revenue@demo.tex", pwd: PASSWORD } })).ok()).toBeTruthy()
  r = await staff.get("/", { maxRedirects: 0 })
  expect(r.status()).toBe(302)
  expect(new URL(r.headers().location, BENCH).pathname).toBe("/kamra/tex")
  await staff.dispose()
})

test("navigation: every new sub-section opens its screen for a user who holds its capability", async ({ page }) => {
  test.setTimeout(180_000)
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, "revenue@demo.tex")
  await page.goto(texPath("/tex"))
  await pickHotel(page)

  const heading = (name: string) => page.getByRole("heading", { level: 1, name })
  const rows = page.locator("main table tbody tr")

  await test.step("Rates & Contracts: versions, periods, occupancy rules, rate plans", async () => {
    // while a list loads, its table shows placeholder rows (no data, nothing to open): the rows
    // counted and opened are those of the list's answer, each a link to its version
    const loaded = page.locator("main table tbody tr[tabindex='0']")
    for (const [entry, path, method, section] of [
      ["Contract versions", "/tex/rates/versions", "versions", null],
      ["Price periods", "/tex/rates/periods", "version_rows", "periods"],
      ["Occupancy rules", "/tex/rates/occupancy", "version_rows", "occupancy"],
      ["Rate plans", "/tex/rates/rate-plans", "version_rows", "rate_plans"],
    ] as const) {
      const answer = page.waitForResponse((r) => {
        const url = new URL(r.url())
        return url.pathname.endsWith(`/api/method/kamra.tex.api.lists.${method}`) && url.searchParams.get("section") === section
      })
      const nav = await openArea(page, "Rates & Contracts")
      await nav.getByRole("link", { name: entry, exact: true }).click()
      await expect(page).toHaveURL(new RegExp(`${path}$`))
      await expect(heading(entry)).toBeVisible()
      await expect(nav.getByRole("link", { name: entry, exact: true })).toHaveAttribute("aria-current", "page")
      const res = await answer
      expect(res.ok(), entry).toBeTruthy()
      const list = ((await res.json()) as { message: { rows: unknown[] } }).message
      expect(list.rows.length, `${entry}: rows in the list's answer`).toBeGreaterThan(0)
      await expect(loaded.first()).toBeVisible()
      await expect(rows).toHaveCount(await loaded.count()) // no placeholder row left
    }
    // a row opens its version on the matching table: Commercial rules, Rate plans
    await loaded.first().click()
    await expect(page).toHaveURL(/\/tex\/rates\/contracts\/[^/]+\/versions\/[^/#]+#plans$/)
    await expect(page.getByRole("tablist", { name: "Version sections", exact: true }).getByRole("tab", { name: /^Commercial rules/, selected: true })).toBeVisible()
    await expect(page.getByRole("tablist", { name: "Rule tables", exact: true }).getByRole("tab", { name: /^Rate plans/, selected: true })).toBeVisible()
  })

  await test.step("Rates & Contracts: restrictions across contracts, as ranges", async () => {
    const lookups = await pageApi<{ room_types: { name: string; room_type_name: string }[] }>(page, "kamra.tex.api.ui_rates.lookups", { property: HOTEL })
    const room = lookups.message.room_types[0]
    const first = isoDate(250 + Math.floor(Math.random() * 60))
    const last = isoDate(0, new Date(new Date(`${first}T12:00:00`).getTime() + 2 * 86_400_000))
    const set = await pageApi(page, "kamra.tex.api.crs.ari_bulk_update", { property: HOTEL, start: first, end: last, room_types: [room.name], restrictions: { min_los: 4 } })
    expect(set.ok, JSON.stringify(set.body).slice(0, 300)).toBeTruthy()
    try {
      const nav = await openArea(page, "Rates & Contracts")
      await nav.getByRole("link", { name: "Restrictions", exact: true }).click()
      await expect(page).toHaveURL(/\/tex\/rates\/restrictions$/)
      await expect(heading("Restrictions")).toBeVisible()
      await page.getByLabel("From", { exact: true }).fill(first)
      await page.getByLabel("To", { exact: true }).fill(last)
      const row = rows.filter({ hasText: "Minimum stay (nights): 4" }).filter({ hasText: room.room_type_name })
      await expect(row).toHaveCount(1)
      await expect(row).toContainText("3 days")
      // a row opens the grid on its first day
      await row.click()
      await expect(page).toHaveURL(new RegExp(`/tex/inventory\\?start=${first}$`))
      await expect(page.getByLabel("Start date")).toHaveValue(first)
    } finally {
      const clear = await pageApi(page, "kamra.tex.api.crs.ari_bulk_update", { property: HOTEL, start: first, end: last, room_types: [room.name], restrictions: { min_los: 0 } })
      expect(clear.ok, JSON.stringify(clear.body).slice(0, 300)).toBeTruthy()
    }
  })

  await test.step("Rates & Contracts: the bulk editor of the grid", async () => {
    const nav = await openArea(page, "Rates & Contracts")
    await nav.getByRole("link", { name: "Bulk editor", exact: true }).click()
    await expect(page.getByRole("dialog", { name: "Bulk update" })).toBeVisible()
    await expect(page).toHaveURL(/\/tex\/inventory$/)
    await page.getByRole("dialog", { name: "Bulk update" }).getByRole("button", { name: "Close" }).first().click()
  })

  await test.step("Booking Engine: rooms and analytics", async () => {
    let nav = await openArea(page, "Booking Engine")
    await nav.getByRole("link", { name: "Rooms", exact: true }).click()
    await expect(page).toHaveURL(/\/tex\/booking-engine\/rooms$/)
    await expect(heading("Rooms")).toBeVisible()
    const cards = page.getByRole("list", { name: "Rooms" }).getByRole("listitem").filter({ hasText: "Occupancy" })
    await expect(cards.first()).toBeVisible()
    await expect(cards.first()).toContainText("Translations")
    await page.getByRole("button", { name: "Translate room texts" }).click()
    await expect(page).toHaveURL(/\/tex\/booking-engine\/content\?kind=rooms$/)
    await expect(page.getByRole("radiogroup", { name: "Texts of" }).getByRole("radio", { name: "Rooms" })).toHaveAttribute("aria-checked", "true")

    nav = await openArea(page, "Booking Engine")
    await nav.getByRole("link", { name: "Analytics", exact: true }).click()
    await expect(page).toHaveURL(/\/tex\/booking-engine\/analytics$/)
    await expect(heading("Analytics")).toBeVisible()
    await expect(page.getByText("Booking funnel")).toBeVisible()
    await expect(page.getByRole("region", { name: "Summary" }).getByText("Searches")).toBeVisible()
    await expect(page.getByText("Tracking and consent")).toBeVisible()
    // the full conversion view is a report (G-46)
    await page.getByRole("button", { name: "Conversion report" }).click()
    await expect(page).toHaveURL(/\/tex\/reports\/conversion$/)
  })

  await test.step("CRM: loyalty and communications as sections; campaigns plainly not available", async () => {
    let nav = await openArea(page, "CRM")
    await nav.getByRole("link", { name: "Loyalty", exact: true }).click()
    await expect(page).toHaveURL(/\/tex\/crm\/loyalty$/)
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible()

    nav = await openArea(page, "CRM")
    await nav.getByRole("link", { name: "Communications", exact: true }).click()
    await expect(page).toHaveURL(/\/tex\/crm\/communications$/)
    await expect(heading("Communications")).toBeVisible()
    await expect(page.locator("main table")).toBeVisible()

    // not started: listed as not available, never a link
    await expect(nav.getByRole("link", { name: /Campaigns/ })).toHaveCount(0)
    await expect(page.getByTestId("tex-nav-crm-campaigns")).toHaveText(/Campaigns\s*Not available yet/)
    await expect(page.getByTestId("tex-nav-crm-campaigns")).toHaveAttribute("aria-disabled", "true")
  })

  await test.step("the command palette reaches sub-sections", async () => {
    await page.keyboard.press("Control+k")
    await page.getByRole("combobox", { name: "Command palette" }).fill("price periods")
    await page.keyboard.press("Enter")
    await expect(page).toHaveURL(/\/tex\/rates\/periods$/)
  })
  noErrors()
})

test("navigation: a restricted user sees only what their capabilities open, and the server agrees", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, "agent@demo.tex") // Reservations Agent: prices without cost, no booking sites, no reports
  await page.goto(texPath("/tex"))
  await pickHotel(page)
  const nav = await openArea(page, "Rates & Contracts")
  for (const shown of ["Contracts", "Contract versions", "Rate plans", "Restrictions"])
    await expect(nav.getByRole("link", { name: shown, exact: true })).toBeVisible()
  for (const hidden of ["Price periods", "Occupancy rules", "Bulk editor"])
    await expect(nav.getByRole("link", { name: hidden, exact: true })).toHaveCount(0)
  await expect(nav.getByRole("link", { name: "Booking Engine", exact: true })).toHaveCount(0)
  // hiding is not the control: the lists refuse
  for (const [method, args] of [
    ["kamra.tex.api.lists.version_rows", { section: "periods", property: HOTEL }],
    ["kamra.tex.api.lists.version_rows", { section: "occupancy" }],
    ["kamra.tex.api.lists.rooms", { property: HOTEL }],
    ["kamra.tex.api.reports.dashboard", { property: HOTEL }],
  ] as const) {
    const r = await pageApi(page, method, args)
    expect(r.status, `${method} ${JSON.stringify(args)}`).toBe(403)
  }
  // a rate plan's adjustment is cost: the agent's rows carry none
  const plans = await pageApi<{ rows: Record<string, unknown>[] }>(page, "kamra.tex.api.lists.version_rows", { section: "rate_plans", property: HOTEL })
  expect(plans.ok).toBeTruthy()
  expect(plans.message.rows.length).toBeGreaterThan(0)
  expect(plans.message.rows.every((r) => !("op" in r) && !("value" in r))).toBe(true)
  noErrors()
})

test("375 px: the sign-in page and the new screens do not scroll sideways; the drawer navigates", async ({ page }) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  await page.setViewportSize({ width: 375, height: 812 })
  await english(page)
  await page.goto(texPath("/login"))
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible()
  expect(await noHorizontalScroll(page)).toBe(true)

  await login(page, "revenue@demo.tex")
  for (const path of [
    "/tex/rates/versions",
    "/tex/rates/periods",
    "/tex/rates/occupancy",
    "/tex/rates/rate-plans",
    "/tex/rates/restrictions",
    "/tex/booking-engine/rooms",
    "/tex/booking-engine/analytics",
    "/tex/crm/communications",
  ]) {
    await page.goto(texPath(path))
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible()
    await page.waitForLoadState("networkidle")
    expect(await noHorizontalScroll(page), path).toBe(true)
  }

  await page.getByRole("button", { name: "Open navigation" }).click()
  const nav = await openArea(page, "Rates & Contracts")
  expect(await noHorizontalScroll(page)).toBe(true)
  await nav.getByRole("link", { name: "Price periods", exact: true }).click()
  await expect(page).toHaveURL(/\/tex\/rates\/periods$/)
  await expect(page.getByRole("heading", { level: 1, name: "Price periods" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Close" })).toHaveCount(0) // the drawer closed
  noErrors()
})

test("source offer: guests and staff are offered the running version's source; the brand is the platform's", async ({ page, browser }) => {
  // AGPL-3.0 section 13 (M2, L1, L3): the booking engine (its pages, the widget's modal, payment and
  // error pages), the legacy guest pages still served, the sign-in page and the admin shell all
  // link the source of the version that runs; no hotel setting removes it
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  await english(page)
  const source = await offered(page)
  const brand = `Aurora Platform ${Date.now().toString(36)}`
  const admin = await request.newContext({ baseURL: BASE })
  expect((await admin.post("/api/method/login", { data: { usr: "Administrator", pwd: ADMIN_PASSWORD } })).ok()).toBeTruthy()
  const settings = async (data: Record<string, unknown>) => {
    const r = await admin.post("/api/method/kamra.tex.api.admin.save_settings", { data: { data: JSON.stringify(data) } })
    expect(r.ok(), await r.text()).toBeTruthy()
  }
  const before = ((await (await admin.get("/api/method/kamra.tex.api.admin.settings")).json()) as { message: { brand_name: string } }).message
  await settings({ brand_name: brand })
  try {
    const guestLine = (scope: Page | ReturnType<Page["frameLocator"]>) => scope.getByTestId("tex-source-notice")
    const expectGuestLine = async (scope: Page | ReturnType<Page["frameLocator"]>, what: string) => {
      const line = guestLine(scope)
      await expect(line, what).toContainText("Booking engine by TEX Engine · AGPL-3.0 · Source code")
      await expect(line.getByRole("link", { name: "Source code" }), what).toHaveAttribute("href", source)
      await expect(line.getByRole("link", { name: "AGPL-3.0" }), what).toHaveAttribute("href", /gnu\.org\/licenses\/agpl-3\.0/)
    }

    await test.step("the booking engine: a site, its manage page, a payment page, an unknown site", async () => {
      await page.goto(`/book/${SITE}`)
      await expectGuestLine(page, "site")
      await page.goto(`/book/${SITE}/manage`)
      await expectGuestLine(page, "manage")
      await page.goto("/book/pay")
      await expectGuestLine(page, "payment link")
      await page.goto("/book/no-such-site-e2e")
      await expectGuestLine(page, "unknown site")
    })

    await test.step("the widget's modal: the booking engine framed by a hotel's page", async () => {
      await page.goto("/book/pay")
      await page.setContent(`<iframe title="booking" src="${new URL(`/book/${SITE}?embed=1`, BASE).href}" style="width:900px;height:700px"></iframe>`)
      const frame = page.frameLocator('iframe[title="booking"]')
      await expect(frame.getByRole("contentinfo")).toHaveCount(0)             // no hotel footer in the modal
      await expectGuestLine(frame, "embedded")
    })

    await test.step("the legacy guest pages still served", async () => {
      await page.goto(texPath("/hk"))
      const line = page.getByTestId("tex-source-notice")
      await expect(line).toContainText("Based on Kamra PMS · AGPL-3.0 · Source code")
      await expect(line.getByRole("link", { name: "Source code" })).toHaveAttribute("href", source)
    })

    await test.step("the sign-in page: the platform's brand, the same offer", async () => {
      await page.goto(texPath("/login"))
      await expect(page.getByRole("heading", { level: 1, name: brand })).toBeVisible()
      await expect(page).toHaveTitle(`Sign in · ${brand}`)
      await expect(page.getByTestId("tex-source-notice").getByRole("link", { name: "Source code" })).toHaveAttribute("href", source)
    })

    await test.step("the page the server renders carries the offer and the brand itself", async () => {
      const visitor = await request.newContext({ baseURL: BENCH })
      const html = await (await visitor.get("/kamra/login")).text()
      expect(html).toContain(`<title>${brand}</title>`)
      expect(html).toContain(`<meta name="tex-source-url" content="${source.replace(/&/g, "&amp;")}"`)
      expect(html).toContain(`<meta name="tex-brand" content="${brand}"`)
      const book = await (await visitor.get(`/book/${SITE}`)).text()
      expect(book).toContain(`<meta name="tex-source-url" content="${source.replace(/&/g, "&amp;")}"`)
      await visitor.dispose()
    })

    await test.step("the admin shell", async () => {
      const context = await browser.newContext({ baseURL: BASE, locale: "en-US" })
      const staff = await context.newPage()
      await english(staff)
      await login(staff, "revenue@demo.tex")
      await staff.goto(texPath("/tex"))
      const nav = staff.getByRole("navigation", { name: "Main navigation" })
      await expect(nav).toBeVisible()
      await expect(staff.getByTestId("tex-source-notice").getByRole("link", { name: "Source code" }).first()).toHaveAttribute("href", source)
      await context.close()
    })
  } finally {
    await settings({ brand_name: before.brand_name || "TEX Engine" })
    await admin.dispose()
  }
  noErrors()
})

test("source offer: Desk's About dialog names TEX Engine, its licence and the running version's source", async ({ page }) => {
  const noErrors = trackErrors(page)
  // Desk is the bench's page; it loads the script from /assets (this tree's file, see DESK_SCRIPT)
  await page.route("**/assets/kamra/js/tex_source.js*", (route) => route.fulfill({ path: DESK_SCRIPT, contentType: "application/javascript" }))
  const r = await page.request.post(`${BENCH}/api/method/login`, { data: { usr: "Administrator", pwd: ADMIN_PASSWORD } })
  expect(r.ok()).toBeTruthy()
  await page.goto(`${BENCH}/app/todo`)
  await page.waitForFunction(() => !!(window as unknown as { frappe?: { boot?: unknown; ui?: { misc?: { about?: unknown } } } }).frappe?.ui?.misc?.about)
  const source = await page.evaluate(() => (window as unknown as { frappe: { boot: { tex_source_url?: string } } }).frappe.boot.tex_source_url)
  expect(source).toMatch(/^https:\/\//)
  if (SOURCE_PREFIX) expect(source!.startsWith(SOURCE_PREFIX)).toBe(true)
  await page.evaluate(() => (window as unknown as { frappe: { ui: { misc: { about: () => void } } } }).frappe.ui.misc.about())
  const offer = page.locator(".about-dialog [data-tex-source-notice]")
  await expect(offer).toBeVisible()
  await expect(offer).toContainText("TEX Engine")
  await expect(offer.getByRole("link", { name: "Kamra PMS" })).toHaveAttribute("href", "https://github.com/Kamra-PMS/kamra-pms")
  await expect(offer.getByRole("link", { name: "AGPL-3.0" })).toHaveAttribute("href", /gnu\.org\/licenses\/agpl-3\.0/)
  await expect(offer.getByRole("link", { name: "Source Code" })).toHaveAttribute("href", source!)
  // opened again, the dialog is reused: the offer is not repeated
  await page.keyboard.press("Escape")
  await page.evaluate(() => (window as unknown as { frappe: { ui: { misc: { about: () => void } } } }).frappe.ui.misc.about())
  await expect(page.locator(".about-dialog [data-tex-source-notice]")).toHaveCount(1)
  noErrors()
})

test("booking engine admin: a site opens under /sites, whatever its name; old links still land on it", async ({ page }) => {
  // M3: a site named like one of the area's pages (rooms, analytics…) opened that page instead
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, "revenue@demo.tex")
  await page.goto(texPath("/tex/booking-engine"))
  await page.getByRole("row").filter({ hasText: "Aurora Riviera Collection" }).first().click()
  await expect(page).toHaveURL(new RegExp(`/tex/booking-engine/sites/${SITE}$`))
  await expect(page.getByRole("heading", { level: 1, name: "Aurora Riviera Collection" })).toBeVisible()
  const nav = await openArea(page, "Booking Engine")
  await expect(nav.getByRole("link", { name: "Sites", exact: true })).toHaveAttribute("aria-current", "page")

  // a link from before the move still opens the site
  await page.goto(texPath(`/tex/booking-engine/${SITE}?tab=domains`))
  await expect(page).toHaveURL(new RegExp(`/tex/booking-engine/sites/${SITE}\\?tab=domains$`))

  // a new site may not take one of the area's page names
  await page.goto(texPath("/tex/booking-engine/new"))
  await expect(page.getByRole("heading", { level: 1, name: "New booking site" })).toBeVisible()
  await page.getByLabel(/^Address \(slug\)/).fill("rooms")
  await page.getByRole("button", { name: "Create site" }).click()
  await expect(page.getByText("This address is reserved. Choose another slug.")).toBeVisible()
  await expect(page).toHaveURL(/\/tex\/booking-engine\/new$/)
  noErrors()
})
