import { lazy, Suspense, useEffect } from "react"
import { Navigate, Route, Routes, useLocation, useParams } from "react-router-dom"
import { PINNED, payLinkRoute } from "./lib/mount"
import { isEmbedded } from "./lib/storage"
import { NotFound } from "./pages/SiteError"
import SitePage from "./pages/SitePage"
import { anyDialogOpen } from "./ui/Dialog"
import { Spinner } from "./ui/feedback"

const ConfirmationPage = lazy(() => import("./pages/ConfirmationPage"))
const ManagePage = lazy(() => import("./pages/ManagePage"))
const MemberPage = lazy(() => import("./pages/MemberPage"))
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

/** An in-app visit to an old-style payment link (…/pay/<token>): the same page, with the
 * token moved into the fragment (G-83). */
function LegacyPayLink() {
  const { token = "" } = useParams()
  const { search } = useLocation()
  const [path, frag] = payLinkRoute(token).split("#")
  return <Navigate to={`${path}${search}#${frag}`} replace />
}

/** Guest booking engine routes.
 *  On the platform (basename /book):
 *  /:site                         search → rooms → extras → details → payment
 *  /:site/confirmation/:booking   after booking / payment return
 *  /:site/manage#token=…          self-service (magic link)
 *  /:site/member#token=…          a loyalty member's sign-in or join link (C-04)
 *  On a hotel's own host, pinned to its site (basename /, ADR-035) the same pages
 *  without the :site prefix: /, /confirmation/:booking, /manage, /member.
 *  Both:
 *  /pay#token=…                   payment link (the token never reaches a server log, G-83);
 *                                 an old /pay/:token link moves its token into the fragment
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
        <Route path="/pay" element={<PayLinkPage />} />
        <Route path="/pay/:token" element={<LegacyPayLink />} />
        {PINNED ? (
          <>
            <Route path="/confirmation/:booking" element={<ConfirmationPage />} />
            <Route path="/manage" element={<ManagePage />} />
            <Route path="/member" element={<MemberPage />} />
            <Route path="/" element={<SitePage />} />
          </>
        ) : (
          <>
            <Route path="/:site/confirmation/:booking" element={<ConfirmationPage />} />
            <Route path="/:site/manage" element={<ManagePage />} />
            <Route path="/:site/member" element={<MemberPage />} />
            <Route path="/:site" element={<SitePage />} />
          </>
        )}
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  )
}
