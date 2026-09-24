import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Copy, FileText, Plus, Search } from "lucide-react"
import { useTexQuery } from "../../../lib/api"
import { useProperty, useSession } from "../../../lib/session"
import { useTexT } from "../../../i18n"
import { Badge, Button, Card, DataTable, EmptyState, ErrorState, Field, IconButton, Input, PageHeader, Select, Toolbar } from "../../../ui"
import { DateRange, StatusBadge } from "../components/common"
import { RatesNav } from "../components/RatesNav"
import { CONTRACT_STATUS, enumLabel, enumOptions } from "../lib/options"
import type { ContractRow } from "../lib/types"
import { versionLabel } from "../lib/util"
import { ContractFormDialog, DuplicateDialog } from "./ContractDialogs"
import { ContractViews } from "../lists/ContractViews"

/** Contracts of the selected hotel with status / market filters (R-04). */
export default function ContractsList() {
  const { t } = useTexT()
  const navigate = useNavigate()
  const property = useProperty()
  const { can, boot } = useSession()
  const [status, setStatus] = useState("")
  const [market, setMarket] = useState("")
  const [q, setQ] = useState("")
  const [creating, setCreating] = useState(false)
  const [dupOf, setDupOf] = useState<ContractRow | null>(null)
  const canEdit = can("contract.edit")
  const list = useTexQuery<ContractRow[]>("contracts", "list_contracts", { property, status: status || undefined, market: market || undefined }, [property, status, market], Boolean(property))

  const rows = useMemo(() => {
    const term = q.trim().toLowerCase()
    if (!term) return list.data
    return list.data?.filter((r) => `${r.contract_code} ${r.contract_name} ${r.market}`.toLowerCase().includes(term))
  }, [list.data, q])

  const marketName = (code: string) => boot.markets.find((m) => m.name === code)?.market_name ?? code

  return (
    <>
      <RatesNav />
      <PageHeader
        title={t("core.nav.rates")}
        subtitle={t("rates.contracts.subtitle")}
        actions={
          canEdit && (
            <Button icon={<Plus className="size-4" aria-hidden />} onClick={() => setCreating(true)}>
              {t("rates.contract.new")}
            </Button>
          )
        }
      />
      <ContractViews />
      <Toolbar>
        <Field label={t("core.action.search")} className="w-full sm:w-64">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-zinc-400" aria-hidden />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("rates.contracts.search_ph")} className="pl-8" type="search" />
          </div>
        </Field>
        <Field label={t("rates.f.status")} className="w-[calc(50%-0.375rem)] sm:w-44">
          <Select value={status} onChange={(e) => setStatus(e.target.value)} options={enumOptions(t, "contract_status", CONTRACT_STATUS)} placeholder={t("core.label.all")} />
        </Field>
        <Field label={t("rates.f.market")} className="w-[calc(50%-0.375rem)] sm:w-48">
          <Select value={market} onChange={(e) => setMarket(e.target.value)} options={boot.markets.map((m) => ({ value: m.name, label: `${m.name} · ${m.market_name}` }))} placeholder={t("core.label.all")} />
        </Field>
      </Toolbar>
      <Card>
        {list.error ? (
          <ErrorState error={list.error} onRetry={list.reload} />
        ) : (
          <DataTable<ContractRow>
            caption={t("rates.contracts.caption")}
            rows={rows}
            loading={list.loading}
            rowKey={(r) => r.name}
            onRowClick={(r) => navigate(`/tex/rates/contracts/${encodeURIComponent(r.name)}`)}
            initialSort={{ key: "code", dir: "asc" }}
            empty={
              <EmptyState
                icon={<FileText className="size-5" />}
                title={status || market || q ? t("rates.contracts.none_filtered") : t("rates.contracts.none")}
                description={canEdit && !(status || market || q) ? t("rates.contracts.none_hint") : undefined}
                action={
                  canEdit && !(status || market || q) ? (
                    <Button size="sm" onClick={() => setCreating(true)}>
                      {t("rates.contract.new")}
                    </Button>
                  ) : undefined
                }
              />
            }
            columns={[
              {
                key: "code",
                header: t("rates.col.contract"),
                sortValue: (r) => r.contract_code,
                cell: (r) => (
                  <div className="min-w-0">
                    <p className="font-medium text-zinc-900">
                      {r.contract_code}
                      <span className="ml-1.5 sm:hidden">
                        <Badge tone="brand">{r.market}</Badge>
                      </span>
                    </p>
                    <p className="max-w-64 truncate text-xs text-zinc-500">{r.contract_name}</p>
                  </div>
                ),
              },
              {
                key: "market",
                header: t("rates.f.market"),
                hideBelow: "sm",
                sortValue: (r) => r.market,
                cell: (r) => (
                  <span title={marketName(r.market)}>
                    <Badge tone="brand">{r.market}</Badge>
                  </span>
                ),
              },
              {
                key: "status",
                header: t("rates.f.status"),
                sortValue: (r) => r.status,
                cell: (r) => (
                  <div className="flex flex-wrap gap-1">
                    <StatusBadge status={r.status} group="contract_status" />
                    {r.has_draft && <Badge tone="warning">{t("rates.contracts.draft_pending")}</Badge>}
                  </div>
                ),
              },
              {
                key: "active_version",
                header: t("rates.col.active_version"),
                hideBelow: "sm",
                sortValue: (r) => r.active_version ?? "",
                cell: (r) =>
                  r.active_version ? (
                    <span className="font-medium tabular-nums">{versionLabel(r.active_version)}</span>
                  ) : (
                    <span className="text-zinc-500">{t("rates.contracts.not_published")}</span>
                  ),
              },
              {
                key: "sale",
                header: t("rates.col.sale_window"),
                hideBelow: "md",
                sortValue: (r) => r.sale_from ?? "",
                cell: (r) => <DateRange from={r.sale_from} to={r.sale_to} />,
              },
              {
                key: "stay",
                header: t("rates.col.stay_window"),
                hideBelow: "md",
                sortValue: (r) => r.stay_from ?? "",
                cell: (r) => <DateRange from={r.stay_from} to={r.stay_to} />,
              },
              {
                key: "basis",
                header: t("rates.col.basis"),
                hideBelow: "lg",
                cell: (r) => (
                  <span className="whitespace-nowrap text-zinc-600">
                    {enumLabel(t, "basis", r.pricing_basis)} · {r.contract_currency}
                  </span>
                ),
              },
              ...(canEdit
                ? [
                    {
                      key: "actions",
                      header: <span className="sr-only">{t("rates.common.row_actions")}</span>,
                      align: "right" as const,
                      cell: (r: ContractRow) => (
                        <IconButton
                          size="sm"
                          label={t("rates.contract.duplicate_label", { code: r.contract_code })}
                          icon={<Copy className="size-4" />}
                          onClick={(e) => {
                            e.stopPropagation()
                            setDupOf(r)
                          }}
                          onKeyDown={(e) => e.stopPropagation()}
                        />
                      ),
                    },
                  ]
                : []),
            ]}
          />
        )}
      </Card>
      <ContractFormDialog open={creating} onClose={() => setCreating(false)} onSaved={(b) => navigate(`/tex/rates/contracts/${encodeURIComponent(b.contract.name)}`)} />
      {dupOf && (
        <DuplicateDialog
          open
          onClose={() => setDupOf(null)}
          contract={dupOf}
          onDone={(b) => navigate(`/tex/rates/contracts/${encodeURIComponent(b.contract.name)}`)}
        />
      )}
    </>
  )
}
