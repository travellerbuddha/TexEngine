import { Link, useLocation } from "react-router-dom"
import { cn } from "../../../../lib/utils"
import { useTexT } from "../../../i18n"
import { RULE_SLUGS } from "../../../shell/nav"
import { InventoryNav } from "../../inventory/InventoryNav"
import { POLICY_KINDS } from "../policies/config"

/** In-page navigation of the pages under /tex/rates, by the area each page belongs to in the side
 * navigation (UX revision 2026-10): the selling rules show their sibling rules as tabs; the
 * restrictions list shows the rates & availability views; contracts (with their own view pills)
 * and promotions show none. One strip of twelve tabs that mixed daily work with set-up is gone;
 * every page is still reachable from the side navigation and the command palette. */
export function RatesNav() {
  const { t } = useTexT()
  const { pathname } = useLocation()
  const path = pathname.replace(/\/+$/, "")
  if (path.includes("/tex/rates/restrictions")) return <InventoryNav />
  const rules = [
    ...RULE_SLUGS.map((slug) => {
      const kind = POLICY_KINDS.find((k) => k.slug === slug)
      const to = `/tex/rates/policies/${slug}`
      return { to, label: t(kind?.navLabel ?? slug), active: path === to || path.startsWith(`${to}/`) }
    }),
    { to: "/tex/rates/fx-rates", label: t("rates.nav.fx_rates"), active: path.includes("/tex/rates/fx-rates") },
  ]
  if (!rules.some((r) => r.active)) return null
  return (
    <nav aria-label={t("rates.nav.label")} className="mb-4 overflow-x-auto border-b border-zinc-200">
      <ul className="flex min-w-max gap-1">
        {rules.map((it) => (
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
