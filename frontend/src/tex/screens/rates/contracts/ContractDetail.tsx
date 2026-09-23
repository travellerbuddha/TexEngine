import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { Archive, ArchiveRestore, Ban, CheckCircle2, CirclePause, CirclePlay, Copy, FilePlus2, History, Pencil, PencilLine, Rocket, Undo2 } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { useTexQuery } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { dateTime } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, Card, CardBody, CardHeader, DescriptionList, EmptyState, ErrorState, PageHeader, Skeleton } from "../../../ui"
import { DateRange, StatusBadge } from "../components/common"
import { RatesNav } from "../components/RatesNav"
import { enumLabel } from "../lib/options"
import type { ContractBundle, ContractStatusAction, VersionRow } from "../lib/types"
import { versionLabel } from "../lib/util"
import { ContractFormDialog, ContractStatusDialog, DuplicateDialog } from "./ContractDialogs"
import { NewDraftDialog, PublishDialog, WithdrawDialog } from "./VersionActions"

// explicit, audited status actions (G-50); the header form never changes the status
const STATUS_ICON: Record<ContractStatusAction, typeof CheckCircle2> = {
  suspend: CirclePause,
  resume: CirclePlay,
  archive: Archive,
  restore: ArchiveRestore,
}

const DOT: Record<string, { cls: string; icon: typeof CheckCircle2 }> = {
  Draft: { cls: "bg-amber-100 text-amber-800 ring-amber-300", icon: PencilLine },
  Published: { cls: "bg-emerald-100 text-emerald-800 ring-emerald-300", icon: CheckCircle2 },
  Superseded: { cls: "bg-zinc-100 text-zinc-600 ring-zinc-300", icon: History },
  Withdrawn: { cls: "bg-rose-100 text-rose-700 ring-rose-300", icon: Ban },
}

/** Contract header + versions timeline with the publishing lifecycle (R-05). */
export default function ContractDetail() {
  const { name = "" } = useParams()
  const { t } = useTexT()
  const navigate = useNavigate()
  const { boot } = useSession()
  const q = useTexQuery<ContractBundle>("contracts", "get_contract", { name }, [name])
  const [editing, setEditing] = useState(false)
  const [duplicating, setDuplicating] = useState(false)
  const [draftFrom, setDraftFrom] = useState<string | null>(null)
  const [publishing, setPublishing] = useState<VersionRow | null>(null)
  const [withdrawing, setWithdrawing] = useState<VersionRow | null>(null)
  const [statusAction, setStatusAction] = useState<ContractStatusAction | null>(null)

  const b = q.data
  const c = b?.contract
  const draft = b?.versions.find((v) => v.status === "Draft")
  const editorLink = (v: string) => `/tex/rates/contracts/${encodeURIComponent(name)}/versions/${encodeURIComponent(v)}`

  if (q.error)
    return (
      <>
        <RatesNav />
        <PageHeader title={t("rates.contract.title")} crumbs={[{ label: t("core.nav.rates"), to: "/tex/rates" }, { label: name }]} />
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      </>
    )

  return (
    <>
      <RatesNav />
      <PageHeader
        crumbs={[{ label: t("core.nav.rates"), to: "/tex/rates" }, { label: c?.contract_code ?? name }]}
        title={c ? c.contract_name : <Skeleton className="h-7 w-64" />}
        meta={
          c && (
            <>
              <Badge tone="neutral" className="font-mono">
                {c.contract_code}
              </Badge>
              <StatusBadge status={c.status} group="contract_status" />
              <Badge tone="brand">{c.market}</Badge>
              <Badge>
                {enumLabel(t, "basis", c.pricing_basis)} · {c.contract_currency}
              </Badge>
              {c.is_bar ? <Badge tone="info">{t("rates.f.is_bar_short")}</Badge> : null}
            </>
          )
        }
        actions={
          (b?.can_edit || Boolean(b?.status_actions?.length)) && (
            <>
              {(b?.status_actions ?? []).map((a) => {
                const Icon = STATUS_ICON[a]
                return (
                  <Button key={a} variant="secondary" icon={<Icon className="size-4" aria-hidden />} onClick={() => setStatusAction(a)}>
                    {t(`rates.contract.status_action.${a}`)}
                  </Button>
                )
              })}
              {b?.can_edit && (
                <>
                  <Button variant="secondary" icon={<Pencil className="size-4" aria-hidden />} onClick={() => setEditing(true)}>
                    {t("rates.contract.edit_header")}
                  </Button>
                  <Button variant="secondary" icon={<Copy className="size-4" aria-hidden />} onClick={() => setDuplicating(true)}>
                    {t("rates.contract.duplicate")}
                  </Button>
                  {draft ? (
                    <Button icon={<PencilLine className="size-4" aria-hidden />} onClick={() => navigate(editorLink(draft.name))}>
                      {t("rates.version.open_draft", { v: versionLabel(draft.name, draft.version_no) })}
                    </Button>
                  ) : (
                    <Button icon={<FilePlus2 className="size-4" aria-hidden />} onClick={() => setDraftFrom("")}>
                      {t("rates.version.new_draft")}
                    </Button>
                  )}
                </>
              )}
            </>
          )
        }
      />

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title={t("rates.version.timeline")} description={t("rates.version.timeline_hint")} />
          <CardBody>
            {!b ? (
              <div className="space-y-4">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-16 w-full" />
                ))}
              </div>
            ) : b.versions.length === 0 ? (
              <EmptyState title={t("rates.version.none")} />
            ) : (
              <ol aria-label={t("rates.version.timeline")} className="relative space-y-5 before:absolute before:top-2 before:bottom-2 before:left-4 before:w-px before:bg-zinc-200">
                {b.versions.map((v) => {
                  const d = DOT[v.status] ?? DOT.Superseded
                  const live = c?.active_version === v.name
                  return (
                    <li key={v.name} className="relative flex gap-3">
                      <span className={cn("relative z-[1] grid size-8 shrink-0 place-items-center rounded-full ring-2", d.cls)} aria-hidden>
                        <d.icon className="size-4" />
                      </span>
                      <div className="min-w-0 flex-1 rounded-lg border border-zinc-200 p-3">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <Link to={editorLink(v.name)} className="text-base font-semibold text-zinc-950 hover:underline">
                              {versionLabel(v.name, v.version_no)}
                            </Link>
                            <StatusBadge status={v.status} group="version_status" />
                            {live && (
                              <Badge tone="success">
                                <CheckCircle2 className="size-3" aria-hidden />
                                {t("rates.version.selling_now")}
                              </Badge>
                            )}
                            {v.based_on && <span className="text-xs text-zinc-500">{t("rates.version.based_on", { v: versionLabel(v.based_on) })}</span>}
                          </div>
                          <VersionButtons
                            v={v}
                            canEdit={Boolean(b.can_edit)}
                            canPublish={Boolean(b.can_publish)}
                            hasDraft={Boolean(draft)}
                            onOpen={() => navigate(editorLink(v.name))}
                            onPublish={() => setPublishing(v)}
                            onWithdraw={() => setWithdrawing(v)}
                            onDraftFrom={() => setDraftFrom(v.name)}
                          />
                        </div>
                        <dl className="mt-2 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
                          <div>
                            <dt className="text-xs text-zinc-500">{t("rates.version.sells_from")}</dt>
                            <dd className="text-zinc-800">{v.status === "Draft" ? t("rates.version.not_yet") : dateTime(v.effective_from)}</dd>
                          </div>
                          <div>
                            <dt className="text-xs text-zinc-500">{t("rates.version.sells_until")}</dt>
                            <dd className="text-zinc-800">{v.status === "Draft" ? "—" : v.active_to ? dateTime(v.active_to) : t("rates.version.open_end")}</dd>
                          </div>
                          {v.published_at && (
                            <div className="sm:col-span-2">
                              <dt className="text-xs text-zinc-500">{t("rates.version.published_by")}</dt>
                              <dd className="text-zinc-800">
                                {v.published_by ?? "—"} · {dateTime(v.published_at)}
                              </dd>
                            </div>
                          )}
                        </dl>
                        {v.change_note && <p className="mt-2 rounded-md bg-zinc-50 px-2.5 py-1.5 text-sm whitespace-pre-line text-zinc-700">{v.change_note}</p>}
                      </div>
                    </li>
                  )
                })}
              </ol>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={t("rates.contract.details")} description={b?.published ? t("rates.contract.details_live") : undefined} />
          <CardBody>
            {!c ? (
              <Skeleton className="h-40 w-full" />
            ) : (
              <DescriptionList
                cols={1}
                items={[
                  { label: t("rates.f.market"), value: `${c.market} · ${boot.markets.find((m) => m.name === c.market)?.market_name ?? ""}` },
                  { label: t("rates.col.sale_window"), value: <DateRange from={c.sale_from} to={c.sale_to} /> },
                  { label: t("rates.col.stay_window"), value: <DateRange from={c.stay_from} to={c.stay_to} /> },
                  { label: t("rates.f.pricing_basis"), value: enumLabel(t, "basis", c.pricing_basis) },
                  { label: t("rates.f.contract_currency"), value: c.contract_currency },
                  { label: t("rates.f.sell_currency"), value: c.sell_currency || t("rates.common.same_as_contract") },
                  { label: t("rates.f.priority"), value: String(c.priority ?? 0) },
                  {
                    label: t("rates.f.channels"),
                    value: c.channels.length
                      ? c.channels.map((x) => boot.channels.find((ch) => ch.name === x.sales_channel)?.channel_name ?? x.sales_channel).join(", ")
                      : t("rates.common.all_channels"),
                  },
                  { label: t("rates.col.active_version"), value: c.active_version ? versionLabel(c.active_version) : t("rates.contracts.not_published") },
                  ...(c.notes ? [{ label: t("rates.f.notes"), value: <span className="whitespace-pre-line">{c.notes}</span> }] : []),
                ]}
              />
            )}
          </CardBody>
        </Card>
      </div>

      {c && (
        <>
          <ContractFormDialog open={editing} onClose={() => setEditing(false)} contract={c} published={Boolean(b?.published)} onSaved={() => q.reload()} />
          {statusAction && (
            <ContractStatusDialog
              open
              onClose={() => setStatusAction(null)}
              contract={c}
              action={statusAction}
              onDone={() => {
                setStatusAction(null)
                q.reload()
              }}
            />
          )}
          <DuplicateDialog open={duplicating} onClose={() => setDuplicating(false)} contract={c} onDone={(nb) => navigate(`/tex/rates/contracts/${encodeURIComponent(nb.contract.name)}`)} />
          <NewDraftDialog
            open={draftFrom !== null}
            onClose={() => setDraftFrom(null)}
            contract={c.name}
            versions={b?.versions ?? []}
            basedOn={draftFrom || undefined}
            onDone={(v) => navigate(editorLink(v))}
          />
          {publishing && (
            <PublishDialog open onClose={() => setPublishing(null)} version={publishing} contractCode={c.contract_code} onDone={q.reload} />
          )}
          {withdrawing && <WithdrawDialog open onClose={() => setWithdrawing(null)} version={withdrawing} onDone={q.reload} />}
        </>
      )}
    </>
  )
}

function VersionButtons({
  v,
  canEdit,
  canPublish,
  hasDraft,
  onOpen,
  onPublish,
  onWithdraw,
  onDraftFrom,
}: {
  v: VersionRow
  canEdit: boolean
  canPublish: boolean
  hasDraft: boolean
  onOpen: () => void
  onPublish: () => void
  onWithdraw: () => void
  onDraftFrom: () => void
}) {
  const { t } = useTexT()
  const label = versionLabel(v.name, v.version_no)
  return (
    <div className="flex flex-wrap gap-1.5">
      <Button size="sm" variant="secondary" onClick={onOpen} aria-label={t(v.status === "Draft" && canEdit ? "rates.version.edit_v" : "rates.version.view_v", { v: label })}>
        {v.status === "Draft" && canEdit ? t("core.action.edit") : t("core.action.view")}
      </Button>
      {v.status === "Draft" && canPublish && (
        <Button size="sm" icon={<Rocket className="size-3.5" aria-hidden />} onClick={onPublish} aria-label={t("rates.version.publish_v", { v: label })}>
          {t("rates.version.publish")}
        </Button>
      )}
      {v.status !== "Draft" && canEdit && (
        <Button
          size="sm"
          variant="ghost"
          icon={<FilePlus2 className="size-3.5" aria-hidden />}
          onClick={onDraftFrom}
          disabled={hasDraft}
          title={hasDraft ? t("rates.version.draft_exists") : undefined}
          aria-label={t("rates.version.draft_from_v", { v: label })}
        >
          {t("rates.version.draft_from")}
        </Button>
      )}
      {v.status === "Published" && canPublish && (
        <Button size="sm" variant="ghost" className="text-rose-700! hover:bg-rose-50!" icon={<Undo2 className="size-3.5" aria-hidden />} onClick={onWithdraw} aria-label={t("rates.version.withdraw_v", { v: label })}>
          {t("rates.version.withdraw")}
        </Button>
      )}
    </div>
  )
}
