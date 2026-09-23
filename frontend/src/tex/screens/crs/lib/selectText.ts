// What happened when an offer was assigned to the rooms of a multi-room party (R-29),
// in words for a toast / live region. Nothing is guessed: rooms the offer does not fit
// or has no stock for stay open for the agent to fill with another offer.
import type { Params } from "../../../i18n"
import type { SelectResult } from "./useBookingFlow"
import type { Offer } from "./types"

type T = (key: string, params?: Params) => string

export const roomList = (idx: number[]) => idx.map((i) => i + 1).join(", ")

export function selectMessage(t: T, res: SelectResult, offer: Offer, roomCount: number): { tone: "info" | "warning"; text: string } | null {
  const picks = res.selection?.picks ?? []
  const missing = picks.length ? picks.map((p, i) => (p ? -1 : i)).filter((i) => i >= 0) : []
  if (!res.assigned.length) {
    if (res.noStock.length) return { tone: "warning", text: t("crs.sel.no_stock", { count: res.noStock.length, rooms: roomList(res.noStock) }) }
    const reason = offer.room_reasons?.find((r) => res.unfit.includes(r.room_index))?.message
    return { tone: "warning", text: t("crs.sel.unfit", { count: res.unfit.length, rooms: roomList(res.unfit), reason: reason ?? "" }) }
  }
  if (roomCount <= 1 || !missing.length) return null
  const parts = [t("crs.sel.assigned", { count: res.assigned.length, rooms: roomList(res.assigned) })]
  if (res.noStock.length) parts.push(t("crs.sel.no_stock_rest", { count: offer.available }))
  parts.push(t("crs.sel.missing", { count: missing.length, rooms: roomList(missing) }))
  return { tone: "info", text: parts.join(" ") }
}
