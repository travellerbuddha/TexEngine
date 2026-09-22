import { useTexT } from "../../../../i18n"
import { date as fmtDate, nightsBetween } from "../../../../lib/format"
import { Notice } from "../../../../ui"
import { RowsEditor } from "../../components/RowsEditor"
import { BOARDS, enumLabel, enumOptions, OCC_TARGETS, OPS_ADJ, OPS_BOARD, OPS_OCC, opText, PERCENT_OPS } from "../../lib/options"
import { NEW_ROW } from "../../lib/tables"
import type { Row } from "../../lib/types"
import { intVal, splitCsv, WEEKDAY_CODES, weekdayName, yearsToMonths } from "../../lib/util"
import { bandOptions, contractRoomOptions, periodOptions, roomOptions, TabIntro, TabIssues, type TabProps } from "./shared"

// ─── Rooms ────────────────────────────────────────────────────────────────

export function RoomsTab({ doc, state, readOnly, issues, setTable }: TabProps) {
  const { t } = useTexT()
  const room = doc.contract_doc.pricing_basis === "ROOM"
  const rows = state.tables.rooms
  const bases = rows.filter((r) => r.is_base).length
  const cap = (rt: string) => doc.room_types.find((r) => r.name === rt)
  return (
    <div className="space-y-4">
      <TabIntro title={t("rates.tab.rooms")}>{t("rates.rooms.intro")}</TabIntro>
      <TabIssues issues={issues} tab="rooms" />
      {rows.length > 0 && bases !== 1 && <Notice tone="warning">{bases === 0 ? t("rates.rooms.no_base") : t("rates.rooms.many_base")}</Notice>}
      <RowsEditor
        caption={t("rates.tab.rooms")}
        readOnly={readOnly}
        rows={rows}
        onChange={(r) => setTable("rooms", r)}
        newRow={() => ({ ...NEW_ROW.rooms(), is_base: rows.length === 0 ? 1 : 0 })}
        addLabel={t("rates.rooms.add")}
        emptyText={t("rates.rooms.empty")}
        columns={[
          { key: "room_type", label: t("rates.f.room_type"), kind: "select", required: true, options: roomOptions(doc), className: "min-w-44" },
          { key: "is_base", label: t("rates.f.is_base"), kind: "check", help: t("rates.h.is_base") },
          { key: "max_adults", label: t("rates.f.max_adults"), kind: "int", help: t("rates.h.zero_room_type"), zeroLabel: t("rates.common.auto") },
          { key: "max_children", label: t("rates.f.max_children"), kind: "int", help: t("rates.h.zero_room_type"), zeroLabel: t("rates.common.auto") },
          { key: "max_occupants", label: t("rates.f.max_occupants"), kind: "int", help: t("rates.h.zero_room_type"), zeroLabel: t("rates.common.auto") },
          { key: "min_adults", label: t("rates.f.min_adults"), kind: "int", help: t("rates.h.min_adults"), zeroLabel: "1" },
          { key: "included_adults", label: t("rates.f.included_adults"), kind: "int", help: t("rates.h.included_adults"), disabled: () => !room, zeroLabel: t("rates.common.auto") },
        ]}
        describe={(r) => {
          const c = cap(String(r.room_type))
          if (!c) return null
          return t("rates.rooms.capacity", {
            adults: intVal(r.max_adults) || c.adults_capacity || 0,
            children: intVal(r.max_children) || c.children_capacity || 0,
            total: intVal(r.max_occupants) || c.max_total_occupants || 0,
          })
        }}
      />
    </div>
  )
}

// ─── Periods ──────────────────────────────────────────────────────────────

export function PeriodsTab({ state, readOnly, issues, setTable }: TabProps) {
  const { t } = useTexT()
  const rows = state.tables.periods
  return (
    <div className="space-y-4">
      <TabIntro title={t("rates.tab.periods")}>{t("rates.periods.intro")}</TabIntro>
      <TabIssues issues={issues} tab="periods" />
      <PeriodStrip rows={rows} />
      <RowsEditor
        caption={t("rates.tab.periods")}
        readOnly={readOnly}
        rows={rows}
        onChange={(r) => setTable("periods", r)}
        newRow={() => {
          const last = rows[rows.length - 1]
          return { ...NEW_ROW.periods(), start_date: last?.end_date ? nextDay(String(last.end_date)) : "" }
        }}
        addLabel={t("rates.periods.add")}
        emptyText={t("rates.periods.empty")}
        columns={[
          { key: "period_code", label: t("rates.f.period_code"), kind: "text", required: true, help: t("rates.h.period_code") },
          { key: "period_name", label: t("rates.f.period_name"), kind: "text", className: "min-w-40" },
          { key: "start_date", label: t("rates.f.start_date"), kind: "date", required: true },
          { key: "end_date", label: t("rates.f.end_date"), kind: "date", required: true, help: t("rates.h.end_inclusive") },
          { key: "weekdays", label: t("rates.f.weekdays"), kind: "weekdays", help: t("rates.h.weekdays") },
          { key: "adjustment_op", label: t("rates.f.adjustment_op"), kind: "select", options: enumOptions(t, "op", OPS_ADJ), placeholder: t("rates.common.none"), help: t("rates.h.adjustment_op"), className: "md:min-w-36" },
          {
            key: "adjustment_value",
            label: t("rates.f.value"),
            kind: "decimal",
            allowNegative: true,
            disabled: (r) => !r.adjustment_op,
            suffix: (r) => (PERCENT_OPS.has(String(r.adjustment_op)) ? "%" : null),
          },
          { key: "priority", label: t("rates.f.priority"), kind: "int", help: t("rates.h.period_priority") },
        ]}
        describe={(r) => {
          const parts: string[] = []
          if (r.start_date && r.end_date && String(r.end_date) >= String(r.start_date))
            parts.push(t("rates.periods.days", { count: nightsBetween(String(r.start_date), String(r.end_date)) + 1 }))
          const wd = splitCsv(r.weekdays)
          if (wd.length) parts.push(t("rates.periods.only_days", { days: wd.map((d) => weekdayName(WEEKDAY_CODES.findIndex((c) => c.toLowerCase() === d.slice(0, 3).toLowerCase()))).join(", ") }))
          if (r.adjustment_op) parts.push(t("rates.periods.adjusted", { op: opText(String(r.adjustment_op), String(r.adjustment_value || "0")) }))
          return parts.join(" · ") || null
        }}
      />
    </div>
  )
}

function nextDay(iso: string) {
  const d = new Date(`${iso}T12:00:00`)
  d.setDate(d.getDate() + 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

/** Compact visual of the periods on a date axis (text labels, not colour only). */
function PeriodStrip({ rows }: { rows: Row[] }) {
  const { t } = useTexT()
  const valid = rows.filter((r) => r.start_date && r.end_date && String(r.end_date) >= String(r.start_date))
  if (valid.length < 2) return null
  const min = valid.reduce((m, r) => (String(r.start_date) < m ? String(r.start_date) : m), String(valid[0].start_date))
  const max = valid.reduce((m, r) => (String(r.end_date) > m ? String(r.end_date) : m), String(valid[0].end_date))
  const span = nightsBetween(min, max) + 1
  const base = valid.filter((r) => !r.weekdays)
  return (
    <figure className="rounded-lg border border-zinc-200 p-3" aria-label={t("rates.periods.strip")}>
      <div className="relative h-7 overflow-hidden rounded bg-zinc-100">
        {base.map((r, i) => {
          const left = (nightsBetween(min, String(r.start_date)) / span) * 100
          const width = ((nightsBetween(String(r.start_date), String(r.end_date)) + 1) / span) * 100
          return (
            <span
              key={r._key}
              title={`${r.period_code}: ${fmtDate(String(r.start_date))} – ${fmtDate(String(r.end_date))}`}
              className={`absolute inset-y-0 flex items-center justify-center overflow-hidden border-r border-white text-[10px] font-medium whitespace-nowrap ${i % 2 ? "bg-tex-200 text-tex-900" : "bg-tex-100 text-tex-900"}`}
              style={{ left: `${left}%`, width: `${width}%` }}
            >
              {String(r.period_code)}
            </span>
          )
        })}
      </div>
      <figcaption className="mt-1 flex justify-between text-[11px] text-zinc-500">
        <span>{fmtDate(min, "short")}</span>
        {valid.length !== base.length && <span>{t("rates.periods.strip_masked", { count: valid.length - base.length })}</span>}
        <span>{fmtDate(max, "short")}</span>
      </figcaption>
    </figure>
  )
}

// ─── Child age bands ──────────────────────────────────────────────────────

export function AgeBandsTab({ state, readOnly, issues, setTable }: TabProps) {
  const { t } = useTexT()
  const rows = state.tables.age_bands
  return (
    <div className="space-y-4">
      <TabIntro title={t("rates.tab.ages")}>{t("rates.ages.intro")}</TabIntro>
      <TabIssues issues={issues} tab="ages" />
      {rows.length === 0 && <Notice tone="info">{t("rates.ages.inherited")}</Notice>}
      <AgeStrip rows={rows} />
      <RowsEditor
        caption={t("rates.tab.ages")}
        readOnly={readOnly}
        rows={rows}
        onChange={(r) => setTable("age_bands", r)}
        newRow={() => {
          const last = rows[rows.length - 1]
          const to = last ? String(last.to_age || "") : ""
          const [ip = "0", fp = ""] = to.split(".")
          const from = to ? String((parseInt(ip, 10) || 0) + (/[1-9]/.test(fp) ? 1 : 0)) : "0"
          return { ...NEW_ROW.age_bands(), from_age: from }
        }}
        addLabel={t("rates.ages.add")}
        columns={[
          { key: "band_code", label: t("rates.f.band_code"), kind: "text", required: true, help: t("rates.h.band_code") },
          { key: "label", label: t("rates.f.band_label"), kind: "text", className: "min-w-36" },
          { key: "from_age", label: t("rates.f.from_age"), kind: "decimal", decimals: 2, help: t("rates.h.from_age") },
          { key: "to_age", label: t("rates.f.to_age"), kind: "decimal", decimals: 2, help: t("rates.h.to_age") },
          { key: "is_infant", label: t("rates.f.is_infant"), kind: "check", help: t("rates.h.is_infant") },
        ]}
        describe={(r) => {
          const a = yearsToMonths(String(r.from_age || "0"))
          const b = yearsToMonths(String(r.to_age || ""))
          if (a === null || b === null || b <= a) return <span className="text-rose-700">{t("rates.ages.invalid")}</span>
          return t("rates.ages.covers", { from: fmtAge(a, t), to: fmtAge(b, t), last: b - 1, first: a })
        }}
      />
    </div>
  )
}

function fmtAge(months: number, t: (k: string, p?: Record<string, string | number>) => string) {
  const y = Math.floor(months / 12)
  const m = months % 12
  return m ? t("rates.ages.years_months", { y, m }) : t("rates.ages.years", { count: y })
}

function AgeStrip({ rows }: { rows: Row[] }) {
  const { t } = useTexT()
  const bands = rows
    .map((r) => ({ key: r._key, code: String(r.band_code || "?"), a: yearsToMonths(String(r.from_age || "0")), b: yearsToMonths(String(r.to_age || "")), infant: Boolean(r.is_infant) }))
    .filter((x): x is { key: string; code: string; a: number; b: number; infant: boolean } => x.a !== null && x.b !== null && x.b > x.a)
  if (!bands.length) return null
  const top = Math.max(18 * 12, ...bands.map((x) => x.b))
  return (
    <figure className="rounded-lg border border-zinc-200 p-3" aria-label={t("rates.ages.strip")}>
      <div className="relative h-7 overflow-hidden rounded bg-zinc-100">
        {bands.map((x) => (
          <span
            key={x.key}
            className={`absolute inset-y-0 flex items-center justify-center overflow-hidden border-r border-white text-[10px] font-semibold ${x.infant ? "bg-sky-200 text-sky-900" : "bg-emerald-200 text-emerald-900"}`}
            style={{ left: `${(x.a / top) * 100}%`, width: `${((x.b - x.a) / top) * 100}%` }}
          >
            {x.code}
          </span>
        ))}
      </div>
      <figcaption className="mt-1 flex justify-between text-[11px] text-zinc-500">
        <span>0</span>
        <span>{t("rates.ages.adult_from", { age: fmtAge(Math.max(...bands.map((x) => x.b)), t) })}</span>
        <span>{Math.round(top / 12)}</span>
      </figcaption>
    </figure>
  )
}

// ─── Occupancy rules ─────────────────────────────────────────────────────

export function OccupancyTab({ doc, state, readOnly, issues, setTable }: TabProps) {
  const { t } = useTexT()
  const basis = doc.contract_doc.pricing_basis
  const bands = bandOptions(state)
  const rows = state.tables.occupancy_rules
  return (
    <div className="space-y-4">
      <TabIntro title={t("rates.tab.occupancy")}>
        <p>{t(`rates.occ.intro.${basis}`)}</p>
        <p className="mt-1">{t("rates.occ.precedence")}</p>
      </TabIntro>
      <TabIssues issues={issues} tab="occupancy" />
      {bands.length === 0 && <Notice tone="info">{t("rates.occ.no_bands")}</Notice>}
      <RowsEditor
        caption={t("rates.tab.occupancy")}
        readOnly={readOnly}
        rows={rows}
        onChange={(r) => setTable("occupancy_rules", r)}
        newRow={NEW_ROW.occupancy_rules}
        addLabel={t("rates.occ.add")}
        emptyText={t("rates.occ.empty")}
        columns={[
          { key: "target", label: t("rates.f.target"), kind: "select", required: true, options: enumOptions(t, "target", OCC_TARGETS) },
          { key: "position", label: t("rates.f.position"), kind: "int", help: t("rates.h.position"), disabled: (r) => r.target === "COMBINATION", max: 12 },
          { key: "age_band", label: t("rates.f.age_band"), kind: "select", options: bands, placeholder: t("rates.common.any"), disabled: (r) => r.target !== "CHILD" },
          { key: "combination", label: t("rates.f.combination"), kind: "text", help: t("rates.h.combination"), className: "w-24" },
          { key: "room_type", label: t("rates.f.room_type"), kind: "select", options: contractRoomOptions(doc, state), placeholder: t("rates.common.all_rooms"), className: "md:min-w-36" },
          { key: "period_code", label: t("rates.f.period"), kind: "select", options: periodOptions(state), placeholder: t("rates.common.all_periods"), className: "md:min-w-32" },
          { key: "op", label: t("rates.f.rule"), kind: "select", required: true, options: enumOptions(t, "op", OPS_OCC), className: "md:min-w-36" },
          { key: "value", label: t("rates.f.value"), kind: "decimal", allowNegative: true, disabled: (r) => r.op === "INHERIT", suffix: (r) => (PERCENT_OPS.has(String(r.op)) ? "%" : null) },
          { key: "is_override", label: t("rates.f.is_override"), kind: "check", help: t("rates.h.is_override") },
          { key: "note", label: t("rates.f.note"), kind: "text", className: "min-w-32" },
        ]}
        describe={(r) => describeOcc(r, t, doc.contract_doc.contract_currency)}
      />
    </div>
  )
}

function describeOcc(r: Row, t: (k: string, p?: Record<string, string | number>) => string, ccy: string) {
  const who =
    r.target === "COMBINATION"
      ? t("rates.occ.who.combination")
      : r.target === "ADULT"
        ? intVal(r.position)
          ? t("rates.occ.who.adult_n", { n: intVal(r.position) })
          : t("rates.occ.who.adult_any")
        : intVal(r.position)
          ? t("rates.occ.who.child_n", { n: intVal(r.position) })
          : t("rates.occ.who.child_any")
  const band = r.target === "CHILD" && r.age_band ? ` (${r.age_band})` : ""
  const v = String(r.value || "0")
  const what = r.op === "INHERIT" ? t("rates.occ.what.INHERIT") : t(`rates.occ.what.${r.op}`, { v, ccy })
  const scope: string[] = []
  if (r.combination) scope.push(t("rates.occ.only_combination", { c: String(r.combination) }))
  if (r.room_type) scope.push(String(r.room_type))
  if (r.period_code) scope.push(String(r.period_code))
  return `${who}${band}: ${what}${scope.length ? ` — ${scope.join(" · ")}` : ""}${r.is_override ? ` · ${t("rates.f.is_override")}` : ""}`
}

// ─── Boards ───────────────────────────────────────────────────────────────

export function BoardsTab({ doc, state, readOnly, issues, setTable }: TabProps) {
  const { t } = useTexT()
  const ccy = doc.contract_doc.contract_currency
  const rows = state.tables.boards
  const hasBase = rows.some((r) => r.is_base)
  return (
    <div className="space-y-4">
      <TabIntro title={t("rates.tab.boards")}>{t("rates.boards.intro")}</TabIntro>
      <TabIssues issues={issues} tab="boards" />
      {rows.length > 0 && !hasBase && <Notice tone="warning">{t("rates.boards.no_base")}</Notice>}
      <RowsEditor
        caption={t("rates.tab.boards")}
        readOnly={readOnly}
        rows={rows}
        onChange={(r) => setTable("boards", r)}
        newRow={() => ({ ...NEW_ROW.boards(), is_base: rows.length === 0 ? 1 : 0, board: rows.length === 0 ? "BB" : "HB" })}
        addLabel={t("rates.boards.add")}
        columns={[
          { key: "board", label: t("rates.f.board"), kind: "select", required: true, options: enumOptions(t, "board", BOARDS), className: "min-w-36" },
          { key: "is_base", label: t("rates.f.board_base"), kind: "check", help: t("rates.h.board_base") },
          { key: "op", label: t("rates.f.board_op"), kind: "select", options: enumOptions(t, "boardop", OPS_BOARD), required: true, disabled: (r) => Boolean(r.is_base), className: "md:min-w-44" },
          {
            key: "adult_amount",
            label: t("rates.f.adult_amount"),
            kind: "decimal",
            disabled: (r) => Boolean(r.is_base),
            suffix: (r) => (r.op === "ADJUST_PERCENT" ? "%" : ccy),
          },
          { key: "child_percent", label: t("rates.f.child_percent"), kind: "decimal", suffix: () => "%", disabled: (r) => Boolean(r.is_base) || r.op !== "ADD" },
          { key: "infant_free", label: t("rates.f.infant_free"), kind: "check", disabled: (r) => Boolean(r.is_base) || r.op !== "ADD" },
          { key: "room_type", label: t("rates.f.room_type"), kind: "select", options: contractRoomOptions(doc, state), placeholder: t("rates.common.all_rooms") },
          { key: "period_code", label: t("rates.f.period"), kind: "select", options: periodOptions(state), placeholder: t("rates.common.all_periods") },
          { key: "label", label: t("rates.f.board_label"), kind: "text" },
        ]}
        describe={(r) => {
          const name = enumLabel(t, "board", String(r.board))
          if (r.is_base) return t("rates.boards.desc_base", { board: name })
          const v = String(r.adult_amount || "0")
          if (r.op === "ADJUST_PERCENT") return t("rates.boards.desc_pct", { board: name, v })
          if (r.op === "ABSOLUTE") return t("rates.boards.desc_abs", { board: name, v, ccy })
          return t("rates.boards.desc_add", { board: name, v, ccy, child: String(r.child_percent || "50") }) + (r.infant_free ? ` ${t("rates.boards.infants_free")}` : "")
        }}
      />
    </div>
  )
}

// ─── Rate plans ───────────────────────────────────────────────────────────

export function RatePlansTab({ doc, state, readOnly, issues, setTable, lookups }: TabProps) {
  const { t } = useTexT()
  const rows = state.tables.rate_plans
  const planName = (n: string) => doc.rate_plan_options.find((p) => p.name === n)?.rate_plan_name ?? n
  return (
    <div className="space-y-4">
      <TabIntro title={t("rates.tab.plans")}>{t("rates.plans.intro")}</TabIntro>
      <TabIssues issues={issues} tab="plans" />
      <RowsEditor
        caption={t("rates.tab.plans")}
        readOnly={readOnly}
        rows={rows}
        onChange={(r) => setTable("rate_plans", r)}
        newRow={NEW_ROW.rate_plans}
        addLabel={t("rates.plans.add")}
        emptyText={t("rates.plans.empty")}
        columns={[
          {
            key: "rate_plan",
            label: t("rates.f.rate_plan"),
            kind: "select",
            required: true,
            className: "min-w-44",
            options: doc.rate_plan_options.map((p) => ({ value: p.name, label: p.rate_plan_name })),
          },
          { key: "op", label: t("rates.f.adjustment"), kind: "select", options: enumOptions(t, "op", OPS_ADJ), placeholder: t("rates.common.no_adjustment"), help: t("rates.h.plan_op"), className: "md:min-w-36" },
          { key: "value", label: t("rates.f.value"), kind: "decimal", allowNegative: true, disabled: (r) => !r.op, suffix: (r) => (PERCENT_OPS.has(String(r.op)) ? "%" : null) },
          { key: "refundable", label: t("rates.f.refundable"), kind: "check" },
          { key: "boards", label: t("rates.f.boards"), kind: "csv", options: enumOptions(t, "board", BOARDS), allLabel: t("rates.common.all_boards") },
          {
            key: "cancellation_policy",
            label: t("rates.f.cancellation_policy"),
            kind: "select",
            placeholder: t("rates.common.plan_default"),
            options: (lookups?.cancellation_policies ?? []).map((p) => ({ value: p.name, label: p.policy_name })),
            className: "min-w-40",
          },
          {
            key: "payment_policy",
            label: t("rates.f.payment_policy"),
            kind: "select",
            placeholder: t("rates.common.plan_default"),
            options: (lookups?.payment_policies ?? []).map((p) => ({ value: p.name, label: p.policy_name })),
            className: "min-w-40",
          },
        ]}
        describe={(r) => {
          if (!r.rate_plan) return null
          const adj = r.op ? t("rates.plans.desc_adj", { op: opText(String(r.op), String(r.value || "0")) }) : t("rates.plans.desc_same")
          return `${planName(String(r.rate_plan))}: ${adj} · ${r.refundable ? t("rates.f.refundable") : t("rates.plans.non_refundable")}`
        }}
      />
    </div>
  )
}
