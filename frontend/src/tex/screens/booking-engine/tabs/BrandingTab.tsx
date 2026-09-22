import { useId, useRef, useState } from "react"
import { ImageUp, X } from "lucide-react"
import type { TexApiError } from "../../../lib/api"
import { useTexT } from "../../../i18n"
import { Button, Card, CardBody, Field, FormGrid, IconButton, Input, Notice, Segmented, Select } from "../../../ui"
import { FormSection } from "../../settings/components/common"
import { BrandPreview } from "../BrandPreview"
import { BUTTON_STYLES, FONTS, HEADER_LAYOUTS, HEX, RADII, SEARCH_STYLES, contrast, onColor, safeImageUrl } from "../site"
import { IMAGE_TYPES, MAX_IMAGE_BYTES, uploadPublicImage } from "../upload"
import type { TabProps } from "./common"

/** Native colour picker + #RRGGBB text input kept in sync. */
function ColorField({ label, value, onChange, error, hint }: { label: string; value: string; onChange: (v: string) => void; error?: string; hint?: string }) {
  const { t } = useTexT()
  const id = useId()
  const valid = HEX.test(value)
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-zinc-800">
        {label}
      </label>
      <div className="flex items-center gap-2">
        <input
          type="color"
          aria-label={t("be.brand.pick", { field: label })}
          value={valid ? value.toLowerCase() : "#000000"}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          className="h-9 w-11 shrink-0 cursor-pointer rounded-lg border border-zinc-300 bg-white p-1"
        />
        <Input
          id={id}
          value={value}
          maxLength={7}
          spellCheck={false}
          autoCapitalize="characters"
          className="font-mono uppercase"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-err` : hint ? `${id}-hint` : undefined}
          onChange={(e) => {
            let v = e.target.value.trim()
            if (v && !v.startsWith("#")) v = `#${v}`
            onChange(v.toUpperCase())
          }}
        />
      </div>
      {error ? (
        <p id={`${id}-err`} role="alert" className="text-xs font-medium text-rose-700">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-xs text-zinc-500">
          {hint}
        </p>
      ) : null}
    </div>
  )
}

/** Image by URL, or upload a public file and keep its /files/… URL. */
function ImageField({ label, value, onChange, error, hint }: { label: string; value: string | null; onChange: (v: string | null) => void; error?: string; hint: string }) {
  const { t } = useTexT()
  const file = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [uploadErr, setUploadErr] = useState<string | null>(null)
  const preview = safeImageUrl(value)
  return (
    <div className="space-y-1.5">
      <Field label={label} error={error ?? uploadErr ?? undefined} hint={hint}>
        <Input
          type="url"
          inputMode="url"
          placeholder="https://… / /files/…"
          value={value ?? ""}
          onChange={(e) => {
            setUploadErr(null)
            onChange(e.target.value.trim() || null)
          }}
        />
      </Field>
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={file}
          type="file"
          accept={IMAGE_TYPES.join(",")}
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={async (e) => {
            const f = e.target.files?.[0]
            e.target.value = ""
            if (!f) return
            if (!IMAGE_TYPES.includes(f.type)) return setUploadErr(t("be.brand.upload_type"))
            if (f.size > MAX_IMAGE_BYTES) return setUploadErr(t("be.brand.upload_size", { mb: 2 }))
            setBusy(true)
            setUploadErr(null)
            try {
              onChange(await uploadPublicImage(f))
            } catch (err) {
              setUploadErr((err as TexApiError).message)
            } finally {
              setBusy(false)
            }
          }}
        />
        <Button
          variant="secondary"
          size="sm"
          loading={busy}
          icon={<ImageUp className="size-3.5" aria-hidden />}
          aria-label={t("be.brand.upload", { field: label })}
          onClick={() => file.current?.click()}
        >
          {t("be.brand.upload_short")}
        </Button>
        {preview && (
          <span className="flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-zinc-50 p-1">
            <img src={preview} alt={t("be.brand.current", { field: label })} className="h-8 max-w-28 rounded object-contain" />
            <IconButton size="sm" label={t("be.brand.remove", { field: label })} icon={<X className="size-3.5" />} onClick={() => onChange(null)} />
          </span>
        )}
      </div>
    </div>
  )
}

export function BrandingTab({ site, set, err }: TabProps) {
  const { t } = useTexT()
  const btnText = onColor(site.primary_color)
  const cButton = contrast(site.primary_color, btnText)
  const cText = contrast(site.background_color, "#1F2328")
  const cOutline = contrast(site.primary_color, "#FFFFFF")
  const warnings: string[] = []
  if (cButton !== null && cButton < 4.5) warnings.push(t("be.brand.low_contrast_button", { ratio: cButton.toFixed(1) }))
  if (cText !== null && cText < 4.5) warnings.push(t("be.brand.low_contrast_text", { ratio: cText.toFixed(1) }))
  if (site.button_style === "outline" && cOutline !== null && cOutline < 3) warnings.push(t("be.brand.low_contrast_outline", { ratio: cOutline.toFixed(1) }))

  const opt = (group: string, v: string) => ({ value: v, label: t(`be.brand.${group}.${v}`) })

  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <Card className="min-w-0">
        <CardBody className="space-y-6">
          <p className="text-sm text-zinc-600">{t("be.brand.safe_tokens")}</p>
          <FormSection title={t("be.brand.colours")}>
            <FormGrid cols={3}>
              <ColorField label={t("be.field.primary_color")} value={site.primary_color} error={err("primary_color")} hint={t("be.field.primary_color_hint")} onChange={(v) => set({ primary_color: v })} />
              <ColorField label={t("be.field.accent_color")} value={site.accent_color} error={err("accent_color")} hint={t("be.field.accent_color_hint")} onChange={(v) => set({ accent_color: v })} />
              <ColorField
                label={t("be.field.background_color")}
                value={site.background_color}
                error={err("background_color")}
                hint={t("be.field.background_color_hint")}
                onChange={(v) => set({ background_color: v })}
              />
            </FormGrid>
            {warnings.length > 0 && (
              <Notice tone="warning" title={t("be.brand.contrast_title")}>
                <ul className="list-disc pl-4">
                  {warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </Notice>
            )}
          </FormSection>

          <FormSection title={t("be.brand.type_shape")}>
            <FormGrid cols={3}>
              <Field label={t("be.field.font")} hint={t("be.field.font_hint")}>
                <Select value={site.font_family} onChange={(e) => set({ font_family: e.target.value })} options={FONTS.map((f) => ({ value: f, label: f }))} />
              </Field>
              <Field label={t("be.field.radius")}>
                <Select value={site.radius} onChange={(e) => set({ radius: e.target.value })} options={RADII.map((v) => opt("radius", v))} />
              </Field>
              <Field label={t("be.field.card_radius")}>
                <Select value={site.card_radius} onChange={(e) => set({ card_radius: e.target.value })} options={RADII.map((v) => opt("radius", v))} />
              </Field>
            </FormGrid>
            <div className="flex flex-wrap gap-x-6 gap-y-4">
              {(
                [
                  ["button_style", BUTTON_STYLES, "button"],
                  ["header_layout", HEADER_LAYOUTS, "header"],
                  ["search_style", SEARCH_STYLES, "search"],
                ] as const
              ).map(([field, values, group]) => (
                <div key={field} className="space-y-1.5">
                  <span className="block text-sm font-medium text-zinc-800" aria-hidden>
                    {t(`be.field.${field}`)}
                  </span>
                  <Segmented<string>
                    size="sm"
                    label={t(`be.field.${field}`)}
                    value={site[field]}
                    onChange={(v) => set({ [field]: v })}
                    options={values.map((v) => opt(group, v))}
                  />
                </div>
              ))}
            </div>
          </FormSection>

          <FormSection title={t("be.brand.images")} description={t("be.brand.images_hint")}>
            <ImageField label={t("be.field.logo")} value={site.logo} error={err("logo")} hint={t("be.field.logo_hint")} onChange={(v) => set({ logo: v })} />
            <ImageField label={t("be.field.hero_image")} value={site.hero_image} error={err("hero_image")} hint={t("be.field.hero_image_hint")} onChange={(v) => set({ hero_image: v })} />
          </FormSection>
        </CardBody>
      </Card>
      <Card className="min-w-0 xl:sticky xl:top-4">
        <CardBody>
          <BrandPreview site={site} />
        </CardBody>
      </Card>
    </div>
  )
}
