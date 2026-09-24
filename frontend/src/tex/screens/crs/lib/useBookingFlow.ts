// Search → offers → quotes → guest → payment → booking, shared by the CRS page and
// the Call Center. Holds the state only; every price, total and deposit comes from
// the server (crs.quote, ui_crs.quote_summary, ui_crs.book).
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { idempotencyKey, TexApiError } from "../../../lib/api"
import { addDays, nightsBetween } from "../../../lib/format"
import { useSession } from "../../../lib/session"
import { useSiteClock } from "../../../lib/siteDay"
import { TEX_LANGS, useTexT } from "../../../i18n"
import {
  bookQuotes,
  extrasAvailability as fetchExtrasAvailability,
  paymentMethods as fetchPaymentMethods,
  quoteOffer,
  quoteSummary,
  searchOffers,
  type ExtraRequest,
  type SearchArgs,
} from "./api"
import { fitChoice, type ExtraChoice, type ExtrasAvailability, type StayDates } from "./extrasStock"
import { offerId, partyComplete, partyToApi, type PartyForm } from "./party"
import type {
  BookingSummary,
  GuestRow,
  Offer,
  OfferRoom,
  PaymentMethod,
  PropertyResult,
  QuoteResult,
  QuoteSummary,
  SearchResult,
} from "./types"

export interface SearchFormState {
  check_in: string
  check_out: string
  rooms: PartyForm[]
  /** Always chosen explicitly — never guessed (CLAUDE.md). */
  market: string
  channel: string
  /** "" = the contract's selling currency. */
  currency: string
  promo: string[]
  properties: string[]
}

export interface GuestFormState {
  first_name: string
  last_name: string
  email: string
  phone: string
  special_requests: string
  language: string
  consent_email: boolean
  consent_sms: boolean
  consent_whatsapp: boolean
  /** CRM guest picked in the lookup (display only; the server matches by email/phone). */
  crm_guest?: GuestRow | null
}

export interface BookerFormState {
  /** The caller is the staying guest. */
  same: boolean
  name: string
  email: string
  phone: string
}

export interface Selection {
  property: string
  /** offerId per room of the party (null = not chosen yet). */
  picks: (string | null)[]
}

export type FieldErrors = Record<string, string>

export interface SelectResult {
  /** The selection after the call (unchanged when nothing could be assigned). */
  selection: Selection | null
  assigned: number[]
  /** Rooms the offer fits but its room type has no stock left for. */
  noStock: number[]
  /** Rooms the offer does not fit (capacity, age rules). */
  unfit: number[]
}

/** Extras chosen per room of the booking (room index → extra code → choice). */
export type RoomExtras = Record<number, Record<string, ExtraChoice>>

/** Service days that still fall inside the stay (after a search with other dates). */
function fitExtras(extras: RoomExtras, stay: StayDates): RoomExtras {
  return Object.fromEntries(
    Object.entries(extras).map(([room, choices]) => [
      room,
      Object.fromEntries(Object.entries(choices).map(([code, c]) => [code, fitChoice(c, stay)])),
    ]),
  )
}

export function asApiError(e: unknown): TexApiError {
  return e instanceof TexApiError ? e : new TexApiError(String((e as Error)?.message ?? e), 0, "Error")
}

/** After a failed validation, move keyboard focus to the first invalid control. */
export function focusFirstInvalid(root: ParentNode = document) {
  window.setTimeout(() => root.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(), 0)
}

type ChannelHotel = { name: string; sales_channels?: string[]; booking_channels?: string[] }

/**
 * Sales channels the user may sell on (price and book) at any of the `selected` hotels (every
 * hotel when none is selected), from the session (ADR-050). `null`: the session does not say
 * (an older server), so every channel is offered and the server decides.
 */
export function sellableChannels(hotels: ChannelHotel[], selected: string[] = []): string[] | null {
  if (hotels.some((h) => !h.sales_channels)) return null
  const pool = selected.length ? hotels.filter((h) => selected.includes(h.name)) : hotels
  const out = new Set<string>()
  for (const h of pool)
    for (const c of h.sales_channels ?? []) if (!h.booking_channels || h.booking_channels.includes(c)) out.add(c)
  return [...out].sort()
}

/** `preferred` when the user may sell on it at one of `hotels`, else the first channel they may. */
export function pickChannel(preferred: string | undefined, hotels: ChannelHotel[], selected: string[] = []): string {
  const allowed = sellableChannels(hotels, selected)
  if (!allowed || (preferred && allowed.includes(preferred))) return preferred ?? "CALL_CENTER"
  return allowed[0] ?? preferred ?? "CALL_CENTER"
}

/** A new search: tomorrow on the site's calendar (`today` from lib/siteDay, G-91), two nights. */
export function defaultSearchForm(today: string, properties: string[], channel = "CALL_CENTER"): SearchFormState {
  const ci = addDays(today, 1)
  return {
    check_in: ci,
    check_out: addDays(ci, 2),
    rooms: [{ adults: 2, children: [] }],
    market: "",
    channel,
    currency: "",
    promo: [],
    properties,
  }
}

export function emptyGuest(lang: string): GuestFormState {
  return {
    first_name: "",
    last_name: "",
    email: "",
    phone: "",
    special_requests: "",
    language: TEX_LANGS.some((l) => l.code === lang) ? lang : "en",
    consent_email: false,
    consent_sms: false,
    consent_whatsapp: false,
    crm_guest: null,
  }
}

const EMPTY_BOOKER: BookerFormState = { same: true, name: "", email: "", phone: "" }

function sameCodes(a: string[], b: string[]) {
  const x = [...new Set(a.map((c) => c.toUpperCase()))].sort().join(",")
  const y = [...new Set(b.map((c) => c.toUpperCase()))].sort().join(",")
  return x === y
}

function emailOk(s: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s.trim())
}

export function useBookingFlow(opts: { channel?: string } = {}) {
  const { boot } = useSession()
  const clock = useSiteClock()
  const { t, lang } = useTexT()
  const sellable = useMemo(
    () => boot.properties.filter((p) => p.capabilities.includes("price.view")),
    [boot.properties],
  )

  // the channel the page sells on, if the user may sell on it; else one they may (ADR-050)
  const defaultChannel = useMemo(() => pickChannel(opts.channel, sellable), [opts.channel, sellable])
  const [form, setForm] = useState<SearchFormState>(() =>
    defaultSearchForm(
      clock.today(),
      sellable.map((p) => p.name),
      defaultChannel,
    ),
  )
  const [formErrors, setFormErrors] = useState<FieldErrors>({})
  const [result, setResult] = useState<SearchResult>()
  const [lastArgs, setLastArgs] = useState<SearchArgs>()
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<TexApiError>()

  const [selection, setSelection] = useState<Selection | null>(null)
  const [extras, setExtras] = useState<RoomExtras>({})
  const [quotePromo, setQuotePromo] = useState<string[]>([])
  const [quotes, setQuotes] = useState<QuoteResult[]>([])
  const [quotedSig, setQuotedSig] = useState("")
  const [quoting, setQuoting] = useState(false)
  const [quoteError, setQuoteError] = useState<TexApiError>()

  const [methods, setMethods] = useState<PaymentMethod[]>()
  const [methodsError, setMethodsError] = useState<TexApiError>()
  const [method, setMethod] = useState("")
  const [summary, setSummary] = useState<QuoteSummary>()
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [summaryError, setSummaryError] = useState<TexApiError>()

  const [guest, setGuest] = useState<GuestFormState>(() => emptyGuest(lang))
  const [booker, setBooker] = useState<BookerFormState>(EMPTY_BOOKER)
  const [guestErrors, setGuestErrors] = useState<FieldErrors>({})
  const [confirmUnpaid, setConfirmUnpaid] = useState(false)
  const [notes, setNotes] = useState("")

  const [booking, setBooking] = useState<BookingSummary>()
  const [booking_pending, setBookingPending] = useState(false)
  const [bookError, setBookError] = useState<TexApiError>()
  const bookKey = useRef<string | null>(null)
  // The quote signature a booking was refused for with ExtraSoldOut although every room's
  // quote still adds its extras: each room is quoted alone, the booking counts the rooms
  // together (G-19). Booking the same quotes again would be refused the same way.
  const [extrasClash, setExtrasClash] = useState("")

  // ── lookups ──
  const propertyResult = useCallback(
    (prop: string | undefined): PropertyResult | undefined => result?.properties.find((p) => p.property === prop),
    [result],
  )
  const findOffer = useCallback(
    (prop: string | undefined, id: string | null | undefined): Offer | undefined => {
      const p = propertyResult(prop)
      if (!p || !id) return undefined
      return p.offers.find((o) => offerId(o) === id) ?? p.unavailable.find((o) => offerId(o) === id)
    },
    [propertyResult],
  )
  /** Offers that can take room `idx` of the party: priced for that room, not restricted, in
   * stock. `left` is the stock of the room type once the other rooms' picks are counted. */
  const roomCandidates = useCallback(
    (prop: string, idx: number, picks: (string | null)[] = []): { offer: Offer; room: OfferRoom; left: number }[] => {
      const p = propertyResult(prop)
      if (!p) return []
      const all = [...p.offers, ...p.unavailable]
      const typeOf = new Map(all.map((o) => [offerId(o), o.room_type]))
      const out: { offer: Offer; room: OfferRoom; left: number }[] = []
      for (const o of all) {
        const room = o.rooms.find((r) => r.room_index === idx)
        if (!room || !room.quote.sellable || o.restrictions.length || o.available < 1) continue
        const usedByOthers = picks.filter((id, j) => j !== idx && id && typeOf.get(id) === o.room_type).length
        out.push({ offer: o, room, left: o.available - usedByOthers })
      }
      return out
    },
    [propertyResult],
  )

  const roomCount = result?.rooms.length ?? form.rooms.length
  const selectedOffers = useMemo(
    () => (selection ? selection.picks.map((id) => findOffer(selection.property, id)) : []),
    [selection, findOffer],
  )
  const selectionComplete = Boolean(selection && selection.picks.length === roomCount && selection.picks.every(Boolean))

  const currentSig = useMemo(
    () => JSON.stringify({ selection, extras, promo: [...quotePromo].sort() }),
    [selection, extras, quotePromo],
  )
  const quotesOk = quotes.length > 0 && quotes.every((q) => q.ok && q.quote_id)
  const quoteStale = quotes.length > 0 && quotedSig !== currentSig
  const extrasTogether = !!extrasClash && extrasClash === quotedSig
  const quoteIds = useMemo(() => (quotesOk ? quotes.map((q) => q.quote_id as string) : []), [quotes, quotesOk])
  const quoteCurrency = quotesOk ? quotes[0].quote?.currency : selectedOffers[0]?.currency

  // ── validation ──
  const validateSearch = useCallback(
    (f: SearchFormState): FieldErrors => {
      const e: FieldErrors = {}
      if (!f.check_in) e.check_in = t("crs.err.check_in")
      else if (f.check_in < clock.today()) e.check_in = t("crs.err.check_in_past")
      if (!f.check_out) e.check_out = t("crs.err.check_out")
      else if (f.check_in && f.check_out <= f.check_in) e.check_out = t("crs.err.check_out_after")
      else if (f.check_in && nightsBetween(f.check_in, f.check_out) > 90) e.check_out = t("crs.err.too_long")
      if (!f.market) e.market = t("crs.err.market")
      if (!f.channel) e.channel = t("crs.err.channel")
      if (!f.properties.length) e.properties = t("crs.err.hotels")
      f.rooms.forEach((r, i) => {
        if (r.adults < 1) e[`room_${i}`] = t("crs.err.adults")
        r.children.forEach((a, k) => {
          if (a === null) e[`room_${i}_child_${k}`] = t("crs.err.child_age")
        })
      })
      if (!f.rooms.every(partyComplete) && !Object.keys(e).some((k) => k.startsWith("room_")))
        e.rooms = t("crs.err.child_age")
      return e
    },
    [t, clock],
  )

  // ── reset helpers ──
  const clearDownstream = useCallback(() => {
    setSelection(null)
    setExtras({})
    setQuotes([])
    setQuotedSig("")
    setQuoteError(undefined)
    setSummary(undefined)
    setSummaryError(undefined)
    setMethods(undefined)
    setMethod("")
    setConfirmUnpaid(false)
    setBooking(undefined)
    setBookError(undefined)
    setExtrasClash("")
    bookKey.current = null
  }, [])

  // ── search ──
  const runSearch = useCallback(
    async (override?: Partial<SearchFormState>, keepSelection = false): Promise<SearchResult | null> => {
      const f = { ...form, ...override }
      const errs = validateSearch(f)
      setFormErrors(errs)
      if (Object.keys(errs).length) return null
      const args: SearchArgs = {
        check_in: f.check_in,
        check_out: f.check_out,
        rooms: f.rooms.map(partyToApi),
        market: f.market,
        channel: f.channel,
        currency: f.currency || undefined,
        promo_codes: f.promo.length ? f.promo : undefined,
        properties: f.properties,
      }
      const prevSelection = selection
      setSearching(true)
      setSearchError(undefined)
      try {
        const r = await searchOffers(args)
        setResult(r)
        setLastArgs(args)
        const keep =
          keepSelection &&
          prevSelection &&
          prevSelection.picks.length === r.rooms.length &&
          prevSelection.picks.every((id) =>
            r.properties.some(
              (p) =>
                p.property === prevSelection.property &&
                [...p.offers, ...p.unavailable].some((o) => offerId(o) === id),
            ),
          )
        const oldExtras = extras
        clearDownstream()
        setQuotePromo(f.promo)
        if (keep && prevSelection) {
          setSelection(prevSelection)
          setExtras(fitExtras(oldExtras, { check_in: r.check_in, check_out: r.check_out }))
        }
        return r
      } catch (e) {
        setSearchError(asApiError(e))
        setResult(undefined)
        clearDownstream()
        return null
      } finally {
        setSearching(false)
      }
    },
    [form, validateSearch, selection, extras, clearDownstream],
  )

  // ── room builder ──
  /** Assign `offer` to every room of the party it fits (or only to `roomIndex`), never to
   * more rooms than its room type has left. The caller learns which rooms got it, which
   * it fits but are out of stock, and which it does not fit, and can quote straight away. */
  const selectOffer = useCallback(
    (prop: string, offer: Offer, roomIndex?: number): SelectResult => {
      const n = result?.rooms.length ?? 1
      const id = offerId(offer)
      const prev = selection
      const picks: (string | null)[] =
        prev && prev.property === prop && prev.picks.length === n ? [...prev.picks] : Array(n).fill(null)
      const p = propertyResult(prop)
      const typeOf = new Map([...(p?.offers ?? []), ...(p?.unavailable ?? [])].map((o) => [offerId(o), o.room_type]))
      const fits = (i: number) => offer.rooms.some((r) => r.room_index === i && r.quote.sellable)
      const targets = roomIndex === undefined ? [...Array(n).keys()] : [roomIndex]
      const unfit = targets.filter((i) => !fits(i))
      const wanted = targets.filter(fits)
      // stock of this room type already used by rooms that keep their pick
      let left = offer.available - picks.filter((pid, j) => pid && !wanted.includes(j) && typeOf.get(pid) === offer.room_type).length
      const assigned: number[] = []
      const noStock: number[] = []
      for (const i of wanted) {
        if (left > 0) {
          picks[i] = id
          assigned.push(i)
          left--
        } else {
          noStock.push(i)
          if (picks[i] && typeOf.get(picks[i]!) === offer.room_type) picks[i] = null
        }
      }
      const next = { property: prop, picks }
      if (assigned.length) {
        setSelection(next)
        if (!prev || prev.property !== prop) {
          setExtras({})
          setMethods(undefined)
          setMethod("")
          setQuotes([])
          setSummary(undefined)
        }
        setBooking(undefined)
      }
      return { selection: assigned.length ? next : prev, assigned, noStock, unfit }
    },
    [result, selection, propertyResult],
  )

  const setRoomPick = useCallback(
    (roomIndex: number, id: string | null) => {
      setSelection((prev) => {
        if (!prev) return prev
        const picks = [...prev.picks]
        picks[roomIndex] = id
        return { ...prev, picks }
      })
    },
    [],
  )

  /** Add, change or (null / quantity 0) remove an extra of a room. */
  const setExtra = useCallback((roomIndex: number, code: string, choice: ExtraChoice | null) => {
    setExtras((prev) => {
      const room = { ...(prev[roomIndex] ?? {}) }
      if (choice && choice.quantity > 0)
        room[code] = { quantity: Math.min(99, Math.floor(choice.quantity)), service_dates: [...new Set(choice.service_dates)].sort() }
      else delete room[code]
      const next = { ...prev, [roomIndex]: room }
      if (!Object.keys(room).length) delete next[roomIndex]
      return next
    })
  }, [])

  // ── limited extras (G-19): what is left per day of the stay, for the extras picker ──
  const [stock, setStock] = useState<{ key: string; data?: ExtrasAvailability; error?: TexApiError }>({ key: "" })
  const stockSeq = useRef(0)
  // crs.extras_availability needs price.view at the hotel (the server checks it too)
  const stockKey =
    selection && result && sellable.some((p) => p.name === selection.property)
      ? JSON.stringify([selection.property, result.check_in, result.check_out])
      : ""
  const loadExtrasStock = useCallback(async () => {
    if (!stockKey) return
    const [prop, ci, co] = JSON.parse(stockKey) as [string, string, string]
    const seq = ++stockSeq.current
    try {
      const data = await fetchExtrasAvailability(prop, ci, co)
      if (seq === stockSeq.current) setStock({ key: stockKey, data })
    } catch (e) {
      // keep what was loaded for this stay: the quote and the booking check the capacity anyway
      if (seq === stockSeq.current) setStock((s) => ({ key: stockKey, data: s.key === stockKey ? s.data : undefined, error: asApiError(e) }))
    }
  }, [stockKey])
  useEffect(() => {
    void loadExtrasStock()
  }, [loadExtrasStock])
  const extrasStock = stock.key === stockKey ? stock.data : undefined
  const extrasStockError = stock.key === stockKey ? stock.error : undefined

  // ── quotes ──
  const loadSummary = useCallback(async (ids: string[], m: string) => {
    if (!ids.length) return
    setSummaryLoading(true)
    try {
      const s = await quoteSummary(ids, m || undefined)
      setSummary(s)
      setSummaryError(undefined)
    } catch (e) {
      setSummaryError(asApiError(e))
    } finally {
      setSummaryLoading(false)
    }
  }, [])

  const requestQuotes = useCallback(
    async (sel: Selection | null = selection): Promise<QuoteResult[] | null> => {
      if (!sel || !sel.picks.every(Boolean)) return null
      setQuoting(true)
      setQuoteError(undefined)
      setSummary(undefined)
      setSummaryError(undefined)
      setBookError(undefined)
      setExtrasClash("")
      const promoChanged = !sameCodes(quotePromo, lastArgs?.promo_codes ?? [])
      // extras belong to a hotel: a selection that just moved hotel starts without any
      const roomExtras = sel.property === selection?.property ? extras : {}
      const sig = JSON.stringify({ selection: sel, extras: roomExtras, promo: [...quotePromo].sort() })
      try {
        const res = await Promise.all(
          sel.picks.map((id, i) => {
            const o = findOffer(sel.property, id)
            const room = o?.rooms.find((r) => r.room_index === i)
            if (!room) throw new TexApiError(t("crs.err.offer_missing"), 0, "Error")
            const ex: ExtraRequest[] = Object.entries(roomExtras[i] ?? {})
              .filter(([, c]) => c.quantity > 0)
              .map(([code, c]) =>
                c.service_dates.length ? { code, quantity: c.quantity, service_dates: c.service_dates } : { code, quantity: c.quantity },
              )
            return quoteOffer(room.offer_key, ex, promoChanged ? quotePromo : undefined)
          }),
        )
        // the summary (total, due now) follows from the effect on the quote ids
        setQuotes(res)
        setQuotedSig(sig)
        bookKey.current = null
        // what the other callers took meanwhile: the picker shows it next to each limited extra
        void loadExtrasStock()
        return res
      } catch (e) {
        setQuoteError(asApiError(e))
        setQuotes([])
        return null
      } finally {
        setQuoting(false)
      }
    },
    [selection, quotePromo, lastArgs, extras, findOffer, t, loadExtrasStock],
  )

  // payment methods for the selected hotel / market / currency / channel
  const selectedProperty = selection?.property
  useEffect(() => {
    if (!selectedProperty || !result || !quoteCurrency) return
    let live = true
    setMethodsError(undefined)
    fetchPaymentMethods(selectedProperty, result.market, quoteCurrency, result.channel)
      .then((m) => {
        if (!live) return
        setMethods(m)
        setMethod((cur) => (cur && m.some((x) => x.method === cur) ? cur : m.length === 1 ? m[0].method : ""))
      })
      .catch((e) => live && setMethodsError(asApiError(e)))
    return () => {
      live = false
    }
  }, [selectedProperty, result, quoteCurrency])

  // amount due depends on the payment method: ask the server again when it changes
  const idsKey = quoteIds.join(",")
  useEffect(() => {
    if (!idsKey) return
    void loadSummary(idsKey.split(","), method)
  }, [method, idsKey, loadSummary])

  // a new intent (anything that changes what gets booked) needs a new idempotency key
  useEffect(() => {
    bookKey.current = null
  }, [quotedSig, guest, booker, method, confirmUnpaid, notes])

  // ── guest / book ──
  const validateGuest = useCallback((): FieldErrors => {
    const e: FieldErrors = {}
    if (!guest.first_name.trim()) e.first_name = t("crs.err.first_name")
    if (!guest.last_name.trim()) e.last_name = t("crs.err.last_name")
    if (!guest.email.trim() && !guest.phone.trim()) e.contact = t("crs.err.contact")
    if (guest.email.trim() && !emailOk(guest.email)) e.email = t("crs.err.email")
    if (!booker.same) {
      if (!booker.name.trim()) e.booker_name = t("crs.err.booker_name")
      if (!booker.email.trim() && !booker.phone.trim()) e.booker_contact = t("crs.err.contact")
      if (booker.email.trim() && !emailOk(booker.email)) e.booker_email = t("crs.err.email")
    }
    return e
  }, [guest, booker, t])

  const applyGuest = useCallback(
    (row: GuestRow | null) => {
      if (!row) {
        setGuest((g) => ({ ...g, crm_guest: null }))
        return
      }
      const [first, ...rest] = (row.full_name || "").split(" ")
      setGuest((g) => ({
        ...g,
        first_name: row.first_name || first || "",
        last_name: row.last_name || rest.join(" ") || "",
        email: row.email || "",
        phone: row.phone || "",
        language: row.tex_language && TEX_LANGS.some((l) => l.code === row.tex_language) ? row.tex_language : g.language,
        crm_guest: row,
        // consent is only ever granted explicitly on this screen, never carried over
        consent_email: false,
        consent_sms: false,
        consent_whatsapp: false,
      }))
      setGuestErrors({})
    },
    [],
  )

  const payAtHotelBlocked = Boolean(method === "Pay at Hotel" && summary && !summary.pay_at_hotel_allowed)
  const canBook = Boolean(
    quotesOk &&
      !quoteStale &&
      summary &&
      summary.usable &&
      !summaryLoading &&
      !payAtHotelBlocked &&
      !extrasTogether &&
      (!methods?.length || method),
  )

  const book = useCallback(async (): Promise<BookingSummary | null> => {
    const errs = validateGuest()
    setGuestErrors(errs)
    if (Object.keys(errs).length) return null
    if (!quotesOk || quoteStale || extrasTogether) return null
    if (methods && methods.length && !method) {
      setGuestErrors({ method: t("crs.err.method") })
      return null
    }
    if (!bookKey.current) bookKey.current = idempotencyKey("crs")
    setBookingPending(true)
    setBookError(undefined)
    try {
      const out = await bookQuotes({
        quote_ids: quoteIds,
        guest: {
          first_name: guest.first_name.trim(),
          last_name: guest.last_name.trim(),
          email: guest.email.trim() || undefined,
          phone: guest.phone.trim() || undefined,
          special_requests: guest.special_requests.trim() || undefined,
          consent_email: guest.consent_email || undefined,
          consent_sms: guest.consent_sms || undefined,
          consent_whatsapp: guest.consent_whatsapp || undefined,
        },
        booker: booker.same
          ? null
          : { name: booker.name.trim(), email: booker.email.trim() || undefined, phone: booker.phone.trim() || undefined },
        payment_method: method || undefined,
        confirm_without_payment: confirmUnpaid && summary?.payment_required ? 1 : 0,
        notes: notes.trim() || undefined,
        idempotency_key: bookKey.current,
        language: guest.language,
      })
      setBooking(out)
      return out
    } catch (e) {
      const err = asApiError(e)
      if (err.type === "ExtraSoldOut") {
        // not a room sell-out: a limited extra (a spa slot…) went since the quote. Nothing was
        // booked; quote the rooms again so the refused extra shows as not added (not charged).
        const res = await requestQuotes()
        // no room's quote refuses an extra: each room alone fits, the rooms together need more
        // than is left. Not bookable again until the extras (or a fresh quote) change.
        const chosen = Object.values(extras).some((room) => Object.keys(room).length > 0)
        if (res && res.length > 1 && chosen && res.every((q) => q.ok && (q.quote?.extras ?? []).every((x) => x.ok)))
          setExtrasClash(currentSig)
      }
      setBookError(err)
      return null
    } finally {
      setBookingPending(false)
    }
  }, [validateGuest, quotesOk, quoteStale, extrasTogether, methods, method, t, quoteIds, guest, booker, confirmUnpaid, summary, notes, requestQuotes, currentSig, extras])

  const resetAll = useCallback(
    (keepSearch = false) => {
      clearDownstream()
      if (!keepSearch) {
        setForm(defaultSearchForm(clock.today(), sellable.map((p) => p.name), defaultChannel))
        setResult(undefined)
        setLastArgs(undefined)
        setFormErrors({})
        setSearchError(undefined)
        setQuotePromo([])
      }
      setGuest(emptyGuest(lang))
      setBooker(EMPTY_BOOKER)
      setGuestErrors({})
      setNotes("")
    },
    [clearDownstream, sellable, defaultChannel, lang, clock],
  )

  return {
    sellable,
    // search
    form,
    setForm,
    formErrors,
    setFormErrors,
    result,
    lastArgs,
    searching,
    searchError,
    runSearch,
    propertyResult,
    findOffer,
    roomCandidates,
    roomCount,
    // selection & quote
    selection,
    selectedOffers,
    selectionComplete,
    selectOffer,
    setRoomPick,
    extras,
    setExtra,
    extrasStock,
    extrasStockError,
    reloadExtrasStock: loadExtrasStock,
    quotePromo,
    setQuotePromo,
    quotes,
    quotesOk,
    quoteStale,
    quoting,
    quoteError,
    requestQuotes,
    quoteCurrency,
    // payment
    methods,
    methodsError,
    method,
    setMethod,
    summary,
    summaryLoading,
    summaryError,
    confirmUnpaid,
    setConfirmUnpaid,
    // guest
    guest,
    setGuest,
    booker,
    setBooker,
    guestErrors,
    setGuestErrors,
    applyGuest,
    notes,
    setNotes,
    // book
    payAtHotelBlocked,
    canBook,
    book,
    booking,
    bookingPending: booking_pending,
    bookError,
    /** The booking failed because a limited extra sold out; the rooms were quoted again. */
    extraSoldOut: bookError?.type === "ExtraSoldOut",
    /** Refused with ExtraSoldOut although no room's new quote refuses an extra: the rooms
     * together need more than is left (booking stays off until the rooms are quoted again). */
    extrasTogether,
    resetAll,
  }
}

export type BookingFlow = ReturnType<typeof useBookingFlow>
