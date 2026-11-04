"""
Request-scoped retrieval trace (#216).

Covers backend/app/rag/trace.py (stages, the allowlist, divergent stages), the
retriever's fusion contributions, the expansion stages and the include_trace flag on
/retrieve (on by default), /ask and /ask/stream (off by default). Tracing must not change
the retrieval, and a serialised trace never holds prompts, chunk bodies, hosts or keys.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.core.settings import settings
from backend.app.core.subjects import get_subject
from backend.app.rag.kg_expansion import KGExpander
from backend.app.rag.trace import (
    NO_TRACE,
    PREVIEW_CHARS,
    RETRIEVAL_STAGES,
    STAGES,
    RetrievalTrace,
    first_divergent_stage,
    sanitize,
    stage_of,
    stage_signature,
)

pytestmark = pytest.mark.unit

ASK = "backend.app.api.routes.ask"
TAIL = "UNIQUE-TAIL-BEYOND-THE-PREVIEW"


def _hit(doc_id: str, section: str, score: float = 1.0, text: str | None = None) -> dict:
    return {
        "_id": doc_id,
        "_score": score,
        "_source": {
            "text": text or f"Text of {doc_id}.",
            "id": doc_id,
            "module_id": "m1",
            "module_title": f"Chapter - {section}",
            "chapter": "Chapter",
            "section": section,
            "key_terms": [],
            "attribution": "OpenStax",
        },
    }


LONG_TEXT = "The Stamp Act taxed printed paper. " * 40 + TAIL
KNN_HITS = [_hit("a", "The Stamp Act", text=LONG_TEXT), _hit("b", "Tea"), _hit("c", "Boston")]
BM25_HITS = [_hit("c", "Boston"), _hit("d", "Townshend"), _hit("a", "The Stamp Act")]


def _retriever(knn: list[dict] = KNN_HITS, bm25: list[dict] = BM25_HITS):
    """A real OpenSearchRetriever whose client answers the kNN and BM25 searches."""
    with patch("backend.app.rag.retriever.get_embedding_model"):
        from backend.app.rag.retriever import OpenSearchRetriever

        retriever = OpenSearchRetriever(index_name="textbook_chunks_us_history")
    retriever.client = MagicMock()
    retriever.client.search.side_effect = lambda index, body: {
        "hits": {"hits": bm25 if "multi_match" in str(body) else knn}
    }
    return retriever


def _adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.query_concept_neighbors.return_value = [
        {
            "name": "Sons of Liberty",
            "weight": 0.68,
            "edges": ["RELATED"],
            "provenance": ["cooccurrence"],
        },
        {"name": "Direct Tax", "weight": 0.0, "edges": ["PREREQ"], "provenance": ["glossary"]},
    ]
    return adapter


def _expander() -> KGExpander:
    expander = KGExpander(extraction_strategy="simple", subject_id="us_history")
    expander.neo4j_adapter = _adapter()
    return expander


@pytest.fixture
def live_pipeline(monkeypatch):
    """/ask's retrieval with a real retriever and expander over fake stores."""
    monkeypatch.setattr(settings, "retrieval_mode", "hybrid")
    monkeypatch.setattr(settings, "rag_kg_expansion", True)
    monkeypatch.setattr(settings, "reranker_enabled", False)
    retriever, expander = _retriever(), _expander()
    with (
        patch(f"{ASK}.get_retriever", return_value=retriever),
        patch(f"{ASK}.get_kg_expander", return_value=expander),
        patch(f"{ASK}.get_known_concepts", return_value=frozenset({"Stamp Act"})),
    ):
        yield retriever


def _retrieve(client, **body):
    return client.post(
        "/api/v1/retrieve",
        json={
            "question": "Why did colonists oppose the Stamp Act?",
            "subject": "us_history",
            "use_window_retrieval": False,
            **body,
        },
    )


class TestRetrievalTrace:
    def test_stages_are_timed_and_kept_in_order(self):
        trace = RetrievalTrace("rid-1")
        with trace.stage("resolve") as stage:
            stage["concepts"] = ["Stamp Act"]
        with trace.stage("knn") as stage:
            stage["hits"] = [{"id": "a", "rank": 1, "score": 0.9}]

        data = trace.to_dict()

        assert data is not None
        assert data["request_id"] == "rid-1"
        assert [stage["name"] for stage in data["stages"]] == ["resolve", "knn"]
        assert all(stage["elapsed_ms"] >= 0 for stage in data["stages"])
        assert data["stages"][0]["concepts"] == ["Stamp Act"]

    def test_a_stage_is_kept_when_it_raises(self):
        trace = RetrievalTrace()
        with pytest.raises(RuntimeError), trace.stage("bm25"):
            raise RuntimeError("search failed")

        assert stage_of(trace.to_dict(), "bm25") == {
            "name": "bm25",
            "elapsed_ms": pytest.approx(0, abs=50),
        }

    def test_unknown_stage_is_an_error(self):
        with (
            pytest.raises(ValueError, match="Unknown retrieval stage"),
            RetrievalTrace().stage("llm"),
        ):
            pass

    def test_no_trace_keeps_nothing(self):
        with NO_TRACE.stage("select") as stage:
            stage["sources"] = [{"id": "a"}]

        assert NO_TRACE.enabled is False
        assert NO_TRACE.to_dict() is None
        assert RetrievalTrace().enabled is True


class TestAllowlist:
    def test_unlisted_stages_and_fields_are_dropped(self):
        data = sanitize(
            {
                "request_id": "rid",
                "host": "opensearch:9200",
                "stages": [
                    {"name": "prompt", "elapsed_ms": 1.0, "text": "You are an expert tutor"},
                    {
                        "name": "bm25",
                        "elapsed_ms": 2.0,
                        "hits": [{"id": "a", "rank": 1, "score": 3.5, "_source": {"text": "x"}}],
                        "query_body": {"multi_match": {}},
                        "host": "localhost",
                    },
                ],
            }
        )

        assert data == {
            "request_id": "rid",
            "stages": [
                {"name": "bm25", "elapsed_ms": 2.0, "hits": [{"id": "a", "rank": 1, "score": 3.5}]}
            ],
        }

    def test_records_keep_their_fields_and_strings_are_cut(self):
        data = sanitize(
            {
                "stages": [
                    {
                        "name": "select",
                        "elapsed_ms": 0.123456789,
                        "sources": [
                            {"id": "a", "rank": 1, "text": LONG_TEXT, "preview": LONG_TEXT}
                        ],
                    },
                    {"name": "resolve", "concepts": ["Stamp Act", {"nested": "map"}]},
                ]
            }
        )

        assert data is not None
        select, resolve = data["stages"]
        assert select["elapsed_ms"] == 0.123457
        assert select["sources"] == [{"id": "a", "rank": 1, "preview": LONG_TEXT[:PREVIEW_CHARS]}]
        assert TAIL not in json.dumps(data)
        assert resolve["concepts"] == ["Stamp Act"]

    def test_nothing_to_sanitize(self):
        assert sanitize(None) is None
        assert sanitize({}) is None


def _trace(**signatures) -> dict:
    """A serialised trace whose stages decide what the keyword arguments say."""
    stages = []
    for name in STAGES:
        stage: dict = {"name": name, "elapsed_ms": 1.0}
        value = signatures.get(name, ["x"])
        if name == "resolve":
            stage["concepts"] = value
        elif name == "expand":
            stage["used"] = value
        elif name in ("knn", "bm25"):
            stage["hits"] = [{"id": doc_id, "rank": i} for i, doc_id in enumerate(value, 1)]
        elif name == "fuse":
            stage["candidates"] = [{"id": doc_id, "rank": i} for i, doc_id in enumerate(value, 1)]
        elif name == "window":
            stage["ran"] = False
        elif name == "rerank":
            stage["ran"] = False
        else:
            stage["sources"] = [{"id": doc_id} for doc_id in value]
        stages.append(stage)
    return {"request_id": None, "stages": stages}


class TestDivergentStage:
    def test_identical_traces_do_not_diverge(self):
        assert first_divergent_stage(_trace(), _trace()) is None

    def test_the_first_differing_stage_is_named(self):
        base = _trace(bm25=["a", "b"], fuse=["a", "b"], select=["a"])
        head = _trace(bm25=["b", "a"], fuse=["b", "a"], select=["b"])

        assert first_divergent_stage(base, head) == "bm25"

    def test_retrieval_stages_skip_the_expansion(self):
        plain = _trace(resolve=[], expand=[], bm25=["a"])
        kg = _trace(resolve=["Stamp Act"], expand=["Stamp Act"], bm25=["b"])

        assert first_divergent_stage(plain, kg) == "resolve"
        assert first_divergent_stage(plain, kg, RETRIEVAL_STAGES) == "bm25"

    def test_a_missing_trace_names_no_stage(self):
        assert first_divergent_stage(None, _trace()) is None
        assert stage_signature(None, "knn") is None


class TestFusionContributions:
    def test_contributions_explain_the_fused_order(self):
        retriever = _retriever()

        merged, candidates = retriever.fuse(KNN_HITS, BM25_HITS, k=60, top_k=3)

        assert merged == retriever._reciprocal_rank_fusion(KNN_HITS, BM25_HITS, k=60, top_k=3)
        assert [c["id"] for c in candidates] == ["a", "c", "b", "d"]  # every candidate
        assert [chunk["id"] for chunk in merged] == ["a", "c", "b"]
        first = candidates[0]
        assert (first["rank"], first["knn_rank"], first["bm25_rank"]) == (1, 1, 3)
        assert first["knn"] == pytest.approx(1 / 61)
        assert first["bm25"] == pytest.approx(1 / 63)
        assert first["score"] == pytest.approx(first["knn"] + first["bm25"])
        assert merged[0]["score"] == first["score"]
        assert first["section"] == "The Stamp Act"
        townshend = candidates[3]
        assert (townshend["knn_rank"], townshend["knn"]) == (None, 0.0)

    def test_hybrid_retrieval_is_the_same_with_and_without_a_trace(self, monkeypatch):
        monkeypatch.setattr(settings, "retrieval_mode", "hybrid")
        trace = RetrievalTrace()

        traced = _retriever().retrieve("q", top_k=3, keyword_query="q Stamp Act", trace=trace)
        untraced = _retriever().retrieve("q", top_k=3, keyword_query="q Stamp Act")

        assert traced == untraced
        data = trace.to_dict()
        assert [stage["name"] for stage in data["stages"]] == ["knn", "bm25", "fuse"]
        assert [hit["id"] for hit in stage_of(data, "bm25")["hits"]] == ["c", "d", "a"]
        assert stage_of(data, "fuse")["k"] == 60

    def test_knn_mode_records_the_knn_stage(self, monkeypatch):
        monkeypatch.setattr(settings, "retrieval_mode", "knn")
        trace = RetrievalTrace()

        _retriever().retrieve("q", top_k=3, trace=trace)

        assert [stage["name"] for stage in trace.to_dict()["stages"]] == ["knn"]


class TestExpansionStages:
    def test_resolve_and_expand_record_what_produced_each_neighbour(self):
        trace = RetrievalTrace()
        question = "Why did colonists oppose the Stamp Act?"

        traced = _expander().expand_query(question, {"Stamp Act"}, trace=trace)
        untraced = _expander().expand_query(question, {"Stamp Act"})

        assert traced == untraced
        data = trace.to_dict()
        assert stage_of(data, "resolve")["concepts"] == ["Stamp Act"]
        assert stage_of(data, "resolve")["terms"][0]["canonical"] == "Stamp Act"
        expand = stage_of(data, "expand")
        assert expand["used"] == ["Stamp Act"]
        assert expand["related"] == ["Sons of Liberty", "Direct Tax"]
        assert expand["neighbours"][0] == {
            "concept": "Sons of Liberty",
            "edges": ["RELATED"],
            "provenance": ["cooccurrence"],
            "source": "Stamp Act",
            "weight": 0.68,
        }
        assert expand["failed_lookups"] == 0


class TestEndpoints:
    def test_retrieve_returns_every_stage_keyed_by_the_request_id(self, client, live_pipeline):
        response = _retrieve(client, use_kg_expansion=True)

        assert response.status_code == 200
        trace = response.json()["trace"]
        assert [stage["name"] for stage in trace["stages"]] == list(STAGES)
        assert trace["request_id"] == response.headers["X-Request-ID"]
        assert stage_of(trace, "window") == {
            "name": "window",
            "elapsed_ms": pytest.approx(0, abs=50),
            "ran": False,
        }
        sources = stage_of(trace, "select")["sources"]
        assert [source["id"] for source in sources] == ["a", "c", "b", "d"]

    def test_plain_retrieval_has_no_expansion_stages(self, client, live_pipeline):
        trace = _retrieve(client, use_kg_expansion=False).json()["trace"]

        assert [stage["name"] for stage in trace["stages"]] == list(RETRIEVAL_STAGES)

    def test_tracing_does_not_change_the_retrieval(self, client, live_pipeline):
        traced = _retrieve(client, include_trace=True).json()
        untraced = _retrieve(client, include_trace=False).json()

        assert untraced["trace"] is None
        assert traced.pop("trace") is not None
        untraced.pop("trace")
        assert json.dumps(traced, sort_keys=True) == json.dumps(untraced, sort_keys=True)

    def test_the_trace_holds_no_prompt_body_host_or_key(self, client, live_pipeline):
        serialised = json.dumps(_retrieve(client).json()["trace"])

        assert TAIL not in serialised  # the chunk body beyond the preview
        assert get_subject("us_history").prompts.system_prompt[:40] not in serialised
        for secret in (settings.opensearch_host, settings.neo4j_uri, settings.neo4j_password):
            assert secret not in serialised
        assert "localhost" not in serialised and "9200" not in serialised

    def test_ask_has_no_trace_unless_asked(self, client, live_pipeline, mock_llm_client):
        with patch(f"{ASK}.get_llm_client", return_value=mock_llm_client):
            default = client.post(
                "/api/v1/ask", json={"question": "What was the Stamp Act?", "subject": "us_history"}
            )
            asked = client.post(
                "/api/v1/ask",
                json={
                    "question": "What was the Stamp Act?",
                    "subject": "us_history",
                    "include_trace": True,
                },
            )

        assert default.json()["trace"] is None
        assert [stage["name"] for stage in asked.json()["trace"]["stages"]] == list(STAGES)
        assert default.json()["sources"] == asked.json()["sources"]

    def test_stream_metadata_carries_the_trace_only_when_asked(self, client, live_pipeline):
        llm = AsyncMock()
        llm.model_name = "test-model"

        async def tokens(*args, **kwargs):
            yield "An answer."

        llm.answer_question_stream = tokens

        def metadata(**body) -> dict:
            with patch(f"{ASK}.get_llm_client", return_value=llm):
                response = client.post(
                    "/api/v1/ask/stream",
                    json={"question": "What was the Stamp Act?", "subject": "us_history", **body},
                )
            first = next(line for line in response.text.splitlines() if line.startswith("data: "))
            return json.loads(first[len("data: ") :])

        assert "trace" not in metadata()
        assert metadata(include_trace=True)["trace"]["stages"][-1]["name"] == "select"
