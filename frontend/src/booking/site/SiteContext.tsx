import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
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

/** Site data per slug and language (the server localises hotel content by Accept-Language). */
const cache = new Map<string, Site>()

export function useSiteData(slug: string | undefined) {
  const { lang } = useI18n()
  const ck = `${slug ?? ""}|${lang}`
  // the site shown and the slug it was loaded for (kept while another language loads)
  const [shown, setShown] = useState<{ slug: string; site: Site } | null>(() => {
    const hit = slug ? cache.get(ck) : undefined
    return slug && hit ? { slug, site: hit } : null
  })
  const shownRef = useRef(shown)
  useEffect(() => {
    shownRef.current = shown
  }, [shown])
  const [error, setError] = useState<ApiError | null>(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!slug) return
    const hit = cache.get(ck)
    if (hit) {
      setShown({ slug, site: hit })
      return
    }
    const ctl = new AbortController()
    setError(null)
    pub<Site>("site", { slug }, ctl.signal)
      .then((s) => {
        cache.set(ck, s)
        setShown({ slug, site: s })
      })
      .catch((e: unknown) => {
        if ((e as Error).name === "AbortError") return
        // after a language switch, keep showing the site in the previous language
        if (shownRef.current?.slug !== slug) setError(e instanceof ApiError ? e : new ApiError("", 0, "", "network"))
      })
    return () => ctl.abort()
  }, [slug, ck, attempt])
  return { site: shown && shown.slug === slug ? shown.site : null, error, retry: () => setAttempt((n) => n + 1) }
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
