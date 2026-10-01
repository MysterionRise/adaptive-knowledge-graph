"""
Knowledge Graph builder.

Builds a concept graph from OpenStax textbook records:

1. Author-marked key terms (``**term**{: data-type="term"}``) and glossary
   definitions are read from the raw text; the text is then cleaned of markup and
   of end-of-section scaffolding (review questions, glossary, references).
2. YAKE keywords from the cleaned prose complement the key terms. Every candidate
   is normalised, stop-concept filtered and merged with its case/plural variants;
   keyword fragments of longer concepts ("United" in "United States") are dropped.
3. The ``max_concepts`` best candidates become concept nodes. COVERS edges link
   modules to the concepts extracted from them; RELATED edges link concepts that
   share at least ``cooccurrence_threshold`` paragraphs; PREREQ edges come from
   glossary definitions (a concept named in another concept's definition is its
   prerequisite) and, optionally, from cue phrases such as "builds on".
4. Importance is PageRank over the RELATED/PREREQ graph.
"""

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import NamedTuple

import networkx as nx
from loguru import logger
from yake import KeywordExtractor

from backend.app.kg.markup import (
    clean_text,
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
)
from backend.app.kg.schema import (
    ConceptNode,
    KnowledgeGraph,
    ModuleNode,
    Relationship,
    RelationshipType,
)
from backend.app.kg.stopwords import (
    FUNCTION_WORDS,
    STOP_CONCEPTS,
    is_stop_concept,
    is_valid_concept,
)

__all__ = [
    "DEFAULT_COOCCURRENCE_THRESHOLD",
    "KGBuilder",
    "PREREQ_PATTERNS",
    "STOP_CONCEPTS",
    "PrereqPattern",
    "is_stop_concept",
]

DEFAULT_COOCCURRENCE_THRESHOLD = 5
"""Paragraphs two concepts must share before they get a RELATED edge."""

MAX_KEYWORD_WORDS = 4
"""Longest YAKE phrase kept; author-marked key terms are not limited."""

MIN_KEY_TERM_LENGTH = 2
"""Shortest author-marked key term ("M1" in Economics); keywords use ``min_concept_length``."""

MIN_KEYWORD_MODULE_RATIO = 0.03
"""A YAKE-only phrase must be a top keyword of at least this share of modules (minimum 1)."""

MAX_KEYWORD_DOCUMENT_RATIO = 0.5
"""A YAKE-only phrase mentioned in more than this share of modules is too generic."""

MIN_MODULES_FOR_DOCUMENT_RATIO = 10
"""Smallest corpus (in modules) for which the document-frequency cut-off is applied."""

FRAGMENT_DOMINANCE = 0.5
"""Drop a YAKE-only phrase when this share of its occurrences lie inside longer concepts."""

SINGLE_WORD_QUOTA = 0.15
"""Share of ``max_concepts`` kept for proper-noun single words ("Constitution", "Lincoln")."""

MIN_CAPITALISED_RATIO = 0.5
"""A proper noun is written with a capital in at least this share of mid-sentence mentions."""

MAX_NAME_PART_RATIO = 0.5
"""...and fewer than this share of its capitalised mentions sit next to another capitalised
word, which would make it part of a longer name ("New York", "Stamp Act", "John Adams")."""

MIN_PHRASE_END_RATIO = 1 / 3
"""...and at least this share of them end a phrase (punctuation, "of", "was", …). Proper
adjectives almost never do, because they precede a noun ("British soldiers")."""

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['.\-][A-Za-z0-9]+)*")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[\"“‘(\[]?[A-Z0-9])|\n+")
_LINE_END_RE = re.compile(r"(?<![.!?:;])[ \t]*\n")
# Keyword phrases that open with a number or a comparative/quantity modifier are
# descriptions, not concepts ("Million African Americans", "Higher Price").
_MODIFIER_PREFIX_RE = re.compile(
    r"(?:\d[\d,.]*|one|two|three|four|five|six|seven|eight|nine|ten|dozens?|hundreds?"
    r"|thousands?|millions?|billions?|trillions?|higher|lower|greater|larger|smaller|bigger"
    r"|more|less|fewer|increased|decreased|rising|falling|large|small|big|many|several"
    r"|various|other|certain|different|similar|specific|entire|whole)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PrereqPattern:
    """A cue phrase that signals a prerequisite relationship within one sentence."""

    name: str
    regex: re.Pattern[str]
    prerequisite_first: bool
    """True when the prerequisite is named before the cue ("A paved the way for B")."""


PREREQ_PATTERNS: list[PrereqPattern] = [
    PrereqPattern(
        "requires_understanding",
        re.compile(
            r"\brequires? (?:an? |some )?(?:basic |solid |good |prior )?"
            r"(?:understanding|knowledge) of\b",
            re.IGNORECASE,
        ),
        prerequisite_first=False,
    ),
    PrereqPattern(
        "builds_on",
        re.compile(r"\bbuil(?:d|ds|t|ding) (?:on|upon)\b", re.IGNORECASE),
        prerequisite_first=False,
    ),
    PrereqPattern(
        "assumes_knowledge",
        re.compile(
            r"\bassumes? (?:some )?(?:knowledge|familiarity|understanding) (?:of|with)\b",
            re.IGNORECASE,
        ),
        prerequisite_first=False,
    ),
    PrereqPattern(
        "prerequisite_for",
        re.compile(
            r"\b(?:is|are|was|were) (?:an? )?(?:essential )?prerequisites? (?:for|to)\b",
            re.IGNORECASE,
        ),
        prerequisite_first=True,
    ),
    PrereqPattern(
        "paved_the_way",
        re.compile(r"\b(?:paved|paves|paving) the way (?:for|to)\b", re.IGNORECASE),
        prerequisite_first=True,
    ),
    PrereqPattern(
        "laid_the_foundation",
        re.compile(
            r"\b(?:laid|lay|lays|laying) the (?:foundation|groundwork) for\b", re.IGNORECASE
        ),
        prerequisite_first=True,
    ),
    PrereqPattern(
        "precursor_to",
        re.compile(r"\b(?:was|were|is|are) (?:a |the )?precursors? (?:to|of)\b", re.IGNORECASE),
        prerequisite_first=True,
    ),
    PrereqPattern(
        "led_to",
        re.compile(r"\b(?:led|leads|leading) to\b", re.IGNORECASE),
        prerequisite_first=True,
    ),
    PrereqPattern(
        "resulted_in",
        re.compile(r"\bresult(?:ed|s)? in\b", re.IGNORECASE),
        prerequisite_first=True,
    ),
]
"""Cue phrases used when ``prereq_patterns=True``, each with its direction."""


@dataclass
class _Candidate:
    """A concept candidate merged across case/plural variants and modules."""

    key: str
    surfaces: Counter[str] = field(default_factory=Counter)
    key_surfaces: Counter[str] = field(default_factory=Counter)
    aliases: set[str] = field(default_factory=set)
    modules: list[str] = field(default_factory=list)
    key_term: bool = False
    definition: str | None = None
    definition_module: str | None = None
    preferred: str | None = None
    """Display-name override, e.g. an acronym used more widely than its expansion."""

    @property
    def name(self) -> str:
        """
        Display name: the most common author spelling, else the most common keyword.

        Ties prefer normal case over ALL CAPS, then the shorter (usually singular) form.
        """
        if self.preferred:
            return display_name(self.preferred)
        pool = self.key_surfaces or self.surfaces
        best = max(
            pool.items(),
            key=lambda item: (item[1], not item[0].isupper(), -len(item[0]), item[0]),
        )
        return display_name(best[0])

    @property
    def is_single_word(self) -> bool:
        return " " not in self.key

    def merge(self, other: "_Candidate") -> None:
        self.surfaces.update(other.surfaces)
        self.key_surfaces.update(other.key_surfaces)
        self.aliases.update(other.aliases)
        self.modules.extend(module for module in other.modules if module not in self.modules)
        self.key_term = self.key_term or other.key_term


@dataclass
class _Module:
    module_id: str
    title: str
    key_terms: list[str]
    texts: list[str] = field(default_factory=list)


class _Occurrence(NamedTuple):
    start: int
    end: int
    key: str


@dataclass
class _Paragraph:
    module_id: str
    words: list[str]
    lower: list[str]


@dataclass(frozen=True)
class _PrereqEdge:
    prerequisite: str
    dependent: str
    evidence: str
    confidence: float
    provenance: dict[str, str]


_Variant = tuple[tuple[str, ...], tuple[str, ...] | None]


def _words(text: str) -> tuple[list[str], list[str]]:
    """Word tokens of ``text`` in original and lower case."""
    words = _WORD_RE.findall(text.replace("’", "'"))
    return words, [word.lower() for word in words]


def _is_name_word(word: str) -> bool:
    """A capitalised word that could belong to a multi-word name ("New", "Stamp", "Adams")."""
    return word[:1].isupper() and word.lower() not in FUNCTION_WORDS


@dataclass
class _CaseStats:
    """How single words are capitalised in running text, keyed by singular lower-case word."""

    mentions: Counter[str] = field(default_factory=Counter)
    capitalised: Counter[str] = field(default_factory=Counter)
    after_name_word: Counter[str] = field(default_factory=Counter)
    before_name_word: Counter[str] = field(default_factory=Counter)
    phrase_end: Counter[str] = field(default_factory=Counter)

    @classmethod
    def from_prose(cls, texts: Iterable[str]) -> "_CaseStats":
        """Count mid-sentence mentions only, so a capital at the start of a sentence is ignored."""
        stats = cls()
        for text in texts:
            for sentence in _SENTENCE_SPLIT_RE.split(text.replace("’", "'")):
                matches = list(_WORD_RE.finditer(sentence))
                for i in range(1, len(matches)):
                    word = matches[i].group()
                    possessive = word.lower().endswith("'s")
                    key = singularize((word[:-2] if possessive else word).lower())
                    stats.mentions[key] += 1
                    if not word[:1].isupper():
                        continue
                    stats.capitalised[key] += 1
                    if _is_name_word(matches[i - 1].group()):
                        stats.after_name_word[key] += 1
                    following = sentence[matches[i].end() :].lstrip()[:1]
                    if i + 1 < len(matches) and following.isalnum():
                        next_word = matches[i + 1].group()
                        if _is_name_word(next_word):
                            stats.before_name_word[key] += 1
                        if possessive or next_word.lower() in FUNCTION_WORDS:
                            stats.phrase_end[key] += 1
                    else:  # end of sentence or punctuation follows
                        stats.phrase_end[key] += 1
        return stats

    def is_proper_noun(self, key: str) -> bool:
        """
        True for a word written as a name on its own: "Constitution", "Congress", "Lincoln".

        It must be capitalised in most mid-sentence mentions (unlike "white" or "total");
        mostly not next to another capitalised word, so parts of longer names ("York" in
        "New York", "Act" in "Stamp Act", "John" in "John Adams") are excluded; and often
        end a phrase, which proper adjectives ("British soldiers") rarely do.
        """
        mentions, capitalised = self.mentions[key], self.capitalised[key]
        if mentions == 0 or capitalised < MIN_CAPITALISED_RATIO * mentions:
            return False
        limit = MAX_NAME_PART_RATIO * capitalised
        return (
            self.after_name_word[key] < limit
            and self.before_name_word[key] < limit
            and self.phrase_end[key] >= MIN_PHRASE_END_RATIO * capitalised
        )


class _PhraseIndex:
    """Finds concept phrases (with simple plural variants) in tokenised text."""

    def __init__(self, candidates: Iterable[_Candidate]):
        self._by_first: dict[str, list[tuple[tuple[str, ...], str, tuple[str, ...] | None]]] = {}
        for candidate in candidates:
            for phrase, exact in sorted(self._variants(candidate), key=str):
                bucket = self._by_first.setdefault(phrase[0], [])
                entry = (phrase, candidate.key, exact)
                if entry not in bucket:
                    bucket.append(entry)

    @staticmethod
    def _variants(candidate: _Candidate) -> set[_Variant]:
        """Lower-case word tuples to match, with an exact-case tuple for acronyms."""
        variants: set[_Variant] = set()
        for surface in {*candidate.surfaces, *candidate.key_surfaces}:
            words, lower = _words(surface)
            if not words:
                continue
            if is_acronym(surface):  # "START" must not match the verb "start"
                variants.add((tuple(lower), tuple(words)))
                continue
            last = lower[-1]
            forms = {last, singularize(last), last + "s", last + "es"}
            if last.endswith("y"):
                forms.add(last[:-1] + "ies")
            variants.update(((*lower[:-1], form), None) for form in forms)
        for alias in candidate.aliases:
            words, lower = _words(alias)
            if words:
                variants.add((tuple(lower), tuple(words) if is_acronym(alias) else None))
        return variants

    def find(self, words: list[str], lower: list[str]) -> list[_Occurrence]:
        """Every (possibly overlapping) concept occurrence."""
        found: list[_Occurrence] = []
        for start, word in enumerate(lower):
            for phrase, key, exact in self._by_first.get(word, ()):
                end = start + len(phrase)
                if tuple(lower[start:end]) == phrase and (
                    exact is None or tuple(words[start:end]) == exact
                ):
                    found.append(_Occurrence(start, end, key))
        return found

    def find_longest(self, words: list[str], lower: list[str]) -> list[_Occurrence]:
        """Leftmost-longest, non-overlapping occurrences ("aggregate demand", not "demand")."""
        ordered = sorted(self.find(words, lower), key=lambda o: (o.start, o.start - o.end))
        kept: list[_Occurrence] = []
        end = 0
        for occurrence in ordered:
            if occurrence.start >= end:
                kept.append(occurrence)
                end = occurrence.end
        return kept


def _contains(longer: list[str], shorter: list[str]) -> bool:
    """True when the key ``shorter`` is a contiguous word run of the key ``longer``."""
    size = len(shorter)
    for start in range(len(longer) - size + 1):
        window = longer[start : start + size]
        if window[:-1] == shorter[:-1] and singularize(window[-1]) == shorter[-1]:
            return True
    return False


class KGBuilder:
    """Builder for constructing knowledge graphs from textbook content."""

    def __init__(
        self,
        max_concepts: int = 200,
        *,
        cooccurrence_threshold: int = DEFAULT_COOCCURRENCE_THRESHOLD,
        prereq_definitions: bool = True,
        prereq_patterns: bool = False,
        min_concept_length: int = 3,
    ):
        """
        Initialize KG builder.

        Args:
            max_concepts: Maximum number of concepts to keep.
            cooccurrence_threshold: Paragraphs two concepts must share for a RELATED edge.
            prereq_definitions: Create PREREQ edges from glossary definitions: a concept
                named in another concept's definition is its prerequisite ("quantity
                demanded" -> "equilibrium"). Precise on the OpenStax books, so on by default.
            prereq_patterns: Also create PREREQ edges from cue phrases in sentences
                ("builds on", "requires an understanding of", "paved the way for", …).
                Off by default: on the OpenStax books most matches are causal narration
                ("a higher price leads to …") rather than prerequisites.
            min_concept_length: Shortest keyword concept name, in characters. Author key
                terms may be as short as ``MIN_KEY_TERM_LENGTH`` ("M1").
        """
        if max_concepts < 1:
            raise ValueError("max_concepts must be at least 1")
        if cooccurrence_threshold < 1:
            raise ValueError("cooccurrence_threshold must be at least 1")
        self.max_concepts = max_concepts
        self.cooccurrence_threshold = cooccurrence_threshold
        self.prereq_definitions = prereq_definitions
        self.prereq_patterns = prereq_patterns
        self.min_concept_length = min_concept_length
        self.kg = KnowledgeGraph()

        # YAKE keyword extractor for concept extraction
        self.keyword_extractor = KeywordExtractor(
            lan="en",
            n=3,  # Max n-gram size
            dedupLim=0.7,  # Deduplication threshold
            top=20,  # Top keywords per document
            features=None,
        )

    # ------------------------------------------------------------------ extraction

    def _keywords(self, prose: str) -> list[str]:
        """YAKE keywords; every line is treated as a sentence so headings stay separate."""
        text = _LINE_END_RE.sub(".\n", prose)
        if not text.strip():
            return []
        try:
            return [keyword for keyword, _score in self.keyword_extractor.extract_keywords(text)]
        except Exception as e:  # YAKE can fail on degenerate input
            logger.warning(f"YAKE extraction failed: {e}")
            return []

    def _add_candidate(self, found: dict[str, _Candidate], raw: str, *, key_term: bool) -> None:
        name, aliases = split_abbreviations(normalize_concept(raw))
        name = normalize_concept(name)
        # Author key terms may be short ("M1", "M2"); keywords keep min_concept_length.
        min_length = MIN_KEY_TERM_LENGTH if key_term else self.min_concept_length
        max_words = None if key_term else MAX_KEYWORD_WORDS
        if not is_valid_concept(name, min_length=min_length, max_words=max_words):
            return
        if not key_term and _MODIFIER_PREFIX_RE.match(name):
            return
        key = concept_key(name)
        candidate = found.setdefault(key, _Candidate(key=key))
        (candidate.key_surfaces if key_term else candidate.surfaces)[name] += 1
        candidate.aliases.update(aliases)
        candidate.key_term = candidate.key_term or key_term

    def _candidates(self, prose: str, key_terms: Iterable[str]) -> dict[str, _Candidate]:
        found: dict[str, _Candidate] = {}
        for term in key_terms:
            self._add_candidate(found, term, key_term=True)
        for keyword in self._keywords(prose):
            self._add_candidate(found, keyword, key_term=False)
        return found

    def extract_concepts_from_text(self, text: str, key_terms: list[str]) -> list[str]:
        """
        Extract concept names from one text.

        Key terms (the ``key_terms`` argument plus ``data-type="term"`` markup and
        glossary entries in the text) come first, followed by YAKE keywords from the
        cleaned prose. Names are normalised and stop-concept filtered, case/plural
        variants are merged, and a keyword is dropped when it mostly occurs inside a
        longer concept ("United" next to "United States"). Key terms are never
        dropped as fragments.

        Args:
            text: Text to extract from (raw OpenStax Markdown or plain prose).
            key_terms: Known key terms to prioritize.

        Returns:
            Concept display names, key terms first.
        """
        marked = [*key_terms, *extract_marked_terms(text), *extract_glossary(text)]
        prose = clean_text(strip_structural_sections(text))
        found = self._candidates(prose, marked)
        occurrences = Counter(o.key for o in _PhraseIndex(found.values()).find(*_words(prose)))
        kept = self._drop_fragments(found, occurrences)
        return [c.name for c in sorted(kept.values(), key=lambda c: not c.key_term)]

    @staticmethod
    def _drop_fragments(
        candidates: dict[str, _Candidate], occurrences: Counter[str]
    ) -> dict[str, _Candidate]:
        """
        Drop keywords that are mostly fragments of one longer concept.

        "United" goes next to "United States" because nearly every "United" is part
        of "United States"; "Demand" stays next to "Aggregate Demand" because it is
        mostly used on its own. Dominance is measured against the single most
        frequent containing concept, so a word spread over many phrases
        ("Photosynthesis" in several keyword trigrams) is kept. The longer concept
        is always kept, author key terms are never removed, and the dropped
        fragment's counts are not merged into the longer concept.
        """
        words = {key: key.split() for key in candidates}
        dropped: set[str] = set()
        for key, candidate in candidates.items():
            if candidate.key_term:
                continue
            inside = max(
                (
                    occurrences[other]
                    for other in candidates
                    if len(words[other]) > len(words[key]) and _contains(words[other], words[key])
                ),
                default=None,
            )
            if inside is None:
                continue
            if occurrences[key] == 0 or inside >= FRAGMENT_DOMINANCE * occurrences[key]:
                dropped.add(key)
        return {key: c for key, c in candidates.items() if key not in dropped}

    # ------------------------------------------------------------------ building

    def build_from_records(self, records: list[dict]) -> KnowledgeGraph:
        """
        Build knowledge graph from normalized data records.

        Args:
            records: Records with ``module_id``, ``module_title``, ``key_terms`` and
                ``text`` (raw OpenStax Markdown or plain prose). Records sharing a
                ``module_id`` are treated as one module.

        Returns:
            Constructed KnowledgeGraph
        """
        logger.info(f"Building KG from {len(records)} records")
        modules = self._group_modules(records)

        # Step 1: module nodes
        for module in modules.values():
            self.kg.modules[module.module_id] = ModuleNode(
                module_id=module.module_id, title=module.title, key_terms=module.key_terms
            )

        # Step 2: candidates, cleaned prose and glossary definitions per module
        candidates: dict[str, _Candidate] = {}
        definitions: dict[str, tuple[str, str]] = {}
        prose_by_module: dict[str, str] = {}
        for module in modules.values():
            raw = "\n\n".join(module.texts)
            glossary = extract_glossary(raw)
            for term, definition in glossary.items():
                key = concept_key(split_abbreviations(normalize_concept(term))[0])
                definitions.setdefault(key, (definition, module.module_id))
            prose = clean_text(strip_structural_sections(raw))
            prose_by_module[module.module_id] = prose
            marked = [*module.key_terms, *extract_marked_terms(raw), *glossary]
            for key, found in self._candidates(prose, marked).items():
                found.modules.append(module.module_id)
                candidates.setdefault(key, _Candidate(key=key)).merge(found)
        self._merge_acronyms(candidates)
        for key, candidate in candidates.items():
            if key in definitions:
                candidate.definition, candidate.definition_module = definitions[key]

        # Step 3: select the concepts
        paragraphs = [
            _Paragraph(module_id, *_words(paragraph))
            for module_id, prose in prose_by_module.items()
            for paragraph in _PARAGRAPH_SPLIT_RE.split(prose)
        ]
        case_stats = _CaseStats.from_prose(prose_by_module.values())
        top = self._select_concepts(candidates, paragraphs, len(modules), case_stats)
        names = {candidate.key: candidate.name for candidate in top}
        logger.info(
            f"Selected {len(top)} concepts from {len(candidates)} candidates "
            f"({sum(c.key_term for c in top)} author key terms)"
        )

        # Step 4: concept nodes; frequency = number of modules that mention the concept
        index = _PhraseIndex(top)
        present_by_paragraph = [
            {o.key for o in index.find_longest(p.words, p.lower)} for p in paragraphs
        ]
        mentioned_in: dict[str, set[str]] = {c.key: set() for c in top}
        for paragraph, present in zip(paragraphs, present_by_paragraph, strict=True):
            for key in present:
                mentioned_in[key].add(paragraph.module_id)
        for candidate in top:
            name = names[candidate.key]
            surfaces = {*candidate.surfaces, *candidate.key_surfaces}
            aliases = {*candidate.aliases, *(display_name(s) for s in surfaces)}
            self.kg.add_concept(
                ConceptNode(
                    name=name,
                    definition=candidate.definition,
                    key_term=candidate.key_term,
                    frequency=len(mentioned_in[candidate.key]) or len(candidate.modules),
                    source_modules=list(candidate.modules),
                    aliases=sorted(aliases - {name}),
                )
            )

        # Step 5: COVERS relationships (Module -> Concept)
        for candidate in top:
            for module_id in candidate.modules:
                self.kg.add_relationship(
                    Relationship(
                        source=module_id,
                        target=names[candidate.key],
                        type=RelationshipType.COVERS,
                        weight=1.0,
                        confidence=1.0,
                        evidence=None,
                    )
                )

        # Step 6: RELATED relationships from paragraph co-occurrence
        self._mine_concept_relationships(present_by_paragraph, names)

        # Step 7: PREREQ relationships from glossary definitions and cue phrases
        prereqs: list[_PrereqEdge] = []
        if self.prereq_definitions:
            prereqs.extend(self._definition_prereqs(top, names, index))
        if self.prereq_patterns:
            prereqs.extend(self._pattern_prereqs(prose_by_module, index))
        self._add_prereq_relationships(prereqs, names)

        # Step 8: importance scores
        self._compute_importance_scores()

        logger.success(f"✓ KG built: {self.kg.get_stats()}")
        return self.kg

    @staticmethod
    def _group_modules(records: list[dict]) -> dict[str, _Module]:
        modules: dict[str, _Module] = {}
        for record in records:
            module_id = record["module_id"]
            module = modules.get(module_id)
            if module is None:
                module = _Module(
                    module_id=module_id,
                    title=record.get("module_title") or module_id,
                    key_terms=list(record.get("key_terms") or []),
                )
                modules[module_id] = module
            module.texts.append(record.get("text") or "")
        return modules

    @staticmethod
    def _merge_acronyms(candidates: dict[str, _Candidate]) -> None:
        """
        Fold an acronym candidate ("GDP") into the concept it abbreviates.

        The acronym becomes the display name when it was extracted from more modules
        than the spelled-out form, as "GDP" is in Economics, so a query for "GDP"
        still names the concept; the other form is kept as an alias.
        """
        for key in list(candidates):
            candidate = candidates.get(key)
            if candidate is None:
                continue
            for alias in sorted(candidate.aliases):
                alias_key = concept_key(alias)
                other = candidates.get(alias_key)
                if other is None or alias_key == key:
                    continue
                acronym_is_more_common = len(other.modules) > len(candidate.modules)
                candidate.merge(other)
                candidate.aliases.update({*other.surfaces, *other.key_surfaces})
                if acronym_is_more_common:
                    candidate.preferred = alias
                del candidates[alias_key]

    def _select_concepts(
        self,
        candidates: dict[str, _Candidate],
        paragraphs: list[_Paragraph],
        module_count: int,
        case_stats: _CaseStats,
    ) -> list[_Candidate]:
        """
        Pick the ``max_concepts`` best candidates.

        Author key terms are always eligible. A YAKE-only phrase must be a top keyword
        of at least ``MIN_KEYWORD_MODULE_RATIO`` of the modules and, in a corpus of at
        least ``MIN_MODULES_FOR_DOCUMENT_RATIO`` modules, be mentioned in at most
        ``MAX_KEYWORD_DOCUMENT_RATIO`` of them; fragments of longer concepts are
        dropped. Candidates are ranked by the number of modules mentioning them.

        Single-word keywords are mostly generic ("War", "Government", "White"), so they
        rank below key terms and multi-word phrases, with one exception: up to
        ``SINGLE_WORD_QUOTA`` of the slots go to single words that the text writes as
        proper nouns ("Constitution", "Congress", "Union", "Lincoln"), most widely
        mentioned first. Other single words only fill slots nothing else wants.
        """
        min_modules = max(1, int(module_count * MIN_KEYWORD_MODULE_RATIO))
        eligible = {
            key: c for key, c in candidates.items() if c.key_term or len(c.modules) >= min_modules
        }
        index = _PhraseIndex(eligible.values())
        occurrences: Counter[str] = Counter()
        mentioned_in: dict[str, set[str]] = {key: set() for key in eligible}
        for paragraph in paragraphs:
            occurrences.update(o.key for o in index.find(paragraph.words, paragraph.lower))
            for occurrence in index.find_longest(paragraph.words, paragraph.lower):
                mentioned_in[occurrence.key].add(paragraph.module_id)

        if module_count >= MIN_MODULES_FOR_DOCUMENT_RATIO:
            limit = MAX_KEYWORD_DOCUMENT_RATIO * module_count
            eligible = {
                key: c
                for key, c in eligible.items()
                if c.key_term or len(mentioned_in[key]) <= limit
            }
        eligible = self._drop_fragments(eligible, occurrences)

        def rank(candidate: _Candidate) -> tuple[bool, int, int, int, str]:
            return (
                candidate.key_term or not candidate.is_single_word,
                len(mentioned_in[candidate.key]),
                len(candidate.modules),
                occurrences[candidate.key],
                candidate.key,
            )

        ranked = sorted(eligible.values(), key=rank, reverse=True)
        preferred = [c for c in ranked if c.key_term or not c.is_single_word]
        single_words = [c for c in ranked if not c.key_term and c.is_single_word]
        proper_nouns = [c for c in single_words if case_stats.is_proper_noun(c.key)]
        proper_nouns = proper_nouns[: int(self.max_concepts * SINGLE_WORD_QUOTA)]
        chosen = {c.key for c in proper_nouns}

        selected = preferred[: self.max_concepts - len(proper_nouns)] + proper_nouns
        leftovers = [c for c in single_words if c.key not in chosen]
        selected += leftovers[: self.max_concepts - len(selected)]
        return sorted(selected, key=rank, reverse=True)

    def _mine_concept_relationships(
        self, present_by_paragraph: list[set[str]], names: dict[str, str]
    ) -> None:
        """
        Create RELATED edges between concepts that share paragraphs.

        Args:
            present_by_paragraph: Concept keys found in each paragraph.
            names: Concept key -> display name.
        """
        cooccurrence: Counter[tuple[str, str]] = Counter()
        for present in present_by_paragraph:
            ordered = sorted(present)
            for i, first in enumerate(ordered):
                for second in ordered[i + 1 :]:
                    cooccurrence[(first, second)] += 1

        threshold = self.cooccurrence_threshold
        related = 0
        for (first, second), count in sorted(cooccurrence.items()):
            if count < threshold:
                continue
            self.kg.add_relationship(
                Relationship(
                    source=names[first],
                    target=names[second],
                    type=RelationshipType.RELATED,
                    weight=min(count / 10.0, 1.0),  # Normalize to 0-1
                    confidence=0.7,  # Medium confidence for co-occurrence
                    evidence=None,
                )
            )
            related += 1
        logger.info(f"Mined {related} RELATED relationships (threshold={threshold})")

    @staticmethod
    def _definition_prereqs(
        concepts: list[_Candidate], names: dict[str, str], index: _PhraseIndex
    ) -> list[_PrereqEdge]:
        """A concept named in another concept's glossary definition is its prerequisite."""
        edges: list[_PrereqEdge] = []
        for candidate in concepts:
            if not candidate.definition:
                continue
            named = {o.key for o in index.find_longest(*_words(candidate.definition))}
            for key in sorted(named - {candidate.key}):
                edges.append(
                    _PrereqEdge(
                        prerequisite=key,
                        dependent=candidate.key,
                        evidence=f"{names[candidate.key]}: {candidate.definition}"[:300],
                        confidence=0.8,
                        provenance={
                            "source": "glossary",
                            "module_id": candidate.definition_module or "",
                        },
                    )
                )
        return edges

    @staticmethod
    def _pattern_prereqs(prose_by_module: dict[str, str], index: _PhraseIndex) -> list[_PrereqEdge]:
        """
        PREREQ candidates from cue phrases, pairing the concepts nearest to the cue.

        For "A paved the way for B" the prerequisite (A) precedes the cue; for
        "B builds on A" it follows.
        """
        edges: list[_PrereqEdge] = []
        for module_id, prose in prose_by_module.items():
            for sentence in _SENTENCE_SPLIT_RE.split(prose):
                for pattern in PREREQ_PATTERNS:
                    match = pattern.regex.search(sentence)
                    if not match:
                        continue
                    before = index.find_longest(*_words(sentence[: match.start()]))
                    after = index.find_longest(*_words(sentence[match.end() :]))
                    if not before or not after:
                        continue
                    left, right = before[-1].key, after[0].key
                    prerequisite, dependent = (
                        (left, right) if pattern.prerequisite_first else (right, left)
                    )
                    edges.append(
                        _PrereqEdge(
                            prerequisite=prerequisite,
                            dependent=dependent,
                            evidence=sentence.strip()[:300],
                            confidence=0.5,
                            provenance={
                                "source": "cue_phrase",
                                "pattern": pattern.name,
                                "module_id": module_id,
                            },
                        )
                    )
        return edges

    def _add_prereq_relationships(self, edges: list[_PrereqEdge], names: dict[str, str]) -> None:
        """
        Add PREREQ edges while keeping the prerequisite graph acyclic.

        Mutual pairs from the same source (each concept named in the other's
        definition) have no clear order and are skipped; any other edge that would
        close a cycle is skipped too. Earlier (higher-confidence) edges win, so a
        cue-phrase edge never cancels the reverse glossary edge.
        """
        pairs = {
            (edge.provenance.get("source"), edge.prerequisite, edge.dependent) for edge in edges
        }
        dag: nx.DiGraph = nx.DiGraph()
        added = 0
        for edge in edges:
            source, target = edge.prerequisite, edge.dependent
            mutual = (edge.provenance.get("source"), target, source) in pairs
            if source == target or mutual or dag.has_edge(source, target):
                continue
            if source in dag and target in dag and nx.has_path(dag, target, source):
                continue
            dag.add_edge(source, target)
            self.kg.add_relationship(
                Relationship(
                    source=names[source],
                    target=names[target],
                    type=RelationshipType.PREREQ,
                    weight=0.8,
                    confidence=edge.confidence,
                    evidence=edge.evidence,
                    provenance=edge.provenance,
                )
            )
            added += 1
        logger.info(f"Added {added} PREREQ relationships ({len(edges)} candidates)")

    def _compute_importance_scores(self) -> None:
        """Compute importance scores for concepts using PageRank."""
        graph = nx.Graph()
        graph.add_nodes_from(self.kg.concepts)

        # Add edges (include both RELATED and PREREQ)
        for rel in self.kg.relationships:
            if rel.type in (RelationshipType.RELATED, RelationshipType.PREREQ):
                graph.add_edge(rel.source, rel.target, weight=rel.weight)

        # Compute PageRank and normalise to 0-1
        if len(graph.nodes) > 0:
            pagerank = nx.pagerank(graph, weight="weight")
            max_pr = max(pagerank.values())
            for concept_name, pr_score in pagerank.items():
                self.kg.concepts[concept_name].importance_score = pr_score / max_pr

        logger.info("Computed importance scores using PageRank")

    def get_top_concepts(self, n: int = 20) -> list[tuple[str, float]]:
        """
        Get top N concepts by importance.

        Args:
            n: Number of concepts to return

        Returns:
            List of (concept_name, importance_score) tuples
        """
        concepts_with_scores = [
            (name, node.importance_score) for name, node in self.kg.concepts.items()
        ]
        concepts_with_scores.sort(key=lambda x: x[1], reverse=True)
        return concepts_with_scores[:n]
