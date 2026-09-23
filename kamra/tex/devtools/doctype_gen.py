"""Generator for TEX DocType JSON files (dev tool, not imported at runtime).

    python -m kamra.tex.devtools.doctype_gen          # (re)write all TEX DocTypes

Specs live in ``kamra/tex/devtools/doctype_specs.py``. JSON is always rewritten
from the spec; controller ``.py`` files are created only when missing, so
hand-written controller logic is never overwritten.
"""

from __future__ import annotations

import json
import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[2]      # …/kamra (python package)
TIMESTAMP = "2026-09-23 14:00:00.000000"

LAYOUT = {"Section Break", "Column Break", "Tab Break"}


def scrub(name: str) -> str:
	return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def classname(name: str) -> str:
	return name.replace(" ", "").replace("-", "")


def F(fieldname, fieldtype, label=None, options=None, **props):
	d = {"fieldname": fieldname, "fieldtype": fieldtype}
	if label:
		d["label"] = label
	if options is not None:
		d["options"] = "\n".join(options) if isinstance(options, list | tuple) else options
	d.update(props)
	return d


_sb = 0


def SB(label=None, **props):
	global _sb
	_sb += 1
	return F(f"section_{_sb}", "Section Break", label, **props)


def CB():
	global _sb
	_sb += 1
	return F(f"column_{_sb}", "Column Break")


def TAB(label):
	global _sb
	_sb += 1
	return F(f"tab_{_sb}", "Tab Break", label)


def perm(role, level="read", **extra):
	base = {"role": role, "read": 1, "report": 1, "print": 1, "email": 1}
	if level in ("write", "full"):
		base.update({"write": 1, "create": 1})
	if level == "full":
		base.update({"delete": 1, "export": 1, "share": 1})
	if level == "readonly":
		base = {"role": role, "read": 1, "report": 1}
	base.update(extra)
	return base


def dt(name, module, fields, *, perms=(), autoname=None, istable=False, issingle=False, title_field=None,
       track_changes=True, search_fields=None, sort_field="modified", description=None, is_submittable=False,
       quick_entry=False, naming_rule=None, in_create=False, extra=None):
	fields = [dict(f) for f in fields]
	for f in fields:
		if f["fieldtype"] in ("Currency",) and "options" not in f:
			pass
	d = {
		"actions": [],
		"creation": TIMESTAMP,
		"doctype": "DocType",
		"editable_grid": 1,
		"engine": "InnoDB",
		"field_order": [f["fieldname"] for f in fields],
		"fields": fields,
		"links": [],
		"modified": TIMESTAMP,
		"modified_by": "Administrator",
		"module": module,
		"name": name,
		"owner": "Administrator",
		"permissions": [] if istable else list(perms),
		"sort_field": sort_field,
		"sort_order": "DESC",
		"states": [],
		"row_format": "Dynamic",
	}
	if autoname:
		d["autoname"] = autoname
	if naming_rule:
		d["naming_rule"] = naming_rule
	if istable:
		d["istable"] = 1
	if issingle:
		d["issingle"] = 1
	if title_field:
		d["title_field"] = title_field
		d["show_title_field_in_link"] = 1
	if track_changes and not istable:
		d["track_changes"] = 1
	if search_fields:
		d["search_fields"] = search_fields
	if description:
		d["description"] = description
	if is_submittable:
		d["is_submittable"] = 1
	if quick_entry:
		d["quick_entry"] = 1
	if in_create:
		d["in_create"] = 1
	if extra:
		d.update(extra)
	return d


CONTROLLER = '''# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

from frappe.model.document import Document


class {cls}(Document):
	pass
'''


def write_all(specs) -> list[str]:
	written = []
	modules = set()
	for d in specs:
		module_dir = APP / scrub(d["module"])
		modules.add(d["module"])
		(module_dir / "doctype").mkdir(parents=True, exist_ok=True)
		for init in (module_dir / "__init__.py", module_dir / "doctype" / "__init__.py"):
			if not init.exists():
				init.write_text("")
		folder = module_dir / "doctype" / scrub(d["name"])
		folder.mkdir(exist_ok=True)
		(folder / "__init__.py").touch()
		(folder / f"{scrub(d['name'])}.json").write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
		ctrl = folder / f"{scrub(d['name'])}.py"
		if not ctrl.exists():
			ctrl.write_text(CONTROLLER.format(cls=classname(d["name"])))
		written.append(d["name"])
	mod_file = APP / "modules.txt"
	current = [m for m in mod_file.read_text().splitlines() if m.strip()]
	for m in sorted(modules):
		if m not in current:
			current.append(m)
	mod_file.write_text("\n".join(current) + "\n")
	return written


if __name__ == "__main__":
	from kamra.tex.devtools.doctype_specs import SPECS

	names = write_all(SPECS)
	print(f"wrote {len(names)} DocTypes")
