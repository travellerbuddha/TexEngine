// A loyalty member on the booking site (C-04, ADR-078; booking/lib/member.ts): the session is kept on this device for
// the time the server gave it, by this device's clock; a link's token is read from the fragment only; a member's
// price is the signed-in member's own. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import {
  forgetMemberSession,
  keepMemberSession,
  linkToken,
  memberPriced,
  memberReturn,
  memberSession,
  rememberMemberReturn,
  sessionTag,
} from "../../src/booking/lib/member.ts"
import { setJSON } from "../../src/booking/lib/storage.ts"

const DAY = 86400

test("a session is kept for the seconds the server gave it, counted on this device, then forgotten", () => {
  const now = Date.UTC(2026, 9, 3, 12)
  keepMemberSession("aurora", "tok-1", 30 * DAY, now)
  assert.equal(memberSession("aurora", now), "tok-1")
  assert.equal(memberSession("aurora", now + 30 * DAY * 1000 - 1), "tok-1")
  assert.equal(memberSession("aurora", now + 30 * DAY * 1000), null)
  // forgotten, not only hidden: an earlier clock does not bring it back
  assert.equal(memberSession("aurora", now), null)
})

test("each site keeps its own session, and signing out forgets it", () => {
  const now = Date.now()
  keepMemberSession("aurora", "tok-a", DAY, now)
  keepMemberSession("borealis", "tok-b", DAY, now)
  assert.equal(memberSession("aurora", now), "tok-a")
  forgetMemberSession("aurora")
  assert.equal(memberSession("aurora", now), null)
  assert.equal(memberSession("borealis", now), "tok-b")
  forgetMemberSession("borealis")
})

test("an unreadable or empty session is never used", () => {
  const now = Date.now()
  keepMemberSession("aurora", "", DAY, now)
  assert.equal(memberSession("aurora", now), null)
  keepMemberSession("aurora", "tok", Number.NaN, now)
  assert.equal(memberSession("aurora", now), null)
  keepMemberSession("aurora", "tok", -5, now)
  assert.equal(memberSession("aurora", now), null)
  // a session kept by an older page (a server time) or tampered with
  setJSON("tex.member.aurora", { token: "tok", expires_at: "2099-01-01 00:00:00" }, "local")
  assert.equal(memberSession("aurora", now), null)
  setJSON("tex.member.aurora", { token: 7, expires: now + 1000 }, "local")
  assert.equal(memberSession("aurora", now), null)
})

test("a link's token is read from the fragment, nowhere else", () => {
  assert.equal(linkToken("#token=abc_DEF-123"), "abc_DEF-123")
  assert.equal(linkToken("#x=1&token=a%2Bb"), "a+b")
  assert.equal(linkToken("token=abc"), "abc")
  assert.equal(linkToken("#mytoken=abc"), null)
  assert.equal(linkToken("#token="), null)
  assert.equal(linkToken(""), null)
  assert.equal(linkToken("#token=%E0%A4%A"), null) // malformed escape
})

test("the search a link was asked from is the one returned to, without the step or the dialog", () => {
  const now = Date.UTC(2026, 9, 3, 12)
  rememberMemberReturn("aurora", "?checkin=2026-11-01&checkout=2026-11-05&step=details&sign_in=1", now)
  assert.equal(memberReturn("aurora", now + 10 * 60 * 1000), "?checkin=2026-11-01&checkout=2026-11-05")
  // taken once
  assert.equal(memberReturn("aurora", now), null)
  // asked for long ago: the site's start page
  rememberMemberReturn("aurora", "?checkin=2026-11-01", now)
  assert.equal(memberReturn("aurora", now + 61 * 60 * 1000), null)
  // nothing to keep: an older one is not left behind
  rememberMemberReturn("aurora", "?checkin=2026-11-01", now)
  rememberMemberReturn("aurora", "?join=1", now)
  assert.equal(memberReturn("aurora", now), null)
})

test("a session's tag names it without its token, and differs between sessions", () => {
  const a = sessionTag("Xms7m4C451jTwKBiCYbG1F16qDhh9Y7kau6iYVPiETk")
  assert.equal(a, sessionTag("Xms7m4C451jTwKBiCYbG1F16qDhh9Y7kau6iYVPiETk"))
  assert.notEqual(a, sessionTag("Xms7m4C451jTwKBiCYbG1F16qDhh9Y7kau6iYVPiETl"))
  assert.ok(a.length <= 7 && !"Xms7m4C451jTwKBiCYbG1F16qDhh9Y7kau6iYVPiETk".includes(a))
})

test("a member's price: a members-only promotion that applied to a room", () => {
  const promo = (applied: boolean, member_only?: boolean) => ({ promo_id: "P", name: "Club", applied, member_only })
  assert.equal(memberPriced([{ promotions: [promo(true, true)] }]), true)
  assert.equal(memberPriced([null, { promotions: [promo(false, false)] }, { promotions: [promo(true, true)] }]), true)
  // offered but not applied, or anyone's promotion
  assert.equal(memberPriced([{ promotions: [promo(false, true)] }]), false)
  assert.equal(memberPriced([{ promotions: [promo(true)] }]), false)
  assert.equal(memberPriced([undefined, null, { promotions: [] }]), false)
})
