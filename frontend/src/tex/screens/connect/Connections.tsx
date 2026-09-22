import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { ArrowRight, Coins, Plus, PlugZap, Trash2 } from "lucide-react"
import { tex, TexApiError, useTexMutation, useTexQuery } from "../../lib/api"
import { useSession } from "../../lib/session"
import { date, dateTime } from "../../lib/format"
import { useTexT } from "../../i18n"
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ConfirmDialog,
  DataTable,
  DescriptionList,
  Drawer,
  EmptyState,
  ErrorState,
  Field,
  FormGrid,
  InlineError,
  Input,
  Notice,
  Segmented,
  Select,
  Skeleton,
  Switch,
  Textarea,
  useToast,
} from "../../ui"
import { ConnectFrame, CATEGORIES, categoryKey } from "./ConnectFrame"

const DOCTYPE = "TEX Integration Connection"

interface ConnRow {
  name: string
  label: string
  category: string
  adapter: string
  enabled: number
  property: string | null
  modified: string
}

interface ConnDoc extends ConnRow {
  environment: "Sandbox" | "Production"
  endpoint_url: string | null
  api_key: string | null
  settings_json: string | null
  last_sync_at: string | null
  last_status: string | null
  last_error: string | null
}

interface AdapterDef {
  key: string
  category: string
  label: string
}

interface TestResult {
  ok: boolean
  error?: string
  [k: string]: unknown
}

interface FxRate {
  provider: string
  base_currency: string
  quote_currency: string
  rate_date: string
  fetched_at: string | null
}

export default function Connections() {
  const { t } = useTexT()
  const toast = useToast()
  const { boot, property } = useSession()
  const list = useTexQuery<ConnRow[]>("policies", "list_records", { doctype: DOCTYPE, property: property?.name }, [property?.name])
  const adapters = useTexQuery<AdapterDef[]>("admin", "adapters", {}, [])
  const [editing, setEditing] = useState<string | "new" | null>(null)
  const [testing, setTesting] = useState<string | null>(null)
  const adapterLabel = (k: string) => adapters.data?.find((a) => a.key === k)?.label ?? k

  const runTest = async (name: string) => {
    setTesting(name)
    try {
      const r = await tex<TestResult>("admin", "test_connection", { name }, { post: true })
      if (r.ok) toast.success(t("connect.test.ok"))
      else toast.error(t("connect.test.failed", { error: r.error ?? "" }))
    } catch (e) {
      toast.error((e as TexApiError).message)
    } finally {
      setTesting(null)
    }
  }

  return (
    <ConnectFrame
      actions={
        <Button icon={<Plus className="size-4" aria-hidden />} onClick={() => setEditing("new")}>
          {t("connect.new")}
        </Button>
      }
    >
      <div className="grid items-start gap-4 lg:grid-cols-3">
        <Card className="min-w-0 lg:col-span-2">
          <CardHeader title={t("connect.list.title")} description={t("connect.list.hint")} />
          {list.error ? (
            <ErrorState error={list.error} onRetry={list.reload} />
          ) : (
            <DataTable<ConnRow>
              caption={t("connect.list.title")}
              rows={list.data}
              loading={list.loading}
              rowKey={(r) => r.name}
              onRowClick={(r) => setEditing(r.name)}
              initialSort={{ key: "label", dir: "asc" }}
              empty={
                <EmptyState
                  icon={<PlugZap className="size-5" />}
                  title={t("connect.list.empty")}
                  description={t("connect.list.empty_hint")}
                  action={
                    <Button variant="secondary" icon={<Plus className="size-4" aria-hidden />} onClick={() => setEditing("new")}>
                      {t("connect.new")}
                    </Button>
                  }
                />
              }
              columns={[
                {
                  key: "label",
                  header: t("connect.field.label"),
                  sortValue: (r) => r.label,
                  cell: (r) => (
                    <span>
                      <span className="font-medium text-zinc-900">{r.label}</span>
                      <span className="block text-xs text-zinc-500">{adapterLabel(r.adapter)}</span>
                    </span>
                  ),
                },
                { key: "category", header: t("connect.field.category"), hideBelow: "sm", sortValue: (r) => r.category, cell: (r) => t(categoryKey(r.category)) },
                {
                  key: "property",
                  header: t("connect.field.hotel"),
                  hideBelow: "md",
                  cell: (r) =>
                    r.property ? (
                      (boot.properties.find((p) => p.name === r.property)?.property_name ?? r.property)
                    ) : (
                      <Badge tone="info">{t("connect.all_hotels")}</Badge>
                    ),
                },
                {
                  key: "enabled",
                  header: t("connect.field.status"),
                  cell: (r) => (r.enabled ? <Badge tone="success">{t("connect.enabled")}</Badge> : <Badge tone="neutral">{t("connect.disabled")}</Badge>),
                },
                {
                  key: "test",
                  header: <span className="sr-only">{t("connect.test.run")}</span>,
                  align: "right",
                  cell: (r) => (
                    <Button
                      variant="secondary"
                      size="sm"
                      loading={testing === r.name}
                      aria-label={`${t("connect.test.run")}: ${r.label}`}
                      onClick={(e) => {
                        e.stopPropagation()
                        void runTest(r.name)
                      }}
                      onKeyDown={(e) => e.stopPropagation()}
                    >
                      {t("connect.test.run")}
                    </Button>
                  ),
                },
              ]}
            />
          )}
        </Card>
        <FxCard />
      </div>
      <ConnectionDrawer
        name={editing}
        adapters={adapters.data ?? []}
        onClose={() => setEditing(null)}
        onSaved={(n) => {
          list.reload()
          if (n) setEditing(n)
        }}
        onDeleted={() => {
          setEditing(null)
          list.reload()
        }}
      />
    </ConnectFrame>
  )
}

// ─── FX provider info (the FX screen itself belongs to Rates & Contracts) ──

function FxCard() {
  const { t } = useTexT()
  const tcmb = useTexQuery<FxRate[]>("policies", "fx_rates", { provider: "TCMB", days: 14 }, [])
  const ecb = useTexQuery<FxRate[]>("policies", "fx_rates", { provider: "ECB", days: 14 }, [])
  const rows = [
    { id: "TCMB", q: tcmb },
    { id: "ECB", q: ecb },
  ]
  return (
    <Card>
      <CardHeader title={t("connect.fx.title")} description={t("connect.fx.hint")} />
      <CardBody className="space-y-3">
        <ul className="space-y-2.5">
          {rows.map(({ id, q }) => {
            const latest = q.data?.[0]
            const pairs = latest ? q.data!.filter((r) => r.rate_date === latest.rate_date).length : 0
            return (
              <li key={id} className="flex items-start gap-2.5">
                <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-md bg-zinc-100 text-zinc-600" aria-hidden>
                  <Coins className="size-3.5" />
                </span>
                <div className="min-w-0 text-sm">
                  <p className="font-medium text-zinc-900">{t(`connect.fx.${id}`)}</p>
                  <p className="text-xs text-zinc-500">
                    {q.loading && !q.data ? (
                      <Skeleton className="mt-1 h-3 w-32" />
                    ) : q.error ? (
                      q.error.isPermission ? t("connect.fx.no_access") : q.error.message
                    ) : latest ? (
                      t("connect.fx.latest", { date: date(latest.rate_date), count: pairs })
                    ) : (
                      t("connect.fx.none")
                    )}
                  </p>
                </div>
              </li>
            )
          })}
        </ul>
        <p className="text-xs text-zinc-500">{t("connect.fx.manual")}</p>
        <Link to="/tex/rates" className="inline-flex items-center gap-1 text-sm font-medium text-tex-700 hover:underline">
          {t("connect.fx.open")} <ArrowRight className="size-4" aria-hidden />
        </Link>
      </CardBody>
    </Card>
  )
}

// ─── editor ──────────────────────────────────────────────────────────────

interface Form {
  label: string
  property: string
  category: string
  adapter: string
  enabled: boolean
  environment: "Sandbox" | "Production"
  endpoint_url: string
  api_key: string
  secret: string
  settings_json: string
}

const EMPTY: Form = {
  label: "",
  property: "",
  category: "PMS",
  adapter: "",
  enabled: true,
  environment: "Sandbox",
  endpoint_url: "",
  api_key: "",
  secret: "",
  settings_json: "",
}

function toForm(d: ConnDoc): Form {
  return {
    label: d.label ?? "",
    property: d.property ?? "",
    category: d.category ?? "PMS",
    adapter: d.adapter ?? "",
    enabled: !!d.enabled,
    environment: d.environment ?? "Sandbox",
    endpoint_url: d.endpoint_url ?? "",
    api_key: d.api_key ?? "",
    secret: "",
    settings_json: d.settings_json ?? "",
  }
}

function ConnectionDrawer({
  name,
  adapters,
  onClose,
  onSaved,
  onDeleted,
}: {
  name: string | "new" | null
  adapters: AdapterDef[]
  onClose: () => void
  onSaved: (name?: string) => void
  onDeleted: () => void
}) {
  const { t } = useTexT()
  const toast = useToast()
  const { boot, property } = useSession()
  const isNew = name === "new"
  const doc = useTexQuery<ConnDoc>("policies", "get_record", { doctype: DOCTYPE, name }, [name], !!name && !isNew)
  const save = useTexMutation<{ doctype: string; data: Record<string, unknown> }, ConnDoc>("policies", "save_record")
  const [form, setForm] = useState<Form>(EMPTY)
  const [initial, setInitial] = useState<Form>(EMPTY)
  const [touched, setTouched] = useState(false)
  const [test, setTest] = useState<TestResult | null>(null)
  const [testing, setTesting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  useEffect(() => {
    setTouched(false)
    setTest(null)
    save.clearError()
    if (isNew) {
      const f = { ...EMPTY, property: property?.name ?? "" }
      setForm(f)
      setInitial(f)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name])
  useEffect(() => {
    if (doc.data && !isNew) {
      const f = toForm(doc.data)
      setForm(f)
      setInitial(f)
    }
  }, [doc.data, isNew])

  const dirty = JSON.stringify(form) !== JSON.stringify(initial)
  const hotels = boot.properties.filter((p) => boot.user.platform_admin || p.capabilities.includes("connect.admin"))
  const forCategory = adapters.filter((a) => a.category === form.category)
  const adapterKnown = adapters.some((a) => a.key === form.adapter)

  const errors = useMemo(() => {
    const e: Partial<Record<keyof Form, string>> = {}
    if (!form.label.trim()) e.label = t("connect.err.required")
    if (!form.adapter.trim()) e.adapter = t("connect.err.required")
    if (form.endpoint_url && !/^https:\/\/[^\s/$.?#].[^\s]*$/i.test(form.endpoint_url.trim())) e.endpoint_url = t("connect.err.https")
    if (form.settings_json.trim()) {
      try {
        const v = JSON.parse(form.settings_json) as unknown
        if (typeof v !== "object" || v === null || Array.isArray(v)) e.settings_json = t("connect.err.json")
      } catch {
        e.settings_json = t("connect.err.json")
      }
    }
    if (!form.property && !boot.user.platform_admin) e.property = t("connect.err.required")
    return e
  }, [form, t, boot.user.platform_admin])
  const valid = Object.keys(errors).length === 0

  const submit = async () => {
    setTouched(true)
    if (!valid) return
    const data: Record<string, unknown> = {
      label: form.label.trim(),
      property: form.property || null,
      category: form.category,
      adapter: form.adapter.trim(),
      enabled: form.enabled ? 1 : 0,
      environment: form.environment,
      endpoint_url: form.endpoint_url.trim() || null,
      api_key: form.api_key.trim() || null,
      settings_json: form.settings_json.trim() || null,
    }
    // write-only: send the secret only when the user typed a new one
    if (form.secret) data.secret = form.secret
    if (!isNew && name) data.name = name
    try {
      const saved = await save.run({ doctype: DOCTYPE, data })
      toast.success(t("core.saved"))
      const f = toForm(saved)
      setForm(f)
      setInitial(f)
      setTest(null)
      onSaved(saved.name)
    } catch {
      /* inline */
    }
  }

  const runTest = async () => {
    if (!name || isNew) return
    setTesting(true)
    setTest(null)
    try {
      setTest(await tex<TestResult>("admin", "test_connection", { name }, { post: true }))
      doc.reload()
    } catch (e) {
      setTest({ ok: false, error: (e as TexApiError).message })
    } finally {
      setTesting(false)
    }
  }

  const d = doc.data
  return (
    <Drawer
      open={!!name}
      onClose={onClose}
      width="lg"
      title={isNew ? t("connect.new") : (d?.label ?? t("connect.edit"))}
      footer={
        <>
          {!isNew && (
            <Button variant="ghost" className="mr-auto text-rose-700" icon={<Trash2 className="size-4" aria-hidden />} onClick={() => setConfirmDelete(true)}>
              {t("core.action.delete")}
            </Button>
          )}
          {!isNew && (
            <Button variant="secondary" loading={testing} disabled={dirty} title={dirty ? t("connect.test.save_first") : undefined} onClick={runTest}>
              {t("connect.test.run")}
            </Button>
          )}
          <Button loading={save.pending} disabled={!dirty && !isNew} onClick={submit}>
            {t("core.action.save")}
          </Button>
        </>
      }
    >
      {doc.error && !isNew ? (
        <ErrorState error={doc.error} onRetry={doc.reload} />
      ) : !isNew && !d ? (
        <div className="space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : (
        <form
          className="space-y-5"
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
        >
          <InlineError error={save.error} />
          {test && (
            <Notice tone={test.ok ? "success" : "danger"} title={test.ok ? t("connect.test.ok") : t("connect.test.failed_title")}>
              {test.ok ? t("connect.test.ok_hint") : test.error}
            </Notice>
          )}
          {dirty && !isNew && <p className="text-xs text-amber-800">{t("connect.test.save_first")}</p>}
          <FormGrid>
            <Field label={t("connect.field.label")} required error={touched ? errors.label : undefined}>
              <Input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} maxLength={140} data-autofocus />
            </Field>
            <Field label={t("connect.field.hotel")} required={!boot.user.platform_admin} error={touched ? errors.property : undefined}>
              <Select
                value={form.property}
                onChange={(e) => setForm({ ...form, property: e.target.value })}
                placeholder={boot.user.platform_admin ? t("connect.all_hotels") : t("connect.select")}
                options={hotels.map((h) => ({ value: h.name, label: h.property_name }))}
              />
            </Field>
            <Field label={t("connect.field.category")} required>
              <Select
                value={form.category}
                onChange={(e) => {
                  const category = e.target.value
                  const first = adapters.find((a) => a.category === category)
                  setForm({ ...form, category, adapter: adapters.some((a) => a.key === form.adapter && a.category === category) ? form.adapter : (first?.key ?? "") })
                }}
                options={CATEGORIES.map((c) => ({ value: c, label: t(categoryKey(c)) }))}
              />
            </Field>
            {forCategory.length > 0 ? (
              <Field label={t("connect.field.adapter")} required error={touched ? errors.adapter : undefined}>
                <Select
                  value={form.adapter}
                  placeholder={t("connect.select")}
                  onChange={(e) => setForm({ ...form, adapter: e.target.value })}
                  options={[
                    ...forCategory.map((a) => ({ value: a.key, label: a.label })),
                    ...(form.adapter && !adapterKnown ? [{ value: form.adapter, label: t("connect.adapter_missing", { key: form.adapter }) }] : []),
                  ]}
                />
              </Field>
            ) : (
              <Field label={t("connect.field.adapter")} required error={touched ? errors.adapter : undefined} hint={t("connect.no_adapter")}>
                <Input value={form.adapter} onChange={(e) => setForm({ ...form, adapter: e.target.value })} className="font-mono" />
              </Field>
            )}
          </FormGrid>

          <div className="space-y-2">
            <span className="block text-sm font-medium text-zinc-800" aria-hidden>
              {t("connect.field.environment")}
            </span>
            <Segmented<"Sandbox" | "Production">
              label={t("connect.field.environment")}
              value={form.environment}
              onChange={(v) => setForm({ ...form, environment: v })}
              options={[
                { value: "Sandbox", label: t("connect.env.sandbox") },
                { value: "Production", label: t("connect.env.production") },
              ]}
            />
            {form.environment === "Production" && <Notice tone="warning">{t("connect.env.production_warning")}</Notice>}
          </div>

          <Field label={t("connect.field.endpoint")} error={touched ? errors.endpoint_url : undefined} hint={t("connect.field.endpoint_hint")}>
            <Input type="url" inputMode="url" value={form.endpoint_url} placeholder="https://" onChange={(e) => setForm({ ...form, endpoint_url: e.target.value })} />
          </Field>
          <FormGrid>
            <Field label={t("connect.field.api_key")}>
              <Input value={form.api_key} autoComplete="off" spellCheck={false} onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
            </Field>
            <Field label={t("connect.field.secret")} hint={isNew ? t("connect.field.secret_hint_new") : t("connect.field.secret_hint")}>
              <Input
                type="password"
                value={form.secret}
                autoComplete="new-password"
                spellCheck={false}
                placeholder={isNew ? "" : "••••••••"}
                onChange={(e) => setForm({ ...form, secret: e.target.value })}
              />
            </Field>
          </FormGrid>
          <Switch checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} label={t("connect.field.enabled")} description={t("connect.field.enabled_hint")} />

          <details className="rounded-lg border border-zinc-200 px-3 py-2" open={!!form.settings_json}>
            <summary className="cursor-pointer text-sm font-medium text-zinc-800">{t("connect.field.advanced")}</summary>
            <div className="mt-3">
              <Field label={t("connect.field.settings_json")} error={touched ? errors.settings_json : undefined} hint={t("connect.field.settings_json_hint")}>
                <Textarea
                  rows={5}
                  className="font-mono text-xs"
                  spellCheck={false}
                  value={form.settings_json}
                  onChange={(e) => setForm({ ...form, settings_json: e.target.value })}
                />
              </Field>
            </div>
          </details>

          {d && (
            <section className="rounded-lg border border-zinc-200 bg-zinc-50/60 p-3">
              <h3 className="mb-2 text-sm font-semibold text-zinc-900">{t("connect.status.title")}</h3>
              <DescriptionList
                items={[
                  {
                    label: t("connect.status.last_test"),
                    value: d.last_status ? (
                      <Badge tone={d.last_status === "OK" ? "success" : "danger"}>{d.last_status === "OK" ? t("connect.status.ok") : t("connect.status.error")}</Badge>
                    ) : (
                      t("connect.status.never")
                    ),
                  },
                  { label: t("connect.status.last_sync"), value: d.last_sync_at ? dateTime(d.last_sync_at) : "—" },
                  ...(d.last_error ? [{ label: t("connect.status.last_error"), value: <span className="text-rose-800">{d.last_error}</span> }] : []),
                ]}
              />
            </section>
          )}
        </form>
      )}
      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        tone="danger"
        title={t("connect.delete.title")}
        body={t("connect.delete.body", { label: d?.label ?? "" })}
        confirmLabel={t("core.action.delete")}
        onConfirm={async () => {
          await tex("policies", "delete_record", { doctype: DOCTYPE, name }, { post: true })
          toast.success(t("connect.delete.done"))
          onDeleted()
        }}
      />
    </Drawer>
  )
}
