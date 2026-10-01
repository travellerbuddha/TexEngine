"""Turkish payment gateways: iyzico, Sipay, bank virtual POS (NestPay/Asseco).

All three use hosted payment pages / 3D forms, so card data never reaches TEX.
The request building and signing below follow the providers' public integration
documentation. They have NOT been certified against live gateways from this
codebase (``production_verified = False``): a merchant must run the provider's
sandbox certification with real sandbox credentials before enabling Production.
Outcomes are never taken from the browser: iyzico and Sipay are re-queried
server-to-server; NestPay callbacks are accepted only with a valid hash.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from decimal import Decimal

import requests

from kamra.tex.payments.providers.base import (
	Checkout,
	Intent,
	Outcome,
	PaymentProvider,
	ProviderError,
	gateway_time,
)

TIMEOUT = 20
ISO_NUMERIC = {"TRY": "949", "EUR": "978", "USD": "840", "GBP": "826"}
ISO_ALPHA = {v: k for k, v in ISO_NUMERIC.items()}


def _money(v: Decimal) -> str:
	return format(Decimal(v).quantize(Decimal("0.01")), "f")


def _stated(v) -> Decimal | None:
	"""An amount a gateway states, or None when it states none (or nothing readable)."""
	if v is None or str(v).strip() == "":
		return None
	try:
		return Decimal(str(v).strip())
	except ArithmeticError:
		return None


def _override(account) -> str:
	"""The account's gateway URL override (checked by ``account_problem``), or ""."""
	return (account.get("gateway_url") or "").strip()


# ─── iyzico ──────────────────────────────────────────────────────────────


def iyzico_auth_header(api_key: str, secret_key: str, uri_path: str, body: str, random_key: str) -> str:
	"""IYZWSv2: signature = HMAC-SHA256(secret, randomKey + uriPath + body) (hex);
	header = 'IYZWSv2 ' + base64('apiKey:{k}&randomKey:{r}&signature:{s}')."""
	signature = hmac.new(secret_key.encode(), (random_key + uri_path + body).encode(), hashlib.sha256).hexdigest()
	raw = f"apiKey:{api_key}&randomKey:{random_key}&signature:{signature}"
	return "IYZWSv2 " + base64.b64encode(raw.encode()).decode()


def iyzico_tokens(provider_ref: str | None) -> list[str]:
	"""The checkout-form tokens stored for a charge (a captured payment is "paymentId|itemId")."""
	return [t for t in str(provider_ref or "").split() if "|" not in t]


def iyzico_payment(provider_ref: str | None) -> str | None:
	"""The captured payment ("paymentId|paymentTransactionId") stored for a charge."""
	return next((t for t in str(provider_ref or "").split() if "|" in t), None)


class IyzicoProvider(PaymentProvider):
	name = "iyzico"
	reports_amount = True
	supports_refund = True
	status_query = True               # checkout-form DETAIL by the token TEX stored

	@staticmethod
	def status_params(provider_ref: str | None) -> list[dict]:
		# each checkout-form token stored for the charge; one without a token has nothing to ask
		return [{"token": t} for t in iyzico_tokens(provider_ref)]
	sandbox_hosts = ("sandbox-api.iyzipay.com",)
	INIT = "/payment/iyzipos/checkoutform/initialize/auth/ecom"
	DETAIL = "/payment/iyzipos/checkoutform/auth/ecom/detail"
	REFUND = "/payment/refund"

	@property
	def base(self) -> str:
		return _override(self.account) or (
			"https://sandbox-api.iyzipay.com" if self.sandbox else "https://api.iyzipay.com")

	def _post(self, path: str, payload: dict) -> dict:
		key, secret = self.secret("api_key"), self.secret("secret_key")        # both encrypted (G-83)
		if not key or not secret:
			raise ProviderError("iyzico API key / secret key are not configured")
		body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
		rnd = secrets.token_hex(8)
		headers = {"Authorization": iyzico_auth_header(key, secret, path, body, rnd), "x-iyzi-rnd": rnd,
		           "Content-Type": "application/json", "Accept": "application/json"}
		r = requests.post(self.base + path, data=body.encode(), headers=headers, timeout=TIMEOUT)
		r.raise_for_status()
		return r.json()

	def create_checkout(self, intent: Intent) -> Checkout:
		c = intent.customer
		names = (c.get("name") or "Guest").split(" ", 1)
		address = {"contactName": c.get("name") or "Guest", "city": c.get("city") or "-",
		           "country": c.get("country") or "Turkey", "address": c.get("address") or "-"}
		payload = {
			"locale": "tr" if intent.locale == "tr" else "en", "conversationId": intent.transaction,
			"price": _money(intent.amount), "paidPrice": _money(intent.amount), "currency": intent.currency,
			"basketId": intent.transaction, "paymentGroup": "PRODUCT", "callbackUrl": intent.callback_url,
			"buyer": {"id": c.get("id") or intent.transaction, "name": names[0], "surname": names[-1],
			          "email": c.get("email") or "noreply@example.com", "gsmNumber": c.get("phone") or "",
			          "identityNumber": c.get("identity_number") or "11111111111",
			          "registrationAddress": address["address"], "ip": c.get("ip") or "127.0.0.1",
			          "city": address["city"], "country": address["country"]},
			"shippingAddress": address, "billingAddress": address,
			"basketItems": [{"id": intent.transaction, "name": intent.description[:100], "category1": "Accommodation",
			                 "itemType": "VIRTUAL", "price": _money(intent.amount)}],
		}
		res = self._post(self.INIT, payload)
		if res.get("status") != "success":
			raise ProviderError(res.get("errorMessage") or "iyzico checkout initialisation failed")
		return Checkout(kind="redirect", url=res.get("paymentPageUrl"), provider_ref=res.get("token"))

	FINAL_FAILURE = ("FAILURE",)

	def can_add_checkout(self, provider_ref: str | None) -> bool:
		"""One checkout form per charge. Every form is its own payment at iyzico, so a second
		form on one charge could capture the money twice while TEX counts it once, and the
		page of a form cannot be shown again (TEX keeps its token, not its URL). Another tab
		therefore supersedes the charge: TEX starts a new one and still records the old
		one's payment should the guest complete it (G-68)."""
		return not iyzico_tokens(provider_ref)

	def handle_callback(self, transaction: str, params: dict, headers: dict, body: bytes, *,
	                    provider_ref: str | None = None) -> Outcome:
		token = params.get("token")
		# only a checkout-form token we stored for this charge is accepted
		issued = iyzico_tokens(provider_ref)
		if not token or not any(hmac.compare_digest(str(token), t) for t in issued):
			raise ProviderError("iyzico callback token does not match this payment")
		res = self._post(self.DETAIL, {"locale": "en", "conversationId": transaction, "token": token})
		if res.get("conversationId") not in (None, transaction):
			raise ProviderError("iyzico result belongs to another order")
		if res.get("status") != "success" or res.get("paymentStatus") != "SUCCESS":
			if res.get("paymentStatus") in self.FINAL_FAILURE:
				return Outcome(status="Failed", raw_status=res.get("paymentStatus"), error_code=res.get("errorCode"),
				               error_message=res.get("errorMessage"))
			# not final yet (or the query itself failed): leave the payment pending
			return Outcome(status="Pending", raw_status=res.get("paymentStatus") or res.get("status"))
		if res.get("basketId") not in (None, transaction):
			raise ProviderError("iyzico result belongs to another order")
		# iyzico's fraud check (O-18, D-8): only a payment with fraudStatus 1 may be served; 0 is under
		# review, -1 rejected (iyzico returns the money itself). Absent or anything else is read as a
		# review: never approved on doubt
		fraud = res.get("fraudStatus")
		fraud = "" if fraud is None else str(fraud).strip()
		if fraud == "-1":
			return Outcome(status="Failed", raw_status="FRAUD_REJECTED", error_code="FRAUD_REJECTED",
			               error_message="iyzico's fraud check rejected the payment")
		if fraud != "1":
			return Outcome(status="Pending", raw_status="FRAUD_REVIEW" if fraud == "0" else "FRAUD_UNKNOWN")
		items = res.get("itemTransactions") or [{}]
		ref = f"{res.get('paymentId')}|{items[0].get('paymentTransactionId') or ''}"
		# ``paidPrice`` includes the instalment interest a merchant may pass on to the guest;
		# ``price`` is the basket TEX asked for. Less paid than asked still never matches.
		price, paid = _stated(res.get("price")), _stated(res.get("paidPrice"))
		amount = price if price is not None else paid
		if price is not None and paid is not None and paid < price:
			amount = paid
		# no capture time: the checkout-form detail states none (``systemTime`` is its answer's time), so
		# its money is judged when its news arrives (ADR-062, D3)
		return Outcome(status="Succeeded", provider_ref=ref, amount=amount,
		               currency=res.get("currency"), card_brand=res.get("cardAssociation"),
		               card_last4=(res.get("lastFourDigits") or "")[-4:] or None, raw_status="SUCCESS")

	def refund(self, provider_ref: str, amount: Decimal, currency: str, *, reference: str | None = None) -> Outcome:
		_pid, _, item = (iyzico_payment(provider_ref) or "").partition("|")
		if not item:
			raise ProviderError("iyzico payment reference is missing")
		payload = {"locale": "en", "paymentTransactionId": item, "price": _money(amount), "currency": currency,
		           "ip": "127.0.0.1"}
		if reference:
			payload["conversationId"] = reference          # TEX's refund id, kept by iyzico with the refund
		# a timeout or a server error propagates: the outcome is unknown and TEX never repeats it
		res = self._post(self.REFUND, payload)
		if res.get("status") != "success":
			return Outcome(status="Failed", error_code=res.get("errorCode"), error_message=res.get("errorMessage"))
		return Outcome(status="Succeeded", provider_ref=str(res.get("paymentTransactionId") or item), amount=amount,
		               currency=currency, raw_status="REFUNDED")


# ─── Sipay (hosted "purchase/link" page) ─────────────────────────────────


def sipay_encrypt(data: str, app_secret: str) -> str:
	"""Sipay hash key: AES-256-CBC of the '|'-joined fields with key
	sha256(sha1(app_secret) + salt), encoded 'iv:salt:cipher' and '/'→'__'."""
	from cryptography.hazmat.primitives import padding
	from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

	data = data.encode()
	iv = hashlib.sha1(os.urandom(16)).hexdigest()[:16]
	password = hashlib.sha1(app_secret.encode()).hexdigest()
	salt = hashlib.sha1(os.urandom(16)).hexdigest()[:4]
	key = hashlib.sha256((password + salt).encode()).hexdigest()[:32]
	padder = padding.PKCS7(128).padder()
	enc = Cipher(algorithms.AES(key.encode()), modes.CBC(iv.encode())).encryptor()
	cipher = enc.update(padder.update(data) + padder.finalize()) + enc.finalize()
	return f"{iv}:{salt}:{base64.b64encode(cipher).decode()}".replace("/", "__")


def sipay_hash_key(total: str, installment: str, currency: str, merchant_key: str, invoice_id: str,
                   app_secret: str) -> str:
	"""Payment hash: 'total|installment|currency|merchant_key|invoice_id'."""
	return sipay_encrypt(f"{total}|{installment}|{currency}|{merchant_key}|{invoice_id}", app_secret)


def sipay_parse_hash_key(hash_key: str, app_secret: str) -> list[str]:
	from cryptography.hazmat.primitives import padding
	from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

	iv, salt, cipher = hash_key.replace("__", "/").split(":", 2)
	password = hashlib.sha1(app_secret.encode()).hexdigest()
	key = hashlib.sha256((password + salt).encode()).hexdigest()[:32]
	dec = Cipher(algorithms.AES(key.encode()), modes.CBC(iv.encode())).decryptor()
	padded = dec.update(base64.b64decode(cipher)) + dec.finalize()
	unpad = padding.PKCS7(128).unpadder()
	return (unpad.update(padded) + unpad.finalize()).decode().split("|")


class SipayProvider(PaymentProvider):
	name = "Sipay"
	# the field names of the check-status answer are taken from the public documentation and
	# not yet confirmed by a recorded sandbox response (certification, BLOCKED): a stated
	# ``amount`` must match, but a success without one is not refused until then
	reports_amount = False
	sandbox_hosts = ("provisioning.sipay.com.tr",)
	status_query = True               # checkstatus by TEX's own id of the charge

	@staticmethod
	def status_params(provider_ref: str | None) -> list[dict]:
		return [{}]                   # asked by the charge's own id: no parameter

	@property
	def base(self) -> str:
		return _override(self.account) or (
			"https://provisioning.sipay.com.tr/ccpayment" if self.sandbox else "https://app.sipay.com.tr/ccpayment")

	def _creds(self):
		app_id = self.secret("api_key")                                           # encrypted (G-83)
		app_secret = self.secret("secret_key")
		merchant_key = self.secret("merchant_key")
		if not (app_id and app_secret and merchant_key):
			raise ProviderError("Sipay app id / app secret / merchant key are not configured")
		return app_id, app_secret, merchant_key

	def _token(self) -> str:
		app_id, app_secret, _ = self._creds()
		r = requests.post(self.base + "/api/token", json={"app_id": app_id, "app_secret": app_secret},
		                  timeout=TIMEOUT)
		r.raise_for_status()
		data = r.json()
		if int(data.get("status_code") or 0) != 100:
			raise ProviderError(data.get("status_description") or "Sipay token request failed")
		return data["data"]["token"]

	def create_checkout(self, intent: Intent) -> Checkout:
		_app_id, _app_secret, merchant_key = self._creds()
		c = intent.customer
		names = (c.get("name") or "Guest").split(" ", 1)
		payload = {
			"merchant_key": merchant_key, "currency_code": intent.currency, "invoice": json.dumps({
				"invoice_id": intent.transaction, "invoice_description": intent.description[:100],
				# the guest's browser comes back to TEX's callback, which re-queries the
				# status server-to-server and then forwards to the booking page
				"total": float(_money(intent.amount)), "return_url": intent.callback_url,
				"cancel_url": intent.callback_url, "items": [{"name": intent.description[:100], "price":
				                                            float(_money(intent.amount)), "qnantity": 1,  # sic — Sipay's field name
				                                            "description": intent.description[:100]}],
				"bill_email": c.get("email"), "bill_phone": c.get("phone"), "bill_name": names[0],
				"bill_surname": names[-1]}),
			"name": names[0], "surname": names[-1],
		}
		r = requests.post(self.base + "/purchase/link", json=payload,
		                  headers={"Authorization": f"Bearer {self._token()}"}, timeout=TIMEOUT)
		r.raise_for_status()
		data = r.json()
		if int(data.get("status") or data.get("status_code") or 0) not in (100, True):
			raise ProviderError(data.get("message") or "Sipay link creation failed")
		return Checkout(kind="redirect", url=data.get("link"), provider_ref=intent.transaction)

	FINAL_FAILURE = ("failed", "declined", "cancelled", "canceled", "rejected")

	def handle_callback(self, transaction: str, params: dict, headers: dict, body: bytes, *,
	                    provider_ref: str | None = None) -> Outcome:
		_app_id, app_secret, merchant_key = self._creds()
		# check-status hash: 'invoice_id|merchant_key' (verify during sandbox certification;
		# a wrong hash fails closed — the transaction stays unpaid, never falsely paid)
		hash_key = sipay_encrypt(f"{transaction}|{merchant_key}", app_secret)
		r = requests.post(self.base + "/api/checkstatus",
		                  json={"merchant_key": merchant_key, "invoice_id": transaction, "hash_key": hash_key},
		                  headers={"Authorization": f"Bearer {self._token()}"}, timeout=TIMEOUT)
		r.raise_for_status()
		data = r.json()
		state = str(data.get("transaction_status") or "").lower()
		ok = int(data.get("status_code") or 0) == 100 and state == "completed"
		if not ok:
			if state in self.FINAL_FAILURE:
				return Outcome(status="Failed", raw_status=state, error_message=data.get("status_description"))
			# unknown / still processing: never fail a payment on an unconfirmed answer
			return Outcome(status="Pending", raw_status=state or str(data.get("status_code")))
		# no capture time: none of the check-status fields TEX reads is one (not certified yet), so its
		# money is judged when its news arrives (ADR-062, D3)
		return Outcome(status="Succeeded", provider_ref=str(data.get("order_no") or transaction),
		               amount=_stated(data.get("amount")), currency=data.get("currency_code"),
		               raw_status="completed")


# ─── Bank virtual POS: NestPay / Asseco 3D Pay Hosting ───────────────────


def nestpay_hash_v3(params: dict, store_key: str) -> str:
	"""Hash ver3: values of all parameters except hash/encoding, sorted by key
	(case-insensitive), '\\' and '|' escaped, joined with '|', + '|' + store key,
	SHA-512, base64."""
	def esc(v):
		return str(v).replace("\\", "\\\\").replace("|", "\\|")

	keys = sorted((k for k in params if k.lower() not in ("hash", "encoding")), key=str.lower)
	plain = "|".join(esc(params[k]) for k in keys) + "|" + esc(store_key)
	return base64.b64encode(hashlib.sha512(plain.encode("utf-8")).digest()).decode()


class NestPayProvider(PaymentProvider):
	name = "Virtual POS"
	reports_amount = True
	sandbox_hosts = ("entegrasyon.asseco-see.com.tr",)

	@property
	def gateway(self) -> str:
		return _override(self.account) or (
			"https://entegrasyon.asseco-see.com.tr/fim/est3Dgate" if self.sandbox else "")

	def create_checkout(self, intent: Intent) -> Checkout:
		if (self.account.get("bank_code") or "NestPay") != "NestPay":
			raise ProviderError(f"{self.account.get('bank_code')} virtual POS is not implemented yet")
		store_key = self.secret("store_key")
		if not (self.account.get("terminal_id") and store_key and self.gateway):
			raise ProviderError("NestPay client id, store key and gateway URL are required")
		fields = {
			"clientid": self.account.get("terminal_id"), "storetype": "3d_pay_hosting",
			"amount": _money(intent.amount), "currency": ISO_NUMERIC.get(intent.currency, ""),
			"oid": intent.transaction, "okUrl": intent.callback_url, "failUrl": intent.callback_url,
			# the bank's server-to-server callback (okUrl / failUrl: the guest's browser)
			"callbackUrl": intent.notify_url or intent.callback_url, "rnd": secrets.token_hex(10),
			"lang": "tr" if intent.locale == "tr" else "en", "TranType": "Auth", "hashAlgorithm": "ver3",
			"Instalment": "",
		}
		if not fields["currency"]:
			raise ProviderError(f"Currency {intent.currency} is not supported by the virtual POS")
		fields["hash"] = nestpay_hash_v3(fields, store_key)
		return Checkout(kind="form_post", url=self.gateway, fields=fields, provider_ref=intent.transaction)

	def handle_callback(self, transaction: str, params: dict, headers: dict, body: bytes, *,
	                    provider_ref: str | None = None) -> Outcome:
		store_key = self.secret("store_key")
		given = params.get("HASH") or params.get("hash") or ""
		check = {k: v for k, v in params.items() if k not in ("cmd",)}
		if not store_key or not hmac.compare_digest(nestpay_hash_v3(check, store_key), given):
			raise ProviderError("invalid virtual POS hash")
		if params.get("oid") != transaction:
			raise ProviderError("virtual POS result belongs to another order")
		approved = params.get("Response") == "Approved" and params.get("ProcReturnCode") == "00" \
			and str(params.get("mdStatus")) in ("1", "2", "3", "4")
		masked = params.get("MaskedPan") or ""
		numeric = str(params.get("currency") or "")
		return Outcome(status="Succeeded" if approved else "Failed", provider_ref=params.get("TransId"),
		               amount=_stated(params.get("amount")), raw_status=params.get("Response"),
		               # the bank's transaction time, in its Istanbul time and covered by the hash (D3)
		               captured_at=gateway_time(params.get("EXTRA.TRXDATE"), "%Y%m%d %H:%M:%S", "Europe/Istanbul")
		               if approved else None,
		               # a code TEX never sends stays as is, so it can never pass for the charge's currency
		               currency=ISO_ALPHA.get(numeric, numeric) or None,
		               card_last4=masked[-4:] if masked[-4:].isdigit() else None,
		               error_code=params.get("ProcReturnCode"), error_message=params.get("ErrMsg"))
