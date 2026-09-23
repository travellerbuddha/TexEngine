import { Link } from "react-router-dom"
import { ArrowRight } from "lucide-react"
import { dateTime } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Card, CardBody } from "../../../ui"
import { CodeBlock } from "../../settings/components/common"
import { adapterLabel, CertificationNotice, ConnectionCounts, EnabledBadge, EnvBadge, Fact, syncTone } from "./common"
import type { ChannelConnection } from "./types"

export function channelPath(name: string) {
  return `/tex/connect/channels/${encodeURIComponent(name)}`
}

/** Last sync outcome as a badge ("Sent", "Failed", or a connection test's OK / Error). */
export function SyncStatus({ status }: { status: string | null }) {
  const { t } = useTexT()
  if (!status) return <span className="text-zinc-500">{t("connect.channels.never_synced")}</span>
  const key = { Sent: "connect.channels.sync.sent", Failed: "connect.channels.sync.failed", OK: "connect.status.ok", Error: "connect.status.error" }[status]
  return <Badge tone={syncTone(status)}>{key ? t(key) : status}</Badge>
}

/** One channel connection of the hotel: health, queues and the webhook address. */
export function ChannelCard({ conn }: { conn: ChannelConnection }) {
  const { t } = useTexT()
  const to = channelPath(conn.name)
  return (
    <Card className="flex flex-col">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-zinc-100 px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold break-words text-zinc-900">
            <Link to={to} className="hover:text-tex-700 hover:underline">
              {conn.label}
            </Link>
          </h2>
          <p className="mt-0.5 text-xs break-words text-zinc-500">{adapterLabel(t, conn.adapter)}</p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <EnvBadge env={conn.environment} />
          <EnabledBadge enabled={conn.enabled} />
        </div>
      </div>
      <CardBody className="flex-1 space-y-4">
        {!conn.certified && <CertificationNotice />}
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Fact label={t("connect.channels.last_sync")}>{conn.last_sync_at ? dateTime(conn.last_sync_at) : "—"}</Fact>
          <Fact label={t("connect.channels.last_status")}>
            <SyncStatus status={conn.last_status} />
          </Fact>
          <Fact label={t("connect.channels.mappings")}>{t("connect.channels.mapping_count", { count: conn.mappings })}</Fact>
        </dl>
        {conn.last_error && (
          <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs break-words text-rose-800">
            <span className="font-semibold">{t("connect.status.last_error")}: </span>
            {conn.last_error}
          </p>
        )}
        <ConnectionCounts conn={conn} />
        <div className="space-y-1">
          <CodeBlock value={conn.webhook_url} label={t("connect.channels.webhook")} />
          <p className="text-xs text-zinc-500">{t("connect.channels.webhook_hint")}</p>
        </div>
      </CardBody>
      <div className="flex justify-end border-t border-zinc-100 px-4 py-3">
        <Link to={to} className="inline-flex items-center gap-1 text-sm font-medium text-tex-700 hover:underline" aria-label={t("connect.channels.open_named", { label: conn.label })}>
          {t("connect.channels.open")} <ArrowRight className="size-4" aria-hidden />
        </Link>
      </div>
    </Card>
  )
}
