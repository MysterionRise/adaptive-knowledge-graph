"""
Tests for scripts/check_embedding_parity.py, the embedding-stack upgrade check (#71).

OpenSearch, the embedding model and the reranker are fakes: nothing is downloaded.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scripts import check_embedding_parity as parity

pytestmark = pytest.mark.unit


def _hit(chunk_id: str, text: str | None, embedding: list[float] | None) -> dict:
    return {"_id": chunk_id, "_source": {"id": chunk_id, "text": text, "embedding": embedding}}


def _chunk(chunk_id: str, text: str, embedding: list[float]) -> dict:
    return {"id": chunk_id, "text": text, "embedding": embedding}


class TestSampleChunks:
    def test_queries_a_fixed_sample_and_skips_incomplete_hits(self):
        client = MagicMock()
        client.search.return_value = {
            "hits": {
                "hits": [
                    _hit("a", "Alpha text", [1.0, 0.0]),
                    _hit("b", None, [0.0, 1.0]),
                    _hit("c", "Gamma text", None),
                ]
            }
        }

        chunks = parity.sample_chunks(client, "akg_test", 3)

        assert chunks == [_chunk("a", "Alpha text", [1.0, 0.0])]
        body = client.search.call_args.kwargs["body"]
        assert client.search.call_args.kwargs["index"] == "akg_test"
        assert body["size"] == 3
        assert body["sort"] == [{"id": "asc"}]
        assert body["_source"] == ["id", "text", "embedding"]


class TestCosine:
    def test_identical_and_orthogonal(self):
        assert parity.cosine([0.6, 0.8], [0.6, 0.8]) == pytest.approx(1.0)
        assert parity.cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_degenerate_vectors_score_zero(self):
        assert parity.cosine([], []) == 0.0
        assert parity.cosine([0.0, 0.0], [1.0, 0.0]) == 0.0
        assert parity.cosine([1.0], [1.0, 0.0]) == 0.0


class TestCompare:
    def test_identical_vectors_pass(self):
        chunks = [_chunk("a", "A", [1.0, 0.0]), _chunk("b", "B", [0.0, 1.0])]

        result = parity.compare(chunks, lambda texts: [[1.0, 0.0], [0.0, 1.0]], 0.999)

        assert result["passed"] is True
        assert result["chunks"] == 2
        assert result["min_cosine"] == pytest.approx(1.0)
        assert result["below_threshold"] == 0

    def test_a_drifted_vector_fails_and_is_listed_first(self):
        chunks = [_chunk("a", "A", [1.0, 0.0]), _chunk("b", "B", [0.0, 1.0])]

        result = parity.compare(chunks, lambda texts: [[1.0, 0.0], [0.1, 1.0]], 0.999)

        assert result["passed"] is False
        assert result["below_threshold"] == 1
        assert result["worst"][0]["id"] == "b"
        assert result["min_cosine"] < 0.999

    def test_encodes_the_chunk_texts_in_order(self):
        seen: list[list[str]] = []

        def encode(texts: list[str]) -> list[list[float]]:
            seen.append(texts)
            return [[1.0] for _ in texts]

        parity.compare([_chunk("a", "first", [1.0]), _chunk("b", "second", [1.0])], encode, 0.9)

        assert seen == [["first", "second"]]


def _overlap_rerank(query: str, chunks: list[dict], top_k: int) -> list[dict]:
    """A fake cross-encoder: rank by the number of shared words."""
    words = set(query.split())
    ranked = sorted(chunks, key=lambda c: len(words & set(c["text"].split())), reverse=True)
    return ranked[:top_k]


class TestRerankSmoke:
    CHUNKS = [
        _chunk(f"c{i}", f"topic{i} alpha{i} beta{i} gamma{i} delta{i}", [1.0]) for i in range(6)
    ]

    def test_each_chunk_ranks_first_for_its_own_opening(self):
        result = parity.rerank_smoke(self.CHUNKS, _overlap_rerank)

        assert result["passed"] is True
        assert result["candidates"] == parity.RERANK_CANDIDATES
        assert result["hits"] == parity.RERANK_CANDIDATES

    def test_fails_when_the_ranking_ignores_the_query(self):
        def fixed_order(query: str, chunks: list[dict], top_k: int) -> list[dict]:
            return chunks[:top_k]

        result = parity.rerank_smoke(self.CHUNKS, fixed_order)

        assert result["hits"] == 1
        assert result["passed"] is False

    def test_no_chunks_fails(self):
        assert parity.rerank_smoke([], _overlap_rerank)["passed"] is False


class TestCachedRevision:
    def test_reads_refs_main_from_the_hub_cache(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
        refs = tmp_path / "models--BAAI--bge-m3" / "refs"
        refs.mkdir(parents=True)
        (refs / "main").write_text("0123456789abcdef0123456789abcdef01234567\n")

        assert parity.cached_revision("BAAI/bge-m3") == "0123456789abcdef0123456789abcdef01234567"

    def test_uncached_model_has_no_revision(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))

        assert parity.cached_revision("BAAI/bge-m3") is None


def test_library_versions_reports_missing_packages_as_none(monkeypatch):
    monkeypatch.setattr(parity, "LIBRARIES", ("pytest", "no-such-package-akg"))

    versions = parity.library_versions()

    assert versions["pytest"]
    assert versions["no-such-package-akg"] is None


class TestMain:
    @pytest.fixture
    def fake_stack(self, monkeypatch):
        """A retriever over two stored chunks and an embedding model that returns `vectors`."""
        state = SimpleNamespace(vectors=[[1.0, 0.0], [0.0, 1.0]])
        client = MagicMock()
        client.search.return_value = {
            "hits": {
                "hits": [
                    _hit("a", "Alpha opening words", [1.0, 0.0]),
                    _hit("b", "Beta opening words", [0.0, 1.0]),
                ]
            }
        }
        model = SimpleNamespace(
            model_name="BAAI/bge-m3",
            device="cpu",
            encode=lambda texts, normalize: state.vectors,
        )

        def fake_retriever(index_name: str):
            retriever = SimpleNamespace(client=None, embedding_model=model)
            retriever.connect = lambda: setattr(retriever, "client", client)
            return retriever

        monkeypatch.setattr("backend.app.rag.retriever.OpenSearchRetriever", fake_retriever)
        monkeypatch.setenv("HF_HUB_CACHE", "/nonexistent-akg-cache")
        return state

    def test_exit_0_when_vectors_match(self, fake_stack, capsys):
        assert parity.main(["--subject", "us_history", "--json"]) == 0

        report = json.loads(capsys.readouterr().out)
        assert report["passed"] is True
        assert report["subject"] == "us_history"
        assert report["parity"]["chunks"] == 2
        assert report["embedding"]["cached_revision"] is None

    def test_exit_1_when_a_vector_drifted(self, fake_stack, capsys):
        fake_stack.vectors = [[1.0, 0.0], [0.5, 0.5]]

        assert parity.main(["--subject", "us_history"]) == 1
        assert "FAIL" in capsys.readouterr().out

    def test_exit_2_on_an_empty_index(self, fake_stack, monkeypatch, capsys):
        monkeypatch.setattr(parity, "sample_chunks", lambda client, index, size: [])

        assert parity.main(["--subject", "us_history"]) == 2
        assert "make seed" in capsys.readouterr().out

    def test_reranker_smoke_runs_with_the_flag(self, fake_stack, monkeypatch, capsys):
        reranker = SimpleNamespace(device="cpu", load=lambda: None, rerank=_overlap_rerank)
        monkeypatch.setattr("backend.app.rag.reranker.get_reranker", lambda: reranker)

        assert parity.main(["--subject", "us_history", "--reranker", "--json"]) == 0

        report = json.loads(capsys.readouterr().out)
        assert report["reranker"]["hits"] == 2
        assert report["reranker"]["passed"] is True
