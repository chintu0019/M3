"""JSONL log of every LLM call, written to ~/.local/state/m3/llm-calls.jsonl.

One line per call. Fields:
  ts             — ISO timestamp
  provider       — ollama | anthropic | openai | fake
  model          — model id as configured
  method         — complete | complete_tool
  prompt_chars   — best-effort char count of the messages payload
  input_tokens   — from provider response usage, if reported; else None
  output_tokens  — from provider response usage, if reported; else None
  latency_ms     — wall-clock
  status         — ok | error:<short>

Writer is async-safe via a single lock. File rolls forever (we don't rotate;
user can archive).
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG_DIR = Path.home() / ".local" / "state" / "m3"


def log_path() -> Path:
    base = Path(os.environ.get("M3_LOG_DIR", str(DEFAULT_LOG_DIR)))
    base.mkdir(parents=True, exist_ok=True)
    return base / "llm-calls.jsonl"


@dataclass
class LLMCall:
    ts: str
    provider: str
    model: str
    method: str                    # complete | complete_tool
    prompt_chars: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int = 0
    status: str = "ok"


_lock = asyncio.Lock()


async def record(call: LLMCall) -> None:
    line = json.dumps(asdict(call)) + "\n"
    async with _lock:
        # Append-only, sync I/O inside the lock is fine — lines are small.
        with log_path().open("a", encoding="utf-8") as fh:
            fh.write(line)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def prompt_chars(messages: list[dict]) -> int:
    """Best-effort char count across the messages payload. Anthropic-style
    content blocks (list[dict]) are flattened by concatenating their text."""
    total = 0
    for m in messages or ():
        c = m.get("content", "")
        if isinstance(c, str):
            total += len(c)
        elif isinstance(c, list):
            for block in c:
                if isinstance(block, dict):
                    t = block.get("text")
                    if isinstance(t, str):
                        total += len(t)
    return total
