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

// 2P review round 2 (LOW 1): the CRM drawer refused to save any edit of a profile whose stored address is not plain
// (made by the Desk form or a legacy path), though the server checks only an address that is sent
test("an address is checked when it is edited, never one left as it was stored", async () => {
  const { editedEmailInvalid } = await import("../../src/lib/email.ts")
  assert.equal(editedEmailInvalid("info@hotel.com.", "info@hotel.com."), false)        // the phone was edited
  assert.equal(editedEmailInvalid("İNFO@HOTEL.COM", "İNFO@HOTEL.COM"), false)
  assert.equal(editedEmailInvalid("info@hotel.com.", "info@hotel.com"), true)          // typed now
  assert.equal(editedEmailInvalid("İNFO@HOTEL.COM", ""), true)
  assert.equal(editedEmailInvalid("info@hotel.com", "İNFO@HOTEL.COM"), false)
  assert.equal(editedEmailInvalid("", "info@hotel.com"), false)                          // cleared
})

// 2P review round 2 (NIT 3): JavaScript's trim() is not Python's strip(): a BOM (U+FEFF) passed here and was refused
// by the server; an information separator (U+001C–U+001F) or NEL (U+0085) the server strips was refused here
test("the ends are trimmed as the server trims them", async () => {
  const { plainEmail: plain } = await import("../../src/lib/email.ts")
  assert.equal(plain("ana@example.com﻿"), null)
  assert.equal(plain("﻿ana@example.com"), null)
  for (const end of ["\u001c", "\u001f", "\u0085", " ", " ", "　", "\t\n"])
    assert.equal(plain(`${end}ana@example.com${end}`), "ana@example.com", JSON.stringify(end))
})
