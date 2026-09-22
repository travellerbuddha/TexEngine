import { Plus, Trash2, Users } from "lucide-react"
import { useId, useRef, useState } from "react"
import { useI18n } from "../i18n"
import { MAX_ADULTS, MAX_CHILDREN, MAX_ROOMS, type Party } from "../lib/criteria"
import { Button, Counter } from "../ui/controls"
import { Dialog } from "../ui/Dialog"
import { useWide } from "./DateRangePicker"

export function guestsSummary(t: ReturnType<typeof useI18n>["t"], rooms: Party[]) {
  const adults = rooms.reduce((n, r) => n + r.adults, 0)
  const children = rooms.reduce((n, r) => n + r.ages.length, 0)
  const parts = [t("guests.adults", { count: adults })]
  if (children) parts.push(t("guests.children", { count: children }))
  parts.push(t("guests.rooms", { count: rooms.length }))
  return parts.join(" · ")
}

export function partyText(t: ReturnType<typeof useI18n>["t"], p: { adults: number; ages?: (number | null)[]; children?: number }) {
  const kids = p.ages ? p.ages.length : p.children ?? 0
  const parts = [t("guests.adults", { count: p.adults })]
  if (kids) {
    const ages = p.ages?.filter((a): a is number => a !== null)
    parts.push(ages && ages.length === kids ? t("guests.childrenAges", { count: kids, ages: ages.join(", ") }) : t("guests.children", { count: kids }))
  }
  return parts.join(", ")
}

export function RoomsEditor({ rooms, onChange, showErrors, single }: { rooms: Party[]; onChange: (r: Party[]) => void; showErrors: boolean; single?: boolean }) {
  const { t } = useI18n()
  const base = useId()
  const update = (i: number, p: Party) => onChange(rooms.map((r, j) => (j === i ? p : r)))
  return (
    <div className="space-y-5">
      {rooms.map((room, i) => (
        <fieldset key={i} className="rounded-ui border border-line p-4">
          <legend className="px-1 text-sm font-semibold">{single ? t("search.guests") : t("guests.room", { n: i + 1 })}</legend>
          {rooms.length > 1 && !single && (
            <div className="-mt-2 flex justify-end">
              <Button variant="ghost" size="sm" onClick={() => onChange(rooms.filter((_, j) => j !== i))} aria-label={t("guests.removeRoom", { n: i + 1 })}>
                <Trash2 className="size-4" aria-hidden />
                {t("guests.remove")}
              </Button>
            </div>
          )}
          <Counter
            label={t("guests.adultsLabel")}
            sublabel={t("guests.adultsHint")}
            value={room.adults}
            min={1}
            max={MAX_ADULTS}
            onChange={(n) => update(i, { ...room, adults: n })}
            decLabel={t("guests.fewerAdults", { n: i + 1 })}
            incLabel={t("guests.moreAdults", { n: i + 1 })}
          />
          <Counter
            label={t("guests.childrenLabel")}
            sublabel={t("guests.childrenHint")}
            value={room.ages.length}
            min={0}
            max={MAX_CHILDREN}
            onChange={(n) => update(i, { ...room, ages: n > room.ages.length ? [...room.ages, ...Array(n - room.ages.length).fill(null)] : room.ages.slice(0, n) })}
            decLabel={t("guests.fewerChildren", { n: i + 1 })}
            incLabel={t("guests.moreChildren", { n: i + 1 })}
          />
          {room.ages.length > 0 && (
            <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-3">
              {room.ages.map((age, k) => {
                const id = `${base}-r${i}-c${k}`
                const missing = showErrors && age === null
                return (
                  <div key={k}>
                    <label htmlFor={id} className="mb-1 block text-xs font-medium text-soft">
                      {t("guests.childAge", { n: k + 1 })}
                    </label>
                    <select
                      id={id}
                      data-missing-age={age === null || undefined}
                      className="bk-input"
                      value={age === null ? "" : String(age)}
                      aria-invalid={missing || undefined}
                      aria-describedby={missing ? `${id}-err` : undefined}
                      onChange={(e) => {
                        const v = e.target.value === "" ? null : Number(e.target.value)
                        update(i, { ...room, ages: room.ages.map((a, j) => (j === k ? v : a)) })
                      }}
                    >
                      <option value="">{t("guests.selectAge")}</option>
                      {Array.from({ length: 18 }, (_, a) => (
                        <option key={a} value={a}>
                          {a === 0 ? t("guests.underOne") : t("guests.years", { count: a })}
                        </option>
                      ))}
                    </select>
                    {missing && (
                      <p id={`${id}-err`} className="mt-1 text-xs font-medium text-bad">
                        {t("guests.ageRequired")}
                      </p>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </fieldset>
      ))}
      {rooms.length < MAX_ROOMS && !single && (
        <Button variant="secondary" block onClick={() => onChange([...rooms, { adults: 2, ages: [] }])}>
          <Plus className="size-4" aria-hidden />
          {t("guests.addRoom")}
        </Button>
      )}
      <p className="text-xs text-muted">{t("guests.agesWhy")}</p>
    </div>
  )
}

export function GuestsPicker({ id, rooms, onChange, error }: { id: string; rooms: Party[]; onChange: (r: Party[]) => void; error?: string | null }) {
  const { t } = useI18n()
  const wide = useWide()
  const [open, setOpen] = useState(false)
  const [showErrors, setShowErrors] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const labelId = useId()
  const valueId = useId()
  const done = () => {
    if (rooms.some((r) => r.ages.some((a) => a === null))) {
      setShowErrors(true)
      document.querySelector<HTMLSelectElement>("dialog[open] [data-missing-age]")?.focus()
      return
    }
    setShowErrors(false)
    setOpen(false)
  }
  return (
    <div>
      <span id={labelId} className="mb-1.5 block text-sm font-medium text-soft">
        {t("search.guests")}
      </span>
      <button
        ref={trigger}
        id={id}
        type="button"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-labelledby={`${labelId} ${valueId}`}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-err` : undefined}
        className="bk-input flex items-center gap-2.5 text-left"
      >
        <Users className="size-5 flex-none text-muted" aria-hidden />
        <span id={valueId} className="min-w-0 flex-1 truncate font-medium">
          {guestsSummary(t, rooms)}
        </span>
      </button>
      {error && (
        <p id={`${id}-err`} className="mt-1 text-sm font-medium text-bad">
          {error}
        </p>
      )}
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={t("guests.title")}
        closeLabel={t("common.close")}
        variant="sheet"
        anchor={trigger.current}
        width={wide ? "420px" : undefined}
        footer={
          <Button block onClick={done}>
            {t("common.done")}
          </Button>
        }
      >
        <RoomsEditor rooms={rooms} onChange={onChange} showErrors={showErrors} />
      </Dialog>
    </div>
  )
}
