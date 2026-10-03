// A loyalty member on the booking site (C-04, ADR-078; booking/lib/member.ts): the session is kept on this device for
// the time the server gave it, by this device's clock; a link's token is read from the fragment only; a member's
// price is the signed-in member's own. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import {
  forgetMemberSession,
  isolateMemberData,
  keepMemberSession,
  keepSessionsOnDevice,
  linkToken,
  memberPriced,
  memberReturn,
  memberSession,
  rememberMemberReturn,
  sessionTag,
} from "../../src/booking/lib/member.ts"
import { getItem, setJSON } from "../../src/booking/lib/storage.ts"

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

test("on a hotel's own host the session is kept on the device; on the platform's shared host only in the tab", () => {
  const now = Date.now()
  keepSessionsOnDevice(true)
  keepMemberSession("aurora", "tok-device", DAY, now)
  assert.ok(getItem("tex.member.aurora", "local"))
  assert.equal(getItem("tex.member.aurora", "session"), null)
  forgetMemberSession("aurora")
  keepSessionsOnDevice(false)
  keepMemberSession("aurora", "tok-tab", DAY, now)
  assert.equal(getItem("tex.member.aurora", "local"), null)
  assert.ok(getItem("tex.member.aurora", "session"))
  assert.equal(memberSession("aurora", now), "tok-tab")
  forgetMemberSession("aurora")
  keepSessionsOnDevice(true)
})

test("on the platform's shared host a site's page keeps no other site's member data (owner, review round 1)", () => {
  const now = Date.now()
  setJSON("tex.member.borealis", { token: "theirs", expires: now + 1000 }, "session")
  setJSON("tex.member.aurora", { token: "ours", expires: now + 1000 }, "session")
  setJSON("tex.member.borealis", { token: "kept-on-device", expires: now + 1000 }, "local")
  setJSON("tex.member.aurora", { token: "kept-on-device", expires: now + 1000 }, "local")
  keepSessionsOnDevice(false)
  rememberMemberReturn("aurora", "?checkin=2026-11-01", now)
  rememberMemberReturn("borealis", "?checkin=2026-12-01", now)
  setJSON("tex.member.back.borealis", { q: "?checkin=2026-12-01", at: now }, "local")
  isolateMemberData("aurora")
  assert.equal(memberSession("aurora", now), "ours")
  assert.equal(memberSession("borealis", now), null)
  // nothing of a member stays on the device there; the search to return to is this site's only, in the tab
  assert.equal(getItem("tex.member.aurora", "local"), null)
  assert.equal(getItem("tex.member.borealis", "local"), null)
  assert.equal(getItem("tex.member.back.borealis", "local"), null)
  assert.equal(memberReturn("borealis", now), null)
  assert.equal(memberReturn("aurora", now), "?checkin=2026-11-01")
  // a site-less page (a payment link) keeps none
  setJSON("tex.member.aurora", { token: "ours", expires: now + 1000 }, "session")
  isolateMemberData(null)
  assert.equal(memberSession("aurora", now), null)
  keepSessionsOnDevice(true)
})

test("the site and the member page of the address a page opened at, before the router runs", async () => {
  const { isMemberPath, slugFromLocation } = await import("../../src/booking/lib/mount.ts")
  assert.equal(slugFromLocation("/book/aurora"), "aurora")
  assert.equal(slugFromLocation("/book/Aurora/member"), "aurora")
  assert.equal(slugFromLocation("/book/pay"), null)                         // a site-less payment page
  assert.equal(slugFromLocation("/book/pay/return"), null)
  assert.equal(slugFromLocation("/book/a%20b"), null)                       // not a slug
  assert.equal(slugFromLocation("/kamra/tex"), null)
  assert.equal(isMemberPath("/book/aurora/member"), true)
  assert.equal(isMemberPath("/member"), true)                               // a hotel's own host
  assert.equal(isMemberPath("/book/aurora/member/x"), false)
  assert.equal(isMemberPath("/book/aurora/manage"), false)
})
