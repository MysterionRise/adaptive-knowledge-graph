"""
Tests for read-only natural-language graph queries (backend/app/kg/cypher_qa.py).

Covers the Cypher validator, READ-transaction execution and the real GraphCypherQAChain
wiring, using a fake LLM and a mocked Neo4j driver: no services are needed.
"""

from unittest.mock import MagicMock, patch

import neo4j
import pytest
from langchain_neo4j import GraphCypherQAChain

from backend.app.core.exceptions import LLMGenerationError, Neo4jConnectionError
from backend.app.kg.cypher_qa import (
    MAX_CYPHER_CHARS,
    CypherQAService,
    CypherValidationError,
    ReadOnlyNeo4jGraph,
    validate_cypher_read_only,
)

pytestmark = pytest.mark.unit

READ_QUERIES = [
    "MATCH (c:Concept) WHERE toLower(c.name) CONTAINS 'revolution' RETURN c.name LIMIT 10",
    "MATCH (c:Concept {name: 'Photosynthesis'})<-[:PREREQ]-(p:Concept) RETURN p.name AS prerequisite",
    "MATCH path = (s:Concept {name: $concept})<-[:PREREQ*1..3]-(p:Concept) "
    "RETURN [n IN nodes(path) | n.name] AS learning_path",
    "MATCH (m:Module)-[:COVERS]->(c:Concept) RETURN m.title AS module, collect(c.name) AS concepts",
    "OPTIONAL MATCH (c:Concept) RETURN c",
    "WITH 1 AS x RETURN x",
    "UNWIND [1, 2] AS x RETURN x",
    "RETURN 1",
    "EXPLAIN MATCH (n) RETURN n",
    "profile MATCH (n) RETURN count(n)",
    "MATCH (n) RETURN n;",
    "  // a leading comment\nMATCH (n) RETURN n LIMIT 1",
    "/* block */ MATCH (n) RETURN n LIMIT 1",
    "CALL db.labels() YIELD label RETURN label",
    "CALL apoc.meta.data() YIELD label, property RETURN label, property",
    'CALL db.index.fulltext.queryNodes("concept_fulltext", "photo") YIELD node, score '
    "RETURN node.name, score",
    "RETURN apoc.meta.cypher.type(1) AS type",
]

BLOCKED_QUERIES = [
    # Write clauses
    pytest.param("CREATE (n:Concept {name: 'x'})", id="create"),
    pytest.param("MERGE (n:Concept {name: 'x'})", id="merge"),
    pytest.param("MATCH (n) DELETE n", id="delete"),
    pytest.param("MATCH (n) DETACH DELETE n", id="detach-delete"),
    pytest.param("MATCH (n) SET n.name = 'x'", id="set"),
    pytest.param("MATCH (n) REMOVE n.name", id="remove"),
    pytest.param("DROP INDEX concept_fulltext", id="drop"),
    pytest.param("INSERT (n:Concept)", id="gql-insert"),
    pytest.param("MATCH (n) FOREACH (x IN [1] | CREATE (:Concept))", id="foreach"),
    pytest.param("MATCH (n) WITH n MATCH (m) MERGE (n)-[:RELATED]->(m)", id="merge-later"),
    # APOC procedures other than apoc.meta.*
    pytest.param(
        'CALL apoc.periodic.iterate("MATCH (n) RETURN n", "DETACH DELETE n", {})',
        id="apoc-periodic-iterate",
    ),
    pytest.param("CALL apoc.periodic.iterate('MATCH (n) RETURN n', 'n', {})", id="apoc-periodic"),
    pytest.param("CALL apoc.schema.assert({}, {}, true)", id="apoc-schema-assert"),
    pytest.param(
        "MATCH (a:Concept), (b:Concept) CALL apoc.refactor.mergeNodes([a, b]) YIELD node "
        "RETURN node",
        id="apoc-refactor-merge-nodes",
    ),
    pytest.param(
        "CALL apoc.load.json('http://169.254.169.254/') YIELD value RETURN value", id="apoc-load"
    ),
    pytest.param("CALL apoc.util.sleep(100000)", id="apoc-sleep"),
    pytest.param(
        "RETURN apoc.cypher.runFirstColumnSingle('MATCH (n) RETURN count(n)', {})",
        id="apoc-cypher-function",
    ),
    pytest.param(
        "CALL apoc.meta.data() YIELD label CALL apoc.create.node(['X'], {}) YIELD node RETURN node",
        id="second-call-checked",
    ),
    pytest.param(
        "MATCH (n) CALL apoc.meta.data() YIELD value WITH 1 AS x "
        "CALL apoc.load.json('file:///etc/passwd') YIELD value RETURN value",
        id="allowed-call-then-apoc-load",
    ),
    # Comment, whitespace, case and quoting tricks
    pytest.param("CALL/**/apoc.schema.assert({}, {}, true)", id="block-comment-separator"),
    pytest.param("CALL apoc . schema . assert({}, {}, true)", id="spaced-namespace"),
    pytest.param("CALL `apoc`.`schema`.`assert`({}, {}, true)", id="backtick-namespace"),
    pytest.param("CALL `apoc.schema.assert`({}, {}, true)", id="backtick-whole-name"),
    pytest.param("call apoc.schema.assert({}, {}, true)", id="lowercase"),
    pytest.param("CALL\tapoc.refactor.mergeNodes([])", id="tab-separator"),
    pytest.param("MATCH (n) // looks harmless\nDETACH DELETE n", id="line-comment"),
    pytest.param("MATCH (n) /* x */ DETACH /* y */ DELETE n", id="block-comments"),
    pytest.param("MATCH (n)\nDETACH\tDELETE n", id="newline-tab"),
    pytest.param(
        "MATCH (n) WHERE n.url = 'http://x' DETACH DELETE n", id="double-slash-in-literal"
    ),
    pytest.param(
        "MATCH (n) WITH n, '\\'' AS q DETACH DELETE n RETURN '\\'' AS r",
        id="escaped-quote-literal-trick",
    ),
    pytest.param("CALL\u200bapoc.schema.assert({}, {}, true)", id="zero-width-separator"),
    # Other procedures, subqueries and transactions
    pytest.param("CALL dbms.killQuery('query-1')", id="dbms-procedure"),
    pytest.param("CALL db.createLabel('Secret')", id="db-write-procedure"),
    pytest.param("CALL { MATCH (n) RETURN n } RETURN n", id="call-subquery"),
    pytest.param("MATCH (n) CALL (n) { RETURN n AS m } RETURN m", id="scoped-subquery"),
    pytest.param(
        "MATCH (n) CALL { WITH n RETURN n AS m } IN TRANSACTIONS RETURN m", id="in-transactions"
    ),
    # Data loading, administration, database switching, multiple statements
    pytest.param("LOAD CSV FROM 'file:///etc/passwd' AS row RETURN row", id="load-csv"),
    pytest.param("MATCH (n) WITH n LOAD CSV FROM 'http://x/a.csv' AS r RETURN r", id="load-later"),
    pytest.param("SHOW USERS", id="show"),
    pytest.param("PROFILE SHOW SETTINGS", id="profile-show"),
    pytest.param("USE system SHOW USERS", id="use"),
    pytest.param("MATCH (n) RETURN n UNION USE other MATCH (m) RETURN m", id="union-use"),
    pytest.param("TERMINATE TRANSACTIONS 'neo4j-transaction-1'", id="terminate"),
    pytest.param("GRANT ROLE admin TO bob", id="grant"),
    pytest.param("ALTER USER neo4j SET PASSWORD 'x'", id="alter"),
    pytest.param("CYPHER 5 MATCH (n) RETURN n", id="cypher-prefix"),
    pytest.param("MATCH (n) RETURN n; MATCH (m) RETURN m", id="two-statements"),
    pytest.param("", id="empty"),
    pytest.param("   ", id="blank"),
]


class TestValidateCypherReadOnly:
    """validate_cypher_read_only: allowlist of read clauses and procedures."""

    @pytest.mark.parametrize("cypher", READ_QUERIES)
    def test_allows_read_queries(self, cypher):
        validate_cypher_read_only(cypher)

    @pytest.mark.parametrize("cypher", BLOCKED_QUERIES)
    def test_rejects_non_read_queries(self, cypher):
        with pytest.raises(CypherValidationError):
            validate_cypher_read_only(cypher)

    @pytest.mark.parametrize(
        ("cypher", "offender"),
        [
            (
                "MATCH (n) CALL apoc.meta.data() YIELD label WITH 1 AS x "
                "CALL dbms.listConfig() YIELD name RETURN name",
                "dbms.listConfig",
            ),
            (
                "CALL db.labels() YIELD label CALL db.propertyKeys() YIELD propertyKey "
                "CALL db.createLabel('X') RETURN label",
                "db.createLabel",
            ),
        ],
    )
    def test_checks_every_call_not_just_the_first(self, cypher, offender):
        """Allowed procedures earlier in a statement do not vouch for later CALLs.

        Only the CALL allowlist can reject these statements (no forbidden clause or
        non-meta APOC namespace appears), so the error names the offending procedure.
        """
        with pytest.raises(CypherValidationError, match=f"CALL {offender} is not permitted"):
            validate_cypher_read_only(cypher)

    def test_scans_string_literals(self):
        """Regression: literals used to be stripped first, so this query passed."""
        with pytest.raises(CypherValidationError, match="DETACH"):
            validate_cypher_read_only(
                'CALL apoc.periodic.iterate("MATCH (n) RETURN n", "DETACH DELETE n", {})'
            )

    def test_rejects_overlong_statement(self):
        cypher = "MATCH (n) RETURN n" + " " * MAX_CYPHER_CHARS
        with pytest.raises(CypherValidationError, match="too long"):
            validate_cypher_read_only(cypher)

    def test_validation_error_is_a_value_error(self):
        """The /graph/query route maps ValueError to HTTP 400."""
        assert issubclass(CypherValidationError, ValueError)


@pytest.fixture
def graph_and_driver(make_neo4j_driver):
    """A ReadOnlyNeo4jGraph on a mocked driver returning one record."""
    driver = make_neo4j_driver([{"name": "Photosynthesis"}])
    with patch("neo4j.GraphDatabase.driver", return_value=driver):
        graph = ReadOnlyNeo4jGraph(
            url="bolt://neo4j.test:7687",
            username="neo4j",
            password="test-password",
            timeout=12.5,
            refresh_schema=False,
        )
    return graph, driver


class TestReadOnlyNeo4jGraph:
    """Every statement runs in a managed READ transaction."""

    def test_query_runs_in_read_transaction(self, graph_and_driver):
        graph, driver = graph_and_driver
        cypher = "MATCH (c:Concept) RETURN c.name AS name"

        rows = graph.query(cypher, {"limit": 5})

        assert rows == [{"name": "Photosynthesis"}]
        driver.session.assert_called_once_with(
            database="neo4j", default_access_mode=neo4j.READ_ACCESS
        )
        driver.mock_session.execute_read.assert_called_once()
        driver.mock_session.execute_write.assert_not_called()
        driver.mock_session.run.assert_not_called()
        driver.execute_query.assert_not_called()
        driver.mock_tx.run.assert_called_once_with(cypher, {"limit": 5})

    def test_transaction_has_timeout_and_row_cap(self, graph_and_driver):
        graph, driver = graph_and_driver

        graph.query("MATCH (c:Concept) RETURN c")

        work = driver.mock_session.execute_read.call_args.args[0]
        assert work.timeout == 12.5
        driver.mock_tx.run.return_value.fetch.assert_called_once_with(graph.max_rows)

    def test_rejected_query_never_reaches_neo4j(self, graph_and_driver):
        graph, driver = graph_and_driver

        with pytest.raises(CypherValidationError):
            graph.query("MATCH (n) DETACH DELETE n")

        driver.session.assert_not_called()

    def test_schema_refresh_is_trusted_but_still_read_only(self, make_neo4j_driver):
        driver = make_neo4j_driver([])
        with patch("neo4j.GraphDatabase.driver", return_value=driver):
            graph = ReadOnlyNeo4jGraph(
                url="bolt://neo4j.test:7687",
                username="neo4j",
                password="test-password",
                refresh_schema=False,
            )

        graph.refresh_schema()

        executed = [call.args[0] for call in driver.mock_tx.run.call_args_list]
        # langchain's own introspection ran, including statements the validator rejects
        assert "SHOW CONSTRAINTS" in executed
        assert any("apoc.meta.data()" in cypher for cypher in executed)
        assert driver.mock_session.execute_read.call_count == len(executed)
        driver.mock_session.execute_write.assert_not_called()
        # the trusted context ends with the refresh
        with pytest.raises(CypherValidationError):
            graph.query("SHOW CONSTRAINTS")


class TestCypherQAService:
    """CypherQAService with the real GraphCypherQAChain."""

    def test_real_chain_builds_with_dangerous_requests_acknowledged(self, make_cypher_qa_service):
        """langchain-neo4j refuses to build the chain without allow_dangerous_requests."""
        service, _ = make_cypher_qa_service("MATCH (c:Concept) RETURN c.name AS name")

        chain = service.chain

        assert isinstance(chain, GraphCypherQAChain)
        assert chain.allow_dangerous_requests is True
        assert chain.graph is service.graph

    def test_query_executes_generated_cypher_read_only(self, make_cypher_qa_service):
        cypher = "MATCH (c:Concept) RETURN c.name AS name LIMIT 5"
        service, driver = make_cypher_qa_service(
            cypher, "Photosynthesis is a concept.", records=[{"name": "Photosynthesis"}]
        )

        result = service.query("Which concepts exist?")

        assert result == {
            "question": "Which concepts exist?",
            "cypher": cypher,
            "result": "Photosynthesis is a concept.",
            "answer": "Photosynthesis is a concept.",
        }
        driver.session.assert_called_once_with(
            database="neo4j", default_access_mode=neo4j.READ_ACCESS
        )
        driver.mock_tx.run.assert_called_once_with(cypher, {})

    @pytest.mark.parametrize(
        "generated",
        [
            "MATCH (n) DETACH DELETE n",
            'CALL apoc.periodic.iterate("MATCH (n) RETURN n", "DETACH DELETE n", {})',
            "CALL apoc.schema.assert({}, {}, true)",
        ],
    )
    def test_generated_write_raises_validation_error(self, make_cypher_qa_service, generated):
        """Blocked Cypher propagates (it used to be swallowed into an HTTP 200)."""
        service, driver = make_cypher_qa_service(generated)

        with pytest.raises(CypherValidationError):
            service.query("Tidy up the graph for me")

        driver.session.assert_not_called()

    def test_neo4j_errors_propagate(self, make_cypher_qa_service):
        service, driver = make_cypher_qa_service("MATCH (c:Concept) RETURN c")
        driver.mock_session.execute_read.side_effect = neo4j.exceptions.ServiceUnavailable("down")

        with pytest.raises(neo4j.exceptions.ServiceUnavailable):
            service.query("Which concepts exist?")

    def test_other_value_errors_are_not_reported_as_validation_errors(self):
        """langchain reports LLM failures as ValueError; they must not become a 400."""
        service = CypherQAService()
        service._chain = MagicMock()
        service._chain.invoke.side_effect = ValueError("Ollama call failed with status code 500")

        with pytest.raises(LLMGenerationError) as excinfo:
            service.query("Which concepts exist?")

        assert not isinstance(excinfo.value, ValueError)

    def test_graph_connection_failure_is_not_a_value_error(self):
        driver = MagicMock()
        driver.verify_connectivity.side_effect = neo4j.exceptions.ServiceUnavailable("down")
        service = CypherQAService(
            neo4j_uri="bolt://neo4j.test:7687", neo4j_user="neo4j", neo4j_password="pw"
        )

        with (
            patch("neo4j.GraphDatabase.driver", return_value=driver),
            pytest.raises(Neo4jConnectionError),
        ):
            _ = service.graph

        assert not issubclass(Neo4jConnectionError, ValueError)

    def test_execute_cypher_validates_before_connecting(self):
        service = CypherQAService()

        with (
            patch("neo4j.GraphDatabase.driver") as driver_factory,
            pytest.raises(CypherValidationError),
        ):
            service.execute_cypher("MATCH (n) DETACH DELETE n")

        driver_factory.assert_not_called()

    def test_close_closes_the_driver(self, make_cypher_qa_service):
        service, driver = make_cypher_qa_service()

        service.close()

        driver.close.assert_called_once()
        assert service._graph is None


class TestLoggingUntrustedText:
    """Errors and Cypher often contain braces (JSON bodies, map literals).

    Logging them must neither raise (loguru formats the message when it gets extra
    arguments, so braces interpolated into the format string raised KeyError) nor drop
    the traceback.
    """

    ERROR_TEXT = 'Ollama call failed with status code 500. Details: {"code": "x"}'

    def test_chain_error_with_braces_is_logged_with_traceback(self, captured_logs):
        service = CypherQAService()
        service._chain = MagicMock()
        service._chain.invoke.side_effect = ValueError(self.ERROR_TEXT)

        with pytest.raises(LLMGenerationError):
            service.query("Which concepts exist?")

        record = next(m.record for m in captured_logs if "CypherQA chain failed" in m)
        assert '{"code": "x"}' in record["message"]
        assert record["exception"] is not None

    def test_preview_error_with_braces_is_logged_with_traceback(self, captured_logs):
        service = CypherQAService()
        service._graph = MagicMock(schema="")
        service._llm = MagicMock()
        service._llm.invoke.side_effect = RuntimeError(self.ERROR_TEXT)

        assert service.generate_cypher_only("Which concepts exist?") is None

        record = next(m.record for m in captured_logs if "Cypher generation error" in m)
        assert '{"code": "x"}' in record["message"]
        assert record["exception"] is not None

    def test_rejected_cypher_with_map_literal_is_logged(self, graph_and_driver, captured_logs):
        graph, _ = graph_and_driver

        with pytest.raises(CypherValidationError):
            graph.query('MATCH (c:Concept {name: "x"}) DETACH DELETE c')

        assert any('{name: "x"}' in message for message in captured_logs)

    def test_question_with_braces_is_logged(self, make_cypher_qa_service, captured_logs):
        service, _ = make_cypher_qa_service("MATCH (c:Concept) RETURN c.name AS name", "ok")

        service.query('Which concepts match {"code": "x"}?')

        assert any('{"code": "x"}' in message for message in captured_logs)
