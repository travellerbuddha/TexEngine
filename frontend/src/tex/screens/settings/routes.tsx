import { Navigate, Route, Routes } from "react-router-dom"
import { Lock } from "lucide-react"
import { useTexT } from "../../i18n"
import { Card, EmptyState } from "../../ui"
import { SettingsFrame, useSettingsAccess } from "./SettingsFrame"
import UsersAccess from "./UsersAccess"
import Profiles from "./Profiles"
import TexSettings from "./TexSettings"
import AuditTrail from "./AuditTrail"
import Markets from "./Markets"
import SystemStatus from "./SystemStatus"

function Denied({ platform }: { platform?: boolean }) {
  const { t } = useTexT()
  return (
    <SettingsFrame>
      <Card>
        <EmptyState icon={<Lock className="size-5" />} title={t("core.error.permission")} description={t(platform ? "settings.denied_platform" : "settings.denied")} />
      </Card>
    </SettingsFrame>
  )
}

/** Routes under /tex/settings (owned by this area). */
export default function AreaRoutes() {
  const access = useSettingsAccess()
  const first = access.users
    ? "users"
    : access.profiles
      ? "profiles"
      : access.markets
        ? "markets"
        : access.audit
          ? "audit"
          : access.status
            ? "status"
            : null
  return (
    <Routes>
      <Route index element={first ? <Navigate to={first} replace /> : <Denied />} />
      <Route path="users" element={access.users ? <UsersAccess /> : <Denied />} />
      <Route path="profiles" element={access.profiles ? <Profiles /> : <Denied />} />
      <Route path="markets" element={access.markets ? <Markets /> : <Denied />} />
      <Route path="platform" element={access.tex ? <TexSettings /> : <Denied platform />} />
      <Route path="audit" element={access.audit ? <AuditTrail /> : <Denied />} />
      <Route path="status" element={access.status ? <SystemStatus /> : <Denied />} />
      <Route path="*" element={first ? <Navigate to={`/tex/settings/${first}`} replace /> : <Denied />} />
    </Routes>
  )
}
