import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react"
import { forwardRef, type ReactNode } from "react"

export { Spinner } from "./controls"

type Tone = "info" | "ok" | "warn" | "bad"

const TONES: Record<Tone, { box: string; icon: typeof Info }> = {
  info: { box: "border-brand/25 bg-brand/5 text-ink", icon: Info },
  ok: { box: "border-ok/30 bg-ok-soft text-ink", icon: CheckCircle2 },
  warn: { box: "border-warn/30 bg-warn-soft text-ink", icon: AlertTriangle },
  bad: { box: "border-bad/30 bg-bad-soft text-ink", icon: XCircle },
}

const ICON_COLOR: Record<Tone, string> = { info: "text-brand-ink", ok: "text-ok", warn: "text-warn", bad: "text-bad" }

/** Inline message. Errors are announced (role=alert); others politely (role=status). */
export const Alert = forwardRef<HTMLDivElement, {
  tone?: Tone
  title?: ReactNode
  children?: ReactNode
  actions?: ReactNode
  className?: string
  live?: boolean
}>(function Alert({ tone = "info", title, children, actions, className = "", live = true }, ref) {
  const { box, icon: Icon } = TONES[tone]
  return (
    <div
      ref={ref}
      tabIndex={-1}
      role={live ? (tone === "bad" ? "alert" : "status") : undefined}
      className={`flex gap-3 rounded-ui border px-4 py-3 outline-none ${box} ${className}`}
    >
      <Icon className={`mt-0.5 size-5 flex-none ${ICON_COLOR[tone]}`} aria-hidden />
      <div className="min-w-0 flex-1 text-sm">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={title ? "mt-0.5 text-soft" : "text-soft"}>{children}</div>}
        {actions && <div className="mt-3 flex flex-wrap gap-2">{actions}</div>}
      </div>
    </div>
  )
})

export interface FieldError {
  id: string
  message: string
}

/** Error summary shown above a form after a failed submit (WCAG 3.3.1): each item
 * links to its field. Receives focus so screen readers announce it. */
export const ErrorSummary = forwardRef<HTMLDivElement, { title: string; errors: FieldError[] }>(function ErrorSummary(
  { title, errors },
  ref,
) {
  if (!errors.length) return null
  return (
    <div ref={ref} tabIndex={-1} role="alert" className="rounded-ui border-2 border-bad bg-bad-soft px-4 py-3 outline-none" aria-labelledby="bk-err-title">
      <p id="bk-err-title" className="font-semibold text-bad">
        {title}
      </p>
      <ul className="mt-1 list-disc pl-5 text-sm">
        {errors.map((e) => (
          <li key={e.id}>
            <a
              href={`#${e.id}`}
              className="inline-block min-h-6 py-0.5 text-bad underline underline-offset-2"
              onClick={(ev) => {
                ev.preventDefault()
                const el = document.getElementById(e.id)
                el?.focus()
                el?.scrollIntoView({ block: "center" })
              }}
            >
              {e.message}
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
})

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-ui bg-line/70 ${className}`} aria-hidden />
}

export function EmptyState({ icon, title, children, actions }: { icon?: ReactNode; title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="bk-card flex flex-col items-center px-6 py-10 text-center">
      {icon && <div className="mb-3 text-muted">{icon}</div>}
      <h2 className="text-lg">{title}</h2>
      {children && <div className="mt-1 max-w-md text-sm text-muted">{children}</div>}
      {actions && <div className="mt-5 flex flex-wrap justify-center gap-2">{actions}</div>}
    </div>
  )
}
