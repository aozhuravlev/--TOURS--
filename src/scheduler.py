"""
Task Scheduler for automated content workflow.

Manages scheduled tasks:
- Morning generation (08:00-09:00): Generate content for tomorrow
- Morning publishing (08:00-09:00): Publish approved content
- Auto-approval: Approve pending content after 24h
"""

import logging
import random
import asyncio
import os
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Callable, Optional, Awaitable
from dataclasses import dataclass
from enum import Enum

import schedule

logger = logging.getLogger(__name__)

# Lock file to prevent concurrent publishing
PUBLISH_LOCK_FILE = Path("/tmp/tours_publish.lock")


class TaskType(Enum):
    """Types of scheduled tasks."""
    GENERATE = "generate"
    PUBLISH = "publish"
    AUTO_APPROVE = "auto_approve"


@dataclass
class ScheduledTask:
    """Represents a scheduled task."""
    task_type: TaskType
    scheduled_time: time
    last_run: Optional[datetime] = None
    enabled: bool = True


class ContentScheduler:
    """
    Manages scheduled content generation and publishing.

    Workflow:
    1. Day 1, 08:00-09:00: Generate content for tomorrow
    2. Moderator reviews (24h window)
    3. Day 2, 08:00-09:00: Publish approved content
    4. If no moderation action: auto-approve and publish
    """

    def __init__(
        self,
        generate_callback: Callable[[], Awaitable[bool]],
        publish_callback: Callable[[], Awaitable[bool]],
        auto_approve_callback: Optional[Callable[[], Awaitable[bool]]] = None,
        hour_start: int = 8,
        hour_end: int = 9,
        timezone_offset: int = 3,  # MSK = UTC+3
    ):
        """
        Initialize scheduler.

        Args:
            generate_callback: Async function to call for content generation
            publish_callback: Async function to call for publishing
            auto_approve_callback: Optional async function for auto-approval
            hour_start: Start of publication window (hour)
            hour_end: End of publication window (hour)
            timezone_offset: Hours offset from UTC
        """
        self.generate_callback = generate_callback
        self.publish_callback = publish_callback
        self.auto_approve_callback = auto_approve_callback
        self.hour_start = hour_start
        self.hour_end = hour_end
        self.timezone_offset = timezone_offset

        self.tasks: list[ScheduledTask] = []
        self._running = False

    def _get_random_time(self) -> time:
        """Get random time within publication window."""
        hour = self.hour_start
        minute = random.randint(0, 59)

        if self.hour_end > self.hour_start:
            hour = random.randint(self.hour_start, self.hour_end - 1)

        return time(hour=hour, minute=minute)

    def schedule_daily_generation(self) -> str:
        """
        Schedule daily content generation.

        Returns:
            Scheduled time string
        """
        gen_time = self._get_random_time()
        time_str = gen_time.strftime("%H:%M")

        schedule.every().day.at(time_str).do(
            lambda: asyncio.create_task(self._run_generation())
        )

        self.tasks.append(ScheduledTask(
            task_type=TaskType.GENERATE,
            scheduled_time=gen_time,
        ))

        logger.info(f"Scheduled daily generation at {time_str}")
        return time_str

    def schedule_daily_publishing(self) -> str:
        """
        Schedule daily content publishing.

        Returns:
            Scheduled time string
        """
        pub_time = self._get_random_time()
        time_str = pub_time.strftime("%H:%M")

        schedule.every().day.at(time_str).do(
            lambda: asyncio.create_task(self._run_publishing())
        )

        self.tasks.append(ScheduledTask(
            task_type=TaskType.PUBLISH,
            scheduled_time=pub_time,
        ))

        logger.info(f"Scheduled daily publishing at {time_str}")
        return time_str

    def schedule_auto_approval(self, check_interval_hours: int = 1) -> None:
        """
        Schedule periodic auto-approval check.

        Args:
            check_interval_hours: Hours between checks
        """
        if not self.auto_approve_callback:
            logger.warning("No auto-approve callback set")
            return

        schedule.every(check_interval_hours).hours.do(
            lambda: asyncio.create_task(self._run_auto_approve())
        )

        logger.info(f"Scheduled auto-approval check every {check_interval_hours}h")

    async def _run_generation(self) -> None:
        """Execute generation task."""
        logger.info("Running scheduled generation...")
        try:
            success = await self.generate_callback()
            if success:
                logger.info("Generation completed successfully")
            else:
                logger.warning("Generation returned failure")

            # Update last_run
            for task in self.tasks:
                if task.task_type == TaskType.GENERATE:
                    task.last_run = datetime.now()
                    break

        except Exception as e:
            logger.error(f"Generation failed: {e}")

    async def _run_publishing(self) -> None:
        """Execute publishing task."""
        logger.info("Running scheduled publishing...")
        try:
            success = await self.publish_callback()
            if success:
                logger.info("Publishing completed successfully")
            else:
                logger.warning("Publishing returned failure (no content?)")

            for task in self.tasks:
                if task.task_type == TaskType.PUBLISH:
                    task.last_run = datetime.now()
                    break

        except Exception as e:
            logger.error(f"Publishing failed: {e}")

    async def _run_auto_approve(self) -> None:
        """Execute auto-approval check."""
        logger.debug("Checking for auto-approval...")
        try:
            if self.auto_approve_callback:
                await self.auto_approve_callback()
        except Exception as e:
            logger.error(f"Auto-approval check failed: {e}")

    def run_once(self, task_type: TaskType) -> None:
        """
        Run a task immediately (for testing).

        Args:
            task_type: Type of task to run
        """
        if task_type == TaskType.GENERATE:
            asyncio.create_task(self._run_generation())
        elif task_type == TaskType.PUBLISH:
            asyncio.create_task(self._run_publishing())
        elif task_type == TaskType.AUTO_APPROVE:
            asyncio.create_task(self._run_auto_approve())

    async def run_loop(self, check_interval: int = 60) -> None:
        """
        Run scheduler loop.

        Args:
            check_interval: Seconds between schedule checks
        """
        self._running = True
        logger.info("Scheduler started")

        while self._running:
            schedule.run_pending()
            await asyncio.sleep(check_interval)

        logger.info("Scheduler stopped")

    def stop(self) -> None:
        """Stop scheduler loop."""
        self._running = False

    def get_status(self) -> dict:
        """Get scheduler status."""
        return {
            "running": self._running,
            "tasks": [
                {
                    "type": task.task_type.value,
                    "scheduled_time": task.scheduled_time.strftime("%H:%M"),
                    "last_run": task.last_run.isoformat() if task.last_run else None,
                    "enabled": task.enabled,
                }
                for task in self.tasks
            ],
            "pending_jobs": len(schedule.jobs),
        }

    def clear_all(self) -> None:
        """Clear all scheduled tasks."""
        schedule.clear()
        self.tasks.clear()
        logger.info("All scheduled tasks cleared")


def create_default_scheduler(
    orchestrator,
    telegram_bot=None,
    publisher=None,
    media_uploader=None,
) -> ContentScheduler:
    """
    Create scheduler with default callbacks.

    Args:
        orchestrator: Orchestrator instance
        telegram_bot: Optional ModerationBot instance
        publisher: Optional InstagramPublisher instance
        media_uploader: Optional MediaUploader instance for uploading videos

    Returns:
        Configured ContentScheduler
    """
    import hashlib

    async def generate_callback() -> bool:
        """Prepare story series (without rendering) and send to moderation."""
        # Use new prepare_story_series (no video rendering yet)
        result = orchestrator.prepare_story_series()
        if not result or not result.success:
            return False

        if telegram_bot:
            # Prepare stories data for telegram (photos, not videos)
            stories_data = [
                {
                    "order": story.order,
                    "text": story.text,
                    "photo_path": str(story.photo.path),
                    "angle": story.angle,
                    "keywords": story.keywords,
                }
                for story in result.stories
            ]

            # Use short content_id (Telegram callback_data limit is 64 bytes)
            short_hash = hashlib.md5(result.topic.subtopic.encode()).hexdigest()[:8]
            content_id = f"series_{short_hash}"

            await telegram_bot.send_prepared_series_for_moderation(
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

        return True

    async def publish_callback() -> bool:
        """
        Publish approved content OR auto-approve and publish pending content older than 24h.

        This unified approach ensures content is never stuck:
        - If manually approved → publish immediately
        - If pending > 24h without moderation → auto-approve and publish

        Uses a lock file to prevent concurrent publishing.
        """
        # Check for lock file to prevent concurrent publishing
        if PUBLISH_LOCK_FILE.exists():
            logger.warning("Publishing already in progress (lock file exists), skipping")
            return False

        # Create lock file
        try:
            PUBLISH_LOCK_FILE.touch()
            logger.debug("Created publish lock file")
        except Exception as e:
            logger.error(f"Failed to create lock file: {e}")
            return False

        try:
            return await _do_publish()
        finally:
            # Always remove lock file
            try:
                PUBLISH_LOCK_FILE.unlink(missing_ok=True)
                logger.debug("Removed publish lock file")
            except Exception as e:
                logger.warning(f"Failed to remove lock file: {e}")

    async def _do_publish() -> bool:
        """Internal publish logic."""
        pending_content = orchestrator.get_pending_content()
        now = datetime.now()

        # Collect content ready for publishing
        to_publish = []

        for publication in pending_content:
            if publication.status == "approved":
                # Already approved by moderator
                to_publish.append(publication)
            elif publication.status == "pending":
                # Check if older than 24h - auto-approve
                pub_date = datetime.fromisoformat(publication.date)
                age = now - pub_date

                if age > timedelta(hours=24):
                    logger.info(f"Auto-approving (>24h): {publication.subtopic}")
                    orchestrator.approve_content(publication)
                    to_publish.append(publication)

        if not to_publish:
            logger.info("No content ready for publishing")
            return False

        # Publish all ready content
        published_count = 0
        for publication in to_publish:
            if publisher and media_uploader:
                try:
                    # For story series, get video paths from output directory
                    from pathlib import Path
                    import os
                    output_dir = Path(os.getenv("OUTPUT_PATH", "output"))

                    # Find video files for this publication date
                    video_files = sorted(output_dir.glob(f"story_{publication.date.replace('-', '')}*.mp4"))

                    if not video_files:
                        logger.warning(f"No video files found for {publication.subtopic}")
                        orchestrator.mark_published(publication, "no_videos")
                        continue

                    # Upload videos and get public URLs
                    video_urls = []
                    for video_path in video_files:
                        url = media_uploader.upload_file(video_path)
                        if url:
                            video_urls.append(url)
                            logger.info(f"Uploaded: {video_path.name} -> {url}")
                        else:
                            logger.error(f"Failed to upload: {video_path}")

                    if not video_urls:
                        logger.error(f"No videos uploaded for {publication.subtopic}")
                        continue

                    # Publish to Instagram
                    result = publisher.publish_story_series(video_urls)

                    if result.success or result.partial_success:
                        media_ids_str = ",".join(result.media_ids[:3])
                        orchestrator.mark_published(publication, media_ids_str)

                        # Delete video files after successful publishing
                        if result.success:
                            for video_path in video_files:
                                try:
                                    video_path.unlink()
                                    logger.info(f"Deleted published video: {video_path.name}")
                                except Exception as e:
                                    logger.warning(f"Failed to delete {video_path.name}: {e}")

                        # Send notification to moderator
                        if telegram_bot:
                            await telegram_bot.send_publish_notification(
                                subtopic=publication.subtopic,
                                published=result.published,
                                total=result.total,
                                media_ids=result.media_ids,
                            )

                        published_count += 1
                        logger.info(f"Published: {publication.subtopic} ({result.published}/{result.total})")
                    else:
                        logger.error(f"Publishing failed: {publication.subtopic}")
                        for error in result.errors:
                            logger.error(f"  {error}")

                except Exception as e:
                    logger.error(f"Publishing error for {publication.subtopic}: {e}")
            else:
                logger.warning(f"Publisher/uploader not configured - marking as published: {publication.subtopic}")
                orchestrator.mark_published(publication, "no_publisher")
                published_count += 1

        logger.info(f"Publishing complete: {published_count} item(s)")
        return published_count > 0

    async def auto_approve_callback() -> bool:
        """
        Legacy auto-approve check - now handled by publish_callback.
        Kept for backwards compatibility but does nothing.
        """
        logger.debug("Auto-approve check skipped (handled by publish_callback)")
        return True

    return ContentScheduler(
        generate_callback=generate_callback,
        publish_callback=publish_callback,
        auto_approve_callback=auto_approve_callback,
    )
