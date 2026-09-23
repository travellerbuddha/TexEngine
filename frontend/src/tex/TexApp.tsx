import { lazy, Suspense, useEffect } from "react"
import { Route, Routes } from "react-router-dom"
import { TexSessionProvider, useSession } from "./lib/session"
import { TexShell } from "./shell/TexShell"
import { Card, EmptyState, ErrorState, Spinner, ToastProvider } from "./ui"
import { useTexI18nReady, useTexT } from "./i18n"

// One lazy chunk per area; each area owns its own sub-routes (routes.tsx).
const Dashboard = lazy(() => import("./screens/dashboard/Dashboard"))
const Crs = lazy(() => import("./screens/crs/routes"))
const Reservations = lazy(() => import("./screens/reservations/routes"))
const Rates = lazy(() => import("./screens/rates/routes"))
const Inventory = lazy(() => import("./screens/inventory/routes"))
const BookingEngine = lazy(() => import("./screens/booking-engine/routes"))
const Crm = lazy(() => import("./screens/crm/routes"))
const Payments = lazy(() => import("./screens/payments/routes"))
const Reports = lazy(() => import("./screens/reports/routes"))
const Connect = lazy(() => import("./screens/connect/routes"))
const Settings = lazy(() => import("./screens/settings/routes"))

function Loading() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <Spinner />
    </div>
  )
}

function NoHotel() {
  const { t } = useTexT()
  return (
    <Card>
      <EmptyState title={t("core.shell.no_hotel")} description={t("core.shell.no_hotel_body")} />
    </Card>
  )
}

function NotFound() {
  const { t } = useTexT()
  return (
    <Card>
      <EmptyState title={t("core.error.not_found")} />
    </Card>
  )
}

/** TEX admin / CRS / call-centre application, mounted at /tex/*. */
export default function TexApp() {
  const i18nReady = useTexI18nReady()
  useEffect(() => {
    const previous = document.title
    document.title = "TEX Engine"
    return () => {
      document.title = previous
    }
  }, [])
  if (!i18nReady)
    return (
      <div className="tex-root flex min-h-screen items-center justify-center bg-zinc-50">
        <Spinner />
      </div>
    )
  return (
    <ToastProvider>
      <TexSessionProvider
        fallback={
          <div className="tex-root flex min-h-screen items-center justify-center bg-zinc-50">
            <Spinner />
          </div>
        }
        onError={(e) => (
          <div className="tex-root flex min-h-screen items-center justify-center bg-zinc-50 p-6">
            <Card className="max-w-lg">
              <ErrorState error={e} onRetry={() => window.location.reload()} />
            </Card>
          </div>
        )}
      >
        <TexShell>
          <Suspense fallback={<Loading />}>
            <AreaRouter />
          </Suspense>
        </TexShell>
      </TexSessionProvider>
    </ToastProvider>
  )
}

function AreaRouter() {
  const { property } = useSession()
  if (!property) return <NoHotel />
  return (
    <Routes>
      <Route index element={<Dashboard />} />
      <Route path="crs/*" element={<Crs />} />
      <Route path="reservations/*" element={<Reservations />} />
      <Route path="rates/*" element={<Rates />} />
      <Route path="inventory/*" element={<Inventory />} />
      <Route path="booking-engine/*" element={<BookingEngine />} />
      <Route path="crm/*" element={<Crm />} />
      <Route path="payments/*" element={<Payments />} />
      <Route path="reports/*" element={<Reports />} />
      <Route path="connect/*" element={<Connect />} />
      <Route path="settings/*" element={<Settings />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}
