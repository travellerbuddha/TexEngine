import { CalendarDays, Copy, Sparkles, Users } from "lucide-react"
import { useState, type ReactNode } from "react"
import { useI18n, type MessageKey } from "../i18n"
import { nightsBetween } from "../lib/dates"
import { isPositive, isZero } from "../lib/format"
import { boardLabel } from "../lib/policy"
import { PriceLines } from "../flow/Summary"
import { partyText } from "../search/GuestsPicker"
import type { BookingRoom, BookingSummary } from "../types"
import { Badge } from "../ui/controls"

const STATUS: Record<string, { key: MessageKey; tone: "ok" | "warn" | "bad" | "neutral" }> = {
  Confirmed: { key: "status.confirmed", tone: "ok" },
  "Pending Payment": { key: "status.pendingPayment", tone: "warn" },
  Held: { key: "status.held", tone: "warn" },
  Cancelled: { key: "status.cancelled", tone: "bad" },
  "Partially Cancelled": { key: "status.partiallyCancelled", tone: "warn" },
  "Checked In": { key: "status.checkedIn", tone: "ok" },
  "Checked Out": { key: "status.checkedOut", tone: "neutral" },
  "No Show": { key: "status.noShow", tone: "bad" },
}

export function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n()
  const s = STATUS[status]
  return <Badge tone={s?.tone ?? "neutral"}>{s ? t(s.key) : status}</Badge>
}

const PAY_STATUS: Record<string, MessageKey> = {
  Unpaid: "payStatus.unpaid",
  Paid: "payStatus.paid",
  "Partially Paid": "payStatus.partial",
  "Pay at Hotel": "payStatus.atHotel",
  Refunded: "payStatus.refunded",
}

export function paymentStatusText(t: ReturnType<typeof useI18n>["t"], s: string) {
  const k = PAY_STATUS[s]
  return k ? t(k) : s
}

export function CopyButton({ value, label }: { value: string; label: string }) {
  const { t } = useI18n()
  const [done, setDone] = useState(false)
  return (
    <button
      type="button"
      className="inline-flex min-h-8 items-center gap-1 rounded-ui px-2 text-xs font-semibold text-brand-ink hover:bg-sunken"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value)
          setDone(true)
          setTimeout(() => setDone(false), 2000)
        } catch {
          /* clipboard blocked */
        }
      }}
      aria-label={`${t("common.copy")}: ${label}`}
    >
      <Copy className="size-3.5" aria-hidden />
      <span aria-live="polite">{done ? t("common.copied") : t("common.copy")}</span>
    </button>
  )
}

/** Price lines of an add-on (extras added after booking, ADR-034): their ref is its id. */
const ADDON_REF = /^ADD-[0-9a-f]+$/i

/** The extras chosen for the room (with it or added later; not those the hotel includes),
 * once per extra with the days it is used on. */
function extrasOf(room: BookingRoom) {
  const out = new Map<string, { name: string; dates: string[] }>()
  for (const e of room.extras ?? []) {
    if (e.ok === false || e.mandatory) continue
    const cur = out.get(e.code) ?? { name: e.name, dates: [] }
    for (const d of e.service_dates ?? []) if (!cur.dates.includes(d)) cur.dates.push(d)
    out.set(e.code, cur)
  }
  return [...out.values()].map((x) => ({ ...x, dates: x.dates.sort() }))
}

export function RoomBlock({ room, index, count, currency, actions, bookingStatus }: { room: BookingRoom; index: number; count: number; currency: string; actions?: ReactNode; bookingStatus?: string }) {
  const { t, range, money, day } = useI18n()
  const [open, setOpen] = useState(false)
  const nights = nightsBetween(room.check_in, room.check_out)
  const ages = (room.child_ages ?? []).map((c) => c.age)
  const extras = extrasOf(room)
  const stayLines = (room.lines ?? []).filter((l) => !ADDON_REF.test(l.ref ?? ""))
  const addonLines = (room.lines ?? []).filter((l) => ADDON_REF.test(l.ref ?? ""))
  return (
    <li className="py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          {count > 1 && <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t("guests.room", { n: index + 1 })}</p>}
          <p className="font-semibold">{room.room_type_name ?? room.room_type}</p>
          <p className="text-sm text-soft">{[boardLabel(t, room.board), room.rate_plan].filter(Boolean).join(" · ")}</p>
        </div>
        <div className="flex items-center gap-2">
          {room.status !== (bookingStatus ?? "Confirmed") && <StatusBadge status={room.status} />}
          {/* for a cancelled room the server's amount is the cancellation fee */}
          {room.status === "Cancelled" ? (
            <span className="text-right text-sm">
              <span className="block text-xs text-muted">{t("manage.feeLabel")}</span>
              <span className="font-semibold tabular-nums">{money(room.amount, currency)}</span>
            </span>
          ) : (
            <span className="font-semibold tabular-nums">{money(room.amount, currency)}</span>
          )}
        </div>
      </div>
      <p className="mt-1 flex items-center gap-1.5 text-sm text-soft">
        <CalendarDays className="size-4 text-muted" aria-hidden />
        {range(room.check_in, room.check_out)} · {t("dates.nights", { count: nights })}
      </p>
      <p className="flex items-center gap-1.5 text-sm text-soft">
        <Users className="size-4 text-muted" aria-hidden />
        {partyText(t, { adults: room.adults, ages: ages.length === room.children ? ages : undefined, children: room.children })}
      </p>
      {extras.length > 0 && (
        <div className="flex items-start gap-1.5 text-sm text-soft">
          <Sparkles className="mt-0.5 size-4 flex-none text-muted" aria-hidden />
          <p className="min-w-0">
            <span className="sr-only">{t("booking.extras")}: </span>
            {extras.map((x, i) => (
              <span key={i}>
                {i > 0 && ", "}
                {x.name}
                {x.dates.length > 0 && <span className="text-muted"> ({x.dates.map(day).join(" · ")})</span>}
              </span>
            ))}
          </p>
        </div>
      )}
      {room.refundable === false && <p className="mt-1 text-xs text-muted">{t("policy.nonRefundable")}</p>}
      {room.pending_change && (
        <p className="mt-2">
          <Badge tone="warn">{t("manage.pendingChange")}</Badge>
        </p>
      )}
      {!!room.lines?.length && (
        <>
          <button type="button" className="mt-1 min-h-6 text-xs font-medium text-brand-ink underline-offset-2 hover:underline" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {t("summary.priceDetails")}
          </button>
          {open && (
            <div className="mt-2 rounded-ui bg-sunken p-3">
              <PriceLines lines={stayLines} currency={currency} />
              {/* extras added after booking: priced on their own, with their own taxes */}
              {addonLines.length > 0 && (
                <div className="mt-2 border-t border-line pt-2">
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{t("booking.addedLater")}</p>
                  <PriceLines lines={addonLines} currency={currency} />
                </div>
              )}
            </div>
          )}
        </>
      )}
      {actions && <div className="mt-3 flex flex-wrap gap-2">{actions}</div>}
    </li>
  )
}

export function Totals({ b }: { b: BookingSummary }) {
  const { t, money } = useI18n()
  return (
    <dl className="space-y-1.5 text-sm">
      <div className="flex justify-between gap-3 text-base">
        <dt className="font-semibold">{t("summary.total")}</dt>
        <dd className="font-bold tabular-nums">{money(b.total, b.currency)}</dd>
      </div>
      {!isZero(b.paid) && (
        <div className="flex justify-between gap-3">
          <dt className="text-soft">{t("booking.paid")}</dt>
          <dd className="tabular-nums text-ok">{money(b.paid, b.currency)}</dd>
        </div>
      )}
      {isPositive(b.balance) && (
        <div className="flex justify-between gap-3">
          <dt className="text-soft">{b.payment_status === "Pay at Hotel" ? t("booking.payAtHotel") : t("booking.balance")}</dt>
          <dd className="tabular-nums">{money(b.balance, b.currency)}</dd>
        </div>
      )}
      <div className="flex justify-between gap-3 text-xs text-muted">
        <dt>{t("booking.paymentStatus")}</dt>
        <dd>{paymentStatusText(t, b.payment_status)}</dd>
      </div>
    </dl>
  )
}
