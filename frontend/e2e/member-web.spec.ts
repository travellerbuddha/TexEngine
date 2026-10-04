// C-04 on the web (owner, 2026-10-03; ADR-078): a loyalty member signs in on the booking site by a one-time e-mail
// link and books the member price; anyone else sees it as "Member price", applied only signed in.
// The revenue manager runs a loyalty program at Aurora Beach Resort (this run's, or one already enabled there) and
// puts a members-only promotion live. A guest searches the site: the header offers "Member sign-in" and the rates
// show "Member price: …". From a rate they join on the dialog (e-mail, name and the tick); the link of the mail (read
// from the server's mail queue) opens the member page, where "Continue" signs them in and brings them back to their
// search, priced as a member: "Your member price", no teaser. On the platform's shared host the session is kept in the
// tab only, never on the device (owner, review round 1). The details step is filled in from the membership, and the
// e-mail a member's price is booked under cannot be changed; the booking is made. The link is spent: opened again in
// this tab it goes back to the search (signed in already), in another browser it asks for a new one. Signing out
// forgets the session and the teaser is back. Mail reaches the queue only with an outgoing account: without one (a
// bench as CI sets it up) the run turns on an outbox of its own that sends nothing (an SMTP host that does not
// resolve, and the site's scheduler, which would flush the queue, is off), and puts the accounts back as they were.
// Clean-up: the stay is cancelled, the promotion archived and a program this run created disabled.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… TEX_E2E_ADMIN_PASSWORD=… npx playwright test -c e2e member-web
import { expect, request as pwRequest, test, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test"
import { ADMIN_PASSWORD, login, pageApi, stayDates, texPath, trackErrors, uniqueRunId } from "./helpers"
import { bookPayAtHotel, guestSearch, nextStep, payWithSandbox } from "./flows/booking"

test.use({ locale: "en-US" })

const BASE = process.env.TEX_E2E_BASE || "http://test.localhost:8000"
const SLUG = "aurora"
const HOTEL = "Aurora Beach Resort"
const REVENUE = "revenue@demo.tex"
const AGENT = "agent@demo.tex"

interface Program {
  name: string
  property: string | null
  enabled: number
}

/** A logged-in staff page in its own browser context. */
async function staff(browser: Browser, user: string, opened: BrowserContext[]): Promise<Page> {
  const ctx = await browser.newContext({ locale: "en-US", baseURL: test.info().project.use.baseURL })
  opened.push(ctx)
  const page = await ctx.newPage()
  await login(page, user)
  await page.goto(texPath("/tex/crm"))
  return page
}

/** Administrator API context: the server's mail queue. */
async function admin(): Promise<APIRequestContext> {
  const ctx = await pwRequest.newContext({ baseURL: BASE })
  const r = await ctx.post("/api/method/login", { data: { usr: "Administrator", pwd: ADMIN_PASSWORD } })
  expect(r.ok(), "login Administrator").toBeTruthy()
  return ctx
}

const OUTBOX = "TEX E2E outbox"

/** An outgoing account, so that mail reaches the queue: null when the bench has one already, else the accounts
 * that were the default (disabled ones: Frappe takes the flag from them when ours becomes the default) to put back. */
async function outboxOn(ctx: APIRequestContext): Promise<string[] | null> {
  const list = async (filters: unknown[]) => {
    const r = await ctx.get("/api/method/frappe.client.get_list", {
      params: { doctype: "Email Account", fields: JSON.stringify(["name"]), filters: JSON.stringify(filters), limit_page_length: "20" },
    })
    expect(r.ok(), "list Email Account").toBeTruthy()
    return ((await r.json()) as { message: { name: string }[] }).message.map((a) => a.name)
  }
  if ((await list([["enable_outgoing", "=", 1], ["default_outgoing", "=", 1]])).length) return null
  const defaults = (await list([["default_outgoing", "=", 1]])).filter((n) => n !== OUTBOX)
  const on = { enable_outgoing: 1, default_outgoing: 1, smtp_server: "smtp.invalid", smtp_port: 25, no_smtp_authentication: 1, awaiting_password: 0 }
  const r = (await list([["name", "=", OUTBOX]])).length
    ? await ctx.post("/api/method/frappe.client.set_value", { data: { doctype: "Email Account", name: OUTBOX, fieldname: on } })
    : await ctx.post("/api/method/frappe.client.insert", {
        data: { doc: { doctype: "Email Account", email_account_name: OUTBOX, email_id: "tex-e2e-outbox@example.com", enable_incoming: 0, ...on } },
      })
  expect(r.ok(), `outbox: ${(await r.text()).slice(0, 300)}`).toBeTruthy()
  return defaults
}

async function outboxOff(ctx: APIRequestContext, defaults: string[]) {
  const r = await ctx.post("/api/method/frappe.client.set_value", {
    data: { doctype: "Email Account", name: OUTBOX, fieldname: { enable_outgoing: 0, default_outgoing: 0 } },
  })
  expect(r.ok(), `outbox off: ${(await r.text()).slice(0, 300)}`).toBeTruthy()
  for (const name of defaults) {
    const back = await ctx.post("/api/method/frappe.client.set_value", { data: { doctype: "Email Account", name, fieldname: "default_outgoing", value: 1 } })
    expect(back.ok(), `default back on ${name}`).toBeTruthy()
  }
}

/** A mail's text as sent: quoted-printable soft breaks and escapes undone, base64 parts decoded. */
function mailText(raw: string): string {
  const qp = raw.replace(/=\r?\n/g, "").replace(/=([0-9A-F]{2})/g, (_, h: string) => String.fromCharCode(parseInt(h, 16)))
  const b64 = [...raw.matchAll(/Content-Transfer-Encoding: base64\r?\n(?:[^\r\n]+\r?\n)*\r?\n([A-Za-z0-9+/=\r\n]+)/g)]
    .map((m) => Buffer.from(m[1].replace(/\s+/g, ""), "base64").toString("utf8"))
    .join("\n")
  return `${qp}\n${b64}`
}

/** The token of the newest member link mailed to this address. */
async function mailedToken(adminCtx: APIRequestContext, email: string): Promise<string> {
  let token: string | null = null
  await expect
    .poll(
      async () => {
        const r = await adminCtx.get("/api/method/frappe.client.get_list", {
          params: {
            doctype: "Email Queue",
            fields: JSON.stringify(["name", "message"]),
            filters: JSON.stringify([["Email Queue Recipient", "recipient", "=", email]]),
            order_by: "creation desc",
            limit_page_length: "1",
          },
        })
        const rows = ((await r.json()) as { message?: { message?: string }[] }).message ?? []
        const text = rows[0]?.message ? mailText(rows[0].message) : ""
        token = /\/member#token=([A-Za-z0-9_-]{20,})/.exec(text)?.[1] ?? null
        return token
      },
      { timeout: 20_000, message: `a member link mailed to ${email}` },
    )
    .not.toBeNull()
  return token!
}

const opened: BrowserContext[] = []
test.afterEach(async () => {
  for (const c of opened.splice(0)) await c.close()
})

test("a guest joins on the site, signs in by the mailed link, books the member price and signs out", async ({ browser }) => {
  test.setTimeout(240_000)
  const run = uniqueRunId()
  const email = `nora.${run.toLowerCase()}@example.com`
  const revenue = await staff(browser, REVENUE, opened)

  // the hotel's program: one enabled at Aurora already (an earlier run's), or this run's
  const listed = await pageApi<{ programs: Program[] }>(revenue, "kamra.tex.api.loyalty.programs")
  expect(listed.ok, JSON.stringify(listed.body).slice(0, 300)).toBeTruthy()
  let program = listed.message.programs.find((p) => p.property === HOTEL && p.enabled)?.name
  let created = false
  if (!program) {
    const saved = await pageApi<{ name: string }>(revenue, "kamra.tex.api.loyalty.save_program", {
      data: {
        program_name: `E2E web members ${run}`,
        property: HOTEL,
        enabled: 1,
        currency: "EUR",
        point_value: "0.1",
        min_redeem_points: 50,
        max_redeem_percent: "50",
        pending_days: 0,
        expiry_months: 24,
        earn_rules: [{ basis: "STAY", rate: "25" }],
        tiers: [{ tier_name: "Silver", min_points: 0, earn_multiplier: "1" }],
        blackouts: [],
      },
    })
    expect(saved.ok, JSON.stringify(saved.body).slice(0, 300)).toBeTruthy()
    program = saved.message.name
    created = true
  }
  const promo = await pageApi<{ name: string }>(revenue, "kamra.tex.api.policies.save_record", {
    doctype: "TEX Promotion",
    data: {
      promotion_name: `E2E web members 10 ${run}`,
      property: HOTEL,
      trigger: "Automatic",
      value_type: "PERCENT",
      value: 10,
      applies_to: "ACCOMMODATION",
      member_only: 1,
    },
  })
  expect(promo.ok, JSON.stringify(promo.body).slice(0, 300)).toBeTruthy()

  const guestCtx = await browser.newContext({ locale: "en-US", baseURL: test.info().project.use.baseURL, viewport: { width: 1280, height: 900 } })
  opened.push(guestCtx)
  const page = await guestCtx.newPage()
  const noErrors = trackErrors(page)
  const mail = await admin()
  let outbox: string[] | null = null
  let reservation: string | null = null
  try {
    const live = await pageApi(revenue, "kamra.tex.api.policies.activate", { doctype: "TEX Promotion", name: promo.message.name })
    expect(live.ok, JSON.stringify(live.body).slice(0, 300)).toBeTruthy()
    outbox = await outboxOn(mail)
    const { checkIn, checkOut } = stayDates(150, 3)
    const header = page.getByRole("banner")
    const teaser = page.getByText(/^Member price: /)

    await test.step("anyone sees the member price as a teaser, and joins from a rate", async () => {
      await guestSearch(page, { checkIn, checkOut, rooms: [{ adults: 2 }], hotel: HOTEL })
      await expect(header.getByRole("button", { name: "Member sign-in" })).toBeVisible()
      await expect(teaser.first()).toBeVisible()
      await expect(page.getByText("Your member price")).toHaveCount(0)
      await page.getByRole("button", { name: "Sign in or join to get it" }).first().click()
      const dialog = page.getByRole("dialog", { name: "Member sign-in" })
      await expect(dialog).toBeVisible()
      await dialog.getByRole("tab", { name: "Join" }).click()
      const join = page.getByRole("dialog", { name: /^Join / })
      await join.getByLabel("Email", { exact: true }).fill(email)
      await join.getByLabel("First name", { exact: true }).fill("Nora")
      await join.getByLabel("Last name", { exact: true }).fill(`Web ${run}`)
      // the program's terms first
      await join.getByRole("button", { name: "Send me the link" }).click()
      await expect(join.getByRole("alert")).toBeVisible()
      await join.getByRole("checkbox", { name: /^I want to become a member of .+\./ }).check()
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("kamra.tex.api.public.member_link") && r.ok()),
        join.getByRole("button", { name: "Send me the link" }).click(),
      ])
      await expect(join.getByText("Check your e-mail")).toBeVisible()
      await expect(join).toContainText(email)
      await join.getByRole("button", { name: "Done" }).click()
      await expect(join).toBeHidden()
    })

    const token = await mailedToken(mail, email)

    await test.step("the mailed link signs the guest in and brings them back to their search, priced as a member", async () => {
      await page.goto(`/book/${SLUG}/member#token=${token}`)
      // the token leaves the address bar before the page asks for anything; the link is spent only by a click
      await expect(page.getByRole("button", { name: "Continue" })).toBeVisible()
      expect(new URL(page.url()).hash, "the token is gone from the address").toBe("")
      await page.getByRole("button", { name: "Continue" }).click()
      await page.waitForURL((u) => u.pathname === `/book/${SLUG}` && u.searchParams.get("checkin") === checkIn, { timeout: 30_000 })
      await expect(header.getByText("Hello, Nora")).toBeVisible()
      await expect(page.getByText("Your member price").first()).toBeVisible({ timeout: 30_000 })
      await expect(teaser).toHaveCount(0)
      // the platform's shared host: the session in this tab only, nothing of it on the device
      const kept = await page.evaluate((slug) => [sessionStorage.getItem(`tex.member.${slug}`), localStorage.getItem(`tex.member.${slug}`)], SLUG)
      expect(kept[0], "the session is kept in the tab").toContain('"expires"')
      expect(kept[0] ?? "").not.toContain(token)
      expect(kept[1], "nothing on the device").toBeNull()
    })

    await test.step("a member's price is booked under the member's e-mail", async () => {
      // a rate row (the innermost list item with a Select button) at a member's price; one the guest may pay at the
      // hotel when there is one, else by card on the sandbox
      const row = (extra = "") =>
        page.locator(
          `xpath=//li[.//*[normalize-space(text())="Your member price"] and .//button[starts-with(@aria-label,"Select: ")]${extra} and not(.//li[.//button[starts-with(@aria-label,"Select: ")]])]`,
        )
      const atHotel = (await row(' and .//*[normalize-space(text())="Pay at the hotel is possible"]').count()) > 0
      const rate = (atHotel ? row(' and .//*[normalize-space(text())="Pay at the hotel is possible"]') : row()).first()
      await rate.getByRole("button", { name: /^Select: / }).click()
      for (let i = 0; i < 3 && (await page.getByRole("heading", { level: 1 }).first().textContent())?.trim() !== "Your details"; i++) await nextStep(page)
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Your details")
      await expect(page.getByLabel("First name", { exact: true })).toHaveValue("Nora")
      await expect(page.getByLabel("Last name", { exact: true })).toHaveValue(`Web ${run}`)
      const mailField = page.getByLabel("Email", { exact: true })
      await expect(mailField).toHaveValue(email)
      await expect(mailField).toHaveAttribute("readonly", "")
      await expect(page.getByText("Your member price is booked under the e-mail you signed in with.")).toBeVisible()
      await page.getByLabel("Mobile phone", { exact: true }).fill(`+49 171 ${String(Date.now()).slice(-7)}`)
      const country = page.getByLabel(/^Country of residence/)
      if (await country.count()) await country.selectOption("DE")
      await page.getByRole("button", { name: "Continue to payment", exact: true }).filter({ visible: true }).first().click()
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Payment", { timeout: 30_000 })
      const [booked] = await Promise.all([
        page.waitForResponse((r) => new URL(r.url()).pathname.endsWith("/kamra.tex.api.public.book"), { timeout: 60_000 }),
        atHotel ? bookPayAtHotel(page) : payWithSandbox(page, "success"),
      ])
      const body = (await booked.json()) as { message?: { rooms?: { reservation: string }[] }; tex_code?: string }
      expect(body.tex_code, "no MEMBERS_ONLY refusal").toBeUndefined()
      reservation = body.message?.rooms?.[0]?.reservation ?? null
      expect(reservation).not.toBeNull()
      await page.waitForURL(/\/book\/[^/]+\/confirmation\//, { timeout: 30_000 })
    })

    await test.step("the link is spent: this tab goes back to the search, another browser asks for a new one", async () => {
      await page.goto(`/book/${SLUG}/member#token=${token}`)
      await page.getByRole("button", { name: "Continue" }).click()
      await page.waitForURL((u) => u.pathname === `/book/${SLUG}`, { timeout: 30_000 })
      const other = await browser.newContext({ locale: "en-US", baseURL: test.info().project.use.baseURL })
      opened.push(other)
      const elsewhere = await other.newPage()
      await elsewhere.goto(`/book/${SLUG}/member#token=${token}`)
      await elsewhere.getByRole("button", { name: "Continue" }).click()
      await expect(elsewhere.getByRole("heading", { name: "This link cannot be used" })).toBeVisible()
      await expect(elsewhere.getByRole("link", { name: "Ask for a new link" })).toBeVisible()
    })

    await test.step("signing out forgets the session here; the teaser is back", async () => {
      await guestSearch(page, { checkIn, checkOut, rooms: [{ adults: 2 }], hotel: HOTEL })
      await expect(header.getByText("Hello, Nora")).toBeVisible()
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("kamra.tex.api.public.member_sign_out")),
        header.getByRole("button", { name: "Sign out" }).click(),
      ])
      await expect(header.getByRole("button", { name: "Member sign-in" })).toBeVisible()
      await expect(teaser.first()).toBeVisible({ timeout: 30_000 })
      await expect(page.getByText("Your member price")).toHaveCount(0)
      expect(await page.evaluate((slug) => sessionStorage.getItem(`tex.member.${slug}`), SLUG)).toBeNull()
    })

    await test.step("staff see the guest's sign-in in CRM and sign them out there (batch 2O)", async () => {
      const asked = await pageApi(page, "kamra.tex.api.public.member_link", { site: SLUG, email, purpose: "sign_in" })
      expect(asked.ok, JSON.stringify(asked.body).slice(0, 300)).toBeTruthy()
      let fresh = token
      await expect.poll(async () => (fresh = await mailedToken(mail, email)), { timeout: 20_000 }).not.toBe(token)
      await page.goto(`/book/${SLUG}/member#token=${fresh}`)
      await page.getByRole("button", { name: "Continue" }).click()
      await page.waitForURL((u) => u.pathname === `/book/${SLUG}`, { timeout: 30_000 })
      await expect(header.getByText("Hello, Nora")).toBeVisible()

      const agent = await staff(browser, AGENT, opened)
      await agent.goto(texPath("/tex/crm"))
      const found = await pageApi<{ rows: { name: string }[] }>(agent, "kamra.tex.api.crm.guests", { q: email, limit: 5 })
      expect(found.ok, JSON.stringify(found.body).slice(0, 300)).toBeTruthy()
      await agent.goto(texPath(`/tex/crm/guests/${encodeURIComponent(found.message.rows[0].name)}`))
      await agent.getByRole("tab", { name: /^Loyalty/ }).click()
      const sessions = agent.getByRole("region", { name: "Signed in on the booking site" })
      await expect(sessions.getByRole("listitem")).toHaveCount(2)                 // the one signed out, and this one
      const signOut = sessions.getByRole("button", { name: "Sign out", exact: true })
      await expect(signOut).toHaveCount(1)
      await Promise.all([
        agent.waitForResponse((r) => r.url().includes("kamra.tex.api.crm.end_member_sessions") && r.ok()),
        signOut.click(),
      ])
      await expect(signOut).toHaveCount(0)
      await expect(sessions.getByText("Signed in", { exact: true })).toHaveCount(0)

      await page.reload()
      await expect(header.getByRole("button", { name: "Member sign-in" })).toBeVisible({ timeout: 30_000 })
      await expect(page.getByText("Your member price")).toHaveCount(0)
    })
    noErrors()
  } finally {
    if (outbox) await outboxOff(mail, outbox)
    await mail.dispose()
    if (reservation) {
      const agent = await staff(browser, AGENT, opened)
      await pageApi(agent, "kamra.tex.api.crs.cancel", { reservation, reason: "E2E clean-up (web membership)" })
    }
    await pageApi(revenue, "kamra.tex.api.policies.archive", { doctype: "TEX Promotion", name: promo.message.name, reason: "E2E clean-up (web membership)" })
    if (created) await pageApi(revenue, "kamra.tex.api.loyalty.set_enabled", { name: program, enabled: 0 })
  }
})
