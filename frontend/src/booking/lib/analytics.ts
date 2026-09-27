// Third-party analytics (GA4 / GTM / Meta pixel) configured per booking site. When the
// site enables the consent banner, nothing is loaded until the guest agrees; the
// choice is remembered per site in this browser only. IDs are validated so a
// misconfigured value can never become script injection (lib/analyticsIds.ts: the same rule as
// the admin form and the server, G-62).
import type { Site } from "../types"
import { analyticsId } from "./analyticsIds.ts"
import { getItem, setItem } from "./storage.ts"

export type Consent = "granted" | "denied" | null

export function trackers(site: Site) {
  const a = site.analytics || ({} as Site["analytics"])
  return {
    ga4: analyticsId("ga4", a.ga4),
    gtm: analyticsId("gtm", a.gtm),
    pixel: analyticsId("pixel", a.meta_pixel),
  }
}

export function hasTrackers(site: Site) {
  const t = trackers(site)
  return !!(t.ga4 || t.gtm || t.pixel)
}

export function storedConsent(site: string): Consent {
  const v = getItem(`tex.consent.${site}`, "local")
  return v === "granted" || v === "denied" ? v : null
}

export function saveConsent(site: string, c: Exclude<Consent, null>) {
  setItem(`tex.consent.${site}`, c, "local")
}

let loaded = false

function script(src: string) {
  const s = document.createElement("script")
  s.async = true
  s.src = src
  document.head.appendChild(s)
}

type W = Window & { dataLayer?: unknown[]; gtag?: (...a: unknown[]) => void; fbq?: ((...a: unknown[]) => void) & { queue?: unknown[]; loaded?: boolean; version?: string; callMethod?: unknown; push?: unknown } }

export function loadAnalytics(site: Site) {
  if (loaded) return
  const t = trackers(site)
  if (!t.ga4 && !t.gtm && !t.pixel) return
  loaded = true
  const w = window as W
  w.dataLayer = w.dataLayer || []
  if (t.gtm) {
    w.dataLayer.push({ "gtm.start": Date.now(), event: "gtm.js" })
    script(`https://www.googletagmanager.com/gtm.js?id=${encodeURIComponent(t.gtm)}`)
  }
  if (t.ga4) {
    w.gtag = function gtag() {
      // eslint-disable-next-line prefer-rest-params
      w.dataLayer!.push(arguments)
    }
    w.gtag("js", new Date())
    w.gtag("config", t.ga4, { anonymize_ip: true })
    script(`https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(t.ga4)}`)
  }
  if (t.pixel) {
    const q: unknown[] = []
    const fbq = function (...args: unknown[]) {
      q.push(args)
    } as NonNullable<W["fbq"]>
    fbq.queue = q
    fbq.loaded = true
    fbq.version = "2.0"
    w.fbq = fbq
    fbq("init", t.pixel)
    fbq("track", "PageView")
    script("https://connect.facebook.net/en_US/fbevents.js")
  }
}

/** Funnel milestone for the hotel's own analytics (only once they are loaded). */
export function analyticsEvent(name: string, params: Record<string, unknown> = {}) {
  if (!loaded) return
  const w = window as W
  try {
    w.gtag?.("event", name, params)
    w.dataLayer?.push({ event: `tex_${name}`, ...params })
  } catch {
    /* ignore */
  }
}
