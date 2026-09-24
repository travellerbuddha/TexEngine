// "This hotel / all my hotels" for the cross-record lists (G-64). The server decides which
// hotels "all" means (those where the list's capability is held, kamra.tex.api.lists); the
// UI only offers the choice when there is more than one such hotel.
import { useCallback, useMemo, useState, type ReactNode } from "react"
import { useTexT } from "../i18n"
import { Segmented } from "../ui"
import { useSession } from "./session"

const KEY = "tex-list-scope"

function stored(): boolean {
  try {
    return localStorage.getItem(KEY) === "all"
  } catch {
    return false
  }
}

export interface HotelScope {
  /** The hotel to ask for, or undefined for every hotel where the capability is held. */
  property: string | undefined
  all: boolean
  /** The hotel's display name. */
  hotelName: (name: string | null | undefined) => string
  control: ReactNode
}

/** A hotel is listed where the user holds every one of `allOf` and, when given, one of
 * `anyOf` (pass module-level constants). */
export function useHotelScope(allOf: readonly string[], anyOf?: readonly string[]): HotelScope {
  const { t } = useTexT()
  const { boot, property, can } = useSession()
  const eligible = useMemo(
    () => boot.properties.filter((p) => allOf.every((c) => can(c, p.name)) && (!anyOf || anyOf.some((c) => can(c, p.name)))),
    [boot.properties, allOf, anyOf, can],
  )
  const [wantAll, setWantAll] = useState(stored)
  const all = wantAll && eligible.length > 1
  const set = useCallback((v: string) => {
    setWantAll(v === "all")
    try {
      localStorage.setItem(KEY, v)
    } catch {
      /* storage blocked */
    }
  }, [])
  const names = useMemo(() => new Map(boot.properties.map((p) => [p.name, p.property_name])), [boot.properties])
  const hotelName = useCallback((n: string | null | undefined) => (n ? (names.get(n) ?? n) : "—"), [names])
  const control =
    eligible.length > 1 ? (
      <Segmented
        label={t("core.scope.label")}
        value={all ? "all" : "hotel"}
        onChange={set}
        options={[
          { value: "hotel", label: t("core.scope.this_hotel") },
          { value: "all", label: t("core.scope.all_hotels", { count: eligible.length }) },
        ]}
      />
    ) : null
  return { property: all ? undefined : property?.name, all, hotelName, control }
}
