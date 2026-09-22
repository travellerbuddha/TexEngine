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
import { getJSON, newKey, rememberPayment, removeItem, saveInstructions, saveManageToken, sessionId, setJSON } from "../lib/storage"
import { armAbandon, disarmAbandon } from "../lib/track"
import { useSite } from "../site/SiteContext"
import type { BookResponse, Offer, PaymentMethod, PaymentStart, QuoteResponse, RatePlanInfo, RoomQuote, SearchResult } from "../types"

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
  special_requests: string
  consent_email: boolean
  consent_sms: boolean
  consent_whatsapp: boolean
}

export interface PriceChange {
  room: number
  from: string
  to: string
  currency: string
}

interface FlowState {
  key: string | null
  hotel: string | null
  selections: (Selection | null)[]
  extras: Record<number, Record<string, ExtraChoice>>
  quotes: (QuoteResponse | null)[]
  quotedAt: number | null
  priceChanges: PriceChange[]
  guest: Guest
  method: PaymentMethod | null
  terms: boolean
  bookKey: string | null
}

const EMPTY_GUEST: Guest = {
  first_name: "",
  last_name: "",
  email: "",
  phone: "",
  country: "",
  special_requests: "",
  consent_email: false,
  consent_sms: false,
  consent_whatsapp: false,
}

function emptyFlow(guest: Guest = EMPTY_GUEST): FlowState {
  return { key: null, hotel: null, selections: [], extras: {}, quotes: [], quotedAt: null, priceChanges: [], guest, method: null, terms: false, bookKey: null }
}

export interface SearchState {
  key: string | null
  hotelScope: string | null
  status: "idle" | "loading" | "done" | "error"
  data: SearchResult | null
  error: ApiError | null
}

export interface FlowError {
  kind: ErrorKind | "unavailable"
  message: string
  room?: number
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
  quoteAll: (override?: (Selection | null)[], baseline?: (Selection | null)[]) => Promise<FlowError | null>
  quotesFresh: boolean
  refreshAfterExpiry: () => Promise<Refreshed>
  setGuest: (g: Partial<Guest>) => void
  setMethod: (m: PaymentMethod) => void
  setTerms: (v: boolean) => void
  book: () => Promise<{ error?: FlowError; payment?: PaymentStart | null; booking?: BookResponse }>
  hasExtras: boolean
  allSelected: boolean
  clearPriceChanges: () => void
  pending: boolean
  setPending: (v: boolean) => void
  flowError: FlowError | null
  setFlowError: (e: FlowError | null) => void
  /** booking reference made in this visit (the basket is already cleared) */
  justBooked: string | null
}

const BookingCtx = createContext<Ctx | null>(null)

export function useBooking() {
  const v = useContext(BookingCtx)
  if (!v) throw new Error("useBooking outside BookingProvider")
  return v
}

function toFlowError(e: unknown): FlowError {
  if (e instanceof ApiError) return { kind: e.kind, message: e.message }
  return { kind: "server", message: "" }
}

export function BookingProvider({ children }: { children: ReactNode }) {
  const { site } = useSite()
  const { lang } = useI18n()
  const [sp, setSp] = useSearchParams()
  const criteria = useMemo(() => parseCriteria(sp), [sp])
  const step = (["extras", "details", "payment"].includes(sp.get("step") ?? "") ? sp.get("step") : "rooms") as Step
  const storeKey = `tex.flow.${site.slug}`

  const [flow, setFlow] = useState<FlowState>(() => getJSON<FlowState>(storeKey) ?? emptyFlow())
  const [search, setSearch] = useState<SearchState>({ key: null, hotelScope: null, status: "idle", data: null, error: null })
  const [activeRoom, setActiveRoom] = useState(0)
  const [pending, setPending] = useState(false)
  const [flowError, setFlowError] = useState<FlowError | null>(null)
  const [justBooked, setJustBooked] = useState<string | null>(null)
  const searchSeq = useRef(0)

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
      if (!opts.force && search.key === key && search.status !== "error" && (search.hotelScope === null || search.hotelScope === scope)) return search.data
      const seq = ++searchSeq.current
      setSearch((s) => ({ key, hotelScope: scope, status: "loading", data: s.key === key ? s.data : null, error: null }))
      try {
        const data = await pub<SearchResult>("search", {
          site: site.slug,
          check_in: criteria.checkIn,
          check_out: criteria.checkOut,
          rooms: apiRooms(criteria),
          currency: criteria.currency || undefined,
          promo_code: criteria.promo || undefined,
          hotel: scope || undefined,
          session_id: sessionId(),
        })
        if (seq === searchSeq.current) setSearch({ key, hotelScope: scope, status: "done", data, error: null })
        analyticsEvent("search", { check_in: criteria.checkIn, check_out: criteria.checkOut })
        return data
      } catch (e) {
        if (seq === searchSeq.current)
          setSearch({ key, hotelScope: scope, status: "error", data: null, error: e instanceof ApiError ? e : new ApiError("", 0, "", "network") })
        return null
      }
    },
    [key, criteria, site, search.key, search.status, search.hotelScope, search.data],
  )

  useEffect(() => {
    if (key) void runSearch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, criteria.hotel])

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
  }, [key, hotel])

  const select = useCallback(
    (roomIndex: number, offer: Offer, hotelName: string, roomName: string) => {
      const room = offer.rooms[roomIndex] ?? offer.rooms[0]
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
        return { ...f, selections, quotes: [], quotedAt: null, priceChanges: [], bookKey: null }
      })
    },
    [criteria.rooms.length],
  )

  const setExtra = useCallback((roomIndex: number, code: string, choice: ExtraChoice | null) => {
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

  const quoteAll = useCallback(async (override?: (Selection | null)[], baseline?: (Selection | null)[]): Promise<FlowError | null> => {
    const sels = override ?? flow.selections
    const base = baseline ?? sels
    if (!sels.length || sels.some((s) => !s)) return { kind: "invalid", message: "" }
    const results = await Promise.allSettled(
      sels.map((s, i) =>
        pub<QuoteResponse>("quote", {
          site: site.slug,
          offer_key: s!.offerKey,
          extras: Object.values(flow.extras[i] ?? {}),
          session_id: sessionId(),
        }),
      ),
    )
    const quotes: QuoteResponse[] = []
    const changes: PriceChange[] = []
    for (let i = 0; i < results.length; i++) {
      const r = results[i]
      if (r.status === "rejected") return { ...toFlowError(r.reason), room: i }
      const q = r.value
      if (!q.ok || !q.quote) {
        const code = q.reasons?.[0]?.code
        return { kind: code === "SOLD_OUT" ? "sold_out" : "unavailable", message: q.reasons?.[0]?.message ?? "", room: i }
      }
      const before = (base[i] ?? sels[i])!.quote.totals.accommodation
      const after = q.quote.totals.accommodation
      if (q.price_changed || (before && after && before !== after))
        changes.push({ room: i, from: q.price_changed && q.previous_total ? q.previous_total : before, to: q.price_changed ? q.quote.totals.total : after, currency: q.quote.currency })
      quotes.push(q)
    }
    setFlow((f) => ({ ...f, quotes, quotedAt: Date.now(), priceChanges: changes, bookKey: null }))
    armAbandon(site.slug, { quotes: quotes.map((q) => q.quote_id), hotel: sels[0]!.hotel })
    return null
  }, [flow.selections, flow.extras, site.slug])

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
      const room = offer?.rooms[i]
      if (!offer || !room) return null
      if (room.quote.totals.total !== s.quote.totals.total) changed = true
      return { ...s, offerKey: room.offer_key, quote: room.quote }
    })
    setFlow((f) => ({ ...f, selections: next, quotes: [], quotedAt: null, bookKey: null }))
    if (next.some((s) => !s)) return { status: "gone", selections: next }
    return { status: changed ? "changed" : "ok", selections: next }
  }, [runSearch, flow.selections])

  const setGuest = useCallback((g: Partial<Guest>) => setFlow((f) => ({ ...f, guest: { ...f.guest, ...g } })), [])
  const setMethod = useCallback((m: PaymentMethod) => setFlow((f) => (f.method === m ? f : { ...f, method: m, bookKey: null })), [])
  const setTerms = useCallback((v: boolean) => setFlow((f) => ({ ...f, terms: v })), [])
  const clearPriceChanges = useCallback(() => setFlow((f) => ({ ...f, priceChanges: [] })), [])

  const book = useCallback(async () => {
    const quoteIds = flow.quotes.map((q) => q?.quote_id).filter((x): x is string => !!x)
    if (!quoteIds.length || quoteIds.length !== flow.selections.length) return { error: { kind: "expired", message: "" } as FlowError }
    const bookKey = flow.bookKey ?? newKey("book")
    if (!flow.bookKey) setFlow((f) => ({ ...f, bookKey }))
    const g = flow.guest
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
          special_requests: g.special_requests.trim(),
          consent_email: g.consent_email,
          consent_sms: g.consent_sms,
          consent_whatsapp: g.consent_whatsapp,
        },
        payment_method: flow.method ?? "Card",
        idempotency_key: bookKey,
        language: lang,
        session_id: sessionId(),
      })
      if (res.manage_token) saveManageToken(res.booking, res.manage_token, site.slug)
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
  }, [flow, site, lang, storeKey])

  const hasExtras = !!(hotel && (site.extras?.[hotel]?.length ?? 0) > 0)
  const allSelected = flow.selections.length === criteria.rooms.length && flow.selections.every(Boolean)
  const hotelName = hotel ? site.hotels.find((h) => h.name === hotel)?.property_name ?? hotel : null

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
  }
  return <BookingCtx.Provider value={value}>{children}</BookingCtx.Provider>
}
