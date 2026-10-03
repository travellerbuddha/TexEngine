import { useEffect, useState } from "react"

// TEX Engine is a network service derived from Kamra PMS under AGPL-3.0: everyone who interacts
// with it (staff and guests) is offered its complete corresponding source (section 13, ADR-060).
// The address is the running version's (kamra.tex.entry.source_url). The server writes it into
// the pages it serves (source_meta), so it shows even when the API is rate limited or down; a
// page served without it (the dev server) asks session.entry once; failing both, the TEX
// repository at the commit this bundle was built from.

export const DEFAULT_SOURCE = "https://github.com/travellerbuddha/TexEngine"
export const UPSTREAM = { name: "Kamra PMS", url: "https://github.com/Kamra-PMS/kamra-pms" }
export const LICENSE = { name: "AGPL-3.0", url: "https://www.gnu.org/licenses/agpl-3.0.html" }

/** The commit this bundle was built from, when the build was told (vite `define` of TEX_BUILD_COMMIT, e.g. an image
 * build); "" for the committed and bench builds, whose pages name the running commit instead (ADR-073). */
export const BUILD_COMMIT: string = typeof __TEX_BUILD_COMMIT__ === "string" ? __TEX_BUILD_COMMIT__ : ""

function served(name: string): string | null {
  if (typeof document === "undefined") return null
  return document.querySelector(`meta[name="${name}"]`)?.getAttribute("content") || null
}

const https = (u: unknown): u is string => typeof u === "string" && /^https:\/\/\S+$/.test(u)

/** Where the running version's source is offered: the served page's address, else one the API
 * gave, else the TEX repository at the build commit. */
export function sourceUrl(fromApi?: string | null): string {
  const page = served("tex-source-url")
  if (https(page)) return page
  if (https(fromApi)) return fromApi
  return BUILD_COMMIT ? `${DEFAULT_SOURCE}/tree/${BUILD_COMMIT}` : DEFAULT_SOURCE
}

let asked: Promise<string | null> | null = null

/** session.entry's address, asked once per page load. */
function fromEntry(): Promise<string | null> {
  asked ??= fetch("/api/method/kamra.tex.api.session.entry", { credentials: "same-origin", headers: { Accept: "application/json" } })
    .then((r) => (r.ok ? (r.json() as Promise<{ message?: { source_url?: unknown } }>) : null))
    .then((body) => (https(body?.message?.source_url) ? body.message.source_url : null))
    .catch(() => null)
  return asked
}

/** `sourceUrl`, asking the server when neither the page nor the caller has the address. */
export function useSourceUrl(fromApi?: string | null): string {
  const [answer, setAnswer] = useState<string | null>(null)
  const known = https(served("tex-source-url")) || https(fromApi)
  useEffect(() => {
    if (known) return
    let live = true
    void fromEntry().then((url) => {
      if (live && url) setAnswer(url)
    })
    return () => {
      live = false
    }
  }, [known])
  return sourceUrl(https(fromApi) ? fromApi : answer)
}

/** The brand name the served page carries (TEX Settings), if any. */
export function servedBrand(): string | null {
  return served("tex-brand")
}
