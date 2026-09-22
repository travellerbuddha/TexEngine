import { Loader2, Minus, Plus } from "lucide-react"
import {
  cloneElement,
  forwardRef,
  isValidElement,
  useId,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactElement,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react"

type Variant = "primary" | "secondary" | "ghost" | "danger"

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: "sm" | "md" | "lg"
  busy?: boolean
  block?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", busy, block, className = "", children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={`bk-btn bk-btn-${variant} ${size === "lg" ? "bk-btn-lg" : size === "sm" ? "bk-btn-sm" : ""} ${block ? "w-full" : ""} ${className}`}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
})

export function Spinner({ label, className = "" }: { label?: string; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 text-muted ${className}`} role="status">
      <Loader2 className="size-5 animate-spin" aria-hidden />
      {label ? <span>{label}</span> : <span className="sr-only">…</span>}
    </span>
  )
}

interface FieldProps {
  label: ReactNode
  hint?: ReactNode
  error?: string | null
  children: ReactElement<{ id?: string; "aria-describedby"?: string; "aria-invalid"?: boolean }>
  className?: string
  optional?: string
  id?: string
}

/** Label + control + hint + error, wired with ids for assistive technology. */
export function Field({ label, hint, error, children, className = "", optional, id: forcedId }: FieldProps) {
  const autoId = useId()
  const id = forcedId ?? children.props.id ?? autoId
  const hintId = hint ? `${id}-hint` : undefined
  const errId = error ? `${id}-err` : undefined
  const describedBy = [children.props["aria-describedby"], hintId, errId].filter(Boolean).join(" ") || undefined
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 flex items-baseline justify-between gap-2 text-sm font-medium text-soft">
        <span>{label}</span>
        {optional && <span className="text-xs font-normal text-muted">{optional}</span>}
      </label>
      {isValidElement(children) &&
        cloneElement(children, { id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      {hint && !error && (
        <p id={hintId} className="mt-1 text-xs text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={errId} className="mt-1 text-sm font-medium text-bad">
          {error}
        </p>
      )}
    </div>
  )
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className = "", ...rest },
  ref,
) {
  return <input ref={ref} className={`bk-input ${className}`} {...rest} />
})

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className = "", children, ...rest },
  ref,
) {
  return (
    <select ref={ref} className={`bk-input ${className}`} {...rest}>
      {children}
    </select>
  )
})

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className = "", ...rest },
  ref,
) {
  return <textarea ref={ref} className={`bk-input min-h-24 ${className}`} {...rest} />
})

export function Checkbox({
  label,
  hint,
  checked,
  onChange,
  id: forcedId,
  error,
  required,
}: {
  label: ReactNode
  hint?: ReactNode
  checked: boolean
  onChange: (v: boolean) => void
  id?: string
  error?: string | null
  required?: boolean
}) {
  const auto = useId()
  const id = forcedId ?? auto
  return (
    <div>
      <div className="flex items-start gap-3">
        <input
          id={id}
          type="checkbox"
          className="bk-check"
          checked={checked}
          required={required}
          aria-invalid={error ? true : undefined}
          aria-describedby={[hint ? `${id}-hint` : "", error ? `${id}-err` : ""].filter(Boolean).join(" ") || undefined}
          onChange={(e) => onChange(e.target.checked)}
        />
        <label htmlFor={id} className="text-sm leading-6 text-soft">
          {label}
          {hint && (
            <span id={`${id}-hint`} className="block text-xs leading-5 text-muted">
              {hint}
            </span>
          )}
        </label>
      </div>
      {error && (
        <p id={`${id}-err`} role="alert" className="mt-1 ml-8 text-sm font-medium text-bad">
          {error}
        </p>
      )}
    </div>
  )
}

/** −/+ counter with a live value; buttons are 40px targets. */
export function Counter({
  label,
  sublabel,
  value,
  min,
  max,
  onChange,
  decLabel,
  incLabel,
}: {
  label: string
  sublabel?: string
  value: number
  min: number
  max: number
  onChange: (n: number) => void
  decLabel: string
  incLabel: string
}) {
  const id = useId()
  return (
    <div className="flex items-center justify-between gap-4 py-2" role="group" aria-labelledby={`${id}-l`}>
      <div>
        <div id={`${id}-l`} className="font-medium">
          {label}
        </div>
        {sublabel && <div className="text-xs text-muted">{sublabel}</div>}
      </div>
      <div className="flex items-center gap-3">
        <button
          type="button"
          className="grid size-10 place-items-center rounded-full border-[1.5px] border-line-strong text-soft hover:border-ink disabled:opacity-40 disabled:hover:border-line-strong"
          onClick={() => onChange(Math.max(min, value - 1))}
          disabled={value <= min}
          aria-label={decLabel}
        >
          <Minus className="size-4" aria-hidden />
        </button>
        <output className="w-6 text-center text-lg font-semibold tabular-nums" aria-live="polite">
          {value}
        </output>
        <button
          type="button"
          className="grid size-10 place-items-center rounded-full border-[1.5px] border-line-strong text-soft hover:border-ink disabled:opacity-40 disabled:hover:border-line-strong"
          onClick={() => onChange(Math.min(max, value + 1))}
          disabled={value >= max}
          aria-label={incLabel}
        >
          <Plus className="size-4" aria-hidden />
        </button>
      </div>
    </div>
  )
}

export function Badge({ tone = "neutral", children, className = "" }: { tone?: "neutral" | "ok" | "warn" | "bad" | "brand" | "accent"; children: ReactNode; className?: string }) {
  const tones: Record<string, string> = {
    neutral: "bg-sunken text-soft",
    ok: "bg-ok-soft text-ok",
    warn: "bg-warn-soft text-warn",
    bad: "bg-bad-soft text-bad",
    brand: "bg-brand/10 text-brand-ink",
    accent: "bg-accent text-on-accent",
  }
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${tones[tone]} ${className}`}>
      {children}
    </span>
  )
}
