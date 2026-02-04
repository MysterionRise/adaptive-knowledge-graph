"""
Text chunking for RAG.

Splits long documents into overlapping chunks suitable for retrieval.
Enterprise pattern: tracks sequential linking for NEXT relationship creation.
"""

from loguru import logger

from backend.app.core.settings import settings


class TextChunker:
    """Chunks text into overlapping segments for RAG."""

    def __init__(
        self,
        chunk_size: int = None,
        chunk_overlap: int = None,
        track_sequential: bool = True,
    ):
        """
        Initialize text chunker.

        Args:
            chunk_size: Target chunk size in characters
            chunk_overlap: Overlap between chunks in characters
            track_sequential: Track previous_chunk_id for NEXT relationships
        """
        self.chunk_size = chunk_size or settings.rag_chunk_size
        self.chunk_overlap = chunk_overlap or settings.rag_chunk_overlap
        self.track_sequential = track_sequential

    def chunk_text(
        self,
        text: str,
        metadata: dict = None,
        previous_chunk_id: str | None = None,
    ) -> list[dict]:
        """
        Chunk a single text into overlapping segments.

        Args:
            text: Text to chunk
            metadata: Optional metadata to attach to each chunk
            previous_chunk_id: ID of chunk preceding this text's first chunk
                               (for cross-document NEXT linking)

        Returns:
            List of chunk dicts with text, metadata, and sequential linking info
        """
        if not text:
            return []

        chunks = []
        start = 0
        chunk_id = 0
        prev_id = previous_chunk_id

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
                current_id = (
                    f"{metadata.get('id', 'chunk')}_{chunk_id}" if metadata else f"chunk_{chunk_id}"
                )

                chunk = {
                    "id": current_id,
                    "text": chunk_text,
                    "start_char": start,
                    "end_char": end,
                    "chunk_index": chunk_id,
                }

                # Add sequential linking for enterprise RAG
                if self.track_sequential:
                    chunk["previous_chunk_id"] = prev_id
                    chunk["next_chunk_id"] = None  # Will be set by next iteration

                    # Update previous chunk's next_chunk_id
                    if chunks and prev_id is not None:
                        chunks[-1]["next_chunk_id"] = current_id

                    prev_id = current_id

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

    def chunk_records(
        self,
        records: list[dict],
        text_field: str = "text",
        group_by: str | None = "module_id",
    ) -> tuple[list[dict], dict[str, str]]:
        """
        Chunk multiple records with sequential linking support.

        When group_by is specified, chunks within the same group are linked
        sequentially via previous_chunk_id/next_chunk_id for NEXT relationships.

        Args:
            records: List of record dicts
            text_field: Field name containing text to chunk
            group_by: Field to group records by for sequential linking.
                      Chunks within the same group are linked. None disables grouping.

        Returns:
            Tuple of (chunks, first_chunks_by_group):
            - chunks: List of chunk dicts
            - first_chunks_by_group: Dict mapping group_id to first chunk_id
              (for FIRST_CHUNK relationships)
        """
        all_chunks = []
        first_chunks_by_group: dict[str, str] = {}

        # Track the last chunk_id per group for sequential linking
        last_chunk_id_per_group: dict[str, str] = {}

        for record in records:
            text = record.get(text_field, "")
            if not text:
                continue

            # Extract metadata (everything except the text field)
            metadata = {k: v for k, v in record.items() if k != text_field}

            # Determine group for sequential linking
            group_id = record.get(group_by) if group_by else None

            # Get previous chunk ID for this group
            prev_chunk_id = last_chunk_id_per_group.get(group_id) if group_id else None

            chunks = self.chunk_text(text, metadata, previous_chunk_id=prev_chunk_id)

            if chunks and group_id:
                # Track first chunk for this group
                if group_id not in first_chunks_by_group:
                    first_chunks_by_group[group_id] = chunks[0]["id"]

                # Update last chunk ID for this group
                last_chunk_id_per_group[group_id] = chunks[-1]["id"]

            all_chunks.extend(chunks)

        logger.info(f"Chunked {len(records)} records into {len(all_chunks)} chunks")
        if first_chunks_by_group:
            logger.info(f"Tracked first chunks for {len(first_chunks_by_group)} groups")

        return all_chunks, first_chunks_by_group


def chunk_for_rag(
    records: list[dict],
    with_sequential_linking: bool = True,
) -> tuple[list[dict], dict[str, str]] | list[dict]:
    """
    Convenience function to chunk records for RAG.

    Args:
        records: List of text records
        with_sequential_linking: If True, returns (chunks, first_chunks_by_module) tuple.
                                 If False, returns just chunks list (legacy behavior).

    Returns:
        If with_sequential_linking:
            Tuple of (chunks, first_chunks_by_module)
        Else:
            List of chunks ready for indexing
    """
    chunker = TextChunker(track_sequential=with_sequential_linking)

    if with_sequential_linking:
        return chunker.chunk_records(records)
    else:
        # Legacy behavior - just return chunks
        chunks, _ = chunker.chunk_records(records, group_by=None)
        return chunks
