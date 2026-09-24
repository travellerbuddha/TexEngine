import { NavLink } from "react-router-dom"
import { cn } from "../../../../lib/utils"
import { useSession } from "../../../lib/session"
import { useTexT } from "../../../i18n"
import type { VersionState } from "./types"
import { Badge, type Tone } from "../../../ui"

/** Views of contract content across contracts (R-35, G-64): contracts, their versions and the
 * tables of versions. Periods and occupancy rules are cost (price.view_cost or contract.edit). */
export function ContractViews() {
  const { t } = useTexT()
  const { can } = useSession()
  const cost = can("price.view_cost") || can("contract.edit")
  const items = [
    { to: "/tex/rates", label: t("core.nav.sub.contracts"), end: true },
    { to: "/tex/rates/versions", label: t("core.nav.sub.versions") },
    ...(cost
      ? [
          { to: "/tex/rates/periods", label: t("core.nav.sub.periods") },
          { to: "/tex/rates/occupancy", label: t("core.nav.sub.occupancy") },
        ]
      : []),
    { to: "/tex/rates/rate-plans", label: t("core.nav.sub.rate_plans") },
  ]
  return (
    <nav aria-label={t("rates.lists.views")} className="mb-4 flex gap-1 overflow-x-auto">
      {items.map((i) => (
        <NavLink
          key={i.to}
          to={i.to}
          end={i.end}
          className={({ isActive }) =>
            cn(
              "shrink-0 rounded-full border px-3 py-1 text-sm font-medium whitespace-nowrap transition-colors",
              isActive ? "border-tex-600 bg-tex-50 text-tex-800" : "border-zinc-200 bg-white text-zinc-600 hover:border-zinc-300 hover:text-zinc-900",
            )
          }
        >
          {i.label}
        </NavLink>
      ))}
    </nav>
  )
}

const STATE_TONE: Record<VersionState, Tone> = {
  live: "success",
  scheduled: "info",
  published: "neutral",
  draft: "warning",
  superseded: "neutral",
  withdrawn: "danger",
}

/** A version's selling state as text + tone (never colour alone). */
export function VersionStateBadge({ state }: { state: VersionState }) {
  const { t } = useTexT()
  return <Badge tone={STATE_TONE[state] ?? "neutral"}>{t(`rates.lists.state.${state}`)}</Badge>
}
