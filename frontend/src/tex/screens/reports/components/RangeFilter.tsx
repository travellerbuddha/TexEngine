import { useId } from "react"
import { useSiteClock } from "../../../lib/siteDay"
import { useTexT } from "../../../i18n"
import { Field, Input, Select } from "../../../ui"
import { presetRange, type RangePreset } from "../lib"

/** Period preset + explicit from/to dates. Choosing a preset fills the dates;
 * editing a date switches the preset to "custom". */
export function RangeFilter({
  presets,
  preset,
  from,
  to,
  onChange,
  labels,
  error,
}: {
  presets: Exclude<RangePreset, "custom">[]
  preset: RangePreset
  from: string
  to: string
  onChange: (next: { preset: RangePreset; from: string; to: string }) => void
  labels?: { period?: string; from?: string; to?: string }
  /** Validation message for the range (shown once, linked to both inputs). */
  error?: string | null
}) {
  const { t } = useTexT()
  const clock = useSiteClock()
  const id = useId()
  const errId = `${id}-err`
  const describedBy = error ? errId : undefined
  return (
    <>
      <Field label={labels?.period ?? t("reports.filter.period")} className="w-full sm:w-44">
        <Select
          value={preset}
          onChange={(e) => {
            const p = e.target.value as RangePreset
            if (p === "custom") onChange({ preset: p, from, to })
            else {
              const [a, b] = presetRange(p, clock.today())
              onChange({ preset: p, from: a, to: b })
            }
          }}
          options={[
            ...presets.map((p) => ({ value: p, label: t(`reports.preset.${p}`) })),
            { value: "custom", label: t("reports.preset.custom") },
          ]}
        />
      </Field>
      <div className="w-[calc(50%-0.375rem)] space-y-1.5 sm:w-40">
        <label htmlFor={`${id}-from`} className="block text-sm font-medium text-zinc-800">
          {labels?.from ?? t("core.label.from")}
        </label>
        <Input
          id={`${id}-from`}
          type="date"
          value={from}
          max={to || undefined}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          onChange={(e) => onChange({ preset: "custom", from: e.target.value, to })}
        />
      </div>
      <div className="w-[calc(50%-0.375rem)] space-y-1.5 sm:w-40">
        <label htmlFor={`${id}-to`} className="block text-sm font-medium text-zinc-800">
          {labels?.to ?? t("core.label.to")}
        </label>
        <Input
          id={`${id}-to`}
          type="date"
          value={to}
          min={from || undefined}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          onChange={(e) => onChange({ preset: "custom", from, to: e.target.value })}
        />
      </div>
      {error && (
        <p id={errId} role="alert" className="w-full text-xs font-medium text-rose-700">
          {error}
        </p>
      )}
    </>
  )
}
