"""
Tests for knowledge-graph concept extraction and graph building.

Covers backend/app/kg/builder.py and its helpers in kg/normalize.py,
kg/stopwords.py and kg/markup.py. YAKE is replaced by a deterministic fake in
most tests so the expected concepts are exact; a few tests run the real YAKE.
"""

from unittest.mock import MagicMock

import networkx as nx
import pytest

from backend.app.kg.builder import (
    DEFAULT_COOCCURRENCE_THRESHOLD,
    PREREQ_PATTERNS,
    STOP_CONCEPTS,
    KGBuilder,
    _CaseStats,
    is_stop_concept,
)
from backend.app.kg.markup import (
    STRUCTURAL_SECTION_TITLES,
    extract_glossary,
    extract_marked_terms,
    strip_structural_sections,
)
from backend.app.kg.normalize import (
    concept_key,
    display_name,
    is_acronym,
    normalize_concept,
    singularize,
    split_abbreviations,
    tokenize,
)
from backend.app.kg.schema import RelationshipType
from backend.app.kg.stopwords import is_valid_concept


class FakeKeywordExtractor:
    """Stands in for YAKE: returns ``always`` plus the ``vocabulary`` phrases found in the text."""

    def __init__(self, vocabulary=(), always=()):
        self.vocabulary = list(vocabulary)
        self.always = list(always)
        self.texts: list[str] = []

    def extract_keywords(self, text):
        self.texts.append(text)
        lowered = text.lower()
        found = [phrase for phrase in self.vocabulary if phrase.lower() in lowered]
        return [(phrase, 0.1) for phrase in [*self.always, *found]]


def make_builder(vocabulary=(), always=(), **kwargs) -> KGBuilder:
    builder = KGBuilder(**kwargs)
    builder.keyword_extractor = FakeKeywordExtractor(vocabulary, always)
    return builder


def record(module_id: str, text: str, key_terms=(), title=None) -> dict:
    return {
        "module_id": module_id,
        "module_title": title or f"US History - {module_id}",
        "section": module_id,
        "key_terms": list(key_terms),
        "text": text,
    }


def edges(kg, rel_type: RelationshipType) -> list:
    return [r for r in kg.relationships if r.type == rel_type]


# A two-module corpus in the shape of data/processed/books_us_history.jsonl.
STAMP_ACT_PARAGRAPH = (
    'Parliament passed the **Stamp Act**{: data-type="term"} in 1765, and the '
    '**Sons of Liberty**{: data-type="term"} organized protests against it.'
)
COLONIAL_PROTESTS = "\n\n".join(
    [
        '<cnx-pi data-type="cnx.flag.introduction"> class="introduction" </cnx-pi>',
        '<cnx-pi data-type="cnx.eoc">class="review-questions" title="Review Questions"</cnx-pi>',
        STAMP_ACT_PARAGRAPH,
        *[f"Protest {i}: the Sons of Liberty burned copies of the Stamp Act." for i in range(5)],
        "Merchants in Boston boycotted British goods.",
        "### Section Summary",
        "The Stamp Act united the colonies against Parliament.",
        "### Review Questions",
        "Which of the following explains why colonists opposed the Stamp Act?",
        '### Glossary\n{: data-type="glossary-title"}',
        "Stamp Act\n: a 1765 tax on printed paper in the colonies\n^",
        "Sons of Liberty\n: artisans and merchants who opposed the Stamp Act",
    ]
)
TOWNSHEND_ACTS = "\n\n".join(
    [
        'The **Townshend Acts**{: data-type="term"} of 1767 taxed glass, lead, and tea.',
        "Colonists compared the Townshend Acts with the Stamp Act.",
        "Merchants in Boston again boycotted British goods.",
        "### Glossary",
        "Townshend Acts\n: taxes on imported goods passed after the repeal of the Stamp Act",
    ]
)
CORPUS = [record("m1", COLONIAL_PROTESTS), record("m2", TOWNSHEND_ACTS)]
VOCABULARY = ["British Goods", "Boston"]
NOISE = ["Data-Type", "Cnx-Pi", "Review Questions", "Summary", "Title", "Explain the Factors"]


@pytest.mark.unit
class TestNormalize:
    def test_tokenize_keeps_inner_punctuation(self):
        assert tokenize("Spanish-American War, U.S. ’s") == ["spanish-american", "war", "u.s", "s"]

    @pytest.mark.parametrize(
        ("word", "singular"),
        [
            ("americans", "american"),
            ("colonies", "colony"),
            ("taxes", "tax"),
            ("churches", "church"),
            ("classes", "class"),
            ("economics", "economics"),
            ("status", "status"),
            ("crisis", "crisis"),
            ("famous", "famous"),
            ("gas", "gas"),
            ("war", "war"),
        ],
    )
    def test_singularize(self, word, singular):
        assert singularize(word) == singular

    def test_concept_key_merges_case_and_plural_variants(self):
        assert concept_key("Americans") == concept_key("american") == concept_key("AMERICAN")
        assert concept_key("Standards of Living") == concept_key("standard of living")
        assert concept_key("Review Questions") == "review question"
        assert concept_key("!!!") == ""

    @pytest.mark.parametrize(
        ("raw", "normalized"),
        [
            ("**Beringia**", "Beringia"),
            ("“slave power”", "slave power"),
            ("  the   Reign of Terror. ", "Reign of Terror"),
            ("Shays’s Rebellion", "Shays’s Rebellion"),
            ("Standard &amp; Poor’s 500 Index", "Standard & Poor’s 500 Index"),
            ("*chasquis*", "chasquis"),
            ("(", ""),
        ],
    )
    def test_normalize_concept(self, raw, normalized):
        assert normalize_concept(raw) == normalized

    def test_split_abbreviations(self):
        assert split_abbreviations("gross domestic product (GDP)") == (
            "gross domestic product",
            ["GDP"],
        )
        assert split_abbreviations("long-run average cost (LRAC) curve") == (
            "long-run average cost curve",
            ["LRAC"],
        )
        assert split_abbreviations("401(k)") == ("401(k)", [])
        assert split_abbreviations("Opportunity Cost") == ("Opportunity Cost", [])

    def test_is_acronym(self):
        assert is_acronym("GDP") and is_acronym("NAACP") and is_acronym("WMDs") is False
        assert not is_acronym("Gdp") and not is_acronym("Real GDP") and not is_acronym("I")

    @pytest.mark.parametrize(
        ("name", "display"),
        [
            ("french and indian war", "French and Indian War"),
            ("real GDP", "Real GDP"),
            ("NORTH AMERICAN INDIANS", "North American Indians"),
            ("spanish-american war", "Spanish-American War"),
            ("aggregate demand/aggregate supply model", "Aggregate Demand/Aggregate Supply Model"),
            ("Alexis de Tocqueville", "Alexis de Tocqueville"),
            ("the Terror", "The Terror"),
            ("NAACP", "NAACP"),
            ("McCarthyism", "McCarthyism"),
        ],
    )
    def test_display_name(self, name, display):
        assert display_name(name) == display


@pytest.mark.unit
class TestStopConcepts:
    @pytest.mark.parametrize(
        "name",
        [
            # the committed graphs' top concepts before this change
            "Data-Type",
            "Cnx-Pi",
            "Cnx",
            "Cnx.Eoc",
            "Cnx-Pi Data-Type",
            "Title",
            "Row",
            "Summary",
            "Review Questions",
            "Questions",
            "Critical Thinking",
            "Critical Thinking Questions",
            "Self-Check Questions",
            "Key Terms",
            "Newline",
            "No-Emphasis",
            # structural headings
            "Section",
            "Chapter",
            "Introduction",
            "Conclusion",
            "Learning Objectives",
            "Figure",
            "Table",
            "Link",
            "Image",
            "Glossary",
            "Key Concepts and Summary",
            "the Summary",
            "REVIEW QUESTIONS",
            # instructions, centuries, empty
            "Explain the Factors",
            "Describe",
            "Nineteenth Century",
            "the twenty-first century",
            "18th century",
            "",
            "---",
        ],
    )
    def test_noise_is_a_stop_concept(self, name):
        assert is_stop_concept(name)

    @pytest.mark.parametrize(
        "name",
        [
            "Title IX",
            "Middle Class",
            "Civil War",
            "Supply",
            "Demand",
            "Reconstruction",
            "Great Depression",
            "Critical Period",
            "Question of Slavery",
        ],
    )
    def test_real_concepts_are_kept(self, name):
        assert not is_stop_concept(name)

    def test_stop_concepts_are_lower_case_and_re_exported(self):
        assert "data-type" in STOP_CONCEPTS and "summary" in STOP_CONCEPTS
        assert all(term == term.lower() for term in STOP_CONCEPTS)

    @pytest.mark.parametrize(
        "name",
        [
            "Ab",
            "1865",
            "1,000",
            "1860s",
            "20th",
            "$5.00",
            "3.5%",
            "of the",
            "and",
            "a<b>",
            "http://openstax.org/l/inca",
            "press_releases",
            "cnx.org",
            "Review Questions",
        ],
    )
    def test_invalid_concepts(self, name):
        assert not is_valid_concept(name)

    def test_valid_concepts_and_limits(self):
        assert is_valid_concept("Tax") and is_valid_concept("GDP") and is_valid_concept("401(k)")
        assert is_valid_concept("M1", min_length=2) and not is_valid_concept("M1")
        assert is_valid_concept("Tea Act of 1773")
        assert not is_valid_concept("Tax", min_length=4)
        assert is_valid_concept("Temporary Assistance for Needy Families")
        assert not is_valid_concept("Temporary Assistance for Needy Families", max_words=4)


@pytest.mark.unit
class TestProperNouns:
    STATS = _CaseStats.from_prose(
        [
            "Delegates signed the Constitution. Critics of the Constitution wanted "
            "amendments. The Constitution's preamble is short.",
            "Merchants in New York traded. Ships reached New York. They sailed to New York.",
            "British soldiers marched. The British army retreated.",
            "white settlers arrived. The white population grew.",
            "Historians admire Lincoln. Lincoln's speeches are famous. They quoted Lincoln often.",
            "The chapter covers the Stamp Act, the Tea Act and the Townshend Act.",
        ]
    )

    @pytest.mark.parametrize("word", ["constitution", "lincoln"])
    def test_names_written_on_their_own(self, word):
        assert self.STATS.is_proper_noun(word)

    @pytest.mark.parametrize(
        ("word", "why"),
        [
            ("york", "part of the longer name New York"),
            ("act", "the head of several names: Stamp Act, Tea Act"),
            ("british", "a proper adjective, always followed by its noun"),
            ("white", "mostly lower-case"),
            ("unknown", "never mentioned"),
        ],
    )
    def test_other_words_are_not_proper_nouns(self, word, why):
        assert not self.STATS.is_proper_noun(word), why


@pytest.mark.unit
class TestMarkupExtraction:
    def test_extract_marked_terms(self):
        text = (
            'a land bridge we call **Beringia**{: data-type="term"}; the '
            '**demand curve**{: data-type="term" .no-emphasis} and '
            '<span data-type="term">scarcity</span>, but not **bold text**.'
        )
        assert extract_marked_terms(text) == ["Beringia", "demand curve", "scarcity"]

    def test_extract_glossary(self):
        text = (
            '### Glossary\n{: data-type="glossary-title"}\n\n'
            "Beringia\n: an ancient land bridge linking Asia and North America\n^\n\n"
            "*chasquis*\n: Incan relay runners\n\n"
            "Beringia\n: a second definition is ignored\n\n"
            "* a bullet\n: is not a glossary entry\n"
        )
        assert extract_glossary(text) == {
            "Beringia": "an ancient land bridge linking Asia and North America",
            "*chasquis*": "Incan relay runners",
        }

    def test_strip_structural_sections(self):
        text = "\n".join(
            [
                "Intro prose.",
                "### Section Summary",
                "Summary prose stays.",
                "### Review Questions",
                "Which of the following is true?",
                "#### Question 2",
                "Explain the Stamp Act.",
                "### Glossary",
                "Stamp Act\n: a tax",
                "## Next Section",
                "Later prose stays.",
                "### References  {#eip-1}",
                "Smith, J. (2000).",
            ]
        )
        stripped = strip_structural_sections(text)

        assert "Intro prose." in stripped and "Summary prose stays." in stripped
        assert "## Next Section\nLater prose stays." in stripped
        for dropped in ("Which of the following", "Question 2", "Explain", "a tax", "Smith"):
            assert dropped not in stripped
        assert "review questions" in STRUCTURAL_SECTION_TITLES

    def test_strip_structural_sections_without_headings_is_identity(self):
        assert strip_structural_sections("Plain text.\n\nMore text.") == "Plain text.\n\nMore text."


@pytest.mark.unit
class TestExtractConceptsFromText:
    def test_key_terms_first_then_keywords_without_noise(self):
        builder = make_builder(vocabulary=["Boston"], always=NOISE)

        concepts = builder.extract_concepts_from_text(COLONIAL_PROTESTS, ["colonial resistance"])

        assert concepts[:3] == ["Colonial Resistance", "Stamp Act", "Sons of Liberty"]
        assert "Boston" in concepts
        assert not [c for c in concepts if is_stop_concept(c)]

    def test_stop_and_short_key_terms_are_dropped(self):
        builder = make_builder()

        concepts = builder.extract_concepts_from_text(
            "Plain prose.", ["Summary", "Review Questions", "X", "1776", "Liberty"]
        )

        assert concepts == ["Liberty"]

    def test_merges_plural_variants_and_drops_fragments(self):
        text = (
            "The United States grew. The United States expanded west. "
            "Americans moved west, and each American farmer wanted land."
        )
        builder = make_builder(vocabulary=["United", "United States", "Americans", "American"])

        concepts = builder.extract_concepts_from_text(text, [])

        assert "United States" in concepts
        assert "United" not in concepts  # every "United" is part of "United States"
        assert len([c for c in concepts if concept_key(c) == "american"]) == 1

    def test_keeps_independent_shorter_keyword(self):
        text = "Demand rises. Demand falls. Demand shifts. Aggregate demand grows."
        builder = make_builder(vocabulary=["Demand", "Aggregate Demand"])

        assert set(builder.extract_concepts_from_text(text, [])) == {"Demand", "Aggregate Demand"}

    def test_key_terms_are_never_dropped_as_fragments(self):
        text = "The Tea Party of 2009 opposed spending. The Boston Tea Party happened in 1773."
        builder = make_builder(vocabulary=["Boston Tea Party"])

        concepts = builder.extract_concepts_from_text(text, ["Tea Party"])

        assert concepts[0] == "Tea Party" and "Boston Tea Party" in concepts

    def test_keywords_limited_to_four_words_and_no_modifiers(self):
        builder = make_builder(
            always=["Five Word Keyword Phrase Here", "Higher Price", "Million African Americans"]
        )

        assert builder.extract_concepts_from_text("Text.", []) == []

    def test_yake_failure_degrades_to_key_terms(self):
        builder = KGBuilder()
        builder.keyword_extractor = MagicMock()
        builder.keyword_extractor.extract_keywords.side_effect = ValueError("bad input")

        assert builder.extract_concepts_from_text("Some prose here.", ["Scarcity"]) == ["Scarcity"]

    def test_empty_text_skips_yake(self):
        builder = make_builder()

        assert builder.extract_concepts_from_text("", []) == []
        assert builder.keyword_extractor.texts == []

    def test_real_yake_returns_clean_concepts(self):
        text = (
            "Photosynthesis converts light energy into chemical energy. "
            "Chloroplasts host photosynthesis in plant cells. "
            "Photosynthesis produces oxygen and glucose from carbon dioxide and water. "
        ) * 3

        concepts = KGBuilder().extract_concepts_from_text(text, [])

        assert "Photosynthesis" in concepts
        assert not [c for c in concepts if is_stop_concept(c) or len(c) < 3]


@pytest.mark.unit
class TestBuildFromRecords:
    def build(self, records=None, vocabulary=VOCABULARY, always=NOISE, **kwargs):
        builder = make_builder(vocabulary=vocabulary, always=always, **kwargs)
        return builder, builder.build_from_records(CORPUS if records is None else records)

    def test_concepts_are_clean_key_terms_with_definitions(self):
        _, kg = self.build()

        # "Boston", a single-word keyword, fills a slot the key terms leave free
        assert set(kg.concepts) == {
            "Stamp Act",
            "Sons of Liberty",
            "Townshend Acts",
            "British Goods",
            "Boston",
        }
        assert not [name for name in kg.concepts if is_stop_concept(name)]
        stamp_act = kg.concepts["Stamp Act"]
        assert stamp_act.key_term is True
        assert stamp_act.definition == "a 1765 tax on printed paper in the colonies"
        assert stamp_act.frequency == 2  # mentioned in both modules
        assert stamp_act.source_modules == ["m1"]
        assert kg.concepts["British Goods"].key_term is False
        assert kg.concepts["British Goods"].definition is None

    def test_structural_sections_do_not_reach_keyword_extraction(self):
        builder, _ = self.build()

        seen = "\n".join(builder.keyword_extractor.texts)
        assert "Which of the following" not in seen
        assert "cnx-pi" not in seen and "data-type" not in seen
        assert "The Stamp Act united the colonies" in seen  # the section summary is kept

    def test_module_nodes(self):
        records = [
            record("m1", COLONIAL_PROTESTS, key_terms=["Stamp Act"], title="Colonial Protests"),
            record("m2", TOWNSHEND_ACTS),
            {"module_id": "m3", "text": "More prose about the Stamp Act."},
        ]
        _, kg = self.build(records)

        assert kg.modules["m1"].title == "Colonial Protests"
        assert kg.modules["m1"].key_terms == ["Stamp Act"]
        assert kg.modules["m3"].title == "m3"

    def test_records_sharing_a_module_are_merged(self):
        records = [
            record("m1", STAMP_ACT_PARAGRAPH),
            record("m1", "Protest: the Sons of Liberty burned the Stamp Act."),
        ]
        _, kg = self.build(records, vocabulary=[], always=[])

        assert list(kg.modules) == ["m1"]
        assert kg.concepts["Stamp Act"].source_modules == ["m1"]

    def test_covers_relationships(self):
        _, kg = self.build()

        covers = {(r.source, r.target) for r in edges(kg, RelationshipType.COVERS)}
        assert ("m1", "Stamp Act") in covers
        assert ("m2", "Townshend Acts") in covers
        assert ("m2", "Stamp Act") not in covers  # mentioned, but not extracted, in m2

    def test_related_edges_need_threshold_shared_paragraphs(self):
        assert DEFAULT_COOCCURRENCE_THRESHOLD == 5
        _, kg = self.build()

        related = {frozenset((r.source, r.target)): r for r in edges(kg, RelationshipType.RELATED)}
        assert set(related) == {frozenset({"Stamp Act", "Sons of Liberty"})}
        edge = next(iter(related.values()))
        assert edge.weight == pytest.approx(0.6)  # 6 shared paragraphs / 10
        assert edge.confidence == 0.7

    def test_cooccurrence_threshold_is_configurable(self):
        _, strict = self.build(cooccurrence_threshold=50)
        _, loose = self.build(cooccurrence_threshold=1)

        assert edges(strict, RelationshipType.RELATED) == []
        loose_pairs = {
            frozenset((r.source, r.target)) for r in edges(loose, RelationshipType.RELATED)
        }
        assert frozenset({"Stamp Act", "Townshend Acts"}) in loose_pairs

    def test_invalid_parameters(self):
        with pytest.raises(ValueError, match="max_concepts"):
            KGBuilder(max_concepts=0)
        with pytest.raises(ValueError, match="cooccurrence_threshold"):
            KGBuilder(cooccurrence_threshold=0)

    def test_prereq_edges_from_glossary_definitions(self):
        _, kg = self.build()

        prereqs = {(r.source, r.target): r for r in edges(kg, RelationshipType.PREREQ)}
        assert set(prereqs) == {("Stamp Act", "Sons of Liberty"), ("Stamp Act", "Townshend Acts")}
        edge = prereqs[("Stamp Act", "Townshend Acts")]
        assert edge.provenance == {"source": "glossary", "module_id": "m2"}
        assert edge.evidence.startswith("Townshend Acts: taxes on imported goods")
        assert edge.confidence == 0.8

    def test_definition_prereqs_can_be_disabled(self):
        _, kg = self.build(prereq_definitions=False)

        assert edges(kg, RelationshipType.PREREQ) == []

    def test_mutual_definitions_and_cycles_are_skipped(self):
        glossary = "\n\n".join(
            [
                "### Glossary",
                "Democracy\n: a system of government based on majority rule",
                "Majority Rule\n: a principle of democracy",
                "Alpha Doctrine\n: a policy that depends on the Beta Doctrine",
                "Beta Doctrine\n: a policy that depends on the Gamma Doctrine",
                "Gamma Doctrine\n: a policy that depends on the Alpha Doctrine",
            ]
        )
        terms = ["Democracy", "Majority Rule", "Alpha Doctrine", "Beta Doctrine", "Gamma Doctrine"]
        records = [record("m1", "Prose about politics.\n\n" + glossary, key_terms=terms)]
        _, kg = self.build(records, vocabulary=[], always=[])

        pairs = {(r.source, r.target) for r in edges(kg, RelationshipType.PREREQ)}
        assert not pairs & {("Democracy", "Majority Rule"), ("Majority Rule", "Democracy")}
        assert len(pairs) == 2  # one edge of the Alpha -> Beta -> Gamma cycle is dropped
        assert nx.is_directed_acyclic_graph(nx.DiGraph(list(pairs)))

    def test_prereq_patterns_are_opt_in(self):
        text = "\n\n".join(
            [
                'The **Townshend Acts**{: data-type="term"} built on the Stamp Act.',
                'The **Stamp Act**{: data-type="term"} paved the way for the Boston Massacre.',
                'The **Boston Massacre**{: data-type="term"} shocked the colonies.',
            ]
        )
        records = [record("m1", text)]

        _, default = self.build(records, vocabulary=[], always=[])
        _, enabled = self.build(records, vocabulary=[], always=[], prereq_patterns=True)

        assert edges(default, RelationshipType.PREREQ) == []
        prereqs = {(r.source, r.target): r for r in edges(enabled, RelationshipType.PREREQ)}
        assert set(prereqs) == {
            ("Stamp Act", "Townshend Acts"),  # "B builds on A": prerequisite after the cue
            ("Stamp Act", "Boston Massacre"),  # "A paved the way for B": prerequisite first
        }
        edge = prereqs[("Stamp Act", "Townshend Acts")]
        assert edge.provenance == {
            "source": "cue_phrase",
            "pattern": "builds_on",
            "module_id": "m1",
        }
        assert edge.evidence == "The Townshend Acts built on the Stamp Act."
        assert edge.confidence == 0.5

    def test_prereq_patterns_have_word_boundaries(self):
        led_to = next(p for p in PREREQ_PATTERNS if p.name == "led_to")

        assert led_to.regex.search("Opposition led to war")
        assert not led_to.regex.search("the government failed to act")

    def test_importance_scores_and_top_concepts(self):
        builder, kg = self.build()

        scores = [c.importance_score for c in kg.concepts.values()]
        assert max(scores) == pytest.approx(1.0)
        assert all(0.0 < score <= 1.0 for score in scores)
        top = builder.get_top_concepts(2)
        assert len(top) == 2
        assert top[0][0] == "Stamp Act"  # the hub of the RELATED/PREREQ graph
        assert top[0][1] >= top[1][1]

    def test_graph_without_edges_gives_equal_importance(self):
        records = [record("m1", 'The **Stamp Act**{: data-type="term"} taxed paper.')]
        builder, kg = self.build(records, vocabulary=[], always=[])

        assert builder.get_top_concepts() == [("Stamp Act", 1.0)]

    def test_empty_corpus(self):
        builder, kg = self.build([], vocabulary=[], always=[])

        assert kg.concepts == {} and kg.relationships == []
        assert builder.get_top_concepts() == []

    def test_max_concepts_prefers_key_terms_and_phrases_over_single_words(self):
        text = (
            "The Civil War began. The war was long. The war was costly. The war ended. "
            "Slavery caused the war. "
            '**Slavery**{: data-type="term"} divided the nation during the Civil War.'
        )
        records = [record("m1", text)]

        _, small = self.build(records, vocabulary=["War", "Civil War"], always=[], max_concepts=2)
        _, large = self.build(records, vocabulary=["War", "Civil War"], always=[], max_concepts=5)

        assert set(small.concepts) == {"Slavery", "Civil War"}
        # "war" is a lower-case common noun, not a proper noun, so it gets no quota slot
        # and only fills a slot that nothing else wants
        assert "War" in large.concepts

    def test_proper_noun_single_words_get_a_bounded_quota(self):
        """ "Constitution" survives next to author key terms; "York", "white", "war" do not."""
        records = [
            record(
                "m1",
                "\n\n".join(
                    [
                        'The **Articles of Confederation**{: data-type="term"} gave Congress '
                        "little power.",
                        "Delegates in Philadelphia replaced them with the Constitution, which "
                        "created a stronger national government.",
                        "Merchants in New York wanted the Constitution ratified quickly.",
                        "Settlers kept moving west while the war with Britain ended.",
                    ]
                ),
            ),
            record(
                "m2",
                "\n\n".join(
                    [
                        'The **Bill of Rights**{: data-type="term"} amended the Constitution in 1791.',
                        "Supporters in New York defended the Constitution.",
                        "After the war, white farmers protested new taxes.",
                    ]
                ),
            ),
            record(
                "m3",
                "\n\n".join(
                    [
                        'The **Federalists**{: data-type="term"} and the '
                        '**Anti-Federalists**{: data-type="term"} argued over the Constitution.',
                        'The **Great Compromise**{: data-type="term"} and the '
                        '**Three-Fifths Compromise**{: data-type="term"} shaped representation.',
                        "Historians compare Lincoln to the founders.",
                        "New York ratified after a long debate about the war debt.",
                    ]
                ),
            ),
        ]
        vocabulary = ["Constitution", "Lincoln", "York", "White", "War", "Congress"]
        key_terms = {
            "Articles of Confederation",
            "Bill of Rights",
            "Federalists",
            "Anti-Federalists",
            "Great Compromise",
            "Three-Fifths Compromise",
        }

        # max_concepts=7 -> int(7 * 0.15) = 1 proper-noun slot, won by the most widely
        # mentioned proper noun
        _, one_slot = self.build(records, vocabulary=vocabulary, always=[], max_concepts=7)
        # max_concepts=14 -> 2 slots; the remaining slots are filled by the other words
        _, two_slots = self.build(records, vocabulary=vocabulary, always=[], max_concepts=14)

        assert set(one_slot.concepts) == key_terms | {"Constitution"}
        assert {"Constitution", "Lincoln"} <= set(two_slots.concepts)

    def test_two_character_key_terms_are_kept(self):
        text = (
            '**M1**{: data-type="term"} counts currency and checking deposits. '
            "M2 adds savings deposits to M1."
        )
        _, kg = self.build([record("m1", text)], vocabulary=["M2"], always=[])

        assert "M1" in kg.concepts  # an author key term
        assert "M2" not in kg.concepts  # a two-character keyword is too short

    def test_keywords_must_recur_across_modules_in_large_corpora(self):
        # 70 modules -> a YAKE-only phrase needs int(70 * 0.03) = 2 modules
        records = [record(f"m{i}", f"Topic {i} prose.") for i in range(68)]
        records.append(record("m68", "Harbor rules. The Erie Canal opened."))
        records.append(record("m69", "The Erie Canal carried grain."))
        records.append(record("m70", "The Cotton Gin changed farming."))

        _, kg = self.build(records, vocabulary=["Erie Canal", "Cotton Gin"], always=[])

        assert "Erie Canal" in kg.concepts
        assert "Cotton Gin" not in kg.concepts

    def test_generic_keywords_are_dropped_in_large_corpora(self):
        records = [
            record(f"m{i}", f"The United States and slavery, part {i}.", key_terms=["Slavery"])
            for i in range(12)
        ]
        _, kg = self.build(records, vocabulary=["United States"], always=[])

        assert "Slavery" in kg.concepts  # key terms are exempt from the document-frequency cap
        assert "United States" not in kg.concepts  # mentioned in every module

    def test_acronyms_merge_into_their_expansion(self):
        records = [
            record("m1", '**gross domestic product (GDP)**{: data-type="term"} measures output.'),
            record("m2", "GDP grew in 2010. Real growth followed."),
            record("m3", "Economists start with GDP."),
        ]
        _, kg = self.build(records, vocabulary=["GDP"], always=[])

        # "GDP" is extracted from more modules than the spelled-out form, so it names the concept
        assert list(kg.concepts) == ["GDP"]
        concept = kg.concepts["GDP"]
        assert concept.aliases == ["Gross Domestic Product"]
        assert concept.frequency == 3
        assert concept.source_modules == ["m1", "m2", "m3"]

    def test_spelled_out_name_wins_when_more_common(self):
        records = [
            record("m1", '**gross domestic product (GDP)**{: data-type="term"} measures output.'),
            record("m2", '**Gross domestic product**{: data-type="term"} grew in 2010.'),
            record("m3", '**GDP**{: data-type="term"} fell in 2009.'),
        ]
        _, kg = self.build(records, vocabulary=[], always=[])

        assert list(kg.concepts) == ["Gross Domestic Product"]
        assert "GDP" in kg.concepts["Gross Domestic Product"].aliases
        assert kg.concepts["Gross Domestic Product"].frequency == 3

    def test_acronym_mentions_are_case_sensitive(self):
        records = [
            record("m1", 'Leaders signed **START**{: data-type="term"} in 1991.'),
            record("m2", "Talks would start again after START expired."),
            record("m3", "Nations start new talks."),
        ]
        _, kg = self.build(records, vocabulary=[], always=[])

        assert kg.concepts["START"].frequency == 2  # "start" (the verb) is not a mention

    def test_build_is_deterministic(self):
        first = make_builder(VOCABULARY, NOISE).build_from_records(CORPUS)
        second = make_builder(VOCABULARY, NOISE).build_from_records(CORPUS)

        assert first.model_dump_json() == second.model_dump_json()

    def test_real_yake_build_has_no_markup_concepts(self):
        builder = KGBuilder()
        kg = builder.build_from_records(CORPUS)

        assert {"Stamp Act", "Sons of Liberty", "Townshend Acts"} <= set(kg.concepts)
        assert not [name for name in kg.concepts if is_stop_concept(name)]
