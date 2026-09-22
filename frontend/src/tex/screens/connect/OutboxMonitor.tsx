import { useState } from "react"
import { RefreshCw, RotateCcw } from "lucide-react"
import { tex, TexApiError, useTexQuery } from "../../lib/api"
import { useSession } from "../../lib/session"
import { dateTime } from "../../lib/format"
import { useTexT } from "../../i18n"
import { Badge, Button, Card, CardHeader, DataTable, EmptyState, ErrorState, Segmented, statusTone, useToast } from "../../ui"
import { ConnectFrame } from "./ConnectFrame"

interface OutboxRow {
  name: string
  connection: string | null
  event: string
  status: "Pending" | "Sent" | "Failed" | "Dead"
  attempts: number | null
  next_attempt_at: string | null
  sent_at: string | null
  last_error: string | null
  reference_doctype: string | null
  reference_name: string | null
  creation: string
}

type StatusFilter = "" | "Pending" | "Failed" | "Dead" | "Sent"

export default function OutboxMonitor() {
  const { t } = useTexT()
  const toast = useToast()
  const { property } = useSession()
  const [status, setStatus] = useState<StatusFilter>("")
  const q = useTexQuery<OutboxRow[]>("admin", "outbox", { property: property?.name, status: status || undefined, limit: 200 }, [property?.name, status])
  const conns = useTexQuery<{ name: string; label: string }[]>(
    "policies",
    "list_records",
    { doctype: "TEX Integration Connection", property: property?.name },
    [property?.name],
  )
  const [retrying, setRetrying] = useState<string | null>(null)
  const label = (c: string | null) => (c ? (conns.data?.find((x) => x.name === c)?.label ?? c) : "—")

  const retry = async (r: OutboxRow) => {
    setRetrying(r.name)
    try {
      await tex("admin", "retry_outbox", { name: r.name }, { post: true })
      toast.success(t("connect.outbox.retried"))
      q.reload()
    } catch (e) {
      toast.error((e as TexApiError).message)
    } finally {
      setRetrying(null)
    }
  }

  const retryButton = (r: OutboxRow) => (
    <Button
      variant="secondary"
      size="sm"
      icon={<RotateCcw className="size-3.5" aria-hidden />}
      loading={retrying === r.name}
      aria-label={`${t("connect.outbox.retry")}: ${r.event} · ${dateTime(r.creation)}`}
      onClick={() => retry(r)}
    >
      {t("connect.outbox.retry")}
    </Button>
  )

  return (
    <ConnectFrame>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="max-w-full overflow-x-auto">
          <Segmented<StatusFilter>
            label={t("connect.outbox.filter")}
            value={status}
            onChange={setStatus}
            options={[
              { value: "", label: t("connect.outbox.all") },
              { value: "Pending", label: t("connect.outbox_status.pending") },
              { value: "Failed", label: t("connect.outbox_status.failed") },
              { value: "Dead", label: t("connect.outbox_status.dead") },
              { value: "Sent", label: t("connect.outbox_status.sent") },
            ]}
          />
        </div>
        <Button variant="secondary" icon={<RefreshCw className="size-4" aria-hidden />} onClick={q.reload} loading={q.loading && !!q.data}>
          {t("core.action.refresh")}
        </Button>
      </div>
      <Card>
        <CardHeader title={t("connect.outbox.title")} description={t("connect.outbox.hint")} />
        {q.error ? (
          <ErrorState error={q.error} onRetry={q.reload} />
        ) : (
          <DataTable<OutboxRow>
            caption={t("connect.outbox.title")}
            rows={q.data}
            loading={q.loading}
            rowKey={(r) => r.name}
            dense
            empty={<EmptyState title={status ? t("connect.outbox.empty_filtered") : t("connect.outbox.empty")} description={t("connect.outbox.empty_hint")} />}
            columns={[
              {
                key: "creation",
                header: t("connect.outbox.col.created"),
                hideBelow: "sm",
                sortValue: (r) => r.creation,
                cell: (r) => <span className="whitespace-nowrap">{dateTime(r.creation)}</span>,
              },
              {
                key: "event",
                header: t("connect.outbox.col.event"),
                sortValue: (r) => r.event,
                cell: (r) => (
                  <span>
                    <span className="font-mono text-xs text-zinc-900">{r.event}</span>
                    <span className="block text-xs text-zinc-500">{label(r.connection)}</span>
                    <span className="block text-xs text-zinc-500 sm:hidden">{dateTime(r.creation)}</span>
                    {r.last_error && <span className="line-clamp-2 text-xs break-words text-rose-800 md:hidden">{r.last_error}</span>}
                  </span>
                ),
              },
              {
                key: "reference",
                header: t("connect.outbox.col.reference"),
                hideBelow: "lg",
                cell: (r) => (r.reference_name ? <span className="font-mono text-xs whitespace-nowrap">{r.reference_name}</span> : "—"),
              },
              {
                key: "status",
                header: t("connect.outbox.col.status"),
                sortValue: (r) => r.status,
                cell: (r) => (
                  <span className="flex flex-col items-start gap-1.5">
                    <Badge tone={statusTone(r.status)}>{t(`connect.outbox_status.${r.status.toLowerCase()}`)}</Badge>
                    {(r.status === "Failed" || r.status === "Dead") && (
                      <span className="sm:hidden">
                        {retryButton(r)}
                      </span>
                    )}
                  </span>
                ),
              },
              { key: "attempts", header: t("connect.outbox.col.attempts"), align: "right", hideBelow: "sm", sortValue: (r) => r.attempts ?? 0, cell: (r) => r.attempts ?? 0 },
              {
                key: "next",
                header: t("connect.outbox.col.next"),
                hideBelow: "md",
                sortValue: (r) => r.next_attempt_at ?? r.sent_at ?? "",
                cell: (r) =>
                  r.status === "Sent" ? (
                    <span className="text-xs text-zinc-500">{t("connect.outbox.sent_at", { when: dateTime(r.sent_at) })}</span>
                  ) : r.status === "Dead" ? (
                    <span className="text-xs text-zinc-500">{t("connect.outbox.no_more")}</span>
                  ) : (
                    <span className="whitespace-nowrap">{dateTime(r.next_attempt_at)}</span>
                  ),
              },
              {
                key: "error",
                header: t("connect.outbox.col.error"),
                hideBelow: "md",
                className: "max-w-xs",
                cell: (r) =>
                  r.last_error ? (
                    <details>
                      <summary className="line-clamp-1 cursor-pointer text-xs text-rose-800">{r.last_error}</summary>
                      <p className="mt-1 text-xs break-words whitespace-pre-wrap text-zinc-700">{r.last_error}</p>
                    </details>
                  ) : (
                    "—"
                  ),
              },
              {
                key: "actions",
                header: <span className="sr-only">{t("connect.outbox.col.actions")}</span>,
                align: "right",
                hideBelow: "sm",
                cell: (r) => (r.status === "Failed" || r.status === "Dead" ? retryButton(r) : null),
              },
            ]}
          />
        )}
      </Card>
    </ConnectFrame>
  )
}
