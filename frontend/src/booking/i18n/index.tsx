// Guest booking i18n (R-49): a small key-based catalog per language, independent of
// the admin catalogs so the guest bundle stays small. English is bundled as the
// fallback; other languages load on demand. Plural entries use Intl.PluralRules
// categories ({ "one": …, "few": …, "many": …, "other": … }) with a {count} value.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react"
import { setApiLanguage } from "../lib/api"
import { formatDate, formatDateTime, formatDay, formatMoney, formatRange, formatTime } from "../lib/format"
import { getItem, setItem } from "../lib/storage"
import en from "./en.json"

export const LANGS = [
  { code: "en", label: "English", intl: "en-GB" },
  { code: "tr", label: "Türkçe", intl: "tr-TR" },
  { code: "de", label: "Deutsch", intl: "de-DE" },
  { code: "ru", label: "Русский", intl: "ru-RU" },
  { code: "ro", label: "Română", intl: "ro-RO" },
  { code: "pl", label: "Polski", intl: "pl-PL" },
] as const

export type Lang = (typeof LANGS)[number]["code"]
export type MessageKey = keyof typeof en
type Plural = { zero?: string; one?: string; two?: string; few?: string; many?: string; other: string }
export type Catalog = Record<string, string | Plural>
export type Vars = Record<string, string | number>

const CODES = new Set<string>(LANGS.map((l) => l.code))

const loaders: Record<Exclude<Lang, "en">, () => Promise<{ default: Catalog }>> = {
  tr: () => import("./tr.json"),
  de: () => import("./de.json"),
  ru: () => import("./ru.json"),
  ro: () => import("./ro.json"),
  pl: () => import("./pl.json"),
}

const loaded: Partial<Record<Lang, Catalog>> = { en: en as Catalog }

export function isLang(v: string | null | undefined): v is Lang {
  return !!v && CODES.has(v)
}

export function intlLocale(lang: Lang) {
  return LANGS.find((l) => l.code === lang)?.intl ?? "en-GB"
}

const PREF = "tex.book.lang"

/** URL ?lang= → saved choice → browser language → site default → English,
 * restricted to the languages the site offers. */
export function detectLang(offered?: string[] | null, siteDefault?: string | null): Lang {
  const allowed = (offered?.length ? offered : LANGS.map((l) => l.code)).filter(isLang)
  const ok = (v: string | null | undefined): v is Lang => isLang(v) && allowed.includes(v)
  let fromUrl: string | null = null
  try {
    fromUrl = new URLSearchParams(window.location.search).get("lang")
  } catch {
    /* ignore */
  }
  if (ok(fromUrl)) return fromUrl
  const saved = getItem(PREF, "local")
  if (ok(saved)) return saved
  for (const nav of navigator.languages ?? [navigator.language]) {
    const code = (nav || "").slice(0, 2).toLowerCase()
    if (ok(code)) return code
  }
  if (ok(siteDefault)) return siteDefault
  return allowed[0] ?? "en"
}

function interpolate(s: string, vars?: Vars) {
  if (!vars) return s
  return s.replace(/\{(\w+)\}/g, (m, k: string) => (vars[k] !== undefined ? String(vars[k]) : m))
}

function translate(cat: Catalog, locale: string, key: string, vars?: Vars): string {
  const entry = cat[key] ?? (en as Catalog)[key]
  if (entry === undefined) return key
  if (typeof entry === "string") return interpolate(entry, vars)
  const count = Number(vars?.count ?? 0)
  const rule = count === 0 && entry.zero ? "zero" : new Intl.PluralRules(locale).select(count)
  return interpolate((entry as Record<string, string>)[rule] ?? entry.other, vars)
}

export interface I18n {
  lang: Lang
  locale: string
  t: (key: MessageKey, vars?: Vars) => string
  setLang: (l: Lang) => void
  money: (amount: string | null | undefined, ccy: string | null | undefined) => string
  date: (v: string | null | undefined, opts?: Intl.DateTimeFormatOptions) => string
  day: (v: string) => string
  range: (a: string, b: string) => string
  dateTime: (v: string | null | undefined) => string
  time: (v: string | null | undefined) => string
}

const Ctx = createContext<I18n | null>(null)

export function I18nProvider({ initial, children }: { initial: Lang; children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initial)
  const [cat, setCat] = useState<Catalog>(() => loaded[initial] ?? (en as Catalog))

  useEffect(() => {
    let alive = true
    setApiLanguage(lang)
    document.documentElement.lang = lang
    const have = loaded[lang]
    if (have) setCat(have)
    else if (lang !== "en")
      loaders[lang]()
        .then((m) => {
          loaded[lang] = m.default
          if (alive) setCat(m.default)
        })
        .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [lang])

  const setLang = useCallback((l: Lang) => {
    setItem(PREF, l, "local")
    setLangState(l)
  }, [])

  const value = useMemo<I18n>(() => {
    const locale = intlLocale(lang)
    return {
      lang,
      locale,
      t: (key, vars) => translate(cat, locale, key, vars),
      setLang,
      money: (amount, ccy) => formatMoney(amount, ccy, locale),
      date: (v, opts) => formatDate(v, locale, opts),
      day: (v) => formatDay(v, locale),
      range: (a, b) => formatRange(a, b, locale),
      dateTime: (v) => formatDateTime(v, locale),
      time: (v) => formatTime(v, locale),
    }
  }, [lang, cat, setLang])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useI18n(): I18n {
  const v = useContext(Ctx)
  if (!v) throw new Error("useI18n outside I18nProvider")
  return v
}

