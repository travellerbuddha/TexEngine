import { Route, Routes } from "react-router-dom"

/** Guest booking engine routes: /book/:site, /book/:site/confirmation/:booking,
 * /book/:site/manage, /book/pay/:token, /book/pay/mock/:txn. */
export default function BookingApp() {
  return (
    <Routes>
      <Route path="*" element={<main className="p-8 text-center text-sm text-zinc-600">TEX Booking</main>} />
    </Routes>
  )
}
