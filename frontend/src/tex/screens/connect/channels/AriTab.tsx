import { useEffect, useMemo, useState } from "react"
import { Link2, ListRestart, Send, CloudUpload } from "lucide-react"
import { tex, TexApiError, useTexQuery } from "../../../lib/api"
import { isoDay } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, CardBody, ConfirmDialog, EmptyState, ErrorState, Field, Input, Segmented, Select, useToast } from "../../../ui"
import { AriTable } from "./AriTable"
import { mappingCodes, useLookupNames } from "./common"
import type { AriDay, AriPreview, PushResult, SendResult, TabProps } from "./types"

type Span = "7" | "14" | "31"
const ISO = /^\d{4}-\d{2}-\d{2}$/
const NO_DAYS: AriDay[] = []

/** ARI preview of one mapping, and the manual push controls. */
export function AriTab({ connection, conn, mappings, lookups, canManage, onChanged, goTo }: TabProps) {
  const { t } = useTexT()
  const toast = useToast()
  const names = useLookupNames(lookups.data)
  const rows = useMemo(() => mappings.data ?? [], [mappings.data])
  const [mapping, setMapping] = useState("")
  const [from, setFrom] = useState(() => isoDay(new Date()))
  const [span, setSpan] = useState<Span>("14")
  const [busy, setBusy] = useState<"queue" | "full" | "send" | null>(null)
  const [confirmFull, setConfirmFull] = useState(false)

  // default to the first enabled mapping; keep the choice while it still exists
  useEffect(() => {
    if (rows.length && !rows.some((m) => m.name === mapping)) setMapping((rows.find((m) => m.enabled) ?? rows[0]).name)
  }, [rows, mapping])

  const validFrom = ISO.test(from)
  const q = useTexQuery<AriPreview>("distribution", "ari_preview", { mapping, date_from: from, days: Number(span) }, [mapping, from, span], !!mapping && validFrom)
  // a cleared or invalid date shows no days (not the last answer under the new date)
  const days = !mapping ? undefined : !validFrom ? NO_DAYS : q.data?.mapping === mapping ? q.data.days : undefined
  // a switched-off connection sends nothing: the server would queue 0 and mark jobs done unsent
  const off = !conn.enabled
  const counts = useMemo(() => {
    const c = { in_sync: 0, changed: 0, never: 0 }
    for (const d of days ?? []) {
      if (d.in_sync) c.in_sync++
      else if (d.sent) c.changed++
      else c.never++
    }
    return c
  }, [days])

  const push = async (full: boolean) => {
    setBusy(full ? "full" : "queue")
    try {
      const r = await tex<PushResult>("distribution", "push_now", { connection, full: full ? 1 : 0 }, { post: true })
      toast.success(full ? t("connect.channels.ari.resend_queued", { count: r.queued }) : t("connect.channels.ari.queued", { count: r.queued }))
      q.reload()
      onChanged()
    } finally {
      setBusy(null)
    }
  }
  const queue = () => push(false).catch((e: unknown) => toast.error((e as TexApiError).message))
  const sendNow = async () => {
    setBusy("send")
    try {
      const r = await tex<SendResult>("distribution", "send_now", { connection }, { post: true })
      const msg = t("connect.channels.ari.sent", { pushed: r.pushed, failed: r.failed, waiting: r.waiting })
      if (r.failed) toast.error(msg)
      else toast.success(msg)
      q.reload()
      onChanged()
    } catch (e) {
      toast.error((e as TexApiError).message)
    } finally {
      setBusy(null)
    }
  }

  if (mappings.error) return <ErrorState error={mappings.error} onRetry={mappings.reload} />
  if (mappings.data && rows.length === 0)
    return (
      <EmptyState
        icon={<Link2 className="size-5" />}
        title={t("connect.channels.ari.no_mappings")}
        description={t("connect.channels.ari.no_mappings_hint")}
        action={
          <Button variant="secondary" onClick={() => goTo("mappings")}>
            {t("connect.channels.tab.mappings")}
          </Button>
        }
      />
    )

  const current = rows.find((m) => m.name === mapping)
  return (
    <>
      <CardBody className="space-y-4 border-b border-zinc-100">
        <p className="text-sm text-zinc-600">{t("connect.channels.ari.hint")}</p>
        <div className="flex flex-wrap items-end gap-3">
          <Field label={t("connect.channels.ari.mapping")} className="w-full min-w-0 sm:w-auto sm:min-w-64">
            <Select
              value={mapping}
              onChange={(e) => setMapping(e.target.value)}
              options={rows.map((m) => ({
                value: m.name,
                label: [mappingCodes(m), names.roomType(m.room_type), m.board, m.enabled ? "" : t("connect.disabled")].filter(Boolean).join(" · "),
              }))}
            />
          </Field>
          <Field label={t("connect.channels.ari.from")} className="w-full sm:w-auto" error={validFrom ? undefined : t("connect.channels.ari.err_date")}>
            <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </Field>
          <div className="space-y-1.5">
            <span className="block text-sm font-medium text-zinc-800" aria-hidden>
              {t("connect.channels.ari.days")}
            </span>
            <Segmented<Span>
              label={t("connect.channels.ari.days")}
              value={span}
              onChange={setSpan}
              options={[
                { value: "7", label: t("connect.channels.ari.days_n", { count: 7 }) },
                { value: "14", label: t("connect.channels.ari.days_n", { count: 14 }) },
                { value: "31", label: t("connect.channels.ari.days_n", { count: 31 }) },
              ]}
            />
          </div>
        </div>
        {canManage && (
          <div className="flex flex-wrap items-center gap-2">
            <Button icon={<ListRestart className="size-4" aria-hidden />} loading={busy === "queue"} disabled={!!busy || off} onClick={queue}>
              {t("connect.channels.ari.queue")}
            </Button>
            <Button variant="secondary" icon={<Send className="size-4" aria-hidden />} loading={busy === "send"} disabled={!!busy || off} onClick={sendNow}>
              {t("connect.channels.ari.send_now")}
            </Button>
            <Button variant="ghost" icon={<CloudUpload className="size-4" aria-hidden />} loading={busy === "full"} disabled={!!busy || off} onClick={() => setConfirmFull(true)}>
              {t("connect.channels.ari.resend")}
            </Button>
            <p className="w-full text-xs text-zinc-500">{off ? t("connect.channels.ari.actions_off") : t("connect.channels.ari.actions_hint")}</p>
          </div>
        )}
        {days && validFrom && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs" aria-live="polite">
            {current && <span className="mr-1 text-zinc-500">{t("connect.channels.ari.summary", { codes: mappingCodes(current), currency: current.sell_currency })}</span>}
            <Badge tone="success">{t("connect.channels.ari.count_in_sync", { count: counts.in_sync })}</Badge>
            <Badge tone={counts.changed ? "warning" : "neutral"}>{t("connect.channels.ari.count_changed", { count: counts.changed })}</Badge>
            <Badge tone="neutral">{t("connect.channels.ari.count_never", { count: counts.never })}</Badge>
          </div>
        )}
      </CardBody>
      {q.error && validFrom ? (
        <ErrorState error={q.error} onRetry={q.reload} />
      ) : (
        <AriTable days={days} loading={(q.loading && validFrom) || !mapping} caption={t("connect.channels.ari.caption", { codes: current ? mappingCodes(current) : "" })} />
      )}
      <ConfirmDialog
        open={confirmFull}
        onClose={() => setConfirmFull(false)}
        title={t("connect.channels.ari.resend_title")}
        body={t("connect.channels.ari.resend_body")}
        confirmLabel={t("connect.channels.ari.resend")}
        onConfirm={() => push(true)}
      />
    </>
  )
}
