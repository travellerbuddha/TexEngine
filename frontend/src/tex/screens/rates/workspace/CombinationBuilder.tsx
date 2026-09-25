// The structured special-combination builder (PRICING_WORKSPACE_UX.md §3.7.1–§3.7.3, D8, D13; slice
// S12): an inline panel under the occupancy ladder (never a modal), opened by "Add combination" or a
// card's Edit. The combination is never typed as text: Adults and Children steppers, quick chips of
// the valid combinations (occupancy.combinationChips over the rooms' capacity from the server; a
// chip no room in scope can host is greyed out and names the rooms that can), and "any adults" /
// "any children" under More. Rooms and Periods (all, or chosen: one rule row each). One line per
// child ("Child 1 (oldest)" by child_ordering) with an age band (labels, or Any), a Rule and a Value
// that takes the `occupancy` shorthand (its form sets the Rule; a number alone takes the Rule
// chosen); a child can have lines for several bands, each band condition on its own. "+ Adult rule"
// and "+ Whole-stay price". A reading line says what Save writes; Save writes it through
// occupancy.planCombination / persistCombination as one history entry, replacing the edited
// card's rows. Nothing here computes a price.
import { useEffect, useId, useMemo, useRef, type ReactNode } from "react"
import { Plus, X } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { useTexT } from "../../../i18n"
import { Button, Checkbox, IconButton, Input, Segmented, Select, Tooltip } from "../../../ui"
import { enumOptions } from "../lib/options"
import { OPS_BY_CONTEXT } from "../lib/shorthand"
import type { Tables } from "../lib/tables"
import { bandCode } from "./bands.ts"
import type { ComboText } from "./CombinationCards"
import type { Basis } from "./model.ts"
import {
  builderLine,
  builderValueText,
  childQualifier,
  combinationChips,
  ensureChildLines,
  isSingleUseCard,
  planCombination,
  readBuilderValue,
  shownChildPositions,
  type BuilderDraft,
  type BuilderIssue,
  type BuilderLine,
  type CapacityLike,
  type CombinationCard,
  type CombinationPlan,
  type ComboChip,
} from "./occupancy.ts"
import { str } from "./rows.ts"
import { KEPT } from "./keptState.ts"
import { useKeptState } from "./useKeptState"
import type { BandLabels } from "./useBandLabels"

/** Child positions a builder offers for "any children" (the server prices at most 8 in a sample). */
const MAX_CHILD_LINES = 8

type Scope = "all" | "chosen"

/** An example value per rule (a number alone takes the rule chosen). */
const PLACEHOLDER: Record<string, string> = { MULTIPLY: "0.5", PERCENT_OF: "50", ADJUST_PERCENT: "-10", ABSOLUTE: "25", FIXED: "25", ADD: "25", SUBTRACT: "25" }

export interface CombinationBuilderProps {
  initial: BuilderDraft
  /** the card being edited (its name in the title), or null for a new combination */
  editing: CombinationCard | null
  tables: Tables
  /** the tables as last written (history.current): what Save plans against */
  current: () => Tables
  /** the special combination cards (the twin refusal names them) */
  cards: readonly CombinationCard[]
  text: ComboText
  labels: BandLabels
  roomName: (rt: string) => string
  capacities: readonly (CapacityLike & { room_type: string })[]
  basis: Basis
  extraUnit: string
  includedAdults: number
  ordering: string
  minorUnits: number
  decimalMark: "." | ","
  ccy: string
  onCancel: () => void
  onSave: (plan: CombinationPlan) => void
}

export function CombinationBuilder(p: CombinationBuilderProps) {
  const { t } = useTexT()
  const titleId = useId()
  const errId = useId()
  // kept by the editor while the builder is open (a section switch or a collapsed Occupancy
  // unmounts it; coming back shows the draft as it was)
  const [draft, setDraft, restored] = useKeptState<BuilderDraft>(KEPT.comboDraft, p.initial)
  // "More" starts open when the draft uses what it holds (an edited card's any / Always wins)
  const [moreOpen, setMoreOpen] = useKeptState(KEPT.comboMore, () => p.initial.isOverride || p.initial.adults === "*" || p.initial.children === "*")
  // the panel opens with the focus in its first field (the opener may be gone: Add hides, a card is
  // replaced); a builder shown again after a section switch leaves the focus where it is
  const firstRef = useRef<HTMLInputElement | null>(null)
  useEffect(() => {
    if (restored) return
    const el = firstRef.current?.disabled ? firstRef.current?.closest("form")?.querySelector<HTMLElement>("input:not(:disabled), select, button") : firstRef.current
    el?.focus()
    // only when the builder opens
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const fmt = { minorUnits: p.minorUnits, decimalMark: p.decimalMark }
  const plan = useMemo(() => planCombination(p.tables, draft, fmt), [p.tables, draft, p.minorUnits, p.decimalMark]) // eslint-disable-line react-hooks/exhaustive-deps
  const issueOf = (id: string) => plan.issues.find((i) => "line" in i && i.line === id)

  // ─── the combination: steppers, chips, any ───────────────────────────────
  const scoped = draft.roomsAll ? null : draft.rooms
  const chips = useMemo(() => combinationChips(p.capacities, scoped), [p.capacities, scoped])
  const maxAdults = Math.max(1, ...p.capacities.map((c) => c.max_adults), draft.adults === "*" ? 1 : draft.adults)
  const maxChildren = Math.max(0, ...p.capacities.map((c) => c.max_children), draft.children === "*" ? 0 : draft.children)
  const hostable = chips.some((c) => c.enabled && (draft.adults === "*" || c.adults === draft.adults) && (draft.children === "*" || c.children === draft.children))
  const name = p.text.name(draft.adults === "*" ? null : draft.adults, draft.children === "*" ? null : draft.children)

  const change = (next: (d: BuilderDraft) => BuilderDraft) => setDraft((d) => ensureChildLines(next(d)))
  const setCombination = (adults: number | "*", children: number | "*") => change((d) => ({ ...d, adults, children }))
  const setCount = (which: "adults" | "children", raw: string, min: number, max: number) => {
    if (!/^[0-9]{1,2}$/.test(raw)) return
    const n = Math.min(max, Math.max(min, parseInt(raw, 10)))
    change((d) => ({ ...d, [which]: n }))
  }

  // ─── lines ─────────────────────────────────────────────────────────────
  const bandCodes = useMemo(() => [...new Set(p.labels.bands.map((b) => bandCode(b)).filter(Boolean))], [p.labels.bands])
  const editLine = (id: string, edit: (l: BuilderLine) => BuilderLine) =>
    change((d) => ({
      ...d,
      childLines: d.childLines.map((l) => (l.id === id ? edit(l) : l)),
      adultLines: d.adultLines.map((l) => (l.id === id ? edit(l) : l)),
      whole: d.whole && d.whole.id === id ? edit(d.whole) : d.whole,
    }))
  /** typing: the shorthand's form sets the Rule; a number alone keeps it */
  const setText = (id: string, text: string) =>
    editLine(id, (l) => {
      const v = readBuilderValue(text, l.op, p.minorUnits)
      return { ...l, text, op: v.kind === "rule" ? v.op : l.op }
    })
  /** choosing a Rule keeps the number typed: the op chosen is the op stored */
  const setOp = (id: string, op: string) =>
    editLine(id, (l) => {
      if (op === "INHERIT") return { ...l, op, text: "" }
      const v = readBuilderValue(l.text, l.op, p.minorUnits)
      return { ...l, op, text: v.kind === "rule" && v.op !== "INHERIT" ? builderValueText(op, v.value, fmt) : l.text }
    })
  /** leaving a field shows its value as stored ("x0.5" → "0.5" under Multiply) */
  const tidy = (id: string) =>
    editLine(id, (l) => {
      const v = readBuilderValue(l.text, l.op, p.minorUnits)
      return v.kind === "rule" ? { ...l, text: builderValueText(v.op, v.value, fmt) } : l
    })
  const removeLine = (id: string) =>
    change((d) => {
      const line = d.childLines.find((l) => l.id === id)
      // any children: removing the last child position's only line takes that position away
      const lastAny = line && d.children === "*" && line.position === d.anyChildren && d.anyChildren > 1 && d.childLines.filter((l) => l.position === line.position).length === 1
      return {
        ...d,
        anyChildren: lastAny ? d.anyChildren - 1 : d.anyChildren,
        childLines: d.childLines.filter((l) => l.id !== id),
        adultLines: d.adultLines.filter((l) => l.id !== id),
        whole: d.whole?.id === id ? null : d.whole,
      }
    })
  const addChildBand = (position: number) => {
    const used = new Set(draft.childLines.filter((l) => l.position === position).map((l) => str(l.age_band).toUpperCase()))
    const free = bandCodes.find((c) => !used.has(c)) ?? ""
    change((d) => ({ ...d, childLines: [...d.childLines, builderLine({ position, age_band: free })].sort((a, b) => a.position - b.position) }))
  }
  const addAdult = () => change((d) => ({ ...d, adultLines: [...d.adultLines, builderLine({ position: d.adults === "*" ? maxAdults : d.adults })] }))
  const addWhole = () => change((d) => ({ ...d, whole: builderLine({ position: 0 }) }))

  // ─── words ─────────────────────────────────────────────────────────────
  const childName = (position: number) => {
    const q = childQualifier(p.ordering, position, draft.children)
    return q ? t(`rates.combo.b.child_${q}`, { n: position }) : t("rates.combo.b.child", { n: position })
  }
  const opOptions = useMemo(() => enumOptions(t, "op", OPS_BY_CONTEXT.occupancy), [t])
  const bandOptions = (current: string) => {
    const list = bandCodes.map((c) => ({ value: c, label: p.labels.labelOf(c) }))
    const code = str(current).toUpperCase()
    if (code && !bandCodes.includes(code)) list.push({ value: code, label: t("rates.occ.ladder.row.unknown_band", { code }) })
    return [{ value: "", label: t("rates.combo.b.any_age") }, ...list]
  }
  const guestUnit = p.basis === "ROOM" ? (p.extraUnit === "ROOM_PRICE" ? "room" : "person_share") : "person"
  const unitWord = (unit: string) => t(`rates.occ.unit.${unit}`, { count: p.includedAdults })
  const issueText = (i: BuilderIssue, lineName?: string): string => {
    switch (i.code) {
      case "VALUE":
        return t(`rates.sh.err.${i.value}`)
      case "DUPLICATE":
        return t(draft.adultLines.some((l) => l.id === i.line) ? "rates.combo.b.err.DUPLICATE_ADULT" : "rates.combo.b.err.DUPLICATE", { line: lineName ?? "" })
      case "POSITION":
        return t("rates.combo.b.err.POSITION", { line: lineName ?? "", name })
      case "TWIN": {
        const owners = p.cards.filter((c) => c.keys.some((k) => i.keys.includes(k))).map((c) => p.text.name(c.adults, c.children))
        return t("rates.combo.b.err.TWIN", { line: lineName ?? "", cards: [...new Set(owners)].join(", ") || name })
      }
      default:
        return t(`rates.combo.b.err.${i.code}`)
    }
  }

  // ─── the reading line and Save ─────────────────────────────────────────
  const rulesText = p.text.rules(plan.rules)
  const reading = rulesText ? t("rates.combo.card.main", { name, rules: rulesText }) : name
  const secondary = [p.text.bands(plan.rules), p.text.scope(draft.roomsAll ? [""] : draft.rooms, draft.periodsAll ? [""] : draft.periods)].filter(Boolean).join(" · ")
  const general = plan.issues.filter((i) => !("line" in i))
  const single = plan.spec !== null && isSingleUseCard({ combination: plan.combination, rules: plan.rules })
  const save = () => {
    // plan against the tables as last written (an edit made meanwhile elsewhere is not lost)
    const fresh = planCombination(p.current(), draft, fmt)
    if (fresh.spec) p.onSave(fresh)
  }

  // ─── one rule line ─────────────────────────────────────────────────────
  const lineRow = (l: BuilderLine, head: ReactNode, lineName: string, opts: { band?: boolean; removable: boolean; hint?: string }) => {
    const v = readBuilderValue(l.text, l.op, p.minorUnits)
    const issue = issueOf(l.id)
    const message = issue ? issueText(issue, lineName) : v.kind === "error" ? t(`rates.sh.err.${v.code}`) : ""
    const msgId = `${errId}-${l.id}`
    const inherit = l.op === "INHERIT"
    const suffix = l.op === "MULTIPLY" ? "×" : l.op === "PERCENT_OF" || l.op === "ADJUST_PERCENT" ? "%" : inherit ? "" : p.ccy
    return (
      <div key={l.id} role="group" aria-label={lineName} className="grid grid-cols-2 items-start gap-x-2 gap-y-1 sm:grid-cols-[9.5rem_minmax(8rem,12rem)_minmax(8rem,11rem)_minmax(6rem,9rem)_2rem]">
        <div className="col-span-2 flex min-h-8 items-center text-xs font-medium text-zinc-800 sm:col-span-1">{head}</div>
        {opts.band ? (
          <Select
            aria-label={t("rates.combo.b.field", { field: t("rates.f.age_band"), line: lineName })}
            value={str(l.age_band).toUpperCase()}
            className="h-8! text-xs!"
            options={bandOptions(l.age_band)}
            onChange={(e) => editLine(l.id, (x) => ({ ...x, age_band: e.target.value }))}
          />
        ) : (
          <span className="hidden sm:block" aria-hidden />
        )}
        <Select aria-label={t("rates.combo.b.field", { field: t("rates.f.rule"), line: lineName })} value={l.op} className="h-8! text-xs!" options={opOptions} onChange={(e) => setOp(l.id, e.target.value)} />
        <div className="relative">
          <Input
            aria-label={t("rates.combo.b.field", { field: t("rates.f.value"), line: lineName })}
            aria-invalid={message ? true : undefined}
            aria-describedby={message ? msgId : undefined}
            autoComplete="off"
            spellCheck={false}
            disabled={inherit}
            placeholder={PLACEHOLDER[l.op] ?? ""}
            value={l.text}
            className={cn("h-8! pr-7 text-right text-xs! tabular-nums", message && "border-rose-500")}
            onChange={(e) => setText(l.id, e.target.value)}
            onBlur={() => tidy(l.id)}
          />
          {suffix && <span className="pointer-events-none absolute inset-y-0 right-2 flex items-center text-[11px] text-zinc-500">{suffix}</span>}
        </div>
        {opts.removable ? <IconButton size="sm" label={t("rates.combo.b.remove_line", { line: lineName })} icon={<X className="size-4" />} onClick={() => removeLine(l.id)} /> : <span aria-hidden />}
        {(message || opts.hint) && (
          <p id={message ? msgId : undefined} className={cn("col-span-2 text-xs sm:col-start-2 sm:col-end-5", message ? "font-medium text-rose-700" : "text-zinc-500")}>
            {message || opts.hint}
          </p>
        )}
      </div>
    )
  }

  const positions = shownChildPositions(draft)
  const childRows = positions.flatMap((pos) => {
    const lines = draft.childLines.filter((l) => l.position === pos)
    const base = childName(pos)
    const out = lines.map((l, i) => {
      const lineName = i === 0 ? base : t("rates.combo.b.line_n", { line: base, n: i + 1 })
      const lastAny = draft.children === "*" && pos === positions.length && pos > 1 && lines.length === 1
      return lineRow(l, i === 0 ? base : <span className="pl-3 text-zinc-500">{t("rates.combo.b.or_band")}</span>, lineName, { band: true, removable: i > 0 || lastAny })
    })
    if (!p.labels.bands.length || lines.length >= bandCodes.length + 1) return out
    return [
      ...out,
      <div key={`add-${pos}`} className="sm:pl-[9.5rem]">
        <Button size="sm" variant="link" className="text-xs" icon={<Plus className="size-3.5" />} onClick={() => addChildBand(pos)}>
          {t("rates.combo.b.add_band", { line: base })}
        </Button>
      </div>,
    ]
  })

  const adultPositions = Array.from({ length: draft.adults === "*" ? maxAdults : draft.adults }, (_, i) => i + 1)
  const adultRows = draft.adultLines.map((l) => {
    const lineName = t("rates.combo.b.adult_n", { n: l.position })
    const head = (
      <label className="inline-flex items-center gap-1.5">
        {t("rates.combo.b.adult")}
        <Select
          aria-label={t("rates.combo.b.adult_position")}
          value={String(l.position)}
          className="h-8! w-18! pr-7! pl-2! text-xs!"
          options={[...new Set([...adultPositions, l.position])].map((n) => ({ value: String(n), label: String(n) }))}
          onChange={(e) => editLine(l.id, (x) => ({ ...x, position: parseInt(e.target.value, 10) }))}
        />
      </label>
    )
    return lineRow(l, head, lineName, { removable: true })
  })

  const wholeHint = (l: BuilderLine) => {
    const v = readBuilderValue(l.text, l.op, p.minorUnits)
    if (v.kind !== "rule") return undefined
    if (v.op === "INHERIT") return t("rates.combo.b.whole_read.inherit")
    const rule = p.text.rule(v.op, v.value)
    const unit = unitWord(p.basis === "ROOM" ? "room" : "person")
    if (v.op === "ABSOLUTE" || v.op === "FIXED") return t("rates.combo.b.whole_read.fixed", { rule })
    if (v.op === "MULTIPLY" || v.op === "PERCENT_OF") return t("rates.combo.b.whole_read.replace", { rule, unit })
    return t("rates.combo.b.whole_read.adjust", { rule })
  }

  const chip = (c: ComboChip) => {
    const active = draft.adults === c.adults && draft.children === c.children
    const full = p.text.name(c.adults, c.children)
    const button = (
      <button
        type="button"
        aria-pressed={active}
        aria-disabled={!c.enabled || undefined}
        onClick={() => c.enabled && setCombination(c.adults, c.children)}
        className={cn(
          "h-7 rounded-md border px-2 text-xs font-medium tabular-nums focus-visible:ring-2 focus-visible:ring-tex-500 focus-visible:outline-none",
          active ? "border-tex-600 bg-tex-600 text-white" : c.enabled ? "border-zinc-300 bg-white text-zinc-800 hover:bg-zinc-50" : "cursor-not-allowed border-dashed border-zinc-300 bg-zinc-50 text-zinc-400",
        )}
      >
        {c.children ? t("rates.combo.b.chip", { adults: c.adults, children: c.children }) : t("rates.combo.b.chip_adults", { adults: c.adults })}
      </button>
    )
    const tip = c.enabled ? full : t("rates.combo.b.chip_off", { name: full, rooms: c.rooms.map(p.roomName).join(", ") })
    return (
      <Tooltip key={`${c.adults}+${c.children}`} content={tip}>
        {button}
      </Tooltip>
    )
  }

  const scopeField = (which: "rooms" | "periods") => {
    const all = which === "rooms" ? draft.roomsAll : draft.periodsAll
    const chosen = which === "rooms" ? draft.rooms : draft.periods
    const options =
      which === "rooms"
        ? p.tables.rooms.map((r) => str(r.room_type)).filter(Boolean).map((rt) => ({ value: rt, label: p.roomName(rt) }))
        : p.tables.periods
            .map((x) => ({ value: str(x.period_code), label: str(x.period_name) ? `${str(x.period_code)} · ${str(x.period_name)}` : str(x.period_code) }))
            .filter((x) => x.value)
    const legend = t(which === "rooms" ? "rates.occ.pop.rooms" : "rates.combo.b.periods")
    const chosenLabel = t(which === "rooms" ? "rates.occ.pop.rooms_chosen" : "rates.combo.b.periods_chosen")
    const set = (patch: Partial<BuilderDraft>) => change((d) => ({ ...d, ...patch }))
    return (
      <fieldset className="min-w-0 space-y-1.5">
        <legend className="mb-1 text-xs font-medium text-zinc-700">{legend}</legend>
        <Segmented<Scope>
          size="sm"
          label={legend}
          value={all ? "all" : "chosen"}
          onChange={(v) => set(which === "rooms" ? { roomsAll: v === "all" } : { periodsAll: v === "all" })}
          options={[
            { value: "all", label: t(which === "rooms" ? "rates.occ.ladder.all_rooms" : "rates.rates.all_periods") },
            ...(options.length ? [{ value: "chosen" as const, label: chosenLabel }] : []),
          ]}
        />
        {!all && (
          <div role="group" aria-label={chosenLabel} className="flex flex-wrap gap-x-3 gap-y-1">
            {options.map((o) => (
              <Checkbox
                key={o.value}
                label={o.label}
                checked={chosen.includes(o.value)}
                onChange={(e) => {
                  const on = e.target.checked
                  change((d) => {
                    const list = which === "rooms" ? d.rooms : d.periods
                    const next = on ? [...list, o.value] : list.filter((x) => x !== o.value)
                    return which === "rooms" ? { ...d, rooms: next } : { ...d, periods: next }
                  })
                }}
              />
            ))}
          </div>
        )}
      </fieldset>
    )
  }

  const counter = (which: "adults" | "children", min: number, max: number) => {
    const value = draft[which]
    const label = t(which === "adults" ? "rates.combo.b.adults" : "rates.combo.b.children")
    return (
      <label className="inline-flex items-center gap-1.5 text-xs font-medium text-zinc-700">
        {label}
        <Input
          ref={which === "adults" ? firstRef : undefined}
          type="number"
          inputMode="numeric"
          min={min}
          max={max}
          step={1}
          disabled={value === "*"}
          placeholder={value === "*" ? t("rates.combo.b.any") : undefined}
          value={value === "*" ? "" : String(value)}
          onChange={(e) => setCount(which, e.target.value, min, max)}
          className="h-8! w-16! text-sm tabular-nums"
        />
      </label>
    )
  }

  const title = p.editing ? t("rates.combo.b.title_edit", { name: p.text.name(p.editing.adults, p.editing.children) }) : t("rates.combo.b.title_new")
  return (
    <form
      role="group"
      aria-labelledby={titleId}
      className="space-y-3 rounded-lg border border-tex-300 bg-white p-3 shadow-sm"
      onSubmit={(e) => {
        e.preventDefault()
        save()
      }}
    >
      <h4 id={titleId} className="text-sm font-semibold text-zinc-900">
        {title}
      </h4>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {counter("adults", 1, maxAdults)}
        {counter("children", 0, maxChildren)}
        {chips.length > 0 && (
          <div role="group" aria-label={t("rates.combo.b.quick_label")} className="flex flex-wrap items-center gap-1">
            <span className="mr-0.5 text-xs text-zinc-500">{t("rates.combo.b.quick")}</span>
            {chips.map(chip)}
          </div>
        )}
      </div>
      {!hostable && <p className="text-xs font-medium text-amber-800">{t("rates.combo.b.no_host", { name })}</p>}

      <div className="grid gap-3 sm:grid-cols-2">
        {scopeField("rooms")}
        {scopeField("periods")}
      </div>

      <div className="space-y-1.5">
        {childRows}
        {draft.children === "*" && positions.length < MAX_CHILD_LINES && (
          <Button size="sm" variant="link" className="text-xs" icon={<Plus className="size-3.5" />} onClick={() => change((d) => ({ ...d, anyChildren: positions.length + 1 }))}>
            {t("rates.combo.b.add_child")}
          </Button>
        )}
        {adultRows}
        {draft.whole && lineRow(draft.whole, t("rates.combo.b.whole"), t("rates.combo.b.whole"), { removable: true, hint: wholeHint(draft.whole) })}
        <div className="flex flex-wrap gap-x-3">
          <Button size="sm" variant="link" className="text-xs" icon={<Plus className="size-3.5" />} onClick={addAdult}>
            {t("rates.combo.b.add_adult")}
          </Button>
          {!draft.whole && (
            <Button size="sm" variant="link" className="text-xs" icon={<Plus className="size-3.5" />} onClick={addWhole}>
              {t("rates.combo.b.add_whole")}
            </Button>
          )}
        </div>
        <p className="text-xs text-zinc-500">{t("rates.combo.b.value_hint", { unit: unitWord(guestUnit) })}</p>
      </div>

      <details className="text-xs text-zinc-700" open={moreOpen} onToggle={(e) => setMoreOpen(e.currentTarget.open)}>
        <summary className="cursor-pointer font-medium select-none">{t("rates.combo.b.more")}</summary>
        <div className="mt-2 space-y-1.5 pl-1">
          <Checkbox
            label={t("rates.combo.b.any_children")}
            checked={draft.children === "*"}
            onChange={(e) => {
              const on = e.target.checked
              change((d) => ({
                ...d,
                children: on ? "*" : Math.min(Math.max(1, d.anyChildren), Math.max(1, maxChildren)),
                anyChildren: Math.max(1, d.children === "*" ? d.anyChildren : d.children),
                adults: on && d.adults === "*" ? 2 : d.adults,
              }))
            }}
          />
          <Checkbox
            label={t("rates.combo.b.any_adults")}
            checked={draft.adults === "*"}
            onChange={(e) => {
              const on = e.target.checked
              change((d) => ({ ...d, adults: on ? "*" : 2, children: on && d.children === "*" ? Math.max(1, d.anyChildren) : d.children }))
            }}
          />
          <div className="space-y-0.5">
            <Checkbox label={t("rates.occ.pop.always_wins")} checked={draft.isOverride} onChange={(e) => change((d) => ({ ...d, isOverride: e.target.checked }))} />
            <p className="pl-6 text-zinc-500">{t("rates.combo.b.always_help")}</p>
          </div>
        </div>
      </details>

      <p className="text-xs text-zinc-500">{t("rates.combo.help")}</p>

      <div aria-live="polite" className="space-y-0.5 rounded-md bg-zinc-50 px-2.5 py-1.5">
        <p className="text-sm text-zinc-800">{t("rates.combo.b.reads", { text: reading })}</p>
        {secondary && <p className="text-xs text-zinc-500">{secondary}</p>}
        {single && <p className="text-xs text-zinc-600">{t("rates.combo.b.single_note")}</p>}
        {general.map((i) => (
          <p key={i.code} className={cn("text-xs", i.code === "NO_RULES" ? "text-zinc-600" : "font-medium text-rose-700")}>
            {issueText(i)}
          </p>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button variant="secondary" size="sm" onClick={p.onCancel}>
          {t("core.action.cancel")}
        </Button>
        <Button size="sm" type="submit" disabled={!plan.spec}>
          {t("rates.combo.b.save")}
        </Button>
      </div>
    </form>
  )
}
