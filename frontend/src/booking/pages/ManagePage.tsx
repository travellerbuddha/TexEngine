import { CalendarCog, CreditCard, KeyRound, Mail, Phone, Sparkles, XCircle } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"
import { useI18n } from "../i18n"
import { ApiError, pub } from "../lib/api"
import { MAX_ADULTS, MAX_CHILDREN, type Party } from "../lib/criteria"
import { parseRefusal, refusalText } from "../lib/extras"
import { isNegative, isPositive, isZero } from "../lib/format"
import { rememberPayment, returnPathFor, setItem, siteManageToken } from "../lib/storage"
import { continuePayment } from "../flow/payment"
import { DateRangePicker } from "../search/DateRangePicker"
import { RoomsEditor } from "../search/GuestsPicker"
import { Shell } from "../site/Layout"
import { SiteProvider, useSite, useSiteData } from "../site/SiteContext"
import type { BookingRoom, BookingSummary, PaymentStart, Proposal, Reason } from "../types"
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

function ChangeDialog({ room, currency, token, onClose, onDone }: { room: BookingRoom; currency: string; token: string; onClose: () => void; onDone: (n: Notice) => void }) {
  const i18n = useI18n()
  const { t, money } = i18n
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
    if (!proposal) return
    setBusy(true)
    setError(null)
    try {
      const r = await pub<{ status: string; message?: string; balance?: string; difference?: string; currency?: string }>("manage_apply", {
        token,
        proposal_token: proposal.proposal_token,
        note: note.trim() || undefined,
      })
      if (r.status === "requested") onDone({ tone: "info", title: t("manage.requestedTitle"), body: t("manage.requestedBody") })
      else onDone({ tone: "ok", title: t("manage.appliedTitle"), body: r.balance && isPositive(r.balance) ? t("manage.appliedBalance", { amount: money(r.balance, r.currency || currency) }) : t("manage.appliedBody") })
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
              <Button onClick={apply} busy={busy} disabled={!proposal.sellable}>
                {lower ? t("manage.sendRequest") : t("manage.confirmChange")}
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
              {higher && <p className="text-sm text-soft">{t("manage.higherNote")}</p>}
              {lower && <Alert tone="info" title={t("manage.lowerTitle")}>{t("manage.lowerBody")}</Alert>}
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
  const { t, money, lang } = useI18n()
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
  const heading = useRef<HTMLHeadingElement>(null)
  const payStatus = sp.get("status")

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
    if (own && !own.startsWith(`/${site.slug}/manage`)) navigate(`${own}${own.includes("?") ? "&" : "?"}${sp.toString()}`, { replace: true })
  }, [sp, site.slug, navigate])
  useEffect(() => {
    document.title = `${t("manage.title")} · ${site.name}`
  }, [t, site.name])
  useEffect(() => {
    if (payStatus === "succeeded") setNotice({ tone: "ok", title: t("manage.paidTitle") })
    else if (payStatus === "failed") setNotice({ tone: "bad", title: t("confirm.failedTitle"), body: t("confirm.failedBody") })
    else if (payStatus === "pending" || payStatus === "unverified") setNotice({ tone: "warn", title: t("confirm.verifyingTitle"), body: t("confirm.verifyingBody") })
  }, [payStatus, t])

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
      const p = await pub<PaymentStart>("pay_booking", { token, payment_method: "Card", return_url: `${window.location.origin}/book/${site.slug}/manage` })
      rememberPayment(p, { currency: data.currency, hotel: data.hotel, amount: isZero(data.paid) && data.status === "Pending Payment" ? data.due_now : undefined })
      const out = continuePayment(p, navigate)
      if (out === "none" || out === "blocked") setPaying(false)
    } catch (e) {
      setPaying(false)
      setNotice({ tone: "bad", title: t("confirm.retryFailed"), body: e instanceof ApiError ? e.message : undefined })
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
        </Alert>
      )}
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
                    <Button variant="secondary" size="sm" onClick={() => setChange(r)}>
                      <CalendarCog className="size-4" aria-hidden />
                      {t("manage.change")}
                    </Button>
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
      {change && <ChangeDialog room={change} currency={data.currency} token={token} onClose={() => setChange(null)} onDone={done} />}
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
  const { site: slug } = useParams()
  const { site, error, retry } = useSiteData(slug)
  if (error) return <SiteError error={error} onRetry={retry} />
  if (!site) return <Spinner className="p-10" />
  return (
    <SiteProvider site={site}>
      <Shell home={`/book/${site.slug}`}>
        <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
          <ManageInSite />
        </div>
      </Shell>
    </SiteProvider>
  )
}
