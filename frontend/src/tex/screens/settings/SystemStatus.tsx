import { CircleCheck, CircleX, RefreshCw, TriangleAlert } from "lucide-react"
import { useTexQuery } from "../../lib/api"
import { useSession } from "../../lib/session"
import { dateTime } from "../../lib/format"
import { useTexT } from "../../i18n"
import { Badge, Button, Card, CardBody, CardHeader, ErrorState, Notice, Skeleton, type Tone } from "../../ui"
import { SettingsFrame } from "./SettingsFrame"
import { CodeBlock } from "./components/common"

type State = "ok" | "warn" | "fail"

interface Issue {
  reason: string
  status: State
  params: Record<string, string | number | null>
}

interface Check {
  key: string
  /** English title from the server (fallback when the UI has no translation) */
  title: string
  scope: "platform" | "site" | "hotel"
  status: State
  /** English text for e-mails and logs; the UI shows the translated issues */
  detail: string
  count: number
  since: string | null
  issues: Issue[]
  /** hotel checks: the hotels (of the viewer) with a problem */
  properties?: string[]
}

interface StatusData {
  overall: State
  checked_at: string
  platform: boolean
  hotels: string[] | null
  checks: Check[]
}

const TONE: Record<State, Tone> = { ok: "success", warn: "warning", fail: "danger" }
const ICON = { ok: CircleCheck, warn: TriangleAlert, fail: CircleX }
const ICON_CLASS: Record<State, string> = { ok: "text-emerald-600", warn: "text-amber-600", fail: "text-rose-600" }
const RANK: Record<State, number> = { fail: 0, warn: 1, ok: 2 }
const PING_PATH = "/api/method/kamra.tex.api.system.ping"

/**
 * /tex/settings/status — TEX system status (kamra.tex.api.system.status, `system.monitor`).
 * Hotel users see their hotels' checks; platform administrators also see the platform
 * (scheduler, workers, encryption key, e-mail queue) and the uptime-monitor address. The
 * server decides what each user may see; this screen only lays it out.
 */
export default function SystemStatus() {
  const { t } = useTexT()
  const { boot } = useSession()
  const q = useTexQuery<StatusData>("system", "status", {}, [])
  const d = q.data

  const hotelName = (name: string) => boot.properties.find((p) => p.name === name)?.property_name ?? name
  const translated = (key: string, fallback: string, params?: Record<string, string | number>) => {
    const v = t(key, params)
    return v === key ? fallback : v
  }
  const issueText = (i: Issue) => {
    const params = Object.fromEntries(Object.entries(i.params ?? {}).filter(([, v]) => v !== null && v !== undefined)) as Record<string, string | number>
    return translated(`settings.status.reason.${i.reason}`, i.reason, params)
  }

  const refresh = (
    <Button variant="secondary" icon={<RefreshCw className="size-4" aria-hidden />} onClick={q.reload} loading={q.loading && !!d}>
      {t("core.action.refresh")}
    </Button>
  )

  const groups: { id: string; label: string; checks: Check[] }[] = d
    ? [
        { id: "platform", label: t("settings.status.group.platform"), checks: d.checks.filter((c) => c.scope === "platform") },
        { id: "operations", label: t("settings.status.group.operations"), checks: d.checks.filter((c) => c.scope !== "platform") },
      ]
        .filter((g) => g.checks.length)
        .map((g) => ({ ...g, checks: [...g.checks].sort((a, b) => RANK[a.status] - RANK[b.status]) }))
    : []

  return (
    <SettingsFrame subtitle={t("settings.status.subtitle")} actions={refresh}>
      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : !d ? (
        <Card className="space-y-3 p-4" aria-busy="true">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </Card>
      ) : (
        <div className="space-y-4">
          <Card>
            <CardBody className="flex flex-wrap items-center gap-3">
              <StatusIcon state={d.overall} className="size-6" />
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-zinc-900">
                  {t("settings.status.overall")}
                  <Badge tone={TONE[d.overall]} data-testid="status-overall">
                    {t(`settings.status.state.${d.overall}`)}
                  </Badge>
                </p>
                <p className="mt-0.5 text-xs text-zinc-500">
                  {t("settings.status.checked_at", { when: dateTime(d.checked_at) })} ·{" "}
                  {d.platform ? t("settings.status.scope_platform") : t("settings.status.scope_hotels", { hotels: (d.hotels ?? []).map(hotelName).join(", ") })}
                </p>
              </div>
            </CardBody>
          </Card>

          {groups.map((g) => (
            <Card key={g.id}>
              <CardHeader title={g.label} />
              <ul className="divide-y divide-zinc-100" aria-label={g.label}>
                {g.checks.map((c) => (
                  <li key={c.key} className="flex gap-3 px-4 py-3" data-testid={`status-check-${c.key}`} data-status={c.status}>
                    <StatusIcon state={c.status} className="mt-0.5 size-4 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-zinc-900">{translated(`settings.status.check.${c.key}`, c.title)}</span>
                        <Badge tone={TONE[c.status]}>{t(`settings.status.state.${c.status}`)}</Badge>
                      </div>
                      {c.issues.length ? (
                        <ul className="mt-1 space-y-0.5 text-sm text-zinc-700">
                          {c.issues.map((i, n) => (
                            <li key={n} className={i.status === "fail" ? "text-rose-800" : undefined}>
                              {issueText(i)}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="mt-1 text-sm text-zinc-500">{t("settings.status.no_problems")}</p>
                      )}
                      {(c.since || (c.properties && c.properties.length > 0)) && (
                        <p className="mt-1 text-xs text-zinc-500">
                          {c.properties && c.properties.length > 0 && t("settings.status.hotels", { hotels: c.properties.map(hotelName).join(", ") })}
                          {c.properties && c.properties.length > 0 && c.since ? " · " : ""}
                          {c.since && t("settings.status.since", { when: dateTime(c.since) })}
                        </p>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          ))}

          <Notice tone="info">{t("settings.status.alerts_hint")}</Notice>

          {d.platform && (
            <Card>
              <CardHeader title={t("settings.status.ping_title")} description={t("settings.status.ping_hint")} />
              <CardBody>
                <CodeBlock value={`${window.location.origin}${PING_PATH}`} label={t("settings.status.ping_title")} />
              </CardBody>
            </Card>
          )}
        </div>
      )}
    </SettingsFrame>
  )
}

function StatusIcon({ state, className }: { state: State; className?: string }) {
  const Icon = ICON[state]
  return <Icon className={`${ICON_CLASS[state]} ${className ?? ""}`} aria-hidden />
}
