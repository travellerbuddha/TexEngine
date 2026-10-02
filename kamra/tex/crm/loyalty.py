"""TEX Loyalty (R-39): earn rules, pending → available maturation, tiers, blackout
dates, redemption as a payment against a booking, expiry and reversal on cancel.

Ledger entries carry signed points. The available balance counts entries whose
status is Available / Used / Expired (i.e. final); Pending earnings are shown
separately and Reversed ones are ignored. Everything is integer points; money
values use Decimal and the program currency.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import ROUND_FLOOR

import frappe
from frappe import _
from frappe.utils import add_days, add_months, getdate, now_datetime, nowdate

from kamra.tex.crm import lots
from kamra.tex.money import ZERO, D, db_dec, from_db, quantize, to_str
from kamra.tex.security import scope
from kamra.tex.security.audit import audit
from kamra.tex.services.txn import undo_to

FINAL = ("Available", "Used", "Expired")


def program_for(property: str) -> str | None:
	"""The hotel's enabled program, else its group's (at most one each: the controller)."""
	name = frappe.db.get_value("TEX Loyalty Program", {"property": property, "enabled": 1}, order_by="creation asc")
	if name:
		return name
	group = frappe.db.get_value("Property", property, "tex_hotel_group")
	if group:
		return frappe.db.get_value("TEX Loyalty Program", {"hotel_group": group, "enabled": 1,
		                                                   "property": ("is", "not set")}, order_by="creation asc")
	return None


def program_properties(prog) -> list[str]:
	"""The (enabled) hotels a program reaches."""
	if prog.get("property"):
		return [prog.property]
	if not prog.get("hotel_group"):
		return []
	return frappe.get_all("Property", filters={"tex_hotel_group": prog.hotel_group, "disabled": 0}, pluck="name",
	                      order_by="name asc")


def visible_programs(props: set[str]) -> set[str]:
	"""Programs the viewer's hotels belong to (their own, or their group's)."""
	if not props:
		return set()
	groups = {g for g in frappe.get_all("Property", filters={"name": ("in", list(props))}, pluck="tex_hotel_group")
	          if g}
	return set(frappe.get_all("TEX Loyalty Program", or_filters={"property": ("in", list(props)),
	                                                            "hotel_group": ("in", list(groups) or [""])},
	                          pluck="name"))


def balances(guest: str, program: str, *, lock: bool = False) -> dict:
	"""A guest's points in a program. ``lock``: read with a shared lock through ``tex_ledger_guest_program``,
	so the balance is what is committed now, not the request's snapshot (a redemption: third review of
	ADR-056, H-1)."""
	shared = " LOCK IN SHARE MODE" if lock else ""
	rows = frappe.db.sql(f"""SELECT status, SUM(points) pts FROM `tabTEX Loyalty Ledger`
		WHERE guest=%s AND program=%s GROUP BY status{shared}""", (guest, program), as_dict=True)  # nosemgrep
	by = {r.status: int(r.pts or 0) for r in rows}
	earned = frappe.db.sql(f"""SELECT COALESCE(SUM(points),0) FROM `tabTEX Loyalty Ledger`
		WHERE guest=%s AND program=%s AND entry_type='Earn' AND status IN ('Available','Used','Expired'){shared}""",
	                       (guest, program))[0][0]  # nosemgrep -- a constant clause
	return {"available": sum(by.get(s, 0) for s in FINAL), "pending": by.get("Pending", 0),
	        "lifetime_earned": int(earned or 0)}


def tier_of(program_doc, lifetime_points: int):
	tiers = sorted(program_doc.tiers or [], key=lambda t: int(t.min_points or 0))
	current = None
	for t in tiers:
		if lifetime_points >= int(t.min_points or 0):
			current = t
	return current


def _in_blackout(program_doc, day: date, purpose: str) -> bool:
	"""``purpose``: "Earning" or "Redemption"; a row without a purpose (before G-24) is both."""
	return any(getdate(b.date_from) <= day <= getdate(b.date_to) for b in program_doc.blackouts or []
	           if b.date_from and b.date_to and (b.get("applies_to") or "Both") in (purpose, "Both"))


def stay_fingerprint(res) -> str:
	"""What an earning depends on in the stay itself: dates, room, value and extras. A
	change of the program's rules never changes it, so it never rewrites past earnings."""
	snap = json.loads(res.tex_pricing_snapshot or "{}")
	extras = sorted((e.get("code"), str(e.get("quantity"))) for e in snap.get("extras") or [] if e.get("ok"))
	basis = [str(res.check_in_date), str(res.check_out_date), res.room_type, res.tex_currency,
	         str(res.tex_total_amount or res.amount_after_tax or 0), extras]
	return hashlib.sha256(json.dumps(basis, default=str).encode()).hexdigest()[:32]


def extra_units(snap: dict, code: str | None) -> tuple[int, str | None]:
	"""Units of the extra ``code`` a price snapshot sold → (units, None), or (0, the quantity) when one
	is not a whole number. A snapshot quantity is a decimal string ("2.000000", ``to_str6``): read as
	Decimal, never ``int()``, which raised in the reservation's update hook and rolled back its
	confirmation (Y-10)."""
	units = 0
	for e in snap.get("extras") or []:
		if not e.get("ok") or e.get("code") != code:
			continue
		q = D(e.get("quantity") or 1)
		if q != q.to_integral_value():
			return 0, str(e.get("quantity"))
		units += int(q)
	return units, None


def points_for(program_doc, res, multiplier) -> tuple[int, list[dict]]:
	"""Deterministic earn calculation for one reservation → (points, explanation)."""
	ci, co = getdate(res.check_in_date), getdate(res.check_out_date)
	nights = max(0, (co - ci).days)
	ccy = res.tex_currency or program_doc.currency or "EUR"
	amount = from_db(res.tex_total_amount or res.amount_after_tax or 0, ccy)
	if _in_blackout(program_doc, ci, "Earning"):
		return 0, [{"rule": "BLACKOUT", "points": 0}]
	total = D(0)
	lines = []
	for r in program_doc.earn_rules or []:
		if r.date_from and ci < getdate(r.date_from):
			continue
		if r.date_to and ci > getdate(r.date_to):
			continue
		rate = db_dec(r.rate)
		if r.basis == "MONEY":
			if program_doc.currency and ccy != program_doc.currency:
				lines.append({"rule": "MONEY", "points": 0, "note": f"currency {ccy} ≠ program {program_doc.currency}"})
				continue
			pts = amount * rate
		elif r.basis == "NIGHTS":
			pts = rate * nights
		elif r.basis == "STAY":
			pts = rate
		elif r.basis == "ROOM":
			if r.room_type != res.room_type:
				continue
			pts = rate * nights
		else:  # EXTRA: points per booked unit of a specific extra (from the price snapshot)
			snap = json.loads(res.tex_pricing_snapshot or "{}")
			code = frappe.db.get_value("TEX Extra", r.extra, "extra_code") if r.extra else None
			qty, odd = extra_units(snap, code)
			if odd is not None:
				lines.append({"rule": r.basis, "rate": str(rate), "points": "0",
				              "note": f"quantity {odd} of {code} is not a whole number"})
				continue
			pts = rate * qty
		total += pts
		lines.append({"rule": r.basis, "rate": str(rate), "points": str(pts)})
	total = total * db_dec(multiplier or 1)
	return int(total.to_integral_value(rounding=ROUND_FLOOR)), lines


EARN_SAVEPOINT = "tex_loyalty_earn"


def on_reservation_change(doc) -> None:
	"""doc_event (Reservation.on_update): earn when confirmed, reverse when cancelled, and
	earn again only when the stay itself changed (its fingerprint). Editing the program's
	rules, tiers or points never rewrites earnings already made (G-24).

	It runs inside the reservation's save (a confirmation, a payment's callback, a cancellation): an earning
	or a reversal that fails never rolls that back (LO-47, owner's choice). It is undone alone to its savepoint, its message
	dropped, logged ("TEX loyalty earning <reservation>"), and ``loyalty.earnings`` warns that a stay's points
	are missing. A deadlock or a lost transaction is raised as it is (its savepoint is gone with it). The points
	return of a cancellation (O-20) is never under this: it is money and fails its request."""
	from kamra.tex.security.audit import log_exception
	from kamra.tex.services.txn import transaction_lost

	if not doc.get("tex_booking") or not doc.guest:
		return
	if doc.flags.get("tex_loyalty_after_money"):
		return          # a cancellation gives the points spent on its booking back first, then calls this (ADR-071 §4)
	program = program_for(doc.property)
	if not program:
		return
	frappe.db.savepoint(EARN_SAVEPOINT)
	messages = frappe.local.message_log
	mark = len(messages)
	try:
		_earn(doc, program)
	except Exception as e:
		if transaction_lost(e):
			raise
		frappe.db.rollback(save_point=EARN_SAVEPOINT)
		del messages[mark:]                   # the earning's refusal is a note for staff, never the save's answer
		log_exception(f"TEX loyalty earning {doc.name}")


def _earn(doc, program: str) -> None:
	"""``on_reservation_change``'s work, under its savepoint."""
	existing = frappe.get_all("TEX Loyalty Ledger", filters={"reservation": doc.name, "entry_type": "Earn",
	                                                         "status": ("!=", "Reversed")},
	                          fields=["name", "points", "status", "stay_fingerprint", "expires_on"])
	if doc.status in ("Cancelled", "No Show"):
		for e in existing:
			_reverse(e, reason=f"reservation {doc.status.lower()}")
		_sync_guest(doc.guest)
		return
	if doc.status not in ("Confirmed", "Checked In", "Checked Out"):
		return
	fingerprint = stay_fingerprint(doc)
	if existing and all(e.stay_fingerprint in (fingerprint, None, "") for e in existing):
		return                  # the stay is unchanged (an earning made before G-24 is kept as it was)
	prog = frappe.get_cached_doc("TEX Loyalty Program", program)
	# the stay's own earnings are about to be replaced: they do not make the guest's tier (O-21, ADR-071 §6)
	own = sum(int(e.points) for e in existing if e.status in FINAL)
	tier = tier_of(prog, balances(doc.guest, program, lock=True)["lifetime_earned"] - own)
	points, lines = points_for(prog, doc, tier.earn_multiplier if tier else 1)
	# the new earning takes the old one's place, in its state: a stay that had matured stays mature
	status = "Available" if any(e.status in FINAL for e in existing) else "Pending"
	# an earning whose points had expired keeps its expiry: a change of the stay never brings expired points back
	# with a fresh one (LO-26, ADR-071 §5). Read before the reversal takes its Expire rows back
	kept = [getdate(e.expires_on) for e in existing if e.status in FINAL and e.expires_on and frappe.db.exists(
		"TEX Loyalty Ledger", {"guest": doc.guest, "program": program, "entry_type": "Expire",
		                       "status": ("in", list(FINAL)), "reason": lots.marker(e.name)})]
	for e in existing:
		_reverse(e, reason="reservation modified", floor=False)       # exact: spent points are not topped up
	if points <= 0:
		_sync_guest(doc.guest)
		return
	avail_on = add_days(getdate(doc.check_out_date), int(prog.pending_days or 0))
	expires_on = add_months(avail_on, int(prog.expiry_months)) if prog.expiry_months else None
	if kept:
		expires_on = min([*kept, *([getdate(expires_on)] if expires_on else [])])
	frappe.get_doc({
		"doctype": "TEX Loyalty Ledger", "program": program, "guest": doc.guest, "entry_type": "Earn",
		"points": points, "status": status, "available_on": avail_on, "expires_on": expires_on,
		"booking": doc.tex_booking, "reservation": doc.name, "property": doc.property,
		"reason": f"stay {doc.check_in_date}→{doc.check_out_date}" + (f" · tier {tier.tier_name}" if tier else ""),
		"stay_fingerprint": fingerprint,
		"explanation": json.dumps({"lines": lines, "tier": tier.tier_name if tier else None,
		                           "multiplier": str(db_dec(tier.earn_multiplier)) if tier else "1"}, default=str),
		"actor": frappe.session.user}).insert(ignore_permissions=True)
	if kept:
		settle(doc.guest, program)                 # past that expiry: its points expire at once, as the job would
	_sync_guest(doc.guest)


def _reverse(entry, *, reason: str, floor: bool = True) -> None:
	"""Take an earning back, with the Expire rows that took points of it (ADR-071 §5). ``floor``: a stay that
	did not happen (cancelled, no-show) never takes the balance below zero: points already spent are not
	clawed back, and an Adjust entry tops the balance up. A stay that changed is exact (``floor=False``): its
	new earning replaces this one, and what was spent is the balance's, which may be below zero until the
	next earnings close it (``lots.plan`` spends such a debt first)."""
	src = frappe.get_doc("TEX Loyalty Ledger", entry.name)
	was_final = src.status in FINAL
	expiry = frappe.get_all("TEX Loyalty Ledger", filters={
		"guest": src.guest, "program": src.program, "entry_type": "Expire", "status": ("in", list(FINAL)),
		"reason": lots.marker(src.name)}, fields=["name", "points"]) if was_final else []
	before = balances(src.guest, src.program, lock=True)["available"] if was_final and floor else 0
	frappe.db.set_value("TEX Loyalty Ledger", src.name, {"status": "Reversed",
	                                                    "reason": f"{src.reason or ''} · reversed: {reason}"[:500]})
	for e in expiry:
		frappe.db.set_value("TEX Loyalty Ledger", e.name, "status", "Reversed")
	gone = int(src.points) + sum(int(e.points) for e in expiry)         # what leaves the balance: earned, less expired
	if was_final and floor and before - gone < 0:
		frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": src.program, "guest": src.guest,
		                "entry_type": "Adjust", "points": gone - before, "status": "Available",
		                "booking": src.booking, "reservation": src.reservation, "property": src.property,
		                "reason": f"{reason}: reversal limited to unspent points",
		                "actor": frappe.session.user}).insert(ignore_permissions=True)


def _sync_guest(guest: str) -> None:
	"""The stored points total, from the ledger as it is committed now (locking reads)."""
	total = 0
	for p in frappe.db.sql("""SELECT DISTINCT program FROM `tabTEX Loyalty Ledger` WHERE guest = %s
		LOCK IN SHARE MODE""", guest, pluck=True):
		total += balances(guest, p, lock=True)["available"]
	frappe.db.set_value("Guest", guest, "tex_loyalty_points", total, update_modified=False)


def _commit() -> None:
	"""A scheduler job's batch is its own unit of work in production; tests keep one transaction."""
	if not frappe.flags.in_test:
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- scheduler job batch boundary


# the rows ``lots.plan`` reads: a guest's final rows in one program, by ``tex_ledger_guest_program``; locked,
# so what is planned is what is committed now
LEDGER_ROWS = """SELECT name, entry_type, points, status, available_on, expires_on, creation, reason, booking, property
	FROM `tabTEX Loyalty Ledger` WHERE guest=%s AND program=%s AND status IN ('Available', 'Used', 'Expired')
	ORDER BY creation ASC, name ASC FOR UPDATE"""


def settle(guest: str, program: str, today: date | None = None) -> dict:
	"""Close the guest's lots that are due and take what is left of them (ADR-071), in one step under the
	guest's lock: whoever writes the guest's ledger locks the guest first, then these rows. The daily job
	settles every guest with a lot past its expiry; a redemption and a negative adjustment settle first, so
	points past their expiry are never spent before the job has run."""
	from kamra.tex.crm.service import require_live_guest

	today = today or getdate(nowdate())
	require_live_guest(guest)
	rows = frappe.db.sql(LEDGER_ROWS, (guest, program), as_dict=True)  # nosemgrep -- a constant statement
	plan = lots.plan(rows, today)
	by_name = {r.name: r for r in rows}

	def expire(points: int, reason: str, like: dict | None = None) -> None:
		frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": program, "guest": guest, "entry_type": "Expire",
		                "points": -points, "status": "Expired", "booking": like and like.booking,
		                "property": like and like.property, "reason": reason}).insert(ignore_permissions=True)

	for lot, points in plan["expire"]:
		expire(points, lots.marker(lot), by_name[lot])
	if plan["excess"]:
		expire(plan["excess"], "points returned after their lot expired")
	for lot in plan["close"]:
		frappe.db.set_value("TEX Loyalty Ledger", lot, "status", "Expired", update_modified=False)
	if plan["expire"] or plan["excess"] or plan["close"]:
		_sync_guest(guest)
	return {"expired": sum(p for _lot, p in plan["expire"]) + plan["excess"], "closed": len(plan["close"])}


def mature_and_expire(today: date | None = None) -> dict:
	"""Scheduler (daily): Pending → Available on ``available_on``; then each guest with a lot past its
	``expires_on`` is settled (``settle``): the lot's unspent points expire, first to expire first used."""
	today = today or getdate(nowdate())
	matured = expired = closed = 0
	# every earning TEX writes has its date; a Pending one without it (Desk) has nothing to wait for
	for name in frappe.get_all("TEX Loyalty Ledger", filters={"status": "Pending", "entry_type": "Earn"},
	                           or_filters=[["available_on", "is", "not set"], ["available_on", "<=", today]],
	                           pluck="name"):
		frappe.db.set_value("TEX Loyalty Ledger", name, "status", "Available")
		matured += 1
	# the rows just matured are locked until the commit: a guest is locked only after they are let go, never
	# while holding ledger rows (everywhere else it is the guest first, then its rows; Part 2H-2)
	_commit()
	# a lot without an expiry date (NULL) never expires (NEW-1, ADR-064); one that has closed is Expired, so
	# the day after it expires it is not looked at again
	due = frappe.db.sql("""SELECT DISTINCT guest, program FROM `tabTEX Loyalty Ledger`
		WHERE entry_type = 'Earn' AND status = 'Available' AND expires_on IS NOT NULL AND expires_on < %s
		ORDER BY guest, program""", today)
	for guest, program in due:
		savepoint = "loyalty_settle"
		frappe.db.savepoint(savepoint)
		try:
			done = settle(guest, program, today)
		except Exception:
			undo_to(savepoint)      # one guest's trouble (a profile merged away) is not the rest's
			frappe.log_error(title=f"Loyalty expiry failed: {guest} / {program}")
			_commit()                  # the log is on record, the next guest starts from a clean transaction
			continue
		expired += done["expired"]
		closed += done["closed"]
		_commit()
	return {"matured": matured, "expired_points": expired, "closed": closed}


def _entry_hotels(entries: list[dict]) -> dict[str, str]:
	"""Ledger entry → the hotel it belongs to: its own (``property``, second review of ADR-056), else
	that of the booking (or stay) it belongs to; an older entry without either (a manual adjustment
	of a group program before hotels were recorded) has none."""
	bookings = {e["booking"] for e in entries if e.get("booking") and not e.get("property")}
	stays = {e["reservation"] for e in entries if e.get("reservation") and not e.get("booking")
	         and not e.get("property")}
	hotel = dict(frappe.get_all("TEX Booking", filters={"name": ("in", list(bookings))}, fields=["name", "property"],
	                            as_list=True)) if bookings else {}
	if stays:
		hotel |= dict(frappe.get_all("Reservation", filters={"name": ("in", list(stays))}, fields=["name", "property"],
		                             as_list=True))
	return {e["name"]: e.get("property") or hotel.get(e.get("booking") or e.get("reservation")) for e in entries}


# what an entry of another hotel never shows (ADR-056 and its second review): which booking or stay,
# the stay's dates (its reason, and when its points mature and expire), how its points were earned
# and who made it; when it was written is shown by month only
OTHER_HOTEL_FIELDS = ("booking", "reservation", "reason", "actor", "explanation", "available_on", "expires_on")


def other_hotel(where: str | None, hotels: set[str] | None, program_hotel: str | None) -> bool:
	"""Whether an entry belongs to another hotel than the viewer's (``hotels``; None: no masking). An
	entry of no known hotel is the program's hotel's in a hotel's program, and nobody's to show in a
	group's."""
	if hotels is None:
		return False
	where = where or program_hotel
	return not where or where not in hotels


def mask_other_hotel(entry: dict) -> None:
	for k in OTHER_HOTEL_FIELDS:
		if k in entry:
			entry[k] = None
	if entry.get("creation"):
		entry["creation"] = str(entry["creation"])[:7]


def summary(guest: str, programs: set[str], hotels: set[str] | None = None) -> list[dict]:
	"""The guest's accounts in ``programs``, the programs the viewer may see (their hotels' own
	or their group's; another tenant's program is never shown, G-65).

	A program's balance is one balance wherever it was earned, so it is shown whole. ``hotels``
	(the viewer's): an entry of another hotel of a shared (group) program shows its points and
	status and the month it was written, never its booking, reason, dates or who made it (ADR-056
	and its second review; as consent entries made at another hotel, ADR-046)."""
	out = []
	for p in frappe.get_all("TEX Loyalty Ledger", filters={"guest": guest, "program": ("in", list(programs) or [""])},
	                        pluck="program", distinct=True, order_by="program asc"):
		prog = frappe.get_cached_doc("TEX Loyalty Program", p)
		b = balances(guest, p)
		tier = tier_of(prog, b["lifetime_earned"])
		entries = frappe.get_all("TEX Loyalty Ledger", filters={"guest": guest, "program": p},
		                         fields=["name", "entry_type", "points", "status", "available_on", "expires_on",
		                                 "booking", "reservation", "property", "reason", "creation"],
		                         order_by="creation desc", limit=50)
		where = _entry_hotels(entries)
		for e in entries:
			for k in ("available_on", "expires_on", "creation"):
				e[k] = str(e[k]) if e[k] else None
			e["other_hotel"] = other_hotel(where[e["name"]], hotels, prog.property)
			if e["other_hotel"]:
				mask_other_hotel(e)
			e.pop("reservation", None)
			e.pop("property", None)
		# below zero: points spent before a stay changed and earned less (O-21); owed, paid off by the next ones
		# earned, never money (LO-25)
		out.append({"program": p, "program_name": prog.program_name, "currency": prog.currency, **b,
		            "debt": max(0, -b["available"]),
		            "value": to_str(quantize(db_dec(prog.point_value) * max(0, b["available"]), prog.currency or "EUR")),
		            "tier": tier.tier_name if tier else None, "entries": entries})
	return out


def adjust(guest: str, program: str, points: int, reason: str, property: str | None = None) -> str:
	"""A manual adjustment, made for one hotel of the program (``property``; the only one the user may
	edit guests at when not given): the hotel it belongs to, whose staff see its reason and who made
	it (ADR-056 second review)."""
	prog = frappe.get_doc("TEX Loyalty Program", program)
	props = [prog.property] if prog.property else frappe.get_all("Property", filters={
		"tex_hotel_group": prog.hotel_group}, pluck="name")
	permitted = scope.permitted_properties()
	editable = sorted(p for p in props if p in permitted and scope.has_capability("crm.edit", p))
	if not editable or (property and property not in editable):
		frappe.throw(_("Not permitted: {0}.").format("crm.edit"), frappe.PermissionError)
	if not property:
		if len(editable) > 1:
			frappe.throw(_("Choose the hotel this adjustment is made for."))
		property = editable[0]
	if not (reason or "").strip():
		frappe.throw(_("A reason is required."))
	points = int(points)
	if points == 0:
		frappe.throw(_("Points must not be zero."))
	# the profile locked and its balance read with a lock, as a redemption does (third review of ADR-056)
	from kamra.tex.crm.service import require_live_guest

	require_live_guest(guest)
	if points < 0:
		settle(guest, program)                      # points past their expiry are not there to take (ADR-071)
	if points < 0 and balances(guest, program, lock=True)["available"] + points < 0:
		frappe.throw(_("The balance cannot go negative."))
	doc = frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": program, "guest": guest,
	                      "entry_type": "Adjust", "points": points, "status": "Available", "reason": reason[:500],
	                      "property": property, "actor": frappe.session.user}).insert(ignore_permissions=True)
	_sync_guest(guest)
	audit("loyalty.adjust", reference_doctype="TEX Loyalty Ledger", reference_name=doc.name,
	      property=property, new={"guest": guest, "points": points}, reason=reason)
	return doc.name


# the points already on a booking, read with locks that each go by an index — the booking, or the charges'
# names — so they hold this booking's rows only, never every payment of every hotel (O-19 review)
LOYALTY_ON_BOOKING = """SELECT name FROM `tabTEX Payment Transaction` WHERE booking=%(b)s AND provider='Loyalty'
                        AND status='Succeeded' AND txn_type='Charge' LOCK IN SHARE MODE"""
ALLOCATED_TO_BOOKING = """SELECT DISTINCT `transaction` FROM `tabTEX Payment Allocation` WHERE booking=%(b)s
                          LOCK IN SHARE MODE"""
LOYALTY_NAMED = """SELECT name FROM `tabTEX Payment Transaction` WHERE name IN %(names)s AND provider='Loyalty'
                   AND status='Succeeded' AND txn_type='Charge' LOCK IN SHARE MODE"""


def loyalty_charges_on(booking: str) -> list[str]:
	"""The succeeded Loyalty charges of ``booking``: redeemed for it, or allocated to it (name order)."""
	own = set(frappe.db.sql_list(LOYALTY_ON_BOOKING, {"b": booking}))
	allocated = frappe.db.sql_list(ALLOCATED_TO_BOOKING, {"b": booking})
	moved = set(frappe.db.sql_list(LOYALTY_NAMED, {"names": tuple(allocated)})) if allocated else set()
	return sorted(own | moved)


def redeemable(b, pct) -> D:
	"""O-19 (audit 2B, ADR-065): the most points may still pay of booking ``b`` (locked by the caller):
	its program's share of its total (``pct``) less the points already on it, and never more than it
	still owes — so points are never paid back as cash. "On it": what the booking holds of its
	succeeded Loyalty payments (``booking_nets``), read with locking reads."""
	from kamra.tex.payments import service as pay

	ccy = b.currency
	total, paid = from_db(b.total_amount, ccy), from_db(b.paid_amount, ccy)
	on_it = sum((pay.booking_nets(t, lock=True).get(b.name, ZERO) for t in loyalty_charges_on(b.name)), ZERO)
	return quantize(max(ZERO, min(quantize(total * pct / 100, ccy) - on_it, total - paid)), ccy)


def redeem(guest: str, booking: str, points: int, *, idempotency_key: str) -> dict:
	"""Burn points as a payment on a booking (min points, max % of the booking, currency)."""
	b = frappe.get_doc("TEX Booking", booking)
	scope.require("payment.link", b.property)
	if b.get("channel_connection"):
		# an OTA booking's price and payment are the channel's (D-11, LO-02), as for its extras and changes
		frappe.throw(_("Points cannot be redeemed on a channel's booking: its price and payment are the channel's."))
	guests = {b.booker_guest} | set(frappe.get_all("Reservation", filters={"tex_booking": booking}, pluck="guest"))
	if guest not in guests:
		frappe.throw(_("The booking belongs to another guest."))
	program = program_for(b.property)
	if not program:
		frappe.throw(_("This hotel has no loyalty program."))
	prog = frappe.get_doc("TEX Loyalty Program", program)
	if prog.currency and prog.currency != b.currency:
		frappe.throw(_("Points can only be redeemed on {0} bookings.").format(prog.currency))
	pct = db_dec(prog.max_redeem_percent if prog.max_redeem_percent is not None else 100)
	if pct <= 0:
		frappe.throw(_("Points cannot be redeemed in this program."))
	for r in frappe.get_all("Reservation", filters={"tex_booking": booking, "status": ("not in", ["Cancelled",
	                                                                                               "No Show"])},
	                        fields=["check_in_date", "check_out_date"]):
		ci, co = getdate(r.check_in_date), getdate(r.check_out_date)
		blocked = next((ci + timedelta(days=i) for i in range(max((co - ci).days, 1))
		                if _in_blackout(prog, ci + timedelta(days=i), "Redemption")), None)
		if blocked:
			frappe.throw(_("Points cannot be redeemed for stays on {0}.").format(frappe.format(blocked, "Date")))
	from kamra.tex.payments.service import ns_key

	idempotency_key = ns_key(b.property, idempotency_key, "loyalty")
	if not idempotency_key:
		frappe.throw(_("Idempotency key required."))
	done = frappe.db.get_value("TEX Payment Transaction", {"idempotency_key": idempotency_key}, "name")
	if done:
		return {"transaction": done, "replay": True}
	points = int(points)
	if points < int(prog.min_redeem_points or 0) or points <= 0:
		frappe.throw(_("At least {0} points must be redeemed.").format(prog.min_redeem_points or 1))
	from kamra.tex.payments import service as pay

	# a booking that cannot take the money is refused before a point is burned (C5)
	pay.refuse_if_it_cannot_take(booking, quantize(db_dec(prog.point_value) * points, b.currency))
	# its total and what it holds read under its lock (taken just now), as they are now (O-19)
	b = frappe.get_doc("TEX Booking", booking, for_update=True)
	# the profile locked (whoever writes its ledger locks it too) and its balance read with a lock: what is
	# committed now, not this request's snapshot, so two redemptions never spend the same points (third
	# review of ADR-056, H-1); a profile merged into another meanwhile is gone
	if not frappe.db.sql("SELECT name FROM `tabGuest` WHERE name=%s FOR UPDATE", guest):
		frappe.throw(_("Guest {0} no longer exists: it was merged into another profile or removed.").format(guest),
		             frappe.DoesNotExistError)
	settle(guest, program)                          # points past their expiry cannot be spent (ADR-071)
	if balances(guest, program, lock=True)["available"] < points:
		frappe.throw(_("Not enough points."))
	value = quantize(db_dec(prog.point_value) * points, b.currency)
	cap = redeemable(b, pct)
	if value > cap:
		most = int(cap / db_dec(prog.point_value)) if db_dec(prog.point_value) > 0 else 0
		frappe.throw(_("Points can cover at most {0} {1} of this booking now ({2} points).").format(
			to_str(cap), b.currency, most))

	txn = frappe.get_doc({"doctype": "TEX Payment Transaction", "property": b.property, "txn_type": "Charge",
	                      "status": "Succeeded", "method": "Manual", "provider": "Loyalty", "amount": value,
	                      "currency": b.currency, "idempotency_key": idempotency_key, "booking": booking,
	                      "provider_ref": f"{points} pts", "raw_status": "REDEEMED", "completed_at": now_datetime(),
	                      "actor": frappe.session.user, "reason": f"loyalty {program}"})
	txn.insert(ignore_permissions=True)
	pay.allocate(txn.name, booking=booking, amount=value, reason="loyalty redemption", _system=True)
	led = frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": program, "guest": guest, "entry_type": "Burn",
	                      "points": -points, "status": "Used", "booking": booking, "property": b.property,
	                      "reason": f"redeemed as {txn.name}", "actor": frappe.session.user}).insert(
		ignore_permissions=True)
	_sync_guest(guest)
	audit("loyalty.redeem", reference_doctype="TEX Loyalty Ledger", reference_name=led.name, property=b.property,
	      new={"booking": booking, "points": points, "value": to_str(value), "transaction": txn.name})
	return {"transaction": txn.name, "ledger": led.name, "value": to_str(value), "currency": b.currency}


# a booking's refunds the gateway has not answered (Pending): their money may be gone already. By ``booking``
# (indexed); read with a lock, as it is now
PENDING_REFUNDS_OF = """SELECT amount, currency FROM `tabTEX Payment Transaction` WHERE booking=%(b)s
                        AND txn_type='Refund' AND status='Pending' LOCK IN SHARE MODE"""
# the burn rows of a booking's Loyalty charges: its guests' rows by ``tex_ledger_guest_program`` (guest), narrowed by
# the booking and by the charge each was redeemed as. A NULL booking or reason matches nothing: a burn that names no
# booking or charge is not one of these. Locked, after the guests and the charges (ADR-071 §4)
BURNS_OF = """SELECT name, guest, program, points, property, reason FROM `tabTEX Loyalty Ledger`
              WHERE guest IN %(guests)s AND entry_type='Burn' AND booking IN %(bookings)s AND reason IN %(reasons)s
              FOR UPDATE"""
# who spent the points of these charges, wherever they are now (LO-06): a plain read by the bookings they were
# redeemed for (indexed), so their profiles are locked before the charges
BURNERS_OF = """SELECT DISTINCT guest FROM `tabTEX Loyalty Ledger`
                WHERE booking IN %(bookings)s AND entry_type='Burn' AND reason IN %(reasons)s"""


def return_points(booking: str, *, reason: str) -> int:
	"""A booking that is cancelled or expires gives back as points, never as money, what its Loyalty charges
	hold beyond what it now costs (O-20, D-16, ADR-071 §4), the newest charge first: the share comes off the
	booking as a Loyalty refund (``payments.points_back``) and its points come back, pro rata, as a positive
	Reverse row of the guest who spent them; a lot that closed meanwhile is never reopened (``settle``: D-16a).
	What a cancellation keeps (a penalty not refunded) keeps its points as it keeps its cash. By state: what the
	booking holds beyond its cost is what is left to give, so a second call gives back nothing.

	The caller holds the booking's lock (and its rooms'). Locks taken here: the guests who may have spent
	points on it, the Loyalty charges (name order), then their burn rows. → the points given back."""
	return sum((s["points"] for s in give_back(booking, reason=reason)), 0)


def give_back(booking: str, *, reason: str, limit=None) -> list[dict]:
	"""``return_points``, at most ``limit`` of money (a lower price's refund, LO-01: the points' share of it comes
	back as points before any cash). → each share given back: {"transaction", "refund", "amount", "points"}."""
	from kamra.tex.crm.service import lock_guest
	from kamra.tex.payments import service as pay

	b = frappe.db.get_value("TEX Booking", booking, ["property", "currency", "booker_guest", "paid_amount",
	                                                  "total_amount"], as_dict=True, for_update=True)
	if not b:
		return []
	ccy = b.currency
	waiting = sum((from_db(r.amount, r.currency) for r in frappe.db.sql(PENDING_REFUNDS_OF, {"b": booking}, as_dict=True)),
	              ZERO)
	over = from_db(b.paid_amount, ccy) - from_db(b.total_amount, ccy) - waiting
	if limit is not None:
		over = min(over, D(limit))
	charges = loyalty_charges_on(booking) if over > 0 else []
	if not charges:
		return []
	# a charge's burn row is on the booking it was redeemed for (this one, or one staff moved it from) and is the
	# burner's, on the booking or not any more (LO-06)
	homes = tuple(sorted({booking, *(h for h in frappe.get_all("TEX Payment Transaction", filters={
		"name": ("in", charges)}, pluck="booking") if h)}))
	reasons = tuple(f"redeemed as {c}" for c in charges)
	guests = sorted({b.booker_guest, *frappe.get_all("Reservation", filters={"tex_booking": booking}, pluck="guest"),
	                 *frappe.db.sql_list(BURNERS_OF, {"bookings": homes, "reasons": reasons})} - {None})
	for g in guests:
		lock_guest(g)                                  # a profile merged away holds no points here
	rows = []
	for name in charges:                               # name order: the order every writer of them takes
		t = frappe.db.get_value("TEX Payment Transaction", name, ["name", "amount", "currency", "creation"],
		                        as_dict=True, for_update=True)
		held = pay.booking_nets(name, lock=True).get(booking, ZERO) - pay.in_flight_from(name, booking, lock=True)
		if held > ZERO:
			rows.append((t, held))
	burns = {}
	if rows and guests:
		for r in frappe.db.sql(BURNS_OF, {"guests": tuple(guests), "bookings": homes,
		                                  "reasons": tuple(f"redeemed as {t.name}" for t, _h in rows)}, as_dict=True):
			burns[r.reason] = r
	left, points, shares, settle_for = over, 0, [], {}
	for t, held in sorted(rows, key=lambda r: (r[0].creation, r[0].name), reverse=True):
		if left <= ZERO:
			break
		burn = burns.get(f"redeemed as {t.name}")
		if not burn:
			frappe.log_error(title=f"Loyalty points not returned: {t.name}",
			                 message=f"No burn row of {booking} for the Loyalty charge {t.name}: its money was left for staff.")
			continue
		take = min(held, left)
		pts = lots.points_of(-int(burn.points), from_db(t.amount, t.currency), pay.refunded_of(t.name, lock=True), take)
		refund = pay.points_back(t.name, booking=booking, amount=take, points=pts, reason=reason)
		if pts:
			frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": burn.program, "guest": burn.guest,
			                "entry_type": "Reverse", "points": pts, "status": "Available", "booking": booking,
			                "property": burn.property or b.property, "reason": f"points returned: {reason} ({t.name})"[:500],
			                "actor": frappe.session.user}).insert(ignore_permissions=True)
		settle_for[(burn.guest, burn.program)] = None
		left -= take
		points += pts
		shares.append({"transaction": t.name, "refund": refund, "amount": to_str(take), "points": pts})
	for guest, program in settle_for:
		settle(guest, program)                         # a lot closed meanwhile: the points that came back expire at once
		_sync_guest(guest)
	if shares:
		audit("loyalty.return", reference_doctype="TEX Booking", reference_name=booking, property=b.property,
		      new={"points": points, "value": to_str(over - left), "currency": ccy,
		           "charges": [{k: v for k, v in s.items() if k != "refund"} for s in shares]}, reason=reason)
	return shares
