import { useEffect, useRef, useState } from "react"
import { Copy, ExternalLink } from "lucide-react"
import { idempotencyKey } from "../../../lib/api"
import { isDecimal } from "../../../lib/format"
import { TEX_LANGS, useTexT } from "../../../i18n"
import { Button, Checkbox, DecimalInput, Dialog, Field, FormGrid, Input, InlineError, Notice, Select, useToast } from "../../../ui"
import { createPaymentLink, reissuePaymentLink, type PaymentLinkResult } from "../lib/api"
import { copyText, isPositive } from "../lib/party"
import { asApiError } from "../lib/useBookingFlow"
import type { TexApiError } from "../../../lib/api"

/** The one-time URL the server returned (it is never stored, so show it now). */
function LinkResult({ result, onReissue }: { result: PaymentLinkResult; onReissue?: () => void }) {
  const { t } = useTexT()
  const toast = useToast()
  if (!result.url)
    return (
      <div className="space-y-3">
        <Notice tone="info">{t("crs.link.replay_no_url")}</Notice>
        {onReissue && (
          <Button variant="secondary" onClick={onReissue}>
            {t("crs.link.reissue")}
          </Button>
        )}
      </div>
    )
  const url = result.url
  return (
    <div className="space-y-3">
      <Notice tone="success">{result.emailed ? t("crs.link.ready_emailed") : t("crs.link.ready")}</Notice>
      <Field label={t("crs.link.url")} hint={t("crs.link.url_once")}>
        <Input id="crs-link-url" readOnly value={url} onFocus={(e) => e.currentTarget.select()} data-autofocus />
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" icon={<Copy className="size-4" aria-hidden />} onClick={async () => (await copyText(url)) && toast.success(t("core.action.copied"))}>
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
  )
}

function useLangDefault() {
  const { lang } = useTexT()
  return TEX_LANGS.some((l) => l.code === lang) ? lang : "en"
}

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
  guestLanguage,
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
  guestLanguage?: string
}) {
  const { t } = useTexT()
  const toast = useToast()
  const uiLang = useLangDefault()
  const [amount, setAmount] = useState(defaultAmount)
  const [email, setEmail] = useState(guestEmail ?? "")
  const [sendEmail, setSendEmail] = useState(Boolean(guestEmail))
  const [language, setLanguage] = useState(guestLanguage ?? uiLang)
  const [hours, setHours] = useState("72")
  const [description, setDescription] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TexApiError>()
  const [result, setResult] = useState<PaymentLinkResult | null>(null)
  const key = useRef("")

  useEffect(() => {
    if (!open) return
    setAmount(defaultAmount)
    setEmail(guestEmail ?? "")
    setSendEmail(Boolean(guestEmail))
    setLanguage(guestLanguage && TEX_LANGS.some((l) => l.code === guestLanguage) ? guestLanguage : uiLang)
    setHours("72")
    setDescription(t("crs.link.default_description", { ref: booking ?? reservation ?? "" }))
    setError(undefined)
    setResult(null)
    key.current = idempotencyKey("plink")
  }, [open, defaultAmount, guestEmail, guestLanguage, uiLang, booking, reservation, t])

  const valid = isDecimal(amount) && isPositive(amount) && description.trim().length > 0 && (!sendEmail || email.trim().includes("@"))
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
        send_email: sendEmail && email.trim() ? 1 : 0,
        language,
      })
      setResult(r)
      toast.success(r.replay ? t("crs.link.replayed") : t("crs.link.created"))
    } catch (e) {
      setError(asApiError(e))
    } finally {
      setBusy(false)
    }
  }
  const reissue = async () => {
    if (!result?.link) return
    setBusy(true)
    setError(undefined)
    try {
      setResult(await reissuePaymentLink(result.link, sendEmail && email.trim() ? 1 : 0, language))
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
        result ? (
          <Button onClick={onClose}>{t("core.action.close")}</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={onClose} disabled={busy}>
              {t("core.action.cancel")}
            </Button>
            <Button onClick={submit} loading={busy} disabled={!valid}>
              {sendEmail && email.trim() ? t("crs.link.create_send") : t("crs.link.create")}
            </Button>
          </>
        )
      }
    >
      {result ? (
        <div className="space-y-3">
          <LinkResult result={result} onReissue={() => void reissue()} />
          <InlineError error={error} />
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
          <Field label={t("crs.link.description")} required>
            <Input id="crs-link-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <FormGrid cols={2}>
            <Field label={t("crs.link.email")} hint={t("crs.link.email_hint")}>
              <Input id="crs-link-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label={t("crs.guest.language")}>
              <Select id="crs-link-lang" value={language} onChange={(e) => setLanguage(e.target.value)} options={TEX_LANGS.map((l) => ({ value: l.code, label: l.label }))} />
            </Field>
          </FormGrid>
          <Checkbox label={t("crs.link.send_email")} checked={sendEmail} disabled={!email.trim()} onChange={(e) => setSendEmail(e.target.checked)} />
          <InlineError error={error} />
        </div>
      )}
    </Dialog>
  )
}

/** Rotate the token of an open link (the old URL stops working) and show the new URL once. */
export function ReissueLinkDialog({
  open,
  onClose,
  link,
  guestEmail,
  guestLanguage,
}: {
  open: boolean
  onClose: () => void
  link: string | null
  guestEmail?: string
  guestLanguage?: string
}) {
  const { t } = useTexT()
  const uiLang = useLangDefault()
  const [sendEmail, setSendEmail] = useState(Boolean(guestEmail))
  const [language, setLanguage] = useState(guestLanguage ?? uiLang)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TexApiError>()
  const [result, setResult] = useState<PaymentLinkResult | null>(null)
  useEffect(() => {
    if (!open) return
    setSendEmail(Boolean(guestEmail))
    setLanguage(guestLanguage && TEX_LANGS.some((l) => l.code === guestLanguage) ? guestLanguage : uiLang)
    setError(undefined)
    setResult(null)
  }, [open, guestEmail, guestLanguage, uiLang])
  return (
    <Dialog
      open={open && Boolean(link)}
      onClose={busy ? () => undefined : onClose}
      title={t("crs.link.reissue_title", { name: link ?? "" })}
      description={t("crs.link.reissue_hint")}
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
                if (!link) return
                setBusy(true)
                setError(undefined)
                try {
                  setResult(await reissuePaymentLink(link, sendEmail ? 1 : 0, language))
                } catch (e) {
                  setError(asApiError(e))
                } finally {
                  setBusy(false)
                }
              }}
            >
              {t("crs.link.reissue")}
            </Button>
          </>
        )
      }
    >
      {result ? (
        <LinkResult result={result} />
      ) : (
        <div className="space-y-3">
          {guestEmail && <Checkbox label={t("crs.link.send_email_to", { email: guestEmail })} checked={sendEmail} onChange={(e) => setSendEmail(e.target.checked)} />}
          <Field label={t("crs.guest.language")}>
            <Select id="crs-reissue-lang" value={language} onChange={(e) => setLanguage(e.target.value)} options={TEX_LANGS.map((l) => ({ value: l.code, label: l.label }))} />
          </Field>
          <InlineError error={error} />
        </div>
      )}
    </Dialog>
  )
}
