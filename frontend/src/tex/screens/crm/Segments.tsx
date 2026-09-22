import { useEffect, useMemo, useRef, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Calculator, Copy, Lock, Plus, Save, Users } from "lucide-react"
import { useTexMutation, useTexQuery } from "../../lib/api"
import { useProperty, useSession } from "../../lib/session"
import { dateTime, num } from "../../lib/format"
import { useTexT } from "../../i18n"
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  Field,
  InlineError,
  Input,
  Notice,
  PageHeader,
  Segmented,
  Skeleton,
  Textarea,
  useToast,
} from "../../ui"
import { cn } from "../../../lib/utils"
import { CrmNav } from "./components/common"
import { safeJson } from "./lib"
import { conditionError, MAX_CONDITIONS, normalizeRules, RuleBuilder } from "./segments/RuleBuilder"
import { SegmentExport } from "./segments/SegmentExport"
import type { Segment, SegmentRules, SegmentsResponse } from "./types"

interface Draft {
  name?: string
  segment_name: string
  description: string
  rules: SegmentRules
}

const EMPTY_RULES: SegmentRules = { match: "all", conditions: [] }

function draftOf(s: Segment | undefined): Draft {
  if (!s) return { segment_name: "", description: "", rules: { match: "all", conditions: [{ field: "stays", op: "gte", value: "2" }] } }
  const r = safeJson<SegmentRules>(s.rules_json, EMPTY_RULES)
  return {
    name: s.name,
    segment_name: s.segment_name,
    description: s.description ?? "",
    rules: { match: r.match === "any" ? "any" : "all", conditions: (r.conditions ?? []).map((c) => ({ ...c, value: typeof c.value === "number" ? String(c.value) : c.value })) },
  }
}

export default function Segments() {
  const { t } = useTexT()
  const property = useProperty()
  const { can, canAnywhere } = useSession()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const list = useTexQuery<SegmentsResponse>("crm", "segments", {}, [])
  const selected = params.get("s") ?? ""
  const isNew = params.get("new") === "1"
  const scopeAll = params.get("scope") === "all"
  const scopeProperty = scopeAll ? undefined : property
  const segments = list.data?.segments ?? []
  const current = segments.find((s) => s.name === selected)
  const canEdit = canAnywhere("crm.edit")
  const canExport = scopeAll ? false : can("guest.export")

  const [draft, setDraft] = useState<Draft>(() => draftOf(undefined))
  const [members, setMembers] = useState<{ count: number } | null>(null)
  const pendingCopy = useRef<Draft | null>(null)
  const save = useTexMutation<{ data: Record<string, unknown> }, { name: string }>("crm", "save_segment")
  const evaluate = useTexMutation<{ segment: string; property?: string }, { segment: string; members: number }>("crm", "evaluate_segment")

  // auto-select the first segment on wide screens only makes sense once loaded
  useEffect(() => {
    if (!list.data || isNew || selected) return
    if (list.data.segments.length) setParams({ s: list.data.segments[0].name, ...(scopeAll ? { scope: "all" } : {}) }, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list.data])

  useEffect(() => {
    const copy = pendingCopy.current
    pendingCopy.current = null
    setDraft(isNew ? (copy ?? draftOf(undefined)) : draftOf(current))
    setMembers(null)
    save.clearError()
    evaluate.clearError()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, isNew, current?.rules_json, current?.segment_name])

  const system = Boolean(current?.system_key) && !isNew
  const readOnly = !canEdit || system
  const fields = list.data?.fields ?? {}
  const ops = list.data?.ops ?? ({} as SegmentsResponse["ops"])
  const original = useMemo(() => (isNew ? null : draftOf(current)), [isNew, current])
  const dirty = !original || JSON.stringify(original) !== JSON.stringify(draft)
  const errors = draft.rules.conditions.map((c) => conditionError(c, fields[c.field], t)).filter(Boolean)
  const nameMissing = !draft.segment_name.trim()
  const canSave = !readOnly && dirty && !nameMissing && errors.length === 0 && draft.rules.conditions.length <= MAX_CONDITIONS

  const select = (patch: Record<string, string>) => {
    const next = new URLSearchParams()
    if (scopeAll) next.set("scope", "all")
    for (const [k, v] of Object.entries(patch)) if (v) next.set(k, v)
    setParams(next)
  }

  const runEvaluate = async (segment: string) => {
    try {
      const r = await evaluate.run({ segment, property: scopeProperty })
      setMembers({ count: r.members })
      list.reload()
    } catch {
      /* inline */
    }
  }

  const onSave = async () => {
    if (!canSave) return
    try {
      const r = await save.run({
        data: {
          name: draft.name,
          segment_name: draft.segment_name.trim(),
          description: draft.description.trim(),
          rules: normalizeRules(draft.rules, fields),
        },
      })
      toast.success(t("crm.seg.saved"))
      list.reload()
      select({ s: r.name })
      void runEvaluate(r.name)
    } catch {
      /* inline */
    }
  }

  const duplicate = () => {
    // consumed by the reset effect once the URL switched to ?new=1
    pendingCopy.current = { ...draft, name: undefined, segment_name: t("crm.seg.copy_of", { name: draft.segment_name }) }
    select({ new: "1" })
  }

  // member_count is only meaningful once the segment has been evaluated
  const memberCount = members?.count ?? (current && !isNew && current.last_evaluated ? current.member_count : null)
  // server time of the last count (the list reloads after every evaluation)
  const memberAt = current && !isNew ? current.last_evaluated : null

  return (
    <>
      <PageHeader
        title={t("crm.seg.title")}
        subtitle={t("crm.seg.subtitle")}
        crumbs={[{ label: t("core.nav.crm"), to: "/tex/crm" }, { label: t("crm.nav.segments") }]}
        actions={
          <>
            <Segmented<"hotel" | "all">
              label={t("crm.scope.label")}
              size="sm"
              value={scopeAll ? "all" : "hotel"}
              onChange={(v) => {
                const next = new URLSearchParams(params)
                if (v === "all") next.set("scope", "all")
                else next.delete("scope")
                setParams(next, { replace: true })
                setMembers(null)
              }}
              options={[
                { value: "hotel", label: t("crm.scope.hotel") },
                { value: "all", label: t("crm.scope.all") },
              ]}
            />
            {canEdit && (
              <Button icon={<Plus className="size-4" aria-hidden />} onClick={() => select({ new: "1" })}>
                {t("crm.seg.new")}
              </Button>
            )}
          </>
        }
      />
      <CrmNav />
      {list.error ? (
        <Card>
          <ErrorState error={list.error} onRetry={list.reload} />
        </Card>
      ) : (
        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
          <Card>
            <CardHeader title={t("crm.seg.list")} description={t("crm.seg.list_hint")} />
            {!list.data ? (
              <div className="space-y-2 p-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : segments.length === 0 ? (
              <EmptyState title={t("crm.seg.empty")} description={canEdit ? t("crm.seg.empty_hint") : undefined} />
            ) : (
              <ul className="divide-y divide-zinc-100" aria-label={t("crm.seg.list")}>
                {segments.map((s) => {
                  const active = s.name === selected && !isNew
                  return (
                    <li key={s.name}>
                      <button
                        type="button"
                        aria-current={active ? "true" : undefined}
                        onClick={() => select({ s: s.name })}
                        className={cn(
                          "flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left transition-colors",
                          active ? "bg-tex-50" : "hover:bg-zinc-50",
                        )}
                      >
                        <span className="min-w-0">
                          <span className={cn("block truncate text-sm font-medium", active ? "text-tex-800" : "text-zinc-900")}>{s.segment_name}</span>
                          <span className="block truncate text-xs text-zinc-500">
                            {s.last_evaluated ? t("crm.seg.evaluated_at", { date: dateTime(s.last_evaluated) }) : t("crm.seg.never_evaluated")}
                          </span>
                        </span>
                        <span className="flex shrink-0 items-center gap-1.5">
                          {s.system_key && (
                            <Badge tone="neutral" title={t("crm.seg.system_hint")}>
                              <Lock className="size-3" aria-hidden />
                              <span className="sr-only">{t("crm.seg.system")}</span>
                            </Badge>
                          )}
                          <Badge tone="info">
                            <Users className="size-3" aria-hidden />
                            {s.last_evaluated && s.member_count !== null ? num(s.member_count) : "—"}
                          </Badge>
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </Card>

          <div className="min-w-0 space-y-5">
            {!isNew && !current ? (
              list.data && (
                <Card>
                  <EmptyState title={segments.length ? t("crm.seg.pick") : t("crm.seg.empty")} />
                </Card>
              )
            ) : (
              <>
                <Card>
                  <CardHeader
                    title={isNew ? t("crm.seg.new_title") : draft.segment_name || current?.segment_name}
                    description={system ? t("crm.seg.system_hint") : readOnly ? t("crm.seg.readonly_hint") : t("crm.seg.editor_hint")}
                    actions={
                      <>
                        {system && <Badge tone="neutral">{t("crm.seg.system")}</Badge>}
                        {canEdit && !isNew && (
                          <Button variant="ghost" size="sm" icon={<Copy className="size-4" aria-hidden />} onClick={duplicate}>
                            {t("crm.seg.duplicate")}
                          </Button>
                        )}
                      </>
                    }
                  />
                  <CardBody className="space-y-4">
                    {!readOnly && (
                      <div className="grid gap-4 sm:grid-cols-2">
                        <Field label={t("crm.seg.name")} required error={nameMissing && draft.segment_name !== "" ? t("crm.edit.required") : undefined}>
                          <Input value={draft.segment_name} onChange={(e) => setDraft({ ...draft, segment_name: e.target.value })} maxLength={140} autoComplete="off" />
                        </Field>
                        <Field label={t("crm.seg.description")}>
                          <Textarea value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} rows={1} maxLength={500} />
                        </Field>
                      </div>
                    )}
                    {readOnly && draft.description && <p className="text-sm text-zinc-600">{draft.description}</p>}
                    <RuleBuilder rules={draft.rules} onChange={(r) => setDraft({ ...draft, rules: r })} fields={fields} ops={ops} readOnly={readOnly} />
                    <InlineError error={save.error} />
                    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-100 pt-4">
                      <div className="text-sm" aria-live="polite">
                        {isNew ? (
                          <span className="text-zinc-500">{t("crm.seg.save_to_count")}</span>
                        ) : (
                          <span className="inline-flex flex-wrap items-center gap-2">
                            <span className="font-semibold text-zinc-900">
                              {memberCount !== null && memberCount !== undefined ? t("crm.seg.members", { count: memberCount }) : t("crm.seg.members_unknown")}
                            </span>
                            {memberAt && <span className="text-xs text-zinc-500">{t("crm.seg.evaluated_at", { date: dateTime(memberAt) })}</span>}
                            {current && (
                              <Link to={`/tex/crm?segment=${encodeURIComponent(current.name)}${scopeAll ? "&scope=all" : ""}`} className="text-xs font-medium text-tex-700 hover:underline">
                                {t("crm.seg.view_guests")}
                              </Link>
                            )}
                          </span>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {!isNew && current && (
                          <Button variant="secondary" icon={<Calculator className="size-4" aria-hidden />} loading={evaluate.pending} disabled={dirty && !readOnly} onClick={() => runEvaluate(current.name)}>
                            {t("crm.seg.evaluate")}
                          </Button>
                        )}
                        {!readOnly && (
                          <Button icon={<Save className="size-4" aria-hidden />} loading={save.pending} disabled={!canSave} onClick={onSave}>
                            {isNew ? t("crm.seg.create") : t("crm.seg.save")}
                          </Button>
                        )}
                      </div>
                    </div>
                    {dirty && !readOnly && !isNew && <p className="text-xs text-amber-700">{t("crm.seg.unsaved")}</p>}
                    <InlineError error={evaluate.error} />
                    <p className="text-xs text-zinc-500">{scopeAll ? t("crm.seg.scope_all_note") : t("crm.seg.scope_hotel_note")}</p>
                  </CardBody>
                </Card>
                {!isNew && current && (
                  canExport ? (
                    <SegmentExport segment={current.name} segmentLabel={current.segment_name} property={scopeProperty} members={memberCount ?? null} />
                  ) : (
                    <Notice tone="info">{scopeAll && can("guest.export") ? t("crm.export.pick_hotel") : t("crm.export.no_permission")}</Notice>
                  )
                )}
              </>
            )}
          </div>
        </div>
      )}
    </>
  )
}
