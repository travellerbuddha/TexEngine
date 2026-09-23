import { useEffect, useMemo, useState } from "react"
import { tex } from "../../../lib/api"
import { useTexT } from "../../../i18n"
import { Button, DecimalInput, Dialog, Field, InlineError, Input, Money, Notice, Segmented, Select, Textarea, useToast } from "../../../ui"
import { BookingPicker } from "../components/BookingPicker"
import { isPositiveAmount, isZero, useEvent, useIntentKey } from "../lib"
import type { TxnDetail } from "../types"

function useAction(open: boolean) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  useEffect(() => {
    if (open) setError(null)
  }, [open])
  const run = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setPending(true)
    setError(null)
    try {
      return await fn()
    } catch (e) {
      setError(e as Error)
      return undefined
    } finally {
      setPending(false)
    }
  }
  return { pending, error, run }
}

function Footer({ onCancel, onConfirm, pending, disabled, label, danger }: { onCancel: () => void; onConfirm: () => void; pending: boolean; disabled: boolean; label: string; danger?: boolean }) {
  const { t } = useTexT()
  return (
    <>
      <Button variant="secondary" onClick={onCancel} disabled={pending}>
        {t("core.action.cancel")}
      </Button>
      <Button variant={danger ? "danger" : "primary"} loading={pending} disabled={disabled} onClick={onConfirm}>
        {label}
      </Button>
    </>
  )
}

/** Bookings holding part of this payment now (after transfers and refunds), never one that holds none. */
function holdingBookings(txn: TxnDetail) {
  return Object.keys(txn.booking_nets ?? {})
}

export function RefundDialog({ open, onClose, txn, onDone }: { open: boolean; onClose: () => void; txn: TxnDetail; onDone: () => void }) {
  const { t } = useTexT()
  const toast = useToast()
  const a = useAction(open)
  const key = useIntentKey("refund", open)
  const [amount, setAmount] = useState("")
  const [reason, setReason] = useState("")
  const [booking, setBooking] = useState("")
  const bookings = useMemo(() => holdingBookings(txn), [txn])
  const ccy = txn.refund_currency || txn.currency
  const close = useEvent(() => {
    if (!a.pending) onClose()
  })
  useEffect(() => {
    if (!open) return
    setAmount(txn.refundable)
    setReason("")
    // no booking by default: the server refunds unallocated money first, then the one booking holding the rest
    setBooking("")
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  const valid = isPositiveAmount(amount) && reason.trim().length > 2
  const submit = async () => {
    if (!valid) return
    const r = await a.run(() =>
      tex<{ refund: string; status?: string; replay?: boolean }>(
        "payments",
        "refund",
        { transaction: txn.name, amount, reason: reason.trim(), idempotency_key: key, booking: booking || undefined },
        { post: true },
      ),
    )
    if (!r) return
    // a refund the gateway has not confirmed (a replay of an unanswered one) is never announced as done
    if (r.status === "Failed") toast.error(t("payments.refund.failed", { name: r.refund }))
    else if (r.status === "Pending") toast.info(t("payments.refund.pending", { name: r.refund }))
    else toast.success(r.replay ? t("payments.refund.replay", { name: r.refund }) : t("payments.refund.done", { name: r.refund }))
    onDone()
    onClose()
  }
  return (
    <Dialog
      open={open}
      onClose={close}
      title={t("payments.refund.title")}
      description={t("payments.refund.desc")}
      footer={<Footer onCancel={close} onConfirm={submit} pending={a.pending} disabled={!valid} label={t("payments.refund.confirm")} danger />}
    >
      <div className="space-y-4">
        <p className="text-sm text-zinc-700">
          {t("payments.refund.refundable")} <Money amount={txn.refundable} currency={ccy} className="font-semibold" />
        </p>
        <Field label={t("payments.amount")} required hint={t("payments.refund.amount_hint")}>
          <DecimalInput value={amount} onValueChange={setAmount} suffix={ccy} data-autofocus />
        </Field>
        {bookings.length > 0 && txn.status === "Succeeded" && (
          <Field label={t("payments.refund.booking")} hint={t("payments.refund.booking_hint")}>
            <Select
              value={booking}
              onChange={(e) => setBooking(e.target.value)}
              options={[
                { value: "", label: t("payments.refund.no_booking") },
                ...bookings.map((b) => ({ value: b, label: `${b} · ${txn.booking_nets[b]} ${txn.currency}` })),
              ]}
            />
          </Field>
        )}
        <Field label={t("core.field.reason")} required hint={t("core.hint.reason_audited")}>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={500} />
        </Field>
        {txn.provider === "Mock" && <Notice tone="warning">{t("payments.refund.sandbox")}</Notice>}
        <InlineError error={a.error} />
      </div>
    </Dialog>
  )
}

export function AllocateDialog({ open, onClose, txn, onDone }: { open: boolean; onClose: () => void; txn: TxnDetail; onDone: () => void }) {
  const { t } = useTexT()
  const toast = useToast()
  const a = useAction(open)
  const key = useIntentKey("allocate", open)
  const [booking, setBooking] = useState("")
  const [amount, setAmount] = useState("")
  const [reason, setReason] = useState("")
  const close = useEvent(() => {
    if (!a.pending) onClose()
  })
  useEffect(() => {
    if (!open) return
    setBooking("")
    setAmount(txn.unallocated)
    setReason("")
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  const valid = Boolean(booking) && isPositiveAmount(amount) && reason.trim().length > 2
  const submit = async () => {
    if (!valid) return
    const r = await a.run(() => tex("payments", "allocate", { transaction: txn.name, booking, amount, reason: reason.trim(), idempotency_key: key }, { post: true }))
    if (r === undefined) return
    toast.success(t("payments.allocate.done", { booking }))
    onDone()
    onClose()
  }
  return (
    <Dialog
      open={open}
      onClose={close}
      title={t("payments.allocate.title")}
      description={t("payments.allocate.desc")}
      size="lg"
      footer={<Footer onCancel={close} onConfirm={submit} pending={a.pending} disabled={!valid} label={t("payments.allocate.confirm")} />}
    >
      <div className="space-y-4">
        <p className="text-sm text-zinc-700">
          {t("payments.allocate.unallocated")} <Money amount={txn.unallocated} currency={txn.currency} className="font-semibold" />
        </p>
        <BookingPicker property={txn.property} value={booking} onChange={(b) => setBooking(b)} label={t("payments.allocate.booking")} required expectCurrency={txn.currency} autoFocus />
        <Field label={t("payments.amount")} required>
          <DecimalInput value={amount} onValueChange={setAmount} suffix={txn.currency} />
        </Field>
        <Field label={t("core.field.reason")} required hint={t("core.hint.reason_audited")}>
          <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} autoComplete="off" />
        </Field>
        <InlineError error={a.error} />
      </div>
    </Dialog>
  )
}

export function TransferDialog({ open, onClose, txn, onDone }: { open: boolean; onClose: () => void; txn: TxnDetail; onDone: () => void }) {
  const { t } = useTexT()
  const toast = useToast()
  const a = useAction(open)
  const key = useIntentKey("transfer", open)
  const sources = useMemo(() => holdingBookings(txn), [txn])
  const [from, setFrom] = useState("")
  const [to, setTo] = useState("")
  const [amount, setAmount] = useState("")
  const [reason, setReason] = useState("")
  const close = useEvent(() => {
    if (!a.pending) onClose()
  })
  useEffect(() => {
    if (!open) return
    setFrom(sources[0] ?? "")
    setTo("")
    setAmount("")
    setReason("")
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  const valid = Boolean(from) && Boolean(to) && from !== to && isPositiveAmount(amount) && reason.trim().length > 2
  const submit = async () => {
    if (!valid) return
    const r = await a.run(() => tex("payments", "transfer", { transaction: txn.name, from_booking: from, to_booking: to, amount, reason: reason.trim(), idempotency_key: key }, { post: true }))
    if (r === undefined) return
    toast.success(t("payments.transfer.done", { from, to }))
    onDone()
    onClose()
  }
  return (
    <Dialog
      open={open}
      onClose={close}
      title={t("payments.transfer.title")}
      description={t("payments.transfer.desc")}
      size="lg"
      footer={<Footer onCancel={close} onConfirm={submit} pending={a.pending} disabled={!valid} label={t("payments.transfer.confirm")} />}
    >
      <div className="space-y-4">
        <Field label={t("payments.transfer.from")} required hint={t("payments.transfer.from_hint")}>
          <Select value={from} onChange={(e) => setFrom(e.target.value)} options={sources.map((b) => ({ value: b, label: b }))} data-autofocus />
        </Field>
        <BookingPicker property={txn.property} value={to} onChange={(b) => setTo(b)} label={t("payments.transfer.to")} required exclude={from} expectCurrency={txn.currency} />
        <Field label={t("payments.amount")} required hint={t("payments.transfer.amount_hint")}>
          <DecimalInput value={amount} onValueChange={setAmount} suffix={txn.currency} />
        </Field>
        <Field label={t("core.field.reason")} required hint={t("core.hint.reason_audited")}>
          <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} autoComplete="off" />
        </Field>
        <InlineError error={a.error} />
      </div>
    </Dialog>
  )
}

export function ConfirmTransferDialog({ open, onClose, txn, onDone }: { open: boolean; onClose: () => void; txn: TxnDetail; onDone: () => void }) {
  const { t } = useTexT()
  const toast = useToast()
  const a = useAction(open)
  const [reference, setReference] = useState("")
  const close = useEvent(() => {
    if (!a.pending) onClose()
  })
  useEffect(() => {
    if (open) setReference("")
  }, [open])
  const valid = reference.trim().length > 0
  const submit = async () => {
    if (!valid) return
    const r = await a.run(() => tex("payments", "mark_transfer_received", { transaction: txn.name, reference: reference.trim() }, { post: true }))
    if (r === undefined) return
    toast.success(t("payments.bank.done"))
    onDone()
    onClose()
  }
  return (
    <Dialog
      open={open}
      onClose={close}
      title={t("payments.bank.title")}
      description={t("payments.bank.desc")}
      footer={<Footer onCancel={close} onConfirm={submit} pending={a.pending} disabled={!valid} label={t("payments.bank.confirm")} />}
    >
      <div className="space-y-4">
        <p className="text-sm text-zinc-700">
          {t("payments.bank.expected")} <Money amount={txn.amount} currency={txn.currency} className="font-semibold" />
          {txn.booking ? ` · ${txn.booking}` : ""}
        </p>
        <Field label={t("payments.bank.reference")} required hint={t("payments.bank.reference_hint")}>
          <Input value={reference} onChange={(e) => setReference(e.target.value)} maxLength={140} autoComplete="off" data-autofocus />
        </Field>
        <Notice tone="warning">{t("payments.bank.check_amount")}</Notice>
        <InlineError error={a.error} />
      </div>
    </Dialog>
  )
}

type RefundOutcome = "Succeeded" | "Failed"

/** A refund the gateway never confirmed: staff checked it in the gateway's panel and record what it did (G-45). */
export function FinishRefundDialog({ open, onClose, txn, onDone }: { open: boolean; onClose: () => void; txn: TxnDetail; onDone: () => void }) {
  const { t } = useTexT()
  const toast = useToast()
  const a = useAction(open)
  const [outcome, setOutcome] = useState<RefundOutcome | "">("")
  const [reference, setReference] = useState("")
  const [reason, setReason] = useState("")
  const close = useEvent(() => {
    if (!a.pending) onClose()
  })
  useEffect(() => {
    if (!open) return
    setOutcome("")
    setReference("")
    setReason("")
  }, [open])
  const valid = Boolean(outcome) && reason.trim().length > 2
  const submit = async () => {
    if (!valid) return
    const r = await a.run(() =>
      tex<{ refund: string; status: string }>(
        "payments",
        "finish_refund",
        { refund: txn.name, outcome, reason: reason.trim(), reference: reference.trim() || undefined },
        { post: true },
      ),
    )
    if (!r) return
    toast.success(t("payments.finish.done", { name: r.refund }))
    onDone()
    onClose()
  }
  return (
    <Dialog
      open={open}
      onClose={close}
      title={t("payments.finish.title")}
      description={t("payments.finish.desc")}
      footer={<Footer onCancel={close} onConfirm={submit} pending={a.pending} disabled={!valid} label={t("payments.finish.confirm")} />}
    >
      <div className="space-y-4">
        <p className="text-sm text-zinc-700">
          {t("payments.finish.amount")} <Money amount={txn.amount} currency={txn.currency} className="font-semibold" />
        </p>
        <Segmented<RefundOutcome | "">
          label={t("payments.finish.outcome")}
          value={outcome}
          onChange={setOutcome}
          options={[
            { value: "Succeeded", label: t("payments.finish.succeeded") },
            { value: "Failed", label: t("payments.finish.failed") },
          ]}
        />
        <Notice tone="info">{t("payments.finish.effect")}</Notice>
        <Field label={t("payments.finish.reference")} hint={t("payments.finish.reference_hint")}>
          <Input value={reference} onChange={(e) => setReference(e.target.value)} maxLength={140} autoComplete="off" />
        </Field>
        <Field label={t("core.field.reason")} required hint={t("core.hint.reason_audited")}>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={500} />
        </Field>
        <InlineError error={a.error} />
      </div>
    </Dialog>
  )
}

/** A successful charge, or a Failed one whose capture TEX refused to count (the server reports it refundable). */
export const canRefund = (txn: TxnDetail) =>
  txn.txn_type === "Charge" && (txn.status === "Succeeded" || txn.status === "Failed") && !isZero(txn.refundable) && txn.provider !== "Manual" && txn.provider !== "Loyalty"
export const canAllocate = (txn: TxnDetail) => txn.txn_type === "Charge" && txn.status === "Succeeded" && !isZero(txn.unallocated)
export const canTransfer = (txn: TxnDetail) => txn.txn_type === "Charge" && txn.status === "Succeeded" && holdingBookings(txn).length > 0
export const canConfirmTransfer = (txn: TxnDetail) => txn.provider === "Bank Transfer" && txn.status === "Pending"
/** A refund still waiting for the gateway's answer (never confirmed, or left by a run that stopped). */
export const canFinishRefund = (txn: TxnDetail) => txn.txn_type === "Refund" && txn.status === "Pending"
/** Pending charges, and Failed or superseded (Cancelled) ones: a captured payment whose callback was lost can be recovered. */
export const canReverify = (txn: TxnDetail) =>
  txn.txn_type === "Charge" && txn.status !== "Succeeded" && (txn.provider === "iyzico" || txn.provider === "Sipay")
