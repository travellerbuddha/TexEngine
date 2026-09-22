import { useEffect, useRef, useState } from "react"
import { Copy, ExternalLink } from "lucide-react"
import { idempotencyKey } from "../../../lib/api"
import { isDecimal } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Button, DecimalInput, Dialog, Field, FormGrid, Input, InlineError, Notice, Select, useToast } from "../../../ui"
import { createPaymentLink } from "../lib/api"
import { copyText, isPositive } from "../lib/party"
import { asApiError } from "../lib/useBookingFlow"
import type { TexApiError } from "../../../lib/api"

/** payments.create_link for a booking (payment.link). The amount starts at the server's
 * due-now / balance figure; the agent may change it, the server validates it. */
export function PaymentLinkDialog({
  open,
  onClose,
  property,
  currency,
  defaultAmount,
  booking,
  reservation,
  guestName,
  guestEmail,
}: {
  open: boolean
  onClose: () => void
  property: string
  currency: string
  defaultAmount: string
  booking?: string
  reservation?: string
  guestName?: string
  guestEmail?: string
}) {
  const { t } = useTexT()
  const toast = useToast()
  const [amount, setAmount] = useState(defaultAmount)
  const [email, setEmail] = useState(guestEmail ?? "")
  const [hours, setHours] = useState("72")
  const [description, setDescription] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TexApiError>()
  const [url, setUrl] = useState<string | null>(null)
  const key = useRef("")

  useEffect(() => {
    if (!open) return
    setAmount(defaultAmount)
    setEmail(guestEmail ?? "")
    setHours("72")
    setDescription(t("crs.link.default_description", { ref: booking ?? reservation ?? "" }))
    setError(undefined)
    setUrl(null)
    key.current = idempotencyKey("plink")
  }, [open, defaultAmount, guestEmail, booking, reservation, t])

  const valid = isDecimal(amount) && isPositive(amount) && description.trim().length > 0
  const submit = async () => {
    setBusy(true)
    setError(undefined)
    try {
      const r = await createPaymentLink({
        property,
        amount,
        currency,
        description: description.trim(),
        expires_hours: Number(hours),
        booking,
        reservation,
        guest_name: guestName,
        guest_email: email.trim() || undefined,
        idempotency_key: key.current,
      })
      setUrl(r.url ?? null)
      toast.success(r.replay ? t("crs.link.replayed") : t("crs.link.created"))
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
      title={t("crs.link.title")}
      description={booking ? t("crs.link.for", { ref: booking }) : undefined}
      footer={
        url ? (
          <Button onClick={onClose}>{t("core.action.close")}</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={onClose} disabled={busy}>
              {t("core.action.cancel")}
            </Button>
            <Button onClick={submit} loading={busy} disabled={!valid}>
              {t("crs.link.create")}
            </Button>
          </>
        )
      }
    >
      {url ? (
        <div className="space-y-3">
          <Notice tone="success">{t("crs.link.ready")}</Notice>
          <Field label={t("crs.link.url")}>
            <Input id="crs-link-url" readOnly value={url} onFocus={(e) => e.currentTarget.select()} data-autofocus />
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              icon={<Copy className="size-4" aria-hidden />}
              onClick={async () => (await copyText(url)) && toast.success(t("core.action.copied"))}
            >
              {t("core.action.copy")}
            </Button>
            <a
              href={url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium text-tex-700 hover:bg-tex-50"
            >
              <ExternalLink className="size-4" aria-hidden />
              {t("crs.link.open")}
            </a>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <FormGrid cols={2}>
            <Field label={t("crs.link.amount")} required error={amount && !isPositive(amount) ? t("crs.link.amount_positive") : undefined}>
              <DecimalInput id="crs-link-amount" value={amount} onValueChange={setAmount} suffix={currency} data-autofocus />
            </Field>
            <Field label={t("crs.link.expires")}>
              <Select
                id="crs-link-expires"
                value={hours}
                onChange={(e) => setHours(e.target.value)}
                options={[24, 48, 72, 168].map((h) => ({ value: String(h), label: t("crs.link.hours", { count: h }) }))}
              />
            </Field>
          </FormGrid>
          <Field label={t("crs.link.email")} hint={t("crs.link.email_hint")}>
            <Input id="crs-link-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label={t("crs.link.description")} required>
            <Input id="crs-link-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <InlineError error={error} />
        </div>
      )}
    </Dialog>
  )
}
