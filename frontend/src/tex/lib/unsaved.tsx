// Unsaved-changes guard of the TEX shell (UX revision 2026-10). The app runs on a BrowserRouter,
// which has no navigation blockers, so a screen with edits that are not saved yet registers a
// check here and the shell asks before anything takes the user away from it:
//   * an in-app link (sidebar, breadcrumbs, a chip): the click is caught on the document before
//     the router sees it, and stopped when the user stays;
//   * the hotel switcher and the command palette (`confirmLeave`);
//   * a reload or closing the tab (beforeunload, the browser's own prompt).
// The browser's Back button inside the app is not caught (no blocker without a data router).
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, type ReactNode } from "react"

type Check = () => boolean

interface Guard {
  /** Register a check (true = something is unsaved); returns the unregister function. */
  register: (check: Check) => () => void
  /** Whether the user may leave: nothing is unsaved, or they agreed to lose it. */
  confirmLeave: () => boolean
}

const Ctx = createContext<Guard>({ register: () => () => undefined, confirmLeave: () => true })

/** Whether a click on `a` would make the router (or the browser) leave the current page. */
function leaves(e: MouseEvent, a: HTMLAnchorElement): boolean {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return false
  if ((a.target && a.target !== "_self") || a.hasAttribute("download")) return false
  const url = new URL(a.href, window.location.href)
  if (url.origin !== window.location.origin) return true
  // a link to the page itself (a hash or the same query) keeps the screen and its edits
  return url.pathname !== window.location.pathname || url.search !== window.location.search
}

export function UnsavedChangesProvider({ message, children }: { message: string; children: ReactNode }) {
  const checks = useRef(new Set<Check>())
  const pending = useCallback(() => [...checks.current].some((c) => c()), [])
  const confirmLeave = useCallback(() => !pending() || window.confirm(message), [pending, message])

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented) return
      const a = (e.target instanceof Element ? e.target.closest("a[href]") : null) as HTMLAnchorElement | null
      if (!a || !leaves(e, a) || !pending()) return
      if (window.confirm(message)) return
      e.preventDefault()
      e.stopPropagation()
    }
    const onUnload = (e: BeforeUnloadEvent) => {
      if (pending()) e.preventDefault()
    }
    // capture: before React's root listener, so the router never starts the navigation
    document.addEventListener("click", onClick, true)
    window.addEventListener("beforeunload", onUnload)
    return () => {
      document.removeEventListener("click", onClick, true)
      window.removeEventListener("beforeunload", onUnload)
    }
  }, [pending, message])

  const value = useMemo<Guard>(
    () => ({
      register: (check) => {
        checks.current.add(check)
        return () => {
          checks.current.delete(check)
        }
      },
      confirmLeave,
    }),
    [confirmLeave],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

/** Protect a screen's unsaved edits: `isDirty` is read when the user is about to leave (pass the
 * latest closure; it may read the DOM). */
export function useUnsavedChanges(isDirty: Check) {
  const { register } = useContext(Ctx)
  const latest = useRef(isDirty)
  latest.current = isDirty
  useEffect(() => register(() => latest.current()), [register])
}

/** Ask before a programmatic navigation or a hotel switch (true = go ahead). */
export function useConfirmLeave(): () => boolean {
  return useContext(Ctx).confirmLeave
}
