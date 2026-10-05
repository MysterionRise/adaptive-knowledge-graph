import argparse
import asyncio
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any

import requests
import yaml
from bs4 import BeautifulSoup
from loguru import logger
from pydantic import BaseModel

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.core.settings import settings
from backend.app.core.subjects import get_all_subjects, get_subject


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


@dataclass(frozen=True)
class SummaryEntry:
    """One module linked from a book's SUMMARY.md."""

    filename: str  # e.g. "m49990.md"
    link_title: str  # The link text in SUMMARY.md
    chapter: str | None  # Title of the enclosing chapter; None for preface, parts and appendices


# A numbered list item: "<indent>3.  {: .chapter} [Title](contents/m123.md)". The class marker
# and the link are both optional ("{: .part} Unit 1. The Chemistry of Life" has no link).
_SUMMARY_ITEM_RE = re.compile(
    r"^(?P<indent>[ \t]*)\d+\.\s+(?:\{:\s*\.(?P<kind>[\w-]+)\s*\}\s*)?(?P<rest>.*)$"
)
_MARKDOWN_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!'\"])")
_SUMMARY_LINK_RE = re.compile(r"\[(?P<title>[^\]]*)\]\(contents/(?P<file>m[^)]*?\.md)\)")


def parse_summary_entries(summary_text: str) -> list[SummaryEntry]:
    """Parse SUMMARY.md into modules with their link titles and chapters.

    The philschatz mirrors list a chapter as ``{: .chapter} [Chapter title](contents/m….md)``
    (that module is the chapter's introduction) with its sections indented below it. Parts
    (``{: .part}``), the preface and appendices are not chapters. Duplicate links keep the
    first occurrence.
    """
    entries: dict[str, SummaryEntry] = {}
    chapter: str | None = None
    chapter_indent = -1
    for line in summary_text.splitlines():
        item = _SUMMARY_ITEM_RE.match(line)
        if not item:
            continue
        indent = len(item["indent"].expandtabs(4))
        kind = item["kind"]
        link = _SUMMARY_LINK_RE.search(item["rest"])
        link_title = clean_title(_MARKDOWN_ESCAPE_RE.sub(r"\1", link["title"])) if link else ""

        if kind == "chapter":
            chapter, chapter_indent = (link_title or None), indent
            entry_chapter = chapter
        elif kind is None and chapter is not None and indent > chapter_indent:
            entry_chapter = chapter
        else:
            # A preface, part or appendix, or an item outside the current chapter
            chapter, chapter_indent = None, -1
            entry_chapter = None

        if link and link["file"] not in entries:
            entries[link["file"]] = SummaryEntry(link["file"], link_title, entry_chapter)
    return list(entries.values())


def parse_summary(summary_text: str) -> list[str]:
    """Extract module filenames from SUMMARY.md, in book order."""
    return [entry.filename for entry in parse_summary_entries(summary_text)]


def clean_title(title: str) -> str:
    """Normalise a title: drop markup, unescape entities and collapse whitespace."""
    text = re.sub(r"<[^>]+>", "", html.unescape(title))
    return " ".join(text.split())


def parse_front_matter_title(text: str) -> str | None:
    """Return the ``title`` from a module's YAML front matter, if it has one."""
    match = re.match(r"^---[ \t]*\r?\n([\s\S]*?)\r?\n---", text)
    if not match:
        return None
    try:
        front_matter = yaml.safe_load(match[1])
    except yaml.YAMLError:
        front_matter = None
    if isinstance(front_matter, dict):
        title = front_matter.get("title")
    else:
        title_line = re.search(r"^title:\s*(.+?)\s*$", match[1], re.MULTILINE)
        title = title_line[1].strip("\"'") if title_line else None
    if title is None:
        return None
    return clean_title(str(title)) or None


def format_module_title(chapter: str | None, section: str) -> str:
    """The stored module title: the section title, prefixed with its chapter when it has one.

    Section titles alone are not unique ("Introduction" opens every chapter), so the chapter
    is part of the title the index boosts and the API cites.
    """
    if chapter and chapter != section:
        return f"{chapter} - {section}"
    return section


def build_record(
    *,
    module_id: str,
    book_title: str,
    chapter: str | None,
    section: str,
    text: str,
    subject_id: str,
) -> dict[str, Any]:
    """One normalised module record, as written to ``books_<subject>.jsonl``."""
    return {
        "module_id": module_id,
        "module_title": format_module_title(chapter, section),
        "book_title": book_title,
        "chapter": chapter,
        "section": section,
        "text": text,
        "key_terms": [],
        "subject_id": subject_id,
    }


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


def _toc_title(raw_title: str) -> str:
    """Plain text of an OpenStax ToC title.

    Numbered titles are marked up as ``<span class="os-number">1.1</span>…
    <span class="os-text">Title</span>``; the ``os-text`` span holds the title itself.
    """
    soup = BeautifulSoup(raw_title, "html.parser")
    text_span = soup.select_one(".os-text")
    return clean_title((text_span or soup).get_text(" ", strip=True))


def _collect_leaf_pages(node: dict, chapter: str | None = None) -> list[dict[str, Any]]:
    """Recursively collect leaf pages (actual content pages) from the book tree.

    Each page carries the title of its innermost enclosing node (its chapter); pages directly
    under the book root (preface, appendices) have no chapter.
    """
    pages: list[dict[str, Any]] = []
    contents = node.get("contents", [])
    if not contents:
        # Leaf node = actual page
        slug = node.get("slug", "")
        pages.append(
            {
                "page_slug": slug,
                "title": _toc_title(node.get("title", slug)) or slug,
                "chapter": chapter,
            }
        )
    else:
        for child in contents:
            child_chapter = _toc_title(child.get("title", "")) or None
            pages.extend(
                _collect_leaf_pages(child, child_chapter if child.get("contents") else chapter)
            )
    return pages


def fetch_openstax_toc(slug: str) -> list[dict[str, Any]]:
    """Fetch table of contents from an OpenStax book.

    Uses the embedded __PRELOADED_STATE__ JSON which contains the full book tree
    on every page. Fetches the 'preface' page as a reliable entry point.

    Returns list of {"page_slug": ..., "title": ..., "chapter": ...} dicts.
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


def _process_github_raw_book(
    book: BookConfig,
    subject_id: str,
    limit: int,
    all_records: list[dict],
) -> None:
    """Process a book from a philschatz GitHub raw source."""
    summary_url = f"{book.repo_url_raw}/{book.summary_path}"
    summary_text = fetch_text(summary_url)

    if not summary_text:
        logger.error(f"Could not fetch summary for {book.title}")
        return

    entries = parse_summary_entries(summary_text)
    logger.info(f"Found {len(entries)} modules in {book.title}")

    if limit and limit > 0:
        entries = entries[:limit]
        logger.info(f"Limiting to first {limit} modules for verification.")

    for entry in entries:
        file_url = f"{book.repo_url_raw}/{book.content_path}/{entry.filename}"
        content = fetch_text(file_url)

        if not content:
            continue

        # Read the title before clean_markdown strips the front matter
        section = parse_front_matter_title(content) or entry.link_title
        clean_content = clean_markdown(content)
        module_id = entry.filename.removesuffix(".md")

        if clean_content.split():
            all_records.append(
                build_record(
                    module_id=module_id,
                    book_title=book.title,
                    chapter=entry.chapter,
                    section=section or module_id,
                    text=clean_content,
                    subject_id=subject_id,
                )
            )


def _process_openstax_web_book(
    book: BookConfig,
    subject_id: str,
    limit: int,
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

        # page_slug is already URL-safe (alphanumeric + hyphens) from OpenStax
        module_id = page_slug

        if content.split():
            all_records.append(
                build_record(
                    module_id=module_id,
                    book_title=book.title,
                    chapter=entry.get("chapter"),
                    section=page_title or module_id,
                    text=content,
                    subject_id=subject_id,
                )
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

    all_records: list[dict] = []

    for book in books:
        logger.info(f"Processing book: {book.title} (source_type={book.source_type})")

        if book.source_type == "openstax_web":
            if not book.openstax_slug:
                logger.error(f"No openstax_slug for openstax_web book: {book.title}")
                continue
            _process_openstax_web_book(book, subject_id, limit, all_records)
        else:
            # Default: github_raw
            if not book.repo_url_raw:
                logger.error(f"No repo_url_raw for github_raw book: {book.title}")
                continue
            _process_github_raw_book(book, subject_id, limit, all_records)

    # Save to JSONL
    logger.info(f"Saving {len(all_records)} records to {books_jsonl_path}")
    with open(books_jsonl_path, "w", encoding="utf-8") as f:
        for record in all_records:
            f.write(json.dumps(record) + "\n")

    logger.success(f"Ingestion complete for {subject_id}! Processed {len(all_records)} modules.")

    if index_rag:
        # Same chunker and documents as scripts/index_to_opensearch.py (make index-rag)
        from scripts.index_to_opensearch import index_records

        index_records(subject_id, all_records)


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
        help="Also index into OpenSearch, exactly like scripts/index_to_opensearch.py.",
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
