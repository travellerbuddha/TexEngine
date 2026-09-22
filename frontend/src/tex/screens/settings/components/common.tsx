// Small building blocks shared by the back-office admin areas (Settings, Connect,
// Booking Engine, Reports). Candidates for promotion to tex/ui by the integrator.
import { useEffect, useRef, useState, type ReactNode } from "react"
import { NavLink } from "react-router-dom"
import { Check, Copy } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { useTexT } from "../../../i18n"
import { Button } from "../../../ui"

export interface SubNavItem {
  to: string
  label: ReactNode
  end?: boolean
}

/** Route-level sub-navigation for an area (links, not ARIA tabs: each entry is a page). */
export function SubNav({ items, label }: { items: SubNavItem[]; label: string }) {
  if (items.length < 2) return null
  return (
    <nav aria-label={label} className="-mt-1 mb-5 flex gap-1 overflow-x-auto border-b border-zinc-200">
      {items.map((i) => (
        <NavLink
          key={i.to}
          to={i.to}
          end={i.end}
          className={({ isActive }) =>
            cn(
              "-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors",
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

async function writeClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // insecure context (plain http dev hosts) or permission denied: legacy fallback
    const ta = document.createElement("textarea")
    ta.value = text
    ta.setAttribute("readonly", "")
    ta.style.position = "fixed"
    ta.style.opacity = "0"
    document.body.appendChild(ta)
    ta.select()
    let ok = false
    try {
      ok = document.execCommand("copy")
    } catch {
      ok = false
    }
    ta.remove()
    return ok
  }
}

/** Copy-to-clipboard button; announces the result politely. `label` names what is copied. */
export function CopyButton({ value, label, size = "sm" }: { value: string; label?: string; size?: "sm" | "md" }) {
  const { t } = useTexT()
  const [state, setState] = useState<"idle" | "done" | "failed">("idle")
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  return (
    <>
      <Button
        variant="secondary"
        size={size}
        icon={state === "done" ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
        aria-label={label ? `${t("core.action.copy")}: ${label}` : undefined}
        onClick={async () => {
          const ok = await writeClipboard(value)
          setState(ok ? "done" : "failed")
          window.clearTimeout(timer.current)
          timer.current = window.setTimeout(() => setState("idle"), 2000)
        }}
      >
        {state === "done" ? t("core.action.copied") : t("core.action.copy")}
      </Button>
      <span className="sr-only" aria-live="polite">
        {state === "done" ? t("core.action.copied") : state === "failed" ? t("settings.copy_failed") : ""}
      </span>
    </>
  )
}

/** Read-only code/value with a copy button (snippets, DNS records, tokens). */
export function CodeBlock({ value, label, wrap = true }: { value: string; label: string; wrap?: boolean }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-zinc-600">{label}</p>
        <CopyButton value={value} label={label} />
      </div>
      <pre
        className={cn(
          "overflow-x-auto rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 font-mono text-xs text-zinc-800",
          wrap ? "break-all whitespace-pre-wrap" : "whitespace-pre",
        )}
      >
        {value}
      </pre>
    </div>
  )
}

/** Warn before closing the tab while a form has unsaved changes. */
export function useUnsavedWarning(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return
    const on = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ""
    }
    window.addEventListener("beforeunload", on)
    return () => window.removeEventListener("beforeunload", on)
  }, [dirty])
}

/** A titled group of fields inside a form card. */
export function FormSection({
  title,
  description,
  children,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cn("space-y-4", className)}>
      <div>
        <h3 className="text-sm font-semibold text-zinc-900">{title}</h3>
        {description && <p className="mt-0.5 text-xs text-zinc-500">{description}</p>}
      </div>
      {children}
    </section>
  )
}

/** Checkbox group with a real <fieldset>/<legend> (WCAG 1.3.1). */
export function CheckboxGroup({
  legend,
  hint,
  options,
  value,
  onChange,
  error,
}: {
  legend: ReactNode
  hint?: ReactNode
  options: { value: string; label: ReactNode }[]
  value: string[]
  onChange: (v: string[]) => void
  error?: ReactNode
}) {
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium text-zinc-800">{legend}</legend>
      {hint && <p className="text-xs text-zinc-500">{hint}</p>}
      <div className="flex flex-wrap gap-2">
        {options.map((o) => {
          const on = value.includes(o.value)
          return (
            <label
              key={o.value}
              className={cn(
                "inline-flex cursor-pointer items-center gap-2 rounded-lg border px-2.5 py-1.5 text-sm transition-colors",
                on ? "border-tex-300 bg-tex-50 text-tex-800" : "border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-50",
              )}
            >
              <input
                type="checkbox"
                className="size-4 accent-tex-600"
                checked={on}
                onChange={(e) => onChange(e.target.checked ? [...value, o.value] : value.filter((x) => x !== o.value))}
              />
              {o.label}
            </label>
          )
        })}
      </div>
      {error && (
        <p className="text-xs font-medium text-rose-700" role="alert">
          {error}
        </p>
      )}
    </fieldset>
  )
}
