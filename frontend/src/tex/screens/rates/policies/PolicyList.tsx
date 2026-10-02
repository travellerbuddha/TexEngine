import { useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { CopyPlus, Plus, Search, SlidersHorizontal } from "lucide-react"
import { useTexQuery } from "../../../lib/api"
import { useProperty, useSession } from "../../../lib/session"
import { date as fmtDate, dateTime } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, Card, Checkbox, DataTable, EmptyState, ErrorState, Field, IconButton, Input, PageHeader, Select, Toolbar, type Column, type Tone } from "../../../ui"
import { StatusBadge } from "../components/common"
import { RatesNav } from "../components/RatesNav"
import { enumLabel, opText } from "../lib/options"
import { decText, roomLabel, useLookups } from "../lib/util"
import { policyKind, type Doc, type ListCol } from "./config"
import { promoValueText } from "./PromotionPanels"
import { csv, promoState, type PromoState } from "./promotions"
import { useSiteClock, useSiteToday } from "../../../lib/siteDay"

const REV_STATUSES = ["Draft", "Active", "Superseded", "Archived"]
/** A promotion's state for a booking today, as text and tone (never colour alone). */
const PROMO_TONE: Record<PromoState, Tone> = { draft: "warning", scheduled: "info", live: "success", ended: "neutral", superseded: "neutral", archived: "neutral" }

/** List of one selling-policy DocType (markup, promotions, FX, …) for the selected hotel. */
export default function PolicyList() {
  const { kind: slug } = useParams()
  const kind = policyKind(slug)
  const { t } = useTexT()
  const navigate = useNavigate()
  const property = useProperty()
  const { can } = useSession()
  const lookups = useLookups(property)
  const today = useSiteToday()
  const clock = useSiteClock()
  const [q, setQ] = useState("")
  const [archived, setArchived] = useState(false)
  const [status, setStatus] = useState("")
  const list = useTexQuery<Doc[]>(
    "policies",
    "list_records",
    { doctype: kind?.doctype, property, include_archived: archived ? 1 : 0 },
    [kind?.doctype, property, archived],
    Boolean(kind && property),
  )

  const rows = useMemo(() => {
    let r = list.data
    if (!r) return r
    if (status) r = r.filter((x) => x.tex_status === status)
    const term = q.trim().toLowerCase()
    if (term) r = r.filter((x) => Object.values(x).some((v) => typeof v === "string" && v.toLowerCase().includes(term)))
    return r
  }, [list.data, q, status])

  if (!kind)
    return (
      <>
        <RatesNav />
        <Card>
          <EmptyState title={t("core.error.not_found")} />
        </Card>
      </>
    )

  const canEdit = can(kind.cap)
  const span = (a: unknown, b: unknown) =>
    !a && !b ? <span className="text-zinc-500">{t("rates.promo.sum.any_date")}</span> : <span className="whitespace-nowrap">{a ? fmtDate(String(a), "short") : "…"} – {b ? fmtDate(String(b), "short") : "…"}</span>
  const render = (c: ListCol, r: Doc) => {
    const v = r[c.key]
    switch (c.render) {
      case "promo_value":
        return <span className="font-medium whitespace-nowrap">{promoValueText(t, r)}</span>
      case "promo_cover": {
        const all = (k: string, label: string) => (csv(r[k]).length ? csv(r[k]).join(", ") : t(label))
        return (
          <span className="block max-w-56 text-xs leading-snug">
            <span className="block truncate">{all("markets", "rates.common.all_markets")}</span>
            <span className="block truncate text-zinc-500">
              {all("channels", "rates.common.all_channels")} · {csv(r.room_types).length ? csv(r.room_types).map((x) => roomLabel(lookups.data?.room_types, x)).join(", ") : t("rates.common.all_rooms")}
            </span>
          </span>
        )
      }
      case "promo_stay":
        return span(r.stay_from, r.stay_to)
      case "promo_sale":
        return span(r.sale_from, r.sale_to)
      case "promo_status": {
        const st = promoState(r, today, clock.now())
        return <Badge tone={PROMO_TONE[st]}>{t(`rates.promo.state.${st}`)}</Badge>
      }
      case "status":
        return <StatusBadge status={String(v || "")} group="rev_status" />
      case "rev":
        return <span className="tabular-nums">r{String(v ?? 1)}</span>
      case "enum":
        return enumLabel(t, c.group ?? "", String(v || ""))
      case "op":
        return <span className="font-medium tabular-nums">{opText(String(r.op || ""), String(r.value ?? ""))}</span>
      case "datetime":
        return v ? <span className="whitespace-nowrap">{dateTime(String(v))}</span> : "—"
      case "date":
        return v ? <span className="whitespace-nowrap">{fmtDate(String(v))}</span> : "—"
      case "check":
        return v ? <Badge tone="success">{t("core.label.yes")}</Badge> : <Badge tone="neutral">{t("core.label.no")}</Badge>
      case "pair":
        return <span className="font-medium">{`${r.from_currency ?? "?"} → ${r.to_currency ?? "?"}`}</span>
      case "decimal":
        return <span className="tabular-nums">{decText(v as string | number | null)}</span>
      case "code":
        return v ? <span className="font-mono text-xs font-semibold">{String(v)}</span> : "—"
      case "room":
        return roomLabel(lookups.data?.room_types, String(v || ""))
      case "contract": {
        const c2 = lookups.data?.contracts.find((x) => x.name === v)
        return c2 ? `${c2.contract_code} · ${c2.contract_name}` : String(v || "—")
      }
      default:
        return v === null || v === undefined || v === "" ? "—" : String(v)
    }
  }
  const columns: Column<Doc>[] = kind.list.map((c) => ({
    key: c.key,
    header: t(c.label),
    hideBelow: c.hideBelow,
    align: c.render === "decimal" || c.render === "rev" ? "right" : undefined,
    sortValue: (r: Doc) => {
      const v = r[c.key]
      return typeof v === "number" ? v : String(v ?? "")
    },
    cell: (r: Doc) => render(c, r),
  }))
  if (list.data?.some((r) => r.property && r.property !== property) || list.data?.some((r) => !r.property))
    columns.push({ key: "property", header: t("rates.f.hotel"), hideBelow: "lg", cell: (r) => (r.property ? String(r.property) : <Badge tone="info">{t("rates.common.global")}</Badge>) })
  if (canEdit)
    columns.push({
      key: "similar",
      header: <span className="sr-only">{t("rates.common.row_actions")}</span>,
      align: "right",
      cell: (r) => (
        <IconButton
          size="sm"
          label={t("rates.policy.similar_label", { name: String(r[typeof kind.titleField === "string" ? kind.titleField : "name"] ?? r.name) })}
          icon={<CopyPlus className="size-4" />}
          onClick={(e) => {
            e.stopPropagation()
            navigate(`/tex/rates/policies/${kind.slug}/new?copy=${encodeURIComponent(String(r.name))}`)
          }}
          onKeyDown={(e) => e.stopPropagation()}
        />
      ),
    })

  return (
    <>
      <RatesNav />
      <PageHeader
        title={t(kind.title)}
        subtitle={t(kind.intro)}
        actions={
          canEdit && (
            <Button icon={<Plus className="size-4" aria-hidden />} onClick={() => navigate(`/tex/rates/policies/${kind.slug}/new`)}>
              {t("rates.policy.new", { what: t(kind.singular) })}
            </Button>
          )
        }
      />
      <Toolbar>
        <Field label={t("core.action.search")} className="w-full sm:w-64">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-zinc-400" aria-hidden />
            <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} className="pl-8" />
          </div>
        </Field>
        {kind.revisioned && (
          <>
            <Field label={t("rates.f.status")} className="w-44">
              <Select value={status} onChange={(e) => setStatus(e.target.value)} options={REV_STATUSES.filter((s) => archived || s !== "Archived").map((s) => ({ value: s, label: t(`rates.rev_status.${s}`) }))} placeholder={t("core.label.all")} />
            </Field>
            <Checkbox className="h-9" label={t("rates.policy.show_archived")} checked={archived} onChange={(e) => setArchived(e.target.checked)} />
          </>
        )}
      </Toolbar>
      {kind.revisioned && <p className="-mt-2 mb-3 text-xs text-zinc-500">{t("rates.policy.revision_hint")}</p>}
      <Card>
        {list.error ? (
          <ErrorState error={list.error} onRetry={list.reload} />
        ) : (
          <DataTable<Doc>
            caption={t(kind.title)}
            rows={rows}
            loading={list.loading}
            rowKey={(r) => String(r.name)}
            onRowClick={(r) => navigate(`/tex/rates/policies/${kind.slug}/${encodeURIComponent(String(r.name))}`)}
            empty={
              <EmptyState
                icon={<SlidersHorizontal className="size-5" />}
                title={q || status ? t("rates.policy.none_filtered") : t("rates.policy.none", { what: t(kind.title) })}
                action={
                  canEdit && !q && !status ? (
                    <Button size="sm" onClick={() => navigate(`/tex/rates/policies/${kind.slug}/new`)}>
                      {t("rates.policy.new", { what: t(kind.singular) })}
                    </Button>
                  ) : undefined
                }
              />
            }
            columns={columns}
          />
        )}
      </Card>
    </>
  )
}
