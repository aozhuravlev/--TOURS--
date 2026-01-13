"""
Topic selector for content generation.

Selects random category and subtopic from topics.json,
respecting content history cooldowns.
"""

import json
import logging
import random
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


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
    ):
        """
        Initialize topic selector.

        Args:
            topics_path: Path to topics.json file
            content_history: Optional ContentHistory instance
        """
        self.topics_path = Path(topics_path)
        self.content_history = content_history
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

    def get_available_subtopics(self) -> list[tuple[str, str, str]]:
        """
        Get subtopics that are not on cooldown.

        Returns:
            List of available (category_id, category_name, subtopic) tuples
        """
        all_subtopics = self.get_all_subtopics()

        if not self.content_history:
            return all_subtopics

        available = []
        for cat_id, cat_name, subtopic in all_subtopics:
            if self.content_history.is_subtopic_available(subtopic):
                available.append((cat_id, cat_name, subtopic))

        logger.debug(f"Available subtopics: {len(available)}/{len(all_subtopics)}")
        return available

    def select_random(
        self,
        category_id: Optional[str] = None,
        check_cooldown: bool = True,
    ) -> Optional[SelectedTopic]:
        """
        Select a random topic.

        Args:
            category_id: Optional category filter
            check_cooldown: Whether to check content history

        Returns:
            SelectedTopic or None if no topics available
        """
        if check_cooldown:
            candidates = self.get_available_subtopics()
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
