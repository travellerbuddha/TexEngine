import { Link, useParams, useSearchParams } from "react-router-dom"
import { ArrowLeft, ArrowRight, PowerOff, RadioTower, RefreshCw } from "lucide-react"
import { useTexQuery } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { dateTime } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, Card, CardBody, EmptyState, ErrorState, Notice, Skeleton, TabPanel, Tabs } from "../../../ui"
import { CodeBlock } from "../../settings/components/common"
import { ConnectFrame } from "../ConnectFrame"
import { SyncStatus } from "./ChannelCard"
import { adapterLabel, CertificationNotice, ConnectionCounts, EnabledBadge, EnvBadge, Fact } from "./common"
import { AriTab } from "./AriTab"
import { InboundTab } from "./InboundTab"
import { MappingsTab } from "./MappingsTab"
import { ReconcileTab } from "./ReconcileTab"
import { SandboxTab } from "./SandboxTab"
import type { ChannelConnection, ChannelTab, Lookups, Mapping, Overview, TabProps } from "./types"

const ALL_TABS: ChannelTab[] = ["mappings", "ari", "bookings", "reconcile", "sandbox"]

/** /tex/connect/channels/:name — one channel connection: mappings, ARI, bookings,
 * reconciliation and (sandbox connections only) a booking simulator. */
export default function ChannelDetail() {
  const { t } = useTexT()
  const { name = "" } = useParams()
  const { property, can } = useSession()
  const [params, setParams] = useSearchParams()
  const overview = useTexQuery<Overview>("distribution", "overview", { property: property?.name }, [property?.name], !!property)
  const lookups = useTexQuery<Lookups>("distribution", "lookups", { connection: name }, [name], !!name)
  const mappings = useTexQuery<Mapping[]>("distribution", "mappings", { connection: name }, [name], !!name)
  const conn = overview.data?.connections.find((c) => c.name === name)
  const canManage = !!overview.data?.can_manage && can("channel.manage")

  const tabs = ALL_TABS.filter((id) => id !== "sandbox" || (canManage && !!lookups.data?.adapter.sandbox))
  const requested = params.get("tab") as ChannelTab | null
  const tab: ChannelTab = requested && tabs.includes(requested) ? requested : "mappings"
  const goTo = (id: ChannelTab) => {
    const next = new URLSearchParams(params)
    if (id === "mappings") next.delete("tab")
    else next.set("tab", id)
    setParams(next, { replace: true })
  }

  const crumbs = [
    { label: t("core.nav.connect"), to: "/tex/connect" },
    { label: t("connect.nav.channels"), to: "/tex/connect/channels" },
    { label: conn?.label ?? name },
  ]

  if (overview.error)
    return (
      <ConnectFrame crumbs={crumbs}>
        <Card>
          <ErrorState error={overview.error} onRetry={overview.reload} />
        </Card>
      </ConnectFrame>
    )
  if (!overview.data)
    return (
      <ConnectFrame crumbs={crumbs}>
        <Card className="space-y-3 p-4" aria-busy="true">
          <Skeleton className="h-5 w-56" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-9 w-full" />
        </Card>
      </ConnectFrame>
    )
  if (!conn)
    return (
      <ConnectFrame crumbs={crumbs}>
        <Card>
          <EmptyState
            icon={<RadioTower className="size-5" />}
            title={t("connect.channels.not_found")}
            description={t("connect.channels.not_found_hint", { hotel: property?.property_name ?? "" })}
            action={
              <Link to="/tex/connect/channels" className="inline-flex items-center gap-1 text-sm font-medium text-tex-700 hover:underline">
                <ArrowLeft className="size-4" aria-hidden /> {t("connect.channels.back")}
              </Link>
            }
          />
        </Card>
      </ConnectFrame>
    )

  const props: TabProps = { connection: name, conn, lookups, mappings, canManage, onChanged: overview.reload, goTo }
  const problems = conn.inbound.Failed + conn.inbound.Dead
  return (
    <ConnectFrame
      title={conn.label}
      subtitle={adapterLabel(t, conn.adapter)}
      crumbs={crumbs}
      meta={
        <>
          <EnvBadge env={conn.environment} />
          <EnabledBadge enabled={conn.enabled} />
          {conn.certified ? <Badge tone="success">{t("connect.channels.certified")}</Badge> : <Badge tone="warning">{t("connect.channels.uncertified.badge")}</Badge>}
        </>
      }
      actions={
        <Button
          variant="secondary"
          icon={<RefreshCw className="size-4" aria-hidden />}
          loading={overview.loading}
          onClick={() => {
            overview.reload()
            mappings.reload()
          }}
        >
          {t("core.action.refresh")}
        </Button>
      }
    >
      <div className="space-y-4">
        {!conn.enabled && <SwitchedOffNotice />}
        {!conn.certified && <CertificationNotice />}
        <ConnectionSummary conn={conn} />
        <Card>
          <Tabs
            label={t("connect.channels.sections")}
            value={tab}
            onChange={(id) => goTo(id as ChannelTab)}
            className="px-2"
            tabs={tabs.map((id) => ({
              id,
              label: t(`connect.channels.tab.${id}`),
              badge:
                id === "mappings" && mappings.data ? (
                  <Badge>{mappings.data.length}</Badge>
                ) : id === "bookings" && problems > 0 ? (
                  <Badge tone="danger">
                    <span aria-hidden>{problems}</span>
                    <span className="sr-only">{t("connect.channels.inbound.problems", { count: problems })}</span>
                  </Badge>
                ) : undefined,
            }))}
          />
          <TabPanel id={tab} className="min-w-0">
            {tab === "mappings" && <MappingsTab {...props} />}
            {tab === "ari" && <AriTab {...props} />}
            {tab === "bookings" && <InboundTab {...props} />}
            {tab === "reconcile" && <ReconcileTab {...props} />}
            {tab === "sandbox" && <SandboxTab {...props} />}
          </TabPanel>
        </Card>
      </div>
    </ConnectFrame>
  )
}

/** A switched-off connection sends no ARI and its webhook refuses bookings (the sandbox
 * too); messages already received are still applied by the queue. */
function SwitchedOffNotice() {
  const { t } = useTexT()
  const { can } = useSession()
  return (
    <Notice
      tone="warning"
      title={
        <span className="inline-flex items-center gap-1.5">
          <PowerOff className="size-4 shrink-0" aria-hidden />
          {t("connect.channels.off.title")}
        </span>
      }
    >
      <p>{t("connect.channels.off.body")}</p>
      {can("connect.admin") ? (
        <Link to="/tex/connect" className="mt-1 inline-flex items-center gap-1 font-medium text-amber-950 underline hover:no-underline">
          {t("connect.channels.off.enable")} <ArrowRight className="size-4" aria-hidden />
        </Link>
      ) : (
        <p className="mt-1">{t("connect.channels.off.ask")}</p>
      )}
    </Notice>
  )
}

/** Health of the connection: last sync, queues and the webhook address. */
function ConnectionSummary({ conn }: { conn: ChannelConnection }) {
  const { t } = useTexT()
  return (
    <Card>
      <CardBody className="grid gap-4 lg:grid-cols-2">
        <div className="min-w-0 space-y-3">
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Fact label={t("connect.channels.last_sync")}>{conn.last_sync_at ? dateTime(conn.last_sync_at) : "—"}</Fact>
            <Fact label={t("connect.channels.last_status")}>
              <SyncStatus status={conn.last_status} />
            </Fact>
            <Fact label={t("connect.channels.mappings")}>{t("connect.channels.mapping_count", { count: conn.mappings })}</Fact>
          </dl>
          {conn.last_error && (
            <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs break-words text-rose-800">
              <span className="font-semibold">{t("connect.status.last_error")}: </span>
              {conn.last_error}
            </p>
          )}
          <ConnectionCounts conn={conn} />
        </div>
        <div className="min-w-0 space-y-1">
          <CodeBlock value={conn.webhook_url} label={t("connect.channels.webhook")} />
          <p className="text-xs text-zinc-500">{t("connect.channels.webhook_hint")}</p>
        </div>
      </CardBody>
    </Card>
  )
}
