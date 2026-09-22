import { FlaskConical } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { useI18n } from "../i18n"
import { ApiError, pub } from "../lib/api"
import { forgetPayment, storedPayment } from "../lib/storage"
import { appPath } from "../flow/payment"
import { Button } from "../ui/controls"
import { Alert, EmptyState } from "../ui/feedback"
import { PlainShell } from "./SiteError"

interface MockResult {
  transaction: string
  status: string
  booking?: string | null
  return_url?: string | null
}

/** Sandbox gateway for the Mock provider: a stand-in for a real card page. It never
 * asks for card data and can only complete transactions of Sandbox accounts. */
export default function MockPayPage() {
  const { t, money } = useI18n()
  const { txn = "" } = useParams()
  const navigate = useNavigate()
  const stored = useRef(storedPayment(txn)).current
  const [busy, setBusy] = useState<"success" | "fail" | null>(null)
  const [error, setError] = useState<string | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    heading.current?.focus({ preventScroll: true })
  }, [])

  const finish = async (outcome: "success" | "fail") => {
    const sig = outcome === "success" ? stored?.success_sig : stored?.fail_sig
    if (!sig) return
    setBusy(outcome)
    setError(null)
    try {
      const r = await pub<MockResult>("mock_pay", { transaction: txn, outcome, sig })
      forgetPayment(txn)
      const status = (r.status || "").toLowerCase()
      const target = r.return_url || "/book"
      const sep = target.includes("?") ? "&" : "?"
      const url = `${target}${sep}payment=${encodeURIComponent(r.transaction)}&status=${encodeURIComponent(status)}`
      const inApp = appPath(url)
      if (inApp) navigate(inApp, { replace: true })
      else window.location.assign(url)
    } catch (e) {
      setBusy(null)
      setError(e instanceof ApiError && e.message ? e.message : t("errors.generic"))
    }
  }

  return (
    <PlainShell
      title={t("mock.docTitle")}
      badge={
        <>
          <FlaskConical className="size-4 text-warn" aria-hidden />
          {t("mock.badge")}
        </>
      }
    >
      <div className="overflow-hidden rounded-card border-2 border-ink bg-surface shadow-card">
        <div className="bk-sandbox-stripes h-3" aria-hidden />
        <div className="p-5 sm:p-8">
          <p className="inline-flex items-center gap-2 rounded-full bg-ink px-3 py-1 text-xs font-bold uppercase tracking-wider text-white">
            <FlaskConical className="size-3.5" aria-hidden />
            {t("mock.label")}
          </p>
          <h1 ref={heading} tabIndex={-1} className="mt-4 text-2xl outline-none sm:text-3xl">
            {t("mock.title")}
          </h1>
          <p className="mt-2 text-soft">{t("mock.body")}</p>
          {!stored?.success_sig ? (
            <div className="mt-6">
              <EmptyState title={t("mock.missingTitle")}>{t("mock.missingBody")}</EmptyState>
            </div>
          ) : (
            <>
              <dl className="mt-6 divide-y divide-line rounded-ui border border-line text-sm">
                {stored.hotel && (
                  <div className="flex justify-between gap-4 p-3">
                    <dt className="text-soft">{t("mock.merchant")}</dt>
                    <dd className="text-right font-medium">{stored.hotel}</dd>
                  </div>
                )}
                {stored.amount && (
                  <div className="flex justify-between gap-4 p-3">
                    <dt className="text-soft">{t("mock.amount")}</dt>
                    <dd className="text-right text-lg font-bold tabular-nums">{money(stored.amount, stored.currency)}</dd>
                  </div>
                )}
                <div className="flex justify-between gap-4 p-3">
                  <dt className="text-soft">{t("mock.transaction")}</dt>
                  <dd className="text-right font-mono text-xs">{txn}</dd>
                </div>
              </dl>
              {error && (
                <Alert tone="bad" className="mt-4" title={t("mock.error")}>
                  {error}
                </Alert>
              )}
              <div className="mt-6 grid gap-3 sm:grid-cols-2">
                <Button size="lg" onClick={() => void finish("success")} busy={busy === "success"} disabled={!!busy}>
                  {t("mock.succeed")}
                </Button>
                <Button size="lg" variant="secondary" onClick={() => void finish("fail")} busy={busy === "fail"} disabled={!!busy}>
                  {t("mock.decline")}
                </Button>
              </div>
            </>
          )}
          <p className="mt-6 text-xs text-muted">{t("mock.footer")}</p>
        </div>
      </div>
    </PlainShell>
  )
}
