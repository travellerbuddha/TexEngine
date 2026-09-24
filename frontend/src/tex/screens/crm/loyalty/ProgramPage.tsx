import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"
import { Ban, Eye, Plus, Power, RotateCcw, Save, Trash2 } from "lucide-react"
import { useTexMutation, useTexQuery } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { overSaved } from "../../../lib/edits"
import { num } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ConfirmDialog,
  DECIMAL_PLACES,
  DecimalInput,
  EmptyState,
  ErrorState,
  Field,
  IconButton,
  InlineError,
  Input,
  Money,
  Notice,
  PageHeader,
  Segmented,
  Select,
  Skeleton,
  Switch,
  TabPanel,
  Tabs,
  useToast,
} from "../../../ui"
import { CrmNav } from "../components/common"
import { useEvent } from "../lib"
import {
  BLACKOUT_PURPOSES,
  EARN_BASES,
  type EarnBasis,
  type ProgramDetail,
  type ProgramLookups,
  type ProgramsResponse,
} from "../types"
import { Ledger } from "./Ledger"
import {
  basisKey,
  blankDraft,
  draftFromProgram,
  hotelName,
  newBlackout,
  newRule,
  newTier,
  payloadOf,
  purposeKey,
  savedRefs,
  scopeText,
  validateDraft,
  type BlackoutDraft,
  type ProgramDraft,
  type RuleDraft,
  type TierDraft,
} from "./lib"
import { EnabledBadge } from "./Programs"

const intOnly = (v: string) => v.replace(/\D/g, "")

/** A numbered row of a child table (earn rule, tier, blackout) with its remove button. */
function RowBox({ title, onRemove, removeLabel, children }: { title: string; onRemove?: () => void; removeLabel: string; children: ReactNode }) {
  return (
    <li className="rounded-lg border border-zinc-200 bg-zinc-50/60 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold tracking-wide text-zinc-600 uppercase">{title}</h3>
        {onRemove && <IconButton label={removeLabel} icon={<Trash2 className="size-4" />} size="sm" onClick={onRemove} />}
      </div>
      {children}
    </li>
  )
}

/** The settings form: a tab panel next to the ledger, a plain section for a new program. */
function SettingsPanel({ tabbed, children }: { tabbed: boolean; children: ReactNode }) {
  return tabbed ? (
    <TabPanel id="settings" className="space-y-5">
      {children}
    </TabPanel>
  ) : (
    <div className="space-y-5">{children}</div>
  )
}

/** /tex/crm/loyalty/new and /tex/crm/loyalty/:name — edit a program, see its ledger (ADR-037). */
export default function ProgramPage() {
  const { name } = useParams()
  const isNew = !name
  const own = name ?? "new"
  const { t } = useTexT()
  const { boot, property } = useSession()
  const navigate = useNavigate()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const tab = !isNew && params.get("tab") === "ledger" ? "ledger" : "settings"

  const prog = useTexQuery<ProgramDetail>("loyalty", "program", { name }, [name], !isNew)
  const p = prog.data && prog.data.name === name ? prog.data : undefined
  const canEdit = isNew || Boolean(p?.can_edit)
  // where a program may live (hotels / whole groups the user edits)
  const list = useTexQuery<ProgramsResponse>("loyalty", "programs", {}, [], canEdit)
  const scopes = list.data?.scopes

  const [state, setState] = useState<{ for: string; draft: ProgramDraft } | null>(null)
  const draft = state?.for === own ? state.draft : null
  const [attempted, setAttempted] = useState(false)
  const [confirm, setConfirm] = useState<"disable" | "delete" | null>(null)

  // a new program starts from the defaults once the allowed scopes are known
  useEffect(() => {
    if (isNew && scopes && state?.for !== "new") {
      setState({ for: "new", draft: blankDraft(scopes, property?.name, boot.properties) })
      setAttempted(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isNew, scopes])
  // the draft the last save sent, until the program is reloaded after it
  const sentRef = useRef<ProgramDraft | null>(null)
  // an existing one is (re)loaded from the server after every save; what the user changed while
  // the save was in flight stays on top of it, never replaced by the saved copy
  useEffect(() => {
    if (p) {
      const sent = sentRef.current
      sentRef.current = null
      const saved = draftFromProgram(p)
      setState((s) => ({
        for: p.name,
        draft: sent && s && (s.for === p.name || s.for === "new") ? overSaved(saved, sent, s.draft) : saved,
      }))
      setAttempted(false)
    }
  }, [p])

  const set = (patch: Partial<ProgramDraft>) => setState((s) => (s && s.for === own ? { ...s, draft: { ...s.draft, ...patch } } : s))
  const setRule = (key: string, patch: Partial<RuleDraft>) =>
    draft && set({ earn_rules: draft.earn_rules.map((r) => (r.key === key ? { ...r, ...patch } : r)) })
  const setTier = (key: string, patch: Partial<TierDraft>) => draft && set({ tiers: draft.tiers.map((r) => (r.key === key ? { ...r, ...patch } : r)) })
  const setBlackout = (key: string, patch: Partial<BlackoutDraft>) =>
    draft && set({ blackouts: draft.blackouts.map((r) => (r.key === key ? { ...r, ...patch } : r)) })

  // room types and extras of the program's hotels: from the program while its scope is unchanged
  const scopeValue = draft ? (draft.scopeType === "hotel" ? draft.property : draft.hotel_group) : ""
  const sameScope = Boolean(
    p && draft && (draft.scopeType === "hotel" ? draft.property === (p.property ?? "") : !p.property && draft.hotel_group === (p.hotel_group ?? "")),
  )
  const lk = useTexQuery<ProgramLookups>(
    "loyalty",
    "lookups",
    draft?.scopeType === "hotel" ? { property: scopeValue } : { hotel_group: scopeValue },
    [draft?.scopeType, scopeValue],
    Boolean(draft && scopeValue && !sameScope && canEdit),
  )
  const lookups = sameScope ? p?.lookups : lk.data
  // what the saved rules reference stays valid while the scope is unchanged
  const saved = useMemo(() => (sameScope && p ? savedRefs(p.earn_rules ?? []) : undefined), [sameScope, p])

  const readOnly = !canEdit
  const members = p?.members ?? 0
  const scopeLocked = !isNew && members > 0
  const errors = useMemo(() => (draft ? validateDraft(t, draft, lookups, saved) : {}), [draft, lookups, saved, t])
  const err = (k: string) => (attempted ? errors[k] : undefined)
  const hasErrors = Object.keys(errors).length > 0
  const original = useMemo(() => (p ? JSON.stringify(payloadOf(draftFromProgram(p), false)) : null), [p])
  const dirty = isNew || (draft !== null && original !== JSON.stringify(payloadOf(draft, false)))

  const save = useTexMutation<{ data: Record<string, unknown> }, { name: string }>("loyalty", "save_program")
  const enable = useTexMutation<{ name: string; enabled: number }, { name: string; enabled: boolean }>("loyalty", "set_enabled")
  const remove = useTexMutation<{ name: string }, { ok: boolean }>("loyalty", "delete_program")
  const closeConfirm = useEvent(() => {
    setConfirm(null)
    // the dialog showed any refusal; do not repeat it on the page
    enable.clearError()
    remove.clearError()
  })

  const onSave = async () => {
    if (!draft || readOnly) return
    setAttempted(true)
    if (hasErrors) return
    try {
      const r = await save.run({ data: { ...(isNew ? {} : { name }), ...payloadOf(draft, isNew) } })
      sentRef.current = draft
      toast.success(isNew ? t("crm.program.created") : t("crm.program.saved"))
      if (isNew) navigate(`/tex/crm/loyalty/${encodeURIComponent(r.name)}`, { replace: true })
      else prog.reload()
    } catch {
      /* inline */
    }
  }

  const setEnabled = async (on: boolean) => {
    if (!name) return
    await enable.run({ name, enabled: on ? 1 : 0 })
    toast.success(on ? t("crm.program.enabled_toast") : t("crm.program.disabled_toast"))
    prog.reload()
  }

  const onDelete = async () => {
    if (!name) return
    await remove.run({ name })
    toast.success(t("crm.program.deleted"))
    navigate("/tex/crm/loyalty", { replace: true })
  }

  const hotelOptions = useMemo(() => {
    const names = new Set(scopes?.hotels ?? [])
    if (draft?.property) names.add(draft.property)
    return [...names].map((h) => ({ value: h, label: hotelName(boot, h) })).sort((a, b) => a.label.localeCompare(b.label))
  }, [scopes, draft?.property, boot])
  const groupOptions = useMemo(() => {
    const names = new Set(scopes?.groups ?? [])
    if (draft?.hotel_group) names.add(draft.hotel_group)
    return [...names].sort().map((g) => ({ value: g, label: g }))
  }, [scopes, draft?.hotel_group])
  const scopeTypes = [
    ...(hotelOptions.length || draft?.scopeType === "hotel" ? (["hotel"] as const) : []),
    ...(groupOptions.length || draft?.scopeType === "group" ? (["group"] as const) : []),
  ]
  const currencyOptions = useMemo(() => {
    const all = new Set(lookups?.currencies ?? [])
    if (draft?.currency) all.add(draft.currency)
    return [...all].sort().map((c) => ({ value: c, label: c }))
  }, [lookups, draft?.currency])
  const manyHotels = new Set((lookups?.room_types ?? []).map((r) => r.property)).size > 1
  const roomOptions = (current: string) => {
    const opts = (lookups?.room_types ?? []).map((r) => ({
      value: r.name,
      label: `${r.room_type_name || r.name}${manyHotels ? ` · ${hotelName(boot, r.property)}` : ""}`,
    }))
    return current && !opts.some((o) => o.value === current) ? [{ value: current, label: current }, ...opts] : opts
  }
  const extraOptions = (current: string) => {
    const opts = (lookups?.extras ?? []).map((x) => ({
      value: x.name,
      label: `${x.extra_name || x.name}${x.extra_code ? ` (${x.extra_code})` : ""}${manyHotels ? ` · ${hotelName(boot, x.property)}` : ""}`,
    }))
    return current && !opts.some((o) => o.value === current) ? [{ value: current, label: current }, ...opts] : opts
  }

  const title = isNew ? t("crm.program.new_title") : (p?.program_name ?? t("crm.nav.loyalty"))
  const loadError = isNew ? list.error : prog.error
  const cannotCreate = isNew && scopes && !scopes.hotels.length && !scopes.groups.length

  return (
    <>
      <PageHeader
        title={title}
        subtitle={p ? scopeText(t, boot, p) : undefined}
        crumbs={[
          { label: t("core.nav.crm"), to: "/tex/crm" },
          { label: t("crm.nav.loyalty"), to: "/tex/crm/loyalty" },
          { label: title },
        ]}
        meta={
          p ? (
            <>
              <EnabledBadge enabled={Boolean(p.enabled)} />
              {!p.can_edit && (
                <Badge tone="neutral">
                  <Eye className="size-3" aria-hidden />
                  {t("crm.programs.view_only")}
                </Badge>
              )}
            </>
          ) : undefined
        }
        actions={
          p?.can_edit ? (
            <>
              {p.enabled ? (
                <Button variant="secondary" icon={<Ban className="size-4" aria-hidden />} disabled={dirty} onClick={() => setConfirm("disable")}>
                  {t("crm.program.disable")}
                </Button>
              ) : (
                <Button
                  variant="secondary"
                  icon={<Power className="size-4" aria-hidden />}
                  disabled={dirty}
                  loading={enable.pending}
                  onClick={() => setEnabled(true).catch(() => undefined)}
                >
                  {t("crm.program.enable")}
                </Button>
              )}
              {members === 0 && (
                <Button variant="ghost" icon={<Trash2 className="size-4" aria-hidden />} disabled={dirty} onClick={() => setConfirm("delete")}>
                  {t("crm.program.delete")}
                </Button>
              )}
            </>
          ) : undefined
        }
      />
      <CrmNav />
      {loadError ? (
        <Card>
          <ErrorState error={loadError} onRetry={isNew ? list.reload : prog.reload} />
        </Card>
      ) : cannotCreate ? (
        <Card>
          <EmptyState title={t("core.error.permission")} description={t("crm.program.cannot_create")} />
        </Card>
      ) : !draft ? (
        <div className="space-y-4">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : (
        <div className="space-y-5">
          {p?.can_edit && dirty && <p className="text-xs text-zinc-600">{t("crm.program.save_first")}</p>}
          <InlineError error={enable.error} />
          {p && (
            <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label={t("crm.program.stats")}>
              {[
                { label: t("crm.program.members"), value: num(p.members) },
                { label: t("crm.program.available"), value: num(p.available_points) },
                { label: t("crm.program.pending"), value: num(p.pending_points) },
                { label: t("crm.program.liability"), value: p.currency ? <Money amount={p.liability} currency={p.currency} /> : "—" },
              ].map((s) => (
                <div key={s.label} className="rounded-(--radius-tex) border border-zinc-200 bg-white p-3 shadow-tex-card">
                  <dt className="text-xs text-zinc-500">{s.label}</dt>
                  <dd className="mt-0.5 text-lg font-semibold text-zinc-950 tabular-nums">{s.value}</dd>
                </div>
              ))}
            </dl>
          )}
          {!isNew && (
            <Tabs
              label={t("crm.program.tabs")}
              value={tab}
              onChange={(id) => setParams(id === "ledger" ? { tab: "ledger" } : {}, { replace: true })}
              tabs={[
                { id: "settings", label: t("crm.program.tab.settings") },
                { id: "ledger", label: t("crm.program.tab.ledger") },
              ]}
            />
          )}
          {tab === "ledger" && name ? (
            <TabPanel id="ledger">
              <Card>
                <Ledger program={name} programName={p?.program_name ?? name} />
              </Card>
            </TabPanel>
          ) : (
            <SettingsPanel tabbed={!isNew}>
              {readOnly && <Notice tone="info">{t("crm.program.readonly")}</Notice>}

              <Card>
                <CardHeader title={t("crm.program.section.general")} description={t("crm.program.section.general_hint")} />
                <CardBody className="space-y-4">
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <Field label={t("crm.program.name")} required error={err("program_name")}>
                      <Input
                        value={draft.program_name}
                        onChange={(e) => set({ program_name: e.target.value })}
                        maxLength={140}
                        autoComplete="off"
                        disabled={readOnly}
                      />
                    </Field>
                    {readOnly ? (
                      <div>
                        <p className="text-sm font-medium text-zinc-800">{t("crm.program.scope")}</p>
                        <p className="mt-1.5 text-sm text-zinc-900">{p ? scopeText(t, boot, p) : "—"}</p>
                      </div>
                    ) : (
                      <fieldset className="min-w-0 space-y-1.5" disabled={scopeLocked}>
                        <legend className="mb-1.5 text-sm font-medium text-zinc-800">
                          {t("crm.program.scope")}
                          <span className="ml-0.5 text-rose-600" aria-hidden>
                            *
                          </span>
                        </legend>
                        <div className="flex flex-wrap items-center gap-2">
                          {scopeTypes.length > 1 && (
                            <Segmented<"hotel" | "group">
                              label={t("crm.program.scope")}
                              size="sm"
                              value={draft.scopeType}
                              onChange={(v) => !scopeLocked && set({ scopeType: v })}
                              options={scopeTypes.map((s) => ({ value: s, label: t(`crm.program.scope.${s}`) }))}
                            />
                          )}
                          <div className="min-w-0 flex-1 basis-40">
                            {draft.scopeType === "hotel" ? (
                              <Select
                                aria-label={t("crm.program.hotel")}
                                aria-invalid={Boolean(err("scope")) || undefined}
                                value={draft.property}
                                onChange={(e) => {
                                  const h = e.target.value
                                  const ccyOf = (n: string) => boot.properties.find((x) => x.name === n)?.currency
                                  const ccy = ccyOf(h)
                                  // follow the hotel unless the user picked another currency
                                  const follow = !draft.currency || draft.currency === ccyOf(draft.property)
                                  set({ property: h, ...(ccy && follow ? { currency: ccy } : {}) })
                                }}
                                placeholder={t("crm.program.pick_hotel")}
                                options={hotelOptions}
                              />
                            ) : (
                              <Select
                                aria-label={t("crm.program.hotel_group")}
                                aria-invalid={Boolean(err("scope")) || undefined}
                                value={draft.hotel_group}
                                onChange={(e) => set({ hotel_group: e.target.value })}
                                placeholder={t("crm.program.pick_group")}
                                options={groupOptions}
                              />
                            )}
                          </div>
                        </div>
                        {scopeLocked && <p className="text-xs text-zinc-500">{t("crm.program.scope_locked", { count: members })}</p>}
                        {err("scope") && (
                          <p className="text-xs font-medium text-rose-700" role="alert">
                            {err("scope")}
                          </p>
                        )}
                      </fieldset>
                    )}
                  </div>
                  {isNew && (
                    <div className="max-w-xl">
                      <Switch
                        checked={draft.enabled}
                        onChange={(v) => set({ enabled: v })}
                        label={t("crm.program.enabled")}
                        description={t("crm.program.enabled_hint")}
                      />
                    </div>
                  )}
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    <Field label={t("crm.program.currency")} hint={t("crm.program.currency_hint")} error={err("currency")}>
                      <Select
                        value={draft.currency}
                        onChange={(e) => set({ currency: e.target.value })}
                        placeholder={t("crm.program.currency_none")}
                        options={currencyOptions}
                        disabled={readOnly}
                      />
                    </Field>
                    <Field label={t("crm.program.point_value")} hint={t("crm.program.point_value_hint")} error={err("point_value")}>
                      <DecimalInput
                        value={draft.point_value}
                        onValueChange={(v) => set({ point_value: v })}
                        decimals={DECIMAL_PLACES}
                        suffix={draft.currency || undefined}
                        disabled={readOnly}
                      />
                    </Field>
                    <Field label={t("crm.program.min_redeem")} error={err("min_redeem_points")}>
                      <Input
                        inputMode="numeric"
                        value={draft.min_redeem_points}
                        onChange={(e) => set({ min_redeem_points: intOnly(e.target.value) })}
                        className="text-right tabular-nums"
                        disabled={readOnly}
                      />
                    </Field>
                    <Field label={t("crm.program.max_redeem")} hint={t("crm.program.max_redeem_hint")} error={err("max_redeem_percent")}>
                      <DecimalInput
                        value={draft.max_redeem_percent}
                        onValueChange={(v) => set({ max_redeem_percent: v })}
                        decimals={2}
                        suffix="%"
                        disabled={readOnly}
                      />
                    </Field>
                    <Field label={t("crm.program.pending_days")} hint={t("crm.program.pending_days_hint")} error={err("pending_days")}>
                      <Input
                        inputMode="numeric"
                        value={draft.pending_days}
                        onChange={(e) => set({ pending_days: intOnly(e.target.value) })}
                        className="text-right tabular-nums"
                        disabled={readOnly}
                      />
                    </Field>
                    <Field label={t("crm.program.expiry_months")} hint={t("crm.program.expiry_hint")} error={err("expiry_months")}>
                      <Input
                        inputMode="numeric"
                        value={draft.expiry_months}
                        onChange={(e) => set({ expiry_months: intOnly(e.target.value) })}
                        className="text-right tabular-nums"
                        disabled={readOnly}
                      />
                    </Field>
                  </div>
                </CardBody>
              </Card>

              <Card>
                <CardHeader
                  title={t("crm.program.rules")}
                  description={t("crm.program.rules_hint")}
                  actions={
                    !readOnly && (
                      <Button
                        variant="secondary"
                        size="sm"
                        icon={<Plus className="size-4" aria-hidden />}
                        onClick={() => set({ earn_rules: [...draft.earn_rules, newRule()] })}
                      >
                        {t("crm.program.add_rule")}
                      </Button>
                    )
                  }
                />
                <CardBody>
                  {draft.earn_rules.length === 0 ? (
                    <p className="text-sm text-zinc-500">{t("crm.program.rules_empty")}</p>
                  ) : (
                    <ol className="space-y-3">
                      {draft.earn_rules.map((r, i) => (
                        <RowBox
                          key={r.key}
                          title={t("crm.program.rule_n", { n: i + 1 })}
                          removeLabel={t("crm.program.remove_rule", { n: i + 1 })}
                          onRemove={readOnly ? undefined : () => set({ earn_rules: draft.earn_rules.filter((x) => x.key !== r.key) })}
                        >
                          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                            <Field label={t("crm.program.basis")}>
                              <Select
                                value={r.basis}
                                onChange={(e) => setRule(r.key, { basis: e.target.value as EarnBasis })}
                                options={EARN_BASES.map((b) => ({ value: b, label: t(basisKey(b)) }))}
                                disabled={readOnly}
                              />
                            </Field>
                            <Field label={t("crm.program.rate")} hint={t(`crm.program.rate_hint.${r.basis.toLowerCase()}`)} error={err(`rule.${r.key}.rate`)}>
                              <DecimalInput value={r.rate} onValueChange={(v) => setRule(r.key, { rate: v })} decimals={DECIMAL_PLACES} disabled={readOnly} />
                            </Field>
                            {r.basis === "ROOM" && (
                              <Field label={t("crm.program.room_type")} required error={err(`rule.${r.key}.room_type`)}>
                                <Select
                                  value={r.room_type}
                                  onChange={(e) => setRule(r.key, { room_type: e.target.value })}
                                  placeholder={t("crm.program.pick_room_type")}
                                  options={roomOptions(r.room_type)}
                                  disabled={readOnly}
                                />
                              </Field>
                            )}
                            {r.basis === "EXTRA" && (
                              <Field label={t("crm.program.extra")} required error={err(`rule.${r.key}.extra`)}>
                                <Select
                                  value={r.extra}
                                  onChange={(e) => setRule(r.key, { extra: e.target.value })}
                                  placeholder={t("crm.program.pick_extra")}
                                  options={extraOptions(r.extra)}
                                  disabled={readOnly}
                                />
                              </Field>
                            )}
                            <Field label={t("crm.program.window_from")}>
                              <Input type="date" value={r.date_from} onChange={(e) => setRule(r.key, { date_from: e.target.value })} disabled={readOnly} />
                            </Field>
                            <Field label={t("crm.program.window_to")} error={err(`rule.${r.key}.window`)}>
                              <Input type="date" value={r.date_to} onChange={(e) => setRule(r.key, { date_to: e.target.value })} disabled={readOnly} />
                            </Field>
                          </div>
                          <p className="mt-2 text-xs text-zinc-500">{t("crm.program.window_hint")}</p>
                        </RowBox>
                      ))}
                    </ol>
                  )}
                </CardBody>
              </Card>

              <Card>
                <CardHeader
                  title={t("crm.program.tiers")}
                  description={t("crm.program.tiers_hint")}
                  actions={
                    !readOnly && (
                      <Button variant="secondary" size="sm" icon={<Plus className="size-4" aria-hidden />} onClick={() => set({ tiers: [...draft.tiers, newTier()] })}>
                        {t("crm.program.add_tier")}
                      </Button>
                    )
                  }
                />
                <CardBody>
                  {draft.tiers.length === 0 ? (
                    <p className="text-sm text-zinc-500">{t("crm.program.tiers_empty")}</p>
                  ) : (
                    <ol className="space-y-3">
                      {draft.tiers.map((x, i) => (
                        <RowBox
                          key={x.key}
                          title={t("crm.program.tier_n", { n: i + 1 })}
                          removeLabel={t("crm.program.remove_tier", { n: i + 1 })}
                          onRemove={readOnly ? undefined : () => set({ tiers: draft.tiers.filter((y) => y.key !== x.key) })}
                        >
                          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                            <Field label={t("crm.program.tier_name")} required error={err(`tier.${x.key}.name`)}>
                              <Input value={x.tier_name} onChange={(e) => setTier(x.key, { tier_name: e.target.value })} maxLength={140} disabled={readOnly} />
                            </Field>
                            <Field label={t("crm.program.tier_from")} error={err(`tier.${x.key}.min_points`)}>
                              <Input
                                inputMode="numeric"
                                value={x.min_points}
                                onChange={(e) => setTier(x.key, { min_points: intOnly(e.target.value) })}
                                className="text-right tabular-nums"
                                disabled={readOnly}
                              />
                            </Field>
                            <Field label={t("crm.program.tier_multiplier")} error={err(`tier.${x.key}.multiplier`)}>
                              <DecimalInput
                                value={x.earn_multiplier}
                                onValueChange={(v) => setTier(x.key, { earn_multiplier: v })}
                                decimals={DECIMAL_PLACES}
                                suffix="×"
                                disabled={readOnly}
                              />
                            </Field>
                          </div>
                        </RowBox>
                      ))}
                    </ol>
                  )}
                </CardBody>
              </Card>

              <Card>
                <CardHeader
                  title={t("crm.program.blackouts")}
                  description={t("crm.program.blackouts_hint")}
                  actions={
                    !readOnly && (
                      <Button
                        variant="secondary"
                        size="sm"
                        icon={<Plus className="size-4" aria-hidden />}
                        onClick={() => set({ blackouts: [...draft.blackouts, newBlackout()] })}
                      >
                        {t("crm.program.add_blackout")}
                      </Button>
                    )
                  }
                />
                <CardBody>
                  {draft.blackouts.length === 0 ? (
                    <p className="text-sm text-zinc-500">{t("crm.program.blackouts_empty")}</p>
                  ) : (
                    <ol className="space-y-3">
                      {draft.blackouts.map((b, i) => (
                        <RowBox
                          key={b.key}
                          title={t("crm.program.blackout_n", { n: i + 1 })}
                          removeLabel={t("crm.program.remove_blackout", { n: i + 1 })}
                          onRemove={readOnly ? undefined : () => set({ blackouts: draft.blackouts.filter((y) => y.key !== b.key) })}
                        >
                          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                            <Field label={t("crm.program.date_from")} required error={err(`blackout.${b.key}.dates`)}>
                              <Input type="date" value={b.date_from} onChange={(e) => setBlackout(b.key, { date_from: e.target.value })} disabled={readOnly} />
                            </Field>
                            <Field label={t("crm.program.date_to")} required>
                              <Input type="date" value={b.date_to} onChange={(e) => setBlackout(b.key, { date_to: e.target.value })} disabled={readOnly} />
                            </Field>
                            <Field label={t("crm.program.applies_to")}>
                              <Select
                                value={b.applies_to}
                                onChange={(e) => setBlackout(b.key, { applies_to: e.target.value as BlackoutDraft["applies_to"] })}
                                options={BLACKOUT_PURPOSES.map((x) => ({ value: x, label: t(purposeKey(x)) }))}
                                disabled={readOnly}
                              />
                            </Field>
                            <Field label={t("crm.program.note")}>
                              <Input value={b.note} onChange={(e) => setBlackout(b.key, { note: e.target.value })} maxLength={140} disabled={readOnly} />
                            </Field>
                          </div>
                        </RowBox>
                      ))}
                    </ol>
                  )}
                </CardBody>
              </Card>

              {!readOnly && (
                <div className="sticky bottom-0 z-10 -mx-1 rounded-(--radius-tex) border border-zinc-200 bg-white/95 px-4 py-3 shadow-tex-card backdrop-blur">
                  <div className="space-y-2">
                    <InlineError error={save.error} />
                    {attempted && hasErrors && (
                      <p className="text-sm font-medium text-rose-700" role="alert">
                        {t("crm.program.fix_errors")}
                      </p>
                    )}
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      {!isNew && dirty && <span className="mr-auto text-xs text-amber-800">{t("crm.program.unsaved")}</span>}
                      {!isNew && (
                        <Button
                          variant="secondary"
                          icon={<RotateCcw className="size-4" aria-hidden />}
                          disabled={!dirty || save.pending}
                          onClick={() => {
                            if (p) setState({ for: p.name, draft: draftFromProgram(p) })
                            setAttempted(false)
                            save.clearError()
                          }}
                        >
                          {t("crm.program.discard")}
                        </Button>
                      )}
                      <Button icon={<Save className="size-4" aria-hidden />} loading={save.pending} disabled={!dirty} onClick={onSave}>
                        {isNew ? t("crm.program.create") : t("crm.program.save")}
                      </Button>
                    </div>
                  </div>
                </div>
              )}
            </SettingsPanel>
          )}
        </div>
      )}
      <ConfirmDialog
        open={confirm === "disable"}
        onClose={closeConfirm}
        onConfirm={() => setEnabled(false)}
        title={t("crm.program.disable_title")}
        body={t("crm.program.disable_body")}
        confirmLabel={t("crm.program.disable")}
        tone="danger"
      />
      <ConfirmDialog
        open={confirm === "delete"}
        onClose={closeConfirm}
        onConfirm={onDelete}
        title={t("crm.program.delete_title")}
        body={t("crm.program.delete_body")}
        confirmLabel={t("crm.program.delete")}
        tone="danger"
      />
    </>
  )
}
