// The "Occupancy & child pricing" region of Pricing (PRICING_WORKSPACE_UX.md §3.6.1, §3.11; slice
// S11): a collapsible section under the room price matrix. Its header holds the rooms scope (All
// rooms or one contract room; a dot marks scopes with rules of their own), which child counts as
// child 1, under ROOM basis the extra-adult unit and whether children fill empty included places,
// and "Child ages…" (the non-modal bands drawer, also opened by #ages). Collapsed, it reads as a
// one-line summary of the ladder; expanded, it shows the ladder (OccupancyLadder) and its resolved
// line, then the special combination cards and their builder (CombinationCards, S12; the ladder's
// ⓘ note links to them). Its open state is remembered per viewer (localStorage); a draft without occupancy rules
// opens it by default, and #occupancy opens it and scrolls to it. The version settings it edits
// are saved with Save (they are not table rows, so the undo history does not hold them).
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"
import { minorUnits as currencyMinorUnits } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Button, Notice, Select, Switch } from "../../../ui"
import type { TabProps } from "../contracts/tabs/shared"
import { CHILD_ORDERING, enumOptions, EXTRA_UNIT } from "../lib/options"
import type { RoomCapacity } from "../lib/types"
import { effectiveBands } from "./bands.ts"
import { ChildAgesDrawer } from "./ChildAgesDrawer"
import { CombinationCards, useComboText } from "./CombinationCards"
import { decimalMarkOf } from "./matrixView.ts"
import { baseRoomOf } from "./model.ts"
import {
  combinationNotes,
  defaultParty,
  fromInheritedRule,
  groupCombinations,
  isSingleUseCard,
  ladderModel,
  ladderSummary,
  partyOptions,
  policySource,
  scopesWithRules,
  type CombinationCard,
  type PartyOption,
  type SummaryItem,
} from "./occupancy.ts"
import { ladderCellId, OccupancyLadder, occRuleText } from "./OccupancyLadder"
import { int, str } from "./rows.ts"
import type { PricingRegion } from "./sections.ts"
import { useBandLabels } from "./useBandLabels"
import type { WorkspaceHistory } from "./useWorkspaceHistory"

const OPEN_KEY = "tex.rates.ws.occupancy_open"

/** What a "Show in grid" or issue request waits to show once the section is open (in its scope). */
type Showing = { key: string } | { card: string } | { row: string; period: string } | { section: true }

function readOpen(fallback: boolean): boolean {
  try {
    const s = window.localStorage.getItem(OPEN_KEY)
    return s === null ? fallback : s === "1"
  } catch {
    return fallback
  }
}

function storeOpen(open: boolean) {
  try {
    window.localStorage.setItem(OPEN_KEY, open ? "1" : "0")
  } catch {
    /* storage blocked: the choice lasts until reload */
  }
}

export function OccupancySection(props: TabProps & { history: WorkspaceHistory; region?: PricingRegion }) {
  const { doc, state, readOnly, preview, history, setSetting, region, setSampleParty } = props
  const { t, tOrdinal, locale } = useTexT()
  const tables = state.tables
  const settings = state.settings
  const basis = doc.contract_doc.pricing_basis
  const minorUnits = doc.contract_doc.minor_units ?? currencyMinorUnits(doc.contract_doc.contract_currency)
  const matrix = preview?.matrix
  const titleId = useId()
  const dotHint = useId()
  const sectionRef = useRef<HTMLElement>(null)

  // ─── open / closed, #occupancy and #ages ────────────────────────────────
  const [open, setOpenState] = useState(() => readOpen(tables.occupancy_rules.length === 0))
  const setOpen = (v: boolean) => {
    setOpenState(v)
    storeOpen(v)
  }
  const [drawer, setDrawer] = useState(false)
  useEffect(() => {
    if (region === "occupancy") {
      setOpenState(true)
      storeOpen(true)
      requestAnimationFrame(() => sectionRef.current?.scrollIntoView({ block: "start" }))
    } else if (region === "ages") setDrawer(true)
  }, [region])

  // ─── rooms, scope, capacity (the server's effective capacity, else the rows') ─────────
  const names = useMemo(() => new Map(doc.room_types.map((r) => [r.name, r.room_type_name || r.name])), [doc.room_types])
  const roomName = useCallback((rt: string) => names.get(rt) ?? rt, [names])
  const rooms = useMemo(() => tables.rooms.map((r) => str(r.room_type)).filter(Boolean), [tables.rooms])
  const [scopePick, setScope] = useState("")
  const scope = rooms.includes(scopePick) ? scopePick : ""
  const served = useMemo(() => new Map((matrix?.rooms ?? []).map((r) => [r.room_type, r.capacity])), [matrix])
  const capOf = (rt: string): RoomCapacity & { room_type: string } => {
    const cap = served.get(rt)
    if (cap) return { ...cap, room_type: rt }
    const row = tables.rooms.find((r) => str(r.room_type) === rt)
    const opt = doc.room_types.find((r) => r.name === rt)
    const max_adults = int(row?.max_adults) || opt?.adults_capacity || 2
    const max_children = int(row?.max_children) || opt?.children_capacity || 0
    return {
      room_type: rt,
      max_adults,
      max_children,
      max_occupants: int(row?.max_occupants) || opt?.max_total_occupants || max_adults + max_children,
      min_adults: int(row?.min_adults) || 1,
      included_adults: int(row?.included_adults) || opt?.base_occupancy || 2,
    }
  }
  const baseRoom = baseRoomOf(tables) ?? ""
  const maxAdults = scope ? capOf(scope).max_adults : rooms.reduce((m, rt) => Math.max(m, capOf(rt).max_adults), 2)
  const maxChildren = scope ? capOf(scope).max_children : rooms.reduce((m, rt) => Math.max(m, capOf(rt).max_children), 0)
  const includedAdults = basis === "ROOM" ? capOf(scope || baseRoom || rooms[0] || "").included_adults : 0

  // ─── bands, inherited rules, the ladder ─────────────────────────────────
  const bands = useMemo(() => effectiveBands(tables, matrix?.age_bands), [tables, matrix?.age_bands])
  const labels = useBandLabels(bands)
  const inherited = useMemo(() => (matrix?.inherited_rules ?? []).map(fromInheritedRule), [matrix?.inherited_rules])
  const extraUnit = str(settings.room_basis_extra_unit)
  const model = useMemo(
    () => ladderModel(tables, scope || null, basis, { maxAdults, includedAdults, bands, inherited, defaults: matrix?.occupancy_defaults ?? null, extraUnit }),
    [tables, scope, basis, maxAdults, includedAdults, bands, inherited, matrix?.occupancy_defaults, extraUnit],
  )
  const cards = useMemo(() => groupCombinations(tables), [tables])
  const comboText = useComboText(labels, minorUnits, roomName)
  const capacities = rooms.map((rt) => capOf(rt))
  const [showCard, setShowCard] = useState<{ id: string; n: number } | null>(null)
  const onShowCard = useCallback((id: string) => setShowCard((s) => ({ id, n: (s?.n ?? 0) + 1 })), [])
  const notes = useMemo(() => combinationNotes(model, cards, scope || null), [model, cards, scope])
  const summary = ladderSummary(model, cards)
  const withRules = useMemo(() => scopesWithRules(tables), [tables])

  // ─── "Show in grid" (S14): an occupancy rule's combination card, else its ladder cell; an issue
  // (S15): a ladder cell in a rooms scope, a combination card, the section or the child ages drawer
  const { show, onShown } = props
  const [showing, setShowing] = useState<Showing | null>(null)
  const [ladderFocus, setLadderFocus] = useState<{ cellId: string; n: number } | null>(null)
  const focusSeq = useRef(0)
  const cardOf = useCallback((key: string) => {
    const card = cards.find((c) => c.keys.includes(key))
    return card && !isSingleUseCard(card) ? card : null
  }, [cards])
  const openSection = () => {
    setOpenState(true)
    storeOpen(true)
  }
  useEffect(() => {
    if (!show) return
    const target = show.target
    if (target.kind === "occupancy") {
      const key = target.key
      onShown?.(show.n)
      const row = tables.occupancy_rules.find((r) => r._key === key)
      if (!row) return
      openSection()
      // a ladder rule is shown in its room's scope (All rooms for a rule of every room)
      if (!cardOf(key)) setScope(rooms.includes(str(row.room_type)) ? str(row.room_type) : "")
      setShowing({ key })
    } else if (target.kind === "ladder") {
      onShown?.(show.n)
      openSection()
      setScope(rooms.includes(target.scope) ? target.scope : "")
      setShowing({ row: target.row, period: target.period })
    } else if (target.kind === "card") {
      onShown?.(show.n)
      openSection()
      setShowing({ card: target.id })
    } else if (target.kind === "region" && target.region === "occupancy") {
      onShown?.(show.n)
      openSection()
      setShowing({ section: true })
    } else if (target.kind === "region" && target.region === "ages") {
      onShown?.(show.n)
      setDrawer(true)
    }
    // the request is handled once, by its number
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show])
  useEffect(() => {
    // after the render that opened the section in that scope
    if (!showing || !open) return
    setShowing(null)
    const focusCell = (row: string, period: string) => {
      focusSeq.current += 1
      setLadderFocus({ cellId: ladderCellId(row, period, scope), n: focusSeq.current })
    }
    if ("key" in showing) {
      const card = cardOf(showing.key)
      if (card) return onShowCard(card.id)
      for (const row of model.rows)
        for (const period of model.periods) if (row.cells[period]?.rule?._key === showing.key) return focusCell(row.id, period)
    } else if ("card" in showing) {
      if (cards.some((c) => c.id === showing.card)) return onShowCard(showing.card)
    } else if ("row" in showing) {
      if (model.rows.some((r) => r.id === showing.row) && model.periods.includes(showing.period)) return focusCell(showing.row, showing.period)
    }
    requestAnimationFrame(() => sectionRef.current?.scrollIntoView({ block: "start" }))
  }, [showing, open, model, cardOf, onShowCard, scope, cards])

  // ─── the resolved line's sample party (price_matrix parties, GAP-2b) ─────
  const partyRoom = scope || baseRoom || rooms[0] || ""
  const partyCap = partyRoom ? capOf(partyRoom) : null
  const parties = useMemo(
    () => (partyCap ? partyOptions(partyCap, bands) : []),
    // the capacity numbers, not the object
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [partyCap?.max_adults, partyCap?.max_children, partyCap?.max_occupants, partyCap?.min_adults, partyRoom, bands],
  )
  const [partyPick, setPartyPick] = useState<string | null>(null)
  const party = parties.find((x) => x.id === partyPick) ?? defaultParty(parties)
  const asking = open && party && partyRoom && preview && preview.mode !== "catalogue" ? { room: partyRoom, parties: [{ adults: party.adults, children: party.children }] } : null
  const askingKey = asking ? JSON.stringify(asking) : ""
  useEffect(() => {
    setSampleParty?.(asking)
    // the request's content is its key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [askingKey, setSampleParty])
  // leaving Pricing (or the editor) stops asking for the party: later matrix calls go without it
  useEffect(() => () => setSampleParty?.(null), [setSampleParty])

  // ─── words ─────────────────────────────────────────────────────────────
  const partyName = (x: PartyOption) => {
    const adults = t("rates.occ.party.adults", { count: x.adults })
    if (!x.children.length) return adults
    return t("rates.occ.party.with_children", { adults, children: t("rates.occ.party.children", { count: x.children.length, bands: x.children.map(labels.labelOf).join(", ") }) })
  }
  const cardName = (c: CombinationCard) => comboText.name(c.adults, c.children)
  const itemName = (x: SummaryItem) => {
    switch (x.kind) {
      case "single":
        return t("rates.occ.sum.single")
      case "adult":
        return tOrdinal("rates.occ.sum.adult", x.position)
      case "adult_any":
        return t("rates.occ.ladder.row.adult_any")
      case "band":
        return x.unknownBand ? x.band : labels.labelOf(x.band)
      case "child":
        return x.band ? t("rates.occ.ladder.row.child_n", { n: x.position, band: x.unknownBand ? x.band : labels.labelOf(x.band) }) : t("rates.occ.ladder.row.child_n_any", { n: x.position })
      default:
        return t("rates.occ.ladder.row.child_any")
    }
  }
  const itemText = (x: SummaryItem) => `${itemName(x)} ${occRuleText(x.op, x.value, minorUnits)}`
  const summaryParts = [
    summary.adults.length ? t("rates.occ.sum.adults", { items: summary.adults.map(itemText).join(" · ") }) : "",
    summary.children.length ? t("rates.occ.sum.children", { items: summary.children.map(itemText).join(" · ") }) : "",
    [summary.combinations ? t("rates.occ.sum.combinations", { count: summary.combinations }) : "", summary.periodOverrides ? t("rates.occ.sum.overrides", { count: summary.periodOverrides }) : ""]
      .filter(Boolean)
      .join(" · "),
  ].filter(Boolean)
  const dotted = (rt: string, label: string) => (withRules.has(rt) ? t("rates.occ.ladder.scope_has_rules", { room: label }) : label)
  const bandSource = !tables.age_bands.length && matrix?.age_bands?.length ? policySource(matrix.age_bands[0].source) : null

  return (
    <section ref={sectionRef} id="occupancy" aria-labelledby={titleId} className="scroll-mt-44 space-y-2 border-t border-zinc-200 pt-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <h2 id={titleId} className="text-base font-semibold text-zinc-900">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={`${titleId}-body`}
            onClick={() => setOpen(!open)}
            className="inline-flex items-center gap-1 rounded-md px-1 py-0.5 -ml-1 hover:bg-zinc-100 focus-visible:ring-2 focus-visible:ring-tex-500 focus-visible:outline-none"
          >
            {open ? <ChevronDown className="size-4" aria-hidden /> : <ChevronRight className="size-4" aria-hidden />}
            {t("rates.occ.ladder.title")}
          </button>
        </h2>
        <label className="inline-flex items-center gap-1.5 text-xs text-zinc-600">
          {t("rates.occ.ladder.rooms")}
          <Select
            aria-describedby={dotHint}
            value={scope}
            className="h-8! w-auto! max-w-56 text-xs!"
            options={[{ value: "", label: dotted("", t("rates.occ.ladder.all_rooms")) }, ...rooms.map((rt) => ({ value: rt, label: dotted(rt, roomName(rt)) }))]}
            onChange={(e) => setScope(e.target.value)}
          />
          <span id={dotHint} className="sr-only">
            {t("rates.occ.ladder.scope_dot_hint")}
          </span>
        </label>
        <label className="inline-flex items-center gap-1.5 text-xs text-zinc-600">
          {t("rates.occ.ladder.child_order")}
          <Select
            disabled={readOnly}
            value={str(settings.child_ordering)}
            className="h-8! w-auto! text-xs!"
            options={enumOptions(t, "child_ordering", CHILD_ORDERING)}
            onChange={(e) => setSetting("child_ordering", e.target.value)}
          />
        </label>
        {basis === "ROOM" && (
          <>
            <label className="inline-flex items-center gap-1.5 text-xs text-zinc-600">
              {t("rates.occ.ladder.extra_unit")}
              <Select
                disabled={readOnly}
                value={extraUnit || "PER_PERSON_SHARE"}
                className="h-8! w-auto! text-xs!"
                options={enumOptions(t, "extra_unit", EXTRA_UNIT)}
                onChange={(e) => setSetting("room_basis_extra_unit", e.target.value)}
              />
            </label>
            <div className="text-xs">
              <Switch
                disabled={readOnly}
                checked={Boolean(settings.room_basis_children_fill_included)}
                onChange={(v) => setSetting("room_basis_children_fill_included", v ? 1 : 0)}
                label={<span className="text-xs font-normal text-zinc-600">{t("rates.occ.ladder.children_fill")}</span>}
              />
            </div>
          </>
        )}
        <Button size="sm" variant="secondary" className="ml-auto" aria-haspopup="dialog" aria-expanded={drawer} onClick={() => setDrawer(true)}>
          {t("rates.occ.ladder.child_ages")}
        </Button>
      </div>

      <div id={`${titleId}-body`}>
        {!open ? (
          <p className="text-xs text-zinc-600">{summaryParts.length ? summaryParts.join(" | ") : t("rates.occ.sum.none")}</p>
        ) : (
          <div className="space-y-2">
            {!bands.length && <Notice tone="info">{t("rates.occ.ladder.no_bands")}</Notice>}
            {bandSource && <p className="text-xs text-zinc-500">{t("rates.occ.ladder.inherited_bands", { source: t(`rates.occ.ladder.source.${bandSource.scope.replace("+", "_")}`) })}</p>}
            <OccupancyLadder
              // a version loaded again (Discard) or another rooms scope starts the grid afresh:
              // no edit in progress, no error drafts, no selection
              key={`${props.epoch ?? 0}:${scope}`}
              doc={doc}
              tables={tables}
              readOnly={readOnly}
              history={history}
              preview={preview}
              model={model}
              cards={cards}
              notes={notes}
              scope={scope}
              basis={basis}
              labels={labels}
              roomName={roomName}
              partyRoom={partyRoom}
              party={party}
              parties={parties}
              onParty={setPartyPick}
              cardName={cardName}
              partyName={partyName}
              onShowCard={onShowCard}
              focus={ladderFocus}
              anchored={props.anchored}
              issueText={props.issueText}
              issuesStale={props.issuesStale}
              maxChildren={maxChildren}
            />
            <CombinationCards
              key={`combos:${props.epoch ?? 0}`}
              tables={tables}
              readOnly={readOnly}
              history={history}
              cards={cards}
              text={comboText}
              labels={labels}
              roomName={roomName}
              capacities={capacities}
              scope={scope}
              basis={basis}
              extraUnit={extraUnit}
              includedAdults={model.includedAdults || includedAdults}
              ordering={str(settings.child_ordering)}
              minorUnits={minorUnits}
              decimalMark={decimalMarkOf(locale)}
              ccy={doc.contract_doc.contract_currency}
              show={showCard}
              anchored={props.anchored}
              issueText={props.issueText}
              issuesStale={props.issuesStale}
            />
          </div>
        )}
      </div>

      <ChildAgesDrawer
        key={props.epoch ?? 0}
        open={drawer}
        onClose={() => setDrawer(false)}
        state={state}
        readOnly={readOnly}
        history={history}
        labels={labels}
        served={matrix?.age_bands}
        setSetting={setSetting}
      />
    </section>
  )
}
