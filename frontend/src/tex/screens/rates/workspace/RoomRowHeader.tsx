// The row header of a room in the price matrix (PRICING_WORKSPACE_UX.md §3.3.1, §3.3.5, §3.11;
// slice S9): the room's name, ★ BASE or its default derivation in words ("Standard ×1.15"), the
// row's label, and the room menu: Set as base (re-point formulas), Derive from…, Capacity…
// (a Drawer; the effective capacity from the server as placeholders), Move up / down, Remove
// (inline confirmation with the dependent rows). Every change is one workspace history entry.
import { memo, useMemo, useRef, useState, type RefObject } from "react"
import { ArrowDown, ArrowUp, GitBranch, MoreHorizontal, Star, Trash2, Users } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { useTexT } from "../../../i18n"
import { Button, Checkbox, Drawer, Field, FormGrid, Input, Menu, MenuItem, MenuSeparator, Notice, Popover, Select } from "../../../ui"
import type { Tables } from "../lib/tables"
import type { RoomCapacity } from "../lib/types"
import { removeRoom, setBaseRoom, setDerivation, type MatrixRoom } from "./model.ts"
import { CAPACITY_FIELDS, moveRoom, roomHasFormulas, setRoomCapacity, type CapacityField, type GridRow } from "./matrixView.ts"
import { int, str } from "./rows.ts"

export type Edit = (label: string, fn: (tables: Tables) => Tables) => boolean

export interface RoomRowHeaderProps {
  room: MatrixRoom
  row: GridRow
  /** the row's label (Base person price, Formula, Resolved (per person) …) */
  rowLabel: string
  roomName: (roomType: string) => string
  /** "Standard ×1.15" for a derived room, "Manual price" for a manual one */
  derivation: string
  tables: Tables
  readOnly: boolean
  /** the room's position among the contract rooms (move up / down) */
  index: number
  count: number
  /** the effective capacity the server priced with (price_matrix), for the Capacity… placeholders */
  capacity?: RoomCapacity
  edit: Edit
}

type Open = "base" | "derive" | "remove" | "capacity" | null

/** Memoised: the header re-renders when its room, row, the tables or its state change, not when
 * the active cell moves. */
export const RoomRowHeader = memo(RoomRowHeaderImpl)

function RoomRowHeaderImpl(p: RoomRowHeaderProps) {
  const { t } = useTexT()
  const { room, row } = p
  const [open, setOpen] = useState<Open>(null)
  const wrap = useRef<HTMLSpanElement>(null)
  // the popovers are anchored to the room menu's button (focus returns there on close)
  const anchor = useMemo<RefObject<HTMLElement | null>>(
    () => ({
      get current() {
        return wrap.current?.querySelector<HTMLElement>('button[aria-haspopup="menu"]') ?? wrap.current
      },
    }),
    [],
  )
  const name = p.roomName(room.room_type)
  const isBase = room.role === "base"
  const close = () => setOpen(null)

  return (
    <div
      role="rowheader"
      className={cn(
        "sticky left-0 z-[1] flex min-h-7 min-w-0 flex-col justify-center border-r border-b border-zinc-200 bg-white py-0.5 pr-1 pl-3 text-left",
        row.first && "border-t-2 border-t-zinc-200",
        isBase && "shadow-[inset_3px_0_0_0_var(--color-tex-500)]",
      )}
    >
      {row.first && (
        <span className="flex min-w-0 items-center gap-1.5">
          {isBase && <Star className="size-3.5 shrink-0 fill-tex-500 text-tex-600" aria-hidden />}
          <span className="min-w-0 truncate text-[11px] font-semibold tracking-wide text-zinc-900 uppercase">{name}</span>
          {isBase && <span className="shrink-0 rounded bg-tex-50 px-1 text-[10px] font-semibold text-tex-700 ring-1 ring-tex-200 ring-inset">{t("rates.ws.room.base")}</span>}
          {!p.readOnly && (
            <span ref={wrap} className="ml-auto shrink-0">
              <Menu label={t("rates.ws.room.menu", { room: name })} icon={<MoreHorizontal className="size-4" aria-hidden />} size="sm" className="size-6!">
                <MenuItem icon={<Star className="size-4" />} disabled={isBase} onSelect={() => setOpen("base")}>
                  {t("rates.ws.room.set_base")}
                </MenuItem>
                <MenuItem icon={<GitBranch className="size-4" />} disabled={isBase || p.count < 2} onSelect={() => setOpen("derive")}>
                  {t("rates.ws.room.derive")}
                </MenuItem>
                <MenuItem icon={<Users className="size-4" />} onSelect={() => setOpen("capacity")}>
                  {t("rates.ws.room.capacity")}
                </MenuItem>
                <MenuSeparator />
                <MenuItem icon={<ArrowUp className="size-4" />} disabled={p.index === 0} onSelect={() => p.edit(t("rates.ws.h.move_room", { room: name }), (tb) => moveRoom(tb, room.room_type, -1))}>
                  {t("rates.ws.room.move_up")}
                </MenuItem>
                <MenuItem
                  icon={<ArrowDown className="size-4" />}
                  disabled={p.index >= p.count - 1}
                  onSelect={() => p.edit(t("rates.ws.h.move_room", { room: name }), (tb) => moveRoom(tb, room.room_type, 1))}
                >
                  {t("rates.ws.room.move_down")}
                </MenuItem>
                <MenuSeparator />
                <MenuItem icon={<Trash2 className="size-4" />} tone="danger" onSelect={() => setOpen("remove")}>
                  {t("rates.ws.room.remove")}
                </MenuItem>
              </Menu>
            </span>
          )}
        </span>
      )}
      <span className={cn("truncate text-xs", row.kind === "resolved" ? "text-zinc-500" : "text-zinc-700", row.first ? "" : "pl-5")}>
        {p.rowLabel}
        {row.first && !isBase && p.derivation && <span className="text-slate-500"> · {p.derivation}</span>}
      </span>

      {open === "base" && <SetBasePopover {...p} anchor={anchor} name={name} onClose={close} />}
      {open === "derive" && <DerivePopover {...p} anchor={anchor} name={name} onClose={close} />}
      {open === "remove" && <RemovePopover {...p} anchor={anchor} name={name} onClose={close} />}
      {open === "capacity" && <CapacityDrawer {...p} name={name} onClose={close} />}
    </div>
  )
}

type PopProps = RoomRowHeaderProps & { anchor: RefObject<HTMLElement | null>; name: string; onClose: () => void }

function SetBasePopover(p: PopProps) {
  const { t } = useTexT()
  const [repoint, setRepoint] = useState(true)
  const previous = p.tables.rooms.find((r) => r.is_base && str(r.room_type) !== p.room.room_type)
  const prevName = previous ? p.roomName(str(previous.room_type)) : ""
  const keeps = roomHasFormulas(p.tables, p.room.room_type)
  return (
    <Popover open onClose={p.onClose} anchorRef={p.anchor} label={t("rates.ws.room.set_base_title", { room: p.name })} width="md">
      <div className="space-y-3 text-sm">
        <p className="text-zinc-700">{t("rates.ws.room.set_base_body", { room: p.name })}</p>
        {previous && <Checkbox label={t("rates.ws.room.repoint", { from: prevName, to: p.name })} checked={repoint} onChange={(e) => setRepoint(e.target.checked)} />}
        {keeps && <Notice tone="warning">{t("rates.ws.room.keeps_formulas", { room: p.name })}</Notice>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={p.onClose}>
            {t("core.action.cancel")}
          </Button>
          <Button
            size="sm"
            data-autofocus
            onClick={() => {
              p.edit(t("rates.ws.h.set_base", { room: p.name }), (tb) => setBaseRoom(tb, p.room.room_type, { repoint }).tables)
              p.onClose()
            }}
          >
            {t("rates.ws.room.set_base")}
          </Button>
        </div>
      </div>
    </Popover>
  )
}

function DerivePopover(p: PopProps) {
  const { t } = useTexT()
  const options = p.tables.rooms
    .map((r) => str(r.room_type))
    .filter((rt) => rt && rt !== p.room.room_type)
    .map((rt) => ({ value: rt, label: p.roomName(rt) }))
  const [base, setBase] = useState(p.room.defaultBase && p.room.defaultBase !== p.room.room_type ? p.room.defaultBase : (options[0]?.value ?? ""))
  const [allPeriods, setAllPeriods] = useState(true)
  const hasDefault = Boolean(p.room.defaultRule && str(p.room.defaultRule.base_room_type))
  return (
    <Popover open onClose={p.onClose} anchorRef={p.anchor} label={t("rates.ws.room.derive_title", { room: p.name })} width="md">
      <form
        className="space-y-3 text-sm"
        onSubmit={(e) => {
          e.preventDefault()
          if (!base) return
          p.edit(t("rates.ws.h.derive", { room: p.name }), (tb) => setDerivation(tb, p.room.room_type, base, { allPeriods }).tables)
          p.onClose()
        }}
      >
        <Field label={t("rates.f.base_room_type")} hint={t("rates.ws.room.derive_hint")}>
          <Select value={base} onChange={(e) => setBase(e.target.value)} options={options} data-autofocus />
        </Field>
        <Checkbox label={t("rates.ws.room.derive_periods")} checked={allPeriods} onChange={(e) => setAllPeriods(e.target.checked)} />
        {!hasDefault && <p className="text-xs text-zinc-500">{t("rates.ws.room.derive_no_formula")}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={p.onClose}>
            {t("core.action.cancel")}
          </Button>
          <Button size="sm" type="submit" disabled={!base}>
            {t("core.action.apply")}
          </Button>
        </div>
      </form>
    </Popover>
  )
}

function RemovePopover(p: PopProps) {
  const { t } = useTexT()
  const counts = removeRoom(p.tables, p.room.room_type).counts
  const parts = [
    counts.prices ? t("rates.ws.count.prices", { count: counts.prices }) : "",
    counts.occupancy ? t("rates.ws.count.occupancy", { count: counts.occupancy }) : "",
    counts.boards ? t("rates.ws.count.boards", { count: counts.boards }) : "",
  ].filter(Boolean)
  return (
    <Popover open onClose={p.onClose} anchorRef={p.anchor} label={t("rates.ws.room.remove_title", { room: p.name })} width="md">
      <div className="space-y-3 text-sm">
        <p className="text-zinc-700">{parts.length ? t("rates.ws.room.remove_body", { rows: parts.join(", ") }) : t("rates.ws.room.remove_body_none")}</p>
        {counts.derivedFrom > 0 && <Notice tone="warning">{t("rates.ws.room.remove_derived", { count: counts.derivedFrom, room: p.name })}</Notice>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={p.onClose} data-autofocus>
            {t("core.action.cancel")}
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={() => {
              p.edit(t("rates.ws.h.remove_room", { room: p.name }), (tb) => removeRoom(tb, p.room.room_type).tables)
              p.onClose()
            }}
          >
            {t("rates.ws.room.remove")}
          </Button>
        </div>
      </div>
    </Popover>
  )
}

const CAPACITY_LABEL: Record<CapacityField, string> = {
  max_adults: "rates.f.max_adults",
  max_children: "rates.f.max_children",
  max_occupants: "rates.f.max_occupants",
  min_adults: "rates.f.min_adults",
  included_adults: "rates.f.included_adults",
}

function CapacityDrawer(p: RoomRowHeaderProps & { name: string; onClose: () => void }) {
  const { t } = useTexT()
  const row = p.tables.rooms.find((r) => str(r.room_type) === p.room.room_type)
  const [form, setForm] = useState<Record<CapacityField, string>>(() => {
    const out = {} as Record<CapacityField, string>
    for (const f of CAPACITY_FIELDS) out[f] = int(row?.[f]) ? String(int(row?.[f])) : ""
    return out
  })
  const bad = CAPACITY_FIELDS.some((f) => form[f] !== "" && !/^[0-9]{1,2}$/.test(form[f]))
  const save = () => {
    if (bad) return
    const patch: Partial<Record<CapacityField, number>> = {}
    for (const f of CAPACITY_FIELDS) patch[f] = form[f] === "" ? 0 : parseInt(form[f], 10)
    p.edit(t("rates.ws.h.capacity", { room: p.name }), (tb) => setRoomCapacity(tb, p.room.room_type, patch))
    p.onClose()
  }
  return (
    <Drawer
      open
      onClose={p.onClose}
      title={t("rates.ws.room.capacity_title", { room: p.name })}
      footer={
        <>
          <Button variant="secondary" onClick={p.onClose}>
            {t("core.action.cancel")}
          </Button>
          <Button onClick={save} disabled={bad}>
            {t("core.action.apply")}
          </Button>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          save()
        }}
      >
        <p className="text-sm text-zinc-600">{t("rates.ws.room.capacity_intro")}</p>
        <FormGrid cols={2}>
          {CAPACITY_FIELDS.map((f) => (
            <Field key={f} label={t(CAPACITY_LABEL[f])} hint={f === "included_adults" ? t("rates.h.included_adults") : f === "min_adults" ? t("rates.h.min_adults") : t("rates.h.zero_room_type")}>
              <Input
                inputMode="numeric"
                value={form[f]}
                placeholder={p.capacity ? String(p.capacity[f]) : t("rates.common.auto")}
                aria-invalid={form[f] !== "" && !/^[0-9]{1,2}$/.test(form[f]) ? true : undefined}
                onChange={(e) => setForm((x) => ({ ...x, [f]: e.target.value.trim() }))}
              />
            </Field>
          ))}
        </FormGrid>
        <button type="submit" hidden />
      </form>
    </Drawer>
  )
}
