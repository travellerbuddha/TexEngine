import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { ClipboardCopy, Keyboard, NotebookPen, PhoneCall, RefreshCw, Star, UserRound, X } from "lucide-react"
import { date, dateTime, money } from "../../lib/format"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  Dialog,
  EmptyState,
  ErrorState,
  IconButton,
  Kbd,
  Money,
  Notice,
  PageHeader,
  Skeleton,
  statusTone,
  Textarea,
  useToast,
} from "../../ui"
import { cn } from "../../../lib/utils"
import type { TexApiError } from "../../lib/api"
import { GuestForm, PaymentPicker } from "./components/CheckoutParts"
import { Confirmation } from "./components/Confirmation"
import { Disclosure, LiveRegion } from "./components/controls"
import { GuestLookup } from "./components/GuestLookup"
import { OfferBadges, OfferPrice, OfferTitle, PolicySummary, RoomFitNotes, roomName } from "./components/OfferParts"
import { usePartyText } from "./components/PartyEditor"
import { PriceBreakdown } from "./components/PriceBreakdown"
import { ExtraSoldOutNotice, ExtrasPicker, QuoteExpiry, roomExtras, roomStock, useExtras } from "./components/QuoteParts"
import { RoomBuilder } from "./components/Results"
import { SearchForm } from "./components/SearchForm"
import { guestProfile, logCall } from "./lib/api"
import { useLabels } from "./lib/labels"
import { copyText, offerId } from "./lib/party"
import { quoteText } from "./lib/quoteText"
import { normalisePromoCode } from "./lib/promoCode"
import { asApiError, focusFirstInvalid, useBookingFlow, type BookingFlow, type Selection } from "./lib/useBookingFlow"
import { roomList, selectMessage } from "./lib/selectText"
import { useServerClock } from "./lib/serverClock"
import type { GuestProfile, GuestRow, Offer, PropertyResult } from "./lib/types"

const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform)
const ALT = IS_MAC ? "⌥" : "Alt+"
const MOD = IS_MAC ? "⌘" : "Ctrl+"

/** Visible shortcut map (also the help dialog). */
const SHORTCUTS: { keys: string; action: string }[] = [
  { keys: `${ALT}N`, action: "crs.cc.key.new" },
  { keys: `${ALT}C`, action: "crs.cc.key.caller" },
  { keys: `${ALT}S`, action: "crs.cc.key.search" },
  { keys: `${ALT}R`, action: "crs.cc.key.results" },
  { keys: "↑ ↓", action: "crs.cc.key.move" },
  { keys: "↵", action: "crs.cc.key.quote" },
  { keys: "1–8", action: "crs.cc.key.room" },
  { keys: `${ALT}U`, action: "crs.cc.key.requote" },
  { keys: `${ALT}Q`, action: "crs.cc.key.copy" },
  { keys: `${ALT}G`, action: "crs.cc.key.guest" },
  { keys: `${ALT}P`, action: "crs.cc.key.payment" },
  { keys: `${ALT}M`, action: "crs.cc.key.notes" },
  { keys: `${MOD}↵`, action: "crs.cc.key.book" },
  { keys: "?", action: "crs.cc.key.help" },
]

interface CallEvent {
  at: Date
  text: string
}

interface ListItem {
  id: string
  prop: PropertyResult
  offer: Offer
  disabled: boolean
}

function isTyping(el: EventTarget | null) {
  const n = el as HTMLElement | null
  if (!n) return false
  const tag = n.tagName
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || n.isContentEditable
}

/** Call Center (R-25): one keyboard-first page for an agent on the phone. */
export default function CallCenterPage() {
  const { t } = useTexT()
  const L = useLabels()
  const toast = useToast()
  const { can } = useSession()
  const partyText = usePartyText()
  const clock = useServerClock()
  const flow = useBookingFlow({ channel: "CALL_CENTER" })

  const [caller, setCaller] = useState<GuestRow | null>(null)
  const [events, setEvents] = useState<CallEvent[]>([])
  const [callNotes, setCallNotes] = useState("")
  const [attachNotes, setAttachNotes] = useState(true)
  const [callStart, setCallStart] = useState(() => new Date())
  const [announce, setAnnounce] = useState("")
  const [help, setHelp] = useState(false)
  const [activeId, setActiveId] = useState<string>()
  const [selectNotice, setSelectNotice] = useState<{ tone: "info" | "warning"; text: string } | null>(null)

  const callerRef = useRef<HTMLInputElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const guestRef = useRef<HTMLInputElement>(null)
  const notesRef = useRef<HTMLTextAreaElement>(null)
  const payRef = useRef<HTMLDivElement>(null)
  const quoteRef = useRef<HTMLHeadingElement>(null)

  const log = useCallback((text: string) => setEvents((e) => [...e, { at: new Date(), text }]), [])

  // the call notes travel to the booking as its internal note (optional)
  const { setNotes } = flow
  useEffect(() => setNotes(attachNotes ? callNotes : ""), [attachNotes, callNotes, setNotes])

  const r = flow.result
  const rooms = r?.rooms.length ?? 1
  const items = useMemo<ListItem[]>(() => {
    if (!r) return []
    const out: ListItem[] = []
    for (const p of r.properties) {
      const sellHere = can("reservation.create", p.property)
      for (const o of p.offers) out.push({ id: `${p.property}::${offerId(o)}`, prop: p, offer: o, disabled: !sellHere })
      for (const o of p.unavailable) out.push({ id: `${p.property}::${offerId(o)}`, prop: p, offer: o, disabled: true })
    }
    return out
  }, [r, can])
  const enabled = useMemo(() => items.filter((i) => !i.disabled), [items])
  const active = items.find((i) => i.id === activeId)

  useEffect(() => {
    if (activeId) document.getElementById(`cc-opt-${cssId(activeId)}`)?.scrollIntoView({ block: "nearest" })
  }, [activeId])

  const selectedProp = flow.selection ? flow.propertyResult(flow.selection.property) : undefined
  const canCost = Boolean(flow.selection && can("price.view_cost", flow.selection.property))

  // ── actions ──
  const doSearch = useCallback(async () => {
    const res = await flow.runSearch()
    if (!res) {
      focusFirstInvalid()
      return
    }
    const count = res.properties.reduce((n, p) => n + p.offers.length, 0)
    setAnnounce(t("crs.results.announce", { count }))
    log(
      t("crs.cc.ev.search", {
        dates: `${date(res.check_in, "short")} – ${date(res.check_out, "short")}`,
        rooms: res.rooms.map((p) => partyText(p.adults, p.children.map((c) => c.age))).join(" + "),
        market: res.market,
        count,
      }),
    )
    const first = res.properties.flatMap((p) => p.offers.map((o) => `${p.property}::${offerId(o)}`))[0]
    setActiveId(first)
    window.setTimeout(() => listRef.current?.focus(), 0)
  }, [flow, t, log, partyText])

  const quoteSelection = useCallback(
    async (sel: Selection) => {
      const res = await flow.requestQuotes(sel)
      if (!res) return
      if (res.every((q) => q.ok)) {
        const p = flow.propertyResult(sel.property)
        const desc = res
          .map((q) =>
            q.quote ? `${roomName(p, q.quote.request.room_type)}, ${L.board(q.quote.request.board)} ${money(q.quote.totals.total, q.quote.currency)}` : "",
          )
          .join(" + ")
        setAnnounce(t("crs.quote.announce_ready"))
        log(t("crs.cc.ev.quote", { hotel: p?.property_name ?? sel.property, desc }))
      } else setAnnounce(t("crs.quote.not_sellable"))
    },
    [flow, t, log, L],
  )

  const chooseItem = useCallback(
    (item: ListItem | undefined, roomIndex?: number) => {
      if (!item || item.disabled) return
      const res = flow.selectOffer(item.prop.property, item.offer, roomIndex)
      const sel = res.selection
      if (sel && sel.property === item.prop.property && sel.picks.every(Boolean)) {
        setSelectNotice(null)
        void quoteSelection(sel)
        return
      }
      // rooms still open (offer fits some rooms only, or no stock left for all)
      const msg = selectMessage(t, res, item.offer, rooms)
      setSelectNotice(msg)
      if (msg) setAnnounce(msg.text)
    },
    [flow, quoteSelection, t, rooms],
  )

  const quoteCopy = useMemo(() => {
    if (!r || !flow.quotes.length || flow.quoteStale) return ""
    return quoteText({
      t,
      board: L.board,
      method: L.method,
      result: r,
      prop: selectedProp,
      quotes: flow.quotes,
      summary: flow.summary,
      paymentMethod: flow.method,
      partyText,
      time: clock.label,
    })
  }, [r, flow.quotes, flow.quoteStale, flow.summary, flow.method, selectedProp, t, L, partyText, clock])

  const copyQuote = useCallback(async () => {
    if (!quoteCopy) return
    if (await copyText(quoteCopy)) {
      toast.success(t("crs.cc.quote_copied"))
      log(t("crs.cc.ev.quote_given"))
    }
  }, [quoteCopy, toast, t, log])

  const doBook = useCallback(async () => {
    if (!flow.canBook || flow.bookingPending) return
    const b = await flow.book()
    if (b) {
      setAnnounce(t("crs.done.announce", { ref: b.booking }))
      log(t("crs.cc.ev.booked", { ref: b.booking, status: L.status(b.status) }))
      window.setTimeout(() => document.getElementById("crs-confirmation-title")?.focus(), 0)
    } else focusFirstInvalid()
  }, [flow, t, log, L])

  const newCall = useCallback(() => {
    flow.resetAll(false)
    setSelectNotice(null)
    setCaller(null)
    setEvents([])
    setCallNotes("")
    setAttachNotes(true)
    setActiveId(undefined)
    setCallStart(new Date())
    setAnnounce(t("crs.cc.new_call_started"))
    window.setTimeout(() => callerRef.current?.focus(), 0)
  }, [flow, t])

  const pickCaller = useCallback(
    (g: GuestRow) => {
      setCaller(g)
      flow.applyGuest(g)
      log(t("crs.cc.ev.caller", { name: g.full_name }))
      setAnnounce(t("crs.cc.caller_set", { name: g.full_name }))
    },
    [flow, log, t],
  )

  // ── global shortcuts ──
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // a dialog (payment link, shortcut help, command palette) owns the keyboard
      if (document.querySelector('[role="dialog"][aria-modal="true"]')) return
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key === "Enter") {
        e.preventDefault()
        void doBook()
        return
      }
      if (e.altKey && !e.ctrlKey && !e.metaKey) {
        const actions: Record<string, () => void> = {
          KeyN: newCall,
          KeyC: () => callerRef.current?.focus(),
          KeyS: () => void doSearch(),
          KeyR: () => listRef.current?.focus(),
          KeyU: () => void flow.requestQuotes(),
          KeyQ: () => void copyQuote(),
          KeyG: () => guestRef.current?.focus(),
          KeyP: () => payRef.current?.querySelector<HTMLInputElement>("input[type=radio]:not(:disabled)")?.focus(),
          KeyM: () => notesRef.current?.focus(),
        }
        const run = actions[e.code]
        if (run) {
          e.preventDefault()
          run()
        }
        return
      }
      if (e.key === "?" && !isTyping(e.target)) {
        e.preventDefault()
        setHelp(true)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [newCall, doSearch, flow, copyQuote, doBook])

  // ── results listbox keys ──
  const onListKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!enabled.length) return
    const idx = enabled.findIndex((i) => i.id === activeId)
    const move = (n: number) => {
      e.preventDefault()
      setActiveId(enabled[Math.max(0, Math.min(enabled.length - 1, n))].id)
    }
    if (e.key === "ArrowDown") move(idx < 0 ? 0 : idx + 1)
    else if (e.key === "ArrowUp") move(idx < 0 ? 0 : idx - 1)
    else if (e.key === "Home") move(0)
    else if (e.key === "End") move(enabled.length - 1)
    else if (e.key === "PageDown") move(idx + 5)
    else if (e.key === "PageUp") move(idx - 5)
    else if (e.key === "Enter" && !e.altKey && !e.ctrlKey && !e.metaKey) {
      e.preventDefault()
      chooseItem(active)
    } else if (/^[1-8]$/.test(e.key) && rooms > 1 && !e.altKey && !e.ctrlKey && !e.metaKey) {
      const n = Number(e.key) - 1
      if (n < rooms) {
        e.preventDefault()
        chooseItem(active, n)
      }
    }
  }

  return (
    <>
      <PageHeader
        title={t("core.nav.call_center")}
        subtitle={t("crs.cc.subtitle")}
        crumbs={[{ label: t("core.nav.crs"), to: "/tex/crs" }, { label: t("core.nav.call_center") }]}
        actions={
          <>
            <Button variant="ghost" icon={<Keyboard className="size-4" aria-hidden />} onClick={() => setHelp(true)} shortcut="?">
              {t("crs.cc.shortcuts")}
            </Button>
            <Button variant="secondary" icon={<PhoneCall className="size-4" aria-hidden />} onClick={newCall} shortcut={`${ALT}N`}>
              {t("crs.cc.new_call")}
            </Button>
          </>
        }
      />
      <LiveRegion message={announce} />
      <ShortcutStrip />

      {/* row 1: who is calling + the running call log; row 2: search/offers + quote/guest/book.
          DOM order = visual order = tab order (caller → notes → search → offers → quote → guest → book). */}
      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_26rem] xl:items-start">
        <CallerPanel caller={caller} onPick={pickCaller} onClear={() => setCaller(null)} inputRef={callerRef} />
        <div className="min-w-0">
          <Card>
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  <NotebookPen className="size-4 text-zinc-400" aria-hidden />
                  {t("crs.cc.notes")}
                  <Kbd>{ALT}M</Kbd>
                </span>
              }
            />
            <CardBody className="space-y-3">
              <label htmlFor="cc-notes" className="sr-only">
                {t("crs.cc.notes")}
              </label>
              <Textarea
                ref={notesRef}
                id="cc-notes"
                rows={4}
                value={callNotes}
                placeholder={t("crs.cc.notes_placeholder")}
                onChange={(e) => setCallNotes(e.target.value)}
              />
              <Checkbox label={t("crs.cc.attach_notes")} checked={attachNotes} onChange={(e) => setAttachNotes(e.target.checked)} />
              <CallSummary events={events} callStart={callStart} notes={callNotes} caller={caller} booking={flow.booking?.booking} />
            </CardBody>
          </Card>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_26rem]">
        {/* ── search + offers ── */}
        <div className="min-w-0 space-y-4">
          <Card>
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  {t("crs.search.title")} <Kbd>{ALT}S</Kbd>
                </span>
              }
            />
            <CardBody>
              <SearchForm
                ref={searchRef}
                form={flow.form}
                onChange={flow.setForm}
                errors={flow.formErrors}
                onSubmit={() => void doSearch()}
                searching={flow.searching}
                hotels={flow.sellable}
                variant="compact"
                marketHint={caller?.tex_market ? { code: caller.tex_market, label: caller.tex_market } : null}
                shortcut={`${ALT}S`}
                idPrefix="cc"
              />
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  {t("crs.results.title")} <Kbd>{ALT}R</Kbd>
                </span>
              }
              description={
                r
                  ? `${t("crs.results.offer_count", { count: enabled.length })} · ${t("crs.results.summary", {
                      from: date(r.check_in, "short"),
                      to: date(r.check_out, "short"),
                      nights: t("core.label.nights", { count: r.nights }),
                      market: r.market,
                    })}`
                  : t("crs.cc.results_hint")
              }
              actions={
                r && rooms > 1 ? (
                  <span className="text-xs text-zinc-500">
                    <Kbd>1</Kbd>–<Kbd>{Math.min(8, rooms)}</Kbd> {t("crs.cc.assign_room")}
                  </span>
                ) : undefined
              }
            />
            {flow.searchError ? (
              <ErrorState error={flow.searchError} onRetry={() => void doSearch()} />
            ) : flow.searching ? (
              <div className="space-y-2 p-4">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : !r ? (
              <EmptyState title={t("crs.cc.no_search")} description={t("crs.cc.no_search_hint")} />
            ) : items.length === 0 ? (
              <EmptyState title={t("crs.results.none")} />
            ) : (
              <OfferListbox
                listRef={listRef}
                flow={flow}
                items={items}
                activeId={activeId}
                onActive={setActiveId}
                onChoose={chooseItem}
                onKeyDown={onListKey}
                canCost={canCost}
              />
            )}
          </Card>
        </div>

        {/* ── quote, guest, payment, book ── */}
        <div className="min-w-0 space-y-4">
          <QuotePanel
            flow={flow}
            headingRef={quoteRef}
            canCost={canCost}
            quoteCopy={quoteCopy}
            onCopy={() => void copyQuote()}
            notice={selectNotice}
          />
          {flow.booking ? (
            <Confirmation
              compact
              booking={flow.booking}
              prop={selectedProp}
              guestName={`${flow.guest.first_name} ${flow.guest.last_name}`.trim()}
              guestEmail={flow.guest.email || undefined}
              guestLanguage={flow.guest.language}
              onNew={newCall}
              newShortcut={`${ALT}N`}
            />
          ) : (
            <Card>
              <CardHeader
                title={
                  <span className="flex items-center gap-2">
                    {t("crs.guest.title")} <Kbd>{ALT}G</Kbd>
                  </span>
                }
                description={caller ? t("crs.cc.guest_from_caller") : undefined}
              />
              <CardBody className="space-y-5">
                <GuestForm flow={flow} lookup={false} ref={guestRef} idPrefix="cc-g" />
                <div ref={payRef} className="border-t border-zinc-100 pt-4">
                  <p className="mb-2 flex items-center gap-2 text-sm font-semibold text-zinc-900">
                    {t("crs.pay.title")} <Kbd>{ALT}P</Kbd>
                  </p>
                  <PaymentPicker
                    flow={flow}
                    canConfirmUnpaid={can("reservation.confirm_unpaid", flow.selection?.property)}
                    idPrefix="cc-pay"
                    showNotes={false}
                  />
                </div>
                <BookBlock flow={flow} onBook={() => void doBook()} />
              </CardBody>
            </Card>
          )}
        </div>
      </div>

      <Dialog open={help} onClose={() => setHelp(false)} title={t("crs.cc.shortcuts")} description={t("crs.cc.shortcuts_hint")}>
        <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 text-sm">
          {SHORTCUTS.map((s) => (
            <div key={s.keys} className="contents">
              <dt>
                <Kbd>{s.keys}</Kbd>
              </dt>
              <dd className="text-zinc-700">{t(s.action)}</dd>
            </div>
          ))}
        </dl>
      </Dialog>
    </>
  )
}

function cssId(s: string) {
  return s.replace(/[^A-Za-z0-9_-]/g, "_")
}

function ShortcutStrip() {
  const { t } = useTexT()
  const shown = SHORTCUTS.filter((s) => !["1–8", "?"].includes(s.keys))
  return (
    <div className="hidden flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs text-zinc-600 md:flex" aria-hidden>
      {shown.map((s) => (
        <span key={s.keys} className="inline-flex items-center gap-1">
          <Kbd>{s.keys}</Kbd>
          {t(s.action)}
        </span>
      ))}
    </div>
  )
}

function CallerPanel({
  caller,
  onPick,
  onClear,
  inputRef,
}: {
  caller: GuestRow | null
  onPick: (g: GuestRow) => void
  onClear: () => void
  inputRef: React.RefObject<HTMLInputElement | null>
}) {
  const { t } = useTexT()
  const L = useLabels()
  const { can } = useSession()
  const clock = useServerClock()
  const [profile, setProfile] = useState<GuestProfile>()
  const [error, setError] = useState<TexApiError>()
  const canCrm = can("crm.view")
  useEffect(() => {
    setProfile(undefined)
    setError(undefined)
    if (!caller) return
    let live = true
    guestProfile(caller.name)
      .then((p) => live && setProfile(p))
      .catch((e) => live && setError(asApiError(e)))
    return () => {
      live = false
    }
  }, [caller])
  const today = clock.today()
  const stays = profile?.stays ?? []
  const open = stays.filter((s) => s.check_out_date >= today && !["Cancelled", "No Show", "Checked Out"].includes(s.status))
  const past = stays.filter((s) => !open.includes(s)).slice(0, 5)
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <UserRound className="size-4 text-zinc-400" aria-hidden />
            {t("crs.cc.caller")} <Kbd>{ALT}C</Kbd>
          </span>
        }
      />
      <CardBody className="grid gap-4 md:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
        {canCrm ? (
          <GuestLookup
            ref={inputRef}
            id="cc-caller"
            label={t("crs.cc.caller_lookup")}
            placeholder={t("crs.guest.lookup_placeholder")}
            hint={caller ? undefined : t("crs.cc.caller_hint")}
            onPick={onPick}
          />
        ) : (
          <p className="text-sm text-zinc-500">{t("crs.guest.lookup_denied")}</p>
        )}
        {!caller && canCrm && <p className="hidden self-center text-sm text-zinc-500 md:block">{t("crs.cc.caller_empty")}</p>}
        {caller && (
          <div className="min-w-0 space-y-3 rounded-lg border border-zinc-200 p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="flex items-center gap-1.5 font-semibold text-zinc-900">
                  <span className="truncate">{caller.full_name}</span>
                  {caller.vip ? <Star className="size-3.5 shrink-0 fill-amber-600 text-amber-600" aria-label={t("crs.guest.vip")} /> : null}
                </p>
                <p className="truncate text-xs text-zinc-600">{[caller.phone, caller.email].filter(Boolean).join(" · ")}</p>
                <p className="text-xs text-zinc-500">
                  {[caller.tex_market, caller.tex_language?.toUpperCase(), t("crs.guest.stays", { count: caller.tex_stays ?? 0 })]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
              <IconButton size="sm" label={t("crs.cc.clear_caller")} icon={<X className="size-4" />} onClick={onClear} />
            </div>
            {caller.blacklisted ? <Notice tone="danger">{t("crs.guest.blacklisted_note")}</Notice> : null}
            {error && !error.isPermission && <p className="text-xs text-rose-700">{error.message}</p>}
            {!profile && !error ? (
              <Skeleton className="h-16 w-full" />
            ) : profile ? (
              <>
                <div className="grid gap-3 sm:grid-cols-2">
                  <StayList title={t("crs.cc.open_bookings", { count: open.length })} stays={open} empty={t("crs.cc.no_open")} highlight L={L} />
                  <StayList title={t("crs.cc.history")} stays={past} empty={t("crs.cc.no_history")} L={L} />
                </div>
                {profile.guest.guest_notes ? (
                  <p className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-900">{profile.guest.guest_notes}</p>
                ) : null}
              </>
            ) : null}
          </div>
        )}
      </CardBody>
    </Card>
  )
}

function StayList({
  title,
  stays,
  empty,
  highlight,
  L,
}: {
  title: string
  stays: GuestProfile["stays"]
  empty: string
  highlight?: boolean
  L: ReturnType<typeof useLabels>
}) {
  return (
    <section>
      <h3 className="text-xs font-semibold tracking-wide text-zinc-500 uppercase">{title}</h3>
      {stays.length === 0 ? (
        <p className="text-xs text-zinc-500">{empty}</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {stays.map((s) => (
            <li key={s.name} className={cn("rounded px-1.5 py-1 text-xs", highlight && "bg-tex-50")}>
              <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5">
                <Link to={`/tex/reservations/${encodeURIComponent(s.name)}`} className="font-medium whitespace-nowrap text-tex-700 hover:underline">
                  {s.name}
                </Link>
                <Badge tone={statusTone(s.status)}>{L.status(s.status)}</Badge>
              </div>
              <p className="text-zinc-600">
                {date(s.check_in_date, "short")} – {date(s.check_out_date, "short")} · {s.property}
              </p>
              <p className="text-zinc-500">
                {L.board(s.tex_board)} · <Money amount={s.tex_total_amount} currency={s.tex_currency} />
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function CallSummary({
  events,
  callStart,
  notes,
  caller,
  booking,
}: {
  events: CallEvent[]
  callStart: Date
  notes: string
  caller: GuestRow | null
  booking?: string
}) {
  const { t } = useTexT()
  const toast = useToast()
  const { can } = useSession()
  const [saving, setSaving] = useState(false)
  const text = [
    t("crs.cc.summary_header", { time: dateTime(callStart) }),
    ...events.map((e) => `• ${e.text}`),
    ...(notes.trim() ? [`${t("crs.cc.notes")}: ${notes.trim()}`] : []),
  ].join("\n")
  const canLog = Boolean(caller && can("crm.edit"))
  return (
    <section aria-labelledby="cc-summary-h" className="space-y-2">
      <h3 id="cc-summary-h" className="text-xs font-semibold tracking-wide text-zinc-500 uppercase">
        {t("crs.cc.summary")}
      </h3>
      {events.length === 0 ? (
        <p className="text-xs text-zinc-500">{t("crs.cc.summary_empty")}</p>
      ) : (
        <ol className="space-y-1 text-xs text-zinc-700">
          {events.map((e, i) => (
            <li key={i} className="border-l-2 border-tex-200 pl-2">
              {e.text}
            </li>
          ))}
        </ol>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="secondary"
          icon={<ClipboardCopy className="size-4" aria-hidden />}
          disabled={!events.length && !notes.trim()}
          onClick={async () => (await copyText(text)) && toast.success(t("core.action.copied"))}
        >
          {t("crs.cc.copy_summary")}
        </Button>
        {canLog && (
          <Button
            size="sm"
            variant="ghost"
            loading={saving}
            disabled={!events.length && !notes.trim()}
            onClick={async () => {
              setSaving(true)
              try {
                await logCall({ guest: caller!.name, subject: t("crs.cc.log_subject"), body: text, booking })
                toast.success(t("crs.cc.logged"))
              } catch (e) {
                toast.error(asApiError(e).message)
              } finally {
                setSaving(false)
              }
            }}
          >
            {t("crs.cc.log_call")}
          </Button>
        )}
      </div>
    </section>
  )
}

function OfferListbox({
  listRef,
  flow,
  items,
  activeId,
  onActive,
  onChoose,
  onKeyDown,
  canCost,
}: {
  listRef: React.RefObject<HTMLDivElement | null>
  flow: BookingFlow
  items: ListItem[]
  activeId: string | undefined
  onActive: (id: string) => void
  onChoose: (item: ListItem) => void
  onKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => void
  canCost: boolean
}) {
  const { t } = useTexT()
  const r = flow.result!
  const rooms = r.rooms.length
  const groups = r.properties.map((p) => ({ p, items: items.filter((i) => i.prop.property === p.property) })).filter((g) => g.items.length)
  return (
    <div
      ref={listRef}
      role="listbox"
      tabIndex={0}
      aria-label={t("crs.cc.offer_list")}
      aria-activedescendant={activeId ? `cc-opt-${cssId(activeId)}` : undefined}
      onKeyDown={onKeyDown}
      onFocus={() => {
        if (!activeId) {
          const first = items.find((i) => !i.disabled)
          if (first) onActive(first.id)
        }
      }}
      className="max-h-[36rem] overflow-y-auto focus-visible:outline-offset-[-2px]"
    >
      {groups.map(({ p, items: gi }) => (
        <div key={p.property} role="group" aria-labelledby={`cc-grp-${cssId(p.property)}`}>
          <div
            id={`cc-grp-${cssId(p.property)}`}
            className="sticky top-0 z-[1] flex items-center justify-between border-b border-zinc-200 bg-zinc-50 px-4 py-1.5 text-xs font-semibold text-zinc-700"
          >
            <span>
              {p.property_name}
              {p.city ? <span className="font-normal text-zinc-500"> · {p.city}</span> : null}
            </span>
            {p.unplaced_rooms?.length ? (
              <span className="font-normal text-amber-800">{t("crs.results.unplaced_short", { count: p.unplaced_rooms.length, rooms: roomList(p.unplaced_rooms) })}</span>
            ) : p.messages.length ? (
              <span className="font-normal text-amber-800">{p.messages[0]}</span>
            ) : null}
          </div>
          {gi.map((item) => {
            const isActive = item.id === activeId
            const picked =
              flow.selection?.property === item.prop.property &&
              flow.selection.picks.map((id, idx) => (id === offerId(item.offer) ? idx + 1 : 0)).filter(Boolean)
            return (
              <div
                key={item.id}
                id={`cc-opt-${cssId(item.id)}`}
                role="option"
                aria-selected={isActive}
                aria-disabled={item.disabled || undefined}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onActive(item.id)
                  listRef.current?.focus()
                  onChoose(item)
                }}
                className={cn(
                  "cursor-pointer border-b border-zinc-100 px-4 py-2 last:border-0",
                  isActive && "bg-tex-50 ring-2 ring-tex-500 ring-inset",
                  item.disabled && "cursor-not-allowed opacity-60",
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 space-y-1">
                    <OfferTitle offer={item.offer} prop={item.prop} />
                    <OfferBadges offer={item.offer} rooms={rooms} />
                  </div>
                  <div className="shrink-0">
                    {item.offer.bookable ? (
                      <OfferPrice offer={item.offer} nights={r.nights} rooms={rooms} />
                    ) : (
                      <p className="max-w-48 text-right text-xs text-rose-800">
                        {(item.offer.reasons ?? item.offer.restrictions).map((x) => x.message).join("; ")}
                      </p>
                    )}
                    {picked && picked.length > 0 && (
                      <p className="mt-0.5 text-right">
                        <Badge tone="brand">{rooms > 1 ? t("crs.cc.in_rooms", { rooms: picked.join(", ") }) : t("crs.results.selected")}</Badge>
                      </p>
                    )}
                  </div>
                </div>
                {isActive && !item.disabled && (
                  <div className="mt-2 grid gap-2 border-t border-tex-200 pt-2 sm:grid-cols-2">
                    <PolicySummary rp={item.offer.rate_plan_info ?? item.offer.rooms[0]?.quote.rate_plan} currency={item.offer.currency} className="text-xs" />
                    <div className="text-xs text-zinc-600">
                      {rooms > 1 &&
                        item.offer.rooms.map((x) => (
                          <p key={x.room_index} className="flex justify-between gap-2">
                            <span>{t("crs.room_n", { n: x.room_index + 1 })}</span>
                            <Money amount={x.quote.totals.total} currency={x.quote.currency} />
                          </p>
                        ))}
                      {canCost && item.offer.rooms[0]?.quote.totals.margin !== undefined && (
                        <p className="flex justify-between gap-2">
                          <span>{t("crs.cost.margin")}</span>
                          <Money amount={item.offer.rooms[0].quote.totals.margin} currency={item.offer.currency} />
                        </p>
                      )}
                      <RoomFitNotes offer={item.offer} />
                      <p className="mt-1 text-zinc-500">
                        <Kbd>↵</Kbd> {rooms > 1 && !item.offer.complete ? t("crs.cc.key.assign_fitting") : t("crs.cc.key.quote")}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}

function QuotePanel({
  flow,
  headingRef,
  canCost,
  quoteCopy,
  onCopy,
  notice,
}: {
  flow: BookingFlow
  headingRef: React.RefObject<HTMLHeadingElement | null>
  canCost: boolean
  quoteCopy: string
  onCopy: () => void
  /** What the last offer assignment left open (multi-room). */
  notice: { tone: "info" | "warning"; text: string } | null
}) {
  const { t } = useTexT()
  const partyText = usePartyText()
  const prop = flow.selection ? flow.propertyResult(flow.selection.property) : undefined
  const extras = useExtras(flow.selection?.property)
  const r = flow.result
  const rooms = r?.rooms.length ?? 1
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-100 px-4 py-3">
        <h2 ref={headingRef} tabIndex={-1} className="text-sm font-semibold text-zinc-900">
          {t("crs.quote.title")}
        </h2>
        {flow.summary && !flow.quoteStale && (
          <span className="text-base font-semibold text-zinc-950">
            <Money amount={flow.summary.total} currency={flow.summary.currency} />
          </span>
        )}
      </div>
      <CardBody className="space-y-4">
        {!flow.selection ? (
          <p className="text-sm text-zinc-500">{t("crs.cc.quote_empty")}</p>
        ) : (
          <>
            {prop && <p className="text-xs font-medium text-zinc-500">{prop.property_name}</p>}
            {notice && !flow.selectionComplete && <Notice tone={notice.tone}>{notice.text}</Notice>}
            {rooms > 1 && <RoomBuilder flow={flow} idPrefix="cc-rb" />}
            {flow.quoting && <Skeleton className="h-24 w-full" />}
            {!flow.quoting &&
              Array.from({ length: rooms }).map((_, i) => {
                const q = flow.quotes[i]
                const party = r?.rooms[i]
                return (
                  <section key={i} className={cn("space-y-2", i > 0 && "border-t border-zinc-100 pt-3")} aria-label={t("crs.room_n", { n: i + 1 })}>
                    {rooms > 1 && (
                      <p className="text-xs font-semibold text-zinc-600">
                        {t("crs.room_n", { n: i + 1 })}
                        {party ? ` · ${partyText(party.adults, party.children.map((c) => c.age))}` : ""}
                      </p>
                    )}
                    {rooms === 1 && flow.selectedOffers[0] && <OfferTitle offer={flow.selectedOffers[0]} prop={prop} />}
                    {q && !q.ok && (
                      <Notice tone="danger" title={t("crs.quote.not_sellable")}>
                        {(q.reasons ?? []).map((x) => x.message).join("; ")}
                      </Notice>
                    )}
                    {q?.ok && q.quote && (
                      <>
                        {q.price_changed && <Notice tone="warning">{t("crs.quote.price_changed")}</Notice>}
                        <PriceBreakdown quote={q.quote} canCost={canCost} />
                      </>
                    )}
                    {!flow.booking && <Disclosure summary={t("crs.extras.title_count", { count: Object.keys(flow.extras[i] ?? {}).length })}>
                      <ExtrasPicker
                        extras={roomExtras(extras.data, i)}
                        value={flow.extras[i] ?? {}}
                        onChange={(code, c) => flow.setExtra(i, code, c)}
                        roomLabel={t("crs.room_n", { n: i + 1 })}
                        idPrefix={`cc-q${i}`}
                        {...roomStock(flow, i, extras.data)}
                      />
                    </Disclosure>}
                  </section>
                )
              })}
            {flow.summary && !flow.quoteStale && !flow.quoting && (
              <QuoteExpiry expiresAt={flow.summary.expires_at} onRequote={flow.booking ? undefined : () => void flow.requestQuotes()} />
            )}
            {!flow.booking && <PromoAndRequote flow={flow} />}
            {quoteCopy && (
              <div className="space-y-1.5 border-t border-zinc-100 pt-3">
                <div className="flex items-center justify-between gap-2">
                  <label htmlFor="cc-quote-text" className="text-xs font-semibold tracking-wide text-zinc-500 uppercase">
                    {t("crs.cc.quote_text")}
                  </label>
                  <Button size="sm" variant="ghost" icon={<ClipboardCopy className="size-4" aria-hidden />} onClick={onCopy} shortcut={`${ALT}Q`}>
                    {t("core.action.copy")}
                  </Button>
                </div>
                <Textarea id="cc-quote-text" readOnly rows={Math.min(10, quoteCopy.split("\n").length + 1)} value={quoteCopy} className="font-mono text-xs" />
              </div>
            )}
          </>
        )}
      </CardBody>
    </Card>
  )
}

function PromoAndRequote({ flow }: { flow: BookingFlow }) {
  const { t } = useTexT()
  return (
    <div className="space-y-2 border-t border-zinc-100 pt-3">
      <QuotePromo flow={flow} />
      {flow.quoteStale && <p className="text-xs text-amber-800">{t("crs.quote.stale")}</p>}
      {flow.quoteError && (
        <Notice tone="danger" title={t("crs.quote.failed")}>
          <p>{flow.quoteError.message}</p>
          <Button size="sm" variant="secondary" className="mt-2" onClick={() => void flow.runSearch(undefined, true)}>
            {t("crs.quote.search_again")}
          </Button>
        </Notice>
      )}
      <Button
        className="w-full"
        variant={flow.quoteStale || !flow.quotes.length ? "primary" : "secondary"}
        disabled={!flow.selectionComplete}
        loading={flow.quoting}
        icon={<RefreshCw className="size-4" aria-hidden />}
        onClick={() => void flow.requestQuotes()}
        shortcut={`${ALT}U`}
      >
        {flow.quotes.length ? t("crs.quote.update") : t("crs.quote.get")}
      </Button>
    </div>
  )
}

function QuotePromo({ flow }: { flow: BookingFlow }): ReactNode {
  const { t } = useTexT()
  return (
    <Disclosure summary={t("crs.quote.promo_count", { count: flow.quotePromo.length })}>
      <label htmlFor="cc-quote-promo" className="sr-only">
        {t("crs.quote.promo")}
      </label>
      <PromoInline flow={flow} />
    </Disclosure>
  )
}

function PromoInline({ flow }: { flow: BookingFlow }) {
  const { t } = useTexT()
  const [draft, setDraft] = useState("")
  const add = () => {
    const c = normalisePromoCode(draft)
    if (c && !flow.quotePromo.includes(c)) flow.setQuotePromo([...flow.quotePromo, c])
    setDraft("")
  }
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-1">
        {flow.quotePromo.map((c) => (
          <span key={c} className="inline-flex items-center gap-0.5 rounded-md bg-tex-50 py-0.5 pr-0.5 pl-1.5 text-xs font-semibold text-tex-800">
            {c}
            <button
              type="button"
              className="rounded p-0.5 hover:bg-tex-100"
              aria-label={t("crs.promo.remove", { code: c })}
              onClick={() => flow.setQuotePromo(flow.quotePromo.filter((x) => x !== c))}
            >
              <X className="size-3" aria-hidden />
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          id="cc-quote-promo"
          value={draft}
          autoComplete="off"
          onChange={(e) => setDraft(normalisePromoCode(e.target.value))}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault()
              add()
            }
          }}
          placeholder={t("crs.search.promo_placeholder")}
          className="h-8 min-w-0 flex-1 rounded-lg border border-zinc-300 bg-white px-2 text-sm uppercase placeholder:normal-case"
        />
        <Button size="sm" variant="secondary" onClick={add} disabled={!draft.trim()}>
          {t("crs.quote.add_code")}
        </Button>
      </div>
    </div>
  )
}

function BookBlock({ flow, onBook }: { flow: BookingFlow; onBook: () => void }) {
  const { t } = useTexT()
  return (
    <div className="space-y-2 border-t border-zinc-100 pt-4">
      {/* a limited extra sold out since the quote (not the room): re-quoted, the extra shows as not added */}
      {flow.extraSoldOut && <ExtraSoldOutNotice flow={flow} />}
      {flow.bookError && !flow.extraSoldOut && (
        <Notice tone="danger" title={flow.bookError.isPermission ? t("core.error.permission") : t("crs.book.failed")}>
          <p>{flow.bookError.message}</p>
          {!flow.bookError.isPermission && (
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" onClick={() => void flow.requestQuotes()} loading={flow.quoting}>
                {t("crs.book.requote")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => void flow.runSearch(undefined, true)}>
                {t("crs.quote.search_again")}
              </Button>
            </div>
          )}
        </Notice>
      )}
      {flow.payAtHotelBlocked && <p className="text-xs text-rose-700">{t("crs.pay.pah_not_allowed")}</p>}
      <Button className="w-full" size="lg" onClick={onBook} loading={flow.bookingPending} disabled={!flow.canBook} shortcut={`${MOD}↵`}>
        {t("crs.book.submit")}
      </Button>
      {!flow.quotesOk && <p className="text-center text-xs text-zinc-500">{t("crs.book.need_quote")}</p>}
    </div>
  )
}
