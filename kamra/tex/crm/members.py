# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt
"""Loyalty members on the web (C-04, owner 2026-10-03; ADR-078).

A guest signs in on a booking site, or joins its hotels' loyalty program, by a one-time link sent to their e-mail:

* ``request_link``: a visitor asks for a link with an e-mail (to join: with their name and an explicit tick). The
  answer is the same whatever the e-mail (nobody learns from the site whether it has a profile or a membership); an
  address without a profile asked to sign in gets a mail that says so and links to joining, with no token. At most
  ``LINKS_PER_ADDRESS`` mails per address and site an hour; a retried request (its idempotency key) sends none.
* ``verify``: the link, used once within ``LINK_MINUTES`` on its own site, opens a session on that device for
  ``SESSION_DAYS`` (the owner's choice). Opening a join link joins the profile with that e-mail, made then with the
  name given when there is none: the link proves the e-mail is theirs, so nobody is joined with another's e-mail.
* ``join_signed_in``: a signed-in guest who is no member asks to join with a tick: a join link goes to their own
  e-mail, as every web join is confirmed (the owner's choice), so a script that holds a session joins nobody.
* A membership staff ended with a rejoin blocked (C-04h, owner 2026-10-04) is never made active on the web: a join
  asked for it gets a mail that says to ask the hotel, with no link; staff joining the guest lift the block.

A link's token lives only in the mail (in the URL fragment, which browsers never send to a server) and in the cache,
by its hash, with what opening it needs (the e-mail, the name to join with) until it is used or expires. A session's
token is stored by its hash (``TEX Member Session``). Erasure deletes the guest's sessions and drops the links mailed to its address and not opened yet; a merge moves the
sessions with the other links to the profile; sessions ended long ago are purged daily.
"""

from __future__ import annotations

import hashlib
import json
import secrets

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, get_datetime, getdate, now_datetime

from kamra.tex.crm import loyalty
from kamra.tex.services.refusals import refusal
from kamra.tex.services.txn import retry_on_deadlock

LINK_MINUTES = 30
SESSION_DAYS = 30
LINKS_PER_ADDRESS = 3                        # per site, an hour
PURGE_AFTER_DAYS = 30                        # an ended session's row is removed this long after it ended
PURPOSES = ("sign_in", "join")
LINK_KEY = "tex:member_link:"                # + the token's hash
COUNT_KEY = "tex:member_links:"              # + site and the address's hash
REQUEST_KEY = "tex:member_request:"          # + site and the idempotency key's hash
PENDING_KEY = "tex:member_pending:"          # + the address's hash: its links' hashes not yet opened
REQUEST_SECONDS = 600
# a refusal that settles a link: anything else (a deadlock answered BUSY, a database error) leaves it to be used
FINAL = frozenset({"NOT_A_MEMBER", "MEMBER_LINK_INVALID"})


def digest(token: str) -> str:
	return hashlib.sha256((token or "").encode()).hexdigest()


def site_properties(site) -> list[str]:
	"""The hotels the site sells: a hotel group's enabled ones (as the site's search, ``sites.selling_properties``)."""
	from kamra.tex.services import sites

	return sites.selling_properties(site)


def site_programs(site) -> list[str]:
	"""The enabled loyalty programs of the site's hotels (each hotel's own, else its group's), in order."""
	out: list[str] = []
	for p in site_properties(site):
		prog = loyalty.program_for(p)
		if prog and prog not in out:
			out.append(prog)
	return out


def site_enterprise(site) -> str | None:
	props = site_properties(site)
	return frappe.db.get_value("Property", props[0], "tex_enterprise") if props else None


def _email(raw) -> str:
	"""One plain address in ASCII, in lower case (``booking.plain_email``, as a booking keys its guest since batch 2P):
	the limit, the profile and the mail are all keyed by it. The whole
	string must be Frappe's own address pattern (review round 1: its check takes a display name, a list or an invisible
	character, each of which would differ; round 2: an apostrophe is an address's, o'brien@…). ASCII only, as the
	database compares accents away (utf8mb4_unicode_ci): an accented domain would find an ASCII member's profile and
	have its link mailed to the look-alike address (round 2)."""
	from kamra.tex.services import booking

	email = booking.plain_email(raw)
	if not email:
		frappe.throw(_("Please enter a valid e-mail address."), refusal("GUEST_EMAIL_INVALID"))
	return email


def _name(raw, code: str) -> str:
	value = " ".join(str(raw or "").split())[:140]
	if not value:
		frappe.throw(_("Please enter your name."), refusal(code))
	return value


def _profile(email: str, enterprise: str | None, *, lock: bool = False) -> str | None:
	"""The profile of this e-mail, as a booking finds it (``booking.profile_of_email``: the e-mail is the identity):
	the oldest of the site's enterprise (or of none) whose stored e-mail is this address, in any case (review round 2
	of 2O, S-1: the database compares accents away, so ana@muller.de found the profile of ana@müller.de and its link
	signed the look-alike's owner in to it). ``lock``: locking reads."""
	from kamra.tex.services import booking

	return booking.profile_of_email(email, enterprise, lock=lock)


def _cache():
	return frappe.cache


def _within_limit(site, email: str) -> bool:
	"""At most ``LINKS_PER_ADDRESS`` mails to one address from one site an hour (a visitor cannot flood an inbox). The
	counter is made with its hour in one step, so it always expires (review round 1)."""
	key = frappe.cache.make_key(f"{COUNT_KEY}{site.name}:{digest(email)}")
	_cache().set(key, 0, ex=3600, nx=True)  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key above
	return _cache().incrby(key, 1) <= LINKS_PER_ADDRESS  # nosemgrep: frappe-cache-breaks-multitenancy -- site-scoped


def _first_request(site, key: str | None) -> bool:
	"""False for a request retried with the same idempotency key within ``REQUEST_SECONDS`` (it sends no mail again)."""
	if not key:
		return True
	k = frappe.cache.make_key(f"{REQUEST_KEY}{site.name}:{digest(str(key)[:140])}")
	return bool(_cache().set(k, 1, ex=REQUEST_SECONDS, nx=True))  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key


def request_link(site, *, email, purpose: str, first_name=None, last_name=None, accepted=False,
                 language: str = "en", idempotency_key: str | None = None) -> None:
	"""Send a sign-in or join link (module docstring). Refuses only what the visitor typed (an e-mail, a name, the
	tick) and a site without a program; otherwise answers the same whatever the e-mail."""
	if purpose not in PURPOSES:
		frappe.throw(_("Invalid request."), refusal("INVALID_REQUEST"))
	if not site_programs(site):
		frappe.throw(_("This site has no loyalty program."), refusal("MEMBERSHIP_UNAVAILABLE"))
	email = _email(email)
	names = {}
	if purpose == "join":
		names = {"first_name": _name(first_name, "GUEST_FIRST_NAME_REQUIRED"),
		         "last_name": _name(last_name, "GUEST_LAST_NAME_REQUIRED")}
		if not accepted:
			frappe.throw(_("Please confirm that you join the loyalty program."), refusal("MEMBER_CONSENT_REQUIRED"))
	_send_link(site, email, purpose, names, language, idempotency_key)


def _send_link(site, email: str, purpose: str, names: dict, language: str, idempotency_key: str | None) -> None:
	if not _first_request(site, idempotency_key) or not _within_limit(site, email):
		return                                         # the same answer: nobody learns the limit was reached
	from kamra.tex.services import notify

	profile = _profile(email, site_enterprise(site))
	if purpose == "sign_in" and not profile:
		notify.member_mail(site, email, "member_none", language=language)
		return
	blocked = _rejoin_blocked(site, profile) if purpose == "join" and profile else []
	if blocked and not _still_theirs(profile, email):
		return                                         # erased meanwhile: nothing goes to its address (review round 2)
	if blocked:
		# staff blocked a rejoin wherever the guest could join here (C-04h): no link; the mail, which only the
		# address's owner reads, says to ask the hotel, naming the programs blocked (never one the guest is still a
		# member of; batch 2Q). The site's answer is the same as ever
		notify.member_mail(site, email, "member_blocked", guest=profile, language=language, programs=blocked)
		return
	token = secrets.token_urlsafe(32)
	# the link's data, by its token's hash, until it is used or expires (a plain string: read and deleted at once); its
	# hash also among the address's pending links, which an erasure drops (batch 2O). One transaction: the address's
	# set always has its expiry, and outlives each of its links
	pending = _pending_key(email)
	pipe = _cache().pipeline(transaction=True)
	pipe.set(_link_key(token), json.dumps({  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key
		"site": site.name, "purpose": purpose, "email": email, "language": language, "profile": profile,
		"expires_at": str(add_to_date(now_datetime(), minutes=LINK_MINUTES)), **names}), ex=LINK_MINUTES * 60)
	pipe.sadd(pending, digest(token))  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key
	pipe.expire(pending, LINK_MINUTES * 60)  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key
	pipe.execute()
	if profile and not _still_theirs(profile, email):
		# erased (or merged away) while this request read it as it was: the erasure's drops may have run before the link
		# was filed, so its own link goes, and nothing is mailed (batch 2Q, §6O). An erasure committed after this read
		# drops the link itself (it is pending by then)
		pipe = _cache().pipeline(transaction=True)
		pipe.delete(_link_key(token))  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key
		pipe.srem(pending, digest(token))  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key
		pipe.execute()
		return
	# greeted by the profile's own name, or by none: never by what a visitor typed for an address they may not own
	notify.member_mail(site, email, "member_join" if purpose == "join" else "member_sign_in", token=token,
	                   guest=profile, language=language)


def _rejoin_blocked(site, guest: str) -> list[str]:
	"""The site's programs the guest is no member of, when staff blocked a rejoin of every one of them (C-04h): a join
	link would join nothing. Empty otherwise. Opening a link checks again, under the profile's lock
	(``loyalty.join_web``)."""
	open_ = [p for p in site_programs(site) if not loyalty.member_of(guest, p)]
	return open_ if open_ and all(loyalty.rejoin_blocked(guest, p) for p in open_) else []


def _link_key(token: str) -> str:
	return frappe.cache.make_key(f"{LINK_KEY}{digest(token)}")


def _pending_key(email: str) -> str:
	"""The address's pending links, whatever site or enterprise sent them (review round 1 S1: a profile of no
	enterprise matches every enterprise's site, so a set by enterprise missed its links). Site-scoped by ``make_key``."""
	return frappe.cache.make_key(f"{PENDING_KEY}{digest(email)}")


def drop_links(emails) -> int:
	"""Right to erasure (``erase_traces``): the links mailed to the profile's addresses and not opened yet go, on every
	booking site of this Frappe site (batch 2O, §6N2: one opened after the erasure signed in, or joined a profile made
	again from the name typed before it). Another enterprise's link to the same address goes too: its owner asks for a
	new one. → how many."""
	dropped = 0
	for email in sorted({str(e).strip().lower() for e in emails or () if e}):
		pending = _pending_key(email)
		pipe = _cache().pipeline(transaction=True)
		pipe.smembers(pending)  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key
		pipe.delete(pending)  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key
		hashes = [h.decode() if isinstance(h, bytes) else h for h in pipe.execute()[0] or ()]
		if hashes:
			dropped += _cache().delete(*(frappe.cache.make_key(f"{LINK_KEY}{h}") for h in hashes))  # nosemgrep: frappe-cache-breaks-multitenancy -- keys are site-scoped by make_key
	return dropped


# the profile's row as committed now (a locking read: a plain one sees the request's read view)
PROFILE_NOW = """SELECT email, tex_erased_at FROM `tabGuest` WHERE name=%s LOCK IN SHARE MODE"""


def _still_theirs(profile: str, email: str) -> bool:
	"""The profile a request found, as committed now: not erased, not merged away, still this address's (batch 2Q review
	round 1: the request's read view can be older than an erasure; the share lock holds it until the request ends)."""
	row = frappe.db.sql(PROFILE_NOW, profile, as_dict=True)
	return bool(row) and not row[0].tex_erased_at and (row[0].email or "").strip().lower() == email


def _take_link(site, token: str) -> dict:
	"""The link's data, once (read and deleted in one step: two opens of one link never both succeed): refused when
	unknown, used, expired or of another site."""
	raw = None
	if token:
		# read and deleted in one transaction (MULTI/EXEC: any Redis version, where GETDEL needs 6.2)
		pipe = _cache().pipeline(transaction=True)
		pipe.get(_link_key(token))  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key
		pipe.delete(_link_key(token))  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key
		raw = pipe.execute()[0]
	try:
		data = json.loads(raw) if raw else None
	except ValueError:
		data = None
	if not isinstance(data, dict) or data.get("site") != site.name:
		frappe.throw(_("This link is not valid or has expired. Please ask for a new one."),
		             refusal("MEMBER_LINK_INVALID"))
	if now_datetime() > get_datetime(data.get("expires_at")):
		frappe.throw(_("This link is not valid or has expired. Please ask for a new one."),
		             refusal("MEMBER_LINK_INVALID"))
	return data


def _put_back(token: str, data: dict) -> None:
	"""A link taken by a request that failed before it was used (review round 1): usable again until it expires, unless
	an erasure dropped the address's links meanwhile (batch 2O). No database read: the request may have lost it."""
	left = int((get_datetime(data.get("expires_at")) - now_datetime()).total_seconds())
	if left <= 0:
		return
	# the raw command, as every one here: the wrapper's own sismember would prefix the made key again
	pipe = _cache().pipeline(transaction=False)
	pipe.sismember(_pending_key(data.get("email") or ""), digest(token))  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key
	if pipe.execute()[0]:
		_cache().set(_link_key(token), json.dumps(data), ex=left)  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key


def verify(site, token: str) -> dict:
	"""Open a link: a session for its profile (made, for a join link, when there is none) → {"session", "expires_at",
	"expires_in", "status"}. A join link joins the site's programs. The link is taken once, outside the part a
	deadlock runs again (review round 1: the retry found it spent); a failure that did not settle it (BUSY, a
	database error) leaves it usable."""
	data = _take_link(site, token)
	try:
		opened = _open(site, data)
	except Exception as e:
		if getattr(e, "code", None) not in FINAL:
			_put_back(token, data)
		raise
	# a request that fails after this (its answer, before its commit) rolls its session back: the link with it (batch
	# 2Q). A commit clears the callback; a COMMIT statement that fails itself is not covered
	frappe.db.after_rollback.add(lambda: _put_back_quietly(token, data))
	return opened


def _put_back_quietly(token: str, data: dict) -> None:
	"""``_put_back`` from a rollback: a failure (Redis) is logged, never the request's answer (review round 1)."""
	try:
		_put_back(token, data)
	except Exception:
		from kamra.tex.security.audit import log_exception

		log_exception("TEX member link put back", defer=True)


@retry_on_deadlock
def _open(site, data: dict) -> dict:
	from kamra.tex.crm.service import require_live_guest

	enterprise = site_enterprise(site)
	profile = _profile(data["email"], enterprise, lock=True)
	if data.get("profile") and profile != data["profile"]:
		# the profile the link was mailed for is gone, erased or no longer this address's (a link opened while it was
		# erased, or put back after the erasure's drop): never one made again from the name typed before (review round 2)
		frappe.throw(_("This link is not valid or has expired. Please ask for a new one."),
		             refusal("MEMBER_LINK_INVALID"))
	if not profile:
		# a sign-in link, or a signed-in guest's join link whose profile is gone since: no profile to make
		if data["purpose"] != "join" or not data.get("first_name") or not data.get("last_name"):
			frappe.throw(_("There is no membership with this e-mail. You can join the program instead."),
			             refusal("NOT_A_MEMBER"))
		profile = frappe.get_doc({
			"doctype": "Guest", "first_name": data["first_name"], "last_name": data["last_name"],
			"email": data["email"], "tex_enterprise": enterprise,
			"tex_language": _language(data.get("language"))}).insert(ignore_permissions=True).name
	require_live_guest(profile)                        # locked, as every write of its records
	if frappe.db.get_value("Guest", profile, "tex_erased_at", for_update=True):
		frappe.throw(_("There is no membership with this e-mail. You can join the program instead."),
		             refusal("NOT_A_MEMBER"))
	if data["purpose"] == "join":
		join_site(site, profile)
	session = secrets.token_urlsafe(32)
	expires = add_days(now_datetime(), SESSION_DAYS)
	frappe.get_doc({"doctype": "TEX Member Session", "site": site.name, "property": site.property or None,
	                "guest": profile, "token_hash": digest(session), "expires_at": expires}
	               ).insert(ignore_permissions=True)
	# expires_in: the device keeps the session by its own clock (the server's time zone is not the browser's)
	return {"session": session, "expires_at": str(expires), "expires_in": SESSION_DAYS * 86400,
	        "status": status(site, profile)}


def session_guest(site, token: str | None) -> str | None:
	"""The guest signed in by this session on this site, or None (unknown, signed out, expired, or an erased
	profile)."""
	if not token:
		return None
	row = frappe.db.get_value("TEX Member Session", {"token_hash": digest(token), "site": site.name},
	                          ["guest", "expires_at", "revoked_at"], as_dict=True)
	if not row or row.revoked_at or not row.expires_at or row.expires_at <= now_datetime():
		return None
	if not frappe.db.exists("Guest", row.guest) or frappe.db.get_value("Guest", row.guest, "tex_erased_at"):
		return None
	return row.guest


def require_session(site, token: str | None) -> str:
	guest = session_guest(site, token)
	if not guest:
		frappe.throw(_("You are signed out. Please sign in again."), refusal("MEMBER_SESSION_ENDED"))
	return guest


def member_hotels(site, guest: str | None) -> set[str]:
	"""The site's hotels whose program the guest is a member of."""
	return loyalty.member_hotels(guest, site_properties(site))


def teaser_hotels(site, props: list[str], *, check_in=None, check_out=None, market: str | None = None,
                  channel: str | None = None, promo_codes=()) -> set[str]:
	"""Of ``props``, the hotels whose program has a members-only promotion live now: where anyone is shown the member
	price as "Member price" (the owner's choice; applied only to a member signed in). With the search's stay, market
	and channel, only where such a promotion may apply to it (``promotions.may_apply_to_stay``; batch 2Q): the teaser
	prices those hotels a second time."""
	from kamra.tex.commercial import context
	from kamra.tex.pricing.promotions import code_key, may_apply_to_stay

	now = now_datetime()
	stay = None
	if check_in and check_out and market and channel:
		stay = {"check_in": getdate(check_in), "check_out": getdate(check_out), "market": market, "channel": channel,
		        "codes": frozenset(code_key(c) for c in promo_codes or () if c)}

	def teased(promotion) -> bool:
		return promotion.member_only and (stay is None or may_apply_to_stay(promotion, **stay))

	return {p for p in props if loyalty.program_for(p) and any(teased(x) for x in context.promotions(p, now))}


def status(site, guest: str) -> dict:
	"""What the booking app shows a signed-in guest: their name and e-mail (their own), whether they are a member at
	any of the site's hotels and at which."""
	g = frappe.db.get_value("Guest", guest, ["first_name", "last_name", "email"], as_dict=True) or {}
	hotels = member_hotels(site, guest)
	return {"signed_in": True, "first_name": g.get("first_name"), "last_name": g.get("last_name"),
	        "email": g.get("email"), "member": bool(hotels), "hotels": sorted(hotels)}


def _language(raw) -> str | None:
	"""A language the booking app speaks, else none (review round 1: the value came from the visitor)."""
	from kamra.tex.services import content

	return content.guest_language(str(raw or "")[:10]) if raw else None


def join_site(site, guest: str) -> None:
	"""The guest joins the programs of the site's hotels: their own act on the web, proven by their e-mail
	(``loyalty.join_web``). The membership is the site's hotel's; on a hotel group's site, the first of its hotels
	(by name) the program serves, so that hotel's staff see the join and the record (review round 1: a group's
	program has no hotel of its own, and the join belonged to nobody)."""
	props = site_properties(site)
	for program in site_programs(site):
		hotel = site.property or next((p for p in props if loyalty.program_for(p) == program), None)
		loyalty.join_web(guest, program, property=hotel)


def join_signed_in(site, token: str | None, accepted, *, language: str = "en",
                   idempotency_key: str | None = None) -> None:
	"""A signed-in guest who is no member asks to join, with the tick: a join link goes to the profile's own e-mail,
	as every web join is confirmed (the owner's choice; review round 1: a script that holds a session on the page
	joins nobody)."""
	guest = require_session(site, token)
	if not accepted:
		frappe.throw(_("Please confirm that you join the loyalty program."), refusal("MEMBER_CONSENT_REQUIRED"))
	if not site_programs(site):
		frappe.throw(_("This site has no loyalty program."), refusal("MEMBERSHIP_UNAVAILABLE"))
	email = frappe.db.get_value("Guest", guest, "email")
	try:
		email = _email(email)
	except frappe.ValidationError:
		# a profile whose stored e-mail is not one plain ASCII address (staff typed it): the guest, signed in to it, is
		# told so (batch 2O; it answered "sent" and sent nothing). Their own profile's: nobody else learns anything.
		# The address check's own message is not this answer's (review round 1, NIT 1)
		frappe.clear_last_message()
		frappe.throw(_("A link cannot be sent to the e-mail address of your profile. Please contact the hotel."),
		             refusal("MEMBER_EMAIL_UNUSABLE"))
	_send_link(site, email, "join", {}, language, idempotency_key)


def sign_out(site, token: str | None) -> None:
	name = frappe.db.get_value("TEX Member Session", {"token_hash": digest(token or ""), "site": site.name,
	                                                  "revoked_at": ("is", "not set")})
	if name:
		frappe.db.set_value("TEX Member Session", name, "revoked_at", now_datetime())


def _seen_by(row, hotels: set[str], cache: dict) -> bool:
	"""A session staff see through ``hotels``: its site's hotel's, or on a hotel group's site (no hotel), one of the
	site's hotels (as ``perm`` reads a site's records)."""
	if row.property:
		return row.property in hotels
	if row.site not in cache:
		site = frappe.get_doc("TEX Booking Site", row.site) if frappe.db.exists("TEX Booking Site", row.site) else None
		cache[row.site] = set(site_properties(site)) if site else set()
	return bool(cache[row.site] & hotels)


SESSION_FIELDS = ["name", "site", "property", "creation", "expires_at", "revoked_at"]


def staff_sessions(guest: str, hotels: set[str], edit: set[str] | None = None) -> list[dict]:
	"""The guest's sessions on the booking sites of ``hotels`` (those the staff member sees the guest through), newest
	first: where, since when, until when, whether signed out (batch 2O); ``can_end``: an open one of a site of
	``edit`` (where they may edit the guest: review round 1, NIT 3). Never a token or its hash."""
	now, cache, out = now_datetime(), {}, []
	for r in frappe.get_all("TEX Member Session", filters={"guest": guest}, fields=SESSION_FIELDS,
	                        order_by="creation desc, name desc"):
		if not _seen_by(r, hotels, cache):
			continue
		# a nullable end read here, never filtered on (ADR-064): no end yet is open
		active = not r.revoked_at and bool(r.expires_at) and r.expires_at > now
		out.append({"name": r.name, "site": r.site,
		            "site_name": frappe.db.get_value("TEX Booking Site", r.site, "site_name") or r.site,
		            "hotel": r.property, "signed_in_at": str(r.creation),
		            "expires_at": str(r.expires_at) if r.expires_at else None,
		            "signed_out_at": str(r.revoked_at) if r.revoked_at else None, "active": active,
		            "can_end": active and _seen_by(r, edit or set(), cache)})
	return out


def staff_end_sessions(guest: str, hotels: set[str], name: str | None = None) -> int:
	"""Staff sign the guest out (a lost phone, a shared computer): every open session of theirs at the booking sites of
	``hotels`` (those where the user may edit the guest), or the one named; audited ``member.sessions_end`` on the guest,
	to the hotels it reached (batch 2O). → how many ended."""
	from kamra.tex.security.audit import audit

	now, cache, ended, reached = now_datetime(), {}, [], set()
	for r in frappe.get_all("TEX Member Session", filters={"guest": guest, **({"name": name} if name else {})},
	                        fields=SESSION_FIELDS):
		if r.revoked_at or not r.expires_at or r.expires_at <= now or not _seen_by(r, hotels, cache):
			continue
		frappe.db.set_value("TEX Member Session", r.name, "revoked_at", now)
		ended.append(r.name)
		reached |= {r.property} if r.property else cache.get(r.site, set()) & hotels
	audit("member.sessions_end", reference_doctype="Guest", reference_name=guest,
	      property=min(reached) if reached else None, hotels=reached, new={"ended": len(ended), "sessions": ended})
	return len(ended)


def end_sessions(guest: str) -> int:
	"""Right to erasure: the guest's sessions go (``erase_traces``)."""
	names = frappe.get_all("TEX Member Session", filters={"guest": guest}, pluck="name")
	if names:
		frappe.db.delete("TEX Member Session", {"name": ("in", names)})
	return len(names)


def purge_sessions() -> int:
	"""Daily: sessions that ended (expired or signed out) more than ``PURGE_AFTER_DAYS`` ago are removed."""
	before = add_days(now_datetime(), -PURGE_AFTER_DAYS)
	# a session with no end yet (NULL) is never purged by that end
	names = set(frappe.get_all("TEX Member Session", filters=[["expires_at", "is", "set"], ["expires_at", "<", before]],
	                           pluck="name"))
	names |= set(frappe.get_all("TEX Member Session", filters=[["revoked_at", "is", "set"], ["revoked_at", "<", before]],
	                            pluck="name"))
	names = sorted(names)
	if names:
		frappe.db.delete("TEX Member Session", {"name": ("in", names)})
	return len(names)


def site_membership(site) -> dict | None:
	"""What the booking app needs to offer signing in and joining: the site's programs by name, or None without one."""
	programs = site_programs(site)
	if not programs:
		return None
	return {"programs": [frappe.db.get_value("TEX Loyalty Program", p, "program_name") or "" for p in programs]}
