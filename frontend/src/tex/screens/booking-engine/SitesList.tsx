import { useNavigate } from "react-router-dom"
import { ExternalLink, Globe, Languages, Plus } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { useSession } from "../../lib/session"
import { dateTime } from "../../lib/format"
import { useTexT } from "../../i18n"
import { Badge, Button, Card, CardHeader, DataTable, EmptyState, ErrorState, PageHeader } from "../../ui"

interface SiteRow {
  name: string
  site_name: string
  site_slug: string
  enabled: number
  property: string | null
  modified: string
}

export default function SitesList() {
  const { t } = useTexT()
  const navigate = useNavigate()
  const { boot } = useSession()
  const q = useTexQuery<SiteRow[]>("policies", "list_records", { doctype: "TEX Booking Site" }, [])
  const hotelName = (p: string) => boot.properties.find((x) => x.name === p)?.property_name ?? p

  return (
    <>
      <PageHeader
        title={t("core.nav.booking_engine")}
        subtitle={t("be.list.subtitle")}
        actions={
          <>
            <Button variant="secondary" icon={<Languages className="size-4" aria-hidden />} onClick={() => navigate("/tex/booking-engine/content")}>
              {t("be.content.title")}
            </Button>
            <Button icon={<Plus className="size-4" aria-hidden />} onClick={() => navigate("/tex/booking-engine/new")}>
              {t("be.new")}
            </Button>
          </>
        }
      />
      <Card>
        <CardHeader title={t("be.list.title")} description={t("be.list.hint")} />
        {q.error ? (
          <ErrorState error={q.error} onRetry={q.reload} />
        ) : (
          <DataTable<SiteRow>
            caption={t("be.list.title")}
            rows={q.data}
            loading={q.loading}
            rowKey={(r) => r.name}
            onRowClick={(r) => navigate(`/tex/booking-engine/${encodeURIComponent(r.name)}`)}
            initialSort={{ key: "site_name", dir: "asc" }}
            empty={
              <EmptyState
                icon={<Globe className="size-5" />}
                title={t("be.list.empty")}
                description={t("be.list.empty_hint")}
                action={
                  <Button variant="secondary" icon={<Plus className="size-4" aria-hidden />} onClick={() => navigate("/tex/booking-engine/new")}>
                    {t("be.new")}
                  </Button>
                }
              />
            }
            columns={[
              {
                key: "site_name",
                header: t("be.field.site_name"),
                sortValue: (r) => r.site_name,
                cell: (r) => (
                  <span>
                    <span className="font-medium text-zinc-900">{r.site_name}</span>
                    <span className="block font-mono text-xs text-zinc-500">/book/{r.site_slug}</span>
                  </span>
                ),
              },
              {
                key: "scope",
                header: t("be.list.serves"),
                sortValue: (r) => (r.property ? hotelName(r.property) : ""),
                cell: (r) => (r.property ? hotelName(r.property) : <Badge tone="info">{t("be.scope.group")}</Badge>),
              },
              {
                key: "enabled",
                header: t("be.list.status"),
                cell: (r) => (r.enabled ? <Badge tone="success">{t("be.status.live")}</Badge> : <Badge tone="neutral">{t("be.status.off")}</Badge>),
              },
              { key: "modified", header: t("be.list.modified"), hideBelow: "md", sortValue: (r) => r.modified, cell: (r) => dateTime(r.modified) },
              {
                key: "open",
                header: <span className="sr-only">{t("be.open_site")}</span>,
                align: "right",
                hideBelow: "sm",
                cell: (r) =>
                  r.enabled ? (
                    <a
                      href={`/book/${encodeURIComponent(r.site_slug)}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => e.stopPropagation()}
                      className="inline-flex items-center gap-1 text-sm font-medium text-tex-700 hover:underline"
                    >
                      {t("be.open_site")}
                      <ExternalLink className="size-3.5" aria-hidden />
                      <span className="sr-only">
                        {r.site_name} ({t("be.new_tab")})
                      </span>
                    </a>
                  ) : null,
              },
            ]}
          />
        )}
      </Card>
    </>
  )
}
