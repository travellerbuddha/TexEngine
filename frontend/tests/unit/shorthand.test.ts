// Unit tests for the Pricing Workspace shorthand parser (PRICING_WORKSPACE_UX.md §3.4, §5.1).
// Run with `npm run test:unit` (node --test, native type stripping; no extra dependencies).
import { test } from "node:test"
import assert from "node:assert/strict"
import {
  AMOUNT_OPS,
  OPS_BY_CONTEXT,
  displayText,
  editText,
  isAmountOp,
  normaliseDecimal,
  parseShorthand,
  type ShContext,
  type ShErrorCode,
  type ShOp,
  type ShResult,
} from "../../src/tex/screens/rates/lib/shorthand.ts"

const CONTEXTS: readonly ShContext[] = ["room", "occupancy", "board", "period_adjust"]

function rule(op: ShOp, value: string): ShResult {
  return { ok: true, kind: "rule", op, value }
}

/** Compares an error result by its code, and by its op when one is expected. */
function assertError(got: ShResult, code: ShErrorCode, op: ShOp | undefined, label: string): void {
  assert.equal(got.ok, false, `${label}: expected ${code}, got ${JSON.stringify(got)}`)
  if (got.ok) return
  assert.equal(got.code, code, `${label}: code`)
  if (op !== undefined) assert.equal(got.op, op, `${label}: op`)
}

// ---------------------------------------------------------------------------------------------
// Accepted input (room context unless stated)
// ---------------------------------------------------------------------------------------------

const ACCEPTED: ReadonlyArray<[string, ShOp, string]> = [
  ["100", "ABSOLUTE", "100"],
  ["=245", "ABSOLUTE", "245"],
  ["= 245", "ABSOLUTE", "245"],
  ["x1.15", "MULTIPLY", "1.15"],
  ["\u00d71.15", "MULTIPLY", "1.15"],
  ["X 1,15", "MULTIPLY", "1.15"],
  ["*1.15", "MULTIPLY", "1.15"],
  ["x 1.150", "MULTIPLY", "1.15"],
  ["50%", "PERCENT_OF", "50"],
  ["50 %", "PERCENT_OF", "50"],
  ["+10%", "ADJUST_PERCENT", "10"],
  ["+ 10 %", "ADJUST_PERCENT", "10"],
  ["-10%", "ADJUST_PERCENT", "-10"],
  ["\u221210%", "ADJUST_PERCENT", "-10"],
  ["+25", "ADD", "25"],
  ["-25", "SUBTRACT", "25"],
  ["\u201325", "SUBTRACT", "25"],
  ["0", "ABSOLUTE", "0"],
  ["000", "ABSOLUTE", "0"],
  ["0.0", "ABSOLUTE", "0"],
  ["x0", "MULTIPLY", "0"],
  ["007,50", "ABSOLUTE", "7.5"],
  ["1,5", "ABSOLUTE", "1.5"],
  ["1500", "ABSOLUTE", "1500"],
  ["1.5", "ABSOLUTE", "1.5"],
  ["1.50", "ABSOLUTE", "1.5"],
  ["1.5000", "ABSOLUTE", "1.5"],
  ["1000.500", "ABSOLUTE", "1000.5"],
  ["0.000000001", "ABSOLUTE", "0.000000001"],
  ["0.1234567890", "ABSOLUTE", "0.123456789"], // 10 places typed, 9 after stripping
  ["123456789012", "ABSOLUTE", "123456789012"],
  ["123456789012.123", "ABSOLUTE", "123456789012.123"], // 12 + 3 = 15 significant digits
  ["123456.789012345", "ABSOLUTE", "123456.789012345"],
  ["\u00a0100\u00a0", "ABSOLUTE", "100"],
  ["\u202f= 245\u2009", "ABSOLUTE", "245"],
  ["+\u00a010\u00a0%", "ADJUST_PERCENT", "10"],
  ["  -25  ", "SUBTRACT", "25"],
  ["=" + " ".repeat(38) + "5", "ABSOLUTE", "5"], // exactly 40 characters
]

test("accepted entries (room)", () => {
  for (const [input, op, value] of ACCEPTED) {
    assert.deepEqual(parseShorthand(input, "room"), rule(op, value), JSON.stringify(input))
  }
})

test("the occupancy context reads the owner's table like the room context", () => {
  for (const [input, op, value] of ACCEPTED) {
    assert.deepEqual(parseShorthand(input, "occupancy"), rule(op, value), JSON.stringify(input))
  }
})

// ---------------------------------------------------------------------------------------------
// Refused input
// ---------------------------------------------------------------------------------------------

const SYNTAX: readonly string[] = [
  "70.",
  ".5",
  "1.",
  ",5",
  "1e5",
  "1 000",
  "1\u00a0000",
  "1.2.3",
  "1,2.3",
  "1,000.50",
  "1.000,50",
  "=-5",
  "x-1",
  "+-5",
  "--5",
  "-+5",
  "=+5",
  "x+1",
  "%",
  "x",
  "=",
  "+",
  "-",
  "\u2212",
  "abc",
  "10%%",
  "-5%%",
  "=50%",
  "x50%",
  "50%x",
  "5x",
  "1 0",
  "10 0%",
  "+10 %%",
  "\uff11\uff10\uff10", // full-width digits
  "\u0661\u0660\u0660", // Arabic-Indic digits
  "=" + " ".repeat(39) + "5", // 41 characters, otherwise valid
  "1".repeat(41), // 41 characters: SYNTAX before RANGE
  "5\n",
  "\n5",
  "5\r",
  "5\t",
  "1\n2",
]

test("syntax errors", () => {
  for (const input of SYNTAX) {
    for (const ctx of CONTEXTS) {
      assertError(parseShorthand(input, ctx), "SYNTAX", undefined, `${JSON.stringify(input)} in ${ctx}`)
    }
  }
})

test("limits: PLACES, then RANGE, then DIGITS", () => {
  assertError(parseShorthand("1234567890123", "room"), "RANGE", "ABSOLUTE", "13 integer digits")
  assertError(parseShorthand("0.1234567891", "room"), "PLACES", "ABSOLUTE", "10 places")
  assertError(parseShorthand("1234567.123456789", "room"), "DIGITS", "ABSOLUTE", "16 significant digits")
  assertError(parseShorthand("123456789012.1234", "room"), "DIGITS", "ABSOLUTE", "12 + 4 significant digits")
  assertError(parseShorthand("x1234567890123", "room"), "RANGE", "MULTIPLY", "range applies to factors")
  assertError(parseShorthand("+0.1234567891%", "room"), "PLACES", "ADJUST_PERCENT", "places apply to percentages")
  // order: PLACES before RANGE, RANGE before DIGITS
  assertError(parseShorthand("1234567890123.1234567891", "room"), "PLACES", "ABSOLUTE", "places first")
  assertError(parseShorthand("1234567890123.456", "room"), "RANGE", "ABSOLUTE", "range before digits")
  // leading integer zeros do not count
  assert.deepEqual(parseShorthand("0000123456789012", "room"), rule("ABSOLUTE", "123456789012"))
})

// ---------------------------------------------------------------------------------------------
// AMBIGUOUS (currency-aware, O5)
// ---------------------------------------------------------------------------------------------

test("AMBIGUOUS: 1-3 integer digits + exactly 3 typed fraction digits, amounts only, minorUnits < 3", () => {
  for (const input of ["1.500", "1,500"]) {
    assertError(parseShorthand(input, "room"), "AMBIGUOUS", "ABSOLUTE", `${input} default`)
    assertError(parseShorthand(input, "room", {}), "AMBIGUOUS", "ABSOLUTE", `${input} {}`)
    assertError(parseShorthand(input, "room", { minorUnits: 2 }), "AMBIGUOUS", "ABSOLUTE", `${input} mu2`)
    assertError(parseShorthand(input, "room", { minorUnits: 0 }), "AMBIGUOUS", "ABSOLUTE", `${input} mu0`)
    assert.deepEqual(parseShorthand(input, "room", { minorUnits: 3 }), rule("ABSOLUTE", "1.5"), `${input} mu3`)
  }
  assert.deepEqual(parseShorthand("12.345", "room", { minorUnits: 3 }), rule("ABSOLUTE", "12.345"))
  assertError(parseShorthand("12.345", "room"), "AMBIGUOUS", "ABSOLUTE", "12.345 default")
  assertError(parseShorthand("999.999", "room"), "AMBIGUOUS", "ABSOLUTE", "999.999")
  assertError(parseShorthand("= 1.500", "room"), "AMBIGUOUS", "ABSOLUTE", "= 1.500")
  assertError(parseShorthand("+1.500", "room", { minorUnits: 2 }), "AMBIGUOUS", "ADD", "+1.500")
  assertError(parseShorthand("-1.500", "room"), "AMBIGUOUS", "SUBTRACT", "-1.500")
  assertError(parseShorthand("001.500", "room"), "AMBIGUOUS", "ABSOLUTE", "leading zeros do not hide it")
  assertError(parseShorthand("1.500", "occupancy"), "AMBIGUOUS", "ABSOLUTE", "occupancy")
  assertError(parseShorthand("+1.500", "occupancy"), "AMBIGUOUS", "ADD", "occupancy ADD")
  // exempt: factors, percentages, a zero integer part, 4+ integer digits, other fraction lengths
  assert.deepEqual(parseShorthand("x1.500", "room"), rule("MULTIPLY", "1.5"))
  assert.deepEqual(parseShorthand("1.125%", "room"), rule("PERCENT_OF", "1.125"))
  assert.deepEqual(parseShorthand("+1.125%", "room"), rule("ADJUST_PERCENT", "1.125"))
  assert.deepEqual(parseShorthand("-1.125%", "room"), rule("ADJUST_PERCENT", "-1.125"))
  assert.deepEqual(parseShorthand("0.500", "room"), rule("ABSOLUTE", "0.5"))
  assert.deepEqual(parseShorthand("1.50", "room"), rule("ABSOLUTE", "1.5"))
  assert.deepEqual(parseShorthand("1500", "room"), rule("ABSOLUTE", "1500"))
  assert.deepEqual(parseShorthand("1.5", "room"), rule("ABSOLUTE", "1.5"))
  assert.deepEqual(parseShorthand("1000.500", "room"), rule("ABSOLUTE", "1000.5"))
  // boards: ABSOLUTE and ADD are amounts, ADJUST_PERCENT is not
  assertError(parseShorthand("1.500", "board"), "AMBIGUOUS", "ABSOLUTE", "board bare")
  assertError(parseShorthand("+1.500", "board"), "AMBIGUOUS", "ADD", "board +")
  assertError(parseShorthand("-1.500", "board"), "AMBIGUOUS", "ADD", "board -")
  assert.deepEqual(parseShorthand("1.500%", "board"), rule("ADJUST_PERCENT", "1.5"))
  assert.deepEqual(parseShorthand("-0.000", "board"), rule("ADD", "0"))
  // period adjustments: ADD and SUBTRACT are amounts, MULTIPLY is not; ABSOLUTE is not allowed at all
  assertError(parseShorthand("+1.500", "period_adjust"), "AMBIGUOUS", "ADD", "period +")
  assertError(parseShorthand("-1.500", "period_adjust"), "AMBIGUOUS", "SUBTRACT", "period -")
  assert.deepEqual(parseShorthand("x1.500", "period_adjust"), rule("MULTIPLY", "1.5"))
  assertError(parseShorthand("1.500", "period_adjust"), "OP_NOT_ALLOWED", "ABSOLUTE", "period bare")
  // 3-decimal currencies accept the amount as typed
  assert.deepEqual(parseShorthand("+1.500", "board", { minorUnits: 3 }), rule("ADD", "1.5"))
  assert.deepEqual(parseShorthand("-12.345", "period_adjust", { minorUnits: 3 }), rule("SUBTRACT", "12.345"))
})

// ---------------------------------------------------------------------------------------------
// Negative zero, clear
// ---------------------------------------------------------------------------------------------

test("negative zero never reaches the value", () => {
  assert.deepEqual(parseShorthand("-0", "room"), rule("SUBTRACT", "0"))
  assert.deepEqual(parseShorthand("-0.00", "room"), rule("SUBTRACT", "0"))
  assert.deepEqual(parseShorthand("-0%", "room"), rule("ADJUST_PERCENT", "0"))
  assert.deepEqual(parseShorthand("\u22120,0 %", "room"), rule("ADJUST_PERCENT", "0"))
  assert.deepEqual(parseShorthand("+0%", "room"), rule("ADJUST_PERCENT", "0"))
  assert.deepEqual(parseShorthand("-0", "board"), rule("ADD", "0"))
  assert.deepEqual(parseShorthand("-0%", "board"), rule("ADJUST_PERCENT", "0"))
  assert.deepEqual(parseShorthand("-0%", "period_adjust"), rule("ADJUST_PERCENT", "0"))
})

test("empty input clears in every context", () => {
  for (const ctx of CONTEXTS) {
    for (const input of ["", "   ", "\u00a0", " \u202f\u2009 "]) {
      assert.deepEqual(parseShorthand(input, ctx), { ok: true, kind: "clear" }, `${JSON.stringify(input)} ${ctx}`)
    }
  }
})

// ---------------------------------------------------------------------------------------------
// Context mapping (§3.4.4, the owner's table everywhere)
// ---------------------------------------------------------------------------------------------

type Expect = ShResult | ShErrorCode | [ShErrorCode, ShOp]

// input → [room, occupancy, board, period_adjust]
const MAPPING: ReadonlyArray<[string, Expect, Expect, Expect, Expect]> = [
  ["100", rule("ABSOLUTE", "100"), rule("ABSOLUTE", "100"), rule("ABSOLUTE", "100"), ["OP_NOT_ALLOWED", "ABSOLUTE"]],
  ["=100", rule("ABSOLUTE", "100"), rule("ABSOLUTE", "100"), rule("ABSOLUTE", "100"), ["OP_NOT_ALLOWED", "ABSOLUTE"]],
  ["x1.15", rule("MULTIPLY", "1.15"), rule("MULTIPLY", "1.15"), ["OP_NOT_ALLOWED", "MULTIPLY"], rule("MULTIPLY", "1.15")],
  ["\u00d71.15", rule("MULTIPLY", "1.15"), rule("MULTIPLY", "1.15"), ["OP_NOT_ALLOWED", "MULTIPLY"], rule("MULTIPLY", "1.15")],
  ["X 1,15", rule("MULTIPLY", "1.15"), rule("MULTIPLY", "1.15"), ["OP_NOT_ALLOWED", "MULTIPLY"], rule("MULTIPLY", "1.15")],
  ["*1.15", rule("MULTIPLY", "1.15"), rule("MULTIPLY", "1.15"), ["OP_NOT_ALLOWED", "MULTIPLY"], rule("MULTIPLY", "1.15")],
  ["50%", rule("PERCENT_OF", "50"), rule("PERCENT_OF", "50"), rule("ADJUST_PERCENT", "50"), ["OP_NOT_ALLOWED", "PERCENT_OF"]],
  ["+10%", rule("ADJUST_PERCENT", "10"), rule("ADJUST_PERCENT", "10"), rule("ADJUST_PERCENT", "10"), rule("ADJUST_PERCENT", "10")],
  ["-10%", rule("ADJUST_PERCENT", "-10"), rule("ADJUST_PERCENT", "-10"), rule("ADJUST_PERCENT", "-10"), rule("ADJUST_PERCENT", "-10")],
  ["+25", rule("ADD", "25"), rule("ADD", "25"), rule("ADD", "25"), rule("ADD", "25")],
  ["-25", rule("SUBTRACT", "25"), rule("SUBTRACT", "25"), rule("ADD", "-25"), rule("SUBTRACT", "25")],
  ["base", "SYNTAX", "SYNTAX", { ok: true, kind: "base" }, "SYNTAX"],
  ["", { ok: true, kind: "clear" }, { ok: true, kind: "clear" }, { ok: true, kind: "clear" }, { ok: true, kind: "clear" }],
  ["=-5", "SYNTAX", "SYNTAX", "SYNTAX", "SYNTAX"],
  ["x-1", "SYNTAX", "SYNTAX", "SYNTAX", "SYNTAX"],
  ["+-5", "SYNTAX", "SYNTAX", "SYNTAX", "SYNTAX"],
  ["--5", "SYNTAX", "SYNTAX", "SYNTAX", "SYNTAX"],
  ["-5%%", "SYNTAX", "SYNTAX", "SYNTAX", "SYNTAX"],
]

test("context mapping follows the owner's table (§3.4.4)", () => {
  for (const [input, ...perCtx] of MAPPING) {
    CONTEXTS.forEach((ctx, i) => {
      const want = perCtx[i]
      const got = parseShorthand(input, ctx)
      const label = `${JSON.stringify(input)} in ${ctx}`
      if (typeof want === "string") assertError(got, want, undefined, label)
      else if (Array.isArray(want)) assertError(got, want[0], want[1], label)
      else assert.deepEqual(got, want, label)
    })
  }
})

test("board context (O1-O3)", () => {
  assert.deepEqual(parseShorthand("20", "board"), rule("ABSOLUTE", "20"))
  assert.deepEqual(parseShorthand("=20", "board"), rule("ABSOLUTE", "20"))
  assert.deepEqual(parseShorthand("+20", "board"), rule("ADD", "20"))
  assert.deepEqual(parseShorthand("-20", "board"), rule("ADD", "-20"))
  assert.deepEqual(parseShorthand("\u221220", "board"), rule("ADD", "-20"))
  assert.deepEqual(parseShorthand("5%", "board"), rule("ADJUST_PERCENT", "5"))
  assert.deepEqual(parseShorthand("+5%", "board"), rule("ADJUST_PERCENT", "5"))
  assert.deepEqual(parseShorthand("-5%", "board"), rule("ADJUST_PERCENT", "-5"))
  assertError(parseShorthand("x1.1", "board"), "OP_NOT_ALLOWED", "MULTIPLY", "board x1.1")
  for (const input of ["BASE", "base", "Base", " bAsE ", "\u00a0base"]) {
    assert.deepEqual(parseShorthand(input, "board"), { ok: true, kind: "base" }, input)
  }
  assertError(parseShorthand("bas e", "board"), "SYNTAX", undefined, "bas e")
  assertError(parseShorthand("=base", "board"), "SYNTAX", undefined, "=base")
})

test("period adjustment context", () => {
  assertError(parseShorthand("10", "period_adjust"), "OP_NOT_ALLOWED", "ABSOLUTE", "10")
  assertError(parseShorthand("=10", "period_adjust"), "OP_NOT_ALLOWED", "ABSOLUTE", "=10")
  assertError(parseShorthand("50%", "period_adjust"), "OP_NOT_ALLOWED", "PERCENT_OF", "50%")
  assert.deepEqual(parseShorthand("+10%", "period_adjust"), rule("ADJUST_PERCENT", "10"))
  assert.deepEqual(parseShorthand("-10%", "period_adjust"), rule("ADJUST_PERCENT", "-10"))
  assert.deepEqual(parseShorthand("x1.1", "period_adjust"), rule("MULTIPLY", "1.1"))
  assert.deepEqual(parseShorthand("+25", "period_adjust"), rule("ADD", "25"))
  assert.deepEqual(parseShorthand("-25", "period_adjust"), rule("SUBTRACT", "25"))
  assertError(parseShorthand("base", "period_adjust"), "SYNTAX", undefined, "base")
  // an op the context refuses is reported before the number limits
  assertError(parseShorthand("1234567890123", "period_adjust"), "OP_NOT_ALLOWED", "ABSOLUTE", "op first")
})

test("room and occupancy refuse 'base'", () => {
  for (const ctx of ["room", "occupancy"] as const) {
    for (const input of ["base", "BASE"]) assertError(parseShorthand(input, ctx), "SYNTAX", undefined, `${input} ${ctx}`)
  }
})

test("the parser never produces an op outside OPS_BY_CONTEXT, INHERIT or FIXED", () => {
  const inputs = [...ACCEPTED.map(([i]) => i), ...MAPPING.map(([i]) => i), "-20", "5%", "+5%"]
  for (const ctx of CONTEXTS) {
    for (const input of inputs) {
      const r = parseShorthand(input, ctx)
      if (r.ok && r.kind === "rule") {
        assert.ok(OPS_BY_CONTEXT[ctx].includes(r.op), `${input} ${ctx} → ${r.op}`)
        assert.notEqual(r.op, "INHERIT")
        assert.notEqual(r.op, "FIXED")
        assert.ok(!r.value.startsWith("-0") || r.value.startsWith("-0."), `${input} ${ctx} → ${r.value}`)
        assert.notEqual(r.value, "-0")
      }
    }
  }
})

test("the result is deterministic", () => {
  for (const [input] of ACCEPTED) {
    assert.deepEqual(parseShorthand(input, "room"), parseShorthand(input, "room"))
  }
})

// ---------------------------------------------------------------------------------------------
// Op sets
// ---------------------------------------------------------------------------------------------

test("OPS_BY_CONTEXT follows the DocType op lists", () => {
  const sorted = (a: readonly ShOp[]) => [...a].sort()
  assert.deepEqual(sorted(OPS_BY_CONTEXT.room), sorted(["ABSOLUTE", "MULTIPLY", "ADJUST_PERCENT", "PERCENT_OF", "ADD", "SUBTRACT", "INHERIT"]))
  assert.deepEqual(sorted(OPS_BY_CONTEXT.occupancy), sorted(["ABSOLUTE", "MULTIPLY", "ADJUST_PERCENT", "PERCENT_OF", "ADD", "SUBTRACT", "INHERIT", "FIXED"]))
  assert.deepEqual(sorted(OPS_BY_CONTEXT.board), sorted(["ADD", "ADJUST_PERCENT", "ABSOLUTE"]))
  assert.deepEqual(sorted(OPS_BY_CONTEXT.period_adjust), sorted(["ADJUST_PERCENT", "MULTIPLY", "ADD", "SUBTRACT"]))
})

test("AMOUNT_OPS names the money amounts", () => {
  assert.deepEqual([...AMOUNT_OPS.room].sort(), ["ABSOLUTE", "ADD", "SUBTRACT"])
  assert.deepEqual([...AMOUNT_OPS.occupancy].sort(), ["ABSOLUTE", "ADD", "FIXED", "SUBTRACT"])
  assert.deepEqual([...AMOUNT_OPS.board].sort(), ["ABSOLUTE", "ADD"])
  assert.deepEqual([...AMOUNT_OPS.period_adjust].sort(), ["ADD", "SUBTRACT"])
  assert.equal(isAmountOp("room", "ABSOLUTE"), true)
  assert.equal(isAmountOp("room", "MULTIPLY"), false)
  assert.equal(isAmountOp("board", "ADJUST_PERCENT"), false)
  assert.equal(isAmountOp("period_adjust", "ABSOLUTE"), false)
  assert.equal(isAmountOp("period_adjust", "SUBTRACT"), true)
})

// ---------------------------------------------------------------------------------------------
// normaliseDecimal
// ---------------------------------------------------------------------------------------------

test("normaliseDecimal canonicalises decimal strings", () => {
  const a = normaliseDecimal("216.000000")
  const b = normaliseDecimal("216")
  assert.deepEqual(a, { ok: true, value: "216" })
  assert.deepEqual(a, b)
  assert.deepEqual(normaliseDecimal("216.00"), { ok: true, value: "216" })
  assert.deepEqual(normaliseDecimal("007,50"), { ok: true, value: "7.5" })
  assert.deepEqual(normaliseDecimal("0.000000001"), { ok: true, value: "0.000000001" })
  assert.deepEqual(normaliseDecimal("54.00"), { ok: true, value: "54" })
  assert.deepEqual(normaliseDecimal("-5.50"), { ok: true, value: "-5.5" })
  assert.deepEqual(normaliseDecimal("+5"), { ok: true, value: "5" })
  assert.deepEqual(normaliseDecimal("-0.00"), { ok: true, value: "0" })
  assert.deepEqual(normaliseDecimal(" 12.30 "), { ok: true, value: "12.3" })
  assert.deepEqual(normaliseDecimal("1.500"), { ok: true, value: "1.5" })
  assert.deepEqual(normaliseDecimal("1.500", { amount: true, minorUnits: 3 }), { ok: true, value: "1.5" })
  assert.deepEqual(normaliseDecimal("1.500", { amount: true }), { ok: false, code: "AMBIGUOUS" })
  assert.deepEqual(normaliseDecimal("1.500", { amount: true, minorUnits: 0 }), { ok: false, code: "AMBIGUOUS" })
  assert.deepEqual(normaliseDecimal("0.1234567891"), { ok: false, code: "PLACES" })
  assert.deepEqual(normaliseDecimal("1234567890123"), { ok: false, code: "RANGE" })
  assert.deepEqual(normaliseDecimal("1234567.123456789"), { ok: false, code: "DIGITS" })
  for (const bad of ["", "abc", "1e5", "1 000", "70.", ".5", "1.2.3", "--5", "5%", "x5"]) {
    assert.deepEqual(normaliseDecimal(bad), { ok: false, code: "SYNTAX" }, JSON.stringify(bad))
  }
})

// ---------------------------------------------------------------------------------------------
// Formatting (§3.4.6)
// ---------------------------------------------------------------------------------------------

test("editText gives ASCII shorthand", () => {
  const cases: ReadonlyArray<[ShOp | "BASE", string, ShContext, string]> = [
    ["ABSOLUTE", "245", "room", "245"],
    ["ABSOLUTE", "245.000000000", "room", "245"],
    ["MULTIPLY", "1.15", "room", "x1.15"],
    ["PERCENT_OF", "50", "room", "50%"],
    ["ADJUST_PERCENT", "10", "room", "+10%"],
    ["ADJUST_PERCENT", "-10", "room", "-10%"],
    ["ADJUST_PERCENT", "0", "room", "+0%"],
    ["ADD", "25", "room", "+25"],
    ["SUBTRACT", "25", "room", "-25"],
    ["ABSOLUTE", "20", "board", "20"],
    ["ADD", "20", "board", "+20"],
    ["ADD", "-20", "board", "-20"],
    ["ADJUST_PERCENT", "5", "board", "+5%"],
    ["BASE", "", "board", "BASE"],
    ["FIXED", "245", "occupancy", "=245"],
    ["INHERIT", "", "room", ""],
    ["INHERIT", "", "occupancy", ""],
    ["MULTIPLY", "1.1", "period_adjust", "x1.1"],
    ["ADD", "25", "period_adjust", "+25"],
    ["SUBTRACT", "25", "period_adjust", "-25"],
  ]
  for (const [op, value, ctx, want] of cases) {
    assert.equal(editText(op, value, ctx), want, `${op} ${value} ${ctx}`)
  }
})

test("editText with the decimal comma", () => {
  const o = { decimalMark: "," } as const
  assert.equal(editText("MULTIPLY", "1.15", "room", o), "x1,15")
  assert.equal(editText("ABSOLUTE", "7.5", "room", o), "7,5")
  assert.equal(editText("ADJUST_PERCENT", "-2.5", "room", o), "-2,5%")
  assert.equal(editText("ADD", "-20.5", "board", o), "-20,5")
  assert.equal(editText("FIXED", "245.25", "occupancy", o), "=245,25")
  assert.equal(editText("ABSOLUTE", "245", "room", o), "245")
  assert.deepEqual(parseShorthand(editText("MULTIPLY", "1.15", "room", o), "room"), rule("MULTIPLY", "1.15"))
})

test("editText keeps a 3-place amount readable in a 0/2-decimal currency", () => {
  // "12.345" would read as AMBIGUOUS there; one trailing zero keeps the value and parses back.
  assert.equal(editText("ABSOLUTE", "12.345", "room"), "12.3450")
  assert.equal(editText("ABSOLUTE", "12.345", "room", { minorUnits: 3 }), "12.345")
  assert.equal(editText("ADD", "-1.5", "board", { minorUnits: 3 }), "-1.5")
  assert.equal(editText("MULTIPLY", "1.125", "room"), "x1.125")
  assert.equal(editText("ADJUST_PERCENT", "1.125", "room"), "+1.125%")
})

test("displayText uses typographic × and −", () => {
  assert.equal(displayText("MULTIPLY", "1.15", "room"), "\u00d71.15")
  assert.equal(displayText("SUBTRACT", "25", "room"), "\u221225")
  assert.equal(displayText("ADD", "25", "room"), "+25")
  assert.equal(displayText("ADJUST_PERCENT", "-10", "room"), "\u221210%")
  assert.equal(displayText("ADJUST_PERCENT", "10", "room"), "+10%")
  assert.equal(displayText("ADD", "-20", "board"), "\u221220")
  assert.equal(displayText("ABSOLUTE", "20", "board"), "20")
  assert.equal(displayText("PERCENT_OF", "50", "room"), "50%")
  assert.equal(displayText("FIXED", "245", "occupancy"), "=245")
  assert.equal(displayText("BASE", "", "board"), "BASE")
  assert.equal(displayText("INHERIT", "", "room"), "")
  assert.equal(displayText("MULTIPLY", "1.15", "room", { decimalMark: "," }), "\u00d71,15")
  assert.equal(displayText("ABSOLUTE", "12.345", "room"), "12.345")
  for (const text of [displayText("MULTIPLY", "1.15", "room"), displayText("SUBTRACT", "25", "room")]) {
    assert.ok(!/[x\-]/.test(text), text)
  }
})

/** The ops the parser can produce in each context, with a flag for ops whose value keeps a sign. */
const PRODUCIBLE: Record<ShContext, ReadonlyArray<[ShOp, boolean]>> = {
  room: [["ABSOLUTE", false], ["MULTIPLY", false], ["PERCENT_OF", false], ["ADJUST_PERCENT", true], ["ADD", false], ["SUBTRACT", false]],
  occupancy: [["ABSOLUTE", false], ["MULTIPLY", false], ["PERCENT_OF", false], ["ADJUST_PERCENT", true], ["ADD", false], ["SUBTRACT", false]],
  board: [["ABSOLUTE", false], ["ADD", true], ["ADJUST_PERCENT", true]],
  period_adjust: [["MULTIPLY", false], ["ADJUST_PERCENT", true], ["ADD", false], ["SUBTRACT", false]],
}

const ROUND_TRIP_VALUES = [
  "0", "1", "7.5", "1.15", "1.5", "12.345", "100", "245", "999.999", "1000.5", "0.5",
  "0.000000001", "123456789012", "123456.789012345", "0.333333333",
]

test("round trip: parseShorthand(editText(op, v, ctx), ctx) = (op, v)", () => {
  for (const ctx of CONTEXTS) {
    for (const [op, signed] of PRODUCIBLE[ctx]) {
      for (const v of ROUND_TRIP_VALUES) {
        const values = signed && v !== "0" ? [v, `-${v}`] : [v]
        for (const value of values) {
          for (const decimalMark of [".", ","] as const) {
            for (const minorUnits of [0, 2, 3]) {
              const text = editText(op, value, ctx, { decimalMark, minorUnits })
              assert.deepEqual(
                parseShorthand(text, ctx, { minorUnits }),
                rule(op, value),
                `${ctx} ${op} ${value} mark=${decimalMark} mu=${minorUnits} text=${JSON.stringify(text)}`,
              )
            }
          }
          // typographic text parses back too (no AMBIGUOUS guard in a 3-decimal currency)
          const shown = displayText(op, value, ctx)
          assert.deepEqual(parseShorthand(shown, ctx, { minorUnits: 3 }), rule(op, value), `display ${ctx} ${op} ${value}`)
        }
      }
    }
    assert.deepEqual(parseShorthand(editText("BASE", "", ctx), ctx), ctx === "board" ? { ok: true, kind: "base" } : { ok: false, code: "SYNTAX" })
  }
})

test("round trip exceptions: FIXED reads back as ABSOLUTE, INHERIT as clear", () => {
  assert.deepEqual(parseShorthand(editText("FIXED", "245", "occupancy"), "occupancy"), rule("ABSOLUTE", "245"))
  assert.deepEqual(parseShorthand(editText("INHERIT", "", "room"), "room"), { ok: true, kind: "clear" })
})

test("editText never turns a stored rule into a different calculation", () => {
  // Values the parser cannot produce either read back with identical arithmetic or refuse to parse.
  assert.deepEqual(parseShorthand(editText("ADD", "-5", "room"), "room"), rule("SUBTRACT", "5"))
  assert.deepEqual(parseShorthand(editText("SUBTRACT", "-5", "room"), "room"), rule("ADD", "5"))
  assert.deepEqual(parseShorthand(editText("ADJUST_PERCENT", "+10", "room"), "room"), rule("ADJUST_PERCENT", "10"))
  for (const [op, value] of [["ABSOLUTE", "-5"], ["FIXED", "-5"], ["MULTIPLY", "-1"], ["PERCENT_OF", "-50"]] as const) {
    const r = parseShorthand(editText(op, value, "occupancy"), "occupancy")
    assertError(r, "SYNTAX", undefined, `${op} ${value}`)
  }
})

test("the Turkish percentage form: %30, +%10, -%30 read as 30%, +10%, -30% (UX revision 2026-10)", () => {
  assert.deepEqual(parseShorthand("+%10", "room"), parseShorthand("+10%", "room"))
  assert.deepEqual(parseShorthand("-%30", "occupancy"), { ok: true, kind: "rule", op: "ADJUST_PERCENT", value: "-30" })
  assert.deepEqual(parseShorthand("- % 7,5", "occupancy"), { ok: true, kind: "rule", op: "ADJUST_PERCENT", value: "-7.5" })
  // a bare share stays a share, never an adjustment
  assert.deepEqual(parseShorthand("%50", "occupancy"), { ok: true, kind: "rule", op: "PERCENT_OF", value: "50" })
  assert.deepEqual(parseShorthand("%50", "board"), parseShorthand("50%", "board"))
  // nothing else is read differently
  for (const bad of ["%", "%%10", "10%%", "%10%", "+%", "%-10", "x%10"]) assert.equal(parseShorthand(bad, "room").ok, false, bad)
})
