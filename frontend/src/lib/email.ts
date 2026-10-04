// A guest's e-mail address as the server keeps it (`kamra.tex.services.booking.plain_email`, batch 2P, ADR-080): one
// plain address in ASCII, trimmed and in lower case, Frappe's address pattern matched whole, at most 140 characters.
// The booking app, the call centre and the CRM check it before sending, so the server's refusal is never the first
// word (2P review rounds 1 and 2). Pure: no DOM, no React.

// frappe.utils.EMAIL_MATCH_PATTERN (Frappe v16.36.1), anchored at both ends
const PATTERN =
  /^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*@(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/

// what Python's str.strip() takes off the ends (str.isspace), which JavaScript's trim() is not: trim() also takes a
// BOM (U+FEFF) and leaves the information separators (U+001C–U+001F) and NEL (U+0085) (review round 2)
const PY_SPACE = new Set([
  0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680,
  0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a,
  0x2028, 0x2029, 0x202f, 0x205f, 0x3000,
])

function pyStrip(raw: string): string {
  const chars = [...raw]
  let start = 0
  let end = chars.length
  while (start < end && PY_SPACE.has(chars[start].codePointAt(0) ?? 0)) start++
  while (end > start && PY_SPACE.has(chars[end - 1].codePointAt(0) ?? 0)) end--
  return chars.slice(start, end).join("")
}

/** The address, trimmed and in lower case, or null when it is not one plain ASCII address. ASCII is checked before
 *  lower case: a KELVIN SIGN (U+212A) lower-cases to an ASCII k. */
export function plainEmail(raw: string | null | undefined): string | null {
  const value = pyStrip(raw ?? "")
  if ([...value].some((c) => (c.codePointAt(0) ?? 0) > 0x7f)) return null
  const email = value.toLowerCase()
  return email.length <= 140 && PATTERN.test(email) ? email : null
}

/** An address typed into a profile that the server would refuse: only one changed from the stored one (the server
 *  checks only an address that is sent; a profile made elsewhere may keep one that is not plain), and not cleared. */
export function editedEmailInvalid(value: string | null | undefined, stored: string | null | undefined): boolean {
  const typed = pyStrip(value ?? "")
  return Boolean(typed) && typed !== pyStrip(stored ?? "") && plainEmail(typed) === null
}
