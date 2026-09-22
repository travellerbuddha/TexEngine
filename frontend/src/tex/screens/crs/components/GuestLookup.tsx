import { forwardRef, useEffect, useId, useState } from "react"
import { Search, Star } from "lucide-react"
import { date } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Input, Spinner } from "../../../ui"
import { cn } from "../../../../lib/utils"
import { findGuests } from "../lib/api"
import { asApiError } from "../lib/useBookingFlow"
import type { GuestRow } from "../lib/types"
import type { TexApiError } from "../../../lib/api"

/** Phone / name / email lookup over crm.guests (WAI-ARIA combobox: ↓/↑ move, Enter picks, Esc closes). */
export const GuestLookup = forwardRef<
  HTMLInputElement,
  {
    onPick: (g: GuestRow) => void
    label: string
    placeholder?: string
    hint?: string
    id?: string
    /** Called with the raw text when the agent presses Enter without a match. */
    onQuery?: (q: string) => void
  }
>(function GuestLookup({ onPick, label, placeholder, hint, id, onQuery }, ref) {
  const { t } = useTexT()
  const autoId = useId()
  const inputId = id ?? `${autoId}-q`
  const listId = `${autoId}-list`
  const [q, setQ] = useState("")
  const [rows, setRows] = useState<GuestRow[]>()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<TexApiError>()
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)

  useEffect(() => {
    const term = q.trim()
    if (term.length < 2) {
      setRows(undefined)
      setError(undefined)
      return
    }
    const ctl = new AbortController()
    const timer = window.setTimeout(() => {
      setLoading(true)
      findGuests(term, ctl.signal)
        .then((r) => {
          setRows(r.rows)
          setError(undefined)
          setActive(0)
          setOpen(true)
        })
        .catch((e) => {
          if ((e as Error).name !== "AbortError") setError(asApiError(e))
        })
        .finally(() => setLoading(false))
    }, 250)
    return () => {
      window.clearTimeout(timer)
      ctl.abort()
    }
  }, [q])

  const pick = (g: GuestRow) => {
    onPick(g)
    setOpen(false)
    setQ("")
    setRows(undefined)
  }
  const list = open && rows ? rows : []
  return (
    <div className="relative">
      <label htmlFor={inputId} className="block text-sm font-medium text-zinc-800">
        {label}
      </label>
      <div className="relative mt-1.5">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-zinc-400" aria-hidden />
        <Input
          ref={ref}
          id={inputId}
          role="combobox"
          aria-expanded={list.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={list[active] ? `${listId}-${list[active].name}` : undefined}
          aria-describedby={hint ? `${inputId}-hint` : undefined}
          autoComplete="off"
          value={q}
          placeholder={placeholder}
          className="pl-8"
          onChange={(e) => {
            setQ(e.target.value)
            setOpen(true)
          }}
          onFocus={() => rows && setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown" && list.length) {
              e.preventDefault()
              setActive((a) => Math.min(a + 1, list.length - 1))
            } else if (e.key === "ArrowUp" && list.length) {
              e.preventDefault()
              setActive((a) => Math.max(a - 1, 0))
            } else if (e.key === "Enter") {
              e.preventDefault()
              if (list[active]) pick(list[active])
              else if (q.trim()) onQuery?.(q.trim())
            } else if (e.key === "Escape" && open) {
              e.stopPropagation()
              setOpen(false)
            }
          }}
        />
        {loading && <Spinner className="absolute top-1/2 right-2.5 -translate-y-1/2" label={t("core.label.loading")} />}
      </div>
      {hint && (
        <p id={`${inputId}-hint`} className="mt-1 text-xs text-zinc-500">
          {hint}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-1 text-xs text-rose-700">
          {error.isPermission ? t("crs.guest.lookup_denied") : error.message}
        </p>
      )}
      <ul
        id={listId}
        role="listbox"
        aria-label={t("crs.guest.matches")}
        className={cn(
          "absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-lg border border-zinc-200 bg-white p-1 shadow-tex-pop",
          !list.length && "hidden",
        )}
      >
        {list.map((g, i) => (
          <li
            key={g.name}
            id={`${listId}-${g.name}`}
            role="option"
            aria-selected={i === active}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => pick(g)}
            onMouseEnter={() => setActive(i)}
            className={cn("cursor-pointer rounded-md px-2.5 py-1.5 text-sm", i === active ? "bg-tex-50 text-tex-900" : "text-zinc-800")}
          >
            <span className="flex items-center gap-1.5 font-medium">
              {g.full_name}
              {g.vip ? <Star className="size-3.5 fill-amber-600 text-amber-600" aria-label={t("crs.guest.vip")} /> : null}
              {g.blacklisted ? <Badge tone="danger">{t("crs.guest.blacklisted")}</Badge> : null}
            </span>
            <span className="block truncate text-xs text-zinc-500">
              {[g.phone, g.email].filter(Boolean).join(" · ") || "—"}
            </span>
            <span className="block text-xs text-zinc-500">
              {t("crs.guest.stays", { count: g.tex_stays ?? 0 })}
              {g.tex_last_stay ? ` · ${t("crs.guest.last_stay", { date: date(g.tex_last_stay) })}` : ""}
              {g.tex_market ? ` · ${g.tex_market}` : ""}
            </span>
          </li>
        ))}
      </ul>
      {open && rows && rows.length === 0 && q.trim().length >= 2 && !loading && (
        <p className="mt-1 text-xs text-zinc-500" role="status">
          {t("crs.guest.no_match")}
        </p>
      )}
    </div>
  )
})
