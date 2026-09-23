import { useState } from "react"
import { AlertTriangle, Inbox, PlayCircle, RefreshCw, RotateCcw } from "lucide-react"
import { tex, TexApiError, useTexQuery } from "../../../lib/api"
import { date, dateTime } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Button, CardBody, DataTable, EmptyState, ErrorState, Money, Segmented, useToast } from "../../../ui"
import { BookingRef, EventBadge, InboundStatusBadge, Pager } from "./common"
import type { ApplyResult, InboundPage, InboundRoom, InboundRow, InboundStatus, TabProps } from "./types"

const PAGE = 25
type Filter = "" | InboundStatus

function RoomLine({ room }: { room: InboundRoom }) {
  const { t } = useTexT()
  return (
    <li className="text-xs">
      <span className="font-mono font-medium text-zinc-900">
        {room.room_code || "—"} / {room.rate_code || "—"}
      </span>
      <span className="block text-zinc-600">
        {date(room.check_in, "short")} → {date(room.check_out, "short")}
        {room.adults ? ` · ${t("connect.channels.ari.adults", { count: room.adults })}` : ""}
      </span>
      {room.total && (
        <span className="block">
          <Money amount={room.total} currency={room.currency} />
        </span>
      )}
    </li>
  )
}

function Notes({ row }: { row: InboundRow }) {
  const { t } = useTexT()
  if (!row.warning && !row.last_error) return <span className="text-zinc-500">—</span>
  return (
    <span className="flex max-w-xs flex-col gap-1">
      {row.warning && (
        <span className="flex items-start gap-1 rounded-md bg-amber-50 px-1.5 py-1 text-xs break-words text-amber-900 ring-1 ring-amber-200 ring-inset">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {row.warning}
        </span>
      )}
      {row.last_error && (
        <details>
          <summary className="cursor-pointer text-xs font-medium text-rose-800">{t("connect.channels.inbound.show_error")}</summary>
          <p className="mt-1 text-xs break-words whitespace-pre-wrap text-zinc-700">{row.last_error}</p>
        </details>
      )}
    </span>
  )
}

/** Booking messages the channel sent, as stored and applied (the inbound log). */
export function InboundTab({ connection, canManage, onChanged }: TabProps) {
  const { t } = useTexT()
  const toast = useToast()
  const [status, setStatus] = useState<Filter>("")
  const [start, setStart] = useState(0)
  const q = useTexQuery<InboundPage>("distribution", "inbound", { connection, status: status || undefined, start, limit: PAGE }, [connection, status, start])
  const [retrying, setRetrying] = useState<string | null>(null)
  const [applying, setApplying] = useState(false)

  const retry = async (r: InboundRow) => {
    setRetrying(r.name)
    try {
      await tex("distribution", "retry_inbound", { name: r.name }, { post: true })
      toast.success(t("connect.channels.inbound.retried"))
      q.reload()
      onChanged()
    } catch (e) {
      toast.error((e as TexApiError).message)
    } finally {
      setRetrying(null)
    }
  }

  const applyNow = async () => {
    setApplying(true)
    try {
      const r = await tex<ApplyResult>("distribution", "apply_now", { connection }, { post: true })
      const msg = t("connect.channels.inbound.applied", { applied: r.applied, failed: r.failed })
      if (r.failed) toast.error(msg)
      else toast.success(msg)
      q.reload()
      onChanged()
    } catch (e) {
      toast.error((e as TexApiError).message)
    } finally {
      setApplying(false)
    }
  }

  const retryButton = (r: InboundRow) => (
    <Button
      variant="secondary"
      size="sm"
      icon={<RotateCcw className="size-3.5" aria-hidden />}
      loading={retrying === r.name}
      aria-label={t("connect.channels.inbound.retry_named", { ref: r.provider_ref })}
      onClick={() => retry(r)}
    >
      {t("connect.outbox.retry")}
    </Button>
  )
  const canRetry = (r: InboundRow) => canManage && (r.status === "Failed" || r.status === "Dead")

  return (
    <>
      <CardBody className="space-y-3 border-b border-zinc-100">
        <p className="text-sm text-zinc-600">{t("connect.channels.inbound.hint")}</p>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Segmented<Filter>
            label={t("connect.channels.inbound.filter")}
            value={status}
            size="sm"
            onChange={(v) => {
              setStatus(v)
              setStart(0)
            }}
            options={[
              { value: "", label: t("connect.outbox.all") },
              ...(["Received", "Applied", "Failed", "Dead", "Ignored"] as const).map((s) => ({ value: s, label: t(`connect.channels.inbound_status.${s.toLowerCase()}`) })),
            ]}
          />
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" icon={<RefreshCw className="size-3.5" aria-hidden />} onClick={q.reload} loading={q.loading && !!q.data}>
              {t("core.action.refresh")}
            </Button>
            {canManage && (
              <Button size="sm" icon={<PlayCircle className="size-3.5" aria-hidden />} onClick={applyNow} loading={applying}>
                {t("connect.channels.inbound.apply_now")}
              </Button>
            )}
          </div>
        </div>
      </CardBody>
      {q.error ? (
        <ErrorState error={q.error} onRetry={q.reload} />
      ) : (
        <>
          <DataTable<InboundRow>
            caption={t("connect.channels.tab.bookings")}
            rows={q.data?.rows}
            loading={q.loading}
            rowKey={(r) => r.name}
            dense
            rowClassName={(r) => (r.warning ? "bg-amber-50/40" : undefined)}
            empty={
              <EmptyState
                icon={<Inbox className="size-5" />}
                title={status ? t("connect.channels.inbound.empty_filtered") : t("connect.channels.inbound.empty")}
                description={t("connect.channels.inbound.empty_hint")}
              />
            }
            columns={[
              {
                key: "ref",
                header: t("connect.channels.inbound.col.ref"),
                cell: (r) => (
                  <span className="flex flex-col items-start gap-1">
                    <span className="font-mono text-xs font-medium break-all text-zinc-900">{r.provider_ref}</span>
                    <EventBadge event={r.event} />
                    {r.booking && (
                      <span className="sm:hidden">
                        <BookingRef name={r.booking} />
                      </span>
                    )}
                    <span className="text-xs whitespace-nowrap text-zinc-500 md:hidden">{dateTime(r.received_at)}</span>
                    {r.warning && (
                      <span className="flex items-start gap-1 text-xs text-amber-900 md:hidden">
                        <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                        {r.warning}
                      </span>
                    )}
                    {r.last_error && <span className="line-clamp-2 text-xs break-words text-rose-800 md:hidden">{r.last_error}</span>}
                  </span>
                ),
              },
              {
                key: "status",
                header: t("connect.channels.inbound.col.status"),
                cell: (r) => (
                  <span className="flex flex-col items-start gap-1">
                    <InboundStatusBadge status={r.status} />
                    {(r.attempts ?? 0) > 0 && <span className="text-xs text-zinc-500">{t("connect.channels.inbound.attempts", { count: r.attempts ?? 0 })}</span>}
                    {canRetry(r) && <span className="sm:hidden">{retryButton(r)}</span>}
                  </span>
                ),
              },
              {
                key: "rooms",
                header: t("connect.channels.inbound.col.rooms"),
                cell: (r) =>
                  r.rooms.length ? (
                    <ul className="space-y-1.5">
                      {r.rooms.map((room, i) => (
                        <RoomLine key={room.line_ref ?? i} room={room} />
                      ))}
                    </ul>
                  ) : (
                    <span className="text-zinc-500">—</span>
                  ),
              },
              {
                key: "guest",
                header: t("connect.channels.inbound.col.guest"),
                hideBelow: "lg",
                cell: (r) => (r.guest_name === null ? <span className="text-xs text-zinc-500 italic">{t("connect.channels.inbound.guest_hidden")}</span> : r.guest_name || "—"),
              },
              { key: "booking", header: t("connect.channels.inbound.col.booking"), hideBelow: "sm", cell: (r) => <BookingRef name={r.booking} /> },
              {
                key: "times",
                header: t("connect.channels.inbound.col.times"),
                hideBelow: "md",
                cell: (r) => (
                  <span className="text-xs whitespace-nowrap">
                    <span className="block">{t("connect.channels.inbound.received_at", { when: dateTime(r.received_at) })}</span>
                    {r.applied_at && <span className="block text-zinc-500">{t("connect.channels.inbound.applied_at", { when: dateTime(r.applied_at) })}</span>}
                  </span>
                ),
              },
              { key: "notes", header: t("connect.channels.inbound.col.notes"), hideBelow: "md", cell: (r) => <Notes row={r} /> },
              ...(canManage
                ? [
                    {
                      key: "actions",
                      header: <span className="sr-only">{t("connect.outbox.col.actions")}</span>,
                      align: "right" as const,
                      hideBelow: "sm" as const,
                      cell: (r: InboundRow) => (canRetry(r) ? retryButton(r) : null),
                    },
                  ]
                : []),
            ]}
          />
          {q.data && <Pager start={start} pageSize={PAGE} total={q.data.total} onChange={setStart} />}
        </>
      )}
    </>
  )
}
