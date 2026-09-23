"""Payments go-live check (ADR-041, G-67).

Lists every payment provider account that may no longer take new money (an uncertified
gateway in Production, the mock outside Sandbox, a gateway URL override that leaves the
provider's sandbox host, a sandbox gateway on a live site) with its open charges. Nothing is
changed: those charges still settle (a payment the gateway verifies is recorded, re-verified
or refunded) while new charges are refused until the account is fixed. Each account gets one
audit entry, so the list outlives the migration output; the payments setup screen shows the
same reason per account.
"""

from kamra.tex.payments.service import gated_accounts
from kamra.tex.security.audit import audit

FIELDS = ("label", "provider", "environment", "enabled", "problem", "open_charges", "open_charge_names")


def execute():
	for r in gated_accounts():
		audit("payment_account.gated", reference_doctype="TEX Payment Provider Account", reference_name=r["account"],
		      property=r["property"], new={k: r[k] for k in FIELDS}, source="System")
		print(f"TEX payments go-live: {r['label']} ({r['provider']}, {r['environment']}) of {r['property']} may not "
		      f"take new money ({r['problem']}); {r['open_charges']} open charge(s) still settle")
