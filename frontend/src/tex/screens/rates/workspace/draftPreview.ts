// The live draft preview's request policy (PRICING_WORKSPACE_UX.md §3.14, slice S8): which calls a
// viewer makes, how long they wait, and that at most one validation is in flight. The React
// binding is useDraftPreview.ts. Pure: no runtime imports (only erasable types), so node --test
// runs it.
//
// Modes, chosen from the server's own flags so that no viewer calls an endpoint it would refuse:
// - overlay (`doc.editable`: a Draft and contract.edit): price_matrix and validate_version are
//   POSTed with the unsaved payload (the read-only overlay, GAP-1);
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

export interface PreviewInput {
  version: string
  /** the overlay payload (overlayPayloadOf(state)); sent in overlay mode only */
  data?: unknown
  /** GAP-2b sample parties of the occupancy ladder (S11), priced in `partyRoom` */
  parties?: SampleParty[]
  partyRoom?: string
}

export interface PreviewRequest {
  args: Record<string, unknown>
  post: boolean
}

/** contracts.price_matrix for this mode, or null when the viewer makes no call. */
export function matrixRequest(mode: PreviewMode, p: PreviewInput): PreviewRequest | null {
  if (mode === "catalogue") return null
  const args: Record<string, unknown> = { version: p.version }
  if (mode === "overlay") args.data = p.data
  if (p.parties && p.parties.length > 0 && p.partyRoom) {
    args.parties = p.parties
    args.party_room = p.partyRoom
  }
  return { args, post: mode === "overlay" }
}

/** contracts.validate_version with the unsaved payload, overlay mode only. */
export function validationRequest(mode: PreviewMode, p: PreviewInput): PreviewRequest | null {
  if (mode !== "overlay") return null
  return { args: { name: p.version, data: p.data }, post: true }
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
