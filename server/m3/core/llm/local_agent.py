"""LLM provider that shells out to a user-installed AI CLI.

The class is CLI-agnostic: any binary that "accepts text on stdin, emits text
on stdout" works. Authentication piggybacks on the user's existing CLI login,
so a Claude Code Max subscriber, a Codex Plus user, or someone with a Gemini
CLI logged in can drive M3 with no separate API key.

The curated ``KNOWN_AGENTS`` table powers the Settings picker and the
``/api/v1/settings/agents`` detection endpoint. Adding a new agent there
makes it appear in the UI; the provider class itself never needs to change.

Tool use: the CLI doesn't have a native tools API, so ``complete_tool``
falls back to the same JSON-in-prompt path OllamaProvider uses
(``m3.core.llm._json_tool``). Brittle in the same ways Ollama is, but lets
the agent loop in ``core/agent.py`` and the structured extraction in
``core/ingest.py`` keep working without per-call guards.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections.abc import AsyncIterator
from typing import Any

from m3.core.llm._json_tool import build_tool_prompt, parse_tool_response
from m3.core.llm.base import LLMProvider, Message, Tool, ToolResult
from m3.core.llm_log import LLMCall, now_iso, prompt_chars, record

logger = logging.getLogger("m3.llm.local_agent")


# The curated list of CLIs the Settings UI offers as one-click "Use this"
# rows. Adding an entry here is the only change needed to surface a new
# agent in the picker. Users can still point at any other binary via the
# "Custom command" form -- detection is just discovery convenience.
KNOWN_AGENTS: list[dict[str, Any]] = [
    {
        "id": "claude_code",
        "command": "claude",
        "label": "Claude Code (Anthropic)",
        "default_args": ["-p"],
    },
    {
        "id": "codex",
        "command": "codex",
        "label": "Codex (OpenAI)",
        "default_args": ["exec"],
    },
    {
        "id": "gemini",
        "command": "gemini",
        "label": "Gemini CLI (Google)",
        # `-p ""`        — gemini's `-p/--prompt` is a string-valued flag;
        #                  empty prompt + stdin works headlessly.
        # `--skip-trust` — gemini refuses to run outside an interactively-
        #                  trusted workspace, which never applies to a
        #                  subprocess. The flag opts into single-session
        #                  trust for headless invocations.
        "default_args": ["-p", "", "--skip-trust"],
    },
    {
        "id": "aider",
        "command": "aider",
        "label": "Aider",
        "default_args": ["--no-stream", "--message"],
    },
    {
        "id": "mods",
        "command": "mods",
        "label": "mods (Charm)",
        "default_args": [],
    },
    {
        "id": "llm",
        "command": "llm",
        "label": "llm (Simon Willison)",
        "default_args": [],
    },
]


def detect_local_agents() -> list[dict[str, Any]]:
    """For each entry in ``KNOWN_AGENTS`` probe ``$PATH`` and report which CLIs
    are installed. Returned shape is what ``GET /api/v1/settings/agents``
    serializes."""
    out: list[dict[str, Any]] = []
    for spec in KNOWN_AGENTS:
        path = shutil.which(spec["command"])
        out.append({
            "id": spec["id"],
            "command": spec["command"],
            "label": spec["label"],
            "default_args": list(spec["default_args"]),
            "available": bool(path),
            "path": path,
        })
    return out


def _flatten_messages(messages: list[Message], system: str | None) -> str:
    """Collapse a chat-style message list into a single text prompt the CLI
    can consume on stdin. CLIs vary in how they accept multi-turn input, so
    we use the most portable shape: tagged role blocks."""
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


class LocalAgentProvider(LLMProvider):
    # We claim tool support and emulate it via ``_json_tool`` so the chat agent
    # loop and structured extraction (both call ``complete_tool`` unconditionally)
    # keep working. Vision / audio aren't routable through stdin so stay False;
    # callers that need those should pick Anthropic.
    supports_tools = True
    supports_vision = False
    supports_audio = False

    def __init__(
        self,
        command: str = "claude",
        args: list[str] | None = None,
        model: str | None = None,
    ) -> None:
        if not shutil.which(command):
            raise RuntimeError(
                f"local agent '{command}' not found on PATH. "
                f"Install it or pick a different provider in Settings."
            )
        self.command = command
        # ``-p`` is Claude Code's non-interactive flag and a sensible default
        # for several other CLIs. An explicit empty list is honored (some
        # CLIs like `mods` and `llm` take the prompt directly without flags).
        self.args: list[str] = list(args) if args is not None else ["-p"]
        # Used as the human-readable label in the "active model" UI chip.
        self._model = model or command

    @property
    def model(self) -> str:
        return self._model

    async def _run(self, prompt: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(prompt.encode())
        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip() or "(no stderr)"
            raise RuntimeError(
                f"local agent '{self.command}' failed (exit {proc.returncode}): {err}"
            )
        return stdout.decode(errors="replace")

    async def complete(
        self,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        prompt = _flatten_messages(messages, system)
        started = time.monotonic()
        status = "ok"
        try:
            return await self._run(prompt)
        except Exception as e:
            status = f"error:{type(e).__name__}"
            raise
        finally:
            await record(LLMCall(
                ts=now_iso(), provider="local_agent", model=self._model,
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
        # Most CLIs print the full response on completion rather than
        # token-streaming. We run the subprocess to completion and yield the
        # body as one chunk; the chat UI already handles single-chunk SSE.
        text = await self.complete(messages, system=system, max_tokens=max_tokens, temperature=temperature)
        if text:
            yield text

    async def complete_tool(
        self,
        messages: list[Message],
        tools: list[Tool],
        system: str | None = None,
        tool_choice: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> ToolResult:
        # Pick the requested tool if specified, otherwise the first one --
        # mirrors OllamaProvider's behavior so callers get the same shape.
        tool_by_name = {t.name: t for t in tools}
        chosen = tool_by_name.get(tool_choice or "") or tools[0]

        repair_prompt = build_tool_prompt(chosen)
        prompt = _flatten_messages(
            list(messages) + [{"role": "user", "content": repair_prompt}],
            system,
        )
        started = time.monotonic()
        status = "ok"
        try:
            text = await self._run(prompt)
            try:
                return parse_tool_response(text, chosen, raw_response={"text": text})
            except ValueError:
                # The CLI replied with prose instead of a tool-call JSON. That's
                # the model's way of saying "I have an answer, I don't need a
                # tool" — return an empty-toolname ToolResult so run_agent
                # promotes `text` to the final answer rather than crashing the
                # whole turn with an error event.
                status = "fallback:plain_text"
                logger.info("local_agent: prose response, falling back to final-answer text")
                return ToolResult(
                    tool_name="",
                    input={},
                    stop_reason="end_turn",
                    text=text,
                    raw_response={"text": text},
                )
        except Exception as e:
            status = f"error:{type(e).__name__}"
            logger.warning("local_agent complete_tool failed: %s", e)
            raise
        finally:
            await record(LLMCall(
                ts=now_iso(), provider="local_agent", model=self._model,
                method="complete_tool", prompt_chars=prompt_chars(messages),
                latency_ms=int((time.monotonic() - started) * 1000),
                status=status,
            ))


__all__ = ["LocalAgentProvider", "KNOWN_AGENTS", "detect_local_agents"]
