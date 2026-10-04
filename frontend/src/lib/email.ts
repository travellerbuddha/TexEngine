// A guest's e-mail address as the server keeps it (`kamra.tex.services.booking.plain_email`, batch 2P, ADR-080): one
// plain address in ASCII, trimmed and in lower case, Frappe's address pattern matched whole, at most 140 characters.
// The booking app and the CRM check it before sending, so the server's refusal is never the first word (2P review
// round 1). Pure: no DOM, no React.

// frappe.utils.EMAIL_MATCH_PATTERN (Frappe v16.36.1), anchored at both ends
const PATTERN =
  /^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*@(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/

/** The address, trimmed and in lower case, or null when it is not one plain ASCII address. ASCII is checked before
 *  lower case: a KELVIN SIGN (U+212A) lower-cases to an ASCII k. */
export function plainEmail(raw: string | null | undefined): string | null {
  const value = (raw ?? "").trim()
  if ([...value].some((c) => (c.codePointAt(0) ?? 0) > 0x7f)) return null
  const email = value.toLowerCase()
  return email.length <= 140 && PATTERN.test(email) ? email : null
}
