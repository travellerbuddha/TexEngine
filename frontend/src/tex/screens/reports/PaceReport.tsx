import { useMemo, useState } from "react"
import { Info } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { useSession } from "../../lib/session"
import { date, num } from "../../lib/format"
import { useTexT } from "../../i18n"
import { Card, CardBody, CardHeader, EmptyState, ErrorState, Skeleton } from "../../ui"
import { cn } from "../../../lib/utils"
import { BarChart, type ChartDatum } from "./components/BarChart"
import { RangeFilter } from "./components/RangeFilter"
import { presetRange, rangeProblem, type RangePreset } from "./lib"
import { ReportsFrame } from "./ReportsFrame"

interface PacePoint {
  days_ago: number
  as_of: string
  room_nights: number
}

interface PaceData {
  property: string
  from: string
  to: string
  points: PacePoint[]
}

const PRESETS = ["next_30", "next_90", "this_month", "next_month", "this_year"] as const

function signed(n: number) {
  return n > 0 ? `+${num(n)}` : n < 0 ? `−${num(Math.abs(n))}` : num(0)
}

export default function PaceReport() {
  const { t } = useTexT()
  const { property } = useSession()
  const [range, setRange] = useState<{ preset: RangePreset; from: string; to: string }>(() => {
    const [from, to] = presetRange("next_90")
    return { preset: "next_90", from, to }
  })
  const problem = rangeProblem(range.from, range.to)
  const q = useTexQuery<PaceData>(
    "reports",
    "pace",
    { property: property?.name, stay_from: range.from, stay_to: range.to },
    [property?.name, range.from, range.to],
    !problem && !!property,
  )
  const d = q.data

  // oldest snapshot first; pick-up = growth versus the previous snapshot
  const points = useMemo(() => {
    if (!d) return []
    const sorted = [...d.points].sort((a, b) => b.days_ago - a.days_ago)
    return sorted.map((p, i) => ({ ...p, pickup: i === 0 ? null : p.room_nights - sorted[i - 1].room_nights }))
  }, [d])
  const at = (n: number) => d?.points.find((p) => p.days_ago === n)?.room_nights
  const today = at(0)
  const pick = (n: number) => (today !== undefined && at(n) !== undefined ? today - (at(n) as number) : undefined)
  const whenLabel = (n: number) => (n === 0 ? t("reports.pace.today") : t("reports.pace.days_ago", { count: n }))

  const chart: ChartDatum[] = points.map((p) => ({
    key: String(p.days_ago),
    label: whenLabel(p.days_ago),
    sublabel: date(p.as_of, "short"),
    value: p.room_nights,
    display: num(p.room_nights),
  }))

  return (
    <ReportsFrame subtitle={property?.property_name}>
      <Card className="mb-4">
        <CardBody className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <RangeFilter
              presets={[...PRESETS]}
              preset={range.preset}
              from={range.from}
              to={range.to}
              onChange={setRange}
              error={problem ? t(problem, { max: 800 }) : null}
              labels={{ period: t("reports.pace.stay_window"), from: t("reports.filter.stay_from"), to: t("core.label.to") }}
            />
          </div>
          <div className="flex items-start gap-2 rounded-lg bg-zinc-50 px-3 py-2 text-xs text-zinc-600">
            <Info className="mt-0.5 size-3.5 shrink-0 text-zinc-500" aria-hidden />
            <p>{t("reports.pace.help")}</p>
          </div>
        </CardBody>
      </Card>

      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : (
        <div className="space-y-4">
          <section aria-label={t("reports.totals")} className={cn("grid grid-cols-1 gap-3 sm:grid-cols-3", q.loading && d && "opacity-60")}>
            {!d ? (
              Array.from({ length: 3 }).map((_, i) => (
                <Card key={i} className="p-4">
                  <Skeleton className="h-3 w-24" />
                  <Skeleton className="mt-3 h-6 w-16" />
                </Card>
              ))
            ) : (
              <>
                <Tile label={t("reports.pace.otb_today")} value={today !== undefined ? num(today) : "—"} hint={t("reports.pace.window", { from: date(d.from), to: date(d.to) })} />
                <Tile label={t("reports.pace.pickup_7")} value={pick(7) !== undefined ? signed(pick(7) as number) : "—"} hint={t("reports.col.room_nights")} />
                <Tile label={t("reports.pace.pickup_30")} value={pick(30) !== undefined ? signed(pick(30) as number) : "—"} hint={t("reports.col.room_nights")} />
              </>
            )}
          </section>

          <Card>
            <CardHeader title={t("reports.pace.chart_title")} description={t("reports.pace.chart_hint")} />
            <CardBody>
              {!d ? (
                <Skeleton className="h-56 w-full" />
              ) : points.every((p) => p.room_nights === 0) ? (
                <EmptyState title={t("reports.pace.empty")} />
              ) : (
                <BarChart
                  data={chart}
                  height={240}
                  stale={q.loading}
                  summary={t("reports.pace.summary", {
                    from: date(d.from),
                    to: date(d.to),
                    today: num(today ?? 0),
                  })}
                />
              )}
            </CardBody>
            {d && (
              <div className="overflow-x-auto border-t border-zinc-100">
                <table className="min-w-full text-sm">
                  <caption className="sr-only">{t("reports.pace.table_caption")}</caption>
                  <thead>
                    <tr className="bg-zinc-50 text-xs font-semibold tracking-wide text-zinc-600 uppercase">
                      <th scope="col" className="px-4 py-2 text-left">
                        {t("reports.pace.col.as_of")}
                      </th>
                      <th scope="col" className="hidden px-4 py-2 text-left sm:table-cell">
                        {t("reports.pace.col.when")}
                      </th>
                      <th scope="col" className="px-4 py-2 text-right">
                        {t("reports.pace.col.otb")}
                      </th>
                      <th scope="col" className="px-4 py-2 text-right">
                        {t("reports.pace.col.pickup")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {points.map((p) => (
                      <tr key={p.days_ago} className="border-t border-zinc-100">
                        <th scope="row" className="px-4 py-2 text-left font-medium text-zinc-900">
                          {date(p.as_of)}
                          <span className="block text-xs font-normal text-zinc-500 sm:hidden">{whenLabel(p.days_ago)}</span>
                        </th>
                        <td className="hidden px-4 py-2 text-zinc-700 sm:table-cell">{whenLabel(p.days_ago)}</td>
                        <td className="px-4 py-2 text-right text-zinc-900 tabular-nums">{num(p.room_nights)}</td>
                        <td className="px-4 py-2 text-right text-zinc-700 tabular-nums">{p.pickup === null ? "—" : signed(p.pickup)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      )}
    </ReportsFrame>
  )
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="px-4 py-3">
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p className="mt-0.5 text-xl font-semibold tracking-tight text-zinc-950">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-zinc-500">{hint}</p>}
    </Card>
  )
}
