import { Trash2 } from "lucide-react"
import { useTexT } from "../../../i18n"
import { Button, DecimalInput, Field, Input, Select } from "../../../ui"

export interface RoomForm {
  id: number
  room_code: string
  rate_code: string
  check_in: string
  check_out: string
  adults: string
  total: string
  currency: string
  line_ref: string
}

export type RoomErrors = Partial<Record<keyof RoomForm, string>>

/** One room line of a simulated channel booking. */
export function SandboxRoomFields({
  room,
  index,
  errors,
  unmapped,
  currencies,
  roomListId,
  rateListId,
  onChange,
  onRoomCode,
  onRemove,
}: {
  room: RoomForm
  index: number
  errors: RoomErrors
  /** the room/rate pair has no enabled mapping on this connection */
  unmapped: boolean
  currencies: string[]
  roomListId: string
  rateListId: string
  onChange: (patch: Partial<RoomForm>) => void
  onRoomCode: (code: string) => void
  onRemove?: () => void
}) {
  const { t } = useTexT()
  const n = index + 1
  return (
    <fieldset className="min-w-0 space-y-3 rounded-lg border border-zinc-200 px-3 pt-1 pb-3">
      <legend className="px-1 text-sm font-semibold text-zinc-900">{t("connect.channels.sandbox.room_n", { n })}</legend>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label={t("connect.channels.sandbox.room_code")} required error={errors.room_code} hint={unmapped ? t("connect.channels.sandbox.unmapped") : undefined}>
          <Input list={roomListId} value={room.room_code} onChange={(e) => onRoomCode(e.target.value)} autoComplete="off" spellCheck={false} className="font-mono" />
        </Field>
        <Field label={t("connect.channels.sandbox.rate_code")} required error={errors.rate_code}>
          <Input list={rateListId} value={room.rate_code} onChange={(e) => onChange({ rate_code: e.target.value })} autoComplete="off" spellCheck={false} className="font-mono" />
        </Field>
        <Field label={t("connect.channels.sandbox.check_in")} required error={errors.check_in}>
          <Input type="date" value={room.check_in} onChange={(e) => onChange({ check_in: e.target.value })} />
        </Field>
        <Field label={t("connect.channels.sandbox.check_out")} required error={errors.check_out}>
          <Input type="date" value={room.check_out} min={room.check_in || undefined} onChange={(e) => onChange({ check_out: e.target.value })} />
        </Field>
        <Field label={t("connect.channels.sandbox.adults")} required error={errors.adults}>
          <Input type="number" min={1} max={9} step={1} inputMode="numeric" value={room.adults} onChange={(e) => onChange({ adults: e.target.value })} />
        </Field>
        <Field label={t("connect.channels.sandbox.total")} required error={errors.total} hint={t("connect.channels.sandbox.total_hint")}>
          <DecimalInput value={room.total} onValueChange={(v) => onChange({ total: v })} suffix={room.currency || undefined} placeholder="450.00" />
        </Field>
        <Field label={t("connect.channels.sandbox.currency")} required error={errors.currency}>
          <Select value={room.currency} onChange={(e) => onChange({ currency: e.target.value })} placeholder={t("connect.select")} options={currencies.map((c) => ({ value: c, label: c }))} />
        </Field>
        <Field label={t("connect.channels.sandbox.line_ref")} error={errors.line_ref} hint={t("connect.channels.sandbox.line_ref_hint")}>
          <Input value={room.line_ref} onChange={(e) => onChange({ line_ref: e.target.value })} autoComplete="off" spellCheck={false} className="font-mono" maxLength={40} />
        </Field>
      </div>
      {onRemove && (
        <div className="flex justify-end">
          <Button variant="ghost" size="sm" className="text-rose-700" icon={<Trash2 className="size-3.5" aria-hidden />} onClick={onRemove}>
            {t("connect.channels.sandbox.remove_room", { n })}
          </Button>
        </div>
      )}
    </fieldset>
  )
}
