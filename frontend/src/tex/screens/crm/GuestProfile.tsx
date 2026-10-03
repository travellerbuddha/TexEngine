import { useState } from "react"
import { Link, useParams } from "react-router-dom"
import { Crown, GitMerge, Lock, MessageSquarePlus, Pencil, ShieldAlert, Users } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { useProperty, useSession } from "../../lib/session"
import { date, money, nightsBetween, num } from "../../lib/format"
import { useTexT } from "../../i18n"
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  DataTable,
  EmptyState,
  ErrorState,
  Money,
  PageHeader,
  Skeleton,
  Stat,
  TabPanel,
  Tabs,
  statusTone,
} from "../../ui"
import { CrmNav } from "./components/common"
import { useEvent } from "./lib"
import { segmentLabel } from "./segments/meta"
import { CommunicationsTimeline, LogCommunicationDialog } from "./profile/Communications"
import { ConsentPanel } from "./profile/ConsentPanel"
import { ContactCard } from "./profile/ContactCard"
import { DuplicatesCard, MergeDialog } from "./profile/Duplicates"
import { EditGuestDrawer } from "./profile/EditGuestDrawer"
import { ExtrasPanel } from "./profile/Extras"
import { LoyaltyPanel } from "./profile/Loyalty"
import type { GuestProfile as Profile, Stay } from "./types"

function roomLabel(s: Stay) {
  const rt = s.room_type ?? ""
  return rt.startsWith(`${s.property}-`) ? rt.slice(s.property.length + 1) : rt || "—"
}

export default function GuestProfile() {
  const { name = "" } = useParams()
  const { t } = useTexT()
  const { can } = useSession()
  const property = useProperty()
  const q = useTexQuery<Profile>("crm", "guest", { name }, [name])
  const [tab, setTab] = useState("stays")
  const [editing, setEditing] = useState(false)
  const [logging, setLogging] = useState(false)
  // the duplicate being merged into this profile ("": typed in the dialog; null: closed)
  const [merging, setMerging] = useState<string | null>(null)
  const closeEdit = useEvent(() => setEditing(false))
  const closeLog = useEvent(() => setLogging(false))
  const closeMerge = useEvent(() => setMerging(null))
  const d = q.data
  const g = d?.guest
  const canEdit = Boolean(d?.hotels.some((h) => can("crm.edit", h)))
  // a hold that ran out of time is no cancellation (O-24, LO-24)
  const stayBadge = (s: Stay) =>
    s.hold_expired ? (
      <Badge tone="neutral">{t("crm.stay.hold_expired")}</Badge>
    ) : (
      <Badge tone={statusTone(s.status)}>{t(`crm.stay.status.${s.status.toLowerCase().replace(/\s+/g, "_")}`)}</Badge>
    )

  const crumbs = [
    { label: t("core.nav.crm"), to: "/tex/crm" },
    { label: t("crm.nav.guests"), to: "/tex/crm" },
    { label: g?.full_name || name },
  ]

  if (q.error)
    return (
      <>
        <PageHeader title={t("crm.profile.title")} crumbs={crumbs} />
        <CrmNav />
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      </>
    )

  const activeStays = d?.stays.filter((s) => s.status !== "Cancelled" && s.status !== "No Show").length ?? 0
  const loyaltyAvailable = d?.loyalty.reduce((s, a) => s + a.available, 0) ?? 0
  const cxl = d?.cancellations
  // fees per currency, never added up across currencies
  const cxlFees = cxl?.fees.length ? cxl.fees.map((f) => money(f.amount, f.currency)).join(" · ") : null

  return (
    <>
      <PageHeader
        title={g ? g.full_name || g.name : <Skeleton className="h-7 w-56" />}
        subtitle={g ? [g.name, g.tex_enterprise].filter(Boolean).join(" · ") : undefined}
        crumbs={crumbs}
        meta={
          g && (
            <>
              {g.vip ? (
                <Badge tone="brand">
                  <Crown className="size-3" aria-hidden />
                  {t("crm.vip")}
                </Badge>
              ) : null}
              {g.blacklisted ? (
                <Badge tone="danger">
                  <ShieldAlert className="size-3" aria-hidden />
                  {t("crm.blacklisted")}
                </Badge>
              ) : null}
              {d?.loyalty.map((a) => (a.tier ? <Badge key={a.program} tone="info">{t("crm.loyalty.tier", { tier: a.tier })}</Badge> : null))}
              {d && d.hotels.length > 0 && (
                <span className="text-xs text-zinc-500">{t("crm.profile.visible_via", { hotels: d.hotels.join(", ") })}</span>
              )}
            </>
          )
        }
        actions={
          canEdit && g ? (
            <>
              <Button variant="secondary" icon={<MessageSquarePlus className="size-4" aria-hidden />} onClick={() => setLogging(true)}>
                {t("crm.comm.log")}
              </Button>
              <Button variant="secondary" icon={<GitMerge className="size-4" aria-hidden />} onClick={() => setMerging("")}>
                {t("crm.merge.action")}
              </Button>
              <Button icon={<Pencil className="size-4" aria-hidden />} onClick={() => setEditing(true)}>
                {t("crm.profile.edit")}
              </Button>
            </>
          ) : undefined
        }
      />
      <CrmNav />
      {!d || !g ? (
        <div className="grid gap-5 lg:grid-cols-3">
          <Card className="p-4 lg:col-span-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="mt-4 h-24 w-full" />
          </Card>
          <Card className="p-4">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="mt-4 h-24 w-full" />
          </Card>
        </div>
      ) : (
        <div className="space-y-5">
          <section aria-label={t("crm.profile.kpis")} className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <Stat label={t("crm.col.stays")} value={num(g.tex_stays ?? 0)} hint={t("crm.profile.stays_hint", { count: activeStays })} />
            <Stat label={t("crm.col.ltv")} value={g.tex_lifetime_currency ? money(g.tex_lifetime_value, g.tex_lifetime_currency) : "—"} hint={t("crm.profile.ltv_hint")} />
            <Stat label={t("crm.col.last_stay")} value={date(g.tex_last_stay)} />
            <Stat label={t("crm.loyalty.available")} value={num(loyaltyAvailable)} hint={t("crm.profile.points_hint")} />
            <Stat
              label={t("crm.profile.cancellations")}
              value={num(cxl?.count ?? 0)}
              hint={[
                cxlFees ? t("crm.profile.cancel_fees", { amount: cxlFees }) : t("crm.profile.no_cancel_fees"),
                cxl?.no_shows ? t("crm.profile.no_shows", { count: cxl.no_shows }) : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            />
          </section>

          <div className="grid items-start gap-5 lg:grid-cols-3">
            <div className="min-w-0 space-y-5 lg:col-span-2">
              <ContactCard guest={g} />
              <Card>
                <Tabs
                  label={t("crm.profile.sections")}
                  value={tab}
                  onChange={setTab}
                  className="px-2"
                  tabs={[
                    { id: "stays", label: t("crm.profile.tab.stays"), badge: <Badge>{d.stays.length}</Badge> },
                    { id: "extras", label: t("crm.profile.tab.extras"), badge: <Badge>{d.extras.length}</Badge> },
                    { id: "comms", label: t("crm.profile.tab.comms"), badge: <Badge>{d.communications.length}</Badge> },
                    { id: "loyalty", label: t("crm.profile.tab.loyalty") },
                  ]}
                />
                {tab === "stays" && (
                  <TabPanel id="stays">
                    <DataTable<Stay>
                      caption={t("crm.profile.stays_caption")}
                      rows={d.stays}
                      rowKey={(s) => s.name}
                      empty={<EmptyState title={t("crm.profile.no_stays")} description={t("crm.profile.no_stays_hint")} />}
                      columns={[
                        {
                          key: "res",
                          header: t("crm.stay.reservation"),
                          cell: (s) => (
                            <div className="min-w-0">
                              <Link to={`/tex/reservations/${encodeURIComponent(s.name)}`} className="font-medium whitespace-nowrap text-tex-700 hover:underline">
                                {s.name}
                              </Link>
                              <p className="text-xs text-zinc-500">{s.property}</p>
                              <p className="text-xs text-zinc-500">{[s.tex_sales_channel, s.tex_market].filter(Boolean).join(" · ")}</p>
                              <p className="text-xs whitespace-nowrap text-zinc-700 sm:hidden">
                                {date(s.check_in_date, "short")} → {date(s.check_out_date, "short")}
                              </p>
                              <span className="mt-1 inline-block sm:hidden">
                                {stayBadge(s)}
                              </span>
                            </div>
                          ),
                        },
                        {
                          key: "dates",
                          header: t("crm.stay.dates"),
                          hideBelow: "sm",
                          sortValue: (s) => s.check_in_date,
                          cell: (s) => (
                            <div className="text-xs whitespace-nowrap">
                              <p>
                                {date(s.check_in_date, "short")} → {date(s.check_out_date, "short")}
                              </p>
                              <p className="text-zinc-500">{t("core.label.nights", { count: nightsBetween(s.check_in_date, s.check_out_date) })}</p>
                            </div>
                          ),
                        },
                        {
                          key: "room",
                          header: t("crm.stay.room"),
                          hideBelow: "md",
                          cell: (s) => (
                            <div className="text-xs">
                              <p className="text-sm">{`${roomLabel(s)}${s.tex_board ? ` · ${s.tex_board}` : ""}`}</p>
                              <p className="inline-flex items-center gap-1 whitespace-nowrap text-zinc-500">
                                <Users className="size-3" aria-hidden />
                                {t("crm.stay.pax", { adults: s.adults ?? 0, children: s.children ?? 0 })}
                              </p>
                            </div>
                          ),
                        },
                        {
                          key: "status",
                          header: t("core.label.status"),
                          hideBelow: "sm",
                          cell: (s) => (
                            <div className="text-xs">
                              {stayBadge(s)}
                              {s.cancellation_fee && <p className="mt-1 whitespace-nowrap text-zinc-600">{t("crm.stay.fee", { amount: money(s.cancellation_fee, s.tex_currency) })}</p>}
                            </div>
                          ),
                        },
                        { key: "total", header: t("core.label.total"), align: "right", cell: (s) => <Money amount={s.tex_total_amount} currency={s.tex_currency} /> },
                      ]}
                    />
                  </TabPanel>
                )}
                {tab === "extras" && (
                  <TabPanel id="extras" className="p-4">
                    <ExtrasPanel lines={d.extras} summary={d.extras_summary} />
                  </TabPanel>
                )}
                {tab === "comms" && (
                  <TabPanel id="comms" className="p-4">
                    <CommunicationsTimeline items={d.communications} />
                  </TabPanel>
                )}
                {tab === "loyalty" && (
                  <TabPanel id="loyalty" className="p-4">
                    <LoyaltyPanel guest={g} accounts={d.loyalty} stays={d.stays} hotels={d.hotels} canEdit={canEdit} onChanged={q.reload} />
                  </TabPanel>
                )}
              </Card>
            </div>

            <div className="min-w-0 space-y-5">
              <DuplicatesCard duplicates={d.possible_duplicates ?? []} canEdit={canEdit} onMerge={setMerging} />
              <ConsentPanel guest={g} history={d.consent_history} canEdit={canEdit} onSaved={q.reload} />
              <Card>
                <CardHeader title={t("crm.profile.segments")} description={t("crm.profile.segments_hint")} />
                <CardBody>
                  {d.segments.length ? (
                    <ul className="flex flex-wrap gap-1.5">
                      {d.segments.map((s) => (
                        <li key={s.name}>
                          <Link
                            to={`/tex/crm/segments?s=${encodeURIComponent(s.name)}`}
                            className="inline-flex items-center gap-1 rounded-full border border-tex-200 bg-tex-50 px-2 py-0.5 text-xs font-medium text-tex-800 hover:bg-tex-100 focus-visible:ring-2 focus-visible:ring-tex-500/40 focus-visible:outline-none"
                          >
                            {s.system_key && (
                              <>
                                <Lock className="size-3" aria-hidden />
                                <span className="sr-only">{t("crm.seg.preset")}:</span>
                              </>
                            )}
                            {segmentLabel(t, s)}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-zinc-500">{t("crm.profile.no_segments")}</p>
                  )}
                  <Link to="/tex/crm/segments" className="mt-3 inline-block text-sm font-medium text-tex-700 hover:underline">
                    {t("crm.profile.manage_segments")}
                  </Link>
                </CardBody>
              </Card>
            </div>
          </div>
          {/* one per opening: it starts from the guest as saved, never from the last edit's form for a frame (2Z) */}
          {editing && <EditGuestDrawer key={g.name} guest={g} open onClose={closeEdit} onSaved={q.reload} />}
          <MergeDialog open={merging !== null} guest={g} source={merging ?? ""} onClose={closeMerge} onMerged={q.reload} />
          <LogCommunicationDialog
            open={logging}
            onClose={closeLog}
            guest={g}
            stays={d.stays}
            hotels={d.hotels}
            defaultHotel={property}
            onSaved={() => {
              setTab("comms")
              q.reload()
            }}
          />
        </div>
      )}
    </>
  )
}
