"""Per-purpose signing secrets (G-89, ADR-041).

Offer keys, gateway return URLs and the sandbox payment page are signed with a secret
derived from the site's ``encryption_key``. There is no fallback: the site name is public,
so a signature keyed by it could be forged by anyone. A site without an encryption key
cannot sign and says so.
"""

from __future__ import annotations

import frappe
from frappe import _


class SigningKeyMissing(frappe.ValidationError):
	"""The site cannot sign: ``encryption_key`` is missing from its site_config."""


def site_secret(purpose: str) -> str:
	"""Secret key material for one purpose: ``"<purpose>:<encryption_key>"``.

	Each purpose ("tex-offer", "tex-callback", "tex-mock-pay") gets its own material, so a
	signature made for one purpose never verifies for another. The callers hash it or use
	it as an HMAC key exactly as before this module existed, so every offer, callback and
	sandbox signature issued with the site's key stays valid. It contains the site key:
	never log it, return it or put it in a URL."""
	key = frappe.local.conf.get("encryption_key")
	if not key:
		# the message names the purpose and the setting, never a secret or the site name
		message = _("TEX cannot sign {0}: this site has no encryption key. Set encryption_key in the site's "
		            "site_config.json.").format(purpose)
		if frappe.session.user == "Guest":
			# a guest is never told how the site is configured; staff find it in the error log
			frappe.log_error(title="TEX signing key missing", message=message)
			frappe.throw(_("This service is temporarily unavailable. Please try again later."), SigningKeyMissing)
		frappe.throw(message, SigningKeyMissing, title=_("Missing encryption key"))
	return f"{purpose}:{key}"
