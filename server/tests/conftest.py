from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def tmp_brain(tmp_path: Path) -> Path:
    """A freshly-initialized ~/brain/ directory rooted at a pytest tmp path."""
    from m3.brain.layout import init_brain

    init_brain(tmp_path)
    return tmp_path


@pytest.fixture
def sample_item_text() -> str:
    return (
        "Had a call with Aditya yesterday about the Pilot Path rollout. "
        "He thinks we should delay by two weeks. I disagree — FluentCRM "
        "is the wrong tool for us, and pushing the date doesn't change that."
    )


@pytest.fixture
def sample_item_id() -> uuid.UUID:
    # Stable UUID for snapshot-style tests
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


_DEFAULT_FAKE_RESPONSE: dict[str, Any] = {
    "kind": "personal",
    "interpretation": {
        "what_happened": "",
        "when": {"iso": None, "source": "unknown"},
        "confidence": 0.0,
    },
    "open_questions": [],
    "hooks": {},
    "self_updates": [],
    "entity_updates": [],
}


class FakeLLM:
    """Returns canned tool-use responses keyed on the text content."""

    def __init__(self, canned: dict[str, dict[str, Any]] | None = None) -> None:
        self._canned = canned or {}
        self.calls: list[dict[str, Any]] = []
        self._completion = "Default title"

    def set_response(self, key: str, response: dict[str, Any]) -> None:
        self._canned[key] = response

    def set_completion_response(self, text: str) -> None:
        self._completion = text

    async def complete(
        self,
        messages,
        system=None,
        max_tokens=4096,
        temperature=0.7,
    ) -> str:
        return self._completion

    async def complete_tool(
        self,
        messages,
        tools,
        system=None,
        tool_choice=None,
        max_tokens=4096,
        temperature=0.2,
    ):
        from m3.core.llm.base import ToolResult

        self.calls.append({"messages": messages, "system": system, "tool_choice": tool_choice})
        user_text = messages[-1]["content"] if isinstance(messages[-1]["content"], str) else ""
        for key, resp in self._canned.items():
            if key in user_text:
                return ToolResult(tool_name=tool_choice or "process_item", input=resp)
        return ToolResult(
            tool_name=tool_choice or "process_item",
            input=_DEFAULT_FAKE_RESPONSE,
        )

    supports_tools = True
    supports_vision = False
    supports_audio = False


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture(autouse=True)
def _git_identity_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure git commits in tests have an identity, without touching the user's global config.

    Also disables commit signing in test brain repos: some sandboxed CI
    environments inject `gpg.format=ssh` + a signing program globally, and
    the brain repos can't reach that signer. Tests don't need signed commits.
    """
    monkeypatch.setenv("GIT_AUTHOR_NAME", "m3-test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@m3.local")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "m3-test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@m3.local")
    # GIT_CONFIG_COUNT/KEY/VALUE lets us inject overrides without writing to ~/.gitconfig.
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "commit.gpgsign")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
