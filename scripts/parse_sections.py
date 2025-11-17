"""
Parse OpenStax Biology 2e HTML files into structured JSON.

This script parses the raw HTML files downloaded by fetch_openstax.py
and extracts structured content: titles, sections, paragraphs, key terms,
and learning objectives.
"""

import json
from pathlib import Path

from bs4 import BeautifulSoup
from loguru import logger

from backend.app.core.settings import settings


def extract_title(soup: BeautifulSoup) -> str:
    """Extract module title."""
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(strip=True)

    # Fallback to first h1
    h1_tag = soup.find("h1")
    if h1_tag:
        return h1_tag.get_text(strip=True)

    return "Untitled"


def extract_learning_objectives(soup: BeautifulSoup) -> list[str]:
    """Extract learning objectives from the module."""
    objectives = []

    # OpenStax uses <div class="learning-objectives"> or <section data-element-type="learning-objectives">
    obj_divs = soup.find_all("div", class_="learning-objectives") + soup.find_all(
        "section", {"data-element-type": "learning-objectives"}
    )

    for obj_div in obj_divs:
        # Find all list items
        for li in obj_div.find_all("li"):
            text = li.get_text(strip=True)
            if text:
                objectives.append(text)

    return objectives


def extract_key_terms(soup: BeautifulSoup) -> list[str]:
    """Extract key terms from the module."""
    key_terms = []

    # OpenStax uses <div class="glossary"> or <section data-element-type="glossary">
    glossary_divs = soup.find_all("div", class_="glossary") + soup.find_all(
        "section", {"data-element-type": "glossary"}
    )

    for glossary in glossary_divs:
        # Find definition terms
        for dt in glossary.find_all("dt"):
            term = dt.get_text(strip=True)
            if term:
                key_terms.append(term)

    # Also look for <strong> or <b> terms in paragraphs
    for strong in soup.find_all(["strong", "b"]):
        term = strong.get_text(strip=True)
        if term and len(term.split()) <= 4:  # Only short phrases
            if term not in key_terms:
                key_terms.append(term)

    return list(set(key_terms))[:50]  # Limit to 50 unique terms


def extract_paragraphs(soup: BeautifulSoup) -> list[dict[str, str]]:
    """
    Extract paragraphs from the module.

    Returns:
        List of dicts with text and optional section heading
    """
    paragraphs = []
    current_section = "Introduction"

    # Find all content sections
    for element in soup.find_all(["h2", "h3", "p"]):
        if element.name in ["h2", "h3"]:
            # Update current section
            current_section = element.get_text(strip=True)
        elif element.name == "p":
            text = element.get_text(strip=True)
            if text and len(text) > 20:  # Skip very short paragraphs
                paragraphs.append({"section": current_section, "text": text})

    return paragraphs


def parse_module(html_path: Path) -> dict | None:
    """
    Parse a single HTML module into structured JSON.

    Args:
        html_path: Path to HTML file

    Returns:
        Dict with parsed content or None if parsing fails
    """
    try:
        html = html_path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "lxml")

        module_id = html_path.stem
        title = extract_title(soup)
        learning_objectives = extract_learning_objectives(soup)
        key_terms = extract_key_terms(soup)
        paragraphs = extract_paragraphs(soup)

        logger.info(
            f"Parsed {module_id}: '{title}' - {len(paragraphs)} paragraphs, {len(key_terms)} key terms"
        )

        return {
            "module_id": module_id,
            "title": title,
            "learning_objectives": learning_objectives,
            "key_terms": key_terms,
            "paragraphs": paragraphs,
            "paragraph_count": len(paragraphs),
            "source_file": str(html_path),
        }

    except Exception as e:
        logger.error(f"Error parsing {html_path}: {e}")
        return None


def main():
    """Main entry point."""
    logger.info("Starting HTML parsing")

    raw_dir = Path(settings.data_raw_dir)
    processed_dir = Path(settings.data_processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)

    # Find all HTML files
    html_files = list(raw_dir.glob("*.html"))
    logger.info(f"Found {len(html_files)} HTML files to parse")

    # Parse each file
    parsed_modules = []
    for html_path in html_files:
        parsed = parse_module(html_path)
        if parsed:
            parsed_modules.append(parsed)

    # Save parsed data
    output_path = processed_dir / "parsed_modules.json"
    output_path.write_text(json.dumps(parsed_modules, indent=2), encoding="utf-8")

    logger.success(f"✓ Parsed {len(parsed_modules)} modules")
    logger.success(f"✓ Saved to {output_path}")

    # Print summary statistics
    total_paragraphs = sum(m["paragraph_count"] for m in parsed_modules)
    total_key_terms = sum(len(m["key_terms"]) for m in parsed_modules)
    logger.info(f"Total paragraphs: {total_paragraphs}")
    logger.info(f"Total key terms: {total_key_terms}")
    logger.info("Next step: run 'make normalize-data'")


if __name__ == "__main__":
    main()
