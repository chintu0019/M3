"""
Anthropic and OpenAI-compatible LLM providers.

``AnthropicProvider`` speaks the Messages API directly; ``OpenAICompatibleProvider``
works with any endpoint that talks the OpenAI chat-completions API (OpenAI,
Groq, OpenRouter, Together, Ollama, llama.cpp, ...).
"""

import base64
import json
import logging
from collections.abc import AsyncIterator

import anthropic

from m3.core.llm.base import LLMProvider, Tool, ToolResult

logger = logging.getLogger("m3.llm")


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
