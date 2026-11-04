"""
Request-scoped retrieval trace (#216): what each retrieval stage did, and how long it took.

The stages, in order: ``resolve`` (the question's spans and the concepts they name),
``expand`` (the concepts the keyword channel uses and the graph neighbours, each with the
concept, edge types and provenance that produced it), ``knn`` and ``bm25`` (each channel's
ranked hits), ``fuse`` (reciprocal rank fusion with each candidate's per-channel rank and
contribution), ``window`` and ``rerank`` (whether they ran and what they changed) and
``select`` (the sources returned). A trace is keyed by the request's ``X-Request-ID``.

Tracing only observes: the retrieval is the same with it on or off. ``NO_TRACE`` stands in
when it is off, so the pipeline has one code path.

The trace never leaves the process unless a request asks for it (``include_trace``), and
then only through ``RetrievalTrace.to_dict``, which keeps the fields allowlisted below and
cuts every string to ``PREVIEW_CHARS``: no prompt text, no chunk text beyond the source
preview, no hosts or credentials. It is unrelated to the LangSmith tracing that
``PRIVACY_LOCAL_ONLY`` refuses.
"""

import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

STAGES = ("resolve", "expand", "knn", "bm25", "fuse", "window", "rerank", "select")
"""Retrieval stages in pipeline order."""

RETRIEVAL_STAGES = STAGES[2:]
"""The stages after expansion: what a KG run and a plain run of one question can share."""

PREVIEW_CHARS = 200
"""Longest string a serialised trace holds (a source preview, like ``/ask``'s sources)."""

# Fields a stage may serialise; anything else a stage records is dropped.
STAGE_FIELDS: dict[str, frozenset[str]] = {
    "resolve": frozenset({"terms", "concepts"}),
    "expand": frozenset({"used", "related", "neighbours", "failed_lookups"}),
    "knn": frozenset({"hits"}),
    "bm25": frozenset({"hits"}),
    "fuse": frozenset({"k", "candidates"}),
    "window": frozenset({"ran", "chunks_in", "chunks_out"}),
    "rerank": frozenset({"ran", "order"}),
    "select": frozenset({"sources"}),
}

# Fields of the items in a list-of-records field.
ITEM_FIELDS: dict[str, frozenset[str]] = {
    "terms": frozenset({"surface", "canonical", "via", "strategy", "status", "candidates"}),
    "neighbours": frozenset({"concept", "source", "edges", "provenance", "weight"}),
    "hits": frozenset({"id", "rank", "score"}),
    "candidates": frozenset(
        {"id", "rank", "score", "knn_rank", "bm25_rank", "knn", "bm25", "chapter", "section"}
    ),
    "sources": frozenset({"id", "rank", "chapter", "section", "score", "preview"}),
}


def _clean(value: Any) -> Any:
    """A JSON-safe copy of a scalar or a list of scalars, strings cut to PREVIEW_CHARS."""
    if isinstance(value, str):
        return value[:PREVIEW_CHARS]
    if isinstance(value, bool | int | None):
        return value
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, list | tuple):
        return [_clean(item) for item in value if not isinstance(item, Mapping)]
    return None


def _clean_field(name: str, value: Any) -> Any:
    item_fields = ITEM_FIELDS.get(name)
    if item_fields is None:
        return _clean(value)
    return [
        {key: _clean(item[key]) for key in sorted(item_fields) if key in item}
        for item in value or []
        if isinstance(item, Mapping)
    ]


def sanitize(trace: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Apply the allowlist to a serialised trace (also to one read back from a report)."""
    if not trace:
        return None
    stages = []
    for stage in trace.get("stages") or []:
        if not isinstance(stage, Mapping) or stage.get("name") not in STAGE_FIELDS:
            continue
        name = str(stage["name"])
        clean: dict[str, Any] = {"name": name, "elapsed_ms": _clean(stage.get("elapsed_ms"))}
        for key in sorted(STAGE_FIELDS[name]):
            if key in stage:
                clean[key] = _clean_field(key, stage[key])
        stages.append(clean)
    return {"request_id": _clean(trace.get("request_id")), "stages": stages}


@dataclass
class _Stage:
    name: str
    elapsed_ms: float
    data: dict[str, Any] = field(default_factory=dict)


class RetrievalTrace:
    """The stages of one request's retrieval."""

    enabled = True

    def __init__(self, request_id: str | None = None):
        self.request_id = request_id
        self._stages: list[_Stage] = []

    @contextmanager
    def stage(self, name: str) -> Iterator[dict[str, Any]]:
        """Time a stage; the caller fills the yielded dict with what the stage did."""
        if name not in STAGE_FIELDS:
            raise ValueError(f"Unknown retrieval stage: {name}")
        data: dict[str, Any] = {}
        started = time.perf_counter()
        try:
            yield data
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            self._stages.append(_Stage(name, elapsed_ms, data))

    def to_dict(self) -> dict[str, Any] | None:
        """The trace through the allowlist, stages in the order they ran."""
        return sanitize(
            {
                "request_id": self.request_id,
                "stages": [
                    {"name": stage.name, "elapsed_ms": stage.elapsed_ms, **stage.data}
                    for stage in self._stages
                ],
            }
        )


class _NoTrace(RetrievalTrace):
    """Tracing off: stages are not timed and nothing is kept."""

    enabled = False

    def __init__(self) -> None:
        super().__init__(None)

    @contextmanager
    def stage(self, name: str) -> Iterator[dict[str, Any]]:
        yield {}

    def to_dict(self) -> dict[str, Any] | None:
        return None


NO_TRACE: RetrievalTrace = _NoTrace()
"""The trace to pass when tracing is off."""


def hits(raw_hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """An OpenSearch channel's hits as trace records: id, 1-based rank and score."""
    return [
        {"id": hit.get("_id"), "rank": rank, "score": hit.get("_score")}
        for rank, hit in enumerate(raw_hits, start=1)
    ]


def sources(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The selected chunks as trace records, with a text preview."""
    return [
        {
            "id": chunk.get("id"),
            "rank": rank,
            "chapter": chunk.get("chapter"),
            "section": chunk.get("section"),
            "score": chunk.get("score"),
            "preview": str(chunk.get("text") or "")[:PREVIEW_CHARS],
        }
        for rank, chunk in enumerate(chunks, start=1)
    ]


def stage_of(trace: Mapping[str, Any] | None, name: str) -> dict[str, Any] | None:
    """A serialised trace's record of one stage, or None when the stage did not run."""
    for stage in (trace or {}).get("stages") or []:
        if isinstance(stage, Mapping) and stage.get("name") == name:
            return dict(stage)
    return None


def stage_signature(trace: Mapping[str, Any] | None, name: str) -> Any:
    """What a stage decided, without timings or scores: compared to find where two runs part."""
    stage = stage_of(trace, name)
    if stage is None:
        return None
    if name == "resolve":
        return stage.get("concepts")
    if name == "expand":
        return stage.get("used")
    if name in ("knn", "bm25"):
        return [hit.get("id") for hit in stage.get("hits") or []]
    if name == "fuse":
        return [candidate.get("id") for candidate in stage.get("candidates") or []]
    if name == "window":
        return (stage.get("ran"), stage.get("chunks_out"))
    if name == "rerank":
        return (stage.get("ran"), stage.get("order"))
    return [source.get("id") or source.get("section") for source in stage.get("sources") or []]


def first_divergent_stage(
    base: Mapping[str, Any] | None,
    head: Mapping[str, Any] | None,
    stages: tuple[str, ...] = STAGES,
) -> str | None:
    """The first of ``stages``, in pipeline order, whose decision differs between two traces."""
    if not base or not head:
        return None
    for name in stages:
        if stage_signature(base, name) != stage_signature(head, name):
            return name
    return None
