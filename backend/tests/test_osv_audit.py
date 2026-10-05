"""
Tests for the dependency-audit helpers (scripts/osv_audit.py) and for the
osv-scanner allowlists they police.
"""

import importlib.util
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts import osv_audit

ALLOWLISTS = [Path("osv-scanner.toml"), Path("frontend/osv-scanner.toml")]

pytestmark = pytest.mark.unit


def _package(
    name: str, version: str, *groups: list[str], ecosystem: str = "PyPI", severity: str = "7.5"
) -> dict[str, Any]:
    return {
        "package": {"name": name, "version": version, "ecosystem": ecosystem},
        "groups": [{"ids": ids, "aliases": ids, "max_severity": severity} for ids in groups],
    }


def _report(*packages: dict[str, Any]) -> dict[str, Any]:
    return {
        "results": [
            {"source": {"path": "poetry.lock", "type": "lockfile"}, "packages": list(packages)}
        ]
    }


class TestNewFindings:
    def test_known_advisory_is_not_new_after_a_version_bump(self):
        base = osv_audit.load_findings(_report(_package("transformers", "4.57.1", ["GHSA-a"])))
        head = osv_audit.load_findings(_report(_package("transformers", "4.57.6", ["GHSA-a"])))
        assert osv_audit.new_findings(base, head) == []

    def test_matches_through_aliases(self):
        base = osv_audit.load_findings(_report(_package("torch", "2.10.0", ["PYSEC-1"])))
        head = osv_audit.load_findings(_report(_package("torch", "2.10.0", ["GHSA-b", "PYSEC-1"])))
        assert osv_audit.new_findings(base, head) == []

    def test_reports_an_advisory_the_change_adds(self):
        base = osv_audit.load_findings(_report(_package("pypdf", "6.16.1", ["GHSA-c"])))
        head = osv_audit.load_findings(
            _report(
                _package("pypdf", "6.16.1", ["GHSA-c"]), _package("langgraph", "1.0.2", ["GHSA-d"])
            )
        )
        added = osv_audit.new_findings(base, head)
        assert [(f.name, sorted(f.ids)) for f in added] == [("langgraph", ["GHSA-d"])]

    def test_same_advisory_on_another_package_is_new(self):
        base = osv_audit.load_findings(
            _report(_package("braces", "3.0.3", ["GHSA-e"], ecosystem="npm"))
        )
        head = osv_audit.load_findings(
            _report(_package("micromatch", "4.0.8", ["GHSA-e"], ecosystem="npm"))
        )
        assert len(osv_audit.new_findings(base, head)) == 1

    def test_pypi_names_are_normalised(self):
        base = osv_audit.load_findings(_report(_package("Typing_Extensions", "4.0", ["GHSA-f"])))
        head = osv_audit.load_findings(_report(_package("typing-extensions", "4.1", ["GHSA-f"])))
        assert osv_audit.new_findings(base, head) == []

    def test_falls_back_to_vulnerabilities_without_groups(self):
        report = _report(
            {
                "package": {"name": "x", "version": "1", "ecosystem": "PyPI"},
                "vulnerabilities": [{"id": "GHSA-g", "aliases": ["CVE-1"]}],
            }
        )
        (finding,) = osv_audit.load_findings(report)
        assert finding.ids == frozenset({"GHSA-g", "CVE-1"})

    def test_empty_reports(self):
        assert osv_audit.load_findings({}) == []
        assert osv_audit.load_findings({"results": None}) == []


class TestCommandLine:
    def _write(self, path: Path, report: dict[str, Any]) -> Path:
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    def test_new_exits_1_and_lists_added_advisories(self, tmp_path, capsys):
        base = self._write(tmp_path / "base.json", _report())
        head = self._write(
            tmp_path / "head.json", _report(_package("langgraph", "1.0.2", ["GHSA-d"]))
        )
        assert osv_audit.main(["new", str(base), str(head)]) == 1
        out = capsys.readouterr().out
        assert "langgraph (PyPI)" in out
        assert "GHSA-d" in out

    def test_new_exits_0_when_nothing_is_added(self, tmp_path, capsys):
        base = self._write(tmp_path / "base.json", _report(_package("torch", "2.10.0", ["GHSA-h"])))
        head = self._write(tmp_path / "head.json", _report())
        assert osv_audit.main(["new", str(base), str(head)]) == 0
        assert "No new advisories" in capsys.readouterr().out

    def test_new_treats_an_empty_file_as_a_clean_report(self, tmp_path):
        base = tmp_path / "base.json"
        base.write_text("", encoding="utf-8")
        head = self._write(tmp_path / "head.json", _report())
        assert osv_audit.main(["new", str(base), str(head)]) == 0

    def test_expiring_lists_entries_and_honours_exit_code(self, tmp_path, capsys):
        soon = (date.today() + timedelta(days=10)).isoformat()
        later = (date.today() + timedelta(days=80)).isoformat()
        config = tmp_path / "osv-scanner.toml"
        config.write_text(
            "[[IgnoredVulns]]\n"
            f'id = "GHSA-soon"\nignoreUntil = {soon}\nreason = "r #1"\n\n'
            "[[IgnoredVulns]]\n"
            f'id = "GHSA-later"\nignoreUntil = {later}\nreason = "r #2"\n',
            encoding="utf-8",
        )
        missing = tmp_path / "missing.toml"
        assert osv_audit.main(["expiring", "--within-days", "30", str(config), str(missing)]) == 0
        out = capsys.readouterr().out
        assert "GHSA-soon" in out
        assert "GHSA-later" not in out
        assert osv_audit.main(["expiring", "--exit-code", str(config)]) == 1
        assert osv_audit.main(["expiring", "--exit-code", "--within-days", "5", str(config)]) == 0

    def test_entry_without_ignore_until_is_always_listed(self, tmp_path):
        config = tmp_path / "osv-scanner.toml"
        config.write_text('[[IgnoredVulns]]\nid = "GHSA-open"\nreason = "r #1"\n', encoding="utf-8")
        (entry,) = osv_audit.expiring_entries([config], within_days=0)
        assert entry.id == "GHSA-open"
        assert entry.ignore_until is None


@pytest.mark.parametrize("config", ALLOWLISTS, ids=str)
def test_allowlist_entries_are_time_boxed_and_tracked(config):
    entries = osv_audit.load_allowlist(config)
    ids = [entry.id for entry in entries]
    assert len(ids) == len(set(ids)), f"duplicate entries in {config}"
    latest = date.today() + timedelta(days=90)
    for entry in entries:
        assert entry.ignore_until is not None, f"{entry.id}: ignoreUntil is required"
        assert entry.ignore_until <= latest, f"{entry.id}: ignoreUntil is more than 90 days out"
        assert re.search(r"#\d+", entry.reason), f"{entry.id}: the reason must name an issue"


# The reasons in osv-scanner.toml say the vulnerable transformers and torch
# features are unused. These checks keep that true.
_UNUSED_FEATURES = {
    "trust_remote_code=True": r"trust_remote_code\s*=\s*True",
    "custom generate code": r"custom_generate",
    "save_pretrained": r"\bsave_pretrained\b",
    "transformers Trainer": r"\bTrainer\b",
    "torch.jit.script": r"\bjit\.script\b",
    ".pt2 archive loading": r"\b(?:torch\.export\.load|load_pt2|\.pt2\b)",
}


@pytest.mark.parametrize("feature", sorted(_UNUSED_FEATURES))
def test_allowlisted_features_are_not_used(feature):
    pattern = re.compile(_UNUSED_FEATURES[feature])
    offenders = [
        f"{path}:{number}"
        for root in (Path("backend/app"), Path("scripts"))
        for path in sorted(root.rglob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if pattern.search(line)
    ]
    assert offenders == [], f"{feature} is used; re-check the osv-scanner.toml reasons"


def test_kernels_package_is_not_installed():
    # The transformers allowlist reasons rely on the `kernels` package being absent.
    assert importlib.util.find_spec("kernels") is None
