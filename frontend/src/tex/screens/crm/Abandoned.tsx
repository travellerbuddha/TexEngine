import { useEffect, useMemo, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Mail, Phone, ShieldCheck, ShieldOff } from "lucide-react"
import { useTexMutation, useTexQuery } from "../../lib/api"
import { useProperty, useSession } from "../../lib/session"
import { date, dateTime, nightsBetween, num } from "../../lib/format"
import { useTexT } from "../../i18n"
import {
  Badge,
  Button,
  Card,
  DataTable,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  InlineError,
  Money,
  Notice,
  PageHeader,
  Select,
  statusTone,
  Textarea,
  Toolbar,
  useToast,
} from "../../ui"
import { cn } from "../../../lib/utils"
import { CrmNav } from "./components/common"
import { useEvent } from "./lib"
import { FUNNEL_STAGES, type AbandonedRow, type AbandonedStatus } from "./types"

const STATUSES: AbandonedStatus[] = ["Open", "Contacted", "Recovered", "Dismissed"]
const NEXT: Record<AbandonedStatus, AbandonedStatus[]> = {
  Open: ["Contacted", "Recovered", "Dismissed"],
  Contacted: ["Recovered", "Dismissed", "Open"],
  Recovered: ["Open"],
  Dismissed: ["Open"],
}
const statusKey = (s: string) => `crm.ab.status.${s.toLowerCase()}`
const stageKey = (s: string) => `crm.ab.stage.${s}`
const actionKey = (to: AbandonedStatus) => (to === "Open" ? "crm.ab.action.reopen" : `crm.ab.action.${to.toLowerCase()}`)

function StageMeter({ stage }: { stage: string }) {
  const { t } = useTexT()
  const idx = FUNNEL_STAGES.indexOf(stage as (typeof FUNNEL_STAGES)[number])
  return (
    <div className="min-w-0">
      <p className="text-sm font-medium text-zinc-900">{t(stageKey(stage))}</p>
      <ol className="mt-1 flex items-center gap-1" aria-label={t("crm.ab.stage_progress", { n: idx + 1, total: FUNNEL_STAGES.length })}>
        {FUNNEL_STAGES.map((s, i) => (
          <li key={s} title={t(stageKey(s))} className={cn("h-1.5 w-5 rounded-full", i <= idx ? "bg-tex-500" : "bg-zinc-200")}>
            <span className="sr-only">
              {t(stageKey(s))}: {i <= idx ? t("crm.ab.reached") : t("crm.ab.not_reached")}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

export default function Abandoned() {
  const { t } = useTexT()
  const property = useProperty()
  const { can } = useSession()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const status = params.get("status") ?? ""
  const days = params.get("days") ?? "30"
  // one fetch for the period; the status filter is applied here so the counters stay complete
  const q = useTexQuery<AbandonedRow[]>("crm", "abandoned", { property, days }, [property, days], Boolean(property))
  const rows = useMemo(() => (q.data && status ? q.data.filter((r) => r.status === status) : q.data), [q.data, status])
  const [target, setTarget] = useState<{ row: AbandonedRow; to: AbandonedStatus } | null>(null)
  const closeTarget = useEvent(() => setTarget(null))
  const canEdit = can("crm.edit")

  const counts = useMemo(() => {
    const c: Record<string, number> = { Open: 0, Contacted: 0, Recovered: 0, Dismissed: 0 }
    for (const r of q.data ?? []) c[r.status] = (c[r.status] ?? 0) + 1
    return c
  }, [q.data])

  // status workflow buttons (in their own column on wide screens, inside the first cell on phones)
  const actions = (r: AbandonedRow, className: string) => (
    <div className={cn("flex flex-wrap gap-1", className)}>
      {NEXT[r.status].map((to) => (
        <Button
          key={to}
          variant={to === "Dismissed" || to === "Open" ? "ghost" : "secondary"}
          size="sm"
          aria-label={`${t(actionKey(to))} · ${t(stageKey(r.stage_reached))} · ${dateTime(r.last_event_at)}`}
          onClick={() => setTarget({ row: r, to })}
        >
          {t(actionKey(to))}
        </Button>
      ))}
    </div>
  )

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params)
    if (v) next.set(k, v)
    else next.delete(k)
    setParams(next, { replace: true })
  }

  return (
    <>
      <PageHeader
        title={t("crm.ab.title")}
        subtitle={t("crm.ab.subtitle")}
        crumbs={[{ label: t("core.nav.crm"), to: "/tex/crm" }, { label: t("crm.nav.abandoned") }]}
      />
      <CrmNav />
      {!can("crm.view") ? (
        <Card>
          <EmptyState title={t("core.error.permission")} description={t("crm.no_access")} />
        </Card>
      ) : (
        <div className="space-y-4">
          <section aria-label={t("crm.ab.summary")} className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {STATUSES.map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={status === s}
                onClick={() => set("status", status === s ? "" : s)}
                className={cn(
                  "rounded-(--radius-tex) border bg-white p-4 text-left shadow-tex-card transition-colors hover:border-tex-300",
                  status === s ? "border-tex-500 ring-1 ring-tex-500" : "border-zinc-200",
                )}
              >
                <span className="block text-xs font-medium tracking-wide text-zinc-500 uppercase">{t(statusKey(s))}</span>
                <span className="mt-1 block text-2xl font-semibold tracking-tight text-zinc-950 tabular-nums">{q.data ? num(counts[s]) : "—"}</span>
                <span className="mt-1 block text-xs text-zinc-500">{status === s ? t("crm.ab.stat_active") : t("crm.ab.stat_hint")}</span>
              </button>
            ))}
          </section>
          <Notice tone="info" title={t("crm.ab.privacy_title")}>
            {t("crm.ab.privacy_body")}
          </Notice>
          <Toolbar className="mb-0">
            <Field label={t("core.label.status")} className="w-[calc(50%-0.375rem)] sm:w-44">
              <Select
                value={status}
                onChange={(e) => set("status", e.target.value)}
                options={[{ value: "", label: t("core.label.all") }, ...STATUSES.map((s) => ({ value: s, label: t(statusKey(s)) }))]}
              />
            </Field>
            <Field label={t("crm.ab.period")} className="w-[calc(50%-0.375rem)] sm:w-44">
              <Select
                value={days}
                onChange={(e) => set("days", e.target.value === "30" ? "" : e.target.value)}
                options={["7", "30", "90", "365"].map((d) => ({ value: d, label: t("crm.ab.last_days", { count: Number(d) }) }))}
              />
            </Field>
          </Toolbar>
          <Card>
            {q.error ? (
              <ErrorState error={q.error} onRetry={q.reload} />
            ) : (
              <DataTable<AbandonedRow>
                caption={t("crm.ab.caption")}
                rows={rows}
                loading={q.loading}
                rowKey={(r) => r.name}
                empty={<EmptyState title={t("crm.ab.empty")} description={t("crm.ab.empty_hint")} />}
                columns={[
                  {
                    key: "stage",
                    header: t("crm.ab.col.stage"),
                    cell: (r) => (
                      <div className="space-y-1">
                        <StageMeter stage={r.stage_reached} />
                        <p className="text-xs text-zinc-500 sm:hidden">
                          {r.check_in ? `${date(r.check_in, "short")} → ${date(r.check_out, "short")}` : "—"}
                        </p>
                        <div className="flex flex-wrap gap-1 md:hidden">
                          <span className="sm:hidden">
                            <Badge tone={statusTone(r.status)}>{t(statusKey(r.status))}</Badge>
                          </span>
                          {r.consent_marketing ? (
                            <Badge tone="success">
                              <ShieldCheck className="size-3" aria-hidden />
                              {r.email || r.phone || t("crm.ab.consent_yes")}
                            </Badge>
                          ) : (
                            <Badge tone="neutral">
                              <ShieldOff className="size-3" aria-hidden />
                              {t("crm.ab.anonymous")}
                            </Badge>
                          )}
                        </div>
                        {canEdit && actions(r, "pt-1 sm:hidden")}
                      </div>
                    ),
                  },
                  {
                    key: "stay",
                    header: t("crm.ab.col.stay"),
                    hideBelow: "sm",
                    sortValue: (r) => r.check_in ?? "",
                    cell: (r) =>
                      r.check_in ? (
                        <div className="text-xs whitespace-nowrap">
                          <p>
                            {date(r.check_in, "short")} → {date(r.check_out, "short")}
                          </p>
                          {r.check_out && <p className="text-zinc-500">{t("core.label.nights", { count: nightsBetween(r.check_in, r.check_out) })}</p>}
                        </div>
                      ) : (
                        "—"
                      ),
                  },
                  { key: "value", header: t("crm.ab.col.value"), align: "right", cell: (r) => <Money amount={r.value} currency={r.currency} /> },
                  {
                    key: "contact",
                    header: t("crm.ab.col.contact"),
                    hideBelow: "md",
                    cell: (r) =>
                      r.consent_marketing ? (
                        <div className="min-w-0 space-y-1 text-xs">
                          <Badge tone="success">
                            <ShieldCheck className="size-3" aria-hidden />
                            {t("crm.ab.consent_yes")}
                          </Badge>
                          {r.email && (
                            <p className="flex items-center gap-1 truncate">
                              <Mail className="size-3 text-zinc-400" aria-hidden />
                              <a className="text-tex-700 hover:underline" href={`mailto:${r.email}`}>
                                {r.email}
                              </a>
                            </p>
                          )}
                          {r.phone && r.phone_channels.length > 0 && (
                            // a phone for the channels the guest agreed to, never a call: TEX records no consent to be called (O-26)
                            <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                              <Phone className="size-3 text-zinc-400" aria-hidden />
                              <span>{r.phone}</span>
                              {r.phone_channels.includes("SMS") && (
                                <a className="text-tex-700 hover:underline" href={`sms:${r.phone}`}>
                                  {t("crm.channel.sms")}
                                </a>
                              )}
                              {r.phone_channels.includes("WhatsApp") && /^\+\d[\d ().-]*$/.test(r.phone) && (
                                <a
                                  className="text-tex-700 hover:underline"
                                  href={`https://wa.me/${r.phone.replace(/\D/g, "")}`}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  {t("crm.channel.whatsapp")}
                                </a>
                              )}
                            </p>
                          )}
                          {r.guest && (
                            <Link className="font-medium text-tex-700 hover:underline" to={`/tex/crm/guests/${encodeURIComponent(r.guest)}`}>
                              {t("crm.ab.open_profile")}
                            </Link>
                          )}
                        </div>
                      ) : (
                        <Badge tone="neutral" title={t("crm.ab.anonymous_hint")}>
                          <ShieldOff className="size-3" aria-hidden />
                          {t("crm.ab.anonymous")}
                        </Badge>
                      ),
                  },
                  {
                    key: "status",
                    header: t("crm.ab.col.status_last"),
                    hideBelow: "sm",
                    sortValue: (r) => r.last_event_at ?? "",
                    cell: (r) => (
                      <div className="space-y-1">
                        <Badge tone={statusTone(r.status)}>{t(statusKey(r.status))}</Badge>
                        <p className="text-xs whitespace-nowrap text-zinc-500">{dateTime(r.last_event_at)}</p>
                        {r.recovered_booking && <p className="text-xs text-zinc-500">{r.recovered_booking}</p>}
                      </div>
                    ),
                  },
                  ...(canEdit
                    ? [
                        {
                          key: "actions",
                          header: <span className="sr-only">{t("crm.ab.col.actions")}</span>,
                          align: "right" as const,
                          hideBelow: "sm" as const,
                          cell: (r: AbandonedRow) => actions(r, "ml-auto max-w-60 justify-end"),
                        },
                      ]
                    : []),
                ]}
              />
            )}
          </Card>
        </div>
      )}
      <StatusDialog
        target={target}
        onClose={closeTarget}
        onDone={(to) => {
          toast.success(t("crm.ab.updated", { status: t(statusKey(to)) }))
          q.reload()
        }}
      />
    </>
  )
}

function StatusDialog({
  target,
  onClose,
  onDone,
}: {
  target: { row: AbandonedRow; to: AbandonedStatus } | null
  onClose: () => void
  onDone: (to: AbandonedStatus) => void
}) {
  const { t } = useTexT()
  const [note, setNote] = useState("")
  const m = useTexMutation<{ name: string; status: string; note?: string }>("crm", "set_abandoned_status")
  const close = useEvent(() => {
    if (!m.pending) onClose()
  })
  useEffect(() => {
    if (target) {
      setNote("")
      m.clearError()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target])
  if (!target) return null
  const { row, to } = target
  const noteRequired = to === "Dismissed"
  const valid = !noteRequired || note.trim().length > 2
  const submit = async () => {
    if (!valid) return
    try {
      await m.run({ name: row.name, status: to, note: note.trim() || undefined })
      onDone(to)
      onClose()
    } catch {
      /* inline */
    }
  }
  return (
    <Dialog
      open
      onClose={close}
      title={t(actionKey(to))}
      description={t("crm.ab.dialog_desc", { from: t(statusKey(row.status)), to: t(statusKey(to)) })}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={m.pending}>
            {t("core.action.cancel")}
          </Button>
          <Button loading={m.pending} disabled={!valid} onClick={submit}>
            {t("core.action.confirm")}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {to === "Contacted" && !row.consent_marketing && <Notice tone="warning">{t("crm.ab.contact_no_consent")}</Notice>}
        {to === "Recovered" && <p className="text-sm text-zinc-600">{t("crm.ab.recovered_hint")}</p>}
        <Field label={t("crm.ab.note")} required={noteRequired} hint={t("core.hint.reason_audited")}>
          <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} maxLength={300} data-autofocus />
        </Field>
        <InlineError error={m.error} />
      </div>
    </Dialog>
  )
}
