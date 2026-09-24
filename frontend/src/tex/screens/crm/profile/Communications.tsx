import { useEffect, useMemo, useState } from "react"
import { ArrowDownLeft, ArrowUpRight, Mail, MessageCircle, MessagesSquare, NotebookPen, Phone, Smartphone } from "lucide-react"
import { useTexMutation } from "../../../lib/api"
import { date, dateTime } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, Dialog, EmptyState, Field, FormGrid, InlineError, Input, Notice, Select, Textarea, useToast, type Tone } from "../../../ui"
import { useEvent } from "../lib"
import type { CommChannel, CommDirection, Communication, ConsentBasis, Guest, Stay } from "../types"

const ICON: Record<CommChannel, typeof Mail> = { Email: Mail, SMS: Smartphone, WhatsApp: MessageCircle, Phone: Phone, Note: NotebookPen }
const CHANNELS: CommChannel[] = ["Phone", "Note", "Email", "SMS", "WhatsApp"]
const DIRECTIONS: CommDirection[] = ["Outbound", "Inbound", "Internal"]
const BASES: ConsentBasis[] = ["Transactional", "Marketing", "Legitimate Interest"]
// "Queued" is in the outgoing queue, not sent: never shown as a success (ADR-047)
const STATUS_TONE: Record<string, Tone> = { Queued: "info", Sent: "success", Delivered: "success", Failed: "danger" }
const CONSENT_OF: Partial<Record<CommChannel, keyof Guest>> = { Email: "tex_consent_email", SMS: "tex_consent_sms", WhatsApp: "tex_consent_whatsapp" }

export const channelKey = (c: string) => `crm.comm.channel.${c.toLowerCase()}`
export const directionKey = (d: string) => `crm.comm.direction.${d.toLowerCase()}`
export const basisKey = (b: string) => `crm.comm.basis.${b.toLowerCase().replace(/\s+/g, "_")}`

export function CommunicationsTimeline({ items }: { items: Communication[] }) {
  const { t } = useTexT()
  const [filter, setFilter] = useState<"" | CommChannel>("")
  const shown = filter ? items.filter((c) => c.channel === filter) : items
  if (!items.length) return <EmptyState icon={<MessagesSquare className="size-5" />} title={t("crm.comm.empty")} description={t("crm.comm.empty_hint")} />
  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <label className="flex items-center gap-2 text-xs text-zinc-600">
          {t("crm.comm.filter")}
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as CommChannel | "")}
            className="h-8 rounded-lg border border-zinc-300 bg-white px-2 text-xs text-zinc-900"
          >
            <option value="">{t("core.label.all")}</option>
            {CHANNELS.map((c) => (
              <option key={c} value={c}>
                {t(channelKey(c))}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ol className="relative space-y-4 border-l border-zinc-200 pl-5">
        {shown.map((c) => {
          const Icon = ICON[c.channel] ?? MessagesSquare
          return (
            <li key={c.name} className="relative">
              <span className="absolute top-0.5 -left-[1.9rem] grid size-5 place-items-center rounded-full bg-white text-zinc-500 ring-1 ring-zinc-200">
                <Icon className="size-3" aria-hidden />
              </span>
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-sm font-medium text-zinc-900">{c.subject || t(channelKey(c.channel))}</span>
                <Badge tone="neutral">
                  {c.direction === "Inbound" ? <ArrowDownLeft className="size-3" aria-hidden /> : c.direction === "Outbound" ? <ArrowUpRight className="size-3" aria-hidden /> : null}
                  {t(channelKey(c.channel))} · {t(directionKey(c.direction))}
                </Badge>
                <Badge tone={c.consent_basis === "Marketing" ? "brand" : "info"}>{t(basisKey(c.consent_basis))}</Badge>
                {c.status && c.status !== "Logged" && <Badge tone={STATUS_TONE[c.status] ?? "info"}>{t(`crm.comm.status.${c.status.toLowerCase()}`)}</Badge>}
              </div>
              {c.status === "Failed" && c.delivery_error && <p className="mt-1 text-xs text-rose-800">{t("crm.comm.delivery_error", { reason: c.delivery_error })}</p>}
              {c.body && <p className="mt-1 text-sm whitespace-pre-line text-zinc-700">{c.body}</p>}
              <p className="mt-1 text-xs text-zinc-500">
                {dateTime(c.sent_at || c.creation)} · {c.actor_name || t("crm.comms.system")}
                {c.booking ? ` · ${c.booking}` : ""}
              </p>
            </li>
          )
        })}
      </ol>
      {!shown.length && <p className="text-sm text-zinc-500">{t("crm.comm.none_for_filter")}</p>}
    </div>
  )
}

interface LogArgs extends Record<string, unknown> {
  guest: string
  channel: CommChannel
  direction: CommDirection
  subject?: string
  body?: string
  consent_basis: ConsentBasis
  booking?: string
  property?: string
}

export function LogCommunicationDialog({
  open,
  onClose,
  guest,
  stays,
  hotels,
  defaultHotel,
  onSaved,
}: {
  open: boolean
  onClose: () => void
  guest: Guest
  stays: Stay[]
  hotels: string[]
  defaultHotel?: string
  onSaved: () => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const [channel, setChannel] = useState<CommChannel>("Phone")
  const [direction, setDirection] = useState<CommDirection>("Outbound")
  const [basis, setBasis] = useState<ConsentBasis>("Transactional")
  const [subject, setSubject] = useState("")
  const [body, setBody] = useState("")
  const [booking, setBooking] = useState("")
  const [hotel, setHotel] = useState("")
  const log = useTexMutation<LogArgs, { name: string }>("crm", "log_communication")
  const close = useEvent(() => {
    if (!log.pending) onClose()
  })

  useEffect(() => {
    if (!open) return
    setChannel("Phone")
    setDirection("Outbound")
    setBasis("Transactional")
    setSubject("")
    setBody("")
    setBooking("")
    setHotel(defaultHotel && hotels.includes(defaultHotel) ? defaultHotel : hotels[0] ?? "")
    log.clearError()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (channel === "Note") setDirection("Internal")
    else if (direction === "Internal") setDirection("Outbound")
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel])

  const bookings = useMemo(() => {
    const seen = new Map<string, Stay>()
    for (const s of stays) if (s.tex_booking && !seen.has(s.tex_booking) && (!hotel || s.property === hotel)) seen.set(s.tex_booking, s)
    return [...seen.values()]
  }, [stays, hotel])

  const consentField = CONSENT_OF[channel]
  const marketingBlocked = basis === "Marketing" && direction === "Outbound" && consentField !== undefined && !guest[consentField]
  const bodyRequired = channel === "Note"
  const valid = !marketingBlocked && (!bodyRequired || body.trim().length > 0) && (subject.trim() || body.trim())

  const submit = async () => {
    if (!valid) return
    try {
      await log.run({
        guest: guest.name,
        channel,
        direction,
        consent_basis: basis,
        subject: subject.trim() || undefined,
        body: body.trim() || undefined,
        booking: booking || undefined,
        property: hotel || undefined,
      })
      toast.success(t("crm.comm.logged"))
      onSaved()
      onClose()
    } catch {
      /* inline */
    }
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title={t("crm.comm.log_title")}
      description={t("crm.comm.log_desc")}
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={log.pending}>
            {t("core.action.cancel")}
          </Button>
          <Button loading={log.pending} disabled={!valid} onClick={submit}>
            {t("crm.comm.save")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <FormGrid cols={3}>
          <Field label={t("crm.comm.channel")}>
            <Select value={channel} onChange={(e) => setChannel(e.target.value as CommChannel)} options={CHANNELS.map((c) => ({ value: c, label: t(channelKey(c)) }))} data-autofocus />
          </Field>
          <Field label={t("crm.comm.direction")}>
            <Select
              value={direction}
              onChange={(e) => setDirection(e.target.value as CommDirection)}
              options={DIRECTIONS.map((d) => ({ value: d, label: t(directionKey(d)), disabled: channel === "Note" ? d !== "Internal" : d === "Internal" }))}
            />
          </Field>
          <Field label={t("crm.comm.basis")} hint={t("crm.comm.basis_hint")}>
            <Select value={basis} onChange={(e) => setBasis(e.target.value as ConsentBasis)} options={BASES.map((b) => ({ value: b, label: t(basisKey(b)) }))} />
          </Field>
        </FormGrid>
        {marketingBlocked && <Notice tone="danger">{t("crm.comm.no_consent", { channel: t(channelKey(channel)) })}</Notice>}
        <Field label={t("crm.comm.subject")}>
          <Input value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={140} autoComplete="off" />
        </Field>
        <Field label={t("crm.comm.body")} required={bodyRequired} hint={t("crm.comm.body_hint")}>
          <Textarea value={body} onChange={(e) => setBody(e.target.value)} rows={5} maxLength={5000} />
        </Field>
        <FormGrid>
          {hotels.length > 1 && (
            <Field label={t("crm.comm.hotel")}>
              <Select value={hotel} onChange={(e) => setHotel(e.target.value)} options={hotels.map((h) => ({ value: h, label: h }))} />
            </Field>
          )}
          <Field label={t("crm.comm.booking")}>
            <Select
              value={booking}
              onChange={(e) => setBooking(e.target.value)}
              placeholder={t("crm.comm.no_booking")}
              options={bookings.map((s) => ({ value: s.tex_booking!, label: `${s.tex_booking} · ${date(s.check_in_date)}` }))}
            />
          </Field>
        </FormGrid>
        <InlineError error={log.error} />
      </div>
    </Dialog>
  )
}
