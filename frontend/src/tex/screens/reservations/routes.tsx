import { Route, Routes } from "react-router-dom"
import BookingDetail from "./BookingDetail"
import ReservationDetail from "./ReservationDetail"
import ReservationList from "./ReservationList"

/** Routes under /tex/reservations (owned by this area). */
export default function AreaRoutes() {
  return (
    <Routes>
      <Route index element={<ReservationList />} />
      <Route path="booking/:name" element={<BookingDetail />} />
      <Route path=":name" element={<ReservationDetail />} />
    </Routes>
  )
}
