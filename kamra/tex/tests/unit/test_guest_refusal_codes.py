"""Guest refusal codes (G-70, audit Parts 2G-2 and 2G-3; ADR-013 amendment): the pure registry, the guest API's
transport and the coded refusals. Every guest endpoint of ``kamra/tex/api/public.py`` copies a refusal's stable
code into the error body (``refusals.coded``), between its rate limit and its deadlock retry; every refusal a guest
can meet carries a code (G-70b) and the booking app has a text for each. No bench needed."""

import ast
import json
import pathlib
import re
import unittest

from kamra.tex import refusal_codes

TEX = pathlib.Path(__file__).resolve().parents[2]
PUBLIC = TEX / "api" / "public.py"
BOOKING_CATALOG = TEX.parents[1] / "frontend" / "src" / "booking" / "i18n" / "en.json"

# the functions every guest endpoint reaches (HANDOFF_STAGE3 §5f, the inventory of guest-reachable refusals), by
# file: each of their ``frappe.throw`` and ``raise`` carries a refusal code. public.py is checked whole
GUEST_PATHS: dict[str, set[str]] = {
	"api/_util.py": {"parse"},
	"services/txn.py": {"retry_on_deadlock"},
	"services/quoting.py": {"verify", "require_fresh", "parse_dob", "checked_dob", "parse", "parse_rooms", "_dates",
	                        "search", "_json", "extra_items", "room_items", "_extras_list", "_on_sale", "_persist",
	                        "create_quotes", "quote_refusal"},
	"commercial/contracts.py": {"load_terms"},
	"services/booking.py": {"_clean_guest", "_fixed", "amount_due_now", "quotes_summary", "check_booking_basket",
	                        "create_booking", "_check_redemption_limits", "cancel_reservation"},
	"availability/extras_repository.py": {"check"},
	"services/holds.py": {"_expire_and_refuse", "open_attempt"},
	"payments/service.py": {"check_return_url", "_refuse", "_busy", "_refuse_in_review", "start_payment", "_supersede",
	                        "complete", "lock_link", "link_charge_key", "link_refusal", "link_by_token"},
	"services/guest_changes.py": {"guard", "guard_room", "submit", "_derive", "_not_made", "pay_again",
	                              "_start_payment"},
	"services/modification.py": {"_snapshot", "build_changed_request", "_resolve", "propose", "require_proposer",
	                             "apply"},
	"services/sold_terms.py": {"refuse"},
	"services/addons.py": {"_snapshot", "_open", "_requests", "apply"},
}
# what makes a raised exception coded: ``refusal(...)`` / ``with_code(...)`` / ``MarketRefused(code=…)``, or a
# class whose definition declares a registered ``code`` (checked below)
CODED_CALLS = {"refusal", "with_code", "MarketRefused"}
CODED_CLASSES = {"PaymentPending": "services/guest_changes.py", "RefundPending": "services/guest_changes.py",
                 "ChangeApplying": "services/guest_changes.py", "ChangeRefused": "services/guest_changes.py",
                 "CurrencyChanged": "services/guest_changes.py", "HoldExpired": "services/holds.py",
                 "PayloadMismatch": "commercial/contracts.py", "ContractNotOnSale": "commercial/contracts.py",
                 "ContractSuspended": "commercial/contracts.py", "AccountRefused": "payments/service.py",
                 "ChargeSuperseded": "payments/service.py", "PaymentBusy": "payments/service.py",
                 "ExtraSoldOut": "availability/extras_repository.py"}
# a value a helper returned coded: ``payments.link_refusal`` / ``quoting.quote_refusal`` (a Refusal),
# ``contracts.not_on_sale`` (a ContractNotOnSale)
CODED_VALUES = {"why", "stopped"}


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


def _last(node: ast.AST) -> str:
	return _name(node).rsplit(".", 1)[-1]


def _is_coded(node: ast.AST | None) -> bool:
	"""The exception expression of a ``frappe.throw`` or a ``raise`` carries a code."""
	if node is None:
		return False
	if isinstance(node, ast.IfExp):
		return _is_coded(node.body) and _is_coded(node.orelse)
	if isinstance(node, ast.Call):
		if _last(node.func) == "type" and node.args:                 # ``type(stopped)``: the class of a coded value
			return _is_coded(node.args[0])
		return _last(node.func) in CODED_CALLS | set(CODED_CLASSES)
	if isinstance(node, ast.Name) and node.id in CODED_VALUES:
		return True
	return _last(node) in CODED_CLASSES


def _uncoded(path: pathlib.Path, functions: set[str] | None) -> list[str]:
	"""``file:line function`` of every ``frappe.throw`` / ``raise X`` in ``functions`` (every function when None)
	whose exception has no code."""
	tree = ast.parse(path.read_text(encoding="utf-8"))
	out = []
	for fn in ast.walk(tree):
		if not isinstance(fn, ast.FunctionDef) or (functions is not None and fn.name not in functions):
			continue
		for n in ast.walk(fn):
			if isinstance(n, ast.Call) and _name(n.func) == "frappe.throw":
				exc = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "exc"), None)
				if not _is_coded(exc):
					out.append(f"{path.relative_to(TEX)}:{n.lineno} {fn.name}: {ast.unparse(n)[:90]}")
			elif isinstance(n, ast.Raise) and n.exc is not None and not _is_coded(n.exc):
				out.append(f"{path.relative_to(TEX)}:{n.lineno} {fn.name}: raise {ast.unparse(n.exc)[:80]}")
	return out


class TestEveryGuestRefusalIsCoded(unittest.TestCase):
	"""G-70b: a refusal a guest can meet is told apart by its code, never by its English wording."""

	def test_every_refusal_of_the_guest_api_carries_a_code(self):
		self.assertEqual(_uncoded(PUBLIC, None), [], "an uncoded refusal in api/public.py")

	def test_every_refusal_the_guest_api_reaches_carries_a_code(self):
		missing, uncoded = [], []
		for rel, functions in GUEST_PATHS.items():
			tree = ast.parse((TEX / rel).read_text(encoding="utf-8"))
			found = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
			missing += [f"{rel}:{f}" for f in sorted(functions - found)]
			uncoded += _uncoded(TEX / rel, functions)
		self.assertEqual(missing, [], "a guest path function moved: update GUEST_PATHS")
		self.assertEqual(uncoded, [])

	def test_the_coded_classes_declare_a_registered_code(self):
		for cls, rel in CODED_CLASSES.items():
			tree = ast.parse((TEX / rel).read_text(encoding="utf-8"))
			node = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == cls), None)
			self.assertIsNotNone(node, cls)
			codes = [a.value.value for a in node.body if isinstance(a, ast.Assign) and isinstance(a.value, ast.Constant)
			         and any(isinstance(t, ast.Name) and t.id == "code" for t in a.targets)]
			self.assertEqual(len(codes), 1, cls)
			self.assertIn(codes[0], refusal_codes.CODES, cls)


class TestEveryCodeHasAGuestText(unittest.TestCase):
	def test_the_booking_app_has_a_text_for_every_code(self):
		"""``refusal.<CODE>`` in the booking app's catalog (en; ``check.ts`` keeps the other languages complete):
		exactly the registry, no code without a text, no text for a code that does not exist."""
		catalog = json.loads(BOOKING_CATALOG.read_text(encoding="utf-8"))
		texts = {k.removeprefix("refusal.") for k in catalog if k.startswith("refusal.")}
		self.assertEqual(sorted(refusal_codes.CODES - texts), [], "codes without a guest text")
		self.assertEqual(sorted(texts - refusal_codes.CODES), [], "texts for no code")
