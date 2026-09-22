import { Route, Routes } from "react-router-dom"
import { BarChart3 } from "lucide-react"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import { Card, EmptyState, PageHeader } from "../../ui"
import ProductionReport from "./ProductionReport"
import PaceReport from "./PaceReport"

function NoAccess() {
  const { t } = useTexT()
  return (
    <>
      <PageHeader title={t("core.nav.reports")} />
      <Card>
        <EmptyState icon={<BarChart3 className="size-5" />} title={t("core.error.permission")} description={t("reports.no_access")} />
      </Card>
    </>
  )
}

/** Routes under /tex/reports (owned by this area). */
export default function AreaRoutes() {
  const { can } = useSession()
  if (!can("report.view")) return <NoAccess />
  return (
    <Routes>
      <Route index element={<ProductionReport />} />
      <Route path="pace" element={<PaceReport />} />
      <Route path="*" element={<ProductionReport />} />
    </Routes>
  )
}
