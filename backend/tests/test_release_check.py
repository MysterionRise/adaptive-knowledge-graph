"""
Test the offline release gate (scripts/release_check.py) and its step in the Release
workflow. The Makefile target is covered in test_makefile.py.

Every check runs on a minimal passing tree under tmp_path, and each test then breaks one
thing. The committed evaluation evidence is never read: on a development tree it is allowed
to be stale, and only the release branch has to pass the evidence check.
"""

import copy
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from backend.tests.eval_report_builders import build_report
from scripts import check_demo_eval, evaluate_rag, release_check

pytestmark = pytest.mark.unit

VERSION = "1.2.3"
TAG = f"v{VERSION}"
RELEASED = "2026-03-04"
GOLDEN_SET = "version: 3\ncases: []\n"

CHANGELOG = f"""# Changelog

## [Unreleased]

## [{VERSION}] - {RELEASED}

### Added

- A feature.

## [1.2.2] - 2026-02-01

- An older release.

[Unreleased]: https://example.com/compare/{TAG}...HEAD
[{VERSION}]: https://example.com/releases/tag/{TAG}
[1.2.2]: https://example.com/releases/tag/v1.2.2
"""

CITATION = f"""cff-version: 1.2.0
title: "Fixture"
version: {VERSION}
date-released: {RELEASED}
"""

RELEASE_WORKFLOW = Path(".github/workflows/release.yml")
GATE_STEP = "Check the release tree (versions, changelog, evidence, assets)"
ON_MAIN_STEP = "Refuse tags whose commit is not on main"
NOTES_STEP = "Extract release notes from CHANGELOG.md"
CREATE_STEP = "Create the GitHub Release (or publish an existing draft)"

# Everything the script imports: with the files the checks read, a checkout of a release tag
CHECKOUT_FILES = (
    "scripts/__init__.py",
    "scripts/release_check.py",
    "scripts/check_demo_eval.py",
    "backend/app/__init__.py",
    "backend/app/core/__init__.py",
    "backend/app/core/eval_report.py",
)


def _write_evidence(tree: Path, report: dict[str, Any]) -> None:
    """Write latest.json and its snapshot, serialised and named as the harness does.

    Unlike ``evaluate_rag.write_reports`` it writes any report to latest.json, also one the
    harness would have written to latest-rehearsal.json or latest-retrieval.json.
    """
    out_dir = tree / "docs/evals"
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    snapshot = evaluate_rag._history_path(out_dir / "history", text, report["generated_at"])
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest.json").write_text(text, encoding="utf-8")
    snapshot.write_text(text, encoding="utf-8")


def _fixture_report() -> dict[str, Any]:
    """A valid full run by an API of the fixture version, on the fixture's golden set."""
    report = build_report()
    report["provenance"]["server"]["app_version"] = VERSION
    report["provenance"]["golden_set"] = {
        "path": "data/evals/golden_qa.yaml",
        "sha256": hashlib.sha256(GOLDEN_SET.encode()).hexdigest(),
    }
    return report


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A minimal tree that passes every check for v1.2.3."""
    root = tmp_path / "tree"
    for directory in ("frontend", "data/evals", "docs/assets/demo"):
        (root / directory).mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[tool.poetry]\nname = "fixture"\nversion = "{VERSION}"\n'
    )
    (root / "frontend/package.json").write_text(json.dumps({"name": "ui", "version": VERSION}))
    (root / "frontend/package-lock.json").write_text(
        json.dumps(
            {
                "name": "ui",
                "version": VERSION,
                "lockfileVersion": 3,
                "packages": {"": {"name": "ui", "version": VERSION}},
            }
        )
    )
    (root / "CITATION.cff").write_text(CITATION)
    (root / "CHANGELOG.md").write_text(CHANGELOG)
    (root / "README.md").write_text("# Fixture\n\nCitation hit rate: 0.9.\n")
    (root / "data/evals/golden_qa.yaml").write_text(GOLDEN_SET)
    (root / "docs/assets/demo/01-home.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    _write_evidence(root, _fixture_report())
    return root


@pytest.fixture
def checkout(tree: Path) -> Path:
    """The passing tree with the script and the modules it imports, as the tag's tree has them."""
    for relative in CHECKOUT_FILES:
        target = tree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(relative, target)
    return tree


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, f"{old!r} not in {path.name}"
    path.write_text(text.replace(old, new))


def _edit_json(path: Path, edit) -> None:
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))


def _snapshots(tree: Path) -> list[Path]:
    return sorted((tree / "docs/evals/history").glob("*.json"))


def _one(errors: list[str]) -> str:
    assert len(errors) == 1, errors
    return errors[0]


# ---------------------------------------------------------------------------
# The passing tree and the exit code
# ---------------------------------------------------------------------------


def test_passing_tree_exits_zero(tree, capsys):
    assert release_check.main(["--root", str(tree), "--tag", TAG]) == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out
    for name in ("versions", "changelog", "placeholders", "evidence", "assets"):
        assert f"ok    {name}: " in out
    assert f"ok    versions: {VERSION} in pyproject.toml" in out
    assert out.splitlines()[-1] == f"release-check for {TAG}: ok"


def test_passing_tree_needs_no_tag(tree, capsys):
    assert release_check.main(["--root", str(tree)]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "release-check: ok"


def test_every_check_has_an_ok_line(tree):
    assert list(release_check.run_checks(tree, TAG)) == list(release_check.CHECKS)


def test_main_exits_one_and_prints_every_error(tree, capsys):
    """Three checks fail, two of them twice: every problem is listed and counted, not just
    the first of each check."""
    _replace(tree / "CITATION.cff", f"version: {VERSION}", "version: 1.2.2")
    with (tree / "README.md").open("a") as readme:
        readme.write("<!-- FILL (hit rate) -->\n\n<!-- FILL (date) -->\n")
    (tree / "docs/assets/demo/01-home.png").unlink()

    assert release_check.main(["--root", str(tree), "--tag", "v9.9.9"]) == 1
    out = capsys.readouterr().out
    assert (
        "FAIL  versions\n"
        "    CITATION.cff: version 1.2.2 differs from the pyproject.toml version 1.2.3\n"
        "    tag v9.9.9 does not match the pyproject.toml version 1.2.3 (expected v1.2.3)\n"
    ) in out
    assert (
        "FAIL  placeholders\n"
        "    README.md:4: unfilled placeholder: <!-- FILL (hit rate) -->\n"
        "    README.md:6: unfilled placeholder: <!-- FILL (date) -->\n"
    ) in out
    assert "FAIL  assets\n    docs/assets/demo: no image" in out
    assert "ok    changelog: " in out
    assert "ok    evidence: " in out
    last = out.splitlines()[-1]
    assert last == (
        "release-check for v9.9.9: FAILED, 5 problem(s) in versions, placeholders, assets"
    )


@pytest.mark.parametrize(
    ("check", "break_tree"),
    [
        ("versions", lambda t: (t / "frontend/package.json").unlink()),
        ("changelog", lambda t: _replace(t / "CHANGELOG.md", f" - {RELEASED}", "")),
        (
            "placeholders",
            lambda t: (t / "CHANGELOG.md").write_text(CHANGELOG + "<!-- FILL (x) -->"),
        ),
        ("evidence", lambda t: _snapshots(t)[0].unlink()),
        ("assets", lambda t: (t / "docs/assets/demo/01-home.png").unlink()),
    ],
)
def test_one_failing_check_is_enough_to_exit_one(tree, capsys, check, break_tree):
    break_tree(tree)
    assert release_check.main(["--root", str(tree), "--tag", TAG]) == 1
    out = capsys.readouterr().out
    assert f"FAIL  {check}\n" in out
    assert out.count("FAIL  ") == 1


def test_a_missing_tree_fails_every_check_without_a_traceback(tmp_path, capsys):
    assert release_check.main(["--root", str(tmp_path / "missing"), "--tag", TAG]) == 1
    out = capsys.readouterr().out
    assert out.count("FAIL  ") == len(release_check.CHECKS)
    assert "ok    " not in out


def test_checks_read_only_the_tree_and_never_write_to_it(tree, tmp_path, monkeypatch):
    def files() -> dict[Path, bytes]:
        return {path: path.read_bytes() for path in sorted(tree.rglob("*")) if path.is_file()}

    before = files()
    monkeypatch.chdir(tmp_path)  # the fixture's files exist only under the tree
    assert release_check.main(["--root", str(tree), "--tag", TAG]) == 0
    assert files() == before


@pytest.mark.parametrize("isolation", [["-I"], ["-I", "-S"]], ids=["isolated", "no-site-packages"])
def test_script_runs_isolated_with_the_standard_library_only(tree, isolation):
    """`python3 -I` from a fresh checkout; -S also hides every installed package."""
    command = [sys.executable, *isolation, "scripts/release_check.py", "--root", str(tree)]
    passing = subprocess.run([*command, "--tag", TAG], capture_output=True, text=True)
    assert passing.returncode == 0, passing.stdout + passing.stderr
    failing = subprocess.run([*command, "--tag", "v9.9.9"], capture_output=True, text=True)
    assert failing.returncode == 1, failing.stdout + failing.stderr
    assert "FAIL  versions" in failing.stdout


def test_script_checks_its_own_checkout_whatever_the_working_directory(checkout, tmp_path):
    """No --root: the default tree is the one the script is in, as on the release runner."""
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(checkout / "scripts/release_check.py"), "--tag", TAG],
        cwd=tmp_path,  # holds none of the files the checks read
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[-1] == f"release-check for {TAG}: ok"


# ---------------------------------------------------------------------------
# Versions and the tag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tag", ["v1.2.4", "v1.2.2", "v1.2.30", "v1.2.03", "v11.2.3"])
def test_fails_on_tag_mismatch(tree, tag):
    error = _one(release_check.check_versions(tree, tag))
    assert error == f"tag {tag} does not match the pyproject.toml version 1.2.3 (expected v1.2.3)"
    assert release_check.check_versions(tree, TAG) == []
    assert release_check.check_versions(tree) == []


@pytest.mark.parametrize("tag", ["v1.2.3-rc.1", "v1.2.3-rc1", "v1.2.3+build.7"])
def test_fails_on_prerelease_tag(tree, tag):
    error = _one(release_check.check_versions(tree, tag))
    assert f"tag {tag} is a pre-release or build tag" in error
    assert "accepts only v1.2.3, the version in pyproject.toml" in error


@pytest.mark.parametrize(
    "tag", ["1.2.3", "V1.2.3", "v1.2", "v1.2.3.0", "v1.2.3rc1", "release-1.2.3", "v1.2.3 ", "v", ""]
)
def test_fails_on_a_tag_that_is_not_a_release_tag(tree, tag):
    error = _one(release_check.check_versions(tree, tag))
    assert f"tag {tag!r} is not a release tag" in error


@pytest.mark.parametrize(
    ("where", "break_tree"),
    [
        (
            "frontend/package.json: version 1.2.2",
            lambda t: _edit_json(t / "frontend/package.json", lambda d: d.update(version="1.2.2")),
        ),
        (
            "frontend/package-lock.json (version): version 1.2.2",
            lambda t: _edit_json(
                t / "frontend/package-lock.json", lambda d: d.update(version="1.2.2")
            ),
        ),
        (
            'frontend/package-lock.json (packages[""].version): version 1.2.2',
            lambda t: _edit_json(
                t / "frontend/package-lock.json",
                lambda d: d["packages"][""].update(version="1.2.2"),
            ),
        ),
        (
            "CITATION.cff: version 1.2.2",
            lambda t: _replace(t / "CITATION.cff", f"version: {VERSION}", 'version: "1.2.2"'),
        ),
    ],
)
def test_fails_on_version_disagreement(tree, where, break_tree):
    break_tree(tree)
    error = _one(release_check.check_versions(tree, TAG))
    assert error == f"{where} differs from the pyproject.toml version 1.2.3"


def test_a_stale_pyproject_version_fails_against_the_tag_and_every_other_file(tree):
    _replace(tree / "pyproject.toml", VERSION, "1.2.2")
    errors = release_check.check_versions(tree, TAG)
    assert len(errors) == 5, errors
    assert sum("differs from the pyproject.toml version 1.2.2" in e for e in errors) == 4
    assert "tag v1.2.3 does not match the pyproject.toml version 1.2.2 (expected v1.2.2)" in errors


@pytest.mark.parametrize(
    ("message", "break_tree"),
    [
        (
            "pyproject.toml: no readable tool.poetry.version",
            lambda t: (t / "pyproject.toml").write_text('[tool.poetry]\nname = "fixture"\n'),
        ),
        (
            "pyproject.toml: no readable tool.poetry.version",
            lambda t: (t / "pyproject.toml").write_text("not toml ["),
        ),
        (
            "pyproject.toml: version 1.2.3rc1 is not MAJOR.MINOR.PATCH",
            lambda t: _replace(t / "pyproject.toml", VERSION, "1.2.3rc1"),
        ),
        (
            "frontend/package.json: not found or not a JSON object",
            lambda t: (t / "frontend/package.json").write_text("{"),
        ),
        (
            "frontend/package-lock.json: not found or not a JSON object",
            lambda t: (t / "frontend/package-lock.json").unlink(),
        ),
        (
            "frontend/package-lock.json: not found or not a JSON object",
            lambda t: (t / "frontend/package-lock.json").write_text("[]"),
        ),
        (
            "frontend/package.json: no version",
            lambda t: _edit_json(t / "frontend/package.json", lambda d: d.update(version=3)),
        ),
        (
            'frontend/package-lock.json (packages[""].version): no version',
            lambda t: _edit_json(t / "frontend/package-lock.json", lambda d: d.pop("packages")),
        ),
        ("CITATION.cff: not found or unreadable", lambda t: (t / "CITATION.cff").unlink()),
        (
            "CITATION.cff: no version",
            lambda t: _replace(t / "CITATION.cff", f"version: {VERSION}\n", ""),
        ),
    ],
)
def test_fails_on_an_unreadable_version(tree, message, break_tree):
    break_tree(tree)
    assert message in release_check.check_versions(tree)


def test_citation_fields_are_top_level_scalars_only():
    text = (
        "cff-version: 1.2.0\n"
        "references:\n"
        "  - version: 9.9.9\n"
        "    date-released: 2000-01-01\n"
        "version: '1.2.3'  # the release\n"
        'date-released: "2026-03-04"\n'
    )
    assert release_check.citation_field(text, "version") == "1.2.3"
    assert release_check.citation_field(text, "date-released") == "2026-03-04"
    assert release_check.citation_field(text, "doi") is None
    assert release_check.citation_field("version:\n", "version") is None


def test_a_repeated_citation_key_reads_as_a_yaml_parser_reads_it():
    """PyYAML keeps the last value of a repeated key, so a stale second one is not missed."""
    text = "cff-version: 1.2.0\nversion: 1.2.3\nversion: 1.2.2\n"
    assert release_check.citation_field(text, "version") == yaml.safe_load(text)["version"]
    assert release_check.citation_field(text, "version") == "1.2.2"


def test_repository_versions_agree():
    """pyproject.toml, the frontend package files and CITATION.cff name one version today."""
    assert release_check.check_versions(Path(".")) == []
    versions, errors = release_check.read_versions(Path("."))
    assert errors == []
    assert len(versions) == 5
    assert len(set(versions.values())) == 1


def test_repository_citation_fields_match_a_yaml_parser():
    """The flat reader and PyYAML agree on the committed CITATION.cff."""
    text = Path("CITATION.cff").read_text()
    parsed = yaml.safe_load(text)
    assert release_check.citation_field(text, "version") == str(parsed["version"])
    assert release_check.citation_field(text, "date-released") == str(parsed["date-released"])


# ---------------------------------------------------------------------------
# Changelog
# ---------------------------------------------------------------------------


def test_fails_on_missing_changelog_section(tree):
    _replace(tree / "CHANGELOG.md", f"## [{VERSION}] - {RELEASED}\n", "")
    errors = release_check.check_changelog(tree, VERSION)
    assert errors == ['CHANGELOG.md: no "## [1.2.3] - YYYY-MM-DD" section']


@pytest.mark.parametrize(
    "heading",
    [
        f" ## [{VERSION}] - {RELEASED}",
        f"### [{VERSION}] - {RELEASED}",
        f"# [{VERSION}] - {RELEASED}",
        f"##[{VERSION}] - {RELEASED}",
        f"## {VERSION} - {RELEASED}",
    ],
    ids=["indented", "level-3", "level-1", "no-space", "no-brackets"],
)
def test_changelog_heading_is_anchored_like_the_release_workflow_awk(tree, heading):
    """The awk matches `## [X.Y.Z]` at the start of a line; anything else gets generated notes."""
    _replace(tree / "CHANGELOG.md", f"## [{VERSION}] - {RELEASED}", heading)
    errors = release_check.check_changelog(tree, VERSION)
    assert errors == ['CHANGELOG.md: no "## [1.2.3] - YYYY-MM-DD" section']


@pytest.mark.parametrize("other", ["1.2.3-rc.1", "1.2.30", "11.2.3", "1x2y3"])
def test_section_of_another_version_is_not_the_section(tree, other):
    _replace(tree / "CHANGELOG.md", f"## [{VERSION}] - {RELEASED}", f"## [{other}] - {RELEASED}")
    errors = release_check.check_changelog(tree, VERSION)
    assert errors == ['CHANGELOG.md: no "## [1.2.3] - YYYY-MM-DD" section']


def test_fails_on_undated_changelog_section(tree):
    _replace(tree / "CHANGELOG.md", f"## [{VERSION}] - {RELEASED}", f"## [{VERSION}]")
    error = _one(release_check.check_changelog(tree, VERSION))
    assert error == (
        'CHANGELOG.md:5: heading "## [1.2.3]" has no date (expected "## [1.2.3] - YYYY-MM-DD")'
    )


@pytest.mark.parametrize("written", ["2026-02-30", "TBD", "04-03-2026", "20260304", "2026-3-4"])
def test_fails_on_a_changelog_date_that_is_not_a_calendar_date(tree, written):
    _replace(tree / "CHANGELOG.md", f"## [{VERSION}] - {RELEASED}", f"## [{VERSION}] - {written}")
    error = _one(release_check.check_changelog(tree, VERSION))
    assert error == f"CHANGELOG.md:5: {written} is not a YYYY-MM-DD date"


def test_fails_on_text_after_the_changelog_date(tree):
    _replace(tree / "CHANGELOG.md", f"- {RELEASED}\n", f"- {RELEASED} (draft)\n")
    assert "has no date" in _one(release_check.check_changelog(tree, VERSION))


def test_fails_on_duplicate_changelog_sections(tree):
    _replace(
        tree / "CHANGELOG.md",
        "## [1.2.2] - 2026-02-01",
        f"## [{VERSION}] - {RELEASED}\n\n- Again.\n\n## [1.2.2] - 2026-02-01",
    )
    error = _one(release_check.check_changelog(tree, VERSION))
    assert error == (
        'CHANGELOG.md: 2 sections start with "## [1.2.3]" (lines 5, 11); expected exactly one'
    )


@pytest.mark.parametrize(
    "body",
    ["\n", "\n   \n\n", f"\n[{VERSION}]: https://example.com/releases/tag/{TAG}\n\n"],
    ids=["blank", "whitespace", "link-reference-only"],
)
def test_fails_on_empty_changelog_section(tree, body):
    """The Release workflow drops link references, so they are not a body."""
    _replace(tree / "CHANGELOG.md", "\n### Added\n\n- A feature.\n\n", body)
    errors = release_check.check_changelog(tree, VERSION)
    assert "CHANGELOG.md:5: the [1.2.3] section is empty" in errors


def test_fails_on_missing_link_reference(tree):
    _replace(tree / "CHANGELOG.md", f"[{VERSION}]: https://example.com/releases/tag/{TAG}\n", "")
    error = _one(release_check.check_changelog(tree, VERSION))
    assert error == 'CHANGELOG.md: no "[1.2.3]: <url>" link reference'


@pytest.mark.parametrize(
    "target",
    [
        "https://example.com/releases/tag/v1.2.2",
        "https://example.com/releases/tag/v1.2.30",
        "https://example.com/releases/tag/v1.2.3-rc.1",
        "https://example.com/compare/v1.2.3...HEAD",
        "https://example.com/releases/tag/1.2.3",
        "v1.2.3",
        "",
    ],
    ids=["previous", "longer", "pre-release", "unreleased-range", "no-v", "no-url", "empty"],
)
def test_fails_on_link_reference_that_does_not_end_with_the_tag(tree, target):
    """The usual slips: the line was copied from the previous release or from [Unreleased]."""
    _replace(
        tree / "CHANGELOG.md",
        f"[{VERSION}]: https://example.com/releases/tag/{TAG}\n",
        f"[{VERSION}]: {target}\n",
    )
    error = _one(release_check.check_changelog(tree, VERSION))
    assert error == (
        "CHANGELOG.md:16: the [1.2.3] link reference does not end with the tag v1.2.3: "
        f"{target or '(empty)'}"
    )


def test_a_compare_range_that_ends_with_the_tag_is_a_link_reference(tree):
    _replace(tree / "CHANGELOG.md", f"releases/tag/{TAG}\n", f"compare/v1.2.2...{TAG}\n")
    assert release_check.check_changelog(tree, VERSION) == []


def test_fails_when_unreleased_is_missing_or_below_the_release(tree):
    changelog = tree / "CHANGELOG.md"
    _replace(changelog, "## [Unreleased]\n\n", "")
    assert release_check.check_changelog(tree, VERSION) == [
        'CHANGELOG.md: no "## [Unreleased]" heading'
    ]

    _replace(changelog, "## [1.2.2] - 2026-02-01", "## [Unreleased]\n\n## [1.2.2] - 2026-02-01")
    assert release_check.check_changelog(tree, VERSION) == [
        'CHANGELOG.md:9: "## [Unreleased]" must stay above "## [1.2.3]" (line 3)'
    ]


def test_headings_inside_code_blocks_are_not_sections(tree):
    """As in the Release workflow's awk, a fenced "## " line neither starts nor ends a section."""
    changelog = tree / "CHANGELOG.md"
    _replace(changelog, "- A feature.\n", "- A feature.\n\n```text\n## [9.9.9] - 2026-01-01\n```\n")
    assert release_check.check_changelog(tree, VERSION) == []

    _replace(
        changelog,
        f"## [{VERSION}] - {RELEASED}\n",
        f"~~~markdown\n## [{VERSION}] - {RELEASED}\n~~~\n",
    )
    assert 'CHANGELOG.md: no "## [1.2.3] - YYYY-MM-DD" section' in release_check.check_changelog(
        tree, VERSION
    )


def test_a_section_whose_body_is_a_code_block_is_not_empty(tree):
    _replace(tree / "CHANGELOG.md", "### Added\n\n- A feature.\n", "```text\nnotes\n```\n")
    assert release_check.check_changelog(tree, VERSION) == []


def test_the_last_section_runs_to_the_end_of_the_file(tree):
    (tree / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## [Unreleased]\n\n## [{VERSION}] - {RELEASED}\n\n- A feature.\n\n"
        f"[{VERSION}]: https://example.com/releases/tag/{TAG}\n"
    )
    assert release_check.check_changelog(tree, VERSION) == []


def test_fails_when_citation_date_differs_from_the_changelog(tree):
    _replace(tree / "CITATION.cff", f"date-released: {RELEASED}", "date-released: 2026-03-05")
    error = _one(release_check.check_changelog(tree, VERSION))
    assert error == (
        "CITATION.cff: date-released 2026-03-05 differs from the CHANGELOG.md date 2026-03-04 "
        "of [1.2.3]"
    )

    _replace(tree / "CITATION.cff", "date-released: 2026-03-05\n", "")
    assert release_check.check_changelog(tree, VERSION) == ["CITATION.cff: no date-released"]

    (tree / "CITATION.cff").unlink()
    assert release_check.check_changelog(tree, VERSION) == ["CITATION.cff: not found or unreadable"]


def test_changelog_needs_the_file_and_a_version(tree):
    assert release_check.check_changelog(tree, None) == [
        "CHANGELOG.md: not checked, pyproject.toml has no version to look for"
    ]
    (tree / "CHANGELOG.md").unlink()
    assert release_check.check_changelog(tree, VERSION) == ["CHANGELOG.md: not found or unreadable"]


# ---------------------------------------------------------------------------
# Placeholders
# ---------------------------------------------------------------------------


def test_fails_on_fill_comment_in_the_readme(tree):
    (tree / "README.md").write_text(
        "# Fixture\n\n| Metric | KG |\n| --- | --- |\n"
        "| Citation hit rate | <!-- FILL (kg_citation_hit_rate) --> |\n"
        "\n<!--FILL(date)-->\n"
    )
    assert release_check.check_placeholders(tree) == [
        "README.md:5: unfilled placeholder: "
        "| Citation hit rate | <!-- FILL (kg_citation_hit_rate) --> |",
        "README.md:7: unfilled placeholder: <!--FILL(date)-->",
    ]


def test_fails_on_fill_comment_in_the_changelog(tree):
    _replace(
        tree / "CHANGELOG.md", "- A feature.", "- A feature: <!-- FILL (final-split claim) -->"
    )
    error = _one(release_check.check_placeholders(tree))
    assert error.startswith("CHANGELOG.md:9: unfilled placeholder: - A feature: <!-- FILL (")


def test_a_line_with_two_fill_comments_is_reported_once(tree):
    (tree / "README.md").write_text("# Fixture\n\n<!-- FILL (a) --> of <!-- FILL (b) -->\n")
    assert release_check.check_placeholders(tree) == [
        "README.md:3: unfilled placeholder: <!-- FILL (a) --> of <!-- FILL (b) -->"
    ]


def test_fill_comment_split_over_lines_is_reported_at_its_first_line(tree):
    (tree / "README.md").write_text("# Fixture\n\n<!--\nFILL (a number)\n-->\n")
    assert release_check.check_placeholders(tree) == ["README.md:3: unfilled placeholder: <!--"]


def test_prose_about_the_marker_is_not_a_placeholder(tree):
    """Only the HTML comment counts, so the documents can describe the check."""
    (tree / "README.md").write_text("# Fixture\n\nNo `FILL (` comment is left. <!-- a note -->\n")
    assert release_check.check_placeholders(tree) == []


def test_placeholder_scan_needs_both_files(tree):
    (tree / "README.md").unlink()
    (tree / "CHANGELOG.md").unlink()
    assert release_check.check_placeholders(tree) == [
        "README.md: not found or unreadable",
        "CHANGELOG.md: not found or unreadable",
    ]


# ---------------------------------------------------------------------------
# Evaluation evidence
# ---------------------------------------------------------------------------


def _rewrite_evidence(tree: Path, mutate) -> None:
    """Replace the evidence with a mutated report and its own, correctly named, snapshot."""
    for snapshot in _snapshots(tree):
        snapshot.unlink()
    report = _fixture_report()
    mutate(report)
    _write_evidence(tree, report)


def test_evidence_written_by_the_harness_passes(tree):
    """release_check cannot import evaluate_rag, so its copy of the snapshot naming is pinned
    against what ``write_reports`` really writes."""
    out_dir = tree / "docs/evals"
    _snapshots(tree)[0].unlink()
    (out_dir / "latest.json").unlink()
    written = evaluate_rag.write_reports(out_dir, _fixture_report())
    assert [path.name for path in written[:2]] == ["latest.json", "latest.md"]

    raw = (out_dir / "latest.json").read_bytes()
    expected = release_check.snapshot_path(raw, json.loads(raw)["generated_at"])
    assert _snapshots(tree) == [tree / expected] == [written[2]]
    assert release_check.check_evidence(tree) == []


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r["run_config"].update(retrieval_only=True), "retrieval-only run"),
        (lambda r: r["run_config"].update(split="rehearsal"), "rehearsal split"),
        (lambda r: r["run_config"].update(limit=3), "partial run"),
        (lambda r: r.update(environment_valid=False), "environment_valid is false"),
        (lambda r: r["results"][0]["kg"].update(status_code=503), "did not return 200"),
        (lambda r: r["provenance"]["llm"].update(ollama_digest=None), "Ollama model digest"),
        (lambda r: r.pop("provenance"), "no provenance"),
        (lambda r: r["provenance"]["harness"].update(git_sha="b" * 40), "differs from the harness"),
    ],
)
def test_fails_on_report_the_demo_gate_rejects(tree, mutate, message):
    _rewrite_evidence(tree, mutate)
    errors = release_check.check_evidence(tree)
    assert errors, "the report passed"
    assert all(error.startswith("docs/evals/latest.json: ") for error in errors)
    assert any(message in error for error in errors), errors


def test_evidence_check_applies_whatever_the_demo_gate_rules_return(tree, monkeypatch):
    """The rules are reused, not copied: a rule added to either function reaches the check."""
    monkeypatch.setattr(release_check, "report_errors", lambda report: ["a new report rule"])
    monkeypatch.setattr(
        check_demo_eval, "checkout_errors", lambda report, root: [f"a new rule for {root.name}"]
    )
    assert release_check.check_evidence(tree) == [
        "docs/evals/latest.json: a new report rule",
        "docs/evals/latest.json: a new rule for tree",
    ]


@pytest.mark.parametrize(
    ("mutate", "raised"),
    [
        (lambda r: r.update(results=5), "TypeError"),
        (lambda r: r["summary"].update(kg_successful_cases="many"), "ValueError"),
        (lambda r: r["summary"].update(kg_successful_cases=float("inf")), "OverflowError"),
    ],
)
def test_fails_on_malformed_report_with_a_named_error(tree, capsys, mutate, raised):
    """The shared rules raise on a shape the harness never writes: a FAIL line, no traceback."""
    _rewrite_evidence(tree, mutate)
    error = _one(release_check.check_evidence(tree))
    assert error.startswith(f"docs/evals/latest.json: malformed report ({raised}: ")

    assert release_check.main(["--root", str(tree), "--tag", TAG]) == 1
    out = capsys.readouterr().out
    assert f"FAIL  evidence\n    {error}\n" in out
    assert out.count("ok    ") == 4


def test_fails_on_app_version_mismatch(tree):
    """A final run made before the version bump records the previous version."""
    _rewrite_evidence(tree, lambda r: r["provenance"]["server"].update(app_version="1.2.2"))
    error = _one(release_check.check_evidence(tree))
    assert error == (
        "docs/evals/latest.json: server app_version 1.2.2 differs from the pyproject.toml "
        "version 1.2.3: run `poetry install` (or rebuild the image), restart the API and re-run"
    )


def test_fails_when_the_version_is_bumped_after_the_run(tree):
    _replace(tree / "pyproject.toml", VERSION, "1.3.0")
    error = _one(release_check.check_evidence(tree))
    assert "server app_version 1.2.3 differs from the pyproject.toml version 1.3.0" in error


def test_fails_when_the_golden_set_changed_since_the_run(tree):
    (tree / "data/evals/golden_qa.yaml").write_text(GOLDEN_SET + "# edited\n")
    error = _one(release_check.check_evidence(tree))
    assert error == (
        "docs/evals/latest.json: golden set data/evals/golden_qa.yaml changed since the run "
        "(sha256 differs)"
    )

    (tree / "data/evals/golden_qa.yaml").unlink()
    error = _one(release_check.check_evidence(tree))
    assert error == "docs/evals/latest.json: golden set data/evals/golden_qa.yaml not found"


def test_evidence_is_judged_in_the_tree_not_the_working_directory(tree, tmp_path, monkeypatch):
    """The fixture's golden set and pyproject.toml exist only under the tree."""
    monkeypatch.chdir(tmp_path)
    assert release_check.check_evidence(tree) == []


def test_recorded_commit_need_not_be_the_checkout(tree):
    """The check runs without git: a squash merge may leave the recorded commit off main."""
    _rewrite_evidence(
        tree,
        lambda r: (
            r["provenance"]["server"].update(git_sha="c" * 40),
            r["provenance"]["harness"].update(git_sha="c" * 40),
        ),
    )
    assert not (tree / ".git").exists()
    assert release_check.check_evidence(tree) == []


def test_fails_on_missing_snapshot(tree):
    snapshot = _snapshots(tree)[0]
    snapshot.unlink()
    error = _one(release_check.check_evidence(tree))
    assert error == (
        f"docs/evals/history/{snapshot.name}: snapshot of docs/evals/latest.json not found "
        "(the snapshot was not committed, or the report was edited after the run)"
    )


def test_snapshot_is_checked_even_when_the_report_is_rejected(tree):
    """One run lists everything to fix: the report's own problems do not hide the snapshot's."""
    _rewrite_evidence(tree, lambda r: r["provenance"]["server"].update(app_version="1.2.2"))
    snapshot = _snapshots(tree)[0]
    snapshot.unlink()
    errors = release_check.check_evidence(tree)
    assert len(errors) == 2, errors
    assert "server app_version 1.2.2 differs from the pyproject.toml version 1.2.3" in errors[0]
    assert errors[1].startswith(f"docs/evals/history/{snapshot.name}: snapshot of ")


def test_fails_on_altered_snapshot(tree):
    snapshot = _snapshots(tree)[0]
    snapshot.write_bytes(
        snapshot.read_bytes().replace(b'"citation_hit": true', b'"citation_hit": false')
    )
    error = _one(release_check.check_evidence(tree))
    assert error == (
        f"docs/evals/history/{snapshot.name}: differs from docs/evals/latest.json "
        "(the snapshot was altered)"
    )


def test_fails_when_the_report_was_edited_after_the_run(tree):
    """An edited latest.json hashes to another name, where no snapshot exists."""
    latest = tree / "docs/evals/latest.json"
    report = json.loads(latest.read_text())
    edited = copy.deepcopy(report)
    edited["summary"]["kg_citation_hit_rate"] = 1.0
    edited["api_url"] = "http://edited"
    latest.write_text(json.dumps(edited, indent=2, ensure_ascii=False) + "\n")
    error = _one(release_check.check_evidence(tree))
    assert "snapshot of docs/evals/latest.json not found" in error
    assert _snapshots(tree)[0].name not in error


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, "docs/evals/latest.json: not found or unreadable"),
        (b"{", "docs/evals/latest.json: invalid JSON"),
        (b"\xff\xfe\x00", "docs/evals/latest.json: invalid JSON"),
        (b"[]", "docs/evals/latest.json: not a JSON object"),
    ],
)
def test_fails_on_missing_or_unreadable_report(tree, content, message):
    latest = tree / "docs/evals/latest.json"
    if content is None:
        latest.unlink()
    else:
        latest.write_bytes(content)
    assert message in _one(release_check.check_evidence(tree))


def test_fails_on_report_without_generated_at(tree):
    _rewrite_evidence(tree, lambda r: r.update(generated_at="unknown"))
    error = _one(release_check.check_evidence(tree))
    assert error == (
        "docs/evals/latest.json: no generated_at date, so its history snapshot has no name"
    )


# ---------------------------------------------------------------------------
# Demo assets
# ---------------------------------------------------------------------------


def test_fails_without_a_demo_image(tree):
    assets = tree / "docs/assets/demo"
    (assets / "01-home.png").unlink()
    (assets / "demo-walkthrough.mp4").write_bytes(b"video")
    (assets / "README.md").write_text("# Assets\n")
    (assets / "empty.png").write_bytes(b"")
    (assets / "folder.png").mkdir()
    expected = ["docs/assets/demo: no image (.png, .jpg, .jpeg, .gif, .webp)"]
    assert release_check.check_assets(tree) == expected

    (assets / "02-chat.JPG").write_bytes(b"\xff\xd8\xff")
    assert release_check.check_assets(tree) == []


def test_fails_without_the_demo_asset_directory(tree):
    (tree / "docs/assets/demo/01-home.png").unlink()
    (tree / "docs/assets/demo").rmdir()
    assert release_check.check_assets(tree) == [
        "docs/assets/demo: no image (.png, .jpg, .jpeg, .gif, .webp)"
    ]


# ---------------------------------------------------------------------------
# Release workflow
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def release_workflow() -> dict[str, Any]:
    return yaml.safe_load(RELEASE_WORKFLOW.read_text())


@pytest.fixture(scope="module")
def release_job(release_workflow) -> dict[str, Any]:
    assert list(release_workflow["jobs"]) == ["release"]
    return release_workflow["jobs"]["release"]


def _steps(job: dict[str, Any]) -> list[str]:
    return [step.get("name", step.get("uses", "")) for step in job["steps"]]


def _step(job: dict[str, Any], name: str) -> dict[str, Any]:
    return next(step for step in job["steps"] if step.get("name") == name)


def _run_step(
    job: dict[str, Any], name: str, cwd: Path, **env: str
) -> subprocess.CompletedProcess[str]:
    """Run a step's script as Actions runs a `run` step without `shell:` (`bash -e`)."""
    return subprocess.run(
        ["bash", "-e", "-c", _step(job, name)["run"]],
        cwd=cwd,
        env={"PATH": os.environ["PATH"], "TAG": TAG, **env},
        capture_output=True,
        text=True,
    )


def _python3_on_path(directory: Path, script: str) -> str:
    """A PATH whose `python3` is the given shell script."""
    bin_dir = directory / "bin"
    bin_dir.mkdir()
    python3 = bin_dir / "python3"
    python3.write_text(f"#!/bin/bash\n{script}\n")
    python3.chmod(0o755)
    return f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


def test_release_workflow_runs_the_gate_before_it_creates_anything(release_job):
    names = _steps(release_job)
    gate = names.index(GATE_STEP)
    assert names.index(ON_MAIN_STEP) < gate
    assert gate < names.index(NOTES_STEP)
    assert gate < names.index(CREATE_STEP)
    # The tag's tree must be checked out before the gate reads it
    checked_out = next(i for i, step in enumerate(release_job["steps"]) if "uses" in step)
    assert release_job["steps"][checked_out]["with"]["ref"] == "refs/tags/${{ env.TAG }}"
    assert checked_out < gate


def test_release_gate_has_no_condition_and_gets_no_token(release_workflow, release_job):
    step = _step(release_job, GATE_STEP)
    assert set(step) == {"name", "run"}  # no `if`, no `continue-on-error`, no `env` (no token)
    assert 'python3 -I scripts/release_check.py --tag "${TAG}"' in step["run"]
    for word in ("GH_TOKEN", "GITHUB_TOKEN", "github.token", "secrets."):
        assert word not in step["run"]
    # Nor through the workflow or the job: only the two steps that call the API get the token
    assert "env" not in release_workflow
    assert set(release_job["env"]) == {"TAG", "GH_REPO"}
    assert not any("token" in value or "secrets." in value for value in release_job["env"].values())
    with_token = [
        step["name"] for step in release_job["steps"] if "GH_TOKEN" in step.get("env", {})
    ]
    assert with_token == [ON_MAIN_STEP, CREATE_STEP]


def test_release_workflow_keeps_its_permissions_and_actions(release_workflow, release_job):
    assert release_workflow["permissions"] == {"contents": "read"}
    assert release_job["permissions"] == {"contents": "write"}
    uses = [step["uses"] for step in release_job["steps"] if "uses" in step]
    assert len(uses) == 1
    assert uses[0].startswith("actions/checkout@v")


def _run_gate(
    job: dict[str, Any], workdir: Path, *, script: bool, exit_code: int = 0
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the gate step with a stand-in for python3 that records its arguments."""
    workdir.mkdir()
    if script:
        (workdir / "scripts").mkdir()
        (workdir / "scripts/release_check.py").write_text("")
    calls = workdir / "python3.calls"
    path = _python3_on_path(workdir, f'echo "$*" >> {shlex.quote(str(calls))}\nexit {exit_code}')
    result = _run_step(job, GATE_STEP, workdir, PATH=path)
    return result, calls.read_text().splitlines() if calls.exists() else []


def test_release_gate_is_skipped_for_tags_that_predate_the_script(release_job, tmp_path):
    """Re-publishing v0.3.0 by hand must still work: its tree has no release_check.py."""
    result, calls = _run_gate(release_job, tmp_path / "old-tag", script=False)
    assert result.returncode == 0, result.stderr
    assert calls == []
    assert result.stdout.startswith("::notice::")
    assert TAG in result.stdout


def test_release_gate_runs_the_script_from_the_tagged_tree(release_job, tmp_path):
    result, calls = _run_gate(release_job, tmp_path / "new-tag", script=True)
    assert result.returncode == 0, result.stderr
    assert calls == [f"-I scripts/release_check.py --tag {TAG}"]
    assert "::notice::" not in result.stdout


def test_release_gate_failure_fails_the_job(release_job, tmp_path):
    result, calls = _run_gate(release_job, tmp_path / "bad-tag", script=True, exit_code=1)
    assert result.returncode == 1
    assert calls == [f"-I scripts/release_check.py --tag {TAG}"]
    assert "::error::" in result.stdout


def test_release_gate_step_runs_the_real_script_on_the_tagged_tree(release_job, checkout, tmp_path):
    """The step's own command line, the real script and an interpreter without packages."""
    path = _python3_on_path(tmp_path, f'exec {shlex.quote(sys.executable)} -S "$@"')

    passed = _run_step(release_job, GATE_STEP, checkout, PATH=path)
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert passed.stdout.splitlines()[-1] == f"release-check for {TAG}: ok"

    failed = _run_step(release_job, GATE_STEP, checkout, PATH=path, TAG="v1.2.4")
    assert failed.returncode == 1
    assert "tag v1.2.4 does not match the pyproject.toml version 1.2.3" in failed.stdout
    assert failed.stdout.splitlines()[-1].startswith("::error::v1.2.4 failed the release check")

    prerelease = _run_step(release_job, GATE_STEP, checkout, PATH=path, TAG="v1.2.3-rc.1")
    assert prerelease.returncode == 1
    assert "tag v1.2.3-rc.1 is a pre-release or build tag" in prerelease.stdout


def _swap(old: str, new: str):
    """An edit of the fixture changelog that fails when its text is not there."""

    def edit(text: str) -> str:
        assert old in text, f"{old!r} not in the fixture changelog"
        return text.replace(old, new)

    return edit


@pytest.mark.parametrize(
    ("edit", "notes"),
    [
        (lambda text: text, "changelog"),
        (_swap("\n", "\r\n"), "changelog"),
        (_swap("### Added\n\n- A feature.\n", "```text\n## [9.9.9]\n```\n"), "changelog"),
        (_swap(f"## [{VERSION}]", "## [1.2.1]"), "generated"),
        (_swap(f"## [{VERSION}]", f"  ## [{VERSION}]"), "generated"),
        (
            _swap(f"## [{VERSION}] - {RELEASED}\n", f"```text\n## [{VERSION}] - {RELEASED}\n```\n"),
            "generated",
        ),
        (_swap("## [Unreleased]\n", "## [Unreleased]\n\n~~~\nunclosed\n"), "generated"),
        (_swap("### Added\n\n- A feature.\n\n", ""), "generated"),
        (
            _swap(
                "### Added\n\n- A feature.\n", "[1.2.1]: https://example.com/releases/tag/v1.2.1\n"
            ),
            "generated",
        ),
    ],
    ids=[
        "fixture",
        "crlf",
        "code-block-body",
        "no-section",
        "indented-heading",
        "fenced-heading",
        "unclosed-fence-above",
        "empty-body",
        "link-reference-body",
    ],
)
def test_changelog_check_fails_whenever_the_workflow_would_generate_notes(
    release_job, tree, tmp_path, edit, notes
):
    """The workflow's own extraction is the reference: with the gate in front, its fallback
    to generated notes is unreachable for a missing or empty section."""
    (tree / "CHANGELOG.md").write_bytes(edit(CHANGELOG).encode())
    output = tmp_path / "github-output"
    output.write_text("")

    result = _run_step(release_job, NOTES_STEP, tree, GITHUB_OUTPUT=str(output))
    assert result.returncode == 0, result.stderr
    assert output.read_text() == f"source={notes}\n"
    errors = release_check.check_changelog(tree, VERSION)
    assert (errors == []) == (notes == "changelog"), errors
