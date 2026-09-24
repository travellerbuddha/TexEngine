// Harness page for tests/dom/overlays.spec.ts (and a manual keyboard check): the real Popover,
// Menu, Tooltip, Drawer and grid hooks with the app's styles, sized to overflow a short viewport.
import { StrictMode, useRef, useState } from "react"
import { createRoot } from "react-dom/client"
import "../../src/index.css"
import { Drawer, Menu, MenuItem, Popover, Tooltip, useGridNavigation, useGridSelection } from "../../src/tex/ui"

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
