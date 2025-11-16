"""
Fetch OpenStax Biology 2e textbook from philschatz GitHub mirror.

This script downloads the HTML content of OpenStax Biology 2e from the
philschatz/biology-book GitHub repository, which mirrors OpenStax content.
The content is licensed under CC BY 4.0.
"""

import asyncio
import json
from pathlib import Path

import aiohttp
from loguru import logger

from backend.app.core.settings import settings

# GitHub raw content base URL for philschatz/biology-book
GITHUB_BASE_URL = "https://raw.githubusercontent.com/philschatz/biology-book/master/contents"
BOOK_TOC_URL = f"{GITHUB_BASE_URL}/m44403.xhtml"

# For demo, we'll focus on key chapters (can expand later)
DEMO_CHAPTERS = [
    "m45448",  # Introduction to Biology
    "m45452",  # Themes and Concepts of Biology
    "m45453",  # The Chemical Foundation of Life
    "m45471",  # Carbon
    "m45472",  # Biological Macromolecules
    "m45473",  # The Structure and Function of Large Biological Molecules
    "m45476",  # Cell Structure
    "m45477",  # Prokaryotic Cells
    "m45478",  # Eukaryotic Cells
    "m45488",  # Photosynthesis
    "m45489",  # The Light-Dependent Reactions
    "m45490",  # The Calvin Cycle
    "m45491",  # Cellular Respiration
    "m45492",  # Glycolysis
    "m45493",  # The Citric Acid Cycle
]


async def fetch_html(session: aiohttp.ClientSession, module_id: str) -> dict[str, str]:
    """
    Fetch a single module's HTML content.

    Args:
        session: aiohttp client session
        module_id: Module ID (e.g., 'm45448')

    Returns:
        Dict with module_id and html content
    """
    url = f"{GITHUB_BASE_URL}/{module_id}.xhtml"
    logger.info(f"Fetching {module_id} from {url}")

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
            if response.status == 200:
                html = await response.text()
                logger.success(f"✓ Fetched {module_id} ({len(html)} bytes)")
                return {"module_id": module_id, "html": html, "url": url}
            else:
                logger.error(f"✗ Failed to fetch {module_id}: HTTP {response.status}")
                return {"module_id": module_id, "html": "", "url": url, "error": f"HTTP {response.status}"}
    except Exception as e:
        logger.error(f"✗ Error fetching {module_id}: {e}")
        return {"module_id": module_id, "html": "", "url": url, "error": str(e)}


async def fetch_all_modules(module_ids: list[str]) -> list[dict[str, str]]:
    """
    Fetch all modules concurrently.

    Args:
        module_ids: List of module IDs to fetch

    Returns:
        List of dicts with module data
    """
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_html(session, module_id) for module_id in module_ids]
        results = await asyncio.gather(*tasks)
        return results


def save_raw_html(modules: list[dict[str, str]], output_dir: Path):
    """
    Save raw HTML files to disk.

    Args:
        modules: List of module data dicts
        output_dir: Directory to save HTML files
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    for module in modules:
        if module.get("html"):
            file_path = output_dir / f"{module['module_id']}.html"
            file_path.write_text(module["html"], encoding="utf-8")
            logger.info(f"Saved {file_path}")

    # Save metadata
    metadata = {
        "source": "philschatz/biology-book",
        "license": "CC BY 4.0",
        "attribution": settings.attribution_openstax,
        "modules_count": len(modules),
        "modules": [
            {
                "id": m["module_id"],
                "url": m["url"],
                "size_bytes": len(m.get("html", "")),
                "error": m.get("error"),
            }
            for m in modules
        ],
    }

    metadata_path = output_dir / "fetch_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    logger.success(f"Saved metadata to {metadata_path}")


def main():
    """Main entry point."""
    logger.info("Starting OpenStax Biology 2e fetch")
    logger.info(f"Fetching {len(DEMO_CHAPTERS)} demo chapters")

    # Fetch modules
    modules = asyncio.run(fetch_all_modules(DEMO_CHAPTERS))

    # Count successes
    successful = sum(1 for m in modules if m.get("html"))
    logger.info(f"Successfully fetched {successful}/{len(modules)} modules")

    # Save to disk
    output_dir = Path(settings.data_raw_dir)
    save_raw_html(modules, output_dir)

    logger.success(f"✓ Fetch complete! Files saved to {output_dir}")
    logger.info("Next step: run 'make parse-data' to parse HTML")


if __name__ == "__main__":
    main()
