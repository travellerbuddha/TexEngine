import { useEffect, useId, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { X } from "lucide-react"
import { cn } from "../../lib/utils"
import { Button, IconButton } from "./primitives"
import { Field, Textarea } from "./form"
import { InlineError } from "./layout"
import { useTexT } from "../i18n"
import { tabbables, useIsPhone } from "./popover"

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

/**
 * A side drawer. Modal by default (backdrop, focus trap, Esc, focus restored). With `modal={false}`
 * it is a non-blocking side panel (PRICING_WORKSPACE_UX.md §1.3, §3.8: "2 non-blocking drawers"):
 * role="dialog" without aria-modal, no backdrop, no focus trap and no scroll lock, so the page stays
 * usable beside it. Focus moves into it on open and back to the opener on close (unless the user
 * put it elsewhere); Escape closes it while the focus is inside it (a Popover, Menu or tooltip
 * opened in it closes first: their Escape runs earlier, at the window). Tab leaves it as if it sat
 * right after its opener: Shift+Tab from its first control goes to the opener, Tab from its last to
 * what follows the opener (S16 review; it is portaled to the end of the page).
 *
 * On a phone (below `sm`) the panel covers the whole page, so there it is the modal drawer: a page
 * under it that stayed in the tab order and the accessibility tree could not be seen (S16 review).
 * On a wide desktop (a md panel from 80rem, lg from 96rem, xl from 120rem: where a few price columns
 * still fit beside it) it sits beside the page instead of over it: the page (`.tex-page`, the
 * shell's content column) gives up the panel's width while it is open, so what the panel is used
 * with (the price matrix beside the Price test) stays on screen (S16 re-review; tex.css).
 */
export function Drawer({
  open,
  onClose,
  title,
  children,
  footer,
  width = "md",
  modal = true,
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  children?: ReactNode
  footer?: ReactNode
  width?: "md" | "lg" | "xl"
  modal?: boolean
}) {
  const phone = useIsPhone()
  if (!modal && !phone) return <SidePanel open={open} onClose={onClose} title={title} footer={footer} width={width}>{children}</SidePanel>
  return <ModalDrawer open={open} onClose={onClose} title={title} footer={footer} width={width}>{children}</ModalDrawer>
}

const DRAWER_WIDTH = { md: "sm:max-w-md", lg: "sm:max-w-2xl", xl: "sm:max-w-4xl" }

type DrawerProps = { open: boolean; onClose: () => void; title: ReactNode; children?: ReactNode; footer?: ReactNode; width: "md" | "lg" | "xl" }

function DrawerBody({ titleId, title, onClose, children, footer }: { titleId: string; title: ReactNode; onClose: () => void; children?: ReactNode; footer?: ReactNode }) {
  const { t } = useTexT()
  return (
    <>
      <div className="flex items-center justify-between gap-4 border-b border-zinc-100 px-5 py-3.5">
        <h2 id={titleId} className="text-base font-semibold text-zinc-950">
          {title}
        </h2>
        <IconButton label={t("core.action.close")} icon={<X className="size-4" />} size="sm" onClick={onClose} />
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
      {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-zinc-100 px-5 py-3">{footer}</div>}
    </>
  )
}

function ModalDrawer({ open, onClose, title, children, footer, width }: DrawerProps) {
  const panel = useModal(open, onClose)
  const titleId = useId()
  if (!open) return null
  return createPortal(
    <div className="tex-root fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" aria-hidden onClick={onClose} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cn("relative flex h-full w-full flex-col bg-white shadow-tex-pop", DRAWER_WIDTH[width])}
      >
        <DrawerBody titleId={titleId} title={title} onClose={onClose} footer={footer}>
          {children}
        </DrawerBody>
      </div>
    </div>,
    document.body,
  )
}

/** The first element Tab reaches after `from` in the page, outside `skip`, or null. */
function nextTabbable(from: HTMLElement, skip: HTMLElement): HTMLElement | null {
  for (const el of tabbables(document.body)) {
    if (skip.contains(el) || from.contains(el)) continue
    if (from.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) return el
  }
  return null
}

// the widths of the side panels open now: the page gives up the widest (html[data-side-panel-open],
// tex.css; not data-side-panel, which marks the panel itself)
const openPanels: DrawerProps["width"][] = []
function syncSidePanels() {
  const order = ["md", "lg", "xl"] as const
  const widest = openPanels.reduce<DrawerProps["width"] | "">((w, x) => (w === "" || order.indexOf(x) > order.indexOf(w) ? x : w), "")
  if (widest) document.documentElement.dataset.sidePanelOpen = widest
  else delete document.documentElement.dataset.sidePanelOpen
}

function SidePanel({ open, onClose, title, children, footer, width }: DrawerProps) {
  const panel = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    if (!open) return
    openPanels.push(width)
    syncSidePanels()
    return () => {
      openPanels.splice(openPanels.indexOf(width), 1)
      syncSidePanels()
    }
  }, [open, width])
  useEffect(() => {
    const el = panel.current
    if (!open || !el) return
    const opener = document.activeElement as HTMLElement | null
    const first = el.querySelector<HTMLElement>("[data-autofocus]") ?? el.querySelector<HTMLElement>(FOCUSABLE)
    ;(first ?? el).focus({ preventScroll: true })
    // Tab out as if the panel followed its opener (the opener: Shift+Tab; what follows it: Tab)
    const onTab = (e: KeyboardEvent) => {
      if (e.key !== "Tab" || e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return
      const t = e.target
      if (!(t instanceof Node) || !el.contains(t) || !opener?.isConnected || el.contains(opener)) return
      const items = tabbables(el)
      const leaving = e.shiftKey ? !items.length || t === el || t === items[0] : !items.length || t === items[items.length - 1]
      if (!leaving) return
      e.preventDefault()
      ;(e.shiftKey ? opener : (nextTabbable(opener, el) ?? opener)).focus()
    }
    el.addEventListener("keydown", onTab)
    return () => {
      el.removeEventListener("keydown", onTab)
      // back to the opener only when the focus was in the panel (or went with it)
      const now = document.activeElement
      if (now && now !== document.body && !el.contains(now)) return
      if (opener?.isConnected) opener.focus({ preventScroll: true })
    }
  }, [open])
  if (!open) return null
  return createPortal(
    <div
      ref={panel}
      role="dialog"
      aria-labelledby={titleId}
      tabIndex={-1}
      data-side-panel=""
      onKeyDown={(e) => {
        if (e.key !== "Escape" || e.defaultPrevented || e.nativeEvent.isComposing) return
        e.stopPropagation()
        closeRef.current()
      }}
      className={cn("tex-root fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l border-zinc-200 bg-white shadow-tex-pop outline-none", DRAWER_WIDTH[width])}
    >
      <DrawerBody titleId={titleId} title={title} onClose={onClose} footer={footer}>
        {children}
      </DrawerBody>
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
