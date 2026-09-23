import { lazy, Suspense, useEffect } from "react"
import { Route, Routes } from "react-router-dom"
import { PINNED } from "./lib/mount"
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

/** Guest booking engine routes.
 *  On the platform (basename /book):
 *  /:site                         search → rooms → extras → details → payment
 *  /:site/confirmation/:booking   after booking / payment return
 *  /:site/manage#token=…          self-service (magic link)
 *  On a hotel's own host, pinned to its site (basename /, ADR-035) the same pages
 *  without the :site prefix: /, /confirmation/:booking, /manage.
 *  Both:
 *  /pay/:token                    payment link
 *  /pay/return                    gateway return of a payment link (no token)
 *  /pay/mock/:txn                 sandbox gateway (Mock provider)
 *  The pages read the site with useSiteSlug() (lib/mount). */
export default function BookingApp() {
  useEmbedBridge()
  return (
    <Suspense fallback={<Spinner className="grid min-h-dvh place-items-center" />}>
      <Routes>
        <Route path="/pay/mock/:txn" element={<MockPayPage />} />
        <Route path="/pay/return" element={<PayReturnPage />} />
        <Route path="/pay/:token" element={<PayLinkPage />} />
        {PINNED ? (
          <>
            <Route path="/confirmation/:booking" element={<ConfirmationPage />} />
            <Route path="/manage" element={<ManagePage />} />
            <Route path="/" element={<SitePage />} />
          </>
        ) : (
          <>
            <Route path="/:site/confirmation/:booking" element={<ConfirmationPage />} />
            <Route path="/:site/manage" element={<ManagePage />} />
            <Route path="/:site" element={<SitePage />} />
          </>
        )}
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  )
}
