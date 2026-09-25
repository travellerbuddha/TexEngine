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
  rates grid shows;
* drafts made from three of the payloads, each broken or unusual in one way (97, reaching every
  issue code main's validation reports but the sweep's AMBIGUOUS_OCCUPANCY_RULES), as an existing
  caller validates a draft before publishing it: the same issues, in main's shape.

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
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from functools import cache
from pathlib import Path

from kamra.tex.pricing import engine, serialize, validate
from kamra.tex.pricing import rooms as room_math
from kamra.tex.pricing.enums import FxMode, Level, OccTarget, Op, PromoValueType
from kamra.tex.pricing.model import (
	AgeBand,
	ChildSpec,
	FxSnapshot,
	MarkupRule,
	OccupancyRule,
	Period,
	PricingContext,
	PricingError,
	Promotion,
	RoomRule,
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


# the drafts' bases: PERSON basis with derived rooms and rate plans, ROOM basis, policy cascades
DRAFT_BASES = ("FX-DE-S27", "FX-ROOM", "FX-POLICY-CASCADE")
# every issue code main's validation reports (validate.py on 6b0102c; OCC_UNKNOWN_* and
# OCC_INHERITED_*_UNUSED for a band, room and period; the sweep's and the room resolver's codes):
# each is reached by some draft or corpus payload. The sweep's AMBIGUOUS_OCCUPANCY_RULES is not: a
# tie it would find is an OCC_AMBIGUOUS error first, and an error stops the sweep
MAIN_CODES = frozenset({
	"CURRENCY", "NO_ROOMS", "NO_PERIODS", "SALE_WINDOW", "STAY_WINDOW", "ROOM_CAPACITY", "INCLUDED_ADULTS",
	"PERIOD_DUPLICATE", "PERIOD_RANGE", "PERIOD_OVERLAP", "ROOM_RULE_DUPLICATE", "ROOM_RULE_UNKNOWN_ROOM",
	"ROOM_RULE_UNKNOWN_PERIOD", "ROOM_RULE_NO_BASE", "ROOM_NEGATIVE", "NO_ROOM_PRICE", "ROOM_DERIVATION_CYCLE",
	"ROOM_DERIVATION_NO_BASE",
	"AGE_BANDS", "AGE_BANDS_MIN_AGE", "NO_AGE_BANDS", "OCC_UNKNOWN_BAND", "OCC_UNKNOWN_ROOM", "OCC_UNKNOWN_PERIOD",
	"OCC_INHERITED_BAND_UNUSED", "OCC_INHERITED_ROOM_UNUSED", "OCC_INHERITED_PERIOD_UNUSED",
	"OCC_COMBINATION_QUALIFIER", "OCC_ADULT_BAND", "OCC_INHERITED_ADULT_BAND_UNUSED", "OCC_NO_VALUE", "OCC_DUPLICATE",
	"OCC_AMBIGUOUS", "OCC_POLICY_OVERRIDE_OUTRANKED", "OCC_INFANT_GENERIC", "NO_BASE_BOARD", "RATE_PLAN_BOARD",
	"OFFER_VALUE", "OFFER_FREE_NIGHTS", "NO_CHILD_RULE", "NEGATIVE_OCCUPANCY_PRICE",
})


def _inherited(r: OccupancyRule, **changes) -> OccupancyRule:
	"""``r`` as a hotel pricing policy's rule."""
	return replace(r, base_level=Level.HOTEL, source="policy:POL-H/r1/hotel", scope_weight=1, **changes)


def drafts(t) -> list[tuple[str, object]]:
	"""(name, terms) of drafts made from ``t``, each broken or unusual in one way, as an existing
	caller validates a draft before publishing it. Made with ``dataclasses.replace`` on the terms
	(the model is the same on main and on this branch), so both validate the very same terms."""
	rooms = sorted(t.rooms)
	room0, room1 = rooms[0], rooms[-1]
	p0, p1 = t.periods[0], t.periods[-1]
	rr0 = t.room_rules[0]
	absolute = next(r for r in t.room_rules if r.op in (Op.ABSOLUTE, Op.FIXED))
	derived = next((r for r in t.room_rules if r.base_room_type), None)
	child = next(r for r in t.occupancy_rules if r.target == OccTarget.CHILD and r.age_band)
	infant = next((b for b in t.age_bands if b.is_infant), None)
	base_board = next(b for b in t.boards if b.is_base)
	spec0 = t.rooms[room0]
	occ = t.occupancy_rules
	out = [
		("currency", replace(t, currency="EURO")),
		("windows", replace(t, sale_from=date(2030, 1, 2), sale_to=date(2030, 1, 1),
		                    stay_from=date(2030, 1, 2), stay_to=date(2030, 1, 1))),
		("no-rooms", replace(t, rooms={})),
		("no-periods", replace(t, periods=())),
		("capacity", replace(t, rooms={**t.rooms, room0: replace(spec0, max_adults=0),
		                               room1: replace(t.rooms[room1], max_occupants=1, max_adults=2)})),
		("included-adults", replace(t, rooms={**t.rooms, room0: replace(spec0, included_adults=spec0.max_adults + 1)})),
		("period-duplicate", replace(t, periods=(*t.periods, replace(p1, name="again")))),
		("period-range", replace(t, periods=(replace(p0, start=p0.end + timedelta(days=1)), *t.periods[1:]))),
		("period-overlap", replace(t, periods=(*t.periods, Period("PX", "overlap", p0.start, p0.end,
		                                                          priority=p0.priority)))),
		("room-rule-duplicate", replace(t, room_rules=(*t.room_rules, replace(rr0, rule_id="RR-TWIN")))),
		("room-rule-unknown", replace(t, room_rules=(*t.room_rules, RoomRule("RR-ZZ", "ZZZ", None, Op.ABSOLUTE, Decimal(9)),
		                                             replace(absolute, rule_id="RR-PZ", period="PZ")))),
		("room-rule-no-base", replace(t, room_rules=(*t.room_rules, RoomRule("RR-NB", room1, p1.code, Op.MULTIPLY,
		                                                                      Decimal("1.1"))))),
		("room-negative", replace(t, room_rules=(replace(absolute, value=Decimal(-5)),
		                                         *(r for r in t.room_rules if r is not absolute)))),
		("no-room-price", replace(t, room_rules=tuple(r for r in t.room_rules if r.room_type != room1))),
		("age-bands", replace(t, age_bands=tuple(replace(b, to_months=b.to_months - 6) if i == 1 else
		                                         replace(b, from_months=b.to_months + 5, to_months=b.from_months)
		                                         if i == 2 else b for i, b in enumerate(t.age_bands)))),
		("no-bands", replace(t, age_bands=())),
		("min-age", replace(t, age_bands=tuple(b for b in t.age_bands if not b.is_infant))),
		("occ-unknown", replace(t, occupancy_rules=(*occ, replace(child, rule_id="O-ZB", age_band="ZZ"),
		                                            replace(child, rule_id="O-ZR", room_type="ZZZ"),
		                                            replace(child, rule_id="O-ZP", period="PZ")))),
		("occ-inherited-unused", replace(t, occupancy_rules=(*occ, _inherited(child, rule_id="P-ZB", age_band="ZZ"),
		                                                     _inherited(child, rule_id="P-ZR", room_type="ZZZ"),
		                                                     _inherited(child, rule_id="P-ZP", period="PZ"),
		                                                     OccupancyRule("P-AB", OccTarget.ADULT, Op.MULTIPLY,
		                                                                   Decimal("0.9"), position=2,
		                                                                   age_band=child.age_band, base_level=Level.HOTEL,
		                                                                   source="policy:POL-H/r1/hotel",
		                                                                   scope_weight=1)))),
		("occ-shape", replace(t, occupancy_rules=(*occ, OccupancyRule("O-CQ", OccTarget.COMBINATION, Op.MULTIPLY,
		                                                             Decimal("0.9")),
		                                          OccupancyRule("O-AB", OccTarget.ADULT, Op.MULTIPLY, Decimal("0.9"),
		                                                        position=2, age_band=child.age_band),
		                                          replace(child, rule_id="O-NV", room_type=room0, value=None)))),
		("occ-duplicate", replace(t, occupancy_rules=(*occ, replace(child, rule_id="O-TWIN")))),
		("occ-ambiguous", replace(t, occupancy_rules=(*occ, replace(child, rule_id="O-A2", adults=2, value=Decimal(40)),
		                                              replace(child, rule_id="O-C1", children=1, value=Decimal(60))))),
		("occ-policy-override", replace(t, occupancy_rules=(*occ, _inherited(child, rule_id="P-OVR", is_override=True,
		                                                                     value=Decimal(7))))),
		("infant-generic", replace(t, occupancy_rules=(*(r for r in occ if not (infant and r.age_band == infant.code)),
		                                               replace(child, rule_id="O-ANY", age_band=None)))),
		("no-base-board", replace(t, boards=tuple(b for b in t.boards if b is not base_board))),
		("offers", replace(t, offers=(*t.offers, Promotion("OF-150", "over", PromoValueType.PERCENT, Decimal(150)),
		                              Promotion("OF-FN", "free", PromoValueType.FREE_NIGHTS, free_nights_stay=3,
		                                        free_nights_pay=3)))),
		("sweep-negative", replace(t, occupancy_rules=(*occ, OccupancyRule("O-NEG", OccTarget.COMBINATION, Op.SUBTRACT,
		                                                                   Decimal(99999), adults=2, children=1)))),
		("sweep-no-child-rule", replace(t, occupancy_rules=tuple(r for r in occ if r.age_band != child.age_band
		                                                         or r.target != OccTarget.CHILD))),
		("sweep-ambiguous", replace(t, occupancy_rules=(*occ, replace(child, rule_id="O-A2", adults=2, value=Decimal(40)),
		                                                replace(child, rule_id="O-C1", children=1, value=Decimal(60))),
		                            occupancy_precedence=1)),
		("board-rows", replace(t, boards=(*t.boards, replace(base_board, rule_id="B-ZR", is_base=False,
		                                                     room_type="ZZZ", adult_amount=Decimal(5)),
		                                  replace(base_board, rule_id="B-ZP", is_base=False, period="PZ",
		                                          adult_amount=Decimal(5)),
		                                  replace(base_board, rule_id="B-TWIN")))),
	]
	if derived is not None:
		base = next(r for r in t.room_rules if r.room_type == derived.base_room_type)
		out.append(("derivation-cycle", replace(t, room_rules=(
			*(r for r in t.room_rules if r is not base),
			replace(base, op=Op.MULTIPLY, value=Decimal("1.1"), base_room_type=derived.room_type)))))
	if t.rate_plans:
		code = sorted(t.rate_plans)[0]
		out.append(("rate-plan-board", replace(t, rate_plans={**t.rate_plans, code: replace(
			t.rate_plans[code], boards=frozenset({"ZZ"}))})))
	if infant is not None:
		out.append(("band-invalid", replace(t, age_bands=(AgeBand("NEG", "negative", 5, 2), *t.age_bands))))
	return out


def issues_of(t) -> list:
	"""``validate_terms`` as an existing caller gets it: each issue's (level, code, message) and the
	keys of its dict, or the error it raises."""
	try:
		return [[i.level, i.code, i.message, sorted(i.to_dict())] for i in validate.validate_terms(t)]
	except Exception as e:                # a draft main cannot validate: the same failure here
		return [["raises", type(e).__name__, str(e)]]


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


def draft_results() -> dict:
	"""Each draft's issues, keyed ``<base>|<draft>``."""
	return {f"{pid}|{name}": issues_of(t) for pid, payload in corpus() if pid in DRAFT_BASES
	        for name, t in drafts(terms_of(payload))}


def record() -> dict:
	out = {"base": BASE, "payloads": {}, "drafts": draft_results(), "quotes": {}}
	for pid, payload in corpus():
		t = terms_of(payload)
		out["payloads"][pid] = payload_result(t)
		for key, ctx, req in cases(pid, t):
			out["quotes"][key] = " ".join(quote_result(ctx, req))
	return out


def write(result: dict, path: str) -> None:
	"""One quote a line, so a new recording diffs readably."""
	lines = ["{", f'"base":{json.dumps(result["base"])},',
	         f'"payloads":{canonical(result["payloads"])},', f'"drafts":{canonical(result["drafts"])},', '"quotes":{']
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

	def test_every_draft_validates_as_on_main(self):
		"""Drafts broken or unusual in every way main's validation knows, as an existing caller checks
		one before publishing: the same issues (level, code, message, main's keys) in the same order."""
		got, want = draft_results(), expected()["drafts"]
		self.assertEqual(sorted(got), sorted(want))
		for key in want:
			with self.subTest(draft=key):
				self.assertEqual(got[key], want[key])
		reached = {i[1] for issues in want.values() for i in issues} | \
			{i[1] for p in expected()["payloads"].values() for i in p["issues"]}
		self.assertEqual(MAIN_CODES - reached, set())

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
