// Which notices the payment-link page shows, from the link as the server reads it and the
// gateway's `status` in the return URL (K2, audit 1c-son). A link whose booking could not take its
// money (parked for the hotel, or refunded: `late_payment`) shows that notice alone — never
// "confirming your payment…" nor "ask the hotel for a new link" beside it.
import type { LatePayment } from "../types"

export type LinkNotices = { payable: boolean; paid: boolean; failed: boolean; verifying: boolean; late: boolean; closed: boolean }

export function payLinkNotices(link: { status: string; late_payment?: LatePayment | null }, status: string | null): LinkNotices {
  const payable = link.status === "Active" || link.status === "Partially Paid"
  const paid = link.status === "Paid"
  const late = Boolean(link.late_payment)
  return {
    payable,
    paid,
    failed: status === "failed" && payable,
    verifying: !late && (status === "pending" || status === "unverified" || (status === "succeeded" && !paid)),
    late,
    closed: !late && !payable && !paid,
  }
}
