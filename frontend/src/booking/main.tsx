import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import "./booking.css"
import BookingApp from "./BookingApp"
import { detectLang, I18nProvider } from "./i18n"

// Guest booking engine bundle (ADR-012): served at /book/<site>/… by kamra/www/book.py.
// Independent of the admin SPA — nothing here imports admin code or catalogs.
createRoot(document.getElementById("tex-booking")!).render(
  <StrictMode>
    <I18nProvider initial={detectLang()}>
      <BrowserRouter basename="/book">
        <BookingApp />
      </BrowserRouter>
    </I18nProvider>
  </StrictMode>,
)
