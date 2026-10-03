// Harness page for tests/dom/overlays.spec.ts (and a manual keyboard check): the real Popover,
// Menu, Tooltip, Drawer and grid hooks with the app's styles, sized to overflow a short viewport.
import { StrictMode, useEffect, useLayoutEffect, useRef, useState } from "react"
import { createRoot } from "react-dom/client"
import "./harness.css"
import { Dialog, Drawer, Menu, MenuItem, Popover, Tooltip, useGridNavigation, useGridSelection } from "../../src/tex/ui"

const ITEMS = Array.from({ length: 50 }, (_, i) => `Item ${i}`)
const FIELDS = Array.from({ length: 40 }, (_, i) => `f${i}`)

function Field({ name }: { name: string }) {
  return (
    <label className="mb-2 block text-xs text-zinc-600">
      {name}
      <input aria-label={name} className="mt-0.5 block w-full rounded border border-zinc-300 px-2 py-1 text-sm" />
    </label>
  )
}

function TallPopover() {
  const [open, setOpen] = useState(false)
  const anchor = useRef<HTMLButtonElement>(null)
  return (
    <>
      <button ref={anchor} type="button" className="rounded border px-2 py-1" onClick={() => setOpen((o) => !o)}>
        Open form
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchorRef={anchor} label="Tall form" width="md">
        {FIELDS.map((f) => (
          <Field key={f} name={f} />
        ))}
      </Popover>
    </>
  )
}

function SmallPopover({ id, fields }: { id: string; fields: string[] }) {
  const [open, setOpen] = useState(false)
  const anchor = useRef<HTMLButtonElement>(null)
  return (
    <>
      <button ref={anchor} type="button" className="rounded border px-2 py-1" onClick={() => setOpen((o) => !o)}>
        {`Open ${id}`}
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchorRef={anchor} label={`Popover ${id}`} width="sm">
        {fields.map((f) => (
          <Field key={f} name={f} />
        ))}
      </Popover>
    </>
  )
}

function DrawerCase() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" className="rounded border px-2 py-1" onClick={() => setOpen(true)}>
        Open drawer
      </button>
      <Drawer open={open} onClose={() => setOpen(false)} title="Drawer title">
        <div className="flex flex-wrap gap-2">
          <Tooltip content="Tip text">
            <button type="button" className="rounded border px-2 py-1">
              Tip target
            </button>
          </Tooltip>
          <SmallPopover id="drawer popover" fields={["d1", "d2"]} />
          <button type="button" className="rounded border px-2 py-1">
            Drawer after
          </button>
          {/* the Drawer's last Tab stop */}
          <SmallPopover id="drawer last" fields={["e1", "e2"]} />
        </div>
      </Drawer>
    </>
  )
}

/** A non-modal Drawer (a side panel, PRICING_WORKSPACE_UX.md §3.8): the page stays usable. */
function SidePanelCase() {
  const [open, setOpen] = useState(false)
  const [clicks, setClicks] = useState(0)
  return (
    <>
      <button type="button" className="rounded border px-2 py-1" onClick={() => setOpen(true)}>
        Open side panel
      </button>
      <button type="button" className="rounded border px-2 py-1" onClick={() => setClicks((n) => n + 1)}>
        Page button
      </button>
      <output data-testid="page-clicks">{clicks}</output>
      <Drawer open={open} onClose={() => setOpen(false)} title="Side panel title" modal={false}>
        <Field name="p1" />
        <SmallPopover id="panel popover" fields={["q1", "q2"]} />
      </Drawer>
    </>
  )
}

/** What each overlay's content showed, commit by commit (read by the spec through `window.__commits`). */
const commits: Record<string, string[]> = {}
;(window as unknown as { __commits: typeof commits }).__commits = commits

/** Records the value of every commit in which it can be seen (a frame paints only what was committed, and
 * nothing under `visibility: hidden`); a hidden commit is recorded as "(hidden)". */
function Probe({ id, value, shownBy }: { id: string; value: string; shownBy: unknown }) {
  const input = useRef<HTMLInputElement>(null)
  useLayoutEffect(() => {
    const seen = input.current && getComputedStyle(input.current).visibility === "visible"
    ;(commits[id] ??= []).push(seen ? value : "(hidden)")
  }, [id, value, shownBy])
  return <input ref={input} aria-label={`${id} amount`} value={value} readOnly className="rounded border px-2 py-1" />
}

/**
 * A form kept mounted while its overlay is closed and reset by a passive effect when it opens: the
 * pattern of about thirty TEX dialogs (ADR-073). The overlay's content must never be committed with the
 * last session's value, or its first frame shows it and what is typed then is lost.
 */
function ResetCase({ kind }: { kind: "dialog" | "drawer" | "panel" }) {
  const [open, setOpen] = useState(false)
  const [round, setRound] = useState(0)
  const [value, setValue] = useState("last session")
  useEffect(() => {
    if (open) setValue(`fresh ${round}`)
  }, [open, round])
  // re-renders the content in the pass after it opens, so the Probe sees a commit that only shows it
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (open) setTick((n) => n + 1)
  }, [open])
  const close = () => {
    setOpen(false)
    setValue("last session")                   // what was typed before closing, kept while closed
  }
  const body = (
    <>
      <Probe id={kind} value={value} shownBy={tick} />
      <button type="button" className="rounded border px-2 py-1" onClick={close}>
        {`Done ${kind}`}
      </button>
    </>
  )
  return (
    <>
      <button
        type="button"
        className="rounded border px-2 py-1"
        onClick={() => {
          setRound((r) => r + 1)
          setOpen(true)
        }}
      >
        {`Open reset ${kind}`}
      </button>
      {kind === "dialog" ? (
        <Dialog open={open} onClose={close} title="Reset dialog">
          {body}
        </Dialog>
      ) : (
        <Drawer open={open} onClose={close} title={`Reset ${kind}`} modal={kind === "drawer"}>
          {body}
        </Drawer>
      )}
    </>
  )
}

function Grid() {
  const selection = useGridSelection({ rows: 3, cols: 3 })
  const nav = useGridNavigation({ rows: 3, cols: 3, selection })
  return (
    <div className="flex items-center gap-4">
      <table role="grid" aria-label="Grid" aria-multiselectable ref={nav.gridRef}>
        <tbody>
          {[0, 1, 2].map((r) => (
            <tr key={r}>
              {[0, 1, 2].map((c) => (
                <td key={c} role="gridcell" className="border px-2 aria-selected:bg-zinc-100" {...nav.cellProps(r, c)}>
                  {`${r}:${c}`}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <output data-testid="grid-selected">{selection.selected.length}</output>
    </div>
  )
}

function Harness() {
  return (
    <div className="tex-root p-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="rounded border px-2 py-1">
          Before
        </button>
        <Menu label="Big menu" text="Big menu">
          {ITEMS.map((i) => (
            <MenuItem key={i}>{i}</MenuItem>
          ))}
        </Menu>
        <TallPopover />
        <button type="button" className="rounded border px-2 py-1">
          After form
        </button>
        <SmallPopover id="small" fields={["s1", "s2"]} />
        <button type="button" className="rounded border px-2 py-1">
          After small
        </button>
        <DrawerCase />
      </div>
      <div className="mt-2">
        <Grid />
      </div>
      {/* on the left: the side panel covers the right of the page */}
      <div className="mt-2 flex items-center gap-2">
        <SidePanelCase />
      </div>
      <div className="mt-2 flex items-center gap-2">
        <ResetCase kind="dialog" />
        <ResetCase kind="drawer" />
        <ResetCase kind="panel" />
      </div>
      {/* the page scrolls too */}
      <div style={{ height: 2000 }} />
    </div>
  )
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Harness />
  </StrictMode>,
)
