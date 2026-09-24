import { useId, useMemo, type ComponentType } from "react"
import { Link } from "react-router-dom"
import { AlertTriangle, ArrowDownToLine, ArrowRight, ArrowUpFromLine, Ban, CheckCircle2, CircleSlash, Lock, TrendingDown } from "lucide-react"
import { useSession } from "../../lib/session"
import { date, weekday } from "../../lib/format"
import { useTexT } from "../../i18n"
import { Badge, Card, CardHeader, EmptyState, Notice, Skeleton, type Tone } from "../../ui"
import { groupAlerts, isInventoryAlert, useSelectHotel, type HotelAlerts, type PortfolioAlert, type PortfolioData } from "./portfolio"

const ALERT_DAYS = 14

/** Every kind has its own icon and words, so the state never rests on colour alone. */
const KIND: Record<PortfolioAlert["kind"], { tone: Tone; icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }> }> = {
  oversold: { tone: "danger", icon: AlertTriangle },
  sold_out: { tone: "danger", icon: CircleSlash },
  few_left: { tone: "warning", icon: TrendingDown },
  closed: { tone: "neutral", icon: Lock },
  stop_sell: { tone: "danger", icon: Ban },
  closed_to_arrival: { tone: "warning", icon: ArrowDownToLine },
  closed_to_departure: { tone: "warning", icon: ArrowUpFromLine },
}

function AlertLine({ alert }: { alert: PortfolioAlert }) {
  const { t } = useTexT()
  const { boot } = useSession()
  const k = KIND[alert.kind]
  const Icon = k.icon
  const parts: string[] = [alert.room_type_name || alert.room_type || t("dash.pf.alert.all_rooms")]
  if (isInventoryAlert(alert)) {
    if (alert.kind === "oversold") parts.push(t("dash.pf.alert.over", { count: -alert.free }))
    else if (alert.kind === "few_left") parts.push(t("dash.pf.alert.left", { count: alert.free, capacity: alert.capacity }))
  } else {
    if (alert.market)
      parts.push(t("dash.pf.alert.market", { market: boot.markets.find((m) => m.name === alert.market)?.market_name ?? alert.market }))
    if (alert.channel)
      parts.push(t("dash.pf.alert.channel", { channel: boot.channels.find((c) => c.name === alert.channel)?.channel_name ?? alert.channel }))
    else if (alert.channel_scope)
      parts.push(t("dash.pf.alert.channel", { channel: t(`dash.pf.scope.${alert.channel_scope === "Booking Engine" ? "be" : alert.channel_scope === "Call Center" ? "cc" : "both"}`) }))
  }
  return (
    <li className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm">
      <Badge tone={k.tone}>
        <Icon className="size-3" aria-hidden />
        {t(`dash.pf.kind.${alert.kind}`)}
      </Badge>
      <span className="min-w-0 break-words text-zinc-700">{parts.join(" · ")}</span>
    </li>
  )
}

/** Inventory and restriction alerts of the next two weeks, by hotel and day. */
export function PortfolioAlerts({ data }: { data: PortfolioData | undefined }) {
  const { t } = useTexT()
  const select = useSelectHotel()
  const uid = useId()
  const groups = useMemo(() => groupAlerts(data?.alerts ?? []), [data])
  // the hotel's full counts (the list itself may be capped by the server)
  const counts = (g: HotelAlerts) => {
    const h = data?.hotels.find((x) => x.hotel === g.hotel)
    const inv = h?.inventory_alerts ?? g.inventory
    const res = h?.restriction_alerts ?? g.restrictions
    return [
      inv ? t("dash.pf.n_inventory_alerts", { count: inv }) : null,
      res ? t("dash.pf.n_restriction_alerts", { count: res }) : null,
    ]
      .filter(Boolean)
      .join(" · ")
  }
  return (
    <Card>
      <CardHeader title={t("dash.pf.alerts")} description={t("dash.pf.alerts_hint", { count: ALERT_DAYS })} />
      {!data ? (
        <div className="space-y-3 p-4" aria-busy="true">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="space-y-2">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-4 w-full max-w-md" />
            </div>
          ))}
        </div>
      ) : groups.length === 0 ? (
        <EmptyState icon={<CheckCircle2 className="size-5" />} title={t("dash.pf.no_alerts")} description={t("dash.pf.no_alerts_hint", { count: ALERT_DAYS })} />
      ) : (
        <>
          {data.alerts_total > data.alerts.length && (
            <div className="px-4 pt-3">
              <Notice tone="info">{t("dash.pf.alerts_capped", { shown: data.alerts.length, count: data.alerts_total })}</Notice>
            </div>
          )}
          <ul className="divide-y divide-zinc-100">
            {groups.map((g, gi) => (
              <li key={g.hotel} className="px-4 py-3">
                <section aria-labelledby={`${uid}-${gi}`}>
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                    <div className="min-w-0">
                      <h3 id={`${uid}-${gi}`} className="text-sm font-semibold text-zinc-900">
                        {g.hotel_name}
                      </h3>
                      <p className="text-xs text-zinc-500">{counts(g)}</p>
                    </div>
                    <Link
                      to="/tex/inventory"
                      onClick={select(g.hotel)}
                      className="inline-flex items-center gap-1 text-sm font-medium text-tex-700 underline-offset-2 hover:underline focus-visible:underline"
                    >
                      {t("dash.pf.open_inventory")}
                      <span className="sr-only">: {g.hotel_name}</span>
                      <ArrowRight className="size-4" aria-hidden />
                    </Link>
                  </div>
                  <ul className="mt-2 space-y-2">
                    {g.days.map((d) => (
                      <li key={d.date} className="grid gap-1 sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-3">
                        <time dateTime={d.date} className="text-xs font-medium text-zinc-600 sm:pt-1">
                          {weekday(d.date)} {date(d.date)}
                        </time>
                        <ul className="space-y-1">
                          {d.alerts.map((a, i) => (
                            <AlertLine key={`${a.kind}-${a.room_type ?? ""}-${i}`} alert={a} />
                          ))}
                        </ul>
                      </li>
                    ))}
                  </ul>
                </section>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  )
}
