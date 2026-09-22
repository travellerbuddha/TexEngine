import { useEffect, useState } from "react"
import { tex } from "../../lib/api"
import { useTexT } from "../../i18n"
import { Button, DecimalInput, Dialog, Field, FormGrid, InlineError, Input, Notice, Select, Textarea, useToast } from "../../ui"
import { BookingPicker } from "./components/BookingPicker"
import { isPositiveAmount, isZero, useEvent, useIntentKey } from "./lib"
import type { BookingSummary } from "./types"

/** How the money was taken outside TEX (sent as free text; the server stores it
 * with the reason). Values stay English for the audit trail. */
const MANUAL_METHODS = ["Card terminal", "Cash", "Bank transfer (outside TEX)", "Agency remittance", "Voucher", "Other"] as const
const manualKey = (m: string) => `payments.manual.method.${m.toLowerCase().replace(/[^a-z]+/g, "_").replace(/_+$/, "")}`

export function ManualPaymentDialog({
  open,
  onClose,
  property,
  initialBooking,
  onDone,
}: {
  open: boolean
  onClose: () => void
  property: string
  initialBooking?: string
  onDone?: (transaction: string) => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const [booking, setBooking] = useState("")
  const [summary, setSummary] = useState<BookingSummary>()
  const [amount, setAmount] = useState("")
  const [method, setMethod] = useState<string>(MANUAL_METHODS[0])
  const [reference, setReference] = useState("")
  const [reason, setReason] = useState("")
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const key = useIntentKey("manual-pay", open)
  const close = useEvent(() => {
    if (!pending) onClose()
  })

  useEffect(() => {
    if (!open) return
    setBooking(initialBooking ?? "")
    setSummary(undefined)
    setAmount("")
    setMethod(MANUAL_METHODS[0])
    setReference("")
    setReason("")
    setError(null)
  }, [open, initialBooking])

  const onBooking = (b: string, s?: BookingSummary) => {
    setBooking(b)
    setSummary(s)
    // prefill with the balance the server reports (the user can change it)
    if (s && !amount && !isZero(s.balance) && !s.balance.startsWith("-")) setAmount(s.balance)
  }

  const valid = Boolean(booking) && isPositiveAmount(amount) && reference.trim().length > 0
  const submit = async () => {
    if (!valid) return
    setPending(true)
    setError(null)
    try {
      const r = await tex<{ transaction: string; replay?: boolean }>(
        "payments",
        "record_manual",
        { booking, amount, method, reference: reference.trim(), reason: reason.trim() || undefined, idempotency_key: key },
        { post: true },
      )
      toast.success(r.replay ? t("payments.manual.replay") : t("payments.manual.done"))
      onClose()
      onDone?.(r.transaction)
    } catch (e) {
      setError(e as Error)
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title={t("payments.manual.title")}
      description={t("payments.manual.desc")}
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={pending}>
            {t("core.action.cancel")}
          </Button>
          <Button loading={pending} disabled={!valid} onClick={submit}>
            {t("payments.manual.save")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <BookingPicker property={property} value={booking} onChange={onBooking} label={t("payments.manual.booking")} required autoFocus />
        <FormGrid>
          <Field label={t("payments.amount")} required hint={summary ? t("payments.manual.currency_hint", { currency: summary.currency }) : undefined}>
            <DecimalInput value={amount} onValueChange={setAmount} suffix={summary?.currency} />
          </Field>
          <Field label={t("payments.manual.method")} required>
            <Select value={method} onChange={(e) => setMethod(e.target.value)} options={MANUAL_METHODS.map((m) => ({ value: m, label: t(manualKey(m)) }))} />
          </Field>
        </FormGrid>
        <Field label={t("payments.manual.reference")} required hint={t("payments.manual.reference_hint")}>
          <Input value={reference} onChange={(e) => setReference(e.target.value)} maxLength={140} autoComplete="off" />
        </Field>
        <Field label={t("payments.manual.note")}>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={300} />
        </Field>
        <Notice tone="info">{t("payments.manual.no_card_data")}</Notice>
        <InlineError error={error} />
      </div>
    </Dialog>
  )
}
