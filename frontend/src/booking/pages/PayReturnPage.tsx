import { CheckCircle2, Clock, XCircle } from "lucide-react"
import { useEffect } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { useI18n } from "../i18n"
import { returnPathFor } from "../lib/storage"
import { EmptyState, Spinner } from "../ui/feedback"
import { PlainShell } from "./SiteError"

/** Where a gateway sends the guest back after paying a payment link. The link's token
 * is never part of the return address (G-10): the tab that started the payment
 * remembered its link page, and the guest continues there. */
export default function PayReturnPage() {
  const { t } = useI18n()
  const [sp] = useSearchParams()
  const navigate = useNavigate()
  const txn = sp.get("payment") ?? ""
  const status = (sp.get("status") ?? "").toLowerCase()
  const own = txn ? returnPathFor(txn) : null

  useEffect(() => {
    if (own) navigate(`${own}${own.includes("?") ? "&" : "?"}${sp.toString()}`, { replace: true })
  }, [own, navigate, sp])

  if (own)
    return (
      <PlainShell title={t("paylink.title")}>
        <Spinner label={t("common.loading")} className="py-10" />
      </PlainShell>
    )
  const [title, icon] =
    status === "succeeded"
      ? [t("payreturn.succeededTitle"), <CheckCircle2 key="ok" className="size-10 text-ok" aria-hidden />]
      : status === "failed" || status === "cancelled"
        ? [t("payreturn.failedTitle"), <XCircle key="bad" className="size-10 text-bad" aria-hidden />]
        : [t("payreturn.pendingTitle"), <Clock key="wait" className="size-10 text-warn" aria-hidden />]
  return (
    <PlainShell title={t("paylink.title")}>
      <EmptyState icon={icon} title={title}>
        {t("payreturn.body")}
      </EmptyState>
    </PlainShell>
  )
}
