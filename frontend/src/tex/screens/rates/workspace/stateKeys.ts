// The Pricing Workspace's cell states and entry error codes (PRICING_WORKSPACE_UX.md §3.20): the grids
// name a cell's state for assistive tech with t(`rates.ws.state.${state}`), t(`rates.occ.state.…`) or
// t(`rates.brd.state.…`), and an entry's refusal with t(`rates.sh.err.${code}`). Those keys are built at
// run time, so the TEX i18n check's literal scan does not see them: each grid's state is typed from the
// lists here, and tests/unit/state-keys.test.ts checks that every key they build is in all six
// catalogues (S16 review: "rates.occ.state.cost_hidden" was missing and read as the raw key).
import type { ShErrorCode } from "../lib/shorthand.ts"
import type { EntryError } from "./matrixView.ts"

/** The room price matrix's cell states (rates.ws.state.*). */
export const MATRIX_CELL_STATES = [
  "manual",
  "formula-default",
  "inherited",
  "period-override",
  "fixed-override",
  "inherit-rule",
  "empty",
  "missing",
  "resolved",
  "resolved_all",
  "unsellable",
  "no_price",
  "loading",
  "draft",
  "pending",
] as const
export type MatrixCellStateKey = (typeof MATRIX_CELL_STATES)[number]

/** The occupancy ladder's cell states (rates.occ.state.*). */
export const LADDER_CELL_STATES = [
  "rule",
  "period-override",
  "inherited",
  "inherit-rule",
  "general",
  "all-rooms",
  "policy",
  "default",
  "missing",
  "included",
  "draft",
  "resolved_all",
  "occ_resolved",
  "unsellable",
  "no_price",
  "no_party",
  "loading",
  "failed",
  "cost_hidden",
] as const
export type LadderCellStateKey = (typeof LADDER_CELL_STATES)[number]

/** The boards grid's cell states (rates.brd.state.*). */
export const BOARD_CELL_STATES = ["base", "rule", "period-override", "inherited", "pending", "empty", "no_value", "draft"] as const
export type BoardCellStateKey = (typeof BOARD_CELL_STATES)[number]

/** Every entry error a grid, popover or builder names with rates.sh.err.* (the shorthand's own and the matrix's). */
export const SH_ERROR_CODES = ["SYNTAX", "PLACES", "DIGITS", "RANGE", "AMBIGUOUS", "OP_NOT_ALLOWED", "BASE_NO_PRICE", "BASE_FORMULA", "NO_BASE_ROOM", "NEGATIVE", "NO_VALUE", "CHANGED", "PENDING"] as const
export type ShErrorKey = (typeof SH_ERROR_CODES)[number]
// the list holds every code the types allow (a new code without a key fails to compile)
type Complete<Union, Listed> = [Exclude<Union, Listed>] extends [never] ? true : never
export const SH_ERROR_CODES_COMPLETE: Complete<ShErrorCode | EntryError, ShErrorKey> = true

/** The i18n keys the grids build from these lists. */
export function stateKeys(): string[] {
  return [
    ...MATRIX_CELL_STATES.map((s) => `rates.ws.state.${s}`),
    ...LADDER_CELL_STATES.map((s) => `rates.occ.state.${s}`),
    ...BOARD_CELL_STATES.map((s) => `rates.brd.state.${s}`),
    ...SH_ERROR_CODES.map((c) => `rates.sh.err.${c}`),
  ]
}
