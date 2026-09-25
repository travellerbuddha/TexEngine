import type { ReactNode } from "react"
import type { Option } from "../../../../ui"
import { IssueList } from "../../components/common"
import type { EditorState, SellingForm } from "../../lib/tables"
import type { Issue, Lookups, Row, VersionDoc, VersionSetting, VersionTable } from "../../lib/types"
import { issueTable } from "../../lib/util"
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

/** The issues an Advanced rule table (or Offers) lists: its own, as the ten-tab editor did. */
export function TabIssues({ issues, tab }: { issues: Issue[] | undefined; tab: string }) {
  const mine = issues?.filter((i) => issueTable(i.code, i.ref) === tab)
  if (!mine?.length) return null
  return <IssueList issues={mine} />
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
