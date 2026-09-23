// G-69 (ADR-039): channel distribution from the staff screens, end to end on the sandbox
// channel manager — no real channel is reached (real providers are blocked on
// certification). A hotel admin creates a sandbox channel connection with a secret in
// Connect → Connections, opens it under Channels, maps a channel room/rate to a demo room
// type, previews ARI (days with TEX's prices), queues and sends it, simulates a channel
// booking, applies it and finds it Applied in the inbound log, then runs reconciliation.
// Codes, the connection label and the booking id are unique per run. At the end the
// channel booking is cancelled through the sandbox, the mapping deleted and the
// connection disabled (a connection with history cannot be deleted), even when a step fails.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e channels
import { expect, test, type Locator, type Page } from "@playwright/test"
import { byLabel, esc, login, pageApi, stayDates, texPath, trackErrors, uniqueRunId } from "./helpers"

const HOTEL_ADMIN = "beach.gm@demo.tex"
/** Demo data at Aurora Beach Resort: the DE contract sells the base room with breakfast
 * and the Flexible rate plan; OTA is the channel-manager sales channel. */
const SOLD_AS = { roomType: "Standard Sea View", board: "BB", ratePlan: "Flexible", market: "DE", channel: "OTA", currency: "EUR" }

test.use({ locale: "en-US" })

async function english(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex-lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
}

/** The detail page's tab panel (one at a time). */
const panel = (page: Page) => page.getByRole("tabpanel")

async function openTab(page: Page, name: string) {
  await page.getByRole("tablist", { name: "Channel connection sections" }).getByRole("tab", { name: new RegExp(`^${esc(name)}`) }).click()
  await expect(page.getByRole("tab", { name: new RegExp(`^${esc(name)}`) })).toHaveAttribute("aria-selected", "true")
}

/** A toast with this text (success toasts are status regions). */
const toast = (page: Page, text: string | RegExp) => page.getByRole("status").filter({ hasText: text }).last()

async function fillMapping(dialog: Locator, codes: { room: string; rate: string }) {
  await byLabel(dialog, "Channel room code").fill(codes.room)
  await byLabel(dialog, "Channel rate code").fill(codes.rate)
  await byLabel(dialog, "Room type").selectOption({ label: SOLD_AS.roomType })
  await byLabel(dialog, "Board").selectOption(SOLD_AS.board)
  await byLabel(dialog, "Rate plan").selectOption({ label: SOLD_AS.ratePlan })
  await byLabel(dialog, "Market").selectOption(SOLD_AS.market)
  await byLabel(dialog, "Sales channel").selectOption(SOLD_AS.channel)
  await byLabel(dialog, "Currency").selectOption(SOLD_AS.currency)
  await byLabel(dialog, "Adults priced").fill("1,2")
  await byLabel(dialog, "Days ahead").fill("30")
}

test("channel distribution: sandbox connection, mapping, ARI push, a channel booking applied, reconciliation", async ({ page }) => {
  test.setTimeout(240_000)
  const noErrors = trackErrors(page)
  const run = uniqueRunId()
  const label = `E2E channel ${run}`
  const codes = { room: `R${run}`, rate: `BAR${run}` }
  const ref = `SBX-E2E-${run}`
  const stay = stayDates(30, 2)
  let connection = ""
  let mappingDeleted = false
  let booked = false

  await english(page)
  await login(page, HOTEL_ADMIN)
  await page.goto(texPath("/tex/connect"))

  try {
    await test.step("Connections: a sandbox channel connection with a secret", async () => {
      await page.getByRole("button", { name: "New connection" }).first().click()
      const drawer = page.getByRole("dialog", { name: "New connection" })
      await expect(drawer).toBeVisible()
      await byLabel(drawer, "Name").fill(label)
      await byLabel(drawer, "Category").selectOption("Channel Manager")
      await expect(byLabel(drawer, "Adapter")).toHaveValue("sandbox_channel")
      await byLabel(drawer, "Secret").fill(`e2e-secret-${run}`)
      await drawer.getByRole("button", { name: "Save", exact: true }).click()
      await expect(toast(page, "Saved")).toBeVisible()
      const saved = page.getByRole("dialog", { name: label })
      await expect(saved).toBeVisible()
      await saved.getByRole("button", { name: "Close" }).click()
      await expect(saved).toBeHidden()
    })

    await test.step("Channels lists it with the certification warning and its webhook", async () => {
      await page.getByRole("navigation", { name: "Connect sections" }).getByRole("link", { name: "Channels" }).click()
      await expect(page).toHaveURL(/\/tex\/connect\/channels$/)
      const title = page.getByRole("link", { name: label, exact: true })
      await expect(title).toBeVisible()
      await expect(page.getByText("Certification blocked — sandbox only").first()).toBeVisible()
      await title.click()
      await expect(page).toHaveURL(/\/tex\/connect\/channels\/[^/?]+/)
      connection = decodeURIComponent(new URL(page.url()).pathname.split("/").pop() ?? "")
      expect(connection).not.toBe("")
      await expect(page.getByRole("heading", { level: 1, name: label })).toBeVisible()
      await expect(page.getByText(`kamra.tex.api.distribution.webhook?connection=${connection}`)).toBeVisible()
      await expect(page.getByText("Not certified", { exact: true })).toBeVisible()
    })

    await test.step("Mappings: the channel room/rate sells the demo room with breakfast", async () => {
      await expect(panel(page).getByText("No mappings yet")).toBeVisible()
      await panel(page).getByRole("button", { name: "Add mapping" }).first().click()
      const dialog = page.getByRole("dialog", { name: "Add mapping" })
      await fillMapping(dialog, codes)
      await dialog.getByRole("button", { name: "Save", exact: true }).click()
      await expect(dialog).toBeHidden()
      await expect(toast(page, "Mapping saved.")).toBeVisible()
      const row = panel(page).getByRole("row").filter({ hasText: `${codes.room} / ${codes.rate}` })
      await expect(row).toBeVisible()
      await expect(row).toContainText(SOLD_AS.roomType)
      await expect(row.getByText("Enabled", { exact: true })).toBeVisible()
      // the same code pair cannot be mapped twice on one connection (server-side check)
      await panel(page).getByRole("button", { name: "Add mapping" }).first().click()
      const again = page.getByRole("dialog", { name: "Add mapping" })
      await fillMapping(again, codes)
      await again.getByRole("button", { name: "Save", exact: true }).click()
      await expect(again.getByRole("alert").filter({ hasText: "already mapped" })).toBeVisible()
      await again.getByRole("button", { name: "Cancel" }).click()
      await expect(again).toBeHidden()
    })

    await test.step("ARI preview: days with TEX's prices; queue and send them to the sandbox", async () => {
      await openTab(page, "ARI preview")
      await expect(byLabel(panel(page), "Mapping")).toHaveValue(/.+/)
      await panel(page).getByRole("radio", { name: "7 days" }).click()
      const table = panel(page).getByRole("table", { name: `Availability, restrictions and prices for ${codes.room} / ${codes.rate}` })
      await expect(table.getByRole("row")).toHaveCount(8) // header + 7 days
      // prices come from the server as strings and are only formatted (never recomputed)
      await expect(table.getByText(/€\d/).first()).toBeVisible()
      await expect(table.getByText("2 adults", { exact: true }).first()).toBeVisible()

      await panel(page).getByRole("button", { name: "Queue changes" }).click()
      await expect(toast(page, /^Changes queued for \d+ mappings?\.$/)).toBeVisible()
      // Send now pushes this connection's due jobs; a job the scheduler holds at that moment
      // is sent by it instead, so send again until the channel has every previewed day
      await expect(async () => {
        await panel(page).getByRole("button", { name: "Send now" }).click()
        await expect(toast(page, /^Sent \d+ · failed 0 · still waiting \d+$/)).toBeVisible({ timeout: 5_000 })
        await expect(table.getByRole("cell", { name: "Never sent", exact: true })).toHaveCount(0, { timeout: 5_000 })
      }).toPass({ timeout: 60_000 })
      await expect(table.getByRole("cell", { name: "In sync", exact: true })).toHaveCount(7)
    })

    await test.step("Sandbox: a simulated channel booking is received and applied", async () => {
      await openTab(page, "Sandbox")
      const form = page.getByRole("form", { name: "Simulated channel booking" })
      await expect(page.getByText("Simulation — no real channel")).toBeVisible()
      await byLabel(form, "Channel booking ID").fill(ref)
      await expect(form.getByRole("radio", { name: "New" })).toHaveAttribute("aria-checked", "true")
      await byLabel(form, "First name").fill("E2E")
      await byLabel(form, "Last name").fill(`Channel ${run}`)
      const room = form.getByRole("group", { name: "Room 1" })
      // the first mapping's codes and currency are proposed
      await expect(byLabel(room, "Room code")).toHaveValue(codes.room)
      await expect(byLabel(room, "Rate code")).toHaveValue(codes.rate)
      await expect(byLabel(room, "Currency")).toHaveValue(SOLD_AS.currency)
      await byLabel(room, "Check-in").fill(stay.checkIn)
      await byLabel(room, "Check-out").fill(stay.checkOut)
      await byLabel(room, "Adults").fill("2")
      await byLabel(room, "Total for the stay").fill("450.00")
      await form.getByRole("button", { name: "Send to TEX" }).click()
      await expect(page.getByText("Received 1 · duplicates 0")).toBeVisible()
      booked = true
      // sending the same message again is a duplicate, not a second booking
      await form.getByRole("button", { name: "Send to TEX" }).click()
      await expect(page.getByText("Received 0 · duplicates 1")).toBeVisible()

      await panel(page).getByRole("button", { name: "Apply received now" }).click()
      await expect(toast(page, /^Applied \d+ · failed 0$/)).toBeVisible()
      await expect(page.getByRole("tab", { name: /^Bookings from the channel/ })).toHaveAttribute("aria-selected", "true")
    })

    await test.step("Bookings from the channel: the message is Applied and links to the TEX booking", async () => {
      const row = panel(page).getByRole("row").filter({ hasText: ref })
      // the queue may apply it a moment later than the button: refresh until it shows
      await expect(async () => {
        await panel(page).getByRole("button", { name: "Refresh" }).click()
        await expect(row.getByText("Applied", { exact: true })).toBeVisible({ timeout: 2_000 })
      }).toPass({ timeout: 60_000 })
      await expect(row).toContainText(`${codes.room} / ${codes.rate}`)
      await expect(row.getByText("New", { exact: true })).toBeVisible()
      await expect(row).toContainText("€450.00")
      await expect(row.getByRole("link").first()).toHaveAttribute("href", /\/tex\/reservations\/booking\//)
      // filter by status
      await panel(page).getByRole("radio", { name: "Applied" }).click()
      await expect(row).toBeVisible()
      await panel(page).getByRole("radio", { name: "Dead" }).click()
      await expect(row).toHaveCount(0)
      await panel(page).getByRole("radio", { name: "All" }).click()
      await expect(row).toBeVisible()
    })

    await test.step("Reconciliation runs and does not report the booking missing in TEX", async () => {
      await openTab(page, "Reconciliation")
      await panel(page).getByRole("button", { name: "Run reconciliation" }).click()
      await expect(panel(page).getByText(/^(No differences found|\d+ differences? found)/)).toBeVisible()
      await expect(panel(page).getByRole("region", { name: "Missing in TEX" }).getByText(ref)).toHaveCount(0)
      await expect(panel(page).getByRole("button", { name: "Run again" })).toBeVisible()
    })

    await test.step("the channel cancels the booking; the mapping is deleted", async () => {
      const cancelled = await pageApi<{ received: number }>(page, "kamra.tex.api.distribution.sandbox_send", {
        connection,
        message: { provider_ref: ref, status: "cancelled", channel_name: "Sandbox OTA", rooms: [] },
      })
      expect(cancelled.ok, JSON.stringify(cancelled.body).slice(0, 300)).toBeTruthy()
      expect((await pageApi(page, "kamra.tex.api.distribution.apply_now", { connection })).ok).toBeTruthy()
      booked = false

      await openTab(page, "Mappings")
      await panel(page).getByRole("button", { name: `Delete mapping ${codes.room} / ${codes.rate}` }).click()
      const confirm = page.getByRole("dialog", { name: "Delete this mapping?" })
      await confirm.getByRole("button", { name: "Delete" }).click()
      await expect(confirm).toBeHidden()
      await expect(toast(page, "Mapping deleted.")).toBeVisible()
      await expect(panel(page).getByText("No mappings yet")).toBeVisible()
      mappingDeleted = true
    })
  } finally {
    // leave nothing selling or receiving: cancel the booking, drop the mapping, switch the connection off
    if (connection) {
      if (booked) {
        await pageApi(page, "kamra.tex.api.distribution.sandbox_send", {
          connection,
          message: { provider_ref: ref, status: "cancelled", channel_name: "Sandbox OTA", rooms: [] },
        }).catch(() => undefined)
        await pageApi(page, "kamra.tex.api.distribution.apply_now", { connection }).catch(() => undefined)
      }
      if (!mappingDeleted) {
        const maps = await pageApi<{ name: string }[]>(page, "kamra.tex.api.distribution.mappings", { connection }).catch(() => undefined)
        for (const m of maps?.message ?? []) await pageApi(page, "kamra.tex.api.distribution.delete_mapping", { name: m.name }).catch(() => undefined)
      }
      const off = await pageApi(page, "kamra.tex.api.policies.save_record", {
        doctype: "TEX Integration Connection",
        data: { name: connection, enabled: 0 },
      })
      expect(off.ok, `disable ${connection}: ${JSON.stringify(off.body).slice(0, 300)}`).toBeTruthy()
    }
  }

  noErrors()
})
