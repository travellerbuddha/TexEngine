import { useMemo, useState } from "react"
import { Download } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { useSession } from "../../lib/session"
import { date, money, num, pct } from "../../lib/format"
import { useTexT } from "../../i18n"
import { Button, Card, CardBody, CardHeader, DataTable, EmptyState, ErrorState, Money, Notice, Segmented, Skeleton, type Column } from "../../ui"
import { cn } from "../../../lib/utils"
import { BarChart, type ChartDatum } from "./components/BarChart"
import { ReportFilters } from "./components/ReportFilters"
import { argsKey, filtersProblem, reportArgs, useReportFilters } from "./filters"
import { TIME_DIMENSIONS, decimalSort, downloadCsv, groupLabel, slugify, toCsv, type CsvColumn, type Dimension } from "./lib"
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
  accommodation?: string
  cost?: string
  margin?: string
  margin_pct?: string | null
}

interface ProdTotal {
  bookings: number
  room_nights: number
  guests: number
  revenue: string
  adr: string | null
  avg_los: string | null
  avg_lead_days: string | null
  accommodation?: string
  cost?: string
  margin?: string
  margin_pct?: string | null
}

interface ProdData {
  scope: { level: string; name: string | null; hotels: string[] }
  stay: { from: string; to: string } | null
  sale: { from: string; to: string } | null
  basis: "stay" | "booking"
  group_by: Dimension
  cost_visible: boolean
  rows: ProdRow[]
  totals: Record<string, ProdTotal>
  truncated: number
  labels: Record<string, string>
}

type Metric = "room_nights" | "revenue"

const HIDE = { sm: "hidden sm:table-cell", md: "hidden md:table-cell", lg: "hidden lg:table-cell" }

export default function ProductionReport() {
  const { t, locale } = useTexT()
  const { boot } = useSession()
  const { filters, update } = useReportFilters("production")
  const problem = filtersProblem(filters)
  const args = reportArgs("production", filters)
  const q = useTexQuery<ProdData>("reports", "report", args, [argsKey(args)], !problem)
  const d = problem ? undefined : q.data
  const groupBy = (d?.group_by ?? filters.group ?? "channel") as Dimension
  const currencies = useMemo(() => (d ? Object.keys(d.totals).sort() : []), [d])
  const rows = d?.rows
  const singleCcy = currencies.length === 1 ? currencies[0] : ""
  const [metricPref, setMetric] = useState<Metric>("room_nights")
  const metric: Metric = singleCcy ? metricPref : "room_nights"
  const costVisible = Boolean(d?.cost_visible)
  const dimLabel = t(`reports.dim.${groupBy}`)
  const label = (key: string) => groupLabel(groupBy, key, boot, t, locale, d?.labels)
  const isTime = TIME_DIMENSIONS.includes(groupBy)

  const chartData: ChartDatum[] = useMemo(() => {
    if (!rows) return []
    const base = isTime ? [...rows].sort((a, b) => a.key.localeCompare(b.key)) : rows
    // revenue bars only when one currency is in view (never compare across currencies)
    const list = base.map((r) => ({
      key: `${r.key}|${r.currency}`,
      label: currencies.length > 1 ? `${label(r.key)} · ${r.currency}` : label(r.key),
      value: metric === "revenue" ? (decimalSort(r.revenue) ?? 0) : r.room_nights,
      display: metric === "revenue" ? money(r.revenue, r.currency) : num(r.room_nights),
    }))
    if (isTime) return list.slice(-62)
    return [...list].sort((a, b) => b.value - a.value).slice(0, 12)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, metric, isTime, locale, currencies.length, groupBy, boot, d?.labels])

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
          {
            key: "accommodation",
            header: t("reports.col.accommodation"),
            align: "right",
            hideBelow: "lg",
            sortValue: (r) => decimalSort(r.accommodation),
            cell: (r) => <Money amount={r.accommodation} currency={r.currency} />,
          },
          { key: "cost", header: t("reports.col.cost"), align: "right", hideBelow: "md", sortValue: (r) => decimalSort(r.cost), cell: (r) => <Money amount={r.cost} currency={r.currency} muted /> },
          { key: "margin", header: t("reports.col.margin"), align: "right", hideBelow: "md", sortValue: (r) => decimalSort(r.margin), cell: (r) => <Money amount={r.margin} currency={r.currency} signed /> },
          { key: "margin_pct", header: t("reports.col.margin_pct"), align: "right", hideBelow: "md", sortValue: (r) => decimalSort(r.margin_pct), cell: (r) => pct(r.margin_pct) },
        ] satisfies Column<ProdRow>[])
      : []),
  ]

  const totalsInView = d ? currencies.map((c) => [c, d.totals[c]] as const) : []

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
              ) : col.key === "guests" ? (
                num(tot.guests)
              ) : col.key === "revenue" ? (
                <Money amount={tot.revenue} currency={c} />
              ) : col.key === "adr" ? (
                <Money amount={tot.adr} currency={c} />
              ) : col.key === "avg_los" ? (
                num(tot.avg_los)
              ) : col.key === "avg_lead_days" ? (
                num(tot.avg_lead_days)
              ) : col.key === "accommodation" ? (
                <Money amount={tot.accommodation} currency={c} />
              ) : col.key === "cost" ? (
                <Money amount={tot.cost} currency={c} muted />
              ) : col.key === "margin" ? (
                <Money amount={tot.margin} currency={c} signed />
              ) : col.key === "margin_pct" ? (
                pct(tot.margin_pct)
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
      { header: t("reports.col.guests"), value: (r) => r.guests },
      { header: t("reports.col.revenue"), value: (r) => r.revenue },
      { header: t("reports.col.adr"), value: (r) => r.adr },
      { header: t("reports.col.avg_los"), value: (r) => r.avg_los },
      { header: t("reports.col.avg_lead"), value: (r) => r.avg_lead_days },
      ...(costVisible
        ? [
            { header: t("reports.col.accommodation"), value: (r: ProdRow) => r.accommodation },
            { header: t("reports.col.cost"), value: (r: ProdRow) => r.cost },
            { header: t("reports.col.margin"), value: (r: ProdRow) => r.margin },
            { header: t("reports.col.margin_pct"), value: (r: ProdRow) => r.margin_pct },
          ]
        : []),
    ]
    const totalRows = totalsInView.map(([c, tot]) => ({ ...tot, _total: true, key: "TOTAL", currency: c }))
    const csv = toCsv(cols, [...rows, ...totalRows])
    const name = ["production", slugify(d.scope.name ?? d.scope.level), d.basis, groupBy, d.stay?.from, d.stay?.to, d.sale?.from, d.sale?.to]
      .filter(Boolean)
      .join("_")
    downloadCsv(`${name}.csv`, csv)
  }

  const period = d?.stay ?? d?.sale
  return (
    <ReportsFrame
      subtitle={period ? t("reports.view.subtitle", { count: d?.scope.hotels.length ?? 1, from: date(period.from), to: date(period.to) }) : undefined}
      actions={
        <Button variant="secondary" icon={<Download className="size-4" aria-hidden />} onClick={exportCsv} disabled={!rows || rows.length === 0}>
          {t("reports.export_csv")}
        </Button>
      }
    >
      <ReportFilters view="production" filters={filters} update={update} problem={problem} note={costVisible ? t("reports.margin.help") : undefined} />

      {q.error && !problem ? (
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

          {d && d.truncated > 0 && <Notice tone="info">{t("reports.truncated", { count: d.truncated })}</Notice>}

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
              key={`${groupBy}-${filters.basis}`}
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
    <Card className="min-w-0 px-4 py-3">
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tracking-tight break-words text-zinc-950 sm:text-xl">{value}</p>
    </Card>
  )
}
