"""A refused market link is a funnel event (G-55b, ADR-056 / ADR-070).

TEX Funnel Event's ``event`` Select gets the option ``market_refused``: the booking engine reports a campaign link's
market the search refused (the refusal's code, the market, the link's country). Without the option the event would
fail validation, and ``_track`` drops a failed event silently. Nothing else changes."""

import frappe


def execute():
	frappe.reload_doc("tex_booking", "doctype", "tex_funnel_event")
