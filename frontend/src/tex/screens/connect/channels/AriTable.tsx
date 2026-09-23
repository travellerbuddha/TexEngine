import { CalendarDays } from "lucide-react"
import { date, num, weekday } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, DataTable, EmptyState, Money } from "../../../ui"
import type { AriDay } from "./types"

/** Sync state of one day: the channel has it, it changed since, or it was never sent. */
export function SyncBadge({ day }: { day: AriDay }) {
  const { t } = useTexT()
  if (day.in_sync) return <Badge tone="success">{t("connect.channels.ari.in_sync")}</Badge>
  if (day.sent) return <Badge tone="warning">{t("connect.channels.ari.changed")}</Badge>
  return <Badge tone="neutral">{t("connect.channels.ari.never_sent")}</Badge>
}

function Restrictions({ day }: { day: AriDay }) {
  const { t } = useTexT()
  if (!day.closed && !day.cta && !day.ctd) return <span className="text-zinc-500">{t("connect.channels.ari.open")}</span>
  return (
    <span className="flex flex-wrap gap-1">
      {day.closed && <Badge tone="danger">{t("connect.channels.ari.closed")}</Badge>}
      {day.cta && <Badge tone="warning">{t("connect.channels.ari.cta")}</Badge>}
      {day.ctd && <Badge tone="warning">{t("connect.channels.ari.ctd")}</Badge>}
    </span>
  )
}

function Stay({ day }: { day: AriDay }) {
  const { t } = useTexT()
  const parts = [
    day.min_los ? t("connect.channels.ari.min_los", { n: day.min_los }) : null,
    day.max_los ? t("connect.channels.ari.max_los", { n: day.max_los }) : null,
  ].filter(Boolean)
  return parts.length ? <span className="whitespace-nowrap">{parts.join(" · ")}</span> : <span className="text-zinc-500">—</span>
}

/** Prices per adults exactly as the server sent them (strings, formatted only). */
function Rates({ day }: { day: AriDay }) {
  const { t } = useTexT()
  if (!day.rates.length) return <span className="text-zinc-500">{t("connect.channels.ari.no_price")}</span>
  return (
    <ul className="space-y-0.5">
      {day.rates.map((r) => (
        <li key={r.adults} className="flex items-baseline justify-between gap-3 whitespace-nowrap">
          <span className="text-xs text-zinc-500">{t("connect.channels.ari.adults", { count: r.adults })}</span>
          <Money amount={r.price} currency={day.currency} className="font-medium text-zinc-900" />
        </li>
      ))}
    </ul>
  )
}

/** What TEX would send to the channel per day, next to what the channel last accepted.
 * On phones the date cell also carries availability, restrictions and the sync state
 * (their columns are hidden), so the table is date + prices at 320px. */
export function AriTable({ days, loading, caption }: { days: AriDay[] | undefined; loading: boolean; caption: string }) {
  const { t } = useTexT()
  return (
    <DataTable<AriDay>
      caption={caption}
      rows={days}
      loading={loading}
      rowKey={(d) => d.date}
      dense
      rowClassName={(d) => (d.sent && !d.in_sync ? "bg-amber-50/50" : undefined)}
      empty={<EmptyState icon={<CalendarDays className="size-5" />} title={t("connect.channels.ari.empty")} />}
      columns={[
        {
          key: "date",
          header: t("connect.channels.ari.col.date"),
          cell: (d) => (
            <span className="block">
              <span className="whitespace-nowrap">
                <span className="mr-1.5 text-xs text-zinc-500">{weekday(d.date)}</span>
                {date(d.date)}
              </span>
              <span className="mt-1 flex flex-col items-start gap-1 text-xs sm:hidden">
                <SyncBadge day={d} />
                <span className="text-zinc-600">{t("connect.channels.ari.available_n", { n: num(d.available) })}</span>
                <Restrictions day={d} />
              </span>
            </span>
          ),
        },
        { key: "available", header: t("connect.channels.ari.col.available"), align: "right", hideBelow: "sm", cell: (d) => num(d.available) },
        { key: "restrictions", header: t("connect.channels.ari.col.restrictions"), hideBelow: "sm", cell: (d) => <Restrictions day={d} /> },
        { key: "stay", header: t("connect.channels.ari.col.stay"), hideBelow: "md", cell: (d) => <Stay day={d} /> },
        { key: "rates", header: t("connect.channels.ari.col.rates"), cell: (d) => <Rates day={d} /> },
        { key: "sync", header: t("connect.channels.ari.col.sync"), hideBelow: "sm", cell: (d) => <SyncBadge day={d} /> },
      ]}
    />
  )
}
