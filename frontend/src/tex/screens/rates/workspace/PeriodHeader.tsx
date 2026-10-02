// Period columns of the price matrix (PRICING_WORKSPACE_UX.md §3.9; slice S9): the column header
// (code, name, compact dates, weekday and night-adjustment badges, the period menu), the
// "+ Period" column, and the thin PeriodStrip of the periods against the stay window. Menu:
// Rename…, Dates…, Night adjustment…, Duplicate, Copy previous period's prices, Move left / right
// (no pricing effect), Delete… (inline confirmation with the dependent rows). Every change is one
// workspace history entry; a rename rewrites the period's rules in the three tables.
import { memo, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type RefObject } from "react"
import { AlertOctagon, AlertTriangle, ArrowLeft, ArrowRight, CalendarClock, CalendarRange, ClipboardCopy, Copy, CopyPlus, MoreHorizontal, Pencil, Percent, Plus, SquareDashedMousePointer, Trash2 } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { date as fmtDate } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, Field, FormGrid, Input, isSaveShortcut, Menu, MenuItem, MenuSeparator, Notice, Popover, useTooltip } from "../../../ui"
import { WeekdayPicker } from "../components/pickers"
import { displayText, type ShOp } from "../lib/shorthand"
import type { Tables } from "../lib/tables"
import { splitCsv, WEEKDAY_CODES, weekdayName } from "../lib/util"
import type { MatrixPeriod } from "./model.ts"
import { parsePeriodAdjust, periodAdjustEditText, setPeriodAdjustment, setPeriodFields } from "./matrixView.ts"
import { addPeriod, copyPeriodFrom, copyPreviousPeriod, deletePeriod, duplicatePeriod, isoDay, isoOfDay, movePeriod, periodDependents, renamePeriod, shiftSeasonYears, type SeasonShift } from "./periods.ts"
import { periodHeaderId } from "./issues.ts"
import { str } from "./rows.ts"
import { headerPick, type Edit } from "./RoomRowHeader"
import type { CellIssue } from "./useCellIssues"

export interface PeriodHeaderProps {
  period: MatrixPeriod
  index: number
  count: number
  tables: Tables
  readOnly: boolean
  edit: Edit
  /** the column was just added with "+ Period": its end date is edited inline, focused */
  fresh: boolean
  /** the new period's inline dates are closed: `byKey` when Enter, Ctrl/Cmd+S or Escape closed
   * them (the focus they held goes to the period's first cell), not when leaving them did */
  onFreshDone: (byKey: boolean) => void
  decimalMark: "." | ","
  /** the contract currency's minor units: the night adjustment's +/- amounts are parsed with them
   * (O5: AMBIGUOUS only below 3 decimals) */
  minorUnits: number
  /** selecting the column's editable cells (header click, the menu's "Select prices"); the
   * column's index in the grid is `index + 1` (All periods is column 0) */
  onSelect?: (c: number, add: boolean, extend?: boolean) => void
  /** the menu button's tabIndex in the grid's header lane (ui/grid.ts; -1 while the grid has a cell) */
  laneTab?: number
  /** validation issues about the period itself (PERIOD_RANGE, PERIOD_OVERLAP, PERIOD_DUPLICATE;
   * S15): a glyph, the messages in the header's description; the header can then take the focus */
  issue?: CellIssue
  /** the period was deleted (its header, menu and confirmation are gone): the matrix moves the
   * focus to the nearest cell left (S16 review) */
  onRemoved?: (index: number) => void
  /** Duplicate made the period `code` (unnamed): the matrix opens Rename… on its header */
  onDuplicated?: (code: string) => void
  /** open Rename… now (a period just made by Duplicate), then call onRenameOpened */
  renameNow?: boolean
  onRenameOpened?: () => void
}

type Open = "rename" | "dates" | "adjust" | "delete" | "copyfrom" | null | "copyfrom"

const dayMonths = new Map<string, Intl.DateTimeFormat>()
function dayMonth(locale: string): Intl.DateTimeFormat {
  let f = dayMonths.get(locale)
  if (!f) {
    f = new Intl.DateTimeFormat(locale, { day: "2-digit", month: "short" })
    dayMonths.set(locale, f)
  }
  return f
}

/** "01–30 Apr" / "01 Apr – 15 May": a compact range in the viewer's locale (display only; the
 * year is the stay window's, shown on the strip). */
function compactRange(start: string, end: string, locale: string): string {
  const a = isoDay(start)
  const b = isoDay(end)
  if (a === null || b === null) return ""
  const at = (iso: string) => new Date(`${iso}T12:00:00`)
  try {
    return dayMonth(locale).formatRange(at(start), at(end))
  } catch {
    return `${fmtDate(start, "short")} – ${fmtDate(end, "short")}`
  }
}

/** Memoised: the header re-renders when its period, the tables or its state change, not when the
 * active cell moves. */
export const PeriodHeader = memo(PeriodHeaderImpl)

function PeriodHeaderImpl(p: PeriodHeaderProps) {
  const { t, locale } = useTexT()
  const { period } = p
  const [open, setOpen] = useState<Open>(null)
  const wrap = useRef<HTMLSpanElement>(null)
  const anchor = useMemo<RefObject<HTMLElement | null>>(
    () => ({
      get current() {
        return wrap.current?.querySelector<HTMLElement>('button[aria-haspopup="menu"]') ?? wrap.current
      },
    }),
    [],
  )
  const close = () => setOpen(null)
  const code = period.code
  // a copy made by Duplicate has no name: Rename… opens on it at once (S16 review)
  const { renameNow, onRenameOpened, readOnly } = p
  // Rename… from the menu starts in the code; on a copy, in its (empty) name
  const [nameFirst, setNameFirst] = useState(false)
  useEffect(() => {
    if (!renameNow || readOnly) return
    setNameFirst(true)
    setOpen("rename")
    onRenameOpened?.()
  }, [renameNow, onRenameOpened, readOnly])
  const adjust = period.adjusted ? p.tables.periods.find((x) => str(x.period_code) === code) : undefined
  const adjustText = adjust ? displayText(str(adjust.adjustment_op) as ShOp, str(adjust.adjustment_value), "period_adjust", { decimalMark: p.decimalMark }) : ""
  const weekdays = splitCsv(period.weekdays)
  const select = p.onSelect ? (add: boolean, extend = false) => p.onSelect?.(p.index + 1, add, extend) : undefined
  const issueId = useId()
  const issue = p.issue
  const IssueIcon = issue?.level === "ERROR" ? AlertOctagon : AlertTriangle
  // the issue's messages on hover and on focus; described once, by the hidden text below
  const tip = useTooltip(issue ? issue.text : null, { describe: false })
  const tp = tip.triggerProps

  return (
    <div
      role="columnheader"
      data-cellid={periodHeaderId(code)}
      data-issue={issue ? issue.level.toLowerCase() : undefined}
      // an issue's link focuses the header (S15)
      tabIndex={issue ? -1 : undefined}
      aria-invalid={issue?.level === "ERROR" ? true : undefined}
      aria-describedby={issue ? issueId : undefined}
      ref={tp.ref}
      onPointerEnter={tp.onPointerEnter}
      onPointerLeave={tp.onPointerLeave}
      onPointerDown={tp.onPointerDown}
      onFocus={tp.onFocus}
      onBlur={tp.onBlur}
      onKeyDown={tp.onKeyDown}
      onMouseDown={(e) => headerPick(e, select)}
      className={cn(
        "flex min-w-0 flex-col justify-end gap-0.5 border-r border-b border-zinc-200 px-2 py-1.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-tex-500 focus-visible:ring-inset",
        p.index % 2 ? "bg-zinc-50" : "bg-white",
        // a dotted top border on a weekday-limited period (§3.18): Tailwind has no per-side style
        weekdays.length > 0 && "border-t-2 border-t-zinc-400 [border-top-style:dotted]!",
        issue && (issue.level === "ERROR" ? "shadow-[inset_0_-2px_0_var(--color-rose-500)]" : "shadow-[inset_0_-2px_0_var(--color-amber-500)]"),
      )}
    >
      {issue && (
        <span id={issueId} hidden>
          {issue.text}
        </span>
      )}
      <span className="flex min-w-0 items-center gap-1">
        <span className="rounded bg-zinc-900 px-1 font-mono text-[11px] font-semibold text-white">{code}</span>
        {issue && <IssueIcon aria-hidden className={cn("size-3.5 shrink-0", issue.level === "ERROR" ? "text-rose-600" : "text-amber-600", issue.stale && "opacity-50")} />}
        {period.adjusted && (
          <Badge tone="warning" className="px-1 py-0 text-[10px]" title={t("rates.ws.period.adjusted", { rule: adjustText })}>
            ◆ {adjustText}
          </Badge>
        )}
        {!p.readOnly && (
          <span ref={wrap} className="ml-auto shrink-0">
            <Menu
              label={t("rates.ws.period.menu", { period: code })}
              icon={<MoreHorizontal className="size-4" aria-hidden />}
              size="sm"
              className="size-6!"
              buttonProps={{ tabIndex: p.laneTab ?? -1, "data-lane-col": String(p.index + 1) }}
            >
              {select && (
                <>
                  <MenuItem icon={<SquareDashedMousePointer className="size-4" />} onSelect={() => select(false)}>
                    {t("rates.ws.period.select")}
                  </MenuItem>
                  <MenuSeparator />
                </>
              )}
              <MenuItem
                icon={<Pencil className="size-4" />}
                onSelect={() => {
                  setNameFirst(false)
                  setOpen("rename")
                }}
              >
                {t("rates.ws.period.rename")}
              </MenuItem>
              <MenuItem icon={<CalendarRange className="size-4" />} onSelect={() => setOpen("dates")}>
                {t("rates.ws.period.dates")}
              </MenuItem>
              <MenuItem icon={<Percent className="size-4" />} onSelect={() => setOpen("adjust")}>
                {t("rates.ws.period.adjust")}
              </MenuItem>
              <MenuSeparator />
              <MenuItem
                icon={<CopyPlus className="size-4" />}
                onSelect={() => {
                  let made = ""
                  p.edit(t("rates.ws.h.duplicate_period", { period: code }), (tb) => {
                    const r = duplicatePeriod(tb, code)
                    if ("error" in r) return tb
                    made = r.code
                    return r.tables
                  })
                  if (made) p.onDuplicated?.(made)
                }}
              >
                {t("rates.ws.period.duplicate")}
              </MenuItem>
              <MenuItem
                icon={<Copy className="size-4" />}
                disabled={p.index === 0}
                onSelect={() =>
                  p.edit(t("rates.ws.h.copy_previous", { period: code }), (tb) => {
                    const r = copyPreviousPeriod(tb, code)
                    return "error" in r ? tb : r.tables
                  })
                }
              >
                {t("rates.ws.period.copy_previous")}
              </MenuItem>
              {/* any season's prices, not only the left neighbour's (UX revision 2026-10) */}
              <MenuItem icon={<ClipboardCopy className="size-4" />} disabled={p.count < 2} onSelect={() => setOpen("copyfrom")}>
                {t("rates.ws.period.copy_from")}
              </MenuItem>
              <MenuSeparator />
              <MenuItem icon={<ArrowLeft className="size-4" />} disabled={p.index === 0} onSelect={() => p.edit(t("rates.ws.h.move_period", { period: code }), (tb) => movePeriod(tb, code, -1))}>
                {t("rates.ws.period.move_left")}
              </MenuItem>
              <MenuItem
                icon={<ArrowRight className="size-4" />}
                disabled={p.index >= p.count - 1}
                onSelect={() => p.edit(t("rates.ws.h.move_period", { period: code }), (tb) => movePeriod(tb, code, 1))}
              >
                {t("rates.ws.period.move_right")}
              </MenuItem>
              <MenuSeparator />
              <MenuItem icon={<Trash2 className="size-4" />} tone="danger" onSelect={() => setOpen("delete")}>
                {t("rates.ws.period.delete")}
              </MenuItem>
            </Menu>
          </span>
        )}
      </span>
      {period.name && <span className="truncate text-xs font-medium text-zinc-800">{period.name}</span>}
      {p.fresh && !p.readOnly ? (
        <FreshDates {...p} />
      ) : (
        <span className="truncate text-[11px] text-zinc-500 tabular-nums">{compactRange(period.start, period.end, locale) || t("rates.ws.period.no_dates")}</span>
      )}
      {weekdays.length > 0 && <span className="truncate text-[10px] text-zinc-500">{t("rates.periods.only_days", { days: weekdays.map(dayName).join(", ") })}</span>}

      {open === "rename" && <RenamePopover {...p} anchor={anchor} onClose={close} nameFirst={nameFirst} />}
      {open === "dates" && <DatesPopover {...p} anchor={anchor} onClose={close} />}
      {open === "adjust" && <AdjustPopover {...p} anchor={anchor} onClose={close} />}
      {open === "delete" && <DeletePopover {...p} anchor={anchor} onClose={close} />}
      {open === "copyfrom" && <CopyFromPopover {...p} anchor={anchor} onClose={close} />}
      {tip.tooltip}
    </div>
  )
}

/** A stored weekday code ("Fri") in the viewer's language, as the periods table shows it. */
const dayName = (code: string) => {
  const i = WEEKDAY_CODES.findIndex((c) => c.toLowerCase() === code.slice(0, 3).toLowerCase())
  return i < 0 ? code : weekdayName(i)
}

/** The inline dates of a column just added: the end date is focused; Enter or leaving the field
 * commits it, Escape keeps the proposed dates. A period without a dated one before it asks for
 * both dates. Only a key that closes them hands the focus on (to the period's first cell); a click
 * elsewhere leaves it where the click put it, and scrolls nothing (final follow-up). */
function FreshDates(p: PeriodHeaderProps) {
  const { t } = useTexT()
  const { period } = p
  const [start, setStart] = useState(period.start)
  const [end, setEnd] = useState(period.end)
  const first = useRef<HTMLInputElement>(null)
  const done = useRef(false)
  useEffect(() => {
    first.current?.focus()
  }, [])
  const needsStart = !period.start
  const finish = (save: boolean, byKey: boolean) => {
    if (done.current) return
    done.current = true
    if (save) {
      const s = isoDay(start) === null ? period.start : start
      const e = isoDay(end) === null ? period.end : end
      p.edit(t("rates.ws.h.period_dates", { period: period.code }), (tb) => setPeriodFields(tb, period.code, { start_date: s, end_date: e }))
    }
    p.onFreshDone(byKey)
  }
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    // Ctrl/Cmd+S commits the dates first; the version editor's save then sends them (S16 re-review)
    if (isSaveShortcut(e)) finish(true, true)
    else if (e.key === "Enter") {
      e.preventDefault()
      finish(true, true)
    } else if (e.key === "Escape") {
      e.preventDefault()
      e.stopPropagation()
      finish(false, true)
    }
  }
  // typed dates not in the version yet (keptState.UNCOMMITTED_INPUT): the tab asks before it closes
  const changed = start !== period.start || end !== period.end
  return (
    <span
      className="flex flex-col gap-0.5"
      data-uncommitted=""
      data-changed={changed ? "" : undefined}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) finish(true, false)
      }}
    >
      {needsStart && (
        <input
          ref={first}
          type="date"
          aria-label={t("rates.ws.period.start_of", { period: period.code })}
          value={start}
          onChange={(e) => setStart(e.target.value)}
          onKeyDown={onKey}
          className="h-6 w-full rounded border border-zinc-300 px-1 text-[11px]"
        />
      )}
      <input
        ref={needsStart ? undefined : first}
        type="date"
        aria-label={t("rates.ws.period.end_of", { period: period.code })}
        value={end}
        min={start || undefined}
        onChange={(e) => setEnd(e.target.value)}
        onKeyDown={onKey}
        className="h-6 w-full rounded border border-tex-400 px-1 text-[11px]"
      />
    </span>
  )
}

type PopProps = PeriodHeaderProps & { anchor: RefObject<HTMLElement | null>; onClose: () => void }

const PERIOD_ERRORS: Record<string, string> = {
  BLANK_CODE: "rates.ws.period.err.BLANK_CODE",
  DUPLICATE_CODE: "rates.ws.period.err.DUPLICATE_CODE",
  UNKNOWN_PERIOD: "rates.ws.period.err.UNKNOWN_PERIOD",
}

function RenamePopover(p: PopProps & { nameFirst?: boolean }) {
  const { t } = useTexT()
  const row = p.tables.periods.find((x) => str(x.period_code) === p.period.code)
  const [code, setCode] = useState(p.period.code)
  const [name, setName] = useState(str(row?.period_name))
  const [error, setError] = useState("")
  const deps = periodDependents(p.tables, p.period.code)
  const rules = deps.prices + deps.occupancy + deps.boards
  return (
    <Popover open onClose={p.onClose} anchorRef={p.anchor} label={t("rates.ws.period.rename_title", { period: p.period.code })} width="md">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          const to = code.trim()
          if (to === p.period.code && name === str(row?.period_name)) return p.onClose()
          const probe = renamePeriod(p.tables, p.period.code, to, name)
          if ("error" in probe) return setError(t(PERIOD_ERRORS[probe.error] ?? "rates.ws.period.err.BLANK_CODE"))
          p.edit(t("rates.ws.h.rename_period", { period: p.period.code, to }), (tb) => {
            const r = renamePeriod(tb, p.period.code, to, name)
            return "error" in r ? tb : r.tables
          })
          p.onClose()
        }}
      >
        <FormGrid cols={2}>
          <Field label={t("rates.f.period_code")} required error={error || undefined} hint={t("rates.h.period_code")}>
            <Input
              value={code}
              maxLength={40}
              onChange={(e) => {
                setCode(e.target.value)
                setError("")
              }}
              data-autofocus={p.nameFirst ? undefined : true}
            />
          </Field>
          <Field label={t("rates.f.period_name")}>
            <Input value={name} maxLength={140} onChange={(e) => setName(e.target.value)} data-autofocus={p.nameFirst ? true : undefined} />
          </Field>
        </FormGrid>
        {rules > 0 && <p className="text-xs text-zinc-500">{t("rates.ws.period.rename_rewrites", { count: rules })}</p>}
        <PopActions onCancel={p.onClose} />
      </form>
    </Popover>
  )
}

/** "Copy prices from…": this period's room prices, occupancy and child rules and boards become a
 * copy of another period's (one undoable edit; the rows are listed by count first). */
function CopyFromPopover(p: PopProps) {
  const { t, locale } = useTexT()
  const others = p.tables.periods.filter((x) => str(x.period_code) !== p.period.code)
  const idx = p.tables.periods.findIndex((x) => str(x.period_code) === p.period.code)
  const left = idx > 0 ? str(p.tables.periods[idx - 1].period_code) : ""
  const [from, setFrom] = useState(left || str(others[0]?.period_code))
  const mine = periodDependents(p.tables, p.period.code)
  const theirs = periodDependents(p.tables, from)
  const label = (x: (typeof others)[number]) => {
    const range = compactRange(str(x.start_date), str(x.end_date), locale)
    return [str(x.period_code), str(x.period_name), range].filter(Boolean).join(" · ")
  }
  return (
    <Popover open onClose={p.onClose} anchorRef={p.anchor} label={t("rates.ws.period.copy_from_title", { period: p.period.code })} width="md">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (!from) return
          p.edit(t("rates.ws.h.copy_from", { period: p.period.code, from }), (tb) => {
            const r = copyPeriodFrom(tb, from, p.period.code)
            return "error" in r ? tb : r.tables
          })
          p.onClose()
        }}
      >
        <Field label={t("rates.ws.period.copy_from_source")}>
          <select
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            data-autofocus
            className="h-9 w-full rounded-lg border border-zinc-300 bg-white px-2 text-sm text-zinc-900 focus:border-tex-500 focus:ring-2 focus:ring-tex-500/30 focus:outline-none"
          >
            {others.map((x) => (
              <option key={str(x.period_code)} value={str(x.period_code)}>
                {label(x)}
              </option>
            ))}
          </select>
        </Field>
        <p className="text-xs text-zinc-600">
          {t("rates.ws.period.copy_from_counts", {
            period: p.period.code,
            from,
            mine: mine.prices + mine.occupancy + mine.boards,
            theirs: theirs.prices + theirs.occupancy + theirs.boards,
          })}
        </p>
        <PopActions onCancel={p.onClose} label={t("rates.ws.period.copy_from_apply")} />
      </form>
    </Popover>
  )
}

function DatesPopover(p: PopProps) {
  const { t } = useTexT()
  const row = p.tables.periods.find((x) => str(x.period_code) === p.period.code)
  const [start, setStart] = useState(str(row?.start_date))
  const [end, setEnd] = useState(str(row?.end_date))
  const [weekdays, setWeekdays] = useState(str(row?.weekdays))
  const [priority, setPriority] = useState(String(row?.priority ?? 0))
  const a = isoDay(start)
  const b = isoDay(end)
  const orderError = a !== null && b !== null && b < a
  const prioOk = /^-?[0-9]{1,4}$/.test(priority.trim())
  const ok = a !== null && b !== null && !orderError && prioOk
  return (
    <Popover open onClose={p.onClose} anchorRef={p.anchor} label={t("rates.ws.period.dates_title", { period: p.period.code })} width="md">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (!ok) return
          p.edit(t("rates.ws.h.period_dates", { period: p.period.code }), (tb) =>
            setPeriodFields(tb, p.period.code, { start_date: start, end_date: end, weekdays, priority: parseInt(priority.trim(), 10) }),
          )
          p.onClose()
        }}
      >
        <FormGrid cols={2}>
          <Field label={t("rates.f.start_date")} required>
            <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} data-autofocus />
          </Field>
          <Field label={t("rates.f.end_date")} required hint={t("rates.h.end_inclusive")} error={orderError ? t("rates.ws.period.err.order") : undefined}>
            <Input type="date" value={end} min={start || undefined} onChange={(e) => setEnd(e.target.value)} />
          </Field>
        </FormGrid>
        <div className="space-y-1.5">
          <span className="block text-sm font-medium text-zinc-800">{t("rates.f.weekdays")}</span>
          <WeekdayPicker value={weekdays} onChange={setWeekdays} label={t("rates.f.weekdays")} />
          <p className="text-xs text-zinc-500">{t("rates.h.weekdays")}</p>
        </div>
        <Field label={t("rates.f.priority")} hint={t("rates.h.period_priority")} error={prioOk ? undefined : t("rates.ws.period.err.priority")}>
          <Input inputMode="numeric" value={priority} onChange={(e) => setPriority(e.target.value)} />
        </Field>
        <PopActions onCancel={p.onClose} disabled={!ok} />
      </form>
    </Popover>
  )
}

function AdjustPopover(p: PopProps) {
  const { t } = useTexT()
  // ASCII text that reads back to the stored adjustment with the contract's minor units (O5)
  const [text, setText] = useState(() => periodAdjustEditText(p.tables, p.period.code, { decimalMark: p.decimalMark, minorUnits: p.minorUnits }))
  const parsed = parsePeriodAdjust(text, { minorUnits: p.minorUnits })
  const reading = !parsed.ok
    ? t(`rates.sh.err.${parsed.code}`)
    : parsed.kind === "clear"
      ? t("rates.ws.period.adjust_none", { period: p.period.code })
      : parsed.kind === "rule"
        ? t("rates.ws.period.adjust_reads", { period: p.period.code, rule: displayText(parsed.op, parsed.value, "period_adjust", { decimalMark: p.decimalMark }) })
        : ""
  return (
    <Popover open onClose={p.onClose} anchorRef={p.anchor} label={t("rates.ws.period.adjust_title", { period: p.period.code })} width="md">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          const r = setPeriodAdjustment(p.tables, p.period.code, parsed)
          if ("error" in r) return
          p.edit(t("rates.ws.h.adjust_period", { period: p.period.code }), (tb) => {
            const x = setPeriodAdjustment(tb, p.period.code, parsed)
            return "error" in x ? tb : x.tables
          })
          p.onClose()
        }}
      >
        <Field label={t("rates.f.adjustment_op")} hint={t("rates.ws.period.adjust_hint")}>
          <Input value={text} onChange={(e) => setText(e.target.value)} aria-invalid={!parsed.ok || undefined} autoComplete="off" spellCheck={false} data-autofocus />
        </Field>
        <p role="status" aria-live="polite" className={cn("rounded-md px-2.5 py-1.5 text-sm", parsed.ok ? "bg-zinc-50 text-zinc-700" : "bg-rose-50 text-rose-800")}>
          {reading}
        </p>
        <Notice tone="info">{t("rates.ws.period.adjust_note")}</Notice>
        <PopActions onCancel={p.onClose} disabled={!parsed.ok} />
      </form>
    </Popover>
  )
}

function DeletePopover(p: PopProps) {
  const { t } = useTexT()
  const deps = periodDependents(p.tables, p.period.code)
  const parts = [
    deps.prices ? t("rates.ws.count.prices", { count: deps.prices }) : "",
    deps.occupancy ? t("rates.ws.count.occupancy", { count: deps.occupancy }) : "",
    deps.boards ? t("rates.ws.count.boards", { count: deps.boards }) : "",
  ].filter(Boolean)
  return (
    <Popover open onClose={p.onClose} anchorRef={p.anchor} label={t("rates.ws.period.delete_title", { period: p.period.code })} width="md">
      <div className="space-y-3 text-sm">
        <p className="text-zinc-700">{parts.length ? t("rates.ws.period.delete_body", { rows: parts.join(", ") }) : t("rates.ws.period.delete_body_none")}</p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={p.onClose} data-autofocus>
            {t("core.action.cancel")}
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={() => {
              const removed = p.edit(t("rates.ws.h.delete_period", { period: p.period.code }), (tb) => deletePeriod(tb, p.period.code).tables)
              p.onClose()
              if (removed) p.onRemoved?.(p.index)
            }}
          >
            {t("rates.ws.period.delete")}
          </Button>
        </div>
      </div>
    </Popover>
  )
}

function PopActions({ onCancel, disabled, label }: { onCancel: () => void; disabled?: boolean; label?: string }) {
  const { t } = useTexT()
  return (
    <div className="flex justify-end gap-2 pt-1">
      <Button variant="secondary" size="sm" onClick={onCancel}>
        {t("core.action.cancel")}
      </Button>
      <Button size="sm" type="submit" disabled={disabled}>
        {label ?? t("core.action.apply")}
      </Button>
    </div>
  )
}

/** The "+ Period" column header: adds a period after the last one (next free code, the day after
 * the last period ends, as long as it) and hands its end date to the header for inline editing. */
export function AddPeriodHeader({ readOnly, edit, onAdded, col, laneTab = -1 }: { readOnly: boolean; edit: Edit; onAdded: (code: string) => void; col?: number; laneTab?: number }) {
  const { t } = useTexT()
  return (
    <div role="columnheader" className="flex items-end border-b border-zinc-200 bg-white px-1.5 py-1.5">
      {!readOnly && (
        <Button
          variant="ghost"
          size="sm"
          aria-label={t("rates.ws.period.add_label")}
          data-add-period=""
          data-lane-col={col === undefined ? undefined : String(col)}
          tabIndex={laneTab}
          icon={<Plus className="size-4" aria-hidden />}
          onClick={() => {
            let code = ""
            edit(t("rates.ws.h.add_period"), (tb) => {
              const r = addPeriod(tb)
              code = r.code
              return r.tables
            })
            if (code) onAdded(code)
          }}
        >
          {t("rates.ws.period.add")}
        </Button>
      )}
    </div>
  )
}

/** A thin timeline of the periods (weekday-limited ones aside) against the stay window: gaps and
 * overlaps are marked with a pattern and counted in text (§3.9). Integer day numbers only. */
export function PeriodStrip({ tables, stayFrom, stayTo }: { tables: Tables; stayFrom?: string | null; stayTo?: string | null }) {
  const { t } = useTexT()
  const spans = tables.periods
    .filter((x) => !str(x.weekdays))
    .map((x) => ({ key: x._key, code: str(x.period_code), a: isoDay(x.start_date), b: isoDay(x.end_date) }))
    .filter((x): x is { key: string; code: string; a: number; b: number } => x.a !== null && x.b !== null && x.b >= x.a)
  if (!spans.length) return null
  const from = isoDay(stayFrom) ?? Math.min(...spans.map((x) => x.a))
  const to = isoDay(stayTo) ?? Math.max(...spans.map((x) => x.b))
  if (to < from) return null
  const days = to - from + 1
  // coverage per day of the window, and the runs of uncovered (gap) and doubly covered (overlap) days
  const cover = new Array<number>(days).fill(0)
  for (const s of spans) for (let d = Math.max(s.a, from); d <= Math.min(s.b, to); d++) cover[d - from] += 1
  const runs: { kind: "gap" | "overlap"; a: number; b: number }[] = []
  for (let i = 0; i < days; i++) {
    const kind = cover[i] === 0 ? "gap" : cover[i] > 1 ? "overlap" : null
    if (!kind) continue
    const last = runs[runs.length - 1]
    if (last && last.kind === kind && last.b === i - 1) last.b = i
    else runs.push({ kind, a: i, b: i })
  }
  const gaps = runs.filter((r) => r.kind === "gap").length
  const overlaps = runs.filter((r) => r.kind === "overlap").length
  const pct = (n: number) => `${(n / days) * 100}%`
  return (
    <figure aria-label={t("rates.ws.strip.label")} className="mb-1.5">
      <div className="relative h-2 overflow-hidden rounded-full bg-zinc-100">
        {spans.map((s, i) => {
          const a = Math.max(s.a, from) - from
          const b = Math.min(s.b, to) - from
          if (b < a) return null
          return <span key={s.key} className={cn("absolute inset-y-0", i % 2 ? "bg-tex-300" : "bg-tex-200")} style={{ left: pct(a), width: pct(b - a + 1) }} title={s.code} />
        })}
        {runs.map((r) => (
          <span
            key={`${r.kind}${r.a}`}
            className={cn("absolute inset-y-0", r.kind === "gap" ? "bg-[repeating-linear-gradient(45deg,#f43f5e_0_2px,transparent_2px_5px)]" : "bg-rose-500/70")}
            style={{ left: pct(r.a), width: pct(r.b - r.a + 1) }}
          />
        ))}
      </div>
      <figcaption className="mt-0.5 flex justify-between gap-2 text-[11px] text-zinc-500">
        <span>{fmtDate(isoOfDay(from), "short")}</span>
        <span className={cn(gaps || overlaps ? "text-rose-700" : "")}>
          {gaps || overlaps
            ? [gaps ? t("rates.ws.strip.gaps", { count: gaps }) : "", overlaps ? t("rates.ws.strip.overlaps", { count: overlaps }) : ""].filter(Boolean).join(" · ")
            : t("rates.ws.strip.covered")}
        </span>
        <span>{fmtDate(isoOfDay(to), "short")}</span>
      </figcaption>
    </figure>
  )
}

/** What a season shift moved, for the user to check before saving (UX revision 2026-10): every
 * period's old and new dates (the first eight, then a count), the offers, and that prices and
 * rules were kept. */
export function SeasonShiftSummary({ shift, years, tables }: { shift: SeasonShift; years: number; tables: Tables }) {
  const { t } = useTexT()
  const name = (code: string) => str(tables.periods.find((x) => str(x.period_code) === code)?.period_name)
  const range = (r: [string, string]) => (r[0] && r[1] ? `${fmtDate(r[0], "short")} – ${fmtDate(r[1], "short")}` : "—")
  return (
    <div className="space-y-1.5">
      <p>{t(years > 0 ? "rates.ws.season.done_later" : "rates.ws.season.done_earlier", { count: shift.periods.length, years: Math.abs(years) })}</p>
      {shift.periods.length > 0 && (
        <ul className="space-y-0.5 text-xs tabular-nums">
          {shift.periods.slice(0, 8).map((x) => (
            <li key={x.code}>
              <span className="font-mono font-semibold">{x.code}</span> {name(x.code)}: {range(x.from)} → <span className="font-semibold">{range(x.to)}</span>
            </li>
          ))}
          {shift.periods.length > 8 && <li>{t("rates.ws.season.more", { count: shift.periods.length - 8 })}</li>}
        </ul>
      )}
      {shift.offers > 0 && <p className="text-xs">{t("rates.ws.season.offers", { count: shift.offers })}</p>}
      <p className="text-xs">{t("rates.ws.season.check")}</p>
    </div>
  )
}

/** "Shift dates…" beside the period strip: every period and offer a year later (a new season from
 * the last one) or earlier, as one undoable edit, with what moved shown until the next shift. */
export function SeasonShiftControl({ tables, edit, readOnly }: { tables: Tables; edit: Edit; readOnly: boolean }) {
  const { t } = useTexT()
  const [done, setDone] = useState<{ shift: SeasonShift; years: number } | null>(null)
  if (readOnly || !tables.periods.some((x) => str(x.start_date))) return null
  const run = (years: number) => {
    let res: SeasonShift | null = null
    edit(t(years > 0 ? "rates.ws.h.shift_later" : "rates.ws.h.shift_earlier", { years: Math.abs(years) }), (tb) => {
      res = shiftSeasonYears(tb, years)
      return res.tables
    })
    if (res) setDone({ shift: res, years })
  }
  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <Menu label={t("rates.ws.season.shift")} text={t("rates.ws.season.shift")} icon={<CalendarClock className="size-4" aria-hidden />} variant="ghost" size="sm" placement="bottom-end">
          <MenuItem onSelect={() => run(1)}>{t("rates.ws.season.plus_year")}</MenuItem>
          <MenuItem onSelect={() => run(-1)}>{t("rates.ws.season.minus_year")}</MenuItem>
        </Menu>
      </div>
      {done && (
        <div>
          <Notice tone="info" title={t("rates.ws.season.title")}>
            <SeasonShiftSummary shift={done.shift} years={done.years} tables={tables} />
          </Notice>
        </div>
      )}
    </div>
  )
}
