// A guest's e-mail is one plain address (batch 2P, ADR-080; `booking.plain_email` on the server): the booking app's
// details step and the CRM's profile drawer check it as the server does, so the server's refusal is not the first
// the guest or staff hear of it (2P review round 1). Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { plainEmail } from "../../src/lib/email.ts"

test("one plain ASCII address, trimmed and in lower case, as the server keeps it", () => {
  assert.equal(plainEmail(" Lena.Kraus@Example.com "), "lena.kraus@example.com")
  assert.equal(plainEmail("o'brien+tex@mail.example.ie"), "o'brien+tex@mail.example.ie")
})

test("anything the server refuses is refused here too", () => {
  for (const raw of ["ana@müller.de", "ana.müller@example.de", "ana@example.com.", "a..b@example.com", "ana​@example.com",
    "İNFO@HOTEL.COM", "ınfo@hotel.com", "Kate@example.com", "Ana <ana@example.de>", "a@example.com, b@example.com",
    "ana@@example.de", "ana@example", "", `${"a".repeat(130)}@example.com`])
    assert.equal(plainEmail(raw), null, JSON.stringify(raw))
})
