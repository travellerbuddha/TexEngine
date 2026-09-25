import { useId, useRef, useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { AlertOctagon, AlertTriangle, Calculator, CheckCircle2, ChevronDown, CornerDownRight, Loader2, Lock, Rocket, RotateCcw, Save, ShieldCheck } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { useSession } from "../../../lib/session"
import { useTexT } from "../../../i18n"
import { Badge, Button, Field, FormGrid, Input, Popover, Select, Tooltip } from "../../../ui"
import { DateRange, StatusBadge } from "../components/common"
import type { EditorState, SellingForm } from "../lib/tables"
import type { Issue, VersionDoc } from "../lib/types"
import { versionLabel } from "../lib/util"
import { BasisPopover, CHIP, CHIP_BUTTON } from "./BasisPopover"
import { issuesBySection } from "./issues.ts"
import type { DraftPreview } from "./useDraftPreview"

export interface ContextHeaderProps {
  doc: VersionDoc
  state: EditorState
  preview: DraftPreview
  editable: boolean
  dirty: boolean
  saving: boolean
  canPublish: boolean
  onSave: () => void
  onDiscard: () => void
  onPublish: () => void
  onPriceTest: () => void
  setSelling: (patch: Partial<SellingForm>) => void
  onBasisApplied: (basis: "PERSON" | "ROOM") => void
  /** "Open draft Vn" / "Create new draft from this version" on a frozen version */
  draftAction?: ReactNode
  /** the section tablist, kept in view with the header */
  children?: ReactNode
  /** an issue's message as shown (band codes as labels, D13) */
  issueText?: (issue: Issue) => string
  /** a click on an issue of the live check (by its index in `preview.issues`): its cell, or the
   * section, region or rule table that holds it (S15) */
  onShowIssue?: (index: number) => void
}

/**
 * The sticky commercial context of the version editor (PRICING_WORKSPACE_UX.md §3.2): what the
 * contract is (contract, market, currencies, pricing basis, base room and occupancy, sale and stay
 * windows), which version and in what state, the live check, and the actions that were in the page
 * header (same names and states: Save with Ctrl S, Discard, Check, Publish), plus the Price test
 * for who may see cost. On phones the chips fold behind "Details".
 */
export function ContextHeader(p: ContextHeaderProps) {
  const { t } = useTexT()
  const { doc, state, preview, editable, dirty } = p
  const cd = doc.contract_doc
  const [details, setDetails] = useState(false)
  const chipsId = useId()
  const baseRoom = String(state.tables.rooms.find((r) => r.is_base)?.room_type ?? "")
  const roomName = (rt: string) => doc.room_types.find((r) => r.name === rt)?.room_type_name || rt
  const selling = doc.selling
  const sellCcy = state.selling?.sell_currency || selling?.sell_currency || ""
  const sale = state.selling ? { from: state.selling.sale_from, to: state.selling.sale_to } : { from: selling?.sale_from, to: selling?.sale_to }
  const stay = state.selling ? { from: state.selling.stay_from, to: state.selling.stay_to } : { from: selling?.stay_from, to: selling?.stay_to }
  const sellingEditable = Boolean(editable && state.selling && doc.selling_editable)

  return (
    <section aria-label={t("rates.ws.context")} className="z-20 -mx-3 mb-4 bg-white/95 px-3 pt-2 backdrop-blur sm:-mx-6 sm:px-6 md:sticky md:top-14">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-zinc-900">{versionLabel(doc.name, doc.version_no)}</span>
          <StatusBadge status={doc.status} group="version_status" />
          {!editable && (
            <Badge tone="neutral">
              <Lock className="size-3" aria-hidden />
              {t("rates.version.read_only")}
            </Badge>
          )}
          {dirty && <Badge tone="warning">{t("rates.version.unsaved")}</Badge>}
          <LiveCheck preview={preview} issueText={p.issueText} onShowIssue={p.onShowIssue} />
        </div>
        <div className="ml-auto flex max-w-full min-w-0 flex-wrap items-center gap-2">
          {doc.can_preview && (
            <Button variant="secondary" icon={<Calculator className="size-4" aria-hidden />} onClick={p.onPriceTest}>
              {t("rates.ws.price_test")}
            </Button>
          )}
          {editable ? (
            <>
              <Button variant="ghost" icon={<RotateCcw className="size-4" aria-hidden />} disabled={!dirty || p.saving} onClick={p.onDiscard}>
                {t("rates.version.discard")}
              </Button>
              <Button
                variant="secondary"
                icon={<ShieldCheck className="size-4" aria-hidden />}
                loading={preview.validating}
                disabled={dirty}
                onClick={preview.validateNow}
                title={dirty ? t("rates.version.save_first") : undefined}
              >
                {t("rates.version.validate")}
              </Button>
              {p.canPublish && (
                <Button variant="secondary" icon={<Rocket className="size-4" aria-hidden />} disabled={dirty} onClick={p.onPublish} title={dirty ? t("rates.version.save_first") : undefined}>
                  {t("rates.version.publish")}
                </Button>
              )}
              <Button icon={<Save className="size-4" aria-hidden />} loading={p.saving} disabled={!dirty} onClick={p.onSave} shortcut="Ctrl S">
                {t("core.action.save")}
              </Button>
            </>
          ) : (
            p.draftAction
          )}
        </div>
      </div>

      <button
        type="button"
        className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-zinc-600 md:hidden"
        aria-expanded={details}
        aria-controls={chipsId}
        onClick={() => setDetails(!details)}
      >
        <ChevronDown className={cn("size-3.5 transition-transform", details && "rotate-180")} aria-hidden />
        {t("rates.ws.details")}
      </button>
      <dl id={chipsId} className={cn(details ? "flex" : "hidden", "mt-2 flex-wrap items-center gap-x-2 gap-y-1.5 md:flex")}>
        <Chip label={t("rates.col.contract")}>
          <Link to={`/tex/rates/contracts/${encodeURIComponent(cd.name)}`} className="truncate font-medium text-tex-700 hover:underline">
            {cd.contract_code} · {cd.contract_name}
          </Link>
        </Chip>
        <Chip label={t("rates.f.market")}>{cd.market || "—"}</Chip>
        <Chip label={t("rates.f.contract_currency")}>{cd.contract_currency || "—"}</Chip>
        {selling && (
          <Chip label={t("rates.f.sell_currency")}>
            <SellingChip editable={sellingEditable} what="currency" state={state} setSelling={p.setSelling} value={sellCcy || t("rates.common.same_as_contract")} hint={doc.selling_source} />
          </Chip>
        )}
        {cd.pricing_basis && (
          <div className="min-w-0">
            <dt className="sr-only">{t("rates.f.pricing_basis")}</dt>
            <dd className="min-w-0">
              <BasisPopover doc={doc} onApplied={p.onBasisApplied} />
            </dd>
          </div>
        )}
        {preview.mode !== "catalogue" && (
          <>
            <Chip label={t("rates.f.is_base")}>{baseRoom ? roomName(baseRoom) : t("rates.common.none")}</Chip>
            <Chip label={t("rates.ws.base_occ.label")}>
              <BaseOccupancy basis={cd.pricing_basis} baseRoom={baseRoom} preview={preview} />
            </Chip>
          </>
        )}
        {selling && (
          <Chip label={t("rates.ws.validity")}>
            <SellingChip
              editable={sellingEditable}
              what="dates"
              state={state}
              setSelling={p.setSelling}
              hint={doc.selling_source}
              value={
                <>
                  <span className="text-xs text-zinc-500">{t("rates.ws.sale")}</span> <DateRange from={sale.from} to={sale.to} /> ·{" "}
                  <span className="text-xs text-zinc-500">{t("rates.ws.stay")}</span> <DateRange from={stay.from} to={stay.to} />
                </>
              }
            />
          </Chip>
        )}
      </dl>
      <div className="mt-1">{p.children}</div>
    </section>
  )
}

function Chip({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className={CHIP}>
      <dt className="shrink-0 text-xs text-zinc-500">{label}</dt>
      <dd className="min-w-0 truncate text-zinc-900">{children}</dd>
    </div>
  )
}

/** PERSON: every adult pays the base person price (×1.00 by default); ROOM: the adults the base
 * room's price covers, as the server built them (the effective included_adults, GAP-3). */
function BaseOccupancy({ basis, baseRoom, preview }: { basis?: string; baseRoom: string; preview: DraftPreview }) {
  const { t } = useTexT()
  if (basis !== "ROOM") return <>{t("rates.ws.base_occ.person")}</>
  const cap = preview.matrix?.rooms.find((r) => r.room_type === baseRoom)?.capacity
  if (!baseRoom || !cap) return <>—</>
  return <span className={cn(preview.stale && "text-zinc-500")}>{t("rates.ws.base_occ.room", { count: cap.included_adults })}</span>
}

/** The selling terms in the header: a popover editing the draft's own terms when they are its own
 * and editable (G-50); otherwise read-only (before the first publish they are the header's). */
function SellingChip({
  editable,
  what,
  state,
  setSelling,
  value,
  hint,
}: {
  editable: boolean
  what: "dates" | "currency"
  state: EditorState
  setSelling: (patch: Partial<SellingForm>) => void
  value: ReactNode
  hint?: string
}) {
  const { t } = useTexT()
  const { boot } = useSession()
  const ref = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const g = state.selling
  if (!editable || !g) {
    if (hint !== "header") return <span className="truncate">{value}</span>
    // before the first publish the terms are the contract header's, edited on the contract page
    return (
      <Tooltip content={t("rates.selling.edit_in_header")}>
        <span className="truncate" tabIndex={0}>
          {value}
        </span>
      </Tooltip>
    )
  }
  const saleBad = Boolean(g.sale_from && g.sale_to && g.sale_from > g.sale_to)
  const stayBad = Boolean(g.stay_from && g.stay_to && g.stay_from > g.stay_to)
  return (
    <>
      <button ref={ref} type="button" aria-haspopup="dialog" aria-expanded={open} className={cn(CHIP_BUTTON, "-my-0.5")} onClick={() => setOpen(!open)}>
        <span className="truncate">{value}</span>
        <ChevronDown className="size-3.5 self-center text-zinc-500" aria-hidden />
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchorRef={ref} label={t("rates.selling.title")} width={what === "dates" ? "lg" : "sm"}>
        {what === "dates" ? (
          <FormGrid cols={2}>
            <Field label={t("rates.f.sale_from")}>
              <Input type="date" value={g.sale_from} onChange={(e) => setSelling({ sale_from: e.target.value })} data-autofocus />
            </Field>
            <Field label={t("rates.f.sale_to")} error={saleBad ? t("rates.v.range") : undefined}>
              <Input type="date" value={g.sale_to} onChange={(e) => setSelling({ sale_to: e.target.value })} />
            </Field>
            <Field label={t("rates.f.stay_from")}>
              <Input type="date" value={g.stay_from} onChange={(e) => setSelling({ stay_from: e.target.value })} />
            </Field>
            <Field label={t("rates.f.stay_to")} error={stayBad ? t("rates.v.range") : undefined}>
              <Input type="date" value={g.stay_to} onChange={(e) => setSelling({ stay_to: e.target.value })} />
            </Field>
          </FormGrid>
        ) : (
          <Field label={t("rates.f.sell_currency")} hint={t("rates.h.sell_currency")}>
            <Select
              value={g.sell_currency}
              onChange={(e) => setSelling({ sell_currency: e.target.value })}
              options={boot.currencies.map((c) => ({ value: c, label: c }))}
              placeholder={t("rates.common.same_as_contract")}
              data-autofocus
            />
          </Field>
        )}
        <p className="mt-3 text-xs text-zinc-500">{t("rates.ws.selling_unsaved")}</p>
      </Popover>
    </>
  )
}

/** The live check chip: the server's issue counts for what the editor shows (overlay), or the
 * report stored at publish ("Checked when published"); a click lists them, grouped by section
 * (S15), and a click on one shows its cell (switching section, opening a region or the rooms scope
 * as needed), or the region or rule table that holds it. Hidden when there is nothing to show (a
 * catalogue, or a frozen version without a stored report). When the check of the state on screen
 * could not run, the chip says so (not older counts, not a spinner) and its popover gives the
 * server's reason and Try again. */
function LiveCheck({ preview, issueText, onShowIssue }: { preview: DraftPreview; issueText?: (issue: Issue) => string; onShowIssue?: (index: number) => void }) {
  const { t } = useTexT()
  const ref = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  if (preview.issuesSource === "none") return null
  const live = preview.issuesSource === "live"
  const failed = live && preview.issuesState === "failed"
  const busy = live && preview.issuesState === "busy"
  const issues: Issue[] | undefined = preview.issues
  const errors = issues?.filter((i) => i.level === "ERROR").length ?? 0
  const warnings = (issues?.length ?? 0) - errors
  const title = live ? t("rates.ws.check.live") : t("rates.ws.check.published")
  return (
    <>
      <button
        ref={ref}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-busy={busy || undefined}
        className={cn(CHIP_BUTTON, "items-center", busy && "text-zinc-500")}
        onClick={() => setOpen(!open)}
      >
        <span className="text-xs text-zinc-500">{title}</span>
        {failed ? (
          <span className="inline-flex items-center gap-1 text-amber-800">
            <AlertTriangle className="size-3.5" aria-hidden />
            <span className="sr-only">{t("rates.ws.check.failed")}</span>
          </span>
        ) : !issues ? (
          <span className="text-zinc-500">…</span>
        ) : errors + warnings === 0 ? (
          <span className="inline-flex items-center gap-1 text-emerald-800">
            <CheckCircle2 className="size-3.5 text-emerald-600" aria-hidden />
            {t("rates.ws.check.none")}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 tabular-nums">
            {errors > 0 && (
              <span className="inline-flex items-center gap-0.5 text-rose-700">
                <AlertOctagon className="size-3.5" aria-hidden />
                {t("rates.ws.check.errors", { count: errors })}
              </span>
            )}
            {warnings > 0 && (
              <span className="inline-flex items-center gap-0.5 text-amber-800">
                <AlertTriangle className="size-3.5" aria-hidden />
                {t("rates.ws.check.warnings", { count: warnings })}
              </span>
            )}
          </span>
        )}
        {busy && (
          <>
            <Loader2 className="size-3.5 animate-spin self-center text-zinc-400" aria-hidden />
            <span className="sr-only">{t("rates.version.checking")}</span>
          </>
        )}
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchorRef={ref} label={title} width="lg">
        <div className="max-h-[60vh] space-y-2">
          {live && preview.savedOnly && <p className="text-xs text-zinc-600">{t("rates.ws.over_cap", { max: preview.maxRows ?? "" })}</p>}
          {busy && <p className="text-xs text-zinc-500">{t("rates.version.checking")}</p>}
          {failed && (
            <div className="space-y-2" role="status">
              <p className="text-sm whitespace-pre-line text-amber-900">
                {t("rates.ws.check.failed")}: {preview.issuesError?.message}
              </p>
              <Button variant="secondary" size="sm" icon={<RotateCcw className="size-4" aria-hidden />} onClick={preview.refetch}>
                {t("core.action.retry")}
              </Button>
            </div>
          )}
          {issues &&
            (issues.length ? (
              <IssueNav
                issues={issues}
                stale={live && preview.issuesStale}
                issueText={issueText}
                onShow={
                  onShowIssue
                    ? (index) => {
                        setOpen(false)
                        onShowIssue(index)
                      }
                    : undefined
                }
              />
            ) : (
              <p className="flex items-center gap-2 text-sm text-emerald-800" role="status">
                <CheckCircle2 className="size-4 text-emerald-600" aria-hidden />
                {t("rates.ws.check.clean")}
              </p>
            ))}
        </div>
      </Popover>
    </>
  )
}

/** At most this many issues per section in the chip's list (the sweep reports up to 200). */
const NAV_MAX = 50

/** The live check's issues by section, errors first; each one a button that shows where it is. */
function IssueNav({ issues, stale, issueText, onShow }: { issues: Issue[]; stale: boolean; issueText?: (issue: Issue) => string; onShow?: (index: number) => void }) {
  const { t } = useTexT()
  const groups = issuesBySection(issues)
  const hintId = useId()
  return (
    <div className={cn("space-y-3", stale && "opacity-60")}>
      {onShow && (
        <p id={hintId} className="text-xs text-zinc-500">
          {t("rates.ws.issue.nav_hint")}
        </p>
      )}
      {groups.map((g) => (
        <section key={g.section} aria-label={t("rates.ws.issue.group", { section: t(`rates.section.${g.section}`), count: g.items.length })}>
          <h3 className="flex flex-wrap items-center gap-x-2 text-xs font-semibold text-zinc-700">
            {t(`rates.section.${g.section}`)}
            <span className="inline-flex items-center gap-1.5 font-normal tabular-nums">
              {g.errors > 0 && <span className="text-rose-700">{t("rates.ws.check.errors", { count: g.errors })}</span>}
              {g.warnings > 0 && <span className="text-amber-800">{t("rates.ws.check.warnings", { count: g.warnings })}</span>}
            </span>
          </h3>
          <ul className="mt-1 space-y-0.5">
            {g.items.slice(0, NAV_MAX).map(({ issue, index }) => {
              const error = issue.level === "ERROR"
              const Icon = error ? AlertOctagon : AlertTriangle
              const body = (
                <>
                  <Icon className={cn("mt-0.5 size-3.5 shrink-0", error ? "text-rose-600" : "text-amber-600")} aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="sr-only">{t(error ? "rates.ws.issue.level_error" : "rates.ws.issue.level_warning")}: </span>
                    <span className="font-mono text-[11px] text-zinc-500">{issue.code}</span> {issueText ? issueText(issue) : issue.message}
                  </span>
                </>
              )
              return (
                <li key={index}>
                  {onShow ? (
                    <button
                      type="button"
                      aria-describedby={hintId}
                      onClick={() => onShow(index)}
                      className="group flex w-full items-start gap-1.5 rounded-md px-1.5 py-1 text-left text-sm text-zinc-900 hover:bg-zinc-100 focus-visible:ring-2 focus-visible:ring-tex-500 focus-visible:outline-none"
                    >
                      {body}
                      <CornerDownRight className="mt-0.5 size-3.5 shrink-0 text-zinc-400 group-hover:text-zinc-700" aria-hidden />
                    </button>
                  ) : (
                    <div className="flex items-start gap-1.5 px-1.5 py-1 text-sm text-zinc-900">{body}</div>
                  )}
                </li>
              )
            })}
            {g.items.length > NAV_MAX && <li className="px-1.5 text-xs text-zinc-500">{t("rates.ws.issue.more", { count: g.items.length - NAV_MAX })}</li>}
          </ul>
        </section>
      ))}
    </div>
  )
}
