import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import "./booking.css"
import BookingApp from "./BookingApp"

// Guest booking engine bundle (ADR-012): served at /book/<site>/… by kamra/www/book.py.
createRoot(document.getElementById("tex-booking")!).render(
  <StrictMode>
    <BrowserRouter basename="/book">
      <BookingApp />
    </BrowserRouter>
  </StrictMode>,
)
