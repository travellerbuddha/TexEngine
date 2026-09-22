// Translated labels for server codes (boards, statuses, pricing modes, deposit
// types). Unknown codes fall back to the raw value, never to an empty string.
import { useCallback, useMemo } from "react"
import { useTexT } from "../../../i18n"
import { boardKey } from "./party"

export function slug(s: string | null | undefined) {
  return (s || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "")
}

export function useLabels() {
  const { t } = useTexT()
  const lookup = useCallback(
    (prefix: string, code: string | null | undefined) => {
      if (!code) return "—"
      const key = `${prefix}.${slug(code)}`
      const v = t(key)
      return v === key ? code : v
    },
    [t],
  )
  return useMemo(
    () => ({
      board: (code: string | null | undefined) => {
        const k = boardKey(code)
        return k ? t(k) : code || "—"
      },
      status: (s: string | null | undefined) => lookup("crs.status", s),
      mode: (m: string | null | undefined) => lookup("crs.mode", m),
      deposit: (d: string | null | undefined) => lookup("crs.deposit", d),
      channel: (c: string | null | undefined) => lookup("crs.channel", c),
      method: (m: string | null | undefined) => lookup("crs.method", m),
      changeType: (c: string | null | undefined) => lookup("crs.change", c),
      basis: (b: string | null | undefined) => lookup("crs.basis", b),
    }),
    [t, lookup],
  )
}
