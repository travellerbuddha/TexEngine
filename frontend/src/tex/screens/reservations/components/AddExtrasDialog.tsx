import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react"
import { ArrowRight, Calculator, PackagePlus } from "lucide-react"
import type { TexApiError } from "../../../lib/api"
import { date, isoDay, money } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, Drawer, EmptyState, ErrorState, Field, Money, Notice, Select, Skeleton, Textarea, useToast } from "../../../ui"
import { cn } from "../../../../lib/utils"
import { NumberStepper } from "../../crs/components/controls"
import { ExplanationList } from "../../crs/components/OfferParts"
import {
  choicesToRequest,
  dayStock,
  isNightlyMode,
  isServiceDateMode,
  shortDay,
  stayDays,
  stayNights,
  tightest,
  unitsPerQuantity,
  usageDays,
  type DayStock,
  type ExtraChoice,
  type ExtrasAvailability,
  type Heads,
  type StayDates,
} from "../../crs/lib/extrasStock"
import { useLabels } from "../../crs/lib/labels"
import { isPositive } from "../../crs/lib/party"
import { useServerClock } from "../../crs/lib/serverClock"
import { asApiError } from "../../crs/lib/useBookingFlow"
import { addonApply, addonOptions, addonPropose } from "../lib/api"
import { addonReasonText } from "../lib/addons"
import type { AddonApplyResult, AddonOption, AddonOptions, AddonProposal, ReservationDetail } from "../lib/types"
import { AddonBreakdown } from "./AddonParts"

/** A proposal is signed for 30 minutes; re-price a little before rather than fail on apply. */
const PROPOSAL_TTL_MS = 30 * 60 * 1000 - 15_000
const SHORTCUT = "Ctrl ↵"

/** No answer, the server failed or was too busy: the extras may or may not have been added.
 * The proposal and its token are kept; adding it again is replayed, never added twice. */
function outcomeUnknown(e: TexApiError) {
  return e.status === 0 || e.status === 429 || e.status >= 500
}

/** The server refused the proposal, so nothing was added: it expired, the price moved, the
 * reservation changed or a limited extra ran out (ValidationError, HTTP 417). */
function refused(e: TexApiError) {
  return !e.isPermission && !outcomeUnknown(e) && (e.status === 417 || e.type === "ValidationError" || e.type === "ExtraSoldOut")
}

/**
 * Add extras to a booked stay (G-22, ADR-034). The stay stays price-locked: the extras are
 * priced on their own (the extra revision on sale now, no promotions) by crs.addon_propose,
 * shown next to the reservation's total, and added only when the agent confirms
 * (crs.addon_apply). The booking's balance grows by the add-on; it is paid like any balance.
 */
export function AddExtrasDialog({
  open,
  onClose,
  res,
  onApplied,
}: {
  open: boolean
  onClose: () => void
  res: ReservationDetail
  onApplied: (r: AddonApplyResult) => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const clock = useServerClock()
  const ids = useId()
  const formId = `${ids}-form`
  const [opts, setOpts] = useState<AddonOptions>()
  const [optsError, setOptsError] = useState<TexApiError>()
  const [loadTick, setLoadTick] = useState(0)
  const [choices, setChoices] = useState<Record<string, ExtraChoice>>({})
  const [proposal, setProposal] = useState<AddonProposal>()
  const [proposedSig, setProposedSig] = useState("")
  const [proposedAt, setProposedAt] = useState(0)
  const [proposing, setProposing] = useState(false)
  const [proposeError, setProposeError] = useState<TexApiError>()
  const [showMissing, setShowMissing] = useState(false)
  const [reason, setReason] = useState("")
  const [applying, setApplying] = useState(false)
  /** Why the last "Add" did not go through (the extras were priced again below). */
  const [applyError, setApplyError] = useState<TexApiError>()
  const [expired, setExpired] = useState(false)
  const resultRef = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    if (!open) {
      // cleared on close, so a new opening never shows (or focuses) the last list
      setOpts(undefined)
      return
    }
    setChoices({})
    setProposal(undefined)
    setProposedSig("")
    setProposeError(undefined)
    setShowMissing(false)
    setReason("")
    setApplyError(undefined)
    setExpired(false)
  }, [open])

  // what can be added now; reloaded (without clearing the list) after a refused apply
  useEffect(() => {
    if (!open) return
    const ctl = new AbortController()
    setOptsError(undefined)
    addonOptions(res.name, ctl.signal)
      .then(setOpts)
      .catch((e: unknown) => {
        if ((e as Error)?.name !== "AbortError") setOptsError(asApiError(e))
      })
    return () => ctl.abort()
  }, [open, res.name, loadTick])

  // once the list is there, start on the first quantity (unless the agent already moved on)
  const formRef = useRef<HTMLFormElement>(null)
  const focused = useRef(false)
  useEffect(() => {
    if (!open) {
      focused.current = false
      return
    }
    if (!opts || focused.current) return
    focused.current = true
    const active = document.activeElement
    const panel = formRef.current?.closest<HTMLElement>("[role=dialog]")
    if (panel && active && panel.contains(active) && active.tagName !== "BUTTON" && active !== panel) return
    formRef.current?.querySelector<HTMLInputElement>("input[type=number]:not([disabled])")?.focus()
  }, [open, opts])

  const stay: StayDates | undefined = opts ? { check_in: opts.check_in, check_out: opts.check_out } : undefined
  const heads: Heads = { adults: res.adults, children: res.children }
  const extras = useMemo(() => opts?.extras ?? [], [opts])
  const request = useMemo(() => choicesToRequest(choices).sort((a, b) => a.code.localeCompare(b.code)), [choices])
  const sig = JSON.stringify(request)
  const stale = Boolean(proposal && proposedSig !== sig)
  const count = request.length
  const missingDays = extras.filter((x) => isServiceDateMode(x.pricing_mode) && (choices[x.code]?.quantity ?? 0) > 0 && !choices[x.code].service_dates.length)
  const fresh = Boolean(proposal && !stale && proposal.ok && proposal.proposal_token)
  /** the last "Add" may or may not have gone through */
  const unknown = Boolean(applyError && outcomeUnknown(applyError))
  const canApply = fresh && !applying && !proposing

  /** The first day an extra can still be ordered for (server clock and the extra's cut-off). */
  const earliest = (hours: number) => {
    const today = clock.today()
    if (!hours) return today
    const d = isoDay(new Date(clock.now().getTime() + hours * 3_600_000))
    return d > today ? d : today
  }

  const propose = async (after?: { error?: TexApiError; expired?: boolean }) => {
    if (!count || proposing) return
    if (missingDays.length) {
      setShowMissing(true)
      document.getElementById(`${ids}-x-${missingDays[0].code}-days`)?.querySelector<HTMLInputElement>("input:not([disabled])")?.focus()
      return
    }
    // after an "Add" without an answer the extras may be in the reservation already: show what it has
    if (unknown) setLoadTick((n) => n + 1)
    setProposing(true)
    setProposeError(undefined)
    setApplyError(after?.error)
    setExpired(Boolean(after?.expired))
    try {
      const p = await addonPropose(res.name, request)
      setProposal(p)
      setProposedSig(sig)
      setProposedAt(Date.now())
      window.setTimeout(() => {
        resultRef.current?.focus({ preventScroll: true })
        resultRef.current?.scrollIntoView({ block: "start", behavior: "smooth" })
      }, 50)
    } catch (e) {
      setProposeError(asApiError(e))
      setProposal(undefined)
    } finally {
      setProposing(false)
    }
  }

  const apply = async () => {
    if (!proposal?.proposal_token || !canApply) return
    // after an unknown outcome the same token is sent again (the server replays it), never re-priced
    if (!unknown && Date.now() - proposedAt > PROPOSAL_TTL_MS) {
      // the signed price is about to expire: price again and let the agent confirm again
      void propose({ expired: true })
      return
    }
    setApplying(true)
    setApplyError(undefined)
    setExpired(false)
    try {
      const r = await addonApply(proposal.proposal_token, reason.trim() || undefined)
      const total = money(r.total, r.currency)
      if (r.replay) toast.info(t("res.addon.replayed", { name: r.reservation }))
      else if (r.balance && isPositive(r.balance))
        toast.success(t("res.addon.done_balance", { name: r.reservation, total, balance: money(r.balance, r.currency) }))
      else toast.success(t("res.addon.done", { name: r.reservation, total }))
      onApplied(r)
    } catch (e) {
      const err = asApiError(e)
      if (refused(err)) {
        // expired, the price moved, the reservation changed or sold out: nothing was added —
        // price again (with fresh availability) and let the agent confirm again
        setLoadTick((n) => n + 1)
        void propose(/expired/i.test(err.message) ? { expired: true } : { error: err })
      } else {
        // no answer, a server failure or busy (the outcome is unknown), no right, or another
        // error: keep the proposal and its token — applying it again never adds twice
        setApplyError(err)
      }
    } finally {
      setApplying(false)
    }
  }

  // Ctrl/⌘ + Enter: add when a fresh price is shown, otherwise price the selection
  const shortcutRef = useRef<() => void>(() => undefined)
  shortcutRef.current = () => {
    if (canApply) void apply()
    else if (count && !proposing && !applying) void propose()
  }
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key === "Enter") {
        e.preventDefault()
        shortcutRef.current()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open])

  const setChoice = (code: string, c: ExtraChoice | null) => {
    setChoices((prev) => {
      const next = { ...prev }
      if (c && c.quantity > 0) next[code] = { quantity: c.quantity, service_dates: [...new Set(c.service_dates)].sort() }
      else delete next[code]
      return next
    })
  }

  const p = proposal
  return (
    <Drawer
      open={open}
      onClose={applying ? () => undefined : onClose}
      width="lg"
      title={t("res.addon.title", { name: res.name })}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={applying}>
            {t("core.action.cancel")}
          </Button>
          <Button
            type="submit"
            form={formId}
            variant={fresh ? "secondary" : "primary"}
            icon={<Calculator className="size-4" aria-hidden />}
            loading={proposing}
            disabled={!count || applying}
            shortcut={fresh ? undefined : SHORTCUT}
          >
            {p ? t("res.addon.reprice") : t("res.addon.price")}
          </Button>
          {fresh && (
            <Button icon={<PackagePlus className="size-4" aria-hidden />} onClick={() => void apply()} loading={applying} disabled={!canApply} shortcut={SHORTCUT}>
              {t("res.addon.confirm")}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-6">
        <Notice tone="info">{t("res.addon.intro")}</Notice>

        <form
          ref={formRef}
          id={formId}
          noValidate
          aria-labelledby={`${ids}-choose`}
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault()
            void propose()
          }}
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 id={`${ids}-choose`} className="text-sm font-semibold text-zinc-900">
              {t("res.addon.choose")} {count > 0 && <Badge tone="brand">{t("res.addon.selected", { count })}</Badge>}
            </h3>
            {stay && <p className="text-xs text-zinc-500">{t("res.addon.stay", { from: date(stay.check_in), to: date(stay.check_out) })}</p>}
          </div>
          {optsError && !opts ? (
            <ErrorState error={optsError} onRetry={() => setLoadTick((n) => n + 1)} />
          ) : !opts || !stay ? (
            <div className="space-y-2" aria-busy="true">
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
            </div>
          ) : !extras.length ? (
            <EmptyState icon={<PackagePlus className="size-5" />} title={t("res.addon.none")} description={t("res.addon.none_hint")} />
          ) : (
            <ul className="divide-y divide-zinc-100">
              {extras.map((x) => (
                <AddonRow
                  key={x.code}
                  x={x}
                  choice={choices[x.code]}
                  onChange={(c) => setChoice(x.code, c)}
                  id={`${ids}-x-${x.code}`}
                  stay={stay}
                  heads={heads}
                  earliest={earliest(x.cutoff_hours)}
                  showMissing={showMissing}
                />
              ))}
            </ul>
          )}
        </form>

        <section aria-labelledby={`${ids}-result`} className="scroll-mt-4 space-y-4">
          <h3 id={`${ids}-result`} ref={resultRef} tabIndex={-1} className="text-sm font-semibold text-zinc-900 focus:outline-none">
            {t("res.addon.result")}
          </h3>
          {expired && <Notice tone="warning">{t("res.addon.expired")}</Notice>}
          {applyError && (
            <Notice tone="danger" title={applyError.isPermission ? t("core.error.permission") : unknown ? t("res.addon.unknown") : t("res.addon.failed")}>
              <p className="whitespace-pre-line">{applyError.message}</p>
              {(unknown || refused(applyError)) && <p className="mt-1 text-xs">{unknown ? t("res.addon.network_hint") : t("res.addon.repriced")}</p>}
            </Notice>
          )}
          {proposeError && (
            <Notice tone="danger" title={proposeError.isPermission ? t("core.error.permission") : t("res.addon.price_failed")}>
              <p className="whitespace-pre-line">{proposeError.message}</p>
            </Notice>
          )}
          {!p && !proposeError && <p className="text-sm text-zinc-500">{t("res.addon.result_hint")}</p>}
          {p && (
            <div className={cn("space-y-4", stale && "opacity-60")} aria-live="polite">
              {stale && (
                <Notice tone="warning">
                  {t("res.addon.stale")}{" "}
                  <button type="button" className="font-medium underline" onClick={() => void propose()}>
                    {t("res.addon.reprice")}
                  </button>
                </Notice>
              )}
              {!p.ok ? (
                <Notice tone="danger" title={t("res.addon.refused")}>
                  <ul className="list-disc pl-4">
                    {p.reasons.map((r, i) => (
                      <li key={i}>{addonReasonText(t, r)}</li>
                    ))}
                  </ul>
                </Notice>
              ) : (
                <>
                  <TotalsStrip p={p} />
                  <div className="rounded-lg border border-tex-200 bg-tex-50/40 p-3">
                    <p className="mb-2 text-xs font-semibold tracking-wide text-tex-800 uppercase">{t("res.addon.priced")}</p>
                    <AddonBreakdown quote={p.addon} />
                  </div>
                  <p className="text-xs text-zinc-600">
                    {t("res.addon.no_promotions")} {t("res.addon.balance_note")}
                  </p>
                  {p.addon.explanation && p.addon.explanation.length > 0 && <ExplanationList steps={p.addon.explanation} />}
                </>
              )}
            </div>
          )}
        </section>

        {fresh && (
          <section aria-labelledby={`${ids}-confirm`} className="space-y-3 rounded-lg border border-zinc-200 p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 id={`${ids}-confirm`} className="text-sm font-semibold text-zinc-900">
                {t("res.addon.confirm_title")}
              </h3>
              <p className="text-xs text-zinc-500">{t("res.mod.expires_hint")}</p>
            </div>
            <Field label={t("res.addon.note")} hint={t("res.addon.note_hint")}>
              <Textarea id={`${ids}-reason`} rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
          </section>
        )}
      </div>
    </Drawer>
  )
}

/** The reservation's total now → with the extras, and what they add (server figures). */
function TotalsStrip({ p }: { p: AddonProposal }) {
  const { t } = useTexT()
  const ids = useId()
  return (
    <div className="flex flex-wrap items-end gap-x-3 gap-y-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
      <div role="group" aria-labelledby={`${ids}-old`}>
        <p id={`${ids}-old`} className="text-xs text-zinc-500">
          {t("res.addon.total_now")}
        </p>
        <p className="text-sm text-zinc-600">
          <data value={p.old_total}>
            <Money amount={p.old_total} currency={p.currency} />
          </data>
        </p>
      </div>
      <div role="group" aria-labelledby={`${ids}-new`}>
        <p id={`${ids}-new`} className="text-xs text-zinc-500">
          {t("res.addon.total_after")}
        </p>
        <p className="flex items-center gap-1.5 text-lg font-semibold text-zinc-950">
          <ArrowRight className="size-4 text-zinc-400" aria-hidden />
          <data value={p.new_total ?? ""}>
            <Money amount={p.new_total} currency={p.currency} />
          </data>
        </p>
      </div>
      <div role="group" aria-labelledby={`${ids}-add`} className="ml-auto text-right">
        <p id={`${ids}-add`} className="text-xs text-zinc-500">
          {t("res.addon.added")}
        </p>
        <p className="text-lg font-semibold">
          <data value={p.addon.totals.total}>
            <Money amount={p.addon.totals.total} currency={p.currency} signed />
          </data>
        </p>
      </div>
    </div>
  )
}

/** One extra that can be added: quantity, its day(s) of the stay, what is left of a limited
 * extra per day, and why it cannot be added (maximum reached, too late, sold out). */
function AddonRow({
  x,
  choice,
  onChange,
  id,
  stay,
  heads,
  earliest,
  showMissing,
}: {
  x: AddonOption
  choice: ExtraChoice | undefined
  onChange: (c: ExtraChoice | null) => void
  id: string
  stay: StayDates
  heads: Heads
  /** The first day it can still be ordered for (ISO). */
  earliest: string
  showMissing: boolean
}) {
  const { t } = useTexT()
  const L = useLabels()
  // the day a one-day extra would use, picked before adding it (e.g. arrival is too late)
  const [pickedDay, setPickedDay] = useState("")
  const code = x.code
  const mode = x.pricing_mode
  const qty = choice?.quantity ?? 0
  const dates = choice?.service_dates ?? []
  const serviceDate = isServiceDateMode(mode)
  const nightly = isNightlyMode(mode)
  const oneDay = !serviceDate && !nightly
  const ci = stay.check_in
  const days = useMemo(() => stayDays({ check_in: ci, check_out: stay.check_out }), [ci, stay.check_out])
  const stock: ExtrasAvailability | undefined = x.limited && x.days ? { [code]: x.days } : undefined
  const limited = Boolean(stock)
  const late = (d: string) => d < earliest
  const perQty = unitsPerQuantity(mode, heads)
  // per-stay maximum, net of what the reservation already has
  const maxLeft = x.max_quantity ? Math.max(x.max_quantity - x.booked, 0) : null
  const hardMax = maxLeft ?? 20
  const need = Math.max(qty, 1) * (perQty ?? 1)
  const stockOf = (d: string) => (limited ? dayStock(stock, code, d) : null)
  const blocked = (s: DayStock | null) => Boolean(s && !s.unknown && (s.closed || s.left < need))
  const usable = (d: string) => !late(d) && !blocked(stockOf(d))
  const pendingDay = days.includes(pickedDay) ? pickedDay : ""
  const pendingDays = oneDay && pendingDay ? [pendingDay] : []
  const used = usageDays(mode, { service_dates: qty > 0 ? dates : pendingDays }, stay)
  const worst = limited ? tightest(stock, code, used) : null

  // too late for the whole stay: a nightly extra needs every night, the others one usable day
  const tooLate = nightly ? stayNights(stay).some(late) : !days.some((d) => !late(d))
  const fits = (left: number) => (left <= 0 ? 0 : perQty ? Math.floor(left / perQty) : hardMax)
  let cap = hardMax
  if (worst && (nightly || qty > 0 || pendingDay)) cap = Math.min(hardMax, worst.closed ? 0 : fits(worst.left))
  else if (limited) {
    // no day chosen yet: as many as the best orderable day of the stay allows
    const best = days
      .filter((d) => !late(d))
      .map((d) => stockOf(d))
      .filter((s): s is DayStock => Boolean(s && !s.unknown && !s.closed))
    cap = Math.min(hardMax, Math.max(0, ...best.map((s) => fits(s.left))))
  }
  if (tooLate) cap = 0
  cap = Math.max(cap, 0)
  const unavailable = qty === 0 && cap === 0
  const firstUsable = days.find(usable) ?? ""

  const dayNote = (d: string, s: DayStock | null) =>
    late(d)
      ? t("res.addon.day_too_late")
      : !s || s.unknown
        ? ""
        : s.closed
          ? t("crs.extras.day_closed")
          : s.left <= 0
            ? t("crs.extras.day_sold_out")
            : t("crs.extras.day_left", { count: s.left })
  const infoId = `${id}-info`

  let stockLine: ReactNode = null
  if (worst && !tooLate && (nightly || qty > 0 || pendingDay)) {
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
  } else if (limited && !tooLate && maxLeft !== 0 && cap === 0) {
    stockLine = <Badge tone="danger">{t("res.addon.none_left")}</Badge>
  }

  const setQty = (v: number) => {
    if (v <= 0) {
      if (oneDay && dates[0]) setPickedDay(dates[0])
      onChange(null)
      return
    }
    if (qty > 0) {
      onChange({ quantity: v, service_dates: dates })
      return
    }
    if (oneDay) {
      // the arrival day unless it is too late (or full): then the first day that is not
      const day = pendingDay || (usable(ci) ? "" : firstUsable)
      onChange({ quantity: v, service_dates: day ? [day] : [] })
    } else onChange({ quantity: v, service_dates: [] })
  }
  const setDay = (v: string) => {
    if (qty > 0) onChange({ quantity: qty, service_dates: v ? [v] : [] })
    else setPickedDay(v)
  }
  const toggleDate = (d: string, on: boolean) => {
    const next = on ? [...new Set([...dates, d])].sort() : dates.filter((v) => v !== d)
    onChange(next.length ? { quantity: Math.max(qty, 1), service_dates: next } : null)
  }
  const dayValue = qty > 0 ? (dates[0] ?? "") : pendingDay
  const dayOptions = [
    {
      value: "",
      label: `${t("crs.extras.day_arrival", { date: shortDay(ci) })}${suffix(dayNote(ci, stockOf(ci)))}`,
      disabled: !usable(ci) && dayValue !== "",
    },
    ...days
      .filter((d) => d !== ci || dayValue === ci)
      .map((d) => ({ value: d, label: `${shortDay(d)}${suffix(dayNote(d, stockOf(d)))}`, disabled: !usable(d) && d !== dayValue })),
  ]
  const missing = serviceDate && qty > 0 && !dates.length

  return (
    <li className={cn("space-y-1.5 py-3", unavailable && "opacity-75")} data-extra={code}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 text-sm">
          <label htmlFor={id} className="block font-medium text-zinc-800">
            {x.name}
          </label>
          <span id={infoId} className="block text-xs text-zinc-500">
            {t("crs.extras.list_price", { amount: money(x.amount, x.currency) })} · {L.mode(mode)}
            {maxLeft !== null && x.max_quantity ? ` · ${t("res.addon.max", { count: x.max_quantity })}` : ""}
            {x.cutoff_hours > 0 ? ` · ${t("res.addon.cutoff", { count: x.cutoff_hours })}` : ""}
          </span>
          {x.description && <span className="mt-0.5 line-clamp-2 block text-xs text-zinc-600">{x.description}</span>}
          <span className="mt-1 flex flex-wrap items-center gap-1.5">
            {x.booked > 0 && <Badge tone="neutral">{t("res.addon.booked", { count: x.booked })}</Badge>}
            {maxLeft === 0 && <Badge tone="warning">{t("res.addon.max_reached")}</Badge>}
            {tooLate && maxLeft !== 0 && <Badge tone="warning">{t("res.addon.too_late")}</Badge>}
            {stockLine}
          </span>
        </div>
        <NumberStepper
          id={id}
          className="shrink-0"
          value={qty}
          min={0}
          max={cap}
          disabled={unavailable}
          aria-describedby={infoId}
          decLabel={t("crs.extras.less", { name: x.name })}
          incLabel={t("crs.extras.more", { name: x.name })}
          onChange={setQty}
        />
      </div>
      {serviceDate && !tooLate && maxLeft !== 0 && days.length > 0 && (
        <fieldset id={`${id}-days`}>
          <legend className="mb-1 text-xs text-zinc-600">
            {t("crs.extras.days")}
            <span className="sr-only"> · {x.name}</span>
          </legend>
          <div className="flex flex-wrap gap-1.5">
            {days.map((d) => {
              const on = dates.includes(d)
              const s = stockOf(d)
              const off = !usable(d)
              const note = dayNote(d, s)
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
          {missing && (
            <p className={cn("mt-1 text-xs font-medium", showMissing ? "text-rose-700" : "text-amber-800")} role={showMissing ? "alert" : undefined}>
              {t("crs.extras.choose_days")}
            </p>
          )}
        </fieldset>
      )}
      {oneDay && !tooLate && maxLeft !== 0 && (qty > 0 || limited || !usable(ci)) && (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <label htmlFor={`${id}-day`} className="text-xs text-zinc-600">
            {t("crs.extras.day")}
            <span className="sr-only"> · {x.name}</span>
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
