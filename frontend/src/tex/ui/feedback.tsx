import { createContext, useCallback, useContext, useRef, useState, type ReactNode, type KeyboardEvent } from "react"
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react"
import { cn } from "../../lib/utils"

type ToastTone = "success" | "error" | "info" | "warning"
interface Toast {
  id: number
  tone: ToastTone
  message: ReactNode
}

const ToastCtx = createContext<(tone: ToastTone, message: ReactNode) => void>(() => undefined)

/** How long a toast stays: 4.5 s (an error or a warning 8 s), longer for a long text, about 60 ms a character up
 * to 15 s, so a sentence that teaches something (the ladder's "Copy, paste and fill work in the room
 * price matrix…", some 190 characters in German) can be read before it goes (S16 re-review 3). */
function toastDuration(tone: ToastTone, message: ReactNode): number {
  const base = tone === "error" || tone === "warning" ? 8000 : 4500
  return typeof message === "string" ? Math.max(base, Math.min(15000, message.length * 60)) : base
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const seq = useRef(0)
  const push = useCallback((tone: ToastTone, message: ReactNode) => {
    const id = ++seq.current
    setToasts((t) => [...t, { id, tone, message }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), toastDuration(tone, message))
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed inset-x-3 top-3 z-[60] flex flex-col gap-2 sm:inset-x-auto sm:top-auto sm:right-4 sm:bottom-4 sm:w-80"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.tone === "error" ? "alert" : "status"}
            className={cn(
              "pointer-events-auto flex items-start gap-2 rounded-lg border bg-white px-3 py-2.5 text-sm shadow-tex-pop",
              t.tone === "error" ? "border-rose-200" : t.tone === "success" ? "border-emerald-200" : t.tone === "warning" ? "border-amber-200" : "border-zinc-200",
            )}
          >
            {t.tone === "success" ? (
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-hidden />
            ) : t.tone === "error" ? (
              <XCircle className="mt-0.5 size-4 shrink-0 text-rose-600" aria-hidden />
            ) : t.tone === "warning" ? (
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" aria-hidden />
            ) : (
              <Info className="mt-0.5 size-4 shrink-0 text-sky-600" aria-hidden />
            )}
            <div className="text-zinc-800">{t.message}</div>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

export function useToast() {
  const push = useContext(ToastCtx)
  return {
    success: (m: ReactNode) => push("success", m),
    error: (m: ReactNode) => push("error", m),
    info: (m: ReactNode) => push("info", m),
    warning: (m: ReactNode) => push("warning", m),
  }
}

export interface TabDef {
  id: string
  label: ReactNode
  badge?: ReactNode
}

/** WAI-ARIA tabs with roving focus (arrow keys, Home/End). */
export function Tabs({
  tabs,
  value,
  onChange,
  label,
  className,
}: {
  tabs: TabDef[]
  value: string
  onChange: (id: string) => void
  label: string
  className?: string
}) {
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = tabs.findIndex((t) => t.id === value)
    let n = i
    if (e.key === "ArrowRight") n = (i + 1) % tabs.length
    else if (e.key === "ArrowLeft") n = (i - 1 + tabs.length) % tabs.length
    else if (e.key === "Home") n = 0
    else if (e.key === "End") n = tabs.length - 1
    else return
    e.preventDefault()
    onChange(tabs[n].id)
    ;(e.currentTarget.querySelector(`[data-tab="${tabs[n].id}"]`) as HTMLElement | null)?.focus()
  }
  return (
    <div role="tablist" aria-label={label} onKeyDown={onKey} className={cn("flex gap-1 overflow-x-auto border-b border-zinc-200", className)}>
      {tabs.map((t) => {
        const active = t.id === value
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            data-tab={t.id}
            id={`tab-${t.id}`}
            aria-selected={active}
            aria-controls={`panel-${t.id}`}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(t.id)}
            className={cn(
              "-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors",
              active ? "border-tex-600 text-tex-700" : "border-transparent text-zinc-600 hover:text-zinc-900",
            )}
          >
            {t.label}
            {t.badge}
          </button>
        )
      })}
    </div>
  )
}

export function TabPanel({ id, children, className }: { id: string; children: ReactNode; className?: string }) {
  return (
    <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`} className={className}>
      {children}
    </div>
  )
}
