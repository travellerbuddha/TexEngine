import { useEffect, useId, useMemo, useRef, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { AlertTriangle, Calculator, Copy, Lock, Plus, Save, Trash2, Users } from "lucide-react"
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
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  InlineError,
  Input,
  Notice,
  PageHeader,
  Segmented,
  Select,
  Skeleton,
  Textarea,
  useToast,
} from "../../ui"
import { cn } from "../../../lib/utils"
import { CrmNav } from "./components/common"
import { safeJson, useEvent } from "./lib"
import { segmentLabel, segmentMeaning, rulesLackCurrency } from "./segments/meta"
import { conditionError, MAX_CONDITIONS, normalizeRules, RuleBuilder } from "./segments/RuleBuilder"
import { SegmentExport } from "./segments/SegmentExport"
import type { Segment, SegmentRules, SegmentsResponse } from "./types"

interface Draft {
  name?: string
  segment_name: string
  description: string
  /** owner of a new segment ("" = the server's default: the user's only enterprise, or platform level) */
  enterprise: string
  rules: SegmentRules
}

const EMPTY_RULES: SegmentRules = { match: "all", conditions: [] }

function rulesOf(s: Segment | undefined): SegmentRules {
  const r = safeJson<SegmentRules>(s?.rules_json, EMPTY_RULES)
  return {
    match: r.match === "any" ? "any" : "all",
    // values are edited as text: an integer stored as a number becomes its digits
    conditions: (r.conditions ?? []).map((c) => ({ ...c, value: typeof c.value === "number" ? String(c.value) : c.value })),
  }
}

function draftOf(s: Segment | undefined, enterprise = ""): Draft {
  if (!s)
    return { segment_name: "", description: "", enterprise, rules: { match: "all", conditions: [{ field: "stays", op: "gte", value: "2" }] } }
  return { name: s.name, segment_name: s.segment_name, description: s.description ?? "", enterprise: s.enterprise ?? "", rules: rulesOf(s) }
}

export default function Segments() {
  const { t } = useTexT()
  const property = useProperty()
  const { can, canAnywhere, boot } = useSession()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const list = useTexQuery<SegmentsResponse>("crm", "segments", {}, [])
  const selected = params.get("s") ?? ""
  const isNew = params.get("new") === "1"
  const scopeAll = params.get("scope") === "all"
  const scopeProperty = scopeAll ? undefined : property
  const segments = useMemo(() => list.data?.segments ?? [], [list.data])
  const own = segments.filter((s) => !s.system_key)
  const presets = segments.filter((s) => s.system_key)
  const current = segments.find((s) => s.name === selected)
  const enterprises = list.data?.enterprises ?? []
  const platformAdmin = Boolean(boot.user.platform_admin)
  const canEdit = canAnywhere("crm.edit")
  // a new segment belongs to one of the user's enterprises (a platform administrator may keep one at platform level)
  const canCreate = canEdit && (enterprises.length > 0 || platformAdmin)
  const mayEdit = (s: Segment | undefined) =>
    Boolean(s && !s.system_key && canEdit && (platformAdmin || enterprises.some((e) => e.name === s.enterprise)))
  const defaultEnterprise = enterprises.length === 1 ? enterprises[0].name : ""
  const pickEnterprise = enterprises.length > 1
  const enterpriseLabel = (name: string | null | undefined) => enterprises.find((e) => e.name === name)?.label ?? name ?? ""
  const canExport = scopeAll ? false : can("guest.export")
  const mineId = useId()
  const presetsId = useId()

  const [draft, setDraft] = useState<Draft>(() => draftOf(undefined))
  // counts made in this session, per segment and scope (a preset's count is never stored)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [confirmDelete, setConfirmDelete] = useState(false)
  const pendingCopy = useRef<Draft | null>(null)
  const save = useTexMutation<{ data: Record<string, unknown> }, { name: string }>("crm", "save_segment")
  const evaluate = useTexMutation<{ segment: string; property?: string }, { segment: string; members: number }>("crm", "evaluate_segment")
  const remove = useTexMutation<{ segment: string }, { ok: boolean }>("crm", "delete_segment")
  const countKey = (name: string) => `${name}@${scopeAll ? "*" : (property ?? "")}`

  // select a segment once the list is loaded (own segments first)
  useEffect(() => {
    if (!list.data || isNew || selected) return
    const first = list.data.segments.find((s) => !s.system_key) ?? list.data.segments[0]
    if (first) setParams({ s: first.name, ...(scopeAll ? { scope: "all" } : {}) }, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list.data])

  useEffect(() => {
    const copy = pendingCopy.current
    pendingCopy.current = null
    setDraft(isNew ? (copy ?? draftOf(undefined, defaultEnterprise)) : draftOf(current))
    save.clearError()
    evaluate.clearError()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, isNew, current?.rules_json, current?.segment_name, current?.description])

  const system = Boolean(current?.system_key) && !isNew
  const readOnly = isNew ? !canCreate : !mayEdit(current)
  const fields = list.data?.fields ?? {}
  const ops = list.data?.ops ?? ({} as SegmentsResponse["ops"])
  const currencies = list.data?.currencies ?? []
  const original = useMemo(() => (isNew ? null : draftOf(current)), [isNew, current])
  const dirty = !original || JSON.stringify(original) !== JSON.stringify(draft)
  const errors = draft.rules.conditions.map((c) => conditionError(c, fields[c.field], t)).filter(Boolean)
  const nameMissing = !draft.segment_name.trim()
  const enterpriseMissing = isNew && pickEnterprise && !platformAdmin && !draft.enterprise
  const canSave =
    !readOnly && dirty && !nameMissing && !enterpriseMissing && errors.length === 0 && draft.rules.conditions.length <= MAX_CONDITIONS
  // a saved money condition without a currency matches nobody (ADR-036)
  const savedLacksCurrency = !isNew && Boolean(current) && rulesLackCurrency(rulesOf(current), fields)
  const label = current ? segmentLabel(t, current) : ""

  const select = (patch: Record<string, string>) => {
    const next = new URLSearchParams()
    if (scopeAll) next.set("scope", "all")
    for (const [k, v] of Object.entries(patch)) if (v) next.set(k, v)
    setParams(next)
  }

  const runEvaluate = async (segment: string, preset: boolean) => {
    try {
      const r = await evaluate.run({ segment, property: scopeProperty })
      setCounts((c) => ({ ...c, [countKey(segment)]: r.members }))
      // an own segment's count is stored when counted across all hotels
      if (!preset && scopeAll) list.reload()
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
          ...(isNew && draft.enterprise ? { enterprise: draft.enterprise } : {}),
        },
      })
      toast.success(t("crm.seg.saved"))
      // the rules may have changed: no session count of this segment (in any scope) still holds
      setCounts((c) => Object.fromEntries(Object.entries(c).filter(([k]) => !k.startsWith(`${r.name}@`))))
      list.reload()
      select({ s: r.name })
      void runEvaluate(r.name, false)
    } catch {
      /* inline */
    }
  }

  const copy = () => {
    if (!current) return
    const ent = current.enterprise && enterprises.some((e) => e.name === current.enterprise) ? current.enterprise : defaultEnterprise
    // consumed by the reset effect once the URL switched to ?new=1. An own segment is copied
    // from the one draft (name, description and rules, unsaved edits included); a preset
    // from its definition.
    pendingCopy.current = {
      segment_name: t("crm.seg.copy_of", { name: system ? label : draft.segment_name.trim() || label }),
      description: (system ? segmentMeaning(t, current) : draft.description) ?? "",
      enterprise: ent,
      rules: system ? rulesOf(current) : draft.rules,
    }
    select({ new: "1" })
  }

  const closeDelete = useEvent(() => setConfirmDelete(false))
  const onDelete = async () => {
    if (!current) return
    await remove.run({ segment: current.name })
    toast.success(t("crm.seg.deleted"))
    select({})
    list.reload()
  }

  const session = current && !isNew ? counts[countKey(current.name)] : undefined
  const stored = current && !isNew && !current.system_key && current.last_evaluated && current.member_count !== null ? current.member_count : null

  const item = (s: Segment) => {
    const active = s.name === selected && !isNew
    const preset = Boolean(s.system_key)
    const c = counts[countKey(s.name)] ?? (!preset && s.last_evaluated && s.member_count !== null ? s.member_count : null)
    const warn = rulesLackCurrency(rulesOf(s), fields)
    const sub = preset
      ? segmentMeaning(t, s)
      : [
          s.last_evaluated ? t("crm.seg.evaluated_at", { date: dateTime(s.last_evaluated) }) : t("crm.seg.never_evaluated"),
          pickEnterprise && s.enterprise ? enterpriseLabel(s.enterprise) : null,
        ]
          .filter(Boolean)
          .join(" · ")
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
            <span className={cn("flex items-center gap-1.5 text-sm font-medium", active ? "text-tex-800" : "text-zinc-900")}>
              {preset && <Lock className="size-3 shrink-0 text-zinc-500" aria-hidden />}
              <span className="truncate">{segmentLabel(t, s)}</span>
            </span>
            {sub && <span className="block truncate text-xs text-zinc-500">{sub}</span>}
          </span>
          <span className="flex shrink-0 items-center gap-1.5">
            {warn && (
              <Badge tone="warning" title={t("crm.seg.warn_currency_short")}>
                <AlertTriangle className="size-3" aria-hidden />
                <span className="sr-only">{t("crm.seg.warn_currency_short")}</span>
              </Badge>
            )}
            <Badge tone="info">
              <Users className="size-3" aria-hidden />
              <span className="sr-only">{t("crm.seg.members_label")}</span>
              {c !== null && c !== undefined ? num(c) : "—"}
            </Badge>
          </span>
        </button>
      </li>
    )
  }

  const countLine = (
    <span className="inline-flex flex-wrap items-center gap-2">
      <span className="font-semibold text-zinc-900">
        {session !== undefined
          ? t("crm.seg.members", { count: session })
          : stored !== null
            ? t("crm.seg.members", { count: stored })
            : t("crm.seg.members_unknown")}
      </span>
      {session !== undefined ? (
        <span className="text-xs text-zinc-500">{scopeAll ? t("crm.seg.count_scope_all") : t("crm.seg.count_scope_hotel")}</span>
      ) : stored !== null && current?.last_evaluated ? (
        <span className="text-xs text-zinc-500">
          {t("crm.seg.evaluated_at", { date: dateTime(current.last_evaluated) })} · {t("crm.seg.count_scope_all")}
        </span>
      ) : null}
      {current && (
        <Link
          to={`/tex/crm?segment=${encodeURIComponent(current.name)}${scopeAll ? "&scope=all" : ""}`}
          className="text-xs font-medium text-tex-700 hover:underline"
        >
          {t("crm.seg.view_guests")}
        </Link>
      )}
    </span>
  )

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
              }}
              options={[
                { value: "hotel", label: t("crm.scope.hotel") },
                { value: "all", label: t("crm.scope.all") },
              ]}
            />
            {canCreate && (
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
            <CardHeader title={t("crm.seg.list")} />
            {!list.data ? (
              <div className="space-y-2 p-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : (
              <>
                <section aria-labelledby={mineId}>
                  <div className="px-4 pt-3 pb-1.5">
                    <h3 id={mineId} className="text-xs font-semibold tracking-wide text-zinc-600 uppercase">
                      {t("crm.seg.mine")}
                    </h3>
                    <p className="text-xs text-zinc-500">{t("crm.seg.mine_hint")}</p>
                  </div>
                  {own.length ? (
                    <ul className="divide-y divide-zinc-100">{own.map(item)}</ul>
                  ) : (
                    <p className="px-4 pb-3 text-sm text-zinc-500">
                      {t("crm.seg.mine_empty")}
                      {canCreate ? ` ${t("crm.seg.empty_hint")}` : ""}
                    </p>
                  )}
                  {canEdit && !canCreate && (
                    <div className="px-4 pb-3">
                      <Notice tone="info">{t("crm.seg.no_enterprise")}</Notice>
                    </div>
                  )}
                </section>
                {presets.length > 0 && (
                  <section aria-labelledby={presetsId} className="border-t border-zinc-200">
                    <div className="px-4 pt-3 pb-1.5">
                      <h3 id={presetsId} className="text-xs font-semibold tracking-wide text-zinc-600 uppercase">
                        {t("crm.seg.presets")}
                      </h3>
                      <p className="text-xs text-zinc-500">{t("crm.seg.presets_hint")}</p>
                    </div>
                    <ul className="divide-y divide-zinc-100">{presets.map(item)}</ul>
                  </section>
                )}
              </>
            )}
          </Card>

          <div className="min-w-0 space-y-5">
            {!isNew && !current ? (
              list.data && (
                <Card>
                  <EmptyState title={segments.length ? t("crm.seg.pick") : t("crm.seg.empty")} />
                </Card>
              )
            ) : system && current ? (
              <Card>
                <CardHeader
                  title={label}
                  description={segmentMeaning(t, current) ?? undefined}
                  actions={
                    <Badge tone="neutral">
                      <Lock className="size-3" aria-hidden />
                      {t("crm.seg.preset")}
                    </Badge>
                  }
                />
                <CardBody className="space-y-4">
                  <p className="text-xs text-zinc-500">{t("crm.seg.preset_hint")}</p>
                  <RuleBuilder rules={draft.rules} onChange={() => undefined} fields={fields} ops={ops} currencies={currencies} readOnly />
                  <div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-100 pt-4">
                    <div className="text-sm" aria-live="polite">
                      {countLine}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="secondary"
                        icon={<Calculator className="size-4" aria-hidden />}
                        loading={evaluate.pending}
                        onClick={() => runEvaluate(current.name, true)}
                      >
                        {t("crm.seg.evaluate")}
                      </Button>
                      {canCreate && (
                        <Button icon={<Copy className="size-4" aria-hidden />} onClick={copy}>
                          {t("crm.seg.copy_to_mine")}
                        </Button>
                      )}
                    </div>
                  </div>
                  <InlineError error={evaluate.error} />
                  <p className="text-xs text-zinc-500">
                    {t("crm.seg.preset_count_note")} {scopeAll ? t("crm.seg.scope_all_note") : t("crm.seg.scope_hotel_note")}
                  </p>
                </CardBody>
              </Card>
            ) : (
              <Card>
                <CardHeader
                  title={isNew ? t("crm.seg.new_title") : draft.segment_name || label}
                  description={readOnly ? t("crm.seg.readonly_hint") : t("crm.seg.editor_hint")}
                  actions={
                    !isNew && current ? (
                      <>
                        {canCreate && (
                          <Button variant="ghost" size="sm" icon={<Copy className="size-4" aria-hidden />} onClick={copy}>
                            {t("crm.seg.duplicate")}
                          </Button>
                        )}
                        {mayEdit(current) && (
                          <Button variant="ghost" size="sm" icon={<Trash2 className="size-4" aria-hidden />} onClick={() => setConfirmDelete(true)}>
                            {t("crm.seg.delete")}
                          </Button>
                        )}
                      </>
                    ) : undefined
                  }
                />
                <CardBody className="space-y-4">
                  {savedLacksCurrency && <Notice tone="warning">{t("crm.seg.warn_currency")}</Notice>}
                  {!readOnly && (
                    <div className="grid gap-4 sm:grid-cols-2">
                      <Field label={t("crm.seg.name")} required error={nameMissing && draft.segment_name !== "" ? t("crm.edit.required") : undefined}>
                        <Input
                          value={draft.segment_name}
                          onChange={(e) => setDraft({ ...draft, segment_name: e.target.value })}
                          maxLength={140}
                          autoComplete="off"
                        />
                      </Field>
                      <Field label={t("crm.seg.description")}>
                        <Textarea value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} rows={1} maxLength={500} />
                      </Field>
                      {isNew && pickEnterprise && (
                        <Field label={t("crm.seg.enterprise")} required={!platformAdmin} hint={t("crm.seg.enterprise_hint")} className="sm:col-span-2">
                          <Select
                            value={draft.enterprise}
                            onChange={(e) => setDraft({ ...draft, enterprise: e.target.value })}
                            placeholder={platformAdmin ? t("crm.seg.enterprise_platform") : t("crm.seg.enterprise_pick")}
                            options={enterprises.map((e) => ({ value: e.name, label: e.label }))}
                          />
                        </Field>
                      )}
                    </div>
                  )}
                  {readOnly && draft.description && <p className="text-sm text-zinc-600">{draft.description}</p>}
                  {!isNew && pickEnterprise && current?.enterprise && (
                    <p className="text-xs text-zinc-500">
                      {t("crm.seg.enterprise")}: <span className="font-medium text-zinc-700">{enterpriseLabel(current.enterprise)}</span>
                    </p>
                  )}
                  <RuleBuilder
                    rules={draft.rules}
                    onChange={(r) => setDraft({ ...draft, rules: r })}
                    fields={fields}
                    ops={ops}
                    currencies={currencies}
                    readOnly={readOnly}
                  />
                  <InlineError error={save.error} />
                  <div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-100 pt-4">
                    <div className="text-sm" aria-live="polite">
                      {isNew ? <span className="text-zinc-500">{t("crm.seg.save_to_count")}</span> : countLine}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {!isNew && current && (
                        <Button
                          variant="secondary"
                          icon={<Calculator className="size-4" aria-hidden />}
                          loading={evaluate.pending}
                          disabled={dirty && !readOnly}
                          onClick={() => runEvaluate(current.name, false)}
                        >
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
                  {dirty && !readOnly && !isNew && <p className="text-xs text-amber-800">{t("crm.seg.unsaved")}</p>}
                  {enterpriseMissing && <p className="text-xs text-zinc-600">{t("crm.seg.enterprise_required")}</p>}
                  <InlineError error={evaluate.error} />
                  <p className="text-xs text-zinc-500">{scopeAll ? t("crm.seg.scope_all_note") : t("crm.seg.scope_hotel_note")}</p>
                </CardBody>
              </Card>
            )}
            {!isNew && current && (
              canExport ? (
                <SegmentExport
                  segment={current.name}
                  segmentLabel={label}
                  property={scopeProperty}
                  members={session ?? null}
                />
              ) : (
                <Notice tone="info">{scopeAll && can("guest.export") ? t("crm.export.pick_hotel") : t("crm.export.no_permission")}</Notice>
              )
            )}
          </div>
        </div>
      )}
      <ConfirmDialog
        open={confirmDelete && Boolean(current)}
        onClose={closeDelete}
        onConfirm={onDelete}
        tone="danger"
        title={t("crm.seg.delete_title")}
        body={t("crm.seg.delete_body", { name: label })}
        confirmLabel={t("crm.seg.delete")}
      />
    </>
  )
}
