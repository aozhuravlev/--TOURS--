"""
Topic selector for content generation.

Selects random category and subtopic from topics.json,
respecting content history cooldowns and photo availability.
"""

import json
import logging
import random
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Supported photo extensions (must match media_manager.py)
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".heif", ".heic"}


@dataclass
class SelectedTopic:
    """Result of topic selection."""
    category_id: str
    category_name: str
    subtopic: str


class TopicSelector:
    """
    Selects topics for content generation.

    Loads topics from JSON file and selects random category/subtopic
    while respecting cooldown periods from content history.
    """

    def __init__(
        self,
        topics_path: Path,
        content_history=None,  # Optional ContentHistory for cooldown checks
        photos_path: Optional[Path] = None,  # Path to photos directory for availability check
    ):
        """
        Initialize topic selector.

        Args:
            topics_path: Path to topics.json file
            content_history: Optional ContentHistory instance
            photos_path: Path to photos directory (if provided, topics without photos are filtered out)
        """
        self.topics_path = Path(topics_path)
        self.content_history = content_history
        self.photos_path = Path(photos_path) if photos_path else None
        self.categories: list[dict] = []

        self._load_topics()

    def _load_topics(self) -> None:
        """Load topics from JSON file."""
        if not self.topics_path.exists():
            raise FileNotFoundError(f"Topics file not found: {self.topics_path}")

        with open(self.topics_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.categories = data.get("categories", [])

        total_subtopics = sum(len(cat.get("subtopics", [])) for cat in self.categories)
        logger.info(f"Loaded {len(self.categories)} categories with {total_subtopics} subtopics")

    def _has_photos_for_subtopic(self, category_name: str, subtopic: str) -> bool:
        """
        Check if a subtopic folder has photos.

        Looks for photos in: photos_path/{category_name}/{subtopic}/
        Falls back to: photos_path/{category_name}/ if subtopic folder doesn't exist

        Args:
            category_name: Category name (e.g., "Грузинская кухня")
            subtopic: Subtopic name (e.g., "Хачапури по-аджарски")

        Returns:
            True if photos exist for this topic, False otherwise
        """
        if not self.photos_path:
            return True  # No photos path configured, assume all topics have photos

        # Try subtopic folder first
        subtopic_folder = self.photos_path / category_name / subtopic
        if subtopic_folder.exists() and subtopic_folder.is_dir():
            photos = [
                f for f in subtopic_folder.iterdir()
                if f.is_file() and f.suffix.lower() in PHOTO_EXTENSIONS
            ]
            if photos:
                return True

        # Try category folder
        category_folder = self.photos_path / category_name
        if category_folder.exists() and category_folder.is_dir():
            # Check for photos directly in category (not in subtopic subfolders)
            photos = [
                f for f in category_folder.iterdir()
                if f.is_file() and f.suffix.lower() in PHOTO_EXTENSIONS
            ]
            if photos:
                return True

            # Check all subtopic folders in category
            for subfolder in category_folder.iterdir():
                if subfolder.is_dir():
                    photos = [
                        f for f in subfolder.iterdir()
                        if f.is_file() and f.suffix.lower() in PHOTO_EXTENSIONS
                    ]
                    if photos:
                        return True

        logger.debug(f"No photos found for {category_name}/{subtopic}")
        return False

    def get_all_subtopics(self) -> list[tuple[str, str, str]]:
        """
        Get all subtopics as flat list.

        Returns:
            List of tuples (category_id, category_name, subtopic)
        """
        result = []
        for cat in self.categories:
            cat_id = cat["id"]
            cat_name = cat["name"]
            for subtopic in cat.get("subtopics", []):
                result.append((cat_id, cat_name, subtopic))
        return result

    def get_available_subtopics(self, check_photos: bool = True) -> list[tuple[str, str, str]]:
        """
        Get subtopics that are not on cooldown and have photos available.

        Args:
            check_photos: Whether to check for photo availability (default: True)

        Returns:
            List of available (category_id, category_name, subtopic) tuples
        """
        all_subtopics = self.get_all_subtopics()

        available = []
        for cat_id, cat_name, subtopic in all_subtopics:
            # Check cooldown
            if self.content_history and not self.content_history.is_subtopic_available(subtopic):
                continue

            # Check photo availability
            if check_photos and self.photos_path and not self._has_photos_for_subtopic(cat_name, subtopic):
                logger.debug(f"Skipping {cat_name}/{subtopic} - no photos available")
                continue

            available.append((cat_id, cat_name, subtopic))

        logger.debug(f"Available subtopics: {len(available)}/{len(all_subtopics)}")
        return available

    def select_random(
        self,
        category_id: Optional[str] = None,
        check_cooldown: bool = True,
        check_photos: bool = True,
    ) -> Optional[SelectedTopic]:
        """
        Select a random topic.

        Args:
            category_id: Optional category filter
            check_cooldown: Whether to check content history
            check_photos: Whether to check for photo availability

        Returns:
            SelectedTopic or None if no topics available
        """
        if check_cooldown or check_photos:
            candidates = self.get_available_subtopics(check_photos=check_photos)
            # If checking cooldown is disabled, add back cooldown topics
            if not check_cooldown:
                all_subtopics = self.get_all_subtopics()
                # Filter by photo availability only
                if check_photos and self.photos_path:
                    candidates = [
                        (cat_id, cat_name, sub) for cat_id, cat_name, sub in all_subtopics
                        if self._has_photos_for_subtopic(cat_name, sub)
                    ]
                else:
                    candidates = all_subtopics
        else:
            candidates = self.get_all_subtopics()

        if not candidates:
            logger.warning("No topics available for selection")
            return None

        # Filter by category if specified
        if category_id:
            candidates = [c for c in candidates if c[0] == category_id]
            if not candidates:
                logger.warning(f"No topics available in category: {category_id}")
                return None

        # Random selection
        cat_id, cat_name, subtopic = random.choice(candidates)

        result = SelectedTopic(
            category_id=cat_id,
            category_name=cat_name,
            subtopic=subtopic,
        )

        logger.info(f"Selected topic: [{cat_name}] {subtopic}")
        return result

    def select_for_category(self, category_name: str) -> Optional[SelectedTopic]:
        """
        Select a random subtopic from specified category by name.

        Args:
            category_name: Category name (e.g., "Грузинская кухня")

        Returns:
            SelectedTopic or None
        """
        # Find category by name
        for cat in self.categories:
            if cat["name"].lower() == category_name.lower():
                return self.select_random(category_id=cat["id"])

        logger.warning(f"Category not found: {category_name}")
        return None

    def select_specific(self, subtopic: str) -> Optional[SelectedTopic]:
        """
        Select a specific subtopic by name.

        Searches all categories for matching subtopic.

        Args:
            subtopic: Subtopic name (e.g., "Аренда велосипедов")

        Returns:
            SelectedTopic or None if not found
        """
        subtopic_lower = subtopic.lower().strip()

        for cat in self.categories:
            for sub in cat.get("subtopics", []):
                if sub.lower().strip() == subtopic_lower:
                    result = SelectedTopic(
                        category_id=cat["id"],
                        category_name=cat["name"],
                        subtopic=sub,
                    )
                    logger.info(f"Selected specific topic: [{cat['name']}] {sub}")
                    return result

        logger.warning(f"Subtopic not found: {subtopic}")
        return None

    def get_categories_list(self) -> list[dict]:
        """Get list of all categories with their IDs and names."""
        return [
            {"id": cat["id"], "name": cat["name"], "subtopics_count": len(cat.get("subtopics", []))}
            for cat in self.categories
        ]

    def get_stats(self) -> dict:
        """Get topic statistics."""
        all_subtopics = self.get_all_subtopics()
        available = self.get_available_subtopics() if self.content_history else all_subtopics

        by_category = {}
        for cat in self.categories:
            cat_subtopics = len(cat.get("subtopics", []))
            cat_available = len([s for s in available if s[0] == cat["id"]])
            by_category[cat["name"]] = {
                "total": cat_subtopics,
                "available": cat_available,
            }

        return {
            "total_categories": len(self.categories),
            "total_subtopics": len(all_subtopics),
            "available_subtopics": len(available),
            "by_category": by_category,
        }
