import { useEffect, useMemo, useState, type ReactNode } from "react"
import { cn } from "../../../../lib/utils"
import { clock as countdown, useServerClock } from "../lib/serverClock"
import { AlertTriangle, RefreshCw } from "lucide-react"
import { money } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, Money, Notice, Select, Skeleton } from "../../../ui"
import { extrasFor } from "../lib/api"
import {
  dayStock,
  extraReasonText,
  isNightlyMode,
  isServiceDateMode,
  shortDay,
  stayDays,
  takenByOtherRooms,
  tightest,
  unitsPerQuantity,
  usageDays,
  type DayStock,
  type ExtraChoice,
  type ExtrasAvailability,
  type Heads,
  type StayDates,
} from "../lib/extrasStock"
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

/** Extras a room of the booking can take: a per-booking extra is charged once, on room 1 (ADR-029). */
export function roomExtras(extras: ExtraDef[] | undefined, index: number): ExtraDef[] | undefined {
  return index === 0 ? extras : extras?.filter((x) => x.pricing_mode !== "RESERVATION")
}

/** What the extras picker knows about the stay and the limited extras (G-19). */
export interface ExtrasStockProps {
  /** The stay: SERVICE_DATE extras choose their day(s) in it, the others may name one day. */
  stay?: StayDates
  /** crs.extras_availability for the stay (limited extras only); omitted = no capacity shown. */
  stock?: ExtrasAvailability
  /** The availability could not be loaded (the quote still checks it). */
  stockFailed?: boolean
  /** Units of limited extras the other rooms of the booking already take, by code and day. */
  taken?: Record<string, Record<string, number>>
  /** Guests of the room: per-person extras take one unit per guest. */
  heads?: Heads
}

/** Stay, capacity and the other rooms' use of limited extras, for room `index` of the booking. */
export function roomStock(flow: BookingFlow, index: number, defs: ExtraDef[] | undefined): ExtrasStockProps {
  const r = flow.result
  if (!r) return {}
  const stay = { check_in: r.check_in, check_out: r.check_out }
  const headsOf = (i: number): Heads | undefined => {
    const p = r.rooms[i]
    return p ? { adults: p.adults, children: p.children.length } : undefined
  }
  const modes = new Map((defs ?? []).map((x) => [x.extra_code, x.pricing_mode]))
  return {
    stay,
    stock: flow.extrasStock,
    stockFailed: Boolean(flow.extrasStockError && !flow.extrasStock),
    heads: headsOf(index),
    taken: takenByOtherRooms(modes, flow.extrasStock, flow.extras, index, stay, headsOf),
  }
}

export function ExtrasPicker({
  extras,
  value,
  onChange,
  roomLabel,
  idPrefix,
  stockFailed,
  ...stockProps
}: {
  extras: ExtraDef[] | undefined
  value: Record<string, ExtraChoice>
  /** null (or quantity 0) removes the extra. */
  onChange: (code: string, choice: ExtraChoice | null) => void
  roomLabel: string
  idPrefix: string
} & ExtrasStockProps) {
  const { t } = useTexT()
  if (!extras) return <Skeleton className="h-10 w-full" />
  if (!extras.length) return <p className="text-sm text-zinc-500">{t("crs.extras.none")}</p>
  return (
    <fieldset>
      <legend className="sr-only">{t("crs.extras.for_room", { room: roomLabel })}</legend>
      {stockFailed && <p className="mb-1 text-xs text-amber-800">{t("crs.extras.stock_failed")}</p>}
      <ul className="divide-y divide-zinc-100">
        {extras.map((x) => (
          <ExtraRow
            key={x.extra_code}
            x={x}
            choice={value[x.extra_code]}
            onChange={(c) => onChange(x.extra_code, c)}
            id={`${idPrefix}-x-${x.extra_code}`}
            {...stockProps}
          />
        ))}
      </ul>
    </fieldset>
  )
}

/** One extra: quantity, its day(s) of the stay and, for a limited extra, what is left. */
function ExtraRow({
  x,
  choice,
  onChange,
  id,
  stay,
  stock,
  taken,
  heads,
}: {
  x: ExtraDef
  choice: ExtraChoice | undefined
  onChange: (c: ExtraChoice | null) => void
  id: string
} & Omit<ExtrasStockProps, "stockFailed">) {
  const { t } = useTexT()
  const L = useLabels()
  // the day a one-day extra would use, picked before adding it (e.g. arrival is sold out)
  const [pickedDay, setPendingDay] = useState("")
  const code = x.extra_code
  const mode = x.pricing_mode
  const qty = choice?.quantity ?? 0
  const dates = useMemo(() => choice?.service_dates ?? [], [choice])
  const serviceDate = isServiceDateMode(mode)
  const oneDay = !serviceDate && !isNightlyMode(mode)
  const ci = stay?.check_in
  const co = stay?.check_out
  const days = useMemo(() => (ci && co ? stayDays({ check_in: ci, check_out: co }) : []), [ci, co])
  // a day picked for another stay (a new search) no longer counts
  const pendingDay = days.includes(pickedDay) ? pickedDay : ""
  const limited = Boolean(stay && stock?.[code])
  const perQty = unitsPerQuantity(mode, heads)
  const hardMax = x.max_quantity > 0 ? x.max_quantity : 20
  const dayValue = qty > 0 ? (dates[0] ?? "") : pendingDay
  const pendingDays = oneDay && pendingDay ? [pendingDay] : []
  const used = stay ? usageDays(mode, { service_dates: qty > 0 ? dates : pendingDays }, stay) : []
  const worst = limited ? tightest(stock, code, used, taken) : null
  // the most that can still be added on the days it would use (per-person: per guest)
  const fits = (left: number) => (left <= 0 ? 0 : perQty ? Math.floor(left / perQty) : hardMax)
  let cap = hardMax
  if (worst) cap = Math.min(hardMax, worst.closed ? 0 : fits(worst.left))
  else if (limited && serviceDate && !used.length) {
    // no day chosen yet: as many as the best day of the stay allows
    const best = days.map((d) => dayStock(stock, code, d, taken)).filter((s): s is DayStock => Boolean(s && !s.unknown && !s.closed))
    cap = Math.min(hardMax, Math.max(0, ...best.map((s) => fits(s.left))))
  }
  cap = Math.max(cap, 0)
  const need = Math.max(qty, 1) * (perQty ?? 1)
  const blocked = (s: DayStock | null) => Boolean(s && !s.unknown && (s.closed || s.left < need))
  const dayNote = (s: DayStock | null) =>
    !s || s.unknown ? "" : s.closed ? t("crs.extras.day_closed") : s.left <= 0 ? t("crs.extras.day_sold_out") : t("crs.extras.day_left", { count: s.left })
  const stockId = `${id}-stock`

  let stockLine: ReactNode = null
  if (worst) {
    const day = shortDay(worst.day)
    stockLine = worst.closed ? (
      <Badge tone="danger">{t("crs.extras.closed_on", { date: day })}</Badge>
    ) : worst.left <= 0 ? (
      <Badge tone="danger">{t("crs.extras.sold_out_on", { date: day })}</Badge>
    ) : (
      <span className={cn("text-xs", worst.left <= 3 || cap < Math.max(qty, 1) ? "font-medium text-amber-800" : "text-zinc-600")}>
        {t("crs.extras.left_on", { count: worst.left, date: day })}
        {cap === 0 && perQty ? ` · ${t("crs.extras.not_enough", { count: perQty })}` : ""}
      </span>
    )
  }

  const setQty = (v: number) => {
    if (v <= 0) {
      if (oneDay && dates[0]) setPendingDay(dates[0])
      onChange(null)
      return
    }
    onChange({ quantity: v, service_dates: qty > 0 ? dates : serviceDate ? [] : pendingDays })
  }
  const setDay = (v: string) => {
    if (qty > 0) onChange({ quantity: qty, service_dates: v ? [v] : [] })
    else setPendingDay(v)
  }
  const toggleDate = (d: string, on: boolean) => {
    const next = on ? [...new Set([...dates, d])].sort() : dates.filter((x) => x !== d)
    onChange(next.length ? { quantity: Math.max(qty, 1), service_dates: next } : null)
  }

  const dayOptions = ci
    ? [
        { value: "", label: `${t("crs.extras.day_arrival", { date: shortDay(ci) })}${suffix(dayNote(limited ? dayStock(stock, code, ci, taken) : null))}` },
        ...days
          .filter((d) => d !== ci || dayValue === ci)
          .map((d) => {
            const s = limited ? dayStock(stock, code, d, taken) : null
            return { value: d, label: `${shortDay(d)}${suffix(dayNote(s))}`, disabled: blocked(s) && d !== dayValue }
          }),
      ]
    : []

  return (
    <li className="space-y-1.5 py-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 text-sm">
          <label htmlFor={id} className="block font-medium text-zinc-800">
            {x.extra_name}
          </label>
          <span className="block text-xs text-zinc-500">
            {t("crs.extras.list_price", { amount: money(String(x.amount), x.currency) })} · {L.mode(mode)}
          </span>
          {stockLine && (
            <span id={stockId} className="mt-0.5 block">
              {stockLine}
            </span>
          )}
        </div>
        {x.is_mandatory ? (
          <Badge>{t("crs.extras.mandatory")}</Badge>
        ) : (
          <NumberStepper
            id={id}
            className="shrink-0"
            value={qty}
            min={0}
            max={cap}
            disabled={qty === 0 && cap === 0}
            aria-describedby={stockLine ? stockId : undefined}
            decLabel={t("crs.extras.less", { name: x.extra_name })}
            incLabel={t("crs.extras.more", { name: x.extra_name })}
            onChange={setQty}
          />
        )}
      </div>
      {!x.is_mandatory && stay && serviceDate && days.length > 0 && (
        <fieldset>
          <legend className="mb-1 text-xs text-zinc-600">
            {t("crs.extras.days")}
            <span className="sr-only"> · {x.extra_name}</span>
          </legend>
          <div className="flex flex-wrap gap-1.5">
            {days.map((d) => {
              const on = dates.includes(d)
              const s = limited ? dayStock(stock, code, d, taken) : null
              const off = blocked(s)
              const note = dayNote(s)
              return (
                <label
                  key={d}
                  className={cn(
                    "inline-flex min-h-8 items-center gap-1.5 rounded-full border px-2.5 text-xs",
                    on
                      ? off
                        ? "border-rose-300 bg-rose-50 font-medium text-rose-900"
                        : "border-tex-500 bg-tex-50 font-medium text-tex-900"
                      : "border-zinc-300 text-zinc-700 hover:border-zinc-400",
                    off && !on ? "cursor-not-allowed opacity-50" : "cursor-pointer",
                  )}
                >
                  <input
                    type="checkbox"
                    className="size-3.5 accent-tex-600"
                    checked={on}
                    disabled={off && !on}
                    onChange={(e) => toggleDate(d, e.target.checked)}
                  />
                  {shortDay(d)}
                  {note && <span className={cn(off ? "text-rose-700" : "text-zinc-500")}>· {note}</span>}
                </label>
              )
            })}
          </div>
          {qty > 0 && !dates.length && <p className="mt-1 text-xs font-medium text-amber-800">{t("crs.extras.choose_days")}</p>}
        </fieldset>
      )}
      {!x.is_mandatory && stay && oneDay && (qty > 0 || limited) && dayOptions.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <label htmlFor={`${id}-day`} className="text-xs text-zinc-600">
            {t("crs.extras.day")}
            <span className="sr-only"> · {x.extra_name}</span>
          </label>
          <div className="min-w-0 flex-1 sm:max-w-64">
            <Select id={`${id}-day`} value={dayValue} onChange={(e) => setDay(e.target.value)} options={dayOptions} />
          </div>
        </div>
      )}
    </li>
  )
}

function suffix(note: string) {
  return note ? ` · ${note}` : ""
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
            extras={roomExtras(extras, index)}
            value={flow.extras[index] ?? {}}
            onChange={(code, c) => flow.setExtra(index, code, c)}
            roomLabel={label}
            idPrefix={`q${index}`}
            {...roomStock(flow, index, extras)}
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

/**
 * The booking was refused because a limited extra (a spa slot…) sold out since the quote — not
 * a room sell-out (G-19). Nothing was booked; the flow has quoted the rooms again, so the
 * refused extras are listed here as not added (and not charged). When no room's quote refuses
 * one, each room alone still fits but the rooms together need more than is left.
 */
export function ExtraSoldOutNotice({ flow, onReviewQuote }: { flow: BookingFlow; onReviewQuote?: () => void }) {
  const { t } = useTexT()
  if (!flow.bookError || !flow.extraSoldOut) return null
  const many = flow.quotes.length > 1
  const refused = flow.quotes.flatMap((q, i) => (q.quote?.extras ?? []).filter((x) => !x.ok).map((x) => ({ room: i, x })))
  return (
    <Notice tone="warning" title={t("crs.book.extra_sold_out")}>
      <p>{flow.bookError.message}</p>
      {refused.length > 0 && (
        <ul className="mt-1 list-disc pl-4 font-medium">
          {refused.map(({ room, x }, k) => (
            <li key={k}>
              {many ? `${t("crs.room_n", { n: room + 1 })}: ` : ""}
              {t("crs.quote.extra_failed", { name: x.name || x.code, reason: extraReasonText(t, x.reason) })}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-1 text-xs">{t(flow.extrasTogether ? "crs.book.extra_sold_out_together" : "crs.book.extra_sold_out_hint")}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {onReviewQuote && (
          <Button size="sm" variant="secondary" onClick={onReviewQuote}>
            {t("crs.book.review_quote")}
          </Button>
        )}
        <Button size="sm" variant={onReviewQuote ? "ghost" : "secondary"} onClick={() => void flow.requestQuotes()} loading={flow.quoting}>
          {t("crs.book.requote")}
        </Button>
      </div>
    </Notice>
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
