import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { Archive, CirclePlay, GitBranch, History, Lock, Save, Trash2 } from "lucide-react"
import { tex, TexApiError, useTexQuery, useTexMutation } from "../../../lib/api"
import { useProperty, useSession } from "../../../lib/session"
import { overSaved } from "../../../lib/edits"
import { dateTime } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  ConfirmDialog,
  DataTable,
  DECIMAL_PLACES,
  DecimalInput,
  Dialog,
  Drawer,
  EmptyState,
  ErrorState,
  Field,
  FormGrid,
  InlineError,
  Input,
  Notice,
  PageHeader,
  Select,
  Skeleton,
  Textarea,
  useToast,
  type Option,
} from "../../../ui"
import { StatusBadge } from "../components/common"
import { CsvPicker } from "../components/pickers"
import { RatesNav } from "../components/RatesNav"
import { RowsEditor, type ColSpec } from "../components/RowsEditor"
import { BOARDS, enumOptions, PERCENT_OPS } from "../lib/options"
import type { Lookups, Row } from "../lib/types"
import { decStr, fromRow, intVal, invalidateLookups, strVal, toRow, UI_RATES, useLookups, type FieldKind } from "../lib/util"
import { fieldKinds, isRequired, policyKind, type Doc, type PolicyField, type PolicyKind, type TableColumn } from "./config"

type T = (k: string, p?: Record<string, string | number>) => string

interface HistoryRow {
  name: string
  revision_no: number
  tex_status: string
  active_from: string | null
  active_to: string | null
  modified_by: string
  modified: string
}

function tableKinds(cols: TableColumn[]): Record<string, FieldKind> {
  return Object.fromEntries(cols.map((c) => [c.key, c.kind]))
}

/** What the server saved but its owner may not expect (``_warnings``), e.g. a promotion that ties
 * in its group (``PROMO_GROUP_TIE``, O-4): only the older one is applied. */
interface SaveWarning {
  code: string
  message: string
  other?: string
  other_name?: string
  older?: string
}

/** Loaded record → editor state (decimals as strings, tables as rows). */
function normalise(kind: PolicyKind, src: Doc): Doc {
  const out: Doc = { ...src }
  for (const f of Object.values(fieldKinds(kind))) {
    const v = src[f.key]
    if (f.kind === "decimal") out[f.key] = decStr(v)
    else if (f.kind === "int") out[f.key] = intVal(v)
    else if (f.kind === "check") out[f.key] = v ? 1 : 0
    else if (f.kind === "table") out[f.key] = ((v as Doc[] | undefined) ?? []).map((r) => toRow(r, tableKinds(f.columns ?? [])))
    else out[f.key] = strVal(v)
  }
  return out
}

function payload(kind: PolicyKind, d: Doc): Doc {
  const out: Doc = {}
  if (d.name) out.name = d.name
  for (const f of Object.values(fieldKinds(kind))) {
    if (f.readOnly) continue
    const v = d[f.key]
    if (f.kind === "table") out[f.key] = ((v as Row[]) ?? []).map((r) => fromRow(r, tableKinds(f.columns ?? [])))
    else if (f.kind === "int") out[f.key] = intVal(v)
    else if (f.kind === "check") out[f.key] = v ? 1 : 0
    else out[f.key] = v === "" || v === undefined ? null : v
  }
  return out
}

/** The saved record, with the fields the user edited while its save was in flight (those that
 * differ in `cur` from the `sent` doc) laid over it. */
function withEdits(kind: PolicyKind, saved: Doc, sent: Doc, cur: Doc | undefined): Doc {
  if (!cur) return saved
  const editable = Object.values(fieldKinds(kind))
    .filter((f) => !f.readOnly)
    .map((f) => f.key)
  return overSaved(saved, sent, cur, editable)
}

/** An age band of another live pricing policy this one cascades with (rules cascade by band code). */
interface InheritedBand {
  code: string
  label: string
  is_infant: boolean
  policies: string[]
}

/** The policy's own bands, then the band codes of the live policies it cascades with, so a
 * hotel (+ market) policy without bands can name the market policy's (ADR-043). */
function bandOptions(t: T, doc: Doc, inherited: InheritedBand[] | undefined): Option[] {
  const own = ((doc.age_bands as Row[]) ?? []).map((b) => String(b.band_code ?? "").trim().toUpperCase()).filter(Boolean)
  const out: Option[] = own.map((code) => ({ value: code, label: code }))
  for (const b of inherited ?? []) {
    if (!own.includes(b.code)) out.push({ value: b.code, label: t("rates.policy.pricing.band_from", { code: b.code, policy: b.policies.join(", ") }) })
  }
  return out
}

function sourceOptions(t: T, source: string | undefined, boot: ReturnType<typeof useSession>["boot"], lookups: Lookups | undefined, doc: Doc, inherited?: InheritedBand[]): Option[] {
  switch (source) {
    case "market":
      return boot.markets.map((m) => ({ value: m.name, label: `${m.name} · ${m.market_name}` }))
    case "channel":
      return boot.channels.map((c) => ({ value: c.name, label: c.channel_name }))
    case "currency":
      return boot.currencies.map((c) => ({ value: c, label: c }))
    case "room_type":
      return (lookups?.room_types ?? []).map((r) => ({ value: r.name, label: r.room_type_name }))
    case "contract":
      return (lookups?.contracts ?? []).map((c) => ({ value: c.name, label: `${c.contract_code} · ${c.contract_name}` }))
    case "rate_plan":
      return (lookups?.rate_plans ?? []).map((r) => ({ value: r.name, label: r.rate_plan_name }))
    case "board":
      return enumOptions(t, "board", BOARDS)
    case "band":
      return bandOptions(t, doc, inherited)
    default:
      return []
  }
}

/** Generic editor with the revision lifecycle (ADR-005): Draft → Activate; live
 * revisions are immutable (Revise creates a new draft); Archive needs a reason. */
export default function PolicyEditor() {
  const { kind: slug, name = "new" } = useParams()
  const kind = policyKind(slug)
  const isNew = name === "new"
  const { t } = useTexT()
  const toast = useToast()
  const navigate = useNavigate()
  const property = useProperty()
  const { boot, can } = useSession()
  const q = useTexQuery<Doc>("policies", "get_record", { doctype: kind?.doctype, name }, [kind?.doctype, name], Boolean(kind && !isNew))
  const save = useTexMutation<{ doctype: string; data: Doc }, Doc>("policies", "save_record")
  const [doc, setDoc] = useState<Doc>()
  const [base, setBase] = useState("")
  const [touched, setTouched] = useState(false)
  const [dialog, setDialog] = useState<"activate" | "archive" | "delete" | "history" | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionErr, setActionErr] = useState<TexApiError>()
  const lookups = useLookups(String(doc?.property || property || "") || undefined)
  const pricing = kind?.doctype === "TEX Pricing Policy"
  const bandArgs = { property: String(doc?.property || "") || null, market: String(doc?.market || "") || null, exclude: isNew ? null : name }
  const inheritedBands = useTexQuery<InheritedBand[]>("policies", "pricing_policy_bands", bandArgs, [pricing, bandArgs.property, bandArgs.market, bandArgs.exclude], Boolean(pricing && doc))

  // a record just created here, and the payload that created it, until it loads
  const created = useRef<{ name: string; sent: Doc } | null>(null)
  useEffect(() => {
    if (!kind) return
    if (isNew) {
      const d = normalise(kind, { ...kind.newDoc(), property: property ?? "" })
      setDoc(d)
      setBase(JSON.stringify(payload(kind, d)))
      setTouched(false)
    } else if (q.data && String(q.data.name) === name) {
      // (until the record at this address arrives, the query still holds the one shown before)
      const d = normalise(kind, q.data)
      // what the user typed while the create was in flight is kept
      const c = created.current?.name === d.name ? created.current : null
      if (c) created.current = null
      setDoc((cur) => (c ? withEdits(kind, d, c.sent, cur) : d))
      setBase(JSON.stringify(payload(kind, d)))
      setTouched(false)
    }
  }, [kind, isNew, name, q.data, property])

  const status = String(doc?.tex_status || "")
  const recProp = String(doc?.property || "") || undefined
  const canCap = kind ? (recProp ? can(kind.cap, recProp) : boot.user.platform_admin) : false
  const editable = Boolean(kind && doc && canCap && (!kind.revisioned || !status || status === "Draft"))
  const dirty = Boolean(kind && doc && JSON.stringify(payload(kind, doc)) !== base)
  const set = useCallback((k: string, v: unknown) => setDoc((d) => (d ? { ...d, [k]: v } : d)), [])

  const missing = useMemo(() => {
    if (!kind || !doc) return []
    const out: string[] = []
    for (const f of Object.values(fieldKinds(kind))) {
      if (!isRequired(f, doc) || (f.showIf && !f.showIf(doc))) continue
      const v = doc[f.key]
      if (v === "" || v === null || v === undefined) out.push(f.key)
    }
    if (kind.propertyRequired && !doc.property) out.push("property")
    return out
  }, [kind, doc])
  // a choice the record's other fields no longer allow (``optionsFor``): the server refuses it
  const invalid = useMemo(() => {
    if (!kind || !doc) return []
    return Object.values(fieldKinds(kind))
      .filter((f) => f.optionsFor && (!f.showIf || f.showIf(doc)) && doc[f.key] && !f.optionsFor(doc).includes(String(doc[f.key])))
      .map((f) => f.key)
  }, [kind, doc])

  if (!kind)
    return (
      <>
        <RatesNav />
        <Card>
          <EmptyState title={t("core.error.not_found")} />
        </Card>
      </>
    )

  const listPath = `/tex/rates/policies/${kind.slug}`
  const title = doc ? (typeof kind.titleField === "function" ? kind.titleField(doc) : String(doc[kind.titleField] || "")) : ""

  const warn = (rec: Doc) => {
    for (const w of (rec._warnings as SaveWarning[] | undefined) ?? [])
      toast.warning(
        w.code === "PROMO_GROUP_TIE" ? t("rates.policy.promotions.group_tie", { name: w.other_name ?? "", id: w.other ?? "", older: w.older ?? "" }) : w.message,
      )
  }

  const onSave = async () => {
    // one save at a time (Enter in a field submits the form)
    if (!doc || save.pending) return
    setTouched(true)
    if (missing.length || invalid.length) {
      toast.error(t("rates.v.fix_required"))
      return
    }
    const sent = doc
    try {
      const saved = await save.run({ doctype: kind.doctype, data: payload(kind, sent) })
      invalidateLookups(String(saved.property || property || ""))
      toast.success(t("core.saved"))
      warn(saved)
      if (isNew) {
        created.current = { name: String(saved.name), sent }
        navigate(`${listPath}/${encodeURIComponent(String(saved.name))}`, { replace: true })
      } else {
        // the saved record is the new base; what the user edited while the save was in flight
        // stays on top of it
        const d = normalise(kind, saved)
        setDoc((cur) => withEdits(kind, d, sent, cur))
        setBase(JSON.stringify(payload(kind, d)))
      }
    } catch {
      /* inline */
    }
  }

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true)
    setActionErr(undefined)
    try {
      await fn()
      toast.success(ok)
    } catch (e) {
      const err = e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error")
      setActionErr(err)
      throw err
    } finally {
      setBusy(false)
    }
  }

  const revise = () =>
    act(async () => {
      const d = await tex<Doc>("policies", "revise", { doctype: kind.doctype, name }, { post: true })
      navigate(`${listPath}/${encodeURIComponent(String(d.name))}`)
    }, t("rates.policy.revised")).catch(() => undefined)

  const header = (
    <PageHeader
      crumbs={[
        // promotions are daily work with their own entry; the other kinds are selling rules
        ...(kind.slug === "promotions" ? [] : [{ label: t("core.nav.selling_rules"), to: "/tex/rates/policies/markup" }]),
        { label: t(kind.title), to: listPath },
        { label: isNew ? t("rates.policy.new_short") : title || name },
      ]}
      title={isNew ? t("rates.policy.new", { what: t(kind.singular) }) : title || <Skeleton className="h-7 w-48" />}
      subtitle={isNew ? t(kind.intro) : !isNew ? <span className="font-mono text-xs">{name}</span> : undefined}
      meta={
        doc &&
        kind.revisioned &&
        !isNew && (
          <>
            <StatusBadge status={status} group="rev_status" />
            <Badge>{t("rates.policy.revision_n", { n: intVal(doc.revision_no) || 1 })}</Badge>
            {doc.active_from ? <span className="text-xs text-zinc-500">{t("rates.policy.live_since", { at: dateTime(String(doc.active_from)) })}</span> : null}
            {doc.active_to ? <span className="text-xs text-zinc-500">{t("rates.policy.live_until", { at: dateTime(String(doc.active_to)) })}</span> : null}
            {!editable && (
              <Badge tone="neutral">
                <Lock className="size-3" aria-hidden />
                {t("rates.version.read_only")}
              </Badge>
            )}
          </>
        )
      }
      actions={
        doc && (
          <>
            {kind.revisioned && !isNew && (
              <Button variant="ghost" icon={<History className="size-4" aria-hidden />} onClick={() => setDialog("history")}>
                {t("rates.policy.history")}
              </Button>
            )}
            {canCap && !isNew && (!kind.revisioned || status === "Draft") && (
              <Button variant="ghost" className="text-rose-700! hover:bg-rose-50!" icon={<Trash2 className="size-4" aria-hidden />} onClick={() => setDialog("delete")}>
                {kind.revisioned ? t("rates.policy.delete_draft") : t("core.action.delete")}
              </Button>
            )}
            {canCap && kind.revisioned && (status === "Active" || status === "Superseded") && (
              <Button variant="ghost" className="text-rose-700! hover:bg-rose-50!" icon={<Archive className="size-4" aria-hidden />} onClick={() => setDialog("archive")}>
                {t("rates.policy.archive")}
              </Button>
            )}
            {canCap && kind.revisioned && (status === "Active" || status === "Superseded") && (
              <Button icon={<GitBranch className="size-4" aria-hidden />} loading={busy} onClick={() => void revise()}>
                {t("rates.policy.revise")}
              </Button>
            )}
            {canCap && kind.revisioned && status === "Draft" && !isNew && (
              <Button variant="secondary" icon={<CirclePlay className="size-4" aria-hidden />} disabled={dirty} title={dirty ? t("rates.version.save_first") : undefined} onClick={() => setDialog("activate")}>
                {t("rates.policy.activate")}
              </Button>
            )}
            {editable && (
              <Button icon={<Save className="size-4" aria-hidden />} loading={save.pending} disabled={!dirty && !isNew} onClick={() => void onSave()}>
                {isNew ? t("rates.policy.create") : t("core.action.save")}
              </Button>
            )}
          </>
        )
      }
    />
  )

  if (q.error)
    return (
      <>
        <RatesNav />
        {header}
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      </>
    )

  return (
    <>
      <RatesNav />
      {header}
      {doc && kind.revisioned && !isNew && status !== "Draft" && (
        <div className="mb-4">
          <Notice tone="info" title={t(status === "Archived" ? "rates.policy.archived_title" : status === "Superseded" ? "rates.policy.superseded_title" : "rates.policy.live_title")}>
            {t(status === "Archived" ? "rates.policy.archived_body" : status === "Superseded" ? "rates.policy.superseded_body" : "rates.policy.live_body")}
          </Notice>
        </div>
      )}
      {doc && kind.revisioned && (isNew || status === "Draft") && (
        <div className="mb-4">
          <Notice tone="warning">{t("rates.policy.draft_body")}</Notice>
        </div>
      )}
      {doc && !canCap && <div className="mb-4"><Notice tone="info">{t("rates.policy.no_permission")}</Notice></div>}
      <InlineError error={save.error ?? actionErr} />
      {!doc ? (
        <Card>
          <CardBody className="space-y-3">
            <Skeleton className="h-6 w-64" />
            <Skeleton className="h-40 w-full" />
          </CardBody>
        </Card>
      ) : (
        <form
          className="mt-2 space-y-5"
          onSubmit={(e) => {
            e.preventDefault()
            void onSave()
          }}
        >
          {kind.sections.map((s) => {
            const visible = s.fields.filter((f) => !f.showIf || f.showIf(doc))
            const table = visible.length === 1 && visible[0].kind === "table"
            return (
              <Card key={s.title}>
                <CardHeader title={t(s.title)} description={s.help ? t(s.help) : undefined} />
                <CardBody>
                  {table ? (
                    <TableField f={visible[0]} doc={doc} readOnly={!editable} lookups={lookups.data} inheritedBands={inheritedBands.data} onChange={(rows) => set(visible[0].key, rows)} />
                  ) : (
                    <FormGrid cols={3}>
                      {visible.map((f) => (
                        <FieldControl key={f.key} f={f} kind={kind} doc={doc} readOnly={!editable || Boolean(f.readOnly)} lookups={lookups.data} error={touched && missing.includes(f.key) ? t("rates.v.required") : invalid.includes(f.key) ? t("rates.v.not_allowed") : undefined} onChange={(v) => set(f.key, v)} />
                      ))}
                    </FormGrid>
                  )}
                </CardBody>
              </Card>
            )
          })}
          <button type="submit" hidden />
        </form>
      )}

      {doc && dialog === "activate" && (
        <ActivateDialog
          onClose={() => setDialog(null)}
          busy={busy}
          onConfirm={async (at) => {
            await act(async () => {
              const d = await tex<Doc>("policies", "activate", { doctype: kind.doctype, name, at }, { post: true })
              warn(d)
              const n = normalise(kind, d)
              setDoc(n)
              setBase(JSON.stringify(payload(kind, n)))
              q.reload()
            }, t("rates.policy.activated"))
            setDialog(null)
          }}
          error={actionErr}
        />
      )}
      <ConfirmDialog
        open={dialog === "archive"}
        onClose={() => setDialog(null)}
        tone="danger"
        requireReason
        title={t("rates.policy.archive_title", { what: title })}
        body={t("rates.policy.archive_body")}
        confirmLabel={t("rates.policy.archive")}
        onConfirm={async (reason) => {
          await tex(UI_RATES, "archive_record", { doctype: kind.doctype, name, reason }, { post: true })
          toast.success(t("rates.policy.archived"))
          q.reload()
        }}
      />
      <ConfirmDialog
        open={dialog === "delete"}
        onClose={() => setDialog(null)}
        tone="danger"
        title={t("rates.policy.delete_title", { what: title || name })}
        body={kind.revisioned ? t("rates.policy.delete_draft_body") : t("rates.policy.delete_body")}
        confirmLabel={t("core.action.delete")}
        onConfirm={async () => {
          await tex("policies", "delete_record", { doctype: kind.doctype, name }, { post: true })
          invalidateLookups(recProp)
          toast.success(t("rates.policy.deleted"))
          navigate(listPath)
        }}
      />
      {kind.revisioned && !isNew && <HistoryDrawer open={dialog === "history"} onClose={() => setDialog(null)} doctype={kind.doctype} name={name} slug={kind.slug} />}
    </>
  )
}

function FieldControl({
  f,
  kind,
  doc,
  readOnly,
  lookups,
  error,
  onChange,
}: {
  f: PolicyField
  kind: PolicyKind
  doc: Doc
  readOnly: boolean
  lookups: Lookups | undefined
  error?: string
  onChange: (v: unknown) => void
}) {
  const { t } = useTexT()
  const { boot, can } = useSession()
  const v = doc[f.key]
  const hint = f.helpByValue ? t(`${f.helpByValue}.${String(v || "")}`) : f.help ? t(f.help) : undefined
  const hintText = hint && !hint.startsWith("rates.") ? hint : undefined
  const common = { label: t(f.label), hint: hintText, error, required: isRequired(f, doc) && !readOnly, className: f.wide || f.kind === "textarea" ? "sm:col-span-2 lg:col-span-3" : undefined }
  switch (f.kind) {
    case "property": {
      const opts = boot.properties.filter((p) => can(kind.cap, p.name) || p.name === v).map((p) => ({ value: p.name, label: p.property_name }))
      const allowGlobal = !kind.propertyRequired && (boot.user.platform_admin || !v)
      return (
        <Field {...common} required={kind.propertyRequired && !readOnly} hint={!kind.propertyRequired ? t(boot.user.platform_admin ? "rates.h.property_global" : "rates.h.property_hotel") : undefined}>
          <Select disabled={readOnly} value={String(v || "")} onChange={(e) => onChange(e.target.value)} options={opts} placeholder={allowGlobal ? t(f.blank ?? "rates.common.all_hotels") : undefined} />
        </Field>
      )
    }
    case "check":
      return (
        <div className={common.className}>
          <Checkbox disabled={readOnly} label={t(f.label)} checked={Boolean(v)} onChange={(e) => onChange(e.target.checked ? 1 : 0)} />
          {hintText && <p className="mt-1 pl-6 text-xs text-zinc-500">{hintText}</p>}
        </div>
      )
    case "int":
      return (
        <Field {...common}>
          <Input type="number" step={1} min={0} disabled={readOnly} value={String(intVal(v))} onChange={(e) => onChange(intVal(e.target.value))} />
        </Field>
      )
    case "decimal":
      return (
        <Field {...common}>
          <DecimalInput disabled={readOnly} value={String(v ?? "")} onValueChange={onChange} decimals={f.decimals ?? DECIMAL_PLACES} allowNegative={f.allowNegative} suffix={f.suffix?.(doc) || undefined} />
        </Field>
      )
    case "select": {
      const allowed = f.optionsFor?.(doc) ?? f.options ?? []
      const cur = String(v || "")
      // a value the other fields no longer allow stays visible, marked, until it is changed
      const values = cur && !allowed.includes(cur) && (f.options ?? []).includes(cur) ? [...allowed, cur] : allowed
      return (
        <Field {...common}>
          <Select disabled={readOnly} value={cur} onChange={(e) => onChange(e.target.value)} options={enumOptions(t, f.group ?? "", values)} placeholder={isRequired(f, doc) ? undefined : t(f.blank ?? "rates.common.none")} />
        </Field>
      )
    }
    case "link": {
      const opts = sourceOptions(t, f.source, boot, lookups, doc)
      const cur = String(v || "")
      return (
        <Field {...common}>
          <Select
            disabled={readOnly}
            value={cur}
            onChange={(e) => onChange(e.target.value)}
            options={cur && !opts.some((o) => o.value === cur) ? [...opts, { value: cur, label: cur }] : opts}
            placeholder={isRequired(f, doc) ? t("rates.common.choose") : t(f.blank ?? "rates.common.any")}
          />
        </Field>
      )
    }
    case "csv":
      return (
        <Field {...common}>
          <CsvPicker disabled={readOnly} value={String(v || "")} onChange={onChange} options={sourceOptions(t, f.source, boot, lookups, doc)} label={t(f.label)} allLabel={t(f.blank ?? "rates.common.all")} />
        </Field>
      )
    case "date":
      return (
        <Field {...common}>
          <Input type="date" disabled={readOnly} value={String(v || "")} onChange={(e) => onChange(e.target.value)} />
        </Field>
      )
    case "textarea":
      return (
        <Field {...common}>
          <Textarea disabled={readOnly} value={String(v || "")} onChange={(e) => onChange(e.target.value)} rows={3} />
        </Field>
      )
    default:
      return (
        <Field {...common}>
          <Input disabled={readOnly} value={String(v || "")} onChange={(e) => onChange(f.key === "code" || f.key === "extra_code" ? e.target.value.toUpperCase() : e.target.value)} />
        </Field>
      )
  }
}

function TableField({ f, doc, readOnly, lookups, inheritedBands, onChange }: { f: PolicyField; doc: Doc; readOnly: boolean; lookups: Lookups | undefined; inheritedBands?: InheritedBand[]; onChange: (rows: Row[]) => void }) {
  const { t } = useTexT()
  const { boot } = useSession()
  const cols: ColSpec[] = (f.columns ?? []).map((c) => ({
    key: c.key,
    label: t(c.label),
    kind: c.kind,
    help: c.help ? t(c.help) : undefined,
    required: c.required,
    decimals: c.decimals,
    allowNegative: c.allowNegative,
    options: c.options ? enumOptions(t, c.group ?? "", c.options) : c.source ? sourceOptions(t, c.source, boot, lookups, doc, inheritedBands) : undefined,
    placeholder: c.blank ? t(c.blank) : undefined,
    suffix: c.percentWhenOp ? (r: Row) => (PERCENT_OPS.has(String(r.op)) ? "%" : null) : undefined,
    disabled: c.key === "age_band" ? (r: Row) => r.target !== "CHILD" : undefined,
  }))
  const defaults = Object.fromEntries((f.columns ?? []).map((c) => [c.key, c.default ?? (c.kind === "int" || c.kind === "check" ? 0 : "")]))
  return <RowsEditor caption={t(f.label)} columns={cols} rows={(doc[f.key] as Row[]) ?? []} onChange={onChange} readOnly={readOnly} newRow={() => ({ ...defaults }) as Omit<Row, "_key">} addLabel={t("rates.common.add_row")} />
}

/** The picked local wall-clock time as an instant (ISO with offset): the server converts it to
 * the hotel system's time zone, so a browser in another zone schedules the same moment. */
function absoluteTime(local: string): string | null {
  const d = local ? new Date(local) : null
  return d && !Number.isNaN(d.getTime()) ? d.toISOString() : null
}

/** "yyyy-MM-ddTHH:mm" in the browser's time zone, for a datetime-local minimum. */
function localNowMinute(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

function ActivateDialog({ onClose, onConfirm, busy, error }: { onClose: () => void; onConfirm: (at: string | null) => Promise<void>; busy: boolean; error?: TexApiError }) {
  const { t } = useTexT()
  const [when, setWhen] = useState<"now" | "later">("now")
  const [at, setAt] = useState("")
  return (
    <Dialog
      open
      onClose={busy ? () => undefined : onClose}
      title={t("rates.policy.activate_title")}
      description={t("rates.policy.activate_body")}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {t("core.action.cancel")}
          </Button>
          <Button loading={busy} disabled={when === "later" && !at} onClick={() => void onConfirm(when === "later" ? absoluteTime(at) : null).catch(() => undefined)}>
            {t("rates.policy.activate")}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <label className="flex items-center gap-2">
          <input type="radio" name="act-when" checked={when === "now"} onChange={() => setWhen("now")} className="accent-tex-600" />
          {t("rates.policy.activate_now")}
        </label>
        <label className="flex items-center gap-2">
          <input type="radio" name="act-when" checked={when === "later"} onChange={() => setWhen("later")} className="accent-tex-600" />
          {t("rates.policy.activate_at")}
        </label>
        {when === "later" && (
          <Field label={t("rates.f.active_from")} hint={t("rates.h.effective_from")}>
            {/* a revision only ever goes live from now on: the server refuses a past time (G-20) */}
            <Input type="datetime-local" value={at} min={localNowMinute()} onChange={(e) => setAt(e.target.value)} />
          </Field>
        )}
        <InlineError error={error} />
      </div>
    </Dialog>
  )
}

function HistoryDrawer({ open, onClose, doctype, name, slug }: { open: boolean; onClose: () => void; doctype: string; name: string; slug: string }) {
  const { t } = useTexT()
  const q = useTexQuery<HistoryRow[]>("policies", "history", { doctype, name }, [doctype, name, open], open)
  return (
    <Drawer open={open} onClose={onClose} title={t("rates.policy.history")} width="lg">
      <p className="mb-3 text-sm text-zinc-600">{t("rates.policy.history_hint")}</p>
      {q.error ? (
        <ErrorState error={q.error} onRetry={q.reload} />
      ) : (
        <DataTable<HistoryRow>
          caption={t("rates.policy.history")}
          rows={q.data}
          loading={q.loading}
          rowKey={(r) => r.name}
          dense
          columns={[
            {
              key: "revision_no",
              header: t("rates.f.revision"),
              cell: (r) => (
                <Link to={`/tex/rates/policies/${slug}/${encodeURIComponent(r.name)}`} onClick={onClose} className="font-medium text-tex-700 hover:underline" aria-current={r.name === name ? "page" : undefined}>
                  r{r.revision_no}
                  {r.name === name && <span className="ml-1 text-xs text-zinc-500">({t("rates.policy.this_one")})</span>}
                </Link>
              ),
            },
            { key: "tex_status", header: t("rates.f.status"), cell: (r) => <StatusBadge status={r.tex_status} group="rev_status" /> },
            { key: "active_from", header: t("rates.f.active_from"), cell: (r) => (r.active_from ? dateTime(r.active_from) : "—") },
            { key: "active_to", header: t("rates.f.active_to"), hideBelow: "sm", cell: (r) => (r.active_to ? dateTime(r.active_to) : "—") },
            { key: "modified_by", header: t("rates.f.modified_by"), hideBelow: "md" },
          ]}
        />
      )}
    </Drawer>
  )
}
