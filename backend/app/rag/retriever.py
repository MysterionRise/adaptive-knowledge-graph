"""
Retriever for semantic search using OpenSearch vector database.

Handles document retrieval and reranking for RAG.
"""

from loguru import logger
from opensearchpy import OpenSearch, helpers

from backend.app.core.settings import settings
from backend.app.nlp.embeddings import get_embedding_model


class OpenSearchRetriever:
    """Retriever using OpenSearch vector database."""

    def __init__(
        self,
        index_name: str | None = None,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        """
        Initialize OpenSearch retriever.

        Args:
            index_name: OpenSearch index name
            host: OpenSearch host
            port: OpenSearch port
        """
        self.index_name = index_name or settings.opensearch_index
        self.host = host or settings.opensearch_host
        self.port = port or settings.opensearch_port
        self.username = username
        self.password = password
        self.client: OpenSearch | None = None
        self.embedding_model = get_embedding_model()

    def connect(self):
        """Connect to OpenSearch."""
        logger.info(f"Connecting to OpenSearch at {self.host}:{self.port}")
        self.client = OpenSearch(
            hosts=[{"host": self.host, "port": self.port}],
            http_compress=True,
            use_ssl=settings.opensearch_use_ssl,
            verify_certs=settings.opensearch_verify_certs,
            ssl_show_warn=False,
            http_auth=(self.username, self.password) if self.username and self.password else None,
        )
        logger.success("✓ Connected to OpenSearch")

    def create_collection(self, embedding_dim: int, recreate: bool = False):
        """
        Create OpenSearch index with kNN configuration.

        Args:
            embedding_dim: Dimension of embeddings
            recreate: If True, delete existing index
        """
        assert self.client is not None, "Not connected. Call connect() first."
        if recreate and self.client.indices.exists(index=self.index_name):
            logger.warning(f"Deleting existing index: {self.index_name}")
            self.client.indices.delete(index=self.index_name)

        if not self.client.indices.exists(index=self.index_name):
            # Create index with kNN settings
            index_body = {
                "settings": {
                    "index": {
                        "knn": True,
                        "knn.algo_param.ef_search": 100,
                    }
                },
                "mappings": {
                    "properties": {
                        "text": {"type": "text"},
                        "id": {"type": "keyword"},
                        "module_id": {"type": "keyword"},
                        "module_title": {"type": "text"},
                        "section": {"type": "text"},
                        "key_terms": {"type": "keyword"},
                        "attribution": {"type": "text"},
                        "embedding": {
                            "type": "knn_vector",
                            "dimension": embedding_dim,
                            "method": {
                                "name": "hnsw",
                                "space_type": "cosinesimil",
                                "engine": "faiss",
                                "parameters": {"ef_construction": 128, "m": 24},
                            },
                        },
                    }
                },
            }

            assert self.client is not None
            self.client.indices.create(index=self.index_name, body=index_body)
            logger.success(f"✓ Created index: {self.index_name}")
        else:
            logger.info(f"Index already exists: {self.index_name}")

    def index_chunks(self, chunks: list[dict], show_progress: bool = True):
        """
        Index text chunks into OpenSearch.

        Args:
            chunks: List of chunk dicts with 'text' and metadata
            show_progress: Show progress bar
        """
        if not chunks:
            logger.warning("No chunks to index")
            return

        logger.info(f"Indexing {len(chunks)} chunks to OpenSearch")

        # Extract texts for embedding
        texts = [chunk["text"] for chunk in chunks]

        # Generate embeddings
        logger.info("Generating embeddings...")
        embeddings = self.embedding_model.encode_batch(texts)

        # Create documents for OpenSearch
        actions = []
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=False)):
            action = {
                "_index": self.index_name,
                "_id": chunk.get("id", f"chunk_{idx}"),
                "_source": {
                    "text": chunk["text"],
                    "id": chunk.get("id", f"chunk_{idx}"),
                    "module_id": chunk.get("module_id"),
                    "module_title": chunk.get("module_title"),
                    "section": chunk.get("section"),
                    "key_terms": chunk.get("key_terms", []),
                    "attribution": chunk.get("attribution"),
                    "embedding": embedding,
                },
            }
            actions.append(action)

        # Bulk index to OpenSearch in small batches
        logger.info("Uploading to OpenSearch...")
        total_success = 0
        total_failed = 0
        batch_size = 50

        for batch_start in range(0, len(actions), batch_size):
            batch = actions[batch_start : batch_start + batch_size]
            try:
                success, failed = helpers.bulk(
                    self.client, batch, chunk_size=batch_size, raise_on_error=False
                )
                total_success += success
                if failed:
                    total_failed += len(failed)
                    if show_progress:
                        logger.warning(
                            f"Batch {batch_start // batch_size}: "
                            f"{len(failed)} failures: {failed[0] if failed else ''}"
                        )
            except Exception as e:
                total_failed += len(batch)
                logger.error(f"Batch {batch_start // batch_size} error: {e}")

            if show_progress and (batch_start // batch_size) % 20 == 0:
                logger.info(
                    f"Progress: {min(batch_start + batch_size, len(actions))}/{len(actions)} docs"
                )

        # Force refresh so docs are immediately searchable
        self.client.indices.refresh(index=self.index_name)

        if show_progress:
            logger.info(f"Successfully indexed: {total_success} documents")
            if total_failed:
                logger.warning(f"Failed to index: {total_failed} documents")

        logger.success(f"✓ Indexed {total_success} chunks to OpenSearch")

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        filter_dict: dict | None = None,
    ) -> list[dict]:
        """
        Retrieve relevant chunks for a query.

        Supports two modes via settings.retrieval_mode:
        - "knn": Vector-only search (original behavior)
        - "hybrid": BM25 text search + kNN vector search with reciprocal rank fusion

        Args:
            query: Query text
            top_k: Number of results to return
            filter_dict: Optional metadata filters

        Returns:
            List of retrieved chunks with scores
        """
        top_k = top_k or settings.rag_retrieval_top_k

        if settings.retrieval_mode == "hybrid":
            return self._retrieve_hybrid(query, top_k, filter_dict)
        return self._retrieve_knn(query, top_k, filter_dict)

    def _retrieve_knn(
        self,
        query: str,
        top_k: int,
        filter_dict: dict | None = None,
    ) -> list[dict]:
        """Retrieve using kNN vector search only."""
        query_embedding = self.embedding_model.encode_query(query)

        knn_clause: dict = {
            "knn": {
                "embedding": {
                    "vector": query_embedding,
                    "k": top_k,
                }
            }
        }

        if filter_dict:
            query_clause: dict = {
                "bool": {
                    "must": [knn_clause],
                    "filter": [{"term": filter_dict}],
                }
            }
        else:
            query_clause = knn_clause

        search_body: dict = {"size": top_k, "query": query_clause}

        assert self.client is not None, "Not connected. Call connect() first."
        results: dict = self.client.search(index=self.index_name, body=search_body)

        return self._format_results(results, "knn")

    def _retrieve_hybrid(
        self,
        query: str,
        top_k: int,
        filter_dict: dict | None = None,
    ) -> list[dict]:
        """
        Retrieve using BM25 + kNN with reciprocal rank fusion.

        Runs both a BM25 text search and a kNN vector search, then merges
        results using RRF for better diversity and relevance.
        """
        query_embedding = self.embedding_model.encode_query(query)
        assert self.client is not None, "Not connected. Call connect() first."

        # kNN vector search
        knn_clause: dict = {
            "knn": {
                "embedding": {
                    "vector": query_embedding,
                    "k": top_k,
                }
            }
        }
        knn_query: dict = {"size": top_k, "query": knn_clause}
        if filter_dict:
            knn_query["query"] = {"bool": {"must": [knn_clause], "filter": [{"term": filter_dict}]}}
        knn_results: dict = self.client.search(index=self.index_name, body=knn_query)

        # BM25 text search
        bm25_clause: dict = {
            "multi_match": {
                "query": query,
                "fields": ["text^3", "module_title^2", "section", "key_terms^2"],
                "type": "best_fields",
                "fuzziness": "AUTO",
            }
        }
        bm25_query: dict = {"size": top_k, "query": bm25_clause}
        if filter_dict:
            bm25_query["query"] = {
                "bool": {"must": [bm25_clause], "filter": [{"term": filter_dict}]}
            }
        bm25_results: dict = self.client.search(index=self.index_name, body=bm25_query)

        # Reciprocal rank fusion
        merged = self._reciprocal_rank_fusion(
            knn_hits=knn_results["hits"]["hits"],
            bm25_hits=bm25_results["hits"]["hits"],
            k=60,
            top_k=top_k,
        )

        logger.info(
            f"Hybrid retrieval: kNN={len(knn_results['hits']['hits'])}, "
            f"BM25={len(bm25_results['hits']['hits'])}, merged={len(merged)} "
            f"for query: '{query[:50]}...'"
        )
        return merged

    def _reciprocal_rank_fusion(
        self,
        knn_hits: list[dict],
        bm25_hits: list[dict],
        k: int = 60,
        top_k: int = 20,
    ) -> list[dict]:
        """Combine kNN and BM25 results using reciprocal rank fusion."""
        scores: dict[str, float] = {}
        chunk_data: dict[str, dict] = {}

        for rank, hit in enumerate(knn_hits, start=1):
            doc_id = hit["_id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
            if doc_id not in chunk_data:
                chunk_data[doc_id] = hit

        for rank, hit in enumerate(bm25_hits, start=1):
            doc_id = hit["_id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
            if doc_id not in chunk_data:
                chunk_data[doc_id] = hit

        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

        merged = []
        for doc_id in sorted_ids[:top_k]:
            hit = chunk_data[doc_id]
            chunk = {
                "text": hit["_source"]["text"],
                "score": scores[doc_id],
                "id": hit["_source"].get("id"),
                "module_id": hit["_source"].get("module_id"),
                "module_title": hit["_source"].get("module_title"),
                "section": hit["_source"].get("section"),
                "key_terms": hit["_source"].get("key_terms", []),
                "attribution": hit["_source"].get("attribution"),
            }
            merged.append(chunk)

        return merged

    def _format_results(self, results: dict, mode: str) -> list[dict]:
        """Format OpenSearch results into standard chunk dicts."""
        retrieved = []
        for hit in results["hits"]["hits"]:
            chunk = {
                "text": hit["_source"]["text"],
                "score": hit["_score"],
                "id": hit["_source"].get("id"),
                "module_id": hit["_source"].get("module_id"),
                "module_title": hit["_source"].get("module_title"),
                "section": hit["_source"].get("section"),
                "key_terms": hit["_source"].get("key_terms", []),
                "attribution": hit["_source"].get("attribution"),
            }
            retrieved.append(chunk)

        logger.info(f"Retrieved {len(retrieved)} chunks ({mode})")
        return retrieved

    def get_collection_info(self) -> dict:
        """Get index information."""
        assert self.client is not None, "Not connected. Call connect() first."
        if not self.client.indices.exists(index=self.index_name):
            return {"exists": False}

        stats = self.client.indices.stats(index=self.index_name)
        doc_count = stats["indices"][self.index_name]["total"]["docs"]["count"]

        return {
            "exists": True,
            "doc_count": doc_count,
        }


# Global singleton for backward compatibility
_retriever: OpenSearchRetriever | None = None

# Registry of retrievers per subject
_retrievers: dict[str, OpenSearchRetriever] = {}


def get_retriever(subject_id: str | None = None) -> OpenSearchRetriever:
    """
    Get or create a retriever instance for a specific subject.

    Uses a registry pattern to reuse retrievers per subject.

    Args:
        subject_id: Subject identifier (e.g., "us_history", "biology").
                   If None, uses the default subject (backward compatible).

    Returns:
        OpenSearchRetriever instance configured for the subject
    """
    global _retriever

    # Backward compatibility: if no subject_id, use default singleton
    if subject_id is None:
        if _retriever is None:
            _retriever = OpenSearchRetriever(
                username=settings.opensearch_user,
                password=settings.opensearch_password,
            )
            _retriever.connect()
        return _retriever

    # Return cached retriever if available
    if subject_id in _retrievers:
        retriever = _retrievers[subject_id]
        # Reconnect if client is None
        if retriever.client is None:
            retriever.connect()
        return retriever

    # Get subject configuration
    from backend.app.core.subjects import get_subject

    subject_config = get_subject(subject_id)

    # Create new retriever with subject-specific index
    retriever = OpenSearchRetriever(
        index_name=subject_config.database.opensearch_index,
        username=settings.opensearch_user,
        password=settings.opensearch_password,
    )
    retriever.connect()

    # Cache the retriever
    _retrievers[subject_id] = retriever

    return retriever


def clear_retrievers() -> None:
    """Clear all cached retrievers."""
    global _retriever
    _retriever = None
    _retrievers.clear()
    logger.info("Cleared all cached retrievers")
