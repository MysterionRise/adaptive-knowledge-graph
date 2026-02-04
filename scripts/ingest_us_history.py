import asyncio
import os
import re
import sys

import requests
from loguru import logger

# Add project root to path
sys.path.append(os.getcwd())

from backend.app.core.settings import settings
from backend.app.rag.retriever import get_retriever

# GitHub Raw Base URLs
SUMMARY_URL = "https://raw.githubusercontent.com/philschatz/us-history-book/master/SUMMARY.md"
CONTENT_BASE_URL = "https://raw.githubusercontent.com/philschatz/us-history-book/master/contents/"
RAW_DATA_DIR = os.path.join(settings.data_raw_dir, "us_history")
os.makedirs(RAW_DATA_DIR, exist_ok=True)


def fetch_text(url: str) -> str:
    response = requests.get(url)
    response.raise_for_status()
    return response.text


def get_chapter_links(summary_text: str) -> list[str]:
    # Extract links like (contents/m12345.md)
    # We only want the filename part
    matches = re.findall(r"\(contents/(m.*?\.md)\)", summary_text)
    return list(dict.fromkeys(matches))  # Dedupe preserving order


def chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    # Simple chunking by words
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


async def ingest():
    logger.info("Starting ingestion of US History book from GitHub...")

    try:
        # 1. Get TOC
        summary_text = fetch_text(SUMMARY_URL)
        files = get_chapter_links(summary_text)
        logger.info(f"Found {len(files)} chapters/sections.")

        retriever = get_retriever()

        total_chunks = 0

        # 2. Process each chapter
        for i, filename in enumerate(files):
            try:
                # Step A: Download
                logger.info(f"Processing {i+1}/{len(files)}: {filename}")
                local_path = os.path.join(RAW_DATA_DIR, filename)

                if os.path.exists(local_path):
                    logger.info(f"Loading from cache: {local_path}")
                    with open(local_path, encoding="utf-8") as f:
                        text = f.read()
                else:
                    url = CONTENT_BASE_URL + filename
                    logger.info(f"Downloading: {url}")
                    text = fetch_text(url)
                    with open(local_path, "w", encoding="utf-8") as f:
                        f.write(text)

                if not text:
                    logger.warning(f"Empty text for {filename}")
                    continue

                # Step B: Chunk & Index
                chunks = chunk_text(text, chunk_size=settings.rag_chunk_size)

                # 4. Index
                docs = []
                for chunk in chunks:
                    docs.append(
                        {
                            "text": chunk,
                            "module_title": "US History",
                            "section": filename.replace(".md", ""),
                            "book": "US History",
                            "key_terms": [],  # Optional
                            "attribution": "OpenStax US History",
                        }
                    )

                # Use the retriever's method which handles embedding generation
                if docs:
                    logger.info(f"Indexing {len(docs)} chunks for {filename}...")
                    retriever.index_chunks(docs, show_progress=False)
                    total_chunks += len(chunks)
                    logger.info(f"Successfully indexed {filename}")

            except requests.exceptions.RequestException as e:
                logger.error(f"Download failed for {filename}: {e}")
            except Exception as e:
                logger.error(f"Indexing/Processing failed for {filename}: {e}")

        logger.info(f"Ingestion complete. Total chunks: {total_chunks}")

        # Force refresh index
        retriever.client.indices.refresh(index=settings.opensearch_index)

    except Exception as e:
        logger.error(f"Ingestion failed: {e}")


if __name__ == "__main__":
    asyncio.run(ingest())
