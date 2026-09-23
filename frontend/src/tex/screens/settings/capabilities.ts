// Capability grouping for the permission-profile matrix. The registry itself comes
// from the server (admin.profiles → capabilities); unknown codes land in "other".

export const CAP_GROUPS: { id: string; caps: string[] }[] = [
  { id: "pricing", caps: ["price.view", "price.view_cost", "price.override", "contract.edit", "contract.publish", "promotion.edit", "markup.edit", "fx.edit", "tax.edit"] },
  { id: "inventory", caps: ["inventory.edit", "restriction.edit"] },
  { id: "reservations", caps: ["reservation.view", "reservation.create", "reservation.modify", "reservation.cancel"] },
  { id: "payments", caps: ["payment.view", "payment.link", "payment.refund"] },
  { id: "guests", caps: ["crm.view", "crm.edit", "guest.export", "loyalty.edit"] },
  { id: "distribution", caps: ["report.view", "booking_site.edit", "connect.admin"] },
  { id: "admin", caps: ["settings.admin", "user.admin"] },
]

/** Capabilities that expose secrets, money movements or other people's access. */
export const SENSITIVE = new Set([
  "price.view_cost",
  "price.override",
  "contract.publish",
  "payment.refund",
  "guest.export",
  "connect.admin",
  "settings.admin",
  "user.admin",
])

export function groupCapabilities(all: string[]): { id: string; caps: string[] }[] {
  const known = new Set(CAP_GROUPS.flatMap((g) => g.caps))
  const groups = CAP_GROUPS.map((g) => ({ id: g.id, caps: g.caps.filter((c) => all.includes(c)) })).filter((g) => g.caps.length)
  const other = all.filter((c) => !known.has(c)).sort()
  if (other.length) groups.push({ id: "other", caps: other })
  return groups
}

/** Translated capability label, falling back to the server's English description. */
export function capLabel(t: (k: string) => string, code: string, serverDescription?: string) {
  const key = `settings.cap.${code}`
  const v = t(key)
  return v === key ? serverDescription || code : v
}

export const SCOPE_LEVELS = ["Hotel", "Hotel Group", "Enterprise", "Platform"] as const
export type ScopeLevel = (typeof SCOPE_LEVELS)[number]

export function scopeKey(level: string) {
  return `settings.scope.${level.toLowerCase().replace(/\s+/g, "_")}`
}
