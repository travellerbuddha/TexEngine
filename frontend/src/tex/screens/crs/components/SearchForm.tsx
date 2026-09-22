import { forwardRef, type FormEvent } from "react"
import { Search } from "lucide-react"
import { useSession } from "../../../lib/session"
import { addDays, isoDay, nightsBetween } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Button, Checkbox, Field, Input, Select } from "../../../ui"
import { cn } from "../../../../lib/utils"
import { CodeChips } from "./controls"
import { PartyEditor } from "./PartyEditor"
import type { FieldErrors, SearchFormState } from "../lib/useBookingFlow"

export interface SearchFormProps {
  form: SearchFormState
  onChange: (f: SearchFormState) => void
  errors: FieldErrors
  onSubmit: () => void
  searching: boolean
  /** Properties the user may price at (price.view). */
  hotels: { name: string; property_name: string; city?: string }[]
  variant?: "full" | "compact"
  /** Visible, explicit suggestion (e.g. the caller's CRM market) — never auto-applied. */
  marketHint?: { code: string; label: string } | null
  shortcut?: string
  idPrefix?: string
}

/** CRS / Call Center search. The first field forwards its ref (focus shortcuts). */
export const SearchForm = forwardRef<HTMLInputElement, SearchFormProps>(function SearchForm(
  { form, onChange, errors, onSubmit, searching, hotels, variant = "full", marketHint, shortcut, idPrefix = "crs" },
  firstRef,
) {
  const { t } = useTexT()
  const { boot } = useSession()
  const set = (patch: Partial<SearchFormState>) => onChange({ ...form, ...patch })
  const today = isoDay(new Date())
  const nights = form.check_in && form.check_out && form.check_out > form.check_in ? nightsBetween(form.check_in, form.check_out) : 0
  const compact = variant === "compact"
  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit()
  }
  const allHotels = form.properties.length === hotels.length
  return (
    <form onSubmit={submit} noValidate aria-label={t("crs.search.title")} className="space-y-4">
      <div className={cn("grid grid-cols-2 gap-3", compact ? "lg:grid-cols-4" : "md:grid-cols-4 xl:grid-cols-6")}>
        <Field label={t("crs.search.check_in")} error={errors.check_in} required>
          <Input
            ref={firstRef}
            id={`${idPrefix}-check-in`}
            type="date"
            min={today}
            value={form.check_in}
            onChange={(e) => {
              const ci = e.target.value
              const keep = form.check_in && form.check_out > form.check_in ? nightsBetween(form.check_in, form.check_out) : 1
              set({ check_in: ci, check_out: ci && (!form.check_out || form.check_out <= ci) ? addDays(ci, keep) : form.check_out })
            }}
          />
        </Field>
        <Field
          label={t("crs.search.check_out")}
          error={errors.check_out}
          hint={nights ? t("core.label.nights", { count: nights }) : undefined}
          required
        >
          <Input
            id={`${idPrefix}-check-out`}
            type="date"
            min={form.check_in ? addDays(form.check_in, 1) : today}
            value={form.check_out}
            onChange={(e) => set({ check_out: e.target.value })}
          />
        </Field>
        <Field
          label={t("crs.search.market")}
          error={errors.market}
          hint={!errors.market && !marketHint ? t("crs.search.market_hint") : undefined}
          required
        >
          <Select
            id={`${idPrefix}-market`}
            value={form.market}
            placeholder={t("crs.search.market_placeholder")}
            options={boot.markets.map((m) => ({ value: m.name, label: m.name === m.market_name ? m.name : `${m.market_name} (${m.name})` }))}
            onChange={(e) => set({ market: e.target.value })}
          />
        </Field>
        <Field label={t("crs.search.channel")} error={errors.channel}>
          <Select
            id={`${idPrefix}-channel`}
            value={form.channel}
            options={boot.channels.map((c) => ({ value: c.name, label: c.channel_name || c.name }))}
            onChange={(e) => set({ channel: e.target.value })}
          />
        </Field>
        <Field label={t("crs.search.currency")}>
          <Select
            id={`${idPrefix}-currency`}
            value={form.currency}
            options={[{ value: "", label: t("crs.search.currency_contract") }, ...boot.currencies.map((c) => ({ value: c, label: c }))]}
            onChange={(e) => set({ currency: e.target.value })}
          />
        </Field>
        <Field label={t("crs.search.promo")} hint={compact ? undefined : t("crs.search.promo_hint")}>
          <CodeChips
            id={`${idPrefix}-promo`}
            value={form.promo}
            onChange={(promo) => set({ promo })}
            placeholder={t("crs.search.promo_placeholder")}
          />
        </Field>
      </div>
      {marketHint && form.market !== marketHint.code && (
        <p className="-mt-2 text-xs text-zinc-600">
          {t("crs.search.market_suggest", { market: marketHint.label })}{" "}
          <button type="button" className="font-medium text-tex-700 underline-offset-2 hover:underline" onClick={() => set({ market: marketHint.code })}>
            {t("crs.search.market_use", { market: marketHint.code })}
          </button>
        </p>
      )}

      <PartyEditor rooms={form.rooms} onChange={(rooms) => set({ rooms })} errors={errors} dense={compact} idPrefix={`${idPrefix}-party`} />

      <div className="flex flex-wrap items-end justify-between gap-3">
        {hotels.length > 1 ? (
          <fieldset className="min-w-0">
            <legend className="mb-1 text-sm font-medium text-zinc-800">{t("crs.search.hotels")}</legend>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5">
              <Checkbox
                label={t("crs.search.all_hotels")}
                checked={allHotels}
                onChange={(e) => set({ properties: e.target.checked ? hotels.map((h) => h.name) : [] })}
              />
              {hotels.map((h) => (
                <Checkbox
                  key={h.name}
                  label={h.city ? `${h.property_name} · ${h.city}` : h.property_name}
                  checked={form.properties.includes(h.name)}
                  onChange={(e) =>
                    set({
                      properties: e.target.checked
                        ? hotels.filter((x) => x.name === h.name || form.properties.includes(x.name)).map((x) => x.name)
                        : form.properties.filter((p) => p !== h.name),
                    })
                  }
                />
              ))}
            </div>
            {errors.properties && (
              <p role="alert" className="mt-1 text-xs font-medium text-rose-700">
                {errors.properties}
              </p>
            )}
          </fieldset>
        ) : (
          <p className="text-sm text-zinc-600">{hotels[0]?.property_name}</p>
        )}
        <Button type="submit" loading={searching} icon={<Search className="size-4" aria-hidden />} shortcut={shortcut} className="w-full sm:w-auto">
          {t("crs.search.submit")}
        </Button>
      </div>
    </form>
  )
})
