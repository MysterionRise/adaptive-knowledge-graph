"""
`scripts/domain_tool.py apply` (#211) and the scripts around it: the `domain-overlay`
probe of scripts/stack_check.py, scripts/seed_demo.sh and scripts/doctor.sh.

Domains are written under tmp_path. The Neo4j adapter is the real class on an in-memory
session (backend/tests/domain_builders.py); nothing connects.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.domain.loader import load_domain
from backend.app.domain.overlay import apply_overlay
from backend.tests.domain_builders import (
    SOURCE_ID,
    SUBJECT,
    documents,
    fake_adapter,
    relationship,
    term,
    write_domain,
)
from scripts import domain_tool, stack_check

pytestmark = pytest.mark.unit


def _no_neo4j(subject_id):
    pytest.fail(f"connected to Neo4j for {subject_id}")


@pytest.fixture
def offline(monkeypatch):
    """Fail the test if the tool asks for a Neo4j adapter."""
    monkeypatch.setattr(domain_tool, "get_neo4j_adapter", _no_neo4j)


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "domains"
    path.mkdir()
    return path


def _run(capsys, *argv: str) -> tuple[int, str]:
    code = domain_tool.main(list(argv))
    return code, capsys.readouterr().out


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


def _curated(root: Path, related: bool = True) -> Path:
    """A reviewed domain; ``related`` adds an approved RELATED entry, which apply skips."""
    terms = [
        term("Tariff", "approved", definition="a curated definition", definition_source=SOURCE_ID),
        term("Trade"),
        term("Quota", "rejected"),
    ]
    edges = [relationship("Trade", "Tariff", "approved")]
    if related:
        edges.append(relationship("Tariff", "Trade", "approved", kind="RELATED"))
    return write_domain(root, documents(terms, edges))


def _unreachable(connected: list[str]):
    """A ``get_neo4j_adapter`` that records the subject and fails like a stopped Neo4j."""

    def connect(subject_id):
        connected.append(subject_id)
        raise ConnectionError("connection refused")

    return connect


@pytest.fixture
def graph(monkeypatch):
    """The subject's adapter on an in-memory graph that the builder seeded."""
    adapter, session = fake_adapter()
    for name in ("Tariff", "Trade", "Quota"):
        session.add_concept(name, definition=f"{name} (builder)")
    session.add_prereq("Trade", "Tariff")
    driver = adapter.driver

    def connect(subject_id):
        assert subject_id == SUBJECT
        adapter.driver = driver  # close() drops it; the registry reconnects
        return adapter

    monkeypatch.setattr(domain_tool, "get_neo4j_adapter", connect)
    return session


@pytest.mark.parametrize("subject_id", ["us_history", "economics", "biology"])
def test_apply_connects_for_a_committed_domain_only_when_it_has_curated_entries(
    capsys, monkeypatch, subject_id
):
    """
    What the seed runs on the committed files. Without an approved, rejected or deprecated
    entry (every committed entry before the first review) apply does not connect and writes
    nothing. From the first reviewed entry on it asks for the subject's graph.
    """
    domain = load_domain(subject_id)
    connected: list[str] = []
    monkeypatch.setattr(domain_tool, "get_neo4j_adapter", _unreachable(connected))

    code, out = _run(capsys, "apply", "--subject", subject_id)

    if domain is not None and domain.has_curated_entries:
        assert (code, connected) == (1, [subject_id]), out
        assert "Neo4j is not reachable" in out
    else:
        assert (code, connected) == (0, []), out
        assert out.strip().endswith("nothing to apply")


def test_apply_without_a_domain_directory_or_curated_entries(capsys, offline, root):
    code, out = _run(capsys, "apply", "--subject", SUBJECT, "--root", str(root))
    assert (code, out) == (0, f"us_history: no domain directory under {root}; nothing to apply\n")

    write_domain(root, documents([term("Tariff"), term("Trade", "proposed")], []))
    code, out = _run(capsys, "apply", "--subject", SUBJECT, "--root", str(root))
    assert code == 0
    assert out == (
        "us_history: no approved, rejected or deprecated entries (2 terms, 0 relationships, "
        "1 sources; entries: 1 extracted, 1 proposed); nothing to apply\n"
    )


def test_apply_refuses_to_run_when_neo4j_is_unreachable(capsys, monkeypatch, root):
    _curated(root)

    def unreachable(subject_id):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(domain_tool, "get_neo4j_adapter", unreachable)

    code, out = _run(capsys, "apply", "--subject", SUBJECT, "--root", str(root))

    assert code == 1
    assert "us_history: Neo4j is not reachable at " in out and "nothing was applied" in out
    assert "error: ConnectionError: connection refused" in out
    assert "`make up`" in out


def test_apply_refuses_a_graph_without_concepts(capsys, graph, root):
    """`make domain-apply` before the first build must not leave a graph that looks seeded."""
    _curated(root)
    graph.concepts.clear()
    graph.edges.clear()

    for arguments in ([], ["--dry-run"]):
        code, out = _run(capsys, "apply", "--subject", SUBJECT, "--root", str(root), *arguments)

        assert code == 1
        assert "us_history: the graph has no concepts; nothing was applied" in out
        assert "hint: build it first: make build-kg SUBJECT=us_history" in out
    assert graph.writes == [] and graph.concepts == {}


def test_apply_runs_for_a_domain_whose_only_curated_entry_is_a_relationship(capsys, graph, root):
    write_domain(root, documents(None, [relationship("Quota", "Tariff", "approved")]))

    code, out = _run(capsys, "apply", "--subject", SUBJECT, "--root", str(root))

    assert code == 0, out
    assert "    merge PREREQ 'Quota' -> 'Tariff': provenance_source, review_status" in out
    assert "us_history: 1 operation(s) applied (0 removal(s), 0 skipped)" in out
    assert graph.edges[("Quota", "Tariff")]["provenance_source"] == "curated"


def test_apply_prints_every_operation_and_is_idempotent(capsys, graph, root):
    _curated(root)

    code, out = _run(capsys, "apply", "--subject", SUBJECT, "--root", str(root))

    assert code == 0, out
    assert out.splitlines() == [
        "us_history: applying",
        "    update concept 'Tariff': term_id, review_status, definition_source, definition "
        "(term 'tariff' is approved)",
        "    merge PREREQ 'Trade' -> 'Tariff': provenance_source, review_status, rule, "
        "evidence_source (the relationship is approved)",
        "    REMOVE concept 'Quota' and its edges (term 'quota' is rejected)",
        "    skipped RELATED 'Tariff' -> 'Trade' (approved): only PREREQ edges are applied",
        "us_history: 3 operation(s) applied (1 removal(s), 1 skipped)",
    ]
    assert graph.concepts["Tariff"]["definition"] == "a curated definition"
    assert "Quota" not in graph.concepts
    assert graph.edges[("Trade", "Tariff")]["provenance_source"] == "curated"
    applied = graph.snapshot()

    code, out = _run(capsys, "apply", "--subject", SUBJECT, "--root", str(root))

    assert code == 0
    assert "us_history: 0 operation(s) applied (0 removal(s), 1 skipped)" in out
    assert graph.snapshot() == applied and len(graph.writes) == 3


def test_apply_dry_run_prints_the_plan_without_writing(capsys, graph, root):
    _curated(root)
    before = graph.snapshot()

    code, out = _run(capsys, "apply", "--subject", SUBJECT, "--root", str(root), "--dry-run")

    assert code == 0
    assert "us_history: plan (dry run, nothing is written)" in out
    assert "    REMOVE concept 'Quota' and its edges (term 'quota' is rejected)" in out
    assert "us_history: 3 operation(s) planned (1 removal(s), 1 skipped)" in out
    assert graph.snapshot() == before and graph.writes == []


def test_apply_fails_on_an_invalid_domain_without_connecting(capsys, offline, root):
    write_domain(
        root, documents([term("Tariff", "approved", provenance={"origin": "builder"})], [])
    )

    code, out = _run(capsys, "apply", "--subject", SUBJECT, "--root", str(root))

    assert code == 1
    assert "the domain is invalid; nothing was applied (2 error(s))" in out
    assert "terms[0].provenance.reviewed_by (term 'tariff')" in out


def test_apply_fails_when_a_write_fails_or_does_not_take(capsys, graph, root, monkeypatch):
    _curated(root)
    from backend.app.kg.neo4j_adapter import Neo4jAdapter

    monkeypatch.setattr(Neo4jAdapter, "delete_concept", lambda self, name: None)
    code, out = _run(capsys, "apply", "--subject", SUBJECT, "--root", str(root))
    assert code == 1
    assert "us_history: 1 operation(s) are still pending after apply" in out
    assert "    REMOVE concept 'Quota' and its edges" in out

    def broken(self, name):
        raise RuntimeError("write failed")

    monkeypatch.setattr(Neo4jAdapter, "delete_concept", broken)
    code, out = _run(capsys, "apply", "--subject", SUBJECT, "--root", str(root))
    assert code == 1
    assert "us_history: apply failed; the graph may be partly updated" in out
    assert "error: RuntimeError: write failed" in out and "apply is idempotent" in out


@pytest.mark.parametrize("command", ["draft", "apply", "export"])
def test_unknown_subject_is_reported(capsys, offline, command):
    code, out = _run(capsys, command, "--subject", "astronomy")

    assert code == 1
    assert out.startswith("Unknown subject 'astronomy'\n")
    assert "us_history" in out


def test_the_tool_runs_as_a_script_and_its_exit_status_follows_the_result(root):
    """
    `python scripts/domain_tool.py` from the repository root, as make and the seed call it.
    Both stop on a non-zero exit status, so a failure has to reach the process.
    """
    command = [sys.executable, "scripts/domain_tool.py", "validate", "--root", str(root)]
    directory = write_domain(root)

    valid = subprocess.run(command, capture_output=True, text=True, timeout=50, check=False)

    assert valid.returncode == 0, valid.stdout + valid.stderr
    assert "us_history: valid (" in valid.stdout

    write_domain(root, documents([term("Tariff", review_status="accepted")], []))
    invalid = subprocess.run(command, capture_output=True, text=True, timeout=50, check=False)

    assert invalid.returncode == 1, invalid.stdout + invalid.stderr
    assert (
        f"{directory / 'dictionary.yaml'}: terms[0].review_status (term 'tariff')" in invalid.stdout
    )


# ---------------------------------------------------------------------------
# stack_check domain-overlay, seed_demo.sh and doctor.sh
# ---------------------------------------------------------------------------


@pytest.fixture
def overlay_graph(monkeypatch, root):
    """stack_check reads domains from ``root`` and the graph from an in-memory session."""
    adapter, session = fake_adapter()
    for name in ("Tariff", "Trade", "Quota"):
        session.add_concept(name, definition=f"{name} (builder)")
    session.add_prereq("Trade", "Tariff")
    monkeypatch.setattr("backend.app.domain.loader.default_domains_root", lambda: root)
    monkeypatch.setattr(
        "backend.app.kg.neo4j_adapter.get_neo4j_adapter", lambda subject_id: adapter
    )
    return adapter, session


def test_overlay_check_skips_subjects_without_curated_entries(capsys, monkeypatch, root):
    monkeypatch.setattr("backend.app.domain.loader.default_domains_root", lambda: root)
    monkeypatch.setattr("backend.app.kg.neo4j_adapter.get_neo4j_adapter", _no_neo4j)
    write_domain(root)  # extracted entries only; economics has no directory

    assert stack_check.main(["domain-overlay", "us_history", "economics"]) == 0
    assert capsys.readouterr().out == "Domain overlay: no curated entries to check\n"


def test_overlay_check_reads_the_graph_only_for_committed_domains_with_curated_entries(
    capsys, monkeypatch
):
    """What `make doctor` runs: no connection before the first review, a read after it."""
    subjects = ["us_history", "economics"]
    domains = {subject_id: load_domain(subject_id) for subject_id in subjects}
    curated = [s for s in subjects if (d := domains[s]) is not None and d.has_curated_entries]
    connected: list[str] = []
    monkeypatch.setattr("backend.app.kg.neo4j_adapter.get_neo4j_adapter", _unreachable(connected))

    code = stack_check.main(["domain-overlay", *subjects])
    out = capsys.readouterr().out

    assert connected == curated
    if curated:
        assert code == 2 and out.startswith(f"Domain overlay: {len(curated)} warning(s)\n")
    else:
        assert code == 0 and out == "Domain overlay: no curated entries to check\n"


def test_overlay_check_warns_when_curated_properties_are_absent(capsys, overlay_graph, root):
    """Someone ran `make build-kg` without `make domain-apply`: a warning, not a failure."""
    adapter, session = overlay_graph
    _curated(root, related=False)

    assert stack_check.main(["domain-overlay", "us_history", "economics"]) == 2
    out = capsys.readouterr().out
    assert out.startswith("Domain overlay: 1 warning(s)\n")
    assert "us_history: 3 curated change(s) are not in the graph (1 removal(s))" in out
    assert "Run: make domain-apply SUBJECT=us_history" in out
    assert session.writes == []  # the probe only reads

    apply_overlay(adapter, load_domain(SUBJECT, root))
    assert stack_check.main(["domain-overlay", "us_history"]) == 0
    assert capsys.readouterr().out == "Domain overlay is applied (us_history)\n"

    # A rebuild writes the builder's definition again: the warning comes back
    session.concepts["Tariff"]["definition"] = "Tariff (builder)"
    assert stack_check.main(["domain-overlay", "us_history"]) == 2
    assert "1 curated change(s) are not in the graph (0 removal(s))" in capsys.readouterr().out


def test_overlay_check_reads_the_graph_for_a_curated_relationship_alone(
    capsys, overlay_graph, root
):
    write_domain(root, documents(None, [relationship("Quota", "Tariff", "approved")]))

    assert stack_check.main(["domain-overlay", "us_history"]) == 2
    assert "1 curated change(s) are not in the graph (0 removal(s))" in capsys.readouterr().out


def test_overlay_check_warns_about_entries_the_overlay_skips(capsys, overlay_graph, root):
    """An approved entry that no apply can bring in must not read as applied."""
    adapter, session = overlay_graph
    _curated(root)  # with an approved RELATED entry
    apply_overlay(adapter, load_domain(SUBJECT, root))
    written = len(session.writes)

    assert stack_check.main(["domain-overlay", "us_history"]) == 2
    out = capsys.readouterr().out
    assert out.startswith("Domain overlay: 1 warning(s)\n")
    assert "us_history: 1 curated entr(ies) cannot be applied to this graph and are skipped" in out
    assert "scripts/domain_tool.py apply --subject us_history --dry-run" in out
    assert "make domain-apply" not in out  # nothing is pending: another apply changes nothing
    assert len(session.writes) == written


def test_overlay_check_warns_when_the_graph_is_not_built(capsys, overlay_graph, root):
    """Applying would be refused, so the hint is the seed, not `make domain-apply`."""
    _, session = overlay_graph
    session.concepts.clear()
    session.edges.clear()
    _curated(root)

    assert stack_check.main(["domain-overlay", "us_history"]) == 2
    out = capsys.readouterr().out
    assert "us_history: the graph has no concepts, so its curated entries are not applied" in out
    assert "Run: make seed" in out and "make domain-apply" not in out
    assert session.writes == []


def test_overlay_check_warns_about_a_name_that_is_not_a_subject_id(capsys, monkeypatch, root):
    monkeypatch.setattr("backend.app.domain.loader.default_domains_root", lambda: root)
    monkeypatch.setattr("backend.app.kg.neo4j_adapter.get_neo4j_adapter", _no_neo4j)

    assert stack_check.main(["domain-overlay", ".cache"]) == 2
    assert "'.cache' is not a subject id; nothing was checked" in capsys.readouterr().out


def test_overlay_check_warns_when_it_cannot_check(capsys, monkeypatch, root):
    monkeypatch.setattr("backend.app.domain.loader.default_domains_root", lambda: root)
    write_domain(root, documents([term("Tariff"), term("Tariff", id="t2")], []))
    _curated_economics = documents([term("Tariff", "rejected")], [], subject_id="economics")
    write_domain(root, _curated_economics, subject_id="economics")

    def unreachable(subject_id):
        raise ConnectionError("connection refused")

    monkeypatch.setattr("backend.app.kg.neo4j_adapter.get_neo4j_adapter", unreachable)

    assert stack_check.main(["domain-overlay", "us_history", "economics"]) == 2
    out = capsys.readouterr().out
    assert out.startswith("Domain overlay: 2 warning(s)\n")
    assert "us_history: the domain files are invalid (1 error(s)); run: poetry run python " in out
    assert "scripts/domain_tool.py validate --subject us_history" in out
    assert "economics: could not read the graph (ConnectionError: connection refused)" in out


def _code_lines(script: str) -> list[str]:
    lines = Path(script).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if not line.lstrip().startswith("#")]


def test_seed_applies_the_domain_after_the_graph_build():
    code = _code_lines("scripts/seed_demo.sh")
    apply_line = 'poetry run python scripts/domain_tool.py apply --subject "$subj"'

    assert code.count(apply_line) == 1
    build_line = next(i for i, line in enumerate(code) if "build_knowledge_graph.py" in line)
    index_line = next(i for i, line in enumerate(code) if "index_to_opensearch.py" in line)
    assert build_line < code.index(apply_line) < index_line
    # Outside the "build or skip" branch: it runs on every seed of the subject
    assert code[code.index(apply_line) - 1] in ("fi", "")


SEED_STATUS = {"us_history": "0 0", "economics": "12 34"}
"""What the recording `poetry` answers to seed-status: "<concepts> <chunks>" per subject."""


def _run_seed(tmp_path: Path, apply_status: int = 0) -> tuple[int, list[str]]:
    """
    Run scripts/seed_demo.sh in a copy, with a `poetry` that records its arguments.

    us_history has no concepts and economics is seeded (``SEED_STATUS``); the recorded
    `domain_tool.py apply` exits with ``apply_status``. Returns the seed's exit status and
    the recorded script calls.
    """
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    for name in ("lib.sh", "seed_demo.sh"):
        (root / "scripts" / name).write_text(Path("scripts", name).read_text(encoding="utf-8"))
    (root / "data" / "processed").mkdir(parents=True)
    for subject_id in SEED_STATUS:
        (root / "data" / "processed" / f"books_{subject_id}.jsonl").write_text("{}\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "poetry.log"
    answers = "".join(
        f'  *"seed-status --subject {subject_id}"*) echo "{status}" ;;\n'
        for subject_id, status in SEED_STATUS.items()
    )
    (bin_dir / "poetry").write_text(
        f'#!/bin/bash\necho "$*" >> "{log}"\ncase "$*" in\n{answers}'
        f'  *"domain_tool.py apply"*) exit {apply_status} ;;\nesac\nexit 0\n'
    )
    (bin_dir / "curl").write_text("#!/bin/bash\nexit 7\n")  # the API is not running
    for tool in ("poetry", "curl"):
        (bin_dir / tool).chmod(0o755)

    result = subprocess.run(
        ["bash", "scripts/seed_demo.sh"],
        cwd=root,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "NO_COLOR": "1"},
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    calls = [line for line in log.read_text(encoding="utf-8").splitlines() if "scripts/" in line]
    return result.returncode, calls


def test_seed_runs_apply_for_every_subject_built_or_not(tmp_path):
    """Apply runs once per subject, after the graph step and before the indexes."""
    code, calls = _run_seed(tmp_path)

    def position(fragment: str) -> int:
        matching = [index for index, call in enumerate(calls) if fragment in call]
        assert len(matching) == 1, (fragment, calls)
        return matching[0]

    assert code == 0, calls
    build = position("scripts/build_knowledge_graph.py --subject us_history")
    applied = position("scripts/domain_tool.py apply --subject us_history")
    assert build < applied < position("scripts/create_neo4j_indexes.py --subject us_history")
    # economics already has concepts: it is not rebuilt, and apply still runs
    assert not [call for call in calls if "build_knowledge_graph.py --subject economics" in call]
    assert position("scripts/domain_tool.py apply --subject economics") < position(
        "scripts/create_neo4j_indexes.py --subject economics"
    )


def test_seed_stops_when_apply_fails(tmp_path):
    """An invalid domain or an apply that does not take must not look like a seeded stack."""
    code, calls = _run_seed(tmp_path, apply_status=1)

    assert code != 0
    assert calls[-1].endswith("scripts/domain_tool.py apply --subject us_history")
    assert not [call for call in calls if "create_neo4j_indexes.py" in call]


def test_doctor_reports_the_overlay_check_as_a_warning():
    code = _code_lines("scripts/doctor.sh")
    probe = next(i for i, line in enumerate(code) if "stack_check.py domain-overlay" in line)

    assert '"${AKG_DEMO_SUBJECTS[@]}"' in code[probe]
    following = code[probe : probe + 6]
    assert 'report_probe warn "$rc" "$out"' in following
    assert not [line for line in following if line.startswith("report_probe fail")]


OVERLAY_WARNING = (
    "Domain overlay: 1 warning(s)\n"
    "  economics: 1 curated change(s) are not in the graph (0 removal(s)); it was probably "
    "rebuilt since the last apply. Run: make domain-apply SUBJECT=economics\n"
)
"""What the recording `poetry` prints for `stack_check.py domain-overlay` (it exits 2)."""

FAKE_COMPOSE_DOCKER = """#!/bin/bash
# `docker compose ... ps -q <service>` prints a container id for a service that has a state;
# `docker inspect --format <template> <id>` prints that state, or the container name.
for last in "$@"; do :; done
state_of() {
    case "$1" in
        *neo4j) printf '%s' "$FAKE_NEO4J" ;;
        *opensearch) printf '%s' "$FAKE_OPENSEARCH" ;;
    esac
}
case "$1 $*" in
    "compose "*" ps -q "*) if [ -n "$(state_of "$last")" ]; then echo "cid-$last"; fi ;;
    "inspect "*Health*) state_of "$last"; echo ;;
    "inspect "*) echo "/adaptive-kg-${last#cid-}" ;;
esac
exit 0
"""


def _run_doctor_stack(tmp_path: Path, neo4j: str, opensearch: str) -> tuple[str, list[str]]:
    """
    Run the "Stack" section of scripts/doctor.sh in a copy, with fake `docker` and `poetry`.

    ``neo4j`` and ``opensearch`` are the container states `docker inspect` reports
    ("healthy", "starting", "exited"); an empty string means the container does not exist.
    The `poetry` records its arguments and answers the probes: both subjects are seeded,
    the index fingerprints match and the overlay check warns (``OVERLAY_WARNING``).
    Returns the section's output and the arguments of the recorded `stack_check.py` calls.
    """
    doctor = Path("scripts/doctor.sh").read_text(encoding="utf-8")
    header = doctor.split('section "Tools"')[0]
    stack = doctor.split('section "Stack"')[1].split('section "Models"')[0]
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "lib.sh").write_text(Path("scripts/lib.sh").read_text(encoding="utf-8"))
    (root / "scripts" / "doctor-stack.sh").write_text(
        header + 'DOCKER_OK=true\nsection "Stack"' + stack
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "poetry.log"
    log.touch()  # `poetry` is not called at all while neither probe group may run
    (bin_dir / "docker").write_text(FAKE_COMPOSE_DOCKER)
    (bin_dir / "poetry").write_text(
        f'#!/bin/bash\necho "$*" >> "{log}"\ncase "$*" in\n'
        '  *"stack_check.py seed-status"*) echo "12 34" ;;\n'
        '  *"stack_check.py index-fingerprint"*) echo "Index fingerprints match" ;;\n'
        f"  *\"stack_check.py domain-overlay\"*) printf '%s' '{OVERLAY_WARNING}'; exit 2 ;;\n"
        "esac\nexit 0\n"
    )
    (bin_dir / "curl").write_text("#!/bin/bash\nexit 7\n")  # no API, no frontend
    for tool in ("docker", "poetry", "curl"):
        (bin_dir / tool).chmod(0o755)

    result = subprocess.run(
        ["bash", "scripts/doctor-stack.sh"],
        cwd=root,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "NO_COLOR": "1",
            "FAKE_NEO4J": neo4j,
            "FAKE_OPENSEARCH": opensearch,
        },
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    probe = "run python scripts/stack_check.py "
    recorded = log.read_text(encoding="utf-8").splitlines()
    return result.stdout, [line.removeprefix(probe) for line in recorded if line.startswith(probe)]


@pytest.mark.parametrize("opensearch", ["", "starting", "exited"])
def test_doctor_runs_the_overlay_check_without_opensearch(tmp_path, opensearch):
    """The check reads Neo4j only: with OpenSearch down the warning must still appear."""
    out, calls = _run_doctor_stack(tmp_path, neo4j="healthy", opensearch=opensearch)

    assert "✓ neo4j is healthy (adaptive-kg-neo4j)" in out
    assert "opensearch is healthy" not in out
    # The seed status and the index fingerprint need OpenSearch; the overlay check does not
    assert calls == ["domain-overlay us_history economics"]
    assert "  ⚠ Domain overlay: 1 warning(s)\n" in out
    assert (
        "      economics: 1 curated change(s) are not in the graph (0 removal(s)); it was "
        "probably rebuilt since the last apply. Run: make domain-apply SUBJECT=economics\n"
    ) in out


def test_doctor_runs_the_overlay_check_after_the_other_probes_on_a_healthy_stack(tmp_path):
    out, calls = _run_doctor_stack(tmp_path, neo4j="healthy", opensearch="healthy")

    assert calls == [
        "seed-status --subject us_history",
        "seed-status --subject economics",
        "index-fingerprint us_history economics",
        "domain-overlay us_history economics",
    ]
    assert "✓ economics seeded: 12 concepts in Neo4j, 34 chunks in OpenSearch" in out
    assert out.count("Domain overlay: 1 warning(s)") == 1


@pytest.mark.parametrize("neo4j", ["", "starting", "exited"])
def test_doctor_skips_the_overlay_check_while_neo4j_is_not_healthy(tmp_path, neo4j):
    out, calls = _run_doctor_stack(tmp_path, neo4j=neo4j, opensearch="healthy")

    assert "✓ opensearch is healthy (adaptive-kg-opensearch)" in out
    assert calls == []
    assert "Domain overlay" not in out
