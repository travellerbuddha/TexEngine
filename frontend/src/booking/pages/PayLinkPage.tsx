import { CheckCircle2, Clock, CreditCard, Lock, ShieldCheck, XCircle } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate, useSearchParams } from "react-router-dom"
import { useI18n } from "../i18n"
import { ApiError, pub } from "../lib/api"
import { isPositive, isZero } from "../lib/format"
import { refusalMessage } from "../lib/refusals"
import { getItem, rememberPayment, rememberReturn, setItem } from "../lib/storage"
import { continuePayment } from "../flow/payment"
import { payLinkPagePath } from "../lib/mount"
import { payLinkNotices } from "../lib/paylink"
import type { PaymentLinkInfo, PaymentStart } from "../types"
import { Button } from "../ui/controls"
import { Alert, EmptyState, Spinner } from "../ui/feedback"
import { PlainShell } from "./SiteError"

const LINK_TOKEN = "tex.paylink.token"
/** the token of the link a payment of this tab was started from (LO-30) */
const paidFrom = (txn: string) => `tex.paylink.txn.${txn}`

/** Take the link's token from the URL fragment (never sent to a server, G-83), keep it for
 * this tab and remove it from the address bar, like the manage page's magic link. Back from a gateway
 * (``payment``: the charge this tab started) the token is the one that charge was started from: the return
 * address carries none (LO-30). */
function takeLinkToken(payment: string | null): string | null {
  const m = /(?:^|[#&])token=([^&]+)/.exec(window.location.hash)
  if (!m) return (payment ? getItem(paidFrom(payment)) : null) ?? getItem(LINK_TOKEN)
  const tok = decodeURIComponent(m[1])
  setItem(LINK_TOKEN, tok)
  try {
    window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search)
  } catch {
    /* ignore */
  }
  return tok
}

export default function PayLinkPage() {
  const i18n = useI18n()
  const { t, money, dateTime } = i18n
  const { hash } = useLocation()
  const [sp] = useSearchParams()
  const payment = sp.get("payment")
  // a link opened again in this tab (only its fragment changes) brings a new token
  const token = useMemo(() => takeLinkToken(payment) ?? "", [hash, payment]) // eslint-disable-line react-hooks/exhaustive-deps
  const navigate = useNavigate()
  const status = sp.get("status")
  const [link, setLink] = useState<PaymentLinkInfo | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [paying, setPaying] = useState(false)
  const [payError, setPayError] = useState<string | null>(null)
  const [account, setAccount] = useState<string | null>(null)
  const polls = useRef(0)
  const heading = useRef<HTMLHeadingElement>(null)

  const load = useCallback(async () => {
    try {
      setLink(await pub<PaymentLinkInfo>("payment_link", { token }))
      setError(null)
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError("", 0, "", "network"))
    }
  }, [token])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (link) heading.current?.focus({ preventScroll: true })
  }, [link?.status]) // eslint-disable-line react-hooks/exhaustive-deps

  // gateway result may land a moment after the guest returns
  useEffect(() => {
    if (!link || status !== "succeeded" || link.status === "Paid" || link.late_payment || polls.current >= 5) return
    const h = setTimeout(() => {
      polls.current++
      void load()
    }, 2500)
    return () => clearTimeout(h)
  }, [link, status, load])

  const pay = async () => {
    if (!link) return
    setPaying(true)
    setPayError(null)
    try {
      // the server picks the hotel's gateway; the guest only chooses when it asks (several card gateways)
      const p = await pub<PaymentStart>("pay_link", { token, provider_account: account ?? undefined })
      rememberPayment(p, { amount: isZero(link.paid) ? link.amount : undefined, currency: link.currency, hotel: link.hotel ?? undefined })
      // the gateway returns to /pay/return (the token is never sent to it); come back here, the token kept for this
      // charge in the tab, never in the address (LO-30)
      setItem(paidFrom(p.transaction), token)
      rememberReturn(p.transaction, payLinkPagePath())
      const out = continuePayment(p, navigate)
      if (out === "none" || out === "blocked") setPaying(false)
    } catch (e) {
      setPaying(false)
      // several card gateways and none chosen: the guest picks one (G-70b: by code, never any refusal)
      if (!account && link.methods.length > 1 && e instanceof ApiError
          && (e.code === "LINK_NO_CARD" || e.code === "PAYMENT_METHOD_UNAVAILABLE")) {
        setAccount(link.methods[0].provider_account)
        return
      }
      setPayError(refusalMessage(i18n, e instanceof ApiError ? e : null))
    }
  }

  const shellTitle = link?.hotel ? `${t("paylink.title")} · ${link.hotel}` : t("paylink.title")
  const badge = (
    <>
      <Lock className="size-4 text-ok" aria-hidden />
      {link?.hotel ?? t("paylink.secure")}
    </>
  )

  if (error)
    return (
      <PlainShell title={t("paylink.title")} badge={badge}>
        <h1 className="sr-only">{t("paylink.title")}</h1>
        <EmptyState icon={<XCircle className="size-8" aria-hidden />} title={error.kind === "not_found" ? t("paylink.invalidTitle") : t("confirm.loadError")} actions={error.kind !== "not_found" && <Button onClick={() => void load()}>{t("common.retry")}</Button>}>
          {error.kind === "not_found" ? t("paylink.invalidBody") : error.code ? refusalMessage(i18n, error) : error.message || t("errors.network")}
        </EmptyState>
      </PlainShell>
    )
  if (!link)
    return (
      <PlainShell title={t("paylink.title")} badge={badge}>
        <Spinner label={t("common.loading")} className="py-10" />
      </PlainShell>
    )

  const notices = payLinkNotices(link, status)
  const { payable, paid } = notices
  let head = t("paylink.heading")
  let Icon = CreditCard
  let tone = "text-brand-ink"
  if (link.late_payment) {
    // its booking could no longer take the money: never "paid — thank you" (B5)
    head = t("manage.lateTitle")
    Icon = Clock
    tone = "text-warn"
  } else if (paid) {
    head = t("paylink.paidTitle")
    Icon = CheckCircle2
    tone = "text-ok"
  } else if (!payable) {
    head = link.status === "Expired" ? t("paylink.expiredTitle") : t("paylink.closedTitle")
    Icon = Clock
    tone = "text-warn"
  }

  return (
    <PlainShell title={shellTitle} badge={badge}>
      <section className="bk-card p-5 sm:p-8" aria-labelledby="bk-pl-h">
        <div className="text-center">
          <Icon className={`mx-auto size-11 ${tone}`} aria-hidden />
          <h1 id="bk-pl-h" ref={heading} tabIndex={-1} className="mt-3 text-2xl outline-none">
            {head}
          </h1>
          {link.hotel && <p className="mt-1 text-soft">{link.hotel}</p>}
        </div>
        {notices.failed && (
          <Alert tone="bad" className="mt-5" title={t("confirm.failedTitle")}>
            {t("confirm.failedBody")}
          </Alert>
        )}
        {notices.verifying && (
          <Alert tone="warn" className="mt-5" title={t("confirm.verifyingTitle")}>
            {t("confirm.verifyingBody")}
          </Alert>
        )}
        {notices.late && (
          <Alert tone="warn" className="mt-5">
            {t(link.late_payment === "refund" ? "manage.lateRefund" : "manage.lateContact")}
          </Alert>
        )}
        {payError && (
          <Alert tone="bad" className="mt-5" title={t("confirm.retryFailed")}>
            {payError}
          </Alert>
        )}
        <dl className="mt-6 divide-y divide-line rounded-ui border border-line text-sm">
          {link.description && (
            <div className="flex justify-between gap-4 p-3">
              <dt className="text-soft">{t("paylink.for")}</dt>
              <dd className="text-right font-medium">{link.description}</dd>
            </div>
          )}
          {link.guest_name && (
            <div className="flex justify-between gap-4 p-3">
              <dt className="text-soft">{t("paylink.guest")}</dt>
              <dd className="text-right font-medium">{link.guest_name}</dd>
            </div>
          )}
          <div className="flex justify-between gap-4 p-3">
            <dt className="text-soft">{t("paylink.amount")}</dt>
            <dd className="text-right text-lg font-bold tabular-nums">{money(link.amount, link.currency)}</dd>
          </div>
          {isPositive(link.paid) && (
            <div className="flex justify-between gap-4 p-3">
              <dt className="text-soft">{t("booking.paid")}</dt>
              <dd className="text-right font-medium tabular-nums text-ok">{money(link.paid, link.currency)}</dd>
            </div>
          )}
          {payable && link.expires_at && link.expires_at !== "None" && (
            <div className="flex justify-between gap-4 p-3">
              <dt className="text-soft">{t("paylink.expires")}</dt>
              <dd className="text-right">{dateTime(link.expires_at)}</dd>
            </div>
          )}
        </dl>
        {payable && account && (
          <fieldset className="mt-6">
            <legend className="mb-2 text-sm font-semibold">{t("paylink.chooseGateway")}</legend>
            <div className="space-y-2">
              {link.methods.map((m) => (
                <label key={m.provider_account} className={`flex cursor-pointer items-center gap-3 rounded-ui border p-3 ${account === m.provider_account ? "border-brand-ink bg-brand/5" : "border-line"}`}>
                  <input type="radio" className="bk-check" name="bk-gateway" checked={account === m.provider_account} onChange={() => setAccount(m.provider_account)} />
                  <span className="font-medium">{m.label}</span>
                </label>
              ))}
            </div>
          </fieldset>
        )}
        {payable && (
          <div className="mt-6">
            <Button size="lg" block onClick={pay} busy={paying}>
              <Lock className="size-4" aria-hidden />
              {isZero(link.paid) ? t("paylink.payAmount", { amount: money(link.amount, link.currency) }) : t("paylink.payRest")}
            </Button>
            <p className="mt-3 flex items-start justify-center gap-2 text-center text-sm text-soft">
              <ShieldCheck className="mt-0.5 size-4 flex-none text-ok" aria-hidden />
              {t("payment.cardSecurity")}
            </p>
          </div>
        )}
        {notices.closed && <p className="mt-5 text-center text-sm text-soft">{t("paylink.closedBody")}</p>}
      </section>
    </PlainShell>
  )
}
