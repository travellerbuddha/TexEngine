// The live draft preview (PRICING_WORKSPACE_UX.md §3.14, slice S8): the server's resolved prices and
// issues for what the editor shows, before anything is saved. The request policy (modes, debounce,
// one validation in flight) is the pure draftPreview.ts; this is its React binding.
//
// - overlay (an editable draft): price_matrix and validate_version are POSTed with the unsaved
//   payload (overlayPayloadOf), 300 ms and ≥ 1.2 s after the last edit. A newer edit aborts the
//   matrix call it makes stale. Validation costs the server seconds, so at most one runs: edits
//   made meanwhile are checked once, after it (the call in flight is not aborted: the server
//   would finish it anyway).
// - saved (not editable, cost visible): one GET of price_matrix per doc.modified; never a
//   validation (it needs contract.edit): the issues are those stored at publish.
// - catalogue (an agent): no request at all.
//
// Results are tagged with the fingerprint of the state they were computed for (`forKey`); `stale`
// says they describe another state (or the version before a refresh) than the one on screen.
// The client computes nothing from them.
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { tex, TexApiError } from "../../../lib/api"
import { fingerprint, overlayPayloadOf, type EditorState } from "../lib/tables"
import { VERSION_TABLES, type Issue, type PriceMatrix, type PriceMatrixResponse, type SampleParty, type ValidationResult, type VersionDoc } from "../lib/types"
import { latestOnly, matrixRequest, MATRIX_DEBOUNCE_MS, previewMode, storedIssues, validateDelay, validationRequest, type PreviewMode } from "./draftPreview.ts"

export interface DraftPreviewOptions {
  /** fingerprint(state), when the caller has already computed it */
  fingerprint?: string
  /** sample parties of the occupancy ladder (GAP-2b, S11), priced in `partyRoom` */
  parties?: SampleParty[]
  partyRoom?: string
}

export interface DraftPreview {
  mode: PreviewMode
  /** the fingerprint of the state on screen */
  key: string
  matrix?: PriceMatrix
  /** the fingerprint the matrix was computed for */
  forKey?: string
  /** the matrix (or its build error) describes another state than the one on screen, or a refresh is on its way */
  stale: boolean
  /** a price_matrix call is in flight */
  loading: boolean
  /** the last price_matrix call failed (the previous matrix stays, stale) */
  error?: TexApiError
  /** the draft cannot be built as it stands (price_matrix `build_error`) */
  buildError?: string
  /** overlay: the live check of the state `issuesForKey`; saved: the report stored at publish */
  issues?: Issue[]
  issuesForKey?: string
  issuesSource: "live" | "published" | "none"
  issuesStale: boolean
  /** a validation is in flight */
  validating: boolean
  issuesError?: TexApiError
  /** Ask again (e.g. after the contract header changed): the matrix, and in overlay mode the issues. */
  refetch: () => void
  /** Validate the state on screen now (the Validate button), still one validation at a time. */
  validateNow: () => void
}

interface ValidationJob {
  key: string
  forKey: string
  args: Record<string, unknown>
}

const asError = (e: unknown) => (e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error"))
const isAbort = (e: unknown) => (e as Error | undefined)?.name === "AbortError"
const SEP = "\u0001"

export function useDraftPreview(doc: VersionDoc | undefined, state: EditorState | undefined, opts: DraftPreviewOptions = {}): DraftPreview {
  const mode: PreviewMode = doc ? previewMode(doc) : "catalogue"
  const own = useMemo(() => (opts.fingerprint === undefined && state ? fingerprint(state) : ""), [opts.fingerprint, state])
  const key = opts.fingerprint ?? own
  // the rows' client keys name the rule ids of an overlay answer ("~" + _key); the fingerprint
  // ignores them, so a reload of the version (new keys, same content) must ask again
  const rowKeys = useMemo(() => (state ? VERSION_TABLES.map((t) => state.tables[t].map((r) => r._key).join(",")).join(";") : ""), [state])
  const stateRef = useRef(state)
  stateRef.current = state
  const version = doc?.name ?? ""
  const modified = doc?.modified ?? ""
  const { parties, partyRoom } = opts
  const partiesJson = parties?.length && partyRoom ? JSON.stringify([parties, partyRoom]) : ""
  const partiesRef = useRef({ parties, partyRoom })
  partiesRef.current = { parties, partyRoom }
  const [tick, setTick] = useState(0)

  // ─── resolved prices (price_matrix) ───────────────────────────────────
  // what the matrix depends on: in overlay mode the payload (a save does not change the answer),
  // in saved mode the stored version; a refresh (tick) and the sample parties in both
  const matrixKey = !doc || mode === "catalogue" ? "" : mode === "overlay" ? [version, "overlay", tick, partiesJson, rowKeys, key].join(SEP) : [version, "saved", modified, tick, partiesJson].join(SEP)
  const [mx, setMx] = useState<{ full: string; forKey: string; matrix?: PriceMatrix; buildError?: string }>()
  const [mxError, setMxError] = useState<TexApiError>()
  const [mxLoading, setMxLoading] = useState(false)
  const answered = useRef(false)

  useEffect(() => {
    if (!matrixKey) {
      setMxLoading(false)
      return
    }
    const ctl = new AbortController()
    const forKey = key
    const fire = () => {
      const st = stateRef.current
      const req = matrixRequest(mode, { version, data: mode === "overlay" && st ? overlayPayloadOf(st) : undefined, ...partiesRef.current })
      if (!req) return
      setMxLoading(true)
      tex<PriceMatrixResponse>("contracts", "price_matrix", req.args, { post: req.post, signal: ctl.signal })
        .then((r) => {
          setMx(r.build_error !== undefined ? { full: matrixKey, forKey, buildError: r.build_error } : { full: matrixKey, forKey, matrix: r })
          setMxError(undefined)
        })
        .catch((e: unknown) => {
          if (!isAbort(e)) setMxError(asError(e))
        })
        .finally(() => {
          if (ctl.signal.aborted) return
          answered.current = true
          setMxLoading(false)
        })
    }
    // the first answer at once, then after the user pauses
    const timer = setTimeout(fire, mode === "overlay" && answered.current ? MATRIX_DEBOUNCE_MS : 0)
    return () => {
      clearTimeout(timer)
      ctl.abort()
    }
    // the key names everything the call depends on
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matrixKey])

  // ─── live check (validate_version with data), overlay mode only ───────
  const [vtick, setVtick] = useState(0)
  const now = useRef(false)
  const lastMs = useRef<number | null>(null)
  const [iss, setIss] = useState<{ full: string; forKey: string; issues: Issue[] }>()
  const [issError, setIssError] = useState<TexApiError>()
  const [validating, setValidating] = useState(false)
  const validKey = doc && mode === "overlay" ? [version, tick, vtick, rowKeys, key].join(SEP) : ""
  const checked = useRef<string | null>(null)

  const flight = useMemo(
    () =>
      latestOnly<ValidationJob>(async (job, signal) => {
        const t0 = performance.now()
        setValidating(true)
        try {
          const r = await tex<ValidationResult>("contracts", "validate_version", job.args, { post: true, signal })
          checked.current = job.key
          setIss({ full: job.key, forKey: job.forKey, issues: r.issues ?? [] })
          setIssError(undefined)
        } catch (e) {
          if (!isAbort(e)) setIssError(asError(e))
        } finally {
          if (!signal.aborted) lastMs.current = performance.now() - t0
          setValidating(false)
        }
      }),
    [],
  )
  useEffect(() => () => flight.cancel(), [flight])

  useEffect(() => {
    if (!validKey) {
      flight.cancel()
      setValidating(false)
      return
    }
    if (checked.current === validKey) return
    // the first check at once; then after the user pauses, at least as long as the last one took
    const delay = now.current || lastMs.current === null ? 0 : validateDelay(lastMs.current)
    now.current = false
    const forKey = key
    const timer = setTimeout(() => {
      const st = stateRef.current
      const req = st ? validationRequest(mode, { version, data: overlayPayloadOf(st) }) : null
      if (req) flight.want({ key: validKey, forKey, args: req.args })
    }, delay)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [validKey])

  const refetch = useCallback(() => setTick((n) => n + 1), [])
  const validateNow = useCallback(() => {
    now.current = true
    setVtick((n) => n + 1)
  }, [])

  const published = mode === "saved" && doc ? storedIssues(doc.validation_report) : undefined
  const live = mode === "overlay"
  return {
    mode,
    key,
    matrix: mode === "catalogue" ? undefined : mx?.matrix,
    forKey: mode === "catalogue" ? undefined : mx?.forKey,
    stale: mode !== "catalogue" && mx?.full !== matrixKey,
    loading: mode !== "catalogue" && mxLoading,
    error: mode === "catalogue" ? undefined : mxError,
    buildError: mode === "catalogue" ? undefined : mx?.buildError,
    issues: live ? iss?.issues : published,
    issuesForKey: live ? iss?.forKey : undefined,
    issuesSource: live ? "live" : published ? "published" : "none",
    issuesStale: live && iss?.full !== validKey,
    validating: live && validating,
    issuesError: live ? issError : undefined,
    refetch,
    validateNow,
  }
}
