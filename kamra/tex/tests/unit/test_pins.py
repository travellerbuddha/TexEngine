"""2Z (ADR-073): CI, the supply-chain check and the local install paths build the same bench.

CI and the supply-chain check took payments' default branch (develop, which already declares Frappe v17) and the
newest frappe-bench, while the Dockerfile and setup-local.sh pinned one payments commit and bench 5.31.0: CI
equalled the image only while develop did not move. Semgrep's rules, its CLI and the registry pack were fetched
unpinned on every run, so a new upstream rule could turn the base red overnight (2026-09-30). Each pin is named
once per file here, and the files must agree; a pin changed in one file alone is red."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CI = ".github/workflows/ci.yml"
SUPPLY = ".github/workflows/supply-chain.yml"
LINTERS = ".github/workflows/linters.yml"
DOCKER = "deploy/tex-local/Dockerfile"
LOCAL = "deploy/tex-local/setup-local.sh"

FRAPPE_TAG = re.compile(r"(?:--frappe-branch\s+|FRAPPE_BRANCH=(?:\$\{TEX_FRAPPE_BRANCH:-)?)(v\d+\.\d+\.\d+)")
PAYMENTS_SHA = re.compile(r"PAYMENTS_REF(?:=|:\s*|=\$\{TEX_PAYMENTS_REF-)\"?([0-9a-f]{40})")
BENCH_CLI = re.compile(r"frappe-bench==([0-9.]+)|BENCH_VERSION=([0-9.]+)")
SHA = re.compile(r"^[0-9a-f]{40}$")


def read(path: str) -> str:
	return (ROOT / path).read_text(encoding="utf-8")


def found(pattern: re.Pattern, paths) -> dict[str, set[str]]:
	return {p: {g for m in pattern.findall(read(p)) for g in ((m,) if isinstance(m, str) else m) if g} for p in paths}


class TestPins(unittest.TestCase):
	def test_one_frappe_tag_everywhere(self):
		tags = found(FRAPPE_TAG, (CI, SUPPLY, DOCKER, LOCAL))
		for path, names in tags.items():
			self.assertTrue(names, f"{path} names no Frappe tag")
		self.assertEqual(len(set().union(*tags.values())), 1, tags)

	def test_one_payments_commit_everywhere(self):
		commits = found(PAYMENTS_SHA, (CI, SUPPLY, DOCKER, LOCAL))
		for path, names in commits.items():
			self.assertTrue(names, f"{path} pins no payments commit (PAYMENTS_REF)")
		self.assertEqual(len(set().union(*commits.values())), 1, commits)

	def test_one_bench_cli_everywhere(self):
		versions = found(BENCH_CLI, (CI, SUPPLY, DOCKER))
		for path, names in versions.items():
			self.assertTrue(names, f"{path} installs frappe-bench unpinned")
		self.assertEqual(len(set().union(*versions.values())), 1, versions)
		for path in (CI, SUPPLY):
			self.assertNotRegex(read(path), r"pip install frappe-bench\s*$|pip install frappe-bench\n", path)

	def test_semgrep_rules_and_cli_are_pinned(self):
		text = read(LINTERS)
		for name in ("FRAPPE_SEMGREP_RULES_REF", "SEMGREP_RULES_REF"):
			value = re.search(rf"{name}:\s*\"?([0-9a-f]+)", text)
			self.assertTrue(value and SHA.match(value.group(1)), f"{name} is not a full commit")
		self.assertRegex(text, r"SEMGREP_VERSION:\s*\"?\d+\.\d+\.\d+")
		self.assertIn('pip install "semgrep==$SEMGREP_VERSION"', text)
		self.assertNotRegex(text, r"--config\s+r/")                    # a registry pack, fetched unpinned
		self.assertNotIn("git clone --depth 1 https://github.com/frappe/semgrep-rules", text)


if __name__ == "__main__":
	unittest.main()
