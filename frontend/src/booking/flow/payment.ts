// Hand the guest to the payment provider the server chose. Card details are only
// ever entered on the provider's page (or the TEX sandbox page); TEX never sees them.
import type { NavigateFunction } from "react-router-dom"
import type { PaymentStart } from "../types"
import { routeFor } from "../lib/mount"
import { disarmAbandon } from "../lib/track"

function inFrame() {
  try {
    return window.self !== window.top
  } catch {
    return true
  }
}

/** In-app router path (without the basename) for a URL on this booking engine, else null
 * (see routeFor in lib/mount: /book/… on the platform, the site's own pages on its host). */
export function appPath(url: string): string | null {
  return routeFor(url)
}

/** Continue on a page of this engine (absolute path or URL) with a payment result query
 * appended: inside the app when it is one of ours, else a full page load. */
export function resumeAt(target: string, query: string, navigate: NavigateFunction) {
  const url = `${target}${target.includes("?") ? "&" : "?"}${query}`
  const inApp = appPath(url)
  if (inApp) navigate(inApp, { replace: true })
  else window.location.assign(url)
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
