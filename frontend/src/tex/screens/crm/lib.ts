// Small helpers for the CRM screens. Nothing here computes money.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import { idempotencyKey } from "../../lib/api"
import { csvCell } from "../../lib/csv"
import type { ConsentField } from "./types"

/** Value that settles `ms` after the last change (search boxes). */
export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(id)
  }, [value, ms])
  return v
}

/** Stable function identity that always calls the latest `fn`. Dialog/Drawer re-run
 * their focus management when `onClose` changes, so close handlers must be stable. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function useEvent<A extends any[], R>(fn: (...args: A) => R): (...args: A) => R {
  const ref = useRef(fn)
  useLayoutEffect(() => {
    ref.current = fn
  })
  return useCallback((...args: A) => ref.current(...args), [])
}

/** One idempotency key per user intent: renewed each time `open` turns true, kept
 * across retries while the dialog stays open. */
export function useIntentKey(prefix: string, open: boolean): string {
  const [key, setKey] = useState(() => idempotencyKey(prefix))
  useEffect(() => {
    if (open) setKey(idempotencyKey(prefix))
  }, [open, prefix])
  return key
}

export const CONSENT_CHANNEL: Record<ConsentField, "email" | "sms" | "whatsapp"> = {
  tex_consent_email: "email",
  tex_consent_sms: "sms",
  tex_consent_whatsapp: "whatsapp",
}

/** Export channel (server name) → guest consent field. */
export const EXPORT_CHANNELS = [
  { channel: "Email", field: "tex_consent_email" as ConsentField, key: "email" },
  { channel: "SMS", field: "tex_consent_sms" as ConsentField, key: "sms" },
  { channel: "WhatsApp", field: "tex_consent_whatsapp" as ConsentField, key: "whatsapp" },
] as const

export function isInteger(s: string, allowNegative = false) {
  return (allowNegative ? /^-?\d+$/ : /^\d+$/).test(s.trim())
}

export function splitTags(s: string | null | undefined): string[] {
  return (s || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)
}

export function downloadCsv(filename: string, header: string[], rows: unknown[][]) {
  const text = [header, ...rows].map((r) => r.map((v) => csvCell(v)).join(",")).join("\r\n")
  // BOM so spreadsheet apps read UTF-8 names (ğ, ş, ł …) correctly
  const blob = new Blob(["﻿", text], { type: "text/csv;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function safeJson<T>(s: string | null | undefined, fallback: T): T {
  if (!s) return fallback
  try {
    return JSON.parse(s) as T
  } catch {
    return fallback
  }
}
