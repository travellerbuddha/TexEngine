// Payments screen helpers. Money stays a decimal string (amounts.ts): never a float.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import { idempotencyKey } from "../../lib/api"

/** Stable function identity that always calls the latest `fn` (Dialog/Drawer
 * re-run focus management when `onClose` changes identity). */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function useEvent<A extends any[], R>(fn: (...args: A) => R): (...args: A) => R {
  const ref = useRef(fn)
  useLayoutEffect(() => {
    ref.current = fn
  })
  return useCallback((...args: A) => ref.current(...args), [])
}

/** One idempotency key per user intent: renewed when `open` turns true and kept
 * while the dialog stays open, so a retried request cannot pay or refund twice. */
export function useIntentKey(prefix: string, open: boolean): string {
  const [key, setKey] = useState(() => idempotencyKey(prefix))
  useEffect(() => {
    if (open) setKey(idempotencyKey(prefix))
  }, [open, prefix])
  return key
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(id)
  }, [value, ms])
  return v
}

// the amount helpers are pure (amounts.ts, node tests); kept importable from here
export { isPositiveAmount, isZero, minusAmount } from "./amounts"

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // clipboard API blocked (http / permissions): fall back to a hidden textarea
    try {
      const ta = document.createElement("textarea")
      ta.value = text
      ta.setAttribute("readonly", "")
      ta.style.position = "fixed"
      ta.style.opacity = "0"
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand("copy")
      ta.remove()
      return ok
    } catch {
      return false
    }
  }
}

export const statusKey = (s: string) => `payments.status.${s.toLowerCase().replace(/\s+/g, "_")}`
export const methodKey = (m: string) => `payments.method.${m.toLowerCase().replace(/\s+/g, "_")}`
export const typeKey = (t: string) => `payments.type.${t.toLowerCase()}`
export const linkStatusKey = (s: string) => `payments.link.status.${s.toLowerCase().replace(/\s+/g, "_")}`
export const allocKey = (s: string) => `payments.alloc.${s.toLowerCase()}`
