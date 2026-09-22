import type { ReactNode } from "react"
import { cn } from "../../../lib/utils"
import { useTexT } from "../../i18n"
import { DecimalInput, Input, Select } from "../../ui"
import type { GridCell } from "./types"

export const R_FIELDS = ["stop_sell", "stop_sell_mode", "min_los", "max_los", "cta", "ctd", "release_days", "min_advance", "max_advance"] as const
export const I_FIELDS = ["closed", "manual_adjustment", "oversell_limit"] as const
export type RField = (typeof R_FIELDS)[number]
export type IField = (typeof I_FIELDS)[number]
export type FieldKey = RField | IField

export const RATE_OPS = ["ABSOLUTE", "ADJUST_PERCENT", "ADD", "SUBTRACT"] as const

export interface Changes {
  on: Partial<Record<FieldKey, boolean>>
  v: Record<FieldKey, string>
  rateOn: boolean
  rateOp: string
  rateValue: string
}

export function emptyChanges(): Changes {
  return {
    on: {},
    v: {
      stop_sell: "STOP",
      stop_sell_mode: "",
      min_los: "0",
      max_los: "0",
      cta: "Yes",
      ctd: "Yes",
      release_days: "0",
      min_advance: "0",
      max_advance: "0",
      closed: "1",
      manual_adjustment: "0",
      oversell_limit: "0",
    },
    rateOn: false,
    rateOp: "ADJUST_PERCENT",
    rateValue: "",
  }
}

const tri = (b: boolean | null | undefined) => (b === true ? "Yes" : b === false ? "No" : "")
const n = (x: number | null | undefined) => String(x ?? 0)

/** Prefill from one grid cell: restrictions set at exactly this scope + pool inventory. */
export function changesFromCell(c: GridCell): Changes {
  const o = c.own
  const base = emptyChanges()
  return {
    ...base,
    v: {
      stop_sell: o?.stop_sell ?? "",
      stop_sell_mode: o?.stop_sell_mode ?? "",
      min_los: n(o?.min_los),
      max_los: n(o?.max_los),
      cta: tri(o?.cta),
      ctd: tri(o?.ctd),
      release_days: n(o?.release_days),
      min_advance: n(o?.min_advance),
      max_advance: n(o?.max_advance),
      closed: c.closed ? "1" : "0",
      manual_adjustment: n(c.manual_adjustment),
      oversell_limit: "0",
    },
  }
}

export interface BulkPayload {
  restrictions?: Record<string, string | number>
  inventory?: Record<string, number>
  rate?: { op: string; value: string }
}

export function toPayload(c: Changes): BulkPayload {
  const out: BulkPayload = {}
  const r: Record<string, string | number> = {}
  for (const f of R_FIELDS) {
    if (!c.on[f]) continue
    const v = c.v[f]
    r[f] = f === "stop_sell" || f === "stop_sell_mode" || f === "cta" || f === "ctd" ? v : parseInt(v || "0", 10) || 0
  }
  if (Object.keys(r).length) out.restrictions = r
  const inv: Record<string, number> = {}
  for (const f of I_FIELDS) if (c.on[f]) inv[f] = parseInt(c.v[f] || "0", 10) || 0
  if (Object.keys(inv).length) out.inventory = inv
  if (c.rateOn && c.rateValue !== "") out.rate = { op: c.rateOp, value: c.rateValue }
  return out
}

export function hasChanges(c: Changes) {
  const p = toPayload(c)
  return Boolean(p.restrictions || p.inventory || p.rate)
}

type T = (k: string, p?: Record<string, string | number>) => string

export function valueText(t: T, f: FieldKey, v: string): string {
  switch (f) {
    case "stop_sell":
      return v === "STOP" ? t("inventory.v.stop") : v === "OPEN" ? t("inventory.v.open_override") : t("inventory.v.no_rule")
    case "stop_sell_mode":
      return v ? t(`inventory.mode.${v}`) : t("inventory.mode.default")
    case "cta":
    case "ctd":
      return v === "Yes" ? t("inventory.v.closed") : v === "No" ? t("inventory.v.open_override") : t("inventory.v.no_rule")
    case "closed":
      return v === "1" ? t("inventory.v.closed_sale") : t("inventory.v.open_sale")
    case "manual_adjustment": {
      const x = parseInt(v || "0", 10) || 0
      return t("inventory.v.rooms_delta", { n: x > 0 ? `+${x}` : String(x) })
    }
    default: {
      const x = parseInt(v || "0", 10) || 0
      return x ? t("inventory.v.days", { count: x }) : t("inventory.v.no_rule")
    }
  }
}

export function describeChanges(t: T, c: Changes, ccy: string | null): string[] {
  const out: string[] = []
  for (const f of [...R_FIELDS, ...I_FIELDS]) if (c.on[f]) out.push(`${t(`inventory.f.${f}`)}: ${valueText(t, f, c.v[f])}`)
  if (c.rateOn && c.rateValue !== "") out.push(`${t("inventory.f.rate")}: ${t(`inventory.ratedesc.${c.rateOp}`, { v: c.rateValue, ccy: ccy ?? "" })}`)
  return out
}

/** Restriction / inventory / rate change fields. Each field has a "change this"
 * checkbox so bulk edits never overwrite fields the user did not touch. */
export function ChangeForm({
  value,
  onChange,
  canRestrict,
  canInventory,
  canRate,
  rateNote,
  ccy,
}: {
  value: Changes
  onChange: (c: Changes) => void
  canRestrict: boolean
  canInventory: boolean
  canRate: boolean
  rateNote?: ReactNode
  ccy: string | null
}) {
  const { t } = useTexT()
  const setV = (f: FieldKey, v: string) => onChange({ ...value, v: { ...value.v, [f]: v }, on: { ...value.on, [f]: true } })
  const setOn = (f: FieldKey, on: boolean) => onChange({ ...value, on: { ...value.on, [f]: on } })

  const row = (f: FieldKey, control: ReactNode, hint?: string) => (
    <div key={f} className={cn("grid grid-cols-[1.25rem_1fr] items-start gap-x-2 gap-y-1 rounded-md px-2 py-1.5 sm:grid-cols-[1.25rem_12rem_1fr]", value.on[f] && "bg-tex-50/70")}>
      <input
        id={`chg-${f}`}
        type="checkbox"
        checked={Boolean(value.on[f])}
        onChange={(e) => setOn(f, e.target.checked)}
        className="mt-2.5 size-4 accent-tex-600"
      />
      <label htmlFor={`chg-${f}`} className="pt-2 text-sm font-medium text-zinc-800">
        {t(`inventory.f.${f}`)}
        {hint && <span className="block text-xs font-normal text-zinc-500">{hint}</span>}
      </label>
      <div className="col-start-2 sm:col-start-3">{control}</div>
    </div>
  )
  const intInput = (f: FieldKey, min = 0) => (
    <Input
      type="number"
      inputMode="numeric"
      min={min}
      max={365}
      step={1}
      aria-label={t(`inventory.f.${f}`)}
      value={value.v[f]}
      onChange={(e) => setV(f, e.target.value)}
      className="w-28"
    />
  )
  const sel = (f: FieldKey, opts: { value: string; label: string }[]) => (
    <Select aria-label={t(`inventory.f.${f}`)} value={value.v[f]} onChange={(e) => setV(f, e.target.value)} options={opts} className="sm:max-w-64" />
  )
  const triOpts = [
    { value: "Yes", label: t("inventory.v.closed") },
    { value: "No", label: t("inventory.v.open_override") },
    { value: "", label: t("inventory.v.no_rule") },
  ]

  return (
    <div className="space-y-5">
      {canRestrict && (
        <fieldset className="space-y-1">
          <legend className="text-sm font-semibold text-zinc-900">{t("inventory.section.restrictions")}</legend>
          <p className="pb-1 text-xs text-zinc-500">{t("inventory.section.restrictions_hint")}</p>
          {row(
            "stop_sell",
            sel("stop_sell", [
              { value: "STOP", label: t("inventory.v.stop") },
              { value: "OPEN", label: t("inventory.v.open_override") },
              { value: "", label: t("inventory.v.no_rule") },
            ]),
          )}
          {row(
            "stop_sell_mode",
            sel("stop_sell_mode", [
              { value: "", label: t("inventory.mode.default") },
              { value: "STAY_THROUGH", label: t("inventory.mode.STAY_THROUGH") },
              { value: "ARRIVAL", label: t("inventory.mode.ARRIVAL") },
              { value: "DEPARTURE", label: t("inventory.mode.DEPARTURE") },
            ]),
            t("inventory.h.stop_sell_mode"),
          )}
          {row("min_los", intInput("min_los"), t("inventory.h.zero_none"))}
          {row("max_los", intInput("max_los"), t("inventory.h.zero_none"))}
          {row("cta", sel("cta", triOpts), t("inventory.h.cta"))}
          {row("ctd", sel("ctd", triOpts), t("inventory.h.ctd"))}
          {row("release_days", intInput("release_days"), t("inventory.h.release"))}
          {row("min_advance", intInput("min_advance"), t("inventory.h.min_advance"))}
          {row("max_advance", intInput("max_advance"), t("inventory.h.max_advance"))}
        </fieldset>
      )}
      {canInventory && (
        <fieldset className="space-y-1">
          <legend className="text-sm font-semibold text-zinc-900">{t("inventory.section.inventory")}</legend>
          <p className="pb-1 text-xs text-zinc-500">{t("inventory.section.inventory_hint")}</p>
          {row(
            "closed",
            sel("closed", [
              { value: "1", label: t("inventory.v.closed_sale") },
              { value: "0", label: t("inventory.v.open_sale") },
            ]),
          )}
          {row("manual_adjustment", intInput("manual_adjustment", -999), t("inventory.h.manual_adjustment"))}
          {row("oversell_limit", intInput("oversell_limit"), t("inventory.h.oversell"))}
        </fieldset>
      )}
      {canRate && (
        <fieldset className="space-y-1">
          <legend className="text-sm font-semibold text-zinc-900">{t("inventory.section.rate")}</legend>
          <p className="pb-1 text-xs text-zinc-500">{rateNote ?? t("inventory.section.rate_hint")}</p>
          <div className={cn("grid grid-cols-[1.25rem_1fr] items-start gap-x-2 gap-y-1 rounded-md px-2 py-1.5 sm:grid-cols-[1.25rem_12rem_1fr]", value.rateOn && "bg-tex-50/70")}>
            <input id="chg-rate" type="checkbox" checked={value.rateOn} onChange={(e) => onChange({ ...value, rateOn: e.target.checked })} className="mt-2.5 size-4 accent-tex-600" />
            <label htmlFor="chg-rate" className="pt-2 text-sm font-medium text-zinc-800">
              {t("inventory.f.rate")}
            </label>
            <div className="col-start-2 flex flex-wrap gap-2 sm:col-start-3">
              <Select
                aria-label={t("inventory.f.rate_op")}
                value={value.rateOp}
                onChange={(e) => onChange({ ...value, rateOp: e.target.value, rateOn: true })}
                options={RATE_OPS.map((o) => ({ value: o, label: t(`inventory.rateop.${o}`) }))}
                className="w-48"
              />
              <div className="w-36">
                <DecimalInput
                  aria-label={t("inventory.f.rate_value")}
                  value={value.rateValue}
                  onValueChange={(v) => onChange({ ...value, rateValue: v, rateOn: true })}
                  decimals={6}
                  suffix={value.rateOp === "ADJUST_PERCENT" ? "%" : (ccy ?? undefined)}
                  allowNegative={value.rateOp === "ADJUST_PERCENT"}
                />
              </div>
            </div>
          </div>
        </fieldset>
      )}
    </div>
  )
}
