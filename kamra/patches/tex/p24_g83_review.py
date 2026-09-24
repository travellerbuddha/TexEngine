"""G-83 review follow-up (ADR-046). Nothing sensitive is printed: only counts.

1. Public files the public folder may no longer serve (``filetypes.may_be_public``):
   - HTML, XHTML and script files are made private (File moves them; a TEX hotel never
     serves them publicly, and they are the direct script-injection risk);
   - every other one (SVG logos, XML, unknown types) may still be shown by a page, so it is
     only reported: one ``file.public_active_content`` audit entry each, for the owner to
     replace or make private.
2. Booking sites whose logo or hero image the rules no longer accept are reported
   (``booking_site.invalid_image``). They stay savable: only a changed image is judged.
3. ``TEX Payment Provider Account.api_key`` was a Data field with change tracking, so the
   change history (Version) kept plain keys. They are masked; since p22 the field is a
   Password, whose changes reach the history only as asterisks.

Each report is audited once: a re-run writes an entry only for what changed since (G-76).
"""

import json

import frappe

from kamra.tex.security import filetypes as ft
from kamra.tex.security.audit import audit, log_exception, recorded

PRIVATISE = frozenset({"html", "htm", "xhtml", "xht", "shtml", "js", "mjs", "hta", "swf"})
ACCOUNT = "TEX Payment Provider Account"
MASK = "*****"


def _public_files() -> tuple[int, int]:
	privatised = reported = 0
	for f in frappe.get_all("File", filters={"is_private": 0, "is_folder": 0},
	                        fields=["name", "file_name", "file_url", "attached_to_doctype", "attached_to_name"]):
		url = f.file_url or ""
		if url.startswith(("http://", "https://")) or (ft.may_be_public(f.file_name) and ft.may_be_public(url)):
			continue
		exts = {ft.extension(n) for n in ft.served_names(url) | ft.served_names(f.file_name)}
		if exts & PRIVATISE:
			try:
				doc = frappe.get_doc("File", f.name)
				doc.is_private = 1
				doc.save(ignore_permissions=True)
				audit("file.privatised", reference_doctype="File", reference_name=f.name, source="System",
				      new={"file_url": doc.file_url}, reason="public HTML/script file made private (G-83)")
				privatised += 1
				continue
			except Exception:
				log_exception(f"TEX p24: could not make {f.name} private")
		new = {"file_url": url, "attached_to": [f.attached_to_doctype, f.attached_to_name]}
		if not recorded("file.public_active_content", reference_doctype="File", reference_name=f.name, new=new):
			audit("file.public_active_content", reference_doctype="File", reference_name=f.name, source="System",
			      new=new, reason="the public folder may no longer serve this type: replace it or make it private (G-83)")
		reported += 1
	return privatised, reported


def _site_images() -> int:
	from kamra.tex.services import sites

	own, n = sites.own_hosts(), 0
	for s in frappe.get_all("TEX Booking Site", fields=["name", "property", "logo", "hero_image"]):
		bad = [f for f in ("logo", "hero_image") if s.get(f) and not ft.safe_image_url(s.get(f), own)]
		if bad:
			new = {f: s.get(f) for f in bad}
			if not recorded("booking_site.invalid_image", reference_doctype="TEX Booking Site", reference_name=s.name,
			                new=new):
				audit("booking_site.invalid_image", reference_doctype="TEX Booking Site", reference_name=s.name,
				      property=s.property, source="System", new=new,
				      reason="replace with an uploaded PNG, JPEG, GIF or WebP image (G-83); the site stays savable")
			n += 1
	return n


def _versioned_keys() -> int:
	n = 0
	for v in frappe.get_all("Version", filters={"ref_doctype": ACCOUNT}, fields=["name", "data"]):
		try:
			data = json.loads(v.data or "{}")
		except ValueError:
			continue
		changed = False
		for row in data.get("changed") or []:
			if isinstance(row, list) and len(row) >= 3 and row[0] == "api_key":
				for i in (1, 2):
					if row[i] and set(str(row[i])) != {"*"}:
						row[i] = MASK
						changed = True
		if changed:
			frappe.db.set_value("Version", v.name, "data", json.dumps(data, indent=1, sort_keys=True, default=str),
			                    update_modified=False)
			n += 1
	return n


def execute():
	privatised, reported = _public_files()
	sites = _site_images()
	versions = _versioned_keys()
	print(f"TEX G-83 review: {privatised} public HTML/script file(s) made private, {reported} other public "
	      f"file(s) reported, {sites} booking site(s) with an image to replace, {versions} change-history "
	      f"row(s) with an API key masked")
