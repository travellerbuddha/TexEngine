import { refusalMessage, type RefusalI18n, type Refused } from "./refusals.ts"
import type { Basket, PaymentMethod } from "../types"

/** The methods the checkout can offer (anything else the server lists is left out). */
export const KNOWN_METHODS: ReadonlySet<string> = new Set(["Card", "Bank Transfer", "Pay at Hotel"])

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
 * What the checkout offers while the server basket is not read yet: the card, nothing else (O-15; a basket that
 * could not be read offers nothing, ``checkoutChoices``, LO-14). The hotel's
 * payment method rules decide which methods it sells (a transfer, pay at the hotel); the server refuses a method
 * they do not offer, so a guess here would show a hotel's guest a choice that books nothing. No account and no
 * amount: the server decides both when the guest books.
 */
export function fallbackChoices(): PayChoice[] {
  return [{ method: "Card", account: null, via: null, dueNow: null, later: null, sandbox: false }]
}

/**
 * The checkout's payment choices from the server basket (LO-14): its available methods once it is read; none when it
 * could not be read (``failed``: the guest is told and may read it again, never offered a method the hotel may not
 * sell); the card (``fallbackChoices``) while it is not read yet, as before.
 */
export function checkoutChoices(basket: { status: string; data: Basket | null }): { choices: PayChoice[]; failed: boolean } {
  if (basket.data) {
    const avail = basket.data.methods.filter((m) => m.available && KNOWN_METHODS.has(m.method))
    return {
      choices: avail.map((m) => ({
        method: m.method as PaymentMethod,
        account: m.provider_account,
        via: avail.filter((x) => x.method === m.method).length > 1 ? m.label : null,
        dueNow: m.due_now,
        later: m.balance_after,
        sandbox: m.sandbox,
      })),
      failed: false,
    }
  }
  if (basket.status === "error") return { choices: [], failed: true }
  return { choices: fallbackChoices(), failed: false }
}

/**
 * What the checkout says when the basket could not be read (LO-14): a rate limit asks the guest to wait, a coded
 * refusal is told in its own words (G-70b); anything else is the connection's, as before. Trying again then does
 * not fail the same way unexplained.
 */
export function basketFailureText(i18n: RefusalI18n, error: (Refused & { kind?: string }) | null | undefined): { title: string; body: string } {
  const t = i18n.t as (key: string) => string
  if (error?.kind === "rate_limit") return { title: t("errors.rateLimitTitle"), body: t("errors.rateLimitBody") }
  if (error?.code) return { title: t("payment.optionsFailedTitle"), body: refusalMessage(i18n, error) }
  return { title: t("payment.optionsFailedTitle"), body: t("payment.optionsFailedBody") }
}

/**
 * A refusal neither a retry nor a refresh clears (§6P, batch 2Q): the rate itself cannot be sold now (a fixed amount
 * the hotel cannot convert, a payload that fails its check). Its own text asks for a new search, and the checkout
 * offers one ("See available rooms") where it offered "Try again" or "Refresh prices", each failing the same way.
 */
export function searchesAgain(error: { code?: string | null } | null | undefined): boolean {
  return error?.code === "RATE_UNAVAILABLE"
}

/**
 * The refresh a basket asks for (§5b, §6G3; batch 2P): read, but its quotes used or expired since they were made. The
 * code of its rooms' problem goes with it, a price already booked first: refreshing that one would book the stay a
 * second time. Null when nothing is to refresh.
 */
export function basketExpiry(basket: { status: string; data: Basket | null }): { code: string | null; message: string } | null {
  if (!basket.data || basket.data.usable) return null
  const codes = basket.data.rooms.map((r) => r.problem_code).filter((c): c is string => Boolean(c))
  return { code: codes.includes("QUOTE_USED") ? "QUOTE_USED" : (codes[0] ?? null), message: "" }
}
