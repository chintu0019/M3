"""HTTP surface for the Settings → Telegram card.

Five endpoints, all under ``/api/v1/telegram``:

* ``GET    /status``           — bot state for the card
* ``POST   /connect``          — save token + (re)start the bot
* ``POST   /disconnect``       — stop bot + clear token + clear allowlist
* ``POST   /pair/start``       — generate one-time code + QR deeplink
* ``GET    /pair/{code}``      — poll pairing status (UI calls every ~2s)

The supervisor (``m3.capture.supervisor``) owns the bot lifecycle; this
router is a thin transport layer over it. Heavy lifting (token paste →
``get_me`` verification → polling task) happens inside ``supervisor.start()``.
"""

from __future__ import annotations

import base64
import io

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from m3.capture import supervisor
from m3.core import config as _cfg


class TelegramStatus(BaseModel):
    configured: bool             # token is set in config
    running: bool                # polling task is alive
    bot_username: str | None     # filled once get_me succeeds
    allowed_chats: list[int] = Field(default_factory=list)
    last_error: str | None       # last failure surfaced to the UI
    started_at: float | None     # unix ts, for the "since X" display


class ConnectRequest(BaseModel):
    token: str


class PairStart(BaseModel):
    code: str                    # full code including the "link-" prefix
    deeplink: str                # https://t.me/<bot>?start=<code>
    qr_data_url: str             # data:image/svg+xml;base64,... — drop into <img src=>.
                                 # Returning a data URL (instead of raw SVG markup)
                                 # lets the client render the QR with a plain <img>
                                 # tag, no innerHTML / sanitizer required.


class PairStatus(BaseModel):
    status: str                  # "pending" | "linked" | "expired"
    chat_id: int | None = None
    chat_title: str | None = None


def _generate_qr_data_url(data: str) -> str:
    """Render the deeplink as a base64-encoded ``data:image/svg+xml`` URL.

    ``SvgPathImage`` produces a single ``<path>`` element which is much
    smaller than the default per-module SVG. We base64-encode it so the
    client can drop it straight into an ``<img src=>`` without any
    sanitization gymnastics.
    """
    img = qrcode.make(
        data,
        image_factory=qrcode.image.svg.SvgPathImage,
        box_size=10,
        border=2,
    )
    buf = io.BytesIO()
    img.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def build_telegram_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/telegram", tags=["telegram"])

    @router.get("/status", response_model=TelegramStatus)
    async def get_status():
        return TelegramStatus(**supervisor.status())

    @router.post("/connect", response_model=TelegramStatus)
    async def connect(body: ConnectRequest):
        token = body.token.strip()
        if not token:
            raise HTTPException(status_code=422, detail="token is required")

        # Persist first so a supervisor restart elsewhere picks it up too.
        def _set_token(c: _cfg.M3Config) -> _cfg.M3Config:
            c.telegram.token = token
            return c
        _cfg.update(_set_token)

        s = await supervisor.restart()
        if not s["running"]:
            # Token didn't validate (get_me failed) — surface the reason and
            # clear it from config so the UI doesn't get stuck thinking the
            # bot is configured-but-broken on the next reload.
            err = s.get("last_error") or "unknown error"
            def _clear(c: _cfg.M3Config) -> _cfg.M3Config:
                c.telegram.token = None
                return c
            _cfg.update(_clear)
            raise HTTPException(status_code=400, detail=f"could not connect to Telegram: {err}")
        return TelegramStatus(**s)

    @router.post("/disconnect", response_model=TelegramStatus)
    async def disconnect():
        await supervisor.stop()

        def _clear(c: _cfg.M3Config) -> _cfg.M3Config:
            c.telegram.token = None
            c.telegram.allowed_chats = []
            return c
        _cfg.update(_clear)

        return TelegramStatus(**supervisor.status())

    @router.post("/pair/start", response_model=PairStart)
    async def pair_start():
        if not supervisor.is_running():
            raise HTTPException(
                status_code=409,
                detail="connect a Telegram bot before generating a pairing code",
            )
        bot_username = supervisor.status().get("bot_username")
        if not bot_username:
            raise HTTPException(status_code=409, detail="bot is still initialising; retry shortly")

        entry = supervisor.new_pair_code()
        deeplink = f"https://t.me/{bot_username}?start={entry.code}"
        return PairStart(
            code=entry.code,
            deeplink=deeplink,
            qr_data_url=_generate_qr_data_url(deeplink),
        )

    @router.get("/pair/{code}", response_model=PairStatus)
    async def pair_poll(code: str):
        entry = supervisor.get_pair(code)
        if entry is None:
            return PairStatus(status="expired")
        if entry.chat_id is not None:
            return PairStatus(status="linked", chat_id=entry.chat_id, chat_title=entry.chat_title)
        return PairStatus(status="pending")

    return router
