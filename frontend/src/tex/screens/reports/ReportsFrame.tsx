import type { ReactNode } from "react"
import { useSearchParams } from "react-router-dom"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import { PageHeader } from "../../ui"
import { SubNav } from "../settings/components/common"
import { shared } from "./filters"

/** Page header + report switcher shared by every report page. Switching report keeps the
 * scope, dates and filters (they live in the URL). */
export function ReportsFrame({ subtitle, actions, children }: { subtitle?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  const { t } = useTexT()
  const { canAnywhere } = useSession()
  const [params] = useSearchParams()
  const q = shared(params)
  return (
    <>
      <PageHeader title={t("core.nav.reports")} subtitle={subtitle} actions={actions} />
      <SubNav
        label={t("reports.nav")}
        items={[
          { to: `/tex/reports${q}`, label: t("reports.nav.production"), end: true },
          ...(canAnywhere("price.view_cost") ? [{ to: `/tex/reports/margin${q}`, label: t("reports.nav.margin") }] : []),
          { to: `/tex/reports/promotions${q}`, label: t("reports.nav.promotion") },
          { to: `/tex/reports/extras${q}`, label: t("reports.nav.extras") },
          { to: `/tex/reports/cancellations${q}`, label: t("reports.nav.cancellation") },
          { to: `/tex/reports/payments${q}`, label: t("reports.nav.payment") },
          { to: `/tex/reports/conversion${q}`, label: t("reports.nav.conversion") },
          { to: "/tex/reports/pace", label: t("reports.nav.pace") },
        ]}
      />
      {children}
    </>
  )
}
