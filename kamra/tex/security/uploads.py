"""Server-side upload checks (G-83, R-53). The browser's checks are a convenience only.

- ``save_public_image``: the TEX booking-site image upload. The bytes must be a PNG, JPEG,
  GIF or WebP image that decodes, at most 2 MB and 8000 px a side; the stored name takes the
  extension of what the bytes are, never of what the name claims.
- ``PublicFileGuard``: mixed into Frappe's File (``hooks.extend_doctype_class``) so that no
  path (``upload_file``, Desk attachments, legacy screens, code) puts HTML, SVG, XML or
  script into the public folder, where it would run in the platform's origin. It runs before
  File writes anything to disk. Such files may still be stored private (Frappe serves those
  as downloads) but never made public later.
"""

from __future__ import annotations

import io
import re

import frappe
from frappe import _

from kamra.tex.security import filetypes as ft


class UploadRefused(frappe.ValidationError):
	pass


def _refuse_active(doc) -> None:
	if doc.get("is_folder") or int(doc.get("is_private") or 0):
		return
	for name in (doc.get("file_name"), doc.get("file_url")):
		if name and not str(name).startswith(("http://", "https://")) and ft.is_active_name(name):
			frappe.throw(_("{0} files cannot be public: HTML, SVG, XML and script files would run in this "
			               "site's pages. Upload it as a private file, or as a PNG, JPEG or WebP image.").format(
				ft.extension(name).upper()), UploadRefused)


class PublicFileGuard:
	"""File controller extension: the checks run before File's own ``before_insert``
	(which writes the content to disk) and before a private file is made public."""

	def before_insert(self):
		_refuse_active(self)
		return super().before_insert()

	def validate(self):
		if not self.is_new() and self.has_value_changed("is_private"):
			_refuse_active(self)
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
	from PIL import Image

	try:
		with Image.open(io.BytesIO(content)) as img:
			width, height = img.size
			fmt = (img.format or "").lower()
			img.verify()                          # the whole image decodes, not just its header
	except Exception:
		frappe.throw(_("The image could not be read. Save it again as PNG, JPEG or WebP."), UploadRefused)
	if fmt != kind or not (0 < width <= ft.MAX_IMAGE_SIDE and 0 < height <= ft.MAX_IMAGE_SIDE):
		frappe.throw(_("Images can be at most {0} pixels wide and high.").format(ft.MAX_IMAGE_SIDE), UploadRefused)
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
