// Shapes returned by kamra.tex.api.payments (and the CRS booking lookups used to
// pick a booking). Amounts are decimal strings in the transaction currency.

export type TxnStatus = "Pending" | "Succeeded" | "Failed" | "Cancelled"
export type TxnType = "Charge" | "Refund" | "Void"
export type TxnMethod = "Card" | "Bank Transfer" | "Pay at Hotel" | "Payment Link" | "Manual"

export const TXN_STATUSES: TxnStatus[] = ["Pending", "Succeeded", "Failed", "Cancelled"]
export const TXN_METHODS: TxnMethod[] = ["Card", "Bank Transfer", "Pay at Hotel", "Payment Link", "Manual"]

export interface Txn {
  name: string
  property: string
  txn_type: TxnType
  status: TxnStatus
  method: TxnMethod
  currency: string
  provider: string | null
  provider_ref: string | null
  booking: string | null
  payment_link: string | null
  card_brand: string | null
  card_last4: string | null
  error_code: string | null
  error_message: string | null
  reason: string | null
  parent_transaction: string | null
  actor: string | null
  amount: string
  created: string
  completed_at: string | null
}

export interface Allocation {
  name: string
  allocation_type: "Allocate" | "Transfer" | "Refund" | "Release"
  amount: string
  currency: string
  booking: string | null
  reason: string | null
  actor: string | null
  creation: string
}

export interface TxnDetail extends Txn {
  allocations: Allocation[]
  refunds: Txn[]
  unallocated: string
  /** In `refund_currency`: a successful charge, or a capture TEX refused to count (G-67). */
  refundable: string
  refund_currency: string
  /** Bookings holding part of this payment now, and how much (G-68). */
  booking_nets: Record<string, string>
}

export type LinkStatus = "Draft" | "Active" | "Partially Paid" | "Paid" | "Expired" | "Cancelled"
export const LINK_STATUSES: LinkStatus[] = ["Active", "Partially Paid", "Paid", "Expired", "Cancelled", "Draft"]

export interface PayLink {
  name: string
  status: LinkStatus
  amount: string
  paid_amount: string
  currency: string
  description: string | null
  expires_at: string | null
  booking: string | null
  reservation: string | null
  guest_name: string | null
  guest_email: string | null
  /** Empty once the backend stops storing bearer URLs (use reissue_link). */
  public_url: string | null
  creation: string
}

export interface CreatedLink {
  link: string
  url?: string
  token?: string
  replay?: boolean
  emailed?: boolean
}

export interface MethodOption {
  method: string
  provider_account: string | null
  provider: string | null
  label: string
  sandbox: boolean
}

export type Provider = "Mock" | "iyzico" | "Sipay" | "Virtual POS" | "Bank Transfer" | "Pay at Hotel"
export const PROVIDERS: Provider[] = ["Mock", "Bank Transfer", "Pay at Hotel", "iyzico", "Sipay", "Virtual POS"]
export const GATEWAYS: Provider[] = ["iyzico", "Sipay", "Virtual POS"]

export const SECRET_FIELDS = ["secret_key", "merchant_key", "store_key", "webhook_secret"] as const
export type SecretField = (typeof SECRET_FIELDS)[number]

export interface Account {
  name: string
  label: string
  property: string
  provider: Provider
  environment: "Sandbox" | "Production"
  enabled: 0 | 1
  currencies: string | null
  api_key: string | null
  terminal_id: string | null
  bank_code: string | null
  gateway_url: string | null
  bank_name: string | null
  iban: string | null
  account_holder: string | null
  transfer_instructions: string | null
  secrets_set: Record<SecretField, boolean>
  production_verified: boolean
  /** Why the account cannot take new payments now (ADR-042); its open payments still settle. */
  problem: "unknown" | "mock" | "uncertified" | "gateway_url" | "sandbox_host" | "sandbox_live_site" | null
}

export interface Rule {
  name: string
  method: "Card" | "Bank Transfer" | "Pay at Hotel"
  provider_account: string | null
  market: string | null
  currency: string | null
  sales_channel: string | null
  priority: number | null
  disabled: 0 | 1
}

export interface AccountsResponse {
  accounts: Account[]
  rules: Rule[]
}

/** kamra.tex.api.crs.reservations row (subset). */
export interface ReservationRow {
  name: string
  property: string
  status: string
  guest: string | null
  guest_name: string | null
  room_type_name: string | null
  check_in_date: string
  check_out_date: string
  tex_booking: string | null
  tex_currency: string | null
  total: string
}

/** kamra.tex.api.crs.booking (subset). */
export interface BookingSummary {
  booking: string
  status: string
  property: string
  currency: string
  total: string
  paid: string
  balance: string
  due_now: string
  payment_status: string | null
  booker_name: string | null
  rooms: { reservation: string; check_in: string; check_out: string; status: string }[]
}
