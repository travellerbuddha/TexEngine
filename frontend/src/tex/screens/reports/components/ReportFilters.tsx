import { Info } from "lucide-react"
import { useTexQuery } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { useTexT } from "../../../i18n"
import { Card, CardBody, Checkbox, Field, Segmented, Select } from "../../../ui"
import { encodeScope, scopeOffered, type PortfolioScopes } from "../../dashboard/portfolio"
import { MAX_RANGE_DAYS, viewDimensions, type ReportView } from "../lib"
import { PRESETS, scopeArgs, type Basis, type ReportFilters as Filters, type Range } from "../filters"
import { RangeFilter } from "./RangeFilter"

interface Options {
  scope: { level: string; name: string | null; hotels: string[] }
  room_types: { name: string; label: string; hotel: string }[]
  rate_plans: { name: string; label: string; hotel: string }[]
  /** A list was cut at `limit` entries. */
  truncated?: { room_types?: boolean; rate_plans?: boolean }
  limit?: number
}

const rangePatch = (suffix: string, r: Range) => ({
  [`period${suffix}`]: r.preset === "this_month" ? null : r.preset,
  [`from${suffix}`]: r.preset === "custom" ? r.from : null,
  [`to${suffix}`]: r.preset === "custom" ? r.to : null,
})

/**
 * A typed date changes that date only. The other one is the live URL's: a change re-renders as a
 * router transition, which waits for the new report, so this render's other date may be stale
 * (typing "from" then "to" while the report loads lost "from").
 */
const typedRange = (suffix: string, shown: Range, n: Range): Range => {
  if (n.preset !== "custom") return n
  const live = new URLSearchParams(window.location.search)
  const custom = live.get(`period${suffix}`) === "custom"
  const other = (k: "from" | "to") => (n[k] !== shown[k] || !custom ? n[k] : (live.get(`${k}${suffix}`) ?? n[k]))
  return { preset: "custom", from: other("from"), to: other("to") }
}

/**
 * The filters of every report view: scope (a hotel, a group, an enterprise or all the
 * viewer's hotels), the stay and / or sale window, market, channel, room, rate, currency,
 * grouping and cancelled stays. A view shows only the filters it can apply (the server
 * refuses the others).
 */
export function ReportFilters({
  view,
  filters: f,
  update,
  problem,
  note,
}: {
  view: ReportView
  filters: Filters
  update: (patch: Record<string, string | null>) => void
  problem: string | null
  note?: string
}) {
  const { t } = useTexT()
  const { boot } = useSession()
  const stayed = view !== "conversion"
  const dims = viewDimensions(view)

  const scopesQ = useTexQuery<PortfolioScopes>("reports", "portfolio_scopes", {}, [])
  const scopes = scopesQ.data
  const optionsQ = useTexQuery<Options>("reports", "filter_options", scopeArgs(f.scope), [f.scope.level, f.scope.name], stayed)
  const opts = optionsQ.data
  const multi = (opts?.scope.hotels.length ?? 1) > 1
  const hotelName = (h: string) => scopes?.hotels.find((x) => x.name === h)?.label ?? h

  const scopeValue = encodeScope(f.scope)
  const scopeOptions = [
    { value: "All", label: t("dash.pf.scope.all", { count: scopes?.hotels.length ?? boot.properties.length }) },
    ...(!scopes || !scopeOffered(f.scope, scopes) ? (f.scope.level !== "All" ? [{ value: scopeValue, label: f.scope.name ?? "" }] : []) : []),
  ]
  const scopeGroups = scopes
    ? [
        { label: t("dash.pf.scope.enterprises"), options: scopes.enterprises.map((e) => ({ value: `Enterprise:${e.name}`, label: e.label })) },
        { label: t("dash.pf.scope.groups"), options: scopes.groups.map((g) => ({ value: `Group:${g.name}`, label: g.label })) },
        { label: t("dash.pf.scope.hotels"), options: scopes.hotels.map((h) => ({ value: `Hotel:${h.name}`, label: h.label })) },
      ]
    : undefined

  const staySide = t("reports.filter.stay_period")
  const saleSide = t("reports.filter.sale_period")
  const primaryLabel = f.basis === "stay" ? staySide : saleSide
  const secondaryLabel = f.basis === "stay" ? saleSide : staySide
  const all = (key: string) => ({ value: "", label: t(key) })
  const withHotel = (label: string, hotel: string) => (multi ? `${label} · ${hotelName(hotel)}` : label)

  return (
    <Card className="mb-4">
      <CardBody className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <Field label={t("reports.filter.scope")} className="w-full sm:w-64">
            <Select
              value={scopeValue}
              // a room type or rate plan belongs to a hotel: another scope clears them (a hidden
              // filter would empty the report)
              onChange={(e) => update({ scope: e.target.value, room: null, rate: null })}
              options={scopeOptions}
              groups={scopeGroups}
            />
          </Field>
          {stayed && (
            <div className="w-full space-y-1.5 sm:w-auto">
              <span className="block text-sm font-medium text-zinc-800" aria-hidden>
                {t("reports.filter.basis")}
              </span>
              <Segmented<Basis>
                label={t("reports.filter.basis")}
                value={f.basis}
                onChange={(v) => update({ basis: v === "stay" ? null : v })}
                options={[
                  { value: "stay", label: t("reports.basis.stay") },
                  { value: "booking", label: t("reports.basis.booking") },
                ]}
              />
            </div>
          )}
        </div>

        <fieldset className="flex flex-wrap items-end gap-3">
          <legend className="sr-only">{primaryLabel}</legend>
          <RangeFilter
            presets={[...PRESETS]}
            preset={f.primary.preset}
            from={f.primary.from}
            to={f.primary.to}
            error={problem ? t(problem, { max: MAX_RANGE_DAYS }) : null}
            labels={{ period: primaryLabel, from: t("core.label.from"), to: t("core.label.to") }}
            onChange={(n) => update(rangePatch("", typedRange("", f.primary, n)))}
          />
        </fieldset>

        {stayed && (
          <div className="space-y-3">
            <Checkbox
              label={f.basis === "stay" ? t("reports.filter.also_sale") : t("reports.filter.also_stay")}
              checked={!!f.secondary}
              onChange={(e) => update({ also: e.target.checked ? "1" : null, period2: null, from2: null, to2: null })}
            />
            {f.secondary && (
              <fieldset className="flex flex-wrap items-end gap-3">
                <legend className="sr-only">{secondaryLabel}</legend>
                <RangeFilter
                  presets={[...PRESETS]}
                  preset={f.secondary.preset}
                  from={f.secondary.from}
                  to={f.secondary.to}
                  labels={{ period: secondaryLabel, from: t("core.label.from"), to: t("core.label.to") }}
                  onChange={(n) => f.secondary && update(rangePatch("2", typedRange("2", f.secondary, n)))}
                />
              </fieldset>
            )}
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label={t("reports.filter.market")}>
            <Select
              value={f.market}
              onChange={(e) => update({ market: e.target.value })}
              options={[all("reports.all_markets"), ...boot.markets.map((m) => ({ value: m.name, label: m.market_name }))]}
            />
          </Field>
          {stayed && (
            <Field label={t("reports.filter.channel")}>
              <Select
                value={f.channel}
                onChange={(e) => update({ channel: e.target.value })}
                options={[all("reports.all_channels"), ...boot.channels.map((c) => ({ value: c.name, label: c.channel_name }))]}
              />
            </Field>
          )}
          {stayed && (
            <Field label={t("reports.filter.room")}>
              <Select
                value={f.room}
                onChange={(e) => update({ room: e.target.value })}
                options={[all("reports.all_rooms"), ...(opts?.room_types ?? []).map((r) => ({ value: r.name, label: withHotel(r.label, r.hotel) }))]}
              />
            </Field>
          )}
          {stayed && (
            <Field label={t("reports.filter.rate")}>
              <Select
                value={f.rate}
                onChange={(e) => update({ rate: e.target.value })}
                options={[all("reports.all_rates"), ...(opts?.rate_plans ?? []).map((r) => ({ value: r.name, label: withHotel(r.label, r.hotel) }))]}
              />
            </Field>
          )}
          {stayed && (
            <Field label={t("reports.filter.currency")}>
              <Select
                value={f.currency}
                onChange={(e) => update({ ccy: e.target.value })}
                options={[all("reports.all_currencies"), ...boot.currencies.map((c) => ({ value: c, label: c }))]}
              />
            </Field>
          )}
          {dims.length > 0 && f.group && (
            <Field label={t("reports.filter.group_by")}>
              <Select
                value={f.group}
                onChange={(e) => update({ group: e.target.value })}
                options={dims.map((d) => ({ value: d, label: t(`reports.dim.${d}`) }))}
              />
            </Field>
          )}
        </div>

        {stayed && (opts?.truncated?.room_types || opts?.truncated?.rate_plans) && (
          <p className="text-xs text-zinc-500">{t("reports.filter.options_cut", { count: opts?.limit ?? 0 })}</p>
        )}

        {(view === "production" || view === "margin" || view === "promotion" || view === "extras") && (
          <Checkbox label={t("reports.filter.include_cancelled")} checked={f.cancelled} onChange={(e) => update({ cancelled: e.target.checked ? "1" : null })} />
        )}

        <div className="flex items-start gap-2 rounded-lg bg-zinc-50 px-3 py-2 text-xs text-zinc-600">
          <Info className="mt-0.5 size-3.5 shrink-0 text-zinc-500" aria-hidden />
          <div className="space-y-1">
            {stayed && <p>{f.basis === "stay" ? t("reports.basis.stay_help") : t("reports.basis.booking_help")}</p>}
            {note && <p>{note}</p>}
          </div>
        </div>
      </CardBody>
    </Card>
  )
}
