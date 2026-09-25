// Child age band labels and codes (PRICING_WORKSPACE_UX.md §3.8, D13). Band codes never reach the
// screen where a label exists: labels are shown instead, and codes printed in server text (rule
// labels such as "Child 1 [CHB] @2A+2C × 0.5", sweep messages, age-band issues) are replaced by
// labels on display. The child ages drawer's band edits (S11) are here too. Pure string handling;
// the only numbers are whole months of age (integer maths on the typed digits, §3.14 (f)).
// Runtime imports: rows.ts and shorthand.ts only.
import { normaliseDecimal } from "../lib/shorthand.ts"
import type { Tables } from "../lib/tables.ts"
import type { Row } from "../lib/types.ts"
import { newRow, str } from "./rows.ts"

/** A band as the editor holds it (an `age_bands` row: band_code, label, from_age, to_age, is_infant)
 * or as the server reports an inherited one (code, label, from_months, to_months, is_infant). */
export interface BandLike {
  /** an editor row's key (so an `age_bands` row is a BandLike) */
  _key?: string
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

// ─── the child ages drawer (§3.8, slice S11) ─────────────────────────────
// Ages are compared by the engine in whole months (ages.years_to_months: years × 12, rounded half
// up). The helpers below read and write the editor's years with integer maths on the digits only
// (ages are not money; §3.14 (f)): nothing is computed in binary floating point.

/** A band's age in years ("2.99", "7", 7) → whole months, rounded half up as the engine does
 * (ages.years_to_months); null for blank or unreadable text. */
export function ageMonths(years: unknown): number | null {
  const n = normaliseDecimal(str(years))
  if (!n.ok) return null
  const [ip, fp = ""] = n.value.split(".")
  const scale = 10 ** fp.length
  const frac = fp ? parseInt(fp, 10) : 0
  return parseInt(ip, 10) * 12 + Math.floor((frac * 24 + scale) / (2 * scale))
}

/** Whole months → years as the drawer shows and stores them (at most 2 decimals, canonical), so
 * that ageMonths gives the same months back: 36 → "3", 35 → "2.92", 30 → "2.5". */
export function monthsToYears(months: number): string {
  const m = Number.isInteger(months) && months > 0 ? months : 0
  const hundredths = Math.floor((m * 100 + 6) / 12)
  const ip = Math.floor(hundredths / 100)
  const fp = String(hundredths % 100).padStart(2, "0").replace(/0+$/, "")
  return fp ? `${ip}.${fp}` : String(ip)
}

/** Where a new band starts after one ending at `to` (years): the next whole year, so "2.99" → "3"
 * and "3" → "3" (the rule of the Child ages table). "0" for the first band. */
export function nextBandFrom(to: unknown): string {
  const n = normaliseDecimal(str(to))
  if (!n.ok) return "0"
  const [ip, fp = ""] = n.value.split(".")
  return String(parseInt(ip, 10) + (/[1-9]/.test(fp) ? 1 : 0))
}

/** A first band that starts at 0 and ends at 3 years or earlier is an infant band by default. */
export function defaultInfant(first: boolean, from: unknown, to: unknown): boolean {
  const a = ageMonths(from)
  const b = ageMonths(to)
  return first && a === 0 && b !== null && b > 0 && b <= 36
}

/** A band as price_matrix reports it (GAP-3): ages in months, the label as built (the code when
 * the band has none), where it comes from. */
export interface ServedBand {
  code: string
  label: string
  from_months: number
  to_months: number
  is_infant: boolean
  source: string
}

/** Served bands as the drawer and the ladder read bands: ages in years (monthsToYears). */
export function bandsFromMatrix(served: readonly ServedBand[]): (BandLike & { code: string; source: string })[] {
  return served.map((b) => ({
    code: str(b.code).toUpperCase(),
    label: str(b.label),
    from_age: monthsToYears(b.from_months),
    to_age: monthsToYears(b.to_months),
    is_infant: b.is_infant ? 1 : 0,
    source: str(b.source),
  }))
}

/** The bands that price this version's children: its own, or (it has none) the ones it inherits
 * from its pricing policy as the server reports them. */
export function effectiveBands(tables: Pick<Tables, "age_bands">, served: readonly ServedBand[] | undefined): readonly BandLike[] {
  return tables.age_bands.length ? tables.age_bands : bandsFromMatrix(served ?? [])
}

/** "Customise for this contract": the inherited bands become the version's own, with the same
 * codes (so inherited rules keep matching) and labels; a label equal to its code (the server's
 * fallback for a blank label) becomes the generated label. One edit. */
export function customiseBands<T extends Pick<Tables, "age_bands">>(tables: T, served: readonly ServedBand[], gen: (band: BandLike) => string): T {
  if (!served.length) return tables
  const age_bands = bandsFromMatrix(served).map((b) =>
    newRow("age_bands", { band_code: b.code, label: bandLabel(b, gen), from_age: str(b.from_age), to_age: str(b.to_age), is_infant: b.is_infant ? 1 : 0 }),
  )
  return { ...tables, age_bands }
}

/** A band typed in the drawer's new-band row. */
export interface BandDraft {
  /** the row key the band will have (the drawer renders the draft under it, so focus stays) */
  key: string
  label: string
  from: string
  to: string
  infant: boolean
}

/** Adds a band: the next free code (INF for an infant band, then CHA, CHB …), the label typed or
 * else the generated one, which is saved (D13). */
export function addBand<T extends Pick<Tables, "age_bands" | "occupancy_rules">>(tables: T, draft: BandDraft, gen: (band: BandLike) => string): T {
  const fields = { from_age: str(draft.from), to_age: str(draft.to), is_infant: draft.infant ? 1 : 0 }
  const label = str(draft.label) || gen(fields)
  const row: Row = { ...newRow("age_bands", { band_code: nextBandCode(tables, { infant: draft.infant }), label, ...fields }), _key: draft.key }
  return { ...tables, age_bands: [...tables.age_bands, row] }
}

export type BandPatch = Partial<Record<"label" | "from_age" | "to_age" | "is_infant", string | number>>

/** Commits a change of one band. A label the user typed stays; a generated label (it equals the
 * generated label of the band as it was) follows the new ages; a label left blank is written as
 * the generated one (D13). The same tables when nothing changes. */
export function updateBand<T extends Pick<Tables, "age_bands">>(tables: T, key: string, patch: BandPatch, gen: (band: BandLike) => string): T {
  const i = tables.age_bands.findIndex((b) => b._key === key)
  if (i < 0) return tables
  const old = tables.age_bands[i]
  const next: Row = { ...old, ...patch }
  const typed = patch.label !== undefined ? str(patch.label) : str(old.label)
  const auto = patch.label === undefined && (!typed || typed === gen(old) || typed.toUpperCase() === bandCode(old))
  next.label = auto || !typed ? gen(next) : typed
  const same = (["label", "from_age", "to_age", "is_infant"] as const).every((k) => str(next[k]) === str(old[k]))
  if (same) return tables
  const age_bands = [...tables.age_bands]
  age_bands[i] = next
  return { ...tables, age_bands }
}

const unnamed = (b: Row) => !str(b.label) || str(b.label).toUpperCase() === bandCode(b)

/** Bands without a name of their own (blank, or the code): "2 bands have no name". */
export function unnamedBands(tables: Pick<Tables, "age_bands">): number {
  return tables.age_bands.filter(unnamed).length
}

/** "Name them": the generated label for every band without a name, in one edit. */
export function nameBands<T extends Pick<Tables, "age_bands">>(tables: T, gen: (band: BandLike) => string): T {
  if (!tables.age_bands.some(unnamed)) return tables
  return { ...tables, age_bands: tables.age_bands.map((b) => (unnamed(b) ? { ...b, label: gen(b) } : b)) }
}

/** The occupancy rules that name a band code (case-insensitive, as the engine reads codes). */
export function bandRuleCount(tables: Pick<Tables, "occupancy_rules">, code: string): number {
  const c = str(code).toUpperCase()
  return c ? tables.occupancy_rules.filter((r) => str(r.age_band).toUpperCase() === c).length : 0
}

/** Removes a band, and the occupancy rules that name its code (unless another band keeps the
 * code): they could never apply again. */
export function removeBand<T extends Pick<Tables, "age_bands" | "occupancy_rules">>(tables: T, key: string): { tables: T; counts: { rules: number } } {
  const band = tables.age_bands.find((b) => b._key === key)
  if (!band) return { tables, counts: { rules: 0 } }
  const code = bandCode(band)
  const age_bands = tables.age_bands.filter((b) => b !== band)
  const kept = age_bands.some((b) => bandCode(b) === code)
  const occupancy_rules = kept || !code ? tables.occupancy_rules : tables.occupancy_rules.filter((r) => str(r.age_band).toUpperCase() !== code)
  return { tables: { ...tables, age_bands, occupancy_rules }, counts: { rules: tables.occupancy_rules.length - occupancy_rules.length } }
}

export interface BandSegment {
  code: string
  band: BandLike
  from: number
  to: number
}

export interface BandCoverage {
  /** valid bands on the month scale, sorted as the server check sorts them */
  segments: BandSegment[]
  /** months no band covers between two bands, and months two bands both cover */
  gaps: { from: number; to: number; codes: [string, string] }[]
  overlaps: { from: number; to: number; codes: [string, string] }[]
  /** codes of bands that end where or before they start */
  invalid: string[]
  /** the first month a band covers (above 0: younger children match no band) and the last */
  start: number
  end: number
}

/** The AgeStrip's reading of the bands, in months, as ages.band_findings reads them (sorted by
 * start, end and code; each pair of neighbours compared). The server check stays the authority. */
export function bandCoverage(bands: readonly BandLike[]): BandCoverage {
  const all = bands.map((band) => ({ code: bandCode(band), band, from: ageMonths(band.from_age ?? "0") ?? 0, to: ageMonths(band.to_age) ?? 0 }))
  all.sort((a, b) => a.from - b.from || a.to - b.to || (a.code < b.code ? -1 : a.code > b.code ? 1 : 0))
  const invalid = all.filter((s) => s.from < 0 || s.to <= s.from).map((s) => s.code)
  const segments = all.filter((s) => s.from >= 0 && s.to > s.from)
  const gaps: BandCoverage["gaps"] = []
  const overlaps: BandCoverage["overlaps"] = []
  for (let i = 1; i < segments.length; i++) {
    const a = segments[i - 1]
    const b = segments[i]
    if (b.from < a.to) overlaps.push({ from: b.from, to: Math.min(a.to, b.to), codes: [a.code, b.code] })
    else if (b.from > a.to) gaps.push({ from: a.to, to: b.from, codes: [a.code, b.code] })
  }
  return {
    segments,
    gaps,
    overlaps,
    invalid,
    start: segments.length ? segments[0].from : 0,
    end: segments.reduce((m, s) => (s.to > m ? s.to : m), 0),
  }
}
