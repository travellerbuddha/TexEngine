import { Route, Routes } from "react-router-dom"
import { Placeholder } from "../Placeholder"

/** Routes under /tex/booking-engine (owned by this area). */
export default function AreaRoutes() {
  return (
    <Routes>
      <Route index element={<Placeholder title="core.nav.booking_engine" />} />
      <Route path="*" element={<Placeholder title="core.nav.booking_engine" />} />
    </Routes>
  )
}
