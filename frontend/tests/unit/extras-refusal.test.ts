// §6G3 (batch 2Q): why a limited extra was not added came as text only ("sold out on 2027-06-02"), which the booking
// app parsed to tell the guest in their language; a quote now carries its code and day (`reason_code`,
// `reason_date`), which decide. A quote made before keeps its text, read as before. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { refusalText } from "../../src/booking/lib/extras.ts"

const i18n = {
  t: (key: string, params?: Record<string, unknown>) => `${key} ${JSON.stringify(params ?? {})}`,
  day: (v: string) => `day(${v})`,
} as unknown as Parameters<typeof refusalText>[0]

test("an extra's refusal is told by its code and day, else by its text", () => {
  assert.equal(refusalText(i18n, "ausverkauft", { reasonCode: "SOLD_OUT", reasonDate: "2027-06-02" }), 'extras.reasonSoldOut {"date":"day(2027-06-02)"}')
  assert.equal(refusalText(i18n, "", { reasonCode: "NOT_ENOUGH", reasonDate: "2027-06-03" }), 'extras.reasonFewLeft {"date":"day(2027-06-03)"}')
  assert.equal(refusalText(i18n, "", { reasonCode: "CLOSED", reasonDate: "2027-06-04" }), 'extras.reasonClosed {"date":"day(2027-06-04)"}')
  // a quote made before the codes: its text, as before; anything else is "not available"
  assert.equal(refusalText(i18n, "not enough left on 2027-06-03"), 'extras.reasonFewLeft {"date":"day(2027-06-03)"}')
  assert.equal(refusalText(i18n, "not available", { reasonCode: "", reasonDate: "" }), "extras.reasonOther {}")
})
