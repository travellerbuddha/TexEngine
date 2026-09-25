// "Add room" / "Add board" (PRICING_WORKSPACE_UX.md §3.4, §3.12; S16 re-review): a menu button whose
// items add a row. Choosing and adding are separate gestures: the arrow keys only move between the
// items, Enter/Space or a click adds one. A native <select> that added in its change handler added
// the first room on the first ArrowDown of a keyboard user reading its options (Chromium fires
// `change` on every arrow press of a closed select), then the next one on the next press.
import type { Ref } from "react"
import { Plus } from "lucide-react"
import { Menu, MenuItem } from "../../../ui"

export interface AddMenuProps {
  /** The button's text and the menu's name ("Add room"). */
  label: string
  items: readonly { value: string; label: string }[]
  onAdd: (value: string) => void
  /** Shown next to the disabled button when there is nothing left to add. */
  emptyText?: string
  /** The wrapper (focus its button with `.querySelector("button")`). */
  ref?: Ref<HTMLSpanElement>
  className?: string
  /** data-add-room / data-add-board on the wrapper (where the focus goes when no cell is left). */
  marker?: string
}

export function AddMenu({ label, items, onAdd, emptyText, ref, className, marker }: AddMenuProps) {
  return (
    <span ref={ref} className={className ?? "inline-flex flex-wrap items-center gap-2"} {...(marker ? { [`data-${marker}`]: "" } : {})}>
      <Menu label={label} text={label} icon={<Plus className="size-4" aria-hidden />} variant="secondary" size="sm" disabled={!items.length}>
        {items.map((i) => (
          <MenuItem key={i.value} onSelect={() => onAdd(i.value)}>
            {i.label}
          </MenuItem>
        ))}
      </Menu>
      {!items.length && emptyText && <span className="text-xs text-zinc-500">{emptyText}</span>}
    </span>
  )
}
