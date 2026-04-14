"""
M3 Telegram Bot -- capture content from Telegram messages.

Handles text, photos, documents, audio, voice, and video.
Uses python-telegram-bot v21+ (async native).
"""

import logging
import uuid

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from m3.core.search import SearchEngine
from m3.storage.models import RawItem

logger = logging.getLogger("m3.telegram")


class TelegramCapture:
    """Telegram bot that captures messages and sends them to M3 for processing."""

    def __init__(self, bot_token: str):
        self.app = Application.builder().token(bot_token).build()
        self.db = None
        self.files = None
        self.arq_pool = None
        self.search_engine: SearchEngine | None = None
        self.llm = None

        # Register handlers
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
        """Start the bot in polling mode."""
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        logger.info("Telegram bot started")

    async def stop(self) -> None:
        """Stop the bot."""
        if self.app.updater.running:
            await self.app.updater.stop()
        if self.app.running:
            await self.app.stop()
        await self.app.shutdown()
        logger.info("Telegram bot stopped")

    async def _create_item(
        self,
        content_text: str | None,
        content_type: str,
        file_path: str | None = None,
    ) -> uuid.UUID:
        """Create a raw item and enqueue processing."""
        item_id = uuid.uuid4()
        async with self.db() as session:
            item = RawItem(
                id=item_id,
                content_text=content_text,
                content_type=content_type,
                source_channel="telegram",
                file_path=file_path,
            )
            session.add(item)
            await session.commit()

        if self.arq_pool:
            await self.arq_pool.enqueue_job("process_item", str(item_id))

        return item_id

    async def _download_and_store(
        self, file_id: str, filename: str, context: ContextTypes.DEFAULT_TYPE
    ) -> tuple[str, bytes]:
        """Download a Telegram file and store in MinIO."""
        tg_file = await context.bot.get_file(file_id)
        file_bytes = await tg_file.download_as_bytearray()
        file_bytes = bytes(file_bytes)

        item_id = uuid.uuid4()
        path = f"raw/{item_id}/{filename}"
        await self.files.upload(path, file_bytes)
        return path, file_bytes

    # --- Command handlers ---

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "Welcome to M3. Send me anything -- text, photos, documents, voice notes -- "
            "and I'll organize it into your knowledge base.\n\n"
            "Commands:\n"
            "/status - System status\n"
            "/search <query> - Search your wiki\n"
            "/ask <question> - Ask your wiki a question"
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        from sqlalchemy import func, select
        from m3.storage.models import WikiPage

        async with self.db() as session:
            pending = (await session.execute(
                select(func.count(RawItem.id)).where(RawItem.status == "pending")
            )).scalar() or 0
            total_items = (await session.execute(
                select(func.count(RawItem.id))
            )).scalar() or 0
            total_pages = (await session.execute(
                select(func.count(WikiPage.id)).where(WikiPage.page_type != "_index")
            )).scalar() or 0

        await update.message.reply_text(
            f"M3 Status:\n"
            f"  Items: {total_items} total, {pending} pending\n"
            f"  Wiki pages: {total_pages}"
        )

    async def cmd_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = " ".join(context.args) if context.args else ""
        if not query:
            await update.message.reply_text("Usage: /search <query>")
            return

        if not self.search_engine:
            await update.message.reply_text("Search not available yet.")
            return

        results = await self.search_engine.search(query, limit=3)
        if not results:
            await update.message.reply_text("No results found.")
            return

        lines = []
        for r in results:
            lines.append(f"*{r.title}*")
            lines.append(f"{r.snippet[:200]}")
            lines.append("")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def cmd_ask(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        question = " ".join(context.args) if context.args else ""
        if not question:
            await update.message.reply_text("Usage: /ask <question>")
            return

        if not self.search_engine or not self.llm:
            await update.message.reply_text("Chat not available yet.")
            return

        results = await self.search_engine.search(question, limit=5)
        context_parts = []
        async with self.db() as session:
            for r in results:
                from m3.storage.models import WikiPage
                page = await session.get(WikiPage, r.page_id)
                if page:
                    context_parts.append(f"### {page.title}\n{page.content[:2000]}")

        wiki_context = "\n\n---\n\n".join(context_parts) if context_parts else "(No relevant pages)"

        system = f"""You are M3, a personal knowledge assistant. Answer based on the wiki context below.
Be concise -- this is a Telegram message.

Wiki context:
{wiki_context}"""

        response = await self.llm.complete(
            messages=[{"role": "user", "content": question}],
            system=system,
            max_tokens=1000,
            temperature=0.5,
        )

        await update.message.reply_text(response)

    # --- Message handlers ---

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = update.message.text
        await self._create_item(content_text=text, content_type="text")
        await update.message.reply_text("Got it. Processing...")

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        photo = update.message.photo[-1]  # Highest resolution
        path, _ = await self._download_and_store(
            photo.file_id, f"photo_{photo.file_unique_id}.jpg", context
        )
        caption = update.message.caption or ""
        await self._create_item(content_text=caption, content_type="image", file_path=path)
        await update.message.reply_text("Photo received. Processing...")

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        doc = update.message.document
        filename = doc.file_name or f"doc_{doc.file_unique_id}"
        path, _ = await self._download_and_store(doc.file_id, filename, context)

        content_type = "file"
        if filename.lower().endswith(".pdf"):
            content_type = "pdf"

        caption = update.message.caption or ""
        await self._create_item(content_text=caption, content_type=content_type, file_path=path)
        await update.message.reply_text(f"Document '{filename}' received. Processing...")

    async def handle_audio(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        audio = update.message.voice or update.message.audio
        ext = "ogg" if update.message.voice else "mp3"
        path, _ = await self._download_and_store(
            audio.file_id, f"audio_{audio.file_unique_id}.{ext}", context
        )
        await self._create_item(content_text=None, content_type="audio", file_path=path)
        await update.message.reply_text("Audio received. Processing...")

    async def handle_video(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        video = update.message.video
        path, _ = await self._download_and_store(
            video.file_id, f"video_{video.file_unique_id}.mp4", context
        )
        caption = update.message.caption or ""
        await self._create_item(content_text=caption, content_type="video", file_path=path)
        await update.message.reply_text("Video received. Processing...")
