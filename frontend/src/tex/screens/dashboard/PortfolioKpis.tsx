import type { ReactNode } from "react"
import { cn } from "../../../lib/utils"
import { date } from "../../lib/format"
import { useTexT } from "../../i18n"
import { Card, Money, Skeleton } from "../../ui"
import type { Amounts, PortfolioData } from "./portfolio"

/**
 * Amounts of several currencies, one line each (never added together). The
 * ranking currency comes first; with no amount at all `empty` is shown.
 */
export function AmountStack({
  amounts,
  first,
  empty,
  align = "start",
  className,
}: {
  amounts: Amounts | undefined
  first?: string
  empty?: ReactNode
  align?: "start" | "end"
  className?: string
}) {
  const entries = Object.entries(amounts ?? {}).filter(([c, v]) => c && v !== undefined && v !== null)
  if (!entries.length) return <>{empty ?? <span className="text-zinc-400">—</span>}</>
  entries.sort(([a], [b]) => (a === first ? -1 : b === first ? 1 : a.localeCompare(b)))
  return (
    <span className={cn("inline-flex flex-col", align === "end" ? "items-end" : "items-start", className)}>
      {entries.map(([c, v]) => (
        <Money key={c} amount={v} currency={c} />
      ))}
    </span>
  )
}

interface Tile {
  id: string
  label: string
  amounts: Amounts
  meta: string
  /** The figure does not apply to this window: show a dash, not a zero. */
  noValue?: boolean
}

/** Portfolio key figures: money per currency (stacked), counts beside it. */
export function PortfolioKpis({ data, currency }: { data: PortfolioData | undefined; currency?: string }) {
  const { t } = useTexT()
  const label = t("dash.kpis")
  if (!data)
    return (
      <section aria-label={label} aria-busy="true" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <Card key={i} className="p-4">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-3 h-6 w-28" />
            <Skeleton className="mt-2 h-3 w-20" />
          </Card>
        ))}
      </section>
    )
  const x = data.totals
  const bookings = (n: number) => t("dash.pf.n_bookings", { count: n })
  // "today" (server date) is only counted when it lies inside the chosen sale window
  const todayInWindow = data.from <= data.today && data.today <= data.to
  const tiles: Tile[] = [
    {
      id: "today",
      label: t("dash.pf.kpi.today"),
      amounts: todayInWindow ? x.today_value : {},
      meta: todayInWindow
        ? `${bookings(x.sold_today)} · ${date(data.today)}`
        : t("dash.pf.kpi.today_outside", { date: date(data.today) }),
      noValue: !todayInWindow,
    },
    { id: "value", label: t("dash.pf.kpi.booking_value"), amounts: x.booking_value, meta: bookings(x.sold) },
    { id: "direct", label: t("dash.pf.kpi.direct"), amounts: x.direct_value, meta: t("dash.pf.kpi.direct_hint") },
    { id: "call", label: t("dash.pf.kpi.call_centre"), amounts: x.call_centre_value, meta: t("dash.pf.kpi.call_centre_hint") },
    {
      id: "cancel",
      label: t("dash.pf.kpi.cancellations"),
      amounts: x.cancelled_value,
      meta: t("dash.pf.n_cancellations", { count: x.cancellations }),
    },
    { id: "pending", label: t("dash.pf.kpi.pending_payment"), amounts: x.pending_payment_value, meta: bookings(x.pending_payment) },
    { id: "balance", label: t("dash.pf.kpi.open_balances"), amounts: x.open_balance_value, meta: bookings(x.open_balances) },
    {
      id: "abandoned",
      label: t("dash.pf.kpi.abandoned"),
      amounts: x.abandoned_value,
      meta: `${t("dash.pf.n_opportunities", { count: x.abandoned })} · ${t("dash.pf.kpi.abandoned_hint", { count: 30 })}`,
    },
  ]
  return (
    <section aria-label={label}>
      <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tiles.map((tile) => (
          <Card key={tile.id} className="flex flex-col p-3 sm:p-4">
            <dt className="text-xs font-medium tracking-wide text-zinc-500 uppercase">{tile.label}</dt>
            <dd className="mt-1 text-base font-semibold tracking-tight text-zinc-950 tabular-nums sm:text-lg xl:text-xl">
              <AmountStack
                amounts={tile.amounts}
                first={currency}
                empty={<Money amount={currency && !tile.noValue ? "0" : null} currency={currency} muted />}
              />
            </dd>
            <dd className="mt-auto pt-1 text-xs text-zinc-500">{tile.meta}</dd>
          </Card>
        ))}
      </dl>
    </section>
  )
}
