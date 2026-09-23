import { useMemo, useState } from "react"
import { Check, Hotel } from "lucide-react"
import { date, money } from "../../../lib/format"
import { useSession } from "../../../lib/session"
import { useTexT } from "../../../i18n"
import { Badge, Button, Card, CardHeader, Checkbox, EmptyState, Field, Notice, Select } from "../../../ui"
import { cn } from "../../../../lib/utils"
import { useLabels } from "../lib/labels"
import { BOARDS, cmpDecimal, offerId } from "../lib/party"
import type { BookingFlow } from "../lib/useBookingFlow"
import type { Offer, PropertyResult } from "../lib/types"
import { Disclosure } from "./controls"
import { assignableRooms, AvailabilityBadge, OfferBadges, OfferDetails, OfferPrice, OfferTitle, ratePlanName, RoomFitNotes, roomName } from "./OfferParts"
import { roomList } from "../lib/selectText"
import { usePartyText } from "./PartyEditor"

/** CRS results grouped by hotel (R-24). Unsellable offers keep their restriction messages. */
export function Results({ flow, onSelect }: { flow: BookingFlow; onSelect: (prop: string, offer: Offer) => void }) {
  const { t } = useTexT()
  const L = useLabels()
  const { can } = useSession()
  const [board, setBoard] = useState("")
  const [refundableOnly, setRefundableOnly] = useState(false)
  const r = flow.result
  const boards = useMemo(() => {
    const seen = new Set<string>()
    r?.properties.forEach((p) => p.offers.forEach((o) => seen.add(o.board)))
    return [...BOARDS.filter((b) => seen.has(b)), ...[...seen].filter((b) => !(BOARDS as readonly string[]).includes(b))]
  }, [r])
  if (!r) return null
  const total = r.properties.reduce((n, p) => n + p.offers.length, 0)
  const keep = (o: Offer) => (!board || o.board === board) && (!refundableOnly || (o.refundable ?? o.rate_plan_info?.refundable))
  return (
    <section aria-labelledby="crs-results-h" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="crs-results-h" className="text-base font-semibold text-zinc-950">
            {t("crs.results.title")}
          </h2>
          <p className="text-sm text-zinc-600">
            {t("crs.results.offer_count", { count: total })} ·{" "}
            {t("crs.results.summary", {
              from: date(r.check_in),
              to: date(r.check_out),
              nights: t("core.label.nights", { count: r.nights }),
              market: r.market,
            })}
          </p>
        </div>
        {total > 0 && (
          <div className="flex flex-wrap items-end gap-3">
            <Field label={t("crs.results.board_filter")}>
              <Select
                id="crs-filter-board"
                className="w-44"
                value={board}
                onChange={(e) => setBoard(e.target.value)}
                options={[{ value: "", label: t("core.label.all") }, ...boards.map((b) => ({ value: b, label: L.board(b) }))]}
              />
            </Field>
            <Checkbox className="h-9" label={t("crs.results.refundable_only")} checked={refundableOnly} onChange={(e) => setRefundableOnly(e.target.checked)} />
          </div>
        )}
      </div>
      {r.properties.length === 0 && (
        <Card>
          <EmptyState title={t("crs.results.none")} />
        </Card>
      )}
      {r.properties.map((p) => (
        <HotelResults
          key={p.property}
          p={p}
          flow={flow}
          offers={p.offers.filter(keep)}
          canCreate={can("reservation.create", p.property)}
          canCost={can("price.view_cost", p.property)}
          onSelect={onSelect}
        />
      ))}
    </section>
  )
}

function HotelResults({
  p,
  flow,
  offers,
  canCreate,
  canCost,
  onSelect,
}: {
  p: PropertyResult
  flow: BookingFlow
  offers: Offer[]
  canCreate: boolean
  canCost: boolean
  onSelect: (prop: string, offer: Offer) => void
}) {
  const { t } = useTexT()
  const r = flow.result!
  const rooms = r.rooms.length
  const L = useLabels()
  const selectedHere = flow.selection?.property === p.property
  const unplaced = p.unplaced_rooms ?? []
  const selectLabel = (o: Offer) => {
    if (rooms <= 1) return t("crs.results.select")
    const can = assignableRooms(o)
    if (can.length === rooms) return t("crs.results.select_all")
    return t("crs.results.select_rooms", { count: can.length, rooms: roomList(can) })
  }
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Hotel className="size-4 text-zinc-400" aria-hidden />
            {p.property_name || p.property}
          </span>
        }
        description={[
          p.city,
          t("crs.results.offer_count", { count: p.offers.length }),
          // the cheapest way to place every room (room types may differ)
          p.from_total
            ? rooms > 1
              ? t("crs.results.from_all", { amount: money(p.from_total, p.from_currency ?? p.offers[0]?.currency) })
              : t("crs.results.from", { amount: money(p.from_total, p.from_currency ?? p.offers[0]?.currency) })
            : null,
        ]
          .filter(Boolean)
          .join(" · ")}
        actions={selectedHere ? <Badge tone="brand">{t("crs.results.selected_hotel")}</Badge> : undefined}
      />
      {/* the server appends its own (English) "fits nowhere" line last; ours is translated */}
      {(unplaced.length ? p.messages.slice(0, -1) : p.messages).map((m, i) => (
        <div key={i} className="px-4 pt-3">
          <Notice tone="warning">{m}</Notice>
        </div>
      ))}
      {unplaced.length > 0 && (
        <div className="px-4 pt-3">
          <Notice tone="warning" title={t("crs.results.unplaced", { count: unplaced.length, rooms: roomList(unplaced) })}>
            {t("crs.results.unplaced_hint", { count: unplaced.length, rooms: roomList(unplaced) })}
          </Notice>
        </div>
      )}
      {!canCreate && p.offers.length > 0 && (
        <div className="px-4 pt-3">
          <Notice tone="info">{t("crs.results.view_only")}</Notice>
        </div>
      )}
      {offers.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-zinc-500">{p.offers.length ? t("crs.results.filtered_out") : t("crs.results.none_here")}</p>
      ) : (
        <ul className="divide-y divide-zinc-200">
          {groupByRoom(offers).map(([roomType, group]) => {
            const content = p.rooms?.[roomType]
            return (
              <li key={roomType} aria-labelledby={`rt-${cssKey(p.property)}-${cssKey(roomType)}`}>
                <div className="flex flex-wrap items-center justify-between gap-2 bg-zinc-50/70 px-4 py-2">
                  <h3 id={`rt-${cssKey(p.property)}-${cssKey(roomType)}`} className="text-sm font-semibold text-zinc-900">
                    {roomName(p, roomType)}
                    {content?.max_adults ? (
                      <span className="ml-2 text-xs font-normal text-zinc-500">
                        {t("crs.offer.max_adults", { count: content.max_adults })}
                        {content.max_children ? ` · ${t("crs.offer.max_children", { count: content.max_children })}` : ""}
                      </span>
                    ) : null}
                  </h3>
                  <AvailabilityBadge available={group[0].available} needed={group[0].room_indexes?.length ?? rooms} />
                </div>
                <ul className="divide-y divide-zinc-100">
                  {group.map((o) => {
                    const id = offerId(o)
                    const picked = selectedHere && flow.selection!.picks.includes(id)
                    const plan = ratePlanName({ ...o, property: p.property })
                    return (
                      <li key={id} className={cn("grid gap-2 px-4 py-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start", picked && "bg-tex-50/60")}>
                        <div className="min-w-0 space-y-1">
                          <p className="text-sm text-zinc-900">
                            <span className="font-medium">{L.board(o.board)}</span>
                            {plan ? <span className="text-zinc-600"> · {plan}</span> : null}
                          </p>
                          <OfferBadges offer={o} rooms={rooms} showAvailability={false} />
                          {rooms > 1 && o.complete && (
                            <p className="text-xs text-zinc-500">
                              {o.rooms.map((x) => `${t("crs.room_n", { n: x.room_index + 1 })} ${money(x.quote.totals.total, x.quote.currency)}`).join(" · ")}
                            </p>
                          )}
                          {rooms > 1 && <RoomFitNotes offer={o} />}
                          <Disclosure summary={t("crs.results.details")}>
                            <OfferDetails offer={o} prop={p} parties={r.rooms} canCost={canCost} />
                          </Disclosure>
                        </div>
                        <div className="flex items-center justify-between gap-4 sm:justify-end">
                          <OfferPrice offer={o} nights={r.nights} rooms={rooms} />
                          {canCreate && (
                            <Button
                              size="sm"
                              className="min-w-24"
                              variant={picked ? "secondary" : "primary"}
                              icon={picked ? <Check className="size-4" aria-hidden /> : undefined}
                              onClick={() => onSelect(p.property, o)}
                              aria-label={t("crs.results.select_aria", { room: roomName(p, o.room_type), board: L.board(o.board), plan: plan ?? "" })}
                            >
                              {picked ? t("crs.results.selected") : selectLabel(o)}
                            </Button>
                          )}
                        </div>
                      </li>
                    )
                  })}
                </ul>
              </li>
            )
          })}
        </ul>
      )}
      {p.unavailable.length > 0 && (
        <div className="border-t border-zinc-100 px-4 py-3">
          <Disclosure summary={t("crs.results.unavailable", { count: p.unavailable.length })}>
            <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
              {p.unavailable.map((o) => (
                <li key={offerId(o)} className="flex flex-col gap-1 px-3 py-2 sm:flex-row sm:items-start sm:justify-between">
                  <OfferTitle offer={o} prop={p} />
                  <ul className="text-sm text-rose-800 sm:max-w-[55%] sm:text-right">
                    {(o.reasons ?? o.restrictions).map((x, i) => (
                      <li key={i}>
                        <Badge tone="danger" className="mr-1">
                          {x.code}
                        </Badge>
                        {x.message}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
            {rooms > 1 && <p className="mt-1 text-xs text-zinc-500">{t("crs.results.unavailable_multi")}</p>}
          </Disclosure>
        </div>
      )}
    </Card>
  )
}

function groupByRoom(offers: Offer[]): [string, Offer[]][] {
  // the server sorts offers by total: the first offer of each room type is its cheapest
  const m = new Map<string, Offer[]>()
  for (const o of offers) {
    const g = m.get(o.room_type)
    if (g) g.push(o)
    else m.set(o.room_type, [o])
  }
  return [...m.entries()]
}

function cssKey(s: string) {
  return s.replace(/[^A-Za-z0-9_-]/g, "_")
}

/** Room builder: one offer per room of the party, all at the same hotel (R-29). */
export function RoomBuilder({ flow, idPrefix = "rb" }: { flow: BookingFlow; idPrefix?: string }) {
  const { t } = useTexT()
  const L = useLabels()
  const partyText = usePartyText()
  const sel = flow.selection
  const r = flow.result
  if (!sel || !r) return null
  const prop = flow.propertyResult(sel.property)
  return (
    <div className="space-y-3">
      {r.rooms.map((party, i) => {
        const cands = flow
          .roomCandidates(sel.property, i, sel.picks)
          .sort((a, b) => cmpDecimal(a.room.quote.totals.total, b.room.quote.totals.total))
        const label = `${t("crs.room_n", { n: i + 1 })} · ${partyText(party.adults, party.children.map((c) => c.age))}`
        if (!cands.length)
          return (
            <div key={i}>
              <p className="text-sm font-medium text-zinc-800">{label}</p>
              <p className="mt-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="status">
                {t("crs.builder.no_fit")}
              </p>
            </div>
          )
        return (
          <Field key={i} label={label}>
            <Select
              id={`${idPrefix}-room-${i}`}
              value={sel.picks[i] ?? ""}
              placeholder={t("crs.builder.choose")}
              onChange={(e) => flow.setRoomPick(i, e.target.value || null)}
              options={cands.map(({ offer, room, left }) => {
                const id = offerId(offer)
                const none = left < 1 && sel.picks[i] !== id
                return {
                  value: id,
                  // a room type whose last rooms the other picks already take cannot be chosen again
                  disabled: none,
                  label: `${roomName(prop, offer.room_type)} · ${L.board(offer.board)}${
                    ratePlanName({ ...offer, property: sel.property }) ? ` · ${ratePlanName({ ...offer, property: sel.property })}` : ""
                  } — ${money(room.quote.totals.total, room.quote.currency)}${none ? ` (${t("crs.builder.none_left")})` : ""}`,
                }
              })}
            />
          </Field>
        )
      })}
    </div>
  )
}
