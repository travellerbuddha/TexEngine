import { useEffect, useState } from "react"
import { cn } from "../../../../lib/utils"
import { clock as countdown, useServerClock } from "../lib/serverClock"
import { AlertTriangle, RefreshCw } from "lucide-react"
import { money } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, Money, Notice, Skeleton } from "../../../ui"
import { extrasFor } from "../lib/api"
import { useLabels } from "../lib/labels"
import type { BookingFlow } from "../lib/useBookingFlow"
import { asApiError } from "../lib/useBookingFlow"
import type { ExtraDef, PropertyResult } from "../lib/types"
import type { TexApiError } from "../../../lib/api"
import { CodeChips, NumberStepper } from "./controls"
import { OfferTitle } from "./OfferParts"
import { usePartyText } from "./PartyEditor"
import { PriceBreakdown } from "./PriceBreakdown"

const extrasCache = new Map<string, ExtraDef[]>()

/** Extras catalogue of a hotel (crs.extras_for), cached per session. */
export function useExtras(property: string | undefined) {
  const [data, setData] = useState<ExtraDef[] | undefined>(property ? extrasCache.get(property) : undefined)
  const [error, setError] = useState<TexApiError>()
  useEffect(() => {
    if (!property) return
    const hit = extrasCache.get(property)
    if (hit) {
      setData(hit)
      return
    }
    let live = true
    setData(undefined)
    extrasFor(property)
      .then((rows) => {
        extrasCache.set(property, rows)
        if (live) setData(rows)
      })
      .catch((e) => live && setError(asApiError(e)))
    return () => {
      live = false
    }
  }, [property])
  return { data, error }
}

export function ExtrasPicker({
  extras,
  value,
  onChange,
  roomLabel,
  idPrefix,
}: {
  extras: ExtraDef[] | undefined
  value: Record<string, number>
  onChange: (code: string, qty: number) => void
  roomLabel: string
  idPrefix: string
}) {
  const { t } = useTexT()
  const L = useLabels()
  if (!extras) return <Skeleton className="h-10 w-full" />
  if (!extras.length) return <p className="text-sm text-zinc-500">{t("crs.extras.none")}</p>
  return (
    <fieldset>
      <legend className="sr-only">{t("crs.extras.for_room", { room: roomLabel })}</legend>
      <ul className="divide-y divide-zinc-100">
        {extras.map((x) => {
          const id = `${idPrefix}-x-${x.extra_code}`
          const qty = value[x.extra_code] ?? 0
          return (
            <li key={x.extra_code} className="flex items-center justify-between gap-3 py-1.5">
              <label htmlFor={id} className="min-w-0 text-sm">
                <span className="block font-medium text-zinc-800">{x.extra_name}</span>
                <span className="block text-xs text-zinc-500">
                  {t("crs.extras.list_price", { amount: money(String(x.amount), x.currency) })} · {L.mode(x.pricing_mode)}
                </span>
              </label>
              {x.is_mandatory ? (
                <Badge>{t("crs.extras.mandatory")}</Badge>
              ) : (
                <NumberStepper
                  id={id}
                  value={qty}
                  min={0}
                  max={x.max_quantity > 0 ? x.max_quantity : 20}
                  decLabel={t("crs.extras.less", { name: x.extra_name })}
                  incLabel={t("crs.extras.more", { name: x.extra_name })}
                  onChange={(v) => onChange(x.extra_code, v)}
                />
              )}
            </li>
          )
        })}
      </ul>
    </fieldset>
  )
}

/** One room of the booking: chosen offer, party, extras and the server quote. */
export function QuoteRoom({
  flow,
  index,
  prop,
  canCost,
  extras,
  showExtras = true,
}: {
  flow: BookingFlow
  index: number
  prop: PropertyResult | undefined
  canCost: boolean
  extras: ExtraDef[] | undefined
  showExtras?: boolean
}) {
  const { t } = useTexT()
  const clock = useServerClock()
  const partyText = usePartyText()
  const offer = flow.selectedOffers[index]
  const party = flow.result?.rooms[index]
  const q = flow.quotes[index]
  const label = t("crs.room_n", { n: index + 1 })
  return (
    <section aria-labelledby={`room-${index}-h`} className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 id={`room-${index}-h`} className="text-sm font-semibold text-zinc-900">
            {label}
            {party ? <span className="font-normal text-zinc-500"> · {partyText(party.adults, party.children.map((c) => c.age))}</span> : null}
          </h3>
          {offer ? <OfferTitle offer={offer} prop={prop} /> : <p className="text-sm text-zinc-500">{t("crs.builder.choose")}</p>}
        </div>
        {q?.ok && q.quote && <Money amount={q.quote.totals.total} currency={q.quote.currency} className="text-base font-semibold" />}
      </div>
      {showExtras && (
        <div>
          <p className="mb-1 text-xs font-semibold tracking-wide text-zinc-500 uppercase">{t("crs.extras.title")}</p>
          <ExtrasPicker
            extras={extras}
            value={flow.extras[index] ?? {}}
            onChange={(code, qty) => flow.setExtra(index, code, qty)}
            roomLabel={label}
            idPrefix={`q${index}`}
          />
        </div>
      )}
      {q && !q.ok && (
        <Notice tone="danger" title={t("crs.quote.not_sellable")}>
          <ul className="list-disc pl-4">
            {(q.reasons ?? []).map((r, i) => (
              <li key={i}>{r.message}</li>
            ))}
          </ul>
        </Notice>
      )}
      {q?.ok && q.quote && (
        <>
          {q.price_changed && (
            <Notice tone="warning" title={t("crs.quote.price_changed")}>
              {t("crs.quote.price_changed_body", {
                old: money(q.previous_total, q.quote.currency),
                now: money(q.quote.totals.total, q.quote.currency),
              })}
            </Notice>
          )}
          <PriceBreakdown quote={q.quote} canCost={canCost} />
          <p className="text-xs text-zinc-500">
            {t("crs.quote.ref", { id: q.quote_id ?? "" })} · {t("crs.quote.valid_until", { time: clock.label(q.expires_at) })}
          </p>
        </>
      )}
    </section>
  )
}

/** Promo codes of the quote, the stale-quote warning and the (re)quote action. */
export function QuoteControls({ flow, shortcut, compact }: { flow: BookingFlow; shortcut?: string; compact?: boolean }) {
  const { t } = useTexT()
  return (
    <div className="space-y-3">
      <div>
        <label htmlFor="crs-quote-promo" className="mb-1.5 block text-sm font-medium text-zinc-800">
          {t("crs.quote.promo")}
        </label>
        <CodeChips id="crs-quote-promo" value={flow.quotePromo} onChange={flow.setQuotePromo} placeholder={t("crs.search.promo_placeholder")} />
      </div>
      {flow.quoteStale && (
        <p className="flex items-center gap-1.5 text-sm text-amber-800" role="status">
          <AlertTriangle className="size-4 shrink-0" aria-hidden />
          {t("crs.quote.stale")}
        </p>
      )}
      {flow.quoteError && (
        <Notice tone="danger" title={t("crs.quote.failed")}>
          <p>{flow.quoteError.message}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => void flow.runSearch(undefined, true)}>
              {t("crs.quote.search_again")}
            </Button>
          </div>
        </Notice>
      )}
      <Button
        onClick={() => void flow.requestQuotes()}
        loading={flow.quoting}
        disabled={!flow.selectionComplete}
        variant={flow.quotesOk && !flow.quoteStale ? "secondary" : "primary"}
        icon={<RefreshCw className="size-4" aria-hidden />}
        shortcut={shortcut}
        className={compact ? "w-full" : undefined}
      >
        {flow.quotes.length ? t("crs.quote.update") : t("crs.quote.get")}
      </Button>
    </div>
  )
}

/**
 * Quote validity on the server clock (bootstrap offset), with a countdown. Expiry is the
 * server's `expires_at`; once past, the agent is asked to re-quote rather than book.
 */
export function QuoteExpiry({ expiresAt, onRequote, className }: { expiresAt?: string | null; onRequote?: () => void; className?: string }) {
  const { t } = useTexT()
  const clock = useServerClock()
  const [, tick] = useState(0)
  useEffect(() => {
    if (!expiresAt) return
    const id = window.setInterval(() => tick((n) => n + 1), 1000)
    return () => window.clearInterval(id)
  }, [expiresAt])
  if (!expiresAt) return null
  const ms = clock.msUntil(expiresAt)
  const until = clock.label(expiresAt)
  if (Number.isNaN(ms)) return <p className={cn("text-xs text-zinc-500", className)}>{t("crs.quote.valid_until", { time: until })}</p>
  if (ms <= 0)
    return (
      <div role="alert" className={cn("flex flex-wrap items-center justify-between gap-2 text-xs font-medium text-rose-700", className)}>
        <span>{t("crs.quote.expired", { time: until })}</span>
        {onRequote && (
          <Button size="sm" variant="secondary" icon={<RefreshCw className="size-4" aria-hidden />} onClick={onRequote}>
            {t("crs.quote.update")}
          </Button>
        )}
      </div>
    )
  return (
    <p className={cn("text-xs", ms < 120_000 ? "font-medium text-amber-800" : "text-zinc-500", className)}>
      {t("crs.quote.valid_until", { time: until })}
      {" · "}
      {/* the ticking figure is not a live region: re-announcing it every second would drown the page */}
      <span className="tabular-nums">{t("crs.quote.time_left", { left: countdown(ms) })}</span>
    </p>
  )
}
