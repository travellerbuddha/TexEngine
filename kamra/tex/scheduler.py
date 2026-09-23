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


# Channel distribution (G-69): inbound bookings first, then ARI pushes.
EVERY_MINUTE = ("kamra.tex.distribution.repository.process_inbound",
                "kamra.tex.distribution.repository.deliver_ari")
# e-mail delivery status follows Frappe's e-mail queue (ADR-047)
EVERY_5_MINUTES = ("kamra.tex.connect.outbox.deliver_pending",
                   "kamra.tex.services.booking.expire_pending_bookings",
                   "kamra.tex.payments.service.expire_links",
                   "kamra.tex.services.mail_status.sync")
# system-status alerts run last, so they see this run's outcome (ADR-047)
EVERY_15_MINUTES = ("kamra.tex.commercial.contracts.roll_version_statuses",
                    "kamra.tex.crm.service.detect_abandoned",
                    # guest changes whose payment never came expire; queued refunds that did not run retry
                    "kamra.tex.services.guest_changes.expire_awaiting",
                    "kamra.tex.ops.alerts.evaluate")


def every_minute() -> None:
	for job in EVERY_MINUTE:
		_run(job)


def every_5_minutes() -> None:
	for job in EVERY_5_MINUTES:
		_run(job)


def every_15_minutes() -> None:
	for job in EVERY_15_MINUTES:
		_run(job)


def site_midnight() -> None:
	# allotment releases and cutoffs that start today reach the channels at once (G-49 review)
	_run("kamra.tex.distribution.repository.allotment_boundaries")


def fx_daily() -> None:
	_run("kamra.tex.connect.fx_providers.daily_fetch")


def daily() -> None:
	for job in ("kamra.tex.crm.loyalty.mature_and_expire", "kamra.tex.crm.service.purge_funnel",
	            "kamra.tex.crm.service.refresh_recent_checkouts", "kamra.tex.availability.extras_repository.reconcile_all",
	            "kamra.tex.services.sites.recheck_domains",
	            "kamra.tex.distribution.repository.daily_resync"):
		_run(job)
