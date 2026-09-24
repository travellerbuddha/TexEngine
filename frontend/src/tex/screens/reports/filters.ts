// Report filters (R-48, ADR-059): one URL-backed state shared by every report view, so a
// view switch keeps the scope, dates and filters, and a report can be bookmarked or shared.
// The server re-checks everything: the hotels a scope may cover, the dates, the values.
import { useMemo } from "react"
import { useSearchParams } from "react-router-dom"
import { useSession } from "../../lib/session"
import { useSiteToday } from "../../lib/siteDay"
import { decodeScope, encodeScope, type Scope } from "../dashboard/portfolio"
import { DEFAULT_GROUP, presetRange, rangeProblem, viewDimensions, type AnyDimension, type RangePreset, type ReportView } from "./lib"

export type Basis = "stay" | "booking"

export const PRESETS = ["this_month", "last_month", "next_month", "next_30", "next_90", "last_30", "ytd", "this_year", "last_year"] as const
const ALL_PRESETS: string[] = [...PRESETS, "custom"]

/** The URL parameters every report view shares. */
const KEYS = ["scope", "basis", "period", "from", "to", "also", "period2", "from2", "to2", "market", "channel", "room", "rate", "ccy", "group", "cancelled"] as const

export interface Range {
  preset: RangePreset
  from: string
  to: string
}

export interface ReportFilters {
  scope: Scope
  basis: Basis
  /** The window of the basis: stay dates (stay basis) or sale dates (booking basis). */
  primary: Range
  /** The other window, when switched on: sale dates on the stay basis, stay dates on the booking basis. */
  secondary: Range | null
  market: string
  channel: string
  room: string
  rate: string
  currency: string
  group: AnyDimension | null
  cancelled: boolean
}

function range(params: URLSearchParams, today: string, suffix = ""): Range {
  const raw = params.get(`period${suffix}`)
  const preset = (raw && ALL_PRESETS.includes(raw) ? raw : "this_month") as RangePreset
  const [a, b] = presetRange(preset === "custom" ? "this_month" : preset, today)
  if (preset !== "custom") return { preset, from: a, to: b }
  // a cleared date stays empty (and is reported), it does not snap back
  return { preset, from: params.get(`from${suffix}`) ?? a, to: params.get(`to${suffix}`) ?? b }
}

/** The report filters of the URL for `view`, and a setter that keeps the other parameters. */
export function useReportFilters(view: ReportView) {
  const { property } = useSession()
  const [params, setParams] = useSearchParams()
  const today = useSiteToday()

  const filters = useMemo<ReportFilters>(() => {
    const scopeRaw = params.get("scope")
    const scope: Scope = scopeRaw ? decodeScope(scopeRaw) : property ? { level: "Hotel", name: property.name } : { level: "All" }
    // conversion counts shopping sessions on the days they happened: sale dates only
    const basis: Basis = view === "conversion" || params.get("basis") === "booking" ? "booking" : "stay"
    const dims = viewDimensions(view)
    const g = params.get("group") as AnyDimension | null
    return {
      scope,
      basis,
      primary: range(params, today),
      secondary: view !== "conversion" && params.get("also") === "1" ? range(params, today, "2") : null,
      market: params.get("market") ?? "",
      channel: params.get("channel") ?? "",
      room: params.get("room") ?? "",
      rate: params.get("rate") ?? "",
      currency: params.get("ccy") ?? "",
      group: dims.length ? (g && dims.includes(g) ? g : DEFAULT_GROUP[view]) : null,
      cancelled: params.get("cancelled") === "1",
    }
  }, [params, property, today, view])

  const update = (patch: Record<string, string | null>) => {
    // from the live URL, not this render's copy: a second change made before the page has
    // re-rendered (router updates are transitions) must not undo the first
    const next = new URLSearchParams(window.location.search)
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === "") next.delete(k)
      else next.set(k, v)
    }
    setParams(next, { replace: true })
  }

  return { filters, update, search: shared(params) }
}

/** The report parameters of the URL (for links between the views). */
export function shared(params: URLSearchParams): string {
  const q = new URLSearchParams()
  for (const k of KEYS) {
    const v = params.get(k)
    if (v !== null && k !== "group") q.set(k, v)
  }
  const s = q.toString()
  return s ? `?${s}` : ""
}

/** i18n key of the problem with the dates, or null. */
export function filtersProblem(f: ReportFilters): string | null {
  return rangeProblem(f.primary.from, f.primary.to) ?? (f.secondary ? rangeProblem(f.secondary.from, f.secondary.to) : null)
}

/** The scope as the API takes it: one hotel, or a level and its name. */
export function scopeArgs(s: Scope): Record<string, string | undefined> {
  if (s.level === "Hotel") return { property: s.name }
  return { level: s.level, name: s.name }
}

/** kamra.tex.api.reports.report arguments for a view. */
export function reportArgs(view: ReportView, f: ReportFilters): Record<string, string | number | undefined> {
  const stay = f.basis === "stay" ? f.primary : f.secondary
  const sale = f.basis === "booking" ? f.primary : f.secondary
  const stayed = view !== "conversion"
  return {
    view,
    ...scopeArgs(f.scope),
    basis: f.basis,
    group_by: f.group ?? undefined,
    stay_from: stay?.from,
    stay_to: stay?.to,
    sale_from: sale?.from,
    sale_to: sale?.to,
    market: f.market || undefined,
    channel: stayed ? f.channel || undefined : undefined,
    room_type: stayed ? f.room || undefined : undefined,
    rate_plan: stayed ? f.rate || undefined : undefined,
    currency: stayed ? f.currency || undefined : undefined,
    include_cancelled: view === "production" || view === "margin" || view === "promotion" || view === "extras" ? (f.cancelled ? 1 : 0) : undefined,
  }
}

/** The dependency list of a report query (every argument). */
export function argsKey(args: Record<string, unknown>): string {
  return JSON.stringify(args)
}

export { encodeScope }
