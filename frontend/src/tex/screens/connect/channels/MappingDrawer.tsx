import { useEffect, useMemo, useState } from "react"
import { Trash2 } from "lucide-react"
import { useTexMutation } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { useTexT } from "../../../i18n"
import { Button, Drawer, Field, FormGrid, InlineError, Input, Select, Switch, useToast, type Option } from "../../../ui"
import { mappingCodes } from "./common"
import type { Lookups, Mapping, MappingInput } from "./types"

interface Form {
  enabled: boolean
  room_type: string
  external_room_code: string
  external_rate_code: string
  board: string
  rate_plan: string
  market: string
  sales_channel: string
  contract: string
  sell_currency: string
  occupancies: string
  horizon_days: string
}

const OCCUPANCIES = /^\s*[1-9]\s*(,\s*[1-9]\s*)*$/

function toForm(m: Mapping | null, lookups: Lookups, defaults: { market?: string; channel?: string }): Form {
  if (m)
    return {
      enabled: !!m.enabled,
      room_type: m.room_type ?? "",
      external_room_code: m.external_room_code ?? "",
      external_rate_code: m.external_rate_code ?? "",
      board: m.board ?? "",
      rate_plan: m.rate_plan ?? "",
      market: m.market ?? "",
      sales_channel: m.sales_channel ?? "",
      contract: m.contract ?? "",
      sell_currency: m.sell_currency ?? "",
      occupancies: m.occupancies || "2",
      horizon_days: String(m.horizon_days ?? 90),
    }
  const has = <R extends { name: string }>(rows: R[], v?: string) => (v && rows.some((r) => r.name === v) ? v : "")
  return {
    enabled: true,
    room_type: "",
    external_room_code: "",
    external_rate_code: "",
    board: "",
    rate_plan: "",
    market: has(lookups.markets, defaults.market),
    sales_channel: has(lookups.channels, defaults.channel),
    contract: "",
    sell_currency: lookups.currency ?? "",
    occupancies: "2",
    horizon_days: "90",
  }
}

/** Add or edit one mapping; the server validates again (codes unique per connection). */
export function MappingDrawer({
  mapping,
  connection,
  lookups,
  onClose,
  onSaved,
  onDelete,
}: {
  mapping: Mapping | "new" | null
  connection: string
  lookups: Lookups
  onClose: () => void
  onSaved: () => void
  onDelete: (m: Mapping) => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const { boot } = useSession()
  const isNew = mapping === "new"
  const current = mapping && mapping !== "new" ? mapping : null
  const save = useTexMutation<{ data: MappingInput }, { name: string }>("distribution", "save_mapping")
  const defaults = { market: boot.settings.default_market, channel: boot.settings.default_sales_channel }
  const [form, setForm] = useState<Form>(() => toForm(current, lookups, defaults))
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    if (!mapping) return
    setForm(toForm(current, lookups, defaults))
    setTouched(false)
    save.clearError()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapping])

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }))

  const errors = useMemo(() => {
    const e: Partial<Record<keyof Form, string>> = {}
    const req = t("connect.err.required")
    for (const k of ["room_type", "external_room_code", "external_rate_code", "board", "market", "sales_channel", "sell_currency"] as const)
      if (!form[k].trim()) e[k] = req
    if (!OCCUPANCIES.test(form.occupancies)) e.occupancies = t("connect.channels.mapping.err_occupancies")
    const h = form.horizon_days.trim()
    if (!/^\d{1,3}$/.test(h) || Number(h) < 1 || Number(h) > 365) e.horizon_days = t("connect.channels.mapping.err_horizon")
    return e
  }, [form, t])
  const valid = Object.keys(errors).length === 0
  const err = (k: keyof Form) => (touched ? errors[k] : undefined)

  const currencies = useMemo(() => {
    const s = new Set<string>(boot.currencies ?? [])
    if (lookups.currency) s.add(lookups.currency)
    if (form.sell_currency) s.add(form.sell_currency)
    return [...s].sort()
  }, [boot.currencies, lookups.currency, form.sell_currency])

  const submit = async () => {
    setTouched(true)
    if (!valid) return
    const data: MappingInput = {
      connection,
      enabled: form.enabled ? 1 : 0,
      room_type: form.room_type,
      external_room_code: form.external_room_code.trim(),
      external_rate_code: form.external_rate_code.trim(),
      board: form.board,
      rate_plan: form.rate_plan || null,
      market: form.market,
      sales_channel: form.sales_channel,
      contract: form.contract || null,
      sell_currency: form.sell_currency,
      occupancies: form.occupancies.replace(/\s+/g, ""),
      horizon_days: Number(form.horizon_days.trim()),
    }
    if (current) data.name = current.name
    try {
      await save.run({ data })
      toast.success(t("connect.channels.mappings.saved"))
      onSaved()
    } catch {
      /* shown inline */
    }
  }

  const option = <R extends { name: string }>(rows: R[], label: (r: R) => string) => rows.map((r) => ({ value: r.name, label: label(r) }))
  const known = (rows: Option[], v: string): Option[] => (v && !rows.some((r) => r.value === v) ? [...rows, { value: v, label: v }] : rows)

  return (
    <Drawer
      open={!!mapping}
      onClose={onClose}
      width="lg"
      title={isNew ? t("connect.channels.mappings.add") : t("connect.channels.mappings.edit_named", { codes: current ? mappingCodes(current) : "" })}
      footer={
        <>
          {current && (
            <Button variant="ghost" className="mr-auto text-rose-700" icon={<Trash2 className="size-4" aria-hidden />} onClick={() => onDelete(current)}>
              {t("core.action.delete")}
            </Button>
          )}
          <Button variant="secondary" onClick={onClose}>
            {t("core.action.cancel")}
          </Button>
          <Button loading={save.pending} onClick={submit}>
            {t("core.action.save")}
          </Button>
        </>
      }
    >
      <form
        className="space-y-5"
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <InlineError error={save.error} />
        <fieldset className="space-y-3">
          <legend className="text-sm font-semibold text-zinc-900">{t("connect.channels.mapping.channel_side")}</legend>
          <p className="text-xs text-zinc-500">{t("connect.channels.mapping.channel_side_hint")}</p>
          <FormGrid>
            <Field label={t("connect.channels.mapping.room_code")} required error={err("external_room_code")}>
              <Input
                value={form.external_room_code}
                onChange={(e) => set("external_room_code", e.target.value)}
                maxLength={140}
                autoComplete="off"
                autoCapitalize="characters"
                spellCheck={false}
                className="font-mono"
                data-autofocus
              />
            </Field>
            <Field label={t("connect.channels.mapping.rate_code")} required error={err("external_rate_code")}>
              <Input
                value={form.external_rate_code}
                onChange={(e) => set("external_rate_code", e.target.value)}
                maxLength={140}
                autoComplete="off"
                autoCapitalize="characters"
                spellCheck={false}
                className="font-mono"
              />
            </Field>
          </FormGrid>
        </fieldset>

        <fieldset className="space-y-3">
          <legend className="text-sm font-semibold text-zinc-900">{t("connect.channels.mapping.tex_side")}</legend>
          <FormGrid>
            <Field label={t("connect.channels.mapping.room_type")} required error={err("room_type")}>
              <Select
                value={form.room_type}
                onChange={(e) => set("room_type", e.target.value)}
                placeholder={t("connect.select")}
                options={known(option(lookups.room_types, (r) => r.room_type_name || r.name), form.room_type)}
              />
            </Field>
            <Field label={t("connect.channels.mapping.board")} required error={err("board")}>
              <Select
                value={form.board}
                onChange={(e) => set("board", e.target.value)}
                placeholder={t("connect.select")}
                options={known(
                  lookups.boards.map((b) => {
                    // board names are shared with the CRS catalog; unknown codes show as they are
                    const name = t(`crs.board.${b}`)
                    return { value: b, label: name === `crs.board.${b}` ? b : `${b} · ${name}` }
                  }),
                  form.board,
                )}
              />
            </Field>
            <Field label={t("connect.channels.mapping.rate_plan")} hint={t("connect.channels.mapping.rate_plan_hint")}>
              <Select
                value={form.rate_plan}
                onChange={(e) => set("rate_plan", e.target.value)}
                placeholder={t("connect.channels.mapping.rate_plan_none")}
                options={known(option(lookups.rate_plans, (r) => r.rate_plan_name || r.name), form.rate_plan)}
              />
            </Field>
            <Field label={t("connect.channels.mapping.market")} required error={err("market")}>
              <Select
                value={form.market}
                onChange={(e) => set("market", e.target.value)}
                placeholder={t("connect.select")}
                options={known(option(lookups.markets, (r) => (r.market_name && r.market_name !== r.name ? `${r.market_name} (${r.name})` : r.name)), form.market)}
              />
            </Field>
            <Field label={t("connect.channels.mapping.sales_channel")} required error={err("sales_channel")}>
              <Select
                value={form.sales_channel}
                onChange={(e) => set("sales_channel", e.target.value)}
                placeholder={t("connect.select")}
                options={known(option(lookups.channels, (r) => r.channel_name || r.name), form.sales_channel)}
              />
            </Field>
            <Field label={t("connect.channels.mapping.currency")} required error={err("sell_currency")}>
              <Select
                value={form.sell_currency}
                onChange={(e) => set("sell_currency", e.target.value)}
                placeholder={t("connect.select")}
                options={currencies.map((c) => ({ value: c, label: c }))}
              />
            </Field>
          </FormGrid>
          <Field label={t("connect.channels.mapping.contract")} hint={t("connect.channels.mapping.contract_hint")}>
            <Select
              value={form.contract}
              onChange={(e) => set("contract", e.target.value)}
              placeholder={t("connect.channels.mapping.contract_auto")}
              options={known(
                option(lookups.contracts, (c) =>
                  [`${c.contract_code} · ${c.contract_name}`, c.market, c.status === "Draft" ? t("connect.channels.mapping.contract_draft") : ""].filter(Boolean).join(" · "),
                ),
                form.contract,
              )}
            />
          </Field>
        </fieldset>

        <fieldset className="space-y-3">
          <legend className="text-sm font-semibold text-zinc-900">{t("connect.channels.mapping.what_to_send")}</legend>
          <FormGrid>
            <Field label={t("connect.channels.mapping.occupancies")} required error={err("occupancies")} hint={t("connect.channels.mapping.occupancies_hint")}>
              <Input value={form.occupancies} onChange={(e) => set("occupancies", e.target.value)} inputMode="numeric" autoComplete="off" placeholder="1,2,3" />
            </Field>
            <Field label={t("connect.channels.mapping.horizon")} required error={err("horizon_days")} hint={t("connect.channels.mapping.horizon_hint")}>
              <Input type="number" min={1} max={365} step={1} inputMode="numeric" value={form.horizon_days} onChange={(e) => set("horizon_days", e.target.value)} />
            </Field>
          </FormGrid>
          <Switch
            checked={form.enabled}
            onChange={(v) => set("enabled", v)}
            label={t("connect.channels.mapping.enabled")}
            description={t("connect.channels.mapping.enabled_hint")}
          />
        </fieldset>
      </form>
    </Drawer>
  )
}
