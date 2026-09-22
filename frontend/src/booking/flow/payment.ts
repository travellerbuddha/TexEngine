// Hand the guest to the payment provider the server chose. Card details are only
// ever entered on the provider's page (or the TEX sandbox page); TEX never sees them.
import type { NavigateFunction } from "react-router-dom"
import type { PaymentStart } from "../types"
import { disarmAbandon } from "../lib/track"

const BASE = "/book"

function inFrame() {
  try {
    return window.self !== window.top
  } catch {
    return true
  }
}

/** In-app path (without the /book basename) for a URL on this booking engine, else null. */
export function appPath(url: string): string | null {
  let u: URL
  try {
    u = new URL(url, window.location.origin)
  } catch {
    return null
  }
  if (!/^https?:$/.test(u.protocol)) return null
  // Any /book/… URL (this host, the TEX host behind a dev proxy, or a verified custom
  // domain) continues inside this app on the current origin, where the tab's
  // session state lives. Only the path is used, so this is never an open redirect.
  if (u.pathname === BASE || u.pathname.startsWith(`${BASE}/`)) return (u.pathname.slice(BASE.length) || "/") + u.search + u.hash
  return null
}

export type PaymentOutcome = "internal" | "external" | "blocked" | "none"

export function continuePayment(p: PaymentStart | null | undefined, navigate: NavigateFunction): PaymentOutcome {
  if (!p) return "none"
  if (p.kind === "redirect" && p.url) {
    const inApp = appPath(p.url)
    disarmAbandon()
    if (inApp) {
      navigate(inApp)
      return "internal"
    }
    if (!/^https:\/\//i.test(p.url)) return "blocked"
    if (inFrame()) {
      try {
        window.top!.location.href = p.url
        return "external"
      } catch {
        return "blocked"
      }
    }
    window.location.assign(p.url)
    return "external"
  }
  if (p.kind === "form_post" && p.url) {
    disarmAbandon()
    const form = document.createElement("form")
    form.method = "POST"
    form.action = p.url
    if (inFrame()) form.target = "_top"
    for (const [k, v] of Object.entries(p.fields ?? {})) {
      const input = document.createElement("input")
      input.type = "hidden"
      input.name = k
      input.value = String(v ?? "")
      form.appendChild(input)
    }
    document.body.appendChild(form)
    form.submit()
    return "external"
  }
  return "none"
}
