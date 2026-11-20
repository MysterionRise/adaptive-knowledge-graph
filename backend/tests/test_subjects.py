"""
Tests for the subject configuration loader (backend/app/core/subjects.py).

These exercise the public functions against the real config/subjects.yaml, so a
change to the config that breaks a subject fails here.
"""

import re
from unittest.mock import patch

import pytest

from backend.app.core.subjects import (
    SLUG_PATTERN,
    BookSource,
    SubjectConfig,
    SubjectsConfig,
    SubjectTheme,
    clear_subjects_cache,
    get_all_subjects,
    get_default_subject_id,
    get_subject,
    get_subject_ids,
    load_subjects_config,
    slug,
)

EXPECTED_SUBJECTS = {"us_history", "biology", "economics", "world_history"}


@pytest.fixture(autouse=True)
def fresh_config():
    clear_subjects_cache()
    yield
    clear_subjects_cache()


@pytest.mark.unit
class TestLoadSubjectsConfig:
    def test_loads_all_configured_subjects(self):
        config = load_subjects_config()

        assert isinstance(config, SubjectsConfig)
        assert config.default_subject == "us_history"
        assert set(config.subjects) == EXPECTED_SUBJECTS
        assert all(subject_id == s.id for subject_id, s in config.subjects.items())

    def test_config_is_cached_until_cleared(self):
        first = load_subjects_config()

        assert load_subjects_config() is first
        clear_subjects_cache()
        assert load_subjects_config() is not first

    def test_empty_config_is_rejected(self):
        with patch("backend.app.core.subjects.yaml.safe_load", return_value=None):
            with pytest.raises(ValueError, match="empty"):
                load_subjects_config()

    def test_every_subject_has_isolated_storage(self):
        subjects = get_all_subjects()
        indexes = [s.database.opensearch_index for s in subjects]
        prefixes = [s.database.label_prefix for s in subjects]

        assert len(set(indexes)) == len(indexes)
        assert len(set(prefixes)) == len(prefixes)
        for subject in subjects:
            assert subject.database.label_prefix == subject.id
            assert subject.database.opensearch_index == f"textbook_chunks_{subject.id}"
            assert subject.database.neo4j_database == "neo4j"

    def test_every_subject_is_complete(self):
        for subject in get_all_subjects():
            assert subject.name and subject.description
            assert subject.books
            assert "ONLY the provided" in subject.prompts.system_prompt
            assert subject.prompts.context_label
            assert subject.theme.primary_color.startswith("#")
            assert "default" in subject.theme.chapter_colors
            assert "CC BY 4.0" in subject.attribution


@pytest.mark.unit
class TestGetSubject:
    def test_default_subject(self):
        assert get_default_subject_id() == "us_history"
        assert get_subject().id == "us_history"
        assert get_subject(None) == get_subject("us_history")

    def test_economics(self):
        economics = get_subject("economics")

        assert isinstance(economics, SubjectConfig)
        assert economics.name == "Economics"
        assert economics.database.opensearch_index == "textbook_chunks_economics"
        book = economics.books[0]
        assert book.title == "Economics"
        assert book.source_type == "github_raw"
        assert book.repo_url_raw.endswith("/economics-book/master")
        assert (book.summary_path, book.content_path, book.branch) == (
            "SUMMARY.md",
            "contents",
            "master",
        )
        assert "economics tutor" in economics.prompts.system_prompt

    def test_openstax_web_books(self):
        world_history = get_subject("world_history")

        assert [b.openstax_slug for b in world_history.books] == [
            "world-history-volume-1",
            "world-history-volume-2",
        ]
        assert all(
            b.source_type == "openstax_web" and b.repo_url_raw is None for b in world_history.books
        )

    def test_biology_has_two_books(self):
        assert [b.title for b in get_subject("biology").books] == [
            "Biology 2e",
            "Concepts of Biology",
        ]

    def test_configured_books_keep_their_values_and_get_stable_ids(self):
        """#211: the ids that sources.yaml cites; a change here orphans the inventory."""
        books = {
            subject.id: [(b.id, b.connector, b.title, b.source_type) for b in subject.books]
            for subject in get_all_subjects()
        }

        assert books == {
            "us_history": [("us-history", "github_raw", "US History", "github_raw")],
            "biology": [
                ("biology-2e", "github_raw", "Biology 2e", "github_raw"),
                ("concepts-of-biology", "github_raw", "Concepts of Biology", "github_raw"),
            ],
            "economics": [("economics", "github_raw", "Economics", "github_raw")],
            "world_history": [
                (
                    "world-history-volume-1",
                    "openstax_web",
                    "World History Volume 1",
                    "openstax_web",
                ),
                (
                    "world-history-volume-2",
                    "openstax_web",
                    "World History Volume 2",
                    "openstax_web",
                ),
            ],
        }
        us_history = get_subject("us_history").books[0]
        assert us_history.repo_url_raw == (
            "https://raw.githubusercontent.com/philschatz/us-history-book/master"
        )

    def test_unknown_subject_lists_available_ones(self):
        with pytest.raises(KeyError) as error:
            get_subject("chemistry")

        message = str(error.value)
        assert "chemistry" in message
        for subject_id in EXPECTED_SUBJECTS:
            assert subject_id in message

    def test_all_subjects_and_ids_agree(self):
        ids = get_subject_ids()

        assert set(ids) == EXPECTED_SUBJECTS
        assert [s.id for s in get_all_subjects()] == ids


@pytest.mark.unit
class TestModelDefaults:
    def test_book_source_defaults(self):
        book = BookSource(title="Chemistry 2e")

        assert book.source_type == "github_raw"
        assert book.repo_url_raw is None and book.openstax_slug is None
        assert (book.summary_path, book.content_path, book.branch) == (
            "SUMMARY.md",
            "contents",
            "master",
        )

    def test_book_source_id_and_connector_have_defaults(self):
        """#211: both are optional, so a subjects.yaml written before them stays valid."""
        book = BookSource(title="Chemistry 2e")
        web = BookSource(title="Algebra & Trigonometry", source_type="openstax_web")

        assert (book.id, book.connector) == ("chemistry-2e", "github_raw")
        assert (web.id, web.connector) == ("algebra-trigonometry", "openstax_web")

    def test_book_source_explicit_id_and_connector_win(self):
        book = BookSource(title="US History", id="us-history-1e", connector="local_files")

        assert (book.id, book.connector) == ("us-history-1e", "local_files")

    def test_book_source_id_must_be_a_slug(self):
        with pytest.raises(ValueError, match="lower-case words joined by hyphens"):
            BookSource(title="Biology", id="Bio 2e")

    def test_title_without_latin_letters_still_gets_a_stable_id(self):
        """A configuration that loaded before the id existed must keep loading."""
        first, again, other = (BookSource(title=t) for t in ("生物学", "生物学", "化学"))

        assert re.fullmatch(r"book-[0-9a-f]{8}", first.id)
        assert first.id == again.id != other.id

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("US History", "us-history"),
            ("  World War II ", "world-war-ii"),
            ("Shays’ Rebellion", "shays-rebellion"),
            ("Hernán Cortés", "hernan-cortes"),
            ("401(k)", "401-k"),
            ("---", ""),
        ],
    )
    def test_slug(self, text, expected):
        assert slug(text) == expected
        assert not expected or re.fullmatch(SLUG_PATTERN, expected)

    def test_theme_chapter_colors_default_to_empty(self):
        theme = SubjectTheme(primary_color="#000", secondary_color="#111", accent_color="#222")

        assert theme.chapter_colors == {}
