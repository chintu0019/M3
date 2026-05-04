"""Interactive setup wizard for `m3 telegram init`.

Walks the user through creating a bot with @BotFather, verifies the token
by hitting Telegram's /getMe, auto-detects their chat id by watching for
the first message, and persists everything to ~/.config/m3/config.yml.

Designed so someone who has never touched the Telegram bot API can go from
`m3 telegram init` to a working configured bot in under two minutes.
"""

from __future__ import annotations

import asyncio
import sys
import time
import webbrowser
from dataclasses import dataclass

import httpx

from m3.core import config as cfg

BOTFATHER_URL = "https://t.me/BotFather"
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
DETECT_TIMEOUT_SECS = 180.0
DETECT_POLL_INTERVAL = 2.0


@dataclass
class BotInfo:
    username: str
    first_name: str
    id: int


class SetupError(Exception):
    pass


async def verify_token(token: str) -> BotInfo:
    """Call Telegram /getMe to confirm the token is valid. Returns bot info on success."""
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(TELEGRAM_API.format(token=token, method="getMe"))
    if r.status_code == 401:
        raise SetupError("Token rejected by Telegram (401). Double-check the token you pasted.")
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise SetupError(f"Telegram said: {data.get('description', 'no description')}")
    result = data["result"]
    return BotInfo(
        username=result.get("username") or "(unknown)",
        first_name=result.get("first_name") or "(unknown)",
        id=int(result.get("id") or 0),
    )


async def detect_chat_id(token: str, timeout_secs: float = DETECT_TIMEOUT_SECS) -> int:
    """Poll getUpdates until we see a message, then return the sender's chat id.

    Uses a fresh offset so only updates that arrive *after* this call returns count.
    """
    async with httpx.AsyncClient(timeout=15.0) as c:
        # First, consume any existing updates so we only see fresh ones.
        try:
            init = await c.get(TELEGRAM_API.format(token=token, method="getUpdates"),
                               params={"timeout": 0, "limit": 100})
            init.raise_for_status()
            updates = init.json().get("result") or []
            offset = (updates[-1]["update_id"] + 1) if updates else 0
        except Exception as e:
            raise SetupError(f"couldn't reach Telegram getUpdates: {e}")

        deadline = time.monotonic() + timeout_secs
        while time.monotonic() < deadline:
            try:
                r = await c.get(
                    TELEGRAM_API.format(token=token, method="getUpdates"),
                    params={"timeout": 10, "offset": offset, "limit": 10},
                )
                r.raise_for_status()
            except httpx.HTTPError:
                # Transient network blip — back off briefly and retry
                await asyncio.sleep(DETECT_POLL_INTERVAL)
                continue

            payload = r.json()
            if not payload.get("ok"):
                raise SetupError(f"Telegram: {payload.get('description', 'error')}")
            for update in payload.get("result") or []:
                offset = update["update_id"] + 1
                chat = _first_chat(update)
                if chat:
                    return int(chat["id"])
            await asyncio.sleep(DETECT_POLL_INTERVAL)

    raise SetupError(
        f"Didn't see any message from you in {timeout_secs:.0f}s. "
        "Did you press /start in the bot chat?"
    )


def _first_chat(update: dict) -> dict | None:
    for key in ("message", "edited_message", "channel_post", "callback_query"):
        payload = update.get(key)
        if isinstance(payload, dict):
            chat = payload.get("chat") or (payload.get("message") or {}).get("chat")
            if chat:
                return chat
    return None


# --- interactive driver ---


def _prompt(msg: str, *, secret: bool = False) -> str:
    """Read a line from stdin with a prompt. Stripped. Returns empty string on EOF."""
    if secret:
        import getpass
        try:
            return getpass.getpass(msg).strip()
        except EOFError:
            return ""
    sys.stdout.write(msg)
    sys.stdout.flush()
    try:
        return (sys.stdin.readline() or "").strip()
    except EOFError:
        return ""


def _yes_no(msg: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    answer = _prompt(f"{msg} {suffix} ").lower()
    if not answer:
        return default
    return answer.startswith("y")


async def run_wizard() -> int:
    """Run the interactive wizard. Returns 0 on success, non-zero on failure."""
    print("=" * 60)
    print("M3 Telegram setup")
    print("=" * 60)
    print()
    print("This walks you through creating a Telegram bot and letting only")
    print("you send messages to it. Takes about two minutes.")
    print()

    # --- Step 1: create a bot with BotFather ---
    print("Step 1 — Create your bot")
    print("-" * 60)
    print("  1. Open @BotFather in Telegram.")
    print("  2. Send /newbot.")
    print("  3. Pick a display name (any) and a username (must end in 'bot').")
    print(f"  4. @BotFather will reply with a token like")
    print(f"     '123456789:AAE...'. Paste it below.")
    print()
    if _yes_no("Open @BotFather in your browser now?"):
        try:
            webbrowser.open(BOTFATHER_URL)
        except Exception:
            pass
    print()

    token = ""
    bot_info: BotInfo | None = None
    while not bot_info:
        token = _prompt("Paste your bot token: ", secret=True)
        if not token:
            print("(nothing entered — aborting)")
            return 1
        try:
            bot_info = await verify_token(token)
        except SetupError as e:
            print(f"  ✗ {e}")
            if not _yes_no("Try again?"):
                return 1

    print(f"  ✓ Token accepted. Bot: @{bot_info.username} ({bot_info.first_name})")
    print()

    # --- Step 2: detect chat id ---
    print("Step 2 — Tell the bot who you are")
    print("-" * 60)
    print(f"  1. Open https://t.me/{bot_info.username} in Telegram.")
    print("  2. Press Start (or send any message) within 3 minutes.")
    print("  3. I'll detect your chat id automatically.")
    print()
    if _yes_no(f"Open @{bot_info.username} in your browser now?"):
        try:
            webbrowser.open(f"https://t.me/{bot_info.username}")
        except Exception:
            pass
    print()
    print("  Waiting for your first message…")
    try:
        chat_id = await detect_chat_id(token)
    except SetupError as e:
        print(f"  ✗ {e}")
        return 1
    print(f"  ✓ Got it. Your chat id is {chat_id}.")
    print()

    # --- Step 3: save config ---
    print("Step 3 — Save config")
    print("-" * 60)
    def _set(c: cfg.M3Config) -> cfg.M3Config:
        c.telegram.token = token
        c.telegram.allowed_chats = [chat_id]
        return c
    saved = cfg.update(_set)
    path = cfg.config_path()
    print(f"  ✓ Saved to {path} (mode 600).")
    print()

    # --- Wrap up ---
    print("=" * 60)
    print("All set.")
    print()
    print("  Run the bot:       m3 telegram")
    print(f"  Chat with it:      https://t.me/{bot_info.username}")
    print("  Allowlist is now:  [{}]".format(chat_id))
    print()
    print("To install it as a background service that starts on login:")
    print("  m3 telegram install-service")
    print("=" * 60)
    return 0
