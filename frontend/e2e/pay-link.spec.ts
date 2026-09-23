// G-83 (ADR-046): a payment link keeps its bearer token out of every request.
// - A link issued now is /book/pay#token=…: the fragment never reaches the server. The page
//   takes the token out of the address bar, keeps it for the tab and posts it to the API.
// - A link e-mailed before the change (/book/pay/<token>) still opens the same page: the token
//   leaves the path before the app makes a request.
// - Payment pages send no Referer (Referrer-Policy: no-referrer, header and meta tag).
// Every request the page makes is watched: none may carry the token in its URL or Referer.
// The link is created as Administrator on the demo "aurora" hotel and cancelled at the end.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_ADMIN_PASSWORD=… npx playwright test -c e2e pay-link
import { expect, request as pwRequest, test, type APIRequestContext, type Page } from "@playwright/test"
import { ADMIN_PASSWORD, api, trackErrors, uniqueRunId } from "./helpers"

const BASE = process.env.TEX_E2E_BASE || "http://test.localhost:8000"
const HOTEL = "Aurora Beach Resort"

interface Link {
  link: string
  url: string
  token: string
}

let admin: APIRequestContext
let link: Link

async function english(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex.book.lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
}

/** Every request the page makes, with its Referer. */
function watchRequests(page: Page) {
  const seen: { url: string; referer: string }[] = []
  page.on("request", (r) => seen.push({ url: r.url(), referer: r.headers()["referer"] ?? "" }))
  return seen
}

function expectTokenNowhere(seen: { url: string; referer: string }[], token: string) {
  expect(seen.length, "the page made requests").toBeGreaterThan(0)
  for (const r of seen) {
    expect(r.url, "request URL").not.toContain(token)
    expect(r.referer, `Referer of ${r.url}`).not.toContain(token)
  }
}

test.beforeAll(async () => {
  admin = await pwRequest.newContext({ baseURL: BASE })
  const login = await admin.post("/api/method/login", { data: { usr: "Administrator", pwd: ADMIN_PASSWORD } })
  expect(login.ok(), "login Administrator").toBeTruthy()
  link = await api<Link>(admin, "kamra.tex.api.payments.create_link", {
    property: HOTEL,
    amount: "12.50",
    currency: "EUR",
    description: `E2E pay link ${uniqueRunId()}`,
    expires_hours: 2,
  })
})

test.afterAll(async () => {
  if (link) await api(admin, "kamra.tex.api.payments.cancel_link", { name: link.link, reason: "e2e clean-up" })
  await admin.dispose()
})

test("a new link carries its token in the fragment only", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  expect(link.url).toContain(`/pay#token=${link.token}`)
  expect(new URL(link.url).pathname).not.toContain(link.token)
  const seen = watchRequests(page)
  const doc = page.waitForResponse((r) => new URL(r.url()).pathname.endsWith("/pay"))
  await page.goto(link.url)
  expect((await doc).headers()["referrer-policy"]).toContain("no-referrer")
  await expect(page.getByRole("heading", { name: "Payment request" })).toBeVisible()
  await expect(page.getByText("12.50").first()).toBeVisible()
  // the token has left the address bar; the page still knows it (a reload keeps working)
  expect(new URL(page.url()).hash).toBe("")
  expect(new URL(page.url()).pathname).toMatch(/\/pay$/)
  expect(await page.locator('meta[name="referrer"]').getAttribute("content")).toBe("no-referrer")
  await page.reload()
  await expect(page.getByRole("heading", { name: "Payment request" })).toBeVisible()
  expectTokenNowhere(seen.slice(1), link.token)             // the page's own requests (the first is the link)
  noErrors()
})

test("an old /book/pay/<token> link opens the same page and moves the token out of the path", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  const old = new URL(link.url)
  old.pathname = `${old.pathname}/${link.token}`
  old.hash = ""
  const seen = watchRequests(page)
  await page.goto(old.toString())
  await expect(page.getByRole("heading", { name: "Payment request" })).toBeVisible()
  const now = new URL(page.url())
  expect(now.pathname).toMatch(/\/pay$/)
  expect(now.pathname + now.search + now.hash).not.toContain(link.token)
  // the first request is the old link itself; nothing after it repeats the token
  expect(seen[0].url).toContain(link.token)
  expectTokenNowhere(seen.slice(1), link.token)
  noErrors()
})
