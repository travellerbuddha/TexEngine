// Small pieces shared by the channel distribution screens (G-69).
import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { ArrowRight, ChevronLeft, ChevronRight, ShieldAlert } from "lucide-react"
import { num } from "../../../lib/format"
import { useSession } from "../../../lib/session"
import { useTexT } from "../../../i18n"
import { Badge, Button, Notice, type Tone } from "../../../ui"
import type { ChannelConnection, InboundEvent, InboundStatus, Lookups, Mapping } from "./types"

type T = (key: string, params?: Record<string, string | number>) => string

/** Adapter name for staff (admin.adapters needs connect.admin, so labels live in i18n). */
export function adapterLabel(t: T, key: string) {
  const k = `connect.channels.adapter.${key}`
  const v = t(k)
  return v === k ? key : v
}

/** Uncertified adapter: nothing reaches a real channel (real providers are blocked). */
export function CertificationNotice() {
  const { t } = useTexT()
  return (
    <Notice
      tone="warning"
      title={
        <span className="inline-flex items-center gap-1.5">
          <ShieldAlert className="size-4 shrink-0" aria-hidden />
          {t("connect.channels.uncertified.title")}
        </span>
      }
    >
      {t("connect.channels.uncertified.body")}
    </Notice>
  )
}

export function EnvBadge({ env }: { env: string }) {
  const { t } = useTexT()
  return env === "Production" ? <Badge tone="brand">{t("connect.env.production")}</Badge> : <Badge tone="info">{t("connect.env.sandbox")}</Badge>
}

export function EnabledBadge({ enabled }: { enabled: number | boolean }) {
  const { t } = useTexT()
  return enabled ? <Badge tone="success">{t("connect.enabled")}</Badge> : <Badge tone="neutral">{t("connect.disabled")}</Badge>
}

const COUNT_TONE: Record<string, Tone> = { Pending: "warning", Received: "info", Failed: "danger", Dead: "danger" }

/** A labelled group of count badges ("Pending 3 · Failed 0 · Dead 0"). Zero reads neutral. */
export function CountBadges({ label, counts, keyPrefix }: { label: string; counts: Record<string, number>; keyPrefix: string }) {
  const { t } = useTexT()
  return (
    <ul aria-label={label} className="flex flex-wrap gap-1.5">
      {Object.entries(counts).map(([status, n]) => (
        <li key={status}>
          <Badge tone={n > 0 ? (COUNT_TONE[status] ?? "neutral") : "neutral"}>
            {t(`${keyPrefix}.${status.toLowerCase()}`)}
            <span className="font-semibold tabular-nums">{num(n)}</span>
          </Badge>
        </li>
      ))}
    </ul>
  )
}

/** Queue + inbound counts of a connection, as two labelled rows. Dead ARI jobs stay on
 * record (the count never goes down); their errors and a retry are in the delivery
 * monitor, which needs connect.admin, so everyone else learns how their days get resent. */
export function ConnectionCounts({ conn }: { conn: ChannelConnection }) {
  const { t } = useTexT()
  const { can } = useSession()
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="w-full text-xs font-medium text-zinc-500 sm:w-32">{t("connect.channels.queue")}</span>
        <CountBadges label={t("connect.channels.queue")} counts={conn.queue} keyPrefix="connect.channels.queue_status" />
      </div>
      {conn.queue.Dead > 0 && (
        <p className="text-xs text-zinc-600 sm:pl-34">
          {t("connect.channels.queue_dead_hint")}
          {can("connect.admin") && (
            <>
              {" "}
              <Link to="/tex/connect/outbox" className="inline-flex items-center gap-0.5 font-medium whitespace-nowrap text-tex-700 hover:underline">
                {t("connect.channels.queue_dead_link")} <ArrowRight className="size-3.5" aria-hidden />
              </Link>
            </>
          )}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="w-full text-xs font-medium text-zinc-500 sm:w-32">{t("connect.channels.inbound")}</span>
        <CountBadges label={t("connect.channels.inbound")} counts={conn.inbound} keyPrefix="connect.channels.inbound_status" />
      </div>
    </div>
  )
}

export function syncTone(status: string | null): Tone {
  if (!status) return "neutral"
  return status === "Sent" || status === "OK" ? "success" : status === "Failed" ? "danger" : "info"
}

/** "12–24 of 60" + previous / next (server-side paging). */
export function Pager({ start, pageSize, total, onChange }: { start: number; pageSize: number; total: number; onChange: (start: number) => void }) {
  const { t } = useTexT()
  if (total <= pageSize && start === 0) return null
  const from = total ? start + 1 : 0
  const to = Math.min(start + pageSize, total)
  return (
    <nav aria-label={t("connect.channels.pager.label")} className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-100 px-4 py-2.5 text-sm">
      <p className="text-zinc-600" aria-live="polite">
        {t("connect.channels.pager.range", { from: num(from), to: num(to), total: num(total) })}
      </p>
      <div className="flex gap-2">
        <Button variant="secondary" size="sm" icon={<ChevronLeft className="size-4" aria-hidden />} disabled={start === 0} onClick={() => onChange(Math.max(0, start - pageSize))}>
          {t("connect.channels.pager.prev")}
        </Button>
        <Button variant="secondary" size="sm" disabled={start + pageSize >= total} onClick={() => onChange(start + pageSize)}>
          {t("connect.channels.pager.next")}
          <ChevronRight className="size-4" aria-hidden />
        </Button>
      </div>
    </nav>
  )
}

/** Channel codes of a mapping: "DBL / BAR". */
export function mappingCodes(m: Pick<Mapping, "external_room_code" | "external_rate_code">) {
  return `${m.external_room_code} / ${m.external_rate_code}`
}

/** Display names for lookup values (falls back to the stored value). */
export function useLookupNames(lookups: Lookups | undefined) {
  const byName = <R extends { name: string }>(rows: R[] | undefined, field: keyof R) => {
    const m = new Map<string, string>()
    for (const r of rows ?? []) m.set(r.name, String(r[field] ?? r.name))
    return (v: string | null | undefined) => (v ? (m.get(v) ?? v) : "")
  }
  return {
    roomType: byName(lookups?.room_types, "room_type_name"),
    ratePlan: byName(lookups?.rate_plans, "rate_plan_name"),
    market: byName(lookups?.markets, "market_name"),
    channel: byName(lookups?.channels, "channel_name"),
    contract: (v: string | null | undefined) => {
      if (!v) return ""
      const c = lookups?.contracts.find((x) => x.name === v)
      return c ? `${c.contract_code} · ${c.contract_name}` : v
    },
  }
}

/** Label + value row used in compact detail blocks. */
export function Fact({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium text-zinc-500">{label}</dt>
      <dd className="mt-0.5 text-sm break-words text-zinc-900">{children}</dd>
    </div>
  )
}

const STATUS_TONE: Record<InboundStatus, Tone> = { Received: "info", Applied: "success", Failed: "danger", Dead: "danger", Ignored: "neutral" }
const EVENT_TONE: Record<InboundEvent, Tone> = { new: "info", modified: "warning", cancelled: "neutral" }

export function InboundStatusBadge({ status }: { status: string }) {
  const { t } = useTexT()
  const s = status as InboundStatus
  return <Badge tone={STATUS_TONE[s] ?? "neutral"}>{STATUS_TONE[s] ? t(`connect.channels.inbound_status.${s.toLowerCase()}`) : status}</Badge>
}

export function EventBadge({ event }: { event: string }) {
  const { t } = useTexT()
  const e = event as InboundEvent
  return <Badge tone={EVENT_TONE[e] ?? "neutral"}>{EVENT_TONE[e] ? t(`connect.channels.event.${e}`) : event}</Badge>
}

/** A TEX booking reference; a link when the viewer may open reservations. */
export function BookingRef({ name }: { name: string | null | undefined }) {
  const { can } = useSession()
  if (!name) return <span className="text-zinc-500">—</span>
  if (!can("reservation.view")) return <span className="font-mono text-xs whitespace-nowrap">{name}</span>
  return (
    <Link to={`/tex/reservations/booking/${encodeURIComponent(name)}`} className="font-mono text-xs font-medium whitespace-nowrap text-tex-700 hover:underline">
      {name}
    </Link>
  )
}
