#!/usr/bin/env python3
"""
Full pipeline test: Generate -> Upload -> Send to Telegram -> Simulate Instagram
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

from src.orchestrator import Orchestrator
from src.modules.video_composer import VideoConfig
from src.modules.telegram_bot import ModerationBot
from src.modules.media_uploader import get_uploader_config, MediaUploader
from src.modules.publisher import InstagramPublisher


async def test_full_pipeline():
    """Test complete pipeline: generate -> telegram -> instagram."""

    print("\n" + "=" * 60)
    print("FULL PIPELINE TEST")
    print("=" * 60)

    # 1. Create orchestrator
    print("\n1. Creating orchestrator...")
    orchestrator = Orchestrator(
        perplexity_api_key=os.getenv("PERPLEXITY_API_KEY"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
        topics_path=Path("config/topics.json"),
        prompts_dir=Path("prompts"),
        photos_path=Path("media/photos"),
        music_path=Path("media/music"),
        output_dir=Path("output"),
        history_path=Path("data/content_history.json"),
        video_config=VideoConfig(duration=15, preset="medium"),
    )
    print("   OK")

    # 2. Generate story
    print("\n2. Generating story...")
    content = orchestrator.generate_story(ken_burns=True)
    if not content:
        print("   FAILED!")
        return
    print(f"   Topic: {content.topic.subtopic}")
    print(f"   Caption: {content.caption[:60]}...")
    print(f"   Video: {content.video_path}")
    print(f"   Size: {content.video_path.stat().st_size / 1024 / 1024:.1f} MB")

    # 3. Upload to media hosting
    print("\n3. Uploading to media hosting...")
    uploader_config = get_uploader_config()
    uploader = MediaUploader(uploader_config)

    video_url = uploader.upload_file(content.video_path)
    if not video_url:
        print("   FAILED!")
        return
    print(f"   URL: {video_url}")

    # 4. Send to Telegram moderator
    print("\n4. Sending to Telegram moderator...")
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_MODERATOR_CHAT_ID")

    if not token or not chat_id:
        print("   SKIPPED (no credentials)")
    else:
        bot = ModerationBot(token=token, moderator_chat_id=int(chat_id))
        bot.build_app()

        # Initialize bot for sending
        await bot.app.initialize()

        # Use short ID (Telegram limits callback_data to 64 bytes)
        import hashlib
        short_id = hashlib.md5(content.topic.subtopic.encode()).hexdigest()[:8]
        success = await bot.send_for_moderation(
            content_id=f"test_{short_id}",
            content_type="story",
            topic=content.topic.category_name,
            subtopic=content.topic.subtopic,
            text=content.caption,
            video_path=content.video_path,
        )

        if success:
            print("   SENT! Check Telegram.")
        else:
            print("   FAILED to send")

        await bot.app.shutdown()

    # 5. Test Instagram API (without actually publishing)
    print("\n5. Testing Instagram API connection...")
    ig_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    ig_account = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")

    if not ig_token or not ig_account:
        print("   SKIPPED (no credentials)")
    else:
        publisher = InstagramPublisher(
            access_token=ig_token,
            instagram_account_id=ig_account,
        )
        if publisher.verify_token():
            print("   Instagram API: OK")
            print(f"   Video URL ready for publishing: {video_url}")
        else:
            print("   Instagram API: FAILED")
        publisher.close()

    print("\n" + "=" * 60)
    print("PIPELINE TEST COMPLETE")
    print("=" * 60)

    print("\nNext steps:")
    print("1. Check Telegram - you should see the story for moderation")
    print("2. Approve/Edit/Reject the content")
    print(f"3. Video URL for Instagram: {video_url}")

    orchestrator.close()


if __name__ == "__main__":
    asyncio.run(test_full_pipeline())
