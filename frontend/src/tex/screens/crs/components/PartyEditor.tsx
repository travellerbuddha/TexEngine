import { Plus, Trash2 } from "lucide-react"
import { useTexT } from "../../../i18n"
import { Button, Field, IconButton, Select } from "../../../ui"
import { cn } from "../../../../lib/utils"
import { NumberStepper } from "./controls"
import { CHILD_AGES, MAX_ADULTS, MAX_CHILDREN, MAX_ROOMS, type PartyForm } from "../lib/party"
import type { FieldErrors } from "../lib/useBookingFlow"

/** Multi-room party: adults and one explicit age per child, per room (R-29). */
export function PartyEditor({
  rooms,
  onChange,
  errors = {},
  dense,
  idPrefix = "party",
}: {
  rooms: PartyForm[]
  onChange: (rooms: PartyForm[]) => void
  errors?: FieldErrors
  dense?: boolean
  idPrefix?: string
}) {
  const { t } = useTexT()
  const set = (i: number, p: PartyForm) => onChange(rooms.map((r, j) => (j === i ? p : r)))
  const ageOptions = CHILD_AGES.map((a) => ({ value: String(a), label: a === 0 ? t("crs.age.infant") : String(a) }))
  return (
    <fieldset className="min-w-0">
      <legend className="mb-1.5 text-sm font-medium text-zinc-800">{t("crs.search.rooms")}</legend>
      <ol className="space-y-2">
        {rooms.map((r, i) => (
          <li
            key={i}
            className={cn(
              "flex flex-wrap items-end gap-x-3 gap-y-2 rounded-lg border border-zinc-200 bg-zinc-50/70",
              dense ? "p-2" : "p-2.5",
            )}
          >
            <p className="flex h-9 w-full items-center text-sm font-semibold text-zinc-800 sm:w-auto sm:min-w-16">
              {t("crs.room_n", { n: i + 1 })}
            </p>
            <Field label={t("crs.search.adults")} error={errors[`room_${i}`]}>
              <NumberStepper
                id={`${idPrefix}-r${i}-adults`}
                value={r.adults}
                min={1}
                max={MAX_ADULTS}
                decLabel={t("crs.search.fewer_adults", { n: i + 1 })}
                incLabel={t("crs.search.more_adults", { n: i + 1 })}
                onChange={(v) => set(i, { ...r, adults: v })}
              />
            </Field>
            <Field label={t("crs.search.children")}>
              <NumberStepper
                id={`${idPrefix}-r${i}-children`}
                value={r.children.length}
                min={0}
                max={MAX_CHILDREN}
                decLabel={t("crs.search.fewer_children", { n: i + 1 })}
                incLabel={t("crs.search.more_children", { n: i + 1 })}
                onChange={(v) =>
                  set(i, {
                    ...r,
                    children: v > r.children.length ? [...r.children, ...Array(v - r.children.length).fill(null)] : r.children.slice(0, v),
                  })
                }
              />
            </Field>
            {r.children.map((age, k) => (
              <Field key={k} label={t("crs.search.child_age_n", { n: k + 1 })} error={errors[`room_${i}_child_${k}`]}>
                <Select
                  id={`${idPrefix}-r${i}-c${k}`}
                  className="w-24"
                  value={age === null ? "" : String(age)}
                  placeholder={t("crs.search.age_placeholder")}
                  options={ageOptions}
                  onChange={(e) =>
                    set(i, {
                      ...r,
                      children: r.children.map((a, j) => (j === k ? (e.target.value === "" ? null : Number(e.target.value)) : a)),
                    })
                  }
                />
              </Field>
            ))}
            {rooms.length > 1 && (
              <IconButton
                className="ml-auto"
                label={t("crs.search.remove_room", { n: i + 1 })}
                icon={<Trash2 className="size-4" />}
                onClick={() => onChange(rooms.filter((_, j) => j !== i))}
              />
            )}
          </li>
        ))}
      </ol>
      {rooms.length < MAX_ROOMS && (
        <Button
          variant="ghost"
          size="sm"
          className="mt-1.5"
          icon={<Plus className="size-4" aria-hidden />}
          onClick={() => onChange([...rooms, { adults: 2, children: [] }])}
        >
          {t("crs.search.add_room")}
        </Button>
      )}
    </fieldset>
  )
}

/** "2 adults · 1 child (5)" */
export function usePartyText() {
  const { t } = useTexT()
  return (adults: number, childAges: (number | null | undefined)[]) => {
    const parts = [t("crs.party.adults", { count: adults })]
    if (childAges.length) {
      const ages = childAges.map((a) => (a === null || a === undefined ? "?" : a === 0 ? t("crs.age.infant_short") : String(a)))
      parts.push(`${t("crs.party.children", { count: childAges.length })} (${ages.join(", ")})`)
    }
    return parts.join(" · ")
  }
}
