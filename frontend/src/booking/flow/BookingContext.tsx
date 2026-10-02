// State of one guest booking on a site: the search (from the URL), the room/rate
// chosen for each requested room, extras, server quotes, guest details and the
// payment choice. Persisted per tab so a reload does not lose the guest's work;
// every price shown comes from the server responses kept here.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { useSearchParams } from "react-router-dom"
import { useI18n } from "../i18n"
import { analyticsEvent } from "../lib/analytics"
import { ApiError, pub, type ErrorKind } from "../lib/api"
import { apiRooms, applyCriteria, isComplete, parseCriteria, searchKey, type Criteria } from "../lib/criteria"
import { siteUrl } from "../lib/mount"
import { getJSON, manageToken, newKey, rememberPayment, removeItem, saveInstructions, saveManageToken, sessionId, setJSON } from "../lib/storage"
import { armAbandon, disarmAbandon, trackMarketRefused } from "../lib/track"
import { marketRefusal, refusedLinkPayload, type MarketRefusal } from "../lib/marketLink"
import { priceChange, type PriceChange } from "../lib/priceChange"
import type { Residency } from "../../lib/residency"
import { useSite } from "../site/SiteContext"
import type { Basket, BookResponse, Offer, PaymentMethod, PaymentStart, QuoteResponse, RatePlanInfo, RoomQuote, SearchResult } from "../types"

export type Step = "rooms" | "extras" | "details" | "payment"

export interface Selection {
  hotel: string
  roomType: string
  roomName: string
  board: string
  ratePlan: string | null
  ratePlanName: string | null
  offerKey: string
  quote: RoomQuote
  rateInfo: RatePlanInfo | null
  currency: string
}

export interface ExtraChoice {
  code: string
  quantity: number
  service_dates?: string[]
}

export interface Guest {
  first_name: string
  last_name: string
  email: string
  phone: string
  country: string
  /** ISO code; asked for a residents-only market's prices, where it counts as much as the residence (O-8) */
  nationality: string
  special_requests: string
  consent_email: boolean
  consent_sms: boolean
  consent_whatsapp: boolean
}

/** An extra the guest asked for that the quote did not add (and does not charge). */
export interface RejectedExtra {
  room: number
  /** the code as the guest's choice holds it */
  code: string
  name: string
  /** the server's reason, e.g. "sold out on 2027-06-10" (see lib/extras refusalText) */
  reason: string
}

export interface QuoteOutcome {
  error: FlowError | null
  /** extras requested but not added by the quotes just made (empty on error) */
  rejected: RejectedExtra[]
  /** the quotes just made (empty on error): book({ quotes }) books these, not the render's (O-30) */
  quotes: QuoteResponse[]
  /** prices that changed with the quotes just made (also in flow.priceChanges; empty on error) */
  changes: PriceChange[]
}

interface FlowState {
  key: string | null
  hotel: string | null
  selections: (Selection | null)[]
  extras: Record<number, Record<string, ExtraChoice>>
  quotes: (QuoteResponse | null)[]
  quotedAt: number | null
  priceChanges: PriceChange[]
  /** per room, the last quote the guest was shown: what the next one is compared with (LO-32). Kept when the extras
   * change (they clear the quotes), gone with the room chosen; absent in a flow saved before it was kept */
  seen?: (RoomQuote | null)[]
  guest: Guest
  method: PaymentMethod | null
  /** gateway chosen when several accounts offer the same method (e.g. two card gateways) */
  providerAccount: string | null
  terms: boolean
  bookKey: string | null
  /** language the saved names and quote lines are in (hotel content is localised) */
  lang?: string
}

const EMPTY_GUEST: Guest = {
  first_name: "",
  last_name: "",
  email: "",
  phone: "",
  country: "",
  nationality: "",
  special_requests: "",
  consent_email: false,
  consent_sms: false,
  consent_whatsapp: false,
}

function emptyFlow(guest: Guest = EMPTY_GUEST): FlowState {
  return { key: null, hotel: null, selections: [], extras: {}, quotes: [], quotedAt: null, priceChanges: [], guest, method: null, providerAccount: null, terms: false, bookKey: null }
}

export interface SearchState {
  key: string | null
  /** language of the offers' names */
  lang: string | null
  hotelScope: string | null
  status: "idle" | "loading" | "done" | "error"
  data: SearchResult | null
  error: ApiError | null
}

export interface FlowError {
  kind: ErrorKind | "unavailable"
  message: string
  room?: number
  /** the refusal's stable code and params (G-70a), when the server sent one */
  code?: string | null
  params?: Record<string, unknown>
}

export interface Refreshed {
  status: "ok" | "changed" | "gone"
  selections: (Selection | null)[]
}

/** Quotes older than this are refreshed before booking (server TTL is 30 min). */
const QUOTE_MAX_AGE = 25 * 60 * 1000

interface Ctx {
  criteria: Criteria
  setCriteria: (c: Criteria, opts?: { replace?: boolean }) => void
  search: SearchState
  runSearch: (opts?: { force?: boolean }) => Promise<SearchResult | null>
  step: Step
  goStep: (s: Step, opts?: { replace?: boolean; keepError?: boolean }) => void
  flow: FlowState
  hotelName: string | null
  activeRoom: number
  setActiveRoom: (i: number) => void
  select: (roomIndex: number, offer: Offer, hotel: string, roomName: string) => void
  setExtra: (roomIndex: number, code: string, choice: ExtraChoice | null) => void
  quoteAll: (override?: (Selection | null)[], baseline?: (Selection | null)[]) => Promise<QuoteOutcome>
  quotesFresh: boolean
  /** extras the current quotes could not add (sold out, closed…): the guest is told, never charged */
  rejectedExtras: RejectedExtra[]
  /** continue without them: forget those choices, keeping the quotes (they do not include them) */
  dropRejectedExtras: () => void
  /** The booking was refused with ExtraSoldOut although every room's quote still adds its extras:
   * each room is quoted alone, the booking counts the rooms together (G-19). That error, while
   * the extras chosen are still the ones refused (null once an extra choice or the search changes). */
  extrasClash: FlowError | null
  /** remember the current extras choice as refused together (see extrasClash) */
  markExtrasClash: (error: FlowError) => void
  refreshAfterExpiry: () => Promise<Refreshed>
  setGuest: (g: Partial<Guest>) => void
  setMethod: (m: PaymentMethod, providerAccount?: string | null) => void
  setTerms: (v: boolean) => void
  /** Book the flow's quotes, or `quotes` just made (quoteAll) with a new idempotency key. */
  book: (opts?: { quotes?: QuoteResponse[] }) => Promise<{ error?: FlowError; payment?: PaymentStart | null; booking?: BookResponse }>
  hasExtras: boolean
  allSelected: boolean
  clearPriceChanges: () => void
  pending: boolean
  setPending: (v: boolean) => void
  flowError: FlowError | null
  setFlowError: (e: FlowError | null) => void
  /** booking reference made in this visit (the basket is already cleared) */
  justBooked: string | null
  /** server total and amount due now per payment method of the quoted rooms */
  basket: BasketState
  reloadBasket: () => void
  /** the prices chosen are for residents of these countries (O-8): the booked quotes' market, else the search's */
  residency: Residency | null
  /** search again without the campaign link's market and country (the standard prices); null without a link */
  standardPrices: (() => void) | null
  /** the campaign link's market the server refused: the results are the standard ones, and say why (G-55b) */
  marketNotice: MarketRefusal | null
}

export interface BasketState {
  status: "idle" | "loading" | "done" | "error"
  data: Basket | null
  /** quote ids the data belongs to */
  key: string | null
}

const BookingCtx = createContext<Ctx | null>(null)

export function useBooking() {
  const v = useContext(BookingCtx)
  if (!v) throw new Error("useBooking outside BookingProvider")
  return v
}

function toFlowError(e: unknown): FlowError {
  if (e instanceof ApiError) return { kind: e.kind, message: e.message, code: e.code, params: e.params }
  return { kind: "server", message: "" }
}

/** Extras the guest chose that a room's quote refused (quote.extras[].ok = false). Extras
 * the hotel adds by itself (mandatory) are not the guest's choice and are left out. */
function findRejected(quotes: (QuoteResponse | null)[], extras: FlowState["extras"]): RejectedExtra[] {
  const out: RejectedExtra[] = []
  quotes.forEach((q, room) => {
    const chosen = extras[room] ?? {}
    const codes = new Map(Object.keys(chosen).map((c) => [c.toUpperCase(), c]))
    for (const e of q?.ok ? q.quote?.extras ?? [] : []) {
      const code = codes.get((e.code ?? "").toUpperCase())
      if (e.ok || !code || out.some((r) => r.room === room && r.code === code)) continue
      out.push({ room, code, name: e.name || code, reason: e.reason ?? "" })
    }
  })
  return out
}

/** The extras chosen for every room (quantities and days), as one comparable string. */
function extrasSignature(extras: FlowState["extras"]): string {
  const rooms = Object.entries(extras)
    .map(([room, choices]) => ({
      room: Number(room),
      choices: Object.entries(choices)
        .map(([code, c]) => `${code}×${c.quantity}@${[...(c.service_dates ?? [])].sort().join("+")}`)
        .sort(),
    }))
    .filter((r) => r.choices.length)
    .sort((a, b) => a.room - b.room)
  return JSON.stringify(rooms)
}

export function BookingProvider({ children }: { children: ReactNode }) {
  const { site } = useSite()
  const { lang } = useI18n()
  const [sp, setSp] = useSearchParams()
  const criteria = useMemo(() => parseCriteria(sp), [sp])
  const step = (["extras", "details", "payment"].includes(sp.get("step") ?? "") ? sp.get("step") : "rooms") as Step
  const storeKey = `tex.flow.${site.slug}`

  const [flow, setFlow] = useState<FlowState>(() => getJSON<FlowState>(storeKey) ?? emptyFlow())
  const [search, setSearch] = useState<SearchState>({ key: null, lang: null, hotelScope: null, status: "idle", data: null, error: null })
  const [activeRoom, setActiveRoom] = useState(0)
  const [pending, setPending] = useState(false)
  const [flowError, setFlowError] = useState<FlowError | null>(null)
  const [justBooked, setJustBooked] = useState<string | null>(null)
  const [basket, setBasket] = useState<BasketState>({ status: "idle", data: null, key: null })
  const [basketTick, setBasketTick] = useState(0)
  // ExtraSoldOut for an extras choice every room's quote accepts (see Ctx.extrasClash)
  const [clash, setClash] = useState<{ sig: string; error: FlowError } | null>(null)
  const searchSeq = useRef(0)
  // a market / country from a link the server refused: search without it from then on
  const refusedMarket = useRef<string | null>(null)
  const [marketNotice, setMarketNotice] = useState<MarketRefusal | null>(null)

  useEffect(() => {
    setJSON(storeKey, flow)
  }, [flow, storeKey])

  const key = isComplete(criteria) ? searchKey(criteria) : null
  const hotel = site.group ? criteria.hotel : site.hotels[0]?.name ?? null

  // a different search (dates, party, promo, currency) or hotel invalidates the selection
  useEffect(() => {
    if (!key) return
    setFlow((f) => {
      if (f.key === key && f.hotel === hotel && f.selections.length === criteria.rooms.length) return f
      return { ...emptyFlow(f.guest), key, hotel }
    })
    setActiveRoom(0)
  }, [key, hotel, criteria.rooms.length])

  const runSearch = useCallback(
    async (opts: { force?: boolean } = {}) => {
      if (!key) return null
      const scope = site.group && criteria.hotel ? criteria.hotel : null
      if (!opts.force && search.key === key && search.lang === lang && search.status !== "error" && (search.hotelScope === null || search.hotelScope === scope))
        return search.data
      const seq = ++searchSeq.current
      setSearch((s) => ({ key, lang, hotelScope: scope, status: "loading", data: s.key === key ? s.data : null, error: null }))
      try {
        const args = {
          site: site.slug,
          check_in: criteria.checkIn,
          check_out: criteria.checkOut,
          rooms: apiRooms(criteria),
          currency: criteria.currency || undefined,
          promo_code: criteria.promo || undefined,
          hotel: scope || undefined,
          session_id: sessionId(),
        }
        // campaign deep link: the market (or the guest's country) picks the contracts
        const linked = criteria.market || criteria.country ? `${criteria.market ?? ""}|${criteria.country ?? ""}` : null
        let data: SearchResult
        if (linked && refusedMarket.current !== linked) {
          try {
            data = await pub<SearchResult>("search", { ...args, market: criteria.market || undefined, country: criteria.country || undefined })
            if (seq === searchSeq.current) setMarketNotice(null)
          } catch (e) {
            // a market the site does not sell, an unknown or ambiguous one, or a residents-only one for another country
            // must never break the page: search without it, say so and count it (G-55b). Any other refusal (bad dates,
            // an unknown hotel, the network) is the search's own error
            const refusal = marketRefusal(e)
            if (!refusal) throw e
            console.warn(`[tex-booking] market link ignored (market=${criteria.market ?? "-"}, country=${criteria.country ?? "-"}): ${refusal.reason}`)
            refusedMarket.current = linked
            if (seq === searchSeq.current) setMarketNotice(refusal)
            trackMarketRefused(site.slug, refusedLinkPayload(refusal.reason, criteria.market, criteria.country))
            analyticsEvent("market_link_refused", { reason: refusal.reason })
            data = await pub<SearchResult>("search", args)
          }
        } else {
          if (!linked && seq === searchSeq.current) setMarketNotice(null)
          data = await pub<SearchResult>("search", args)
        }
        if (seq === searchSeq.current) setSearch({ key, lang, hotelScope: scope, status: "done", data, error: null })
        analyticsEvent("search", { check_in: criteria.checkIn, check_out: criteria.checkOut })
        return data
      } catch (e) {
        if (seq === searchSeq.current)
          setSearch({ key, lang, hotelScope: scope, status: "error", data: null, error: e instanceof ApiError ? e : new ApiError("", 0, "", "network") })
        return null
      }
    },
    [key, criteria, site, lang, search.key, search.lang, search.status, search.hotelScope, search.data],
  )

  // a language switch searches again: room and rate names come back in the new language
  useEffect(() => {
    if (key) void runSearch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, criteria.hotel, lang])

  // Selections keep their names from the latest search (language switch, reload), and
  // the fresh offer key and quote when the price is unchanged; a different price is
  // left to the quote step, which reports it.
  useEffect(() => {
    const data = search.status === "done" ? search.data : null
    if (!data) return
    setFlow((f) => {
      let touched = false
      const selections = f.selections.map((s, i) => {
        if (!s) return s
        const prop = data.properties.find((p) => p.property === s.hotel)
        const offer = prop?.offers.find((o) => o.room_type === s.roomType && o.board === s.board && o.rate_plan === s.ratePlan)
        if (!prop || !offer) return s
        const room = offer.rooms.find((r) => r.room_index === i)
        const same = !!room && room.quote.totals.total === s.quote.totals.total
        const next: Selection = {
          ...s,
          roomName: prop.rooms[s.roomType]?.name ?? s.roomName,
          ratePlanName: offer.rate_plan_info?.name ?? s.ratePlanName,
          rateInfo: offer.rate_plan_info ?? s.rateInfo,
          offerKey: same ? room.offer_key : s.offerKey,
          quote: same ? room.quote : s.quote,
        }
        touched = true
        return next
      })
      return touched ? { ...f, selections } : f
    })
  }, [search.status, search.data])

  const setCriteria = useCallback(
    (c: Criteria, opts: { replace?: boolean } = {}) => setSp(applyCriteria(sp, c), { replace: opts.replace }),
    [sp, setSp],
  )

  const goStep = useCallback(
    (s: Step, opts: { replace?: boolean; keepError?: boolean } = {}) => {
      const next = new URLSearchParams(sp)
      if (s === "rooms") next.delete("step")
      else next.set("step", s)
      setSp(next, { replace: opts.replace })
      if (!opts.keepError) setFlowError(null)
      window.scrollTo({ top: 0 })
    },
    [sp, setSp],
  )

  useEffect(() => {
    setFlowError(null)
    setClash(null)
  }, [key, hotel])

  const select = useCallback(
    (roomIndex: number, offer: Offer, hotelName: string, roomName: string) => {
      // rooms holds only the parties this room type fits: look up by room_index
      const room = offer.rooms.find((r) => r.room_index === roomIndex)
      if (!room) return
      const sel: Selection = {
        hotel: hotelName,
        roomType: offer.room_type,
        roomName,
        board: offer.board,
        ratePlan: offer.rate_plan,
        ratePlanName: offer.rate_plan_info?.name ?? null,
        offerKey: room.offer_key,
        quote: room.quote,
        rateInfo: offer.rate_plan_info ?? room.quote.rate_plan ?? null,
        currency: offer.currency,
      }
      setFlow((f) => {
        const selections = Array.from({ length: criteria.rooms.length }, (_, i) => (i === roomIndex ? sel : f.selections[i] ?? null))
        const next = selections.findIndex((s) => !s)
        if (next >= 0) setActiveRoom(next)
        // a room chosen again is compared with the search's price of it again
        const seen = (f.seen ?? []).map((q, i) => (i === roomIndex ? null : q))
        return { ...f, selections, quotes: [], seen, quotedAt: null, priceChanges: [], bookKey: null }
      })
    },
    [criteria.rooms.length],
  )

  const setExtra = useCallback((roomIndex: number, code: string, choice: ExtraChoice | null) => {
    setClash(null)
    setFlow((f) => {
      const room = { ...(f.extras[roomIndex] ?? {}) }
      if (choice && choice.quantity > 0) room[code] = choice
      else delete room[code]
      return { ...f, extras: { ...f.extras, [roomIndex]: room }, quotes: [], quotedAt: null, bookKey: null }
    })
  }, [])

  const quotesFresh =
    flow.quotes.length === flow.selections.length &&
    flow.quotes.length > 0 &&
    flow.quotes.every((q) => q?.ok) &&
    !!flow.quotedAt &&
    Date.now() - flow.quotedAt < QUOTE_MAX_AGE

  const quoteAll = useCallback(async (override?: (Selection | null)[], baseline?: (Selection | null)[]): Promise<QuoteOutcome> => {
    const sels = override ?? flow.selections
    const base = baseline ?? sels
    const failed = (error: FlowError): QuoteOutcome => ({ error, rejected: [], quotes: [], changes: [] })
    if (!sels.length || sels.some((s) => !s)) return failed({ kind: "invalid", message: "" })
    // the rooms of a booking are quoted together: a coupon's minimum basket is the whole
    // booking's (G-84), so every room is priced knowing the others
    let results: QuoteResponse[]
    try {
      const out = await pub<{ ok: boolean; rooms: QuoteResponse[] }>("quote_rooms", {
        site: site.slug,
        rooms: sels.map((s, i) => ({ offer_key: s!.offerKey, extras: Object.values(flow.extras[i] ?? {}) })),
        session_id: sessionId(),
      })
      results = out.rooms
    } catch (e) {
      return failed(toFlowError(e))
    }
    const quotes: QuoteResponse[] = []
    const changes: PriceChange[] = []
    for (let i = 0; i < results.length; i++) {
      const q = results[i]
      if (!q.ok || !q.quote) {
        const code = q.reasons?.[0]?.code
        return failed({ kind: code === "SOLD_OUT" ? "sold_out" : "unavailable", message: "", room: i })
      }
      // against the last quote the guest saw of this room, else the search's offer (LO-32)
      const change = priceChange(i, q, flow.seen?.[i] ?? null, (base[i] ?? sels[i])!.quote)
      if (change) changes.push(change)
      quotes.push(q)
    }
    setFlow((f) => ({ ...f, quotes, seen: quotes.map((r) => r.quote ?? null), quotedAt: Date.now(), priceChanges: changes, bookKey: null }))
    armAbandon(site.slug, { quotes: quotes.map((q) => q.quote_id), hotel: sels[0]!.hotel })
    return { error: null, rejected: findRejected(quotes, flow.extras), quotes, changes }
  }, [flow.selections, flow.extras, flow.seen, site.slug])

  const rejectedExtras = useMemo(() => findRejected(flow.quotes, flow.extras), [flow.quotes, flow.extras])

  // the quotes already leave these extras out (and do not charge them): keep the quotes
  const dropRejectedExtras = useCallback(() => {
    setFlow((f) => {
      const gone = findRejected(f.quotes, f.extras)
      if (!gone.length) return f
      const extras = { ...f.extras }
      for (const r of gone) {
        const room = { ...(extras[r.room] ?? {}) }
        delete room[r.code]
        extras[r.room] = room
      }
      return { ...f, extras }
    })
  }, [])

  const extrasSig = useMemo(() => extrasSignature(flow.extras), [flow.extras])
  const extrasClash = clash && clash.sig === extrasSig ? clash.error : null
  const markExtrasClash = useCallback((error: FlowError) => setClash({ sig: extrasSig, error }), [extrasSig])

  /** After "expired": search again with the same criteria and re-pick the same rooms. */
  const refreshAfterExpiry = useCallback(async (): Promise<Refreshed> => {
    const data = await runSearch({ force: true })
    if (!data) return { status: "gone", selections: [] }
    const prop = data.properties.find((p) => p.property === flow.selections[0]?.hotel)
    if (!prop) return { status: "gone", selections: [] }
    let changed = false
    const next: (Selection | null)[] = flow.selections.map((s, i) => {
      if (!s) return null
      const offer = prop.offers.find((o) => o.room_type === s.roomType && o.board === s.board && o.rate_plan === s.ratePlan)
      const room = offer?.rooms.find((r) => r.room_index === i)
      if (!offer || !room) return null
      if (room.quote.totals.total !== s.quote.totals.total) changed = true
      return { ...s, offerKey: room.offer_key, quote: room.quote }
    })
    setFlow((f) => ({ ...f, selections: next, quotes: [], quotedAt: null, bookKey: null }))
    if (next.some((s) => !s)) return { status: "gone", selections: next }
    return { status: changed ? "changed" : "ok", selections: next }
  }, [runSearch, flow.selections])

  // quotes (price lines, extra names) are in the language they were made in: after a
  // switch, or on a flow saved in another language, quote the same rooms again
  useEffect(() => {
    if (flow.lang === lang) return
    const requote = flow.quotes.length > 0 && flow.selections.length > 0 && flow.selections.every(Boolean)
    setFlow((f) => ({ ...f, lang }))
    if (!requote) return
    setPending(true)
    void quoteAll().then(({ error }) => {
      setPending(false)
      if (error) setFlowError(error)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang, flow.lang])

  const setGuest = useCallback((g: Partial<Guest>) => setFlow((f) => ({ ...f, guest: { ...f.guest, ...g } })), [])
  const setMethod = useCallback(
    (m: PaymentMethod, providerAccount: string | null = null) =>
      setFlow((f) => (f.method === m && f.providerAccount === providerAccount ? f : { ...f, method: m, providerAccount, bookKey: null })),
    [],
  )
  const setTerms = useCallback((v: boolean) => setFlow((f) => ({ ...f, terms: v })), [])
  const clearPriceChanges = useCallback(() => setFlow((f) => ({ ...f, priceChanges: [] })), [])

  // server total and amount due now per payment method, once every room is quoted
  const quotedIds = flow.quotes.map((q) => q?.quote_id).filter((x): x is string => !!x)
  const basketKey = quotedIds.length && quotedIds.length === flow.selections.length ? quotedIds.join(",") : null
  useEffect(() => {
    if (!basketKey) {
      setBasket({ status: "idle", data: null, key: null })
      return
    }
    let alive = true
    setBasket((b) => ({ status: "loading", data: b.key === basketKey ? b.data : null, key: basketKey }))
    pub<Basket>("basket", { site: site.slug, quote_ids: basketKey.split(","), session_id: sessionId() })
      .then((data) => alive && setBasket({ status: "done", data, key: basketKey }))
      .catch(() => alive && setBasket({ status: "error", data: null, key: basketKey }))
    return () => {
      alive = false
    }
  }, [basketKey, site.slug, basketTick])
  const reloadBasket = useCallback(() => setBasketTick((n) => n + 1), [])

  const book = useCallback(async (opts: { quotes?: QuoteResponse[] } = {}) => {
    // quotes just made in the same step (refreshed before booking) are not in this render's flow yet:
    // the caller passes them, and they are a new intent with a new key (O-30)
    const fresh = opts.quotes
    const quoteIds = (fresh ?? flow.quotes).map((q) => q?.quote_id).filter((x): x is string => !!x)
    if (!quoteIds.length || quoteIds.length !== flow.selections.length) return { error: { kind: "expired", message: "" } as FlowError }
    const bookKey = (fresh ? null : flow.bookKey) ?? newKey("book")
    if (bookKey !== flow.bookKey) setFlow((f) => ({ ...f, bookKey }))
    const g = flow.guest
    const method = flow.method ?? "Card"
    // name the gateway only when several accounts offer this method (e.g. two card gateways)
    const sameMethod = basket.data?.methods.filter((m) => m.available && m.method === method) ?? []
    const providerAccount = sameMethod.length > 1 ? flow.providerAccount ?? sameMethod[0].provider_account : null
    try {
      const res = await pub<BookResponse>("book", {
        site: site.slug,
        quote_ids: quoteIds,
        guest: {
          first_name: g.first_name.trim(),
          last_name: g.last_name.trim(),
          email: g.email.trim(),
          phone: g.phone.trim(),
          country: g.country || undefined,
          // a flow saved before the field existed has none
          nationality: g.nationality || undefined,
          special_requests: g.special_requests.trim(),
          consent_email: g.consent_email,
          consent_sms: g.consent_sms,
          consent_whatsapp: g.consent_whatsapp,
        },
        payment_method: method,
        provider_account: providerAccount || undefined,
        idempotency_key: bookKey,
        language: lang,
        session_id: sessionId(),
        // the server fills in {booking} and accepts only its own host or the site's verified domains
        return_url: siteUrl(site.slug, "confirmation/{booking}"),
      })
      // A retried request (same session + key) answers like the first one, with a short-lived
      // resume token instead of the manage token: never replace a manage token we already hold.
      const held = manageToken(res.booking)
      if (res.manage_token && !(res.idempotent_replay && held && !held.includes("."))) saveManageToken(res.booking, res.manage_token, site.slug)
      const hotelName = site.hotels.find((h) => h.name === res.property)?.property_name ?? res.property
      if (res.payment) {
        rememberPayment(res.payment, { amount: res.due_now, currency: res.currency, hotel: hotelName })
        if (res.payment.instructions && Object.keys(res.payment.instructions).length) saveInstructions(res.booking, res.payment.instructions)
      }
      disarmAbandon()
      analyticsEvent("booking", { booking: res.booking, currency: res.currency, value: res.total })
      // the booking exists now: forget the basket (the guest details stay only for this tab's next booking)
      setJustBooked(res.booking)
      setFlow((f) => ({ ...emptyFlow(f.guest) }))
      removeItem(storeKey)
      return { payment: res.payment, booking: res }
    } catch (e) {
      return { error: toFlowError(e) }
    }
  }, [flow, site, lang, storeKey, basket.data])

  const hasExtras = !!(hotel && (site.extras?.[hotel]?.length ?? 0) > 0)
  const allSelected = flow.selections.length === criteria.rooms.length && flow.selections.every(Boolean)
  const hotelName = hotel ? site.hotels.find((h) => h.name === hotel)?.property_name ?? hotel : null
  // the booked quotes' market once the basket of these quotes is read (null there means "ask nothing"), else the search's
  const residency = basket.key === basketKey && basket.data ? basket.data.residency ?? null : search.data?.residency ?? null
  const linked = !!(criteria.market || criteria.country)
  const standardPrices = useCallback(() => setCriteria({ ...criteria, market: null, country: null }), [criteria, setCriteria])

  const value: Ctx = {
    criteria,
    setCriteria,
    search,
    runSearch,
    step,
    goStep,
    flow,
    hotelName,
    activeRoom,
    setActiveRoom,
    select,
    setExtra,
    quoteAll,
    quotesFresh,
    rejectedExtras,
    dropRejectedExtras,
    extrasClash,
    markExtrasClash,
    refreshAfterExpiry,
    setGuest,
    setMethod,
    setTerms,
    book,
    hasExtras,
    allSelected,
    clearPriceChanges,
    pending,
    setPending,
    flowError,
    setFlowError,
    justBooked,
    basket,
    reloadBasket,
    residency,
    standardPrices: linked ? standardPrices : null,
    marketNotice: linked ? marketNotice : null,
  }
  return <BookingCtx.Provider value={value}>{children}</BookingCtx.Provider>
}
