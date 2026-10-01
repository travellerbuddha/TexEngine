// Capability grouping for the permission-profile matrix. The registry itself comes
// from the server (admin.profiles → capabilities); unknown codes land in "other".

export const CAP_GROUPS: { id: string; caps: string[] }[] = [
  { id: "pricing", caps: ["price.view", "price.view_cost", "price.override", "price.any_channel", "contract.edit", "contract.publish", "promotion.edit", "markup.edit", "fx.edit", "fx.manual_rate", "tax.edit"] },
  { id: "inventory", caps: ["inventory.edit", "restriction.edit"] },
  { id: "reservations", caps: ["reservation.view", "reservation.create", "reservation.modify", "reservation.cancel"] },
  { id: "payments", caps: ["payment.view", "payment.link", "payment.refund"] },
  { id: "guests", caps: ["crm.view", "crm.edit", "guest.export", "loyalty.edit"] },
  { id: "distribution", caps: ["report.view", "booking_site.edit", "connect.admin"] },
  { id: "admin", caps: ["settings.admin", "user.admin", "system.monitor"] },
]

/** Prices and books on every sales channel, whatever the profile's channel list (ADR-050). */
export const ANY_CHANNEL = "price.any_channel"

/** Where a profile's holders price and book (ADR-050): every channel with price.any_channel,
 * else its channel list, else the call centre. `label` translates a channel code. */
export function channelSummary(
  t: (k: string) => string,
  label: (code: string) => string,
  p: { capabilities: string[]; sales_channels?: string[] },
) {
  if (p.capabilities.includes(ANY_CHANNEL)) return t("settings.profiles.channels_all")
  if (p.sales_channels?.length) return p.sales_channels.map(label).join(", ")
  return t("settings.profiles.channels_default")
}

/** Capabilities that expose secrets, money movements or other people's access. */
export const SENSITIVE = new Set([
  "price.view_cost",
  "price.override",
  "price.any_channel",
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
