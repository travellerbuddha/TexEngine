import { Link } from "react-router-dom"
import { ArrowRight, RadioTower, RefreshCw } from "lucide-react"
import { useTexQuery } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { useTexT } from "../../../i18n"
import { Button, Card, EmptyState, ErrorState, Skeleton } from "../../../ui"
import { ConnectFrame } from "../ConnectFrame"
import { ChannelCard } from "./ChannelCard"
import type { Overview } from "./types"

/** /tex/connect/channels — the selected hotel's channel manager connections. */
export default function ChannelList() {
  const { t } = useTexT()
  const { property, can } = useSession()
  const q = useTexQuery<Overview>("distribution", "overview", { property: property?.name }, [property?.name], !!property)
  const conns = q.data?.connections

  return (
    <ConnectFrame
      actions={
        <Button variant="secondary" icon={<RefreshCw className="size-4" aria-hidden />} onClick={q.reload} loading={q.loading && !!q.data}>
          {t("core.action.refresh")}
        </Button>
      }
    >
      <p className="mb-4 max-w-3xl text-sm text-zinc-600">{t("connect.channels.intro")}</p>
      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : !conns ? (
        <div className="grid items-start gap-4 lg:grid-cols-2" aria-busy="true">
          {[0, 1].map((i) => (
            <Card key={i} className="space-y-3 p-4">
              <Skeleton className="h-5 w-48" />
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-9 w-full" />
            </Card>
          ))}
        </div>
      ) : conns.length === 0 ? (
        <Card>
          <EmptyState
            icon={<RadioTower className="size-5" />}
            title={t("connect.channels.empty")}
            description={can("connect.admin") ? t("connect.channels.empty_hint_admin") : t("connect.channels.empty_hint")}
            action={
              can("connect.admin") ? (
                <Link to="/tex/connect" className="inline-flex items-center gap-1 text-sm font-medium text-tex-700 hover:underline">
                  {t("connect.channels.open_connections")} <ArrowRight className="size-4" aria-hidden />
                </Link>
              ) : undefined
            }
          />
        </Card>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          {conns.map((c) => (
            <ChannelCard key={c.name} conn={c} />
          ))}
        </div>
      )}
    </ConnectFrame>
  )
}
