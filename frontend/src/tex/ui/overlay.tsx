import { useEffect, useId, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { X } from "lucide-react"
import { cn } from "../../lib/utils"
import { Button, IconButton } from "./primitives"
import { Field, Textarea } from "./form"
import { InlineError } from "./layout"
import { useTexT } from "../i18n"

const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'

/** Focus trap + Esc + restore focus on close (WAI-ARIA dialog pattern). */
function useModal(open: boolean, onClose: () => void) {
  const panel = useRef<HTMLDivElement>(null)
  // keep the latest close handler without re-running the effect: re-running would
  // steal focus back to the first field whenever a parent re-renders
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    const el = panel.current
    const first = el?.querySelector<HTMLElement>("[data-autofocus]") ?? el?.querySelector<HTMLElement>(FOCUSABLE)
    ;(first ?? el)?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation()
        closeRef.current()
      }
      if (e.key !== "Tab" || !el) return
      const items = Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((n) => n.offsetParent !== null)
      if (!items.length) return
      const a = items[0]
      const z = items[items.length - 1]
      if (e.shiftKey && document.activeElement === a) {
        e.preventDefault()
        z.focus()
      } else if (!e.shiftKey && document.activeElement === z) {
        e.preventDefault()
        a.focus()
      }
    }
    document.addEventListener("keydown", onKey, true)
    const overflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.removeEventListener("keydown", onKey, true)
      document.body.style.overflow = overflow
      previous?.focus?.()
    }
  }, [open])
  return panel
}

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  description?: ReactNode
  children?: ReactNode
  footer?: ReactNode
  size?: "sm" | "md" | "lg" | "xl"
}) {
  const panel = useModal(open, onClose)
  const titleId = useId()
  const descId = useId()
  const { t } = useTexT()
  if (!open) return null
  const width = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl", xl: "max-w-4xl" }[size]
  return createPortal(
    <div className="tex-root fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4">
      <div className="absolute inset-0 bg-black/40" aria-hidden onClick={onClose} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        className={cn(
          "relative flex max-h-[92vh] w-full flex-col rounded-t-2xl bg-white shadow-tex-pop sm:rounded-2xl",
          width,
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-zinc-100 px-5 py-4">
          <div>
            <h2 id={titleId} className="text-base font-semibold text-zinc-950">
              {title}
            </h2>
            {description && (
              <p id={descId} className="mt-0.5 text-sm text-zinc-500">
                {description}
              </p>
            )}
          </div>
          <IconButton label={t("core.action.close")} icon={<X className="size-4" />} size="sm" onClick={onClose} />
        </div>
        <div className="overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-zinc-100 px-5 py-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}

export function Drawer({
  open,
  onClose,
  title,
  children,
  footer,
  width = "md",
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  children?: ReactNode
  footer?: ReactNode
  width?: "md" | "lg" | "xl"
}) {
  const panel = useModal(open, onClose)
  const titleId = useId()
  const { t } = useTexT()
  if (!open) return null
  const w = { md: "sm:max-w-md", lg: "sm:max-w-2xl", xl: "sm:max-w-4xl" }[width]
  return createPortal(
    <div className="tex-root fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" aria-hidden onClick={onClose} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cn("relative flex h-full w-full flex-col bg-white shadow-tex-pop", w)}
      >
        <div className="flex items-center justify-between gap-4 border-b border-zinc-100 px-5 py-3.5">
          <h2 id={titleId} className="text-base font-semibold text-zinc-950">
            {title}
          </h2>
          <IconButton label={t("core.action.close")} icon={<X className="size-4" />} size="sm" onClick={onClose} />
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-zinc-100 px-5 py-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}

/** Confirmation that can require a written reason (audited actions). */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  body,
  confirmLabel,
  tone = "primary",
  requireReason,
  reasonLabel,
}: {
  open: boolean
  onClose: () => void
  onConfirm: (reason: string) => Promise<unknown> | void
  title: ReactNode
  body?: ReactNode
  confirmLabel?: ReactNode
  tone?: "primary" | "danger"
  requireReason?: boolean
  reasonLabel?: ReactNode
}) {
  const { t } = useTexT()
  const [reason, setReason] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  useEffect(() => {
    if (open) {
      setReason("")
      setError(null)
    }
  }, [open])
  const ok = !requireReason || reason.trim().length > 2
  return (
    <Dialog
      open={open}
      onClose={busy ? () => undefined : onClose}
      title={title}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {t("core.action.cancel")}
          </Button>
          <Button
            variant={tone === "danger" ? "danger" : "primary"}
            loading={busy}
            disabled={!ok}
            onClick={async () => {
              setBusy(true)
              setError(null)
              try {
                await onConfirm(reason.trim())
                onClose()
              } catch (e) {
                setError(e as Error)
              } finally {
                setBusy(false)
              }
            }}
          >
            {confirmLabel ?? t("core.action.confirm")}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {body && <div className="text-sm text-zinc-700">{body}</div>}
        {requireReason && (
          <Field label={reasonLabel ?? t("core.field.reason")} required hint={t("core.hint.reason_audited")}>
            <Textarea value={reason} onChange={(e) => setReason(e.target.value)} data-autofocus />
          </Field>
        )}
        <InlineError error={error} />
      </div>
    </Dialog>
  )
}
