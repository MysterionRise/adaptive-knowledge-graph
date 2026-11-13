"""
Offline release gate: is this tree ready to be tagged and published?

    python3 -I scripts/release_check.py                 # check the tree
    python3 -I scripts/release_check.py --tag v0.4.0    # and that the tag is its version
    make release-check TAG=v0.4.0

Standard library only, no network and no git, so it runs on a fresh checkout before
`poetry install` (Python >=3.11 for `tomllib`). The Release workflow runs it on the tag's tree
before it creates anything. Each check prints one `ok` or `FAIL` line, and every problem is
listed under its check with the file it is in. The exit code is 0 when every check passes and 1
otherwise; nothing is advisory. The default tree is the checkout the script is in, whatever the
working directory.

Checks:
- versions: pyproject.toml, frontend/package.json, the two root entries of
  frontend/package-lock.json and CITATION.cff carry the same MAJOR.MINOR.PATCH version; with
  --tag, the tag is exactly "v" plus that version (pre-release and build tags fail);
- changelog: CHANGELOG.md has exactly one "## [X.Y.Z] - YYYY-MM-DD" section, found the way the
  Release workflow's awk finds it, with a calendar date and a body, "## [Unreleased]" is still
  above it, the target of the "[X.Y.Z]: " link reference ends with the tag (".../vX.Y.Z", or a
  compare range that ends "...vX.Y.Z"), and CITATION.cff date-released is that date;
- placeholders: README.md and CHANGELOG.md contain no "<!-- FILL (" comment;
- evidence: docs/evals/latest.json passes the demo gate's rules (eval_report.report_errors and
  check_demo_eval.checkout_errors) and its byte-identical snapshot is in docs/evals/history/;
- assets: docs/assets/demo/ holds at least one non-empty image file.

What ties the evidence to the release is the app version the API reported (it must be the
pyproject version, so bump the version before the final-split run), the golden-set hash and
the snapshot's bytes. The commit recorded in the report is not compared with the tag or with
main: a report is committed after its run, and a squash merge leaves the commit of a release
branch unreachable from main. The check only requires the server and the harness to have run
the same commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.eval_report import report_errors  # noqa: E402
from scripts import check_demo_eval  # noqa: E402

PACKAGE_JSON = Path("frontend/package.json")
PACKAGE_LOCK = Path("frontend/package-lock.json")
CITATION = Path("CITATION.cff")
CHANGELOG = Path("CHANGELOG.md")
README = Path("README.md")
LATEST_REPORT = Path("docs/evals/latest.json")
HISTORY_DIR = Path("docs/evals/history")
DEMO_ASSETS = Path("docs/assets/demo")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")

VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
# The tag names the Release workflow accepts (its "Validate the tag name" step).
TAG_RE = re.compile(r"v(\d+\.\d+\.\d+)([-+][0-9A-Za-z.-]+)?")
# The Release workflow's awk: a line that opens or closes a fenced code block, and a link
# reference definition (left out of the release notes).
FENCE_RE = re.compile(r"\s*(```|~~~)")
LINK_REFERENCE_RE = re.compile(r"\[.*\]: ")
PLACEHOLDER_RE = re.compile(r"<!--\s*FILL\s*\(")

# What a passing check covered, printed on its `ok` line.
CHECKS = {
    "versions": "pyproject.toml, frontend/package.json, frontend/package-lock.json, CITATION.cff",
    "changelog": "CHANGELOG.md section, date and link reference; CITATION.cff date-released",
    "placeholders": "README.md and CHANGELOG.md",
    "evidence": "docs/evals/latest.json and its snapshot in docs/evals/history/",
    "assets": "docs/assets/demo/",
}


def _read_text(root: Path, relative: Path) -> str | None:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _truncate(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _pyproject() -> Path:
    """One definition of where the version lives, shared with the demo gate."""
    return check_demo_eval.PYPROJECT


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


def citation_field(text: str, name: str) -> str | None:
    """A top-level scalar of CITATION.cff, read without a YAML parser (None when absent).

    A repeated key yields its last value, as in the YAML parsers that accept one.
    """
    values = re.findall(rf"^{re.escape(name)}:[ \t]*(.*)$", text, re.MULTILINE)
    if not values:
        return None
    value = values[-1].split(" #")[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value or None


def _json_object(root: Path, relative: Path) -> dict[str, Any] | None:
    text = _read_text(root, relative)
    try:
        data = None if text is None else json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def read_versions(root: Path) -> tuple[dict[str, str], list[str]]:
    """Every place the version is written, as {where: version}, and what could not be read."""
    errors: list[str] = []
    found: dict[str, object] = {}

    pyproject = _pyproject()
    project_version = check_demo_eval.pyproject_version(root / pyproject)
    if project_version is None:
        errors.append(f"{pyproject}: no readable tool.poetry.version")
    else:
        found[str(pyproject)] = project_version

    package = _json_object(root, PACKAGE_JSON)
    if package is None:
        errors.append(f"{PACKAGE_JSON}: not found or not a JSON object")
    else:
        found[str(PACKAGE_JSON)] = package.get("version")

    lock = _json_object(root, PACKAGE_LOCK)
    if lock is None:
        errors.append(f"{PACKAGE_LOCK}: not found or not a JSON object")
    else:
        packages = lock.get("packages")
        root_package = packages.get("") if isinstance(packages, dict) else None
        found[f"{PACKAGE_LOCK} (version)"] = lock.get("version")
        found[f'{PACKAGE_LOCK} (packages[""].version)'] = (
            root_package.get("version") if isinstance(root_package, dict) else None
        )

    citation = _read_text(root, CITATION)
    if citation is None:
        errors.append(f"{CITATION}: not found or unreadable")
    else:
        found[str(CITATION)] = citation_field(citation, "version")

    versions = {where: value for where, value in found.items() if isinstance(value, str) and value}
    errors.extend(f"{where}: no version" for where in found if where not in versions)
    return versions, errors


def tag_errors(tag: str, version: str | None) -> list[str]:
    """Why ``tag`` is not the release tag of ``version`` (the pyproject version, if known)."""
    pyproject = _pyproject()
    match = TAG_RE.fullmatch(tag)
    if match is None:
        return [f"tag {tag!r} is not a release tag (expected vMAJOR.MINOR.PATCH)"]
    if match[2]:
        expected = f"v{version}" if version else "vMAJOR.MINOR.PATCH"
        return [
            f"tag {tag} is a pre-release or build tag: the release check accepts only "
            f"{expected}, the version in {pyproject}"
        ]
    if version is not None and match[1] != version:
        return [f"tag {tag} does not match the {pyproject} version {version} (expected v{version})"]
    return []


def check_versions(root: Path, tag: str | None = None) -> list[str]:
    """The version files agree with pyproject.toml and, when given, with the tag."""
    versions, errors = read_versions(root)
    pyproject = str(_pyproject())
    reference = versions.get(pyproject)
    if reference is not None:
        if not VERSION_RE.fullmatch(reference):
            errors.append(f"{pyproject}: version {reference} is not MAJOR.MINOR.PATCH")
        errors.extend(
            f"{where}: version {version} differs from the {pyproject} version {reference}"
            for where, version in versions.items()
            if version != reference
        )
    if tag is not None:
        errors.extend(tag_errors(tag, reference))
    return errors


# ---------------------------------------------------------------------------
# Changelog
# ---------------------------------------------------------------------------


def _changelog_lines(text: str) -> list[tuple[int, str, bool]]:
    """(line number, line, fenced) for every line, with the fence toggling of the awk.

    A fence delimiter counts as fenced: like any line inside a code block it can neither
    start nor end a section, and it is never dropped as a link reference.
    """
    lines: list[tuple[int, str, bool]] = []
    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE_RE.match(line):
            fenced = not fenced
            lines.append((number, line, True))
        else:
            lines.append((number, line, fenced))
    return lines


def _iso_date(value: str) -> date | None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def check_changelog(root: Path, version: str | None) -> list[str]:
    """CHANGELOG.md has the dated section of ``version``, and CITATION.cff has its date."""
    text = _read_text(root, CHANGELOG)
    if text is None:
        return [f"{CHANGELOG}: not found or unreadable"]
    if version is None:
        return [f"{CHANGELOG}: not checked, {_pyproject()} has no version to look for"]

    errors: list[str] = []
    lines = _changelog_lines(text)
    headings = [(n, line) for n, line, fenced in lines if not fenced and line.startswith("## ")]
    prefix = f"## [{version}]"
    expected = f'"{prefix} - YYYY-MM-DD"'
    sections = [(n, line) for n, line in headings if line.startswith(prefix)]
    released: date | None = None
    if not sections:
        errors.append(f"{CHANGELOG}: no {expected} section")
    else:
        if len(sections) > 1:
            numbers = ", ".join(str(n) for n, _ in sections)
            errors.append(
                f'{CHANGELOG}: {len(sections)} sections start with "{prefix}" '
                f"(lines {numbers}); expected exactly one"
            )
        # The Release workflow publishes the first one.
        number, heading = sections[0]
        dated = re.fullmatch(rf"{re.escape(prefix)} - (\S+)", heading.rstrip())
        if dated is None:
            errors.append(
                f'{CHANGELOG}:{number}: heading "{heading.strip()}" has no date '
                f"(expected {expected})"
            )
        else:
            released = _iso_date(dated[1])
            if released is None:
                errors.append(f"{CHANGELOG}:{number}: {dated[1]} is not a YYYY-MM-DD date")
        end = next((n for n, _ in headings if n > number), len(lines) + 1)
        body = [
            line
            for n, line, fenced in lines
            if number < n < end and (fenced or not LINK_REFERENCE_RE.match(line))
        ]
        if not any(line.strip() for line in body):
            errors.append(f"{CHANGELOG}:{number}: the [{version}] section is empty")

    unreleased = [n for n, line in headings if line.rstrip() == "## [Unreleased]"]
    if not unreleased:
        errors.append(f'{CHANGELOG}: no "## [Unreleased]" heading')
    elif sections and unreleased[0] > sections[0][0]:
        errors.append(
            f'{CHANGELOG}:{unreleased[0]}: "## [Unreleased]" must stay above "{prefix}" '
            f"(line {sections[0][0]})"
        )

    reference = f"[{version}]: "
    targets = [
        (n, line[len(reference) :].strip())
        for n, line, fenced in lines
        if not fenced and line.startswith(reference)
    ]
    if not targets:
        errors.append(f'{CHANGELOG}: no "{reference}<url>" link reference')
    # ".../releases/tag/vX.Y.Z" or ".../compare/vA.B.C...vX.Y.Z". A longer version (vX.Y.Z0),
    # a pre-release (vX.Y.Z-rc.1) and the [Unreleased] range (vX.Y.Z...HEAD) are other targets.
    ends_with_tag = re.compile(rf"(/|\.\.\.)v{re.escape(version)}$")
    errors.extend(
        f"{CHANGELOG}:{n}: the [{version}] link reference does not end with the tag "
        f"v{version}: {_truncate(target) or '(empty)'}"
        for n, target in targets
        if not ends_with_tag.search(target)
    )

    citation = _read_text(root, CITATION)
    date_released = None if citation is None else citation_field(citation, "date-released")
    if citation is None:
        errors.append(f"{CITATION}: not found or unreadable")
    elif date_released is None:
        errors.append(f"{CITATION}: no date-released")
    elif released is not None and date_released != released.isoformat():
        errors.append(
            f"{CITATION}: date-released {date_released} differs from the {CHANGELOG} date "
            f"{released.isoformat()} of [{version}]"
        )
    return errors


# ---------------------------------------------------------------------------
# Placeholders
# ---------------------------------------------------------------------------


def check_placeholders(root: Path) -> list[str]:
    """No "<!-- FILL (" comment is left in README.md or CHANGELOG.md."""
    errors: list[str] = []
    for relative in (README, CHANGELOG):
        text = _read_text(root, relative)
        if text is None:
            errors.append(f"{relative}: not found or unreadable")
            continue
        lines = text.splitlines()
        # One error per line, however many comments the line holds
        numbers = {
            text.count("\n", 0, match.start()) + 1 for match in PLACEHOLDER_RE.finditer(text)
        }
        errors.extend(
            f"{relative}:{number}: unfilled placeholder: {_truncate(lines[number - 1].strip())}"
            for number in sorted(numbers)
        )
    return errors


# ---------------------------------------------------------------------------
# Evaluation evidence
# ---------------------------------------------------------------------------


def snapshot_path(raw: bytes, generated_at: str) -> Path:
    """Where evaluate_rag.py saved the report: history/<date>-<first 12 hex of its sha256>.json.

    The same naming as ``evaluate_rag._history_path``, which this script cannot import (the
    harness needs third-party packages).
    """
    return HISTORY_DIR / f"{generated_at[:10]}-{hashlib.sha256(raw).hexdigest()[:12]}.json"


def snapshot_errors(root: Path, raw: bytes, generated_at: object) -> list[str]:
    """The report's snapshot exists in docs/evals/history/ with identical bytes."""
    if not isinstance(generated_at, str) or _iso_date(generated_at[:10]) is None:
        return [f"{LATEST_REPORT}: no generated_at date, so its history snapshot has no name"]
    relative = snapshot_path(raw, generated_at)
    try:
        snapshot = (root / relative).read_bytes()
    except OSError:
        return [
            f"{relative}: snapshot of {LATEST_REPORT} not found (the snapshot was not "
            "committed, or the report was edited after the run)"
        ]
    if snapshot != raw:
        return [f"{relative}: differs from {LATEST_REPORT} (the snapshot was altered)"]
    return []


def check_evidence(root: Path) -> list[str]:
    """docs/evals/latest.json is valid release evidence for this tree and has its snapshot."""
    try:
        raw = (root / LATEST_REPORT).read_bytes()
    except OSError:
        return [f"{LATEST_REPORT}: not found or unreadable"]
    try:
        report = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        return [f"{LATEST_REPORT}: invalid JSON ({error})"]
    if not isinstance(report, dict):
        return [f"{LATEST_REPORT}: not a JSON object"]
    try:
        reasons = [*report_errors(report), *check_demo_eval.checkout_errors(report, root)]
    except (ArithmeticError, AttributeError, LookupError, TypeError, ValueError) as error:
        # The shared rules expect the shape the harness writes and raise on another one
        reasons = [f"malformed report ({type(error).__name__}: {error})"]
    errors = [f"{LATEST_REPORT}: {reason}" for reason in reasons]
    # The snapshot is judged whatever the report says, so one run lists everything to fix
    errors.extend(snapshot_errors(root, raw, report.get("generated_at")))
    return errors


# ---------------------------------------------------------------------------
# Demo assets
# ---------------------------------------------------------------------------


def check_assets(root: Path) -> list[str]:
    """docs/assets/demo/ holds at least one non-empty image."""
    directory = root / DEMO_ASSETS
    entries = sorted(directory.iterdir()) if directory.is_dir() else []
    for entry in entries:
        if entry.suffix.lower() in IMAGE_SUFFIXES and entry.is_file() and entry.stat().st_size:
            return []
    return [f"{DEMO_ASSETS}: no image ({', '.join(IMAGE_SUFFIXES)})"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run_checks(root: Path, tag: str | None = None) -> dict[str, list[str]]:
    """Every check's errors, by check name, in the order they are reported."""
    version = check_demo_eval.pyproject_version(root / _pyproject())
    return {
        "versions": check_versions(root, tag),
        "changelog": check_changelog(root, version),
        "placeholders": check_placeholders(root),
        "evidence": check_evidence(root),
        "assets": check_assets(root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline release gate: versions, changelog, placeholders, evaluation "
        "evidence and demo assets. Exits 1 when any check fails."
    )
    parser.add_argument("--tag", help="release tag the versions must match, for example v0.4.0")
    parser.add_argument(
        "--root", type=Path, default=PROJECT_ROOT, help="tree to check (default: this checkout)"
    )
    args = parser.parse_args(argv)

    results = run_checks(args.root, args.tag)
    version = check_demo_eval.pyproject_version(args.root / _pyproject())
    for name, errors in results.items():
        if errors:
            print(f"FAIL  {name}")
            for error in errors:
                print(f"    {error}")
        elif name == "versions":
            print(f"ok    {name}: {version} in {CHECKS[name]}")
        else:
            print(f"ok    {name}: {CHECKS[name]}")
    failed = [name for name, errors in results.items() if errors]
    target = f" for {args.tag}" if args.tag else ""
    if failed:
        count = sum(len(errors) for errors in results.values())
        print(f"release-check{target}: FAILED, {count} problem(s) in {', '.join(failed)}")
        return 1
    print(f"release-check{target}: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
