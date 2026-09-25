// Anchored, non-modal overlays for routine edits (PRICING_WORKSPACE_UX.md §3.18, §3.19):
// Popover (role="dialog", not modal), Menu (menu button + role="menu" with roving items) and
// Tooltip (hover/focus after 300 ms, aria-describedby). No positioning library: fixed
// positioning from placement.ts, which flips and clamps inside the viewport.
import {
  Children,
  cloneElement,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type FocusEvent as ReactFocusEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactElement,
  type ReactNode,
  type Ref,
  type RefObject,
} from "react"
import { createPortal, flushSync } from "react-dom"
import { X } from "lucide-react"
import { cn } from "../../lib/utils"
import { useTexT } from "../i18n"
import { Button, IconButton, type ButtonSize, type ButtonVariant } from "./primitives"
import { placeFloating, type FloatingPlacement } from "./placement"

export type { FloatingPlacement } from "./placement"

type ElementRef = RefObject<HTMLElement | null>

const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'

// Phones get a bottom sheet instead of an anchored panel (Tailwind's `sm` breakpoint).
const PHONE = "(max-width: 639.98px)"

function subscribePhone(onChange: () => void) {
  const m = window.matchMedia(PHONE)
  m.addEventListener("change", onChange)
  return () => m.removeEventListener("change", onChange)
}

/** Below Tailwind's `sm` breakpoint (a phone): overlays take the whole screen there. */
export function useIsPhone(): boolean {
  return useSyncExternalStore(
    subscribePhone,
    () => window.matchMedia(PHONE).matches,
    () => false,
  )
}

/** Where a floating panel is portaled: into the anchor's modal Dialog/Drawer when it has one
 * (content outside an aria-modal dialog is hidden from assistive technology), else the body. */
function portalTarget(anchor: HTMLElement | null): HTMLElement {
  return anchor?.closest<HTMLElement>('[aria-modal="true"]') ?? document.body
}

/** The scroll positions inside `panel` (itself included) that are not at the origin. */
function scrollPositions(panel: HTMLElement): [Element, number, number][] {
  const kept: [Element, number, number][] = []
  for (const el of [panel, ...panel.querySelectorAll("*")]) {
    if (el.scrollTop || el.scrollLeft) kept.push([el, el.scrollTop, el.scrollLeft])
  }
  return kept
}

/** Keep `panel` next to `anchor` (fixed position, flipped and clamped) while `open`. */
function useFloatingPosition(open: boolean, anchorRef: ElementRef, panelRef: ElementRef, placement: FloatingPlacement, enabled = true) {
  useLayoutEffect(() => {
    const panel = panelRef.current
    if (!open || !enabled || !panel) return
    const update = (e?: Event) => {
      const anchor = anchorRef.current
      if (!anchor?.isConnected) return
      // A scroll re-places the panel only when it moved the anchor: the scrolled box holds the
      // anchor (the page, a Drawer body, a Popover body under a Menu). The panel's own scrolling
      // (the wheel, focus moving to an item below the fold) and unrelated boxes leave it alone.
      if (e?.type === "scroll" && e.target instanceof Node && !e.target.contains(anchor)) return
      // Measure the natural size, then constrain it. Without the constraint nothing inside the
      // panel overflows and the browser resets its scroll positions: keep them and put them back.
      const scrolled = scrollPositions(panel)
      panel.style.maxHeight = ""
      panel.style.maxWidth = ""
      const a = anchor.getBoundingClientRect()
      const pos = placeFloating(
        { top: a.top, left: a.left, right: a.right, bottom: a.bottom },
        { width: panel.offsetWidth, height: panel.offsetHeight },
        { width: document.documentElement.clientWidth, height: window.innerHeight },
        placement,
      )
      panel.style.top = `${pos.top}px`
      panel.style.left = `${pos.left}px`
      panel.style.maxHeight = `${pos.maxHeight}px`
      panel.style.maxWidth = `${pos.maxWidth}px`
      panel.dataset.placement = pos.placement
      for (const [el, top, left] of scrolled) {
        el.scrollTop = top
        el.scrollLeft = left
      }
    }
    update()
    window.addEventListener("resize", update)
    window.addEventListener("scroll", update, true)
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => update())
    observer?.observe(panel)
    if (anchorRef.current) observer?.observe(anchorRef.current)
    return () => {
      window.removeEventListener("resize", update)
      window.removeEventListener("scroll", update, true)
      observer?.disconnect()
      panel.style.top = ""
      panel.style.left = ""
      panel.style.maxHeight = ""
      panel.style.maxWidth = ""
    }
  }, [open, enabled, placement, anchorRef, panelRef])
}

// Open floating layers, oldest first. A Menu opened from inside a Popover is above it: a
// pointerdown in the Menu is not "outside" the Popover, and Escape closes the Menu first.
// A shown tooltip is a layer too, so Escape on its trigger only hides it (not the Popover,
// Drawer or Dialog it sits in).
type Layer = { panel: HTMLElement; anchorRef: ElementRef; tooltip?: boolean }
const layers: Layer[] = []

function owns(layer: Layer, node: Node): boolean {
  if (layer.panel.contains(node)) return true
  const anchor = layer.anchorRef.current
  // a tooltip's trigger exactly: an editor inside a grid cell with a tooltip is not the trigger
  return !!anchor && (layer.tooltip ? anchor === node : anchor.contains(node))
}

/** The layer an Escape belongs to: the newest layer holding the key's target, else (nothing
 * focused) the newest layer. */
function escapeOwner(target: EventTarget | null): Layer | undefined {
  const t = target instanceof Node && target !== document.body ? target : null
  for (let i = layers.length - 1; i >= 0; i--) if (!t || owns(layers[i], t)) return layers[i]
  return undefined
}

/** Escape (from inside the layer, its anchor, or with nothing focused) and an outside pointerdown close it. */
function useDismiss(open: boolean, onClose: () => void, anchorRef: ElementRef, panelRef: ElementRef) {
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    const panel = panelRef.current
    if (!open || !panel) return
    const me: Layer = { panel, anchorRef }
    layers.push(me)
    const onPointerDown = (e: PointerEvent) => {
      const t = e.target
      if (!(t instanceof Node) || owns(me, t)) return
      // a layer above this one; a tooltip only by its bubble, and only when its trigger is here
      const above = (l: Layer) =>
        l.tooltip ? l.panel.contains(t) && !!l.anchorRef.current && owns(me, l.anchorRef.current) : owns(l, t)
      if (layers.slice(layers.indexOf(me) + 1).some(above)) return
      closeRef.current()
    }
    // window + capture: runs before the document-level Escape of a Dialog/Drawer underneath
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.isComposing) return
      if (escapeOwner(e.target) !== me) return
      e.preventDefault()
      e.stopPropagation()
      closeRef.current()
    }
    document.addEventListener("pointerdown", onPointerDown, true)
    window.addEventListener("keydown", onKeyDown, true)
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true)
      window.removeEventListener("keydown", onKeyDown, true)
      const i = layers.indexOf(me)
      if (i >= 0) layers.splice(i, 1)
    }
  }, [open, anchorRef, panelRef])
}

/** The panel's visible Tab stops in document order (a positive tabindex is not reordered). */
/** The elements Tab reaches inside `panel`, in DOM order (shown, tabIndex ≥ 0). */
export function tabbables(panel: HTMLElement): HTMLElement[] {
  return Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.tabIndex >= 0 && el.getClientRects().length > 0)
}

/**
 * Tab from the Popover's last element, or Shift+Tab from its first, leaves it as if the panel sat
 * right after its trigger: it closes, and focus goes on from the trigger (Tab: to the element
 * after it; Shift+Tab: to the trigger). Without this, focus left the page (the panel is portaled
 * to the end of the body) or wrapped inside a Drawer while the Popover stayed open.
 * Window + capture: runs before the Tab trap of a Dialog/Drawer underneath.
 */
function useTabOut(open: boolean, onClose: () => void, anchorRef: ElementRef, panelRef: ElementRef) {
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    const panel = panelRef.current
    if (!open || !panel) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Tab" || e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return
      const t = e.target
      const anchor = anchorRef.current
      if (!(t instanceof Node) || !panel.contains(t) || !anchor?.isConnected) return
      const items = tabbables(panel)
      const leaving = e.shiftKey ? !items.length || t === panel || t === items[0] : !items.length || t === items[items.length - 1]
      if (!leaving) return
      if (e.shiftKey) e.preventDefault()
      anchor.focus()
      // unmount now, so the browser's Tab (and a Drawer's trap) moves on from the trigger
      // without the panel in the page
      flushSync(() => closeRef.current())
    }
    window.addEventListener("keydown", onKeyDown, true)
    return () => window.removeEventListener("keydown", onKeyDown, true)
  }, [open, anchorRef, panelRef])
}

/** Focus moves into the panel on open and back to the anchor on close (unless the user has
 * already put it somewhere else, e.g. by clicking another control). */
function useFocusInOut(open: boolean, anchorRef: ElementRef, panelRef: ElementRef, initial: () => HTMLElement | null | undefined) {
  const initialRef = useRef(initial)
  initialRef.current = initial
  useEffect(() => {
    const panel = panelRef.current
    if (!open || !panel) return
    const opener = anchorRef.current
    const target = initialRef.current() ?? panel.querySelector<HTMLElement>(FOCUSABLE) ?? panel
    target.focus({ preventScroll: true })
    // an item below the fold of a scrolling panel (a Menu opened with ArrowUp starts on its last
    // item): scroll the panel, which sits inside the viewport, to show it
    if (target !== panel) target.scrollIntoView({ block: "nearest", inline: "nearest" })
    return () => {
      const now = document.activeElement
      if (now && now !== document.body && !panel.contains(now)) return
      const back = anchorRef.current ?? opener
      if (back?.isConnected) back.focus()
    }
  }, [open, anchorRef, panelRef])
}

// ---------------------------------------------------------------------------------------------
// Popover
// ---------------------------------------------------------------------------------------------

const POPOVER_WIDTH = {
  auto: "w-max min-w-48",
  sm: "w-64",
  md: "w-80",
  lg: "w-[28rem]",
}

export interface PopoverProps {
  open: boolean
  onClose: () => void
  /** The trigger: the panel is placed next to it and focus returns to it on close. */
  anchorRef: RefObject<HTMLElement | null>
  /** The dialog's accessible name (aria-labelledby), shown as the panel title. */
  label: ReactNode
  children?: ReactNode
  placement?: FloatingPlacement
  /** Focused on open. Default: the first [data-autofocus] element, else the first focusable one. */
  initialFocusRef?: RefObject<HTMLElement | null>
  /** Keep the title for assistive technology only (it still names the dialog). */
  hideLabel?: boolean
  width?: keyof typeof POPOVER_WIDTH
  className?: string
}

/**
 * Non-modal popover for routine edits (role="dialog" without aria-modal, no focus trap, no
 * backdrop). Escape or a pointerdown outside it and its trigger closes it; focus moves in on open
 * and returns to the trigger on close. Tab past its last element (Shift+Tab before its first)
 * closes it and goes on from the trigger. Below 640 px it is a bottom sheet (still not modal).
 */
export function Popover({
  open,
  onClose,
  anchorRef,
  label,
  children,
  placement = "bottom-start",
  initialFocusRef,
  hideLabel,
  width = "auto",
  className,
}: PopoverProps) {
  const { t } = useTexT()
  const titleId = useId()
  const panelRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const sheet = useIsPhone()
  useFloatingPosition(open, anchorRef, panelRef, placement, !sheet)
  useDismiss(open, onClose, anchorRef, panelRef)
  useTabOut(open, onClose, anchorRef, panelRef)
  useFocusInOut(open, anchorRef, panelRef, () => {
    const body = bodyRef.current
    return initialFocusRef?.current ?? body?.querySelector<HTMLElement>("[data-autofocus]") ?? body?.querySelector<HTMLElement>(FOCUSABLE)
  })
  if (!open) return null
  return createPortal(
    <div
      ref={panelRef}
      role="dialog"
      aria-labelledby={titleId}
      tabIndex={-1}
      data-sheet={sheet || undefined}
      className={cn(
        "tex-root fixed z-[55] flex flex-col border-zinc-200 bg-white text-left shadow-tex-pop outline-none",
        sheet ? "inset-x-0 bottom-0 max-h-[92vh] rounded-t-2xl border-t" : cn("rounded-xl border", POPOVER_WIDTH[width]),
        className,
      )}
    >
      {sheet ? (
        <div className="flex items-center justify-between gap-3 border-b border-zinc-100 px-4 py-2">
          <div id={titleId} className="min-w-0 text-sm font-semibold text-zinc-950">
            {label}
          </div>
          <IconButton label={t("core.action.close")} icon={<X className="size-4" />} size="sm" onClick={onClose} />
        </div>
      ) : (
        <div id={titleId} className={hideLabel ? "sr-only" : "px-3 pt-2.5 text-xs font-semibold text-zinc-600"}>
          {label}
        </div>
      )}
      <div ref={bodyRef} className={cn("min-h-0 overflow-y-auto", sheet ? "px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]" : "p-3")}>
        {children}
      </div>
    </div>,
    portalTarget(anchorRef.current),
  )
}

// ---------------------------------------------------------------------------------------------
// Menu
// ---------------------------------------------------------------------------------------------

const MenuCtx = createContext<{ close: () => void } | null>(null)

function menuItems(panel: HTMLElement | null): HTMLElement[] {
  return panel ? Array.from(panel.querySelectorAll<HTMLElement>('[role="menuitem"]')) : []
}

/** The keys of an open role="menu" (Menu, ContextMenu): arrows, Home/End and first-letter
 * typeahead move between items; Tab leaves (`onTab` closes the menu and puts the focus back). */
function onMenuKeys(e: ReactKeyboardEvent<HTMLDivElement>, panel: HTMLElement | null, onTab: () => void) {
  const items = menuItems(panel)
  if (!items.length) return
  const i = items.indexOf(document.activeElement as HTMLElement)
  const go = (n: number) => {
    e.preventDefault()
    items[(n + items.length) % items.length].focus()
  }
  switch (e.key) {
    case "ArrowDown":
      return go(i + 1)
    case "ArrowUp":
      return go(i < 0 ? -1 : i - 1)
    case "Home":
      return go(0)
    case "End":
      return go(-1)
    case "Tab":
      onTab()
      return
  }
  if (e.key.length !== 1 || e.key === " " || e.ctrlKey || e.metaKey || e.altKey) return
  const lang = document.documentElement.lang || undefined
  const key = e.key.toLocaleLowerCase(lang)
  for (let step = 1; step <= items.length; step++) {
    const item = items[(i + step + items.length) % items.length]
    const name = (item.dataset.text ?? item.textContent ?? "").trim().toLocaleLowerCase(lang)
    if (name.startsWith(key)) {
      e.preventDefault()
      item.focus()
      return
    }
  }
}

export interface MenuProps {
  /** Accessible name of the menu, and of the button when it shows only an icon. */
  label: string
  /** MenuItem / MenuSeparator elements. */
  children: ReactNode
  icon?: ReactNode
  /** Visible button text; without it the button is icon-only with a tooltip. */
  text?: ReactNode
  placement?: FloatingPlacement
  variant?: ButtonVariant
  size?: ButtonSize
  disabled?: boolean
  className?: string
  /** More props of the menu button: `tabIndex` -1 for a button in a grid's header (reached with
   * the arrow keys, not Tab: one tab stop per grid, §3.19) and its `data-lane-*` attributes. */
  buttonProps?: { tabIndex?: number } & { [key: `data-${string}`]: string | undefined }
}

/**
 * Menu button (aria-haspopup="menu", aria-expanded) and its role="menu" list. Arrow keys,
 * Home/End and first-letter typeahead move focus between items; Enter/Space activate; Escape
 * closes and returns focus to the button; Tab closes and moves on from the button.
 */
export function Menu({ label, children, icon, text, placement = "bottom-start", variant = "ghost", size = "sm", disabled, className, buttonProps }: MenuProps) {
  const [open, setOpen] = useState(false)
  const from = useRef<"first" | "last">("first")
  const buttonRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const menuId = useId()
  const close = useCallback(() => setOpen(false), [])
  const ctx = useMemo(() => ({ close }), [close])
  useFloatingPosition(open, buttonRef, panelRef, placement)
  useDismiss(open, close, buttonRef, panelRef)
  useFocusInOut(open, buttonRef, panelRef, () => {
    const items = menuItems(panelRef.current)
    return from.current === "last" ? items[items.length - 1] : items[0]
  })

  const onMenuKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) =>
    onMenuKeys(e, panelRef.current, () => {
      // leave from the button, so Tab / Shift+Tab continue in page order
      buttonRef.current?.focus()
      close()
    })

  const toggle = () => {
    from.current = "first"
    setOpen((o) => !o)
  }
  const onButtonKeyDown = (e: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return
    e.preventDefault()
    from.current = e.key === "ArrowUp" ? "last" : "first"
    setOpen(true)
  }
  const aria = {
    "aria-haspopup": "menu" as const,
    "aria-expanded": open,
    "aria-controls": open ? menuId : undefined,
  }
  return (
    <>
      {text ? (
        <Button ref={buttonRef} variant={variant} size={size} icon={icon} disabled={disabled} className={className} onClick={toggle} onKeyDown={onButtonKeyDown} {...aria} {...buttonProps}>
          {text}
        </Button>
      ) : (
        <Tooltip content={label} describe={false} disabled={open}>
          <button
            ref={buttonRef}
            type="button"
            aria-label={label}
            disabled={disabled}
            onClick={toggle}
            onKeyDown={onButtonKeyDown}
            {...aria}
            {...buttonProps}
            className={cn(
              "inline-flex shrink-0 items-center justify-center rounded-lg text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900",
              "disabled:cursor-not-allowed disabled:opacity-50",
              open && "bg-zinc-100 text-zinc-900",
              size === "sm" ? "size-8" : "size-9",
              className,
            )}
          >
            {icon}
          </button>
        </Tooltip>
      )}
      {open &&
        createPortal(
          <div
            ref={panelRef}
            id={menuId}
            role="menu"
            aria-label={label}
            tabIndex={-1}
            onKeyDown={onMenuKeyDown}
            className="tex-root fixed z-[55] min-w-44 overflow-y-auto rounded-lg border border-zinc-200 bg-white p-1 shadow-tex-pop outline-none sm:max-w-xs"
          >
            <MenuCtx.Provider value={ctx}>{children}</MenuCtx.Provider>
          </div>,
          portalTarget(buttonRef.current),
        )}
    </>
  )
}

export interface ContextMenuProps {
  open: boolean
  onClose: () => void
  /** What the menu is for (a grid cell): it is placed next to it and the focus returns to it. */
  anchorRef: RefObject<HTMLElement | null>
  /** Accessible name of the menu. */
  label: string
  /** MenuItem / MenuSeparator elements. */
  children: ReactNode
  placement?: FloatingPlacement
}

/**
 * A context menu (role="menu") opened by the page, not by a button of its own: from a right-click
 * (or a long press), Shift+F10 or the ContextMenu key on an element such as a grid cell. It has
 * the Menu's keys (arrows, Home/End, typeahead, Enter/Space, Escape); Escape, Tab, an outside
 * pointerdown or choosing an item close it, and the focus goes back to the element.
 */
export function ContextMenu({ open, onClose, anchorRef, label, children, placement = "bottom-start" }: ContextMenuProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  const close = useCallback(() => closeRef.current(), [])
  const ctx = useMemo(() => ({ close }), [close])
  useFloatingPosition(open, anchorRef, panelRef, placement)
  useDismiss(open, close, anchorRef, panelRef)
  useFocusInOut(open, anchorRef, panelRef, () => menuItems(panelRef.current)[0])
  if (!open) return null
  return createPortal(
    <div
      ref={panelRef}
      role="menu"
      aria-label={label}
      tabIndex={-1}
      onKeyDown={(e) =>
        onMenuKeys(e, panelRef.current, () => {
          e.preventDefault()
          anchorRef.current?.focus()
          close()
        })
      }
      className="tex-root fixed z-[55] min-w-44 overflow-y-auto rounded-lg border border-zinc-200 bg-white p-1 shadow-tex-pop outline-none sm:max-w-xs"
    >
      <MenuCtx.Provider value={ctx}>{children}</MenuCtx.Provider>
    </div>,
    portalTarget(anchorRef.current),
  )
}

export interface MenuItemProps {
  onSelect?: () => void
  children: ReactNode
  /** Focusable but not activatable (it still says why it is there). */
  disabled?: boolean
  icon?: ReactNode
  /** Shortcut hint shown on the right, e.g. "Ctrl+R" (visual; see `keyshortcuts`). */
  shortcut?: string
  /** aria-keyshortcuts value, e.g. "Control+R". */
  keyshortcuts?: string
  tone?: "default" | "danger"
  /** Typeahead text when the visible text does not start with the right letter. */
  textValue?: string
}

/** One role="menuitem". Selecting it runs onSelect and closes the menu. */
export function MenuItem({ onSelect, children, disabled, icon, shortcut, keyshortcuts, tone = "default", textValue }: MenuItemProps) {
  const menu = useContext(MenuCtx)
  return (
    <button
      type="button"
      role="menuitem"
      tabIndex={-1}
      aria-disabled={disabled || undefined}
      aria-keyshortcuts={keyshortcuts}
      data-text={textValue}
      onClick={() => {
        if (disabled) return
        onSelect?.()
        menu?.close()
      }}
      onPointerMove={(e) => {
        if (e.pointerType === "mouse" && document.activeElement !== e.currentTarget) e.currentTarget.focus({ preventScroll: true })
      }}
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm outline-none focus:bg-zinc-100",
        disabled ? "cursor-not-allowed text-zinc-400" : tone === "danger" ? "text-rose-700" : "text-zinc-800",
      )}
    >
      {icon && (
        <span aria-hidden className="flex size-4 shrink-0 items-center justify-center text-zinc-500">
          {icon}
        </span>
      )}
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {shortcut && (
        <kbd aria-hidden className="ml-3 font-sans text-[11px] text-zinc-400">
          {shortcut}
        </kbd>
      )}
    </button>
  )
}

export function MenuSeparator() {
  return <div role="separator" className="-mx-1 my-1 h-px bg-zinc-100" />
}

// ---------------------------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------------------------

export interface TooltipOptions {
  placement?: FloatingPlacement
  /** Delay before showing on hover or focus, in ms (default 300). */
  delay?: number
  /** Add the text to the trigger's description (aria-describedby). Pass false when it repeats
   * the trigger's accessible name, e.g. the label of an icon-only button. Default true. */
  describe?: boolean
  disabled?: boolean
}

export interface TooltipTriggerProps {
  ref: (el: HTMLElement | null) => void
  "aria-describedby"?: string
  onPointerEnter: (e: ReactPointerEvent<HTMLElement>) => void
  onPointerLeave: (e: ReactPointerEvent<HTMLElement>) => void
  onPointerDown: (e: ReactPointerEvent<HTMLElement>) => void
  onFocus: (e: ReactFocusEvent<HTMLElement>) => void
  onBlur: (e: ReactFocusEvent<HTMLElement>) => void
  onKeyDown: (e: ReactKeyboardEvent<HTMLElement>) => void
}

function focusVisible(el: Element): boolean {
  try {
    return el.matches(":focus-visible")
  } catch {
    return true
  }
}

/**
 * Tooltip behaviour for a trigger you render yourself (a grid cell, say): spread `triggerProps`
 * on the focusable trigger and render `tooltip` next to it or inside it. The text is always the
 * trigger's description (a hidden element referenced by aria-describedby), so it reaches
 * assistive technology without hovering.
 *
 * It shows after `delay` on mouse hover and on keyboard focus (:focus-visible), stays while the
 * pointer is over it, and hides on Escape, blur, pointer leave and press. Escape on its trigger
 * only hides it (the Popover, Drawer or Dialog around it stays open). It never shows on touch,
 * so a tooltip must never be the only carrier of essential information.
 */
export function useTooltip(content: ReactNode, { placement = "top", delay = 300, describe = true, disabled }: TooltipOptions = {}) {
  const id = useId()
  const off = disabled || content === null || content === undefined || content === "" || content === false
  const [shown, setShown] = useState(false)
  const anchorRef = useRef<HTMLElement | null>(null)
  const bubbleRef = useRef<HTMLDivElement>(null)
  const showTimer = useRef<number | undefined>(undefined)
  const hideTimer = useRef<number | undefined>(undefined)

  const clearTimers = useCallback(() => {
    window.clearTimeout(showTimer.current)
    window.clearTimeout(hideTimer.current)
  }, [])
  const hide = useCallback(() => {
    clearTimers()
    setShown(false)
  }, [clearTimers])
  const show = () => {
    if (off) return
    clearTimers()
    showTimer.current = window.setTimeout(() => setShown(true), delay)
  }
  const hideSoon = () => {
    clearTimers()
    hideTimer.current = window.setTimeout(() => setShown(false), 100)
  }

  useEffect(() => clearTimers, [clearTimers])
  useEffect(() => {
    if (off) hide()
  }, [off, hide])
  const visible = shown && !off
  useEffect(() => {
    const bubble = bubbleRef.current
    if (!visible || !bubble) return
    const me: Layer = { panel: bubble, anchorRef, tooltip: true }
    layers.push(me)
    // Escape always hides it. On its trigger (or with nothing focused) the key stops here, so the
    // Popover, Drawer or Dialog around it stays open; elsewhere the key goes on as well.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.isComposing) return
      const mine = escapeOwner(e.target) === me
      hide()
      if (!mine) return
      e.preventDefault()
      e.stopPropagation()
    }
    window.addEventListener("keydown", onKey, true)
    return () => {
      window.removeEventListener("keydown", onKey, true)
      const i = layers.indexOf(me)
      if (i >= 0) layers.splice(i, 1)
    }
  }, [visible, hide])
  useFloatingPosition(visible, anchorRef, bubbleRef, placement)

  const ref = useCallback((el: HTMLElement | null) => {
    anchorRef.current = el
  }, [])
  const triggerProps: TooltipTriggerProps = {
    ref,
    "aria-describedby": describe && !off ? id : undefined,
    onPointerEnter: (e) => {
      if (e.pointerType !== "touch") show()
    },
    onPointerLeave: () => hideSoon(),
    onPointerDown: () => hide(),
    // keyboard focus on the trigger itself only: focus that follows a click or a tap, or that a
    // closing menu puts back, does not match :focus-visible; an editor inside it is not the trigger
    onFocus: (e) => {
      if (e.target === e.currentTarget && focusVisible(e.currentTarget)) show()
    },
    onBlur: () => hide(),
    onKeyDown: (e) => {
      if (e.key === "Escape") hide()
    },
  }
  const tooltip = (
    <>
      {describe && !off && (
        <span id={id} hidden>
          {content}
        </span>
      )}
      {visible &&
        createPortal(
          <div
            ref={bubbleRef}
            role="tooltip"
            onPointerEnter={() => window.clearTimeout(hideTimer.current)}
            onPointerLeave={hideSoon}
            className="tex-root fixed z-[65] max-w-xs rounded-md border border-transparent bg-zinc-900 px-2 py-1 text-xs leading-snug text-white shadow-tex-pop"
          >
            {content}
          </div>,
          portalTarget(anchorRef.current),
        )}
    </>
  )
  return { triggerProps, tooltip, shown: visible }
}

type TriggerElementProps = {
  ref?: Ref<HTMLElement>
  "aria-describedby"?: string
  onPointerEnter?: (e: ReactPointerEvent<HTMLElement>) => void
  onPointerLeave?: (e: ReactPointerEvent<HTMLElement>) => void
  onPointerDown?: (e: ReactPointerEvent<HTMLElement>) => void
  onFocus?: (e: ReactFocusEvent<HTMLElement>) => void
  onBlur?: (e: ReactFocusEvent<HTMLElement>) => void
  onKeyDown?: (e: ReactKeyboardEvent<HTMLElement>) => void
}

function chain<E>(a: ((e: E) => void) | undefined, b: (e: E) => void): (e: E) => void {
  return a
    ? (e: E) => {
        a(e)
        b(e)
      }
    : b
}

function assignRef<T>(ref: Ref<T> | undefined, value: T | null) {
  if (typeof ref === "function") ref(value)
  else if (ref) ref.current = value
}

/**
 * Tooltip for one focusable child element (a button, a link, a badge with tabIndex=0):
 * `<Tooltip content={t("…")}><Button …/></Tooltip>`. Replaces `title` attributes in new code.
 * For triggers that cannot take a sibling (table cells), use `useTooltip`.
 */
export function Tooltip({ content, children, ...options }: TooltipOptions & { content: ReactNode; children: ReactElement }) {
  const { triggerProps: tp, tooltip } = useTooltip(content, options)
  const child = Children.only(children) as ReactElement<TriggerElementProps>
  const p = child.props
  const own = p.ref
  const ref = useMemo(
    () => (el: HTMLElement | null) => {
      assignRef(own, el)
      tp.ref(el)
    },
    [own, tp.ref],
  )
  const describedBy = [p["aria-describedby"], tp["aria-describedby"]].filter(Boolean).join(" ") || undefined
  return (
    <>
      {cloneElement(child, {
        ref,
        "aria-describedby": describedBy,
        onPointerEnter: chain(p.onPointerEnter, tp.onPointerEnter),
        onPointerLeave: chain(p.onPointerLeave, tp.onPointerLeave),
        onPointerDown: chain(p.onPointerDown, tp.onPointerDown),
        onFocus: chain(p.onFocus, tp.onFocus),
        onBlur: chain(p.onBlur, tp.onBlur),
        onKeyDown: chain(p.onKeyDown, tp.onKeyDown),
      })}
      {tooltip}
    </>
  )
}
