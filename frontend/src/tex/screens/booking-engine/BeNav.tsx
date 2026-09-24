import { NavLink } from "react-router-dom"
import { cn } from "../../../lib/utils"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"

/** Secondary navigation inside /tex/booking-engine (R-35, G-64): sites (configuration,
 * branding, widgets, domains and policies are tabs of a site), rooms, content, analytics.
 * Each entry only with the capabilities its screen's endpoints require. */
export function BeNav() {
  const { t } = useTexT()
  const { can } = useSession()
  const items = [
    { to: "/tex/booking-engine", label: t("core.nav.sub.sites"), end: true, show: can("price.view") },
    { to: "/tex/booking-engine/rooms", label: t("core.nav.sub.rooms"), show: can("booking_site.edit") },
    { to: "/tex/booking-engine/content", label: t("core.nav.sub.content"), show: can("booking_site.edit") },
    { to: "/tex/booking-engine/analytics", label: t("core.nav.sub.analytics"), show: can("report.view") },
  ].filter((i) => i.show)
  if (items.length < 2) return null
  return (
    <nav aria-label={t("be.nav.label")} className="-mt-2 mb-5 flex gap-1 overflow-x-auto border-b border-zinc-200">
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
