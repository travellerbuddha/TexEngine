import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { CalendarRange, OctagonX } from "lucide-react"
import { useTexQuery } from "../../../lib/api"
import { addDays, date as fmtDate } from "../../../lib/format"
import { useHotelScope } from "../../../lib/hotelScope"
import { useSession } from "../../../lib/session"
import { useSiteToday } from "../../../lib/siteDay"
import { useTexT } from "../../../i18n"
import { Badge, Button, Card, DataTable, EmptyState, ErrorState, Field, Input, Notice, PageHeader, Select, Toolbar } from "../../../ui"
import { DateRange } from "../components/common"
import { RatesNav } from "../components/RatesNav"
import { useLookups } from "../lib/util"
import type { RestrictionList, RestrictionRange } from "./types"

const CAPS = ["price.view"] as const
const MAX_DAYS = 366

type T = (key: string, params?: Record<string, string | number>) => string

function channelScopeLabel(t: T, value: string) {
  return t(`inventory.channel_scope.${value === "Booking Engine" ? "be" : value === "Call Center" ? "cc" : "both"}`)
}

/** Where a restriction applies, most specific parts only. */
function scopeText(t: T, r: RestrictionRange, channelName: (c: string) => string): string {
  const parts = [
    r.contract ? t("inventory.scope.contract", { c: r.contract_code ?? r.contract }) : null,
    r.market ? t("inventory.scope.market", { m: r.market }) : null,
    r.rate_plan ? t("inventory.scope.rate_plan", { r: r.rate_plan_name ?? r.rate_plan }) : null,
    r.sales_channel ? t("inventory.scope.channel", { c: channelName(r.sales_channel) }) : null,
    r.channel_scope ? t("inventory.scope.channel_scope", { c: channelScopeLabel(t, r.channel_scope) }) : null,
  ].filter(Boolean)
  return parts.length ? parts.join(" · ") : t("rates.lists.restrictions.everywhere")
}

/** The restriction's rules as short texts (each one text + tone, never colour alone). */
function rules(t: T, r: RestrictionRange): { text: string; tone: "danger" | "warning" | "info" | "neutral" | "success" }[] {
  const out: { text: string; tone: "danger" | "warning" | "info" | "neutral" | "success" }[] = []
  if (r.stop_sell === "STOP")
    out.push({ text: `${t("inventory.v.stop")}${r.stop_sell_mode ? ` · ${t(`inventory.mode.${r.stop_sell_mode}`)}` : ""}`, tone: "danger" })
  if (r.stop_sell === "OPEN") out.push({ text: t("inventory.v.open_override"), tone: "success" })
  if (r.min_los) out.push({ text: `${t("inventory.f.min_los")}: ${r.min_los}`, tone: "warning" })
  if (r.max_los) out.push({ text: `${t("inventory.f.max_los")}: ${r.max_los}`, tone: "warning" })
  if (r.cta) out.push({ text: r.cta === "Yes" ? t("inventory.f.cta") : `${t("inventory.f.cta")}: ${t("core.label.no")}`, tone: r.cta === "Yes" ? "warning" : "neutral" })
  if (r.ctd) out.push({ text: r.ctd === "Yes" ? t("inventory.f.ctd") : `${t("inventory.f.ctd")}: ${t("core.label.no")}`, tone: r.ctd === "Yes" ? "warning" : "neutral" })
  if (r.release_days) out.push({ text: `${t("inventory.f.release_days")}: ${r.release_days}`, tone: "info" })
  if (r.book_from) out.push({ text: t("inventory.window.from", { d: fmtDate(r.book_from) }), tone: "info" })
  if (r.book_to) out.push({ text: t("inventory.window.to", { d: fmtDate(r.book_to) }), tone: "info" })
  if (r.min_advance) out.push({ text: t("inventory.window.min_advance", { n: r.min_advance }), tone: "info" })
  if (r.max_advance) out.push({ text: t("inventory.window.max_advance", { n: r.max_advance }), tone: "info" })
  return out
}

/** Restrictions of a period across contracts, markets and channels (R-35 Restrictions, R-16,
 * G-64): consecutive days with the same rule read as one range. Edited in the rates &
 * availability grid, which each row opens on its first day. */
export default function Restrictions() {
  const { t } = useTexT()
  const navigate = useNavigate()
  const { boot, property, setProperty, can } = useSession()
  const hotels = useHotelScope(CAPS)
  const today = useSiteToday()
  const [from, setFrom] = useState<string | null>(null)
  const [to, setTo] = useState<string | null>(null)
  const [roomType, setRoomType] = useState("")
  useEffect(() => setRoomType(""), [property?.name])
  const a = from ?? today
  const b = to ?? addDays(a, 89)
  const span = (new Date(`${b}T12:00:00`).getTime() - new Date(`${a}T12:00:00`).getTime()) / 86_400_000
  const rangeError = b < a ? t("rates.lists.restrictions.range_order") : span >= MAX_DAYS ? t("rates.lists.restrictions.range_max") : null
  const lookups = useLookups(hotels.all ? undefined : property?.name)
  const room = hotels.all ? "" : roomType
  const list = useTexQuery<RestrictionList>(
    "lists",
    "restrictions",
    { property: hotels.property, date_from: a, date_to: b, room_type: room || undefined },
    [hotels.property, a, b, room],
    !rangeError,
  )
  const channelName = (c: string) => boot.channels.find((x) => x.name === c)?.channel_name ?? c
  const openGrid = (r: RestrictionRange) => {
    if (r.property !== property?.name) setProperty(r.property)
    navigate(`/tex/inventory?start=${r.date_from}`)
  }

  return (
    <>
      <RatesNav />
      <PageHeader
        title={t("core.nav.sub.restrictions")}
        subtitle={t("rates.lists.restrictions.subtitle")}
        crumbs={[{ label: t("core.nav.rates"), to: "/tex/rates" }, { label: t("core.nav.sub.restrictions") }]}
        actions={
          can("restriction.edit") && (
            <Button variant="secondary" icon={<CalendarRange className="size-4" aria-hidden />} onClick={() => navigate("/tex/inventory")}>
              {t("rates.lists.restrictions.edit_in_grid")}
            </Button>
          )
        }
      />
      <Toolbar>
        <Field label={t("core.label.from")} className="w-[calc(50%-0.375rem)] sm:w-40" error={rangeError ?? undefined}>
          <Input type="date" value={a} onChange={(e) => e.target.value && setFrom(e.target.value)} />
        </Field>
        <Field label={t("core.label.to")} className="w-[calc(50%-0.375rem)] sm:w-40">
          <Input type="date" value={b} min={a} onChange={(e) => e.target.value && setTo(e.target.value)} />
        </Field>
        {!hotels.all && (
          <Field label={t("rates.f.room_type")} className="w-full sm:w-52">
            <Select value={roomType} onChange={(e) => setRoomType(e.target.value)} options={(lookups.data?.room_types ?? []).map((r) => ({ value: r.name, label: r.room_type_name }))} placeholder={t("rates.common.all_rooms")} />
          </Field>
        )}
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
          <DataTable<RestrictionRange>
            caption={t("rates.lists.restrictions.caption", { from: fmtDate(a), to: fmtDate(b) })}
            rows={rangeError ? [] : list.data?.rows}
            loading={list.loading}
            rowKey={(r) => `${r.property}|${r.room_type}|${r.contract}|${r.market}|${r.rate_plan}|${r.sales_channel}|${r.channel_scope}|${r.date_from}`}
            onRowClick={openGrid}
            initialSort={{ key: "dates", dir: "asc" }}
            empty={<EmptyState icon={<OctagonX className="size-5" />} title={t("rates.lists.restrictions.none")} description={t("rates.lists.restrictions.none_hint")} />}
            columns={[
              {
                key: "dates",
                header: t("rates.lists.col.dates"),
                sortValue: (r) => r.date_from,
                cell: (r) => (
                  <span>
                    <DateRange from={r.date_from} to={r.date_to} />
                    <span className="block text-xs text-zinc-500">{t("inventory.n_days", { count: r.days })}</span>
                    <span className="block text-xs text-zinc-700 sm:hidden">{r.room_type_name ?? t("inventory.bulk.all_rooms")}</span>
                  </span>
                ),
              },
              {
                key: "room",
                header: t("rates.f.room_type"),
                hideBelow: "sm",
                sortValue: (r) => r.room_type_name ?? "",
                cell: (r) => (
                  <span>
                    {r.room_type_name ?? <span className="text-zinc-600">{t("inventory.bulk.all_rooms")}</span>}
                    {hotels.all && <span className="block text-xs text-zinc-500">{hotels.hotelName(r.property)}</span>}
                  </span>
                ),
              },
              {
                key: "rules",
                header: t("inventory.section.restrictions"),
                cell: (r) => (
                  <span className="flex flex-wrap gap-1">
                    {rules(t, r).map((x) => (
                      <Badge key={x.text} tone={x.tone}>
                        {x.text}
                      </Badge>
                    ))}
                  </span>
                ),
              },
              { key: "scope", header: t("inventory.scope.label"), hideBelow: "md", cell: (r) => <span className="text-zinc-700">{scopeText(t, r, channelName)}</span> },
              { key: "note", header: t("rates.f.note"), hideBelow: "lg", cell: (r) => <span className="line-clamp-2 max-w-48 text-zinc-600">{r.note || "—"}</span> },
            ]}
          />
        )}
      </Card>
      <p className="mt-2 text-xs text-zinc-600">{t("rates.lists.restrictions.open_hint")}</p>
    </>
  )
}
