import type { ReactNode } from "react"
import { useTexT } from "../../i18n"
import { PageHeader } from "../../ui"
import { SubNav } from "../settings/components/common"

/** Page header + report switcher shared by every report page. */
export function ReportsFrame({ subtitle, actions, children }: { subtitle?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  const { t } = useTexT()
  return (
    <>
      <PageHeader title={t("core.nav.reports")} subtitle={subtitle} actions={actions} />
      <SubNav
        label={t("reports.nav")}
        items={[
          { to: "/tex/reports", label: t("reports.nav.production"), end: true },
          { to: "/tex/reports/pace", label: t("reports.nav.pace") },
        ]}
      />
      {children}
    </>
  )
}
