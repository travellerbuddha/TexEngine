// Room parties, board labels and small display helpers shared by the CRS, Call
// Center and Reservations screens. No money arithmetic lives here.

export const MAX_ROOMS = 8
export const MAX_ADULTS = 12
export const MAX_CHILDREN = 8
export const CHILD_AGES = Array.from({ length: 18 }, (_, i) => i)

export interface PartyForm {
  adults: number
  /** One entry per child; null until the agent picks the age (never guessed). */
  children: (number | null)[]
}

export const BOARDS = ["RO", "BB", "HB", "FB", "AI", "UAI"] as const

/** i18n key of a board code (unknown codes fall back to the code itself). */
export function boardKey(code: string | null | undefined) {
  return code && (BOARDS as readonly string[]).includes(code) ? `crs.board.${code}` : null
}

export function partyComplete(p: PartyForm) {
  return p.adults >= 1 && p.children.every((a) => a !== null)
}

export function partyToApi(p: PartyForm) {
  return { adults: p.adults, children: p.children.map((a) => ({ age: a as number })) }
}

/** Compare two decimal strings exactly (display ordering only). */
export function cmpDecimal(a: string | null | undefined, b: string | null | undefined): number {
  const pa = parse(a)
  const pb = parse(b)
  if (!pa && !pb) return 0
  if (!pa) return 1
  if (!pb) return -1
  const scale = Math.max(pa.frac.length, pb.frac.length)
  const x = BigInt((pa.neg ? "-" : "") + pa.int + pa.frac.padEnd(scale, "0"))
  const y = BigInt((pb.neg ? "-" : "") + pb.int + pb.frac.padEnd(scale, "0"))
  return x === y ? 0 : x < y ? -1 : 1
}

function parse(s: string | null | undefined) {
  if (s === null || s === undefined) return null
  const m = /^\s*([-+]?)(\d+)(?:\.(\d+))?\s*$/.exec(String(s))
  if (!m) return null
  return { neg: m[1] === "-", int: m[2], frac: m[3] ?? "" }
}

/** True when a decimal string is strictly positive. */
export function isPositive(s: string | null | undefined) {
  return cmpDecimal(s, "0") > 0
}

export function isZero(s: string | null | undefined) {
  return cmpDecimal(s, "0") === 0
}

export function offerId(o: { room_type: string; board: string; rate_plan: string | null; contract: string }) {
  return `${o.contract}|${o.room_type}|${o.board}|${o.rate_plan ?? ""}`
}

/** "Aurora Beach Resort-STD" → "STD" when no display name is known. */
export function shortCode(name: string, property?: string) {
  if (property && name.startsWith(`${property}-`)) return name.slice(property.length + 1)
  return name
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // clipboard API blocked (insecure origin, permissions): fall back to a selection copy
    const ta = document.createElement("textarea")
    ta.value = text
    ta.setAttribute("readonly", "")
    ta.style.position = "fixed"
    ta.style.opacity = "0"
    document.body.appendChild(ta)
    ta.select()
    let ok = false
    try {
      ok = document.execCommand("copy")
    } catch {
      ok = false
    }
    document.body.removeChild(ta)
    return ok
  }
}
