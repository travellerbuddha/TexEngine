// Unit tests for the rate-plan row's refundable flag taken from its rate plan and cancellation
// policy (Y-4, ADR-067). Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { planRowIssues, planRowRefundable, withPlanRefundable } from "../../src/tex/screens/rates/workspace/rows.ts"
import type { Row } from "../../src/tex/screens/rates/lib/types.ts"

const plans = [
  { name: "FLEX", tex_refundable: 1 },
  { name: "NRF", tex_refundable: 0 },
  { name: "OLD", tex_refundable: null },
]
const policies = [
  { name: "CXL-FREE", refundable: 1 },
  { name: "CXL-NRF", refundable: 0 },
]
const row = (key: string, patch: Record<string, string | number | null> = {}): Row => ({
  _key: key,
  rate_plan: "",
  op: "",
  value: "",
  refundable: 1,
  boards: "",
  cancellation_policy: "",
  payment_policy: "",
  ...patch,
})

test("a row is refundable only when its rate plan and its own policy both are", () => {
  assert.equal(planRowRefundable(plans[0], undefined), 1)
  assert.equal(planRowRefundable(plans[1], undefined), 0)
  assert.equal(planRowRefundable(plans[2], undefined), 1) // a plan without the flag is refundable
  assert.equal(planRowRefundable(undefined, undefined), 1)
  assert.equal(planRowRefundable(plans[0], policies[1]), 0)
  assert.equal(planRowRefundable(plans[1], policies[0]), 0)
  assert.equal(planRowRefundable(plans[0], policies[0]), 1)
})

test("choosing a rate plan or a policy sets the flag; other rows and a hand-set flag are kept", () => {
  const prev = [row("a", { rate_plan: "FLEX" }), row("b")]
  // a new row's rate plan is picked: the non-refundable plan clears the flag
  let next = withPlanRefundable(prev, [prev[0], { ...prev[1], rate_plan: "NRF" }], plans, policies)
  assert.deepEqual(next.map((r) => r.refundable), [1, 0])
  // a non-refundable policy on the refundable plan clears it too
  next = withPlanRefundable(next, [{ ...next[0], cancellation_policy: "CXL-NRF" }, next[1]], plans, policies)
  assert.deepEqual(next.map((r) => r.refundable), [0, 0])
  // the user ticks it again by hand: kept (the server then refuses the publish)
  const hand = withPlanRefundable(next, [{ ...next[0], refundable: 1 }, next[1]], plans, policies)
  assert.deepEqual(hand.map((r) => r.refundable), [1, 0])
  // a new row added with a rate plan takes its flag; one without keeps the default
  const added = withPlanRefundable(hand, [...hand, row("c", { rate_plan: "NRF" }), row("d")], plans, policies)
  assert.deepEqual(added.map((r) => r.refundable), [1, 0, 0, 1])
})

test("a row without its own policy takes the rate plan's default policy (O-2b)", () => {
  const withDefaults = [{ name: "FLEX", tex_refundable: 1, tex_cancellation_policy: "CXL-NRF" }, { name: "SAVE", tex_refundable: 1, tex_cancellation_policy: "CXL-FREE" }]
  const prev = [row("a")]
  // the plan is refundable, its default policy is not: the server would refuse the publish
  let next = withPlanRefundable(prev, [{ ...prev[0], rate_plan: "FLEX" }], withDefaults, policies)
  assert.equal(next[0].refundable, 0)
  // the row's own refundable policy wins over the plan's default
  next = withPlanRefundable(next, [{ ...next[0], cancellation_policy: "CXL-FREE" }], withDefaults, policies)
  assert.equal(next[0].refundable, 1)
  // a plan whose default policy is refundable
  next = withPlanRefundable([row("b")], [{ ...row("b"), rate_plan: "SAVE" }], withDefaults, policies)
  assert.equal(next[0].refundable, 1)
})

test("a rate plan's issues are listed under its row (O-2b)", () => {
  const issues = [
    { level: "WARNING" as const, code: "RATE_PLAN_REFUNDABLE", message: "w", ref: { rate_plan: "NRF" } },
    { level: "ERROR" as const, code: "POLICY_CURRENCY", message: "e", ref: { rate_plan: "FLEX" } },
    { level: "ERROR" as const, code: "SALE_WINDOW", message: "s" },
  ]
  assert.deepEqual(planRowIssues(issues, "FLEX"), { issues: [issues[1]], tone: "danger" })
  assert.deepEqual(planRowIssues(issues, "NRF"), { issues: [issues[0]], tone: "warning" })
  assert.deepEqual(planRowIssues(issues, ""), { issues: [], tone: undefined })
  assert.deepEqual(planRowIssues(undefined, "FLEX"), { issues: [], tone: undefined })
})
