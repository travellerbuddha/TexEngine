import { Link, useLocation } from "react-router-dom"
import { cn } from "../../../../lib/utils"
import { useTexT } from "../../../i18n"
import { POLICY_KINDS } from "../policies/config"

/** Sub-navigation of the Rates & Contracts area (R-35): contracts + selling policies. */
export function RatesNav() {
  const { t } = useTexT()
  const { pathname } = useLocation()
  const path = pathname.replace(/\/+$/, "")
  const items = [
    { to: "/tex/rates", label: t("rates.nav.contracts"), active: path.endsWith("/tex/rates") || path.includes("/tex/rates/contracts") },
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
