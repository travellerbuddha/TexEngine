import { useState } from "react"
import { Link, useParams } from "react-router-dom"
import { Ban, Copy, History, Lock, MailCheck, PackagePlus, PencilLine, Star } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { date } from "../../lib/format"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  DescriptionList,
  ErrorState,
  IconButton,
  Money,
  Notice,
  PageHeader,
  Skeleton,
  statusTone,
  useToast,
} from "../../ui"
import { UI_CRS } from "../crs/lib/api"
import { useServerClock } from "../crs/lib/serverClock"
import { ExplanationList, PolicySummary } from "../crs/components/OfferParts"
import { usePartyText } from "../crs/components/PartyEditor"
import { PriceBreakdown } from "../crs/components/PriceBreakdown"
import { useLabels } from "../crs/lib/labels"
import { copyText, shortCode } from "../crs/lib/party"
import { AcknowledgeDialog, CancelDialog, CorrectImportDialog, ResendConfirmationDialog, SimulatorDialog } from "./components/ActionDialogs"
import { AddExtrasDialog } from "./components/AddExtrasDialog"
import { AddedExtrasCard } from "./components/AddonParts"
import { GuestChangesCard } from "./components/GuestChanges"
import { PaymentSummaryCard, RevisionTimeline } from "./components/DetailParts"
import { ModifyDrawer } from "./components/ModifyDrawer"
import { ADDON_STATUSES } from "./lib/addons"
import type { ReservationDetail as Detail, GuestChangeRequest } from "./lib/types"

const TERMINAL = ["Cancelled", "No Show", "Checked Out"]
type Dlg = "modify" | "simulate" | "cancel" | "ack" | "resend" | "addon" | "correct" | null

/** Reservation detail: stay, guest, locked price snapshot, revisions, payments (R-21–R-23, R-46). */
export default function ReservationDetail() {
  const { name = "" } = useParams()
  const { t } = useTexT()
  const q = useTexQuery<Detail>(UI_CRS, "reservation", { name }, [name])
  const [dialog, setDialog] = useState<Dlg>(null)
  const d = q.data

  if (q.error)
    return (
      <>
        <PageHeader title={name} crumbs={[{ label: t("core.nav.reservations"), to: "/tex/reservations" }, { label: name }]} />
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      </>
    )
  if (!d)
    return (
      <>
        <PageHeader title={name} crumbs={[{ label: t("core.nav.reservations"), to: "/tex/reservations" }, { label: name }]} />
        <div className="grid gap-5 lg:grid-cols-3" aria-busy="true">
          <Card className="space-y-3 p-4 lg:col-span-2">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-40 w-full" />
          </Card>
          <Card className="space-y-3 p-4">
            <Skeleton className="h-5 w-24" />
            <Skeleton className="h-20 w-full" />
          </Card>
        </div>
      </>
    )
  return <DetailView d={d} dialog={dialog} setDialog={setDialog} reload={q.reload} />
}

function DetailView({
  d,
  dialog,
  setDialog,
  reload,
}: {
  d: Detail
  dialog: Dlg
  setDialog: (v: Dlg) => void
  reload: () => void
}) {
  const { t } = useTexT()
  const { boot } = useSession()
  const L = useLabels()
  const toast = useToast()
  const partyText = usePartyText()
  const clock = useServerClock()
  const caps = new Set(d.capabilities)
  // the guest's own changes and their money (G-45): read again after anything on the page changed
  const [gcrTick, setGcrTick] = useState(0)
  const gcr = useTexQuery<GuestChangeRequest[]>("crs", "guest_change_requests", { reservation: d.name }, [d.name, d.revision_no, d.status, d.guest_change_pending, gcrTick], caps.has("reservation.view"))
  const guestChanges = gcr.data ?? []
  const decideFirst = guestChanges.some((r) => r.needs_staff)
  const guestChangesCard = guestChanges.length > 0 && (
    <GuestChangesCard
      rows={guestChanges}
      caps={caps}
      currency={d.currency}
      adults={d.adults}
      childAges={(d.child_ages ?? []).map((c) => c.age)}
      onResolved={() => {
        setGcrTick((n) => n + 1)
        reload()
      }}
    />
  )
  const terminal = TERMINAL.includes(d.status)
  const texPriced = Boolean(d.pricing?.request)
  const canModify = caps.has("reservation.modify") && !terminal && texPriced
  // extras added after booking (G-22): priced on their own, the stay stays price-locked
  const canAddExtras = caps.has("reservation.modify") && ADDON_STATUSES.includes(d.status) && texPriced
  const canCancel = caps.has("reservation.cancel") && !terminal
  const canSimulate = caps.has("price.view") && texPriced
  const canCost = caps.has("price.view_cost")
  // new manage link by e-mail: booking-level, not once everything is cancelled
  const canResend = Boolean(d.booking) && caps.has("reservation.modify") && d.status !== "Cancelled"
  // an imported stay is locked at the amount its file carried: corrected with price.override (ADR-052 review)
  const imported = d.pricing_source === "Imported"
  const canCorrect = imported && caps.has("price.override")
  const snap = d.pricing
  const childAges = (d.child_ages ?? []).map((c) => c.age)
  const ratePlanName = snap?.rate_plan?.name ?? (d.rate_plan ? shortCode(d.rate_plan, d.property) : null)
  const hash = snap?.contract?.payload_hash
  // extra code → name, for the revisions that added extras (they name codes only)
  const extraNames: Record<string, string> = {}
  for (const e of [...(snap?.extras ?? []), ...(snap?.addons ?? []).flatMap((a) => a.quote?.extras ?? [])]) if (e.name) extraNames[e.code] = e.name
  return (
    <>
      <PageHeader
        crumbs={[{ label: t("core.nav.reservations"), to: "/tex/reservations" }, { label: d.name }]}
        title={
          <span className="flex flex-wrap items-center gap-2">
            {d.name}
            {d.guest?.vip ? <Star className="size-5 fill-amber-600 text-amber-600" aria-label={t("crs.guest.vip")} /> : null}
          </span>
        }
        subtitle={[d.guest?.full_name, d.property].filter(Boolean).join(" · ")}
        meta={
          <>
            <Badge tone={statusTone(d.status)}>{L.status(d.status)}</Badge>
            {d.price_locked && (
              <Badge tone="neutral">
                <Lock className="size-3" aria-hidden />
                {t("res.detail.price_locked")}
              </Badge>
            )}
            {imported && (
              <Badge tone="info" title={t("res.imported.badge_hint")}>
                {t("res.imported.badge")}
              </Badge>
            )}
            {d.revision_no ? <Badge tone="neutral">{t("res.rev.n", { n: d.revision_no })}</Badge> : null}
            {d.booking && (
              <Link to={`/tex/reservations/booking/${encodeURIComponent(d.booking)}`} className="text-sm font-medium text-tex-700 hover:underline">
                {t("res.detail.booking", { ref: d.booking })}
              </Link>
            )}
          </>
        }
        actions={
          <>
            {canResend && (
              <Button variant="ghost" icon={<MailCheck className="size-4" aria-hidden />} onClick={() => setDialog("resend")}>
                {t("res.resend.button")}
              </Button>
            )}
            {canCorrect && (
              <Button variant="ghost" icon={<PencilLine className="size-4" aria-hidden />} onClick={() => setDialog("correct")}>
                {t("res.imported.button")}
              </Button>
            )}
            {canSimulate && (
              <Button variant="ghost" icon={<History className="size-4" aria-hidden />} onClick={() => setDialog("simulate")}>
                {t("res.sim.button")}
              </Button>
            )}
            {canCancel && (
              <Button variant="secondary" icon={<Ban className="size-4" aria-hidden />} onClick={() => setDialog("cancel")}>
                {t("res.cancel.button")}
              </Button>
            )}
            {canAddExtras && (
              <Button variant="secondary" icon={<PackagePlus className="size-4" aria-hidden />} onClick={() => setDialog("addon")}>
                {t("res.addon.button")}
              </Button>
            )}
            {canModify && (
              <Button icon={<PencilLine className="size-4" aria-hidden />} onClick={() => setDialog("modify")}>
                {t("res.mod.button")}
              </Button>
            )}
          </>
        }
      />

      {d.guest_change_pending && (
        <div className="mb-5">
          <Notice tone="warning" title={t("res.ack.banner_title")}>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <p className="whitespace-pre-line">{d.guest_change_note || t("res.ack.banner_body")}</p>
              {caps.has("reservation.modify") && (
                <Button size="sm" onClick={() => setDialog("ack")}>
                  {t("res.ack.button")}
                </Button>
              )}
            </div>
          </Notice>
        </div>
      )}
      {d.status === "Cancelled" && (
        <div className="mb-5">
          <Notice tone="danger" title={t("res.detail.cancelled")}>
            {d.cancellation_fee ? (
              <>
                {t("res.detail.cancel_fee")} <Money amount={d.cancellation_fee} currency={d.currency} className="font-semibold" />
              </>
            ) : (
              t("res.detail.no_fee")
            )}
          </Notice>
        </div>
      )}
      {!texPriced && (
        <div className="mb-5">
          <Notice tone="info">{t("res.detail.not_tex")}</Notice>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="min-w-0 space-y-5 lg:col-span-2">
          {decideFirst && guestChangesCard}
          <Card>
            <CardHeader title={t("res.detail.stay")} />
            <CardBody>
              <DescriptionList
                cols={3}
                items={[
                  { label: t("crs.search.check_in"), value: date(d.check_in, "long") },
                  { label: t("crs.search.check_out"), value: date(d.check_out, "long") },
                  { label: t("res.detail.nights"), value: t("core.label.nights", { count: d.nights }) },
                  { label: t("res.field.room_type"), value: d.room_type_name || d.room_type },
                  { label: t("res.field.board"), value: L.board(d.board) },
                  { label: t("res.field.rate_plan"), value: ratePlanName ?? "—" },
                  { label: t("res.cmp.party"), value: partyText(d.adults, childAges.length ? childAges : Array(d.children).fill(null)) },
                  { label: t("crs.search.market"), value: d.market ?? "—" },
                  { label: t("crs.search.channel"), value: L.channel(d.channel) },
                  { label: t("res.detail.sold_at"), value: clock.label(d.sale_at) },
                  { label: t("res.detail.room"), value: d.room ?? t("res.detail.unassigned") },
                  { label: t("crs.guest.requests"), value: d.special_requests || "—" },
                ]}
              />
            </CardBody>
          </Card>

          <Card role="region" aria-label={t("res.snap.title")}>
            <CardHeader
              title={t("res.snap.title")}
              description={snap?.accepted_at ? t("res.snap.accepted", { time: clock.label(snap.accepted_at) }) : undefined}
              actions={
                // the stored (locked) total; <data> carries the raw decimal for tools and tests
                <data value={d.total}>
                  <Money amount={d.total} currency={d.currency} className="text-lg font-semibold text-zinc-950" />
                </data>
              }
            />
            <CardBody className="space-y-4">
              {texPriced ? (
                <>
                  <PriceBreakdown quote={snap} nightly={d.nightly} canCost={canCost} finalTotal={snap.override_amount} />
                  {snap.override_amount && (
                    <Notice tone="warning">
                      {t("res.snap.override")} <Money amount={snap.override_amount} currency={d.currency} className="font-semibold" />
                    </Notice>
                  )}
                  <div className="grid gap-4 border-t border-zinc-100 pt-4 md:grid-cols-2">
                    <dl className="space-y-2 text-sm">
                      <div>
                        <dt className="text-xs font-medium text-zinc-500">{t("res.snap.contract_label")}</dt>
                        <dd className="text-zinc-800">
                          {snap.contract?.name} · {t("res.snap.contract", { code: snap.contract?.code ?? "", version: snap.contract?.version_no ?? "" })}
                          <span className="block text-xs text-zinc-500">{d.contract_version}</span>
                        </dd>
                      </div>
                      {hash && (
                        <div>
                          <dt className="text-xs font-medium text-zinc-500">{t("res.snap.hash")}</dt>
                          <dd className="flex items-center gap-1">
                            <code className="truncate rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-xs text-zinc-700" title={hash}>
                              {hash.slice(0, 16)}…
                            </code>
                            <IconButton
                              size="sm"
                              label={t("res.snap.copy_hash")}
                              icon={<Copy className="size-3.5" />}
                              onClick={async () => (await copyText(hash)) && toast.success(t("core.action.copied"))}
                            />
                          </dd>
                        </div>
                      )}
                      {snap.promotions?.some((p) => p.applied) && (
                        <div>
                          <dt className="text-xs font-medium text-zinc-500">{t("res.snap.promotions")}</dt>
                          <dd className="text-zinc-800">
                            {snap.promotions
                              .filter((p) => p.applied)
                              .map((p) => (p.code ? `${p.name} (${p.code})` : p.name))
                              .join(", ")}
                          </dd>
                        </div>
                      )}
                      {snap.fx_rates && snap.fx_rates.length > 0 ? (
                        <div>
                          <dt className="text-xs font-medium text-zinc-500">{t("res.snap.fx")}</dt>
                          {/* every rate the sold price was converted with, as recorded at the sale (G-56) */}
                          {snap.fx_rates.map((r) => (
                            <dd
                              key={`${r.from}-${r.to}`}
                              className="text-zinc-800"
                              title={[r.provider && `${r.provider} ${r.provider_rate ?? ""} ${r.rate_date ?? ""}`, r.policy_id, r.used_for.join(", ")]
                                .filter(Boolean)
                                .join(" · ")}
                            >
                              1 {r.from} = {r.sell_rate} {r.to}
                            </dd>
                          ))}
                        </div>
                      ) : (
                        snap.fx &&
                        snap.fx.from !== snap.fx.to && (
                          <div>
                            <dt className="text-xs font-medium text-zinc-500">{t("res.snap.fx")}</dt>
                            <dd className="text-zinc-800">
                              1 {snap.fx.from} = {snap.fx.sell_rate} {snap.fx.to}
                            </dd>
                          </div>
                        )
                      )}
                    </dl>
                    <PolicySummary rp={snap.rate_plan} currency={d.currency} />
                  </div>
                  {canCost && snap.explanation && snap.explanation.length > 0 && <ExplanationList steps={snap.explanation} />}
                </>
              ) : (
                <p className="text-sm">
                  <Money amount={d.total} currency={d.currency} />
                </p>
              )}
            </CardBody>
          </Card>

          {texPriced && (snap.addons?.length ?? 0) > 0 && <AddedExtrasCard addons={snap.addons ?? []} />}

          {!decideFirst && guestChangesCard}

          <Card role="region" aria-label={t("res.rev.title")}>
            <CardHeader title={t("res.rev.title")} description={t("res.rev.subtitle")} />
            <CardBody>
              <RevisionTimeline revisions={d.revisions} property={d.property} extraNames={extraNames} />
            </CardBody>
          </Card>
        </div>

        <div className="min-w-0 space-y-5">
          <Card>
            <CardHeader title={t("res.detail.guest")} />
            <CardBody>
              {d.guest ? (
                <DescriptionList
                  cols={1}
                  items={[
                    { label: t("res.col.guest"), value: d.guest.full_name },
                    { label: t("crs.guest.email"), value: d.guest.email ? <a className="text-tex-700 hover:underline" href={`mailto:${d.guest.email}`}>{d.guest.email}</a> : "—" },
                    { label: t("crs.guest.phone"), value: d.guest.phone ? <a className="text-tex-700 hover:underline" href={`tel:${d.guest.phone}`}>{d.guest.phone}</a> : "—" },
                    { label: t("crs.guest.language"), value: d.guest.tex_language?.toUpperCase() ?? "—" },
                    ...(d.guest.tex_tags ? [{ label: t("res.detail.tags"), value: d.guest.tex_tags }] : []),
                  ]}
                />
              ) : (
                <p className="text-sm text-zinc-500">{t("res.detail.guest_hidden")}</p>
              )}
            </CardBody>
          </Card>
          {d.booking && caps.has("price.view") && (
            <PaymentSummaryCard
              booking={d.booking}
              version={`${d.revision_no ?? 0}:${d.status}`}
              reservation={d.name}
              guestName={d.guest?.full_name}
              guestEmail={d.guest?.email ?? undefined}
              guestLanguage={d.guest?.tex_language ?? undefined}
            />
          )}
        </div>
      </div>

      {canModify && (
        <ModifyDrawer
          open={dialog === "modify"}
          onClose={() => setDialog(null)}
          res={d}
          onApplied={() => {
            setDialog(null)
            reload()
          }}
        />
      )}
      {canAddExtras && (
        <AddExtrasDialog
          open={dialog === "addon"}
          onClose={() => setDialog(null)}
          res={d}
          onApplied={() => {
            setDialog(null)
            reload()
          }}
        />
      )}
      {canSimulate && <SimulatorDialog open={dialog === "simulate"} onClose={() => setDialog(null)} res={d} canCost={canCost} />}
      {canCancel && (
        <CancelDialog
          open={dialog === "cancel"}
          onClose={() => setDialog(null)}
          res={d}
          canWaive={caps.has("price.override")}
          onCancelled={() => {
            setDialog(null)
            reload()
          }}
        />
      )}
      {canResend && d.booking && (
        <ResendConfirmationDialog open={dialog === "resend"} onClose={() => setDialog(null)} booking={d.booking} />
      )}
      {canCorrect && (
        <CorrectImportDialog
          open={dialog === "correct"}
          onClose={() => setDialog(null)}
          res={d}
          currencies={boot.currencies}
          onDone={() => {
            setDialog(null)
            reload()
          }}
        />
      )}
      <AcknowledgeDialog
        open={dialog === "ack"}
        onClose={() => setDialog(null)}
        res={d}
        onDone={() => {
          setDialog(null)
          reload()
        }}
      />
    </>
  )
}
