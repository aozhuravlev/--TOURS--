"""
Image searcher for finding and downloading photos.

Supports:
- Wikimedia Commons (primary, best for specific topics)
- Pexels API (fallback for generic photos)
- Unsplash API (optional)

Downloads, processes, and crops images to Instagram formats.
"""

import logging
import requests
import hashlib
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

# Instagram format dimensions
STORY_SIZE = (1080, 1920)  # 9:16
POST_SIZE = (1080, 1350)   # 4:5


@dataclass
class ImageResult:
    """Search result from image API."""
    id: str
    url: str  # Download URL
    thumb_url: str  # Preview URL
    author: str
    source: str  # "wikimedia", "unsplash", or "pexels"
    description: Optional[str] = None
    license: Optional[str] = None  # License info (for Wikimedia)

    @property
    def attribution(self) -> str:
        """Get attribution string for the image."""
        if self.source == "wikimedia":
            return f"Photo by {self.author} (Wikimedia Commons, {self.license or 'CC'})"
        return f"Photo by {self.author} on {self.source.capitalize()}"


class ImageSearcher:
    """
    Search and download images from stock photo APIs.

    Uses Unsplash as primary source, Pexels as fallback.
    """

    def __init__(
        self,
        unsplash_key: Optional[str] = None,
        pexels_key: Optional[str] = None,
        download_dir: Optional[Path] = None,
    ):
        """
        Initialize image searcher.

        Args:
            unsplash_key: Unsplash API access key
            pexels_key: Pexels API key (optional fallback)
            download_dir: Directory for downloaded images
        """
        self.unsplash_key = unsplash_key
        self.pexels_key = pexels_key
        self.download_dir = Path(download_dir) if download_dir else Path("media/photos/downloaded")

        # Create download directory
        self.download_dir.mkdir(parents=True, exist_ok=True)

        # Session for HTTP requests
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ToursBatumi/1.0 (Instagram content automation)"
        })

        if not unsplash_key and not pexels_key:
            logger.warning("No image API keys configured - image search will fail")

    def search(
        self,
        query: str,
        count: int = 5,
        orientation: str = "portrait",
    ) -> list[ImageResult]:
        """
        Search for images matching query.

        Priority:
        1. Wikimedia Commons (best for specific topics like Georgian food)
        2. Pexels (fallback for generic photos)
        3. Unsplash (if configured)

        Args:
            query: Search query (keywords)
            count: Number of results to return
            orientation: Image orientation ("portrait", "landscape", "squarish")

        Returns:
            List of ImageResult objects
        """
        results = []

        # Priority 1: Wikimedia Commons (best for specific content)
        # Use short query for Wikimedia (3-4 words work best)
        wiki_query = ' '.join(query.split()[:4])
        try:
            results = self._search_wikimedia(wiki_query, count)
            if results:
                logger.info(f"Found {len(results)} images on Wikimedia for '{wiki_query}'")
                return results
            else:
                logger.debug(f"Wikimedia: no results for '{wiki_query}'")
        except Exception as e:
            logger.warning(f"Wikimedia search failed: {e}")

        # Priority 2: Pexels (good generic photos)
        if self.pexels_key:
            try:
                results = self._search_pexels(query, count, orientation)
                if results:
                    logger.info(f"Found {len(results)} images on Pexels for '{query}'")
                    return results
            except Exception as e:
                logger.warning(f"Pexels search failed: {e}")

        # Priority 3: Unsplash (optional)
        if self.unsplash_key:
            try:
                results = self._search_unsplash(query, count, orientation)
                if results:
                    logger.info(f"Found {len(results)} images on Unsplash for '{query}'")
                    return results
            except Exception as e:
                logger.warning(f"Unsplash search failed: {e}")

        logger.warning(f"No images found for '{query}'")
        return []

    def _search_unsplash(
        self,
        query: str,
        count: int,
        orientation: str,
    ) -> list[ImageResult]:
        """Search Unsplash API."""
        url = "https://api.unsplash.com/search/photos"

        params = {
            "query": query,
            "per_page": count,
            "orientation": orientation,
        }

        headers = {
            "Authorization": f"Client-ID {self.unsplash_key}"
        }

        response = self.session.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        results = []

        for photo in data.get("results", []):
            results.append(ImageResult(
                id=photo["id"],
                url=photo["urls"]["regular"],  # 1080px wide
                thumb_url=photo["urls"]["thumb"],
                author=photo["user"]["name"],
                source="unsplash",
                description=photo.get("alt_description") or photo.get("description"),
            ))

        return results

    def _search_pexels(
        self,
        query: str,
        count: int,
        orientation: str,
    ) -> list[ImageResult]:
        """Search Pexels API."""
        url = "https://api.pexels.com/v1/search"

        params = {
            "query": query,
            "per_page": count,
            "orientation": orientation,
        }

        headers = {
            "Authorization": self.pexels_key
        }

        response = self.session.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        results = []

        for photo in data.get("photos", []):
            results.append(ImageResult(
                id=str(photo["id"]),
                url=photo["src"]["large2x"],  # High resolution
                thumb_url=photo["src"]["tiny"],
                author=photo["photographer"],
                source="pexels",
                description=photo.get("alt"),
            ))

        return results

    def _search_wikimedia(
        self,
        query: str,
        count: int,
    ) -> list[ImageResult]:
        """
        Search Wikimedia Commons for images.

        Wikimedia Commons has excellent coverage of:
        - Georgian cuisine (khachapuri, khinkali, etc.)
        - Batumi landmarks and architecture
        - Georgian culture and traditions

        All images are freely licensed (CC-BY, CC-BY-SA, CC0, etc.)
        """
        # Step 1: Search for files
        search_url = "https://commons.wikimedia.org/w/api.php"

        search_params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": f"{query} filetype:bitmap",  # Only images
            "srnamespace": "6",  # File namespace
            "srlimit": count * 2,  # Get more to filter
        }

        try:
            response = self.session.get(search_url, params=search_params, timeout=30)
            response.raise_for_status()
            search_data = response.json()
        except Exception as e:
            logger.warning(f"Wikimedia search failed: {e}")
            return []

        search_results = search_data.get("query", {}).get("search", [])

        if not search_results:
            logger.debug(f"Wikimedia: no search results for '{query}'")
            return []

        logger.debug(f"Wikimedia: found {len(search_results)} raw results for '{query}'")

        # Step 2: Get image info (URLs, authors, licenses)
        titles = [r["title"] for r in search_results]

        info_params = {
            "action": "query",
            "format": "json",
            "titles": "|".join(titles),
            "prop": "imageinfo",
            "iiprop": "url|user|extmetadata|size",
            "iiurlwidth": 1200,  # Get scaled URL for reasonable size
        }

        try:
            response = self.session.get(search_url, params=info_params, timeout=30)
            response.raise_for_status()
            info_data = response.json()
        except Exception as e:
            logger.warning(f"Wikimedia info query failed: {e}")
            return []

        pages = info_data.get("query", {}).get("pages", {})

        results = []
        for page_id, page in pages.items():
            if page_id == "-1":  # Page not found
                continue

            imageinfo = page.get("imageinfo", [{}])[0]

            # Skip small images (less than 800px)
            width = imageinfo.get("width", 0)
            height = imageinfo.get("height", 0)
            if width < 800 or height < 800:
                logger.debug(f"Wikimedia: skipping small image {width}x{height}")
                continue

            # Get URLs
            url = imageinfo.get("thumburl") or imageinfo.get("url")
            if not url:
                continue

            # Get metadata
            extmeta = imageinfo.get("extmetadata", {})
            author = extmeta.get("Artist", {}).get("value", imageinfo.get("user", "Unknown"))
            # Clean HTML from author
            if "<" in author:
                import re
                author = re.sub(r"<[^>]+>", "", author).strip()

            license_info = extmeta.get("LicenseShortName", {}).get("value", "CC")
            description = extmeta.get("ImageDescription", {}).get("value", "")
            if "<" in description:
                import re
                description = re.sub(r"<[^>]+>", "", description)[:200]

            results.append(ImageResult(
                id=page.get("title", ""),
                url=url,
                thumb_url=imageinfo.get("thumburl", url),
                author=author[:50],  # Limit author length
                source="wikimedia",
                description=description,
                license=license_info,
            ))

            if len(results) >= count:
                break

        return results

    def download(
        self,
        image: ImageResult,
        filename: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Path:
        """
        Download image to local storage.

        Args:
            image: ImageResult to download
            filename: Optional custom filename
            category: Optional category folder to save into

        Returns:
            Path to downloaded file
        """
        if filename is None:
            # Generate unique filename from URL hash
            url_hash = hashlib.md5(image.url.encode()).hexdigest()[:8]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{image.source}_{timestamp}_{url_hash}.jpg"

        # Determine output directory
        if category:
            # Save to category folder (e.g., media/photos/Грузинская кухня/)
            output_dir = self.download_dir.parent / category
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            output_dir = self.download_dir

        output_path = output_dir / filename

        logger.info(f"Downloading image: {image.url[:50]}...")

        response = self.session.get(image.url, timeout=60)
        response.raise_for_status()

        output_path.write_bytes(response.content)

        file_size = output_path.stat().st_size / 1024  # KB
        logger.info(f"Downloaded: {output_path.name} to {output_dir.name}/ ({file_size:.1f} KB)")

        return output_path

    def search_and_download(
        self,
        query: str,
        orientation: str = "portrait",
        category: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Search for image and download the best result.

        Args:
            query: Search query
            orientation: Image orientation
            category: Category folder to save into

        Returns:
            Path to downloaded image, or None if not found
        """
        results = self.search(query, count=1, orientation=orientation)

        if not results:
            return None

        return self.download(results[0], category=category)

    def _extract_keywords(self, text: str, max_words: int = 5) -> str:
        """
        Extract meaningful keywords from text for image search.

        Removes common Russian words and keeps nouns/adjectives.
        """
        import re

        # Common Russian stop words to remove
        stop_words = {
            'и', 'в', 'на', 'с', 'к', 'по', 'за', 'из', 'от', 'до', 'для', 'о', 'об',
            'это', 'как', 'что', 'так', 'но', 'а', 'или', 'не', 'да', 'же', 'ли',
            'вы', 'мы', 'он', 'она', 'они', 'вам', 'вас', 'нам', 'нас', 'его', 'её',
            'быть', 'есть', 'был', 'была', 'будет', 'можно', 'нужно', 'очень',
            'этот', 'эта', 'эти', 'того', 'этого', 'такой', 'такая', 'такие',
            'который', 'которая', 'которые', 'свой', 'своя', 'свои',
            'все', 'всё', 'весь', 'вся', 'каждый', 'любой', 'другой',
            'здесь', 'тут', 'там', 'где', 'когда', 'если', 'чтобы', 'потому',
            'только', 'уже', 'ещё', 'даже', 'просто', 'именно', 'ведь',
        }

        # Clean text: remove punctuation, lowercase
        text = re.sub(r'[^\w\s]', ' ', text.lower())
        words = text.split()

        # Filter out stop words and short words
        keywords = [w for w in words if w not in stop_words and len(w) > 2]

        # Return first N words
        return ' '.join(keywords[:max_words])

    def search_by_description(
        self,
        description: str,
        topic: str,
        subtopic: str,
        english_keywords: str = "",
        location: str = "Batumi Georgia",
        max_attempts: int = 5,
    ) -> Optional[Path]:
        """
        Search for image based on English keywords.

        Uses Wikimedia Commons first, then Pexels as fallback.
        Always adds "Georgia Batumi" to queries for relevance.

        Args:
            description: Generated text description (Russian) - not used directly
            topic: Main topic - used as category folder
            subtopic: Specific subtopic - not used directly
            english_keywords: English keywords for search (required for good results)
            location: Location context
            max_attempts: Maximum query attempts

        Returns:
            Path to downloaded image, or None if all attempts fail
        """
        # Build query variations (English only)
        queries = []

        if english_keywords:
            # Priority 1: Keywords alone (best for Wikimedia - short queries work better)
            queries.append(english_keywords)
            # Priority 2: Keywords + Georgia Batumi (for Pexels fallback)
            queries.append(f"{english_keywords} Georgia Batumi")
            # Priority 3: Keywords + Georgia (broader)
            queries.append(f"{english_keywords} Georgia")

        # Priority 4: Location-based fallbacks
        queries.extend([
            location,
            "Batumi Georgia",
        ])

        # Remove empty/duplicate queries and limit attempts
        seen = set()
        unique_queries = []
        for q in queries:
            q_clean = q.strip()
            if q_clean and q_clean.lower() not in seen:
                seen.add(q_clean.lower())
                unique_queries.append(q_clean)

        queries = unique_queries[:max_attempts]

        for i, query in enumerate(queries):
            logger.info(f"Searching for image (attempt {i+1}/{len(queries)}): '{query}'")

            result = self.search_and_download(
                query,
                orientation="portrait",
                category=topic,
            )

            if result:
                logger.info(f"Found image for '{query}' -> saved to '{topic}/'")
                return result

            logger.debug(f"No results for '{query}', trying next...")

        logger.warning(f"No images found for description")
        return None

    def search_for_topic(
        self,
        topic: str,
        subtopic: str,
        location: str = "Batumi Georgia",
        max_attempts: int = 3,
    ) -> Optional[Path]:
        """
        Smart search for topic-related image (legacy method).

        Prefer search_by_description() for better results.
        """
        queries = [
            f"{subtopic} {location}",
            f"{subtopic} Georgia",
            subtopic,
            f"{topic} {location}",
            f"{topic}",
            location,
        ]

        queries = queries[:max_attempts]

        for i, query in enumerate(queries):
            logger.info(f"Searching for image (attempt {i+1}/{len(queries)}): '{query}'")

            result = self.search_and_download(
                query,
                orientation="portrait",
                category=topic,
            )

            if result:
                logger.info(f"Found image for '{query}' -> saved to '{topic}/'")
                return result

            logger.debug(f"No results for '{query}', trying next...")

        logger.warning(f"No images found for topic '{topic}' / '{subtopic}'")
        return None

    def cleanup_old_downloads(self, keep_days: int = 7) -> int:
        """
        Remove downloaded images older than specified days.

        Returns:
            Number of files deleted
        """
        import time

        deleted = 0
        cutoff = time.time() - (keep_days * 24 * 60 * 60)

        for file in self.download_dir.iterdir():
            if file.is_file() and file.stat().st_mtime < cutoff:
                file.unlink()
                deleted += 1
                logger.debug(f"Deleted old image: {file.name}")

        if deleted:
            logger.info(f"Cleaned up {deleted} old downloaded images")

        return deleted

    def close(self):
        """Close HTTP session."""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
