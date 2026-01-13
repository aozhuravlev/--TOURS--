"""
Configuration management for tours.batumi Instagram automation.

Loads settings from .env file and provides typed access to all configuration values.
"""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


# Project root directory (parent of config/)
PROJECT_ROOT = Path(__file__).parent.parent.resolve()


@dataclass
class APIConfig:
    """External API credentials."""
    perplexity_key: str
    deepseek_key: str
    unsplash_key: Optional[str] = None


@dataclass
class TelegramConfig:
    """Telegram bot settings."""
    bot_token: str
    moderator_chat_id: int


@dataclass
class InstagramConfig:
    """Instagram Graph API settings."""
    business_account_id: str
    access_token: str
    facebook_page_id: str


@dataclass
class PathsConfig:
    """File system paths."""
    photos: Path
    music: Path
    content_history: Path
    output: Path
    prompts: Path
    topics: Path


@dataclass
class ScheduleConfig:
    """Publication schedule settings."""
    publish_hour_start: int
    publish_hour_end: int


@dataclass
class AntiRepeatConfig:
    """Content rotation cooldowns in days."""
    subtopic_cooldown: int
    photo_cooldown: int
    music_cooldown: int


@dataclass
class VideoConfig:
    """Video generation settings."""
    story_duration: int  # seconds
    bitrate: str
    resolution: tuple[int, int] = (1080, 1920)  # width x height for Stories


@dataclass
class Settings:
    """Main settings container."""
    api: APIConfig
    telegram: TelegramConfig
    instagram: InstagramConfig
    paths: PathsConfig
    schedule: ScheduleConfig
    anti_repeat: AntiRepeatConfig
    video: VideoConfig
    log_level: str


def load_settings(env_path: Optional[Path] = None) -> Settings:
    """
    Load settings from .env file.

    Args:
        env_path: Optional path to .env file. Defaults to PROJECT_ROOT/.env

    Returns:
        Settings object with all configuration values

    Raises:
        ValueError: If required environment variables are missing
    """
    if env_path is None:
        env_path = PROJECT_ROOT / ".env"

    load_dotenv(env_path)

    def get_required(key: str) -> str:
        """Get required environment variable or raise error."""
        value = os.getenv(key)
        if not value:
            raise ValueError(f"Required environment variable {key} is not set")
        return value

    def get_optional(key: str, default: str = "") -> str:
        """Get optional environment variable with default."""
        return os.getenv(key, default)

    def get_int(key: str, default: int) -> int:
        """Get integer environment variable with default."""
        value = os.getenv(key)
        return int(value) if value else default

    # Build configuration objects
    api = APIConfig(
        perplexity_key=get_required("PERPLEXITY_API_KEY"),
        deepseek_key=get_required("DEEPSEEK_API_KEY"),
        unsplash_key=get_optional("UNSPLASH_ACCESS_KEY") or None,
    )

    telegram = TelegramConfig(
        bot_token=get_required("TELEGRAM_BOT_TOKEN"),
        moderator_chat_id=int(get_required("TELEGRAM_MODERATOR_CHAT_ID")),
    )

    instagram = InstagramConfig(
        business_account_id=get_required("INSTAGRAM_BUSINESS_ACCOUNT_ID"),
        access_token=get_required("INSTAGRAM_ACCESS_TOKEN"),
        facebook_page_id=get_required("FACEBOOK_PAGE_ID"),
    )

    paths = PathsConfig(
        photos=PROJECT_ROOT / get_optional("MEDIA_PHOTOS_PATH", "media/photos"),
        music=PROJECT_ROOT / get_optional("MEDIA_MUSIC_PATH", "media/music"),
        content_history=PROJECT_ROOT / get_optional("CONTENT_HISTORY_PATH", "data/content_history.json"),
        output=PROJECT_ROOT / get_optional("OUTPUT_PATH", "output"),
        prompts=PROJECT_ROOT / "prompts",
        topics=PROJECT_ROOT / "config" / "topics.json",
    )

    schedule = ScheduleConfig(
        publish_hour_start=get_int("PUBLISH_HOUR_START", 8),
        publish_hour_end=get_int("PUBLISH_HOUR_END", 9),
    )

    anti_repeat = AntiRepeatConfig(
        subtopic_cooldown=get_int("SUBTOPIC_COOLDOWN_DAYS", 7),
        photo_cooldown=get_int("PHOTO_COOLDOWN_DAYS", 30),
        music_cooldown=get_int("MUSIC_COOLDOWN_DAYS", 14),
    )

    video = VideoConfig(
        story_duration=get_int("STORY_DURATION_SECONDS", 15),
        bitrate=get_optional("VIDEO_BITRATE", "4000k"),
    )

    return Settings(
        api=api,
        telegram=telegram,
        instagram=instagram,
        paths=paths,
        schedule=schedule,
        anti_repeat=anti_repeat,
        video=video,
        log_level=get_optional("LOG_LEVEL", "INFO"),
    )


def get_settings() -> Settings:
    """
    Get settings singleton.

    For testing, use load_settings() directly with custom env_path.
    """
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


# Global settings singleton (lazy loaded)
_settings: Optional[Settings] = None
