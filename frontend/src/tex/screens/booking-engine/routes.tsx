import { Route, Routes } from "react-router-dom"
import { Globe } from "lucide-react"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import { Card, EmptyState, PageHeader } from "../../ui"
import SitesList from "./SitesList"
import SiteEditor from "./SiteEditor"
import ContentTranslations from "./ContentTranslations"

function NoAccess() {
  const { t } = useTexT()
  return (
    <>
      <PageHeader title={t("core.nav.booking_engine")} />
      <Card>
        <EmptyState icon={<Globe className="size-5" />} title={t("core.error.permission")} description={t("be.no_access")} />
      </Card>
    </>
  )
}

/** Routes under /tex/booking-engine (owned by this area). */
export default function AreaRoutes() {
  const { canAnywhere } = useSession()
  // sites can serve other hotels than the selected one; the server checks each site
  if (!canAnywhere("booking_site.edit")) return <NoAccess />
  return (
    <Routes>
      <Route index element={<SitesList />} />
      <Route path="new" element={<SiteEditor key="new" isNew />} />
      <Route path="content" element={<ContentTranslations />} />
      <Route path=":name" element={<SiteEditor key="edit" />} />
      <Route path="*" element={<SitesList />} />
    </Routes>
  )
}
