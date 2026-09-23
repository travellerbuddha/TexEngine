import { NavLink } from "react-router-dom"
import { cn } from "../../../lib/utils"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"

/** Secondary navigation inside /tex/inventory: room grid and limited extras
 * (links, not ARIA tabs: each entry is a page). */
export function InventoryNav() {
  const { t } = useTexT()
  const { can } = useSession()
  const items = [
    { to: "/tex/inventory", label: t("inventory.nav.rooms"), end: true, show: true },
    // the extras grid needs price.view (the backend checks it too)
    { to: "/tex/inventory/extras", label: t("inventory.nav.extras"), end: false, show: can("price.view") },
  ].filter((i) => i.show)
  if (items.length < 2) return null
  return (
    <nav aria-label={t("inventory.nav.label")} className="-mt-2 mb-5 flex gap-1 overflow-x-auto border-b border-zinc-200">
      {items.map((i) => (
        <NavLink
          key={i.to}
          to={i.to}
          end={i.end}
          className={({ isActive }) =>
            cn(
              "-mb-px border-b-2 px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors",
              isActive ? "border-tex-600 text-tex-700" : "border-transparent text-zinc-600 hover:text-zinc-900",
            )
          }
        >
          {i.label}
        </NavLink>
      ))}
    </nav>
  )
}
