// Band labels bound to the viewer's language (PRICING_WORKSPACE_UX.md §3.8, D13; slice S11). The
// pure bands.ts decides what a band is called and where codes stand in server text; this binds its
// generated labels ("Infant 0–2.99", "Child 3–6.99") to t(), in the viewer's decimal mark. Used by
// the occupancy ladder, the child ages drawer and the rule popover, and later by the combination
// cards (S12), the price test (S14) and the issue lists (S15): a band code is never rendered where a
// label exists.
import { useCallback, useMemo } from "react"
import { useTexT } from "../../../i18n"
import { bandCode, bandLabel, displayBandCodes, generatedLabel, type BandLike } from "./bands.ts"
import { decimalMarkOf } from "./matrixView.ts"

export interface BandLabels {
  /** the bands the labels come from (the version's, or the inherited ones) */
  bands: readonly BandLike[]
  /** the generated label of a band in the viewer's language ("Child 3–6.99"), whatever its label */
  gen: (band: BandLike) => string
  /** a band's label (its own, else the generated one); the code itself when no band has it */
  labelOf: (code: string) => string
  /** server text with its band codes shown as labels: `[CODE]` always, bare codes only when
   * `codes` names them (an issue's ref, or every code for a NO_CHILD_RULE reason) */
  display: (text: string, codes?: readonly string[]) => string
}

export function useBandLabels(bands: readonly BandLike[]): BandLabels {
  const { t, locale } = useTexT()
  const mark = decimalMarkOf(locale)
  const gen = useCallback(
    (band: BandLike) => {
      const g = generatedLabel(band)
      const local = (s: string) => (mark === "," ? s.replace(".", ",") : s)
      return t(g.key, { from: local(g.params.from), to: local(g.params.to) })
    },
    [t, mark],
  )
  const byCode = useMemo(() => {
    const m = new Map<string, BandLike>()
    for (const b of bands) {
      const c = bandCode(b)
      if (c && !m.has(c)) m.set(c, b)
    }
    return m
  }, [bands])
  const labelOf = useCallback(
    (code: string) => {
      const c = String(code ?? "").trim().toUpperCase()
      const band = byCode.get(c)
      return band ? bandLabel(band, gen) : c
    },
    [byCode, gen],
  )
  const display = useCallback(
    (text: string, codes?: readonly string[]) => displayBandCodes(text, bands, { codes, labelOf: (_code, band) => bandLabel(band, gen) }),
    [bands, gen],
  )
  return useMemo(() => ({ bands, gen, labelOf, display }), [bands, gen, labelOf, display])
}
