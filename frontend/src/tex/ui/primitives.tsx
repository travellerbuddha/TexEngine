import { forwardRef, type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode } from "react"
import { Loader2 } from "lucide-react"
import { cn } from "../../lib/utils"

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "link"
export type ButtonSize = "sm" | "md" | "lg"

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-tex-600 text-white shadow-sm hover:bg-tex-700 active:bg-tex-800 dark:text-zinc-50",
  secondary: "border border-zinc-300 bg-white text-zinc-800 shadow-sm hover:bg-zinc-50 active:bg-zinc-100",
  ghost: "text-zinc-700 hover:bg-zinc-100 active:bg-zinc-200",
  danger: "bg-rose-600 text-white shadow-sm hover:bg-rose-700 dark:text-zinc-50",
  link: "text-tex-700 underline-offset-2 hover:underline px-0",
}
const SIZE: Record<ButtonSize, string> = {
  sm: "h-8 px-2.5 text-xs gap-1.5",
  md: "h-9 px-3.5 text-sm gap-2",
  lg: "h-11 px-5 text-base gap-2",
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  icon?: ReactNode
  /** Keyboard shortcut hint shown on the button, e.g. "⌘↵". */
  shortcut?: string
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading, icon, shortcut, className, children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-lg font-medium whitespace-nowrap transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        VARIANT[variant],
        variant !== "link" && SIZE[size],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
      {shortcut && (
        <kbd className="ml-1 hidden rounded border border-current/25 px-1 font-sans text-[10px] opacity-70 sm:inline">
          {shortcut}
        </kbd>
      )}
    </button>
  )
})

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string
  icon: ReactNode
  size?: "sm" | "md"
}

/** Icon-only button: `label` is mandatory and becomes the accessible name. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, icon, size = "md", className, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex items-center justify-center rounded-lg text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900",
        "disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "size-8" : "size-9",
        className,
      )}
      {...rest}
    >
      {icon}
    </button>
  )
})

export type Tone = "neutral" | "info" | "success" | "warning" | "danger" | "brand"

const TONE: Record<Tone, string> = {
  neutral: "bg-zinc-100 text-zinc-700 ring-zinc-200",
  info: "bg-sky-50 text-sky-800 ring-sky-200",
  success: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  warning: "bg-amber-50 text-amber-900 ring-amber-200",
  danger: "bg-rose-50 text-rose-800 ring-rose-200",
  brand: "bg-tex-50 text-tex-800 ring-tex-200",
}

export function Badge({ tone = "neutral", className, children, ...rest }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset",
        TONE[tone],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  )
}

/** Status → tone for the status values used across TEX. */
export function statusTone(status?: string | null): Tone {
  switch ((status || "").toLowerCase()) {
    case "confirmed":
    case "paid":
    case "succeeded":
    case "published":
    case "active":
    case "sent":
    case "recovered":
    case "checked in":
      return "success"
    case "pending":
    case "pending payment":
    case "held":
    case "partially paid":
    case "draft":
    case "open":
    case "requested":
    case "contacted":
      return "warning"
    case "cancelled":
    case "failed":
    case "dead":
    case "withdrawn":
    case "expired":
    case "no show":
    case "unpaid":
      return "danger"
    case "superseded":
    case "archived":
    case "checked out":
    case "dismissed":
      return "neutral"
    default:
      return "info"
  }
}

export function Spinner({ className, label = "Loading" }: { className?: string; label?: string }) {
  return (
    <span role="status" className={cn("inline-flex items-center", className)}>
      <Loader2 className="size-4 animate-spin text-zinc-400" aria-hidden />
      <span className="sr-only">{label}</span>
    </span>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden className={cn("block animate-pulse rounded-md bg-zinc-200/70", className)} />
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-zinc-300 bg-zinc-50 px-1.5 py-0.5 font-sans text-[11px] font-medium text-zinc-600">
      {children}
    </kbd>
  )
}

export function VisuallyHidden({ children }: { children: ReactNode }) {
  return <span className="sr-only">{children}</span>
}
