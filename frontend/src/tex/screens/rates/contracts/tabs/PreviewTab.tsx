import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Calculator, CheckCircle2, LocateFixed, Minus, Plus, XCircle } from "lucide-react"
import { cn } from "../../../../../lib/utils"
import { tex, TexApiError } from "../../../../lib/api"
import { useSession } from "../../../../lib/session"
import { date as fmtDate, dateTime, minorUnits as currencyMinorUnits, money, nightsBetween, weekday } from "../../../../lib/format"
import { useSiteClock } from "../../../../lib/siteDay"
import { useTexT } from "../../../../i18n"
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  DataTable,
  DescriptionList,
  EmptyState,
  ErrorState,
  Field,
  FormGrid,
  IconButton,
  InlineError,
  Input,
  Money,
  Notice,
  Select,
  Skeleton,
  Switch,
} from "../../../../ui"
import { BOARDS, enumLabel, enumOptions } from "../../lib/options"
import { IssueList } from "../../components/common"
import { overlayPayloadOf } from "../../lib/tables"
import type { ExplainStep, Issue, NightLine, PreviewChild, PreviewResult, VersionDoc } from "../../lib/types"
import { decText, splitCsv, toFrappeDatetime, versionLabel } from "../../lib/util"
import { bandCode, effectiveBands } from "../../workspace/bands.ts"
import { MATRIX_DEBOUNCE_MS } from "../../workspace/draftPreview.ts"
import { ExplainLadderView, useStepText } from "../../workspace/ExplainLadder"
import { childPayload, prefillOf, showTargetOf, withChildMode, type ChildEntry, type ChildMode, type ShowTarget } from "../../workspace/priceTest.ts"
import { useBandLabels } from "../../workspace/useBandLabels"
import type { DraftPreview } from "../../workspace/useDraftPreview"
import { contractRoomOptions, TabIntro, type TabProps } from "./shared"

const LEVELS = ["GLOBAL", "HOTEL", "MARKET", "CONTRACT", "VERSION", "ROOM", "PERIOD", "COMBINATION", "OVERRIDE"]

/** Preview & audit (PRICING_WORKSPACE_UX.md §2): the full Price test, the resolved price matrix,
 * every issue and the version's facts. Nothing is priced in the browser. */
export function PreviewTab(props: TabProps) {
  const { t } = useTexT()
  return (
    <div className="space-y-5">
      <TabIntro title={t("rates.section.preview")}>{t("rates.preview.intro")}</TabIntro>
      <PriceTestPanel {...props} />
      <MatrixCard preview={props.preview} dirty={props.dirty} />
      <IssuesCard doc={props.doc} preview={props.preview} dirty={props.dirty} format={props.issueText} />
      <VersionInfo doc={props.doc} />
    </div>
  )
}

/** Where the Price test starts (S14): "Test this price" on a matrix cell, or the header's Price
 * test from the matrix cell that last had the focus; `n` repeats a request. */
export interface PriceTestPrefill {
  room?: string
  period?: string
  n: number
}

/** The price test ("Why this price", preview_price, PRICING_WORKSPACE_UX.md §3.13): shown when the
 * server says the viewer may see contract cost on this version's hotel (`can_preview`, GAP-10); an
 * editor's unsaved changes are priced as shown (the read-only overlay, GAP-1), without a save. */
export function PriceTestPanel(props: TabProps & { layout?: "page" | "drawer"; prefill?: PriceTestPrefill | null }) {
  const { t } = useTexT()
  const { can } = useSession()
  const { doc } = props
  if (!(doc.can_preview ?? can("price.view_cost", doc.contract_doc.property))) return <Notice tone="info">{t("rates.preview.needs_cost")}</Notice>
  return (
    <div className="space-y-4">
      {doc.editable && props.dirty && <Notice tone="info">{props.preview?.savedOnly ? t("rates.preview.unsaved") : t("rates.preview.priced_unsaved")}</Notice>}
      <PriceTestForm {...props} />
    </div>
  )
}

interface Form {
  room_type: string
  board: string
  rate_plan: string
  check_in: string
  check_out: string
  adults: number
  children: ChildEntry[]
  market: string
  channel: string
  currency: string
  sale_at: string
  promo: string
}

const CHILD_MODES: ChildMode[] = ["years", "months", "dob"]

function PriceTestForm({ doc, state, dirty, preview, layout = "page", prefill, showInGrid }: TabProps & { layout?: "page" | "drawer"; prefill?: PriceTestPrefill | null }) {
  const { t } = useTexT()
  const { boot, can } = useSession()
  const canCost = doc.can_preview ?? can("price.view_cost", doc.contract_doc.property)
  const clock = useSiteClock()
  const rooms = contractRoomOptions(doc, state)
  const boardCodes = Array.from(new Set(state.tables.boards.map((b) => String(b.board)).filter(Boolean)))
  const baseBoard = String(state.tables.boards.find((b) => b.is_base)?.board ?? boardCodes[0] ?? "BB")
  const plans = state.tables.rate_plans.map((r) => String(r.rate_plan)).filter(Boolean)
  const stay = state.selling ?? doc.selling
  /** the stay a request (or none) starts from: the active matrix cell's room and period (§3.13) */
  const prefillFrom = (at: PriceTestPrefill | null | undefined) =>
    prefillOf({
      rooms: rooms.map((r) => r.value),
      baseRoom: String(state.tables.rooms.find((r) => r.is_base)?.room_type ?? ""),
      periods: state.tables.periods.map((p) => ({ code: String(p.period_code ?? "").trim(), start: String(p.start_date ?? ""), end: String(p.end_date ?? "") })),
      stayFrom: stay?.stay_from,
      stayTo: stay?.stay_to,
      active: at ? { room: at.room, period: at.period } : null,
      today: clock.today(),
    })
  const [f, setF] = useState<Form>(() => {
    const start = prefillFrom(prefill)
    return {
      room_type: start.room,
      board: baseBoard,
      rate_plan: plans[0] ?? "",
      check_in: start.checkIn,
      check_out: start.checkOut,
      adults: 2,
      children: [],
      market: doc.contract_doc.market,
      channel: boot.settings.default_sales_channel || "DIRECT_WEB",
      currency: doc.contract_doc.contract_currency,
      sale_at: "",
      promo: "",
    }
  })
  // another "Test this price" while the drawer is open: its room and dates
  const applied = useRef(prefill?.n ?? 0)
  useEffect(() => {
    if (!prefill || prefill.n === applied.current) return
    applied.current = prefill.n
    const start = prefillFrom(prefill)
    setF((x) => ({ ...x, room_type: start.room, check_in: start.checkIn, check_out: start.checkOut }))
    // the request's content is its number
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill])

  const [res, setRes] = useState<PreviewResult>()
  const [err, setErr] = useState<TexApiError>()
  const [busy, setBusy] = useState(false)
  const [live, setLive] = useState(false)
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }))
  const setChild = (i: number, c: ChildEntry) => set("children", f.children.map((x, j) => (j === i ? c : x)))
  const nights = f.check_in && f.check_out ? nightsBetween(f.check_in, f.check_out) : 0
  const children = f.children.map(childPayload)
  const childOk = children.every((c) => c !== null)
  const valid = Boolean(f.room_type && f.board && nights > 0 && nights <= 90 && childOk && (plans.length === 0 || f.rate_plan))
  const withData = Boolean(doc.editable && dirty && !preview?.savedOnly)
  const args = {
    version: doc.name,
    room_type: f.room_type,
    board: f.board,
    rate_plan: f.rate_plan || null,
    check_in: f.check_in,
    check_out: f.check_out,
    adults: f.adults,
    children: children as PreviewChild[],
    market: f.market || null,
    channel: f.channel,
    currency: f.currency || null,
    sale_at: toFrappeDatetime(f.sale_at),
    promo_codes: splitCsv(f.promo).map((c) => c.toUpperCase()),
  }
  // what a result answers: the inputs and the draft priced (its fingerprint, or the saved draft)
  const key = JSON.stringify([args, withData ? (preview?.key ?? "") : "saved", doc.modified])
  const [resKey, setResKey] = useState("")
  const latest = useRef({ args, key, withData, state })
  latest.current = { args, key, withData, state }
  const flight = useRef<AbortController | null>(null)
  useEffect(() => () => flight.current?.abort(), [])

  const run = useCallback(async () => {
    const { args: a, key: k, withData: wd, state: st } = latest.current
    flight.current?.abort()
    const ctl = new AbortController()
    flight.current = ctl
    setBusy(true)
    setErr(undefined)
    try {
      const r = await tex<PreviewResult>(
        "contracts",
        "preview_price",
        // unsaved edits are priced as shown, never saved (the read-only overlay, GAP-1); above the
        // overlay's row cap the saved draft is priced, as the notice says
        { ...a, ...(wd ? { data: overlayPayloadOf(st) } : {}) },
        { post: true, signal: ctl.signal },
      )
      if (ctl.signal.aborted) return
      setRes(r)
      setResKey(k)
    } catch (e) {
      if ((e as Error | undefined)?.name === "AbortError") return
      setErr(e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error"))
    } finally {
      if (flight.current === ctl) {
        flight.current = null
        setBusy(false)
      }
    }
  }, [])

  // Live: after a result, a settled edit (of the form, or of the draft: its fingerprint) prices again
  useEffect(() => {
    if (!live || !valid || key === resKey) return
    const timer = setTimeout(() => void run(), MATRIX_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [live, valid, key, resKey, run])
  const stale = Boolean(res && resKey !== key)

  const modeLabel = (m: ChildMode) => t(`rates.pt.child_mode.${m}`)
  return (
    <>
      <Card>
        <CardHeader title={t("rates.preview.calculator")} description={t("rates.preview.calculator_hint")} />
        <CardBody>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              if (valid) void run()
            }}
          >
            <FormGrid cols={layout === "drawer" ? 2 : 4}>
              <Field label={t("rates.f.room_type")} required>
                <Select value={f.room_type} onChange={(e) => set("room_type", e.target.value)} options={rooms} placeholder={rooms.length ? undefined : t("rates.common.choose")} />
              </Field>
              <Field label={t("rates.f.board")} required>
                <Select value={f.board} onChange={(e) => set("board", e.target.value)} options={enumOptions(t, "board", boardCodes.length ? boardCodes : BOARDS)} />
              </Field>
              <Field label={t("rates.f.rate_plan")} required={plans.length > 0} hint={plans.length ? undefined : t("rates.preview.no_plans")}>
                <Select
                  value={f.rate_plan}
                  onChange={(e) => set("rate_plan", e.target.value)}
                  disabled={!plans.length}
                  options={plans.map((p) => ({ value: p, label: doc.rate_plan_options.find((o) => o.name === p)?.rate_plan_name ?? p }))}
                  placeholder={plans.length ? undefined : "—"}
                />
              </Field>
              <Field label={t("rates.f.adults")} required>
                <Input type="number" min={1} max={12} value={String(f.adults)} onChange={(e) => set("adults", Math.max(1, Math.min(12, parseInt(e.target.value || "1", 10) || 1)))} />
              </Field>
              <Field label={t("rates.f.check_in")} required>
                <Input type="date" value={f.check_in} onChange={(e) => set("check_in", e.target.value)} />
              </Field>
              <Field label={t("rates.f.check_out")} required error={f.check_in && f.check_out && nights <= 0 ? t("rates.v.checkout_after") : undefined} hint={nights > 0 ? t("core.label.nights", { count: nights }) : undefined}>
                <Input type="date" value={f.check_out} onChange={(e) => set("check_out", e.target.value)} />
              </Field>
              <Field label={t("rates.f.market")} hint={t("rates.h.preview_market")}>
                <Select value={f.market} onChange={(e) => set("market", e.target.value)} options={boot.markets.map((m) => ({ value: m.name, label: `${m.name} · ${m.market_name}` }))} />
              </Field>
              <Field label={t("rates.f.channel")}>
                <Select value={f.channel} onChange={(e) => set("channel", e.target.value)} options={boot.channels.map((c) => ({ value: c.name, label: c.channel_name }))} />
              </Field>
              <Field label={t("rates.f.sell_currency")} hint={t("rates.h.preview_currency")}>
                <Select value={f.currency} onChange={(e) => set("currency", e.target.value)} options={boot.currencies.map((c) => ({ value: c, label: c }))} />
              </Field>
              <Field label={t("rates.f.sale_at")} hint={t("rates.h.sale_at")}>
                <Input type="datetime-local" value={f.sale_at} onChange={(e) => set("sale_at", e.target.value)} />
              </Field>
              <Field label={t("rates.f.promo_codes")} hint={t("rates.h.promo_codes")}>
                <Input value={f.promo} onChange={(e) => set("promo", e.target.value)} placeholder="EARLY10" autoCapitalize="characters" />
              </Field>
            </FormGrid>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium text-zinc-800">{t("rates.f.children_ages")}</legend>
              <p className="text-xs text-zinc-500">
                {t("rates.h.children_ages")} {t("rates.pt.children_exact")}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                {f.children.map((c, i) => {
                  const n = i + 1
                  const bad = children[i] === null
                  return (
                    <span key={i} className="inline-flex items-center gap-1 rounded-lg border border-zinc-200 p-1">
                      {c.mode === "dob" ? (
                        <Input type="date" aria-label={t("rates.pt.child_dob", { n })} value={c.value} max={f.check_in || undefined} onChange={(e) => setChild(i, { ...c, value: e.target.value })} className="w-40!" aria-invalid={bad || undefined} />
                      ) : (
                        <Input
                          aria-label={c.mode === "months" ? t("rates.pt.child_months", { n }) : t("rates.preview.child_age", { n })}
                          inputMode="numeric"
                          value={c.value}
                          onChange={(e) => setChild(i, { ...c, value: e.target.value.replace(/\D/g, "").slice(0, c.mode === "months" ? 3 : 2) })}
                          className="w-16! text-right"
                          aria-invalid={bad || undefined}
                        />
                      )}
                      <Select
                        aria-label={t("rates.pt.child_mode_label", { n })}
                        value={c.mode}
                        onChange={(e) => setChild(i, withChildMode(c, e.target.value as ChildMode))}
                        options={CHILD_MODES.map((m) => ({ value: m, label: modeLabel(m) }))}
                        className="h-9! w-auto! text-xs!"
                      />
                      <IconButton size="sm" label={t("rates.preview.remove_child", { n })} icon={<Minus className="size-4" />} onClick={() => set("children", f.children.filter((_, j) => j !== i))} />
                    </span>
                  )
                })}
                {f.children.length < 6 && (
                  <Button variant="secondary" size="sm" icon={<Plus className="size-4" aria-hidden />} onClick={() => set("children", [...f.children, { mode: "years", value: "5" }])}>
                    {t("rates.preview.add_child")}
                  </Button>
                )}
              </div>
            </fieldset>
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" loading={busy} disabled={!valid} icon={<Calculator className="size-4" aria-hidden />} shortcut="↵">
                {t("rates.preview.run")}
              </Button>
              {res && (
                <Switch checked={live} onChange={setLive} label={<span className="text-sm font-normal">{t("rates.pt.live")}</span>} description={t("rates.pt.live_hint")} />
              )}
              <span className="text-xs text-zinc-500">{t("rates.preview.on_version", { v: versionLabel(doc.name, doc.version_no), status: t(`rates.version_status.${doc.status}`) })}</span>
            </div>
            <InlineError error={err} />
          </form>
        </CardBody>
      </Card>
      {res && (
        <div className={cn("space-y-3 transition-opacity", stale && "opacity-60")} aria-busy={busy || undefined}>
          {stale && (
            <p role="status" className="text-xs text-zinc-600">
              {live ? t("rates.pt.updating") : t("rates.pt.stale")}
            </p>
          )}
          <PreviewResultView res={res} canCost={canCost} layout={layout} doc={doc} state={state} preview={preview} showInGrid={showInGrid} />
        </div>
      )}
    </>
  )
}

function PreviewResultView({
  res,
  canCost,
  layout,
  doc,
  state,
  preview,
  showInGrid,
}: {
  res: PreviewResult
  canCost: boolean
  layout: "page" | "drawer"
  doc: VersionDoc
  state: TabProps["state"]
  preview?: DraftPreview
  showInGrid?: (target: ShowTarget) => void
}) {
  const { t } = useTexT()
  const ccy = res.currency ?? ""
  const contractCcy = res.contract?.currency ?? ccy
  const nights = res.nights ?? []
  const [night, setNight] = useState<string>(nights[0]?.date ?? "")
  const steps = useMemo(() => (res.explanation ?? []).filter((s) => !s.night || !night || s.night === night), [res.explanation, night])
  // band codes are shown as labels everywhere (D13): the draft's bands, else the inherited ones
  const bands = useMemo(() => effectiveBands(state.tables, preview?.matrix?.age_bands), [state.tables, preview?.matrix?.age_bands])
  const labels = useBandLabels(bands)
  const names = useMemo(() => new Map(doc.room_types.map((r) => [r.name, r.room_type_name || r.name])), [doc.room_types])
  const roomName = useCallback((rt: string) => names.get(rt) ?? rt, [names])
  const stepText = useStepText(labels, roomName)
  const allCodes = useMemo(() => bands.map(bandCode).filter(Boolean), [bands])
  // "Show in grid": the draft row each rule id names, looked up once per rule id and table state
  const targets = useMemo(() => new Map<string, ShowTarget | null>(), [state.tables])
  const targetOf = (ruleId: string | null | undefined): ShowTarget | null => {
    if (!showInGrid || !ruleId) return null
    if (!targets.has(ruleId)) targets.set(ruleId, showTargetOf(state.tables, ruleId))
    return targets.get(ruleId) ?? null
  }
  const minorUnits = doc.contract_doc.minor_units ?? currencyMinorUnits(contractCcy)
  const page = layout === "page"

  if (!res.sellable)
    return (
      <Notice tone="danger" title={t("rates.preview.unsellable")}>
        <ul className="mt-1 list-disc pl-5">
          {res.reasons.map((r, i) => (
            <li key={i}>
              <span className="font-mono text-xs opacity-70">{r.code}</span> {labels.display(r.message, r.code === "NO_CHILD_RULE" ? allCodes : undefined)}
            </li>
          ))}
        </ul>
      </Notice>
    )

  const tot = res.totals ?? {}
  return (
    <div className="space-y-5" aria-live="polite">
      <div className={cn("grid gap-5", page && "lg:grid-cols-3")}>
        <Card className={page ? "lg:col-span-2" : undefined}>
          <CardHeader
            title={t("rates.preview.result")}
            description={res.contract ? `${res.contract.code} · V${res.contract.version_no} · ${res.contract.market} · ${enumLabel(t, "basis", res.contract.basis)}` : undefined}
            actions={
              res.rate_plan && (
                <Badge tone={res.rate_plan.refundable ? "success" : "warning"}>
                  {res.rate_plan.name} · {res.rate_plan.refundable ? t("rates.f.refundable") : t("rates.plans.non_refundable")}
                </Badge>
              )
            }
          />
          <CardBody className="space-y-4">
            <div className="flex flex-wrap items-end gap-x-8 gap-y-2">
              <div>
                <p id="pv-total-label" className="text-xs font-medium tracking-wide text-zinc-500 uppercase">
                  {t("core.label.total")}
                </p>
                {/* <output>: the result of the server calculation, named "Total" for assistive tech */}
                <output aria-labelledby="pv-total-label" className="block text-3xl font-semibold tracking-tight text-zinc-950">
                  <Money amount={tot.total} currency={ccy} />
                </output>
              </div>
              {canCost && tot.cost !== undefined && (
                <>
                  <div>
                    <p className="text-xs text-zinc-500">{t("rates.preview.cost")}</p>
                    <p className="text-lg font-medium">
                      <Money amount={tot.cost} currency={ccy} />
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-zinc-500">{t("rates.preview.margin")}</p>
                    <p className="text-lg font-medium">
                      <Money amount={tot.margin} currency={ccy} /> <span className="text-sm text-zinc-500">({decText(tot.margin_percent)} %)</span>
                    </p>
                  </div>
                </>
              )}
            </div>
            <dl className={cn("grid grid-cols-2 gap-x-6 gap-y-1 text-sm", page && "sm:grid-cols-3")}>
              {(["accommodation_gross", "accommodation_discount", "accommodation", "extras", "discounts", "subtotal", "tax", "tax_added"] as const).map((k) =>
                tot[k] !== undefined ? (
                  <div key={k} className="flex justify-between gap-2 border-b border-zinc-100 py-1">
                    <dt className="text-zinc-600">{t(`rates.preview.tot.${k}`)}</dt>
                    <dd>
                      <Money amount={tot[k]} currency={ccy} />
                    </dd>
                  </div>
                ) : null,
              )}
            </dl>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t("rates.preview.terms")} />
          <CardBody className="space-y-3 text-sm">
            {res.fx && (
              <div>
                <p className="text-xs text-zinc-500">{t("rates.preview.fx")}</p>
                <p>
                  {res.fx.from} → {res.fx.to} · {enumLabel(t, "fx_mode", res.fx.mode)}
                  {res.fx.mode !== "IDENTITY" && (
                    <>
                      {" "}
                      · {t("rates.preview.fx_rate", { rate: decText(res.fx.sell_rate, 0) })}
                      {res.fx.provider_rate && ` (${res.fx.provider} ${decText(res.fx.provider_rate, 0)})`}
                    </>
                  )}
                </p>
              </div>
            )}
            {res.rate_plan?.cancellation_policy && (
              <div>
                <p className="text-xs text-zinc-500">{t("rates.f.cancellation_policy")}</p>
                <p>{res.rate_plan.cancellation_policy.name}</p>
                {res.rate_plan.cancellation_policy.description && <p className="text-xs text-zinc-500">{res.rate_plan.cancellation_policy.description}</p>}
              </div>
            )}
            {res.rate_plan?.payment_policy && (
              <div>
                <p className="text-xs text-zinc-500">{t("rates.f.payment_policy")}</p>
                <p>{res.rate_plan.payment_policy.name}</p>
              </div>
            )}
            {(res.promotions ?? []).length > 0 && (
              <div>
                <p className="text-xs text-zinc-500">{t("rates.preview.promotions")}</p>
                <ul className="mt-1 space-y-1">
                  {res.promotions!.map((p) => (
                    <li key={p.promo_id} className="flex items-start gap-1.5">
                      {p.applied ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-hidden /> : <XCircle className="mt-0.5 size-4 shrink-0 text-zinc-400" aria-hidden />}
                      <span>
                        <span className="font-medium">{p.name}</span>{" "}
                        <span className="text-zinc-500">
                          {p.applied ? t("rates.preview.promo_applied", { amount: decText(p.discount) }) : t("rates.preview.promo_not_applied", { reason: p.reason })}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* the Explain ladder (§3.13.1): the stages in engine order, every value a server field */}
      <Card>
        <CardBody>
          <ExplainLadderView res={res} stepText={stepText} periods={state.tables.periods} minorUnits={minorUnits} sellMinorUnits={currencyMinorUnits(ccy)} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t("rates.preview.nightly")} description={t("rates.preview.nightly_hint", { contract: contractCcy, sell: ccy })} />
        <DataTable<NightLine>
          caption={t("rates.preview.nightly")}
          rows={nights}
          rowKey={(n) => n.date}
          dense
          columns={[
            { key: "date", header: t("rates.preview.col.night"), cell: (n) => <span className="whitespace-nowrap">{weekday(n.date)} {fmtDate(n.date)}</span> },
            { key: "period", header: t("rates.f.period"), hideBelow: "sm" },
            { key: "unit", header: t("rates.preview.col.unit"), align: "right", hideBelow: "md", cell: (n) => decText(n.unit) },
            { key: "occupancy", header: t("rates.preview.col.occupancy"), align: "right", hideBelow: "md", cell: (n) => decText(n.occupancy) },
            { key: "board", header: t("rates.f.board"), align: "right", hideBelow: "md", cell: (n) => decText(n.board) },
            ...(canCost
              ? [
                  { key: "cost", header: t("rates.preview.col.cost"), align: "right" as const, cell: (n: NightLine) => decText(n.cost_net) },
                  { key: "sell_contract", header: t("rates.preview.col.markup"), align: "right" as const, hideBelow: "lg" as const, cell: (n: NightLine) => decText(n.sell_contract) },
                ]
              : []),
            { key: "sell", header: t("rates.preview.col.sell"), align: "right", hideBelow: "sm", cell: (n) => decText(n.sell) },
            { key: "final", header: t("rates.preview.col.final"), align: "right", cell: (n) => <span className="font-medium">{decText(n.final)}</span> },
          ]}
        />
      </Card>

      <Card>
        <CardHeader
          title={t("rates.preview.why")}
          description={t("rates.preview.why_hint")}
          actions={
            nights.length > 1 && (
              <Field label={t("rates.preview.show_night")} inline>
                <Select
                  value={night}
                  onChange={(e) => setNight(e.target.value)}
                  options={[{ value: "", label: t("rates.preview.all_nights") }, ...nights.map((n) => ({ value: n.date, label: `${weekday(n.date)} ${fmtDate(n.date, "short")}` }))]}
                  className="w-44"
                />
              </Field>
            )
          }
        />
        <CardBody>
          <ol className="space-y-1.5" aria-label={t("rates.preview.why")}>
            {steps.map((s, i) => (
              <StepItem key={i} s={s} text={stepText(s)} display={labels.display} target={targetOf(s.rule?.rule_id)} onShow={showInGrid} />
            ))}
          </ol>
          <p className="mt-4 text-xs text-zinc-500">
            {t("rates.preview.precedence")}{" "}
            {LEVELS.map((l, i) => (
              <span key={l}>
                {i > 0 && " < "}
                {t(`rates.level.${l}`)}
              </span>
            ))}
          </p>
        </CardBody>
      </Card>
    </div>
  )
}

const STAGE_TONE: Record<string, "neutral" | "info" | "success" | "warning" | "danger" | "brand"> = {
  contract: "brand",
  period: "neutral",
  room: "info",
  occupancy: "info",
  board: "info",
  rate_plan: "info",
  night: "neutral",
  markup: "warning",
  fx: "warning",
  promotion: "success",
  extra: "neutral",
  tax: "neutral",
  total: "brand",
}

/** One step of "Why this price": the stage, the sentence (localised, band labels), the rule that
 * won with its level, what it overrode, and "Show in grid" when the rule is a row of the draft. */
function StepItem({ s, text, display, target, onShow }: { s: ExplainStep; text: string; display: (text: string) => string; target: ShowTarget | null; onShow?: (target: ShowTarget) => void }) {
  const { t } = useTexT()
  const stage = t(`rates.stage.${s.stage}`)
  const ruleLabel = s.rule ? display(s.rule.label || s.rule.rule_id) : ""
  return (
    <li className={cn("flex flex-wrap items-start gap-2 rounded-md px-2 py-1.5 text-sm", s.stage === "total" ? "bg-tex-50" : "hover:bg-zinc-50")}>
      <Badge tone={STAGE_TONE[s.stage] ?? "neutral"} className="min-w-20 justify-center">
        {stage.startsWith("rates.stage.") ? s.stage : stage}
      </Badge>
      <div className="min-w-0 flex-1">
        <p className="text-zinc-900">{text}</p>
        {(s.rule || s.overridden.length > 0) && (
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-zinc-500">
            {s.rule && (
              <>
                <span>{t("rates.preview.won")}</span>
                {s.rule.level && <Badge tone="neutral">{t(`rates.level.${s.rule.level}`)}</Badge>}
                <span className="font-medium text-zinc-700">{ruleLabel}</span>
                {s.rule.source && <span className="font-mono">({s.rule.source})</span>}
              </>
            )}
            {s.overridden.length > 0 && (
              <span>
                · {t("rates.preview.overrode")} {s.overridden.map((o) => display(o.label || o.rule_id)).join(", ")}
              </span>
            )}
            {target && onShow && (
              <button
                type="button"
                onClick={() => onShow(target)}
                aria-label={t("rates.pt.show_in_grid_rule", { rule: ruleLabel })}
                className="inline-flex items-center gap-0.5 rounded px-1 font-medium text-tex-700 underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-tex-500 focus-visible:outline-none"
              >
                <LocateFixed className="size-3" aria-hidden />
                {t("rates.pt.show_in_grid")}
              </button>
            )}
          </p>
        )}
      </div>
      {s.after !== null && s.before !== null && (
        <span className="text-xs whitespace-nowrap text-zinc-600 tabular-nums">
          {decText(s.before)} → <span className="font-medium text-zinc-900">{decText(s.after)}</span>
        </span>
      )}
    </li>
  )
}

/** The server's nightly unit per room and period (price_matrix), from the editor's live preview:
 * unsaved changes included for an editor (overlay), the stored version otherwise; never fetched
 * for a viewer without cost (catalogue). */
export function MatrixCard({ preview, dirty }: { preview?: DraftPreview; dirty?: boolean }) {
  const { t } = useTexT()
  if (!preview || preview.mode === "catalogue") return null
  const m = preview.matrix
  // an older matrix is dimmed while the one for the screen is on its way; when its call failed,
  // the failure is shown with Try again instead (not an older matrix as if it were current)
  const busy = preview.matrixState === "busy"
  return (
    <Card>
      <CardHeader
        title={t("rates.preview.matrix")}
        description={m ? t(`rates.rates.unit.${m.basis}`, { ccy: m.currency }) : t("rates.preview.matrix_hint")}
        actions={
          <span className="flex flex-wrap items-center gap-2">
            {preview.mode === "overlay" && dirty && !preview.savedOnly && <Badge tone="info">{t("rates.ws.unsaved_included")}</Badge>}
            {preview.savedOnly && dirty && <Badge tone="warning">{t("rates.ws.saved_only")}</Badge>}
            {m && busy && (
              <span className="text-xs text-zinc-500" role="status">
                {t("rates.ws.updating")}
              </span>
            )}
          </span>
        }
      />
      {preview.savedOnly && dirty && (
        <CardBody className="pb-0">
          <Notice tone="warning">{t("rates.ws.over_cap", { max: preview.maxRows ?? "" })}</Notice>
        </CardBody>
      )}
      {preview.matrixState === "failed" && preview.error ? (
        <ErrorState error={preview.error} onRetry={preview.refetch} />
      ) : preview.buildError && !preview.stale ? (
        <CardBody>
          <Notice tone="warning" title={t("rates.ws.build_error")}>
            <span className="whitespace-pre-line">{preview.buildError}</span>
          </Notice>
        </CardBody>
      ) : !m ? (
        <CardBody>
          <Skeleton className="h-24 w-full" />
        </CardBody>
      ) : m.rooms.length === 0 ? (
        <EmptyState title={t("rates.rates.need_rooms_periods")} />
      ) : (
        <div className={cn("max-h-[60vh] overflow-auto transition-opacity", busy && "opacity-60")} aria-busy={busy || undefined}>
          <table className="min-w-full border-separate border-spacing-0 text-sm">
            <caption className="sr-only">{t("rates.preview.matrix")}</caption>
            <thead>
              <tr>
                <th scope="col" className="sticky top-0 left-0 z-[3] border-r border-b border-zinc-200 bg-zinc-50 px-3 py-2 text-left text-xs font-semibold text-zinc-600">
                  {t("rates.f.room_type")}
                </th>
                {m.periods.map((p) => (
                  <th key={p.code} scope="col" className="sticky top-0 z-[2] border-b border-zinc-200 bg-zinc-50 px-3 py-2 text-right text-xs font-semibold text-zinc-700">
                    <span className="block">{p.code}</span>
                    <span className="block font-normal whitespace-nowrap text-zinc-500">
                      {fmtDate(p.start, "short")} – {fmtDate(p.end, "short")}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {m.rooms.map((r) => (
                <tr key={r.room_type}>
                  <th scope="row" className="sticky left-0 z-[1] border-r border-b border-zinc-100 bg-white px-3 py-2 text-left font-medium whitespace-nowrap text-zinc-900">
                    {r.name}
                  </th>
                  {m.periods.map((p) => {
                    const v = r.cells[p.code]
                    const e = r.errors?.[p.code]
                    return (
                      <td key={p.code} className="border-b border-zinc-100 px-3 py-2 text-right tabular-nums" title={e}>
                        {v !== null && v !== undefined ? money(v, m.currency) : <span className="text-rose-700">{e ? t("rates.rates.unsellable") : "—"}</span>}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

/** Every issue: the live check of what the editor shows, or the report stored at publish. */
function IssuesCard({ doc, preview, dirty, format }: { doc: VersionDoc; preview?: DraftPreview; dirty: boolean; format?: (issue: Issue) => string }) {
  const { t } = useTexT()
  if (!preview || preview.issuesSource === "none") return null
  const live = preview.issuesSource === "live"
  const busy = live && preview.issuesState === "busy"
  const failed = live && preview.issuesState === "failed"
  const description = !live
    ? doc.published_at
      ? t("rates.ws.check.published_at", { at: dateTime(doc.published_at) })
      : undefined
    : preview.savedOnly && dirty
      ? t("rates.ws.over_cap", { max: preview.maxRows ?? "" })
      : dirty
        ? t("rates.ws.check.live_unsaved")
        : t("rates.ws.check.live_saved")
  return (
    <Card>
      <CardHeader
        title={live ? t("rates.ws.check.live") : t("rates.ws.check.published")}
        description={description}
        actions={
          busy && (
            <span className="text-xs text-zinc-500" role="status">
              {t("rates.version.checking")}
            </span>
          )
        }
      />
      <CardBody className={cn("space-y-3", busy && preview.issuesStale && "opacity-60")}>
        {failed ? (
          <Notice tone="warning" title={t("rates.ws.check.failed")}>
            <span className="block whitespace-pre-line">{preview.issuesError?.message}</span>
            <Button variant="secondary" size="sm" className="mt-2" onClick={preview.refetch}>
              {t("core.action.retry")}
            </Button>
          </Notice>
        ) : preview.issues ? (
          <IssueList issues={preview.issues} emptyOk={t("rates.ws.check.clean")} format={format} />
        ) : (
          <Skeleton className="h-10 w-full" />
        )}
      </CardBody>
    </Card>
  )
}

/** What the version is: number and status, when it sells from, who published it, what it was copied from. */
function VersionInfo({ doc }: { doc: VersionDoc }) {
  const { t } = useTexT()
  const items = [
    { label: t("rates.ws.info.version"), value: versionLabel(doc.name, doc.version_no) },
    { label: t("rates.ws.info.status"), value: t(`rates.version_status.${doc.status}`) },
  ]
  if (doc.effective_from) items.push({ label: t("rates.version.sells_from"), value: dateTime(doc.effective_from) })
  if (doc.active_to) items.push({ label: t("rates.version.sells_until"), value: dateTime(doc.active_to) })
  if (doc.published_at) items.push({ label: t("rates.ws.info.published_at"), value: dateTime(doc.published_at) })
  if (doc.published_by) items.push({ label: t("rates.version.published_by"), value: doc.published_by })
  if (doc.based_on) items.push({ label: t("rates.ws.info.based_on"), value: versionLabel(doc.based_on) })
  if (doc.change_note) items.push({ label: t("rates.f.change_note"), value: doc.change_note })
  if (doc.payload_hash) items.push({ label: t("rates.ws.info.payload_hash"), value: doc.payload_hash.slice(0, 12) })
  return (
    <Card>
      <CardHeader title={t("rates.ws.info.title")} />
      <CardBody>
        <DescriptionList cols={3} items={items} />
      </CardBody>
    </Card>
  )
}
