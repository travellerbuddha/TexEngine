// The child age bands drawer of the Pricing Workspace (PRICING_WORKSPACE_UX.md §3.8, D13; slice
// S11): a non-modal side panel (Drawer md, modal={false}) opened by "Child ages…" or #ages. One
// line per band: Label, From, Up to (not incl.), Infant. "Add band" starts a new band from the
// previous band's end (2.99 → 3) and focuses Up to; Enter there adds the next one. Labels are
// saved, not only displayed: a band committed with a blank label gets its generated label in the
// viewer's language (bands.addBand / updateBand); bands saved without a name are named only when
// the user asks ("Name them"). Codes are hidden behind "Advanced" (a rename cascades to the
// occupancy rules). Without bands of its own the version shows the inherited policy bands
// read-only, with "Customise for this contract". Every band edit is one workspace history entry;
// the child rules (age basis, children over the maximum, infants as occupants) are version
// settings, saved with Save like the Settings table.
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react"
import { Trash2, X } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { useTexT } from "../../../i18n"
import { Button, DecimalInput, Drawer, Field, IconButton, Input, Notice, Select, Switch } from "../../../ui"
import { newKey } from "../lib/keys"
import { AGE_BASIS, enumOptions } from "../lib/options"
import type { EditorState } from "../lib/tables"
import type { MatrixAgeBand, Row, VersionSetting } from "../lib/types"
import {
  addBand,
  ageMonths,
  bandCode,
  bandCoverage,
  bandLabel,
  bandRuleCount,
  bandsFromMatrix,
  customiseBands,
  defaultInfant,
  nameBands,
  nextBandCode,
  nextBandFrom,
  removeBand,
  renameBandCode,
  unnamedBands,
  updateBand,
  type BandLike,
  type BandPatch,
} from "./bands.ts"
import { policySource } from "./occupancy.ts"
import { str } from "./rows.ts"
import type { BandLabels } from "./useBandLabels"
import type { WorkspaceHistory } from "./useWorkspaceHistory"

/** The new band being typed: a row not yet in the table, under the key it will have. */
interface BandDraftState {
  key: string
  label: string
  labelTouched: boolean
  from: string
  to: string
  infant: boolean
  infantTouched: boolean
}

type BandField = "label" | "from" | "to" | "code"

export interface ChildAgesDrawerProps {
  open: boolean
  onClose: () => void
  state: EditorState
  readOnly: boolean
  history: WorkspaceHistory
  labels: BandLabels
  /** the bands the server priced with (price_matrix age_bands): inherited when the version has none */
  served?: MatrixAgeBand[]
  setSetting: (k: VersionSetting, v: string | number) => void
}

export function ChildAgesDrawer(p: ChildAgesDrawerProps) {
  const { t } = useTexT()
  const { state, readOnly, history, labels } = p
  const tables = state.tables
  const own = tables.age_bands
  const inherited = own.length ? [] : (p.served ?? []).filter((b) => b.source !== "version")
  const canEdit = !readOnly
  const [draft, setDraft] = useState<BandDraftState | null>(null)
  const [draftError, setDraftError] = useState("")
  const [showCodes, setShowCodes] = useState(false)
  const [codeErrors, setCodeErrors] = useState<Record<string, string>>({})
  const [confirming, setConfirming] = useState<string | null>(null)
  const body = useRef<HTMLDivElement>(null)
  const focusNext = useRef<{ key: string; field: BandField } | null>(null)

  // closing the drawer drops a new band that was not committed (and an open confirmation)
  useEffect(() => {
    if (p.open) return
    setDraft(null)
    setDraftError("")
    setConfirming(null)
  }, [p.open])

  // focus the field a gesture asked for once it is rendered (a new band's Up to)
  useEffect(() => {
    const want = focusNext.current
    if (!want) return
    focusNext.current = null
    requestAnimationFrame(() => body.current?.querySelector<HTMLInputElement>(`[data-band-field="${want.key}:${want.field}"]`)?.focus())
  })

  const gen = labels.gen
  const newDraft = (from: string): BandDraftState => ({ key: newKey(), label: "", labelTouched: false, from, to: "", infant: false, infantTouched: false })
  const startDraft = () => {
    const last = own[own.length - 1]
    const d = newDraft(last ? nextBandFrom(last.to_age) : "0")
    setDraft(d)
    setDraftError("")
    focusNext.current = { key: d.key, field: "to" }
  }
  const draftInfant = (d: BandDraftState) => (d.infantTouched ? d.infant : defaultInfant(own.length === 0, d.from, d.to))
  const draftBand = (d: BandDraftState): BandLike => ({ from_age: d.from, to_age: d.to, is_infant: draftInfant(d) ? 1 : 0 })
  const rangeOk = (from: unknown, to: unknown) => {
    const a = ageMonths(from === "" ? "0" : from)
    const b = ageMonths(to)
    return a !== null && b !== null && b > a
  }

  /** Commits the new band (its Up to was committed); `next`: Enter, so the next band starts. */
  const commitDraft = (d: BandDraftState, next: boolean) => {
    if (!rangeOk(d.from, d.to)) {
      setDraftError(t("rates.ages.invalid"))
      return
    }
    const infant = draftInfant(d)
    const label = d.labelTouched ? d.label.trim() : ""
    history.apply(t("rates.bands.h.add", { label: label || gen(draftBand(d)) }), (tb) => addBand(tb, { key: d.key, label, from: d.from, to: d.to, infant }, gen))
    setDraftError("")
    if (next) {
      const n = newDraft(nextBandFrom(d.to))
      setDraft(n)
      focusNext.current = { key: n.key, field: "to" }
    } else setDraft(null)
  }

  const commitBand = (band: Row, patch: BandPatch) => {
    const name = bandLabel(band, gen)
    history.apply(t("rates.bands.h.edit", { label: name }), (tb) => updateBand(tb, band._key, patch, gen))
  }

  const onCommit = (item: Row | BandDraftState, isDraft: boolean, field: BandField, text: string, enter: boolean) => {
    if (isDraft) {
      const d = item as BandDraftState
      const next: BandDraftState =
        field === "label" ? { ...d, label: text, labelTouched: text.trim() !== "" } : field === "from" ? { ...d, from: text } : field === "to" ? { ...d, to: text } : d
      setDraft(next)
      if (field === "to" && text.trim()) commitDraft(next, enter)
      return
    }
    const band = item as Row
    if (field === "code") {
      const res = renameBandCode(history.current() ?? tables, str(band.band_code), text)
      if ("error" in res) {
        setCodeErrors((e) => ({ ...e, [band._key]: t(`rates.bands.err.${res.error}`) }))
        return
      }
      setCodeErrors((e) => {
        const n = { ...e }
        delete n[band._key]
        return n
      })
      history.apply(t("rates.bands.h.rename", { from: bandCode(band), to: text.trim().toUpperCase() }), (tb) => {
        const r = renameBandCode(tb, str(band.band_code), text)
        return "error" in r ? tb : r.tables
      })
      return
    }
    commitBand(band, field === "label" ? { label: text } : field === "from" ? { from_age: text } : { to_age: text })
    // Enter in the last band's Up to starts the next band
    if (enter && field === "to" && !draft && own[own.length - 1]?._key === band._key && canEdit) {
      const n = newDraft(nextBandFrom(text))
      setDraft(n)
      focusNext.current = { key: n.key, field: "to" }
    }
  }

  const remove = (band: Row, confirmed: boolean) => {
    const rules = bandRuleCount(tables, bandCode(band))
    if (rules && !confirmed) {
      setConfirming(band._key)
      return
    }
    setConfirming(null)
    history.apply(t("rates.bands.h.remove", { label: bandLabel(band, gen) }), (tb) => removeBand(tb, band._key).tables)
  }

  const unnamed = canEdit ? unnamedBands(tables) : 0
  const list: { item: Row | BandDraftState; isDraft: boolean; key: string }[] = [
    ...own.map((b) => ({ item: b as Row | BandDraftState, isDraft: false, key: b._key })),
    ...(draft ? [{ item: draft as Row | BandDraftState, isDraft: true, key: draft.key }] : []),
  ]
  const s = state.settings
  const source = inherited.length ? policySource(inherited[0].source) : null
  const stripBands: readonly BandLike[] = own.length ? own : bandsFromMatrix(inherited)

  return (
    <Drawer open={p.open} onClose={p.onClose} title={t("rates.bands.title")} width="md" modal={false}>
      <div ref={body} className="space-y-4 text-sm">
        <p className="text-xs text-zinc-600">{t("rates.ages.intro")}</p>

        {inherited.length > 0 ? (
          <section aria-labelledby="bands-inherited" className="space-y-2">
            <h3 id="bands-inherited" className="text-sm font-semibold text-zinc-900">
              {t("rates.bands.inherited_title", { source: source ? t(`rates.occ.ladder.source.${source.scope.replace("+", "_")}`) : t("rates.occ.ladder.source.policy") })}
            </h3>
            <p className="text-xs text-zinc-500">{t("rates.bands.inherited_body")}</p>
            <ul className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
              {bandsFromMatrix(inherited).map((b) => (
                <li key={b.code} className="flex items-center justify-between gap-3 px-3 py-1.5">
                  <span className="font-medium text-zinc-900">{bandLabel(b, gen)}</span>
                  <span className="text-xs text-zinc-500 tabular-nums">{t("rates.bands.range", { from: str(b.from_age) || "0", to: str(b.to_age) })}</span>
                </li>
              ))}
            </ul>
            {canEdit && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => history.apply(t("rates.bands.h.customise"), (tb) => customiseBands(tb, inherited, gen))}
              >
                {t("rates.bands.customise")}
              </Button>
            )}
          </section>
        ) : (
          <section aria-labelledby="bands-own" className="space-y-2">
            <h3 id="bands-own" className="sr-only">
              {t("rates.bands.title")}
            </h3>
            {unnamed > 0 && (
              <Notice tone="warning">
                <span className="mr-2">{t("rates.bands.unnamed", { count: unnamed })}</span>
                <Button size="sm" variant="secondary" onClick={() => history.apply(t("rates.bands.h.name"), (tb) => nameBands(tb, gen))}>
                  {t("rates.bands.name_them")}
                </Button>
              </Notice>
            )}
            {list.length === 0 && <Notice tone="info">{t("rates.bands.none")}</Notice>}
            {list.length > 0 && (
              <div role="table" aria-label={t("rates.bands.title")} className="rounded-lg border border-zinc-200">
                <div role="row" className={cn("grid items-end gap-2 border-b border-zinc-200 px-2 py-1.5 text-[11px] font-semibold text-zinc-600", gridCols(showCodes))}>
                  <span role="columnheader">{t("rates.f.band_label")}</span>
                  <span role="columnheader">{t("rates.bands.col.from")}</span>
                  <span role="columnheader">{t("rates.bands.col.to")}</span>
                  <span role="columnheader">{t("rates.bands.col.infant")}</span>
                  {showCodes && <span role="columnheader">{t("rates.f.band_code")}</span>}
                  <span role="columnheader" className="sr-only">
                    {t("rates.bands.col.actions")}
                  </span>
                </div>
                {list.map(({ item, isDraft, key }) => {
                  const band = isDraft ? null : (item as Row)
                  const d = isDraft ? (item as BandDraftState) : null
                  const fields = band ? { from: str(band.from_age), to: str(band.to_age), infant: Boolean(Number(band.is_infant)) } : { from: d!.from, to: d!.to, infant: draftInfant(d!) }
                  const name = band ? bandLabel(band, gen) : t("rates.bands.new_band")
                  const labelValue = band ? str(band.label) : d!.labelTouched ? d!.label : fields.to && rangeOk(fields.from, fields.to) ? gen(draftBand(d!)) : ""
                  const invalid = band ? !rangeOk(fields.from, fields.to) : Boolean(draftError)
                  const code = band ? bandCode(band) : nextBandCode(tables, { infant: fields.infant })
                  return (
                    <div key={key} role="row" className="border-b border-zinc-100 px-2 py-1.5 last:border-b-0">
                      <div className={cn("grid items-center gap-2", gridCols(showCodes))}>
                        <span role="cell">
                          <CommitInput
                            field={`${key}:label`}
                            label={t("rates.bands.input.label", { band: name })}
                            value={labelValue}
                            placeholder={band ? gen(band) : gen({ from_age: fields.from, to_age: fields.to || "…", is_infant: fields.infant ? 1 : 0 })}
                            disabled={!canEdit}
                            onCommit={(v, enter) => onCommit(item, isDraft, "label", v, enter)}
                          />
                        </span>
                        <span role="cell">
                          <CommitInput
                            decimal
                            field={`${key}:from`}
                            label={t("rates.bands.input.from", { band: name })}
                            value={fields.from}
                            disabled={!canEdit}
                            invalid={invalid}
                            onCommit={(v, enter) => onCommit(item, isDraft, "from", v, enter)}
                          />
                        </span>
                        <span role="cell">
                          <CommitInput
                            decimal
                            field={`${key}:to`}
                            label={t("rates.bands.input.to", { band: name })}
                            value={fields.to}
                            disabled={!canEdit}
                            invalid={invalid}
                            onCommit={(v, enter) => onCommit(item, isDraft, "to", v, enter)}
                          />
                        </span>
                        <span role="cell" className="flex justify-center">
                          <input
                            type="checkbox"
                            role="switch"
                            aria-checked={fields.infant}
                            aria-label={t("rates.bands.input.infant", { band: name })}
                            className="size-4 accent-tex-600"
                            checked={fields.infant}
                            disabled={!canEdit}
                            onChange={(e) => {
                              const on = e.target.checked
                              if (d) setDraft({ ...d, infant: on, infantTouched: true })
                              else if (band) commitBand(band, { is_infant: on ? 1 : 0 })
                            }}
                          />
                        </span>
                        {showCodes && (
                          <span role="cell">
                            {band ? (
                              <CommitInput
                                field={`${key}:code`}
                                label={t("rates.bands.input.code", { band: name })}
                                value={code}
                                disabled={!canEdit}
                                invalid={Boolean(codeErrors[key])}
                                onCommit={(v) => onCommit(item, false, "code", v, false)}
                              />
                            ) : (
                              <span className="block px-1 font-mono text-xs text-zinc-500">{code}</span>
                            )}
                          </span>
                        )}
                        <span role="cell" className="flex justify-end">
                          {canEdit &&
                            (d ? (
                              <IconButton size="sm" label={t("rates.bands.cancel_new")} icon={<X className="size-4" />} onClick={() => setDraft(null)} />
                            ) : (
                              band && <IconButton size="sm" label={t("rates.bands.remove", { band: name })} icon={<Trash2 className="size-4" />} onClick={() => remove(band, false)} />
                            ))}
                        </span>
                      </div>
                      {invalid && <p className="mt-1 text-xs text-rose-700">{d && draftError ? draftError : t("rates.ages.invalid")}</p>}
                      {band && codeErrors[key] && <p className="mt-1 text-xs text-rose-700">{codeErrors[key]}</p>}
                      {band && confirming === key && (
                        <div role="group" aria-label={t("rates.bands.remove", { band: name })} className="mt-1.5 flex flex-wrap items-center gap-2 rounded-md bg-rose-50 px-2 py-1.5 text-xs text-rose-900">
                          <span>{t("rates.bands.remove_rules", { count: bandRuleCount(tables, code) })}</span>
                          <Button size="sm" variant="danger" onClick={() => remove(band, true)}>
                            {t("rates.bands.remove_do")}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                            {t("core.action.cancel")}
                          </Button>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
            {canEdit && (
              <div className="flex flex-wrap items-center gap-3">
                <Button size="sm" variant="secondary" onClick={startDraft} disabled={Boolean(draft)}>
                  {t("rates.ages.add")}
                </Button>
                {own.length > 0 && (
                  <label className="inline-flex items-center gap-1.5 text-xs text-zinc-600">
                    <input type="checkbox" className="size-3.5 accent-tex-600" checked={showCodes} onChange={(e) => setShowCodes(e.target.checked)} />
                    {t("rates.bands.advanced")}
                  </label>
                )}
              </div>
            )}
            {showCodes && <p className="text-xs text-zinc-500">{t("rates.bands.code_help")}</p>}
          </section>
        )}

        <AgeStrip bands={stripBands} labelOf={(b) => bandLabel(b, gen)} />

        <section aria-labelledby="child-rules" className="space-y-3 rounded-lg border border-zinc-200 p-3">
          <h3 id="child-rules" className="text-sm font-semibold text-zinc-900">
            {t("rates.bands.child_rules")}
          </h3>
          <Field label={t("rates.f.age_basis")} hint={t("rates.h.age_basis")}>
            <Select disabled={readOnly} value={String(s.age_basis)} onChange={(e) => p.setSetting("age_basis", e.target.value)} options={enumOptions(t, "age_basis", AGE_BASIS)} />
          </Field>
          <Switch
            disabled={readOnly}
            checked={Boolean(s.children_over_max_as_adults)}
            onChange={(v) => p.setSetting("children_over_max_as_adults", v ? 1 : 0)}
            label={t("rates.f.children_over_max_as_adults")}
            description={t("rates.h.children_over_max_as_adults")}
          />
          <Switch
            disabled={readOnly}
            checked={Boolean(s.infants_count_as_occupants)}
            onChange={(v) => p.setSetting("infants_count_as_occupants", v ? 1 : 0)}
            label={t("rates.f.infants_count_as_occupants")}
            description={t("rates.h.infants_count_as_occupants")}
          />
          <p className="text-xs text-zinc-500">{t("rates.bands.settings_note")}</p>
        </section>
      </div>
    </Drawer>
  )
}

const gridCols = (codes: boolean) => (codes ? "grid-cols-[minmax(0,1fr)_4rem_4.5rem_2.5rem_4.5rem_2rem]" : "grid-cols-[minmax(0,1fr)_4rem_4.5rem_2.5rem_2rem]")

/** A field that keeps what is typed and commits it on Enter or when it loses the focus. While it
 * does not have the focus it shows the stored value (an undo, another edit). */
function CommitInput(p: {
  field: string
  label: string
  value: string
  placeholder?: string
  decimal?: boolean
  disabled?: boolean
  invalid?: boolean
  onCommit: (text: string, enter: boolean) => void
}) {
  const [text, setText] = useState(p.value)
  const focused = useRef(false)
  useEffect(() => {
    if (!focused.current) setText(p.value)
  }, [p.value])
  const commit = (enter: boolean) => {
    if (text !== p.value || (enter && text !== "")) p.onCommit(text, enter)
  }
  const common = {
    "data-band-field": p.field,
    "aria-label": p.label,
    "aria-invalid": p.invalid || undefined,
    disabled: p.disabled,
    placeholder: p.placeholder,
    onFocus: () => {
      focused.current = true
    },
    onBlur: () => {
      focused.current = false
      commit(false)
    },
    onKeyDown: (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key !== "Enter") return
      e.preventDefault()
      commit(true)
    },
    className: cn("h-8! px-2! text-sm", p.invalid && "border-rose-400!"),
  }
  return p.decimal ? <DecimalInput {...common} value={text} onValueChange={setText} decimals={2} /> : <Input {...common} value={text} onChange={(e) => setText(e.target.value)} />
}

/** Coverage of the bands in months (bands.bandCoverage): labels, not codes; gaps and overlaps
 * marked, and said in words. The server check AGE_BANDS stays the authority. */
function AgeStrip({ bands, labelOf }: { bands: readonly BandLike[]; labelOf: (band: BandLike) => string }) {
  const { t } = useTexT()
  const cov = bandCoverage(bands)
  if (!cov.segments.length) return null
  const top = Math.max(18 * 12, cov.end)
  const at = (m: number) => `${(m / top) * 100}%`
  const span = (a: number, b: number) => `${((b - a) / top) * 100}%`
  const fmt = (months: number) => {
    const y = Math.floor(months / 12)
    const m = months % 12
    return m ? t("rates.ages.years_months", { y, m }) : t("rates.ages.years", { count: y })
  }
  const notes: ReactNode[] = []
  if (cov.start > 0) notes.push(t("rates.bands.min_age", { age: fmt(cov.start) }))
  if (cov.gaps.length) notes.push(t("rates.bands.gaps", { count: cov.gaps.length }))
  if (cov.overlaps.length) notes.push(t("rates.bands.overlaps", { count: cov.overlaps.length }))
  if (cov.invalid.length) notes.push(t("rates.bands.invalid_count", { count: cov.invalid.length }))
  return (
    <figure className="rounded-lg border border-zinc-200 p-3">
      <div className="relative h-7 overflow-hidden rounded bg-zinc-100" aria-hidden>
        {cov.segments.map((x, i) => (
          <span
            key={`${x.code}-${i}`}
            className={cn(
              "absolute inset-y-0 flex items-center justify-center overflow-hidden border-r border-white px-0.5 text-[10px] font-semibold whitespace-nowrap",
              x.band.is_infant === 1 || x.band.is_infant === true || x.band.is_infant === "1" ? "bg-sky-200 text-sky-900" : "bg-emerald-200 text-emerald-900",
            )}
            style={{ left: at(x.from), width: span(x.from, x.to) }}
          >
            {labelOf(x.band)}
          </span>
        ))}
        {cov.gaps.map((g, i) => (
          <span key={`g${i}`} className="absolute inset-y-0 bg-[repeating-linear-gradient(45deg,#fecdd3_0_4px,#fff1f2_4px_8px)]" style={{ left: at(g.from), width: span(g.from, g.to) }} />
        ))}
        {cov.overlaps.map((o, i) => (
          <span key={`o${i}`} className="absolute inset-y-0 bg-amber-600/40" style={{ left: at(o.from), width: span(o.from, o.to) }} />
        ))}
      </div>
      <figcaption className="mt-1 flex flex-wrap justify-between gap-x-3 text-[11px] text-zinc-500">
        <span>{t("rates.bands.strip_caption", { age: fmt(cov.end) })}</span>
        <span className={notes.length ? "text-rose-700" : undefined}>{notes.length ? notes.join(" · ") : t("rates.bands.coverage_ok")}</span>
      </figcaption>
    </figure>
  )
}
