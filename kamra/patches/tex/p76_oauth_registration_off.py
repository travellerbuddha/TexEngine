"""Frappe's OAuth provider registers no client for a guest on a TEX site (audit Part 2Z, ADR-073).

Frappe's OAuth Settings turn dynamic client registration on by default, and ``register_client`` is a guest
endpoint with no rate limit: anyone could create an OAuth Client with scope "all" and a redirect of their own,
and a staff member who clicked "Allow" on its authorize link would hand that client a bearer token. TEX uses no
Frappe OAuth client (its MCP login is its own, ``kamra.mcp_oauth``). New sites get it off at install; this patch
switches it off on a site installed before, once: an administrator who switches it on again for a reviewed
integration is not overruled by a forced re-run (G-76).

It deletes nothing. It prints how many OAuth Clients a guest registered, for review before go-live
(GO_LIVE_READINESS): the count only, never a name."""

import frappe

from kamra.tex.setup import close_oauth_registration, ran_before


def execute():
	if ran_before(__name__):
		return
	close_oauth_registration()
	if frappe.db.exists("DocType", "OAuth Client"):
		print(f"p76: {frappe.db.count('OAuth Client', {'owner': 'Guest'})} OAuth Client(s) registered by a guest "
		      "to review (Desk → OAuth Client)")
