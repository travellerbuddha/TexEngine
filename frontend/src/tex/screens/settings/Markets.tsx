import { useMemo, useState } from "react"
import { AlertTriangle, Pencil, Plus } from "lucide-react"
import { useTexMutation, useTexQuery } from "../../lib/api"
import { useSession } from "../../lib/session"
import { TEX_LANGS, useTexT } from "../../i18n"
import {
  Badge,
  Button,
  Card,
  DataTable,
  Drawer,
  EmptyState,
  ErrorState,
  Field,
  FormGrid,
  InlineError,
  Input,
  Notice,
  Select,
  Switch,
  Textarea,
  useToast,
  type Column,
} from "../../ui"
import { SettingsFrame } from "./SettingsFrame"

interface Overlap {
  market: string
  countries: string[]
}

export interface MarketRow {
  name: string
  market_code: string
  market_name: string
  is_global: number
  disabled: number
  countries: string | null
  /** sold on the web only to residents of its countries (O-8, ADR-070) */
  residency_required: number
  default_currency: string | null
  default_language: string | null
  parent_market: string | null
  contracts: number
  overlaps: Overlap[]
}

type Draft = {
  name?: string
  market_code: string
  market_name: string
  is_global: boolean
  disabled: boolean
  countries: string
  residency_required: boolean
  default_currency: string
  default_language: string
  parent_market: string
}

const EMPTY: Draft = {
  market_code: "",
  market_name: "",
  is_global: false,
  disabled: false,
  countries: "",
  residency_required: false,
  default_currency: "",
  default_language: "",
  parent_market: "",
}

function toDraft(m: MarketRow): Draft {
  return {
    name: m.name,
    market_code: m.market_code,
    market_name: m.market_name,
    is_global: !!m.is_global,
    disabled: !!m.disabled,
    countries: m.countries ?? "",
    residency_required: !!m.residency_required,
    default_currency: m.default_currency ?? "",
    default_language: m.default_language ?? "",
    parent_market: m.parent_market ?? "",
  }
}

function countryList(v: string | null) {
  return (v ?? "")
    .split(/[\s,]+/)
    .map((c) => c.trim().toUpperCase())
    .filter(Boolean)
}

function OverlapText({ overlaps }: { overlaps: Overlap[] }) {
  const { t } = useTexT()
  return (
    <>
      {overlaps
        .map((o) => t("settings.markets.overlap_item", { market: o.market, countries: o.countries.join(", ") }))
        .join(" · ")}
    </>
  )
}

/** Markets (R-13): platform master data every contract, markup and payment rule refers to. */
export default function Markets() {
  const { t } = useTexT()
  const { boot, reload: reloadSession } = useSession()
  const platform = boot.user.platform_admin
  const q = useTexQuery<MarketRow[]>("admin", "markets", {}, [])
  const [editing, setEditing] = useState<Draft | null>(null)

  const columns: Column<MarketRow>[] = useMemo(
    () => [
      {
        key: "market_code",
        header: t("settings.markets.code"),
        sortValue: (m) => m.market_code,
        cell: (m) => (
          <span className="inline-flex items-center gap-1.5 font-mono font-semibold text-zinc-900">
            {m.market_code}
            {m.is_global ? <Badge tone="brand">{t("settings.markets.global")}</Badge> : null}
          </span>
        ),
      },
      { key: "market_name", header: t("settings.markets.name"), sortValue: (m) => m.market_name },
      {
        key: "countries",
        header: t("settings.markets.countries"),
        hideBelow: "md",
        cell: (m) => {
          const list = countryList(m.countries)
          if (m.is_global) return <span className="text-zinc-500">{t("settings.markets.all_other")}</span>
          if (!list.length) return <span className="text-zinc-400">—</span>
          return (
            <span className="block max-w-72 truncate font-mono text-xs" title={list.join(", ")}>
              {list.join(", ")}
            </span>
          )
        },
      },
      { key: "default_currency", header: t("settings.markets.currency"), hideBelow: "sm", cell: (m) => m.default_currency ?? "—" },
      {
        key: "contracts",
        header: t("settings.markets.contracts"),
        align: "right",
        hideBelow: "sm",
        sortValue: (m) => m.contracts,
        cell: (m) => m.contracts,
      },
      {
        key: "status",
        header: t("settings.markets.status"),
        cell: (m) => (
          <span className="inline-flex flex-wrap items-center gap-1.5">
            <Badge tone={m.disabled ? "neutral" : "success"}>{t(m.disabled ? "settings.markets.disabled" : "settings.markets.active")}</Badge>
            {m.residency_required ? <Badge tone="info">{t("settings.markets.residents_badge")}</Badge> : null}
            {m.overlaps.length > 0 && (
              <Badge tone="warning" title={m.overlaps.map((o) => `${o.market}: ${o.countries.join(", ")}`).join("; ")}>
                <AlertTriangle className="size-3" aria-hidden />
                {t("settings.markets.overlap_badge")}
              </Badge>
            )}
          </span>
        ),
      },
      ...(platform
        ? [
            {
              key: "edit",
              header: <span className="sr-only">{t("core.action.edit")}</span>,
              align: "right" as const,
              hideBelow: "sm" as const,
              cell: (m: MarketRow) => (
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Pencil className="size-3.5" aria-hidden />}
                  aria-label={`${t("core.action.edit")}: ${m.market_code}`}
                  onClick={(e) => {
                    e.stopPropagation()
                    setEditing(toDraft(m))
                  }}
                >
                  <span className="hidden sm:inline">{t("core.action.edit")}</span>
                </Button>
              ),
            },
          ]
        : []),
    ],
    [t, platform],
  )

  const overlapping = (q.data ?? []).filter((m) => m.overlaps.length)
  return (
    <SettingsFrame
      subtitle={t("settings.markets.subtitle")}
      actions={
        platform ? (
          <Button icon={<Plus className="size-4" aria-hidden />} onClick={() => setEditing({ ...EMPTY })}>
            {t("settings.markets.new")}
          </Button>
        ) : undefined
      }
    >
      <div className="space-y-4">
        {!platform && <Notice tone="info">{t("settings.markets.read_only")}</Notice>}
        {overlapping.length > 0 && (
          <Notice tone="warning" title={t("settings.markets.overlap_title")}>
            {t("settings.markets.overlap_body")}{" "}
            <OverlapText overlaps={overlapping.flatMap((m) => m.overlaps.map((o) => ({ ...o, market: `${m.market_code} ↔ ${o.market}` })))} />
          </Notice>
        )}
        {q.error ? (
          <Card>
            <ErrorState error={q.error} onRetry={q.reload} />
          </Card>
        ) : (
          <Card>
            <DataTable
              caption={t("settings.markets.caption")}
              columns={columns}
              rows={q.data}
              loading={q.loading}
              rowKey={(m) => m.name}
              onRowClick={platform ? (m) => setEditing(toDraft(m)) : undefined}
              initialSort={{ key: "market_code", dir: "asc" }}
              empty={<EmptyState title={t("settings.markets.empty")} />}
            />
          </Card>
        )}
      </div>
      <MarketEditor
        draft={editing}
        markets={q.data ?? []}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null)
          q.reload()
          // contract, markup and search pickers read markets from the session
          void reloadSession()
        }}
      />
    </SettingsFrame>
  )
}

function MarketEditor({
  draft,
  markets,
  onClose,
  onSaved,
}: {
  draft: Draft | null
  markets: MarketRow[]
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useTexT()
  const { boot } = useSession()
  const toast = useToast()
  const save = useTexMutation<{ data: Draft }, { name: string; overlaps: Overlap[] }>("admin", "save_market")
  const [d, setD] = useState<Draft | null>(draft)
  const [key, setKey] = useState(draft)
  // re-seed the form whenever another market is opened
  if (draft !== key) {
    setKey(draft)
    setD(draft)
    save.clearError()
  }
  if (!d) return null
  const isNew = !d.name
  const set = (patch: Partial<Draft>) => setD({ ...d, ...patch })
  const codeOk = !isNew || /^[A-Z0-9_]{2,20}$/.test(d.market_code)
  const valid = codeOk && d.market_name.trim().length > 0
  const submit = async () => {
    const out = await save.run({ data: { ...d, countries: countryList(d.countries).join(", ") } })
    if (out.overlaps.length)
      toast.info(
        <>
          {t("settings.markets.saved_overlap")} <OverlapText overlaps={out.overlaps} />
        </>,
      )
    else toast.success(t("settings.markets.saved", { code: out.name }))
    onSaved()
  }
  return (
    <Drawer
      open
      onClose={onClose}
      title={isNew ? t("settings.markets.new") : t("settings.markets.edit_title", { code: d.market_code })}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={save.pending}>
            {t("core.action.cancel")}
          </Button>
          <Button onClick={() => void submit().catch(() => undefined)} loading={save.pending} disabled={!valid}>
            {t("core.action.save")}
          </Button>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (valid) void submit().catch(() => undefined)
        }}
      >
        <FormGrid>
          <Field label={t("settings.markets.code")} required hint={isNew ? t("settings.markets.code_hint") : t("settings.markets.code_fixed")} error={!codeOk && d.market_code ? t("settings.markets.code_invalid") : undefined}>
            <Input
              value={d.market_code}
              onChange={(e) => set({ market_code: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "") })}
              disabled={!isNew}
              maxLength={20}
              className="font-mono"
              data-autofocus
            />
          </Field>
          <Field label={t("settings.markets.name")} required>
            <Input value={d.market_name} onChange={(e) => set({ market_name: e.target.value })} maxLength={140} />
          </Field>
        </FormGrid>
        <Switch
          checked={d.is_global}
          onChange={(v) => set({ is_global: v, countries: v ? "" : d.countries, residency_required: v ? false : d.residency_required })}
          label={t("settings.markets.is_global")}
          description={t("settings.markets.is_global_hint")}
        />
        {!d.is_global && (
          <Field label={t("settings.markets.countries")} hint={t("settings.markets.countries_hint")}>
            <Textarea value={d.countries} onChange={(e) => set({ countries: e.target.value.toUpperCase() })} rows={3} className="font-mono" />
          </Field>
        )}
        {!d.is_global && (
          <Switch
            checked={d.residency_required}
            onChange={(v) => set({ residency_required: v })}
            label={t("settings.markets.residents_only")}
            description={t("settings.markets.residents_only_hint")}
          />
        )}
        <FormGrid>
          <Field label={t("settings.markets.currency")}>
            <Select
              value={d.default_currency}
              onChange={(e) => set({ default_currency: e.target.value })}
              placeholder={t("settings.markets.none")}
              options={boot.currencies.map((c) => ({ value: c, label: c }))}
            />
          </Field>
          <Field label={t("settings.markets.language")}>
            <Select
              value={d.default_language}
              onChange={(e) => set({ default_language: e.target.value })}
              placeholder={t("settings.markets.none")}
              options={TEX_LANGS.map((l) => ({ value: l.code, label: l.label }))}
            />
          </Field>
        </FormGrid>
        <Field label={t("settings.markets.parent")} hint={t("settings.markets.parent_hint")}>
          <Select
            value={d.parent_market}
            onChange={(e) => set({ parent_market: e.target.value })}
            placeholder={t("settings.markets.none")}
            options={markets.filter((m) => m.name !== d.name).map((m) => ({ value: m.name, label: `${m.market_code} · ${m.market_name}` }))}
          />
        </Field>
        {!isNew && (
          <Switch
            checked={d.disabled}
            onChange={(v) => set({ disabled: v })}
            label={t("settings.markets.disable")}
            description={t("settings.markets.disable_hint")}
          />
        )}
        <InlineError error={save.error} />
        <button type="submit" hidden />
      </form>
    </Drawer>
  )
}
