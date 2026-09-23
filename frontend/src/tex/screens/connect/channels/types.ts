// Shapes of kamra.tex.api.distribution (G-69). Money arrives as decimal strings and is
// only ever displayed, never recomputed here (ADR-003).
import type { QueryState } from "../../../lib/api"

export type Environment = "Sandbox" | "Production"

export interface ChannelConnection {
  name: string
  label: string
  adapter: string
  enabled: number | boolean
  environment: Environment
  last_sync_at: string | null
  last_status: string | null
  last_error: string | null
  certified: boolean
  mappings: number
  queue: { Pending: number; Failed: number; Dead: number }
  inbound: { Received: number; Failed: number; Dead: number }
  webhook_url: string
}

export interface Overview {
  connections: ChannelConnection[]
  can_manage: boolean
}

export interface Mapping {
  name: string
  property: string
  connection: string
  enabled: number | boolean
  room_type: string
  external_room_code: string
  external_rate_code: string
  board: string
  rate_plan: string | null
  market: string
  sales_channel: string
  contract: string | null
  sell_currency: string
  /** "1,2" — adults priced */
  occupancies: string | null
  horizon_days: number | null
}

/** What save_mapping takes (name only when editing). */
export interface MappingInput {
  name?: string
  connection: string
  enabled: 0 | 1
  room_type: string
  external_room_code: string
  external_rate_code: string
  board: string
  rate_plan: string | null
  market: string
  sales_channel: string
  contract: string | null
  sell_currency: string
  occupancies: string
  horizon_days: number
}

export interface Lookups {
  room_types: { name: string; room_type_name: string }[]
  rate_plans: { name: string; rate_plan_name: string }[]
  markets: { name: string; market_name: string }[]
  channels: { name: string; channel_name: string; channel_group: string | null }[]
  contracts: { name: string; contract_code: string; contract_name: string; market: string | null; status: string }[]
  currency: string | null
  boards: string[]
  adapter: { key: string; environment: Environment; sandbox: boolean }
}

export interface AriRate {
  adults: number
  /** decimal string, e.g. "123.45" */
  price: string
}

export interface AriDay {
  date: string
  available: number
  closed: boolean
  cta: boolean
  ctd: boolean
  min_los: number | null
  max_los: number | null
  currency: string | null
  rates: AriRate[]
  in_sync: boolean
  sent: boolean
}

export interface AriPreview {
  mapping: string
  days: AriDay[]
}

export type InboundStatus = "Received" | "Applied" | "Failed" | "Dead" | "Ignored"
export type InboundEvent = "new" | "modified" | "cancelled"

export interface InboundRoom {
  room_code: string | null
  rate_code: string | null
  check_in: string | null
  check_out: string | null
  adults: number | null
  /** decimal string as the channel sent it */
  total: string | null
  currency: string | null
  line_ref: string | null
}

export interface InboundRow {
  name: string
  provider_ref: string
  event: InboundEvent
  status: InboundStatus
  attempts: number | null
  received_at: string | null
  applied_at: string | null
  booking: string | null
  warning: string | null
  last_error: string | null
  rooms: InboundRoom[]
  /** null when the viewer may not see guest data (crm.view) */
  guest_name: string | null
}

export interface InboundPage {
  rows: InboundRow[]
  total: number
}

export type MismatchKind = "missing_in_tex" | "status_differs" | "total_differs" | "missing_in_channel" | "ari_drift"

export interface Mismatch {
  kind: MismatchKind
  key: string
  // ari_drift
  mapping?: string
  date?: string
  pushed?: boolean
  // missing_in_tex
  inbound_status?: string | null
  // status_differs / total_differs (channel vs TEX) and missing_in_channel
  channel?: string | null
  tex?: string | null
  booking?: string | null
  status?: string | null
}

export interface ReconcileResult {
  mismatches: Mismatch[]
  total: number
}

export interface PushResult {
  queued: number
}

export interface SendResult {
  pushed: number
  failed: number
  waiting: number
}

export interface ApplyResult {
  applied: number
  failed: number
}

export interface SandboxResult {
  received: number
  duplicates: number
}

/** TEX's neutral booking message (what the sandbox channel sends). */
export interface SandboxRoom {
  room_code: string
  rate_code: string
  check_in: string
  check_out: string
  adults: number
  children_ages: number[]
  total: string
  currency: string
  line_ref: string
}

export interface SandboxMessage {
  provider_ref: string
  status: InboundEvent
  channel_name: string
  guest: { first_name: string; last_name: string; email: string; phone: string; country: string }
  rooms: SandboxRoom[]
  notes: string
}

export type ChannelTab = "mappings" | "ari" | "bookings" | "reconcile" | "sandbox"

/** What every tab of a connection's detail page receives. */
export interface TabProps {
  connection: string
  conn: ChannelConnection
  lookups: QueryState<Lookups>
  mappings: QueryState<Mapping[]>
  /** channel.manage at the connection's hotel (the server re-checks every write) */
  canManage: boolean
  /** queues or inbound counts may have changed: refresh the connection's summary */
  onChanged: () => void
  goTo: (tab: ChannelTab) => void
}
