import { useMemo, useState, type ReactNode } from "react"
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react"
import { cn } from "../../lib/utils"
import { Skeleton } from "./primitives"
import { EmptyState } from "./layout"

export interface Column<T> {
  key: string
  header: ReactNode
  /** Cell renderer; defaults to row[key]. */
  cell?: (row: T) => ReactNode
  /** Value used for sorting (string/number). Omit to make the column unsortable. */
  sortValue?: (row: T) => string | number | null | undefined
  align?: "left" | "right" | "center"
  className?: string
  /** Hide below the given breakpoint to keep tables readable on phones. */
  hideBelow?: "sm" | "md" | "lg"
}

export interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[] | undefined
  rowKey: (row: T) => string
  loading?: boolean
  onRowClick?: (row: T) => void
  empty?: ReactNode
  caption?: string
  dense?: boolean
  initialSort?: { key: string; dir: "asc" | "desc" }
  footer?: ReactNode
  rowClassName?: (row: T) => string | undefined
}

/** Responsive visibility classes of `Column.hideBelow` (reuse them in footer rows). */
export const HIDE = { sm: "hidden sm:table-cell", md: "hidden md:table-cell", lg: "hidden lg:table-cell" }

/** Accessible, sortable table. Rows with onRowClick are keyboard reachable
 * (Enter/Space open them) and announce as buttons. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  onRowClick,
  empty,
  caption,
  dense,
  initialSort,
  footer,
  rowClassName,
}: DataTableProps<T>) {
  const [sort, setSort] = useState(initialSort)
  const sorted = useMemo(() => {
    if (!rows || !sort) return rows
    const col = columns.find((c) => c.key === sort.key)
    if (!col?.sortValue) return rows
    const get = col.sortValue
    return [...rows].sort((a, b) => {
      const x = get(a)
      const y = get(b)
      if (x === y) return 0
      if (x === null || x === undefined) return 1
      if (y === null || y === undefined) return -1
      const r = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true })
      return sort.dir === "asc" ? r : -r
    })
  }, [rows, sort, columns])

  const pad = dense ? "px-3 py-1.5" : "px-4 py-2.5"
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-separate border-spacing-0 text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key
              const ariaSort = active ? (sort!.dir === "asc" ? "ascending" : "descending") : c.sortValue ? "none" : undefined
              return (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={ariaSort}
                  className={cn(
                    "sticky top-0 z-[1] border-b border-zinc-200 bg-zinc-50 text-xs font-semibold tracking-wide text-zinc-600 uppercase",
                    pad,
                    c.align === "right" ? "text-right" : c.align === "center" ? "text-center" : "text-left",
                    c.hideBelow && HIDE[c.hideBelow],
                    c.className,
                  )}
                >
                  {c.sortValue ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 uppercase hover:text-zinc-900"
                      onClick={() =>
                        setSort(active && sort!.dir === "asc" ? { key: c.key, dir: "desc" } : { key: c.key, dir: "asc" })
                      }
                    >
                      {c.header}
                      {active ? (
                        sort!.dir === "asc" ? (
                          <ArrowUp className="size-3" aria-hidden />
                        ) : (
                          <ArrowDown className="size-3" aria-hidden />
                        )
                      ) : (
                        <ArrowUpDown className="size-3 opacity-40" aria-hidden />
                      )}
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {loading && !rows
            ? Array.from({ length: 5 }).map((_, i) => (
                <tr key={i}>
                  {columns.map((c) => (
                    <td key={c.key} className={cn("border-b border-zinc-100", pad, c.hideBelow && HIDE[c.hideBelow])}>
                      <Skeleton className="h-4 w-full max-w-40" />
                    </td>
                  ))}
                </tr>
              ))
            : sorted?.map((row) => (
                <tr
                  key={rowKey(row)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  onKeyDown={
                    onRowClick
                      ? (e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault()
                            onRowClick(row)
                          }
                        }
                      : undefined
                  }
                  tabIndex={onRowClick ? 0 : undefined}
                  className={cn(
                    "group",
                    onRowClick && "cursor-pointer hover:bg-tex-50/60 focus-visible:bg-tex-50",
                    rowClassName?.(row),
                  )}
                >
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      className={cn(
                        "border-b border-zinc-100 text-zinc-800",
                        pad,
                        c.align === "right" ? "text-right tabular-nums" : c.align === "center" ? "text-center" : "text-left",
                        c.hideBelow && HIDE[c.hideBelow],
                        c.className,
                      )}
                    >
                      {c.cell ? c.cell(row) : String((row as Record<string, unknown>)[c.key] ?? "—")}
                    </td>
                  ))}
                </tr>
              ))}
        </tbody>
        {footer && <tfoot>{footer}</tfoot>}
      </table>
      {!loading && sorted && sorted.length === 0 && (empty ?? <EmptyState title="—" />)}
    </div>
  )
}
