"""What an uploaded file is, decided by its bytes and never by its name (G-83, R-53).

Pure: importable without frappe. The Frappe glue (the TEX image upload and the guard on
every public File) is in ``kamra.tex.security.uploads``.
"""

from __future__ import annotations

import re

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_SIDE = 8000
# raster images a booking site may show; SVG is never one of them (it can carry script)
IMAGE_EXTENSIONS = {"png": "png", "jpeg": "jpg", "gif": "gif", "webp": "webp"}
# served from the public folder these run in the platform's origin (script, markup, plugins)
ACTIVE_EXTENSIONS = frozenset({"html", "htm", "xhtml", "xht", "shtml", "svg", "svgz", "xml", "xsl", "xslt", "js",
                               "mjs", "swf", "hta"})

_SAFE_URL_CHARS = r"[^\s\"'<>()`\\]+"
_LOCAL = re.compile(rf"^/(?:files|private/files|assets)/{_SAFE_URL_CHARS}$")
_REMOTE = re.compile(rf"^https://[a-z0-9.-]+(?::\d+)?/{_SAFE_URL_CHARS}$", re.IGNORECASE)


def sniff_image(content: bytes | None) -> str | None:
	"""``png`` / ``jpeg`` / ``gif`` / ``webp`` from the magic bytes, else None."""
	c = content or b""
	if c.startswith(b"\x89PNG\r\n\x1a\n") and len(c) > 24:
		return "png"
	if c.startswith(b"\xff\xd8\xff") and len(c) > 3:
		return "jpeg"
	if c[:6] in (b"GIF87a", b"GIF89a") and len(c) > 10:
		return "gif"
	if c[:4] == b"RIFF" and c[8:12] == b"WEBP" and len(c) > 16:
		return "webp"
	return None


def extension(name: str | None) -> str:
	"""The last extension of a file name or URL path, lower case ("" when there is none)."""
	base = (name or "").split("?", 1)[0].split("#", 1)[0].rsplit("/", 1)[-1]
	return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def is_active_name(name: str | None) -> bool:
	"""Would a web server hand this file to a browser as markup or script?"""
	return extension(name) in ACTIVE_EXTENSIONS


def safe_image_url(url: str | None) -> bool:
	"""A booking site's logo or hero: a file of this platform that is not active content,
	or an https address. Never script, markup, quotes or other schemes."""
	u = (url or "").strip()
	if _LOCAL.match(u):
		return not is_active_name(u) and not u.endswith("/")
	return bool(_REMOTE.match(u))
