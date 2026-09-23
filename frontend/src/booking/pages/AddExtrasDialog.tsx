// Manage page: the guest adds extras to a booked room (G-22, ADR-034). The extras are
// priced on their own at today's prices (the stay stays price-locked; no promotions):
// pick → check the price (manage_extras_propose) → add (manage_extras_apply). The
// booking's balance grows by them and is paid like any balance: Pay now, or at the hotel.
import { CheckCircle2, Clock, Sparkles } from "lucide-react"
import { useCallback, useEffect, useId, useMemo, useState, type ReactNode } from "react"
import { useI18n, type I18n, type MessageKey } from "../i18n"
import { ApiError, pub, type ErrorKind } from "../lib/api"
import { addonRefusalText, earliestOrderDay, stayDays } from "../lib/extras"
import { isPositive } from "../lib/format"
import type { AddonApplied, AddonOption, AddonOptions, AddonProposal, AddonRequest, BookingRoom } from "../types"
import { Badge, Button, Checkbox, Counter, Field, Select } from "../ui/controls"
import { Dialog } from "../ui/Dialog"
import { Alert, Spinner } from "../ui/feedback"
import { Photo } from "../ui/Photo"

export interface ExtrasNotice {
  tone: "ok" | "warn" | "bad" | "info"
  title: string
  body?: string
}

const NIGHTLY = new Set(["NIGHT", "PERSON_NIGHT"])
const COUNTED = new Set(["UNIT", "USAGE"])
/** the most of one extra the guest can pick when the hotel sets no maximum (as at checkout) */
const DEFAULT_MAX = 9
/** apply refusals the guest gets past by pricing the same extras again: the proposal
 * expired, the price moved, the reservation changed or a limited extra ran out */
const RECHECK = new Set<ErrorKind>(["expired", "invalid", "sold_out", "extra_sold_out"])

type DayState = "open" | "low" | "gone" | "late"

interface Plan {
  /** chosen dates (SERVICE_DATE), every night, or one day of the stay (as the server counts use) */
  kind: "dates" | "nightly" | "day"
  /** how many more the guest can add (the maximum minus what the room already has) */
  left: number
  /** why it cannot be added now */
  blocked: "max" | "gone" | "late" | null
  state: (d: string) => DayState
  /** the days offered (those still in time; sold-out ones shown disabled) */
  shown: string[]
  /** a one-day extra: arrival, else the first day still possible */
  defaultDay: string | null
  /** the guest places a one-day extra on a day: a limited one, or arrival is too late to order */
  pickDay: boolean
  /** few left on the nights a nightly extra uses */
  low: boolean
}

function planFor(x: AddonOption, stay: string[], now: Date): Plan {
  const earliest = earliestOrderDay(x.cutoff_hours, now)
  const state = (d: string): DayState => {
    if (d < earliest) return "late"
    const a = x.days?.[d]
    return !a ? "open" : !a.available ? "gone" : a.low ? "low" : "open"
  }
  const left = x.max_quantity && x.max_quantity > 0 ? Math.max(x.max_quantity - (x.booked || 0), 0) : DEFAULT_MAX
  const kind: Plan["kind"] = x.pricing_mode === "SERVICE_DATE" ? "dates" : NIGHTLY.has(x.pricing_mode) ? "nightly" : "day"
  const used = kind === "nightly" && stay.length > 1 ? stay.slice(0, -1) : stay
  const states = used.map(state)
  const open = used.filter((_, i) => states[i] === "open" || states[i] === "low")
  let blocked: Plan["blocked"] = null
  if (left <= 0) blocked = "max"
  else if (!used.length) blocked = "late"
  else if (kind === "nightly") blocked = states.includes("late") ? "late" : states.includes("gone") ? "gone" : null
  else if (!open.length) blocked = states.includes("gone") ? "gone" : "late"
  const defaultDay = kind === "day" ? (open.includes(stay[0]) ? stay[0] : (open[0] ?? null)) : null
  return {
    kind,
    left,
    blocked,
    state,
    shown: used.filter((_, i) => states[i] !== "late"),
    defaultDay,
    pickDay: kind === "day" && !blocked && stay.length > 1 && (x.limited || defaultDay !== stay[0]),
    low: kind === "nightly" && states.includes("low"),
  }
}

interface Choice {
  quantity: number
  /** SERVICE_DATE: the chosen dates */
  dates: string[]
  /** a one-day extra placed by the guest */
  day: string | null
}

const NONE: Choice = { quantity: 0, dates: [], day: null }

function toRequest(x: AddonOption, plan: Plan, c: Choice | undefined): AddonRequest | null {
  if (!c || plan.blocked) return null
  if (plan.kind === "dates") return c.dates.length ? { code: x.code, quantity: 1, service_dates: [...c.dates].sort() } : null
  if (c.quantity < 1) return null
  const day = plan.pickDay ? (c.day ?? plan.defaultDay) : null
  return { code: x.code, quantity: Math.min(c.quantity, plan.left), ...(day ? { service_dates: [day] } : {}) }
}

function errorText(t: I18n["t"], e: unknown) {
  if (e instanceof ApiError) {
    if (e.kind === "network") return t("errors.network")
    if (e.kind === "rate_limit") return t("errors.rateLimitBody")
    if (e.message) return e.message
  }
  return t("errors.generic")
}

function ExtraCard({ x, plan, choice, onChange }: { x: AddonOption; plan: Plan; choice: Choice | undefined; onChange: (c: Choice) => void }) {
  const { t, money, day } = useI18n()
  const id = useId()
  const cur = choice ?? NONE
  const modeKey = `extra.mode.${x.pricing_mode}` as MessageKey
  const chosen = plan.kind === "dates" ? cur.dates.length > 0 : cur.quantity > 0
  const usedDay = plan.kind === "day" ? (cur.day ?? plan.defaultDay) : null
  const low = !plan.blocked && (plan.kind === "nightly" ? plan.low : !!usedDay && plan.state(usedDay) === "low")
  const cutoff = Math.floor(Number(x.cutoff_hours) || 0)
  const counted = COUNTED.has(x.pricing_mode) || (x.max_quantity ?? 0) > 1

  let control: ReactNode
  if (plan.blocked === "max") control = <p className="text-sm text-muted">{t("manage.extras.maxReached")}</p>
  else if (plan.blocked === "gone") control = <p className="text-sm text-muted">{t("extras.soldOutBody")}</p>
  else if (plan.blocked === "late") control = <p className="text-sm text-muted">{t("manage.extras.tooLate")}</p>
  else if (plan.kind === "dates")
    control = (
      <fieldset>
        <legend className="mb-1.5 text-sm font-medium text-soft">
          {t("extras.chooseDates")}
          <span className="sr-only"> · {x.name}</span>
        </legend>
        <div className="flex flex-wrap gap-2">
          {plan.shown.map((d) => {
            const on = cur.dates.includes(d)
            const s = plan.state(d)
            // a sold-out day stays removable when it was already chosen
            const locked = s === "gone" && !on
            const look = on ? "border-brand-ink bg-brand/10 font-semibold" : locked ? "cursor-not-allowed border-line bg-sunken text-muted" : "border-line-strong"
            return (
              <label key={d} className={`inline-flex min-h-10 items-center gap-2 rounded-full border px-3 text-sm ${locked ? "" : "cursor-pointer"} ${look}`}>
                <input
                  type="checkbox"
                  className="bk-check"
                  checked={on}
                  disabled={locked}
                  onChange={(e) => onChange({ ...cur, quantity: 1, dates: e.target.checked ? [...cur.dates, d].sort() : cur.dates.filter((v) => v !== d) })}
                />
                {day(d)}
                {s === "gone" ? (
                  <span className="text-xs font-medium">· {t("extras.soldOut")}</span>
                ) : s === "low" ? (
                  <span className="text-xs font-medium text-warn">· {t("extras.fewLeft")}</span>
                ) : null}
              </label>
            )
          })}
        </div>
      </fieldset>
    )
  else if (counted)
    control = (
      <Counter
        label={t("extras.quantity")}
        value={Math.min(cur.quantity, plan.left)}
        min={0}
        max={plan.left}
        onChange={(n) => onChange({ ...cur, quantity: n })}
        decLabel={t("extras.less", { name: x.name })}
        incLabel={t("extras.more", { name: x.name })}
      />
    )
  else
    control = (
      <Checkbox
        id={id}
        label={
          <span className="font-medium text-ink">
            {t("extras.add")}
            <span className="sr-only">: {x.name}</span>
          </span>
        }
        checked={cur.quantity > 0}
        onChange={(v) => onChange({ ...cur, quantity: v ? 1 : 0 })}
      />
    )

  return (
    <li className={`bk-card flex gap-4 p-4 ${chosen ? "ring-2 ring-brand-ink" : ""}`}>
      <Photo src={x.image} alt="" className="hidden size-20 flex-none rounded-ui sm:grid" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
          <div className="min-w-0">
            <h3 className="text-base font-semibold">{x.name}</h3>
            {x.category && <p className="text-xs text-muted">{x.category}</p>}
            {plan.blocked === "gone" ? (
              <Badge className="mt-1">{t("extras.soldOut")}</Badge>
            ) : (
              low && (
                <Badge tone="warn" className="mt-1">
                  {t("extras.fewLeft")}
                </Badge>
              )
            )}
          </div>
          <p className="text-sm">
            <span className="font-semibold tabular-nums">{money(x.amount, x.currency)}</span>{" "}
            <span className="text-muted">{t(modeKey) !== modeKey ? t(modeKey) : ""}</span>
          </p>
        </div>
        {x.description && <p className="mt-1 text-sm text-soft">{x.description}</p>}
        {(x.booked > 0 || (cutoff > 0 && !plan.blocked)) && (
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {x.booked > 0 && (
              <span className="inline-flex items-center gap-1 font-medium text-ok">
                <CheckCircle2 className="size-3.5" aria-hidden />
                {t("manage.extras.booked", { count: x.booked })}
              </span>
            )}
            {cutoff > 0 && !plan.blocked && (
              <span className="inline-flex items-center gap-1 text-muted">
                <Clock className="size-3.5" aria-hidden />
                {t("manage.extras.cutoff", { count: cutoff })}
              </span>
            )}
          </div>
        )}
        <div className="mt-2">{control}</div>
        {plan.pickDay && chosen && (
          <Field
            label={
              <>
                {t("extras.day")}
                <span className="sr-only"> · {x.name}</span>
              </>
            }
            className="mt-2 max-w-xs"
          >
            <Select value={usedDay ?? ""} onChange={(e) => onChange({ ...cur, day: e.target.value })}>
              {plan.shown.map((d) => {
                const s = plan.state(d)
                const note = s === "gone" ? ` · ${t("extras.soldOut")}` : s === "low" ? ` · ${t("extras.fewLeft")}` : ""
                return (
                  <option key={d} value={d} disabled={s === "gone" && d !== usedDay}>
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

function Review({ p, asked, byCode }: { p: AddonProposal; asked: AddonRequest[]; byCode: Map<string, AddonOption> }) {
  const i18n = useI18n()
  const { t, money, day } = i18n
  const hid = useId()
  if (!p.ok) {
    const names = asked.map((a) => ({ code: a.code, name: byCode.get(a.code)?.name ?? a.code, cutoff_hours: byCode.get(a.code)?.cutoff_hours }))
    return (
      <Alert tone="bad" title={t("manage.extras.notPossibleTitle")}>
        {!!p.reasons?.length && (
          <ul className="space-y-1">
            {p.reasons.map((r, i) => (
              <li key={i}>{addonRefusalText(i18n, r, names)}</li>
            ))}
          </ul>
        )}
        <p className={p.reasons?.length ? "mt-2" : ""}>{t("manage.extras.notPossibleBody")}</p>
      </Alert>
    )
  }
  const extraLines = p.lines.filter((l) => l.kind === "EXTRA")
  const taxLines = p.lines.filter((l) => l.kind !== "EXTRA")
  return (
    <>
      <section aria-labelledby={hid}>
        <h3 id={hid} className="text-base font-semibold">
          {t("manage.extras.yourExtras")}
        </h3>
        <dl className="mt-2 divide-y divide-line rounded-ui border border-line text-sm">
          {extraLines.map((l, i) => {
            // the server names lines in the hotel's language; the guest's names come with the options
            const n = asked.find((a) => a.code === l.code)?.quantity ?? 1
            const dates = p.extras.find((e) => e.code === l.code)?.service_dates ?? []
            return (
              <div key={`${l.code}-${i}`} className="flex justify-between gap-3 p-3">
                <dt className="min-w-0">
                  <span className="font-medium">
                    {byCode.get(l.code)?.name ?? l.description}
                    {n > 1 ? ` × ${n}` : ""}
                  </span>
                  {dates.length > 0 && <span className="block text-xs text-muted">{dates.map(day).join(" · ")}</span>}
                </dt>
                <dd className="shrink-0 tabular-nums">{money(l.amount, p.currency)}</dd>
              </div>
            )
          })}
          {taxLines.map((l, i) => (
            <div key={`t${i}`} className={`flex justify-between gap-3 p-3 ${l.included ? "text-xs text-muted" : ""}`}>
              <dt className={l.included ? "" : "text-soft"}>{l.included ? t("manage.extras.included", { name: l.description }) : l.description}</dt>
              <dd className="tabular-nums">{money(l.amount, p.currency)}</dd>
            </div>
          ))}
          <div className="flex justify-between gap-3 p-3 font-semibold">
            <dt>{t("manage.extras.addonTotal")}</dt>
            <dd className="tabular-nums">{money(p.totals.total, p.currency)}</dd>
          </div>
        </dl>
      </section>
      <dl className="divide-y divide-line rounded-ui border border-line text-sm">
        <div className="flex justify-between gap-3 p-3">
          <dt className="text-soft">{t("manage.extras.oldTotal")}</dt>
          <dd className="tabular-nums">{money(p.old_total, p.currency)}</dd>
        </div>
        <div className="flex justify-between gap-3 p-3">
          <dt className="font-semibold">{t("manage.extras.newTotal")}</dt>
          <dd className="font-bold tabular-nums">{money(p.new_total, p.currency)}</dd>
        </div>
      </dl>
      <p className="text-sm text-soft">{t("manage.extras.payNote")}</p>
      <p className="text-xs text-muted">{t("manage.extras.ownPrice")}</p>
    </>
  )
}

export function AddExtrasDialog({
  room,
  currency,
  token,
  onClose,
  onDone,
}: {
  room: BookingRoom
  /** the booking's currency (its balance) */
  currency: string
  token: string
  onClose: () => void
  onDone: (n: ExtrasNotice) => void
}) {
  const { t, money, range } = useI18n()
  const [options, setOptions] = useState<AddonOptions | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [choices, setChoices] = useState<Record<string, Choice>>({})
  const [proposal, setProposal] = useState<AddonProposal | null>(null)
  /** the extras the proposal priced (priced again as they are when it expires) */
  const [asked, setAsked] = useState<AddonRequest[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [nothing, setNothing] = useState(false)
  const [refreshed, setRefreshed] = useState(false)

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoadError(null)
      try {
        const o = await pub<AddonOptions>("manage_extras", { token, reservation: room.reservation }, signal)
        setOptions({ ...o, extras: o?.extras ?? [] })
      } catch (e) {
        if ((e as Error).name === "AbortError") return
        setLoadError(errorText(t, e))
      }
    },
    [token, room.reservation, t],
  )
  useEffect(() => {
    const ctl = new AbortController()
    void load(ctl.signal)
    return () => ctl.abort()
  }, [load])

  const stay = useMemo(() => stayDays(options?.check_in, options?.check_out), [options])
  const plans = useMemo(() => {
    const now = new Date()
    return new Map((options?.extras ?? []).map((x) => [x.code, planFor(x, stay, now)]))
  }, [options, stay])
  const byCode = useMemo(() => new Map((options?.extras ?? []).map((x) => [x.code, x])), [options])
  const requests = useMemo(
    () => (options?.extras ?? []).map((x) => toRequest(x, plans.get(x.code)!, choices[x.code])).filter((r): r is AddonRequest => !!r),
    [options, plans, choices],
  )

  const check = async (reqs: AddonRequest[], again = false) => {
    setError(null)
    if (!reqs.length) return setNothing(true)
    setBusy(true)
    try {
      const p = await pub<AddonProposal>("manage_extras_propose", { token, reservation: room.reservation, extras: reqs })
      setAsked(reqs)
      setRefreshed(again)
      setProposal(p)
    } catch (e) {
      setError(errorText(t, e))
    }
    setBusy(false)
  }

  const apply = async () => {
    if (!proposal?.proposal_token) return
    setBusy(true)
    setError(null)
    try {
      const r = await pub<AddonApplied>("manage_extras_apply", { token, proposal_token: proposal.proposal_token })
      const owed = r.balance && isPositive(r.balance) ? money(r.balance, currency) : null
      onDone({
        tone: "ok",
        title: t("manage.extras.addedTitle"),
        body: !owed
          ? t("manage.extras.addedBody")
          : r.payment_status === "Pay at Hotel"
            ? t("manage.extras.addedAtHotel", { amount: owed })
            : t("manage.extras.addedBalance", { amount: owed, payNow: t("confirm.payNow") }),
      })
    } catch (e) {
      setBusy(false)
      if (e instanceof ApiError && RECHECK.has(e.kind)) {
        // proposals last 30 minutes and are bound to the price and the reservation as they
        // were: price the same extras again and let the guest confirm (as ChangeDialog does)
        setProposal(null)
        await check(asked, true)
        return
      }
      setError(errorText(t, e))
    }
  }

  const choose = (code: string, c: Choice) => {
    setNothing(false)
    setChoices((all) => ({ ...all, [code]: c }))
  }
  const editAgain = () => {
    setProposal(null)
    setError(null)
    setRefreshed(false)
  }

  const hasExtras = !!options?.extras.length
  let body: ReactNode
  if (loadError)
    body = (
      <Alert
        tone="bad"
        title={t("manage.extras.loadError")}
        actions={
          <Button variant="secondary" onClick={() => void load()}>
            {t("common.retry")}
          </Button>
        }
      >
        {loadError}
      </Alert>
    )
  else if (!options) body = <Spinner label={t("common.loading")} className="py-8" />
  else if (!hasExtras)
    body = (
      <div className="flex flex-col items-center px-2 py-8 text-center">
        <Sparkles className="mb-3 size-8 text-muted" aria-hidden />
        <h3 className="text-lg">{t("manage.extras.emptyTitle")}</h3>
        <p className="mt-1 max-w-md text-sm text-muted">{t("manage.extras.emptyBody")}</p>
      </div>
    )
  else if (proposal)
    body = (
      <div className="space-y-4">
        {refreshed && (
          <Alert tone="warn" title={t("manage.refreshedTitle")}>
            {t("manage.extras.refreshedBody")}
          </Alert>
        )}
        <Review p={proposal} asked={asked} byCode={byCode} />
        {error && (
          <Alert tone="bad" title={t("manage.extras.applyFailed")}>
            {error}
          </Alert>
        )}
      </div>
    )
  else
    body = (
      <div className="space-y-4">
        <p className="text-sm text-soft">{t("manage.extras.intro")}</p>
        <ul className="space-y-3">
          {options.extras.map((x) => (
            <ExtraCard key={x.code} x={x} plan={plans.get(x.code)!} choice={choices[x.code]} onChange={(c) => choose(x.code, c)} />
          ))}
        </ul>
        {error && (
          <Alert tone="bad" title={t("manage.extras.proposeFailed")}>
            {error}
          </Alert>
        )}
        <p className="text-xs text-muted">{t("manage.extras.priceNote")}</p>
      </div>
    )

  return (
    <Dialog
      open
      onClose={onClose}
      title={t("manage.extras.title", { name: room.room_type_name ?? room.room_type })}
      description={range(room.check_in, room.check_out)}
      closeLabel={t("common.close")}
      variant="full"
      footer={
        hasExtras ? (
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-end">
            {nothing && !proposal && (
              <p role="alert" className="text-sm font-medium text-bad sm:mr-auto">
                {t("manage.extras.chooseFirst")}
              </p>
            )}
            <div className="flex flex-col-reverse gap-2 sm:flex-row">
              {proposal ? (
                <>
                  <Button variant={proposal.ok ? "secondary" : "primary"} onClick={editAgain} disabled={busy}>
                    {t("extras.changeChoice")}
                  </Button>
                  {proposal.ok && (
                    <Button onClick={apply} busy={busy}>
                      {t("manage.extras.confirm")}
                    </Button>
                  )}
                </>
              ) : (
                <Button onClick={() => void check(requests)} busy={busy}>
                  {t("manage.extras.checkPrice")}
                </Button>
              )}
            </div>
          </div>
        ) : (
          <div className="flex justify-end">
            <Button variant="secondary" onClick={onClose}>
              {t("common.close")}
            </Button>
          </div>
        )
      }
    >
      {body}
    </Dialog>
  )
}
