import { type ReactNode } from "react"
import { ArrowDown, ArrowUp, Copy, Plus, Trash2 } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { useTexT } from "../../../i18n"
import { date as fmtDate } from "../../../lib/format"
import { Button, DecimalInput, IconButton, Input, Select, type Option } from "../../../ui"
import type { FieldKind } from "../lib/util"
import { intVal, newKey, splitCsv } from "../lib/util"
import type { Row } from "../lib/types"
import { CsvPicker, WeekdayPicker } from "./pickers"

export interface ColSpec {
  key: string
  label: string
  kind: FieldKind
  options?: Option[]
  /** Blank option label for optional selects (e.g. "Every period"). */
  placeholder?: string
  className?: string
  decimals?: number
  allowNegative?: boolean
  required?: boolean
  /** Column explanation (shown as the header tooltip and on phones under the label). */
  help?: string
  /** Not applicable for this row (rendered as a dash, value kept). */
  disabled?: (row: Row) => boolean
  suffix?: (row: Row) => ReactNode
  min?: number
  max?: number
  /** Text for the "blank = all" state of csv pickers. */
  allLabel?: string
  /** int columns: 0 means "default" — shown as this placeholder text. */
  zeroLabel?: string
}

/**
 * Editable child table (contract version tables, policy rules). Desktop: a dense
 * table; phones (< md): every row becomes a labelled card. Read-only renders text.
 */
export function RowsEditor({
  caption,
  columns,
  rows,
  onChange,
  readOnly,
  newRow,
  addLabel,
  emptyText,
  describe,
  rowTone,
}: {
  caption: string
  columns: ColSpec[]
  rows: Row[]
  onChange: (rows: Row[]) => void
  readOnly?: boolean
  newRow: () => Omit<Row, "_key">
  addLabel: string
  emptyText?: ReactNode
  /** Plain-language reading of the row, shown under it. */
  describe?: (row: Row) => ReactNode
  rowTone?: (row: Row) => "danger" | "warning" | undefined
}) {
  const { t } = useTexT()
  const set = (i: number, key: string, v: string | number) => onChange(rows.map((r, j) => (j === i ? { ...r, [key]: v } : r)))
  const remove = (i: number) => onChange(rows.filter((_, j) => j !== i))
  const dup = (i: number) => onChange([...rows.slice(0, i + 1), { ...rows[i], _key: newKey() }, ...rows.slice(i + 1)])
  const move = (i: number, d: -1 | 1) => {
    const j = i + d
    if (j < 0 || j >= rows.length) return
    const next = [...rows]
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }
  const add = () => onChange([...rows, { ...(newRow() as Row), _key: newKey() }])

  return (
    <div className="space-y-3">
      <div className={cn("overflow-x-auto md:rounded-lg md:border md:border-zinc-200", rows.length === 0 && "hidden")}>
        <table className="block w-full border-separate border-spacing-0 text-sm md:table">
          <caption className="sr-only">{caption}</caption>
          <thead className="hidden md:table-header-group">
            <tr>
              {columns.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  title={c.help}
                  className={cn(
                    "border-b border-zinc-200 bg-zinc-50 px-2 py-2 text-left text-xs font-semibold text-zinc-600 first:pl-3",
                    c.className,
                  )}
                >
                  <span className={cn(c.help && "cursor-help underline decoration-zinc-300 decoration-dotted underline-offset-2")}>{c.label}</span>
                  {c.required && !readOnly && (
                    <span className="ml-0.5 text-rose-600" aria-hidden>
                      *
                    </span>
                  )}
                </th>
              ))}
              {!readOnly && (
                <th scope="col" className="w-24 border-b border-zinc-200 bg-zinc-50 px-2 py-2 text-right text-xs font-semibold text-zinc-600">
                  <span className="sr-only">{t("rates.common.row_actions")}</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody className="block space-y-3 md:table-row-group md:space-y-0">
            {rows.map((row, i) => {
              const tone = rowTone?.(row)
              const text = describe?.(row)
              return (
                <RowFragment key={row._key}>
                  <tr
                    className={cn(
                      "block rounded-lg border border-zinc-200 p-3 md:table-row md:rounded-none md:border-0 md:p-0",
                      tone === "danger" && "border-rose-300 bg-rose-50/40 md:bg-rose-50/40",
                      tone === "warning" && "border-amber-300 bg-amber-50/40 md:bg-amber-50/40",
                    )}
                  >
                    {columns.map((c) => {
                      const na = c.disabled?.(row)
                      return (
                        <td
                          key={c.key}
                          className={cn(
                            "block py-1 align-top md:table-cell md:px-2 md:py-1.5 md:first:pl-3",
                            !text && "md:border-b md:border-zinc-100",
                            c.className,
                          )}
                        >
                          <span className="mb-0.5 block text-xs font-medium text-zinc-600 md:hidden">
                            {c.label}
                            {c.required && !readOnly && (
                              <span className="ml-0.5 text-rose-600" aria-hidden>
                                *
                              </span>
                            )}
                          </span>
                          {na ? (
                            <span className="inline-flex h-8 items-center text-zinc-400" aria-label={t("rates.common.not_applicable")}>
                              —
                            </span>
                          ) : (
                            <CellControl col={c} row={row} index={i} readOnly={readOnly} onValue={(v) => set(i, c.key, v)} />
                          )}
                        </td>
                      )
                    })}
                    {text && <td className="block pt-1 text-xs text-zinc-600 md:hidden">{text}</td>}
                    {!readOnly && (
                      <td className={cn("block pt-2 md:table-cell md:px-2 md:py-1.5 md:text-right", !text && "md:border-b md:border-zinc-100")}>
                        <div className="flex justify-end gap-0.5">
                          <span className="hidden gap-0.5 md:inline-flex">
                            <IconButton size="sm" label={t("rates.common.move_up", { n: i + 1 })} icon={<ArrowUp className="size-3.5" />} onClick={() => move(i, -1)} disabled={i === 0} />
                            <IconButton size="sm" label={t("rates.common.move_down", { n: i + 1 })} icon={<ArrowDown className="size-3.5" />} onClick={() => move(i, 1)} disabled={i === rows.length - 1} />
                          </span>
                          <IconButton size="sm" label={t("rates.common.duplicate_row", { n: i + 1 })} icon={<Copy className="size-3.5" />} onClick={() => dup(i)} />
                          <IconButton size="sm" label={t("rates.common.delete_row", { n: i + 1 })} icon={<Trash2 className="size-3.5" />} onClick={() => remove(i)} className="hover:text-rose-700!" />
                        </div>
                      </td>
                    )}
                  </tr>
                  {text && (
                    <tr className="hidden md:table-row">
                      <td colSpan={columns.length + (readOnly ? 0 : 1)} className="border-b border-zinc-100 px-3 pb-2 text-xs text-zinc-600">
                        {text}
                      </td>
                    </tr>
                  )}
                </RowFragment>
              )
            })}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && <p className="rounded-lg border border-dashed border-zinc-300 px-4 py-6 text-center text-sm text-zinc-500">{emptyText ?? t("rates.common.no_rows")}</p>}
      {!readOnly && (
        <Button variant="secondary" size="sm" icon={<Plus className="size-4" aria-hidden />} onClick={add}>
          {addLabel}
        </Button>
      )}
    </div>
  )
}

function RowFragment({ children }: { children: ReactNode }) {
  return <>{children}</>
}

function CellControl({
  col,
  row,
  index,
  readOnly,
  onValue,
}: {
  col: ColSpec
  row: Row
  index: number
  readOnly?: boolean
  onValue: (v: string | number) => void
}) {
  const v = row[col.key]
  const aria = `${col.label} ${index + 1}`
  if (readOnly) return <ReadValue col={col} row={row} value={v} />
  switch (col.kind) {
    case "int":
      return (
        <Input
          type="number"
          inputMode="numeric"
          min={col.min ?? 0}
          max={col.max}
          step={1}
          aria-label={aria}
          value={v === null || v === undefined || (col.zeroLabel && !v) ? "" : String(v)}
          placeholder={col.zeroLabel}
          onChange={(e) => onValue(e.target.value === "" ? 0 : intVal(e.target.value))}
          className="h-8! min-w-16 px-2! text-right tabular-nums"
        />
      )
    case "decimal":
      return (
        <DecimalInput
          aria-label={aria}
          value={v === null || v === undefined ? "" : String(v)}
          onValueChange={onValue}
          decimals={col.decimals ?? 6}
          allowNegative={col.allowNegative}
          suffix={col.suffix?.(row)}
          className="h-8! min-w-20 px-2!"
        />
      )
    case "check":
      return (
        <span className="inline-flex h-8 items-center">
          <input
            type="checkbox"
            aria-label={aria}
            checked={Boolean(v)}
            onChange={(e) => onValue(e.target.checked ? 1 : 0)}
            className="size-4 rounded border-zinc-300 accent-tex-600"
          />
        </span>
      )
    case "select":
      return (
        <Select
          aria-label={aria}
          value={v === null || v === undefined ? "" : String(v)}
          onChange={(e) => onValue(e.target.value)}
          options={withCurrent(col.options ?? [], String(v ?? ""))}
          placeholder={col.required ? undefined : (col.placeholder ?? "—")}
          className="h-8! min-w-28 pl-2! text-sm"
        />
      )
    case "date":
      return (
        <Input
          type="date"
          aria-label={aria}
          value={String(v ?? "")}
          onChange={(e) => onValue(e.target.value)}
          className="h-8! min-w-34 px-2!"
        />
      )
    case "csv":
      return (
        <div className="min-w-32">
          <CsvPicker compact value={String(v ?? "")} onChange={onValue} options={col.options ?? []} label={aria} allLabel={col.allLabel} />
        </div>
      )
    case "weekdays":
      return <WeekdayPicker value={String(v ?? "")} onChange={onValue} label={aria} />
    default:
      return (
        <Input
          aria-label={aria}
          value={String(v ?? "")}
          placeholder={col.placeholder}
          onChange={(e) => onValue(e.target.value)}
          className="h-8! min-w-24 px-2!"
          {...(col.required && !v ? { "aria-invalid": true } : {})}
        />
      )
  }
}

/** Keep an unknown stored value selectable (e.g. a room type later disabled). */
function withCurrent(options: Option[], current: string): Option[] {
  if (!current || options.some((o) => o.value === current)) return options
  return [...options, { value: current, label: current }]
}

function ReadValue({ col, row, value }: { col: ColSpec; row: Row; value: unknown }) {
  const { t } = useTexT()
  if (col.kind === "check") return <span>{value ? t("core.label.yes") : t("core.label.no")}</span>
  if (value === null || value === undefined || value === "") {
    if (col.kind === "csv") return <span className="text-zinc-500">{col.allLabel ?? t("rates.common.all")}</span>
    return <span className="text-zinc-400">{col.kind === "select" && col.placeholder ? col.placeholder : "—"}</span>
  }
  if (col.kind === "select") return <span>{col.options?.find((o) => o.value === value)?.label ?? String(value)}</span>
  if (col.kind === "date") return <span className="whitespace-nowrap">{fmtDate(String(value))}</span>
  if (col.kind === "csv")
    return (
      <span>
        {splitCsv(value)
          .map((x) => col.options?.find((o) => o.value === x)?.label ?? x)
          .join(", ")}
      </span>
    )
  if (col.kind === "int" && !value && col.zeroLabel) return <span className="text-zinc-500">{col.zeroLabel}</span>
  if (col.kind === "decimal" || col.kind === "int")
    return (
      <span className="tabular-nums">
        {String(value)}
        {col.suffix ? <span className="ml-1 text-xs text-zinc-500">{col.suffix(row)}</span> : null}
      </span>
    )
  return <span>{String(value)}</span>
}
