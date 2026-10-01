"""TEX Payments service (R-40, R-41, ADR-016).

Every money movement is a TEX Payment Transaction (idempotent by key) plus, for
charges applied to a booking, a TEX Payment Allocation. Refunds, reallocations and
transfers are new rows — nothing is edited away. Callbacks are verified by the
provider adapter; completing the same transaction twice is a no-op.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import secrets
import time

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, getdate, now_datetime

from kamra.tex.money import ZERO, D, from_db, quantize, to_str
from kamra.tex.payments.providers import REGISTRY, account_problem, simple, turkey
from kamra.tex.payments.providers.base import Intent, Outcome, ProviderError
from kamra.tex.security import scope
from kamra.tex.security.audit import audit, log_exception
from kamra.tex.security.keys import site_secret
from kamra.tex.services import holds
from kamra.tex.services.txn import DEADLOCK_ATTEMPTS, note_committed_step, transaction_lost, undo_to


class AccountRefused(frappe.ValidationError):
	"""A provider account that may not run for what was asked of it (G-67, ADR-041)."""


class ChargeSuperseded(frappe.ValidationError):
	"""A reused Pending charge could not take another checkout, so it was cancelled; the
	caller may start a new charge (G-68). A late verified payment of it is still recorded."""


class PaymentBusy(frappe.ValidationError):
	"""Another request is starting the same payment (or one for the same link) right now."""


class RefundUnknown(frappe.ValidationError):
	"""The gateway did not answer a refund (a timeout, a connection or server error): it may
	have refunded. The refund stays Pending with the error UNKNOWN, on record before the gateway
	was asked, and is never made again by TEX: staff check it at the gateway (review of
	ADR-044)."""


# a refund on record (Pending) this long without an answer: the run that asked for it died, or
# the gateway never answered (its calls time out in well under a minute). Staff check it at the
# gateway, and nothing refunds its money again until they did (G-45 re-review)
REFUND_STUCK_MINUTES = 5


class RefundConflict(RefundUnknown):
	"""The gateway answered a refund after an outcome was recorded for it (staff recorded what
	they saw while the call ran) and says something else, or nothing. The record is kept, the
	conflict audited (``payment.refund_outcome_conflict``) and shown in the system status; the
	caller refunds nothing more on it: staff reconcile it at the gateway (third review of
	ADR-044)."""


def _durable_commit() -> None:
	"""Put a money movement on record before a gateway is asked to make it, so that a crash or a
	timeout after the gateway acted can never lose the record and repeat the movement. Tests
	keep one transaction."""
	if not frappe.flags.in_test:
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- a refund attempt must be durable before the gateway call


def _commit_step() -> None:
	"""End a step of a payment start (NEW-6, ADR-066): what it wrote is on record, and every row, gap
	and naming-series lock the request took so far is released before the gateway is asked for a
	checkout, and again once its answer is recorded. Tests keep one transaction. The request is not
	run again on a deadlock after this (``txn.retry_on_deadlock``, P1-8 e)."""
	note_committed_step()
	if not frappe.flags.in_test:
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- no row, gap or series lock is held through a gateway call (NEW-6)


# a charge in one of these states still records a payment the gateway verifies (another tab,
# a restart, a superseded checkout): money a gateway captured is never ignored (G-68)
SETTLEABLE = ("Pending", "Failed", "Cancelled")
MAX_LINK_ATTEMPTS = 50


def _mock_secret() -> str:
	# the site key, never the public site name (G-89): same value as before for a keyed site
	return hashlib.sha256(site_secret("tex-mock-pay").encode()).hexdigest()


def ns_key(property: str, raw: str | None, kind: str) -> str | None:
	"""Staff-supplied idempotency keys are namespaced per hotel and purpose, so a key
	reused elsewhere can neither collide nor replay another hotel's record."""
	raw = (raw or "").strip()[:140]
	if not raw:
		return None
	return hashlib.sha256(f"{kind}|{property}|{raw}".encode()).hexdigest()


# how a gateway reaches the callback (G-74, ADR-053): the guest's browser coming back from the
# payment page, or the gateway's own server-to-server notification. Signed with the id, so a
# return address never passes for a notification.
CALLBACK_SOURCES = {"return": "Gateway Return", "notify": "Webhook"}


def callback_signature(transaction: str, via: str | None = None) -> str:
	"""Signs the gateway return URL so arbitrary transaction ids cannot be poked. ``via`` (a key
	of ``CALLBACK_SOURCES``) is signed with it; a URL issued before G-74 has none."""
	msg = f"{transaction}|{via}" if via else transaction
	return hmac.new(site_secret("tex-callback").encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]


def callback_url(transaction: str, via: str) -> str:
	# gateways call back to the platform host, never to a host taken from the request (G-21)
	return _platform_url(f"/api/method/kamra.tex.api.payments.callback?txn={transaction}&via={via}"
	                     f"&cb={callback_signature(transaction, via)}")


def allowed_return_hosts(property: str) -> set[str]:
	"""The platform host and the verified hosts of the hotel's (and its group's) enabled
	booking sites — never the request's Host header (G-21)."""
	from kamra.tex.services import sites as sites_svc

	group = frappe.db.get_value("Property", property, "tex_hotel_group")
	names = frappe.get_all("TEX Booking Site", or_filters={"property": property, "hotel_group": group or "__none__"},
	                       pluck="name")
	return sites_svc.return_hosts(names)


def _platform_url(uri: str) -> str:
	from kamra.tex.services import sites as sites_svc

	return sites_svc.platform_url(uri)


def _link_url(property: str, booking: str | None, token: str) -> str:
	"""A payment link opens on the hotel's booking host when it has one (G-21). The token is in
	the URL fragment, which browsers never send to a server, so it reaches no access log or
	Referer header (G-83); the page posts it to the API. Links sent before as ``pay/<token>``
	still open (the page moves the token out of the path) until they expire."""
	from kamra.tex.services import sites as sites_svc

	site = sites_svc.site_for(property, frappe.db.get_value("TEX Booking", booking, "booking_site") if booking
	                          else None)
	return sites_svc.guest_url(site, f"pay#token={token}", site_scoped=False)


def check_return_url(property: str, url: str) -> str:
	"""Open-redirect guard for every payment flow (ADR-021)."""
	from urllib.parse import urlparse

	u = urlparse(url or "")
	if u.scheme not in ("https", "http") or (u.scheme == "http" and not frappe.conf.get("developer_mode")) \
			or u.hostname not in allowed_return_hosts(property):
		frappe.throw(_("Invalid return address."), frappe.ValidationError)
	return url


def account_rule(acc, purpose: str = "new") -> str | None:
	"""Why this account may not run for ``purpose``, or None (ADR-041).

	- ``new``: take new money: start a charge, offer a method, save an enabled account;
	- ``settle``: money a gateway already holds: record a capture, re-verify, refund. An
	  uncertified Production account left from before certification was required still
	  settles, so captured money is never stranded;
	- ``keep``: save a disabled account. It runs nothing until it is enabled again, and
	  enabling it is a save under ``new``, so only an unknown provider is refused."""
	if purpose == "keep":
		return None if acc.get("provider") in REGISTRY else "unknown"
	return account_problem(acc.get("provider"), acc.get("environment"), acc.get("gateway_url"),
	                       live_site=bool(frappe.conf.get("tex_production")),
	                       developer_mode=bool(frappe.conf.get("developer_mode")), settling=purpose == "settle")


def _refuse(acc, message: str) -> None:
	if frappe.session.user == "Guest":
		# a guest is never told how the hotel's payments are set up; staff find the reason in
		# the error log (G-67)
		frappe.log_error(title=f"TEX payment account refused: {acc.get('name')}"[:140], message=message)
		frappe.throw(_("This payment method is not available."), AccountRefused)
	frappe.throw(message, AccountRefused, title=_("Payment provider"))


def check_account(acc, *, purpose: str = "new") -> None:
	"""The rules every provider account obeys (G-67, ADR-041): checked by the account's
	controller whoever saves it (TEX API, Desk, REST) and again before every use, so an
	account changed behind the controller's back fails closed."""
	problem = account_rule(acc, purpose)
	if not problem:
		return
	provider = acc.get("provider") or "—"
	cls = REGISTRY.get(acc.get("provider") or "")
	_refuse(acc, {
		"unknown": _("{0} is not an installed payment provider.").format(provider),
		"mock": _("The mock provider can only be used in Sandbox."),
		"uncertified": _("{0} is not certified for production: use the Sandbox environment.").format(provider),
		"gateway_url": _("A gateway URL override is only allowed in Sandbox (for sandbox or test hosts). "
		                 "A Production account uses the provider's live host: clear the gateway URL."),
		"sandbox_host": _("A Sandbox gateway URL override must be an https address on {0}'s own sandbox host "
		                  "({1}): clear it to use the default sandbox address.").format(
			provider, ", ".join(cls.sandbox_hosts) if cls else "—"),
		"sandbox_live_site": _("{0} is set to Sandbox and this site is live (tex_production): a sandbox payment is "
		                       "test money and must not confirm a booking. Disable this account.").format(provider),
	}[problem])


def provider_for(account_name: str, *, purpose: str = "new", transaction: str | None = None):
	"""The provider of an account, checked for ``purpose`` (see ``account_rule``). A disabled
	account runs nothing, settling included: disabling is the hotel's stop switch (a leaked
	gateway key must not confirm bookings)."""
	acc = frappe.get_doc("TEX Payment Provider Account", account_name)
	if not acc.enabled:
		_refuse(acc, _("Payment provider {0} is disabled.").format(acc.label))
	check_account(acc, purpose=purpose)
	if purpose == "settle" and (gated := account_rule(acc, "new")):
		# an account that could not take this money today still settles it, on the record (ADR-041)
		audit("payment_account.settled_while_gated", reference_doctype="TEX Payment Provider Account",
		      reference_name=acc.name, property=acc.property,
		      new={"problem": gated, "transaction": transaction, "provider": acc.provider,
		           "environment": acc.environment})
	cls = REGISTRY[acc.provider]
	return cls(acc, _mock_secret()) if cls is simple.MockProvider else cls(acc)


def gated_accounts(property: str | None = None) -> list[dict]:
	"""The go-live check (ADR-041): every account that may not take new money, why, and its
	open (Pending) charges. Those charges still settle; new ones are refused. Run by patch
	p19 on migrate and shown on the payments setup screen."""
	filters = {"property": property} if property else {}
	out = []
	for a in frappe.get_all("TEX Payment Provider Account", filters=filters,
	                        fields=["name", "label", "property", "provider", "environment", "enabled", "gateway_url"],
	                        order_by="property asc, label asc"):
		problem = account_rule(a, "new")
		if not problem:
			continue
		# by name, not by last write: the same open charges make the same report (p19 audits it once)
		open_charges = frappe.get_all("TEX Payment Transaction", filters={
			"provider_account": a.name, "txn_type": "Charge", "status": "Pending"}, pluck="name",
			order_by="name asc")
		out.append({"account": a.name, "label": a.label, "property": a.property, "provider": a.provider,
		            "environment": a.environment, "enabled": bool(a.enabled), "problem": problem,
		            "open_charges": len(open_charges), "open_charge_names": open_charges[:20]})
	return out


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
		                          ["provider", "label", "environment", "enabled", "currencies", "gateway_url"],
		                          as_dict=True) if r.provider_account else None
		if r.provider_account and (not acc or not acc.enabled):
			continue
		if acc and account_rule(acc, "new"):
			continue                     # it could not run (G-67): never offer it
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


START_SAVEPOINT = "tex_start_payment"
# a start asks the gateway with no lock held; for this long its lease tells a second start of the same
# charge that one is being started. Longer than the slowest gateway path: Sipay makes two calls (token,
# checkout), each up to TIMEOUT to connect and TIMEOUT to read (4 × TIMEOUT = 80 s), plus a margin: 5 ×
# TIMEOUT = 100 s. An older lease is a start that died between its steps: its checkout never reached the
# guest (NEW-6, ADR-066)
CHECKOUT_LEASE_SECONDS = 5 * turkey.TIMEOUT


def _busy() -> None:
	frappe.throw(_("A payment is being started. Please wait a moment and try again."), PaymentBusy)


def _end_lease(txn, stamp) -> None:
	"""Clear the checkout lease of ``txn`` (locked) if it is still this start's; a later start that took
	over a lapsed one keeps its own."""
	if txn.checkout_started_at and get_datetime(txn.checkout_started_at) == stamp:
		frappe.db.set_value("TEX Payment Transaction", txn.name, "checkout_started_at", None, update_modified=False)
		txn.checkout_started_at = None            # a save of ``txn`` after this never writes it back


def start_payment(*, property: str, amount, currency: str, provider_account: str, booking: str | None = None,
                  payment_link: str | None = None, description: str, customer: dict, return_url: str,
                  idempotency_key: str, method: str = "Card", locale: str = "en",
                  reservation: str | None = None) -> dict:
	"""Start (or, with the same key, restart) a charge. A restart reuses the Pending charge;
	when that charge cannot take another checkout, or its new checkout fails, it is superseded:
	cancelled, with a late verified payment still recorded, and ``ChargeSuperseded`` raised so
	the caller can start a new charge (G-68).

	Three steps, so that no row, gap or naming-series lock is held while the gateway works (NEW-6,
	ADR-066): (a) the charge is put on record with a checkout lease and committed — with everything the
	request did before (a booking made just now included); (b) the gateway is asked, no lock held; (c)
	its answer is recorded under the charge's lock and committed. A start of the same charge while one's
	lease is young is told so (``PaymentBusy``); a failed checkout is on record before the caller hears."""
	amount = quantize(D(amount), currency)
	if amount <= 0:
		frappe.throw(_("Nothing to pay."))
	acc_property = frappe.db.get_value("TEX Payment Provider Account", provider_account, "property")
	if acc_property != property:
		# a guest must never route a hotel's payment through another hotel's gateway
		frappe.throw(_("This payment method is not available."), frappe.PermissionError)
	check_return_url(property, return_url)
	idempotency_key = ns_key(property, idempotency_key, "charge")
	existing = frappe.db.get_value("TEX Payment Transaction", {"idempotency_key": idempotency_key}, "name")
	if existing:
		# a locking read by name: the charge as it is now (a callback may have settled it after
		# this request's snapshot, G-68). Only an existing row is locked, never a gap of the key
		# index, so no other payment's insert waits behind this one.
		existing = frappe.db.get_value("TEX Payment Transaction", existing,
		                               ["name", "status", "provider_account", "amount", "currency",
		                                "checkout_started_at"], as_dict=True, for_update=True)
	if existing and existing.status != "Pending":
		frappe.throw(_("This payment was already processed ({0}).").format(existing.status))
	stamp = now_datetime()
	if existing and existing.checkout_started_at and \
			get_datetime(existing.checkout_started_at) > add_to_date(stamp, seconds=-CHECKOUT_LEASE_SECONDS):
		# another request is asking the gateway for this charge's checkout right now (another tab, a
		# double click, a retried request): one checkout at a time, never two for one charge
		_busy()
	if existing and (existing.provider_account != provider_account or existing.currency != currency
	                 or from_db(existing.amount, existing.currency) != amount):
		# a reused charge is exactly the charge that was started, never re-routed or re-priced
		frappe.throw(_("This payment was started with another method or amount."))
	provider = provider_for(provider_account)
	# a booking waiting for its payment: the attempt is refused once its hold is over, else it
	# keeps the rooms until its own deadline, never longer (K-2a)
	held = booking or (frappe.db.get_value("TEX Payment Link", payment_link, "booking") if payment_link else None)
	hold_method = holds.TRANSFER if provider.name == holds.TRANSFER else method
	# ── (a) the charge on record, with its lease ──
	# a second start of the same charge (another tab, a double click, a restart) reuses the
	# Pending transaction: one charge, never two (G-68)
	if existing:
		txn = frappe.get_doc("TEX Payment Transaction", existing.name, for_update=True)
		if not provider.can_add_checkout(txn.provider_ref):
			_supersede(txn, "another checkout was asked for")
		# a restart is a new attempt (2F-1): the hold decides it as it does a new charge (refused once it is
		# over, P1-9; the booking is locked after the charge, the order of money coming in), and the charge's
		# deadline moves to the new attempt's, never back — ``paid_in_time`` reads it
		until = holds.open_attempt(held, hold_method) if held else None
		if until and (not txn.expires_at or get_datetime(txn.expires_at) < get_datetime(until)):
			frappe.db.set_value("TEX Payment Transaction", txn.name, "expires_at", until, update_modified=False)
		frappe.db.set_value("TEX Payment Transaction", txn.name, "checkout_started_at", stamp, update_modified=False)
	else:
		# the key is unique: a start that lost the race to the same new key undoes its own steps back to
		# here and is told a payment is being started (one start per charge, and per link: each tab of a
		# link gets the same key while its charge is Pending)
		frappe.db.savepoint(START_SAVEPOINT)
		messages = frappe.local.message_log
		mark = len(messages)
		expires_at = holds.open_attempt(held, hold_method) if held else None
		try:
			txn = _new_txn(property=property, txn_type="Charge", method=method, amount=amount, currency=currency,
			               provider_account=provider_account, provider=provider.name,
			               idempotency_key=idempotency_key, booking=booking, payment_link=payment_link,
			               return_url=return_url, reservation=reservation, expires_at=expires_at,
			               checkout_started_at=stamp)
		except frappe.UniqueValidationError:
			frappe.db.rollback(save_point=START_SAVEPOINT)
			del messages[mark:]           # Frappe's "must be unique" message is not this request's answer
			# a locking read: the charge the other request committed, not this transaction's older snapshot
			if not frappe.db.sql("SELECT name FROM `tabTEX Payment Transaction` WHERE idempotency_key=%s "
			                     "LOCK IN SHARE MODE", idempotency_key):
				raise
			_busy()
	intent = Intent(transaction=txn.name, amount=amount, currency=currency, description=description,
	                return_url=return_url, callback_url=callback_url(txn.name, "return"),
	                notify_url=callback_url(txn.name, "notify"), customer=customer, locale=locale)
	_commit_step()
	# ── (b) the gateway, no lock held: nothing between the commit and the call takes one ──
	try:
		checkout = provider.create_checkout(intent)
	except Exception as e:
		if transaction_lost(e):
			# a deadlock: the request's transaction is gone, raised for the retry (ADR-056 reviews)
			raise
		# ── (c′) a failed start, on record before the caller hears of it ──
		log_exception(f"TEX payment start failed {txn.name}")
		txn = frappe.get_doc("TEX Payment Transaction", txn.name, for_update=True)      # as it is now
		_end_lease(txn, stamp)
		if txn.status == "Pending" and existing:
			# the gateway may refuse a second checkout for the same order; a new charge gets a
			# new order, and the checkout started earlier is still recorded if it is paid
			try:
				_supersede(txn, "the gateway refused another checkout")
			except ChargeSuperseded:
				_commit_step()
				raise
		if txn.status == "Pending":
			txn.status = "Failed"
			txn.error_message = str(e)[:500]
			txn.completed_at = now_datetime()
			txn.save(ignore_permissions=True)
		# a charge a callback settled meanwhile (an earlier checkout of a reused one) keeps its status
		_commit_step()
		frappe.throw(_("The payment could not be started. Please try another method."))
	# ── (c) the answer, recorded under the charge's lock; its status is never changed here ──
	txn = frappe.get_doc("TEX Payment Transaction", txn.name, for_update=True)          # as it is now
	if checkout.provider_ref:
		# a reused charge keeps what its earlier checkouts need to be recognised when paid
		txn.provider_ref = provider.merge_ref(txn.provider_ref, checkout.provider_ref) if existing \
			else checkout.provider_ref
		# an earlier checkout of a reused charge may have been paid meanwhile: its reference is still kept
		txn.flags.tex_system_update = txn.status != "Pending"
		txn.save(ignore_permissions=True)
	_end_lease(txn, stamp)
	_commit_step()
	return {"transaction": txn.name, "kind": checkout.kind, "url": checkout.url, "fields": checkout.fields,
	        "instructions": checkout.instructions, "sandbox": provider.sandbox}


def _supersede(txn, why: str) -> None:
	"""Cancel a reused Pending charge that cannot go on and raise ``ChargeSuperseded``. The
	charge keeps its references, so a payment of one of its checkouts is still verified and
	recorded (``complete`` settles Cancelled charges) and flagged if it overpays."""
	txn.flags.tex_system_update = True
	txn.status = "Cancelled"
	txn.error_code = "SUPERSEDED"
	txn.error_message = why
	txn.completed_at = now_datetime()
	txn.save(ignore_permissions=True)
	audit("payment.superseded", reference_doctype="TEX Payment Transaction", reference_name=txn.name,
	      property=txn.property, new={"reason": why, "link": txn.payment_link, "booking": txn.booking})
	# raised, not frappe.throw: the callers catch it and go on, and a queued message would reach
	# the guest in the successful response
	raise ChargeSuperseded(_("The payment could not be started. Please try again."))


def complete(transaction: str, *, params: dict, headers: dict | None = None, body: bytes = b"") -> dict:
	"""Provider callback → verified outcome → transaction final + allocation. Idempotent.

	Only an outcome the gateway authenticated for THIS transaction changes it; an
	unverifiable or not-yet-final result raises ProviderError / stays Pending, so a
	forged request can never fail a payment the guest is completing (ADR-021).
	A Failed or Cancelled charge still accepts a verified success (the gateway captured the
	money): a charge can have had several checkouts (another tab, a restart, G-68), and one of
	them failing must not hide another one paid; staff re-verification uses the same path.

	The gateway is asked first, holding no lock: a slow gateway must not keep the link or
	the payment locked while other requests wait (G-68). Then the link and the payment are
	locked and read as they are now (locking reads), and the outcome is applied once."""
	row = frappe.db.get_value("TEX Payment Transaction", transaction,
	                          ["name", "status", "provider_account", "provider_ref", "payment_link"], as_dict=True)
	if not row:
		frappe.throw(_("Unknown payment."), frappe.DoesNotExistError)
	if row.status not in SETTLEABLE:
		return {"transaction": row.name, "status": row.status, "replay": True}
	provider = provider_for(row.provider_account, purpose="settle", transaction=row.name)
	outcome = provider.handle_callback(row.name, params, headers or {}, body, provider_ref=row.provider_ref)
	if outcome.status == "Pending":
		if outcome.raw_status in FRAUD_REVIEW:
			_under_review(row, outcome)
		return {"transaction": row.name, "status": row.status, "pending": True}
	_lock_link_then_payment(row.name, row.payment_link)
	txn = frappe.get_doc("TEX Payment Transaction", transaction, for_update=True)
	if txn.status not in SETTLEABLE:
		return {"transaction": txn.name, "status": txn.status, "replay": True}
	was_reviewed = txn.status == "Pending" and txn.raw_status in FRAUD_REVIEW
	refused = False
	if outcome.status == "Succeeded":
		checked = _checked_capture(provider, outcome, txn)
		if checked is not outcome:
			_capture_refused(txn, outcome, checked)
			refused = True
		outcome = checked
	if txn.status != "Pending" and outcome.status != "Succeeded":
		return {"transaction": txn.name, "status": txn.status, "replay": True}
	txn.status = outcome.status if outcome.status in ("Succeeded", "Failed", "Cancelled") else "Pending"
	txn.flags.tex_system_update = True
	if not refused:
		# a refused capture keeps the charge's checkout references (another tab of it may still
		# be paid); the gateway's reference of the refused capture is in its audit entry
		txn.provider_ref = outcome.provider_ref or txn.provider_ref
	txn.raw_status = outcome.raw_status
	txn.error_code = outcome.error_code
	txn.error_message = (outcome.error_message or "")[:500] or None
	txn.card_brand = outcome.card_brand
	txn.card_last4 = outcome.card_last4
	if outcome.status == "Succeeded" and outcome.captured_at:
		txn.captured_at = outcome.captured_at        # the gateway's clock: whether it was paid in time (B4)
	txn.completed_at = now_datetime()
	txn.save(ignore_permissions=True)
	if txn.status == "Succeeded":
		_after_charge(txn)
	elif txn.status == "Failed" and was_reviewed:
		_review_rejected(txn)
	# the source is how the outcome arrived: the caller says (the gateway's return or notification,
	# staff re-verifying, the sandbox page), else the request itself (G-74)
	audit("payment." + txn.status.lower(), reference_doctype="TEX Payment Transaction", reference_name=txn.name,
	      property=txn.property, new={"amount": to_str(from_db(txn.amount, txn.currency)), "currency": txn.currency,
	                                  "provider": txn.provider, "booking": txn.booking, "link": txn.payment_link})
	return {"transaction": txn.name, "status": txn.status}


# the gateway holds the payment in its fraud review (O-18, D-8): iyzico's fraudStatus 0, or absent / unknown
FRAUD_REVIEW = ("FRAUD_REVIEW", "FRAUD_UNKNOWN")


def _paying_booking(txn) -> str | None:
	"""The booking a charge pays: its own, or its payment link's (a link's charge names no booking)."""
	if txn.get("booking"):
		return txn.booking
	return frappe.db.get_value("TEX Payment Link", txn.payment_link, "booking") if txn.get("payment_link") else None


def _under_review(row, outcome: Outcome) -> None:
	"""O-18, D-8: the gateway holds this Pending charge in its fraud review. Recorded once (``raw_status``,
	audit ``payment.under_review`` with the booking's attempt deadline before it): a booking waiting for its
	payment keeps its rooms for it for the link hold (``holds.hold_for_review``); any other (a balance, a
	change, none) holds nothing. Locks: link → payment, then the booking (ADR-066)."""
	_lock_link_then_payment(row.name, row.payment_link)
	txn = frappe.get_doc("TEX Payment Transaction", row.name, for_update=True)      # as it is now
	if txn.status != "Pending" or txn.raw_status in FRAUD_REVIEW:
		return                        # settled meanwhile, or its review is on record already: held once
	booking = _paying_booking(txn)
	txn.raw_status = outcome.raw_status
	txn.save(ignore_permissions=True)
	held = holds.hold_for_review(booking, txn) if booking else None
	audit("payment.under_review", reference_doctype="TEX Payment Transaction", reference_name=txn.name,
	      property=txn.property, old={"payment_attempt_until": str(held[0]) if held and held[0] else None},
	      new={"raw_status": outcome.raw_status, "booking": booking,
	           "payment_attempt_until": str(held[1]) if held else None})


def _review_rejected(txn) -> None:
	"""O-18, D-8: the gateway rejected a charge it held in review (now Failed). Its review hold ends: the
	booking's attempt deadline goes back to what it was before the review, or its other Pending charges'
	(``holds.after_review_rejected``); audited ``payment.fraud_rejected``, the team told. TEX recorded no
	money for it (the gateway returns any itself): nothing goes to reconciliation."""
	from kamra.tex.services import notify

	booking = _paying_booking(txn)
	review = frappe.get_all("TEX Audit Event", filters={"action": "payment.under_review", "reference_name": txn.name},
	                        fields=["old_value"], order_by="creation asc", limit=1)
	before = json.loads(review[0].old_value or "{}").get("payment_attempt_until") if review else None
	back = holds.after_review_rejected(booking, txn.name, get_datetime(before) if before else None) \
		if booking else None
	audit("payment.fraud_rejected", reference_doctype="TEX Payment Transaction", reference_name=txn.name,
	      property=txn.property, new={"booking": booking, "payment_attempt_until": str(back) if back else None})
	notify.payment_rejected(txn, booking)


def complete_retrying(transaction: str, **kw) -> dict:
	"""C3, P1-8: ``complete`` run again when the database chose it as a deadlock victim or a lock wait
	timed out. It is idempotent — a rerun asks the gateway again and applies its verified outcome once —
	so a charge the gateway captured never stays Pending (nor its money unreconciled) because of either.
	Only here: the endpoints are run again on a deadlock only. After the last try the error itself is
	raised (a caller's own deadlock wrapper may run it again: at most 3 × 3 tries). Its callers have no
	uncommitted work before it, and nothing on its way commits."""
	for attempt in range(1, DEADLOCK_ATTEMPTS + 1):
		try:
			return complete(transaction, **kw)
		except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
			# the whole transaction back: a lock wait timeout undid only the statement that waited
			# (innodb_rollback_on_timeout OFF), the rest of this try must not stay
			frappe.db.rollback()
			if attempt == DEADLOCK_ATTEMPTS:
				raise
			time.sleep(random.uniform(0.02, 0.1) * attempt)
	return None


REVERIFY_TRY_SAVEPOINT = "tex_reverify_try"
def _undo_to(save_point: str) -> None:
	"""Undo what was written since ``save_point``. A deadlock or a lock wait timeout in ``complete_retrying`` rolls
	the whole transaction back and a step commit ends it: either way the savepoint is gone and ``undo_to`` rolls
	back whole instead — safe where this runs: the job's every charge is a transaction of its own and staff's
	request has no uncommitted work before it."""
	undo_to(save_point)


def reverify(transaction: str, *, attempts: list[dict] | None = None, log: bool = True,
             step_commit: bool = False) -> tuple[dict | None, Exception | None]:
	"""Ask the gateway again for a charge by itself (its provider's ``status_query``): each of its questions
	(``attempts``, default ``status_params`` of its reference, newest first) until one confirms it. A try
	that failed leaves no message behind (P1-8); ``log``: a try the gateway did not answer is logged.
	``step_commit`` (the job): a try that changed the charge is on record before the next question, so no
	lock is held through it (ADR-066). A try that failed leaves nothing it wrote half way (money recorded, its
	allocation refused): it is undone before the next question. → (the last answer, the last error)."""
	if attempts is None:
		row = frappe.db.get_value("TEX Payment Transaction", transaction, ["provider", "provider_ref"], as_dict=True)
		cls = REGISTRY.get(row.provider) if row else None
		attempts = cls.status_params(row.provider_ref) if cls and cls.status_query else []
	out, error, state = None, None, None
	for n, params in enumerate(attempts):
		if step_commit:
			now_state = frappe.db.get_value("TEX Payment Transaction", transaction, ["status", "modified"])
			if n and now_state != state:
				_commit_step()             # the last question changed the charge: on record before the next
			state = now_state
		mark = len(frappe.local.message_log)
		frappe.db.savepoint(REVERIFY_TRY_SAVEPOINT)
		try:
			res = complete_retrying(transaction, params=params)
		except ProviderError as e:
			del frappe.local.message_log[mark:]
			_undo_to(REVERIFY_TRY_SAVEPOINT)
			error = e                                  # this question is not verifiable: ask the next
			continue
		except Exception as e:
			del frappe.local.message_log[mark:]
			if transaction_lost(e):
				raise
			_undo_to(REVERIFY_TRY_SAVEPOINT)
			# the gateway did not answer this question: an older checkout may still hold the payment
			if log:
				log_exception(f"TEX payment re-verify error {transaction}")
			error = e
			continue
		out = res
		if res.get("status") == "Succeeded":
			break
	return out, error


REVERIFY_AFTER_MINUTES = 3        # a checkout this young is still in the guest's hands
REVERIFY_WINDOW_HOURS = 2         # asked until then past its deadline (a fraud review's included, O-18)
REVERIFY_BATCH = 20
REVERIFY_BUDGET_SECONDS = 60      # one tick is a single RQ job with 300 s for the whole 5-minute group
REVERIFY_SAVEPOINT = "tex_reverify"


def reverify_pending(now=None) -> dict:
	"""Scheduler, first of the 5-minute jobs (NEW-2): card charges still Pending whose gateway TEX can ask
	(``status_query``) are asked, as the guest's browser would have told TEX had it come back — before this
	tick's expiry, so money taken in time confirms its booking. The same path as a callback (``complete``).

	Candidates (a plain read, no lock): Pending charges of an enabled account (a disabled one settles
	nothing), at least 3 minutes old, with no start asking the gateway for a checkout right now (a lapsed
	lease is a dead start), their deadline — or, without one, their creation — within the last 2 hours;
	20 per tick, none started after 60 s, by urgency: those still holding rooms first (the nearest deadline
	first: money found in time confirms the booking), then those holding none, oldest first, then those whose
	deadline has gone by, the latest first — an abandoned iyzico checkout stays Pending for 2 hours and must
	not starve the payments that can still be saved. Each is asked under a savepoint; an error is logged
	("TEX payment re-verify <charge>") and undone; each is on record before the next question (ADR-066)."""
	now = get_datetime(now or now_datetime())
	askable = tuple(sorted(name for name, cls in REGISTRY.items() if cls.status_query)) or ("",)
	# NULL checkout_started_at: no start is asking the gateway; NULL expires_at: a charge that holds no rooms
	# (a link's without a waiting booking, a change's, a balance's), judged by when it started (ADR-064).
	# Urgency: 0 = its deadline is ahead (holds rooms), nearest first; 1 = no deadline, oldest first; 2 = its
	# deadline has gone by, latest first. A CASE without ELSE is NULL outside its group: constant inside it
	names = frappe.db.sql("""SELECT t.name FROM `tabTEX Payment Transaction` t
	                         JOIN `tabTEX Payment Provider Account` a ON a.name = t.provider_account
	                         WHERE t.txn_type = 'Charge' AND t.status = 'Pending' AND t.provider IN %(askable)s
	                           AND a.enabled = 1 AND t.creation <= %(settled)s
	                           AND (t.checkout_started_at IS NULL OR t.checkout_started_at < %(lease)s)
	                           AND IFNULL(t.expires_at, t.creation) >= %(window)s
	                         ORDER BY CASE WHEN t.expires_at > %(now)s THEN 0 WHEN t.expires_at IS NULL THEN 1 ELSE 2 END,
	                                  CASE WHEN t.expires_at > %(now)s THEN t.expires_at END,
	                                  CASE WHEN t.expires_at IS NULL THEN t.creation END,
	                                  CASE WHEN t.expires_at <= %(now)s THEN t.expires_at END DESC,
	                                  t.name LIMIT %(limit)s""",
	                      {"askable": askable, "now": now, "settled": add_to_date(now, minutes=-REVERIFY_AFTER_MINUTES),
	                       "lease": add_to_date(now, seconds=-CHECKOUT_LEASE_SECONDS),
	                       "window": add_to_date(now, hours=-REVERIFY_WINDOW_HOURS), "limit": REVERIFY_BATCH},
	                      pluck=True)
	started = time.monotonic()
	done = {"asked": 0, "errors": 0}
	for name in names:
		if time.monotonic() - started > REVERIFY_BUDGET_SECONDS:
			break
		frappe.db.savepoint(REVERIFY_SAVEPOINT)
		mark = len(frappe.local.message_log)
		done["asked"] += 1
		try:
			out, error = reverify(name, log=False, step_commit=True)
			if out is None and error is not None:
				raise error
		except Exception as e:
			if transaction_lost(e):
				frappe.db.rollback()         # a deadlock victim's transaction is gone with its savepoint
			else:
				_undo_to(REVERIFY_SAVEPOINT)       # gone after a step commit or a retried deadlock: whole
			del frappe.local.message_log[mark:]
			log_exception(f"TEX payment re-verify {name}")
			done["errors"] += 1
		if not frappe.flags.in_test:
			# on record (its Error Log and audit included) before the next gateway question: no lock is held
			# through it (ADR-066); tests keep one transaction
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one charge per transaction, none held across a gateway call
	return done


def _checked_capture(provider, outcome: Outcome, txn) -> Outcome:
	"""A gateway's success counts only for exactly this charge (G-67): a gateway that reports
	amounts must state the amount it captured (missing or 0 is not trusted), any stated amount
	must equal the charge, and a stated currency must be the charge's currency. Returns the
	outcome itself when it counts, else a Failed outcome naming the mismatch."""
	expected = from_db(txn.amount, txn.currency)
	try:
		stated = quantize(D(outcome.amount), txn.currency) if outcome.amount is not None else ZERO
	except (TypeError, ValueError, ArithmeticError):
		stated = None                                  # unreadable: never equal to the charge
	must_state = getattr(provider, "reports_amount", False)
	code = message = None
	if stated is None or (stated and stated != expected) or (not stated and must_state):
		code = "AMOUNT_MISMATCH"
		message = f"provider amount {to_str(stated) if stated else '-'} differs from {to_str(expected)}"
	elif outcome.currency and str(outcome.currency).strip().upper() != (txn.currency or "").upper():
		code = "CURRENCY_MISMATCH"
		message = f"provider currency {str(outcome.currency)[:8]} differs from {txn.currency}"
	if not code:
		return outcome
	return Outcome(status="Failed", provider_ref=outcome.provider_ref, raw_status=outcome.raw_status,
	               error_code=code, error_message=message)


def _capture_refused(txn, captured: Outcome, checked: Outcome) -> None:
	"""The gateway holds money TEX did not count (G-67): put what it stated on the record,
	once per gateway reference, so finance can refund it (``refund`` reads it back)."""
	ref = (captured.provider_ref or "")[:140] or None
	seen = frappe.get_all("TEX Audit Event", filters={"action": "payment.capture_mismatch",
	                                                  "reference_doctype": "TEX Payment Transaction",
	                                                  "reference_name": txn.name}, pluck="new_value")
	if any((json.loads(v or "{}") or {}).get("provider_ref") == ref for v in seen):
		return
	try:
		amount = to_str(D(captured.amount)) if captured.amount is not None else None
	except (TypeError, ValueError, ArithmeticError):
		amount = None
	audit("payment.capture_mismatch", reference_doctype="TEX Payment Transaction", reference_name=txn.name,
	      property=txn.property,
	      new={"code": checked.error_code, "provider_ref": ref, "amount": amount,
	           "currency": str(captured.currency).strip().upper()[:8] if captured.currency else None,
	           "expected_amount": to_str(from_db(txn.amount, txn.currency)), "expected_currency": txn.currency,
	           "link": txn.payment_link, "booking": txn.booking})


def refused_capture(txn) -> dict | None:
	"""The money a gateway captured for this charge that TEX refused to count (G-67), as the
	gateway stated it: {provider_ref, amount, currency}. A missing amount or currency is the
	charge's own. None when there is none, or when there are several (those are refunded in
	the gateway's merchant panel)."""
	if txn.txn_type != "Charge" or txn.status == "Succeeded":
		return None
	rows = frappe.get_all("TEX Audit Event", filters={"action": "payment.capture_mismatch",
	                                                  "reference_doctype": "TEX Payment Transaction",
	                                                  "reference_name": txn.name}, pluck="new_value")
	captures = {c.get("provider_ref"): c for c in (json.loads(v or "{}") or {} for v in rows)}
	if len(captures) != 1:
		return None
	(ref, c), = captures.items()
	if not ref:
		return None
	ccy = c.get("currency") or txn.currency
	return {"provider_ref": ref, "currency": ccy,
	        "amount": quantize(D(c.get("amount")), ccy) if c.get("amount") else from_db(txn.amount, txn.currency)}


def _lock_link_then_payment(transaction: str, link: str | None = None) -> None:
	"""Lock order for a payment: its link first (if any), then the payment row. ``pay_link``
	holds the link while it reuses or starts the link's charge, so a callback of that charge
	must never hold the charge while it waits for the link."""
	link = link or frappe.db.get_value("TEX Payment Transaction", transaction, "payment_link")
	if link:
		_lock("TEX Payment Link", link)
	_lock("TEX Payment Transaction", transaction)


def lock_link(name: str, *, nowait: bool = False) -> frappe._dict:
	"""Lock a payment link and read it as it is now (a locking read, not the snapshot).
	``nowait``: a link another request is starting a payment for answers at once instead of
	waiting for that request (G-68); the link is held only until its charge is on record (NEW-6)."""
	query = "SELECT name, status, amount, paid_amount, currency, property FROM `tabTEX Payment Link` WHERE name=%s"
	try:
		rows = frappe.db.sql(query + (" FOR UPDATE NOWAIT" if nowait else " FOR UPDATE"), name, as_dict=True)
	except frappe.QueryTimeoutError:
		frappe.throw(_("A payment for this link is being started. Please wait a moment and try again."), PaymentBusy)
	if not rows:
		frappe.throw(_("This payment link is not valid."), frappe.DoesNotExistError)
	return rows[0]


def link_charge_key(link: str, due, provider_account: str, property: str) -> str:
	"""The idempotency key of a link's next charge (G-68): the same while its charge is
	Pending (two tabs, a double click → one charge), a new one after each Failed or Cancelled
	attempt (a retry is a new charge). A guest who switches to another gateway gets that
	gateway's own charge. Called under ``lock_link``.

	Each attempt's key is looked up, and a charge found is read again with a locking read by
	name, so its status is what it is now, not what this request's snapshot saw (a callback may
	have settled it since). A count would be a snapshot read, and a locking count would lock
	the whole table: ``payment_link`` has no index."""
	stem = f"link:{link}:{provider_account}:{to_str(D(due))}"
	for n in range(MAX_LINK_ATTEMPTS):
		key = f"{stem}:{n}"
		name = frappe.db.get_value("TEX Payment Transaction", {"idempotency_key": ns_key(property, key, "charge")})
		status = frappe.db.get_value("TEX Payment Transaction", name, "status", for_update=True) if name else None
		if status not in ("Failed", "Cancelled"):
			return key          # a new charge, the Pending one to reuse, or a paid one start_payment refuses
	frappe.throw(_("This payment link has had too many attempts. Please contact the hotel."))


def _after_charge(txn) -> None:
	amount = from_db(txn.amount, txn.currency)
	if txn.payment_link:
		# locked and read as it is now: a stale copy would lose the other payment's amount
		link = frappe.get_doc("TEX Payment Link", txn.payment_link, for_update=True)
		link.flags.tex_system_update = True
		owed = from_db(link.amount, link.currency)
		before = from_db(link.paid_amount, link.currency)
		closed = link.status if link.status in ("Cancelled", "Expired") else None
		link.paid_amount = before + amount
		link.status = "Paid" if link.paid_amount >= owed else "Partially Paid"
		link.save(ignore_permissions=True)
		if before + amount > owed:
			# the money is recorded and allocated as usual (never lost); finance refunds the excess
			audit("payment_link.overpaid", reference_doctype="TEX Payment Link", reference_name=link.name,
			      property=link.property, new={"transaction": txn.name, "amount": to_str(amount),
			                                   "link_amount": to_str(owed), "paid_before": to_str(before),
			                                   "excess": to_str(before + amount - owed), "currency": link.currency})
		if closed:
			# a checkout opened before staff cancelled the link (or before it expired) was paid:
			# the money is recorded; finance decides whether to keep or refund it
			audit("payment_link.paid_after_close", reference_doctype="TEX Payment Link", reference_name=link.name,
			      property=link.property, new={"transaction": txn.name, "amount": to_str(amount),
			                                   "status_before": closed, "currency": link.currency})
		if link.booking and not txn.booking:
			if allocate(txn.name, booking=link.booking, amount=amount, reason="payment link", _system=True) is None:
				# its booking could not take the money (kept off it, in reconciliation): the link is closed,
				# never shown "Paid" (C7)
				frappe.db.set_value("TEX Payment Link", link.name, "status", closed or "Cancelled", update_modified=False)
				audit("payment_link.closed", reference_doctype="TEX Payment Link", reference_name=link.name,
				      property=link.property, new={"transaction": txn.name, "status": closed or "Cancelled",
				                                   "why": "its booking could not take the payment"})
			return
	if txn.booking:
		allocate(txn.name, booking=txn.booking, amount=amount, reason="booking payment", _system=True)
		# a guest change waiting for this payment applies now, server-side (G-45); a failure there
		# never fails the payment: the charge is recorded and, if the change cannot apply, refunded
		from kamra.tex.services import guest_changes

		guest_changes.on_charge_succeeded(txn)


def _share(lock: bool) -> str:
	"""A locking read, once the payment is locked: it reads the rows as they are now, never an
	older snapshot of the transaction, so an amount deciding a limit counts every refund and
	allocation committed before the lock (ADR-032; G-45 re-review 4). Every writer of them holds
	the payment's lock, and the columns read by are indexed, so it waits for no one else."""
	return " LOCK IN SHARE MODE" if lock else ""


def _allocations(transaction: str, lock: bool = False) -> list:
	return frappe.db.sql(
		f"""SELECT booking, allocation_type, amount, currency FROM `tabTEX Payment Allocation`
		WHERE `transaction`=%s{_share(lock)}""", (transaction,), as_dict=True)  # nosemgrep -- constant SQL


def _refunds_of(transaction: str, status: str, lock: bool = False) -> list:
	return frappe.db.sql(
		f"""SELECT name, booking, amount, currency FROM `tabTEX Payment Transaction`
		WHERE parent_transaction=%s AND txn_type='Refund' AND status=%s{_share(lock)}""",
		(transaction, status), as_dict=True)  # nosemgrep -- constant SQL


def allocated_of(transaction: str, *, lock: bool = False) -> D:
	total = ZERO
	for r in _allocations(transaction, lock):
		a = from_db(r.amount, r.currency)
		total += -a if r.allocation_type in ("Release", "Refund") else a
	return total


def _lock(doctype: str, name: str) -> None:
	"""Row lock: allocations of one payment (or changes of one link) run one at a time, so
	two submits can never both see the same unallocated amount (G-14)."""
	frappe.db.sql(f"SELECT name FROM `tab{doctype}` WHERE name=%s FOR UPDATE", name)  # nosemgrep -- constant doctype


def _replayed_allocation(property: str, key: str | None, kind: str,
                         lock: bool = False) -> tuple[str | None, str | None]:
	"""→ (namespaced key, allocation already made with it)."""
	key = ns_key(property, key, kind)
	if not key:
		return key, None
	done = frappe.db.sql(f"SELECT name FROM `tabTEX Payment Allocation` WHERE idempotency_key=%s{_share(lock)}",
	                     (key,))  # nosemgrep -- constant SQL
	return key, (done[0][0] if done else None)


def allocate(transaction: str, *, booking: str, amount, reason: str, _system: bool = False,
             idempotency_key: str | None = None) -> str:
	txn = frappe.get_doc("TEX Payment Transaction", transaction, for_update=True)    # locked, as it is now
	if not _system:
		scope.require("payment.refund", txn.property)
	key, done = _replayed_allocation(txn.property, idempotency_key, "allocate", lock=True)
	if done:
		return done
	if txn.status != "Succeeded" or txn.txn_type != "Charge":
		frappe.throw(_("Only successful charges can be allocated."))
	from kamra.tex.services import late_payments

	# money paid in time may take its expired booking back with the money it held (B4): those charges
	# are locked now, before the booking — every payment path locks a charge, then its booking (D4)
	locked = late_payments.lock_expiry_money(booking, but=transaction) if _system and holds.paid_in_time(txn) else []
	# locked after the charge (the order a callback takes) and read as it is now (K-2b)
	b = frappe.get_doc("TEX Booking", booking, for_update=True)
	if b.property != txn.property:
		frappe.throw(_("A payment can only be allocated to a booking of the same hotel."))
	if b.currency != txn.currency:
		if not _system:
			frappe.throw(_("Currency mismatch between payment and booking."))
		# money that came in another currency (a link made before D-10) is recorded, never undone: it stays
		# on its charge, off the booking, for staff (P1-5, ADR-065); the link is closed (``_after_charge``)
		came = quantize(D(amount), txn.currency)
		late_payments.keep_off(txn, booking, late_payments.CURRENCY_MISMATCH, came, (
			f"{to_str(came)} {txn.currency} of this payment came for booking {booking}, which is in {b.currency}: "
			f"a booking is paid in its own currency. It stays on the payment, off the booking. Refund it, and send "
			f"the guest a new link in {b.currency}."))
		return None
	amount = quantize(D(amount), txn.currency)
	# money staff took themselves (the desk, points) may pay a fee; money on its way never does (C6)
	why = late_payments.problem(b, amount=amount, in_flight=_system and txn.provider not in ("Manual", "Loyalty"))
	if why == late_payments.BOOKING_CANCELLED and _system:
		from kamra.tex.services import guest_changes

		if guest_changes.request_of_charge(txn):
			why = None          # a guest change's payment: its request applies or refunds it (G-45)
	if why in late_payments.REVIVABLE and _system and late_payments.revive(txn, booking, amount, locked):
		# paid in time, its news late: the booking has its rooms back (B4)
		why = late_payments.problem(frappe.get_doc("TEX Booking", booking, for_update=True), amount=amount)
	if why:
		if not _system:
			frappe.throw(late_payments.refusal(why, b, amount))         # staff: told why, never silent (K-2c)
		# money its booking cannot take: recorded, kept off it, in reconciliation (K-2b, K-2c)
		late_payments.reconcile(txn, booking, why)
		return None
	if _system and txn.provider not in ("Manual", "Loyalty"):
		from kamra.tex.services import guest_changes

		if not guest_changes.request_of_charge(txn):
			# money that came by itself (a gateway, a link, a transfer) is taken up to what the booking owes;
			# the rest stays on the charge for staff, never twice on the booking (P1-7, ADR-065). A guest
			# change's payment is its request's to apply (G-45); staff allocate knowingly
			now = frappe.db.get_value("TEX Booking", booking, ["total_amount", "paid_amount", "currency"],
			                          as_dict=True, for_update=True)
			owed = max(ZERO, from_db(now.total_amount, now.currency) - from_db(now.paid_amount, now.currency))
			if amount > owed:
				excess = amount - owed
				late_payments.keep_off(txn, booking, late_payments.OVERPAID, excess, (
					f"{to_str(excess)} {txn.currency} of this payment is more than booking {booking} owed "
					f"({to_str(owed)} {txn.currency}): it stays on the payment, off the booking. Refund it, or "
					"allocate it to the booking the guest meant."))
				amount = owed
				if amount <= ZERO:
					return None
	# a refund still waiting for its answer takes the unallocated money first: it is not free
	free = (from_db(txn.amount, txn.currency) - allocated_of(transaction, lock=True) - refunded_of(transaction, lock=True)
	        - in_flight_of(transaction, lock=True))
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
		late_payments.settled(transaction)      # staff booked the stay again with this money
	return doc.name


def release(transaction: str, *, booking: str, amount, reason: str, idempotency_key: str | None = None,
            _system: bool = False) -> str:
	"""Take (part of) an allocation back from a booking — e.g. to transfer it. ``_system``: TEX takes
	it back itself (a booking that expired before it was paid in full, B2)."""
	_lock("TEX Payment Transaction", transaction)
	txn = frappe.get_doc("TEX Payment Transaction", transaction)
	if not _system:
		scope.require("payment.refund", txn.property)
	key, done = _replayed_allocation(txn.property, idempotency_key, "release", lock=True)
	if done:
		return done
	amount = quantize(D(amount), txn.currency)
	# what the booking holds of it, less refunds from it still waiting for their answer: money
	# being refunded never moves to another booking (G-45 re-review 4)
	on_booking = booking_nets(transaction, lock=True).get(booking, ZERO)
	free = on_booking - in_flight_from(transaction, booking, lock=True)
	if amount <= 0 or amount > free:
		if free < on_booking:
			frappe.throw(_("Only {0} of what this booking holds of this payment can move: {1} is being refunded.").format(
				to_str(free), to_str(on_booking - free)))
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


def refunded_of(transaction: str, *, lock: bool = False) -> D:
	return sum((from_db(r.amount, r.currency) for r in _refunds_of(transaction, "Succeeded", lock)), ZERO)


def pending_refunds(booking: str) -> list:
	"""Refunds that come off this booking and the gateway has not confirmed (Pending): their
	money may be back on the card already, so it is not the booking's to use (G-45 re-review)."""
	return frappe.get_all("TEX Payment Transaction", filters={"txn_type": "Refund", "status": "Pending",
	                                                          "booking": booking},
	                      fields=["name", "amount", "currency"])


def stuck(row, now=None) -> bool:
	"""A Pending refund the gateway never answered (UNKNOWN), or on record so long that the run
	asking for it must have died."""
	now = get_datetime(now or now_datetime())
	return row.error_code == "UNKNOWN" or get_datetime(row.creation) < add_to_date(now, minutes=-REFUND_STUCK_MINUTES)


def in_flight_of(transaction: str, *, lock: bool = False, exclude: str | None = None) -> D:
	"""Refunds of this charge the gateway was asked for and has not confirmed (Pending): the
	money may be gone, so it is never refunded or planned again (review of ADR-044)."""
	return sum((from_db(r.amount, r.currency) for r in _refunds_of(transaction, "Pending", lock)
	            if r.name != exclude), ZERO)


def in_flight_from(transaction: str, booking: str | None, *, lock: bool = False, exclude: str | None = None) -> D:
	"""Of those, the refunds that come off ``booking`` (None: the payment's unallocated money)."""
	return sum((from_db(r.amount, r.currency) for r in _refunds_of(transaction, "Pending", lock)
	            if r.name != exclude and (r.booking or None) == (booking or None)), ZERO)


def booking_nets(transaction: str, *, lock: bool = False) -> dict[str, D]:
	"""What each booking holds of this payment now: Allocate +, Release −, Refund −."""
	nets: dict[str, D] = {}
	for r in _allocations(transaction, lock):
		if r.booking:
			a = from_db(r.amount, r.currency)
			nets[r.booking] = nets.get(r.booking, ZERO) + (-a if r.allocation_type in ("Release", "Refund") else a)
	return nets


def _refund_source(txn, amount: D, booking: str | None, *, lock: bool = False,
                   exclude: str | None = None) -> tuple[str | None, D]:
	"""Which booking a refund comes out of, and how much of it (G-68). → (booking or None,
	amount taken off that booking).

	The payment's unallocated remainder goes first: it belongs to no booking. Only the rest
	comes off a booking, where the money sits *now* (after a transfer it is on the new
	booking, not on ``txn.booking``): the named booking, at most what it holds; without a
	name, the one booking holding money, and a question when several do. When nothing comes
	off a booking, the refund names none. Money other refunds still waiting for their answer
	take (all but ``exclude``, the refund being settled) is not counted (re-review 4);
	``lock``: read under the payment's lock (locking reads)."""
	ccy = txn.currency
	nets = booking_nets(txn.name, lock=lock)
	holding = {b: n - in_flight_from(txn.name, b, lock=lock, exclude=exclude) for b, n in nets.items()}
	holding = {b: n for b, n in holding.items() if n > 0}
	unallocated = (from_db(txn.amount, ccy) - allocated_of(txn.name, lock=lock) - refunded_of(txn.name, lock=lock)
	               - in_flight_from(txn.name, None, lock=lock, exclude=exclude))
	rest = max(ZERO, amount - max(ZERO, unallocated))
	if booking:
		held = holding.get(booking, ZERO)
		if rest > held:
			frappe.throw(_("Booking {0} holds {1} {3} of this payment and {2} {3} of it is unallocated: at most "
			               "{4} {3} can be refunded from this booking.").format(
				booking, to_str(held), to_str(unallocated), ccy, to_str(held + unallocated)))
		return (booking, rest) if rest > 0 else (None, ZERO)
	if not rest:
		return None, ZERO
	if len(holding) > 1:
		frappe.throw(_("{0} {1} of this refund must come from a booking and this payment is allocated to several "
		               "bookings ({2}): choose which booking the refund comes from.").format(
			to_str(rest), ccy, ", ".join(sorted(holding))))
	target, held = next(iter(holding.items()), (None, ZERO))
	if rest > held:
		frappe.throw(_("At most {0} {1} can be refunded.").format(to_str(held + unallocated), ccy))
	return target, rest


def auto_refundable(txn) -> bool:
	"""Whether TEX may refund this charge by itself (G-45): a succeeded charge of an enabled
	account whose provider refunds through TEX and may settle today. Manual payments, bank
	transfers and pay at hotel are refunded by staff."""
	if txn.txn_type != "Charge" or txn.status != "Succeeded" or not txn.provider_account:
		return False
	acc = frappe.db.get_value("TEX Payment Provider Account", txn.provider_account,
	                          ["provider", "environment", "enabled", "gateway_url"], as_dict=True)
	cls = REGISTRY.get((acc or {}).get("provider") or "")
	return bool(acc and acc.enabled and cls and cls.supports_refund and not account_rule(acc, "settle"))


def booking_charges(booking: str) -> list[dict]:
	"""The succeeded charges holding this booking's money now (G-45): what each holds for it
	(its net allocation, at most what is still refundable), whether TEX may refund it by itself,
	when it was taken, its provider and whether it is loyalty points (never paid back as cash,
	O-19). A charge that also holds unallocated money is left to staff: a refund of it takes that
	money first (ADR-042), not this booking's."""
	out = []
	for name in sorted(set(frappe.get_all("TEX Payment Allocation", filters={"booking": booking},
	                                      pluck="transaction"))):
		t = frappe.db.get_value("TEX Payment Transaction", name, ["name", "txn_type", "status", "amount", "currency",
		                                                           "provider_account", "provider", "completed_at",
		                                                           "creation"], as_dict=True)
		if not t or t.txn_type != "Charge" or t.status != "Succeeded":
			continue
		held = booking_nets(name).get(booking, ZERO)
		if held <= 0:
			continue
		refunded = refunded_of(name)
		in_flight = in_flight_of(name)
		amount = from_db(t.amount, t.currency)
		unallocated = amount - allocated_of(name) - refunded
		out.append({"transaction": name, "available": max(ZERO, min(held, amount - refunded - in_flight)),
		            # a refund of it the gateway never confirmed: staff check it first
		            "supported": auto_refundable(t) and unallocated <= 0 and in_flight <= 0,
		            "at": str(get_datetime(t.completed_at or t.creation)), "provider": t.provider,
		            "points": t.provider == "Loyalty"})
	return sorted(out, key=lambda c: (c["at"], c["transaction"]), reverse=True)


def _by_key(key: str, lock: bool = False):
	rows = frappe.db.sql(f"SELECT name, status FROM `tabTEX Payment Transaction` WHERE idempotency_key=%s{_share(lock)}",
	                     (key,), as_dict=True)  # nosemgrep -- constant SQL
	return rows[0] if rows else None


def _take_off(txn, r, booking: str, amount: D, reason: str) -> None:
	"""Refund ``r`` takes ``amount`` off ``booking``: an allocation keyed to the refund (a
	correction finds it again) and the booking's paid amount."""
	from kamra.tex.services import booking as booking_svc

	frappe.get_doc({"doctype": "TEX Payment Allocation", "property": txn.property, "transaction": txn.name,
	                "allocation_type": "Refund", "amount": amount, "currency": txn.currency, "booking": booking,
	                "reason": reason, "actor": frappe.session.user,
	                "idempotency_key": ns_key(txn.property, f"refund-of:{r.name}", "allocate")}).insert(
		ignore_permissions=True)
	booking_svc.apply_payment(booking, -amount, reference=f"refund {r.name}")


def _taken_off(txn, refund_name: str) -> tuple[str | None, D]:
	"""→ (booking, amount) refund ``refund_name`` took off a booking, if any."""
	row = frappe.db.get_value("TEX Payment Allocation",
	                          {"idempotency_key": ns_key(txn.property, f"refund-of:{refund_name}", "allocate")},
	                          ["booking", "amount", "currency"], as_dict=True)
	return (row.booking, from_db(row.amount, row.currency)) if row else (None, ZERO)


def refund(transaction: str, *, amount, reason: str, idempotency_key: str, booking: str | None = None,
           _system: bool = False, durable: bool = False, on_record=None, relock=None, on_conflict=None,
           _late: bool = False) -> dict:
	"""Refund a successful charge, or money a gateway captured that TEX refused to count
	(an amount or currency mismatch, G-67): that refund is in the currency the gateway
	stated, against the captured payment, and never touches a booking.

	``_system``: a refund TEX makes by itself for a guest's own change (G-45: an overpayment
	under the hotel's refund policy, or a payment for a change that could not apply). Only
	``services.guest_changes`` passes it, always naming the booking; staff need payment.refund.
	``_late`` (with ``_system``): a late payment in reconciliation whose rooms are gone, never on
	a booking (``services.late_payments.refund_queued``, K-2b).

	``durable`` (the staff endpoint and the refund job): the refund is committed as Pending
	before the gateway is asked. A gateway that answers "no" (``ProviderError`` or a Failed
	outcome) is a definite failure; any other error (timeout, connection, server) leaves the
	refund Pending with the error UNKNOWN and raises ``RefundUnknown``: the gateway may have
	refunded, so the same key never asks again and staff check it at the gateway. A replay of
	the key returns the refund as it is (``status``).

	``on_record(refund)``: called with the new refund's name before it is committed, so the
	caller's record of it (the guest change making it) is durable with it (G-45 re-review).

	After the gateway answered (``durable``), the locks are taken again in one order: the
	booking (``relock()`` locks it and whatever the caller holds with it: a guest change locks
	its booking, then its request), then the refund, then its charge: the order staff take to
	record an outcome (``finish_unknown_refund``). The refund is read again as it is now: if an
	outcome was recorded for it meanwhile, it is never overwritten: the same answer is taken as
	it stands (``recorded``), another one (or none) is a ``RefundConflict``; ``on_conflict(refund)``
	is called first, while every lock is held, so the caller stops whatever depends on it (a
	guest change stops all its runs, re-review 4). Where the money comes off is decided again
	then, under the locks: a transfer meanwhile cannot move money being refunded (``release``),
	and the refund takes it off where it is.

	Every amount deciding a limit is read with a locking read once the charge is locked
	(``_share``), the idempotency key again too (re-review 4)."""
	txn = frappe.get_doc("TEX Payment Transaction", transaction)
	if _system:
		if _late and txn.reconciliation != "Refund Queued":
			frappe.throw(_("Only a late payment queued for its refund is refunded this way."))
		if not booking and not _late:
			frappe.throw(_("A refund TEX makes by itself names the booking it comes from."))
	else:
		scope.require("payment.refund", txn.property)
	if not (reason or "").strip():
		frappe.throw(_("A refund reason is required."))
	if booking and frappe.db.get_value("TEX Booking", booking, "property") != txn.property:
		frappe.throw(_("The booking belongs to another hotel."))
	idempotency_key = ns_key(txn.property, idempotency_key, "refund")
	if not idempotency_key:
		frappe.throw(_("Idempotency key required."))
	done = frappe.db.get_value("TEX Payment Transaction", {"idempotency_key": idempotency_key}, ["name", "status"],
	                           as_dict=True)
	if done:
		return {"refund": done.name, "replay": True, "status": done.status}
	txn = frappe.get_doc("TEX Payment Transaction", transaction, for_update=True)   # locked, as it is now
	again = _by_key(idempotency_key, lock=True)                                      # another tab, just before
	if again:
		return {"refund": again.name, "replay": True, "status": again.status}
	if txn.txn_type != "Charge":
		frappe.throw(_("Only successful charges can be refunded."))
	if txn.status == "Succeeded":
		ccy, ref = txn.currency, txn.provider_ref
		amount = quantize(D(amount), ccy)
		# a refund the gateway never confirmed may have been made: it is not refundable again
		refundable = from_db(txn.amount, ccy) - refunded_of(transaction, lock=True) - in_flight_of(transaction, lock=True)
	else:
		capture = refused_capture(txn)
		if not capture:
			frappe.throw(_("Only successful charges, or a capture TEX refused, can be refunded."))
		if booking:
			frappe.throw(_("This money was never on a booking: refund it without choosing one."))
		if not frappe.db.exists("Currency", capture["currency"]):
			frappe.throw(_("The gateway stated an unknown currency ({0}): refund it in the gateway's merchant "
			               "panel.").format(capture["currency"]))
		ccy, ref = capture["currency"], capture["provider_ref"]
		amount = quantize(D(amount), ccy)
		refundable = capture["amount"] - refunded_of(transaction, lock=True) - in_flight_of(transaction, lock=True)
	if amount <= 0 or amount > refundable:
		frappe.throw(_("At most {0} {1} can be refunded.").format(to_str(refundable), ccy))
	target, from_booking = (_refund_source(txn, amount, booking, lock=True) if txn.status == "Succeeded"
	                        else (None, ZERO))
	first = target              # the booking first decided for, before a durable refund decides again
	provider = provider_for(txn.provider_account, purpose="settle", transaction=txn.name)
	r = _new_txn(property=txn.property, txn_type="Refund", method=txn.method, amount=amount, currency=ccy,
	             provider_account=txn.provider_account, provider=txn.provider, idempotency_key=idempotency_key,
	             parent_transaction=txn.name, booking=target, reason=reason)
	if on_record:
		on_record(r.name)
	if durable:
		_durable_commit()                 # on record before the gateway acts (review of ADR-044)
	error = None
	try:
		outcome = provider.refund(ref, amount, ccy, reference=r.name)
	except ProviderError as e:
		outcome = Outcome(status="Failed", error_code="PROVIDER", error_message=str(e))
	except Exception as e:
		outcome, error = None, str(e)
	if durable:
		# the commit released every lock: the booking first (with what the caller holds), then
		# this refund as it is now, then its charge (third review of ADR-044)
		if relock:
			relock()
		elif target:
			frappe.db.get_value("TEX Booking", target, "name", for_update=True)
		now_status = frappe.db.get_value("TEX Payment Transaction", r.name, "status", for_update=True)
		_lock("TEX Payment Transaction", txn.name)
		if now_status != "Pending":
			return _answered_after_record(r, txn, outcome, now_status, error, durable, on_conflict)
		r.reload()
		if outcome and outcome.status == "Succeeded" and txn.status == "Succeeded":
			# where the money is now, under the locks (as a verification decides it): never a
			# booking it was moved off meanwhile (re-review 4)
			target, from_booking = _refund_source(txn, amount, booking, lock=True, exclude=r.name)
			if target != r.booking:
				r.flags.tex_system_update = True          # decided again by TEX, never by hand
				r.booking = target
	if outcome is None:
		_refund_unknown(r, txn, error or "", durable)
	r.status = outcome.status
	r.provider_ref = outcome.provider_ref
	r.raw_status = outcome.raw_status
	r.error_message = (outcome.error_message or "")[:500] or None
	r.completed_at = now_datetime()
	r.save(ignore_permissions=True)
	if r.status == "Succeeded" and target and from_booking > 0:
		# only what comes off the booking is taken from it; the rest was unallocated money
		_take_off(txn, r, target, from_booking, reason)
	from kamra.tex.services import late_payments

	if txn.status == "Succeeded" and r.status in ("Succeeded", "Failed"):
		# a booking that ended never confirmed while this refund was on its way holds no money (P1-3): the
		# booking it comes off now, and the one first decided for when the money moved meanwhile (review)
		for name in dict.fromkeys(b for b in (r.booking or booking, first) if b):
			late_payments.after_refund(r.name, name)
	if r.status == "Succeeded":
		late_payments.settled(txn.name)          # a late payment in reconciliation, given back
	audit("payment.refund", reference_doctype="TEX Payment Transaction", reference_name=r.name,
	      property=txn.property, new={"of": txn.name, "amount": to_str(amount), "currency": ccy, "status": r.status,
	                                  "booking": target, "from_booking": to_str(from_booking),
	                                  "refused_capture": txn.status != "Succeeded"}, reason=reason)
	return {"refund": r.name, "status": r.status}


def _answered_after_record(r, txn, outcome, recorded: str, error: str | None, durable: bool,
                           on_conflict=None) -> dict:
	"""The gateway answered a refund whose outcome was recorded meanwhile. The same answer: the
	books already say it (nothing is applied twice). Another answer, or none: a conflict, open
	until staff record what the gateway actually did (``correct_refund``)."""
	said = outcome.status if outcome else "no answer"
	if said == recorded:
		return {"refund": r.name, "status": recorded, "recorded": True}
	audit("payment.refund_outcome_conflict", reference_doctype="TEX Payment Transaction", reference_name=r.name,
	      property=txn.property, new={"of": txn.name, "recorded": recorded, "gateway": said,
	                                  "gateway_ref": outcome.provider_ref if outcome else None,
	                                  "gateway_error": ((outcome.error_message if outcome else error) or "")[:200],
	                                  "amount": to_str(from_db(r.amount, r.currency)), "currency": r.currency,
	                                  "booking": r.booking})
	if on_conflict:
		on_conflict(r.name)
	if durable:
		_durable_commit()
	raise RefundConflict(_("The gateway answered refund {0} ({1}) after it was recorded as {2}: reconcile it at the "
	                       "gateway. TEX refunds nothing more on it.").format(r.name, said, recorded))


def _refund_unknown(r, txn, error: str, durable: bool) -> None:
	"""The gateway did not answer: the refund stays Pending, marked UNKNOWN, on record (and
	committed) before ``RefundUnknown`` is raised. The booking is not changed until staff know."""
	frappe.clear_last_message()
	log_exception(f"TEX refund {r.name} unanswered")
	r.flags.tex_system_update = True
	r.error_code = "UNKNOWN"
	r.error_message = ("The gateway did not answer this refund (it may have been made): check it at the gateway "
	                   "before refunding again. " + error)[:500]
	r.save(ignore_permissions=True)
	audit("payment.refund_unknown", reference_doctype="TEX Payment Transaction", reference_name=r.name,
	      property=txn.property, new={"of": txn.name, "amount": to_str(from_db(r.amount, r.currency)),
	                                  "currency": r.currency, "booking": r.booking})
	if durable:
		_durable_commit()
	raise RefundUnknown(_("The payment gateway did not confirm the refund. Check it at the gateway before "
	                      "refunding again."))


def finish_unknown_refund(refund_txn: str, *, outcome: str, reference: str | None, reason: str) -> dict:
	"""Staff checked at the gateway a refund it never confirmed (``RefundUnknown``, or left
	Pending by a run that died), and record what it did: ``Succeeded`` takes the money off the
	booking the refund named (the payment's unallocated money first, ADR-042), ``Failed`` leaves
	it where it is. Needs payment.refund. Callers go through ``guest_changes.verify_refund``,
	which also settles the guest change the refund was made for."""
	r = frappe.get_doc("TEX Payment Transaction", refund_txn, for_update=True)
	scope.require("payment.refund", r.property)
	if r.txn_type != "Refund" or r.status != "Pending":
		frappe.throw(_("Only a refund waiting for its outcome can be settled here ({0}).").format(r.status))
	if not stuck(r):
		# its gateway call may still be running: its answer would then be lost (third review)
		frappe.throw(_("This refund was asked for a moment ago and the gateway's answer may still come: check again "
		               "in a few minutes."))
	if outcome not in ("Succeeded", "Failed"):
		frappe.throw(_("Choose whether the gateway refunded it."))
	if not (reason or "").strip():
		frappe.throw(_("A reason is required."))
	txn = frappe.get_doc("TEX Payment Transaction", r.parent_transaction, for_update=True)
	amount = from_db(r.amount, r.currency)
	target, from_booking = (_refund_source(txn, amount, r.booking, lock=True, exclude=r.name)
	                        if outcome == "Succeeded" and txn.status == "Succeeded" else (None, ZERO))
	r.flags.tex_system_update = True
	r.status = outcome
	r.raw_status = "VERIFIED BY STAFF"
	r.provider_ref = (reference or "").strip()[:140] or r.provider_ref
	r.error_message = f"{outcome} (checked at the gateway by {frappe.session.user}): {reason.strip()}"[:500]
	r.completed_at = now_datetime()
	r.save(ignore_permissions=True)
	if outcome == "Succeeded" and target and from_booking > 0:
		_take_off(txn, r, target, from_booking, reason)
	from kamra.tex.services import late_payments

	# a booking that ended never confirmed while this refund was on its way holds no money (P1-3)
	late_payments.after_refund(r.name, r.booking or target)
	late_payments.settled(txn.name)             # its reconciliation follows the refund's outcome (C4)
	audit("payment.refund_verified", reference_doctype="TEX Payment Transaction", reference_name=r.name,
	      property=r.property, new={"of": txn.name, "outcome": outcome, "amount": to_str(amount),
	                                "currency": r.currency, "booking": target, "from_booking": to_str(from_booking)},
	      reason=reason)
	return {"refund": r.name, "status": r.status, "amount": to_str(amount), "currency": r.currency}


def refund_outside(transaction: str, *, amount, reason: str, reference: str, idempotency_key: str,
                   booking: str | None = None, _system: bool = False) -> dict:
	"""Money the hotel gave back outside TEX (cash at the desk, a bank transfer, the card
	terminal): recorded as a succeeded Manual refund of ``transaction`` and taken off the
	booking holding it, so it is no longer counted as paid nor offered to the guest as credit
	(G-93). No gateway is asked. Needs payment.refund (``_system``: a guest change's staff close,
	already checked). Audited ``payment.refund_outside``; idempotent by key.

	With ``booking`` named, the money comes off that booking only: it was given back to that
	booking's guest, never the payment's unallocated money nor another booking's (re-review 4).
	Without, as any refund (the unallocated money first, then the one booking holding the rest).
	The bookings are locked before the payment, the order of every refund; the amounts deciding
	the limits are locking reads. → the refund, and ``from_booking``: what came off ``booking``."""
	holding = [booking] if booking else sorted(b for b, n in booking_nets(transaction).items() if n > 0)
	for name in holding:
		frappe.db.get_value("TEX Booking", name, "name", for_update=True)       # the booking(s) first
	txn = frappe.get_doc("TEX Payment Transaction", transaction, for_update=True)
	if not _system:
		scope.require("payment.refund", txn.property)
	if not (reason or "").strip():
		frappe.throw(_("A refund reason is required."))
	if not (reference or "").strip():
		frappe.throw(_("Say how it was refunded (the receipt or transfer reference)."))
	if booking and frappe.db.get_value("TEX Booking", booking, "property") != txn.property:
		frappe.throw(_("The booking belongs to another hotel."))
	key = ns_key(txn.property, idempotency_key, "refund-outside")
	if not key:
		frappe.throw(_("Idempotency key required."))
	done = _by_key(key, lock=True)
	if done:
		target, took = _taken_off(txn, done.name)
		return {"refund": done.name, "replay": True, "status": done.status, "booking": target,
		        "from_booking": to_str(took)}
	if txn.txn_type != "Charge" or txn.status != "Succeeded":
		frappe.throw(_("Only successful payments can be refunded."))
	ccy = txn.currency
	amount = quantize(D(amount), ccy)
	refundable = from_db(txn.amount, ccy) - refunded_of(transaction, lock=True) - in_flight_of(transaction, lock=True)
	if amount <= 0 or amount > refundable:
		frappe.throw(_("At most {0} {1} can be refunded.").format(to_str(refundable), ccy))
	if booking:
		held = booking_nets(transaction, lock=True).get(booking, ZERO) - in_flight_from(transaction, booking, lock=True)
		if amount > held:
			frappe.throw(_("Booking {0} holds {1} {2} of this payment: at most that can be recorded as given back to "
			               "its guest.").format(booking, to_str(max(ZERO, held)), ccy))
		target, from_booking = booking, amount
	else:
		target, from_booking = _refund_source(txn, amount, None, lock=True)
		if target and target not in holding:
			frappe.throw(_("The bookings holding this payment changed meanwhile: please try again."))
	r = _new_txn(property=txn.property, txn_type="Refund", method="Manual", amount=amount, currency=ccy,
	             provider="Manual", provider_ref=reference.strip()[:140], idempotency_key=key,
	             parent_transaction=txn.name, booking=target, reason=reason.strip()[:500])
	r.status = "Succeeded"
	r.raw_status = "REFUNDED OUTSIDE TEX"
	r.completed_at = now_datetime()
	r.save(ignore_permissions=True)
	if target and from_booking > 0:
		_take_off(txn, r, target, from_booking, reason)
	from kamra.tex.services import late_payments

	late_payments.settled(txn.name)             # money in reconciliation given back outside TEX (C4)
	audit("payment.refund_outside", reference_doctype="TEX Payment Transaction", reference_name=r.name,
	      property=txn.property, new={"of": txn.name, "amount": to_str(amount), "currency": ccy, "booking": target,
	                                  "from_booking": to_str(from_booking), "reference": reference.strip()[:140]},
	      reason=reason)
	return {"refund": r.name, "status": r.status, "booking": target, "from_booking": to_str(from_booking)}


def conflict_open(refund: str) -> dict | None:
	"""The gateway's answer that contradicted the outcome recorded for this refund, while staff
	have not recorded what it actually did: {"recorded", "gateway", ...}; None otherwise."""
	row = frappe.db.get_value("TEX Audit Event", {"action": "payment.refund_outcome_conflict",
	                                              "reference_name": refund}, "new_value", order_by="creation desc")
	if not row or frappe.db.exists("TEX Audit Event", {"action": "payment.refund_conflict_resolved",
	                                                   "reference_name": refund}):
		return None
	try:
		return json.loads(row) or {}
	except ValueError:
		return {}


def correct_refund(refund_txn: str, *, outcome: str, reason: str, reference: str | None = None) -> dict:
	"""Staff record what the gateway actually did with a refund whose recorded outcome its answer
	contradicted (``payment.refund_outcome_conflict``), after checking it there: the refund and
	the booking are put right, and the conflict is resolved (audited
	``payment.refund_conflict_resolved``; the system status no longer fails on it). A refund
	recorded as not made that was made comes off the booking (where the money is now, as any
	refund); one recorded as made that was not goes back onto the booking it came off. The
	outcome already recorded only resolves it. Needs payment.refund; the caller locks the
	booking first (``guest_changes.resolve_conflict``)."""
	r = frappe.get_doc("TEX Payment Transaction", refund_txn, for_update=True)
	scope.require("payment.refund", r.property)
	if r.txn_type != "Refund" or r.status not in ("Succeeded", "Failed") or not conflict_open(r.name):
		frappe.throw(_("There is no open conflict on this refund."))
	if outcome not in ("Succeeded", "Failed"):
		frappe.throw(_("Choose whether the gateway refunded it."))
	if not (reason or "").strip():
		frappe.throw(_("A reason is required."))
	txn = frappe.get_doc("TEX Payment Transaction", r.parent_transaction, for_update=True)
	amount, recorded = from_db(r.amount, r.currency), r.status
	booking, moved = r.booking, ZERO
	if outcome != recorded:
		if outcome == "Succeeded":
			booking, moved = (_refund_source(txn, amount, r.booking, lock=True, exclude=r.name)
			                  if txn.status == "Succeeded" else (None, ZERO))
			if booking and moved > 0:
				_take_off(txn, r, booking, moved, reason)
		else:
			booking, moved = _taken_off(txn, r.name)
			if booking and moved > 0:
				from kamra.tex.services import booking as booking_svc

				frappe.get_doc({"doctype": "TEX Payment Allocation", "property": txn.property, "transaction": txn.name,
				                "allocation_type": "Allocate", "amount": moved, "currency": txn.currency,
				                "booking": booking, "reason": f"refund {r.name} was not made: {reason.strip()}"[:500],
				                "actor": frappe.session.user,
				                "idempotency_key": ns_key(txn.property, f"put-back:{r.name}", "allocate")}).insert(
					ignore_permissions=True)
				booking_svc.apply_payment(booking, moved, reference=f"refund {r.name} not made")
		r.flags.tex_system_update = True
		r.status = outcome
		r.raw_status = "CORRECTED BY STAFF"
		r.provider_ref = (reference or "").strip()[:140] or r.provider_ref
		r.error_message = (f"{outcome} (the gateway's answer, recorded by {frappe.session.user} after it contradicted "
		                   f"{recorded}): {reason.strip()}")[:500]
		r.save(ignore_permissions=True)
	from kamra.tex.services import late_payments

	# money put back on a booking that ended never confirmed comes off it again (P1-3)
	late_payments.after_refund(r.name, booking or r.booking, key=f"refund-fix:{r.name}")
	late_payments.settled(txn.name)             # a refund found not made opens its reconciliation again (C4)
	audit("payment.refund_conflict_resolved", reference_doctype="TEX Payment Transaction", reference_name=r.name,
	      property=r.property, new={"of": txn.name, "recorded": recorded, "outcome": outcome, "amount": to_str(amount),
	                                "currency": r.currency, "booking": booking, "moved": to_str(moved)}, reason=reason)
	return {"refund": r.name, "status": r.status, "amount": to_str(amount), "currency": r.currency}


def mark_transfer_received(transaction: str, *, reference: str, value_date=None, amount=None) -> dict:
	"""Staff saw a bank transfer arrive. ``value_date``: the day the money was on the account (its
	valör), which decides whether it was paid in time (D3); not before the charge, never in the
	future (the staff API requires it). ``amount``: what arrived, more than nothing and at most what
	was asked (P1-11): a transfer that came short (a bank's fee) is recorded and allocated as it came;
	a booking it no longer pays the deposit of keeps waiting for the rest, and expires with its hold."""
	_lock_link_then_payment(transaction)
	txn = frappe.get_doc("TEX Payment Transaction", transaction, for_update=True)   # as it is now
	scope.require("payment.refund", txn.property)
	if txn.provider != "Bank Transfer" or txn.status != "Pending":
		frappe.throw(_("Only pending bank transfers can be confirmed."))
	now = now_datetime()
	asked = from_db(txn.amount, txn.currency)
	came = asked if amount in (None, "") else _finite(amount)
	if came is None:
		frappe.throw(_("Amount must be a number."))
	came = quantize(came, txn.currency)
	if came <= ZERO or came > asked:
		frappe.throw(_("The amount received must be more than zero and at most the {0} {1} asked.").format(
			to_str(asked), txn.currency))
	if value_date:
		value_date = getdate(value_date)
		if value_date > now.date() or value_date < get_datetime(txn.creation).date():
			frappe.throw(_("The value date must be between the day the transfer was asked for and today."))
		txn.captured_at = get_datetime(value_date)
	txn.flags.tex_system_update = True
	txn.amount = came
	txn.status = "Succeeded"
	txn.raw_status = "RECEIVED"
	txn.provider_ref = reference[:140]
	txn.completed_at = now
	txn.save(ignore_permissions=True)
	_after_charge(txn)
	audit("payment.transfer_received", reference_doctype="TEX Payment Transaction", reference_name=txn.name,
	      property=txn.property, new={"reference": reference, "value_date": str(value_date) if value_date else None,
	                                  "amount": to_str(came), "asked": to_str(asked)})
	# money its booking could not take is in reconciliation: staff see it at once (K-2c)
	return {"transaction": txn.name, "status": txn.status,
	        "reconciliation": frappe.db.get_value("TEX Payment Transaction", txn.name, "reconciliation") or None}


def _finite(value) -> D | None:
	"""``value`` as a finite Decimal, or None when it is not a number (text, NaN, Infinity)."""
	try:
		d = D(value)
	except (TypeError, ValueError):
		return None
	return d if d.is_finite() else None


def refuse_if_it_cannot_take(booking: str, amount) -> None:
	"""C5: staff paying a booking that cannot take the money (cancelled, expired, its rooms given back)
	are told why and nothing is recorded — never money parked at the desk, nor points burned. The
	booking is locked (a new charge follows it, locked by no one else)."""
	from kamra.tex.services import late_payments

	b = frappe.get_doc("TEX Booking", booking, for_update=True)
	amount = quantize(D(amount), b.currency)
	why = late_payments.problem(b, amount=amount)
	if why:
		frappe.throw(late_payments.refusal(why, b, amount))


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
	refuse_if_it_cannot_take(booking, amount)
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
	# money taken for a booking that could not take it stays on record in reconciliation (K-2c)
	return {"transaction": txn.name, "status": txn.status,
	        "reconciliation": frappe.db.get_value("TEX Payment Transaction", txn.name, "reconciliation") or None}


# ─── payment links ───────────────────────────────────────────────────────


LINK_SAVEPOINT = "tex_create_link"


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
	if reservation:
		# a TEX room's link belongs to its booking: it holds the booking's rooms and its payment is
		# allocated to it (D6)
		of = frappe.db.get_value("Reservation", reservation, "tex_booking")
		if booking and of and of != booking:
			frappe.throw(_("The reservation belongs to another booking."))
		booking = booking or of or None
	if booking:
		ccy = frappe.db.get_value("TEX Booking", booking, "currency")
		if currency != ccy:
			# a booking is paid in its own currency: TEX never converts a payment (D-10, P1-5)
			frappe.throw(_("Booking {0} is in {1}: send its payment link in {1}, not {2}.").format(
				booking, ccy, currency))
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
	if provider_account:
		# staff hear now why the account could not take the money, not the guest later (G-67)
		provider_for(provider_account)
	token = secrets.token_urlsafe(24)
	expires_at = add_to_date(now_datetime(), hours=max(1, min(int(expires_hours or 72), 24 * 60)))
	# the key is unique in the database (O-38): a request that lost the race to the same key undoes its
	# own steps back to here and answers with the link the other one made (one link, one e-mail)
	frappe.db.savepoint(LINK_SAVEPOINT)
	messages = frappe.local.message_log
	mark = len(messages)
	# a link of a booking waiting for its payment holds its rooms for the link hold and expires with
	# it (B6); a standalone link keeps its own validity (K-2d)
	expires_at, rooms_held_until = holds.hold_for_link(booking, expires_at)
	doc = frappe.get_doc({
		"doctype": "TEX Payment Link", "property": property, "status": "Active", "amount": amount,
		"currency": currency, "description": (description or "")[:500],
		"expires_at": expires_at,
		"provider_account": provider_account, "booking": booking, "reservation": reservation,
		"guest_name": guest_name, "guest_email": guest_email, "token_hash": link_token_hash(token),
		# the URL embeds the bearer token: returned once, never stored (only its hash is)
		"idempotency_key": idempotency_key, "public_url": None,
	})
	try:
		doc.insert(ignore_permissions=True)
	except frappe.UniqueValidationError:
		if not idempotency_key:
			raise
		frappe.db.rollback(save_point=LINK_SAVEPOINT)
		del messages[mark:]           # Frappe's "must be unique" message is not this request's answer
		# a locking read: the link the other request committed, not this transaction's older snapshot
		made = frappe.db.sql("SELECT name FROM `tabTEX Payment Link` WHERE idempotency_key=%s LOCK IN SHARE MODE",
		                     idempotency_key)
		if not made:
			raise
		return {"link": made[0][0], "replay": True}
	url = _link_url(property, booking, token)
	emailed = False
	if send_email:
		from kamra.tex.services import notify

		emailed = notify.payment_link(doc.name, url, language)
	audit("payment_link.create", reference_doctype="TEX Payment Link", reference_name=doc.name, property=property,
	      new={"amount": to_str(amount), "currency": currency, "booking": booking, "emailed": emailed,
	           "expires_at": str(expires_at)})
	# when the link stops working and, for a booking waiting for its payment, until when its rooms are held
	return {"link": doc.name, "url": url, "token": token, "emailed": emailed, "expires_at": str(expires_at),
	        "rooms_held_until": str(rooms_held_until) if rooms_held_until else None}


def reissue_link(name: str, *, send_email: bool = False, language: str = "en") -> dict:
	"""New token for an open link (the old URL stops working) — staff lost or resend. Never for a link
	its booking cannot take the money of, or asking more than it owes (E4). The link is locked first and read
	as it is now (P1-4): a guest starting its payment holds the link and asks for the booking next, so the
	booking (``link_refusal``) is never taken before the link."""
	link = frappe.get_doc("TEX Payment Link", name, for_update=True)
	scope.require("payment.link", link.property)
	if link.status not in ("Active", "Partially Paid"):
		frappe.throw(_("Only open links can be reissued."))
	if link.booking:
		why = link_refusal(link.booking, from_db(link.amount, link.currency) - from_db(link.paid_amount, link.currency),
		                   link.currency, guest=False)
		if why:
			frappe.throw(why)
	token = secrets.token_urlsafe(24)
	link.flags.tex_system_update = True
	link.token_hash = link_token_hash(token)
	link.save(ignore_permissions=True)
	url = _link_url(link.property, link.booking, token)
	emailed = False
	if send_email:
		from kamra.tex.services import notify

		emailed = notify.payment_link(link.name, url, language)
	audit("payment_link.reissue", reference_doctype="TEX Payment Link", reference_name=name, property=link.property,
	      new={"emailed": emailed})
	return {"link": link.name, "url": url, "token": token, "emailed": emailed,
	        "expires_at": str(link.expires_at) if link.expires_at else None}


def link_refusal(booking: str, amount, currency: str, *, guest: bool) -> str | None:
	"""E4: why a link of ``booking`` asking ``amount`` may not be paid, nor sent again: it asks another
	currency than the booking's (a booking is paid in its own currency, D-10: a link made before that
	rule); its booking cannot take the money (cancelled, expired, its rooms given back:
	``late_payments.problem``; a link's money is on its way, never kept as a fee, C6); or it owes less
	than the link asks. None when it may. Locks the booking (after the link: the order of a link's
	payment). ``guest``: told to the guest, else to staff."""
	from kamra.tex.services import late_payments

	b = frappe.get_doc("TEX Booking", booking, for_update=True)
	if currency != b.currency:
		return (_("This payment link cannot be paid online. Please contact the hotel.") if guest else
		        _("Booking {0} is in {1}; this link asks {2}: cancel it and send a new link in {1}.").format(
			        b.name, b.currency, currency))
	amount = quantize(D(amount), currency)
	if late_payments.problem(b, amount=amount, in_flight=True):
		return (_("This payment link can no longer be paid: its booking cannot take payments any more. Please "
		          "contact the hotel.") if guest else
		        _("Booking {0} ({1}) cannot take this link's payment: cancel the link.").format(b.name, _(b.status)))
	owed = quantize(from_db(b.total_amount, b.currency) - from_db(b.paid_amount, b.currency), b.currency)
	if amount <= owed:
		return None
	if guest:
		return (_("This payment link can no longer be paid: its booking is paid in full.") if owed <= ZERO else
		        _("This payment link asks {0} {1}, more than its booking still owes ({2} {1}). Please contact the "
		          "hotel for a new link.").format(to_str(amount), currency, to_str(owed)))
	return _("Booking {0} owes {1} {2}, less than this link asks ({3} {2}): cancel it and send a new link.").format(
		b.name, to_str(max(owed, ZERO)), currency, to_str(amount))


def close_links_of(booking: str, why: str) -> list[str]:
	"""E4: the open links of a booking that takes no more money — paid in full, cancelled or expired — are
	closed (``Cancelled``; ``Expired`` once past their own expiry), audited; a balance link of a booking
	that still owes stays open. Called under
	the booking's lock: a link a payment is being started for (locked by it: the order is link, then
	booking) is skipped, never waited for; that payment finds the booking as it is now (``link_refusal``).
	Each link is locked by its name (no gap or scan lock). → the links closed."""
	closed = []
	now = now_datetime()
	for name in frappe.get_all("TEX Payment Link", filters={"booking": booking,
	                                                        "status": ("in", ["Active", "Partially Paid"])},
	                           pluck="name", order_by="name asc"):
		row = frappe.db.sql("""SELECT status, property, expires_at FROM `tabTEX Payment Link` WHERE name=%s
		                       FOR UPDATE SKIP LOCKED""", name, as_dict=True)
		if not row or row[0].status not in ("Active", "Partially Paid"):
			continue
		status = "Expired" if row[0].expires_at and get_datetime(row[0].expires_at) <= now else "Cancelled"
		frappe.db.set_value("TEX Payment Link", name, "status", status, update_modified=False)
		audit("payment_link.closed", reference_doctype="TEX Payment Link", reference_name=name,
		      property=row[0].property, new={"booking": booking, "status": status, "was": row[0].status, "why": why})
		closed.append(name)
	return closed


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
	"""Scheduler: active links past their expiry become Expired (audited, G-74)."""
	n = 0
	# a link without an expiry time never expires, as ``link_by_token`` reads it (NEW-1, ADR-064)
	for name in frappe.get_all("TEX Payment Link", filters=[["status", "in", ["Active", "Partially Paid"]],
	                                                        ["expires_at", "is", "set"],
	                                                        ["expires_at", "<", now_datetime()]], pluck="name"):
		link = frappe.get_doc("TEX Payment Link", name)
		link.flags.tex_system_update = True
		before = link.status
		link.status = "Expired"
		link.save(ignore_permissions=True)
		audit("payment_link.expire", reference_doctype="TEX Payment Link", reference_name=name,
		      property=link.property, old={"status": before},
		      new={"status": "Expired", "expires_at": str(link.expires_at),
		           "paid_amount": to_str(from_db(link.paid_amount, link.currency)), "currency": link.currency})
		n += 1
	return n


def cancel_link(name: str, reason: str):
	"""→ until when its booking's rooms are still held (None: not held, or no booking; E3). The link is locked
	and read as it is now, before its booking (P1-4)."""
	link = frappe.get_doc("TEX Payment Link", name, for_update=True)
	scope.require("payment.link", link.property)
	if link.status not in ("Active", "Draft"):
		frappe.throw(_("Only active links can be cancelled."))
	link.status = "Cancelled"
	link.save(ignore_permissions=True)
	# the rooms it held for the guest are no longer held for it (D7)
	held = holds.after_link_closed(link.booking)
	audit("payment_link.cancel", reference_doctype="TEX Payment Link", reference_name=name, property=link.property,
	      reason=reason)
	return held
