import { useCallback, useEffect, useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { FilePlus2, Lock, Rocket, RotateCcw, Save, ShieldCheck } from "lucide-react"
import { tex, TexApiError, useTexQuery, useTexMutation } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { overSaved } from "../../../lib/edits"
import { dateTime } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Button, Card, CardBody, ErrorState, Notice, PageHeader, Skeleton, TabPanel, Tabs, useToast } from "../../../ui"
import { IssueCount, IssueList, StatusBadge } from "../components/common"
import { RatesNav } from "../components/RatesNav"
import { fingerprint, payloadOf, stateFromDoc, type EditorState, type SellingForm } from "../lib/tables"
import type { ContractBundle, Row, ValidationResult, VersionDoc, VersionSetting, VersionTable } from "../lib/types"
import { countIssues, useLookups, versionLabel } from "../lib/util"
import { NewDraftDialog, PublishDialog } from "./VersionActions"
import { OffersTab } from "./tabs/OffersTab"
import { PreviewTab } from "./tabs/PreviewTab"
import { RatesTab } from "./tabs/RatesTab"
import { SettingsTab } from "./tabs/SettingsTab"
import type { TabProps } from "./tabs/shared"
import { AgeBandsTab, BoardsTab, OccupancyTab, PeriodsTab, RatePlansTab, RoomsTab } from "./tabs/TableTabs"

const TABS = ["rooms", "periods", "rates", "ages", "occupancy", "boards", "plans", "offers", "settings", "preview"] as const
type TabId = (typeof TABS)[number]

/** Contract version editor. Drafts are editable; published versions are frozen
 * (ADR-004) and shown read-only with a path to a new draft. */
export default function VersionEditor() {
  const { name = "", version = "" } = useParams()
  const { t } = useTexT()
  const toast = useToast()
  const navigate = useNavigate()
  const { can } = useSession()
  const q = useTexQuery<VersionDoc>("contracts", "get_version", { name: version }, [version])
  const contract = useTexQuery<ContractBundle>("contracts", "get_contract", { name }, [name])
  const lookups = useLookups(q.data?.contract_doc.property)
  const save = useTexMutation<{ name: string; data: Record<string, unknown> }, VersionDoc>("contracts", "save_version")
  const [doc, setDoc] = useState<VersionDoc>()
  const [state, setState] = useState<EditorState>()
  const [base, setBase] = useState("")
  const [tab, setTab] = useState<TabId>(() => (TABS.includes(window.location.hash.slice(1) as TabId) ? (window.location.hash.slice(1) as TabId) : "rooms"))
  const [check, setCheck] = useState<ValidationResult>()
  const [checking, setChecking] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [drafting, setDrafting] = useState(false)

  useEffect(() => {
    const onHash = () => {
      const h = window.location.hash.slice(1) as TabId
      if (TABS.includes(h)) setTab(h)
    }
    window.addEventListener("hashchange", onHash)
    return () => window.removeEventListener("hashchange", onHash)
  }, [])

  const load = useCallback((d: VersionDoc) => {
    const s = stateFromDoc(d)
    setDoc(d)
    setState(s)
    setBase(fingerprint(s))
  }, [])
  useEffect(() => {
    if (q.data) load(q.data)
  }, [q.data, load])
  /** A save came back: the saved version becomes the base, and what Discard returns to. What the
   * user changed while the save was in flight (a setting, a table, the selling terms) stays on top
   * of it: replacing the editor with the saved copy would drop those edits, and a later save would
   * then send them away too. */
  const settle = useCallback((d: VersionDoc, sent: EditorState) => {
    const saved = stateFromDoc(d)
    setDoc(d)
    setBase(fingerprint(saved))
    setState((cur) =>
      cur
        ? {
            ...saved,
            settings: overSaved(saved.settings, sent.settings, cur.settings),
            tables: overSaved(saved.tables, sent.tables, cur.tables),
            ...(JSON.stringify(cur.selling) !== JSON.stringify(sent.selling) ? { selling: cur.selling } : {}),
          }
        : saved,
    )
  }, [])

  const editable = Boolean(doc?.editable)
  const dirty = Boolean(state && editable && fingerprint(state) !== base)

  const validate = useCallback(async () => {
    if (!doc || doc.status !== "Draft" || !can("contract.edit", doc.contract_doc.property)) return
    setChecking(true)
    try {
      setCheck(await tex<ValidationResult>("contracts", "validate_version", { name: doc.name }))
    } catch (e) {
      toast.error((e as TexApiError).message)
    } finally {
      setChecking(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc?.name, doc?.status])
  useEffect(() => {
    void validate()
  }, [validate])

  const onSave = useCallback(async () => {
    // one save at a time (Ctrl+S while one is in flight waits for the next press)
    if (!doc || !state || !dirty || save.pending) return
    const sent = state
    try {
      const d = await save.run({ name: doc.name, data: payloadOf(sent) })
      settle(d, sent)
      toast.success(t("rates.version.saved"))
      setChecking(true)
      tex<ValidationResult>("contracts", "validate_version", { name: d.name })
        .then(setCheck)
        .catch(() => undefined)
        .finally(() => setChecking(false))
    } catch (e) {
      toast.error((e as Error).message)
    }
  }, [doc, state, dirty, save, settle, toast, t])

  // Ctrl/Cmd+S saves; warn before leaving with unsaved edits
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault()
        void onSave()
      }
    }
    const onUnload = (e: BeforeUnloadEvent) => {
      if (dirty) e.preventDefault()
    }
    window.addEventListener("keydown", onKey)
    window.addEventListener("beforeunload", onUnload)
    return () => {
      window.removeEventListener("keydown", onKey)
      window.removeEventListener("beforeunload", onUnload)
    }
  }, [onSave, dirty])

  const setTable = useCallback((k: VersionTable, rows: Row[]) => setState((s) => (s ? { ...s, tables: { ...s.tables, [k]: rows } } : s)), [])
  const setSetting = useCallback((k: VersionSetting, v: string | number) => setState((s) => (s ? { ...s, settings: { ...s.settings, [k]: v } } : s)), [])
  const setSelling = useCallback((patch: Partial<SellingForm>) => setState((s) => (s?.selling ? { ...s, selling: { ...s.selling, ...patch } } : s)), [])
  const changeTab = (id: string) => {
    setTab(id as TabId)
    window.history.replaceState(null, "", `#${id}`)
  }

  const issues = check?.issues
  const tabDefs = useMemo(
    () =>
      TABS.map((id) => {
        const c = countIssues(issues, id)
        const n = id === "rooms" || id === "periods" || id === "rates" || id === "ages" || id === "occupancy" || id === "boards" || id === "plans" || id === "offers" ? rowCount(state, id) : null
        return {
          id,
          label: (
            <>
              {t(`rates.tab.${id}`)}
              {n !== null && n > 0 && <span className="text-xs font-normal text-zinc-500 tabular-nums">{n}</span>}
            </>
          ),
          badge: <IssueCount errors={c.errors} warnings={c.warnings} />,
        }
      }),
    [issues, state, t],
  )

  const draft = contract.data?.versions.find((v) => v.status === "Draft")
  const cd = doc?.contract_doc
  const vlabel = doc ? versionLabel(doc.name, doc.version_no) : versionLabel(version)
  const canPublish = Boolean(contract.data?.can_publish)

  if (q.error)
    return (
      <>
        <RatesNav />
        <PageHeader title={vlabel} crumbs={[{ label: t("core.nav.rates"), to: "/tex/rates" }, { label: name, to: `/tex/rates/contracts/${encodeURIComponent(name)}` }, { label: vlabel }]} />
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      </>
    )

  const props: TabProps | undefined =
    doc && state ? { doc, state, readOnly: !editable, issues, setTable, setSetting, setSelling, lookups: lookups.data, dirty, onSave } : undefined

  return (
    <>
      <RatesNav />
      <PageHeader
        crumbs={[
          { label: t("core.nav.rates"), to: "/tex/rates" },
          { label: cd?.contract_code ?? name, to: `/tex/rates/contracts/${encodeURIComponent(name)}` },
          { label: vlabel },
        ]}
        title={cd ? `${cd.contract_code} · ${vlabel}` : <Skeleton className="h-7 w-48" />}
        subtitle={cd?.contract_name}
        meta={
          doc && (
            <>
              <StatusBadge status={doc.status} group="version_status" />
              {!editable && (
                <Badge tone="neutral">
                  <Lock className="size-3" aria-hidden />
                  {t("rates.version.read_only")}
                </Badge>
              )}
              {dirty && <Badge tone="warning">{t("rates.version.unsaved")}</Badge>}
              {doc.effective_from && <span className="text-xs text-zinc-500">{t("rates.version.effective_since", { at: dateTime(doc.effective_from) })}</span>}
            </>
          )
        }
        actions={
          doc &&
          (editable ? (
            <>
              <Button variant="ghost" icon={<RotateCcw className="size-4" aria-hidden />} disabled={!dirty || save.pending} onClick={() => doc && load(doc)}>
                {t("rates.version.discard")}
              </Button>
              <Button variant="secondary" icon={<ShieldCheck className="size-4" aria-hidden />} loading={checking} disabled={dirty} onClick={() => void validate()} title={dirty ? t("rates.version.save_first") : undefined}>
                {t("rates.version.validate")}
              </Button>
              {canPublish && (
                <Button variant="secondary" icon={<Rocket className="size-4" aria-hidden />} disabled={dirty} onClick={() => setPublishing(true)} title={dirty ? t("rates.version.save_first") : undefined}>
                  {t("rates.version.publish")}
                </Button>
              )}
              <Button icon={<Save className="size-4" aria-hidden />} loading={save.pending} disabled={!dirty} onClick={() => void onSave()} shortcut="Ctrl S">
                {t("core.action.save")}
              </Button>
            </>
          ) : (
            doc.status !== "Draft" &&
            can("contract.edit", cd?.property) &&
            (draft ? (
              <Button icon={<FilePlus2 className="size-4" aria-hidden />} onClick={() => navigate(`/tex/rates/contracts/${encodeURIComponent(name)}/versions/${encodeURIComponent(draft.name)}`)}>
                {t("rates.version.open_draft", { v: versionLabel(draft.name, draft.version_no) })}
              </Button>
            ) : (
              <Button icon={<FilePlus2 className="size-4" aria-hidden />} onClick={() => setDrafting(true)}>
                {t("rates.version.new_draft_from_this")}
              </Button>
            ))
          ))
        }
      />

      {doc && doc.status !== "Draft" && (
        <div className="mb-4">
          <Notice tone="info" title={t("rates.version.immutable_title")}>
            {t("rates.version.immutable_body")}
          </Notice>
        </div>
      )}
      {doc && doc.status === "Draft" && !editable && (
        <div className="mb-4">
          <Notice tone="info">{t("rates.version.no_edit_permission")}</Notice>
        </div>
      )}
      {editable && issues && issues.length > 0 && (
        <details className="mb-4 rounded-lg border border-zinc-200 bg-white px-3 py-2" open={issues.some((i) => i.level === "ERROR")}>
          <summary className="cursor-pointer text-sm font-medium text-zinc-800">
            {t("rates.version.issues_summary", { errors: issues.filter((i) => i.level === "ERROR").length, warnings: issues.filter((i) => i.level !== "ERROR").length })}
          </summary>
          <div className="mt-2">
            <IssueList issues={issues} compact />
          </div>
        </details>
      )}
      {editable && check && check.issues.length === 0 && !dirty && (
        <p className="mb-4 flex items-center gap-1.5 text-sm text-emerald-800" role="status">
          <ShieldCheck className="size-4 text-emerald-600" aria-hidden />
          {t("rates.version.check_ok")}
        </p>
      )}
      {save.error && (
        <div className="mb-4">
          <Notice tone="danger" title={t("rates.version.save_failed")}>
            <span className="whitespace-pre-line">{save.error.message}</span>
          </Notice>
        </div>
      )}

      <Card>
        <Tabs tabs={tabDefs} value={tab} onChange={changeTab} label={t("rates.version.sections")} className="px-2" />
        <CardBody className="min-h-64">
          {!props ? (
            <div className="space-y-3">
              <Skeleton className="h-6 w-64" />
              <Skeleton className="h-40 w-full" />
            </div>
          ) : (
            <TabPanel id={tab}>
              {tab === "settings" && <SettingsTab {...props} />}
              {tab === "rooms" && <RoomsTab {...props} />}
              {tab === "periods" && <PeriodsTab {...props} />}
              {tab === "rates" && <RatesTab {...props} />}
              {tab === "ages" && <AgeBandsTab {...props} />}
              {tab === "occupancy" && <OccupancyTab {...props} />}
              {tab === "boards" && <BoardsTab {...props} />}
              {tab === "plans" && <RatePlansTab {...props} />}
              {tab === "offers" && <OffersTab {...props} />}
              {tab === "preview" && <PreviewTab {...props} />}
            </TabPanel>
          )}
        </CardBody>
      </Card>

      {doc && cd && publishing && (
        <PublishDialog
          open
          onClose={() => setPublishing(false)}
          version={doc}
          contractCode={cd.contract_code}
          onDone={() => {
            q.reload()
            contract.reload()
          }}
        />
      )}
      {doc && contract.data && (
        <NewDraftDialog
          open={drafting}
          onClose={() => setDrafting(false)}
          contract={name}
          versions={contract.data.versions}
          basedOn={doc.name}
          onDone={(v) => navigate(`/tex/rates/contracts/${encodeURIComponent(name)}/versions/${encodeURIComponent(v)}`)}
        />
      )}
    </>
  )
}

function rowCount(state: EditorState | undefined, tab: string): number | null {
  if (!state) return null
  const map: Record<string, VersionTable> = {
    rooms: "rooms",
    periods: "periods",
    rates: "period_rates",
    ages: "age_bands",
    occupancy: "occupancy_rules",
    boards: "boards",
    plans: "rate_plans",
    offers: "offers",
  }
  const k = map[tab]
  return k ? state.tables[k].length : null
}

