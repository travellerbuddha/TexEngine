import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react"
import { Link } from "react-router-dom"
import { ArrowDownToLine, ArrowUpFromLine, Ban, CalendarClock, ChevronLeft, ChevronRight, Layers, Lock, PencilLine, Tag } from "lucide-react"
import { cn } from "../../../lib/utils"
import { useTexQuery } from "../../lib/api"
import { useProperty, useSession } from "../../lib/session"
import { addDays, date as fmtDate } from "../../lib/format"
import { useSiteToday } from "../../lib/siteDay"
import { getTexLang, intlLocale, useTexT } from "../../i18n"
import { Button, Card, Checkbox, EmptyState, ErrorState, Field, Input, Notice, PageHeader, Segmented, Select, Skeleton, Toolbar } from "../../ui"
import { decText, isoWeekday, useLookups, versionLabel, weekdayName } from "../rates/lib/util"
import { PublishDialog } from "../rates/contracts/VersionActions"
import { BulkDialog, CellDialog, channelScopeLabel, scopeText, windowText } from "./Dialogs"
import { InventoryNav } from "./InventoryNav"
import { Legend } from "./Legend"
import { CHANNEL_SCOPES, channelArgs, HOTEL_METRICS, METRICS, SCOPE_PREFIX, type Grid, type GridCell, type GridRow, type Metric, type Scope } from "./types"

const PREF = "tex-inv-grid"

interface Prefs {
  days: number
  scope: Scope
  metrics: Metric[]
}

function loadPrefs(property: string | undefined): Prefs {
  const fallback: Prefs = { days: 14, scope: { contract: "", market: "", channel: "", rate_plan: "" }, metrics: METRICS }
  try {
    const raw = localStorage.getItem(`${PREF}:${property}`)
    if (!raw) return fallback
    const p = JSON.parse(raw) as Partial<Prefs>
    const metrics = (p.metrics ?? []).filter((m) => METRICS.includes(m))
    return { days: [7, 14, 28].includes(p.days ?? 0) ? p.days! : 14, scope: { ...fallback.scope, ...(p.scope ?? {}) }, metrics: metrics.length ? metrics : METRICS }
  } catch {
    return fallback
  }
}

/** Rates & availability grid (R-36): dates × room types with restrictions,
 * inventory and the contract rate; keyboard navigable; bulk editor. */
export default function AriGrid() {
  const { t } = useTexT()
  const property = useProperty()
  const { boot, can } = useSession()
  const lookups = useLookups(property)
  const [prefs, setPrefs] = useState<Prefs>(() => loadPrefs(property))
  // start null = the site's today (G-91): the grid follows the site's midnight until moved
  const today = useSiteToday()
  const [picked, setStart] = useState<string | null>(null)
  const start = picked ?? today
  const [cellEdit, setCellEdit] = useState<{ row: GridRow; cell: GridCell } | null>(null)
  const [bulk, setBulk] = useState(false)
  const [publishDraft, setPublishDraft] = useState<string | null>(null)
  useEffect(() => setPrefs(loadPrefs(property)), [property])
  useEffect(() => {
    try {
      localStorage.setItem(`${PREF}:${property}`, JSON.stringify(prefs))
    } catch {
      /* storage blocked */
    }
  }, [prefs, property])

  const { days, scope } = prefs
  const setScope = (k: keyof Scope, v: string) => setPrefs((p) => ({ ...p, scope: { ...p.scope, [k]: v } }))
  const ch = channelArgs(scope)
  const q = useTexQuery<Grid>(
    "crs",
    "ari_grid",
    { property, start, days, contract: scope.contract || undefined, market: scope.market || undefined, channel: ch.channel || undefined, channel_scope: ch.channel_scope || undefined, rate_plan: scope.rate_plan || undefined },
    [property, start, days, scope.contract, scope.market, scope.channel, scope.rate_plan],
    Boolean(property),
  )
  const grid = q.data
  const contract = lookups.data?.contracts.find((c) => c.name === scope.contract)
  const ratePlan = lookups.data?.rate_plans.find((r) => r.name === scope.rate_plan)
  const channel = boot.channels.find((c) => c.name === scope.channel)
  const scopeLabel = scopeText(t, scope, contract ? `${contract.contract_code}` : undefined, ratePlan?.rate_plan_name, channel?.channel_name)
  const metrics = prefs.metrics.filter((m) => m !== "rate" || Boolean(grid?.contract))
  const canEditAny = can("restriction.edit") || can("inventory.edit") || (can("contract.edit") && Boolean(scope.contract))

  return (
    <>
      <PageHeader
        title={t("core.nav.inventory")}
        subtitle={t("inventory.subtitle")}
        actions={
          canEditAny &&
          grid && (
            <Button icon={<Layers className="size-4" aria-hidden />} onClick={() => setBulk(true)}>
              {t("inventory.bulk.open")}
            </Button>
          )
        }
      />
      <InventoryNav />
      <Toolbar className="items-end">
        <div className="flex items-end gap-1">
          <Button variant="secondary" size="md" aria-label={t("inventory.prev", { count: days })} onClick={() => setStart(addDays(start, -days))} icon={<ChevronLeft className="size-4" aria-hidden />} />
          <Field label={t("inventory.start")}>
            <Input type="date" value={start} onChange={(e) => e.target.value && setStart(e.target.value)} className="w-40" />
          </Field>
          <Button variant="secondary" size="md" aria-label={t("inventory.next", { count: days })} onClick={() => setStart(addDays(start, days))} icon={<ChevronRight className="size-4" aria-hidden />} />
          <Button variant="ghost" onClick={() => setStart(null)} disabled={start === today}>
            {t("inventory.today")}
          </Button>
        </div>
        <Segmented<string>
          label={t("inventory.days")}
          value={String(days)}
          onChange={(v) => setPrefs((p) => ({ ...p, days: Number(v) }))}
          options={[7, 14, 28].map((d) => ({ value: String(d), label: t("inventory.n_days", { count: d }) }))}
        />
      </Toolbar>
      <Toolbar>
        <Field label={t("rates.f.contract")} className="w-full sm:w-64">
          <Select value={scope.contract} onChange={(e) => setScope("contract", e.target.value)} options={(lookups.data?.contracts ?? []).map((c) => ({ value: c.name, label: `${c.contract_code} · ${c.market}` }))} placeholder={t("inventory.scope.hotel_wide")} />
        </Field>
        <Field label={t("rates.f.market")} className="w-[calc(50%-0.375rem)] sm:w-40">
          <Select value={scope.market} onChange={(e) => setScope("market", e.target.value)} options={boot.markets.map((m) => ({ value: m.name, label: m.name }))} placeholder={t("core.label.all")} />
        </Field>
        <Field label={t("rates.f.channel")} className="w-[calc(50%-0.375rem)] sm:w-44">
          <Select
            value={scope.channel}
            onChange={(e) => setScope("channel", e.target.value)}
            options={[
              ...CHANNEL_SCOPES.map((v) => ({ value: `${SCOPE_PREFIX}${v}`, label: channelScopeLabel(t, v) })),
              ...boot.channels.map((c) => ({ value: c.name, label: c.channel_name })),
            ]}
            placeholder={t("core.label.all")}
          />
        </Field>
        <Field label={t("rates.f.rate_plan")} className="w-full sm:w-48">
          <Select value={scope.rate_plan} onChange={(e) => setScope("rate_plan", e.target.value)} options={(lookups.data?.rate_plans ?? []).map((r) => ({ value: r.name, label: r.rate_plan_name }))} placeholder={t("core.label.all")} />
        </Field>
      </Toolbar>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-zinc-600">
          <span className="font-medium text-zinc-800">{t("inventory.scope.label")}:</span> {scopeLabel}
        </p>
        <fieldset className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <legend className="sr-only">{t("inventory.show_rows")}</legend>
          <span className="text-xs font-medium text-zinc-600" aria-hidden>
            {t("inventory.show_rows")}:
          </span>
          {METRICS.map((m) => (
            <Checkbox
              key={m}
              className="text-xs"
              label={t(`inventory.metric.${m}`)}
              checked={prefs.metrics.includes(m)}
              disabled={m === "rate" && !scope.contract}
              onChange={(e) => setPrefs((p) => ({ ...p, metrics: e.target.checked ? METRICS.filter((x) => x === m || p.metrics.includes(x)) : p.metrics.filter((x) => x !== m) }))}
            />
          ))}
        </fieldset>
      </div>
      {!scope.contract && <p className="mb-3 text-xs text-zinc-500">{t("inventory.choose_contract_hint")}</p>}
      {grid?.draft && (
        <div className="mb-3">
          <Notice tone="warning">
            <span>{t("inventory.draft_notice", { v: versionLabel(grid.draft) })} </span>
            <Link to={`/tex/rates/contracts/${encodeURIComponent(grid.contract ?? "")}/versions/${encodeURIComponent(grid.draft)}`} className="font-medium underline">
              {t("inventory.result.open_draft")}
            </Link>
          </Notice>
        </div>
      )}
      {grid?.contract && !grid.version && !grid.draft && (
        <div className="mb-3">
          <Notice tone="info">{t("inventory.no_version")}</Notice>
        </div>
      )}
      <Card className="overflow-hidden">
        {q.error ? (
          <ErrorState error={q.error} onRetry={q.reload} />
        ) : !grid ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : grid.rows.length === 0 ? (
          <EmptyState title={t("inventory.no_rooms")} />
        ) : (
          <GridTable grid={grid} metrics={metrics} today={today} loading={q.loading} editable={canEditAny} onOpen={(row, cell) => setCellEdit({ row, cell })} />
        )}
      </Card>
      <Legend />
      {grid && cellEdit && (
        <CellDialog
          grid={grid}
          room={cellEdit.row}
          cell={cellEdit.cell}
          scope={scope}
          scopeLabel={scopeLabel}
          onClose={() => setCellEdit(null)}
          onApplied={q.reload}
          onPublish={(d) => {
            setCellEdit(null)
            setPublishDraft(d)
          }}
        />
      )}
      {grid && bulk && (
        <BulkDialog
          grid={grid}
          scope={scope}
          scopeLabel={scopeLabel}
          onClose={() => setBulk(false)}
          onApplied={q.reload}
          onPublish={(d) => {
            setBulk(false)
            setPublishDraft(d)
          }}
        />
      )}
      {publishDraft && (
        <PublishDialog open onClose={() => setPublishDraft(null)} version={{ name: publishDraft, version_no: 0 }} contractCode={contract?.contract_code ?? scope.contract} onDone={q.reload} />
      )}
    </>
  )
}

interface FlatRow {
  row: GridRow
  metric: Metric
}

function GridTable({
  grid,
  metrics,
  today,
  loading,
  editable,
  onOpen,
}: {
  grid: Grid
  metrics: Metric[]
  today: string
  loading: boolean
  editable: boolean
  onOpen: (row: GridRow, cell: GridCell) => void
}) {
  const { t } = useTexT()
  const table = useRef<HTMLTableElement>(null)
  // the hotel-level row holds restrictions only (G-48)
  const rowMetrics = useCallback((row: GridRow) => (row.level === "hotel" ? metrics.filter((m) => HOTEL_METRICS.includes(m)) : metrics), [metrics])
  const flat = useMemo<FlatRow[]>(() => grid.rows.flatMap((row) => rowMetrics(row).map((metric) => ({ row, metric }))), [grid.rows, rowMetrics])
  const [pos, setPos] = useState({ r: 0, c: 0 })
  const r = Math.min(pos.r, Math.max(0, flat.length - 1))
  const c = Math.min(pos.c, grid.dates.length - 1)

  const focusCell = useCallback((nr: number, nc: number) => {
    setPos({ r: nr, c: nc })
    requestAnimationFrame(() => table.current?.querySelector<HTMLElement>(`[data-cell="${nr}:${nc}"]`)?.focus())
  }, [])

  const onKey = (e: KeyboardEvent<HTMLTableCellElement>, ri: number, ci: number) => {
    const last = { r: flat.length - 1, c: grid.dates.length - 1 }
    let nr = ri
    let nc = ci
    switch (e.key) {
      case "ArrowRight":
        nc = Math.min(last.c, ci + 1)
        break
      case "ArrowLeft":
        nc = Math.max(0, ci - 1)
        break
      case "ArrowDown":
        nr = Math.min(last.r, ri + 1)
        break
      case "ArrowUp":
        nr = Math.max(0, ri - 1)
        break
      case "Home":
        nc = 0
        if (e.ctrlKey) nr = 0
        break
      case "End":
        nc = last.c
        if (e.ctrlKey) nr = last.r
        break
      case "PageDown":
        nr = Math.min(last.r, ri + rowMetrics(flat[ri].row).length)
        break
      case "PageUp":
        nr = Math.max(0, ri - rowMetrics(flat[ri].row).length)
        break
      case "Enter":
      case " ":
        e.preventDefault()
        if (editable) onOpen(flat[ri].row, flat[ri].row.cells[ci])
        return
      default:
        return
    }
    e.preventDefault()
    focusCell(nr, nc)
  }

  const ccy = grid.currency ?? ""
  return (
    <div className={cn("max-h-[70vh] overflow-auto", loading && "opacity-60")} aria-busy={loading || undefined}>
      <table ref={table} role="grid" aria-rowcount={flat.length + 1} aria-colcount={grid.dates.length + 1} aria-readonly={!editable || undefined} className="min-w-full border-separate border-spacing-0 text-xs">
        <caption className="sr-only">{t("inventory.caption", { from: fmtDate(grid.dates[0]), to: fmtDate(grid.dates[grid.dates.length - 1]) })}</caption>
        <thead>
          <tr role="row">
            <th role="columnheader" scope="col" className="sticky top-0 left-0 z-[4] w-28 min-w-28 border-r border-b border-zinc-200 bg-zinc-50 px-2 py-2 text-left font-semibold text-zinc-600 sm:w-44 sm:min-w-44">
              {t("inventory.room_date")}
            </th>
            {grid.dates.map((d) => {
              const wd = isoWeekday(d)
              const weekend = wd >= 5
              return (
                <th
                  key={d}
                  role="columnheader"
                  scope="col"
                  className={cn(
                    "sticky top-0 z-[2] min-w-16 border-b border-zinc-200 px-1 py-1.5 text-center font-medium",
                    weekend ? "bg-zinc-100 text-zinc-800" : "bg-zinc-50 text-zinc-700",
                    d === today && "shadow-[inset_0_-2px_0_var(--color-tex-600)]",
                  )}
                >
                  <span className="block text-[10px] tracking-wide text-zinc-500 uppercase">{weekdayName(wd)}</span>
                  <span className="block text-sm font-semibold tabular-nums">{d.slice(8, 10)}</span>
                  <span className="block text-[10px] text-zinc-500">{fmtMonth(d)}</span>
                  {d === today && <span className="sr-only">{t("inventory.today")}</span>}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {grid.rows.map((row) => {
            const shown = rowMetrics(row)
            return shown.map((metric, mi) => {
              const ri = flat.findIndex((f) => f.row === row && f.metric === metric)
              return (
                <tr key={`${row.room_type ?? "*"}-${metric}`} role="row" data-level={row.level}>
                  <th
                    role="rowheader"
                    scope="row"
                    className={cn(
                      "sticky left-0 z-[1] border-r border-zinc-200 px-2 py-1 text-left align-middle font-normal",
                      row.level === "hotel" ? "bg-zinc-50" : "bg-white",
                      mi === shown.length - 1 ? "border-b border-b-zinc-300" : "border-b border-b-zinc-100",
                    )}
                  >
                    {mi === 0 && <span className="block max-w-24 truncate text-[13px] font-semibold text-zinc-900 sm:max-w-40" title={row.name}>{row.name}</span>}
                    {mi === 0 && row.level === "hotel" && <span className="block text-[10px] text-zinc-500">{t("inventory.hotel_row_hint")}</span>}
                    <span className="block text-[11px] text-zinc-500">
                      {t(`inventory.metric.${metric}`)}
                      {metric === "rate" && ccy && <span className="text-zinc-400"> · {ccy}</span>}
                      <span className="sr-only"> · {row.name}</span>
                    </span>
                  </th>
                  {row.cells.map((cell, ci) => {
                    const weekend = isoWeekday(cell.date) >= 5
                    const active = ri === r && ci === c
                    return (
                      <td
                        key={cell.date}
                        role="gridcell"
                        data-cell={`${ri}:${ci}`}
                        tabIndex={active ? 0 : -1}
                        onKeyDown={(e) => onKey(e, ri, ci)}
                        onClick={() => {
                          setPos({ r: ri, c: ci })
                          if (editable) onOpen(row, cell)
                        }}
                        onFocus={() => (ri !== r || ci !== c) && setPos({ r: ri, c: ci })}
                        aria-label={cellLabel(t, metric, cell, row.name, ccy)}
                        className={cn(
                          "relative h-9 cursor-default px-1 text-center align-middle tabular-nums outline-none focus-visible:z-[3] focus-visible:ring-2 focus-visible:ring-tex-500 focus-visible:ring-inset",
                          mi === shown.length - 1 ? "border-b border-b-zinc-300" : "border-b border-b-zinc-100",
                          weekend && "bg-zinc-50/80",
                          editable && "cursor-pointer hover:bg-tex-50",
                          cellTone(metric, cell),
                        )}
                      >
                        <CellContent metric={metric} cell={cell} />
                        {isOwn(metric, cell) && <span aria-hidden className="absolute top-0 right-0 size-0 border-t-[6px] border-l-[6px] border-t-tex-600 border-l-transparent" />}
                      </td>
                    )
                  })}
                </tr>
              )
            })
          })}
        </tbody>
      </table>
    </div>
  )
}

function fmtMonth(iso: string) {
  return new Intl.DateTimeFormat(intlLocale(getTexLang()), { month: "short" }).format(new Date(`${iso}T12:00:00`))
}

function isOwn(metric: Metric, c: GridCell): boolean {
  const o = c.own
  if (!o) return false
  switch (metric) {
    case "stop":
      return Boolean(o.stop_sell)
    case "los":
      return Boolean(o.min_los || o.max_los)
    case "arrdep":
      return o.cta !== null || o.ctd !== null
    case "release":
      return Boolean(o.release_days)
    case "window":
      return Boolean(o.book_from || o.book_to || o.min_advance || o.max_advance)
    default:
      return false
  }
}

function cellTone(metric: Metric, c: GridCell): string | false {
  if (metric === "avail") {
    if (c.closed) return "bg-zinc-200/70 text-zinc-600"
    if (c.available === 0) return "bg-rose-50 text-rose-800"
    if (c.capacity && c.available !== null && c.available * 5 <= c.capacity) return "bg-amber-50 text-amber-900"
  }
  if (metric === "window" && (c.book_from || c.book_to)) return "bg-sky-50 text-sky-900"
  if (metric === "stop" && c.stop_sell) return "bg-rose-50 text-rose-800"
  if (metric === "arrdep" && (c.cta || c.ctd)) return "bg-amber-50 text-amber-900"
  return false
}

function CellContent({ metric, cell }: { metric: Metric; cell: GridCell }) {
  const { t } = useTexT()
  switch (metric) {
    case "rate": {
      const draft = cell.draft_rate && cell.draft_rate !== cell.rate
      return (
        <span className="inline-flex flex-col items-center leading-tight">
          <span className={cn("font-medium", draft && "text-zinc-400 line-through")}>{cell.rate ? decText(cell.rate) : "—"}</span>
          {draft && (
            <span className="inline-flex items-center gap-0.5 font-semibold text-amber-800">
              <PencilLine className="size-3" aria-hidden />
              {decText(cell.draft_rate)}
            </span>
          )}
          {cell.promo && !draft && <Tag className="size-3 text-emerald-700" aria-hidden />}
        </span>
      )
    }
    case "avail":
      if (cell.closed)
        return (
          <span className="inline-flex items-center gap-0.5 font-medium">
            <Lock className="size-3" aria-hidden />
            {t("inventory.short.closed")}
          </span>
        )
      return (
        <span>
          <span className="text-sm font-semibold">{cell.available}</span>
          <span className="text-zinc-400">/{cell.capacity}</span>
          {cell.manual_adjustment !== 0 && <span className="block text-[10px] text-zinc-500">{cell.manual_adjustment > 0 ? `+${cell.manual_adjustment}` : cell.manual_adjustment}</span>}
        </span>
      )
    case "stop":
      return cell.stop_sell ? (
        <span className="inline-flex items-center gap-0.5 font-semibold">
          <Ban className="size-3" aria-hidden />
          {t("inventory.short.stop")}
        </span>
      ) : cell.own?.stop_sell === "OPEN" ? (
        <span className="text-emerald-800">{t("inventory.short.open")}</span>
      ) : (
        <span className="text-zinc-300">·</span>
      )
    case "los":
      return cell.min_los || cell.max_los ? (
        <span className="font-medium">
          {cell.min_los ?? "–"}
          <span className="text-zinc-400">/</span>
          {cell.max_los ?? "–"}
        </span>
      ) : (
        <span className="text-zinc-300">·</span>
      )
    case "arrdep":
      return cell.cta || cell.ctd ? (
        <span className="inline-flex flex-col items-center gap-0 text-[10px] leading-tight font-semibold">
          {cell.cta && (
            <span className="inline-flex items-center gap-0.5">
              <ArrowDownToLine className="size-3" aria-hidden />
              CTA
            </span>
          )}
          {cell.ctd && (
            <span className="inline-flex items-center gap-0.5">
              <ArrowUpFromLine className="size-3" aria-hidden />
              CTD
            </span>
          )}
        </span>
      ) : (
        <span className="text-zinc-300">·</span>
      )
    case "release":
      return cell.release_days ? <span className="font-medium">{cell.release_days}</span> : <span className="text-zinc-300">·</span>
    case "window":
      return cell.book_from || cell.book_to || cell.min_advance || cell.max_advance ? (
        <span className="inline-flex flex-col items-center text-[10px] leading-tight font-semibold">
          {(cell.book_from || cell.book_to) && (
            <span className="inline-flex items-center gap-0.5">
              <CalendarClock className="size-3" aria-hidden />
              {shortDay(cell.book_from)}–{shortDay(cell.book_to)}
            </span>
          )}
          {(cell.min_advance || cell.max_advance) && (
            <span>
              {cell.min_advance ?? 0}–{cell.max_advance ?? "∞"}
              {t("inventory.short.days")}
            </span>
          )}
        </span>
      ) : (
        <span className="text-zinc-300">·</span>
      )
  }
}

function shortDay(iso: string | null) {
  if (!iso) return "…"
  return new Intl.DateTimeFormat(intlLocale(getTexLang()), { day: "numeric", month: "short" }).format(new Date(`${iso}T12:00:00`))
}

function cellLabel(t: (k: string, p?: Record<string, string | number>) => string, metric: Metric, c: GridCell, room: string, ccy: string): string {
  const day = `${weekdayName(isoWeekday(c.date), "long")} ${fmtDate(c.date)}`
  let v: string
  switch (metric) {
    case "rate":
      v = c.rate ? `${decText(c.rate)} ${ccy}` : t("inventory.aria.no_rate")
      if (c.draft_rate && c.draft_rate !== c.rate) v += `, ${t("inventory.legend.draft")} ${decText(c.draft_rate)}`
      if (c.promo) v += `, ${t("inventory.legend.promo")}`
      break
    case "avail":
      v = c.closed ? t("inventory.v.closed_sale") : t("inventory.aria.avail", { a: c.available ?? 0, cap: c.capacity ?? 0, sold: c.sold ?? 0 })
      break
    case "stop":
      v = c.stop_sell ? t("inventory.v.stop") : t("inventory.v.open")
      break
    case "los":
      v = t("inventory.aria.los", { min: c.min_los ?? "–", max: c.max_los ?? "–" })
      break
    case "arrdep":
      v = [c.cta ? t("inventory.f.cta") : "", c.ctd ? t("inventory.f.ctd") : ""].filter(Boolean).join(", ") || t("inventory.v.no_rule")
      break
    case "release":
      v = c.release_days ? t("inventory.v.days", { count: c.release_days }) : t("inventory.v.no_rule")
      break
    case "window":
      v = windowText(t, c)
      break
  }
  const own = isOwn(metric, c) ? `, ${t("inventory.legend.own")}` : ""
  return `${room}, ${t(`inventory.metric.${metric}`)}, ${day}: ${v}${own}`
}
