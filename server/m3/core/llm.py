"""
M3 LLM Provider — abstractions and implementations for LLM + embeddings.

LLMProvider handles text generation (Anthropic Claude).
EmbeddingProvider handles vector embeddings (fastembed local by default).
"""

import asyncio
import base64
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import anthropic

from m3.config import EmbeddingSettings, LLMSettings

logger = logging.getLogger("m3.llm")


# --- Abstractions ---


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str: ...

    @abstractmethod
    async def complete_stream(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]: ...


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    @abstractmethod
    def dimensions(self) -> int: ...


# --- Content helpers ---


def make_content_blocks(
    text: str | None = None,
    image_bytes: bytes | None = None,
    audio_bytes: bytes | None = None,
    media_type: str | None = None,
) -> list[dict]:
    """Build Anthropic content blocks for multimodal messages."""
    blocks = []
    if image_bytes and media_type:
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(image_bytes).decode(),
            },
        })
    if audio_bytes and media_type:
        blocks.append({
            "type": "audio",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(audio_bytes).decode(),
            },
        })
    if text:
        blocks.append({"type": "text", "text": text})
    return blocks


# --- Anthropic implementation ---


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    async def complete(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system

        response = await self.client.messages.create(**kwargs)
        return response.content[0].text

    async def complete_stream(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system

        async with self.client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text


# --- OpenAI-compatible implementation (MiniMax, OpenRouter, Groq, Together, Ollama, etc.) ---


class OpenAICompatibleProvider(LLMProvider):
    """Works with any provider that speaks the OpenAI chat completions API."""

    def __init__(self, api_key: str, model: str, base_url: str):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    async def complete(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(self._normalize_messages(messages))

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    async def complete_stream(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(self._normalize_messages(messages))

        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    def _normalize_messages(self, messages: list[dict]) -> list[dict]:
        """Convert Anthropic-style content blocks to plain text for OpenAI API.

        Anthropic uses [{"type": "text", "text": "..."}] content blocks.
        OpenAI expects a plain string. Multimodal (images/audio) is dropped
        since most OpenAI-compatible providers don't support it the same way.
        """
        normalized = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                # Extract text from content blocks
                text_parts = [
                    block["text"] for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                content = "\n".join(text_parts) if text_parts else ""
            normalized.append({"role": msg["role"], "content": content})
        return normalized


# --- FastEmbed local embedding ---


class FastEmbedProvider(EmbeddingProvider):
    """Local CPU-based embeddings via fastembed + ONNX runtime."""

    def __init__(self, model: str = "nomic-ai/nomic-embed-text-v1.5", dim: int = 768):
        from fastembed import TextEmbedding

        self._model_name = model
        self._dim = dim
        self._model = TextEmbedding(model_name=model)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        def _embed():
            embeddings = list(self._model.embed(texts))
            return [e.tolist() for e in embeddings]

        return await asyncio.to_thread(_embed)

    @property
    def dimensions(self) -> int:
        return self._dim


# --- Factories ---


def create_llm_provider(settings: LLMSettings) -> LLMProvider:
    provider_config = settings.providers.get(settings.default_provider)
    if not provider_config:
        raise ValueError(f"LLM provider '{settings.default_provider}' not configured")

    if provider_config.type == "anthropic":
        return AnthropicProvider(api_key=provider_config.api_key, model=provider_config.model)

    if provider_config.type == "openai_compatible":
        if not provider_config.base_url:
            raise ValueError("openai_compatible provider requires a base_url")
        return OpenAICompatibleProvider(
            api_key=provider_config.api_key,
            model=provider_config.model,
            base_url=provider_config.base_url,
        )

    raise ValueError(f"Unknown LLM provider type: {provider_config.type}")


def create_embedding_provider(settings: EmbeddingSettings) -> EmbeddingProvider:
    if settings.provider == "fastembed":
        return FastEmbedProvider(model=settings.model, dim=settings.dimensions)

    raise ValueError(f"Unknown embedding provider: {settings.provider}")
