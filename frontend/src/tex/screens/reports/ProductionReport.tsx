import { useMemo, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { Download, Info } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { useSession } from "../../lib/session"
import { date, money, num, pct } from "../../lib/format"
import { useSiteToday } from "../../lib/siteDay"
import { useTexT } from "../../i18n"
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  DataTable,
  EmptyState,
  ErrorState,
  Field,
  Money,
  Notice,
  Segmented,
  Select,
  Skeleton,
  type Column,
} from "../../ui"
import { cn } from "../../../lib/utils"
import { BarChart, type ChartDatum } from "./components/BarChart"
import { RangeFilter } from "./components/RangeFilter"
import {
  DIMENSIONS,
  TIME_DIMENSIONS,
  decimalSort,
  downloadCsv,
  groupLabel,
  presetRange,
  rangeProblem,
  slugify,
  toCsv,
  type CsvColumn,
  type Dimension,
  type RangePreset,
} from "./lib"
import { ReportsFrame } from "./ReportsFrame"

interface ProdRow {
  key: string
  currency: string
  bookings: number
  room_nights: number
  revenue: string
  guests: number
  adr: string | null
  avg_los: string | null
  avg_lead_days: string | null
  cost?: string
  margin?: string
  margin_pct?: string | null
}

interface ProdTotal {
  bookings: number
  room_nights: number
  revenue: string
  adr: string | null
}

interface ProdData {
  property: string
  from: string
  to: string
  basis: "stay" | "booking"
  group_by: Dimension
  cost_visible: boolean
  rows: ProdRow[]
  totals: Record<string, ProdTotal>
}

type Basis = "stay" | "booking"
type Metric = "room_nights" | "revenue"

const PRESETS = ["this_month", "last_month", "next_month", "next_30", "next_90", "last_30", "ytd", "this_year", "last_year"] as const
const HIDE = { sm: "hidden sm:table-cell", md: "hidden md:table-cell", lg: "hidden lg:table-cell" }

function isPreset(v: string | null): v is RangePreset {
  return !!v && ([...PRESETS, "custom"] as string[]).includes(v)
}

export default function ProductionReport() {
  const { t, locale } = useTexT()
  const { boot, property } = useSession()
  const [params, setParams] = useSearchParams()
  const today = useSiteToday()

  // filters live in the URL so a report view can be bookmarked or shared
  const preset: RangePreset = isPreset(params.get("period")) ? (params.get("period") as RangePreset) : "this_month"
  const [defFrom, defTo] = presetRange(preset === "custom" ? "this_month" : preset, today)
  const from = preset === "custom" ? params.get("from") || defFrom : defFrom
  const to = preset === "custom" ? params.get("to") || defTo : defTo
  const groupBy: Dimension = (DIMENSIONS as readonly string[]).includes(params.get("group") ?? "") ? (params.get("group") as Dimension) : "channel"
  const basis: Basis = params.get("basis") === "booking" ? "booking" : "stay"
  const includeCancelled = params.get("cancelled") === "1"

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === "") next.delete(k)
      else next.set(k, v)
    }
    setParams(next, { replace: true })
  }

  const problem = rangeProblem(from, to)
  const q = useTexQuery<ProdData>(
    "reports",
    "production",
    { property: property?.name, date_from: from, date_to: to, group_by: groupBy, basis, include_cancelled: includeCancelled ? 1 : 0 },
    [property?.name, from, to, groupBy, basis, includeCancelled],
    !problem && !!property,
  )
  const d = q.data
  const currencies = useMemo(() => (d ? Object.keys(d.totals).sort() : []), [d])
  const [ccyFilter, setCcyFilter] = useState("")
  const ccy = currencies.includes(ccyFilter) ? ccyFilter : ""
  const rows = useMemo(() => (d ? d.rows.filter((r) => !ccy || r.currency === ccy) : undefined), [d, ccy])
  const singleCcy = ccy || (currencies.length === 1 ? currencies[0] : "")
  const [metricPref, setMetric] = useState<Metric>("room_nights")
  const metric: Metric = singleCcy ? metricPref : "room_nights"
  const costVisible = Boolean(d?.cost_visible)
  const dimLabel = t(`reports.dim.${groupBy}`)
  const label = (key: string) => groupLabel(groupBy, key, boot, t, locale)
  const isTime = TIME_DIMENSIONS.includes(groupBy)

  const chartData: ChartDatum[] = useMemo(() => {
    if (!rows) return []
    const base = isTime ? [...rows].sort((a, b) => a.key.localeCompare(b.key)) : rows
    // revenue bars only when one currency is in view (never compare across currencies)
    const list = base.map((r) => ({
      key: `${r.key}|${r.currency}`,
      label: currencies.length > 1 && !ccy ? `${label(r.key)} · ${r.currency}` : label(r.key),
      value: metric === "revenue" ? (decimalSort(r.revenue) ?? 0) : r.room_nights,
      display: metric === "revenue" ? money(r.revenue, r.currency) : num(r.room_nights),
    }))
    if (isTime) return list.slice(-62)
    return [...list].sort((a, b) => b.value - a.value).slice(0, 12)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, metric, isTime, locale, currencies.length, ccy, groupBy, boot])

  const columns: Column<ProdRow>[] = [
    {
      key: "key",
      header: dimLabel,
      sortValue: (r) => (isTime ? r.key : label(r.key)),
      cell: (r) => (
        <span className="font-medium text-zinc-900" title={r.key}>
          {label(r.key)}
        </span>
      ),
    },
    ...(currencies.length > 1
      ? ([{ key: "currency", header: t("reports.col.currency"), hideBelow: "md", sortValue: (r) => r.currency }] satisfies Column<ProdRow>[])
      : []),
    { key: "bookings", header: t("reports.col.bookings"), align: "right", hideBelow: "sm", sortValue: (r) => r.bookings, cell: (r) => num(r.bookings) },
    { key: "room_nights", header: t("reports.col.room_nights"), align: "right", sortValue: (r) => r.room_nights, cell: (r) => num(r.room_nights) },
    { key: "guests", header: t("reports.col.guests"), align: "right", hideBelow: "lg", sortValue: (r) => r.guests, cell: (r) => num(r.guests) },
    {
      key: "revenue",
      header: t("reports.col.revenue"),
      align: "right",
      sortValue: (r) => decimalSort(r.revenue),
      cell: (r) => <Money amount={r.revenue} currency={r.currency} className="font-medium" />,
    },
    { key: "adr", header: t("reports.col.adr"), align: "right", hideBelow: "sm", sortValue: (r) => decimalSort(r.adr), cell: (r) => <Money amount={r.adr} currency={r.currency} /> },
    { key: "avg_los", header: t("reports.col.avg_los"), align: "right", hideBelow: "lg", sortValue: (r) => decimalSort(r.avg_los), cell: (r) => num(r.avg_los) },
    {
      key: "avg_lead_days",
      header: t("reports.col.avg_lead"),
      align: "right",
      hideBelow: "lg",
      sortValue: (r) => decimalSort(r.avg_lead_days),
      cell: (r) => num(r.avg_lead_days),
    },
    ...(costVisible
      ? ([
          { key: "cost", header: t("reports.col.cost"), align: "right", hideBelow: "md", sortValue: (r) => decimalSort(r.cost), cell: (r) => <Money amount={r.cost} currency={r.currency} muted /> },
          { key: "margin", header: t("reports.col.margin"), align: "right", hideBelow: "md", sortValue: (r) => decimalSort(r.margin), cell: (r) => <Money amount={r.margin} currency={r.currency} signed /> },
          { key: "margin_pct", header: t("reports.col.margin_pct"), align: "right", hideBelow: "md", sortValue: (r) => decimalSort(r.margin_pct), cell: (r) => pct(r.margin_pct) },
        ] satisfies Column<ProdRow>[])
      : []),
  ]

  const totalsInView = d ? currencies.filter((c) => !ccy || c === ccy).map((c) => [c, d.totals[c]] as const) : []

  const footer = totalsInView.length ? (
    <>
      {totalsInView.map(([c, tot]) => (
        <tr key={c} className="bg-zinc-50 font-semibold">
          {columns.map((col) => {
            const cls = cn(
              "border-t border-zinc-200 px-3 py-2 text-zinc-900",
              col.align === "right" ? "text-right tabular-nums" : "text-left",
              col.hideBelow && HIDE[col.hideBelow],
            )
            const v =
              col.key === "key" ? (
                <span>{totalsInView.length > 1 ? t("reports.total_ccy", { currency: c }) : t("core.label.total")}</span>
              ) : col.key === "currency" ? (
                c
              ) : col.key === "bookings" ? (
                num(tot.bookings)
              ) : col.key === "room_nights" ? (
                num(tot.room_nights)
              ) : col.key === "revenue" ? (
                <Money amount={tot.revenue} currency={c} />
              ) : col.key === "adr" ? (
                <Money amount={tot.adr} currency={c} />
              ) : null
            return col.key === "key" ? (
              <th key={col.key} scope="row" className={cls}>
                {v}
              </th>
            ) : (
              <td key={col.key} className={cls}>
                {v}
              </td>
            )
          })}
        </tr>
      ))}
    </>
  ) : undefined

  const exportCsv = () => {
    if (!d || !rows) return
    const cols: CsvColumn<ProdRow & { _total?: boolean }>[] = [
      { header: `${dimLabel} (${t("reports.csv.key")})`, value: (r) => (r._total ? "TOTAL" : r.key), text: true },
      { header: dimLabel, value: (r) => (r._total ? t("core.label.total") : label(r.key)), text: true },
      { header: t("reports.col.currency"), value: (r) => r.currency, text: true },
      { header: t("reports.col.bookings"), value: (r) => r.bookings },
      { header: t("reports.col.room_nights"), value: (r) => r.room_nights },
      { header: t("reports.col.guests"), value: (r) => (r._total ? "" : r.guests) },
      { header: t("reports.col.revenue"), value: (r) => r.revenue },
      { header: t("reports.col.adr"), value: (r) => r.adr },
      { header: t("reports.col.avg_los"), value: (r) => r.avg_los },
      { header: t("reports.col.avg_lead"), value: (r) => r.avg_lead_days },
      ...(costVisible
        ? [
            { header: t("reports.col.cost"), value: (r: ProdRow) => r.cost },
            { header: t("reports.col.margin"), value: (r: ProdRow) => r.margin },
            { header: t("reports.col.margin_pct"), value: (r: ProdRow) => r.margin_pct },
          ]
        : []),
    ]
    const totalRows = totalsInView.map(([c, tot]) => ({
      _total: true,
      key: "TOTAL",
      currency: c,
      bookings: tot.bookings,
      room_nights: tot.room_nights,
      revenue: tot.revenue,
      guests: 0,
      adr: tot.adr,
      avg_los: null,
      avg_lead_days: null,
    }))
    const csv = toCsv(cols, [...rows, ...totalRows])
    const name = ["production", slugify(property?.property_name ?? d.property), basis, groupBy, d.from, d.to, ccy && ccy.toLowerCase()]
      .filter(Boolean)
      .join("_")
    downloadCsv(`${name}.csv`, csv)
  }

  return (
    <ReportsFrame
      subtitle={d ? t("reports.production.subtitle", { hotel: property?.property_name ?? "", from: date(d.from), to: date(d.to) }) : property?.property_name}
      actions={
        <Button variant="secondary" icon={<Download className="size-4" aria-hidden />} onClick={exportCsv} disabled={!rows || rows.length === 0}>
          {t("reports.export_csv")}
        </Button>
      }
    >
      <Card className="mb-4">
        <CardBody className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <RangeFilter
              presets={[...PRESETS]}
              preset={preset}
              from={from}
              to={to}
              error={problem ? t(problem, { max: 800 }) : null}
              labels={{ from: basis === "stay" ? t("reports.filter.stay_from") : t("reports.filter.booked_from"), to: t("core.label.to") }}
              onChange={(n) => update({ period: n.preset === "this_month" ? null : n.preset, from: n.preset === "custom" ? n.from : null, to: n.preset === "custom" ? n.to : null })}
            />
            <Field label={t("reports.filter.group_by")} className="w-full sm:w-48">
              <Select
                value={groupBy}
                onChange={(e) => update({ group: e.target.value === "channel" ? null : e.target.value })}
                options={DIMENSIONS.map((dm) => ({ value: dm, label: t(`reports.dim.${dm}`) }))}
              />
            </Field>
          </div>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-zinc-800" aria-hidden>
                {t("reports.filter.basis")}
              </span>
              <Segmented<Basis>
                label={t("reports.filter.basis")}
                value={basis}
                onChange={(v) => update({ basis: v === "stay" ? null : v })}
                options={[
                  { value: "stay", label: t("reports.basis.stay") },
                  { value: "booking", label: t("reports.basis.booking") },
                ]}
              />
            </div>
            <Checkbox
              label={t("reports.filter.include_cancelled")}
              checked={includeCancelled}
              onChange={(e) => update({ cancelled: e.target.checked ? "1" : null })}
            />
            {currencies.length > 1 && (
              <Field label={t("reports.filter.currency")} inline>
                <Select
                  value={ccy}
                  onChange={(e) => setCcyFilter(e.target.value)}
                  options={[{ value: "", label: t("reports.all_currencies") }, ...currencies.map((c) => ({ value: c, label: c }))]}
                  className="w-auto"
                />
              </Field>
            )}
          </div>
          <div className="flex items-start gap-2 rounded-lg bg-zinc-50 px-3 py-2 text-xs text-zinc-600">
            <Info className="mt-0.5 size-3.5 shrink-0 text-zinc-500" aria-hidden />
            <p>{basis === "stay" ? t("reports.basis.stay_help") : t("reports.basis.booking_help")}</p>
          </div>
        </CardBody>
      </Card>

      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : (
        <div className="space-y-4">
          <section aria-label={t("reports.totals")} className="space-y-2">
            {!d ? (
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Card key={i} className="p-4">
                    <Skeleton className="h-3 w-20" />
                    <Skeleton className="mt-3 h-6 w-28" />
                  </Card>
                ))}
              </div>
            ) : totalsInView.length === 0 ? null : (
              <>
                {currencies.length > 1 && <Notice tone="info">{t("reports.per_currency_notice")}</Notice>}
                {totalsInView.map(([c, tot]) => (
                  <div key={c} className={cn("grid grid-cols-2 gap-3 lg:grid-cols-4", q.loading && "opacity-60")}>
                    <TotalTile label={currencies.length > 1 ? `${t("reports.col.revenue")} · ${c}` : t("reports.col.revenue")} value={money(tot.revenue, c)} />
                    <TotalTile label={t("reports.col.room_nights")} value={num(tot.room_nights)} />
                    <TotalTile label={t("reports.col.bookings")} value={num(tot.bookings)} />
                    <TotalTile label={t("reports.col.adr")} value={money(tot.adr, c)} />
                  </div>
                ))}
              </>
            )}
          </section>

          {d && rows && rows.length > 0 && chartData.length > 1 && (
            <Card>
              <CardHeader
                title={metric === "revenue" ? t("reports.col.revenue") : t("reports.col.room_nights")}
                description={
                  isTime
                    ? t("reports.grouped_by", { dim: dimLabel })
                    : `${t("reports.grouped_by", { dim: dimLabel })} · ${t("reports.chart.top", { count: chartData.length })}`
                }
                actions={
                  singleCcy ? (
                    <Segmented<Metric>
                      size="sm"
                      label={t("reports.chart.metric")}
                      value={metric}
                      onChange={setMetric}
                      options={[
                        { value: "room_nights", label: t("reports.col.room_nights") },
                        { value: "revenue", label: t("reports.col.revenue") },
                      ]}
                    />
                  ) : undefined
                }
              />
              <CardBody>
                <BarChart
                  data={chartData}
                  orientation={isTime ? "vertical" : "horizontal"}
                  integer={metric === "room_nights"}
                  stale={q.loading}
                  summary={t("reports.chart.summary", {
                    metric: metric === "revenue" ? t("reports.col.revenue") : t("reports.col.room_nights"),
                    dim: dimLabel,
                    count: chartData.length,
                  })}
                />
                <p className="mt-2 text-xs text-zinc-500">{t("reports.chart.table_hint")}</p>
              </CardBody>
            </Card>
          )}

          <Card>
            <CardHeader
              title={t("reports.nav.production")}
              description={costVisible ? `${t("reports.grouped_by", { dim: dimLabel })} · ${t("reports.cost_visible")}` : t("reports.grouped_by", { dim: dimLabel })}
            />
            <DataTable<ProdRow>
              key={`${groupBy}-${basis}`}
              caption={t("reports.production.table_caption", { dim: dimLabel })}
              rows={rows}
              loading={q.loading}
              rowKey={(r) => `${r.key}|${r.currency}`}
              dense
              initialSort={isTime ? { key: "key", dir: "asc" } : undefined}
              columns={columns}
              footer={footer}
              empty={<EmptyState title={t("reports.empty")} description={t("reports.empty_hint")} />}
            />
          </Card>
        </div>
      )}
    </ReportsFrame>
  )
}

function TotalTile({ label, value }: { label: string; value: string }) {
  return (
    <Card className="px-4 py-3">
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p className="mt-0.5 text-xl font-semibold tracking-tight text-zinc-950">{value}</p>
    </Card>
  )
}
