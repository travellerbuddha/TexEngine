import { AlertTriangle } from "lucide-react"
import { date, weekday } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Money } from "../../../ui"
import { cn } from "../../../../lib/utils"
import { extraReasonText, parseCapacityReason } from "../lib/extrasStock"
import { isPositive, isZero } from "../lib/party"
import type { QuoteDict } from "../lib/types"
import { Disclosure, Row } from "./controls"

/** Guest-facing nightly amounts: quote nights ({date, amount}) or a snapshot's nightly list. */
export function NightlyTable({ nights, currency, caption }: { nights: { date: string; amount: string }[]; currency: string; caption: string }) {
  const { t } = useTexT()
  if (!nights.length) return null
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">{caption}</caption>
      <thead className="sr-only">
        <tr>
          <th scope="col">{t("crs.quote.night")}</th>
          <th scope="col">{t("crs.quote.amount")}</th>
        </tr>
      </thead>
      <tbody>
        {nights.map((n) => (
          <tr key={n.date} className="border-b border-zinc-100 last:border-0">
            <td className="py-0.5 text-zinc-600">
              <span className="inline-block w-10 text-zinc-400">{weekday(n.date)}</span>
              {date(n.date)}
            </td>
            <td className="py-0.5 text-right tabular-nums">
              <Money amount={n.amount} currency={currency} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Lines, taxes and totals exactly as the server returned them (never re-summed). */
export function PriceBreakdown({
  quote,
  nightly,
  canCost,
  className,
  showNightly = true,
  finalTotal,
}: {
  /** A manual final price (price override) that replaces the calculated total. */
  finalTotal?: string | null
  quote: Pick<QuoteDict, "lines" | "taxes" | "totals" | "currency" | "promotions" | "extras"> & { nights?: QuoteDict["nights"] }
  /** Overrides quote.nights (e.g. ui_crs.reservation's rounded nightly list). */
  nightly?: { date: string; amount: string }[]
  canCost?: boolean
  className?: string
  showNightly?: boolean
}) {
  const { t } = useTexT()
  const ccy = quote.currency
  // tax lines are shown from `taxes` when present (rate + included flag); otherwise as lines
  const lines = (quote.taxes ?? []).length ? (quote.lines ?? []).filter((l) => l.kind !== "TAX") : (quote.lines ?? [])
  const tot = quote.totals ?? {}
  const nights = nightly ?? (quote.nights ?? []).filter((n): n is { date: string; amount: string } => typeof n.amount === "string")
  const failedExtras = (quote.extras ?? []).filter((e) => !e.ok)
  return (
    <div className={cn("space-y-2", className)}>
      <ul className="divide-y divide-zinc-100">
        {lines.map((l, i) => (
          <li key={i} className="flex items-baseline justify-between gap-3 py-1 text-sm">
            <span className="min-w-0 text-zinc-700">
              {l.description}
              {l.ref && l.kind !== "ACCOMMODATION" ? <span className="text-zinc-400"> · {l.ref}</span> : null}
            </span>
            <Money amount={l.amount} currency={ccy} signed={l.amount.trim().startsWith("-")} className="shrink-0" />
          </li>
        ))}
      </ul>
      {(quote.taxes ?? []).length > 0 && (
        <ul className="space-y-0.5 border-t border-zinc-100 pt-1.5">
          {quote.taxes.map((x, i) => (
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
      <div className="border-t border-zinc-200 pt-1.5">
        {tot.subtotal !== undefined && tot.subtotal !== tot.total && <Row label={t("crs.quote.subtotal")} value={<Money amount={tot.subtotal} currency={ccy} />} />}
        {tot.tax_added && isPositive(tot.tax_added) && <Row label={t("crs.quote.tax_added")} value={<Money amount={tot.tax_added} currency={ccy} />} />}
        {tot.discounts && isPositive(tot.discounts) && (
          <Row label={t("crs.quote.discounts")} value={<Money amount={`-${tot.discounts}`} currency={ccy} signed />} />
        )}
        {finalTotal ? (
          <>
            <Row label={t("crs.quote.calculated_total")} value={<Money amount={tot.total} currency={ccy} className="text-zinc-500 line-through" />} />
            <Row strong label={t("crs.quote.final_manual")} value={<Money amount={finalTotal} currency={ccy} />} />
          </>
        ) : (
          <Row strong label={t("crs.quote.total")} value={<Money amount={tot.total} currency={ccy} />} />
        )}
        {canCost && tot.cost !== undefined && (
          <div className="mt-1 rounded-md border border-dashed border-zinc-300 px-2 py-1">
            <p className="text-[11px] font-semibold tracking-wide text-zinc-500 uppercase">{t("crs.cost.internal")}</p>
            <Row label={t("crs.cost.cost")} value={<Money amount={tot.cost} currency={ccy} />} />
            <Row
              label={t("crs.cost.margin")}
              value={
                <>
                  <Money amount={tot.margin} currency={ccy} />
                  {tot.margin_percent ? <span className="text-zinc-500"> ({tot.margin_percent} %)</span> : null}
                </>
              }
            />
          </div>
        )}
      </div>
      {failedExtras.length > 0 && (
        // not charged: a capacity refusal (sold out, closed, only N left — G-19) or a rule
        <ul className="space-y-0.5 text-xs text-amber-800">
          {failedExtras.map((e, i) => (
            <li key={`${e.code}-${i}`} className={cn("flex items-start gap-1", parseCapacityReason(e.reason) && "font-medium")}>
              <AlertTriangle className="mt-px size-3.5 shrink-0" aria-hidden />
              <span>{t("crs.quote.extra_failed", { name: e.name || e.code, reason: extraReasonText(t, e.reason) })}</span>
            </li>
          ))}
        </ul>
      )}
      {showNightly && nights.length > 0 && (
        <Disclosure summary={t("crs.quote.nightly", { count: nights.length })}>
          <NightlyTable nights={nights} currency={ccy} caption={t("crs.quote.nightly", { count: nights.length })} />
        </Disclosure>
      )}
    </div>
  )
}
