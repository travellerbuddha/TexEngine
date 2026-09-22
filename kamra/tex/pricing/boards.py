"""Board (meal plan) supplements. The contract's base board is included in the room
price; other boards add a supplement per adult/child per night, a percentage of the
night's occupancy amount, or a fixed amount per room-night."""

from __future__ import annotations

from decimal import Decimal

from kamra.tex.money import HUNDRED, ZERO, D
from kamra.tex.pricing.ages import Party
from kamra.tex.pricing.enums import Level, Op
from kamra.tex.pricing.explain import Explanation
from kamra.tex.pricing.model import BoardRule, ContractTerms, Period, RuleRef, Unsellable


def _level(r: BoardRule) -> Level:
	if r.period:
		return Level.PERIOD
	if r.room_type:
		return Level.ROOM
	return Level.VERSION


def board_rule(terms: ContractTerms, board: str, room_type: str, period: Period) -> BoardRule | None:
	cands = [r for r in terms.boards if r.board == board
	         and (r.room_type is None or r.room_type == room_type)
	         and (r.period is None or r.period == period.code)]
	if not cands:
		return None
	return max(cands, key=lambda r: (r.period is not None, r.room_type is not None, r.rule_id))


def price_board(terms: ContractTerms, board: str, room_type: str, period: Period, party: Party,
                occupancy_total: Decimal, *, night=None, explain: Explanation | None = None) -> Decimal:
	rule = board_rule(terms, board, room_type, period)
	if rule is None:
		raise Unsellable("NO_BOARD", f"board {board} is not offered under this contract", board=board)
	ref = RuleRef("board_rule", rule.rule_id, _level(rule), "version", f"{board}")
	if rule.is_base:
		if explain is not None:
			explain.add("board", "BOARD_BASE", "board {board} included in the price", night=night,
			            rule=ref, board=board)
		return ZERO

	if rule.op == Op.ADD:
		band_pct = dict(rule.band_percents)
		amount = D(rule.adult_amount) * party.adults
		for child in party.children:
			if child.band.is_infant and rule.infant_free:
				continue
			pct = D(band_pct.get(child.band.code, rule.child_percent))
			amount += D(rule.adult_amount) * pct / HUNDRED
	elif rule.op == Op.ADJUST_PERCENT or rule.op == Op.PERCENT_OF:
		amount = occupancy_total * D(rule.adult_amount) / HUNDRED
	elif rule.op in (Op.ABSOLUTE, Op.FIXED):
		amount = D(rule.adult_amount)
	else:
		raise Unsellable("BOARD_OP_UNSUPPORTED", f"board rule {rule.rule_id} uses unsupported {rule.op}")

	if explain is not None:
		explain.add("board", "BOARD_SUPPLEMENT", "board {board} supplement {amount}", night=night,
		            after=amount, rule=ref, board=board, amount=amount)
	return amount
