import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { Award, Gift, SlidersHorizontal, UserMinus, UserPlus } from "lucide-react"
import { tex, useTexMutation, useTexQuery, type TexModule } from "../../../lib/api"
import { useProperty, useSession } from "../../../lib/session"
import { date, month, num, pct } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, Checkbox, DataTable, Dialog, EmptyState, Field, InlineError, Input, Money, Notice, Select, statusTone, useToast } from "../../../ui"
import { isInteger, useEvent, useIntentKey } from "../lib"
import { WebSessions } from "./WebSessions"
import type { Guest, LoyaltyAccount, LoyaltyEntry, LoyaltyMembership, LoyaltyProgramInfo, Stay } from "../types"

/** Our optional helper module (kamra/tex/api/ui_backoffice_crm_payments.py). */
export const UI_MODULE: TexModule = "ui_backoffice_crm_payments"

const entryKey = (e: string) => `crm.loyalty.entry.${e.toLowerCase()}`
const statusKey = (s: string) => `crm.loyalty.status.${s.toLowerCase()}`

export function LoyaltyPanel({
  guest,
  accounts,
  stays,
  hotels,
  canEdit,
  onChanged,
}: {
  guest: Guest
  accounts: LoyaltyAccount[]
  stays: Stay[]
  hotels: string[]
  canEdit: boolean
  onChanged: () => void
}) {
  const { t } = useTexT()
  const { can } = useSession()
  const current = useProperty()
  const [adjust, setAdjust] = useState<string | null>(null)
  const [redeem, setRedeem] = useState(false)
  const [membership, setMembership] = useState<{ program: string; mode: "join" | "leave" } | null>(null)
  // programs this guest can collect in (also when the ledger is still empty)
  const programs = useTexQuery<LoyaltyProgramInfo[]>(UI_MODULE, "loyalty_programs", { guest: guest.name }, [guest.name])
  const programOptions = useMemo(() => {
    const m = new Map<string, string>()
    for (const a of accounts) m.set(a.program, a.program_name)
    for (const p of programs.data ?? []) m.set(p.program, p.program_name)
    return [...m.entries()].map(([value, label]) => ({ value, label }))
  }, [accounts, programs.data])
  const redeemable = stays.some((s) => s.tex_booking && s.status !== "Cancelled" && can("payment.link", s.property))
  const closeAdjust = useEvent(() => setAdjust(null))
  const closeRedeem = useEvent(() => setRedeem(false))
  const closeMembership = useEvent(() => setMembership(null))
  // the hotels a membership or an adjustment can be made for: the program's own, or its hotels the user sees the guest
  // through (a hotel group's program; C-04 review round 1)
  const programHotels: ProgramHotels = Object.fromEntries(
    (programs.data ?? []).map((p) => [p.program, { own: p.program_property ?? null, hotels: p.hotels ?? [p.property] }]),
  )
  // memberships of the programs the guest can collect in now (enabled; a disabled one has no member prices)
  const memberPrograms = (programs.data ?? []).map((p) => ({ value: p.program, label: p.program_name }))

  const actions = (
    <div className="flex flex-wrap gap-2">
      {canEdit && programOptions.length > 0 && (
        <Button variant="secondary" size="sm" icon={<SlidersHorizontal className="size-4" aria-hidden />} onClick={() => setAdjust(programOptions[0].value)}>
          {t("crm.loyalty.adjust")}
        </Button>
      )}
      {redeemable && accounts.some((a) => a.available > 0) && (
        <Button variant="secondary" size="sm" icon={<Gift className="size-4" aria-hidden />} onClick={() => setRedeem(true)}>
          {t("crm.loyalty.redeem")}
        </Button>
      )}
    </div>
  )

  return (
    <div className="space-y-4">
      {memberPrograms.length > 0 && (
        <Memberships programs={memberPrograms} accounts={accounts} canEdit={canEdit} onAct={(program, mode) => setMembership({ program, mode })} />
      )}
      {!accounts.length ? (
        <EmptyState
          icon={<Award className="size-5" />}
          title={t("crm.loyalty.empty")}
          description={programOptions.length ? t("crm.loyalty.empty_hint") : t("crm.loyalty.no_program")}
          action={canEdit && programOptions.length > 0 ? actions : undefined}
        />
      ) : (
        <>
          <div className="flex justify-end">{actions}</div>
          {accounts.map((a) => (
            <section key={a.program} aria-label={a.program_name} className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-semibold text-zinc-900">{a.program_name}</h3>
                {a.tier && (
                  <Badge tone="brand">
                    <Award className="size-3" aria-hidden />
                    {t("crm.loyalty.tier", { tier: a.tier })}
                  </Badge>
                )}
              </div>
              <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div className="rounded-lg border border-zinc-200 p-3">
                  <dt className="text-xs text-zinc-500">{t("crm.loyalty.available")}</dt>
                  <dd className="text-xl font-semibold text-zinc-950 tabular-nums">{num(a.available)}</dd>
                </div>
                <div className="rounded-lg border border-zinc-200 p-3">
                  <dt className="text-xs text-zinc-500">{t("crm.loyalty.pending")}</dt>
                  <dd className="text-xl font-semibold text-zinc-950 tabular-nums">{num(a.pending)}</dd>
                </div>
                <div className="rounded-lg border border-zinc-200 p-3">
                  <dt className="text-xs text-zinc-500">{t("crm.loyalty.lifetime")}</dt>
                  <dd className="text-xl font-semibold text-zinc-950 tabular-nums">{num(a.lifetime_earned)}</dd>
                </div>
                <div className="rounded-lg border border-zinc-200 p-3">
                  <dt className="text-xs text-zinc-500">{t("crm.loyalty.value")}</dt>
                  <dd className="text-xl font-semibold text-zinc-950">
                    <Money amount={a.value} currency={a.currency} />
                  </dd>
                </div>
              </dl>
              {!!a.debt && a.debt > 0 && <Notice tone="warning">{t("crm.loyalty.debt", { points: num(a.debt) })}</Notice>}
              <div className="rounded-lg border border-zinc-200">
                <DataTable<LoyaltyEntry>
                  dense
                  caption={t("crm.loyalty.ledger_caption", { program: a.program_name })}
                  rows={a.entries}
                  rowKey={(e) => e.name}
                  empty={<EmptyState title={t("crm.loyalty.no_entries")} />}
                  columns={[
                    // another hotel's entry: the month only (ADR-056 second review)
                    { key: "creation", header: t("crm.loyalty.col.date"), cell: (e) => (e.other_hotel ? month(e.creation) : date(e.creation)) },
                    { key: "type", header: t("crm.loyalty.col.type"), cell: (e) => t(entryKey(e.entry_type)) },
                    {
                      key: "points",
                      header: t("crm.loyalty.col.points"),
                      align: "right",
                      cell: (e) => (
                        <span className={e.points < 0 ? "text-rose-700" : "text-emerald-700"}>
                          {e.points > 0 ? "+" : ""}
                          {num(e.points)}
                        </span>
                      ),
                    },
                    { key: "status", header: t("crm.loyalty.col.status"), cell: (e) => <Badge tone={e.status === "Available" ? "success" : e.status === "Pending" ? "warning" : statusTone(e.status)}>{t(statusKey(e.status))}</Badge> },
                    {
                      key: "booking",
                      header: t("crm.loyalty.col.booking"),
                      hideBelow: "md",
                      // a booking at another hotel of a shared program stays with that hotel (ADR-056)
                      cell: (e) => (e.other_hotel ? <span className="text-xs text-zinc-500 italic">{t("crm.loyalty.other_hotel")}</span> : e.booking || "—"),
                    },
                    {
                      key: "dates",
                      header: t("crm.loyalty.col.dates"),
                      hideBelow: "lg",
                      cell: (e) =>
                        e.status === "Pending" && e.available_on
                          ? t("crm.loyalty.available_on", { date: date(e.available_on) })
                          : e.expires_on
                            ? t("crm.loyalty.expires_on", { date: date(e.expires_on) })
                            : "—",
                    },
                    { key: "reason", header: t("crm.loyalty.col.reason"), hideBelow: "md", cell: (e) => <span className="line-clamp-2 text-xs text-zinc-600">{e.reason || "—"}</span> },
                  ]}
                />
              </div>
            </section>
          ))}
        </>
      )}
      <WebSessions guest={guest.name} canEdit={canEdit} />
      <AdjustDialog
        open={adjust !== null}
        program={adjust ?? ""}
        programs={programOptions}
        programHotels={programHotels}
        hotels={hotels.filter((h) => can("crm.edit", h))}
        defaultHotel={current}
        accounts={accounts}
        guest={guest.name}
        onClose={closeAdjust}
        onDone={onChanged}
      />
      <MembershipDialog
        open={membership !== null}
        mode={membership?.mode ?? "join"}
        program={membership?.program ?? ""}
        programName={memberPrograms.find((p) => p.value === membership?.program)?.label ?? ""}
        blocked={Boolean(accounts.find((a) => a.program === membership?.program)?.membership?.rejoin_blocked)}
        programHotels={programHotels}
        hotels={hotels.filter((h) => can("crm.edit", h))}
        defaultHotel={current}
        guest={guest.name}
        onClose={closeMembership}
        onDone={onChanged}
      />
      <RedeemDialog
        open={redeem}
        guest={guest.name}
        stays={stays.filter((s) => s.tex_booking && s.status !== "Cancelled" && can("payment.link", s.property) && hotels.includes(s.property))}
        programs={programs.data ?? []}
        accounts={accounts}
        onClose={closeRedeem}
        onDone={onChanged}
      />
    </div>
  )
}

/** program → its own hotel (none for a hotel group's program) and its hotels the user sees the guest through */
type ProgramHotels = Record<string, { own: string | null; hotels: string[] }>

/** The hotels a membership or an adjustment of `program` can be made for: the program's own hotel, else those of
 * its hotels where the user may edit the guest (`editable`). Not listed (loading): every hotel the user may edit. */
function hotelChoices(programHotels: ProgramHotels, program: string, editable: string[]): string[] {
  const p = programHotels[program]
  if (!p) return editable
  return p.own ? [p.own] : p.hotels.filter((h) => editable.includes(h))
}

/** The guest's membership of each program (C-04, ADR-077): a member gets its members-only prices. Staff who may
 * edit the guest join them (with the guest's word, audited) or end the membership with a reason. */
function Memberships({
  programs,
  accounts,
  canEdit,
  onAct,
}: {
  programs: { value: string; label: string }[]
  accounts: LoyaltyAccount[]
  canEdit: boolean
  onAct: (program: string, mode: "join" | "leave") => void
}) {
  const { t } = useTexT()
  return (
    <ul aria-label={t("crm.loyalty.member.title")} className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
      {programs.map((p) => {
        const acc = accounts.find((a) => a.program === p.value)
        const member = Boolean(acc?.member)
        return (
          <li key={p.value} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
            <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm">
              <span className="font-medium text-zinc-900">{p.label}</span>
              <MemberBadge member={member} membership={acc?.membership} />
            </div>
            {canEdit &&
              (member ? (
                <Button variant="secondary" size="sm" icon={<UserMinus className="size-4" aria-hidden />} onClick={() => onAct(p.value, "leave")}>
                  {t("crm.loyalty.member.leave")}
                </Button>
              ) : (
                <Button variant="secondary" size="sm" icon={<UserPlus className="size-4" aria-hidden />} onClick={() => onAct(p.value, "join")}>
                  {t("crm.loyalty.member.join")}
                </Button>
              ))}
          </li>
        )
      })}
    </ul>
  )
}

function MemberBadge({ member, membership }: { member: boolean; membership?: LoyaltyMembership | null }) {
  const { t } = useTexT()
  // another hotel's membership of a shared program: when, by month only (ADR-056)
  const when = (d: string | null) => (d ? (membership?.other_hotel ? month(d) : date(d)) : "")
  if (member)
    return (
      <>
        <Badge tone="success">{t("crm.loyalty.member.yes")}</Badge>
        <span className="text-xs text-zinc-500">
          {membership?.joined_at ? t("crm.loyalty.member.since", { date: when(membership.joined_at) }) : t("crm.loyalty.member.by_stays")}
        </span>
      </>
    )
  if (membership?.status === "Left")
    return (
      <>
        <Badge tone="neutral">{t("crm.loyalty.member.left")}</Badge>
        {membership.left_at && <span className="text-xs text-zinc-500">{t("crm.loyalty.member.left_on", { date: when(membership.left_at) })}</span>}
        {membership.rejoin_blocked && <Badge tone="warning">{t("crm.loyalty.member.blocked")}</Badge>}
      </>
    )
  return <Badge tone="neutral">{t("crm.loyalty.member.no")}</Badge>
}

function MembershipDialog({
  open,
  mode,
  program,
  programName,
  blocked,
  programHotels,
  hotels,
  defaultHotel,
  guest,
  onClose,
  onDone,
}: {
  open: boolean
  mode: "join" | "leave"
  program: string
  programName: string
  /** staff blocked a rejoin on the web (C-04h): joining the guest here lifts it */
  blocked: boolean
  programHotels: ProgramHotels
  /** the hotels through which the user may edit this guest */
  hotels: string[]
  defaultHotel: string | null | undefined
  guest: string
  onClose: () => void
  onDone: () => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const [reason, setReason] = useState("")
  const [block, setBlock] = useState(false)
  const [hotel, setHotel] = useState("")
  // a membership is made at one hotel of the program, whose staff read it in full (as an adjustment, ADR-056)
  const hotelOptions = hotelChoices(programHotels, program, hotels)
  const chosenHotel = hotelOptions.includes(hotel) ? hotel : hotelOptions.length === 1 ? hotelOptions[0] : ""
  const m = useTexMutation<{ guest: string; program: string; reason?: string; block_rejoin?: 0 | 1; property?: string }, { name: string; status: string }>(
    "crm",
    mode === "join" ? "loyalty_join" : "loyalty_leave",
  )
  const close = useEvent(() => {
    if (!m.pending) onClose()
  })
  useEffect(() => {
    if (open) {
      setReason("")
      setBlock(false)
      setHotel(defaultHotel && hotels.includes(defaultHotel) ? defaultHotel : "")
      m.clearError()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  const valid = Boolean(program) && (Boolean(chosenHotel) || hotelOptions.length === 0) && (mode === "join" || reason.trim().length > 2)
  const submit = async () => {
    if (!valid) return
    try {
      await m.run({
        guest,
        program,
        ...(mode === "leave" ? { reason: reason.trim(), block_rejoin: block ? 1 : 0 } : {}),
        ...(chosenHotel ? { property: chosenHotel } : {}),
      })
      toast.success(t(mode === "join" ? "crm.loyalty.member.joined" : "crm.loyalty.member.ended", { program: programName }))
      onDone()
      onClose()
    } catch {
      /* inline */
    }
  }
  return (
    <Dialog
      open={open}
      onClose={close}
      title={t(mode === "join" ? "crm.loyalty.member.join_title" : "crm.loyalty.member.leave_title", { program: programName })}
      description={t(mode === "join" ? "crm.loyalty.member.join_desc" : "crm.loyalty.member.leave_desc")}
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={m.pending}>
            {t("core.action.cancel")}
          </Button>
          <Button loading={m.pending} disabled={!valid} onClick={submit} variant={mode === "leave" ? "danger" : undefined}>
            {t(mode === "join" ? "crm.loyalty.member.join" : "crm.loyalty.member.leave")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {hotelOptions.length > 1 && (
          <Field label={t("crm.loyalty.member.hotel")} required>
            <Select
              value={chosenHotel}
              onChange={(e) => setHotel(e.target.value)}
              options={[{ value: "", label: t("crm.loyalty.adjust_hotel_pick") }, ...hotelOptions.map((h) => ({ value: h, label: h }))]}
              data-autofocus
            />
          </Field>
        )}
        {mode === "join" && blocked && <Notice tone="warning">{t("crm.loyalty.member.join_lifts_block")}</Notice>}
        {mode === "leave" && (
          <Field label={t("core.field.reason")} required hint={t("core.hint.reason_audited")}>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} autoComplete="off" data-autofocus />
          </Field>
        )}
        {mode === "leave" && (
          <div className="space-y-1">
            <Checkbox checked={block} onChange={(e) => setBlock(e.target.checked)} label={t("crm.loyalty.member.block_rejoin")} />
            <p className="text-xs text-zinc-500">{t("crm.loyalty.member.block_rejoin_hint")}</p>
          </div>
        )}
        <InlineError error={m.error} />
      </div>
    </Dialog>
  )
}

function AdjustDialog({
  open,
  program: initialProgram,
  programs,
  programHotels,
  hotels,
  defaultHotel,
  accounts,
  guest,
  onClose,
  onDone,
}: {
  open: boolean
  program: string
  programs: { value: string; label: string }[]
  programHotels: ProgramHotels
  /** the hotels through which the user may edit this guest */
  hotels: string[]
  defaultHotel: string | null | undefined
  accounts: LoyaltyAccount[]
  guest: string
  onClose: () => void
  onDone: () => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const [program, setProgram] = useState(initialProgram)
  const [direction, setDirection] = useState<"add" | "remove">("add")
  const [points, setPoints] = useState("")
  const [reason, setReason] = useState("")
  // an adjustment belongs to one hotel of the program, whose staff see its reason (ADR-056 second review)
  const hotelOptions = hotelChoices(programHotels, program, hotels)
  const [hotel, setHotel] = useState("")
  const chosenHotel = hotelOptions.includes(hotel) ? hotel : hotelOptions.length === 1 ? hotelOptions[0] : ""
  const m = useTexMutation<{ guest: string; program: string; points: number; reason: string; property?: string }, { name: string }>(
    "crm",
    "loyalty_adjust",
  )
  const close = useEvent(() => {
    if (!m.pending) onClose()
  })
  useEffect(() => {
    if (open) {
      setProgram(initialProgram)
      setDirection("add")
      setPoints("")
      setReason("")
      setHotel(defaultHotel && hotels.includes(defaultHotel) ? defaultHotel : "")
      m.clearError()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  const available = accounts.find((a) => a.program === program)?.available ?? 0
  const validPoints = isInteger(points) && Number(points) > 0
  const valid = validPoints && reason.trim().length > 2 && Boolean(program) && (Boolean(chosenHotel) || hotelOptions.length === 0)
  const submit = async () => {
    if (!valid) return
    const signed = direction === "add" ? Number(points) : -Number(points)
    try {
      await m.run({ guest, program, points: signed, reason: reason.trim(), ...(chosenHotel ? { property: chosenHotel } : {}) })
      toast.success(t("crm.loyalty.adjusted", { points: num(signed) }))
      onDone()
      onClose()
    } catch {
      /* inline */
    }
  }
  return (
    <Dialog
      open={open}
      onClose={close}
      title={t("crm.loyalty.adjust_title")}
      description={t("crm.loyalty.adjust_desc")}
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={m.pending}>
            {t("core.action.cancel")}
          </Button>
          <Button loading={m.pending} disabled={!valid} onClick={submit}>
            {t("crm.loyalty.adjust_save")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {programs.length > 1 && (
          <Field label={t("crm.loyalty.program")}>
            <Select value={program} onChange={(e) => setProgram(e.target.value)} options={programs} />
          </Field>
        )}
        {hotelOptions.length > 1 && (
          <Field label={t("crm.loyalty.adjust_hotel")} required hint={t("crm.loyalty.adjust_hotel_hint")}>
            <Select
              value={chosenHotel}
              onChange={(e) => setHotel(e.target.value)}
              options={[{ value: "", label: t("crm.loyalty.adjust_hotel_pick") }, ...hotelOptions.map((h) => ({ value: h, label: h }))]}
            />
          </Field>
        )}
        <fieldset>
          <legend className="mb-1.5 text-sm font-medium text-zinc-800">{t("crm.loyalty.direction")}</legend>
          <div className="flex gap-4">
            <label className="inline-flex items-center gap-2 text-sm">
              <input type="radio" name="adj-dir" checked={direction === "add"} onChange={() => setDirection("add")} className="accent-tex-600" />
              {t("crm.loyalty.add")}
            </label>
            <label className="inline-flex items-center gap-2 text-sm">
              <input type="radio" name="adj-dir" checked={direction === "remove"} onChange={() => setDirection("remove")} className="accent-tex-600" />
              {t("crm.loyalty.remove")}
            </label>
          </div>
        </fieldset>
        <Field
          label={t("crm.loyalty.points")}
          required
          hint={direction === "remove" ? t("crm.loyalty.remove_hint", { available: num(available) }) : undefined}
          error={points && !validPoints ? t("crm.loyalty.points_invalid") : undefined}
        >
          <Input inputMode="numeric" value={points} onChange={(e) => setPoints(e.target.value.replace(/[^\d]/g, ""))} data-autofocus autoComplete="off" />
        </Field>
        <Field label={t("core.field.reason")} required hint={t("core.hint.reason_audited")}>
          <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} autoComplete="off" />
        </Field>
        <InlineError error={m.error} />
      </div>
    </Dialog>
  )
}

function RedeemDialog({
  open,
  guest,
  stays,
  programs,
  accounts,
  onClose,
  onDone,
}: {
  open: boolean
  guest: string
  stays: Stay[]
  programs: LoyaltyProgramInfo[]
  accounts: LoyaltyAccount[]
  onClose: () => void
  onDone: () => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const bookings = useMemo(() => {
    const m = new Map<string, Stay>()
    for (const s of stays) if (s.tex_booking && !m.has(s.tex_booking)) m.set(s.tex_booking, s)
    return [...m.values()]
  }, [stays])
  const [booking, setBooking] = useState("")
  const [points, setPoints] = useState("")
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [done, setDone] = useState<{ transaction: string; value?: string; currency?: string; replay?: boolean } | null>(null)
  const key = useIntentKey("loyalty-redeem", open)
  const close = useEvent(() => {
    if (!pending) onClose()
  })
  useEffect(() => {
    if (open) {
      setBooking(bookings[0]?.tex_booking ?? "")
      setPoints("")
      setError(null)
      setDone(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  const stay = bookings.find((b) => b.tex_booking === booking)
  const prog = programs.find((p) => p.property === stay?.property)
  const account = accounts.find((a) => a.program === prog?.program) ?? (accounts.length === 1 ? accounts[0] : undefined)
  const validPoints = isInteger(points) && Number(points) > 0
  const valid = Boolean(booking) && validPoints

  const submit = async () => {
    if (!valid) return
    setPending(true)
    setError(null)
    try {
      const r = await tex<{ transaction: string; value?: string; currency?: string; replay?: boolean }>(
        "crm",
        "loyalty_redeem",
        { guest, booking, points: Number(points), idempotency_key: key },
        { post: true },
      )
      setDone(r)
      toast.success(t("crm.loyalty.redeemed"))
      onDone()
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
      title={t("crm.loyalty.redeem_title")}
      description={t("crm.loyalty.redeem_desc")}
      footer={
        done ? (
          <Button onClick={close}>{t("core.action.close")}</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={close} disabled={pending}>
              {t("core.action.cancel")}
            </Button>
            <Button loading={pending} disabled={!valid} onClick={submit}>
              {t("crm.loyalty.redeem_save")}
            </Button>
          </>
        )
      }
    >
      {done ? (
        <Notice tone="success" title={done.replay ? t("crm.loyalty.redeem_replay") : t("crm.loyalty.redeemed")}>
          <p>
            {done.value ? (
              <>
                {t("crm.loyalty.redeem_value")} <Money amount={done.value} currency={done.currency} />.{" "}
              </>
            ) : null}
            <Link className="font-medium underline" to={`/tex/payments/transactions/${encodeURIComponent(done.transaction)}`}>
              {t("crm.loyalty.view_payment", { name: done.transaction })}
            </Link>
          </p>
        </Notice>
      ) : (
        <div className="space-y-4">
          {!bookings.length ? (
            <Notice tone="warning">{t("crm.loyalty.no_bookings")}</Notice>
          ) : (
            <Field label={t("crm.loyalty.booking")} required>
              <Select
                value={booking}
                onChange={(e) => setBooking(e.target.value)}
                options={bookings.map((b) => ({ value: b.tex_booking!, label: `${b.tex_booking} · ${b.property} · ${date(b.check_in_date)}` }))}
                data-autofocus
              />
            </Field>
          )}
          <Field
            label={t("crm.loyalty.points")}
            required
            hint={
              account
                ? t("crm.loyalty.redeem_hint", { available: num(account.available), min: num(prog?.min_redeem_points ?? 0), pct: pct(prog?.max_redeem_percent ?? "100") })
                : undefined
            }
            error={points && !validPoints ? t("crm.loyalty.points_invalid") : undefined}
          >
            <Input inputMode="numeric" value={points} onChange={(e) => setPoints(e.target.value.replace(/[^\d]/g, ""))} autoComplete="off" />
          </Field>
          <p className="text-xs text-zinc-500">{t("crm.loyalty.redeem_server_note")}</p>
          <InlineError error={error} />
        </div>
      )}
    </Dialog>
  )
}
