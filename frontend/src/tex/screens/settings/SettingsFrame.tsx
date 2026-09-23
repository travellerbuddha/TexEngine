import type { ReactNode } from "react"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import { PageHeader } from "../../ui"
import { SubNav, type SubNavItem } from "./components/common"

export interface SettingsAccess {
  users: boolean
  profiles: boolean
  tex: boolean
  audit: boolean
  markets: boolean
  /** System status (ADR-047): platform administrators, or system.monitor at some hotel */
  status: boolean
}

/** Which settings pages the user may open (the server re-checks every call). */
export function useSettingsAccess(): SettingsAccess {
  const { boot, canAnywhere } = useSession()
  const platform = boot.user.platform_admin
  const users = platform || canAnywhere("user.admin")
  const settingsAdmin = platform || canAnywhere("settings.admin")
  return {
    users,
    profiles: users || settingsAdmin,
    tex: platform,
    audit: settingsAdmin,
    markets: platform || canAnywhere("price.view"),
    status: platform || canAnywhere("system.monitor"),
  }
}

export function SettingsFrame({ subtitle, actions, children }: { subtitle?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  const { t } = useTexT()
  const access = useSettingsAccess()
  const items: SubNavItem[] = []
  if (access.users) items.push({ to: "/tex/settings/users", label: t("settings.nav.users") })
  if (access.profiles) items.push({ to: "/tex/settings/profiles", label: t("settings.nav.profiles") })
  if (access.markets) items.push({ to: "/tex/settings/markets", label: t("settings.nav.markets") })
  if (access.tex) items.push({ to: "/tex/settings/platform", label: t("settings.nav.tex") })
  if (access.audit) items.push({ to: "/tex/settings/audit", label: t("settings.nav.audit") })
  if (access.status) items.push({ to: "/tex/settings/status", label: t("settings.nav.status") })
  return (
    <>
      <PageHeader title={t("core.nav.settings")} subtitle={subtitle} actions={actions} />
      <SubNav label={t("settings.nav")} items={items} />
      {children}
    </>
  )
}
