"""
Media manager for photos and music.

Handles:
- Scanning media directories
- Selecting photos by category
- Selecting music tracks
- Integration with content history for cooldown checks
"""

import logging
import random
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Supported file extensions
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".heif", ".heic"}
MUSIC_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav"}


@dataclass
class MediaFile:
    """Represents a media file with metadata."""
    path: Path
    category: Optional[str] = None  # For photos: folder name
    filename: str = ""

    def __post_init__(self):
        self.filename = self.path.name

    @property
    def relative_path(self) -> str:
        """Get path relative to media root for storage."""
        return str(self.path)


class MediaManager:
    """
    Manages photo and music pools.

    Photos are organized by category/subtopic (nested subdirectories).
    Music can be in root or subcategories (traditional, modern, etc.).
    """

    def __init__(
        self,
        photos_path: Path,
        music_path: Path,
        content_history=None,  # Optional ContentHistory for cooldown checks
    ):
        """
        Initialize media manager.

        Args:
            photos_path: Root directory containing photo subdirectories
            music_path: Root directory containing music files
            content_history: Optional ContentHistory instance for cooldown checks
        """
        self.photos_path = Path(photos_path)
        self.music_path = Path(music_path)
        self.content_history = content_history

        # Caches
        self._photos_cache: dict[str, list[MediaFile]] = {}  # category -> photos
        self._subtopic_photos_cache: dict[str, list[MediaFile]] = {}  # "category/subtopic" -> photos
        self._music_cache: list[MediaFile] = []
        self._category_mapping: dict[str, str] = {}  # normalized -> original

        self._scan_media()

    def _scan_media(self) -> None:
        """Scan media directories and populate caches."""
        self._scan_photos()
        self._scan_music()

    def _scan_photos(self) -> None:
        """Scan photos directory, organizing by category and subtopic (nested structure)."""
        self._photos_cache.clear()
        self._subtopic_photos_cache.clear()
        self._category_mapping.clear()

        if not self.photos_path.exists():
            logger.warning(f"Photos directory not found: {self.photos_path}")
            return

        # Scan all subdirectories as categories
        for category_dir in self.photos_path.iterdir():
            if not category_dir.is_dir():
                continue

            category_name = category_dir.name
            normalized_category = self._normalize_category(category_name)
            self._category_mapping[normalized_category] = category_name

            category_photos = []

            # Scan photos directly in category folder
            for item in category_dir.iterdir():
                if item.is_file() and item.suffix.lower() in PHOTO_EXTENSIONS:
                    category_photos.append(MediaFile(
                        path=item,
                        category=category_name,
                    ))

            # Scan subtopic subdirectories
            for subtopic_dir in category_dir.iterdir():
                if not subtopic_dir.is_dir():
                    continue

                subtopic_name = subtopic_dir.name
                subtopic_key = f"{normalized_category}/{self._normalize_category(subtopic_name)}"
                subtopic_photos = []

                for photo_path in subtopic_dir.iterdir():
                    if photo_path.suffix.lower() in PHOTO_EXTENSIONS:
                        photo = MediaFile(
                            path=photo_path,
                            category=category_name,
                        )
                        subtopic_photos.append(photo)
                        # Also add to category-level cache for fallback
                        category_photos.append(photo)

                if subtopic_photos:
                    self._subtopic_photos_cache[subtopic_key] = subtopic_photos
                    logger.debug(f"Found {len(subtopic_photos)} photos in subtopic '{category_name}/{subtopic_name}'")

            if category_photos:
                self._photos_cache[normalized_category] = category_photos
                logger.info(f"Found {len(category_photos)} photos in category '{category_name}'")

        total_photos = sum(len(p) for p in self._photos_cache.values())
        logger.info(f"Total photos scanned: {total_photos} in {len(self._photos_cache)} categories")

    def _scan_music(self) -> None:
        """Scan music directory (flat or with subcategories)."""
        self._music_cache.clear()

        if not self.music_path.exists():
            logger.warning(f"Music directory not found: {self.music_path}")
            return

        # Scan root and all subdirectories
        for item in self.music_path.rglob("*"):
            if item.is_file() and item.suffix.lower() in MUSIC_EXTENSIONS:
                # Category is the parent folder if nested, None if in root
                category = None
                if item.parent != self.music_path:
                    category = item.parent.name

                self._music_cache.append(MediaFile(
                    path=item,
                    category=category,
                ))

        logger.info(f"Found {len(self._music_cache)} music tracks")

    def _normalize_category(self, category: str) -> str:
        """
        Normalize category name for matching.

        Converts "Горная Аджария" -> "горная аджария"
        Also maps topic IDs like "mountain_adjara" to folder names.
        """
        return category.lower().strip()

    def get_categories(self) -> list[str]:
        """Get list of available photo categories."""
        return list(self._category_mapping.values())

    def get_photos_count(self, category: Optional[str] = None) -> int:
        """Get count of photos, optionally filtered by category."""
        if category:
            normalized = self._normalize_category(category)
            return len(self._photos_cache.get(normalized, []))
        return sum(len(p) for p in self._photos_cache.values())

    def get_music_count(self) -> int:
        """Get count of music tracks."""
        return len(self._music_cache)

    def find_photos_for_category(
        self,
        category_id: str,
        category_name: str,
    ) -> list[MediaFile]:
        """
        Find photos matching a topic category.

        Tries multiple matching strategies:
        1. Exact folder name match
        2. Category ID match (e.g., "mountain_adjara")
        3. Partial name match

        Args:
            category_id: Category ID from topics.json (e.g., "mountain_adjara")
            category_name: Human-readable category name (e.g., "Горная Аджария")

        Returns:
            List of matching MediaFile objects
        """
        # Try exact category name match
        normalized_name = self._normalize_category(category_name)
        if normalized_name in self._photos_cache:
            return self._photos_cache[normalized_name]

        # Try category ID match (convert underscores to spaces)
        normalized_id = category_id.replace("_", " ").lower()
        for norm_cat, photos in self._photos_cache.items():
            if normalized_id in norm_cat or norm_cat in normalized_id:
                return photos

        # Try partial match on category name
        for norm_cat, photos in self._photos_cache.items():
            # Check if any word from category_name is in folder name
            words = normalized_name.split()
            if any(word in norm_cat for word in words if len(word) > 3):
                return photos

        logger.warning(f"No photos found for category: {category_id} / {category_name}")
        return []

    def select_photo(
        self,
        category_id: str,
        category_name: str,
        subtopic: Optional[str] = None,
        check_cooldown: bool = True,
        exclude_paths: Optional[list[str]] = None,
    ) -> Optional[MediaFile]:
        """
        Select a random photo for the given category/subtopic.

        Search order (with fallback):
        1. Subtopic folder (if specified)
        2. Category folder
        3. Any available photo

        Args:
            category_id: Category ID from topics.json
            category_name: Human-readable category name
            subtopic: Optional subtopic name for more specific search
            check_cooldown: Whether to check content history for cooldown
            exclude_paths: List of photo paths to exclude (e.g., already used in current series)

        Returns:
            Selected MediaFile or None if no photos available
        """
        photos = []
        exclude_set = set(exclude_paths) if exclude_paths else set()

        # Try subtopic folder first if specified
        if subtopic:
            photos = self.find_photos_for_subtopic(category_name, subtopic)
            if photos:
                logger.debug(f"Found {len(photos)} photos in subtopic '{subtopic}'")

        # Fallback to category folder
        if not photos:
            photos = self.find_photos_for_category(category_id, category_name)
            if photos and subtopic:
                logger.debug(f"Subtopic '{subtopic}' empty, using category '{category_name}'")

        # Final fallback: any photo
        if not photos:
            all_photos = [p for photos_list in self._photos_cache.values() for p in photos_list]
            if all_photos:
                logger.warning(f"Using fallback photo selection for {category_name}")
                photos = all_photos
            else:
                return None

        # Filter out excluded photos (already used in current series)
        if exclude_set:
            filtered = [p for p in photos if str(p.path) not in exclude_set]
            if filtered:
                photos = filtered
                logger.debug(f"Excluded {len(exclude_set)} already-used photos, {len(photos)} remaining")
            else:
                logger.warning(f"All photos excluded, reusing from pool")

        # Filter by cooldown if content history available
        if check_cooldown and self.content_history:
            available_photos = [
                p for p in photos
                if self.content_history.is_photo_available(str(p.path))
            ]
            if available_photos:
                photos = available_photos
            else:
                logger.warning(f"All photos for {category_name} are on cooldown, ignoring cooldown")

        # Random selection
        selected = random.choice(photos)
        logger.info(f"Selected photo: {selected.filename} for {category_name}" +
                    (f"/{subtopic}" if subtopic else ""))

        return selected

    def find_photos_for_subtopic(
        self,
        category_name: str,
        subtopic: str,
    ) -> list[MediaFile]:
        """
        Find photos in a specific subtopic folder.

        Args:
            category_name: Category name (e.g., "Грузинская кухня")
            subtopic: Subtopic name (e.g., "Хачапури по-аджарски")

        Returns:
            List of MediaFile objects from subtopic folder
        """
        normalized_category = self._normalize_category(category_name)
        normalized_subtopic = self._normalize_category(subtopic)
        subtopic_key = f"{normalized_category}/{normalized_subtopic}"

        # Exact match
        if subtopic_key in self._subtopic_photos_cache:
            return self._subtopic_photos_cache[subtopic_key]

        # Try partial match on subtopic name
        for key, photos in self._subtopic_photos_cache.items():
            if key.startswith(f"{normalized_category}/"):
                key_subtopic = key.split("/", 1)[1]
                # Check if subtopic words match
                if normalized_subtopic in key_subtopic or key_subtopic in normalized_subtopic:
                    return photos

        return []

    def select_music(
        self,
        category: Optional[str] = None,
        check_cooldown: bool = True,
    ) -> Optional[MediaFile]:
        """
        Select a random music track.

        Args:
            category: Optional category filter (traditional, modern, etc.)
            check_cooldown: Whether to check content history for cooldown

        Returns:
            Selected MediaFile or None if no music available
        """
        tracks = self._music_cache

        if not tracks:
            logger.warning("No music tracks available")
            return None

        # Filter by category if specified
        if category:
            category_tracks = [t for t in tracks if t.category == category]
            if category_tracks:
                tracks = category_tracks

        # Filter by cooldown
        if check_cooldown and self.content_history:
            available_tracks = [
                t for t in tracks
                if self.content_history.is_music_available(str(t.path))
            ]
            if available_tracks:
                tracks = available_tracks
            else:
                logger.warning("All music tracks are on cooldown, ignoring cooldown")

        selected = random.choice(tracks)
        logger.info(f"Selected music: {selected.filename}")

        return selected

    def rescan(self) -> None:
        """Rescan media directories to pick up new files."""
        logger.info("Rescanning media directories...")
        self._scan_media()

    def get_stats(self) -> dict:
        """Get media statistics."""
        photo_stats = {
            cat: len(photos) for cat, photos in self._photos_cache.items()
        }

        music_by_category = {}
        for track in self._music_cache:
            cat = track.category or "root"
            music_by_category[cat] = music_by_category.get(cat, 0) + 1

        return {
            "photos": {
                "total": sum(photo_stats.values()),
                "by_category": photo_stats,
            },
            "music": {
                "total": len(self._music_cache),
                "by_category": music_by_category,
            },
        }
