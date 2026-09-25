// Horizontal scroll kept in step across several scroll containers (PRICING_WORKSPACE_UX.md §3.1:
// the matrix, the occupancy ladder and the boards grid share one column template so P1…Pn line
// up; each has its own scroll box, so without this, scrolling one to P8 left the others at P1;
// S16 review). A container registers itself; scrolling any of them sideways scrolls the others to
// the same scrollLeft, and a container registered later starts where the group is.
import { createContext, createElement, useCallback, useContext, useMemo, type ReactNode } from "react"

export interface ScrollSync {
  /** Keep `el`'s scrollLeft in step with the group's; the returned function leaves the group. */
  register: (el: HTMLElement) => () => void
}

export function createScrollSync(): ScrollSync {
  const members = new Set<HTMLElement>()
  // the scrollLeft each member was set to by the group: its own scroll event is an echo, not a
  // user scroll (read back after the write, so a container that clamps it is not taken for one)
  const echoes = new WeakMap<HTMLElement, number>()
  let x = 0
  const onScroll = (e: Event) => {
    const src = e.currentTarget as HTMLElement
    const left = src.scrollLeft
    if (echoes.get(src) === left) {
      echoes.delete(src)
      return
    }
    echoes.delete(src)
    if (left === x) return // a vertical scroll
    x = left
    for (const el of members) {
      if (el === src || el.scrollLeft === x) continue
      el.scrollLeft = x
      echoes.set(el, el.scrollLeft)
    }
  }
  return {
    register(el) {
      members.add(el)
      if (x && el.scrollLeft !== x) {
        el.scrollLeft = x
        echoes.set(el, el.scrollLeft)
      }
      el.addEventListener("scroll", onScroll, { passive: true })
      return () => {
        el.removeEventListener("scroll", onScroll)
        members.delete(el)
      }
    },
  }
}

const ScrollSyncContext = createContext<ScrollSync | null>(null)

/** Scroll containers under it that use `useScrollSyncRef` scroll sideways together. */
export function ScrollSyncGroup({ children }: { children: ReactNode }) {
  const sync = useMemo(createScrollSync, [])
  return createElement(ScrollSyncContext.Provider, { value: sync }, children)
}

/** A ref callback for a scroll container that joins the enclosing ScrollSyncGroup (none: no-op). */
export function useScrollSyncRef(): (el: HTMLElement | null) => (() => void) | void {
  const sync = useContext(ScrollSyncContext)
  return useCallback((el: HTMLElement | null) => (el && sync ? sync.register(el) : undefined), [sync])
}
