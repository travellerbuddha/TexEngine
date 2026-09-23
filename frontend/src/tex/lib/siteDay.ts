// The site's "today" for the staff app (G-91). Date pickers and default ranges start on the
// hotel's calendar day, which is the server's day in the site time zone (System Settings) —
// not the browser's: just after the site's midnight a browser in an earlier zone is still on
// yesterday (a past arrival the server refuses, a grid starting yesterday), and one in a later
// zone is already on tomorrow.
//
// session.bootstrap → server: {time_zone, now, today}. The site's wall clock is read as
//   Intl.DateTimeFormat({ timeZone: time_zone }) of (browser clock + skew)
//   skew = server.now − that zone's wall clock read in the browser when the bootstrap arrived
// Intl follows the site's own midnight and DST changes for as long as the tab stays open; the
// skew cancels a browser clock that is off (and zone data that disagrees with the server's by
// a fixed offset). A browser that does not know the zone counts the time elapsed since
// server.now instead. The day is never before server.today.
import { useCallback, useMemo, useSyncExternalStore } from "react"
import { isoDay } from "./format"
import { useSession, type Bootstrap } from "./session"

const DAY_MS = 86_400_000
const HOUR_MS = 3_600_000
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

/** A naive wall-clock time ("2026-09-24T01:31:19.844512") → its digits read as UTC (ms). */
export function wallMs(v: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3})\d*)?)?)?$/.exec(v.trim())
  if (!m) return null
  const [, y, mo, d, h = "0", mi = "0", s = "0", ms = "0"] = m
  return Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s), Number(ms.padEnd(3, "0")))
}

const formats = new Map<string, Intl.DateTimeFormat | null>()

/** A formatter for the wall clock of `tz`, or null when this browser does not know the zone. */
function zoneFormat(tz: string): Intl.DateTimeFormat | null {
  if (!formats.has(tz)) {
    let f: Intl.DateTimeFormat | null = null
    try {
      f = new Intl.DateTimeFormat("en-US", {
        timeZone: tz,
        hourCycle: "h23",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    } catch {
      f = null // RangeError: an unknown time zone
    }
    formats.set(tz, f)
  }
  return formats.get(tz) ?? null
}

/** The wall clock of the formatter's zone at `instant`, its digits read as UTC (ms). */
function zoneWall(f: Intl.DateTimeFormat, instant: number): number | null {
  const p: Record<string, number> = {}
  for (const x of f.formatToParts(instant)) if (x.type !== "literal") p[x.type] = Number(x.value)
  if (!p.year || !p.month || !p.day) return null
  return Date.UTC(p.year, p.month - 1, p.day, (p.hour ?? 0) % 24, p.minute ?? 0, p.second ?? 0, ((instant % 1000) + 1000) % 1000)
}

const dayOf = (wall: number) => new Date(wall).toISOString().slice(0, 10)

export interface SiteClock {
  /** IANA zone of the site, when the server says. */
  tz?: string
  /** The site's calendar day now, "YYYY-MM-DD". */
  today: () => string
  /** The site's calendar day `ms` from now, counted on its wall clock (as the server adds hours). */
  dayAfter: (ms: number) => string
  /** Milliseconds until the site's next midnight (at least one second). */
  msToNextDay: () => number
}

/** The site clock for a bootstrap's `server` block, received at browser time `receivedAt`. */
export function siteClock(server: Bootstrap["server"], receivedAt: number): SiteClock {
  const tz = server?.time_zone || undefined
  const floor = server?.today && ISO_DAY.test(server.today) ? server.today : undefined
  const serverWall = server?.now ? wallMs(server.now) : null
  const f = tz ? zoneFormat(tz) : null
  const arrivedWall = f ? zoneWall(f, receivedAt) : null
  const skew = serverWall !== null && arrivedWall !== null ? serverWall - arrivedWall : null

  /** The site's wall clock now (digits read as UTC), or null without a server clock. */
  const wall = (): number | null => {
    const now = Date.now()
    if (f && skew !== null) {
      const w = zoneWall(f, now + skew)
      if (w !== null) return w
    }
    return serverWall !== null ? serverWall + (now - receivedAt) : null
  }
  const notBeforeFloor = (d: string) => (floor && d < floor ? floor : d)

  return {
    tz,
    today: () => {
      const w = wall()
      return w === null ? (floor ?? isoDay(new Date())) : notBeforeFloor(dayOf(w))
    },
    dayAfter: (ms) => {
      const w = wall()
      return w === null ? notBeforeFloor(isoDay(new Date(Date.now() + ms))) : notBeforeFloor(dayOf(w + ms))
    },
    msToNextDay: () => {
      const w = wall()
      return w === null ? HOUR_MS : Math.max(1000, DAY_MS - (((w % DAY_MS) + DAY_MS) % DAY_MS))
    },
  }
}

/** The site clock of this session: `today()` / `dayAfter()` at the moment they are called
 * (event handlers, form resets). Components that show "today" use `useSiteToday()`. */
export function useSiteClock(): SiteClock {
  const { boot } = useSession()
  const server = boot.server
  const arrived = boot.receivedAt
  return useMemo(() => siteClock(server, arrived ?? Date.now()), [server, arrived])
}

/** The site's today ("YYYY-MM-DD"); the component re-renders when the site's day changes
 * (its midnight, or a tab coming back after it). */
export function useSiteToday(): string {
  const clock = useSiteClock()
  const subscribe = useCallback(
    (notify: () => void) => {
      let timer = 0
      const arm = () => {
        // at the site's next midnight, and at least hourly (sleep and DST move wall clocks)
        timer = window.setTimeout(
          () => {
            notify()
            arm()
          },
          Math.min(clock.msToNextDay() + 250, HOUR_MS),
        )
      }
      const onVisible = () => {
        if (document.visibilityState === "visible") notify()
      }
      arm()
      document.addEventListener("visibilitychange", onVisible)
      return () => {
        window.clearTimeout(timer)
        document.removeEventListener("visibilitychange", onVisible)
      }
    },
    [clock],
  )
  return useSyncExternalStore(subscribe, clock.today)
}
