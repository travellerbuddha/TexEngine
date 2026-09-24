// Placement of anchored floating panels (Popover, Menu, Tooltip): fixed positioning that
// flips to the other side of the anchor and clamps inside the viewport. Pure pixel geometry
// with no runtime imports, unit tested with `node --test` (tests/unit/placement.test.ts).

/** Side of the anchor, then alignment ("start" = left edges, "end" = right edges, none = centred). */
export type FloatingPlacement = "bottom-start" | "bottom-end" | "bottom" | "top-start" | "top-end" | "top"

/** Viewport coordinates, as from getBoundingClientRect(). */
export type FloatingRect = { top: number; left: number; right: number; bottom: number }

export type FloatingPosition = {
  top: number
  left: number
  /** Height available to the panel; its content scrolls beyond it. */
  maxHeight: number
  maxWidth: number
  /** The placement actually used (after a flip). */
  placement: FloatingPlacement
}

/** Below this many pixels a panel no longer stays attached to its anchor; it overlaps it instead. */
const MIN_ATTACHED = 120

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(v, hi))
}

/**
 * Where to put a panel of `size` next to `anchor` inside `viewport`.
 * - The panel goes on the requested side; it flips when it does not fit there and the other side
 *   has more room.
 * - When it fits neither side it stays attached and scrolls inside (maxHeight), unless the room
 *   is below 120 px; then it overlaps the anchor and may use the whole viewport height.
 * - It is always clamped inside the viewport, `margin` pixels from each edge.
 */
export function placeFloating(
  anchor: FloatingRect,
  size: { width: number; height: number },
  viewport: { width: number; height: number },
  placement: FloatingPlacement = "bottom-start",
  opts: { gap?: number; margin?: number } = {},
): FloatingPosition {
  const gap = opts.gap ?? 4
  const margin = opts.margin ?? 8
  const dash = placement.indexOf("-")
  const wanted = (dash < 0 ? placement : placement.slice(0, dash)) as "top" | "bottom"
  const align = dash < 0 ? "" : placement.slice(dash + 1)

  const below = viewport.height - margin - (anchor.bottom + gap)
  const above = anchor.top - gap - margin
  let side = wanted
  if (side === "bottom" && size.height > below && above > below) side = "top"
  else if (side === "top" && size.height > above && below > above) side = "bottom"

  const room = side === "bottom" ? below : above
  const fullHeight = Math.max(0, viewport.height - 2 * margin)
  const height = Math.min(size.height, fullHeight)
  let top: number
  let maxHeight: number
  if (height <= room || room >= MIN_ATTACHED) {
    maxHeight = Math.max(0, Math.min(room, fullHeight))
    top = side === "bottom" ? anchor.bottom + gap : anchor.top - gap - Math.min(height, maxHeight)
  } else {
    maxHeight = fullHeight
    top = side === "bottom" ? anchor.bottom + gap : anchor.top - gap - height
  }
  top = clamp(top, margin, viewport.height - margin - Math.min(height, maxHeight))

  const maxWidth = Math.max(0, viewport.width - 2 * margin)
  const width = Math.min(size.width, maxWidth)
  let left = align === "start" ? anchor.left : align === "end" ? anchor.right - width : (anchor.left + anchor.right - width) / 2
  left = clamp(left, margin, viewport.width - margin - width)

  return {
    top: Math.round(top),
    left: Math.round(left),
    maxHeight: Math.floor(maxHeight),
    maxWidth: Math.floor(maxWidth),
    placement: (align ? `${side}-${align}` : side) as FloatingPlacement,
  }
}
