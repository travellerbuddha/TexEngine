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

export function acknowledgeGuestChange(reservation: string, note?: string) {
  return tex<{ ok: boolean }>("crs", "acknowledge_guest_change", { reservation, note }, { post: true })
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
