"""
Stop-concept vocabulary shared by every concept extractor.

OpenStax sources mix prose with markup (``data-type="term"``, ``<cnx-pi>``
processing instructions, kramdown attribute lists) and a fixed set of structural
headings (Review Questions, Glossary, Key Concepts and Summary). Keyword
extraction returns those as "concepts": the committed graphs' top concepts
included Data-Type, Cnx-Pi, Title, Summary and Review Questions. The lists below
were derived from ``data/processed/books_us_history.jsonl`` and
``data/processed/books_economics.jsonl``.
"""

import re

from backend.app.kg.normalize import concept_key, tokenize

# Tokens that only ever come from markup. A candidate containing one is noise
# ("Cnx-Pi Data-Type", "Newline", "Data-Type Term").
MARKUP_TOKENS: frozenset[str] = frozenset(
    {
        "cnx",
        "cnx-pi",
        "cnx.eoc",
        "cnx.flag.introduction",
        "colspan",
        "data-alt",
        "data-align",
        "data-label",
        "data-title",
        "data-type",
        "eip",
        "footnote-ref",
        "glossary-title",
        "href",
        "http",
        "https",
        "mrow",
        "msub",
        "mtext",
        "newline",
        "no-emphasis",
        "os-embed",
        "os-teacher",
        "rowspan",
        "target-chapter",
        "www",
        "xmlns",
    }
)

# Markup element/attribute names that are also ordinary words: noise only when
# they are the whole candidate ("Title" is, "Title IX" is not).
_MARKUP_WORDS = {
    "abstract",
    "alt",
    "caption",
    "class",
    "column",
    "content",
    "data type",
    "eob",
    "eoc",
    "equation",
    "figure",
    "footnote",
    "image",
    "link",
    "math",
    "media",
    "metadata",
    "module",
    "no emphasis",
    "note",
    "page",
    "row",
    "span",
    "table",
    "term",
    "title",
    "type",
}

# Textbook scaffolding: headings, end-of-chapter material, feature boxes and
# OpenStax/licensing boilerplate.
_STRUCTURAL_TERMS = {
    "answer",
    "answer key",
    "appendix",
    "attribution",
    "bring it home",
    "chapter",
    "chapter outline",
    "chapter review",
    "check understanding",
    "check-understanding",
    "clear it up",
    "click and explore",
    "conclusion",
    "creative commons",
    "credit",
    "critical thinking",
    "critical thinking question",
    "download",
    "econ",
    "end-of-chapter",
    "end-of-module",
    "exercise",
    "further reading",
    "glossary",
    "index",
    "introduction",
    "key concept",
    "key concepts and summary",
    "key term",
    "learning objective",
    "license",
    "link it up",
    "my story",
    "openstax",
    "openstax college",
    "practice",
    "preface",
    "problem",
    "question",
    "reference",
    "review",
    "review question",
    "rice university",
    "section",
    "section summary",
    "self-check",
    "self-check question",
    "solution",
    "suggested reading",
    "summary",
    "thinking question",
    "work it out",
}

# Question stems and instructions ("Explain why…", "Describe how…"). A candidate
# starting with one of these is rejected as well ("Explain the Factors").
INSTRUCTIONAL_TERMS: frozenset[str] = frozenset(
    {
        "analyze",
        "compare",
        "consider",
        "define",
        "describe",
        "discuss",
        "evaluate",
        "explain",
        "identify",
        "summarize",
    }
)

# Nouns too generic to be a concept on their own in any subject.
_GENERIC_TERMS = {
    "example",
    "fact",
    "kind",
    "lot",
    "number",
    "part",
    "people",
    "point",
    "result",
    "thing",
    "time",
    "today",
    "way",
    "year",
}

STOP_CONCEPTS: frozenset[str] = frozenset(
    _MARKUP_WORDS
    | _STRUCTURAL_TERMS
    | _GENERIC_TERMS
    | set(INSTRUCTIONAL_TERMS)
    | set(MARKUP_TOKENS)
)
"""Lower-case stop phrases; plural forms are matched too ("review questions")."""

# English function words; a candidate made only of these is not a concept.
FUNCTION_WORDS: frozenset[str] = frozenset(
    "a about after all also an and any are as at be been before between but by can could did "
    "do does during each for from had has have he her his how i if in into is it its may might "
    "more most much must no not of on one or other our over she should so some such than that "
    "the their them then there these they this those through to under up was we were what when "
    "where which while who why will with would you your".split()
)

_STOP_KEYS = frozenset(concept_key(term) for term in STOP_CONCEPTS)
_ARTICLES = frozenset({"a", "an", "the"})
_NUMERIC_RE = re.compile(r"[\d\s.,%$€£/:×+\-–—]+(?:s|st|nd|rd|th)?")
_MARKUP_CHARS_RE = re.compile(r"[<>{}=#\\|@_^~]|https?:|www\.|\.(?:com|org|gov|edu|html?)\b")
# "Nineteenth Century", "18th century", "twenty-first century".
_CENTURY_RE = re.compile(
    r"(?:(?:early|late|mid)[\s-]+)?(?:[a-z]+-)?[a-z0-9]+(?:th|st|nd|rd)[\s-]+centur(?:y|ies)"
)


def is_stop_concept(name: str) -> bool:
    """
    True when ``name`` is markup or textbook scaffolding rather than a concept.

    Matching ignores case, punctuation and plural forms ("Review Question",
    "review questions" and "REVIEW QUESTIONS" all match). A name containing a
    markup-only token ("Cnx-Pi Data-Type"), starting with an instruction verb
    ("Explain the Factors") or naming a century ("Nineteenth Century") is a stop
    concept too, as is a name with no word characters at all.
    """
    tokens = tokenize(name)
    if len(tokens) > 1 and tokens[0] in _ARTICLES:
        tokens = tokens[1:]
    if not tokens:
        return True
    if tokens[0] in INSTRUCTIONAL_TERMS or any(token in MARKUP_TOKENS for token in tokens):
        return True
    joined = " ".join(tokens)
    return (
        joined in STOP_CONCEPTS
        or joined.replace("-", " ") in STOP_CONCEPTS
        or concept_key(joined) in _STOP_KEYS
        or _CENTURY_RE.fullmatch(joined) is not None
    )


def is_valid_concept(name: str, *, min_length: int = 3, max_words: int | None = None) -> bool:
    """
    True when a normalised name is worth keeping as a concept.

    Rejects names shorter than ``min_length`` characters, numbers and years
    ("1865", "1,000", "1860s"), anything that still looks like markup or a URL,
    names made only of function words, stop concepts and, when ``max_words`` is
    set, phrases of more than ``max_words`` words.
    """
    stripped = name.strip()
    lowered = stripped.lower()
    if len(stripped) < min_length:
        return False
    if _NUMERIC_RE.fullmatch(lowered) or _MARKUP_CHARS_RE.search(lowered):
        return False
    if max_words is not None and len(stripped.split()) > max_words:
        return False
    tokens = tokenize(stripped)
    if not tokens or all(token in FUNCTION_WORDS for token in tokens):
        return False
    return not is_stop_concept(stripped)
