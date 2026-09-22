import { useEffect, useState } from "react"
import { useTexMutation } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { useTexT } from "../../../i18n"
import { Button, Checkbox, Dialog, Field, FormGrid, InlineError, Input, Notice, Select, Textarea, useToast } from "../../../ui"
import { CsvPicker } from "../components/pickers"
import { BASIS, CONTRACT_STATUS, enumOptions } from "../lib/options"
import type { ContractBundle, ContractDoc } from "../lib/types"
import { invalidateLookups, joinCsv, splitCsv } from "../lib/util"

interface HeaderForm {
  contract_code: string
  contract_name: string
  market: string
  status: string
  pricing_basis: string
  contract_currency: string
  sell_currency: string
  priority: number
  is_bar: boolean
  sale_from: string
  sale_to: string
  stay_from: string
  stay_to: string
  channels: string
  notes: string
}

function toForm(c: ContractDoc | undefined, defaults: { currency?: string; market?: string }): HeaderForm {
  return {
    contract_code: c?.contract_code ?? "",
    contract_name: c?.contract_name ?? "",
    market: c?.market ?? defaults.market ?? "",
    status: c?.status ?? "Draft",
    pricing_basis: c?.pricing_basis ?? "PERSON",
    contract_currency: c?.contract_currency ?? defaults.currency ?? "EUR",
    sell_currency: c?.sell_currency ?? "",
    priority: c?.priority ?? 0,
    is_bar: Boolean(c?.is_bar),
    sale_from: c?.sale_from ?? "",
    sale_to: c?.sale_to ?? "",
    stay_from: c?.stay_from ?? "",
    stay_to: c?.stay_to ?? "",
    channels: joinCsv((c?.channels ?? []).map((x) => x.sales_channel)),
    notes: c?.notes ?? "",
  }
}

/** New contract / edit contract header (save_contract). */
export function ContractFormDialog({
  open,
  onClose,
  contract,
  onSaved,
}: {
  open: boolean
  onClose: () => void
  contract?: ContractDoc
  onSaved: (b: ContractBundle) => void
}) {
  const { t } = useTexT()
  const { boot, property } = useSession()
  const toast = useToast()
  const save = useTexMutation<{ data: Record<string, unknown> }, ContractBundle>("contracts", "save_contract")
  const [f, setF] = useState<HeaderForm>(() => toForm(contract, { currency: property?.currency, market: property?.default_market }))
  const [touched, setTouched] = useState(false)
  useEffect(() => {
    if (open) {
      setF(toForm(contract, { currency: property?.currency, market: property?.default_market ?? undefined }))
      setTouched(false)
      save.clearError()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, contract])
  const set = <K extends keyof HeaderForm>(k: K, v: HeaderForm[K]) => setF((x) => ({ ...x, [k]: v }))
  const locked = Boolean(contract?.active_version)
  const saleBad = f.sale_from && f.sale_to && f.sale_from > f.sale_to
  const stayBad = f.stay_from && f.stay_to && f.stay_from > f.stay_to
  const missing = !f.contract_code.trim() || !f.contract_name.trim() || !f.market || !f.contract_currency
  const invalid = missing || Boolean(saleBad) || Boolean(stayBad)

  const submit = async () => {
    setTouched(true)
    if (invalid) return
    const data: Record<string, unknown> = {
      contract_code: f.contract_code.trim(),
      contract_name: f.contract_name.trim(),
      market: f.market,
      status: f.status,
      pricing_basis: f.pricing_basis,
      contract_currency: f.contract_currency,
      sell_currency: f.sell_currency || null,
      priority: f.priority,
      is_bar: f.is_bar ? 1 : 0,
      sale_from: f.sale_from || null,
      sale_to: f.sale_to || null,
      stay_from: f.stay_from || null,
      stay_to: f.stay_to || null,
      channels: splitCsv(f.channels),
      notes: f.notes || null,
    }
    if (contract) data.name = contract.name
    else data.property = property?.name
    try {
      const b = await save.run({ data })
      invalidateLookups(b.contract.property)
      toast.success(contract ? t("rates.contract.saved") : t("rates.contract.created", { code: b.contract.contract_code }))
      onSaved(b)
      onClose()
    } catch {
      /* shown inline */
    }
  }

  const marketOpts = boot.markets.map((m) => ({ value: m.name, label: `${m.name} · ${m.market_name}` }))
  const ccyOpts = boot.currencies.map((c) => ({ value: c, label: c }))
  const channelOpts = boot.channels.map((c) => ({ value: c.name, label: c.channel_name }))

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={contract ? t("rates.contract.edit_title", { code: contract.contract_code }) : t("rates.contract.new_title")}
      description={contract ? undefined : t("rates.contract.new_desc")}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={save.pending}>
            {t("core.action.cancel")}
          </Button>
          <Button onClick={submit} loading={save.pending}>
            {contract ? t("core.action.save") : t("rates.contract.create")}
          </Button>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <FormGrid cols={2}>
          <Field label={t("rates.f.contract_code")} required hint={t("rates.h.contract_code")} error={touched && !f.contract_code.trim() ? t("rates.v.required") : undefined}>
            <Input value={f.contract_code} maxLength={40} onChange={(e) => set("contract_code", e.target.value.toUpperCase())} data-autofocus />
          </Field>
          <Field label={t("rates.f.contract_name")} required error={touched && !f.contract_name.trim() ? t("rates.v.required") : undefined}>
            <Input value={f.contract_name} maxLength={140} onChange={(e) => set("contract_name", e.target.value)} />
          </Field>
          <Field label={t("rates.f.market")} required hint={t("rates.h.market")} error={touched && !f.market ? t("rates.v.required") : undefined}>
            <Select value={f.market} onChange={(e) => set("market", e.target.value)} options={marketOpts} placeholder={t("rates.common.choose")} />
          </Field>
          <Field label={t("rates.f.status")} hint={t("rates.h.contract_status")}>
            <Select value={f.status} onChange={(e) => set("status", e.target.value)} options={enumOptions(t, "contract_status", CONTRACT_STATUS)} />
          </Field>
          <Field label={t("rates.f.pricing_basis")} hint={locked ? t("rates.h.locked_after_publish") : t("rates.h.pricing_basis")}>
            <Select value={f.pricing_basis} disabled={locked} onChange={(e) => set("pricing_basis", e.target.value)} options={enumOptions(t, "basis", BASIS)} />
          </Field>
          <Field label={t("rates.f.contract_currency")} required hint={locked ? t("rates.h.locked_after_publish") : t("rates.h.contract_currency")}>
            <Select value={f.contract_currency} disabled={locked} onChange={(e) => set("contract_currency", e.target.value)} options={ccyOpts} />
          </Field>
          <Field label={t("rates.f.sell_currency")} hint={t("rates.h.sell_currency")}>
            <Select value={f.sell_currency} onChange={(e) => set("sell_currency", e.target.value)} options={ccyOpts} placeholder={t("rates.common.same_as_contract")} />
          </Field>
          <Field label={t("rates.f.priority")} hint={t("rates.h.contract_priority")}>
            <Input type="number" step={1} value={String(f.priority)} onChange={(e) => set("priority", parseInt(e.target.value || "0", 10) || 0)} />
          </Field>
        </FormGrid>
        <Checkbox label={t("rates.f.is_bar")} checked={f.is_bar} onChange={(e) => set("is_bar", e.target.checked)} />
        <fieldset className="space-y-3">
          <legend className="text-sm font-semibold text-zinc-900">{t("rates.contract.validity")}</legend>
          <p className="text-xs text-zinc-500">{t("rates.h.sale_vs_stay")}</p>
          <FormGrid cols={4}>
            <Field label={t("rates.f.sale_from")}>
              <Input type="date" value={f.sale_from} onChange={(e) => set("sale_from", e.target.value)} />
            </Field>
            <Field label={t("rates.f.sale_to")} error={saleBad ? t("rates.v.range") : undefined}>
              <Input type="date" value={f.sale_to} onChange={(e) => set("sale_to", e.target.value)} />
            </Field>
            <Field label={t("rates.f.stay_from")}>
              <Input type="date" value={f.stay_from} onChange={(e) => set("stay_from", e.target.value)} />
            </Field>
            <Field label={t("rates.f.stay_to")} error={stayBad ? t("rates.v.range") : undefined}>
              <Input type="date" value={f.stay_to} onChange={(e) => set("stay_to", e.target.value)} />
            </Field>
          </FormGrid>
        </fieldset>
        <Field label={t("rates.f.channels")} hint={t("rates.h.channels")}>
          <CsvPicker value={f.channels} onChange={(v) => set("channels", v)} options={channelOpts} label={t("rates.f.channels")} allLabel={t("rates.common.all_channels")} />
        </Field>
        <Field label={t("rates.f.notes")}>
          <Textarea value={f.notes} onChange={(e) => set("notes", e.target.value)} rows={2} />
        </Field>
        {!contract && <Notice tone="info">{t("rates.contract.new_notice")}</Notice>}
        <InlineError error={save.error} />
        <button type="submit" hidden />
      </form>
    </Dialog>
  )
}

/** Duplicate a contract with its latest version as a new draft (R-55). */
export function DuplicateDialog({
  open,
  onClose,
  contract,
  onDone,
}: {
  open: boolean
  onClose: () => void
  contract: ContractDoc | { name: string; contract_code: string; contract_name: string; market: string; property: string }
  onDone: (b: ContractBundle) => void
}) {
  const { t } = useTexT()
  const { boot } = useSession()
  const toast = useToast()
  const dup = useTexMutation<{ name: string; contract_code: string; contract_name: string; market: string }, ContractBundle>(
    "contracts",
    "duplicate_contract",
  )
  const [code, setCode] = useState("")
  const [name, setName] = useState("")
  const [market, setMarket] = useState("")
  useEffect(() => {
    if (open) {
      setCode(`${contract.contract_code}-COPY`.slice(0, 40))
      setName(t("rates.contract.copy_name", { name: contract.contract_name }))
      setMarket(contract.market)
      dup.clearError()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  const submit = async () => {
    if (!code.trim()) return
    try {
      const b = await dup.run({ name: contract.name, contract_code: code.trim().toUpperCase(), contract_name: name.trim(), market })
      invalidateLookups(b.contract.property)
      toast.success(t("rates.contract.duplicated", { code: b.contract.contract_code }))
      onDone(b)
      onClose()
    } catch {
      /* inline */
    }
  }
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t("rates.contract.duplicate_title", { code: contract.contract_code })}
      description={t("rates.contract.duplicate_desc")}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={dup.pending}>
            {t("core.action.cancel")}
          </Button>
          <Button onClick={submit} loading={dup.pending} disabled={!code.trim()}>
            {t("rates.contract.duplicate")}
          </Button>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <Field label={t("rates.f.contract_code")} required hint={t("rates.h.contract_code")}>
          <Input value={code} maxLength={40} onChange={(e) => setCode(e.target.value.toUpperCase())} data-autofocus />
        </Field>
        <Field label={t("rates.f.contract_name")}>
          <Input value={name} maxLength={140} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={t("rates.f.market")} hint={t("rates.h.duplicate_market")}>
          <Select value={market} onChange={(e) => setMarket(e.target.value)} options={boot.markets.map((m) => ({ value: m.name, label: `${m.name} · ${m.market_name}` }))} />
        </Field>
        <InlineError error={dup.error} />
        <button type="submit" hidden />
      </form>
    </Dialog>
  )
}
