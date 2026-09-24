// Child age band labels and codes (PRICING_WORKSPACE_UX.md §3.8, D13). Band codes never reach the
// screen where a label exists: labels are shown instead, and codes printed in server text (rule
// labels such as "Child 1 [CHB] @2A+2C × 0.5", sweep messages, age-band issues) are replaced by
// labels on display. Pure string handling, no maths; runtime imports: rows.ts and shorthand.ts only.
import { normaliseDecimal } from "../lib/shorthand.ts"
import type { Tables } from "../lib/tables.ts"
import type { Row } from "../lib/types.ts"
import { str } from "./rows.ts"

/** A band as the editor holds it (an `age_bands` row: band_code, label, from_age, to_age, is_infant)
 * or as the server reports an inherited one (code, label, from_months, to_months, is_infant). */
export interface BandLike {
  band_code?: string | number | null
  code?: string | null
  label?: string | number | null
  from_age?: string | number | null
  to_age?: string | number | null
  is_infant?: number | boolean | string | null
}

/** The i18n descriptor of a generated label: "Infant {from}–{to}" or "Child {from}–{to}". */
export interface GeneratedLabel {
  key: "rates.bands.label_infant" | "rates.bands.label_child"
  params: { from: string; to: string }
}

/** The band's code as the engine reads it (trimmed, upper case). */
export function bandCode(band: BandLike): string {
  return str(band.band_code ?? band.code).toUpperCase()
}

function ageText(v: unknown): string {
  const s = str(v)
  const n = normaliseDecimal(s)
  return n.ok ? n.value : s
}

/** The generated label of a band from its ages in years, as typed (canonical decimal strings,
 * "7.00" → "7"; nothing is computed). */
export function generatedLabel(band: BandLike): GeneratedLabel {
  const infant = band.is_infant === 1 || band.is_infant === true || band.is_infant === "1"
  return { key: infant ? "rates.bands.label_infant" : "rates.bands.label_child", params: { from: ageText(band.from_age), to: ageText(band.to_age) } }
}

/** The band's label, or `gen(band)` when the label is blank or equals the code (the server falls
 * back to the code for a blank label, contracts.age_bands_of). */
export function bandLabel(band: BandLike, gen: (band: BandLike) => string): string {
  const label = str(band.label)
  if (!label || label.toUpperCase() === bandCode(band)) return gen(band)
  return label
}

const TOKEN = "A-Za-z0-9_"

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

/** Replaces band codes in server text by labels:
 * - always `[CODE]` → `[label]` for every known band (rule labels, sweep messages);
 * - with `codes` (an issue's ref.age_band / ref.age_bands, or every band code for a NO_CHILD_RULE
 *   reason), also every whole-token occurrence of those codes (no letter, digit or underscore on
 *   either side): "age bands CHA and CHB overlap" → "age bands Child 3–6.99 and Child 7–11.99 overlap".
 * Codes are matched as the server prints them (upper case). Unknown codes (OCC_UNKNOWN_BAND) have
 * no label and stay. One pass over the text, so a replaced label is never replaced again. */
export function displayBandCodes(
  text: string,
  bands: readonly BandLike[],
  opts: { codes?: readonly string[]; labelOf: (code: string, band: BandLike) => string },
): string {
  if (!text) return text
  const known = new Map<string, BandLike>()
  for (const b of bands) {
    const c = bandCode(b)
    if (c && !known.has(c)) known.set(c, b)
  }
  if (known.size === 0) return text
  const byLength = (a: string, b: string) => b.length - a.length || (a < b ? -1 : a > b ? 1 : 0)
  const all = [...known.keys()].sort(byLength).map(escapeRe)
  const tokens = [...new Set((opts.codes ?? []).map((c) => str(c).toUpperCase()))].filter((c) => known.has(c)).sort(byLength).map(escapeRe)
  const parts = [`\\[(${all.join("|")})\\]`]
  if (tokens.length) parts.push(`(?<![${TOKEN}])(${tokens.join("|")})(?![${TOKEN}])`)
  const re = new RegExp(parts.join("|"), "g")
  return text.replace(re, (_m, bracket: string | undefined, token: string | undefined) => {
    const code = bracket ?? token ?? ""
    const band = known.get(code)
    if (!band) return _m
    const label = opts.labelOf(code, band)
    return bracket !== undefined ? `[${label}]` : label
  })
}

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

/** The next free band code: INF, CHA, CHB, … CHZ, then CH27, CH28, … A code still named by an
 * occupancy rule (an orphan reference) is not free: reusing it would silently attach those rules
 * to the new band. `infant: false` skips INF. */
export function nextBandCode(tables: Pick<Tables, "age_bands" | "occupancy_rules">, opts?: { infant?: boolean }): string {
  const used = new Set<string>()
  for (const b of tables.age_bands) used.add(str(b.band_code).toUpperCase())
  for (const r of tables.occupancy_rules) used.add(str(r.age_band).toUpperCase())
  const candidates = [...(opts?.infant === false ? [] : ["INF"]), ...LETTERS.split("").map((c) => `CH${c}`)]
  for (const c of candidates) if (!used.has(c)) return c
  for (let n = 27; ; n++) if (!used.has(`CH${n}`)) return `CH${n}`
}

export type RenameBandResult<T> = { tables: T; counts: { rules: number } } | { error: "BLANK_CODE" | "DUPLICATE_CODE" | "UNKNOWN_BAND" }

/** Renames a band code (the Advanced disclosure of the bands drawer) and rewrites every occupancy
 * rule naming it (codes compare case-insensitively, as the engine reads them upper-cased). */
export function renameBandCode<T extends Pick<Tables, "age_bands" | "occupancy_rules">>(tables: T, oldCode: string, newCode: string): RenameBandResult<T> {
  const from = str(oldCode).toUpperCase()
  const to = str(newCode).toUpperCase()
  if (!to) return { error: "BLANK_CODE" }
  if (!tables.age_bands.some((b) => str(b.band_code).toUpperCase() === from)) return { error: "UNKNOWN_BAND" }
  if (to === from) return { tables, counts: { rules: 0 } }
  if (tables.age_bands.some((b) => str(b.band_code).toUpperCase() === to)) return { error: "DUPLICATE_CODE" }
  let rules = 0
  const occupancy_rules = tables.occupancy_rules.map((r): Row => {
    if (str(r.age_band).toUpperCase() !== from) return r
    rules += 1
    return { ...r, age_band: to }
  })
  const age_bands = tables.age_bands.map((b): Row => (str(b.band_code).toUpperCase() === from ? { ...b, band_code: to } : b))
  return { tables: { ...tables, age_bands, occupancy_rules: rules ? occupancy_rules : tables.occupancy_rules }, counts: { rules } }
}
