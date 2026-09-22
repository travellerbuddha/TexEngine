// Compile-time guard (tsc -b): every guest catalog has exactly the English keys,
// and plural entries carry the categories their language needs. Nothing imports
// this file, so it is never part of the booking bundle.
import de from "./de.json"
import en from "./en.json"
import pl from "./pl.json"
import ro from "./ro.json"
import ru from "./ru.json"
import tr from "./tr.json"

type Keys = keyof typeof en
type SameKeys<T> = [Exclude<Keys, keyof T>, Exclude<keyof T, Keys>] extends [never, never] ? true : false

/** Keys whose English value is a plural object. */
type PluralKeys = { [K in Keys]: (typeof en)[K] extends string ? never : K }[Keys]
type HasForms<T, Forms extends string> = {
  [K in PluralKeys & keyof T]: T[K] extends Record<Forms | "other", string> ? true : K
}[PluralKeys & keyof T]

export const catalogKeysMatch: [SameKeys<typeof tr>, SameKeys<typeof de>, SameKeys<typeof ru>, SameKeys<typeof ro>, SameKeys<typeof pl>] = [
  true,
  true,
  true,
  true,
  true,
]

// Intl.PluralRules categories used for counts: en/tr/de one+other, ro one+few+other, ru/pl one+few+many+other
export const pluralFormsComplete: [
  HasForms<typeof en, "one">,
  HasForms<typeof tr, "one">,
  HasForms<typeof de, "one">,
  HasForms<typeof ro, "one" | "few">,
  HasForms<typeof ru, "one" | "few" | "many">,
  HasForms<typeof pl, "one" | "few" | "many">,
] = [true, true, true, true, true, true]
