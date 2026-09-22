// Moving forward through the flow (rooms → extras → details) and recovering from the
// server's "sold out", "no longer available" and "offer expired" answers by searching
// again for the same stay.
import { useEffect, useRef } from "react"
import { useI18n } from "../i18n"
import { Button } from "../ui/controls"
import { Alert } from "../ui/feedback"
import { useBooking, type FlowError, type Step } from "./BookingContext"

export function useContinue() {
  const b = useBooking()

  const go = async (from: Step) => {
    b.setFlowError(null)
    if (from === "rooms" && b.hasExtras) return b.goStep("extras")
    if (b.quotesFresh) return b.goStep("details")
    b.setPending(true)
    const err = await b.quoteAll()
    b.setPending(false)
    if (err) return b.setFlowError(err)
    b.goStep("details")
  }

  return { go, busy: b.pending, error: b.flowError, errorView: <FlowErrorAlert /> }
}

export function FlowErrorAlert() {
  const { t } = useI18n()
  const b = useBooking()
  const ref = useRef<HTMLDivElement>(null)
  const e = b.flowError
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
    const err = await b.quoteAll(r.selections, before)
    b.setPending(false)
    b.setFlowError(err)
    if (!err && b.step === "rooms") b.goStep(b.hasExtras ? "extras" : "details")
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
    <Alert ref={ref} tone={e.kind === "expired" ? "warn" : "bad"} title={title} actions={action}>
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
