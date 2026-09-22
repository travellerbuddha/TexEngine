import { useState } from "react"
import { Link } from "react-router-dom"
import { CheckCircle2, Clock, Copy, Link2, Plus } from "lucide-react"
import { date } from "../../../lib/format"
import { useSession } from "../../../lib/session"
import { useTexT } from "../../../i18n"
import { Badge, Button, Card, CardBody, Money, statusTone, useToast } from "../../../ui"
import { useLabels } from "../lib/labels"
import { copyText, isPositive } from "../lib/party"
import type { BookingSummary, PropertyResult } from "../lib/types"
import { Row } from "./controls"
import { roomName } from "./OfferParts"
import { PaymentLinkDialog } from "./PaymentLinkDialog"

/** Booking number, amounts due and the follow-up actions (R-25: send payment link). */
export function Confirmation({
  booking,
  prop,
  guestName,
  guestEmail,
  onNew,
  newShortcut,
  compact,
}: {
  booking: BookingSummary
  prop?: PropertyResult
  guestName?: string
  guestEmail?: string
  onNew: () => void
  newShortcut?: string
  compact?: boolean
}) {
  const { t } = useTexT()
  const L = useLabels()
  const toast = useToast()
  const { can } = useSession()
  const [linkOpen, setLinkOpen] = useState(false)
  const confirmed = booking.status === "Confirmed"
  const linkAmount = isPositive(booking.due_now) ? booking.due_now : booking.balance
  const canLink = can("payment.link", booking.property) && isPositive(booking.balance)
  return (
    <Card>
      <CardBody className={compact ? "space-y-3" : "space-y-4"}>
        <div className="flex items-start gap-3">
          {confirmed ? (
            <CheckCircle2 className="mt-0.5 size-6 shrink-0 text-emerald-600" aria-hidden />
          ) : (
            <Clock className="mt-0.5 size-6 shrink-0 text-amber-600" aria-hidden />
          )}
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-zinc-950" tabIndex={-1} id="crs-confirmation-title">
              {confirmed ? t("crs.done.confirmed") : t("crs.done.pending")}
            </h2>
            <p className="text-sm text-zinc-600">{confirmed ? t("crs.done.confirmed_hint") : t("crs.done.pending_hint")}</p>
            {booking.idempotent_replay && <p className="mt-1 text-xs text-amber-800">{t("crs.done.replay")}</p>}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-zinc-50 px-3 py-2">
          <span className="text-xs text-zinc-500">{t("crs.done.number")}</span>
          <span className="font-mono text-lg font-semibold tracking-tight text-zinc-950">{booking.booking}</span>
          <Button
            variant="ghost"
            size="sm"
            icon={<Copy className="size-4" aria-hidden />}
            onClick={async () => (await copyText(booking.booking)) && toast.success(t("core.action.copied"))}
          >
            {t("core.action.copy")}
          </Button>
          <span className="ml-auto flex flex-wrap gap-1">
            <Badge tone={statusTone(booking.status)}>{L.status(booking.status)}</Badge>
            <Badge tone={statusTone(booking.payment_status)}>{L.status(booking.payment_status)}</Badge>
          </span>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Row strong label={t("crs.quote.total")} value={<Money amount={booking.total} currency={booking.currency} />} />
            <Row label={t("crs.pay.due_now")} value={<Money amount={booking.due_now} currency={booking.currency} />} />
            <Row label={t("crs.pay.paid")} value={<Money amount={booking.paid} currency={booking.currency} />} />
            <Row label={t("crs.pay.balance")} value={<Money amount={booking.balance} currency={booking.currency} />} />
          </div>
          <ul className="space-y-1 text-sm">
            {booking.rooms.map((r, i) => (
              <li key={r.reservation} className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="min-w-0">
                  <Link to={`/tex/reservations/${encodeURIComponent(r.reservation)}`} className="font-medium text-tex-700 hover:underline">
                    {r.reservation}
                  </Link>
                  <span className="block text-xs text-zinc-500">
                    {t("crs.room_n", { n: i + 1 })} · {roomName(prop, r.room_type)} · {date(r.check_in, "short")} – {date(r.check_out, "short")}
                  </span>
                </span>
                <Money amount={r.amount} currency={booking.currency} />
              </li>
            ))}
          </ul>
        </div>
        <div className="flex flex-wrap gap-2 border-t border-zinc-100 pt-3">
          {canLink && (
            <Button icon={<Link2 className="size-4" aria-hidden />} onClick={() => setLinkOpen(true)}>
              {t("crs.done.send_link")}
            </Button>
          )}
          <Link
            to={`/tex/reservations/booking/${encodeURIComponent(booking.booking)}`}
            className="inline-flex h-9 items-center rounded-lg border border-zinc-300 bg-white px-3.5 text-sm font-medium text-zinc-800 shadow-sm hover:bg-zinc-50"
          >
            {t("crs.done.open_booking")}
          </Link>
          <Button variant="ghost" icon={<Plus className="size-4" aria-hidden />} onClick={onNew} shortcut={newShortcut}>
            {t("crs.done.new")}
          </Button>
        </div>
      </CardBody>
      <PaymentLinkDialog
        open={linkOpen}
        onClose={() => setLinkOpen(false)}
        property={booking.property}
        currency={booking.currency}
        defaultAmount={linkAmount}
        booking={booking.booking}
        guestName={guestName}
        guestEmail={guestEmail}
      />
    </Card>
  )
}
