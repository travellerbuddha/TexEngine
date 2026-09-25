// The Price test's Explain ladder (PRICING_WORKSPACE_UX.md §3.13.1, §3.13.2, §3.19, D14; slice
// S14): the final price, then a table per block of nights (and one for the stay) with a row header
// per stage and "before" / "after" columns, the explanation steps as detail lines under their
// stage, and the caption "Stages are shown in the order the engine applies them." Every amount is a
// server string (explainLadder), formatted for display only; a chain break is logged in dev builds.
//
// useStepText says a step in the viewer's language: English viewers read the server's sentence
// with band codes shown as labels and room ids as room names (S16 review: "Garden Villa = Standard
// Sea View × 1.35", not the room type ids); other languages get rates.explain.<CODE> with the
// step's params (room ids as room names, bands as labels, numbers in their decimal mark) when the
// catalogue has that template, else the server's sentence as English viewers read it.
import { useCallback, useEffect, useId, useMemo, useState, type ReactNode } from "react"
import { useTexT } from "../../../i18n"
import { date as fmtDate, weekday } from "../../../lib/format"
import { Field, Money, Select } from "../../../ui"
import { enumLabel } from "../lib/options"
import type { ExplainStep, PreviewResult, Row } from "../lib/types"
import { decText } from "../lib/util"
import { bandCode } from "./bands.ts"
import { explainLadder, type LadderStage, type NightBlock } from "./explainLadder.ts"
import { bareBandCodes, isDecimalText, localNumber, parseChildLabel, parseOpText, withRoomNames } from "./explainText.ts"
import { decimalMarkOf } from "./matrixView.ts"
import { str } from "./rows.ts"
import type { BandLabels } from "./useBandLabels"

type Params = Record<string, string | number>

const CHILD_CODES = new Set(["CHILD_SLOT", "CHILD_INCLUDED"])

/** A step's sentence in the viewer's language (see the file comment). */
export function useStepText(labels: BandLabels, roomName: (roomType: string) => string): (step: ExplainStep) => string {
  const { t, has, lang, locale } = useTexT()
  const mark = decimalMarkOf(locale)
  const known = useMemo(() => new Set(labels.bands.map(bandCode).filter(Boolean)), [labels.bands])
  return useCallback(
    (s: ExplainStep) => {
      const codes = bareBandCodes(s.code, s.params ?? undefined, known)
      const key = `rates.explain.${s.code}`
      if (lang === "en" || !s.params || !has(key)) return withRoomNames(labels.display(s.text, codes), s.params, roomName)
      // a signed percentage ("+10", "-7,5") with the sign in front, the % where the language puts it
      const pct = (n: string) => {
        const sign = n.startsWith("-") ? "−" : n.startsWith("+") ? "+" : ""
        return t("rates.explain.op.pct", { sign, v: sign ? n.slice(1) : n })
      }
      const op = (v: string) => {
        const o = parseOpText(v)
        if (!o) return v
        const n = localNumber(o.value, mark)
        switch (o.kind) {
          case "abs":
            return `= ${n}`
          case "mul":
            return `× ${n}`
          case "add":
            return `+ ${n}`
          case "sub":
            return `− ${n}`
          case "pct_of":
            return t("rates.explain.op.pct_of", { v: n })
          case "pct":
            return pct(n)
          default:
            return t("rates.explain.op.inherit")
        }
      }
      const child = (v: string) => {
        const c = parseChildLabel(v)
        if (!c) return labels.display(v, codes)
        const age = c.months ? t("rates.explain.age_ym", { y: c.years, m: c.months }) : t("rates.explain.age_y", { y: c.years })
        const band = known.has(c.band.trim().toUpperCase()) ? labels.labelOf(c.band) : c.band
        return t("rates.explain.child_label", { n: c.n, age, band })
      }
      const out: Params = { currency: s.currency ?? "", night: s.night ? fmtDate(s.night, "short") : "" }
      for (const [k, v] of Object.entries(s.params)) {
        if (v === null || v === undefined) out[k] = ""
        else if (typeof v === "number") out[k] = v
        else if (typeof v === "boolean") out[k] = String(v)
        else if (k === "room" || k === "base") out[k] = roomName(v)
        else if (k === "op") out[k] = op(v)
        else if (k === "label" && CHILD_CODES.has(s.code)) out[k] = child(v)
        else if (k === "board") out[k] = enumLabel(t, "board", v)
        else if (k === "basis") out[k] = enumLabel(t, "basis", v)
        else if (k === "inc") out[k] = v ? t("rates.explain.p.included") : ""
        else if (k === "rate" && v === "fixed") out[k] = t("rates.explain.p.fixed")
        else if (k === "rate" && /^\d+(\.\d+)?%$/.test(v)) out[k] = pct(localNumber(v.slice(0, -1), mark))
        else if (isDecimalText(v)) out[k] = decText(v, 2)
        else out[k] = v
      }
      // plural counts, and a rate plan by its name
      if (s.code === "ROOM_BASIS") out.count = typeof s.params.included === "number" ? s.params.included : 0
      if (s.code === "RATE_PLAN_ADJUSTMENT" && s.rule?.label) out.code = s.rule.label
      return labels.display(t(key, out), codes)
    },
    [t, has, lang, mark, known, labels, roomName],
  )
}

export interface ExplainLadderViewProps {
  res: PreviewResult
  stepText: (step: ExplainStep) => string
  /** the version's periods (the Period stage names their dates) */
  periods: readonly Row[]
  /** minor units of the contract currency and of the sell currency */
  minorUnits: number
  sellMinorUnits: number
}

export function ExplainLadderView({ res, stepText, periods, minorUnits, sellMinorUnits }: ExplainLadderViewProps) {
  const { t } = useTexT()
  const ladder = useMemo(() => explainLadder(res), [res])
  const [night, setNight] = useState("")
  const titleId = useId()
  const nights = res.nights ?? []
  const sellCcy = res.currency ?? ""
  const contractCcy = res.contract?.currency ?? sellCcy
  const two = contractCcy !== sellCcy

  // the chain check (§3.13.1): a break is a server inconsistency, reported to developers only
  useEffect(() => {
    if (import.meta.env.DEV && ladder.chainBreaks.length) console.warn("Explain ladder: stages whose before is not the previous after", ladder.chainBreaks)
  }, [ladder])

  const fmt = (v: string | null, which: "contract" | "sell") => {
    if (v === null) return ""
    const text = decText(v, which === "sell" ? sellMinorUnits : minorUnits)
    return two ? `${text} ${which === "sell" ? sellCcy : contractCcy}` : text
  }
  const periodRange = (code: string) => {
    const p = periods.find((x) => str(x.period_code) === code)
    return p && str(p.start_date) && str(p.end_date) ? `${fmtDate(str(p.start_date), "short")}–${fmtDate(str(p.end_date), "short")}` : ""
  }
  const label = (s: LadderStage) => (s.id === "period_adjustment" ? t("rates.pt.stage.period_adjustment", { code: s.period?.code ?? "" }) : t(`rates.pt.stage.${s.id}`))
  const note = (s: LadderStage): ReactNode => {
    if (s.missing) return t("rates.pt.ladder.missing")
    switch (s.id) {
      case "period": {
        const range = periodRange(s.period?.code ?? "")
        return [s.period?.code, s.period?.name, range && `(${range})`].filter(Boolean).join(" · ")
      }
      case "room":
        return s.derived === false ? t("rates.pt.ladder.entered") : ""
      case "board":
        return s.included ? t("rates.pt.ladder.board_included") : s.supplement !== null && s.supplement !== undefined ? t("rates.pt.ladder.board_supplement", { amount: fmt(s.supplement, "contract") }) : ""
      case "fx":
        return s.rate ? t("rates.pt.ladder.fx_rate", { from: contractCcy, to: sellCcy, rate: decText(s.rate, 0) }) : ""
      case "tax":
        return s.included ? t("rates.pt.ladder.tax_included", { amount: fmt(s.tax ?? null, "sell") }) : t("rates.pt.ladder.tax", { amount: fmt(s.tax ?? null, "sell") })
      default:
        return ""
    }
  }

  const table = (key: string, title: string, stages: LadderStage[]) => (
    <table key={key} className="w-full border-collapse text-sm">
      <caption className="pb-1 text-left text-xs font-semibold tracking-wide text-zinc-600 uppercase">{title}</caption>
      <thead>
        <tr className="border-b border-zinc-200 text-xs text-zinc-500">
          <th scope="col" className="py-1 pr-3 text-left font-medium">
            {t("rates.pt.ladder.stage")}
          </th>
          <th scope="col" className="w-20 py-1 text-right font-medium sm:w-28">
            {t("rates.pt.ladder.before")}
          </th>
          <th scope="col" className="w-20 py-1 pl-2 text-right font-medium sm:w-28">
            {t("rates.pt.ladder.after")}
          </th>
        </tr>
      </thead>
      <tbody>
        {stages.map((s) => {
          const n = note(s)
          return [
            <tr key={s.id} data-stage={s.id} className="border-t border-zinc-100 align-top">
              <th scope="row" className="py-1.5 pr-3 text-left font-medium text-zinc-900">
                {label(s)}
                {n && <span className="block text-xs font-normal text-zinc-500">{n}</span>}
              </th>
              {s.amount ? (
                <>
                  <td className="py-1.5 text-right text-zinc-600 tabular-nums">{fmt(s.before, s.beforeCurrency)}</td>
                  <td className="py-1.5 pl-2 text-right font-medium text-zinc-900 tabular-nums">{fmt(s.after, s.afterCurrency)}</td>
                </>
              ) : (
                <td colSpan={2} className="py-1.5 text-right text-xs text-zinc-500">
                  {t("rates.pt.ladder.no_amount")}
                </td>
              )}
            </tr>,
            ...s.lines.map((l) => (
              <tr key={`${s.id}:${l.index}`} data-line={l.step.code} className="text-xs text-zinc-600">
                <td className="py-0.5 pr-3 pl-4">{stepText(l.step)}</td>
                <td className="py-0.5 text-right text-zinc-500 tabular-nums">{fmt(l.step.before, s.beforeCurrency)}</td>
                <td className="py-0.5 pl-2 text-right tabular-nums">{fmt(l.step.after, s.afterCurrency)}</td>
              </tr>
            )),
          ]
        })}
      </tbody>
    </table>
  )

  const blockTitle = (b: NightBlock, one?: number) =>
    one !== undefined || b.first === b.last
      ? t("rates.pt.ladder.night_block", { n: one ?? b.first, period: b.period })
      : t("rates.pt.ladder.nights_block", { from: b.first, to: b.last, period: b.period })
  const shown: { block: NightBlock; title: string }[] = night
    ? ladder.nights.filter((b) => b.dates.includes(night)).map((b) => ({ block: b, title: blockTitle(b, nights.findIndex((x) => x.date === night) + 1) }))
    : ladder.nights.map((b) => ({ block: b, title: blockTitle(b) }))

  return (
    <section aria-labelledby={titleId} className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 id={titleId} className="text-base font-semibold text-zinc-900">
            {t("rates.pt.ladder.title")}
          </h3>
          <p className="text-sm text-zinc-600">
            {t("rates.pt.ladder.final")} <span className="text-lg font-semibold text-zinc-950 tabular-nums">{<Money amount={res.totals?.total} currency={sellCcy} />}</span>
          </p>
        </div>
        {nights.length > 1 && (
          <Field label={t("rates.pt.ladder.night")} inline>
            <Select
              value={night}
              onChange={(e) => setNight(e.target.value)}
              options={[{ value: "", label: t("rates.preview.all_nights") }, ...nights.map((n, i) => ({ value: n.date, label: t("rates.pt.ladder.night_option", { n: i + 1, date: `${weekday(n.date)} ${fmtDate(n.date, "short")}` }) }))]}
              className="w-44"
            />
          </Field>
        )}
      </div>
      {shown.map(({ block, title }) => table(`n:${block.first}`, title, block.stages))}
      {ladder.stay.length > 0 && table("stay", t("rates.pt.ladder.stay"), ladder.stay)}
      <p className="text-xs text-zinc-500">{t("rates.pt.ladder.order")}</p>
    </section>
  )
}
