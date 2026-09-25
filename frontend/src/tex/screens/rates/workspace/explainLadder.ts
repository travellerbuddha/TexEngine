// The Explain ladder of the Price test (PRICING_WORKSPACE_UX.md §3.13.1, D2, D14; slice S14): a
// quote's explanation steps, nights and totals mapped to the stages in the order the engine
// computes them, per night (engine.py: period, room, occupancy, board, period adjustment, rate
// plan, night cost, cost offers, markup, FX, promotions), then at stay level (cost offers,
// promotions, tax, the final price).
//
// Every value is a server string, shown as served: an explanation step's before/after, a night's
// fields (unit, subtotal_adults, subtotal_children, occupancy, subtotal_board, cost, cost_net,
// sell_contract, sell, final; GAP-12) or the quote's totals. Nothing is added, subtracted or
// multiplied here. A quote without a field (one stored before GAP-12) leaves that stage's
// before/after blank. The chain check compares canonical decimal strings (normaliseDecimal): a
// stage whose before differs from the previous amount-bearing stage's after is reported in
// `chainBreaks`, which is never "fixed" by computing.
//
// Pure: no runtime imports but shorthand.ts.
import { normaliseDecimal } from "../lib/shorthand.ts"
import type { ExplainStep, NightLine, PreviewResult } from "../lib/types.ts"

/** The per-night stages, in engine order (§3.13.1 rows 1–14). */
export const NIGHT_STAGES = [
  "base",
  "period",
  "room",
  "occupancy",
  "child",
  "combination",
  "board",
  "period_adjustment",
  "rate_plan",
  "night_cost",
  "cost_offers",
  "markup",
  "fx",
  "promotion",
] as const
/** The stay-level stages, after the nights (§3.13.1 rows 11, 14, 15 and the final price). */
export const STAY_STAGES = ["cost_offers", "promotion", "tax", "final"] as const

export type NightStageId = (typeof NIGHT_STAGES)[number]
export type StayStageId = (typeof STAY_STAGES)[number]
export type StageId = NightStageId | StayStageId

/** An explanation step shown under a stage: the step as served and its place in the explanation. */
export interface LadderLine {
  index: number
  step: ExplainStep
}

export interface LadderStage {
  id: StageId
  /** Served strings; null is blank (the stage has no such value, or the quote lacks the field). */
  before: string | null
  after: string | null
  /** False for the Period stage: it identifies the period and carries no amount. */
  amount: boolean
  /** The quote lacks the night field this stage reads (a quote from before GAP-12): before and
   * after are blank and the chain cannot be followed across it. */
  missing: boolean
  /** The currency of before and after: the contract's, or the sell currency (FX goes from one to
   * the other). */
  beforeCurrency: "contract" | "sell"
  afterCurrency: "contract" | "sell"
  lines: LadderLine[]
  /** Period and Period adjustment: the period's code and name (the PERIOD step's params). */
  period?: { code: string; name: string }
  /** Room: false when the room is priced by its own entered price (no derivation). */
  derived?: boolean
  /** Board: the supplement (nights[].board) and whether the board is the base board (included). */
  supplement?: string | null
  included?: boolean
  /** FX: the sell rate (fx.sell_rate). */
  rate?: string | null
  /** Tax: the tax amount (totals.tax); `included` when the prices include it. */
  tax?: string | null
}

export interface NightBlock {
  /** The nights of the block (ISO dates, consecutive nights with string-identical stages). */
  dates: string[]
  /** 1-based numbers of its first and last night in the stay. */
  first: number
  last: number
  /** The period code (nights[].period). */
  period: string
  stages: LadderStage[]
}

export interface ChainBreak {
  /** "night" (with its date) or "stay" */
  scope: "night" | "stay"
  night: string | null
  stage: StageId
  /** The stage's before (or its only value) and the previous stage's after, as served. */
  value: string
  previous: StageId
  previousAfter: string
}

export interface ExplainLadder {
  nights: NightBlock[]
  stay: LadderStage[]
  chainBreaks: ChainBreak[]
}

/** The step codes placed by name; any other code goes to the stage its `stage` field names (g). */
const PLACED = new Set([
  "PERIOD",
  "ROOM_ABSOLUTE",
  "ROOM_DERIVED",
  "ROOM_BASIS",
  "ADULT_SLOT",
  "CHILD_SLOT",
  "CHILD_INCLUDED",
  "CHILD_AS_ADULT",
  "COMBINATION_RULE",
  "OCCUPANCY_TOTAL",
  "BOARD_BASE",
  "BOARD_SUPPLEMENT",
  "PERIOD_ADJUSTMENT",
  "RATE_PLAN_ADJUSTMENT",
  "NIGHT_COST",
  "MARKUP",
  "MARKUP_STACK",
  "NO_MARKUP",
  "FX",
  "TAX",
  "TOTAL",
])

/** The server's step stage → the ladder stage an unplaced step is shown under. Stages with no
 * ladder stage (contract, extra, addon, unsellable) stay in the "Why this price" list only. */
const NIGHT_STAGE_OF: Record<string, NightStageId> = {
  period: "period",
  room: "room",
  occupancy: "occupancy",
  board: "board",
  rate_plan: "rate_plan",
  night: "night_cost",
  markup: "markup",
  fx: "fx",
  cost_offer: "cost_offers",
  promotion: "promotion",
  coupon: "promotion",
}
const STAY_STAGE_OF: Record<string, StayStageId> = {
  cost_offer: "cost_offers",
  promotion: "promotion",
  coupon: "promotion",
  tax: "tax",
  total: "final",
}

/** The stages that exist only when something happened there. */
const OPTIONAL: ReadonlySet<StageId> = new Set(["child", "combination", "period_adjustment", "rate_plan", "cost_offers"])

const has = (o: object, k: string) => Object.prototype.hasOwnProperty.call(o, k)
const str = (v: unknown): string | null => (typeof v === "string" ? v : v === null || v === undefined ? null : String(v))

/** A night field as served; null when the quote lacks it. */
function field(n: NightLine, k: keyof NightLine): string | null {
  return has(n, k) ? str(n[k]) : null
}

/** Canonical form of a served decimal string, or null when it cannot be read (then it is never
 * reported as a mismatch: the check only compares what it can read). */
function canon(s: string | null): string | null {
  if (s === null) return null
  const n = normaliseDecimal(s)
  return n.ok ? n.value : null
}

/** Two served decimal strings are the same number (compared as canonical strings). */
export function sameAmount(a: string | null, b: string | null): boolean | null {
  const x = canon(a)
  const y = canon(b)
  if (x === null || y === null) return null
  return x === y
}

function stage(id: StageId, lines: LadderLine[], p: Partial<LadderStage> = {}): LadderStage {
  return {
    id,
    before: null,
    after: null,
    amount: id !== "period",
    missing: false,
    beforeCurrency: "contract",
    afterCurrency: "contract",
    lines,
    ...p,
  }
}

const first = <T>(xs: T[]): T | undefined => xs[0]
const last = <T>(xs: T[]): T | undefined => xs[xs.length - 1]

/** The stages of one night, in engine order. `own`: the night's steps; `stayLevel`: steps without
 * a night that belong to every night (CHILD_AS_ADULT, FX, unplaced night-stage steps). */
function nightStages(q: PreviewResult, n: NightLine, own: LadderLine[], stayLevel: LadderLine[], withChildren: boolean, costOfferSteps: boolean): LadderStage[] {
  const code = (c: string) => own.filter((l) => l.step.code === c)
  const codes = (...cs: string[]) => own.filter((l) => cs.includes(l.step.code))
  const stayCode = (...cs: string[]) => stayLevel.filter((l) => cs.includes(l.step.code))
  const out = new Map<StageId, LadderStage>()

  // 1. Base: the root of the derivation chain (the first ROOM_ABSOLUTE of the night)
  const absolutes = code("ROOM_ABSOLUTE")
  const root = first(absolutes)
  out.set("base", stage("base", root ? [root] : [], { after: root ? str(root.step.after) : null }))

  // 2. Period: identification only
  const periodLine = first(code("PERIOD"))
  const pp = periodLine?.step.params ?? {}
  out.set(
    "period",
    stage("period", code("PERIOD"), { period: { code: str(pp.period) ?? n.period, name: str(pp.name) ?? "" } }),
  )

  // 3. Room: each derivation before → after, in chain order; else the entered price
  const derived = code("ROOM_DERIVED")
  const roomLines = [...absolutes.slice(1), ...derived]
  out.set(
    "room",
    derived.length
      ? stage("room", roomLines, { before: str(first(derived)!.step.before), after: str(last(derived)!.step.after), derived: true })
      : stage("room", roomLines, { after: field(n, "unit"), derived: false }),
  )

  // 4. Occupancy (adults): unit → subtotal_adults
  const adults = field(n, "subtotal_adults")
  out.set(
    "occupancy",
    stage("occupancy", codes("ROOM_BASIS", "ADULT_SLOT"), adults === null ? { missing: true } : { before: field(n, "unit"), after: adults }),
  )

  // 5. Child: subtotal_adults → subtotal_children (only when children travel)
  const childLines = [...codes("CHILD_SLOT", "CHILD_INCLUDED"), ...stayCode("CHILD_AS_ADULT")].sort((a, b) => a.index - b.index)
  if (withChildren || childLines.length) {
    const children = field(n, "subtotal_children")
    out.set(
      "child",
      stage("child", childLines, adults === null || children === null ? { missing: true } : { before: adults, after: children }),
    )
  }

  // 6. Special combination: the whole-combination rule's before → after
  const combo = first(code("COMBINATION_RULE"))
  if (combo) out.set("combination", stage("combination", [combo], { before: str(combo.step.before), after: str(combo.step.after) }))

  // the closing line of 4–6 (the occupancy total) goes under the last of them
  const total = code("OCCUPANCY_TOTAL")
  if (total.length) {
    const closing = out.get("combination") ?? out.get("child") ?? out.get("occupancy")!
    closing.lines = [...closing.lines, ...total]
  }

  // 7. Board: occupancy → subtotal_board; the supplement is nights[].board
  const boardLines = codes("BOARD_BASE", "BOARD_SUPPLEMENT")
  const board = field(n, "subtotal_board")
  out.set(
    "board",
    stage("board", boardLines, {
      ...(board === null ? { missing: true } : { before: field(n, "occupancy"), after: board }),
      supplement: field(n, "board"),
      included: boardLines.some((l) => l.step.code === "BOARD_BASE"),
    }),
  )

  // 8. Period adjustment (applied to occupancy + board)
  const adj = first(code("PERIOD_ADJUSTMENT"))
  if (adj) {
    const ap = adj.step.params ?? {}
    out.set(
      "period_adjustment",
      stage("period_adjustment", [adj], { before: str(adj.step.before), after: str(adj.step.after), period: { code: str(ap.period) ?? n.period, name: out.get("period")!.period!.name } }),
    )
  }

  // 9. Rate plan
  const rp = code("RATE_PLAN_ADJUSTMENT")
  if (rp.length) out.set("rate_plan", stage("rate_plan", rp, { before: str(first(rp)!.step.before), after: str(last(rp)!.step.after) }))

  // 10. Night cost: the contract cost of the night
  out.set("night_cost", stage("night_cost", code("NIGHT_COST"), { after: field(n, "cost") }))

  // 11. Cost offers: cost → cost_net (their steps are the stay's)
  const cost = field(n, "cost")
  const costNet = field(n, "cost_net")
  if (costOfferSteps || sameAmount(cost, costNet) === false) out.set("cost_offers", stage("cost_offers", [], { before: cost, after: costNet }))

  // 12. Markup: cost_net → sell_contract
  out.set("markup", stage("markup", codes("MARKUP", "MARKUP_STACK", "NO_MARKUP"), { before: costNet, after: field(n, "sell_contract") }))

  // 13. FX: sell_contract (contract currency) → sell (sell currency), with the rate
  out.set(
    "fx",
    stage("fx", stayCode("FX").filter((l) => (l.step.params?.use ?? "accommodation") === "accommodation"), {
      before: field(n, "sell_contract"),
      after: field(n, "sell"),
      afterCurrency: "sell",
      rate: str(q.fx?.sell_rate) ?? null,
    }),
  )

  // 14. Promotion: sell → final (the promotions' steps are the stay's)
  out.set("promotion", stage("promotion", [], { before: field(n, "sell"), after: field(n, "final"), beforeCurrency: "sell", afterCurrency: "sell" }))

  // (g) a step of a code not placed above goes under the stage its `stage` field names (an
  // optional stage it names is shown for it, without amounts)
  for (const l of [...own, ...stayLevel]) {
    if (PLACED.has(l.step.code)) continue
    const id = NIGHT_STAGE_OF[l.step.stage]
    const s = id ? (out.get(id) ?? (OPTIONAL.has(id) ? stage(id, []) : undefined)) : undefined
    if (!id || !s) continue
    s.lines = [...s.lines, l].sort((a, b) => a.index - b.index)
    out.set(id, s)
  }
  return NIGHT_STAGES.filter((id) => out.has(id)).map((id) => out.get(id)!)
}

/** The stay-level stages: cost offers and promotions (their steps' before → after), tax
 * (subtotal → total) and the final price (total). */
function stayStages(q: PreviewResult, stayLines: LadderLine[]): LadderStage[] {
  const tot = q.totals ?? {}
  const byStage = (id: StayStageId) => stayLines.filter((l) => STAY_STAGE_OF[l.step.stage] === id)
  const out: LadderStage[] = []
  const running = (lines: LadderLine[], id: StayStageId, ccy: "contract" | "sell") => {
    const amounts = lines.filter((l) => l.step.code === "PROMO_APPLIED" && l.step.before !== null && l.step.after !== null)
    return stage(id, lines, {
      before: amounts.length ? str(first(amounts)!.step.before) : null,
      after: amounts.length ? str(last(amounts)!.step.after) : null,
      beforeCurrency: ccy,
      afterCurrency: ccy,
    })
  }
  const cost = byStage("cost_offers")
  if (cost.length) out.push(running(cost, "cost_offers", "contract"))
  const promo = byStage("promotion")
  if (promo.length) out.push(running(promo, "promotion", "sell"))
  const taxLines = byStage("tax")
  const taxSteps = taxLines.filter((l) => l.step.code === "TAX")
  out.push(
    stage("tax", taxLines, {
      before: str(tot.subtotal),
      after: str(tot.total),
      tax: str(tot.tax),
      included: taxSteps.length > 0 && taxSteps.every((l) => str(l.step.params?.inc) !== null && str(l.step.params?.inc) !== ""),
      beforeCurrency: "sell",
      afterCurrency: "sell",
    }),
  )
  out.push(stage("final", byStage("final"), { after: str(tot.total), beforeCurrency: "sell", afterCurrency: "sell" }))
  return out
}

/** Which stages start a chain of their own (their before is not the previous stage's after):
 * the base price, and at stay level the cost offers (contract cost), the promotions (the sell
 * price) and the tax (the subtotal with extras and rounding). */
const CHAIN_START: ReadonlySet<string> = new Set(["night:base", "stay:cost_offers", "stay:promotion", "stay:tax"])

/** The chain check of one list of stages (§3.13.1): skips the Period identification; a stage
 * with a missing field breaks the chain (nothing to compare with); a stage with only a value
 * (Base, Night cost, the final price) is compared by that value; values are compared as
 * canonical decimal strings, and a value that cannot be read is not reported. */
function checkChain(stages: LadderStage[], scope: "night" | "stay", night: string | null): ChainBreak[] {
  const out: ChainBreak[] = []
  let prev: { id: StageId; after: string } | null = null
  for (const s of stages) {
    if (!s.amount) continue
    if (s.missing) {
      prev = null
      continue
    }
    const value = s.before ?? s.after
    if (value !== null && prev && !CHAIN_START.has(`${scope}:${s.id}`) && sameAmount(prev.after, value) === false)
      out.push({ scope, night, stage: s.id, value, previous: prev.id, previousAfter: prev.after })
    if (s.after !== null) prev = { id: s.id, after: s.after }
    else if (s.before !== null) prev = null
  }
  return out
}

/** A night's stages as a comparable string: values, facts and detail lines, not the date. */
function signature(period: string, stages: LadderStage[]): string {
  return JSON.stringify([
    period,
    stages.map((s) => [
      s.id,
      s.before,
      s.after,
      s.missing,
      s.period ?? null,
      s.derived ?? null,
      s.supplement ?? null,
      s.included ?? null,
      s.rate ?? null,
      s.lines.map((l) => [l.step.code, l.step.text, l.step.before, l.step.after, l.step.rule?.rule_id ?? null]),
    ]),
  ])
}

/**
 * The Explain ladder of a quote (§3.13.1): per night, the stages in engine order (consecutive
 * nights whose stages are string-identical form one block, "Nights 1–3 · P2"), then the stay's
 * stages, and the chain breaks of every night and of the stay block. An unsellable quote, or one
 * without nights (the guest view), has no night blocks.
 */
export function explainLadder(quote: PreviewResult): ExplainLadder {
  const steps = quote.explanation ?? []
  const lines: LadderLine[] = steps.map((step, index) => ({ index, step }))
  const byNight = new Map<string, LadderLine[]>()
  const stayLevel: LadderLine[] = []
  for (const l of lines) {
    if (l.step.night) {
      const xs = byNight.get(l.step.night) ?? []
      xs.push(l)
      byNight.set(l.step.night, xs)
    } else stayLevel.push(l)
  }
  const withChildren = (quote.request?.children?.length ?? 0) > 0
  const costOfferSteps = stayLevel.some((l) => l.step.stage === "cost_offer")
  // steps without a night that every night shows: CHILD_AS_ADULT, FX, and unplaced night stages
  const everyNight = stayLevel.filter((l) => l.step.code === "CHILD_AS_ADULT" || l.step.code === "FX" || (!PLACED.has(l.step.code) && !STAY_STAGE_OF[l.step.stage] && NIGHT_STAGE_OF[l.step.stage]))
  const stayOwn = stayLevel.filter((l) => !everyNight.includes(l))

  const blocks: NightBlock[] = []
  const breaks: ChainBreak[] = []
  let prevSig = ""
  ;(quote.nights ?? []).forEach((n, i) => {
    const stages = nightStages(quote, n, byNight.get(n.date) ?? [], everyNight, withChildren, costOfferSteps)
    breaks.push(...checkChain(stages, "night", n.date))
    const sig = signature(n.period, stages)
    const open = blocks[blocks.length - 1]
    if (open && sig === prevSig) {
      open.dates.push(n.date)
      open.last = i + 1
    } else blocks.push({ dates: [n.date], first: i + 1, last: i + 1, period: n.period, stages })
    prevSig = sig
  })
  const stay = quote.sellable === false ? [] : stayStages(quote, stayOwn)
  breaks.push(...checkChain(stay, "stay", null))
  // within the stay's cost offers and promotions, each applied offer starts from the previous one's result
  for (const s of stay) {
    const applied = s.lines.filter((l) => l.step.code === "PROMO_APPLIED" && l.step.before !== null && l.step.after !== null)
    for (let i = 1; i < applied.length; i++) {
      const before = str(applied[i].step.before)!
      const after = str(applied[i - 1].step.after)!
      if (sameAmount(after, before) === false) breaks.push({ scope: "stay", night: null, stage: s.id, value: before, previous: s.id, previousAfter: after })
    }
  }
  return { nights: blocks, stay, chainBreaks: breaks }
}
