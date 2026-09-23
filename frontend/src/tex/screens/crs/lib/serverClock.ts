// The server clock (session.bootstrap → server: {time_zone, now}). API datetimes are naive
// wall-clock times in `time_zone`; the browser may sit in another zone and its clock may be
// off, so quote countdowns and "today" are measured on the server clock:
//   offset = server now − browser time when the bootstrap response arrived.
// Naive strings are read with the same (browser-local) parser on both sides of that
// subtraction, so the zone cancels out and only the wall-clock digits matter.
import { useMemo } from "react"
import { dateTime, isoDay } from "../../../lib/format"
import { useSession } from "../../../lib/session"

const wall = (v: string) => new Date(v.replace(" ", "T")).getTime()

/** When the bootstrap response for `now` reached the browser (resource timing), else first sight. */
const seen = new Map<string, number>()
function receivedAt(now: string): number {
  const known = seen.get(now)
  if (known !== undefined) return known
  let at = Date.now()
  try {
    const entries = performance.getEntriesByType("resource") as PerformanceResourceTiming[]
    const hit = entries.filter((e) => e.name.includes("kamra.tex.api.session.bootstrap")).at(-1)
    // the latest bootstrap call is the one whose `now` the session holds
    if (hit && hit.responseStart > 0) at = performance.timeOrigin + hit.responseStart
  } catch {
    /* no resource timing: first sight is close enough right after sign-in */
  }
  seen.set(now, at)
  return at
}

export interface ServerClock {
  /** IANA zone of the server wall clock, when the server says. */
  tz?: string
  /** A Date whose local fields read the server wall clock now. */
  now: () => Date
  /** Server-side calendar day (the server rejects arrivals before it). */
  today: () => string
  /** Milliseconds from server-now until a naive server datetime (negative once past). */
  msUntil: (v?: string | null) => number
  /** A server datetime for display, labelled with the server time zone. */
  label: (v?: string | null) => string
}

export function useServerClock(): ServerClock {
  const { boot } = useSession()
  const tz = boot.server?.time_zone
  const now = boot.server?.now
  const arrived = boot.receivedAt
  return useMemo(() => {
    const offset = now ? wall(now) - (arrived ?? receivedAt(now)) : 0
    const serverNow = () => new Date(Date.now() + offset)
    return {
      tz,
      now: serverNow,
      today: () => isoDay(serverNow()),
      msUntil: (v) => (v ? wall(v) - serverNow().getTime() : Number.NaN),
      label: (v) => (!v ? "—" : tz ? `${dateTime(v)} (${tz})` : dateTime(v)),
    }
  }, [tz, now, arrived])
}

/** "4:59" / "1:02:03" for a countdown; "0:00" once expired. */
export function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = String(s % 60).padStart(2, "0")
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`
}
