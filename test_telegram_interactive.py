#!/usr/bin/env python3
"""
Interactive Telegram bot test with moderation workflow.
Bot will listen for moderator actions.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
import os
import logging

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

from src.modules.telegram_bot import ModerationBot


async def on_approve(content_id: str, text: str):
    """Called when moderator approves content."""
    print("\n" + "=" * 40)
    print("ОДОБРЕНО!")
    print("=" * 40)
    print(f"Content ID: {content_id}")
    print(f"Text: {text}")
    print("=" * 40 + "\n")


async def on_reject(content_id: str):
    """Called when moderator rejects content."""
    print("\n" + "=" * 40)
    print("ОТКЛОНЕНО!")
    print("=" * 40)
    print(f"Content ID: {content_id}")
    print("=" * 40 + "\n")


async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_MODERATOR_CHAT_ID")

    if not token or not chat_id:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_MODERATOR_CHAT_ID in .env")
        return

    print("\n" + "=" * 60)
    print("TELEGRAM BOT - Interactive Test")
    print("=" * 60)

    bot = ModerationBot(
        token=token,
        moderator_chat_id=int(chat_id),
        on_approve=on_approve,
        on_reject=on_reject,
    )

    bot.build_app()

    # Send test content
    print("\n1. Sending test content to moderator...")
    await bot.app.initialize()
    await bot.app.start()

    test_video = Path("output")
    video_files = list(test_video.glob("story_*.mp4"))
    video_path = video_files[-1] if video_files else None

    success = await bot.send_for_moderation(
        content_id="test_interactive",
        content_type="story",
        topic="Тестовая категория",
        subtopic="Тестовая подтема",
        text="Это тестовое сообщение для проверки модерации.\n\nНажми кнопку чтобы проверить.",
        video_path=video_path,
    )

    if success:
        print("   ОТПРАВЛЕНО! Проверь Telegram.")
    else:
        print("   Ошибка отправки!")
        return

    print("\n2. Bot is now listening for your actions...")
    print("   - Press APPROVE/EDIT/REJECT in Telegram")
    print("   - Press Ctrl+C to stop\n")

    # Start polling to receive updates
    await bot.app.updater.start_polling()

    try:
        # Keep running until interrupted
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n\nStopping bot...")
    finally:
        await bot.app.updater.stop()
        await bot.app.stop()
        await bot.app.shutdown()

    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
