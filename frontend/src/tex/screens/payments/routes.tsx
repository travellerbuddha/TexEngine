import { lazy } from "react"
import { Route, Routes } from "react-router-dom"
import { useTexT } from "../../i18n"
import { Card, EmptyState } from "../../ui"
import Transactions from "./Transactions"

const TransactionDetail = lazy(() => import("./TransactionDetail"))
const Links = lazy(() => import("./Links"))
const Setup = lazy(() => import("./Setup"))

function NotFound() {
  const { t } = useTexT()
  return (
    <Card>
      <EmptyState title={t("core.error.not_found")} />
    </Card>
  )
}

/** Routes under /tex/payments (owned by this area). */
export default function AreaRoutes() {
  return (
    <Routes>
      <Route index element={<Transactions />} />
      <Route path="transactions/:name" element={<TransactionDetail />} />
      <Route path="links" element={<Links />} />
      <Route path="setup" element={<Setup />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}
