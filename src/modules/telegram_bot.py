"""
Telegram Bot for content moderation.

Provides interface for moderator to:
- View generated content (video + text)
- Edit text before publishing
- Approve or reject content
"""

import logging
import asyncio
import tempfile
import io
import json
from pathlib import Path
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass, asdict
from enum import Enum

from PIL import Image
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


@dataclass
class PendingStoryForModeration:
    """Single story in moderation (photo+text, no video yet)."""
    order: int
    text: str
    photo_path: Path
    angle: str = ""
    keywords: str = ""  # For result metadata
    status: str = "pending"  # "pending", "approved", "edited", "deleted"
    edited_text: Optional[str] = None
    message_id: Optional[int] = None


@dataclass
class PendingSeriesForModeration:
    """Story series in moderation (photos+texts, no videos yet)."""
    content_id: str
    topic: str  # category_name
    subtopic: str
    stories: list[PendingStoryForModeration]
    music_path: Path
    ken_burns: bool
    story_duration: Optional[float]
    category_id: str = ""  # For history recording
    prepared_result: any = None  # PreparedStorySeriesResult from orchestrator (not serialized)


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
        on_finish_moderation: Optional[Callable[[str, list, any], Awaitable[None]]] = None,
    ):
        """
        Initialize moderation bot.

        Args:
            token: Telegram bot token
            moderator_chat_id: Chat ID of moderator
            on_approve: Callback when content is approved (content_id, text)
            on_reject: Callback when content is rejected (content_id)
            on_finish_moderation: Callback when moderation is finished
                (content_id, approved_stories, prepared_result)
        """
        self.token = token
        self.moderator_chat_id = moderator_chat_id
        self.on_approve = on_approve
        self.on_reject = on_reject
        self.on_finish_moderation = on_finish_moderation

        # Store pending edits: chat_id -> content_id
        self._editing: dict[int, str] = {}
        # Store pending edits for specific story: chat_id -> (content_id, order)
        self._editing_story: dict[int, tuple[str, int]] = {}
        # Store content data: content_id -> PendingContent
        self._pending: dict[str, PendingContent] = {}
        # Store pending series: content_id -> PendingStorySeries
        self._pending_series: dict[str, PendingStorySeries] = {}
        # Store prepared series for moderation: content_id -> PendingSeriesForModeration
        self._pending_prepared_series: dict[str, PendingSeriesForModeration] = {}

        self.app: Optional[Application] = None

        # File for persisting pending series (so Docker bot can load data from manual generation)
        self._persistence_file = Path("data/pending_series.json")

    def _save_pending_series(self) -> None:
        """Save pending prepared series to file for cross-process persistence."""
        try:
            data = {}
            for content_id, series in self._pending_prepared_series.items():
                data[content_id] = {
                    "content_id": series.content_id,
                    "topic": series.topic,
                    "subtopic": series.subtopic,
                    "category_id": series.category_id,
                    "music_path": str(series.music_path),
                    "ken_burns": series.ken_burns,
                    "story_duration": series.story_duration,
                    "stories": [
                        {
                            "order": s.order,
                            "text": s.text,
                            "photo_path": str(s.photo_path),
                            "angle": s.angle,
                            "keywords": s.keywords,
                            "status": s.status,
                            "edited_text": s.edited_text,
                            "message_id": s.message_id,
                        }
                        for s in series.stories
                    ],
                }

            self._persistence_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._persistence_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.debug(f"Saved {len(data)} pending series to {self._persistence_file}")

        except Exception as e:
            logger.error(f"Failed to save pending series: {e}")

    def _load_pending_series(self) -> None:
        """Load pending prepared series from file."""
        if not self._persistence_file.exists():
            return

        try:
            with open(self._persistence_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for content_id, series_data in data.items():
                if content_id not in self._pending_prepared_series:
                    stories = [
                        PendingStoryForModeration(
                            order=s["order"],
                            text=s["text"],
                            photo_path=Path(s["photo_path"]),
                            angle=s.get("angle", ""),
                            keywords=s.get("keywords", ""),
                            status=s.get("status", "pending"),
                            edited_text=s.get("edited_text"),
                            message_id=s.get("message_id"),
                        )
                        for s in series_data["stories"]
                    ]

                    self._pending_prepared_series[content_id] = PendingSeriesForModeration(
                        content_id=series_data["content_id"],
                        topic=series_data["topic"],
                        subtopic=series_data["subtopic"],
                        stories=stories,
                        music_path=Path(series_data["music_path"]),
                        ken_burns=series_data.get("ken_burns", True),
                        story_duration=series_data.get("story_duration"),
                        category_id=series_data.get("category_id", ""),
                        prepared_result=None,  # Reconstructed in _finish_moderation
                    )

            logger.debug(f"Loaded {len(data)} pending series from {self._persistence_file}")

        except Exception as e:
            logger.error(f"Failed to load pending series: {e}")

    def _delete_series_from_file(self, content_id: str) -> None:
        """Remove a series from the persistence file."""
        if not self._persistence_file.exists():
            return

        try:
            with open(self._persistence_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            if content_id in data:
                del data[content_id]

                with open(self._persistence_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                logger.debug(f"Deleted series {content_id} from persistence file")

        except Exception as e:
            logger.error(f"Failed to delete series from file: {e}")

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

    def _convert_photo_for_telegram(self, photo_path: Path) -> io.BytesIO:
        """
        Convert photo to Telegram-compatible format (JPEG).

        Telegram supports: JPG, PNG, WebP (up to 5MB for photos).
        This converts AVIF, HEIC, and other formats to JPEG.
        Also resizes if too large and applies EXIF orientation.

        Returns:
            BytesIO buffer with JPEG data
        """
        from PIL import ImageOps
        MAX_SIZE = 1280  # Max dimension for Telegram photos

        try:
            with Image.open(photo_path) as img:
                # Apply EXIF orientation (fixes rotated photos)
                img = ImageOps.exif_transpose(img)

                # Convert to RGB if necessary (removes alpha, handles RGBA)
                if img.mode in ('RGBA', 'P', 'LA'):
                    # Create white background for transparency
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')

                # Resize if too large
                if img.width > MAX_SIZE or img.height > MAX_SIZE:
                    img.thumbnail((MAX_SIZE, MAX_SIZE), Image.Resampling.LANCZOS)

                # Save to buffer as JPEG
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=85, optimize=True)
                buffer.seek(0)
                return buffer

        except Exception as e:
            logger.error(f"Failed to convert photo {photo_path}: {e}")
            raise

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
        order = int(parts[2]) if len(parts) > 2 else None

        # Legacy actions (for single content / old series)
        if action == "approve" and content_id:
            await self._approve_content(query, content_id)
        elif action == "edit" and content_id:
            await self._start_edit(query, content_id)
        elif action == "reject" and content_id:
            await self._reject_content(query, content_id)
        elif action == "cancel_edit":
            await self._cancel_edit(query)
        # New per-story actions
        elif action == "story_ok" and content_id and order is not None:
            await self._approve_story(query, content_id, order)
        elif action == "story_edit" and content_id and order is not None:
            await self._start_story_edit(query, content_id, order)
        elif action == "story_del" and content_id and order is not None:
            await self._delete_story(query, content_id, order)
        elif action == "cancel_story_edit":
            await self._cancel_story_edit(query)
        elif action == "finish" and content_id:
            await self._finish_moderation(query, content_id)

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages (for editing)."""
        chat_id = update.effective_chat.id

        # Check for story-level editing first
        if chat_id in self._editing_story:
            content_id, order = self._editing_story[chat_id]
            new_text = update.message.text

            series = self._pending_prepared_series.get(content_id)
            if not series:
                # Try loading from file (for cross-process persistence)
                self._load_pending_series()
                series = self._pending_prepared_series.get(content_id)

            if series:
                # Find and update story
                for story in series.stories:
                    if story.order == order:
                        story.edited_text = new_text
                        story.status = "edited"
                        break

                # Persist change
                self._save_pending_series()

            del self._editing_story[chat_id]

            await update.message.reply_text(
                f"✅ Текст истории #{order} обновлён!\n\n"
                f"Новый текст:\n{new_text}\n\n"
                f"Нажмите «📹 Завершить модерацию» когда будете готовы."
            )
            return

        # Legacy single content editing
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

    async def _approve_story(self, query, content_id: str, order: int):
        """Approve a single story in prepared series."""
        series = self._pending_prepared_series.get(content_id)
        if not series:
            # Try loading from file (for cross-process persistence)
            self._load_pending_series()
            series = self._pending_prepared_series.get(content_id)

        if not series:
            await query.edit_message_caption(
                caption="⚠️ Серия не найдена или уже обработана."
            )
            return

        # Find story by order
        story = None
        for s in series.stories:
            if s.order == order:
                story = s
                break

        if not story:
            await query.edit_message_caption(
                caption="⚠️ История не найдена."
            )
            return

        # Update status
        story.status = "approved"

        # Persist change
        self._save_pending_series()

        # Update caption to show approval
        await query.edit_message_caption(
            caption=f"✅ #{story.order}/{len(series.stories)} ОДОБРЕНО\n\n{story.text}"
        )

        logger.info(f"Story {order} approved for {content_id}")

    async def _start_story_edit(self, query, content_id: str, order: int):
        """Start editing mode for a specific story."""
        series = self._pending_prepared_series.get(content_id)
        if not series:
            # Try loading from file (for cross-process persistence)
            self._load_pending_series()
            series = self._pending_prepared_series.get(content_id)

        if not series:
            await query.edit_message_caption(
                caption="⚠️ Серия не найдена или уже обработана."
            )
            return

        # Find story by order
        story = None
        for s in series.stories:
            if s.order == order:
                story = s
                break

        if not story:
            await query.edit_message_caption(
                caption="⚠️ История не найдена."
            )
            return

        chat_id = query.message.chat_id
        self._editing_story[chat_id] = (content_id, order)

        keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_story_edit")]]

        await query.edit_message_caption(
            caption=f"✏️ РЕДАКТИРОВАНИЕ #{story.order}\n\n"
                    f"Текущий текст:\n{story.text}\n\n"
                    f"Отправьте новый текст сообщением:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _cancel_story_edit(self, query):
        """Cancel story editing mode."""
        chat_id = query.message.chat_id
        edit_info = self._editing_story.get(chat_id)

        if chat_id in self._editing_story:
            del self._editing_story[chat_id]

        if edit_info:
            content_id, order = edit_info
            series = self._pending_prepared_series.get(content_id)
            if not series:
                # Try loading from file (for cross-process persistence)
                self._load_pending_series()
                series = self._pending_prepared_series.get(content_id)
            if series:
                story = None
                for s in series.stories:
                    if s.order == order:
                        story = s
                        break

                if story:
                    keyboard = self._build_per_story_keyboard(content_id, order)
                    await query.edit_message_caption(
                        caption=f"#{story.order}/{len(series.stories)}\n\n{story.text}",
                        reply_markup=keyboard,
                    )
                    return

        await query.edit_message_caption(
            caption="Редактирование отменено."
        )

    async def _delete_story(self, query, content_id: str, order: int):
        """Mark a story as deleted."""
        series = self._pending_prepared_series.get(content_id)
        if not series:
            # Try loading from file (for cross-process persistence)
            self._load_pending_series()
            series = self._pending_prepared_series.get(content_id)

        if not series:
            await query.edit_message_caption(
                caption="⚠️ Серия не найдена или уже обработана."
            )
            return

        # Find story by order
        story = None
        for s in series.stories:
            if s.order == order:
                story = s
                break

        if not story:
            await query.edit_message_caption(
                caption="⚠️ История не найдена."
            )
            return

        # Update status
        story.status = "deleted"

        # Persist change
        self._save_pending_series()

        # Update caption to show deletion
        await query.edit_message_caption(
            caption=f"❌ #{story.order}/{len(series.stories)} УДАЛЕНО\n\n"
                    f"~~{story.text}~~"
        )

        logger.info(f"Story {order} deleted for {content_id}")

    def _reconstruct_prepared_result(self, series: PendingSeriesForModeration):
        """
        Reconstruct PreparedStorySeriesResult from serialized data.

        Used when series was loaded from file and prepared_result is None.
        """
        # Lazy import to avoid circular dependencies
        from src.orchestrator import PreparedStorySeriesResult, PreparedStory
        from src.modules.topic_selector import SelectedTopic
        from src.modules.media_manager import MediaFile

        # Reconstruct topic
        topic = SelectedTopic(
            category_id=series.category_id or "",
            category_name=series.topic,
            subtopic=series.subtopic,
        )

        # Reconstruct music
        music = MediaFile(path=series.music_path)

        # Reconstruct prepared stories
        prepared_stories = [
            PreparedStory(
                order=s.order,
                angle=s.angle,
                text=s.text,
                keywords=s.keywords,
                photo=MediaFile(path=s.photo_path),
            )
            for s in series.stories
        ]

        return PreparedStorySeriesResult(
            topic=topic,
            facts="",  # Not needed for rendering
            stories=prepared_stories,
            music=music,
            ken_burns=series.ken_burns,
            story_duration=series.story_duration,
            success=True,
        )

    async def _finish_moderation(self, query, content_id: str):
        """Finish moderation and trigger video rendering."""
        series = self._pending_prepared_series.get(content_id)
        if not series:
            # Try loading from file (for cross-process persistence)
            self._load_pending_series()
            series = self._pending_prepared_series.get(content_id)

        if not series:
            # Check if it's an old-style series
            if content_id in self._pending_series:
                # Handle as legacy approval
                await self._approve_content(query, content_id)
                return

            await query.edit_message_text(
                text="⚠️ Серия не найдена или уже обработана."
            )
            return

        # Collect approved stories
        approved_stories = []
        for story in series.stories:
            if story.status in ("approved", "edited", "pending"):
                # Include pending as approved by default
                text = story.edited_text if story.edited_text else story.text
                approved_stories.append({
                    "order": story.order,
                    "text": text,
                    "photo_path": str(story.photo_path),
                })

        deleted_count = sum(1 for s in series.stories if s.status == "deleted")

        if not approved_stories:
            await query.edit_message_text(
                text=f"❌ Все истории удалены. Серия отклонена.\n\n"
                     f"Тема: {series.subtopic}"
            )
            # Clean up memory and file
            del self._pending_prepared_series[content_id]
            self._delete_series_from_file(content_id)
            if self.on_reject:
                await self.on_reject(content_id)
            return

        # Update message to show processing
        await query.edit_message_text(
            text=f"⏳ РЕНДЕРИНГ ВИДЕО...\n\n"
                 f"Тема: {series.subtopic}\n"
                 f"Историй к рендерингу: {len(approved_stories)}\n"
                 f"Удалено: {deleted_count}\n\n"
                 f"Пожалуйста, подождите..."
        )

        # Reconstruct prepared_result if it was loaded from file (None)
        prepared_result = series.prepared_result
        if prepared_result is None:
            logger.info(f"Reconstructing prepared_result for {content_id} from serialized data")
            prepared_result = self._reconstruct_prepared_result(series)

        # Call finish moderation callback
        if self.on_finish_moderation:
            await self.on_finish_moderation(
                content_id,
                approved_stories,
                prepared_result,
            )

        # Clean up memory and file
        del self._pending_prepared_series[content_id]
        self._delete_series_from_file(content_id)

        logger.info(f"Moderation finished for {content_id}: {len(approved_stories)} approved, {deleted_count} deleted")

    async def _reject_content(self, query, content_id: str):
        """Reject content."""
        content = self._pending.get(content_id)
        if not content:
            # Try prepared series (new workflow)
            if content_id in self._pending_prepared_series:
                series = self._pending_prepared_series[content_id]
                if self.on_reject:
                    await self.on_reject(content_id)
                del self._pending_prepared_series[content_id]
                self._delete_series_from_file(content_id)
                await query.edit_message_text(
                    text=f"❌ СЕРИЯ ОТКЛОНЕНА\n\n{series.subtopic}"
                )
                return

            # Try legacy series
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
        if content_id in self._pending_prepared_series:
            del self._pending_prepared_series[content_id]
            self._delete_series_from_file(content_id)
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

    def _build_per_story_keyboard(self, content_id: str, order: int) -> InlineKeyboardMarkup:
        """Build inline keyboard for per-story moderation."""
        keyboard = [
            [
                InlineKeyboardButton("✅ OK", callback_data=f"story_ok:{content_id}:{order}"),
                InlineKeyboardButton("✏️ Изменить", callback_data=f"story_edit:{content_id}:{order}"),
                InlineKeyboardButton("❌ Удалить", callback_data=f"story_del:{content_id}:{order}"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    def _build_finish_moderation_keyboard(self, content_id: str) -> InlineKeyboardMarkup:
        """Build keyboard for finish moderation button."""
        keyboard = [
            [
                InlineKeyboardButton("📹 Завершить модерацию", callback_data=f"finish:{content_id}"),
            ],
            [
                InlineKeyboardButton("❌ Отменить всё", callback_data=f"reject:{content_id}"),
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

    async def send_prepared_series_for_moderation(
        self,
        content_id: str,
        topic: str,
        subtopic: str,
        stories: list[dict],
        music_path: Path,
        ken_burns: bool = True,
        story_duration: Optional[float] = None,
        category_id: str = "",
        prepared_result: any = None,
    ) -> bool:
        """
        Send prepared story series (photos + texts) to moderator for review.

        Unlike send_series_for_moderation, this sends PHOTOS (not videos) with
        per-story moderation buttons. Videos are rendered only after approval.

        Args:
            content_id: Unique content identifier
            topic: Category name
            subtopic: Subtopic name
            stories: List of dicts with 'order', 'text', 'photo_path', 'angle', 'keywords' keys
            music_path: Path to music file
            ken_burns: Whether to use Ken Burns effect when rendering
            story_duration: Duration per story
            category_id: Category ID for history recording
            prepared_result: PreparedStorySeriesResult from orchestrator

        Returns:
            True if sent successfully
        """
        if not self.app:
            logger.error("Bot app not initialized. Call build_app() first.")
            return False

        # Create pending stories for moderation
        pending_stories = [
            PendingStoryForModeration(
                order=s.get("order", i + 1),
                text=s["text"],
                photo_path=Path(s["photo_path"]),
                angle=s.get("angle", ""),
                keywords=s.get("keywords", ""),
                status="pending",
            )
            for i, s in enumerate(stories)
        ]

        # Store pending series
        self._pending_prepared_series[content_id] = PendingSeriesForModeration(
            content_id=content_id,
            topic=topic,
            subtopic=subtopic,
            stories=pending_stories,
            music_path=music_path,
            ken_burns=ken_burns,
            story_duration=story_duration,
            category_id=category_id,
            prepared_result=prepared_result,
        )

        # Persist to file for cross-process access
        self._save_pending_series()

        try:
            bot = self.app.bot

            # Send intro message
            await bot.send_message(
                chat_id=self.moderator_chat_id,
                text=f"📸 СЕРИЯ STORIES для модерации\n\n"
                     f"[{len(stories)} историй] {subtopic}\n"
                     f"Категория: {topic}\n\n"
                     f"Для каждой истории: ✅ OK, ✏️ Изменить или ❌ Удалить\n"
                     f"В конце нажмите «📹 Завершить модерацию»"
            )

            # Send each photo with text and per-story buttons
            for story in pending_stories:
                if story.photo_path.exists():
                    caption = f"#{story.order}/{len(pending_stories)}\n\n{story.text}"
                    keyboard = self._build_per_story_keyboard(content_id, story.order)

                    # Convert photo to Telegram-compatible format
                    try:
                        photo_buffer = self._convert_photo_for_telegram(story.photo_path)
                    except Exception as e:
                        logger.error(f"Failed to convert photo {story.photo_path}: {e}")
                        continue

                    with photo_buffer as photo_file:
                        message = await bot.send_photo(
                            chat_id=self.moderator_chat_id,
                            photo=photo_file,
                            caption=caption[:1024],
                            reply_markup=keyboard,
                        )
                        # Store message_id for later updates
                        story.message_id = message.message_id
                else:
                    logger.warning(f"Photo not found: {story.photo_path}")

            # Send finish moderation button
            finish_keyboard = self._build_finish_moderation_keyboard(content_id)
            await bot.send_message(
                chat_id=self.moderator_chat_id,
                text=f"📋 Готово для модерации: {len(stories)} историй\n\n"
                     f"Когда закончите - нажмите «📹 Завершить модерацию»",
                reply_markup=finish_keyboard,
            )

            logger.info(f"Sent prepared series for moderation: {content_id} ({len(stories)} stories)")
            return True

        except Exception as e:
            logger.error(f"Failed to send prepared series: {e}")
            return False

    async def send_render_complete_notification(
        self,
        subtopic: str,
        story_count: int,
        video_paths: list[Path],
    ) -> bool:
        """
        Send notification that video rendering is complete.

        Args:
            subtopic: Topic name
            story_count: Number of rendered videos
            video_paths: List of video file paths

        Returns:
            True if notification sent successfully
        """
        if not self.app:
            logger.error("Bot app not initialized. Call build_app() first.")
            return False

        message = (
            f"🎬 ВИДЕО ГОТОВЫ\n\n"
            f"Тема: {subtopic}\n"
            f"Историй: {story_count}\n\n"
            f"Видео сохранены и готовы к публикации."
        )

        try:
            await self.app.bot.send_message(
                chat_id=self.moderator_chat_id,
                text=message,
            )
            logger.info(f"Sent render complete notification: {subtopic}")
            return True
        except Exception as e:
            logger.error(f"Failed to send render notification: {e}")
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
