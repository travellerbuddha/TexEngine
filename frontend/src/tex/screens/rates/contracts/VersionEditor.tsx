import { useCallback, useEffect, useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { FilePlus2 } from "lucide-react"
import { useTexQuery, useTexMutation } from "../../../lib/api"
import { useSession } from "../../../lib/session"
import { dateTime } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Button, Card, CardBody, Drawer, ErrorState, Notice, PageHeader, shortcutLetter, Skeleton, TabPanel, Tabs, useToast } from "../../../ui"
import { IssueCount } from "../components/common"
import { RatesNav } from "../components/RatesNav"
import { fingerprint, payloadOf, settleState, stateFromDoc, type EditorState, type SellingForm } from "../lib/tables"
import type { ContractBundle, Row, VersionDoc, VersionSetting, VersionTable } from "../lib/types"
import { countIssues, editorHash, parseEditorHash, useLookups, versionLabel } from "../lib/util"
import { ContextHeader } from "../workspace/ContextHeader"
import { PricingSection } from "../workspace/PricingSection"
import { SECTIONS, DEFAULT_RULE_TABLE, type EditorPlace, type PricingRegion, type RuleTableId, type SectionId } from "../workspace/sections.ts"
import { useDraftPreview } from "../workspace/useDraftPreview"
import { useWorkspaceHistory } from "../workspace/useWorkspaceHistory"
import { CommercialRulesSection } from "./sections/CommercialRulesSection"
import { NewDraftDialog, PublishDialog } from "./VersionActions"
import { OffersTab } from "./tabs/OffersTab"
import { PreviewTab, PriceTestPanel } from "./tabs/PreviewTab"
import type { TabProps } from "./tabs/shared"

const initialPlace = (): EditorPlace => parseEditorHash(window.location.hash) ?? { section: "pricing" }

/** The name of a table in the history's labels ("Rule table: Room prices"). */
const TABLE_LABEL: Record<VersionTable, string> = {
  rooms: "rates.tab.rooms",
  periods: "rates.tab.periods",
  period_rates: "rates.tab.rates",
  age_bands: "rates.tab.ages",
  occupancy_rules: "rates.tab.occupancy_rules",
  boards: "rates.tab.boards",
  rate_plans: "rates.tab.plans",
  offers: "rates.tab.offers",
}

/** Contract version editor, in four sections (PRICING_WORKSPACE_UX.md §2): Pricing, Commercial rules
 * (with the Advanced rule tables), Offers & promotions, Preview & audit, under a sticky commercial
 * context header. Drafts are editable; published versions are frozen (ADR-004) and shown read-only
 * with a path to a new draft. The server prices and checks what is on screen as it is edited
 * (useDraftPreview); nothing is saved until Save. */
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
  const [section, setSection] = useState<SectionId>(() => initialPlace().section)
  const [ruleTable, setRuleTable] = useState<RuleTableId>(() => initialPlace().table ?? DEFAULT_RULE_TABLE)
  const [region, setRegion] = useState<PricingRegion | undefined>(() => initialPlace().region)
  const [publishing, setPublishing] = useState(false)
  const [drafting, setDrafting] = useState(false)
  const [testing, setTesting] = useState(false)

  // old and new hashes (§2): #rates, #occupancy, #plans … land on the section that holds them now
  useEffect(() => {
    const onHash = () => {
      const p = parseEditorHash(window.location.hash)
      if (!p) return
      setSection(p.section)
      if (p.table) setRuleTable(p.table)
      setRegion(p.region)
    }
    window.addEventListener("hashchange", onHash)
    return () => window.removeEventListener("hashchange", onHash)
  }, [])

  const setTable = useCallback((k: VersionTable, rows: Row[]) => setState((s) => (s ? { ...s, tables: { ...s.tables, [k]: rows } } : s)), [])
  // the workspace undo history (§3.10): cleared whenever a version is loaded, and by Discard
  const history = useWorkspaceHistory(state, setTable)
  const clearHistory = history.clear
  // the sections' table writes (the Advanced rule tables, Offers) go through the history too, so an
  // undo in the matrix never puts back a table older than an edit made there (S10)
  const record = history.record
  const recordTable = useCallback((k: VersionTable, rows: Row[]) => void record(k, rows, t("rates.ws.h.table", { table: t(TABLE_LABEL[k]) })), [record, t])
  const [epoch, setEpoch] = useState(0)
  const load = useCallback(
    (d: VersionDoc) => {
      const s = stateFromDoc(d)
      setDoc(d)
      setState(s)
      setBase(fingerprint(s))
      clearHistory()
      setEpoch((n) => n + 1)
    },
    [clearHistory],
  )
  useEffect(() => {
    if (q.data) load(q.data)
  }, [q.data, load])
  /** A save came back: the saved version becomes the base, and what Discard returns to. What the
   * user changed while the save was in flight (a setting, a table, the selling terms) stays on top
   * of it: replacing the editor with the saved copy would drop those edits, and a later save would
   * then send them away too. Rows keep their client keys (keepKeys), so selection, focus and open
   * panels survive the save. */
  const settle = useCallback((d: VersionDoc, sent: EditorState) => {
    const saved = stateFromDoc(d)
    setDoc(d)
    setBase(fingerprint(saved))
    setState((cur) => settleState(saved, sent, cur))
  }, [])

  const editable = Boolean(doc?.editable)
  const fp = useMemo(() => (state ? fingerprint(state) : ""), [state])
  const dirty = Boolean(state && editable && fp !== base)
  // the server's resolved prices and issues for what is on screen (overlay, saved or catalogue)
  const preview = useDraftPreview(doc, state, { fingerprint: fp, base })

  const onSave = useCallback(async () => {
    // one save at a time (Ctrl+S while one is in flight waits for the next press)
    if (!doc || !state || !dirty || save.pending) return
    const sent = state
    try {
      const d = await save.run({ name: doc.name, data: payloadOf(sent) })
      settle(d, sent)
      toast.success(t("rates.version.saved"))
    } catch (e) {
      toast.error((e as Error).message)
    }
  }, [doc, state, dirty, save, settle, toast, t])

  // Ctrl/Cmd+S saves; warn before leaving with unsaved edits
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // by letter on every layout (Russian: Ctrl + the key marked S types "ы"; ui/keys.ts)
      if ((e.ctrlKey || e.metaKey) && !e.altKey && shortcutLetter(e) === "s") {
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

  const setSetting = useCallback((k: VersionSetting, v: string | number) => setState((s) => (s ? { ...s, settings: { ...s.settings, [k]: v } } : s)), [])
  const setSelling = useCallback((patch: Partial<SellingForm>) => setState((s) => (s?.selling ? { ...s, selling: { ...s.selling, ...patch } } : s)), [])
  // the tabs write the canonical hash (#pricing, #rules/<table>, #offers, #preview)
  const changeSection = (id: string) => {
    const next = id as SectionId
    setSection(next)
    setRegion(undefined)
    window.history.replaceState(null, "", `#${editorHash({ section: next, table: ruleTable })}`)
  }
  const changeTable = (table: RuleTableId) => {
    setRuleTable(table)
    window.history.replaceState(null, "", `#${editorHash({ section: "rules", table })}`)
  }
  /** The basis popover saved the contract header: show the new basis and price again, without
   * touching the version being edited (its unsaved edits and the save base stay as they are). */
  const refetchPreview = preview.refetch
  const onBasisApplied = useCallback(
    (basis: "PERSON" | "ROOM") => {
      setDoc((d) => (d ? { ...d, contract_doc: { ...d.contract_doc, pricing_basis: basis } } : d))
      refetchPreview()
    },
    [refetchPreview],
  )

  const issues = preview.issues
  const offersCount = state?.tables.offers.length ?? 0
  const tabDefs = useMemo(
    () =>
      SECTIONS.map((id) => {
        const c = countIssues(issues, id)
        return {
          id,
          label: (
            <>
              {t(`rates.section.${id}`)}
              {id === "offers" && offersCount > 0 && <span className="text-xs font-normal text-zinc-500 tabular-nums">{offersCount}</span>}
            </>
          ),
          badge: <IssueCount errors={c.errors} warnings={c.warnings} />,
        }
      }),
    [issues, offersCount, t],
  )

  const draft = contract.data?.versions.find((v) => v.status === "Draft")
  const cd = doc?.contract_doc
  const vlabel = doc ? versionLabel(doc.name, doc.version_no) : versionLabel(version)
  const canPublish = Boolean(doc?.can_publish ?? contract.data?.can_publish)

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
    doc && state ? { doc, state, readOnly: !editable, issues, setTable: recordTable, setSetting, setSelling, lookups: lookups.data, dirty, onSave, preview, history, epoch } : undefined

  const draftAction =
    doc &&
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

  const sections = <Tabs tabs={tabDefs} value={section} onChange={changeSection} label={t("rates.version.sections")} />

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
        meta={doc?.effective_from && <span className="text-xs text-zinc-500">{t("rates.version.effective_since", { at: dateTime(doc.effective_from) })}</span>}
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
      {save.error && (
        <div className="mb-4">
          <Notice tone="danger" title={t("rates.version.save_failed")}>
            <span className="whitespace-pre-line">{save.error.message}</span>
          </Notice>
        </div>
      )}

      {doc && state ? (
        <ContextHeader
          doc={doc}
          state={state}
          preview={preview}
          editable={editable}
          dirty={dirty}
          saving={save.pending}
          canPublish={canPublish}
          onSave={() => void onSave()}
          onDiscard={() => load(doc)}
          onPublish={() => setPublishing(true)}
          onPriceTest={() => setTesting(true)}
          setSelling={setSelling}
          onBasisApplied={onBasisApplied}
          draftAction={draftAction}
        >
          {sections}
        </ContextHeader>
      ) : (
        <div className="mb-4">{sections}</div>
      )}

      <Card>
        <CardBody className="min-h-64">
          {!props ? (
            <div className="space-y-3">
              <Skeleton className="h-6 w-64" />
              <Skeleton className="h-40 w-full" />
            </div>
          ) : (
            <TabPanel id={section}>
              {section === "pricing" && <PricingSection {...props} region={region} />}
              {section === "rules" && <CommercialRulesSection {...props} table={ruleTable} onTable={changeTable} />}
              {section === "offers" && <OffersTab {...props} />}
              {section === "preview" && <PreviewTab {...props} />}
            </TabPanel>
          )}
        </CardBody>
      </Card>

      {props && testing && (
        <Drawer open onClose={() => setTesting(false)} title={t("rates.ws.price_test")} width="lg">
          <PriceTestPanel {...props} layout="drawer" />
        </Drawer>
      )}
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
