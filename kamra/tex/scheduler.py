"""TEX scheduled jobs (wired in kamra/hooks.py). Each job is isolated: one failing
job is logged and never stops the others."""

from __future__ import annotations

import frappe

from kamra.tex.security.audit import log_exception


def _run(path: str) -> None:
	try:
		frappe.get_attr(path)()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- scheduler job boundary
	except Exception:
		frappe.db.rollback()
		log_exception(f"TEX job {path}")


def every_5_minutes() -> None:
	for job in ("kamra.tex.connect.outbox.deliver_pending",
	            "kamra.tex.services.booking.expire_pending_bookings",
	            "kamra.tex.payments.service.expire_links"):
		_run(job)


def every_15_minutes() -> None:
	for job in ("kamra.tex.commercial.contracts.roll_version_statuses",
	            "kamra.tex.crm.service.detect_abandoned"):
		_run(job)


def fx_daily() -> None:
	_run("kamra.tex.connect.fx_providers.daily_fetch")


def daily() -> None:
	for job in ("kamra.tex.crm.loyalty.mature_and_expire", "kamra.tex.crm.service.purge_funnel",
	            "kamra.tex.crm.service.refresh_recent_checkouts", "kamra.tex.availability.extras_repository.reconcile_all"):
		_run(job)
