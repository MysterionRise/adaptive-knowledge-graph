"""
What the query-time concept lexicon would take from a domain (#211).

``backend.app.nlp.lexicon.ConceptLexicon`` is built from the concept names and aliases
stored in the subject's graph. A curated domain adds three things to that: the approved
aliases of each concept, the names a reviewer rejected or deprecated, and the context
terms that tell two senses of a shared alias apart.

This module is not wired into the request path. Nothing in ``backend.app.rag`` or
``backend.app.nlp`` imports it, so retrieval is unchanged by this module; it only fixes
the shape of what a domain provides. Curated aliases still reach questions today, because
``apply`` writes them to the graph and the lexicon reads the graph. Using
``context_terms`` at query time is a later change.

The functions are pure: they read a loaded ``Domain`` and touch neither files nor
services.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from backend.app.domain.models import REMOVING_STATUSES, WRITING_STATUSES, Domain


@dataclass(frozen=True)
class DomainLexicon:
    """The curated part of a subject's lexicon."""

    aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """Approved term name -> its aliases, in dictionary order."""

    rejected_names: frozenset[str] = frozenset()
    """Names of rejected and deprecated terms: a question must not resolve to them."""

    context_terms: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """Approved term name -> the words that select this sense of a shared alias."""


def domain_lexicon(domain: Domain | None) -> DomainLexicon:
    """
    The curated lexicon of a domain; empty for ``None`` (a subject without a domain).

    Only approved terms contribute aliases and context terms. Extracted and proposed
    terms contribute nothing.
    """
    if domain is None:
        return DomainLexicon()
    approved = [term for term in domain.terms if term.review_status in WRITING_STATUSES]
    return DomainLexicon(
        aliases={term.name: tuple(term.aliases) for term in approved},
        rejected_names=frozenset(
            term.name for term in domain.terms if term.review_status in REMOVING_STATUSES
        ),
        context_terms={
            term.name: tuple(term.context_terms) for term in approved if term.context_terms
        },
    )


def merged_aliases(
    graph_aliases: Mapping[str, Iterable[str]], lexicon: DomainLexicon
) -> dict[str, list[str]]:
    """
    The name-to-aliases mapping a ``ConceptLexicon`` would be built from.

    Starts from the graph's concepts (``Neo4jAdapter.get_concept_aliases()``), drops the
    rejected names and adds each concept's approved aliases after the stored ones, without
    repeating any. An approved term that the graph does not hold is left out: the lexicon
    must only resolve to concepts that exist.
    """
    merged: dict[str, list[str]] = {}
    for name, stored in graph_aliases.items():
        if name in lexicon.rejected_names:
            continue
        merged[name] = list(dict.fromkeys([*stored, *lexicon.aliases.get(name, ())]))
    return merged
