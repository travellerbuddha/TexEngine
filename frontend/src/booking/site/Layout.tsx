import { Globe, Mail, MapPin, MessageCircle, Phone } from "lucide-react"
import { useId, useState, type ReactNode } from "react"
import { useSearchParams } from "react-router-dom"
import { isLang, LANGS, localText, useI18n, type Lang } from "../i18n"
import { safeImage } from "../lib/branding"
import { isEmbedded } from "../lib/storage"
import { Button } from "../ui/controls"
import { Dialog } from "../ui/Dialog"
import { useSite } from "./SiteContext"

function LanguageSelect() {
  const { t, lang, setLang } = useI18n()
  const { site } = useSite()
  const [sp, setSp] = useSearchParams()
  const id = useId()
  const offered = LANGS.filter((l) => !site.languages?.length || site.languages.includes(l.code))
  if (offered.length < 2) return null
  return (
    <div className="relative flex items-center">
      <label htmlFor={id} className="sr-only">
        {t("header.language")}
      </label>
      <Globe className="pointer-events-none absolute left-2.5 size-4 text-muted" aria-hidden />
      <select
        id={id}
        value={lang}
        onChange={(e) => {
          const v = e.target.value
          if (!isLang(v)) return
          setLang(v as Lang)
          if (sp.has("lang")) {
            const next = new URLSearchParams(sp)
            next.set("lang", v)
            setSp(next, { replace: true })
          }
        }}
        className="h-10 appearance-none rounded-ui border border-line bg-surface py-1 pl-8 pr-3 text-sm font-medium text-soft hover:border-line-strong"
      >
        {offered.map((l) => (
          <option key={l.code} value={l.code} lang={l.code}>
            {l.label}
          </option>
        ))}
      </select>
    </div>
  )
}

function CurrencySelect() {
  const { t } = useI18n()
  const { site } = useSite()
  const [sp, setSp] = useSearchParams()
  const id = useId()
  if ((site.currencies?.length ?? 0) < 2) return null
  const current = sp.get("currency") || site.default_currency || site.currencies[0]
  return (
    <div className="flex items-center">
      <label htmlFor={id} className="sr-only">
        {t("header.currency")}
      </label>
      <select
        id={id}
        value={current}
        onChange={(e) => {
          const next = new URLSearchParams(sp)
          next.set("currency", e.target.value)
          next.delete("step")
          setSp(next)
        }}
        className="h-10 appearance-none rounded-ui border border-line bg-surface px-3 text-sm font-medium text-soft hover:border-line-strong"
      >
        {site.currencies.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
    </div>
  )
}

export function Brand({ compact }: { compact?: boolean }) {
  const { site } = useSite()
  const logo = safeImage(site.branding?.logo)
  return logo ? (
    <img src={logo} alt={site.name} className={compact ? "h-8 w-auto" : "h-9 w-auto max-w-[180px] object-contain"} />
  ) : (
    <span className={`font-heading leading-tight ${compact ? "text-base" : "text-lg sm:text-xl"}`} style={{ fontWeight: "var(--bk-heading-weight)" }}>
      {site.name}
    </span>
  )
}

export function Header({ home }: { home?: string }) {
  const { site, theme } = useSite()
  const { t } = useI18n()
  const embedded = isEmbedded()
  const phone = site.contact?.phone
  const brand = home ? (
    <a href={home} className="inline-flex min-h-10 items-center rounded-ui" aria-label={t("header.home", { name: site.name })}>
      <Brand compact={embedded} />
    </a>
  ) : (
    <Brand compact={embedded} />
  )
  const controls = (
    <div className="flex items-center gap-2">
      {phone && theme.header !== "split" && !embedded && (
        <a href={`tel:${phone.replace(/[^\d+]/g, "")}`} className="hidden h-10 items-center gap-2 rounded-ui px-2 text-sm font-medium text-soft hover:text-ink md:inline-flex">
          <Phone className="size-4" aria-hidden />
          {phone}
        </a>
      )}
      <LanguageSelect />
      <CurrencySelect />
    </div>
  )
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur supports-[backdrop-filter]:bg-surface/85">
      <a href="#bk-main" className="sr-only-focusable absolute left-2 top-2 z-50 rounded-ui bg-ink px-3 py-2 text-sm font-semibold text-white">
        {t("a11y.skip")}
      </a>
      {theme.header === "center" ? (
        <div className="mx-auto grid max-w-6xl grid-cols-[1fr_auto_1fr] items-center gap-2 px-4 py-2.5 sm:px-6">
          <span />
          <div className="justify-self-center">{brand}</div>
          <div className="justify-self-end">{controls}</div>
        </div>
      ) : (
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-2.5 sm:px-6">
          {brand}
          {theme.header === "split" && phone && !embedded && (
            <a href={`tel:${phone.replace(/[^\d+]/g, "")}`} className="hidden items-center gap-2 text-sm font-medium text-soft hover:text-ink md:inline-flex">
              <Phone className="size-4" aria-hidden />
              {phone}
            </a>
          )}
          {controls}
        </div>
      )}
    </header>
  )
}

export function Footer() {
  const { site, needsConsent, reopenConsent } = useSite()
  const { t, lang } = useI18n()
  const [policies, setPolicies] = useState(false)
  const c = site.contact || {}
  const wa = c.whatsapp?.replace(/[^\d]/g, "")
  const note = localText(site.texts?.footer_note, lang)
  const hasTrackers = !!(site.analytics?.ga4 || site.analytics?.gtm || site.analytics?.meta_pixel)
  return (
    <footer className="mt-16 border-t border-line bg-surface">
      <div className="mx-auto grid max-w-6xl gap-6 px-4 py-8 text-sm text-soft sm:grid-cols-[1.4fr_1fr] sm:px-6">
        <div>
          <p className="font-semibold text-ink">{site.name}</p>
          {note && <p className="mt-1 max-w-prose text-muted">{note}</p>}
          <ul className="mt-3 space-y-1.5">
            {c.phone && (
              <li>
                <a className="inline-flex min-h-6 items-center gap-2 hover:text-ink" href={`tel:${c.phone.replace(/[^\d+]/g, "")}`}>
                  <Phone className="size-4" aria-hidden /> {c.phone}
                </a>
              </li>
            )}
            {c.email && (
              <li>
                <a className="inline-flex min-h-6 items-center gap-2 hover:text-ink" href={`mailto:${c.email}`}>
                  <Mail className="size-4" aria-hidden /> {c.email}
                </a>
              </li>
            )}
            {wa && (
              <li>
                <a className="inline-flex min-h-6 items-center gap-2 hover:text-ink" href={`https://wa.me/${wa}`} rel="noopener noreferrer" target="_blank">
                  <MessageCircle className="size-4" aria-hidden /> WhatsApp
                </a>
              </li>
            )}
            {c.address && (
              <li className="flex items-start gap-2">
                <MapPin className="mt-0.5 size-4 flex-none" aria-hidden /> <span className="whitespace-pre-line">{c.address}</span>
              </li>
            )}
          </ul>
        </div>
        <div className="flex flex-col items-start gap-2 sm:items-end">
          {site.policies && (
            <button type="button" className="min-h-6 underline underline-offset-2 hover:text-ink" onClick={() => setPolicies(true)}>
              {t("footer.policies")}
            </button>
          )}
          {hasTrackers && site.analytics?.consent_banner && !needsConsent && (
            <button type="button" className="min-h-6 underline underline-offset-2 hover:text-ink" onClick={reopenConsent}>
              {t("footer.cookies")}
            </button>
          )}
          <p className="text-xs text-muted">{t("footer.poweredBy")}</p>
        </div>
      </div>
      <Dialog open={policies} onClose={() => setPolicies(false)} title={t("footer.policies")} closeLabel={t("common.close")}>
        <p className="whitespace-pre-line text-sm text-soft">{site.policies}</p>
      </Dialog>
    </footer>
  )
}

export function ConsentBanner() {
  const { site, needsConsent, setConsent, consent } = useSite()
  const { t } = useI18n()
  const id = useId()
  if (!needsConsent) return null
  const withdraw = (c: "granted" | "denied") => {
    const wasGranted = consent === "granted"
    setConsent(c)
    // loaded trackers cannot be unloaded: a fresh page honours the withdrawal
    if (wasGranted && c === "denied") window.location.reload()
  }
  return (
    <section
      aria-labelledby={id}
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface p-4 shadow-[0_-8px_24px_rgb(22_24_29/0.08)] sm:inset-x-auto sm:bottom-4 sm:left-4 sm:max-w-md sm:rounded-card sm:border"
    >
      <h2 id={id} className="text-base">
        {t("consent.title")}
      </h2>
      <p className="mt-1 text-sm text-soft">{t("consent.body", { name: site.name })}</p>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Button variant="secondary" onClick={() => withdraw("denied")}>
          {t("consent.decline")}
        </Button>
        <Button variant="secondary" onClick={() => withdraw("granted")}>
          {t("consent.accept")}
        </Button>
      </div>
    </section>
  )
}

export function Shell({ children, home }: { children: ReactNode; home?: string }) {
  const embedded = isEmbedded()
  return (
    <div className="flex min-h-dvh flex-col">
      <Header home={home} />
      <main id="bk-main" tabIndex={-1} className="flex-1 outline-none">
        {children}
      </main>
      {!embedded && <Footer />}
      <ConsentBanner />
    </div>
  )
}
