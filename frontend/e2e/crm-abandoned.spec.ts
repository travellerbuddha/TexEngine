// LO-27 (Part 2K-6): the abandoned-bookings list offers a guest's phone only for the channels the guest agreed to:
// an sms: link, a WhatsApp link to an international number (opened apart, no referrer), and never a call. There is no
// tel: link, because TEX records no consent to be called (O-26). Which contact data a row carries is the server's
// (crm.service.abandoned, its integration tests). How the page offers it is under test here, so the rows are the
// server's shape, served by the test.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e crm-abandoned
import { expect, test, type Page } from "@playwright/test"
import { login, texPath, trackErrors } from "./helpers"

/** crm.view at the demo hotels */
const REVENUE = "revenue@demo.tex"

async function english(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex-lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
}

const row = (name: string, over: Record<string, unknown> = {}) => ({
  name,
  site: "aurora",
  stage_reached: "guest_details",
  status: "Open",
  guest: `G-${name}`,
  email: `${name.toLowerCase()}@example.com`,
  phone: "+90 532 111 22 33",
  phone_channels: ["SMS", "WhatsApp"],
  consent_marketing: 1,
  value: "420.00",
  currency: "EUR",
  check_in: "2027-05-01",
  check_out: "2027-05-04",
  last_event_at: "2026-10-02 10:00:00",
  recovered_booking: null,
  ...over,
})

test("the abandoned list offers SMS and WhatsApp to a guest who agreed, and never a call (LO-27)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "the contact column is the wide screen's")
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, REVENUE)
  const rows = [
    row("AB-BOTH"),
    // SMS only: no WhatsApp link
    row("AB-SMS", { phone: "+49 170 1234567", phone_channels: ["SMS"] }),
    // WhatsApp agreed but the number is not international: wa.me cannot reach it, so no link
    row("AB-LOCAL", { phone: "0532 111 22 33", phone_channels: ["WhatsApp"] }),
    // no consent: anonymous, as the server sends it
    row("AB-ANON", { guest: null, email: null, phone: null, phone_channels: [], consent_marketing: 0 }),
  ]
  await page.route(
    (url) => new URL(url).pathname.endsWith("/api/method/kamra.tex.api.crm.abandoned"),
    (route) => route.fulfill({ status: 200, contentType: "application/json", json: { message: rows } }),
  )
  await page.goto(texPath("/tex/crm/abandoned"))
  await expect(page.getByRole("heading", { level: 1, name: "Abandoned bookings" })).toBeVisible()
  const main = page.getByRole("main")
  const rowOf = (email: string) => main.getByRole("row").filter({ has: page.getByRole("link", { name: email }) })

  const both = rowOf("ab-both@example.com")
  await expect(both.getByRole("link", { name: "SMS", exact: true })).toHaveAttribute("href", "sms:+90 532 111 22 33")
  const wa = both.getByRole("link", { name: "WhatsApp", exact: true })
  await expect(wa).toHaveAttribute("href", "https://wa.me/905321112233")
  await expect(wa).toHaveAttribute("target", "_blank")
  await expect(wa).toHaveAttribute("rel", /noreferrer/)

  const sms = rowOf("ab-sms@example.com")
  await expect(sms.getByRole("link", { name: "SMS", exact: true })).toHaveAttribute("href", "sms:+49 170 1234567")
  await expect(sms.getByRole("link", { name: "WhatsApp", exact: true })).toHaveCount(0)

  const local = rowOf("ab-local@example.com")
  await expect(local.getByText("0532 111 22 33")).toBeVisible()
  await expect(local.getByRole("link", { name: "WhatsApp", exact: true })).toHaveCount(0)
  await expect(local.getByRole("link", { name: "SMS", exact: true })).toHaveCount(0)

  // the anonymous case shows no contact at all
  await expect(main.getByText("No consent · anonymous").filter({ visible: true }).first()).toBeVisible()
  // never a call, on any row
  await expect(main.locator('a[href^="tel:"]')).toHaveCount(0)
  await expect(main.locator('a[href^="sms:"]')).toHaveCount(2)
  noErrors()
})
