// The browser's Back and Forward buttons inside the app (UX revision 2026-10). The app runs on a
// BrowserRouter, which has no navigation blockers, so the TEX shell's unsaved-changes guard
// (./unsaved.tsx) asks here before a history step takes the user off a page with unsaved edits:
//   * the popstate listener is installed before the router starts (main.tsx), so it runs before
//     the router's own listener;
//   * the user stays: the event is stopped (the router never sees it) and the browser is sent back
//     to the entry it left (history.go), whose own popstate is stopped too: the page, its URL and
//     its edits are as they were;
//   * the user leaves: the event goes on to the router as usual.
// A step that only changes the hash keeps the page (and its edits): never asked. Leaving the app
// (a step to another document) is the browser's own beforeunload prompt.

/** May the user leave the page shown? (asks when something is unsaved; true = go ahead) */
type Ask = () => boolean

let ask: Ask | null = null
let installed = false
/** React Router's index of the entry shown, and its path + query (updated on every navigation) */
let at: number | null = null
let atPage = ""
/** the step back to the entry the user stayed on: stopped like the step it undoes */
let restoring = false

const indexOf = (state: unknown): number | null => {
  const i = (state as { idx?: unknown } | null)?.idx
  return typeof i === "number" ? i : null
}
const pageOf = () => window.location.pathname + window.location.search

/** Install once, before the router (main.tsx). */
export function installBackGuard() {
  if (installed || typeof window === "undefined") return
  installed = true
  noteLocation()
  window.addEventListener("popstate", (e) => {
    if (restoring) {
      restoring = false
      e.stopImmediatePropagation()
      return
    }
    const next = indexOf(e.state)
    const leaving = pageOf() !== atPage
    if (ask && leaving && at !== null && next !== null && next !== at && !ask()) {
      e.stopImmediatePropagation()
      restoring = true
      window.history.go(at - next)
      return
    }
    at = next
    atPage = pageOf()
  })
}

/** The page shown changed (any navigation): remember where the user is. */
export function noteLocation() {
  at = indexOf(window.history.state)
  atPage = pageOf()
}

/** Set (or clear) the question asked before a history step leaves the page. */
export function setBackGuard(fn: Ask | null) {
  ask = fn
}
