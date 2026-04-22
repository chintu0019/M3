"""Agent loop: LLM + BrainTools = grounded Q&A over the user's brain.

The loop emits an async stream of AgentEvent records so callers (HTTP SSE,
CLI REPL, tests) can render progress incrementally.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from m3.core.llm import LLMProvider, Tool
from m3.core.tools import BrainTools

logger = logging.getLogger("m3.agent")

MAX_TOOL_ROUNDS = 5

SYSTEM_PROMPT = """You are M3, a personal brain. You answer questions grounded in the user's own notes.

Rules:
- Always try a brain tool first (search_brain, open_item, open_entity, list_open_questions) before answering from parametric knowledge.
- Cite items you drew from in your final answer: `[^<item_id>]`.
- If the tools return nothing relevant, say so — don't invent.
- Keep answers concise. The user reads on a phone or laptop.
- You have at most 5 tool rounds, so pick queries carefully."""


@dataclass
class AgentEvent:
    type: str                 # "tool_call" | "tool_result" | "final" | "error"
    content: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] | None = None
    tool_result: Any | None = None


async def run_agent(
    *, llm: LLMProvider, tools: BrainTools, user_message: str,
    history: list[dict] | None = None,
) -> AsyncIterator[AgentEvent]:
    tool_objs = [Tool(name=s["name"], description=s["description"], input_schema=s["input_schema"])
                 for s in tools.schemas()]
    messages: list[dict] = list(history or []) + [{"role": "user", "content": user_message}]

    for round_idx in range(MAX_TOOL_ROUNDS):
        result = await llm.complete_tool(
            messages=messages, tools=tool_objs, system=SYSTEM_PROMPT,
            tool_choice=None,                      # let the LLM decide
            max_tokens=2048, temperature=0.2,
        )
        # If the LLM didn't call a tool, its `text` is the final answer.
        if not result.tool_name:
            yield AgentEvent(type="final", content=result.text or "(no answer)")
            return

        tool_name = result.tool_name
        tool_input = result.input or {}
        yield AgentEvent(type="tool_call", tool_name=tool_name, tool_input=tool_input)

        tool_result = await tools.dispatch(tool_name, tool_input)
        yield AgentEvent(type="tool_result", tool_name=tool_name, tool_result=tool_result)

        # Record the tool round in the conversation so the next LLM call sees it.
        import json as _json
        messages.append({"role": "assistant", "content": f"[called {tool_name} with {_json.dumps(tool_input)}]"})
        messages.append({"role": "user", "content": f"[tool:{tool_name}] result:\n{_json.dumps(tool_result)[:4000]}"})

    # Ran out of rounds — force a final answer from what we have.
    forced = await llm.complete_tool(
        messages=messages + [{"role": "user", "content": "You've used your tool rounds. Give your best answer now, no more tool calls."}],
        tools=[], system=SYSTEM_PROMPT, tool_choice=None,
        max_tokens=1024, temperature=0.2,
    )
    yield AgentEvent(type="final", content=forced.text or "(tool round limit reached)")
