// The advanced rule popover of a matrix cell (PRICING_WORKSPACE_UX.md §3.5; slice S9): a non-modal
// Popover named "Edit price: {room} · {period}" (the legacy dialog name, for helper continuity) with
// the rule (every op of the room context, INHERIT included, with its help text), the value, the
// room it derives from, and the periods it applies to (this / all / selected; one row per period).
// The op chosen is the op stored: nothing is re-interpreted or adjusted once (unlike the shorthand
// on the base room, O4). Focus returns to the cell on close.
//
// The occupancy ladder's variant (OccRulePopover, slice S11), named "Edit rule: {slot} · {period}":
// the guest and age band are fixed by the row; the rule (the occupancy ops, FIXED and INHERIT
// included), its value, the Rooms scope (all rooms, or chosen rooms: one row per room), "Always
// wins (override)", a note and the periods it applies to. On a child band row it can name one child
// position instead ("Child 2 · 7–11.99", a position row of its own), and on the single-use row
// (PERSON basis) switch it to "also when children travel" (§3.6.2, S16 re-review): the whole row
// switches, every period keeping its value (S16 re-review 2). A write the single-use row refuses (a
// special combination's cell, a relative rule the switch would carry) is said, and Apply waits;
// a row whose rule comes from All rooms or a pricing policy says so instead of switching (S16
// re-review 3).
import { useId, useMemo, useState, type RefObject } from "react"
import { useTexT } from "../../../i18n"
import { Button, Checkbox, DECIMAL_PLACES, DecimalInput, Field, Input, Popover, Segmented, Select } from "../../../ui"
import { enumOptions } from "../lib/options"
import { displayText, isAmountOp, normaliseDecimal, OPS_BY_CONTEXT, type ShOp } from "../lib/shorthand"
import { ALL_PERIODS, isRelativeOp } from "./model.ts"
import type { PopoverRule } from "./matrixView.ts"
import type { OccRule, SingleRefusal, SlotSwitch } from "./occupancy.ts"

type AppliesTo = "this" | "all" | "selected"

export interface RuleEditorPopoverProps {
  anchorRef: RefObject<HTMLElement | null>
  onClose: () => void
  /** display names */
  roomName: string
  periodName: string
  /** the cell: its period code ("" = All periods) */
  period: string
  /** every period code of the version, in column order */
  periods: { code: string; label: string }[]
  /** rooms a derived op may derive from (the room itself excluded) */
  baseOptions: { value: string; label: string }[]
  /** what the popover opens with: the cell's own rule, the text typed so far, or the row's default */
  initial: PopoverRule
  /** the cell has a row of its own (Remove is offered) */
  hasRule: boolean
  minorUnits: number
  ccy: string
  decimalMark: "." | ","
  onApply: (periods: string[], rule: PopoverRule | null) => void
}

export function RuleEditorPopover(p: RuleEditorPopoverProps) {
  const { t } = useTexT()
  const [op, setOp] = useState(p.initial.op || "ABSOLUTE")
  const [value, setValue] = useState(p.initial.value)
  const [base, setBase] = useState(p.initial.base || p.baseOptions[0]?.value || "")
  const [applies, setApplies] = useState<AppliesTo>("this")
  const [chosen, setChosen] = useState<string[]>(() => (p.period ? [p.period] : []))
  const opts = useMemo(() => enumOptions(t, "op", OPS_BY_CONTEXT.room), [t])
  const derived = isRelativeOp(op)
  const inherit = op === "INHERIT"
  const allCell = p.period === ALL_PERIODS

  const targets = applies === "all" ? [ALL_PERIODS] : applies === "selected" ? chosen : [p.period]
  const checked = inherit ? null : normaliseDecimal(value, { amount: isAmountOp("room", op as ShOp), minorUnits: p.minorUnits })
  const valueError = !inherit && value.trim() !== "" && checked && !checked.ok ? t(`rates.sh.err.${checked.code}`) : undefined
  const ready = (inherit || (checked?.ok ?? false)) && (!derived || Boolean(base)) && targets.length > 0
  const baseName = p.baseOptions.find((b) => b.value === base)?.label ?? base
  const canon = checked?.ok ? checked.value : value
  const rule = displayText(op as ShOp, canon, "room", { decimalMark: p.decimalMark })
  const where = applies === "this" ? p.periodName : applies === "all" ? t("rates.rates.all_periods") : targets.join(", ")
  const cell = `${p.roomName} · ${where}`
  const reading = !ready
    ? ""
    : inherit
      ? t("rates.ws.pop.reads_inherit", { cell })
      : derived
        ? t("rates.sh.read.formula", { cell, formula: op === "PERCENT_OF" ? t("rates.ws.formula_pct", { base: baseName, rule }) : t("rates.ws.formula", { base: baseName, rule }) })
        : t("rates.sh.read.price", { cell, amount: rule })
  const suffix = op === "ADJUST_PERCENT" || op === "PERCENT_OF" ? "%" : op === "MULTIPLY" ? "×" : p.ccy

  const apply = () => {
    if (!ready) return
    p.onApply(targets, { op, value: inherit ? "" : canon, base: derived ? base : "" })
  }

  return (
    <Popover open onClose={p.onClose} anchorRef={p.anchorRef} label={t("rates.rates.edit_cell", { cell: `${p.roomName} · ${p.periodName}` })} width="md">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          apply()
        }}
      >
        <Field label={t("rates.f.rule")} hint={t(`rates.op_help.${op}`)}>
          <Select value={op} onChange={(e) => setOp(e.target.value)} options={opts} data-autofocus />
        </Field>
        {!inherit && (
          <Field label={t("rates.f.value")} required error={valueError}>
            <DecimalInput value={value} onValueChange={setValue} decimals={DECIMAL_PLACES} allowNegative={op === "ADJUST_PERCENT"} suffix={suffix} />
          </Field>
        )}
        {derived && (
          <Field label={t("rates.f.base_room_type")} required hint={t("rates.h.base_room_type")}>
            <Select value={base} onChange={(e) => setBase(e.target.value)} options={p.baseOptions} placeholder={t("rates.common.choose")} />
          </Field>
        )}
        <AppliesToField periodName={p.periodName} periods={p.periods} allCell={allCell} applies={applies} onApplies={setApplies} chosen={chosen} onChosen={setChosen} />
        {reading && <p className="rounded-md bg-zinc-50 px-2.5 py-1.5 text-sm text-zinc-700">{reading}</p>}
        <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
          {p.hasRule && (
            <Button variant="ghost" size="sm" className="mr-auto text-rose-700! hover:bg-rose-50!" onClick={() => p.onApply([p.period], null)}>
              {t("rates.rates.remove_rule")}
            </Button>
          )}
          <Button variant="secondary" size="sm" onClick={p.onClose}>
            {t("core.action.cancel")}
          </Button>
          <Button size="sm" type="submit" disabled={!ready}>
            {t("core.action.apply")}
          </Button>
        </div>
      </form>
    </Popover>
  )
}

/** "Applies to": this period / All periods / selected periods (one row per period). */
function AppliesToField(p: {
  periodName: string
  periods: { code: string; label: string }[]
  allCell: boolean
  applies: AppliesTo
  onApplies: (v: AppliesTo) => void
  chosen: string[]
  onChosen: (update: (c: string[]) => string[]) => void
}) {
  const { t } = useTexT()
  return (
    <fieldset className="space-y-2">
      <legend className="mb-1 text-sm font-medium text-zinc-800">{t("rates.ws.pop.applies_to")}</legend>
      <Segmented<AppliesTo>
        size="sm"
        label={t("rates.ws.pop.applies_to")}
        value={p.applies}
        onChange={p.onApplies}
        options={[
          ...(p.allCell ? [] : [{ value: "this" as const, label: t("rates.ws.pop.this_period", { period: p.periodName }) }]),
          { value: p.allCell ? ("this" as const) : ("all" as const), label: t("rates.rates.all_periods") },
          ...(p.periods.length ? [{ value: "selected" as const, label: t("rates.ws.pop.selected_periods") }] : []),
        ]}
      />
      {p.applies === "selected" && (
        <div role="group" aria-label={t("rates.ws.pop.selected_periods")} className="flex flex-wrap gap-x-3 gap-y-1">
          {p.periods.map((x) => (
            <Checkbox
              key={x.code}
              label={x.label}
              checked={p.chosen.includes(x.code)}
              onChange={(e) => {
                const on = e.target.checked
                p.onChosen((c) => (on ? [...c, x.code] : c.filter((y) => y !== x.code)))
              }}
            />
          ))}
        </div>
      )}
      {p.applies !== "this" && <p className="text-xs text-zinc-500">{t("rates.ws.pop.one_row_each")}</p>}
    </fieldset>
  )
}

type RoomsScope = "all" | "chosen"

export interface OccRulePopoverProps {
  anchorRef: RefObject<HTMLElement | null>
  onClose: () => void
  /** the row's guest ("3rd adult", "Child 7–11.99") and the column's period name */
  slotName: string
  periodName: string
  /** the cell's period code ("" = All periods) */
  period: string
  periods: { code: string; label: string }[]
  /** the contract rooms (value = room type) */
  rooms: { value: string; label: string }[]
  /** the ladder's rooms scope ("" = all rooms) */
  scope: string
  initial: OccRule
  /** the cell has a row of its own (Remove is offered) */
  hasRule: boolean
  /** the reading sentence of a rule for this row, or for the slot it is switched to (no arithmetic) */
  reading: (op: string, value: string, where: string, to?: SlotSwitch) => string
  /** a child band row: the child positions a rule may name instead (1…positions; 0 none) */
  positions?: number
  /** the single-use row that may switch form (PERSON basis): the form it has */
  single?: "whole" | "children"
  /** the single-use row whose rule comes from All rooms or a pricing policy: it does not switch here */
  singleForeign?: boolean
  /** why a rule may not be written for these rooms and periods (with the switch, if any), or null */
  refusal?: (rooms: string[], periods: string[], to?: SlotSwitch) => SingleRefusal | null
  /** the guest's name for a switched slot ("Child 2 · Child 3–6.99") */
  slotNameAs?: (to: SlotSwitch) => string
  minorUnits: number
  ccy: string
  onApply: (rooms: string[], periods: string[], rule: OccRule | null, to?: SlotSwitch) => void
}

/** The ladder cell's rule popover (§3.5): the op chosen is the op stored, one row per room and
 * period; "Always wins" beats special combinations and every other rule for this guest. */
export function OccRulePopover(p: OccRulePopoverProps) {
  const { t } = useTexT()
  const [op, setOp] = useState(p.initial.op || "MULTIPLY")
  const [value, setValue] = useState(p.initial.value)
  const [isOverride, setIsOverride] = useState(p.initial.is_override)
  const [note, setNote] = useState(p.initial.note)
  const [applies, setApplies] = useState<AppliesTo>("this")
  const [chosen, setChosen] = useState<string[]>(() => (p.period ? [p.period] : []))
  const [roomsScope, setRoomsScope] = useState<RoomsScope>(p.scope ? "chosen" : "all")
  const [roomsChosen, setRoomsChosen] = useState<string[]>(() => (p.scope ? [p.scope] : []))
  // a child position instead of the band row ("0" = every child in the band), the single-use form
  const [position, setPosition] = useState("0")
  const [single, setSingle] = useState(p.single)
  const to: SlotSwitch | undefined = position !== "0" ? { position: Number(position) } : single && single !== p.single ? { single } : undefined
  const slotName = to && p.slotNameAs ? p.slotNameAs(to) : p.slotName
  const opts = useMemo(() => enumOptions(t, "op", OPS_BY_CONTEXT.occupancy), [t])
  const inherit = op === "INHERIT"
  const allCell = p.period === ALL_PERIODS
  const ids = useId()
  const singleHelpId = `${ids}-single-help`
  const singleNoteId = `${ids}-single-note`
  const refusedId = `${ids}-refused`

  const targets = applies === "all" ? [ALL_PERIODS] : applies === "selected" ? chosen : [p.period]
  const rooms = roomsScope === "all" ? [""] : roomsChosen
  const checked = inherit ? null : normaliseDecimal(value, { amount: isAmountOp("occupancy", op as ShOp), minorUnits: p.minorUnits })
  const valueError = !inherit && value.trim() !== "" && checked && !checked.ok ? t(`rates.sh.err.${checked.code}`) : undefined
  const refused = targets.length > 0 && rooms.length > 0 ? (p.refusal?.(rooms, targets, to) ?? null) : null
  const ready = (inherit || (checked?.ok ?? false)) && targets.length > 0 && rooms.length > 0 && !refused
  const canon = checked?.ok ? checked.value : value
  const where = applies === "this" ? p.periodName : applies === "all" ? t("rates.rates.all_periods") : targets.join(", ")
  const reading = ready ? p.reading(op, inherit ? "" : canon, `${slotName} · ${where}`, to) : ""
  const suffix = op === "ADJUST_PERCENT" || op === "PERCENT_OF" ? "%" : op === "MULTIPLY" ? "×" : p.ccy

  const apply = () => {
    if (!ready) return
    p.onApply(rooms, targets, { op, value: inherit ? "" : canon, is_override: isOverride, note: note.trim() }, to)
  }

  return (
    <Popover open onClose={p.onClose} anchorRef={p.anchorRef} label={t("rates.occ.pop.title", { cell: `${p.slotName} · ${p.periodName}` })} width="md">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          apply()
        }}
      >
        <Field label={t("rates.f.rule")} hint={t(`rates.op_help.${op}`)}>
          <Select value={op} onChange={(e) => setOp(e.target.value)} options={opts} data-autofocus />
        </Field>
        {!inherit && (
          <Field label={t("rates.f.value")} required error={valueError}>
            <DecimalInput value={value} onValueChange={setValue} decimals={DECIMAL_PLACES} allowNegative={op === "ADJUST_PERCENT"} suffix={suffix} />
          </Field>
        )}
        {(p.positions ?? 0) > 0 && (
          <Field label={t("rates.occ.pop.position")} hint={t("rates.occ.pop.position_help")}>
            <Select
              value={position}
              onChange={(e) => setPosition(e.target.value)}
              options={[
                { value: "0", label: t("rates.occ.pop.position_any") },
                ...Array.from({ length: p.positions ?? 0 }, (_, i) => ({ value: String(i + 1), label: t("rates.occ.pop.position_n", { n: i + 1 }) })),
              ]}
            />
          </Field>
        )}
        {p.single && (
          <div className="space-y-0.5">
            <Checkbox
              label={t("rates.occ.pop.single_children")}
              checked={single === "children"}
              onChange={(e) => setSingle(e.target.checked ? "children" : "whole")}
              aria-describedby={`${singleHelpId} ${singleNoteId}`}
            />
            <p id={singleHelpId} className="pl-6 text-xs text-zinc-500">
              {t("rates.occ.pop.single_children_help")}
            </p>
            {/* what Apply now does, said when the box changes (a live region there from the start) */}
            <p id={singleNoteId} role="status" aria-live="polite" className="pl-6 text-xs font-medium text-zinc-700">
              {single !== p.single ? t("rates.occ.pop.single_whole_row") : ""}
            </p>
          </div>
        )}
        {p.singleForeign && <p className="text-xs text-zinc-600">{t("rates.occ.pop.single_foreign")}</p>}
        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm font-medium text-zinc-800">{t("rates.occ.pop.rooms")}</legend>
          <Segmented<RoomsScope>
            size="sm"
            label={t("rates.occ.pop.rooms")}
            value={roomsScope}
            onChange={setRoomsScope}
            options={[
              { value: "all", label: t("rates.occ.ladder.all_rooms") },
              ...(p.rooms.length ? [{ value: "chosen" as const, label: t("rates.occ.pop.rooms_chosen") }] : []),
            ]}
          />
          {roomsScope === "chosen" && (
            <div role="group" aria-label={t("rates.occ.pop.rooms_chosen")} className="flex flex-wrap gap-x-3 gap-y-1">
              {p.rooms.map((x) => (
                <Checkbox
                  key={x.value}
                  label={x.label}
                  checked={roomsChosen.includes(x.value)}
                  onChange={(e) => {
                    const on = e.target.checked
                    setRoomsChosen((c) => (on ? [...c, x.value] : c.filter((y) => y !== x.value)))
                  }}
                />
              ))}
            </div>
          )}
          {roomsScope === "chosen" && roomsChosen.length > 1 && <p className="text-xs text-zinc-500">{t("rates.occ.pop.one_row_each_room")}</p>}
        </fieldset>
        <AppliesToField periodName={p.periodName} periods={p.periods} allCell={allCell} applies={applies} onApplies={setApplies} chosen={chosen} onChosen={setChosen} />
        <div className="space-y-0.5">
          <Checkbox label={t("rates.occ.pop.always_wins")} checked={isOverride} onChange={(e) => setIsOverride(e.target.checked)} />
          <p className="pl-6 text-xs text-zinc-500">{t("rates.occ.pop.always_wins_help")}</p>
        </div>
        <Field label={t("rates.f.note")}>
          <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={140} />
        </Field>
        {reading && <p className="rounded-md bg-zinc-50 px-2.5 py-1.5 text-sm text-zinc-700">{reading}</p>}
        <p id={refusedId} role="status" aria-live="polite" className={refused ? "rounded-md bg-rose-50 px-2.5 py-1.5 text-sm text-rose-800" : "sr-only"}>
          {refused === "card" ? t("rates.occ.pop.refused_card") : refused === "relative" ? t("rates.occ.pop.refused_relative") : ""}
        </p>
        <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
          {p.hasRule && !to && (
            <Button variant="ghost" size="sm" className="mr-auto text-rose-700! hover:bg-rose-50!" onClick={() => p.onApply([p.scope], [p.period], null)}>
              {t("rates.rates.remove_rule")}
            </Button>
          )}
          <Button variant="secondary" size="sm" onClick={p.onClose}>
            {t("core.action.cancel")}
          </Button>
          <Button size="sm" type="submit" disabled={!ready} aria-describedby={refused ? refusedId : undefined}>
            {t("core.action.apply")}
          </Button>
        </div>
      </form>
    </Popover>
  )
}
