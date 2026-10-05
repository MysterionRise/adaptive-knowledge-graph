"""
Dependency-audit helpers for CI.

Two subcommands:

``new BASE.json HEAD.json``
    Compare two osv-scanner JSON reports (``--format json``) and list the
    advisories HEAD has that BASE lacks. Exit status 1 when there are any. A
    head finding counts as known when the base report has the same package
    (ecosystem and normalised name) with an overlapping advisory ID or alias,
    so a version bump that keeps an existing advisory is not "new", while
    removing an allowlist entry without fixing the advisory is.

``expiring [--within-days N] [--exit-code] CONFIG...``
    List the ``[[IgnoredVulns]]`` entries of osv-scanner.toml files whose
    ``ignoreUntil`` date is missing, has passed or falls within the next N
    days (default 30). With ``--exit-code`` the exit status is 1 when any entry
    is listed; otherwise it is always 0.

Both print Markdown, suitable for a job summary or an issue body.
"""

import argparse
import json
import re
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Finding:
    """One advisory group reported for one package."""

    ecosystem: str
    name: str
    version: str
    ids: frozenset[str]
    max_severity: str

    @property
    def key(self) -> tuple[str, str]:
        return self.ecosystem.lower(), _normalise_name(self.ecosystem, self.name)


@dataclass(frozen=True)
class AllowlistEntry:
    """One ``[[IgnoredVulns]]`` entry of an osv-scanner.toml file."""

    config: Path
    id: str
    ignore_until: date | None
    reason: str


def _normalise_name(ecosystem: str, name: str) -> str:
    # PEP 503: PyPI names compare case-insensitively with runs of -, _ and . folded.
    if ecosystem.lower() == "pypi":
        return re.sub(r"[-_.]+", "-", name).lower()
    return name.lower()


def load_findings(report: dict[str, Any]) -> list[Finding]:
    """Flatten an osv-scanner JSON report into one finding per package and advisory group."""
    findings: list[Finding] = []
    for result in report.get("results") or []:
        for package_vulns in result.get("packages") or []:
            package = package_vulns.get("package") or {}
            groups = package_vulns.get("groups") or [
                {"ids": [vuln.get("id")], "aliases": vuln.get("aliases") or []}
                for vuln in package_vulns.get("vulnerabilities") or []
            ]
            for group in groups:
                ids = frozenset(
                    str(i) for i in [*(group.get("ids") or []), *(group.get("aliases") or [])] if i
                )
                if not ids:
                    continue
                findings.append(
                    Finding(
                        ecosystem=str(package.get("ecosystem", "")),
                        name=str(package.get("name", "")),
                        version=str(package.get("version", "")),
                        ids=ids,
                        max_severity=str(group.get("max_severity") or ""),
                    )
                )
    return findings


def new_findings(base: list[Finding], head: list[Finding]) -> list[Finding]:
    """Return the head findings that no base finding for the same package matches."""
    known: dict[tuple[str, str], set[str]] = {}
    for finding in base:
        known.setdefault(finding.key, set()).update(finding.ids)
    return [f for f in head if not (f.ids & known.get(f.key, set()))]


def load_allowlist(config: Path) -> list[AllowlistEntry]:
    """Read the ``[[IgnoredVulns]]`` entries of one osv-scanner.toml file."""
    data = tomllib.loads(config.read_text(encoding="utf-8"))
    entries = []
    for raw in data.get("IgnoredVulns") or []:
        until = raw.get("ignoreUntil")
        if isinstance(until, datetime):
            until = until.date()
        entries.append(
            AllowlistEntry(
                config=config,
                id=str(raw.get("id", "")),
                ignore_until=until if isinstance(until, date) else None,
                reason=str(raw.get("reason", "")),
            )
        )
    return entries


def expiring_entries(
    configs: Sequence[Path], within_days: int, today: date | None = None
) -> list[AllowlistEntry]:
    """Entries that have expired or expire within ``within_days`` of ``today``."""
    limit = (today or date.today()) + timedelta(days=within_days)
    return [
        entry
        for config in configs
        if config.exists()
        for entry in load_allowlist(config)
        if entry.ignore_until is None or entry.ignore_until <= limit
    ]


def _format_new(findings: list[Finding]) -> str:
    if not findings:
        return "No new advisories compared with the base branch.\n"
    lines = [
        f"{len(findings)} advisory group(s) not present on the base branch:",
        "",
        "| Package | Version | Advisories | Max severity |",
        "| --- | --- | --- | --- |",
    ]
    for f in sorted(findings, key=lambda f: (f.ecosystem, f.name, sorted(f.ids))):
        ids = ", ".join(sorted(f.ids))
        lines.append(
            f"| {f.name} ({f.ecosystem}) | {f.version} | {ids} | {f.max_severity or '?'} |"
        )
    lines += [
        "",
        "Upgrade the package, or add a time-boxed `[[IgnoredVulns]]` entry with a reason and "
        "an issue to the `osv-scanner.toml` next to the lockfile.",
    ]
    return "\n".join(lines) + "\n"


def _format_expiring(entries: list[AllowlistEntry], within_days: int) -> str:
    if not entries:
        return f"No allowlist entry expires within {within_days} days.\n"
    lines = [
        f"{len(entries)} allowlist entr{'y' if len(entries) == 1 else 'ies'} expired or "
        f"expiring within {within_days} days:",
        "",
        "| Advisory | Config | Ignored until | Reason |",
        "| --- | --- | --- | --- |",
    ]
    for e in sorted(entries, key=lambda e: (e.ignore_until or date.min, e.id)):
        until = e.ignore_until.isoformat() if e.ignore_until else "not set"
        lines.append(f"| {e.id} | `{e.config}` | {until} | {e.reason} |")
    return "\n".join(lines) + "\n"


def _read_report(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    report: dict[str, Any] = json.loads(text)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="list advisories HEAD adds compared with BASE")
    new.add_argument("base", type=Path, help="osv-scanner JSON report for the base")
    new.add_argument("head", type=Path, help="osv-scanner JSON report for the change")
    expiring = sub.add_parser("expiring", help="list allowlist entries that expire soon")
    expiring.add_argument("--within-days", type=int, default=30)
    expiring.add_argument(
        "--exit-code", action="store_true", help="exit with status 1 when any entry is listed"
    )
    expiring.add_argument("configs", type=Path, nargs="+", help="osv-scanner.toml files")
    args = parser.parse_args(argv)

    if args.command == "new":
        added = new_findings(
            load_findings(_read_report(args.base)), load_findings(_read_report(args.head))
        )
        sys.stdout.write(_format_new(added))
        return 1 if added else 0

    entries = expiring_entries(args.configs, args.within_days)
    sys.stdout.write(_format_expiring(entries, args.within_days))
    return 1 if entries and args.exit_code else 0


if __name__ == "__main__":
    sys.exit(main())
