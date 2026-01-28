"""
Task Scheduler for automated content workflow.

Manages scheduled tasks:
- Morning generation (08:00-09:00): Prepare content and send for moderation
- Auto-approval: Track history for pending content older than 24h
"""

import logging
import random
import asyncio
from datetime import datetime, time
from typing import Callable, Optional, Awaitable
from dataclasses import dataclass
from enum import Enum

import schedule

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """Types of scheduled tasks."""
    GENERATE = "generate"
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
    Manages scheduled content generation.

    Workflow:
    1. Morning (08:00-09:00): Prepare content and send to Telegram for moderation
    2. Moderator reviews (photos + text)
    3. After approval: Videos are rendered and sent to moderator
    4. Moderator manually publishes to Instagram
    """

    def __init__(
        self,
        generate_callback: Callable[[], Awaitable[bool]],
        auto_approve_callback: Optional[Callable[[], Awaitable[bool]]] = None,
        hour_start: int = 8,
        hour_end: int = 9,
        timezone_offset: int = 3,  # MSK = UTC+3
    ):
        """
        Initialize scheduler.

        Args:
            generate_callback: Async function to call for content generation
            auto_approve_callback: Optional async function for auto-approval
            hour_start: Start of generation window (hour)
            hour_end: End of generation window (hour)
            timezone_offset: Hours offset from UTC
        """
        self.generate_callback = generate_callback
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
) -> ContentScheduler:
    """
    Create scheduler with default callbacks.

    Args:
        orchestrator: Orchestrator instance
        telegram_bot: Optional ModerationBot instance

    Returns:
        Configured ContentScheduler
    """
    import hashlib

    async def generate_callback() -> bool:
        """Prepare story series (without rendering) and send to moderation."""
        # Use prepare_story_series (no video rendering yet)
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
                motion_effects=result.motion_effects,
                story_duration=result.story_duration,
                category_id=result.topic.category_id,
                font_path=result.font_path,
                prepared_result=result,
            )

        return True

    async def auto_approve_callback() -> bool:
        """
        Auto-approve check for history tracking.
        Content older than 24h without moderation is logged.
        """
        logger.debug("Auto-approve check (for history tracking)")
        return True

    return ContentScheduler(
        generate_callback=generate_callback,
        auto_approve_callback=auto_approve_callback,
    )
