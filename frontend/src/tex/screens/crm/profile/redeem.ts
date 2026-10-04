// The bookings a guest's points can be redeemed on, from the CRM (pure: no React, no DOM; tests/unit/crm-redeem).
import type { Stay } from "../types"

/** One stay per TEX booking points can pay part of: not cancelled, not a channel's (its price and payment are the
 * channel's: the server refuses it, LO-02; batch 2O), at a hotel the user takes payments for (and, given `hotels`,
 * one they see the guest through). */
export function redeemableBookings<S extends Pick<Stay, "property" | "status" | "tex_booking" | "channel_booking">>(
  stays: S[],
  can: (cap: string, property?: string) => boolean,
  hotels?: string[],
): S[] {
  const seen = new Set<string>()
  return stays.filter((s) => {
    if (!s.tex_booking || seen.has(s.tex_booking) || s.status === "Cancelled" || s.channel_booking) return false
    if (!can("payment.link", s.property) || (hotels && !hotels.includes(s.property))) return false
    seen.add(s.tex_booking)
    return true
  })
}
