import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import "./booking.css"
import BookingApp from "./BookingApp"
import { detectLang, I18nProvider } from "./i18n"
import { BASENAME } from "./lib/mount"

// Guest booking engine bundle (ADR-012): served at /book/<site>/… by kamra/www/book.py, and
// from "/" on a hotel's own verified host, pinned to its site (kamra/tex/booking_host.py,
// ADR-035; see lib/mount.ts).
// Independent of the admin SPA — nothing here imports admin code or catalogs.
createRoot(document.getElementById("tex-booking")!).render(
  <StrictMode>
    <I18nProvider initial={detectLang()}>
      <BrowserRouter basename={BASENAME}>
        <BookingApp />
      </BrowserRouter>
    </I18nProvider>
  </StrictMode>,
)
