// The validation issues a cell of the workspace shows (PRICING_WORKSPACE_UX.md §3.3.3 `error`,
// §3.15, §3.19; slice S15): the matrix, the ladder, the boards grid, the combination cards and the
// period headers look their anchor id up here (issues.anchorIssues) and get the cell's issue state,
// its level (an error or only warnings) and the text a screen reader reads and the tooltip shows,
// with band codes as labels.
import { useCallback } from "react"
import { useTexT } from "../../../i18n"
import type { Issue } from "../lib/types"
import type { AnchoredIssues } from "./issues.ts"

export interface CellIssue {
  /** ERROR when one of its issues is an error (publish is refused), else WARNING */
  level: "ERROR" | "WARNING"
  /** "Error: room SUP has two rules for period P4 · Warning: …" (at most three, then "+N more") */
  text: string
  /** the issues belong to an older state than the one on screen (the live check is on its way) */
  stale: boolean
  count: number
}

const SHOWN = 3

export function useCellIssues(anchored: AnchoredIssues | undefined, issueText: ((issue: Issue) => string) | undefined, stale: boolean | undefined): (id: string) => CellIssue | undefined {
  const { t } = useTexT()
  return useCallback(
    (id: string) => {
      const list = anchored?.byCell.get(id)
      if (!list?.length) return undefined
      const errors = list.filter((i) => i.level === "ERROR")
      // errors first: what blocks publishing is read first
      const ordered = [...errors, ...list.filter((i) => i.level !== "ERROR")]
      const parts = ordered
        .slice(0, SHOWN)
        .map((i) => t(i.level === "ERROR" ? "rates.ws.issue.error" : "rates.ws.issue.warning", { message: issueText ? issueText(i) : i.message }))
      if (ordered.length > SHOWN) parts.push(t("rates.ws.issue.more", { count: ordered.length - SHOWN }))
      return { level: errors.length ? "ERROR" : "WARNING", text: parts.join(" · "), stale: Boolean(stale), count: list.length }
    },
    [anchored, issueText, stale, t],
  )
}
