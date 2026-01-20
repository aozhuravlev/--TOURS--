"""
Telegram Bot for content moderation.

Provides interface for moderator to:
- View generated content (video + text)
- Edit text before publishing
- Approve or reject content
"""

import logging
import asyncio
from pathlib import Path
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logger = logging.getLogger(__name__)


class ModerationAction(Enum):
    """Possible moderation actions."""
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


@dataclass
class PendingContent:
    """Content awaiting moderation."""
    content_id: str
    content_type: str  # "story", "post", or "story_series"
    topic: str
    subtopic: str
    text: str
    video_path: Optional[Path]
    photo_path: Path


@dataclass
class StorySeriesItem:
    """Single story in a series for moderation."""
    order: int
    text: str
    video_path: Path


@dataclass
class PendingStorySeries:
    """Story series awaiting moderation."""
    content_id: str
    topic: str
    subtopic: str
    stories: list[StorySeriesItem]


class ModerationBot:
    """
    Telegram bot for content moderation.

    Sends generated content to moderator and handles approval workflow.
    """

    def __init__(
        self,
        token: str,
        moderator_chat_id: int,
        on_approve: Optional[Callable[[str, str], Awaitable[None]]] = None,
        on_reject: Optional[Callable[[str], Awaitable[None]]] = None,
    ):
        """
        Initialize moderation bot.

        Args:
            token: Telegram bot token
            moderator_chat_id: Chat ID of moderator
            on_approve: Callback when content is approved (content_id, text)
            on_reject: Callback when content is rejected (content_id)
        """
        self.token = token
        self.moderator_chat_id = moderator_chat_id
        self.on_approve = on_approve
        self.on_reject = on_reject

        # Store pending edits: chat_id -> content_id
        self._editing: dict[int, str] = {}
        # Store content data: content_id -> PendingContent
        self._pending: dict[str, PendingContent] = {}
        # Store pending series: content_id -> PendingStorySeries
        self._pending_series: dict[str, PendingStorySeries] = {}

        self.app: Optional[Application] = None

    def build_app(self) -> Application:
        """Build and configure the bot application."""
        self.app = Application.builder().token(self.token).build()

        # Handlers
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        self.app.add_handler(CallbackQueryHandler(self._handle_callback))
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._handle_text,
        ))

        return self.app

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        await update.message.reply_text(
            "Привет! Я бот для модерации контента tours.batumi.\n\n"
            "Я буду отправлять сгенерированный контент для проверки.\n"
            "Вы можете одобрить, отредактировать или отклонить публикацию.\n\n"
            "Команды:\n"
            "/status - статус ожидающего контента\n"
            "/help - справка"
        )

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        pending_count = len(self._pending)
        series_count = len(self._pending_series)

        if pending_count == 0 and series_count == 0:
            await update.message.reply_text("Нет контента, ожидающего модерации.")
        else:
            items = []
            for c in self._pending.values():
                if c.content_type == "story_series":
                    series = self._pending_series.get(c.content_id)
                    story_count = len(series.stories) if series else "?"
                    items.append(f"• [СЕРИЯ {story_count} шт] {c.subtopic}")
                else:
                    items.append(f"• [{c.content_type}] {c.subtopic}")

            await update.message.reply_text(
                f"Ожидают модерации: {pending_count}\n\n" + "\n".join(items)
            )

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        await update.message.reply_text(
            "📋 Как работает модерация:\n\n"
            "1. Система генерирует контент и отправляет его сюда\n"
            "2. Вы получаете видео + текст для проверки\n"
            "3. Выберите действие:\n"
            "   ✅ Одобрить - публикуется как есть\n"
            "   ✏️ Редактировать - введите новый текст\n"
            "   ❌ Отклонить - не публикуется\n\n"
            "Если не ответить в течение 24ч, контент публикуется автоматически."
        )

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline button callbacks."""
        query = update.callback_query
        await query.answer()

        data = query.data
        parts = data.split(":")
        action = parts[0]
        content_id = parts[1] if len(parts) > 1 else None

        if action == "approve" and content_id:
            await self._approve_content(query, content_id)
        elif action == "edit" and content_id:
            await self._start_edit(query, content_id)
        elif action == "reject" and content_id:
            await self._reject_content(query, content_id)
        elif action == "cancel_edit":
            await self._cancel_edit(query)

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages (for editing)."""
        chat_id = update.effective_chat.id

        if chat_id in self._editing:
            content_id = self._editing[chat_id]
            new_text = update.message.text

            # Update pending content
            if content_id in self._pending:
                self._pending[content_id].text = new_text

            # Call approve callback with new text
            if self.on_approve:
                await self.on_approve(content_id, new_text)

            del self._editing[chat_id]
            if content_id in self._pending:
                del self._pending[content_id]

            await update.message.reply_text(
                f"✅ Текст обновлён и контент одобрен!\n\n"
                f"Новый текст:\n{new_text}"
            )
        else:
            await update.message.reply_text(
                "Сейчас нет контента для редактирования.\n"
                "Дождитесь нового контента от системы."
            )

    async def _approve_content(self, query, content_id: str):
        """Approve content for publishing."""
        content = self._pending.get(content_id)
        if not content:
            # Try to find in series (might be message-based, not caption)
            if content_id in self._pending_series:
                series = self._pending_series[content_id]
                if self.on_approve:
                    await self.on_approve(content_id, "")  # Series has no single text
                del self._pending_series[content_id]
                del self._pending[content_id]
                await query.edit_message_text(
                    text=f"✅ СЕРИЯ ОДОБРЕНА\n\n"
                         f"{len(series.stories)} историй: {series.subtopic}"
                )
                return

            await query.edit_message_text(
                text="⚠️ Контент не найден или уже обработан."
            )
            return

        if self.on_approve:
            await self.on_approve(content_id, content.text)

        # Clean up series data if present
        if content_id in self._pending_series:
            del self._pending_series[content_id]
        del self._pending[content_id]

        # Use edit_message_text for text messages (series), edit_message_caption for media
        if content.content_type == "story_series":
            await query.edit_message_text(
                text=f"✅ СЕРИЯ ОДОБРЕНА\n\n"
                     f"[{content.content_type}] {content.subtopic}\n\n"
                     f"{content.text[:500]}..."
            )
        else:
            await query.edit_message_caption(
                caption=f"✅ ОДОБРЕНО\n\n"
                        f"[{content.content_type}] {content.subtopic}\n\n"
                        f"{content.text}"
            )

    async def _start_edit(self, query, content_id: str):
        """Start editing mode."""
        content = self._pending.get(content_id)
        if not content:
            await query.edit_message_caption(
                caption="⚠️ Контент не найден или уже обработан."
            )
            return

        chat_id = query.message.chat_id
        self._editing[chat_id] = content_id

        keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_edit")]]

        await query.edit_message_caption(
            caption=f"✏️ РЕЖИМ РЕДАКТИРОВАНИЯ\n\n"
                    f"Текущий текст:\n{content.text}\n\n"
                    f"Отправьте новый текст сообщением:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _cancel_edit(self, query):
        """Cancel editing mode."""
        chat_id = query.message.chat_id
        content_id = self._editing.get(chat_id)

        if chat_id in self._editing:
            del self._editing[chat_id]

        content = self._pending.get(content_id) if content_id else None

        if content:
            keyboard = self._build_keyboard(content_id)
            await query.edit_message_caption(
                caption=f"📝 Контент для модерации\n\n"
                        f"[{content.content_type.upper()}] {content.subtopic}\n"
                        f"Категория: {content.topic}\n\n"
                        f"Текст:\n{content.text}",
                reply_markup=keyboard,
            )
        else:
            await query.edit_message_caption(
                caption="Редактирование отменено."
            )

    async def _reject_content(self, query, content_id: str):
        """Reject content."""
        content = self._pending.get(content_id)
        if not content:
            # Try series
            if content_id in self._pending_series:
                series = self._pending_series[content_id]
                if self.on_reject:
                    await self.on_reject(content_id)
                del self._pending_series[content_id]
                await query.edit_message_text(
                    text=f"❌ СЕРИЯ ОТКЛОНЕНА\n\n{series.subtopic}"
                )
                return

            await query.edit_message_text(
                text="⚠️ Контент не найден или уже обработан."
            )
            return

        if self.on_reject:
            await self.on_reject(content_id)

        # Clean up series data if present
        if content_id in self._pending_series:
            del self._pending_series[content_id]
        del self._pending[content_id]

        if content.content_type == "story_series":
            await query.edit_message_text(
                text=f"❌ СЕРИЯ ОТКЛОНЕНА\n\n{content.subtopic}"
            )
        else:
            await query.edit_message_caption(
                caption=f"❌ ОТКЛОНЕНО\n\n"
                        f"[{content.content_type}] {content.subtopic}"
            )

    def _build_keyboard(self, content_id: str) -> InlineKeyboardMarkup:
        """Build inline keyboard for moderation."""
        keyboard = [
            [
                InlineKeyboardButton("✅ Одобрить", callback_data=f"approve:{content_id}"),
                InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit:{content_id}"),
            ],
            [
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject:{content_id}"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    async def send_for_moderation(
        self,
        content_id: str,
        content_type: str,
        topic: str,
        subtopic: str,
        text: str,
        video_path: Optional[Path] = None,
        photo_path: Optional[Path] = None,
    ) -> bool:
        """
        Send content to moderator for review.

        Args:
            content_id: Unique content identifier
            content_type: "story" or "post"
            topic: Category name
            subtopic: Subtopic name
            text: Generated text
            video_path: Path to video file (for stories)
            photo_path: Path to photo file

        Returns:
            True if sent successfully
        """
        if not self.app:
            logger.error("Bot app not initialized. Call build_app() first.")
            return False

        # Store pending content
        self._pending[content_id] = PendingContent(
            content_id=content_id,
            content_type=content_type,
            topic=topic,
            subtopic=subtopic,
            text=text,
            video_path=video_path,
            photo_path=photo_path,
        )

        caption = (
            f"📝 Контент для модерации\n\n"
            f"[{content_type.upper()}] {subtopic}\n"
            f"Категория: {topic}\n\n"
            f"Текст:\n{text}"
        )

        keyboard = self._build_keyboard(content_id)

        try:
            bot = self.app.bot

            if video_path and video_path.exists():
                with open(video_path, "rb") as video_file:
                    await bot.send_video(
                        chat_id=self.moderator_chat_id,
                        video=video_file,
                        caption=caption,
                        reply_markup=keyboard,
                    )
            elif photo_path and photo_path.exists():
                with open(photo_path, "rb") as photo_file:
                    await bot.send_photo(
                        chat_id=self.moderator_chat_id,
                        photo=photo_file,
                        caption=caption,
                        reply_markup=keyboard,
                    )
            else:
                await bot.send_message(
                    chat_id=self.moderator_chat_id,
                    text=caption,
                    reply_markup=keyboard,
                )

            logger.info(f"Sent content for moderation: {content_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send content: {e}")
            return False

    async def send_series_for_moderation(
        self,
        content_id: str,
        topic: str,
        subtopic: str,
        stories: list[dict],
    ) -> bool:
        """
        Send story series to moderator for review.

        Sends all videos as a media group, then a summary message with buttons.

        Args:
            content_id: Unique content identifier
            topic: Category name
            subtopic: Subtopic name
            stories: List of dicts with 'order', 'text', 'video_path' keys

        Returns:
            True if sent successfully
        """
        if not self.app:
            logger.error("Bot app not initialized. Call build_app() first.")
            return False

        # Store pending series
        series_items = [
            StorySeriesItem(
                order=s.get("order", i + 1),
                text=s["text"],
                video_path=Path(s["video_path"]),
            )
            for i, s in enumerate(stories)
        ]

        self._pending_series[content_id] = PendingStorySeries(
            content_id=content_id,
            topic=topic,
            subtopic=subtopic,
            stories=series_items,
        )

        # Also store as pending content for unified handling
        combined_text = "\n\n".join([
            f"#{s.order}: {s.text}"
            for s in series_items
        ])

        self._pending[content_id] = PendingContent(
            content_id=content_id,
            content_type="story_series",
            topic=topic,
            subtopic=subtopic,
            text=combined_text,
            video_path=series_items[0].video_path if series_items else None,
            photo_path=None,
        )

        try:
            bot = self.app.bot

            # Send intro message
            await bot.send_message(
                chat_id=self.moderator_chat_id,
                text=f"📚 СЕРИЯ STORIES для модерации\n\n"
                     f"[{len(stories)} историй] {subtopic}\n"
                     f"Категория: {topic}\n\n"
                     f"Сейчас отправлю все видео..."
            )

            # Send videos individually with their texts
            for i, story_item in enumerate(series_items):
                if story_item.video_path.exists():
                    caption = f"#{story_item.order}/{len(series_items)}: {story_item.text}"
                    with open(story_item.video_path, "rb") as video_file:
                        await bot.send_video(
                            chat_id=self.moderator_chat_id,
                            video=video_file,
                            caption=caption[:1024],  # Telegram caption limit
                        )
                else:
                    logger.warning(f"Video not found: {story_item.video_path}")

            # Send summary with buttons
            summary_text = (
                f"📋 Серия готова к модерации\n\n"
                f"Тема: {subtopic}\n"
                f"Количество: {len(stories)} историй\n\n"
                f"Тексты:\n" +
                "\n".join([f"#{s.order}: {s.text}" for s in series_items])
            )

            keyboard = self._build_keyboard(content_id)

            await bot.send_message(
                chat_id=self.moderator_chat_id,
                text=summary_text[:4096],  # Telegram message limit
                reply_markup=keyboard,
            )

            logger.info(f"Sent story series for moderation: {content_id} ({len(stories)} stories)")
            return True

        except Exception as e:
            logger.error(f"Failed to send story series: {e}")
            return False

    async def send_publish_notification(
        self,
        subtopic: str,
        published: int,
        total: int,
        media_ids: list[str],
    ) -> bool:
        """
        Send notification about successful story publication.

        Args:
            subtopic: Topic name that was published
            published: Number of successfully published stories
            total: Total number of stories attempted
            media_ids: List of Instagram media IDs

        Returns:
            True if notification sent successfully
        """
        if not self.app:
            logger.error("Bot app not initialized. Call build_app() first.")
            return False

        # Format media IDs (truncate if too long)
        if media_ids:
            ids_str = ", ".join(media_ids[:3])
            if len(media_ids) > 3:
                ids_str += f"... (+{len(media_ids) - 3})"
        else:
            ids_str = "-"

        # Build message
        if published == total:
            status = "✅ ОПУБЛИКОВАНО"
        elif published > 0:
            status = "⚠️ ЧАСТИЧНО ОПУБЛИКОВАНО"
        else:
            status = "❌ ОШИБКА ПУБЛИКАЦИИ"

        message = (
            f"{status}\n\n"
            f"Тема: {subtopic}\n"
            f"Историй: {published}/{total}\n"
            f"ID: {ids_str}"
        )

        try:
            await self.app.bot.send_message(
                chat_id=self.moderator_chat_id,
                text=message,
            )
            logger.info(f"Sent publish notification: {subtopic} ({published}/{total})")
            return True

        except Exception as e:
            logger.error(f"Failed to send publish notification: {e}")
            return False

    def run_polling(self):
        """Run bot with polling (blocking)."""
        if not self.app:
            self.build_app()
        self.app.run_polling()

    async def start(self):
        """Start bot (non-blocking, for integration with other async code)."""
        if not self.app:
            self.build_app()
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

    async def stop(self):
        """Stop bot."""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
