"""
Fingerprint of the embedding stack that built an OpenSearch index (#71).

``OpenSearchRetriever.create_collection`` stores the embedding model, its revision, the
vector dimension and the vector of a fixed probe text in the index mapping's ``_meta``.
``scripts/stack_check.py index-fingerprint`` (run by ``make doctor``) re-embeds the probe
with the installed stack and compares: another model, or a probe vector that drifted below
cosine 0.999 (after a transformers, sentence-transformers or torch upgrade, say), means new
query vectors no longer match the stored ones and the index needs rebuilding. A different
revision whose probe still matches is only worth a warning.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.app.core.settings import model_revision, settings

PROBE_TEXT = (
    "Index fingerprint probe: the Declaration of Independence, supply and demand, and how "
    "a cell membrane controls what enters the cell."
)
PROBE_DECIMALS = 6
DEFAULT_THRESHOLD = 0.999


class Encoder(Protocol):
    """The part of ``EmbeddingModel`` a fingerprint needs."""

    model_name: str

    def encode(self, texts: str | list[str], normalize: bool = ...) -> list[list[float]]: ...


@dataclass
class FingerprintCheck:
    """Outcome of comparing an index fingerprint with the installed embedding stack."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    probe_cosine: float | None = None


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; 0.0 when either vector is empty, zero or of another length."""
    if len(a) != len(b) or not a:
        return 0.0
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


def fingerprint(model: Encoder) -> dict[str, Any]:
    """The ``_meta.embedding`` block for an index whose vectors ``model`` produces."""
    vector = [float(x) for x in model.encode([PROBE_TEXT], normalize=True)[0]]
    return {
        "model": model.model_name,
        "revision": model_revision(model.model_name, settings.embedding_model_revision),
        "dimension": len(vector),
        "probe_text": PROBE_TEXT,
        "probe_vector": [round(x, PROBE_DECIMALS) for x in vector],
    }


def check_fingerprint(
    meta: dict[str, Any], model: Encoder, threshold: float = DEFAULT_THRESHOLD
) -> FingerprintCheck:
    """Compare an index's ``_meta.embedding`` with what ``model`` produces now."""
    result = FingerprintCheck()
    if meta.get("model") != model.model_name:
        # Another model's vectors are not comparable, so the probe is not checked
        result.errors.append(
            f"built with {meta.get('model')}, but the configured model is {model.model_name}"
        )
        return result
    stored = meta.get("probe_vector")
    if not isinstance(stored, list) or not stored:
        result.errors.append("the fingerprint has no probe vector")
        return result
    probe = str(meta.get("probe_text") or PROBE_TEXT)
    current = [float(x) for x in model.encode([probe], normalize=True)[0]]
    result.probe_cosine = cosine(stored, current)
    if result.probe_cosine < threshold:
        result.errors.append(
            f"probe vector cosine {result.probe_cosine:.6f} is below {threshold}: the installed "
            "embedding stack no longer reproduces the stored vectors"
        )
        return result
    revision = model_revision(model.model_name, settings.embedding_model_revision)
    if meta.get("revision") != revision:
        result.warnings.append(
            f"built with revision {meta.get('revision')}, configured {revision}; the probe "
            "vector still matches"
        )
    return result
