// G-60 / G-64 (ADR-060): the entry screens say TEX Engine and offer the source, the site root
// leads somewhere, and every navigation sub-section opens a working screen for a user who
// holds its capability, while a restricted user does not see the gated ones (and the server
// refuses them).
//   TEX_E2E_BASE=http://test.localhost:5182 TEX_E2E_BENCH=http://test.localhost:8012 \
//   TEX_E2E_PASSWORD=… npx playwright test -c e2e entry-branding
// TEX_E2E_BENCH is the Frappe server behind the SPA ("/" is a server redirect); it defaults to
// TEX_E2E_BASE when that is the bench itself.
import { expect, request, test, type Page } from "@playwright/test"
import { APP_PREFIX, isoDate, login, PASSWORD, pageApi, texPath, trackErrors } from "./helpers"

const BASE = process.env.TEX_E2E_BASE || "http://test.localhost:8000"
const BENCH = process.env.TEX_E2E_BENCH || (APP_PREFIX ? BASE : "http://test.localhost:8000")
const HOTEL = "Aurora Beach Resort"
const LANGS = ["English", "Türkçe", "Deutsch", "Русский", "Română", "Polski"]

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

  // the page signs in
  await page.getByLabel("Email or username").fill("revenue@demo.tex")
  await page.getByLabel("Password").fill(PASSWORD)
  await page.getByRole("button", { name: "Sign in" }).click()
  await expect(page).toHaveURL(/\/tex$/)
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible()
  await expect(page).toHaveTitle("TEX Engine")
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
    for (const [entry, path] of [
      ["Contract versions", "/tex/rates/versions"],
      ["Price periods", "/tex/rates/periods"],
      ["Occupancy rules", "/tex/rates/occupancy"],
      ["Rate plans", "/tex/rates/rate-plans"],
    ] as const) {
      const nav = await openArea(page, "Rates & Contracts")
      await nav.getByRole("link", { name: entry, exact: true }).click()
      await expect(page).toHaveURL(new RegExp(`${path}$`))
      await expect(heading(entry)).toBeVisible()
      await expect(nav.getByRole("link", { name: entry, exact: true })).toHaveAttribute("aria-current", "page")
      await expect(rows.first()).toBeVisible()
      expect(await rows.count(), entry).toBeGreaterThan(0)
    }
    // a row opens its version on the matching tab
    await rows.first().click()
    await expect(page).toHaveURL(/\/tex\/rates\/contracts\/[^/]+\/versions\/[^/#]+#plans$/)
    await expect(page.getByRole("tab", { name: /Rate plans/, selected: true })).toBeVisible()
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
