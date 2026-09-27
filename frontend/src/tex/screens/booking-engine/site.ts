// TEX Booking Site model, defaults and client-side validation. The server
// (tex_booking_site.py) re-validates everything; these rules mirror it so users
// see problems before saving.
import { analyticsId } from "../../../booking/lib/analyticsIds.ts"

/** A custom booking host (ADR-035). `verified`, `verified_at`, `last_checked_at` and
 * `check_failures` are written only by the server's DNS check: read-only here, and the
 * server ignores them on save. */
export interface SiteDomain {
  domain: string
  is_primary: number
  verified: number
  verification_token?: string | null
  verified_at?: string | null
  last_checked_at?: string | null
  check_failures?: number | null
}

export interface Site {
  name?: string
  modified?: string
  site_name: string
  site_slug: string
  enabled: number
  property: string | null
  hotel_group: string | null
  default_language: string
  languages: string
  default_currency: string | null
  currencies: string | null
  default_market: string | null
  sales_channel: string | null
  self_service_enabled: number
  logo: string | null
  primary_color: string
  accent_color: string
  background_color: string
  font_family: string
  radius: string
  card_radius: string
  button_style: string
  header_layout: string
  search_style: string
  hero_image: string | null
  contact_phone: string | null
  contact_email: string | null
  whatsapp: string | null
  address: string | null
  custom_texts: string | null
  policies: string | null
  allowed_embed_origins: string | null
  widget_mode: string
  domains: SiteDomain[]
  ga4_measurement_id: string | null
  gtm_container_id: string | null
  meta_pixel_id: string | null
  consent_banner: number
}

export const SITE_LANGS = ["en", "tr", "de", "ru", "ro", "pl"] as const
export const FONTS = ["Inter", "DM Sans", "Nunito Sans", "Source Sans 3", "Lora", "Playfair Display", "System"] as const
export const RADII = ["none", "sm", "md", "lg", "xl"] as const
export const BUTTON_STYLES = ["solid", "outline", "pill"] as const
export const HEADER_LAYOUTS = ["left", "center", "split"] as const
export const SEARCH_STYLES = ["inline", "card", "overlay"] as const
export const WIDGET_MODES = ["search", "button", "modal", "redirect"] as const
export const RESERVED_SLUGS = ["pay", "api", "assets", "manage", "widget"]
/** The admin area's own pages (/tex/booking-engine/<page>): refused as the slug of a new site or a
 * site moved to another slug (G-64 review M3; kamra TEX Booking Site.ADMIN_SLUGS). */
export const ADMIN_SLUGS = ["new", "sites", "content", "rooms", "analytics"]

/** Keys of the per-language custom texts the guest booking pages read. */
export const TEXT_KEYS = ["headline", "tagline", "search_button", "confirmation_note", "footer_note"] as const

export const FONT_STACK: Record<string, string> = {
  Inter: "Inter, ui-sans-serif, system-ui, sans-serif",
  "DM Sans": "'DM Sans', ui-sans-serif, system-ui, sans-serif",
  "Nunito Sans": "'Nunito Sans', ui-sans-serif, system-ui, sans-serif",
  "Source Sans 3": "'Source Sans 3', ui-sans-serif, system-ui, sans-serif",
  Lora: "Lora, Georgia, serif",
  "Playfair Display": "'Playfair Display', Georgia, serif",
  System: "system-ui, -apple-system, 'Segoe UI', sans-serif",
}

export const RADIUS_PX: Record<string, number> = { none: 0, sm: 4, md: 8, lg: 12, xl: 18 }

export function newSite(property?: string): Site {
  return {
    site_name: "",
    site_slug: "",
    enabled: 1,
    property: property ?? null,
    hotel_group: null,
    default_language: "en",
    languages: SITE_LANGS.join(","),
    default_currency: null,
    currencies: null,
    default_market: null,
    sales_channel: null,
    self_service_enabled: 1,
    logo: null,
    primary_color: "#0B3B5B",
    accent_color: "#C8963E",
    background_color: "#F7F7F5",
    font_family: "Inter",
    radius: "md",
    card_radius: "lg",
    button_style: "solid",
    header_layout: "left",
    search_style: "card",
    hero_image: null,
    contact_phone: null,
    contact_email: null,
    whatsapp: null,
    address: null,
    custom_texts: null,
    policies: null,
    allowed_embed_origins: "",
    widget_mode: "search",
    domains: [],
    ga4_measurement_id: null,
    gtm_container_id: null,
    meta_pixel_id: null,
    consent_banner: 1,
  }
}

export const csv = (v: string | null | undefined) =>
  (v ?? "")
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean)

export const lines = (v: string | null | undefined) =>
  (v ?? "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean)

// ─── validation (mirrors tex_booking_site.py) ─────────────────────────────

export const HEX = /^#[0-9a-fA-F]{6}$/
export const ORIGIN = /^https:\/\/[a-z0-9.-]+(:\d+)?$/
/** A host name (book.hotel.com), never a path: the same rule as HOST in kamra/tex/services/sites.py. */
export const HOST = /^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/
/** A verified host that misses its TXT record on this many daily checks in a row is un-verified (sites.UNVERIFY_AFTER). */
export const UNVERIFY_AFTER = 3

export function normaliseSlug(s: string) {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+|-+$/g, "")
}

export function normaliseOrigin(s: string) {
  return s.trim().toLowerCase().replace(/\/+$/, "")
}

/** Like the server's normalize_host: lower case, without scheme, trailing slashes or dot. */
export function normaliseDomain(s: string) {
  return s
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, "")
    .replace(/\/+$/, "")
    .replace(/\.+$/, "")
}

/** Why a custom domain is refused (an i18n key), or null for a valid host name. A path
 * (hotel.com/book) gets its own message: TEX cannot serve a path on the hotel's own website. */
export function domainError(raw: string): string | null {
  const d = normaliseDomain(raw)
  if (HOST.test(d)) return null
  if (/[/?#]/.test(d)) return "be.err.domain_path"
  return "be.err.domain"
}

/** Images shown in the preview: uploaded files, app assets or https URLs only (no data:, javascript: …). */
export function safeImageUrl(u: string | null | undefined): string | null {
  const v = (u ?? "").trim()
  if (!v) return null
  if (/^\/(files|private\/files|assets)\/[^\s"'<>()]+$/.test(v)) return v
  if (/^https:\/\/[^\s"'<>()]+$/i.test(v)) return v
  return null
}

/** What the server accepts as a NEW logo or hero (G-83): a PNG, JPEG, GIF or WebP in the public
 * files, or an https address (the server also refuses the platform's own hosts). An image a site
 * already had is not judged again. */
export function newImageUrlOk(u: string | null | undefined): boolean {
  const v = (u ?? "").trim()
  if (/^\/files\/[A-Za-z0-9._-]+\.(png|jpe?g|gif|webp)$/i.test(v)) return !v.includes("..")
  return /^https:\/\/[a-z0-9.-]+(:\d+)?\/[^\s"'<>()`\\]+$/i.test(v)
}

export type TabId = "general" | "branding" | "texts" | "contact" | "analytics" | "embed" | "domains"
export type Errors = Partial<Record<string, string>>

/** Field errors keyed by field name (values are i18n keys). */
export function validateSite(s: Site, saved?: Site | null): Errors {
  const e: Errors = {}
  if (!s.site_name.trim()) e.site_name = "be.err.required"
  const slug = normaliseSlug(s.site_slug)
  if (!slug) e.site_slug = "be.err.required"
  else if (RESERVED_SLUGS.includes(slug) || (ADMIN_SLUGS.includes(slug) && slug !== saved?.site_slug)) e.site_slug = "be.err.slug_reserved"
  if (!s.property && !s.hotel_group) e.scope = "be.err.scope"
  const langs = csv(s.languages)
  if (!langs.length) e.languages = "be.err.languages"
  else if (!langs.includes(s.default_language)) e.default_language = "be.err.default_language"
  const ccys = csv(s.currencies)
  if (s.default_currency && ccys.length && !ccys.includes(s.default_currency)) e.default_currency = "be.err.default_currency"
  for (const f of ["primary_color", "accent_color", "background_color"] as const) if (s[f] && !HEX.test(s[f])) e[f] = "be.err.hex"
  for (const f of ["logo", "hero_image"] as const) if (s[f] && s[f] !== saved?.[f] && !newImageUrlOk(s[f])) e[f] = "be.err.image_url"
  if (s.contact_email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s.contact_email)) e.contact_email = "be.err.email"
  if (s.whatsapp && !/^\+?[0-9 ()-]{6,20}$/.test(s.whatsapp)) e.whatsapp = "be.err.phone"
  if (s.contact_phone && !/^\+?[0-9 ()./-]{6,24}$/.test(s.contact_phone)) e.contact_phone = "be.err.phone"
  // the engine's rule (G-62); like the images, an id the site already had is not judged again
  for (const [f, kind, err] of [
    ["ga4_measurement_id", "ga4", "be.err.ga4"],
    ["gtm_container_id", "gtm", "be.err.gtm"],
    ["meta_pixel_id", "pixel", "be.err.pixel"],
  ] as const)
    if (s[f]?.trim() && s[f] !== saved?.[f] && !analyticsId(kind, s[f])) e[f] = err
  if (lines(s.allowed_embed_origins).some((o) => !ORIGIN.test(normaliseOrigin(o)))) e.allowed_embed_origins = "be.err.origin"
  const badDomain = s.domains.map((d) => domainError(d.domain)).find(Boolean)
  if (badDomain) e.domains = badDomain
  else if (new Set(s.domains.map((d) => normaliseDomain(d.domain))).size < s.domains.length) e.domains = "be.domains.duplicate"
  else if (s.domains.filter((d) => d.is_primary).length > 1) e.domains = "be.err.one_primary"
  if (s.custom_texts) {
    try {
      const v = JSON.parse(s.custom_texts) as unknown
      if (typeof v !== "object" || v === null || Array.isArray(v)) e.custom_texts = "be.err.texts"
    } catch {
      e.custom_texts = "be.err.texts"
    }
  }
  return e
}

export const FIELD_TAB: Record<string, TabId> = {
  site_name: "general",
  site_slug: "general",
  scope: "general",
  languages: "general",
  default_language: "general",
  default_currency: "general",
  primary_color: "branding",
  accent_color: "branding",
  background_color: "branding",
  logo: "branding",
  hero_image: "branding",
  custom_texts: "texts",
  contact_email: "contact",
  contact_phone: "contact",
  whatsapp: "contact",
  ga4_measurement_id: "analytics",
  gtm_container_id: "analytics",
  meta_pixel_id: "analytics",
  allowed_embed_origins: "embed",
  domains: "domains",
}

// ─── colour contrast (WCAG 2.x) for the branding warnings ─────────────────

function lum(hex: string) {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}

export function contrast(a: string, b: string): number | null {
  if (!HEX.test(a) || !HEX.test(b)) return null
  const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m)
  return (x + 0.05) / (y + 0.05)
}

/** Readable text colour on a filled background. */
export function onColor(hex: string) {
  if (!HEX.test(hex)) return "#ffffff"
  return (contrast(hex, "#ffffff") ?? 0) >= (contrast(hex, "#111111") ?? 0) ? "#ffffff" : "#111111"
}

export type Texts = Record<string, Record<string, string> | string>

export function parseTexts(raw: string | null | undefined): Texts {
  if (!raw) return {}
  try {
    const v = JSON.parse(raw) as unknown
    return typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Texts) : {}
  } catch {
    return {}
  }
}

/** Serialise, dropping empty strings and empty languages. */
export function serialiseTexts(t: Texts): string | null {
  const out: Texts = {}
  for (const [lang, v] of Object.entries(t)) {
    if (typeof v === "string") {
      if (v.trim()) out[lang] = v
      continue
    }
    const kept = Object.fromEntries(Object.entries(v).filter(([, s]) => s.trim()))
    if (Object.keys(kept).length) out[lang] = kept
  }
  return Object.keys(out).length ? JSON.stringify(out) : null
}
