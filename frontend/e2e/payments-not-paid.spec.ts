// §6K1 "Not done" (batch 2O): no e2e covered "Not paid (checked with the bank)" (LO-18). A payment of the bank TEX
// cannot ask for its outcome (the Virtual POS) stays Pending until staff check it in the bank's panel; finance marks
// it not paid with a reason, and it is closed Failed. The account is this run's own, used by no payment rule: only
// this run's payment link takes it, so no other spec's card payments change.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e payments-not-paid
import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test"
import { login, pageApi, texPath, trackErrors, uniqueRunId } from "./helpers"

test.use({ locale: "en-US" })

const HOTEL = "Aurora Beach Resort"
const ADMIN = "beach.gm@demo.tex" //    settings.admin at the hotel: the account and the link
const FINANCE = "finance@demo.tex" // payment.refund: the check with the bank

async function staff(browser: Browser, user: string, opened: BrowserContext[]): Promise<Page> {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "en-US", baseURL: test.info().project.use.baseURL })
  opened.push(ctx)
  const page = await ctx.newPage()
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex-lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
  await login(page, user)
  await page.goto(texPath("/tex/payments"))
  return page
}

const opened: BrowserContext[] = []
test.afterEach(async () => {
  for (const c of opened.splice(0)) await c.close()
})

test("finance marks a virtual POS payment not paid after checking it with the bank (LO-18)", async ({ browser, request }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "one layout is enough: the dialog is the same")
  test.setTimeout(120_000)
  const run = uniqueRunId()
  const admin = await staff(browser, ADMIN, opened)
  const account = await pageApi<{ name: string }>(admin, "kamra.tex.api.payments.save_account", {
    property: HOTEL,
    data: {
      label: `E2E virtual POS ${run}`,
      provider: "Virtual POS",
      bank_code: "NestPay",
      environment: "Sandbox",
      enabled: 1,
      terminal_id: `E2E${run}`,
      store_key: `e2e-store-${run}`,
    },
  })
  expect(account.ok, JSON.stringify(account.body).slice(0, 400)).toBeTruthy()
  let link: string | null = null
  try {
    const made = await pageApi<{ link: string; token: string }>(admin, "kamra.tex.api.payments.create_link", {
      property: HOTEL,
      amount: "12.00",
      currency: "EUR",
      description: `E2E not paid ${run}`,
      provider_account: account.message.name,
      idempotency_key: `e2e-not-paid-${run}`,
    })
    expect(made.ok, JSON.stringify(made.body).slice(0, 400)).toBeTruthy()
    link = made.message.link

    // the guest starts paying: TEX hands the browser the bank's 3D form; the bank never tells TEX the outcome
    const started = await request.post("/api/method/kamra.tex.api.public.pay_link", { data: { token: made.message.token } })
    const body = (await started.json()) as { message?: { transaction?: string; kind?: string; url?: string } }
    expect(started.ok(), JSON.stringify(body).slice(0, 400)).toBeTruthy()
    const txn = body.message?.transaction ?? ""
    expect(txn).not.toBe("")
    expect(body.message?.kind).toBe("form_post") //                    the bank's 3D page, in its sandbox
    expect(body.message?.url ?? "").toContain("asseco-see.com.tr")

    const finance = await staff(browser, FINANCE, opened)
    const noErrors = trackErrors(finance)
    await finance.goto(texPath(`/tex/payments/transactions/${encodeURIComponent(txn)}`))
    await expect(finance.getByRole("heading", { level: 1 })).toContainText(txn)
    await expect(finance.getByRole("button", { name: "Re-verify" })).toHaveCount(0) //  TEX cannot ask this bank
    await finance.getByRole("button", { name: "Not paid (checked with the bank)" }).click()
    const dialog = finance.getByRole("dialog", { name: "Mark as not paid" })
    await expect(dialog).toContainText("TEX cannot ask this bank")
    await expect(dialog).toContainText("12.00")
    const confirm = dialog.getByRole("button", { name: "Mark not paid" })
    await expect(confirm).toBeDisabled() //                                              a reason first
    await dialog.getByLabel("Reason").fill("Checked in the bank's panel: never charged (E2E)")
    await Promise.all([
      finance.waitForResponse((r) => r.url().includes("kamra.tex.api.payments.close_unpaid") && r.ok()),
      confirm.click(),
    ])
    await expect(dialog).toBeHidden()
    await expect(finance.getByText(`Payment ${txn} marked not paid`)).toBeVisible()
    await expect(finance.getByRole("button", { name: "Not paid (checked with the bank)" })).toHaveCount(0)
    const after = await pageApi<{ status: string; error_code?: string | null }>(finance, "kamra.tex.api.payments.transaction", { name: txn })
    expect(after.ok, JSON.stringify(after.body).slice(0, 400)).toBeTruthy()
    expect(after.message.status).toBe("Failed")
    noErrors()
  } finally {
    // an account is never deleted (its record is audited): this run's is disabled (CI's database is new each run)
    if (link) await pageApi(admin, "kamra.tex.api.payments.cancel_link", { name: link, reason: "E2E clean-up (not paid)" })
    if (account.message?.name)
      await pageApi(admin, "kamra.tex.api.payments.save_account", { property: HOTEL, data: { name: account.message.name, enabled: 0 } })
  }
})
