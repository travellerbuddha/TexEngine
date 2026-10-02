import { CheckCircle2, Clock, CreditCard, Landmark, XCircle } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { useI18n } from "../i18n"
import { ApiError, pub } from "../lib/api"
import { isPositive, isZero } from "../lib/format"
import { refusalMessage } from "../lib/refusals"
import { instructionsFor, manageToken, rememberPayment, rememberReturn, saveManageToken } from "../lib/storage"
import { continuePayment } from "../flow/payment"
import { sitePath, siteRoute, siteUrl, useSiteSlug } from "../lib/mount"
import { Shell } from "../site/Layout"
import { siteText, SiteProvider, useSite, useSiteData } from "../site/SiteContext"
import type { BookingSummary, PaymentStart } from "../types"
import { Button } from "../ui/controls"
import { Alert, EmptyState, Spinner } from "../ui/feedback"
import { CopyButton, RoomBlock, StatusBadge, Totals } from "./bookingView"
import { SiteError } from "./SiteError"

type PayParam = "succeeded" | "failed" | "pending" | "unverified" | null

function Instructions({ data, currency }: { data: Record<string, string | null>; currency: string }) {
  const { t, money } = useI18n()
  const rows: [string, string | null | undefined, boolean][] = [
    [t("bank.amount"), data.amount ? money(data.amount, data.currency || currency) : null, false],
    [t("bank.bank"), data.bank, false],
    [t("bank.holder"), data.account_holder, false],
    [t("bank.iban"), data.iban, true],
    [t("bank.reference"), data.reference, true],
  ]
  return (
    <section className="bk-card p-4 sm:p-6" aria-labelledby="bk-bank-h">
      <h2 id="bk-bank-h" className="flex items-center gap-2 text-lg">
        <Landmark className="size-5 text-soft" aria-hidden />
        {t("bank.title")}
      </h2>
      <dl className="mt-3 divide-y divide-line text-sm">
        {rows
          .filter(([, v]) => !!v)
          .map(([k, v, copy]) => (
            <div key={k} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <dt className="text-soft">{k}</dt>
              <dd className="flex items-center gap-1 font-semibold">
                <span className={copy ? "font-mono tracking-wide" : ""}>{v}</span>
                {copy && <CopyButton value={String(v)} label={k} />}
              </dd>
            </div>
          ))}
      </dl>
      {data.note && <p className="mt-3 whitespace-pre-line text-sm text-soft">{data.note}</p>}
      <p className="mt-3 text-sm text-muted">{t("bank.referenceHint")}</p>
    </section>
  )
}

function Confirmation({ booking }: { booking: string }) {
  const i18n = useI18n()
  const { t, lang } = i18n
  const { site } = useSite()
  const navigate = useNavigate()
  const [sp] = useSearchParams()
  const payParam = (sp.get("status") as PayParam) ?? null
  const token = manageToken(booking)
  const [data, setData] = useState<BookingSummary | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [paying, setPaying] = useState(false)
  const [payError, setPayError] = useState<string | null>(null)
  const polls = useRef(0)
  const heading = useRef<HTMLHeadingElement>(null)
  const instructions = instructionsFor(booking)

  const load = useCallback(async () => {
    if (!token) return
    try {
      const b = await pub<BookingSummary>("booking_status", { token })
      setData(b)
      setError(null)
      return b
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError("", 0, "", "network"))
    }
  }, [token])

  // the booking view is localised by the server: load it again after a language switch
  useEffect(() => {
    void load()
  }, [load, lang])

  // the gateway result can reach the server a moment after the guest: re-check briefly
  useEffect(() => {
    if (!data) return
    const waiting = data.status === "Pending Payment" && (payParam === "succeeded" || payParam === "pending" || payParam === "unverified")
    if (!waiting || polls.current >= 6) return
    const h = setTimeout(() => {
      polls.current++
      void load()
    }, 2500)
    return () => clearTimeout(h)
  }, [data, payParam, load])

  useEffect(() => {
    if (data) heading.current?.focus({ preventScroll: true })
  }, [data?.booking]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    document.title = `${t("confirm.docTitle")} · ${site.name}`
  }, [t, site.name])

  const pay = async () => {
    if (!token || !data) return
    setPaying(true)
    setPayError(null)
    try {
      const p = await pub<PaymentStart>("pay_booking", {
        token,
        payment_method: "Card",
        return_url: siteUrl(site.slug, `confirmation/${encodeURIComponent(booking)}`),
      })
      rememberPayment(p, { amount: isZero(data.paid) ? data.due_now : undefined, currency: data.currency, hotel: data.hotel })
      rememberReturn(p.transaction, sitePath(site.slug, `confirmation/${encodeURIComponent(booking)}`))
      const out = continuePayment(p, navigate)
      if (out === "none" || out === "blocked") setPaying(false)
    } catch (e) {
      setPaying(false)
      setPayError(refusalMessage(i18n, e instanceof ApiError ? e : null))
    }
  }

  if (!token)
    return (
      <EmptyState title={t("confirm.noTokenTitle")}>
        <p>{t("confirm.noTokenBody", { booking })}</p>
      </EmptyState>
    )
  if (error)
    return (
      <Alert tone="bad" title={t("confirm.loadError")} actions={<Button onClick={() => void load()}>{t("common.retry")}</Button>}>
        {error.code ? refusalMessage(i18n, error) : error.message || t("errors.network")}
      </Alert>
    )
  if (!data) return <Spinner label={t("common.loading")} className="py-10" />

  const pending = data.status === "Pending Payment" || data.status === "Held"
  const failed = pending && payParam === "failed"
  const verifying = pending && (payParam === "succeeded" || payParam === "pending" || payParam === "unverified")
  const bank = pending && !!instructions && !payParam
  const payAtHotel = data.payment_status === "Pay at Hotel"

  let Icon = CheckCircle2
  let tone = "text-ok"
  let title = t("confirm.confirmedTitle")
  let body = payAtHotel ? t("confirm.confirmedPayAtHotel") : t("confirm.confirmedBody")
  if (data.status === "Cancelled" && data.late_payment) {
    // its money came when it could no longer take it: never "payment received" (B5)
    Icon = Clock
    tone = "text-warn"
    title = t("manage.lateTitle")
    body = t(data.late_payment === "refund" ? "manage.lateRefund" : "manage.lateContact")
  } else if (data.status === "Cancelled") {
    Icon = XCircle
    tone = "text-bad"
    title = t("confirm.cancelledTitle")
    body = t("confirm.cancelledBody")
  } else if (failed) {
    Icon = XCircle
    tone = "text-bad"
    title = t("confirm.failedTitle")
    body = t("confirm.failedBody")
  } else if (verifying) {
    Icon = Clock
    tone = "text-warn"
    title = t("confirm.verifyingTitle")
    body = t("confirm.verifyingBody")
  } else if (bank) {
    Icon = Landmark
    tone = "text-warn"
    title = t("confirm.bankTitle")
    body = t("confirm.bankBody")
  } else if (pending) {
    Icon = CreditCard
    tone = "text-warn"
    title = t("confirm.payTitle")
    body = t("confirm.payBody")
  }
  const note = siteText(site, lang, "confirmation_note")
  // no bearer token in the link: an address or href is read by the site's tag container. The manage
  // page takes the tab's site token, set to this booking's on the click (O-27)
  const manageHref = siteRoute(site.slug, "manage")
  const canPay = pending && !bank && !payAtHotel && isPositive(data.due_now)

  return (
    <div className="space-y-6">
      <section className="bk-card p-5 text-center sm:p-8" aria-labelledby="bk-confirm-h">
        <Icon className={`mx-auto size-12 ${tone}`} aria-hidden />
        <h1 id="bk-confirm-h" ref={heading} tabIndex={-1} className="mt-3 text-2xl outline-none sm:text-3xl">
          {title}
        </h1>
        <p className="mx-auto mt-2 max-w-lg text-soft">{body}</p>
        {note && data.status !== "Cancelled" && <p className="mx-auto mt-3 max-w-lg whitespace-pre-line text-sm text-soft">{note}</p>}
        <div className="mt-4 inline-flex flex-wrap items-center justify-center gap-2 rounded-ui bg-sunken px-4 py-2">
          <span className="text-sm text-soft">{t("confirm.reference")}</span>
          <span className="font-mono text-lg font-bold tracking-wide">{data.booking}</span>
          <CopyButton value={data.booking} label={t("confirm.reference")} />
        </div>
        <div className="mt-3" role="status" aria-label={t("confirm.statusLabel")}>
          <StatusBadge status={data.status} />
        </div>
        {payError && (
          <Alert tone="bad" className="mt-4 text-left" title={t("confirm.retryFailed")}>
            {payError}
          </Alert>
        )}
        {(failed || canPay) && (
          <div className="mt-5 flex flex-col items-center gap-2">
            <Button size="lg" onClick={pay} busy={paying}>
              <CreditCard className="size-4" aria-hidden />
              {failed ? t("confirm.retryPayment") : t("confirm.payNow")}
            </Button>
            <p className="text-xs text-muted">{t("confirm.holdNote")}</p>
          </div>
        )}
        {verifying && (
          <div className="mt-5">
            <Button variant="secondary" onClick={() => void load()}>
              {t("confirm.checkAgain")}
            </Button>
          </div>
        )}
      </section>

      {bank && instructions && <Instructions data={instructions} currency={data.currency} />}

      <section className="bk-card p-4 sm:p-6" aria-labelledby="bk-your-booking">
        <h2 id="bk-your-booking" className="text-lg">
          {data.hotel ?? site.name}
        </h2>
        {data.booker_name && <p className="text-sm text-muted">{t("confirm.bookedBy", { name: data.booker_name })}</p>}
        <ul className="mt-4 divide-y divide-line">
          {data.rooms.map((r, i) => (
            <RoomBlock key={r.reservation} room={r} index={i} count={data.rooms.length} currency={data.currency} bookingStatus={data.status} />
          ))}
        </ul>
        <div className="mt-4 border-t border-line pt-4">
          <Totals b={data} />
        </div>
      </section>

      {site.self_service && data.status !== "Cancelled" && (
        <section className="bk-card flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-6">
          <div>
            <h2 className="text-lg">{t("confirm.manageTitle")}</h2>
            <p className="text-sm text-soft">{t("confirm.manageBody")}</p>
          </div>
          <Link to={manageHref} onClick={() => saveManageToken(data.booking, token, site.slug)} className="bk-btn bk-btn-secondary">
            {t("confirm.manageCta")}
          </Link>
        </section>
      )}
    </div>
  )
}

export default function ConfirmationPage() {
  const { booking } = useParams()
  const slug = useSiteSlug()
  const { site, error, retry } = useSiteData(slug)
  if (error) return <SiteError error={error} onRetry={retry} />
  if (!site || !booking) return <Spinner className="p-10" />
  return (
    <SiteProvider site={site}>
      <Shell home={sitePath(site.slug)}>
        <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
          <Confirmation booking={booking} />
        </div>
      </Shell>
    </SiteProvider>
  )
}
