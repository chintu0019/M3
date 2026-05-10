import asyncio
import pytest

from m3.core.headline import generate_headline


class _FakeLLM:
    """Records calls and returns canned responses."""
    def __init__(self, response: str = "Test Headline"):
        self.response = response
        self.calls: list[list[dict]] = []

    async def complete(
        self, messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        self.calls.append(messages)
        return self.response


def test_generate_headline_calls_llm_with_proposition():
    llm = _FakeLLM(response="Long CTO tenure")
    result = asyncio.run(generate_headline(
        proposition="Manoj has been the CTO of three startups.", llm=llm,
    ))
    assert result == "Long CTO tenure"
    assert len(llm.calls) == 1
    user_msg = llm.calls[0][-1]
    assert user_msg["role"] == "user"
    assert "Manoj has been the CTO of three startups." in user_msg["content"]


def test_generate_headline_truncates_to_80():
    llm = _FakeLLM(response="x" * 200)
    result = asyncio.run(generate_headline(proposition="A claim.", llm=llm))
    assert len(result) <= 80


def test_generate_headline_strips_quotes_and_trailing_period():
    llm = _FakeLLM(response='"Long CTO tenure."')
    result = asyncio.run(generate_headline(proposition="A.", llm=llm))
    assert result == "Long CTO tenure"


def test_generate_headline_takes_first_line_only():
    llm = _FakeLLM(response="Long CTO tenure\nExtra commentary the model added")
    result = asyncio.run(generate_headline(proposition="A.", llm=llm))
    assert result == "Long CTO tenure"


def test_generate_headline_returns_empty_on_empty_response():
    llm = _FakeLLM(response="")
    result = asyncio.run(generate_headline(proposition="A.", llm=llm))
    assert result == ""
