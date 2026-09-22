import { useEffect, useState } from "react"
import { useTexMutation } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { useTexT } from "../../../i18n"
import { Button, Dialog, Field, FormGrid, InlineError, Input, Select, Switch, useToast } from "../../../ui"
import { methodKey, useEvent } from "../lib"
import type { Account, Rule } from "../types"

const RULE_METHODS: Rule["method"][] = ["Card", "Bank Transfer", "Pay at Hotel"]
/** Which provider types can serve which method. */
const SERVES: Record<Rule["method"], string[]> = {
  Card: ["Mock", "iyzico", "Sipay", "Virtual POS"],
  "Bank Transfer": ["Bank Transfer"],
  "Pay at Hotel": ["Pay at Hotel"],
}

interface Form {
  method: Rule["method"]
  provider_account: string
  market: string
  currency: string
  sales_channel: string
  priority: string
  disabled: boolean
}

function formOf(r: Rule | null): Form {
  return {
    method: r?.method ?? "Card",
    provider_account: r?.provider_account ?? "",
    market: r?.market ?? "",
    currency: r?.currency ?? "",
    sales_channel: r?.sales_channel ?? "",
    priority: String(r?.priority ?? 0),
    disabled: Boolean(r?.disabled),
  }
}

export function RuleDialog({
  open,
  rule,
  accounts,
  property,
  onClose,
  onSaved,
}: {
  open: boolean
  rule: Rule | null
  accounts: Account[]
  property: string
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const { boot } = useSession()
  const [form, setForm] = useState<Form>(() => formOf(rule))
  const save = useTexMutation<{ property: string; data: Record<string, unknown> }, { name: string }>("payments", "save_rule")
  const close = useEvent(() => {
    if (!save.pending) onClose()
  })
  useEffect(() => {
    if (open) {
      setForm(formOf(rule))
      save.clearError()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, rule])

  const usable = accounts.filter((a) => SERVES[form.method].includes(a.provider))
  const needsAccount = form.method !== "Pay at Hotel"
  const priorityOk = /^-?\d{1,4}$/.test(form.priority.trim())
  const valid = priorityOk && (!needsAccount || Boolean(form.provider_account))

  const submit = async () => {
    if (!valid) return
    try {
      await save.run({
        property,
        data: {
          name: rule?.name,
          method: form.method,
          provider_account: form.provider_account || null,
          market: form.market || null,
          currency: form.currency || null,
          sales_channel: form.sales_channel || null,
          priority: Number(form.priority),
          disabled: form.disabled ? 1 : 0,
        },
      })
      toast.success(t("payments.rule.saved"))
      onSaved()
      onClose()
    } catch {
      /* inline */
    }
  }

  const any = t("payments.rule.any")
  return (
    <Dialog
      open={open}
      onClose={close}
      title={rule ? t("payments.rule.edit_title") : t("payments.rule.new_title")}
      description={t("payments.rule.desc")}
      size="lg"
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
      <div className="space-y-4">
        <FormGrid>
          <Field label={t("payments.rule.method")} required>
            <Select
              value={form.method}
              onChange={(e) => setForm({ ...form, method: e.target.value as Rule["method"], provider_account: "" })}
              options={RULE_METHODS.map((m) => ({ value: m, label: t(methodKey(m)) }))}
              data-autofocus
            />
          </Field>
          <Field label={t("payments.rule.account")} required={needsAccount} hint={needsAccount && !usable.length ? t("payments.rule.no_account") : undefined}>
            <Select
              value={form.provider_account}
              onChange={(e) => setForm({ ...form, provider_account: e.target.value })}
              options={[
                { value: "", label: needsAccount ? t("payments.rule.pick_account") : t("payments.rule.no_account_needed") },
                ...usable.map((a) => ({ value: a.name, label: `${a.label} · ${a.environment === "Production" ? t("payments.env.production") : t("payments.env.sandbox")}${a.enabled ? "" : ` · ${t("payments.acc.disabled")}`}` })),
              ]}
            />
          </Field>
          <Field label={t("payments.rule.market")}>
            <Select value={form.market} onChange={(e) => setForm({ ...form, market: e.target.value })} options={[{ value: "", label: any }, ...boot.markets.map((m) => ({ value: m.name, label: `${m.market_name} (${m.name})` }))]} />
          </Field>
          <Field label={t("payments.currency")}>
            <Select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })} options={[{ value: "", label: any }, ...boot.currencies.map((c) => ({ value: c, label: c }))]} />
          </Field>
          <Field label={t("payments.rule.channel")}>
            <Select
              value={form.sales_channel}
              onChange={(e) => setForm({ ...form, sales_channel: e.target.value })}
              options={[{ value: "", label: any }, ...boot.channels.map((c) => ({ value: c.name, label: c.channel_name || c.name }))]}
            />
          </Field>
          <Field label={t("payments.rule.priority")} hint={t("payments.rule.priority_hint")} error={!priorityOk ? t("payments.rule.priority_invalid") : undefined}>
            <Input inputMode="numeric" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value.replace(/[^\d-]/g, "") })} className="text-right tabular-nums" />
          </Field>
        </FormGrid>
        <Switch checked={!form.disabled} onChange={(v) => setForm({ ...form, disabled: !v })} label={t("payments.rule.active")} description={t("payments.rule.active_hint")} />
        <p className="text-xs text-zinc-500">{t("payments.rule.specificity")}</p>
        <InlineError error={save.error} />
      </div>
    </Dialog>
  )
}
