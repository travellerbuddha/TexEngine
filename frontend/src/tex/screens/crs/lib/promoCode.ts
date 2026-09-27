// A promotion code as the server keys it (O-31, `kamra.tex.pricing.promotions.code_key`): what the
// CRS and Call Center inputs keep while the agent types, and what they send.

/** Upper-cased with the Turkish dotted İ and dotless ı as I (every combining dot above an I dropped);
 *  letters of any alphabet (Ş, Ğ, Ü…), digits, "_" and "-" are kept, anything else is left out. */
export function normalisePromoCode(s: string): string {
  let key = s.normalize("NFC")
  // to a fixed point, as the server: stacked dots above (İ + U+0307 …) turn back into İ under NFC (2D-1)
  for (let pass = 0; pass < key.length + 2; pass++) {
    const step = key.replace(/[İı]/g, "I").toUpperCase().replace(/I\u0307/g, "I").normalize("NFC")
    if (step === key) break
    key = step
  }
  return key.replace(/[^\p{Lu}0-9_-]/gu, "")
}

