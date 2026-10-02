// Guest refusal codes (G-70, ADR-013 amendment): what a refusal's stable code means to the booking app (the kind of
// recovery it offers) and the guest's text for it, `refusal.<CODE>` in every booking catalog, in the guest's
// language. The server's codes are kamra/tex/refusal_codes.py; its unit tests check that en.json has a text for
// exactly those codes. Pure: no DOM, no React.
import type { ErrorKind } from "./api.ts"
import { countryNames, regionDisplay } from "../../lib/residency.ts"

const kinds = (kind: ErrorKind, codes: string[]) => Object.fromEntries(codes.map((c) => [c, kind]))

/** The kind a code means, whatever the language of its message. A code missing here is classified by its HTTP
 * status (404 not found, 403 permission, else invalid). A market code (G-55b, O-8) is a refusal the search or
 * checkout recovers from, never "sold out": a quote of a market the site no longer sells is searched again
 * (expired); the others the search drops the link for, or checkout asks the guest's residence. */
export const KIND_BY_CODE: Readonly<Record<string, ErrorKind>> = {
  SOLD_OUT: "sold_out",
  EXTRA_SOLD_OUT: "extra_sold_out",
  // the offer, the quote or the rate is gone: the same rooms are searched or priced again
  ...kinds("expired", ["OFFER_INVALID", "OFFER_EXPIRED", "QUOTE_INVALID", "QUOTE_EXPIRED", "QUOTE_USED", "NOT_ON_SALE",
    "CONTRACT_NOT_ON_SALE", "CONTRACT_SUSPENDED", "RATE_UNAVAILABLE", "ROOM_NOT_SOLD", "SEARCH_AGAIN",
    "BASKET_NOT_TOGETHER", "PROPOSAL_EXPIRED", "MARKET_NOT_ALLOWED"]),
  ...kinds("invalid", ["MARKET_UNKNOWN", "MARKET_AMBIGUOUS", "MARKET_REQUIRED", "MARKET_RESIDENCY"]),
  // the guest chooses another way to pay
  ...kinds("payment_method", ["PAYMENT_METHOD_UNAVAILABLE", "PAY_AT_HOTEL_NOT_ALLOWED", "WEB_TRANSFER_ROOMS",
    "PAYMENT_START_FAILED"]),
  // the same step again in a moment (a payment the bank is reviewing waits for its answer instead: its own text)
  ...kinds("retry", ["BUSY", "PAYMENT_BUSY", "CHARGE_SUPERSEDED"]),
  // the time to pay is over: the rooms are given back
  ...kinds("hold_expired", ["HOLD_EXPIRED", "HOLD_EXPIRED_TRANSFER"]),
  ...kinds("not_found", ["SITE_NOT_FOUND", "NOT_FOUND", "LINK_INVALID", "PAYMENT_UNKNOWN"]),
  ...kinds("permission", ["NOT_PERMITTED", "MANAGE_LINK_INVALID", "MANAGE_LINK_EXPIRED", "MANAGE_RESERVATION_INVALID",
    "MANAGE_REQUEST_INVALID"]),
  RATE_LIMITED: "rate_limit",
}

/** What `refusalMessage` reads of an error (an ApiError, a FlowError). */
export interface Refused {
  code?: string | null
  params?: Record<string, unknown>
  message?: string
}

/** The parts of the booking app's i18n `refusalMessage` uses. */
export interface RefusalI18n {
  t: (key: never, vars?: Record<string, string | number>) => string
  locale: string
  day: (v: string) => string
  money: (amount: string | null | undefined, ccy: string | null | undefined) => string
}

const DAY = /^\d{4}-\d{2}-\d{2}$/
const AMOUNT = /^-?\d+(\.\d+)?$/

/** A refusal's params as the catalog's placeholders: a day in the guest's format, an amount with its currency,
 * countries by name; plain text and numbers as they are. Anything else is left out. */
export function refusalVars(params: Record<string, unknown> | undefined, i18n: Omit<RefusalI18n, "t">) {
  const p = params ?? {}
  const out: Record<string, string | number> = {}
  const ccy = typeof p.currency === "string" ? p.currency : null
  for (const [k, v] of Object.entries(p)) {
    if (k === "countries" && Array.isArray(v))
      out.countries = countryNames(v.filter((c): c is string => typeof c === "string"), regionDisplay(i18n.locale))
    else if (k === "date" && typeof v === "string" && DAY.test(v)) out.date = i18n.day(v)
    else if ((k === "amount" || k === "owed") && typeof v === "string" && AMOUNT.test(v)) out[k] = i18n.money(v, ccy)
    else if (typeof v === "string" || typeof v === "number") out[k] = v
  }
  return out
}

/** The guest's text for a refusal: its code's catalog text with its params; the server's message when the code has
 * no text or a placeholder no value (never a "{room}" on screen); `fallback` (default: errors.generic) without
 * either. */
export function refusalMessage(i18n: RefusalI18n, e: Refused | null | undefined, fallback?: string): string {
  const t = i18n.t as (key: string, vars?: Record<string, string | number>) => string
  const otherwise = e?.message || fallback || t("errors.generic")
  if (!e?.code) return otherwise
  const key = `refusal.${e.code}`
  const text = t(key, refusalVars(e.params, i18n))
  return text === key || /\{\w+\}/.test(text) ? otherwise : text
}
