import {
  cloneElement,
  forwardRef,
  isValidElement,
  useId,
  type InputHTMLAttributes,
  type ReactElement,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react"
import { cn } from "../../lib/utils"

const CONTROL =
  "block w-full rounded-lg border border-zinc-300 bg-white text-sm text-zinc-900 shadow-sm placeholder:text-zinc-400 " +
  "transition-colors hover:border-zinc-400 focus:border-tex-500 focus:outline-none focus:ring-2 focus:ring-tex-500/30 " +
  "disabled:cursor-not-allowed disabled:bg-zinc-50 disabled:text-zinc-500 aria-[invalid=true]:border-rose-500 aria-[invalid=true]:ring-rose-500/20"

export interface FieldProps {
  label: ReactNode
  hint?: ReactNode
  error?: ReactNode
  required?: boolean
  className?: string
  /** A single control; Field wires id, aria-describedby and aria-invalid. */
  children: ReactElement<Record<string, unknown>>
  inline?: boolean
}

/** Label + control + hint/error with correct ARIA wiring (WCAG 1.3.1, 3.3.1). */
export function Field({ label, hint, error, required, className, children, inline }: FieldProps) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  const errId = error ? `${id}-err` : undefined
  const own = isValidElement(children) ? children.props : {}
  const control = isValidElement(children)
    ? cloneElement(children, {
        id: (own.id as string | undefined) ?? id,
        // merge with the control's own ARIA instead of overwriting it
        "aria-describedby":
          [own["aria-describedby"] as string | undefined, hintId, errId].filter(Boolean).join(" ") || undefined,
        "aria-invalid": error ? true : (own["aria-invalid"] as boolean | undefined),
        "aria-required": required || (own["aria-required"] as boolean | undefined),
      })
    : children
  const controlId = (isValidElement(children) && (children.props.id as string | undefined)) || id
  return (
    <div className={cn(inline ? "flex items-center gap-3" : "space-y-1.5", className)}>
      <label htmlFor={controlId} className="block text-sm font-medium text-zinc-800">
        {label}
        {required && (
          <span className="ml-0.5 text-rose-600" aria-hidden>
            *
          </span>
        )}
      </label>
      {control}
      {hint && !error && (
        <p id={hintId} className="text-xs text-zinc-500">
          {hint}
        </p>
      )}
      {error && (
        <p id={errId} className="text-xs font-medium text-rose-700" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} className={cn(CONTROL, "h-9 px-3", className)} {...rest} />
})

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, rows = 3, ...rest },
  ref,
) {
  return <textarea ref={ref} rows={rows} className={cn(CONTROL, "px-3 py-2", className)} {...rest} />
})

export interface Option {
  value: string
  label: string
  disabled?: boolean
}

export const Select = forwardRef<
  HTMLSelectElement,
  SelectHTMLAttributes<HTMLSelectElement> & { options: Option[]; placeholder?: string }
>(function Select({ className, options, placeholder, ...rest }, ref) {
  return (
    <select ref={ref} className={cn(CONTROL, "h-9 pr-8 pl-3", className)} {...rest}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled}>
          {o.label}
        </option>
      ))}
    </select>
  )
})

/** Decimal input that keeps the typed string (money never becomes a float). */
export const DecimalInput = forwardRef<
  HTMLInputElement,
  Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> & {
    value: string
    onValueChange: (v: string) => void
    decimals?: number
    allowNegative?: boolean
    suffix?: ReactNode
  }
>(function DecimalInput({ value, onValueChange, decimals = 2, allowNegative, suffix, className, ...rest }, ref) {
  const re = new RegExp(`^${allowNegative ? "-?" : ""}\\d*(\\.\\d{0,${decimals}})?$`)
  return (
    <div className="relative">
      <input
        ref={ref}
        inputMode="decimal"
        autoComplete="off"
        value={value}
        onChange={(e) => {
          const v = e.target.value.replace(",", ".")
          if (v === "" || re.test(v)) onValueChange(v)
        }}
        className={cn(CONTROL, "h-9 px-3 text-right tabular-nums", suffix ? "pr-12" : "", className)}
        {...rest}
      />
      {suffix && (
        <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-zinc-500">
          {suffix}
        </span>
      )}
    </div>
  )
})

export function Checkbox({
  label,
  className,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }) {
  return (
    <label className={cn("inline-flex cursor-pointer items-center gap-2 text-sm text-zinc-800", className)}>
      <input type="checkbox" className="size-4 rounded border-zinc-300 text-tex-600 accent-tex-600" {...rest} />
      {label}
    </label>
  )
}

export function Switch({
  checked,
  onChange,
  label,
  disabled,
  description,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: ReactNode
  disabled?: boolean
  description?: ReactNode
}) {
  const id = useId()
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <label htmlFor={id} className="text-sm font-medium text-zinc-800">
          {label}
        </label>
        {description && <p className="text-xs text-zinc-500">{description}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-50",
          checked ? "bg-tex-600" : "bg-zinc-300",
        )}
      >
        <span
          className={cn(
            "inline-block size-5 rounded-full bg-white shadow transition-transform",
            checked ? "translate-x-5.5" : "translate-x-0.5",
          )}
        />
      </button>
    </div>
  )
}

/** Segmented control (radio group) — arrow keys move, WAI-ARIA radiogroup. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  size = "md",
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: ReactNode }[]
  label: string
  size?: "sm" | "md"
}) {
  const idx = options.findIndex((o) => o.value === value)
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="inline-flex max-w-full overflow-x-auto rounded-lg border border-zinc-300 bg-zinc-50 p-0.5"
      onKeyDown={(e) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return
        e.preventDefault()
        const n = (idx + (e.key === "ArrowRight" ? 1 : -1) + options.length) % options.length
        onChange(options[n].value)
        ;(e.currentTarget.querySelectorAll("button")[n] as HTMLButtonElement | undefined)?.focus()
      }}
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          tabIndex={o.value === value ? 0 : -1}
          onClick={() => onChange(o.value)}
          className={cn(
            "shrink-0 rounded-md font-medium whitespace-nowrap transition-colors",
            size === "sm" ? "px-2 py-1 text-xs" : "px-3 py-1.5 text-sm",
            o.value === value ? "bg-white text-zinc-900 shadow-sm" : "text-zinc-600 hover:text-zinc-900",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function FormGrid({ children, cols = 2, className }: { children: ReactNode; cols?: 1 | 2 | 3 | 4; className?: string }) {
  const c = { 1: "", 2: "sm:grid-cols-2", 3: "sm:grid-cols-2 lg:grid-cols-3", 4: "sm:grid-cols-2 lg:grid-cols-4" }[cols]
  return <div className={cn("grid grid-cols-1 gap-4", c, className)}>{children}</div>
}
