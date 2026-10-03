import { useMemo, useState } from "react"
import { KeyRound, ShieldAlert } from "lucide-react"
import { useTexMutation } from "../../../lib/api"
import { useTexT } from "../../../i18n"
import { Badge, Button, Drawer, Field, FormGrid, InlineError, Input, Notice, Segmented, Select, Switch, Textarea, useToast } from "../../../ui"
import { useEvent } from "../lib"
import { GATEWAYS, PROVIDERS, type Account, type Provider, type SecretField } from "../types"

type DataField = "terminal_id" | "bank_code" | "gateway_url" | "bank_name" | "iban" | "account_holder" | "transfer_instructions"

/** Which fields each adapter reads (kamra/tex/payments/providers). */
const FIELDS: Record<Provider, { data: DataField[]; secrets: SecretField[] }> = {
  Mock: { data: [], secrets: [] },
  "Pay at Hotel": { data: [], secrets: [] },
  "Bank Transfer": { data: ["bank_name", "iban", "account_holder", "transfer_instructions"], secrets: [] },
  iyzico: { data: ["gateway_url"], secrets: ["api_key", "secret_key", "webhook_secret"] },
  Sipay: { data: ["gateway_url"], secrets: ["api_key", "secret_key", "merchant_key", "webhook_secret"] },
  "Virtual POS": { data: ["bank_code", "terminal_id", "gateway_url"], secrets: ["store_key", "webhook_secret"] },
}
/** Provider-specific names for the shared fields (e.g. Sipay calls the API key "App ID"). */
const LABEL_OVERRIDE: Partial<Record<Provider, Partial<Record<DataField | SecretField, string>>>> = {
  Sipay: { api_key: "payments.acc.field.app_id", secret_key: "payments.acc.field.app_secret" },
  "Virtual POS": { terminal_id: "payments.acc.field.client_id" },
}
const BANK_CODES = ["NestPay", "Garanti", "YKB PosNet", "Vakif", "Kuveyt"]

interface Form {
  label: string
  provider: Provider
  environment: "Sandbox" | "Production"
  enabled: boolean
  currencies: string
  data: Record<DataField, string>
  secrets: Record<SecretField, string>
}

function formOf(a: Account | null): Form {
  const data = {} as Record<DataField, string>
  for (const f of ["terminal_id", "bank_code", "gateway_url", "bank_name", "iban", "account_holder", "transfer_instructions"] as DataField[])
    data[f] = (a?.[f] as string | null) ?? ""
  return {
    label: a?.label ?? "",
    provider: a?.provider ?? "Bank Transfer",
    environment: a?.environment ?? "Sandbox",
    enabled: a ? Boolean(a.enabled) : true,
    currencies: a?.currencies ?? "",
    data,
    // secrets are write-only: never pre-filled, blank keeps the stored value
    secrets: { api_key: "", secret_key: "", merchant_key: "", store_key: "", webhook_secret: "" },
  }
}

export function AccountDrawer({
  open,
  account,
  property,
  onClose,
  onSaved,
}: {
  open: boolean
  account: Account | null
  property: string
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  // mounted per opening (Setup): the form starts from the account it opens (2Z)
  const [form, setForm] = useState<Form>(() => formOf(account))
  const save = useTexMutation<{ property: string; data: Record<string, unknown> }, { name: string }>("payments", "save_account")
  const close = useEvent(() => {
    if (!save.pending) onClose()
  })
  const spec = FIELDS[form.provider]
  const gateway = GATEWAYS.includes(form.provider)
  const mockProd = form.provider === "Mock" && form.environment === "Production"
  const currenciesOk = !form.currencies.trim() || /^[A-Z]{3}(\s*,\s*[A-Z]{3})*$/.test(form.currencies.trim().toUpperCase())
  const valid = form.label.trim().length > 0 && !mockProd && currenciesOk
  const fieldLabel = (f: DataField | SecretField) => t(LABEL_OVERRIDE[form.provider]?.[f] ?? `payments.acc.field.${f}`)
  const secretsChanged = useMemo(() => Object.values(form.secrets).some(Boolean), [form.secrets])

  const submit = async () => {
    if (!valid) return
    const data: Record<string, unknown> = {
      name: account?.name,
      label: form.label.trim(),
      provider: form.provider,
      environment: form.environment,
      enabled: form.enabled ? 1 : 0,
      currencies: form.currencies.trim().toUpperCase().replace(/\s+/g, ""),
    }
    for (const f of spec.data) data[f] = form.data[f].trim()
    for (const f of spec.secrets) if (form.secrets[f]) data[f] = form.secrets[f]
    try {
      await save.run({ property, data })
      // drop the typed secrets from memory as soon as they are stored
      setForm((x) => ({ ...x, secrets: { api_key: "", secret_key: "", merchant_key: "", store_key: "", webhook_secret: "" } }))
      toast.success(t("payments.acc.saved"))
      onSaved()
      onClose()
    } catch {
      /* inline */
    }
  }

  return (
    <Drawer
      open={open}
      onClose={close}
      title={account ? t("payments.acc.edit_title", { label: account.label }) : t("payments.acc.new_title")}
      width="lg"
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={save.pending}>
            {t("core.action.cancel")}
          </Button>
          <Button loading={save.pending} disabled={!valid} onClick={submit}>
            {t("core.action.save")}
          </Button>
        </>
      }
    >
      <form
        className="space-y-6"
        autoComplete="off"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <FormGrid>
          <Field label={t("payments.acc.label")} required>
            <Input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} maxLength={140} data-autofocus />
          </Field>
          <Field label={t("payments.acc.provider")} required hint={account ? t("payments.acc.provider_locked") : undefined}>
            <Select
              value={form.provider}
              disabled={Boolean(account)}
              onChange={(e) => setForm({ ...form, provider: e.target.value as Provider, environment: e.target.value === "Mock" ? "Sandbox" : form.environment })}
              options={PROVIDERS.map((p) => ({ value: p, label: t(`payments.provider.${p.toLowerCase().replace(/\s+/g, "_")}`) }))}
            />
          </Field>
        </FormGrid>

        <div className="space-y-2">
          <p className="text-sm font-medium text-zinc-800">{t("payments.acc.environment")}</p>
          <Segmented<"Sandbox" | "Production">
            label={t("payments.acc.environment")}
            value={form.environment}
            onChange={(v) => setForm({ ...form, environment: v })}
            options={[
              { value: "Sandbox", label: t("payments.env.sandbox") },
              { value: "Production", label: t("payments.env.production") },
            ]}
          />
          {mockProd && <Notice tone="danger">{t("payments.acc.mock_prod")}</Notice>}
          {form.environment === "Production" && gateway && (
            <Notice tone="danger" title={t("payments.acc.not_verified_title")}>
              {t("payments.acc.not_verified_body", { provider: t(`payments.provider.${form.provider.toLowerCase().replace(/\s+/g, "_")}`) })}
            </Notice>
          )}
          {form.environment === "Sandbox" && gateway && <Notice tone="info">{t("payments.acc.sandbox_note")}</Notice>}
        </div>

        <Switch checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} label={t("payments.acc.enabled")} description={t("payments.acc.enabled_hint")} />

        <Field label={t("payments.acc.currencies")} hint={t("payments.acc.currencies_hint")} error={!currenciesOk ? t("payments.acc.currencies_invalid") : undefined}>
          <Input value={form.currencies} onChange={(e) => setForm({ ...form, currencies: e.target.value })} placeholder="EUR, TRY" />
        </Field>

        {spec.data.length > 0 && (
          <fieldset className="space-y-4">
            <legend className="mb-2 text-sm font-semibold text-zinc-900">{t("payments.acc.settings")}</legend>
            <FormGrid>
              {spec.data.map((f) =>
                f === "bank_code" ? (
                  <Field key={f} label={fieldLabel(f)} hint={t("payments.acc.bank_code_hint")}>
                    <Select
                      value={form.data.bank_code || "NestPay"}
                      onChange={(e) => setForm({ ...form, data: { ...form.data, bank_code: e.target.value } })}
                      options={BANK_CODES.map((b) => ({ value: b, label: b }))}
                    />
                  </Field>
                ) : f === "transfer_instructions" ? (
                  <Field key={f} label={fieldLabel(f)} className="sm:col-span-2" hint={t("payments.acc.instructions_hint")}>
                    <Textarea value={form.data[f]} onChange={(e) => setForm({ ...form, data: { ...form.data, [f]: e.target.value } })} rows={3} />
                  </Field>
                ) : (
                  <Field key={f} label={fieldLabel(f)} hint={f === "gateway_url" ? t("payments.acc.gateway_url_hint") : undefined}>
                    <Input
                      value={form.data[f]}
                      onChange={(e) => setForm({ ...form, data: { ...form.data, [f]: e.target.value } })}
                      className={f === "iban" || f === "terminal_id" ? "font-mono" : undefined}
                      inputMode={f === "gateway_url" ? "url" : undefined}
                    />
                  </Field>
                ),
              )}
            </FormGrid>
          </fieldset>
        )}

        {spec.secrets.length > 0 && (
          <fieldset className="space-y-4 rounded-lg border border-zinc-200 p-3">
            <legend className="flex items-center gap-1.5 px-1 text-sm font-semibold text-zinc-900">
              <KeyRound className="size-4 text-zinc-500" aria-hidden />
              {t("payments.acc.secrets")}
            </legend>
            <p className="text-xs text-zinc-600">{t("payments.acc.secrets_hint")}</p>
            <FormGrid>
              {spec.secrets.map((f) => {
                const isSet = Boolean(account?.secrets_set?.[f])
                return (
                  <Field
                    key={f}
                    label={
                      <span className="inline-flex items-center gap-2">
                        {fieldLabel(f)}
                        <Badge tone={isSet ? "success" : "neutral"}>{isSet ? t("payments.acc.secret_set") : t("payments.acc.secret_not_set")}</Badge>
                      </span>
                    }
                    hint={isSet ? t("payments.acc.secret_keep") : t("payments.acc.secret_enter")}
                  >
                    <Input
                      type="password"
                      autoComplete="new-password"
                      spellCheck={false}
                      value={form.secrets[f]}
                      onChange={(e) => setForm({ ...form, secrets: { ...form.secrets, [f]: e.target.value } })}
                      placeholder={isSet ? "••••••••" : ""}
                    />
                  </Field>
                )
              })}
            </FormGrid>
            {secretsChanged && (
              <p className="flex items-center gap-1.5 text-xs font-medium text-amber-800">
                <ShieldAlert className="size-3.5" aria-hidden />
                {t("payments.acc.secrets_will_replace")}
              </p>
            )}
          </fieldset>
        )}

        <p className="text-xs text-zinc-500">{t("payments.acc.audit_hint")}</p>
        <InlineError error={save.error} />
        <button type="submit" className="hidden" aria-hidden tabIndex={-1} />
      </form>
    </Drawer>
  )
}
