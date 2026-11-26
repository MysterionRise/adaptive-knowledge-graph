"""
scripts/domain_tool.py export (#211): flat CSV and JSON.

Every domain is written under tmp_path; nothing connects to Neo4j. `validate` and `draft`
are tested in test_domain_tool.py, `apply` in test_domain_apply.py.
"""

import csv
import io
import json
from pathlib import Path

import pytest

from backend.tests.domain_builders import (
    REVIEWED,
    SOURCE_ID,
    SUBJECT,
    documents,
    relationship,
    term,
    write_domain,
)
from scripts import domain_tool

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Fail the test if the tool asks for a Neo4j adapter."""
    monkeypatch.setattr(
        domain_tool, "get_neo4j_adapter", lambda subject_id: pytest.fail("connected to Neo4j")
    )


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "domains"
    path.mkdir()
    return path


def _run(capsys, *argv: str) -> tuple[int, str]:
    code = domain_tool.main(list(argv))
    return code, capsys.readouterr().out


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def _reviewed_domain(root: Path) -> Path:
    terms = [
        term(
            "Tariff",
            "approved",
            definition="a tax on imported goods",
            definition_source=SOURCE_ID,
            aliases=["Duty", "Customs Duty"],
            scope="trade policy",
            context_terms=["import"],
            provenance={"origin": "builder", "method": "key_term", "note": "checked", **REVIEWED},
        ),
        term("Trade"),
    ]
    return write_domain(root, documents(terms, [relationship("Trade", "Tariff", "approved")]))


def test_export_csv_has_the_documented_columns(capsys, root):
    _reviewed_domain(root)

    code, out = _run(capsys, "export", "--subject", SUBJECT, "--root", str(root))

    assert code == 0
    rows = list(csv.reader(io.StringIO(out)))
    assert rows[0] == [
        "subject_id",
        "id",
        "name",
        "aliases",
        "definition",
        "definition_source",
        "scope",
        "context_terms",
        "review_status",
        "provenance_origin",
        "provenance_method",
        "provenance_module_id",
        "provenance_reviewed_by",
        "provenance_reviewed_on",
        "provenance_note",
    ]
    assert rows[1] == [
        SUBJECT,
        "tariff",
        "Tariff",
        "Duty; Customs Duty",
        "a tax on imported goods",
        SOURCE_ID,
        "trade policy",
        "import",
        "approved",
        "builder",
        "key_term",
        "",
        "project maintainer",
        "2026-11-11",
        "checked",
    ]
    assert rows[2][:9] == [SUBJECT, "trade", "Trade", "", "", "", "", "", "extracted"]
    assert len(rows) == 3


def test_export_csv_of_relationships_and_sources(capsys, root):
    _reviewed_domain(root)

    _, edges = _run(
        capsys, "export", "--subject", SUBJECT, "--root", str(root), "--table", "relationships"
    )
    _, sources = _run(
        capsys, "export", "--subject", SUBJECT, "--root", str(root), "--table", "sources"
    )

    edge_rows = list(csv.DictReader(io.StringIO(edges)))
    assert list(edge_rows[0]) == list(domain_tool.RELATIONSHIP_COLUMNS)
    assert edge_rows[0]["review_status"] == "approved" and edge_rows[0]["type"] == "PREREQ"
    assert (edge_rows[0]["source"], edge_rows[0]["target"]) == ("Trade", "Tariff")
    assert edge_rows[0]["confidence"] == "0.8"
    source_rows = list(csv.DictReader(io.StringIO(sources)))
    assert list(source_rows[0]) == list(domain_tool.SOURCE_COLUMNS)
    assert source_rows[0]["id"] == SOURCE_ID and source_rows[0]["review_status"] == "approved"


def test_export_json_holds_flat_rows_for_every_table(capsys, root, tmp_path):
    _reviewed_domain(root)
    out_file = tmp_path / "domain.json"

    code, out = _run(
        capsys,
        "export",
        "--subject",
        SUBJECT,
        "--root",
        str(root),
        "--format",
        "json",
        "--out",
        str(out_file),
    )

    assert code == 0 and out == f"us_history: wrote {out_file}\n"
    document = json.loads(out_file.read_text(encoding="utf-8"))
    assert list(document) == ["subject_id", "schema_version", "terms", "relationships", "sources"]
    assert document["subject_id"] == SUBJECT and document["schema_version"] == 1
    for table, columns in domain_tool.TABLE_COLUMNS.items():
        assert [list(row) for row in document[table]] == [list(columns)] * len(document[table])
        assert not [v for row in document[table] for v in row.values() if isinstance(v, dict)]
    assert "review_status" in domain_tool.TERM_COLUMNS
    assert document["terms"][0]["aliases"] == ["Duty", "Customs Duty"]  # lists stay lists
    assert document["terms"][0]["provenance_reviewed_on"] == "2026-11-11"

    arguments = ["export", "--subject", SUBJECT, "--root", str(root), "--format", "json"]
    _, only_terms = _run(capsys, *arguments, "--table", "terms")
    assert list(json.loads(only_terms)) == ["subject_id", "schema_version", "terms"]


def test_export_fails_without_a_valid_domain(capsys, root):
    code, out = _run(capsys, "export", "--subject", "biology", "--root", str(root))
    assert code == 1 and "biology: no domain directory" in out

    write_domain(root, documents([term("Tariff"), term("Tariff", id="t2")], []))
    code, out = _run(capsys, "export", "--subject", SUBJECT, "--root", str(root))
    assert code == 1 and "the domain is invalid; nothing was exported" in out
