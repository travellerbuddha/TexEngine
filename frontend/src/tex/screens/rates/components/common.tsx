import type { ReactNode } from "react"
import { AlertOctagon, AlertTriangle, CheckCircle2 } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { useTexT } from "../../../i18n"
import { date as fmtDate } from "../../../lib/format"
import { Badge, statusTone } from "../../../ui"
import { enumLabel } from "../lib/options"
import type { Issue } from "../lib/types"

/** Status as text + tone (never colour alone). `group` picks the label set. */
export function StatusBadge({ status, group }: { status: string | null | undefined; group: "contract_status" | "version_status" | "rev_status" }) {
  const { t } = useTexT()
  if (!status) return null
  return <Badge tone={statusTone(status)}>{enumLabel(t, group, status)}</Badge>
}

/** "12 Jan 2026 – 31 Dec 2027"; open ends read "from …" / "until …" / "Open". */
export function DateRange({ from, to, className }: { from?: string | null; to?: string | null; className?: string }) {
  const { t } = useTexT()
  let text: string
  if (from && to) text = `${fmtDate(from)} – ${fmtDate(to)}`
  else if (from) text = t("rates.common.from_date", { date: fmtDate(from) })
  else if (to) text = t("rates.common.until_date", { date: fmtDate(to) })
  else text = t("rates.common.open_ended")
  return <span className={cn("whitespace-nowrap", !from && !to && "text-zinc-500", className)}>{text}</span>
}

const asIs = (issue: Issue) => issue.message

/** Server validation issues (validate_version): errors block publishing, warnings don't.
 * `format` gives an issue's message as shown (the version editor shows band codes as their labels,
 * D13); the server's message by default (the policy editor). */
export function IssueList({
  issues,
  emptyOk,
  compact,
  format = asIs,
}: {
  issues: Issue[] | undefined
  emptyOk?: ReactNode
  compact?: boolean
  format?: (issue: Issue) => string
}) {
  const { t } = useTexT()
  if (!issues) return null
  if (!issues.length)
    return emptyOk ? (
      <p className="flex items-center gap-2 text-sm text-emerald-800" role="status">
        <CheckCircle2 className="size-4 text-emerald-600" aria-hidden />
        {emptyOk}
      </p>
    ) : null
  const errors = issues.filter((i) => i.level === "ERROR")
  const warnings = issues.filter((i) => i.level !== "ERROR")
  return (
    <div className="space-y-2">
      {errors.length > 0 && (
        <IssueGroup tone="danger" title={t("rates.validation.errors", { count: errors.length })} items={errors} compact={compact} format={format} />
      )}
      {warnings.length > 0 && (
        <IssueGroup tone="warning" title={t("rates.validation.warnings", { count: warnings.length })} items={warnings} compact={compact} format={format} />
      )}
    </div>
  )
}

function IssueGroup({ tone, title, items, compact, format }: { tone: "danger" | "warning"; title: string; items: Issue[]; compact?: boolean; format: (issue: Issue) => string }) {
  const Icon = tone === "danger" ? AlertOctagon : AlertTriangle
  const max = compact ? 6 : 50
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cn(
        "rounded-lg border px-3 py-2 text-sm",
        tone === "danger" ? "border-rose-200 bg-rose-50 text-rose-900" : "border-amber-200 bg-amber-50 text-amber-900",
      )}
    >
      <p className="flex items-center gap-1.5 font-semibold">
        <Icon className="size-4 shrink-0" aria-hidden />
        {title}
      </p>
      <ul className="mt-1 list-disc space-y-0.5 pl-6">
        {items.slice(0, max).map((i, n) => (
          <li key={`${i.code}-${n}`}>
            <span className="font-mono text-[11px] opacity-70">{i.code}</span> {format(i)}
          </li>
        ))}
        {items.length > max && <li>… +{items.length - max}</li>}
      </ul>
    </div>
  )
}

/** Tab badge: counts of errors / warnings for a version-editor tab. */
export function IssueCount({ errors, warnings }: { errors: number; warnings: number }) {
  const { t } = useTexT()
  if (!errors && !warnings) return null
  return (
    <span className="inline-flex gap-1">
      {errors > 0 && (
        <Badge tone="danger">
          <AlertOctagon className="size-3" aria-hidden />
          <span aria-hidden>{errors}</span>
          <span className="sr-only">{t("rates.validation.errors", { count: errors })}</span>
        </Badge>
      )}
      {warnings > 0 && (
        <Badge tone="warning">
          <AlertTriangle className="size-3" aria-hidden />
          <span aria-hidden>{warnings}</span>
          <span className="sr-only">{t("rates.validation.warnings", { count: warnings })}</span>
        </Badge>
      )}
    </span>
  )
}

/** Explanatory paragraph under a section heading. */
export function Help({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("text-sm text-zinc-600", className)}>{children}</p>
}
