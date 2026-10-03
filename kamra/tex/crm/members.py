# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt
"""Loyalty members on the web (C-04, owner 2026-10-03; ADR-078).

A guest signs in on a booking site, or joins its hotels' loyalty program, by a one-time link sent to their e-mail:

* ``request_link``: a visitor asks for a link with an e-mail (to join: with their name and an explicit tick). The
  answer is the same whatever the e-mail (nobody learns from the site whether it has a profile or a membership); an
  address without a profile asked to sign in gets a mail that says so and links to joining, with no token. At most
  ``LINKS_PER_ADDRESS`` mails per address and site an hour.
* ``verify``: the link, used once within ``LINK_MINUTES`` on its own site, opens a session on that device for
  ``SESSION_DAYS`` (the owner's choice). Opening a join link joins the profile with that e-mail, made then with the
  name given when there is none: the link proves the e-mail is theirs, so nobody is joined with another's e-mail.
* ``join_signed_in``: a signed-in guest who is no member joins with a tick.

A link's token lives only in the mail (in the URL fragment, which browsers never send to a server) and in the cache,
by its hash, with what opening it needs (the e-mail, the name to join with) until it is used or expires. A session's
token is stored by its hash (``TEX Member Session``). Erasure deletes the guest's sessions; a merge moves them with the
other links to the profile; sessions ended long ago are purged daily.
"""

from __future__ import annotations

import hashlib
import json
import secrets

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, get_datetime, now_datetime, validate_email_address

from kamra.tex.crm import loyalty
from kamra.tex.services.refusals import refusal

LINK_MINUTES = 30
SESSION_DAYS = 30
LINKS_PER_ADDRESS = 3                        # per site, an hour
PURGE_AFTER_DAYS = 30                        # an ended session's row is removed this long after it ended
PURPOSES = ("sign_in", "join")
LINK_KEY = "tex:member_link:"                # + the token's hash
COUNT_KEY = "tex:member_links:"              # + site and the address's hash


def digest(token: str) -> str:
	return hashlib.sha256((token or "").encode()).hexdigest()


def site_properties(site) -> list[str]:
	from kamra.tex.services import sites

	return sites.site_properties(site)


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
	email = (raw or "").strip().lower()[:140]
	if not email or not validate_email_address(email):
		frappe.throw(_("Please enter a valid e-mail address."), refusal("GUEST_EMAIL_INVALID"))
	return email


def _name(raw, code: str) -> str:
	value = " ".join(str(raw or "").split())[:140]
	if not value:
		frappe.throw(_("Please enter your name."), refusal(code))
	return value


def _profile(email: str, enterprise: str | None, *, lock: bool = False) -> str | None:
	"""The profile a booking with this e-mail would join (``booking._find_profile``: the e-mail is the identity)."""
	from kamra.tex.services.booking import _find_profile

	return _find_profile({"email": email}, enterprise, staff=False, lock=lock)


def _cache():
	return frappe.cache


def _within_limit(site, email: str) -> bool:
	"""At most ``LINKS_PER_ADDRESS`` mails to one address from one site an hour (a visitor cannot flood an inbox)."""
	key = frappe.cache.make_key(f"{COUNT_KEY}{site.name}:{digest(email)}")
	if not _cache().get(key):  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key above
		_cache().setex(key, 3600, 0)
	return _cache().incrby(key, 1) <= LINKS_PER_ADDRESS


def request_link(site, *, email, purpose: str, first_name=None, last_name=None, accepted=False,
                 language: str = "en") -> None:
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
	if not _within_limit(site, email):
		return                                         # the same answer: nobody learns the limit was reached
	from kamra.tex.services import notify

	profile = _profile(email, site_enterprise(site))
	if purpose == "sign_in" and not profile:
		notify.member_mail(site, email, "member_none", language=language)
		return
	token = secrets.token_urlsafe(32)
	# the link's data, by its token's hash, until it is used or expires (a plain string: read and deleted at once)
	_cache().set(_link_key(token), json.dumps({  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key
		"site": site.name, "purpose": purpose, "email": email, "language": language,
		"expires_at": str(add_to_date(now_datetime(), minutes=LINK_MINUTES)), **names}), ex=LINK_MINUTES * 60)
	notify.member_mail(site, email, "member_join" if purpose == "join" else "member_sign_in", token=token,
	                   guest=profile, name=" ".join(names.values()) or None, language=language)


def _link_key(token: str) -> str:
	return frappe.cache.make_key(f"{LINK_KEY}{digest(token)}")


def _take_link(site, token: str) -> dict:
	"""The link's data, once (read and deleted in one step: two opens of one link never both succeed): refused when
	unknown, used, expired or of another site."""
	raw = _cache().getdel(_link_key(token)) if token else None  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key
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


def verify(site, token: str) -> dict:
	"""Open a link: a session for its profile (made, for a join link, when there is none) → {"session", "expires_at",
	"status"}. A join link joins the site's programs."""
	from kamra.tex.crm.service import require_live_guest

	data = _take_link(site, token)
	enterprise = site_enterprise(site)
	profile = _profile(data["email"], enterprise, lock=True)
	if not profile:
		if data["purpose"] != "join":
			frappe.throw(_("There is no membership with this e-mail. You can join the program instead."),
			             refusal("NOT_A_MEMBER"))
		profile = frappe.get_doc({
			"doctype": "Guest", "first_name": data["first_name"], "last_name": data["last_name"],
			"email": data["email"], "tex_enterprise": enterprise,
			"tex_language": (data.get("language") or "")[:10] or None}).insert(ignore_permissions=True).name
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
	return {"session": session, "expires_at": str(expires), "status": status(site, profile)}


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
	return {p for p in site_properties(site) if loyalty.is_member(guest, p)} if guest else set()


def status(site, guest: str) -> dict:
	"""What the booking app shows a signed-in guest: their name and e-mail (their own), whether they are a member at
	any of the site's hotels and at which."""
	g = frappe.db.get_value("Guest", guest, ["first_name", "last_name", "email"], as_dict=True) or {}
	hotels = member_hotels(site, guest)
	return {"signed_in": True, "first_name": g.get("first_name"), "last_name": g.get("last_name"),
	        "email": g.get("email"), "member": bool(hotels), "hotels": sorted(hotels)}


def join_site(site, guest: str) -> None:
	"""The guest joins the programs of the site's hotels: their own act on the web, proven by their e-mail
	(``loyalty.join_web``). The membership is the site's hotel's, or, on a hotel group's site, the program's own
	hotel's (none for a group's program)."""
	for program in site_programs(site):
		own = frappe.db.get_value("TEX Loyalty Program", program, "property")
		loyalty.join_web(guest, program, property=site.property or own or None)


def join_signed_in(site, token: str | None, accepted) -> dict:
	guest = require_session(site, token)
	if not accepted:
		frappe.throw(_("Please confirm that you join the loyalty program."), refusal("MEMBER_CONSENT_REQUIRED"))
	if not site_programs(site):
		frappe.throw(_("This site has no loyalty program."), refusal("MEMBERSHIP_UNAVAILABLE"))
	from kamra.tex.crm.service import require_live_guest

	require_live_guest(guest)
	join_site(site, guest)
	return status(site, guest)


def sign_out(site, token: str | None) -> None:
	name = frappe.db.get_value("TEX Member Session", {"token_hash": digest(token or ""), "site": site.name,
	                                                  "revoked_at": ("is", "not set")})
	if name:
		frappe.db.set_value("TEX Member Session", name, "revoked_at", now_datetime())


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
