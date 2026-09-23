import { CalendarCog, CreditCard, KeyRound, Mail, Phone, Sparkles, XCircle } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useSearchParams, type NavigateFunction } from "react-router-dom"
import { useI18n } from "../i18n"
import { ApiError, pub } from "../lib/api"
import { MAX_ADULTS, MAX_CHILDREN, type Party } from "../lib/criteria"
import { parseRefusal, refusalText } from "../lib/extras"
import { isNegative, isPositive, isZero } from "../lib/format"
import { getItem, rememberPayment, removeItem, returnPathFor, setItem, siteManageToken } from "../lib/storage"
import { continuePayment, resumeAt } from "../flow/payment"
import { sitePath, siteUrl, useSiteSlug } from "../lib/mount"
import { DateRangePicker } from "../search/DateRangePicker"
import { RoomsEditor } from "../search/GuestsPicker"
import { Shell } from "../site/Layout"
import { SiteProvider, useSite, useSiteData } from "../site/SiteContext"
import type { BookingRoom, BookingSummary, ChangeOutcome, ChangeResult, PaymentStart, PendingChange, Proposal, Reason, Settlement } from "../types"
import { Button, Field, Textarea } from "../ui/controls"
import { Dialog } from "../ui/Dialog"
import { Alert, EmptyState, Spinner } from "../ui/feedback"
import { AddExtrasDialog } from "./AddExtrasDialog"
import { RoomBlock, StatusBadge, Totals } from "./bookingView"
import { SiteError } from "./SiteError"

/** Take the magic-link token from the URL fragment (never sent to the server or
 * written to logs), keep it for this tab and remove it from the address bar. */
function takeFragmentToken(slug: string): string | null {
  const m = /(?:^|[#&])token=([^&]+)/.exec(window.location.hash)
  if (!m) return null
  const tok = decodeURIComponent(m[1])
  setItem(`tex.manage.site.${slug}`, tok)
  try {
    window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search)
  } catch {
    /* ignore */
  }
  return tok
}

function useFragmentToken(slug: string) {
  const [token, setToken] = useState<string | null>(() => takeFragmentToken(slug) ?? siteManageToken(slug))
  // another magic link opened in the same tab only changes the fragment
  useEffect(() => {
    const on = () => {
      const tok = takeFragmentToken(slug)
      if (tok) setToken(tok)
    }
    window.addEventListener("hashchange", on)
    return () => window.removeEventListener("hashchange", on)
  }, [slug])
  return token
}

type Notice = { tone: "ok" | "warn" | "bad" | "info"; title: string; body?: string } | null
type I18nT = ReturnType<typeof useI18n>

/** Back from a change's payment, the page looks again this often while the server applies it. */
const CHANGE_RECHECKS = 10
const CHANGE_RECHECK_MS = 2000

/** A change's payment started from this tab: which request it pays for (read on return). */
const changeKey = (txn: string) => `tex.change.pay.${txn}`

/** Hand a change's payment to the gateway (the booking's own payment flow). The change is
 * made by the server once the gateway confirms the payment, never by this page. */
function payForChange(r: ChangeResult, ctx: { currency: string; hotel?: string }, navigate: NavigateFunction): boolean {
  const p = r.payment
  if (!p) return false
  rememberPayment(p, { currency: r.currency || ctx.currency, hotel: ctx.hotel, amount: r.amount })
  if (r.request) setItem(changeKey(p.transaction), r.request)
  const out = continuePayment(p, navigate)
  return out === "internal" || out === "external"
}

/** What happens to the money of a proposed change, in the guest's words (server figures only). */
function settlementText(i18n: I18nT, s: Settlement, difference: string | null): { tone: "info" | "warn"; title?: string; body: string } | null {
  const { t, money } = i18n
  const amount = money(s.amount, s.currency)
  switch (s.kind) {
    case "pay_now":
      return { tone: "info", title: t("manage.settle.payNowTitle", { amount }), body: t("manage.settle.payNowBody", { amount }) }
    case "pay_at_hotel":
      return { tone: "info", body: t("manage.settle.atHotel", { amount }) }
    case "balance":
      if (isZero(s.amount)) return { tone: "info", body: t("manage.settle.covered") }
      return { tone: "info", body: isNegative(difference) ? t("manage.settle.balanceDown", { amount }) : t("manage.settle.balanceUp", { amount }) }
    case "refund": {
      // only what a card can take back is promised as a card refund; the rest the hotel refunds (server-decided)
      const parts = []
      if (s.refund && isPositive(s.refund)) parts.push(t("manage.settle.refund", { amount: money(s.refund, s.currency) }))
      if (s.hotel_refund && isPositive(s.hotel_refund)) parts.push(t("manage.settle.hotelRefund", { amount: money(s.hotel_refund, s.currency) }))
      return { tone: "info", body: parts.join(" ") || t("manage.settle.refund", { amount }) }
    }
    case "credit":
      return { tone: "info", body: t("manage.settle.credit", { amount }) }
    case "staff_approval":
      // a lower price, or a new arrival inside the rate's cancellation terms (the server decides which)
      return { tone: "info", title: t(difference && isNegative(difference) ? "manage.lowerTitle" : "manage.termsTitle"), body: t("manage.lowerBody") }
    case "staff":
      return { tone: "warn", title: t("manage.settle.staffTitle"), body: t("manage.settle.staff", { amount }) }
    default:
      return null
  }
}

/** The notice after the guest confirmed a change (server figures only). */
function resultNotice(i18n: I18nT, r: ChangeResult, currency: string): Notice {
  const { t, money } = i18n
  const s = r.settlement
  const amount = s ? money(s.amount, s.currency || currency) : ""
  if (r.status === "processing") return { tone: "info", title: t("manage.done.processingTitle"), body: t("manage.done.processingBody") }
  if (r.status === "requested")
    return s?.kind === "staff"
      ? { tone: "info", title: t("manage.requestedTitle"), body: t("manage.done.staff", { amount }) }
      : { tone: "info", title: t("manage.requestedTitle"), body: t("manage.requestedBody") }
  const title = t("manage.appliedTitle")
  switch (s?.kind) {
    case "pay_now":
      return { tone: "ok", title, body: t("manage.done.paid", { amount }) }
    case "pay_at_hotel":
      return { tone: "ok", title, body: t("manage.done.atHotel", { amount }) }
    case "refund": {
      // what went back to the card already, what is on its way, what the hotel refunds
      const card = s.refund ?? s.amount
      const hotel = s.hotel_refund && isPositive(s.hotel_refund) ? s.hotel_refund : null
      const parts = []
      if (isPositive(card)) parts.push(s.refund_done ? t("manage.done.refunded", { amount: money(card, s.currency) }) : t("manage.done.refund", { amount: money(card, s.currency) }))
      if (hotel) parts.push(isPositive(card) ? t("manage.settle.hotelRefund", { amount: money(hotel, s.currency) }) : t("manage.done.refundByHotel", { amount: money(hotel, s.currency) }))
      return { tone: "ok", title, body: parts.join(" ") || t("manage.appliedBody") }
    }
    case "staff":
      return { tone: "ok", title, body: t("manage.done.refundByHotel", { amount }) }
    case "credit":
      return { tone: "ok", title, body: t("manage.done.credit", { amount }) }
  }
  return { tone: "ok", title, body: r.balance && isPositive(r.balance) ? t("manage.appliedBalance", { amount: money(r.balance, r.currency || currency) }) : t("manage.appliedBody") }
}

/** What happened to the guest's money for a change that was not made (the server decides it). */
function moneyBack(i18n: I18nT, c: ChangeOutcome): string {
  const { t, money } = i18n
  const paid = money(c.paid, c.currency)
  switch (c.money_back) {
    case "hotel":
      return t("manage.return.hotelRefund", { amount: paid })
    case "refunded":
      return t("manage.return.refunded", { amount: paid })
    case "refunding":
      return t("manage.return.refunding", { amount: paid })
    default:
      return t("manage.return.noPayment")
  }
}

/** Back from the payment page of a change: what came of it, as the server has it now. */
function changeReturnNotice(i18n: I18nT, data: BookingSummary, request: string, payStatus: string | null): Notice {
  const { t, money } = i18n
  const c = data.rooms.map((r) => r.last_change).find((x) => x?.request === request)
  if (!c) return null
  const amount = money(c.amount, c.currency)
  switch (c.status) {
    case "applied":
    case "approved":
      return { tone: "ok", title: t("manage.return.appliedTitle"), body: t("manage.return.appliedBody", { amount }) }
    case "failed":
      return { tone: "bad", title: t("manage.return.failedTitle"), body: `${t("manage.return.failedBody")} ${moneyBack(i18n, c)}` }
    case "expired":
    case "superseded":
      return { tone: "bad", title: t("manage.return.voidTitle"), body: `${t("manage.return.voidBody")} ${moneyBack(i18n, c)}` }
    case "awaiting_payment":
      return payStatus === "failed" || payStatus === "cancelled"
        ? { tone: "bad", title: t("manage.return.declinedTitle"), body: t("manage.return.declinedBody") }
        : { tone: "warn", title: t("confirm.verifyingTitle"), body: t("confirm.verifyingBody") }
  }
  return null
}

/** A guest's change of a room still waiting: for their payment (with a way to pay), or for the hotel. */
function PendingChangeNotice({ room, change, currency, onPay, paying }: { room: BookingRoom; change: PendingChange; currency: string; onPay: () => void; paying: boolean }) {
  const { t, money, range } = useI18n()
  const name = room.room_type_name ?? room.room_type
  if (change.status === "awaiting_payment" && change.amount) {
    const amount = money(change.amount, change.currency || currency)
    const ch = change.changes ?? {}
    const dates = range(ch.check_in ?? room.check_in, ch.check_out ?? room.check_out)
    return (
      <Alert
        tone="warn"
        title={t("manage.pending.payTitle", { name })}
        actions={
          <Button onClick={onPay} busy={paying}>
            <CreditCard className="size-4" aria-hidden />
            {t("manage.pending.payButton", { amount })}
          </Button>
        }
      >
        {t("manage.pending.payBody", { amount, dates })}
      </Alert>
    )
  }
  if (change.status === "requested")
    return (
      <Alert tone="info" title={t("manage.pending.requestTitle", { name })}>
        {change.kind === "staff" && change.amount ? t("manage.done.staff", { amount: money(change.amount, change.currency || currency) }) : t("manage.requestedBody")}
      </Alert>
    )
  return null
}

/** Reservation statuses extras can still be added to (services/addons.py OPEN_STATUSES). */
const EXTRAS_OPEN = new Set(["Confirmed", "Pending Payment", "Held"])

function CancelDialog({ room, currency, token, onClose, onDone }: { room: BookingRoom; currency: string; token: string; onClose: () => void; onDone: (n: Notice) => void }) {
  const { t, money } = useI18n()
  const [reason, setReason] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fee = room.cancellation_fee_now ?? "0"
  const free = isZero(fee)
  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await pub<{ penalty: string; currency: string }>("manage_cancel", { token, reservation: room.reservation, reason: reason.trim() || undefined })
      onDone({
        tone: "ok",
        title: t("manage.cancelledTitle"),
        body: isZero(r.penalty) ? t("manage.cancelledFree") : t("manage.cancelledFee", { amount: money(r.penalty, r.currency || currency) }),
      })
    } catch (e) {
      setBusy(false)
      setError(e instanceof ApiError && e.message ? e.message : t("errors.generic"))
    }
  }
  return (
    <Dialog
      open
      onClose={onClose}
      title={t("manage.cancelTitle", { name: room.room_type_name ?? room.room_type })}
      closeLabel={t("common.close")}
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose}>
            {t("manage.keep")}
          </Button>
          <Button variant="danger" onClick={submit} busy={busy}>
            {t("manage.confirmCancel")}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <div className={`rounded-ui border p-4 ${free ? "border-ok/30 bg-ok-soft" : "border-warn/30 bg-warn-soft"}`}>
          <p className="text-sm text-soft">{t("manage.feeLabel")}</p>
          <p className="text-2xl font-bold tabular-nums">{free ? t("manage.noFee") : money(fee, currency)}</p>
          <p className="mt-1 text-sm text-soft">{free ? t("manage.freeExplain") : room.refundable === false ? t("manage.nonRefExplain") : t("manage.feeExplain")}</p>
        </div>
        <Field label={t("manage.reason")} optional={t("common.optional")}>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value.slice(0, 300))} rows={3} />
        </Field>
        {error && (
          <Alert tone="bad" title={t("manage.cancelFailed")}>
            {error}
          </Alert>
        )}
      </div>
    </Dialog>
  )
}

function ChangeDialog({ room, currency, hotel, token, onClose, onDone }: { room: BookingRoom; currency: string; hotel?: string; token: string; onClose: () => void; onDone: (n: Notice) => void }) {
  const i18n = useI18n()
  const { t, money } = i18n
  const { site } = useSite()
  const navigate = useNavigate()
  // a limited extra no longer available on the new dates ("Spa: sold out on 2027-06-12" or
  // "Spa: not enough left on 2027-06-12"; guests never see how many are left, G-19)
  const warningText = (w: Reason) => {
    const at = w.code === "EXTRA_SOLD_OUT" ? w.message.lastIndexOf(": ") : -1
    if (at <= 0) return w.message
    const why = w.message.slice(at + 2)
    return parseRefusal(why).kind === "other" ? w.message : `${w.message.slice(0, at)}: ${refusalText(i18n, why)}`
  }
  const [checkIn, setCheckIn] = useState<string | null>(room.check_in)
  const [checkOut, setCheckOut] = useState<string | null>(room.check_out)
  const initialAges = (room.child_ages ?? []).map((c) => (typeof c.age === "number" ? c.age : null))
  const [party, setParty] = useState<Party[]>([{ adults: room.adults, ages: initialAges.length === room.children ? initialAges : Array(room.children).fill(null) }])
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState("")
  const [showErrors, setShowErrors] = useState(false)
  const [refreshed, setRefreshed] = useState(false)

  const check = async () => {
    setError(null)
    if (!checkIn || !checkOut) return setError(t("search.errDates"))
    if (party[0].ages.some((a) => a === null)) {
      setShowErrors(true)
      return setError(t("search.errAges"))
    }
    setBusy(true)
    try {
      const p = await pub<Proposal>("manage_propose", {
        token,
        reservation: room.reservation,
        changes: { check_in: checkIn, check_out: checkOut, adults: party[0].adults, children: party[0].ages },
      })
      setProposal(p)
    } catch (e) {
      setError(e instanceof ApiError && e.message ? e.message : t("errors.generic"))
    }
    setBusy(false)
  }

  const apply = async () => {
    if (!proposal?.proposal_token) return
    setBusy(true)
    setError(null)
    try {
      const r = await pub<ChangeResult>("manage_apply", {
        token,
        proposal_token: proposal.proposal_token,
        note: note.trim() || undefined,
        // the gateway brings the guest back here; the server applies the change once it is paid
        return_url: siteUrl(site.slug, "manage"),
      })
      if (r.status === "payment_required") {
        if (!payForChange(r, { currency, hotel }, navigate)) {
          setBusy(false)
          setError(t("errors.generic"))
        }
        return
      }
      onDone(resultNotice(i18n, r, currency))
    } catch (e) {
      setBusy(false)
      if (e instanceof ApiError && e.kind === "expired") {
        // proposals are valid for 30 minutes: price the same change again and let the guest confirm
        setProposal(null)
        setRefreshed(true)
        await check()
        return
      }
      setError(e instanceof ApiError && e.message ? e.message : t("errors.generic"))
    }
  }

  const lower = !!proposal?.difference && isNegative(proposal.difference)
  const higher = !!proposal?.difference && isPositive(proposal.difference)
  const settlement = proposal?.settlement ?? null
  const settleAmount = settlement ? money(settlement.amount, settlement.currency) : ""
  const confirmLabel =
    settlement?.kind === "pay_now"
      ? t("manage.settle.payNowButton", { amount: settleAmount })
      : settlement?.kind === "staff_approval" || settlement?.kind === "staff"
        ? t("manage.sendRequest")
        : t("manage.confirmChange")
  const explain = settlement ? settlementText(i18n, settlement, proposal?.difference ?? null) : null
  return (
    <Dialog
      open
      onClose={onClose}
      title={t("manage.changeTitle", { name: room.room_type_name ?? room.room_type })}
      closeLabel={t("common.close")}
      variant="full"
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          {proposal ? (
            <>
              <Button variant="secondary" onClick={() => setProposal(null)}>
                {t("manage.editAgain")}
              </Button>
              <Button onClick={apply} busy={busy} disabled={!proposal.sellable || !proposal.proposal_token}>
                {confirmLabel}
              </Button>
            </>
          ) : (
            <Button onClick={check} busy={busy}>
              {t("manage.checkPrice")}
            </Button>
          )}
        </div>
      }
    >
      {!proposal ? (
        <div className="space-y-5">
          <DateRangePicker
            id="bk-change-dates"
            checkIn={checkIn}
            checkOut={checkOut}
            onChange={(a, b) => {
              setCheckIn(a)
              setCheckOut(b)
            }}
          />
          <RoomsEditor
            rooms={party}
            onChange={(r) => setParty([{ adults: Math.min(MAX_ADULTS, r[0]?.adults ?? 1), ages: (r[0]?.ages ?? []).slice(0, MAX_CHILDREN) }])}
            showErrors={showErrors}
            single
          />
          {error && (
            <Alert tone="bad" title={t("manage.proposeFailed")}>
              {error}
            </Alert>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          {refreshed && (
            <Alert tone="warn" title={t("manage.refreshedTitle")}>
              {t("manage.refreshedBody")}
            </Alert>
          )}
          {!proposal.sellable ? (
            <Alert tone="bad" title={t("manage.notPossibleTitle")}>
              {proposal.warnings?.map(warningText).join(" ") || t("manage.notPossibleBody")}
            </Alert>
          ) : (
            <>
              <dl className="divide-y divide-line rounded-ui border border-line text-sm">
                <div className="flex justify-between gap-3 p-3">
                  <dt className="text-soft">{t("manage.currentPrice")}</dt>
                  <dd className="tabular-nums">{money(proposal.old_total, proposal.currency)}</dd>
                </div>
                <div className="flex justify-between gap-3 p-3">
                  <dt className="font-semibold">{t("manage.newPrice")}</dt>
                  <dd className="font-bold tabular-nums">{money(proposal.new_total, proposal.currency)}</dd>
                </div>
                {proposal.difference && !isZero(proposal.difference) && (
                  <div className="flex justify-between gap-3 p-3">
                    <dt className="text-soft">{t("manage.difference")}</dt>
                    <dd className={`font-semibold tabular-nums ${lower ? "text-ok" : ""}`}>
                      {higher ? "+" : ""}
                      {money(proposal.difference, proposal.currency)}
                    </dd>
                  </div>
                )}
              </dl>
              {!!proposal.warnings?.length && (
                <Alert tone="warn" title={t("manage.warnings")}>
                  {proposal.warnings.map(warningText).join(" ")}
                  {proposal.warnings.some((w) => w.code === "EXTRA_SOLD_OUT") && ` ${t("manage.extraDropped")}`}
                </Alert>
              )}
              {explain && (
                <Alert tone={explain.tone} title={explain.title} live={false}>
                  {explain.body}
                </Alert>
              )}
              <Field label={t("manage.note")} optional={t("common.optional")}>
                <Textarea value={note} onChange={(e) => setNote(e.target.value.slice(0, 300))} rows={2} />
              </Field>
            </>
          )}
          {error && (
            <Alert tone="bad" title={t("manage.applyFailed")}>
              {error}
            </Alert>
          )}
        </div>
      )}
    </Dialog>
  )
}

function Manage({ token }: { token: string | null }) {
  const i18n = useI18n()
  const { t, money, lang } = i18n
  const { site } = useSite()
  const navigate = useNavigate()
  const [sp] = useSearchParams()
  const [data, setData] = useState<BookingSummary | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [notice, setNotice] = useState<Notice>(null)
  const [cancel, setCancel] = useState<BookingRoom | null>(null)
  const [change, setChange] = useState<BookingRoom | null>(null)
  const [addExtras, setAddExtras] = useState<BookingRoom | null>(null)
  const [paying, setPaying] = useState(false)
  const [payingChange, setPayingChange] = useState<string | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const payStatus = sp.get("status")
  const payTxn = sp.get("payment")
  // a change's payment started from this tab: the page says what came of the change (read once
  // per return, the stored key is removed once the change is settled)
  const changeRequest = useMemo(() => (payTxn ? getItem(changeKey(payTxn)) : null), [payTxn])

  const load = useCallback(async () => {
    if (!token) return
    try {
      setData(await pub<BookingSummary>("booking_status", { token }))
      setError(null)
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError("", 0, "", "network"))
    }
  }, [token])

  // the booking view is localised by the server: load it again after a language switch
  useEffect(() => {
    void load()
  }, [load, lang])
  // a gateway that fell back to the server's default return page: continue where this tab started
  useEffect(() => {
    const txn = sp.get("payment")
    const own = txn ? returnPathFor(txn) : null
    if (own && !own.startsWith(sitePath(site.slug, "manage"))) resumeAt(own, sp.toString(), navigate)
  }, [sp, site.slug, navigate])
  useEffect(() => {
    document.title = `${t("manage.title")} · ${site.name}`
  }, [t, site.name])
  useEffect(() => {
    if (changeRequest) return
    if (payStatus === "succeeded") setNotice({ tone: "ok", title: t("manage.paidTitle") })
    else if (payStatus === "failed") setNotice({ tone: "bad", title: t("confirm.failedTitle"), body: t("confirm.failedBody") })
    else if (payStatus === "pending" || payStatus === "unverified") setNotice({ tone: "warn", title: t("confirm.verifyingTitle"), body: t("confirm.verifyingBody") })
  }, [payStatus, t, changeRequest])
  // back from a change's payment: the change as the server has it now (made once the gateway
  // confirmed the payment, or not made and the payment refunded)
  const [recheck, setRecheck] = useState(0)
  useEffect(() => {
    if (!changeRequest || !payTxn || !data) return
    const n = changeReturnNotice(i18n, data, changeRequest, payStatus)
    if (n) setNotice(n)
    const c = data.rooms.map((r) => r.last_change).find((x) => x?.request === changeRequest)
    if (c && c.status !== "awaiting_payment") removeItem(changeKey(payTxn))
    // the gateway confirmed the payment and the server applies the change right after it: look
    // again for a little while (the page never applies it itself)
    if (c?.status === "awaiting_payment" && payStatus === "succeeded" && recheck < CHANGE_RECHECKS) {
      const timer = window.setTimeout(() => {
        setRecheck((n) => n + 1)
        void load()
      }, CHANGE_RECHECK_MS)
      return () => window.clearTimeout(timer)
    }
  }, [changeRequest, payTxn, data, payStatus, i18n, recheck, load])

  const done = (n: Notice) => {
    setCancel(null)
    setChange(null)
    setAddExtras(null)
    setNotice(n)
    void load()
    requestAnimationFrame(() => heading.current?.focus())
  }

  const pay = async () => {
    if (!token || !data) return
    setPaying(true)
    try {
      const p = await pub<PaymentStart>("pay_booking", { token, payment_method: "Card", return_url: siteUrl(site.slug, "manage") })
      rememberPayment(p, { currency: data.currency, hotel: data.hotel, amount: isZero(data.paid) && data.status === "Pending Payment" ? data.due_now : undefined })
      const out = continuePayment(p, navigate)
      if (out === "none" || out === "blocked") setPaying(false)
    } catch (e) {
      setPaying(false)
      setNotice({ tone: "bad", title: t("confirm.retryFailed"), body: e instanceof ApiError ? e.message : undefined })
    }
  }

  const payChange = async (room: BookingRoom) => {
    const request = room.pending_change?.request
    if (!token || !data || !request) return
    setPayingChange(request)
    try {
      const r = await pub<ChangeResult>("manage_change_pay", { token, request, return_url: siteUrl(site.slug, "manage") })
      if (r.status === "payment_required") {
        if (!payForChange(r, { currency: data.currency, hotel: data.hotel }, navigate)) {
          setPayingChange(null)
          setNotice({ tone: "bad", title: t("confirm.retryFailed"), body: t("errors.generic") })
        }
        return
      }
      setPayingChange(null)
      done(resultNotice(i18n, r, data.currency))
    } catch (e) {
      setPayingChange(null)
      // its price check expired: the guest makes the change again
      setNotice({
        tone: "bad",
        title: t("confirm.retryFailed"),
        body: e instanceof ApiError && e.kind === "expired" ? t("manage.pending.expired") : e instanceof ApiError ? e.message : undefined,
      })
      void load()
    }
  }

  if (!token)
    return (
      <EmptyState icon={<KeyRound className="size-8" aria-hidden />} title={t("manage.noTokenTitle")}>
        {t("manage.noTokenBody")}
      </EmptyState>
    )
  if (error)
    return (
      <Alert tone="bad" title={error.kind === "permission" ? t("manage.invalidLink") : t("confirm.loadError")} actions={error.kind !== "permission" && <Button onClick={() => void load()}>{t("common.retry")}</Button>}>
        {error.message || t("errors.network")}
      </Alert>
    )
  if (!data) return <Spinner label={t("common.loading")} className="py-10" />

  const active = (r: BookingRoom) => !["Cancelled", "Checked Out", "No Show", "Checked In"].includes(r.status)
  const owes = data.status !== "Cancelled" && data.payment_status !== "Pay at Hotel" && (data.status === "Pending Payment" ? isPositive(data.due_now) : isPositive(data.balance))
  // pay at the hotel: what is due there, and the choice to pay it online when the hotel takes cards
  const atHotel = data.status !== "Cancelled" && data.payment_status === "Pay at Hotel" && isPositive(data.balance)
  const waiting = data.rooms.filter((r) => r.pending_change && r.pending_change.status !== "noted")
  const c = site.contact || {}
  return (
    <div className="space-y-6">
      <div>
        <h1 ref={heading} tabIndex={-1} className="text-2xl outline-none sm:text-3xl">
          {t("manage.title")}
        </h1>
        <p className="mt-1 flex flex-wrap items-center gap-2 text-soft">
          <span>
            {t("confirm.reference")} <span className="font-mono font-semibold text-ink">{data.booking}</span>
          </span>
          <StatusBadge status={data.status} />
        </p>
      </div>
      {notice && (
        <Alert tone={notice.tone} title={notice.title}>
          {notice.body}
        </Alert>
      )}
      {data.guest_change_pending && !notice && (
        <Alert tone="warn" title={t("manage.pendingTitle")}>
          {t("manage.pendingBody")}
        </Alert>
      )}
      {owes && (
        <Alert
          tone={data.status === "Pending Payment" ? "warn" : "info"}
          title={data.status === "Pending Payment" ? t("manage.paymentDue") : t("manage.balanceTitle")}
          actions={
            <Button onClick={pay} busy={paying} variant={data.status === "Pending Payment" ? "primary" : "secondary"}>
              <CreditCard className="size-4" aria-hidden />
              {t("confirm.payNow")}
            </Button>
          }
        >
          {data.status === "Pending Payment" ? t("manage.paymentDueBody") : t("manage.balanceBody", { amount: money(data.balance, data.currency) })}
          {data.changes_blocked === "PAYMENT_PENDING" && ` ${t("manage.changesAfterPayment")}`}
        </Alert>
      )}
      {data.changes_blocked === "REFUND_PENDING" && (
        <Alert tone="info" title={t("manage.refundPendingTitle")}>
          {t("manage.refundPendingBody")}
        </Alert>
      )}
      {data.changes_blocked === "CHANGE_APPLYING" && (
        <Alert tone="info" title={t("manage.changeApplyingTitle")}>
          {t("manage.changeApplyingBody")}
        </Alert>
      )}
      {atHotel && (
        <Alert
          tone="info"
          title={t("manage.atHotelTitle")}
          actions={
            data.can_pay_online ? (
              <Button onClick={pay} busy={paying} variant="secondary">
                <CreditCard className="size-4" aria-hidden />
                {t("confirm.payNow")}
              </Button>
            ) : undefined
          }
        >
          {t("manage.atHotelBody", { amount: money(data.balance, data.currency) })}
          {data.can_pay_online && ` ${t("manage.atHotelOnline")}`}
        </Alert>
      )}
      {data.credit && isPositive(data.credit) && (
        <Alert tone="info" title={t("manage.creditTitle", { amount: money(data.credit, data.currency) })}>
          {t("manage.creditBody")}
        </Alert>
      )}
      {data.refund_due && isPositive(data.refund_due) && data.changes_blocked !== "REFUND_PENDING" && (
        <Alert tone="info" title={t("manage.refundDueTitle", { amount: money(data.refund_due, data.currency) })}>
          {t("manage.refundDueBody")}
        </Alert>
      )}
      {waiting.map((r) => (
        <PendingChangeNotice key={r.reservation} room={r} change={r.pending_change!} currency={data.currency} onPay={() => void payChange(r)} paying={payingChange === r.pending_change?.request} />
      ))}
      <section className="bk-card p-4 sm:p-6" aria-labelledby="bk-manage-hotel">
        <h2 id="bk-manage-hotel" className="text-lg">
          {data.hotel ?? site.name}
        </h2>
        <ul className="mt-4 divide-y divide-line">
          {data.rooms.map((r, i) => (
            <RoomBlock
              key={r.reservation}
              room={r}
              index={i}
              count={data.rooms.length}
              currency={data.currency}
              bookingStatus={data.status}
              actions={
                data.self_service && active(r) ? (
                  <>
                    {!data.changes_blocked && r.can_change !== false && (
                      <Button variant="secondary" size="sm" onClick={() => setChange(r)}>
                        <CalendarCog className="size-4" aria-hidden />
                        {t("manage.change")}
                      </Button>
                    )}
                    {EXTRAS_OPEN.has(r.status) && (
                      <Button variant="secondary" size="sm" onClick={() => setAddExtras(r)}>
                        <Sparkles className="size-4" aria-hidden />
                        {t("manage.addExtras")}
                      </Button>
                    )}
                    <Button variant="ghost" size="sm" onClick={() => setCancel(r)} className="text-bad">
                      <XCircle className="size-4" aria-hidden />
                      {t("manage.cancel")}
                    </Button>
                  </>
                ) : undefined
              }
            />
          ))}
        </ul>
        <div className="mt-4 border-t border-line pt-4">
          <Totals b={data} />
        </div>
      </section>
      {!data.self_service && (
        <Alert tone="info" title={t("manage.contactTitle")}>
          <p>{t("manage.contactBody")}</p>
          <p className="mt-2 flex flex-wrap gap-4">
            {c.phone && (
              <a className="inline-flex items-center gap-1.5 font-medium text-brand-ink underline" href={`tel:${c.phone.replace(/[^\d+]/g, "")}`}>
                <Phone className="size-4" aria-hidden /> {c.phone}
              </a>
            )}
            {c.email && (
              <a className="inline-flex items-center gap-1.5 font-medium text-brand-ink underline" href={`mailto:${c.email}`}>
                <Mail className="size-4" aria-hidden /> {c.email}
              </a>
            )}
          </p>
        </Alert>
      )}
      {cancel && <CancelDialog room={cancel} currency={data.currency} token={token} onClose={() => setCancel(null)} onDone={done} />}
      {change && <ChangeDialog room={change} currency={data.currency} hotel={data.hotel} token={token} onClose={() => setChange(null)} onDone={done} />}
      {addExtras && <AddExtrasDialog room={addExtras} currency={data.currency} token={token} onClose={() => setAddExtras(null)} onDone={done} />}
    </div>
  )
}

function ManageInSite() {
  const { site } = useSite()
  const token = useFragmentToken(site.slug)
  return <Manage token={token} />
}

export default function ManagePage() {
  const slug = useSiteSlug()
  const { site, error, retry } = useSiteData(slug)
  if (error) return <SiteError error={error} onRetry={retry} />
  if (!site) return <Spinner className="p-10" />
  return (
    <SiteProvider site={site}>
      <Shell home={sitePath(site.slug)}>
        <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
          <ManageInSite />
        </div>
      </Shell>
    </SiteProvider>
  )
}
