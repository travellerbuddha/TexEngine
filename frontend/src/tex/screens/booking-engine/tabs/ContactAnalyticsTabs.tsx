import { useTexT } from "../../../i18n"
import { Card, CardBody, CardHeader, Field, FormGrid, Input, Notice, Switch, Textarea } from "../../../ui"
import type { TabProps } from "./common"

export function ContactTab({ site, set, err }: TabProps) {
  const { t } = useTexT()
  return (
    <Card>
      <CardHeader title={t("be.contact.title")} description={t("be.contact.hint")} />
      <CardBody className="space-y-4">
        <FormGrid>
          <Field label={t("be.field.contact_phone")} error={err("contact_phone")}>
            <Input type="tel" autoComplete="off" value={site.contact_phone ?? ""} onChange={(e) => set({ contact_phone: e.target.value || null })} />
          </Field>
          <Field label={t("be.field.contact_email")} error={err("contact_email")}>
            <Input type="email" autoComplete="off" value={site.contact_email ?? ""} onChange={(e) => set({ contact_email: e.target.value.trim() || null })} />
          </Field>
          <Field label={t("be.field.whatsapp")} error={err("whatsapp")} hint={t("be.field.whatsapp_hint")}>
            <Input type="tel" autoComplete="off" value={site.whatsapp ?? ""} onChange={(e) => set({ whatsapp: e.target.value || null })} />
          </Field>
        </FormGrid>
        <Field label={t("be.field.address")}>
          <Textarea rows={3} maxLength={500} value={site.address ?? ""} onChange={(e) => set({ address: e.target.value || null })} />
        </Field>
      </CardBody>
    </Card>
  )
}

export function AnalyticsTab({ site, set, err }: TabProps) {
  const { t } = useTexT()
  const anyTracker = !!(site.ga4_measurement_id || site.gtm_container_id || site.meta_pixel_id)
  return (
    <Card>
      <CardHeader title={t("be.analytics.title")} description={t("be.analytics.hint")} />
      <CardBody className="space-y-4">
        <FormGrid cols={3}>
          <Field label={t("be.field.ga4")} error={err("ga4_measurement_id")} hint={t("be.field.ga4_hint")}>
            <Input
              className="font-mono"
              spellCheck={false}
              placeholder="G-XXXXXXXXXX"
              value={site.ga4_measurement_id ?? ""}
              onChange={(e) => set({ ga4_measurement_id: e.target.value.trim().toUpperCase() || null })}
            />
          </Field>
          <Field label={t("be.field.gtm")} error={err("gtm_container_id")} hint={t("be.field.gtm_hint")}>
            <Input
              className="font-mono"
              spellCheck={false}
              placeholder="GTM-XXXXXXX"
              value={site.gtm_container_id ?? ""}
              onChange={(e) => set({ gtm_container_id: e.target.value.trim().toUpperCase() || null })}
            />
          </Field>
          <Field label={t("be.field.meta_pixel")} error={err("meta_pixel_id")} hint={t("be.field.meta_pixel_hint")}>
            <Input
              className="font-mono"
              inputMode="numeric"
              spellCheck={false}
              placeholder="123456789012345"
              value={site.meta_pixel_id ?? ""}
              onChange={(e) => set({ meta_pixel_id: e.target.value.trim() || null })}
            />
          </Field>
        </FormGrid>
        <Switch
          checked={!!site.consent_banner}
          onChange={(v) => set({ consent_banner: v ? 1 : 0 })}
          label={t("be.field.consent_banner")}
          description={t("be.field.consent_banner_hint")}
        />
        {anyTracker && !site.consent_banner && <Notice tone="warning">{t("be.analytics.no_consent_warning")}</Notice>}
      </CardBody>
    </Card>
  )
}
