import { Route, Routes } from "react-router-dom"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import { Card, EmptyState, PageHeader } from "../../ui"
import CrsPage from "./CrsPage"
import CallCenterPage from "./CallCenterPage"

/** Selling needs a price view somewhere and the right to create reservations. */
function Guard({ children }: { children: React.ReactNode }) {
  const { t } = useTexT()
  const { canAnywhere } = useSession()
  if (!canAnywhere("price.view") || !canAnywhere("reservation.create"))
    return (
      <>
        <PageHeader title={t("core.nav.crs")} />
        <Card>
          <EmptyState title={t("core.error.permission")} description={t("crs.page.no_access")} />
        </Card>
      </>
    )
  return <>{children}</>
}

/** Routes under /tex/crs (owned by this area). */
export default function AreaRoutes() {
  return (
    <Guard>
      <Routes>
        <Route index element={<CrsPage />} />
        <Route path="call-center" element={<CallCenterPage />} />
        <Route path="*" element={<CrsPage />} />
      </Routes>
    </Guard>
  )
}
