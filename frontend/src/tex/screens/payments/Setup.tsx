import { useState } from "react"
import { AlertTriangle, CheckCircle2, FlaskConical, KeyRound, Pencil, Plus, XCircle } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { useProperty, useSession } from "../../lib/session"
import { useTexT } from "../../i18n"
import { Badge, Button, Card, CardBody, CardHeader, DataTable, EmptyState, ErrorState, Field, FormGrid, IconButton, Notice, PageHeader, Select, Skeleton } from "../../ui"
import { PaymentsNav } from "./components/common"
import { methodKey, useEvent } from "./lib"
import { AccountDrawer } from "./setup/AccountDrawer"
import { RuleDialog } from "./setup/RuleDialog"
import { GATEWAYS, SECRET_FIELDS, type Account, type AccountsResponse, type MethodOption, type Rule } from "./types"

const providerKey = (p: string) => `payments.provider.${p.toLowerCase().replace(/\s+/g, "_")}`

function AccountCard({ a, onEdit }: { a: Account; onEdit: () => void }) {
  const { t } = useTexT()
  const secrets = SECRET_FIELDS.filter((f) => a.secrets_set && f in a.secrets_set)
  const gateway = GATEWAYS.includes(a.provider)
  return (
    <li className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-zinc-900">{a.label}</p>
          <p className="text-xs text-zinc-500">
            {t(providerKey(a.provider))} · <span className="font-mono">{a.name}</span>
          </p>
        </div>
        <IconButton label={t("payments.acc.edit_label", { label: a.label })} icon={<Pencil className="size-4" />} size="sm" onClick={onEdit} />
      </div>
      <div className="flex flex-wrap gap-1.5">
        {a.environment === "Production" ? (
          <Badge tone="danger">{t("payments.env.production")}</Badge>
        ) : (
          <Badge tone="warning">
            <FlaskConical className="size-3" aria-hidden />
            {t("payments.env.sandbox")}
          </Badge>
        )}
        <Badge tone={a.enabled ? "success" : "neutral"}>{a.enabled ? t("payments.acc.enabled_badge") : t("payments.acc.disabled")}</Badge>
        {gateway && !a.production_verified && (
          <Badge tone="warning" title={t("payments.acc.not_verified_short_hint")}>
            <AlertTriangle className="size-3" aria-hidden />
            {t("payments.acc.not_verified_short")}
          </Badge>
        )}
        {a.currencies && <Badge tone="neutral">{a.currencies}</Badge>}
      </div>
      {a.problem && (
        <Notice tone="danger" title={t("payments.acc.problem_title")}>
          {t(`payments.acc.problem.${a.problem}`)}
        </Notice>
      )}
      {a.provider === "Bank Transfer" && (a.bank_name || a.iban) && (
        <p className="text-xs text-zinc-600">
          {a.bank_name} {a.iban && <span className="font-mono">· {a.iban}</span>}
        </p>
      )}
      {gateway && (
        <ul className="grid grid-cols-1 gap-1 text-xs sm:grid-cols-2" aria-label={t("payments.acc.secrets")}>
          {secrets.map((f) => (
            <li key={f} className="flex items-center gap-1.5">
              {a.secrets_set[f] ? <CheckCircle2 className="size-3.5 text-emerald-600" aria-hidden /> : <XCircle className="size-3.5 text-zinc-400" aria-hidden />}
              <span className="text-zinc-700">{t(`payments.acc.field.${f}`)}:</span>
              <span className={a.secrets_set[f] ? "font-medium text-emerald-800" : "text-zinc-500"}>{a.secrets_set[f] ? t("payments.acc.secret_set") : t("payments.acc.secret_not_set")}</span>
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

function MethodsPreview({ property }: { property: string }) {
  const { t } = useTexT()
  const { boot } = useSession()
  const [market, setMarket] = useState("")
  const [currency, setCurrency] = useState("")
  const [channel, setChannel] = useState("")
  const q = useTexQuery<MethodOption[]>("payments", "methods", { property, market: market || undefined, currency: currency || undefined, channel: channel || undefined }, [property, market, currency, channel])
  const any = t("payments.rule.any")
  return (
    <Card>
      <CardHeader title={t("payments.preview.title")} description={t("payments.preview.desc")} />
      <CardBody className="space-y-4">
        <FormGrid cols={3}>
          <Field label={t("payments.rule.market")}>
            <Select value={market} onChange={(e) => setMarket(e.target.value)} options={[{ value: "", label: any }, ...boot.markets.map((m) => ({ value: m.name, label: m.market_name }))]} />
          </Field>
          <Field label={t("payments.currency")}>
            <Select value={currency} onChange={(e) => setCurrency(e.target.value)} options={[{ value: "", label: any }, ...boot.currencies.map((c) => ({ value: c, label: c }))]} />
          </Field>
          <Field label={t("payments.rule.channel")}>
            <Select value={channel} onChange={(e) => setChannel(e.target.value)} options={[{ value: "", label: any }, ...boot.channels.map((c) => ({ value: c.name, label: c.channel_name || c.name }))]} />
          </Field>
        </FormGrid>
        <div aria-live="polite">
          {q.error ? (
            <ErrorState error={q.error} onRetry={q.reload} />
          ) : !q.data ? (
            <Skeleton className="h-8 w-full" />
          ) : q.data.length === 0 ? (
            <Notice tone="warning">{t("payments.preview.none")}</Notice>
          ) : (
            <ol className="flex flex-wrap gap-2">
              {q.data.map((m, i) => (
                <li key={m.method} className="inline-flex items-center gap-2 rounded-lg border border-zinc-200 px-3 py-1.5 text-sm">
                  <span className="text-xs text-zinc-400">{i + 1}.</span>
                  <span className="font-medium">{t(methodKey(m.method))}</span>
                  <span className="text-xs text-zinc-500">{m.label}</span>
                  {m.sandbox && <Badge tone="warning">{t("payments.sandbox")}</Badge>}
                </li>
              ))}
            </ol>
          )}
        </div>
      </CardBody>
    </Card>
  )
}

export default function Setup() {
  const { t } = useTexT()
  const property = useProperty()
  const { can } = useSession()
  const allowed = can("settings.admin")
  const q = useTexQuery<AccountsResponse>("payments", "accounts", { property }, [property], Boolean(property) && allowed)
  const [account, setAccount] = useState<Account | null | undefined>(undefined)
  const [rule, setRule] = useState<Rule | null | undefined>(undefined)
  const closeAccount = useEvent(() => setAccount(undefined))
  const closeRule = useEvent(() => setRule(undefined))
  const accounts = q.data?.accounts ?? []
  const byName = new Map(accounts.map((a) => [a.name, a]))
  const anyProdGateway = accounts.some((a) => a.environment === "Production" && GATEWAYS.includes(a.provider) && a.enabled)

  return (
    <>
      <PageHeader
        title={t("payments.setup.title")}
        subtitle={t("payments.setup.subtitle")}
        crumbs={[{ label: t("core.nav.payments"), to: "/tex/payments" }, { label: t("payments.nav.setup") }]}
      />
      <PaymentsNav />
      {!allowed ? (
        <Card>
          <EmptyState icon={<KeyRound className="size-5" />} title={t("core.error.permission")} description={t("payments.setup.no_access")} />
        </Card>
      ) : q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : (
        <div className="space-y-5">
          <Notice tone={anyProdGateway ? "danger" : "warning"} title={t("payments.setup.verify_title")}>
            {t("payments.setup.verify_body")}
          </Notice>
          <Card>
            <CardHeader
              title={t("payments.setup.accounts")}
              description={t("payments.setup.accounts_hint")}
              actions={
                <Button size="sm" icon={<Plus className="size-4" aria-hidden />} onClick={() => setAccount(null)}>
                  {t("payments.acc.new")}
                </Button>
              }
            />
            <CardBody>
              {!q.data ? (
                <div className="grid gap-3 md:grid-cols-2">
                  <Skeleton className="h-28 w-full" />
                  <Skeleton className="h-28 w-full" />
                </div>
              ) : accounts.length === 0 ? (
                <EmptyState title={t("payments.setup.no_accounts")} description={t("payments.setup.no_accounts_hint")} />
              ) : (
                <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {accounts.map((a) => (
                    <AccountCard key={a.name} a={a} onEdit={() => setAccount(a)} />
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title={t("payments.setup.rules")}
              description={t("payments.setup.rules_hint")}
              actions={
                <Button size="sm" variant="secondary" icon={<Plus className="size-4" aria-hidden />} onClick={() => setRule(null)} disabled={!q.data}>
                  {t("payments.rule.new")}
                </Button>
              }
            />
            <DataTable<Rule>
              caption={t("payments.setup.rules")}
              rows={q.data?.rules}
              loading={q.loading}
              rowKey={(r) => r.name}
              empty={<EmptyState title={t("payments.setup.no_rules")} description={t("payments.setup.no_rules_hint")} />}
              columns={[
                {
                  key: "method",
                  header: t("payments.rule.method"),
                  cell: (r) => (
                    <div>
                      <p className="font-medium">{t(methodKey(r.method))}</p>
                      <p className="text-xs text-zinc-500 md:hidden">{r.provider_account ? byName.get(r.provider_account)?.label ?? r.provider_account : "—"}</p>
                    </div>
                  ),
                },
                { key: "account", header: t("payments.rule.account"), hideBelow: "md", cell: (r) => (r.provider_account ? byName.get(r.provider_account)?.label ?? r.provider_account : "—") },
                { key: "market", header: t("payments.rule.market"), hideBelow: "sm", cell: (r) => r.market || <span className="text-zinc-500">{t("payments.rule.any")}</span> },
                { key: "currency", header: t("payments.currency"), hideBelow: "lg", cell: (r) => r.currency || <span className="text-zinc-500">{t("payments.rule.any")}</span> },
                { key: "channel", header: t("payments.rule.channel"), hideBelow: "lg", cell: (r) => r.sales_channel || <span className="text-zinc-500">{t("payments.rule.any")}</span> },
                { key: "priority", header: t("payments.rule.priority"), align: "right", sortValue: (r) => r.priority ?? 0, cell: (r) => r.priority ?? 0 },
                { key: "state", header: t("core.label.status"), hideBelow: "sm", cell: (r) => <Badge tone={r.disabled ? "neutral" : "success"}>{r.disabled ? t("payments.rule.disabled") : t("payments.rule.active_badge")}</Badge> },
                {
                  key: "edit",
                  header: <span className="sr-only">{t("core.action.edit")}</span>,
                  align: "right",
                  cell: (r) => <IconButton label={t("payments.rule.edit_label", { method: t(methodKey(r.method)) })} icon={<Pencil className="size-4" />} size="sm" onClick={() => setRule(r)} />,
                },
              ]}
            />
          </Card>

          {property && <MethodsPreview property={property} />}

          {property && <AccountDrawer open={account !== undefined} account={account ?? null} property={property} onClose={closeAccount} onSaved={q.reload} />}
          {property && <RuleDialog open={rule !== undefined} rule={rule ?? null} accounts={accounts} property={property} onClose={closeRule} onSaved={q.reload} />}
        </div>
      )}
    </>
  )
}
