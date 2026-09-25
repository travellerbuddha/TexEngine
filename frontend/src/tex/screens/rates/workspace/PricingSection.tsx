import type { ReactNode } from "react"
import { useTexT } from "../../../i18n"
import { Badge, Notice } from "../../../ui"
import { RatesTab } from "../contracts/tabs/RatesTab"
import { contractRoomOptions, TabIntro, type TabProps } from "../contracts/tabs/shared"
import { enumLabel } from "../lib/options"
import { BoardsSection, usePeriodChannel } from "./BoardsSection"
import { OccupancySection } from "./OccupancySection"
import { PriceMatrix } from "./PriceMatrix"
import type { PricingRegion } from "./sections.ts"

/**
 * The Pricing section (PRICING_WORKSPACE_UX.md §2, §3): the price model where it is read and
 * entered. The room price matrix (S9) is edited inline and priced live by the server; under it,
 * Occupancy & child pricing (S11) with the child ages drawer, then Boards (S13), whose grid
 * highlights the matrix's active period (#occupancy, #ages and #boards open them). A viewer without
 * cost (an agent's catalogue) sees what sells, without amounts and without any cost call; the
 * matrix is not rendered for it. The Advanced "Room prices" and "Boards" tables stay under
 * Commercial rules.
 */
export function PricingSection(props: TabProps & { region?: PricingRegion }) {
  // the matrix's active period reaches the boards grid only (no re-render of the rest of Pricing)
  const matrixPeriod = usePeriodChannel()
  if (props.preview?.mode === "catalogue") return <CatalogueView {...props} />
  if (!props.history) return <RatesTab {...props} />
  return (
    <div className="space-y-6">
      <PriceMatrix key={props.epoch ?? 0} {...props} history={props.history} onActivePeriod={matrixPeriod.set} />
      <OccupancySection {...props} history={props.history} region={props.region} />
      <BoardsSection key={`boards:${props.epoch ?? 0}`} {...props} history={props.history} region={props.region} matrixPeriod={matrixPeriod} />
    </div>
  )
}

function CatalogueView({ doc, state }: TabProps) {
  const { t } = useTexT()
  const rooms = contractRoomOptions(doc, state)
  const boards = Array.from(new Set(state.tables.boards.map((b) => String(b.board || "")).filter(Boolean)))
  const plans = state.tables.rate_plans.filter((r) => r.rate_plan)
  return (
    <div className="space-y-4">
      <TabIntro title={t("rates.section.pricing")} />
      <Notice tone="info">{t("rates.ws.catalogue.no_amounts")}</Notice>
      <div className="grid gap-4 md:grid-cols-3">
        <CatalogueList id="cat-rooms" title={t("rates.tab.rooms")} empty={t("rates.common.no_rows")}>
          {rooms.map((r) => (
            <li key={r.value}>{r.label}</li>
          ))}
        </CatalogueList>
        <CatalogueList id="cat-boards" title={t("rates.tab.boards")} empty={t("rates.common.no_rows")}>
          {boards.map((b) => (
            <li key={b}>
              {enumLabel(t, "board", b)} <span className="font-mono text-xs text-zinc-500">{b}</span>
            </li>
          ))}
        </CatalogueList>
        <CatalogueList id="cat-plans" title={t("rates.tab.plans")} empty={t("rates.preview.no_plans")}>
          {plans.map((r) => {
            const id = String(r.rate_plan)
            return (
              <li key={r._key} className="flex flex-wrap items-center gap-2">
                {doc.rate_plan_options.find((o) => o.name === id)?.rate_plan_name ?? id}
                <Badge tone={r.refundable ? "success" : "warning"}>{r.refundable ? t("rates.f.refundable") : t("rates.plans.non_refundable")}</Badge>
              </li>
            )
          })}
        </CatalogueList>
      </div>
    </div>
  )
}

function CatalogueList({ id, title, empty, children }: { id: string; title: string; empty: string; children: ReactNode[] }) {
  return (
    <section aria-labelledby={id} className="rounded-lg border border-zinc-200 p-3">
      <h3 id={id} className="mb-2 text-sm font-semibold text-zinc-900">
        {title}
      </h3>
      {children.length ? <ul className="space-y-1 text-sm text-zinc-800">{children}</ul> : <p className="text-sm text-zinc-500">{empty}</p>}
    </section>
  )
}
