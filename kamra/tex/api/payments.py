"""TEX Payments API (R-40, R-41).

``callback`` is the only guest-reachable endpoint here: gateways (or the guest's
browser coming back from a hosted page) land on it; the outcome is verified by the
provider adapter — signature / server-to-server re-query — never taken from the
browser. Everything else is staff-only and capability-checked per hotel.
"""

from __future__ import annotations

from urllib.parse import urlencode, urlparse

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from kamra.tex.api._util import as_int, text
from kamra.tex.money import from_db, to_str
from kamra.tex.payments import service as pay
from kamra.tex.payments.providers.base import ProviderError
from kamra.tex.security import scope
from kamra.tex.security.audit import log_exception
from kamra.tex.security.scope import require_capability

GATEWAYS = ("iyzico", "Sipay", "Virtual POS")


# ─── gateway callback ────────────────────────────────────────────────────


def _forward(url: str | None, **params) -> None:
	from kamra.tex.services import sites

	target = url or sites.platform_url("/book")
	sep = "&" if urlparse(target).query else "?"
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = target + sep + urlencode({k: v for k, v in params.items() if v})


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
@rate_limit(limit=60, seconds=60)
def callback(txn: str | None = None, **_ignored):
	"""Gateway return / notification. Idempotent: a replay returns the stored result."""
	import hmac

	name = text(txn or frappe.form_dict.get("txn"), 40)
	cb = str(frappe.form_dict.get("cb") or "")
	# the return URL we gave the gateway is signed: unknown or unsigned ids go nowhere
	if not name or not hmac.compare_digest(pay.callback_signature(name), cb):
		frappe.throw(_("Unknown payment."), frappe.DoesNotExistError)
	row = frappe.db.get_value("TEX Payment Transaction", name, ["name", "provider", "return_url", "booking"],
	                          as_dict=True)
	if not row or row.provider not in GATEWAYS:
		frappe.throw(_("Unknown payment."), frappe.DoesNotExistError)
	params = {k: v for k, v in frappe.form_dict.items() if k not in ("cmd", "txn", "cb")}
	req = getattr(frappe.local, "request", None)
	headers = {k: v for k, v in req.headers.items()} if req is not None else {}
	body = req.get_data(cache=True) if req is not None else b""
	try:
		out = pay.complete(row.name, params=params, headers=headers, body=body)
		status = out["status"]
	except ProviderError:
		# forged or garbled callback: the transaction stays as it was
		frappe.db.rollback()
		log_exception(f"TEX payment callback rejected {row.name}")
		status = "Unverified"
	except Exception:
		# gateway unreachable while re-querying: stays Pending, staff can re-verify
		frappe.db.rollback()
		log_exception(f"TEX payment callback error {row.name}")
		status = "Pending"
	# Sipay returns via GET, which Frappe does not auto-commit; the verified outcome must persist.
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- verified payment outcome must be durable before redirect
	_forward(row.return_url, payment=row.name, status=status.lower())


# ─── staff: transactions ─────────────────────────────────────────────────


def _txn_row(r) -> dict:
	return {**{k: r.get(k) for k in ("name", "property", "txn_type", "status", "method", "currency", "provider",
	                                  "provider_ref", "booking", "payment_link", "card_brand", "card_last4",
	                                  "error_code", "error_message", "reason", "parent_transaction", "actor")},
	        "amount": to_str(from_db(r.amount, r.currency)), "created": str(r.creation),
	        "completed_at": str(r.completed_at) if r.completed_at else None}


_TXN_FIELDS = ["name", "property", "txn_type", "status", "method", "amount", "currency", "provider",
               "provider_ref", "booking", "payment_link", "card_brand", "card_last4", "error_code",
               "error_message", "reason", "parent_transaction", "actor", "creation", "completed_at"]


@frappe.whitelist()
@require_capability("payment.view")
def transactions(property: str, booking: str | None = None, status: str | None = None, method: str | None = None,
                 date_from: str | None = None, date_to: str | None = None, limit=100, start=0):
	filters: dict = {"property": property}
	if booking:
		filters["booking"] = booking
	if status:
		filters["status"] = status
	if method:
		filters["method"] = method
	if date_from and date_to:
		filters["creation"] = ("between", [date_from, f"{date_to} 23:59:59"])
	rows = frappe.get_all("TEX Payment Transaction", filters=filters, fields=_TXN_FIELDS, order_by="creation desc",
	                      limit_start=as_int(start, 0, lo=0), limit_page_length=as_int(limit, 100, lo=1, hi=500))
	return [_txn_row(r) for r in rows]


@frappe.whitelist()
@require_capability("payment.view", property_arg=None, doc_arg=("name", "TEX Payment Transaction"))
def transaction(name: str):
	r = frappe.db.get_value("TEX Payment Transaction", name, _TXN_FIELDS, as_dict=True)
	allocations = frappe.get_all("TEX Payment Allocation", filters={"transaction": name},
	                             fields=["name", "allocation_type", "amount", "currency", "booking", "reason", "actor",
	                                     "creation"], order_by="creation asc")
	for a in allocations:
		a["amount"] = to_str(from_db(a["amount"], a["currency"]))
		a["creation"] = str(a["creation"])
	refunds = frappe.get_all("TEX Payment Transaction", filters={"parent_transaction": name}, fields=_TXN_FIELDS,
	                         order_by="creation asc")
	return {**_txn_row(r), "allocations": allocations, "refunds": [_txn_row(x) for x in refunds],
	        "unallocated": to_str(from_db(r.amount, r.currency) - pay.allocated_of(name) - pay.refunded_of(name))
	        if r.txn_type == "Charge" and r.status == "Succeeded" else "0",
	        "refundable": to_str(from_db(r.amount, r.currency) - pay.refunded_of(name))
	        if r.txn_type == "Charge" and r.status == "Succeeded" else "0"}


@frappe.whitelist(methods=["POST"])
@require_capability("payment.view", property_arg=None, doc_arg=("transaction", "TEX Payment Transaction"))
def reverify(transaction: str):
	"""Ask the gateway again for a Pending or Failed charge (iyzico / Sipay support a
	status query): a charge the gateway did capture is recovered, never lost."""
	row = frappe.db.get_value("TEX Payment Transaction", transaction, ["provider", "provider_ref", "status"],
	                          as_dict=True)
	if row.status not in ("Pending", "Failed") or row.provider not in ("iyzico", "Sipay"):
		frappe.throw(_("Only pending or failed iyzico / Sipay payments can be re-verified."))
	params = {"token": (row.provider_ref or "").split("|")[0]} if row.provider == "iyzico" else {}
	try:
		return pay.complete(transaction, params=params, allow_failed=True)
	except ProviderError as e:
		frappe.throw(_("The gateway did not confirm this payment: {0}").format(str(e)[:200]))


@frappe.whitelist(methods=["POST"])
@require_capability("payment.refund", property_arg=None, doc_arg=("transaction", "TEX Payment Transaction"))
def refund(transaction: str, amount, reason: str, idempotency_key: str, booking: str | None = None):
	return pay.refund(transaction, amount=amount, reason=text(reason, 500) or "", booking=booking,
	                  idempotency_key=text(idempotency_key, 140) or frappe.throw(_("Idempotency key required.")))


@frappe.whitelist(methods=["POST"])
@require_capability("payment.refund", property_arg=None, doc_arg=("transaction", "TEX Payment Transaction"))
def allocate(transaction: str, booking: str, amount, reason: str, idempotency_key: str | None = None):
	return {"allocation": pay.allocate(transaction, booking=booking, amount=amount, reason=text(reason, 300) or "",
	                                   idempotency_key=text(idempotency_key, 140))}


@frappe.whitelist(methods=["POST"])
@require_capability("payment.refund", property_arg=None, doc_arg=("transaction", "TEX Payment Transaction"))
def transfer(transaction: str, from_booking: str, to_booking: str, amount, reason: str,
             idempotency_key: str | None = None):
	if not text(reason, 300):
		frappe.throw(_("A reason is required."))
	return pay.transfer(transaction, from_booking=from_booking, to_booking=to_booking, amount=amount,
	                    reason=text(reason, 300), idempotency_key=text(idempotency_key, 140))


@frappe.whitelist(methods=["POST"])
@require_capability("payment.refund", property_arg=None, doc_arg=("transaction", "TEX Payment Transaction"))
def mark_transfer_received(transaction: str, reference: str):
	if not text(reference, 140):
		frappe.throw(_("The bank reference is required."))
	return pay.mark_transfer_received(transaction, reference=text(reference, 140))


@frappe.whitelist(methods=["POST"])
@require_capability("payment.refund", property_arg=None, doc_arg=("booking", "TEX Booking"))
def record_manual(booking: str, amount, method: str, reference: str, idempotency_key: str,
                  reason: str | None = None):
	return pay.record_manual(booking=booking, amount=amount, method=text(method, 40) or "Other",
	                         reference=text(reference, 140) or "", reason=text(reason, 300),
	                         idempotency_key=text(idempotency_key, 140) or frappe.throw(_("Idempotency key required.")))


@frappe.whitelist()
def methods(property: str, market: str | None = None, currency: str | None = None, channel: str | None = None):
	scope.require("payment.view", property)
	return pay.payment_methods(property, market=market, currency=currency, channel=channel)


# ─── staff: payment links ────────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
@require_capability("payment.link")
def create_link(property: str, amount, currency: str, description: str, expires_hours=72,
                provider_account: str | None = None, booking: str | None = None, reservation: str | None = None,
                guest_name: str | None = None, guest_email: str | None = None, idempotency_key: str | None = None,
                send_email=0, language: str | None = None):
	if provider_account and frappe.db.get_value("TEX Payment Provider Account", provider_account,
	                                            "property") not in (None, property):
		frappe.throw(_("That payment account belongs to another hotel."))
	return pay.create_link(property=property, amount=amount, currency=currency, description=text(description, 500),
	                       expires_hours=as_int(expires_hours, 72, lo=1, hi=24 * 60),
	                       provider_account=provider_account, booking=booking, reservation=reservation,
	                       guest_name=text(guest_name, 140), guest_email=text(guest_email, 140),
	                       idempotency_key=text(idempotency_key, 140), send_email=bool(as_int(send_email, 0)),
	                       language=text(language, 5) or "en")


@frappe.whitelist(methods=["POST"])
@require_capability("payment.link", property_arg=None, doc_arg=("name", "TEX Payment Link"))
def reissue_link(name: str, send_email=0, language: str | None = None):
	return pay.reissue_link(name, send_email=bool(as_int(send_email, 0)), language=text(language, 5) or "en")


@frappe.whitelist()
@require_capability("payment.view")
def links(property: str, status: str | None = None, booking: str | None = None, limit=100):
	filters: dict = {"property": property}
	if status:
		filters["status"] = status
	if booking:
		filters["booking"] = booking
	rows = frappe.get_all("TEX Payment Link", filters=filters,
	                      fields=["name", "status", "amount", "paid_amount", "currency", "description", "expires_at",
	                              "booking", "reservation", "guest_name", "guest_email", "public_url", "creation"],
	                      order_by="creation desc", limit_page_length=as_int(limit, 100, lo=1, hi=500))
	for r in rows:
		r["amount"] = to_str(from_db(r["amount"], r["currency"]))
		r["paid_amount"] = to_str(from_db(r["paid_amount"], r["currency"]))
		r["expires_at"] = str(r["expires_at"]) if r["expires_at"] else None
		r["creation"] = str(r["creation"])
	return rows


@frappe.whitelist(methods=["POST"])
@require_capability("payment.link", property_arg=None, doc_arg=("name", "TEX Payment Link"))
def cancel_link(name: str, reason: str):
	if not text(reason, 300):
		frappe.throw(_("A reason is required."))
	pay.cancel_link(name, text(reason, 300))
	return {"ok": True}


# ─── staff: provider accounts & method rules (secrets are write-only) ────

_ACCOUNT_FIELDS = ["name", "label", "property", "provider", "environment", "enabled", "currencies", "api_key",
                   "terminal_id", "bank_code", "gateway_url", "bank_name", "iban", "account_holder",
                   "transfer_instructions"]
_SECRETS = ("secret_key", "merchant_key", "store_key", "webhook_secret")


@frappe.whitelist()
@require_capability("settings.admin")
def accounts(property: str):
	rows = frappe.get_all("TEX Payment Provider Account", filters={"property": property}, fields=_ACCOUNT_FIELDS,
	                      order_by="label asc")
	for r in rows:
		doc = frappe.get_doc("TEX Payment Provider Account", r["name"])
		r["secrets_set"] = {f: bool(doc.get_password(f, raise_exception=False)) for f in _SECRETS}
		r["production_verified"] = False
	rules = frappe.get_all("TEX Payment Method Rule", filters={"property": property},
	                       fields=["name", "method", "provider_account", "market", "currency", "sales_channel",
	                               "priority", "disabled"], order_by="priority desc, method asc")
	return {"accounts": rows, "rules": rules}


@frappe.whitelist(methods=["POST"])
@require_capability("settings.admin")
def save_account(property: str, data):
	from kamra.tex.api._util import parse

	d = parse(data, {}) or {}
	name = d.get("name")
	if name:
		doc = frappe.get_doc("TEX Payment Provider Account", name)
		if doc.property != property:
			frappe.throw(_("That payment account belongs to another hotel."), frappe.PermissionError)
	else:
		doc = frappe.new_doc("TEX Payment Provider Account")
		doc.property = property
	for f in _ACCOUNT_FIELDS:
		if f in ("name", "property") or f not in d:
			continue
		doc.set(f, d[f])
	for f in _SECRETS:
		if d.get(f):          # blank = keep the stored secret
			doc.set(f, d[f])
	if doc.environment == "Production" and doc.provider == "Mock":
		frappe.throw(_("The mock provider can only be used in Sandbox."))
	doc.save(ignore_permissions=True)
	from kamra.tex.security.audit import audit

	audit("payment_account.save", reference_doctype="TEX Payment Provider Account", reference_name=doc.name,
	      property=property, new={"provider": doc.provider, "environment": doc.environment, "enabled": doc.enabled,
	                              "secrets_changed": [f for f in _SECRETS if d.get(f)]})
	return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
@require_capability("settings.admin")
def save_rule(property: str, data):
	from kamra.tex.api._util import parse

	d = parse(data, {}) or {}
	doc = frappe.get_doc("TEX Payment Method Rule", d["name"]) if d.get("name") else frappe.new_doc(
		"TEX Payment Method Rule")
	if d.get("name") and doc.property != property:
		frappe.throw(_("That rule belongs to another hotel."), frappe.PermissionError)
	doc.property = property
	for f in ("method", "provider_account", "market", "currency", "sales_channel"):
		if f in d:
			doc.set(f, d[f] or None)
	for f in ("priority", "disabled"):
		if f in d:
			doc.set(f, as_int(d[f], 0))
	if doc.provider_account and frappe.db.get_value("TEX Payment Provider Account", doc.provider_account,
	                                                "property") != property:
		frappe.throw(_("That payment account belongs to another hotel."))
	doc.save(ignore_permissions=True)
	return {"name": doc.name}
