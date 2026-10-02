// Promotions as staff read them (UX revision 2026-10): where a promotion stands (draft, scheduled,
// on sale, ended), what it covers, which date ranges are back to front, and what a copy starts
// from. Pure: no runtime imports, no money arithmetic (amounts stay the decimal text stored);
// tested with `node --test` (tests/unit/promotions.test.ts).

export type Doc = Record<string, unknown>

const s = (v: unknown) => (v === null || v === undefined ? "" : String(v).trim())

/** "DE,UK" → ["DE", "UK"]. */
export function csv(v: unknown): string[] {
  return s(v)
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)
}

export type PromoState = "draft" | "scheduled" | "live" | "ended" | "superseded" | "archived"

/**
 * Where a promotion stands for a guest booking today (`today`: the site's date, `now`: its time,
 * both ISO): a revision not yet active is a draft; an active one whose start is still to come is
 * scheduled; one whose sale or stay window has passed has ended (still "Active" in its lifecycle,
 * but it applies to nothing any more); otherwise it is on sale.
 */
export function promoState(d: Doc, today: string, now: string): PromoState {
  const st = s(d.tex_status)
  if (st === "Draft" || !st) return "draft"
  if (st === "Archived") return "archived"
  if (st === "Superseded") return "superseded"
  const from = s(d.active_from)
  if (from && from.replace("T", " ") > now.replace("T", " ")) return "scheduled"
  const saleTo = s(d.sale_to)
  const stayTo = s(d.stay_to)
  if ((saleTo && saleTo < today) || (stayTo && stayTo < today)) return "ended"
  return "live"
}

/** The date pairs of a promotion whose end is before its start (the save is refused on them). */
export const PROMO_RANGES: [string, string][] = [
  ["sale_from", "sale_to"],
  ["stay_from", "stay_to"],
]

export function backToFront(d: Doc, ranges: readonly [string, string][] = PROMO_RANGES): string[] {
  const out: string[] = []
  for (const [a, b] of ranges) {
    const x = s(d[a])
    const y = s(d[b])
    if (x && y && y < x) out.push(b)
  }
  return out
}

/** Every market, channel and room open: the promotion applies to all of them. */
export function coversEverything(d: Doc): boolean {
  return !csv(d.markets).length && !csv(d.channels).length && !csv(d.room_types).length
}

/** Fields a copy never takes over: identity, lifecycle, use counts, and the coupon code (a code
 * names one promotion). */
const NOT_COPIED = new Set(["name", "tex_status", "revision_no", "revision_of", "active_from", "active_to", "times_redeemed", "code", "modified", "creation", "owner", "modified_by", "_warnings"])

/** A new record from `src` ("Create similar"): its terms, without what identifies it, the title
 * marked as a copy (`copyTitle`). */
export function copyOf(src: Doc, titleField: string, copyTitle: (title: string) => string): Doc {
  const out: Doc = {}
  for (const [k, v] of Object.entries(src)) if (!NOT_COPIED.has(k)) out[k] = v
  out[titleField] = copyTitle(s(src[titleField]))
  return out
}
