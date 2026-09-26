"""Guest notifications (transactional e-mail) for TEX bookings and payment links, and the hotel
reservations team's notice of money kept off a booking (B5).

Bearer secrets (manage-booking tokens, payment-link tokens) exist in clear only at
the moment they are created; they go straight into the e-mail and are never stored
or logged. Every message is recorded as a ``TEX Communication`` (without the link).
Sending is best-effort: a mail problem never fails the booking or the payment.

"Queued" means Frappe's e-mail queue took the message, not that it was sent: the
communication keeps the queue entry (``email_queue``) and ``services.mail_status`` moves it
to Sent or Failed when the queue does (ADR-047). A message the queue refused (no outgoing
account) is recorded as Failed with the reason, so staff see the attempt.

A guest mail is sent in the hotel's name: the From display name is the hotel, the From
address is always the site's own default outgoing account (never an address of the hotel's
domain, which would be spoofing through this mail server), and Reply-To is the hotel's
e-mail (else its booking site's contact e-mail) when that is a valid address.
"""

from __future__ import annotations

from email.utils import formataddr

import frappe
from frappe.utils import escape_html, validate_email_address

from kamra.tex.lib_text import AFTER_EXPIRY_NEXT, render
from kamra.tex.money import from_db, to_str
from kamra.tex.security.audit import log_exception
from kamra.tex.services.txn import transaction_lost, undo_step

LANGS = ("en", "tr", "de", "ru", "ro", "pl")


def manage_url(property: str, booking_site: str | None, token: str) -> str | None:
	from kamra.tex.services import sites

	site = sites.site_for(property, booking_site)
	# the token travels in the URL fragment, which browsers never send to servers; the link
	# opens on the site's own host when it has one (G-21), never on a request's Host header
	return sites.guest_url(site, f"manage#token={token}") if site else None


def _amount(value, ccy: str | None) -> str:
	ccy = ccy or "EUR"
	return f"{to_str(from_db(value or 0, ccy))} {ccy}"


def _log(guest: str | None, property: str, subject: str, template: str, *, booking: str | None = None,
         email_queue: str | None = None, error: str | None = None) -> str | None:
	if not guest:
		return None
	return frappe.get_doc({
		"doctype": "TEX Communication", "guest": guest, "property": property, "booking": booking,
		"channel": "Email", "direction": "Outbound", "status": "Queued" if email_queue else "Failed",
		"consent_basis": "Transactional", "template": template, "subject": subject[:140],
		"sent_at": frappe.utils.now_datetime(), "actor": frappe.session.user, "email_queue": email_queue,
		"delivery_error": None if email_queue else (error or "NotQueued")[:140]}).insert(ignore_permissions=True).name


def hotel_sender(property: str, booking_site: str | None = None) -> tuple[str | None, str | None]:
	"""(From, Reply-To) of a hotel's guest mail. From: the hotel's name with the default
	outgoing account's own address (None without an account: Frappe then reports the missing
	account). Reply-To: the hotel's e-mail, else its booking site's contact e-mail, if valid."""
	from kamra.tex.services import sites

	account = frappe.db.get_value("Email Account", {"default_outgoing": 1, "enable_outgoing": 1}, "email_id")
	hotel = frappe.db.get_value("Property", property, ["property_name", "email"], as_dict=True) or {}
	name = " ".join(str(hotel.get("property_name") or property or "").split())[:80]
	sender = formataddr((name, account)) if account and name else None
	site = sites.site_for(property, booking_site)
	candidates = [hotel.get("email"), frappe.db.get_value("TEX Booking Site", site, "contact_email") if site else None]
	reply_to = next((e.strip() for e in candidates if e and validate_email_address(e.strip())), None)
	return sender, reply_to


def _send(to: str, subject: str, html: str, *, reference: tuple[str, str], property: str | None = None,
          booking_site: str | None = None) -> str | None:
	"""Queue the mail; the Email Queue name, or None when the queue took nothing (e.g. every
	recipient unsubscribed)."""
	sender, reply_to = hotel_sender(property, booking_site) if property else (None, None)
	q = frappe.sendmail(recipients=[to], subject=subject, message=html, reference_doctype=reference[0],
	                    reference_name=reference[1], delayed=True, sender=sender, reply_to=reply_to)
	return getattr(q, "name", None) or None


SEND_SAVEPOINT, LOG_SAVEPOINT = "tex_mail_send", "tex_mail_log"


def _deliver(to: str, subject: str, html: str, *, reference: tuple[str, str], guest: str | None, property: str,
             template: str, booking: str | None, log_title: str, booking_site: str | None = None) -> dict:
	"""Queue one guest e-mail and record what happened. Never raises for a mail problem:
	{"queued": bool, "status": "Queued" | "Failed", "communication": name | None}. Each step (the queue
	row, the record) is undone to its savepoint when it fails, a lock wait timeout included, which undoes
	only its statement. A deadlock is not a mail problem: the caller's transaction is gone, so it is
	raised (``txn.undo_step``; ADR-056 second and third reviews)."""
	messages = getattr(frappe.local, "message_log", None)
	seen = len(messages) if isinstance(messages, list) else 0
	frappe.db.savepoint(SEND_SAVEPOINT)
	try:
		queue, error = _send(to, subject, html, reference=reference, property=property,
		                     booking_site=booking_site), None
	except Exception as e:
		undo_step(e, SEND_SAVEPOINT)
		log_exception(log_title)
		if isinstance(messages, list):
			del messages[seen:]              # the refusal is reported by the status, never shown to a guest
		queue, error = None, type(e).__name__
	frappe.db.savepoint(LOG_SAVEPOINT)
	try:
		comm = _log(guest, property, subject, template, booking=booking, email_queue=queue, error=error)
	except Exception as e:
		undo_step(e, LOG_SAVEPOINT)
		log_exception(log_title)
		comm = None
	return {"queued": bool(queue), "status": "Queued" if queue else "Failed", "communication": comm}


def booking_created(booking: str, manage_token: str) -> bool:
	"""Booking e-mail with the manage link. True when it was queued."""
	return booking_mail(booking, manage_token)["queued"]


def booking_mail(booking: str, manage_token: str) -> dict:
	"""Booking e-mail with the manage link: {"queued", "status", "communication"}."""
	try:
		b = frappe.get_doc("TEX Booking", booking)
		if not b.booker_email:
			return {"queued": False, "status": "Failed", "communication": None}
		lang = (b.language or "en")[:2]
		lang = lang if lang in LANGS else "en"
		hotel = frappe.db.get_value("Property", b.property, "property_name") or b.property
		link = manage_url(b.property, b.booking_site, manage_token)
		key = "booking_confirmed" if b.status == "Confirmed" else "booking_pending"
		subject, body = render(key, lang, hotel=escape_html(hotel), ref=escape_html(b.name),
		                       name=escape_html(b.booker_name or ""), total=escape_html(_amount(b.total_amount, b.currency)),
		                       link=link or "")
	except Exception as e:
		if transaction_lost(e):
			raise                            # reads only: nothing to undo, but the transaction is gone
		log_exception(f"TEX booking e-mail {booking}")
		return {"queued": False, "status": "Failed", "communication": None}
	return _deliver(b.booker_email, subject, body, reference=("TEX Booking", b.name), guest=b.booker_guest,
	                property=b.property, template=key, booking=b.name, log_title=f"TEX booking e-mail {booking}",
	                booking_site=b.booking_site)


def booking_confirmed(booking: str) -> None:
	"""Payment received after a pending booking: short confirmation, no secret link."""
	try:
		b = frappe.get_doc("TEX Booking", booking)
		if not b.booker_email:
			return
		lang = (b.language or "en")[:2]
		lang = lang if lang in LANGS else "en"
		hotel = frappe.db.get_value("Property", b.property, "property_name") or b.property
		subject, body = render("payment_received", lang, hotel=escape_html(hotel), ref=escape_html(b.name),
		                       name=escape_html(b.booker_name or ""), total=escape_html(_amount(b.total_amount, b.currency)),
		                       link="")
	except Exception as e:
		if transaction_lost(e):
			raise                            # reads only: nothing to undo, but the transaction is gone
		log_exception(f"TEX confirmation e-mail {booking}")
		return
	_deliver(b.booker_email, subject, body, reference=("TEX Booking", b.name), guest=b.booker_guest,
	         property=b.property, template="payment_received", booking=b.name,
	         log_title=f"TEX confirmation e-mail {booking}", booking_site=b.booking_site)


def payment_link(link_name: str, url: str, lang: str = "en") -> bool:
	try:
		link = frappe.get_doc("TEX Payment Link", link_name)
		if not link.guest_email:
			return False
		hotel = frappe.db.get_value("Property", link.property, "property_name") or link.property
		lang = lang if lang in LANGS else "en"
		subject, body = render("payment_link", lang, hotel=escape_html(hotel), ref=escape_html(link.booking or link.name),
		                       name=escape_html(link.guest_name or ""), total=escape_html(_amount(link.amount, link.currency)),
		                       link=url)
		guest = frappe.db.get_value("TEX Booking", link.booking, "booker_guest") if link.booking else None
	except Exception as e:
		if transaction_lost(e):
			raise                            # reads only: nothing to undo, but the transaction is gone
		log_exception(f"TEX payment-link e-mail {link_name}")
		return False
	return _deliver(link.guest_email, subject, body, reference=("TEX Payment Link", link.name), guest=guest,
	                property=link.property, template="payment_link", booking=link.booking,
	                log_title=f"TEX payment-link e-mail {link_name}")["queued"]


def reconciliation(txn, booking: str, state: str, note: str, amount) -> None:
	"""B5: money kept off its booking (reconciliation). The hotel's reservations team is e-mailed (the
	hotel's e-mail, else the TEX Settings status-alert recipients); the guest who paid — not money staff
	took at the desk, whom they already told — is told the booking could not take it and what happens
	to it (``payment_after_expiry``). Best-effort: never fails the payment."""
	team_notice(txn, booking, state, note, amount)
	if txn.provider != "Manual":
		payment_after_expiry(booking, "refund" if state == "Refund Queued" else "contact", amount, txn.currency)


def team_recipients(property: str) -> list[str]:
	from kamra.tex.ops import alerts

	email = (frappe.db.get_value("Property", property, "email") or "").strip()
	return [email] if email and validate_email_address(email) else alerts.recipients()


def team_notice(txn, booking: str | None, state: str, note: str, amount) -> None:
	"""The hotel's reservations team: a payment is in reconciliation (``state``), why, and where to act."""
	try:
		to = team_recipients(txn.property)
		subject = f"TEX: payment {txn.name} for booking {booking or '-'} is in reconciliation ({state})"
		body = (f"A payment of <b>{escape_html(to_str(amount))} {escape_html(txn.currency)}</b> ({escape_html(txn.name)}, "
		        f"{escape_html(txn.method or '')}) could not be taken by booking <b>{escape_html(booking or '-')}</b>: it is kept "
		        f"off the booking in reconciliation, <b>{escape_html(state)}</b>.<br><br>{escape_html(note)}<br><br>"
		        "Open TEX → Payments → this payment to allocate or refund it.")
	except Exception as e:
		if transaction_lost(e):
			raise
		log_exception(f"TEX reconciliation notice {txn.name}")
		return
	for address in to:
		_deliver(address, subject, body, reference=("TEX Payment Transaction", txn.name), guest=None,
		         property=txn.property, template="reconciliation_notice", booking=booking,
		         log_title=f"TEX reconciliation notice {txn.name}")


def payment_after_expiry(booking: str, next_step: str, amount, currency: str) -> None:
	"""The guest: their payment of ``amount`` came when the booking could no longer take it; ``next_step``
	"refund" (refunded by itself) or "contact" (the hotel decides)."""
	try:
		b = frappe.get_doc("TEX Booking", booking)
		if not b.booker_email:
			return
		lang = (b.language or "en")[:2]
		lang = lang if lang in LANGS else "en"
		hotel = frappe.db.get_value("Property", b.property, "property_name") or b.property
		subject, body = render("payment_after_expiry", lang, hotel=escape_html(hotel), ref=escape_html(b.name),
		                       name=escape_html(b.booker_name or ""),
		                       total=escape_html(f"{to_str(amount)} {currency}"),
		                       next=AFTER_EXPIRY_NEXT[next_step][lang])
	except Exception as e:
		if transaction_lost(e):
			raise                            # reads only: nothing to undo, but the transaction is gone
		log_exception(f"TEX late payment e-mail {booking}")
		return
	_deliver(b.booker_email, subject, body, reference=("TEX Booking", b.name), guest=b.booker_guest,
	         property=b.property, template="payment_after_expiry", booking=b.name,
	         log_title=f"TEX late payment e-mail {booking}", booking_site=b.booking_site)
