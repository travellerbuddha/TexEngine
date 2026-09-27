// A promotion code as the server keys it (O-31, `kamra.tex.pricing.promotions.code_key`): what the
// CRS and Call Center inputs keep while the agent types, and what they send.

/** Upper-cased with the Turkish dotted İ and dotless ı as I (a combining dot above an I dropped);
 *  letters of any alphabet (Ş, Ğ, Ü…), digits, "_" and "-" are kept, anything else is left out. */
export function normalisePromoCode(s: string): string {
  return s
    .normalize("NFC")
    .replace(/[İı]/g, "I")
    .toUpperCase()
    .replace(/İ/g, "I")
    .normalize("NFC")
    .replace(/[^\p{Lu}0-9_-]/gu, "")
}
