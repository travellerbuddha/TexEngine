import { Globe, SearchX, WifiOff } from "lucide-react"
import { useEffect, useId, type ReactNode } from "react"
import { isLang, LANGS, useI18n } from "../i18n"
import type { ApiError } from "../lib/api"
import { Button } from "../ui/controls"
import { EmptyState } from "../ui/feedback"

function LangSelect() {
  const { t, lang, setLang } = useI18n()
  const id = useId()
  return (
    <div className="relative flex items-center">
      <label htmlFor={id} className="sr-only">
        {t("header.language")}
      </label>
      <Globe className="pointer-events-none absolute left-2.5 size-4 text-muted" aria-hidden />
      <select
        id={id}
        value={lang}
        onChange={(e) => isLang(e.target.value) && setLang(e.target.value)}
        className="h-10 appearance-none rounded-ui border border-line bg-surface py-1 pl-8 pr-3 text-sm font-medium text-soft"
      >
        {LANGS.map((l) => (
          <option key={l.code} value={l.code} lang={l.code}>
            {l.label}
          </option>
        ))}
      </select>
    </div>
  )
}

/** Page chrome for pages that are not tied to a booking site (payment links, sandbox). */
export function PlainShell({ title, children, badge }: { title: string; children: ReactNode; badge?: ReactNode }) {
  useEffect(() => {
    document.title = title
  }, [title])
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 py-2.5 sm:px-6">
          <span className="inline-flex items-center gap-2 font-semibold">{badge}</span>
          <LangSelect />
        </div>
      </header>
      <main id="bk-main" tabIndex={-1} className="mx-auto w-full max-w-3xl flex-1 px-4 py-8 outline-none sm:px-6">
        {children}
      </main>
    </div>
  )
}

export function SiteError({ error, onRetry }: { error: ApiError; onRetry: () => void }) {
  const { t } = useI18n()
  const missing = error.kind === "not_found" || error.kind === "invalid"
  return (
    <PlainShell title={missing ? t("errors.siteNotFound") : t("errors.networkTitle")}>
      <h1 className="sr-only">{missing ? t("errors.siteNotFound") : t("errors.networkTitle")}</h1>
      <EmptyState
        icon={missing ? <SearchX className="size-8" aria-hidden /> : <WifiOff className="size-8" aria-hidden />}
        title={missing ? t("errors.siteNotFound") : t("errors.networkTitle")}
        actions={!missing && <Button onClick={onRetry}>{t("common.retry")}</Button>}
      >
        {missing ? t("errors.siteNotFoundBody") : error.kind === "rate_limit" ? t("errors.rateLimitBody") : t("errors.network")}
      </EmptyState>
    </PlainShell>
  )
}

export function NotFound() {
  const { t } = useI18n()
  return (
    <PlainShell title={t("errors.pageNotFound")}>
      <h1 className="sr-only">{t("errors.pageNotFound")}</h1>
      <EmptyState icon={<SearchX className="size-8" aria-hidden />} title={t("errors.pageNotFound")}>
        {t("errors.pageNotFoundBody")}
      </EmptyState>
    </PlainShell>
  )
}
