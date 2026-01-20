#!/usr/bin/env python3
"""
Quick publish script for story series from output folder.

Usage:
    python scripts/publish_now.py                    # Publish all videos from output/
    python scripts/publish_now.py --dry-run          # Test without publishing
    python scripts/publish_now.py --upload-only      # Only upload to hosting
"""

import sys
import os
import logging
import argparse
import asyncio
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.modules.media_uploader import MediaUploader, get_uploader_config
from src.modules.publisher import InstagramPublisher
from src.modules.telegram_bot import ModerationBot

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def get_video_files(output_dir: Path) -> list[Path]:
    """Get all video files from output directory, sorted by name."""
    videos = sorted(output_dir.glob("*.mp4"))
    return videos


def upload_videos(videos: list[Path], dry_run: bool = False) -> list[str]:
    """Upload videos to hosting and return public URLs."""
    if dry_run:
        logger.info("[DRY RUN] Would upload videos:")
        for v in videos:
            logger.info(f"  - {v.name}")
        return [f"https://example.com/{v.name}" for v in videos]

    config = get_uploader_config()
    uploader = MediaUploader(config)

    # Test connection first
    logger.info("Testing SSH connection...")
    if not uploader.test_connection():
        logger.error("SSH connection failed!")
        return []

    # Ensure remote directory exists
    if not uploader.ensure_remote_dir():
        logger.error("Failed to create remote directory!")
        return []

    # Upload each video
    urls = []
    for i, video_path in enumerate(videos):
        logger.info(f"Uploading {i + 1}/{len(videos)}: {video_path.name}")
        url = uploader.upload_video(video_path)
        if url:
            urls.append(url)
            logger.info(f"  -> {url}")
        else:
            logger.error(f"  FAILED to upload {video_path.name}")

    return urls


def publish_stories(video_urls: list[str], dry_run: bool = False):
    """
    Publish stories to Instagram.

    Returns:
        SeriesPublishResult on success/partial success, None on failure
    """
    if dry_run:
        logger.info("[DRY RUN] Would publish stories:")
        for i, url in enumerate(video_urls):
            logger.info(f"  {i + 1}. {url}")
        return None

    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    account_id = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")

    if not access_token or not account_id:
        logger.error("Missing Instagram credentials in .env!")
        return None

    publisher = InstagramPublisher(
        access_token=access_token,
        instagram_account_id=account_id,
    )

    # Verify token first
    logger.info("Verifying Instagram token...")
    if not publisher.verify_token():
        logger.error("Instagram token verification failed!")
        publisher.close()
        return None

    # Publish series
    logger.info(f"Publishing {len(video_urls)} stories...")
    logger.info("This will take several minutes due to anti-detection delays.")
    logger.info("-" * 50)

    result = publisher.publish_story_series(video_urls)

    publisher.close()

    if result.success:
        logger.info("=" * 50)
        logger.info(f"SUCCESS! Published {result.published}/{result.total} stories")
        logger.info(f"Media IDs: {result.media_ids}")
        return result
    elif result.partial_success:
        logger.warning("=" * 50)
        logger.warning(f"PARTIAL SUCCESS: {result.published}/{result.total} stories")
        logger.warning(f"Errors: {result.errors}")
        return result
    else:
        logger.error("=" * 50)
        logger.error(f"FAILED to publish stories")
        logger.error(f"Errors: {result.errors}")
        return None


async def send_telegram_notification(result, subtopic: str) -> bool:
    """Send publication notification to Telegram."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_MODERATOR_CHAT_ID")

    if not token or not chat_id:
        logger.warning("Telegram not configured, skipping notification")
        return False

    bot = ModerationBot(token=token, moderator_chat_id=int(chat_id))
    bot.build_app()

    try:
        await bot.app.initialize()
        success = await bot.send_publish_notification(
            subtopic=subtopic,
            published=result.published,
            total=result.total,
            media_ids=result.media_ids,
        )
        await bot.app.shutdown()
        return success
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Publish story series to Instagram")
    parser.add_argument("--dry-run", action="store_true", help="Test without publishing")
    parser.add_argument("--upload-only", action="store_true", help="Only upload to hosting")
    parser.add_argument("--output-dir", type=str, default=str(PROJECT_ROOT / "output"),
                        help="Directory with video files")
    parser.add_argument("--subtopic", type=str, default="Story Series",
                        help="Subtopic name for notification")
    parser.add_argument("--no-notify", action="store_true",
                        help="Skip Telegram notification")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)

    # Get video files
    videos = get_video_files(output_dir)

    if not videos:
        logger.error(f"No video files found in {output_dir}")
        sys.exit(1)

    logger.info(f"Found {len(videos)} videos in {output_dir}")
    for v in videos:
        size_mb = v.stat().st_size / 1024 / 1024
        logger.info(f"  - {v.name} ({size_mb:.1f} MB)")

    # Upload
    logger.info("-" * 50)
    logger.info("Step 1: Uploading videos to hosting...")
    urls = upload_videos(videos, dry_run=args.dry_run)

    if not urls:
        logger.error("No videos uploaded!")
        sys.exit(1)

    logger.info(f"Uploaded {len(urls)} videos")

    if args.upload_only:
        logger.info("-" * 50)
        logger.info("Upload complete. URLs:")
        for url in urls:
            print(url)
        sys.exit(0)

    # Publish
    logger.info("-" * 50)
    logger.info("Step 2: Publishing to Instagram...")
    result = publish_stories(urls, dry_run=args.dry_run)

    if result:
        # Send Telegram notification
        if not args.dry_run and not args.no_notify:
            logger.info("-" * 50)
            logger.info("Step 3: Sending Telegram notification...")
            asyncio.run(send_telegram_notification(result, args.subtopic))

        logger.info("=" * 50)
        logger.info("DONE!")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
