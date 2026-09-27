import { AlertTriangle, Building2, Check, CreditCard, Landmark, Lock, ShieldCheck } from "lucide-react"
import { useEffect, useId, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react"
import { useNavigate } from "react-router-dom"
import { useI18n, type MessageKey } from "../i18n"
import { pub } from "../lib/api"
import { extraAnchor, extraStock, refusalText, stayDays, type DayAvailability, type ExtrasAvailability } from "../lib/extras"
import { boardLabel, cancellation, paymentTerms } from "../lib/policy"
import { useBooking, type Step } from "../flow/BookingContext"
import { continuePayment } from "../flow/payment"
import { sitePath, siteRoute } from "../lib/mount"
import { Summary } from "../flow/Summary"
import { FlowErrorAlert, PriceChangeNotice, RejectedExtrasNotice, useBackToExtras, useContinue } from "../flow/useContinue"
import { rememberReturn, sessionId } from "../lib/storage"
import { useSite } from "../site/SiteContext"
import type { PaymentMethod, PaymentStart, QuoteResponse, SiteExtra } from "../types"
import { Badge, Button, Checkbox, Counter, Field, Input, Select, Textarea } from "../ui/controls"
import { Alert, ErrorSummary, Spinner, type FieldError } from "../ui/feedback"
import { isZero } from "../lib/format"
import { Photo } from "../ui/Photo"
import COUNTRIES from "./countries.json"

/** special_requests limit the server accepts */
const REQUESTS_MAX = 1000

// ─── progress ────────────────────────────────────────────────────────────

function Steps() {
  const { t } = useI18n()
  const { step, goStep, hasExtras } = useBooking()
  const steps: { id: Step; label: MessageKey }[] = [
    { id: "rooms", label: "steps.rooms" },
    ...(hasExtras ? [{ id: "extras" as Step, label: "steps.extras" as MessageKey }] : []),
    { id: "details", label: "steps.details" },
    { id: "payment", label: "steps.payment" },
  ]
  const current = steps.findIndex((s) => s.id === step)
  return (
    <nav aria-label={t("steps.label")} className="mb-5">
      <ol className="flex items-center gap-1.5 overflow-x-auto text-sm sm:gap-2">
        {steps.map((s, i) => {
          const done = i < current
          const here = i === current
          const content = (
            <>
              <span
                className={`grid size-6 flex-none place-items-center rounded-full text-xs font-bold ${here ? "bg-brand text-on-brand" : done ? "bg-ok text-white" : "bg-sunken text-muted"}`}
                aria-hidden
              >
                {done ? <Check className="size-3.5" /> : i + 1}
              </span>
              <span className={here ? "font-semibold text-ink" : `max-sm:sr-only ${done ? "text-soft" : "text-muted"}`}>{t(s.label)}</span>
            </>
          )
          return (
            <li key={s.id} className="flex flex-none items-center gap-1.5 sm:gap-2">
              {done ? (
                <button type="button" onClick={() => goStep(s.id)} className="inline-flex min-h-10 items-center gap-2 rounded-ui px-1 hover:underline">
                  {content}
                  <span className="sr-only">({t("steps.completed")})</span>
                </button>
              ) : (
                <span className="inline-flex min-h-10 items-center gap-2 px-1" aria-current={here ? "step" : undefined}>
                  {content}
                </span>
              )}
              {i < steps.length - 1 && <span className="h-px w-4 flex-none bg-line-strong sm:w-8" aria-hidden />}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

function StepHeading({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    ref.current?.focus({ preventScroll: true })
  }, [])
  return (
    <h1 ref={ref} tabIndex={-1} className="text-2xl outline-none sm:text-3xl">
      {children}
    </h1>
  )
}

// ─── extras ──────────────────────────────────────────────────────────────

const COUNTED = new Set(["UNIT", "USAGE"])

/** Per-day state of the hotel's limited extras for this stay (G-19). Null until known or
 * when it cannot be read: the extras then show as usual and the quote decides. */
function useExtrasAvailability(hotel: string, checkIn: string | null, checkOut: string | null, refreshKey: string) {
  const { site } = useSite()
  const [data, setData] = useState<ExtrasAvailability | null>(null)
  useEffect(() => {
    if (!hotel || !checkIn || !checkOut) return
    const ctl = new AbortController()
    pub<ExtrasAvailability>("extras_availability", { site: site.slug, hotel, check_in: checkIn, check_out: checkOut, session_id: sessionId() }, ctl.signal)
      .then((d) => setData(d && typeof d === "object" ? d : {}))
      .catch(() => undefined)
    return () => ctl.abort()
  }, [site.slug, hotel, checkIn, checkOut, refreshKey])
  return data
}

function ExtraItem({ extra, roomIndex, days }: { extra: SiteExtra; roomIndex: number; days?: Record<string, DayAvailability> }) {
  const i18n = useI18n()
  const { t, money, day } = i18n
  const { flow, setExtra, criteria, rejectedExtras } = useBooking()
  const choice = flow.extras[roomIndex]?.[extra.extra_code]
  const qty = choice?.quantity ?? 0
  const mode = extra.pricing_mode
  const modeKey = `extra.mode.${mode}` as MessageKey
  const mandatory = !!extra.is_mandatory
  const max = extra.max_quantity && extra.max_quantity > 0 ? extra.max_quantity : 9
  const counted = COUNTED.has(mode) || (extra.max_quantity ?? 0) > 1
  const id = useId()
  const stay = useMemo(() => stayDays(criteria.checkIn, criteria.checkOut), [criteria.checkIn, criteria.checkOut])
  // a chosen extra is used on its service date, else on arrival (as the server counts it)
  const chosenDay = choice ? choice.service_dates?.[0] ?? criteria.checkIn : null
  const stock = extraStock(mode, days, criteria.checkIn, criteria.checkOut, chosenDay)
  const soldOut = stock.soldOut && !mandatory
  const usedDay = chosenDay ?? stock.defaultDay
  const rejected = rejectedExtras.find((r) => r.room === roomIndex && r.code === extra.extra_code)
  // a limited extra is counted on one day of the stay: the guest may say which
  const pickDay = stock.oneDay && stay.length > 1 && qty > 0 && !soldOut && !mandatory

  const choose = (quantity: number) =>
    setExtra(
      roomIndex,
      extra.extra_code,
      quantity > 0 ? { code: extra.extra_code, quantity, ...(stock.oneDay && usedDay ? { service_dates: [usedDay] } : {}) } : null,
    )

  const price = (
    <p className="text-sm">
      <span className="font-semibold tabular-nums">{money(extra.amount, extra.currency)}</span>{" "}
      <span className="text-muted">{t(modeKey) !== modeKey ? t(modeKey) : ""}</span>
    </p>
  )
  let control: ReactNode
  if (mandatory) control = <p className="text-sm font-medium text-soft">{t("extras.mandatory")}</p>
  else if (soldOut)
    control = (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p className="text-sm text-muted">{t("extras.soldOutBody")}</p>
        {qty > 0 && (
          <Button size="sm" variant="ghost" onClick={() => setExtra(roomIndex, extra.extra_code, null)}>
            {t("extras.remove")}
            <span className="sr-only">: {extra.extra_name}</span>
          </Button>
        )}
      </div>
    )
  else if (mode === "SERVICE_DATE") {
    const dates = choice?.service_dates ?? []
    control = (
      <fieldset>
        <legend className="mb-1.5 text-sm font-medium text-soft">
          {t("extras.chooseDates")}
          <span className="sr-only"> · {extra.extra_name}</span>
        </legend>
        <div className="flex flex-wrap gap-2">
          {stay.map((d) => {
            const on = dates.includes(d)
            const a = stock.day(d)
            // a day no longer available stays removable when it was already chosen
            const locked = !a.available && !on
            const look = on
              ? a.available
                ? "border-brand-ink bg-brand/10 font-semibold"
                : "border-warn bg-warn-soft font-semibold"
              : locked
                ? "cursor-not-allowed border-line bg-sunken text-muted"
                : "border-line-strong"
            return (
              <label key={d} className={`inline-flex min-h-10 items-center gap-2 rounded-full border px-3 text-sm ${locked ? "" : "cursor-pointer"} ${look}`}>
                <input
                  type="checkbox"
                  className="bk-check"
                  checked={on}
                  disabled={locked}
                  onChange={(e) => {
                    const next = e.target.checked ? [...dates, d].sort() : dates.filter((x) => x !== d)
                    setExtra(roomIndex, extra.extra_code, next.length ? { code: extra.extra_code, quantity: 1, service_dates: next } : null)
                  }}
                />
                {day(d)}
                {!a.available ? (
                  <span className="text-xs font-medium">· {t("extras.soldOut")}</span>
                ) : a.low ? (
                  <span className="text-xs font-medium text-warn">· {t("extras.fewLeft")}</span>
                ) : null}
              </label>
            )
          })}
        </div>
      </fieldset>
    )
  } else if (counted)
    control = (
      <Counter
        label={t("extras.quantity")}
        value={qty}
        min={0}
        max={max}
        onChange={choose}
        decLabel={t("extras.less", { name: extra.extra_name })}
        incLabel={t("extras.more", { name: extra.extra_name })}
      />
    )
  else
    control = (
      <Checkbox
        id={id}
        label={
          <span className="font-medium text-ink">
            {qty ? t("extras.added") : t("extras.add")}
            <span className="sr-only">: {extra.extra_name}</span>
          </span>
        }
        checked={qty > 0}
        onChange={(v) => choose(v ? 1 : 0)}
      />
    )

  return (
    <li
      id={extraAnchor(roomIndex, extra.extra_code)}
      tabIndex={-1}
      className={`bk-card flex scroll-mt-20 gap-4 p-4 outline-none ${rejected ? "ring-2 ring-warn" : qty ? "ring-2 ring-brand-ink" : ""}`}
    >
      <Photo src={extra.image} alt="" className="hidden size-20 flex-none rounded-ui sm:grid" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
          <div className="min-w-0">
            <h3 className="text-base font-semibold">{extra.extra_name}</h3>
            {extra.category && <p className="text-xs text-muted">{extra.category}</p>}
            {soldOut ? (
              <Badge className="mt-1">{t("extras.soldOut")}</Badge>
            ) : (
              !mandatory && stock.low && <Badge tone="warn" className="mt-1">{t("extras.fewLeft")}</Badge>
            )}
          </div>
          {price}
        </div>
        {extra.description && <p className="mt-1 text-sm text-soft">{extra.description}</p>}
        {rejected && (
          <p className="mt-2 flex items-start gap-1.5 text-sm font-medium text-ink">
            <AlertTriangle className="mt-0.5 size-4 flex-none text-warn" aria-hidden />
            {refusalText(i18n, rejected.reason)}
          </p>
        )}
        <div className="mt-2">{control}</div>
        {pickDay && (
          <Field
            label={
              <>
                {t("extras.day")}
                <span className="sr-only"> · {extra.extra_name}</span>
              </>
            }
            className="mt-2 max-w-xs"
          >
            <Select value={usedDay ?? ""} onChange={(e) => setExtra(roomIndex, extra.extra_code, { code: extra.extra_code, quantity: qty, service_dates: [e.target.value] })}>
              {stay.map((d) => {
                const a = stock.day(d)
                const note = !a.available ? ` · ${t("extras.soldOut")}` : a.low ? ` · ${t("extras.fewLeft")}` : ""
                return (
                  <option key={d} value={d} disabled={!a.available && d !== usedDay}>
                    {`${day(d)}${note}`}
                  </option>
                )
              })}
            </Select>
          </Field>
        )}
      </div>
    </li>
  )
}

function ExtrasStep() {
  const { t } = useI18n()
  const { site } = useSite()
  const { criteria, flow, rejectedExtras } = useBooking()
  const { go, busy } = useContinue()
  const hotel = flow.selections[0]?.hotel ?? ""
  const extras = site.extras?.[hotel] ?? []
  const multi = criteria.rooms.length > 1
  // read again when a quote refuses an extra: what is left has changed
  const refused = rejectedExtras.map((r) => `${r.room}|${r.code}|${r.reason}`).join(",")
  const availability = useExtrasAvailability(hotel, criteria.checkIn, criteria.checkOut, refused)
  return (
    <StepLayout
      summary={
        <Summary
          action={
            <Button onClick={() => void go("extras")} busy={busy} block>
              {t("common.continue")}
            </Button>
          }
        />
      }
    >
      <div className="space-y-5">
        <div>
          <StepHeading>{t("extras.title")}</StepHeading>
          <p className="mt-1 text-soft">{t("extras.subtitle")}</p>
        </div>
        <FlowErrorAlert />
        <RejectedExtrasNotice />
        {criteria.rooms.map((_, i) => (
          <section key={i} aria-labelledby={multi ? `bk-extras-r${i}` : undefined} className="space-y-3">
            {multi && (
              <h2 id={`bk-extras-r${i}`} className="text-lg">
                {t("guests.room", { n: i + 1 })} · {flow.selections[i]?.roomName}
              </h2>
            )}
            <ul className="space-y-3">
              {/* a per-booking extra is charged once, on room 1 (ADR-029) */}
              {extras
                .filter((e) => i === 0 || e.pricing_mode !== "RESERVATION")
                .map((e) => (
                  <ExtraItem key={e.extra_code} extra={e} roomIndex={i} days={availability?.[e.extra_code] ?? availability?.[e.extra_code.toUpperCase()]} />
                ))}
            </ul>
          </section>
        ))}
        <p className="text-sm text-muted">{t("extras.priceNote")}</p>
        <div className="hidden justify-end lg:flex">
          <Button size="lg" onClick={() => void go("extras")} busy={busy}>
            {t("common.continue")}
          </Button>
        </div>
      </div>
    </StepLayout>
  )
}

// ─── guest details ───────────────────────────────────────────────────────

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/
const PHONE = /^\+?[\d\s().-]{6,20}$/

function DetailsStep() {
  const { t, locale } = useI18n()
  const { flow, setGuest, goStep } = useBooking()
  const g = flow.guest
  const [submitted, setSubmitted] = useState(false)
  const summaryRef = useRef<HTMLDivElement>(null)
  const base = useId()
  const ids = {
    first: `${base}-first`,
    last: `${base}-last`,
    email: `${base}-email`,
    phone: `${base}-phone`,
    country: `${base}-country`,
    requests: `${base}-requests`,
  }
  const countries = useMemo(() => {
    let names: Intl.DisplayNames | null = null
    try {
      names = new Intl.DisplayNames([locale], { type: "region" })
    } catch {
      /* old engines */
    }
    return Object.entries(COUNTRIES as Record<string, string>)
      .map(([code, name]) => ({ code, name, label: names?.of(code) ?? name }))
      .sort((a, b) => a.label.localeCompare(b.label, locale))
  }, [locale])
  // the server takes ISO 3166-1 alpha-2 codes; older saved forms may hold a country name
  const countryCode = g.country && !(g.country in COUNTRIES) ? countries.find((c) => c.name === g.country)?.code ?? "" : g.country

  const errors: FieldError[] = []
  if (!g.first_name.trim()) errors.push({ id: ids.first, message: t("details.errFirst") })
  if (!g.last_name.trim()) errors.push({ id: ids.last, message: t("details.errLast") })
  if (!EMAIL.test(g.email.trim())) errors.push({ id: ids.email, message: g.email.trim() ? t("details.errEmailFormat") : t("details.errEmail") })
  if (!g.phone.trim()) errors.push({ id: ids.phone, message: t("details.errPhone") })
  else if (!PHONE.test(g.phone.trim())) errors.push({ id: ids.phone, message: t("details.errPhoneFormat") })
  const errFor = (id: string) => (submitted ? errors.find((e) => e.id === id)?.message ?? null : null)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setSubmitted(true)
    if (errors.length) {
      requestAnimationFrame(() => summaryRef.current?.focus())
      return
    }
    goStep("payment")
  }

  return (
    <StepLayout
      summary={
        <Summary
          action={
            <Button onClick={() => document.getElementById("bk-details-submit")?.click()} block>
              {t("details.toPayment")}
            </Button>
          }
        />
      }
    >
      <form onSubmit={submit} noValidate className="space-y-6" aria-labelledby="bk-details-h">
        <div>
          <StepHeading>
            <span id="bk-details-h">{t("details.title")}</span>
          </StepHeading>
          <p className="mt-1 text-soft">{t("details.subtitle")}</p>
        </div>
        <PriceChangeNotice />
        <FlowErrorAlert />
        <RejectedExtrasNotice />
        {submitted && <ErrorSummary ref={summaryRef} title={t("details.errSummary", { count: errors.length })} errors={errors} />}
        <div className="bk-card space-y-4 p-4 sm:p-6">
          <h2 className="text-lg">{t("details.contact")}</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("details.firstName")} error={errFor(ids.first)} id={ids.first}>
              <Input value={g.first_name} onChange={(e) => setGuest({ first_name: e.target.value.slice(0, 140) })} autoComplete="given-name" required />
            </Field>
            <Field label={t("details.lastName")} error={errFor(ids.last)} id={ids.last}>
              <Input value={g.last_name} onChange={(e) => setGuest({ last_name: e.target.value.slice(0, 140) })} autoComplete="family-name" required />
            </Field>
            <Field label={t("details.email")} hint={t("details.emailHint")} error={errFor(ids.email)} id={ids.email}>
              <Input type="email" inputMode="email" value={g.email} onChange={(e) => setGuest({ email: e.target.value.slice(0, 140) })} autoComplete="email" required spellCheck={false} />
            </Field>
            <Field label={t("details.phone")} hint={t("details.phoneHint")} error={errFor(ids.phone)} id={ids.phone}>
              <Input type="tel" inputMode="tel" value={g.phone} onChange={(e) => setGuest({ phone: e.target.value.slice(0, 40) })} autoComplete="tel" required />
            </Field>
            <Field label={t("details.country")} optional={t("common.optional")} id={ids.country} className="sm:col-span-2">
              <Select value={countryCode} onChange={(e) => setGuest({ country: e.target.value })} autoComplete="country">
                <option value="">{t("details.selectCountry")}</option>
                {countries.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.label}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        </div>
        <div className="bk-card space-y-3 p-4 sm:p-6">
          <h2 className="text-lg">{t("details.requestsTitle")}</h2>
          <Field
            label={t("details.requests")}
            optional={t("common.optional")}
            hint={t("details.requestsHint", { count: REQUESTS_MAX - g.special_requests.length })}
            id={ids.requests}
          >
            <Textarea
              value={g.special_requests}
              onChange={(e) => setGuest({ special_requests: e.target.value.slice(0, REQUESTS_MAX) })}
              maxLength={REQUESTS_MAX}
              rows={4}
            />
          </Field>
        </div>
        <fieldset className="bk-card space-y-3 p-4 sm:p-6">
          <legend className="sr-only">{t("details.marketingTitle")}</legend>
          <h2 className="text-lg" aria-hidden>
            {t("details.marketingTitle")}
          </h2>
          <p className="text-sm text-muted">{t("details.marketingIntro")}</p>
          <Checkbox label={t("details.consentEmail")} checked={g.consent_email} onChange={(v) => setGuest({ consent_email: v })} />
          <Checkbox label={t("details.consentSms")} checked={g.consent_sms} onChange={(v) => setGuest({ consent_sms: v })} />
          <Checkbox label={t("details.consentWhatsapp")} checked={g.consent_whatsapp} onChange={(v) => setGuest({ consent_whatsapp: v })} />
          <p className="text-xs text-muted">{t("details.marketingNote")}</p>
        </fieldset>
        <div className="hidden justify-end lg:flex">
          <Button type="submit" size="lg">
            {t("details.toPayment")}
          </Button>
        </div>
        {/* phones: the bottom bar's button submits this form */}
        <button type="submit" id="bk-details-submit" hidden />
      </form>
    </StepLayout>
  )
}

// ─── payment ─────────────────────────────────────────────────────────────

const METHOD_ICON: Record<PaymentMethod, typeof CreditCard> = { Card: CreditCard, "Bank Transfer": Landmark, "Pay at Hotel": Building2 }
const METHOD_TEXT: Record<PaymentMethod, { label: MessageKey; body: MessageKey }> = {
  Card: { label: "payment.card", body: "payment.cardBody" },
  "Bank Transfer": { label: "payment.bank", body: "payment.bankBody" },
  "Pay at Hotel": { label: "payment.hotel", body: "payment.hotelBody" },
}
const KNOWN = new Set<string>(["Card", "Bank Transfer", "Pay at Hotel"])

interface PayChoice {
  method: PaymentMethod
  account: string | null
  /** gateway label when several accounts offer the same method */
  via: string | null
  dueNow: string | null
  later: string | null
  sandbox: boolean
}

function PaymentStep() {
  const i18n = useI18n()
  const { t, money } = i18n
  const { site } = useSite()
  const navigate = useNavigate()
  const b = useBooking()
  const { flow, criteria, setMethod, setTerms, quotesFresh, quoteAll, book, pending, setPending, setFlowError } = b
  const backToExtras = useBackToExtras()
  const [termsError, setTermsError] = useState(false)
  const [methodError, setMethodError] = useState<string | null>(null)
  const [redirecting, setRedirecting] = useState<PaymentStart | null>(null)
  const [blocked, setBlocked] = useState(false)
  const termsId = useId()
  const radioName = useId()
  const methodErrRef = useRef<HTMLDivElement>(null)

  // Methods and amounts come from the server basket (same deposit rules as booking);
  // if it cannot be read, fall back to the generic list and let book() decide.
  const basket = b.basket.status === "done" ? b.basket.data : null
  const basketLoading = b.basket.status === "loading" || (b.basket.status === "idle" && b.quotesFresh)
  const choices: PayChoice[] = useMemo(() => {
    if (basket) {
      const avail = basket.methods.filter((m) => m.available && KNOWN.has(m.method))
      return avail.map((m) => ({
        method: m.method as PaymentMethod,
        account: m.provider_account,
        via: avail.filter((x) => x.method === m.method).length > 1 ? m.label : null,
        dueNow: m.due_now,
        later: m.balance_after,
        sandbox: m.sandbox,
      }))
    }
    const payAtHotel = flow.selections.every((s) => s && paymentTerms(i18n, s.rateInfo, s.currency).payAtHotel)
    return (["Card", "Bank Transfer", ...(payAtHotel ? ["Pay at Hotel"] : [])] as PaymentMethod[]).map((m) => ({
      method: m,
      account: null,
      via: null,
      dueNow: null,
      later: null,
      sandbox: false,
    }))
  }, [basket, flow.selections, i18n])
  const current =
    choices.find((c) => c.method === flow.method && (!c.account || !flow.providerAccount || c.account === flow.providerAccount)) ?? choices[0] ?? null
  const method: PaymentMethod = current?.method ?? "Card"
  const currency = basket?.currency ?? flow.selections[0]?.currency ?? ""
  const payingNow = current?.dueNow ? !isZero(current.dueNow) : method !== "Pay at Hotel"
  const bookLabel = payingNow
    ? current?.dueNow
      ? t("payment.bookAndPayAmount", { amount: money(current.dueNow, currency) })
      : t("payment.bookAndPay")
    : t("payment.bookNow")

  useEffect(() => {
    if (current && (flow.method !== current.method || (current.account && flow.providerAccount !== current.account)))
      setMethod(current.method, current.account)
  }, [current, flow.method, flow.providerAccount, setMethod])

  // quotes used or expired since they were made: offer the refresh path
  useEffect(() => {
    if (basket && !basket.usable) setFlowError({ kind: "expired", message: "" })
  }, [basket, setFlowError])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setMethodError(null)
    // the booking refused this very choice of extras (the rooms together need more than is
    // left, e.g. back here through the browser history): back to the extras with the message
    if (b.extrasClash) {
      b.goStep("extras", { keepError: true })
      return setFlowError({ ...b.extrasClash })
    }
    if (!flow.terms) {
      setTermsError(true)
      document.getElementById(termsId)?.focus()
      return
    }
    setPending(true)
    setFlowError(null)
    // quotes older than the page keeps them are made again, and those are booked: this render's
    // flow still holds the old ones (O-30)
    let fresh: QuoteResponse[] | undefined
    if (!quotesFresh) {
      const { error, rejected, quotes, changes } = await quoteAll()
      if (error) {
        setPending(false)
        return setFlowError(error)
      }
      // an extra can no longer be added, or a price changed: the guest sees it (and the new total)
      // before booking; their next submit books the quotes just made (fresh, in the flow)
      if (rejected.length || changes.length) return setPending(false)
      fresh = quotes
    }
    const res = await book({ quotes: fresh })
    if (res.error) {
      // a limited extra ran out, not the room: back to the extras, never to the room search
      if (res.error.kind === "extra_sold_out") return void backToExtras(res.error)
      setPending(false)
      if (res.error.kind === "invalid" && /payment|pay|hotel/i.test(res.error.message)) {
        setMethodError(res.error.message)
        requestAnimationFrame(() => methodErrRef.current?.focus())
      } else setFlowError(res.error)
      return
    }
    const booking = res.booking!
    const confirmation = `confirmation/${encodeURIComponent(booking.booking)}`
    const p = res.payment
    if (p && (p.kind === "redirect" || p.kind === "form_post")) {
      rememberReturn(p.transaction, sitePath(site.slug, confirmation))
      setRedirecting(p)
      const outcome = continuePayment(p, navigate)
      if (outcome === "blocked") setBlocked(true)
      return
    }
    setPending(false)
    navigate(siteRoute(site.slug, confirmation), { replace: true })
  }

  if (redirecting)
    return (
      <div className="mx-auto max-w-lg py-10 text-center" role="status" aria-live="polite">
        <Lock className="mx-auto size-10 text-brand-ink" aria-hidden />
        <h1 className="mt-4 text-2xl">{t("payment.redirecting")}</h1>
        <p className="mt-2 text-soft">{t("payment.redirectingBody")}</p>
        {(blocked || redirecting.url) && (
          <p className="mt-6">
            <a href={redirecting.url ?? "#"} target={blocked ? "_top" : undefined} className="bk-btn bk-btn-primary bk-btn-lg">
              {t("payment.continueToPayment")}
            </a>
          </p>
        )}
      </div>
    )

  // arriving here without the earlier steps (e.g. a reload after booking) → start over
  if (!flow.guest.email || !b.allSelected)
    return <Alert tone="warn" title={t("payment.missingTitle")} actions={<Button onClick={() => b.goStep("rooms")}>{t("common.startAgain")}</Button>} />

  return (
    <StepLayout
      summary={
        <Summary
          action={
            <Button onClick={() => document.getElementById("bk-pay-submit")?.click()} busy={pending} disabled={!choices.length} block>
              {bookLabel}
            </Button>
          }
        />
      }
    >
      <form onSubmit={submit} noValidate className="space-y-6">
        <div>
          <StepHeading>{t("payment.title")}</StepHeading>
          <p className="mt-1 text-soft">{t("payment.subtitle")}</p>
        </div>
        <PriceChangeNotice />
        <FlowErrorAlert />
        <RejectedExtrasNotice />
        <section className="bk-card flex items-start justify-between gap-3 p-4 sm:px-6" aria-labelledby="bk-guest-review">
          <div className="min-w-0 text-sm">
            <h2 id="bk-guest-review" className="text-xs font-semibold uppercase tracking-wide text-muted">
              {t("payment.bookingFor")}
            </h2>
            <p className="mt-1 font-semibold">
              {flow.guest.first_name} {flow.guest.last_name}
            </p>
            <p className="truncate text-soft">{flow.guest.email}</p>
            <p className="text-soft">{flow.guest.phone}</p>
          </div>
          <Button variant="ghost" size="sm" onClick={() => b.goStep("details")} aria-label={t("payment.editDetails")}>
            {t("search.edit")}
          </Button>
        </section>
        <fieldset className="bk-card p-4 sm:p-6" aria-describedby={methodError ? `${radioName}-err` : undefined}>
          <legend className="sr-only">{t("payment.methodTitle")}</legend>
          <h2 className="text-lg" aria-hidden>
            {t("payment.methodTitle")}
          </h2>
          {methodError && (
            <div ref={methodErrRef} tabIndex={-1} id={`${radioName}-err`} className="mt-3 rounded-ui border border-bad/30 bg-bad-soft px-3 py-2 text-sm text-bad outline-none" role="alert">
              <p className="font-semibold">{t("payment.methodUnavailable")}</p>
              <p>{methodError}</p>
            </div>
          )}
          {basketLoading && !basket ? (
            <p className="mt-3">
              <Spinner label={t("payment.checkingOptions")} />
            </p>
          ) : !choices.length ? (
            <Alert tone="warn" className="mt-3" title={t("payment.noMethodsTitle")}>
              {t("payment.noMethodsBody")}
            </Alert>
          ) : (
            <div className="mt-3 space-y-2.5">
              {choices.map((c) => {
                const Icon = METHOD_ICON[c.method]
                const on = current === c
                return (
                  <label
                    key={`${c.method}|${c.account ?? ""}`}
                    className={`flex cursor-pointer items-start gap-3 rounded-ui border p-3.5 has-[:focus-visible]:outline-3 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-brand-ink ${on ? "border-brand-ink bg-brand/5 ring-1 ring-brand-ink" : "border-line hover:border-line-strong"}`}
                  >
                    <input
                      type="radio"
                      name={radioName}
                      value={`${c.method}|${c.account ?? ""}`}
                      checked={on}
                      onChange={() => setMethod(c.method, c.account)}
                      className="bk-check mt-0.5 rounded-full"
                    />
                    <Icon className="mt-0.5 size-5 flex-none text-soft" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block font-semibold">
                        {t(METHOD_TEXT[c.method].label)}
                        {c.via && <span className="font-normal text-muted"> · {c.via}</span>}
                      </span>
                      <span className="block text-sm text-muted">{t(METHOD_TEXT[c.method].body)}</span>
                      {c.dueNow !== null && (
                        <span className="mt-1 block text-sm">
                          {isZero(c.dueNow) ? (
                            <span className="font-medium text-ok">{t("payment.nothingNow")}</span>
                          ) : (
                            <span className="font-semibold">{t("payment.dueNowAmount", { amount: money(c.dueNow, currency) })}</span>
                          )}
                          {c.later && !isZero(c.later) && <span className="text-soft"> · {t("payment.laterAmount", { amount: money(c.later, currency) })}</span>}
                        </span>
                      )}
                    </span>
                  </label>
                )
              })}
            </div>
          )}
          {method === "Card" && (
            <p className="mt-3 flex items-start gap-2 text-sm text-soft">
              <ShieldCheck className="mt-0.5 size-4 flex-none text-ok" aria-hidden />
              {t("payment.cardSecurity")}
            </p>
          )}
        </fieldset>

        <section className="bk-card space-y-3 p-4 sm:p-6" aria-labelledby="bk-policies-h">
          <h2 id="bk-policies-h" className="text-lg">
            {t("payment.policiesTitle")}
          </h2>
          <ul className="space-y-3 text-sm">
            {flow.selections.map((s, i) =>
              s ? (
                <li key={i}>
                  <p className="font-semibold">
                    {criteria.rooms.length > 1 ? `${t("guests.room", { n: i + 1 })} · ` : ""}
                    {s.roomName} · {boardLabel(t, s.board)}
                    {s.ratePlanName ? ` · ${s.ratePlanName}` : ""}
                  </p>
                  <p className="text-soft">{cancellation(i18n, s.rateInfo, criteria.checkIn!).text}</p>
                  {method !== "Pay at Hotel" && <p className="text-soft">{paymentTerms(i18n, s.rateInfo, s.currency).text}</p>}
                  {s.rateInfo?.cancellation_policy?.description && <p className="text-xs text-muted">{s.rateInfo.cancellation_policy.description}</p>}
                </li>
              ) : null,
            )}
          </ul>
          {site.policies && (
            <details className="text-sm">
              <summary className="cursor-pointer font-medium text-brand-ink">{t("payment.hotelPolicies")}</summary>
              <p className="mt-2 whitespace-pre-line text-soft">{site.policies}</p>
            </details>
          )}
          <Checkbox
            id={termsId}
            label={t("payment.terms")}
            checked={flow.terms}
            onChange={(v) => {
              setTerms(v)
              if (v) setTermsError(false)
            }}
            error={termsError ? t("payment.termsRequired") : null}
            required
          />
        </section>

        <div className="hidden justify-end lg:flex">
          <Button type="submit" size="lg" busy={pending} disabled={!choices.length}>
            <Lock className="size-4" aria-hidden />
            {bookLabel}
          </Button>
        </div>
        <button type="submit" id="bk-pay-submit" hidden />
      </form>
    </StepLayout>
  )
}

export default function Checkout() {
  const { step, allSelected, goStep, hasExtras, flow, justBooked } = useBooking()
  const { t } = useI18n()
  // deep link or reload into a step whose earlier steps are missing → back to rooms
  const missing = !justBooked && (!allSelected || (step === "payment" && !flow.guest.email) || (step === "extras" && !hasExtras))
  useEffect(() => {
    if (missing) goStep("rooms", { replace: true })
  }, [missing, goStep])
  if (missing) return null
  const needsQuotes = (step === "details" || step === "payment") && flow.quotes.length !== flow.selections.length
  return (
    <div>
      <Steps />
      {needsQuotes && step === "details" && <QuoteOnArrival />}
      {step === "extras" && <ExtrasStep />}
      {step === "details" && <DetailsStep />}
      {step === "payment" && <PaymentStep />}
      {!["extras", "details", "payment"].includes(step) && <p>{t("common.loading")}</p>}
    </div>
  )
}

/** Step content with the booking summary beside it (sidebar on desktop, bottom bar on phones). */
function StepLayout({ children, summary }: { children: ReactNode; summary: ReactNode }) {
  return (
    <div className="grid gap-6 pb-28 lg:grid-cols-[minmax(0,1fr)_340px] lg:pb-0">
      <div className="min-w-0">{children}</div>
      {summary}
    </div>
  )
}

/** Details reached without quotes (e.g. back/forward): price the stay again quietly. */
function QuoteOnArrival() {
  const { quoteAll, setFlowError, setPending } = useBooking()
  const done = useRef(false)
  useEffect(() => {
    if (done.current) return
    done.current = true
    setPending(true)
    void quoteAll().then(({ error }) => {
      setPending(false)
      if (error) setFlowError(error)
    })
  }, [quoteAll, setFlowError, setPending])
  return null
}
