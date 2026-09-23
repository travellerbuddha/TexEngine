"""Server-side upload checks (G-83, R-53). The browser's checks are a convenience only.

- ``save_public_image``: the TEX booking-site image upload. The bytes must be a PNG, JPEG
  (an iPhone's multi-picture JPEG too), GIF or WebP image of at most 2 MB and 8000 px a side
  that Pillow decodes whole; the stored name takes the extension of what the bytes are, never
  of what the name claims.
- ``PublicFileGuard``: mixed into Frappe's File (``hooks.extend_doctype_class``). The public
  folder serves only the types in ``filetypes.PUBLIC_EXTENSIONS`` (images, video, audio, PDF,
  office documents, fonts, zip), judged on the name File actually stores (URL-decoded, with
  Frappe's ``[/\\%?#] → _``), on every path (``upload_file``, Desk attachments, inline images,
  legacy screens, code). Anything else, HTML, SVG and XML above all, is refused as a public file
  before a byte is written, and a private file is never made public if it is one of those.
  A file is private when flagged so or when its URL is under ``/private/`` (as Frappe decides).
"""

from __future__ import annotations

import io
import re

import frappe
from frappe import _

from kamra.tex.security import filetypes as ft


class UploadRefused(frappe.ValidationError):
	pass


def _private(doc, *, by_url: bool = True) -> bool:
	if int(doc.get("is_private") or 0):
		return True
	return by_url and str(doc.get("file_url") or "").startswith("/private/")


def refuse_public(doc, *names, by_url: bool = True) -> None:
	"""Refuse a public file stored under any of ``names`` that the public folder may not serve."""
	if doc.get("is_folder") or _private(doc, by_url=by_url):
		return
	for name in names:
		if not name or str(name).startswith(("http://", "https://")) or ft.may_be_public(name):
			continue
		ext = next((ft.extension(n) for n in ft.served_names(name) if ft.extension(n)), "")
		what = _("{0} files").format(ext.upper()) if ext else _("Files without an extension")
		frappe.throw(_("{0} cannot be public: only images, video, audio, PDF and office documents are served "
		               "publicly, and HTML, SVG, XML and script files would run in this site's pages. Store it "
		               "as a private file, or use a PNG, JPEG or WebP image.").format(what), UploadRefused)


class PublicFileGuard:
	"""File controller extension. Checks the names a new file may be stored under before File's
	own ``before_insert``, the final name right before the bytes are written, and the final URL
	when a file is created, made public or moved."""

	def before_insert(self):
		refuse_public(self, self.get("file_name"), self.get("file_url"))
		return super().before_insert()

	def save_file_on_filesystem(self):
		refuse_public(self, self.file_name, by_url=False)      # the name File settled on, just before writing
		return super().save_file_on_filesystem()

	def validate(self):
		if self.is_new():
			refuse_public(self, self.get("file_url"))
		elif self.has_value_changed("is_private") or self.has_value_changed("file_url"):
			# the flag decides here: the URL still names the private folder until File moves the file
			refuse_public(self, self.get("file_url"), self.get("file_name"), by_url=False)
		return super().validate()


def check_image(content: bytes) -> str:
	"""→ the image kind (``png`` …) of ``content``, or refuse it."""
	if not content:
		frappe.throw(_("The file is empty."), UploadRefused)
	if len(content) > ft.MAX_IMAGE_BYTES:
		frappe.throw(_("Images can be at most {0} MB.").format(ft.MAX_IMAGE_BYTES // (1024 * 1024)), UploadRefused)
	kind = ft.sniff_image(content)
	if not kind:
		frappe.throw(_("Upload a PNG, JPEG, GIF or WebP image. SVG and other files are not accepted."), UploadRefused)
	from PIL import Image, ImageFile

	unreadable = _("The image could not be read whole. Save it again as PNG, JPEG or WebP.")
	try:
		with Image.open(io.BytesIO(content)) as img:
			width, height = img.size
			fmt = (img.format or "").lower()
	except Exception:
		frappe.throw(unreadable, UploadRefused)
	if fmt == "mpo":
		fmt = "jpeg"                            # an iPhone's multi-picture JPEG: a JPEG, more frames after it
	if fmt != kind:
		frappe.throw(_("The file is not the image its first bytes announce. Save it again as PNG, JPEG or WebP."),
		             UploadRefused)
	if not (0 < width <= ft.MAX_IMAGE_SIDE and 0 < height <= ft.MAX_IMAGE_SIDE):
		frappe.throw(_("Images can be at most {0} pixels wide and high.").format(ft.MAX_IMAGE_SIDE), UploadRefused)
	# decode every frame: Frappe lets Pillow fill a cut image in (LOAD_TRUNCATED_IMAGES), an upload
	# must be whole. Pillow's verify() only checks PNG; JPEG, GIF and WebP need a real decode.
	truncated = ImageFile.LOAD_TRUNCATED_IMAGES
	ImageFile.LOAD_TRUNCATED_IMAGES = False
	try:
		with Image.open(io.BytesIO(content)) as img:
			for frame in range(min(getattr(img, "n_frames", 1), 500)):
				img.seek(frame)
				img.load()
	except Exception:
		frappe.throw(unreadable, UploadRefused)
	finally:
		ImageFile.LOAD_TRUNCATED_IMAGES = truncated
	return kind


def save_public_image(filename: str | None, content: bytes, *, attached_to: tuple[str, str] | None = None) -> dict:
	"""Store a checked image in the public folder (a booking site shows it to anonymous guests)."""
	kind = check_image(content)
	stem = re.sub(r"[^A-Za-z0-9_-]+", "-", (filename or "").rsplit(".", 1)[0]).strip("-")[:60] or "image"
	doc = frappe.get_doc({
		"doctype": "File", "file_name": f"{stem}.{ft.IMAGE_EXTENSIONS[kind]}", "content": content, "is_private": 0,
		"folder": "Home", "attached_to_doctype": attached_to[0] if attached_to else None,
		"attached_to_name": attached_to[1] if attached_to else None,
	})
	doc.insert(ignore_permissions=True)
	return {"file_url": doc.file_url, "file_name": doc.file_name, "name": doc.name}
