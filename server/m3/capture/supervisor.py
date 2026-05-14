"""In-process Telegram bot supervisor.

Replaces the launchd/systemd `m3 telegram` daemon: the bot now runs as an
asyncio task inside the `m3 start` process, lifecycle-managed by FastAPI's
lifespan and reachable from the API for live reconfigure (connect/pair/
disconnect from the Settings UI).

State model — one supervisor per process, module-level singletons. The bot
is either off (token unset) or running (token set + polling task alive).
On unexpected exit we retry with exponential backoff up to a cap; after
that we give up and surface the last error through `status()` so the UI
can show it instead of silently flapping.

Pairing codes live in-memory only. A code starts as `pending`, the
``/start link-<code>`` handler in ``telegram.py`` calls
:func:`consume_pair_code` to flip it to `linked` with the chat id, and the
HTTP poll endpoint reads that state. Codes expire after 10 minutes.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("m3.capture.supervisor")


PAIR_TTL_SECS = 10 * 60
RESTART_BACKOFF_SECS = (2, 5, 15, 30, 60)   # capped attempts; index = retry count


@dataclass
class _PairEntry:
    code: str
    created_at: float
    chat_id: Optional[int] = None        # filled when the user scans + bot consumes
    chat_title: Optional[str] = None     # username or chat title, for UI display


@dataclass
class _SupState:
    capture: object | None = None        # TelegramCapture | None — typed as object to avoid import cycle
    task: asyncio.Task | None = None
    bot_username: str | None = None
    last_error: str | None = None
    started_at: float | None = None
    retry_count: int = 0
    pairs: dict[str, _PairEntry] = field(default_factory=dict)
    # Lock ordering: take this for any structural change to the state above.
    # All public functions acquire it before mutating.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_state = _SupState()


def is_running() -> bool:
    return _state.task is not None and not _state.task.done()


def status() -> dict:
    """Snapshot of the supervisor state for the API.

    Read-only — safe to call without the lock since dict/None reads are
    atomic in CPython and the worst case is a slightly stale view.
    """
    from m3.core import config as _cfg
    return {
        "configured": bool(_cfg.telegram_token()),
        "running": is_running(),
        "bot_username": _state.bot_username,
        "allowed_chats": sorted(_cfg.telegram_allowed_chats()),
        "last_error": _state.last_error,
        "started_at": _state.started_at,
    }


async def start() -> dict:
    """Start the bot if a token is configured. Idempotent.

    On a clean start this fetches the bot's username via ``get_me`` so the
    Settings UI can show "Connected as @yourbot" and the pairing QR can
    embed the right deeplink. If the token is invalid we surface the
    error and leave the supervisor stopped.
    """
    from m3.capture.telegram import build_from_config
    from m3.core import config as _cfg

    async with _state.lock:
        if is_running():
            return status()
        if not _cfg.telegram_token():
            _state.last_error = None
            return status()
        try:
            cap = build_from_config()
            await cap.start()
            me = await cap.app.bot.get_me()
            _state.capture = cap
            _state.bot_username = me.username
            _state.last_error = None
            _state.started_at = time.time()
            _state.retry_count = 0
            _state.task = asyncio.create_task(_supervise(), name="m3-telegram-supervisor")
            logger.info("telegram bot online as @%s", me.username)
        except Exception as e:
            _state.last_error = f"{type(e).__name__}: {e}"
            logger.warning("telegram bot failed to start: %s", _state.last_error)
            # Best-effort cleanup of a half-built capture
            cap = locals().get("cap")
            if cap is not None:
                try:
                    await cap.stop()
                except Exception:
                    pass
            _state.capture = None
            _state.bot_username = None
            _state.task = None
            _state.started_at = None
        return status()


async def stop() -> dict:
    """Stop polling + tear down. Idempotent."""
    async with _state.lock:
        task = _state.task
        cap = _state.capture
        _state.task = None
        _state.capture = None
        _state.bot_username = None
        _state.started_at = None
    if task is not None:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    if cap is not None:
        try:
            await cap.stop()  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning("telegram bot stop raised: %s", e)
    return status()


async def restart() -> dict:
    """Stop (if running) then start. Used when the token changes."""
    await stop()
    return await start()


async def _supervise() -> None:
    """Watchdog: keep the long-polling loop alive across transient failures.

    python-telegram-bot's Application runs its own loops; this task just
    waits for them to die so we can decide whether to restart. The
    capture's ``start()`` already kicks off polling, so we mostly idle
    here until something blows up.
    """
    try:
        while True:
            await asyncio.sleep(5)
            cap = _state.capture
            if cap is None:
                return
            # python-telegram-bot keeps Application.running / updater.running flags.
            # If the updater stopped while we still hold the capture, it's a crash.
            if not cap.app.running or not cap.app.updater.running:  # type: ignore[attr-defined]
                raise RuntimeError("telegram updater stopped unexpectedly")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        _state.last_error = f"{type(e).__name__}: {e}"
        logger.warning("telegram supervisor: %s — will retry", _state.last_error)
        # Tear down the dead capture before retrying so start() builds fresh.
        cap = _state.capture
        _state.capture = None
        _state.bot_username = None
        if cap is not None:
            try:
                await cap.stop()  # type: ignore[attr-defined]
            except Exception:
                pass
        idx = min(_state.retry_count, len(RESTART_BACKOFF_SECS) - 1)
        delay = RESTART_BACKOFF_SECS[idx]
        _state.retry_count += 1
        if _state.retry_count > len(RESTART_BACKOFF_SECS):
            logger.error("telegram bot retry cap reached — giving up; user can reconnect in Settings")
            _state.task = None
            return
        await asyncio.sleep(delay)
        # Clear our own task reference before re-entering start() so the
        # idempotency check there doesn't see us and bail.
        _state.task = None
        await start()


# --- pairing codes ---


def new_pair_code() -> _PairEntry:
    """Generate a one-time pairing code with 10-minute expiry.

    Format: ``link-<8 url-safe chars>``. Short enough to fit in a Telegram
    ``/start`` deeplink (Telegram caps the start_param at 64 chars) but
    long enough that brute-forcing a live code in the TTL window is
    infeasible.
    """
    _expire_old_pairs()
    code = "link-" + secrets.token_urlsafe(6)   # 8 chars after b64 padding strip
    entry = _PairEntry(code=code, created_at=time.time())
    _state.pairs[code] = entry
    return entry


def get_pair(code: str) -> _PairEntry | None:
    _expire_old_pairs()
    return _state.pairs.get(code)


def consume_pair_code(code: str, chat_id: int, chat_title: str | None) -> bool:
    """Mark a pending pairing code as linked. Returns True on success.

    Called from the bot's ``/start link-<code>`` handler — must not raise
    on a bad code; the handler will reply differently in each case.
    """
    _expire_old_pairs()
    entry = _state.pairs.get(code)
    if entry is None:
        return False
    if entry.chat_id is not None:
        return False   # already consumed
    entry.chat_id = chat_id
    entry.chat_title = chat_title
    return True


def _expire_old_pairs() -> None:
    cutoff = time.time() - PAIR_TTL_SECS
    expired = [c for c, e in _state.pairs.items() if e.created_at < cutoff]
    for c in expired:
        _state.pairs.pop(c, None)
