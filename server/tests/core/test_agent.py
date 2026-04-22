import pytest

from m3.core.agent import AgentEvent, run_agent
from m3.core.tools import BrainTools


class _Embedder:
    dim = 768
    async def embed(self, texts):
        return [[0.0] * 768 for _ in texts]


class _ScriptedLLM:
    """Emits a pre-scripted sequence of responses — one per turn."""

    supports_tools = True
    supports_vision = False
    supports_audio = False

    def __init__(self, turns: list):
        self._turns = turns
        self._i = 0

    async def complete_tool(self, *, messages, tools, system, tool_choice, max_tokens, temperature):
        from m3.core.llm.base import ToolResult
        turn = self._turns[self._i]
        self._i += 1
        if turn["type"] == "tool":
            return ToolResult(tool_name=turn["name"], input=turn.get("input", {}), text=turn.get("text", ""))
        # "final" — no tool call, just text
        return ToolResult(tool_name="", input={}, text=turn["text"])


@pytest.mark.asyncio
async def test_agent_final_message_no_tools(tmp_brain):
    tools = BrainTools(brain_root=tmp_brain, embedder=_Embedder())
    llm = _ScriptedLLM([{"type": "final", "text": "I don't need to look anything up; hello."}])
    events = []
    async for ev in run_agent(llm=llm, tools=tools, user_message="Just say hi"):
        events.append(ev)
    kinds = [e.type for e in events]
    assert "final" in kinds
    final = [e for e in events if e.type == "final"][0]
    assert "hello" in final.content


@pytest.mark.asyncio
async def test_agent_invokes_tool_and_uses_result(tmp_brain):
    from m3.brain.items import ItemMeta, write_meta
    import uuid as _u
    write_meta(tmp_brain, ItemMeta(
        id=_u.UUID("00000000-0000-0000-0000-000000000abc"),
        kind="personal", source="cli", created_at="2026-04-19T10:00:00+00:00",
        original_filename=None, extracted_text="Coffee with Aditya.",
        when_iso="2026-04-19", when_source="ingest_time", hooks={},
        llm_output_raw={}, confidence=0.9,
    ))

    tools = BrainTools(brain_root=tmp_brain, embedder=_Embedder())
    llm = _ScriptedLLM([
        {"type": "tool", "name": "search_brain", "input": {"query": "Aditya"}},
        {"type": "final", "text": "Found one item about Aditya."},
    ])
    events = [e async for e in run_agent(llm=llm, tools=tools, user_message="who did I meet?")]
    kinds = [e.type for e in events]
    assert "tool_call" in kinds
    assert "tool_result" in kinds
    assert kinds[-1] == "final"
    final = [e for e in events if e.type == "final"][0]
    assert "Found one" in final.content


@pytest.mark.asyncio
async def test_agent_caps_tool_rounds(tmp_brain):
    tools = BrainTools(brain_root=tmp_brain, embedder=_Embedder())
    # LLM that always wants to call tools — agent must stop it
    llm = _ScriptedLLM([{"type": "tool", "name": "list_open_questions", "input": {}}] * 20)
    events = [e async for e in run_agent(llm=llm, tools=tools, user_message="loop forever")]
    tool_calls = sum(1 for e in events if e.type == "tool_call")
    assert tool_calls <= 5
    # Final must still fire
    assert events[-1].type == "final"
