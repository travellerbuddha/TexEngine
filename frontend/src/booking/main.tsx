import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import "./booking.css"
import BookingApp from "./BookingApp"
import { detectLang, I18nProvider } from "./i18n"
import { isolateMemberData, keepSessionsOnDevice, takeMemberLinkToken } from "./lib/member"
import { adoptPathToken, BASENAME, isMemberPath, PINNED, slugFromLocation } from "./lib/mount"

// Guest booking engine bundle (ADR-012): served at /book/<site>/… by kamra/www/book.py, and
// from "/" on a hotel's own verified host, pinned to its site (kamra/tex/booking_host.py,
// ADR-035; see lib/mount.ts).
// Independent of the admin SPA — nothing here imports admin code or catalogs.
// an old payment link's token leaves the path before anything else runs (G-83)
adoptPathToken()
// a member's session (ADR-078, owner 2026-10-03): on the device on a hotel's own host, in the tab on the platform's
// shared host, where a site's page first removes every other site's member data (their tag containers run here
// too); a member link's token leaves the address bar before anything else runs
keepSessionsOnDevice(PINNED)
if (!PINNED) isolateMemberData(slugFromLocation())
if (isMemberPath()) takeMemberLinkToken()
createRoot(document.getElementById("tex-booking")!).render(
  <StrictMode>
    <I18nProvider initial={detectLang()}>
      <BrowserRouter basename={BASENAME}>
        <BookingApp />
      </BrowserRouter>
    </I18nProvider>
  </StrictMode>,
)
