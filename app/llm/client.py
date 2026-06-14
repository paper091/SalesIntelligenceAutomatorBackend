"""LLM client abstraction. Default implementation talks to Groq's
OpenAI-compatible API; swap providers via the LLM_PROVIDER env var.
"""
from __future__ import annotations

import asyncio
import json
import random
from abc import ABC, abstractmethod

from openai import AsyncOpenAI, APIStatusError

from app.core.config import settings

_MAX_RETRIES = 3


class LLMClient(ABC):
    """Minimal interface the pipeline depends on."""

    @abstractmethod
    async def complete_json(self, system: str, user: str, model: str) -> dict:
        """Return a parsed JSON object from the model's response."""


class GroqClient(LLMClient):
    """Groq's API is OpenAI-compatible, so we reuse the `openai` SDK."""

    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url)

    async def complete_json(self, system: str, user: str, model: str) -> dict:
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    temperature=0.1,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                content = response.choices[0].message.content or "{}"
                return json.loads(content)
            except APIStatusError as exc:
                # Groq's free tier rate-limits aggressively; back off with
                # jitter and retry rather than failing the whole lead.
                if exc.status_code == 429 and attempt < _MAX_RETRIES - 1:
                    backoff = (2**attempt) + random.random()
                    await asyncio.sleep(backoff)
                    continue
                raise
            except json.JSONDecodeError:
                # Occasionally the model returns truncated/invalid JSON
                # even in JSON mode - just try again.
                if attempt < _MAX_RETRIES - 1:
                    continue
                raise


def get_llm_client() -> LLMClient:
    """Return the configured LLM client. Currently only Groq is implemented;
    other providers (Ollama, Gemini) can be added here behind LLM_PROVIDER.
    """
    if settings.llm_provider == "groq":
        return GroqClient()
    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")
