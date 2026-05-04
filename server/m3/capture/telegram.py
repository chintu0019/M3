"""M3 Telegram bot — captures messages + files and POSTs them to the local M3 server.

Architecture: the bot is a separate process (`m3 telegram`) that talks to the
running `m3 start` HTTP API. No Postgres/MinIO/ARQ — capture is now one HTTP
call per message, server-side handles the brain writes.

Config via env:
  M3_TELEGRAM_TOKEN         — bot API token from @BotFather (required)
  M3_TELEGRAM_ALLOWED_CHATS — comma-separated chat IDs allowed to talk to the bot
                              (strongly recommended; without it anyone who finds
                              the bot's username can send content into your brain)
  M3_SERVER_URL             — base URL of the running m3 server (default:
                              http://127.0.0.1:7007)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger("m3.telegram")


DEFAULT_SERVER_URL = "http://127.0.0.1:7007"
INGEST_TIMEOUT_SECS = 180.0   # LLM-backed ingest can be slow with Ollama
CHAT_TIMEOUT_SECS = 180.0


def _parse_allowed_chats(raw: str | None) -> frozenset[int]:
    if not raw:
        return frozenset()
    out: set[int] = set()
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            out.add(int(piece))
        except ValueError:
            logger.warning("ignoring non-integer chat id in M3_TELEGRAM_ALLOWED_CHATS: %r", piece)
    return frozenset(out)


class M3ApiClient:
    """Thin HTTP client for the M3 local server. Separate from the Telegram-framework
    bits so it can be unit-tested without instantiating a real bot."""

    def __init__(
        self,
        *,
        server_url: str = DEFAULT_SERVER_URL,
        http_client: httpx.AsyncClient | None = None,
        bearer_token: str | None = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self._own_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(CHAT_TIMEOUT_SECS, read=CHAT_TIMEOUT_SECS),
        )
        self._bearer = bearer_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._bearer}"} if self._bearer else {}

    async def aclose(self) -> None:
        if self._own_client:
            await self._http.aclose()

    async def ingest_text(self, text: str) -> dict[str, Any]:
        r = await self._http.post(
            f"{self.server_url}/api/v1/ingest/text",
            json={"text": text, "source": "telegram"},
            headers=self._headers(),
            timeout=INGEST_TIMEOUT_SECS,
        )
        r.raise_for_status()
        return r.json()

    async def ingest_file(self, *, filename: str, content: bytes, mime: str) -> dict[str, Any]:
        files = {"file": (filename, content, mime)}
        data = {"source": "telegram"}
        r = await self._http.post(
            f"{self.server_url}/api/v1/ingest/file",
            files=files, data=data,
            headers=self._headers(),
            timeout=INGEST_TIMEOUT_SECS,
        )
        r.raise_for_status()
        return r.json()

    async def retrieve(self, query: str, k: int = 3) -> list[dict[str, Any]]:
        r = await self._http.get(
            f"{self.server_url}/api/v1/retrieve",
            params={"q": query, "k": k},
            headers=self._headers(),
            timeout=30.0,
        )
        r.raise_for_status()
        return r.json().get("hits", [])

    async def chat(self, message: str) -> str:
        """Stream the /api/v1/chat SSE response and return the final content."""
        async with self._http.stream(
            "POST", f"{self.server_url}/api/v1/chat",
            json={"message": message},
            headers=self._headers(),
            timeout=CHAT_TIMEOUT_SECS,
        ) as r:
            r.raise_for_status()
            final = ""
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                try:
                    ev = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "final":
                    final = ev.get("content") or ""
                elif ev.get("type") == "error":
                    return f"(agent error) {ev.get('content') or 'unknown'}"
            return final or "(no answer)"

    async def status(self) -> dict[str, Any]:
        r = await self._http.get(
            f"{self.server_url}/api/v1/status",
            headers=self._headers(),
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json()

    async def entity_count(self) -> int:
        r = await self._http.get(
            f"{self.server_url}/api/v1/entities",
            headers=self._headers(),
            timeout=15.0,
        )
        r.raise_for_status()
        return len(r.json().get("entities", []))


class TelegramCapture:
    """Long-poll Telegram bot that forwards messages to the M3 HTTP API."""

    def __init__(
        self,
        *,
        bot_token: str,
        server_url: str = DEFAULT_SERVER_URL,
        allowed_chats: frozenset[int] = frozenset(),
        http_client: httpx.AsyncClient | None = None,
        bearer_token: str | None = None,
    ) -> None:
        self.app = Application.builder().token(bot_token).build()
        self.api = M3ApiClient(
            server_url=server_url,
            http_client=http_client,
            bearer_token=bearer_token,
        )
        self.server_url = self.api.server_url
        self.allowed_chats = allowed_chats

        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("search", self.cmd_search))
        self.app.add_handler(CommandHandler("ask", self.cmd_ask))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        self.app.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        self.app.add_handler(MessageHandler(filters.Document.ALL, self.handle_document))
        self.app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self.handle_audio))
        self.app.add_handler(MessageHandler(filters.VIDEO, self.handle_video))

    async def start(self) -> None:
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        logger.info(
            "Telegram bot polling (server=%s, allowlist=%s)",
            self.server_url,
            ",".join(str(c) for c in sorted(self.allowed_chats)) or "(open)",
        )

    async def stop(self) -> None:
        if self.app.updater.running:
            await self.app.updater.stop()
        if self.app.running:
            await self.app.stop()
        await self.app.shutdown()
        await self.api.aclose()

    # --- guards ---

    def _chat_is_allowed(self, update: Update) -> bool:
        if not self.allowed_chats:
            return True   # no allowlist configured; open bot (NOT recommended)
        chat = update.effective_chat
        return bool(chat and chat.id in self.allowed_chats)

    async def _reject(self, update: Update) -> None:
        await update.message.reply_text(
            "Sorry — this M3 instance doesn't accept messages from this chat. "
            "Add your chat id to M3_TELEGRAM_ALLOWED_CHATS."
        )

    # --- commands ---

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._chat_is_allowed(update):
            return await self._reject(update)
        await update.message.reply_text(
            "Welcome to M3. Send me anything — text, photos, documents, voice notes — "
            "and I'll route it into your brain.\n\n"
            "Commands:\n"
            "/status  — server + brain summary\n"
            "/search <query>  — top 3 matching items\n"
            "/ask <question>  — agent answer grounded in your brain"
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._chat_is_allowed(update):
            return await self._reject(update)
        try:
            status, entity_count = await asyncio.gather(self.api.status(), self.api.entity_count())
        except Exception as e:
            return await update.message.reply_text(f"M3 server unreachable: {e}")
        await update.message.reply_text(
            f"M3 server: ok\n"
            f"brain: {status.get('brain_root')}\n"
            f"entities: {entity_count}"
        )

    async def cmd_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._chat_is_allowed(update):
            return await self._reject(update)
        query = " ".join(context.args) if context.args else ""
        if not query:
            return await update.message.reply_text("Usage: /search <query>")
        try:
            hits = await self.api.retrieve(query, k=3)
        except Exception as e:
            return await update.message.reply_text(f"search failed: {e}")
        if not hits:
            return await update.message.reply_text("No hits.")
        lines: list[str] = []
        for h in hits:
            when = h.get("when_iso") or "----"
            excerpt = (h.get("excerpt") or h.get("snippet") or "")[:200]
            lines.append(f"[{when}] {excerpt}")
        await update.message.reply_text("\n\n".join(lines))

    async def cmd_ask(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._chat_is_allowed(update):
            return await self._reject(update)
        question = " ".join(context.args) if context.args else ""
        if not question:
            return await update.message.reply_text("Usage: /ask <question>")
        placeholder = await update.message.reply_text("Thinking…")
        try:
            answer = await self.api.chat(question)
        except Exception as e:
            answer = f"(agent failed) {e}"
        # Telegram hard-limits messages to 4096 chars. Truncate if necessary.
        await placeholder.edit_text(_truncate(answer, 4000))

    # --- media handlers ---

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._chat_is_allowed(update):
            return await self._reject(update)
        text = update.message.text or ""
        if not text.strip():
            return
        placeholder = await update.message.reply_text("Ingesting…")
        try:
            out = await self.api.ingest_text(text)
            summary = _format_ingest_summary(out)
        except Exception as e:
            summary = f"ingest failed: {e}"
        await placeholder.edit_text(summary)

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._chat_is_allowed(update):
            return await self._reject(update)
        photo = update.message.photo[-1]
        filename = f"photo_{photo.file_unique_id}.jpg"
        content = await _download(context, photo.file_id)
        placeholder = await update.message.reply_text("Ingesting photo…")
        try:
            out = await self.api.ingest_file(filename=filename, content=content, mime="image/jpeg")
            summary = _format_ingest_summary(out)
        except Exception as e:
            summary = f"ingest failed: {e}"
        await placeholder.edit_text(summary)

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._chat_is_allowed(update):
            return await self._reject(update)
        doc = update.message.document
        filename = doc.file_name or f"doc_{doc.file_unique_id}"
        content = await _download(context, doc.file_id)
        placeholder = await update.message.reply_text(f"Ingesting {filename}…")
        mime = doc.mime_type or "application/octet-stream"
        try:
            out = await self.api.ingest_file(filename=filename, content=content, mime=mime)
            summary = _format_ingest_summary(out)
        except Exception as e:
            summary = f"ingest failed: {e}"
        await placeholder.edit_text(summary)

    async def handle_audio(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._chat_is_allowed(update):
            return await self._reject(update)
        audio = update.message.voice or update.message.audio
        ext = "ogg" if update.message.voice else "mp3"
        filename = f"audio_{audio.file_unique_id}.{ext}"
        mime = "audio/ogg" if update.message.voice else "audio/mpeg"
        content = await _download(context, audio.file_id)
        placeholder = await update.message.reply_text("Ingesting audio…")
        try:
            out = await self.api.ingest_file(filename=filename, content=content, mime=mime)
            summary = _format_ingest_summary(out)
        except Exception as e:
            summary = f"ingest failed: {e}"
        await placeholder.edit_text(summary)

    async def handle_video(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._chat_is_allowed(update):
            return await self._reject(update)
        video = update.message.video
        filename = f"video_{video.file_unique_id}.mp4"
        content = await _download(context, video.file_id)
        placeholder = await update.message.reply_text("Ingesting video…")
        try:
            out = await self.api.ingest_file(filename=filename, content=content, mime="video/mp4")
            summary = _format_ingest_summary(out)
        except Exception as e:
            summary = f"ingest failed: {e}"
        await placeholder.edit_text(summary)


async def _download(context: ContextTypes.DEFAULT_TYPE, file_id: str) -> bytes:
    tg_file = await context.bot.get_file(file_id)
    return bytes(await tg_file.download_as_bytearray())


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _format_ingest_summary(out: dict[str, Any]) -> str:
    """Human-readable summary of an ingest response.

    Surfaces the degenerate cases explicitly so users know when M3 stored
    something but didn't actually understand it:
    - kind=unknown → fallback path, extraction failed, item preserved for FTS
    - self=[], entities=[] → extraction was hollow (model didn't populate slots)
    - low confidence → model itself is unsure
    """
    kind = out.get("kind") or "?"
    conf = out.get("confidence") or 0.0
    self_touched = out.get("self_touched") or []
    entities = out.get("entities_touched") or []
    qs = out.get("questions_raised") or 0

    # Strong negative signal: extraction hit the fallback path.
    if kind == "unknown":
        return (
            "⚠ extraction failed — item text preserved and searchable, "
            "but no self/entity updates.\n"
            "try `/ask` on the content, or reprocess later."
        )

    # Hollow extraction — valid shape but nothing useful.
    if not self_touched and not entities and qs == 0 and kind not in {"record", "signal"}:
        return (
            f"△ {kind} (conf {conf:.2f}) · saved but no self or entity updates.\n"
            "this often means the local model missed the content; "
            "try the Settings tab to switch to Anthropic."
        )

    parts = [f"✓ {kind} (conf {conf:.2f})"]
    if self_touched:
        parts.append(f"self: {', '.join(self_touched)}")
    if entities:
        parts.append(f"entities: {', '.join(entities)}")
    if qs:
        parts.append(f"{qs} open question{'s' if qs != 1 else ''}")
    return "\n".join(parts)


def build_from_config() -> TelegramCapture:
    """Build a TelegramCapture using config resolution (env > config.yml > default).
    Raises a helpful RuntimeError if the token isn't configured anywhere yet."""
    from m3.core import config as _cfg
    token = _cfg.telegram_token()
    if not token:
        raise RuntimeError(
            "Telegram bot token not configured. Run `m3 telegram init` once to set it up."
        )
    return TelegramCapture(
        bot_token=token,
        server_url=_cfg.telegram_server_url(),
        allowed_chats=_cfg.telegram_allowed_chats(),
        bearer_token=_cfg.auth_api_key() if _cfg.auth_required() else None,
    )


# Preserved for callers that pre-date the config module. New code should use
# build_from_config.
def build_from_env() -> TelegramCapture:
    return build_from_config()


async def run() -> None:
    """Entrypoint for `m3 telegram` — polls until Ctrl+C."""
    cap = build_from_config()
    await cap.start()
    try:
        stop_event = asyncio.Event()
        await stop_event.wait()
    finally:
        await cap.stop()
