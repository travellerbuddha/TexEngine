import { Fragment } from "react"
import { useTexT } from "../../../i18n"
import { Badge } from "../../../ui"
import { AuditValue } from "./JsonDiff"

type Pair = [unknown, unknown]

/** One collection of an audit event (ADR-053): the rows of a contract table, a section of a
 * published payload or the cells of an ARI bulk edit, each row named by its natural key. */
export interface CollectionChange {
  count?: [number, number]
  totals?: { added?: number; removed?: number; changed?: number }
  added?: string[]
  removed?: string[]
  changed?: Record<string, Record<string, Pair>>
  changed_keys?: string[]
  fields?: Record<string, Pair>
  unchanged?: number
  old_values?: Record<string, Record<string, number>>
}

export type Collections = Record<string, CollectionChange>

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v)
}

/** Split an audit value into its plain fields and its `collections` (shown by
 * {@link CollectionChanges}); the plain fields keep the old / new viewer. */
export function splitCollections(value: unknown): { rest: unknown; collections: Collections | null } {
  if (!isRecord(value) || !isRecord(value.collections)) return { rest: value, collections: null }
  const { collections, ...rest } = value
  const found = collections as Collections
  return { rest: Object.keys(rest).length ? rest : null, collections: Object.keys(found).length ? found : null }
}

function KeyList({ label, keys, total, tone }: { label: string; keys: string[]; total: number; tone: "success" | "danger" | "neutral" }) {
  const { t } = useTexT()
  const more = total - keys.length
  return (
    <div className="flex flex-wrap items-baseline gap-1.5 text-xs">
      <Badge tone={tone}>{label}</Badge>
      {keys.map((k) => (
        <span key={k} className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[11px] text-zinc-800">
          {k}
        </span>
      ))}
      {more > 0 && <span className="text-zinc-500">{t("settings.audit.coll.more", { count: more })}</span>}
    </div>
  )
}

function PairTable({ rows, keyLabel }: { rows: [string, string, Pair][]; keyLabel?: string }) {
  const { t } = useTexT()
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-zinc-500">
            {keyLabel && (
              <th scope="col" className="py-1 pr-3 font-medium">
                {keyLabel}
              </th>
            )}
            <th scope="col" className="py-1 pr-3 font-medium">
              {t("settings.audit.field")}
            </th>
            <th scope="col" className="py-1 pr-3 font-medium">
              {t("settings.audit.old")}
            </th>
            <th scope="col" className="py-1 font-medium">
              {t("settings.audit.new")}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([key, field, [before, after]], i) => (
            <tr key={`${key}|${field}`} className="border-t border-zinc-100 align-top">
              {keyLabel && (
                <th scope="row" className="py-1.5 pr-3 text-left font-mono text-xs font-medium text-zinc-700">
                  {i === 0 || rows[i - 1][0] !== key ? key : ""}
                </th>
              )}
              <td className="py-1.5 pr-3 font-mono text-xs text-zinc-700">{field}</td>
              <td className="max-w-[16rem] py-1.5 pr-3">
                <AuditValue v={before ?? null} />
              </td>
              <td className="max-w-[16rem] py-1.5">
                <AuditValue v={after ?? null} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** What happened to each collection of an audit event: counts, added and removed rows by
 * key, changed rows field by field (old → new), and for bulk edits the values before. */
export function CollectionChanges({ collections }: { collections: Collections }) {
  const { t } = useTexT()
  const label = (name: string) => {
    const key = `settings.audit.coll.name.${name}`
    const s = t(key)
    return s === key ? name : s
  }
  return (
    <div className="space-y-4">
      {Object.entries(collections).map(([name, c]) => {
        const totals = c.totals ?? {}
        const changedRows: [string, string, Pair][] = Object.entries(c.changed ?? {}).flatMap(([key, fields]) =>
          Object.entries(fields).map(([f, pair]) => [key, f, pair] as [string, string, Pair]),
        )
        const moreChanged = (totals.changed ?? 0) - Object.keys(c.changed ?? {}).length - (c.changed_keys?.length ?? 0)
        return (
          <section key={name} className="space-y-2 rounded-md border border-zinc-200 bg-white p-3">
            <h4 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-zinc-800">
              {label(name)}
              {c.count && c.count[0] !== c.count[1] && (
                <span className="text-xs font-normal text-zinc-500 tabular-nums">{t("settings.audit.coll.rows", { before: c.count[0], after: c.count[1] })}</span>
              )}
              {(totals.changed ?? 0) > 0 && <Badge tone="warning">{t("settings.audit.coll.changed", { count: totals.changed ?? 0 })}</Badge>}
              {(c.unchanged ?? 0) > 0 && <Badge tone="neutral">{t("settings.audit.coll.unchanged", { count: c.unchanged ?? 0 })}</Badge>}
            </h4>
            {c.fields && <PairTable rows={Object.entries(c.fields).map(([f, pair]) => ["", f, pair] as [string, string, Pair])} />}
            {!!c.added?.length && <KeyList label={t("settings.audit.coll.added", { count: totals.added ?? c.added.length })} keys={c.added} total={totals.added ?? c.added.length} tone="success" />}
            {!!c.removed?.length && <KeyList label={t("settings.audit.coll.removed", { count: totals.removed ?? c.removed.length })} keys={c.removed} total={totals.removed ?? c.removed.length} tone="danger" />}
            {changedRows.length > 0 && <PairTable rows={changedRows} keyLabel={t("settings.audit.coll.row")} />}
            {!!c.changed_keys?.length && <KeyList label={t("settings.audit.coll.also_changed")} keys={c.changed_keys} total={c.changed_keys.length + Math.max(moreChanged, 0)} tone="neutral" />}
            {c.old_values && (
              <div className="text-xs text-zinc-600">
                <p className="mb-1 font-medium text-zinc-700">{t("settings.audit.coll.previous_values")}</p>
                <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5">
                  {Object.entries(c.old_values).map(([field, counts]) => (
                    <Fragment key={field}>
                      <dt className="font-mono">{field}</dt>
                      <dd className="tabular-nums">
                        {Object.entries(counts)
                          .map(([v, n]) => `${v === "" ? t("settings.audit.empty_value") : v} × ${n}`)
                          .join(" · ")}
                      </dd>
                    </Fragment>
                  ))}
                </dl>
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}
