"""What an uploaded file is, decided by its bytes and by the name it is stored under, never by
the name a client sends (G-83, R-53, ADR-046).

Pure: importable without frappe. The Frappe glue (the TEX image upload and the guard on
every public File) is in ``kamra.tex.security.uploads``.
"""

from __future__ import annotations

import mimetypes
import re
from urllib.parse import unquote, urlparse

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_SIDE = 8000
# raster images a booking site may show; SVG is never one of them (it can carry script)
IMAGE_EXTENSIONS = {"png": "png", "jpeg": "jpg", "gif": "gif", "webp": "webp"}
# The only files the public folder serves (review of G-83): what hotels and Frappe store publicly
# (images, room and housekeeping video, audio, PDFs and office documents, fonts, archives).
# Anything else (HTML, SVG, every XML type browsers render, script, unknown or no extension)
# must be stored private, where Frappe checks access and forces a download.
PUBLIC_EXTENSIONS = frozenset({
	"png", "jpg", "jpeg", "gif", "webp", "avif", "bmp", "ico", "tif", "tiff", "heic", "heif",
	"mp4", "m4v", "mov", "webm", "ogv", "3gp",
	"mp3", "m4a", "aac", "oga", "ogg", "opus", "wav", "weba",
	"pdf", "txt", "csv", "tsv", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "rtf",
	"woff", "woff2", "ttf", "otf", "eot",
	"zip",
})
# served from the public folder these run in the platform's origin (script, markup, plugins);
# used for reporting (p24) and messages: the allow-list above is what decides
ACTIVE_EXTENSIONS = frozenset({"html", "htm", "xhtml", "xht", "shtml", "svg", "svgz", "xml", "xsl", "xslt", "xsd",
                               "rss", "atom", "rdf", "mml", "kml", "js", "mjs", "swf", "hta"})
# Frappe stores ``file_name`` with these characters replaced by "_" (save_file_on_filesystem)
_FRAPPE_UNSAFE = re.compile(r"[/\\%?#]")
_LOCAL_IMAGE = re.compile(r"^/files/[A-Za-z0-9._-]+\.(?:png|jpe?g|gif|webp)$", re.IGNORECASE)
_REMOTE = re.compile(r"^https://[a-z0-9.-]+(?::\d+)?/[^\s\"'<>()`\\]+$", re.IGNORECASE)


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
	"""The last extension of a stored file name, lower case ("" when there is none)."""
	base = (name or "").rsplit("/", 1)[-1]
	return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def served_names(name: str | None) -> set[str]:
	"""The names a file name or URL can end up stored and served under: as given and URL-
	decoded (File unquotes ``file_url``), each with Frappe's ``[/\\%?#] → _`` applied to its
	last path segment (a URL) or to the whole name (a file name loses its slashes)."""
	raw = str(name or "")
	out = set()
	for v in {raw, unquote(raw)}:
		base = v.rsplit("/", 1)[-1] if v.startswith("/") else v.replace("/", "")
		out.add(_FRAPPE_UNSAFE.sub("_", base))
	return out


def _active_type(mime: str | None) -> bool:
	m = (mime or "").lower()
	return m in ("text/html", "application/x-shockwave-flash", "text/x-component") or m.endswith(("/xml", "+xml")) \
		or "javascript" in m


def may_be_public(name: str | None) -> bool:
	"""May a file stored under this name (or URL) be served from the public folder?"""
	for n in served_names(name):
		ext = extension(n)
		if ext not in PUBLIC_EXTENSIONS or _active_type(mimetypes.guess_type(f"x.{ext}")[0]):
			return False
	return True


def is_active_name(name: str | None) -> bool:
	"""Would a web server hand this file to a browser as markup or script?"""
	return any(extension(n) in ACTIVE_EXTENSIONS or _active_type(mimetypes.guess_type(n)[0])
	           for n in served_names(name) if n)


def safe_image_url(url: str | None, own_hosts=()) -> bool:
	"""A booking site's logo or hero: a PNG/JPEG/GIF/WebP in this platform's public files, or an
	https address on another host. Never another path of the platform (an image request
	carries the viewer's session), script, markup, quotes or another scheme."""
	u = (url or "").strip()
	if _LOCAL_IMAGE.match(u):
		return ".." not in u
	if not _REMOTE.match(u):
		return False
	host = (urlparse(u).hostname or "").lower()
	return host not in {str(h).lower() for h in own_hosts if h}
