// Shorthand entry for the Pricing Workspace grids (PRICING_WORKSPACE_UX.md §3.4, D4, D10, O1–O5).
//
// Pure and deterministic: no runtime imports, erasable TypeScript only (tested with `node --test`),
// and no number conversion. Values stay decimal strings from the keyboard to the server; nothing
// here does arithmetic, it only parses, canonicalises and formats text. The parser is
// locale-independent: `.` and `,` are both the decimal mark and grouping separators never exist.
// Its output depends only on the text, the grid context and the currency's minor units, never on
// the cell's current value.

/** The rule operations the DocTypes store (`TEX Period Rate`, `TEX Occupancy Rule`, ...). */
export type ShOp = "ABSOLUTE" | "FIXED" | "MULTIPLY" | "PERCENT_OF" | "ADJUST_PERCENT" | "ADD" | "SUBTRACT" | "INHERIT"

/** The grid a cell belongs to: period_rates, occupancy_rules, boards or periods.adjustment_op. */
export type ShContext = "room" | "occupancy" | "board" | "period_adjust"

export type ShErrorCode = "SYNTAX" | "PLACES" | "DIGITS" | "RANGE" | "AMBIGUOUS" | "OP_NOT_ALLOWED"

export type ShResult =
  | { ok: true; kind: "rule"; op: ShOp; value: string }
  | { ok: true; kind: "clear" }
  | { ok: true; kind: "base" }
  | { ok: false; code: ShErrorCode; op?: ShOp }

export type ShParseOptions = {
  /** Minor units of the contract currency (`contract_doc.minor_units`, money.minor_units). Default 2. */
  minorUnits?: number
}

export type ShFormatOptions = {
  /** The viewer's decimal mark; the canonical value always uses ".". */
  decimalMark?: "." | ","
  /** The minor units the text will be parsed with again (only editText uses it). Default 2. */
  minorUnits?: number
}

export type ShDecimal = { ok: true; value: string } | { ok: false; code: ShErrorCode }

/** Allowed ops per context: the DocTypes' `Select` options. */
export const OPS_BY_CONTEXT: Readonly<Record<ShContext, readonly ShOp[]>> = Object.freeze({
  room: Object.freeze<ShOp[]>(["ABSOLUTE", "MULTIPLY", "ADJUST_PERCENT", "PERCENT_OF", "ADD", "SUBTRACT", "INHERIT"]),
  occupancy: Object.freeze<ShOp[]>(["ABSOLUTE", "MULTIPLY", "ADJUST_PERCENT", "PERCENT_OF", "ADD", "SUBTRACT", "INHERIT", "FIXED"]),
  board: Object.freeze<ShOp[]>(["ADD", "ADJUST_PERCENT", "ABSOLUTE"]),
  period_adjust: Object.freeze<ShOp[]>(["ADJUST_PERCENT", "MULTIPLY", "ADD", "SUBTRACT"]),
})

/** The (context, op) pairs whose value is a money amount (the AMBIGUOUS guard applies to them).
 * FIXED is a fixed slot price, so it is an amount too; only the advanced popover produces it. */
export const AMOUNT_OPS: Readonly<Record<ShContext, readonly ShOp[]>> = Object.freeze({
  room: Object.freeze<ShOp[]>(["ABSOLUTE", "ADD", "SUBTRACT"]),
  occupancy: Object.freeze<ShOp[]>(["ABSOLUTE", "FIXED", "ADD", "SUBTRACT"]),
  board: Object.freeze<ShOp[]>(["ABSOLUTE", "ADD"]),
  period_adjust: Object.freeze<ShOp[]>(["ADD", "SUBTRACT"]),
})

export function isAmountOp(ctx: ShContext, op: ShOp): boolean {
  return AMOUNT_OPS[ctx].includes(op)
}

const MAX_INPUT_LENGTH = 40
const MAX_PLACES = 9 // money.DB_PLACES (ADR-055)
const MAX_INTEGER_DIGITS = 12 // DECIMAL(21, 9)
const MAX_SIGNIFICANT_DIGITS = 15 // money.DB_SAFE_DIGITS
const DEFAULT_MINOR_UNITS = 2 // money.minor_units default

const MUL = "\u00d7" // the multiply marker after normalisation
const NUM = "([0-9]+)(?:[.,]([0-9]+))?" // ASCII digits, at most one decimal mark, never leading or trailing

// The grammar of §3.4.3 after normalisation; spaces only after a prefix and before "%".
const RE_ABSOLUTE = new RegExp(`^(?:= *)?${NUM}$`)
const RE_MULTIPLY = new RegExp(`^${MUL} *${NUM}$`)
const RE_PERCENT_OF = new RegExp(`^${NUM} *%$`)
const RE_ADJUST_PERCENT = new RegExp(`^([+-]) *${NUM} *%$`)
const RE_ADD = new RegExp(`^\\+ *${NUM}$`)
const RE_SUBTRACT = new RegExp(`^- *${NUM}$`)
const RE_BASE = /^base$/i
const RE_DECIMAL = new RegExp(`^([+-]?)${NUM}$`)

function minorUnitsOf(opts: { minorUnits?: number } | undefined): number {
  const mu = opts?.minorUnits
  return typeof mu === "number" && mu >= 0 ? mu : DEFAULT_MINOR_UNITS
}

/** Trims ASCII spaces only (a tab or line break must still reach the SYNTAX check). Linear, so a
 * long pasted run of spaces cannot make the regex engine backtrack. */
function trimSpaces(s: string): string {
  let start = 0
  let end = s.length
  while (start < end && s.charCodeAt(start) === 32) start++
  while (end > start && s.charCodeAt(end - 1) === 32) end--
  return s.slice(start, end)
}

/** Checks the limits and returns the canonical magnitude (no sign) of `int[.frac]` as typed. */
function canonicalMagnitude(intTyped: string, fracTyped: string, amount: boolean, minorUnits: number): ShDecimal {
  const int = intTyped.replace(/^0+/, "") || "0"
  const frac = fracTyped.replace(/0+$/, "")
  if (frac.length > MAX_PLACES) return { ok: false, code: "PLACES" }
  if (int.length > MAX_INTEGER_DIGITS) return { ok: false, code: "RANGE" }
  const significant = int === "0" ? frac.replace(/^0+/, "").length : int.length + frac.length
  if (significant > MAX_SIGNIFICANT_DIGITS) return { ok: false, code: "DIGITS" }
  // O5: "1.500" typed as an amount in a 0/2-decimal currency is refused, never read as 1.5. The
  // integer part is judged by its value (leading zeros do not hide it), the fraction as typed.
  if (amount && minorUnits < 3 && int !== "0" && int.length <= 3 && fracTyped.length === 3) {
    return { ok: false, code: "AMBIGUOUS" }
  }
  return { ok: true, value: frac ? `${int}.${frac}` : int }
}

/** Canonical decimal string: leading integer zeros and trailing fraction zeros stripped, "." as the
 * mark, an optional sign kept (never "-0"). `amount` applies the AMBIGUOUS guard (O5). Also used
 * to compare server decimal strings ("216.000000" = "216") without arithmetic. */
export function normaliseDecimal(text: string, opts?: { amount?: boolean; minorUnits?: number }): ShDecimal {
  const m = RE_DECIMAL.exec(trimSpaces(text))
  if (!m) return { ok: false, code: "SYNTAX" }
  const r = canonicalMagnitude(m[2], m[3] ?? "", opts?.amount === true, minorUnitsOf(opts))
  if (!r.ok) return r
  return { ok: true, value: m[1] === "-" && r.value !== "0" ? `-${r.value}` : r.value }
}

type Form = { op: ShOp; negative: boolean; int: string; frac: string }

/** Matches the grammar and maps the form to the op of `ctx` (§3.4.4, the owner's table). */
function matchForm(s: string, ctx: ShContext): Form | null {
  let m: RegExpExecArray | null
  if ((m = RE_ABSOLUTE.exec(s))) return { op: "ABSOLUTE", negative: false, int: m[1], frac: m[2] ?? "" }
  if ((m = RE_MULTIPLY.exec(s))) return { op: "MULTIPLY", negative: false, int: m[1], frac: m[2] ?? "" }
  if ((m = RE_PERCENT_OF.exec(s))) {
    // O3: PERCENT_OF is not a board op; the board engine reads "50%" as ADJUST_PERCENT 50.
    return { op: ctx === "board" ? "ADJUST_PERCENT" : "PERCENT_OF", negative: false, int: m[1], frac: m[2] ?? "" }
  }
  if ((m = RE_ADJUST_PERCENT.exec(s))) return { op: "ADJUST_PERCENT", negative: m[1] === "-", int: m[2], frac: m[3] ?? "" }
  if ((m = RE_ADD.exec(s))) return { op: "ADD", negative: false, int: m[1], frac: m[2] ?? "" }
  if ((m = RE_SUBTRACT.exec(s))) {
    // O2: SUBTRACT is not a board op; "-20" on a board is stored as ADD -20.
    if (ctx === "board") return { op: "ADD", negative: true, int: m[1], frac: m[2] ?? "" }
    return { op: "SUBTRACT", negative: false, int: m[1], frac: m[2] ?? "" }
  }
  return null
}

/** Parses one cell entry (§3.4.2–§3.4.4). The sign lives in the op, except for ADJUST_PERCENT and
 * board ADD, whose value keeps it. INHERIT and FIXED are never produced (advanced popover only). */
export function parseShorthand(input: string, ctx: ShContext, opts?: ShParseOptions): ShResult {
  if (/[\n\r\t]/.test(input)) return { ok: false, code: "SYNTAX" }
  const s = trimSpaces(
    input
      .replace(/[\u00a0\u202f\u2009]/g, " ")
      .replace(/[\u2212\u2013]/g, "-")
      .replace(/[\u00d7xX*]/g, MUL),
  )
  if (s.length > MAX_INPUT_LENGTH) return { ok: false, code: "SYNTAX" }
  if (s === "") return { ok: true, kind: "clear" }
  if (RE_BASE.test(s)) return ctx === "board" ? { ok: true, kind: "base" } : { ok: false, code: "SYNTAX" }
  const form = matchForm(s, ctx)
  if (!form) return { ok: false, code: "SYNTAX" }
  const op = form.op
  if (!OPS_BY_CONTEXT[ctx].includes(op)) return { ok: false, code: "OP_NOT_ALLOWED", op }
  const r = canonicalMagnitude(form.int, form.frac, isAmountOp(ctx, op), minorUnitsOf(opts))
  if (!r.ok) return { ok: false, code: r.code, op }
  return { ok: true, kind: "rule", op, value: form.negative && r.value !== "0" ? `-${r.value}` : r.value }
}

/** A 1–3 digit, non-zero integer with exactly 3 fraction digits: the shape AMBIGUOUS refuses. */
const RE_AMBIGUOUS_SHAPE = /^[1-9][0-9]{0,2}\.[0-9]{3}$/

function format(op: ShOp | "BASE", value: string, ctx: ShContext, opts: ShFormatOptions | undefined, typographic: boolean): string {
  if (op === "BASE") return "BASE"
  if (op === "INHERIT") return "" // the caller shows a tag
  const canon = normaliseDecimal(value)
  const v = canon.ok ? canon.value : trimSpaces(value) // unreadable text is shown as given
  const negative = v.startsWith("-")
  let mag = negative ? v.slice(1) : v
  // Edit text must parse back to the same value: an amount such as 12.345 in a 0/2-decimal
  // currency gets one trailing zero ("12.3450"), which the AMBIGUOUS guard accepts.
  const readBack: ShOp = op === "FIXED" ? "ABSOLUTE" : op === "SUBTRACT" && ctx === "board" ? "ADD" : op
  if (!typographic && canon.ok && isAmountOp(ctx, readBack) && minorUnitsOf(opts) < 3 && RE_AMBIGUOUS_SHAPE.test(mag)) mag += "0"
  if (opts?.decimalMark === ",") mag = mag.replace(".", ",")
  const mul = typographic ? MUL : "x"
  const minus = typographic ? "\u2212" : "-"
  // A stored value the parser cannot produce keeps its arithmetic or refuses to parse again:
  // a negative value on a form without a sign stays after the op's prefix ("=-5", "x-1"), which
  // is a SYNTAX error, never a different op; ADD/SUBTRACT with a negative value swap the sign.
  switch (op) {
    case "ABSOLUTE":
      return negative ? `=${minus}${mag}` : mag
    case "FIXED":
      // FIXED has no shorthand of its own: "=245" reads back as ABSOLUTE 245, the same arithmetic
      // (§3.4.6). The cell keeps a FIXED tag so the two stay distinguishable.
      return `=${negative ? minus : ""}${mag}`
    case "MULTIPLY":
      return `${mul}${negative ? minus : ""}${mag}`
    case "PERCENT_OF":
      return negative ? `=${minus}${mag}%` : `${mag}%`
    case "ADJUST_PERCENT":
      return `${negative ? minus : "+"}${mag}%`
    case "ADD":
      return `${negative ? minus : "+"}${mag}`
    case "SUBTRACT":
      return `${negative ? "+" : minus}${mag}`
    default:
      return mag
  }
}

/** ASCII shorthand for editing and copying: 245, x1.15, 50%, +10%, -10%, +25, -25; on boards
 * 20 (ABSOLUTE), +20 / -20 (ADD), +5%, BASE; FIXED =245; INHERIT "" (§3.4.6). With the same
 * minorUnits, parseShorthand(editText(op, v, ctx), ctx) gives (op, v) back for every op the
 * parser can produce in ctx. */
export function editText(op: ShOp | "BASE", value: string, ctx: ShContext, opts?: ShFormatOptions): string {
  return format(op, value, ctx, opts, false)
}

/** The same text for display, with typographic × and − (it still parses back). */
export function displayText(op: ShOp | "BASE", value: string, ctx: ShContext, opts?: ShFormatOptions): string {
  return format(op, value, ctx, opts, true)
}
