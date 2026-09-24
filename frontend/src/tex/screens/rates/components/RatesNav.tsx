import { Link, useLocation } from "react-router-dom"
import { cn } from "../../../../lib/utils"
import { useSession } from "../../../lib/session"
import { useTexT } from "../../../i18n"
import { POLICY_KINDS } from "../policies/config"

/** Sub-navigation of the Rates & Contracts area (R-35): contracts (and their versions and
 * tables, G-64), restrictions, selling policies. */
export function RatesNav() {
  const { t } = useTexT()
  const { can } = useSession()
  const { pathname } = useLocation()
  const path = pathname.replace(/\/+$/, "")
  // contracts, their versions and the tables of versions are one section (ContractViews)
  const contractViews = ["/tex/rates/contracts", "/tex/rates/versions", "/tex/rates/periods", "/tex/rates/occupancy", "/tex/rates/rate-plans"]
  const items = [
    { to: "/tex/rates", label: t("rates.nav.contracts"), active: path.endsWith("/tex/rates") || contractViews.some((v) => path.includes(v)) },
    // the restrictions list needs price.view, as the grid (the navigation's rule, nav.ts)
    ...(can("price.view") ? [{ to: "/tex/rates/restrictions", label: t("core.nav.sub.restrictions"), active: path.includes("/tex/rates/restrictions") }] : []),
    ...POLICY_KINDS.map((k) => {
      const to = `/tex/rates/policies/${k.slug}`
      return { to, label: t(k.navLabel), active: path.includes(to) }
    }),
    { to: "/tex/rates/fx-rates", label: t("rates.nav.fx_rates"), active: path.includes("/tex/rates/fx-rates") },
  ]
  return (
    <nav aria-label={t("rates.nav.label")} className="mb-4 overflow-x-auto border-b border-zinc-200">
      <ul className="flex min-w-max gap-1">
        {items.map((it) => (
          <li key={it.to}>
            <Link
              to={it.to}
              aria-current={it.active ? "page" : undefined}
              className={cn(
                "-mb-px inline-flex items-center border-b-2 px-2.5 py-2 text-sm font-medium whitespace-nowrap transition-colors",
                it.active ? "border-tex-600 text-tex-700" : "border-transparent text-zinc-600 hover:text-zinc-900",
              )}
            >
              {it.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}
