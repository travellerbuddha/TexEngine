import { Search, Tag } from "lucide-react"
import { useEffect, useId, useState, type FormEvent } from "react"
import { useI18n } from "../i18n"
import { MAX_NIGHTS, type Criteria } from "../lib/criteria"
import { nightsBetween, today } from "../lib/dates"
import { useSite } from "../site/SiteContext"
import { Button, Field, Input, Select } from "../ui/controls"
import { DateRangePicker } from "./DateRangePicker"
import { GuestsPicker } from "./GuestsPicker"

interface Props {
  value: Criteria
  onSearch: (c: Criteria) => void
  busy?: boolean
  variant?: "card" | "inline" | "overlay" | "bar"
}

export function SearchForm({ value, onSearch, busy, variant = "card" }: Props) {
  const { t } = useI18n()
  const { site } = useSite()
  const [draft, setDraft] = useState<Criteria>(value)
  const [errors, setErrors] = useState<{ dates?: string; guests?: string }>({})
  const [promoOpen, setPromoOpen] = useState(!!value.promo)
  const base = useId()
  const ids = { hotel: `${base}-hotel`, dates: `${base}-dates`, guests: `${base}-guests`, promo: `${base}-promo` }

  // follow outside changes (back/forward, widget links)
  useEffect(() => {
    setDraft(value)
    if (value.promo) setPromoOpen(true)
  }, [value])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const errs: typeof errors = {}
    if (!draft.checkIn || !draft.checkOut) errs.dates = t("search.errDates")
    else if (draft.checkIn < today()) errs.dates = t("search.errPast")
    else if (draft.checkOut <= draft.checkIn) errs.dates = t("search.errOrder")
    else if (nightsBetween(draft.checkIn, draft.checkOut) > MAX_NIGHTS) errs.dates = t("search.errLong", { count: MAX_NIGHTS })
    if (draft.rooms.some((r) => r.ages.some((a) => a === null))) errs.guests = t("search.errAges")
    setErrors(errs)
    if (errs.dates) return document.getElementById(ids.dates)?.focus()
    if (errs.guests) return document.getElementById(ids.guests)?.focus()
    onSearch({ ...draft, promo: draft.promo.trim().toUpperCase() })
  }

  const shell =
    variant === "card"
      ? "bk-card p-4 shadow-pop sm:p-5"
      : variant === "overlay"
        ? "rounded-card border border-white/40 bg-surface/95 p-4 shadow-pop backdrop-blur sm:p-5"
        : variant === "bar"
          ? "bk-card p-3 sm:p-4"
          : "rounded-card border border-line bg-surface p-4"

  const group = site.group && site.hotels.length > 1
  return (
    <form onSubmit={submit} noValidate className={shell} aria-label={t("search.formLabel")} role="search">
      <div className={`grid gap-3 ${group ? "lg:grid-cols-[1fr_1.35fr_1.1fr_auto]" : "md:grid-cols-[1.4fr_1.1fr_auto]"}`}>
        {group && (
          <Field label={t("search.hotel")} id={ids.hotel}>
            <Select value={draft.hotel ?? ""} onChange={(e) => setDraft({ ...draft, hotel: e.target.value || null })}>
              <option value="">{t("search.allHotels")}</option>
              {site.hotels.map((h) => (
                <option key={h.name} value={h.name}>
                  {h.city ? `${h.property_name} — ${h.city}` : h.property_name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <DateRangePicker
          id={ids.dates}
          checkIn={draft.checkIn}
          checkOut={draft.checkOut}
          error={errors.dates}
          onChange={(ci, co) => {
            setDraft((d) => ({ ...d, checkIn: ci, checkOut: co }))
            if (ci && co) setErrors((e) => ({ ...e, dates: undefined }))
          }}
        />
        <GuestsPicker
          id={ids.guests}
          rooms={draft.rooms}
          error={errors.guests}
          onChange={(rooms) => {
            setDraft((d) => ({ ...d, rooms }))
            if (rooms.every((r) => r.ages.every((a) => a !== null))) setErrors((e) => ({ ...e, guests: undefined }))
          }}
        />
        <div className="flex items-end">
          <Button type="submit" size="lg" block busy={busy} className="md:min-h-12 md:min-w-36">
            <Search className="size-4" aria-hidden />
            {t("search.submit")}
          </Button>
        </div>
      </div>
      <div className="mt-3">
        {promoOpen ? (
          <div className="max-w-xs">
            <Field label={t("search.promo")} optional={t("common.optional")} id={ids.promo}>
              <Input
                value={draft.promo}
                onChange={(e) => setDraft({ ...draft, promo: e.target.value.slice(0, 40) })}
                autoComplete="off"
                autoCapitalize="characters"
                spellCheck={false}
                className="uppercase"
              />
            </Field>
          </div>
        ) : (
          <button
            type="button"
            className="inline-flex min-h-8 items-center gap-1.5 rounded-ui text-sm font-medium text-brand-ink underline-offset-2 hover:underline"
            onClick={() => {
              setPromoOpen(true)
              // the button is replaced by the field: move focus into it
              requestAnimationFrame(() => document.getElementById(ids.promo)?.focus())
            }}
          >
            <Tag className="size-4" aria-hidden />
            {t("search.havePromo")}
          </button>
        )}
      </div>
    </form>
  )
}
