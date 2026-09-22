import { CalendarDays, MapPin, Pencil, Users } from "lucide-react"
import { lazy, Suspense, useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import { useI18n } from "../i18n"
import { safeImage } from "../lib/branding"
import { isComplete } from "../lib/criteria"
import { nightsBetween } from "../lib/dates"
import { isEmbedded } from "../lib/storage"
import { BookingProvider, useBooking } from "../flow/BookingContext"
import { guestsSummary } from "../search/GuestsPicker"
import { useWide } from "../search/DateRangePicker"
import { SearchForm } from "../search/SearchForm"
import { Shell } from "../site/Layout"
import { siteText, SiteProvider, useSite, useSiteData } from "../site/SiteContext"
import { Button } from "../ui/controls"
import { Spinner } from "../ui/feedback"
import { Photo } from "../ui/Photo"
import { SiteError } from "./SiteError"

const Results = lazy(() => import("../results/Results"))
const Checkout = lazy(() => import("../checkout/Checkout"))

function Loading() {
  const { t } = useI18n()
  return (
    <div className="grid min-h-40 place-items-center py-10">
      <Spinner label={t("common.loading")} />
    </div>
  )
}

function Hero({ compact }: { compact: boolean }) {
  const { site, theme } = useSite()
  const { t, lang } = useI18n()
  const hero = safeImage(site.branding?.hero_image) ?? safeImage(site.hotels[0]?.hero_image) ?? safeImage(site.hotels[0]?.gallery?.[0]?.url)
  const title = siteText(site, lang, "headline") ?? site.name
  const subtitle = siteText(site, lang, "tagline") ?? (site.group ? t("home.subtitleGroup", { count: site.hotels.length }) : t("home.subtitle"))
  if (compact || theme.searchStyle === "inline") {
    return (
      <div className="mx-auto max-w-6xl px-4 pt-6 sm:px-6">
        <h1 className="text-2xl sm:text-3xl">{title}</h1>
        {!compact && subtitle && <p className="mt-1 text-soft">{subtitle}</p>}
      </div>
    )
  }
  const overlay = theme.searchStyle === "overlay"
  return (
    <div className={`relative overflow-hidden ${overlay ? "min-h-[440px] sm:min-h-[520px]" : "min-h-[240px] sm:min-h-[340px]"}`}>
      {hero ? (
        <img src={hero} alt="" className="absolute inset-0 size-full object-cover" fetchPriority="high" />
      ) : (
        <div
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(90% 120% at 85% 0%, color-mix(in oklab, var(--bk-accent) 45%, transparent) 0%, transparent 55%), linear-gradient(135deg, color-mix(in oklab, var(--bk-primary) 92%, black) 0%, var(--bk-primary) 55%, color-mix(in oklab, var(--bk-primary) 70%, white) 100%)",
          }}
          aria-hidden
        />
      )}
      <div className="absolute inset-0 bg-gradient-to-b from-black/10 via-black/25 to-black/55" aria-hidden />
      <div className="bk-on-dark relative mx-auto flex h-full max-w-6xl flex-col justify-end px-4 pb-20 pt-14 text-white sm:px-6 sm:pb-24 sm:pt-20">
        <h1 className="max-w-2xl text-3xl leading-tight drop-shadow-sm sm:text-5xl">{title}</h1>
        {subtitle && <p className="mt-2 max-w-xl text-base text-white/90 sm:text-lg">{subtitle}</p>}
      </div>
    </div>
  )
}

function SearchSummaryBar({ onEdit }: { onEdit: () => void }) {
  const { t, range } = useI18n()
  const { criteria, hotelName } = useBooking()
  const nights = nightsBetween(criteria.checkIn!, criteria.checkOut!)
  return (
    <div className="bk-card flex items-center gap-3 p-3">
      <div className="min-w-0 flex-1 text-sm">
        {hotelName && (
          <p className="flex items-center gap-1.5 truncate font-semibold">
            <MapPin className="size-4 flex-none text-muted" aria-hidden />
            {hotelName}
          </p>
        )}
        <p className="flex items-start gap-1.5">
          <CalendarDays className="mt-0.5 size-4 flex-none text-muted" aria-hidden />
          <span>
            {range(criteria.checkIn!, criteria.checkOut!)} · {t("dates.nights", { count: nights })}
          </span>
        </p>
        <p className="flex items-start gap-1.5 text-muted">
          <Users className="mt-0.5 size-4 flex-none" aria-hidden />
          {guestsSummary(t, criteria.rooms)}
        </p>
      </div>
      <Button variant="secondary" size="sm" onClick={onEdit} aria-expanded={false}>
        <Pencil className="size-4" aria-hidden />
        {t("search.edit")}
      </Button>
    </div>
  )
}

function Intro() {
  const { site } = useSite()
  const { t } = useI18n()
  const { criteria, setCriteria } = useBooking()
  if (!site.group || site.hotels.length < 2)
    return site.hotels[0]?.showcase_description ? (
      <section className="mx-auto mt-10 max-w-3xl px-4 text-center text-soft sm:px-6">
        <p className="whitespace-pre-line">{site.hotels[0].showcase_description}</p>
      </section>
    ) : null
  return (
    <section className="mx-auto mt-10 max-w-6xl px-4 sm:px-6" aria-labelledby="bk-our-hotels">
      <h2 id="bk-our-hotels" className="text-xl sm:text-2xl">
        {t("home.ourHotels")}
      </h2>
      <ul className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {site.hotels.map((h) => (
          <li key={h.name} className="bk-card overflow-hidden">
            <Photo src={h.hero_image ?? h.gallery?.[0]?.url} alt={h.property_name} kind="hotel" className="aspect-[16/9] w-full" />
            <div className="p-4">
              <h3 className="text-lg">{h.property_name}</h3>
              {h.city && <p className="text-sm text-muted">{h.city}</p>}
              <Button
                variant="secondary"
                size="sm"
                className="mt-3"
                onClick={() => {
                  setCriteria({ ...criteria, hotel: h.name }, { replace: true })
                  window.scrollTo({ top: 0, behavior: "smooth" })
                  requestAnimationFrame(() => document.querySelector<HTMLButtonElement>("form[role=search] [aria-haspopup=dialog]")?.focus())
                }}
                aria-label={t("home.checkDatesAt", { name: h.property_name })}
              >
                {t("home.checkDates")}
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function SiteHome() {
  const { site, theme } = useSite()
  const { t } = useI18n()
  const { step, criteria, setCriteria, search, hotelName } = useBooking()
  const wide = useWide("(min-width: 768px)")
  const [editing, setEditing] = useState(false)
  const searched = isComplete(criteria)
  const embedded = isEmbedded()

  useEffect(() => {
    const what =
      step === "extras" ? t("steps.extras") : step === "details" ? t("steps.details") : step === "payment" ? t("steps.payment") : searched ? t("steps.rooms") : null
    document.title = [what, hotelName && searched ? hotelName : site.name].filter(Boolean).join(" · ")
  }, [step, searched, site.name, hotelName, t])

  useEffect(() => setEditing(false), [criteria])

  if (step !== "rooms")
    return (
      <Shell>
        <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
          <Suspense fallback={<Loading />}>
            <Checkout />
          </Suspense>
        </div>
      </Shell>
    )

  const compact = searched || embedded
  const form = (
    <SearchForm
      value={criteria}
      onSearch={(c) => setCriteria(c)}
      busy={search.status === "loading"}
      variant={compact ? "bar" : theme.searchStyle === "overlay" ? "overlay" : theme.searchStyle === "inline" ? "inline" : "card"}
    />
  )
  return (
    <Shell>
      {searched ? <h1 className="sr-only">{t("results.title", { name: hotelName ?? site.name })}</h1> : <Hero compact={embedded} />}
      <div className={`mx-auto max-w-6xl px-4 sm:px-6 ${!compact && theme.searchStyle !== "inline" ? "relative -mt-14 sm:-mt-16" : "mt-4"}`}>
        {searched && !wide && !editing ? <SearchSummaryBar onEdit={() => setEditing(true)} /> : form}
      </div>
      {searched ? (
        <div className="mx-auto mt-6 max-w-6xl px-4 sm:px-6">
          <Suspense fallback={<Loading />}>
            <Results />
          </Suspense>
        </div>
      ) : (
        <Intro />
      )}
    </Shell>
  )
}

export default function SitePage() {
  const { site: slug } = useParams()
  const { site, error, retry } = useSiteData(slug)
  if (error) return <SiteError error={error} onRetry={retry} />
  if (!site) return <Loading />
  return (
    <SiteProvider site={site}>
      <BookingProvider>
        <SiteHome />
      </BookingProvider>
    </SiteProvider>
  )
}
