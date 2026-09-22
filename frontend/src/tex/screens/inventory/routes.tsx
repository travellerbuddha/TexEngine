import { Navigate, Route, Routes } from "react-router-dom"
import AriGrid from "./AriGrid"

/** Routes under /tex/inventory (rates & availability grid, workstream A). */
export default function AreaRoutes() {
  return (
    <Routes>
      <Route index element={<AriGrid />} />
      <Route path="*" element={<Navigate to="/tex/inventory" replace />} />
    </Routes>
  )
}
