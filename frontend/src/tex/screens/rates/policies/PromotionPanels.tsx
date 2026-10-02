// The promotion editor's two working panels (UX revision 2026-10):
// - the summary: what the promotion gives, how, when it is booked and stayed, and where it applies,
//   in one block of plain sentences, with a warning when it applies to every market, channel and
//   room (an empty list means "all"; never left to be discovered after activation);
// - the price check: one stay priced by the engine without and with this promotion, a draft too
//   (policies.promotion_check), with the engine's own reason when it does not apply.
// Amounts are the server's decimal strings, shown as they are; nothing is computed here.
import { useMemo, useState } from "react"
import { BadgeCheck, Calculator, CircleX, TriangleAlert } from "lucide-react"
import { tex, TexApiError, useTexQuery } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { date as fmtDate } from "../../../lib/format"
import { useSiteToday } from "../../../lib/siteDay"
import { useTexT } from "../../../i18n"
import { Button, Card, CardBody, CardHeader, Field, FormGrid, InlineError, Input, Money, Notice, Select } from "../../../ui"
import { BOARDS, enumLabel } from "../lib/options"
import type { Lookups } from "../lib/types"
import { decText, roomLabel } from "../lib/util"
import { addDays } from "../../../lib/format"
import { coversEverything, csv, type Doc } from "./promotions"

type T = (k: string, p?: Record<string, string | number>) => string
const s = (v: unknown) => (v === null || v === undefined ? "" : String(v).trim())

function range(t: T, from: unknown, to: unknown): string {
  const a = s(from)
  const b = s(to)
  if (!a && !b) return t("rates.promo.sum.any_date")
  if (a && b) return `${fmtDate(a)} – ${fmtDate(b)}`
  return a ? t("rates.promo.sum.from", { d: fmtDate(a) }) : t("rates.promo.sum.until", { d: fmtDate(b) })
}

/** What the promotion gives, in words. */
export function promoValueText(t: T, d: Doc): string {
  const vt = s(d.value_type) || "PERCENT"
  if (["PERCENT", "FIXED_STAY", "FIXED_NIGHT", "MULTIPLIER"].includes(vt) && !s(d.value)) return t("rates.promo.sum.no_value")
  const v = decText(s(d.value) || null, 0)
  const ccy = s(d.currency)
  switch (vt) {
    case "PERCENT":
      return t("rates.promo.sum.value.PERCENT", { v })
    case "FIXED_STAY":
    case "FIXED_NIGHT":
      return t(`rates.promo.sum.value.${vt}`, { v: decText(s(d.value) || null), ccy: ccy || t("rates.common.sell_currency") })
    case "MULTIPLIER":
      return t("rates.promo.sum.value.MULTIPLIER", { v: decText(s(d.value) || null) })
    case "FREE_NIGHTS":
      return t("rates.promo.sum.value.FREE_NIGHTS", { stay: s(d.free_nights_stay) || "?", pay: s(d.free_nights_pay) || "?" })
    default:
      return t("rates.promo.sum.value.VALUE_ADDED", { text: s(d.value_added) || "—" })
  }
}

export function PromotionSummary({ doc, lookups }: { doc: Doc; lookups: Lookups | undefined }) {
  const { t } = useTexT()
  const { boot } = useSession()
  const list = (values: string[], all: string, name: (v: string) => string) => (values.length ? values.map(name).join(", ") : all)
  const market = (m: string) => boot.markets.find((x) => x.name === m)?.market_name ?? m
  const channel = (c: string) => boot.channels.find((x) => x.name === c)?.channel_name ?? c
  const lead = [Number(doc.min_lead_days || 0) > 0 ? t("rates.promo.sum.min_lead", { n: Number(doc.min_lead_days) }) : "", Number(doc.max_lead_days || 0) > 0 ? t("rates.promo.sum.max_lead", { n: Number(doc.max_lead_days) }) : ""].filter(Boolean)
  const nights = [Number(doc.min_nights || 0) > 0 ? t("rates.promo.sum.min_nights", { n: Number(doc.min_nights) }) : "", Number(doc.max_nights || 0) > 0 ? t("rates.promo.sum.max_nights", { n: Number(doc.max_nights) }) : ""].filter(Boolean)
  const combine = doc.exclusive ? t("rates.promo.sum.exclusive") : doc.stackable ? t("rates.promo.sum.stackable", { p: Number(doc.priority || 0) }) : t("rates.promo.sum.not_stackable")
  const everything = coversEverything(doc)
  const undated = !s(doc.sale_from) && !s(doc.sale_to) && !s(doc.stay_from) && !s(doc.stay_to)
  const rows: [string, string][] = [
    [t("rates.promo.sum.gives"), `${promoValueText(t, doc)} · ${doc.trigger === "Code" ? t("rates.promo.sum.code", { code: s(doc.code) || "—" }) : t("rates.promo.sum.automatic")}`],
    [t("rates.promo.sum.booked"), [range(t, doc.sale_from, doc.sale_to), ...lead].join(" · ")],
    [t("rates.promo.sum.stayed"), [range(t, doc.stay_from, doc.stay_to), ...nights].join(" · ")],
    [t("rates.f.markets"), list(csv(doc.markets), t("rates.common.all_markets"), market)],
    [t("rates.f.channels"), list(csv(doc.channels), t("rates.common.all_channels"), channel)],
    [t("rates.f.room_types"), list(csv(doc.room_types), t("rates.common.all_rooms"), (r) => roomLabel(lookups?.room_types, r))],
    [t("rates.promo.sum.combines"), combine],
  ]
  return (
    <Card className="mb-5">
      <CardHeader title={t("rates.promo.sum.title")} description={t("rates.promo.sum.help")} />
      <CardBody className="space-y-3">
        <dl className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-[auto_1fr]">
          {rows.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="font-medium text-zinc-600">{k}</dt>
              <dd className="text-zinc-900">{v}</dd>
            </div>
          ))}
        </dl>
        {everything && (
          <Notice tone="warning">
            <span className="flex items-start gap-2">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
              {t("rates.promo.sum.everything")}
            </span>
          </Notice>
        )}
        {undated && <Notice tone="info">{t("rates.promo.sum.undated")}</Notice>}
      </CardBody>
    </Card>
  )
}

interface CheckAnswer {
  sellable: boolean
  reasons?: { code: string; message: string }[]
  currency?: string
  without?: { total: string; discounts: string; accommodation: string }
  with?: { total: string; discounts: string; accommodation: string }
  outcome?: { applied: boolean; reason: string; discount: string } | null
  applied_others?: { name: string; promo_id: string }[]
}

interface VersionLite {
  boards?: { board: string }[]
  rate_plans?: { rate_plan: string }[]
}

/** One stay priced by the engine without and with this promotion (it need not be active). */
export function PromotionCheck({ doc, name, dirty, lookups }: { doc: Doc; name: string | null; dirty: boolean; lookups: Lookups | undefined }) {
  const { t } = useTexT()
  const { boot, can } = useSession()
  const today = useSiteToday()
  const markets = csv(doc.markets)
  const rooms = csv(doc.room_types)
  const contracts = useMemo(() => {
    const all = (lookups?.contracts ?? []).filter((c) => c.active_version)
    const fit = all.filter((c) => (!markets.length || markets.includes(c.market)) && (!csv(doc.contracts).length || csv(doc.contracts).includes(c.name)))
    return fit.length ? fit : all
  }, [lookups, markets, doc.contracts])
  const [contract, setContract] = useState("")
  const c = contracts.find((x) => x.name === contract) ?? contracts[0]
  const version = useTexQuery<VersionLite>("contracts", "get_version", { name: c?.active_version }, [c?.active_version], Boolean(c?.active_version))
  const boards = version.data?.boards?.map((b) => b.board).filter(Boolean) ?? []
  const plans = version.data?.rate_plans?.map((r) => r.rate_plan).filter(Boolean) ?? []
  const roomOptions = (lookups?.room_types ?? []).filter((r) => !rooms.length || rooms.includes(r.name))
  const stayFrom = s(doc.stay_from) && s(doc.stay_from) > today ? s(doc.stay_from) : addDays(today, 30)
  const [f, setF] = useState({ room: "", board: "", plan: "", checkIn: "", nights: "3", adults: "2", children: "", market: "", channel: "", saleAt: "" })
  const set = (k: keyof typeof f, v: string) => setF((x) => ({ ...x, [k]: v }))
  const room = f.room || roomOptions[0]?.name || ""
  const board = f.board || csv(doc.boards).find((b) => boards.includes(b)) || boards[0] || ""
  const plan = f.plan || csv(doc.rate_plans).find((p) => plans.includes(p)) || plans[0] || ""
  const checkIn = f.checkIn || stayFrom
  const market = f.market || markets[0] || c?.market || ""
  const channel = f.channel || csv(doc.channels)[0] || "DIRECT_WEB"
  const saleAt = f.saleAt || (s(doc.sale_from) > today ? s(doc.sale_from) : "")
  const [res, setRes] = useState<CheckAnswer>()
  const [err, setErr] = useState<TexApiError>()
  const [busy, setBusy] = useState(false)
  const nights = Math.max(1, Math.min(30, parseInt(f.nights || "3", 10) || 3))
  const kids = f.children
    .split(/[,; ]+/)
    .map((x) => x.trim())
    .filter(Boolean)
  const kidsOk = kids.every((k) => /^\d{1,2}$/.test(k) && Number(k) < 18)
  if (!can("price.view_cost")) return null
  const run = async () => {
    if (!name || !c) return
    setBusy(true)
    setErr(undefined)
    try {
      setRes(
        await tex<CheckAnswer>(
          "policies",
          "promotion_check",
          {
            name,
            contract: c.name,
            room_type: room,
            board,
            rate_plan: plan || null,
            check_in: checkIn,
            check_out: addDays(checkIn, nights),
            adults: Number(f.adults) || 2,
            children: kids.map(Number),
            market,
            channel,
            sale_at: saleAt ? `${saleAt} 12:00:00` : null,
          },
          { post: true },
        ),
      )
    } catch (e) {
      setErr(e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error"))
    } finally {
      setBusy(false)
    }
  }
  const ccy = res?.currency ?? c?.contract_currency ?? ""
  return (
    <Card className="mb-5">
      <CardHeader title={t("rates.promo.check.title")} description={t("rates.promo.check.help")} />
      <CardBody className="space-y-4">
        {!name && <Notice tone="info">{t("rates.promo.check.save_first")}</Notice>}
        {name && dirty && <Notice tone="warning">{t("rates.promo.check.unsaved")}</Notice>}
        {!contracts.length && <Notice tone="info">{t("rates.promo.check.no_contract")}</Notice>}
        <FormGrid cols={4}>
          <Field label={t("rates.col.contract")}>
            <Select value={c?.name ?? ""} onChange={(e) => setContract(e.target.value)} options={contracts.map((x) => ({ value: x.name, label: `${x.contract_code} · ${x.market}` }))} />
          </Field>
          <Field label={t("rates.f.room_type")}>
            <Select value={room} onChange={(e) => set("room", e.target.value)} options={roomOptions.map((r) => ({ value: r.name, label: r.room_type_name }))} />
          </Field>
          <Field label={t("rates.f.board")}>
            <Select value={board} onChange={(e) => set("board", e.target.value)} options={(boards.length ? boards : [...BOARDS]).map((b) => ({ value: b, label: enumLabel(t, "board", b) }))} />
          </Field>
          {plans.length > 0 && (
            <Field label={t("rates.f.rate_plan")}>
              <Select value={plan} onChange={(e) => set("plan", e.target.value)} options={plans.map((p) => ({ value: p, label: lookups?.rate_plans.find((r) => r.name === p)?.rate_plan_name ?? p }))} />
            </Field>
          )}
          <Field label={t("rates.promo.check.check_in")}>
            <Input type="date" value={checkIn} onChange={(e) => set("checkIn", e.target.value)} />
          </Field>
          <Field label={t("rates.promo.check.nights")}>
            <Input type="number" min={1} max={30} value={f.nights} onChange={(e) => set("nights", e.target.value)} />
          </Field>
          <Field label={t("rates.promo.check.adults")}>
            <Input type="number" min={1} max={12} value={f.adults} onChange={(e) => set("adults", e.target.value)} />
          </Field>
          <Field label={t("rates.promo.check.children")} hint={t("rates.promo.check.children_hint")} error={kidsOk ? undefined : t("rates.promo.check.children_bad")}>
            <Input value={f.children} onChange={(e) => set("children", e.target.value)} placeholder="5, 9" />
          </Field>
          <Field label={t("rates.f.market")}>
            <Select value={market} onChange={(e) => set("market", e.target.value)} options={boot.markets.map((m) => ({ value: m.name, label: m.name }))} />
          </Field>
          <Field label={t("rates.f.channel")}>
            <Select value={channel} onChange={(e) => set("channel", e.target.value)} options={boot.channels.map((x) => ({ value: x.name, label: x.channel_name }))} />
          </Field>
          <Field label={t("rates.promo.check.sale_at")} hint={t("rates.promo.check.sale_at_hint")}>
            <Input type="date" value={saleAt} onChange={(e) => set("saleAt", e.target.value)} />
          </Field>
        </FormGrid>
        <div className="flex flex-wrap items-center gap-3">
          <Button icon={<Calculator className="size-4" aria-hidden />} loading={busy} disabled={!name || !c || !room || !board || !kidsOk} onClick={() => void run()}>
            {t("rates.promo.check.run")}
          </Button>
          <span className="text-xs text-zinc-500">{t("rates.promo.check.read_only")}</span>
        </div>
        <InlineError error={err} />
        {res && (
          <div role="status" className="rounded-lg border border-zinc-200 bg-zinc-50 p-3 text-sm">
            {!res.sellable ? (
              <p className="text-zinc-800">{t("rates.promo.check.unsellable", { why: (res.reasons ?? []).map((r) => r.message).join("; ") || "—" })}</p>
            ) : (
              <>
                <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1">
                  <dt className="text-zinc-600">{t("rates.promo.check.without")}</dt>
                  <dd className="font-medium tabular-nums">
                    <Money amount={res.without?.total ?? ""} currency={ccy} />
                  </dd>
                  <dt className="text-zinc-600">{t("rates.promo.check.with")}</dt>
                  <dd className="font-semibold tabular-nums">
                    <Money amount={res.with?.total ?? ""} currency={ccy} />
                  </dd>
                  <dt className="text-zinc-600">{t("rates.promo.check.discount")}</dt>
                  <dd className="tabular-nums">
                    {res.outcome?.applied ? <Money amount={res.outcome.discount} currency={ccy} /> : "—"}
                  </dd>
                </dl>
                <p className="mt-2 flex items-start gap-2">
                  {res.outcome?.applied ? (
                    <>
                      <BadgeCheck className="mt-0.5 size-4 shrink-0 text-emerald-700" aria-hidden />
                      <span>{t("rates.promo.check.applied")}</span>
                    </>
                  ) : (
                    <>
                      <CircleX className="mt-0.5 size-4 shrink-0 text-rose-700" aria-hidden />
                      <span>{t("rates.promo.check.not_applied", { why: res.outcome?.reason || "—" })}</span>
                    </>
                  )}
                </p>
                {res.applied_others && res.applied_others.length > 0 && (
                  <p className="mt-1 text-xs text-zinc-600">{t("rates.promo.check.others", { names: res.applied_others.map((p) => p.name).join(", ") })}</p>
                )}
              </>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  )
}
