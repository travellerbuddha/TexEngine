import { useEffect, useMemo, useState } from "react"
import { AlertTriangle, Trash2 } from "lucide-react"
import { cn } from "../../../../../lib/utils"
import { useTexQuery } from "../../../../lib/api"
import { date as fmtDate, money } from "../../../../lib/format"
import { useTexT } from "../../../../i18n"
import { Badge, Button, DecimalInput, Dialog, Field, IconButton, Notice, Select } from "../../../../ui"
import { DERIVED_OPS, enumLabel, enumOptions, OPS_ROOM, opText, PERCENT_OPS } from "../../lib/options"
import type { PriceMatrix, Row } from "../../lib/types"
import { newKey } from "../../lib/util"
import { contractRoomOptions, TabIntro, TabIssues, type TabProps } from "./shared"

const ALL = "" // period_code blank = rule for every period

/** Room × period price grid (TEX Period Rate): base room absolute prices, derived
 * rooms via MULTIPLY / % / ADD of the base (R-10), period overrides. */
export function RatesTab({ doc, state, readOnly, issues, setTable, dirty }: TabProps) {
  const { t } = useTexT()
  const ccy = doc.contract_doc.contract_currency
  const rooms = contractRoomOptions(doc, state)
  const periods = state.tables.periods.filter((p) => String(p.period_code || "").trim())
  const rules = state.tables.period_rates
  const [edit, setEdit] = useState<{ room: string; period: string } | null>(null)
  const matrix = useTexQuery<PriceMatrix>("contracts", "price_matrix", { version: doc.name }, [doc.name, doc.modified])

  const find = (room: string, period: string) => rules.find((r) => r.room_type === room && String(r.period_code || "").trim() === period)
  const known = new Set(rooms.map((r) => r.value))
  const knownP = new Set(periods.map((p) => String(p.period_code).trim()))
  const orphans = rules.filter((r) => !known.has(String(r.room_type)) || (String(r.period_code || "").trim() && !knownP.has(String(r.period_code).trim())))
  const baseRoom = state.tables.rooms.find((r) => r.is_base)?.room_type as string | undefined

  const resolved = (room: string, period: string) => {
    if (dirty || !matrix.data) return undefined
    const row = matrix.data.rooms.find((r) => r.room_type === room)
    if (!row) return undefined
    return { value: row.cells[period] ?? null, error: row.errors?.[period] }
  }

  const upsert = (room: string, period: string, patch: { op: string; value: string; base_room_type: string } | null) => {
    const rest = rules.filter((r) => !(r.room_type === room && String(r.period_code || "").trim() === period))
    if (!patch) return setTable("period_rates", rest)
    const existing = find(room, period)
    const row: Row = { ...(existing ?? { _key: newKey() }), room_type: room, period_code: period, op: patch.op, value: patch.value, base_room_type: DERIVED_OPS.has(patch.op) ? patch.base_room_type : "" }
    setTable("period_rates", existing ? rules.map((r) => (r === existing ? row : r)) : [...rules, row])
  }

  const cols = [{ code: ALL, name: t("rates.rates.all_periods"), start: "", end: "" }, ...periods.map((p) => ({ code: String(p.period_code).trim(), name: String(p.period_name || ""), start: String(p.start_date || ""), end: String(p.end_date || "") }))]

  return (
    <div className="space-y-4">
      <TabIntro title={t("rates.tab.rates")} aside={<Badge tone="info">{t(`rates.rates.unit.${doc.contract_doc.pricing_basis}`, { ccy })}</Badge>}>
        {t("rates.rates.intro")}
      </TabIntro>
      <TabIssues issues={issues} tab="rates" />
      {rooms.length === 0 || periods.length === 0 ? (
        <Notice tone="info">{t("rates.rates.need_rooms_periods")}</Notice>
      ) : (
        <>
          <div className="max-h-[65vh] overflow-auto rounded-lg border border-zinc-200">
            <table className="min-w-full border-separate border-spacing-0 text-sm">
              <caption className="sr-only">{t("rates.rates.caption")}</caption>
              <thead>
                <tr>
                  <th scope="col" className="sticky top-0 left-0 z-[3] min-w-40 border-r border-b border-zinc-200 bg-zinc-50 px-3 py-2 text-left text-xs font-semibold text-zinc-600">
                    {t("rates.f.room_type")}
                  </th>
                  {cols.map((c) => (
                    <th key={c.code || "all"} scope="col" className="sticky top-0 z-[2] min-w-28 border-b border-zinc-200 bg-zinc-50 px-2 py-2 text-left align-bottom text-xs font-semibold text-zinc-700">
                      <span className="block">{c.code || c.name}</span>
                      {c.code && <span className="block truncate font-normal text-zinc-500">{c.name}</span>}
                      {c.start && (
                        <span className="block font-normal whitespace-nowrap text-zinc-500">
                          {fmtDate(c.start, "short")} – {fmtDate(c.end, "short")}
                        </span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rooms.map((room) => {
                  const isBase = room.value === baseRoom
                  return (
                    <tr key={room.value}>
                      <th scope="row" className="sticky left-0 z-[1] border-r border-b border-zinc-100 bg-white px-3 py-2 text-left align-top font-medium text-zinc-900">
                        <span className="block">{room.label}</span>
                        {isBase && <Badge tone="brand">{t("rates.f.is_base")}</Badge>}
                      </th>
                      {cols.map((c) => {
                        const rule = find(room.value, c.code)
                        const res = c.code ? resolved(room.value, c.code) : undefined
                        const inherited = !rule && c.code && find(room.value, ALL)
                        const label = `${room.label} · ${c.code || c.name}`
                        const content = (
                          <>
                            {rule ? (
                              <span className="block font-medium text-zinc-900 tabular-nums">
                                {rule.op === "INHERIT" ? t("rates.op.INHERIT") : opText(String(rule.op), String(rule.value || "0"))}
                                {DERIVED_OPS.has(String(rule.op)) && rule.base_room_type && (
                                  <span className="block text-[11px] font-normal text-zinc-500">{t("rates.rates.of_room", { room: rooms.find((r) => r.value === rule.base_room_type)?.label ?? String(rule.base_room_type) })}</span>
                                )}
                              </span>
                            ) : (
                              <span className="block text-zinc-400">{inherited ? t("rates.rates.from_all") : "—"}</span>
                            )}
                            {res && (
                              <span className={cn("mt-0.5 block text-[11px] tabular-nums", res.error ? "text-rose-700" : "text-emerald-800")} title={res.error}>
                                {res.error ? (
                                  <>
                                    <AlertTriangle className="mr-0.5 inline size-3" aria-hidden />
                                    {t("rates.rates.unsellable")}
                                  </>
                                ) : res.value !== null ? (
                                  <>= {money(res.value, ccy)}</>
                                ) : null}
                              </span>
                            )}
                          </>
                        )
                        return (
                          <td key={c.code || "all"} className="border-b border-zinc-100 p-1 align-top">
                            {readOnly ? (
                              <div className="rounded-md px-2 py-1.5" aria-label={label}>
                                {content}
                              </div>
                            ) : (
                              <button
                                type="button"
                                onClick={() => setEdit({ room: room.value, period: c.code })}
                                aria-label={t("rates.rates.edit_cell", { cell: label })}
                                className="block w-full rounded-md border border-transparent px-2 py-1.5 text-left hover:border-tex-300 hover:bg-tex-50/60"
                              >
                                {content}
                              </button>
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-zinc-500">
            {dirty ? t("rates.rates.resolved_after_save") : matrix.error ? matrix.error.message : t("rates.rates.resolved_legend")}
          </p>
        </>
      )}

      {orphans.length > 0 && (
        <section className="space-y-2" aria-labelledby="orphans">
          <h3 id="orphans" className="text-sm font-semibold text-zinc-900">
            {t("rates.rates.orphans")}
          </h3>
          <p className="text-sm text-zinc-600">{t("rates.rates.orphans_hint")}</p>
          <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
            {orphans.map((r) => (
              <li key={r._key} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                <span>
                  {String(r.room_type)} · {String(r.period_code || t("rates.rates.all_periods"))} · {opText(String(r.op), String(r.value || "0"))}
                </span>
                {!readOnly && (
                  <IconButton size="sm" label={t("core.action.delete")} icon={<Trash2 className="size-4" />} onClick={() => setTable("period_rates", rules.filter((x) => x !== r))} />
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {edit && (
        <RuleDialog
          key={`${edit.room}|${edit.period}`}
          room={rooms.find((r) => r.value === edit.room)?.label ?? edit.room}
          period={edit.period ? edit.period : t("rates.rates.all_periods")}
          rule={find(edit.room, edit.period)}
          baseOptions={rooms.filter((r) => r.value !== edit.room)}
          defaultBase={baseRoom && baseRoom !== edit.room ? baseRoom : ""}
          isBase={edit.room === baseRoom}
          ccy={ccy}
          onClose={() => setEdit(null)}
          onApply={(patch) => {
            upsert(edit.room, edit.period, patch)
            setEdit(null)
          }}
        />
      )}
    </div>
  )
}

function RuleDialog({
  room,
  period,
  rule,
  baseOptions,
  defaultBase,
  isBase,
  ccy,
  onClose,
  onApply,
}: {
  room: string
  period: string
  rule: Row | undefined
  baseOptions: { value: string; label: string }[]
  defaultBase: string
  isBase: boolean
  ccy: string
  onClose: () => void
  onApply: (patch: { op: string; value: string; base_room_type: string } | null) => void
}) {
  const { t } = useTexT()
  const [op, setOp] = useState(String(rule?.op || (isBase ? "ABSOLUTE" : "MULTIPLY")))
  const [value, setValue] = useState(String(rule?.value ?? ""))
  const [base, setBase] = useState(String(rule?.base_room_type || defaultBase))
  useEffect(() => {
    if (DERIVED_OPS.has(op) && !base && defaultBase) setBase(defaultBase)
  }, [op, base, defaultBase])
  const derived = DERIVED_OPS.has(op)
  const needsValue = op !== "INHERIT"
  const ok = (!needsValue || value !== "") && (!derived || Boolean(base))
  const suffix = PERCENT_OPS.has(op) ? "%" : op === "MULTIPLY" ? "×" : ccy
  const opts = useMemo(() => enumOptions(t, "op", OPS_ROOM), [t])
  return (
    <Dialog
      open
      onClose={onClose}
      title={t("rates.rates.rule_title", { room, period })}
      footer={
        <>
          {rule && (
            <Button variant="ghost" className="mr-auto text-rose-700! hover:bg-rose-50!" onClick={() => onApply(null)}>
              {t("rates.rates.remove_rule")}
            </Button>
          )}
          <Button variant="secondary" onClick={onClose}>
            {t("core.action.cancel")}
          </Button>
          <Button disabled={!ok} onClick={() => onApply({ op, value: needsValue ? value : "0", base_room_type: base })}>
            {t("core.action.apply")}
          </Button>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (ok) onApply({ op, value: needsValue ? value : "0", base_room_type: base })
        }}
      >
        <Field label={t("rates.f.rule")} hint={t(`rates.op_help.${op}`)}>
          <Select value={op} onChange={(e) => setOp(e.target.value)} options={opts} data-autofocus />
        </Field>
        {needsValue && (
          <Field label={t("rates.f.value")} required hint={op === "ABSOLUTE" ? t("rates.rates.abs_hint", { ccy }) : undefined}>
            <DecimalInput value={value} onValueChange={setValue} decimals={6} allowNegative={op === "ADJUST_PERCENT"} suffix={suffix} />
          </Field>
        )}
        {derived && (
          <Field label={t("rates.f.base_room_type")} required hint={t("rates.h.base_room_type")}>
            <Select value={base} onChange={(e) => setBase(e.target.value)} options={baseOptions} placeholder={t("rates.common.choose")} />
          </Field>
        )}
        {derived && base && value && (
          <p className="rounded-md bg-zinc-50 px-3 py-2 text-sm text-zinc-700">
            {t("rates.rates.reads", { room, rule: `${enumLabel(t, "op", op)} ${opText(op, value)}`, base: baseOptions.find((b) => b.value === base)?.label ?? base })}
          </p>
        )}
        <button type="submit" hidden />
      </form>
    </Dialog>
  )
}
