"""
Text chunking for RAG.

Splits long documents into overlapping chunks suitable for retrieval.
"""


from loguru import logger

from backend.app.core.settings import settings


class TextChunker:
    """Chunks text into overlapping segments for RAG."""

    def __init__(
        self,
        chunk_size: int = None,
        chunk_overlap: int = None,
    ):
        """
        Initialize text chunker.

        Args:
            chunk_size: Target chunk size in characters
            chunk_overlap: Overlap between chunks in characters
        """
        self.chunk_size = chunk_size or settings.rag_chunk_size
        self.chunk_overlap = chunk_overlap or settings.rag_chunk_overlap

    def chunk_text(self, text: str, metadata: dict = None) -> list[dict]:
        """
        Chunk a single text into overlapping segments.

        Args:
            text: Text to chunk
            metadata: Optional metadata to attach to each chunk

        Returns:
            List of chunk dicts with text and metadata
        """
        if not text:
            return []

        chunks = []
        start = 0
        chunk_id = 0

        while start < len(text):
            end = start + self.chunk_size

            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence endings
                sentence_ends = [". ", "! ", "? ", ".\n", "!\n", "?\n"]
                best_break = -1

                for sent_end in sentence_ends:
                    pos = text.rfind(sent_end, start, end)
                    if pos > best_break:
                        best_break = pos + len(sent_end)

                if best_break > start:
                    end = best_break

            chunk_text = text[start:end].strip()

            if chunk_text:
                chunk = {
                    "id": f"{metadata.get('id', 'chunk')}_{chunk_id}" if metadata else f"chunk_{chunk_id}",
                    "text": chunk_text,
                    "start_char": start,
                    "end_char": end,
                    "chunk_index": chunk_id,
                }

                # Add metadata
                if metadata:
                    chunk.update(metadata)

                chunks.append(chunk)
                chunk_id += 1

            # Move start position with overlap
            start = end - self.chunk_overlap

            # Prevent infinite loop
            if start >= len(text) - self.chunk_overlap:
                break

        return chunks

    def chunk_records(self, records: list[dict], text_field: str = "text") -> list[dict]:
        """
        Chunk multiple records.

        Args:
            records: List of record dicts
            text_field: Field name containing text to chunk

        Returns:
            List of chunk dicts
        """
        all_chunks = []

        for record in records:
            text = record.get(text_field, "")
            if not text:
                continue

            # Extract metadata (everything except the text field)
            metadata = {k: v for k, v in record.items() if k != text_field}

            chunks = self.chunk_text(text, metadata)
            all_chunks.extend(chunks)

        logger.info(f"Chunked {len(records)} records into {len(all_chunks)} chunks")
        return all_chunks


def chunk_for_rag(records: list[dict]) -> list[dict]:
    """
    Convenience function to chunk records for RAG.

    Args:
        records: List of text records

    Returns:
        List of chunks ready for indexing
    """
    chunker = TextChunker()
    return chunker.chunk_records(records)
