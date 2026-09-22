import { Route, Routes } from "react-router-dom"
import { Placeholder } from "../Placeholder"

/** Routes under /tex/reservations (owned by this area). */
export default function AreaRoutes() {
  return (
    <Routes>
      <Route index element={<Placeholder title="core.nav.reservations" />} />
      <Route path="*" element={<Placeholder title="core.nav.reservations" />} />
    </Routes>
  )
}
