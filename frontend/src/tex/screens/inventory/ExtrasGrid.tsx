import { useCallback, useRef, useState, type KeyboardEvent } from "react"
import { Link } from "react-router-dom"
import { AlertTriangle, ChevronLeft, ChevronRight, Layers, Lock, RefreshCcw, StickyNote } from "lucide-react"
import { cn } from "../../../lib/utils"
import { useTexQuery } from "../../lib/api"
import { useProperty, useSession } from "../../lib/session"
import { addDays, date as fmtDate, isoDay } from "../../lib/format"
import { getTexLang, intlLocale, useTexT } from "../../i18n"
import { Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, Skeleton, Toolbar } from "../../ui"
import { isoWeekday, weekdayName } from "../rates/lib/util"
import { ExtraChangeDialog, ExtraDayDialog, RecountDialog, type ChangeInit } from "./ExtrasDialogs"
import { ExtrasLegend } from "./ExtrasLegend"
import { InventoryNav } from "./InventoryNav"
import type { ExtraGridCell, ExtraGridRow, ExtrasGrid as Grid } from "./types"

const DAYS = 14

type T = (k: string, p?: Record<string, string | number>) => string

/** Limited extras × days (G-19): sold / capacity / left per day, closed days,
 * capacity overrides; bulk change, recount and who-holds-it per day. */
export default function ExtrasGrid() {
  const { t } = useTexT()
  const property = useProperty()
  const { can } = useSession()
  const [start, setStart] = useState(() => isoDay(new Date()))
  const [day, setDay] = useState<{ row: ExtraGridRow; cell: ExtraGridCell } | null>(null)
  const [change, setChange] = useState<ChangeInit | null>(null)
  const [recount, setRecount] = useState(false)
  const canView = can("price.view")
  const canEdit = can("inventory.edit")
  const q = useTexQuery<Grid>("crs", "extras_grid", { property, start, days: DAYS }, [property, start], Boolean(property) && canView)
  const grid = q.data && q.data.property === property ? q.data : undefined
  const today = isoDay(new Date())
  const hasExtras = Boolean(grid && grid.extras.length > 0)

  return (
    <>
      <PageHeader
        title={t("core.nav.inventory")}
        subtitle={t("inventory.extras.subtitle")}
        actions={
          canEdit &&
          grid &&
          hasExtras && (
            <>
              <Button variant="secondary" icon={<RefreshCcw className="size-4" aria-hidden />} onClick={() => setRecount(true)}>
                {t("inventory.extras.recount.action")}
              </Button>
              <Button
                icon={<Layers className="size-4" aria-hidden />}
                onClick={() => setChange({ codes: grid.extras.map((x) => x.code), from: grid.dates[0], to: grid.dates[grid.dates.length - 1] })}
              >
                {t("inventory.extras.change.action")}
              </Button>
            </>
          )
        }
      />
      <InventoryNav />
      {!canView ? (
        <Card>
          <EmptyState icon={<Lock className="size-5" />} title={t("core.error.permission")} description={t("inventory.extras.no_access")} />
        </Card>
      ) : (
        <>
          <Toolbar className="items-end">
            <div className="flex items-end gap-1">
              <Button
                variant="secondary"
                size="md"
                aria-label={t("inventory.prev", { count: DAYS })}
                onClick={() => setStart((s) => addDays(s, -DAYS))}
                icon={<ChevronLeft className="size-4" aria-hidden />}
              />
              <Field label={t("inventory.start")}>
                <Input type="date" value={start} onChange={(e) => e.target.value && setStart(e.target.value)} className="w-40" />
              </Field>
              <Button
                variant="secondary"
                size="md"
                aria-label={t("inventory.next", { count: DAYS })}
                onClick={() => setStart((s) => addDays(s, DAYS))}
                icon={<ChevronRight className="size-4" aria-hidden />}
              />
              <Button variant="ghost" onClick={() => setStart(today)} disabled={start === today}>
                {t("inventory.today")}
              </Button>
            </div>
          </Toolbar>
          <Card className="overflow-hidden">
            {q.error ? (
              <ErrorState error={q.error} onRetry={q.reload} />
            ) : !grid ? (
              <div className="space-y-2 p-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : !hasExtras ? (
              <NoLimitedExtras />
            ) : (
              <ExtrasTable grid={grid} today={today} loading={q.loading} editable={canEdit} onOpen={(row, cell) => setDay({ row, cell })} />
            )}
          </Card>
          {hasExtras && <ExtrasLegend />}
        </>
      )}
      {grid && day && (
        <ExtraDayDialog
          property={grid.property}
          row={day.row}
          cell={day.cell}
          onClose={() => setDay(null)}
          onChange={
            canEdit
              ? () => {
                  setDay(null)
                  setChange({ codes: [day.row.code], from: day.cell.date, to: day.cell.date })
                }
              : undefined
          }
        />
      )}
      {grid && change && <ExtraChangeDialog grid={grid} init={change} onClose={() => setChange(null)} onApplied={q.reload} />}
      {grid && recount && <RecountDialog grid={grid} onClose={() => setRecount(false)} onDone={q.reload} />}
    </>
  )
}

/** Empty state: how an extra becomes limited (Rates → Extras). */
function NoLimitedExtras() {
  const { t } = useTexT()
  const { can } = useSession()
  const where = `${t("core.nav.rates")} → ${t("rates.nav.extras")}`
  return (
    <EmptyState
      title={t("inventory.extras.empty.title")}
      description={t("inventory.extras.empty.body", { field: t("rates.f.inventory_tracked"), cap: t("rates.f.daily_capacity"), where })}
      action={
        (can("price.view") || can("contract.edit")) && (
          <Link
            to="/tex/rates/policies/extras"
            className="inline-flex h-9 items-center rounded-lg border border-zinc-300 bg-white px-3.5 text-sm font-medium text-zinc-800 shadow-sm hover:bg-zinc-50 focus-visible:ring-2 focus-visible:ring-tex-500 focus-visible:outline-none"
          >
            {t("inventory.extras.empty.link", { where })}
          </Link>
        )
      }
    />
  )
}

function ExtrasTable({
  grid,
  today,
  loading,
  editable,
  onOpen,
}: {
  grid: Grid
  today: string
  loading: boolean
  editable: boolean
  onOpen: (row: ExtraGridRow, cell: ExtraGridCell) => void
}) {
  const { t } = useTexT()
  const table = useRef<HTMLTableElement>(null)
  const [pos, setPos] = useState({ r: 0, c: 0 })
  const r = Math.min(pos.r, Math.max(0, grid.extras.length - 1))
  const c = Math.min(pos.c, grid.dates.length - 1)

  const focusCell = useCallback((nr: number, nc: number) => {
    setPos({ r: nr, c: nc })
    requestAnimationFrame(() => table.current?.querySelector<HTMLElement>(`[data-cell="${nr}:${nc}"]`)?.focus())
  }, [])

  const onKey = (e: KeyboardEvent<HTMLTableCellElement>, ri: number, ci: number) => {
    const last = { r: grid.extras.length - 1, c: grid.dates.length - 1 }
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
      case "Enter":
      case " ":
        e.preventDefault()
        onOpen(grid.extras[ri], grid.extras[ri].cells[ci])
        return
      default:
        return
    }
    e.preventDefault()
    focusCell(nr, nc)
  }

  return (
    <div className={cn("max-h-[70vh] overflow-auto", loading && "opacity-60")} aria-busy={loading || undefined}>
      <table
        ref={table}
        role="grid"
        aria-rowcount={grid.extras.length + 1}
        aria-colcount={grid.dates.length + 1}
        aria-readonly={!editable || undefined}
        className="min-w-full border-separate border-spacing-0 text-xs"
      >
        <caption className="sr-only">{t("inventory.extras.caption", { from: fmtDate(grid.dates[0]), to: fmtDate(grid.dates[grid.dates.length - 1]) })}</caption>
        <thead>
          <tr role="row">
            <th
              role="columnheader"
              scope="col"
              className="sticky top-0 left-0 z-[4] w-28 min-w-28 border-r border-b border-zinc-200 bg-zinc-50 px-2 py-2 text-left font-semibold text-zinc-600 sm:w-44 sm:min-w-44"
            >
              {t("inventory.extras.extra_date")}
            </th>
            {grid.dates.map((d) => {
              const wd = isoWeekday(d)
              return (
                <th
                  key={d}
                  role="columnheader"
                  scope="col"
                  className={cn(
                    "sticky top-0 z-[2] min-w-16 border-b border-zinc-200 px-1 py-1.5 text-center font-medium",
                    wd >= 5 ? "bg-zinc-100 text-zinc-800" : "bg-zinc-50 text-zinc-700",
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
          {grid.extras.map((row, ri) => (
            <tr key={row.code} role="row">
              <th role="rowheader" scope="row" className="sticky left-0 z-[1] border-r border-b border-zinc-200 border-b-zinc-300 bg-white px-2 py-1 text-left align-middle font-normal">
                <span className="block max-w-24 truncate text-[13px] font-semibold text-zinc-900 sm:max-w-40" title={row.name}>
                  {row.name}
                </span>
                <span className="block truncate text-[11px] text-zinc-500">
                  <span className="font-mono">{row.code}</span> · {t("inventory.extras.per_day", { n: row.daily_capacity })}
                  <span className="sr-only">, {t("inventory.extras.aria.default_cap", { n: row.daily_capacity })}</span>
                </span>
              </th>
              {row.cells.map((cell, ci) => {
                const active = ri === r && ci === c
                const label = cellLabel(t, row, cell)
                return (
                  <td
                    key={cell.date}
                    role="gridcell"
                    data-cell={`${ri}:${ci}`}
                    tabIndex={active ? 0 : -1}
                    onKeyDown={(e) => onKey(e, ri, ci)}
                    onClick={() => {
                      setPos({ r: ri, c: ci })
                      onOpen(row, cell)
                    }}
                    onFocus={() => (ri !== r || ci !== c) && setPos({ r: ri, c: ci })}
                    aria-label={label}
                    title={label}
                    className={cn(
                      "relative h-11 cursor-pointer border-b border-b-zinc-300 px-1 text-center align-middle tabular-nums outline-none hover:bg-tex-50 focus-visible:z-[3] focus-visible:ring-2 focus-visible:ring-tex-500 focus-visible:ring-inset",
                      isoWeekday(cell.date) >= 5 && "bg-zinc-50/80",
                      cellTone(cell),
                    )}
                  >
                    <CellContent cell={cell} />
                    {cell.override !== null && (
                      <span aria-hidden className="absolute top-0 right-0 size-0 border-t-[6px] border-l-[6px] border-t-tex-600 border-l-transparent" />
                    )}
                    {cell.note && <StickyNote aria-hidden className="absolute top-0.5 left-0.5 size-2.5 text-zinc-500" />}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function fmtMonth(iso: string) {
  return new Intl.DateTimeFormat(intlLocale(getTexLang()), { month: "short" }).format(new Date(`${iso}T12:00:00`))
}

/** Background tone; every state also has an icon or text (never colour alone). */
function cellTone(c: ExtraGridCell): string | false {
  if (c.over) return "bg-rose-100 text-rose-900"
  if (c.closed) return "bg-zinc-200/70 text-zinc-600"
  if (c.remaining === 0) return "bg-rose-50 text-rose-800"
  if (c.capacity > 0 && c.remaining * 5 <= c.capacity) return "bg-amber-50 text-amber-900"
  return false
}

function CellContent({ cell }: { cell: ExtraGridCell }) {
  const { t } = useTexT()
  return (
    <span className="inline-flex flex-col items-center leading-tight">
      <span className="inline-flex items-center gap-0.5">
        {cell.closed && cell.over && <Lock className="size-3" aria-hidden />}
        <span className="text-sm font-semibold">{cell.sold}</span>
        <span className="text-zinc-500">/{cell.capacity}</span>
      </span>
      {cell.over ? (
        <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold">
          <AlertTriangle className="size-3" aria-hidden />
          {t("inventory.extras.short.over")}
        </span>
      ) : cell.closed ? (
        <span className="inline-flex items-center gap-0.5 text-[10px] font-medium">
          <Lock className="size-3" aria-hidden />
          {t("inventory.short.closed")}
        </span>
      ) : (
        <span className={cn("text-[10px]", cell.remaining === 0 ? "font-semibold" : "text-zinc-600")}>{t("inventory.extras.short.left", { n: cell.remaining })}</span>
      )}
    </span>
  )
}

function cellLabel(t: T, row: ExtraGridRow, c: ExtraGridCell): string {
  const day = `${weekdayName(isoWeekday(c.date), "long")} ${fmtDate(c.date)}`
  const parts = [t("inventory.extras.aria.cell", { sold: c.sold, cap: c.capacity, left: c.remaining })]
  if (c.sold > 0) parts.push(t("inventory.extras.aria.held_confirmed", { held: c.held, confirmed: c.confirmed }))
  if (c.closed) parts.push(t("inventory.v.closed_sale"))
  if (c.over) parts.push(t("inventory.extras.legend.over"))
  if (c.override !== null) parts.push(t("inventory.extras.aria.override", { n: row.daily_capacity }))
  if (c.note) parts.push(t("inventory.extras.aria.note", { note: c.note }))
  return `${row.name}, ${day}: ${parts.join(", ")}`
}
