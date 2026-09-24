import { Link } from "react-router-dom"
import { PackagePlus } from "lucide-react"
import { date, num } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, DataTable, EmptyState, Money } from "../../../ui"
import type { ExtraSummary, StayExtra } from "../types"

/** Extras the guest bought on stays at the viewer's hotels (R-37): a line per extra and
 * currency, then every extra with its stay. Amounts come from the server, per currency. */
export function ExtrasPanel({ lines, summary }: { lines: StayExtra[]; summary: ExtraSummary[] }) {
  const { t } = useTexT()
  if (!lines.length)
    return <EmptyState icon={<PackagePlus className="size-5" />} title={t("crm.profile.no_extras")} description={t("crm.profile.no_extras_hint")} />
  return (
    <div className="space-y-4">
      <ul aria-label={t("crm.extra.summary")} className="flex flex-wrap gap-2">
        {summary.map((s) => (
          <li key={`${s.code}-${s.currency}`} className="rounded-lg border border-zinc-200 px-3 py-2 text-sm">
            <p className="font-medium text-zinc-900">
              {s.name} <span className="text-zinc-500">× {num(s.quantity)}</span>
            </p>
            <p className="text-xs text-zinc-600">
              <Money amount={s.amount} currency={s.currency} /> · {t("crm.extra.stays", { count: s.stays })}
            </p>
          </li>
        ))}
      </ul>
      <DataTable<StayExtra>
        dense
        caption={t("crm.profile.extras_caption")}
        rows={lines}
        rowKey={(e) => `${e.reservation}-${e.code}-${e.service_dates.join(",")}-${e.added_later ? 1 : 0}`}
        columns={[
          {
            key: "extra",
            header: t("crm.extra.name"),
            cell: (e) => (
              <div className="min-w-0">
                <p className="font-medium">{e.name}</p>
                <p className="text-xs text-zinc-500">{e.code}</p>
                {e.added_later && <Badge tone="info">{t("crm.extra.added_later")}</Badge>}
              </div>
            ),
          },
          {
            key: "stay",
            header: t("crm.stay.reservation"),
            cell: (e) => (
              <div className="text-xs">
                <Link to={`/tex/reservations/${encodeURIComponent(e.reservation)}`} className="font-medium whitespace-nowrap text-tex-700 hover:underline">
                  {e.reservation}
                </Link>
                <p className="text-zinc-500">
                  {e.property} · {date(e.check_in, "short")}
                </p>
              </div>
            ),
          },
          { key: "qty", header: t("crm.extra.quantity"), align: "right", cell: (e) => num(e.quantity) },
          {
            key: "dates",
            header: t("crm.extra.service_dates"),
            hideBelow: "md",
            cell: (e) => <span className="text-xs text-zinc-600">{e.service_dates.length ? e.service_dates.map((d) => date(d, "short")).join(", ") : "—"}</span>,
          },
          { key: "amount", header: t("core.label.total"), align: "right", cell: (e) => <Money amount={e.amount} currency={e.currency} /> },
        ]}
      />
    </div>
  )
}
