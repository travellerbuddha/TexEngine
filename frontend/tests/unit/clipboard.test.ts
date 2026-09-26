// Unit tests for the room price matrix clipboard (PRICING_WORKSPACE_UX.md §3.10; slice S10): TSV
// encode / decode, the block Ctrl/Cmd+C copies, where a paste is anchored, and paste planning (one
// value fills the selection, a block anchored at the active cell must fit the editable cells,
// every cell parsed in its context with the contract's minor units, all or nothing).
// Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { parseShorthand } from "../../src/tex/screens/rates/lib/shorthand.ts"
import { copyBlock, decodeTSV, encodeTSV, pasteOrigin, planPaste, PASTE_MAX_ERRORS, type PasteResult } from "../../src/tex/screens/rates/workspace/clipboard.ts"
import { gridSelectionInit, gridSelectionReducer, selectedCells, type GridSelection } from "../../src/tex/ui/grid-model.ts"

// the owner's example as the matrix walks it (workspace-matrix.test.ts "grid rows"): Standard is
// the base room, Superior and Deluxe are formula rooms, each with a resolved row under it
const ROWS = [
  { room: "STD", editable: true },
  { room: "SUP", editable: true },
  { room: "SUP", editable: false }, // resolved
  { room: "DLX", editable: true },
  { room: "DLX", editable: false }, // resolved
]
const COLS = ["", "P1", "P2", "P3", "P4"]
const NAMES: Record<string, string> = { STD: "Standard", SUP: "Superior", DLX: "Deluxe" }
const editable = (r: number, c: number) => Boolean(ROWS[r]?.editable) && c >= 0 && c < COLS.length
const label = ({ r, c }: { r: number; c: number }) => `${COLS[c] || "All periods"} · ${NAMES[ROWS[r].room]}`
const bounds = { rows: ROWS.length, cols: COLS.length }
const room = (minorUnits = 2) => (text: string) => parseShorthand(text, "room", { minorUnits })

function plan(block: string[][], active: { r: number; c: number }, selection: { r: number; c: number }[] = [], minorUnits = 2): PasteResult {
  return planPaste(block, active, selection, editable, room(minorUnits), { ...bounds, label })
}
function items(res: PasteResult) {
  assert.ok(res.ok, `expected a paste plan, got ${JSON.stringify(res)}`)
  return res.items.map((x) => [x.cell.r, x.cell.c, x.text, x.parsed.ok && x.parsed.kind === "rule" ? `${x.parsed.op} ${x.parsed.value}` : x.parsed.ok ? x.parsed.kind : x.parsed.code])
}

// ─── TSV ──────────────────────────────────────────────────────────────────

test("TSV round trip: rows by line breaks, cells by tabs, empty cells kept", () => {
  const block = [
    ["70", "80", "100", "130"],
    ["x1.15", "", "=245", "x1.2"],
    ["", "", "", ""],
  ]
  const text = encodeTSV(block)
  // every row ends with a line break, as spreadsheets write it (decodeTSV trims exactly that one)
  assert.equal(text, "70\t80\t100\t130\nx1.15\t\t=245\tx1.2\n\t\t\t\n")
  assert.deepEqual(decodeTSV(text), block)
  assert.deepEqual(decodeTSV(encodeTSV([["70"]])), [["70"]])
  // a last row of one empty cell (a room without rules) is kept, so it clears where it is pasted
  assert.deepEqual(decodeTSV(encodeTSV([["70"], [""]])), [["70"], [""]])
  // one empty cell copied is one empty cell (it clears), not "nothing to paste"
  assert.deepEqual(decodeTSV(encodeTSV([[""]])), [[""]])
  assert.equal(encodeTSV([]), "")
})

test("decodeTSV: a spreadsheet's trailing line break is trimmed, CRLF and CR split lines, an empty text is no block", () => {
  // what a spreadsheet puts on the clipboard for a 2×2 block (Windows line breaks, one at the end)
  assert.deepEqual(decodeTSV("70\t80\r\n100\t130\r\n"), [
    ["70", "80"],
    ["100", "130"],
  ])
  assert.deepEqual(decodeTSV("70\r80\n"), [["70"], ["80"]])
  // only one trailing line break is trimmed: a last empty row that was copied stays
  assert.deepEqual(decodeTSV("70\n\n"), [["70"], [""]])
  // one empty cell copied is one empty cell (it clears); nothing on the clipboard is nothing
  assert.deepEqual(decodeTSV("\n"), [[""]])
  assert.deepEqual(decodeTSV(""), [])
  // empty cells anywhere in a row are kept
  assert.deepEqual(decodeTSV("\t\t5\t\n"), [["", "", "5", ""]])
})

test("encodeTSV never lets a cell's own tab or line break split the block", () => {
  assert.equal(encodeTSV([["a\tb", "c\r\nd"]]), "a b\tc d\n")
})

test("the block Ctrl/Cmd+C copies: a range's rectangle; several ranges give their rows × columns, the rest empty", () => {
  const text = (r: number, c: number) => `${r}:${c}`
  assert.deepEqual(copyBlock([{ r0: 1, c0: 2, r1: 2, c1: 3 }], text), [
    ["1:2", "1:3"],
    ["2:2", "2:3"],
  ])
  // Ctrl/Cmd+Click on Standard P1 and Deluxe P3: the rows and the columns that hold a selected cell
  assert.deepEqual(
    copyBlock(
      [
        { r0: 0, c0: 1, r1: 0, c1: 1 },
        { r0: 3, c0: 3, r1: 3, c1: 3 },
      ],
      text,
    ),
    [
      ["0:1", ""],
      ["", "3:3"],
    ],
  )
  // a column selected by its header skips the resolved rows (they are not selected), so the block
  // holds the entry rows only and pastes back onto them
  assert.deepEqual(
    copyBlock(
      [
        { r0: 0, c0: 2, r1: 1, c1: 2 },
        { r0: 3, c0: 2, r1: 3, c1: 2 },
      ],
      text,
    ),
    [["0:2"], ["1:2"], ["3:2"]],
  )
  assert.deepEqual(copyBlock([], text), [])
})

// the owner grid with "Show resolved" on (the verifier's S10 case): Standard is the base room,
// Superior and Deluxe are formula rooms, Family a manual room; each of the three has a resolved row
const OWNER = [
  { room: "STD", editable: true, text: ["", "70", "80", "100", "130"] },
  { room: "SUP", editable: true, text: ["x1.15", "x1.15", "245", "x1.15", "x1.2"] },
  { room: "SUP", editable: false, text: ["", "80.5", "245", "115", "156"] },
  { room: "DLX", editable: true, text: ["x1.35", "x1.35", "x1.35", "x1.35", "x1.35"] },
  { room: "DLX", editable: false, text: ["", "94.5", "108", "135", "175.5"] },
  { room: "FAM", editable: true, text: ["90", "90", "90", "90", "90"] },
  { room: "FAM", editable: false, text: ["", "90", "90", "90", "90"] },
]
const ownerEditable = (r: number, c: number) => Boolean(OWNER[r]?.editable) && c >= 0 && c < 5
const ownerEntry = (r: number) => Boolean(OWNER[r]?.editable)
const ownerText = (r: number, c: number) => OWNER[r].text[c]
const ownerStart = (r: number, c: number) => gridSelectionReducer(gridSelectionInit(OWNER.length, 5), { type: "moveTo", r, c })
const shiftDown = (s: GridSelection, n: number) => {
  for (let i = 0; i < n; i++) s = gridSelectionReducer(s, { type: "move", dr: 1, dc: 0, extend: true })
  return s
}
/** Ctrl/Cmd+C then Ctrl/Cmd+V as PriceMatrix does them: the clipboard's text in between. */
function copyThenPaste(from: GridSelection, to: GridSelection) {
  const tsv = encodeTSV(copyBlock(from.ranges, ownerText, ownerEntry))
  const res = planPaste(decodeTSV(tsv), pasteOrigin(to), selectedCells(to, ownerEditable), ownerEditable, room(), { rows: OWNER.length, cols: 5 })
  assert.ok(res.ok, `expected a paste plan, got ${JSON.stringify(res)}`)
  return { tsv, written: res.items.map((x) => [OWNER[x.cell.r].room, x.cell.r, x.cell.c, x.text]) }
}

test("a range over entry and resolved rows copies the entry rows only, so it pastes back onto the same rooms (S10 review)", () => {
  // Shift+ArrowDown ×3 from Standard P1: Standard, Superior, Superior resolved, Deluxe
  const range = shiftDown(ownerStart(0, 1), 3)
  assert.deepEqual(range.ranges, [{ r0: 0, c0: 1, r1: 3, c1: 1 }])
  assert.deepEqual(copyBlock(range.ranges, ownerText, ownerEntry), [["70"], ["x1.15"], ["x1.35"]])
  // pasted at Standard P2: Standard, Superior and Deluxe P2 take their own row's text; Family is untouched
  const there = copyThenPaste(range, gridSelectionReducer(range, { type: "moveTo", r: 0, c: 2 }))
  assert.equal(there.tsv, "70\nx1.15\nx1.35\n")
  assert.deepEqual(there.written, [
    ["STD", 0, 2, "70"],
    ["SUP", 1, 2, "x1.15"],
    ["DLX", 3, 2, "x1.35"],
  ])
  // pasted back where it was copied: the same cells, the same texts
  assert.deepEqual(copyThenPaste(range, range).written, [
    ["STD", 0, 1, "70"],
    ["SUP", 1, 1, "x1.15"],
    ["DLX", 3, 1, "x1.35"],
  ])
  // Shift+Click from Superior's resolved P1 to Deluxe P2: Deluxe's row only
  const click = gridSelectionReducer(ownerStart(2, 1), { type: "click", r: 3, c: 2, shift: true })
  assert.deepEqual(copyBlock(click.ranges, ownerText, ownerEntry), [["x1.35", "x1.35"]])
  // Ctrl/Cmd+Click on Standard P1 and Superior's resolved P3: the resolved cell's column goes with its row
  assert.deepEqual(
    copyBlock(
      [
        { r0: 0, c0: 1, r1: 0, c1: 1 },
        { r0: 2, c0: 3, r1: 2, c1: 3 },
      ],
      ownerText,
      ownerEntry,
    ),
    [["70"]],
  )
})

test("resolved cells selected on their own copy the server's exact amounts (§3.10)", () => {
  assert.deepEqual(copyBlock([{ r0: 2, c0: 1, r1: 2, c1: 4 }], ownerText, ownerEntry), [["80.5", "245", "115", "156"]])
  assert.deepEqual(copyBlock([{ r0: 4, c0: 1, r1: 4, c1: 2 }], ownerText, ownerEntry), [["94.5", "108"]])
  // pasted onto Family P1: the amounts become Family's prices
  const from = gridSelectionReducer(ownerStart(2, 1), { type: "click", r: 2, c: 4, shift: true })
  assert.deepEqual(copyThenPaste(from, ownerStart(5, 1)).written, [
    ["FAM", 5, 1, "80.5"],
    ["FAM", 5, 2, "245"],
    ["FAM", 5, 3, "115"],
    ["FAM", 5, 4, "156"],
  ])
})

test("a block is anchored at the top-left of the selection that holds the active cell, else at the active cell", () => {
  // Shift+ArrowRight ×3 from Standard P1: the active cell moved to P4, the block goes to P1
  assert.deepEqual(pasteOrigin({ active: { r: 0, c: 4 }, ranges: [{ r0: 0, c0: 1, r1: 0, c1: 4 }] }), { r: 0, c: 1 })
  assert.deepEqual(pasteOrigin({ active: { r: 3, c: 2 }, ranges: [{ r0: 3, c0: 2, r1: 3, c1: 2 }] }), { r: 3, c: 2 })
  assert.deepEqual(pasteOrigin({ active: { r: 1, c: 1 }, ranges: [] }), { r: 1, c: 1 })
})

// ─── paste planning ────────────────────────────────────────────────────────

test("one value fills the whole selection, each cell parsed in its context", () => {
  const sel = [
    { r: 3, c: 3 },
    { r: 3, c: 4 },
  ]
  assert.deepEqual(items(plan([["x1.40"]], { r: 3, c: 4 }, sel)), [
    [3, 3, "x1.40", "MULTIPLY 1.4"],
    [3, 4, "x1.40", "MULTIPLY 1.4"],
  ])
  // with nothing selected but the active cell, the value goes there
  assert.deepEqual(items(plan([["70"]], { r: 0, c: 1 })), [[0, 1, "70", "ABSOLUTE 70"]])
  // a copied empty cell clears the selection
  assert.deepEqual(items(plan([[""]], { r: 0, c: 1 }, [{ r: 0, c: 1 }])), [[0, 1, "", "clear"]])
})

test("a 2×2 block is anchored at the active cell", () => {
  assert.deepEqual(
    items(
      plan(
        [
          ["70", "80"],
          ["x1.1", "x1.2"],
        ],
        { r: 0, c: 1 },
      ),
    ),
    [
      [0, 1, "70", "ABSOLUTE 70"],
      [0, 2, "80", "ABSOLUTE 80"],
      [1, 1, "x1.1", "MULTIPLY 1.1"],
      [1, 2, "x1.2", "MULTIPLY 1.2"],
    ],
  )
  // a 1×4 block copied from a spreadsheet into Standard P1:P4
  assert.deepEqual(
    items(plan(decodeTSV("70\t80\t100\t130\r\n"), { r: 0, c: 1 })).map((x) => [x[1], x[3]]),
    [
      [1, "ABSOLUTE 70"],
      [2, "ABSOLUTE 80"],
      [3, "ABSOLUTE 100"],
      [4, "ABSOLUTE 130"],
    ],
  )
})

test("a block that overflows the editable cells is refused with SHAPE, and nothing is applied", () => {
  // 1×3 from Standard P3: only P3 and P4 are left
  assert.deepEqual(plan([["70", "80", "90"]], { r: 0, c: 3 }), { ok: false, code: "SHAPE", rows: 1, cols: 3, availableRows: 3, availableCols: 2 })
  // 4 rows from Standard: only three entry rows (Standard, Superior, Deluxe) are there
  assert.deepEqual(plan([["1"], ["2"], ["3"], ["4"]], { r: 0, c: 1 }), { ok: false, code: "SHAPE", rows: 4, cols: 1, availableRows: 3, availableCols: 4 })
  // a ragged block is as wide as its widest row; a cell a row does not have is not written
  assert.deepEqual(plan([["1"], ["2", "3", "4", "5", "6"]], { r: 0, c: 1 }), { ok: false, code: "SHAPE", rows: 2, cols: 5, availableRows: 3, availableCols: 4 })
  assert.deepEqual(
    items(plan([["70", "80"], ["x1.1"]], { r: 0, c: 1 })).map((x) => [x[0], x[1]]),
    [
      [0, 1],
      [0, 2],
      [1, 1],
    ],
  )
})

test("a block with an invalid cell applies nothing and names it: 'P3 · Superior'", () => {
  const res = plan(
    [
      ["80", "90"],
      ["x1.1", "abc"],
    ],
    { r: 0, c: 2 },
  )
  assert.deepEqual(res, { ok: false, code: "INVALID", count: 1, errors: [{ cell: { r: 1, c: 3 }, where: "P3 · Superior", text: "abc", code: "SYNTAX" }] })
})

test("at most three failures are named, and all of them are counted", () => {
  const res = plan([["a", "b", "c", "d"], ["x1.1", "e"]], { r: 0, c: 1 })
  assert.ok(!res.ok && res.code === "INVALID")
  assert.equal(PASTE_MAX_ERRORS, 3)
  assert.equal(res.count, 5)
  assert.deepEqual(
    res.errors.map((e) => e.where),
    ["P1 · Standard", "P2 · Standard", "P3 · Standard"],
  )
})

test("resolved rows are never paste targets", () => {
  // the active cell on Superior's resolved row: nowhere to anchor a block, nowhere to put a value
  assert.deepEqual(plan([["70", "80"]], { r: 2, c: 1 }), { ok: false, code: "NO_TARGET" })
  assert.deepEqual(plan([["70"]], { r: 2, c: 1 }), { ok: false, code: "NO_TARGET" })
  // a block from Superior's formula row goes on to Deluxe's formula row, over Superior's resolved row
  assert.deepEqual(
    items(plan([["x1.1"], ["x1.3"]], { r: 1, c: 1 })).map((x) => [x[0], x[1], x[3]]),
    [
      [1, 1, "MULTIPLY 1.1"],
      [3, 1, "MULTIPLY 1.3"],
    ],
  )
  // one value over a selection: only its editable cells are in it (useGridSelection's `selected`)
  assert.deepEqual(items(plan([["x1.2"]], { r: 2, c: 2 }, [{ r: 1, c: 2 }])), [[1, 2, "x1.2", "MULTIPLY 1.2"]])
  // a read-only version has no editable cell at all
  const none = planPaste([["70"]], { r: 0, c: 1 }, [], () => false, room(), bounds)
  assert.deepEqual(none, { ok: false, code: "NO_TARGET" })
})

test("'1.500' in a pasted price cell is AMBIGUOUS with minor units 2 and a price with 3 (O5)", () => {
  const two = plan([["1.500"]], { r: 0, c: 1 }, [], 2)
  assert.ok(!two.ok && two.code === "INVALID")
  assert.deepEqual(two.errors, [{ cell: { r: 0, c: 1 }, where: "P1 · Standard", text: "1.500", code: "AMBIGUOUS" }])
  assert.deepEqual(items(plan([["1.500"]], { r: 0, c: 1 }, [], 3)), [[0, 1, "1.500", "ABSOLUTE 1.5"]])
  // factors are exempt at any minor units
  assert.deepEqual(items(plan([["x1.500"]], { r: 1, c: 1 }, [], 2)), [[1, 1, "x1.500", "MULTIPLY 1.5"]])
})

test("an empty clipboard pastes nothing", () => {
  assert.deepEqual(plan([], { r: 0, c: 1 }), { ok: false, code: "EMPTY" })
  assert.deepEqual(plan([[]], { r: 0, c: 1 }), { ok: false, code: "EMPTY" })
})
