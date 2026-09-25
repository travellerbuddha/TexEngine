// The special combination cards of the Pricing Workspace (PRICING_WORKSPACE_UX.md §3.7, D8, D13;
// slice S12), under the occupancy ladder. One card per group of occupancy.groupCombinations
// (the ladder's single-use row is not a special combination): "2 Adults + 2 Children → Child 1
// ×0.50 · Child 2 ×0.25" over its age bands by label, its rooms and its periods; ◆ when it holds
// for some periods only. Edit opens the structured builder in place of the card (a card the
// builder cannot show, e.g. one with a note, is edited in the rule tables); Remove deletes its
// rows. Every change is one workspace history entry with the undo toast. Each card carries
// `data-card` (its id) for the ladder's ⓘ note, "Show in grid" and issue anchoring.
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react"
import { AlertOctagon, AlertTriangle, Plus } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { useTexT } from "../../../i18n"
import { Badge, Button } from "../../../ui"
import type { Tables } from "../lib/tables"
import type { Issue } from "../lib/types"
import { UndoToastView } from "./BulkToolbar"
import { CombinationBuilder } from "./CombinationBuilder"
import { ALL_PERIODS, type Basis } from "./model.ts"
import {
  builderFromCard,
  groupCombinations,
  isSingleUseCard,
  newBuilderDraft,
  persistCombination,
  removeCombination,
  type BuilderDraft,
  type CapacityLike,
  type CardRule,
  type CombinationCard,
  type CombinationPlan,
} from "./occupancy.ts"
import { cardAnchorId, type AnchoredIssues } from "./issues.ts"
import { occRuleText } from "./OccupancyLadder"
import type { BandLabels } from "./useBandLabels"
import { useCellIssues } from "./useCellIssues"
import { useUndoToast, type WorkspaceHistory } from "./useWorkspaceHistory"

/** How combinations read (cards, the builder's reading line, the ladder's ⓘ notes). */
export interface ComboText {
  /** "2 Adults + 2 Children", "2 Adults + any children", "3 Adults" */
  name: (adults: number | null, children: number | null) => string
  /** "Child 1 ×0.50 · Child 2 ×0.25" */
  rules: (rules: readonly CardRule[]) => string
  /** the children's age bands by label: "Child 1: Child 7–11.99 · Child 2: any age" */
  bands: (rules: readonly CardRule[]) => string
  /** "All rooms · All periods", "Standard, Deluxe · P1, P2"; All with named ones: "All rooms + Standard" */
  scope: (rooms: readonly string[], periods: readonly string[]) => string
  /** one rule as a cell shows it: "×0.50", "−5%", "25.00", "inherit" */
  rule: (op: string, value: string) => string
}

export function useComboText(labels: BandLabels, minorUnits: number, roomName: (rt: string) => string): ComboText {
  const { t } = useTexT()
  return useMemo<ComboText>(() => {
    const rule = (op: string, value: string) => (op === "INHERIT" ? t("rates.ws.state.inherit_tag") : occRuleText(op, value, minorUnits))
    const ruleText = (r: CardRule) => rule(r.op, r.value)
    return {
      rule,
      name: (adults, children) => {
        const a = adults === null ? t("rates.combo.any_adults") : t("rates.combo.adults", { count: adults })
        if (children === 0) return a
        const c = children === null ? t("rates.combo.any_children") : t("rates.combo.children", { count: children })
        return t("rates.combo.name", { adults: a, children: c })
      },
      rules: (rules) =>
        rules
          .map((r) => {
            const rule = ruleText(r)
            if (r.target === "COMBINATION") return t("rates.combo.rule.whole", { rule })
            if (r.target === "ADULT") return r.position ? t("rates.combo.rule.adult", { n: r.position, rule }) : t("rates.combo.rule.adult_any", { rule })
            return r.position ? t("rates.combo.rule.child", { n: r.position, rule }) : t("rates.combo.rule.child_any", { rule })
          })
          .join(" · "),
      bands: (rules) =>
        rules
          .filter((r) => r.target === "CHILD")
          .map((r) => {
            const band = r.age_band ? labels.labelOf(r.age_band) : t("rates.combo.b.any_age")
            return r.position ? t("rates.combo.card.band", { n: r.position, band }) : t("rates.combo.card.band_any", { band })
          })
          .join(" · "),
      scope: (rooms, periods) => {
        // All and named ones together (groupCombinations keeps them apart; never hide the named ones)
        const list = (xs: readonly string[], all: string, allText: string, name: (x: string) => string) => {
          const named = xs.filter((x) => x !== all).map(name).join(", ")
          return !xs.length || xs.includes(all) ? (named ? `${allText} + ${named}` : allText) : named
        }
        return `${list(rooms, "", t("rates.occ.ladder.all_rooms"), roomName)} · ${list(periods, ALL_PERIODS, t("rates.rates.all_periods"), (x) => x)}`
      },
    }
  }, [t, labels, minorUnits, roomName])
}

type Open = { mode: "add" } | { mode: "edit"; id: string; draft: BuilderDraft } | null

export interface CombinationCardsProps {
  tables: Tables
  readOnly: boolean
  history: WorkspaceHistory
  /** groupCombinations(tables) */
  cards: readonly CombinationCard[]
  text: ComboText
  labels: BandLabels
  roomName: (rt: string) => string
  /** every contract room with its effective capacity (the server's, else the rows'), for the chips */
  capacities: readonly (CapacityLike & { room_type: string })[]
  /** the ladder's rooms scope ("" = all rooms): a new combination starts with it */
  scope: string
  basis: Basis
  extraUnit: string
  includedAdults: number
  /** the version's child_ordering (which child is child 1) */
  ordering: string
  minorUnits: number
  decimalMark: "." | ","
  ccy: string
  /** a card to bring into view and focus (the ladder's ⓘ note, Show in grid); `n` repeats a request */
  show?: { id: string; n: number } | null
  /** the validation issues anchored on cards (S15), their messages as shown, and whether they are
   * older than the state on screen */
  anchored?: AnchoredIssues
  issueText?: (issue: Issue) => string
  issuesStale?: boolean
}

/** The card element of an id (ids are JSON: compared, never put in a selector). */
function cardElement(root: HTMLElement | null, id: string): HTMLElement | null {
  if (!root) return null
  for (const el of root.querySelectorAll<HTMLElement>("[data-card]")) if (el.dataset.card === id) return el
  return null
}

export function CombinationCards(p: CombinationCardsProps) {
  const { tables, readOnly, history, text } = p
  const { t } = useTexT()
  const canEdit = !readOnly
  const titleId = useId()
  const rootRef = useRef<HTMLElement | null>(null)
  const addRef = useRef<HTMLButtonElement | null>(null)
  const cards = useMemo(() => p.cards.filter((c) => !isSingleUseCard(c)), [p.cards])
  const [open, setOpen] = useState<Open>(null)
  const [highlight, setHighlight] = useState<string | null>(null)
  const [announce, setAnnounce] = useState("")
  const say = useCallback((s: string) => setAnnounce((prev) => (prev === s ? `${s}​` : s)), [])
  const undoToast = useUndoToast(history)
  // the validation issues about a card's rules or its party (§3.15, S15)
  const issueAt = useCellIssues(p.anchored, p.issueText, p.issuesStale)

  // bring a card into view and focus it (after the render that shows it)
  const [focusReq, setFocusReq] = useState<{ id: string; n: number } | null>(null)
  const seq = useRef(0)
  const focusCard = useCallback((id: string) => {
    seq.current += 1
    setFocusReq({ id, n: seq.current })
  }, [])
  // only requests made while mounted (a remount after Discard does not replay the last one)
  const handled = useRef(p.show?.n ?? 0)
  useEffect(() => {
    if (!p.show || p.show.n === handled.current) return
    handled.current = p.show.n
    focusCard(p.show.id)
  }, [p.show, focusCard])
  useEffect(() => {
    if (!focusReq) return
    const el = cardElement(rootRef.current, focusReq.id)
    if (!el) return
    el.scrollIntoView({ block: "nearest" })
    el.focus({ preventScroll: true })
    setHighlight(focusReq.id)
    const timer = window.setTimeout(() => setHighlight((h) => (h === focusReq.id ? null : h)), 2000)
    return () => window.clearTimeout(timer)
  }, [focusReq])

  const nameOf = (c: Pick<CombinationCard, "adults" | "children">) => text.name(c.adults, c.children)

  const startAdd = () => {
    setOpen({ mode: "add" })
  }
  const startEdit = (card: CombinationCard) => {
    const draft = builderFromCard(card, { minorUnits: p.minorUnits, decimalMark: p.decimalMark })
    if (draft) setOpen({ mode: "edit", id: card.id, draft })
  }
  const closeBuilder = (back: string | null) => {
    setOpen(null)
    requestAnimationFrame(() => {
      if (back) {
        const el = cardElement(rootRef.current, back)
        ;(el?.querySelector<HTMLElement>("[data-card-edit]") ?? el)?.focus()
      } else addRef.current?.focus()
    })
  }

  const save = (plan: CombinationPlan) => {
    const spec = plan.spec
    if (!spec) return
    const name = text.name(spec.adults === "*" ? null : spec.adults, spec.children === "*" ? null : spec.children)
    const editing = open?.mode === "edit"
    // an edited card saved as it was: nothing to record
    if (open?.mode === "edit") {
      const before = cards.find((c) => c.id === open.id)
      const after = groupCombinations(persistCombination(history.current() ?? tables, spec).tables)
      if (before && after.some((c) => c.id === before.id && c.keys.length === before.keys.length)) return closeBuilder(before.id)
    }
    let added: string | null = null
    const done = history.apply(t(editing ? "rates.combo.h.edit" : "rates.combo.h.add", { name }), (tb) => {
      const res = persistCombination(tb, spec)
      added = res.tables.occupancy_rules.at(-1)?._key ?? null
      return res.tables
    })
    setOpen(null)
    const message = t("rates.combo.saved", { name })
    if (done) {
      undoToast.show(message)
      say(message)
    }
    // the saved card (a single-use combination lands in the ladder's first row instead)
    const now = history.current() ?? tables
    const card = added ? groupCombinations(now).find((c) => c.keys.includes(added as string)) : undefined
    if (card && !isSingleUseCard(card)) focusCard(card.id)
    else requestAnimationFrame(() => addRef.current?.focus())
  }

  const remove = (card: CombinationCard) => {
    const name = nameOf(card)
    const at = cards.findIndex((c) => c.id === card.id)
    if (!history.apply(t("rates.combo.h.remove", { name }), (tb) => removeCombination(tb, card).tables)) return
    if (open?.mode === "edit" && open.id === card.id) setOpen(null)
    const message = t("rates.combo.removed", { name })
    undoToast.show(message)
    say(message)
    // the focus goes to the next card's Edit, else the previous one's, else Add
    const next = cards[at + 1] ?? cards[at - 1]
    requestAnimationFrame(() => {
      const el = next ? cardElement(rootRef.current, next.id) : null
      ;(el?.querySelector<HTMLElement>("[data-card-edit]") ?? el ?? addRef.current)?.focus()
    })
  }

  const latest = useRef(undoToast)
  latest.current = undoToast
  const onToastUndo = useCallback(() => {
    const label = latest.current.undo()
    if (label) say(t("rates.ws.bulk.undone", { label }))
  }, [say, t])
  const onToastFocusBack = useCallback(() => addRef.current?.focus(), [])

  const builder = (initial: BuilderDraft, editing: CombinationCard | null) => (
    <CombinationBuilder
      key={editing?.id ?? "new"}
      initial={initial}
      editing={editing}
      tables={tables}
      current={() => history.current() ?? tables}
      cards={cards}
      text={text}
      labels={p.labels}
      roomName={p.roomName}
      capacities={p.capacities}
      basis={p.basis}
      extraUnit={p.extraUnit}
      includedAdults={p.includedAdults}
      ordering={p.ordering}
      minorUnits={p.minorUnits}
      decimalMark={p.decimalMark}
      ccy={p.ccy}
      onCancel={() => closeBuilder(editing?.id ?? null)}
      onSave={save}
    />
  )

  const newDraft = useMemo(
    () => newBuilderDraft(p.scope ? { roomsAll: false, rooms: [p.scope] } : {}),
    // a fresh draft each time Add is pressed
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [open?.mode === "add", p.scope],
  )
  const editingCard = open?.mode === "edit" ? cards.find((c) => c.id === open.id) : undefined

  return (
    <section ref={rootRef} aria-labelledby={titleId} className="space-y-2 pt-2">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={titleId} className="text-sm font-semibold text-zinc-900">
          {t("rates.combo.title")}
          {cards.length > 0 && <span className="ml-1.5 font-normal text-zinc-500">({cards.length})</span>}
        </h3>
        {canEdit && open?.mode !== "add" && (
          <Button ref={addRef} size="sm" variant="secondary" className="ml-auto" icon={<Plus className="size-4" />} onClick={startAdd}>
            {t("rates.combo.add")}
          </Button>
        )}
      </div>
      {/* the open builder says it itself */}
      {!open && <p className="text-xs text-zinc-500">{t("rates.combo.help")}</p>}
      <span role="status" aria-live="polite" className="sr-only">
        {announce}
      </span>

      {cards.length > 0 ? (
        <ul className="space-y-1.5">
          {cards.map((card) => {
            if (open?.mode === "edit" && open.id === card.id)
              return (
                <li key={card.id} data-card={card.id} data-combination={card.combination}>
                  {builder(open.draft, card)}
                </li>
              )
            const name = nameOf(card)
            const main = t("rates.combo.card.main", { name, rules: text.rules(card.rules) })
            const bands = text.bands(card.rules)
            const secondary = [bands, text.scope(card.rooms, card.periods)].filter(Boolean).join(" · ")
            const issue = issueAt(cardAnchorId(card.id))
            const IssueIcon = issue?.level === "ERROR" ? AlertOctagon : AlertTriangle
            const issueId = `${titleId}-issue-${cards.indexOf(card)}`
            return (
              <li
                key={card.id}
                data-card={card.id}
                data-combination={card.combination}
                data-issue={issue ? issue.level.toLowerCase() : undefined}
                tabIndex={-1}
                aria-label={t("rates.combo.card.label", { text: main, scope: secondary })}
                aria-describedby={issue ? issueId : undefined}
                className={cn(
                  "rounded-md border border-zinc-200 bg-white px-3 py-2 transition-shadow outline-none focus-visible:ring-2 focus-visible:ring-tex-500",
                  issue && (issue.level === "ERROR" ? "border-rose-300" : "border-amber-300"),
                  highlight === card.id && "ring-2 ring-sky-400",
                )}
              >
                <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-zinc-900">{main}</p>
                    <p className="text-xs text-zinc-500">{secondary}</p>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                    {card.periodScoped && <Badge tone="warning">◆ {t("rates.combo.card.by_period")}</Badge>}
                    {card.isOverride && <Badge tone="info">{t("rates.combo.card.always")}</Badge>}
                    {canEdit &&
                      (card.expressible ? (
                        <Button data-card-edit size="sm" variant="ghost" aria-label={t("rates.combo.card.edit", { name })} onClick={() => startEdit(card)}>
                          {t("core.action.edit")}
                        </Button>
                      ) : (
                        <a
                          data-card-edit
                          href="#rules/occupancy"
                          className="rounded-md px-2 py-1 text-xs font-medium text-tex-700 underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-tex-500 focus-visible:outline-none"
                          aria-describedby={`${titleId}-tables`}
                        >
                          {t("rates.combo.card.edit_tables")}
                        </a>
                      ))}
                    {canEdit && (
                      <Button size="sm" variant="ghost" className="text-rose-700! hover:bg-rose-50!" aria-label={t("rates.combo.card.remove", { name })} onClick={() => remove(card)}>
                        {t("rates.combo.card.remove_short")}
                      </Button>
                    )}
                  </div>
                </div>
                {issue && (
                  <p id={issueId} className={cn("mt-1 flex items-start gap-1 text-xs", issue.level === "ERROR" ? "text-rose-800" : "text-amber-900", issue.stale && "opacity-60")}>
                    <IssueIcon className="mt-px size-3.5 shrink-0" aria-hidden />
                    <span>{issue.text}</span>
                  </p>
                )}
              </li>
            )
          })}
        </ul>
      ) : (
        open?.mode !== "add" && <p className="text-xs text-zinc-500">{t("rates.combo.none")}</p>
      )}
      <span id={`${titleId}-tables`} hidden>
        {t("rates.combo.card.edit_tables_tip")}
      </span>

      {open?.mode === "add" && builder(newDraft, null)}
      {open?.mode === "edit" && !editingCard && builder(open.draft, null)}
      <UndoToastView toast={undoToast.toast} onUndo={onToastUndo} onDismiss={undoToast.dismiss} onHold={undoToast.hold} onFocusBack={onToastFocusBack} />
    </section>
  )
}
