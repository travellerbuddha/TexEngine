import { useState } from "react"
import { ChevronDown, ChevronRight, Copy, Plus, Trash2 } from "lucide-react"
import { useTexT } from "../../../../i18n"
import { Badge, Button, Checkbox, DecimalInput, Field, FormGrid, IconButton, Input, Select } from "../../../../ui"
import { DateRange } from "../../components/common"
import { CsvPicker } from "../../components/pickers"
import { BOARDS, enumLabel, enumOptions, PROMO_KINDS, PROMO_STAGE, PROMO_VALUE, STAY_MATCH } from "../../lib/options"
import { NEW_ROW } from "../../lib/tables"
import type { Row } from "../../lib/types"
import { intVal, newKey } from "../../lib/util"
import { contractRoomOptions, TabIntro, TabIssues, type TabProps } from "./shared"

/** Contract offers (TEX Contract Offer): early booking, long stay, free nights…
 * part of the frozen contract terms, unlike the hotel-wide Promotions. */
export function OffersTab({ doc, state, readOnly, issues, setTable }: TabProps) {
  const { t } = useTexT()
  const rows = state.tables.offers
  const [open, setOpen] = useState<string | null>(null)
  const set = (key: string, patch: Partial<Row>) => setTable("offers", rows.map((r) => (r._key === key ? ({ ...r, ...patch } as Row) : r)))
  const ccy = doc.contract_doc.contract_currency
  return (
    <div className="space-y-4">
      <TabIntro title={t("rates.tab.offers")}>{t("rates.offers.intro")}</TabIntro>
      <TabIssues issues={issues} tab="offers" />
      {rows.length === 0 && <p className="rounded-lg border border-dashed border-zinc-300 px-4 py-6 text-center text-sm text-zinc-500">{t("rates.offers.empty")}</p>}
      <ul className="space-y-2">
        {rows.map((r, i) => {
          const expanded = open === r._key
          const panelId = `offer-${r._key}`
          return (
            <li key={r._key} className="rounded-lg border border-zinc-200">
              <div className="flex flex-wrap items-center gap-2 px-3 py-2">
                <button type="button" aria-expanded={expanded} aria-controls={panelId} onClick={() => setOpen(expanded ? null : r._key)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
                  {expanded ? <ChevronDown className="size-4 shrink-0 text-zinc-500" aria-hidden /> : <ChevronRight className="size-4 shrink-0 text-zinc-500" aria-hidden />}
                  <span className="font-mono text-sm font-semibold text-zinc-900">{String(r.offer_code || "—")}</span>
                  <span className="truncate text-sm text-zinc-700">{String(r.offer_name || "")}</span>
                </button>
                <Badge tone="brand">{enumLabel(t, "promo_kind", String(r.kind))}</Badge>
                <Badge>{offerValue(r, t, ccy)}</Badge>
                {r.exclusive ? <Badge tone="warning">{t("rates.f.exclusive")}</Badge> : r.stackable ? <Badge tone="success">{t("rates.f.stackable")}</Badge> : null}
                {!readOnly && (
                  <span className="flex gap-0.5">
                    <IconButton size="sm" label={t("rates.common.duplicate_row", { n: i + 1 })} icon={<Copy className="size-3.5" />} onClick={() => setTable("offers", [...rows.slice(0, i + 1), { ...r, _key: newKey(), offer_code: `${r.offer_code}2` }, ...rows.slice(i + 1)])} />
                    <IconButton size="sm" label={t("rates.common.delete_row", { n: i + 1 })} icon={<Trash2 className="size-3.5" />} onClick={() => setTable("offers", rows.filter((x) => x !== r))} />
                  </span>
                )}
              </div>
              {expanded && (
                <div id={panelId} className="space-y-4 border-t border-zinc-100 px-3 py-3">
                  <OfferForm row={r} readOnly={readOnly} onChange={(p) => set(r._key, p)} roomOptions={contractRoomOptions(doc, state)} ccy={ccy} />
                </div>
              )}
              {!expanded && (
                <p className="px-3 pb-2 pl-9 text-xs text-zinc-500">
                  {t("rates.offers.sale")} <DateRange from={String(r.sale_from || "") || null} to={String(r.sale_to || "") || null} /> · {t("rates.offers.stay")} <DateRange from={String(r.stay_from || "") || null} to={String(r.stay_to || "") || null} />
                </p>
              )}
            </li>
          )
        })}
      </ul>
      {!readOnly && (
        <Button
          variant="secondary"
          size="sm"
          icon={<Plus className="size-4" aria-hidden />}
          onClick={() => {
            const row = { ...(NEW_ROW.offers() as Row), _key: newKey() }
            setTable("offers", [...rows, row])
            setOpen(row._key)
          }}
        >
          {t("rates.offers.add")}
        </Button>
      )}
    </div>
  )
}

function offerValue(r: Row, t: (k: string, p?: Record<string, string | number>) => string, ccy: string) {
  const v = String(r.value || "0")
  switch (r.value_type) {
    case "PERCENT":
      return `−${v} %`
    case "FIXED_STAY":
      return t("rates.offers.v_fixed_stay", { v, ccy })
    case "FIXED_NIGHT":
      return t("rates.offers.v_fixed_night", { v, ccy })
    case "MULTIPLIER":
      return `× ${v}`
    case "FREE_NIGHTS":
      return t("rates.offers.v_free", { stay: intVal(r.free_nights_stay), pay: intVal(r.free_nights_pay) })
    default:
      return enumLabel(t, "promo_value", String(r.value_type))
  }
}

function OfferForm({
  row,
  readOnly,
  onChange,
  roomOptions,
  ccy,
}: {
  row: Row
  readOnly: boolean
  onChange: (p: Partial<Row>) => void
  roomOptions: { value: string; label: string }[]
  ccy: string
}) {
  const { t } = useTexT()
  const s = (k: string) => String(row[k] ?? "")
  const n = (k: string) => String(intVal(row[k]))
  const int = (k: string) => (
    <Input type="number" min={0} step={1} disabled={readOnly} value={n(k)} onChange={(e) => onChange({ [k]: intVal(e.target.value) })} />
  )
  const vt = s("value_type")
  return (
    <>
      <FormGrid cols={3}>
        <Field label={t("rates.f.offer_code")} required hint={t("rates.h.offer_code")}>
          <Input disabled={readOnly} value={s("offer_code")} onChange={(e) => onChange({ offer_code: e.target.value.toUpperCase() })} />
        </Field>
        <Field label={t("rates.f.offer_name")}>
          <Input disabled={readOnly} value={s("offer_name")} onChange={(e) => onChange({ offer_name: e.target.value })} />
        </Field>
        <Field label={t("rates.f.kind")}>
          <Select disabled={readOnly} value={s("kind")} onChange={(e) => onChange({ kind: e.target.value })} options={enumOptions(t, "promo_kind", PROMO_KINDS)} />
        </Field>
        <Field label={t("rates.f.value_type")} hint={t(`rates.promo_value_help.${vt || "PERCENT"}`)}>
          <Select disabled={readOnly} value={vt} onChange={(e) => onChange({ value_type: e.target.value })} options={enumOptions(t, "promo_value", PROMO_VALUE)} />
        </Field>
        {vt !== "FREE_NIGHTS" && vt !== "VALUE_ADDED" && (
          <Field label={t("rates.f.value")}>
            <DecimalInput disabled={readOnly} value={s("value")} onValueChange={(v) => onChange({ value: v })} decimals={6} suffix={vt === "PERCENT" ? "%" : vt === "MULTIPLIER" ? "×" : ccy} />
          </Field>
        )}
        {vt === "FREE_NIGHTS" && (
          <>
            <Field label={t("rates.f.free_nights_stay")} hint={t("rates.h.free_nights")}>
              {int("free_nights_stay")}
            </Field>
            <Field label={t("rates.f.free_nights_pay")}>{int("free_nights_pay")}</Field>
          </>
        )}
        <Field label={t("rates.f.stage")} hint={t(`rates.stage_help.${s("stage") || "SELL"}`)}>
          <Select disabled={readOnly} value={s("stage")} onChange={(e) => onChange({ stage: e.target.value })} options={enumOptions(t, "stage", PROMO_STAGE)} />
        </Field>
      </FormGrid>
      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold text-zinc-900">{t("rates.offers.dates")}</legend>
        <FormGrid cols={4}>
          <Field label={t("rates.f.sale_from")}>
            <Input type="date" disabled={readOnly} value={s("sale_from")} onChange={(e) => onChange({ sale_from: e.target.value })} />
          </Field>
          <Field label={t("rates.f.sale_to")}>
            <Input type="date" disabled={readOnly} value={s("sale_to")} onChange={(e) => onChange({ sale_to: e.target.value })} />
          </Field>
          <Field label={t("rates.f.stay_from")}>
            <Input type="date" disabled={readOnly} value={s("stay_from")} onChange={(e) => onChange({ stay_from: e.target.value })} />
          </Field>
          <Field label={t("rates.f.stay_to")}>
            <Input type="date" disabled={readOnly} value={s("stay_to")} onChange={(e) => onChange({ stay_to: e.target.value })} />
          </Field>
          <Field label={t("rates.f.stay_match")} hint={t(`rates.stay_match_help.${s("stay_match") || "ANY_NIGHT"}`)} className="sm:col-span-2">
            <Select disabled={readOnly} value={s("stay_match")} onChange={(e) => onChange({ stay_match: e.target.value })} options={enumOptions(t, "stay_match", STAY_MATCH)} />
          </Field>
          <Field label={t("rates.f.min_nights")} hint={t("rates.h.zero_no_limit")}>
            {int("min_nights")}
          </Field>
          <Field label={t("rates.f.max_nights")} hint={t("rates.h.zero_no_limit")}>
            {int("max_nights")}
          </Field>
          <Field label={t("rates.f.min_lead_days")} hint={t("rates.h.min_lead_days")}>
            {int("min_lead_days")}
          </Field>
          <Field label={t("rates.f.max_lead_days")} hint={t("rates.h.max_lead_days")}>
            {int("max_lead_days")}
          </Field>
        </FormGrid>
      </fieldset>
      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold text-zinc-900">{t("rates.offers.eligibility")}</legend>
        <FormGrid cols={3}>
          <Field label={t("rates.f.room_types")}>
            <CsvPicker disabled={readOnly} value={s("room_types")} onChange={(v) => onChange({ room_types: v })} options={roomOptions} label={t("rates.f.room_types")} allLabel={t("rates.common.all_rooms")} />
          </Field>
          <Field label={t("rates.f.boards")}>
            <CsvPicker disabled={readOnly} value={s("boards")} onChange={(v) => onChange({ boards: v })} options={enumOptions(t, "board", BOARDS)} label={t("rates.f.boards")} allLabel={t("rates.common.all_boards")} />
          </Field>
        </FormGrid>
      </fieldset>
      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold text-zinc-900">{t("rates.offers.combination")}</legend>
        <p className="text-xs text-zinc-500">{t("rates.h.stacking_rules")}</p>
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          <Checkbox disabled={readOnly} label={t("rates.f.stackable")} checked={Boolean(row.stackable)} onChange={(e) => onChange({ stackable: e.target.checked ? 1 : 0 })} />
          <Checkbox disabled={readOnly} label={t("rates.f.exclusive")} checked={Boolean(row.exclusive)} onChange={(e) => onChange({ exclusive: e.target.checked ? 1 : 0 })} />
        </div>
        <FormGrid cols={3}>
          <Field label={t("rates.f.priority")} hint={t("rates.h.promo_priority")}>
            <Input type="number" step={1} disabled={readOnly} value={n("priority")} onChange={(e) => onChange({ priority: intVal(e.target.value) })} />
          </Field>
          <Field label={t("rates.f.offer_group")} hint={t("rates.h.promo_group")}>
            <Input disabled={readOnly} value={s("offer_group")} onChange={(e) => onChange({ offer_group: e.target.value })} />
          </Field>
        </FormGrid>
      </fieldset>
    </>
  )
}
