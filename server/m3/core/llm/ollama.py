"""Ollama provider.

Uses Ollama's native tools API when the selected model supports it, falls back
to a JSON-schema-in-prompt path when the model returns a free-form response.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from m3.core.llm._json_tool import (
    build_tool_prompt,
    parse_tool_response,
    recover_stringified_payload,
    satisfies_required,
)
from m3.core.llm.base import LLMProvider, Message, Tool, ToolResult
from m3.core.llm_log import LLMCall, now_iso, prompt_chars, record

logger = logging.getLogger("m3.llm.ollama")


class OllamaProvider(LLMProvider):
    supports_tools = True
    supports_vision = False
    supports_audio = False

    def __init__(self, host: str = "http://localhost:11434", model: str = "qwen2.5:7b") -> None:
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
        started = time.monotonic()
        status = "ok"
        try:
            r = await self._client.post("/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
            return data["message"]["content"]
        except Exception as e:
            status = f"error:{type(e).__name__}"
            raise
        finally:
            # Ollama's /api/chat doesn't reliably report token usage; leave
            # input/output_tokens as None and fall back to prompt_chars for
            # rough sizing.
            await record(LLMCall(
                ts=now_iso(), provider="ollama", model=self._model,
                method="complete", prompt_chars=prompt_chars(messages),
                latency_ms=int((time.monotonic() - started) * 1000),
                status=status,
            ))

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
        started = time.monotonic()
        status = "ok"
        try:
            return await self._complete_tool_impl(
                messages, tools, system, tool_choice, max_tokens, temperature,
            )
        except Exception as e:
            status = f"error:{type(e).__name__}"
            raise
        finally:
            await record(LLMCall(
                ts=now_iso(), provider="ollama", model=self._model,
                method="complete_tool", prompt_chars=prompt_chars(messages),
                latency_ms=int((time.monotonic() - started) * 1000),
                status=status,
            ))

    async def _complete_tool_impl(
        self,
        messages: list[Message],
        tools: list[Tool],
        system: str | None,
        tool_choice: str | None,
        max_tokens: int,
        temperature: float,
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
        tool_by_name = {t.name: t for t in tools}
        chosen = tool_by_name.get(tool_choice or "") or tools[0]
        if tool_calls:
            call = tool_calls[0]
            fn = call.get("function", {})
            args = fn.get("arguments") or {}
            args = recover_stringified_payload(args, chosen.input_schema)
            if satisfies_required(args, chosen.input_schema):
                return ToolResult(
                    tool_name=fn.get("name", tool_choice or ""),
                    input=args,
                    stop_reason="tool_use",
                    text="",
                    raw_response=data,
                )
            logger.warning(
                "ollama: tool_calls returned but missing required schema keys; falling back"
            )
        else:
            logger.warning("ollama: no tool_calls; falling back to JSON-in-prompt parse")

        repair_prompt = build_tool_prompt(chosen)
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
        return parse_tool_response(text, chosen, raw_response=r2.json())
