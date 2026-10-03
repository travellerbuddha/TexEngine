"""LO-44 (Part 2K-6): the DocType specs (``kamra/tex/devtools/doctype_specs.py``) are what the committed DocType
JSON is generated from (``doctype_gen.write_all``). A spec whose ``modified`` stamp is older than its JSON's would
move the JSON's stamp back on the next generation (Frappe then skips the DocType on migrate), and a spec that
lacks a field added to the JSON alone would drop that field. No bench: the specs and the JSON files are read
as they are."""

from __future__ import annotations

import json
import unittest

from kamra.tex.devtools import doctype_specs
from kamra.tex.devtools.doctype_gen import APP, scrub


def committed(spec: dict) -> dict:
	path = APP / scrub(spec["module"]) / "doctype" / scrub(spec["name"]) / f"{scrub(spec['name'])}.json"
	return json.loads(path.read_text())


class TestDoctypeSpecs(unittest.TestCase):
	def test_every_spec_is_stamped_at_least_as_late_as_its_json(self):
		behind = {s["name"]: (s["modified"], committed(s)["modified"]) for s in doctype_specs.SPECS
		          if s["modified"] < committed(s)["modified"]}
		self.assertEqual(behind, {})

	def test_every_spec_generates_its_committed_json(self):
		drift = {}
		for s in doctype_specs.SPECS:
			j = committed(s)
			keys = sorted(k for k in set(s) | set(j) if k != "modified" and s.get(k) != j.get(k))
			if keys:
				only_json = sorted({f["fieldname"] for f in j.get("fields", [])} - {f["fieldname"] for f in s["fields"]})
				drift[s["name"]] = (keys, only_json)
		self.assertEqual(drift, {})


if __name__ == "__main__":
	unittest.main()
