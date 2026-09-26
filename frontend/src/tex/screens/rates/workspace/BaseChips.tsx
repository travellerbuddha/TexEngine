// The Base room and Base occupancy chips of the context header (PRICING_WORKSPACE_UX.md §3.2):
// "Base room" is a select in a popover (the row menu's Set as base, with its re-point checkbox);
// with the ROOM basis, "Base occupancy" is a popover stepper writing the base room's
// included_adults (0 = the room type's). Both are version edits through the workspace history
// (Undo puts them back), like the row menu's Set as base and Capacity… (S16 review). Read-only
// text where the version cannot be edited.
import { useId, useRef, useState } from "react"
import { ChevronDown, Minus, Plus } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { useTexT } from "../../../i18n"
import { Button, Checkbox, Field, IconButton, Input, Notice, Popover, Select } from "../../../ui"
import type { Tables } from "../lib/tables"
import { CHIP_BUTTON } from "./BasisPopover"
import { roomHasFormulas, setRoomCapacity } from "./matrixView.ts"
import { setBaseRoom } from "./model.ts"
import { int, str } from "./rows.ts"

export type HeaderEdit = (label: string, fn: (tables: Tables) => Tables) => boolean

/** The most adults a room price can include (the capacity fields' two digits). */
const MAX_INCLUDED = 99

export function BaseRoomChip({ tables, roomName, edit }: { tables: Tables; roomName: (rt: string) => string; edit?: HeaderEdit }) {
  const { t } = useTexT()
  const ref = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const rooms = tables.rooms.map((r) => str(r.room_type)).filter(Boolean)
  const base = str(tables.rooms.find((r) => r.is_base)?.room_type)
  const [choice, setChoice] = useState(base)
  const [repoint, setRepoint] = useState(true)
  const value = base ? roomName(base) : t("rates.common.none")
  if (!edit || !rooms.length) return <span className="truncate">{value}</span>
  const close = () => setOpen(false)
  const changed = Boolean(choice) && choice !== base
  const apply = () => {
    if (!changed) return
    edit(t("rates.ws.h.set_base", { room: roomName(choice) }), (tb) => setBaseRoom(tb, choice, { repoint: Boolean(base) && repoint }).tables)
    close()
  }
  return (
    <>
      <button
        ref={ref}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        className={cn(CHIP_BUTTON, "-my-0.5")}
        onClick={() => {
          setChoice(base || rooms[0])
          setRepoint(true)
          setOpen(!open)
        }}
      >
        <span className="truncate">{value}</span>
        <ChevronDown className="size-3.5 self-center text-zinc-500" aria-hidden />
      </button>
      <Popover open={open} onClose={close} anchorRef={ref} label={t("rates.f.is_base")} width="md">
        <form
          className="space-y-3 text-sm"
          onSubmit={(e) => {
            e.preventDefault()
            apply()
          }}
        >
          <Field label={t("rates.f.is_base")} hint={t("rates.h.is_base")}>
            <Select value={choice} options={rooms.map((rt) => ({ value: rt, label: roomName(rt) }))} onChange={(e) => setChoice(e.target.value)} data-autofocus />
          </Field>
          {changed && base && <Checkbox label={t("rates.ws.room.repoint", { from: roomName(base), to: roomName(choice) })} checked={repoint} onChange={(e) => setRepoint(e.target.checked)} />}
          {changed && roomHasFormulas(tables, choice) && <Notice tone="warning">{t("rates.ws.room.keeps_formulas", { room: roomName(choice) })}</Notice>}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={close}>
              {t("core.action.cancel")}
            </Button>
            <Button size="sm" type="submit" disabled={!changed}>
              {t("rates.ws.room.set_base")}
            </Button>
          </div>
        </form>
      </Popover>
    </>
  )
}

/** ROOM basis: the adults the base room's price covers, as the server built them (`effective`, the
 * effective included_adults); the stepper writes the room's own value (0 = the room type's). */
export function BaseOccupancyChip({
  tables,
  roomName,
  effective,
  stale,
  edit,
}: {
  tables: Tables
  roomName: (rt: string) => string
  /** the server's effective included adults of the base room (price_matrix capacity) */
  effective?: number
  stale?: boolean
  edit?: HeaderEdit
}) {
  const { t } = useTexT()
  const ref = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const base = str(tables.rooms.find((r) => r.is_base)?.room_type)
  const own = int(tables.rooms.find((r) => r.is_base)?.included_adults)
  const [text, setText] = useState("")
  const inputId = useId()
  const hintId = useId()
  const shown = effective ? t("rates.ws.base_occ.room", { count: effective }) : "—"
  if (!edit || !base) return <span className={cn(stale && "text-zinc-500")}>{shown}</span>
  // the stepper starts from what the prices include: the room's own value, else the effective one
  // (0 would read as "none"; typing 0 goes back to the room type's)
  const start = own || effective || 0
  const n = /^[0-9]{1,2}$/.test(text.trim()) ? parseInt(text.trim(), 10) : null
  const step = (d: number) => setText(String(Math.max(0, Math.min(MAX_INCLUDED, (n ?? start) + d))))
  const close = () => setOpen(false)
  const apply = () => {
    if (n === null) return
    // unchanged: the room's own value, or the effective one it already has from the room type
    if (n !== own && !(own === 0 && n === effective)) edit(t("rates.ws.h.capacity", { room: roomName(base) }), (tb) => setRoomCapacity(tb, base, { included_adults: n }))
    close()
  }
  const label = t("rates.f.included_adults")
  return (
    <>
      <button
        ref={ref}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        className={cn(CHIP_BUTTON, "-my-0.5", stale && "text-zinc-500")}
        onClick={() => {
          setText(String(start))
          setOpen(!open)
        }}
      >
        <span className="truncate">{shown}</span>
        <ChevronDown className="size-3.5 self-center text-zinc-500" aria-hidden />
      </button>
      <Popover open={open} onClose={close} anchorRef={ref} label={t("rates.ws.base_occ.title", { room: roomName(base) })} width="sm">
        <form
          className="space-y-3 text-sm"
          onSubmit={(e) => {
            e.preventDefault()
            apply()
          }}
        >
          <div className="space-y-1.5">
            <label htmlFor={inputId} className="block text-sm font-medium text-zinc-800">
              {label}
            </label>
            <div className="flex items-center gap-1.5">
              <IconButton label={t("rates.ws.base_occ.less")} icon={<Minus className="size-4" />} size="sm" disabled={(n ?? start) <= 0} onClick={() => step(-1)} />
              <Input
                id={inputId}
                inputMode="numeric"
                className="w-16! text-center"
                value={text}
                aria-describedby={hintId}
                aria-invalid={n === null ? true : undefined}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "ArrowUp" || e.key === "ArrowDown") {
                    e.preventDefault()
                    step(e.key === "ArrowUp" ? 1 : -1)
                  }
                }}
                data-autofocus
              />
              <IconButton label={t("rates.ws.base_occ.more")} icon={<Plus className="size-4" />} size="sm" disabled={(n ?? start) >= MAX_INCLUDED} onClick={() => step(1)} />
            </div>
            <p id={hintId} className="text-xs text-zinc-500">
              {t("rates.ws.base_occ.hint", { count: effective ?? 0 })}
            </p>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={close}>
              {t("core.action.cancel")}
            </Button>
            <Button size="sm" type="submit" disabled={n === null}>
              {t("core.action.apply")}
            </Button>
          </div>
        </form>
      </Popover>
    </>
  )
}
