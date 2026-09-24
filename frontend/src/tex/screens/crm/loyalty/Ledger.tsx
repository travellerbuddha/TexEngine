import { useId, useState } from "react"
import { Link } from "react-router-dom"
import { ListTree } from "lucide-react"
import { useTexQuery } from "../../../lib/api"
import { dateTime, date as fmtDate, num } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, EmptyState, ErrorState, Field, Select, Skeleton, statusTone } from "../../../ui"
import { Pager } from "../components/common"
import { safeJson } from "../lib"
import { LEDGER_TYPES, type LedgerPage, type LedgerRow } from "../types"
import { basisKey, decimalText } from "./lib"

const PAGE = 25
const entryKey = (e: string) => `crm.loyalty.entry.${e.toLowerCase()}`
const statusKey = (s: string) => `crm.loyalty.status.${s.toLowerCase()}`

interface Explanation {
  lines?: { rule?: string; rate?: string; points?: string | number; note?: string }[]
  tier?: string | null
  multiplier?: string | number | null
}

/** The stored explanation of an earning: which rules applied, the tier multiplier, rounding. */
function ExplanationView({ raw }: { raw: string }) {
  const { t } = useTexT()
  const ex = safeJson<Explanation | null>(raw, null)
  if (!ex || !Array.isArray(ex.lines)) return null
  const ruleLabel = (r?: string) => {
    if (!r) return "—"
    if (r === "BLACKOUT") return t("crm.ledger.blackout")
    const k = basisKey(r)
    const v = t(k)
    return v === k ? r : v
  }
  const mult = decimalText(String(ex.multiplier ?? "1"))
  return (
    <details className="group mt-2 rounded-md border border-zinc-200 bg-zinc-50/70 text-xs">
      <summary className="cursor-pointer px-2.5 py-1.5 font-medium text-tex-700 select-none hover:underline focus-visible:ring-2 focus-visible:ring-tex-500/40 focus-visible:outline-none">
        {t("crm.ledger.explain")}
      </summary>
      <div className="space-y-2 border-t border-zinc-200 px-2.5 py-2">
        {ex.lines.length ? (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left">
              <caption className="sr-only">{t("crm.ledger.explain")}</caption>
              <thead>
                <tr className="text-zinc-500">
                  <th scope="col" className="py-0.5 pr-3 font-medium">
                    {t("crm.ledger.col.rule")}
                  </th>
                  <th scope="col" className="py-0.5 pr-3 text-right font-medium">
                    {t("crm.ledger.col.rate")}
                  </th>
                  <th scope="col" className="py-0.5 text-right font-medium">
                    {t("crm.loyalty.col.points")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {ex.lines.map((l, i) => (
                  <tr key={i} className="align-top text-zinc-800">
                    <td className="py-0.5 pr-3">
                      {ruleLabel(l.rule)}
                      {l.note && <span className="block text-zinc-500">{l.note}</span>}
                    </td>
                    <td className="py-0.5 pr-3 text-right tabular-nums">{l.rate !== undefined ? decimalText(String(l.rate)) : "—"}</td>
                    <td className="py-0.5 text-right tabular-nums">{l.points !== undefined ? decimalText(String(l.points)) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-zinc-600">{t("crm.ledger.no_lines")}</p>
        )}
        <p className="text-zinc-700">{ex.tier ? t("crm.ledger.tier", { tier: ex.tier, multiplier: mult }) : t("crm.ledger.no_tier", { multiplier: mult })}</p>
        <p className="text-zinc-500">{t("crm.ledger.rounded")}</p>
      </div>
    </details>
  )
}

function Entry({ r }: { r: LedgerRow }) {
  const { t } = useTexT()
  const tone = r.status === "Available" ? "success" : r.status === "Pending" ? "warning" : statusTone(r.status)
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-sm font-medium text-zinc-900">{t(entryKey(r.entry_type))}</span>
        <span className={r.points < 0 ? "text-sm font-semibold text-rose-700 tabular-nums" : "text-sm font-semibold text-emerald-700 tabular-nums"}>
          {r.points > 0 ? "+" : ""}
          {num(r.points)}
        </span>
        <Badge tone={tone}>{t(statusKey(r.status))}</Badge>
        <span className="ml-auto text-xs text-zinc-500">{dateTime(r.creation)}</span>
      </div>
      <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-zinc-600">
        {r.guest ? (
          <Link to={`/tex/crm/guests/${encodeURIComponent(r.guest)}`} className="font-medium text-tex-700 hover:underline">
            {r.guest_name || r.guest}
          </Link>
        ) : (
          <span className="italic">{t("crm.ledger.guest_elsewhere")}</span>
        )}
        {r.other_hotel && <span className="italic">{t("crm.loyalty.other_hotel")}</span>}
        {r.booking && (
          <Link to={`/tex/reservations/booking/${encodeURIComponent(r.booking)}`} className="text-tex-700 hover:underline">
            {t("crm.loyalty.booking")} {r.booking}
          </Link>
        )}
        {r.status === "Pending" && r.available_on ? (
          <span>{t("crm.loyalty.available_on", { date: fmtDate(r.available_on) })}</span>
        ) : r.expires_on ? (
          <span>{t("crm.loyalty.expires_on", { date: fmtDate(r.expires_on) })}</span>
        ) : null}
        {r.actor && <span>{t("crm.ledger.by", { actor: r.actor })}</span>}
      </p>
      {r.reason && <p className="mt-1 text-xs break-words text-zinc-600">{r.reason}</p>}
      {r.explanation && <ExplanationView raw={r.explanation} />}
    </li>
  )
}

/** Paged ledger of one program, newest first, filterable by entry type. */
export function Ledger({ program, programName }: { program: string; programName: string }) {
  const { t } = useTexT()
  const [type, setType] = useState("")
  const [start, setStart] = useState(0)
  const listId = useId()
  const q = useTexQuery<LedgerPage>(
    "loyalty",
    "ledger",
    { name: program, entry_type: type || undefined, start, limit: PAGE },
    [program, type, start],
  )
  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-zinc-100 px-4 py-3">
        <div className="min-w-0">
          <h2 id={listId} className="text-sm font-semibold text-zinc-900">
            {t("crm.ledger.caption", { program: programName })}
          </h2>
          <p className="text-xs text-zinc-500">{t("crm.ledger.hint")}</p>
        </div>
        <Field label={t("crm.ledger.filter")} className="w-full sm:w-48">
          <Select
            value={type}
            onChange={(e) => {
              setType(e.target.value)
              setStart(0)
            }}
            options={[{ value: "", label: t("crm.ledger.all") }, ...LEDGER_TYPES.map((x) => ({ value: x, label: t(entryKey(x)) }))]}
          />
        </Field>
      </div>
      {q.error ? (
        <ErrorState error={q.error} onRetry={q.reload} />
      ) : !q.data ? (
        <div className="space-y-2 p-4" aria-busy="true">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : q.data.rows.length === 0 ? (
        <EmptyState icon={<ListTree className="size-5" />} title={t("crm.ledger.empty")} description={type ? undefined : t("crm.ledger.empty_hint")} />
      ) : (
        <>
          <ul aria-labelledby={listId} aria-busy={q.loading || undefined} className="divide-y divide-zinc-100">
            {q.data.rows.map((r) => (
              <Entry key={r.name} r={r} />
            ))}
          </ul>
          <Pager start={start} pageSize={PAGE} total={q.data.total} onChange={setStart} />
        </>
      )}
    </div>
  )
}
