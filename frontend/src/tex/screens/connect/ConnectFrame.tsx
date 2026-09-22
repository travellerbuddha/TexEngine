import type { ReactNode } from "react"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import { PageHeader } from "../../ui"
import { SubNav } from "../settings/components/common"

export const CATEGORIES = ["PMS", "Channel Manager", "Payments", "FX", "Email", "SMS", "WhatsApp"] as const

export function categoryKey(c: string) {
  return `connect.cat.${c.toLowerCase().replace(/\s+/g, "_")}`
}

export function ConnectFrame({ actions, children }: { actions?: ReactNode; children: ReactNode }) {
  const { t } = useTexT()
  const { property } = useSession()
  return (
    <>
      <PageHeader title={t("core.nav.connect")} subtitle={t("connect.subtitle", { hotel: property?.property_name ?? "" })} actions={actions} />
      <SubNav
        label={t("connect.nav")}
        items={[
          { to: "/tex/connect", label: t("connect.nav.connections"), end: true },
          { to: "/tex/connect/outbox", label: t("connect.nav.outbox") },
        ]}
      />
      {children}
    </>
  )
}
