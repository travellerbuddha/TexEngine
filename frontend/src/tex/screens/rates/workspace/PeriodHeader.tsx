// Period columns of the price matrix (PRICING_WORKSPACE_UX.md §3.9; slice S9): the column header
// (code, name, compact dates, weekday and night-adjustment badges, the period menu), the
// "+ Period" column, and the thin PeriodStrip of the periods against the stay window. Menu:
// Rename…, Dates…, Night adjustment…, Duplicate, Copy previous period's prices, Move left / right
// (no pricing effect), Delete… (inline confirmation with the dependent rows). Every change is one
// workspace history entry; a rename rewrites the period's rules in the three tables.
import { memo, useEffect, useMemo, useRef, useState, type KeyboardEvent, type RefObject } from "react"
import { ArrowLeft, ArrowRight, CalendarRange, Copy, CopyPlus, MoreHorizontal, Pencil, Percent, Plus, Trash2 } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { date as fmtDate } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, Field, FormGrid, Input, Menu, MenuItem, MenuSeparator, Notice, Popover } from "../../../ui"
import { WeekdayPicker } from "../components/pickers"
import { displayText, parseShorthand, type ShOp } from "../lib/shorthand"
import type { Tables } from "../lib/tables"
import { splitCsv } from "../lib/util"
import type { MatrixPeriod } from "./model.ts"
import { setPeriodAdjustment, setPeriodFields } from "./matrixView.ts"
import { addPeriod, copyPreviousPeriod, deletePeriod, duplicatePeriod, isoDay, isoOfDay, movePeriod, periodDependents, renamePeriod } from "./periods.ts"
import { str } from "./rows.ts"
import type { Edit } from "./RoomRowHeader"

export interface PeriodHeaderProps {
  period: MatrixPeriod
  index: number
  count: number
  tables: Tables
  readOnly: boolean
  edit: Edit
  /** the column was just added with "+ Period": its end date is edited inline, focused */
  fresh: boolean
  onFreshDone: () => void
  decimalMark: "." | ","
}

type Open = "rename" | "dates" | "adjust" | "delete" | null

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
  const adjust = period.adjusted ? p.tables.periods.find((x) => str(x.period_code) === code) : undefined
  const adjustText = adjust ? displayText(str(adjust.adjustment_op) as ShOp, str(adjust.adjustment_value), "period_adjust", { decimalMark: p.decimalMark }) : ""
  const weekdays = splitCsv(period.weekdays)

  return (
    <div
      role="columnheader"
      className={cn(
        "flex min-w-0 flex-col justify-end gap-0.5 border-r border-b border-zinc-200 px-2 py-1.5 text-left",
        p.index % 2 ? "bg-zinc-50" : "bg-white",
        weekdays.length > 0 && "border-t-2 border-t-dotted border-t-zinc-400",
      )}
    >
      <span className="flex min-w-0 items-center gap-1">
        <span className="rounded bg-zinc-900 px-1 font-mono text-[11px] font-semibold text-white">{code}</span>
        {period.adjusted && (
          <Badge tone="warning" className="px-1 py-0 text-[10px]" title={t("rates.ws.period.adjusted", { rule: adjustText })}>
            ◆ {adjustText}
          </Badge>
        )}
        {!p.readOnly && (
          <span ref={wrap} className="ml-auto shrink-0">
            <Menu label={t("rates.ws.period.menu", { period: code })} icon={<MoreHorizontal className="size-4" aria-hidden />} size="sm" className="size-6!">
              <MenuItem icon={<Pencil className="size-4" />} onSelect={() => setOpen("rename")}>
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
                onSelect={() =>
                  p.edit(t("rates.ws.h.duplicate_period", { period: code }), (tb) => {
                    const r = duplicatePeriod(tb, code)
                    return "error" in r ? tb : r.tables
                  })
                }
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
      {weekdays.length > 0 && <span className="truncate text-[10px] text-zinc-500">{t("rates.periods.only_days", { days: weekdays.join(", ") })}</span>}

      {open === "rename" && <RenamePopover {...p} anchor={anchor} onClose={close} />}
      {open === "dates" && <DatesPopover {...p} anchor={anchor} onClose={close} />}
      {open === "adjust" && <AdjustPopover {...p} anchor={anchor} onClose={close} />}
      {open === "delete" && <DeletePopover {...p} anchor={anchor} onClose={close} />}
    </div>
  )
}

/** The inline dates of a column just added: the end date is focused; Enter or leaving the field
 * commits it, Escape keeps the proposed dates. A period without a dated one before it asks for
 * both dates. */
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
  const finish = (save: boolean) => {
    if (done.current) return
    done.current = true
    if (save) {
      const s = isoDay(start) === null ? period.start : start
      const e = isoDay(end) === null ? period.end : end
      p.edit(t("rates.ws.h.period_dates", { period: period.code }), (tb) => setPeriodFields(tb, period.code, { start_date: s, end_date: e }))
    }
    p.onFreshDone()
  }
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault()
      finish(true)
    } else if (e.key === "Escape") {
      e.preventDefault()
      e.stopPropagation()
      finish(false)
    }
  }
  return (
    <span
      className="flex flex-col gap-0.5"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) finish(true)
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

function RenamePopover(p: PopProps) {
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
              data-autofocus
            />
          </Field>
          <Field label={t("rates.f.period_name")}>
            <Input value={name} maxLength={140} onChange={(e) => setName(e.target.value)} />
          </Field>
        </FormGrid>
        {rules > 0 && <p className="text-xs text-zinc-500">{t("rates.ws.period.rename_rewrites", { count: rules })}</p>}
        <PopActions onCancel={p.onClose} />
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
  const row = p.tables.periods.find((x) => str(x.period_code) === p.period.code)
  const current = row && str(row.adjustment_op) ? displayText(str(row.adjustment_op) as ShOp, str(row.adjustment_value), "period_adjust", { decimalMark: p.decimalMark }) : ""
  const [text, setText] = useState(current.replace("×", "x").replace("−", "-"))
  const parsed = parseShorthand(text, "period_adjust")
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
              p.edit(t("rates.ws.h.delete_period", { period: p.period.code }), (tb) => deletePeriod(tb, p.period.code).tables)
              p.onClose()
            }}
          >
            {t("rates.ws.period.delete")}
          </Button>
        </div>
      </div>
    </Popover>
  )
}

function PopActions({ onCancel, disabled }: { onCancel: () => void; disabled?: boolean }) {
  const { t } = useTexT()
  return (
    <div className="flex justify-end gap-2 pt-1">
      <Button variant="secondary" size="sm" onClick={onCancel}>
        {t("core.action.cancel")}
      </Button>
      <Button size="sm" type="submit" disabled={disabled}>
        {t("core.action.apply")}
      </Button>
    </div>
  )
}

/** The "+ Period" column header: adds a period after the last one (next free code, the day after
 * the last period ends, as long as it) and hands its end date to the header for inline editing. */
export function AddPeriodHeader({ readOnly, edit, onAdded }: { readOnly: boolean; edit: Edit; onAdded: (code: string) => void }) {
  const { t } = useTexT()
  return (
    <div role="columnheader" className="flex items-end border-b border-zinc-200 bg-white px-1.5 py-1.5">
      {!readOnly && (
        <Button
          variant="ghost"
          size="sm"
          aria-label={t("rates.periods.add")}
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
