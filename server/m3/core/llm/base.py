"""
Abstract base classes and shared types for the M3 LLM provider package.

``LLMProvider`` is the text-generation interface; ``EmbeddingProvider`` is the
vector-embeddings interface. ``Tool`` / ``ToolResult`` describe the
tool-use protocol that providers with ``supports_tools=True`` expose.

Kept free of provider-specific imports (no ``anthropic``, no ``openai``,
no ``fastembed``) so submodules can import from here without pulling in
optional dependencies.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

Message = dict[str, Any]


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
