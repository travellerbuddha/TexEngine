import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react"
import { detectLang, useI18n } from "../i18n"
import { hasTrackers, loadAnalytics, saveConsent, storedConsent, type Consent } from "../lib/analytics"
import { ApiError, pub } from "../lib/api"
import { applyTheme, themeFrom, type Theme } from "../lib/branding"
import type { Hotel, Site } from "../types"

interface SiteCtx {
  site: Site
  theme: Theme
  hotel: (name: string | null | undefined) => Hotel | undefined
  consent: Consent
  needsConsent: boolean
  setConsent: (c: Exclude<Consent, null>) => void
  reopenConsent: () => void
}

const Ctx = createContext<SiteCtx | null>(null)

const cache = new Map<string, Site>()

export function useSiteData(slug: string | undefined) {
  const [site, setSite] = useState<Site | null>(() => (slug ? cache.get(slug) ?? null : null))
  const [error, setError] = useState<ApiError | null>(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!slug) return
    if (cache.has(slug)) {
      setSite(cache.get(slug)!)
      return
    }
    const ctl = new AbortController()
    setError(null)
    pub<Site>("site", { slug }, ctl.signal)
      .then((s) => {
        cache.set(slug, s)
        setSite(s)
      })
      .catch((e: unknown) => {
        if ((e as Error).name !== "AbortError") setError(e instanceof ApiError ? e : new ApiError("", 0, "", "network"))
      })
    return () => ctl.abort()
  }, [slug, attempt])
  return { site, error, retry: () => setAttempt((n) => n + 1) }
}

export function SiteProvider({ site, children }: { site: Site; children: ReactNode }) {
  const { lang, setLang } = useI18n()
  const theme = useMemo(() => themeFrom(site.branding), [site])
  const [consent, setConsentState] = useState<Consent>(() => storedConsent(site.slug))
  const [reopened, setReopened] = useState(false)

  useEffect(() => {
    applyTheme(theme, site.branding?.font)
  }, [theme, site])

  // keep the language within what the site offers
  useEffect(() => {
    const offered = site.languages?.length ? site.languages : null
    if (offered && !offered.includes(lang)) setLang(detectLang(offered, site.default_language))
  }, [site, lang, setLang])

  const trackersConfigured = hasTrackers(site)
  const bannerOn = !!site.analytics?.consent_banner

  useEffect(() => {
    if (!trackersConfigured) return
    if (!bannerOn || consent === "granted") loadAnalytics(site)
  }, [site, consent, bannerOn, trackersConfigured])

  const setConsent = useCallback(
    (c: Exclude<Consent, null>) => {
      saveConsent(site.slug, c)
      setConsentState(c)
      setReopened(false)
    },
    [site.slug],
  )

  const value = useMemo<SiteCtx>(
    () => ({
      site,
      theme,
      hotel: (name) => site.hotels.find((h) => h.name === name),
      consent,
      needsConsent: trackersConfigured && bannerOn && (consent === null || reopened),
      setConsent,
      reopenConsent: () => setReopened(true),
    }),
    [site, theme, consent, trackersConfigured, bannerOn, reopened, setConsent],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSite(): SiteCtx {
  const v = useContext(Ctx)
  if (!v) throw new Error("useSite outside SiteProvider")
  return v
}

export function useOptionalSite(): SiteCtx | null {
  return useContext(Ctx)
}

export type SiteTextKey = "headline" | "tagline" | "search_button" | "confirmation_note" | "footer_note"

/** Hotel-authored text from site().texts ({ "<lang>": { headline, … } }): the current
 * language, then the site's default language, else null (the caller's built-in
 * default). Always plain text — rendered as React text, never as HTML. */
export function siteText(site: Site, lang: string, key: SiteTextKey): string | null {
  const texts = (site.texts ?? {}) as Record<string, unknown>
  for (const l of [lang, site.default_language]) {
    const block = l ? texts[l] : null
    if (block && typeof block === "object") {
      const v = (block as Record<string, unknown>)[key]
      if (typeof v === "string" && v.trim()) return v.trim()
    }
  }
  return null
}

export function useSiteText() {
  const { site } = useSite()
  const { lang } = useI18n()
  return (key: SiteTextKey) => siteText(site, lang, key)
}
