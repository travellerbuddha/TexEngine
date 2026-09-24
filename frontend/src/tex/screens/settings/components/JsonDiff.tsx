import { useMemo, useState } from "react"
import { cn } from "../../../../lib/utils"
import { useTexT } from "../../../i18n"
import { Badge, Button, type Tone } from "../../../ui"

type Kind = "added" | "removed" | "changed" | "same"

interface DiffRow {
  key: string
  kind: Kind
  before: unknown
  after: unknown
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v)
}

function same(a: unknown, b: unknown) {
  return JSON.stringify(a) === JSON.stringify(b)
}

/** Key-level diff of two audit payloads (old_value / new_value). */
export function diffObjects(before: unknown, after: unknown): DiffRow[] | null {
  if (!isObject(before) && !isObject(after)) return null
  const a = isObject(before) ? before : {}
  const b = isObject(after) ? after : {}
  const keys = [...Object.keys(a), ...Object.keys(b).filter((k) => !(k in a))]
  return keys.map((key) => {
    const inA = key in a
    const inB = key in b
    const kind: Kind = !inA ? "added" : !inB ? "removed" : same(a[key], b[key]) ? "same" : "changed"
    return { key, kind, before: a[key], after: b[key] }
  })
}

/** One audit value: blank, a scalar, or pretty-printed JSON. */
export function AuditValue({ v }: { v: unknown }) {
  const { t } = useTexT()
  if (v === undefined) return <span className="text-zinc-400">—</span>
  if (v === null || v === "") return <span className="text-zinc-400 italic">{t("settings.audit.empty_value")}</span>
  if (typeof v === "object")
    return (
      <pre className="max-h-48 overflow-auto rounded bg-zinc-50 px-2 py-1 font-mono text-[11px] leading-snug break-all whitespace-pre-wrap text-zinc-800">
        {JSON.stringify(v, null, 2)}
      </pre>
    )
  return <span className="font-mono text-xs break-all text-zinc-800">{String(v)}</span>
}

const TONE: Record<Kind, Tone> = { added: "success", removed: "danger", changed: "warning", same: "neutral" }

/** Old/new value viewer. Changes are labelled in text (not colour alone). */
export function JsonDiff({ before, after }: { before: unknown; after: unknown }) {
  const { t } = useTexT()
  const [showSame, setShowSame] = useState(false)
  const [raw, setRaw] = useState(false)
  const rows = useMemo(() => diffObjects(before, after), [before, after])
  const unchanged = rows?.filter((r) => r.kind === "same").length ?? 0
  const visible = rows?.filter((r) => showSame || r.kind !== "same") ?? []

  if (before == null && after == null) return <p className="text-sm text-zinc-500">{t("settings.audit.no_values")}</p>

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {rows && unchanged > 0 && !raw && (
          <Button variant="ghost" size="sm" aria-pressed={showSame} onClick={() => setShowSame((s) => !s)}>
            {showSame ? t("settings.audit.hide_unchanged") : t("settings.audit.show_unchanged", { count: unchanged })}
          </Button>
        )}
        <Button variant="ghost" size="sm" aria-pressed={raw} onClick={() => setRaw((s) => !s)}>
          {raw ? t("settings.audit.view_diff") : t("settings.audit.view_raw")}
        </Button>
      </div>
      {raw || !rows ? (
        <div className="grid gap-3 md:grid-cols-2">
          <div className="min-w-0">
            <p className="mb-1 text-xs font-medium text-zinc-500">{t("settings.audit.old")}</p>
            <AuditValue v={before ?? null} />
          </div>
          <div className="min-w-0">
            <p className="mb-1 text-xs font-medium text-zinc-500">{t("settings.audit.new")}</p>
            <AuditValue v={after ?? null} />
          </div>
        </div>
      ) : visible.length === 0 ? (
        <p className="text-sm text-zinc-500">{t("settings.audit.no_changes")}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <caption className="sr-only">{t("settings.audit.changes")}</caption>
            <thead>
              <tr className="text-left text-xs text-zinc-500">
                <th scope="col" className="py-1 pr-3 font-medium">
                  {t("settings.audit.field")}
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  {t("settings.audit.change")}
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
              {visible.map((r) => (
                <tr key={r.key} className={cn("border-t border-zinc-100 align-top", r.kind === "same" && "opacity-70")}>
                  <th scope="row" className="py-1.5 pr-3 text-left font-mono text-xs font-medium text-zinc-700">
                    {r.key}
                  </th>
                  <td className="py-1.5 pr-3">
                    <Badge tone={TONE[r.kind]}>{t(`settings.audit.kind.${r.kind}`)}</Badge>
                  </td>
                  <td className="max-w-[18rem] py-1.5 pr-3">
                    <AuditValue v={r.kind === "added" ? undefined : r.before} />
                  </td>
                  <td className="max-w-[18rem] py-1.5">
                    <AuditValue v={r.kind === "removed" ? undefined : r.after} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
