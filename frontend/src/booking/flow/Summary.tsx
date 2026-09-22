import { CalendarDays, ChevronDown, Users } from "lucide-react"
import { useState, type ReactNode } from "react"
import { useI18n } from "../i18n"
import { nightsBetween } from "../lib/dates"
import { isZero } from "../lib/format"
import { boardLabel, cancellation } from "../lib/policy"
import { partyText } from "../search/GuestsPicker"
import { Dialog } from "../ui/Dialog"
import type { QuoteLine, RoomQuote } from "../types"
import { useBooking, type Selection } from "./BookingContext"

/** Nightly amount when every night costs the same (server figures), else null. */
export function uniformNight(q: RoomQuote | null | undefined): string | null {
  const n = q?.nights ?? []
  if (!n.length) return null
  return n.every((x) => x.amount === n[0].amount) ? n[0].amount : null
}

export function PriceLines({ lines, currency }: { lines: QuoteLine[]; currency: string }) {
  const { money } = useI18n()
  const shown = lines.filter((l) => !l.included)
  const included = lines.filter((l) => l.included)
  return (
    <dl className="space-y-1 text-sm">
      {shown.map((l, i) => (
        <div key={i} className="flex justify-between gap-3">
          <dt className="text-soft">{l.description}</dt>
          <dd className={`tabular-nums ${l.amount.startsWith("-") ? "text-ok" : ""}`}>{money(l.amount, currency)}</dd>
        </div>
      ))}
      {included.map((l, i) => (
        <div key={`i${i}`} className="flex justify-between gap-3 text-xs text-muted">
          <dt>{l.description}</dt>
          <dd className="tabular-nums">{money(l.amount, currency)}</dd>
        </div>
      ))}
    </dl>
  )
}

function RoomSummary({ i, sel, multi }: { i: number; sel: Selection | null; multi: boolean }) {
  const { t, money } = useI18n()
  const { flow, criteria } = useBooking()
  const i18n = useI18n()
  const party = criteria.rooms[i]
  const quoted = flow.quotes[i]?.ok ? flow.quotes[i]!.quote! : null
  const q = quoted ?? sel?.quote ?? null
  const [open, setOpen] = useState(false)
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      {multi && <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t("guests.room", { n: i + 1 })}</p>}
      {sel && q ? (
        <>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="font-semibold leading-snug">{sel.roomName}</p>
              <p className="text-sm text-soft">
                {[boardLabel(t, sel.board), sel.ratePlanName].filter(Boolean).join(" · ")}
              </p>
              {party && <p className="text-sm text-muted">{partyText(t, party)}</p>}
            </div>
            <p className="text-right font-semibold tabular-nums">{money(q.totals.total, q.currency)}</p>
          </div>
          {criteria.checkIn && <p className="mt-1 text-xs text-muted">{cancellation(i18n, sel.rateInfo, criteria.checkIn).text}</p>}
          {q.promotions?.length > 0 && (
            <p className="mt-1 text-xs font-medium text-ok">{q.promotions.map((p) => p.name).join(", ")}</p>
          )}
          <button
            type="button"
            className="mt-1.5 inline-flex min-h-6 items-center gap-1 text-xs font-medium text-brand-ink underline-offset-2 hover:underline"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            {t("summary.priceDetails")}
            <ChevronDown className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
          </button>
          {open && (
            <div className="mt-2 rounded-ui bg-sunken p-3">
              <PriceLines lines={q.lines} currency={q.currency} />
              {!isZero(q.totals.tax_added ?? "0") && (
                <p className="mt-2 text-xs text-muted">{t("summary.taxesAdded", { amount: money(q.totals.tax_added, q.currency) })}</p>
              )}
            </div>
          )}
        </>
      ) : (
        <div>
          {party && <p className="text-sm text-muted">{partyText(t, party)}</p>}
          <p className="text-sm font-medium text-soft">{t("summary.notSelected")}</p>
        </div>
      )}
    </li>
  )
}

export function SummaryBody({ children }: { children?: ReactNode }) {
  const { t, money, range } = useI18n()
  const { flow, criteria, hotelName } = useBooking()
  const n = criteria.rooms.length
  const nights = criteria.checkIn && criteria.checkOut ? nightsBetween(criteria.checkIn, criteria.checkOut) : 0
  const single = n === 1 ? (flow.quotes[0]?.ok ? flow.quotes[0]!.quote! : flow.selections[0]?.quote) : null
  return (
    <div>
      {hotelName && <p className="text-lg font-semibold leading-snug">{hotelName}</p>}
      <div className="mt-2 space-y-1 text-sm text-soft">
        {criteria.checkIn && criteria.checkOut && (
          <p className="flex items-center gap-2">
            <CalendarDays className="size-4 text-muted" aria-hidden />
            {range(criteria.checkIn, criteria.checkOut)} · {t("dates.nights", { count: nights })}
          </p>
        )}
        <p className="flex items-center gap-2">
          <Users className="size-4 text-muted" aria-hidden />
          {t("guests.rooms", { count: n })}
        </p>
      </div>
      <ul className="mt-4 divide-y divide-line border-y border-line py-3">
        {Array.from({ length: n }, (_, i) => (
          <RoomSummary key={i} i={i} sel={flow.selections[i] ?? null} multi={n > 1} />
        ))}
      </ul>
      {single ? (
        <div className="mt-3 flex items-baseline justify-between gap-3">
          <span className="font-semibold">{t("summary.total")}</span>
          <span className="text-2xl font-bold tabular-nums">{money(single.totals.total, single.currency)}</span>
        </div>
      ) : (
        n > 1 && <p className="mt-3 text-sm text-muted">{t("summary.multiTotalNote")}</p>
      )}
      {single && !isZero(single.totals.tax ?? "0") && isZero(single.totals.tax_added ?? "0") && (
        <p className="mt-1 text-right text-xs text-muted">{t("summary.taxesIncluded")}</p>
      )}
      {children && <div className="mt-4">{children}</div>}
    </div>
  )
}

/** Desktop: sticky side panel. Phones: a bar pinned to the bottom with the key
 * figure and the next action; the full summary opens in a sheet. */
export function Summary({ action, compactLabel }: { action?: ReactNode; compactLabel?: ReactNode }) {
  const { t, money } = useI18n()
  const { flow, criteria } = useBooking()
  const [open, setOpen] = useState(false)
  if (compactLabel === undefined) {
    const n = criteria.rooms.length
    const q = n === 1 ? (flow.quotes[0]?.ok ? flow.quotes[0]!.quote! : flow.selections[0]?.quote) : null
    const nights = criteria.checkIn && criteria.checkOut ? nightsBetween(criteria.checkIn, criteria.checkOut) : 0
    compactLabel = q ? (
      <>
        <span className="tabular-nums">{money(q.totals.total, q.currency)}</span>
        <span className="font-normal text-muted"> · {t("dates.nights", { count: nights })}</span>
      </>
    ) : (
      `${t("guests.rooms", { count: n })} · ${t("dates.nights", { count: nights })}`
    )
  }
  return (
    <>
      <aside className="hidden lg:block" aria-label={t("summary.title")}>
        <div className="bk-card sticky top-20 p-5">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">{t("summary.title")}</h2>
          <SummaryBody>{action}</SummaryBody>
        </div>
      </aside>
      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface/97 px-4 py-3 shadow-[0_-8px_24px_rgb(22_24_29/0.08)] backdrop-blur lg:hidden">
        <div className="mx-auto flex max-w-3xl items-center gap-3">
          <button
            type="button"
            className="min-w-0 flex-1 rounded-ui text-left"
            onClick={() => setOpen(true)}
            aria-haspopup="dialog"
          >
            <span className="block truncate text-sm font-semibold">{compactLabel}</span>
            <span className="text-xs font-medium text-brand-ink underline underline-offset-2">{t("summary.view")}</span>
          </button>
          {action && <div className="flex-none">{action}</div>}
        </div>
      </div>
      <Dialog open={open} onClose={() => setOpen(false)} title={t("summary.title")} closeLabel={t("common.close")} variant="sheet">
        <SummaryBody />
      </Dialog>
    </>
  )
}
