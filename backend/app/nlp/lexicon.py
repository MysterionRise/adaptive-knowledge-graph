"""
Query-time concept lexicon (#212): a subject's concept names and their stored aliases.

Questions name concepts in many shapes: "GDP" for "Gross Domestic Product", "recessions"
for "Recession", "the Stamp Act" for "Stamp Act". The lexicon keys every name and alias
with ``query_key`` (case, punctuation, a leading article and a plural last word ignored)
and resolves a span of a question in this order:

1. exact: the span's key is a concept's name or one of its aliases (a name wins);
2. contained: the longest name or alias inside the span ("the Stamp Act of 1765");
3. containing, for spans of two or more words only: the shortest name or alias that
   contains the span. A single generic word ("war", "policy", "American") never matches
   this way, so it no longer pulls in "Civil War", "Fiscal Policy" or "American River".

An alias shared by several concepts is ambiguous: it resolves to no concept, and KG
expansion leaves it out (telling the senses apart needs the domain model of #211). Ties
are broken by length and then alphabetically, so a resolution never depends on set order.

A lexicon is also a read-only set of its concept names, so it can stand in wherever a
plain set of names was used. Stop concepts ("Summary", "Data-Type") are left out.
"""

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Set
from dataclasses import dataclass
from functools import lru_cache

from backend.app.kg.normalize import query_key, singularize
from backend.app.kg.stopwords import is_stop_concept


@dataclass(frozen=True)
class Resolution:
    """What a span of a question resolved to."""

    surface: str  # the span as the question has it
    canonical: str | None  # the concept's name; None when the span is ambiguous
    via: str  # "name" or "alias"
    candidates: tuple[str, ...] = ()  # the concepts an ambiguous span could mean

    @property
    def status(self) -> str:
        return "resolved" if self.canonical is not None else "ambiguous"


def _tokens(key: str) -> tuple[str, ...]:
    """A key's words, each singularised, for the containment steps."""
    return tuple(singularize(word) for word in key.split())


def _contains(longer: tuple[str, ...], shorter: tuple[str, ...]) -> bool:
    """Whether ``shorter`` occurs in ``longer`` as consecutive whole words."""
    size = len(shorter)
    return any(longer[i : i + size] == shorter for i in range(len(longer) - size + 1))


class ConceptLexicon(Set[str]):
    """A subject's concept names, with their aliases, keyed for matching questions."""

    def __init__(self, aliases_by_name: Mapping[str, Iterable[str]]):
        names = frozenset(name for name in aliases_by_name if not is_stop_concept(name))
        by_name: dict[str, set[str]] = defaultdict(set)
        by_alias: dict[str, set[str]] = defaultdict(set)
        for name in names:
            if key := query_key(name):
                by_name[key].add(name)
            for alias in aliases_by_name[name] or ():
                if alias_key := query_key(alias):
                    by_alias[alias_key].add(name)
        self._names = names
        self._by_name = {key: frozenset(found) for key, found in by_name.items()}
        # A key that is some concept's name resolves to that name, never to an alias
        self._by_alias = {
            key: frozenset(found) for key, found in by_alias.items() if key not in by_name
        }
        keys = [(key, _tokens(key)) for key in {*self._by_name, *self._by_alias}]
        self._longest_first = sorted(keys, key=lambda k: (-len(k[1]), -len(k[0]), k[0]))
        self._shortest_first = sorted(keys, key=lambda k: (len(k[1]), len(k[0]), k[0]))

    @classmethod
    def from_names(cls, names: Iterable[str]) -> "ConceptLexicon":
        """A lexicon without aliases."""
        return cls(dict.fromkeys(names, ()))

    def __contains__(self, name: object) -> bool:
        return name in self._names

    def __iter__(self) -> Iterator[str]:
        return iter(self._names)

    def __len__(self) -> int:
        return len(self._names)

    @property
    def alias_count(self) -> int:
        """Alias keys that are not also a concept name."""
        return len(self._by_alias)

    def _resolve_key(self, surface: str, key: str) -> Resolution:
        if key in self._by_name:
            return Resolution(surface, min(self._by_name[key]), "name")
        concepts = self._by_alias[key]
        if len(concepts) == 1:
            return Resolution(surface, next(iter(concepts)), "alias")
        return Resolution(surface, None, "alias", tuple(sorted(concepts)))

    def resolve(self, span: str) -> Resolution | None:
        """Resolve a span of a question (see the module docstring); None without a match."""
        key = query_key(span)
        if not key:
            return None
        if key in self._by_name or key in self._by_alias:
            return self._resolve_key(span, key)
        tokens = _tokens(key)
        for candidate, candidate_tokens in self._longest_first:
            if _contains(tokens, candidate_tokens):
                return self._resolve_key(span, candidate)
        if len(tokens) < 2:
            return None
        for candidate, candidate_tokens in self._shortest_first:
            if _contains(candidate_tokens, tokens):
                return self._resolve_key(span, candidate)
        return None

    def find_in(self, text: str) -> list[Resolution]:
        """Every name or alias in ``text`` as whole words, longest first, one per concept.

        The fallback when the NER and YAKE strategies find nothing.
        """
        tokens = _tokens(query_key(text))
        found: list[Resolution] = []
        seen: set[str | None] = set()
        for candidate, candidate_tokens in self._longest_first:
            if _contains(tokens, candidate_tokens):
                resolution = self._resolve_key(candidate, candidate)
                if resolution.canonical not in seen or resolution.canonical is None:
                    seen.add(resolution.canonical)
                    found.append(resolution)
        return found


@lru_cache(maxsize=32)
def lexicon_for(names: frozenset[str]) -> ConceptLexicon:
    """A lexicon without aliases for a set of names, memoised per set."""
    return ConceptLexicon.from_names(names)
