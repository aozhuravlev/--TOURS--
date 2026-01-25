#!/usr/bin/env python3
"""
tours.batumi Instagram Automation - Main Entry Point

Usage:
    python main.py                      # Run full system (scheduler + bot)
    python main.py generate             # Generate one story now
    python main.py generate --post      # Generate one post now
    python main.py generate --series    # Generate story series (3-7 connected stories)
    python main.py stats                # Show system statistics
    python main.py test                 # Run integration test
"""

import sys
import asyncio
import logging
import argparse
from pathlib import Path

from dotenv import load_dotenv
import os

# Project root
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load environment
load_dotenv(PROJECT_ROOT / ".env")

from src.orchestrator import Orchestrator
from src.modules.video_composer import VideoConfig
from src.modules.telegram_bot import ModerationBot
from src.scheduler import ContentScheduler, create_default_scheduler

# Setup logging
def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(PROJECT_ROOT / "logs" / "app.log"),
        ],
    )

logger = logging.getLogger(__name__)


def create_orchestrator(
    use_text_overlay: bool = True,
) -> Orchestrator:
    """Create and configure orchestrator."""
    return Orchestrator(
        perplexity_api_key=os.getenv("PERPLEXITY_API_KEY"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
        # Image search disabled - using local photo library only
        unsplash_api_key=None,
        pexels_api_key=None,
        topics_path=PROJECT_ROOT / "config" / "topics.json",
        prompts_dir=PROJECT_ROOT / "prompts",
        photos_path=PROJECT_ROOT / "media" / "photos",
        music_path=PROJECT_ROOT / "media" / "music",
        output_dir=PROJECT_ROOT / "output",
        history_path=PROJECT_ROOT / "data" / "content_history.json",
        fonts_dir=PROJECT_ROOT / "assets" / "fonts",
        video_config=VideoConfig(
            duration=int(os.getenv("STORY_DURATION_SECONDS", "15")),
            preset="medium",
        ),
        subtopic_cooldown_days=int(os.getenv("SUBTOPIC_COOLDOWN_DAYS", "7")),
        photo_cooldown_days=int(os.getenv("PHOTO_COOLDOWN_DAYS", "30")),
        music_cooldown_days=int(os.getenv("MUSIC_COOLDOWN_DAYS", "14")),
        use_image_search=False,
        use_text_overlay=use_text_overlay,
    )


def create_telegram_bot(orchestrator: Orchestrator) -> ModerationBot:
    """Create and configure Telegram bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_MODERATOR_CHAT_ID")

    if not token or not chat_id:
        logger.warning("Telegram bot not configured (missing token or chat_id)")
        return None

    # We'll set this reference after bot creation for the callback
    bot_ref = [None]

    async def on_approve(content_id: str, text: str):
        logger.info(f"Content approved via Telegram: {content_id}")
        # Find and approve publication
        for pub in orchestrator.history.publications:
            if pub.subtopic in content_id:
                pub.text = text
                orchestrator.approve_content(pub)
                break

    async def on_reject(content_id: str):
        logger.info(f"Content rejected via Telegram: {content_id}")
        for pub in orchestrator.history.publications:
            if pub.subtopic in content_id:
                orchestrator.reject_content(pub)
                break

    async def on_finish_moderation(content_id: str, approved_stories: list, prepared_result):
        """Called when moderation is finished - render videos and send to moderator."""
        logger.info(f"Moderation finished for {content_id}: {len(approved_stories)} stories approved")

        if not approved_stories:
            logger.warning("No approved stories to render")
            return

        # Render videos for approved stories only
        result = orchestrator.render_approved_stories(prepared_result, approved_stories)

        if result and result.success:
            logger.info(f"Rendered {result.story_count} videos for {result.topic.subtopic}")

            # Send videos to moderator for manual Instagram publishing
            if bot_ref[0]:
                await bot_ref[0].send_videos_for_manual_publish(
                    subtopic=result.topic.subtopic,
                    story_count=result.story_count,
                    video_paths=result.video_paths,
                )
        else:
            logger.error(f"Failed to render videos for {content_id}")
            # Notify about failure
            if bot_ref[0] and bot_ref[0].app:
                try:
                    await bot_ref[0].app.bot.send_message(
                        chat_id=int(chat_id),
                        text=f"❌ ОШИБКА РЕНДЕРИНГА\n\nНе удалось отрендерить видео для: {content_id}"
                    )
                except Exception as e:
                    logger.error(f"Failed to send error notification: {e}")

    bot = ModerationBot(
        token=token,
        moderator_chat_id=int(chat_id),
        on_approve=on_approve,
        on_reject=on_reject,
        on_finish_moderation=on_finish_moderation,
    )

    # Store bot reference for use in callback
    bot_ref[0] = bot

    return bot


def cmd_generate(args):
    """Generate content now."""
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))

    logger.info("Starting content generation...")

    use_text_overlay = not getattr(args, "no_overlay", False)

    orchestrator = create_orchestrator(
        use_text_overlay=use_text_overlay,
    )

    if args.series:
        # Check if we should use the new workflow (prepare only, no render)
        if getattr(args, "send_telegram", False):
            # New workflow: prepare series (no video rendering) and send for moderation
            result = orchestrator.prepare_story_series(
                subtopic=getattr(args, "subtopic", None),
                ken_burns=not args.static,
                min_count=getattr(args, "min_stories", 3),
                max_count=getattr(args, "max_stories", 7),
            )
            if result and result.success:
                print(f"\n{'=' * 60}")
                print(f"Prepared Story Series ({result.story_count} stories)")
                print("=" * 60)
                print(f"Topic: [{result.topic.category_name}] {result.topic.subtopic}")
                print(f"\nStories (photos ready, videos will be rendered after moderation):")
                for story in result.stories:
                    print(f"\n  #{story.order} [{story.angle}]")
                    print(f"    Text: {story.text}")
                    print(f"    Photo: {story.photo.filename}")
                print("=" * 60)

                print("\nSending to Telegram for moderation...")
                bot = create_telegram_bot(orchestrator)
                if bot:
                    bot.build_app()
                    stories_data = [
                        {
                            "order": s.order,
                            "text": s.text,
                            "photo_path": str(s.photo.path),
                            "angle": s.angle,
                            "keywords": s.keywords,
                        }
                        for s in result.stories
                    ]
                    import hashlib
                    short_hash = hashlib.md5(result.topic.subtopic.encode()).hexdigest()[:8]
                    content_id = f"series_{short_hash}"

                    async def send():
                        await bot.start()
                        success = await bot.send_prepared_series_for_moderation(
                            content_id=content_id,
                            topic=result.topic.category_name,
                            subtopic=result.topic.subtopic,
                            stories=stories_data,
                            music_path=result.music.path,
                            ken_burns=result.ken_burns,
                            story_duration=result.story_duration,
                            category_id=result.topic.category_id,
                            font_path=result.font_path,
                            prepared_result=result,
                        )
                        # Keep bot running to handle callbacks
                        if success:
                            print("Sent to Telegram! Waiting for moderation...")
                            print("Press Ctrl+C to stop waiting.")
                            try:
                                while True:
                                    await asyncio.sleep(1)
                            except asyncio.CancelledError:
                                pass
                        await bot.stop()
                        return success

                    try:
                        asyncio.run(send())
                    except KeyboardInterrupt:
                        print("\nStopped.")
                else:
                    print("Telegram bot not configured")
            else:
                error = result.error if result else "Unknown error"
                print(f"Story series preparation failed: {error}")
                sys.exit(1)
        else:
            # Old workflow: generate full videos immediately (for local testing)
            result = orchestrator.generate_story_series(
                subtopic=getattr(args, "subtopic", None),
                ken_burns=not args.static,
                min_count=getattr(args, "min_stories", 3),
                max_count=getattr(args, "max_stories", 7),
            )
            if result and result.success:
                print(f"\n{'=' * 60}")
                print(f"Generated Story Series ({result.story_count} stories)")
                print("=" * 60)
                print(f"Topic: [{result.topic.category_name}] {result.topic.subtopic}")
                print(f"\nStories:")
                for story in result.stories:
                    print(f"\n  #{story.order} [{story.angle}]")
                    print(f"    Text: {story.text}")
                    print(f"    Video: {story.video_path.name}")
                    size = story.video_path.stat().st_size / 1024 / 1024
                    print(f"    Size: {size:.1f} MB")
                print("=" * 60)
            else:
                error = result.error if result else "Unknown error"
                print(f"Story series generation failed: {error}")
                sys.exit(1)
    elif args.post:
        content = orchestrator.generate_post()
        content_type = "Post"
        if content:
            print(f"\n{'=' * 60}")
            print(f"Generated {content_type}")
            print("=" * 60)
            print(f"Topic: [{content.topic.category_name}] {content.topic.subtopic}")
            print(f"\nCaption:\n{content.caption}")
            if content.video_path:
                print(f"\nVideo: {content.video_path}")
                print(f"Size: {content.video_path.stat().st_size / 1024 / 1024:.1f} MB")
            print("=" * 60)
        else:
            print("Generation failed!")
            sys.exit(1)
    else:
        content = orchestrator.generate_story(ken_burns=not args.static)
        content_type = "Story"
        if content:
            print(f"\n{'=' * 60}")
            print(f"Generated {content_type}")
            print("=" * 60)
            print(f"Topic: [{content.topic.category_name}] {content.topic.subtopic}")
            print(f"\nCaption:\n{content.caption}")
            if content.video_path:
                print(f"\nVideo: {content.video_path}")
                print(f"Size: {content.video_path.stat().st_size / 1024 / 1024:.1f} MB")
            print("=" * 60)
        else:
            print("Generation failed!")
            sys.exit(1)

    orchestrator.close()


def cmd_stats(args):
    """Show system statistics."""
    setup_logging("WARNING")

    orchestrator = create_orchestrator()
    stats = orchestrator.get_stats()

    print("\n" + "=" * 60)
    print("TOURS.BATUMI - System Statistics")
    print("=" * 60)

    print("\nTopics:")
    print(f"  Categories: {stats['topics']['total_categories']}")
    print(f"  Subtopics: {stats['topics']['total_subtopics']} total, {stats['topics']['available_subtopics']} available")

    print("\nMedia:")
    print(f"  Photos: {stats['media']['photos']['total']}")
    for cat, count in stats['media']['photos']['by_category'].items():
        print(f"    - {cat}: {count}")
    print(f"  Music: {stats['media']['music']['total']}")

    print("\nPublications:")
    print(f"  Total: {stats['history']['total_publications']}")
    for status, count in stats['history'].get('by_status', {}).items():
        print(f"    - {status}: {count}")

    print("\n" + "=" * 60)

    orchestrator.close()


def cmd_test(args):
    """Run integration test."""
    setup_logging("INFO")

    print("\n" + "=" * 60)
    print("TOURS.BATUMI - Integration Test")
    print("=" * 60)

    # Test orchestrator
    print("\n1. Testing Orchestrator...")
    orchestrator = create_orchestrator()
    print("   Orchestrator created")

    # Test generation
    print("\n2. Testing Story Generation...")
    content = orchestrator.generate_story()
    if content:
        print(f"   Generated: {content.topic.subtopic}")
        print(f"   Caption: {content.caption[:50]}...")
        print(f"   Video: {content.video_path}")
    else:
        print("   FAILED!")

    # Test Telegram bot (without sending)
    print("\n3. Testing Telegram Bot...")
    bot = create_telegram_bot(orchestrator)
    if bot:
        bot.build_app()
        print("   Bot configured")
    else:
        print("   Bot not configured (missing credentials)")

    # Stats
    print("\n4. System Stats:")
    stats = orchestrator.get_stats()
    print(f"   Topics: {stats['topics']['available_subtopics']} available")
    print(f"   Publications: {stats['history']['total_publications']}")

    orchestrator.close()

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


async def cmd_run(args):
    """Run full system with scheduler and bot."""
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))

    logger.info("Starting tours.batumi automation system...")

    # Create components
    orchestrator = create_orchestrator()
    bot = create_telegram_bot(orchestrator)

    # Create scheduler
    scheduler = create_default_scheduler(
        orchestrator=orchestrator,
        telegram_bot=bot,
    )

    # Schedule daily generation
    gen_time = scheduler.schedule_daily_generation()
    scheduler.schedule_auto_approval(check_interval_hours=1)

    logger.info(f"Scheduled generation at {gen_time}")

    # Start Telegram bot if configured
    if bot:
        bot.build_app()
        await bot.start()
        logger.info("Telegram bot started")

    # Run scheduler
    try:
        await scheduler.run_loop()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        scheduler.stop()
        if bot:
            await bot.stop()
        orchestrator.close()

    logger.info("System stopped")


def main():
    parser = argparse.ArgumentParser(
        description="tours.batumi Instagram Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # generate command
    gen_parser = subparsers.add_parser("generate", help="Generate content now")
    gen_parser.add_argument("--post", action="store_true", help="Generate post instead of story")
    gen_parser.add_argument("--series", action="store_true", help="Generate story series (3-7 connected stories)")
    gen_parser.add_argument("--subtopic", type=str, help="Specific subtopic to use (e.g., 'Аренда велосипедов')")
    gen_parser.add_argument("--min-stories", type=int, default=3, help="Minimum stories in series (default: 3)")
    gen_parser.add_argument("--max-stories", type=int, default=7, help="Maximum stories in series (default: 7)")
    gen_parser.add_argument("--static", action="store_true", help="Disable Ken Burns effect (static image)")
    gen_parser.add_argument("--no-overlay", action="store_true", help="Disable text overlay on video")
    gen_parser.add_argument("--send-telegram", action="store_true", help="Send to Telegram for moderation")

    # stats command
    subparsers.add_parser("stats", help="Show system statistics")

    # test command
    subparsers.add_parser("test", help="Run integration test")

    # run command (default)
    subparsers.add_parser("run", help="Run full system")

    args = parser.parse_args()

    # Ensure logs directory exists
    (PROJECT_ROOT / "logs").mkdir(exist_ok=True)

    if args.command == "generate":
        cmd_generate(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "test":
        cmd_test(args)
    elif args.command == "run":
        asyncio.run(cmd_run(args))
    else:
        # Default: show help
        parser.print_help()


if __name__ == "__main__":
    main()
