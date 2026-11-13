"""
Unit tests for scripts/ingest_books.py: module titles and chapters (no network).
"""

import json
from pathlib import Path

import pytest

from scripts import ingest_books

REPO_ROOT = Path(__file__).resolve().parents[2]

SUMMARY = """---
title: "U.S. History"
layout: page
---

<div data-type="abstract"></div>

1.  {: .preface} [Preface](contents/m52490.md)
2.  {: .chapter} [Early Globalization: The Atlantic World, 1492–1650](contents/m49991.md)
    1.  [Portuguese Exploration and Spanish Conquest](contents/m49994.md)
    2.  [Challenges to Spain’s Supremacy](contents/m49990.md)

3.  {: .chapter} [America\\'s War for Independence, 1775-1783](contents/m50025.md)
    1.  [The Early Years of the Revolution](contents/m50027.md)

4.  {: .part} Unit 2. The Cell
    1.  {: .chapter} [Cell Structure](contents/m44404.md)
        1.  [Studying Cells](contents/m44405.md)

5.  {: .appendix} [The Declaration of Independence](contents/m51696.md)
6.  {: .appendix} [Further Reading](contents/m51702.md)
7.  {: .chapter} [Duplicate](contents/m49994.md)
"""

MODULE = """---
title: "Challenges to Spain’s Supremacy"
layout: page
---

<div data-type="abstract" markdown="1">
By the end of this section, you will be able to:
</div>

For Europeans, the discovery of an Atlantic World meant newfound wealth.
"""


@pytest.mark.unit
class TestParseSummary:
    def test_entries_carry_link_title_and_chapter(self):
        entries = {e.filename: e for e in ingest_books.parse_summary_entries(SUMMARY)}

        assert entries["m52490.md"].chapter is None
        intro = entries["m49991.md"]
        assert (
            intro.link_title
            == intro.chapter
            == "Early Globalization: The Atlantic World, 1492–1650"
        )
        assert entries["m49990.md"] == ingest_books.SummaryEntry(
            "m49990.md", "Challenges to Spain’s Supremacy", intro.chapter
        )

    def test_markdown_escapes_are_removed(self):
        entries = {e.filename: e for e in ingest_books.parse_summary_entries(SUMMARY)}
        assert entries["m50027.md"].chapter == "America's War for Independence, 1775-1783"

    def test_parts_and_appendices_are_not_chapters(self):
        entries = {e.filename: e for e in ingest_books.parse_summary_entries(SUMMARY)}

        # A chapter nested in a part, with its sections indented one level deeper
        assert entries["m44404.md"].chapter == "Cell Structure"
        assert entries["m44405.md"].chapter == "Cell Structure"
        assert entries["m51696.md"].chapter is None
        assert entries["m51702.md"].chapter is None

    def test_duplicates_keep_the_first_entry_in_book_order(self):
        filenames = ingest_books.parse_summary(SUMMARY)
        assert filenames == [
            "m52490.md",
            "m49991.md",
            "m49994.md",
            "m49990.md",
            "m50025.md",
            "m50027.md",
            "m44404.md",
            "m44405.md",
            "m51696.md",
            "m51702.md",
        ]
        entries = {e.filename: e for e in ingest_books.parse_summary_entries(SUMMARY)}
        assert entries["m49994.md"].chapter.startswith("Early Globalization")


@pytest.mark.unit
class TestTitles:
    def test_front_matter_title(self):
        assert ingest_books.parse_front_matter_title(MODULE) == "Challenges to Spain’s Supremacy"

    def test_front_matter_title_of_a_tracked_module(self):
        text = (REPO_ROOT / "data/raw/us_history/m49990.md").read_text(encoding="utf-8")
        assert ingest_books.parse_front_matter_title(text) == "Challenges to Spain’s Supremacy"

    @pytest.mark.parametrize(
        ("text", "title"),
        [
            ("No front matter\n", None),
            ("---\nlayout: page\n---\nText", None),
            ('---\ntitle: "A &amp; <em>B</em>"\n---\n', "A & B"),
            ("---\ntitle: Unquoted: colon\nbad: [yaml\n---\n", "Unquoted: colon"),
        ],
    )
    def test_front_matter_edge_cases(self, text, title):
        assert ingest_books.parse_front_matter_title(text) == title

    def test_module_title_includes_the_chapter(self):
        assert ingest_books.format_module_title("Ch", "Introduction") == "Ch - Introduction"
        assert ingest_books.format_module_title(None, "Preface") == "Preface"
        assert ingest_books.format_module_title("Same", "Same") == "Same"


@pytest.mark.unit
def test_github_raw_records_use_front_matter_title_and_chapter(monkeypatch):
    pages = {
        "https://raw.example/book/SUMMARY.md": SUMMARY,
        "https://raw.example/book/contents/m49990.md": MODULE,
        # No front matter: the SUMMARY link text is the title
        "https://raw.example/book/contents/m49991.md": "Chapter introduction text.",
    }
    monkeypatch.setattr(ingest_books, "fetch_text", pages.get)
    book = ingest_books.BookConfig(title="US History", repo_url_raw="https://raw.example/book")

    records: list[dict] = []
    ingest_books._process_github_raw_book(book, "us_history", 0, records)

    chapter = "Early Globalization: The Atlantic World, 1492–1650"
    assert records == [
        {
            "module_id": "m49991",
            "module_title": chapter,
            "book_title": "US History",
            "chapter": chapter,
            "section": chapter,
            "text": "Chapter introduction text.",
            "key_terms": [],
            "subject_id": "us_history",
        },
        {
            "module_id": "m49990",
            "module_title": f"{chapter} - Challenges to Spain’s Supremacy",
            "book_title": "US History",
            "chapter": chapter,
            "section": "Challenges to Spain’s Supremacy",
            "text": (
                "By the end of this section, you will be able to:\n\n\n"
                "For Europeans, the discovery of an Atlantic World meant newfound wealth."
            ),
            "key_terms": [],
            "subject_id": "us_history",
        },
    ]


@pytest.mark.unit
def test_openstax_toc_pages_carry_their_chapter():
    numbered = (
        '<span class="os-number">1.1</span><span class="os-divider"> </span>'
        '<span class="os-text">Developing a Global Perspective</span>'
    )
    tree = {
        "title": "World History Volume 1",
        "contents": [
            {"slug": "preface", "title": "Preface"},
            {
                "title": "Unit 1",
                "contents": [
                    {
                        "title": '<span class="os-number">1</span><span class="os-text">Ch One</span>',
                        "contents": [
                            {"slug": "1-introduction", "title": "Introduction"},
                            {"slug": "1-1-global", "title": numbered},
                        ],
                    }
                ],
            },
        ],
    }

    assert ingest_books._collect_leaf_pages(tree) == [
        {"page_slug": "preface", "title": "Preface", "chapter": None},
        {"page_slug": "1-introduction", "title": "Introduction", "chapter": "Ch One"},
        {
            "page_slug": "1-1-global",
            "title": "Developing a Global Perspective",
            "chapter": "Ch One",
        },
    ]


@pytest.mark.unit
def test_openstax_web_records_use_page_title_and_chapter(monkeypatch):
    toc = [
        {"page_slug": "preface", "title": "Preface", "chapter": None},
        {"page_slug": "1-introduction", "title": "Introduction", "chapter": "Ch One"},
    ]
    monkeypatch.setattr(ingest_books, "fetch_openstax_toc", lambda slug: toc)
    monkeypatch.setattr(ingest_books, "fetch_openstax_page", lambda slug, page: f"Text {page}.")
    monkeypatch.setattr(ingest_books, "OPENSTAX_FETCH_DELAY", 0)
    book = ingest_books.BookConfig(
        title="World History Volume 1", source_type="openstax_web", openstax_slug="wh-1"
    )

    records: list[dict] = []
    ingest_books._process_openstax_web_book(book, "world_history", 0, records)

    assert [(r["module_id"], r["module_title"], r["chapter"], r["section"]) for r in records] == [
        ("preface", "Preface", None, "Preface"),
        ("1-introduction", "Ch One - Introduction", "Ch One", "Introduction"),
    ]


# ---------------------------------------------------------------------------
# OpenStax web pages: the CSS selectors that pick the content and drop the rest
# ---------------------------------------------------------------------------

PAGE_BODY = """
<h1>Trade Routes</h1>
<p>Merchants crossed the desert.</p>
<div data-type="note"><p>Link to learning</p></div>
<figure><figcaption>A caravan</figcaption></figure>
<nav>On this page</nav>
<script>var tracked = 1;</script>
<style>.x { color: red; }</style>
<footer>Page footer</footer>
<p>Cities grew along the routes.</p>
"""

PAGE_TEXT = "Trade Routes\nMerchants crossed the desert.\nCities grew along the routes."


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


def _serve(monkeypatch, html: str) -> list[str]:
    """Answer ``requests.get`` in ingest_books with this page; returns the URLs asked for."""
    asked: list[str] = []

    def fake_get(url: str, timeout: int) -> _Response:
        asked.append(url)
        return _Response(html)

    monkeypatch.setattr(ingest_books.requests, "get", fake_get)
    return asked


@pytest.mark.unit
@pytest.mark.parametrize(
    "wrapper",
    [
        # The page element wins over the <main> around it: the breadcrumb is not content
        '<main><p>Breadcrumb</p><div data-type="page">{body}</div></main>',
        "<main>{body}</main>",
        '<div id="main-content">{body}</div>',
    ],
    ids=["data-type-page", "main", "main-content"],
)
def test_openstax_page_text_keeps_the_prose_and_drops_the_rest(monkeypatch, wrapper):
    """The page text is the content element without notes, figures, navigation and code."""
    html = (
        "<html><body><nav>Site menu</nav>"
        + wrapper.format(body=PAGE_BODY)
        + "<footer>Site footer</footer></body></html>"
    )
    asked = _serve(monkeypatch, html)

    text = ingest_books.fetch_openstax_page("world-history-volume-1", "1-2-trade-routes")

    assert text == PAGE_TEXT
    assert asked == [
        f"{ingest_books.OPENSTAX_BASE_URL}/world-history-volume-1/pages/1-2-trade-routes"
    ]


def _client_rendered_page(state: dict) -> str:
    """A page whose content is only in the embedded state, escaped as OpenStax serves it."""
    embedded = json.dumps(state).replace("</", "<\\/")
    return (
        '<html><body><div id="root"></div>'
        f"<script>window.__PRELOADED_STATE__ = {embedded};</script>"
        "<script>var other = 2;</script></body></html>"
    )


@pytest.mark.unit
def test_preloaded_state_is_read_from_its_script_tag():
    state = {"content": {"page": {"content": PAGE_BODY}}}

    assert ingest_books._extract_preloaded_state(_client_rendered_page(state)) == state
    assert ingest_books._extract_preloaded_state("<html><script>var x = 1;</script></html>") is None


@pytest.mark.unit
def test_client_rendered_openstax_page_falls_back_to_the_embedded_state(monkeypatch):
    """Without a content element the text comes from the embedded page HTML.

    This path drops figures, navigation and code, and keeps notes: its selector list has no
    ``[data-type='note']``, unlike the one for server-rendered pages.
    """
    _serve(monkeypatch, _client_rendered_page({"content": {"page": {"content": PAGE_BODY}}}))

    text = ingest_books.fetch_openstax_page("world-history-volume-1", "1-2-trade-routes")

    assert text == (
        "Trade Routes\nMerchants crossed the desert.\nLink to learning\n"
        "Cities grew along the routes."
    )
