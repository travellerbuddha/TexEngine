"""Entry screens (G-60, ADR-060): the product name, the source offer and where "/" leads.

The Frappe app stays ``kamra`` (ADR-001); what people see says TEX Engine. The name shown
comes from TEX Settings > Brand name (a platform setting), never from a request.

TEX Engine is a network service derived from Kamra PMS under AGPL-3.0. Section 13 asks that
every user interacting with it can get its complete corresponding source: staff and guests
alike (the admin app, the sign-in page, the booking engine, the legacy guest pages, Desk). They
link to the source of the version that runs: the TEX repository at the running commit, or the
site config's ``tex_source_url`` when an operator offers it elsewhere (https, no credentials; a
``{commit}`` in it is replaced by the running commit).
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

import frappe

PRODUCT = "TEX Engine"
SOURCE_URL = "https://github.com/travellerbuddha/TexEngine"
UPSTREAM = {"name": "Kamra PMS", "url": "https://github.com/Kamra-PMS/kamra-pms"}
LICENSE = {"name": "AGPL-3.0", "url": "https://www.gnu.org/licenses/agpl-3.0.html"}

# the SPA's router is mounted here (kamra/www/kamra.py, website_route_rules)
SPA_MOUNT = "kamra"
SIGN_IN = "/kamra/login"
ADMIN_APP = "/kamra/tex"
# a signed-in user without Desk access: Frappe's own portal page
PORTAL = "/me"
MAX_BRAND = 60


def brand_name() -> str:
	"""TEX Settings > Brand name, as plain text (the pages escape it), or the product name."""
	try:
		value = frappe.db.get_single_value("TEX Settings", "brand_name")
	except Exception:
		value = None
	value = " ".join(str(value or "").split())[:MAX_BRAND]
	return value or PRODUCT


COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
_UNSET = object()
_head: object | str | None = _UNSET


def _git_head(root: str) -> str | None:
	"""The commit checked out at ``root``, read from its ``.git`` (a directory, or a worktree's
	``gitdir:`` file) without running git. None when it cannot be told."""
	git = os.path.join(root, ".git")
	if os.path.isfile(git):
		with open(git, encoding="utf-8") as f:  # nosemgrep: frappe-security-file-traversal -- the app's own checkout
			line = f.read().strip()
		if not line.startswith("gitdir:"):
			return None
		git = os.path.normpath(os.path.join(root, line.split(":", 1)[1].strip()))
	if not os.path.isdir(git):
		return None
	common = git
	if os.path.isfile(os.path.join(git, "commondir")):
		with open(os.path.join(git, "commondir"), encoding="utf-8") as f:  # nosemgrep: frappe-security-file-traversal -- the app's own checkout
			common = os.path.normpath(os.path.join(git, f.read().strip()))
	with open(os.path.join(git, "HEAD"), encoding="utf-8") as f:  # nosemgrep: frappe-security-file-traversal -- the app's own checkout
		head = f.read().strip()
	if not head.startswith("ref:"):
		return head.lower() if COMMIT.match(head.lower()) else None
	ref = head.split(":", 1)[1].strip()
	for base in (git, common):
		path = os.path.join(base, *ref.split("/"))
		if os.path.isfile(path):
			with open(path, encoding="utf-8") as f:  # nosemgrep: frappe-security-file-traversal -- the app's own checkout
				sha = f.read().strip().lower()
			return sha if COMMIT.match(sha) else None
	packed = os.path.join(common, "packed-refs")
	if os.path.isfile(packed):
		with open(packed, encoding="utf-8") as f:  # nosemgrep: frappe-security-file-traversal -- the app's own checkout
			for line in f:
				parts = line.split()
				if len(parts) == 2 and parts[1] == ref and COMMIT.match(parts[0].lower()):
					return parts[0].lower()
	return None


def source_commit() -> str | None:
	"""The commit of the TEX Engine that runs: the site config's ``tex_source_commit`` (for an
	install without its git checkout), else the app checkout's HEAD (read once per process)."""
	global _head
	value = str(frappe.conf.get("tex_source_commit") or "").strip().lower()
	if COMMIT.match(value):
		return value
	if _head is _UNSET:
		try:
			_head = _git_head(os.path.dirname(frappe.get_app_path("kamra")))
		except Exception:
			_head = None
	return _head if isinstance(_head, str) else None


def offer_url(value: str | None) -> str | None:
	"""``value`` when it may be offered to anonymous visitors as the source address: an https URL
	with a host, at most 300 characters, no spaces, and no user name or password in it (L2)."""
	value = str(value or "").strip()
	if not value.startswith("https://") or len(value) > 300 or any(c.isspace() for c in value):
		return None
	try:
		parts = urlsplit(value)
	except ValueError:
		return None
	if not parts.hostname or parts.username is not None or parts.password is not None or "@" in parts.netloc:
		return None
	return value


def source_url() -> str:
	"""Where the running version's source is offered: the site config's ``tex_source_url`` (its
	``{commit}`` replaced by the running commit, or HEAD when that is unknown), otherwise the TEX
	Engine repository at the running commit."""
	commit = source_commit()
	value = offer_url(frappe.conf.get("tex_source_url"))
	if value:
		return value.replace("{commit}", commit or "HEAD")
	return f"{SOURCE_URL}/tree/{commit}" if commit else SOURCE_URL


def info() -> dict:
	"""What the public sign-in page shows: the name and the source offer. Nothing else."""
	return {"product": PRODUCT, "brand_name": brand_name(), "source_url": source_url(),
	        "upstream": dict(UPSTREAM), "license": dict(LICENSE)}


def extend_bootinfo(bootinfo) -> None:
	"""Desk's boot carries the source offer (Help > About, ``public/js/tex_source.js``)."""
	bootinfo.tex_source_url = source_url()


def source_meta() -> str:
	"""The source offer as ``<meta>`` tags for a served page (L3): the page shows it without
	asking the API, which may be rate limited or down."""
	from html import escape

	return (f'<meta name="tex-source-url" content="{escape(source_url(), quote=True)}" />'
	        f'<meta name="tex-brand" content="{escape(brand_name(), quote=True)}" />')


def below_mount(path: str | None) -> bool:
	"""Whether a request path is the SPA's own (``/kamra`` and below)."""
	first = (path or "").strip("/").split("/", 1)[0]
	return first == SPA_MOUNT


def root_target(user: str | None = None) -> str:
	"""Where the site root leads: the TEX admin app for a Desk user, the sign-in page for a
	visitor, Frappe's portal for a signed-in user without Desk access."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return SIGN_IN
	if user == "Administrator" or frappe.get_cached_value("User", user, "user_type") == "System User":
		return ADMIN_APP
	return PORTAL
