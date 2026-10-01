"""
LLM client for question answering and text generation.

Supports local Ollama and remote OpenRouter APIs, including streaming.

Privacy: while ``PRIVACY_LOCAL_ONLY`` is enabled no request is ever sent to
OpenRouter. Remote mode is refused and hybrid mode never falls back. This is
checked on every call, in addition to the startup validation in ``Settings``.
"""

import json
import ssl
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import aiohttp
from loguru import logger
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.app.core.exceptions import LLMConnectionError, LLMGenerationError
from backend.app.core.settings import settings

LLMProvider = Literal["local", "remote"]

DEFAULT_MAX_TOKENS = 1024


class RemoteLLMDisabledError(LLMGenerationError):
    """A remote LLM call was attempted while PRIVACY_LOCAL_ONLY is enabled."""


@dataclass(frozen=True)
class LLMResult:
    """Generated text plus the provider and model that actually produced it."""

    text: str
    provider: LLMProvider
    model: str
    fallback: bool = False  # True when hybrid mode fell back from Ollama to OpenRouter


@dataclass
class LLMStreamInfo:
    """Filled in by a streaming call before its first token is yielded."""

    provider: LLMProvider | None = None
    model: str | None = None
    fallback: bool = False


class LLMClient:
    """Client for LLM inference (Ollama or OpenRouter)."""

    def __init__(
        self,
        mode: str | None = None,
        model_name: str | None = None,
    ):
        """
        Initialize LLM client.

        Args:
            mode: LLM mode ('local', 'remote', or 'hybrid'); defaults to LLM_MODE
            model_name: Override for the primary model: the OpenRouter model in remote
                mode, otherwise the Ollama model
        """
        self.mode = mode or settings.llm_mode
        if self.mode == "remote":
            self.local_model = settings.llm_local_model
            self.remote_model = model_name or settings.openrouter_model
        else:
            self.local_model = model_name or settings.llm_local_model
            self.remote_model = settings.openrouter_model

        self.ollama_host = settings.llm_ollama_host
        self.openrouter_api_key = settings.openrouter_api_key
        self.openrouter_base_url = settings.openrouter_base_url

    @property
    def model_name(self) -> str:
        """The model tried first in this mode (the OpenRouter model in remote mode)."""
        return self.remote_model if self.mode == "remote" else self.local_model

    @staticmethod
    def _remote_allowed() -> bool:
        return not settings.privacy_local_only

    def _ensure_remote_allowed(self) -> None:
        if not self._remote_allowed():
            raise RemoteLLMDisabledError(
                "Remote LLM calls are disabled because PRIVACY_LOCAL_ONLY=true "
                "(set LLM_MODE=local, or PRIVACY_LOCAL_ONLY=false to allow OpenRouter)"
            )

    def _may_fall_back(self) -> bool:
        """Whether a failed local call may be retried on OpenRouter."""
        if self.mode != "hybrid":
            return False
        if not self._remote_allowed():
            logger.warning("Hybrid fallback to OpenRouter skipped: PRIVACY_LOCAL_ONLY=true")
            return False
        return True

    async def generate_result(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        """
        Generate text and report which provider and model produced it.

        Args:
            prompt: User prompt
            system_prompt: System/instruction prompt
            temperature: Temperature for sampling (defaults to LLM_TEMPERATURE)
            max_tokens: Maximum tokens to generate (defaults to 1024)

        Returns:
            LLMResult with the generated text, provider, model and fallback flag
        """
        temperature = temperature if temperature is not None else settings.llm_temperature
        max_tokens = max_tokens or DEFAULT_MAX_TOKENS

        if self.mode == "remote":
            self._ensure_remote_allowed()
            text = await self._generate_openrouter(prompt, system_prompt, temperature, max_tokens)
            return LLMResult(text=text, provider="remote", model=self.remote_model)

        try:
            text = await self._generate_ollama(prompt, system_prompt, temperature, max_tokens)
            return LLMResult(text=text, provider="local", model=self.local_model)
        except (LLMConnectionError, LLMGenerationError) as e:
            if not self._may_fall_back():
                raise
            logger.warning(f"Local LLM failed ({e}), falling back to remote")

        text = await self._generate_openrouter(prompt, system_prompt, temperature, max_tokens)
        return LLMResult(text=text, provider="remote", model=self.remote_model, fallback=True)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """
        Generate text using LLM.

        Args:
            prompt: User prompt
            system_prompt: System/instruction prompt
            temperature: Temperature for sampling
            max_tokens: Maximum tokens to generate

        Returns:
            Generated text
        """
        result = await self.generate_result(prompt, system_prompt, temperature, max_tokens)
        return result.text

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream_info: LLMStreamInfo | None = None,
    ) -> AsyncIterator[str]:
        """
        Generate text using LLM with streaming.

        Yields tokens as they arrive from the LLM provider. When ``stream_info`` is
        given it is filled in with the serving provider and model before the first
        token. Hybrid mode only falls back to OpenRouter if Ollama fails before
        producing any token.
        """
        temperature = temperature if temperature is not None else settings.llm_temperature
        max_tokens = max_tokens or DEFAULT_MAX_TOKENS
        info = stream_info if stream_info is not None else LLMStreamInfo()

        if self.mode == "remote":
            self._ensure_remote_allowed()
            info.provider = "remote"
            info.model = self.remote_model
            async for token in self._stream_openrouter(
                prompt, system_prompt, temperature, max_tokens
            ):
                yield token
            return

        info.provider = "local"
        info.model = self.local_model
        yielded_any = False
        try:
            async for token in self._stream_ollama(prompt, system_prompt, temperature, max_tokens):
                yielded_any = True
                yield token
            return
        except (LLMConnectionError, LLMGenerationError) as e:
            if yielded_any or not self._may_fall_back():
                raise
            logger.warning(f"Local LLM stream failed ({e}), falling back to remote")

        info.provider = "remote"
        info.model = self.remote_model
        info.fallback = True
        async for token in self._stream_openrouter(prompt, system_prompt, temperature, max_tokens):
            yield token

    def _ollama_payload(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> dict[str, Any]:
        """Build an Ollama /api/generate payload; sampling parameters go in ``options``."""
        return {
            "model": self.local_model,
            "prompt": prompt,
            "system": system_prompt or "",
            "stream": stream,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }

    async def _generate_ollama(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        """Generate using local Ollama."""
        url = f"{self.ollama_host}/api/generate"
        payload = self._ollama_payload(prompt, system_prompt, temperature, max_tokens, False)

        @retry(
            stop=stop_after_attempt(settings.llm_retry_attempts),
            wait=wait_exponential(min=settings.llm_retry_min_wait, max=settings.llm_retry_max_wait),
            retry=retry_if_exception_type(LLMConnectionError),
            before_sleep=before_sleep_log(logger, "WARNING"),  # type: ignore[arg-type]
            reraise=True,
        )
        async def _call() -> str:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=settings.llm_timeout),
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            return str(data.get("response", ""))
                        else:
                            error_text = await response.text()
                            raise LLMGenerationError(
                                f"Ollama API error ({response.status}): {error_text}"
                            )
            except aiohttp.ClientError as e:
                raise LLMConnectionError(f"Ollama connection failed: {e}") from e

        return await _call()

    async def _stream_ollama(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> AsyncIterator[str]:
        """Stream tokens from local Ollama."""
        url = f"{self.ollama_host}/api/generate"
        payload = self._ollama_payload(prompt, system_prompt, temperature, max_tokens, True)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=settings.llm_stream_timeout),
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise LLMGenerationError(
                            f"Ollama API error ({response.status}): {error_text}"
                        )

                    async for line in response.content:
                        line_text = line.decode("utf-8").strip()
                        if not line_text:
                            continue
                        try:
                            data = json.loads(line_text)
                            token = data.get("response", "")
                            if token:
                                yield token
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
        except aiohttp.ClientError as e:
            raise LLMConnectionError(f"Ollama connection failed: {e}") from e

    def _openrouter_request(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> tuple[str, dict[str, Any], dict[str, str], ssl.SSLContext | bool]:
        """Build URL, payload, headers and SSL option for an OpenRouter chat completion."""
        self._ensure_remote_allowed()
        if not self.openrouter_api_key:
            raise LLMGenerationError("OpenRouter API key not configured")

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.remote_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if stream:
            payload["stream"] = True

        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
        }

        ssl_param: ssl.SSLContext | bool = True
        if not settings.openrouter_verify_ssl:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            ssl_param = ssl_context

        return f"{self.openrouter_base_url}/chat/completions", payload, headers, ssl_param

    async def _generate_openrouter(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Generate using OpenRouter API."""
        url, payload, headers, ssl_param = self._openrouter_request(
            prompt, system_prompt, temperature, max_tokens, stream=False
        )

        @retry(
            stop=stop_after_attempt(settings.llm_retry_attempts),
            wait=wait_exponential(min=settings.llm_retry_min_wait, max=settings.llm_retry_max_wait),
            retry=retry_if_exception_type(LLMConnectionError),
            before_sleep=before_sleep_log(logger, "WARNING"),  # type: ignore[arg-type]
            reraise=True,
        )
        async def _call() -> str:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=settings.llm_timeout),
                        ssl=ssl_param,
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            return str(data["choices"][0]["message"]["content"])
                        else:
                            error_text = await response.text()
                            raise LLMGenerationError(
                                f"OpenRouter API error ({response.status}): {error_text}"
                            )
            except aiohttp.ClientError as e:
                raise LLMConnectionError(f"OpenRouter connection failed: {e}") from e

        return await _call()

    async def _stream_openrouter(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        """Stream tokens from OpenRouter API (SSE)."""
        url, payload, headers, ssl_param = self._openrouter_request(
            prompt, system_prompt, temperature, max_tokens, stream=True
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=settings.llm_stream_timeout),
                    ssl=ssl_param,
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise LLMGenerationError(
                            f"OpenRouter API error ({response.status}): {error_text}"
                        )

                    async for line in response.content:
                        line_text = line.decode("utf-8").strip()
                        if not line_text or not line_text.startswith("data: "):
                            continue
                        data_str = line_text[6:]  # Strip "data: " prefix
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            token = delta.get("content", "")
                            if token:
                                yield token
                        except json.JSONDecodeError:
                            continue
        except aiohttp.ClientError as e:
            raise LLMConnectionError(f"OpenRouter connection failed: {e}") from e

    async def answer_question(
        self,
        question: str,
        context: list[str],
        attribution: str,
        system_prompt: str | None = None,
        context_label: str | None = None,
    ) -> dict[str, Any]:
        """
        Answer a question using retrieved context.

        Args:
            question: User question
            context: List of retrieved text chunks
            attribution: Attribution text to include
            system_prompt: Custom system prompt (defaults to generic tutor prompt)
            context_label: Label for the context section (e.g., "Context from US History")

        Returns:
            Dict with 'answer', 'question', 'model' (the model that produced the answer),
            'provider' ('local' or 'remote'), 'fallback' (hybrid fell back to remote)
            and 'mode'
        """
        prompts = self._build_answer_prompts(
            question, context, attribution, system_prompt, context_label
        )

        result = await self.generate_result(
            prompt=prompts["user_prompt"],
            system_prompt=prompts["system_prompt"],
            temperature=0.1,  # Low temperature for factual accuracy
        )

        return {
            "answer": result.text,
            "question": question,
            "model": result.model,
            "provider": result.provider,
            "fallback": result.fallback,
            "mode": self.mode,
        }

    async def answer_question_stream(
        self,
        question: str,
        context: list[str],
        attribution: str,
        system_prompt: str | None = None,
        context_label: str | None = None,
        stream_info: LLMStreamInfo | None = None,
    ) -> AsyncIterator[str]:
        """Stream answer tokens for a question using retrieved context."""
        prompts = self._build_answer_prompts(
            question, context, attribution, system_prompt, context_label
        )

        async for token in self.generate_stream(
            prompt=prompts["user_prompt"],
            system_prompt=prompts["system_prompt"],
            temperature=0.1,
            stream_info=stream_info,
        ):
            yield token

    def _build_answer_prompts(
        self,
        question: str,
        context: list[str],
        attribution: str,
        system_prompt: str | None = None,
        context_label: str | None = None,
    ) -> dict[str, str]:
        """Build system and user prompts for answer generation."""
        context_str = "\n\n".join([f"[{i + 1}] {chunk}" for i, chunk in enumerate(context)])

        if system_prompt is None:
            system_prompt = """You are an expert tutor. Answer the student's question using ONLY the provided textbook context.

Rules:
1. Base your answer ONLY on the provided context
2. If the context doesn't contain enough information, say so
3. Cite context passages using [1], [2], etc.
4. Be clear, accurate, and educational
5. Include the attribution at the end of your response"""

        if context_label is None:
            context_label = "Context from textbook"

        user_prompt = f"""Question: {question}

{context_label}:
{context_str}

Please answer the question based on the context above. End your response with the attribution:
{attribution}"""

        return {"system_prompt": system_prompt, "user_prompt": user_prompt}


# Global singleton
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """
    Get or create global LLM client instance.

    Returns:
        LLMClient instance
    """
    global _llm_client

    if _llm_client is None:
        _llm_client = LLMClient()

    return _llm_client
