// TEX i18n (ADR-013): key-based catalogs per area and language. Areas live in
// locales/<area>/<lang>.json so feature teams never edit the same file. English is
// bundled (it is the fallback); every other language is one lazy chunk loaded when
// chosen. Missing keys fall back to English, then to the key itself.
import { useCallback, useEffect, useState } from "react"

export const TEX_LANGS = [
  { code: "en", label: "English", intl: "en-GB" },
  { code: "tr", label: "Türkçe", intl: "tr-TR" },
  { code: "de", label: "Deutsch", intl: "de-DE" },
  { code: "ru", label: "Русский", intl: "ru-RU" },
  { code: "ro", label: "Română", intl: "ro-RO" },
  { code: "pl", label: "Polski", intl: "pl-PL" },
] as const

export type TexLang = (typeof TEX_LANGS)[number]["code"]
type Plural = { zero?: string; one?: string; few?: string; many?: string; other: string }
type Entry = string | Plural
type Catalog = Record<string, Entry>

const english = import.meta.glob("./locales/*/en.json", { eager: true, import: "default" }) as Record<string, Catalog>
const lazyFiles = import.meta.glob(["./locales/*/*.json", "!./locales/*/en.json"], { import: "default" }) as Record<
  string,
  () => Promise<Catalog>
>

const CATALOGS: Record<string, Catalog> = { en: Object.assign({}, ...Object.values(english)) as Catalog }
const loading = new Map<string, Promise<void>>()

/** Load a language's catalogs (all areas); resolves at once for English or when loaded. */
export function loadTexLang(lang: string): Promise<void> {
  if (CATALOGS[lang]) return Promise.resolve()
  let p = loading.get(lang)
  if (!p) {
    const parts = Object.entries(lazyFiles).filter(([path]) => path.endsWith(`/${lang}.json`))
    p = Promise.all(parts.map(([, load]) => load()))
      .then((cats) => {
        CATALOGS[lang] = Object.assign({}, ...cats) as Catalog
        window.dispatchEvent(new Event("tex:lang"))
      })
      .catch(() => {
        // offline or a stale deploy: keep English rather than failing the app
        loading.delete(lang)
      })
    loading.set(lang, p)
  }
  return p
}

const KEY = "tex-lang"
const codes = new Set<string>(TEX_LANGS.map((l) => l.code))

function detect(): TexLang {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved && codes.has(saved)) return saved as TexLang
  } catch {
    /* storage blocked */
  }
  const nav = (navigator.language || "en").slice(0, 2).toLowerCase()
  return (codes.has(nav) ? nav : "en") as TexLang
}

let current: TexLang = detect()
// <html lang> drives hyphenation, screen readers and locale-aware text-transform
// (Turkish uppercase: "Tarih" → "TARİH", not "TARIH")
if (typeof document !== "undefined") document.documentElement.setAttribute("lang", current)
void loadTexLang(current)

/** True once the current language's catalogs are loaded (gate the first paint on it
 * so the UI does not flash English). */
export function useTexI18nReady(): boolean {
  const [ready, setReady] = useState(() => !!CATALOGS[current])
  useEffect(() => {
    if (ready) return
    let alive = true
    void loadTexLang(current).then(() => alive && setReady(true))
    return () => {
      alive = false
    }
  }, [ready])
  return ready
}

export function getTexLang(): TexLang {
  return current
}

export function intlLocale(lang: TexLang = current): string {
  return TEX_LANGS.find((l) => l.code === lang)?.intl ?? "en-GB"
}

export async function setTexLang(lang: TexLang) {
  await loadTexLang(lang)
  current = lang
  try {
    localStorage.setItem(KEY, lang)
  } catch {
    /* ignore */
  }
  document.documentElement.setAttribute("lang", lang)
  window.dispatchEvent(new Event("tex:lang"))
}

export type Params = Record<string, string | number>

function interpolate(s: string, params?: Params) {
  if (!params) return s
  return s.replace(/\{(\w+)\}/g, (_, k: string) => (params[k] !== undefined ? String(params[k]) : `{${k}}`))
}

export function translate(lang: TexLang, key: string, params?: Params): string {
  const entry = CATALOGS[lang]?.[key] ?? CATALOGS.en?.[key]
  if (entry === undefined) return interpolate(key, params)
  if (typeof entry === "string") return interpolate(entry, params)
  const n = Number(params?.count ?? 0)
  const rule = new Intl.PluralRules(intlLocale(lang)).select(n) as keyof Plural
  const form = (n === 0 && entry.zero) || entry[rule] || entry.other
  return interpolate(form, params)
}

/** Non-reactive translate (for code outside components). */
export function tt(key: string, params?: Params) {
  return translate(current, key, params)
}

/** Reactive translator bound to the current TEX language. */
export function useTexT() {
  const [lang, setLang] = useState<TexLang>(current)
  useEffect(() => {
    const on = () => setLang(current)
    window.addEventListener("tex:lang", on)
    return () => window.removeEventListener("tex:lang", on)
  }, [])
  const t = useCallback((key: string, params?: Params) => translate(lang, key, params), [lang])
  return { t, lang, locale: intlLocale(lang) }
}

/** Keys missing from a loaded language (dev aid; the build-time check is
 * scripts/tex-i18n-check.mjs). */
export function missingKeys(lang: TexLang): string[] {
  const en = CATALOGS.en ?? {}
  const other = CATALOGS[lang] ?? {}
  return Object.keys(en).filter((k) => !(k in other))
}
