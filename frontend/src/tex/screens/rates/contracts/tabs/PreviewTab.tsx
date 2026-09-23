import { useMemo, useState } from "react"
import { Calculator, CheckCircle2, Minus, Plus, XCircle } from "lucide-react"
import { cn } from "../../../../../lib/utils"
import { tex, TexApiError, useTexQuery } from "../../../../lib/api"
import { useSession } from "../../../../lib/session"
import { addDays, date as fmtDate, isoDay, money, nightsBetween, weekday } from "../../../../lib/format"
import { useTexT } from "../../../../i18n"
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  DataTable,
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
} from "../../../../ui"
import { BOARDS, enumLabel, enumOptions } from "../../lib/options"
import type { ExplainStep, NightLine, PreviewResult, PriceMatrix } from "../../lib/types"
import { decText, splitCsv, toFrappeDatetime, versionLabel } from "../../lib/util"
import { contractRoomOptions, TabIntro, type TabProps } from "./shared"

const LEVELS = ["GLOBAL", "HOTEL", "MARKET", "CONTRACT", "VERSION", "ROOM", "PERIOD", "COMBINATION", "OVERRIDE"]

/** "Why this price": server-side price preview on this version (preview_price) and
 * the nightly unit matrix (price_matrix). Nothing is priced in the browser. */
export function PreviewTab(props: TabProps) {
  const { t } = useTexT()
  const { can } = useSession()
  return (
    <div className="space-y-5">
      <TabIntro title={t("rates.tab.preview")}>{t("rates.preview.intro")}</TabIntro>
      {props.dirty && <Notice tone="warning">{t("rates.preview.unsaved")}</Notice>}
      {can("price.view_cost") ? <Calculator_ {...props} /> : <Notice tone="info">{t("rates.preview.needs_cost")}</Notice>}
      <MatrixCard version={props.doc.name} modified={props.doc.modified} />
    </div>
  )
}

function defaultDates(stayFrom?: string | null): [string, string] {
  const today = isoDay(new Date())
  let a = addDays(today, 14)
  if (stayFrom && stayFrom > a) a = stayFrom
  return [a, addDays(a, 3)]
}

function Calculator_({ doc, state }: TabProps) {
  const { t } = useTexT()
  const { boot, can } = useSession()
  const rooms = contractRoomOptions(doc, state)
  const boardCodes = Array.from(new Set(state.tables.boards.map((b) => String(b.board)).filter(Boolean)))
  const baseBoard = String(state.tables.boards.find((b) => b.is_base)?.board ?? boardCodes[0] ?? "BB")
  const plans = state.tables.rate_plans.map((r) => String(r.rate_plan)).filter(Boolean)
  const [ci0, co0] = defaultDates(null)
  const [f, setF] = useState({
    room_type: rooms[0]?.value ?? "",
    board: baseBoard,
    rate_plan: plans[0] ?? "",
    check_in: ci0,
    check_out: co0,
    adults: 2,
    children: [] as string[],
    market: doc.contract_doc.market,
    channel: boot.settings.default_sales_channel || "DIRECT_WEB",
    currency: doc.contract_doc.contract_currency,
    sale_at: "",
    promo: "",
  })
  const [res, setRes] = useState<PreviewResult>()
  const [err, setErr] = useState<TexApiError>()
  const [busy, setBusy] = useState(false)
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }))
  const nights = f.check_in && f.check_out ? nightsBetween(f.check_in, f.check_out) : 0
  const childOk = f.children.every((a) => /^\d{1,2}$/.test(a) && parseInt(a, 10) <= 17)
  const valid = Boolean(f.room_type && f.board && nights > 0 && nights <= 90 && childOk && (plans.length === 0 || f.rate_plan))

  const run = async () => {
    if (!valid) return
    setBusy(true)
    setErr(undefined)
    try {
      const r = await tex<PreviewResult>(
        "contracts",
        "preview_price",
        {
          version: doc.name,
          room_type: f.room_type,
          board: f.board,
          rate_plan: f.rate_plan || null,
          check_in: f.check_in,
          check_out: f.check_out,
          adults: f.adults,
          children: f.children.map((a) => parseInt(a, 10)),
          market: f.market || null,
          channel: f.channel,
          currency: f.currency || null,
          sale_at: toFrappeDatetime(f.sale_at),
          promo_codes: splitCsv(f.promo).map((c) => c.toUpperCase()),
        },
        { post: true },
      )
      setRes(r)
    } catch (e) {
      setErr(e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Card>
        <CardHeader title={t("rates.preview.calculator")} description={t("rates.preview.calculator_hint")} />
        <CardBody>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              void run()
            }}
          >
            <FormGrid cols={4}>
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
              <p className="text-xs text-zinc-500">{t("rates.h.children_ages")}</p>
              <div className="flex flex-wrap items-center gap-2">
                {f.children.map((a, i) => (
                  <span key={i} className="inline-flex items-center gap-1">
                    <Input
                      aria-label={t("rates.preview.child_age", { n: i + 1 })}
                      inputMode="numeric"
                      value={a}
                      onChange={(e) => set("children", f.children.map((x, j) => (j === i ? e.target.value.replace(/\D/g, "").slice(0, 2) : x)))}
                      className="w-16! text-right"
                      aria-invalid={!/^\d{1,2}$/.test(a) || parseInt(a, 10) > 17 ? true : undefined}
                    />
                    <IconButton size="sm" label={t("rates.preview.remove_child", { n: i + 1 })} icon={<Minus className="size-4" />} onClick={() => set("children", f.children.filter((_, j) => j !== i))} />
                  </span>
                ))}
                {f.children.length < 6 && (
                  <Button variant="secondary" size="sm" icon={<Plus className="size-4" aria-hidden />} onClick={() => set("children", [...f.children, "5"])}>
                    {t("rates.preview.add_child")}
                  </Button>
                )}
              </div>
            </fieldset>
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" loading={busy} disabled={!valid} icon={<Calculator className="size-4" aria-hidden />} shortcut="↵">
                {t("rates.preview.run")}
              </Button>
              <span className="text-xs text-zinc-500">{t("rates.preview.on_version", { v: versionLabel(doc.name, doc.version_no), status: t(`rates.version_status.${doc.status}`) })}</span>
            </div>
            <InlineError error={err} />
          </form>
        </CardBody>
      </Card>
      {res && <PreviewResultView res={res} canCost={can("price.view_cost")} />}
    </>
  )
}

function PreviewResultView({ res, canCost }: { res: PreviewResult; canCost: boolean }) {
  const { t } = useTexT()
  const ccy = res.currency ?? ""
  const contractCcy = res.contract?.currency ?? ccy
  const nights = res.nights ?? []
  const [night, setNight] = useState<string>(nights[0]?.date ?? "")
  const steps = useMemo(() => (res.explanation ?? []).filter((s) => !s.night || !night || s.night === night), [res.explanation, night])

  if (!res.sellable)
    return (
      <Notice tone="danger" title={t("rates.preview.unsellable")}>
        <ul className="mt-1 list-disc pl-5">
          {res.reasons.map((r, i) => (
            <li key={i}>
              <span className="font-mono text-xs opacity-70">{r.code}</span> {r.message}
            </li>
          ))}
        </ul>
      </Notice>
    )

  const tot = res.totals ?? {}
  return (
    <div className="space-y-5" aria-live="polite">
      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
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
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
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
              <StepItem key={i} s={s} />
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

function StepItem({ s }: { s: ExplainStep }) {
  const { t } = useTexT()
  const stage = t(`rates.stage.${s.stage}`)
  return (
    <li className={cn("flex flex-wrap items-start gap-2 rounded-md px-2 py-1.5 text-sm", s.stage === "total" ? "bg-tex-50" : "hover:bg-zinc-50")}>
      <Badge tone={STAGE_TONE[s.stage] ?? "neutral"} className="min-w-20 justify-center">
        {stage.startsWith("rates.stage.") ? s.stage : stage}
      </Badge>
      <div className="min-w-0 flex-1">
        <p className="text-zinc-900">{s.text}</p>
        {(s.rule || s.overridden.length > 0) && (
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-zinc-500">
            {s.rule && (
              <>
                <span>{t("rates.preview.won")}</span>
                {s.rule.level && <Badge tone="neutral">{t(`rates.level.${s.rule.level}`)}</Badge>}
                <span className="font-medium text-zinc-700">{s.rule.label || s.rule.rule_id}</span>
                {s.rule.source && <span className="font-mono">({s.rule.source})</span>}
              </>
            )}
            {s.overridden.length > 0 && (
              <span>
                · {t("rates.preview.overrode")} {s.overridden.map((o) => o.label || o.rule_id).join(", ")}
              </span>
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

function MatrixCard({ version, modified }: { version: string; modified?: string }) {
  const { t } = useTexT()
  const q = useTexQuery<PriceMatrix>("contracts", "price_matrix", { version }, [version, modified])
  const m = q.data
  return (
    <Card>
      <CardHeader title={t("rates.preview.matrix")} description={m ? t(`rates.rates.unit.${m.basis}`, { ccy: m.currency }) : t("rates.preview.matrix_hint")} />
      {q.error ? (
        <ErrorState error={q.error} onRetry={q.reload} />
      ) : !m ? (
        <CardBody>
          <Skeleton className="h-24 w-full" />
        </CardBody>
      ) : m.rooms.length === 0 ? (
        <EmptyState title={t("rates.rates.need_rooms_periods")} />
      ) : (
        <div className="max-h-[60vh] overflow-auto">
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
