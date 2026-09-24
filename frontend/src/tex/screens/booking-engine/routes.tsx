import { Navigate, Route, Routes, useLocation, useParams } from "react-router-dom"
import { Globe } from "lucide-react"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import { Card, EmptyState, PageHeader } from "../../ui"
import SitesList from "./SitesList"
import SiteEditor from "./SiteEditor"
import ContentTranslations from "./ContentTranslations"
import Rooms from "./Rooms"
import Analytics from "./Analytics"

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

/** A link from before sites moved under /sites (G-64 review M3): /tex/booking-engine/<site>. */
function OldSiteLink() {
  const { name = "" } = useParams()
  const { search, hash } = useLocation()
  return <Navigate to={`/tex/booking-engine/sites/${encodeURIComponent(name)}${search}${hash}`} replace />
}

/** Routes under /tex/booking-engine (owned by this area). A site opens at sites/<name>, whatever
 * its name: before, /tex/booking-engine/<name> opened the area's own page for a site named
 * "rooms", "analytics", "content" or "new". Those names are refused for new sites (and patch p47
 * reports older ones), so an old link to any other site still lands on it. */
export default function AreaRoutes() {
  const { canAnywhere } = useSession()
  // sites can serve other hotels than the selected one; the server checks each site
  if (!canAnywhere("booking_site.edit")) return <NoAccess />
  return (
    <Routes>
      <Route index element={<SitesList />} />
      <Route path="new" element={<SiteEditor key="new" isNew />} />
      <Route path="sites" element={<Navigate to="/tex/booking-engine" replace />} />
      <Route path="sites/:name" element={<SiteEditor key="edit" />} />
      <Route path="content" element={<ContentTranslations />} />
      <Route path="rooms" element={<Rooms />} />
      <Route path="analytics" element={<Analytics />} />
      <Route path=":name" element={<OldSiteLink />} />
      <Route path="*" element={<SitesList />} />
    </Routes>
  )
}
