// The workspace sends its opt-in flag (ADR-061, "Existing semantics kept, the workspace's additions
// opt-in"): every contract call whose answer it builds on carries workspace=1 — get_version when it
// opens a draft, price_matrix and validate_version as it prices and checks an unsaved edit,
// preview_price from the Price test, save_version on Save, validate_version and publish_version in the
// publish dialog. Without the flag the server answers as it did before the workspace (no board checks
// or issue refs, a blank value saved as 0, children read as whole years, no night subtotals, main's
// keys; `test_existing_semantics`). The draft is made through the API, as an existing caller would.
import { expect, test, type Page, type Request } from "@playwright/test"
import { login, trackErrors } from "./helpers"
import { previewPrice, publishVersion, saveDraft } from "./flows/contracts"
import { archiveAll, N, newDraft, openVersion, ownerDraft, Y } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const made: string[] = []
const FLAGGED = ["get_version", "price_matrix", "validate_version", "preview_price", "save_version", "publish_version"]

/** Each contracts call the page makes: its method, whether it was a POST, and its workspace flag. */
function watch(page: Page) {
  const seen: { m: string; post: boolean; flag: string | null }[] = []
  page.on("request", (r: Request) => {
    const m = /kamra\.tex\.api\.contracts\.(\w+)/.exec(r.url())
    if (!m) return
    const post = r.method() === "POST"
    const flag = post
      ? (r.postDataJSON() as Record<string, unknown> | null)?.workspace
      : new URL(r.url()).searchParams.get("workspace")
    seen.push({ m: m[1], post, flag: flag === undefined || flag === null ? null : String(flag) })
  })
  return seen
}

test.afterAll(async ({ browser }) => archiveAll(browser, made, "pricing workspace opt-in e2e clean-up"))

test("the workspace sends workspace=1 on every call whose answer it builds on: open, live price and check, Price test, Save, Publish", async ({ page }) => {
  const noErrors = trackErrors(page)
  await login(page, "revenue@demo.tex")
  const d = await newDraft(page, "E2E-PWO", ownerDraft())
  made.push(d.contract)
  const seen = watch(page)
  await openVersion(page, d)

  // an unsaved edit: the overlay prices it and the live check validates it
  const matrix = page.getByRole("grid", { name: "Room prices by period", exact: true })
  await matrix.getByRole("gridcell", { name: new RegExp(`^${N.DLX} · All periods: `) }).first().click()
  await page.keyboard.type("x1.4")
  await page.keyboard.press("Enter")
  await expect(page.getByText("Unsaved changes", { exact: true })).toBeVisible()
  await expect.poll(() => seen.filter((x) => x.m === "validate_version" && x.post).length, { timeout: 20_000 }).toBeGreaterThan(0)

  // the Price test (with a child's age), Save, then the publish dialog's check and Publish
  const q = await previewPrice(page, { room: N.DLX, board: "BB", checkIn: `${Y}-05-01`, checkOut: `${Y}-05-04`, adults: 2, children: [8] })
  expect(Number(q.total)).toBeGreaterThan(0)
  await saveDraft(page)
  await publishVersion(page, "E2E opt-in flag")

  for (const m of FLAGGED) expect(seen.some((x) => x.m === m), `${m} was called`).toBeTruthy()
  expect(seen.filter((x) => FLAGGED.includes(x.m) && x.flag !== "1"), "calls without the workspace flag").toEqual([])
  noErrors()
})
