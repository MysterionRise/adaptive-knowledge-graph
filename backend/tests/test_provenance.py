"""
Evaluation provenance and determinism on the API side.

- /ask, /ask/stream and /retrieve report a KG-expansion status (ok/empty/failed/disabled)
- /api/v1/retrieve runs retrieval without the LLM
- /api/v1/demo/provenance reports models, an allowlist of settings and data counts, never
  secrets
- the demo status reads the new report schema
- LLM_SEED reaches Ollama; revisions reach the model loaders
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.app.api.routes import demo
from backend.app.core.settings import Settings, settings
from backend.app.rag.kg_expansion import KGExpander

pytestmark = pytest.mark.unit

ASK = "backend.app.api.routes.ask"


def _expander(expanded: list[str], failed_lookups: int = 0) -> MagicMock:
    expander = MagicMock()
    expander.expand_query.return_value = {
        "extracted_concepts": expanded[:1],
        "expanded_concepts": expanded,
        "expanded_query": "q " + " ".join(expanded),
        "failed_lookups": failed_lookups,
    }
    return expander


def _post_ask(client, mock_retriever, mock_llm_client, expander, concepts, **body):
    with (
        patch(f"{ASK}.get_retriever", return_value=mock_retriever),
        patch(f"{ASK}.get_llm_client", return_value=mock_llm_client),
        patch(f"{ASK}.get_kg_expander", return_value=expander),
        patch(f"{ASK}.get_known_concepts", return_value=frozenset(concepts)),
    ):
        return client.post(
            "/api/v1/ask",
            json={"question": "What is photosynthesis?", "use_window_retrieval": False, **body},
        )


class TestKGExpansionStatus:
    def test_ok_when_concepts_are_added(self, client, mock_retriever, mock_llm_client):
        response = _post_ask(
            client, mock_retriever, mock_llm_client, _expander(["A", "B"]), {"A", "B"}
        )
        assert response.status_code == 200
        assert response.json()["kg_expansion_status"] == "ok"
        assert response.json()["expanded_concepts"] == ["A", "B"]

    def test_empty_when_nothing_matches(self, client, mock_retriever, mock_llm_client):
        response = _post_ask(client, mock_retriever, mock_llm_client, _expander([]), {"A"})
        assert response.status_code == 200
        assert response.json()["kg_expansion_status"] == "empty"
        assert response.json()["expanded_concepts"] is None

    def test_failed_when_neo4j_raises(self, client, mock_retriever, mock_llm_client):
        expander = MagicMock()
        expander.expand_query.side_effect = RuntimeError("Neo4j down")
        response = _post_ask(client, mock_retriever, mock_llm_client, expander, {"A"})
        assert response.status_code == 200  # the request still succeeds
        assert response.json()["kg_expansion_status"] == "failed"
        assert response.json()["expanded_concepts"] is None

    def test_failed_when_no_concepts_can_be_loaded(self, client, mock_retriever, mock_llm_client):
        expander = _expander(["A"])
        response = _post_ask(client, mock_retriever, mock_llm_client, expander, set())
        assert response.status_code == 200
        assert response.json()["kg_expansion_status"] == "failed"
        expander.expand_query.assert_not_called()

    def test_failed_when_a_neighbour_lookup_fails(self, client, mock_retriever, mock_llm_client):
        expander = _expander(["A"], failed_lookups=1)
        response = _post_ask(client, mock_retriever, mock_llm_client, expander, {"A"})
        assert response.json()["kg_expansion_status"] == "failed"

    def test_disabled_by_request(self, client, mock_retriever, mock_llm_client):
        response = _post_ask(
            client, mock_retriever, mock_llm_client, _expander(["A"]), {"A"}, use_kg_expansion=False
        )
        assert response.json()["kg_expansion_status"] == "disabled"

    def test_disabled_by_setting(self, client, mock_retriever, mock_llm_client, monkeypatch):
        monkeypatch.setattr(settings, "rag_kg_expansion", False)
        response = _post_ask(client, mock_retriever, mock_llm_client, _expander(["A"]), {"A"})
        assert response.json()["kg_expansion_status"] == "disabled"

    def test_stream_metadata_reports_the_status(self, client, mock_retriever):
        llm = AsyncMock()
        llm.model_name = "test-model"

        async def tokens(*args, **kwargs):
            yield "Answer"

        llm.answer_question_stream = tokens
        expander = MagicMock()
        expander.expand_query.side_effect = RuntimeError("Neo4j down")
        with (
            patch(f"{ASK}.get_retriever", return_value=mock_retriever),
            patch(f"{ASK}.get_llm_client", return_value=llm),
            patch(f"{ASK}.get_kg_expander", return_value=expander),
            patch(f"{ASK}.get_known_concepts", return_value=frozenset({"A"})),
        ):
            response = client.post("/api/v1/ask/stream", json={"question": "What is it?"})
        first = response.text.split("\n\n")[0]
        metadata = json.loads(first.removeprefix("data: "))
        assert metadata["type"] == "metadata"
        assert metadata["kg_expansion_status"] == "failed"


class TestKGExpanderFailedLookups:
    def test_counts_neighbour_lookup_errors(self):
        expander = KGExpander(subject_id="us_history")
        adapter = MagicMock()
        adapter.query_concept_neighbors.side_effect = [
            [{"name": "Tea Act"}],
            RuntimeError("Neo4j down"),
        ]
        expander.neo4j_adapter = adapter
        with patch.object(expander, "extract_concepts_from_query", return_value=["Tax", "Tea"]):
            result = expander.expand_query("Why tea?", {"Tax", "Tea"})
        assert result["failed_lookups"] == 1
        assert set(result["expanded_concepts"]) == {"Tax", "Tea", "Tea Act"}

    def test_no_connection_counts_every_lookup_as_failed(self):
        expander = KGExpander(subject_id="us_history")
        expander.neo4j_adapter = None
        with patch.object(expander, "extract_concepts_from_query", return_value=["Tax"]):
            result = expander.expand_query("Why tax?", {"Tax"})
        assert result["failed_lookups"] == 1


class TestRetrieveEndpoint:
    def test_returns_sources_without_calling_the_llm(self, client, mock_retriever):
        llm_factory = MagicMock()
        with (
            patch(f"{ASK}.get_retriever", return_value=mock_retriever),
            patch(f"{ASK}.get_llm_client", llm_factory),
            patch(f"{ASK}.get_kg_expander", return_value=_expander(["A"])),
            patch(f"{ASK}.get_known_concepts", return_value=frozenset({"A"})),
        ):
            response = client.post(
                "/api/v1/retrieve",
                json={"question": "What is photosynthesis?", "use_window_retrieval": False},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["kg_expansion_status"] == "ok"
        assert data["retrieved_count"] == 3
        assert len(data["sources"]) == 3
        assert "answer" not in data
        llm_factory.assert_not_called()

    def test_no_content_is_404(self, client):
        retriever = MagicMock()
        retriever.retrieve.return_value = []
        with patch(f"{ASK}.get_retriever", return_value=retriever):
            response = client.post(
                "/api/v1/retrieve",
                json={"question": "Anything?", "use_kg_expansion": False},
            )
        assert response.status_code == 404

    def test_markup_is_rejected(self, client):
        response = client.post("/api/v1/retrieve", json={"question": "<script>x</script>?"})
        assert response.status_code == 422

    def test_unknown_subject_is_404(self, client):
        response = client.post(
            "/api/v1/retrieve", json={"question": "What is it?", "subject": "astrology"}
        )
        assert response.status_code == 404

    def test_backend_error_is_a_generic_500(self, client):
        retriever = MagicMock()
        retriever.retrieve.side_effect = RuntimeError("opensearch at 10.0.0.5 refused")
        with patch(f"{ASK}.get_retriever", return_value=retriever):
            response = client.post(
                "/api/v1/retrieve", json={"question": "What is it?", "use_kg_expansion": False}
            )
        assert response.status_code == 500
        assert "10.0.0.5" not in response.text


SECRETS = {
    "api_key": "sentinel-api-key-0123456789",
    "neo4j_password": "sentinel-neo4j-password",
    "opensearch_password": "sentinel-opensearch-password",
    "openrouter_api_key": "sentinel-openrouter-key",
}


class TestProvenanceEndpoint:
    @staticmethod
    def _get(client, adapter=None, opensearch=None):
        """GET /demo/provenance with a mocked Neo4j adapter and OpenSearch `_count`."""
        if adapter is None:
            adapter = MagicMock()
            adapter.get_graph_stats.return_value = {"Concept_count": 42}
        if opensearch is None:

            async def opensearch(url, auth=None):
                return httpx.Response(200, json={"count": 314}, request=httpx.Request("GET", url))

        retriever_factory = MagicMock()
        with (
            patch("backend.app.kg.neo4j_adapter.get_neo4j_adapter", return_value=adapter),
            patch.object(httpx.AsyncClient, "get", AsyncMock(side_effect=opensearch)),
            patch("backend.app.rag.retriever.get_retriever", retriever_factory),
        ):
            response = client.get("/api/v1/demo/provenance")
        retriever_factory.assert_not_called()  # it would load the embedding model
        return response

    def test_reports_models_settings_counts_and_git_sha(self, client, monkeypatch):
        monkeypatch.setattr(settings, "git_sha", "c0ffee" * 6 + "beef")
        monkeypatch.setattr(settings, "embedding_model_revision", "rev-123")
        monkeypatch.setattr(settings, "llm_seed", 42)
        response = self._get(client)
        assert response.status_code == 200
        data = response.json()
        assert data["git_sha"] == "c0ffee" * 6 + "beef"
        assert data["embedding"]["model"] == settings.embedding_model
        assert data["embedding"]["revision"] == "rev-123"
        assert data["embedding"]["device"] == settings.embedding_device
        assert data["reranker"]["model"] == settings.reranker_model
        assert data["reranker"]["enabled"] is settings.reranker_enabled
        assert data["llm"] == {
            "mode": "local",
            "model": settings.llm_local_model,
            "temperature": settings.llm_temperature,
            "seed": 42,
        }
        assert set(data["retrieval"]) == set(demo.PROVENANCE_RETRIEVAL_SETTINGS)
        assert {s["id"] for s in data["subjects"]} >= {"us_history", "economics"}
        assert all(s["concept_count"] == 42 and s["chunk_count"] == 314 for s in data["subjects"])

    def test_allowlist_holds_no_secret_fields(self):
        secretish = ("password", "key", "secret", "token", "user", "host", "uri", "url")
        for name in demo.PROVENANCE_RETRIEVAL_SETTINGS:
            assert hasattr(settings, name), name
            assert not any(word in name for word in secretish), name

    def test_secrets_never_appear_in_the_response(self, client, monkeypatch):
        for name, value in SECRETS.items():
            monkeypatch.setattr(settings, name, value)
        monkeypatch.setattr(settings, "neo4j_uri", "bolt://internal-db.example:7687")
        monkeypatch.setattr(settings, "llm_ollama_host", "http://ollama.internal:11434")
        text = self._get(client).text
        for value in [*SECRETS.values(), "internal-db.example", "ollama.internal"]:
            assert value not in text

    def test_unreadable_stores_give_null_counts(self, client, captured_logs):
        adapter = MagicMock()
        adapter.get_graph_stats.side_effect = RuntimeError("bolt://neo4j:hunter2@db refused")
        opensearch = AsyncMock(side_effect=httpx.ConnectError("http://admin:pw@os refused"))
        response = self._get(client, adapter, opensearch)
        assert response.status_code == 200
        assert "hunter2" not in response.text
        assert "pw@os" not in response.text
        for subject in response.json()["subjects"]:
            assert subject["concept_count"] is None
            assert subject["chunk_count"] is None

    def test_missing_index_counts_zero_chunks(self, client):
        async def missing(url, auth=None):
            return httpx.Response(404, request=httpx.Request("GET", url))

        data = self._get(client, opensearch=missing).json()
        assert all(s["chunk_count"] == 0 for s in data["subjects"])

    def test_counts_each_subject_index(self, client):
        urls: list[str] = []

        async def count(url, auth=None):
            urls.append(url)
            return httpx.Response(200, json={"count": 1}, request=httpx.Request("GET", url))

        self._get(client, opensearch=count)
        assert any(url.endswith("/textbook_chunks_us_history/_count") for url in urls), urls

    def test_resolved_embedding_device_once_loaded(self, client):
        with patch("backend.app.nlp.embeddings.loaded_embedding_device", return_value="cpu"):
            data = self._get(client).json()
        assert data["embedding"]["resolved_device"] == "cpu"


def _write_report(tmp_path: Path, **overrides) -> Path:
    report = {
        "schema_version": 2,
        "generated_at": "2026-10-05T00:00:00+00:00",
        "environment_valid": True,
        "provenance": {
            "server": {"git_sha": "abc123"},
            "golden_set": {"sha256": "f" * 64},
        },
        "run_config": {"retrieval_only": False},
        "summary": {
            "cases": 2,
            "kg_successful_cases": 2,
            "plain_successful_cases": 2,
            "kg_expansion_failures": 0,
            "kg_prompt_injection_resistance_rate": 1.0,
        },
    }
    report.update(overrides)
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


class TestDemoLatestEvalSchema:
    def test_report_with_provenance_is_ok(self, tmp_path):
        status = demo._latest_eval_status(_write_report(tmp_path))
        assert status.status == "ok"
        assert status.has_provenance is True
        assert status.git_sha == "abc123"
        assert status.golden_set_sha256 == "f" * 64
        assert status.kg_expansion_failures == 0
        assert status.prompt_injection_resistance_rate == 1.0

    def test_report_without_provenance_is_an_error(self, tmp_path):
        status = demo._latest_eval_status(_write_report(tmp_path, provenance=None))
        assert status.status == "error"
        assert status.has_provenance is False
        assert "provenance" in (status.message or "")

    def test_invalid_report_is_an_error(self, tmp_path):
        status = demo._latest_eval_status(_write_report(tmp_path, environment_valid=False))
        assert status.status == "error"
        assert "invalid" in (status.message or "")

    def test_retrieval_only_report_is_an_error(self, tmp_path):
        path = _write_report(tmp_path, run_config={"retrieval_only": True})
        status = demo._latest_eval_status(path)
        assert status.status == "error"
        assert "retrieval-only" in (status.message or "")


class TestDeterminismSettings:
    def test_empty_values_mean_unset(self):
        configured = Settings(
            _env_file=None,
            llm_seed="",
            embedding_model_revision=" ",
            reranker_model_revision="",
            git_sha="",
        )
        assert configured.llm_seed is None
        assert configured.embedding_model_revision is None
        assert configured.reranker_model_revision is None
        assert configured.git_sha == "unknown"

    def test_defaults(self):
        defaults = Settings(_env_file=None)
        assert defaults.llm_seed is None
        assert defaults.git_sha == "unknown"
        assert Settings(_env_file=None, llm_seed="7").llm_seed == 7

    @pytest.mark.asyncio
    async def test_seed_is_sent_to_ollama_only_when_set(self):
        from backend.app.nlp.llm_client import LLMClient

        client = LLMClient()
        with patch("backend.app.nlp.llm_client.settings") as mocked:
            mocked.llm_seed = None
            assert "seed" not in client._ollama_payload("p", None, 0.0, 10, False)["options"]
            mocked.llm_seed = 42
            options = client._ollama_payload("p", None, 0.0, 10, False)["options"]
        assert options == {"temperature": 0.0, "num_predict": 10, "seed": 42}

    def test_embedding_revision_is_passed_when_configured(self, monkeypatch):
        from backend.app.nlp.embeddings import EmbeddingModel

        monkeypatch.setattr(settings, "embedding_model_revision", "abc123")
        with (
            patch("sentence_transformers.SentenceTransformer") as model_cls,
            patch("backend.app.nlp.embeddings.resolve_device", return_value="cpu"),
        ):
            EmbeddingModel(model_name="test-model").load()
        model_cls.assert_called_once_with("test-model", device="cpu", revision="abc123")

    def test_reranker_revision_is_passed_when_configured(self, monkeypatch):
        from backend.app.rag.reranker import Reranker

        monkeypatch.setattr(settings, "reranker_model_revision", "def456")
        with (
            patch("sentence_transformers.CrossEncoder") as encoder_cls,
            patch("backend.app.rag.reranker.resolve_device", return_value="cpu"),
        ):
            Reranker().load()
        encoder_cls.assert_called_once_with(
            settings.reranker_model, device="cpu", revision="def456"
        )
