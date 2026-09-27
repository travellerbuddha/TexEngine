"""Fail on a pip-audit finding the reviewed list does not name (NEW-5, supply-chain.yml).

    python pip_audit_gate.py <pip-audit JSON report> <pip-audit-ignore.txt>

A finding passes when its id or one of its aliases is in the list (``ID | package | reason | review
YYYY-MM-DD`` per line, ``#`` comments). Anything else fails the job with the package, version, id and fixed
releases. A listed entry past its review date, or no longer reported, is annotated (a warning / a notice), not
failed: the list is kept by review, not by the calendar. Standard library only."""

from __future__ import annotations

import datetime
import json
import sys


def ignores(path: str) -> dict[str, tuple[str, str, datetime.date | None]]:
	out = {}
	with open(path, encoding="utf-8") as f:
		for n, line in enumerate(f, 1):
			line = line.strip()
			if not line or line.startswith("#"):
				continue
			parts = [p.strip() for p in line.split("|")]
			if len(parts) != 4 or not parts[3].startswith("review "):
				raise SystemExit(f"{path}:{n}: expected 'ID | package version | reason | review YYYY-MM-DD'")
			review = datetime.date.fromisoformat(parts[3].removeprefix("review ").strip())
			out[parts[0]] = (parts[1], parts[2], review)
	return out


def main(report: str, ignore_file: str) -> int:
	with open(report, encoding="utf-8") as f:
		data = json.load(f)
	listed = ignores(ignore_file)
	used, new = set(), []
	for dep in data.get("dependencies", []):
		if dep.get("skip_reason"):
			print(f"not audited: {dep['name']}: {dep['skip_reason']}")
		for v in dep.get("vulns") or []:
			hit = ({v["id"], *v.get("aliases", [])}) & listed.keys()
			if hit:
				used |= hit
			else:
				fix = ", ".join(v.get("fix_versions") or []) or "none"
				new.append(f"{dep['name']} {dep.get('version')}: {v['id']} (aliases: {', '.join(v.get('aliases', [])) or '-'};"
				           f" fixed in: {fix})")
	today = datetime.date.today()
	for vid, (pkg, _reason, review) in sorted(listed.items()):
		if review and review < today:
			print(f"::warning::{vid} ({pkg}) was due for review on {review.isoformat()}")
		if vid not in used:
			print(f"::notice::{vid} ({pkg}) is no longer reported: remove it from {ignore_file}")
	if new:
		print(f"::error::{len(new)} Python dependency finding(s) not in {ignore_file}: upgrade, or review and list them")
		for line in new:
			print(line)
		return 1
	print(f"pip-audit: no new finding ({len(used)} reviewed finding(s) listed in {ignore_file})")
	return 0


if __name__ == "__main__":
	sys.exit(main(*sys.argv[1:3]))
