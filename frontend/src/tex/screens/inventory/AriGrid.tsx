import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { ArrowDownToLine, ArrowUpFromLine, Ban, CalendarClock, ChevronLeft, ChevronRight, Layers, Lock, PencilLine, Rows3, Tag } from "lucide-react"
import { cn } from "../../../lib/utils"
import { useTexQuery } from "../../lib/api"
import { useProperty, useSession } from "../../lib/session"
import { useConfirmLeave, useUnsavedChanges } from "../../lib/unsaved"
import { addDays, date as fmtDate } from "../../lib/format"
import { useSiteToday } from "../../lib/siteDay"
import { getTexLang, intlLocale, useTexT } from "../../i18n"
import {
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Notice,
  PageHeader,
  Popover,
  Segmented,
  Select,
  Skeleton,
  Toolbar,
  useGridNavigation,
  useGridSelection,
  useToast,
  type GridSelectionApi,
} from "../../ui"
import { decText, isoWeekday, useLookups, versionLabel, weekdayName } from "../rates/lib/util"
import { PublishDialog } from "../rates/contracts/VersionActions"
import { decodeTSV, encodeTSV, copyBlock } from "../rates/workspace/clipboard.ts"
import { BulkDialog, CellDialog, channelScopeLabel, scopeText, windowText, type BulkInitial } from "./Dialogs"
import { GridActions, type RateChangesAnswer } from "./GridActions"
import { InventoryNav } from "./InventoryNav"
import { Legend } from "./Legend"
import { cellKey, parseRateEntry, planRatePaste, rateEditText, type GridTarget, type PendingRate, type RateEdit } from "./rateEdits.ts"
import { CHANNEL_SCOPES, channelArgs, HOTEL_METRICS, METRICS, SCOPE_PREFIX, type Grid, type GridCell, type GridRow, type Metric, type Scope } from "./types"

const PREF = "tex-inv-grid"
/** The daily work view: price, rooms left, open or closed (UX revision 2026-10). The other rows
 * (stay length, arrival/departure, release, booking window) are one click away. */
export const DAILY: Metric[] = ["rate", "avail", "stop"]
const DAY_OPTIONS = [7, 14, 31, 60]

interface Prefs {
  days: number
  scope: Scope
  metrics: Metric[]
}

function loadPrefs(property: string | undefined): Prefs {
  const fallback: Prefs = { days: 14, scope: { contract: "", market: "", channel: "", rate_plan: "" }, metrics: DAILY }
  try {
    const raw = localStorage.getItem(`${PREF}:${property}`)
    if (!raw) return fallback
    const p = JSON.parse(raw) as Partial<Prefs>
    const metrics = (p.metrics ?? []).filter((m) => METRICS.includes(m))
    return { days: [...DAY_OPTIONS, 28].includes(p.days ?? 0) ? p.days! : 14, scope: { ...fallback.scope, ...(p.scope ?? {}) }, metrics: metrics.length ? metrics : DAILY }
  } catch {
    return fallback
  }
}

const sameSet = (a: Metric[], b: Metric[]) => a.length === b.length && a.every((m) => b.includes(m))

interface FlatRow {
  row: GridRow
  metric: Metric
}

interface Editing {
  r: number
  c: number
  text: string
  /** started by typing a character (the caret goes after it), not by Enter / F2 / a double click */
  typed?: boolean
  error?: string
}

/** Rates & availability (R-36; UX revision 2026-10): dates × room types with the price, the rooms
 * left and whether the night is on sale. Select cells (click, Shift+click, drag, a room's or a
 * day's header, Ctrl+A), then type a price or a change (+10 %), paste a block from a spreadsheet,
 * or close / open sale for the selection. Price edits stay unsaved until previewed and saved to
 * the contract's draft; nothing sells at them until the draft is published. Enter or a double
 * click opens a cell's full editor, and the bulk editor stays for every other field. */
export default function AriGrid() {
  const { t } = useTexT()
  const toast = useToast()
  const property = useProperty()
  const { boot, can, property: hotel } = useSession()
  const confirmLeave = useConfirmLeave()
  const lookups = useLookups(property)
  const [prefs, setPrefs] = useState<Prefs>(() => loadPrefs(property))
  // start null = the site's today (G-91): the grid follows the site's midnight until moved
  const today = useSiteToday()
  // deep links (G-64): ?start=YYYY-MM-DD opens that day (Rates & availability › Restrictions);
  // ?bulk=1 opens the bulk editor (the side navigation's Bulk editor)
  const [params, setParams] = useSearchParams()
  const startParam = /^\d{4}-\d{2}-\d{2}$/.test(params.get("start") ?? "") ? params.get("start") : null
  const [picked, setStart] = useState<string | null>(startParam)
  useEffect(() => {
    if (startParam) setStart(startParam)
  }, [startParam])
  const start = picked ?? today
  const [cellEdit, setCellEdit] = useState<{ row: GridRow; cell: GridCell } | null>(null)
  const [bulk, setBulk] = useState<BulkInitial | true | null>(null)
  const [publishDraft, setPublishDraft] = useState<string | null>(null)
  const [rowsOpen, setRowsOpen] = useState(false)
  const rowsBtn = useRef<HTMLButtonElement>(null)

  // the price edits not saved yet (cell → entry), and the states before each change (Undo)
  const [pending, setPending] = useState<Map<string, PendingRate>>(() => new Map())
  const [history, setHistory] = useState<Map<string, PendingRate>[]>([])
  const [preview, setPreview] = useState<RateChangesAnswer | null>(null)
  useUnsavedChanges(() => pending.size > 0)
  const changePending = useCallback((f: (m: Map<string, PendingRate>) => Map<string, PendingRate>) => {
    setPending((cur) => {
      const next = f(cur)
      if (next !== cur) setHistory((h) => [...h.slice(-49), cur])
      return next
    })
  }, [])
  const undo = useCallback(() => {
    setHistory((h) => {
      if (!h.length) return h
      setPending(h[h.length - 1])
      return h.slice(0, -1)
    })
  }, [])
  const dropPending = useCallback(() => {
    setPending(new Map())
    setHistory([])
  }, [])

  useEffect(() => {
    setPrefs(loadPrefs(property))
    dropPending()
  }, [property, dropPending])
  useEffect(() => {
    try {
      localStorage.setItem(`${PREF}:${property}`, JSON.stringify(prefs))
    } catch {
      /* storage blocked */
    }
  }, [prefs, property])

  const { days, scope } = prefs
  const setScope = (k: keyof Scope, v: string) => {
    // the unsaved prices belong to the contract they were typed for
    if (k === "contract" && pending.size) {
      if (!confirmLeave()) return
      dropPending()
    }
    setPrefs((p) => ({ ...p, scope: { ...p.scope, [k]: v } }))
  }
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
  const canRestrict = can("restriction.edit")
  // rates are cost (G-11): the grid hides them from who may not see cost, and they cannot be changed there
  const canRate = can("contract.edit") && Boolean(scope.contract) && Boolean(grid && !grid.rates_hidden)
  const canEditAny = canRestrict || can("inventory.edit") || canRate
  const wantsBulk = params.get("bulk") === "1"
  useEffect(() => {
    if (!wantsBulk || !grid) return
    if (canEditAny) setBulk(true)
    setParams(
      (p) => {
        p.delete("bulk")
        return p
      },
      { replace: true },
    )
  }, [wantsBulk, grid, canEditAny, setParams])

  // ── the rendered rows, the selection and the keyboard ──
  const rowMetrics = useCallback((row: GridRow) => (row.level === "hotel" ? metrics.filter((m) => HOTEL_METRICS.includes(m)) : metrics), [metrics])
  const flat = useMemo<FlatRow[]>(() => (grid ? grid.rows.flatMap((row) => rowMetrics(row).map((metric) => ({ row, metric }))) : []), [grid, rowMetrics])
  const dates = useMemo(() => grid?.dates ?? [], [grid])
  const isEditable = useCallback(() => canEditAny, [canEditAny])
  const sel = useGridSelection({ rows: flat.length, cols: dates.length, isEditable })
  const [editing, setEditing] = useState<Editing | null>(null)
  const rateRoom = (r: number) => (flat[r]?.metric === "rate" && flat[r].row.room_type ? flat[r].row.room_type : null)
  const priceable = (r: number, c: number) => canRate && rateRoom(r) !== null && flat[r].row.cells[c]?.rate !== undefined
  const minorUnits = grid?.minor_units ?? 2
  const nav = useGridNavigation({
    rows: flat.length,
    cols: dates.length,
    selection: sel,
    onEdit: (cell, req) => {
      if (priceable(cell.r, cell.c)) {
        const p = pending.get(cellKey(rateRoom(cell.r)!, dates[cell.c]))
        setEditing({ r: cell.r, c: cell.c, text: req.text ?? (p ? rateEditText(p) : ""), typed: req.text !== undefined })
        return
      }
      if (req.text === undefined && canEditAny && flat[cell.r]) setCellEdit({ row: flat[cell.r].row, cell: flat[cell.r].row.cells[cell.c] })
    },
    onKey: (e, cell) => {
      const mod = e.ctrlKey || e.metaKey
      if (mod && !e.altKey && e.key.toLowerCase() === "z") {
        e.preventDefault()
        undo()
        return true
      }
      if ((e.key === "Delete" || e.key === "Backspace") && !mod) {
        // clears the unsaved edits of the selected price cells (never a saved price)
        const keys = sel.selected.filter(({ r, c }) => priceable(r, c)).map(({ r, c }) => cellKey(rateRoom(r)!, dates[c]))
        const all = keys.length ? keys : priceable(cell.r, cell.c) ? [cellKey(rateRoom(cell.r)!, dates[cell.c])] : []
        if (all.some((k) => pending.has(k))) {
          e.preventDefault()
          changePending((m) => {
            const next = new Map(m)
            for (const k of all) next.delete(k)
            return next
          })
          return true
        }
      }
    },
  })

  // the selection as cells (room type or the hotel row × night)
  const targets = useMemo<GridTarget[]>(() => {
    const seen = new Set<string>()
    const out: GridTarget[] = []
    for (const { r, c } of sel.selected) {
      const f = flat[r]
      const date = dates[c]
      if (!f || !date) continue
      const k = `${f.row.room_type ?? "*"}|${date}`
      if (seen.has(k)) continue
      seen.add(k)
      out.push({ room: f.row.room_type, date })
    }
    return out
  }, [sel.selected, flat, dates])
  // a single click is a selection of one cell: the bar shows it only once more than that is chosen
  // or a key started it, so a look at a cell does not open anything
  const [touched, setTouched] = useState(false)
  const shownTargets = touched || sel.multiple ? targets : []
  const roomName = useCallback((rt: string | null) => (rt === null ? t("inventory.hotel_level") : (grid?.rows.find((r) => r.room_type === rt)?.name ?? rt)), [grid, t])
  const cellAt = useCallback(
    (room: string | null, date: string) => {
      const row = grid?.rows.find((r) => r.room_type === room)
      return row?.cells.find((c) => c.date === date)
    },
    [grid],
  )

  // ── entries: typed in a cell, applied to the selection, pasted ──
  const setEntries = (cells: { room: string; date: string }[], edit: RateEdit | null) =>
    changePending((m) => {
      const next = new Map(m)
      for (const x of cells) {
        if (edit) next.set(cellKey(x.room, x.date), { room: x.room, date: x.date, ...edit })
        else next.delete(cellKey(x.room, x.date))
      }
      return next
    })
  const commitEditing = (move: 1 | -1 | 0, refocus = true) => {
    if (!editing) return
    const room = rateRoom(editing.r)
    const date = dates[editing.c]
    if (!room || !date) return setEditing(null)
    const r = parseRateEntry(editing.text, minorUnits)
    if (!r.ok) return setEditing({ ...editing, error: t(`inventory.entry.err.${r.code}`) })
    setEntries([{ room, date }], "edit" in r ? r.edit : null)
    setEditing(null)
    if (!refocus) return
    const c = Math.min(Math.max(editing.c + move, 0), dates.length - 1)
    nav.focusCell(editing.r, c)
  }
  const priceSelection = (edit: RateEdit) => {
    const cells = targets.filter((x): x is { room: string; date: string } => x.room !== null && cellAt(x.room, x.date)?.rate !== undefined)
    setEntries(cells, edit)
    toast.info(t("inventory.rates.entered", { count: cells.length }))
  }

  // copy / paste: the price rows only (a block pastes rooms down, nights across)
  const gridEl = useRef<HTMLTableElement | null>(null)
  const rateRooms = useMemo(() => flat.filter((f) => f.metric === "rate" && f.row.room_type).map((f) => f.row.room_type!), [flat])
  const copyText = (r: number, c: number) => {
    const room = rateRoom(r)
    if (!room) return ""
    const p = pending.get(cellKey(room, dates[c]))
    if (p) return rateEditText(p)
    const cell = flat[r].row.cells[c]
    return cell.draft_rate ?? cell.rate ?? ""
  }
  const clip = useRef({ copy: (_e: ClipboardEvent) => undefined as void, paste: (_e: ClipboardEvent) => undefined as void })
  clip.current = {
    copy: (e) => {
      const block = copyBlock(sel.state.ranges, copyText, (r) => rateRoom(r) !== null)
      if (!block.length || !e.clipboardData || !block.some((row) => row.some(Boolean))) return
      e.clipboardData.setData("text/plain", encodeTSV(block))
      e.preventDefault()
      toast.info(t("inventory.rates.copied", { count: block.reduce((n, row) => n + row.length, 0) }))
    },
    paste: (e) => {
      if (!canRate || !e.clipboardData) return
      const at = sel.state.active
      const room = rateRoom(at.r)
      if (!room) return void toast.error(t("inventory.rates.paste_on_price"))
      e.preventDefault()
      const block = decodeTSV(e.clipboardData.getData("text/plain"))
      if (!block.length) return
      const res = planRatePaste(block, rateRooms, dates, { row: rateRooms.indexOf(room), col: at.c }, minorUnits)
      if (!res.ok) {
        const f = res.failures[0]
        return void toast.error(
          f.code === "OUTSIDE" ? t("inventory.rates.paste_outside", { rows: block.length, cols: Math.max(...block.map((x) => x.length)) }) : t("inventory.rates.paste_bad", { text: f.text, error: t(`inventory.entry.err.${f.code}`) }),
        )
      }
      const usable = res.edits.filter((x) => cellAt(x.room, x.date)?.rate !== undefined)
      changePending((m) => {
        const next = new Map(m)
        for (const x of res.clears) next.delete(cellKey(x.room, x.date))
        for (const x of usable) next.set(cellKey(x.room, x.date), x)
        return next
      })
      toast.info(t("inventory.rates.pasted", { count: usable.length }))
    },
  }
  useEffect(() => {
    const mine = () => {
      const a = document.activeElement
      return a instanceof HTMLElement && a.getAttribute("role") === "gridcell" && Boolean(gridEl.current?.contains(a))
    }
    const copy = (e: ClipboardEvent) => mine() && clip.current.copy(e)
    const paste = (e: ClipboardEvent) => mine() && clip.current.paste(e)
    document.addEventListener("copy", copy)
    document.addEventListener("paste", paste)
    return () => {
      document.removeEventListener("copy", copy)
      document.removeEventListener("paste", paste)
    }
  }, [])

  const newPrice = useMemo(() => {
    const out = new Map<string, string>()
    for (const c of preview?.cells ?? []) for (let d = c.start; d <= c.end; d = addDays(d, 1)) out.set(cellKey(c.room_type, d), c.new)
    return out
  }, [preview])

  // the draft's unpublished prices in view
  const draftCells = grid?.draft ? grid.rows.reduce((n, r) => n + r.cells.filter((c) => c.draft_rate && c.draft_rate !== c.rate).length, 0) : 0
  const bulkFromSelection = (): BulkInitial => {
    const ds = targets.map((x) => x.date).sort()
    const rooms = [...new Set(targets.map((x) => x.room).filter((r): r is string => r !== null))]
    return { from: ds[0], to: ds[ds.length - 1], rooms, hotelLevel: rooms.length === 0 }
  }

  const view = sameSet(prefs.metrics, DAILY) ? "daily" : sameSet(prefs.metrics, METRICS) ? "all" : "custom"
  return (
    <>
      <PageHeader
        title={t("core.nav.inventory")}
        subtitle={t("inventory.subtitle")}
        actions={
          canEditAny &&
          grid && (
            <Button variant="secondary" icon={<Layers className="size-4" aria-hidden />} onClick={() => setBulk(true)}>
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
          options={DAY_OPTIONS.map((d) => ({ value: String(d), label: t("inventory.n_days", { count: d }) }))}
        />
        <div className="flex items-end gap-1">
          <Segmented<string>
            label={t("inventory.view.label")}
            value={view}
            onChange={(v) => v !== "custom" && setPrefs((p) => ({ ...p, metrics: v === "daily" ? DAILY : METRICS }))}
            options={[
              { value: "daily", label: t("inventory.view.daily") },
              { value: "all", label: t("inventory.view.all") },
              ...(view === "custom" ? [{ value: "custom", label: t("inventory.view.custom") }] : []),
            ]}
          />
          <Button ref={rowsBtn} variant="ghost" size="md" icon={<Rows3 className="size-4" aria-hidden />} aria-expanded={rowsOpen} onClick={() => setRowsOpen((o) => !o)}>
            {t("inventory.show_rows")}
          </Button>
          <Popover open={rowsOpen} onClose={() => setRowsOpen(false)} anchorRef={rowsBtn} label={t("inventory.show_rows")} width="sm">
            <fieldset className="space-y-1.5">
              <legend className="sr-only">{t("inventory.show_rows")}</legend>
              {METRICS.map((m) => (
                <Checkbox
                  key={m}
                  label={t(`inventory.metric.${m}`)}
                  checked={prefs.metrics.includes(m)}
                  disabled={m === "rate" && !scope.contract}
                  onChange={(e) => setPrefs((p) => ({ ...p, metrics: e.target.checked ? METRICS.filter((x) => x === m || p.metrics.includes(x)) : p.metrics.filter((x) => x !== m) }))}
                />
              ))}
            </fieldset>
          </Popover>
        </div>
      </Toolbar>
      <Toolbar>
        <Field label={t("inventory.scope.price_source")} className="w-full sm:w-64">
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

      {/* what this screen works on, in words: the hotel, where the prices come from and what a
          restriction set here applies to (never only by the selects' values) */}
      <dl className="mb-3 grid gap-x-6 gap-y-1 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs sm:grid-cols-[auto_1fr]">
        <dt className="font-semibold text-zinc-600">{t("core.shell.hotel")}</dt>
        <dd className="font-medium text-zinc-900">{hotel?.property_name}</dd>
        <dt className="font-semibold text-zinc-600">{t("inventory.scope.prices")}</dt>
        <dd className="text-zinc-800">
          {contract && grid?.contract ? (
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span>{t("inventory.scope.prices_from", { c: contract.contract_code, m: contract.market, ccy: grid.currency ?? contract.contract_currency, basis: t(`inventory.rates.basis.${grid.basis ?? contract.pricing_basis}`) })}</span>
              {grid.version ? <Badge tone="success">{t("inventory.scope.on_sale", { v: versionLabel(grid.version) })}</Badge> : <Badge tone="neutral">{t("inventory.scope.none_on_sale")}</Badge>}
              {grid.draft && <Badge tone="warning">{t("inventory.scope.draft", { v: versionLabel(grid.draft) })}</Badge>}
            </span>
          ) : (
            <span className="text-zinc-600">{t("inventory.choose_contract_hint")}</span>
          )}
        </dd>
        <dt className="font-semibold text-zinc-600">{t("inventory.scope.restrictions_label")}</dt>
        <dd className="text-zinc-800">
          {scopeLabel} <span className="text-zinc-500">· {t("inventory.scope.restrictions_now")}</span>
        </dd>
      </dl>

      {grid?.draft && draftCells > 0 && (
        <div className="mb-3">
          <Notice tone="warning">
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span>{t("inventory.draft_cells", { count: draftCells, v: versionLabel(grid.draft), live: grid.version ? versionLabel(grid.version) : "—" })}</span>
              <Link to={`/tex/rates/contracts/${encodeURIComponent(grid.contract ?? "")}/versions/${encodeURIComponent(grid.draft)}`} className="font-medium underline">
                {t("inventory.result.open_draft")}
              </Link>
              {can("contract.publish") && (
                <Button size="sm" variant="secondary" onClick={() => setPublishDraft(grid.draft)}>
                  {t("rates.version.publish")}
                </Button>
              )}
            </span>
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
        ) : grid.rows.every((r) => r.level === "hotel") ? (
          <EmptyState title={t("inventory.no_rooms")} />
        ) : (
          <GridTable
            grid={grid}
            flat={flat}
            today={today}
            loading={q.loading}
            editable={canEditAny}
            sel={sel}
            cellProps={nav.cellProps}
            gridRef={(el) => {
              nav.gridRef(el)
              gridEl.current = el as HTMLTableElement | null
            }}
            showSelection={touched || sel.multiple}
            pending={pending}
            newPrice={newPrice}
            editing={editing}
            onEditingText={(text) => setEditing((e) => (e ? { ...e, text, error: undefined } : e))}
            onTouched={() => setTouched(true)}
            onEditingKey={(e) => {
              if (e.key === "Enter" || e.key === "Tab") {
                e.preventDefault()
                commitEditing(e.shiftKey ? -1 : 1)
              } else if (e.key === "Escape") {
                e.preventDefault()
                const at = editing
                setEditing(null)
                if (at) nav.focusCell(at.r, at.c)
              }
            }}
            onEditingBlur={() => editing && !editing.error && commitEditing(0, false)}
          />
        )}
      </Card>
      {editing?.error && (
        <p role="alert" className="mt-2 text-sm font-medium text-rose-700">
          {t("inventory.entry.invalid", { text: editing.text })}: {editing.error}
        </p>
      )}
      <Legend />
      {grid && (
        <GridActions
          grid={grid}
          scope={scope}
          scopeLabel={scopeLabel}
          contractCode={contract?.contract_code}
          targets={shownTargets}
          roomName={roomName}
          cellAt={cellAt}
          canRate={canRate}
          canRestrict={canRestrict}
          canPublish={can("contract.publish")}
          minorUnits={minorUnits}
          pending={[...pending.values()]}
          canUndo={history.length > 0}
          onUndo={undo}
          onDiscardPending={dropPending}
          onPriceEntry={priceSelection}
          onPreview={setPreview}
          onSaved={() => {
            dropPending()
            q.reload()
          }}
          onPublish={setPublishDraft}
          onRestrictionsApplied={q.reload}
          onMore={() => setBulk(bulkFromSelection())}
          onDetails={
            shownTargets.length === 1 && canEditAny
              ? () => {
                  const x = shownTargets[0]
                  const row = grid.rows.find((r) => r.room_type === x.room)
                  const cell = row?.cells.find((c) => c.date === x.date)
                  if (row && cell) setCellEdit({ row, cell })
                }
              : undefined
          }
          onClearSelection={() => {
            sel.clear()
            setTouched(false)
          }}
        />
      )}
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
          initial={bulk === true ? undefined : bulk}
          onClose={() => setBulk(null)}
          onApplied={q.reload}
          onPublish={(d) => {
            setBulk(null)
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

function GridTable({
  grid,
  flat,
  today,
  loading,
  editable,
  sel,
  cellProps,
  gridRef,
  showSelection,
  pending,
  newPrice,
  editing,
  onEditingText,
  onEditingKey,
  onEditingBlur,
  onTouched,
}: {
  grid: Grid
  flat: FlatRow[]
  today: string
  loading: boolean
  editable: boolean
  sel: GridSelectionApi
  cellProps: ReturnType<typeof useGridNavigation>["cellProps"]
  gridRef: (el: HTMLElement | null) => void
  /** draw the selection (not before the user acted on the grid: the first cell is selected from the start) */
  showSelection: boolean
  pending: Map<string, PendingRate>
  newPrice: Map<string, string>
  editing: Editing | null
  onEditingText: (text: string) => void
  onEditingKey: (e: KeyboardEvent<HTMLInputElement>) => void
  onEditingBlur: () => void
  /** the user acted on the grid (a click, a key): the action bar shows the selection from then on */
  onTouched: () => void
}) {
  const { t } = useTexT()
  // drag to select: the button held down over cells extends the range from where it started
  const dragging = useRef(false)
  useEffect(() => {
    const up = () => {
      dragging.current = false
    }
    window.addEventListener("mouseup", up)
    return () => window.removeEventListener("mouseup", up)
  }, [])
  const rowsOf = (row: GridRow) => flat.map((f, i) => (f.row === row ? i : -1)).filter((i) => i >= 0)
  const selectRoom = (row: GridRow, add: boolean) => {
    const rs = rowsOf(row)
    rs.forEach((r, i) => sel.selectRow(r, { add: add || i > 0 }))
  }

  const ccy = grid.currency ?? ""
  return (
    <div className={cn("max-h-[70vh] overflow-auto", loading && "opacity-60")} aria-busy={loading || undefined} onMouseDownCapture={onTouched} onKeyDownCapture={onTouched}>
      <table
        ref={gridRef}
        role="grid"
        aria-multiselectable={editable || undefined}
        aria-rowcount={flat.length + 1}
        aria-colcount={grid.dates.length + 1}
        aria-readonly={!editable || undefined}
        className="min-w-full border-separate border-spacing-0 text-xs select-none"
      >
        <caption className="sr-only">{t("inventory.caption", { from: fmtDate(grid.dates[0]), to: fmtDate(grid.dates[grid.dates.length - 1]) })}</caption>
        <thead>
          <tr role="row">
            <th role="columnheader" scope="col" className="sticky top-0 left-0 z-[4] w-28 min-w-28 border-r border-b border-zinc-200 bg-zinc-50 px-2 py-2 text-left font-semibold text-zinc-600 sm:w-44 sm:min-w-44">
              {t("inventory.room_date")}
            </th>
            {grid.dates.map((d, ci) => {
              const wd = isoWeekday(d)
              const weekend = wd >= 5
              return (
                <th
                  key={d}
                  role="columnheader"
                  scope="col"
                  className={cn(
                    "sticky top-0 z-[2] min-w-16 border-b border-zinc-200 p-0 text-center font-medium",
                    weekend ? "bg-zinc-100 text-zinc-800" : "bg-zinc-50 text-zinc-700",
                    d === today && "shadow-[inset_0_-2px_0_var(--color-tex-600)]",
                  )}
                >
                  {/* a day's header selects that day for every room (Shift / Ctrl add to the selection) */}
                  <button
                    type="button"
                    tabIndex={-1}
                    disabled={!editable}
                    onClick={(e) => sel.selectCol(ci, { add: e.metaKey || e.ctrlKey, extend: e.shiftKey })}
                    aria-label={t("inventory.select_day", { day: fmtDate(d) })}
                    className="block w-full px-1 py-1.5 hover:bg-tex-50 disabled:cursor-default disabled:hover:bg-transparent"
                  >
                    <span className="block text-[10px] tracking-wide text-zinc-500 uppercase">{weekdayName(wd)}</span>
                    <span className="block text-sm font-semibold tabular-nums">{d.slice(8, 10)}</span>
                    <span className="block text-[10px] text-zinc-500">{fmtMonth(d)}</span>
                  </button>
                  {d === today && <span className="sr-only">{t("inventory.today")}</span>}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {grid.rows.map((row) => {
            const shown = flat.filter((f) => f.row === row)
            // the hotel-level row's name comes from the server in English: shown in the user's language
            const rowName = row.level === "hotel" ? t("inventory.hotel_level") : row.name
            return shown.map((f, mi) => {
              const ri = flat.indexOf(f)
              const metric = f.metric
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
                    {mi === 0 &&
                      (editable ? (
                        // a room's name selects all its nights in view
                        <button
                          type="button"
                          tabIndex={-1}
                          onClick={(e) => selectRoom(row, e.metaKey || e.ctrlKey)}
                          className="block max-w-24 truncate text-left text-[13px] font-semibold text-zinc-900 hover:text-tex-700 hover:underline sm:max-w-40"
                          title={t("inventory.select_room", { room: rowName })}
                        >
                          {rowName}
                        </button>
                      ) : (
                        <span className="block max-w-24 truncate text-[13px] font-semibold text-zinc-900 sm:max-w-40" title={rowName}>
                          {rowName}
                        </span>
                      ))}
                    {mi === 0 && row.level === "hotel" && <span className="block text-[10px] text-zinc-500">{t("inventory.hotel_row_hint")}</span>}
                    <span className="block text-[11px] text-zinc-500">
                      {t(`inventory.metric.${metric}`)}
                      {metric === "rate" && ccy && (
                        <span className="text-zinc-400">
                          {" "}
                          · {ccy} · {t(`inventory.unit.${grid.basis ?? "PERSON"}`)}
                        </span>
                      )}
                      <span className="sr-only"> · {rowName}</span>
                    </span>
                  </th>
                  {row.cells.map((cell, ci) => {
                    const weekend = isoWeekday(cell.date) >= 5
                    const selected = showSelection && sel.isSelected(ri, ci)
                    const key = row.room_type ? cellKey(row.room_type, cell.date) : ""
                    const p = metric === "rate" ? pending.get(key) : undefined
                    const isEditing = editing?.r === ri && editing.c === ci
                    const props = cellProps(ri, ci)
                    return (
                      <td
                        key={cell.date}
                        role="gridcell"
                        {...props}
                        onMouseDown={(e) => {
                          if (isEditing) return
                          props.onMouseDown?.(e)
                          if (e.button === 0 && !e.shiftKey && !e.metaKey && !e.ctrlKey) dragging.current = true
                        }}
                        onMouseEnter={() => {
                          if (dragging.current) sel.click(ri, ci, { shift: true })
                        }}
                        aria-label={cellLabel(t, metric, cell, rowName, ccy, p, p ? newPrice.get(key) : undefined)}
                        className={cn(
                          "relative h-9 cursor-default px-1 text-center align-middle tabular-nums outline-none focus-visible:z-[3] focus-visible:ring-2 focus-visible:ring-tex-500 focus-visible:ring-inset",
                          mi === shown.length - 1 ? "border-b border-b-zinc-300" : "border-b border-b-zinc-100",
                          weekend && "bg-zinc-50/80",
                          editable && "cursor-cell hover:bg-tex-50",
                          cellTone(metric, cell),
                          p && "bg-amber-50 text-amber-950",
                          selected && "bg-tex-100/80 shadow-[inset_0_0_0_1px_var(--color-tex-400)]",
                        )}
                      >
                        {isEditing ? (
                          <input
                            autoFocus
                            aria-label={t("inventory.entry.cell", { room: rowName, day: fmtDate(cell.date) })}
                            aria-invalid={Boolean(editing.error) || undefined}
                            value={editing.text}
                            onChange={(e) => onEditingText(e.target.value)}
                            onKeyDown={(e) => {
                              e.stopPropagation()
                              onEditingKey(e)
                            }}
                            onBlur={onEditingBlur}
                            onFocus={(e) => {
                              const el = e.currentTarget
                              if (editing.typed) el.setSelectionRange(el.value.length, el.value.length)
                              else el.select()
                            }}
                            className={cn(
                              "absolute inset-0.5 w-[calc(100%-4px)] rounded border bg-white px-1 text-center text-xs tabular-nums outline-none",
                              editing.error ? "border-rose-500 ring-2 ring-rose-300" : "border-tex-500 ring-2 ring-tex-200",
                            )}
                          />
                        ) : (
                          <CellContent metric={metric} cell={cell} pending={p} next={p ? newPrice.get(key) : undefined} />
                        )}
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

function CellContent({ metric, cell, pending, next }: { metric: Metric; cell: GridCell; pending?: PendingRate; next?: string }) {
  const { t } = useTexT()
  switch (metric) {
    case "rate": {
      if (pending)
        // an unsaved entry: as typed, and the server's new price once previewed
        return (
          <span className="inline-flex flex-col items-center leading-tight">
            <span className="font-semibold">{next ? decText(next) : rateEditText(pending)}</span>
            <span className="inline-flex items-center gap-0.5 text-[10px] font-medium text-amber-800">
              <span aria-hidden>●</span>
              {next ? rateEditText(pending) : t("inventory.short.unsaved")}
            </span>
          </span>
        )
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
        <span className="text-zinc-400" aria-hidden>
          ✓
        </span>
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

function cellLabel(t: (k: string, p?: Record<string, string | number>) => string, metric: Metric, c: GridCell, room: string, ccy: string, pending?: PendingRate, next?: string): string {
  const day = `${weekdayName(isoWeekday(c.date), "long")} ${fmtDate(c.date)}`
  let v: string
  switch (metric) {
    case "rate":
      v = c.rate ? `${decText(c.rate)} ${ccy}` : t("inventory.aria.no_rate")
      if (c.draft_rate && c.draft_rate !== c.rate) v += `, ${t("inventory.legend.draft")} ${decText(c.draft_rate)}`
      if (c.promo) v += `, ${t("inventory.legend.promo")}`
      if (pending) v += `, ${t("inventory.aria.unsaved", { entry: rateEditText(pending) })}${next ? ` ${decText(next)} ${ccy}` : ""}`
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

