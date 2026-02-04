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

        # Bulk index to OpenSearch
        logger.info("Uploading to OpenSearch...")
        success, failed = helpers.bulk(self.client, actions, chunk_size=100, raise_on_error=False)

        if show_progress:
            logger.info(f"Successfully indexed: {success} documents")
            if failed:
                logger.warning(f"Failed to index: {len(failed)} documents")

        logger.success(f"✓ Indexed {success} chunks to OpenSearch")

    def retrieve(
        self,
        query: str,
        top_k: int = None,
        filter_dict: dict | None = None,
    ) -> list[dict]:
        """
        Retrieve relevant chunks for a query.

        Args:
            query: Query text
            top_k: Number of results to return
            filter_dict: Optional metadata filters

        Returns:
            List of retrieved chunks with scores
        """
        top_k = top_k or settings.rag_retrieval_top_k

        # Encode query
        query_embedding = self.embedding_model.encode_query(query)

        # Build kNN search query
        search_body = {
            "size": top_k,
            "query": {
                "knn": {
                    "embedding": {
                        "vector": query_embedding,
                        "k": top_k,
                    }
                }
            },
        }

        # Add filters if provided
        if filter_dict:
            search_body["query"] = {
                "bool": {
                    "must": [{"knn": search_body["query"]["knn"]}],
                    "filter": [{"term": filter_dict}],
                }
            }

        # Search OpenSearch
        results = self.client.search(index=self.index_name, body=search_body)

        # Format results
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

        logger.info(f"Retrieved {len(retrieved)} chunks for query: '{query[:50]}...'")
        return retrieved

    def get_collection_info(self) -> dict:
        """Get index information."""
        if not self.client.indices.exists(index=self.index_name):
            return {"exists": False}

        stats = self.client.indices.stats(index=self.index_name)
        doc_count = stats["indices"][self.index_name]["total"]["docs"]["count"]

        return {
            "exists": True,
            "doc_count": doc_count,
        }


# Global singleton
_retriever: OpenSearchRetriever | None = None


def get_retriever() -> OpenSearchRetriever:
    """
    Get or create global retriever instance.

    Returns:
        OpenSearchRetriever instance
    """
    global _retriever

    if _retriever is None:
        _retriever = OpenSearchRetriever(
            username=settings.opensearch_user,
            password=settings.opensearch_password,
        )
        _retriever.connect()

    return _retriever
