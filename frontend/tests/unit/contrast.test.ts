// Contrast of the Pricing Workspace's state colours in the light and the dark theme (S16 review;
// PRICING_WORKSPACE_UX.md §3.3.3, §3.18, §3.19). The dark theme remaps only some shades (index.css
// and tex.css `.dark`): a shade it leaves alone keeps its light value on the dark backgrounds, so
// amber-950 text on the remapped amber-50 read at about 1.1:1. The palette is read from the CSS the
// app builds with (Tailwind's theme.css, then the app's @theme and .dark blocks), colours are
// converted (oklch or hex) to sRGB and compared by WCAG contrast. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { readdirSync, readFileSync } from "node:fs"
import { SELECTED, STALE, TONE } from "../../src/tex/screens/rates/workspace/cellTone.ts"

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8")
const TAILWIND = read("../../node_modules/tailwindcss/theme.css")
const APP = read("../../src/index.css")
const TEX = read("../../src/tex/tex.css")

/** The body of the first block that starts with `head` (braces balanced). */
function block(css: string, head: string): string {
  const at = css.indexOf(head)
  assert.ok(at >= 0, `no ${head} block`)
  let depth = 0
  const open = css.indexOf("{", at)
  for (let i = open; i < css.length; i++) {
    if (css[i] === "{") depth++
    else if (css[i] === "}" && --depth === 0) return css.slice(open + 1, i)
  }
  throw new Error(`unclosed ${head}`)
}

function colours(css: string): Map<string, string> {
  return new Map([...css.matchAll(/--color-([a-z]+(?:-[0-9]+)?):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]))
}

const LIGHT = new Map([...colours(TAILWIND), ...colours(block(APP, "@theme")), ...colours(block(TEX, "@theme"))])
const DARK_ONLY = new Map([...colours(block(APP, ".dark")), ...colours(block(TEX, ".dark"))])
const DARK = new Map([...LIGHT, ...DARK_ONLY])

type Rgb = [number, number, number] // linear sRGB, 0–1

function linear(c: number): number {
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

function parse(value: string): Rgb {
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value)
  if (hex) {
    const h = hex[1].length === 3 ? [...hex[1]].map((x) => x + x).join("") : hex[1]
    return [0, 2, 4].map((i) => linear(parseInt(h.slice(i, i + 2), 16) / 255)) as Rgb
  }
  const ok = /^oklch\(\s*([0-9.]+)%\s+([0-9.]+)\s+([0-9.]+)\s*\)$/.exec(value)
  assert.ok(ok, `cannot read the colour ${value}`)
  const [L, C, H] = [Number(ok[1]) / 100, Number(ok[2]), (Number(ok[3]) * Math.PI) / 180]
  const [a, b] = [C * Math.cos(H), C * Math.sin(H)]
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3
  const clamp = (x: number) => Math.min(1, Math.max(0, x))
  return [
    clamp(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    clamp(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    clamp(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ]
}

const luminance = ([r, g, b]: Rgb) => 0.2126 * r + 0.7152 * g + 0.0722 * b

function contrast(theme: Map<string, string>, fg: string, bg: string): number {
  const [x, y] = [fg, bg].map((name) => {
    const v = theme.get(name)
    assert.ok(v, `no colour ${name}`)
    return luminance(parse(v))
  })
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
}

const themes = [
  ["light", LIGHT],
  ["dark", DARK],
] as const

function assertContrast(fg: string, bg: string, min: number, what: string) {
  for (const [name, theme] of themes) {
    const c = contrast(theme, fg, bg)
    assert.ok(c >= min, `${what}: ${fg} on ${bg} is ${c.toFixed(2)}:1 in the ${name} theme (at least ${min}:1)`)
  }
}

test("the palette is read: known values in both themes", () => {
  assert.equal(LIGHT.get("white"), "#fff")
  assert.equal(DARK.get("white"), "#1c1c1f")
  assert.equal(DARK.get("amber-50"), "#3b2c0a")
  assert.ok(contrast(LIGHT, "black", "white") > 20.9)
  // the review's measurements: amber-950 on the remapped amber-50, slate-700 on the dark white
  assert.ok(contrast(DARK, "amber-950", "amber-50") < 1.3)
  assert.ok(contrast(DARK, "slate-700", "white") < 2)
})

test("every cell tone's text reads at 4.5:1 on its background, light and dark", () => {
  for (const [tone, classes] of Object.entries(TONE)) {
    const fg = /(?:^|\s)text-([a-z]+-[0-9]+|white)(?=\s|$)/.exec(classes)?.[1]
    const bg = /(?:^|\s)bg-([a-z]+-[0-9]+|white)(?=\s|$)/.exec(classes)?.[1] ?? "white"
    assert.ok(fg, `${tone} has a text colour`)
    assertContrast(fg, bg, 4.5, `tone ${tone}`)
  }
})

test("the workspace's other state texts and the selection outline", () => {
  assertContrast("amber-900", "amber-50", 4.5, "the Fill and Boards confirmation bars")
  assertContrast("tex-300", "zinc-900", 4.5, "the undo toast's Undo on the toast")
  assertContrast("zinc-700", "white", 4.5, "a formula-default cell")
  assertContrast("zinc-600", "white", 4.5, "the row header's derivation")
  assertContrast("amber-800", "white", 4.5, "the combination builder's no-host warning")
  assertContrast("zinc-500", "white", 4.5, "the price test ladder's before amounts")
  const outline = /aria-selected:outline-([a-z]+-[0-9]+)/.exec(SELECTED)?.[1]
  assert.ok(outline, "a selected cell has an outline, not only a tint")
  assertContrast(outline, "white", 3, "the selection outline on a cell")
  assertContrast(outline, "sky-50", 3, "the selection outline on the selection tint")
  assertContrast(outline, "amber-50", 3, "the selection outline on an override cell")
})

test("a stale resolved value reads at 4.5:1: a muted ink, not dimmed (S16 re-review)", () => {
  // opacity-55 over zinc-800 on zinc-50 composited to about 3.4:1, and "updating" could last
  assert.ok(!/opacity/.test(STALE), "a stale cell is not dimmed with opacity")
  const fg = /(?:^|\s)text-([a-z]+-[0-9]+)!?(?=\s|$)/.exec(STALE)?.[1]
  assert.ok(fg, "a stale cell has its own text colour")
  const bg = /(?:^|\s)bg-([a-z]+-[0-9]+)(?=\s|$)/.exec(TONE.resolved)?.[1] ?? "white"
  assertContrast(fg, bg, 4.5, "a stale resolved cell")
})

// a text or background shade the dark theme does not remap keeps its light value there
const REMAPPED = new Set([...DARK_ONLY.keys()])
const NEUTRAL = new Set(["white", "black", "transparent", "current", "inherit"])

function* sources(dir: URL): Generator<[string, string]> {
  for (const d of readdirSync(dir, { withFileTypes: true })) {
    if (d.isFile() && /\.(ts|tsx)$/.test(d.name)) yield [d.name, readFileSync(new URL(d.name, dir), "utf8")]
  }
}

test("workspace text and background colours use only shades the dark theme remaps", () => {
  const bad: string[] = []
  for (const [file, text] of sources(new URL("../../src/tex/screens/rates/workspace/", import.meta.url))) {
    for (const m of text.matchAll(/(?<![\w-])(?:[a-z-]+:)*(text|bg)-([a-z]+)-([0-9]{2,3})(?:\/[0-9]+)?(?![\w-])/g)) {
      const shade = `${m[2]}-${m[3]}`
      if (NEUTRAL.has(m[2]) || REMAPPED.has(shade)) continue
      bad.push(`${file}: ${m[0]}`)
    }
  }
  assert.deepEqual(bad, [])
})
