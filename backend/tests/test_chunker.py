"""
Tests for RAG chunking and OpenStax markup cleaning (backend/app/rag/chunker.py).

The markup snippets are copied (trimmed) from data/raw/us_history/*.md and
data/processed/books_*.jsonl, the sources whose ``cnx-pi`` markup reached the
OpenSearch index before ``clean_text`` was applied.
"""

from pathlib import Path

import pytest

from backend.app.rag.chunker import TextChunker, chunk_for_rag, clean_text

RAW_US_HISTORY_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "us_history"

# data/raw/us_history/m49991.md (chapter introduction), trimmed
INTRO_MODULE = """---
title: "Introduction"
layout: page
---


<cnx-pi data-type="cnx.flag.introduction"> class="introduction" </cnx-pi>

<div data-type="abstract" markdown="1">
* Portuguese Exploration and Spanish Conquest
* Religious Upheavals in the Developing Atlantic World

</div>

<cnx-pi data-type="cnx.eoc">class="summary" title="Summary"</cnx-pi>

<cnx-pi data-type="cnx.eoc">class="review-questions" title="Review Questions"</cnx-pi>

 ![A woodcut shows King Ferdinand of Spain as a crowned, robed ruler seated on a throne.](../resources/CNX_History_02_00_Ferdinand.jpg "After Christopher Columbus &#x201C;discovered&#x201D; the New World, he sent letters home to Spain (credit: Library of Congress)."){: #CNX_History_02_00_Ferdinand}

The story of the Atlantic World is the story of global migration, a migration driven in large part by the actions and aspirations of the ruling heads of Europe. Columbus is hardly visible in this illustration of his ships making landfall on the Caribbean island of Hispaniola ([\\[link\\]](#CNX_History_02_00_Ferdinand)).
"""

# data/raw/us_history/m49986.md, trimmed
TERM_AND_NOTE = """Some scholars believe that between nine and fifteen thousand years ago, a land bridge existed between Asia and North America that we now call **Beringia**{: data-type="term"}. The first inhabitants of what would be named the Americas migrated across this bridge in search of food.

<div data-type="note" data-has-label="true" class="history click-and-explore" data-label="Click and Explore" markdown="1">
<span data-type="media" id="eip-idp44469952" data-alt=" "> ![ ](../resources/OSC_Interactive_120.png) </span>
Visit the [University of Arizona Library Special Collections][1] to view facsimiles and descriptions of two of the four surviving Mayan codices.

</div>

<q>He narrated that mounted men would come to this land in a great wooden house \\[ships\\] this structure was to lodge many men.</q>

[1]: http://openstax.org/l/mayancodex
"""

GLOSSARY = """<div data-type="glossary" markdown="1">
### Glossary
{: data-type="glossary-title"}

Beringia
: an ancient land bridge linking Asia and North America
^

*chasquis*
: Incan relay runners used to send messages over great distances

</div>
"""

# data/raw/us_history/m50038.md, trimmed
TABLE = """<table id="Table_08_01_BillRights" pgwide="2" summary="A table lists the rights protected by the first ten amendments to the Constitution. Amendment 10 protects states&#x2019; rights."><caption><span data-type="title">Rights Protected by the First Ten Amendments</span></caption><tbody>
<tr>
<td>Amendment 1</td>
<td>Right to freedoms of religion and speech</td>
</tr>
</tbody></table>
"""

# data/processed/books_economics.jsonl (m48644), MathML
MATHML = (
    '<math xmlns="http://www.w3.org/1998/Math/MathML"><mtext>Budget</mtext><mo>=</mo>'
    "<msub><mtext>P</mtext><mn>1</mn></msub><msub><mtext> × Q</mtext><mn>1</mn>"
    '</msub><msub><mtext> + P</mtext><mrow><mn>2</mn><mspace width="0.2em" />'
    "</mrow></msub><msub><mtext>× Q</mtext><mn>2</mn></msub></math>\n\n"
    "where P and Q are the price and quantity of items purchased."
)

# data/processed/books_economics.jsonl (m48614): the first price-elasticity example
ELASTICITY = (
    '<math xmlns="http://www.w3.org/1998/Math/MathML"><mtable columnalign="right center left">'
    "<mtr><mtd><mtext>% change in quantity</mtext></mtd><mtd><mo>=</mo></mtd><mtd><mfrac>"
    "<mrow><mn>3,000</mn><mo>–</mo><mn>2,800</mn></mrow><mrow><mo>(</mo><mn>3,000</mn>"
    "<mo>+</mo><mn>2,800</mn><mo>)</mo><mo>/2</mo></mrow></mfrac><mn> × 100</mn></mtd></mtr>"
    "<mtr><mtd /><mtd><mo>=</mo></mtd><mtd><mfrac><mn>200</mn><mn>2,900</mn></mfrac>"
    "<mn> × 100</mn></mtd></mtr><mtr><mtd /><mtd><mo>=</mo></mtd><mtd><mn>6.9</mn></mtd></mtr>"
    "<mtr><mtd><mtext>Price Elasticity of Demand</mtext></mtd><mtd><mo>=</mo></mtd><mtd><mfrac>"
    "<mrow><mn>    6.9%</mn></mrow><mrow><mn>–15.4%</mn></mrow></mfrac></mtd></mtr>"
    "<mtr><mtd /><mtd><mo>=</mo></mtd><mtd><mn>0.45</mn></mtd></mtr></mtable></math>"
)

# data/processed/books_economics.jsonl (m48662, m48729): exponents written as <sup>
HHI = "it has 100% market share. The HHI is 100<sup>2</sup> = 10,000."
HHI_SUM = (
    "In this case, the HHI is 16<sup>2</sup> + 10<sup>2</sup> + 8<sup>2</sup> + "
    "7(6<sup>2</sup>) + 8(3<sup>2</sup>) = 744."
)
HYPERINFLATION = "for an annual rate that month of 4.69 × 10<sup>28</sup>%), came in the same month"

# data/processed/books_us_history.jsonl: an image title cut short upstream, then prose
IMAGE_REMNANT = (
    'n. The strand binding the three women may represent tobacco."){: #CNX_History_01_00_ThreeWomen}'
    "\n\nSome scholars believe that a land bridge existed between Asia and North America."
)

# data/processed/books_us_history.jsonl (m52490): newline markers after chapter titles
NEWLINE_MARKERS = (
    "Chapter 1: The Americas, Europe, and Africa before 1492* * *\n"
    '{: data-type="newline"}\n\n'
    " Chapter 2: Early Globalization: The Atlantic World, 1492–1650* * *\n"
    '{: data-type="newline"}\n'
)

MARKUP_FRAGMENTS = ("cnx-pi", "data-type", "class=", "title=", "{:", "<", ">", "](", "\\[")


def assert_no_markup(text: str) -> None:
    for fragment in MARKUP_FRAGMENTS:
        assert fragment not in text, f"{fragment!r} left in {text!r}"


@pytest.mark.unit
class TestCleanText:
    def test_strips_cnx_processing_instructions_front_matter_and_images(self):
        cleaned = clean_text(INTRO_MODULE)

        assert_no_markup(cleaned)
        assert "layout: page" not in cleaned
        assert "Review Questions" not in cleaned
        assert "woodcut" not in cleaned  # image alt text and title are dropped
        assert cleaned.startswith("* Portuguese Exploration and Spanish Conquest")
        assert "island of Hispaniola." in cleaned  # "([link])" figure reference removed

    def test_strips_raw_processing_instructions(self):
        text = '<?cnx.eoc class="summary" title="Summary"?>The Townshend Acts raised taxes.'
        assert clean_text(text) == "The Townshend Acts raised taxes."

    def test_unwraps_key_terms_notes_links_and_quotes(self):
        cleaned = clean_text(TERM_AND_NOTE)

        assert_no_markup(cleaned)
        assert "that we now call Beringia. The first inhabitants" in cleaned
        assert "Visit the University of Arizona Library Special Collections to view" in cleaned
        assert "openstax.org" not in cleaned  # reference-style link definition removed
        assert "a great wooden house [ships] this structure" in cleaned

    def test_joins_glossary_definition_lists(self):
        cleaned = clean_text(GLOSSARY)

        assert_no_markup(cleaned)
        assert "Glossary" in cleaned
        assert "Beringia: an ancient land bridge linking Asia and North America" in cleaned
        assert "chasquis: Incan relay runners" in cleaned
        assert "^" not in cleaned

    def test_keeps_table_caption_and_cells_but_not_summary_attribute(self):
        cleaned = clean_text(TABLE)

        assert_no_markup(cleaned)
        assert "Rights Protected by the First Ten Amendments" in cleaned
        assert "Amendment 1" in cleaned
        assert "Right to freedoms of religion and speech" in cleaned
        assert "A table lists" not in cleaned

    def test_linearises_mathml_subscripts(self):
        cleaned = clean_text(MATHML)

        assert_no_markup(cleaned)
        assert cleaned.startswith("Budget = P_1 × Q_1 + P_2")
        assert cleaned.endswith("where P and Q are the price and quantity of items purchased.")

    def test_linearises_mathml_fractions_without_merging_numbers(self):
        assert clean_text(ELASTICITY) == (
            "% change in quantity = (3,000 – 2,800)/((3,000 + 2,800)/2) × 100\n"
            "= 200/2,900 × 100\n"
            "= 6.9\n"
            "Price Elasticity of Demand = 6.9%/(–15.4%)\n"
            "= 0.45"
        )

    @pytest.mark.parametrize(
        ("math", "expected"),
        [
            # m48626, m48700, m48715: powers
            ("<mi>π</mi><msup><mi>r</mi><mn>2</mn></msup>", "πr^2"),
            (
                "<mrow><mn>3</mn><mo>,</mo><mn>000</mn><msup><mrow><mo>(</mo><mn>1</mn><mo>+</mo>"
                "<mn>.07</mn><mo>)</mo></mrow><mrow><mn>40</mn></mrow></msup><mo>=</mo>"
                "<mtext>$</mtext><mn>44,923</mn></mrow>",
                "3,000(1 + .07)^40 = $44,923",
            ),
            (
                "<msup><mtext>Future Value = Present Value × (1 + g)</mtext>"
                "<mtext>n</mtext></msup>",
                "Future Value = Present Value × (1 + g)^n",
            ),
            # m48614: an inequality keeps its operator
            (
                "<mtext>% change in quantity</mtext><mo>&gt;</mo><mtext>% change in price</mtext>",
                "% change in quantity > % change in price",
            ),
            ("<msubsup><mi>x</mi><mn>1</mn><mn>2</mn></msubsup>", "x_1^2"),
            (
                "<msqrt><mn>16</mn></msqrt><mo>+</mo><mroot><mn>8</mn><mn>3</mn></mroot>",
                "√(16) + 8^(1/3)",
            ),
            (
                "<mfenced><mn>1</mn><mn>2</mn></mfenced><mo>&#x2260;</mo><mi>x</mi>",
                "(1, 2) ≠ x",
            ),
            (
                "<mfrac><mrow><mi>a</mi><mo>+</mo><mi>b</mi></mrow><mi>c</mi></mfrac>",
                "(a + b)/c",
            ),
        ],
    )
    def test_linearises_mathml_scripts(self, math, expected):
        block = f'<math xmlns="http://www.w3.org/1998/Math/MathML">{math}</math>'
        assert clean_text(block) == expected

    def test_malformed_mathml_falls_back_to_separate_tokens(self):
        assert clean_text("<math><mn>200</mn><mn>2,900</math> was the ratio.") == (
            "200 2,900 was the ratio."
        )

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            (HHI, "it has 100% market share. The HHI is 100^2 = 10,000."),
            (HHI_SUM, "In this case, the HHI is 16^2 + 10^2 + 8^2 + 7(6^2) + 8(3^2) = 744."),
            (
                HYPERINFLATION,
                "for an annual rate that month of 4.69 × 10^28%), came in the same month",
            ),
            ("(1 + interest rate)<sup>time</sup>", "(1 + interest rate)^time"),
            ("x<sup>n + 1</sup>", "x^(n + 1)"),
            # ordinals, marks and footnote markers are not exponents
            ("Work in the 21<sup>st</sup> Century", "Work in the 21st Century"),
            ("courses for AP<sup>&#xAE;</sup> students", "courses for AP® students"),
            ("Total Revenue<sup>*</sup>", "Total Revenue*"),
            (
                'The Chart<sup><a data-type="footnote-link" href="#footnote1">1</a></sup> shows',
                "The Chart shows",
            ),
        ],
    )
    def test_superscripts(self, text, expected):
        assert clean_text(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "A firm should expand output if P > MC and cut output if P < MC.",
            "If P<MC, reduce output; if P>MC, expand it.",
            "The condition P<AVC means shut down, while P>ATC means profit.",
            "If Qd<Qs there is a surplus; if Qd>Qs a shortage.",
            "the ratio a<b holds, but c>d does not",
            "The placeholder <name> should be replaced.",
            "Use the form <Your Name> <Your Address> and sign.",
            "less than <5% of the labor force",
            "Is x<? Yes. Is y?>",
            "Texas A&M, AT&T, Marks&notes and the &copy symbol",
            "x**2 + y**2 = z**2 and a*b*c",
            "call __init__ to construct snake_case_name",
            "Significant at the 1% level*** and Stars: * * *",
            "Refs [1][2][3] support this, see [sic].",
            "The cost [C](in dollars) rises.",
            "[Answer]: The equilibrium price is $5.",
            "[1]: Smith, 2020",
            "Press the # key, C# and Channel 5 ##",
            'The book title="Common Sense" was popular and type="A" personalities',
            "The <firm decides\nto expand output> today.",
        ],
    )
    def test_prose_that_only_looks_like_markup_is_kept(self, text):
        assert clean_text(text) == text

    def test_reference_links_need_a_definition(self):
        text = "See [the codices][1] and [the Aztec][2].\n\n[1]: http://openstax.org/l/mayancodex"

        assert clean_text(text) == "See the codices and [the Aztec][2]."

    def test_table_rule_rows_are_removed_without_splitting_the_table(self):
        text = "| Price | Quantity |\n|---|---|\n| $1 | 100 |\n|----------\n| $2 | 80 |"

        assert clean_text(text) == "| Price | Quantity |\n| $1 | 100 |\n| $2 | 80 |"

    def test_removes_image_title_remnants(self):
        cleaned = clean_text(IMAGE_REMNANT)

        assert (
            cleaned
            == "Some scholars believe that a land bridge existed between Asia and North America."
        )

    def test_removes_newline_markers_and_rules(self):
        cleaned = clean_text(NEWLINE_MARKERS)

        assert cleaned == (
            "Chapter 1: The Americas, Europe, and Africa before 1492\n\n"
            "Chapter 2: Early Globalization: The Atlantic World, 1492–1650"
        )

    def test_decodes_entities_emphasis_escapes_and_heading_markers(self):
        text = (
            "### About OpenStax   {#eip-38}\n\n"
            "Welcome to *U.S. History*, an OpenStax resource for AP<sup>&#xAE;</sup> "
            "courses &amp; more. See press\\\\\\_releases and E<sub>1</sub>."
        )
        cleaned = clean_text(text)

        assert cleaned == (
            "About OpenStax\n\n"
            "Welcome to U.S. History, an OpenStax resource for AP® courses & more. "
            "See press_releases and E1."
        )

    def test_keeps_bullets_and_escaped_asterisks(self):
        text = "* First point\n* Second point with 2 \\* 3 = 6"
        assert clean_text(text) == "* First point\n* Second point with 2 * 3 = 6"

    def test_preserves_sentences_and_paragraphs(self):
        text = "First sentence.  Second   sentence!\n\n\n\nNew paragraph?\n"
        assert clean_text(text) == "First sentence. Second sentence!\n\nNew paragraph?"

    def test_plain_text_is_unchanged(self):
        text = "Supply and demand determine the equilibrium price.\n\nPrices adjust."
        assert clean_text(text) == text

    def test_is_idempotent(self):
        once = clean_text(INTRO_MODULE + TERM_AND_NOTE + GLOSSARY + TABLE)
        assert clean_text(once) == once

    @pytest.mark.parametrize("text", ["", "   ", '<cnx-pi data-type="cnx.eoc">class="x"</cnx-pi>'])
    def test_empty_or_markup_only_text(self, text):
        assert clean_text(text) == ""

    @pytest.mark.skipif(not RAW_US_HISTORY_DIR.is_dir(), reason="raw OpenStax data not present")
    def test_no_markup_survives_in_any_raw_us_history_module(self):
        paths = sorted(RAW_US_HISTORY_DIR.glob("*.md"))
        assert paths

        for path in paths:
            cleaned = clean_text(path.read_text(encoding="utf-8"))
            for fragment in ("cnx-pi", "data-type=", "{:", "<div", "<span", "](../resources"):
                assert fragment not in cleaned, f"{fragment!r} left in {path.name}"


@pytest.mark.unit
class TestTextChunker:
    SENTENCES = " ".join(f"Sentence number {i} explains a concept." for i in range(40))

    def test_cleans_markup_before_chunking_by_default(self):
        chunks = TextChunker(chunk_size=200, chunk_overlap=20).chunk_text(
            INTRO_MODULE + TERM_AND_NOTE
        )

        assert chunks
        for chunk in chunks:
            assert_no_markup(chunk["text"])

    def test_clean_markup_can_be_disabled(self):
        text = '**Beringia**{: data-type="term"} was a land bridge.'
        chunks = TextChunker(chunk_size=500, chunk_overlap=0, clean_markup=False).chunk_text(text)

        assert chunks[0]["text"] == text

    def test_breaks_at_sentence_boundaries_with_overlap(self):
        chunker = TextChunker(chunk_size=200, chunk_overlap=40)
        chunks = chunker.chunk_text(self.SENTENCES)

        assert len(chunks) > 3
        for chunk in chunks[:-1]:
            assert chunk["text"].endswith("concept.")
        for previous, current in zip(chunks, chunks[1:], strict=False):
            assert current["start_char"] < previous["end_char"]  # overlapping windows
            assert current["start_char"] > previous["start_char"]  # always advancing
        assert chunks[-1]["text"].endswith("Sentence number 39 explains a concept.")

    def test_sequential_ids_links_and_metadata(self):
        chunker = TextChunker(chunk_size=200, chunk_overlap=20)
        chunks = chunker.chunk_text(
            self.SENTENCES, metadata={"module_id": "m1", "chapter": "c", "section": "s"}
        )

        assert [c["id"] for c in chunks] == [f"m1_{i}" for i in range(len(chunks))]
        assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
        assert chunks[0]["previous_chunk_id"] is None
        assert chunks[-1]["next_chunk_id"] is None
        for previous, current in zip(chunks, chunks[1:], strict=False):
            assert previous["next_chunk_id"] == current["id"]
            assert current["previous_chunk_id"] == previous["id"]
        assert all(
            c["module_id"] == "m1" and c["chapter"] == "c" and c["section"] == "s" for c in chunks
        )

    def test_id_prefix_prefers_id_then_module_then_default(self):
        chunker = TextChunker(chunk_size=500, chunk_overlap=0)

        assert (
            chunker.chunk_text("Short text.", {"id": "doc", "module_id": "m"})[0]["id"] == "doc_0"
        )
        assert chunker.chunk_text("Short text.", {"module_id": "m"})[0]["id"] == "m_0"
        assert chunker.chunk_text("Short text.")[0]["id"] == "chunk_0"

    def test_previous_chunk_id_and_start_index(self):
        chunks = TextChunker(chunk_size=500, chunk_overlap=0).chunk_text(
            "Short text.", {"module_id": "m"}, previous_chunk_id="m_4", start_index=5
        )

        assert chunks[0]["id"] == "m_5"
        assert chunks[0]["chunk_index"] == 5
        assert chunks[0]["previous_chunk_id"] == "m_4"

    def test_untracked_chunks_have_no_links(self):
        chunks = TextChunker(chunk_size=200, chunk_overlap=20, track_sequential=False).chunk_text(
            self.SENTENCES
        )

        assert chunks
        assert all("previous_chunk_id" not in c and "next_chunk_id" not in c for c in chunks)

    @pytest.mark.parametrize("text", ["", '<cnx-pi data-type="cnx.eoc">class="x"</cnx-pi>'])
    def test_empty_text_gives_no_chunks(self, text):
        assert TextChunker().chunk_text(text) == []

    def test_defaults_come_from_settings(self):
        from backend.app.core.settings import settings

        chunker = TextChunker()

        assert chunker.chunk_size == settings.rag_chunk_size
        assert chunker.chunk_overlap == settings.rag_chunk_overlap
        assert chunker.clean_markup is True


@pytest.mark.unit
class TestChunkRecords:
    def records(self):
        long_text = " ".join(f"Point {i} about the colonies." for i in range(30))
        return [
            {"module_id": "m1", "section": "a", "text": long_text},
            {"module_id": "m1", "section": "b", "text": long_text},
            {"module_id": "m2", "section": "c", "text": "The Stamp Act of 1765 taxed paper."},
            {"module_id": "m3", "section": "d", "text": ""},
        ]

    def test_links_records_of_one_module_with_unique_ids(self):
        chunks, first = TextChunker(chunk_size=150, chunk_overlap=20).chunk_records(self.records())

        m1 = [c for c in chunks if c["module_id"] == "m1"]
        ids = [c["id"] for c in m1]
        assert len(ids) == len(set(ids))
        assert [c["chunk_index"] for c in m1] == list(range(len(m1)))
        for previous, current in zip(m1, m1[1:], strict=False):
            assert previous["next_chunk_id"] == current["id"]
            assert current["previous_chunk_id"] == previous["id"]
        assert first == {"m1": "m1_0", "m2": "m2_0"}  # m3 has no text

    def test_modules_are_not_linked_to_each_other(self):
        chunks, _ = TextChunker(chunk_size=150, chunk_overlap=20).chunk_records(self.records())

        m2 = [c for c in chunks if c["module_id"] == "m2"]
        assert len(m2) == 1
        assert m2[0]["previous_chunk_id"] is None
        assert m2[0]["next_chunk_id"] is None
        assert "text" in m2[0] and m2[0]["section"] == "c"

    def test_without_grouping_records_are_independent(self):
        chunks, first = TextChunker(chunk_size=150, chunk_overlap=20).chunk_records(
            self.records(), group_by=None
        )

        assert first == {}
        starts = [c for c in chunks if c["chunk_index"] == 0]
        assert len(starts) == 3
        assert all(c["previous_chunk_id"] is None for c in starts)

    def test_chunk_for_rag_returns_tuple_or_list(self):
        records = [{"module_id": "m1", "text": INTRO_MODULE}]

        chunks, first = chunk_for_rag(records)
        legacy = chunk_for_rag(records, with_sequential_linking=False)

        assert first == {"m1": "m1_0"}
        assert isinstance(legacy, list)
        assert [c["text"] for c in legacy] == [c["text"] for c in chunks]
        for chunk in chunks:
            assert_no_markup(chunk["text"])

    def test_chunk_for_rag_can_keep_markup(self):
        records = [{"module_id": "m1", "text": '<cnx-pi data-type="cnx.eoc">x</cnx-pi> Prose.'}]

        chunks, _ = chunk_for_rag(records, clean_markup=False)

        assert "cnx-pi" in chunks[0]["text"]
