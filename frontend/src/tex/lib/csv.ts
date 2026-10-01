// One CSV cell for every TEX export: a free-text cell that starts like a spreadsheet formula gets a leading
// quote (formula injection), but an international phone number is not a formula and is exported as it is
// (O-33): the SMS / WhatsApp export gave "'+905321234567".

/** "+", a digit, then digits, plain spaces, brackets, dots and hyphens: no tab, letter, `|`, `!` or `=` a formula could use. */
const PHONE = /^\+\d[\d ().-]*$/

/** Quote a CSV cell. ``text``: a free-text cell, whose formula starts (`= + - @`, a tab or a return) are neutralised. */
export function csvCell(v: unknown, text = true): string {
  let s = v === null || v === undefined ? "" : String(v)
  if (text && /^[=+\-@\t\r]/.test(s) && !PHONE.test(s)) s = `'${s}`
  return /[",\n\r;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}
