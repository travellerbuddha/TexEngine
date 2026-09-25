// The room price matrix's bulk tools (PRICING_WORKSPACE_UX.md §3.10, §3.19, §3.21; slice S10): the
// toolbar (Fill →, Fill ↓, Adjust…, Undo, Redo and the Keyboard shortcuts popover), the inline
// "Set a fixed price override?" confirmation of a fill, and the "Applied to N cells · Undo" toast.
// The fill, adjust and undo logic is PriceMatrix's (bulk.ts, useWorkspaceHistory); this renders it.
// Fill and Adjust are hidden below 768 px (§3.21: phones edit one cell at a time); Undo and Redo stay.
import { memo, useEffect, useRef, useState, type ReactNode, type RefObject } from "react"
import { ArrowDownToLine, ArrowRightToLine, Keyboard, Redo2, SlidersHorizontal, Undo2, X } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { useTexT } from "../../../i18n"
import { Button, Popover } from "../../../ui"
import type { UndoToastState } from "./useWorkspaceHistory"

export interface BulkToolbarProps {
  /** Fill → / Fill ↓ have something to copy in the selection */
  canFillRight: boolean
  canFillDown: boolean
  /** the selection holds an editable cell (Adjust… lists what it changes) */
  canAdjust: boolean
  onFill: (dir: "right" | "down") => void
  onAdjust: () => void
  /** the Adjust… button: the popover's anchor */
  adjustRef: RefObject<HTMLButtonElement | null>
  adjustOpen: boolean
  canUndo: boolean
  canRedo: boolean
  onUndo: () => void
  onRedo: () => void
}

/** Memoised: the matrix re-renders on every arrow key (the selection), the toolbar only when one
 * of its states changes (its callbacks are stable). Without this an arrow key took about 10 ms more
 * on 265 and on 1,005 cells (development React, S10 measurement). */
export const BulkToolbar = memo(BulkToolbarImpl)

function BulkToolbarImpl(p: BulkToolbarProps) {
  const { t } = useTexT()
  return (
    // a labelled group of ordinary buttons (each its own tab stop), not an ARIA toolbar, which would
    // promise arrow-key navigation with one tab stop
    <div role="group" aria-label={t("rates.ws.bulk.toolbar")} className="flex flex-wrap items-center gap-1.5">
      <span className="hidden items-center gap-1.5 md:inline-flex">
        <Button
          variant="secondary"
          size="sm"
          icon={<ArrowRightToLine className="size-4" aria-hidden />}
          shortcut={t("rates.kbd.fill_right.keys")}
          aria-keyshortcuts="Control+R Meta+R"
          disabled={!p.canFillRight}
          onClick={() => p.onFill("right")}
        >
          {t("rates.ws.bulk.fill_right")}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          icon={<ArrowDownToLine className="size-4" aria-hidden />}
          shortcut={t("rates.kbd.fill_down.keys")}
          aria-keyshortcuts="Control+D Meta+D"
          disabled={!p.canFillDown}
          onClick={() => p.onFill("down")}
        >
          {t("rates.ws.bulk.fill_down")}
        </Button>
        <Button
          ref={p.adjustRef}
          variant="secondary"
          size="sm"
          icon={<SlidersHorizontal className="size-4" aria-hidden />}
          aria-haspopup="dialog"
          aria-expanded={p.adjustOpen}
          disabled={!p.canAdjust}
          onClick={p.onAdjust}
        >
          {t("rates.ws.bulk.adjust")}
        </Button>
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Button variant="ghost" size="sm" icon={<Undo2 className="size-4" aria-hidden />} aria-keyshortcuts="Control+Z Meta+Z" disabled={!p.canUndo} onClick={p.onUndo}>
          {t("rates.ws.bulk.undo")}
        </Button>
        <Button variant="ghost" size="sm" icon={<Redo2 className="size-4" aria-hidden />} aria-keyshortcuts="Control+Shift+Z Meta+Shift+Z Control+Y" disabled={!p.canRedo} onClick={p.onRedo}>
          {t("rates.ws.bulk.redo")}
        </Button>
      </span>
      <span className="hidden md:inline-flex">
        <KeyboardShortcuts />
      </span>
    </div>
  )
}

/** Every key of the matrix, in the order of §3.10 (§3.19: "A Keyboard shortcuts popover lists every key"). */
const SHORTCUTS = [
  "move",
  "extend",
  "add",
  "header",
  "header_range",
  "header_lane",
  "select_all",
  "clear_selection",
  "edit",
  "commit",
  "revert",
  "bulk",
  "rule",
  "delete",
  "fill_right",
  "fill_down",
  "copy",
  "paste",
  "undo",
  "redo",
  "save",
] as const

export function KeyboardShortcuts() {
  const { t } = useTexT()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLButtonElement>(null)
  return (
    <>
      <Button ref={ref} variant="ghost" size="sm" icon={<Keyboard className="size-4" aria-hidden />} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {t("rates.kbd.title")}
      </Button>
      <Popover open={open} onClose={() => setOpen(false)} anchorRef={ref} label={t("rates.kbd.title")} width="lg" placement="bottom-end">
        <p className="mb-2 text-xs text-zinc-500">{t("rates.kbd.mac_note")}</p>
        <table className="w-full text-left text-sm">
          <thead className="sr-only">
            <tr>
              <th scope="col">{t("rates.kbd.keys")}</th>
              <th scope="col">{t("rates.kbd.action")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {SHORTCUTS.map((id) => (
              <tr key={id}>
                <th scope="row" className="py-1 pr-3 align-top font-normal whitespace-nowrap">
                  <kbd className="rounded border border-zinc-300 bg-zinc-50 px-1.5 py-0.5 font-sans text-xs text-zinc-800">{t(`rates.kbd.${id}.keys`)}</kbd>
                </th>
                <td className="py-1 text-zinc-700">{t(`rates.kbd.${id}`)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Popover>
    </>
  )
}

/** The inline confirmation of a fill that puts prices into formula rows (§3.10). Not modal: the
 * grid stays usable; the confirm button takes the focus, Escape or Cancel drop the fill. */
export function FillConfirm({ message, onConfirm, onCancel }: { message: string; onConfirm: () => void; onCancel: () => void }) {
  const { t } = useTexT()
  const ref = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    ref.current?.focus()
  }, [])
  return (
    <div
      role="group"
      aria-label={t("rates.ws.fill.confirm_title")}
      className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"
      onKeyDown={(e) => {
        if (e.key !== "Escape") return
        e.preventDefault()
        e.stopPropagation()
        onCancel()
      }}
    >
      <span className="min-w-0 flex-1">{message}</span>
      <Button ref={ref} size="sm" onClick={onConfirm}>
        {t("rates.ws.fill.confirm")}
      </Button>
      <Button variant="secondary" size="sm" onClick={onCancel}>
        {t("core.action.cancel")}
      </Button>
    </div>
  )
}

/** The toast of a bulk operation: "Applied to 8 cells · Undo" (§3.10). Its text is announced by
 * the matrix's polite live region; the toast itself is not a live region (no double reading).
 * Its Undo and close button take the toast away: when it held the focus (a keyboard user tabbed
 * to it, or a click focused the button), `onFocusBack` puts the focus back where the user works
 * (the matrix: the grid's active cell), so it never drops to the page. */
export const UndoToastView = memo(UndoToastViewImpl)

function UndoToastViewImpl({
  toast,
  onUndo,
  onDismiss,
  onHold,
  onFocusBack,
}: {
  toast: UndoToastState | null
  onUndo: () => void
  onDismiss: () => void
  onHold: (on: boolean) => void
  onFocusBack?: () => void
}) {
  const { t } = useTexT()
  const box = useRef<HTMLDivElement | null>(null)
  if (!toast) return null
  const leaving = (action: () => void) => () => {
    const held = Boolean(box.current?.contains(document.activeElement))
    action()
    if (held) onFocusBack?.()
  }
  return (
    <div
      ref={box}
      data-testid="undo-toast"
      // bottom centre: the app's own toasts use the bottom-right corner (top on phones)
      className="pointer-events-auto fixed inset-x-3 bottom-3 z-[58] flex items-center gap-3 rounded-lg border border-zinc-200 bg-zinc-900 px-3 py-2.5 text-sm text-white shadow-tex-pop sm:inset-x-auto sm:bottom-4 sm:left-1/2 sm:w-max sm:max-w-md sm:-translate-x-1/2"
      onPointerEnter={() => onHold(true)}
      onPointerLeave={() => onHold(false)}
      onFocus={() => onHold(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) onHold(false)
      }}
    >
      <span className="min-w-0 flex-1">{toast.message}</span>
      <ToastButton onClick={leaving(onUndo)}>{t("rates.ws.bulk.undo")}</ToastButton>
      <button type="button" aria-label={t("core.action.close")} onClick={leaving(onDismiss)} className="rounded p-0.5 text-zinc-400 hover:bg-zinc-800 hover:text-white focus-visible:ring-2 focus-visible:ring-white focus-visible:outline-none">
        <X className="size-4" aria-hidden />
      </button>
    </div>
  )
}

function ToastButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn("rounded-md px-2 py-1 font-semibold text-tex-300 hover:bg-zinc-800 hover:text-tex-200", "focus-visible:ring-2 focus-visible:ring-white focus-visible:outline-none")}
    >
      {children}
    </button>
  )
}
