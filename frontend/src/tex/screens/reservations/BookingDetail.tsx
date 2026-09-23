import { useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { MailCheck } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { date, num } from "../../lib/format"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import { Badge, Button, Card, CardHeader, DataTable, DescriptionList, CardBody, ErrorState, Money, Notice, PageHeader, Skeleton, statusTone } from "../../ui"
import { useLabels } from "../crs/lib/labels"
import { shortCode } from "../crs/lib/party"
import type { BookingRoom, BookingSummary } from "../crs/lib/types"
import type { ReservationRow } from "./lib/types"
import { ResendConfirmationDialog } from "./components/ActionDialogs"
import { PaymentSummaryBody } from "./components/DetailParts"

/** Multi-room booking: the parent of reservations A/B/C (R-29) with its payments. */
export default function BookingDetail() {
  const { name = "" } = useParams()
  const { t } = useTexT()
  const L = useLabels()
  const navigate = useNavigate()
  const { can } = useSession()
  const [resend, setResend] = useState(false)
  const q = useTexQuery<BookingSummary>("crs", "booking", { name }, [name])
  const b = q.data
  // names, board and guest of each room (the booking summary only carries codes)
  const rows = useTexQuery<ReservationRow[]>("crs", "reservations", { q: name, limit: 50 }, [name], Boolean(b))
  const byName = new Map((rows.data ?? []).filter((r) => r.tex_booking === name).map((r) => [r.name, r]))
  const crumbs = [{ label: t("core.nav.reservations"), to: "/tex/reservations" }, { label: name }]
  if (q.error)
    return (
      <>
        <PageHeader title={name} crumbs={crumbs} />
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      </>
    )
  if (!b)
    return (
      <>
        <PageHeader title={name} crumbs={crumbs} />
        <Card className="space-y-3 p-4" aria-busy="true">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-32 w-full" />
        </Card>
      </>
    )
  const showMoney = can("price.view", b.property)
  const canResend = can("reservation.modify", b.property) && b.status !== "Cancelled"
  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title={t("res.booking.title", { name: b.booking })}
        subtitle={[b.booker_name, b.property].filter(Boolean).join(" · ")}
        meta={
          <>
            <Badge tone={statusTone(b.status)}>{L.status(b.status)}</Badge>
            <Badge tone={statusTone(b.payment_status)}>{L.status(b.payment_status)}</Badge>
            {b.guest_change_pending && <Badge tone="warning">{t("res.badge.guest_change")}</Badge>}
          </>
        }
        actions={
          canResend ? (
            <Button variant="secondary" icon={<MailCheck className="size-4" aria-hidden />} onClick={() => setResend(true)}>
              {t("res.resend.button")}
            </Button>
          ) : undefined
        }
      />
      {canResend && <ResendConfirmationDialog open={resend} onClose={() => setResend(false)} booking={b.booking} />}
      {b.guest_change_pending && (
        <div className="mb-5">
          <Notice tone="warning">{t("res.booking.guest_change")}</Notice>
        </div>
      )}
      <div className="grid gap-5 lg:grid-cols-3">
        <div className="min-w-0 space-y-5 lg:col-span-2">
          <Card>
            <CardHeader title={t("res.booking.rooms", { count: b.rooms.length })} />
            <DataTable<BookingRoom>
              caption={t("res.booking.rooms", { count: b.rooms.length })}
              rows={b.rooms}
              rowKey={(r) => r.reservation}
              onRowClick={(r) => navigate(`/tex/reservations/${encodeURIComponent(r.reservation)}`)}
              columns={[
                {
                  key: "reservation",
                  header: t("res.col.reservation"),
                  cell: (r) => (
                    <span className="block whitespace-nowrap">
                      <span className="font-medium text-zinc-900">{r.reservation}</span>
                      {byName.get(r.reservation)?.guest_name && (
                        <span className="block text-xs text-zinc-500">{byName.get(r.reservation)?.guest_name}</span>
                      )}
                    </span>
                  ),
                },
                {
                  key: "room_type",
                  header: t("res.col.room"),
                  hideBelow: "sm",
                  cell: (r) => {
                    const row = byName.get(r.reservation)
                    return (
                      <span className="block">
                        {row?.room_type_name || shortCode(r.room_type, b.property)}
                        {row?.tex_board && <span className="block text-xs text-zinc-500">{L.board(row.tex_board)}</span>}
                      </span>
                    )
                  },
                },
                {
                  key: "stay",
                  header: t("res.col.stay"),
                  // guests under the dates: the card is two thirds wide, a separate column clipped the total
                  cell: (r) => (
                    <span className="block whitespace-nowrap">
                      {date(r.check_in, "short")} – {date(r.check_out, "short")}
                      <span className="block text-xs text-zinc-500">
                        {t("res.col.pax")}: {num(r.adults)} + {num(r.children)}
                      </span>
                    </span>
                  ),
                },
                { key: "status", header: t("core.label.status"), cell: (r) => <Badge tone={statusTone(r.status)}>{L.status(r.status)}</Badge> },
                {
                  key: "amount",
                  header: t("core.label.total"),
                  align: "right",
                  cell: (r) => (showMoney ? <Money amount={r.amount} currency={b.currency} /> : "—"),
                },
              ]}
            />
          </Card>
          <Card>
            <CardHeader title={t("res.booking.details")} />
            <CardBody>
              <DescriptionList
                cols={3}
                items={[
                  { label: t("res.booking.booker"), value: b.booker_name },
                  { label: t("crs.search.market"), value: b.market },
                  { label: t("crs.search.channel"), value: L.channel(b.channel) },
                ]}
              />
            </CardBody>
          </Card>
        </div>
        <div className="min-w-0">
          {showMoney && (
            <Card>
              <CardHeader title={t("res.pay.title")} />
              <PaymentSummaryBody b={b} onChanged={q.reload} />
            </Card>
          )}
        </div>
      </div>
    </>
  )
}
