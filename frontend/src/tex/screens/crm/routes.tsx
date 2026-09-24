import { lazy } from "react"
import { Route, Routes } from "react-router-dom"
import { useTexT } from "../../i18n"
import { Card, EmptyState } from "../../ui"
import GuestList from "./GuestList"

const GuestProfile = lazy(() => import("./GuestProfile"))
const Segments = lazy(() => import("./Segments"))
const Abandoned = lazy(() => import("./Abandoned"))
const Programs = lazy(() => import("./loyalty/Programs"))
const ProgramPage = lazy(() => import("./loyalty/ProgramPage"))
const Communications = lazy(() => import("./Communications"))

function NotFound() {
  const { t } = useTexT()
  return (
    <Card>
      <EmptyState title={t("core.error.not_found")} />
    </Card>
  )
}

/** Routes under /tex/crm (owned by this area). */
export default function AreaRoutes() {
  return (
    <Routes>
      <Route index element={<GuestList />} />
      <Route path="guests/:name" element={<GuestProfile />} />
      <Route path="segments" element={<Segments />} />
      <Route path="abandoned" element={<Abandoned />} />
      <Route path="loyalty" element={<Programs />} />
      <Route path="loyalty/new" element={<ProgramPage />} />
      <Route path="loyalty/:name" element={<ProgramPage />} />
      <Route path="communications" element={<Communications />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}
