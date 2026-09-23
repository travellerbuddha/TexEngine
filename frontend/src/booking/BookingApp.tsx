import { lazy, Suspense, useEffect } from "react"
import { Route, Routes } from "react-router-dom"
import { isEmbedded } from "./lib/storage"
import { NotFound } from "./pages/SiteError"
import SitePage from "./pages/SitePage"
import { anyDialogOpen } from "./ui/Dialog"
import { Spinner } from "./ui/feedback"

const ConfirmationPage = lazy(() => import("./pages/ConfirmationPage"))
const ManagePage = lazy(() => import("./pages/ManagePage"))
const PayLinkPage = lazy(() => import("./pages/PayLinkPage"))
const MockPayPage = lazy(() => import("./pages/MockPayPage"))
const PayReturnPage = lazy(() => import("./pages/PayReturnPage"))

/** Inside the widget's modal iframe, Esc (with no dialog of ours open) asks the
 * host page's widget to close the modal. */
function useEmbedBridge() {
  useEffect(() => {
    if (!isEmbedded() || window.parent === window) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || anyDialogOpen()) return
      window.parent.postMessage({ type: "tex-booking:close" }, "*")
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])
}

/** Guest booking engine routes (basename /book):
 *  /:site                         search → rooms → extras → details → payment
 *  /:site/confirmation/:booking   after booking / payment return
 *  /:site/manage#token=…          self-service (magic link)
 *  /pay/:token                    payment link
 *  /pay/return                    gateway return of a payment link (no token)
 *  /pay/mock/:txn                 sandbox gateway (Mock provider) */
export default function BookingApp() {
  useEmbedBridge()
  return (
    <Suspense fallback={<Spinner className="grid min-h-dvh place-items-center" />}>
      <Routes>
        <Route path="/pay/mock/:txn" element={<MockPayPage />} />
        <Route path="/pay/return" element={<PayReturnPage />} />
        <Route path="/pay/:token" element={<PayLinkPage />} />
        <Route path="/:site/confirmation/:booking" element={<ConfirmationPage />} />
        <Route path="/:site/manage" element={<ManagePage />} />
        <Route path="/:site" element={<SitePage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  )
}
