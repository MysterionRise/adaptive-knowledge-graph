import argparse
import asyncio
import json
import os
import re
import sys
import time
from typing import Any

import requests
from bs4 import BeautifulSoup
from loguru import logger
from pydantic import BaseModel

# Add project root to path
sys.path.append(os.getcwd())

from backend.app.core.settings import settings
from backend.app.core.subjects import SubjectConfig, get_all_subjects, get_subject
from backend.app.rag.retriever import OpenSearchRetriever, get_retriever


class BookConfig(BaseModel):
    title: str
    source_type: str = "github_raw"  # "github_raw" or "openstax_web"
    # github_raw fields
    repo_url_raw: str | None = None
    summary_path: str = "SUMMARY.md"
    content_path: str = "contents"
    branch: str = "master"
    # openstax_web fields
    openstax_slug: str | None = None  # e.g. "world-history-volume-1"


def get_books_for_subject(subject_id: str) -> list[BookConfig]:
    """Get book configurations from subjects.yaml for a specific subject."""
    subject_config = get_subject(subject_id)
    return [
        BookConfig(
            title=book.title,
            source_type=book.source_type,
            repo_url_raw=book.repo_url_raw,
            summary_path=book.summary_path,
            content_path=book.content_path,
            branch=book.branch,
            openstax_slug=book.openstax_slug,
        )
        for book in subject_config.books
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


OPENSTAX_BASE_URL = "https://openstax.org/books"
OPENSTAX_FETCH_DELAY = 0.5  # seconds between page fetches


def _extract_preloaded_state(html: str) -> dict[str, Any] | None:
    """Extract the __PRELOADED_STATE__ JSON from an OpenStax page."""
    marker = "window.__PRELOADED_STATE__ = "
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.select("script"):
        text = script.string or ""
        if marker in text:
            json_str = text.split(marker, 1)[1].rstrip(";").strip()
            try:
                result: dict[str, Any] = json.loads(json_str)
                return result
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse __PRELOADED_STATE__ JSON: {e}")
                return None
    return None


def _collect_leaf_pages(node: dict) -> list[dict[str, str]]:
    """Recursively collect leaf pages (actual content pages) from the book tree."""
    pages: list[dict[str, str]] = []
    contents = node.get("contents", [])
    if not contents:
        # Leaf node = actual page
        slug = node.get("slug", "")
        raw_title = node.get("title", slug)
        # Titles may contain HTML markup — strip it
        clean_title = BeautifulSoup(raw_title, "html.parser").get_text(strip=True)
        pages.append({"page_slug": slug, "title": clean_title})
    else:
        for child in contents:
            pages.extend(_collect_leaf_pages(child))
    return pages


def fetch_openstax_toc(slug: str) -> list[dict[str, str]]:
    """Fetch table of contents from an OpenStax book.

    Uses the embedded __PRELOADED_STATE__ JSON which contains the full book tree
    on every page. Fetches the 'preface' page as a reliable entry point.

    Returns list of {"page_slug": ..., "title": ...} dicts.
    """
    url = f"{OPENSTAX_BASE_URL}/{slug}/pages/preface"
    logger.info(f"Fetching OpenStax ToC from {url}")

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch OpenStax page for {slug}: {e}")
        return []

    state = _extract_preloaded_state(resp.text)
    if not state:
        logger.error(f"No __PRELOADED_STATE__ found on page for {slug}")
        return []

    try:
        tree = state["content"]["book"]["tree"]
    except (KeyError, TypeError):
        logger.error(f"Unexpected __PRELOADED_STATE__ structure for {slug}")
        return []

    toc_entries = _collect_leaf_pages(tree)
    logger.info(f"Found {len(toc_entries)} pages in OpenStax ToC for {slug}")
    return toc_entries


def fetch_openstax_page(slug: str, page_slug: str) -> str | None:
    """Fetch and extract text from a single OpenStax page.

    First tries DOM selectors on the SSR HTML. Falls back to the embedded
    __PRELOADED_STATE__ JSON if the page is client-side rendered.
    """
    url = f"{OPENSTAX_BASE_URL}/{slug}/pages/{page_slug}"

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Failed to fetch OpenStax page {page_slug}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Try SSR content via DOM selectors
    content = (
        soup.select_one('[data-type="page"]')
        or soup.select_one("main")
        or soup.select_one("#main-content")
    )

    if content:
        # Remove non-content elements
        for tag in content.select("figure, nav, footer, [data-type='note'], script, style"):
            tag.decompose()
        text = content.get_text(separator="\n", strip=True)
    else:
        # Fallback: extract from __PRELOADED_STATE__ for JS-rendered pages
        state = _extract_preloaded_state(resp.text)
        if state:
            page_html = state.get("content", {}).get("page", {}).get("content", "")
            if page_html:
                page_soup = BeautifulSoup(page_html, "html.parser")
                for tag in page_soup.select("figure, nav, footer, script, style"):
                    tag.decompose()
                text = page_soup.get_text(separator="\n", strip=True)
            else:
                logger.warning(f"No content in __PRELOADED_STATE__ for page {page_slug}")
                return None
        else:
            logger.warning(f"No main content found on page {page_slug}")
            return None

    # Clean up excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)

    return text.strip() if text.strip() else None


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


def _add_record_and_index(
    record: dict,
    all_records: list[dict],
    subject_id: str,
    subject_config: SubjectConfig,
    index_rag: bool,
    retriever: OpenSearchRetriever | None,
    book_title: str,
    module_id: str,
) -> None:
    """Add a record to results and optionally index into OpenSearch."""
    all_records.append(record)

    if index_rag and retriever:
        docs = []
        for chunk_idx, chunk in enumerate(record["chunks"]):
            docs.append(
                {
                    "id": f"{subject_id}_{module_id}_chunk_{chunk_idx}",
                    "text": chunk,
                    "module_id": module_id,
                    "module_title": book_title,
                    "section": module_id,
                    "book": book_title,
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


def _process_github_raw_book(
    book: BookConfig,
    subject_id: str,
    subject_config: SubjectConfig,
    limit: int,
    index_rag: bool,
    retriever: OpenSearchRetriever | None,
    all_records: list[dict],
) -> None:
    """Process a book from a philschatz GitHub raw source."""
    summary_url = f"{book.repo_url_raw}/{book.summary_path}"
    summary_text = fetch_text(summary_url)

    if not summary_text:
        logger.error(f"Could not fetch summary for {book.title}")
        return

    chapters = parse_summary(summary_text)
    logger.info(f"Found {len(chapters)} chapters in {book.title}")

    if limit and limit > 0:
        chapters = chapters[:limit]
        logger.info(f"Limiting to first {limit} chapters for verification.")

    for filename in chapters:
        file_url = f"{book.repo_url_raw}/{book.content_path}/{filename}"
        content = fetch_text(file_url)

        if not content:
            continue

        clean_content = clean_markdown(content)
        chunks = chunk_text(clean_content, chunk_size=settings.rag_chunk_size)

        module_id = filename.replace(".md", "")

        if chunks:
            record = {
                "module_id": module_id,
                "module_title": f"{book.title} - {module_id}",
                "book_title": book.title,
                "section": module_id,
                "text": clean_content,
                "key_terms": [],
                "chunks": chunks,
                "subject_id": subject_id,
            }
            _add_record_and_index(
                record,
                all_records,
                subject_id,
                subject_config,
                index_rag,
                retriever,
                book.title,
                module_id,
            )


def _process_openstax_web_book(
    book: BookConfig,
    subject_id: str,
    subject_config: SubjectConfig,
    limit: int,
    index_rag: bool,
    retriever: OpenSearchRetriever | None,
    all_records: list[dict],
) -> None:
    """Process a book from the OpenStax website (HTML source)."""
    if not book.openstax_slug:
        logger.error(f"No openstax_slug configured for book: {book.title}")
        return

    toc = fetch_openstax_toc(book.openstax_slug)
    if not toc:
        logger.error(f"Could not fetch ToC for {book.title}")
        return

    logger.info(f"Found {len(toc)} pages in {book.title}")

    if limit and limit > 0:
        toc = toc[:limit]
        logger.info(f"Limiting to first {limit} pages for verification.")

    for entry in toc:
        page_slug = entry["page_slug"]
        page_title = entry["title"]

        content = fetch_openstax_page(book.openstax_slug, page_slug)

        if not content:
            continue

        # Rate-limit after successful fetch to be polite to openstax.org
        time.sleep(OPENSTAX_FETCH_DELAY)

        chunks = chunk_text(content, chunk_size=settings.rag_chunk_size)
        # page_slug is already URL-safe (alphanumeric + hyphens) from OpenStax
        module_id = page_slug

        if chunks:
            record = {
                "module_id": module_id,
                "module_title": f"{book.title} - {page_title}",
                "book_title": book.title,
                "section": module_id,
                "text": content,
                "key_terms": [],
                "chunks": chunks,
                "subject_id": subject_id,
            }
            _add_record_and_index(
                record,
                all_records,
                subject_id,
                subject_config,
                index_rag,
                retriever,
                book.title,
                module_id,
            )


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

    all_records: list[dict] = []

    for book in books:
        logger.info(f"Processing book: {book.title} (source_type={book.source_type})")

        if book.source_type == "openstax_web":
            if not book.openstax_slug:
                logger.error(f"No openstax_slug for openstax_web book: {book.title}")
                continue
            _process_openstax_web_book(
                book, subject_id, subject_config, limit, index_rag, retriever, all_records
            )
        else:
            # Default: github_raw
            if not book.repo_url_raw:
                logger.error(f"No repo_url_raw for github_raw book: {book.title}")
                continue
            _process_github_raw_book(
                book, subject_id, subject_config, limit, index_rag, retriever, all_records
            )

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
        help="Subject ID to ingest. Use --list-subjects to see options. Defaults to us_history.",
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
