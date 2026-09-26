import { useEffect, useState } from "react"
import { Check, Copy, KeyRound, Mail } from "lucide-react"
import { tex, useTexQuery } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { dateTime } from "../../../lib/format"
import { TEX_LANGS, useTexT } from "../../../i18n"
import { Button, Checkbox, DecimalInput, Dialog, Field, FormGrid, InlineError, Input, Money, Notice, Select, Textarea, useToast } from "../../../ui"
import { BookingPicker } from "../components/BookingPicker"
import { copyText, isPositiveAmount, useEvent, useIntentKey } from "../lib"
import type { BookingSummary, CreatedLink, MethodOption, PayLink } from "../types"

const EXPIRY = [24, 48, 72, 168, 336, 720] as const

/** Shows a bearer URL once, with copy. The URL is never stored by the UI. */
export function LinkUrlDialog({
  open,
  onClose,
  url,
  title,
  emailedTo,
  emailFailed,
  reissued,
  expiresAt,
  heldUntil,
}: {
  open: boolean
  onClose: () => void
  url: string
  title: string
  emailedTo?: string | null
  emailFailed?: boolean
  reissued?: boolean
  /** When the link stops working, as the server set it (B6). */
  expiresAt?: string | null
  /** A booking awaiting payment: its rooms are held until then, and the link expires then (B6). */
  heldUntil?: string | null
}) {
  const { t } = useTexT()
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (open) setCopied(false)
  }, [open, url])
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={t("payments.links.url_once")}
      footer={<Button onClick={onClose}>{t("core.action.close")}</Button>}
    >
      <div className="space-y-4">
        <Field label={t("payments.links.url")}>
          <Input readOnly value={url} onFocus={(e) => e.currentTarget.select()} className="font-mono text-xs" />
        </Field>
        <div className="flex flex-wrap gap-2">
          <Button
            icon={copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
            onClick={async () => setCopied(await copyText(url))}
            data-autofocus
          >
            {copied ? t("core.action.copied") : t("payments.links.copy")}
          </Button>
        </div>
        <p className="sr-only" aria-live="polite">
          {copied ? t("core.action.copied") : ""}
        </p>
        {emailedTo && (
          <Notice tone="success">
            <span className="inline-flex items-center gap-1.5">
              <Mail className="size-4" aria-hidden />
              {t("payments.links.emailed", { email: emailedTo })}
            </span>
          </Notice>
        )}
        {emailFailed && <Notice tone="warning">{t("payments.links.email_failed")}</Notice>}
        {expiresAt && (
          <Notice tone="info">
            {[t("payments.links.valid_until", { date: dateTime(expiresAt) }), heldUntil ? t("payments.links.rooms_held", { date: dateTime(heldUntil) }) : null].filter(Boolean).join(" ")}
          </Notice>
        )}
        {reissued && <Notice tone="warning">{t("payments.links.reissued_note")}</Notice>}
        <p className="flex items-start gap-1.5 text-xs text-zinc-500">
          <KeyRound className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {t("payments.links.bearer_note")}
        </p>
      </div>
    </Dialog>
  )
}

export function CreateLinkDialog({
  open,
  onClose,
  property,
  defaultCurrency,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  property: string
  defaultCurrency: string
  onCreated: (r: CreatedLink, emailTo: string | null) => void
}) {
  const { t, lang } = useTexT()
  const toast = useToast()
  const { boot } = useSession()
  const methods = useTexQuery<MethodOption[]>("payments", "methods", { property }, [property], open)
  const cardAccounts = (methods.data ?? []).filter((m) => m.method === "Card" && m.provider_account)
  const [amount, setAmount] = useState("")
  const [currency, setCurrency] = useState(defaultCurrency)
  const [description, setDescription] = useState("")
  const [expires, setExpires] = useState("72")
  const [account, setAccount] = useState("")
  const [booking, setBooking] = useState("")
  const [guestName, setGuestName] = useState("")
  const [guestEmail, setGuestEmail] = useState("")
  const [sendEmail, setSendEmail] = useState(false)
  const [emailLang, setEmailLang] = useState<string>(lang)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const key = useIntentKey("paylink", open)
  const close = useEvent(() => {
    if (!pending) onClose()
  })

  useEffect(() => {
    if (!open) return
    setAmount("")
    setCurrency(defaultCurrency)
    setDescription("")
    setExpires("72")
    setAccount("")
    setBooking("")
    setGuestName("")
    setGuestEmail("")
    setSendEmail(false)
    setEmailLang(lang)
    setError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, defaultCurrency])

  const onBooking = (b: string, s?: BookingSummary) => {
    setBooking(b)
    if (s) {
      setCurrency(s.currency)
      if (!amount && s.balance && !s.balance.startsWith("-") && !/^0*(\.0*)?$/.test(s.balance)) setAmount(s.balance)
      if (!guestName && s.booker_name) setGuestName(s.booker_name)
      if (!description) setDescription(t("payments.links.default_desc", { booking: b }))
    }
  }

  const emailOk = !guestEmail || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(guestEmail)
  const valid = isPositiveAmount(amount) && Boolean(currency) && description.trim().length > 0 && emailOk && (!sendEmail || Boolean(guestEmail))
  const submit = async () => {
    if (!valid) return
    setPending(true)
    setError(null)
    try {
      const r = await tex<CreatedLink>(
        "payments",
        "create_link",
        {
          property,
          amount,
          currency,
          description: description.trim(),
          expires_hours: Number(expires),
          provider_account: account || undefined,
          booking: booking || undefined,
          guest_name: guestName.trim() || undefined,
          guest_email: guestEmail.trim() || undefined,
          send_email: sendEmail && guestEmail ? 1 : 0,
          language: sendEmail && guestEmail ? emailLang : undefined,
          idempotency_key: key,
        },
        { post: true },
      )
      toast.success(r.replay ? t("payments.links.replay") : t("payments.links.created"))
      onCreated(r, sendEmail && guestEmail ? guestEmail.trim() : null)
      onClose()
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
      title={t("payments.links.create_title")}
      description={t("payments.links.create_desc")}
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={pending}>
            {t("core.action.cancel")}
          </Button>
          <Button loading={pending} disabled={!valid} onClick={submit}>
            {t("payments.links.create")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <FormGrid>
          <Field label={t("payments.amount")} required>
            <DecimalInput value={amount} onValueChange={setAmount} suffix={currency} data-autofocus />
          </Field>
          <Field label={t("payments.currency")} required hint={booking ? t("payments.links.currency_from_booking") : undefined}>
            <Select value={currency} disabled={Boolean(booking)} onChange={(e) => setCurrency(e.target.value)} options={boot.currencies.map((c) => ({ value: c, label: c }))} />
          </Field>
        </FormGrid>
        <Field label={t("payments.links.description")} required hint={t("payments.links.description_hint")}>
          <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} maxLength={500} />
        </Field>
        <FormGrid>
          <Field label={t("payments.links.expiry")} hint={booking ? t("payments.links.expiry_hint") : undefined}>
            <Select value={expires} onChange={(e) => setExpires(e.target.value)} options={EXPIRY.map((h) => ({ value: String(h), label: h < 168 ? t("payments.links.hours", { count: h }) : t("payments.links.days", { count: h / 24 }) }))} />
          </Field>
          <Field label={t("payments.links.account")} hint={t("payments.links.account_hint")}>
            <Select
              value={account}
              onChange={(e) => setAccount(e.target.value)}
              options={[
                { value: "", label: t("payments.links.account_auto") },
                ...cardAccounts.map((m) => ({ value: m.provider_account!, label: `${m.label}${m.sandbox ? ` (${t("payments.sandbox")})` : ""}` })),
              ]}
            />
          </Field>
        </FormGrid>
        <BookingPicker property={property} value={booking} onChange={onBooking} label={t("payments.links.booking")} />
        <FormGrid>
          <Field label={t("payments.links.guest_name")}>
            <Input value={guestName} onChange={(e) => setGuestName(e.target.value)} maxLength={140} autoComplete="off" />
          </Field>
          <Field label={t("payments.links.guest_email")} error={!emailOk ? t("payments.links.email_invalid") : undefined}>
            <Input type="email" value={guestEmail} onChange={(e) => setGuestEmail(e.target.value)} maxLength={140} autoComplete="off" />
          </Field>
        </FormGrid>
        <div className="flex flex-wrap items-end gap-3">
          <Checkbox checked={sendEmail} disabled={!guestEmail || !emailOk} onChange={(e) => setSendEmail(e.target.checked)} label={t("payments.links.send_email")} className="py-2" />
          {sendEmail && (
            <Field label={t("payments.links.email_language")} className="w-44">
              <Select value={emailLang} onChange={(e) => setEmailLang(e.target.value)} options={TEX_LANGS.map((l) => ({ value: l.code, label: l.label }))} />
            </Field>
          )}
        </div>
        <p className="text-xs text-zinc-500">{t("payments.links.transactional_note")}</p>
        <InlineError error={error} />
      </div>
    </Dialog>
  )
}

/** Rotates the token; the previous URL stops working immediately. */
export function ReissueDialog({
  link,
  onClose,
  onDone,
}: {
  link: PayLink | null
  onClose: () => void
  onDone: (url: string, link: PayLink, email: { to: string | null; failed: boolean }) => void
}) {
  const { t, lang } = useTexT()
  const [sendEmail, setSendEmail] = useState(false)
  const [emailLang, setEmailLang] = useState<string>(lang)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const close = useEvent(() => {
    if (!pending) onClose()
  })
  useEffect(() => {
    if (!link) return
    setError(null)
    setSendEmail(false)
    setEmailLang(lang)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [link])
  if (!link) return null
  const submit = async () => {
    setPending(true)
    setError(null)
    try {
      const email = sendEmail && Boolean(link.guest_email)
      const r = await tex<{ link: string; url: string; emailed?: boolean }>(
        "payments",
        "reissue_link",
        { name: link.name, send_email: email ? 1 : 0, language: email ? emailLang : undefined },
        { post: true },
      )
      onClose()
      onDone(r.url, link, { to: email && r.emailed !== false ? link.guest_email : null, failed: email && r.emailed === false })
    } catch (e) {
      setError(e as Error)
    } finally {
      setPending(false)
    }
  }
  return (
    <Dialog
      open
      onClose={close}
      title={t("payments.links.reissue_title")}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={pending}>
            {t("core.action.cancel")}
          </Button>
          <Button loading={pending} onClick={submit}>
            {t("payments.links.reissue_confirm")}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm text-zinc-700">
        <p>
          <span className="font-mono">{link.name}</span> · <Money amount={link.amount} currency={link.currency} />
          {link.expires_at ? ` · ${t("payments.links.expires", { date: dateTime(link.expires_at) })}` : ""}
        </p>
        <Notice tone="warning">{t("payments.links.reissue_warning")}</Notice>
        {link.guest_email && (
          <div className="space-y-3">
            <Checkbox checked={sendEmail} onChange={(e) => setSendEmail(e.target.checked)} label={t("payments.links.send_email_to", { email: link.guest_email })} />
            {sendEmail && (
              <Field label={t("payments.links.email_language")}>
                <Select value={emailLang} onChange={(e) => setEmailLang(e.target.value)} options={TEX_LANGS.map((l) => ({ value: l.code, label: l.label }))} />
              </Field>
            )}
          </div>
        )}
        <InlineError error={error} />
      </div>
    </Dialog>
  )
}
