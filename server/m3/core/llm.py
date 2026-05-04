"""
M3 LLM Provider — abstractions and implementations for LLM + embeddings.

LLMProvider handles text generation (Anthropic Claude).
EmbeddingProvider handles vector embeddings (fastembed local by default).

Providers expose capability flags so engines can pick a rich single-call path
when tool use / vision is available, and fall back to multi-call JSON-repair
loops only when they aren't.
"""

import asyncio
import base64
import json
import logging
import shutil
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import anthropic

from m3.config import EmbeddingSettings, LLMSettings

logger = logging.getLogger("m3.llm")


# --- Abstractions ---


@dataclass
class Tool:
    """A tool the LLM can invoke. input_schema is a JSON Schema object that
    the provider enforces: when present, the tool call's arguments are
    guaranteed to be valid JSON matching the schema."""
    name: str
    description: str
    input_schema: dict


@dataclass
class ToolResult:
    """Result of a forced/selected tool call. `input` is already parsed JSON."""
    tool_name: str
    input: dict
    stop_reason: str = "tool_use"
    text: str = ""  # Any text the model emitted alongside the tool call
    raw_response: dict = field(default_factory=dict)


class LLMProvider(ABC):
    # Capability flags. Engines read these to choose between a rich single-call
    # path (tool use / structured output / multimodal) and a text-only fallback.
    supports_tools: bool = False
    supports_vision: bool = False
    supports_audio: bool = False

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

    async def complete_tool(
        self,
        messages: list[dict],
        tools: list[Tool],
        system: str | None = None,
        tool_choice: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> ToolResult:
        """Invoke the model with tool definitions and return the tool call.

        If `tool_choice` names a tool, the model is forced to invoke that tool,
        which guarantees schema-valid JSON. If None, the model may choose to
        call any tool or respond as text (text is returned in ToolResult.text
        with tool_name="").

        Providers that set supports_tools=False raise NotImplementedError;
        callers are expected to check the flag and fall back to a prompt-based
        JSON path.
        """
        raise NotImplementedError("This provider does not support tool use")


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
    supports_tools = True
    supports_vision = True
    # Claude Sonnet 4+ supports audio input; keep it on by default. Callers
    # that pass audio blocks to a model that doesn't handle them will get a
    # provider error, which is the right failure mode.
    supports_audio = True

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

    async def complete_tool(
        self,
        messages: list[dict],
        tools: list[Tool],
        system: str | None = None,
        tool_choice: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> ToolResult:
        anth_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]
        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "tools": anth_tools,
        }
        if system:
            kwargs["system"] = system
        if tool_choice:
            kwargs["tool_choice"] = {"type": "tool", "name": tool_choice}

        response = await self.client.messages.create(**kwargs)

        text_parts: list[str] = []
        tool_name = ""
        tool_input: dict = {}
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "tool_use":
                tool_name = block.name
                tool_input = block.input if isinstance(block.input, dict) else {}
            elif btype == "text":
                text_parts.append(block.text)

        return ToolResult(
            tool_name=tool_name,
            input=tool_input,
            stop_reason=response.stop_reason or "end_turn",
            text="".join(text_parts),
        )


# --- OpenAI-compatible implementation (MiniMax, OpenRouter, Groq, Together, Ollama, etc.) ---


class OpenAICompatibleProvider(LLMProvider):
    """Works with any provider that speaks the OpenAI chat completions API.

    Tool/vision support varies per endpoint. Cloud vendors (OpenAI, Groq,
    OpenRouter, Together) support function calling; many self-hosted setups
    (plain Ollama, llama.cpp) do not. Capability flags can be overridden via
    constructor arguments; the conservative default is "no tools, no vision"
    so a misconfigured local endpoint falls back to the JSON-repair path
    instead of crashing.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        supports_tools: bool = False,
        supports_vision: bool = False,
    ):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.supports_tools = supports_tools
        self.supports_vision = supports_vision

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

    async def complete_tool(
        self,
        messages: list[dict],
        tools: list[Tool],
        system: str | None = None,
        tool_choice: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> ToolResult:
        if not self.supports_tools:
            raise NotImplementedError(
                "This openai_compatible endpoint is not configured with tool support"
            )

        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(self._normalize_messages(messages))

        choice: str | dict = "auto"
        if tool_choice:
            choice = {"type": "function", "function": {"name": tool_choice}}

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=openai_tools,
            tool_choice=choice,
        )
        msg = response.choices[0].message
        tool_name = ""
        tool_input: dict = {}
        if getattr(msg, "tool_calls", None):
            call = msg.tool_calls[0]
            tool_name = call.function.name
            try:
                tool_input = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                tool_input = {}

        return ToolResult(
            tool_name=tool_name,
            input=tool_input,
            stop_reason=response.choices[0].finish_reason or "stop",
            text=msg.content or "",
        )

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


# --- Local agent (BYO installed AI CLI, e.g. `claude` from Claude Code) ---


# Keep this in sync with detect_local_agents() and the Settings UI.
LOCAL_AGENTS: list[dict] = [
    {"id": "claude_code", "command": "claude", "label": "Claude Code"},
    {"id": "codex", "command": "codex", "label": "OpenAI Codex CLI"},
    {"id": "gemini", "command": "gemini", "label": "Gemini CLI"},
]


def detect_local_agents() -> list[dict]:
    """Probe PATH for AI CLIs M3 can drive without an API key."""
    out: list[dict] = []
    for spec in LOCAL_AGENTS:
        path = shutil.which(spec["command"])
        out.append({
            "id": spec["id"],
            "command": spec["command"],
            "label": spec["label"],
            "available": bool(path),
            "path": path,
        })
    return out


class LocalAgentProvider(LLMProvider):
    """Drive the user's locally installed AI CLI as the LLM backend.

    The default target is `claude` (Claude Code). Authentication piggybacks on
    the user's existing login, so a Max-plan subscriber gets full quality
    without provisioning a separate API key.

    Tool use and vision are off because not every CLI exposes them uniformly;
    the compilation engine falls back to its text-only JSON-repair path. That
    is the same path it uses for non-tool OpenAI-compatible providers.
    """

    supports_tools = False
    supports_vision = False
    supports_audio = False

    def __init__(
        self,
        command: str = "claude",
        args: list[str] | None = None,
        model: str | None = None,
    ):
        if not shutil.which(command):
            raise RuntimeError(
                f"local agent '{command}' not found on PATH. Install it or pick a different provider."
            )
        self.command = command
        # `-p` runs Claude Code non-interactively and prints the response.
        # Other CLIs share this convention; override via config if needed.
        self.args = args if args is not None else ["-p"]
        self.model = model or command

    @staticmethod
    def _flatten(messages: list[dict], system: str | None) -> str:
        parts: list[str] = []
        if system:
            parts.append(f"[system]\n{system}")
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "\n".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            parts.append(f"[{role}]\n{content}")
        return "\n\n".join(parts)

    async def complete(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        prompt = self._flatten(messages, system)
        proc = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(prompt.encode())
        if proc.returncode != 0:
            raise RuntimeError(
                f"local agent '{self.command}' failed (exit {proc.returncode}): "
                f"{stderr.decode(errors='replace').strip()}"
            )
        return stdout.decode(errors="replace")

    async def complete_stream(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        prompt = self._flatten(messages, system)
        proc = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if proc.stdin:
            proc.stdin.write(prompt.encode())
            await proc.stdin.drain()
            proc.stdin.close()
        assert proc.stdout is not None
        while True:
            chunk = await proc.stdout.read(256)
            if not chunk:
                break
            yield chunk.decode(errors="replace")
        ret = await proc.wait()
        if ret != 0:
            err = b""
            if proc.stderr:
                err = await proc.stderr.read()
            raise RuntimeError(
                f"local agent stream failed (exit {ret}): "
                f"{err.decode(errors='replace').strip()}"
            )


# --- Unconfigured fallback ---------------------------------------------------
# Used when the configured provider can't be instantiated (no API key, missing
# CLI binary, etc.). We boot the server cleanly with this in place so the user
# can pick a real provider in Settings without hitting a 500 on every request.


class UnconfiguredProvider(LLMProvider):
    """Placeholder provider returned when no LLM is configured.

    Every method raises a clear, user-facing error pointing the user at
    Settings. The server still starts, the UI still loads, and Settings can
    detect this state via the `configured: false` flag on /api/v1/settings/llm.
    """

    supports_tools = False
    supports_vision = False
    supports_audio = False

    def __init__(self, reason: str = "no provider configured"):
        self.reason = reason
        self.model = "(unconfigured)"

    def _fail(self) -> None:
        raise RuntimeError(
            f"No LLM is configured ({self.reason}). "
            "Open Settings and pick an installed agent or add an API key."
        )

    async def complete(self, *args, **kwargs) -> str:
        self._fail()
        raise AssertionError("unreachable")

    async def complete_stream(self, *args, **kwargs):
        self._fail()
        if False:  # pragma: no cover -- generator marker
            yield ""

    async def complete_tool(self, *args, **kwargs):
        self._fail()
        raise AssertionError("unreachable")


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


def _build_provider(provider_config) -> LLMProvider:
    """Construct the provider described by `provider_config`. May raise if the
    config refers to a CLI binary that isn't on PATH or an API key that's
    missing -- callers should catch and degrade to UnconfiguredProvider."""
    if provider_config.type == "anthropic":
        if not provider_config.api_key:
            raise RuntimeError("anthropic provider has no api_key")
        return AnthropicProvider(api_key=provider_config.api_key, model=provider_config.model)

    if provider_config.type == "openai_compatible":
        if not provider_config.base_url:
            raise RuntimeError("openai_compatible provider requires a base_url")
        is_local = "localhost" in provider_config.base_url or "127.0.0.1" in provider_config.base_url
        if not provider_config.api_key and not is_local:
            raise RuntimeError("openai_compatible provider has no api_key")
        return OpenAICompatibleProvider(
            api_key=provider_config.api_key,
            model=provider_config.model,
            base_url=provider_config.base_url,
            supports_tools=provider_config.supports_tools,
            supports_vision=provider_config.supports_vision,
        )

    if provider_config.type == "local_agent":
        return LocalAgentProvider(
            command=provider_config.command or "claude",
            args=list(provider_config.args) if provider_config.args else None,
            model=provider_config.model,
        )

    raise RuntimeError(f"unknown LLM provider type: {provider_config.type}")


def create_llm_provider(settings: LLMSettings) -> LLMProvider:
    """Build the active LLM provider, or return an UnconfiguredProvider if it
    can't be instantiated. The server always starts -- the UI surfaces the
    unconfigured state and prompts the user to pick a provider in Settings."""
    provider_config = settings.providers.get(settings.default_provider)
    if not provider_config:
        logger.warning(
            "no provider entry for '%s'; starting in unconfigured state",
            settings.default_provider,
        )
        return UnconfiguredProvider(f"provider '{settings.default_provider}' not defined")

    try:
        return _build_provider(provider_config)
    except Exception as exc:
        logger.warning(
            "could not initialize '%s' (%s); starting in unconfigured state. "
            "Pick a provider in Settings.",
            settings.default_provider, exc,
        )
        return UnconfiguredProvider(str(exc))


def create_embedding_provider(settings: EmbeddingSettings) -> EmbeddingProvider:
    if settings.provider == "fastembed":
        return FastEmbedProvider(model=settings.model, dim=settings.dimensions)

    raise ValueError(f"Unknown embedding provider: {settings.provider}")
