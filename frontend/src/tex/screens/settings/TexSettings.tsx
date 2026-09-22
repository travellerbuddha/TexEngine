import { useEffect, useMemo, useState } from "react"
import { ShieldAlert } from "lucide-react"
import { useTexMutation, useTexQuery } from "../../lib/api"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  ConfirmDialog,
  ErrorState,
  Field,
  FormGrid,
  InlineError,
  Input,
  Notice,
  Select,
  Skeleton,
  Switch,
  useToast,
} from "../../ui"
import { SettingsFrame } from "./SettingsFrame"
import { useUnsavedWarning } from "./components/common"

interface TexSettingsData {
  strict_tenancy: number
  show_legacy_pms: number
  brand_name: string | null
  support_email: string | null
  default_market: string | null
  default_sales_channel: string | null
  offer_ttl_minutes: number | null
  quote_ttl_minutes: number | null
  hold_minutes: number | null
  manage_link_days: number | null
  fx_provider_default: string | null
  fx_max_age_days: number | null
}

const INT_FIELDS: { key: keyof TexSettingsData; min: number; max: number }[] = [
  { key: "offer_ttl_minutes", min: 1, max: 1440 },
  { key: "quote_ttl_minutes", min: 1, max: 1440 },
  { key: "hold_minutes", min: 1, max: 1440 },
  { key: "manage_link_days", min: 1, max: 3650 },
]

type Form = Record<keyof TexSettingsData, string>

function toForm(d: TexSettingsData): Form {
  const f = {} as Form
  for (const [k, v] of Object.entries(d)) f[k as keyof TexSettingsData] = v === null || v === undefined ? "" : String(v)
  return f
}

export default function TexSettings() {
  const { t } = useTexT()
  const toast = useToast()
  const { boot, reload } = useSession()
  const q = useTexQuery<TexSettingsData>("admin", "settings", {}, [])
  const save = useTexMutation<{ data: Record<string, unknown> }, TexSettingsData>("admin", "save_settings")
  const [form, setForm] = useState<Form | null>(null)
  const [confirmLoose, setConfirmLoose] = useState(false)

  useEffect(() => {
    if (q.data) setForm(toForm(q.data))
  }, [q.data])

  const initial = useMemo(() => (q.data ? toForm(q.data) : null), [q.data])
  const dirty = !!form && !!initial && JSON.stringify(form) !== JSON.stringify(initial)
  useUnsavedWarning(dirty)

  const set = (k: keyof TexSettingsData, v: string) => form && setForm({ ...form, [k]: v })
  const errors: Partial<Record<keyof TexSettingsData, string>> = {}
  if (form) {
    for (const f of INT_FIELDS) {
      const v = form[f.key]
      if (!/^\d+$/.test(v) || Number(v) < f.min || Number(v) > f.max) errors[f.key] = t("settings.err.range", { min: f.min, max: f.max })
    }
    const age = form.fx_max_age_days
    if (!/^\d+$/.test(age) || Number(age) < 1 || Number(age) > 30) errors.fx_max_age_days = t("settings.err.range", { min: 1, max: 30 })
    if (form.support_email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.support_email)) errors.support_email = t("settings.err.email")
    if (!form.brand_name.trim()) errors.brand_name = t("settings.err.required")
  }
  const valid = Object.keys(errors).length === 0

  const submit = async () => {
    if (!form || !valid) return
    const data: Record<string, unknown> = {
      strict_tenancy: form.strict_tenancy === "1" ? 1 : 0,
      show_legacy_pms: form.show_legacy_pms === "1" ? 1 : 0,
      brand_name: form.brand_name.trim(),
      support_email: form.support_email.trim() || null,
      default_market: form.default_market || null,
      default_sales_channel: form.default_sales_channel || null,
      fx_provider_default: form.fx_provider_default || "TCMB",
      fx_max_age_days: Number(form.fx_max_age_days),
    }
    for (const f of INT_FIELDS) data[f.key] = Number(form[f.key])
    try {
      const after = await save.run({ data })
      setForm(toForm(after))
      q.reload()
      toast.success(t("core.saved"))
      await reload() // brand name and legacy navigation come from the session
    } catch {
      /* inline */
    }
  }

  return (
    <SettingsFrame subtitle={t("settings.tex.subtitle")}>
      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : !form ? (
        <Card className="space-y-3 p-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </Card>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
        >
          <InlineError error={save.error} />
          <Card className={form.strict_tenancy === "1" ? undefined : "border-rose-300"}>
            <CardHeader title={t("settings.tex.tenancy")} description={t("settings.tex.tenancy_hint")} />
            <CardBody className="space-y-4">
              <Switch
                checked={form.strict_tenancy === "1"}
                onChange={(v) => (v ? set("strict_tenancy", "1") : setConfirmLoose(true))}
                label={t("settings.tex.strict_tenancy")}
                description={t("settings.tex.strict_tenancy_hint")}
              />
              {form.strict_tenancy === "1" ? (
                <Notice tone="success">{t("settings.tex.strict_on")}</Notice>
              ) : (
                <div role="alert" className="flex gap-2 rounded-lg border border-rose-300 bg-rose-50 px-3 py-2.5 text-sm text-rose-900">
                  <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                  <div>
                    <p className="font-semibold">{t("settings.tex.strict_off_title")}</p>
                    <p>{t("settings.tex.strict_off_body")}</p>
                  </div>
                </div>
              )}
              <Switch
                checked={form.show_legacy_pms === "1"}
                onChange={(v) => set("show_legacy_pms", v ? "1" : "0")}
                label={t("settings.tex.legacy")}
                description={t("settings.tex.legacy_hint")}
              />
            </CardBody>
          </Card>

          <Card>
            <CardHeader title={t("settings.tex.brand")} />
            <CardBody>
              <FormGrid>
                <Field label={t("settings.tex.brand_name")} required error={errors.brand_name} hint={t("settings.tex.brand_name_hint")}>
                  <Input value={form.brand_name} onChange={(e) => set("brand_name", e.target.value)} maxLength={140} />
                </Field>
                <Field label={t("settings.tex.support_email")} error={errors.support_email}>
                  <Input type="email" value={form.support_email} onChange={(e) => set("support_email", e.target.value)} />
                </Field>
                <Field label={t("settings.tex.default_market")} hint={t("settings.tex.default_market_hint")}>
                  <Select
                    value={form.default_market}
                    placeholder={t("settings.none")}
                    onChange={(e) => set("default_market", e.target.value)}
                    options={boot.markets.map((m) => ({ value: m.name, label: `${m.market_name} (${m.name})` }))}
                  />
                </Field>
                <Field label={t("settings.tex.default_channel")}>
                  <Select
                    value={form.default_sales_channel}
                    placeholder={t("settings.none")}
                    onChange={(e) => set("default_sales_channel", e.target.value)}
                    options={boot.channels.map((c) => ({ value: c.name, label: c.channel_name }))}
                  />
                </Field>
              </FormGrid>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title={t("settings.tex.ttl")} description={t("settings.tex.ttl_hint")} />
            <CardBody>
              <FormGrid cols={4}>
                {INT_FIELDS.map((f) => (
                  <Field key={f.key} label={t(`settings.tex.${f.key}`)} error={errors[f.key]} hint={t(`settings.tex.${f.key}_hint`)}>
                    <Input
                      inputMode="numeric"
                      value={form[f.key]}
                      onChange={(e) => set(f.key, e.target.value.replace(/[^\d]/g, ""))}
                    />
                  </Field>
                ))}
              </FormGrid>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title={t("settings.tex.fx")} description={t("settings.tex.fx_hint")} />
            <CardBody>
              <FormGrid>
                <Field label={t("settings.tex.fx_provider")}>
                  <Select
                    value={form.fx_provider_default || "TCMB"}
                    onChange={(e) => set("fx_provider_default", e.target.value)}
                    options={["TCMB", "ECB", "MANUAL"].map((p) => ({ value: p, label: t(`settings.fx.${p}`) }))}
                  />
                </Field>
                <Field label={t("settings.tex.fx_max_age")} error={errors.fx_max_age_days} hint={t("settings.tex.fx_max_age_hint")}>
                  <Input inputMode="numeric" value={form.fx_max_age_days} onChange={(e) => set("fx_max_age_days", e.target.value.replace(/[^\d]/g, ""))} />
                </Field>
              </FormGrid>
            </CardBody>
          </Card>

          <div className="sticky bottom-0 z-10 -mx-1 flex flex-wrap items-center justify-end gap-2 rounded-lg border border-zinc-200 bg-white/95 px-3 py-2 shadow-tex-card backdrop-blur">
            {dirty && <span className="mr-auto text-xs font-medium text-amber-800">{t("settings.unsaved")}</span>}
            <Button variant="secondary" disabled={!dirty || save.pending} onClick={() => initial && setForm(initial)}>
              {t("core.action.reset")}
            </Button>
            <Button type="submit" loading={save.pending} disabled={!dirty || !valid}>
              {t("core.action.save")}
            </Button>
          </div>
        </form>
      )}
      <ConfirmDialog
        open={confirmLoose}
        onClose={() => setConfirmLoose(false)}
        tone="danger"
        title={t("settings.tex.strict_confirm_title")}
        body={
          <div className="space-y-2">
            <p>{t("settings.tex.strict_off_body")}</p>
            <p className="font-medium">{t("settings.tex.strict_confirm_body")}</p>
          </div>
        }
        confirmLabel={t("settings.tex.strict_confirm")}
        onConfirm={() => {
          set("strict_tenancy", "0")
        }}
      />
    </SettingsFrame>
  )
}
