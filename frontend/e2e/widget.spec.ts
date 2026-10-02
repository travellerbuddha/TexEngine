// The embeddable search widget (<tex-booking-widget>, R-30, ADR-012; G-44). A host page on the bench's
// origin loads the committed widget bundle, as a hotel website would. The "aurora" site gets a brand
// colour other than the widget's default (#1C3FA8, the demo colour) and pill buttons for the run, put
// back after it. The widget takes the site's theme, opens the booking engine in its modal with the
// search, and never leaves the host page locked: closing the modal, removing the element or
// re-rendering it (an attribute change) gives the page its scrolling back, and a re-render keeps the
// site's theme.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e widget
import { expect, request as pwRequest, test, type Page } from "@playwright/test"
import { ADMIN_PASSWORD, api, stayDates, trackErrors } from "./helpers"

const BASE = process.env.TEX_E2E_BASE || "http://test.localhost:8000"
const SLUG = "aurora"
const COLOR = "#7B2D8E"
const HOST_PAGE = `${BASE}/__e2e/widget-host`

const HOST_HTML = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Hotel website</title>
<script type="module" src="/assets/kamra/tex/tex-widget.js"></script></head>
<body><h1>Hotel website</h1><tex-booking-widget site="${SLUG}" lang="tr" market="GLOBAL"></tex-booking-widget>
<div style="height:3000px"></div></body></html>`

/** The widget's brand colour as its shadow root computes it. */
const brand = (page: Page) =>
  page.evaluate(() => {
    const w = document.querySelector("tex-booking-widget")?.shadowRoot?.querySelector(".w")
    return w ? getComputedStyle(w).getPropertyValue("--p").trim().toLowerCase() : ""
  })

const overflow = (page: Page) => page.evaluate(() => document.documentElement.style.overflow)

/** Fill the dates and search: the modal opens with the booking engine. */
async function search(page: Page, checkIn: string, checkOut: string) {
  await page.locator("tex-booking-widget #ci").fill(checkIn)
  await page.locator("tex-booking-widget #co").fill(checkOut)
  await page.locator("tex-booking-widget button.go").click()
  await expect(page.locator("tex-booking-widget dialog")).toBeVisible()
}

test("the widget keeps the site's theme and never leaves the host page locked", async ({ page }) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  const admin = await pwRequest.newContext({ baseURL: BASE })
  const r = await admin.post("/api/method/login", { data: { usr: "Administrator", pwd: ADMIN_PASSWORD } })
  expect(r.ok(), "login Administrator").toBeTruthy()
  const before = await api<{ primary_color: string | null; button_style: string | null }>(admin, "frappe.client.get_value", {
    doctype: "TEX Booking Site",
    filters: SLUG,
    fieldname: ["primary_color", "button_style"],
  })
  await api(admin, "frappe.client.set_value", { doctype: "TEX Booking Site", name: SLUG, fieldname: { primary_color: COLOR, button_style: "pill" } })
  try {
    await page.route(HOST_PAGE, (route) => route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: HOST_HTML }))
    await page.goto(HOST_PAGE)
    // 1. the site's theme
    await expect.poll(() => brand(page)).toBe(COLOR.toLowerCase())

    // 2. the search opens the engine in the modal, with the search and the widget's settings
    const { checkIn, checkOut } = stayDates(300, 2)
    await search(page, checkIn, checkOut)
    const src = (await page.locator("tex-booking-widget iframe").getAttribute("src")) ?? ""
    const url = new URL(src, BASE)
    expect(url.pathname).toBe(`/book/${SLUG}`)
    expect(Object.fromEntries(url.searchParams)).toMatchObject({ checkin: checkIn, checkout: checkOut, rooms: "2", lang: "tr", embed: "1", market: "GLOBAL" })
    await expect
      .poll(
        async () => {
          const frame = page.frames().find((f) => f.url().startsWith(`${BASE}/book/${SLUG}?`))
          if (!frame) return ""
          return frame.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--bk-primary").trim()).catch(() => "")
        },
        { timeout: 30_000 },
      )
      .toBe(COLOR.toLowerCase())
    expect(await overflow(page)).toBe("hidden")

    // 3. closing the modal gives the page its scrolling back
    await page.locator("tex-booking-widget button.x").click()
    await expect(page.locator("tex-booking-widget dialog")).toBeHidden()
    expect(await overflow(page)).toBe("")

    // a re-render (another language) while the modal is open replaces it: the page is not left locked,
    // 4. and the site's theme stays
    await search(page, checkIn, checkOut)
    expect(await overflow(page)).toBe("hidden")
    await page.evaluate(() => document.querySelector("tex-booking-widget")!.setAttribute("lang", "de"))
    await expect(page.locator("tex-booking-widget button.go")).toHaveText("Suchen")
    expect(await overflow(page)).toBe("")
    expect(await brand(page)).toBe(COLOR.toLowerCase())

    // removing the element while the modal is open gives the page its scrolling back
    await search(page, checkIn, checkOut)
    expect(await overflow(page)).toBe("hidden")
    await page.evaluate(() => document.querySelector("tex-booking-widget")!.remove())
    expect(await overflow(page)).toBe("")
    noErrors()
  } finally {
    await api(admin, "frappe.client.set_value", {
      doctype: "TEX Booking Site",
      name: SLUG,
      fieldname: { primary_color: before.primary_color ?? "", button_style: before.button_style ?? "" },
    })
    await admin.dispose()
  }
})

test("when its site changes, the modal names no hotel until the new site's theme arrives (LO-31)", async ({ page }) => {
  const noErrors = trackErrors(page)
  const OTHER = "lo31-other"
  const title = () => page.evaluate(() => document.querySelector("tex-booking-widget")?.shadowRoot?.querySelector(".mt")?.textContent ?? "")
  await page.route(HOST_PAGE, (route) => route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: HOST_HTML }))
  // the other site's theme arrives only when the test lets it
  let release: () => void = () => undefined
  const held = new Promise<void>((resolve) => (release = resolve))
  await page.route(
    (url) => url.pathname === "/api/method/kamra.tex.api.public.site" && url.searchParams.get("slug") === OTHER,
    async (route) => {
      await held
      await route.fulfill({ status: 200, contentType: "application/json", json: { message: { name: "Other Resort", branding: {} } } })
    },
  )
  await page.goto(HOST_PAGE)
  // the aurora site's name, once its theme is applied (the widget's own word before: "Rezervasyon", lang tr)
  await expect.poll(title).not.toBe("Rezervasyon")
  const aurora = await title()
  expect(aurora).not.toBe("")

  await page.evaluate((slug) => document.querySelector("tex-booking-widget")!.setAttribute("site", slug), OTHER)
  // re-rendered for the other site, its theme not here yet: never the previous site's name
  expect(await title()).toBe("Rezervasyon")
  release()
  await expect.poll(title).toBe("Other Resort")
  noErrors()
})

test("a modal closed by the browser itself gives the host page its scrolling back (LO-49)", async ({ page }) => {
  const noErrors = trackErrors(page)
  await page.route(HOST_PAGE, (route) => route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: HOST_HTML }))
  await page.goto(HOST_PAGE)
  const { checkIn, checkOut } = stayDates(305, 2)
  await search(page, checkIn, checkOut)
  expect(await overflow(page)).toBe("hidden")
  // closed without the widget's own close button or Escape (a close request the page could not cancel, a script)
  await page.evaluate(() => document.querySelector("tex-booking-widget")!.shadowRoot!.querySelector("dialog")!.close())
  await expect(page.locator("tex-booking-widget dialog")).toBeHidden()
  await expect.poll(() => overflow(page)).toBe("")
  noErrors()
})
