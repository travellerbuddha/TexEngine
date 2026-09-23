// Extras added after booking (G-22, ADR-034): display helpers shared by the add-extras
// drawer, the "Added after booking" card, the modification drawer and the revision history.
// No money arithmetic here: every amount is the server's string, only formatted.
import type { Params } from "../../../i18n"
import { money } from "../../../lib/format"
import { extraWarningText, isNightlyMode, shortDay } from "../../crs/lib/extrasStock"
import type { ExtraOutcome, Reason } from "../../crs/lib/types"
import type { AddonEntry } from "./types"

type T = (key: string, params?: Params) => string

/** Reservation statuses extras can still be added to (not arrived, not cancelled). */
export const ADDON_STATUSES = ["Confirmed", "Pending Payment", "Held"]

/** A count as sent ("2.000000" → "2"); never parsed into a float. */
export function qtyText(q: string | number | null | undefined): string {
  const s = String(q ?? "").trim()
  if (!/^\d+\.\d+$/.test(s)) return s || "—"
  return s.replace(/0+$/, "").replace(/\.$/, "")
}

/** The day(s) an added extra is used on: its service dates, else its one usage day. Nightly
 * extras are used every night of the stay, so none are listed. */
export function extraDays(e: Pick<ExtraOutcome, "service_dates" | "usage" | "pricing_mode">): string[] {
  if (e.service_dates?.length) return [...new Set(e.service_dates)].sort()
  if (isNightlyMode(e.pricing_mode)) return []
  return [...new Set((e.usage ?? []).map((u) => u.date))].sort()
}

/** "Spa × 2 (Tue 12 Jun)" */
export function extraText(e: ExtraOutcome): string {
  const days = extraDays(e)
  return `${e.name || e.code} × ${qtyText(e.quantity)}${days.length ? ` (${days.map((d) => shortDay(d)).join(", ")})` : ""}`
}

/** One add-on on a line: "Spa × 2 (Tue 12 Jun), Dinner × 1 · €120.00". */
export function addonText(a: AddonEntry): string {
  const xs = (a.quote?.extras ?? []).filter((e) => e.ok !== false).map(extraText).join(", ")
  return `${xs || a.id} · ${money(a.quote?.totals?.total, a.quote?.currency)}`
}

/** A refusal of crs.addon_propose in the agent's language when it is a known one (staff may
 * see how many are left); anything else as the server sent it. */
export function addonReasonText(t: T, r: Reason): string {
  const msg = r.message || ""
  const named = /^(.*?): (.*)$/.exec(msg)
  const name = named?.[1] ?? ""
  const rest = named?.[2] ?? ""
  switch (r.code) {
    case "ADDON_EMPTY":
      return t("res.addon.reason.empty")
    case "ADDON_SOLD_OUT":
      return extraWarningText(t, msg)
    case "ADDON_TOO_LATE": {
      const m = /^can no longer be added for (\d{4}-\d{2}-\d{2})$/.exec(rest)
      return m ? t("res.addon.reason.too_late", { name, date: shortDay(m[1]) }) : msg
    }
    case "ADDON_QUANTITY": {
      const m = /^at most (\d+) per stay$/.exec(rest)
      return m ? t("res.addon.reason.quantity", { name, count: Number(m[1]) }) : msg
    }
    case "ADDON_NOT_AVAILABLE":
      if (rest === "not available to add") return t("res.addon.reason.not_available", { name })
      if (rest === "included by the hotel") return t("res.addon.reason.included", { name })
      if (rest.startsWith("charged once per booking")) return t("res.addon.reason.first_room", { name })
      return msg
    default:
      return msg
  }
}
