"""Guest notifications (transactional e-mail) for TEX bookings and payment links.

Bearer secrets (manage-booking tokens, payment-link tokens) exist in clear only at
the moment they are created; they go straight into the e-mail and are never stored
or logged. Every message is recorded as a ``TEX Communication`` (without the link).
Sending is best-effort: a mail problem never fails the booking or the payment.
"""

from __future__ import annotations

import frappe
from frappe.utils import escape_html, get_url

from kamra.tex.lib_text import render
from kamra.tex.money import from_db, to_str
from kamra.tex.security.audit import log_exception

LANGS = ("en", "tr", "de", "ru", "ro", "pl")


def _site_slug(property: str, booking_site: str | None) -> str | None:
	if booking_site:
		return frappe.db.get_value("TEX Booking Site", booking_site, "site_slug")
	slug = frappe.db.get_value("TEX Booking Site", {"property": property, "enabled": 1}, "site_slug")
	if slug:
		return slug
	group = frappe.db.get_value("Property", property, "tex_hotel_group")
	return frappe.db.get_value("TEX Booking Site", {"hotel_group": group, "enabled": 1}, "site_slug") if group else None


def manage_url(property: str, booking_site: str | None, token: str) -> str | None:
	slug = _site_slug(property, booking_site)
	# the token travels in the URL fragment, which browsers never send to servers
	return get_url(f"/book/{slug}/manage#token={token}") if slug else None


def _amount(value, ccy: str | None) -> str:
	ccy = ccy or "EUR"
	return f"{to_str(from_db(value or 0, ccy))} {ccy}"


def _log(guest: str | None, property: str, subject: str, template: str, *, booking: str | None = None) -> None:
	if not guest:
		return
	frappe.get_doc({"doctype": "TEX Communication", "guest": guest, "property": property, "booking": booking,
	                "channel": "Email", "direction": "Outbound", "status": "Queued",
	                "consent_basis": "Transactional", "template": template, "subject": subject[:140],
	                "sent_at": frappe.utils.now_datetime(), "actor": frappe.session.user}).insert(
		ignore_permissions=True)


def _send(to: str, subject: str, html: str, *, reference: tuple[str, str]) -> None:
	frappe.sendmail(recipients=[to], subject=subject, message=html, reference_doctype=reference[0],
	                reference_name=reference[1], delayed=True)


def booking_created(booking: str, manage_token: str) -> bool:
	"""Booking e-mail with the manage link. True when it was queued."""
	try:
		b = frappe.get_doc("TEX Booking", booking)
		if not b.booker_email:
			return False
		lang = (b.language or "en")[:2]
		lang = lang if lang in LANGS else "en"
		hotel = frappe.db.get_value("Property", b.property, "property_name") or b.property
		link = manage_url(b.property, b.booking_site, manage_token)
		key = "booking_confirmed" if b.status == "Confirmed" else "booking_pending"
		subject, body = render(key, lang, hotel=escape_html(hotel), ref=escape_html(b.name),
		                       name=escape_html(b.booker_name or ""), total=escape_html(_amount(b.total_amount, b.currency)),
		                       link=link or "")
		_send(b.booker_email, subject, body, reference=("TEX Booking", b.name))
		_log(b.booker_guest, b.property, subject, key, booking=b.name)
		return True
	except Exception:
		log_exception(f"TEX booking e-mail {booking}")
		return False


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
		_send(b.booker_email, subject, body, reference=("TEX Booking", b.name))
		_log(b.booker_guest, b.property, subject, "payment_received", booking=b.name)
	except Exception:
		log_exception(f"TEX confirmation e-mail {booking}")


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
		_send(link.guest_email, subject, body, reference=("TEX Payment Link", link.name))
		guest = frappe.db.get_value("TEX Booking", link.booking, "booker_guest") if link.booking else None
		_log(guest, link.property, subject, "payment_link", booking=link.booking)
		return True
	except Exception:
		log_exception(f"TEX payment-link e-mail {link_name}")
		return False
