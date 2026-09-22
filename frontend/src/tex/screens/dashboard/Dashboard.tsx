import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { ArrowRight } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { useProperty, useSession } from "../../lib/session"
import { addDays, date, isoDay, money, num, pct } from "../../lib/format"
import { useTexT } from "../../i18n"
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  DataTable,
  EmptyState,
  ErrorState,
  Money,
  PageHeader,
  Segmented,
  Skeleton,
  Stat,
} from "../../ui"

interface ProdRow {
  key: string
  currency: string
  bookings: number
  room_nights: number
  revenue: string
  adr: string | null
  margin?: string
  margin_pct?: string | null
}

interface DashboardData {
  from: string
  to: string
  currency: string
  stay: Record<string, { bookings: number; room_nights: number; revenue: string; adr: string | null }>
  by_channel: ProdRow[]
  pickup_by_day: ProdRow[]
  reservations_created: number
  cancellations: number
  cancellation_rate: string | null
  today: { arrivals: number; departures: number }
  guest_changes_pending: number
  open_balance: Record<string, string>
  funnel: { search: number; quote: number; guest_details: number; payment_started: number; booked: number; conversion_pct: string | null }
  abandoned_open: number
}

type Range = "this_month" | "next_30" | "next_90"

function rangeDates(r: Range): [string, string] {
  const today = new Date()
  if (r === "this_month") {
    const a = new Date(today.getFullYear(), today.getMonth(), 1)
    const b = new Date(today.getFullYear(), today.getMonth() + 1, 0)
    return [isoDay(a), isoDay(b)]
  }
  const start = isoDay(today)
  return [start, addDays(start, r === "next_30" ? 29 : 89)]
}

export default function Dashboard() {
  const { t } = useTexT()
  const property = useProperty()
  const { can } = useSession()
  const [range, setRange] = useState<Range>("this_month")
  const [from, to] = useMemo(() => rangeDates(range), [range])
  const canReports = can("report.view")
  const q = useTexQuery<DashboardData>("reports", "dashboard", { property, date_from: from, date_to: to }, [property, from, to], canReports)
  const d = q.data

  // one bar per calendar day of the period (days without sales show as empty)
  const pickup = useMemo(() => {
    if (!d) return []
    const byDay = new Map<string, number>()
    for (const r of d.pickup_by_day) byDay.set(r.key, (byDay.get(r.key) ?? 0) + r.room_nights)
    const days: { day: string; n: number }[] = []
    for (let day = d.from; day <= d.to && days.length < 120; day = addDays(day, 1)) days.push({ day, n: byDay.get(day) ?? 0 })
    return days
  }, [d])
  const pickupMax = useMemo(() => Math.max(1, ...pickup.map((p) => p.n)), [pickup])

  return (
    <>
      <PageHeader
        title={t("core.nav.dashboard")}
        subtitle={d ? t("dash.period", { from: date(d.from), to: date(d.to) }) : undefined}
        actions={
          <Segmented<Range>
            label={t("dash.range")}
            value={range}
            onChange={setRange}
            options={[
              { value: "this_month", label: t("dash.range.this_month") },
              { value: "next_30", label: t("dash.range.next_30") },
              { value: "next_90", label: t("dash.range.next_90") },
            ]}
          />
        }
      />
      {!canReports ? (
        <Card>
          <EmptyState
            title={t("dash.no_reports")}
            action={
              <Link to="/tex/reservations">
                <Button variant="secondary">{t("core.nav.reservations")}</Button>
              </Link>
            }
          />
        </Card>
      ) : q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : (
        <div className="space-y-5">
          <section aria-label={t("dash.kpis")} className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {!d ? (
              Array.from({ length: 4 }).map((_, i) => (
                <Card key={i} className="p-4">
                  <Skeleton className="h-3 w-24" />
                  <Skeleton className="mt-3 h-7 w-32" />
                </Card>
              ))
            ) : (
              <>
                <Stat
                  label={t("dash.revenue")}
                  value={
                    Object.keys(d.stay).length ? (
                      <span className="flex flex-col">
                        {Object.entries(d.stay).map(([ccy, v]) => (
                          <span key={ccy}>{money(v.revenue, ccy)}</span>
                        ))}
                      </span>
                    ) : (
                      money("0", d.currency)
                    )
                  }
                  hint={t("dash.on_the_books")}
                />
                <Stat
                  label={t("dash.room_nights")}
                  value={num(Object.values(d.stay).reduce((s, v) => s + v.room_nights, 0))}
                  hint={Object.entries(d.stay)
                    .map(([ccy, v]) => `${t("dash.adr")} ${money(v.adr, ccy)}`)
                    .join(" · ")}
                />
                <Stat
                  label={t("dash.bookings_created")}
                  value={num(d.reservations_created)}
                  hint={t("dash.cancellations", { count: d.cancellations, rate: pct(d.cancellation_rate) })}
                />
                <Stat
                  label={t("dash.conversion")}
                  value={pct(d.funnel.conversion_pct)}
                  hint={t("dash.searches", { count: d.funnel.search })}
                />
              </>
            )}
          </section>

          <div className="grid gap-5 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader title={t("dash.by_channel")} description={t("dash.by_channel_hint")} />
              <DataTable<ProdRow>
                caption={t("dash.by_channel")}
                rows={d?.by_channel}
                loading={q.loading}
                rowKey={(r) => `${r.key}-${r.currency}`}
                initialSort={{ key: "room_nights", dir: "desc" }}
                empty={<EmptyState title={t("dash.no_stays")} />}
                columns={[
                  { key: "key", header: t("dash.col.channel"), sortValue: (r) => r.key },
                  { key: "bookings", header: t("dash.col.bookings"), align: "right", sortValue: (r) => r.bookings },
                  { key: "room_nights", header: t("dash.col.room_nights"), align: "right", sortValue: (r) => r.room_nights },
                  { key: "revenue", header: t("dash.col.revenue"), align: "right", cell: (r) => <Money amount={r.revenue} currency={r.currency} /> },
                  { key: "adr", header: t("dash.adr"), align: "right", hideBelow: "sm", cell: (r) => <Money amount={r.adr} currency={r.currency} /> },
                ]}
              />
            </Card>

            <div className="space-y-5">
              <Card>
                <CardHeader title={t("dash.today")} />
                <CardBody className="grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-xs text-zinc-500">{t("dash.arrivals")}</p>
                    <p className="text-xl font-semibold tabular-nums">{d ? num(d.today.arrivals) : "—"}</p>
                  </div>
                  <div>
                    <p className="text-xs text-zinc-500">{t("dash.departures")}</p>
                    <p className="text-xl font-semibold tabular-nums">{d ? num(d.today.departures) : "—"}</p>
                  </div>
                </CardBody>
              </Card>
              <Card>
                <CardHeader title={t("dash.attention")} />
                <ul className="divide-y divide-zinc-100 text-sm">
                  <li>
                    <Link to="/tex/reservations?guest_changes=1" className="flex items-center justify-between px-4 py-2.5 hover:bg-zinc-50">
                      <span>{t("dash.guest_changes")}</span>
                      <Badge tone={d?.guest_changes_pending ? "warning" : "neutral"}>{d ? d.guest_changes_pending : "—"}</Badge>
                    </Link>
                  </li>
                  <li>
                    <Link to="/tex/crm/abandoned" className="flex items-center justify-between px-4 py-2.5 hover:bg-zinc-50">
                      <span>{t("dash.abandoned")}</span>
                      <Badge tone={d?.abandoned_open ? "warning" : "neutral"}>{d ? d.abandoned_open : "—"}</Badge>
                    </Link>
                  </li>
                  <li>
                    <Link to="/tex/payments" className="flex items-center justify-between gap-3 px-4 py-2.5 hover:bg-zinc-50">
                      <span>{t("dash.open_balance")}</span>
                      <span className="text-right">
                        {d && Object.keys(d.open_balance).length
                          ? Object.entries(d.open_balance).map(([c, v]) => (
                              <span key={c} className="block">
                                <Money amount={v} currency={c} />
                              </span>
                            ))
                          : "—"}
                      </span>
                    </Link>
                  </li>
                </ul>
              </Card>
            </div>
          </div>

          <Card>
            <CardHeader
              title={t("dash.pickup")}
              description={t("dash.pickup_hint")}
              actions={
                <Link to="/tex/reports" className="inline-flex items-center gap-1 text-sm font-medium text-tex-700 hover:underline">
                  {t("core.nav.reports")} <ArrowRight className="size-4" aria-hidden />
                </Link>
              }
            />
            <CardBody>
              {d && d.pickup_by_day.length ? (
                <div>
                  <ol className="flex h-40 items-end gap-px border-b border-zinc-200" aria-label={t("dash.pickup")}>
                    {pickup.map((p) => (
                      <li key={p.day} className="flex h-full min-w-0 flex-1 flex-col justify-end" title={`${date(p.day)}: ${p.n}`}>
                        <span className="sr-only">
                          {date(p.day)}: {p.n}
                        </span>
                        <span
                          aria-hidden
                          className="mx-auto block w-full max-w-6 rounded-t-sm bg-tex-500/80"
                          style={{ height: p.n ? `${Math.max(4, (p.n / pickupMax) * 100)}%` : "0" }}
                        />
                      </li>
                    ))}
                  </ol>
                  <div className="mt-1 flex justify-between text-[11px] text-zinc-500" aria-hidden>
                    <span>{date(d.from, "short")}</span>
                    <span>{date(d.to, "short")}</span>
                  </div>
                </div>
              ) : (
                <EmptyState title={t("dash.no_pickup")} />
              )}
            </CardBody>
          </Card>
        </div>
      )}
    </>
  )
}
