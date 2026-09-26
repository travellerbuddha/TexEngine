"""NEW-1 guard (ADR-064): a comparison on a nullable Date/Datetime field says what NULL means.

Frappe reads NULL in such a comparison two different ways, and neither is written in the code:

* ``frappe.get_all`` / ``get_list`` (and ``frappe.db.get_all`` / ``get_list``) compare
  ``IFNULL(field, '0001-01-01')`` for ``<`` and ``<=``: a row with no date is "before
  everything". ``{"active_to": ("<=", now)}`` therefore picks every version without an end
  (NEW-1: the roll superseded every live version). ``>`` / ``>=`` leave NULL out.
* ``frappe.db.get_value`` / ``get_values`` / ``count`` / ``exists`` / ``delete`` / ``set_value``
  with filters and ``frappe.qb.get_query`` (and query-builder comparisons) use plain SQL: NULL
  matches no comparison at all.

So every such filter in TEX says what NULL means, in the same call: ``[field, "is", "set"]`` or
``[field, "is", "not set"]`` in its filters, or the field with ``is`` in its ``or_filters`` (an
explicit OR); a query-builder comparison has ``.isnull()`` / ``.notnull()`` on the same column in
the same function. Otherwise it needs a reviewed ``ALLOWED`` entry with its reason.

What this guard covers:
* every ``*.py`` under ``kamra/`` except tests;
* the calls named above, with the doctype a string literal or a string constant (module level or in
  the function) and the filters a literal, or a local name built in the same function from
  literals (assignment, ``x[field] = ...``, ``append`` / ``extend`` / ``update``, ``**`` unpacking,
  ``a if c else b``);
* dict filters, ``[field, op, value]`` and ``[doctype, field, op, value]`` lists, ``or_filters``;
* query-builder comparisons ``T.field <op> value`` where ``T = frappe.qb.DocType(<doctype>)`` in
  the same function or at module level, one name or a tuple (``E, S = DocType(a), DocType(b)``), or
  ``frappe.qb.DocType(<doctype>).field`` written in place;
* a field is nullable when its DocType JSON in this repository gives it type Date or Datetime and
  neither ``reqd`` nor ``not_nullable``; ``creation`` / ``modified`` are never NULL.

What it cannot read, it lists (``Unread``), and ``test_nothing_unreadable_is_left_out`` is red for
each until it is made readable or given a reviewed ``UNREADABLE`` entry with its reason:
* one of the calls above whose filters it cannot read while what builds them holds a comparison
  operator (a filter from a parameter or a helper, a comprehension);
* a ``frappe.qb.DocType(...)`` table whose doctype it cannot read, compared with ``<``/``<=``/``>``/``>=``.

What it does not cover (it cannot tell, so it says nothing):
* raw SQL (``frappe.db.sql``): plain SQL semantics, NULL matches no comparison;
* doctypes whose JSON is not in this repository (Frappe core: Error Log, Email Queue, …) and
  custom fields added to them at install;
* a call whose doctype is computed at run time (a parameter, a helper's return value);
  ``test_resolution_is_not_silently_empty`` checks that the scanner does resolve the known calls;
* other APIs (``frappe.get_doc(dt, filters)``, reports), query-builder columns read by subscript
  (``T["field"]``) or through ``Field``/``Criterion`` objects, and tables passed in as arguments.
"""

from __future__ import annotations

import ast
import json
import pathlib
import unittest
from dataclasses import dataclass

APP = pathlib.Path(__file__).resolve().parents[3]            # the ``kamra`` package
REPO = APP.parent

# IFNULL(field, '0001-01-01') for < and <=: NULL is "before everything"
LIST_APIS = {"frappe.get_all", "frappe.get_list", "frappe.db.get_all", "frappe.db.get_list"}
# plain SQL: NULL matches no comparison
QB_APIS = {"frappe.db.get_value", "frappe.db.get_values", "frappe.db.count", "frappe.db.exists",
           "frappe.db.delete", "frappe.db.set_value", "frappe.qb.get_query", "frappe.get_value"}
COMPARISONS = {"<", "<=", ">", ">="}
QB_OPS = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}
QB_NULL_CHECKS = {"isnull", "notnull", "isnotnull"}

# (path under the repo, function, doctype, field) -> why the implicit NULL reading is left there
ALLOWED: dict[tuple[str, str, str, str], str] = {
	("kamra/housekeeping.py", "escalate_overdue_tasks", "Housekeeping Task", "due_by"):
		"legacy Kamra PMS housekeeping, not a TEX flow (kept, hidden from TEX). get_all reads a task without "
		"due_by as overdue and escalates it: reported in the Part 2A remainder, not changed here",
	("kamra/laundry.py", "laundry_revenue", "Laundry Order", "delivered_at"):
		"legacy Kamra PMS laundry report, not a TEX flow. >= leaves an order without a delivery time out of "
		"the window, which is right: its revenue has no day to fall on",
}
# (path under the repo, function, what) -> why a call the scanner cannot read is safe (reviewed)
UNREADABLE: dict[tuple[str, str, str], str] = {}


def doctype_fields() -> dict[str, dict[str, dict]]:
	out: dict[str, dict[str, dict]] = {}
	for path in APP.glob("**/doctype/*/*.json"):
		try:
			data = json.loads(path.read_text())
		except ValueError:
			continue
		if isinstance(data, dict) and data.get("doctype") == "DocType" and data.get("name"):
			out[data["name"]] = {f["fieldname"]: f for f in data.get("fields") or [] if f.get("fieldname")}
	return out


def nullable_date(fields: dict[str, dict[str, dict]], doctype: str | None, field: str) -> bool:
	if not doctype or field in ("creation", "modified"):
		return False
	df = fields.get(doctype, {}).get(field)
	return bool(df) and df.get("fieldtype") in ("Date", "Datetime") and not df.get("reqd") \
		and not df.get("not_nullable")


def dotted(node) -> str:
	parts = []
	while isinstance(node, ast.Attribute):
		parts.append(node.attr)
		node = node.value
	if isinstance(node, ast.Name):
		parts.append(node.id)
		return ".".join(reversed(parts))
	return ""


def is_qb_table(node) -> bool:
	return isinstance(node, ast.Call) and dotted(node.func) in ("frappe.qb.DocType", "DocType") and bool(node.args)


def text(node) -> str | None:
	return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


@dataclass
class Cond:
	doctype: str | None          # a [doctype, field, op, value] row names its own (child) doctype
	field: str
	op: str


@dataclass
class Unread:
	"""A call or query-builder table the scanner could not read while a comparison is in play."""
	path: str
	function: str
	line: int
	what: str

	@property
	def key(self):
		return (self.path, self.function, self.what)

	def __str__(self):
		return f"{self.path}:{self.line} {self.function}: {self.what} cannot be read"


@dataclass
class Finding:
	path: str
	function: str
	line: int
	api: str
	doctype: str
	field: str
	op: str

	@property
	def key(self):
		return (self.path, self.function, self.doctype, self.field)

	def __str__(self):
		if self.api not in LIST_APIS:
			reading = "plain SQL: a row without the date never matches"
		elif self.op in ("<", "<="):
			reading = "get_all reads NULL as 0001-01-01: a row without the date matches"
		else:
			reading = "get_all: a row without the date never matches"

		return (f"{self.path}:{self.line} {self.function}: {self.api}({self.doctype!r}) "
		        f"{self.field} {self.op} …  [{reading}]")


class Scope:
	"""What a function (or the module) assigns: string constants, filter literals, qb tables."""

	def __init__(self, body, parent: Scope | None = None):
		self.parent = parent
		self.strings: dict[str, str] = {}
		self.values: dict[str, list] = {}           # name -> every expression that builds it
		self.tables: dict[str, str] = {}             # name -> doctype of frappe.qb.DocType(...)
		self.unknown_tables: dict[str, str] = {}     # name -> the DocType(...) argument it cannot read
		for node in body:
			for sub in ast.walk(node) if parent else [node]:
				self._note(sub)

	def _note(self, node):
		if isinstance(node, ast.Assign):
			for target in node.targets:
				if isinstance(target, ast.Name):
					self._assign(target.id, node.value)
				elif isinstance(target, ast.Tuple | ast.List) and isinstance(node.value, ast.Tuple | ast.List) \
						and len(target.elts) == len(node.value.elts):
					for name, value in zip(target.elts, node.value.elts, strict=True):  # E, S = DocType(a), DocType(b)
						if isinstance(name, ast.Name):
							self._assign(name.id, value)
				elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
					key = text(target.slice)
					if key is not None:
						self.values.setdefault(target.value.id, []).append(
							ast.Dict(keys=[ast.Constant(key)], values=[node.value]))
		elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
			self._assign(node.target.id, node.value)
		elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
			self.values.setdefault(node.target.id, []).append(node.value)
		elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
				and isinstance(node.func.value, ast.Name) and node.args:
			name, method = node.func.value.id, node.func.attr
			if method == "append":
				self.values.setdefault(name, []).append(ast.List(elts=[node.args[0]]))
			elif method in ("extend", "update"):
				self.values.setdefault(name, []).append(node.args[0])

	def _assign(self, name: str, value):
		if (s := text(value)) is not None:
			self.strings[name] = s
		elif is_qb_table(value):
			if (dt := self.string(value.args[0])) is not None:
				self.tables[name] = dt
			else:
				self.unknown_tables[name] = ast.unparse(value.args[0])
		self.values.setdefault(name, []).append(value)

	def string(self, node) -> str | None:
		if (s := text(node)) is not None:
			return s
		if isinstance(node, ast.Name):
			scope = self
			while scope:
				if node.id in scope.strings:
					return scope.strings[node.id]
				scope = scope.parent
		return None

	def table(self, name: str) -> str | None:
		scope = self
		while scope:
			if name in scope.tables:
				return scope.tables[name]
			scope = scope.parent
		return None

	def unknown_table(self, name: str) -> str | None:
		scope = self
		while scope:
			if name in scope.unknown_tables:
				return scope.unknown_tables[name]
			scope = scope.parent
		return None

	def builds(self, name: str) -> list:
		scope = self
		while scope:
			if name in scope.values:
				return scope.values[name]
			scope = scope.parent
		return []


def conditions(node, scope: Scope, seen: frozenset = frozenset()) -> list[Cond] | None:
	"""The filter rows a filters expression holds; None when it cannot be read statically."""
	if isinstance(node, ast.Dict):
		out = []
		for key, value in zip(node.keys, node.values, strict=True):
			if key is None:                                            # {**base, ...}
				more = conditions(value, scope, seen)
				if more is None:
					return None
				out += more
				continue
			op = "="
			if isinstance(value, ast.Tuple | ast.List) and value.elts and text(value.elts[0]) is not None:
				op = text(value.elts[0]).lower()
			field = scope.string(key)
			if field is None:
				if op in COMPARISONS or op == "is":
					return None
				continue                                               # {name: value}: an equality
			out.append(Cond(None, field, op))
		return out
	if isinstance(node, ast.Call) and dotted(node.func) == "dict":     # dict(base, field=(op, v))
		out = []
		for arg in node.args:
			more = conditions(arg, scope, seen)
			if more is None:
				return None
			out += more
		keys = [ast.Constant(kw.arg) if kw.arg else None for kw in node.keywords]
		more = conditions(ast.Dict(keys=keys, values=[kw.value for kw in node.keywords]), scope, seen)
		return None if more is None else out + more
	if isinstance(node, ast.List | ast.Tuple):
		out = []
		for row in node.elts:
			if isinstance(row, ast.List | ast.Tuple) and len(row.elts) in (3, 4):
				doctype = scope.string(row.elts[0]) if len(row.elts) == 4 else None
				field, op = scope.string(row.elts[-3]), text(row.elts[-2])
				if op is None:
					return None
				if field is None:
					if op.lower() in COMPARISONS or op.lower() == "is":
						return None
					continue                                           # [name, "=", value]: an equality
				out.append(Cond(doctype, field, op.lower()))
			elif isinstance(row, ast.Dict | ast.Name):
				more = conditions(row, scope, seen)
				if more is None:
					return None
				out += more
			elif isinstance(row, ast.Starred):
				more = conditions(row.value, scope, seen)
				if more is None:
					return None
				out += more
			else:
				return None
		return out
	if isinstance(node, ast.IfExp):
		a, b = conditions(node.body, scope, seen), conditions(node.orelse, scope, seen)
		return None if a is None or b is None else a + b
	if isinstance(node, ast.Constant) and node.value is None:
		return []
	if isinstance(node, ast.Name) and node.id not in seen:
		builds = scope.builds(node.id)
		if not builds:
			return None
		out = []
		for value in builds:
			more = conditions(value, scope, seen | {node.id})
			if more is None:
				return None
			out += more
		return out
	return None


def _arg(call: ast.Call, index: int, *names: str):
	for kw in call.keywords:
		if kw.arg in names:
			return kw.value
	return call.args[index] if len(call.args) > index else None


class Scanner(ast.NodeVisitor):
	def __init__(self, path: str, tree: ast.Module, fields):
		self.path, self.fields = path, fields
		self.module = Scope(tree.body)
		self.scope, self.function = self.module, "<module>"
		self.findings: list[Finding] = []
		self.resolved = 0                          # calls whose doctype and filters were read
		self.unresolved: list[Unread] = []

	def visit_FunctionDef(self, node):
		outer = (self.scope, self.function)
		self.scope = Scope(node.body, parent=self.module)
		self.function = node.name if outer[1] == "<module>" else f"{outer[1]}.{node.name}"
		self._qb(node)
		self.generic_visit(node)
		self.scope, self.function = outer

	visit_AsyncFunctionDef = visit_FunctionDef

	def visit_ClassDef(self, node):
		outer = self.function
		self.function = node.name if outer == "<module>" else f"{outer}.{node.name}"
		self.generic_visit(node)
		self.function = outer

	def visit_Call(self, node):
		api = dotted(node.func)
		if api in LIST_APIS or api in QB_APIS:
			self._call(api, node)
		self.generic_visit(node)

	def _call(self, api: str, call: ast.Call):
		doctype = self.scope.string(_arg(call, 0, "doctype", "dt", "table"))
		if doctype is None:
			return
		if api in LIST_APIS:
			filters = _arg(call, 999, "filters")
			if filters is None and len(call.args) > 1 and self._filters_shaped(call.args[1]):
				filters = call.args[1]                 # get_all(dt, {…}) / get_all(dt, [[…]]) reads it as filters
			groups = [filters, _arg(call, 999, "or_filters")]
		else:
			filters = _arg(call, 1, "filters", "dn", "name")
			groups = [filters]
		rows: list[Cond] = []
		for group in groups:
			if group is None:
				continue
			more = conditions(group, self.scope)
			if more is None:
				# not readable here (a parameter, a document name, a computed filter): listed when what
				# builds it holds a comparison operator
				if self._holds_comparison(group):
					what = f"{api}({ast.unparse(_arg(call, 0, 'doctype', 'dt', 'table'))})"
					self.unresolved.append(Unread(self.path, self.function, call.lineno, what))
				return
			rows += more
		self.resolved += 1
		explicit = {(c.doctype or doctype, c.field) for c in rows if c.op == "is"}
		for c in rows:
			dt = c.doctype or doctype
			if c.op in COMPARISONS and nullable_date(self.fields, dt, c.field) and (dt, c.field) not in explicit:
				self.findings.append(Finding(self.path, self.function, call.lineno, api, dt, c.field, c.op))

	def _holds_comparison(self, node, seen: frozenset = frozenset()) -> bool:
		for sub in ast.walk(node):
			if isinstance(sub, ast.Constant) and sub.value in COMPARISONS:
				return True
			if isinstance(sub, ast.Name) and sub.id not in seen:
				if any(self._holds_comparison(b, seen | {sub.id}) for b in self.scope.builds(sub.id)):
					return True
		return False

	def _filters_shaped(self, node) -> bool:
		"""Frappe's get_all(dt, x): x is filters when it is a dict or a list of rows, else fields."""
		for value in ([node] if not isinstance(node, ast.Name) else self.scope.builds(node.id)):
			if isinstance(value, ast.Dict):
				return True
			if isinstance(value, ast.List | ast.Tuple) and value.elts \
					and isinstance(value.elts[0], ast.List | ast.Tuple):
				return True
		return False

	def _qb(self, fn):
		"""Query-builder comparisons ``T.field <op> x`` on a ``frappe.qb.DocType`` table."""
		checked = set()
		compares = []
		for node in ast.walk(fn):
			if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
					and node.func.attr in QB_NULL_CHECKS and isinstance(node.func.value, ast.Attribute) \
					and isinstance(node.func.value.value, ast.Name):
				checked.add((node.func.value.value.id, node.func.value.attr))
			elif isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in QB_OPS:
				compares.append(node)
		for node in compares:
			for side in (node.left, node.comparators[0]):
				if not isinstance(side, ast.Attribute):
					continue
				if is_qb_table(side.value):                                # frappe.qb.DocType("X").field < y
					doctype, key = self.scope.string(side.value.args[0]), None
					if doctype is None:
						self.unresolved.append(Unread(self.path, self.function, node.lineno,
						                              f"frappe.qb.DocType({ast.unparse(side.value.args[0])})"))
						continue
				elif isinstance(side.value, ast.Name):
					doctype, key = self.scope.table(side.value.id), (side.value.id, side.attr)
					if doctype is None and (unknown := self.scope.unknown_table(side.value.id)) is not None:
						self.unresolved.append(Unread(self.path, self.function, node.lineno,
						                              f"frappe.qb.DocType({unknown})"))
						continue
				else:
					continue
				if doctype and nullable_date(self.fields, doctype, side.attr) and key not in checked:
					self.findings.append(Finding(self.path, self.function, node.lineno, "frappe.qb",
					                             doctype, side.attr, QB_OPS[type(node.ops[0])]))


def scan() -> tuple[list[Finding], int, list[Unread]]:
	fields = doctype_fields()
	findings, resolved, unresolved = [], 0, []
	for path in sorted(APP.rglob("*.py")):
		rel = path.relative_to(REPO).as_posix()
		if "/tests/" in rel or path.name.startswith("test_") or "/node_modules/" in rel:
			continue
		tree = ast.parse(path.read_text(), filename=rel)
		scanner = Scanner(rel, tree, fields)
		scanner.visit(tree)
		findings += {(f.line, f.doctype, f.field, f.op): f for f in scanner.findings}.values()
		resolved += scanner.resolved
		unresolved += {(u.line, u.what): u for u in scanner.unresolved}.values()
	return findings, resolved, unresolved


class TestNullableDateFilters(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.findings, cls.resolved, cls.unresolved = scan()

	def test_every_nullable_date_comparison_says_what_null_means(self):
		open_ = [f for f in self.findings if f.key not in ALLOWED]
		self.assertEqual(open_, [], "a comparison on a nullable Date/Datetime field must say what NULL means "
		                 "(add [field, 'is', 'set'|'not set'], an explicit OR, or a reviewed ALLOWED entry):\n"
		                 + "\n".join(map(str, open_)))

	def test_every_allowed_entry_is_still_needed_and_has_a_reason(self):
		keys = {f.key for f in self.findings}
		for key, reason in ALLOWED.items():
			self.assertIn(key, keys, f"stale ALLOWED entry: {key}")
			self.assertGreater(len(reason.strip()), 20, f"ALLOWED entry without a reason: {key}")

	def test_nothing_unreadable_is_left_out(self):
		# a call it cannot read never drops out of the guard in silence (review round 1)
		open_ = [u for u in self.unresolved if u.key not in UNREADABLE]
		self.assertEqual(open_, [], "the guard cannot read these; make them readable (literal filters, a "
		                 "frappe.qb.DocType of a string) or add a reviewed UNREADABLE entry with its reason:\n"
		                 + "\n".join(map(str, open_)))
		keys = {u.key for u in self.unresolved}
		for key, reason in UNREADABLE.items():
			self.assertIn(key, keys, f"stale UNREADABLE entry: {key}")
			self.assertGreater(len(reason.strip()), 20, f"UNREADABLE entry without a reason: {key}")

	def test_resolution_is_not_silently_empty(self):
		# the scanner reads the calls it claims to read: a broken resolver would pass everything
		self.assertGreater(self.resolved, 300)
		self.assertTrue(nullable_date(doctype_fields(), "TEX Contract Version", "active_to"))
		self.assertFalse(nullable_date(doctype_fields(), "TEX Contract Version", "creation"))

	def test_the_scanner_sees_what_it_must(self):
		# the NEW-1 shapes, each read as a finding; the explicit forms are not
		src = '''
import frappe
DT = "TEX Contract Version"
def roll(now):
	frappe.get_all(DT, filters={"status": "Published", "active_to": ("<=", now)})
def explicit(now):
	frappe.get_all(DT, filters=[["status", "=", "Published"], ["active_to", "is", "set"],
	                            ["active_to", "<=", now]])
def built(now):
	f = {"status": "Published"}
	f["active_to"] = ("<", now)
	return frappe.db.count(DT, f)
def either(now):
	return frappe.get_all(DT, filters={"status": "Published"},
	                      or_filters=[["active_to", "is", "not set"], ["active_to", ">", now]])
def qb(now):
	v = frappe.qb.DocType("TEX Contract Version")
	return frappe.qb.from_(v).select(v.name).where(v.active_to < now)
def qb_explicit(now):
	v = frappe.qb.DocType("TEX Contract Version")
	return frappe.qb.from_(v).select(v.name).where(v.active_to.isnull() | (v.active_to > now))
def qb_tuple(now):
	v, s = frappe.qb.DocType("TEX Contract Version"), frappe.qb.DocType("TEX Audit Scope")
	return frappe.qb.from_(v).select(v.name).where(v.active_to <= now)
def unreadable(now, more):
	return frappe.get_all(DT, filters=[["active_to", "<=", now], *more])
def qb_unknown(doctype, now):
	t = frappe.qb.DocType(doctype)
	return frappe.qb.from_(t).select(t.name).where(t.active_to < now)
'''
		tree = ast.parse(src)
		scanner = Scanner("probe.py", tree, doctype_fields())
		scanner.visit(tree)
		self.assertEqual(sorted((f.function, f.field, f.op) for f in scanner.findings),
		                 [("built", "active_to", "<"), ("qb", "active_to", "<"), ("qb_tuple", "active_to", "<="),
		                  ("roll", "active_to", "<=")])
		# what it cannot read, it lists: the guard is red for these until they are made readable or reviewed
		self.assertEqual(sorted((u.function, u.what) for u in scanner.unresolved),
		                 [("qb_unknown", "frappe.qb.DocType(doctype)"), ("unreadable", "frappe.get_all(DT)")])


if __name__ == "__main__":
	unittest.main()
