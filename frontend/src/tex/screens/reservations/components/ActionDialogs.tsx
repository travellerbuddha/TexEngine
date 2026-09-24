import { useEffect, useState } from "react"
import { History } from "lucide-react"
import type { TexApiError } from "../../../lib/api"
import { date, isoDay } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Button, Checkbox, Dialog, Field, InlineError, Input, Money, Notice, Skeleton, Textarea, useToast } from "../../../ui"
import { cn } from "../../../../lib/utils"
import { Row } from "../../crs/components/controls"
import { penaltyText } from "../../crs/components/OfferParts"
import { PriceBreakdown } from "../../crs/components/PriceBreakdown"
import { cmpDecimal, isZero } from "../../crs/lib/party"
import { useServerClock } from "../../crs/lib/serverClock"
import { asApiError } from "../../crs/lib/useBookingFlow"
import { acknowledgeGuestChange, cancelReservation, cancellationPreview, resendConfirmation, simulate, type ResendResult } from "../lib/api"
import type { CancelPreview, CancelResult, ReservationDetail, Simulation } from "../lib/types"
import { localToServer } from "./ModifyDrawer"

/** "What would this stay have cost if sold on …?" — read-only (R-22). */
export function SimulatorDialog({ open, onClose, res, canCost }: { open: boolean; onClose: () => void; res: ReservationDetail; canCost: boolean }) {
  const { t } = useTexT()
  const clock = useServerClock()
  const [at, setAt] = useState("")
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<Simulation>()
  const [error, setError] = useState<TexApiError>()
  useEffect(() => {
    if (!open) return
    setResult(undefined)
    setError(undefined)
    // start one month before the original sale: a typical "sold earlier" question
    const base = res.sale_at ? res.sale_at.slice(0, 10) : clock.today()
    const d = new Date(`${base}T12:00:00`)
    d.setMonth(d.getMonth() - 1)
    setAt(`${isoDay(d)}T12:00`)
  }, [open, res.sale_at, clock])
  const run = async () => {
    if (!at) return
    setBusy(true)
    setError(undefined)
    try {
      setResult(await simulate(res.name, localToServer(at)))
    } catch (e) {
      setError(asApiError(e))
      setResult(undefined)
    } finally {
      setBusy(false)
    }
  }
  const s = result
  const dir = s?.difference ? cmpDecimal(s.difference, "0") : 0
  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={t("res.sim.title")}
      description={t("res.sim.subtitle")}
      footer={<Button variant="secondary" onClick={onClose}>{t("core.action.close")}</Button>}
    >
      <div className="space-y-4">
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            void run()
          }}
        >
          <Field label={t("res.sim.sale_at")} hint={t("res.basis.sale_at_hint", { tz: clock.tz ?? "—" })}>
            <Input id="sim-at" type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} data-autofocus />
          </Field>
          <Button type="submit" loading={busy} disabled={!at} icon={<History className="size-4" aria-hidden />}>
            {t("res.sim.run")}
          </Button>
        </form>
        <InlineError error={error} />
        {busy && !s && <Skeleton className="h-32 w-full" />}
        {s && (s.sellable === false || !s.simulated) ? (
          <Notice tone="warning" title={t("res.sim.not_sellable")}>
            {(s.reasons ?? []).map((r) => r.message).join("; ")}
          </Notice>
        ) : s && s.simulated && s.actual ? (
          <div className="space-y-3" aria-live="polite">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg border border-zinc-200 p-3">
                <p className="text-xs text-zinc-500">{t("res.sim.actual", { date: clock.label(s.actual.sale_at) })}</p>
                <p className="text-lg font-semibold">
                  <Money amount={s.actual.total} currency={s.actual.currency} />
                </p>
                <p className="text-xs text-zinc-500">{s.actual.version}</p>
              </div>
              <div className="rounded-lg border border-tex-200 bg-tex-50/40 p-3">
                <p className="text-xs text-zinc-500">{t("res.sim.simulated", { date: clock.label(s.simulated_sale_at) })}</p>
                <p className="text-lg font-semibold">
                  {s.simulated.sellable ? <Money amount={s.simulated.totals.total} currency={s.simulated.currency} /> : t("res.sim.not_sellable")}
                </p>
                <p className="text-xs text-zinc-500">{s.contract ? `${s.contract.code} · ${s.contract_version}` : s.contract_version}</p>
                {s.contract && s.contract.status_now !== "Active" && (
                  <p className="text-xs text-amber-700">
                    {t("res.sim.contract_now", { status: t(`rates.contract_status.${s.contract.status_now}`) })}
                  </p>
                )}
              </div>
              <div className={cn("rounded-lg border p-3", dir > 0 ? "border-amber-200 bg-amber-50" : dir < 0 ? "border-emerald-200 bg-emerald-50" : "border-zinc-200")}>
                <p className="text-xs text-zinc-500">{t("res.cmp.difference")}</p>
                <p className="text-lg font-semibold">
                  {s.difference === null || s.difference === undefined ? (
                    "—"
                  ) : isZero(s.difference) ? (
                    t("res.cmp.no_change")
                  ) : (
                    <Money amount={s.difference} currency={s.simulated.currency} signed />
                  )}
                </p>
                <p className="text-xs text-zinc-500">{t("res.sim.difference_hint")}</p>
              </div>
            </div>
            {s.simulated.sellable ? (
              <PriceBreakdown quote={s.simulated} canCost={canCost} showNightly={false} />
            ) : (
              <Notice tone="warning">{s.simulated.reasons.map((r) => r.message).join("; ")}</Notice>
            )}
            <p className="text-xs text-zinc-500">{t("res.sim.readonly")}</p>
          </div>
        ) : null}
      </div>
    </Dialog>
  )
}

function ruleText(t: (k: string, p?: Record<string, string | number>) => string, preview: CancelPreview) {
  const r = preview.basis.rule
  if (typeof r === "string") {
    if (r.startsWith("non-refundable")) return t("res.cancel.rule_nonref")
    if (r.startsWith("no policy")) return t("res.cancel.rule_none")
    if (r.startsWith("free cancellation")) return t("res.cancel.rule_free")
    return r
  }
  return r.days_before_arrival >= 9999
    ? t("crs.policy.rule_any", { penalty: penaltyText(t, r, preview.currency) })
    : t("crs.policy.rule", { days: r.days_before_arrival, penalty: penaltyText(t, r, preview.currency) })
}

/** Cancel with the server's penalty preview; waiving needs price.override (audited). */
export function CancelDialog({
  open,
  onClose,
  res,
  canWaive,
  onCancelled,
}: {
  open: boolean
  onClose: () => void
  res: ReservationDetail
  canWaive: boolean
  onCancelled: (r: CancelResult) => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const [preview, setPreview] = useState<CancelPreview>()
  const [previewError, setPreviewError] = useState<TexApiError>()
  const [waive, setWaive] = useState(false)
  const [reason, setReason] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TexApiError>()
  useEffect(() => {
    if (!open) return
    setPreview(undefined)
    setPreviewError(undefined)
    setWaive(false)
    setReason("")
    setError(undefined)
    let live = true
    cancellationPreview(res.name)
      .then((p) => live && setPreview(p))
      .catch((e) => live && setPreviewError(asApiError(e)))
    return () => {
      live = false
    }
  }, [open, res.name])
  const ok = reason.trim().length > 2 && Boolean(preview) && !busy
  const submit = async () => {
    setBusy(true)
    setError(undefined)
    try {
      const r = await cancelReservation(res.name, reason.trim(), waive)
      toast.success(t("res.cancel.done", { name: res.name }))
      onCancelled(r)
    } catch (e) {
      setError(asApiError(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog
      open={open}
      onClose={busy ? () => undefined : onClose}
      title={t("res.cancel.title", { name: res.name })}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {t("res.cancel.keep")}
          </Button>
          <Button variant="danger" onClick={() => void submit()} loading={busy} disabled={!ok}>
            {t("res.cancel.confirm")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-zinc-700">
          {t("res.cancel.body", { guest: res.guest?.full_name ?? "—", from: date(res.check_in), to: date(res.check_out) })}
        </p>
        <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2" aria-live="polite">
          {previewError ? (
            <p className="text-sm text-rose-700" role="alert">
              {previewError.message}
            </p>
          ) : !preview ? (
            <Skeleton className="h-10 w-full" />
          ) : (
            <>
              <Row label={t("res.cancel.total")} value={<Money amount={res.total} currency={res.currency} />} />
              <Row
                strong
                label={t("res.cancel.penalty")}
                value={
                  waive ? (
                    <span>
                      <Money amount={preview.penalty} currency={preview.currency} className="text-zinc-400 line-through" />{" "}
                      <Money amount="0" currency={preview.currency} />
                    </span>
                  ) : (
                    <Money amount={preview.penalty} currency={preview.currency} />
                  )
                }
              />
              <p className="mt-1 text-xs text-zinc-600">
                {ruleText(t, preview)} · {t("res.cancel.days_before", { count: preview.basis.days_before })}
              </p>
            </>
          )}
        </div>
        {canWaive && preview && !isZero(preview.penalty) && (
          <Checkbox
            className="items-start"
            label={
              <span>
                {t("res.cancel.waive")}
                <span className="block text-xs text-zinc-500">{t("res.cancel.waive_hint")}</span>
              </span>
            }
            checked={waive}
            onChange={(e) => setWaive(e.target.checked)}
          />
        )}
        <Field label={t("core.field.reason")} hint={t("core.hint.reason_audited")} required>
          <Textarea id="cancel-reason" value={reason} onChange={(e) => setReason(e.target.value)} data-autofocus />
        </Field>
        <InlineError error={error} />
      </div>
    </Dialog>
  )
}

/** Acknowledge a change the guest made through self-service (optional note, audited). */
export function AcknowledgeDialog({ open, onClose, res, onDone }: { open: boolean; onClose: () => void; res: ReservationDetail; onDone: () => void }) {
  const { t } = useTexT()
  const toast = useToast()
  const [note, setNote] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TexApiError>()
  useEffect(() => {
    if (open) {
      setNote("")
      setError(undefined)
    }
  }, [open])
  return (
    <Dialog
      open={open}
      onClose={busy ? () => undefined : onClose}
      size="sm"
      title={t("res.ack.title")}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {t("core.action.cancel")}
          </Button>
          <Button
            loading={busy}
            onClick={async () => {
              setBusy(true)
              setError(undefined)
              try {
                await acknowledgeGuestChange(res.name, note.trim() || undefined)
                toast.success(t("res.ack.done"))
                onDone()
              } catch (e) {
                setError(asApiError(e))
              } finally {
                setBusy(false)
              }
            }}
          >
            {t("res.ack.confirm")}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {res.guest_change_note && <p className="rounded bg-amber-50 px-2 py-1.5 text-sm whitespace-pre-line text-amber-900">{res.guest_change_note}</p>}
        <Field label={t("res.ack.note")} hint={t("core.hint.reason_audited")}>
          <Textarea id="ack-note" value={note} onChange={(e) => setNote(e.target.value)} data-autofocus />
        </Field>
        <InlineError error={error} />
      </div>
    </Dialog>
  )
}

/**
 * Re-send the booking e-mail (crs.resend_confirmation). Only a hash of the guest's manage
 * link is stored, so the e-mail carries a NEW link and the old one stops working — the
 * agent is told before confirming. The result says what happened, never more: "queued" (the
 * guest's timeline later shows Sent or Failed), or not queued — the link was replaced but no
 * e-mail went out.
 */
export function ResendConfirmationDialog({ open, onClose, booking }: { open: boolean; onClose: () => void; booking: string }) {
  const { t } = useTexT()
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TexApiError>()
  const [result, setResult] = useState<ResendResult>()
  useEffect(() => {
    if (open) {
      setError(undefined)
      setResult(undefined)
    }
  }, [open])
  return (
    <Dialog
      open={open}
      onClose={busy ? () => undefined : onClose}
      size="sm"
      title={t("res.resend.title")}
      description={booking}
      footer={
        result ? (
          <Button onClick={onClose}>{t("core.action.close")}</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={onClose} disabled={busy}>
              {t("core.action.cancel")}
            </Button>
            <Button
              loading={busy}
              onClick={async () => {
                setBusy(true)
                setError(undefined)
                try {
                  const r = await resendConfirmation(booking)
                  setResult(r)
                  if (r.queued) toast.success(t("res.resend.queued", { email: r.email }))
                } catch (e) {
                  setError(asApiError(e))
                } finally {
                  setBusy(false)
                }
              }}
            >
              {t("res.resend.confirm")}
            </Button>
          </>
        )
      }
    >
      {result ? (
        result.queued ? (
          <Notice tone="success" title={t("res.resend.queued", { email: result.email })}>
            {t("res.resend.queued_hint")} {t("res.resend.old_dead")}
          </Notice>
        ) : (
          <Notice tone="warning" title={t("res.resend.not_sent_title")}>
            {t("res.resend.not_sent", { email: result.email })}
          </Notice>
        )
      ) : (
        <div className="space-y-3 text-sm text-zinc-700">
          <p>{t("res.resend.body")}</p>
          <Notice tone="warning">{t("res.resend.warning")}</Notice>
          <InlineError error={error} />
        </div>
      )}
    </Dialog>
  )
}
