"""Ollama provider.

Uses Ollama's native tools API when the selected model supports it, falls back
to a JSON-schema-in-prompt path when the model returns a free-form response.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from m3.core.llm.base import LLMProvider, Message, Tool, ToolResult

logger = logging.getLogger("m3.llm.ollama")


class OllamaProvider(LLMProvider):
    supports_tools = True
    supports_vision = False
    supports_audio = False

    def __init__(self, host: str = "http://localhost:11434", model: str = "qwen2.5:14b") -> None:
        self._host = host.rstrip("/")
        self._model = model
        self._client = httpx.AsyncClient(base_url=self._host, timeout=httpx.Timeout(120.0, read=120.0))

    async def complete(
        self,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "stream": False,
        }
        r = await self._client.post("/api/chat", json=payload)
        r.raise_for_status()
        data = r.json()
        return data["message"]["content"]

    async def complete_stream(
        self,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "stream": True,
        }
        async with self._client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                piece = chunk.get("message", {}).get("content", "")
                if piece:
                    yield piece
                if chunk.get("done"):
                    break

    async def complete_tool(
        self,
        messages: list[Message],
        tools: list[Tool],
        system: str | None = None,
        tool_choice: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> ToolResult:
        # Prefer Ollama's native tools API. If the model returns a free-form response,
        # fall back to JSON-schema-in-prompt extraction below.
        tools_payload = [
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
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "tools": tools_payload,
            "stream": False,
        }
        r = await self._client.post("/api/chat", json=payload)
        r.raise_for_status()
        data = r.json()
        tool_calls = data.get("message", {}).get("tool_calls") or []
        if tool_calls:
            call = tool_calls[0]
            fn = call.get("function", {})
            return ToolResult(
                tool_name=fn.get("name", tool_choice or ""),
                input=fn.get("arguments") or {},
                stop_reason="tool_use",
                text="",
                raw_response=data,
            )

        logger.warning("ollama: no tool_calls; falling back to JSON-in-prompt parse")
        tool_by_name = {t.name: t for t in tools}
        chosen = tool_by_name.get(tool_choice or "") or tools[0]
        schema_str = json.dumps(chosen.input_schema, indent=2)
        repair_prompt = (
            f"Call the `{chosen.name}` tool. Reply with valid JSON only matching this schema:\n"
            f"{schema_str}\nNo prose, no fences."
        )
        r2 = await self._client.post(
            "/api/chat",
            json={
                "model": self._model,
                "messages": (
                    ([{"role": "system", "content": system}] if system else [])
                    + messages
                    + [{"role": "user", "content": repair_prompt}]
                ),
                "options": {"temperature": 0.0, "num_predict": max_tokens},
                "stream": False,
            },
        )
        r2.raise_for_status()
        text = r2.json()["message"]["content"]
        parsed = _parse_json(text)
        return ToolResult(
            tool_name=chosen.name,
            input=parsed,
            stop_reason="tool_use",
            text="",
            raw_response=r2.json(),
        )


def _parse_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        return json.loads(text[start : end + 1])
    raise ValueError(f"could not parse JSON from Ollama response: {text[:200]}")
