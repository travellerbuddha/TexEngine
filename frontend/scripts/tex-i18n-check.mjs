// TEX i18n completeness (R-49): every key of every area exists in all six
// languages, plural entries carry an "other" form, and placeholders match English.
// Also (PRICING_WORKSPACE_UX.md §3.20, slice S15): every key used as a string literal in
// src/tex (t("…"), t('…'), tOrdinal("…"); not template literals, which build keys at run time)
// must exist in the English catalogue of its area (the area whose keys share its first segment).
// And (§3.20, S16 review): a Pricing Workspace string with a {count} is a plural object
// (one/few/many/other), never a plain string ("1 adults", "1 взрослых").
import { readdirSync, readFileSync, existsSync } from "node:fs"
import { join, relative } from "node:path"

const LANGS = ["en", "tr", "de", "ru", "ro", "pl"]
const roots = [["admin", "src/tex/i18n/locales"], ["booking", "src/booking/i18n/locales"]]
let problems = 0
// the Pricing Workspace's namespaces (§3.20; the boards' keys are rates.brd.*)
const WORKSPACE_KEYS = ["rates.section.", "rates.ws.", "rates.sh.", "rates.occ.", "rates.combo.", "rates.bands.", "rates.brd.", "rates.boards.", "rates.pt.", "rates.kbd.", "rates.explain."]
const placeholders = (v) => {
  const s = typeof v === "string" ? v : Object.values(v ?? {}).join(" ")
  return [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(",")
}
for (const [label, root] of roots) {
  if (!existsSync(root)) continue
  const areas = readdirSync(root, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name)
  const flat = areas.length ? areas : ["."]
  for (const area of flat) {
    const dir = join(root, area)
    const load = (l) => {
      const f = join(dir, `${l}.json`)
      if (!existsSync(f)) {
        console.error(`✗ ${label}/${area}: missing ${l}.json`)
        problems++
        return {}
      }
      return JSON.parse(readFileSync(f, "utf8"))
    }
    const en = load("en")
    if (label === "admin" && area === "rates") {
      for (const [k, v] of Object.entries(en)) {
        if (typeof v === "string" && v.includes("{count}") && WORKSPACE_KEYS.some((ns) => k.startsWith(ns))) {
          console.error(`✗ ${label}/${area}/en: "${k}" has a {count} but is not a plural object (one/…/other)`)
          problems++
        }
      }
    }
    for (const l of LANGS.slice(1)) {
      const cat = load(l)
      for (const [k, v] of Object.entries(en)) {
        if (!(k in cat)) {
          console.error(`✗ ${label}/${area}/${l}: missing "${k}"`)
          problems++
        } else if (typeof cat[k] === "object" && !cat[k].other) {
          console.error(`✗ ${label}/${area}/${l}: plural "${k}" has no "other"`)
          problems++
        } else if (placeholders(cat[k]) !== placeholders(v) && !(typeof v === "object")) {
          console.error(`✗ ${label}/${area}/${l}: placeholders differ in "${k}"`)
          problems++
        }
      }
      for (const k of Object.keys(cat)) if (!(k in en)) console.warn(`! ${label}/${area}/${l}: extra key "${k}"`)
    }
  }
}
// ─── literal keys used in the code ─────────────────────────────────────────
const ADMIN_ROOT = "src/tex/i18n/locales"
const english = new Map() // area → Set of its English keys
const areaOf = new Map() // first key segment ("rates", "core", …) → areas whose keys use it
if (existsSync(ADMIN_ROOT)) {
  for (const d of readdirSync(ADMIN_ROOT, { withFileTypes: true })) {
    if (!d.isDirectory()) continue
    const f = join(ADMIN_ROOT, d.name, "en.json")
    if (!existsSync(f)) continue
    const keys = new Set(Object.keys(JSON.parse(readFileSync(f, "utf8"))))
    english.set(d.name, keys)
    for (const k of keys) {
      const head = k.split(".")[0]
      if (!areaOf.has(head)) areaOf.set(head, new Set())
      areaOf.get(head).add(d.name)
    }
  }
}
function* sources(dir) {
  for (const d of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, d.name)
    if (d.isDirectory()) {
      if (d.name !== "node_modules") yield* sources(p)
    } else if (/\.(ts|tsx)$/.test(d.name) && !/\.d\.ts$/.test(d.name)) yield p
  }
}
// t("key" …) / t('key' …) / tOrdinal("key" …) (i18n.t too): nothing word-like before the name (not .at( or format()),
// and the literal must end the argument (a "rates." + x concatenation builds a key at run time)
const LITERAL = /(?<![\w$])(?:t|tOrdinal)\(\s*(["'])([A-Za-z0-9_.\-]+)\1\s*[,)]/g
// and t(cond ? "key.a" : "key.b" …): both keys of a conditional argument (S16 re-review 3: keys such
// as rates.ws.bulk.matrix_only_ro and rates.occ.sum.single_any were built this way, out of the scan)
const TERNARY = /(?<![\w$])(?:t|tOrdinal)\(\s*[^()"'`,;]*?\?\s*(["'])([A-Za-z0-9_.\-]+)\1\s*:\s*(["'])([A-Za-z0-9_.\-]+)\3\s*[,)]/g
let used = 0
if (existsSync("src/tex")) {
  for (const file of sources("src/tex")) {
    const text = readFileSync(file, "utf8")
    const found = [...text.matchAll(LITERAL)].map((m) => ({ key: m[2], index: m.index }))
    for (const m of text.matchAll(TERNARY)) found.push({ key: m[2], index: m.index }, { key: m[4], index: m.index })
    for (const { key, index } of found) {
      if (!key.includes(".")) continue // not a catalogue key (e.g. a one-word helper argument)
      used++
      const areas = areaOf.get(key.split(".")[0])
      if (areas && [...areas].some((a) => english.get(a).has(key))) continue
      const line = text.slice(0, index).split("\n").length
      const where = areas ? [...areas].map((a) => `${a}/en.json`).join(" or ") : "any area's en.json (no area has this prefix)"
      console.error(`✗ ${relative(".", file)}:${line}: t("${key}") is missing from ${where}`)
      problems++
    }
  }
}

if (problems) {
  console.error(`\n${problems} i18n problem(s)`)
  process.exit(1)
}
console.log(`Literal keys in src/tex: ${used} found in their area's en.json`)
console.log("TEX i18n catalogs complete for", LANGS.join(", "))
