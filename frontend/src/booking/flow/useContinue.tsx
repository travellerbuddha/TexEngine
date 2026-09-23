// Moving forward through the flow (rooms → extras → details) and recovering from the
// server's "sold out", "no longer available" and "offer expired" answers by searching
// again for the same stay. A limited extra that runs out (G-19) never sends the guest
// back to the room search: the extras step says what could not be added.
import { useEffect, useRef } from "react"
import { useI18n } from "../i18n"
import { extraAnchor, refusalText } from "../lib/extras"
import { Button } from "../ui/controls"
import { Alert } from "../ui/feedback"
import { useBooking, type FlowError, type Step } from "./BookingContext"

export function useContinue() {
  const b = useBooking()

  const go = async (from: Step) => {
    b.setFlowError(null)
    if (from === "rooms" && b.hasExtras) return b.goStep("extras")
    // the booking refused this very choice of extras (the rooms together need more than is
    // left): going on would only be refused again. The message stays; a new object, so the
    // alert takes focus and scrolls into view again.
    if (from === "extras" && b.extrasClash) return b.setFlowError({ ...b.extrasClash })
    if (b.quotesFresh) {
      // the notice about extras that could not be added is on screen: going on accepts it
      if (from === "extras") b.dropRejectedExtras()
      return b.goStep("details")
    }
    b.setPending(true)
    const { error, rejected } = await b.quoteAll()
    b.setPending(false)
    if (error) return b.setFlowError(error)
    // stay on the extras step: the notice lists what could not be added and why
    if (from === "extras" && rejected.length) return
    b.goStep("details")
  }

  return { go, busy: b.pending, error: b.flowError, errorView: <FlowErrorAlert /> }
}

/** A limited extra sold out while booking (ExtraSoldOut): back to the extras step with the
 * server's message, and quote the same rooms again so the guest sees what is left. */
export function useBackToExtras() {
  const b = useBooking()
  return async (err: FlowError) => {
    if (b.hasExtras && b.step !== "extras") b.goStep("extras", { keepError: true })
    b.setFlowError(err)
    b.setPending(true)
    const { error, rejected } = await b.quoteAll()
    b.setPending(false)
    if (error) return b.setFlowError(error)
    // Each room is quoted on its own but the booking counts the rooms together: when no room's
    // quote refuses anything, the rooms together need more than is left. The message stays and
    // this choice of extras cannot go on to booking again unchanged.
    const chosen = Object.values(b.flow.extras).some((room) => Object.keys(room ?? {}).length > 0)
    if (!rejected.length && chosen && b.criteria.rooms.length > 1) b.markExtrasClash(err)
  }
}

export function FlowErrorAlert() {
  const { t } = useI18n()
  const b = useBooking()
  const ref = useRef<HTMLDivElement>(null)
  const e = b.flowError
  const backToExtras = useBackToExtras()
  useEffect(() => {
    if (e) {
      ref.current?.focus()
      ref.current?.scrollIntoView({ block: "center" })
    }
  }, [e])
  if (!e) return null

  const research = async () => {
    b.setPending(true)
    await b.runSearch({ force: true })
    b.setPending(false)
    b.goStep("rooms")
  }

  const refresh = async () => {
    b.setPending(true)
    const before = b.flow.selections
    const r = await b.refreshAfterExpiry()
    if (r.status === "gone") {
      b.setPending(false)
      b.goStep("rooms", { keepError: true })
      b.setFlowError({ kind: "unavailable", message: "", room: undefined })
      return
    }
    const { error } = await b.quoteAll(r.selections, before)
    b.setPending(false)
    b.setFlowError(error)
    if (!error && b.step === "rooms") b.goStep(b.hasExtras ? "extras" : "details")
  }

  const roomLabel = (err: FlowError) => (err.room !== undefined && b.criteria.rooms.length > 1 ? `${t("guests.room", { n: err.room + 1 })}: ` : "")
  let title = t("errors.genericTitle")
  let body: string = e.message || t("errors.generic")
  let action = (
    <Button size="sm" onClick={() => b.setFlowError(null)} variant="secondary">
      {t("common.dismiss")}
    </Button>
  )
  if (e.kind === "sold_out") {
    title = roomLabel(e) + t("errors.soldOutTitle")
    body = t("errors.soldOutBody")
    action = (
      <Button size="sm" onClick={research} busy={b.pending}>
        {t("errors.seeAvailable")}
      </Button>
    )
  } else if (e.kind === "extra_sold_out") {
    title = t("errors.extraSoldOutTitle")
    // every room alone still gets its extras, the rooms together need more than is left
    body = [e.message, t(b.extrasClash ? "errors.extraSoldOutTogether" : "errors.extraSoldOutBody")].filter(Boolean).join(" ")
    if (b.step !== "extras" && b.hasExtras)
      action = (
        <Button size="sm" onClick={() => void backToExtras(e)} busy={b.pending}>
          {t("errors.reviewExtras")}
        </Button>
      )
  } else if (e.kind === "unavailable") {
    title = roomLabel(e) + t("errors.unavailableTitle")
    body = t("errors.unavailableBody")
    action = (
      <Button size="sm" onClick={research} busy={b.pending}>
        {t("errors.seeAvailable")}
      </Button>
    )
  } else if (e.kind === "expired") {
    title = t("errors.expiredTitle")
    body = t("errors.expiredBody")
    action = (
      <Button size="sm" onClick={refresh} busy={b.pending}>
        {t("errors.refreshPrices")}
      </Button>
    )
  } else if (e.kind === "rate_limit") {
    title = t("errors.rateLimitTitle")
    body = t("errors.rateLimitBody")
  } else if (e.kind === "network") {
    title = t("errors.networkTitle")
    body = t("errors.network")
  }
  return (
    <Alert ref={ref} tone={e.kind === "expired" || e.kind === "extra_sold_out" ? "warn" : "bad"} title={title} actions={action}>
      {body}
    </Alert>
  )
}

/** Shown after quoting when the server's price differs from the search result. */
export function PriceChangeNotice() {
  const { t, money } = useI18n()
  const b = useBooking()
  const changes = b.flow.priceChanges
  if (!changes.length) return null
  const multi = b.criteria.rooms.length > 1
  return (
    <Alert
      tone="warn"
      title={t("errors.priceChangedTitle")}
      actions={
        <>
          <Button size="sm" variant="secondary" onClick={b.clearPriceChanges}>
            {t("errors.acceptPrice")}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => b.goStep("rooms")}>
            {t("errors.chooseAgain")}
          </Button>
        </>
      }
    >
      <ul className="space-y-0.5">
        {changes.map((c) => (
          <li key={c.room}>
            {multi ? `${t("guests.room", { n: c.room + 1 })}: ` : ""}
            {t("errors.priceChangedLine", { from: money(c.from, c.currency), to: money(c.to, c.currency) })}
          </li>
        ))}
      </ul>
    </Alert>
  )
}

/** After quoting: the extras the guest chose that could not be added (sold out or closed
 * on a day, not enough left…). They are not charged; the guest continues without them or
 * changes the choice on the extras step. */
export function RejectedExtrasNotice() {
  const i18n = useI18n()
  const { t } = i18n
  const b = useBooking()
  const ref = useRef<HTMLDivElement>(null)
  const list = b.rejectedExtras
  const sig = list.map((r) => `${r.room}|${r.code}|${r.reason}`).join(",")
  const onExtras = b.step === "extras"
  useEffect(() => {
    if (sig) ref.current?.scrollIntoView({ block: "nearest" })
  }, [sig])
  if (!list.length) return null
  const multi = b.criteria.rooms.length > 1

  const without = () => {
    b.dropRejectedExtras()
    if (onExtras) b.goStep("details")
  }
  const change = () => {
    if (!onExtras) return b.goStep("extras")
    const first = document.getElementById(extraAnchor(list[0].room, list[0].code))
    first?.scrollIntoView({ block: "center" })
    first?.focus({ preventScroll: true })
  }

  return (
    <Alert
      ref={ref}
      tone="warn"
      title={t("extras.rejectedTitle")}
      actions={
        <>
          <Button size="sm" variant="secondary" onClick={without} disabled={b.pending}>
            {t("extras.continueWithout")}
          </Button>
          <Button size="sm" variant="ghost" onClick={change} disabled={b.pending}>
            {t("extras.changeChoice")}
          </Button>
        </>
      }
    >
      <ul className="space-y-0.5">
        {list.map((r) => (
          <li key={`${r.room}|${r.code}`} className="break-words">
            {multi ? `${t("guests.room", { n: r.room + 1 })}: ` : ""}
            <span className="font-medium text-ink">{r.name}</span> — {refusalText(i18n, r.reason)}
          </li>
        ))}
      </ul>
      <p className="mt-1">{t("extras.rejectedBody")}</p>
    </Alert>
  )
}
