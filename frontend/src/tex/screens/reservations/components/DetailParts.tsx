import { useState } from "react"
import { Link2 } from "lucide-react"
import { useTexQuery } from "../../../lib/api"
import { date, dateTime } from "../../../lib/format"
import { useSession } from "../../../lib/session"
import { useTexT } from "../../../i18n"
import { Badge, Button, Card, CardBody, CardHeader, ErrorState, Money, Skeleton, statusTone } from "../../../ui"
import { cn } from "../../../../lib/utils"
import { Row } from "../../crs/components/controls"
import { PaymentLinkDialog, ReissueLinkDialog } from "../../crs/components/PaymentLinkDialog"
import { useLabels } from "../../crs/lib/labels"
import { useServerClock } from "../../crs/lib/serverClock"
import { isPositive, isZero, shortCode } from "../../crs/lib/party"
import type { BookingSummary } from "../../crs/lib/types"
import type { Revision } from "../lib/types"

const FIELD_KEYS: Record<string, string> = {
  check_in_date: "res.field.check_in",
  check_out_date: "res.field.check_out",
  room_type: "res.field.room_type",
  adults: "res.field.adults",
  children: "res.field.children",
  tex_board: "res.field.board",
  rate_plan: "res.field.rate_plan",
  tex_market: "res.field.market",
  tex_total_amount: "res.field.total",
  tex_contract_version: "res.field.contract_version",
  status: "core.label.status",
  penalty: "res.field.penalty",
}

function show(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—"
  if (typeof v === "object") return JSON.stringify(v)
  return String(v)
}

/** Revision history (R-23): who changed what, old → new amount, basis and reason. */
const DATE_FIELDS = new Set(["check_in_date", "check_out_date"])

export function RevisionTimeline({ revisions, property }: { revisions: Revision[]; property?: string }) {
  const { t } = useTexT()
  const L = useLabels()
  const fmt = (k: string, v: unknown) => {
    const x = show(v)
    if (x === "—") return x
    if (DATE_FIELDS.has(k)) return date(x.slice(0, 10))
    if (k === "tex_board") return L.board(x)
    if (k === "room_type" || k === "rate_plan") return shortCode(x, property)
    return x
  }
  if (!revisions.length) return <p className="text-sm text-zinc-500">{t("res.rev.none")}</p>
  const ordered = [...revisions].sort((a, b) => b.revision_no - a.revision_no)
  return (
    <ol aria-label={t("res.rev.title")} className="relative space-y-4 border-l border-zinc-200 pl-5">
      {ordered.map((r) => {
        const fields = Object.entries(r.changes ?? {}).filter(([k, v]) => k !== "requested" && k !== "policy" && Array.isArray(v))
        const original = r.change_type === "Original"
        const override = r.pricing_basis === "MANUAL" && r.override_amount && !isZero(r.override_amount)
        return (
          <li
            key={r.name}
            className="relative"
            // raw figures for tools and tests (the text shows them formatted)
            data-revision={r.revision_no}
            data-change-type={r.change_type}
            data-old-amount={r.old_amount ?? ""}
            data-new-amount={r.new_amount ?? ""}
            data-currency={r.currency ?? ""}
          >
            <span
              aria-hidden
              className={cn(
                "absolute top-1 -left-[1.6rem] size-3 rounded-full border-2 border-white ring-1",
                r.change_type === "Cancellation" ? "bg-rose-600 ring-rose-200" : original ? "bg-emerald-600 ring-emerald-200" : "bg-tex-600 ring-tex-200",
              )}
            />
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-sm font-semibold text-zinc-900">
                {t("res.rev.n", { n: r.revision_no })} · {L.changeType(r.change_type)}
              </p>
              <time className="text-xs text-zinc-500" dateTime={r.creation}>
                {dateTime(r.creation)}
              </time>
            </div>
            <p className="text-xs text-zinc-500">
              {r.actor}
              {r.source ? ` · ${L.source(r.source)}` : ""}
              {r.pricing_basis && r.pricing_basis !== "NONE" ? ` · ${L.basis(r.pricing_basis)}` : ""}
              {r.approval_status && r.approval_status !== "Not Required" ? ` · ${L.approval(r.approval_status)}` : ""}
            </p>
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
              {original ? (
                <span>
                  {t("res.rev.sold_at")} <Money amount={r.new_amount} currency={r.currency} className="font-medium" />
                </span>
              ) : (
                <>
                  <Money amount={r.old_amount} currency={r.currency} muted />
                  <span aria-hidden>→</span>
                  <span className="sr-only">{t("res.rev.to")}</span>
                  <Money amount={r.new_amount} currency={r.currency} className="font-medium" />
                  {r.difference && !isZero(r.difference) && (
                    <span className="text-xs">
                      (<Money amount={r.difference} currency={r.currency} signed />)
                    </span>
                  )}
                  {override && <Badge tone="warning">{t("res.rev.override")}</Badge>}
                </>
              )}
            </div>
            {fields.length > 0 && (
              <ul className="mt-1 space-y-0.5 text-xs text-zinc-600">
                {fields.map(([k, v]) => {
                  const [a, b] = v as [unknown, unknown]
                  const money = k === "tex_total_amount"
                  return (
                    <li key={k}>
                      <span className="font-medium text-zinc-700">{FIELD_KEYS[k] ? t(FIELD_KEYS[k]) : k}:</span>{" "}
                      {money ? (
                        <>
                          <Money amount={show(a)} currency={r.currency} muted /> → <Money amount={show(b)} currency={r.currency} />
                        </>
                      ) : (
                        <>
                          <span className="line-through decoration-zinc-400">{fmt(k, a)}</span> → <span className="text-zinc-900">{fmt(k, b)}</span>
                        </>
                      )}
                    </li>
                  )
                })}
              </ul>
            )}
            {r.change_type === "Cancellation" && typeof r.changes?.penalty === "string" && (
              <p className="mt-1 text-xs text-zinc-600">
                {t("res.field.penalty")}: <Money amount={r.changes.penalty as string} currency={r.currency} />
              </p>
            )}
            {r.reason && (
              <blockquote className="mt-1 border-l-2 border-zinc-300 pl-2 text-sm text-zinc-700 italic">{r.reason}</blockquote>
            )}
          </li>
        )
      })}
    </ol>
  )
}

/** Payment summary of the booking a reservation belongs to (crs.booking). */
export function PaymentSummaryCard({
  booking,
  guestName,
  guestEmail,
  guestLanguage,
  reservation,
  version,
}: {
  booking: string
  guestName?: string
  guestEmail?: string
  guestLanguage?: string
  reservation?: string
  /** Changes whenever the reservation changes (revision / status), to refetch the booking. */
  version?: string
}) {
  const { t } = useTexT()
  const q = useTexQuery<BookingSummary>("crs", "booking", { name: booking }, [booking, version])
  return (
    <Card>
      <CardHeader title={t("res.pay.title")} description={booking} />
      {q.error ? (
        <ErrorState error={q.error} onRetry={q.reload} />
      ) : !q.data ? (
        <CardBody className="space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </CardBody>
      ) : (
        <PaymentSummaryBody
          b={q.data}
          guestName={guestName}
          guestEmail={guestEmail}
          guestLanguage={guestLanguage}
          reservation={reservation}
          onChanged={q.reload}
        />
      )}
    </Card>
  )
}

export function PaymentSummaryBody({
  b,
  guestName,
  guestEmail,
  guestLanguage,
  reservation,
  onChanged,
}: {
  b: BookingSummary
  guestName?: string
  guestEmail?: string
  guestLanguage?: string
  reservation?: string
  onChanged?: () => void
}) {
  const { t } = useTexT()
  const L = useLabels()
  const { can } = useSession()
  const clock = useServerClock()
  const [open, setOpen] = useState(false)
  const [reissue, setReissue] = useState<string | null>(null)
  const mayLink = can("payment.link", b.property)
  const canLink = mayLink && isPositive(b.balance) && b.status !== "Cancelled"
  return (
    <CardBody className="space-y-3">
      <div className="flex flex-wrap gap-1">
        <Badge tone={statusTone(b.payment_status)}>{L.status(b.payment_status)}</Badge>
        {b.status !== "Confirmed" && <Badge tone={statusTone(b.status)}>{L.status(b.status)}</Badge>}
      </div>
      <div>
        <Row strong label={t("crs.quote.total")} value={<Money amount={b.total} currency={b.currency} />} />
        <Row label={t("crs.pay.paid")} value={<Money amount={b.paid} currency={b.currency} />} />
        <Row label={t("crs.pay.balance")} value={<Money amount={b.balance} currency={b.currency} />} />
        {isPositive(b.due_now) && <Row label={t("crs.pay.due_now")} value={<Money amount={b.due_now} currency={b.currency} />} />}
      </div>
      {b.transactions && b.transactions.length > 0 && (
        <div>
          <p className="text-xs font-semibold tracking-wide text-zinc-500 uppercase">{t("res.pay.transactions")}</p>
          <ul className="mt-1 space-y-1 text-sm">
            {b.transactions.map((x) => (
              <li key={x.name} className="flex items-baseline justify-between gap-2">
                <span className="min-w-0">
                  {L.method(x.method)} · {L.txn(x.txn_type)}
                  {x.card_last4 ? ` ·••${x.card_last4}` : ""}
                  <span className="block text-xs text-zinc-500">{dateTime(x.completed_at || x.creation)}</span>
                </span>
                <span className="text-right">
                  <Money amount={x.amount} currency={x.currency} />
                  <Badge tone={statusTone(x.status)} className="ml-1">
                    {L.status(x.status)}
                  </Badge>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {b.payment_links && b.payment_links.length > 0 && (
        <div>
          <p className="text-xs font-semibold tracking-wide text-zinc-500 uppercase">{t("res.pay.links")}</p>
          <ul className="mt-1 space-y-1 text-sm">
            {b.payment_links.map((l) => (
              <li key={l.name} className="flex items-baseline justify-between gap-2">
                <span className="min-w-0">
                  {l.name}
                  {l.expires_at && (
                    <span className="block text-xs text-zinc-500">{t("res.pay.expires", { time: clock.label(l.expires_at) })}</span>
                  )}
                  {isPositive(l.paid_amount) && (
                    <span className="block text-xs text-zinc-500">
                      {t("res.pay.link_paid")} <Money amount={l.paid_amount} currency={l.currency} />
                    </span>
                  )}
                </span>
                <span className="text-right">
                  <Money amount={l.amount} currency={l.currency} />
                  <Badge tone={statusTone(l.status)} className="ml-1">
                    {L.status(l.status)}
                  </Badge>
                  {mayLink && (l.status === "Active" || l.status === "Partially Paid") && (
                    <button
                      type="button"
                      className="ml-2 text-xs font-medium text-tex-700 hover:underline"
                      aria-label={t("crs.link.reissue_title", { name: l.name })}
                      onClick={() => setReissue(l.name)}
                    >
                      {t("crs.link.reissue_short")}
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {canLink && (
        <>
          <Button variant="secondary" size="sm" icon={<Link2 className="size-4" aria-hidden />} onClick={() => setOpen(true)}>
            {t("crs.done.send_link")}
          </Button>
          <PaymentLinkDialog
            open={open}
            onClose={() => {
              setOpen(false)
              onChanged?.()
            }}
            property={b.property}
            currency={b.currency}
            defaultAmount={isPositive(b.due_now) ? b.due_now : b.balance}
            booking={b.booking}
            reservation={reservation}
            guestName={guestName ?? b.booker_name}
            guestEmail={guestEmail}
            guestLanguage={guestLanguage}
          />
        </>
      )}
      <ReissueLinkDialog
        open={reissue !== null}
        link={reissue}
        onClose={() => {
          setReissue(null)
          onChanged?.()
        }}
        guestEmail={guestEmail}
        guestLanguage={guestLanguage}
      />
    </CardBody>
  )
}
