import { useEffect, useState } from "react"
import { tex, useTexMutation } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { useTexT } from "../../../i18n"
import { Button, Checkbox, ConfirmDialog, Dialog, Field, FormGrid, InlineError, Input, Notice, Select, Textarea, useToast } from "../../../ui"
import { CsvPicker } from "../components/pickers"
import { BASIS, enumLabel, enumOptions } from "../lib/options"
import type { ContractBundle, ContractDoc, ContractStatusAction } from "../lib/types"
import { invalidateLookups, joinCsv, splitCsv } from "../lib/util"
import { shiftIsoYears } from "../workspace/periods.ts"

interface HeaderForm {
  contract_code: string
  contract_name: string
  market: string
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

/** New contract / edit contract header (save_contract). Once a version was published, what the
 * contract sells on is fixed (G-50, ADR-045): market, currency and basis for good, windows,
 * channels, priority and sell currency per version. Those fields are shown read-only; the server
 * refuses them too. The status moves through the contract's actions, never through this form. */
export function ContractFormDialog({
  open,
  onClose,
  contract,
  published = false,
  onSaved,
}: {
  open: boolean
  onClose: () => void
  contract?: ContractDoc
  /** A version of this contract was published (``get_contract().published``). */
  published?: boolean
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
  const locked = Boolean(contract) && published
  const fixedHint = locked ? t("rates.h.locked_fixed") : undefined
  const versionedHint = locked ? t("rates.h.locked_versioned") : undefined
  const saleBad = f.sale_from && f.sale_to && f.sale_from > f.sale_to
  const stayBad = f.stay_from && f.stay_to && f.stay_from > f.stay_to
  const missing = !f.contract_code.trim() || !f.contract_name.trim() || !f.market || !f.contract_currency
  const invalid = missing || (!locked && (Boolean(saleBad) || Boolean(stayBad)))

  const submit = async () => {
    setTouched(true)
    if (invalid) return
    const data: Record<string, unknown> = {
      contract_code: f.contract_code.trim(),
      contract_name: f.contract_name.trim(),
      is_bar: f.is_bar ? 1 : 0,
      notes: f.notes || null,
    }
    if (!locked)
      Object.assign(data, {
        market: f.market,
        pricing_basis: f.pricing_basis,
        contract_currency: f.contract_currency,
        sell_currency: f.sell_currency || null,
        priority: f.priority,
        sale_from: f.sale_from || null,
        sale_to: f.sale_to || null,
        stay_from: f.stay_from || null,
        stay_to: f.stay_to || null,
        channels: splitCsv(f.channels),
      })
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
        {locked && (
          <Notice tone="info" title={t("rates.contract.locked_title")}>
            {t("rates.contract.locked_body")}
          </Notice>
        )}
        <FormGrid cols={2}>
          <Field label={t("rates.f.contract_code")} required hint={t("rates.h.contract_code")} error={touched && !f.contract_code.trim() ? t("rates.v.required") : undefined}>
            <Input value={f.contract_code} maxLength={40} onChange={(e) => set("contract_code", e.target.value.toUpperCase())} data-autofocus />
          </Field>
          <Field label={t("rates.f.contract_name")} required error={touched && !f.contract_name.trim() ? t("rates.v.required") : undefined}>
            <Input value={f.contract_name} maxLength={140} onChange={(e) => set("contract_name", e.target.value)} />
          </Field>
          <Field label={t("rates.f.market")} required hint={fixedHint ?? t("rates.h.market")} error={touched && !f.market ? t("rates.v.required") : undefined}>
            <Select value={f.market} disabled={locked} onChange={(e) => set("market", e.target.value)} options={marketOpts} placeholder={t("rates.common.choose")} />
          </Field>
          <Field label={t("rates.f.pricing_basis")} hint={fixedHint ?? t("rates.h.pricing_basis")}>
            <Select value={f.pricing_basis} disabled={locked} onChange={(e) => set("pricing_basis", e.target.value)} options={enumOptions(t, "basis", BASIS)} />
          </Field>
          <Field label={t("rates.f.contract_currency")} required hint={fixedHint ?? t("rates.h.contract_currency")}>
            <Select value={f.contract_currency} disabled={locked} onChange={(e) => set("contract_currency", e.target.value)} options={ccyOpts} />
          </Field>
          <Field label={t("rates.f.sell_currency")} hint={versionedHint ?? t("rates.h.sell_currency")}>
            <Select value={f.sell_currency} disabled={locked} onChange={(e) => set("sell_currency", e.target.value)} options={ccyOpts} placeholder={t("rates.common.same_as_contract")} />
          </Field>
          <Field label={t("rates.f.priority")} hint={versionedHint ?? t("rates.h.contract_priority")}>
            <Input type="number" step={1} disabled={locked} value={String(f.priority)} onChange={(e) => set("priority", parseInt(e.target.value || "0", 10) || 0)} />
          </Field>
        </FormGrid>
        <Checkbox label={t("rates.f.is_bar")} checked={f.is_bar} onChange={(e) => set("is_bar", e.target.checked)} />
        <fieldset className="space-y-3">
          <legend className="text-sm font-semibold text-zinc-900">{t("rates.contract.validity")}</legend>
          <p className="text-xs text-zinc-500">{versionedHint ?? t("rates.h.sale_vs_stay")}</p>
          <FormGrid cols={4}>
            <Field label={t("rates.f.sale_from")}>
              <Input type="date" disabled={locked} value={f.sale_from} onChange={(e) => set("sale_from", e.target.value)} />
            </Field>
            <Field label={t("rates.f.sale_to")} error={!locked && saleBad ? t("rates.v.range") : undefined}>
              <Input type="date" disabled={locked} value={f.sale_to} onChange={(e) => set("sale_to", e.target.value)} />
            </Field>
            <Field label={t("rates.f.stay_from")}>
              <Input type="date" disabled={locked} value={f.stay_from} onChange={(e) => set("stay_from", e.target.value)} />
            </Field>
            <Field label={t("rates.f.stay_to")} error={!locked && stayBad ? t("rates.v.range") : undefined}>
              <Input type="date" disabled={locked} value={f.stay_to} onChange={(e) => set("stay_to", e.target.value)} />
            </Field>
          </FormGrid>
        </fieldset>
        <Field label={t("rates.f.channels")} hint={versionedHint ?? t("rates.h.channels")}>
          <CsvPicker value={f.channels} disabled={locked} onChange={(v) => set("channels", v)} options={channelOpts} label={t("rates.f.channels")} allLabel={t("rates.common.all_channels")} />
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

/** Suspend, resume, archive or restore a contract (G-50): an explicit, audited action with a
 * reason (``contract.publish``), the only way besides publishing that the status changes. */
export function ContractStatusDialog({
  open,
  onClose,
  contract,
  action,
  onDone,
}: {
  open: boolean
  onClose: () => void
  contract: { name: string; contract_code: string }
  action: ContractStatusAction
  onDone: () => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  return (
    <ConfirmDialog
      open={open}
      onClose={onClose}
      tone={action === "suspend" || action === "archive" ? "danger" : "primary"}
      requireReason
      title={t(`rates.contract.status_title.${action}`, { code: contract.contract_code })}
      body={t(`rates.contract.status_body.${action}`)}
      confirmLabel={t(`rates.contract.status_action.${action}`)}
      onConfirm={async (reason) => {
        const r = await tex<{ status: string }>("contracts", "set_contract_status", { name: contract.name, action, reason }, { post: true })
        toast.success(t("rates.contract.status_done", { code: contract.contract_code, status: enumLabel(t, "contract_status", r.status) }))
        onDone()
      }}
    />
  )
}

/** What a duplicate opens next: the new contract, or (a new season) its draft with the dates moved. */
export function duplicateTarget(b: ContractBundle, opts?: { shiftYears?: number }): string {
  const draft = b.versions.find((v) => v.status === "Draft")
  const base = `/tex/rates/contracts/${encodeURIComponent(b.contract.name)}`
  return opts?.shiftYears && draft ? `${base}/versions/${encodeURIComponent(draft.name)}?shift_years=${opts.shiftYears}#pricing` : base
}

/** "DE-2026" → "DE-2027": the first year in a code or name, a year on (none: unchanged). */
export function nextSeasonText(s: string): string | null {
  const m = /(20\d\d)/.exec(s)
  return m ? s.replace(m[1], String(Number(m[1]) + 1)) : null
}

type Windows = { sale_from: string; sale_to: string; stay_from: string; stay_to: string }

/** Duplicate a contract with its latest version as a new draft (R-55). "A new season" (UX revision
 * 2026-10) also moves the contract's sale and stay windows a year on (shown, editable) and opens
 * the copy's draft with every period and offer a year on, as an unsaved edit listed for checking. */
export function DuplicateDialog({
  open,
  onClose,
  contract,
  onDone,
}: {
  open: boolean
  onClose: () => void
  contract: (ContractDoc | { name: string; contract_code: string; contract_name: string; market: string; property: string }) & Partial<Record<keyof Windows, string | null>>
  onDone: (b: ContractBundle, opts?: { shiftYears?: number }) => void
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
  const [season, setSeason] = useState(false)
  const [win, setWin] = useState<Windows>({ sale_from: "", sale_to: "", stay_from: "", stay_to: "" })
  const [err, setErr] = useState<Error | null>(null)
  const [busy, setBusy] = useState(false)
  const copyCode = `${contract.contract_code}-COPY`.slice(0, 40)
  const copyName = t("rates.contract.copy_name", { name: contract.contract_name })
  useEffect(() => {
    if (open) {
      setCode(copyCode)
      setName(copyName)
      setMarket(contract.market)
      setSeason(false)
      setErr(null)
      dup.clearError()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  const toggleSeason = (on: boolean) => {
    setSeason(on)
    const year = (v?: string | null, edge: "start" | "end" = "start") => (v ? shiftIsoYears(v, 1, edge) : "")
    if (on) {
      setWin({ sale_from: year(contract.sale_from), sale_to: year(contract.sale_to, "end"), stay_from: year(contract.stay_from), stay_to: year(contract.stay_to, "end") })
      // a code or name that names the season's year names the next one; otherwise left as it is
      if (code === copyCode) setCode((nextSeasonText(contract.contract_code) ?? copyCode).toUpperCase().slice(0, 40))
      if (name === copyName) setName(nextSeasonText(contract.contract_name) ?? copyName)
    } else {
      if (code === (nextSeasonText(contract.contract_code) ?? "").toUpperCase()) setCode(copyCode)
      if (name === nextSeasonText(contract.contract_name)) setName(copyName)
    }
  }
  const windowBad = (a: string, b: string) => Boolean(a && b && b < a)
  const bad = season && (windowBad(win.sale_from, win.sale_to) || windowBad(win.stay_from, win.stay_to))
  const submit = async () => {
    if (!code.trim() || bad) return
    setBusy(true)
    setErr(null)
    try {
      const b = await dup.run({ name: contract.name, contract_code: code.trim().toUpperCase(), contract_name: name.trim(), market })
      invalidateLookups(b.contract.property)
      if (season) {
        // the copy is not published yet: its sale and stay windows are the contract's (save_contract)
        await tex("contracts", "save_contract", { data: { name: b.contract.name, ...win } }, { post: true })
      }
      toast.success(t("rates.contract.duplicated", { code: b.contract.contract_code }))
      onDone(b, season ? { shiftYears: 1 } : undefined)
      onClose()
    } catch (e) {
      setErr(e as Error)
    } finally {
      setBusy(false)
    }
  }
  const dateField = (k: keyof Windows, label: string) => (
    <Field label={label}>
      <Input type="date" value={win[k]} onChange={(e) => setWin({ ...win, [k]: e.target.value })} />
    </Field>
  )
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t("rates.contract.duplicate_title", { code: contract.contract_code })}
      description={t("rates.contract.duplicate_desc")}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {t("core.action.cancel")}
          </Button>
          <Button onClick={submit} loading={busy} disabled={!code.trim() || bad}>
            {season ? t("rates.contract.duplicate_season") : t("rates.contract.duplicate")}
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
        <Checkbox
          label={<span className="font-medium">{t("rates.contract.season_label")}</span>}
          checked={season}
          onChange={(e) => toggleSeason(e.target.checked)}
        />
        {season && (
          <div className="space-y-3 rounded-lg border border-tex-200 bg-tex-50/40 p-3">
            <p className="text-xs text-zinc-700">{t("rates.contract.season_hint")}</p>
            <FormGrid cols={2}>
              {dateField("stay_from", t("rates.f.stay_from"))}
              {dateField("stay_to", t("rates.f.stay_to"))}
              {dateField("sale_from", t("rates.f.sale_from"))}
              {dateField("sale_to", t("rates.f.sale_to"))}
            </FormGrid>
            {bad && <p className="text-xs font-medium text-rose-700">{t("rates.v.range")}</p>}
          </div>
        )}
        <Field label={t("rates.f.contract_code")} required hint={t("rates.h.contract_code")}>
          <Input value={code} maxLength={40} onChange={(e) => setCode(e.target.value.toUpperCase())} data-autofocus />
        </Field>
        <Field label={t("rates.f.contract_name")}>
          <Input value={name} maxLength={140} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={t("rates.f.market")} hint={t("rates.h.duplicate_market")}>
          <Select value={market} onChange={(e) => setMarket(e.target.value)} options={boot.markets.map((m) => ({ value: m.name, label: `${m.name} · ${m.market_name}` }))} />
        </Field>
        <InlineError error={err ?? dup.error} />
        <button type="submit" hidden />
      </form>
    </Dialog>
  )
}
