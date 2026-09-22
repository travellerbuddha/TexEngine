import { useSession } from "../../../lib/session"
import { TEX_LANGS, useTexT } from "../../../i18n"
import { Card, CardBody, Field, FormGrid, Input, Notice, Segmented, Select, Switch } from "../../../ui"
import { CheckboxGroup, FormSection } from "../../settings/components/common"
import { SITE_LANGS, csv, normaliseSlug } from "../site"
import type { TabProps } from "./common"

export function GeneralTab({ site, set, err, isNew }: TabProps) {
  const { t } = useTexT()
  const { boot } = useSession()
  const editable = boot.properties.filter((p) => boot.user.platform_admin || p.capabilities.includes("booking_site.edit"))
  const groups = [...new Set(editable.map((p) => p.hotel_group).filter(Boolean) as string[])].sort()
  const scope: "hotel" | "group" = site.hotel_group && !site.property ? "group" : "hotel"
  const langs = csv(site.languages)
  const ccys = csv(site.currencies)
  const allCcys = [...new Set([...boot.currencies, ...ccys])].sort()
  const withCurrent = (opts: { value: string; label: string }[], cur: string | null) =>
    cur && !opts.some((o) => o.value === cur) ? [...opts, { value: cur, label: cur }] : opts
  const groupHotels = site.hotel_group ? boot.properties.filter((p) => p.hotel_group === site.hotel_group) : []

  return (
    <div className="space-y-4">
      <Card>
        <CardBody className="space-y-5">
          <FormSection title={t("be.general.identity")}>
            <FormGrid>
              <Field label={t("be.field.site_name")} required error={err("site_name")} hint={t("be.field.site_name_hint")}>
                <Input value={site.site_name} maxLength={140} onChange={(e) => set({ site_name: e.target.value })} />
              </Field>
              <Field
                label={t("be.field.slug")}
                required
                error={err("site_slug")}
                hint={!isNew && site.name && normaliseSlug(site.site_slug) !== site.name ? t("be.field.slug_changed") : t("be.field.slug_hint", { url: `/book/${normaliseSlug(site.site_slug) || "…"}` })}
              >
                <Input
                  value={site.site_slug}
                  maxLength={60}
                  spellCheck={false}
                  autoCapitalize="none"
                  className="font-mono"
                  onChange={(e) => set({ site_slug: e.target.value.toLowerCase() })}
                  onBlur={(e) => set({ site_slug: normaliseSlug(e.target.value) })}
                />
              </Field>
            </FormGrid>
            <Switch
              checked={!!site.enabled}
              onChange={(v) => set({ enabled: v ? 1 : 0 })}
              label={t("be.field.enabled")}
              description={t("be.field.enabled_hint")}
            />
          </FormSection>

          <FormSection title={t("be.general.serves")} description={t("be.general.serves_hint")}>
            <Segmented<"hotel" | "group">
              label={t("be.general.serves")}
              value={scope}
              onChange={(v) =>
                v === "hotel"
                  ? set({ property: site.property || editable[0]?.name || null, hotel_group: null })
                  : set({ property: null, hotel_group: site.hotel_group || groups[0] || null })
              }
              options={[
                { value: "hotel", label: t("be.scope.hotel") },
                { value: "group", label: t("be.scope.group") },
              ]}
            />
            {scope === "hotel" ? (
              <Field label={t("be.field.hotel")} required error={err("scope")}>
                <Select
                  value={site.property ?? ""}
                  placeholder={t("be.select")}
                  onChange={(e) => set({ property: e.target.value || null, hotel_group: null })}
                  options={withCurrent(
                    editable.map((p) => ({ value: p.name, label: p.property_name })),
                    site.property,
                  )}
                />
              </Field>
            ) : (
              <>
                <Field label={t("be.field.hotel_group")} required error={err("scope")}>
                  <Select
                    value={site.hotel_group ?? ""}
                    placeholder={t("be.select")}
                    onChange={(e) => set({ hotel_group: e.target.value || null, property: null })}
                    options={withCurrent(
                      groups.map((g) => ({ value: g, label: g })),
                      site.hotel_group,
                    )}
                  />
                </Field>
                {site.hotel_group && (
                  <Notice tone="info">
                    {t("be.general.group_note", { count: groupHotels.length, hotels: groupHotels.map((p) => p.property_name).join(", ") || "—" })}
                  </Notice>
                )}
              </>
            )}
          </FormSection>
        </CardBody>
      </Card>

      <Card>
        <CardBody className="space-y-5">
          <FormSection title={t("be.general.languages")} description={t("be.general.languages_hint")}>
            <CheckboxGroup
              legend={t("be.field.languages")}
              options={SITE_LANGS.map((l) => ({ value: l, label: TEX_LANGS.find((x) => x.code === l)?.label ?? l }))}
              value={langs}
              error={err("languages")}
              onChange={(v) => {
                const ordered = SITE_LANGS.filter((l) => v.includes(l))
                set({
                  languages: ordered.join(","),
                  default_language: ordered.includes(site.default_language as (typeof SITE_LANGS)[number]) ? site.default_language : (ordered[0] ?? site.default_language),
                })
              }}
            />
            <Field label={t("be.field.default_language")} error={err("default_language")} className="sm:max-w-xs">
              <Select
                value={site.default_language}
                onChange={(e) => set({ default_language: e.target.value })}
                options={langs.map((l) => ({ value: l, label: TEX_LANGS.find((x) => x.code === l)?.label ?? l }))}
              />
            </Field>
          </FormSection>

          <FormSection title={t("be.general.currencies")} description={t("be.general.currencies_hint")}>
            <CheckboxGroup
              legend={t("be.field.currencies")}
              hint={t("be.field.currencies_hint")}
              options={allCcys.map((c) => ({ value: c, label: c }))}
              value={ccys}
              onChange={(v) => {
                const next = allCcys.filter((c) => v.includes(c))
                set({
                  currencies: next.join(",") || null,
                  default_currency: site.default_currency && next.length && !next.includes(site.default_currency) ? next[0] : site.default_currency,
                })
              }}
            />
            <Field label={t("be.field.default_currency")} error={err("default_currency")} hint={t("be.field.default_currency_hint")} className="sm:max-w-xs">
              <Select
                value={site.default_currency ?? ""}
                placeholder={t("be.hotel_default")}
                onChange={(e) => set({ default_currency: e.target.value || null })}
                options={(ccys.length ? ccys : allCcys).map((c) => ({ value: c, label: c }))}
              />
            </Field>
          </FormSection>

          <FormSection title={t("be.general.selling")} description={t("be.general.selling_hint")}>
            <FormGrid>
              <Field label={t("be.field.default_market")} hint={t("be.field.default_market_hint")}>
                <Select
                  value={site.default_market ?? ""}
                  placeholder={t("be.platform_default")}
                  onChange={(e) => set({ default_market: e.target.value || null })}
                  options={withCurrent(
                    boot.markets.map((m) => ({ value: m.name, label: `${m.market_name} (${m.name})` })),
                    site.default_market,
                  )}
                />
              </Field>
              <Field label={t("be.field.sales_channel")} hint={t("be.field.sales_channel_hint")}>
                <Select
                  value={site.sales_channel ?? ""}
                  placeholder={t("be.platform_default")}
                  onChange={(e) => set({ sales_channel: e.target.value || null })}
                  options={withCurrent(
                    boot.channels.map((c) => ({ value: c.name, label: c.channel_name })),
                    site.sales_channel,
                  )}
                />
              </Field>
            </FormGrid>
            <Switch
              checked={!!site.self_service_enabled}
              onChange={(v) => set({ self_service_enabled: v ? 1 : 0 })}
              label={t("be.field.self_service")}
              description={t("be.field.self_service_hint")}
            />
          </FormSection>
        </CardBody>
      </Card>
    </div>
  )
}
