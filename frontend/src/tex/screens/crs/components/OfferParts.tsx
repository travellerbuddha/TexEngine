import type { ReactNode } from "react"
import { date, money, weekday } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Money } from "../../../ui"
import { cn } from "../../../../lib/utils"
import { useLabels } from "../lib/labels"
import { shortCode } from "../lib/party"
import type { Offer, PropertyResult, RatePlanInfo } from "../lib/types"
import { Row } from "./controls"
import { usePartyText } from "./PartyEditor"

export function roomName(p: PropertyResult | undefined, roomType: string) {
  return p?.rooms?.[roomType]?.name || shortCode(roomType, p?.property)
}

export function ratePlanName(o: Pick<Offer, "rate_plan" | "rate_plan_info"> & { property?: string }) {
  return o.rate_plan_info?.name || (o.rate_plan ? shortCode(o.rate_plan, o.property) : null)
}

/** "Standard Sea View" / "Half board · Flexible" */
export function OfferTitle({ offer, prop, className }: { offer: Offer; prop: PropertyResult | undefined; className?: string }) {
  const L = useLabels()
  const rp = ratePlanName({ ...offer, property: prop?.property })
  return (
    <div className={cn("min-w-0", className)}>
      <p className="truncate font-medium text-zinc-900">{roomName(prop, offer.room_type)}</p>
      <p className="truncate text-sm text-zinc-600">
        {L.board(offer.board)}
        {rp ? ` · ${rp}` : ""}
      </p>
    </div>
  )
}

export function RefundBadge({ refundable }: { refundable: boolean | undefined }) {
  const { t } = useTexT()
  if (refundable === undefined) return null
  return <Badge tone={refundable ? "success" : "warning"}>{refundable ? t("crs.offer.refundable") : t("crs.offer.non_refundable")}</Badge>
}

/** Truthful scarcity: the server's own count, shown plainly. */
export function AvailabilityBadge({ available, rooms }: { available: number; rooms: number }) {
  const { t } = useTexT()
  if (available < rooms) return <Badge tone="danger">{t("crs.offer.sold_out")}</Badge>
  return <Badge tone={available <= 3 ? "warning" : "neutral"}>{t("crs.offer.left", { count: available })}</Badge>
}

export function OfferBadges({ offer, rooms }: { offer: Offer; rooms: number }) {
  const { t } = useTexT()
  const applied = offer.rooms[0]?.quote.promotions.filter((p) => p.applied) ?? []
  return (
    <div className="flex flex-wrap items-center gap-1">
      <RefundBadge refundable={offer.refundable ?? offer.rate_plan_info?.refundable} />
      <AvailabilityBadge available={offer.available} rooms={rooms} />
      {applied.map((p) => (
        <Badge key={p.promo_id} tone="brand">
          {p.code ? t("crs.offer.promo_code", { code: p.code }) : p.name}
        </Badge>
      ))}
    </div>
  )
}

/** Server total for the stay and the server's average per night. */
export function OfferPrice({ offer, nights, rooms, align = "right" }: { offer: Offer; nights: number; rooms: number; align?: "left" | "right" }) {
  const { t } = useTexT()
  if (!offer.total) return null
  return (
    <div className={align === "right" ? "text-right" : "text-left"}>
      <p className="text-lg leading-tight font-semibold text-zinc-950">
        <Money amount={offer.total} currency={offer.currency} />
      </p>
      <p className="text-xs text-zinc-500">
        {offer.per_night ? t("crs.offer.per_night", { amount: money(offer.per_night, offer.currency) }) : null}
        {offer.per_night ? " · " : ""}
        {rooms > 1
          ? t("crs.offer.for_rooms", { count: rooms, nights: t("core.label.nights", { count: nights }) })
          : t("core.label.nights", { count: nights })}
      </p>
    </div>
  )
}

export function penaltyText(
  t: (k: string, p?: Record<string, string | number>) => string,
  rule: { penalty_type: string; penalty_value: string },
  currency?: string,
) {
  if (rule.penalty_type === "PERCENT") return t("crs.policy.pct", { value: rule.penalty_value.replace(/\.0+$/, "") })
  if (rule.penalty_type === "NIGHTS") return t("crs.policy.nights", { count: Number(rule.penalty_value) })
  return money(rule.penalty_value, currency)
}

/** Cancellation + payment terms of a rate plan, in the server's words plus rule lines. */
export function PolicySummary({ rp, currency, className }: { rp: RatePlanInfo | null | undefined; currency?: string; className?: string }) {
  const { t } = useTexT()
  const L = useLabels()
  if (!rp) return null
  const cp = rp.cancellation_policy
  const pp = rp.payment_policy
  const rules = [...(cp?.rules ?? [])].sort((a, b) => b.days_before_arrival - a.days_before_arrival)
  return (
    <dl className={cn("space-y-2 text-sm", className)}>
      <div>
        <dt className="text-xs font-medium text-zinc-500">{t("crs.policy.cancellation")}</dt>
        <dd className="text-zinc-800">
          {cp?.description || cp?.name || (rp.refundable ? t("crs.policy.free") : t("crs.offer.non_refundable"))}
          {rules.length > 0 && rp.refundable && (
            <ul className="mt-0.5 list-disc pl-4 text-xs text-zinc-600">
              {rules.map((r, i) => (
                <li key={i}>
                  {r.days_before_arrival >= 9999
                    ? t("crs.policy.rule_any", { penalty: penaltyText(t, r, currency) })
                    : t("crs.policy.rule", { days: r.days_before_arrival, penalty: penaltyText(t, r, currency) })}
                </li>
              ))}
            </ul>
          )}
        </dd>
      </div>
      {pp && (
        <div>
          <dt className="text-xs font-medium text-zinc-500">{t("crs.policy.payment")}</dt>
          <dd className="text-zinc-800">
            {pp.name || L.deposit(pp.deposit_type)}
            {pp.deposit_type && (
              <span className="text-zinc-600">
                {" "}
                · {L.deposit(pp.deposit_type)}
                {pp.deposit_type === "PERCENT" && pp.deposit_value ? ` ${pp.deposit_value.replace(/\.0+$/, "")}%` : ""}
                {pp.deposit_type === "FIXED" && pp.deposit_value ? ` ${money(pp.deposit_value, currency)}` : ""}
                {pp.deposit_type === "NIGHTS" && pp.deposit_value ? ` ${t("crs.policy.nights", { count: Number(pp.deposit_value) })}` : ""}
              </span>
            )}
            {pp.allow_pay_at_hotel && <span className="text-zinc-600"> · {t("crs.policy.pay_at_hotel_ok")}</span>}
            {pp.description ? <span className="block text-xs text-zinc-600">{pp.description}</span> : null}
          </dd>
        </div>
      )}
      {rp.inclusions?.length > 0 && (
        <div>
          <dt className="text-xs font-medium text-zinc-500">{t("crs.policy.inclusions")}</dt>
          <dd className="text-zinc-800">{rp.inclusions.join(", ")}</dd>
        </div>
      )}
    </dl>
  )
}

/** Expandable offer facts: per-room prices, policies, nightly stock, promotions, and
 * (price.view_cost only) cost, margin and the rule-level explanation. */
export function OfferDetails({
  offer,
  prop,
  parties,
  canCost,
}: {
  offer: Offer
  prop: PropertyResult | undefined
  parties: { adults: number; children: { age: number | null }[] }[]
  canCost: boolean
}) {
  const { t } = useTexT()
  const partyText = usePartyText()
  const available = offer.rooms[0]?.quote.promotions.filter((p) => !p.applied && p.code) ?? []
  const explanation = canCost ? offer.rooms[0]?.quote.explanation : undefined
  const content = prop?.rooms?.[offer.room_type]
  const facts = content
    ? [
        content.max_adults ? t("crs.offer.max_adults", { count: content.max_adults }) : null,
        content.max_children ? t("crs.offer.max_children", { count: content.max_children }) : null,
        content.size_sqm ? `${content.size_sqm} m²` : null,
        content.bed_type || content.beds || null,
        content.view || null,
      ].filter(Boolean)
    : []
  return (
    <div className="grid gap-4 rounded-lg bg-zinc-50 p-3 text-sm md:grid-cols-2">
      <div className="space-y-3">
        {(facts.length > 0 || content?.description) && (
          <p className="text-xs text-zinc-600">
            {facts.join(" · ")}
            {content?.description ? <span className="block">{content.description}</span> : null}
          </p>
        )}
        <section aria-label={t("crs.offer.rooms_priced")}>
          {offer.rooms.map((r) => {
            const party = parties[r.room_index]
            const tot = r.quote.totals
            return (
              <div key={r.room_index} className="border-b border-zinc-200 pb-1.5 last:border-0">
                <p className="text-xs font-medium text-zinc-500">
                  {t("crs.room_n", { n: r.room_index + 1 })}
                  {party ? ` · ${partyText(party.adults, party.children.map((c) => c.age))}` : ""}
                </p>
                <Row label={t("crs.quote.total")} value={<Money amount={tot.total} currency={r.quote.currency} />} />
                {r.per_night && <Row label={t("crs.quote.avg_night")} value={<Money amount={r.per_night} currency={r.quote.currency} />} />}
                {canCost && tot.cost !== undefined && (
                  <>
                    <Row label={t("crs.cost.cost")} value={<Money amount={tot.cost} currency={r.quote.currency} />} />
                    <Row
                      label={t("crs.cost.margin")}
                      value={
                        <>
                          <Money amount={tot.margin} currency={r.quote.currency} />
                          {tot.margin_percent ? <span className="text-zinc-500"> ({tot.margin_percent} %)</span> : null}
                        </>
                      }
                    />
                  </>
                )}
                {!r.quote.sellable && r.quote.reasons.map((x, i) => <p key={i} className="text-xs text-rose-700">{x.message}</p>)}
              </div>
            )
          })}
        </section>
        {offer.availability && offer.availability.length > 0 && (
          <section>
            <p className="text-xs font-medium text-zinc-500">{t("crs.offer.nightly_stock")}</p>
            <ul className="mt-1 flex flex-wrap gap-1">
              {offer.availability.map((d) => (
                <li key={d.day} className="rounded border border-zinc-200 bg-white px-1.5 py-0.5 text-xs tabular-nums" title={date(d.day)}>
                  <span className="text-zinc-500">
                    {weekday(d.day)} {Number(d.day.slice(8, 10))}
                  </span>{" "}
                  <span className={d.available <= 0 ? "font-semibold text-rose-700" : "font-medium text-zinc-900"}>{d.available}</span>
                </li>
              ))}
            </ul>
          </section>
        )}
        <p className="text-xs text-zinc-500">
          {t("crs.offer.contract", { code: offer.contract_code, version: offer.version })} · {offer.market}
        </p>
      </div>
      <div className="space-y-3">
        <PolicySummary rp={offer.rate_plan_info ?? offer.rooms[0]?.quote.rate_plan} currency={offer.currency} />
        {available.length > 0 && (
          <div>
            <p className="text-xs font-medium text-zinc-500">{t("crs.offer.codes_available")}</p>
            <ul className="text-xs text-zinc-700">
              {available.map((p) => (
                <li key={p.promo_id}>
                  <span className="font-semibold">{p.code}</span> · {p.name}
                </li>
              ))}
            </ul>
          </div>
        )}
        {explanation && explanation.length > 0 && <ExplanationList steps={explanation} />}
      </div>
    </div>
  )
}

/** Rule-level explanation (internal users only). */
export function ExplanationList({ steps, title }: { steps: { stage: string; text: string; night: string | null; rule?: { level: string | null; label: string } | null }[]; title?: ReactNode }) {
  const { t } = useTexT()
  return (
    <details className="group">
      <summary className="cursor-pointer text-xs font-medium text-tex-700 hover:underline">
        {title ?? t("crs.explain.title")} ({steps.length})
      </summary>
      <ol className="mt-2 max-h-72 space-y-0.5 overflow-y-auto rounded border border-zinc-200 bg-white p-2 font-mono text-[11px] leading-relaxed text-zinc-700">
        {steps.map((s, i) => (
          <li key={i}>
            {s.night ? <span className="text-zinc-400">[{s.night}] </span> : null}
            <span className="text-zinc-500">{s.stage}: </span>
            {s.text}
            {s.rule?.level ? <span className="text-zinc-400"> · {s.rule.level}</span> : null}
          </li>
        ))}
      </ol>
    </details>
  )
}
