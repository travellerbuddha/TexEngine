// The action bar of the rates & availability grid (UX revision 2026-10): what is selected, the
// price entry for the selection, the unsaved price edits with their server preview, Save to the
// draft (and publish), and closing or opening sale with its scope stated before it applies.
//
// Prices: nothing is computed here. An entry is kept as typed; "Preview" asks the server what each
// room's price is now and would be (crs.ari_rate_changes without apply), "Save to draft" writes
// them in one transaction. Nothing is sold at the new prices until the draft is published (the
// existing Publish dialog, with its checks). Sale: restrictions apply at once (as the bulk editor's
// always did); the bar says so, names the scope, and keeps an Undo that restores each cell's
// recorded previous value (never an inverse calculation).
import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { Ban, CalendarClock, Check, CircleSlash, Eye, ListChecks, Rocket, Save, SlidersHorizontal, Undo2, X } from "lucide-react"
import { cn } from "../../../lib/utils"
import { tex, TexApiError } from "../../lib/api"
import { date as fmtDate } from "../../lib/format"
import { useTexT } from "../../i18n"
import { Badge, Button, Checkbox, InlineError, Input, Notice, useToast } from "../../ui"
import { decText, versionLabel } from "../rates/lib/util"
import { channelArgs, type Grid, type GridCell, type Scope } from "./types"
import { parseRateEntry, rateEditText, targetBatches, toChanges, type GridTarget, type PendingRate, type RateEdit } from "./rateEdits.ts"

type T = (k: string, p?: Record<string, string | number>) => string

/** crs.ari_rate_changes */
export interface RateChangesAnswer {
  contract: string
  draft: string | null
  creates_draft: boolean
  based_on: string
  currency: string
  basis: "PERSON" | "ROOM"
  new_periods: number
  cells: { room_type: string; start: string; end: string; current: string; new: string }[]
  errors: string[]
  applied: boolean
}

export interface GridActionsProps {
  grid: Grid
  scope: Scope
  /** the restrictions' scope in words (contract, market, channel, rate plan) */
  scopeLabel: string
  contractCode?: string
  targets: GridTarget[]
  roomName: (rt: string | null) => string
  cellAt: (room: string | null, date: string) => GridCell | undefined
  /** a contract is chosen and the user may change its rates */
  canRate: boolean
  canRestrict: boolean
  canPublish: boolean
  minorUnits: number
  pending: PendingRate[]
  canUndo: boolean
  onUndo: () => void
  onDiscardPending: () => void
  /** an entry for every selected room cell that has a contract price */
  onPriceEntry: (edit: RateEdit) => void
  /** the server's new price per cell, after a preview */
  onPreview: (answer: RateChangesAnswer | null) => void
  onSaved: () => void
  onPublish: (draft: string) => void
  onRestrictionsApplied: () => void
  onMore: () => void
  onDetails?: () => void
  onClearSelection: () => void
}

/** "12 Oct – 16 Oct" or one day. */
function span(a: string, b: string) {
  return a === b ? fmtDate(a, "short") : `${fmtDate(a, "short")} – ${fmtDate(b, "short")}`
}

function entryError(t: T, code: string) {
  return t(`inventory.entry.err.${code}`)
}

/** What an entry does, in words: "Set to 120.00 EUR", "Raise by 10 %", "Lower by 20 EUR". */
export function entryReading(t: T, e: RateEdit, ccy: string) {
  switch (e.op) {
    case "ABSOLUTE":
      return t("inventory.entry.read.ABSOLUTE", { v: decText(e.value), ccy })
    case "ADJUST_PERCENT":
      return e.value.startsWith("-") ? t("inventory.entry.read.PCT_DOWN", { v: e.value.slice(1) }) : t("inventory.entry.read.PCT_UP", { v: e.value })
    case "ADD":
      return t("inventory.entry.read.ADD", { v: decText(e.value), ccy })
    case "SUBTRACT":
      return t("inventory.entry.read.SUBTRACT", { v: decText(e.value), ccy })
  }
}

export function GridActions(p: GridActionsProps) {
  const { t } = useTexT()
  const toast = useToast()
  const { grid, scope } = p
  const ccy = grid.currency ?? ""
  const rooms = useMemo(() => [...new Set(p.targets.map((x) => x.room))], [p.targets])
  const nights = useMemo(() => [...new Set(p.targets.map((x) => x.date))].sort(), [p.targets])
  const roomTargets = p.targets.filter((x) => x.room !== null)
  const priced = roomTargets.filter((x) => p.cellAt(x.room, x.date)?.rate !== undefined)

  // ── price entry for the selection ──
  const [entry, setEntry] = useState("")
  const parsed = entry.trim() ? parseRateEntry(entry, p.minorUnits) : null
  const applyEntry = () => {
    if (!parsed?.ok || !("edit" in parsed) || !priced.length) return
    p.onPriceEntry(parsed.edit)
    setEntry("")
  }

  // ── preview and save of the unsaved price edits ──
  const changes = useMemo(() => toChanges(p.pending), [p.pending])
  const [answer, setAnswer] = useState<RateChangesAnswer | null>(null)
  const [busy, setBusy] = useState<"preview" | "save" | null>(null)
  const [err, setErr] = useState<TexApiError>()
  const pendingKey = JSON.stringify(changes)
  const { onPreview } = p
  // an edit after the preview makes it stale: the user previews again
  useEffect(() => {
    setAnswer(null)
    setErr(undefined)
    onPreview(null)
  }, [pendingKey, scope.contract, onPreview])
  const call = async (apply: 0 | 1) => {
    setBusy(apply ? "save" : "preview")
    setErr(undefined)
    try {
      const a = await tex<RateChangesAnswer>("crs", "ari_rate_changes", { property: grid.property, contract: scope.contract, changes, apply }, { post: true })
      return a
    } catch (e) {
      setErr(e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error"))
      return null
    } finally {
      setBusy(null)
    }
  }
  const preview = async () => {
    const a = await call(0)
    if (a) {
      setAnswer(a)
      p.onPreview(a)
    }
  }
  const save = async (publish: boolean) => {
    const a = await call(1)
    if (!a) return
    // the cells (room × night) saved, as the user entered them
    toast.success(t("inventory.rates.saved", { count: p.pending.length, v: versionLabel(a.draft) }))
    p.onSaved()
    if (publish && a.draft) p.onPublish(a.draft)
  }

  // ── close / open sale ──
  const [sale, setSale] = useState<null | { close: boolean; contractOnly: boolean; override: boolean }>(null)
  const [saleBusy, setSaleBusy] = useState(false)
  const [saleErr, setSaleErr] = useState<TexApiError>()
  const [undo, setUndo] = useState<null | { text: string; restore: { room: string | null; date: string; value: string }[]; contract: string | null }>(null)
  const cells = p.targets.map((x) => ({ ...x, cell: p.cellAt(x.room, x.date) }))
  const ownStop = (c: GridCell | undefined) => (c?.own?.stop_sell ?? "") as "" | "STOP" | "OPEN"
  const alreadyClosed = cells.filter((x) => x.cell?.stop_sell).length
  const inherited = cells.filter((x) => x.cell?.stop_sell && ownStop(x.cell) !== "STOP").length
  const runSale = async () => {
    if (!sale) return
    const contract = sale.contractOnly ? scope.contract || null : null
    // the grid shows each cell's own value at its own scope only: at another scope it is unknown
    const same = contract === (scope.contract || null)
    // the value each cell gets; cells that stay as they are are left out
    const plan = cells
      .map((x) => {
        const own = same ? ownStop(x.cell) : null
        let value: string | null
        if (sale.close) value = own === "STOP" ? null : "STOP"
        else if (own === null || own === "STOP") value = "" // clear what is set there (nothing set: nothing written)
        else if (sale.override && x.cell?.stop_sell) value = "OPEN"
        else value = null
        return { room: x.room, date: x.date, value, prev: own }
      })
      .filter((x): x is { room: string | null; date: string; value: string; prev: "" | "STOP" | "OPEN" | null } => x.value !== null)
    if (!plan.length) {
      setSale(null)
      toast.info(t("inventory.sale.nothing"))
      return
    }
    setSaleBusy(true)
    setSaleErr(undefined)
    try {
      await applyStops(grid.property, scope, contract, plan)
      const text = t(sale.close ? "inventory.sale.done_close" : "inventory.sale.done_open", { count: plan.length })
      // Undo puts back each cell's recorded value: only where the grid showed it (its own scope)
      setUndo(same ? { text, restore: plan.map((x) => ({ room: x.room, date: x.date, value: x.prev ?? "" })), contract } : { text, restore: [], contract })
      setSale(null)
      p.onRestrictionsApplied()
    } catch (e) {
      setSaleErr(e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error"))
    } finally {
      setSaleBusy(false)
    }
  }
  const runUndo = async () => {
    if (!undo) return
    setSaleBusy(true)
    try {
      await applyStops(grid.property, scope, undo.contract, undo.restore)
      toast.success(t("inventory.sale.undone"))
      setUndo(null)
      p.onRestrictionsApplied()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSaleBusy(false)
    }
  }

  const selecting = p.targets.length > 0
  if (!selecting && !p.pending.length && !undo) return null
  const draftLabel = answer ? (answer.creates_draft ? t("inventory.rates.new_draft") : versionLabel(answer.draft)) : grid.draft ? versionLabel(grid.draft) : t("inventory.rates.new_draft")

  return (
    <section aria-label={t("inventory.actions.label")} className="sticky bottom-0 z-20 -mx-3 mt-3 border-t border-zinc-200 bg-white/95 px-3 py-3 shadow-[0_-4px_12px_-6px_rgb(0_0_0/0.15)] backdrop-blur sm:-mx-6 sm:px-6">
      {/* ── the selection and what can be done with it ── */}
      {selecting && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <p className="min-w-0 text-sm text-zinc-800" aria-live="polite">
            <ListChecks className="mr-1.5 inline size-4 text-tex-600" aria-hidden />
            <span className="font-semibold">{t("inventory.sel.count", { count: p.targets.length })}</span>
            <span className="text-zinc-600">
              {" · "}
              {t("inventory.sel.rooms", { count: rooms.length })}: {rooms.map((r) => p.roomName(r)).join(", ")}
              {" · "}
              {span(nights[0], nights[nights.length - 1])} ({t("inventory.sel.nights", { count: nights.length })})
            </span>
          </p>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {p.onDetails && (
              <Button size="sm" variant="ghost" icon={<SlidersHorizontal className="size-4" aria-hidden />} onClick={p.onDetails}>
                {t("inventory.sel.details")}
              </Button>
            )}
            <Button size="sm" variant="ghost" icon={<X className="size-4" aria-hidden />} onClick={p.onClearSelection}>
              {t("inventory.sel.clear")}
            </Button>
          </div>
        </div>
      )}
      {selecting && (
        <div className="mt-2 flex flex-wrap items-start gap-x-6 gap-y-3">
          {/* price */}
          <div className="min-w-0">
            <p className="mb-1 text-xs font-semibold tracking-wide text-zinc-500 uppercase">{t("inventory.rates.title")}</p>
            {p.canRate && priced.length ? (
              <form
                className="flex flex-wrap items-start gap-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  applyEntry()
                }}
              >
                <div className="w-56">
                  <Input
                    aria-label={t("inventory.rates.entry_label", { count: priced.length })}
                    aria-describedby="inv-entry-help"
                    aria-invalid={parsed ? !parsed.ok : undefined}
                    value={entry}
                    onChange={(e) => setEntry(e.target.value)}
                    placeholder={t("inventory.rates.entry_ph")}
                    inputMode="decimal"
                    className="tabular-nums"
                  />
                  <p id="inv-entry-help" className={cn("mt-1 w-[22rem] max-w-[80vw] text-xs", parsed && !parsed.ok ? "font-medium text-rose-700" : "text-zinc-500")}>
                    {parsed
                      ? parsed.ok
                        ? "edit" in parsed
                          ? `${entryReading(t, parsed.edit, ccy)} · ${t("inventory.rates.entry_cells", { count: priced.length })}`
                          : t("inventory.rates.entry_hint")
                        : entryError(t, parsed.code)
                      : t("inventory.rates.entry_hint")}
                  </p>
                </div>
                <Button type="submit" size="md" variant="secondary" disabled={!parsed?.ok || !("edit" in parsed)}>
                  {t("inventory.rates.entry_apply")}
                </Button>
              </form>
            ) : (
              <p className="max-w-64 text-xs text-zinc-500">{!scope.contract ? t("inventory.rates.needs_contract") : !roomTargets.length ? t("inventory.rates.needs_rooms") : t("inventory.rates.no_rights")}</p>
            )}
          </div>
          {/* sale */}
          {p.canRestrict && (
            <div>
              <p className="mb-1 text-xs font-semibold tracking-wide text-zinc-500 uppercase">{t("inventory.sale.title")}</p>
              <div className="flex flex-wrap gap-2">
                <Button size="md" variant="secondary" icon={<Ban className="size-4 text-rose-700" aria-hidden />} onClick={() => setSale({ close: true, contractOnly: Boolean(scope.contract), override: false })}>
                  {t("inventory.sale.close")}
                </Button>
                <Button size="md" variant="secondary" icon={<CircleSlash className="size-4 text-emerald-700" aria-hidden />} onClick={() => setSale({ close: false, contractOnly: Boolean(scope.contract), override: false })}>
                  {t("inventory.sale.open")}
                </Button>
                <Button size="md" variant="ghost" icon={<CalendarClock className="size-4" aria-hidden />} onClick={p.onMore}>
                  {t("inventory.sale.more")}
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── close / open sale: what, where, from when ── */}
      {sale && (
        <div role="group" aria-label={t(sale.close ? "inventory.sale.confirm_close" : "inventory.sale.confirm_open")} className="mt-3 rounded-lg border border-zinc-200 bg-zinc-50 p-3 text-sm">
          <p className="font-semibold text-zinc-900">
            {t(sale.close ? "inventory.sale.confirm_close_n" : "inventory.sale.confirm_open_n", { count: p.targets.length })}
          </p>
          <p className="mt-0.5 text-zinc-700">
            {rooms.map((r) => p.roomName(r)).join(", ")} · {span(nights[0], nights[nights.length - 1])}
          </p>
          <fieldset className="mt-2">
            <legend className="text-xs font-semibold text-zinc-600">{t("inventory.sale.where")}</legend>
            <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1">
              {scope.contract && (
                <label className="flex items-center gap-2">
                  <input type="radio" name="inv-sale-scope" className="accent-tex-600" checked={sale.contractOnly} onChange={() => setSale({ ...sale, contractOnly: true })} />
                  {t("inventory.sale.only_contract", { c: p.contractCode ?? scope.contract })}
                </label>
              )}
              <label className="flex items-center gap-2">
                <input type="radio" name="inv-sale-scope" className="accent-tex-600" checked={!sale.contractOnly} onChange={() => setSale({ ...sale, contractOnly: false })} />
                {t("inventory.sale.all_contracts")}
              </label>
            </div>
            <p className="mt-1 text-xs text-zinc-600">{t("inventory.sale.also", { scope: p.scopeLabel.split(" · ").slice(1).join(" · ") })}</p>
          </fieldset>
          {sale.close && alreadyClosed > 0 && <p className="mt-2 text-xs text-zinc-600">{t("inventory.sale.already_closed", { count: alreadyClosed })}</p>}
          {!sale.close && inherited > 0 && sale.contractOnly === Boolean(scope.contract) && (
            <div className="mt-2">
              <p className="text-xs text-zinc-700">{t("inventory.sale.inherited", { count: inherited })}</p>
              <Checkbox className="mt-1 text-xs" label={t("inventory.sale.override")} checked={sale.override} onChange={(e) => setSale({ ...sale, override: e.target.checked })} />
            </div>
          )}
          <p className="mt-2 text-xs font-medium text-amber-800">{t("inventory.sale.immediate")}</p>
          <InlineError error={saleErr} />
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" variant={sale.close ? "danger" : "primary"} loading={saleBusy} icon={<Check className="size-4" aria-hidden />} onClick={() => void runSale()}>
              {t(sale.close ? "inventory.sale.confirm_close" : "inventory.sale.confirm_open")}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setSale(null)} disabled={saleBusy}>
              {t("core.action.cancel")}
            </Button>
          </div>
        </div>
      )}
      {undo && !sale && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-zinc-700" role="status">
          <Check className="size-4 text-emerald-600" aria-hidden />
          {undo.text}
          {undo.restore.length > 0 && (
            <Button size="sm" variant="link" icon={<Undo2 className="size-3.5" aria-hidden />} loading={saleBusy} onClick={() => void runUndo()}>
              {t("inventory.sale.undo")}
            </Button>
          )}
          <button type="button" className="text-xs text-zinc-500 underline" onClick={() => setUndo(null)}>
            {t("core.action.close")}
          </button>
        </p>
      )}

      {/* ── unsaved price edits ── */}
      {p.pending.length > 0 && (
        <div className={cn("mt-3 rounded-lg border p-3", answer?.errors.length ? "border-rose-300 bg-rose-50/60" : "border-amber-300 bg-amber-50/60")}>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <Badge tone="warning">{t("inventory.rates.unsaved_badge")}</Badge>
            <p className="text-sm text-zinc-800">
              {t("inventory.rates.unsaved", { count: p.pending.length })}{" "}
              <span className="text-zinc-600">
                {t("inventory.rates.target", { c: p.contractCode ?? scope.contract, v: draftLabel })}
              </span>
            </p>
            <div className="ml-auto flex flex-wrap gap-2">
              <Button size="sm" variant="ghost" icon={<Undo2 className="size-4" aria-hidden />} disabled={!p.canUndo || Boolean(busy)} onClick={p.onUndo} shortcut="Ctrl Z">
                {t("inventory.rates.undo")}
              </Button>
              <Button size="sm" variant="ghost" disabled={Boolean(busy)} onClick={p.onDiscardPending}>
                {t("inventory.rates.discard")}
              </Button>
              {!answer ? (
                <Button size="sm" icon={<Eye className="size-4" aria-hidden />} loading={busy === "preview"} onClick={() => void preview()}>
                  {t("inventory.rates.preview")}
                </Button>
              ) : (
                <>
                  <Button size="sm" icon={<Save className="size-4" aria-hidden />} loading={busy === "save"} disabled={answer.errors.length > 0} onClick={() => void save(false)}>
                    {t("inventory.rates.save")}
                  </Button>
                  {p.canPublish && (
                    <Button size="sm" variant="secondary" icon={<Rocket className="size-4" aria-hidden />} disabled={answer.errors.length > 0 || Boolean(busy)} onClick={() => void save(true)}>
                      {t("inventory.rates.save_publish")}
                    </Button>
                  )}
                </>
              )}
            </div>
          </div>
          <InlineError error={err} />
          {answer && <PreviewTable t={t} answer={answer} roomName={p.roomName} />}
          {!answer && <p className="mt-1 text-xs text-zinc-600">{t("inventory.rates.preview_hint")}</p>}
        </div>
      )}
    </section>
  )
}

function PreviewTable({ t, answer, roomName }: { t: T; answer: RateChangesAnswer; roomName: (rt: string | null) => string }) {
  const ccy = answer.currency
  return (
    <div className="mt-3 space-y-2">
      {answer.errors.length > 0 && (
        <Notice tone="danger" title={t("inventory.rates.refused_title")}>
          <ul className="list-disc pl-5">
            {answer.errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </Notice>
      )}
      <div className="max-h-40 overflow-auto rounded-md border border-zinc-200 bg-white">
        <table className="min-w-full text-sm">
          <caption className="sr-only">{t("inventory.rates.preview_caption")}</caption>
          <thead className="sticky top-0 bg-zinc-50 text-left text-xs text-zinc-600">
            <tr>
              <th scope="col" className="px-3 py-1.5 font-medium">{t("inventory.rates.col_room")}</th>
              <th scope="col" className="px-3 py-1.5 font-medium">{t("inventory.rates.col_nights")}</th>
              <th scope="col" className="px-3 py-1.5 text-right font-medium">{answer.creates_draft ? t("inventory.rates.col_now_live") : t("inventory.rates.col_now_draft")}</th>
              <th scope="col" className="px-3 py-1.5 text-right font-medium">{t("inventory.rates.col_new")}</th>
            </tr>
          </thead>
          <tbody>
            {answer.cells.map((c) => (
              <tr key={`${c.room_type}-${c.start}`} className="border-t border-zinc-100">
                <td className="px-3 py-1.5">{roomName(c.room_type)}</td>
                <td className="px-3 py-1.5 whitespace-nowrap">{span(c.start, c.end)}</td>
                <td className="px-3 py-1.5 text-right text-zinc-600 tabular-nums">
                  {decText(c.current)} {ccy}
                </td>
                <td className="px-3 py-1.5 text-right font-semibold tabular-nums">
                  {decText(c.new)} {ccy}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-zinc-600">
        {t(`inventory.rates.basis.${answer.basis}`)}
        {" · "}
        {answer.new_periods > 0 ? t("inventory.rates.new_periods", { count: answer.new_periods }) : t("inventory.rates.no_new_periods")}
        {" · "}
        {t("inventory.rates.not_live")}{" "}
        <Link to={`/tex/rates/contracts/${encodeURIComponent(answer.contract)}`} className="font-medium text-tex-700 underline">
          {t("inventory.rates.open_contract")}
        </Link>
      </p>
    </div>
  )
}

/** Stop-sell values per cell at the grid's market / channel / rate plan and `contract`, one bulk
 * call per rectangle of cells that get the same value. */
async function applyStops(property: string, scope: Scope, contract: string | null, plan: { room: string | null; date: string; value: string }[]) {
  const byValue = new Map<string, GridTarget[]>()
  for (const x of plan) byValue.set(x.value, [...(byValue.get(x.value) ?? []), { room: x.room, date: x.date }])
  for (const [value, targets] of byValue) {
    for (const b of targetBatches(targets)) {
      const hotel = b.rooms.includes(null)
      const roomTypes = b.rooms.filter((r): r is string => r !== null)
      for (const part of [...(hotel ? [null] : []), ...(roomTypes.length ? [roomTypes] : [])]) {
        await tex(
          "crs",
          "ari_bulk_update",
          {
            property,
            start: b.start,
            end: b.end,
            room_types: part ?? [],
            hotel_level: part === null ? 1 : 0,
            contract,
            market: scope.market || null,
            ...channelArgs(scope),
            rate_plan: scope.rate_plan || null,
            restrictions: { stop_sell: value },
          },
          { post: true },
        )
      }
    }
  }
}

export { rateEditText }
