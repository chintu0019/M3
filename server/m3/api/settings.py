"""
M3 Settings API -- full CRUD for LLM providers, persisted via user_settings.json.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from m3.api.deps import verify_auth
from m3.config import LLMProviderConfig
from m3.core.engines.loader import load_engine
from m3.core.llm import create_llm_provider, detect_local_agents
from m3.schemas.api import SelfContextSettings, ThemeSetting
from m3.storage.user_settings import UserSettingsStore

logger = logging.getLogger("m3.settings")

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


# --- Schemas ---


class ProviderInfo(BaseModel):
    name: str
    type: str
    model: str
    base_url: str | None = None
    has_api_key: bool
    active: bool


class LLMSettingsResponse(BaseModel):
    active_provider: str
    providers: list[ProviderInfo]


class SwitchProviderRequest(BaseModel):
    provider: str


class ProviderCreateRequest(BaseModel):
    name: str
    type: str = "openai_compatible"  # anthropic | openai_compatible | local_agent
    model: str
    api_key: str = ""
    base_url: str | None = None
    command: str | None = None
    args: list[str] = []


class ProviderUpdateRequest(BaseModel):
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    command: str | None = None
    args: list[str] | None = None


# --- Helpers ---


def _build_response(request: Request) -> LLMSettingsResponse:
    """Build the standard LLM settings response from current state."""
    settings = request.app.state.settings
    active = settings.llm.default_provider
    providers = []
    for name, config in settings.llm.providers.items():
        providers.append(ProviderInfo(
            name=name,
            type=config.type,
            model=config.model,
            base_url=config.base_url,
            has_api_key=bool(config.api_key),
            active=(name == active),
        ))
    return LLMSettingsResponse(active_provider=active, providers=providers)


def _rebuild_llm(request: Request) -> None:
    """Rebuild the LLM provider and compilation engine from current settings."""
    settings = request.app.state.settings
    new_llm = create_llm_provider(settings.llm)
    request.app.state.llm = new_llm
    request.app.state.engine = load_engine(settings.processing, new_llm)


# --- Endpoints ---


@router.get("/llm", response_model=LLMSettingsResponse)
async def get_llm_settings(
    request: Request,
    _auth: str = Depends(verify_auth),
):
    """Return available LLM providers and which one is active."""
    return _build_response(request)


@router.put("/llm/switch", response_model=LLMSettingsResponse)
async def switch_provider(
    body: SwitchProviderRequest,
    request: Request,
    _auth: str = Depends(verify_auth),
):
    """Switch the active LLM provider."""
    settings = request.app.state.settings
    store = request.app.state.user_store

    if body.provider not in settings.llm.providers:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{body.provider}' not found. "
                   f"Available: {list(settings.llm.providers.keys())}",
        )

    config = settings.llm.providers[body.provider]
    is_local_url = config.base_url and ("localhost" in config.base_url or "127.0.0.1" in config.base_url)
    is_local_agent = config.type == "local_agent"
    if not config.api_key and not is_local_url and not is_local_agent:
        raise HTTPException(status_code=400, detail=f"Provider '{body.provider}' has no API key set.")

    settings.llm.default_provider = body.provider
    store.set_active_provider(body.provider)
    _rebuild_llm(request)

    logger.info(f"Switched to provider '{body.provider}' ({config.model})")
    return _build_response(request)


@router.post("/llm/providers", response_model=LLMSettingsResponse, status_code=201)
async def add_provider(
    body: ProviderCreateRequest,
    request: Request,
    _auth: str = Depends(verify_auth),
):
    """Add a new LLM provider."""
    settings = request.app.state.settings
    store = request.app.state.user_store

    if body.name in settings.llm.providers:
        raise HTTPException(status_code=409, detail=f"Provider '{body.name}' already exists.")

    if body.type not in ("anthropic", "openai_compatible", "local_agent"):
        raise HTTPException(
            status_code=400,
            detail="Type must be 'anthropic', 'openai_compatible', or 'local_agent'.",
        )

    if body.type == "openai_compatible" and not body.base_url:
        raise HTTPException(status_code=400, detail="openai_compatible providers require a base_url.")

    if body.type == "local_agent" and not body.command:
        raise HTTPException(status_code=400, detail="local_agent providers require a command (e.g. 'claude').")

    # Add to in-memory settings
    provider_config = LLMProviderConfig(
        type=body.type,
        api_key=body.api_key,
        model=body.model,
        base_url=body.base_url,
        command=body.command,
        args=body.args,
    )
    settings.llm.providers[body.name] = provider_config

    # Persist
    store.set_provider(body.name, {
        "type": body.type,
        "api_key": body.api_key,
        "model": body.model,
        "base_url": body.base_url,
        "command": body.command,
        "args": body.args,
    })

    logger.info(f"Added provider '{body.name}' ({body.type}, {body.model})")
    return _build_response(request)


@router.put("/llm/providers/{name}", response_model=LLMSettingsResponse)
async def update_provider(
    name: str,
    body: ProviderUpdateRequest,
    request: Request,
    _auth: str = Depends(verify_auth),
):
    """Update an existing provider's config."""
    settings = request.app.state.settings
    store = request.app.state.user_store

    if name not in settings.llm.providers:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found.")

    config = settings.llm.providers[name]

    if body.model is not None:
        config.model = body.model
    if body.api_key is not None:
        config.api_key = body.api_key
    if body.base_url is not None:
        config.base_url = body.base_url
    if body.command is not None:
        config.command = body.command
    if body.args is not None:
        config.args = body.args

    # Persist
    store.set_provider(name, {
        "type": config.type,
        "api_key": config.api_key,
        "model": config.model,
        "base_url": config.base_url,
        "command": config.command,
        "args": config.args,
    })

    # If this is the active provider, rebuild LLM
    if name == settings.llm.default_provider:
        _rebuild_llm(request)

    logger.info(f"Updated provider '{name}'")
    return _build_response(request)


@router.delete("/llm/providers/{name}", response_model=LLMSettingsResponse)
async def delete_provider(
    name: str,
    request: Request,
    _auth: str = Depends(verify_auth),
):
    """Delete a provider."""
    settings = request.app.state.settings
    store = request.app.state.user_store

    if name not in settings.llm.providers:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found.")

    if name == settings.llm.default_provider:
        raise HTTPException(status_code=400, detail="Cannot delete the active provider. Switch first.")

    del settings.llm.providers[name]
    store.delete_provider(name)

    logger.info(f"Deleted provider '{name}'")
    return _build_response(request)


# --- Local agents (BYO installed AI CLI) ---


class LocalAgentInfo(BaseModel):
    id: str
    command: str
    label: str
    available: bool
    path: str | None = None


@router.get("/agents", response_model=list[LocalAgentInfo])
async def list_local_agents(_auth: str = Depends(verify_auth)):
    """Probe PATH for AI CLIs M3 can drive without an API key.

    The Settings UI uses this to render a "use my installed agent" option.
    """
    return detect_local_agents()


# --- Self-context (Phase D) ---


@router.get("/self-context", response_model=SelfContextSettings)
async def get_self_context_settings(
    request: Request,
    _auth: str = Depends(verify_auth),
):
    store: UserSettingsStore = request.app.state.user_store
    return SelfContextSettings(enabled=store.get_self_context_enabled())


@router.put("/self-context", response_model=SelfContextSettings)
async def set_self_context_settings(
    body: SelfContextSettings,
    request: Request,
    _auth: str = Depends(verify_auth),
):
    store: UserSettingsStore = request.app.state.user_store
    store.set_self_context_enabled(body.enabled)
    return SelfContextSettings(enabled=store.get_self_context_enabled())


# --- Theme (Phase E) ---


@router.get("/theme", response_model=ThemeSetting)
async def get_theme_setting(
    request: Request,
    _auth: str = Depends(verify_auth),
):
    store: UserSettingsStore = request.app.state.user_store
    return ThemeSetting(theme=store.get_theme())


@router.put("/theme", response_model=ThemeSetting)
async def set_theme_setting(
    body: ThemeSetting,
    request: Request,
    _auth: str = Depends(verify_auth),
):
    store: UserSettingsStore = request.app.state.user_store
    try:
        store.set_theme(body.theme)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ThemeSetting(theme=store.get_theme())
