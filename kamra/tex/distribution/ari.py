"""ARI change detection and run compression (G-69). Pure — no frappe import."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from kamra.tex.distribution.model import AriDay, AriRun


def changed(days: list[AriDay], pushed: dict) -> list[AriDay]:
	"""The days whose values differ from what the channel last accepted (``pushed``:
	date → fingerprint)."""
	return [d for d in days if pushed.get(d.day) != d.fingerprint()]


def runs(room_code: str, rate_code: str, days: list[AriDay]) -> list[AriRun]:
	"""Consecutive days with the same values, as ranges (days sorted, gaps split runs)."""
	out: list[AriRun] = []
	for d in sorted(days, key=lambda x: x.day):
		last = out[-1] if out else None
		if (last and last.date_to + timedelta(days=1) == d.day
				and last.values.fingerprint() == d.fingerprint()):
			out[-1] = replace(last, date_to=d.day)
		else:
			out.append(AriRun(room_code, rate_code, d.day, d.day, d))
	return out


def expand(run: AriRun) -> list[AriDay]:
	"""The days of a run (used to record what was accepted)."""
	n = (run.date_to - run.date_from).days
	return [replace(run.values, day=run.date_from + timedelta(days=i)) for i in range(n + 1)]
