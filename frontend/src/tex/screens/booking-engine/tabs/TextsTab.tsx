import { useMemo, useState } from "react"
import { TEX_LANGS, useTexT } from "../../../i18n"
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, Notice, Segmented, Textarea } from "../../../ui"
import { TEXT_KEYS, csv, parseTexts, serialiseTexts, type Texts } from "../site"
import type { TabProps } from "./common"

const LONG = new Set(["confirmation_note", "footer_note"])
const MAX: Record<string, number> = { headline: 80, tagline: 160, search_button: 30, confirmation_note: 600, footer_note: 300 }

/** Custom texts are stored as one JSON object keyed by language, e.g.
 * {"en": {"headline": "…"}, "tr": {"headline": "…"}} — edited here as fields. */
export function TextsTab({ site, set, err }: TabProps) {
  const { t } = useTexT()
  const langs = csv(site.languages)
  const [lang, setLang] = useState(langs.includes(site.default_language) ? site.default_language : (langs[0] ?? "en"))
  const active = langs.includes(lang) ? lang : (langs[0] ?? "en")
  const texts = useMemo(() => parseTexts(site.custom_texts), [site.custom_texts])
  const current = texts[active]
  const values: Record<string, string> = typeof current === "object" ? current : {}
  const extraKeys = Object.keys(values).filter((k) => !(TEXT_KEYS as readonly string[]).includes(k))
  const otherLangs = Object.keys(texts).filter((l) => !langs.includes(l))
  const filled = (l: string) => {
    const v = texts[l]
    return typeof v === "object" ? Object.values(v).filter((s) => s.trim()).length : typeof v === "string" && v.trim() ? 1 : 0
  }

  const update = (key: string, value: string) => {
    const next: Texts = { ...texts, [active]: { ...values, [key]: value } }
    set({ custom_texts: serialiseTexts(next) })
  }
  const copyFromDefault = () => {
    const src = texts[site.default_language]
    if (typeof src !== "object") return
    const merged = { ...values }
    for (const [k, v] of Object.entries(src)) if (!merged[k]?.trim()) merged[k] = v
    set({ custom_texts: serialiseTexts({ ...texts, [active]: merged }) })
  }
  const langLabel = (l: string) => TEX_LANGS.find((x) => x.code === l)?.label ?? l

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={t("be.texts.title")} description={t("be.texts.hint")} />
        <CardBody className="space-y-4">
          {err("custom_texts") && <Notice tone="danger">{err("custom_texts")}</Notice>}
          <div className="max-w-full overflow-x-auto">
            <Segmented<string>
              label={t("be.texts.language")}
              value={active}
              onChange={setLang}
              options={langs.map((l) => ({
                value: l,
                label: (
                  <span className="inline-flex items-center gap-1.5">
                    {l.toUpperCase()}
                    <span className="sr-only">{langLabel(l)}</span>
                    {filled(l) > 0 && (
                      <Badge tone="brand" className="px-1 py-0 text-[10px]">
                        {filled(l)}
                      </Badge>
                    )}
                  </span>
                ),
              }))}
            />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium text-zinc-800">
              {langLabel(active)}
              {active === site.default_language && (
                <Badge tone="neutral" className="ml-2">
                  {t("be.texts.default_lang")}
                </Badge>
              )}
            </p>
            {active !== site.default_language && typeof texts[site.default_language] === "object" && (
              <Button variant="ghost" size="sm" onClick={copyFromDefault}>
                {t("be.texts.copy_default", { lang: langLabel(site.default_language) })}
              </Button>
            )}
          </div>
          {typeof current === "string" && <Notice tone="warning">{t("be.texts.legacy_value")}</Notice>}
          {
            <div className="grid gap-4 sm:grid-cols-2">
              {TEXT_KEYS.map((k) => (
                <Field
                  key={`${active}-${k}`}
                  label={t(`be.text.${k}`)}
                  hint={t(`be.text.${k}_hint`)}
                  className={LONG.has(k) ? "sm:col-span-2" : undefined}
                >
                  {LONG.has(k) ? (
                    <Textarea rows={3} maxLength={MAX[k]} value={values[k] ?? ""} onChange={(e) => update(k, e.target.value)} lang={active} />
                  ) : (
                    <Input maxLength={MAX[k]} value={values[k] ?? ""} onChange={(e) => update(k, e.target.value)} lang={active} />
                  )}
                </Field>
              ))}
              {extraKeys.map((k) => (
                <Field key={`${active}-x-${k}`} label={t("be.texts.extra", { key: k })}>
                  <Input value={values[k] ?? ""} onChange={(e) => update(k, e.target.value)} lang={active} />
                </Field>
              ))}
            </div>
          }
          {otherLangs.length > 0 && <p className="text-xs text-zinc-500">{t("be.texts.hidden_langs", { langs: otherLangs.join(", ") })}</p>}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t("be.policies.title")} description={t("be.policies.hint")} />
        <CardBody>
          <Field label={t("be.field.policies")}>
            <Textarea rows={6} maxLength={4000} value={site.policies ?? ""} onChange={(e) => set({ policies: e.target.value || null })} />
          </Field>
        </CardBody>
      </Card>
    </div>
  )
}
