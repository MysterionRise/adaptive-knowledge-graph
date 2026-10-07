"""
The embedding-stack fingerprint stored in each OpenSearch index (#71).

- Pinned model revisions: BGE-M3 loads a fixed commit unless a revision is configured
- fingerprint() / check_fingerprint(): match, another model, probe drift, another revision
- OpenSearchRetriever.create_collection() writes the fingerprint into the mapping's _meta
- `stack_check.py index-fingerprint` (run by make doctor): exit 0, 1 or 2

The embedding model is a fake: nothing is downloaded.
"""

import math
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.app.core.settings import PINNED_MODEL_REVISIONS, Settings, model_revision, settings
from backend.app.rag.index_fingerprint import (
    PROBE_TEXT,
    check_fingerprint,
    cosine,
    fingerprint,
)
from scripts import stack_check

pytestmark = pytest.mark.unit

BGE_M3 = "BAAI/bge-m3"
PINNED = PINNED_MODEL_REVISIONS[BGE_M3]


class FakeEncoder:
    """Encodes every text to `vector` (normalized), recording what it was asked."""

    def __init__(self, vector: list[float], model_name: str = BGE_M3):
        self.model_name = model_name
        self.vector = vector
        self.texts: list[str] = []

    def encode(self, texts, normalize=True):
        texts = [texts] if isinstance(texts, str) else texts
        self.texts.extend(texts)
        norm = math.sqrt(sum(x * x for x in self.vector)) if normalize else 1.0
        return [[x / norm for x in self.vector] for _ in texts]


@pytest.fixture
def default_revision(monkeypatch):
    """No EMBEDDING_MODEL_REVISION configured: BGE-M3 loads its pinned commit."""
    monkeypatch.setattr(settings, "embedding_model_revision", None)


class TestModelRevision:
    def test_bge_m3_is_pinned_by_default(self):
        assert model_revision(BGE_M3, None) == PINNED
        assert len(PINNED) == 40 and int(PINNED, 16) >= 0  # a full commit hash

    def test_a_configured_revision_wins(self):
        assert model_revision(BGE_M3, "abc123") == "abc123"
        assert model_revision(BGE_M3, "main") == "main"

    def test_other_models_are_not_pinned(self):
        assert model_revision("intfloat/multilingual-e5-large", None) is None
        assert model_revision("BAAI/bge-reranker-v2-m3", None) is None

    def test_effective_revisions_on_settings(self):
        defaults = Settings(_env_file=None, embedding_model_revision="", reranker_model_revision="")
        assert defaults.effective_embedding_revision == PINNED
        assert defaults.effective_reranker_revision is None

        other = Settings(
            _env_file=None,
            embedding_model="intfloat/multilingual-e5-large",
            reranker_model_revision="r1",
        )
        assert other.effective_embedding_revision is None
        assert other.effective_reranker_revision == "r1"


class TestCosine:
    def test_identical_and_orthogonal(self):
        assert cosine([0.6, 0.8], [0.6, 0.8]) == pytest.approx(1.0)
        assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_degenerate_vectors_score_zero(self):
        assert cosine([], []) == 0.0
        assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0
        assert cosine([1.0], [1.0, 0.0]) == 0.0


class TestFingerprint:
    def test_records_model_revision_dimension_and_probe(self, default_revision):
        encoder = FakeEncoder([3.0, 4.0, 0.0])

        meta = fingerprint(encoder)

        assert meta == {
            "model": BGE_M3,
            "revision": PINNED,
            "dimension": 3,
            "probe_text": PROBE_TEXT,
            "probe_vector": [0.6, 0.8, 0.0],
        }
        assert encoder.texts == [PROBE_TEXT]

    def test_probe_vector_is_rounded(self, default_revision):
        meta = fingerprint(FakeEncoder([1.0, 2.0, 3.0]))

        assert meta["probe_vector"] == [0.267261, 0.534522, 0.801784]

    def test_records_the_configured_revision(self, monkeypatch):
        monkeypatch.setattr(settings, "embedding_model_revision", "main")

        assert fingerprint(FakeEncoder([1.0, 0.0]))["revision"] == "main"


class TestCheckFingerprint:
    def test_matching_stack_passes(self, default_revision):
        encoder = FakeEncoder([1.0, 2.0, 3.0])

        check = check_fingerprint(fingerprint(encoder), encoder)

        assert check.errors == [] and check.warnings == []
        assert check.probe_cosine == pytest.approx(1.0)

    def test_another_model_fails_without_comparing_vectors(self, default_revision):
        meta = fingerprint(FakeEncoder([1.0, 0.0], model_name="intfloat/multilingual-e5-large"))
        encoder = FakeEncoder([1.0, 0.0])

        check = check_fingerprint(meta, encoder)

        assert check.errors == [
            f"built with intfloat/multilingual-e5-large, but the configured model is {BGE_M3}"
        ]
        assert check.probe_cosine is None
        assert encoder.texts == []

    def test_drifted_probe_fails(self, default_revision):
        meta = fingerprint(FakeEncoder([1.0, 0.0, 0.0]))

        check = check_fingerprint(meta, FakeEncoder([1.0, 0.1, 0.0]))

        assert check.probe_cosine is not None and check.probe_cosine < 0.999
        assert len(check.errors) == 1
        assert "no longer reproduces the stored vectors" in check.errors[0]
        assert check.warnings == []

    def test_drift_within_the_threshold_passes(self, default_revision):
        meta = fingerprint(FakeEncoder([1.0, 0.0, 0.0]))

        check = check_fingerprint(meta, FakeEncoder([1.0, 0.01, 0.0]))

        assert check.errors == []
        assert 0.999 <= check.probe_cosine < 1.0

    def test_another_revision_with_a_matching_probe_only_warns(self, monkeypatch):
        monkeypatch.setattr(settings, "embedding_model_revision", "main")
        encoder = FakeEncoder([1.0, 2.0])
        meta = fingerprint(encoder)
        monkeypatch.setattr(settings, "embedding_model_revision", None)

        check = check_fingerprint(meta, encoder)

        assert check.errors == []
        assert check.warnings == [
            f"built with revision main, configured {PINNED}; the probe vector still matches"
        ]

    def test_dimension_change_fails(self, default_revision):
        meta = fingerprint(FakeEncoder([1.0, 0.0, 0.0]))

        check = check_fingerprint(meta, FakeEncoder([1.0, 0.0]))

        assert check.probe_cosine == 0.0
        assert check.errors

    def test_stored_probe_text_is_encoded(self, default_revision):
        meta = {**fingerprint(FakeEncoder([1.0, 0.0])), "probe_text": "an older probe"}
        encoder = FakeEncoder([1.0, 0.0])

        check_fingerprint(meta, encoder)

        assert encoder.texts == ["an older probe"]

    def test_missing_probe_vector_fails(self, default_revision):
        check = check_fingerprint({"model": BGE_M3, "revision": PINNED}, FakeEncoder([1.0]))

        assert check.errors == ["the fingerprint has no probe vector"]

    def test_custom_threshold(self, default_revision):
        meta = fingerprint(FakeEncoder([1.0, 0.0]))

        check = check_fingerprint(meta, FakeEncoder([1.0, 0.5]), threshold=0.8)

        assert check.errors == []


class TestCreateCollection:
    def test_new_index_mapping_carries_the_fingerprint(self, default_revision):
        encoder = FakeEncoder([0.0, 3.0, 4.0])
        with patch("backend.app.rag.retriever.get_embedding_model", return_value=encoder):
            from backend.app.rag.retriever import OpenSearchRetriever

            retriever = OpenSearchRetriever(index_name="textbook_chunks_test")
        retriever.client = MagicMock()
        retriever.client.indices.exists.return_value = False

        retriever.create_collection(embedding_dim=3)

        mappings = retriever.client.indices.create.call_args.kwargs["body"]["mappings"]
        assert mappings["_meta"] == {"embedding": fingerprint(encoder)}
        assert mappings["_meta"]["embedding"]["dimension"] == 3
        assert mappings["properties"]["embedding"]["dimension"] == 3


# ---------------------------------------------------------------------------
# stack_check.py index-fingerprint
# ---------------------------------------------------------------------------


def _mapping(index: str, meta: dict | None) -> dict:
    mappings: dict = {"properties": {"text": {"type": "text"}}}
    if meta is not None:
        mappings["_meta"] = {"embedding": meta}
    return {index: {"mappings": mappings}}


@pytest.fixture
def fake_stack(monkeypatch, default_revision):
    """OpenSearch mappings per index, a cached model and a fake EmbeddingModel."""
    state = SimpleNamespace(
        responses={},  # index -> (status, body) or an exception to raise
        requested=[],
        cached=True,
        vector=[1.0, 2.0, 3.0],
        loads=0,
        load_error=None,
        offline_at_load=None,
    )

    def fake_http_json(url, payload=None, timeout=5.0, auth=None, context=None):
        index = url.split("/")[-2]
        state.requested.append(url)
        response = state.responses.get(index, (404, {"error": "index_not_found_exception"}))
        if isinstance(response, Exception):
            raise response
        return response

    class FakeEmbeddingModel(FakeEncoder):
        def __init__(self):
            super().__init__(state.vector)

        def load(self):
            state.loads += 1
            state.offline_at_load = os.environ.get("HF_HUB_OFFLINE")
            if state.load_error:
                raise state.load_error

    monkeypatch.setattr(stack_check, "_http_json", fake_http_json)
    monkeypatch.setattr(
        "backend.app.core.privacy.hf_model_is_cached", lambda model, revision=None: state.cached
    )
    monkeypatch.setattr("backend.app.nlp.embeddings.EmbeddingModel", FakeEmbeddingModel)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")  # what the command sets for a cached model
    monkeypatch.setattr(settings, "embedding_model", BGE_M3)
    return state


def _run(*subjects: str) -> int:
    return stack_check.main(["index-fingerprint", *subjects])


US = "textbook_chunks_us_history"
ECON = "textbook_chunks_economics"


class TestIndexFingerprintCommand:
    def test_matching_indexes_pass(self, fake_stack, capsys):
        meta = fingerprint(FakeEncoder(fake_stack.vector))
        fake_stack.responses = {US: (200, _mapping(US, meta)), ECON: (200, _mapping(ECON, meta))}

        assert _run("us_history", "economics") == 0

        out = capsys.readouterr().out
        assert out.startswith(
            "Index fingerprints match the embedding stack (us_history, economics;"
        )
        assert "lowest probe cosine 1.000000" in out
        assert fake_stack.loads == 1  # one model load for every subject
        assert fake_stack.requested[0].endswith(f"/{US}/_mapping")

    def test_drift_fails_with_a_rebuild_hint(self, fake_stack, capsys):
        meta = fingerprint(FakeEncoder([1.0, 0.0, 0.0]))
        fake_stack.responses = {US: (200, _mapping(US, meta))}

        assert _run("us_history") == 1

        out = capsys.readouterr().out
        assert out.startswith("Index fingerprints do not match the embedding stack")
        assert "us_history: probe vector cosine" in out
        assert "make index-rag SUBJECT=us_history RECREATE=1" in out

    def test_another_model_fails(self, fake_stack, capsys):
        meta = fingerprint(FakeEncoder(fake_stack.vector, model_name="other/model"))
        fake_stack.responses = {US: (200, _mapping(US, meta))}

        assert _run("us_history") == 1
        assert "built with other/model" in capsys.readouterr().out

    def test_index_without_fingerprint_warns(self, fake_stack, capsys):
        fake_stack.responses = {US: (200, _mapping(US, None))}

        assert _run("us_history") == 2

        out = capsys.readouterr().out
        assert out.startswith("Index fingerprints: 1 warning(s) (checked: none)")
        assert "built before index fingerprints" in out
        assert "make index-rag SUBJECT=us_history RECREATE=1" in out
        assert fake_stack.loads == 0

    def test_revision_change_warns(self, fake_stack, monkeypatch, capsys):
        meta = {**fingerprint(FakeEncoder(fake_stack.vector)), "revision": "0" * 40}
        fake_stack.responses = {US: (200, _mapping(US, meta))}

        assert _run("us_history") == 2

        out = capsys.readouterr().out
        assert "(checked: us_history)" in out
        assert f"built with revision {'0' * 40}, configured {PINNED}" in out

    def test_missing_indexes_are_skipped(self, fake_stack, capsys):
        assert _run("us_history", "economics") == 0

        assert capsys.readouterr().out.strip() == "Index fingerprints: no seeded index to check"
        assert fake_stack.loads == 0

    def test_uncached_model_warns_instead_of_downloading(self, fake_stack, capsys):
        fake_stack.cached = False
        meta = fingerprint(FakeEncoder(fake_stack.vector))
        fake_stack.responses = {US: (200, _mapping(US, meta))}

        assert _run("us_history") == 2

        assert "is not cached, so the fingerprints were not checked" in capsys.readouterr().out
        assert fake_stack.loads == 0

    def test_model_load_failure_fails(self, fake_stack, capsys):
        fake_stack.load_error = OSError("out of memory")
        fake_stack.responses = {US: (200, _mapping(US, fingerprint(FakeEncoder([1.0]))))}

        assert _run("us_history") == 1

        out = capsys.readouterr().out
        assert out.startswith("Index fingerprints could not be checked")
        assert "OSError: out of memory" in out

    def test_unreadable_mapping_fails(self, fake_stack, capsys):
        fake_stack.responses = {US: OSError("connection refused"), ECON: (500, {})}

        assert _run("us_history", "economics") == 1

        out = capsys.readouterr().out
        assert out.startswith("Index fingerprints could not be checked")
        assert f"us_history: cannot read the {US} mapping (connection refused)" in out
        assert f"economics: cannot read the {ECON} mapping (HTTP 500)" in out

    def test_alias_resolves_to_the_concrete_index(self, fake_stack, capsys):
        meta = fingerprint(FakeEncoder(fake_stack.vector))
        fake_stack.responses = {US: (200, _mapping(f"{US}_v2", meta))}

        assert _run("us_history") == 0

    def test_offline_is_set_before_the_model_loads(self, fake_stack, monkeypatch):
        monkeypatch.delenv("HF_HUB_OFFLINE")
        fake_stack.responses = {US: (200, _mapping(US, fingerprint(FakeEncoder([1.0]))))}

        _run("us_history")

        assert fake_stack.offline_at_load == "1"
