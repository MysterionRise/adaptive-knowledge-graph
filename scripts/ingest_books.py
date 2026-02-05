import argparse
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
from backend.app.core.subjects import get_all_subjects, get_subject, get_subject_ids
from backend.app.rag.retriever import get_retriever


class BookConfig(BaseModel):
    title: str
    repo_url_raw: str  # e.g. "https://raw.githubusercontent.com/philschatz/us-history-book/master"
    summary_path: str = "SUMMARY.md"
    content_path: str = "contents"
    branch: str = "master"


# Legacy BOOKS list for backward compatibility (will be overridden by subjects.yaml)
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


def get_books_for_subject(subject_id: str) -> list[BookConfig]:
    """Get book configurations from subjects.yaml for a specific subject."""
    try:
        subject_config = get_subject(subject_id)
        return [
            BookConfig(
                title=book.title,
                repo_url_raw=book.repo_url_raw,
                summary_path=book.summary_path,
                content_path=book.content_path,
                branch=book.branch,
            )
            for book in subject_config.books
        ]
    except Exception as e:
        logger.warning(f"Failed to load books from subjects.yaml for {subject_id}: {e}")
        logger.info("Falling back to hardcoded BOOKS list")
        return BOOKS


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


async def process_books(
    limit: int = 10,
    index_rag: bool = False,
    subject_id: str | None = None,
):
    """
    Process and ingest books for a subject.

    Args:
        limit: Maximum number of chapters to process per book (0 = all)
        index_rag: Whether to index into OpenSearch
        subject_id: Subject identifier (e.g., "us_history", "biology").
                   If None, uses the default subject.
    """
    # Get subject configuration
    subject_config = get_subject(subject_id)
    subject_id = subject_config.id  # Ensure we have the resolved ID

    logger.info(f"Starting book ingestion pipeline for subject: {subject_id}")
    logger.info(f"Configuration: limit={limit}, index_rag={index_rag}")

    # Get books from subjects.yaml
    books = get_books_for_subject(subject_id)
    logger.info(f"Found {len(books)} books for subject {subject_id}")

    # Ensure processed dir exists
    os.makedirs(settings.data_processed_dir, exist_ok=True)

    # Use subject-specific JSONL path
    books_jsonl_path = os.path.join(settings.data_processed_dir, f"books_{subject_id}.jsonl")

    # Get subject-specific retriever
    retriever = get_retriever(subject_id) if index_rag else None

    # Create the index if it doesn't exist
    if retriever:
        try:
            retriever.create_collection(embedding_dim=1024, recreate=False)
        except Exception as e:
            logger.warning(f"Could not create index (may already exist): {e}")

    all_records = []

    for book in books:
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
                    "subject_id": subject_id,  # Add subject_id to records
                }
                all_records.append(record)

                # Index into OpenSearch (RAG)
                if index_rag and retriever:
                    docs = []
                    for chunk_idx, chunk in enumerate(chunks):
                        docs.append(
                            {
                                "id": f"{subject_id}_{module_id}_chunk_{chunk_idx}",
                                "text": chunk,
                                "module_id": module_id,
                                "module_title": book.title,
                                "section": module_id,
                                "book": book.title,
                                "key_terms": [],
                                "attribution": subject_config.attribution,
                                "subject_id": subject_id,
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

    logger.success(f"Ingestion complete for {subject_id}! Processed {len(all_records)} modules.")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Ingest textbook content for a subject into the knowledge graph."
    )
    parser.add_argument(
        "--subject",
        type=str,
        default=None,
        help=f"Subject ID to ingest (available: {get_subject_ids()}). Defaults to us_history.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum chapters per book (0 = all chapters). Default: 0",
    )
    parser.add_argument(
        "--index-rag",
        action="store_true",
        help="Index content into OpenSearch for RAG retrieval.",
    )
    parser.add_argument(
        "--list-subjects",
        action="store_true",
        help="List all available subjects and exit.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.list_subjects:
        print("Available subjects:")
        for subject in get_all_subjects():
            books_info = ", ".join(b.title for b in subject.books)
            print(f"  - {subject.id}: {subject.name} ({len(subject.books)} books: {books_info})")
        sys.exit(0)

    # Index content for the specified subject
    asyncio.run(
        process_books(
            limit=args.limit,
            index_rag=args.index_rag,
            subject_id=args.subject,
        )
    )
