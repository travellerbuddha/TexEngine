import type { ReactNode } from "react"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import { PageHeader, type Crumb } from "../../ui"
import { SubNav } from "../settings/components/common"

export const CATEGORIES = ["PMS", "Channel Manager", "Payments", "FX", "Email", "SMS", "WhatsApp"] as const

export function categoryKey(c: string) {
  return `connect.cat.${c.toLowerCase().replace(/\s+/g, "_")}`
}

/** Connect area frame: one page header and the section links the user may open
 * (Connections and the delivery monitor need connect.admin, Channels channel.view). */
export function ConnectFrame({
  actions,
  children,
  title,
  subtitle,
  crumbs,
  meta,
}: {
  actions?: ReactNode
  children: ReactNode
  title?: ReactNode
  subtitle?: ReactNode
  crumbs?: Crumb[]
  meta?: ReactNode
}) {
  const { t } = useTexT()
  const { property, can } = useSession()
  const admin = can("connect.admin")
  return (
    <>
      <PageHeader
        title={title ?? t("core.nav.connect")}
        subtitle={subtitle ?? t("connect.subtitle", { hotel: property?.property_name ?? "" })}
        crumbs={crumbs}
        meta={meta}
        actions={actions}
      />
      <SubNav
        label={t("connect.nav")}
        items={[
          ...(admin
            ? [
                { to: "/tex/connect", label: t("connect.nav.connections"), end: true },
                { to: "/tex/connect/outbox", label: t("connect.nav.outbox") },
              ]
            : []),
          ...(can("channel.view") ? [{ to: "/tex/connect/channels", label: t("connect.nav.channels") }] : []),
        ]}
      />
      {children}
    </>
  )
}
