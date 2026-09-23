"""TEX reports API (R-45, R-46)."""

from __future__ import annotations

import frappe

from kamra.tex.reports import service as rep


@frappe.whitelist()
def dashboard(property: str, date_from: str | None = None, date_to: str | None = None):
	return rep.dashboard(property, date_from, date_to)


@frappe.whitelist()
def production(property: str, date_from: str, date_to: str, group_by: str = "channel", basis: str = "stay",
               include_cancelled=0):
	return rep.production(property, date_from, date_to, group_by=group_by, basis=basis,
	                      include_cancelled=bool(int(include_cancelled or 0)))


@frappe.whitelist()
def pace(property: str, stay_from: str, stay_to: str):
	return rep.pace(property, stay_from, stay_to)


@frappe.whitelist()
def portfolio_scopes():
	"""Enterprises, groups and hotels the user may report on (R-47)."""
	from kamra.tex.reports import portfolio as pf

	return pf.scopes()


@frappe.whitelist()
def portfolio(level: str = "All", name: str | None = None, date_from: str | None = None,
              date_to: str | None = None):
	"""The sales dashboard of a portfolio: every hotel of the scope where the user holds
	``report.view`` (checked per hotel in the service)."""
	from kamra.tex.reports import portfolio as pf

	return pf.portfolio(level, name, date_from, date_to)
