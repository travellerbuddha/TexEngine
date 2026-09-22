import { ArrowLeft, BedDouble, Check, Eye, Maximize2, SearchX, Users } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useI18n } from "../i18n"
import { nightsBetween } from "../lib/dates"
import { isZero } from "../lib/format"
import { boardLabel, cancellation, paymentTerms, reasonText } from "../lib/policy"
import { trackRoomView } from "../lib/track"
import { useBooking } from "../flow/BookingContext"
import { Summary, uniformNight } from "../flow/Summary"
import { useContinue } from "../flow/useContinue"
import { partyText } from "../search/GuestsPicker"
import { useSite } from "../site/SiteContext"
import type { Offer, PropertyResult, RoomContent } from "../types"
import { Badge, Button } from "../ui/controls"
import { Dialog } from "../ui/Dialog"
import { Alert, EmptyState, Skeleton } from "../ui/feedback"
import { Photo } from "../ui/Photo"

function ResultsSkeleton() {
  return (
    <div className="space-y-4" aria-hidden>
      {[0, 1, 2].map((i) => (
        <div key={i} className="bk-card flex flex-col gap-4 p-4 sm:flex-row">
          <Skeleton className="aspect-[16/10] w-full sm:w-64" />
          <div className="flex-1 space-y-3">
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        </div>
      ))}
    </div>
  )
}

function HotelList({ properties }: { properties: PropertyResult[] }) {
  const { t, money } = useI18n()
  const { site } = useSite()
  const { criteria, setCriteria } = useBooking()
  const nights = nightsBetween(criteria.checkIn!, criteria.checkOut!)
  return (
    <section aria-labelledby="bk-hotels-h">
      <h2 id="bk-hotels-h" className="text-xl sm:text-2xl">
        {t("results.chooseHotel")}
      </h2>
      <ul className="mt-4 grid gap-4 md:grid-cols-2">
        {properties.map((p) => {
          const h = site.hotels.find((x) => x.name === p.property)
          const cheapest = p.offers[0]
          const types = new Set(p.offers.map((o) => o.room_type)).size
          return (
            <li key={p.property} className="bk-card flex flex-col overflow-hidden">
              <Photo src={h?.hero_image ?? h?.gallery?.[0]?.url} alt={p.property_name} kind="hotel" className="aspect-[16/9] w-full" />
              <div className="flex flex-1 flex-col p-4">
                <h3 className="text-lg">{p.property_name}</h3>
                {p.city && <p className="text-sm text-muted">{p.city}</p>}
                {h?.showcase_description && <p className="mt-2 line-clamp-2 text-sm text-soft">{h.showcase_description}</p>}
                <div className="mt-auto flex items-end justify-between gap-3 pt-4">
                  {cheapest?.total ? (
                    <div>
                      <p className="text-xs text-muted">{t("results.fromFor", { count: nights })}</p>
                      <p className="text-xl font-bold tabular-nums">{money(cheapest.total, cheapest.currency)}</p>
                      <p className="text-xs text-muted">{t("results.roomTypes", { count: types })}</p>
                    </div>
                  ) : (
                    <p className="text-sm font-medium text-soft">{t("results.hotelUnavailable")}</p>
                  )}
                  <Button
                    variant={cheapest ? "primary" : "secondary"}
                    disabled={!cheapest}
                    onClick={() => setCriteria({ ...criteria, hotel: p.property })}
                    aria-label={t("results.seeRoomsAt", { name: p.property_name })}
                  >
                    {t("results.seeRooms")}
                  </Button>
                </div>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function facts(t: ReturnType<typeof useI18n>["t"], c: RoomContent | undefined) {
  if (!c) return []
  const out: { icon: typeof BedDouble; text: string }[] = []
  if (c.size_sqm && Number(c.size_sqm) > 0) out.push({ icon: Maximize2, text: t("room.size", { size: String(Math.round(Number(c.size_sqm))) }) })
  const beds = c.beds || c.bed_type
  if (beds) out.push({ icon: BedDouble, text: String(beds) })
  if (c.max_adults) out.push({ icon: Users, text: c.max_children ? t("room.sleepsKids", { adults: c.max_adults, children: c.max_children }) : t("room.sleeps", { count: c.max_adults }) })
  if (c.view) out.push({ icon: Eye, text: c.view })
  return out
}

function RoomDetails({ open, onClose, content, name }: { open: boolean; onClose: () => void; content?: RoomContent; name: string }) {
  const { t } = useI18n()
  return (
    <Dialog open={open} onClose={onClose} title={name} closeLabel={t("common.close")} variant="sheet">
      <Photo src={content?.image} alt={name} className="-mx-5 -mt-4 mb-4 aspect-[16/9] w-[calc(100%+2.5rem)] max-w-none" />
      <ul className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-soft">
        {facts(t, content).map((f, i) => (
          <li key={i} className="flex items-center gap-1.5">
            <f.icon className="size-4 text-muted" aria-hidden />
            {f.text}
          </li>
        ))}
      </ul>
      {content?.description && <p className="mt-4 whitespace-pre-line text-sm text-soft">{content.description}</p>}
      {!!content?.amenities?.length && (
        <>
          <h3 className="mt-5 text-sm font-semibold">{t("room.amenities")}</h3>
          <ul className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm text-soft">
            {content.amenities.map((a) => (
              <li key={a} className="flex items-center gap-2">
                <Check className="size-4 text-ok" aria-hidden />
                {a}
              </li>
            ))}
          </ul>
        </>
      )}
    </Dialog>
  )
}

function RateRow({ offer, roomIndex, nights, onSelect, selected, roomName }: { offer: Offer; roomIndex: number; nights: number; onSelect: () => void; selected: boolean; roomName: string }) {
  const i18n = useI18n()
  const { t, money } = i18n
  const { criteria } = useBooking()
  const rq = offer.rooms[roomIndex] ?? offer.rooms[0]
  const q = rq?.quote
  if (!q) return null
  const info = offer.rate_plan_info ?? q.rate_plan
  const cx = cancellation(i18n, info, criteria.checkIn!)
  const pay = paymentTerms(i18n, info, q.currency)
  const night = uniformNight(q)
  // strike-through only with the server's own pre-discount figure, and only when it is comparable to the total
  const strike = !isZero(q.totals.accommodation_discount ?? "0") && q.totals.accommodation === q.totals.total ? q.totals.accommodation_gross : null
  const planName = info?.name ?? offer.rate_plan ?? t("rate.standard")
  return (
    <li className={`rounded-ui border p-3 sm:p-4 ${selected ? "border-brand-ink bg-brand/5 ring-1 ring-brand-ink" : "border-line"}`}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1.5">
          <p className="font-semibold">{planName}</p>
          <ul className="space-y-1 text-sm">
            <li className={`flex items-start gap-1.5 ${cx.refundable && cx.freeUntil ? "text-ok" : "text-soft"}`}>
              <span aria-hidden>{cx.refundable ? "✓" : "•"}</span>
              <span className={cx.refundable && cx.freeUntil ? "font-medium" : ""}>{cx.text}</span>
            </li>
            <li className="flex items-start gap-1.5 text-soft">
              <span aria-hidden>•</span>
              <span>{pay.text}</span>
            </li>
            {pay.payAtHotel && (
              <li className="flex items-start gap-1.5 text-soft">
                <span aria-hidden>•</span>
                <span>{t("policy.payAtHotelPossible")}</span>
              </li>
            )}
            {(info?.inclusions ?? []).map((inc) => (
              <li key={inc} className="flex items-start gap-1.5 text-ok">
                <span aria-hidden>✓</span>
                <span>{inc}</span>
              </li>
            ))}
          </ul>
          {q.promotions?.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-0.5">
              {q.promotions.map((p) => (
                <Badge key={p.promo_id} tone="ok">
                  {p.name}
                </Badge>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-end justify-between gap-3 sm:flex-col sm:items-end sm:text-right">
          <div>
            {strike && (
              <p className="text-sm text-muted">
                <span className="sr-only">{t("rate.was")} </span>
                <s>{money(strike, q.currency)}</s>
              </p>
            )}
            <p className="text-xl font-bold tabular-nums">
              {strike && <span className="sr-only">{t("rate.now")} </span>}
              {money(q.totals.total, q.currency)}
            </p>
            <p className="text-xs text-muted">
              {t("rate.forNights", { count: nights })}
              {night && <> · {t("rate.perNight", { amount: money(night, q.currency) })}</>}
            </p>
            {!isZero(q.totals.tax_added ?? "0") && <p className="text-xs text-muted">{t("rate.inclTaxes")}</p>}
            {!night && q.nights.length > 1 && <NightlyPrices nights={q.nights} currency={q.currency} />}
          </div>
          <Button
            variant={selected ? "secondary" : "primary"}
            onClick={onSelect}
            aria-pressed={selected}
            aria-label={`${selected ? t("rate.selected") : t("rate.select")}: ${roomName}, ${planName}, ${boardLabel(t, offer.board)}, ${money(q.totals.total, q.currency)}`}
            className="min-w-28"
          >
            {selected && <Check className="size-4" aria-hidden />}
            {selected ? t("rate.selected") : t("rate.select")}
          </Button>
        </div>
      </div>
    </li>
  )
}

function NightlyPrices({ nights, currency }: { nights: { date: string; amount: string }[]; currency: string }) {
  const { t, money, day } = useI18n()
  return (
    <details className="mt-1 text-xs text-muted">
      <summary className="cursor-pointer text-brand-ink">{t("rate.nightly")}</summary>
      <ul className="mt-1 space-y-0.5 text-left">
        {nights.map((n) => (
          <li key={n.date} className="flex justify-between gap-4">
            <span>{day(n.date)}</span>
            <span className="tabular-nums">{money(n.amount, currency)}</span>
          </li>
        ))}
      </ul>
    </details>
  )
}

function RoomCard({ property, roomType, offers }: { property: PropertyResult; roomType: string; offers: Offer[] }) {
  const { t } = useI18n()
  const { site } = useSite()
  const { criteria, activeRoom, select, flow } = useBooking()
  const content = property.rooms[roomType]
  const name = content?.name ?? roomType
  const boards = useMemo(() => [...new Set(offers.map((o) => o.board))], [offers])
  const [board, setBoard] = useState(boards[0])
  const [details, setDetails] = useState(false)
  const nights = nightsBetween(criteria.checkIn!, criteria.checkOut!)
  const current = boards.includes(board) ? board : boards[0]
  const rates = offers.filter((o) => o.board === current)
  const available = Math.min(...offers.map((o) => o.available))
  const f = facts(t, content)
  const sel = flow.selections[activeRoom]
  const boardGroup = `board-${roomType}`
  return (
    <li className="bk-card overflow-hidden">
      <div className="flex flex-col md:flex-row">
        <div className="relative md:w-72 md:flex-none">
          <Photo src={content?.image} alt={name} className="aspect-[16/9] w-full md:aspect-auto md:h-full md:min-h-56" />
          {available <= 3 && (
            <span className="absolute left-3 top-3 rounded-full bg-surface/95 px-2.5 py-1 text-xs font-semibold text-warn shadow-card">
              {t("room.onlyLeft", { count: available })}
            </span>
          )}
        </div>
        <div className="min-w-0 flex-1 p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <h3 className="text-lg sm:text-xl">{name}</h3>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setDetails(true)
                trackRoomView(site.slug, { hotel: property.property, room_type: roomType })
              }}
            >
              {t("room.details")}
            </Button>
          </div>
          {f.length > 0 && (
            <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-soft">
              {f.map((x, i) => (
                <li key={i} className="flex items-center gap-1.5">
                  <x.icon className="size-4 text-muted" aria-hidden />
                  {x.text}
                </li>
              ))}
            </ul>
          )}
          {!!content?.amenities?.length && (
            <ul className="mt-2 flex flex-wrap gap-1.5" aria-label={t("room.amenities")}>
              {content.amenities.slice(0, 5).map((a) => (
                <li key={a} className="rounded-full bg-sunken px-2.5 py-0.5 text-xs text-soft">
                  {a}
                </li>
              ))}
              {content.amenities.length > 5 && <li className="px-1 text-xs text-muted">{t("room.more", { count: content.amenities.length - 5 })}</li>}
            </ul>
          )}
          {boards.length > 1 && (
            <fieldset className="mt-4">
              <legend className="mb-1.5 text-sm font-medium text-soft">{t("room.mealPlan")}</legend>
              <div className="flex flex-wrap gap-2">
                {boards.map((b) => (
                  <label
                    key={b}
                    className={`inline-flex min-h-10 cursor-pointer items-center rounded-full border px-3.5 text-sm font-medium has-[:focus-visible]:outline-3 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-brand-ink ${b === current ? "border-brand-ink bg-brand text-on-brand" : "border-line-strong bg-surface text-soft hover:border-ink"}`}
                  >
                    <input type="radio" className="sr-only" name={boardGroup} value={b} checked={b === current} onChange={() => setBoard(b)} />
                    {boardLabel(t, b)}
                  </label>
                ))}
              </div>
            </fieldset>
          )}
          {boards.length === 1 && <p className="mt-3 text-sm font-medium text-soft">{boardLabel(t, current)}</p>}
          <ul className="mt-3 space-y-2" aria-label={t("room.ratesFor", { name })}>
            {rates.map((o) => {
              const rq = o.rooms[activeRoom] ?? o.rooms[0]
              return (
                <RateRow
                  key={`${o.rate_plan}-${o.board}`}
                  offer={o}
                  roomIndex={activeRoom}
                  nights={nights}
                  roomName={name}
                  selected={!!sel && sel.offerKey === rq?.offer_key}
                  onSelect={() => {
                    select(activeRoom, o, property.property, name)
                    trackRoomView(site.slug, { hotel: property.property, room_type: roomType, board: o.board, rate_plan: o.rate_plan })
                  }}
                />
              )
            })}
          </ul>
        </div>
      </div>
      <RoomDetails open={details} onClose={() => setDetails(false)} content={content} name={name} />
    </li>
  )
}

function RoomTabs() {
  const { t } = useI18n()
  const { criteria, activeRoom, setActiveRoom, flow } = useBooking()
  if (criteria.rooms.length < 2) return null
  return (
    <nav aria-label={t("results.roomTabs")} className="-mx-4 overflow-x-auto px-4 pb-1">
      <ol className="flex gap-2">
        {criteria.rooms.map((r, i) => {
          const sel = flow.selections[i]
          const active = i === activeRoom
          return (
            <li key={i} className="flex-none">
              <button
                type="button"
                onClick={() => setActiveRoom(i)}
                aria-current={active ? "step" : undefined}
                className={`min-h-14 rounded-ui border px-3.5 py-2 text-left text-sm ${active ? "border-brand-ink bg-surface ring-2 ring-brand-ink" : "border-line bg-surface hover:border-line-strong"}`}
              >
                <span className="flex items-center gap-1.5 font-semibold">
                  {sel && <Check className="size-4 text-ok" aria-hidden />}
                  {t("guests.room", { n: i + 1 })}
                  <span className="sr-only">{sel ? `, ${t("results.chosen", { name: sel.roomName })}` : `, ${t("summary.notSelected")}`}</span>
                </span>
                <span className="block text-xs text-muted">{sel ? sel.roomName : partyText(t, r)}</span>
              </button>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

function RoomList({ property }: { property: PropertyResult }) {
  const { t } = useI18n()
  const { site } = useSite()
  const { criteria, setCriteria, activeRoom } = useBooking()
  const [freeOnly, setFreeOnly] = useState(false)
  const groups = useMemo(() => {
    const m = new Map<string, Offer[]>()
    for (const o of property.offers) {
      if (freeOnly && o.refundable === false) continue
      m.set(o.room_type, [...(m.get(o.room_type) ?? []), o])
    }
    return [...m.entries()]
  }, [property, freeOnly])
  const unavailable = useMemo(() => {
    const avail = new Set(property.offers.map((o) => o.room_type))
    const m = new Map<string, Offer>()
    for (const o of property.unavailable) if (!avail.has(o.room_type) && !m.has(o.room_type)) m.set(o.room_type, o)
    return [...m.values()]
  }, [property])
  const multi = criteria.rooms.length > 1
  const heading = useRef<HTMLHeadingElement>(null)
  const firstRender = useRef(true)
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false
      return
    }
    heading.current?.focus()
  }, [activeRoom])
  const hasRefundable = property.offers.some((o) => o.refundable)
  return (
    <section aria-labelledby="bk-rooms-h" className="space-y-4">
      {site.group && site.hotels.length > 1 && (
        <Button variant="ghost" size="sm" onClick={() => setCriteria({ ...criteria, hotel: null })} className="-ml-3">
          <ArrowLeft className="size-4" aria-hidden />
          {t("results.allHotels")}
        </Button>
      )}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="bk-rooms-h" ref={heading} tabIndex={-1} className="text-xl outline-none sm:text-2xl">
            {multi ? t("results.chooseForRoom", { n: activeRoom + 1 }) : t("results.chooseRoom")}
          </h2>
          <p className="text-sm text-muted">
            {multi ? partyText(t, criteria.rooms[activeRoom]) + " · " : ""}
            {t("results.count", { count: groups.length })}
          </p>
        </div>
        {hasRefundable && (
          <button
            type="button"
            aria-pressed={freeOnly}
            onClick={() => setFreeOnly((v) => !v)}
            className={`inline-flex min-h-10 items-center gap-1.5 rounded-full border px-3.5 text-sm font-medium ${freeOnly ? "border-brand-ink bg-brand text-on-brand" : "border-line-strong bg-surface text-soft hover:border-ink"}`}
          >
            {freeOnly && <Check className="size-4" aria-hidden />}
            {t("results.freeCancellationOnly")}
          </button>
        )}
      </div>
      <RoomTabs />
      {groups.length ? (
        <ul className="space-y-4">
          {groups.map(([rt, offers]) => (
            <RoomCard key={rt} property={property} roomType={rt} offers={offers} />
          ))}
        </ul>
      ) : (
        <EmptyState icon={<SearchX className="size-8" aria-hidden />} title={property.offers.length ? t("results.noMatchFilter") : t("results.noneTitle")}>
          {property.offers.length ? null : t(multi ? "results.noneBodyMulti" : "results.noneBody")}
        </EmptyState>
      )}
      {unavailable.length > 0 && (
        <div className="pt-4">
          <h3 className="text-base font-semibold text-soft">{t("results.unavailableTitle")}</h3>
          <ul className="mt-2 divide-y divide-line rounded-card border border-line bg-surface">
            {unavailable.map((o) => (
              <li key={o.room_type} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
                <span className="font-medium text-soft">{property.rooms[o.room_type]?.name ?? o.room_type}</span>
                <span className="text-muted">{reasonText(t, o.reasons, multi)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

function ContinueAction() {
  const { t } = useI18n()
  const { allSelected, criteria, flow, activeRoom, setActiveRoom } = useBooking()
  const { go, busy } = useContinue()
  if (!allSelected && criteria.rooms.length > 1 && flow.selections[activeRoom]) {
    const next = criteria.rooms.findIndex((_, i) => !flow.selections[i])
    return (
      <Button onClick={() => setActiveRoom(next)} block>
        {t("results.nextRoom", { n: next + 1 })}
      </Button>
    )
  }
  return (
    <Button onClick={() => void go("rooms")} disabled={!allSelected} busy={busy} block>
      {t("common.continue")}
    </Button>
  )
}

export default function Results() {
  const { t, money } = useI18n()
  const { site } = useSite()
  const { search, criteria, runSearch, flow, allSelected } = useBooking()
  const { error, errorView } = useContinue()
  const data = search.data
  const loading = search.status === "loading"
  const statusText = loading ? t("results.searching") : data ? t("results.updated") : ""

  let body
  if (search.status === "error") {
    body = (
      <Alert
        tone="bad"
        title={search.error?.kind === "rate_limit" ? t("errors.rateLimitTitle") : t("results.errorTitle")}
        actions={<Button onClick={() => void runSearch({ force: true })}>{t("common.retry")}</Button>}
      >
        {search.error?.message || t("errors.network")}
      </Alert>
    )
  } else if (!data) {
    body = <ResultsSkeleton />
  } else {
    const hotel = site.group ? criteria.hotel : data.properties[0]?.property
    const prop = hotel ? data.properties.find((p) => p.property === hotel) : null
    if (site.group && site.hotels.length > 1 && !hotel) body = <HotelList properties={data.properties} />
    else if (prop) body = <RoomList property={prop} />
    else
      body = (
        <EmptyState icon={<SearchX className="size-8" aria-hidden />} title={t("results.noneTitle")}>
          {t("results.noneBody")}
        </EmptyState>
      )
  }

  const showSummary = !!data && (!site.group || !!criteria.hotel || site.hotels.length === 1)
  const sel0 = flow.selections[0]
  const n = criteria.rooms.length
  const chosen = flow.selections.filter(Boolean).length
  const compact =
    n === 1 && sel0 ? money(sel0.quote.totals.total, sel0.quote.currency) : n > 1 ? t("results.progress", { done: chosen, count: n }) : t("summary.notSelected")

  return (
    <div className={`grid gap-6 ${showSummary ? "lg:grid-cols-[minmax(0,1fr)_340px]" : ""}`}>
      <div className={`min-w-0 space-y-4 ${showSummary ? "pb-24 lg:pb-0" : ""}`} aria-busy={loading || undefined}>
        <p className="sr-only" role="status" aria-live="polite">
          {statusText}
        </p>
        {error && errorView}
        {loading && data && <p className="text-sm text-muted">{t("results.searching")}</p>}
        {body}
      </div>
      {showSummary && <Summary action={<ContinueAction />} compactLabel={allSelected || chosen ? compact : t("summary.notSelected")} />}
    </div>
  )
}
