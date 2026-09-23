import { useNavigate } from "react-router-dom"
import { Award, CheckCircle2, Eye, Plus, XCircle } from "lucide-react"
import { useTexQuery } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { num } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, Card, DataTable, EmptyState, ErrorState, Money, PageHeader } from "../../../ui"
import { CrmNav } from "../components/common"
import type { ProgramRow, ProgramsResponse } from "../types"
import { decimalText, scopeText } from "./lib"

/** Enabled/disabled as icon + text (never colour alone). */
export function EnabledBadge({ enabled }: { enabled: boolean }) {
  const { t } = useTexT()
  return enabled ? (
    <Badge tone="success">
      <CheckCircle2 className="size-3" aria-hidden />
      {t("crm.programs.enabled")}
    </Badge>
  ) : (
    <Badge tone="neutral">
      <XCircle className="size-3" aria-hidden />
      {t("crm.programs.disabled")}
    </Badge>
  )
}

/** /tex/crm/loyalty — the loyalty programs of the user's hotels and groups (ADR-037). */
export default function Programs() {
  const { t } = useTexT()
  const { boot, canAnywhere } = useSession()
  const navigate = useNavigate()
  const q = useTexQuery<ProgramsResponse>("loyalty", "programs", {}, [], canAnywhere("crm.view"))
  const scopes = q.data?.scopes
  const canCreate = Boolean(scopes && (scopes.hotels.length || scopes.groups.length))
  const open = (p: ProgramRow) => navigate(`/tex/crm/loyalty/${encodeURIComponent(p.name)}`)

  return (
    <>
      <PageHeader
        title={t("crm.programs.title")}
        subtitle={t("crm.programs.subtitle")}
        crumbs={[{ label: t("core.nav.crm"), to: "/tex/crm" }, { label: t("crm.nav.loyalty") }]}
        actions={
          canCreate ? (
            <Button icon={<Plus className="size-4" aria-hidden />} onClick={() => navigate("/tex/crm/loyalty/new")}>
              {t("crm.programs.new")}
            </Button>
          ) : undefined
        }
      />
      <CrmNav />
      {!canAnywhere("crm.view") ? (
        <Card>
          <EmptyState title={t("core.error.permission")} description={t("crm.no_access")} />
        </Card>
      ) : q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : (
        <>
          <Card>
            <DataTable<ProgramRow>
              caption={t("crm.programs.caption")}
              rows={q.data?.programs}
              loading={q.loading}
              rowKey={(p) => p.name}
              onRowClick={open}
              empty={
                <EmptyState
                  icon={<Award className="size-5" />}
                  title={t("crm.programs.empty")}
                  description={canCreate ? t("crm.programs.empty_hint") : t("crm.programs.empty_readonly")}
                />
              }
              columns={[
                {
                  key: "program",
                  header: t("crm.programs.col.program"),
                  sortValue: (p) => p.program_name,
                  cell: (p) => (
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="font-medium text-zinc-900">{p.program_name}</span>
                        {!p.can_edit && (
                          <Badge tone="neutral">
                            <Eye className="size-3" aria-hidden />
                            {t("crm.programs.view_only")}
                          </Badge>
                        )}
                      </div>
                      <p className="truncate text-xs text-zinc-500">{scopeText(t, boot, p)}</p>
                      <p className="text-xs text-zinc-500 sm:hidden">
                        {t("crm.programs.col.members")}: {num(p.members)}
                      </p>
                    </div>
                  ),
                },
                { key: "status", header: t("crm.programs.col.status"), cell: (p) => <EnabledBadge enabled={Boolean(p.enabled)} /> },
                { key: "currency", header: t("crm.programs.col.currency"), hideBelow: "lg", cell: (p) => p.currency || "—" },
                {
                  key: "point_value",
                  header: t("crm.programs.col.point_value"),
                  align: "right",
                  hideBelow: "lg",
                  cell: (p) => (p.currency ? `${decimalText(p.point_value)} ${p.currency}` : decimalText(p.point_value)),
                },
                { key: "members", header: t("crm.programs.col.members"), align: "right", hideBelow: "sm", sortValue: (p) => p.members, cell: (p) => num(p.members) },
                {
                  key: "available",
                  header: t("crm.programs.col.available"),
                  align: "right",
                  hideBelow: "md",
                  sortValue: (p) => p.available_points,
                  cell: (p) => num(p.available_points),
                },
                { key: "pending", header: t("crm.programs.col.pending"), align: "right", hideBelow: "lg", cell: (p) => num(p.pending_points) },
                {
                  key: "liability",
                  header: t("crm.programs.col.liability"),
                  align: "right",
                  cell: (p) => (p.currency ? <Money amount={p.liability} currency={p.currency} /> : "—"),
                },
              ]}
            />
          </Card>
          <p className="mt-3 text-xs text-zinc-500">{t("crm.programs.liability_hint")}</p>
        </>
      )}
    </>
  )
}
