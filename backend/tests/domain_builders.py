"""
Builders for domain-artifact tests (#211): a small valid domain in a temporary directory
and an in-memory Neo4j session that executes the overlay's queries.

Nothing here reads or writes ``data/domains`` or connects to a service.
"""

from pathlib import Path
from typing import Any

import yaml

from backend.app.core.subjects import slug
from backend.app.domain.loader import DOMAIN_FILES
from backend.app.domain.models import Domain
from backend.app.kg.neo4j_adapter import Neo4jAdapter

SUBJECT = "us_history"
SOURCE_ID = "demo-book"
REVIEWED = {"reviewed_by": "project maintainer", "reviewed_on": "2026-11-11"}
CURATED_STATUSES = ("approved", "rejected", "deprecated")


def provenance(status: str, **fields: Any) -> dict[str, Any]:
    """Builder provenance for an extracted entry; a reviewed one records who and when."""
    if status == "extracted":
        return {"origin": "builder", "method": "key_term", "module_id": "m1", **fields}
    reviewed = REVIEWED if status in CURATED_STATUSES else {}
    return {"origin": "reviewer", **reviewed, **fields}


def term(name: str, status: str = "extracted", **fields: Any) -> dict[str, Any]:
    """One dictionary.yaml entry; ``fields`` override or add keys."""
    entry: dict[str, Any] = {
        "id": slug(name),
        "name": name,
        "aliases": [],
        "definition": None,
        "definition_source": None,
        "review_status": status,
        "provenance": provenance(status),
    }
    entry.update(fields)
    return entry


def relationship(
    source: str, target: str, status: str = "extracted", kind: str = "PREREQ", **fields: Any
) -> dict[str, Any]:
    """One relationships.yaml entry."""
    entry: dict[str, Any] = {
        "source": source,
        "target": target,
        "type": kind,
        "rule": "glossary_definition",
        "evidence_source": SOURCE_ID,
        "confidence": 0.8,
        "review_status": status,
        "provenance": provenance(status),
    }
    entry.update(fields)
    return entry


def source(source_id: str = SOURCE_ID, **fields: Any) -> dict[str, Any]:
    """One sources.yaml entry."""
    entry: dict[str, Any] = {
        "id": source_id,
        "title": "Demo Book",
        "connector": "github_raw",
        "uri": "https://example.org/demo-book",
        "license": "CC BY 4.0",
        "steward": "project maintainer",
        "review_status": "approved",
    }
    entry.update(fields)
    return entry


def documents(
    terms: list[dict[str, Any]] | None = None,
    relationships: list[dict[str, Any]] | None = None,
    sources: list[dict[str, Any]] | None = None,
    subject_id: str = SUBJECT,
) -> dict[str, dict[str, Any]]:
    """The four files of a valid domain as mappings, by file name."""
    if terms is None:
        terms = [
            term(
                "Tariff",
                definition="a tax on imported goods",
                definition_source=SOURCE_ID,
                aliases=["Tariffs"],
            ),
            term("Trade"),
            term("Quota"),
        ]
    if relationships is None:
        relationships = [relationship("Trade", "Tariff")]
    return {
        "domain.yaml": {
            "schema_version": 1,
            "subject_id": subject_id,
            "status": "draft",
            "steward": "project maintainer",
            "review_cadence": None,
            "accuracy_bar": None,
        },
        "dictionary.yaml": {"schema_version": 1, "terms": terms},
        "relationships.yaml": {"schema_version": 1, "relationships": relationships},
        "sources.yaml": {
            "schema_version": 1,
            "sources": sources if sources is not None else [source()],
        },
    }


def write_domain(
    root: Path, files: dict[str, dict[str, Any]] | None = None, subject_id: str = SUBJECT
) -> Path:
    """Write a domain's files under ``root/<subject_id>``; returns that directory."""
    files = files if files is not None else documents(subject_id=subject_id)
    assert set(files) == set(DOMAIN_FILES)
    directory = root / subject_id
    directory.mkdir(parents=True, exist_ok=True)
    for name, document in files.items():
        (directory / name).write_text(
            yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
    return directory


def make_domain(
    root: Path,
    terms: list[dict[str, Any]] | None = None,
    relationships: list[dict[str, Any]] | None = None,
) -> Domain:
    """Write a domain and load it; fails the test when it does not validate."""
    from backend.app.domain.loader import load_domain

    write_domain(root, documents(terms, relationships))
    domain = load_domain(SUBJECT, root)
    assert domain is not None
    return domain


class FakeGraphSession:
    """
    A Neo4j session that keeps concepts and PREREQ edges in memory.

    ``run`` recognises the overlay queries of ``Neo4jAdapter`` by their text and executes
    them as Neo4j would: ``SET x += $properties`` sets each property and a ``None`` value
    removes it; ``MERGE`` creates what is missing; ``DETACH DELETE`` drops a concept with
    its edges. Every call is recorded in ``calls`` as (query, parameters).
    """

    def __init__(self, label: str):
        self.label = label
        self.concepts: dict[str, dict[str, Any]] = {}
        self.edges: dict[tuple[str, str], dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> "FakeGraphSession":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    # -- seeding, as the builder would persist

    def add_concept(self, name: str, **properties: Any) -> None:
        self.concepts[name] = {"aliases": [], **properties}

    def add_prereq(self, source_name: str, target_name: str, **properties: Any) -> None:
        self.edges[(source_name, target_name)] = {
            "weight": 0.8,
            "confidence": 0.8,
            "provenance_source": "glossary",
            **properties,
        }

    @property
    def writes(self) -> list[tuple[str, dict[str, Any]]]:
        return [call for call in self.calls if "MERGE" in call[0] or "DELETE" in call[0]]

    def snapshot(self) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
        """A deep copy of the node and edge property sets."""
        return (
            {name: dict(properties) for name, properties in self.concepts.items()},
            {edge: dict(properties) for edge, properties in self.edges.items()},
        )

    # -- the queries

    @staticmethod
    def _set(target: dict[str, Any], properties: dict[str, Any]) -> None:
        for key, value in properties.items():
            if value is None:
                target.pop(key, None)
            else:
                target[key] = value

    def run(self, query: str, **parameters: Any) -> list[dict[str, Any]]:
        self.calls.append((query, parameters))
        assert f":{self.label}" in query, "every overlay query is scoped to the subject's label"
        if "DETACH DELETE" in query:
            name = parameters["name"]
            self.concepts.pop(name, None)
            self.edges = {edge: p for edge, p in self.edges.items() if name not in edge}
        elif "MERGE (c:" in query:
            created = {
                "key_term": False,
                "frequency": 0,
                "importance_score": 0.0,
                "source_modules": [],
                "aliases": [],
            }
            concept = self.concepts.setdefault(parameters["name"], created)
            self._set(concept, parameters["properties"])
        elif "MERGE (a)-[r:PREREQ]->(b)" in query:
            edge = (parameters["source"], parameters["target"])
            if edge[0] in self.concepts and edge[1] in self.concepts:
                properties = self.edges.setdefault(edge, {"weight": parameters["weight"]})
                self._set(properties, parameters["properties"])
        elif "DELETE r" in query:
            self.edges.pop((parameters["source"], parameters["target"]), None)
        elif "properties(r) AS properties" in query:
            return [
                {"source": edge[0], "target": edge[1], "properties": dict(properties)}
                for edge, properties in self.edges.items()
            ]
        elif "c.term_id AS term_id" in query:
            return [
                {
                    "name": name,
                    "definition": properties.get("definition"),
                    "aliases": list(properties.get("aliases") or []),
                    "term_id": properties.get("term_id"),
                    "review_status": properties.get("review_status"),
                    "definition_source": properties.get("definition_source"),
                }
                for name, properties in self.concepts.items()
            ]
        else:
            raise AssertionError(f"unexpected query: {query}")
        return []


def fake_adapter(label_prefix: str = SUBJECT) -> tuple[Neo4jAdapter, FakeGraphSession]:
    """A real ``Neo4jAdapter`` whose driver hands out one ``FakeGraphSession``."""
    from unittest.mock import MagicMock

    adapter = Neo4jAdapter(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="password",
        database="neo4j",
        label_prefix=label_prefix,
    )
    session = FakeGraphSession(f"{label_prefix}_Concept")
    driver = MagicMock(name="neo4j_driver")
    driver.session.return_value = session
    adapter.driver = driver
    return adapter, session
