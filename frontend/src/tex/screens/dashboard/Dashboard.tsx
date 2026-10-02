import { useMemo, useState, type ReactNode } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { ArrowRight } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { useProperty, useSession } from "../../lib/session"
import { addDays, date, money, num, pct } from "../../lib/format"
import { useSiteToday } from "../../lib/siteDay"
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
import { presetRange } from "../reports/lib"
import PortfolioDashboard from "./PortfolioDashboard"

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
  /** the server's day these figures are for (the list they open asks for the same day) */
  today: { date?: string; arrivals: number; departures: number }
  guest_changes_pending: number
  open_balance: Record<string, string>
  funnel: { search: number; quote: number; guest_details: number; payment_started: number; booked: number; conversion_pct: string | null }
  abandoned_open: number
}

type Range = "this_month" | "next_30" | "next_90"

type View = "hotel" | "portfolio"
const VIEW_KEY = "tex-dashboard-view"

function storedView(): View | null {
  try {
    const v = localStorage.getItem(VIEW_KEY)
    return v === "portfolio" || v === "hotel" ? v : null
  } catch {
    return null
  }
}

/**
 * Dashboard: the selected hotel, or — for users who report on two or more hotels —
 * the portfolio of every hotel they may see (G-25, ADR-038). `?view=` wins over the
 * remembered choice, so links into one hotel always land on its own dashboard.
 */
export default function Dashboard() {
  const { t } = useTexT()
  const { boot, can } = useSession()
  const [params, setParams] = useSearchParams()
  const portfolioOk = useMemo(() => boot.properties.filter((p) => can("report.view", p.name)).length >= 2, [boot, can])
  const asked = params.get("view")
  const view: View =
    portfolioOk && (asked === "portfolio" || (asked !== "hotel" && storedView() === "portfolio")) ? "portfolio" : "hotel"
  const setView = (v: View) => {
    try {
      localStorage.setItem(VIEW_KEY, v)
    } catch {
      /* storage blocked: the URL still carries the view */
    }
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set("view", v)
        return next
      },
      { replace: true },
    )
  }
  const viewSwitch = portfolioOk ? (
    <Segmented<View>
      label={t("dash.view")}
      value={view}
      onChange={setView}
      options={[
        { value: "hotel", label: t("dash.view.hotel") },
        { value: "portfolio", label: t("dash.view.portfolio") },
      ]}
    />
  ) : undefined
  return view === "portfolio" ? <PortfolioDashboard viewSwitch={viewSwitch} /> : <HotelDashboard viewSwitch={viewSwitch} />
}

/** The selected hotel's dashboard (R-45). */
function HotelDashboard({ viewSwitch }: { viewSwitch?: ReactNode }) {
  const { t } = useTexT()
  const property = useProperty()
  const { can, property: hotel } = useSession()
  const [range, setRange] = useState<Range>("this_month")
  // the hotel's month / next days start on the site's today (G-91)
  const today = useSiteToday()
  const [from, to] = useMemo(() => presetRange(range, today), [range, today])
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
        subtitle={
          viewSwitch
            ? [hotel?.property_name, d ? t("dash.period", { from: date(d.from), to: date(d.to) }) : null].filter(Boolean).join(" · ")
            : d
              ? t("dash.period", { from: date(d.from), to: date(d.to) })
              : undefined
        }
        meta={viewSwitch}
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

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
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

            <div className="min-w-0 space-y-5">
              <Card>
                <CardHeader title={t("dash.today")} />
                {/* each figure opens the reservations behind it (UX revision 2026-10) */}
                <CardBody className="grid grid-cols-2 gap-3">
                  {(["arrivals", "departures"] as const).map((k) => {
                    const n = d?.today[k]
                    const body = (
                      <>
                        <span className="block text-xs text-zinc-500">{t(`dash.${k}`)}</span>
                        <span className="flex items-center gap-1 text-xl font-semibold tabular-nums">
                          {n === undefined ? "—" : num(n)}
                          {d && <ArrowRight className="size-4 text-zinc-400" aria-hidden />}
                        </span>
                      </>
                    )
                    return d ? (
                      <Link
                        key={k}
                        to={`/tex/reservations?${k === "arrivals" ? "arriving" : "departing"}=${d.today.date ?? today}`}
                        aria-label={t(`dash.${k}_open`, { count: n ?? 0 })}
                        className="-m-1.5 rounded-lg p-1.5 hover:bg-zinc-50 focus-visible:outline-2 focus-visible:outline-tex-600"
                      >
                        {body}
                      </Link>
                    ) : (
                      <div key={k}>{body}</div>
                    )
                  })}
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
