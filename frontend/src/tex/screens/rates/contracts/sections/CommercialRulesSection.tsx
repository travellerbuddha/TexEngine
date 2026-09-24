import { useTexT } from "../../../../i18n"
import { TabPanel, Tabs } from "../../../../ui"
import { IssueCount } from "../../components/common"
import type { VersionTable } from "../../lib/types"
import { countTableIssues } from "../../lib/util"
import { RULE_TABLES, type RuleTableId } from "../../workspace/sections.ts"
import { RatesTab } from "../tabs/RatesTab"
import { SettingsTab } from "../tabs/SettingsTab"
import type { TabProps } from "../tabs/shared"
import { AgeBandsTab, BoardsTab, OccupancyTab, PeriodsTab, RatePlansTab, RoomsTab } from "../tabs/TableTabs"

const LABEL: Record<RuleTableId, string> = {
  plans: "rates.tab.plans",
  settings: "rates.tab.settings",
  rooms: "rates.tab.rooms",
  periods: "rates.tab.periods",
  rates: "rates.tab.rates",
  ages: "rates.tab.ages",
  occupancy: "rates.tab.occupancy_rules",
  boards: "rates.tab.boards",
}

const ROWS: Partial<Record<RuleTableId, VersionTable>> = {
  plans: "rate_plans",
  rooms: "rooms",
  periods: "periods",
  rates: "period_rates",
  ages: "age_bands",
  occupancy: "occupancy_rules",
  boards: "boards",
}

/**
 * Commercial rules (PRICING_WORKSPACE_UX.md §2, D5): rate plans and settings, then the Advanced
 * rule tables: the ten-tab editor's own row editors, unchanged (weekdays, priorities, notes, raw
 * ops), so no capability is lost. Each inner tab counts its rows and the issues it lists.
 */
export function CommercialRulesSection({ table, onTable, ...props }: TabProps & { table: RuleTableId; onTable: (table: RuleTableId) => void }) {
  const { t } = useTexT()
  const tabs = RULE_TABLES.map((id) => {
    const c = countTableIssues(props.issues, id)
    const k = ROWS[id]
    const n = k ? props.state.tables[k].length : 0
    return {
      id,
      label: (
        <>
          {t(LABEL[id])}
          {n > 0 && <span className="text-xs font-normal text-zinc-500 tabular-nums">{n}</span>}
        </>
      ),
      badge: <IssueCount errors={c.errors} warnings={c.warnings} />,
    }
  })
  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-sm text-zinc-600">{t("rates.rules.intro")}</p>
      <Tabs tabs={tabs} value={table} onChange={(id) => onTable(id as RuleTableId)} label={t("rates.rules.tables")} />
      <TabPanel id={table}>
        {table === "plans" && <RatePlansTab {...props} />}
        {table === "settings" && <SettingsTab {...props} />}
        {table === "rooms" && <RoomsTab {...props} />}
        {table === "periods" && <PeriodsTab {...props} />}
        {table === "rates" && <RatesTab {...props} />}
        {table === "ages" && <AgeBandsTab {...props} />}
        {table === "occupancy" && <OccupancyTab {...props} />}
        {table === "boards" && <BoardsTab {...props} />}
      </TabPanel>
    </div>
  )
}
