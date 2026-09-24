// TEX session: who am I, which hotels, what may I do there (kamra.tex.api.session.bootstrap).
// The UI uses capabilities only to decide what to show — every endpoint re-checks.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react"
import { tex, TexApiError } from "./api"

export interface TexProperty {
  name: string
  property_name: string
  city?: string
  country?: string
  currency?: string
  hotel_group?: string
  enterprise?: string
  default_market?: string
  capabilities: string[]
  /** Sales channels the user may price on (search) at this hotel (ADR-050). The server
   * re-checks the channel of every search, quote and booking. */
  sales_channels?: string[]
  /** Sales channels the user may quote and book on at this hotel (ADR-050 review). */
  booking_channels?: string[]
}

export interface Bootstrap {
  user: { name: string; full_name: string; roles: string[]; platform_admin: boolean }
  properties: TexProperty[]
  capabilities: Record<string, string>
  settings: { brand_name: string; show_legacy_pms: boolean; default_market?: string; default_sales_channel?: string }
  markets: { name: string; market_name: string; is_global: number; default_currency?: string; countries?: string }[]
  channels: { name: string; channel_name: string; channel_group?: string }[]
  currencies: string[]
  /** Server wall clock: datetimes from the API are naive times in `time_zone`; `today` is the
   * site's calendar day when `now` was read (staff "today" comes from it: lib/siteDay). */
  server?: { time_zone: string; now: string; today: string }
  /** Browser clock (ms) when this bootstrap arrived: server offset = server.now − receivedAt. */
  receivedAt?: number
}

interface SessionValue {
  boot: Bootstrap
  property: TexProperty | undefined
  setProperty: (name: string) => void
  /** Capability at the selected hotel (or at `propertyName`). */
  can: (cap: string, propertyName?: string) => boolean
  /** Capability at any hotel in scope. */
  canAnywhere: (cap: string) => boolean
  reload: () => Promise<void>
}

const Ctx = createContext<SessionValue | null>(null)
const KEY = "tex-property"

export function useSession(): SessionValue {
  const v = useContext(Ctx)
  if (!v) throw new Error("useSession must be used inside <TexSessionProvider>")
  return v
}

/** Convenience: the selected hotel's name (every hotel-bound screen needs it). */
export function useProperty(): string | undefined {
  return useSession().property?.name
}

export function TexSessionProvider({
  children,
  fallback,
  onError,
}: {
  children: ReactNode
  fallback: ReactNode
  onError: (e: TexApiError) => ReactNode
}) {
  const [boot, setBoot] = useState<Bootstrap>()
  const [error, setError] = useState<TexApiError>()
  const [selected, setSelected] = useState<string | undefined>(() => {
    try {
      return localStorage.getItem(KEY) ?? undefined
    } catch {
      return undefined
    }
  })

  const load = useCallback(async () => {
    try {
      const b = await tex<Bootstrap>("session", "bootstrap")
      setBoot({ ...b, receivedAt: Date.now() })
      setError(undefined)
    } catch (e) {
      setError(e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error"))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const value = useMemo<SessionValue | null>(() => {
    if (!boot) return null
    const property = boot.properties.find((p) => p.name === selected) ?? boot.properties[0]
    const byName = new Map(boot.properties.map((p) => [p.name, p]))
    return {
      boot,
      property,
      setProperty: (name: string) => {
        setSelected(name)
        try {
          localStorage.setItem(KEY, name)
        } catch {
          /* ignore */
        }
      },
      can: (cap, propertyName) => {
        const p = propertyName ? byName.get(propertyName) : property
        return Boolean(p?.capabilities.includes(cap))
      },
      canAnywhere: (cap) => boot.properties.some((p) => p.capabilities.includes(cap)),
      reload: load,
    }
  }, [boot, selected, load])

  if (error) return <>{onError(error)}</>
  if (!value) return <>{fallback}</>
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
