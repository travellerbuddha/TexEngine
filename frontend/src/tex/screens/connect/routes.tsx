import { Route, Routes } from "react-router-dom"
import { PlugZap } from "lucide-react"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import { Card, EmptyState, PageHeader } from "../../ui"
import Connections from "./Connections"
import OutboxMonitor from "./OutboxMonitor"

function NoAccess() {
  const { t } = useTexT()
  return (
    <>
      <PageHeader title={t("core.nav.connect")} />
      <Card>
        <EmptyState icon={<PlugZap className="size-5" />} title={t("core.error.permission")} description={t("connect.no_access")} />
      </Card>
    </>
  )
}

/** Routes under /tex/connect (owned by this area). */
export default function AreaRoutes() {
  const { can } = useSession()
  if (!can("connect.admin")) return <NoAccess />
  return (
    <Routes>
      <Route index element={<Connections />} />
      <Route path="outbox" element={<OutboxMonitor />} />
      <Route path="*" element={<Connections />} />
    </Routes>
  )
}
