import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { ArrowDownLeft, ArrowUpRight, MessagesSquare, Search } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { dateTime } from "../../lib/format"
import { useHotelScope } from "../../lib/hotelScope"
import { useTexT } from "../../i18n"
import { Badge, Card, DataTable, EmptyState, ErrorState, Field, Input, PageHeader, Select, Toolbar, type Tone } from "../../ui"
import { CrmNav, Pager } from "./components/common"
import { basisKey, channelKey, directionKey } from "./profile/Communications"
import type { CommChannel, CommDirection, ConsentBasis } from "./types"

interface CommRow {
  name: string
  guest: string
  guest_name: string | null
  property: string
  channel: CommChannel
  direction: CommDirection
  status: string
  consent_basis: ConsentBasis
  subject: string | null
  template: string | null
  sent_at: string | null
  creation: string
  actor: string | null
  actor_name: string | null
  /** The viewer may open the guest's profile (a booking at one of their hotels). */
  guest_openable: boolean
  booking: string | null
  reservation: string | null
  delivery_error: string | null
}

const CAPS = ["crm.view"] as const
const CHANNELS: CommChannel[] = ["Email", "Phone", "Note", "SMS", "WhatsApp"]
const STATUSES = ["Queued", "Sent", "Delivered", "Failed", "Logged"] as const
const DIRECTIONS: CommDirection[] = ["Outbound", "Inbound", "Internal"]
// "Queued" is waiting in the outgoing queue, never shown as a success (ADR-047)
const STATUS_TONE: Record<string, Tone> = { Queued: "info", Sent: "success", Delivered: "success", Failed: "danger", Logged: "neutral" }
const PAGE = 50

/** Guest communications across guests (R-35 CRM › Communications, R-37, G-64): e-mails the
 * platform sent and calls, notes and messages staff logged, at the hotels where the user may
 * see guests (crm.view, checked by the server). The message itself stays on the guest's
 * profile, which each row opens. */
export default function Communications() {
  const { t } = useTexT()
  const navigate = useNavigate()
  const hotels = useHotelScope(CAPS)
  const [channel, setChannel] = useState("")
  const [status, setStatus] = useState("")
  const [direction, setDirection] = useState("")
  const [q, setQ] = useState("")
  const [term, setTerm] = useState("")
  const [start, setStart] = useState(0)
  useEffect(() => {
    const h = window.setTimeout(() => setTerm(q.trim()), 300)
    return () => window.clearTimeout(h)
  }, [q])
  useEffect(() => setStart(0), [channel, status, direction, term, hotels.property])
  const list = useTexQuery<{ rows: CommRow[]; total: number }>(
    "lists",
    "communications",
    { property: hotels.property, channel: channel || undefined, status: status || undefined, direction: direction || undefined, q: term || undefined, start, limit: PAGE },
    [hotels.property, channel, status, direction, term, start],
  )
  const filtered = Boolean(channel || status || direction || term)

  return (
    <>
      <PageHeader
        title={t("core.nav.sub.communications")}
        subtitle={t("crm.comms.subtitle")}
        crumbs={[{ label: t("core.nav.crm"), to: "/tex/crm" }, { label: t("core.nav.sub.communications") }]}
      />
      <CrmNav />
      <Toolbar>
        <Field label={t("core.action.search")} className="w-full sm:w-64">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-zinc-400" aria-hidden />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("crm.comms.search_ph")} className="pl-8" type="search" />
          </div>
        </Field>
        <Field label={t("crm.comm.channel")} className="w-[calc(50%-0.375rem)] sm:w-40">
          <Select value={channel} onChange={(e) => setChannel(e.target.value)} options={CHANNELS.map((c) => ({ value: c, label: t(channelKey(c)) }))} placeholder={t("core.label.all")} />
        </Field>
        <Field label={t("core.label.status")} className="w-[calc(50%-0.375rem)] sm:w-40">
          <Select value={status} onChange={(e) => setStatus(e.target.value)} options={STATUSES.map((s) => ({ value: s, label: t(`crm.comm.status.${s.toLowerCase()}`) }))} placeholder={t("core.label.all")} />
        </Field>
        <Field label={t("crm.comm.direction")} className="w-full sm:w-40">
          <Select value={direction} onChange={(e) => setDirection(e.target.value)} options={DIRECTIONS.map((d) => ({ value: d, label: t(directionKey(d)) }))} placeholder={t("core.label.all")} />
        </Field>
        {hotels.control && <div className="self-end">{hotels.control}</div>}
      </Toolbar>
      <Card>
        {list.error ? (
          <ErrorState error={list.error} onRetry={list.reload} />
        ) : (
          <>
            <DataTable<CommRow>
              caption={t("core.nav.sub.communications")}
              rows={list.data?.rows}
              loading={list.loading}
              rowKey={(r) => r.name}
              onRowClick={(r) => navigate(`/tex/crm/guests/${encodeURIComponent(r.guest)}`)}
              rowClickable={(r) => r.guest_openable}
              empty={<EmptyState icon={<MessagesSquare className="size-5" />} title={filtered ? t("crm.comms.none_filtered") : t("crm.comm.empty")} description={filtered ? undefined : t("crm.comms.empty_hint")} />}
              columns={[
                {
                  key: "when",
                  header: t("crm.comms.col.when"),
                  hideBelow: "sm",
                  cell: (r) => <span className="whitespace-nowrap text-zinc-700">{dateTime(r.sent_at || r.creation)}</span>,
                },
                {
                  key: "guest",
                  header: t("crm.col.guest"),
                  cell: (r) => (
                    <span className="min-w-0">
                      <span className="font-medium text-zinc-900">{r.guest_name || r.guest}</span>
                      {!r.guest_openable && <span className="block text-xs text-zinc-500">{t("crm.comms.not_openable")}</span>}
                      <span className="block text-xs whitespace-nowrap text-zinc-500 sm:hidden">{dateTime(r.sent_at || r.creation)}</span>
                      {hotels.all && <span className="block text-xs text-zinc-500">{hotels.hotelName(r.property)}</span>}
                    </span>
                  ),
                },
                {
                  key: "subject",
                  header: t("crm.comm.subject"),
                  cell: (r) => (
                    <span className="min-w-0">
                      <span className="line-clamp-1 max-w-72 text-zinc-900">{r.subject || r.template || t(channelKey(r.channel))}</span>
                      {r.booking && <span className="block font-mono text-xs text-zinc-500">{r.booking}</span>}
                    </span>
                  ),
                },
                {
                  key: "channel",
                  header: t("crm.comm.channel"),
                  hideBelow: "sm",
                  cell: (r) => (
                    <Badge tone="neutral">
                      {r.direction === "Inbound" ? <ArrowDownLeft className="size-3" aria-hidden /> : r.direction === "Outbound" ? <ArrowUpRight className="size-3" aria-hidden /> : null}
                      {t(channelKey(r.channel))} · {t(directionKey(r.direction))}
                    </Badge>
                  ),
                },
                {
                  key: "status",
                  header: t("core.label.status"),
                  cell: (r) => (
                    <span title={r.delivery_error ? t("crm.comm.delivery_error", { reason: r.delivery_error }) : undefined}>
                      <Badge tone={STATUS_TONE[r.status] ?? "neutral"}>{t(`crm.comm.status.${r.status.toLowerCase()}`)}</Badge>
                    </span>
                  ),
                },
                { key: "basis", header: t("crm.comm.basis"), hideBelow: "lg", cell: (r) => <Badge tone={r.consent_basis === "Marketing" ? "brand" : "info"}>{t(basisKey(r.consent_basis))}</Badge> },
                { key: "actor", header: t("crm.comms.col.by"), hideBelow: "lg", cell: (r) => <span className="text-zinc-600">{r.actor_name || t("crm.comms.system")}</span> },
              ]}
            />
            <Pager start={start} pageSize={PAGE} total={list.data?.total ?? 0} onChange={setStart} />
          </>
        )}
      </Card>
    </>
  )
}
