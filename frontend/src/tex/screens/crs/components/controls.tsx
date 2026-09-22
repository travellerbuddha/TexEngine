// Small controls used across the CRS, Call Center and Reservations screens. Built
// here first (UI_WORKSTREAMS: area components before promotion to tex/ui).
import { useState, type InputHTMLAttributes, type ReactNode } from "react"
import { ChevronRight, Minus, Plus, X } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { useTexT } from "../../../i18n"

const BOX =
  "rounded-lg border border-zinc-300 bg-white text-sm text-zinc-900 shadow-sm transition-colors hover:border-zinc-400 " +
  "aria-[invalid=true]:border-rose-500"

/** Integer input with − / + affordances. Keyboard: type, or ↑/↓ in the field. */
export function NumberStepper({
  value,
  min,
  max,
  onChange,
  decLabel,
  incLabel,
  className,
  ...rest
}: Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "min" | "max"> & {
  value: number
  min: number
  max: number
  onChange: (v: number) => void
  decLabel: string
  incLabel: string
}) {
  const clamp = (n: number) => Math.min(max, Math.max(min, n))
  return (
    <div className={cn("inline-flex h-9 items-stretch", BOX, className)}>
      <button
        type="button"
        tabIndex={-1}
        aria-label={decLabel}
        title={decLabel}
        disabled={value <= min}
        onClick={() => onChange(clamp(value - 1))}
        className="grid w-8 place-items-center rounded-l-lg text-zinc-600 hover:bg-zinc-100 disabled:opacity-40"
      >
        <Minus className="size-3.5" aria-hidden />
      </button>
      <input
        type="number"
        inputMode="numeric"
        min={min}
        max={max}
        value={value}
        onChange={(e) => {
          const n = parseInt(e.target.value, 10)
          if (!Number.isNaN(n)) onChange(clamp(n))
        }}
        className="w-10 border-x border-zinc-200 bg-transparent text-center tabular-nums [appearance:textfield] focus:outline-none [&::-webkit-inner-spin-button]:appearance-none"
        {...rest}
      />
      <button
        type="button"
        tabIndex={-1}
        aria-label={incLabel}
        title={incLabel}
        disabled={value >= max}
        onClick={() => onChange(clamp(value + 1))}
        className="grid w-8 place-items-center rounded-r-lg text-zinc-600 hover:bg-zinc-100 disabled:opacity-40"
      >
        <Plus className="size-3.5" aria-hidden />
      </button>
    </div>
  )
}

/** Promo / coupon codes as chips. Enter, comma or space adds; Backspace removes the last. */
export function CodeChips({
  value,
  onChange,
  placeholder,
  ...rest
}: Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> & {
  value: string[]
  onChange: (v: string[]) => void
}) {
  const { t } = useTexT()
  const [draft, setDraft] = useState("")
  const add = () => {
    const c = draft.trim().toUpperCase()
    if (c && !value.includes(c)) onChange([...value, c])
    setDraft("")
  }
  return (
    <div className={cn("flex min-h-9 flex-wrap items-center gap-1 px-1.5 py-1", BOX)}>
      {value.map((c) => (
        <span key={c} className="inline-flex items-center gap-0.5 rounded-md bg-tex-50 py-0.5 pr-0.5 pl-1.5 text-xs font-semibold text-tex-800">
          {c}
          <button
            type="button"
            className="rounded p-0.5 hover:bg-tex-100"
            aria-label={t("crs.promo.remove", { code: c })}
            onClick={() => onChange(value.filter((x) => x !== c))}
          >
            <X className="size-3" aria-hidden />
          </button>
        </span>
      ))}
      <input
        value={draft}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => setDraft(e.target.value.toUpperCase().replace(/[^A-Z0-9_-]/g, ""))}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === "," || e.key === " ") && draft.trim()) {
            e.preventDefault()
            add()
          } else if (e.key === "Backspace" && !draft && value.length) onChange(value.slice(0, -1))
        }}
        onBlur={add}
        placeholder={value.length ? undefined : placeholder}
        className="h-7 min-w-20 flex-1 rounded bg-transparent px-1 text-sm uppercase placeholder:normal-case placeholder:text-zinc-400"
        {...rest}
      />
    </div>
  )
}

/** Native disclosure (keyboard + screen reader support for free). */
export function Disclosure({
  summary,
  children,
  className,
  defaultOpen,
}: {
  summary: ReactNode
  children: ReactNode
  className?: string
  defaultOpen?: boolean
}) {
  return (
    <details className={cn("group", className)} open={defaultOpen}>
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded text-xs font-medium text-tex-700 hover:underline [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" aria-hidden />
        {summary}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  )
}

/** Label / value row for compact price and fact lists. */
export function Row({ label, value, strong, className }: { label: ReactNode; value: ReactNode; strong?: boolean; className?: string }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-3 py-0.5 text-sm", strong && "font-semibold text-zinc-950", className)}>
      <span className={cn("min-w-0", strong ? "text-zinc-900" : "text-zinc-600")}>{label}</span>
      <span className="shrink-0 text-right tabular-nums">{value}</span>
    </div>
  )
}

/** Polite live region for status announcements (search done, quote ready, booked). */
export function LiveRegion({ message }: { message: string }) {
  return (
    <p aria-live="polite" role="status" className="sr-only">
      {message}
    </p>
  )
}
