"""Payloads that existed before the Pricing Workspace price, validate and freeze exactly as on
main (ADR-061, "Existing semantics kept, the workspace's additions opt-in").

The owner's rule for the workspace: it changes the UX only, and no existing pricing semantics change
without the owner's sign-off. This test prices a fixed corpus of ``tex.contract.v1`` payloads with
the code under test and compares every result with what main (``6b0102c``, the branch's base; main
``1575c8b`` adds only the design document) computed for the same payload and request, recorded in
``parity_data/main_6b0102c.json``:

* every quote, byte for byte (the sha256 of its canonical JSON): ``RoomQuote.to_dict(internal=True)``
  (what the price test answers and what a TEX Quote and a reservation snapshot store) and the guest
  view ``to_dict(internal=False)``. Per payload: every room (and one it does not have) × board (and
  one it does not have) × rate plan (and none) × party (adults only, children in every band and
  order, an age in months, a date of birth, ages above the bands) × stay (one night, three nights
  across a period change, seven nights), without and with a markup and taxes;
* each payload's validation, issue by issue: the same issues (level, code, message) in the same
  order and nothing more, each given as main gave it (``Issue.to_dict()`` has main's three keys),
  and so the same ``ok`` and the same publish decision;
* the payload a publish freezes from the same terms (its hash), and each room × period unit the
  rates grid shows.

The workspace's additions to these functions are opt-in and off by default (``TestWorkspaceOptIn``):
the board checks (``validate_terms(board_checks=True)``, GAP-5), an issue's ``ref``
(``Issue.to_dict(ref=True)``, D9) and a night's running subtotals
(``RoomQuote.to_dict(subtotals=True)``, GAP-12). ``TestMainParity`` passes against main's code and
against this branch's; ``TestWorkspaceOptIn`` needs this branch (main has no such switches).

The corpus (``parity_data/corpus.json``) has 14 fixture contracts in every shape main accepts
(PERSON and ROOM basis, derived rooms, combination rules, the three child orders, policy cascades,
legacy precedence, a 3-decimal currency, weekday periods with night adjustments, rate plans with
terms, offers of every stage, board rows scoped to a room or period, orphan board rows and two rows
of one board for the same scope) and 11 payloads published on the dev site (its demo contracts and
contracts its end-to-end runs published).

To record the expected results again, run this file against main's code only::

    git archive 6b0102c kamra | tar -x -C /tmp/main
    PYTHONPATH=/tmp/main python kamra/tex/tests/unit/test_main_parity.py record /tmp/expected.json

and replace ``parity_data/main_6b0102c.json`` with the output (run as a script, the worktree is not
on the path, so every ``kamra`` import is main's). Recorded again so on 2026-09-25: byte for byte
the committed file.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from functools import cache
from pathlib import Path

from kamra.tex.pricing import engine, serialize, validate
from kamra.tex.pricing import rooms as room_math
from kamra.tex.pricing.enums import FxMode, Op
from kamra.tex.pricing.model import (
	ChildSpec,
	FxSnapshot,
	MarkupRule,
	PricingContext,
	PricingError,
	StayRequest,
	TaxRule,
	Unsellable,
)

DATA = Path(__file__).parent / "parity_data"
CORPUS = DATA / "corpus.json"
EXPECTED = DATA / "main_6b0102c.json"
BASE = "6b0102c"
# the board checks the workspace added (GAP-5): the workspace's opt-in, never an existing caller's
BOARD_CHECKS = frozenset({"BOARD_UNKNOWN_ROOM", "BOARD_UNKNOWN_PERIOD", "BOARD_DUPLICATE"})
# an issue as main gives it (``Issue.to_dict``) and a night of main's internal quote
MAIN_ISSUE_KEYS = {"level", "code", "message"}
MAIN_NIGHT_KEYS = {"date", "period", "unit", "occupancy", "board", "cost", "cost_net", "sell_contract", "sell", "final"}
SUBTOTALS = {"subtotal_adults", "subtotal_children", "subtotal_board"}

# (label, adults, children): an int is an age in years, "mNN" an age in months, "dobN" a date of birth
# N years and 40 days before arrival. Every party on one night; some across a period change; two for
# the long stay, the other rate plans and a room or board the contract does not have.
PARTIES = (
	("1A", 1, ()), ("2A", 2, ()), ("3A", 3, ()), ("4A", 4, ()),
	("1A+8", 1, (8,)), ("2A+8", 2, (8,)), ("2A+1", 2, (1,)), ("2A+4+10", 2, (4, 10)),
	("2A+10+4+1", 2, (10, 4, 1)), ("2A+m95", 2, ("m95",)), ("2A+dob8", 2, ("dob8",)), ("2A+16", 2, (16,)),
)
ACROSS = ("1A", "2A", "3A", "2A+8", "2A+4+10")
FEW = ("2A", "2A+8")
MARKUP = MarkupRule("MK-ALL", Op.ADJUST_PERCENT, Decimal("7"), label="Every market")
TAXES = (TaxRule("KV", "Accommodation tax", rate=Decimal("2"), order=1),
         TaxRule("VAT", "VAT", rate=Decimal("10"), order=2))


def canonical(obj) -> str:
	return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def digest(obj) -> str:
	return hashlib.sha256(canonical(obj).encode()).hexdigest()[:16]


@cache
def corpus() -> tuple[tuple[str, dict], ...]:
	data = json.loads(CORPUS.read_text(encoding="utf-8"))
	return tuple((p["id"], p["payload"]) for p in data["payloads"])


def terms_of(payload: dict):
	return serialize.terms_from_payload(payload, serialize.payload_hash(serialize.normalise_payload(payload)))


def _stays(t) -> list[tuple[str, date, date]]:
	"""One night at the first period's start, three nights across the next period's start, seven
	nights: inside the contract's stay window and on or after its first sale day."""
	first = min((d for d in (t.stay_from, t.sale_from) if d), default=None)
	lo = max(min(p.start for p in t.periods), first) if first else min(p.start for p in t.periods)
	lo = max(lo, t.sale_from or lo, t.stay_from or lo)
	later = sorted(p.start for p in t.periods if p.start > lo)
	cross = later[0] - timedelta(days=1) if later else lo + timedelta(days=1)
	out = [("1n", lo, lo + timedelta(days=1)), ("3n", cross, cross + timedelta(days=3)),
	       ("7n", lo, lo + timedelta(days=7))]
	return [(k, a, b) for k, a, b in out if not t.stay_to or b - timedelta(days=1) <= t.stay_to]


def _sale_at(t, check_in: date) -> datetime:
	"""120 days before arrival, inside the sale window."""
	day = check_in - timedelta(days=120)
	if t.sale_from and day < t.sale_from:
		day = t.sale_from
	if t.sale_to and day > t.sale_to:
		day = t.sale_to
	return datetime.combine(day, time(10, 0))


def _child(spec, check_in: date) -> ChildSpec:
	if isinstance(spec, int):
		return ChildSpec(age=spec)
	if spec.startswith("m"):
		return ChildSpec(age_months=int(spec[1:]))
	years = int(spec[3:])
	return ChildSpec(dob=date(check_in.year - years, check_in.month, min(check_in.day, 28)) - timedelta(days=40))


def cases(pid: str, t):
	"""(key, context, request) of every quote of the payload, in a fixed order: one night for every
	room, board and party with the first rate plan; three nights across a period change and seven
	nights for fewer parties and boards; the other rate plans, none (refused when the contract has
	plans), a room and a board the contract lacks, and a markup with taxes, for a few parties."""
	plain = PricingContext(terms=t, fx=FxSnapshot(t.currency, t.currency, FxMode.IDENTITY, Decimal(1)))
	marked = PricingContext(terms=t, fx=plain.fx, markups=(MARKUP,), tax_rules=TAXES)
	rooms, boards = sorted(t.rooms), sorted({b.board for b in t.boards})
	plans = sorted(t.rate_plans) or [None]
	plan = plans[0]
	channel = sorted(t.channels)[0] if t.channels else "DIRECT_WEB"
	everyone = tuple(p[0] for p in PARTIES)
	for stay, check_in, check_out in _stays(t):
		runs = []     # (context label, context, room, board, rate plan, parties)
		if stay == "1n":
			runs += [("plain", plain, rm, bd, plan, everyone) for rm in rooms for bd in boards]
			runs += [("plain", plain, rm, boards[0], other, FEW) for rm in rooms for other in plans[1:]]
			if t.rate_plans:
				runs.append(("plain", plain, rooms[0], boards[0], None, FEW[:1]))
			runs += [("plain", plain, "NO-SUCH-ROOM", boards[0], plan, FEW[:1]),
			         ("plain", plain, rooms[0], "NO-SUCH-BOARD", plan, FEW[:1])]
			runs += [("markup+tax", marked, rm, boards[0], plan, ("2A", "2A+8", "2A+4+10")) for rm in rooms]
		elif stay == "3n":
			runs += [("plain", plain, rm, boards[0], plan, ACROSS) for rm in rooms]
			runs += [("plain", plain, rm, bd, plan, FEW) for rm in rooms for bd in boards[1:]]
		else:
			runs += [("plain", plain, rooms[0], bd, plan, FEW) for bd in boards]
		sale_at = _sale_at(t, check_in)
		for how, ctx, room, board, rate_plan, labels in runs:
			for label, adults, kids in PARTIES:
				if label not in labels:
					continue
				req = StayRequest(property=t.property, room_type=room, board=board, check_in=check_in,
				                  check_out=check_out, adults=adults, sale_at=sale_at, market=t.market,
				                  channel=channel, sell_currency=t.currency,
				                  children=tuple(_child(k, check_in) for k in kids), rate_plan=rate_plan)
				yield f"{pid}|{stay}|{room}|{board}|{rate_plan or '-'}|{label}|{how}", ctx, req


def quote_result(ctx, req) -> tuple[str, str]:
	"""(digest of the internal and guest quote dicts, a readable summary)."""
	try:
		q = engine.price_stay(ctx, req)
	except PricingError as e:          # a refusal is a result too: the same error on both sides
		return digest(["raises", type(e).__name__, getattr(e, "code", None), str(e)]), f"raises {type(e).__name__}"
	internal, guest = q.to_dict(internal=True), q.to_dict(internal=False)
	summary = f"total {internal['totals'].get('total')}" if q.sellable else \
		"unsellable " + ",".join(r.get("code", "") for r in q.reasons)
	return digest([internal, guest]), summary


def payload_result(t) -> dict:
	"""What a publish and the rates grid take from the terms: the issues, the frozen payload's hash
	and each room × period unit."""
	units = []
	for rt in sorted(t.rooms):
		for p in t.periods:
			try:
				units.append([rt, p.code, str(room_math.room_unit(t, rt, p))])
			except Unsellable as u:
				units.append([rt, p.code, f"unsellable {u.code}"])
	return {"issues": [[i.level, i.code, i.message] for i in validate.validate_terms(t)],
	        "hash": serialize.payload_hash(serialize.normalise_payload(serialize.terms_to_payload(t))),
	        "units": units}


def record() -> dict:
	out = {"base": BASE, "payloads": {}, "quotes": {}}
	for pid, payload in corpus():
		t = terms_of(payload)
		out["payloads"][pid] = payload_result(t)
		for key, ctx, req in cases(pid, t):
			out["quotes"][key] = " ".join(quote_result(ctx, req))
	return out


def write(result: dict, path: str) -> None:
	"""One quote a line, so a new recording diffs readably."""
	lines = ["{", f'"base":{json.dumps(result["base"])},',
	         f'"payloads":{canonical(result["payloads"])},', '"quotes":{']
	items = list(result["quotes"].items())
	lines += [f"{json.dumps(k, ensure_ascii=False)}:{json.dumps(v, ensure_ascii=False)}"
	          + ("," if i < len(items) - 1 else "") for i, (k, v) in enumerate(items)]
	lines += ["}", "}"]
	Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


@cache
def expected() -> dict:
	return json.loads(EXPECTED.read_text(encoding="utf-8"))


class TestMainParity(unittest.TestCase):
	"""Passes against main's code and against this branch's."""

	def test_the_corpus_is_the_one_recorded_on_main(self):
		self.assertEqual(expected()["base"], BASE)
		self.assertEqual(sorted(expected()["payloads"]), sorted(pid for pid, _p in corpus()))
		keys = [key for pid, payload in corpus() for key, _c, _r in cases(pid, terms_of(payload))]
		self.assertEqual(len(keys), len(set(keys)))
		self.assertEqual(keys, list(expected()["quotes"]))
		self.assertGreater(len(keys), 2000)

	def test_every_quote_is_mains(self):
		"""Each quote's internal dict (price test, TEX Quote, reservation snapshot) and guest view,
		byte for byte."""
		recorded = expected()["quotes"]
		differ, sellable = [], 0
		for pid, payload in corpus():
			for key, ctx, req in cases(pid, terms_of(payload)):
				got = " ".join(quote_result(ctx, req))
				sellable += got.split(" ", 2)[1] == "total"
				if got != recorded.get(key):
					differ.append(f"{key}: main {recorded.get(key)!r}, now {got!r}")
		self.assertEqual(differ[:15], [], f"{len(differ)} of {len(recorded)} quotes differ from main")
		self.assertGreater(sellable, 1000)          # the corpus prices, it does not only refuse

	def test_every_payload_validates_and_freezes_as_on_main(self):
		"""The same issues in the same order and nothing more (no board check), each with main's
		keys only; the same frozen hash and units."""
		for pid, payload in corpus():
			with self.subTest(payload=pid):
				t = terms_of(payload)
				want = expected()["payloads"][pid]
				got = payload_result(t)
				self.assertEqual(got["hash"], want["hash"])
				self.assertEqual(got["units"], want["units"])
				self.assertEqual(got["issues"], want["issues"])
				for issue in validate.validate_terms(t):
					self.assertEqual(set(issue.to_dict()), MAIN_ISSUE_KEYS)

	def test_board_rows_main_published_still_publish(self):
		"""The corpus has board rows main published: an orphan room, an orphan period and two rows of
		one board for the same scope. An existing caller is not told about them, and the version is
		as publishable as on main."""
		want = expected()["payloads"]["FX-BOARDS-ORPHANS-TWINS"]["issues"]
		self.assertFalse([i for i in want if i[0] == "ERROR"])
		issues = validate.validate_terms(terms_of(dict(corpus())["FX-BOARDS-ORPHANS-TWINS"]))
		self.assertEqual([i.code for i in issues if i.code in BOARD_CHECKS], [])
		self.assertFalse([i for i in issues if i.level == "ERROR"])


class TestWorkspaceOptIn(unittest.TestCase):
	"""The workspace's additions are there when asked for, and only then (this branch only)."""

	def test_the_board_checks_are_the_workspaces(self):
		t = terms_of(dict(corpus())["FX-BOARDS-ORPHANS-TWINS"])
		plain = validate.validate_terms(t)
		checked = validate.validate_terms(t, board_checks=True)
		self.assertEqual({i.code: i.level for i in checked if i.code in BOARD_CHECKS},
		                 dict.fromkeys(BOARD_CHECKS, "ERROR"))
		# the board errors come after the board check main has, and before the sweep, which an error stops
		first = next(n for n, i in enumerate(checked) if i.code in BOARD_CHECKS)
		self.assertEqual([i.to_dict() for i in checked[:first]], [i.to_dict() for i in plain[:first]])
		for pid, payload in corpus():            # a clean contract has none
			if pid != "FX-BOARDS-ORPHANS-TWINS":
				with self.subTest(payload=pid):
					t = terms_of(payload)
					self.assertEqual([i.code for i in validate.validate_terms(t, board_checks=True)
					                  if i.code in BOARD_CHECKS], [])

	def test_an_issues_ref_is_the_workspaces(self):
		issues = [i for pid, payload in corpus() for i in validate.validate_terms(terms_of(payload))]
		with_ref = [i for i in issues if i.ref]
		self.assertTrue(with_ref)
		for i in issues:
			self.assertEqual(set(i.to_dict()), MAIN_ISSUE_KEYS)
			self.assertEqual(i.to_dict(ref=True), {**i.to_dict(), **({"ref": i.ref} if i.ref else {})})

	def test_a_nights_subtotals_are_the_workspaces(self):
		for pid, payload in corpus():
			t = terms_of(payload)
			key, ctx, req = next(c for c in cases(pid, t) if c[0].endswith("|2A+8|plain"))
			with self.subTest(case=key):
				try:
					q = engine.price_stay(ctx, req)
				except PricingError:
					continue
				plain, extra = q.to_dict(internal=True), q.to_dict(internal=True, subtotals=True)
				self.assertEqual([set(n) for n in plain["nights"]], [MAIN_NIGHT_KEYS] * len(q.nights))
				self.assertEqual([set(n) for n in extra["nights"]], [MAIN_NIGHT_KEYS | SUBTOTALS] * len(q.nights))
				self.assertEqual({**extra, "nights": None}, {**plain, "nights": None})
				self.assertEqual([{k: n[k] for k in MAIN_NIGHT_KEYS} for n in extra["nights"]], plain["nights"])
				# the guest view never carries them
				self.assertEqual(q.to_dict(internal=False, subtotals=True), q.to_dict(internal=False))


if __name__ == "__main__":
	if sys.argv[1:2] == ["record"] and len(sys.argv) == 3:
		write(record(), sys.argv[2])
	else:
		sys.exit("usage: PYTHONPATH=<a checkout of main> python test_main_parity.py record <out.json>")
