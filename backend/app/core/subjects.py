"""
Subject configuration loader for multi-subject support.

Loads subject configuration from config/subjects.yaml and provides
Pydantic models for type-safe access to subject settings.
"""

import hashlib
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic import BaseModel, Field, model_validator

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
"""Identifiers of the domain artifacts (#211): lower-case words joined by single hyphens."""

_SLUG_SEPARATOR_RE = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    """
    Lower-case hyphenated identifier of a title or name.

    "Biology 2e" -> "biology-2e", "World War II" -> "world-war-ii". Accents are dropped and
    every other run of characters outside a-z and 0-9 becomes one hyphen. The result is
    empty when the text has no letter or digit.
    """
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return _SLUG_SEPARATOR_RE.sub("-", ascii_text.lower()).strip("-")


class BookSource(BaseModel):
    """
    Configuration for a book source.

    ``id`` and ``connector`` tie a book to its entry in the subject's source inventory
    (``data/domains/<subject_id>/sources.yaml``, #211). Both have defaults, so an entry
    without them stays valid: ``id`` is ``slug(title)`` ("US History" -> "us-history") and
    ``connector`` is the ``source_type``. A title without a letter or digit in a-z and 0-9
    gets "book-" and the first eight hex digits of its SHA-256. Set ``id`` explicitly before
    renaming a book whose id the inventory already uses.
    """

    title: str
    id: str = ""  # default: slug(title)
    source_type: str = "github_raw"  # "github_raw" or "openstax_web"
    connector: str = ""  # the ingestion connector; default: source_type
    # github_raw fields (existing, optional for openstax_web sources)
    repo_url_raw: str | None = None
    summary_path: str = "SUMMARY.md"
    content_path: str = "contents"
    branch: str = "master"
    # openstax_web fields
    openstax_slug: str | None = None  # e.g. "world-history-volume-1"

    @model_validator(mode="after")
    def _default_id_and_connector(self) -> "BookSource":
        if not self.id:
            digest = hashlib.sha256(self.title.encode("utf-8")).hexdigest()
            self.id = slug(self.title) or f"book-{digest[:8]}"
        if not re.fullmatch(SLUG_PATTERN, self.id):
            raise ValueError(
                f"book id {self.id!r} (title {self.title!r}) must be lower-case words joined "
                "by hyphens"
            )
        if not self.connector:
            self.connector = self.source_type
        return self


class SubjectPrompts(BaseModel):
    """LLM prompts for a subject."""

    system_prompt: str
    context_label: str


class SubjectDatabase(BaseModel):
    """Database configuration for a subject."""

    neo4j_database: str = "neo4j"
    label_prefix: str
    opensearch_index: str


class SubjectTheme(BaseModel):
    """Frontend theme configuration for a subject."""

    primary_color: str
    secondary_color: str
    accent_color: str
    chapter_colors: dict[str, str] = Field(default_factory=dict)


class SubjectConfig(BaseModel):
    """Complete configuration for a subject."""

    id: str  # Subject ID (e.g., "us_history", "biology")
    name: str
    description: str
    database: SubjectDatabase
    books: list[BookSource]
    prompts: SubjectPrompts
    theme: SubjectTheme
    attribution: str


class SubjectsConfig(BaseModel):
    """Root configuration containing all subjects."""

    default_subject: str
    subjects: dict[str, SubjectConfig]


def _find_config_path() -> Path:
    """Find config/subjects.yaml: first under the working directory, then the repo root."""
    # backend/app/core/subjects.py -> parents[3] is the repository root
    repo_root = Path(__file__).resolve().parents[3]
    possible_paths = [
        Path.cwd() / "config" / "subjects.yaml",
        repo_root / "config" / "subjects.yaml",
    ]

    for path in possible_paths:
        if path.exists():
            return path

    raise FileNotFoundError(
        f"Could not find subjects.yaml. Tried: {[str(p) for p in possible_paths]}"
    )


def _parse_subject_config(subject_id: str, data: dict[str, Any]) -> SubjectConfig:
    """Parse a subject configuration from YAML data."""
    return SubjectConfig(
        id=subject_id,
        name=data["name"],
        description=data["description"],
        database=SubjectDatabase(**data["database"]),
        books=[BookSource(**book) for book in data["books"]],
        prompts=SubjectPrompts(**data["prompts"]),
        theme=SubjectTheme(**data["theme"]),
        attribution=data["attribution"],
    )


@lru_cache(maxsize=1)
def load_subjects_config() -> SubjectsConfig:
    """
    Load and cache subjects configuration from YAML file.

    Returns:
        SubjectsConfig with all subject configurations

    Raises:
        FileNotFoundError: If subjects.yaml is not found
        ValueError: If YAML is invalid
    """
    config_path = _find_config_path()
    logger.info(f"Loading subjects configuration from {config_path}")

    with open(config_path, encoding="utf-8") as f:
        raw_config = yaml.safe_load(f)

    if not raw_config:
        raise ValueError("subjects.yaml is empty")

    subjects = {}
    for subject_id, subject_data in raw_config.get("subjects", {}).items():
        subjects[subject_id] = _parse_subject_config(subject_id, subject_data)

    config = SubjectsConfig(
        default_subject=raw_config.get("default_subject", "us_history"),
        subjects=subjects,
    )

    logger.success(f"Loaded {len(subjects)} subjects: {list(subjects.keys())}")
    return config


def get_subject(subject_id: str | None = None) -> SubjectConfig:
    """
    Get configuration for a specific subject.

    Args:
        subject_id: Subject identifier (e.g., "us_history", "biology").
                   If None, returns the default subject.

    Returns:
        SubjectConfig for the requested subject

    Raises:
        KeyError: If subject_id is not found
    """
    config = load_subjects_config()

    if subject_id is None:
        subject_id = config.default_subject

    if subject_id not in config.subjects:
        available = list(config.subjects.keys())
        raise KeyError(f"Subject '{subject_id}' not found. Available subjects: {available}")

    return config.subjects[subject_id]


def get_all_subjects() -> list[SubjectConfig]:
    """
    Get all available subject configurations.

    Returns:
        List of all SubjectConfig objects
    """
    config = load_subjects_config()
    return list(config.subjects.values())


def get_subject_ids() -> list[str]:
    """
    Get list of all available subject IDs.

    Returns:
        List of subject identifiers
    """
    config = load_subjects_config()
    return list(config.subjects.keys())


def get_default_subject_id() -> str:
    """
    Get the default subject ID.

    Returns:
        Default subject identifier
    """
    config = load_subjects_config()
    return config.default_subject


def clear_subjects_cache() -> None:
    """Clear the cached subjects configuration (for testing/hot reload)."""
    load_subjects_config.cache_clear()
    logger.info("Cleared subjects configuration cache")
