import { useEffect, useMemo, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { Crown, Search, ShieldAlert } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { useProperty, useSession } from "../../lib/session"
import { date, money, num } from "../../lib/format"
import { useTexT } from "../../i18n"
import { Badge, Card, DataTable, EmptyState, ErrorState, Field, Input, PageHeader, Segmented, Select, Toolbar } from "../../ui"
import { ConsentChips, CrmNav, Pager } from "./components/common"
import { useDebounced } from "./lib"
import type { GuestPage, GuestRow, SegmentsResponse } from "./types"

const PAGE = 25

export default function GuestList() {
  const { t } = useTexT()
  const property = useProperty()
  const { can } = useSession()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [q, setQ] = useState(params.get("q") ?? "")
  const dq = useDebounced(q.trim(), 300)
  const vip = params.get("vip") ?? ""
  const consent = params.get("consent") ?? ""
  const segment = params.get("segment") ?? ""
  const scopeAll = params.get("scope") === "all"
  const start = Number(params.get("start") ?? 0) || 0

  const set = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    if (!("start" in patch)) next.delete("start")
    setParams(next, { replace: true })
  }

  useEffect(() => {
    if ((params.get("q") ?? "") !== dq) set({ q: dq })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dq])

  const segs = useTexQuery<SegmentsResponse>("crm", "segments", {}, [])
  const args = {
    q: dq || undefined,
    vip: vip === "" ? undefined : vip,
    consent: consent || undefined,
    segment: segment || undefined,
    property: scopeAll ? undefined : property,
    start,
    limit: PAGE,
  }
  const list = useTexQuery<GuestPage>("crm", "guests", args, [dq, vip, consent, segment, scopeAll, property, start])

  const segmentOptions = useMemo(
    () => (segs.data?.segments ?? []).map((s) => ({ value: s.name, label: s.segment_name })),
    [segs.data],
  )
  const filtered = Boolean(dq || vip || consent || segment)

  return (
    <>
      <PageHeader
        title={t("crm.guests.title")}
        subtitle={t("crm.guests.subtitle")}
        crumbs={[{ label: t("core.nav.crm"), to: "/tex/crm" }, { label: t("crm.nav.guests") }]}
        actions={
          <Segmented<"hotel" | "all">
            label={t("crm.scope.label")}
            size="sm"
            value={scopeAll ? "all" : "hotel"}
            onChange={(v) => set({ scope: v === "all" ? "all" : "" })}
            options={[
              { value: "hotel", label: t("crm.scope.hotel") },
              { value: "all", label: t("crm.scope.all") },
            ]}
          />
        }
      />
      <CrmNav />
      {!can("crm.view") ? (
        <Card>
          <EmptyState title={t("core.error.permission")} description={t("crm.no_access")} />
        </Card>
      ) : (
        <>
          <Toolbar>
            <div className="relative w-full sm:w-72">
              <Field label={t("crm.guests.search")}>
                <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("crm.guests.search_ph")} className="pl-8" />
              </Field>
              <Search className="pointer-events-none absolute bottom-2.5 left-2.5 size-4 text-zinc-400" aria-hidden />
            </div>
            <Field label={t("crm.guests.vip")} className="w-[calc(50%-0.375rem)] sm:w-36">
              <Select
                value={vip}
                onChange={(e) => set({ vip: e.target.value })}
                options={[
                  { value: "", label: t("core.label.all") },
                  { value: "1", label: t("crm.guests.vip_only") },
                  { value: "0", label: t("crm.guests.non_vip") },
                ]}
              />
            </Field>
            <Field label={t("crm.guests.consent")} className="w-[calc(50%-0.375rem)] sm:w-44">
              <Select
                value={consent}
                onChange={(e) => set({ consent: e.target.value })}
                options={[
                  { value: "", label: t("crm.guests.consent_any") },
                  { value: "tex_consent_email", label: t("crm.guests.consent_email") },
                  { value: "tex_consent_sms", label: t("crm.guests.consent_sms") },
                  { value: "tex_consent_whatsapp", label: t("crm.guests.consent_whatsapp") },
                ]}
              />
            </Field>
            <Field label={t("crm.guests.segment")} className="w-full sm:w-56">
              <Select
                value={segment}
                onChange={(e) => set({ segment: e.target.value })}
                disabled={!segmentOptions.length}
                options={[{ value: "", label: t("crm.guests.segment_any") }, ...segmentOptions]}
              />
            </Field>
          </Toolbar>
          <Card>
            {list.error ? (
              <ErrorState error={list.error} onRetry={list.reload} />
            ) : (
              <>
                <DataTable<GuestRow>
                  caption={t("crm.guests.caption")}
                  rows={list.data?.rows}
                  loading={list.loading}
                  rowKey={(r) => r.name}
                  onRowClick={(r) => navigate(`/tex/crm/guests/${encodeURIComponent(r.name)}`)}
                  empty={
                    <EmptyState
                      title={filtered ? t("crm.guests.empty_filtered") : t("crm.guests.empty")}
                      description={filtered ? t("crm.guests.empty_filtered_hint") : t("crm.guests.empty_hint")}
                    />
                  }
                  columns={[
                    {
                      key: "name",
                      header: t("crm.col.guest"),
                      cell: (r) => (
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="font-medium text-zinc-900">{r.full_name || r.name}</span>
                            {r.vip ? (
                              <Badge tone="brand">
                                <Crown className="size-3" aria-hidden />
                                {t("crm.vip")}
                              </Badge>
                            ) : null}
                            {r.blacklisted ? (
                              <Badge tone="danger">
                                <ShieldAlert className="size-3" aria-hidden />
                                {t("crm.blacklisted")}
                              </Badge>
                            ) : null}
                          </div>
                          <p className="truncate text-xs text-zinc-500 md:hidden">{r.email || r.phone || r.name}</p>
                        </div>
                      ),
                    },
                    {
                      key: "contact",
                      header: t("crm.col.contact"),
                      hideBelow: "md",
                      cell: (r) => (
                        <div className="max-w-56 min-w-0 text-xs">
                          <p className="truncate">{r.email || "—"}</p>
                          <p className="truncate text-zinc-500">{r.phone || ""}</p>
                        </div>
                      ),
                    },
                    {
                      key: "market",
                      header: t("crm.col.market"),
                      hideBelow: "lg",
                      cell: (r) => [r.tex_market, r.tex_country].filter(Boolean).join(" · ") || "—",
                    },
                    {
                      key: "consent",
                      header: t("crm.col.consent"),
                      hideBelow: "sm",
                      cell: (r) => <ConsentChips row={r} compact />,
                    },
                    {
                      key: "stays",
                      header: t("crm.col.stays"),
                      align: "right",
                      hideBelow: "sm",
                      sortValue: (r) => r.tex_stays ?? 0,
                      cell: (r) => num(r.tex_stays ?? 0),
                    },
                    {
                      key: "ltv",
                      header: t("crm.col.ltv"),
                      align: "right",
                      hideBelow: "md",
                      cell: (r) => <span className="tabular-nums">{r.tex_lifetime_currency ? money(r.tex_lifetime_value, r.tex_lifetime_currency) : "—"}</span>,
                    },
                    {
                      key: "last",
                      header: t("crm.col.last_stay"),
                      hideBelow: "lg",
                      sortValue: (r) => r.tex_last_stay ?? "",
                      cell: (r) => date(r.tex_last_stay),
                    },
                    {
                      key: "points",
                      header: t("crm.col.points"),
                      align: "right",
                      hideBelow: "lg",
                      cell: (r) => (r.tex_loyalty_points ? num(r.tex_loyalty_points) : "—"),
                    },
                  ]}
                />
                {list.data && (
                  <Pager start={start} pageSize={PAGE} total={list.data.total} onChange={(s) => set({ start: String(s) })} />
                )}
              </>
            )}
          </Card>
          <p className="mt-3 text-xs text-zinc-500">{t("crm.guests.ltv_hint")}</p>
        </>
      )}
    </>
  )
}
