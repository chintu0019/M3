"""Tests for the `m3 telegram init` wizard's lower-level pieces."""

from __future__ import annotations

import httpx
import pytest

from m3.capture import telegram_setup


# Capture the REAL AsyncClient constructor at import time so our monkeypatched
# factory (which replaces httpx.AsyncClient globally) doesn't end up calling
# itself recursively.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _mock_client(handler) -> httpx.AsyncClient:
    return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), timeout=5.0)


@pytest.mark.asyncio
async def test_verify_token_happy_path(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/getMe")
        return httpx.Response(200, json={
            "ok": True,
            "result": {"id": 123, "is_bot": True, "first_name": "M3", "username": "m3_test_bot"},
        })

    async def _fake_client(*args, **kwargs):
        return _mock_client(handler)

    # Monkeypatch httpx.AsyncClient so verify_token uses our transport.
    orig = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda *a, **kw: _mock_client(handler),
    )
    try:
        info = await telegram_setup.verify_token("fake-token")
    finally:
        monkeypatch.setattr(httpx, "AsyncClient", orig)
    assert info.username == "m3_test_bot"
    assert info.id == 123


@pytest.mark.asyncio
async def test_verify_token_401_raises_setup_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _mock_client(handler))
    with pytest.raises(telegram_setup.SetupError, match="401"):
        await telegram_setup.verify_token("bad-token")


@pytest.mark.asyncio
async def test_detect_chat_id_returns_first_message_chat(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        # First call: initial getUpdates to drain existing (return empty)
        if calls["n"] == 1:
            return httpx.Response(200, json={"ok": True, "result": []})
        # Second call: a real message lands
        return httpx.Response(200, json={"ok": True, "result": [
            {
                "update_id": 101,
                "message": {
                    "message_id": 1,
                    "chat": {"id": 987654321, "type": "private"},
                    "text": "/start",
                },
            },
        ]})

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _mock_client(handler))
    # Tight timeout + short poll so the test runs fast even if logic breaks
    monkeypatch.setattr(telegram_setup, "DETECT_POLL_INTERVAL", 0.01)
    chat_id = await telegram_setup.detect_chat_id("token", timeout_secs=5.0)
    assert chat_id == 987654321


@pytest.mark.asyncio
async def test_detect_chat_id_times_out_if_no_messages(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": []})
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _mock_client(handler))
    monkeypatch.setattr(telegram_setup, "DETECT_POLL_INTERVAL", 0.01)
    with pytest.raises(telegram_setup.SetupError, match="Didn't see any message"):
        await telegram_setup.detect_chat_id("token", timeout_secs=0.25)


def test_first_chat_finds_message_chat():
    update = {"update_id": 1, "message": {"chat": {"id": 1}}}
    assert telegram_setup._first_chat(update) == {"id": 1}


def test_first_chat_finds_edited_message_chat():
    update = {"update_id": 1, "edited_message": {"chat": {"id": 2}}}
    assert telegram_setup._first_chat(update) == {"id": 2}


def test_first_chat_returns_none_when_no_chat():
    assert telegram_setup._first_chat({"update_id": 1}) is None
