// The occupancy ladder and the boards grid have no clipboard and no fills of their own (ADR-061 S11
// deviation 8): Ctrl/Cmd+C, Ctrl/Cmd+V, Ctrl/Cmd+R and Ctrl/Cmd+D on one of their cells did nothing
// without a word, so a column of child factors pasted from a spreadsheet simply vanished. They now
// say where those work and what to use here instead (S16 re-review).
import { useCallback, useEffect, useRef, type RefObject } from "react"
import { useTexT } from "../../../i18n"
import { useToast } from "../../../ui"

/** Listens for copy and paste on a focused cell of `gridEl` (the events reach the document while a
 * cell has the focus, as in the matrix; a cell editor's own copy and paste are left alone), and
 * returns the notice for the grid's key handler to show on Ctrl/Cmd+R and Ctrl/Cmd+D. A viewer who
 * cannot edit (`canEdit` false) is only told where copy works: there is no entry to type for them
 * (S16 re-review 2). */
export function useMatrixOnlyBulk(gridEl: RefObject<HTMLElement | null>, canEdit: boolean): () => void {
  const { t } = useTexT()
  const toast = useToast()
  const notice = useRef(() => {})
  notice.current = () => toast.info(t(canEdit ? "rates.ws.bulk.matrix_only" : "rates.ws.bulk.matrix_only_ro"))
  useEffect(() => {
    const onClip = (e: ClipboardEvent) => {
      const a = document.activeElement
      if (!(a instanceof HTMLElement) || a.getAttribute("role") !== "gridcell" || !gridEl.current?.contains(a)) return
      e.preventDefault()
      notice.current()
    }
    document.addEventListener("copy", onClip)
    document.addEventListener("paste", onClip)
    return () => {
      document.removeEventListener("copy", onClip)
      document.removeEventListener("paste", onClip)
    }
  }, [gridEl])
  return useCallback(() => notice.current(), [])
}
