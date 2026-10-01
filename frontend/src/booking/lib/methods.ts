import type { PaymentMethod } from "../types"

/** One payment choice of the checkout: a method, the account behind it and what it asks now. */
export interface PayChoice {
  method: PaymentMethod
  account: string | null
  /** gateway label when several accounts offer the same method */
  via: string | null
  dueNow: string | null
  later: string | null
  sandbox: boolean
}

/**
 * What the checkout offers when the server basket cannot be read: the card, nothing else (O-15). The hotel's
 * payment method rules decide which methods it sells (a transfer, pay at the hotel); the server refuses a method
 * they do not offer, so a guess here would show a hotel's guest a choice that books nothing. No account and no
 * amount: the server decides both when the guest books.
 */
export function fallbackChoices(): PayChoice[] {
  return [{ method: "Card", account: null, via: null, dueNow: null, later: null, sandbox: false }]
}
