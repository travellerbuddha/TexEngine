import { Navigate, Route, Routes } from "react-router-dom"
import { Card, EmptyState } from "../../ui"
import { useTexT } from "../../i18n"
import ContractsList from "./contracts/ContractsList"
import ContractDetail from "./contracts/ContractDetail"
import VersionEditor from "./contracts/VersionEditor"
import PolicyList from "./policies/PolicyList"
import PolicyEditor from "./policies/PolicyEditor"
import FxRates from "./policies/FxRates"
import Versions from "./lists/Versions"
import VersionRows from "./lists/VersionRows"
import Restrictions from "./lists/Restrictions"

function NotFound() {
  const { t } = useTexT()
  return (
    <Card>
      <EmptyState title={t("core.error.not_found")} />
    </Card>
  )
}

/** Routes under /tex/rates (Rates & Contracts, workstream A). */
export default function AreaRoutes() {
  return (
    <Routes>
      <Route index element={<ContractsList />} />
      <Route path="contracts" element={<Navigate to="/tex/rates" replace />} />
      <Route path="contracts/:name" element={<ContractDetail />} />
      <Route path="contracts/:name/versions/:version" element={<VersionEditor />} />
      <Route path="policies" element={<Navigate to="/tex/rates/policies/markup" replace />} />
      <Route path="policies/:kind" element={<PolicyList />} />
      <Route path="policies/:kind/:name" element={<PolicyEditor />} />
      <Route path="fx-rates" element={<FxRates />} />
      {/* cross-contract lists (R-35, G-64) */}
      <Route path="versions" element={<Versions />} />
      <Route path="periods" element={<VersionRows key="periods" section="periods" />} />
      <Route path="occupancy" element={<VersionRows key="occupancy" section="occupancy" />} />
      <Route path="rate-plans" element={<VersionRows key="rate_plans" section="rate_plans" />} />
      <Route path="restrictions" element={<Restrictions />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}
