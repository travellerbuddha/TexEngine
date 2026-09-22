import type { ReactNode } from "react"
import { NavLink } from "react-router-dom"
import { ChevronLeft, ChevronRight, Mail, MessageCircle, Smartphone } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { num } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button } from "../../../ui"
import type { ConsentField } from "../types"

/** Secondary navigation inside /tex/crm (links, not ARIA tabs: each is a page). */
export function CrmNav() {
  const { t } = useTexT()
  const items = [
    { to: "/tex/crm", label: t("crm.nav.guests"), end: true },
    { to: "/tex/crm/segments", label: t("crm.nav.segments") },
    { to: "/tex/crm/abandoned", label: t("crm.nav.abandoned") },
  ]
  return (
    <nav aria-label={t("crm.nav.label")} className="-mt-2 mb-5 flex gap-1 overflow-x-auto border-b border-zinc-200">
      {items.map((i) => (
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

const CONSENT_ICON: Record<ConsentField, typeof Mail> = {
  tex_consent_email: Mail,
  tex_consent_sms: Smartphone,
  tex_consent_whatsapp: MessageCircle,
}
const CONSENT_KEY: Record<ConsentField, string> = {
  tex_consent_email: "crm.channel.email",
  tex_consent_sms: "crm.channel.sms",
  tex_consent_whatsapp: "crm.channel.whatsapp",
}

/** Marketing consent per channel. Granted channels read as text + icon, never colour alone. */
export function ConsentChips({ row, compact }: { row: Record<ConsentField, 0 | 1 | boolean>; compact?: boolean }) {
  const { t } = useTexT()
  const fields = Object.keys(CONSENT_ICON) as ConsentField[]
  const granted = fields.filter((f) => Boolean(row[f]))
  if (!granted.length)
    return (
      <Badge tone="neutral" title={t("crm.consent.none_hint")}>
        {t("crm.consent.none")}
      </Badge>
    )
  return (
    <span className="inline-flex flex-wrap gap-1">
      {granted.map((f) => {
        const Icon = CONSENT_ICON[f]
        return (
          <Badge key={f} tone="success" title={t("crm.consent.granted_for", { channel: t(CONSENT_KEY[f]) })}>
            <Icon className="size-3" aria-hidden />
            {compact ? <span className="sr-only">{t(CONSENT_KEY[f])}</span> : t(CONSENT_KEY[f])}
          </Badge>
        )
      })}
    </span>
  )
}

export function consentLabelKey(f: ConsentField) {
  return CONSENT_KEY[f]
}

export function ConsentIcon({ field, className }: { field: ConsentField; className?: string }) {
  const Icon = CONSENT_ICON[field]
  return <Icon className={className ?? "size-4"} aria-hidden />
}

/** "1–25 of 60" + previous/next. */
export function Pager({
  start,
  pageSize,
  total,
  onChange,
}: {
  start: number
  pageSize: number
  total: number
  onChange: (start: number) => void
}) {
  const { t } = useTexT()
  if (total <= pageSize && start === 0) return null
  const from = total ? start + 1 : 0
  const to = Math.min(start + pageSize, total)
  return (
    <nav aria-label={t("crm.pager.label")} className="flex items-center justify-between gap-3 border-t border-zinc-100 px-4 py-2.5 text-sm">
      <p className="text-zinc-600" aria-live="polite">
        {t("crm.pager.range", { from: num(from), to: num(to), total: num(total) })}
      </p>
      <div className="flex gap-2">
        <Button
          variant="secondary"
          size="sm"
          icon={<ChevronLeft className="size-4" aria-hidden />}
          disabled={start === 0}
          onClick={() => onChange(Math.max(0, start - pageSize))}
        >
          {t("crm.pager.prev")}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={start + pageSize >= total}
          onClick={() => onChange(start + pageSize)}
        >
          {t("crm.pager.next")}
          <ChevronRight className="size-4" aria-hidden />
        </Button>
      </div>
    </nav>
  )
}

/** Label/value pair used in compact panels. */
export function Meta({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium text-zinc-500">{label}</dt>
      <dd className="mt-0.5 text-sm break-words text-zinc-900">{children}</dd>
    </div>
  )
}
