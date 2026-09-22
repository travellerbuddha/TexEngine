import { useState } from "react"
import { Download, Info } from "lucide-react"
import { tex, useTexQuery } from "../../../lib/api"
import { isoDay, num } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, Card, CardBody, CardHeader, InlineError, Notice, Skeleton, useToast } from "../../../ui"
import { ConsentIcon } from "../components/common"
import { downloadCsv, EXPORT_CHANNELS } from "../lib"
import type { ExportRow, GuestPage } from "../types"

function ChannelRow({
  segment,
  segmentLabel,
  property,
  members,
  channel,
  field,
  channelKey,
}: {
  segment: string
  segmentLabel: string
  property?: string
  members: number | null
  channel: string
  field: (typeof EXPORT_CHANNELS)[number]["field"]
  channelKey: string
}) {
  const { t } = useTexT()
  const toast = useToast()
  // consented members (the server applies the same filter in the export)
  const q = useTexQuery<GuestPage>("crm", "guests", { segment, consent: field, property, limit: 1 }, [segment, field, property])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [exported, setExported] = useState<number | null>(null)
  const consented = q.data?.total ?? null
  const label = t(`crm.channel.${channelKey}`)

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      const rows = await tex<ExportRow[]>("crm", "export_segment", { segment, channel, property }, { post: true })
      const contact = channel === "Email" ? "email" : "phone"
      downloadCsv(
        `${segmentLabel.replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-|-$/g, "") || "segment"}-${channel.toLowerCase()}-${isoDay(new Date())}.csv`,
        ["guest", "first_name", "last_name", contact, "language", "country"],
        rows.map((r) => [r.guest, r.first_name, r.last_name, channel === "Email" ? r.email : r.phone, r.language, r.country]),
      )
      setExported(rows.length)
      toast.success(t("crm.export.done", { count: rows.length, channel: label }))
    } catch (e) {
      setError(e as Error)
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="space-y-2 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="rounded-md bg-zinc-100 p-1.5 text-zinc-600">
            <ConsentIcon field={field} />
          </span>
          <div className="min-w-0">
            <p className="text-sm font-medium text-zinc-900">{label}</p>
            <p className="text-xs text-zinc-500">
              {q.loading && consented === null ? (
                <Skeleton className="mt-1 h-3 w-40" />
              ) : q.error ? (
                t("crm.export.count_failed")
              ) : members !== null && (consented ?? 0) <= members ? (
                t("crm.export.consented_of", { consented: num(consented ?? 0), members: num(members) })
              ) : members !== null ? (
                // the stored member count predates newer guests: do not show "5 of 3"
                `${t("crm.export.consented", { consented: num(consented ?? 0) })} · ${t("crm.export.stale")}`
              ) : (
                t("crm.export.consented", { consented: num(consented ?? 0) })
              )}
            </p>
          </div>
        </div>
        <Button
          variant="secondary"
          size="sm"
          icon={<Download className="size-4" aria-hidden />}
          loading={busy}
          disabled={consented === 0}
          onClick={run}
        >
          {t("crm.export.button", { channel: label })}
        </Button>
      </div>
      {exported !== null && (
        <p className="text-xs text-zinc-600">
          <Badge tone="success">{t("crm.export.rows", { count: exported })}</Badge>{" "}
          {consented !== null && exported < consented ? t("crm.export.blacklist_excluded", { count: consented - exported }) : null}
        </p>
      )}
      <InlineError error={error} />
    </li>
  )
}

export function SegmentExport({
  segment,
  segmentLabel,
  property,
  members,
}: {
  segment: string
  segmentLabel: string
  property?: string
  members: number | null
}) {
  const { t } = useTexT()
  return (
    <Card>
      <CardHeader title={t("crm.export.title")} description={t("crm.export.subtitle")} />
      <CardBody className="space-y-3 pb-0">
        <Notice tone="info">
          <span className="flex gap-2">
            <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>{t("crm.export.why_counts_differ")}</span>
          </span>
        </Notice>
      </CardBody>
      <ul className="divide-y divide-zinc-100">
        {EXPORT_CHANNELS.map((c) => (
          <ChannelRow
            key={c.channel}
            segment={segment}
            segmentLabel={segmentLabel}
            property={property}
            members={members}
            channel={c.channel}
            field={c.field}
            channelKey={c.key}
          />
        ))}
      </ul>
      <p className="border-t border-zinc-100 px-4 py-2.5 text-xs text-zinc-500">{t("crm.export.audited")}</p>
    </Card>
  )
}
