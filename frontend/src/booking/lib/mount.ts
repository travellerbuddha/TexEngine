// Where this booking engine is mounted (G-21, ADR-035).
//
// On the platform the engine lives under /book: /book/<site>/… for a booking site and
// /book/pay/… for the site-less payment pages. On a hotel's own verified host
// (book.hotel.com) the server serves the same bundle pinned to that host's site: the page
// carries <meta name="tex-booking-site" content="<slug>"> and every page routes from "/"
// (/, /manage, /confirmation/<booking>, /pay/…). The platform's /book/… pages still work
// on that host. Every in-app link and every return URL is built here, never by hand.
import { useParams } from "react-router-dom"

const SLUG = /^[a-z0-9](?:[a-z0-9-]{0,138}[a-z0-9])?$/

function readPinned(): string | null {
  try {
    const raw = document.querySelector<HTMLMetaElement>('meta[name="tex-booking-site"]')?.getAttribute("content")
    const slug = (raw ?? "").trim().toLowerCase()
    return SLUG.test(slug) ? slug : null
  } catch {
    return null
  }
}

/** The booking site this page is pinned to (its own host), else null (the platform). Read once. */
export const PINNED_SLUG: string | null = readPinned()
export const PINNED = PINNED_SLUG !== null
/** BrowserRouter basename. */
export const BASENAME = PINNED ? "/" : "/book"
/** Absolute path of the engine's entry page. */
export const HOME_PATH = PINNED ? "/" : "/book"

const clean = (sub: string) => sub.replace(/^\/+/, "")

/** Router path (relative to BASENAME) of a page of a booking site: "/<sub>" when pinned,
 * else "/<slug>/<sub>". `sub` may carry a query or fragment ("manage#token=…"). */
export function siteRoute(slug: string, sub = ""): string {
  const s = clean(sub)
  if (PINNED) return `/${s}`
  const base = `/${encodeURIComponent(slug)}`
  return s ? `${base}${/^[?#]/.test(s) ? "" : "/"}${s}` : base
}

/** Absolute path (on this origin) of a page of a booking site: "/<sub>" on the site's own
 * host, "/book/<slug>/<sub>" on the platform. */
export function sitePath(slug: string, sub = ""): string {
  const r = siteRoute(slug, sub)
  return PINNED ? r : `/book${r}`
}

/** Router path of a site-less payment page ("<token>", "return", "mock/<txn>"): the same in both mounts. */
export function payRoute(sub: string): string {
  return `/pay/${clean(sub)}`
}

/** Absolute path of a site-less payment page: "/pay/<sub>" on a hotel's host, "/book/pay/<sub>" on the platform. */
export function payPath(sub: string): string {
  return PINNED ? payRoute(sub) : `/book${payRoute(sub)}`
}

/** Router path of the payment-link page. The token travels in the URL fragment, which
 * browsers never send to a server: no access log or Referer header ever holds it (G-83). */
export function payLinkRoute(token: string): string {
  return `/pay#token=${encodeURIComponent(token)}`
}

/** Absolute path of the payment-link page for `token` ("/book/pay#token=…" on the platform). */
export function payLinkPath(token: string): string {
  return PINNED ? payLinkRoute(token) : `/book${payLinkRoute(token)}`
}

/** Absolute path of the payment-link page with no token: where a gateway's return brings the guest back, the
 * tab's stored token read again (LO-30), so no address after the e-mailed link carries it. */
export function payLinkPagePath(): string {
  return PINNED ? "/pay" : "/book/pay"
}

/** A payment link e-mailed before G-83 carries its token in the path (…/pay/<token>). Move
 * it into the fragment before the app starts, so that no request the page makes (API calls
 * and their Referer) repeats it. Call once, before the router reads the location. */
export function adoptPathToken(): void {
  try {
    const base = PINNED ? "" : "/book"
    const m = /^\/pay\/([^/]+)\/?$/.exec(window.location.pathname.slice(base.length))
    if (!window.location.pathname.startsWith(`${base}/pay/`) || !m || m[1] === "return") return
    const token = decodeURIComponent(m[1])
    window.history.replaceState(window.history.state, "", `${base}/pay${window.location.search}#token=${encodeURIComponent(token)}`)
  } catch {
    /* leave the address as it is */
  }
}

/** Absolute URL on the current origin of a page of a booking site (return URLs sent to the server). */
export function siteUrl(slug: string, sub = ""): string {
  return `${window.location.origin}${sitePath(slug, sub)}`
}

/** The booking site of the current page: the pinned site, else the :site route parameter. */
export function useSiteSlug(): string | undefined {
  const { site } = useParams()
  return PINNED_SLUG ?? site
}

/** The booking site of the address the page opened at, before the router runs (null on a site-less page). */
export function slugFromLocation(path = window.location.pathname): string | null {
  if (PINNED_SLUG) return PINNED_SLUG
  const m = /^\/book\/([^/?#]+)/.exec(path)
  const slug = m ? decodeURIComponent(m[1]).toLowerCase() : null
  return slug && slug !== "pay" && SLUG.test(slug) ? slug : null
}

/** The member page of a site, as the address the page opened at (where a member link's token arrives). */
export function isMemberPath(path = window.location.pathname): boolean {
  return /^\/(?:book\/[^/]+\/)?member\/?$/.test(path)
}

// pages a pinned engine serves from "/" (everything else on the host is the platform's)
const PINNED_ROUTE = /^\/(?:|manage|member|confirmation\/[^/]+|pay|pay\/.+)$/

/** In-app router path for a URL of this booking engine, else null (leave the app).
 * - /book/… on any host (this host, the TEX host behind a dev proxy, a verified custom
 *   domain) continues inside this app on the current origin, where the tab's session
 *   state lives. When pinned, only /book/pay/… and the pinned site's /book/<slug>/… do.
 * - When pinned, the site's own pages ("/", "/manage", …) on this origin do too.
 * Only the path is used, so this is never an open redirect. */
export function routeFor(url: string): string | null {
  let u: URL
  try {
    u = new URL(url, window.location.origin)
  } catch {
    return null
  }
  if (!/^https?:$/.test(u.protocol)) return null
  const rest = u.search + u.hash
  const p = u.pathname
  if (p === "/book" || p.startsWith("/book/")) {
    const inner = p.slice("/book".length) || "/"
    if (!PINNED) return inner + rest
    if (inner === "/") return "/" + rest
    if (inner === "/pay" || inner.startsWith("/pay/")) return inner + rest
    const prefix = `/${PINNED_SLUG}`
    if (inner === prefix || inner.startsWith(`${prefix}/`)) return (inner.slice(prefix.length) || "/") + rest
    return null
  }
  if (PINNED && u.origin === window.location.origin && PINNED_ROUTE.test(p)) return p + rest
  return null
}
