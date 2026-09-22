import { useEffect, useId, useMemo, useState } from "react"
import { Search, X } from "lucide-react"
import { useTexQuery } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { date } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, InlineError, Input, Money, Skeleton, Spinner, statusTone } from "../../../ui"
import { useDebounced } from "../lib"
import type { BookingSummary, ReservationRow } from "../types"

/** Find a booking of the selected hotel by number, guest name, email or phone, then
 * show the server's totals for it. `onChange` receives the booking and its summary. */
export function BookingPicker({
  property,
  value,
  onChange,
  label,
  required,
  exclude,
  expectCurrency,
  autoFocus,
}: {
  property: string
  value: string
  onChange: (booking: string, summary?: BookingSummary) => void
  label: string
  required?: boolean
  exclude?: string
  expectCurrency?: string
  autoFocus?: boolean
}) {
  const { t } = useTexT()
  const { can } = useSession()
  const id = useId()
  const [q, setQ] = useState("")
  const dq = useDebounced(q.trim(), 300)
  const canSearch = can("reservation.view", property)
  const search = useTexQuery<ReservationRow[]>("crs", "reservations", { property, q: dq, limit: 20 }, [property, dq], canSearch && !value && dq.length >= 2)
  const summary = useTexQuery<BookingSummary>("crs", "booking", { name: value }, [value], Boolean(value) && canSearch)

  useEffect(() => {
    if (summary.data && summary.data.booking === value) onChange(value, summary.data)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [summary.data])

  const bookings = useMemo(() => {
    const m = new Map<string, ReservationRow>()
    for (const r of search.data ?? []) if (r.tex_booking && r.tex_booking !== exclude && !m.has(r.tex_booking)) m.set(r.tex_booking, r)
    return [...m.values()].slice(0, 8)
  }, [search.data, exclude])
  const looksLikeId = /^[A-Z]{2,}-[\w-]+$/i.test(dq)

  const labelEl = (
    <label htmlFor={id} className="block text-sm font-medium text-zinc-800">
      {label}
      {required && (
        <span className="ml-0.5 text-rose-600" aria-hidden>
          *
        </span>
      )}
    </label>
  )

  if (value) {
    const s = summary.data
    const mismatch = s && expectCurrency && s.currency !== expectCurrency
    return (
      <div className="space-y-1.5">
        {labelEl}
        <div id={id} className="rounded-lg border border-zinc-200 bg-zinc-50 p-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="font-mono text-sm font-medium text-zinc-900">{value}</p>
              {s ? (
                <p className="text-xs text-zinc-600">
                  {s.booker_name || "—"} · {s.rooms[0] ? `${date(s.rooms[0].check_in, "short")} → ${date(s.rooms[0].check_out, "short")}` : ""}
                </p>
              ) : summary.loading ? (
                <Skeleton className="mt-1 h-3 w-40" />
              ) : null}
            </div>
            <Button variant="ghost" size="sm" icon={<X className="size-4" aria-hidden />} onClick={() => onChange("")}>
              {t("payments.picker.change")}
            </Button>
          </div>
          {s && (
            <dl className="mt-2 grid grid-cols-3 gap-2 text-xs">
              <div>
                <dt className="text-zinc-500">{t("payments.picker.total")}</dt>
                <dd className="font-medium">
                  <Money amount={s.total} currency={s.currency} />
                </dd>
              </div>
              <div>
                <dt className="text-zinc-500">{t("payments.picker.paid")}</dt>
                <dd className="font-medium">
                  <Money amount={s.paid} currency={s.currency} />
                </dd>
              </div>
              <div>
                <dt className="text-zinc-500">{t("payments.picker.balance")}</dt>
                <dd className="font-semibold">
                  <Money amount={s.balance} currency={s.currency} />
                </dd>
              </div>
            </dl>
          )}
          {s && (
            <p className="mt-2 flex flex-wrap gap-1">
              <Badge tone={statusTone(s.status)}>{t(`payments.booking_status.${s.status.toLowerCase().replace(/\s+/g, "_")}`)}</Badge>
              {s.payment_status && <Badge tone="neutral">{t(`payments.payment_status.${s.payment_status.toLowerCase().replace(/\s+/g, "_")}`)}</Badge>}
            </p>
          )}
          {mismatch && <p className="mt-2 text-xs font-medium text-rose-700">{t("payments.picker.currency_mismatch", { currency: s.currency, expected: expectCurrency })}</p>}
          {summary.error && <InlineError error={summary.error} />}
        </div>
      </div>
    )
  }

  if (!canSearch)
    return (
      <div className="space-y-1.5">
        {labelEl}
        <Input id={id} value={q} onChange={(e) => setQ(e.target.value)} onBlur={() => q.trim() && onChange(q.trim())} placeholder="TEX-2026-00001" autoFocus={autoFocus} />
      </div>
    )

  return (
    <div className="space-y-1.5">
      {labelEl}
      <div className="relative">
        <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-zinc-400" aria-hidden />
        <Input
          id={id}
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("payments.picker.placeholder")}
          className="pl-8"
          aria-describedby={`${id}-hint`}
          autoComplete="off"
          data-autofocus={autoFocus ? "" : undefined}
        />
      </div>
      <p id={`${id}-hint`} className="text-xs text-zinc-500">
        {t("payments.picker.hint")}
      </p>
      {dq.length >= 2 && (
        <div className="rounded-lg border border-zinc-200" aria-live="polite">
          {search.loading ? (
            <div className="flex items-center gap-2 px-3 py-2 text-sm text-zinc-500">
              <Spinner /> {t("core.label.loading")}
            </div>
          ) : search.error ? (
            <div className="p-2">
              <InlineError error={search.error} />
            </div>
          ) : (
            <ul className="max-h-60 divide-y divide-zinc-100 overflow-y-auto">
              {bookings.map((r) => (
                <li key={r.tex_booking}>
                  <button
                    type="button"
                    onClick={() => {
                      onChange(r.tex_booking!)
                      setQ("")
                    }}
                    className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-tex-50 focus-visible:bg-tex-50"
                  >
                    <span className="min-w-0">
                      <span className="block font-mono text-xs font-medium text-zinc-900">{r.tex_booking}</span>
                      <span className="block truncate text-xs text-zinc-600">
                        {r.guest_name || "—"} · {date(r.check_in_date, "short")} → {date(r.check_out_date, "short")}
                      </span>
                    </span>
                    <Money amount={r.total} currency={r.tex_currency} className="text-xs" />
                  </button>
                </li>
              ))}
              {!bookings.length && (
                <li className="px-3 py-2 text-sm text-zinc-500">
                  {t("payments.picker.none")}
                  {looksLikeId && (
                    <Button variant="link" size="sm" className="ml-2" onClick={() => onChange(dq.toUpperCase())}>
                      {t("payments.picker.use", { booking: dq.toUpperCase() })}
                    </Button>
                  )}
                </li>
              )}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
