import os

import pytest

from m3.core.llm import Tool
from m3.core.llm.ollama import OllamaProvider


@pytest.mark.skipif(
    not os.environ.get("OLLAMA_HOST"),
    reason="Set OLLAMA_HOST to run Ollama integration tests.",
)
@pytest.mark.asyncio
async def test_ollama_tool_use_returns_schema_valid_json():
    provider = OllamaProvider(
        host=os.environ["OLLAMA_HOST"],
        model=os.environ.get("OLLAMA_MODEL", "qwen2.5:14b"),
    )
    tool = Tool(
        name="echo",
        description="Return a copy of the input.",
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    )
    result = await provider.complete_tool(
        messages=[{"role": "user", "content": "Call echo with message='hello'."}],
        tools=[tool],
        system="You must call the echo tool exactly once with message='hello'.",
        tool_choice="echo",
        max_tokens=256,
        temperature=0.0,
    )
    assert result.tool_name == "echo"
    assert result.input.get("message") == "hello"
