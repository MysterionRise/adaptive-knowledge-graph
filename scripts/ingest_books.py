import asyncio
import json
import os
import re
import sys

import requests
from loguru import logger
from pydantic import BaseModel

# Add project root to path
sys.path.append(os.getcwd())

from backend.app.core.settings import settings
from backend.app.rag.retriever import get_retriever


class BookConfig(BaseModel):
    title: str
    repo_url_raw: str  # e.g. "https://raw.githubusercontent.com/philschatz/us-history-book/master"
    summary_path: str = "SUMMARY.md"
    content_path: str = "contents"
    branch: str = "master"


BOOKS = [
    BookConfig(
        title="US History",
        repo_url_raw="https://raw.githubusercontent.com/philschatz/us-history-book/master",
    ),
    BookConfig(
        title="American Government",
        repo_url_raw="https://raw.githubusercontent.com/philschatz/american-government-book/master",
    ),
]


def fetch_text(url: str) -> str | None:
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


def parse_summary(summary_text: str) -> list[str]:
    """Extract chapter filenames from SUMMARY.md"""
    # Look for links like (contents/m12345.md)
    matches = re.findall(r"\(contents/(m.*?\.md)\)", summary_text)
    return list(dict.fromkeys(matches))  # Dedupe


def clean_markdown(text: str) -> str:
    """Remove Liquid tags and other non-content artifacts."""
    # Remove metadata headers (--- ... ---)
    text = re.sub(r"^---[\s\S]*?---", "", text)
    # Remove HTML comments
    text = re.sub(r"<!--[\s\S]*?-->", "", text)
    # Remove div tags but keep content
    text = re.sub(r"<div.*?>", "", text)
    text = re.sub(r"</div>", "", text)
    # Remove images
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    return text.strip()


def chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    words = text.split()
    chunks = []
    current_chunk = []
    current_count = 0

    for word in words:
        current_chunk.append(word)
        current_count += 1
        if current_count >= chunk_size:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
            current_count = 0

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


async def process_books(limit: int = 10, index_rag: bool = False):
    logger.info("Starting book ingestion pipeline...")
    logger.info(f"Configuration: limit={limit}, index_rag={index_rag}")

    # Ensure processed dir exists
    os.makedirs(settings.data_processed_dir, exist_ok=True)
    books_jsonl_path = settings.data_books_jsonl

    retriever = get_retriever() if index_rag else None

    all_records = []

    for book in BOOKS:
        logger.info(f"Processing book: {book.title}")

        # 1. Fetch Summary
        summary_url = f"{book.repo_url_raw}/{book.summary_path}"
        summary_text = fetch_text(summary_url)

        if not summary_text:
            logger.error(f"Could not fetch summary for {book.title}")
            continue

        chapters = parse_summary(summary_text)
        logger.info(f"Found {len(chapters)} chapters in {book.title}")

        if limit and limit > 0:
            chapters = chapters[:limit]
            logger.info(f"Limiting to first {limit} chapters for verification.")

        # 2. Process Chapters
        for filename in chapters:
            file_url = f"{book.repo_url_raw}/{book.content_path}/{filename}"
            content = fetch_text(file_url)

            if not content:
                continue

            clean_content = clean_markdown(content)
            chunks = chunk_text(clean_content, chunk_size=settings.rag_chunk_size)

            module_id = filename.replace(".md", "")

            # Create records for JSONL (KG building)
            if chunks:
                record = {
                    "module_id": module_id,
                    "module_title": f"{book.title} - {module_id}",
                    "book_title": book.title,
                    "section": module_id,
                    "text": clean_content,
                    "key_terms": [],
                    "chunks": chunks,
                }
                all_records.append(record)

                # Index into OpenSearch (RAG)
                if index_rag and retriever:
                    docs = []
                    for chunk in chunks:
                        docs.append(
                            {
                                "text": chunk,
                                "module_title": book.title,
                                "section": module_id,
                                "book": book.title,
                                "key_terms": [],
                                "attribution": f"{book.title} (OpenStax/PhilSchatz)",
                            }
                        )

                    if docs:
                        try:
                            retriever.index_chunks(docs, show_progress=False)
                        except Exception as e:
                            logger.error(f"Failed to index {module_id}: {e}")

    # Save to JSONL
    logger.info(f"Saving {len(all_records)} records to {books_jsonl_path}")
    with open(books_jsonl_path, "w", encoding="utf-8") as f:
        for record in all_records:
            # Remove giant 'chunks' from jsonl if not needed for KG but useful for debugging
            record_copy = record.copy()
            del record_copy["chunks"]
            f.write(json.dumps(record_copy) + "\n")

    logger.success("Ingestion complete!")


if __name__ == "__main__":
    # Disable RAG indexing for speed/stability during dev verification
    # Run with RAG indexing enabled and larger limit for demo
    asyncio.run(process_books(limit=50, index_rag=True))
