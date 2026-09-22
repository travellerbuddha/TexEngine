// Plain-text quote an agent can read to (or paste for) the caller. Every amount is
// the server's; this only lays the figures out in words.
import { date, dateTime, money } from "../../../lib/format"
import type { Params } from "../../../i18n"
import type { PropertyResult, QuoteResult, QuoteSummary, SearchResult } from "./types"
import { shortCode } from "./party"

type T = (key: string, params?: Params) => string

export function quoteText(opts: {
  t: T
  board: (code: string) => string
  method: (m: string) => string
  result: SearchResult
  prop: PropertyResult | undefined
  quotes: QuoteResult[]
  summary: QuoteSummary | undefined
  paymentMethod: string
  partyText: (adults: number, ages: (number | null)[]) => string
}): string {
  const { t, board, result, prop, quotes, summary, paymentMethod, partyText } = opts
  const lines: string[] = []
  lines.push(
    `${prop?.property_name ?? quotes[0]?.quote?.request.property ?? ""} · ${date(result.check_in)} – ${date(result.check_out)} (${t("core.label.nights", {
      count: result.nights,
    })})`,
  )
  quotes.forEach((q, i) => {
    const party = result.rooms[i]
    const who = party ? partyText(party.adults, party.children.map((c) => c.age)) : ""
    if (!q.ok || !q.quote) {
      lines.push(`${t("crs.room_n", { n: i + 1 })}: ${(q.reasons ?? []).map((r) => r.message).join("; ")}`)
      return
    }
    const qd = q.quote
    const room = prop?.rooms?.[qd.request.room_type]?.name ?? shortCode(qd.request.room_type, qd.request.property)
    const plan = qd.rate_plan?.name ? `, ${qd.rate_plan.name}` : ""
    lines.push(`${t("crs.room_n", { n: i + 1 })} — ${room}, ${board(qd.request.board)}${plan} · ${who}: ${money(qd.totals.total, qd.currency)}`)
    const extras = qd.lines.filter((l) => l.kind === "EXTRA")
    if (extras.length) lines.push(`  ${t("crs.text.extras")}: ${extras.map((l) => `${l.description} ${money(l.amount, qd.currency)}`).join(", ")}`)
    const disc = qd.lines.filter((l) => l.kind === "DISCOUNT" || l.kind === "COUPON")
    if (disc.length) lines.push(`  ${t("crs.text.discounts")}: ${disc.map((l) => `${l.description} ${money(l.amount, qd.currency)}`).join(", ")}`)
    const cp = qd.rate_plan?.cancellation_policy
    if (cp?.description || cp?.name) lines.push(`  ${t("crs.policy.cancellation")}: ${cp.description || cp.name}`)
  })
  if (summary) {
    const due =
      paymentMethod && summary.due_now !== null
        ? ` · ${t("crs.text.due_now", { amount: money(summary.due_now, summary.currency), method: opts.method(paymentMethod) })}`
        : ""
    lines.push(`${t("crs.text.total")}: ${money(summary.total, summary.currency)}${due}`)
    lines.push(t("crs.text.valid_until", { time: dateTime(summary.expires_at) }))
  }
  return lines.join("\n")
}
