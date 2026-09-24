import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { ChevronDown, ChevronRight, Filter } from "lucide-react"
import { tex, TexApiError } from "../../lib/api"
import { useSession } from "../../lib/session"
import { dateTime } from "../../lib/format"
import { useTexT } from "../../i18n"
import { Badge, Button, Card, DescriptionList, EmptyState, ErrorState, Field, Input, Select, Skeleton } from "../../ui"
import { cn } from "../../../lib/utils"
import { SettingsFrame } from "./SettingsFrame"
import { CollectionChanges, splitCollections } from "./components/CollectionDiff"
import { JsonDiff } from "./components/JsonDiff"

interface AuditRow {
  name: string
  event_time: string
  action: string
  actor: string | null
  actor_roles: string | null
  source: string | null
  property: string | null
  /** an event of a hotel group or an enterprise (ADR-053): the hotels it reached that the
   * viewer may see, and how many others */
  hotel_group?: string | null
  enterprise?: string | null
  hotels?: string[]
  other_hotels?: number
  reference_doctype: string | null
  reference_name: string | null
  reason: string | null
  old_value: unknown
  new_value: unknown
}

interface Filters {
  property: string
  action: string
  actor: string
  from: string
  to: string
}

const PAGE = 50
const ACTION_HINTS = [
  "booking.",
  "reservation.",
  "contract.",
  "contract.version.save",
  "grid.bulk_update",
  "payment.",
  "payment_account.",
  "payment_rule.",
  "payment_policy.",
  "payment_link.",
  "refund.",
  "profile.save",
  "settings.save",
  "grant.",
  "user.invite",
  "outbox.retry",
  "booking_site.",
  "tex_booking_site.save",
  "tex_integration_connection.save",
  "fx.",
]

export default function AuditTrail() {
  const { t } = useTexT()
  const { boot, property } = useSession()
  const platform = boot.user.platform_admin
  const hotels = boot.properties.filter((p) => platform || p.capabilities.includes("settings.admin"))
  const defaultHotel = hotels.some((h) => h.name === property?.name) ? property!.name : (hotels[0]?.name ?? "")
  const empty: Filters = { property: platform ? "" : defaultHotel, action: "", actor: "", from: "", to: "" }
  const [draft, setDraft] = useState<Filters>(empty)
  const [applied, setApplied] = useState<Filters>(empty)
  const [rows, setRows] = useState<AuditRow[]>()
  const [error, setError] = useState<TexApiError>()
  const [loading, setLoading] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [open, setOpen] = useState<Set<string>>(new Set())
  const seq = useRef(0)

  const dateErr =
    (draft.from && !draft.to) || (!draft.from && draft.to)
      ? t("settings.audit.err.both_dates")
      : draft.from && draft.to && draft.to < draft.from
        ? t("settings.audit.err.order")
        : null

  const load = useCallback(
    async (start: number) => {
      const my = ++seq.current
      setLoading(true)
      setError(undefined)
      try {
        const args: Record<string, unknown> = { start, limit: PAGE }
        if (applied.property) args.property = applied.property
        if (applied.action.trim()) args.action = applied.action.trim()
        if (applied.actor.trim()) args.actor = applied.actor.trim()
        if (applied.from && applied.to) {
          args.date_from = applied.from
          args.date_to = applied.to
        }
        const page = await tex<AuditRow[]>("admin", "audit_log", args)
        if (my !== seq.current) return
        setRows((prev) => (start === 0 ? page : [...(prev ?? []), ...page]))
        setHasMore(page.length === PAGE)
      } catch (e) {
        if (my !== seq.current) return
        setError(e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error"))
      } finally {
        if (my === seq.current) setLoading(false)
      }
    },
    [applied],
  )

  useEffect(() => {
    setOpen(new Set())
    void load(0)
  }, [load])

  const hotelName = useMemo(() => new Map(boot.properties.map((p) => [p.name, p.property_name])), [boot.properties])
  const hotelsOf = (r: AuditRow) => {
    if (r.property) return hotelName.get(r.property) ?? r.property
    const names = (r.hotels ?? []).map((h) => hotelName.get(h) ?? h)
    const others = r.other_hotels ? t("settings.audit.other_hotels", { count: r.other_hotels }) : ""
    return [names.join(", "), others].filter(Boolean).join(" ") || "—"
  }
  const sourceLabel = (source: string) => {
    const key = `settings.audit.source_label.${source.toLowerCase().replace(/\s+/g, "_")}`
    const label = t(key)
    return label === key ? source : label
  }
  const toggle = (name: string) => {
    const next = new Set(open)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    setOpen(next)
  }

  return (
    <SettingsFrame subtitle={t("settings.audit.subtitle")}>
      <Card className="mb-4">
        <form
          className="flex flex-wrap items-end gap-3 p-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (!dateErr) setApplied({ ...draft })
          }}
        >
          <Field label={t("settings.audit.hotel")} className="w-full sm:w-60">
            <Select
              value={draft.property}
              onChange={(e) => setDraft({ ...draft, property: e.target.value })}
              options={[
                ...(platform ? [{ value: "", label: t("settings.audit.all_hotels") }] : []),
                ...hotels.map((h) => ({ value: h.name, label: h.property_name })),
              ]}
            />
          </Field>
          <Field label={t("settings.audit.action")} className="w-full sm:w-48">
            <Input list="tex-audit-actions" placeholder={t("settings.audit.action_placeholder")} value={draft.action} onChange={(e) => setDraft({ ...draft, action: e.target.value })} autoComplete="off" />
          </Field>
          <datalist id="tex-audit-actions">
            {ACTION_HINTS.map((a) => (
              <option key={a} value={a} />
            ))}
          </datalist>
          <Field label={t("settings.audit.actor")} className="w-full sm:w-52">
            <Input type="email" placeholder="name@hotel.com" value={draft.actor} onChange={(e) => setDraft({ ...draft, actor: e.target.value })} autoComplete="off" />
          </Field>
          <Field label={t("core.label.from")} className="w-[calc(50%-0.375rem)] sm:w-40" error={dateErr}>
            <Input type="date" value={draft.from} onChange={(e) => setDraft({ ...draft, from: e.target.value })} />
          </Field>
          <Field label={t("core.label.to")} className="w-[calc(50%-0.375rem)] sm:w-40">
            <Input type="date" value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />
          </Field>
          <div className="flex gap-2 pb-0.5">
            <Button type="submit" icon={<Filter className="size-4" aria-hidden />} disabled={!!dateErr}>
              {t("core.action.apply")}
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setDraft(empty)
                setApplied(empty)
              }}
            >
              {t("core.action.reset")}
            </Button>
          </div>
          <p className="w-full text-xs text-zinc-500">{t("settings.audit.filter_help")}</p>
        </form>
      </Card>

      {error ? (
        <Card>
          <ErrorState error={error} onRetry={() => load(0)} />
        </Card>
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="min-w-full border-separate border-spacing-0 text-sm">
              <caption className="sr-only">{t("settings.audit.caption")}</caption>
              <thead>
                <tr className="text-left text-xs font-semibold tracking-wide text-zinc-600 uppercase">
                  <th scope="col" className="w-10 border-b border-zinc-200 bg-zinc-50 px-2 py-2">
                    <span className="sr-only">{t("settings.audit.details")}</span>
                  </th>
                  <th scope="col" className="border-b border-zinc-200 bg-zinc-50 px-3 py-2">
                    {t("settings.audit.time")}
                  </th>
                  <th scope="col" className="border-b border-zinc-200 bg-zinc-50 px-3 py-2">
                    {t("settings.audit.action")}
                  </th>
                  <th scope="col" className="hidden border-b border-zinc-200 bg-zinc-50 px-3 py-2 sm:table-cell">
                    {t("settings.audit.actor")}
                  </th>
                  <th scope="col" className="hidden border-b border-zinc-200 bg-zinc-50 px-3 py-2 md:table-cell">
                    {t("settings.audit.hotel")}
                  </th>
                  <th scope="col" className="hidden border-b border-zinc-200 bg-zinc-50 px-3 py-2 lg:table-cell">
                    {t("settings.audit.reference")}
                  </th>
                  <th scope="col" className="hidden border-b border-zinc-200 bg-zinc-50 px-3 py-2 xl:table-cell">
                    {t("settings.audit.reason")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {!rows && loading
                  ? Array.from({ length: 6 }).map((_, i) => (
                      <tr key={i}>
                        <td colSpan={7} className="border-b border-zinc-100 px-3 py-2.5">
                          <Skeleton className="h-4 w-full" />
                        </td>
                      </tr>
                    ))
                  : rows?.map((r) => {
                      const isOpen = open.has(r.name)
                      const detailId = `audit-${r.name}`
                      return (
                        <Fragment key={r.name}>
                          <tr className={cn("align-top", isOpen && "bg-tex-50/40")}>
                            <td className="border-b border-zinc-100 px-2 py-1.5">
                              <Button
                                variant="ghost"
                                size="sm"
                                className="px-1.5"
                                aria-expanded={isOpen}
                                aria-controls={detailId}
                                aria-label={`${t("settings.audit.details")}: ${r.action} · ${dateTime(r.event_time)}`}
                                onClick={() => toggle(r.name)}
                                icon={isOpen ? <ChevronDown className="size-4" aria-hidden /> : <ChevronRight className="size-4" aria-hidden />}
                              />
                            </td>
                            <td className="border-b border-zinc-100 px-3 py-2 text-zinc-700 tabular-nums sm:whitespace-nowrap">{dateTime(r.event_time)}</td>
                            <td className="border-b border-zinc-100 px-3 py-2">
                              <span className="font-mono text-xs font-medium [overflow-wrap:anywhere] text-zinc-900 sm:whitespace-nowrap">{r.action}</span>
                              <span className="block text-xs text-zinc-500 sm:hidden">{r.actor ?? "—"}</span>
                            </td>
                            <td className="hidden border-b border-zinc-100 px-3 py-2 whitespace-nowrap text-zinc-700 sm:table-cell">{r.actor ?? "—"}</td>
                            <td className="hidden border-b border-zinc-100 px-3 py-2 text-zinc-700 md:table-cell">
                              {hotelsOf(r)}
                              {!r.property && (r.hotel_group || r.enterprise) && (
                                <span className="block text-xs text-zinc-500">{r.hotel_group || r.enterprise}</span>
                              )}
                            </td>
                            <td className="hidden border-b border-zinc-100 px-3 py-2 text-zinc-700 lg:table-cell">
                              {r.reference_name ? (
                                <>
                                  <span className="block text-xs text-zinc-500">{r.reference_doctype}</span>
                                  <span className="font-mono text-xs">{r.reference_name}</span>
                                </>
                              ) : (
                                "—"
                              )}
                            </td>
                            <td className="hidden max-w-xs border-b border-zinc-100 px-3 py-2 text-zinc-700 xl:table-cell">
                              <span className="line-clamp-2">{r.reason || "—"}</span>
                            </td>
                          </tr>
                          {isOpen && (
                            <tr id={detailId}>
                              <td colSpan={7} className="border-b border-zinc-200 bg-zinc-50/60 px-4 py-3">
                                <div className="space-y-4">
                                  <DescriptionList
                                    cols={3}
                                    items={[
                                      { label: t("settings.audit.actor"), value: r.actor },
                                      { label: t("settings.audit.source"), value: r.source ? <Badge tone="neutral">{sourceLabel(r.source)}</Badge> : "—" },
                                      { label: r.property ? t("settings.audit.hotel") : t("settings.audit.scope_hotels"), value: hotelsOf(r) },
                                      ...(r.hotel_group ? [{ label: t("settings.audit.hotel_group"), value: r.hotel_group }] : []),
                                      ...(r.enterprise ? [{ label: t("settings.audit.enterprise"), value: r.enterprise }] : []),
                                      {
                                        label: t("settings.audit.reference"),
                                        value: r.reference_name ? `${r.reference_doctype} · ${r.reference_name}` : "—",
                                      },
                                      { label: t("settings.audit.reason"), value: r.reason || "—" },
                                      { label: t("settings.audit.event_id"), value: <span className="font-mono text-xs">{r.name}</span> },
                                    ]}
                                  />
                                  {r.actor_roles && (
                                    <details className="text-xs text-zinc-600">
                                      <summary className="cursor-pointer font-medium text-zinc-700">{t("settings.audit.actor_roles")}</summary>
                                      <p className="mt-1 break-words">{r.actor_roles}</p>
                                    </details>
                                  )}
                                  <div className="space-y-3">
                                    <p className="text-xs font-semibold tracking-wide text-zinc-600 uppercase">{t("settings.audit.changes")}</p>
                                    <AuditChanges row={r} />
                                  </div>
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      )
                    })}
              </tbody>
            </table>
          </div>
          {rows && rows.length === 0 && !loading && <EmptyState title={t("settings.audit.empty")} description={t("settings.audit.empty_hint")} />}
          {rows && rows.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-zinc-100 px-4 py-2.5 text-xs text-zinc-500">
              <span aria-live="polite">{t("settings.audit.shown", { count: rows.length })}</span>
              {hasMore && (
                <Button variant="secondary" size="sm" loading={loading} onClick={() => load(rows.length)}>
                  {t("settings.audit.more")}
                </Button>
              )}
            </div>
          )}
        </Card>
      )}
    </SettingsFrame>
  )
}

/** Old / new values, with the collections of an event (contract tables, payload sections,
 * ARI cells, ADR-053) shown row by row instead of as raw JSON. */
function AuditChanges({ row }: { row: AuditRow }) {
  const { rest, collections } = useMemo(() => splitCollections(row.new_value), [row.new_value])
  return (
    <>
      {(!collections || row.old_value != null || rest != null) && <JsonDiff before={row.old_value} after={rest} />}
      {collections && <CollectionChanges collections={collections} />}
    </>
  )
}
