// Source module names stay distinct on every disk. Windows and macOS disks ignore letter case: two
// modules in one folder whose names differ only in case or extension (ExplainLadder.tsx beside
// explainLadder.ts) make an import without an extension load the wrong one there ("does not provide
// an export named …" in `npm run dev`, a failed `npm run build`), while Linux and CI resolve it.
// Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { readdirSync } from "node:fs"
import { join, relative } from "node:path"
import { fileURLToPath } from "node:url"

const ROOT = fileURLToPath(new URL("../..", import.meta.url))
const MODULE = /\.(ts|tsx|js|jsx|mjs|mts|cjs|cts|json)$/

function* files(dir: string): Generator<string> {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name.startsWith(".")) continue
    const p = join(dir, e.name)
    if (e.isDirectory()) yield* files(p)
    else yield p
  }
}

test("no two modules in a folder differ only in letter case or extension", () => {
  const groups = new Map<string, string[]>()
  for (const top of ["src", "e2e", "tests"]) {
    for (const f of files(join(ROOT, top))) {
      if (!MODULE.test(f)) continue
      const key = relative(ROOT, f).replace(MODULE, "").toLowerCase()
      groups.set(key, [...(groups.get(key) ?? []), relative(ROOT, f)])
    }
  }
  const clashes = [...groups.values()].filter((g) => g.length > 1)
  assert.deepEqual(clashes, [], `rename one of each: ${clashes.map((g) => g.join(" / ")).join("; ")}`)
})

test("no two files or folders anywhere differ only in letter case", () => {
  const seen = new Map<string, string>()
  const clashes: string[] = []
  for (const top of ["src", "e2e", "tests", "public"]) {
    for (const f of files(join(ROOT, top))) {
      const rel = relative(ROOT, f)
      const prev = seen.get(rel.toLowerCase())
      if (prev && prev !== rel) clashes.push(`${prev} / ${rel}`)
      else seen.set(rel.toLowerCase(), rel)
    }
  }
  assert.deepEqual(clashes, [])
})
