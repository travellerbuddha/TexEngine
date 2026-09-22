import { useState } from "react"
import { ExternalLink, Plus, X } from "lucide-react"
import { useTexQuery } from "../../../lib/api"
import { useTexT } from "../../../i18n"
import { Button, Card, CardBody, CardHeader, ErrorState, Field, IconButton, Input, Notice, Select, Skeleton } from "../../../ui"
import { CodeBlock } from "../../settings/components/common"
import { ORIGIN, WIDGET_MODES, lines, normaliseOrigin } from "../site"
import type { TabProps } from "./common"

interface Snippet {
  script: string
  element: string
  link: string
  allowed_origins: string[]
}

export function EmbedTab({ site, set, err, isNew, dirty }: TabProps) {
  const { t } = useTexT()
  const origins = lines(site.allowed_embed_origins)
  const [draft, setDraft] = useState("")
  const [draftErr, setDraftErr] = useState<string | null>(null)
  const snippet = useTexQuery<Snippet>("admin", "embed_snippet", { site: site.name }, [site.name, site.modified], !isNew && !!site.name)

  const add = () => {
    const o = normaliseOrigin(draft)
    if (!ORIGIN.test(o)) return setDraftErr(t("be.err.origin"))
    if (origins.includes(o)) return setDraftErr(t("be.embed.duplicate"))
    set({ allowed_embed_origins: [...origins, o].join("\n") })
    setDraft("")
    setDraftErr(null)
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={t("be.embed.widget")} description={t("be.embed.widget_hint")} />
        <CardBody className="space-y-4">
          <Field label={t("be.field.widget_mode")} hint={t(`be.embed.mode.${site.widget_mode}_hint`)} className="sm:max-w-sm">
            <Select
              value={site.widget_mode}
              onChange={(e) => set({ widget_mode: e.target.value })}
              options={WIDGET_MODES.map((m) => ({ value: m, label: t(`be.embed.mode.${m}`) }))}
            />
          </Field>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t("be.embed.origins")} description={t("be.embed.origins_hint")} />
        <CardBody className="space-y-3">
          {err("allowed_embed_origins") && <Notice tone="danger">{err("allowed_embed_origins")}</Notice>}
          {origins.length === 0 ? (
            <p className="text-sm text-zinc-500">{t("be.embed.no_origins")}</p>
          ) : (
            <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200" aria-label={t("be.embed.origins")}>
              {origins.map((o) => (
                <li key={o} className="flex items-center justify-between gap-2 px-3 py-1.5">
                  <span className={ORIGIN.test(normaliseOrigin(o)) ? "font-mono text-sm break-all text-zinc-800" : "font-mono text-sm break-all text-rose-700"}>{o}</span>
                  <IconButton
                    size="sm"
                    label={t("be.embed.remove_origin", { origin: o })}
                    icon={<X className="size-4" />}
                    onClick={() => set({ allowed_embed_origins: origins.filter((x) => x !== o).join("\n") })}
                  />
                </li>
              ))}
            </ul>
          )}
          <form
            className="flex flex-wrap items-start gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              add()
            }}
          >
            <Field label={t("be.embed.add_origin")} error={draftErr ?? undefined} className="min-w-0 flex-1">
              <Input
                type="url"
                inputMode="url"
                placeholder="https://www.hotel.com"
                value={draft}
                spellCheck={false}
                autoCapitalize="none"
                onChange={(e) => {
                  setDraft(e.target.value)
                  setDraftErr(null)
                }}
              />
            </Field>
            <Button type="submit" variant="secondary" icon={<Plus className="size-4" aria-hidden />} className="sm:mt-7" disabled={!draft.trim()}>
              {t("be.embed.add")}
            </Button>
          </form>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t("be.embed.code")} description={t("be.embed.code_hint")} />
        <CardBody className="space-y-4">
          {isNew ? (
            <Notice tone="info">{t("be.embed.save_first")}</Notice>
          ) : snippet.error ? (
            <ErrorState error={snippet.error} onRetry={snippet.reload} />
          ) : !snippet.data ? (
            <div className="space-y-3">
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
            </div>
          ) : (
            <>
              {dirty && <Notice tone="warning">{t("be.embed.unsaved")}</Notice>}
              {!site.enabled && <Notice tone="warning">{t("be.embed.disabled")}</Notice>}
              <CodeBlock label={t("be.embed.step_script")} value={snippet.data.script} />
              <CodeBlock label={t("be.embed.step_element")} value={snippet.data.element} />
              <CodeBlock label={t("be.embed.step_both")} value={`${snippet.data.script}\n${snippet.data.element}`} wrap />
              <div className="space-y-1.5">
                <CodeBlock label={t("be.embed.link")} value={snippet.data.link} />
                <a
                  href={`/book/${encodeURIComponent(site.site_slug)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-sm font-medium text-tex-700 hover:underline"
                >
                  {t("be.open_site")} <ExternalLink className="size-3.5" aria-hidden />
                  <span className="sr-only">({t("be.new_tab")})</span>
                </a>
              </div>
            </>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
