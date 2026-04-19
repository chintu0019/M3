"""
Factory functions that build concrete providers from ``m3.config`` settings.

Kept separate from the provider modules so ``base.py`` stays dependency-free
and the provider modules don't need to know about the app's config layer.
"""

from m3.config import EmbeddingSettings, LLMSettings
from m3.core.llm.anthropic import AnthropicProvider, OpenAICompatibleProvider
from m3.core.llm.base import EmbeddingProvider, LLMProvider
from m3.core.llm.embeddings import FastEmbedProvider


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
            supports_tools=provider_config.supports_tools,
            supports_vision=provider_config.supports_vision,
        )

    raise ValueError(f"Unknown LLM provider type: {provider_config.type}")


def create_embedding_provider(settings: EmbeddingSettings) -> EmbeddingProvider:
    if settings.provider == "fastembed":
        return FastEmbedProvider(model=settings.model, dim=settings.dimensions)

    raise ValueError(f"Unknown embedding provider: {settings.provider}")
