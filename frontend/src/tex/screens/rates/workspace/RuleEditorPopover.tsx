// The advanced rule popover of a matrix cell (PRICING_WORKSPACE_UX.md §3.5; slice S9): a non-modal
// Popover named "Edit price: {room} · {period}" (the legacy dialog name, for helper continuity) with
// the rule (every op of the room context, INHERIT included, with its help text), the value, the
// room it derives from, and the periods it applies to (this / all / selected; one row per period).
// The op chosen is the op stored: nothing is re-interpreted or adjusted once (unlike the shorthand
// on the base room, O4). Focus returns to the cell on close.
import { useMemo, useState, type RefObject } from "react"
import { useTexT } from "../../../i18n"
import { Button, Checkbox, DECIMAL_PLACES, DecimalInput, Field, Popover, Segmented, Select } from "../../../ui"
import { enumOptions } from "../lib/options"
import { displayText, isAmountOp, normaliseDecimal, OPS_BY_CONTEXT, type ShOp } from "../lib/shorthand"
import { ALL_PERIODS, isRelativeOp } from "./model.ts"
import type { PopoverRule } from "./matrixView.ts"

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
        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm font-medium text-zinc-800">{t("rates.ws.pop.applies_to")}</legend>
          <Segmented<AppliesTo>
            size="sm"
            label={t("rates.ws.pop.applies_to")}
            value={applies}
            onChange={setApplies}
            options={[
              ...(allCell ? [] : [{ value: "this" as const, label: t("rates.ws.pop.this_period", { period: p.periodName }) }]),
              { value: allCell ? ("this" as const) : ("all" as const), label: t("rates.rates.all_periods") },
              ...(p.periods.length ? [{ value: "selected" as const, label: t("rates.ws.pop.selected_periods") }] : []),
            ]}
          />
          {applies === "selected" && (
            <div role="group" aria-label={t("rates.ws.pop.selected_periods")} className="flex flex-wrap gap-x-3 gap-y-1">
              {p.periods.map((x) => (
                <Checkbox
                  key={x.code}
                  label={x.label}
                  checked={chosen.includes(x.code)}
                  onChange={(e) => setChosen((c) => (e.target.checked ? [...c, x.code] : c.filter((y) => y !== x.code)))}
                />
              ))}
            </div>
          )}
          {applies !== "this" && <p className="text-xs text-zinc-500">{t("rates.ws.pop.one_row_each")}</p>}
        </fieldset>
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
