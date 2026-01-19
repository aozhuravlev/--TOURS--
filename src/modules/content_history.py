"""
Content history tracking to prevent repetition.

Tracks published content and enforces cooldown periods for:
- Subtopics (default: 7 days)
- Photos (default: 90 days)
- Music tracks (default: 14 days)
"""

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class Publication:
    """Record of a single published content item."""
    date: str  # ISO format: YYYY-MM-DD
    content_type: str  # "story" or "post"
    category_id: str
    subtopic: str
    photo_path: str
    music_path: str
    text: str
    status: str = "published"  # "pending", "published", "rejected"
    instagram_id: Optional[str] = None


@dataclass
class ContentHistory:
    """
    Manages content publication history and cooldown tracking.

    Provides methods to:
    - Check if a subtopic/photo/music is available (not on cooldown)
    - Record new publications
    - Query publication history
    """
    history_path: Path
    subtopic_cooldown_days: int = 7
    photo_cooldown_days: int = 90
    music_cooldown_days: int = 14

    # Internal state
    publications: list[Publication] = field(default_factory=list)
    last_used_subtopics: dict[str, str] = field(default_factory=dict)  # subtopic -> date
    last_used_photos: dict[str, str] = field(default_factory=dict)  # path -> date
    last_used_music: dict[str, str] = field(default_factory=dict)  # path -> date

    def __post_init__(self):
        """Load existing history from file."""
        self._load()

    def _load(self) -> None:
        """Load history from JSON file."""
        if not self.history_path.exists():
            logger.info(f"No history file found at {self.history_path}, starting fresh")
            return

        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Load publications
            for pub_data in data.get("publications", []):
                self.publications.append(Publication(**pub_data))

            # Load last_used mappings
            self.last_used_subtopics = data.get("last_used", {}).get("subtopics", {})
            self.last_used_photos = data.get("last_used", {}).get("photos", {})
            self.last_used_music = data.get("last_used", {}).get("music", {})

            logger.info(f"Loaded {len(self.publications)} publications from history")

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to load history from {self.history_path}: {e}")
            raise

    def save(self) -> None:
        """Save history to JSON file."""
        # Ensure directory exists
        self.history_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "publications": [asdict(pub) for pub in self.publications],
            "last_used": {
                "subtopics": self.last_used_subtopics,
                "photos": self.last_used_photos,
                "music": self.last_used_music,
            },
        }

        with open(self.history_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.debug(f"Saved history to {self.history_path}")

    def is_subtopic_available(self, subtopic: str, reference_date: Optional[date] = None) -> bool:
        """
        Check if a subtopic is available (not on cooldown).

        Args:
            subtopic: The subtopic name to check
            reference_date: Date to check against (defaults to today)

        Returns:
            True if subtopic can be used, False if on cooldown
        """
        if reference_date is None:
            reference_date = date.today()

        last_used = self.last_used_subtopics.get(subtopic)
        if not last_used:
            return True

        last_date = date.fromisoformat(last_used)
        days_since = (reference_date - last_date).days

        available = days_since >= self.subtopic_cooldown_days
        if not available:
            logger.debug(f"Subtopic '{subtopic}' on cooldown: {days_since}/{self.subtopic_cooldown_days} days")

        return available

    def is_photo_available(self, photo_path: str, reference_date: Optional[date] = None) -> bool:
        """Check if a photo is available (not on cooldown)."""
        if reference_date is None:
            reference_date = date.today()

        # Normalize path for comparison
        normalized_path = str(Path(photo_path))

        last_used = self.last_used_photos.get(normalized_path)
        if not last_used:
            return True

        last_date = date.fromisoformat(last_used)
        days_since = (reference_date - last_date).days

        return days_since >= self.photo_cooldown_days

    def is_music_available(self, music_path: str, reference_date: Optional[date] = None) -> bool:
        """Check if a music track is available (not on cooldown)."""
        if reference_date is None:
            reference_date = date.today()

        normalized_path = str(Path(music_path))

        last_used = self.last_used_music.get(normalized_path)
        if not last_used:
            return True

        last_date = date.fromisoformat(last_used)
        days_since = (reference_date - last_date).days

        return days_since >= self.music_cooldown_days

    def get_available_subtopics(
        self,
        all_subtopics: list[str],
        reference_date: Optional[date] = None
    ) -> list[str]:
        """
        Filter list of subtopics to only those available.

        Args:
            all_subtopics: Full list of possible subtopics
            reference_date: Date to check against

        Returns:
            List of subtopics not on cooldown
        """
        return [s for s in all_subtopics if self.is_subtopic_available(s, reference_date)]

    def record_publication(
        self,
        content_type: str,
        category_id: str,
        subtopic: str,
        photo_path: str,
        music_path: str,
        text: str,
        status: str = "pending",
        publication_date: Optional[date] = None,
    ) -> Publication:
        """
        Record a new publication.

        Args:
            content_type: "story" or "post"
            category_id: Category ID from topics.json
            subtopic: Selected subtopic
            photo_path: Path to photo used
            music_path: Path to music track used
            text: Generated text content
            status: Publication status (pending/published/rejected)
            publication_date: Date of publication (defaults to today)

        Returns:
            The created Publication record
        """
        if publication_date is None:
            publication_date = date.today()

        date_str = publication_date.isoformat()

        publication = Publication(
            date=date_str,
            content_type=content_type,
            category_id=category_id,
            subtopic=subtopic,
            photo_path=str(photo_path),
            music_path=str(music_path),
            text=text,
            status=status,
        )

        self.publications.append(publication)

        # Update last_used tracking
        self.last_used_subtopics[subtopic] = date_str
        self.last_used_photos[str(Path(photo_path))] = date_str
        self.last_used_music[str(Path(music_path))] = date_str

        self.save()

        logger.info(f"Recorded {content_type} publication: {subtopic}")

        return publication

    def update_publication_status(
        self,
        publication: Publication,
        status: str,
        instagram_id: Optional[str] = None
    ) -> None:
        """
        Update the status of a publication.

        Args:
            publication: Publication record to update
            status: New status
            instagram_id: Optional Instagram post ID after publishing
        """
        publication.status = status
        if instagram_id:
            publication.instagram_id = instagram_id

        self.save()

        logger.info(f"Updated publication status: {publication.subtopic} -> {status}")

    def record_story_series(
        self,
        category_id: str,
        subtopic: str,
        photo_paths: list[str],
        music_path: str,
        texts: list[str],
        status: str = "pending",
        publication_date: Optional[date] = None,
    ) -> Publication:
        """
        Record a story series publication.

        This properly tracks all photos used in the series for cooldown.

        Args:
            category_id: Category ID from topics.json
            subtopic: Selected subtopic
            photo_paths: List of paths to photos used (one per story)
            music_path: Path to music track used
            texts: List of texts for each story
            status: Publication status
            publication_date: Date of publication

        Returns:
            The created Publication record
        """
        if publication_date is None:
            publication_date = date.today()

        date_str = publication_date.isoformat()

        # Create combined text preview
        combined_text = f"[Series: {len(texts)} stories]\n" + "\n".join([
            f"#{i + 1}: {t[:50]}{'...' if len(t) > 50 else ''}"
            for i, t in enumerate(texts)
        ])

        publication = Publication(
            date=date_str,
            content_type="story_series",
            category_id=category_id,
            subtopic=subtopic,
            photo_path=photo_paths[0] if photo_paths else "",  # Store first for reference
            music_path=str(music_path),
            text=combined_text,
            status=status,
        )

        self.publications.append(publication)

        # Update last_used tracking for subtopic and music
        self.last_used_subtopics[subtopic] = date_str
        self.last_used_music[str(Path(music_path))] = date_str

        # Track ALL photos used in the series
        for photo_path in photo_paths:
            self.last_used_photos[str(Path(photo_path))] = date_str

        self.save()

        logger.info(f"Recorded story_series publication: {subtopic} ({len(photo_paths)} photos)")

        return publication

    def get_pending_publications(self) -> list[Publication]:
        """Get all publications awaiting moderation/publishing."""
        return [p for p in self.publications if p.status == "pending"]

    def get_stats(self) -> dict:
        """Get usage statistics."""
        total = len(self.publications)
        by_status = {}
        by_type = {}
        by_category = {}

        for pub in self.publications:
            by_status[pub.status] = by_status.get(pub.status, 0) + 1
            by_type[pub.content_type] = by_type.get(pub.content_type, 0) + 1
            by_category[pub.category_id] = by_category.get(pub.category_id, 0) + 1

        return {
            "total_publications": total,
            "by_status": by_status,
            "by_type": by_type,
            "by_category": by_category,
            "tracked_subtopics": len(self.last_used_subtopics),
            "tracked_photos": len(self.last_used_photos),
            "tracked_music": len(self.last_used_music),
        }
