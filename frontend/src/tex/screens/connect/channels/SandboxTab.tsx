import { useEffect, useId, useMemo, useRef, useState } from "react"
import { FlaskConical, Plus, PlayCircle, Send, Shuffle } from "lucide-react"
import { tex, TexApiError, useTexMutation } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { addDays, isDecimal } from "../../../lib/format"
import { useSiteClock } from "../../../lib/siteDay"
import { useTexT } from "../../../i18n"
import { Button, CardBody, Field, FormGrid, InlineError, Input, Notice, Segmented, useToast } from "../../../ui"
import { SandboxRoomFields, type RoomErrors, type RoomForm } from "./SandboxRoomFields"
import type { ApplyResult, InboundEvent, Mapping, SandboxMessage, SandboxResult, TabProps } from "./types"

interface MsgForm {
  provider_ref: string
  status: InboundEvent
  channel_name: string
  first_name: string
  last_name: string
  email: string
  rooms: RoomForm[]
  /** next default line reference (L1, L2, …): only ever grows, so removing a room and
   * adding another never repeats a reference (Modified messages match rooms by it) */
  next_line: number
}

const ISO = /^\d{4}-\d{2}-\d{2}$/
let seq = 0

function randomRef() {
  const bytes = crypto.getRandomValues(new Uint8Array(4))
  return `SBX-${Array.from(bytes, (b) => b.toString(36).padStart(2, "0")).join("").toUpperCase().slice(0, 7)}`
}

/** A room arriving 30 days after the site's today (G-91). */
function newRoom(m: Mapping | undefined, currency: string, n: number, today: string): RoomForm {
  const arrive = addDays(today, 30)
  return {
    id: ++seq,
    room_code: m?.external_room_code ?? "",
    rate_code: m?.external_rate_code ?? "",
    check_in: arrive,
    check_out: addDays(arrive, 2),
    adults: "2",
    total: "",
    currency: m?.sell_currency || currency,
    line_ref: `L${n}`,
  }
}

/** The line reference a room is sent with (blank: its position, as the channel would). */
function lineRef(r: RoomForm, i: number) {
  return r.line_ref.trim() || `L${i + 1}`
}

/** Sandbox connections only: compose a booking message in TEX's neutral format and
 * receive it exactly as the channel's signed webhook would (no real channel involved). */
export function SandboxTab({ connection, conn, lookups, mappings, onChanged, goTo }: TabProps) {
  const { t } = useTexT()
  const toast = useToast()
  const { boot } = useSession()
  const clock = useSiteClock()
  const uid = useId()
  const rows = useMemo(() => (mappings.data ?? []).filter((m) => m.enabled), [mappings.data])
  const hotelCurrency = lookups.data?.currency ?? ""
  const [form, setForm] = useState<MsgForm>(() => ({
    provider_ref: randomRef(),
    status: "new",
    channel_name: "Sandbox OTA",
    first_name: "",
    last_name: "",
    email: "",
    rooms: [newRoom(rows[0], hotelCurrency, 1, clock.today())],
    next_line: 2,
  }))
  const [touched, setTouched] = useState(false)
  const [result, setResult] = useState<(SandboxResult & { ref: string; status: InboundEvent }) | null>(null)
  const [applying, setApplying] = useState(false)
  const send = useTexMutation<{ connection: string; message: SandboxMessage }, SandboxResult>("distribution", "sandbox_send")
  // a switched-off connection refuses every message (the webhook's "unknown connection")
  const off = !conn.enabled
  const errorRef = useRef<HTMLDivElement>(null)
  // the server's answer sits above the fields while Send is at the bottom: bring it into view
  useEffect(() => {
    if (send.error) errorRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [send.error])

  // mappings may arrive after the form was opened: prefill the untouched first room
  useEffect(() => {
    const m = rows[0]
    if (!m) return
    setForm((f) =>
      f.rooms.length === 1 && !f.rooms[0].room_code && !f.rooms[0].rate_code
        ? { ...f, rooms: [{ ...f.rooms[0], room_code: m.external_room_code, rate_code: m.external_rate_code, currency: m.sell_currency || f.rooms[0].currency }] }
        : f,
    )
  }, [rows])

  const roomCodes = useMemo(() => [...new Set(rows.map((m) => m.external_room_code))].sort(), [rows])
  const rateCodes = useMemo(() => {
    const forRooms = new Set(form.rooms.map((r) => r.room_code))
    const pick = rows.filter((m) => forRooms.has(m.external_room_code))
    return [...new Set((pick.length ? pick : rows).map((m) => m.external_rate_code))].sort()
  }, [rows, form.rooms])
  const currencies = useMemo(() => {
    const s = new Set<string>(boot.currencies ?? [])
    if (hotelCurrency) s.add(hotelCurrency)
    for (const m of rows) if (m.sell_currency) s.add(m.sell_currency)
    for (const r of form.rooms) if (r.currency) s.add(r.currency)
    return [...s].sort()
  }, [boot.currencies, hotelCurrency, rows, form.rooms])
  const mapped = (r: RoomForm) => rows.some((m) => m.external_room_code === r.room_code.trim() && m.external_rate_code === r.rate_code.trim())

  const cancelled = form.status === "cancelled"
  const errors = useMemo(() => {
    const req = t("connect.err.required")
    const top: Partial<Record<"provider_ref" | "email" | "rooms", string>> = {}
    if (!form.provider_ref.trim()) top.provider_ref = req
    if (form.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) top.email = t("connect.channels.sandbox.err_email")
    if (!cancelled && form.rooms.length === 0) top.rooms = t("connect.channels.sandbox.err_rooms")
    const ccys = new Set(form.rooms.map((r) => r.currency).filter(Boolean))
    if (!cancelled && ccys.size > 1) top.rooms = t("connect.channels.sandbox.err_currency_mix")
    // two rooms with one line reference: a later "Modified" would update one and cancel the other
    const refs = form.rooms.map((r, i) => lineRef(r, i))
    // a cancellation carries only the booking id: its rooms are neither checked nor sent
    const rooms: RoomErrors[] = form.rooms.map((r, i) => {
      if (cancelled) return {}
      const e: RoomErrors = {}
      if (refs.indexOf(refs[i]) !== i) e.line_ref = t("connect.channels.sandbox.err_line_ref")
      if (!r.room_code.trim()) e.room_code = req
      if (!r.rate_code.trim()) e.rate_code = req
      if (!ISO.test(r.check_in)) e.check_in = req
      if (!ISO.test(r.check_out)) e.check_out = req
      else if (ISO.test(r.check_in) && r.check_out <= r.check_in) e.check_out = t("connect.channels.sandbox.err_dates")
      if (!/^[1-9]$/.test(r.adults.trim())) e.adults = t("connect.channels.sandbox.err_adults")
      if (!isDecimal(r.total, 2) || r.total.trim().startsWith("-")) e.total = t("connect.channels.sandbox.err_total")
      if (!/^[A-Z]{3}$/.test(r.currency)) e.currency = req
      return e
    })
    const ok = Object.keys(top).length === 0 && rooms.every((e) => Object.keys(e).length === 0)
    return { top, rooms, ok }
  }, [form, cancelled, t])

  const setRoom = (id: number, patch: Partial<RoomForm>) => setForm((f) => ({ ...f, rooms: f.rooms.map((r) => (r.id === id ? { ...r, ...patch } : r)) }))
  // a mapped room code brings its rate code and currency along (still editable)
  const setRoomCode = (id: number, code: string) => {
    const m = rows.find((x) => x.external_room_code === code.trim())
    setForm((f) => ({
      ...f,
      rooms: f.rooms.map((r) => {
        if (r.id !== id) return r
        const next = { ...r, room_code: code }
        if (m && !rows.some((x) => x.external_room_code === m.external_room_code && x.external_rate_code === r.rate_code)) {
          next.rate_code = m.external_rate_code
          next.currency = m.sell_currency || r.currency
        }
        return next
      }),
    }))
  }

  const submit = async () => {
    setTouched(true)
    if (!errors.ok || off) return
    const message: SandboxMessage = {
      provider_ref: form.provider_ref.trim(),
      status: form.status,
      channel_name: form.channel_name.trim(),
      guest: { first_name: form.first_name.trim(), last_name: form.last_name.trim(), email: form.email.trim(), phone: "", country: "" },
      rooms: (cancelled ? [] : form.rooms).map((r, i) => ({
        room_code: r.room_code.trim(),
        rate_code: r.rate_code.trim(),
        check_in: r.check_in,
        check_out: r.check_out,
        adults: Number(r.adults.trim()),
        children_ages: [],
        total: r.total.trim(),
        currency: r.currency,
        line_ref: lineRef(r, i),
      })),
      notes: "",
    }
    try {
      const r = await send.run({ connection, message })
      setResult({ ...r, ref: message.provider_ref, status: message.status })
      onChanged()
    } catch {
      /* shown inline */
    }
  }

  const applyNow = async () => {
    setApplying(true)
    try {
      const r = await tex<ApplyResult>("distribution", "apply_now", { connection }, { post: true })
      const msg = t("connect.channels.inbound.applied", { applied: r.applied, failed: r.failed })
      if (r.failed) toast.error(msg)
      else toast.success(msg)
      onChanged()
      goTo("bookings")
    } catch (e) {
      toast.error((e as TexApiError).message)
    } finally {
      setApplying(false)
    }
  }

  const roomListId = `${uid}-rooms`
  const rateListId = `${uid}-rates`
  return (
    <CardBody className="space-y-5">
      <Notice
        tone="warning"
        title={
          <span className="inline-flex items-center gap-1.5">
            <FlaskConical className="size-4 shrink-0" aria-hidden />
            {t("connect.channels.sandbox.title")}
          </span>
        }
      >
        {t("connect.channels.sandbox.simulation")}
      </Notice>

      <form
        className="space-y-5"
        noValidate
        aria-label={t("connect.channels.sandbox.form")}
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <div ref={errorRef} className="scroll-mt-4 empty:hidden">
          <InlineError error={send.error} />
        </div>
        <fieldset className="space-y-3">
          <legend className="text-sm font-semibold text-zinc-900">{t("connect.channels.sandbox.booking")}</legend>
          <FormGrid>
            <Field label={t("connect.channels.sandbox.provider_ref")} required error={touched ? errors.top.provider_ref : undefined} hint={t("connect.channels.sandbox.provider_ref_hint")}>
              <Input value={form.provider_ref} onChange={(e) => setForm({ ...form, provider_ref: e.target.value })} maxLength={140} autoComplete="off" spellCheck={false} className="font-mono" />
            </Field>
            <Field label={t("connect.channels.sandbox.channel_name")} hint={t("connect.channels.sandbox.channel_name_hint")}>
              <Input value={form.channel_name} onChange={(e) => setForm({ ...form, channel_name: e.target.value })} maxLength={140} autoComplete="off" />
            </Field>
          </FormGrid>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="space-y-1.5">
              <span className="block text-sm font-medium text-zinc-800" aria-hidden>
                {t("connect.channels.sandbox.status")}
              </span>
              <Segmented<InboundEvent>
                label={t("connect.channels.sandbox.status")}
                value={form.status}
                onChange={(v) => setForm({ ...form, status: v })}
                options={(["new", "modified", "cancelled"] as const).map((v) => ({ value: v, label: t(`connect.channels.event.${v}`) }))}
              />
            </div>
            <Button variant="ghost" size="sm" icon={<Shuffle className="size-3.5" aria-hidden />} onClick={() => setForm({ ...form, provider_ref: randomRef(), status: "new" })}>
              {t("connect.channels.sandbox.new_ref")}
            </Button>
          </div>
          <p className="text-xs text-zinc-500">{t(`connect.channels.sandbox.status_hint.${form.status}`)}</p>
        </fieldset>

        <fieldset className="space-y-3">
          <legend className="text-sm font-semibold text-zinc-900">{t("connect.channels.sandbox.guest")}</legend>
          <FormGrid cols={3}>
            <Field label={t("connect.channels.sandbox.first_name")}>
              <Input value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} maxLength={140} autoComplete="off" />
            </Field>
            <Field label={t("connect.channels.sandbox.last_name")}>
              <Input value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} maxLength={140} autoComplete="off" />
            </Field>
            <Field label={t("connect.channels.sandbox.email")} error={touched ? errors.top.email : undefined}>
              <Input type="email" inputMode="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} autoComplete="off" />
            </Field>
          </FormGrid>
          <p className="text-xs text-zinc-500">{t("connect.channels.sandbox.guest_hint")}</p>
        </fieldset>

        <section className="space-y-3" aria-labelledby={`${uid}-rooms-title`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id={`${uid}-rooms-title`} className="text-sm font-semibold text-zinc-900">
              {t("connect.channels.sandbox.rooms")}
            </h3>
            {!cancelled && (
              <Button
                variant="secondary"
                size="sm"
                icon={<Plus className="size-3.5" aria-hidden />}
                onClick={() => setForm({ ...form, rooms: [...form.rooms, newRoom(rows[0], hotelCurrency, form.next_line, clock.today())], next_line: form.next_line + 1 })}
              >
                {t("connect.channels.sandbox.add_room")}
              </Button>
            )}
          </div>
          {touched && errors.top.rooms && (
            <p className="text-xs font-medium text-rose-700" role="alert">
              {errors.top.rooms}
            </p>
          )}
          {cancelled && <p className="text-xs text-zinc-500">{t("connect.channels.sandbox.cancel_rooms_hint")}</p>}
          <datalist id={roomListId}>
            {roomCodes.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
          <datalist id={rateListId}>
            {rateCodes.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
          {!cancelled &&
            form.rooms.map((r, i) => (
              <SandboxRoomFields
                key={r.id}
                room={r}
                index={i}
                errors={touched ? (errors.rooms[i] ?? {}) : {}}
                unmapped={!!r.room_code.trim() && !!r.rate_code.trim() && !mapped(r)}
                currencies={currencies}
                roomListId={roomListId}
                rateListId={rateListId}
                onChange={(patch) => setRoom(r.id, patch)}
                onRoomCode={(code) => setRoomCode(r.id, code)}
                onRemove={form.rooms.length > 1 ? () => setForm({ ...form, rooms: form.rooms.filter((x) => x.id !== r.id) }) : undefined}
              />
            ))}
        </section>

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" icon={<Send className="size-4" aria-hidden />} loading={send.pending} disabled={off}>
            {t("connect.channels.sandbox.send")}
          </Button>
          <p className="text-xs text-zinc-500">{off ? t("connect.channels.sandbox.send_off") : t("connect.channels.sandbox.send_hint")}</p>
        </div>
      </form>

      {result && (
        <Notice tone={result.received ? "success" : "info"} title={t("connect.channels.sandbox.result", { received: result.received, duplicates: result.duplicates })}>
          <p>{result.received ? t("connect.channels.sandbox.result_hint", { ref: result.ref }) : t("connect.channels.sandbox.result_duplicate", { ref: result.ref })}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" icon={<PlayCircle className="size-3.5" aria-hidden />} loading={applying} onClick={applyNow}>
              {t("connect.channels.inbound.apply_now")}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => goTo("bookings")}>
              {t("connect.channels.sandbox.open_log")}
            </Button>
          </div>
        </Notice>
      )}
    </CardBody>
  )
}
