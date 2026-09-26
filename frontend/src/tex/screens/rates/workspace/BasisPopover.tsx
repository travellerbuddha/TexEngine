import { useRef, useState } from "react"
import { ChevronDown, Lock } from "lucide-react"
import { useTexMutation } from "../../../lib/api"
import { useTexT } from "../../../i18n"
import { Button, InlineError, Notice, Popover, Segmented, Tooltip } from "../../../ui"
import { enumLabel } from "../lib/options"
import type { ContractBundle, VersionDoc } from "../lib/types"

type Basis = "PERSON" | "ROOM"

/** The chip's look (shared with the other context chips). */
export const CHIP = "inline-flex max-w-full min-w-0 items-baseline gap-1.5 rounded-md px-1.5 py-0.5 text-sm"
export const CHIP_BUTTON = `${CHIP} border border-zinc-200 bg-white hover:border-tex-300 hover:bg-tex-50/60 focus-visible:outline-2 focus-visible:outline-tex-500 aria-expanded:border-tex-400`

/**
 * The pricing basis chip of the context header and its popover (PRICING_WORKSPACE_UX.md §3.2.1,
 * acceptance step 1). A button only while the viewer may edit the contract and no version was
 * published (`can_edit_contract && !basis_locked`, GAP-10); otherwise a read-only chip, locked
 * after the first publish. Apply saves the contract header at once through the existing
 * `contracts.save_contract({name, pricing_basis})`, which re-checks contract.edit and refuses a
 * change after publish (G-50); the version being edited is not touched, so unsaved rule edits stay.
 * Non-modal: no dialog opens.
 */
export function BasisPopover({ doc, onApplied }: { doc: VersionDoc; onApplied: (basis: Basis) => void }) {
  const { t } = useTexT()
  const basis = doc.contract_doc.pricing_basis as Basis | undefined
  const value = enumLabel(t, "basis", basis)
  const label = t("rates.f.pricing_basis")
  const name = t("rates.ws.basis.name", { basis: value })
  const ref = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const [choice, setChoice] = useState<Basis>(basis ?? "PERSON")
  const save = useTexMutation<{ data: { name: string; pricing_basis: Basis } }, ContractBundle>("contracts", "save_contract")

  const text = (
    <>
      <span className="text-xs text-zinc-500">{label}</span>
      <span className="truncate font-medium text-zinc-900">{value}</span>
    </>
  )
  // an agent's catalogue does not carry the basis
  if (!basis) return null
  if (!doc.can_edit_contract || doc.basis_locked) {
    if (!doc.basis_locked) return <span className={CHIP}>{text}</span>
    return (
      <Tooltip content={t("rates.ws.basis.locked")}>
        <span className={CHIP} tabIndex={0} aria-label={name}>
          {text}
          <Lock className="size-3 self-center text-zinc-500" aria-hidden />
        </span>
      </Tooltip>
    )
  }

  const apply = async () => {
    try {
      const r = await save.run({ data: { name: doc.contract_doc.name, pricing_basis: choice } })
      onApplied(r.contract.pricing_basis)
      setOpen(false)
    } catch {
      // the server's message is shown in the popover (save.error)
    }
  }
  return (
    <>
      <button
        ref={ref}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={name}
        className={CHIP_BUTTON}
        onClick={() => {
          if (!open) {
            setChoice(basis)
            save.clearError()
          }
          setOpen(!open)
        }}
      >
        {text}
        <ChevronDown className="size-3.5 self-center text-zinc-500" aria-hidden />
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchorRef={ref} label={label} width="md">
        <div className="space-y-3">
          <Segmented<Basis>
            value={choice}
            onChange={setChoice}
            label={label}
            options={[
              { value: "PERSON", label: t("rates.basis.PERSON") },
              { value: "ROOM", label: t("rates.basis.ROOM") },
            ]}
          />
          <p className="text-sm text-zinc-700">{t(`rates.ws.basis.reads.${choice}`)}</p>
          <Notice tone="info">{t("rates.ws.basis.notice")}</Notice>
          <InlineError error={save.error} />
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setOpen(false)}>
              {t("core.action.cancel")}
            </Button>
            <Button size="sm" loading={save.pending} disabled={choice === basis} onClick={() => void apply()}>
              {t("core.action.apply")}
            </Button>
          </div>
        </div>
      </Popover>
    </>
  )
}
