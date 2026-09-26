// The Adjust… popover of the room price matrix (PRICING_WORKSPACE_UX.md §3.10, §1.4 "a preview
// before, an undo after", D2, O5; slice S10): a non-modal Popover with the op (+%, −%, +amount,
// −amount, ×) and the value, focused on open. It changes the selected entered prices (manual and
// fixed-override cells, in any row); formula cells are skipped and counted. The preview is the
// server's: apply_op_values is asked with the prices as they are now, 250 ms after the last
// keystroke, and lists the first 8 "before → after" lines of the prices that change, "+N more",
// and the prices it refuses. Apply is disabled while the preview is pending, when nothing changes
// or when a price is refused; it commits the server's amounts as ABSOLUTE in one history entry.
// The client computes no amount.
import { useEffect, useMemo, useState, type RefObject } from "react"
import { Loader2 } from "lucide-react"
import { tex, TexApiError } from "../../../lib/api"
import { useTexT } from "../../../i18n"
import { Button, DECIMAL_PLACES, DecimalInput, Field, Popover, Segmented } from "../../../ui"
import type { Tables } from "../lib/tables"
import type { ApplyOpResult } from "../lib/types"
import { ADJUST_KINDS, ADJUST_PREVIEW_LINES, adjustCalls, adjustPreview, adjustRule, adjustTargets, answersInOrder, isAmountKind, type AdjustKind, type AdjustTarget } from "./bulk.ts"
import type { AdjustAnswer, CellRef } from "./matrixView.ts"

/** The preview debounce after a keystroke (§3.10). */
export const ADJUST_DEBOUNCE_MS = 250

export interface AdjustPopoverProps {
  anchorRef: RefObject<HTMLElement | null>
  onClose: () => void
  /** the version (apply_op_values' `version`) */
  version: string
  /** the tables as they are now (the targets and their prices follow them) */
  tables: Tables
  /** the cells selected when the popover opened */
  cells: CellRef[]
  minorUnits: number
  ccy: string
  /** "Standard · P1" */
  cellName: (cell: CellRef) => string
  /** an amount in the currency's decimals (display only) */
  amount: (v: string) => string
  /** commits the answers; a refusal comes back as the message to show */
  onApply: (targets: AdjustTarget[], answers: AdjustAnswer[], count: number) => string | void
}

interface Answered {
  key: string
  answers?: AdjustAnswer[]
  error?: string
}

export function AdjustPopover(p: AdjustPopoverProps) {
  const { t } = useTexT()
  const [kind, setKind] = useState<AdjustKind>("up_pct")
  const [text, setText] = useState("")
  const [answered, setAnswered] = useState<Answered | null>(null)
  const [refusal, setRefusal] = useState<string>()
  const { targets, formulas, others } = useMemo(() => adjustTargets(p.tables, p.cells), [p.tables, p.cells])
  const rule = adjustRule(kind, text, p.minorUnits)
  // what the preview is for: the op, the value and every price as it is now
  const key = rule.ok && targets.length ? JSON.stringify([rule.op, rule.value, targets.map((x) => [x.cell.room, x.cell.period, x.current])]) : ""

  useEffect(() => {
    if (!key || !rule.ok) return
    const ctl = new AbortController()
    const timer = window.setTimeout(async () => {
      const calls = adjustCalls(targets, rule.op, rule.value)
      try {
        const results = await Promise.all(
          calls.map((c) => tex<ApplyOpResult[]>("contracts", "apply_op_values", { version: p.version, values: c.values, op: c.op, value: c.value }, { post: true, signal: ctl.signal })),
        )
        setAnswered({ key, answers: answersInOrder(calls, results, targets.length) })
      } catch (e) {
        if ((e as Error).name === "AbortError") return
        setAnswered({ key, error: e instanceof TexApiError || e instanceof Error ? e.message : String(e) })
      }
    }, ADJUST_DEBOUNCE_MS)
    return () => {
      window.clearTimeout(timer)
      ctl.abort()
    }
    // `key` holds the op, the value and the targets' prices
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, p.version])

  const current = answered && answered.key === key ? answered : null
  const pending = Boolean(key) && !current
  const preview = current?.answers ? adjustPreview(targets, current.answers) : null
  const valueError = !rule.ok && rule.code !== "BLANK" ? t(`rates.sh.err.${rule.code}`) : undefined
  const ready = Boolean(preview && preview.changes.length > 0 && preview.errors.length === 0 && !pending)
  const suffix = kind === "up_pct" || kind === "down_pct" ? "%" : kind === "times" ? "×" : p.ccy
  const opLabel = (k: AdjustKind) => t(`rates.ws.adjust.op.${k}`)

  const apply = () => {
    if (!ready || !current?.answers) return
    const r = p.onApply(targets, current.answers, preview?.changes.length ?? 0)
    if (r) setRefusal(r)
  }

  return (
    <Popover open onClose={p.onClose} anchorRef={p.anchorRef} label={t("rates.ws.adjust.title")} width="lg">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          apply()
        }}
      >
        <Segmented<AdjustKind>
          size="sm"
          label={t("rates.ws.adjust.op_label")}
          value={kind}
          onChange={(k) => {
            setKind(k)
            setRefusal(undefined)
          }}
          options={ADJUST_KINDS.map((k) => ({ value: k, label: opLabel(k) }))}
        />
        <Field label={t("rates.f.value")} required error={valueError} hint={isAmountKind(kind) ? t("rates.ws.adjust.amount_hint", { ccy: p.ccy }) : undefined}>
          <DecimalInput
            data-autofocus
            value={text}
            onValueChange={(v) => {
              setText(v)
              setRefusal(undefined)
            }}
            decimals={DECIMAL_PLACES}
            suffix={suffix}
          />
        </Field>
        <p className="text-xs text-zinc-600">
          {t("rates.ws.adjust.targets", { count: targets.length })}
          {formulas > 0 && <> · {t("rates.ws.adjust.skipped_formulas", { count: formulas })}</>}
          {others > 0 && <> · {t("rates.ws.adjust.skipped_other", { count: others })}</>}
        </p>
        <div role="status" aria-live="polite" className="min-h-10 rounded-md bg-zinc-50 px-2.5 py-2 text-sm text-zinc-800">
          {!targets.length ? (
            <span className="text-zinc-600">{t("rates.ws.adjust.no_targets")}</span>
          ) : !rule.ok ? (
            <span className="text-zinc-500">{t("rates.ws.adjust.enter_value")}</span>
          ) : pending ? (
            <span className="inline-flex items-center gap-1.5 text-zinc-600">
              <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
              {t("rates.ws.adjust.calculating")}
            </span>
          ) : current?.error ? (
            <span className="text-rose-800">{current.error}</span>
          ) : preview ? (
            <AdjustLines preview={preview} cellName={p.cellName} amount={p.amount} />
          ) : null}
        </div>
        {refusal && (
          <p role="alert" className="text-sm text-rose-800">
            {refusal}
          </p>
        )}
        <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
          <Button variant="secondary" size="sm" onClick={p.onClose}>
            {t("core.action.cancel")}
          </Button>
          <Button size="sm" type="submit" disabled={!ready}>
            {t("core.action.apply")}
          </Button>
        </div>
      </form>
    </Popover>
  )
}

function AdjustLines({ preview, cellName, amount }: { preview: NonNullable<ReturnType<typeof adjustPreview>>; cellName: (c: CellRef) => string; amount: (v: string) => string }) {
  const { t } = useTexT()
  const shown = preview.changes.slice(0, ADJUST_PREVIEW_LINES)
  const more = preview.changes.length - shown.length
  return (
    <div className="space-y-1">
      {preview.errors.length > 0 && (
        <ul className="space-y-0.5 text-rose-800">
          {preview.errors.slice(0, ADJUST_PREVIEW_LINES).map((e) => (
            <li key={`${e.cell.room}|${e.cell.period}`}>{t("rates.ws.bulk_error", { cell: cellName(e.cell), error: t(`rates.sh.err.${e.code}`) })}</li>
          ))}
          {preview.errors.length > ADJUST_PREVIEW_LINES && <li>{t("rates.ws.adjust.more", { count: preview.errors.length - ADJUST_PREVIEW_LINES })}</li>}
        </ul>
      )}
      {shown.length === 0 && preview.errors.length === 0 && <p className="text-zinc-600">{t("rates.ws.adjust.nothing")}</p>}
      {shown.length > 0 && (
        <ul className="space-y-0.5 tabular-nums">
          {shown.map((c) => (
            <li key={`${c.cell.room}|${c.cell.period}`}>{t("rates.ws.adjust.line", { cell: cellName(c.cell), before: amount(c.before), after: amount(c.after) })}</li>
          ))}
          {more > 0 && <li className="text-zinc-600">{t("rates.ws.adjust.more", { count: more })}</li>}
        </ul>
      )}
      {preview.unchanged > 0 && <p className="text-xs text-zinc-500">{t("rates.ws.adjust.unchanged", { count: preview.unchanged })}</p>}
    </div>
  )
}
