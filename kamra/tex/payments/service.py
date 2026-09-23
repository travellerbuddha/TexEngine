"""TEX Payments service (R-40, R-41, ADR-016).

Every money movement is a TEX Payment Transaction (idempotent by key) plus, for
charges applied to a booking, a TEX Payment Allocation. Refunds, reallocations and
transfers are new rows — nothing is edited away. Callbacks are verified by the
provider adapter; completing the same transaction twice is a no-op.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, get_url, now_datetime

from kamra.tex.money import ZERO, D, from_db, quantize, to_str
from kamra.tex.payments.providers import simple, turkey
from kamra.tex.payments.providers.base import Intent, Outcome, ProviderError
from kamra.tex.security import scope
from kamra.tex.security.audit import audit, log_exception


def _mock_secret() -> str:
	key = frappe.local.conf.get("encryption_key") or frappe.local.site
	return hashlib.sha256(("tex-mock-pay:" + str(key)).encode()).hexdigest()


def ns_key(property: str, raw: str | None, kind: str) -> str | None:
	"""Staff-supplied idempotency keys are namespaced per hotel and purpose, so a key
	reused elsewhere can neither collide nor replay another hotel's record."""
	raw = (raw or "").strip()[:140]
	if not raw:
		return None
	return hashlib.sha256(f"{kind}|{property}|{raw}".encode()).hexdigest()


def callback_signature(transaction: str) -> str:
	"""Signs the gateway return URL so arbitrary transaction ids cannot be poked."""
	key = frappe.local.conf.get("encryption_key") or frappe.local.site
	return hmac.new(("tex-callback:" + str(key)).encode(), transaction.encode(), hashlib.sha256).hexdigest()[:32]


def allowed_return_hosts(property: str) -> set[str]:
	from urllib.parse import urlparse

	hosts = {urlparse(get_url()).hostname}
	group = frappe.db.get_value("Property", property, "tex_hotel_group")
	sites = frappe.get_all("TEX Booking Site", or_filters={"property": property, "hotel_group": group or "__none__"},
	                       pluck="name")
	if sites:
		hosts |= set(frappe.get_all("TEX Booking Domain", filters={"parent": ("in", sites), "verified": 1},
		                            pluck="domain"))
	return hosts


def check_return_url(property: str, url: str) -> str:
	"""Open-redirect guard for every payment flow (ADR-021)."""
	from urllib.parse import urlparse

	u = urlparse(url or "")
	if u.scheme not in ("https", "http") or (u.scheme == "http" and not frappe.conf.get("developer_mode")) \
			or u.hostname not in allowed_return_hosts(property):
		frappe.throw(_("Invalid return address."), frappe.ValidationError)
	return url


def provider_for(account_name: str):
	acc = frappe.get_doc("TEX Payment Provider Account", account_name)
	if not acc.enabled:
		frappe.throw(_("Payment provider {0} is disabled.").format(acc.label))
	return {
		"Mock": lambda: simple.MockProvider(acc, _mock_secret()),
		"Bank Transfer": lambda: simple.BankTransferProvider(acc),
		"Pay at Hotel": lambda: simple.PayAtHotelProvider(acc),
		"iyzico": lambda: turkey.IyzicoProvider(acc),
		"Sipay": lambda: turkey.SipayProvider(acc),
		"Virtual POS": lambda: turkey.NestPayProvider(acc),
	}[acc.provider]()


# ─── method selection ────────────────────────────────────────────────────


def payment_methods(property: str, *, market: str | None, currency: str | None, channel: str | None) -> list[dict]:
	"""Methods offered for this hotel/market/currency/channel (most specific rules win
	per method; a rule with a blank dimension matches any value)."""
	rows = frappe.get_all("TEX Payment Method Rule", filters={"property": property, "disabled": 0},
	                      fields=["name", "method", "provider_account", "market", "currency", "sales_channel",
	                              "priority"])
	best: dict[str, tuple] = {}
	for r in rows:
		if (r.market and r.market != market) or (r.currency and r.currency != currency) \
				or (r.sales_channel and r.sales_channel != channel):
			continue
		spec = (bool(r.market) + bool(r.currency) + bool(r.sales_channel), r.priority or 0, r.name)
		if r.method not in best or spec > best[r.method][0]:
			best[r.method] = (spec, r)
	out = []
	for method, (_spec, r) in sorted(best.items(), key=lambda x: (-x[1][0][1], x[0])):
		acc = frappe.db.get_value("TEX Payment Provider Account", r.provider_account,
		                          ["provider", "label", "environment", "enabled", "currencies"], as_dict=True) \
			if r.provider_account else None
		if r.provider_account and (not acc or not acc.enabled):
			continue
		if acc and acc.currencies and currency and currency not in [c.strip() for c in acc.currencies.split(",")]:
			continue
		out.append({"method": method, "provider_account": r.provider_account,
		            "provider": acc.provider if acc else ("Pay at Hotel" if method == "Pay at Hotel" else None),
		            "label": acc.label if acc else method, "sandbox": (acc.environment == "Sandbox") if acc else False})
	return out


# ─── transactions ────────────────────────────────────────────────────────


def _new_txn(**kw) -> frappe.model.document.Document:
	doc = frappe.get_doc({"doctype": "TEX Payment Transaction", "status": "Pending", "actor": frappe.session.user,
	                      **kw})
	doc.insert(ignore_permissions=True)
	return doc


def start_payment(*, property: str, amount, currency: str, provider_account: str, booking: str | None = None,
                  payment_link: str | None = None, description: str, customer: dict, return_url: str,
                  idempotency_key: str, method: str = "Card", locale: str = "en") -> dict:
	amount = quantize(D(amount), currency)
	if amount <= 0:
		frappe.throw(_("Nothing to pay."))
	acc_property = frappe.db.get_value("TEX Payment Provider Account", provider_account, "property")
	if acc_property != property:
		# a guest must never route a hotel's payment through another hotel's gateway
		frappe.throw(_("This payment method is not available."), frappe.PermissionError)
	check_return_url(property, return_url)
	idempotency_key = ns_key(property, idempotency_key, "charge")
	existing = frappe.db.get_value("TEX Payment Transaction", {"idempotency_key": idempotency_key},
	                               ["name", "status"], as_dict=True)
	if existing and existing.status != "Pending":
		frappe.throw(_("This payment was already processed ({0}).").format(existing.status))
	provider = provider_for(provider_account)
	txn = frappe.get_doc("TEX Payment Transaction", existing.name) if existing else _new_txn(
		property=property, txn_type="Charge", method=method, amount=amount, currency=currency,
		provider_account=provider_account, provider=provider.name, idempotency_key=idempotency_key,
		booking=booking, payment_link=payment_link, return_url=return_url)
	callback = get_url(f"/api/method/kamra.tex.api.payments.callback?txn={txn.name}&cb={callback_signature(txn.name)}")
	try:
		checkout = provider.create_checkout(Intent(transaction=txn.name, amount=amount, currency=currency,
		                                           description=description, return_url=return_url,
		                                           callback_url=callback, customer=customer, locale=locale))
	except (ProviderError, Exception) as e:
		txn.status = "Failed"
		txn.error_message = str(e)[:500]
		txn.completed_at = now_datetime()
		txn.save(ignore_permissions=True)
		log_exception(f"TEX payment start failed {txn.name}")
		frappe.throw(_("The payment could not be started. Please try another method."))
	if checkout.provider_ref:
		txn.provider_ref = checkout.provider_ref
		txn.save(ignore_permissions=True)
	return {"transaction": txn.name, "kind": checkout.kind, "url": checkout.url, "fields": checkout.fields,
	        "instructions": checkout.instructions, "sandbox": provider.sandbox}


def complete(transaction: str, *, params: dict, headers: dict | None = None, body: bytes = b"",
             allow_failed: bool = False) -> dict:
	"""Provider callback → verified outcome → transaction final + allocation. Idempotent.

	Only an outcome the gateway authenticated for THIS transaction changes it; an
	unverifiable or not-yet-final result raises ProviderError / stays Pending, so a
	forged request can never fail a payment the guest is completing (ADR-021).
	``allow_failed``: staff re-verification may turn a Failed charge into Succeeded."""
	frappe.db.sql("SELECT name FROM `tabTEX Payment Transaction` WHERE name=%s FOR UPDATE", transaction)
	txn = frappe.get_doc("TEX Payment Transaction", transaction)
	if txn.status != "Pending" and not (allow_failed and txn.status == "Failed"):
		return {"transaction": txn.name, "status": txn.status, "replay": True}
	provider = provider_for(txn.provider_account)
	outcome = provider.handle_callback(txn.name, params, headers or {}, body, provider_ref=txn.provider_ref)
	if outcome.status == "Pending":
		return {"transaction": txn.name, "status": txn.status, "pending": True}
	if allow_failed and txn.status == "Failed" and outcome.status != "Succeeded":
		return {"transaction": txn.name, "status": txn.status}
	if outcome.amount and quantize(outcome.amount, txn.currency) != from_db(txn.amount, txn.currency):
		outcome = Outcome(status="Failed", provider_ref=outcome.provider_ref, raw_status=outcome.raw_status,
		                  error_code="AMOUNT_MISMATCH", error_message="provider amount differs")
	txn.status = outcome.status if outcome.status in ("Succeeded", "Failed", "Cancelled") else "Pending"
	txn.flags.tex_system_update = True
	txn.provider_ref = outcome.provider_ref or txn.provider_ref
	txn.raw_status = outcome.raw_status
	txn.error_code = outcome.error_code
	txn.error_message = (outcome.error_message or "")[:500] or None
	txn.card_brand = outcome.card_brand
	txn.card_last4 = outcome.card_last4
	txn.completed_at = now_datetime()
	txn.save(ignore_permissions=True)
	if txn.status == "Succeeded":
		_after_charge(txn)
	audit("payment." + txn.status.lower(), reference_doctype="TEX Payment Transaction", reference_name=txn.name,
	      property=txn.property, new={"amount": to_str(from_db(txn.amount, txn.currency)), "currency": txn.currency,
	                                  "provider": txn.provider, "booking": txn.booking, "link": txn.payment_link},
	      source="Webhook")
	return {"transaction": txn.name, "status": txn.status}


def _after_charge(txn) -> None:
	amount = from_db(txn.amount, txn.currency)
	if txn.payment_link:
		link = frappe.get_doc("TEX Payment Link", txn.payment_link)
		link.flags.tex_system_update = True
		link.paid_amount = from_db(link.paid_amount, link.currency) + amount
		link.status = "Paid" if link.paid_amount >= from_db(link.amount, link.currency) else "Partially Paid"
		link.save(ignore_permissions=True)
		if link.booking and not txn.booking:
			allocate(txn.name, booking=link.booking, amount=amount, reason="payment link", _system=True)
			return
	if txn.booking:
		allocate(txn.name, booking=txn.booking, amount=amount, reason="booking payment", _system=True)


def allocated_of(transaction: str) -> D:
	rows = frappe.get_all("TEX Payment Allocation", filters={"transaction": transaction},
	                      fields=["allocation_type", "amount", "currency"])
	total = ZERO
	for r in rows:
		a = from_db(r.amount, r.currency)
		total += -a if r.allocation_type in ("Release", "Refund") else a
	return total


def _lock(doctype: str, name: str) -> None:
	"""Row lock: allocations of one payment (or changes of one link) run one at a time, so
	two submits can never both see the same unallocated amount (G-14)."""
	frappe.db.sql(f"SELECT name FROM `tab{doctype}` WHERE name=%s FOR UPDATE", name)  # nosemgrep -- constant doctype


def _replayed_allocation(property: str, key: str | None, kind: str) -> tuple[str | None, str | None]:
	"""→ (namespaced key, allocation already made with it)."""
	key = ns_key(property, key, kind)
	return key, (frappe.db.get_value("TEX Payment Allocation", {"idempotency_key": key}, "name") if key else None)


def allocate(transaction: str, *, booking: str, amount, reason: str, _system: bool = False,
             idempotency_key: str | None = None) -> str:
	_lock("TEX Payment Transaction", transaction)
	txn = frappe.get_doc("TEX Payment Transaction", transaction)
	if not _system:
		scope.require("payment.refund", txn.property)
	key, done = _replayed_allocation(txn.property, idempotency_key, "allocate")
	if done:
		return done
	if txn.status != "Succeeded" or txn.txn_type != "Charge":
		frappe.throw(_("Only successful charges can be allocated."))
	b = frappe.get_doc("TEX Booking", booking)
	if b.property != txn.property:
		frappe.throw(_("A payment can only be allocated to a booking of the same hotel."))
	if b.currency != txn.currency:
		frappe.throw(_("Currency mismatch between payment and booking."))
	amount = quantize(D(amount), txn.currency)
	free = from_db(txn.amount, txn.currency) - allocated_of(transaction) - refunded_of(transaction)
	if amount <= 0 or amount > free:
		frappe.throw(_("Only {0} {1} of this payment is unallocated.").format(to_str(free), txn.currency))
	doc = frappe.get_doc({"doctype": "TEX Payment Allocation", "property": txn.property, "transaction": transaction,
	                      "allocation_type": "Allocate", "amount": amount, "currency": txn.currency,
	                      "booking": booking, "payment_link": txn.payment_link, "reason": reason,
	                      "actor": frappe.session.user, "idempotency_key": key})
	doc.insert(ignore_permissions=True)
	from kamra.tex.services import booking as booking_svc

	booking_svc.apply_payment(booking, amount, reference=transaction)
	if not _system:
		audit("payment.allocate", reference_doctype="TEX Payment Allocation", reference_name=doc.name,
		      property=txn.property, new={"transaction": transaction, "booking": booking, "amount": to_str(amount)},
		      reason=reason)
	return doc.name


def release(transaction: str, *, booking: str, amount, reason: str, idempotency_key: str | None = None) -> str:
	"""Take (part of) an allocation back from a booking — e.g. to transfer it."""
	_lock("TEX Payment Transaction", transaction)
	txn = frappe.get_doc("TEX Payment Transaction", transaction)
	scope.require("payment.refund", txn.property)
	key, done = _replayed_allocation(txn.property, idempotency_key, "release")
	if done:
		return done
	amount = quantize(D(amount), txn.currency)
	on_booking = sum((from_db(r.amount, r.currency) * (1 if r.allocation_type == "Allocate" else -1)
	                  for r in frappe.get_all("TEX Payment Allocation",
	                                          filters={"transaction": transaction, "booking": booking},
	                                          fields=["amount", "currency", "allocation_type"])), ZERO)
	if amount <= 0 or amount > on_booking:
		frappe.throw(_("Only {0} is allocated to this booking.").format(to_str(on_booking)))
	doc = frappe.get_doc({"doctype": "TEX Payment Allocation", "property": txn.property, "transaction": transaction,
	                      "allocation_type": "Release", "amount": amount, "currency": txn.currency,
	                      "booking": booking, "reason": reason, "actor": frappe.session.user,
	                      "idempotency_key": key})
	doc.insert(ignore_permissions=True)
	from kamra.tex.services import booking as booking_svc

	booking_svc.apply_payment(booking, -amount, reference=f"release {transaction}")
	audit("payment.release", reference_doctype="TEX Payment Allocation", reference_name=doc.name,
	      property=txn.property, new={"transaction": transaction, "booking": booking, "amount": to_str(amount)},
	      reason=reason)
	return doc.name


def transfer(transaction: str, *, from_booking: str, to_booking: str, amount, reason: str,
             idempotency_key: str | None = None) -> dict:
	rel = release(transaction, booking=from_booking, amount=amount, reason=f"transfer: {reason}",
	              idempotency_key=f"{idempotency_key}:out" if idempotency_key else None)
	alloc = allocate(transaction, booking=to_booking, amount=amount, reason=f"transfer: {reason}",
	                 idempotency_key=f"{idempotency_key}:in" if idempotency_key else None)
	return {"released": rel, "allocated": alloc}


def refunded_of(transaction: str) -> D:
	rows = frappe.get_all("TEX Payment Transaction", filters={"parent_transaction": transaction,
	                                                          "txn_type": "Refund", "status": "Succeeded"},
	                      fields=["amount", "currency"])
	return sum((from_db(r.amount, r.currency) for r in rows), ZERO)


def refund(transaction: str, *, amount, reason: str, idempotency_key: str, booking: str | None = None) -> dict:
	txn = frappe.get_doc("TEX Payment Transaction", transaction)
	scope.require("payment.refund", txn.property)
	if not (reason or "").strip():
		frappe.throw(_("A refund reason is required."))
	if booking and frappe.db.get_value("TEX Booking", booking, "property") != txn.property:
		frappe.throw(_("The booking belongs to another hotel."))
	idempotency_key = ns_key(txn.property, idempotency_key, "refund")
	if not idempotency_key:
		frappe.throw(_("Idempotency key required."))
	done = frappe.db.get_value("TEX Payment Transaction", {"idempotency_key": idempotency_key}, "name")
	if done:
		return {"refund": done, "replay": True}
	frappe.db.sql("SELECT name FROM `tabTEX Payment Transaction` WHERE name=%s FOR UPDATE", transaction)
	amount = quantize(D(amount), txn.currency)
	refundable = from_db(txn.amount, txn.currency) - refunded_of(transaction)
	if txn.status != "Succeeded" or txn.txn_type != "Charge":
		frappe.throw(_("Only successful charges can be refunded."))
	if amount <= 0 or amount > refundable:
		frappe.throw(_("At most {0} {1} can be refunded.").format(to_str(refundable), txn.currency))
	r = _new_txn(property=txn.property, txn_type="Refund", method=txn.method, amount=amount, currency=txn.currency,
	             provider_account=txn.provider_account, provider=txn.provider, idempotency_key=idempotency_key,
	             parent_transaction=txn.name, booking=booking or txn.booking, reason=reason)
	provider = provider_for(txn.provider_account)
	try:
		outcome = provider.refund(txn.provider_ref, amount, txn.currency)
	except ProviderError as e:
		outcome = Outcome(status="Failed", error_code="PROVIDER", error_message=str(e))
	r.status = outcome.status
	r.provider_ref = outcome.provider_ref
	r.raw_status = outcome.raw_status
	r.error_message = (outcome.error_message or "")[:500] or None
	r.completed_at = now_datetime()
	r.save(ignore_permissions=True)
	if r.status == "Succeeded" and (booking or txn.booking):
		target = booking or txn.booking
		frappe.get_doc({"doctype": "TEX Payment Allocation", "property": txn.property, "transaction": txn.name,
		                "allocation_type": "Refund", "amount": amount, "currency": txn.currency,
		                "booking": target, "reason": reason, "actor": frappe.session.user}).insert(
			ignore_permissions=True)
		from kamra.tex.services import booking as booking_svc

		booking_svc.apply_payment(target, -amount, reference=f"refund {r.name}")
	audit("payment.refund", reference_doctype="TEX Payment Transaction", reference_name=r.name,
	      property=txn.property, new={"of": txn.name, "amount": to_str(amount), "status": r.status}, reason=reason)
	return {"refund": r.name, "status": r.status}


def mark_transfer_received(transaction: str, *, reference: str) -> dict:
	_lock("TEX Payment Transaction", transaction)
	txn = frappe.get_doc("TEX Payment Transaction", transaction)
	scope.require("payment.refund", txn.property)
	if txn.provider != "Bank Transfer" or txn.status != "Pending":
		frappe.throw(_("Only pending bank transfers can be confirmed."))
	txn.status = "Succeeded"
	txn.raw_status = "RECEIVED"
	txn.provider_ref = reference[:140]
	txn.completed_at = now_datetime()
	txn.save(ignore_permissions=True)
	_after_charge(txn)
	audit("payment.transfer_received", reference_doctype="TEX Payment Transaction", reference_name=txn.name,
	      property=txn.property, new={"reference": reference})
	return {"transaction": txn.name, "status": txn.status}


def record_manual(*, booking: str, amount, method: str, reference: str, reason: str | None = None,
                  idempotency_key: str) -> dict:
	"""A payment taken outside TEX (desk card terminal, cash, agency remittance): stored
	as a succeeded Manual transaction and allocated to the booking. Finance-only."""
	b = frappe.get_doc("TEX Booking", booking)
	scope.require("payment.refund", b.property)
	if not (reference or "").strip():
		frappe.throw(_("A payment reference is required."))
	idempotency_key = ns_key(b.property, idempotency_key, "manual")
	if not idempotency_key:
		frappe.throw(_("Idempotency key required."))
	done = frappe.db.get_value("TEX Payment Transaction", {"idempotency_key": idempotency_key}, "name")
	if done:
		return {"transaction": done, "replay": True}
	amount = quantize(D(amount), b.currency)
	if amount <= 0:
		frappe.throw(_("Amount must be positive."))
	txn = _new_txn(property=b.property, txn_type="Charge", method="Manual", amount=amount, currency=b.currency,
	               provider="Manual", provider_ref=reference.strip()[:140], idempotency_key=idempotency_key,
	               booking=booking, reason=(f"{method}: {reason or ''}").strip()[:500])
	txn.status = "Succeeded"
	txn.raw_status = "RECORDED"
	txn.completed_at = now_datetime()
	txn.save(ignore_permissions=True)
	allocate(txn.name, booking=booking, amount=amount, reason="manual payment", _system=True)
	audit("payment.manual", reference_doctype="TEX Payment Transaction", reference_name=txn.name,
	      property=b.property, new={"booking": booking, "amount": to_str(amount), "method": method,
	                                "reference": reference}, reason=reason)
	return {"transaction": txn.name, "status": txn.status}


# ─── payment links ───────────────────────────────────────────────────────


def link_token_hash(token: str) -> str:
	return hashlib.sha256(("tex-paylink:" + token).encode()).hexdigest()


def create_link(*, property: str, amount, currency: str, description: str, expires_hours: int = 72,
                provider_account: str | None = None, booking: str | None = None, reservation: str | None = None,
                guest_name: str | None = None, guest_email: str | None = None,
                idempotency_key: str | None = None, send_email: bool = False, language: str = "en") -> dict:
	scope.require("payment.link", property)
	if booking and frappe.db.get_value("TEX Booking", booking, "property") != property:
		frappe.throw(_("The booking belongs to another hotel."))
	if reservation and frappe.db.get_value("Reservation", reservation, "property") != property:
		frappe.throw(_("The reservation belongs to another hotel."))
	amount = quantize(D(amount), currency)
	if amount <= 0:
		frappe.throw(_("Amount must be positive."))
	idempotency_key = ns_key(property, idempotency_key, "link")
	if idempotency_key:
		existing = frappe.db.get_value("TEX Payment Link", {"idempotency_key": idempotency_key}, "name")
		if existing:
			return {"link": existing, "replay": True}
	if provider_account and frappe.db.get_value("TEX Payment Provider Account", provider_account,
	                                            "property") != property:
		frappe.throw(_("That payment account belongs to another hotel."))
	token = secrets.token_urlsafe(24)
	doc = frappe.get_doc({
		"doctype": "TEX Payment Link", "property": property, "status": "Active", "amount": amount,
		"currency": currency, "description": (description or "")[:500],
		"expires_at": add_to_date(now_datetime(), hours=max(1, min(int(expires_hours or 72), 24 * 60))),
		"provider_account": provider_account, "booking": booking, "reservation": reservation,
		"guest_name": guest_name, "guest_email": guest_email, "token_hash": link_token_hash(token),
		# the URL embeds the bearer token: returned once, never stored (only its hash is)
		"idempotency_key": idempotency_key, "public_url": None,
	})
	doc.insert(ignore_permissions=True)
	url = get_url(f"/book/pay/{token}")
	emailed = False
	if send_email:
		from kamra.tex.services import notify

		emailed = notify.payment_link(doc.name, url, language)
	audit("payment_link.create", reference_doctype="TEX Payment Link", reference_name=doc.name, property=property,
	      new={"amount": to_str(amount), "currency": currency, "booking": booking, "emailed": emailed})
	return {"link": doc.name, "url": url, "token": token, "emailed": emailed}


def reissue_link(name: str, *, send_email: bool = False, language: str = "en") -> dict:
	"""New token for an open link (the old URL stops working) — staff lost or resend."""
	link = frappe.get_doc("TEX Payment Link", name)
	scope.require("payment.link", link.property)
	if link.status not in ("Active", "Partially Paid"):
		frappe.throw(_("Only open links can be reissued."))
	token = secrets.token_urlsafe(24)
	link.flags.tex_system_update = True
	link.token_hash = link_token_hash(token)
	link.save(ignore_permissions=True)
	url = get_url(f"/book/pay/{token}")
	emailed = False
	if send_email:
		from kamra.tex.services import notify

		emailed = notify.payment_link(link.name, url, language)
	audit("payment_link.reissue", reference_doctype="TEX Payment Link", reference_name=name, property=link.property,
	      new={"emailed": emailed})
	return {"link": link.name, "url": url, "token": token, "emailed": emailed}


def link_by_token(token: str):
	name = frappe.db.get_value("TEX Payment Link", {"token_hash": link_token_hash(token or "")})
	if not name:
		frappe.throw(_("This payment link is not valid."), frappe.DoesNotExistError)
	link = frappe.get_doc("TEX Payment Link", name)
	if link.status == "Active" and link.expires_at and get_datetime(link.expires_at) < now_datetime():
		link.flags.tex_system_update = True
		link.status = "Expired"
		link.save(ignore_permissions=True)
	return link


def expire_links() -> int:
	"""Scheduler: active links past their expiry become Expired."""
	n = 0
	for name in frappe.get_all("TEX Payment Link", filters={"status": ("in", ["Active", "Partially Paid"]),
	                                                        "expires_at": ("<", now_datetime())}, pluck="name"):
		link = frappe.get_doc("TEX Payment Link", name)
		link.flags.tex_system_update = True
		link.status = "Expired"
		link.save(ignore_permissions=True)
		n += 1
	return n


def cancel_link(name: str, reason: str) -> None:
	_lock("TEX Payment Link", name)
	link = frappe.get_doc("TEX Payment Link", name)
	scope.require("payment.link", link.property)
	if link.status not in ("Active", "Draft"):
		frappe.throw(_("Only active links can be cancelled."))
	link.status = "Cancelled"
	link.save(ignore_permissions=True)
	audit("payment_link.cancel", reference_doctype="TEX Payment Link", reference_name=name, property=link.property,
	      reason=reason)
