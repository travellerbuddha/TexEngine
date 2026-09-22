import { X } from "lucide-react"
import { useEffect, useId, useLayoutEffect, useRef, type ReactNode } from "react"

export type DialogVariant = "center" | "sheet" | "full"

interface Props {
  open: boolean
  onClose: () => void
  title: ReactNode
  closeLabel: string
  children: ReactNode
  footer?: ReactNode
  /** center: modal; sheet: bottom sheet on phones; full: full screen on phones */
  variant?: DialogVariant
  /** On wide screens, position the dialog under this element (popover style). */
  anchor?: HTMLElement | null
  width?: string
  description?: ReactNode
  bodyClassName?: string
  /** CSS selector of the element to focus when the dialog opens (default: first control). */
  initialFocus?: string
}

function syncScrollLock() {
  if (document.querySelector("dialog.bk-dialog[open]")) document.documentElement.style.overflow = "hidden"
  else document.documentElement.style.removeProperty("overflow")
}

/** Modal dialog on the native <dialog> element: top layer, inert page behind,
 * focus kept inside, Esc closes, focus returns to the opener. */
export function Dialog({ open, onClose, title, closeLabel, children, footer, variant = "center", anchor, width, description, bodyClassName = "", initialFocus }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const opener = useRef<HTMLElement | null>(null)
  const titleId = useId()
  const descId = useId()

  useEffect(() => {
    const dlg = ref.current
    if (!dlg) return
    if (open && !dlg.open) {
      opener.current = document.activeElement as HTMLElement | null
      dlg.showModal()
      syncScrollLock()
      const target = initialFocus ? dlg.querySelector<HTMLElement>(initialFocus) : null
      target?.focus()
    } else if (!open && dlg.open) {
      dlg.close()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // an unmounted dialog leaves the top layer by itself; just release the scroll lock
  useEffect(() => () => queueMicrotask(syncScrollLock), [])

  // popover placement next to the anchor on wide screens
  useLayoutEffect(() => {
    const dlg = ref.current
    if (!open || !dlg || !anchor) return
    const place = () => {
      if (window.innerWidth < 640) {
        dlg.classList.remove("bk-anchored")
        dlg.style.removeProperty("top")
        dlg.style.removeProperty("left")
        return
      }
      dlg.classList.add("bk-anchored")
      const r = anchor.getBoundingClientRect()
      const w = dlg.offsetWidth
      const h = dlg.offsetHeight
      const left = Math.max(16, Math.min(r.left, window.innerWidth - w - 16))
      let top = r.bottom + 8
      if (top + h > window.innerHeight - 16) top = Math.max(16, window.innerHeight - h - 16)
      dlg.style.left = `${left}px`
      dlg.style.top = `${top}px`
    }
    place()
    window.addEventListener("resize", place)
    return () => window.removeEventListener("resize", place)
  }, [open, anchor])

  const onNativeClose = () => {
    syncScrollLock()
    const el = opener.current
    if (el && document.contains(el)) el.focus({ preventScroll: true })
    if (open) onClose()
  }

  const cls = variant === "sheet" ? "bk-sheet" : variant === "full" ? "bk-full" : ""
  return (
    <dialog
      ref={ref}
      className={`bk-dialog ${cls}`}
      aria-labelledby={titleId}
      aria-describedby={description ? descId : undefined}
      style={width ? { width } : undefined}
      // React propagates these through the component tree: ignore a nested dialog's events
      onCancel={(e) => {
        if (e.target !== e.currentTarget) return
        e.preventDefault()
        onClose()
      }}
      onClose={(e) => {
        if (e.target === e.currentTarget) onNativeClose()
      }}
      onClick={(e) => {
        // a click on the backdrop lands on the <dialog> element itself
        if (e.target === ref.current) {
          const r = ref.current.getBoundingClientRect()
          const inside = e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom
          if (!inside) onClose()
        }
      }}
    >
      {open && (
        <>
          <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
            <div className="min-w-0">
              <h2 id={titleId} className="text-lg leading-tight">
                {title}
              </h2>
              {description && (
                <p id={descId} className="mt-0.5 text-sm text-muted">
                  {description}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="-mr-2 -mt-1 grid size-10 flex-none place-items-center rounded-full text-soft hover:bg-sunken"
              aria-label={closeLabel}
            >
              <X className="size-5" aria-hidden />
            </button>
          </div>
          <div className={`min-h-0 flex-1 overflow-y-auto px-5 py-4 ${bodyClassName}`}>{children}</div>
          {footer && <div className="border-t border-line bg-surface px-5 py-3">{footer}</div>}
        </>
      )}
    </dialog>
  )
}

/** True while any booking dialog is open (the embed Esc bridge must not close the modal then). */
export function anyDialogOpen() {
  return !!document.querySelector("dialog[open]")
}
