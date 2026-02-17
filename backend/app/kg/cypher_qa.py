"""
Natural language to Cypher query generation using LangChain.

Implements GraphCypherQAChain for text-to-Cypher translation,
allowing users to query the knowledge graph in plain English.

Note: Requires langchain, langchain-community, and langchain-neo4j packages.
These are optional dependencies - the module gracefully handles their absence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from backend.app.core.settings import settings

if TYPE_CHECKING:
    from langchain_neo4j import GraphCypherQAChain, Neo4jGraph

# Lazy imports tracking
_langchain_available: bool | None = None


def _check_langchain() -> bool:
    """Check if LangChain dependencies are available."""
    global _langchain_available
    if _langchain_available is None:
        try:
            import langchain_neo4j  # noqa: F401

            _langchain_available = True
        except ImportError:
            _langchain_available = False
            logger.warning(
                "LangChain dependencies not installed. "
                "Run: poetry install to install langchain packages"
            )
    return _langchain_available


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
    2. Execute queries against Neo4j
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

        self._graph: Neo4jGraph | None = None
        self._chain: GraphCypherQAChain | None = None
        self._llm: object | None = None
        self._prompt: object | None = None

    def _ensure_langchain(self):
        """Ensure LangChain is available, raise if not."""
        if not _check_langchain():
            raise ImportError(
                "LangChain dependencies not installed. "
                "Run: poetry install to install langchain packages"
            )

    @property
    def graph(self) -> Neo4jGraph:
        """Lazy-load Neo4j graph connection."""
        if self._graph is None:
            self._ensure_langchain()
            from langchain_neo4j import Neo4jGraph

            self._graph = Neo4jGraph(
                url=self.neo4j_uri,
                username=self.neo4j_user,
                password=self.neo4j_password,
            )
        return self._graph

    @property
    def prompt(self):
        """Lazy-load prompt template."""
        if self._prompt is None:
            self._ensure_langchain()
            from langchain.prompts import PromptTemplate

            self._prompt = PromptTemplate(
                input_variables=["schema", "question"],
                template=CYPHER_GENERATION_TEMPLATE,
            )
        return self._prompt

    @property
    def llm(self):
        """Get LLM for Cypher generation."""
        if self._llm is None:
            self._ensure_langchain()

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
            self._ensure_langchain()
            from langchain_neo4j import GraphCypherQAChain

            self._chain = GraphCypherQAChain.from_llm(
                llm=self.llm,
                graph=self.graph,
                cypher_prompt=self.prompt,
                verbose=settings.debug,
                return_intermediate_steps=True,
                validate_cypher=True,  # Validate syntax before execution
            )
        return self._chain

    def query(self, question: str) -> dict:
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
        """
        logger.info(f"CypherQA query: {question}")

        try:
            response = self.chain.invoke({"query": question})

            # Extract intermediate steps
            cypher_query = None
            if "intermediate_steps" in response:
                for step in response["intermediate_steps"]:
                    if isinstance(step, dict) and "query" in step:
                        cypher_query = step["query"]
                        break

            result = {
                "question": question,
                "cypher": cypher_query,
                "result": response.get("result"),
                "answer": response.get("result"),
            }

            logger.info(f"Generated Cypher: {cypher_query}")
            return result

        except Exception as e:
            logger.error(f"CypherQA error: {e}")
            return {
                "question": question,
                "cypher": None,
                "result": None,
                "answer": f"Error: {str(e)}",
                "error": str(e),
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

            # Generate via LLM
            response = self.llm.invoke(prompt_text)
            cypher = str(response.content).strip()

            # Clean up response (remove markdown code blocks if present)
            if cypher.startswith("```"):
                lines = cypher.split("\n")
                cypher = "\n".join(line for line in lines if not line.startswith("```")).strip()

            logger.info(f"Generated Cypher (preview): {cypher}")
            return cypher

        except Exception as e:
            logger.error(f"Cypher generation error: {e}")
            return None

    def execute_cypher(self, cypher: str) -> list[dict]:
        """
        Execute a Cypher query directly.

        Args:
            cypher: Cypher query string

        Returns:
            List of result records as dicts
        """
        try:
            results = self.graph.query(cypher)
            return results
        except Exception as e:
            logger.error(f"Cypher execution error: {e}")
            raise

    def get_schema(self) -> str:
        """Get the current graph schema."""
        return self.graph.schema

    def close(self):
        """Close connections."""
        # Neo4jGraph manages its own connection lifecycle
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


def is_langchain_available() -> bool:
    """Check if LangChain is available for CypherQA functionality."""
    return _check_langchain()
