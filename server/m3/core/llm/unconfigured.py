"""Placeholder LLM provider used when no real one can be built.

The factory in ``m3.app._make_llm`` returns this when the user's selected
provider can't be instantiated -- missing API key, ``claude`` binary not on
PATH, unknown provider name, etc. The server boots cleanly and the UI
surfaces a "pick one" CTA instead of letting users hit a 500 on their first
chat.

Every method raises a single user-facing ``RuntimeError`` pointing at
Settings. Callers (the chat router, settings endpoint) special-case
``isinstance(llm, UnconfiguredProvider)`` to render the empty state up
front rather than letting the error propagate as a generic SSE error event.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from m3.core.llm.base import LLMProvider, Message, Tool, ToolResult


class UnconfiguredProvider(LLMProvider):
    supports_tools = False
    supports_vision = False
    supports_audio = False

    def __init__(self, reason: str = "no provider configured") -> None:
        self.reason = reason
        # Surfaced in UI labels alongside other providers' model names.
        self._model = "(unconfigured)"

    @property
    def model(self) -> str:
        return self._model

    def _fail(self) -> None:
        raise RuntimeError(
            f"No LLM is configured ({self.reason}). "
            "Open Settings and pick an installed agent or add an API key."
        )

    async def complete(
        self,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        self._fail()
        raise AssertionError("unreachable")  # pragma: no cover

    async def complete_stream(
        self,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        # The ``if False: yield`` marker keeps this defined as an async
        # generator (so callers can ``async for`` over it) while still
        # raising before any chunks are produced.
        self._fail()
        if False:  # pragma: no cover
            yield ""

    async def complete_tool(
        self,
        messages: list[Message],
        tools: list[Tool],
        system: str | None = None,
        tool_choice: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> ToolResult:
        self._fail()
        raise AssertionError("unreachable")  # pragma: no cover


__all__ = ["UnconfiguredProvider"]
