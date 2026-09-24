import { useMemo } from "react"
import { Download } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { useSession } from "../../lib/session"
import { date, money, num, pct } from "../../lib/format"
import { useTexT } from "../../i18n"
import { Button, Card, CardHeader, DataTable, EmptyState, ErrorState, HIDE, Money, Notice, Skeleton, type Column } from "../../ui"
import { cn } from "../../../lib/utils"
import { ReportFilters } from "./components/ReportFilters"
import { argsKey, filtersProblem, reportArgs, useReportFilters } from "./filters"
import { decimalSort, downloadCsv, groupLabel, OTHER_KEY, slugify, TIME_DIMENSIONS, toCsv, type CsvColumn, type ReportView } from "./lib"
import { ReportsFrame } from "./ReportsFrame"

type Row = Record<string, unknown> & { key: string; currency?: string; name?: string | null; stage?: string | null }
type Totals = Record<string, Record<string, unknown>>

interface ViewData {
  view: ReportView
  scope: { level: string; name: string | null; hotels: string[] }
  stay: { from: string; to: string } | null
  sale: { from: string; to: string } | null
  group_by: string | null
  cost_visible: boolean
  rows: Row[]
  /** Per currency; conversion (no money) has one flat total. */
  totals: Totals | Record<string, unknown>
  truncated: number
  labels: Record<string, string>
  methods?: MethodRow[]
  method_totals?: Record<string, { charged: string; refunded: string; net: string }>
}

interface MethodRow {
  method: string
  provider: string | null
  currency: string
  charges: number
  refunds: number
  charged: string
  refunded: string
  net: string
}

type Kind = "money" | "count" | "pct" | "qty" | "days"

interface Spec {
  key: string
  label: string
  kind: Kind
  hide?: "sm" | "md" | "lg"
  signed?: boolean
  muted?: boolean
  /** false: not summed (the total row leaves it empty). */
  total?: boolean
}

/** Views this page draws (production has its own page with a chart). */
export type TableView = Exclude<ReportView, "production">

const TILES: Record<TableView, string[]> = {
  margin: ["revenue", "accommodation", "cost", "margin"],
  promotion: ["applications", "discount"],
  extras: ["amount"],
  cancellation: ["cancelled", "cancelled_value", "fees", "net_lost"],
  payment: ["value", "paid", "balance"],
  conversion: ["searched", "booked", "conversion_pct", "confirmed"],
}

function useSpecs(view: TableView, costVisible: boolean): Spec[] {
  const { t } = useTexT()
  const c = (k: string) => t(`reports.col.${k}`)
  switch (view) {
    case "margin":
      return [
        { key: "room_nights", label: c("room_nights"), kind: "count", hide: "sm" },
        { key: "revenue", label: c("revenue"), kind: "money" },
        { key: "accommodation", label: c("accommodation"), kind: "money" },
        { key: "extras", label: c("extras"), kind: "money", hide: "md" },
        { key: "taxes", label: c("taxes"), kind: "money", hide: "md" },
        { key: "not_from_contract", label: c("not_from_contract"), kind: "money", hide: "lg" },
        { key: "cancellation_fees", label: c("cancellation_fees"), kind: "money", hide: "lg" },
        { key: "cost", label: c("cost"), kind: "money", muted: true },
        { key: "margin", label: c("margin"), kind: "money", signed: true },
        { key: "margin_pct", label: c("margin_pct"), kind: "pct" },
      ]
    case "promotion":
      return [
        { key: "applications", label: c("applications"), kind: "count" },
        { key: "room_nights", label: c("room_nights"), kind: "count", hide: "sm", total: false },
        { key: "revenue", label: c("stay_revenue"), kind: "money", hide: "sm", total: false },
        { key: "discount", label: c("discount"), kind: "money" },
        // a cost-stage offer lowers the contract cost: only with cost access (the server sends it)
        ...(costVisible ? [{ key: "cost_reduction", label: c("cost_reduction"), kind: "money" as const, hide: "sm" as const }] : []),
      ]
    case "extras":
      return [
        { key: "stays", label: c("stays"), kind: "count", total: false },
        { key: "quantity", label: c("quantity"), kind: "qty", total: false },
        { key: "amount", label: c("amount"), kind: "money" },
      ]
    case "cancellation":
      return [
        { key: "stays", label: c("stays"), kind: "count", hide: "sm" },
        { key: "cancelled", label: c("cancelled"), kind: "count" },
        { key: "no_shows", label: c("no_shows"), kind: "count", hide: "md" },
        { key: "cancelled_pct", label: c("cancelled_pct"), kind: "pct" },
        { key: "cancelled_nights", label: c("cancelled_nights"), kind: "count", hide: "md" },
        { key: "cancelled_value", label: c("cancelled_value"), kind: "money" },
        { key: "fees", label: c("fees"), kind: "money", hide: "sm" },
        { key: "net_lost", label: c("net_lost"), kind: "money", hide: "md" },
        { key: "avg_days_before_arrival", label: c("avg_days_before_arrival"), kind: "days", hide: "lg" },
      ]
    case "payment":
      return [
        { key: "bookings", label: c("bookings"), kind: "count", hide: "sm" },
        { key: "value", label: c("value"), kind: "money" },
        { key: "paid", label: c("paid"), kind: "money" },
        { key: "balance", label: c("balance"), kind: "money" },
        { key: "charged", label: c("charged"), kind: "money", hide: "md" },
        { key: "refunded", label: c("refunded"), kind: "money", hide: "md" },
        { key: "pending", label: c("pending"), kind: "money", hide: "lg" },
      ]
    case "conversion":
      return [
        { key: "sessions", label: c("sessions"), kind: "count", hide: "sm" },
        { key: "searched", label: c("searched"), kind: "count" },
        { key: "quoted", label: c("quoted"), kind: "count", hide: "sm" },
        { key: "details", label: c("details"), kind: "count", hide: "md" },
        { key: "booked", label: c("booked"), kind: "count" },
        { key: "confirmed", label: c("confirmed"), kind: "count", hide: "sm" },
        { key: "conversion_pct", label: c("conversion_pct"), kind: "pct" },
        { key: "confirmed_pct", label: c("confirmed_pct"), kind: "pct", hide: "md" },
      ]
  }
}

function show(kind: Kind, v: unknown, ccy: string | undefined, spec?: Spec) {
  if (v === null || v === undefined || v === "") return "—"
  if (kind === "money") return <Money amount={String(v)} currency={ccy} signed={spec?.signed} muted={spec?.muted} />
  if (kind === "pct") return pct(String(v))
  return num(v as string | number)
}

function text(kind: Kind, v: unknown, ccy: string | undefined) {
  if (v === null || v === undefined || v === "") return "—"
  if (kind === "money") return money(String(v), ccy)
  if (kind === "pct") return pct(String(v))
  return num(v as string | number)
}

function sortOf(kind: Kind, v: unknown) {
  if (v === null || v === undefined || v === "") return null
  return kind === "count" ? Number(v) : decimalSort(String(v))
}

/**
 * One report view as a table: rows per grouping (or per promotion / extra), totals per
 * currency (never added across currencies), tiles, CSV. Every figure is the server's decimal
 * string; nothing here adds money.
 */
export default function ViewReport({ view }: { view: TableView }) {
  const { t, locale } = useTexT()
  const { boot } = useSession()
  const { filters, update } = useReportFilters(view)
  const problem = filtersProblem(filters)
  const args = reportArgs(view, filters)
  const q = useTexQuery<ViewData>("reports", "report", args, [argsKey(args)], !problem)
  const d = problem ? undefined : q.data
  const specs = useSpecs(view, Boolean(q.data?.cost_visible))
  const hasMoney = view !== "conversion"
  const totals = (d?.totals ?? {}) as Totals
  const currencies = useMemo(() => (d && hasMoney ? Object.keys(totals).sort() : []), [d, hasMoney, totals])
  const dim = d?.group_by ?? filters.group
  const keyHeader = view === "promotion" ? t("reports.col.promotion") : view === "extras" ? t("reports.col.extra") : t(`reports.dim.${dim}`)
  const label = (r: Row) =>
    r.key === OTHER_KEY
      ? t("reports.other")
      : view === "promotion" || view === "extras"
        ? `${r.name ?? r.key}${r.stage === "COST" ? ` · ${t("reports.promotion.cost_stage")}` : ""}`
        : groupLabel((dim ?? "channel") as never, r.key, boot, t, locale, d?.labels, view)
  const isTime = !!dim && TIME_DIMENSIONS.includes(dim as never)

  const columns: Column<Row>[] = [
    {
      key: "key",
      header: keyHeader,
      sortValue: (r) => (isTime ? r.key : label(r)),
      cell: (r) => (
        <span className="font-medium text-zinc-900" title={r.key}>
          {label(r)}
        </span>
      ),
    },
    ...(currencies.length > 1 ? ([{ key: "currency", header: t("reports.col.currency"), hideBelow: "md", sortValue: (r) => r.currency }] satisfies Column<Row>[]) : []),
    ...specs.map<Column<Row>>((s) => ({
      key: s.key,
      header: s.label,
      align: "right",
      hideBelow: s.hide,
      sortValue: (r) => sortOf(s.kind, r[s.key]),
      cell: (r) => show(s.kind, r[s.key], r.currency, s),
    })),
  ]

  // one total row per currency (conversion: one row), the rows' sums as the server made them
  const totalRows: [string, Record<string, unknown>][] = d ? (hasMoney ? currencies.map((c) => [c, totals[c]]) : [["", d.totals as Record<string, unknown>]]) : []
  const footer = totalRows.length ? (
    <>
      {totalRows.map(([c, tot]) => (
        <tr key={c || "all"} className="bg-zinc-50 font-semibold">
          {columns.map((col) => {
            const cls = cn(
              "border-t border-zinc-200 px-3 py-2 text-zinc-900",
              col.align === "right" ? "text-right tabular-nums" : "text-left",
              col.hideBelow && HIDE[col.hideBelow],
            )
            if (col.key === "key")
              return (
                <th key={col.key} scope="row" className={cls}>
                  {totalRows.length > 1 ? t("reports.total_ccy", { currency: c }) : t("core.label.total")}
                </th>
              )
            const s = specs.find((x) => x.key === col.key)
            return (
              <td key={col.key} className={cls}>
                {col.key === "currency" ? c : s && s.total !== false ? show(s.kind, tot[s.key], c || undefined) : null}
              </td>
            )
          })}
        </tr>
      ))}
    </>
  ) : undefined

  const exportCsv = () => {
    if (!d) return
    const cols: CsvColumn<Row & { _total?: boolean }>[] = [
      { header: `${keyHeader} (${t("reports.csv.key")})`, value: (r) => (r._total ? "TOTAL" : r.key), text: true },
      { header: keyHeader, value: (r) => (r._total ? t("core.label.total") : label(r)), text: true },
      ...(hasMoney ? [{ header: t("reports.col.currency"), value: (r: Row) => r.currency, text: true }] : []),
      ...specs.map((s) => ({ header: s.label, value: (r: Row & { _total?: boolean }) => (r._total && s.total === false ? "" : r[s.key]) })),
    ]
    const csv = toCsv(cols, [...d.rows, ...totalRows.map(([c, tot]) => ({ ...tot, key: "TOTAL", currency: c || undefined, _total: true }))])
    const name = ["report", view, slugify(d.scope.name ?? d.scope.level), dim, d.stay?.from, d.stay?.to, d.sale?.from, d.sale?.to].filter(Boolean).join("_")
    downloadCsv(`${name}.csv`, csv)
  }

  const period = d?.stay ?? d?.sale
  const subtitle = d && period ? t("reports.view.subtitle", { count: d.scope.hotels.length, from: date(period.from), to: date(period.to) }) : undefined

  return (
    <ReportsFrame
      subtitle={subtitle}
      actions={
        <Button variant="secondary" icon={<Download className="size-4" aria-hidden />} onClick={exportCsv} disabled={!d || d.rows.length === 0}>
          {t("reports.export_csv")}
        </Button>
      }
    >
      <ReportFilters view={view} filters={filters} update={update} problem={problem} note={t(`reports.${view}.help`)} />

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
            ) : (
              <>
                {currencies.length > 1 && <Notice tone="info">{t("reports.per_currency_notice")}</Notice>}
                {totalRows.map(([c, tot]) => (
                  <div key={c || "all"} className={cn("grid grid-cols-2 gap-3 lg:grid-cols-4", q.loading && "opacity-60")} data-currency={c || undefined}>
                    {TILES[view].map((k) => {
                      const s = specs.find((x) => x.key === k)!
                      return <Tile key={k} label={currencies.length > 1 ? `${s.label} · ${c}` : s.label} value={text(s.kind, tot[k], c || undefined)} />
                    })}
                  </div>
                ))}
              </>
            )}
          </section>

          {d && d.truncated > 0 && <Notice tone="info">{t("reports.truncated", { count: d.truncated })}</Notice>}

          <Card>
            <CardHeader title={t(`reports.nav.${view}`)} description={dim ? t("reports.grouped_by", { dim: t(`reports.dim.${dim}`) }) : undefined} />
            <DataTable<Row>
              key={`${view}-${dim}`}
              caption={t("reports.view.table_caption", { view: t(`reports.nav.${view}`) })}
              rows={d?.rows}
              loading={q.loading}
              rowKey={(r) => `${r.key}|${r.currency ?? ""}`}
              dense
              initialSort={isTime ? { key: "key", dir: "asc" } : undefined}
              columns={columns}
              footer={footer}
              empty={<EmptyState title={t(`reports.${view}.empty`)} description={t("reports.empty_hint")} />}
            />
          </Card>

          {view === "payment" && d?.methods && <Methods rows={d.methods} totals={d.method_totals ?? {}} />}
        </div>
      )}
    </ReportsFrame>
  )
}

function Methods({ rows, totals }: { rows: MethodRow[]; totals: Record<string, { charged: string; refunded: string; net: string }> }) {
  const { t } = useTexT()
  const ccys = Object.keys(totals).sort()
  const columns: Column<MethodRow>[] = [
    {
      key: "method",
      header: t("reports.col.method"),
      sortValue: (r) => r.method,
      cell: (r) => {
        const k = `payments.method.${(r.method ?? "").toLowerCase().replace(/\s+/g, "_")}`
        const l = t(k)
        return <span className="font-medium text-zinc-900">{l === k ? r.method : l}</span>
      },
    },
    { key: "provider", header: t("reports.col.provider"), hideBelow: "sm", sortValue: (r) => r.provider ?? "", cell: (r) => r.provider ?? "—" },
    ...(ccys.length > 1 ? ([{ key: "currency", header: t("reports.col.currency"), sortValue: (r) => r.currency }] satisfies Column<MethodRow>[]) : []),
    { key: "charged", header: t("reports.col.charged"), align: "right", sortValue: (r) => decimalSort(r.charged), cell: (r) => <Money amount={r.charged} currency={r.currency} /> },
    { key: "refunded", header: t("reports.col.refunded"), align: "right", hideBelow: "sm", sortValue: (r) => decimalSort(r.refunded), cell: (r) => <Money amount={r.refunded} currency={r.currency} /> },
    { key: "net", header: t("reports.col.net"), align: "right", sortValue: (r) => decimalSort(r.net), cell: (r) => <Money amount={r.net} currency={r.currency} className="font-medium" /> },
  ]
  return (
    <Card>
      <CardHeader title={t("reports.payment.methods")} description={t("reports.payment.methods_help")} />
      <DataTable<MethodRow>
        caption={t("reports.payment.methods")}
        rows={rows}
        rowKey={(r) => `${r.method}|${r.provider}|${r.currency}`}
        dense
        columns={columns}
        footer={
          ccys.length ? (
            <>
              {ccys.map((c) => (
                <tr key={c} className="bg-zinc-50 font-semibold">
                  {columns.map((col) => {
                    const cls = cn("border-t border-zinc-200 px-3 py-2", col.align === "right" ? "text-right tabular-nums" : "text-left", col.hideBelow && HIDE[col.hideBelow])
                    const v = col.key === "charged" || col.key === "refunded" || col.key === "net" ? <Money amount={totals[c][col.key]} currency={c} /> : null
                    return col.key === "method" ? (
                      <th key={col.key} scope="row" className={cls}>
                        {ccys.length > 1 ? t("reports.total_ccy", { currency: c }) : t("core.label.total")}
                      </th>
                    ) : (
                      <td key={col.key} className={cls}>
                        {col.key === "currency" ? c : v}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </>
          ) : undefined
        }
        empty={<EmptyState title={t("reports.payment.no_payments")} />}
      />
    </Card>
  )
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <Card className="min-w-0 px-4 py-3">
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tracking-tight break-words text-zinc-950 sm:text-xl">{value}</p>
    </Card>
  )
}
