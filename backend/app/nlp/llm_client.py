"""
LLM client for question answering and text generation.

Supports local Ollama and remote OpenRouter APIs.
"""

import ssl

import aiohttp
from loguru import logger

from backend.app.core.settings import settings


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
            mode: LLM mode ('local', 'remote', or 'hybrid')
            model_name: Model name to use
        """
        self.mode = mode or settings.llm_mode
        self.model_name = model_name or settings.llm_local_model

        self.ollama_host = settings.llm_ollama_host
        self.openrouter_api_key = settings.openrouter_api_key
        self.openrouter_base_url = settings.openrouter_base_url

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = None,
        max_tokens: int = None,
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
        temperature = temperature if temperature is not None else settings.llm_temperature
        max_tokens = max_tokens or 1024

        if self.mode == "local":
            return await self._generate_ollama(prompt, system_prompt, temperature)
        elif self.mode == "remote":
            return await self._generate_openrouter(prompt, system_prompt, temperature, max_tokens)
        else:  # hybrid - try local first, fall back to remote
            try:
                return await self._generate_ollama(prompt, system_prompt, temperature)
            except Exception as e:
                logger.warning(f"Local LLM failed ({e}), falling back to remote")
                return await self._generate_openrouter(
                    prompt, system_prompt, temperature, max_tokens
                )

    async def _generate_ollama(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
    ) -> str:
        """Generate using local Ollama."""
        url = f"{self.ollama_host}/api/generate"

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "system": system_prompt or "",
            "temperature": temperature,
            "stream": False,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("response", "")
                else:
                    error_text = await response.text()
                    raise RuntimeError(f"Ollama API error ({response.status}): {error_text}")

    async def _generate_openrouter(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Generate using OpenRouter API."""
        if not self.openrouter_api_key:
            raise RuntimeError("OpenRouter API key not configured")

        url = f"{self.openrouter_base_url}/chat/completions"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": settings.openrouter_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
        }

        # Configure SSL context
        ssl_context = None
        if not settings.openrouter_verify_ssl:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
                ssl=ssl_context,
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    error_text = await response.text()
                    raise RuntimeError(f"OpenRouter API error ({response.status}): {error_text}")

    async def answer_question(
        self,
        question: str,
        context: list[str],
        attribution: str,
        system_prompt: str | None = None,
        context_label: str | None = None,
    ) -> dict[str, str]:
        """
        Answer a question using retrieved context.

        Args:
            question: User question
            context: List of retrieved text chunks
            attribution: Attribution text to include
            system_prompt: Custom system prompt (defaults to generic tutor prompt)
            context_label: Label for the context section (e.g., "Context from US History")

        Returns:
            Dict with 'answer' and 'reasoning'
        """
        # Build context string
        context_str = "\n\n".join([f"[{i + 1}] {chunk}" for i, chunk in enumerate(context)])

        # Default system prompt if not provided
        if system_prompt is None:
            system_prompt = """You are an expert tutor. Answer the student's question using ONLY the provided textbook context.

Rules:
1. Base your answer ONLY on the provided context
2. If the context doesn't contain enough information, say so
3. Cite context passages using [1], [2], etc.
4. Be clear, accurate, and educational
5. Include the attribution at the end of your response"""

        # Default context label if not provided
        if context_label is None:
            context_label = "Context from textbook"

        # User prompt
        user_prompt = f"""Question: {question}

{context_label}:
{context_str}

Please answer the question based on the context above. End your response with the attribution:
{attribution}"""

        # Generate answer
        answer = await self.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.1,  # Low temperature for factual accuracy
        )

        return {
            "answer": answer,
            "question": question,
            "model": self.model_name,
            "mode": self.mode,
        }


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
