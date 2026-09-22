// Human wording for the frozen rate-plan policies the server returns. Only dates and
// percentages are described here; amounts always come from the server.
import type { I18n, MessageKey } from "../i18n"
import type { RatePlanInfo, Reason } from "../types"
import { addDays, today } from "./dates"

const BOARDS: Record<string, MessageKey> = {
  RO: "board.RO",
  BB: "board.BB",
  HB: "board.HB",
  FB: "board.FB",
  AI: "board.AI",
  UAI: "board.UAI",
}

export function boardLabel(t: I18n["t"], code: string | null | undefined) {
  if (!code) return ""
  const k = BOARDS[code]
  return k ? t(k) : code
}

export interface CancelInfo {
  refundable: boolean
  /** free cancellation up to and including this day */
  freeUntil: string | null
  text: string
}

export function cancellation(i18n: I18n, info: RatePlanInfo | null | undefined, checkIn: string): CancelInfo {
  const { t, date } = i18n
  if (info && info.refundable === false) return { refundable: false, freeUntil: null, text: t("policy.nonRefundable") }
  const rules = (info?.cancellation_policy?.rules ?? []).filter((r) => Number.isInteger(Number(r.days_before_arrival)))
  if (!rules.length) return { refundable: true, freeUntil: null, text: t("policy.freeCancellation") }
  const days = Math.max(...rules.map((r) => Number(r.days_before_arrival)))
  if (days >= 3650) return { refundable: false, freeUntil: null, text: t("policy.nonRefundable") }
  const until = addDays(checkIn, -days)
  if (until < today()) return { refundable: true, freeUntil: null, text: t("policy.feeApplies") }
  return { refundable: true, freeUntil: until, text: t("policy.freeUntil", { date: date(until, { day: "numeric", month: "long", year: "numeric" }) }) }
}

export function paymentTerms(i18n: I18n, info: RatePlanInfo | null | undefined, currency: string) {
  const { t, money } = i18n
  const p = info?.payment_policy
  const kind = (p?.deposit_type || "FULL").toUpperCase()
  const v = p?.deposit_value ?? ""
  let text: string
  if (kind === "NONE") text = t("policy.payNothingNow")
  else if (kind === "PERCENT") text = t("policy.depositPercent", { percent: v.replace(/\.0+$/, "") })
  else if (kind === "FIXED") text = t("policy.depositFixed", { amount: money(v, currency) })
  else if (kind === "NIGHTS") text = t("policy.depositNights", { count: Number.parseInt(v || "1", 10) || 1 })
  else text = t("policy.payInFull")
  return { text, payAtHotel: !!p?.allow_pay_at_hotel || kind === "NONE" }
}

const REASONS: Record<string, MessageKey> = {
  SOLD_OUT: "reason.soldOut",
  MIN_LOS: "reason.minStay",
  MAX_LOS: "reason.maxStay",
  MIN_ADVANCE: "reason.advance",
  MAX_ADVANCE: "reason.advance",
  RELEASE: "reason.advance",
  STOP_SELL: "reason.closed",
  STOP_SELL_ARRIVAL: "reason.noArrival",
  STOP_SELL_DEPARTURE: "reason.noDeparture",
  MAX_ADULTS: "reason.occupancy",
  MAX_CHILDREN: "reason.occupancy",
  MAX_OCCUPANTS: "reason.occupancy",
  MIN_ADULTS: "reason.occupancy",
}

export function reasonText(t: I18n["t"], reasons: Reason[] | undefined, multiRoom = false) {
  const r = reasons?.[0]
  if (!r) return t("reason.unavailable")
  const k = REASONS[r.code]
  // with several rooms, a room type is offered only when it fits every room's guests
  if (k === "reason.occupancy" && multiRoom) return t("reason.occupancyMulti")
  return k ? t(k) : t("reason.unavailable")
}
