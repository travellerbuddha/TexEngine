// Residents-only markets (O-8, ADR-070, D-5): a market whose web prices are for guests whose country of residence
// or nationality is one of its countries (TR, the domestic market). The booking engine's checkout and the Call
// Center ask for them up front; the server decides (create_booking), and a mismatch there is refused (the Call
// Center may book anyway with a reason). Pure: no DOM, no React.

/** What the server says of a residents-only market's prices (`search.residency`, `basket.residency`). */
export interface Residency {
  countries: string[]
}

/** The ISO 3166-1 alpha-2 code of a country given as a code or by one of `names` (code → name, any case); null for
 * anything else (a CRM profile's nationality defaults to "Indian", which is no country). */
export function isoCountry(value: string | null | undefined, names: Record<string, string>): string | null {
  const v = (value ?? "").trim()
  if (!v) return null
  if (/^[A-Za-z]{2}$/.test(v)) return v.toUpperCase()
  const lower = v.toLocaleLowerCase("en")
  const hit = Object.entries(names).find(([, name]) => name.toLocaleLowerCase("en") === lower)
  return hit ? hit[0] : null
}

/** A market's countries from its comma-separated list (TEX Market.countries), upper case and sorted. */
export function marketCountries(csv: string | null | undefined): string[] {
  return [...new Set((csv ?? "").split(/[,\n]/).map((c) => c.trim().toUpperCase()).filter(Boolean))].sort()
}

/** Whether a guest of this residence or nationality may book a market for residents of `countries`. */
export function qualifies(countries: readonly string[], country?: string | null, nationality?: string | null): boolean {
  const set = new Set(countries.map((c) => c.toUpperCase()))
  return [country, nationality].some((c) => !!c && set.has(c.trim().toUpperCase()))
}

export type ResidencyProblem = "required" | "not_eligible" | null

/** What the booking engine's details form says of the guest's declared residence for a residents-only market's
 * prices: the country of residence is required; residence or nationality must be among the market's countries.
 * Any other market asks nothing (the country stays optional). */
export function residencyProblem(
  residency: Residency | null | undefined,
  country?: string | null,
  nationality?: string | null,
): ResidencyProblem {
  if (!residency) return null
  if (!country) return "required"
  return qualifies(residency.countries, country, nationality) ? null : "not_eligible"
}

/** The market's countries for a sentence, each by `display` (e.g. Intl.DisplayNames#of in the guest's language),
 * else by its code. */
export function countryNames(codes: readonly string[], display: (code: string) => string | undefined): string {
  return codes.map((c) => display(c) || c).join(", ")
}

/** `Intl.DisplayNames` for regions in `locale`, safe on engines without it (no name: undefined). */
export function regionDisplay(locale: string): (code: string) => string | undefined {
  let names: Intl.DisplayNames | null = null
  try {
    names = new Intl.DisplayNames([locale], { type: "region" })
  } catch {
    /* old engines */
  }
  return (code) => {
    try {
      return names?.of(code) ?? undefined
    } catch {
      return undefined
    }
  }
}
