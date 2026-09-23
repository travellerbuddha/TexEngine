"""How a guest's own change to a booking is settled (G-45, ADR-044). Pure: no frappe.

``settle`` decides, for one change, what happens to the money:

- a higher price is paid before the change applies, as far as the booking's payment terms
  need it *now*: ``collect = max(0, min(difference, required_now(new) − paid))``. A full
  prepayment collects the whole difference, a 30 % deposit collects the deposit share of the
  new total not paid yet, pay-at-hotel collects nothing. Arrears the booking already had are
  never charged by a change (``collect`` is capped at the difference);
- a lower price follows the hotel's policy: staff approval, an automatic refund of the true
  overpayment (``paid − new total``; a deposit-only booking just gets a smaller balance), or a
  credit kept on the booking. A lower price on a non-refundable rate, or while cancelling now
  would cost a penalty (``penalty_applies``), always goes to the hotel: shortening a stay must
  never give back what its terms keep (review of ADR-044). Of a refund, only what the charges
  holding the money can give back automatically (``auto_refundable``) goes back to the card;
  the rest is refunded by the hotel (``hotel_refund``).

``plan_refunds`` splits a refund over the charges holding the booking's money: newest first,
each at most what it holds for this booking, only charges whose provider can refund. What no
charge can give back is the remainder (it stays as credit for staff).

Amounts are ``Decimal`` in one currency, rounded to its minor unit by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal("0")

# settlement kinds (the guest API returns them as they are)
PAY_NOW = "pay_now"                      # the change applies once this amount is paid online
PAY_AT_HOTEL = "pay_at_hotel"            # applies now; the difference is paid at the hotel
BALANCE = "balance"                      # applies now; nothing to pay now, the open balance changes
REFUND = "refund"                        # applies now; the overpayment is refunded to the card
CREDIT = "credit"                        # applies now; the overpayment stays as credit on the booking
STAFF_APPROVAL = "staff_approval"        # a lower price the hotel approves first
STAFF = "staff"                          # money is due now and no card payment is set up: staff handle it
NONE = "none"                            # the price does not change
KINDS = (PAY_NOW, PAY_AT_HOTEL, BALANCE, REFUND, CREDIT, STAFF_APPROVAL, STAFF, NONE)

# Property.tex_lower_price_refund
LOWER_STAFF = "Staff approval"
LOWER_REFUND = "Refund automatically"
LOWER_CREDIT = "Keep as credit"


@dataclass(frozen=True)
class Settlement:
	kind: str
	collect: Decimal = ZERO                # charged online before the change applies
	refund: Decimal = ZERO                 # refunded after the change applied
	credit: Decimal = ZERO                 # kept on the booking as credit
	hotel_refund: Decimal = ZERO           # of the overpayment: refunded by the hotel, not to a card by TEX
	difference: Decimal = ZERO             # new total − old total
	balance_after: Decimal = ZERO          # new total − money held once settled (< 0: credit)
	due_later: Decimal = ZERO              # how much more the open balance grows (+) or shrinks (−)

	@property
	def amount(self) -> Decimal:
		"""The one figure the guest is shown for this kind."""
		if self.kind in (PAY_NOW, STAFF) and self.collect:
			return self.collect
		if self.kind == REFUND:
			return self.refund + self.hotel_refund
		if self.kind == CREDIT:
			return self.credit
		if self.kind in (PAY_AT_HOTEL, BALANCE):
			return abs(self.due_later)
		if self.kind in (STAFF_APPROVAL, STAFF):
			return abs(self.difference)
		return ZERO

	@property
	def applies_now(self) -> bool:
		return self.kind in (PAY_AT_HOTEL, BALANCE, REFUND, CREDIT, NONE)


def _open(total: Decimal, held: Decimal) -> Decimal:
	return max(ZERO, total - held)


def settle(old_total, new_total, paid, required_now_new, *, pay_at_hotel: bool, lower_policy: str | None,
           card_available: bool, penalty_applies: bool = False, auto_refundable=None) -> Settlement:
	"""One change of a booking. Totals are the booking's (all rooms), before and after the
	change; ``paid`` is what the booking holds now and may use (money set aside for a refund
	is not counted); ``required_now_new`` what its payment terms require to be paid by now with
	the new price (deposit rules, 0 for pay at hotel). ``penalty_applies``: the room's rate is
	non-refundable or cancelling it now costs a penalty. ``auto_refundable``: how much of an
	overpayment the charges holding it can refund to the card (None: all of it)."""
	old_total, new_total, paid, required = (Decimal(old_total), Decimal(new_total), Decimal(paid),
	                                         Decimal(required_now_new))
	diff = new_total - old_total
	due_later = _open(new_total, paid) - _open(old_total, paid)
	if diff == 0:
		return Settlement(NONE, difference=diff, balance_after=new_total - paid)
	if diff > 0:
		collect = max(ZERO, min(diff, required - paid))
		if collect > 0:
			if not card_available:
				return Settlement(STAFF, collect=collect, difference=diff, balance_after=new_total - paid,
				                  due_later=due_later)
			return Settlement(PAY_NOW, collect=collect, difference=diff, balance_after=new_total - paid - collect,
			                  due_later=_open(new_total, paid + collect) - _open(old_total, paid))
		return Settlement(PAY_AT_HOTEL if pay_at_hotel else BALANCE, difference=diff,
		                  balance_after=new_total - paid, due_later=due_later)
	if penalty_applies or lower_policy not in (LOWER_REFUND, LOWER_CREDIT):
		# the default, any policy this code does not know, and any lower price the rate's terms
		# would charge for: the hotel decides
		return Settlement(STAFF_APPROVAL, difference=diff, balance_after=new_total - paid, due_later=due_later)
	over = max(ZERO, paid - new_total)
	if over == 0:
		return Settlement(BALANCE, difference=diff, balance_after=new_total - paid, due_later=due_later)
	if lower_policy == LOWER_REFUND:
		auto = over if auto_refundable is None else min(over, max(ZERO, Decimal(auto_refundable)))
		return Settlement(REFUND, refund=auto, hotel_refund=over - auto, difference=diff,
		                  balance_after=new_total - (paid - over), due_later=due_later)
	return Settlement(CREDIT, credit=over, difference=diff, balance_after=new_total - paid, due_later=due_later)


@dataclass(frozen=True)
class Charge:
	"""A successful charge holding money of the booking being refunded."""
	transaction: str
	available: Decimal            # what it holds for this booking and can still refund
	supported: bool = True        # its provider refunds through TEX (a card gateway, not a transfer)
	at: str = ""                  # when it was taken (sortable): newest is refunded first


def plan_refunds(amount, charges) -> tuple[list[tuple[str, Decimal]], Decimal]:
	"""→ ([(transaction, amount)], remainder). Newest charge first, each capped by what it
	holds; charges the provider cannot refund are skipped; the remainder is what is left."""
	left = Decimal(amount)
	plan: list[tuple[str, Decimal]] = []
	for c in sorted(charges, key=lambda c: (c.at, c.transaction), reverse=True):
		if left <= 0:
			break
		if not c.supported or c.available <= 0:
			continue
		take = min(left, Decimal(c.available))
		plan.append((c.transaction, take))
		left -= take
	return plan, max(ZERO, left)
