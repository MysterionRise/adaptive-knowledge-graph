"""
Natural language to Cypher query generation using LangChain.

Implements GraphCypherQAChain for text-to-Cypher translation,
allowing users to query the knowledge graph in plain English.

LLM-generated Cypher is untrusted input. This module enforces two controls:

1. ``validate_cypher_read_only`` rejects write and admin clauses, subqueries, multiple
   statements and any procedure call or APOC use outside a small read-only allowlist,
   before anything reaches Neo4j. Every ``CALL`` in the statement is checked.
2. ``ReadOnlyNeo4jGraph`` runs every statement in a READ transaction
   (``session.execute_read``) with a timeout and a row cap; Neo4j rejects writes in
   READ transactions.

Defence in depth outside this code: the bundled compose stack restricts Neo4j to the
``apoc.meta.*`` procedures (``dbms.security.procedures.allowlist``, see #102). Other
deployments should set the same allowlist; the two controls above do not depend on it.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Any

import neo4j
from langchain_core.prompts import PromptTemplate
from langchain_neo4j import GraphCypherQAChain, Neo4jGraph
from langchain_neo4j.graphs.neo4j_graph import value_sanitize
from loguru import logger

from backend.app.core.exceptions import LLMGenerationError, Neo4jConnectionError
from backend.app.core.settings import settings

# Transaction timeout for every statement sent through ReadOnlyNeo4jGraph.
QUERY_TIMEOUT_SECONDS = 30.0
# Records kept from a generated query (the chain passes only its top_k to the LLM).
MAX_RESULT_ROWS = 100
# Generated statements are short; anything longer is rejected before it is parsed.
MAX_CYPHER_CHARS = 10_000


class CypherValidationError(ValueError):
    """Cypher that is not a permitted read-only query.

    A ``ValueError``, so the ``/graph/query`` route maps it to HTTP 400.
    """


class GeneratedCypherError(LLMGenerationError):
    """Neo4j rejected the Cypher the model generated (syntax, types, unknown names).

    Invalid LLM output: the API contract for that is HTTP 502.
    """


# LLM output often arrives as a Markdown block. langchain's extract_cypher() drops the
# fences but keeps the language tag ("cypher\nMATCH ..."), so fences and a tag line that
# is exactly "cypher" are stripped before validation and execution. Nothing else is:
# "CYPHER 5 MATCH ..." or "CYPHER runtime=... MATCH ..." still reach the validator,
# which rejects them.
_OPENING_FENCE = re.compile(r"\A```[ \t]*(?:cypher)?[ \t]*(?:\r?\n|\Z)", re.IGNORECASE)
_CLOSING_FENCE = re.compile(r"(?:\r?\n)?[ \t]*```\Z")
_LANGUAGE_TAG_LINE = re.compile(r"\Acypher[ \t]*\r?\n", re.IGNORECASE)


_ACCESS_MODE_ERROR = "Neo.ClientError.Statement.AccessMode"  # a write in a READ transaction


def normalize_generated_cypher(cypher: str) -> str:
    """Strip Markdown code fences and a bare ``cypher`` language-tag line from LLM output."""
    text = cypher.strip()
    text = _OPENING_FENCE.sub("", text, count=1)
    text = _CLOSING_FENCE.sub("", text, count=1).strip()
    return _LANGUAGE_TAG_LINE.sub("", text, count=1).strip()


# Write, data-loading and batching clauses. Matched as whole words anywhere in the raw
# statement, string literals and comments included: a false positive costs a 400, while
# stripping literals before matching let
# 'CALL apoc.periodic.iterate("MATCH (n) RETURN n", "DETACH DELETE n", {})' through.
_FORBIDDEN_CLAUSES = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|INSERT|FOREACH|LOAD)\b", re.IGNORECASE
)
# A statement has to start with a read clause. This also rules out USE, SHOW, TERMINATE,
# GRANT and the other administration commands.
_ALLOWED_LEADING_CLAUSES = frozenset({"MATCH", "OPTIONAL", "WITH", "UNWIND", "RETURN", "CALL"})
_LEADING_NOISE = re.compile(r"(?:\s|//[^\n]*|/\*.*?\*/)*", re.DOTALL)
_EXPLAIN_OR_PROFILE = re.compile(r"(?:EXPLAIN|PROFILE)\b", re.IGNORECASE)
_FIRST_WORD = re.compile(r"[A-Za-z]+")
_UNION_USE = re.compile(r"\bUNION(?:\s+(?:ALL|DISTINCT))?\s+USE\b", re.IGNORECASE)
_CALL = re.compile(r"\bCALL\b", re.IGNORECASE)
_PROCEDURE_NAME = re.compile(r"\s*([A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)")
_APOC_NAMESPACE = re.compile(r"\bapoc\s*\.\s*(\w+)", re.IGNORECASE)
# Comment markers and backtick quoting can hide separators from the patterns above
# (CALL/**/apoc.x, `apoc`.`periodic`); they are replaced by spaces, nothing is removed.
_SEPARATOR_TRICKS = re.compile(r"/\*|\*/|//|`")

# Procedures generated Cypher may CALL. Anything else, including CALL { ... } subqueries
# and CALL ... IN TRANSACTIONS, is rejected.
_ALLOWED_PROCEDURE_PREFIXES = ("apoc.meta.",)
_ALLOWED_PROCEDURES = frozenset(
    {
        "db.labels",
        "db.relationshipTypes",
        "db.propertyKeys",
        "db.schema.visualization",
        "db.schema.nodeTypeProperties",
        "db.schema.relTypeProperties",
        "db.index.fulltext.queryNodes",
        "db.index.fulltext.queryRelationships",
    }
)


def _is_allowed_procedure(name: str) -> bool:
    return name in _ALLOWED_PROCEDURES or name.startswith(_ALLOWED_PROCEDURE_PREFIXES)


def _skip_leading_noise(text: str) -> str:
    """Drop leading whitespace and comments."""
    noise = _LEADING_NOISE.match(text)
    return text[noise.end() :] if noise else text


def validate_cypher_read_only(cypher: str) -> None:
    """Reject Cypher that could write, administer the server or escape the checks below.

    The checks run on the raw text and are deliberately conservative: a read query that
    merely mentions a forbidden word (in a string literal, say) is rejected too.

    Raises:
        CypherValidationError: if the statement is not a permitted read-only query.
    """
    if not cypher.strip():
        raise CypherValidationError("Empty Cypher statement")
    if len(cypher) > MAX_CYPHER_CHARS:
        raise CypherValidationError("Cypher statement is too long")

    text = _SEPARATOR_TRICKS.sub(" ", cypher)

    if ";" in text.strip().removesuffix(";"):
        raise CypherValidationError("Only a single Cypher statement is permitted")

    body = _skip_leading_noise(cypher)
    if explain := _EXPLAIN_OR_PROFILE.match(body):
        body = _skip_leading_noise(body[explain.end() :])
    first_word = _FIRST_WORD.match(body)
    if not first_word or first_word.group(0).upper() not in _ALLOWED_LEADING_CLAUSES:
        raise CypherValidationError("Cypher statement must start with a read clause")

    if forbidden := _FORBIDDEN_CLAUSES.search(text):
        raise CypherValidationError(f"{forbidden.group(1).upper()} is not permitted")

    if _UNION_USE.search(text):
        raise CypherValidationError("USE is not permitted")

    for call in _CALL.finditer(text):
        name_match = _PROCEDURE_NAME.match(text, call.end())
        name = re.sub(r"\s+", "", name_match.group(1)) if name_match else ""
        if not _is_allowed_procedure(name):
            target = name or "subquery"
            raise CypherValidationError(f"CALL {target} is not permitted")

    for apoc in _APOC_NAMESPACE.finditer(text):
        if apoc.group(1) != "meta":
            raise CypherValidationError(f"apoc.{apoc.group(1)} is not permitted")


def run_read_transaction(
    driver: neo4j.Driver,
    cypher: str,
    params: dict[str, Any],
    *,
    database: str | None,
    timeout: float | None,
    max_rows: int | None,
) -> list[dict[str, Any]]:
    """Run ``cypher`` in a managed READ transaction; return up to ``max_rows`` records."""

    @neo4j.unit_of_work(timeout=timeout)
    def work(tx: neo4j.ManagedTransaction) -> list[dict[str, Any]]:
        result = tx.run(cypher, params)
        records = result.fetch(max_rows) if max_rows is not None else list(result)
        return [record.data() for record in records]

    with driver.session(database=database, default_access_mode=neo4j.READ_ACCESS) as session:
        return session.execute_read(work)


# Set while langchain's own schema introspection runs (refresh_schema). Those fixed
# statements (CALL apoc.meta.data(), SHOW CONSTRAINTS, ...) skip the validator; they still
# run in READ transactions. Every other statement, including all generated Cypher, is
# validated.
_schema_refresh_in_progress: ContextVar[bool] = ContextVar(
    "_schema_refresh_in_progress", default=False
)


class ReadOnlyNeo4jGraph(Neo4jGraph):
    """``Neo4jGraph`` that can only read.

    Every statement runs through ``session.execute_read`` (READ access mode) with the
    transaction ``timeout``. Statements other than langchain's schema introspection are
    checked by ``validate_cypher_read_only`` and return at most ``max_rows`` records.
    """

    def __init__(self, *args: Any, max_rows: int = MAX_RESULT_ROWS, **kwargs: Any) -> None:
        self.max_rows = max_rows
        super().__init__(*args, **kwargs)

    def refresh_schema(self) -> None:
        """Refresh the schema; langchain's fixed introspection queries are not validated."""
        token = _schema_refresh_in_progress.set(True)
        try:
            super().refresh_schema()
        finally:
            _schema_refresh_in_progress.reset(token)

    def query(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Run ``query`` in a READ transaction (validated unless it is schema introspection).

        Untrusted statements are normalised first (Markdown fences, a bare ``cypher`` tag
        line), and the normalised text is what gets both validated and executed.
        """
        trusted = _schema_refresh_in_progress.get()
        if not trusted:
            query = normalize_generated_cypher(query)
            try:
                validate_cypher_read_only(query)
            except CypherValidationError as e:
                logger.warning("Rejected generated Cypher ({}): {!r}", e, query[:500])
                raise

        self._check_driver_state()
        records = run_read_transaction(
            self._driver,
            query,
            params or {},
            database=self._database,
            timeout=self.timeout,
            max_rows=None if trusted else self.max_rows,
        )
        if self.sanitize:
            records = [value_sanitize(record) for record in records]
        return records


# Cypher generation prompt template with domain-specific examples
CYPHER_GENERATION_TEMPLATE = """Task: Generate a Cypher statement to query a knowledge graph about educational content.

Schema:
{schema}

Node Types:
- Concept: Educational concepts with properties (name, importance_score, key_term, frequency)
- Module: Textbook modules with properties (module_id, title, key_terms)
- Chunk: Text chunks with properties (chunkId, text, moduleId, section, textEmbedding)

Relationship Types:
- PREREQ: Concept -> Concept (prerequisite relationship)
- RELATED: Concept <-> Concept (bidirectional relation)
- COVERS: Module -> Concept (module covers a concept)
- MENTIONS: Chunk -> Concept (text mentions a concept)
- NEXT: Chunk -> Chunk (sequential chunks)
- FIRST_CHUNK: Module -> Chunk (first chunk in module)

Examples:

# What concepts are prerequisites for Photosynthesis?
MATCH (c:Concept {{name: "Photosynthesis"}})<-[:PREREQ]-(prereq:Concept)
RETURN prereq.name AS prerequisite, prereq.importance_score AS importance
ORDER BY importance DESC

# Which modules cover DNA replication?
MATCH (m:Module)-[:COVERS]->(c:Concept)
WHERE toLower(c.name) CONTAINS "dna"
RETURN m.title AS module, collect(c.name) AS concepts

# What concepts are related to mitosis?
MATCH (c:Concept {{name: "Mitosis"}})-[:RELATED]-(related:Concept)
RETURN related.name AS concept, related.importance_score AS importance
ORDER BY importance DESC
LIMIT 10

# Find the most important concepts
MATCH (c:Concept)
WHERE c.importance_score > 0.5
RETURN c.name AS concept, c.importance_score AS score
ORDER BY score DESC
LIMIT 20

# What concepts does a module cover?
MATCH (m:Module {{title: $module_title}})-[:COVERS]->(c:Concept)
RETURN c.name AS concept
ORDER BY c.importance_score DESC

# Find learning path (prerequisites chain)
MATCH path = (start:Concept {{name: $concept}})<-[:PREREQ*1..3]-(prereq:Concept)
RETURN [n IN nodes(path) | n.name] AS learning_path

Instructions:
- Only use node and relationship types from the schema
- Use case-insensitive matching (toLower) for text searches
- Return meaningful column aliases
- Limit results to prevent overwhelming responses
- Do not include explanations, only the Cypher query

Question: {question}

Cypher Query:"""


class CypherQAService:
    """
    Natural language to Cypher query generation.

    Uses LangChain's GraphCypherQAChain to:
    1. Translate natural language questions to Cypher
    2. Execute queries against Neo4j (read-only, see module docstring)
    3. Format and return results
    """

    def __init__(
        self,
        neo4j_uri: str | None = None,
        neo4j_user: str | None = None,
        neo4j_password: str | None = None,
    ):
        """
        Initialize CypherQA service.

        Args:
            neo4j_uri: Neo4j connection URI
            neo4j_user: Neo4j username
            neo4j_password: Neo4j password
        """
        self.neo4j_uri = neo4j_uri or settings.neo4j_uri
        self.neo4j_user = neo4j_user or settings.neo4j_user
        self.neo4j_password = neo4j_password or settings.neo4j_password

        self._graph: ReadOnlyNeo4jGraph | None = None
        self._chain: GraphCypherQAChain | None = None
        self._llm: Any | None = None
        self._prompt: PromptTemplate | None = None

    @property
    def graph(self) -> ReadOnlyNeo4jGraph:
        """Lazy-load the read-only Neo4j graph connection.

        Raises:
            Neo4jConnectionError: Neo4j is unreachable, rejects the credentials or lacks
                the APOC meta procedures needed for schema introspection.
        """
        if self._graph is None:
            try:
                self._graph = ReadOnlyNeo4jGraph(
                    url=self.neo4j_uri,
                    username=self.neo4j_user,
                    password=self.neo4j_password,
                    database=settings.neo4j_database,
                    timeout=QUERY_TIMEOUT_SECONDS,
                )
            except (
                ValueError,
                neo4j.exceptions.ServiceUnavailable,
                neo4j.exceptions.AuthError,
            ) as e:
                # langchain-neo4j reports connection, authentication and APOC problems as
                # ValueError; re-raise so they are not mistaken for a rejected query (400).
                raise Neo4jConnectionError("Neo4j is not available for graph queries") from e
        return self._graph

    @property
    def prompt(self) -> PromptTemplate:
        """Lazy-load prompt template."""
        if self._prompt is None:
            self._prompt = PromptTemplate(
                input_variables=["schema", "question"],
                template=CYPHER_GENERATION_TEMPLATE,
            )
        return self._prompt

    @property
    def llm(self):
        """Get LLM for Cypher generation."""
        if self._llm is None:
            if settings.llm_mode == "local":
                # Use Ollama
                from langchain_community.chat_models import ChatOllama

                self._llm = ChatOllama(
                    base_url=settings.llm_ollama_host,
                    model=settings.llm_local_model,
                    temperature=0.0,  # Deterministic for Cypher
                )
            else:
                # Use OpenRouter via LangChain OpenAI compatibility
                from langchain_community.chat_models import ChatOpenAI

                self._llm = ChatOpenAI(
                    base_url=settings.openrouter_base_url,
                    api_key=settings.openrouter_api_key,
                    model=settings.openrouter_model,
                    temperature=0.0,
                )
        return self._llm

    @property
    def chain(self) -> GraphCypherQAChain:
        """Lazy-load GraphCypherQAChain."""
        if self._chain is None:
            self._chain = GraphCypherQAChain.from_llm(
                llm=self.llm,
                graph=self.graph,
                cypher_prompt=self.prompt,
                verbose=settings.debug,
                return_intermediate_steps=True,
                validate_cypher=True,  # Correct relationship directions against the schema
                # langchain-neo4j refuses to build the chain without this acknowledgement
                # that LLM-generated Cypher runs with our database credentials. Controls
                # enforced by this code: validate_cypher_read_only() rejects writes,
                # subqueries and non-allowlisted procedures (every CALL) before execution,
                # and ReadOnlyNeo4jGraph runs every statement in a READ transaction with a
                # timeout and a row cap. Defence in depth provided by the bundled compose
                # stack (see #102): Neo4j loads only the apoc.meta.* procedures.
                allow_dangerous_requests=True,
            )
        return self._chain

    def query(self, question: str) -> dict[str, Any]:
        """
        Execute natural language query against knowledge graph.

        Args:
            question: Natural language question

        Returns:
            Dict with:
            - question: Original question
            - cypher: Generated Cypher query
            - result: Query results
            - answer: Formatted answer

        Raises:
            CypherValidationError: The generated Cypher is not a permitted read-only query,
                or Neo4j refused it as a write (a ValueError: the API answers 400).
            GeneratedCypherError: Neo4j rejected the generated Cypher as invalid (syntax,
                types, unknown names): invalid LLM output, answered with 502.
            Neo4jConnectionError: Neo4j is not available or rejects our credentials.
            LLMGenerationError: Building or running the chain failed with any other
                ValueError (langchain reports LLM backend and configuration errors, such as
                an Ollama HTTP error or a missing OpenRouter key, that way).
        """
        # Untrusted text (questions, Cypher, error messages with JSON or Cypher maps) is
        # passed as loguru arguments, never interpolated into the format string.
        logger.info("CypherQA query: {}", question)

        try:
            response = self.chain.invoke({"query": question})
        except CypherValidationError:
            raise
        except neo4j.exceptions.AuthError as e:
            raise Neo4jConnectionError("Neo4j rejected the configured credentials") from e
        except neo4j.exceptions.ClientError as e:
            if isinstance(e, neo4j.exceptions.Forbidden) or e.code == _ACCESS_MODE_ERROR:
                # A write reached Neo4j and the READ transaction refused it.
                logger.warning("Neo4j refused a generated write ({}): {}", e.code, e.message)
                raise CypherValidationError("Write operations are not permitted") from e
            logger.warning("The model generated an invalid query ({}): {}", e.code, e.message)
            raise GeneratedCypherError("The model generated an invalid query") from e
        except (neo4j.exceptions.ServiceUnavailable, neo4j.exceptions.SessionExpired) as e:
            raise Neo4jConnectionError("Neo4j is not available for graph queries") from e
        except ValueError as e:
            logger.opt(exception=True).error("CypherQA chain failed: {}", e)
            raise LLMGenerationError("Cypher QA chain failed") from e

        cypher_query = next(
            (
                normalize_generated_cypher(step["query"])
                for step in response.get("intermediate_steps", [])
                if isinstance(step, dict) and isinstance(step.get("query"), str)
            ),
            None,
        )
        logger.info("Generated Cypher: {}", cypher_query)

        return {
            "question": question,
            "cypher": cypher_query,
            "result": response.get("result"),
            "answer": response.get("result"),
        }

    def generate_cypher_only(self, question: str) -> str | None:
        """
        Generate Cypher without executing.

        Useful for previewing or validating queries.

        Args:
            question: Natural language question

        Returns:
            Generated Cypher query or None if generation failed
        """
        try:
            # Get schema
            schema = self.graph.schema

            # Format prompt
            prompt_text = self.prompt.format(
                schema=schema,
                question=question,
            )

            # Generate via LLM; strip Markdown fences and a bare language tag, as for execution
            response = self.llm.invoke(prompt_text)
            cypher = normalize_generated_cypher(str(response.content))

            logger.info("Generated Cypher (preview): {}", cypher)
            return cypher

        except Exception as e:
            logger.opt(exception=True).error("Cypher generation error: {}", e)
            return None

    def execute_cypher(self, cypher: str) -> list[dict[str, Any]]:
        """
        Execute a read-only Cypher query directly.

        Args:
            cypher: Cypher query string

        Returns:
            List of result records as dicts (at most ``MAX_RESULT_ROWS``)

        Raises:
            CypherValidationError: If the query is not a permitted read-only query
                (checked by ``ReadOnlyNeo4jGraph.query`` before anything is sent)
        """
        return self.graph.query(cypher)

    def get_schema(self) -> str:
        """Get the current graph schema."""
        return self.graph.schema

    def close(self):
        """Close connections."""
        if self._graph is not None:
            self._graph.close()
        self._graph = None
        self._chain = None


# Global singleton
_cypher_qa_service: CypherQAService | None = None


def get_cypher_qa_service() -> CypherQAService:
    """
    Get or create global CypherQA service instance.

    Returns:
        CypherQAService instance
    """
    global _cypher_qa_service

    if _cypher_qa_service is None:
        _cypher_qa_service = CypherQAService()

    return _cypher_qa_service
