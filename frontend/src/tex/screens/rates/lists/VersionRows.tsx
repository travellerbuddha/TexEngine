import { useMemo, useState, type ReactNode } from "react"
import { useNavigate } from "react-router-dom"
import { CalendarDays, Search, SlidersHorizontal, Users } from "lucide-react"
import { useTexQuery } from "../../../lib/api"
import { useHotelScope } from "../../../lib/hotelScope"
import { useTexT } from "../../../i18n"
import { Badge, Card, DataTable, EmptyState, ErrorState, Field, Input, Notice, PageHeader, Segmented, Toolbar, type Column } from "../../../ui"
import { DateRange } from "../components/common"
import { RatesNav } from "../components/RatesNav"
import { enumLabel, opText } from "../lib/options"
import { splitCsv, versionLabel, WEEKDAY_CODES, weekdayName } from "../lib/util"
import { ContractViews, VersionStateBadge } from "./ContractViews"
import type { ListOf, OccupancyRow, PeriodRow, RatePlanRow } from "./types"

export type Section = "periods" | "occupancy" | "rate_plans"

const PRICE = ["price.view"] as const
const COST = ["price.view_cost", "contract.edit"] as const

// where each list opens its version (the editor's canonical hashes, PRICING_WORKSPACE_UX.md §2):
// periods are columns of Pricing, occupancy its region there, rate plans a Commercial rules table
const TAB: Record<Section, string> = { periods: "pricing", occupancy: "occupancy", rate_plans: "plans" }
const TITLE: Record<Section, string> = { periods: "core.nav.sub.periods", occupancy: "core.nav.sub.occupancy", rate_plans: "core.nav.sub.rate_plans" }
const ICON: Record<Section, ReactNode> = {
  periods: <CalendarDays className="size-5" />,
  occupancy: <Users className="size-5" />,
  rate_plans: <SlidersHorizontal className="size-5" />,
}

type AnyRow = PeriodRow | OccupancyRow | RatePlanRow

const WEEKDAY_KEYS = WEEKDAY_CODES.map((c) => c.toLowerCase())

/** "Fri,Sat" (any case, as contracts.parse_weekdays reads it) → localised day names. */
function weekdaysText(raw: string | null | undefined, allDays: string): string {
  const codes = splitCsv((raw ?? "").replace(/;/g, ","))
  if (!codes.length || codes.length === 7) return allDays
  return codes
    .map((c) => {
      const i = WEEKDAY_KEYS.indexOf(c.slice(0, 3).toLowerCase())
      return i >= 0 ? weekdayName(i) : c
    })
    .join(", ")
}

/** One table of contract versions across contracts (R-35 Price Periods, Occupancy Rules, Rate
 * Plans; G-64): drafts and published versions by default, each row opens its version. */
export default function VersionRows({ section }: { section: Section }) {
  const { t } = useTexT()
  const navigate = useNavigate()
  const cost = section !== "rate_plans"
  const hotels = useHotelScope(PRICE, cost ? COST : undefined)
  const [which, setWhich] = useState<"current" | "all">("current")
  const [q, setQ] = useState("")
  const list = useTexQuery<ListOf<AnyRow>>("lists", "version_rows", { section, property: hotels.property, status: which }, [section, hotels.property, which])

  const rows = useMemo(() => {
    const term = q.trim().toLowerCase()
    const all = list.data?.rows
    if (!term || !all) return all
    return all.filter((r) => Object.values(r).some((v) => typeof v === "string" && v.toLowerCase().includes(term)))
  }, [list.data, q])

  const common: Column<AnyRow>[] = [
    {
      key: "contract",
      header: t("rates.col.contract"),
      sortValue: (r) => `${r.contract_code} ${String(r.version_no).padStart(4, "0")} ${String(r.idx).padStart(4, "0")}`,
      cell: (r) => (
        <div className="min-w-0">
          <p className="font-medium whitespace-nowrap text-zinc-900">
            {r.contract_code} · {versionLabel(r.version, r.version_no)}
          </p>
          <div className="mt-0.5 flex flex-wrap items-center gap-1">
            <VersionStateBadge state={r.state} />
            {hotels.all && <span className="text-xs text-zinc-500">{hotels.hotelName(r.property)}</span>}
          </div>
        </div>
      ),
    },
  ]
  const columns: Column<AnyRow>[] = [...common, ...sectionColumns(section, t, (list.data?.rows ?? []).some((r) => "op" in r))]

  return (
    <>
      <RatesNav />
      <PageHeader
        title={t(TITLE[section])}
        subtitle={t(`rates.lists.${section}.subtitle`)}
        crumbs={[{ label: t("core.nav.rates"), to: "/tex/rates" }, { label: t(TITLE[section]) }]}
      />
      <ContractViews />
      <Toolbar>
        <Field label={t("core.action.search")} className="w-full sm:w-64">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-zinc-400" aria-hidden />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("rates.lists.search_ph")} className="pl-8" type="search" />
          </div>
        </Field>
        <div className="self-end">
          <Segmented
            label={t("rates.lists.which")}
            value={which}
            onChange={setWhich}
            options={[
              { value: "current", label: t("rates.lists.which_current") },
              { value: "all", label: t("rates.lists.which_all") },
            ]}
          />
        </div>
        {hotels.control && <div className="self-end">{hotels.control}</div>}
      </Toolbar>
      <p className="mb-3 text-xs text-zinc-600">{t(which === "current" ? "rates.lists.which_current_hint" : "rates.lists.which_all_hint")}</p>
      {list.data?.truncated && (
        <div className="mb-3">
          <Notice tone="info">{t("rates.lists.truncated")}</Notice>
        </div>
      )}
      <Card>
        {list.error ? (
          <ErrorState error={list.error} onRetry={list.reload} />
        ) : (
          <DataTable<AnyRow>
            caption={t(TITLE[section])}
            rows={rows}
            loading={list.loading}
            rowKey={(r) => `${r.version}-${r.idx}`}
            onRowClick={(r) => navigate(`/tex/rates/contracts/${encodeURIComponent(r.contract)}/versions/${encodeURIComponent(r.version)}#${TAB[section]}`)}
            initialSort={{ key: "contract", dir: "asc" }}
            empty={<EmptyState icon={ICON[section]} title={q ? t("rates.lists.none_filtered") : t(`rates.lists.${section}.none`)} />}
            columns={columns}
          />
        )}
      </Card>
    </>
  )
}

type T = (key: string, params?: Record<string, string | number>) => string

function sectionColumns(section: Section, t: T, showAdjustment: boolean): Column<AnyRow>[] {
  if (section === "periods")
    return [
      {
        key: "period",
        header: t("rates.f.period"),
        sortValue: (r) => (r as PeriodRow).period_code,
        cell: (r) => {
          const p = r as PeriodRow
          return (
            <span>
              <span className="font-mono text-xs font-medium text-zinc-900">{p.period_code}</span>
              {p.period_name && <span className="block text-xs text-zinc-500">{p.period_name}</span>}
            </span>
          )
        },
      },
      {
        key: "dates",
        header: t("rates.lists.col.dates"),
        sortValue: (r) => (r as PeriodRow).start_date ?? "",
        cell: (r) => <DateRange from={(r as PeriodRow).start_date} to={(r as PeriodRow).end_date} />,
      },
      {
        key: "weekdays",
        header: t("rates.f.weekdays"),
        hideBelow: "md",
        cell: (r) => <span className="text-zinc-700">{weekdaysText((r as PeriodRow).weekdays, t("rates.lists.all_days"))}</span>,
      },
      {
        key: "adjustment",
        header: t("rates.f.adjustment_op"),
        hideBelow: "sm",
        cell: (r) => {
          const p = r as PeriodRow
          return p.adjustment_op ? <span className="tabular-nums">{opText(p.adjustment_op, p.adjustment_value)}</span> : <span className="text-zinc-500">{t("rates.common.no_adjustment")}</span>
        },
      },
      { key: "priority", header: t("rates.f.priority"), hideBelow: "lg", align: "right", sortValue: (r) => (r as PeriodRow).priority ?? 0, cell: (r) => (r as PeriodRow).priority ?? 0 },
    ]
  if (section === "occupancy")
    return [
      {
        key: "target",
        header: t("rates.f.target"),
        sortValue: (r) => (r as OccupancyRow).target,
        cell: (r) => {
          const o = r as OccupancyRow
          return (
            <span className="whitespace-nowrap">
              {enumLabel(t, "target", o.target)}
              {o.position ? <span className="text-zinc-500"> · {t("rates.lists.position", { n: o.position })}</span> : null}
            </span>
          )
        },
      },
      {
        key: "band",
        header: t("rates.f.age_band"),
        hideBelow: "sm",
        cell: (r) => {
          const o = r as OccupancyRow
          return (
            <span className="font-mono text-xs">
              {o.age_band || "—"}
              {o.combination && <span className="ml-1 text-zinc-500">({o.combination})</span>}
            </span>
          )
        },
      },
      {
        key: "rule",
        header: t("rates.lists.col.rule"),
        cell: (r) => {
          const o = r as OccupancyRow
          return (
            <span className="whitespace-nowrap tabular-nums">
              {opText(o.op, o.value)}
              {o.is_override ? (
                <Badge tone="info" className="ml-1.5">
                  {t("rates.f.is_override")}
                </Badge>
              ) : null}
            </span>
          )
        },
      },
      { key: "room", header: t("rates.f.room_type"), hideBelow: "md", cell: (r) => (r as OccupancyRow).room_type_name || <span className="text-zinc-500">{t("rates.common.all_rooms")}</span> },
      { key: "period", header: t("rates.f.period"), hideBelow: "lg", cell: (r) => (r as OccupancyRow).period_code || <span className="text-zinc-500">{t("rates.common.all_periods")}</span> },
      { key: "note", header: t("rates.f.note"), hideBelow: "lg", cell: (r) => <span className="line-clamp-2 max-w-56 text-zinc-600">{(r as OccupancyRow).note || "—"}</span> },
    ]
  return [
    {
      key: "plan",
      header: t("rates.f.rate_plan"),
      sortValue: (r) => (r as RatePlanRow).rate_plan_name,
      cell: (r) => {
        const p = r as RatePlanRow
        return (
          <span>
            <span className="font-medium text-zinc-900">{p.rate_plan_name}</span>
            {p.rate_plan_code && <span className="ml-1.5 font-mono text-xs text-zinc-500">{p.rate_plan_code}</span>}
          </span>
        )
      },
    },
    {
      key: "refundable",
      header: t("rates.f.refundable"),
      sortValue: (r) => (r as RatePlanRow).refundable,
      cell: (r) => ((r as RatePlanRow).refundable ? <Badge tone="success">{t("core.label.yes")}</Badge> : <Badge tone="warning">{t("core.label.no")}</Badge>),
    },
    ...(showAdjustment
      ? [
          {
            key: "adjustment",
            header: t("rates.f.adjustment"),
            hideBelow: "sm" as const,
            cell: (r: AnyRow) => {
              const p = r as RatePlanRow
              return p.op ? <span className="tabular-nums">{opText(p.op, p.value)}</span> : <span className="text-zinc-500">{t("rates.common.no_adjustment")}</span>
            },
          },
        ]
      : []),
    { key: "boards", header: t("rates.f.boards"), hideBelow: "md", cell: (r) => splitCsv((r as RatePlanRow).boards).join(", ") || <span className="text-zinc-500">{t("rates.common.all_boards")}</span> },
    { key: "cxl", header: t("rates.f.cancellation_policy"), hideBelow: "lg", cell: (r) => (r as RatePlanRow).cancellation_policy_name || <span className="text-zinc-500">{t("rates.common.plan_default")}</span> },
    { key: "pay", header: t("rates.f.payment_policy"), hideBelow: "lg", cell: (r) => (r as RatePlanRow).payment_policy_name || <span className="text-zinc-500">{t("rates.common.plan_default")}</span> },
  ]
}

