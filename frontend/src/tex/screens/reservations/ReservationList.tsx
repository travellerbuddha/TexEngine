import { useEffect, useMemo, useState } from "react"
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom"
import { ChevronLeft, ChevronRight, Lock, Plus, Search, X } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { date, num } from "../../lib/format"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import { Badge, Button, Card, Checkbox, DataTable, EmptyState, ErrorState, Field, Input, Money, PageHeader, Select, Skeleton, statusTone, Toolbar } from "../../ui"
import { useLabels } from "../crs/lib/labels"
import type { ReservationRow } from "./lib/types"

const PAGE = 25
export const STATUSES = ["Confirmed", "Pending Payment", "Held", "Requested", "Checked In", "Checked Out", "Cancelled", "No Show"]

/** Reservations list (search, status, arrival range, pending guest changes, paging). */
export default function ReservationList() {
  const { t } = useTexT()
  const L = useLabels()
  const navigate = useNavigate()
  const { boot, can, canAnywhere, property: current } = useSession()
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const q = params.get("q") ?? ""
  const status = params.get("status") ?? ""
  const hotels = boot.properties.filter((p) => p.capabilities.includes("reservation.view"))
  // the hotel the screen works on, unless "all hotels" is chosen (UX revision 2026-10): every
  // hotel is an explicit choice (?property=all), never the silent default
  const wanted = params.get("property") ?? ""
  const all = hotels.length > 1 && wanted === "all"
  const property = all ? "" : wanted && wanted !== "all" ? wanted : hotels.length > 1 && current && hotels.some((h) => h.name === current.name) ? current.name : ""
  const from = params.get("from") ?? ""
  const to = params.get("to") ?? ""
  const pending = params.get("guest_changes") === "1"
  const page = Math.max(0, Number(params.get("page") ?? 0) || 0)
  const [draft, setDraft] = useState(q)
  useEffect(() => setDraft(q), [q])

  // built from the URL as it is now, not as this render saw it: a debounced search, or a change made
  // right after Enter, never undoes the change before it (a hotel chosen within 350 ms was lost)
  const liveParams = () => new URLSearchParams(window.location.search)
  const update = (patch: Record<string, string | null>, keepPage = false) => {
    const next = liveParams()
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    if (!keepPage) next.delete("page")
    setParams(next, { replace: true })
  }

  // debounce the free-text search into the URL (nothing to do when Enter already put it there). A row
  // opened just before it fires has left the list already (the URL changes at once, the list unmounts
  // after the detail renders): the search is no longer the page's, so it never pulls the list back
  useEffect(() => {
    if (draft === q) return
    const path = window.location.pathname
    const h = window.setTimeout(() => {
      if (window.location.pathname !== path) return
      if ((liveParams().get("q") ?? "") !== draft.trim()) update({ q: draft.trim() || null })
    }, 350)
    return () => window.clearTimeout(h)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft])

  const args = useMemo(
    () => ({
      property: property || undefined,
      q: q || undefined,
      status: status || undefined,
      arrival_from: from || undefined,
      arrival_to: to || undefined,
      pending_only: pending ? (1 as const) : undefined,
      limit: PAGE + 1,
      start: page * PAGE,
    }),
    [property, q, status, from, to, pending, page],
  )
  const list = useTexQuery<ReservationRow[]>("crs", "reservations", args, [JSON.stringify(args)], canAnywhere("reservation.view"))
  const rows = list.data?.slice(0, PAGE)
  const hasNext = (list.data?.length ?? 0) > PAGE
  const filtered = Boolean(q || status || (wanted && wanted !== "all" && wanted !== current?.name) || from || to || pending)
  // nothing found in one hotel for a number or a name: the other hotels are one click away
  const elsewhere = Boolean(q && !all && hotels.length > 1 && rows && rows.length === 0 && !list.loading)
  const open = (name: string) => navigate(`/tex/reservations/${encodeURIComponent(name)}`, { state: { back: location.search } })

  if (!canAnywhere("reservation.view"))
    return (
      <>
        <PageHeader title={t("core.nav.reservations")} />
        <Card>
          <EmptyState icon={<Lock className="size-5" />} title={t("core.error.permission")} description={t("res.list.no_access")} />
        </Card>
      </>
    )

  return (
    <>
      <PageHeader
        title={t("core.nav.reservations")}
        subtitle={t("res.list.subtitle")}
        actions={
          canAnywhere("reservation.create") ? (
            <Link
              to="/tex/crs"
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-tex-600 px-3.5 text-sm font-medium text-white shadow-sm hover:bg-tex-700 dark:text-zinc-50"
            >
              <Plus className="size-4" aria-hidden />
              {t("core.cmd.new_booking")}
            </Link>
          ) : undefined
        }
      />
      <Card className="mb-4 p-4">
        <Toolbar className="mb-0">
          <div className="w-full min-w-0 sm:w-72">
            <label htmlFor="res-q" className="mb-1.5 block text-sm font-medium text-zinc-800">
              {t("core.action.search")}
            </label>
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-zinc-400" aria-hidden />
              <Input
                id="res-q"
                type="search"
                className="pl-8"
                placeholder={t("res.list.search_placeholder")}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && update({ q: draft.trim() || null })}
              />
            </div>
          </div>
          <Field label={t("core.label.status")} className="w-full sm:w-44">
            <Select
              id="res-status"
              value={status}
              onChange={(e) => update({ status: e.target.value || null })}
              options={[{ value: "", label: t("core.label.all") }, ...STATUSES.map((s) => ({ value: s, label: L.status(s) }))]}
            />
          </Field>
          {hotels.length > 1 && (
            <Field label={t("core.shell.hotel")} className="w-full sm:w-52">
              <Select
                id="res-hotel"
                value={all ? "all" : property}
                onChange={(e) => update({ property: e.target.value === current?.name ? null : e.target.value })}
                options={[...hotels.map((h) => ({ value: h.name, label: h.property_name })), { value: "all", label: t("res.list.all_hotels_n", { count: hotels.length }) }]}
              />
            </Field>
          )}
          <Field label={t("res.list.arrival_from")} className="w-[calc(50%-0.375rem)] sm:w-40">
            <Input id="res-from" type="date" value={from} max={to || undefined} onChange={(e) => update({ from: e.target.value || null })} />
          </Field>
          <Field label={t("res.list.arrival_to")} className="w-[calc(50%-0.375rem)] sm:w-40">
            <Input id="res-to" type="date" value={to} min={from || undefined} onChange={(e) => update({ to: e.target.value || null })} />
          </Field>
          <Checkbox
            className="h-9"
            label={t("res.list.guest_changes")}
            checked={pending}
            onChange={(e) => update({ guest_changes: e.target.checked ? "1" : null })}
          />
          {filtered && (
            <Button
              variant="ghost"
              icon={<X className="size-4" aria-hidden />}
              onClick={() => {
                setDraft("")
                setParams(new URLSearchParams(), { replace: true })
              }}
            >
              {t("res.list.clear")}
            </Button>
          )}
        </Toolbar>
      </Card>

      <Card>
        {list.error ? (
          <ErrorState error={list.error} onRetry={list.reload} />
        ) : (
          <>
            {/* phones: one card per reservation; wider screens: the sortable table */}
            <MobileList rows={rows} loading={list.loading} hotels={hotels} canPrice={(p) => can("price.view", p)} empty={pending ? t("res.list.no_changes") : filtered ? t("res.list.none_filtered") : t("res.list.none")} back={location.search} />
            {elsewhere && (
              <div className="px-4 pb-4 sm:hidden">
                <Button size="sm" onClick={() => update({ property: "all" })}>
                  {t("res.list.search_all")}
                </Button>
              </div>
            )}
            <div className="hidden sm:block">
            <DataTable<ReservationRow>
              caption={t("res.list.caption")}
              rows={rows}
              loading={list.loading}
              rowKey={(r) => r.name}
              onRowClick={(r) => open(r.name)}
              empty={
                <EmptyState
                  title={pending ? t("res.list.no_changes") : filtered ? t("res.list.none_filtered") : t("res.list.none")}
                  description={elsewhere ? t("res.list.none_here", { hotel: hotelName(hotels, property) }) : filtered ? t("res.list.none_hint") : undefined}
                  action={
                    elsewhere ? (
                      <Button size="sm" onClick={() => update({ property: "all" })}>
                        {t("res.list.search_all")}
                      </Button>
                    ) : undefined
                  }
                />
              }
              columns={[
                {
                  key: "name",
                  header: t("res.col.reservation"),
                  sortValue: (r) => r.name,
                  cell: (r) => (
                    <span className="block whitespace-nowrap">
                      <span className="font-medium text-zinc-900">{r.name}</span>
                      {r.tex_booking && <span className="block text-xs text-zinc-500">{r.tex_booking}</span>}
                      {r.channel_ref && (
                        <span className="block text-xs text-zinc-600" title={t("res.list.channel_ref")}>
                          {t("res.list.channel_ref_short", { ref: r.channel_ref })}
                        </span>
                      )}
                    </span>
                  ),
                },
                {
                  key: "guest",
                  header: t("res.col.guest"),
                  sortValue: (r) => r.guest_name ?? "",
                  cell: (r) => (
                    <span className="block min-w-0">
                      <span className="block max-w-[14rem] truncate">{r.guest_name || "—"}</span>
                      <span className="block max-w-[14rem] truncate text-xs text-zinc-500">
                        {hotelName(hotels, r.property)}
                        {r.tex_sales_channel ? ` · ${L.channel(r.tex_sales_channel)}` : ""}
                      </span>
                    </span>
                  ),
                },
                {
                  key: "stay",
                  header: t("res.col.stay"),
                  sortValue: (r) => r.check_in_date,
                  cell: (r) => (
                    <span className="block whitespace-nowrap">
                      {date(r.check_in_date, "short")} – {date(r.check_out_date, "short")}
                      <span className="block text-xs text-zinc-500">{t("core.label.nights", { count: r.nights })}</span>
                    </span>
                  ),
                },
                {
                  key: "room",
                  header: t("res.col.room"),
                  hideBelow: "lg",
                  cell: (r) => (
                    <span className="block max-w-[12rem]">
                      <span className="block truncate">{r.room_type_name || r.room_type}</span>
                      <span className="block truncate text-xs text-zinc-500">{L.board(r.tex_board)}</span>
                    </span>
                  ),
                },
                {
                  key: "pax",
                  header: t("res.col.pax"),
                  hideBelow: "lg",
                  align: "right",
                  cell: (r) => `${num(r.adults)} + ${num(r.children)}`,
                },
                {
                  key: "status",
                  header: t("core.label.status"),
                  sortValue: (r) => r.status,
                  cell: (r) => (
                    <span className="flex flex-wrap gap-1">
                      <Badge tone={statusTone(r.status)}>{L.status(r.status)}</Badge>
                      {r.tex_guest_change_pending ? <Badge tone="warning">{t("res.badge.guest_change")}</Badge> : null}
                    </span>
                  ),
                },
                {
                  key: "total",
                  header: t("core.label.total"),
                  align: "right",
                  cell: (r) => (can("price.view", r.property) ? <Money amount={r.total} currency={r.tex_currency} /> : "—"),
                },
              ]}
            />
            </div>
            {(page > 0 || hasNext) && (
              <nav aria-label={t("res.list.paging")} className="flex items-center justify-between gap-3 border-t border-zinc-100 px-4 py-3 text-sm">
                <span className="text-zinc-600">{t("res.list.showing", { from: page * PAGE + 1, to: page * PAGE + (rows?.length ?? 0) })}</span>
                <span className="flex gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<ChevronLeft className="size-4" aria-hidden />}
                    disabled={page === 0 || list.loading}
                    onClick={() => update({ page: page > 1 ? String(page - 1) : null }, true)}
                  >
                    {t("res.list.prev")}
                  </Button>
                  <Button variant="secondary" size="sm" disabled={!hasNext || list.loading} onClick={() => update({ page: String(page + 1) }, true)}>
                    {t("res.list.next")}
                    <ChevronRight className="size-4" aria-hidden />
                  </Button>
                </span>
              </nav>
            )}
          </>
        )}
      </Card>
    </>
  )
}

function MobileList({
  rows,
  loading,
  hotels,
  canPrice,
  empty,
  back,
}: {
  rows: ReservationRow[] | undefined
  loading: boolean
  hotels: { name: string; property_name: string }[]
  canPrice: (property: string) => boolean
  empty: string
  back: string
}) {
  const { t } = useTexT()
  const L = useLabels()
  if (loading && !rows)
    return (
      <div className="space-y-2 p-3 sm:hidden" aria-busy="true">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-20 w-full" />
        ))}
      </div>
    )
  if (!rows?.length) return <div className="sm:hidden">{!loading && <EmptyState title={empty} />}</div>
  return (
    <ul className="divide-y divide-zinc-100 sm:hidden" aria-label={t("res.list.caption")}>
      {rows.map((r) => (
        <li key={r.name}>
          <Link to={`/tex/reservations/${encodeURIComponent(r.name)}`} state={{ back }} className="block px-4 py-3 hover:bg-zinc-50 focus-visible:bg-tex-50">
            <span className="flex items-start justify-between gap-2">
              <span className="min-w-0">
                <span className="block font-medium text-zinc-900">{r.guest_name || "—"}</span>
                <span className="block text-xs text-zinc-500">
                  {r.name} · {hotelName(hotels, r.property)}
                  {r.channel_ref ? ` · ${r.channel_ref}` : ""}
                </span>
              </span>
              <span className="shrink-0 text-right">
                {canPrice(r.property) && <Money amount={r.total} currency={r.tex_currency} className="block text-sm font-medium" />}
              </span>
            </span>
            <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-zinc-600">
              <span>
                {date(r.check_in_date, "short")} – {date(r.check_out_date, "short")} · {t("core.label.nights", { count: r.nights })}
              </span>
              <Badge tone={statusTone(r.status)}>{L.status(r.status)}</Badge>
              {r.tex_guest_change_pending ? <Badge tone="warning">{t("res.badge.guest_change")}</Badge> : null}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  )
}

function hotelName(hotels: { name: string; property_name: string }[], name: string) {
  return hotels.find((h) => h.name === name)?.property_name ?? name
}
