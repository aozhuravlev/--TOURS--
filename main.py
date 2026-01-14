#!/usr/bin/env python3
"""
tours.batumi Instagram Automation - Main Entry Point

Usage:
    python main.py                  # Run full system (scheduler + bot)
    python main.py generate         # Generate one story now
    python main.py generate --post  # Generate one post now
    python main.py stats            # Show system statistics
    python main.py test             # Run integration test
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
    use_image_search: bool = True,
    use_text_overlay: bool = True,
) -> Orchestrator:
    """Create and configure orchestrator."""
    return Orchestrator(
        perplexity_api_key=os.getenv("PERPLEXITY_API_KEY"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
        unsplash_api_key=os.getenv("UNSPLASH_ACCESS_KEY"),
        pexels_api_key=os.getenv("PEXELS_API_KEY"),
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
        use_image_search=use_image_search,
        use_text_overlay=use_text_overlay,
    )


def create_telegram_bot(orchestrator: Orchestrator) -> ModerationBot:
    """Create and configure Telegram bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_MODERATOR_CHAT_ID")

    if not token or not chat_id:
        logger.warning("Telegram bot not configured (missing token or chat_id)")
        return None

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

    bot = ModerationBot(
        token=token,
        moderator_chat_id=int(chat_id),
        on_approve=on_approve,
        on_reject=on_reject,
    )

    return bot


def cmd_generate(args):
    """Generate content now."""
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))

    logger.info("Starting content generation...")

    use_image_search = not getattr(args, "no_image_search", False)
    use_text_overlay = not getattr(args, "no_overlay", False)

    orchestrator = create_orchestrator(
        use_image_search=use_image_search,
        use_text_overlay=use_text_overlay,
    )

    if args.post:
        content = orchestrator.generate_post()
        content_type = "Post"
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

    # Schedule tasks
    gen_time = scheduler.schedule_daily_generation()
    pub_time = scheduler.schedule_daily_publishing()
    scheduler.schedule_auto_approval(check_interval_hours=1)

    logger.info(f"Scheduled generation at {gen_time}")
    logger.info(f"Scheduled publishing at {pub_time}")

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
    gen_parser.add_argument("--static", action="store_true", help="Disable Ken Burns effect (static image)")
    gen_parser.add_argument("--no-image-search", action="store_true", help="Use local photos only (no Unsplash)")
    gen_parser.add_argument("--no-overlay", action="store_true", help="Disable text overlay on video")

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
