"""
Lexical normalisation helpers for knowledge-graph concepts.

Concept names arrive from several sources (author-marked key terms, YAKE
keywords, spaCy spans) in inconsistent shapes: ``**Beringia**``, ``“slave power”``,
``gross domestic product (GDP)``, ``Americans`` next to ``American``. These helpers
give every name a clean surface form, a comparison key that merges case and
singular/plural variants, and a readable display form.
"""

import html
import re

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:['.\-][a-z0-9]+)*")
_EDGE_QUOTES_RE = re.compile(r"(?<!\w)[\"'`´“”‘’]+|[\"'`´“”‘’]+(?!\w)")
_MARKDOWN_EMPHASIS_RE = re.compile(r"[*`]+")
_WHITESPACE_RE = re.compile(r"\s+")
_LEADING_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)
_ABBREVIATION_RE = re.compile(r"\s*\(([A-Za-z][A-Za-z0-9&.\-]{1,11})\)")
_EDGE_PUNCTUATION = " \t\r\n.,;:!?-–—/\\|{}<>#_"
_BRACKETS = (("(", ")"), ("[", "]"))

# Last-word endings that look plural but are not ("economics", "status", "crisis").
_NON_PLURAL_ENDINGS = ("ss", "us", "is", "ics", "ous")

# Words kept lower-case inside a display name ("Bill of Rights", "Alexis de Tocqueville").
_MINOR_WORDS = frozenset(
    {"a", "an", "and", "as", "at", "by", "de", "du", "for", "from", "in", "into", "of", "on"}
    | {"or", "per", "the", "to", "v.", "via", "von", "vs", "vs.", "with"}
)
_WORD_PART_RE = re.compile(r"([-/])")


def tokenize(text: str) -> list[str]:
    """Lower-case word tokens; hyphens, apostrophes and dots inside a word are kept."""
    return _TOKEN_RE.findall(text.lower().replace("’", "'"))


def singularize(word: str) -> str:
    """
    Conservative English singular of a lower-case word.

    Only regular plurals are handled ("colonies" -> "colony", "taxes" -> "tax",
    "americans" -> "american"). Words that merely end in "s" ("economics",
    "status", "crisis") and words of three letters or fewer are returned unchanged.
    """
    if len(word) <= 3 or not word.endswith("s") or word.endswith(_NON_PLURAL_ENDINGS):
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "xes", "ches", "shes", "zes")):
        return word[:-2]
    return word[:-1]


def concept_key(name: str) -> str:
    """
    Comparison key for a concept name.

    Case, punctuation and spacing are ignored and the last word is singularised,
    so "Americans", "american" and "AMERICAN" share the key "american". In an
    "X of Y" phrase the head noun X is singularised too ("Standards of Living").
    """
    tokens = tokenize(name)
    if not tokens:
        return ""
    tokens[-1] = singularize(tokens[-1])
    if "of" in tokens[1:-1]:
        head = tokens.index("of", 1) - 1
        tokens[head] = singularize(tokens[head])
    return " ".join(tokens)


def _trim_edges(text: str) -> str:
    """Strip edge punctuation, and edge brackets only when they are unbalanced ("401(k)" stays)."""
    while True:
        trimmed = text.strip(_EDGE_PUNCTUATION)
        for opening, closing in _BRACKETS:
            if trimmed.endswith(closing) and trimmed.count(closing) > trimmed.count(opening):
                trimmed = trimmed[:-1]
            if trimmed.startswith(opening) and trimmed.count(opening) > trimmed.count(closing):
                trimmed = trimmed[1:]
        if trimmed == text:
            return trimmed
        text = trimmed


def normalize_concept(raw: str) -> str:
    """
    Clean surface form of a concept name.

    Unescapes HTML entities, drops Markdown emphasis and surrounding quotes,
    collapses whitespace and trims edge punctuation, unbalanced brackets and a
    leading article. Returns an empty string when nothing meaningful is left.
    """
    text = html.unescape(raw)
    text = _MARKDOWN_EMPHASIS_RE.sub("", text)
    text = _EDGE_QUOTES_RE.sub("", text)
    text = _trim_edges(_WHITESPACE_RE.sub(" ", text))
    text = _LEADING_ARTICLE_RE.sub("", text)
    return _trim_edges(text)


def split_abbreviations(name: str) -> tuple[str, list[str]]:
    """
    Split parenthesised acronyms out of a name.

    "gross domestic product (GDP)" -> ("gross domestic product", ["GDP"]). Only
    groups with at least two capital letters count, so "401(k)" is unchanged.
    """
    acronyms = [
        match.group(1)
        for match in _ABBREVIATION_RE.finditer(name)
        if sum(char.isupper() for char in match.group(1)) >= 2
    ]
    if not acronyms:
        return name, []
    base = _ABBREVIATION_RE.sub(
        lambda match: "" if match.group(1) in acronyms else match.group(0), name
    )
    return _WHITESPACE_RE.sub(" ", base).strip(), acronyms


def is_acronym(name: str) -> bool:
    """True for a single all-capitals word such as "GDP", "NAACP" or "START"."""
    return " " not in name and sum(char.isupper() for char in name) >= 2 and name.upper() == name


def display_name(name: str) -> str:
    """
    Title-case form that keeps acronyms and existing capitals.

    "french and indian war" -> "French and Indian War", "real GDP" -> "Real GDP",
    and an all-caps heading such as "NORTH AMERICAN INDIANS" -> "North American Indians".
    Parts of hyphenated or slashed words are capitalised separately.
    """
    words = name.split()
    shouting = len(words) > 1 and all(word.upper() == word for word in words)
    result = []
    for index, word in enumerate(words):
        if shouting:
            word = word.lower()
        if index > 0 and word.lower() in _MINOR_WORDS:
            result.append(word.lower())
        else:
            parts = _WORD_PART_RE.split(word)
            result.append(
                "".join(part[:1].upper() + part[1:] if part.islower() else part for part in parts)
            )
    return " ".join(result)
