"""GET + PUT /api/v1/settings — LLM provider configuration.

The UI reads the effective settings (env > config.yml > default) and writes
changes to ~/.config/m3/config.yml. Since _make_llm is called per-request and
re-reads config on each call, a setting change takes effect on the NEXT
incoming request without a server restart.

The API key is stored in the chmod-600 config file but never returned on
read — the UI only sees a boolean presence flag. env_overrides surfaces any
env vars that would win over config.yml, so users can tell when their saved
setting isn't being used because an env var is shadowing it.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from m3.core import config as _cfg


class LLMSettingsView(BaseModel):
    """What the UI sees. api_key is redacted."""
    provider: str
    ollama_host: str
    ollama_model: str
    anthropic_model: str
    anthropic_api_key_present: bool = False
    # Informational — tells the user which value is actually in effect.
    env_overrides: list[str] = Field(default_factory=list)


class LLMSettingsUpdate(BaseModel):
    """Payload the UI sends. Only non-null fields are written."""
    provider: str | None = None
    ollama_host: str | None = None
    ollama_model: str | None = None
    anthropic_model: str | None = None
    anthropic_api_key: str | None = None  # full value, stored in chmod-600 config.yml
    clear_anthropic_api_key: bool = False


def build_settings_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["settings"])

    @router.get("/settings", response_model=LLMSettingsView)
    async def get_settings():
        current = _cfg.load()
        overrides = []
        for env_name in (
            "M3_LLM_PROVIDER", "OLLAMA_HOST", "OLLAMA_MODEL",
            "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
        ):
            if os.environ.get(env_name):
                overrides.append(env_name)
        return LLMSettingsView(
            provider=_cfg.llm_provider(),
            ollama_host=_cfg.ollama_host(),
            ollama_model=_cfg.ollama_model(),
            anthropic_model=_cfg.anthropic_model(),
            anthropic_api_key_present=bool(
                current.llm.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
            ),
            env_overrides=overrides,
        )

    @router.put("/settings", response_model=LLMSettingsView)
    async def put_settings(body: LLMSettingsUpdate):
        if body.provider is not None and body.provider not in ("ollama", "anthropic"):
            raise HTTPException(status_code=422, detail=f"unknown provider: {body.provider!r}")

        def _mutator(c: _cfg.M3Config) -> _cfg.M3Config:
            if body.provider is not None:
                c.llm.provider = body.provider
            if body.ollama_host is not None:
                c.llm.ollama_host = body.ollama_host or None
            if body.ollama_model is not None:
                c.llm.ollama_model = body.ollama_model or None
            if body.anthropic_model is not None:
                c.llm.anthropic_model = body.anthropic_model or None
            if body.clear_anthropic_api_key:
                c.llm.anthropic_api_key = None
            elif body.anthropic_api_key is not None:
                # Empty string clears, non-empty sets.
                c.llm.anthropic_api_key = body.anthropic_api_key or None
            return c

        _cfg.update(_mutator)
        return await get_settings()

    return router
