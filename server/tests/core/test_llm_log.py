from __future__ import annotations

import json

import pytest

from m3.core.llm_log import LLMCall, log_path, now_iso, prompt_chars, record


@pytest.fixture(autouse=True)
def _tmp_log(tmp_path, monkeypatch):
    monkeypatch.setenv("M3_LOG_DIR", str(tmp_path / "state"))


@pytest.mark.asyncio
async def test_record_writes_jsonl():
    await record(LLMCall(
        ts=now_iso(), provider="anthropic", model="claude-sonnet-4",
        method="complete_tool", prompt_chars=120, input_tokens=50,
        output_tokens=100, latency_ms=1234,
    ))
    lines = log_path().read_text().splitlines()
    assert len(lines) == 1
    d = json.loads(lines[0])
    assert d["provider"] == "anthropic"
    assert d["input_tokens"] == 50
    assert d["latency_ms"] == 1234


@pytest.mark.asyncio
async def test_multiple_records_append():
    for i in range(3):
        await record(LLMCall(
            ts=now_iso(), provider="ollama", model="qwen2.5:7b",
            method="complete", prompt_chars=10 * i, latency_ms=i,
        ))
    assert len(log_path().read_text().splitlines()) == 3


def test_prompt_chars_plain_strings():
    assert prompt_chars([{"role": "user", "content": "hello"}]) == 5


def test_prompt_chars_content_blocks():
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "abc"},
        {"type": "text", "text": "de"},
    ]}]
    assert prompt_chars(msgs) == 5


def test_prompt_chars_empty():
    assert prompt_chars([]) == 0
    assert prompt_chars(None) == 0
