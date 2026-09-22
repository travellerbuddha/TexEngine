import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react"
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react"
import { useI18n } from "../i18n"
import { MAX_NIGHTS } from "../lib/criteria"
import { addDays, addMonths, isoDay, monthGrid, monthStart, nightsBetween, parseDay, today, weekStartFor } from "../lib/dates"
import { Button } from "../ui/controls"
import { Dialog } from "../ui/Dialog"

export function useWide(query = "(min-width: 640px)") {
  const [wide, setWide] = useState(() => (typeof window !== "undefined" ? window.matchMedia(query).matches : true))
  useEffect(() => {
    const mq = window.matchMedia(query)
    const on = () => setWide(mq.matches)
    mq.addEventListener("change", on)
    return () => mq.removeEventListener("change", on)
  }, [query])
  return wide
}

/** Same day of month `delta` months away, clamped to that month's last day. */
function shiftMonth(day: string, delta: number) {
  const d = parseDay(day)
  const target = new Date(d.getFullYear(), d.getMonth() + delta, 1, 12)
  const last = new Date(target.getFullYear(), target.getMonth() + 1, 0, 12).getDate()
  target.setDate(Math.min(d.getDate(), last))
  return isoDay(target)
}

interface CalendarProps {
  checkIn: string | null
  checkOut: string | null
  onPick: (day: string) => void
  wide: boolean
  maxDay: string
}

function Calendar({ checkIn, checkOut, onPick, wide, maxDay }: CalendarProps) {
  const { locale, t, date } = useI18n()
  const min = today()
  const weekStart = useMemo(() => weekStartFor(locale), [locale])
  const [focusDay, setFocusDay] = useState(() => checkOut ?? checkIn ?? min)
  const [offset, setOffset] = useState(() => monthStart(checkIn ?? min))
  const [hover, setHover] = useState<string | null>(null)
  const [keyNav, setKeyNav] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const firstMonth = monthStart(min)
  const lastMonth = monthStart(maxDay)
  const selectingOut = !!checkIn && !checkOut
  const outLimit = checkIn ? addDays(checkIn, MAX_NIGHTS) : maxDay

  const months = useMemo(() => {
    if (wide) return [offset, addMonths(offset, 1)]
    const out: string[] = []
    for (let m = firstMonth; m <= lastMonth; m = addMonths(m, 1)) out.push(m)
    return out
  }, [wide, offset, firstMonth, lastMonth])

  const monthFmt = useMemo(() => new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" }), [locale])
  const weekdays = useMemo(() => {
    const narrow = new Intl.DateTimeFormat(locale, { weekday: "short" })
    const long = new Intl.DateTimeFormat(locale, { weekday: "long" })
    // 2024-01-07 is a Sunday
    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date(2024, 0, 7 + ((weekStart + i) % 7), 12)
      return { short: narrow.format(d), long: long.format(d) }
    })
  }, [locale, weekStart])

  const disabled = (d: string) => d < min || d > maxDay || (selectingOut && (d > outLimit))

  // keep keyboard focus on the focused day after it moves (and scroll it into view)
  useLayoutEffect(() => {
    if (!keyNav) return
    const el = box.current?.querySelector<HTMLButtonElement>(`[data-day="${focusDay}"]`)
    el?.focus()
  }, [focusDay, keyNav, offset])

  // phones: start the scrolling month list at the selection (after the dialog is shown)
  useEffect(() => {
    if (wide) return
    const start = monthStart(checkIn ?? min)
    const raf = requestAnimationFrame(() => {
      if (start === firstMonth) return
      box.current?.querySelector<HTMLElement>(`[data-month="${start}"]`)?.scrollIntoView({ block: "start" })
    })
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wide])

  const move = (d: string) => {
    const next = d < min ? min : d > maxDay ? maxDay : d
    setKeyNav(true)
    setFocusDay(next)
    if (wide) {
      const m = monthStart(next)
      if (m < offset) setOffset(m)
      else if (m > addMonths(offset, 1)) setOffset(addMonths(m, -1))
    }
  }

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const day = (e.target as HTMLElement).dataset?.day
    if (!day) return
    const dow = (parseDay(day).getDay() - weekStart + 7) % 7
    const map: Record<string, () => string> = {
      ArrowLeft: () => addDays(day, -1),
      ArrowRight: () => addDays(day, 1),
      ArrowUp: () => addDays(day, -7),
      ArrowDown: () => addDays(day, 7),
      Home: () => addDays(day, -dow),
      End: () => addDays(day, 6 - dow),
      PageUp: () => shiftMonth(day, -1),
      PageDown: () => shiftMonth(day, 1),
    }
    const f = map[e.key]
    if (!f) return
    e.preventDefault()
    move(f())
  }

  const rangeEnd = checkOut ?? (selectingOut && hover && hover > checkIn! ? hover : null)

  const renderMonth = (first: string) => {
    const cells = monthGrid(first, weekStart)
    const weeks: (string | null)[][] = []
    for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7))
    const captionId = `m-${first}`
    return (
      <div key={first} data-month={first} className="min-w-0">
        <h3 id={captionId} className="mb-2 text-center text-[0.95rem] font-semibold capitalize">
          {monthFmt.format(parseDay(first))}
        </h3>
        <table role="grid" aria-labelledby={captionId} className="w-full table-fixed border-collapse">
          <thead className={wide ? "" : "sr-only"}>
            <tr>
              {weekdays.map((w) => (
                <th key={w.long} scope="col" abbr={w.long} className="pb-1 text-xs font-medium text-muted">
                  {w.short}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {weeks.map((w, wi) => (
              <tr key={wi}>
                {w.map((d, di) => {
                  if (!d) return <td key={di} className="p-0" />
                  const isStart = d === checkIn
                  const isEnd = d === rangeEnd
                  const inRange = !!checkIn && !!rangeEnd && d > checkIn && d < rangeEnd
                  const edge = isStart ? (rangeEnd ? "start" : "single") : isEnd ? "end" : undefined
                  const off = disabled(d)
                  const state = isStart ? t("dates.checkInState") : isEnd && checkOut ? t("dates.checkOutState") : inRange ? t("dates.inStayState") : ""
                  return (
                    <td key={d} className="bk-cell p-0 py-0.5" data-in-range={inRange || undefined} data-edge={edge} aria-selected={isStart || isEnd || inRange || undefined} role="gridcell">
                      <button
                        type="button"
                        className="bk-day"
                        data-day={d}
                        data-today={d === min || undefined}
                        tabIndex={d === focusDay ? 0 : -1}
                        disabled={off}
                        aria-label={`${date(d, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}${state ? `, ${state}` : ""}`}
                        aria-current={d === min ? "date" : undefined}
                        onClick={() => {
                          setFocusDay(d)
                          onPick(d)
                        }}
                        onMouseEnter={() => selectingOut && setHover(d)}
                        onFocus={() => {
                          if (focusDay !== d) setFocusDay(d)
                          if (selectingOut) setHover(d)
                        }}
                      >
                        {parseDay(d).getDate()}
                      </button>
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

  return (
    <div ref={box} onKeyDown={onKey} onMouseLeave={() => setHover(null)}>
      {wide ? (
        <div className="relative">
          <div className="absolute inset-x-0 top-[-4px] flex justify-between">
            <button
              type="button"
              className="grid size-10 place-items-center rounded-full hover:bg-sunken disabled:opacity-30"
              onClick={() => setOffset(addMonths(offset, -1))}
              disabled={offset <= firstMonth}
              aria-label={t("dates.prevMonth")}
            >
              <ChevronLeft className="size-5" aria-hidden />
            </button>
            <button
              type="button"
              className="grid size-10 place-items-center rounded-full hover:bg-sunken disabled:opacity-30"
              onClick={() => setOffset(addMonths(offset, 1))}
              disabled={addMonths(offset, 1) >= lastMonth}
              aria-label={t("dates.nextMonth")}
            >
              <ChevronRight className="size-5" aria-hidden />
            </button>
          </div>
          <div className="grid grid-cols-2 gap-8">{months.map(renderMonth)}</div>
        </div>
      ) : (
        <>
          <div className="sticky top-0 z-10 -mx-5 grid grid-cols-7 border-b border-line bg-surface px-5 py-2 text-center text-xs font-medium text-muted" aria-hidden>
            {weekdays.map((w) => (
              <span key={w.long}>{w.short}</span>
            ))}
          </div>
          <div className="space-y-6 pt-3">{months.map(renderMonth)}</div>
        </>
      )}
    </div>
  )
}

interface PickerProps {
  id: string
  checkIn: string | null
  checkOut: string | null
  onChange: (checkIn: string | null, checkOut: string | null) => void
  error?: string | null
  label?: string
}

/** Stay dates: one field that opens a calendar (full screen on phones, popover on
 * wider screens). Keyboard: arrows move by day/week, PageUp/PageDown by month. */
export function DateRangePicker({ id, checkIn, checkOut, onChange, error, label }: PickerProps) {
  const { t, day } = useI18n()
  const wide = useWide()
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const labelId = useId()
  const valueId = useId()
  const statusId = useId()
  const maxDay = addDays(today(), 540)
  const nights = checkIn && checkOut ? nightsBetween(checkIn, checkOut) : 0

  const pick = (d: string) => {
    if (checkIn && !checkOut && d > checkIn && nightsBetween(checkIn, d) <= MAX_NIGHTS) onChange(checkIn, d)
    else onChange(d, null)
  }

  const status = !checkIn ? t("dates.pickCheckIn") : !checkOut ? t("dates.pickCheckOut") : t("dates.nights", { count: nights })

  return (
    <div>
      <span id={labelId} className="mb-1.5 block text-sm font-medium text-soft">
        {label ?? t("search.dates")}
      </span>
      <button
        ref={trigger}
        id={id}
        type="button"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-labelledby={`${labelId} ${valueId}`}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-err` : undefined}
        className={`bk-input flex items-center gap-2.5 text-left ${error ? "" : ""}`}
      >
        <CalendarDays className="size-5 flex-none text-muted" aria-hidden />
        <span id={valueId} className="min-w-0 flex-1 truncate">
          {checkIn ? (
            <>
              <span className="font-medium">{day(checkIn)}</span>
              <span className="px-1.5 text-muted" aria-hidden>
                →
              </span>
              <span className="sr-only"> – </span>
              <span className="font-medium">{checkOut ? day(checkOut) : t("dates.checkOut")}</span>
              {nights > 0 && <span className="ml-2 text-sm text-muted">· {t("dates.nights", { count: nights })}</span>}
            </>
          ) : (
            <span className="text-[#6b6f77]">{t("dates.placeholder")}</span>
          )}
        </span>
      </button>
      {error && (
        <p id={`${id}-err`} className="mt-1 text-sm font-medium text-bad">
          {error}
        </p>
      )}
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={t("dates.title")}
        closeLabel={t("common.close")}
        variant="full"
        anchor={trigger.current}
        width={wide ? "min(680px, calc(100vw - 32px))" : undefined}
        initialFocus="[data-day][tabindex='0']"
        description={
          <span id={statusId} aria-live="polite">
            {status}
          </span>
        }
        footer={
          <div className="flex items-center justify-between gap-3">
            <Button variant="ghost" onClick={() => onChange(null, null)} disabled={!checkIn}>
              {t("dates.clear")}
            </Button>
            <div className="flex items-center gap-3">
              {checkIn && checkOut && (
                <span className="hidden text-sm text-muted sm:inline">
                  {day(checkIn)} – {day(checkOut)}
                </span>
              )}
              <Button onClick={() => setOpen(false)} disabled={!checkIn || !checkOut}>
                {t("common.done")}
              </Button>
            </div>
          </div>
        }
      >
        <Calendar checkIn={checkIn} checkOut={checkOut} onPick={pick} wide={wide} maxDay={maxDay} />
      </Dialog>
    </div>
  )
}
