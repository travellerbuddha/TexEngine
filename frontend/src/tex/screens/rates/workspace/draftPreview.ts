// The live draft preview's request policy (PRICING_WORKSPACE_UX.md §3.14, slice S8): which calls a
// viewer makes, how long they wait, and that at most one validation is in flight. The React
// binding is useDraftPreview.ts. Pure: no runtime imports (only erasable types), so node --test
// runs it.
//
// Modes, chosen from the server's own flags so that no viewer calls an endpoint it would refuse:
// - overlay (`doc.editable`: a Draft and contract.edit): price_matrix and validate_version are
//   POSTed with the unsaved payload (the read-only overlay, GAP-1). They ask for the saved draft
//   by name instead, with no payload and so no row cap (§3.15, `previewSource`), when what is on
//   screen is the saved draft, for the Check button, and when the overlay would not take the draft
//   (more rows than `overlay_max_rows`, or the server refused it as `OverlayTooLarge`);
// - saved (not editable, cost visible): price_matrix of the saved version by GET, never
//   validate_version (it needs contract.edit); the issues are the report stored at publish;
// - catalogue (`doc.cost_hidden`, agents): no call at all.
import type { Issue, SampleParty } from "../lib/types.ts"

export type PreviewMode = "overlay" | "saved" | "catalogue"

export function previewMode(doc: { editable?: boolean; cost_hidden?: boolean }): PreviewMode {
  if (doc.cost_hidden) return "catalogue"
  return doc.editable ? "overlay" : "saved"
}

/** Resolved prices follow an edit after this pause (the matrix answers in 0.2–0.7 s, ADR-061). */
export const MATRIX_DEBOUNCE_MS = 300
/** Validation waits at least this long after the last edit… */
export const VALIDATE_DEBOUNCE_MS = 1200
/** …and as long as the previous validation took, up to this: a validation costs about 2 s on a
 * realistic contract and 10 s near the overlay's row cap (ADR-061), and the server has no guard
 * against a queue of them. */
export const VALIDATE_DEBOUNCE_MAX_MS = 10_000

export function validateDelay(lastMs: number | null | undefined): number {
  if (typeof lastMs !== "number" || !(lastMs > VALIDATE_DEBOUNCE_MS)) return VALIDATE_DEBOUNCE_MS
  return Math.min(Math.round(lastMs), VALIDATE_DEBOUNCE_MAX_MS)
}

/** Where an answer comes from: the state on screen through the overlay (its payload POSTed), or
 * the saved draft asked for by name (no payload, no row cap). */
export type PreviewSource = "overlay" | "saved"

/** The server's refusal of an overlay above its row cap (`api/contracts.py` OverlayTooLarge), as
 * the client sees it (`TexApiError.type`). */
export const OVERLAY_TOO_LARGE = "OverlayTooLarge"

/** Whether `e` is the overlay's row-cap refusal (not any other refusal, such as a blank value). */
export function isTooLarge(e: unknown): boolean {
  return Boolean(e && typeof e === "object" && (e as { type?: unknown }).type === OVERLAY_TOO_LARGE)
}

/** The rows a payload of these tables carries, over all of them: what the overlay counts against
 * its cap (an integer count, §3.14 (f)). */
export function overlayRows(tables: Readonly<Record<string, readonly unknown[] | undefined>>): number {
  let n = 0
  for (const rows of Object.values(tables)) n += rows?.length ?? 0
  return n
}

export interface SourceInput {
  /** the state on screen is the saved draft (its fingerprint is the save base) */
  clean: boolean
  /** overlayRows of the state on screen */
  rows: number
  /** the most rows the overlay takes, as the server reports it (get_version `overlay_max_rows`) */
  maxRows?: number | null
  /** the row count of a state the server refused as too large (OverlayTooLarge) */
  refusedRows?: number | null
  /** the Check button asked: it validates the saved draft (§3.15) */
  now?: boolean
}

/** Whether the overlay takes a state of `rows` rows: not above the cap the server reports, and not
 * as large as a state it refused. Without either, the server decides. */
export function overlayFits(p: Pick<SourceInput, "rows" | "maxRows" | "refusedRows">): boolean {
  if (typeof p.maxRows === "number" && p.rows > p.maxRows) return false
  if (typeof p.refusedRows === "number" && p.rows >= p.refusedRows) return false
  return true
}

/** Where an answer is asked from, or null when the viewer asks nothing. In overlay mode the saved
 * draft is asked for by name when it is what the screen shows (`clean`: the same answer, with no
 * payload to send and no row cap), for the Check button (`now`, §3.15: "the Validate button still
 * validates the saved draft") and when the overlay does not take the draft (`overlayFits`). */
export function previewSource(mode: PreviewMode, p: SourceInput): PreviewSource | null {
  if (mode === "catalogue") return null
  if (mode === "saved" || p.clean || p.now || !overlayFits(p)) return "saved"
  return "overlay"
}

export interface KeyInput {
  version: string
  /** the saved draft's revision (`doc.modified`) */
  modified: string
  /** refresh counters: `refetch` (both answers) and `validateNow` (the validation) */
  tick: number
  vtick: number
  /** the sample parties asked for (their JSON), "" for none */
  parties: string
  /** the rows' client keys: the rule ids of an overlay answer are "~" + _key */
  rowKeys: string
  /** the fingerprint of the state on screen */
  key: string
  /** the overlay takes the state on screen (overlayFits) */
  fits: boolean
}

const SEP = "\u0001"

/**
 * What each answer depends on (a new one is asked exactly when its key changes); "" asks nothing.
 * - overlay mode, a draft the overlay takes: the content on screen (fingerprint and row keys),
 *   however it is asked; a save of what is on screen (a new revision, same content, keys kept)
 *   keeps the answers, and the validation also follows the Check button (vtick);
 * - overlay mode above the cap, and saved mode: the saved draft's revision, whatever the screen
 *   shows; edits ask nothing, a save asks again. Saved mode never validates.
 */
export function previewKeys(mode: PreviewMode, p: KeyInput): { matrix: string; valid: string } {
  if (mode === "catalogue") return { matrix: "", valid: "" }
  const saved = [p.version, "saved", p.modified, p.tick, p.parties].join(SEP)
  if (mode === "saved") return { matrix: saved, valid: "" }
  if (!p.fits) return { matrix: saved, valid: [p.version, "saved", p.modified, p.tick, p.vtick].join(SEP) }
  return {
    matrix: [p.version, "draft", p.tick, p.parties, p.rowKeys, p.key].join(SEP),
    valid: [p.version, "draft", p.tick, p.vtick, p.rowKeys, p.key].join(SEP),
  }
}

export interface PreviewInput {
  version: string
  /** the overlay payload (overlayPayloadOf(state)); sent in overlay mode only */
  data?: unknown
  /** GAP-2b sample parties of the occupancy ladder (S11), priced in `partyRoom` */
  parties?: SampleParty[]
  partyRoom?: string
  /** previewSource: "saved" asks for the saved draft by name (overlay mode's default is the overlay) */
  source?: PreviewSource
  /** the rooms of the saved draft (doc.rooms): an answer about the saved draft prices the sample
   * parties only in one of them (price_matrix refuses a party room that is not a contract room) */
  savedRooms?: readonly string[]
}

export interface PreviewRequest {
  args: Record<string, unknown>
  post: boolean
}

/** contracts.price_matrix for this mode, or null when the viewer makes no call: a POST with the
 * payload through the overlay, else a GET of the saved draft. */
export function matrixRequest(mode: PreviewMode, p: PreviewInput): PreviewRequest | null {
  if (mode === "catalogue") return null
  const overlay = mode === "overlay" && p.source !== "saved"
  const args: Record<string, unknown> = { version: p.version }
  if (overlay) args.data = p.data
  const roomKnown = overlay || !p.savedRooms || p.savedRooms.includes(p.partyRoom ?? "")
  if (p.parties && p.parties.length > 0 && p.partyRoom && roomKnown) {
    args.parties = p.parties
    args.party_room = p.partyRoom
  }
  return { args, post: overlay }
}

/** contracts.validate_version, overlay mode only (an editor): a POST with the unsaved payload, or
 * the saved draft by name (a GET, as the Check button asked before the overlay). */
export function validationRequest(mode: PreviewMode, p: PreviewInput): PreviewRequest | null {
  if (mode !== "overlay") return null
  if (p.source === "saved") return { args: { name: p.version }, post: false }
  return { args: { name: p.version, data: p.data }, post: true }
}

/** What a preview answer's call is doing, from the keys alone:
 * - busy: a call is in flight, or the answer wanted has not been asked for yet (the debounce);
 * - failed: the call for the answer wanted failed (nothing retries until the key changes);
 * - ready: the answer wanted is there, or nothing is asked. */
export type CallState = "ready" | "busy" | "failed"

export interface CallInput {
  /** the key of the answer wanted now ("" when nothing is asked) */
  key: string
  /** the key of the last answer received */
  answered?: string
  /** the key of the last call that failed */
  failed?: string
  /** a call is in flight */
  running: boolean
}

export function callState(p: CallInput): CallState {
  if (!p.key) return "ready"
  if (p.running) return "busy"
  if (p.failed === p.key) return "failed"
  return p.answered === p.key ? "ready" : "busy"
}

const isIssue = (x: unknown): x is Issue => {
  if (!x || typeof x !== "object") return false
  const i = x as Record<string, unknown>
  return typeof i.level === "string" && typeof i.code === "string" && typeof i.message === "string"
}

/**
 * The issues a version stored when it was published (`validation_report`): the server stores the
 * list of issues; an object with `issues` is read too. Undefined when there is no report.
 */
export function storedIssues(report: unknown): Issue[] | undefined {
  const list = Array.isArray(report) ? report : report && typeof report === "object" ? (report as { issues?: unknown }).issues : undefined
  return Array.isArray(list) ? list.filter(isIssue) : undefined
}

/** Whether the live check of the state `key` can be skipped: it is the last one answered
 * (`answered`), and no check is in flight (one for another state would replace that answer when it
 * ends, so `key` is asked again after it). */
export function alreadyChecked(key: string, answered: string | null | undefined, busy: boolean): boolean {
  return key === answered && !busy
}

export interface FlightJob {
  /** what the job checks (the state's fingerprint plus the version and a refresh counter) */
  key: string
}

export interface LatestOnly<J extends FlightJob> {
  /** Run `job` now when nothing runs; otherwise it waits, replacing any job already waiting.
   * Asking for the running job's key again leaves nothing waiting. */
  want(job: J): void
  /** Abort the running job and drop the waiting one (the editor left, or the mode changed). */
  cancel(): void
  busy(): boolean
  waiting(): string | null
}

/**
 * At most one job in flight, and only the newest waiting: each validation costs the server seconds
 * (ADR-061), so a new one is not started while one runs, and edits made meanwhile are checked
 * once, after it. A failed job frees the flight like a finished one.
 */
export function latestOnly<J extends FlightJob>(run: (job: J, signal: AbortSignal) => Promise<unknown>): LatestOnly<J> {
  let running: { job: J; ctl: AbortController } | null = null
  let pending: J | null = null

  const start = (job: J) => {
    const flight = { job, ctl: new AbortController() }
    running = flight
    const done = () => {
      if (running !== flight) return // cancelled meanwhile: whatever runs now is not this one
      running = null
      const next = pending
      pending = null
      if (next) start(next)
    }
    let p: Promise<unknown>
    try {
      p = run(job, flight.ctl.signal)
    } catch (e) {
      p = Promise.reject(e)
    }
    p.then(done, done)
  }

  return {
    want(job) {
      if (!running) return start(job)
      pending = job.key === running.job.key ? null : job
    },
    cancel() {
      pending = null
      if (running) {
        running.ctl.abort()
        running = null
      }
    },
    busy: () => running !== null,
    waiting: () => (pending ? pending.key : null),
  }
}
