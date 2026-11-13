"""
Tests for the dependency-audit helpers (scripts/osv_audit.py) and for the
osv-scanner allowlists they police.
"""

import importlib.util
import json
import re
import tomllib
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts import osv_audit

FRONTEND_ALLOWLIST = Path("frontend/osv-scanner.toml")
FRONTEND_LOCK = Path("frontend/package-lock.json")
ALLOWLISTS = [Path("osv-scanner.toml"), FRONTEND_ALLOWLIST]
FRONTEND_ENTRIES = osv_audit.load_allowlist(FRONTEND_ALLOWLIST)
# The directories of frontend/ that Next.js compiles into the application
FRONTEND_SOURCES = [Path("frontend", name) for name in ("app", "components", "lib", "types")]

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


@pytest.mark.parametrize("config", ALLOWLISTS, ids=str)
def test_allowlists_have_only_the_keys_in_use(config):
    """A fact about an entry goes into its reason, not into a new key.

    #254 records that osv-scanner rejects a configuration with a key it does not know and
    then scans without the allowlist. Check the osv-scanner configuration reference before
    extending either set.
    """
    data = tomllib.loads(config.read_text(encoding="utf-8"))
    assert set(data) == {"IgnoredVulns"}, f"unexpected top-level key in {config}"
    for raw in data["IgnoredVulns"]:
        assert set(raw) == {"id", "ignoreUntil", "reason"}, f"{raw.get('id')} in {config}"


# The reason contract of frontend/osv-scanner.toml (#254). A reason starts with the package
# and every version the lock has of it: "braces 3.0.3 is a dev-only dependency ...", or
# "minimatch 3.1.5, 9.0.9 and 10.2.6 are dev-only dependencies ...".
_VERSION = r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.+-]+)?"
_DEV_ONLY_REASON = re.compile(
    r"^(?P<name>(?:@[\w.-]+/)?[\w.-]+) "
    rf"(?P<versions>{_VERSION}(?:(?:, | and ){_VERSION})*) "
    r"(?:is a dev-only dependency|are dev-only dependencies)\b"
)
_NOT_BUNDLED = "not in the production bundle"
_REASON_FORMAT = (
    'the reason does not start with "<package> <version> is a dev-only dependency" or '
    '"<package> <version>, <version> and <version> are dev-only dependencies"'
)
# The dependency groups npm installs besides devDependencies: for the root project with
# --omit=dev, and for every other package always
_PRODUCTION_GROUPS = ("dependencies", "optionalDependencies", "peerDependencies")
# A package named with a version after the start of a reason, as in "via jest 30"
_TOOL_MENTION = re.compile(
    r"(?<![\w./@-])(?P<tool>(?:@[\w.-]+/)?[\w.-]+) (?P<version>\d+(?:\.\d+)*)"
)


def _listed(versions: set[str]) -> str:
    """Join versions in numeric order, so 9.0.9 comes before 10.2.6."""
    return ", ".join(sorted(versions, key=lambda v: ([int(n) for n in re.findall(r"\d+", v)], v)))


def _copies_of(packages: dict[str, Any], name: str) -> dict[str, dict[str, Any]]:
    """Every lock entry of a package: the top-level copy and the nested ones."""
    return {
        path: meta
        for path, meta in packages.items()
        if path == f"node_modules/{name}" or path.endswith(f"/node_modules/{name}")
    }


def _installed_with(packages: dict[str, Any], start: str) -> set[str]:
    """The lock paths of a package and of everything npm installs for it, transitively.

    A dependency resolves as Node resolves it: to the nearest ``node_modules/<name>`` on the
    way up from the package that asks for it.
    """
    seen: set[str] = set()
    todo = [start]
    while todo:
        path = todo.pop()
        if path in seen or path not in packages:
            continue
        seen.add(path)
        for group in _PRODUCTION_GROUPS:
            for dependency in packages[path].get(group) or {}:
                above = path
                while above and f"{above}/node_modules/{dependency}" not in packages:
                    above = above.rpartition("/node_modules/")[0]
                todo.append(f"{above}/node_modules/{dependency}".lstrip("/"))
    return seen


def dev_only_violations(reason: str, lock: dict[str, Any]) -> list[str]:
    """List what contradicts an allowlist reason's claim that an npm package is dev-only.

    The reason has to follow the contract above and say that the package is not in the
    production bundle. The lock (a parsed package-lock.json) has to agree: every copy of the
    package, nested ones included, is marked ``"dev": true``, which is what
    ``npm prune --omit=dev`` removes; the copies have exactly the stated versions; and the
    project does not depend on the package directly.

    Args:
        reason: The ``reason`` of one ``[[IgnoredVulns]]`` entry.
        lock: The parsed lockfile (``lockfileVersion`` 2 or 3, with a ``packages`` table).

    Returns:
        One sentence per violation; empty when the reason and the lock agree.
    """
    violations = []
    if _NOT_BUNDLED not in reason:
        violations.append(f'the reason does not say "{_NOT_BUNDLED}"')
    match = _DEV_ONLY_REASON.match(reason)
    if match is None:
        return [*violations, _REASON_FORMAT]

    name = match["name"]
    stated = set(re.split(r", | and ", match["versions"]))
    packages = lock.get("packages") or {}
    copies = _copies_of(packages, name)
    if not copies:
        violations.append(f"{name} is not in the lock")
    violations.extend(
        f'{path} is not marked "dev": true in the lock'
        for path, meta in copies.items()
        if meta.get("dev") is not True
    )
    locked = {str(meta.get("version")) for meta in copies.values()}
    if copies and locked != stated:
        violations.append(
            f"the reason states {name} {_listed(stated)}; the lock has {_listed(locked)}"
        )
    root = packages.get("") or {}
    violations.extend(
        f"{name} is one of the project's {group}"
        for group in _PRODUCTION_GROUPS
        if name in (root.get(group) or {})
    )
    return violations


def named_tool_violations(reason: str, lock: dict[str, Any]) -> list[str]:
    """List the tools an allowlist reason names that the lock contradicts.

    A reason says where its package comes from, as in "via jest 30". A tool is one of the
    project's devDependencies named with a version. The lock has to have the tool at that
    version, and installing the tool has to install the package. The braces reason said
    "jest 29" while the lock had jest 30, and jest never installed braces (#254). Other
    names in a reason are not checked.

    Args:
        reason: The ``reason`` of one ``[[IgnoredVulns]]`` entry.
        lock: The parsed lockfile (``lockfileVersion`` 2 or 3, with a ``packages`` table).

    Returns:
        One sentence per violation. Empty when the lock agrees, and when the reason does not
        follow the contract, which ``dev_only_violations`` reports.
    """
    match = _DEV_ONLY_REASON.match(reason)
    if match is None:
        return []
    name = match["name"]
    packages = lock.get("packages") or {}
    tools = (packages.get("") or {}).get("devDependencies") or {}
    mentions = dict.fromkeys(
        (mention["tool"].lower(), mention["version"])
        for mention in _TOOL_MENTION.finditer(reason, match.end())
    )
    violations = []
    for tool, version in mentions:
        if tool == name or tool not in tools:
            continue
        path = f"node_modules/{tool}"
        locked = str((packages.get(path) or {}).get("version"))
        stated = version.split(".")
        if locked.split(".")[: len(stated)] != stated:
            violations.append(f"the reason names {tool} {version}; the lock has {tool} {locked}")
        if not _copies_of(packages, name).keys() & _installed_with(packages, path):
            violations.append(f"{tool} does not depend on {name} in the lock")
    return violations


def _import_of(name: str) -> re.Pattern[str]:
    """Match an import of a package, or of a path inside it, in JavaScript or TypeScript."""
    return re.compile(
        r"""(?:\bfrom|\bimport|\brequire\s*\(|\bimport\s*\()\s*['"]"""
        + re.escape(name)
        + r"""(?:/[^'"]*)?['"]"""
    )


@pytest.fixture(scope="module")
def frontend_lock() -> dict[str, Any]:
    return json.loads(FRONTEND_LOCK.read_text(encoding="utf-8"))


@pytest.mark.parametrize("entry", FRONTEND_ENTRIES, ids=lambda entry: entry.id)
def test_frontend_allowlist_entries_are_dev_only_in_the_lock(entry, frontend_lock):
    """Each npm entry is accepted as dev-only; the lock has to say the same (#254).

    A dependency update that changes a locked version of an allowlisted package fails here
    until the entry's reason states the new versions. test_docker.py checks that the
    frontend image prunes dev dependencies.
    """
    assert dev_only_violations(entry.reason, frontend_lock) == [], (
        f"{entry.id}: the reason in {FRONTEND_ALLOWLIST} and {FRONTEND_LOCK} disagree"
    )


@pytest.mark.parametrize("entry", FRONTEND_ENTRIES, ids=lambda entry: entry.id)
def test_frontend_allowlist_reasons_name_tools_as_the_lock_has_them(entry, frontend_lock):
    """A major update of a tool a reason names fails here until the reason is updated."""
    assert named_tool_violations(entry.reason, frontend_lock) == [], (
        f"{entry.id}: the reason in {FRONTEND_ALLOWLIST} and {FRONTEND_LOCK} disagree"
    )


@pytest.mark.parametrize("entry", FRONTEND_ENTRIES, ids=lambda entry: entry.id)
def test_frontend_sources_do_not_import_an_allowlisted_package(entry):
    """The lock and the prune cover node_modules, not what Next.js compiles into .next.

    The build runs with the dev dependencies installed and bundles what the application
    imports, so a direct import would put a dev-only package into the production bundle.
    """
    match = _DEV_ONLY_REASON.match(entry.reason)
    assert match is not None, f"{entry.id}: {_REASON_FORMAT}"
    imported = _import_of(match["name"])
    assert all(root.is_dir() for root in FRONTEND_SOURCES), "a frontend source directory moved"
    offenders = [
        f"{path}:{number}"
        for root in FRONTEND_SOURCES
        for path in sorted(root.rglob("*"))
        if path.suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if imported.search(line)
    ]
    assert offenders == [], f"{entry.id}: the application imports {match['name']}"


def _npm_lock(packages: dict[str, dict[str, Any]], **root: dict[str, str]) -> dict[str, Any]:
    """A package-lock.json with these package paths and these fields on the root project."""
    return {"lockfileVersion": 3, "packages": {"": {"name": "app", **root}, **packages}}


def _dev(version: str) -> dict[str, Any]:
    return {"version": version, "dev": True}


_BRACES_REASON = (
    "braces 3.0.3 is a dev-only dependency (via tailwindcss 3) and is not in the production "
    "bundle; no fixed release yet; tracked in #1"
)
_GLOB_REASON = (
    "glob 10.5.0 and 13.0.6 are dev-only dependencies (via jest 30) and are not in the "
    "production bundle; tracked in #1"
)
_SCOPED_REASON = (
    "@scope/tool 3.0.3 is a dev-only dependency and is not in the production bundle; tracked in #1"
)


class TestDevOnlyViolations:
    def test_accepts_one_dev_only_copy_at_the_stated_version(self):
        lock = _npm_lock({"node_modules/braces": _dev("3.0.3")}, dependencies={"next": "16.0.0"})
        assert dev_only_violations(_BRACES_REASON, lock) == []

    def test_accepts_several_versions_in_nested_copies(self):
        reason = (
            "minimatch 3.1.5, 9.0.9 and 10.2.6 are dev-only dependencies (via ESLint 9) and "
            "are not in the production bundle; tracked in #1"
        )
        lock = _npm_lock(
            {
                "node_modules/minimatch": _dev("3.1.5"),
                "node_modules/glob/node_modules/minimatch": _dev("9.0.9"),
                "node_modules/jest-config/node_modules/minimatch": _dev("10.2.6"),
                "node_modules/jest-runtime/node_modules/minimatch": _dev("10.2.6"),
            }
        )
        assert dev_only_violations(reason, lock) == []

    def test_accepts_a_scoped_package_and_a_prerelease_version(self):
        reason = (
            "@scope/tool 2.0.0-rc.1 is a dev-only dependency and is not in the production "
            "bundle; tracked in #1"
        )
        lock = _npm_lock({"node_modules/@scope/tool": _dev("2.0.0-rc.1")})
        assert dev_only_violations(reason, lock) == []

    @pytest.mark.parametrize(
        ("reason", "path"),
        [
            (_BRACES_REASON, "node_modules/chokidar/node_modules/braces"),
            (_SCOPED_REASON, "node_modules/jest/node_modules/@scope/tool"),
        ],
        ids=["plain-name", "scoped-name"],
    )
    def test_accepts_a_package_that_has_only_a_nested_copy(self, reason, path):
        assert dev_only_violations(reason, _npm_lock({path: _dev("3.0.3")})) == []

    def test_accepts_a_copy_that_is_dev_and_optional(self):
        # npm prune --omit=dev removes it: "dev" is set, unlike on a devOptional copy
        lock = _npm_lock({"node_modules/braces": {**_dev("3.0.3"), "optional": True}})
        assert dev_only_violations(_BRACES_REASON, lock) == []

    def test_ignores_other_packages_whose_path_ends_alike(self):
        lock = _npm_lock(
            {
                "node_modules/glob": _dev("10.5.0"),
                "node_modules/jest-config/node_modules/glob": _dev("13.0.6"),
                "node_modules/fast-glob": {"version": "3.3.3"},
                "node_modules/@scope/glob": {"version": "1.0.0"},
                "node_modules/glob-parent": {"version": "5.1.2"},
                "node_modules/glob/node_modules/path-scurry": {"version": "2.0.0"},
            },
            dependencies={"fast-glob": "^3.3.3"},
        )
        assert dev_only_violations(_GLOB_REASON, lock) == []

    @pytest.mark.parametrize(
        "reason",
        [
            "braces is a dev-only dependency and is not in the production bundle; #1",
            "braces 3 is a dev-only dependency and is not in the production bundle; #1",
            "braces 3.0.3 has no fixed release yet and is not in the production bundle; #1",
            "The package braces 3.0.3 is a dev-only dependency, not in the production bundle; #1",
            "braces 3.0.3 or 3.0.4 is a dev-only dependency, not in the production bundle; #1",
        ],
    )
    def test_rejects_a_reason_that_does_not_follow_the_format(self, reason):
        lock = _npm_lock({"node_modules/braces": _dev("3.0.3")})
        assert dev_only_violations(reason, lock) == [_REASON_FORMAT]

    def test_rejects_a_reason_without_the_production_bundle_claim(self):
        reason = "braces 3.0.3 is a dev-only dependency (via tailwindcss 3); tracked in #1"
        lock = _npm_lock({"node_modules/braces": _dev("3.0.3")})
        assert dev_only_violations(reason, lock) == [
            'the reason does not say "not in the production bundle"'
        ]

    def test_rejects_a_reason_that_makes_neither_claim(self):
        reason = "braces 3.0.3 has no fixed release yet; tracked in #1"
        lock = _npm_lock({"node_modules/braces": _dev("3.0.3")})
        assert dev_only_violations(reason, lock) == [
            'the reason does not say "not in the production bundle"',
            _REASON_FORMAT,
        ]

    @pytest.mark.parametrize(
        "lock",
        [
            _npm_lock({"node_modules/micromatch": _dev("4.0.8")}),
            _npm_lock({"node_modules/@scope/braces": _dev("3.0.3")}),
            _npm_lock({"node_modules/xbraces": _dev("3.0.3")}),
            # lockfileVersion 1 has no packages table
            {"lockfileVersion": 1, "dependencies": {"braces": {"version": "3.0.3", "dev": True}}},
        ],
        ids=["other-package", "scoped-namesake", "longer-name", "no-packages-table"],
    )
    def test_rejects_a_package_the_lock_does_not_have(self, lock):
        assert dev_only_violations(_BRACES_REASON, lock) == ["braces is not in the lock"]

    @pytest.mark.parametrize(
        "flags",
        [{}, {"dev": False}, {"devOptional": True}, {"optional": True}, {"peer": True}],
        ids=lambda flags: ",".join(flags) or "no-flag",
    )
    def test_rejects_a_copy_that_is_not_dev_only(self, flags):
        lock = _npm_lock({"node_modules/braces": {"version": "3.0.3", **flags}})
        assert dev_only_violations(_BRACES_REASON, lock) == [
            'node_modules/braces is not marked "dev": true in the lock'
        ]

    def test_rejects_a_nested_production_copy_at_a_stated_version(self):
        # Same version as the dev-only top-level copy, so only the dev flag gives it away
        lock = _npm_lock(
            {
                "node_modules/braces": _dev("3.0.3"),
                "node_modules/next/node_modules/braces": {"version": "3.0.3"},
            }
        )
        assert dev_only_violations(_BRACES_REASON, lock) == [
            'node_modules/next/node_modules/braces is not marked "dev": true in the lock'
        ]

    def test_rejects_a_nested_production_copy_of_a_scoped_package(self):
        lock = _npm_lock(
            {
                "node_modules/@scope/tool": _dev("3.0.3"),
                "node_modules/next/node_modules/@scope/tool": {"version": "3.0.3"},
            }
        )
        assert dev_only_violations(_SCOPED_REASON, lock) == [
            'node_modules/next/node_modules/@scope/tool is not marked "dev": true in the lock'
        ]

    def test_rejects_a_stale_version(self):
        lock = _npm_lock({"node_modules/braces": _dev("3.0.4")})
        assert dev_only_violations(_BRACES_REASON, lock) == [
            "the reason states braces 3.0.3; the lock has 3.0.4"
        ]

    def test_rejects_a_nested_version_the_reason_does_not_state(self):
        lock = _npm_lock(
            {
                "node_modules/braces": _dev("3.0.3"),
                "node_modules/chokidar/node_modules/braces": _dev("2.3.2"),
            }
        )
        assert dev_only_violations(_BRACES_REASON, lock) == [
            "the reason states braces 3.0.3; the lock has 2.3.2, 3.0.3"
        ]

    def test_rejects_a_stated_version_the_lock_no_longer_has(self):
        lock = _npm_lock({"node_modules/glob": _dev("10.5.0")})
        assert dev_only_violations(_GLOB_REASON, lock) == [
            "the reason states glob 10.5.0, 13.0.6; the lock has 10.5.0"
        ]

    @pytest.mark.parametrize("group", ["dependencies", "optionalDependencies", "peerDependencies"])
    def test_rejects_a_direct_production_dependency(self, group):
        lock = _npm_lock({"node_modules/braces": _dev("3.0.3")}, **{group: {"braces": "^3.0.3"}})
        assert dev_only_violations(_BRACES_REASON, lock) == [
            f"braces is one of the project's {group}"
        ]

    def test_accepts_a_direct_dev_dependency(self):
        lock = _npm_lock(
            {"node_modules/braces": _dev("3.0.3")}, devDependencies={"braces": "^3.0.3"}
        )
        assert dev_only_violations(_BRACES_REASON, lock) == []

    def test_reports_every_violation(self):
        reason = "glob 10.5.0 and 13.0.6 are dev-only dependencies of jest 30; tracked in #1"
        lock = _npm_lock(
            {
                "node_modules/glob": {"version": "10.5.0"},
                "node_modules/jest-config/node_modules/glob": _dev("14.0.0"),
            },
            dependencies={"glob": "^10.5.0"},
        )
        assert dev_only_violations(reason, lock) == [
            'the reason does not say "not in the production bundle"',
            'node_modules/glob is not marked "dev": true in the lock',
            "the reason states glob 10.5.0, 13.0.6; the lock has 10.5.0, 14.0.0",
            "glob is one of the project's dependencies",
        ]


def _tool(version: str, **dependencies: str) -> dict[str, Any]:
    return {"version": version, "dev": True, "dependencies": dependencies}


# jest installs glob 13 and minimatch 10 as nested copies, tailwindcss installs glob 10 and
# braces, and eslint installs none of them
_TOOLING_PACKAGES = {
    "node_modules/jest": _tool("30.5.2", **{"jest-config": "30.5.2"}),
    "node_modules/jest-config": _tool("30.5.2", glob="^13.0.0"),
    "node_modules/jest-config/node_modules/glob": _tool("13.0.6", minimatch="^10.2.2"),
    "node_modules/jest-config/node_modules/minimatch": _dev("10.2.6"),
    "node_modules/tailwindcss": _tool("3.4.19", sucrase="^3.35.0", micromatch="^4.0.8"),
    "node_modules/sucrase": _tool("3.35.0", glob="^10.3.10"),
    "node_modules/glob": _dev("10.5.0"),
    "node_modules/micromatch": _tool("4.0.8", braces="^3.0.3"),
    "node_modules/braces": _dev("3.0.3"),
    "node_modules/eslint": _tool("9.39.5", debug="^4.3.2"),
    "node_modules/debug": _dev("4.4.3"),
}
_TOOLING_LOCK = _npm_lock(
    _TOOLING_PACKAGES,
    devDependencies={"jest": "^30.5.2", "tailwindcss": "^3.4.19", "eslint": "^9.39.0"},
)


class TestNamedToolViolations:
    @pytest.mark.parametrize(
        "reason",
        [
            "glob 10.5.0 and 13.0.6 are dev-only dependencies (via jest 30 and tailwindcss "
            "3/sucrase) and are not in the production bundle; tracked in #1",
            "glob 10.5.0 and 13.0.6 are dev-only dependencies (via jest 30.5 and Tailwindcss "
            "3.4.19); tracked in #1",
            "braces 3.0.3 is a dev-only dependency (via micromatch in tailwindcss 3. It is "
            "not in the production bundle); tracked in #1",
            "minimatch 10.2.6 is a dev-only dependency (via jest 30); tracked in #1",
        ],
        ids=[
            "majors",
            "longer-versions-and-capitals",
            "version-before-a-full-stop",
            "sibling-of-a-nested-copy",
        ],
    )
    def test_accepts_tools_at_the_locked_version_that_install_the_package(self, reason):
        assert named_tool_violations(reason, _TOOLING_LOCK) == []

    def test_ignores_names_that_are_not_tools_of_the_project(self):
        # glob 14 is the package itself, micromatch is not a devDependency, #30 is an issue
        reason = (
            "glob 10.5.0 and 13.0.6 are dev-only dependencies (via micromatch 5 and webpack "
            "6); the fix is only in glob 14; tracked in #30"
        )
        lock = _npm_lock(_TOOLING_PACKAGES, devDependencies={"jest": "^30", "glob": "^10.5.0"})
        assert named_tool_violations(reason, lock) == []

    def test_rejects_a_stale_tool_version(self):
        reason = "glob 10.5.0 and 13.0.6 are dev-only dependencies (via jest 29); tracked in #1"
        assert named_tool_violations(reason, _TOOLING_LOCK) == [
            "the reason names jest 29; the lock has jest 30.5.2"
        ]

    def test_rejects_a_tool_that_does_not_install_the_package(self):
        reason = "braces 3.0.3 is a dev-only dependency (via ESLint 9); tracked in #1"
        assert named_tool_violations(reason, _TOOLING_LOCK) == [
            "eslint does not depend on braces in the lock"
        ]

    def test_rejects_the_braces_reason_as_it_was(self):
        # The reason before #254: jest was at 30 and did not install braces
        reason = (
            "braces 3.0.3 is a dev-only dependency (via chokidar and micromatch in the build "
            "and test tooling: tailwindcss 3, jest 29, the Next.js ESLint plugin) and is not "
            "in the production bundle; no fixed release yet; tracked in #166"
        )
        assert named_tool_violations(reason, _TOOLING_LOCK) == [
            "the reason names jest 29; the lock has jest 30.5.2",
            "jest does not depend on braces in the lock",
        ]

    def test_resolves_a_dependency_to_the_nearest_copy(self):
        # sucrase gets its own copy of lines, which does not depend on glob; the top-level
        # copy does
        lock = _npm_lock(
            {
                "node_modules/tailwindcss": _tool("3.4.19", sucrase="^3.35.0"),
                "node_modules/sucrase": _tool("3.35.0", lines="^1.0.0"),
                "node_modules/sucrase/node_modules/lines": _tool("1.0.0"),
                "node_modules/lines": _tool("2.0.0", glob="^10.5.0"),
                "node_modules/glob": _dev("10.5.0"),
            },
            devDependencies={"tailwindcss": "^3.4.19"},
        )
        reason = "glob 10.5.0 is a dev-only dependency (via tailwindcss 3); tracked in #1"
        assert named_tool_violations(reason, lock) == [
            "tailwindcss does not depend on glob in the lock"
        ]

    def test_leaves_a_reason_outside_the_contract_to_the_dev_only_check(self):
        assert named_tool_violations("comes with jest 29; tracked in #1", _TOOLING_LOCK) == []


@pytest.mark.parametrize(
    "line",
    [
        "import { glob } from 'glob'",
        '} from "glob"',
        "import 'glob'",
        "const glob = require('glob')",
        "const { glob } = await import('glob')",
        "import { sync } from 'glob/dist/esm/index.js'",
        "export * from 'glob'",
    ],
)
def test_import_pattern_matches_an_import_of_the_package(line):
    assert _import_of("glob").search(line)


@pytest.mark.parametrize(
    "line",
    [
        "import fg from 'fast-glob'",
        "import parent from 'glob-parent'",
        "import { glob } from './glob'",
        "import { glob } from '@scope/glob'",
        "// glob is a dev dependency",
        "const pattern = 'glob'",
    ],
)
def test_import_pattern_ignores_other_modules(line):
    assert _import_of("glob").search(line) is None


# The torch reasons in osv-scanner.toml say jit.script and .pt2 loading are unused.
# The transformers checks outlived their allowlist entries (#71): the app only loads
# the configured models, and remote code, model saving and training stay out of it.
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
    # With `kernels` installed, transformers can fetch compute kernels (code) from the Hub.
    assert importlib.util.find_spec("kernels") is None
