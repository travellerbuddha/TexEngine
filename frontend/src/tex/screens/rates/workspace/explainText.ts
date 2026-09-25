// Reading the server's explanation parameters for the Price test's localised sentences
// (PRICING_WORKSPACE_UX.md §3.13.2, §3.20; slice S14). The engine explains every step with an
// English template and its parameters (explain.py): decimals as exact strings, a rule's operation
// as describe_op prints it ("× 1.35", "50% of", "+10%", "= 245.00", "+ 10.00", "− 5.00", "inherit")
// and a child as occupancy.py labels it ("Child 1 (8y, CHB)", "Child 2 (11y11m, Child 7–11.99)").
// These functions split those strings so the screen can say them in the viewer's language, with
// room names and band labels. String handling only: no number is converted or computed.
// Pure: no runtime imports.

/** A decimal parameter as the server sends it (to_str_param: digits, a point, at least one decimal). */
export function isDecimalText(v: unknown): v is string {
  return typeof v === "string" && /^-?\d+\.\d+$/.test(v)
}

/** A number as typed by describe_op or display ("1.35", "10", "0.333333333") in the viewer's decimal
 * mark; the digits are kept as they are. */
export function localNumber(s: string, mark: "." | ","): string {
  return mark === "," ? s.replace(".", ",") : s
}

export type OpKind = "abs" | "mul" | "pct_of" | "pct" | "add" | "sub" | "inherit"

export interface OpText {
  kind: OpKind
  /** the number as printed (sign kept for "pct": "+10", "-7.5") */
  value: string
}

const NUM = "(-?\\d+(?:\\.\\d+)?)"
const OP_FORMS: [RegExp, OpKind][] = [
  [new RegExp(`^= ${NUM}$`), "abs"],
  [new RegExp(`^× ${NUM}$`), "mul"],
  [new RegExp(`^${NUM}% of$`), "pct_of"],
  [/^([+-]\d+(?:\.\d+)?)%$/, "pct"],
  [new RegExp(`^\\+ ${NUM}$`), "add"],
  [new RegExp(`^− ${NUM}$`), "sub"],
]

/** A describe_op string split into its kind and number; null for anything else (then it is shown
 * as the server wrote it). */
export function parseOpText(s: unknown): OpText | null {
  if (typeof s !== "string") return null
  if (s === "inherit") return { kind: "inherit", value: "" }
  for (const [re, kind] of OP_FORMS) {
    const m = re.exec(s)
    if (m) return { kind, value: m[1] }
  }
  return null
}

export interface ChildLabel {
  /** the child's position ("Child 1") */
  n: number
  years: number
  months: number
  /** the band's label as the engine printed it: its label, or its code when it has none */
  band: string
}

/** occupancy.py's child label "Child {position} ({y}y[{m}m], {band label or code})". */
export function parseChildLabel(s: unknown): ChildLabel | null {
  if (typeof s !== "string") return null
  const m = /^Child (\d+) \((\d+)y(?:(\d+)m)?, (.+)\)$/.exec(s)
  if (!m) return null
  return { n: parseInt(m[1], 10), years: parseInt(m[2], 10), months: m[3] ? parseInt(m[3], 10) : 0, band: m[4] }
}

/** The band codes a step's sentence may print bare (not in brackets), for the token rule of
 * displayBandCodes: a child step's band when the engine printed its code (the band has no label).
 * Bracketed codes (rule labels) are replaced for every known band anyway. */
export function bareBandCodes(code: string, params: Record<string, unknown> | undefined, known: ReadonlySet<string>): string[] {
  if (code !== "CHILD_SLOT" && code !== "CHILD_INCLUDED") return []
  const child = parseChildLabel(params?.label)
  const band = child?.band.trim().toUpperCase()
  return band && known.has(band) ? [band] : []
}

/** The server's sentence with the step's room ids (its `room` and `base` params) as room names; the
 * longer id first, and an id only where it is not part of a longer word. Text handling only. */
export function withRoomNames(text: string, params: Record<string, unknown> | null | undefined, roomName: (roomType: string) => string): string {
  const ids = [params?.room, params?.base].filter((v): v is string => typeof v === "string" && v !== "" && roomName(v) !== v)
  let out = text
  for (const id of [...new Set(ids)].sort((a, b) => b.length - a.length)) {
    const re = new RegExp(`(?<![\\w-])${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![\\w-])`, "g")
    out = out.replace(re, () => roomName(id))
  }
  return out
}
