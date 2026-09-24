import { useState } from "react"
import { Link } from "react-router-dom"
import { BarChart3, Settings2 } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { num, pct } from "../../lib/format"
import { useSession } from "../../lib/session"
import { useSiteToday } from "../../lib/siteDay"
import { useTexT } from "../../i18n"
import { Card, CardBody, CardHeader, EmptyState, ErrorState, PageHeader, Skeleton, Stat, Toolbar } from "../../ui"
import { RangeFilter } from "../reports/components/RangeFilter"
import { presetRange, type RangePreset } from "../reports/lib"
import { BeNav } from "./BeNav"

/** The booking-engine part of kamra.tex.api.reports.dashboard (funnel events, R-38). */
interface Dashboard {
  from: string
  to: string
  funnel: { search: number; quote: number; guest_details: number; payment_started: number; booked: number; conversion_pct: string | null }
  abandoned_open: number
}

interface SiteRow {
  name: string
  site_name: string
  property: string | null
  enabled: number
}

const STEPS = ["search", "quote", "guest_details", "payment_started", "booked"] as const
const PRESETS: Exclude<RangePreset, "custom">[] = ["last_30", "this_month", "last_month", "ytd"]

/** Share of `n` in `of` with one decimal, for display only (counts, not money). */
function share(n: number, of: number): string | null {
  return of > 0 ? String(Math.round((n / of) * 1000) / 10) : null
}

/** Booking engine analytics (R-35 Booking Engine › Analytics, G-64): how many visiting
 * sessions reach each step of the booking engine at the selected hotel, from its funnel
 * events (report.view, checked by the server). Tracking tags are set per site. */
export default function Analytics() {
  const { t } = useTexT()
  const { property, can } = useSession()
  const today = useSiteToday()
  const [range, setRange] = useState<{ preset: RangePreset; from: string; to: string }>(() => {
    const [from, to] = presetRange("last_30", today)
    return { preset: "last_30", from, to }
  })
  const bad = range.to < range.from
  const q = useTexQuery<Dashboard>("reports", "dashboard", { property: property?.name, date_from: range.from, date_to: range.to }, [property?.name, range.from, range.to], Boolean(property) && !bad)
  const sites = useTexQuery<SiteRow[]>("policies", "list_records", { doctype: "TEX Booking Site" }, [], can("price.view"))
  const f = q.data?.funnel
  const mine = (sites.data ?? []).filter((s) => !s.property || s.property === property?.name)

  return (
    <>
      <PageHeader
        title={t("core.nav.sub.analytics")}
        subtitle={property ? t("be.analytics_page.subtitle", { hotel: property.property_name }) : undefined}
        crumbs={[{ label: t("core.nav.booking_engine"), to: "/tex/booking-engine" }, { label: t("core.nav.sub.analytics") }]}
      />
      <BeNav />
      <Toolbar className="items-end">
        <RangeFilter presets={PRESETS} preset={range.preset} from={range.from} to={range.to} onChange={setRange} error={bad ? t("be.analytics_page.range_order") : null} />
      </Toolbar>
      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : (
        <div className="space-y-5">
          <section aria-label={t("be.analytics_page.summary")} className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {f ? (
              <>
                <Stat label={t("be.analytics_page.step.search")} value={num(f.search)} />
                <Stat label={t("be.analytics_page.step.booked")} value={num(f.booked)} />
                <Stat label={t("dash.conversion")} value={pct(f.conversion_pct)} hint={t("be.analytics_page.conversion_hint")} />
                <Stat
                  label={t("be.analytics_page.abandoned")}
                  value={num(q.data?.abandoned_open ?? 0)}
                  hint={
                    can("crm.view") ? (
                      <Link to="/tex/crm/abandoned" className="font-medium text-tex-700 underline">
                        {t("be.analytics_page.open_abandoned")}
                      </Link>
                    ) : undefined
                  }
                />
              </>
            ) : (
              Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 w-full" />)
            )}
          </section>

          <Card>
            <CardHeader title={t("be.analytics_page.funnel")} description={t("be.analytics_page.funnel_hint")} />
            {!f ? (
              <CardBody>
                <Skeleton className="h-40 w-full" />
              </CardBody>
            ) : f.search === 0 ? (
              <EmptyState icon={<BarChart3 className="size-5" />} title={t("be.analytics_page.none")} description={t("be.analytics_page.none_hint")} />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <caption className="sr-only">{t("be.analytics_page.funnel")}</caption>
                  <thead>
                    <tr className="border-b border-zinc-200 text-left text-xs font-medium text-zinc-600">
                      <th scope="col" className="px-4 py-2">
                        {t("be.analytics_page.col.step")}
                      </th>
                      <th scope="col" className="px-4 py-2 text-right">
                        {t("be.analytics_page.col.sessions")}
                      </th>
                      <th scope="col" className="hidden px-4 py-2 text-right sm:table-cell">
                        {t("be.analytics_page.col.of_searches")}
                      </th>
                      <th scope="col" className="px-4 py-2 text-right">
                        {t("be.analytics_page.col.from_previous")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {STEPS.map((s, i) => {
                      const n = f[s]
                      const prev = i ? f[STEPS[i - 1]] : null
                      const width = f.search ? Math.min(100, (n / f.search) * 100) : 0
                      return (
                        <tr key={s} className="border-b border-zinc-100 last:border-0">
                          <th scope="row" className="px-4 py-2.5 text-left font-medium text-zinc-900">
                            {t(`be.analytics_page.step.${s}`)}
                            <span className="mt-1 block h-1.5 rounded-full bg-zinc-100" aria-hidden>
                              <span className="block h-1.5 rounded-full bg-tex-600" style={{ width: `${width}%` }} />
                            </span>
                          </th>
                          <td className="px-4 py-2.5 text-right tabular-nums">{num(n)}</td>
                          <td className="hidden px-4 py-2.5 text-right text-zinc-700 tabular-nums sm:table-cell">{pct(share(n, f.search))}</td>
                          <td className="px-4 py-2.5 text-right text-zinc-700 tabular-nums">{prev === null ? "—" : pct(share(n, prev))}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {can("price.view") && (
            <Card>
              <CardHeader title={t("be.analytics_page.tracking")} description={t("be.analytics_page.tracking_hint")} />
              {sites.error ? (
                <ErrorState error={sites.error} onRetry={sites.reload} />
              ) : (
                <ul className="divide-y divide-zinc-100">
                  {mine.map((s) => (
                    <li key={s.name} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
                      <span className="min-w-0 truncate font-medium text-zinc-900">{s.site_name}</span>
                      <Link to={`/tex/booking-engine/${encodeURIComponent(s.name)}?tab=analytics`} className="inline-flex shrink-0 items-center gap-1.5 font-medium text-tex-700 underline">
                        <Settings2 className="size-4" aria-hidden />
                        {t("be.analytics_page.tracking_open")}
                      </Link>
                    </li>
                  ))}
                  {sites.data && !mine.length && <li className="px-4 py-3 text-sm text-zinc-600">{t("be.analytics_page.no_sites")}</li>}
                </ul>
              )}
            </Card>
          )}
        </div>
      )}
    </>
  )
}
