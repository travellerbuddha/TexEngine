import { useEffect, useMemo, useState } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"
import { ExternalLink } from "lucide-react"
import { useTexMutation, useTexQuery } from "../../lib/api"
import { useSession } from "../../lib/session"
import { dateTime } from "../../lib/format"
import { useTexT } from "../../i18n"
import { Badge, Button, Card, ErrorState, Notice, PageHeader, Skeleton, TabPanel, Tabs, useToast, type TabDef } from "../../ui"
import { useUnsavedWarning } from "../settings/components/common"
import { FIELD_TAB, lines, newSite, normaliseDomain, normaliseOrigin, normaliseSlug, validateSite, type Site, type TabId } from "./site"
import { GeneralTab } from "./tabs/GeneralTab"
import { BrandingTab } from "./tabs/BrandingTab"
import { TextsTab } from "./tabs/TextsTab"
import { AnalyticsTab, ContactTab } from "./tabs/ContactAnalyticsTabs"
import { EmbedTab } from "./tabs/EmbedTab"
import { DomainsTab } from "./tabs/DomainsTab"
import type { TabProps } from "./tabs/common"

const DOCTYPE = "TEX Booking Site"
const TABS: TabId[] = ["general", "branding", "texts", "contact", "analytics", "embed", "domains"]
/** Required-field errors wait for the first save attempt; format errors show at once. */
const REQUIRED = new Set(["site_name", "site_slug", "scope"])

/** Server doc → editable draft (drops bookkeeping the save endpoint ignores anyway). */
function toDraft(d: Site & Record<string, unknown>): Site {
  const base = newSite()
  const out = { ...base } as Record<string, unknown>
  for (const k of Object.keys(base)) if (k in d) out[k] = d[k] ?? (base as unknown as Record<string, unknown>)[k]
  out.name = d.name
  out.modified = d.modified
  out.domains = ((d.domains as Site["domains"]) ?? []).map((x) => ({
    domain: x.domain,
    is_primary: x.is_primary ? 1 : 0,
    verified: x.verified ? 1 : 0,
    verification_token: x.verification_token ?? null,
  }))
  for (const k of ["property", "hotel_group", "default_currency", "currencies", "default_market", "sales_channel", "logo", "hero_image"]) out[k] = d[k] ?? null
  return out as unknown as Site
}

export default function SiteEditor({ isNew = false }: { isNew?: boolean }) {
  const { t } = useTexT()
  const toast = useToast()
  const navigate = useNavigate()
  const { name } = useParams()
  const { property } = useSession()
  const [params, setParams] = useSearchParams()
  const tab = (TABS as string[]).includes(params.get("tab") ?? "") ? (params.get("tab") as TabId) : "general"
  const setTab = (id: string) => {
    const next = new URLSearchParams(params)
    if (id === "general") next.delete("tab")
    else next.set("tab", id)
    setParams(next, { replace: true })
  }

  const q = useTexQuery<Site & Record<string, unknown>>("policies", "get_record", { doctype: DOCTYPE, name }, [name], !isNew && !!name)
  const save = useTexMutation<{ doctype: string; data: Record<string, unknown> }, Site & Record<string, unknown>>("policies", "save_record")
  const [draft, setDraft] = useState<Site | null>(() => (isNew ? newSite(property?.name) : null))
  const [base, setBase] = useState<Site | null>(() => (isNew ? newSite(property?.name) : null))
  const [attempted, setAttempted] = useState(false)

  useEffect(() => {
    if (q.data) {
      const d = toDraft(q.data)
      setDraft(d)
      setBase(d)
    }
  }, [q.data])

  const dirty = !!draft && !!base && JSON.stringify(draft) !== JSON.stringify(base)
  useUnsavedWarning(dirty)
  const errors = useMemo(() => (draft ? validateSite(draft) : {}), [draft])
  const errorTabs = useMemo(() => {
    const m: Partial<Record<TabId, number>> = {}
    for (const f of Object.keys(errors)) {
      if (!attempted && REQUIRED.has(f)) continue
      const tb = FIELD_TAB[f] ?? "general"
      m[tb] = (m[tb] ?? 0) + 1
    }
    return m
  }, [errors, attempted])
  const err = (f: string) => {
    const k = errors[f]
    if (!k || (!attempted && REQUIRED.has(f))) return undefined
    return t(k)
  }

  const set = (patch: Partial<Site>) => setDraft((d) => (d ? { ...d, ...patch } : d))

  const submit = async () => {
    if (!draft) return
    setAttempted(true)
    if (Object.keys(errors).length) {
      const first = FIELD_TAB[Object.keys(errors)[0]] ?? "general"
      setTab(first)
      return
    }
    const data: Record<string, unknown> = {
      ...draft,
      site_slug: normaliseSlug(draft.site_slug),
      allowed_embed_origins: lines(draft.allowed_embed_origins).map(normaliseOrigin).join("\n"),
      domains: draft.domains.map((d) => ({ ...d, domain: normaliseDomain(d.domain) })),
    }
    delete data.modified
    if (isNew) delete data.name
    try {
      const saved = await save.run({ doctype: DOCTYPE, data })
      const d = toDraft(saved)
      setDraft(d)
      setBase(d)
      setAttempted(false)
      toast.success(isNew ? t("be.created") : t("core.saved"))
      if (isNew && saved.name) navigate(`/tex/booking-engine/${encodeURIComponent(String(saved.name))}${tab !== "general" ? `?tab=${tab}` : ""}`, { replace: true })
    } catch {
      window.scrollTo({ top: 0, behavior: "smooth" })
    }
  }

  const tabs: TabDef[] = TABS.map((id) => ({
    id,
    label: t(`be.tab.${id}`),
    badge: errorTabs[id] ? (
      <Badge tone="danger" className="px-1 py-0 text-[10px]">
        {errorTabs[id]}
        <span className="sr-only">{t("be.tab_errors")}</span>
      </Badge>
    ) : undefined,
  }))

  const crumbs = [{ label: t("core.nav.booking_engine"), to: "/tex/booking-engine" }, { label: isNew ? t("be.new") : (draft?.site_name ?? name ?? "") }]

  if (!isNew && q.error)
    return (
      <>
        <PageHeader title={t("be.site")} crumbs={crumbs} />
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
        {q.error.isPermission && <p className="mt-3 text-sm text-zinc-600">{t("be.group_permission")}</p>}
      </>
    )

  if (!draft)
    return (
      <>
        <PageHeader title={<Skeleton className="h-7 w-64" />} crumbs={crumbs} />
        <Card className="space-y-3 p-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </Card>
      </>
    )

  const props: TabProps = { site: draft, set, err, errors, isNew, dirty, reload: q.reload }

  return (
    <>
      <PageHeader
        title={isNew ? t("be.new") : draft.site_name || t("be.site")}
        crumbs={crumbs}
        meta={
          !isNew && (
            <>
              {base?.enabled ? <Badge tone="success">{t("be.status.live")}</Badge> : <Badge tone="neutral">{t("be.status.off")}</Badge>}
              <span className="font-mono text-xs text-zinc-500">/book/{base?.site_slug}</span>
              {base?.modified && <span className="text-xs text-zinc-500">{t("be.last_saved", { when: dateTime(base.modified) })}</span>}
            </>
          )
        }
        actions={
          !isNew &&
          base?.enabled ? (
            <a
              href={`/book/${encodeURIComponent(base.site_slug)}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-zinc-300 bg-white px-3.5 text-sm font-medium text-zinc-800 shadow-sm hover:bg-zinc-50"
            >
              {t("be.open_site")}
              <ExternalLink className="size-4" aria-hidden />
              <span className="sr-only">({t("be.new_tab")})</span>
            </a>
          ) : undefined
        }
      />

      <div className="space-y-4 pb-20">
        {save.error && (
          <Notice tone="danger" title={save.error.isPermission ? t("be.save_refused") : t("be.save_failed")}>
            <p className="whitespace-pre-line">{save.error.message}</p>
          </Notice>
        )}
        {attempted && Object.keys(errorTabs).length > 0 && (
          <Notice tone="danger" title={t("be.fix_errors")}>
            {t("be.fix_errors_in", { tabs: (Object.keys(errorTabs) as TabId[]).map((x) => t(`be.tab.${x}`)).join(", ") })}
          </Notice>
        )}
        <Tabs tabs={tabs} value={tab} onChange={setTab} label={t("be.sections")} />
        <TabPanel id={tab}>
          {tab === "general" && <GeneralTab {...props} />}
          {tab === "branding" && <BrandingTab {...props} />}
          {tab === "texts" && <TextsTab {...props} />}
          {tab === "contact" && <ContactTab {...props} />}
          {tab === "analytics" && <AnalyticsTab {...props} />}
          {tab === "embed" && <EmbedTab {...props} />}
          {tab === "domains" && <DomainsTab {...props} />}
        </TabPanel>
      </div>

      <div className="sticky bottom-0 z-10 -mx-1 flex flex-wrap items-center justify-end gap-2 rounded-lg border border-zinc-200 bg-white/95 px-3 py-2 shadow-tex-card backdrop-blur">
        <span className="mr-auto text-xs font-medium" aria-live="polite">
          {dirty ? <span className="text-amber-800">{t("be.unsaved")}</span> : !isNew ? <span className="hidden text-zinc-500 sm:inline">{t("be.all_saved")}</span> : null}
        </span>
        {isNew ? (
          <Button variant="secondary" onClick={() => navigate("/tex/booking-engine")}>
            {t("core.action.cancel")}
          </Button>
        ) : (
          <Button variant="secondary" disabled={!dirty || save.pending} onClick={() => base && setDraft(base)}>
            {t("be.discard")}
          </Button>
        )}
        <Button loading={save.pending} disabled={!dirty && !isNew} onClick={submit}>
          {isNew ? t("be.create") : t("core.action.save")}
        </Button>
      </div>
    </>
  )
}
