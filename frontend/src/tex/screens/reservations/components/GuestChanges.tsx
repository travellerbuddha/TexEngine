import { useEffect, useState } from "react"
import { Check, CircleDollarSign, X } from "lucide-react"
import type { TexApiError } from "../../../lib/api"
import { date } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, Card, CardBody, CardHeader, Dialog, Field, InlineError, Money, Notice, Segmented, Textarea, useToast } from "../../../ui"
import { usePartyText } from "../../crs/components/PartyEditor"
import { isPositive, isZero } from "../../crs/lib/party"
import { useServerClock } from "../../crs/lib/serverClock"
import { asApiError } from "../../crs/lib/useBookingFlow"
import { resolveGuestChange, type RefundOutcome, type ResolveAction, type ResolveSettlement, type StaffMoney } from "../lib/api"
import type { GuestChangeRequest } from "../lib/types"

type Tone = "neutral" | "info" | "success" | "warning" | "danger"
const STATUS_TONE: Record<GuestChangeRequest["status"], Tone> = {
  "Awaiting Payment": "warning",
  Requested: "warning",
  Applied: "success",
  Approved: "success",
  Rejected: "neutral",
  Failed: "danger",
  Expired: "neutral",
  Superseded: "neutral",
}
/** i18n key suffix of a status / settlement ("Credit on booking" → "credit_on_booking"). */
const slug = (v: string) => v.toLowerCase().replace(/[^a-z0-9]+/g, "_")

/**
 * The guest's own changes of this reservation (manage page, G-45 / ADR-044): what they asked
 * for, what it cost, how the money was settled (paid online, at the hotel, refunded, kept as
 * credit, left to staff). A request waiting for the hotel is approved or rejected here
 * (reservation.modify; a refund needs payment.refund), and money left to staff (a refund TEX
 * could not make, or one the gateway never confirmed: staff say what the gateway did) is marked
 * as settled (payment.refund). The server decides and re-checks everything; amounts are its own.
 */
export function GuestChangesCard({
  rows,
  caps,
  currency,
  adults,
  childAges,
  onResolved,
}: {
  rows: GuestChangeRequest[]
  caps: Set<string>
  currency: string
  adults: number
  childAges: (number | null)[]
  onResolved: () => void
}) {
  const { t } = useTexT()
  const clock = useServerClock()
  const partyText = usePartyText()
  const [dialog, setDialog] = useState<{ row: GuestChangeRequest; action: ResolveAction } | null>(null)
  const canDecide = caps.has("reservation.modify")
  const canRefund = caps.has("payment.refund")

  const changesText = (r: GuestChangeRequest) => {
    const c = r.changes ?? {}
    const parts: string[] = []
    if (c.check_in) parts.push(`${t("crs.search.check_in")} ${date(c.check_in, "long")}`)
    if (c.check_out) parts.push(`${t("crs.search.check_out")} ${date(c.check_out, "long")}`)
    if (c.adults !== undefined || c.children !== undefined) {
      const ages = (c.children ?? childAges).map((x) => (typeof x === "number" ? x : x && typeof x === "object" ? (x.age ?? null) : null))
      parts.push(partyText(c.adults ?? adults, ages))
    }
    return parts.join(" · ") || "—"
  }

  return (
    <Card role="region" aria-label={t("res.gcr.title")}>
      <CardHeader title={t("res.gcr.title")} description={t("res.gcr.subtitle")} />
      <CardBody className="p-0">
        <ul className="divide-y divide-zinc-100">
          {rows.map((r) => {
            const ccy = r.currency || currency
            const settled = r.settlement && r.settlement !== "None" ? r.settlement : null
            return (
              <li key={r.name} data-request={r.name} data-status={r.status} className="space-y-2 px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={STATUS_TONE[r.status] ?? "info"}>{t(`res.gcr.status.${slug(r.status)}`)}</Badge>
                    {r.needs_staff && <Badge tone="warning">{t("res.gcr.needs_staff")}</Badge>}
                    <span className="text-xs text-zinc-500">
                      {r.name} · {clock.label(r.creation)}
                    </span>
                  </div>
                  <Money amount={r.difference} currency={ccy} signed className="text-sm font-semibold" />
                </div>
                <p className="text-sm text-zinc-800">{changesText(r)}</p>
                <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
                  {isPositive(r.collect_amount) && (
                    <div className="flex justify-between gap-3">
                      <dt className="text-zinc-500">{t("res.gcr.collect")}</dt>
                      <dd>
                        <Money amount={r.collect_amount} currency={ccy} />
                      </dd>
                    </div>
                  )}
                  {settled && (
                    <div className="flex justify-between gap-3">
                      <dt className="text-zinc-500">{t(`res.gcr.settlement.${slug(settled)}`)}</dt>
                      <dd>
                        <Money amount={r.settlement_amount} currency={ccy} />
                      </dd>
                    </div>
                  )}
                  {!isZero(r.refunded_amount) && (
                    <div className="flex justify-between gap-3">
                      <dt className="text-zinc-500">{t("res.gcr.refunded")}</dt>
                      <dd>
                        <Money amount={r.refunded_amount} currency={ccy} />
                      </dd>
                    </div>
                  )}
                  {r.status === "Requested" && r.overpaid_after && isPositive(r.overpaid_after) && (
                    <div className="flex justify-between gap-3">
                      <dt className="text-zinc-500">{t("res.gcr.overpaid")}</dt>
                      <dd>
                        <Money amount={r.overpaid_after} currency={ccy} />
                      </dd>
                    </div>
                  )}
                  {r.status === "Awaiting Payment" && r.expires_at && (
                    <div className="flex justify-between gap-3">
                      <dt className="text-zinc-500">{t("res.gcr.expires")}</dt>
                      <dd className="text-right">{clock.label(r.expires_at)}</dd>
                    </div>
                  )}
                </dl>
                {r.status === "Requested" && r.penalty_terms && <p className="text-xs text-amber-800">{t("res.gcr.penalty_terms")}</p>}
                {r.settle_pending && <p className="text-xs text-amber-800">{t(r.verify_refund ? "res.gcr.refund_waits" : "res.gcr.refund_pending")}</p>}
                {r.staff_open && (
                  <Notice tone={r.staff_reason === "Verify refund at gateway" ? "danger" : "warning"}>
                    <span className="font-medium">{t(`res.gcr.staff.${slug(r.staff_reason || "Refund by staff")}`)}</span>{" "}
                    <Money amount={r.verify_refund ? r.staff_amount : r.staff_due} currency={ccy} className="font-semibold" />
                    {r.unknown_refund && <span className="block text-xs">{t("res.gcr.staff.unknown_refund", { refund: r.unknown_refund })}</span>}
                    {!r.can_close && r.close_blocked && <span className="block text-xs">{r.close_blocked}</span>}
                  </Notice>
                )}
                {r.note && (
                  <p className="text-sm text-zinc-600">
                    <span className="font-medium">{t("res.gcr.guest_note")}:</span> {r.note}
                  </p>
                )}
                {r.error && <p className="text-xs whitespace-pre-line text-zinc-500">{r.error}</p>}
                {r.resolved_at && (
                  <p className="text-xs text-zinc-500">
                    {t("res.gcr.resolved", { user: r.resolved_by ?? "—", time: clock.label(r.resolved_at) })}
                    {r.resolution ? ` — ${r.resolution}` : ""}
                  </p>
                )}
                {((r.status === "Requested" && canDecide) || (r.can_close && canRefund)) && (
                  <div className="flex flex-wrap gap-2 pt-1">
                    {r.status === "Requested" && canDecide && (
                      <>
                        <Button size="sm" icon={<Check className="size-4" aria-hidden />} onClick={() => setDialog({ row: r, action: "approve" })}>
                          {t("res.gcr.approve")}
                        </Button>
                        <Button size="sm" variant="secondary" icon={<X className="size-4" aria-hidden />} onClick={() => setDialog({ row: r, action: "reject" })}>
                          {t("res.gcr.reject")}
                        </Button>
                      </>
                    )}
                    {r.can_close && canRefund && (
                      <Button size="sm" variant="secondary" icon={<CircleDollarSign className="size-4" aria-hidden />} onClick={() => setDialog({ row: r, action: "close" })}>
                        {t("res.gcr.close")}
                      </Button>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      </CardBody>
      <ResolveDialog
        target={dialog}
        canRefund={canRefund}
        onClose={() => setDialog(null)}
        onDone={() => {
          setDialog(null)
          onResolved()
        }}
      />
    </Card>
  )
}

function ResolveDialog({
  target,
  canRefund,
  onClose,
  onDone,
}: {
  target: { row: GuestChangeRequest; action: ResolveAction } | null
  canRefund: boolean
  onClose: () => void
  onDone: () => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const [reason, setReason] = useState("")
  const [settlement, setSettlement] = useState<ResolveSettlement>("Credit on booking")
  const [outcome, setOutcome] = useState<RefundOutcome | "">("")
  const [staffMoney, setStaffMoney] = useState<StaffMoney | "">("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TexApiError>()
  const row = target?.row
  const action = target?.action
  const overpaid = action === "approve" && !!row?.overpaid_after && isPositive(row.overpaid_after)
  // a refund the gateway never confirmed: staff say what the gateway did before closing
  const verify = action === "close" && !!row?.verify_refund
  // other money left to staff: say what became of it (refunded outside TEX is recorded on the booking)
  const settleMoney = action === "close" && !verify
  useEffect(() => {
    if (!target) return
    setReason("")
    setError(undefined)
    setSettlement(canRefund ? "Refund" : "Credit on booking")
    setOutcome("")
    setStaffMoney("")
  }, [target, canRefund])

  const submit = async () => {
    if (!row || !action || !reason.trim() || (verify && !outcome) || (settleMoney && !staffMoney)) return
    setBusy(true)
    setError(undefined)
    try {
      await resolveGuestChange(
        row.name,
        action,
        reason.trim(),
        overpaid ? settlement : undefined,
        verify && outcome ? outcome : undefined,
        settleMoney && staffMoney ? staffMoney : undefined,
      )
      toast.success(t(`res.gcr.done.${action}`))
      onDone()
    } catch (e) {
      setError(asApiError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={!!target}
      onClose={busy ? () => undefined : onClose}
      size="sm"
      title={action ? t(`res.gcr.${action}_title`) : ""}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {t("core.action.cancel")}
          </Button>
          <Button loading={busy} disabled={!reason.trim() || (verify && !outcome) || (settleMoney && !staffMoney)} variant={action === "reject" ? "danger" : "primary"} onClick={() => void submit()}>
            {action ? t(`res.gcr.${action}`) : ""}
          </Button>
        </>
      }
    >
      {row && action && (
        <div className="space-y-3">
          <p className="text-sm text-zinc-700">{t(`res.gcr.${action}_body`)}</p>
          {overpaid && (
            <div className="space-y-2">
              <Notice tone="warning">
                {t("res.gcr.approve_overpaid")} <Money amount={row.overpaid_after} currency={row.currency} className="font-semibold" />
              </Notice>
              <Segmented<ResolveSettlement>
                label={t("res.gcr.settlement_choice")}
                value={settlement}
                onChange={setSettlement}
                options={[
                  ...(canRefund ? [{ value: "Refund" as const, label: t("res.gcr.choose_refund") }] : []),
                  { value: "Credit on booking" as const, label: t("res.gcr.choose_credit") },
                ]}
              />
              {!canRefund && <p className="text-xs text-zinc-500">{t("res.gcr.no_refund_cap")}</p>}
            </div>
          )}
          {verify && (
            <div className="space-y-2">
              <Notice tone="danger">{t("res.gcr.verify_body", { refund: row.verify_refund ?? "" })}</Notice>
              <Segmented<RefundOutcome | "">
                label={t("res.gcr.verify_choice")}
                value={outcome}
                onChange={setOutcome}
                options={[
                  { value: "Succeeded", label: t("res.gcr.verify_succeeded") },
                  { value: "Failed", label: t("res.gcr.verify_failed") },
                ]}
              />
            </div>
          )}
          {settleMoney && (
            <div className="space-y-2">
              <Segmented<StaffMoney | "">
                label={t("res.gcr.staff_money_choice")}
                value={staffMoney}
                onChange={setStaffMoney}
                options={[
                  { value: "Refunded outside TEX", label: t("res.gcr.staff_money.refunded") },
                  { value: "Kept on the booking", label: t("res.gcr.staff_money.kept") },
                ]}
              />
              <p className="text-xs text-zinc-500">{t(staffMoney === "Kept on the booking" ? "res.gcr.staff_money.kept_hint" : "res.gcr.staff_money.refunded_hint")}</p>
            </div>
          )}
          <Field label={t("res.gcr.reason")} hint={t("core.hint.reason_audited")} required>
            <Textarea id="gcr-reason" value={reason} onChange={(e) => setReason(e.target.value.slice(0, 500))} data-autofocus />
          </Field>
          <InlineError error={error} />
        </div>
      )}
    </Dialog>
  )
}
