import { createContext, useContext, type ReactNode } from "react"
import type { Option } from "../../../../ui"
import { IssueList } from "../../components/common"
import type { EditorState, SellingForm } from "../../lib/tables"
import type { Issue, Lookups, Row, VersionDoc, VersionSetting, VersionTable } from "../../lib/types"
import { issueTable } from "../../lib/util"
import type { AnchoredIssues } from "../../workspace/issues.ts"
import type { ShowRequest, ShowTarget } from "../../workspace/priceTest.ts"
import type { DraftPreview, SampleRequest } from "../../workspace/useDraftPreview"
import type { WorkspaceHistory } from "../../workspace/useWorkspaceHistory"

export interface TabProps {
  doc: VersionDoc
  state: EditorState
  readOnly: boolean
  issues: Issue[] | undefined
  setTable: (t: VersionTable, rows: Row[]) => void
  setSetting: (k: VersionSetting, v: string | number) => void
  /** Edit the draft's selling terms (only when ``state.selling`` is set). */
  setSelling: (patch: Partial<SellingForm>) => void
  lookups?: Lookups
  /** Whether the editor has unsaved edits (server previews use the saved draft). */
  dirty: boolean
  onSave?: () => void
  /** The editor's live preview (useDraftPreview): the resolved prices shown instead of fetching
   * them again, and no cost call for a viewer who may not make it. */
  preview?: DraftPreview
  /** The workspace undo history (useWorkspaceHistory): every workspace edit goes through it. */
  history?: WorkspaceHistory
  /** Bumped each time the editor loads a version (and on Discard): workspace views keyed on it
   * start afresh (no edit in progress, no error drafts). */
  epoch?: number
  /** The occupancy ladder asks the live preview to price a sample party (GAP-2b, S11); null stops it. */
  setSampleParty?: (request: SampleRequest | null) => void
  /** "Test this price" on a matrix cell: the Price test for that room and period (S14); absent
   * when the viewer may not use the Price test (`can_preview`). */
  onPriceTest?: (cell: MatrixCellRef) => void
  /** The matrix cell that got the focus: the header's Price test starts from it (S14). */
  onMatrixCell?: (cell: MatrixCellRef) => void
  /** "Show in grid" from the Price test (S14): Pricing shows and focuses the target. */
  showInGrid?: (target: ShowTarget) => void
  /** A pending "Show in grid" request: the grid that holds the target focuses it and calls
   * `onShown(n)`, which clears it (a later remount does not replay it). */
  show?: ShowRequest | null
  onShown?: (n: number) => void
  /** Where the issues are shown (issues.anchorIssues over `issues` and the tables on screen, S15):
   * the grids mark the cells they point at. */
  anchored?: AnchoredIssues
  /** An issue's message as shown: band codes as their labels (D13). */
  issueText?: (issue: Issue) => string
  /** The issues belong to an older state than the one on screen (the live check is on its way). */
  issuesStale?: boolean
}

/** A matrix cell: its room and period ("" = All periods). */
export interface MatrixCellRef {
  room: string
  period: string
}

export function roomOptions(doc: VersionDoc): Option[] {
  return doc.room_types.map((r) => ({ value: r.name, label: r.room_type_name || r.name }))
}

/** Room types that are part of this contract (Rooms tab), in table order. */
export function contractRoomOptions(doc: VersionDoc, state: EditorState): Option[] {
  const all = roomOptions(doc)
  return state.tables.rooms
    .map((r) => String(r.room_type || ""))
    .filter(Boolean)
    .map((rt) => all.find((o) => o.value === rt) ?? { value: rt, label: rt })
}

export function periodOptions(state: EditorState): Option[] {
  return state.tables.periods
    .filter((p) => String(p.period_code || "").trim())
    .map((p) => ({ value: String(p.period_code).trim(), label: p.period_name ? `${p.period_code} · ${p.period_name}` : String(p.period_code) }))
}

export function bandOptions(state: EditorState): Option[] {
  return state.tables.age_bands
    .filter((b) => String(b.band_code || "").trim())
    .map((b) => {
      const code = String(b.band_code).trim().toUpperCase()
      return { value: code, label: b.label ? `${code} · ${b.label}` : code }
    })
}

/** How the version editor shows an issue's message (band codes as labels, D13), for the lists of
 * the Advanced rule tables and Offers; the server's message outside the editor. */
export const IssueFormatContext = createContext<((issue: Issue) => string) | undefined>(undefined)

/** The issues an Advanced rule table (or Offers) lists: its own, as the ten-tab editor did. */
export function TabIssues({ issues, tab }: { issues: Issue[] | undefined; tab: string }) {
  const format = useContext(IssueFormatContext)
  const mine = issues?.filter((i) => issueTable(i.code, i.ref) === tab)
  if (!mine?.length) return null
  return <IssueList issues={mine} format={format} />
}

export function TabIntro({ title, children, aside }: { title: ReactNode; children?: ReactNode; aside?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="max-w-3xl space-y-1">
        <h2 className="text-base font-semibold text-zinc-900">{title}</h2>
        {children && <div className="text-sm text-zinc-600">{children}</div>}
      </div>
      {aside}
    </div>
  )
}
