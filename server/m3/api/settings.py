"""GET + PUT /api/v1/settings — LLM provider configuration.

The UI reads the effective settings (env > config.yml > default) and writes
changes to ~/.config/m3/config.yml. Since _make_llm is called per-request and
re-reads config on each call, a setting change takes effect on the NEXT
incoming request without a server restart.

The API key is stored in the chmod-600 config file but never returned on
read — the UI only sees a boolean presence flag. env_overrides surfaces any
env vars that would win over config.yml, so users can tell when their saved
setting isn't being used because an env var is shadowing it.

Also exposes ``configured`` / ``unconfigured_reason`` so the UI can render
an empty-state CTA when the active provider can't be built (no API key,
missing CLI binary, etc.) instead of letting users hit an error on first
chat. ``GET /api/v1/settings/agents`` lists installed AI CLIs the
local_agent provider can wrap.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from m3.core import config as _cfg
from m3.core.llm.local_agent import detect_local_agents
from m3.core.llm.unconfigured import UnconfiguredProvider


class LLMSettingsView(BaseModel):
    """What the UI sees. api_key is redacted."""
    provider: str
    ollama_host: str
    ollama_model: str
    anthropic_model: str
    anthropic_api_key_present: bool = False
    # local_agent: the CLI binary M3 will subprocess and the args it'll
    # prepend before piping the prompt on stdin. Empty string / empty list
    # mean "fall back to defaults" (claude / ["-p"]).
    local_agent_command: str = ""
    local_agent_args: list[str] = Field(default_factory=list)
    # False when the active provider can't be built (e.g. claude CLI not on
    # PATH, anthropic with no API key). Lets the UI render a "pick one" CTA
    # instead of hitting cryptic 500s on first chat.
    configured: bool = True
    unconfigured_reason: str | None = None
    # Informational — tells the user which value is actually in effect.
    env_overrides: list[str] = Field(default_factory=list)
    # Canvas redesign feature flag — see CanvasConfig in core/config.py.
    # NOTE: this isn't strictly an LLM setting; the class name LLMSettingsView
    # is now slightly incongruous. A later refactor can rename to SettingsView
    # once more non-LLM settings land.
    canvas_v2_enabled: bool = False


class LLMSettingsUpdate(BaseModel):
    """Payload the UI sends. Only non-null fields are written."""
    provider: str | None = None
    ollama_host: str | None = None
    ollama_model: str | None = None
    anthropic_model: str | None = None
    anthropic_api_key: str | None = None  # full value, stored in chmod-600 config.yml
    clear_anthropic_api_key: bool = False
    local_agent_command: str | None = None
    local_agent_args: list[str] | None = None
    canvas_v2_enabled: bool | None = None


class LocalAgentInfo(BaseModel):
    """One row in the GET /api/v1/settings/agents response."""
    id: str
    command: str
    label: str
    default_args: list[str]
    available: bool
    path: str | None = None


def _probe_configured() -> tuple[bool, str | None]:
    """Try to build the active LLM. Return ``(configured, reason)``.

    Mirrors what _make_llm in app.py does so the UI sees the same answer the
    chat router would. Any RuntimeError from construction (missing key /
    binary / unknown provider) flips ``configured`` to False with the
    reason text the UI shows in the empty-state banner.
    """
    from m3.app import _make_llm  # local import: avoids settings -> app cycle at startup
    llm = _make_llm()
    if isinstance(llm, UnconfiguredProvider):
        return False, llm.reason
    return True, None


def build_settings_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["settings"])

    @router.get("/settings", response_model=LLMSettingsView)
    async def get_settings():
        current = _cfg.load()
        overrides = []
        for env_name in (
            "M3_LLM_PROVIDER", "OLLAMA_HOST", "OLLAMA_MODEL",
            "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
            "LOCAL_AGENT_COMMAND", "LOCAL_AGENT_ARGS",
        ):
            if os.environ.get(env_name):
                overrides.append(env_name)
        configured, reason = _probe_configured()
        return LLMSettingsView(
            provider=_cfg.llm_provider(),
            ollama_host=_cfg.ollama_host(),
            ollama_model=_cfg.ollama_model(),
            anthropic_model=_cfg.anthropic_model(),
            anthropic_api_key_present=bool(
                current.llm.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
            ),
            local_agent_command=_cfg.local_agent_command(),
            local_agent_args=_cfg.local_agent_args(),
            configured=configured,
            unconfigured_reason=reason,
            env_overrides=overrides,
            canvas_v2_enabled=_cfg.canvas_v2_enabled(),
        )

    @router.put("/settings", response_model=LLMSettingsView)
    async def put_settings(body: LLMSettingsUpdate):
        if body.provider is not None and body.provider not in (
            "ollama", "anthropic", "local_agent",
        ):
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
            if body.local_agent_command is not None:
                c.llm.local_agent_command = body.local_agent_command or None
            if body.local_agent_args is not None:
                # Honor an explicit empty list as "no args" -- needed for
                # CLIs like ``mods`` and ``llm`` that take the prompt
                # directly without flags. Sending no field at all (None)
                # leaves the previous value alone.
                c.llm.local_agent_args = list(body.local_agent_args)
            if body.canvas_v2_enabled is not None:
                c.canvas.v2 = bool(body.canvas_v2_enabled)
            return c

        _cfg.update(_mutator)
        return await get_settings()

    @router.get("/settings/agents", response_model=list[LocalAgentInfo])
    async def list_agents():
        """Probe PATH for AI CLIs M3 can wrap as the local_agent provider.

        Each entry comes from the curated KNOWN_AGENTS table in
        m3.core.llm.local_agent. The Settings UI renders one row per entry
        with a "Use this" button for available agents. Users can also point
        at any custom command via the local_agent_command field -- detection
        is just discovery convenience.
        """
        return detect_local_agents()

    return router
