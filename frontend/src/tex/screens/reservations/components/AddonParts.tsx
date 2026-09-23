// Extras added after booking (G-22, ADR-034): an add-on's price as the server returned it,
// and the reservation's add-ons. Amounts are never re-summed here.
import type { ReactNode } from "react"
import { useTexT } from "../../../i18n"
import { Badge, Card, CardBody, CardHeader, DescriptionList, Money } from "../../../ui"
import { cn } from "../../../../lib/utils"
import { Row } from "../../crs/components/controls"
import { shortDay } from "../../crs/lib/extrasStock"
import { useLabels } from "../../crs/lib/labels"
import { isPositive, isZero } from "../../crs/lib/party"
import { useServerClock } from "../../crs/lib/serverClock"
import type { ExtraOutcome } from "../../crs/lib/types"
import { extraDays, qtyText } from "../lib/addons"
import type { AddonEntry, AddonQuote } from "../lib/types"

/** The extras of an add-on (name × quantity, day(s), amount), its taxes and its total
 * (`totalRow={false}` when the total is shown next to it already). */
export function AddonBreakdown({ quote, className, totalRow = true }: { quote: AddonQuote; className?: string; totalRow?: boolean }) {
  const { t } = useTexT()
  const L = useLabels()
  const ccy = quote.currency
  const taxes = quote.taxes ?? []
  // extra lines carry the rounded amount; the outcomes carry quantity and days (one per line)
  const outcomes = new Map<string, ExtraOutcome[]>()
  for (const e of quote.extras ?? []) outcomes.set(e.code, [...(outcomes.get(e.code) ?? []), e])
  const lines = (quote.lines ?? []).filter((l) => l.kind !== "TAX" || !taxes.length)
  const tot = quote.totals ?? {}
  return (
    <div className={cn("space-y-2", className)}>
      <ul className="divide-y divide-zinc-100">
        {lines.map((l, i) => {
          const o = l.kind === "TAX" ? undefined : outcomes.get(l.code)?.shift()
          const days = o ? extraDays(o) : []
          return (
            <li key={i} className="flex items-baseline justify-between gap-3 py-1 text-sm">
              <span className="min-w-0 text-zinc-700">
                {l.description || o?.name || l.code}
                {o && <span className="text-zinc-500"> × {qtyText(o.quantity)}</span>}
                {o && (
                  <span className="block text-xs text-zinc-500">
                    {days.length ? days.map((d) => shortDay(d)).join(", ") : L.mode(o.pricing_mode)}
                  </span>
                )}
              </span>
              <Money amount={l.amount} currency={ccy} className="shrink-0" />
            </li>
          )
        })}
      </ul>
      {taxes.length > 0 && (
        <ul className="space-y-0.5 border-t border-zinc-100 pt-1.5">
          {taxes.map((x, i) => (
            <li key={i} className="flex items-baseline justify-between gap-3 text-sm text-zinc-600">
              <span>
                {x.name}
                {x.rate && !isZero(x.rate) ? ` ${x.rate.replace(/\.0+$/, "")}%` : ""}
                {x.included ? <span className="text-zinc-400"> · {t("crs.quote.tax_included")}</span> : null}
              </span>
              <Money amount={x.amount} currency={ccy} />
            </li>
          ))}
        </ul>
      )}
      {(totalRow || isPositive(tot.tax_added)) && (
        <div className="border-t border-zinc-200 pt-1.5">
          {isPositive(tot.tax_added) && (
            <>
              {tot.subtotal !== undefined && <Row label={t("crs.quote.subtotal")} value={<Money amount={tot.subtotal} currency={ccy} />} />}
              <Row label={t("crs.quote.tax_added")} value={<Money amount={tot.tax_added} currency={ccy} />} />
            </>
          )}
          {totalRow && <Row strong label={t("res.addon.addon_total")} value={<Money amount={tot.total} currency={ccy} />} />}
        </div>
      )}
    </div>
  )
}

/**
 * "Added after booking": every add-on of the reservation — when, by whom (guest online or
 * the desk), its extras and its total. They are already part of the locked price above.
 */
export function AddedExtrasCard({ addons, action }: { addons: AddonEntry[]; action?: ReactNode }) {
  const { t } = useTexT()
  const L = useLabels()
  const clock = useServerClock()
  const ordered = [...addons].sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0))
  return (
    <Card role="region" aria-label={t("res.addon.card_title")}>
      <CardHeader title={t("res.addon.card_title")} description={t("res.addon.card_hint")} actions={action} />
      <CardBody>
        <ol className="space-y-3">
          {ordered.map((a) => (
            <li
              key={a.id}
              className="space-y-3 rounded-lg border border-zinc-200 p-3"
              // raw figures for tools and tests (the text shows them formatted)
              data-addon={a.id}
              data-total={a.quote?.totals?.total ?? ""}
              data-currency={a.quote?.currency ?? ""}
            >
              <DescriptionList
                cols={3}
                items={[
                  { label: t("res.addon.added_at"), value: clock.label(a.at) },
                  {
                    label: t("res.addon.source"),
                    value: a.source ? <Badge tone={a.source === "Guest" ? "info" : "neutral"}>{L.source(a.source)}</Badge> : "—",
                  },
                  {
                    label: t("res.addon.addon_total"),
                    value: <Money amount={a.quote?.totals?.total} currency={a.quote?.currency} className="font-semibold" />,
                  },
                ]}
              />
              {a.quote && <AddonBreakdown quote={a.quote} totalRow={false} className="border-t border-zinc-100 pt-2" />}
            </li>
          ))}
        </ol>
      </CardBody>
    </Card>
  )
}
