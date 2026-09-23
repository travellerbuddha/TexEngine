import { useMemo, useState, type ReactNode } from "react"
import { CheckCircle2, Scale } from "lucide-react"
import { useTexMutation } from "../../../lib/api"
import { date, dateTime } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, CardBody, EmptyState, InlineError, Money, Notice, statusTone } from "../../../ui"
import { BookingRef, EventBadge, InboundStatusBadge, mappingCodes } from "./common"
import type { Mapping, Mismatch, MismatchKind, ReconcileResult, TabProps } from "./types"

/** Booking differences first (they need a person), ARI drift last (a push fixes it). */
const KINDS: MismatchKind[] = ["missing_in_tex", "status_differs", "total_differs", "missing_in_channel", "ari_drift"]
const SHOWN = 10

function TexStatus({ status }: { status: string | null | undefined }) {
  const { t } = useTexT()
  if (!status) return <span className="text-zinc-500">—</span>
  const key = `connect.channels.tex_status.${status.toLowerCase().replace(/\s+/g, "_")}`
  const label = t(key)
  return <Badge tone={statusTone(status)}>{label === key ? status : label}</Badge>
}

function Line({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <span className="text-zinc-500">{label}</span>
      {children}
    </span>
  )
}

/** One difference, in words and with links to the records involved. */
function MismatchItem({ m, mappings }: { m: Mismatch; mappings: Mapping[] }) {
  const { t } = useTexT()
  const ref = <span className="font-mono text-xs font-medium break-all text-zinc-900">{m.key}</span>
  switch (m.kind) {
    case "ari_drift": {
      const mp = mappings.find((x) => x.name === m.mapping)
      return (
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-mono text-xs font-medium text-zinc-900">{mp ? mappingCodes(mp) : m.key}</span>
          <span className="whitespace-nowrap">{date(m.date)}</span>
          {m.pushed ? <Badge tone="warning">{t("connect.channels.ari.changed")}</Badge> : <Badge tone="neutral">{t("connect.channels.ari.never_sent")}</Badge>}
        </span>
      )
    }
    case "missing_in_tex":
      return (
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {ref}
          <Line label={t("connect.channels.reconcile.last_message")}>{m.inbound_status ? <InboundStatusBadge status={m.inbound_status} /> : "—"}</Line>
        </span>
      )
    case "status_differs":
      return (
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {ref}
          <Line label={t("connect.channels.reconcile.channel")}>{m.channel ? <EventBadge event={m.channel} /> : "—"}</Line>
          <Line label={t("connect.channels.reconcile.tex")}>
            <TexStatus status={m.tex} />
          </Line>
          <BookingRef name={m.booking} />
        </span>
      )
    case "total_differs":
      return (
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {ref}
          <Line label={t("connect.channels.reconcile.channel")}>
            <Money amount={m.channel} className="font-medium" />
          </Line>
          <Line label={t("connect.channels.reconcile.tex")}>
            <Money amount={m.tex} className="font-medium" />
          </Line>
          <BookingRef name={m.booking} />
        </span>
      )
    case "missing_in_channel":
      return (
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {ref}
          <BookingRef name={m.booking} />
          <TexStatus status={m.status} />
        </span>
      )
    default:
      return ref
  }
}

function Group({ kind, items, mappings }: { kind: MismatchKind; items: Mismatch[]; mappings: Mapping[] }) {
  const { t } = useTexT()
  const [all, setAll] = useState(false)
  const shown = all ? items : items.slice(0, SHOWN)
  const headingId = `reconcile-${kind}`
  return (
    <section aria-labelledby={headingId} className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={headingId} className="text-sm font-semibold text-zinc-900">
          {t(`connect.channels.reconcile.kind.${kind}`)}
        </h3>
        <Badge tone={kind === "ari_drift" ? "warning" : "danger"}>{items.length}</Badge>
      </div>
      <p className="text-xs text-zinc-500">{t(`connect.channels.reconcile.kind.${kind}_hint`)}</p>
      <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200 text-sm">
        {shown.map((m, i) => (
          <li key={`${m.key}-${i}`} className="px-3 py-2">
            <MismatchItem m={m} mappings={mappings} />
          </li>
        ))}
      </ul>
      {items.length > SHOWN && (
        <Button variant="link" size="sm" onClick={() => setAll(!all)} aria-expanded={all}>
          {all ? t("connect.channels.reconcile.show_less") : t("connect.channels.reconcile.show_all", { count: items.length })}
        </Button>
      )}
    </section>
  )
}

/** Compare TEX with the channel: ARI drift and booking differences (read-only, audited). */
export function ReconcileTab({ connection, mappings }: TabProps) {
  const { t } = useTexT()
  const run = useTexMutation<{ connection: string }, ReconcileResult>("distribution", "reconcile")
  const [result, setResult] = useState<ReconcileResult | null>(null)
  const [ranAt, setRanAt] = useState<Date | null>(null)
  const groups = useMemo(() => {
    const by = new Map<MismatchKind, Mismatch[]>()
    for (const m of result?.mismatches ?? []) by.set(m.kind, [...(by.get(m.kind) ?? []), m])
    return KINDS.filter((k) => by.has(k)).map((k) => ({ kind: k, items: by.get(k)! }))
  }, [result])

  const start = async () => {
    try {
      setResult(await run.run({ connection }))
      setRanAt(new Date())
    } catch {
      /* shown inline */
    }
  }

  const runButton = (
    <Button icon={<Scale className="size-4" aria-hidden />} loading={run.pending} onClick={start} variant={result ? "secondary" : "primary"}>
      {result ? t("connect.channels.reconcile.run_again") : t("connect.channels.reconcile.run")}
    </Button>
  )

  if (!result)
    return (
      <CardBody className="space-y-3">
        <InlineError error={run.error} />
        <EmptyState icon={<Scale className="size-5" />} title={t("connect.channels.reconcile.intro_title")} description={t("connect.channels.reconcile.intro")} action={runButton} />
      </CardBody>
    )

  return (
    <CardBody className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-zinc-700" aria-live="polite">
          {result.total ? t("connect.channels.reconcile.found", { count: result.total }) : t("connect.channels.reconcile.none")}
          {ranAt && <span className="block text-xs text-zinc-500">{t("connect.channels.reconcile.checked_at", { when: dateTime(ranAt) })}</span>}
        </p>
        {runButton}
      </div>
      <InlineError error={run.error} />
      {result.total === 0 ? (
        <EmptyState icon={<CheckCircle2 className="size-5 text-emerald-600" />} title={t("connect.channels.reconcile.in_sync")} description={t("connect.channels.reconcile.in_sync_hint")} />
      ) : (
        <>
          {result.total > result.mismatches.length && <Notice tone="info">{t("connect.channels.reconcile.truncated", { shown: result.mismatches.length, total: result.total })}</Notice>}
          {groups.map((g) => (
            <Group key={g.kind} kind={g.kind} items={g.items} mappings={mappings.data ?? []} />
          ))}
        </>
      )}
    </CardBody>
  )
}
