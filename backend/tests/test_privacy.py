"""
Tests for PRIVACY_LOCAL_ONLY enforcement beyond the LLM mode (#159).

Covers:
- The settings validator: LangSmith tracing, remote Ollama hosts and Ollama cloud models
- Hugging Face Hub telemetry and offline mode
- The autouse network guard itself
- End to end, with the LangSmith tracing variables set: startup, /api/v1/ask and
  /api/v1/graph/query through the real GraphCypherQAChain make no non-loopback connection
"""

import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.core import privacy
from backend.app.core.privacy import (
    TRACING_ENV_VARS,
    configure_huggingface_hub,
    hf_model_is_cached,
    is_cloud_model,
    ollama_host_problem,
)
from backend.app.core.settings import (
    PINNED_MODEL_REVISIONS,
    PRIVACY_LLM_MODE_ERROR,
    Settings,
)
from backend.app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]

# What a .env copied from a LangSmith quickstart contains.
LANGSMITH_ENV = {
    "LANGSMITH_TRACING": "true",
    "LANGCHAIN_TRACING_V2": "true",
    "LANGSMITH_API_KEY": "lsv2_pt_test_key_not_real",
    "LANGCHAIN_API_KEY": "lsv2_pt_test_key_not_real",
    "LANGSMITH_ENDPOINT": "https://api.smith.langchain.com",
    "LANGSMITH_PROJECT": "akg-privacy-test",
}


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


@pytest.fixture
def clean_tracing_env(monkeypatch):
    """No tracing variable from the developer's shell leaks into these tests."""
    for name in (*TRACING_ENV_VARS, *LANGSMITH_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def langsmith_unconfigured():
    """langsmith as a fresh process sees it: tracing decided by the environment alone.

    Importing the app already ran ``langsmith.configure(enabled=False)``; this undoes it for
    the test (and the env-var cache) and restores everything afterwards.
    """
    import langsmith._internal._context as ls_context
    from langsmith import utils as ls_utils

    previous = ls_context._GLOBAL_TRACING_ENABLED
    token = ls_context._TRACING_ENABLED.set(None)
    ls_context._GLOBAL_TRACING_ENABLED = None
    ls_utils.get_env_var.cache_clear()
    yield
    ls_context._TRACING_ENABLED.reset(token)
    ls_context._GLOBAL_TRACING_ENABLED = previous
    ls_utils.get_env_var.cache_clear()


# ==========================================================================
# Settings validator
# ==========================================================================


@pytest.mark.unit
class TestTracingRefused:
    @pytest.mark.parametrize("name", TRACING_ENV_VARS)
    @pytest.mark.parametrize("value", ["true", "True", "1", "local"])
    def test_tracing_variable_refused(self, monkeypatch, clean_tracing_env, name, value):
        monkeypatch.setenv(name, value)

        with pytest.raises(ValidationError, match=re.escape(name)) as excinfo:
            Settings(_env_file=None)

        message = str(excinfo.value)
        assert "refuses LangSmith tracing" in message
        assert "PRIVACY_LOCAL_ONLY=false" in message

    @pytest.mark.parametrize("value", ["", "false", "False", "0", "no", "off"])
    def test_tracing_off_values_start(self, monkeypatch, clean_tracing_env, value):
        for name in TRACING_ENV_VARS:
            monkeypatch.setenv(name, value)

        Settings(_env_file=None)

    def test_key_and_endpoint_alone_start(self, monkeypatch, clean_tracing_env):
        """API key, endpoint and project send nothing unless a tracing switch is on."""
        for name in ("LANGSMITH_API_KEY", "LANGSMITH_ENDPOINT", "LANGSMITH_PROJECT"):
            monkeypatch.setenv(name, LANGSMITH_ENV[name])

        Settings(_env_file=None)

    def test_tracing_in_env_file_refused(self, tmp_path, clean_tracing_env):
        """Compose passes .env into the container; a local run reads it through settings."""
        env_file = tmp_path / ".env"
        env_file.write_text("LANGCHAIN_TRACING_V2=true\n")

        with pytest.raises(ValidationError, match="LANGCHAIN_TRACING_V2"):
            Settings(_env_file=env_file)

    def test_all_offending_variables_named(self, monkeypatch, clean_tracing_env):
        monkeypatch.setenv("LANGSMITH_TRACING", "true")
        monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")

        with pytest.raises(ValidationError, match="LANGSMITH_TRACING, LANGCHAIN_TRACING_V2"):
            Settings(_env_file=None)

    def test_tracing_allowed_without_privacy(self, monkeypatch, clean_tracing_env):
        monkeypatch.setenv("LANGSMITH_TRACING", "true")

        assert Settings(_env_file=None, privacy_local_only=False).langsmith_tracing == "true"


@pytest.mark.unit
class TestOllamaHost:
    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:11434",
            "http://LOCALHOST:11434",
            "http://ollama.localhost:11434",
            "http://ollama:11434",
            "http://host.docker.internal:11434",
            "http://host.containers.internal:11434",
            "http://127.0.0.1:11434",
            "http://127.0.0.2:11434",
            "http://[::1]:11434",
            "http://10.1.2.3:11434",
            "http://172.16.0.10:11434",
            "http://192.168.1.20:11434",
            "http://[fd00::1]:11434",
            "http://[::ffff:192.168.1.20]:11434",
            "localhost:11434",
        ],
    )
    def test_local_hosts_allowed_without_dns(self, url):
        with patch.object(privacy.socket, "getaddrinfo") as getaddrinfo:
            assert ollama_host_problem(url) is None
            _settings(llm_ollama_host=url)
        getaddrinfo.assert_not_called()

    @pytest.mark.parametrize(
        "url",
        [
            "http://8.8.8.8:11434",
            "https://1.1.1.1",
            "http://[2001:4860:4860::8888]:11434",
            "http://169.254.169.254",  # link-local (cloud metadata), not a private LAN
            "http://100.64.0.1:11434",  # carrier-grade NAT / tailnets: not private
        ],
    )
    def test_public_ip_literals_refused(self, url):
        with pytest.raises(ValidationError) as excinfo:
            _settings(llm_ollama_host=url)

        message = str(excinfo.value)
        assert "requires a local Ollama" in message
        assert "is not a loopback or private address" in message
        assert "LLM_OLLAMA_HOST" in message

    def _addrinfo(self, *addresses):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 0)) for a in addresses]

    def test_hostname_resolving_to_private_addresses_allowed(self):
        with patch.object(
            privacy.socket, "getaddrinfo", return_value=self._addrinfo("192.168.1.5", "10.0.0.5")
        ) as getaddrinfo:
            _settings(llm_ollama_host="http://gpu-box.lan:11434")
        getaddrinfo.assert_called_once_with("gpu-box.lan", None)

    def test_hostname_resolving_to_any_public_address_refused(self):
        with (
            patch.object(
                privacy.socket,
                "getaddrinfo",
                return_value=self._addrinfo("192.168.1.5", "93.184.215.14"),
            ),
            pytest.raises(ValidationError, match="resolves to non-private addresses"),
        ):
            _settings(llm_ollama_host="https://ollama.example.com")

    def test_unresolvable_hostname_refused(self):
        with (
            patch.object(privacy.socket, "getaddrinfo", side_effect=socket.gaierror("nope")),
            pytest.raises(ValidationError, match="could not be resolved"),
        ):
            _settings(llm_ollama_host="http://no-such-host.invalid:11434")

    def test_missing_host_refused(self):
        with pytest.raises(ValidationError, match="has no host name"):
            _settings(llm_ollama_host="http://:11434")

    def test_remote_host_allowed_without_privacy(self):
        _settings(privacy_local_only=False, llm_ollama_host="https://8.8.8.8")


@pytest.mark.unit
class TestCloudModels:
    @pytest.mark.parametrize(
        "model", ["gpt-oss:120b-cloud", "deepseek-v3.1:671b-CLOUD", "glm-4.6:cloud"]
    )
    def test_cloud_models_refused(self, model):
        assert is_cloud_model(model)
        with pytest.raises(ValidationError) as excinfo:
            _settings(llm_local_model=model)

        message = str(excinfo.value)
        assert "refuses Ollama cloud models" in message
        assert f"LLM_LOCAL_MODEL={model!r}" in message

    @pytest.mark.parametrize(
        "model", ["llama3.1:8b-instruct-q4_K_M", "qwen2.5:7b", "soundcloud-bot:latest", "mistral"]
    )
    def test_local_models_allowed(self, model):
        assert not is_cloud_model(model)
        _settings(llm_local_model=model)

    def test_cloud_model_allowed_without_privacy(self):
        _settings(privacy_local_only=False, llm_local_model="gpt-oss:120b-cloud")


@pytest.mark.unit
def test_every_problem_reported_at_once(monkeypatch, clean_tracing_env):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")

    with pytest.raises(ValidationError) as excinfo:
        _settings(llm_mode="hybrid", llm_ollama_host="http://8.8.8.8", llm_local_model="x:cloud")

    message = str(excinfo.value)
    for fragment in (
        PRIVACY_LLM_MODE_ERROR,
        "LANGSMITH_TRACING",
        "LLM_OLLAMA_HOST",
        "LLM_LOCAL_MODEL",
    ):
        assert fragment in message


# ==========================================================================
# Hugging Face Hub
# ==========================================================================


def _cache_model(hub: Path, model: str, commit: str | None = None, ref: str = "main") -> None:
    """Cache a snapshot the way huggingface_hub does: the commit (by default the model's
    pinned one) under snapshots/, and refs/<ref> pointing at it."""
    commit = commit or PINNED_MODEL_REVISIONS.get(model, "abc123")
    repo = hub / f"models--{model.replace('/', '--')}"
    snapshot = repo / "snapshots" / commit
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}")
    (repo / "refs").mkdir(exist_ok=True)
    (repo / "refs" / ref).write_text(commit)


@pytest.fixture
def hf_env(tmp_path, monkeypatch):
    """An empty Hugging Face cache under tmp_path; os.environ is restored afterwards."""
    with patch.dict(os.environ):
        for name in ("HF_HUB_OFFLINE", "HF_HUB_CACHE", "HF_HUB_DISABLE_TELEMETRY"):
            os.environ.pop(name, None)
        os.environ["HF_HOME"] = str(tmp_path / "hf")
        yield tmp_path / "hf" / "hub"


@pytest.mark.unit
class TestHuggingFaceHub:
    def test_telemetry_off_after_settings_import(self):
        assert os.environ.get("HF_HUB_DISABLE_TELEMETRY") == "1"

    def test_first_run_stays_online(self, hf_env):
        status = configure_huggingface_hub(_settings())

        assert os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"
        assert "HF_HUB_OFFLINE" not in os.environ
        assert "BAAI/bge-m3 not cached yet" in status

    def test_offline_once_models_cached(self, hf_env):
        _cache_model(hf_env, "BAAI/bge-m3")

        status = configure_huggingface_hub(_settings())

        assert os.environ["HF_HUB_OFFLINE"] == "1"
        assert status.startswith("offline")

    def test_enabled_reranker_must_be_cached_too(self, hf_env):
        _cache_model(hf_env, "BAAI/bge-m3")

        status = configure_huggingface_hub(_settings(reranker_enabled=True))
        assert "HF_HUB_OFFLINE" not in os.environ
        assert "BAAI/bge-reranker-v2-m3" in status

        _cache_model(hf_env, "BAAI/bge-reranker-v2-m3")
        configure_huggingface_hub(_settings(reranker_enabled=True))
        assert os.environ["HF_HUB_OFFLINE"] == "1"

    def test_explicit_setting_respected(self, hf_env):
        _cache_model(hf_env, "BAAI/bge-m3")
        os.environ["HF_HUB_OFFLINE"] = "0"

        assert "set explicitly" in configure_huggingface_hub(_settings())
        assert os.environ["HF_HUB_OFFLINE"] == "0"

    def test_online_without_privacy(self, hf_env):
        _cache_model(hf_env, "BAAI/bge-m3")

        configure_huggingface_hub(_settings(privacy_local_only=False))

        assert "HF_HUB_OFFLINE" not in os.environ
        assert os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"

    def test_cache_dir_resolution(self, hf_env, tmp_path):
        assert privacy.hf_hub_cache_dir() == hf_env
        os.environ["HF_HUB_CACHE"] = str(tmp_path / "custom")
        assert privacy.hf_hub_cache_dir() == tmp_path / "custom"
        del os.environ["HF_HUB_CACHE"], os.environ["HF_HOME"]
        os.environ["XDG_CACHE_HOME"] = str(tmp_path / "xdg")
        assert privacy.hf_hub_cache_dir() == tmp_path / "xdg" / "huggingface" / "hub"

    def test_empty_snapshot_is_not_cached(self, hf_env):
        (hf_env / "models--BAAI--bge-m3" / "snapshots" / "abc123").mkdir(parents=True)

        assert not hf_model_is_cached("BAAI/bge-m3")

    def test_local_model_directory_counts_as_cached(self, hf_env, tmp_path):
        assert hf_model_is_cached(str(tmp_path))

    def test_another_commit_does_not_count_for_the_pinned_one(self, hf_env):
        _cache_model(hf_env, "BAAI/bge-m3", commit="0" * 40)

        status = configure_huggingface_hub(_settings())

        assert hf_model_is_cached("BAAI/bge-m3")
        assert not hf_model_is_cached("BAAI/bge-m3", PINNED_MODEL_REVISIONS["BAAI/bge-m3"])
        assert "HF_HUB_OFFLINE" not in os.environ
        assert "BAAI/bge-m3 not cached yet" in status

    def test_branch_revision_resolves_through_refs(self, hf_env):
        _cache_model(hf_env, "BAAI/bge-m3", commit="1" * 40, ref="main")

        assert hf_model_is_cached("BAAI/bge-m3", "main")
        assert hf_model_is_cached("BAAI/bge-m3", "1" * 40)
        assert not hf_model_is_cached("BAAI/bge-m3", "v2.0")

        configure_huggingface_hub(_settings(embedding_model_revision="main"))
        assert os.environ["HF_HUB_OFFLINE"] == "1"

    def test_api_import_sets_env_before_huggingface_hub_loads(self, tmp_path):
        """Importing the API must not import huggingface_hub: it reads the variables once."""
        code = (
            "import os, sys\n"
            "import backend.app.main\n"
            "assert 'huggingface_hub' not in sys.modules, 'huggingface_hub imported too early'\n"
            "assert os.environ['HF_HUB_DISABLE_TELEMETRY'] == '1'\n"
            "print(os.environ.get('HF_HUB_OFFLINE', 'unset'))\n"
        )
        hub = tmp_path / "hub"
        _cache_model(hub, "BAAI/bge-m3")
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("HF_", "LANGSMITH_", "LANGCHAIN_"))
        }
        env.update(HF_HUB_CACHE=str(hub), RERANKER_ENABLED="false", PRIVACY_LOCAL_ONLY="true")

        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=tmp_path,  # no repository .env
            env={**env, "PYTHONPATH": str(REPO_ROOT)},
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().splitlines()[-1] == "1"


# ==========================================================================
# The network guard (conftest.py)
# ==========================================================================


@pytest.mark.unit
class TestNetworkGuard:
    def test_non_loopback_connect_blocked_and_recorded(self, network_guard):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(OSError, match="tried to connect"):
                sock.connect(("192.0.2.1", 443))
            with pytest.raises(OSError, match="tried to connect"):
                sock.connect_ex(("example.com", 80))
        finally:
            sock.close()
        assert network_guard == ["connect ('192.0.2.1', 443)", "connect ('example.com', 80)"]
        network_guard.clear()

    def test_dns_lookup_blocked_and_recorded(self, network_guard):
        with pytest.raises(OSError, match="tried to resolve"):
            socket.getaddrinfo("api.smith.langchain.com", 443)
        assert network_guard == ["getaddrinfo 'api.smith.langchain.com'"]
        network_guard.clear()

    def test_loopback_allowed(self, network_guard):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        client = socket.create_connection(server.getsockname(), timeout=5)
        client.close()
        server.close()
        assert socket.getaddrinfo("localhost", 80)
        assert network_guard == []


# ==========================================================================
# End to end with the LangSmith tracing variables set
# ==========================================================================


def _ask(client: TestClient, mocks) -> None:
    retriever, llm_client, kg_expander = mocks
    with (
        patch("backend.app.api.routes.ask.get_retriever", return_value=retriever),
        patch("backend.app.api.routes.ask.get_llm_client", return_value=llm_client),
        patch("backend.app.api.routes.ask.get_kg_expander", return_value=kg_expander),
        patch(
            "backend.app.api.routes.ask.get_known_concepts",
            return_value=frozenset({"photosynthesis"}),
        ),
    ):
        response = client.post(
            "/api/v1/ask",
            json={"question": "What is photosynthesis?", "use_window_retrieval": False},
        )
    assert response.status_code == 200, response.text


def _graph_query(client: TestClient, service) -> None:
    with patch("backend.app.kg.cypher_qa.get_cypher_qa_service", return_value=service):
        response = client.post(
            "/api/v1/graph/query",
            json={"question": "Which concepts exist?", "preview_only": False},
        )
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "Photosynthesis is a concept."


def _flush_tracers() -> None:
    from langchain_core.tracers.langchain import wait_for_all_tracers

    wait_for_all_tracers()


@pytest.mark.unit
class TestNoRemoteTrafficWithTracingVariables:
    """#159 acceptance: tracing variables set, no non-loopback connection anywhere."""

    QUERY = "MATCH (c:Concept) RETURN c.name AS name LIMIT 5"

    def test_startup_refused(self, monkeypatch, clean_tracing_env, network_guard):
        for name, value in LANGSMITH_ENV.items():
            monkeypatch.setenv(name, value)

        with pytest.raises(ValidationError, match="refuses LangSmith tracing"):
            create_app(Settings(_env_file=None))

        assert network_guard == []

    def test_api_process_refuses_to_import(self, tmp_path):
        """``uvicorn backend.app.main:app`` fails at import with the startup error."""
        env = {
            k: v for k, v in os.environ.items() if not k.startswith(("LANGSMITH_", "LANGCHAIN_"))
        }
        env.update(LANGSMITH_ENV, PRIVACY_LOCAL_ONLY="true", PYTHONPATH=str(REPO_ROOT))

        result = subprocess.run(
            [sys.executable, "-c", "import backend.app.main"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode != 0
        assert "refuses LangSmith tracing" in result.stderr
        assert "LANGSMITH_TRACING, LANGCHAIN_TRACING_V2" in result.stderr

    def test_ask_and_real_cypher_chain_stay_local(
        self,
        monkeypatch,
        clean_tracing_env,
        langsmith_unconfigured,
        network_guard,
        mock_retriever,
        mock_llm_client,
        mock_kg_expander,
        make_cypher_qa_service,
    ):
        """Defence in depth: tracing switched on after the settings were validated.

        The app disables LangSmith tracing globally, so neither the API nor the real
        GraphCypherQAChain (which would otherwise post runs to LangSmith) leaves loopback.
        """
        app_settings = Settings(_env_file=None)  # validated before the variables appear
        for name, value in LANGSMITH_ENV.items():
            monkeypatch.setenv(name, value)

        from langsmith import utils as ls_utils

        assert ls_utils.tracing_is_enabled() is True  # the variables are live

        app = create_app(app_settings)
        assert ls_utils.tracing_is_enabled() is False

        service, driver = make_cypher_qa_service(
            self.QUERY, "Photosynthesis is a concept.", records=[{"name": "Photosynthesis"}]
        )
        with TestClient(app) as client:  # runs the lifespan (startup and shutdown)
            _ask(client, (mock_retriever, mock_llm_client, mock_kg_expander))
            _graph_query(client, service)
        _flush_tracers()

        driver.mock_tx.run.assert_called_once_with(self.QUERY, {})
        assert network_guard == []

    def test_control_without_the_guard_the_chain_would_reach_langsmith(
        self,
        monkeypatch,
        clean_tracing_env,
        langsmith_unconfigured,
        network_guard,
        make_cypher_qa_service,
    ):
        """Proves the test above can fail: without the global switch the chain traces."""
        for name, value in LANGSMITH_ENV.items():
            monkeypatch.setenv(name, value)
        service, _ = make_cypher_qa_service(
            self.QUERY, "Photosynthesis is a concept.", records=[{"name": "Photosynthesis"}]
        )

        service.query("Which concepts exist?")
        _flush_tracers()

        assert network_guard, "expected the LangSmith tracer to attempt a remote connection"
        network_guard.clear()
