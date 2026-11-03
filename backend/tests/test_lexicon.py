"""Query-time concept lexicon: names, aliases, plurals and generic words (#212)."""

import pytest

from backend.app.kg.normalize import query_key
from backend.app.nlp.lexicon import ConceptLexicon, Resolution, lexicon_for

pytestmark = pytest.mark.unit

LEXICON = ConceptLexicon(
    {
        "Gross Domestic Product": ["GDP", "gross domestic products"],
        "Recession": ["Recessions"],
        "Civil War": [],
        "World War": [],
        "American Revolution": [],
        "American River": [],
        "Fiscal Policy": [],
        "Stamp Act": [],
        "Capital": ["capital stock"],
        "Physical Capital": ["capital stock"],
        "Federalists": ["Federalist"],
        "Federalist": [],
        "Summary": ["recap"],  # a stop concept: never part of the lexicon
    }
)


def resolve(span: str) -> tuple[str | None, str] | None:
    resolution = LEXICON.resolve(span)
    return (resolution.canonical, resolution.via) if resolution else None


class TestAcceptance:
    def test_an_abbreviation_and_its_expansion_resolve_to_one_concept(self):
        assert resolve("GDP") == ("Gross Domestic Product", "alias")
        assert resolve("gross domestic product") == ("Gross Domestic Product", "name")

    @pytest.mark.parametrize("word", ["war", "War", "policy", "American", "act"])
    def test_a_generic_word_resolves_to_nothing(self, word):
        assert LEXICON.resolve(word) is None

    def test_an_alias_of_several_concepts_is_ambiguous(self):
        resolution = LEXICON.resolve("capital stock")
        assert resolution == Resolution(
            "capital stock", None, "alias", ("Capital", "Physical Capital")
        )
        assert resolution.status == "ambiguous"


class TestResolve:
    @pytest.mark.parametrize(
        ("span", "expected"),
        [
            ("recessions", ("Recession", "name")),  # plural of a name
            ("the Stamp Act", ("Stamp Act", "name")),  # leading article
            ("The Stamp Act of 1765", ("Stamp Act", "name")),  # longest name inside the span
            ("the American Revolution", ("American Revolution", "name")),
            ("World War Two", ("World War", "name")),
            ("fiscal policies", ("Fiscal Policy", "name")),
            ("civil", None),  # one word: no containing match
            ("american revolution era", ("American Revolution", "name")),
            ("capital", ("Capital", "name")),  # a name is never ambiguous
            ("federalist", ("Federalist", "name")),  # a name beats another concept's alias
            ("recap", None),  # alias of a stop concept
            ("", None),
            ("   ", None),
        ],
    )
    def test_spans(self, span, expected):
        assert resolve(span) == expected

    def test_two_word_span_inside_a_longer_concept(self):
        lexicon = ConceptLexicon.from_names(["Sons of Liberty", "Daughters of Liberty"])
        assert lexicon.resolve("sons of").canonical == "Sons of Liberty"
        assert lexicon.resolve("of liberty").canonical == "Sons of Liberty"  # shortest, then name
        assert lexicon.resolve("liberty") is None

    def test_the_surface_is_kept_as_written(self):
        assert LEXICON.resolve("The GDP").surface == "The GDP"


class TestSetBehaviour:
    def test_is_a_set_of_names_without_stop_concepts(self):
        assert "Civil War" in LEXICON
        assert "Summary" not in LEXICON
        assert "GDP" not in LEXICON  # an alias, not a name
        assert len(LEXICON) == 12
        assert LEXICON == set(LEXICON)

    def test_alias_count_leaves_out_keys_that_are_names(self):
        # GDP, capital stock; "gross domestic products", "Recessions" and "Federalist"
        # share a key with a name
        assert LEXICON.alias_count == 2

    def test_lexicon_for_is_memoised(self):
        names = frozenset({"Civil War"})
        assert lexicon_for(names) is lexicon_for(frozenset({"Civil War"}))


class TestFindIn:
    def test_every_name_or_alias_in_the_text_longest_first(self):
        found = LEXICON.find_in("Did GDP fall after the Civil War and in recessions?")
        # Most words first, then most characters
        assert [r.canonical for r in found] == ["Civil War", "Recession", "Gross Domestic Product"]

    def test_whole_words_only(self):
        assert LEXICON.find_in("warfare and facts") == []

    def test_ambiguous_aliases_are_reported(self):
        found = LEXICON.find_in("How is the capital stock measured?")
        assert [(r.canonical, r.status) for r in found] == [
            (None, "ambiguous"),
            ("Capital", "resolved"),
        ]


def test_query_key_drops_a_leading_article_and_singularises():
    assert query_key("The Stamp Acts") == query_key("stamp act") == "stamp act"
    assert query_key("an Economics") == "economics"
