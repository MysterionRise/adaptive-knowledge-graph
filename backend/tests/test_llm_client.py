"""
Tests for the LLM client module.

Tests cover:
- Initialization with default settings and custom overrides
- Mode-based dispatch routing (local, remote, hybrid)
- Ollama generate: success, error status, connection error
- OpenRouter generate: success, error status, missing API key
- Hybrid fallback: local failure cascading to remote
- Ollama streaming: NDJSON token yielding, done flag, connection error
- OpenRouter streaming: SSE token yielding, [DONE] sentinel, missing API key
- answer_question: prompt construction, generate call, return structure
- _build_answer_prompts: default/custom system prompt, context formatting, attribution
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from backend.app.core.exceptions import LLMConnectionError, LLMGenerationError
from backend.app.nlp.llm_client import LLMClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(mode="local", model_name="test-model", api_key="test-key"):
    """Create an LLMClient with patched settings to avoid env leakage."""
    with patch("backend.app.nlp.llm_client.settings") as mock_settings:
        mock_settings.llm_mode = mode
        mock_settings.llm_local_model = model_name
        mock_settings.llm_ollama_host = "http://localhost:11434"
        mock_settings.openrouter_api_key = api_key
        mock_settings.openrouter_base_url = "https://openrouter.ai/api/v1"
        mock_settings.openrouter_model = "mistralai/mixtral-8x7b-instruct"
        mock_settings.openrouter_verify_ssl = True
        mock_settings.llm_temperature = 0.1
        mock_settings.llm_timeout = 60
        mock_settings.llm_stream_timeout = 120
        mock_settings.llm_retry_attempts = 1  # fast tests, no real retries
        mock_settings.llm_retry_min_wait = 0
        mock_settings.llm_retry_max_wait = 0

        client = LLMClient(mode=mode, model_name=model_name)
    return client


def _mock_aiohttp_response(status=200, json_data=None, text_data="", content_lines=None):
    """
    Build a mock aiohttp response object.

    Args:
        status: HTTP status code.
        json_data: Data returned by response.json().
        text_data: Data returned by response.text().
        content_lines: List of bytes lines for streaming (async iterator).
    """
    mock_response = AsyncMock()
    mock_response.status = status
    mock_response.json = AsyncMock(return_value=json_data or {})
    mock_response.text = AsyncMock(return_value=text_data)
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    if content_lines is not None:

        class _AsyncLineIterator:
            def __init__(self, lines):
                self._lines = iter(lines)

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self._lines)
                except StopIteration as err:
                    raise StopAsyncIteration from err

        mock_response.content = _AsyncLineIterator(content_lines)

    return mock_response


def _mock_aiohttp_session(mock_response):
    """Build a mock aiohttp.ClientSession wrapping a response."""
    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


# ===========================================================================
# 1. Initialization
# ===========================================================================


@pytest.mark.unit
class TestLLMClientInit:
    """Tests for LLMClient.__init__ defaults and overrides."""

    def test_defaults_from_settings(self):
        """Init without arguments should pull from settings."""
        with patch("backend.app.nlp.llm_client.settings") as mock_settings:
            mock_settings.llm_mode = "local"
            mock_settings.llm_local_model = "llama3.1:8b"
            mock_settings.llm_ollama_host = "http://localhost:11434"
            mock_settings.openrouter_api_key = ""
            mock_settings.openrouter_base_url = "https://openrouter.ai/api/v1"

            client = LLMClient()

        assert client.mode == "local"
        assert client.model_name == "llama3.1:8b"
        assert client.ollama_host == "http://localhost:11434"

    def test_custom_mode_and_model(self):
        """Custom mode and model_name should override settings."""
        client = _make_client(mode="remote", model_name="my-custom-model")
        assert client.mode == "remote"
        assert client.model_name == "my-custom-model"

    def test_hybrid_mode(self):
        """Hybrid mode should be accepted."""
        client = _make_client(mode="hybrid")
        assert client.mode == "hybrid"


# ===========================================================================
# 2. generate() dispatch
# ===========================================================================


@pytest.mark.unit
class TestGenerateDispatch:
    """Tests that generate() routes to the correct backend."""

    @pytest.mark.asyncio
    async def test_local_mode_calls_ollama(self):
        """Local mode should dispatch to _generate_ollama."""
        client = _make_client(mode="local")
        with patch.object(client, "_generate_ollama", new_callable=AsyncMock) as mock_ollama:
            mock_ollama.return_value = "local answer"
            result = await client.generate("test prompt")

        assert result == "local answer"
        mock_ollama.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_remote_mode_calls_openrouter(self):
        """Remote mode should dispatch to _generate_openrouter."""
        client = _make_client(mode="remote")
        with patch.object(
            client, "_generate_openrouter", new_callable=AsyncMock
        ) as mock_openrouter:
            mock_openrouter.return_value = "remote answer"
            result = await client.generate("test prompt")

        assert result == "remote answer"
        mock_openrouter.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_hybrid_mode_tries_local_first(self):
        """Hybrid mode should try local first."""
        client = _make_client(mode="hybrid")
        with patch.object(client, "_generate_ollama", new_callable=AsyncMock) as mock_ollama:
            mock_ollama.return_value = "local answer"
            result = await client.generate("test prompt")

        assert result == "local answer"
        mock_ollama.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_passes_temperature(self):
        """Custom temperature should be forwarded to the backend."""
        client = _make_client(mode="local")
        with patch.object(client, "_generate_ollama", new_callable=AsyncMock) as mock_ollama:
            mock_ollama.return_value = "answer"
            await client.generate("prompt", temperature=0.7)

        call_args = mock_ollama.call_args
        assert call_args[0][2] == 0.7  # third positional arg is temperature


# ===========================================================================
# 3. _generate_ollama
# ===========================================================================


@pytest.mark.unit
class TestGenerateOllama:
    """Tests for Ollama generate endpoint."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Successful Ollama response should return the 'response' field."""
        client = _make_client(mode="local")
        mock_response = _mock_aiohttp_response(
            status=200, json_data={"response": "Ollama says hello"}
        )
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await client._generate_ollama("test prompt", "system", 0.1)

        assert result == "Ollama says hello"

    @pytest.mark.asyncio
    async def test_empty_response_field(self):
        """Missing 'response' key should return empty string."""
        client = _make_client(mode="local")
        mock_response = _mock_aiohttp_response(status=200, json_data={})
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await client._generate_ollama("test prompt", None, 0.1)

        assert result == ""

    @pytest.mark.asyncio
    async def test_error_status_raises_generation_error(self):
        """Non-200 status should raise LLMGenerationError."""
        client = _make_client(mode="local")
        mock_response = _mock_aiohttp_response(status=500, text_data="Internal Server Error")
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(LLMGenerationError, match="Ollama API error"):
                await client._generate_ollama("test prompt", None, 0.1)

    @pytest.mark.asyncio
    async def test_connection_error_raises_llm_connection_error(self):
        """aiohttp.ClientError should be wrapped in LLMConnectionError."""
        client = _make_client(mode="local")

        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=aiohttp.ClientError("Connection refused"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(LLMConnectionError, match="Ollama connection failed"):
                await client._generate_ollama("test prompt", None, 0.1)

    @pytest.mark.asyncio
    async def test_system_prompt_included_in_payload(self):
        """System prompt should be forwarded in the POST payload."""
        client = _make_client(mode="local")
        mock_response = _mock_aiohttp_response(
            status=200, json_data={"response": "ok"}
        )
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await client._generate_ollama("my prompt", "be helpful", 0.5)

        # Inspect the json payload passed to session.post
        post_call = mock_session.post
        post_call.assert_called_once()
        call_kwargs = post_call.call_args
        payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        assert payload["system"] == "be helpful"
        assert payload["prompt"] == "my prompt"
        assert payload["temperature"] == 0.5
        assert payload["stream"] is False


# ===========================================================================
# 4. _generate_openrouter
# ===========================================================================


@pytest.mark.unit
class TestGenerateOpenRouter:
    """Tests for OpenRouter generate endpoint."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Successful OpenRouter response should extract message content."""
        client = _make_client(mode="remote", api_key="sk-test-123")
        json_data = {
            "choices": [
                {"message": {"content": "OpenRouter says hello"}}
            ]
        }
        mock_response = _mock_aiohttp_response(status=200, json_data=json_data)
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await client._generate_openrouter("prompt", "system", 0.1, 1024)

        assert result == "OpenRouter says hello"

    @pytest.mark.asyncio
    async def test_error_status_raises_generation_error(self):
        """Non-200 status should raise LLMGenerationError."""
        client = _make_client(mode="remote", api_key="sk-test-123")
        mock_response = _mock_aiohttp_response(status=429, text_data="Rate limit exceeded")
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(LLMGenerationError, match="OpenRouter API error"):
                await client._generate_openrouter("prompt", None, 0.1, 1024)

    @pytest.mark.asyncio
    async def test_missing_api_key_raises_generation_error(self):
        """Empty API key should raise LLMGenerationError immediately."""
        client = _make_client(mode="remote", api_key="")
        with pytest.raises(LLMGenerationError, match="API key not configured"):
            await client._generate_openrouter("prompt", None, 0.1, 1024)

    @pytest.mark.asyncio
    async def test_connection_error_raises_llm_connection_error(self):
        """aiohttp.ClientError should be wrapped in LLMConnectionError."""
        client = _make_client(mode="remote", api_key="sk-test-123")

        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=aiohttp.ClientError("timeout"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(LLMConnectionError, match="OpenRouter connection failed"):
                await client._generate_openrouter("prompt", None, 0.1, 1024)

    @pytest.mark.asyncio
    async def test_system_prompt_in_messages(self):
        """System prompt should appear as the first message."""
        client = _make_client(mode="remote", api_key="sk-test-123")
        json_data = {"choices": [{"message": {"content": "ok"}}]}
        mock_response = _mock_aiohttp_response(status=200, json_data=json_data)
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await client._generate_openrouter("user prompt", "system prompt", 0.2, 512)

        call_kwargs = mock_session.post.call_args[1]
        payload = call_kwargs["json"]
        assert payload["messages"][0] == {"role": "system", "content": "system prompt"}
        assert payload["messages"][1] == {"role": "user", "content": "user prompt"}
        assert payload["temperature"] == 0.2
        assert payload["max_tokens"] == 512

    @pytest.mark.asyncio
    async def test_no_system_prompt_omits_system_message(self):
        """When system_prompt is None, messages should only contain user."""
        client = _make_client(mode="remote", api_key="sk-test-123")
        json_data = {"choices": [{"message": {"content": "ok"}}]}
        mock_response = _mock_aiohttp_response(status=200, json_data=json_data)
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await client._generate_openrouter("user prompt", None, 0.1, 1024)

        call_kwargs = mock_session.post.call_args[1]
        payload = call_kwargs["json"]
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_authorization_header(self):
        """Authorization header should contain the API key."""
        client = _make_client(mode="remote", api_key="sk-secret-key")
        json_data = {"choices": [{"message": {"content": "ok"}}]}
        mock_response = _mock_aiohttp_response(status=200, json_data=json_data)
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await client._generate_openrouter("prompt", None, 0.1, 1024)

        call_kwargs = mock_session.post.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer sk-secret-key"


# ===========================================================================
# 5. Hybrid fallback
# ===========================================================================


@pytest.mark.unit
class TestHybridFallback:
    """Tests for hybrid mode: local fail -> remote fallback."""

    @pytest.mark.asyncio
    async def test_generate_falls_back_on_connection_error(self):
        """generate() should fall back to remote when local raises LLMConnectionError."""
        client = _make_client(mode="hybrid", api_key="sk-test")

        with patch.object(
            client, "_generate_ollama", new_callable=AsyncMock
        ) as mock_local, patch.object(
            client, "_generate_openrouter", new_callable=AsyncMock
        ) as mock_remote:
            mock_local.side_effect = LLMConnectionError("connection refused")
            mock_remote.return_value = "remote answer"

            result = await client.generate("test prompt")

        assert result == "remote answer"
        mock_local.assert_awaited_once()
        mock_remote.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_falls_back_on_generation_error(self):
        """generate() should fall back to remote when local raises LLMGenerationError."""
        client = _make_client(mode="hybrid", api_key="sk-test")

        with patch.object(
            client, "_generate_ollama", new_callable=AsyncMock
        ) as mock_local, patch.object(
            client, "_generate_openrouter", new_callable=AsyncMock
        ) as mock_remote:
            mock_local.side_effect = LLMGenerationError("model not loaded")
            mock_remote.return_value = "remote answer"

            result = await client.generate("test prompt")

        assert result == "remote answer"

    @pytest.mark.asyncio
    async def test_stream_falls_back_on_connection_error(self):
        """generate_stream() should fall back to remote when local streaming fails."""
        client = _make_client(mode="hybrid", api_key="sk-test")

        async def failing_stream(*args, **kwargs):
            raise LLMConnectionError("connection refused")
            # Make this a generator by having an unreachable yield
            yield  # pragma: no cover

        async def remote_stream(*args, **kwargs):
            yield "remote"
            yield " token"

        with patch.object(client, "_stream_ollama", side_effect=failing_stream), patch.object(
            client, "_stream_openrouter", side_effect=remote_stream
        ):
            tokens = []
            async for token in client.generate_stream("test prompt"):
                tokens.append(token)

        assert tokens == ["remote", " token"]

    @pytest.mark.asyncio
    async def test_stream_falls_back_on_generation_error(self):
        """generate_stream() should fall back to remote when local raises LLMGenerationError."""
        client = _make_client(mode="hybrid", api_key="sk-test")

        async def failing_stream(*args, **kwargs):
            raise LLMGenerationError("model error")
            yield  # pragma: no cover

        async def remote_stream(*args, **kwargs):
            yield "fallback"

        with patch.object(client, "_stream_ollama", side_effect=failing_stream), patch.object(
            client, "_stream_openrouter", side_effect=remote_stream
        ):
            tokens = []
            async for token in client.generate_stream("test prompt"):
                tokens.append(token)

        assert tokens == ["fallback"]

    @pytest.mark.asyncio
    async def test_generate_local_succeeds_no_fallback(self):
        """When local succeeds in hybrid mode, remote should not be called."""
        client = _make_client(mode="hybrid", api_key="sk-test")

        with patch.object(
            client, "_generate_ollama", new_callable=AsyncMock
        ) as mock_local, patch.object(
            client, "_generate_openrouter", new_callable=AsyncMock
        ) as mock_remote:
            mock_local.return_value = "local answer"

            result = await client.generate("test prompt")

        assert result == "local answer"
        mock_remote.assert_not_awaited()


# ===========================================================================
# 6. _stream_ollama
# ===========================================================================


@pytest.mark.unit
class TestStreamOllama:
    """Tests for Ollama streaming (NDJSON)."""

    @pytest.mark.asyncio
    async def test_yields_tokens(self):
        """Should yield tokens from NDJSON response lines."""
        client = _make_client(mode="local")
        lines = [
            json.dumps({"response": "Hello", "done": False}).encode() + b"\n",
            json.dumps({"response": " world", "done": False}).encode() + b"\n",
            json.dumps({"response": "", "done": True}).encode() + b"\n",
        ]
        mock_response = _mock_aiohttp_response(status=200, content_lines=lines)
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            tokens = []
            async for token in client._stream_ollama("prompt", None, 0.1):
                tokens.append(token)

        assert tokens == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_handles_done_flag(self):
        """Should stop iterating when done=True."""
        client = _make_client(mode="local")
        lines = [
            json.dumps({"response": "first", "done": False}).encode() + b"\n",
            json.dumps({"response": "last", "done": True}).encode() + b"\n",
            json.dumps({"response": "should not appear", "done": False}).encode() + b"\n",
        ]
        mock_response = _mock_aiohttp_response(status=200, content_lines=lines)
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            tokens = []
            async for token in client._stream_ollama("prompt", None, 0.1):
                tokens.append(token)

        assert "should not appear" not in tokens
        assert tokens == ["first", "last"]

    @pytest.mark.asyncio
    async def test_skips_empty_lines(self):
        """Empty lines in the NDJSON stream should be ignored."""
        client = _make_client(mode="local")
        lines = [
            b"\n",
            json.dumps({"response": "token", "done": False}).encode() + b"\n",
            b"   \n",
            json.dumps({"response": "", "done": True}).encode() + b"\n",
        ]
        mock_response = _mock_aiohttp_response(status=200, content_lines=lines)
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            tokens = []
            async for token in client._stream_ollama("prompt", None, 0.1):
                tokens.append(token)

        assert tokens == ["token"]

    @pytest.mark.asyncio
    async def test_skips_invalid_json_lines(self):
        """Malformed JSON lines should be skipped without raising."""
        client = _make_client(mode="local")
        lines = [
            b"not valid json\n",
            json.dumps({"response": "valid", "done": False}).encode() + b"\n",
            json.dumps({"response": "", "done": True}).encode() + b"\n",
        ]
        mock_response = _mock_aiohttp_response(status=200, content_lines=lines)
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            tokens = []
            async for token in client._stream_ollama("prompt", None, 0.1):
                tokens.append(token)

        assert tokens == ["valid"]

    @pytest.mark.asyncio
    async def test_error_status_raises_generation_error(self):
        """Non-200 status should raise LLMGenerationError."""
        client = _make_client(mode="local")
        mock_response = _mock_aiohttp_response(status=500, text_data="Internal Error")
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(LLMGenerationError, match="Ollama API error"):
                async for _ in client._stream_ollama("prompt", None, 0.1):
                    pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_connection_error_raises_llm_connection_error(self):
        """aiohttp.ClientError should be wrapped in LLMConnectionError."""
        client = _make_client(mode="local")

        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=aiohttp.ClientError("Connection refused"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(LLMConnectionError, match="Ollama connection failed"):
                async for _ in client._stream_ollama("prompt", None, 0.1):
                    pass  # pragma: no cover


# ===========================================================================
# 7. _stream_openrouter
# ===========================================================================


@pytest.mark.unit
class TestStreamOpenRouter:
    """Tests for OpenRouter streaming (SSE)."""

    @pytest.mark.asyncio
    async def test_yields_tokens_from_sse(self):
        """Should yield tokens from SSE data lines."""
        client = _make_client(mode="remote", api_key="sk-test")
        lines = [
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n',
            b'data: {"choices":[{"delta":{"content":" world"}}]}\n',
            b"data: [DONE]\n",
        ]
        mock_response = _mock_aiohttp_response(status=200, content_lines=lines)
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            tokens = []
            async for token in client._stream_openrouter("prompt", None, 0.1, 1024):
                tokens.append(token)

        assert tokens == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_handles_done_sentinel(self):
        """Should stop iterating when [DONE] sentinel is received."""
        client = _make_client(mode="remote", api_key="sk-test")
        lines = [
            b'data: {"choices":[{"delta":{"content":"token"}}]}\n',
            b"data: [DONE]\n",
            b'data: {"choices":[{"delta":{"content":"after done"}}]}\n',
        ]
        mock_response = _mock_aiohttp_response(status=200, content_lines=lines)
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            tokens = []
            async for token in client._stream_openrouter("prompt", None, 0.1, 1024):
                tokens.append(token)

        assert "after done" not in tokens
        assert tokens == ["token"]

    @pytest.mark.asyncio
    async def test_skips_non_data_lines(self):
        """Lines that don't start with 'data: ' should be ignored."""
        client = _make_client(mode="remote", api_key="sk-test")
        lines = [
            b": keep-alive\n",
            b"\n",
            b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
            b"data: [DONE]\n",
        ]
        mock_response = _mock_aiohttp_response(status=200, content_lines=lines)
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            tokens = []
            async for token in client._stream_openrouter("prompt", None, 0.1, 1024):
                tokens.append(token)

        assert tokens == ["ok"]

    @pytest.mark.asyncio
    async def test_skips_empty_content_deltas(self):
        """Deltas with empty content should not yield tokens."""
        client = _make_client(mode="remote", api_key="sk-test")
        lines = [
            b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n',
            b'data: {"choices":[{"delta":{"content":""}}]}\n',
            b'data: {"choices":[{"delta":{"content":"real"}}]}\n',
            b"data: [DONE]\n",
        ]
        mock_response = _mock_aiohttp_response(status=200, content_lines=lines)
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            tokens = []
            async for token in client._stream_openrouter("prompt", None, 0.1, 1024):
                tokens.append(token)

        assert tokens == ["real"]

    @pytest.mark.asyncio
    async def test_skips_invalid_json(self):
        """Malformed JSON in SSE data should be skipped."""
        client = _make_client(mode="remote", api_key="sk-test")
        lines = [
            b"data: {invalid json}\n",
            b'data: {"choices":[{"delta":{"content":"valid"}}]}\n',
            b"data: [DONE]\n",
        ]
        mock_response = _mock_aiohttp_response(status=200, content_lines=lines)
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            tokens = []
            async for token in client._stream_openrouter("prompt", None, 0.1, 1024):
                tokens.append(token)

        assert tokens == ["valid"]

    @pytest.mark.asyncio
    async def test_missing_api_key_raises_generation_error(self):
        """Empty API key should raise LLMGenerationError before any HTTP call."""
        client = _make_client(mode="remote", api_key="")
        with pytest.raises(LLMGenerationError, match="API key not configured"):
            async for _ in client._stream_openrouter("prompt", None, 0.1, 1024):
                pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_error_status_raises_generation_error(self):
        """Non-200 status should raise LLMGenerationError."""
        client = _make_client(mode="remote", api_key="sk-test")
        mock_response = _mock_aiohttp_response(status=503, text_data="Service Unavailable")
        mock_session = _mock_aiohttp_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(LLMGenerationError, match="OpenRouter API error"):
                async for _ in client._stream_openrouter("prompt", None, 0.1, 1024):
                    pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_connection_error_raises_llm_connection_error(self):
        """aiohttp.ClientError should be wrapped in LLMConnectionError."""
        client = _make_client(mode="remote", api_key="sk-test")

        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=aiohttp.ClientError("DNS failure"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(LLMConnectionError, match="OpenRouter connection failed"):
                async for _ in client._stream_openrouter("prompt", None, 0.1, 1024):
                    pass  # pragma: no cover


# ===========================================================================
# 8. answer_question
# ===========================================================================


@pytest.mark.unit
class TestAnswerQuestion:
    """Tests for the high-level answer_question method."""

    @pytest.mark.asyncio
    async def test_returns_expected_dict(self):
        """answer_question should return a dict with answer, question, model, mode."""
        client = _make_client(mode="local", model_name="test-model")

        with patch.object(client, "generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "The answer is 42."

            result = await client.answer_question(
                question="What is the answer?",
                context=["Context chunk 1", "Context chunk 2"],
                attribution="CC BY 4.0",
            )

        assert result["answer"] == "The answer is 42."
        assert result["question"] == "What is the answer?"
        assert result["model"] == "test-model"
        assert result["mode"] == "local"

    @pytest.mark.asyncio
    async def test_calls_generate_with_built_prompts(self):
        """answer_question should pass the built prompts to generate."""
        client = _make_client(mode="local")

        with patch.object(client, "generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "answer"

            await client.answer_question(
                question="Q?",
                context=["chunk"],
                attribution="attr",
            )

        call_kwargs = mock_gen.call_args[1]
        assert "Q?" in call_kwargs["prompt"]
        assert "chunk" in call_kwargs["prompt"]
        assert "attr" in call_kwargs["prompt"]
        assert call_kwargs["system_prompt"] is not None
        assert call_kwargs["temperature"] == 0.1

    @pytest.mark.asyncio
    async def test_custom_system_prompt_forwarded(self):
        """Custom system_prompt should override the default."""
        client = _make_client(mode="local")

        with patch.object(client, "generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "answer"

            await client.answer_question(
                question="Q?",
                context=["chunk"],
                attribution="attr",
                system_prompt="You are a math tutor.",
            )

        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["system_prompt"] == "You are a math tutor."

    @pytest.mark.asyncio
    async def test_custom_context_label(self):
        """Custom context_label should appear in the user prompt."""
        client = _make_client(mode="local")

        with patch.object(client, "generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "answer"

            await client.answer_question(
                question="Q?",
                context=["chunk"],
                attribution="attr",
                context_label="Context from US History",
            )

        call_kwargs = mock_gen.call_args[1]
        assert "Context from US History" in call_kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_answer_question_stream_yields_tokens(self):
        """answer_question_stream should yield tokens from generate_stream."""
        client = _make_client(mode="local")

        async def mock_stream(**kwargs):
            yield "Hello"
            yield " World"

        with patch.object(client, "generate_stream", side_effect=mock_stream):
            tokens = []
            async for token in client.answer_question_stream(
                question="Q?",
                context=["chunk"],
                attribution="attr",
            ):
                tokens.append(token)

        assert tokens == ["Hello", " World"]


# ===========================================================================
# 9. _build_answer_prompts
# ===========================================================================


@pytest.mark.unit
class TestBuildPrompts:
    """Tests for _build_answer_prompts."""

    def test_default_system_prompt(self):
        """Without custom system_prompt, should use the expert tutor default."""
        client = _make_client()
        result = client._build_answer_prompts(
            question="What is GDP?",
            context=["GDP is gross domestic product."],
            attribution="OpenStax CC BY 4.0",
        )

        assert "expert tutor" in result["system_prompt"]
        assert "ONLY the provided" in result["system_prompt"]
        assert "attribution" in result["system_prompt"].lower()

    def test_custom_system_prompt(self):
        """Custom system_prompt should replace the default entirely."""
        client = _make_client()
        result = client._build_answer_prompts(
            question="Q?",
            context=["chunk"],
            attribution="attr",
            system_prompt="You are a pirate.",
        )

        assert result["system_prompt"] == "You are a pirate."

    def test_context_formatting(self):
        """Context chunks should be numbered with [1], [2], etc."""
        client = _make_client()
        result = client._build_answer_prompts(
            question="Q?",
            context=["First chunk", "Second chunk", "Third chunk"],
            attribution="attr",
        )

        user_prompt = result["user_prompt"]
        assert "[1] First chunk" in user_prompt
        assert "[2] Second chunk" in user_prompt
        assert "[3] Third chunk" in user_prompt

    def test_attribution_in_user_prompt(self):
        """Attribution text should appear in the user prompt."""
        client = _make_client()
        result = client._build_answer_prompts(
            question="Q?",
            context=["chunk"],
            attribution="Licensed under CC BY 4.0",
        )

        assert "Licensed under CC BY 4.0" in result["user_prompt"]

    def test_question_in_user_prompt(self):
        """The question should appear in the user prompt."""
        client = _make_client()
        result = client._build_answer_prompts(
            question="What causes inflation?",
            context=["chunk"],
            attribution="attr",
        )

        assert "What causes inflation?" in result["user_prompt"]

    def test_default_context_label(self):
        """Default context_label should be 'Context from textbook'."""
        client = _make_client()
        result = client._build_answer_prompts(
            question="Q?",
            context=["chunk"],
            attribution="attr",
        )

        assert "Context from textbook" in result["user_prompt"]

    def test_custom_context_label(self):
        """Custom context_label should replace the default."""
        client = _make_client()
        result = client._build_answer_prompts(
            question="Q?",
            context=["chunk"],
            attribution="attr",
            context_label="Context from Economics",
        )

        assert "Context from Economics" in result["user_prompt"]
        assert "Context from textbook" not in result["user_prompt"]

    def test_returns_dict_with_both_keys(self):
        """Should return a dict with exactly 'system_prompt' and 'user_prompt'."""
        client = _make_client()
        result = client._build_answer_prompts(
            question="Q?",
            context=["chunk"],
            attribution="attr",
        )

        assert set(result.keys()) == {"system_prompt", "user_prompt"}

    def test_empty_context_list(self):
        """Empty context list should produce a user prompt with no numbered items."""
        client = _make_client()
        result = client._build_answer_prompts(
            question="Q?",
            context=[],
            attribution="attr",
        )

        assert "[1]" not in result["user_prompt"]
        assert "Q?" in result["user_prompt"]
