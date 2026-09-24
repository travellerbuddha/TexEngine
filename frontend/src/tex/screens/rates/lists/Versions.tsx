import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { History, Search } from "lucide-react"
import { useTexQuery } from "../../../lib/api"
import { dateTime } from "../../../lib/format"
import { useHotelScope } from "../../../lib/hotelScope"
import { useTexT } from "../../../i18n"
import { Badge, Card, DataTable, EmptyState, ErrorState, Field, Input, Notice, PageHeader, Select, Toolbar } from "../../../ui"
import { RatesNav } from "../components/RatesNav"
import { enumOptions } from "../lib/options"
import { versionLabel } from "../lib/util"
import { ContractViews, VersionStateBadge } from "./ContractViews"
import type { ListOf, VersionListRow } from "./types"

const CAPS = ["price.view"] as const
const STATUSES = ["Draft", "Published", "Superseded", "Withdrawn"] as const

/** Every version of every contract (R-35 Contract Versions, G-64): what sells now, what is
 * scheduled, drafts and history. Opens the version editor. */
export default function Versions() {
  const { t } = useTexT()
  const navigate = useNavigate()
  const hotels = useHotelScope(CAPS)
  const [status, setStatus] = useState("")
  const [q, setQ] = useState("")
  const list = useTexQuery<ListOf<VersionListRow>>("lists", "versions", { property: hotels.property, status: status || undefined }, [hotels.property, status])

  const rows = useMemo(() => {
    const term = q.trim().toLowerCase()
    const all = list.data?.rows
    if (!term || !all) return all
    return all.filter((r) => `${r.contract_code} ${r.contract_name} ${r.market} ${r.change_note ?? ""}`.toLowerCase().includes(term))
  }, [list.data, q])

  return (
    <>
      <RatesNav />
      <PageHeader
        title={t("core.nav.sub.versions")}
        subtitle={t("rates.lists.versions.subtitle")}
        crumbs={[{ label: t("core.nav.rates"), to: "/tex/rates" }, { label: t("core.nav.sub.versions") }]}
      />
      <ContractViews />
      <Toolbar>
        <Field label={t("core.action.search")} className="w-full sm:w-64">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-zinc-400" aria-hidden />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("rates.contracts.search_ph")} className="pl-8" type="search" />
          </div>
        </Field>
        <Field label={t("rates.f.status")} className="w-full sm:w-44">
          <Select value={status} onChange={(e) => setStatus(e.target.value)} options={enumOptions(t, "version_status", STATUSES)} placeholder={t("core.label.all")} />
        </Field>
        {hotels.control && <div className="self-end">{hotels.control}</div>}
      </Toolbar>
      {list.data?.truncated && (
        <div className="mb-3">
          <Notice tone="info">{t("rates.lists.truncated")}</Notice>
        </div>
      )}
      <Card>
        {list.error ? (
          <ErrorState error={list.error} onRetry={list.reload} />
        ) : (
          <DataTable<VersionListRow>
            caption={t("core.nav.sub.versions")}
            rows={rows}
            loading={list.loading}
            rowKey={(r) => r.name}
            onRowClick={(r) => navigate(`/tex/rates/contracts/${encodeURIComponent(r.contract)}/versions/${encodeURIComponent(r.name)}`)}
            empty={<EmptyState icon={<History className="size-5" />} title={q || status ? t("rates.lists.none_filtered") : t("rates.lists.versions.none")} />}
            columns={[
              {
                key: "contract",
                header: t("rates.col.contract"),
                sortValue: (r) => r.contract_code,
                cell: (r) => (
                  <div className="min-w-0">
                    <p className="font-medium text-zinc-900">{r.contract_code}</p>
                    <p className="max-w-56 truncate text-xs text-zinc-500">{r.contract_name}</p>
                  </div>
                ),
              },
              {
                key: "version",
                header: t("rates.lists.col.version"),
                sortValue: (r) => r.version_no,
                cell: (r) => (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium tabular-nums">{versionLabel(r.name, r.version_no)}</span>
                    <VersionStateBadge state={r.state} />
                  </div>
                ),
              },
              ...(hotels.all ? [{ key: "hotel", header: t("rates.f.hotel"), hideBelow: "md" as const, sortValue: (r: VersionListRow) => hotels.hotelName(r.property), cell: (r: VersionListRow) => hotels.hotelName(r.property) }] : []),
              {
                key: "market",
                header: t("rates.f.market"),
                hideBelow: "sm",
                sortValue: (r) => r.market,
                cell: (r) => <Badge tone="brand">{r.market}</Badge>,
              },
              {
                key: "effective_from",
                header: t("rates.version.sells_from"),
                hideBelow: "md",
                sortValue: (r) => r.effective_from ?? "",
                cell: (r) => <span className="whitespace-nowrap">{r.effective_from ? dateTime(r.effective_from) : t("rates.version.not_yet")}</span>,
              },
              {
                key: "active_to",
                header: t("rates.version.sells_until"),
                hideBelow: "lg",
                sortValue: (r) => r.active_to ?? "",
                cell: (r) => <span className="whitespace-nowrap text-zinc-600">{r.active_to ? dateTime(r.active_to) : r.status === "Published" ? t("rates.version.open_end") : "—"}</span>,
              },
              {
                key: "published_by",
                header: t("rates.version.published_by"),
                hideBelow: "lg",
                sortValue: (r) => r.published_at ?? "",
                cell: (r) =>
                  r.published_by ? (
                    <span className="text-zinc-700">
                      {r.published_by}
                      <span className="block text-xs text-zinc-500">{dateTime(r.published_at)}</span>
                    </span>
                  ) : (
                    "—"
                  ),
              },
              {
                key: "note",
                header: t("rates.f.change_note"),
                hideBelow: "lg",
                cell: (r) => <span className="line-clamp-2 max-w-64 text-zinc-600">{r.change_note || "—"}</span>,
              },
            ]}
            initialSort={{ key: "contract", dir: "asc" }}
          />
        )}
      </Card>
    </>
  )
}
