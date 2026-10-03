// The payments screen's amount helpers. Money stays a decimal string: they validate, compare against zero or
// subtract exactly (scaled BigInt), never through a float. Pure, no imports; unit tested with `node --test`
// (tests/unit/payment-amounts.test.ts).

/** "0", "0.00", "-0.0", "" → true. */
export function isZero(s: string | null | undefined) {
  return !s || /^[-+]?0*(\.0*)?$/.test(s.trim())
}

/** `a − b` of two decimal amounts, exactly (scaled BigInt), with `decimals` fraction digits:
 *  ("192.60", "187.6") → "5.00". */
export function minusAmount(a: string, b: string, decimals = 2): string {
  const scaled = (s: string) => {
    const [i, f = ""] = s.trim().split(".")
    return BigInt((i || "0") + (f + "0".repeat(decimals)).slice(0, decimals))
  }
  const d = scaled(a) - scaled(b)
  const neg = d < BigInt(0)
  const digits = (neg ? -d : d).toString().padStart(decimals + 1, "0")
  // a currency without decimals (VND, JPY) has no fraction part (LO-45)
  if (decimals === 0) return `${neg ? "-" : ""}${digits}`
  return `${neg ? "-" : ""}${digits.slice(0, -decimals)}.${digits.slice(-decimals)}`
}

/** A positive decimal with at most `decimals` fraction digits (string check only); a whole number when the
 * currency has none. */
export function isPositiveAmount(s: string, decimals = 2) {
  const v = s.trim()
  const pattern = decimals > 0 ? `^\\d+(\\.\\d{1,${decimals}})?$` : "^\\d+$"
  return new RegExp(pattern).test(v) && !isZero(v)
}
