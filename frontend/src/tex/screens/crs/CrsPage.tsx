import { useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { ArrowLeft, ArrowRight, Headphones, RotateCcw } from "lucide-react"
import { date, dateTime } from "../../lib/format"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import { Button, Card, CardBody, CardHeader, ErrorState, Money, Notice, PageHeader } from "../../ui"
import { cn } from "../../../lib/utils"
import { GuestForm, PaymentPicker } from "./components/CheckoutParts"
import { Confirmation } from "./components/Confirmation"
import { LiveRegion, Row } from "./components/controls"
import { OfferTitle } from "./components/OfferParts"
import { usePartyText } from "./components/PartyEditor"
import { QuoteControls, QuoteRoom, useExtras } from "./components/QuoteParts"
import { Results, RoomBuilder } from "./components/Results"
import { SearchForm } from "./components/SearchForm"
import { focusFirstInvalid, useBookingFlow, type BookingFlow } from "./lib/useBookingFlow"
import { useLabels } from "./lib/labels"
import type { Offer } from "./lib/types"

type Step = "search" | "quote" | "checkout" | "done"
const STEPS: Step[] = ["search", "quote", "checkout", "done"]

/** CRS: multi-hotel search → room builder → quote with extras → guest & payment → booking. */
export default function CrsPage() {
  const { t } = useTexT()
  const { can } = useSession()
  const flow = useBookingFlow({ channel: "CALL_CENTER" })
  const [step, setStep] = useState<Step>("search")
  const [announce, setAnnounce] = useState("")
  const heading = useRef<HTMLHeadingElement>(null)
  const firstField = useRef<HTMLInputElement>(null)
  const prop = flow.selection ? flow.propertyResult(flow.selection.property) : undefined
  const canCost = Boolean(flow.selection && can("price.view_cost", flow.selection.property))

  // move focus to the step heading so keyboard and screen-reader users land in context
  const go = (s: Step) => {
    setStep(s)
    window.setTimeout(() => heading.current?.focus(), 0)
  }

  const onSearch = async () => {
    const r = await flow.runSearch()
    if (r) setAnnounce(t("crs.results.announce", { count: r.properties.reduce((n, p) => n + p.offers.length, 0) }))
    else focusFirstInvalid()
  }

  const onSelect = async (property: string, offer: Offer) => {
    const sel = flow.selectOffer(property, offer)
    if (sel.picks.every(Boolean)) {
      go("quote")
      const res = await flow.requestQuotes(sel)
      if (res) setAnnounce(res.every((q) => q.ok) ? t("crs.quote.announce_ready") : t("crs.quote.not_sellable"))
    }
  }

  const onBook = async () => {
    const b = await flow.book()
    if (b) {
      go("done")
      setAnnounce(t("crs.done.announce", { ref: b.booking }))
    } else focusFirstInvalid()
  }

  // Ctrl/Cmd+Enter books from anywhere on the checkout step
  useEffect(() => {
    if (step !== "checkout") return
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault()
        if (flow.canBook && !flow.bookingPending) void onBook()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  })

  const reachable: Record<Step, boolean> = {
    search: step !== "done",
    quote: step !== "done" && flow.selectionComplete,
    checkout: step !== "done" && flow.quotesOk && !flow.quoteStale,
    done: step === "done",
  }

  return (
    <>
      <PageHeader
        title={t("core.nav.crs")}
        subtitle={t("crs.page.subtitle")}
        actions={
          <>
            {step !== "search" && step !== "done" && (
              <Button
                variant="ghost"
                icon={<RotateCcw className="size-4" aria-hidden />}
                onClick={() => {
                  flow.resetAll(true)
                  go("search")
                }}
              >
                {t("crs.page.start_over")}
              </Button>
            )}
            <Link
              to="/tex/crs/call-center"
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-zinc-300 bg-white px-3.5 text-sm font-medium text-zinc-800 shadow-sm hover:bg-zinc-50"
            >
              <Headphones className="size-4" aria-hidden />
              {t("core.nav.call_center")}
            </Link>
          </>
        }
      />
      <LiveRegion message={announce} />
      <Stepper step={step} reachable={reachable} onGo={go} />

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-5">
          <h2 ref={heading} tabIndex={-1} className="sr-only">
            {t(`crs.step.${step}`)}
          </h2>

          {step === "search" && (
            <>
              <Card>
                <CardBody>
                  <SearchForm
                    ref={firstField}
                    form={flow.form}
                    onChange={flow.setForm}
                    errors={flow.formErrors}
                    onSubmit={() => void onSearch()}
                    searching={flow.searching}
                    hotels={flow.sellable}
                  />
                </CardBody>
              </Card>
              {flow.searchError && (
                <Card>
                  <ErrorState error={flow.searchError} onRetry={() => void onSearch()} />
                </Card>
              )}
              <Results flow={flow} onSelect={(p, o) => void onSelect(p, o)} />
            </>
          )}

          {step === "quote" && <QuoteStep flow={flow} canCost={canCost} />}

          {step === "checkout" && (
            <>
              <Card>
                <CardHeader title={t("crs.guest.title")} description={t("crs.guest.subtitle")} />
                <CardBody>
                  <GuestForm flow={flow} canLookup={can("crm.view", flow.selection?.property)} />
                </CardBody>
              </Card>
              <Card>
                <CardHeader title={t("crs.pay.title")} />
                <CardBody>
                  <PaymentPicker flow={flow} canConfirmUnpaid={can("reservation.create", flow.selection?.property)} />
                </CardBody>
              </Card>
              <BookErrors flow={flow} onRequote={() => void flow.requestQuotes()} onSearchAgain={() => { void flow.runSearch(undefined, true); go("search") }} />
            </>
          )}

          {step === "done" && flow.booking && (
            <Confirmation
              booking={flow.booking}
              prop={prop}
              guestName={`${flow.guest.first_name} ${flow.guest.last_name}`.trim()}
              guestEmail={flow.guest.email || undefined}
              guestLanguage={flow.guest.language}
              onNew={() => {
                flow.resetAll(true)
                go("search")
                window.setTimeout(() => firstField.current?.focus(), 0)
              }}
            />
          )}
        </div>

        {step !== "done" && (
          <aside aria-label={t("crs.summary.title")} className="lg:sticky lg:top-20 lg:self-start">
            <SummaryCard flow={flow} step={step} onGo={go} onBook={() => void onBook()} />
          </aside>
        )}
      </div>
    </>
  )
}

function Stepper({ step, reachable, onGo }: { step: Step; reachable: Record<Step, boolean>; onGo: (s: Step) => void }) {
  const { t } = useTexT()
  const idx = STEPS.indexOf(step)
  return (
    <nav aria-label={t("crs.step.nav")}>
      <p className="text-sm font-medium text-zinc-700 sm:hidden">
        {t("crs.step.of", { n: idx + 1, total: STEPS.length })} · {t(`crs.step.${step}`)}
      </p>
      <ol className="hidden items-center gap-2 sm:flex">
        {STEPS.map((s, i) => {
          const current = s === step
          const done = i < idx
          return (
            <li key={s} className="flex items-center gap-2">
              {i > 0 && <span aria-hidden className="h-px w-6 bg-zinc-300" />}
              <button
                type="button"
                aria-current={current ? "step" : undefined}
                disabled={!reachable[s] || current}
                onClick={() => onGo(s)}
                className={cn(
                  "inline-flex items-center gap-2 rounded-full px-2.5 py-1 text-sm font-medium transition-colors",
                  current ? "bg-tex-600 text-white dark:text-zinc-50" : done ? "text-tex-700 hover:bg-tex-50" : "text-zinc-500",
                  "disabled:cursor-default",
                )}
              >
                <span
                  className={cn(
                    "grid size-5 place-items-center rounded-full text-xs",
                    current ? "bg-white/20" : done ? "bg-tex-100 text-tex-800" : "bg-zinc-200 text-zinc-600",
                  )}
                  aria-hidden
                >
                  {i + 1}
                </span>
                {t(`crs.step.${s}`)}
              </button>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

function QuoteStep({ flow, canCost }: { flow: BookingFlow; canCost: boolean }) {
  const { t } = useTexT()
  const prop = flow.selection ? flow.propertyResult(flow.selection.property) : undefined
  const extras = useExtras(flow.selection?.property)
  const rooms = flow.result?.rooms.length ?? 1
  return (
    <>
      {rooms > 1 && (
        <Card>
          <CardHeader title={t("crs.builder.title")} description={t("crs.builder.hint")} />
          <CardBody>
            <RoomBuilder flow={flow} />
          </CardBody>
        </Card>
      )}
      <Card>
        <CardHeader title={t("crs.quote.title")} description={t("crs.quote.subtitle")} />
        <CardBody className="space-y-6">
          {extras.error && <Notice tone="warning">{extras.error.message}</Notice>}
          {Array.from({ length: rooms }).map((_, i) => (
            <div key={i} className={cn(i > 0 && "border-t border-zinc-100 pt-5")}>
              <QuoteRoom flow={flow} index={i} prop={prop} canCost={canCost} extras={extras.data} />
            </div>
          ))}
          <div className="border-t border-zinc-100 pt-4">
            <QuoteControls flow={flow} />
          </div>
        </CardBody>
      </Card>
    </>
  )
}

export function BookErrors({ flow, onRequote, onSearchAgain }: { flow: BookingFlow; onRequote: () => void; onSearchAgain: () => void }) {
  const { t } = useTexT()
  if (!flow.bookError) return null
  if (flow.bookError.isPermission) return <Notice tone="danger" title={t("core.error.permission")}>{flow.bookError.message}</Notice>
  return (
    <Notice tone="danger" title={t("crs.book.failed")}>
      <p>{flow.bookError.message}</p>
      <p className="mt-1 text-xs">{t("crs.book.failed_hint")}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={onRequote} loading={flow.quoting}>
          {t("crs.book.requote")}
        </Button>
        <Button size="sm" variant="ghost" onClick={onSearchAgain}>
          {t("crs.quote.search_again")}
        </Button>
      </div>
    </Notice>
  )
}

function SummaryCard({ flow, step, onGo, onBook }: { flow: BookingFlow; step: Step; onGo: (s: Step) => void; onBook: () => void }) {
  const { t } = useTexT()
  const L = useLabels()
  const partyText = usePartyText()
  const r = flow.result
  const sel = flow.selection
  const prop = sel ? flow.propertyResult(sel.property) : undefined
  const offers = flow.selectedOffers
  // one offer for every room → the server's search total for the party applies as is
  const single = offers.length > 0 && offers.every((o) => o && o === offers[0]) ? offers[0] : undefined
  return (
    <Card>
      <CardHeader title={t("crs.summary.title")} description={prop ? prop.property_name : t("crs.summary.empty")} />
      <CardBody className="space-y-3">
        {r && (
          <div className="text-sm text-zinc-700">
            <p className="font-medium text-zinc-900">
              {date(r.check_in)} – {date(r.check_out)}
            </p>
            <p className="text-xs text-zinc-500">
              {t("core.label.nights", { count: r.nights })} · {r.market} · {L.channel(r.channel)}
            </p>
          </div>
        )}
        {sel && r && (
          <ul className="space-y-2">
            {r.rooms.map((party, i) => {
              const o = offers[i]
              const q = flow.quotes[i]
              return (
                <li key={i} className="text-sm">
                  <p className="text-xs font-medium text-zinc-500">
                    {t("crs.room_n", { n: i + 1 })} · {partyText(party.adults, party.children.map((c) => c.age))}
                  </p>
                  {o ? <OfferTitle offer={o} prop={prop} /> : <p className="text-zinc-500">{t("crs.builder.choose")}</p>}
                  {q?.ok && q.quote && !flow.quoteStale && (
                    <p className="text-right text-sm font-medium">
                      <Money amount={q.quote.totals.total} currency={q.quote.currency} />
                    </p>
                  )}
                </li>
              )
            })}
          </ul>
        )}
        <div className="border-t border-zinc-100 pt-2">
          {flow.summary && !flow.quoteStale ? (
            <>
              <Row strong label={t("crs.quote.total")} value={<Money amount={flow.summary.total} currency={flow.summary.currency} />} />
              {flow.summary.due_now !== null && flow.method && (
                <Row label={t("crs.pay.due_now")} value={<Money amount={flow.summary.due_now} currency={flow.summary.currency} />} />
              )}
              <p className="mt-1 text-xs text-zinc-500">{t("crs.quote.valid_until", { time: dateTime(flow.summary.expires_at) })}</p>
            </>
          ) : single?.total ? (
            <Row label={t("crs.summary.search_total")} value={<Money amount={single.total} currency={single.currency} />} />
          ) : (
            <p className="text-xs text-zinc-500">{t("crs.summary.total_after_quote")}</p>
          )}
        </div>
        {step === "search" && (
          <>
            {sel && (r?.rooms.length ?? 1) > 1 && (
              <div className="border-t border-zinc-100 pt-3">
                <p className="mb-2 text-xs font-semibold tracking-wide text-zinc-500 uppercase">{t("crs.builder.title")}</p>
                <RoomBuilder flow={flow} idPrefix="side" />
              </div>
            )}
            <Button
              className="w-full"
              disabled={!flow.selectionComplete}
              icon={<ArrowRight className="size-4" aria-hidden />}
              onClick={() => {
                onGo("quote")
                if (!flow.quotes.length || flow.quoteStale) void flow.requestQuotes()
              }}
            >
              {t("crs.summary.to_quote")}
            </Button>
          </>
        )}
        {step === "quote" && (
          <div className="flex gap-2">
            <Button variant="secondary" icon={<ArrowLeft className="size-4" aria-hidden />} onClick={() => onGo("search")}>
              {t("core.action.back")}
            </Button>
            <Button
              className="flex-1"
              disabled={!flow.quotesOk || flow.quoteStale || flow.quoting}
              icon={<ArrowRight className="size-4" aria-hidden />}
              onClick={() => onGo("checkout")}
            >
              {t("crs.summary.to_guest")}
            </Button>
          </div>
        )}
        {step === "checkout" && (
          <div className="flex gap-2">
            <Button variant="secondary" icon={<ArrowLeft className="size-4" aria-hidden />} onClick={() => onGo("quote")}>
              {t("core.action.back")}
            </Button>
            <Button className="flex-1" onClick={onBook} loading={flow.bookingPending} disabled={!flow.canBook} shortcut="Ctrl ↵">
              {t("crs.book.submit")}
            </Button>
          </div>
        )}
        {step === "checkout" && flow.payAtHotelBlocked && <p className="text-xs text-rose-700">{t("crs.pay.pah_not_allowed")}</p>}
      </CardBody>
    </Card>
  )
}
