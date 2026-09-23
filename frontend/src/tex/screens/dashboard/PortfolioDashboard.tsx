import { useMemo, useState, type ReactNode } from "react"
import { useSearchParams } from "react-router-dom"
import { cn } from "../../../lib/utils"
import { useTexQuery } from "../../lib/api"
import { useSession } from "../../lib/session"
import { date } from "../../lib/format"
import { useSiteToday } from "../../lib/siteDay"
import { useTexT } from "../../i18n"
import { Card, EmptyState, ErrorState, Field, InlineError, PageHeader, Select, Spinner, Toolbar } from "../../ui"
import { RangeFilter } from "../reports/components/RangeFilter"
import { presetRange, type RangePreset } from "../reports/lib"
import { PortfolioAlerts } from "./PortfolioAlerts"
import { PortfolioKpis } from "./PortfolioKpis"
import { PortfolioHotels, PortfolioMarkets, PortfolioRooms } from "./PortfolioTables"
import {
  currenciesOf,
  decodeScope,
  encodeScope,
  mainCurrency,
  MAX_PORTFOLIO_DAYS,
  saleRangeProblem,
  SALE_PRESETS,
  scopeOffered,
  type PortfolioData,
  type PortfolioScopes,
  type Scope,
} from "./portfolio"

type SalePreset = (typeof SALE_PRESETS)[number]
const isPreset = (v: string | null): v is SalePreset => (SALE_PRESETS as readonly string[]).includes(v ?? "")

/**
 * Sales picture of every hotel the user may report on (R-47, ADR-038): all of them,
 * an enterprise, a hotel group or one hotel. Scope and sale window live in the URL,
 * so going back from a hotel returns to the same view.
 */
export default function PortfolioDashboard({ viewSwitch }: { viewSwitch?: ReactNode }) {
  const { t } = useTexT()
  const { boot, can } = useSession()
  const [params, setParams] = useSearchParams()

  const update = (patch: Record<string, string | null>) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set("view", "portfolio")
        for (const [k, v] of Object.entries(patch)) {
          if (v === null) next.delete(k)
          else next.set(k, v)
        }
        return next
      },
      { replace: true },
    )

  // --- scope
  const scopesQ = useTexQuery<PortfolioScopes>("reports", "portfolio_scopes", {}, [])
  const scopes = scopesQ.data
  const requested = decodeScope(params.get("scope"))
  const scope: Scope = scopeOffered(requested, scopes) ? requested : { level: "All" }
  const reportHotels = boot.properties.filter((p) => can("report.view", p.name)).length

  // --- sale window (sale dates, not stay dates)
  const rawPeriod = params.get("period")
  const preset: RangePreset = rawPeriod === "custom" ? "custom" : isPreset(rawPeriod) ? rawPeriod : "this_month"
  const today = useSiteToday()
  const [from, to] = useMemo<[string, string]>(() => {
    if (preset !== "custom") return presetRange(preset, today)
    // a cleared date stays empty (and is reported), it does not snap back
    const [a, b] = presetRange("this_month", today)
    return [params.get("from") ?? a, params.get("to") ?? b]
  }, [preset, params, today])
  const problem = saleRangeProblem(from, to)

  const q = useTexQuery<PortfolioData>(
    "reports",
    "portfolio",
    { level: scope.level, name: scope.name, date_from: from, date_to: to },
    [scope.level, scope.name, from, to],
    !problem,
  )
  const d = problem ? undefined : q.data

  // --- currencies: never added up; one of them orders the money columns
  const currencies = useMemo(() => (d ? currenciesOf(d) : []), [d])
  const [picked, setPicked] = useState<string>()
  const homeCurrency = d?.hotels.map((h) => boot.properties.find((p) => p.name === h.hotel)?.currency).find(Boolean)
  const currency =
    (picked && currencies.includes(picked) ? picked : undefined) ?? (d ? mainCurrency(d, currencies) : undefined) ?? homeCurrency

  const scopeOptions = [
    { value: "All", label: t("dash.pf.scope.all", { count: scopes?.hotels.length ?? reportHotels }) },
    // until the list arrives, keep the scope from the URL selectable
    ...(!scopes && requested.level !== "All" ? [{ value: encodeScope(requested), label: requested.name ?? "" }] : []),
  ]
  const scopeGroups = scopes
    ? [
        {
          label: t("dash.pf.scope.enterprises"),
          options: scopes.enterprises.map((e) => ({ value: encodeScope({ level: "Enterprise", name: e.name }), label: e.label })),
        },
        {
          label: t("dash.pf.scope.groups"),
          options: scopes.groups.map((g) => ({ value: encodeScope({ level: "Group", name: g.name }), label: g.label })),
        },
        {
          label: t("dash.pf.scope.hotels"),
          options: scopes.hotels.map((h) => ({ value: encodeScope({ level: "Hotel", name: h.name }), label: h.label })),
        },
      ]
    : undefined

  const refreshing = q.loading && !!d

  return (
    <>
      <PageHeader
        title={t("core.nav.dashboard")}
        subtitle={d ? t("dash.pf.subtitle", { count: d.scope.hotels, from: date(d.from), to: date(d.to) }) : undefined}
        meta={viewSwitch}
      />

      <Toolbar>
        <Field label={t("dash.pf.scope")} className="w-full sm:w-72">
          <Select
            value={encodeScope(scope)}
            onChange={(e) => update({ scope: e.target.value === "All" ? null : e.target.value })}
            options={scopeOptions}
            groups={scopeGroups}
          />
        </Field>
        <RangeFilter
          presets={[...SALE_PRESETS]}
          preset={preset}
          from={from}
          to={to}
          labels={{ period: t("dash.pf.sale_period") }}
          error={problem ? t(problem, { max: MAX_PORTFOLIO_DAYS }) : null}
          onChange={(next) =>
            update(
              next.preset === "custom"
                ? { period: "custom", from: next.from, to: next.to }
                : { period: next.preset === "this_month" ? null : next.preset, from: null, to: null },
            )
          }
        />
        {currencies.length > 1 && (
          <Field label={t("dash.pf.sort_currency")} className="w-full sm:w-40">
            <Select value={currency} onChange={(e) => setPicked(e.target.value)} options={currencies.map((c) => ({ value: c, label: c }))} />
          </Field>
        )}
        {refreshing && (
          <span className="inline-flex h-9 items-center gap-2 text-sm text-zinc-500">
            <Spinner label={t("core.label.loading")} />
            <span aria-hidden>{t("core.label.loading")}</span>
          </span>
        )}
      </Toolbar>
      {scopesQ.error && !scopesQ.error.isPermission && (
        <div className="mb-4">
          <InlineError error={scopesQ.error} />
        </div>
      )}

      {problem ? (
        <Card>
          <EmptyState title={t("dash.pf.fix_period")} />
        </Card>
      ) : q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : (
        <div aria-busy={q.loading} className={cn("space-y-5 transition-opacity", refreshing && "opacity-60")}>
          {currencies.length > 1 && <p className="text-xs text-zinc-500">{t("dash.pf.per_currency")}</p>}
          <PortfolioKpis data={d} currency={currency} />
          <PortfolioHotels data={d} currency={currency} />
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
            <PortfolioMarkets data={d} currency={currency} />
            <PortfolioRooms data={d} currency={currency} />
          </div>
          <PortfolioAlerts data={d} />
          {d && <p className="text-xs text-zinc-500">{t("dash.pf.footnote", { date: date(d.today) })}</p>}
        </div>
      )}
    </>
  )
}
