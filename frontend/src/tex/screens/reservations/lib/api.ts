import { tex } from "../../../lib/api"
import { UI_CRS } from "../../crs/lib/api"
import type {
  AddonApplyResult,
  AddonOptions,
  AddonProposal,
  AddonRequest,
  ApplyResult,
  CancelPreview,
  CancelResult,
  ContractVersionInfo,
  GuestChangeRequest,
  Proposal,
  ReservationDetail,
  ReservationRow,
  Simulation,
} from "./types"

export interface ListArgs {
  property?: string
  q?: string
  status?: string
  arrival_from?: string
  arrival_to?: string
  pending_only?: 0 | 1
  limit: number
  start: number
}

export function listReservations(args: ListArgs, signal?: AbortSignal) {
  return tex<ReservationRow[]>("crs", "reservations", { ...args }, { signal })
}

export function getReservation(name: string) {
  return tex<ReservationDetail>(UI_CRS, "reservation", { name })
}

export type Basis = "CURRENT" | "ORIGINAL_VERSION" | "ORIGINAL_SALE_DATE" | "HISTORICAL_SALE_DATE"

export function proposeModification(reservation: string, changes: Record<string, unknown>, basis: Basis, basis_sale_at?: string) {
  return tex<Proposal>("crs", "propose_modification", { reservation, changes, basis, basis_sale_at }, { post: true })
}

export function applyModification(proposal_token: string, reason: string, override_amount?: string) {
  return tex<ApplyResult>("crs", "apply_modification", { proposal_token, reason, override_amount }, { post: true })
}

export function simulate(reservation: string, sale_at: string) {
  return tex<Simulation>("crs", "simulate", { reservation, sale_at })
}

export function cancellationPreview(reservation: string) {
  return tex<CancelPreview>("crs", "cancellation_preview", { reservation })
}

export function cancelReservation(reservation: string, reason: string, waive_penalty: boolean) {
  return tex<CancelResult>("crs", "cancel", { reservation, reason, waive_penalty: waive_penalty ? 1 : 0 }, { post: true })
}

/** Correct the amount (and currency) an imported stay was locked at: price.override, a reason,
 * a revision and an audit event (ADR-052 review). Amounts travel as strings. */
export function correctImportedAmount(reservation: string, amount: string, reason: string, currency?: string) {
  return tex<{ reservation: string; revision: string; old_amount: string; new_amount: string; currency: string }>(
    "crs",
    "correct_imported_amount",
    { reservation, amount, reason, currency },
    { post: true },
  )
}

export function acknowledgeGuestChange(reservation: string, note?: string) {
  return tex<{ ok: boolean }>("crs", "acknowledge_guest_change", { reservation, note }, { post: true })
}

// ─── a guest's own changes and their money (G-45, ADR-044) ─────────────

/** The guest's change requests of a reservation, newest first (reservation.view). */
export function guestChangeRequests(reservation: string, signal?: AbortSignal) {
  return tex<GuestChangeRequest[]>("crs", "guest_change_requests", { reservation }, { signal })
}

export type ResolveAction = "approve" | "reject" | "close"
export type ResolveSettlement = "Refund" | "Credit on booking"
/** What the gateway did with a refund it never confirmed (staff checked it there). */
export type RefundOutcome = "Succeeded" | "Failed"

/** Approve / reject a request waiting for the hotel (reservation.modify; a refund also needs
 * payment.refund), or close money left to staff (payment.refund; a refund the gateway never
 * confirmed needs its outcome). The reason is audited. */
/** What became of money left to staff, said when they close it (G-93). */
export type StaffMoney = "Refunded outside TEX" | "Kept on the booking"

export function resolveGuestChange(request: string, action: ResolveAction, reason: string, settlement?: ResolveSettlement, refund_outcome?: RefundOutcome, staff_money?: StaffMoney) {
  return tex<GuestChangeRequest>("crs", "resolve_guest_change", { request, action, reason, settlement, refund_outcome, staff_money }, { post: true })
}

export function contractVersion(name: string) {
  return tex<ContractVersionInfo>("contracts", "get_version", { name })
}

export interface ResendResult {
  booking: string
  /** true when the e-mail queue took the message — queued, not yet sent (ADR-047); false when
   * nothing could be queued (e.g. no outgoing mail account). The new link replaced the old one anyway. */
  queued: boolean
  status: "Queued" | "Failed"
  email: string
}

/** Re-send the booking e-mail with a NEW manage link; the old link stops working. */
export function resendConfirmation(booking: string) {
  return tex<ResendResult>("crs", "resend_confirmation", { booking }, { post: true })
}

// ─── extras added after booking (G-22, ADR-034) ─────────────────────────

/** What can be added to the reservation now, with what is left of limited extras per day. */
export function addonOptions(reservation: string, signal?: AbortSignal) {
  return tex<AddonOptions>("crs", "addon_options", { reservation }, { signal })
}

/** Price extras on their own (the stay stays price-locked); a signed 30-minute proposal. */
export function addonPropose(reservation: string, extras: AddonRequest[]) {
  return tex<AddonProposal>("crs", "addon_propose", { reservation, extras }, { post: true })
}

/** Add the proposed extras; the booking's balance grows by their total. */
export function addonApply(proposal_token: string, reason?: string) {
  return tex<AddonApplyResult>("crs", "addon_apply", { proposal_token, reason }, { post: true })
}
