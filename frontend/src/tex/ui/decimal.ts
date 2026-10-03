// The text a DecimalInput takes while it is typed. Pure, no imports; unit tested with `node --test`
// (tests/unit/decimal-input.test.ts).

/** Digits, then a point and up to `decimals` fraction digits (a point alone while typing); with no decimals
 * (VND, JPY) no point at all: a dialog's check would refuse it, with nothing said (2K-6 review N4). */
export function decimalPattern(decimals: number, allowNegative = false): RegExp {
  const fraction = decimals > 0 ? `(\\.\\d{0,${decimals}})?` : ""
  return new RegExp(`^${allowNegative ? "-?" : ""}\\d*${fraction}$`)
}
