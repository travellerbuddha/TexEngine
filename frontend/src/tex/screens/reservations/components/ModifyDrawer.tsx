import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react"
import { AlertTriangle, ArrowRight, Calculator, RotateCcw } from "lucide-react"
import { useTexQuery, type TexApiError } from "../../../lib/api"
import { addDays, date, isDecimal, nightsBetween } from "../../../lib/format"
import { useSession } from "../../../lib/session"
import { useTexT } from "../../../i18n"
import {
  Badge,
  Button,
  Checkbox,
  DecimalInput,
  Drawer,
  Field,
  FormGrid,
  Input,
  InlineError,
  Money,
  Notice,
  Select,
  Skeleton,
  Textarea,
  useToast,
} from "../../../ui"
import { cn } from "../../../../lib/utils"
import { CodeChips } from "../../crs/components/controls"
import { ExplanationList } from "../../crs/components/OfferParts"
import { PartyEditor, usePartyText } from "../../crs/components/PartyEditor"
import { PriceBreakdown } from "../../crs/components/PriceBreakdown"
import { ExtrasPicker, useExtras } from "../../crs/components/QuoteParts"
import {
  choicesToRequest,
  extraWarningName,
  extraWarningText,
  fitChoice,
  sameChoices,
  shortDay,
  type ExtraChoice,
  type StayDates,
} from "../../crs/lib/extrasStock"
import { useLabels } from "../../crs/lib/labels"
import { useServerClock } from "../../crs/lib/serverClock"
import { BOARDS, DOB_ERRORS, childToApi, cmpDecimal, dobProblem, isDob, isZero, shortCode, type PartyForm } from "../../crs/lib/party"
import { asApiError } from "../../crs/lib/useBookingFlow"
import type { StayRequest } from "../../crs/lib/types"
import { applyModification, proposeModification, type Basis } from "../lib/api"
import { addonText } from "../lib/addons"
import type { AddonEntry, ApplyResult, ContractVersionInfo, Proposal, ReservationDetail } from "../lib/types"

interface ModForm {
  check_in: string
  check_out: string
  room_type: string
  board: string
  rate_plan: string
  market: string
  party: PartyForm
  /** Quantity and service days per extra code (days are kept when only the quantity changes). */
  extras: Record<string, ExtraChoice>
  promo: string[]
  /** Extras added after booking (G-22) to remove: their add-on ids. */
  drop: string[]
}

/** A modification warning: a limited extra has no capacity for the new stay (G-19). */
const EXTRA_SOLD_OUT = "EXTRA_SOLD_OUT"
const FULL_DAY = /^[1-9]\d{3}-\d{2}-\d{2}$/

export const BASES: Basis[] = ["CURRENT", "ORIGINAL_VERSION", "ORIGINAL_SALE_DATE", "HISTORICAL_SALE_DATE"]

function formOf(req: StayRequest): ModForm {
  return {
    check_in: req.check_in,
    check_out: req.check_out,
    room_type: req.room_type,
    board: req.board,
    rate_plan: req.rate_plan ?? "",
    market: req.market,
    // a child sold by date of birth keeps it (the server prices it in months on arrival, G-52)
    party: { adults: req.adults, children: (req.children ?? []).map((c) => (c.dob ? { dob: c.dob } : (c.age ?? null))) },
    extras: Object.fromEntries(
      (req.extras ?? []).map((e) => [e.code, { quantity: e.quantity, service_dates: [...(e.service_dates ?? [])].sort() }]),
    ),
    promo: [...(req.promo_codes ?? [])],
    drop: [],
  }
}

/** Service days of every extra kept inside the stay; a moved check-in moves them along. */
function fitExtras(extras: Record<string, ExtraChoice>, stay: StayDates, shiftDays = 0): Record<string, ExtraChoice> {
  return Object.fromEntries(Object.entries(extras).map(([code, c]) => [code, fitChoice(c, stay, shiftDays)]))
}

/** The extras line of the comparison: code × quantity (service days). */
function extrasText(xs: StayRequest["extras"] | undefined) {
  return (
    (xs ?? [])
      .map((e) => `${e.code}×${e.quantity}${e.service_dates?.length ? ` (${e.service_dates.map((d) => shortDay(d)).join(", ")})` : ""}`)
      .join(", ") || "—"
  )
}

/** Only what the agent changed goes to propose_modification. */
function changesOf(a: ModForm, b: ModForm): Record<string, unknown> {
  const c: Record<string, unknown> = {}
  if (b.check_in !== a.check_in) c.check_in = b.check_in
  if (b.check_out !== a.check_out) c.check_out = b.check_out
  if (b.room_type !== a.room_type) c.room_type = b.room_type
  if (b.board !== a.board) c.board = b.board
  if (b.rate_plan !== a.rate_plan && b.rate_plan) c.rate_plan = b.rate_plan
  if (b.market !== a.market) c.market = b.market
  if (b.party.adults !== a.party.adults) c.adults = b.party.adults
  if (JSON.stringify(b.party.children) !== JSON.stringify(a.party.children)) c.children = b.party.children.map(childToApi)
  const ex = choicesToRequest(b.extras)
  if (!sameChoices(choicesToRequest(a.extras), ex)) c.extras = ex
  if ([...b.promo].sort().join(",") !== [...a.promo].sort().join(",")) c.promo_codes = b.promo
  if (b.drop.length) c.drop_addons = [...b.drop].sort()
  return c
}

/** "2026-08-01T10:00" → "2026-08-01 10:00:00" (server wall clock, bootstrap server.time_zone). */
export function localToServer(v: string) {
  return v ? `${v.replace("T", " ")}${v.length === 16 ? ":00" : ""}` : ""
}

export function ModifyDrawer({
  open,
  onClose,
  res,
  onApplied,
}: {
  open: boolean
  onClose: () => void
  res: ReservationDetail
  onApplied: (r: ApplyResult) => void
}) {
  const { t } = useTexT()
  const L = useLabels()
  const toast = useToast()
  const clock = useServerClock()
  const { boot } = useSession()
  const caps = useMemo(() => new Set(res.capabilities), [res.capabilities])
  const canOverride = caps.has("price.override")
  const canCost = caps.has("price.view_cost")
  const initial = useMemo(() => formOf(res.pricing.request), [res.pricing.request])
  const [form, setForm] = useState<ModForm>(initial)
  const [basis, setBasis] = useState<Basis>("CURRENT")
  const [basisAt, setBasisAt] = useState("")
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [proposal, setProposal] = useState<Proposal>()
  const [proposedSig, setProposedSig] = useState("")
  const [proposing, setProposing] = useState(false)
  const [proposeError, setProposeError] = useState<TexApiError>()
  const [override, setOverride] = useState(false)
  const [overrideAmount, setOverrideAmount] = useState("")
  const [reason, setReason] = useState("")
  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState<TexApiError>()
  const errorRef = useRef<HTMLDivElement>(null)
  const resultRef = useRef<HTMLElement>(null)
  // server answers land below the form: bring them into view
  useEffect(() => {
    if (applyError) errorRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [applyError])

  useEffect(() => {
    if (!open) return
    setForm(initial)
    setBasis("CURRENT")
    setBasisAt("")
    setErrors({})
    setProposal(undefined)
    setProposedSig("")
    setProposeError(undefined)
    setOverride(false)
    setOverrideAmount("")
    setReason("")
    setApplyError(undefined)
  }, [open, initial])

  const version = useTexQuery<ContractVersionInfo>(
    "contracts",
    "get_version",
    { name: res.contract_version },
    [res.contract_version],
    open && Boolean(res.contract_version),
  )
  const extras = useExtras(open ? res.property : undefined)

  const changes = useMemo(() => changesOf(initial, form), [initial, form])
  const sig = JSON.stringify({ changes, basis, basisAt })
  const stale = Boolean(proposal && proposedSig !== sig)
  const changedCount = Object.keys(changes).length

  const v = version.data
  const roomOptions = useMemo(() => {
    const names = new Map((v?.room_types ?? []).map((r) => [r.name, r.room_type_name]))
    const ids = v ? [...new Set(v.rooms.map((r) => r.room_type))] : []
    if (!ids.includes(initial.room_type)) ids.unshift(initial.room_type)
    return ids.map((id) => ({ value: id, label: names.get(id) ?? (id === res.room_type ? res.room_type_name ?? id : shortCode(id, res.property)) }))
  }, [v, initial.room_type, res.room_type, res.room_type_name, res.property])
  const boardOptions = useMemo(() => {
    const codes = v ? [...new Set(v.boards.map((b) => b.board))] : []
    if (!codes.includes(initial.board)) codes.unshift(initial.board)
    codes.sort((a, b) => (BOARDS as readonly string[]).indexOf(a) - (BOARDS as readonly string[]).indexOf(b))
    return codes.map((c) => ({ value: c, label: L.board(c) }))
  }, [v, initial.board, L])
  const planOptions = useMemo(() => {
    const names = new Map((v?.rate_plan_options ?? []).map((r) => [r.name, r.rate_plan_name]))
    const ids = v ? [...new Set(v.rate_plans.map((r) => r.rate_plan))] : []
    if (initial.rate_plan && !ids.includes(initial.rate_plan)) ids.unshift(initial.rate_plan)
    return ids.map((id) => ({ value: id, label: names.get(id) ?? shortCode(id, res.property) }))
  }, [v, initial.rate_plan, res.property])
  const roomName = (id: string) => roomOptions.find((o) => o.value === id)?.label ?? shortCode(id, res.property)
  const planName = (id: string | null | undefined) => (id ? planOptions.find((o) => o.value === id)?.label ?? shortCode(id, res.property) : "—")

  const validate = () => {
    const e: Record<string, string> = {}
    if (!form.check_in) e.check_in = t("crs.err.check_in")
    if (!form.check_out || form.check_out <= form.check_in) e.check_out = t("crs.err.check_out_after")
    if ("children" in changes)
      form.party.children.forEach((a, k) => {
        const why = isDob(a) ? dobProblem(a.dob, clock.today(), form.check_in) : ""
        if (a === null) e[`room_0_child_${k}`] = t("crs.err.child_age")
        else if (why) e[`room_0_child_${k}`] = t(DOB_ERRORS[why])
      })
    if (basis === "HISTORICAL_SALE_DATE" && !basisAt) e.basis_at = t("res.mod.err_basis_at")
    setErrors(e)
    return !Object.keys(e).length
  }

  const propose = async () => {
    if (!validate()) return
    setProposing(true)
    setProposeError(undefined)
    setApplyError(undefined)
    try {
      const p = await proposeModification(res.name, changes, basis, basis === "HISTORICAL_SALE_DATE" ? localToServer(basisAt) : undefined)
      setProposal(p)
      setProposedSig(sig)
      setOverrideAmount("")
      window.setTimeout(() => resultRef.current?.scrollIntoView({ block: "start", behavior: "smooth" }), 50)
    } catch (e) {
      setProposeError(asApiError(e))
      setProposal(undefined)
    } finally {
      setProposing(false)
    }
  }

  const overrideOk = !override || (isDecimal(overrideAmount) && cmpDecimal(overrideAmount, "0") >= 0)
  const canApply = Boolean(proposal && !stale && proposal.sellable && reason.trim().length > 2 && overrideOk && !applying)
  const apply = async () => {
    if (!proposal || !canApply) return
    setApplying(true)
    setApplyError(undefined)
    try {
      const r = await applyModification(proposal.proposal_token, reason.trim(), override ? overrideAmount : undefined)
      toast.success(t("res.mod.applied", { rev: r.revision }))
      onApplied(r)
    } catch (e) {
      setApplyError(asApiError(e))
    } finally {
      setApplying(false)
    }
  }

  const set = (patch: Partial<ModForm>) => setForm((f) => ({ ...f, ...patch }))
  const nights = form.check_out > form.check_in ? nightsBetween(form.check_in, form.check_out) : 0
  // moving check-in keeps the stay length; only check-out edits change it
  const stayNights = useRef(nightsBetween(initial.check_in, initial.check_out) || 1)
  // the last complete check-in: extras' service days move by as many days as the stay does
  const lastCheckIn = useRef(initial.check_in)
  useEffect(() => {
    if (!open) return
    stayNights.current = nightsBetween(initial.check_in, initial.check_out) || 1
    lastCheckIn.current = initial.check_in
  }, [open, initial])
  const stay: StayDates | undefined =
    FULL_DAY.test(form.check_in) && FULL_DAY.test(form.check_out) && form.check_out > form.check_in
      ? { check_in: form.check_in, check_out: form.check_out }
      : undefined
  const droppedExtras = (proposal?.warnings ?? []).filter((w) => w.code === EXTRA_SOLD_OUT)
  const addons = useMemo(() => res.pricing?.addons ?? [], [res.pricing])
  // add-ons the proposal removes: not carried over into the proposed price
  const removedAddons = proposal ? removedBy(proposal, addons) : []

  return (
    <Drawer
      open={open}
      onClose={applying ? () => undefined : onClose}
      width="xl"
      title={t("res.mod.title", { name: res.name })}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={applying}>
            {t("core.action.cancel")}
          </Button>
          <Button
            variant={proposal && !stale ? "secondary" : "primary"}
            icon={<Calculator className="size-4" aria-hidden />}
            onClick={() => void propose()}
            loading={proposing}
          >
            {proposal ? t("res.mod.recalculate") : t("res.mod.calculate")}
          </Button>
          {proposal && (
            <Button onClick={() => void apply()} loading={applying} disabled={!canApply}>
              {t("res.mod.apply")}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-6">
        <Notice tone="info">{t("res.mod.intro")}</Notice>
        <section aria-labelledby="mod-what" className="space-y-4">
          <h3 id="mod-what" className="text-sm font-semibold text-zinc-900">
            {t("res.mod.what")} {changedCount > 0 && <Badge tone="brand">{t("res.mod.changed_n", { count: changedCount })}</Badge>}
          </h3>
          <FormGrid cols={3}>
            <Field label={t("crs.search.check_in")} error={errors.check_in}>
              <Input
                id="mod-ci"
                type="date"
                value={form.check_in}
                onChange={(e) => {
                  const ci = e.target.value
                  // shift check-out only once the year is complete (typing "2026" passes 0002, 0020…)
                  if (!FULL_DAY.test(ci)) {
                    set({ check_in: ci })
                    return
                  }
                  const co = addDays(ci, stayNights.current)
                  const shift = nightsBetween(lastCheckIn.current, ci)
                  lastCheckIn.current = ci
                  set({ check_in: ci, check_out: co, extras: fitExtras(form.extras, { check_in: ci, check_out: co }, shift) })
                }}
              />
            </Field>
            <Field label={t("crs.search.check_out")} error={errors.check_out} hint={nights ? t("core.label.nights", { count: nights }) : undefined}>
              <Input
                id="mod-co"
                type="date"
                min={form.check_in ? addDays(form.check_in, 1) : undefined}
                value={form.check_out}
                onChange={(e) => {
                  const co = e.target.value
                  if (co && form.check_in && co > form.check_in) stayNights.current = Math.min(90, nightsBetween(form.check_in, co))
                  // a shorter stay drops the service days after the new check-out
                  const fits = FULL_DAY.test(co) && FULL_DAY.test(form.check_in) && co > form.check_in
                  set({ check_out: co, extras: fits ? fitExtras(form.extras, { check_in: form.check_in, check_out: co }) : form.extras })
                }}
              />
            </Field>
            <Field label={t("crs.search.market")} hint={t("res.mod.market_hint")}>
              <Select
                id="mod-market"
                value={form.market}
                onChange={(e) => set({ market: e.target.value })}
                options={boot.markets.map((m) => ({ value: m.name, label: m.name === m.market_name ? m.name : `${m.market_name} (${m.name})` }))}
              />
            </Field>
            <Field label={t("res.field.room_type")}>
              {version.loading ? <Skeleton className="h-9 w-full" /> : <Select id="mod-room" value={form.room_type} onChange={(e) => set({ room_type: e.target.value })} options={roomOptions} />}
            </Field>
            <Field label={t("res.field.board")}>
              <Select id="mod-board" value={form.board} onChange={(e) => set({ board: e.target.value })} options={boardOptions} />
            </Field>
            <Field label={t("res.field.rate_plan")}>
              <Select
                id="mod-plan"
                value={form.rate_plan}
                onChange={(e) => set({ rate_plan: e.target.value })}
                options={planOptions.length ? planOptions : [{ value: "", label: "—" }]}
              />
            </Field>
          </FormGrid>
          {version.error && <p className="text-xs text-amber-800">{t("res.mod.options_limited")}</p>}
          <PartyEditor rooms={[form.party]} onChange={(r) => set({ party: r[0] })} errors={errors} idPrefix="mod-party" maxRooms={1} />
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <p className="mb-1 text-sm font-medium text-zinc-800">{t("crs.extras.title")}</p>
              {/* no remaining capacity here: this reservation's own units would count against it;
                  the proposal checks the limited extras for the new stay (EXTRA_SOLD_OUT) */}
              <ExtrasPicker
                extras={extras.data}
                value={form.extras}
                roomLabel={res.name}
                idPrefix="mod"
                stay={stay}
                onChange={(code, c) => {
                  const next = { ...form.extras }
                  if (c && c.quantity > 0) next[code] = { quantity: c.quantity, service_dates: [...new Set(c.service_dates)].sort() }
                  else delete next[code]
                  set({ extras: next })
                }}
              />
            </div>
            <Field label={t("crs.quote.promo")}>
              <CodeChips id="mod-promo" value={form.promo} onChange={(promo) => set({ promo })} placeholder={t("crs.search.promo_placeholder")} />
            </Field>
          </div>
          {addons.length > 0 && (
            <fieldset className="space-y-2 rounded-lg border border-zinc-200 p-3">
              <legend className="px-1 text-sm font-medium text-zinc-800">{t("res.mod.drop_title")}</legend>
              <p className="text-xs text-zinc-500">{t("res.mod.drop_hint")}</p>
              <ul className="space-y-1.5">
                {addons.map((a) => (
                  <li key={a.id}>
                    <Checkbox
                      className="items-start"
                      checked={form.drop.includes(a.id)}
                      onChange={(e) => set({ drop: e.target.checked ? [...new Set([...form.drop, a.id])] : form.drop.filter((x) => x !== a.id) })}
                      label={
                        <span className="min-w-0">
                          <span className="block text-zinc-800">{addonText(a)}</span>
                          <span className="block text-xs text-zinc-500">
                            {t("res.mod.drop_added", { time: clock.label(a.at) })}
                            {a.source ? ` · ${L.source(a.source)}` : ""}
                          </span>
                        </span>
                      }
                    />
                  </li>
                ))}
              </ul>
            </fieldset>
          )}
          {changedCount > 0 && (
            <Button
              variant="ghost"
              size="sm"
              icon={<RotateCcw className="size-4" aria-hidden />}
              onClick={() => {
                setForm(initial)
                stayNights.current = nightsBetween(initial.check_in, initial.check_out) || 1
                lastCheckIn.current = initial.check_in
              }}
            >
              {t("res.mod.reset")}
            </Button>
          )}
        </section>

        <BasisPicker basis={basis} onBasis={setBasis} basisAt={basisAt} onBasisAt={setBasisAt} canOverride={canOverride} error={errors.basis_at} res={res} />

        <section ref={resultRef} aria-labelledby="mod-result" aria-live="polite" className="scroll-mt-4 space-y-4">
          <h3 id="mod-result" className="text-sm font-semibold text-zinc-900">
            {t("res.mod.result")}
          </h3>
          {proposeError && <InlineError error={proposeError} />}
          {!proposal && !proposeError && <p className="text-sm text-zinc-500">{t("res.mod.result_hint")}</p>}
          {proposal && (
            <div className={cn("space-y-4", stale && "opacity-60")}>
              {stale && (
                <Notice tone="warning">
                  {t("res.mod.stale")}{" "}
                  <button type="button" className="font-medium underline" onClick={() => void propose()}>
                    {t("res.mod.recalculate")}
                  </button>
                </Notice>
              )}
              <Comparison p={proposal} canCost={canCost} roomName={roomName} planName={planName} addons={addons} />
            </div>
          )}
        </section>

        {proposal && !stale && proposal.sellable && (
          <section aria-labelledby="mod-apply" className="space-y-3 rounded-lg border border-zinc-200 p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 id="mod-apply" className="text-sm font-semibold text-zinc-900">
                {t("res.mod.confirm")}
              </h3>
              <p className="text-xs text-zinc-500">{t("res.mod.expires_hint")}</p>
            </div>
            {canOverride && (
              <div className="space-y-2">
                <Checkbox label={t("res.mod.override")} checked={override} onChange={(e) => setOverride(e.target.checked)} />
                {override && (
                  <Field label={t("res.mod.override_amount")} hint={t("res.mod.override_hint")} error={!overrideOk && overrideAmount ? t("res.mod.override_invalid") : undefined} required>
                    <DecimalInput id="mod-override" value={overrideAmount} onValueChange={setOverrideAmount} suffix={proposal.proposed.currency} className="max-w-48" />
                  </Field>
                )}
              </div>
            )}
            {droppedExtras.length > 0 && (
              <p className="flex items-start gap-1.5 text-sm font-medium text-amber-800">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                {t("res.mod.apply_drops", { extras: droppedExtras.map((w) => extraWarningName(w.message)).join(", ") })}
              </p>
            )}
            {removedAddons.length > 0 && (
              <p className="flex items-start gap-1.5 text-sm font-medium text-zinc-800">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-700" aria-hidden />
                {t("res.mod.apply_removes_addons", { count: removedAddons.length, extras: removedAddons.map(addonText).join("; ") })}
              </p>
            )}
            <Field label={t("core.field.reason")} hint={t("core.hint.reason_audited")} required>
              <Textarea id="mod-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            {applyError && (
              <div ref={errorRef}>
              <Notice tone="danger" title={applyError.isPermission ? t("core.error.permission") : t("res.mod.apply_failed")}>
                <p>{applyError.message}</p>
                {!applyError.isPermission && (
                  <>
                    <p className="mt-1 text-xs">{t("res.mod.apply_failed_hint")}</p>
                    <Button size="sm" variant="secondary" className="mt-2" onClick={() => void propose()} loading={proposing}>
                      {t("res.mod.repropose")}
                    </Button>
                  </>
                )}
              </Notice>
              </div>
            )}
          </section>
        )}
      </div>
    </Drawer>
  )
}

function BasisPicker({
  basis,
  onBasis,
  basisAt,
  onBasisAt,
  canOverride,
  error,
  res,
}: {
  basis: Basis
  onBasis: (b: Basis) => void
  basisAt: string
  onBasisAt: (v: string) => void
  canOverride: boolean
  error?: string
  res: ReservationDetail
}) {
  const { t } = useTexT()
  const clock = useServerClock()
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-semibold text-zinc-900">{t("res.basis.title")}</legend>
      <p className="text-xs text-zinc-500">{t("res.basis.hint")}</p>
      <div className="grid gap-2 md:grid-cols-2">
        {BASES.map((b) => {
          const locked = b === "HISTORICAL_SALE_DATE" && !canOverride
          const id = `basis-${b}`
          return (
            <label
              key={b}
              htmlFor={id}
              className={cn(
                "flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm",
                basis === b ? "border-tex-500 bg-tex-50" : "border-zinc-200 hover:border-zinc-300",
                locked && "cursor-not-allowed opacity-60",
              )}
            >
              <input id={id} type="radio" name="mod-basis" className="mt-0.5 size-4 accent-tex-600" checked={basis === b} disabled={locked} onChange={() => onBasis(b)} />
              <span>
                <span className="block font-medium text-zinc-900">{t(`crs.basis.${b.toLowerCase()}`)}</span>
                <span className="block text-xs text-zinc-600">
                  {t(`res.basis.${b.toLowerCase()}_help`, { sale: clock.label(res.sale_at), version: res.contract_version ?? "—" })}
                </span>
                {locked && <span className="block text-xs text-zinc-500">{t("res.basis.needs_override")}</span>}
              </span>
            </label>
          )
        })}
      </div>
      {basis === "HISTORICAL_SALE_DATE" && (
        <Field label={t("res.basis.sale_at")} hint={t("res.basis.sale_at_hint", { tz: clock.tz ?? "—" })} error={error} required>
          <Input id="mod-basis-at" type="datetime-local" className="max-w-64" value={basisAt} onChange={(e) => onBasisAt(e.target.value)} />
        </Field>
      )}
    </fieldset>
  )
}

/** The reservation's add-ons that a proposal no longer carries (removed with the change). */
function removedBy(p: Proposal, addons: AddonEntry[]): AddonEntry[] {
  const kept = new Set((p.proposed.addons ?? []).map((a) => a.id))
  return addons.filter((a) => !kept.has(a.id))
}

/** OLD (price-locked) vs PROPOSED, side by side, with the server's difference (R-21). */
function Comparison({
  p,
  canCost,
  roomName,
  planName,
  addons,
}: {
  p: Proposal
  canCost: boolean
  roomName: (id: string) => string
  planName: (id: string | null | undefined) => string
  /** The reservation's extras added after booking (G-22). */
  addons: AddonEntry[]
}) {
  const { t } = useTexT()
  const clock = useServerClock()
  const ids = useId()
  const L = useLabels()
  const partyText = usePartyText()
  const a = p.old.request
  const b = p.proposed.request
  const diff = p.difference
  const dir = diff === null ? 0 : cmpDecimal(diff, "0")
  // limited extras with no capacity for the new stay: dropped (not charged) if applied (G-19)
  const dropped = p.warnings.filter((w) => w.code === EXTRA_SOLD_OUT)
  const others = p.warnings.filter((w) => w.code !== EXTRA_SOLD_OUT)
  const removed = removedBy(p, addons)
  const keptAddons = addons.filter((a) => !removed.includes(a))
  const facts: { label: string; old: ReactNode; neu: ReactNode; changed: boolean }[] = [
    {
      label: t("res.cmp.stay"),
      old: `${date(a.check_in)} – ${date(a.check_out)}`,
      neu: `${date(b.check_in)} – ${date(b.check_out)}`,
      changed: a.check_in !== b.check_in || a.check_out !== b.check_out,
    },
    {
      label: t("res.field.room_type"),
      old: roomName(a.room_type),
      neu: roomName(b.room_type),
      changed: a.room_type !== b.room_type,
    },
    { label: t("res.field.board"), old: L.board(a.board), neu: L.board(b.board), changed: a.board !== b.board },
    { label: t("res.field.rate_plan"), old: planName(a.rate_plan), neu: planName(b.rate_plan), changed: a.rate_plan !== b.rate_plan },
    {
      label: t("res.cmp.party"),
      old: partyText(a.adults, (a.children ?? []).map((c) => c.age)),
      neu: partyText(b.adults, (b.children ?? []).map((c) => c.age)),
      changed: JSON.stringify([a.adults, a.children?.map((c) => c.age)]) !== JSON.stringify([b.adults, b.children?.map((c) => c.age)]),
    },
    { label: t("crs.search.market"), old: a.market, neu: b.market, changed: a.market !== b.market },
    {
      label: t("crs.extras.title"),
      old: extrasText(a.extras),
      neu: extrasText(b.extras),
      changed: !sameChoices(a.extras ?? [], b.extras ?? []),
    },
    {
      label: t("crs.quote.promo"),
      old: (a.promo_codes ?? []).join(", ") || "—",
      neu: (b.promo_codes ?? []).join(", ") || "—",
      changed: (a.promo_codes ?? []).join(",") !== (b.promo_codes ?? []).join(","),
    },
    ...(addons.length
      ? [
          {
            label: t("res.cmp.addons"),
            old: addons.map(addonText).join("; "),
            neu: keptAddons.map(addonText).join("; ") || "—",
            changed: removed.length > 0,
          },
        ]
      : []),
  ]
  return (
    <div className="space-y-4">
      {/* OLD (locked) → PROPOSED and the server's difference: each figure is a group named by
          its caption, carrying the raw decimal in <data value> (screen readers and tests) */}
      <div
        className={cn(
          "flex flex-wrap items-end gap-x-3 gap-y-2 rounded-lg border px-4 py-3",
          dir > 0 ? "border-amber-200 bg-amber-50" : dir < 0 ? "border-emerald-200 bg-emerald-50" : "border-zinc-200 bg-zinc-50",
        )}
      >
        <div role="group" aria-labelledby={`${ids}-old`}>
          <p id={`${ids}-old`} className="text-xs text-zinc-500">
            {t("res.cmp.current")}
          </p>
          <p className="text-sm text-zinc-600">
            <data value={p.old.total}>
              <Money amount={p.old.total} currency={p.old.currency} />
            </data>
          </p>
        </div>
        <div role="group" aria-labelledby={`${ids}-new`}>
          <p id={`${ids}-new`} className="text-xs text-zinc-500">
            {t("res.cmp.proposed")}
          </p>
          <p className="flex items-center gap-1.5 text-lg font-semibold text-zinc-950">
            <ArrowRight className="size-4 text-zinc-400" aria-hidden />
            {p.proposed.sellable ? (
              <data value={p.proposed.totals.total}>
                <Money amount={p.proposed.totals.total} currency={p.proposed.currency} />
              </data>
            ) : (
              <span className="text-base font-medium text-rose-700">{t("res.cmp.not_sellable")}</span>
            )}
          </p>
        </div>
        <div role="group" aria-labelledby={`${ids}-diff`} className="ml-auto text-right">
          <p id={`${ids}-diff`} className="text-xs text-zinc-500">
            {t("res.cmp.difference")}
          </p>
          <p className="text-lg font-semibold">
            {diff === null ? (
              "—"
            ) : (
              <data value={diff}>{isZero(diff) ? t("res.cmp.no_change") : <Money amount={diff} currency={p.proposed.currency} signed />}</data>
            )}
          </p>
        </div>
      </div>
      <p className="text-xs text-zinc-600">
        {t("res.cmp.basis", {
          basis: L.basis(p.basis),
          // the server's detail ends with a raw timestamp; the formatted one follows in {at}
          detail: p.basis_detail.replace(/\s+(at|on sale at)\s+\d{4}-\d{2}-\d{2}[ T][\d:.]+$/, "").replace(/ on sale$/, ""),
          at: clock.label(p.pricing_sale_at),
        })}
      </p>
      {p.currency_changed && <Notice tone="warning">{t("res.cmp.currency_changed", { old: p.old.currency, neu: p.proposed.currency })}</Notice>}
      {removed.length > 0 && (
        <Notice tone="info" title={t("res.cmp.addons_removed", { count: removed.length })}>
          <p>{t("res.cmp.addons_removed_hint")}</p>
          <ul className="mt-1 list-disc pl-4 font-medium">
            {removed.map((x) => (
              <li key={x.id} data-addon={x.id} data-total={x.quote?.totals?.total ?? ""}>
                {addonText(x)}
              </li>
            ))}
          </ul>
        </Notice>
      )}
      {dropped.length > 0 && (
        <Notice tone="warning" title={t("res.cmp.extras_dropped")}>
          <p>{t("res.cmp.extras_dropped_hint")}</p>
          <ul className="mt-1 list-disc pl-4 font-medium">
            {dropped.map((w, i) => (
              <li key={i}>{extraWarningText(t, w.message)}</li>
            ))}
          </ul>
        </Notice>
      )}
      {others.length > 0 && (
        <Notice tone={p.sellable ? "warning" : "danger"} title={t("res.cmp.warnings")}>
          <ul className="list-disc pl-4">
            {others.map((w, i) => (
              <li key={i}>{w.message}</li>
            ))}
          </ul>
        </Notice>
      )}
      {!p.proposed.sellable && p.proposed.reasons.length > 0 && (
        <Notice tone="danger" title={t("res.cmp.not_sellable")}>
          <ul className="list-disc pl-4">
            {p.proposed.reasons.map((w, i) => (
              <li key={i}>{w.message}</li>
            ))}
          </ul>
        </Notice>
      )}

      <dl className="divide-y divide-zinc-100 border-y border-zinc-100 text-sm sm:hidden">
        {facts.map((f) => (
          <div key={f.label} className="py-1.5">
            <dt className="text-xs font-medium text-zinc-500">
              {f.label}
              {f.changed && (
                <Badge tone="brand" className="ml-1.5">
                  {t("res.cmp.changed")}
                </Badge>
              )}
            </dt>
            <dd className="text-zinc-800">
              {f.changed ? (
                <>
                  <span className="text-zinc-500 line-through decoration-zinc-400">{f.old}</span>
                  <span className="sr-only"> {t("res.rev.to")} </span>
                  <span aria-hidden> → </span>
                  <span className="font-semibold text-zinc-950">{f.neu}</span>
                </>
              ) : (
                f.neu
              )}
            </dd>
          </div>
        ))}
      </dl>
      <div className="hidden overflow-x-auto sm:block">
        <table className="w-full min-w-[32rem] text-sm">
          <caption className="sr-only">{t("res.cmp.caption")}</caption>
          <thead>
            <tr className="border-b border-zinc-200 text-left text-xs font-semibold tracking-wide text-zinc-500 uppercase">
              <th scope="col" className="w-32 py-1.5 pr-2">
                <span className="sr-only">{t("res.cmp.field")}</span>
              </th>
              <th scope="col" className="py-1.5 pr-2">
                {t("res.cmp.current")}
              </th>
              <th scope="col" className="py-1.5">
                {t("res.cmp.proposed")}
              </th>
            </tr>
          </thead>
          <tbody>
            {facts.map((f) => (
              <tr key={f.label} className="border-b border-zinc-100 align-top">
                <th scope="row" className="py-1.5 pr-2 text-left text-xs font-medium text-zinc-500">
                  {f.label}
                </th>
                <td className="py-1.5 pr-2 text-zinc-700">{f.old}</td>
                <td className={cn("py-1.5", f.changed ? "font-semibold text-zinc-950" : "text-zinc-700")}>
                  {f.neu}
                  {f.changed && (
                    <Badge tone="brand" className="ml-1.5">
                      {t("res.cmp.changed")}
                    </Badge>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-zinc-200 p-3">
          <p className="mb-2 text-xs font-semibold tracking-wide text-zinc-500 uppercase">{t("res.cmp.current")}</p>
          {p.old.lines && p.old.totals ? (
            <PriceBreakdown
              quote={{ lines: p.old.lines, totals: p.old.totals, currency: p.old.currency, taxes: [], promotions: [], extras: [] }}
              canCost={canCost}
              showNightly={false}
            />
          ) : (
            <p className="text-sm">
              <Money amount={p.old.total} currency={p.old.currency} />
            </p>
          )}
          {p.old.contract && (
            <p className="mt-2 text-xs text-zinc-500">{t("res.snap.contract", { code: p.old.contract.code, version: p.old.contract.version_no })}</p>
          )}
        </div>
        <div className="rounded-lg border border-tex-200 bg-tex-50/40 p-3">
          <p className="mb-2 text-xs font-semibold tracking-wide text-tex-800 uppercase">{t("res.cmp.proposed")}</p>
          {p.proposed.sellable ? (
            <PriceBreakdown quote={p.proposed} canCost={canCost} showNightly={false} />
          ) : (
            <p className="text-sm text-rose-700">{t("res.cmp.not_sellable")}</p>
          )}
          {p.proposed.contract && (
            <p className="mt-2 text-xs text-zinc-500">{t("res.snap.contract", { code: p.proposed.contract.code, version: p.proposed.contract.version_no })}</p>
          )}
        </div>
      </div>
      {canCost && p.proposed.explanation && p.proposed.explanation.length > 0 && <ExplanationList steps={p.proposed.explanation} />}
    </div>
  )
}
