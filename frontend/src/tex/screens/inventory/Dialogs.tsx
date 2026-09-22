import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { AlertTriangle, ArrowLeft, CheckCircle2 } from "lucide-react"
import { tex, TexApiError } from "../../lib/api"
import { useSession } from "../../lib/session"
import { addDays, date as fmtDate, weekday } from "../../lib/format"
import { useTexT } from "../../i18n"
import { Badge, Button, Checkbox, DescriptionList, Dialog, Field, FormGrid, InlineError, Input, Notice, useToast } from "../../ui"
import { WeekdayNumbers } from "../rates/components/pickers"
import { decText, isoWeekday, versionLabel } from "../rates/lib/util"
import { ChangeForm, changesFromCell, describeChanges, emptyChanges, hasChanges, toPayload, type Changes } from "./ChangeForm"
import type { BulkResult, Grid, GridCell, Scope } from "./types"

type T = (k: string, p?: Record<string, string | number>) => string

export function scopeText(t: T, scope: Scope, contractLabel: string | undefined, ratePlanLabel: string | undefined, channelLabel: string | undefined) {
  return [
    scope.contract ? t("inventory.scope.contract", { c: contractLabel ?? scope.contract }) : t("inventory.scope.all_contracts"),
    scope.market ? t("inventory.scope.market", { m: scope.market }) : t("inventory.scope.all_markets"),
    scope.channel ? t("inventory.scope.channel", { c: channelLabel ?? scope.channel }) : t("inventory.scope.all_channels"),
    scope.rate_plan ? t("inventory.scope.rate_plan", { r: ratePlanLabel ?? scope.rate_plan }) : t("inventory.scope.all_rate_plans"),
  ].join(" · ")
}

async function applyBulk(property: string, scope: Scope, start: string, end: string, roomTypes: string[], weekdays: number[] | null, c: Changes) {
  const p = toPayload(c)
  return tex<BulkResult>(
    "crs",
    "ari_bulk_update",
    {
      property,
      start,
      end,
      room_types: roomTypes,
      weekdays: weekdays && weekdays.length < 7 ? weekdays : null,
      contract: scope.contract || null,
      market: scope.market || null,
      channel: scope.channel || null,
      rate_plan: scope.rate_plan || null,
      restrictions: p.restrictions ?? null,
      inventory: p.inventory ?? null,
      rate: p.rate ?? null,
    },
    { post: true },
  )
}

function usePerms() {
  const { can } = useSession()
  return { canRestrict: can("restriction.edit"), canInventory: can("inventory.edit"), canRate: can("contract.edit"), canPublish: can("contract.publish") }
}

/** Result of a bulk/cell update, incl. the draft created by a rate change. */
function ResultView({ result, contract, onPublish }: { result: BulkResult; contract: string; onPublish: (draft: string) => void }) {
  const { t } = useTexT()
  const { canPublish } = usePerms()
  const draftUrl = result.rate ? `/tex/rates/contracts/${encodeURIComponent(contract)}/versions/${encodeURIComponent(result.rate.draft)}` : ""
  return (
    <div className="space-y-3" role="status">
      <p className="flex items-center gap-2 text-sm font-medium text-emerald-800">
        <CheckCircle2 className="size-4 text-emerald-600" aria-hidden />
        {t("inventory.result.done", { dates: result.dates, rooms: result.rooms })}
      </p>
      <ul className="list-disc space-y-1 pl-6 text-sm text-zinc-700">
        {result.restriction_cells !== undefined && <li>{t("inventory.result.restrictions", { count: result.restriction_cells })}</li>}
        {result.inventory && <li>{t("inventory.result.inventory", { fields: Object.keys(result.inventory).map((k) => t(`inventory.f.${k}`)).join(", ") })}</li>}
        {result.rate && <li>{t("inventory.result.rate", { count: result.rate.periods.length })}</li>}
      </ul>
      {result.rate && (
        <Notice tone="warning" title={t("inventory.result.draft_title", { v: versionLabel(result.rate.draft) })}>
          <p>{t("inventory.result.draft_body")}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Link to={draftUrl} className="inline-flex h-8 items-center rounded-lg border border-zinc-300 bg-white px-2.5 text-xs font-medium text-zinc-800 hover:bg-zinc-50">
              {t("inventory.result.open_draft")}
            </Link>
            {canPublish && (
              <Button size="sm" onClick={() => onPublish(result.rate!.draft)}>
                {t("rates.version.publish")}
              </Button>
            )}
          </div>
        </Notice>
      )}
    </div>
  )
}

/** Edit one cell (room type × date) at the current scope. */
export function CellDialog({
  grid,
  room,
  cell,
  scope,
  scopeLabel,
  onClose,
  onApplied,
  onPublish,
}: {
  grid: Grid
  room: { room_type: string; name: string }
  cell: GridCell
  scope: Scope
  scopeLabel: string
  onClose: () => void
  onApplied: () => void
  onPublish: (draft: string) => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const perms = usePerms()
  const [c, setC] = useState<Changes>(() => ({ ...changesFromCell(cell), rateOp: "ABSOLUTE", rateValue: cell.draft_rate ?? cell.rate ?? "" }))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<TexApiError>()
  const [result, setResult] = useState<BulkResult>()
  const canRate = perms.canRate && Boolean(scope.contract) && cell.rate !== undefined
  const editable = perms.canRestrict || perms.canInventory || canRate
  const apply = async () => {
    setBusy(true)
    setErr(undefined)
    try {
      const r = await applyBulk(grid.property, scope, cell.date, cell.date, [room.room_type], null, c)
      toast.success(t("inventory.saved"))
      onApplied()
      if (r.rate) setResult(r)
      else onClose()
    } catch (e) {
      setErr(e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error"))
    } finally {
      setBusy(false)
    }
  }
  const ccy = grid.currency
  return (
    <Dialog
      open
      onClose={busy ? () => undefined : onClose}
      size="lg"
      title={`${room.name} · ${weekday(cell.date)} ${fmtDate(cell.date)}`}
      description={scopeLabel}
      footer={
        result ? (
          <Button onClick={onClose}>{t("core.action.close")}</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={onClose} disabled={busy}>
              {t("core.action.cancel")}
            </Button>
            {editable && (
              <Button onClick={() => void apply()} loading={busy} disabled={!hasChanges(c)}>
                {t("core.action.save")}
              </Button>
            )}
          </>
        )
      }
    >
      {result ? (
        <ResultView result={result} contract={scope.contract} onPublish={onPublish} />
      ) : (
        <div className="space-y-5">
          <div className="rounded-lg border border-zinc-200 bg-zinc-50/60 p-3">
            <p className="mb-2 text-xs font-semibold tracking-wide text-zinc-500 uppercase">{t("inventory.cell.current")}</p>
            <DescriptionList
              cols={3}
              items={[
                { label: t("inventory.metric.avail"), value: cell.closed ? t("inventory.v.closed_sale") : `${cell.available} / ${cell.capacity} (${t("inventory.cell.sold", { n: cell.sold })})` },
                { label: t("inventory.f.stop_sell"), value: cell.stop_sell ? t("inventory.v.stop") : t("inventory.v.open") },
                { label: t("inventory.metric.los"), value: `${cell.min_los ?? "–"} / ${cell.max_los ?? "–"}` },
                { label: t("inventory.metric.arrdep"), value: [cell.cta && "CTA", cell.ctd && "CTD"].filter(Boolean).join(" · ") || "—" },
                { label: t("inventory.f.release_days"), value: cell.release_days ?? "—" },
                ...(cell.rate !== undefined
                  ? [
                      {
                        label: t("inventory.metric.rate"),
                        value: (
                          <span>
                            {cell.rate ? `${decText(cell.rate)} ${ccy ?? ""}` : "—"}
                            {cell.draft_rate && cell.draft_rate !== cell.rate && (
                              <Badge tone="warning" className="ml-2">
                                {t("inventory.legend.draft")}: {decText(cell.draft_rate)}
                              </Badge>
                            )}
                          </span>
                        ),
                      },
                    ]
                  : []),
              ]}
            />
            <p className="mt-2 text-xs text-zinc-500">{t("inventory.cell.effective_hint")}</p>
          </div>
          {editable ? (
            <ChangeForm
              value={c}
              onChange={setC}
              canRestrict={perms.canRestrict}
              canInventory={perms.canInventory}
              canRate={canRate}
              ccy={ccy}
              rateNote={t("inventory.section.rate_hint_cell", { basis: t(`inventory.basis.${grid.basis ?? "PERSON"}`) })}
            />
          ) : (
            <Notice tone="info">{t("inventory.read_only")}</Notice>
          )}
          <InlineError error={err} />
        </div>
      )}
    </Dialog>
  )
}

/** Bulk update: dates × weekdays × room types → restrictions / inventory / rate. */
export function BulkDialog({
  grid,
  scope,
  scopeLabel,
  onClose,
  onApplied,
  onPublish,
}: {
  grid: Grid
  scope: Scope
  scopeLabel: string
  onClose: () => void
  onApplied: () => void
  onPublish: (draft: string) => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const perms = usePerms()
  const [from, setFrom] = useState(grid.dates[0])
  const [to, setTo] = useState(grid.dates[grid.dates.length - 1])
  const [wd, setWd] = useState<number[]>([0, 1, 2, 3, 4, 5, 6])
  const [rooms, setRooms] = useState<string[]>(grid.rows.map((r) => r.room_type))
  const [c, setC] = useState<Changes>(emptyChanges)
  const [step, setStep] = useState<"edit" | "review">("edit")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<TexApiError>()
  const [result, setResult] = useState<BulkResult>()
  const canRate = perms.canRate && Boolean(scope.contract)

  const dayCount = useMemo(() => {
    if (!from || !to || to < from) return 0
    let n = 0
    for (let d = from, i = 0; d <= to && i < 401; d = addDays(d, 1), i++) if (wd.includes(isoWeekday(d))) n++
    return n
  }, [from, to, wd])
  const rangeBad = !from || !to || to < from
  const valid = !rangeBad && dayCount > 0 && rooms.length > 0 && hasChanges(c)
  const lines = describeChanges(t, c, grid.currency)

  const apply = async () => {
    setBusy(true)
    setErr(undefined)
    try {
      const r = await applyBulk(grid.property, scope, from, to, rooms, wd, c)
      setResult(r)
      toast.success(t("inventory.saved"))
      onApplied()
    } catch (e) {
      setErr(e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open
      onClose={busy ? () => undefined : onClose}
      size="xl"
      title={t("inventory.bulk.title")}
      description={scopeLabel}
      footer={
        result ? (
          <Button onClick={onClose}>{t("core.action.close")}</Button>
        ) : step === "edit" ? (
          <>
            <Button variant="secondary" onClick={onClose}>
              {t("core.action.cancel")}
            </Button>
            <Button disabled={!valid} onClick={() => setStep("review")}>
              {t("inventory.bulk.review")}
            </Button>
          </>
        ) : (
          <>
            <Button variant="secondary" icon={<ArrowLeft className="size-4" aria-hidden />} onClick={() => setStep("edit")} disabled={busy}>
              {t("core.action.back")}
            </Button>
            <Button onClick={() => void apply()} loading={busy}>
              {t("inventory.bulk.apply", { count: dayCount * rooms.length })}
            </Button>
          </>
        )
      }
    >
      {result ? (
        <ResultView result={result} contract={scope.contract} onPublish={onPublish} />
      ) : step === "edit" ? (
        <div className="space-y-5">
          <FormGrid cols={2}>
            <Field label={t("inventory.bulk.from")} required>
              <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} data-autofocus />
            </Field>
            <Field label={t("inventory.bulk.to")} required error={rangeBad && from && to ? t("rates.v.range") : undefined} hint={!rangeBad ? t("inventory.bulk.days_selected", { count: dayCount }) : undefined}>
              <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </Field>
          </FormGrid>
          <div className="space-y-1.5">
            <p className="text-sm font-medium text-zinc-800">{t("inventory.bulk.weekdays")}</p>
            <WeekdayNumbers value={wd} onChange={setWd} label={t("inventory.bulk.weekdays")} />
          </div>
          <fieldset className="space-y-1.5">
            <legend className="text-sm font-medium text-zinc-800">{t("inventory.bulk.rooms")}</legend>
            <div className="flex flex-wrap gap-x-5 gap-y-2">
              <Checkbox
                label={<span className="font-medium">{t("inventory.bulk.all_rooms")}</span>}
                checked={rooms.length === grid.rows.length}
                onChange={(e) => setRooms(e.target.checked ? grid.rows.map((r) => r.room_type) : [])}
              />
              {grid.rows.map((r) => (
                <Checkbox
                  key={r.room_type}
                  label={r.name}
                  checked={rooms.includes(r.room_type)}
                  onChange={(e) => setRooms(e.target.checked ? [...rooms, r.room_type] : rooms.filter((x) => x !== r.room_type))}
                />
              ))}
            </div>
          </fieldset>
          <ChangeForm
            value={c}
            onChange={setC}
            canRestrict={perms.canRestrict}
            canInventory={perms.canInventory}
            canRate={canRate}
            ccy={grid.currency}
            rateNote={scope.contract ? t("inventory.section.rate_hint_bulk", { basis: t(`inventory.basis.${grid.basis ?? "PERSON"}`) }) : undefined}
          />
          {perms.canRate && !scope.contract && <p className="text-xs text-zinc-500">{t("inventory.bulk.rate_needs_contract")}</p>}
        </div>
      ) : (
        <div className="space-y-4">
          <Notice tone="info" title={t("inventory.bulk.confirm_title")}>
            {t("inventory.bulk.confirm_body", { days: dayCount, rooms: rooms.length, cells: dayCount * rooms.length })}
          </Notice>
          <DescriptionList
            cols={2}
            items={[
              { label: t("inventory.bulk.period"), value: `${fmtDate(from)} – ${fmtDate(to)}` },
              { label: t("inventory.bulk.weekdays"), value: wd.length === 7 ? t("inventory.bulk.every_day") : wd.map((d) => weekday(addDays("2024-01-01", d))).join(", ") },
              { label: t("inventory.bulk.rooms"), value: rooms.map((r) => grid.rows.find((x) => x.room_type === r)?.name ?? r).join(", ") },
              { label: t("inventory.scope.label"), value: scopeLabel },
            ]}
          />
          <div>
            <p className="text-sm font-semibold text-zinc-900">{t("inventory.bulk.changes")}</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-6 text-sm text-zinc-800">
              {lines.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </div>
          {c.rateOn && (
            <Notice tone="warning">
              <span className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                {t("inventory.bulk.rate_warning")}
              </span>
            </Notice>
          )}
          <InlineError error={err} />
        </div>
      )}
    </Dialog>
  )
}
