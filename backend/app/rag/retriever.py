"""
Retriever for semantic search using Qdrant vector database.

Handles document retrieval and reranking for RAG.
"""


from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from backend.app.core.settings import settings
from backend.app.nlp.embeddings import get_embedding_model


class QdrantRetriever:
    """Retriever using Qdrant vector database."""

    def __init__(
        self,
        collection_name: str | None = None,
        host: str | None = None,
        port: int | None = None,
    ):
        """
        Initialize Qdrant retriever.

        Args:
            collection_name: Qdrant collection name
            host: Qdrant host
            port: Qdrant port
        """
        self.collection_name = collection_name or settings.qdrant_collection
        self.host = host or settings.qdrant_host
        self.port = port or settings.qdrant_port

        self.client: QdrantClient | None = None
        self.embedding_model = get_embedding_model()

    def connect(self):
        """Connect to Qdrant."""
        logger.info(f"Connecting to Qdrant at {self.host}:{self.port}")
        self.client = QdrantClient(host=self.host, port=self.port)
        logger.success("✓ Connected to Qdrant")

    def create_collection(self, embedding_dim: int, recreate: bool = False):
        """
        Create Qdrant collection.

        Args:
            embedding_dim: Dimension of embeddings
            recreate: If True, delete existing collection
        """
        if recreate and self.client.collection_exists(self.collection_name):
            logger.warning(f"Deleting existing collection: {self.collection_name}")
            self.client.delete_collection(self.collection_name)

        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=embedding_dim, distance=Distance.COSINE),
            )
            logger.success(f"✓ Created collection: {self.collection_name}")
        else:
            logger.info(f"Collection already exists: {self.collection_name}")

    def index_chunks(self, chunks: list[dict], show_progress: bool = True):
        """
        Index text chunks into Qdrant.

        Args:
            chunks: List of chunk dicts with 'text' and metadata
            show_progress: Show progress bar
        """
        if not chunks:
            logger.warning("No chunks to index")
            return

        logger.info(f"Indexing {len(chunks)} chunks to Qdrant")

        # Extract texts for embedding
        texts = [chunk["text"] for chunk in chunks]

        # Generate embeddings
        logger.info("Generating embeddings...")
        embeddings = self.embedding_model.encode_batch(texts)

        # Create points for Qdrant
        points = []
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=False)):
            point = PointStruct(
                id=idx,
                vector=embedding,
                payload={
                    "text": chunk["text"],
                    "id": chunk.get("id", f"chunk_{idx}"),
                    "module_id": chunk.get("module_id"),
                    "module_title": chunk.get("module_title"),
                    "section": chunk.get("section"),
                    "key_terms": chunk.get("key_terms", []),
                    "attribution": chunk.get("attribution"),
                },
            )
            points.append(point)

        # Upload to Qdrant in batches
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            self.client.upsert(collection_name=self.collection_name, points=batch)
            if show_progress:
                logger.info(f"Uploaded {min(i + batch_size, len(points))}/{len(points)} chunks")

        logger.success(f"✓ Indexed {len(chunks)} chunks to Qdrant")

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

        # Search Qdrant
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding,
            limit=top_k,
            query_filter=filter_dict,
        )

        # Format results
        retrieved = []
        for result in results:
            chunk = {
                "text": result.payload["text"],
                "score": result.score,
                "id": result.payload.get("id"),
                "module_id": result.payload.get("module_id"),
                "module_title": result.payload.get("module_title"),
                "section": result.payload.get("section"),
                "key_terms": result.payload.get("key_terms", []),
                "attribution": result.payload.get("attribution"),
            }
            retrieved.append(chunk)

        logger.info(f"Retrieved {len(retrieved)} chunks for query: '{query[:50]}...'")
        return retrieved

    def get_collection_info(self) -> dict:
        """Get collection information."""
        if not self.client.collection_exists(self.collection_name):
            return {"exists": False}

        info = self.client.get_collection(self.collection_name)
        return {
            "exists": True,
            "vectors_count": info.vectors_count,
            "points_count": info.points_count,
        }


# Global singleton
_retriever: QdrantRetriever | None = None


def get_retriever() -> QdrantRetriever:
    """
    Get or create global retriever instance.

    Returns:
        QdrantRetriever instance
    """
    global _retriever

    if _retriever is None:
        _retriever = QdrantRetriever()
        _retriever.connect()

    return _retriever
