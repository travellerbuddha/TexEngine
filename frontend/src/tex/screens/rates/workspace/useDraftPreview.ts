// The live draft preview (PRICING_WORKSPACE_UX.md §3.14, slice S8): the server's resolved prices and
// issues for what the editor shows, before anything is saved. The request policy (modes, debounce,
// one validation in flight) is the pure draftPreview.ts; this is its React binding.
//
// - overlay (an editable draft): price_matrix and validate_version are POSTed with the unsaved
//   payload (overlayPayloadOf), 300 ms and ≥ 1.2 s after the last edit. A newer edit aborts the
//   matrix call it makes stale. Validation costs the server seconds, so at most one runs: edits
//   made meanwhile are checked once, after it (the call in flight is not aborted: the server
//   would finish it anyway). The saved draft is asked for by name instead (no payload, no row
//   cap; previewSource) while the screen shows it (`base`), for the Check button, and when the
//   overlay does not take the draft (above `doc.overlay_max_rows`, or refused as too large): then
//   the answers are the saved draft's, and `savedOnly` says the unsaved changes are not in them.
// - saved (not editable, cost visible): one GET of price_matrix per doc.modified; never a
//   validation (it needs contract.edit): the issues are those stored at publish.
// - catalogue (an agent): no request at all.
//
// Results are tagged with the fingerprint of the state they were computed for (`forKey`); `stale`
// says they describe another state (or the version before a refresh) than the one on screen, and
// `matrixState` / `issuesState` whether an answer is on its way, there, or failed for the state
// on screen (callState). The occupancy ladder's sample parties go with the matrix call, but the
// rooms' prices do not depend on them: an answer asked again only for another party is not stale
// (pricesKey), and `partiesFor` names the parties an answer priced (sampleKey), so the ladder never
// shows one party's totals for another. The client computes nothing from them.
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { tex, TexApiError } from "../../../lib/api"
import { fingerprint, overlayPayloadOf, type EditorState } from "../lib/tables"
import { VERSION_TABLES, type Issue, type PriceMatrix, type PriceMatrixResponse, type SampleParty, type ValidationResult, type VersionDoc } from "../lib/types"
import {
  alreadyChecked,
  callState,
  isTooLarge,
  latestOnly,
  matrixRequest,
  MATRIX_DEBOUNCE_MS,
  overlayFits,
  overlayRows,
  previewKeys,
  previewMode,
  previewSource,
  pricesKey,
  sampleKey,
  storedIssues,
  validateDelay,
  validationRequest,
  type CallState,
  type PreviewMode,
} from "./draftPreview.ts"

/** The sample parties the occupancy ladder's resolved line asks for (GAP-2b, S11), priced in `room`. */
export interface SampleRequest {
  room: string
  parties: SampleParty[]
}

export interface DraftPreviewOptions {
  /** fingerprint(state), when the caller has already computed it */
  fingerprint?: string
  /** the fingerprint of the saved draft (the editor's save base): while the state on screen has it,
   * the saved draft is asked for by name (§3.15) */
  base?: string
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
  /** the matrix's room prices (or its build error) describe another state than the one on screen, or
   * a refresh is on its way; not when only the sample parties changed (pricesKey) */
  stale: boolean
  /** a price_matrix call is in flight */
  loading: boolean
  /** a price_matrix call for other room prices than the answer's is in flight (not one asked only
   * for another sample party) */
  pricesLoading: boolean
  /** the sample parties the matrix's `party_cells` priced (sampleKey of what was sent; "" none) */
  partiesFor?: string
  /** the matrix wanted: on its way (busy), there (ready), or its call failed (failed: `error`, until the state changes or refetch) */
  matrixState: CallState
  /** the price_matrix call for the state on screen failed (an older matrix may stay, stale) */
  error?: TexApiError
  /** the draft cannot be built as it stands (price_matrix `build_error`) */
  buildError?: string
  /** overlay: the live check of the state `issuesForKey` (none while the check of the state on
   * screen failed: older issues would read as current, in the chip, the section badges and the
   * lists); saved: the report stored at publish */
  issues?: Issue[]
  issuesForKey?: string
  issuesSource: "live" | "published" | "none"
  issuesStale: boolean
  /** a validation is in flight */
  validating: boolean
  /** the live check wanted: on its way, there, or failed (`issuesError`); "ready" when there is no live check */
  issuesState: CallState
  /** the validation of the state on screen failed (an older check may stay, stale) */
  issuesError?: TexApiError
  /** overlay mode: the draft has more rows than the overlay takes and unsaved changes, so the
   * matrix and the live check are the saved draft's, without them (until a save) */
  savedOnly: boolean
  /** the most rows the overlay takes (get_version `overlay_max_rows`) */
  maxRows?: number
  /** Ask again (e.g. after the contract header changed): the matrix, and in overlay mode the issues. */
  refetch: () => void
  /** Validate the state on screen now (the Validate button), still one validation at a time. */
  validateNow: () => void
}

interface ValidationJob {
  key: string
  forKey: string
  /** the rows of the state sent (a row-cap refusal is remembered by them) */
  rows: number
  args: Record<string, unknown>
  post: boolean
}

interface Failure {
  key: string
  error: TexApiError
}

const asError = (e: unknown) => (e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error"))
const isAbort = (e: unknown) => (e as Error | undefined)?.name === "AbortError"

export function useDraftPreview(doc: VersionDoc | undefined, state: EditorState | undefined, opts: DraftPreviewOptions = {}): DraftPreview {
  const mode: PreviewMode = doc ? previewMode(doc) : "catalogue"
  const own = useMemo(() => (opts.fingerprint === undefined && state ? fingerprint(state) : ""), [opts.fingerprint, state])
  const key = opts.fingerprint ?? own
  const base = opts.base
  // the rows' client keys name the rule ids of an overlay answer ("~" + _key); the fingerprint
  // ignores them, so a reload of the version (new keys, same content) must ask again
  const rowKeys = useMemo(() => (state ? VERSION_TABLES.map((t) => state.tables[t].map((r) => r._key).join(",")).join(";") : ""), [state])
  const rows = useMemo(() => (state ? overlayRows(state.tables) : 0), [state])
  const stateRef = useRef(state)
  stateRef.current = state
  const version = doc?.name ?? ""
  const modified = doc?.modified ?? ""
  const { parties, partyRoom } = opts
  const partiesJson = sampleKey(parties, partyRoom)
  const savedRooms = useMemo(() => (doc?.rooms ?? []).map((r) => String(r.room_type ?? "").trim()).filter(Boolean), [doc?.rooms])
  const partiesRef = useRef({ parties, partyRoom, savedRooms })
  partiesRef.current = { parties, partyRoom, savedRooms }
  const [tick, setTick] = useState(0)
  const [vtick, setVtick] = useState(0)

  // ─── where the answers come from (previewSource) and what they depend on (previewKeys) ────────
  const clean = base !== undefined && key === base
  const maxRows = mode === "overlay" ? doc?.overlay_max_rows : undefined
  // a state of this many rows was refused as too large (OverlayTooLarge): no overlay until fewer
  const [refused, setRefused] = useState<{ version: string; rows: number }>()
  const refusedRows = refused && refused.version === version ? refused.rows : null
  const fits = overlayFits({ rows, maxRows, refusedRows })
  const keyInput = { version, modified, tick, vtick, parties: partiesJson, rowKeys, key, fits }
  const keys = previewKeys(mode, keyInput)
  const matrixKey = doc ? keys.matrix : ""
  const prices = doc ? pricesKey(mode, keyInput) : ""
  const validKey = doc ? keys.valid : ""
  const source = previewSource(mode, { clean, rows, maxRows, refusedRows })
  const savedOnly = mode === "overlay" && !fits && !clean
  // an answer about the saved draft describes the save base, not what the screen shows
  const describes = (src: string | null) => (src === "saved" && base !== undefined ? base : key)
  const refuse = useCallback((n: number) => setRefused({ version, rows: n }), [version])

  // ─── resolved prices (price_matrix) ───────────────────────────────────
  // `prices`: the answer's pricesKey; `parties`: the sampleKey of the parties it was asked with
  const [mx, setMx] = useState<{ full: string; prices: string; parties: string; forKey: string; matrix?: PriceMatrix; buildError?: string }>()
  const [mxError, setMxError] = useState<Failure>()
  // the pricesKey of the call in flight, null when none
  const [mxLoading, setMxLoading] = useState<string | null>(null)
  const answered = useRef(false)

  useEffect(() => {
    if (!matrixKey) {
      setMxLoading(null)
      return
    }
    const ctl = new AbortController()
    const full = matrixKey
    const forPrices = prices
    const src = source ?? "saved"
    const forKey = describes(src)
    const fire = () => {
      const st = stateRef.current
      const req = matrixRequest(mode, { version, source: src, data: src === "overlay" && st ? overlayPayloadOf(st) : undefined, ...partiesRef.current })
      if (!req) return
      const sent = st ? overlayRows(st.tables) : 0
      const priced = sampleKey(req.args.parties, req.args.party_room)
      setMxLoading(forPrices)
      tex<PriceMatrixResponse>("contracts", "price_matrix", req.args, { post: req.post, signal: ctl.signal })
        .then((r) => {
          const tag = { full, prices: forPrices, parties: priced, forKey }
          setMx(r.build_error !== undefined ? { ...tag, buildError: r.build_error } : { ...tag, matrix: r })
        })
        .catch((e: unknown) => {
          if (isAbort(e)) return
          if (req.post && isTooLarge(e)) refuse(sent)
          setMxError({ key: full, error: asError(e) })
        })
        .finally(() => {
          if (ctl.signal.aborted) return
          answered.current = true
          setMxLoading(null)
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

  // ─── live check (validate_version), overlay mode only ─────────────────
  const now = useRef(false)
  const lastMs = useRef<number | null>(null)
  const [iss, setIss] = useState<{ full: string; forKey: string; issues: Issue[] }>()
  const [issError, setIssError] = useState<Failure>()
  const [validating, setValidating] = useState(false)
  const checked = useRef<string | null>(null)
  const refuseRef = useRef(refuse)
  refuseRef.current = refuse

  const flight = useMemo(
    () =>
      latestOnly<ValidationJob>(async (job, signal) => {
        const t0 = performance.now()
        setValidating(true)
        try {
          const r = await tex<ValidationResult>("contracts", "validate_version", job.args, { post: job.post, signal })
          checked.current = job.key
          setIss({ full: job.key, forKey: job.forKey, issues: r.issues ?? [] })
        } catch (e) {
          if (!isAbort(e)) {
            if (job.post && isTooLarge(e)) refuseRef.current(job.rows)
            setIssError({ key: job.key, error: asError(e) })
          }
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
    if (alreadyChecked(validKey, checked.current, flight.busy())) return
    // the first check at once; then after the user pauses, at least as long as the last one took
    const asked = now.current
    const delay = asked || lastMs.current === null ? 0 : validateDelay(lastMs.current)
    now.current = false
    // the Check button validates the saved draft by name (§3.15), as does a clean or too large draft
    const src = previewSource(mode, { clean, rows, maxRows, refusedRows, now: asked }) ?? "saved"
    const forKey = describes(src)
    const timer = setTimeout(() => {
      const st = stateRef.current
      const req = st ? validationRequest(mode, { version, source: src, data: src === "overlay" ? overlayPayloadOf(st) : undefined }) : null
      if (req) flight.want({ key: validKey, forKey, rows: st ? overlayRows(st.tables) : 0, args: req.args, post: req.post })
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
  const catalogue = mode === "catalogue"
  const matrixState = catalogue ? "ready" : callState({ key: matrixKey, answered: mx?.full, failed: mxError?.key, running: mxLoading !== null })
  const issuesState = live ? callState({ key: validKey, answered: iss?.full, failed: issError?.key, running: validating }) : "ready"
  return {
    mode,
    key,
    matrix: catalogue ? undefined : mx?.matrix,
    forKey: catalogue ? undefined : mx?.forKey,
    stale: !catalogue && mx?.prices !== prices,
    loading: !catalogue && mxLoading !== null,
    pricesLoading: !catalogue && mxLoading !== null && mxLoading !== mx?.prices,
    partiesFor: catalogue ? undefined : mx?.parties,
    matrixState,
    error: matrixState === "failed" ? mxError?.error : undefined,
    buildError: catalogue ? undefined : mx?.buildError,
    issues: live ? (issuesState === "failed" ? undefined : iss?.issues) : published,
    issuesForKey: live && issuesState !== "failed" ? iss?.forKey : undefined,
    issuesSource: live ? "live" : published ? "published" : "none",
    issuesStale: live && iss?.full !== validKey,
    validating: live && validating,
    issuesState,
    issuesError: issuesState === "failed" ? issError?.error : undefined,
    savedOnly,
    maxRows: maxRows ?? undefined,
    refetch,
    validateNow,
  }
}
