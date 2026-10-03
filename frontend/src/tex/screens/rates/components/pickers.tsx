import { useLayoutEffect, useState } from "react"
import { ListChecks } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { useTexT } from "../../../i18n"
import { Badge, Button, Checkbox, Dialog, type Option } from "../../../ui"
import { joinCsv, splitCsv, WEEKDAY_CODES, weekdayName } from "../lib/util"

/**
 * Multi-select stored as a comma list (promotion/extra eligibility, rate-plan boards…).
 * Blank means "all", which is spelled out so a revenue manager never guesses.
 */
export function CsvPicker({
  value,
  onChange,
  options,
  label,
  allLabel,
  disabled,
  id,
  compact,
  ...aria
}: {
  value: string
  onChange: (v: string) => void
  options: Option[]
  label: string
  allLabel?: string
  disabled?: boolean
  id?: string
  compact?: boolean
  "aria-describedby"?: string
  "aria-invalid"?: boolean
}) {
  const { t } = useTexT()
  const [open, setOpen] = useState(false)
  const selected = splitCsv(value)
  const [draft, setDraft] = useState<string[]>(selected)
  // the draft is the value as the popover opens, before its first frame is painted (2Z: a passive effect showed
  // the last opening's ticks for a frame and dropped a click made in it)
  useLayoutEffect(() => {
    if (open) setDraft(splitCsv(value))
  }, [open, value])
  const labelOf = (v: string) => options.find((o) => o.value === v)?.label ?? v
  const summary = selected.length ? selected.map(labelOf).join(", ") : (allLabel ?? t("rates.common.all"))
  const unknown = draft.filter((v) => !options.some((o) => o.value === v))
  return (
    <>
      <button
        id={id}
        type="button"
        disabled={disabled}
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-label={`${label}: ${summary}`}
        aria-describedby={aria["aria-describedby"]}
        aria-invalid={aria["aria-invalid"]}
        className={cn(
          "flex w-full min-w-0 items-center gap-2 rounded-lg border border-zinc-300 bg-white px-2.5 text-left text-sm text-zinc-900 shadow-sm hover:border-zinc-400 disabled:cursor-not-allowed disabled:bg-zinc-50 disabled:text-zinc-500",
          compact ? "h-8" : "h-9",
        )}
      >
        <ListChecks className="size-4 shrink-0 text-zinc-400" aria-hidden />
        <span className={cn("truncate", !selected.length && "text-zinc-500")}>{summary}</span>
      </button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={label}
        description={allLabel ? t("rates.common.csv_hint_all", { all: allLabel }) : t("rates.common.csv_hint")}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDraft([])}>
              {t("rates.common.clear")}
            </Button>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              {t("core.action.cancel")}
            </Button>
            <Button
              onClick={() => {
                onChange(joinCsv(draft))
                setOpen(false)
              }}
            >
              {t("core.action.apply")}
            </Button>
          </>
        }
      >
        <fieldset className="space-y-2">
          <legend className="sr-only">{label}</legend>
          {options.map((o) => (
            <Checkbox
              key={o.value}
              className="flex"
              label={o.label}
              checked={draft.includes(o.value)}
              onChange={(e) => setDraft((d) => (e.target.checked ? [...d, o.value] : d.filter((x) => x !== o.value)))}
            />
          ))}
          {unknown.length > 0 && (
            <div className="flex flex-wrap items-center gap-1 pt-2 text-xs text-zinc-500">
              {t("rates.common.other_values")}
              {unknown.map((u) => (
                <Badge key={u}>{u}</Badge>
              ))}
            </div>
          )}
        </fieldset>
      </Dialog>
    </>
  )
}

/** Weekday toggles stored as "Mon,Fri,Sat" (period weekday masks). Blank = every day. */
export function WeekdayPicker({
  value,
  onChange,
  label,
  disabled,
}: {
  value: string
  onChange: (v: string) => void
  label: string
  disabled?: boolean
}) {
  const set = new Set(splitCsv(value).map((s) => s.slice(0, 3).toLowerCase()))
  const toggle = (code: string) => {
    const lc = code.toLowerCase()
    const next = WEEKDAY_CODES.filter((c) => (c.toLowerCase() === lc ? !set.has(lc) : set.has(c.toLowerCase())))
    onChange(joinCsv([...next]))
  }
  return (
    <div role="group" aria-label={label} className="flex gap-0.5">
      {WEEKDAY_CODES.map((c, i) => {
        const on = set.has(c.toLowerCase())
        return (
          <button
            key={c}
            type="button"
            disabled={disabled}
            aria-pressed={on}
            aria-label={weekdayName(i, "long")}
            title={weekdayName(i, "long")}
            onClick={() => toggle(c)}
            className={cn(
              "h-8 min-w-9 rounded-md border px-1 text-xs font-medium transition-colors disabled:cursor-not-allowed",
              on ? "border-tex-600 bg-tex-600 text-white dark:text-zinc-50" : "border-zinc-300 bg-white text-zinc-600 hover:bg-zinc-50",
            )}
          >
            <span aria-hidden>{weekdayName(i)}</span>
          </button>
        )
      })}
    </div>
  )
}

/** Weekday checkboxes for the grid bulk editor: numbers 0=Mon…6=Sun. */
export function WeekdayNumbers({
  value,
  onChange,
  label,
}: {
  value: number[]
  onChange: (v: number[]) => void
  label: string
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1">
      {Array.from({ length: 7 }, (_, i) => {
        const on = value.includes(i)
        return (
          <button
            key={i}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(on ? value.filter((x) => x !== i) : [...value, i].sort())}
            className={cn(
              "h-8 min-w-11 rounded-md border px-2 text-xs font-medium transition-colors",
              on ? "border-tex-600 bg-tex-600 text-white dark:text-zinc-50" : "border-zinc-300 bg-white text-zinc-600 hover:bg-zinc-50",
            )}
          >
            {weekdayName(i)}
          </button>
        )
      })}
    </div>
  )
}
