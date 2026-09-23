import { useId } from "react"
import { AlertTriangle, Plus, Trash2 } from "lucide-react"
import { useSession } from "../../../lib/session"
import { TEX_LANGS, useTexT } from "../../../i18n"
import { Button, DecimalInput, IconButton, Input, Segmented, Select } from "../../../ui"
import { isInteger } from "../lib"
import type { Condition, FieldKind, SegmentRules } from "../types"
import { fieldGroups, fieldHint, fieldLabel, lacksCurrency, opKey } from "./meta"

export { fieldKey, opKey } from "./meta"

export const MAX_CONDITIONS = 25
const NO_VALUE_OPS = new Set(["empty", "not_empty"])

/** Default operator/value for a field kind (a money condition takes the only currency, if there is one). */
export function blankCondition(field: string, kind: FieldKind, ops: string[], currencies: string[] = []): Condition {
  const op = kind === "bool" ? "is" : kind === "list" ? "contains" : kind === "str" ? "eq" : ops.includes("gte") ? "gte" : ops[0]
  const c: Condition = { field, op, value: kind === "bool" ? true : "" }
  if (kind === "money") c.currency = currencies.length === 1 ? currencies[0] : ""
  return c
}

/** Client-side check that mirrors the server's strict validation (the server validates again). */
export function conditionError(c: Condition, kind: FieldKind | undefined, t: (k: string) => string): string | null {
  if (!kind) return t("crm.seg.err.field")
  if (NO_VALUE_OPS.has(c.op) || kind === "bool") return null
  const v = String(c.value ?? "").trim()
  if (!v) return t("crm.seg.err.value")
  if (kind === "int" && !isInteger(v, true)) return t("crm.seg.err.int")
  if (kind === "money" && !/^-?\d+(\.\d+)?$/.test(v)) return t("crm.seg.err.money")
  if (lacksCurrency(c, kind)) return t("crm.seg.err.currency")
  return null
}

/** Rules as the server expects them: ints as numbers, booleans as booleans, money as a
 * decimal string with its currency. */
export function normalizeRules(rules: SegmentRules, fields: Record<string, FieldKind>): SegmentRules {
  return {
    match: rules.match,
    conditions: rules.conditions.map((c) => {
      const kind = fields[c.field]
      if (NO_VALUE_OPS.has(c.op)) return { field: c.field, op: c.op, value: null }
      if (kind === "bool") return { field: c.field, op: "is", value: c.value === true || c.value === "true" || c.value === 1 }
      if (kind === "int") return { field: c.field, op: c.op, value: Number(String(c.value).trim()) }
      if (kind === "money")
        return { field: c.field, op: c.op, value: String(c.value ?? "").trim(), currency: String(c.currency ?? "").trim().toUpperCase() }
      return { field: c.field, op: c.op, value: String(c.value ?? "").trim() }
    }),
  }
}

export function RuleBuilder({
  rules,
  onChange,
  fields,
  ops,
  currencies,
  readOnly,
}: {
  rules: SegmentRules
  onChange: (r: SegmentRules) => void
  fields: Record<string, FieldKind>
  ops: Record<FieldKind, string[]>
  currencies: string[]
  readOnly?: boolean
}) {
  const { t } = useTexT()
  const { boot } = useSession()
  const uid = useId()
  const groups = fieldGroups(t, fields)
  const update = (i: number, patch: Partial<Condition>) =>
    onChange({ ...rules, conditions: rules.conditions.map((c, j) => (j === i ? { ...c, ...patch } : c)) })
  const remove = (i: number) => onChange({ ...rules, conditions: rules.conditions.filter((_, j) => j !== i) })
  const add = () => {
    const f = "stays" in fields ? "stays" : Object.keys(fields)[0]
    if (!f) return
    onChange({ ...rules, conditions: [...rules.conditions, blankCondition(f, fields[f], ops[fields[f]] ?? [], currencies)] })
  }
  const listIds = { market: `${uid}-markets`, language: `${uid}-langs`, lifetime_currency: `${uid}-ccy` } as Record<string, string>

  const valueInput = (c: Condition, i: number, kind: FieldKind) => {
    const label = t("crm.seg.value_for", { field: fieldLabel(t, c.field) })
    if (NO_VALUE_OPS.has(c.op)) return <span className="text-xs text-zinc-500">{t("crm.seg.no_value")}</span>
    if (kind === "bool")
      return (
        <Select
          aria-label={label}
          disabled={readOnly}
          value={c.value === true || c.value === "true" || c.value === 1 ? "true" : "false"}
          onChange={(e) => update(i, { value: e.target.value === "true" })}
          options={[
            { value: "true", label: t("core.label.yes") },
            { value: "false", label: t("core.label.no") },
          ]}
        />
      )
    if (kind === "money") {
      const ccy = String(c.currency ?? "")
      const options = currencies.includes(ccy) || !ccy ? currencies : [ccy, ...currencies]
      return (
        <div className="flex gap-2">
          <div className="min-w-0 flex-1">
            <DecimalInput aria-label={label} disabled={readOnly} value={String(c.value ?? "")} onValueChange={(v) => update(i, { value: v })} />
          </div>
          <Select
            aria-label={t("crm.seg.currency_for", { field: fieldLabel(t, c.field) })}
            aria-invalid={!ccy || undefined}
            disabled={readOnly}
            value={ccy}
            onChange={(e) => update(i, { currency: e.target.value })}
            placeholder={t("crm.seg.currency")}
            options={options.map((x) => ({ value: x, label: x }))}
            className="w-28 shrink-0"
          />
        </div>
      )
    }
    if (kind === "int")
      return (
        <Input
          aria-label={label}
          disabled={readOnly}
          inputMode="numeric"
          value={String(c.value ?? "")}
          onChange={(e) => update(i, { value: e.target.value.replace(/[^\d-]/g, "") })}
          className="text-right tabular-nums"
        />
      )
    const multi = c.op === "in" || c.op === "not_in" || kind === "list"
    return (
      <Input
        aria-label={label}
        disabled={readOnly}
        list={multi ? undefined : listIds[c.field]}
        value={String(c.value ?? "")}
        placeholder={multi ? t("crm.seg.comma_ph") : undefined}
        onChange={(e) => update(i, { value: e.target.value })}
      />
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm text-zinc-700">{t("crm.seg.match_intro")}</span>
        <Segmented<"all" | "any">
          label={t("crm.seg.match")}
          size="sm"
          value={rules.match}
          onChange={(m) => !readOnly && onChange({ ...rules, match: m })}
          options={[
            { value: "all", label: t("crm.seg.match_all") },
            { value: "any", label: t("crm.seg.match_any") },
          ]}
        />
      </div>
      {rules.conditions.length === 0 ? (
        <p className="rounded-lg border border-dashed border-zinc-300 px-3 py-4 text-center text-sm text-zinc-500">{t("crm.seg.no_conditions")}</p>
      ) : (
        <ol className="space-y-2">
          {rules.conditions.map((c, i) => {
            const kind = fields[c.field]
            const err = conditionError(c, kind, t)
            const hint = kind ? fieldHint(t, c.field) : null
            const noCurrency = lacksCurrency(c, kind)
            return (
              <li key={i} className="rounded-lg border border-zinc-200 bg-zinc-50/60 p-2.5">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1.3fr)_minmax(0,0.9fr)_minmax(0,1.4fr)_auto] sm:items-center">
                  <Select
                    aria-label={t("crm.seg.field_n", { n: i + 1 })}
                    disabled={readOnly}
                    value={c.field}
                    onChange={(e) => {
                      const f = e.target.value
                      update(i, { currency: undefined, ...blankCondition(f, fields[f], ops[fields[f]] ?? [], currencies) })
                    }}
                    options={kind ? [] : [{ value: c.field, label: c.field }]}
                    groups={groups}
                  />
                  <Select
                    aria-label={t("crm.seg.op_n", { n: i + 1 })}
                    disabled={readOnly}
                    value={c.op}
                    onChange={(e) => update(i, { op: e.target.value })}
                    options={(kind ? ops[kind] ?? [] : [c.op]).map((o) => ({ value: o, label: t(opKey(o)) }))}
                  />
                  <div className="min-w-0">{kind ? valueInput(c, i, kind) : null}</div>
                  {!readOnly && (
                    <IconButton
                      label={t("crm.seg.remove_n", { n: i + 1 })}
                      icon={<Trash2 className="size-4" />}
                      size="sm"
                      onClick={() => remove(i)}
                      className="justify-self-end"
                    />
                  )}
                </div>
                {hint && <p className="mt-1 text-xs text-zinc-500">{hint}</p>}
                {err && !readOnly && (
                  <p className="mt-1 text-xs font-medium text-rose-700" role="alert">
                    {err}
                  </p>
                )}
                {readOnly && noCurrency && (
                  <p className="mt-1 flex items-center gap-1 text-xs font-medium text-amber-800">
                    <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
                    {t("crm.seg.warn_currency")}
                  </p>
                )}
                {i < rules.conditions.length - 1 && (
                  <p className="mt-2 text-[11px] font-semibold tracking-wider text-zinc-500 uppercase" aria-hidden>
                    {rules.match === "all" ? t("crm.seg.and") : t("crm.seg.or")}
                  </p>
                )}
              </li>
            )
          })}
        </ol>
      )}
      {!readOnly && (
        <Button
          variant="secondary"
          size="sm"
          icon={<Plus className="size-4" aria-hidden />}
          onClick={add}
          disabled={rules.conditions.length >= MAX_CONDITIONS}
        >
          {t("crm.seg.add_condition")}
        </Button>
      )}
      <datalist id={listIds.market}>
        {boot.markets.map((m) => (
          <option key={m.name} value={m.name}>
            {m.market_name}
          </option>
        ))}
      </datalist>
      <datalist id={listIds.language}>
        {TEX_LANGS.map((l) => (
          <option key={l.code} value={l.code}>
            {l.label}
          </option>
        ))}
      </datalist>
      <datalist id={listIds.lifetime_currency}>
        {currencies.map((c) => (
          <option key={c} value={c} />
        ))}
      </datalist>
    </div>
  )
}
