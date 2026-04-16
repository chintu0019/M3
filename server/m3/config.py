"""
M3 Configuration — Pydantic Settings with YAML + env var support.

Load order: defaults -> config.yml -> environment variables.
Env vars use M3_ prefix with __ as nested delimiter.
Example: M3_DATABASE__URL overrides database.url
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    url: str = "postgresql+asyncpg://m3:m3dev@localhost:5432/m3"
    pool_size: int = 10
    max_overflow: int = 20


class StorageSettings(BaseModel):
    endpoint: str = "localhost:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"
    bucket: str = "m3-data"
    secure: bool = False


class RedisSettings(BaseModel):
    url: str = "redis://localhost:6379"


class LLMProviderConfig(BaseModel):
    type: str = "anthropic"  # anthropic, openai_compatible
    api_key: str = ""
    model: str = "claude-sonnet-4-20250514"
    base_url: str | None = None  # For OpenAI-compatible APIs (MiniMax, OpenRouter, Groq, etc.)
    # Capability hints for openai_compatible endpoints. Anthropic is always
    # capable. Cloud vendors that speak OpenAI (Groq, Together, OpenRouter,
    # OpenAI itself) should set supports_tools=true; plain local Ollama
    # without a tool-capable model should leave these at false.
    supports_tools: bool = False
    supports_vision: bool = False


class EmbeddingSettings(BaseModel):
    provider: str = "fastembed"
    model: str = "nomic-ai/nomic-embed-text-v1.5"
    dimensions: int = 768


class LLMSettings(BaseModel):
    default_provider: str = "minimax"
    providers: dict[str, LLMProviderConfig] = {
        "minimax": LLMProviderConfig(
            type="openai_compatible",
            model="MiniMax-M1",
            base_url="https://api.minimaxi.chat/v1",
        ),
        "claude": LLMProviderConfig(),
    }
    embedding: EmbeddingSettings = EmbeddingSettings()


class ProcessingSettings(BaseModel):
    engine: str = "basic"
    engine_path: str | None = None
    auto_compile: bool = True
    compile_interval_minutes: int = 60
    wiki_mode: str = "document"  # "document" (current) or "entity" (Phase 2+)


class TelegramSettings(BaseModel):
    enabled: bool = False
    bot_token: str = ""


class CaptureSettings(BaseModel):
    telegram: TelegramSettings = TelegramSettings()


class AuthSettings(BaseModel):
    api_key: str = ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="M3_",
        env_nested_delimiter="__",
    )

    server_host: str = "0.0.0.0"
    server_port: int = 8000
    data_dir: str = "/data"
    database: DatabaseSettings = DatabaseSettings()
    storage: StorageSettings = StorageSettings()
    redis: RedisSettings = RedisSettings()
    llm: LLMSettings = LLMSettings()
    processing: ProcessingSettings = ProcessingSettings()
    capture: CaptureSettings = CaptureSettings()
    auth: AuthSettings = AuthSettings()


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, recursively for nested dicts."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from config.yml (if exists) + env vars.

    config.yml values are used as defaults, env vars override everything.
    """
    yaml_data: dict[str, Any] = {}

    paths_to_try = [config_path] if config_path else [
        Path("config.yml"),
        Path("config.yaml"),
        Path("/etc/m3/config.yml"),
    ]

    for path in paths_to_try:
        if path and Path(path).exists():
            with open(path) as f:
                yaml_data = yaml.safe_load(f) or {}
            break

    return Settings(**yaml_data)
