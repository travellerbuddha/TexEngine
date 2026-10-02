import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import "./index.css"
import App from "./App"
import { initTheme } from "./lib/theme"
import { initLang } from "./lib/dir"
import { asset } from "./lib/asset"
import { AuthProvider } from "./lib/auth"
import { CashierAuthProvider } from "./lib/cashierAuth"
import { ROUTER_BASENAME } from "./lib/routing"
import { installBackGuard } from "./tex/lib/backGuard"

initTheme()
initLang()
// before the router: its popstate listener must run first (unsaved edits on Back/Forward)
installBackGuard()

// Favicons, base-aware (see index.html note).
function setIcon(rel: string, href: string, type?: string) {
  const link = document.createElement("link")
  link.rel = rel
  link.href = asset(href)
  if (type) link.type = type
  document.head.appendChild(link)
}
setIcon("icon", "tex-mark.svg", "image/svg+xml")
setIcon("icon", "tex-favicon-32.png", "image/png")
setIcon("apple-touch-icon", "tex-apple-touch-180.png")

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename={ROUTER_BASENAME}>
      <AuthProvider>
        <CashierAuthProvider>
          <App />
        </CashierAuthProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
