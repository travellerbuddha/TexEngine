// TEX i18n completeness (R-49): every key of every area exists in all six
// languages, plural entries carry an "other" form, and placeholders match English.
import { readdirSync, readFileSync, existsSync } from "node:fs"
import { join } from "node:path"

const LANGS = ["en", "tr", "de", "ru", "ro", "pl"]
const roots = [["admin", "src/tex/i18n/locales"], ["booking", "src/booking/i18n/locales"]]
let problems = 0
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
if (problems) {
  console.error(`\n${problems} i18n problem(s)`)
  process.exit(1)
}
console.log("TEX i18n catalogs complete for", LANGS.join(", "))
