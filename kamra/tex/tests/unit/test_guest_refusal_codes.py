"""Guest refusal codes (G-70a, audit Part 2G-2; ADR-013 amendment): the pure registry and the guest API's
transport. Every guest endpoint of ``kamra/tex/api/public.py`` copies a refusal's stable code into the
error body (``refusals.coded``), between its rate limit and its deadlock retry. No bench needed."""

import ast
import pathlib
import re
import unittest

from kamra.tex import refusal_codes

PUBLIC = pathlib.Path(__file__).resolve().parents[2] / "api" / "public.py"


def _name(node: ast.AST) -> str:
	"""``a.b.c`` of a decorator (a call's function)."""
	if isinstance(node, ast.Call):
		node = node.func
	if isinstance(node, ast.Attribute):
		return f"{_name(node.value)}.{node.attr}"
	return node.id if isinstance(node, ast.Name) else ""


def _guest_endpoints() -> dict[str, list[str]]:
	"""Every ``@frappe.whitelist(allow_guest=True, …)`` function of public.py → its decorator names, outermost
	first."""
	tree = ast.parse(PUBLIC.read_text(encoding="utf-8"))
	out = {}
	for fn in tree.body:
		if not isinstance(fn, ast.FunctionDef):
			continue
		for d in fn.decorator_list:
			if _name(d) == "frappe.whitelist" and isinstance(d, ast.Call) and any(
					k.arg == "allow_guest" and isinstance(k.value, ast.Constant) and k.value.value is True
					for k in d.keywords):
				out[fn.name] = [_name(x) for x in fn.decorator_list]
	return out


class TestRegistry(unittest.TestCase):
	def test_codes_are_upper_snake_and_listed_once(self):
		self.assertEqual(len(refusal_codes.ORDERED), len(set(refusal_codes.ORDERED)),
		                 [c for c in refusal_codes.ORDERED if refusal_codes.ORDERED.count(c) > 1])
		self.assertEqual(refusal_codes.CODES, frozenset(refusal_codes.ORDERED))
		bad = [c for c in refusal_codes.CODES if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", c)]
		self.assertEqual(bad, [])

	def test_the_fallback_codes_and_the_market_codes_are_registered(self):
		# what ``refusals.coded`` gives an uncoded 404 / 403 / 429, and the market codes O-8 and G-55b use
		for code in ("NOT_FOUND", "NOT_PERMITTED", "RATE_LIMITED", "MARKET_UNKNOWN", "MARKET_AMBIGUOUS",
		             "MARKET_REQUIRED", "MARKET_NOT_ALLOWED", "MARKET_RESIDENCY", "CONTRACT_NOT_ON_SALE",
		             "CONTRACT_SUSPENDED"):
			self.assertIn(code, refusal_codes.CODES)

	def test_the_registry_is_pure(self):
		tree = ast.parse(pathlib.Path(refusal_codes.__file__).read_text(encoding="utf-8"))
		imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {
			(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
		self.assertNotIn("frappe", imported)


class TestGuestEndpointsAreCoded(unittest.TestCase):
	def test_every_guest_endpoint_puts_its_refusal_code_in_the_error_body(self):
		endpoints = _guest_endpoints()
		self.assertGreaterEqual(len(endpoints), 20)                  # the guest API of public.py (HANDOFF_STAGE3 §1.1)
		missing = sorted(n for n, decorators in endpoints.items() if "refusals.coded" not in decorators)
		self.assertEqual(missing, [], "a guest endpoint without @refusals.coded")

	def test_the_code_is_taken_inside_the_rate_limit_and_outside_the_deadlock_retry(self):
		"""Inside ``rate_limit`` (a limited caller is answered by Frappe), outside ``retry_on_deadlock`` (the code is
		the final answer's, the "very busy" one included)."""
		for name, decorators in _guest_endpoints().items():
			coded = decorators.index("refusals.coded")
			self.assertEqual(decorators[coded - 1], "rate_limit", name)
			if "retry_on_deadlock" in decorators:
				self.assertEqual(decorators.index("retry_on_deadlock"), coded + 1, name)
