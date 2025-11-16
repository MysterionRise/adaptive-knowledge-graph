"""
Normalize parsed OpenStax content into JSONL format with attribution.

This script takes the parsed JSON from parse_sections.py and normalizes it
into a JSONL format suitable for knowledge graph construction and RAG indexing.
Adds proper CC BY 4.0 attribution to all content.
"""

import json
from pathlib import Path
from typing import Dict, List

from loguru import logger

from backend.app.core.settings import settings


def normalize_module(module: Dict) -> List[Dict]:
    """
    Normalize a single module into JSONL records.

    Each paragraph becomes a separate record with metadata.

    Args:
        module: Parsed module dict

    Returns:
        List of normalized records
    """
    records = []

    for idx, paragraph in enumerate(module["paragraphs"]):
        record = {
            "id": f"{module['module_id']}_p{idx}",
            "module_id": module["module_id"],
            "module_title": module["title"],
            "section": paragraph["section"],
            "text": paragraph["text"],
            "key_terms": module["key_terms"],
            "learning_objectives": module["learning_objectives"],
            "attribution": settings.attribution_openstax,
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "source": "OpenStax Biology 2e",
        }
        records.append(record)

    return records


def main():
    """Main entry point."""
    logger.info("Starting data normalization")

    processed_dir = Path(settings.data_processed_dir)
    input_path = processed_dir / "parsed_modules.json"

    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        logger.error("Run 'make parse-data' first")
        return

    # Load parsed modules
    parsed_modules = json.loads(input_path.read_text(encoding="utf-8"))
    logger.info(f"Loaded {len(parsed_modules)} parsed modules")

    # Normalize all modules
    all_records = []
    for module in parsed_modules:
        records = normalize_module(module)
        all_records.extend(records)
        logger.info(f"Normalized {module['module_id']}: {len(records)} records")

    # Save as JSONL (one record per line)
    output_path = Path(settings.data_books_jsonl)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        for record in all_records:
            f.write(json.dumps(record) + "\n")

    logger.success(f"✓ Normalized {len(all_records)} records")
    logger.success(f"✓ Saved to {output_path}")

    # Also save a summary JSON for easy inspection
    summary = {
        "total_records": len(all_records),
        "total_modules": len(parsed_modules),
        "modules": [
            {"id": m["module_id"], "title": m["title"], "paragraph_count": m["paragraph_count"]}
            for m in parsed_modules
        ],
        "sample_record": all_records[0] if all_records else None,
    }

    summary_path = processed_dir / "normalized_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info(f"Saved summary to {summary_path}")
    logger.info(f"Next step: run 'make build-kg' to build the knowledge graph")


if __name__ == "__main__":
    main()
