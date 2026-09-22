import { NavLink } from "react-router-dom"
import { CreditCard, FlaskConical } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { useSession } from "../../../lib/session"
import { useTexT } from "../../../i18n"
import { Badge, statusTone, type Tone } from "../../../ui"
import { linkStatusKey, methodKey, statusKey } from "../lib"
import type { Txn } from "../types"

/** Secondary navigation inside /tex/payments. */
export function PaymentsNav() {
  const { t } = useTexT()
  const { can } = useSession()
  const items = [
    { to: "/tex/payments", label: t("payments.nav.transactions"), end: true, show: true },
    { to: "/tex/payments/links", label: t("payments.nav.links"), show: true },
    { to: "/tex/payments/setup", label: t("payments.nav.setup"), show: can("settings.admin") },
  ]
  return (
    <nav aria-label={t("payments.nav.label")} className="-mt-2 mb-5 flex gap-1 overflow-x-auto border-b border-zinc-200">
      {items
        .filter((i) => i.show)
        .map((i) => (
          <NavLink
            key={i.to}
            to={i.to}
            end={i.end}
            className={({ isActive }) =>
              cn(
                "-mb-px border-b-2 px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors",
                isActive ? "border-tex-600 text-tex-700" : "border-transparent text-zinc-600 hover:text-zinc-900",
              )
            }
          >
            {i.label}
          </NavLink>
        ))}
    </nav>
  )
}

const TXN_TONE: Record<string, Tone> = { Succeeded: "success", Pending: "warning", Failed: "danger", Cancelled: "neutral" }

export function TxnStatusBadge({ status }: { status: string }) {
  const { t } = useTexT()
  return <Badge tone={TXN_TONE[status] ?? "info"}>{t(statusKey(status))}</Badge>
}

const LINK_TONE: Record<string, Tone> = {
  Active: "info",
  "Partially Paid": "warning",
  Paid: "success",
  Expired: "danger",
  Cancelled: "neutral",
  Draft: "neutral",
}

export function LinkStatusBadge({ status }: { status: string }) {
  const { t } = useTexT()
  return <Badge tone={LINK_TONE[status] ?? statusTone(status)}>{t(linkStatusKey(status))}</Badge>
}

/** Card brand + last 4 only — TEX never receives the full number. */
export function CardLabel({ brand, last4 }: { brand?: string | null; last4?: string | null }) {
  const { t } = useTexT()
  if (!brand && !last4) return null
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap text-zinc-700">
      <CreditCard className="size-3.5 text-zinc-400" aria-hidden />
      <span>{brand || t("payments.card")}</span>
      {last4 && (
        <span className="font-mono tabular-nums" aria-label={t("payments.card_ending", { last4 })}>
          •••• {last4}
        </span>
      )}
    </span>
  )
}

export function MethodLabel({ txn }: { txn: Pick<Txn, "method" | "provider" | "card_brand" | "card_last4"> }) {
  const { t } = useTexT()
  return (
    <span className="flex flex-col gap-0.5 text-sm">
      <span className="inline-flex items-center gap-1.5">
        {t(methodKey(txn.method))}
        {txn.provider === "Mock" && (
          <Badge tone="warning" title={t("payments.sandbox_hint")}>
            <FlaskConical className="size-3" aria-hidden />
            {t("payments.sandbox")}
          </Badge>
        )}
      </span>
      {(txn.card_brand || txn.card_last4) && (
        <span className="text-xs">
          <CardLabel brand={txn.card_brand} last4={txn.card_last4} />
        </span>
      )}
    </span>
  )
}

/** Link to the reservations area filtered to one booking (bookings have no screen of their own). */
export function bookingHref(booking: string) {
  return `/tex/reservations?q=${encodeURIComponent(booking)}`
}
