import { expect, test } from "@playwright/test"
import { ADMIN_PASSWORD, login, pageApi, texPath, trackErrors, uniqueRunId } from "./helpers"
import {
  addBoard,
  addOccupancyRules,
  addPeriod,
  addRooms,
  changeContractRate,
  createContract,
  createMarket,
  isoDate,
  openDraft,
  publishVersion,
  retireE2EMarkets,
  setBaseRate,
} from "./flows/contracts"
import { addExtra, fillGuest, guestSearch, payWithSandbox, pickRoom, readConfirmation } from "./flows/booking"
import { applyChange, openReservation, proposeChange, readLockedPrice, readRevisions } from "./flows/reservations"

// R-58 critical journey, through the UI end to end:
//  (1) enterprise/hotel exists (2) admin creates a market (3) contract (4) price period
//  (5) base per-person rate (6) adult/child formulas (7) publish
//  (8) guest searches (9) correct availability (10) correct price (11) selects the room
//  (12) adds an extra (13) pays with the sandbox provider (14) booking confirmed
//  (15) admin changes the contract (16) the existing reservation keeps its price
//  (17) dates are modified (18) the proposed difference is correct (19) revision recorded.
// Every price asserted comes from the server; the test only compares decimal strings.
// Codes are unique per run, so the journey can run repeatedly on the same bench.

const HOTEL = "Aurora Beach Resort"
const ROOM = "Standard Sea View"
const ROOM_ID = `${HOTEL}-STD`
const COUNTRIES = ["MT"]
const PARTY = { adults: 2, children: [8] }

test.use({ locale: "en-US" })

/** exact decimal-string arithmetic in cents (money never becomes a float) */
const cents = (a: string) => {
  const neg = a.startsWith("-")
  const [w, f = ""] = a.replace(/^[-+]/, "").split(".")
  const v = BigInt(w + (f + "00").slice(0, 2))
  return neg ? -v : v
}

interface PreviewDict {
  sellable?: boolean
  reasons?: { message: string }[]
  totals?: { total: string }
}

test("R-58 critical journey: contract → guest booking → contract change → modification → revision", async ({ page }) => {
  test.setTimeout(420_000)
  const noErrors = trackErrors(page)
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex-lang", "en")
    } catch {
      /* English is the default */
    }
  })
  const run = uniqueRunId()
  const market = `E2E_${run}`
  const code = `E2E-J-${run}`
  const season = { code: "SEASON", name: "Journey season", from: isoDate(7), to: isoDate(400) }
  // far out and spread per run: other suites and demo data book the nearer months
  const offset = 200 + (Number.parseInt(run.slice(-3), 36) % 150)
  const checkIn = isoDate(offset)
  const checkOut = isoDate(offset + 3)
  const newCheckOut = isoDate(offset + 4)
  let contract = ""
  let v1 = ""
  let v2 = ""
  let bookingTotal = ""
  let bookingRef = ""

  const preview = async (version: string, out: string) => {
    const r = await pageApi<PreviewDict>(page, "kamra.tex.api.contracts.preview_price", {
      version,
      room_type: ROOM_ID,
      board: "BB",
      check_in: checkIn,
      check_out: out,
      adults: PARTY.adults,
      children: PARTY.children,
      market,
      channel: "DIRECT_WEB",
    })
    expect(r.ok, JSON.stringify(r.body).slice(0, 300)).toBeTruthy()
    expect(r.message.sellable, JSON.stringify(r.message.reasons)).toBeTruthy()
    return r.message.totals!.total
  }

  await test.step("(1) the enterprise and the hotel exist and are in the admin's scope", async () => {
    await login(page, "Administrator", ADMIN_PASSWORD)
    const boot = await pageApi<{ properties: { name: string; enterprise: string | null; hotel_group: string | null }[] }>(
      page,
      "kamra.tex.api.session.bootstrap",
    )
    const hotel = boot.message.properties.find((p) => p.name === HOTEL)
    expect(hotel, `${HOTEL} in scope`).toBeTruthy()
    expect(hotel!.enterprise).toBeTruthy()
    expect(hotel!.hotel_group).toBeTruthy()
  })

  await test.step("(2) platform admin creates the market", async () => {
    await retireE2EMarkets(page, COUNTRIES)
    await createMarket(page, { code: market, name: `Journey ${run}`, countries: COUNTRIES, currency: "EUR" })
  })

  await test.step("(3–6) revenue manager: contract, period, base per-person rate, adult/child formulas", async () => {
    await login(page, "revenue@demo.tex")
    contract = await createContract(page, {
      hotel: HOTEL,
      code,
      market,
      currency: "EUR",
      basis: "PERSON",
      saleFrom: isoDate(0),
      stayFrom: season.from,
      stayTo: season.to,
    })
    v1 = await openDraft(page, contract)
    await addRooms(page, [{ room: ROOM, base: true }])
    await addPeriod(page, season)
    await setBaseRate(page, { room: ROOM, period: season.code, amount: "100" })
    await addOccupancyRules(page, {
      thirdAdultPercent: "70",
      bands: [
        { code: "INF", label: "Infant", fromAge: "0", toAge: "2", infant: true, percent: "0" },
        { code: "CHD", label: "Child", fromAge: "2", toAge: "12", percent: "50" },
      ],
    })
    await addBoard(page, { board: "HB", adultAmount: "25", childPercent: "50", infantFree: true })
  })

  await test.step("(7) publish: the version is frozen", async () => {
    expect(await publishVersion(page, `Journey ${run}`)).toBe(v1)
  })

  const expectedV1 = await test.step("server price of the guest's stay on V1 (direct web, this market)", async () => preview(v1, checkOut))

  await test.step("(8–11) guest searches the campaign link, sees the room at the server price and selects it", async () => {
    await page.context().clearCookies()
    const found = await guestSearch(page, { checkIn, checkOut, rooms: [PARTY], hotel: HOTEL, market })
    expect(found.view).toBe("rooms")
    // (9) availability: the contracted room is on sale for these dates
    const ours = found.rates.filter((r) => r.room === ROOM && r.board === "Bed & breakfast")
    expect(ours.length, `${ROOM} with breakfast on offer`).toBeGreaterThan(0)
    // (10) the price the guest sees is the server's price for this contract, market and channel
    expect(ours[0].amount).toBe(expectedV1)
    // (11) select it
    const chosen = await pickRoom(page, { roomName: ROOM, board: "Bed & breakfast" })
    expect(chosen.amount).toBe(expectedV1)
  })

  await test.step("(12–14) guest adds an extra, pays with the sandbox card and the booking is confirmed", async () => {
    await addExtra(page, { name: "Airport transfer", quantity: 1 })
    await fillGuest(page, {
      firstName: "Journey",
      lastName: `Guest ${run}`,
      email: `journey.${run.toLowerCase()}@example.com`,
      phone: "+356 2100 0000",
      country: "MT",
    })
    const paid = await payWithSandbox(page, "success")
    expect(paid.transaction).not.toBe("")
    const done = await readConfirmation(page)
    expect(done.status).toBe("Confirmed")
    expect(done.booking).toMatch(/^TEX-/)
    // the stay plus the extra: more than the room alone
    expect(cents(done.amount) > cents(expectedV1)).toBeTruthy()
    bookingRef = done.booking
    bookingTotal = done.amount
  })

  await test.step("(15) revenue manager raises the contract rate through a new version", async () => {
    await login(page, "revenue@demo.tex")
    v2 = await changeContractRate(page, { contract, room: ROOM, period: season.code, newRate: "120" })
    expect(v2).toMatch(/-V2$/)
    // the same stay now costs more on the version that is selling
    expect(cents(await preview(v2, checkOut)) > cents(expectedV1)).toBeTruthy()
  })

  await test.step("(16) the existing reservation keeps its locked price", async () => {
    await page.goto(texPath("/tex/reservations"))
    await openReservation(page, { booking: bookingRef })
    const locked = await readLockedPrice(page)
    expect(locked.amount).toBe(bookingTotal)
  })

  await test.step("(17–18) one more night: the proposal on the original terms and on current terms differ by exactly the rate change", async () => {
    const onOriginal = await proposeChange(page, { checkOut: newCheckOut, basis: "ORIGINAL_VERSION" })
    expect(onOriginal.old.amount).toBe(bookingTotal)
    // the difference shown is the proposed total minus the locked one
    expect(cents(onOriginal.difference.amount!)).toBe(cents(onOriginal.proposed.amount!) - cents(onOriginal.old.amount!))

    const onCurrent = await proposeChange(page, { checkOut: newCheckOut, basis: "CURRENT" })
    expect(onCurrent.old.amount).toBe(bookingTotal)
    expect(cents(onCurrent.difference.amount!)).toBe(cents(onCurrent.proposed.amount!) - cents(onCurrent.old.amount!))
    // same stay, same extra: the gap between the two bases is the gap between V2 and V1 for the new stay
    const v1Stay = await preview(v1, newCheckOut)
    const v2Stay = await preview(v2, newCheckOut)
    expect(cents(onCurrent.proposed.amount!) - cents(onOriginal.proposed.amount!)).toBe(cents(v2Stay) - cents(v1Stay))
    // nothing changed until applied
    expect((await readLockedPrice(page)).amount).toBe(bookingTotal)

    const applied = await applyChange(page, `Journey ${run}: guest stays one more night`)
    expect(applied.old_total).toBe(bookingTotal)
    expect(applied.new_total).toBe(onCurrent.proposed.amount)
    expect((await readLockedPrice(page)).amount).toBe(onCurrent.proposed.amount)
  })

  await test.step("(19) the revision history records the change", async () => {
    const revisions = await readRevisions(page)
    expect(revisions[0]).toMatchObject({ oldAmount: bookingTotal })
    expect(revisions[0].text).toContain(`Journey ${run}: guest stays one more night`)
    expect(revisions.at(-1)?.changeType).toBe("Original")
  })

  noErrors()
})
