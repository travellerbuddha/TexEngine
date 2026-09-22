import type { HTMLAttributes, ReactNode } from "react"
import { AlertTriangle, Inbox, Lock } from "lucide-react"
import { Link } from "react-router-dom"
import { cn } from "../../lib/utils"
import { Button } from "./primitives"
import { TexApiError } from "../lib/api"
import { useTexT } from "../i18n"

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("min-w-0 rounded-(--radius-tex) border border-zinc-200 bg-white shadow-tex-card", className)} {...rest} />
}

export function CardHeader({
  title,
  description,
  actions,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-3 border-b border-zinc-100 px-4 py-3", className)}>
      <div className="min-w-0">
        <h2 className="text-sm font-semibold text-zinc-900">{title}</h2>
        {description && <p className="mt-0.5 text-xs text-zinc-500">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function CardBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4", className)} {...rest} />
}

export interface Crumb {
  label: ReactNode
  to?: string
}

/** Page title block. Each screen renders exactly one (one <h1> per page). */
export function PageHeader({
  title,
  subtitle,
  actions,
  crumbs,
  meta,
}: {
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  crumbs?: Crumb[]
  meta?: ReactNode
}) {
  return (
    <header className="mb-5 space-y-2">
      {crumbs && crumbs.length > 0 && (
        <nav aria-label="Breadcrumb">
          <ol className="flex flex-wrap items-center gap-1 text-xs text-zinc-500">
            {crumbs.map((c, i) => (
              <li key={i} className="flex items-center gap-1">
                {i > 0 && <span aria-hidden>/</span>}
                {c.to ? (
                  <Link to={c.to} className="hover:text-zinc-800 hover:underline">
                    {c.label}
                  </Link>
                ) : (
                  <span aria-current="page">{c.label}</span>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-zinc-950 sm:text-2xl">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-zinc-500">{subtitle}</p>}
          {meta && <div className="mt-2 flex flex-wrap items-center gap-2">{meta}</div>}
        </div>
        {actions && <div className="flex max-w-full min-w-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  )
}

export function Toolbar({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("mb-4 flex flex-wrap items-end gap-3", className)}>{children}</div>
}

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <div className="rounded-full bg-zinc-100 p-3 text-zinc-500" aria-hidden>
        {icon ?? <Inbox className="size-5" />}
      </div>
      <p className="text-sm font-semibold text-zinc-800">{title}</p>
      {description && <p className="max-w-md text-sm text-zinc-500">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

/** Uniform error block: permission errors read differently from failures. */
export function ErrorState({ error, onRetry }: { error: TexApiError | Error; onRetry?: () => void }) {
  const { t } = useTexT()
  const perm = error instanceof TexApiError && error.isPermission
  return (
    <div role="alert" className="flex flex-col items-center gap-2 px-6 py-10 text-center">
      <div className={cn("rounded-full p-3", perm ? "bg-zinc-100 text-zinc-600" : "bg-rose-50 text-rose-600")} aria-hidden>
        {perm ? <Lock className="size-5" /> : <AlertTriangle className="size-5" />}
      </div>
      <p className="text-sm font-semibold text-zinc-800">{perm ? t("core.error.permission") : t("core.error.title")}</p>
      <p className="max-w-lg text-sm whitespace-pre-line text-zinc-600">{error.message}</p>
      {onRetry && !perm && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          {t("core.action.retry")}
        </Button>
      )}
    </div>
  )
}

export function InlineError({ error }: { error?: Error | null }) {
  if (!error) return null
  return (
    <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm whitespace-pre-line text-rose-800">
      {error.message}
    </div>
  )
}

export function Notice({ tone = "info", children, title }: { tone?: "info" | "warning" | "success" | "danger"; children: ReactNode; title?: ReactNode }) {
  const tones = {
    info: "border-sky-200 bg-sky-50 text-sky-900",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
    success: "border-emerald-200 bg-emerald-50 text-emerald-900",
    danger: "border-rose-200 bg-rose-50 text-rose-900",
  }
  return (
    <div className={cn("rounded-lg border px-3 py-2 text-sm", tones[tone])} role={tone === "danger" ? "alert" : "status"}>
      {title && <p className="font-semibold">{title}</p>}
      <div>{children}</div>
    </div>
  )
}

export function Stat({
  label,
  value,
  hint,
  trend,
  className,
}: {
  label: ReactNode
  value: ReactNode
  hint?: ReactNode
  trend?: { value: string; positive?: boolean }
  className?: string
}) {
  return (
    <Card className={cn("p-4", className)}>
      <p className="text-xs font-medium tracking-wide text-zinc-500 uppercase">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-zinc-950 tabular-nums">{value}</p>
      <div className="mt-1 flex items-center gap-2 text-xs">
        {trend && <span className={trend.positive ? "text-emerald-700" : "text-rose-700"}>{trend.value}</span>}
        {hint && <span className="text-zinc-500">{hint}</span>}
      </div>
    </Card>
  )
}

/** Definition list for record detail panels. */
export function DescriptionList({ items, cols = 2 }: { items: { label: ReactNode; value: ReactNode }[]; cols?: 1 | 2 | 3 }) {
  return (
    <dl className={cn("grid grid-cols-1 gap-x-6 gap-y-3", cols === 2 && "sm:grid-cols-2", cols === 3 && "sm:grid-cols-3")}>
      {items.map((it, i) => (
        <div key={i} className="min-w-0">
          <dt className="text-xs font-medium text-zinc-500">{it.label}</dt>
          <dd className="mt-0.5 text-sm break-words text-zinc-900">{it.value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  )
}
