import type { ReactElement } from "react"
import { Navigate, Route, Routes } from "react-router-dom"
import { PlugZap } from "lucide-react"
import { useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import { Card, EmptyState } from "../../ui"
import { ConnectFrame } from "./ConnectFrame"
import Connections from "./Connections"
import OutboxMonitor from "./OutboxMonitor"
import ChannelDetail from "./channels/ChannelDetail"
import ChannelList from "./channels/ChannelList"

function NoAccess({ message }: { message: string }) {
  const { t } = useTexT()
  return (
    <ConnectFrame>
      <Card>
        <EmptyState icon={<PlugZap className="size-5" />} title={t("core.error.permission")} description={t(message)} />
      </Card>
    </ConnectFrame>
  )
}

/** Routes under /tex/connect (owned by this area). Connections and the delivery monitor
 * need connect.admin; channel distribution needs channel.view (every endpoint re-checks). */
export default function AreaRoutes() {
  const { can } = useSession()
  const admin = can("connect.admin")
  const channels = can("channel.view")
  if (!admin && !channels) return <NoAccess message="connect.no_access" />
  const adminOnly = (el: ReactElement) => (admin ? el : <NoAccess message="connect.no_access" />)
  const channelsOnly = (el: ReactElement) => (channels ? el : <NoAccess message="connect.channels.no_access" />)
  // a channel-only user landing on the area goes to the screens they may open
  const home = admin ? <Connections /> : <Navigate to="/tex/connect/channels" replace />
  return (
    <Routes>
      <Route index element={home} />
      <Route path="outbox" element={adminOnly(<OutboxMonitor />)} />
      <Route path="channels" element={channelsOnly(<ChannelList />)} />
      <Route path="channels/:name" element={channelsOnly(<ChannelDetail />)} />
      <Route path="*" element={home} />
    </Routes>
  )
}
