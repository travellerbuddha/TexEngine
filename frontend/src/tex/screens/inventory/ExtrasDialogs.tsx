import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { AlertTriangle, ArrowLeft, CheckCircle2, Lock, PencilLine } from "lucide-react"
import { tex, TexApiError, useTexQuery } from "../../lib/api"
import { useSession } from "../../lib/session"
import { addDays, date as fmtDate, nightsBetween, weekday } from "../../lib/format"
import { useTexT } from "../../i18n"
import {
  Badge,
  Button,
  Checkbox,
  DataTable,
  DescriptionList,
  Dialog,
  ErrorState,
  Field,
  FormGrid,
  InlineError,
  Input,
  Notice,
  Select,
  statusTone,
  useToast,
  type Column,
} from "../../ui"
import { WeekdayNumbers } from "../rates/components/pickers"
import { isoWeekday, weekdayName } from "../rates/lib/util"
import type { ExtraAllocation, ExtraGridCell, ExtraGridRow, ExtrasBulkResult, ExtrasDrift, ExtrasGrid } from "./types"

/** Backend limit of one bulk update (kamra/tex/availability/extras.py MAX_UPDATE_DAYS). */
const MAX_UPDATE_DAYS = 400
const ALL_WEEKDAYS = [0, 1, 2, 3, 4, 5, 6]

function asApiError(e: unknown): TexApiError {
  return e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error")
}

function dayTitle(iso: string) {
  return `${weekday(iso)} ${fmtDate(iso)}`
}

// ─── one day of one extra: counts + who holds it ─────────────────────────

type AllocRow = ExtraAllocation & { key: string }

/** Day detail: capacity, sold (held / confirmed), note and, with reservation.view,
 * the allocations holding the units. */
export function ExtraDayDialog({
  property,
  row,
  cell,
  onClose,
  onChange,
}: {
  property: string
  row: ExtraGridRow
  cell: ExtraGridCell
  onClose: () => void
  /** Present with inventory.edit: open the change dialog for this extra and day. */
  onChange?: () => void
}) {
  const { t } = useTexT()
  const { can } = useSession()
  const canView = can("reservation.view", property)
  const anySold = cell.sold > 0 || cell.held + cell.confirmed > 0
  const q = useTexQuery<ExtraAllocation[]>(
    "crs",
    "extras_allocations",
    { property, extra_code: row.code, date: cell.date },
    [property, row.code, cell.date],
    canView && anySold,
  )
  const rows = useMemo<AllocRow[] | undefined>(() => q.data?.map((a, i) => ({ ...a, key: `${a.reservation ?? a.booking ?? "-"}:${a.status}:${i}` })), [q.data])
  const statusText = (s: string) => (s === "Held" || s === "Confirmed" ? t(`inventory.extras.status.${s}`) : s)

  const columns: Column<AllocRow>[] = [
    {
      key: "reservation",
      header: t("inventory.extras.day.col_reservation"),
      cell: (a) => (
        <span className="block min-w-0">
          {a.reservation ? (
            <Link to={`/tex/reservations/${encodeURIComponent(a.reservation)}`} className="font-medium whitespace-nowrap text-tex-700 hover:underline">
              {a.reservation}
            </Link>
          ) : a.booking ? (
            <Link to={`/tex/reservations/booking/${encodeURIComponent(a.booking)}`} className="font-medium whitespace-nowrap text-tex-700 hover:underline">
              {a.booking}
            </Link>
          ) : (
            "—"
          )}
          {/* the booker column is hidden on phones: show the name here instead */}
          <span className="block text-xs text-zinc-500 sm:hidden">{a.booker_name ?? "—"}</span>
        </span>
      ),
    },
    { key: "booker", header: t("inventory.extras.day.col_booker"), cell: (a) => a.booker_name ?? "—", hideBelow: "sm" },
    { key: "units", header: t("inventory.extras.day.col_units"), cell: (a) => a.units, align: "right" },
    { key: "status", header: t("core.label.status"), cell: (a) => <Badge tone={statusTone(a.status)}>{statusText(a.status)}</Badge> },
  ]

  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      title={`${row.name} · ${dayTitle(cell.date)}`}
      description={row.code}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t("core.action.close")}
          </Button>
          {onChange && (
            <Button icon={<PencilLine className="size-4" aria-hidden />} onClick={onChange}>
              {t("inventory.extras.day.change")}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-5">
        <div className="rounded-lg border border-zinc-200 bg-zinc-50/60 p-3">
          <DescriptionList
            cols={3}
            items={[
              {
                label: t("inventory.extras.day.capacity"),
                value:
                  cell.override !== null
                    ? t("inventory.extras.day.cap_override", { n: cell.capacity, d: row.daily_capacity })
                    : t("inventory.extras.day.cap_default", { n: cell.capacity }),
              },
              { label: t("inventory.extras.day.sold"), value: t("inventory.extras.day.sold_detail", { sold: cell.sold, held: cell.held, confirmed: cell.confirmed }) },
              {
                label: t("inventory.extras.day.left"),
                value: cell.over ? (
                  <span className="inline-flex items-center gap-1 font-medium text-rose-800">
                    <AlertTriangle className="size-4" aria-hidden />
                    {t("inventory.extras.legend.over")}
                  </span>
                ) : (
                  cell.remaining
                ),
              },
              {
                label: t("inventory.extras.day.sale"),
                value: cell.closed ? (
                  <span className="inline-flex items-center gap-1 font-medium">
                    <Lock className="size-4" aria-hidden />
                    {t("inventory.v.closed_sale")}
                  </span>
                ) : (
                  t("inventory.v.open_sale")
                ),
              },
              ...(cell.note ? [{ label: t("inventory.extras.day.note"), value: cell.note }] : []),
            ]}
          />
        </div>
        <section aria-labelledby="inv-x-holders" className="space-y-2">
          <h3 id="inv-x-holders" className="text-sm font-semibold text-zinc-900">
            {t("inventory.extras.day.holders")}
          </h3>
          {!anySold ? (
            <p className="text-sm text-zinc-500">{t("inventory.extras.day.none")}</p>
          ) : !canView ? (
            <Notice tone="info">{t("inventory.extras.day.no_view")}</Notice>
          ) : q.error ? (
            <ErrorState error={q.error} onRetry={q.reload} />
          ) : (
            <div className="rounded-lg border border-zinc-200">
              <DataTable
                columns={columns}
                rows={rows}
                rowKey={(a) => a.key}
                loading={q.loading}
                dense
                caption={t("inventory.extras.day.holders_caption", { extra: row.name, date: fmtDate(cell.date) })}
                empty={<p className="px-3 py-4 text-sm text-zinc-500">{t("inventory.extras.day.none")}</p>}
              />
            </div>
          )}
        </section>
      </div>
    </Dialog>
  )
}

// ─── bulk change: capacity override / open-close / note ──────────────────

export interface ChangeInit {
  codes: string[]
  from: string
  to: string
}

/** Change capacity, sale and note of limited extras for dates × weekdays (inventory.edit). */
export function ExtraChangeDialog({ grid, init, onClose, onApplied }: { grid: ExtrasGrid; init: ChangeInit; onClose: () => void; onApplied: () => void }) {
  const { t } = useTexT()
  const toast = useToast()
  const { boot } = useSession()
  const hotel = boot.properties.find((p) => p.name === grid.property)?.property_name ?? grid.property
  const [codes, setCodes] = useState<string[]>(init.codes)
  const [from, setFrom] = useState(init.from)
  const [to, setTo] = useState(init.to)
  const [wd, setWd] = useState<number[]>(ALL_WEEKDAYS)
  const [cap, setCap] = useState("")
  const [sale, setSale] = useState<"" | "1" | "0">("")
  const [noteOn, setNoteOn] = useState(false)
  const [note, setNote] = useState("")
  const [step, setStep] = useState<"edit" | "review">("edit")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<TexApiError>()
  const [result, setResult] = useState<ExtrasBulkResult>()

  const rangeBad = !from || !to || to < from
  const tooLong = !rangeBad && nightsBetween(from, to) >= MAX_UPDATE_DAYS
  const capBad = cap !== "" && !/^\d+$/.test(cap.trim())
  const dayCount = useMemo(() => {
    if (rangeBad) return 0
    let n = 0
    for (let d = from, i = 0; d <= to && i < MAX_UPDATE_DAYS + 1; d = addDays(d, 1), i++) if (wd.includes(isoWeekday(d))) n++
    return n
  }, [from, to, wd, rangeBad])
  const hasChange = cap.trim() !== "" || sale !== "" || noteOn
  const valid = !rangeBad && !tooLong && !capBad && dayCount > 0 && codes.length > 0 && hasChange
  const nameOf = (code: string) => grid.extras.find((x) => x.code === code)?.name ?? code

  const lines: string[] = []
  if (cap.trim() !== "")
    lines.push(parseInt(cap, 10) === 0 ? t("inventory.extras.change.line_cap_default") : t("inventory.extras.change.line_cap", { n: parseInt(cap, 10) }))
  if (sale !== "") lines.push(`${t("inventory.extras.change.sale")}: ${sale === "1" ? t("inventory.v.closed_sale") : t("inventory.v.open_sale")}`)
  if (noteOn) lines.push(note.trim() ? t("inventory.extras.change.line_note", { note: note.trim() }) : t("inventory.extras.change.line_note_clear"))

  const apply = async () => {
    setBusy(true)
    setErr(undefined)
    try {
      const r = await tex<ExtrasBulkResult>(
        "crs",
        "extras_bulk_update",
        {
          property: grid.property,
          extra_codes: codes,
          start: from,
          end: to,
          weekdays: wd.length < 7 ? wd : null,
          capacity: cap.trim() === "" ? null : parseInt(cap, 10),
          closed: sale === "" ? null : Number(sale),
          note: noteOn ? note.trim() : null,
        },
        { post: true },
      )
      toast.success(t("inventory.extras.change.done", { count: r.updated }))
      onApplied()
      if (r.over_capacity.length) setResult(r)
      else onClose()
    } catch (e) {
      setErr(asApiError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open
      onClose={busy ? () => undefined : onClose}
      size="xl"
      title={t("inventory.extras.change.title")}
      description={hotel}
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
              {t("inventory.bulk.apply", { count: dayCount * codes.length })}
            </Button>
          </>
        )
      }
    >
      {result ? (
        <div className="space-y-3" role="status">
          <p className="flex items-center gap-2 text-sm font-medium text-emerald-800">
            <CheckCircle2 className="size-4 text-emerald-600" aria-hidden />
            {t("inventory.extras.change.done", { count: result.updated })}
          </p>
          <Notice tone="warning" title={t("inventory.extras.change.over_title", { count: result.over_capacity.length })}>
            <p className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              {t("inventory.extras.change.over_body")}
            </p>
            <ul className="mt-2 list-disc space-y-0.5 pl-6">
              {result.over_capacity.map((o) => (
                <li key={`${o.extra_code}:${o.date}`}>
                  {t("inventory.extras.change.over_line", { extra: nameOf(o.extra_code), date: dayTitle(o.date), sold: o.sold, cap: o.capacity })}
                </li>
              ))}
            </ul>
          </Notice>
        </div>
      ) : step === "edit" ? (
        <div className="space-y-5">
          <fieldset className="space-y-1.5">
            <legend className="text-sm font-medium text-zinc-800">{t("inventory.extras.change.extras")}</legend>
            <div className="flex flex-wrap gap-x-5 gap-y-2">
              <Checkbox
                label={<span className="font-medium">{t("inventory.extras.change.all_extras")}</span>}
                checked={codes.length === grid.extras.length}
                onChange={(e) => setCodes(e.target.checked ? grid.extras.map((x) => x.code) : [])}
              />
              {grid.extras.map((x) => (
                <Checkbox
                  key={x.code}
                  label={
                    <span>
                      {x.name} <span className="font-mono text-xs text-zinc-500">{x.code}</span>
                    </span>
                  }
                  checked={codes.includes(x.code)}
                  onChange={(e) => setCodes(e.target.checked ? [...codes, x.code] : codes.filter((c) => c !== x.code))}
                />
              ))}
            </div>
          </fieldset>
          <FormGrid cols={2}>
            <Field label={t("inventory.bulk.from")} required>
              <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} data-autofocus />
            </Field>
            <Field
              label={t("inventory.bulk.to")}
              required
              error={rangeBad && from && to ? t("rates.v.range") : tooLong ? t("inventory.extras.change.range_max", { n: MAX_UPDATE_DAYS }) : undefined}
              hint={!rangeBad ? t("inventory.bulk.days_selected", { count: dayCount }) : undefined}
            >
              <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </Field>
          </FormGrid>
          <div className="space-y-1.5">
            <p className="text-sm font-medium text-zinc-800">{t("inventory.bulk.weekdays")}</p>
            <WeekdayNumbers value={wd} onChange={setWd} label={t("inventory.bulk.weekdays")} />
          </div>
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold text-zinc-900">{t("inventory.bulk.changes")}</legend>
            <FormGrid cols={2}>
              <Field
                label={t("inventory.extras.change.capacity")}
                hint={t("inventory.extras.change.capacity_hint")}
                error={capBad ? t("inventory.extras.change.capacity_bad") : undefined}
              >
                <Input
                  type="number"
                  inputMode="numeric"
                  min={0}
                  step={1}
                  value={cap}
                  placeholder={t("inventory.extras.change.unchanged")}
                  onChange={(e) => setCap(e.target.value)}
                  className="w-full sm:w-40"
                />
              </Field>
              <Field label={t("inventory.extras.change.sale")}>
                <Select
                  value={sale}
                  onChange={(e) => setSale(e.target.value as "" | "1" | "0")}
                  options={[
                    { value: "", label: t("inventory.extras.change.unchanged") },
                    { value: "1", label: t("inventory.extras.change.close") },
                    { value: "0", label: t("inventory.extras.change.open") },
                  ]}
                  className="sm:max-w-64"
                />
              </Field>
            </FormGrid>
            <div className="space-y-2">
              <Checkbox label={t("inventory.extras.change.note_on")} checked={noteOn} onChange={(e) => setNoteOn(e.target.checked)} />
              {noteOn && (
                <Field label={t("inventory.extras.day.note")} hint={t("inventory.extras.change.note_hint")}>
                  <Input value={note} maxLength={140} onChange={(e) => setNote(e.target.value)} />
                </Field>
              )}
            </div>
          </fieldset>
        </div>
      ) : (
        <div className="space-y-4">
          <Notice tone="info" title={t("inventory.bulk.confirm_title")}>
            {t("inventory.extras.change.confirm_body", { days: dayCount, extras: codes.length, cells: dayCount * codes.length })}
          </Notice>
          <DescriptionList
            cols={2}
            items={[
              { label: t("inventory.bulk.period"), value: `${fmtDate(from)} – ${fmtDate(to)}` },
              { label: t("inventory.bulk.weekdays"), value: wd.length === 7 ? t("inventory.bulk.every_day") : wd.map((d) => weekdayName(d)).join(", ") },
              { label: t("inventory.extras.change.extras"), value: codes.map(nameOf).join(", ") },
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
          {cap.trim() !== "" && <p className="text-xs text-zinc-500">{t("inventory.extras.change.over_hint")}</p>}
          <InlineError error={err} />
        </div>
      )}
    </Dialog>
  )
}

// ─── recount (reconcile the counters with the allocation ledger) ──────────

/** Rebuild sold counters from the ledger (inventory.edit), with confirmation; shows the drift. */
export function RecountDialog({ grid, onClose, onDone }: { grid: ExtrasGrid; onClose: () => void; onDone: () => void }) {
  const { t } = useTexT()
  const toast = useToast()
  const [code, setCode] = useState("")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<TexApiError>()
  const [drift, setDrift] = useState<ExtrasDrift["drift"]>()
  const nameOf = (c: string) => grid.extras.find((x) => x.code === c)?.name ?? c

  const run = async () => {
    setBusy(true)
    setErr(undefined)
    try {
      const r = await tex<ExtrasDrift>("crs", "extras_reconcile", { property: grid.property, extra_code: code || null }, { post: true })
      setDrift(r.drift)
      toast.success(t("inventory.extras.recount.done"))
      onDone()
    } catch (e) {
      setErr(asApiError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open
      onClose={busy ? () => undefined : onClose}
      size="md"
      title={t("inventory.extras.recount.title")}
      footer={
        drift ? (
          <Button onClick={onClose}>{t("core.action.close")}</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={onClose} disabled={busy}>
              {t("core.action.cancel")}
            </Button>
            <Button onClick={() => void run()} loading={busy}>
              {t("inventory.extras.recount.action")}
            </Button>
          </>
        )
      }
    >
      {drift ? (
        drift.length === 0 ? (
          <Notice tone="success">{t("inventory.extras.recount.none")}</Notice>
        ) : (
          <Notice tone="warning" title={t("inventory.extras.recount.fixed", { count: drift.length })}>
            <ul className="mt-1 list-disc space-y-0.5 pl-6">
              {drift.map((d) => (
                <li key={`${d.extra_code}:${d.date}`}>{t("inventory.extras.recount.line", { extra: nameOf(d.extra_code), date: dayTitle(d.date), was: d.was, now: d.now })}</li>
              ))}
            </ul>
          </Notice>
        )
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-zinc-700">{t("inventory.extras.recount.body")}</p>
          <Field label={t("inventory.extras.change.extras")}>
            <Select
              value={code}
              onChange={(e) => setCode(e.target.value)}
              options={grid.extras.map((x) => ({ value: x.code, label: `${x.name} (${x.code})` }))}
              placeholder={t("inventory.extras.change.all_extras")}
              data-autofocus
            />
          </Field>
          <InlineError error={err} />
        </div>
      )}
    </Dialog>
  )
}
