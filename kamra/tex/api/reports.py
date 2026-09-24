"""TEX reports API (R-14, R-47, R-48; ADR-038, ADR-059).

Every endpoint declares its capability (``report.view``); the service narrows a scope to the
hotels where the viewer holds it, and computes cost and margin only with ``price.view_cost``
at every hotel of the report.
"""

from __future__ import annotations

from functools import wraps

import frappe
from frappe.utils import cint

from kamra.tex.reports import service as rep
from kamra.tex.security.scope import require_capability


def throttled(fn):
	"""Each user runs at most ``service.RATE_LIMIT`` reports a minute (G-46 review, M5)."""
	@wraps(fn)
	def wrapper(*args, **kwargs):
		rep.throttle()
		return fn(*args, **kwargs)

	return wrapper


@frappe.whitelist()
@require_capability("report.view")
def dashboard(property: str, date_from: str | None = None, date_to: str | None = None):
	return rep.dashboard(property, date_from, date_to)


@frappe.whitelist()
@require_capability("report.view")
@throttled
def production(property: str | None = None, date_from: str | None = None, date_to: str | None = None,
               group_by: str = "channel", basis: str = "stay", include_cancelled=0, level: str | None = None,
               name: str | None = None, stay_from: str | None = None, stay_to: str | None = None,
               sale_from: str | None = None, sale_to: str | None = None, market=None, channel=None, room_type=None,
               rate_plan=None, currency=None):
	"""Production. ``date_from`` / ``date_to`` (the former one-hotel form) are the stay or the
	sale window by ``basis``; ``stay_*`` and ``sale_*`` may be given together."""
	if date_from or date_to:
		if basis == "stay":
			stay_from, stay_to = stay_from or date_from, stay_to or date_to
		else:
			sale_from, sale_to = sale_from or date_from, sale_to or date_to
	return rep.report("production", property=property, level=level, name=name, group_by=group_by, basis=basis,
	                  stay_from=stay_from, stay_to=stay_to, sale_from=sale_from, sale_to=sale_to, market=market,
	                  channel=channel, room_type=room_type, rate_plan=rate_plan, currency=currency,
	                  include_cancelled=bool(cint(include_cancelled)))


@frappe.whitelist()
@require_capability("report.view")
@throttled
def report(view: str, property: str | None = None, level: str | None = None, name: str | None = None,
           group_by: str | None = None, basis: str | None = None, stay_from: str | None = None, stay_to: str | None = None,
           sale_from: str | None = None, sale_to: str | None = None, market=None, channel=None, room_type=None,
           rate_plan=None, currency=None, include_cancelled=0):
	"""One report view (production, margin, promotion, extras, cancellation, payment,
	conversion) of one hotel (``property``) or a scope (``level`` / ``name``)."""
	return rep.report(view, property=property, level=level, name=name, group_by=group_by, basis=basis,
	                  stay_from=stay_from, stay_to=stay_to, sale_from=sale_from, sale_to=sale_to, market=market,
	                  channel=channel, room_type=room_type, rate_plan=rate_plan, currency=currency,
	                  include_cancelled=bool(cint(include_cancelled)))


@frappe.whitelist()
@require_capability("report.view")
def filter_options(property: str | None = None, level: str | None = None, name: str | None = None):
	"""Room types and rate plans of the report's hotels (the scope the viewer may report on)."""
	return rep.filter_options(property, level, name)


@frappe.whitelist()
@require_capability("report.view")
def pace(property: str, stay_from: str, stay_to: str):
	return rep.pace(property, stay_from, stay_to)


@frappe.whitelist()
@require_capability("report.view", property_arg=None)
def portfolio_scopes():
	"""Enterprises, groups and hotels the user may report on (R-47)."""
	from kamra.tex.reports import portfolio as pf

	return pf.scopes()


@frappe.whitelist()
@require_capability("report.view", property_arg=None)
@throttled
def portfolio(level: str = "All", name: str | None = None, date_from: str | None = None,
              date_to: str | None = None):
	"""The sales dashboard of a portfolio: every hotel of the scope where the user holds
	``report.view`` (checked per hotel in the service)."""
	from kamra.tex.reports import portfolio as pf

	return pf.portfolio(level, name, date_from, date_to)
