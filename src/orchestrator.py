"""
Content Orchestrator - main pipeline coordinator.

Coordinates the entire content generation workflow:
1. Select topic (with anti-repeat)
2. Fetch relevant facts (Perplexity)
3. Generate text (DeepSeek)
4. Select media (photo + music)
5. Compose video (FFmpeg)
6. Record to history
7. Send to moderation (Telegram)
"""

import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

from .modules.topic_selector import TopicSelector, SelectedTopic
from .modules.news_fetcher import NewsFetcher, NewsResult
from .modules.text_generator import TextGenerator, GeneratedText, GeneratedStorySeries as TextStorySeries, StoryItem
from .modules.media_manager import MediaManager, MediaFile
from .modules.video_composer import VideoComposer, VideoConfig
from .modules.content_history import ContentHistory, Publication
from .modules.image_searcher import ImageSearcher

logger = logging.getLogger(__name__)


@dataclass
class GeneratedContent:
    """Complete generated content package."""
    # Topic
    topic: SelectedTopic

    # Text
    text: GeneratedText
    facts: str

    # Media
    photo: MediaFile
    music: MediaFile
    video_path: Optional[Path] = None

    # Metadata
    content_type: str = "story"  # "story" or "post"
    created_at: datetime = field(default_factory=datetime.now)
    publication: Optional[Publication] = None

    @property
    def caption(self) -> str:
        """Get final text for Instagram caption."""
        return self.text.humanized_text


@dataclass
class StorySeriesItem:
    """Single story in a generated series."""
    order: int
    angle: str
    text: str
    keywords: str
    photo: MediaFile
    video_path: Path


@dataclass
class PreparedStory:
    """Story prepared for moderation (without video)."""
    order: int
    angle: str
    text: str
    keywords: str
    photo: MediaFile
    # No video_path - video not rendered yet


@dataclass
class PreparedStorySeriesResult:
    """Series prepared for moderation (before video rendering)."""
    topic: SelectedTopic
    facts: str
    stories: list[PreparedStory]
    music: MediaFile
    ken_burns: bool = True
    story_duration: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.now)
    success: bool = True
    error: Optional[str] = None

    @property
    def story_count(self) -> int:
        """Get number of stories."""
        return len(self.stories)


@dataclass
class GeneratedStorySeriesResult:
    """Complete generated story series package."""
    # Topic
    topic: SelectedTopic
    facts: str

    # Stories
    stories: list[StorySeriesItem]
    music: MediaFile

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    publication: Optional[Publication] = None
    success: bool = True
    error: Optional[str] = None

    @property
    def video_paths(self) -> list[Path]:
        """Get all video paths in order."""
        return [s.video_path for s in self.stories]

    @property
    def story_count(self) -> int:
        """Get number of stories."""
        return len(self.stories)


class Orchestrator:
    """
    Main content generation orchestrator.

    Coordinates all modules to produce ready-to-publish content.
    """

    def __init__(
        self,
        # API keys
        perplexity_api_key: str,
        deepseek_api_key: str,
        unsplash_api_key: Optional[str] = None,
        pexels_api_key: Optional[str] = None,
        # Paths
        topics_path: Path = None,
        prompts_dir: Path = None,
        photos_path: Path = None,
        music_path: Path = None,
        output_dir: Path = None,
        history_path: Path = None,
        fonts_dir: Optional[Path] = None,
        # Settings
        video_config: Optional[VideoConfig] = None,
        subtopic_cooldown_days: int = 7,
        photo_cooldown_days: int = 30,
        music_cooldown_days: int = 14,
        use_image_search: bool = True,
        use_text_overlay: bool = True,
    ):
        """
        Initialize orchestrator with all dependencies.

        Args:
            perplexity_api_key: API key for Perplexity
            deepseek_api_key: API key for DeepSeek
            unsplash_api_key: API key for Unsplash (for image search)
            pexels_api_key: API key for Pexels (fallback for image search)
            topics_path: Path to topics.json
            prompts_dir: Directory with prompt .txt files
            photos_path: Directory with photos
            music_path: Directory with music
            output_dir: Directory for generated videos
            history_path: Path to content_history.json
            fonts_dir: Directory with font files for text overlays
            video_config: Optional video settings
            subtopic_cooldown_days: Days before subtopic can repeat
            photo_cooldown_days: Days before photo can repeat
            music_cooldown_days: Days before music can repeat
            use_image_search: Whether to search for images online (vs local pool)
            use_text_overlay: Whether to add text overlay on stories
        """
        logger.info("Initializing Orchestrator...")

        # Feature flags
        self.use_image_search = use_image_search and bool(unsplash_api_key or pexels_api_key)
        self.use_text_overlay = use_text_overlay

        # Initialize content history first (needed by other modules)
        self.history = ContentHistory(
            history_path=history_path,
            subtopic_cooldown_days=subtopic_cooldown_days,
            photo_cooldown_days=photo_cooldown_days,
            music_cooldown_days=music_cooldown_days,
        )

        # Initialize modules
        self.topic_selector = TopicSelector(
            topics_path=topics_path,
            content_history=self.history,
            photos_path=photos_path,  # Check photo availability when selecting topics
        )

        self.news_fetcher = NewsFetcher(
            api_key=perplexity_api_key,
        )

        self.text_generator = TextGenerator(
            api_key=deepseek_api_key,
            prompts_dir=prompts_dir,
        )

        self.media_manager = MediaManager(
            photos_path=photos_path,
            music_path=music_path,
            content_history=self.history,
        )

        self.video_composer = VideoComposer(
            output_dir=output_dir,
            config=video_config,
            fonts_dir=fonts_dir,
        )

        # Initialize image searcher if API keys provided
        self.image_searcher: Optional[ImageSearcher] = None
        if self.use_image_search:
            download_dir = photos_path / "downloaded" if photos_path else None
            self.image_searcher = ImageSearcher(
                unsplash_key=unsplash_api_key,
                pexels_key=pexels_api_key,
                download_dir=download_dir,
            )
            logger.info("Image search enabled (Unsplash/Pexels)")
        else:
            logger.info("Image search disabled, using local photo pool")

        if self.use_text_overlay:
            logger.info("Text overlay enabled for stories")
        else:
            logger.info("Text overlay disabled")

        logger.info("Orchestrator initialized successfully")

    def generate_story(
        self,
        category_id: Optional[str] = None,
        ken_burns: bool = True,
    ) -> Optional[GeneratedContent]:
        """
        Generate complete Instagram Story content.

        Args:
            category_id: Optional category filter
            ken_burns: Use Ken Burns effect in video

        Returns:
            GeneratedContent or None on failure
        """
        return self._generate_content(
            content_type="story",
            category_id=category_id,
            ken_burns=ken_burns,
        )

    def generate_post(
        self,
        category_id: Optional[str] = None,
    ) -> Optional[GeneratedContent]:
        """
        Generate complete Instagram Post content.

        Args:
            category_id: Optional category filter

        Returns:
            GeneratedContent or None on failure
        """
        return self._generate_content(
            content_type="post",
            category_id=category_id,
            ken_burns=False,
        )

    def generate_story_series(
        self,
        category_id: Optional[str] = None,
        subtopic: Optional[str] = None,
        ken_burns: bool = True,
        min_count: int = 3,
        max_count: int = 7,
        story_duration: Optional[float] = None,
    ) -> Optional[GeneratedStorySeriesResult]:
        """
        Generate a series of connected Instagram Stories.

        Args:
            category_id: Optional category filter
            subtopic: Optional specific subtopic name (overrides category_id)
            ken_burns: Use Ken Burns effect in videos
            min_count: Minimum number of stories (default 3)
            max_count: Maximum number of stories (default 7)
            story_duration: Duration per story (None = random 5-8s per story)

        Returns:
            GeneratedStorySeriesResult or None on failure
        """
        logger.info("=== Starting STORY SERIES generation ===")

        # Step 1: Select topic
        logger.info("Step 1: Selecting topic...")
        if subtopic:
            topic = self.topic_selector.select_specific(subtopic)
        else:
            topic = self.topic_selector.select_random(category_id=category_id)
        if not topic:
            logger.error("Failed to select topic")
            return None
        logger.info(f"Selected: [{topic.category_name}] {topic.subtopic}")

        # Step 2: Fetch facts from Perplexity
        logger.info("Step 2: Fetching facts...")
        news_result = self.news_fetcher.search(
            topic=topic.category_name,
            subtopic=topic.subtopic,
        )
        facts = news_result.content if news_result.success else ""
        if facts:
            logger.info(f"Got {len(facts)} chars of facts")
        else:
            logger.warning("No facts fetched, continuing without")

        # Step 3: Generate story series text
        logger.info("Step 3: Generating story series text...")
        text_series = self.text_generator.generate_story_series(
            topic=topic.category_name,
            subtopic=topic.subtopic,
            facts=facts,
            min_count=min_count,
            max_count=max_count,
        )

        if not text_series.success:
            logger.error(f"Story series generation failed: {text_series.error}")
            return None
        logger.info(f"Generated {len(text_series.stories)} stories")

        # Step 4: Select music (one track for all stories)
        logger.info("Step 4: Selecting music...")
        music = self.media_manager.select_music()
        if not music:
            logger.error("Failed to select music")
            return None
        logger.info(f"Selected music: {music.filename}")

        # Step 5: For each story, find photo and prepare data
        logger.info("Step 5: Finding photos for each story...")
        story_data = []
        used_photo_paths = []  # Track photos used in this series to avoid duplicates

        for i, story_item in enumerate(text_series.stories):
            logger.info(f"  Story {i + 1}/{len(text_series.stories)}: {story_item.angle}")

            # Try to find photo using keywords
            photo = None
            photo_source = "local"

            if self.use_image_search and self.image_searcher:
                # Use provided keywords or extract from text
                keywords = story_item.keywords
                if not keywords:
                    keywords = self.text_generator.extract_english_keywords(
                        russian_text=story_item.text,
                        max_keywords=4,
                    )

                if keywords:
                    logger.debug(f"    Keywords: {keywords}")
                    photo_path = self.image_searcher.search_by_description(
                        description=story_item.text,
                        topic=topic.category_name,
                        subtopic=topic.subtopic,
                        english_keywords=keywords,
                        location="Batumi Georgia",
                        max_attempts=3,
                    )
                    if photo_path and str(photo_path) not in used_photo_paths:
                        photo = MediaFile(
                            path=photo_path,
                            filename=photo_path.name,
                            category=topic.category_name,
                        )
                        photo_source = "online"

            # Fallback to local pool
            if not photo:
                if self.use_image_search:
                    logger.warning(f"    Online search failed for story {i + 1}, using local")
                photo = self.media_manager.select_photo(
                    category_id=topic.category_id,
                    category_name=topic.category_name,
                    subtopic=topic.subtopic,
                    exclude_paths=used_photo_paths,
                )

            if not photo:
                logger.error(f"Failed to find photo for story {i + 1}")
                return None

            # Track this photo to avoid reuse in same series
            used_photo_paths.append(str(photo.path))

            logger.info(f"    Photo ({photo_source}): {photo.filename}")

            story_data.append({
                "order": story_item.order,
                "angle": story_item.angle,
                "text": story_item.text,
                "keywords": story_item.keywords,
                "photo": photo,
            })

        # Step 6: Compose all videos with sequential music
        logger.info("Step 6: Composing videos...")

        video_stories_input = [
            {"photo_path": s["photo"].path, "text": s["text"]}
            for s in story_data
        ]

        try:
            video_paths = self.video_composer.compose_story_series(
                stories=video_stories_input,
                music_path=music.path,
                ken_burns=ken_burns,
                story_duration=story_duration,
            )
        except Exception as e:
            logger.error(f"Video composition failed: {e}")
            return None

        logger.info(f"Created {len(video_paths)} videos")

        # Step 7: Build result
        logger.info("Step 7: Building result...")
        series_items = []
        for i, sd in enumerate(story_data):
            series_items.append(StorySeriesItem(
                order=sd["order"],
                angle=sd["angle"],
                text=sd["text"],
                keywords=sd["keywords"],
                photo=sd["photo"],
                video_path=video_paths[i],
            ))

        # Step 8: Record to history (tracking ALL photos)
        logger.info("Step 8: Recording to history...")
        publication = self.history.record_story_series(
            category_id=topic.category_id,
            subtopic=topic.subtopic,
            photo_paths=[str(sd["photo"].path) for sd in story_data],
            music_path=str(music.path),
            texts=[sd["text"] for sd in story_data],
            status="pending",
        )

        result = GeneratedStorySeriesResult(
            topic=topic,
            facts=facts,
            stories=series_items,
            music=music,
            publication=publication,
            success=True,
        )

        logger.info(f"=== STORY SERIES generation complete ({len(series_items)} stories) ===")
        return result

    def prepare_story_series(
        self,
        category_id: Optional[str] = None,
        subtopic: Optional[str] = None,
        ken_burns: bool = True,
        min_count: int = 3,
        max_count: int = 7,
        story_duration: Optional[float] = None,
    ) -> Optional[PreparedStorySeriesResult]:
        """
        Prepare a series of stories for moderation (without rendering videos).

        Args:
            category_id: Optional category filter
            subtopic: Optional specific subtopic name (overrides category_id)
            ken_burns: Use Ken Burns effect when rendering (stored for later)
            min_count: Minimum number of stories (default 3)
            max_count: Maximum number of stories (default 7)
            story_duration: Duration per story (None = random 5-8s per story)

        Returns:
            PreparedStorySeriesResult or None on failure
        """
        logger.info("=== Starting STORY SERIES preparation (no render) ===")

        # Step 1: Select topic
        logger.info("Step 1: Selecting topic...")
        if subtopic:
            topic = self.topic_selector.select_specific(subtopic)
        else:
            topic = self.topic_selector.select_random(category_id=category_id)
        if not topic:
            logger.error("Failed to select topic")
            return None
        logger.info(f"Selected: [{topic.category_name}] {topic.subtopic}")

        # Step 2: Fetch facts from Perplexity
        logger.info("Step 2: Fetching facts...")
        news_result = self.news_fetcher.search(
            topic=topic.category_name,
            subtopic=topic.subtopic,
        )
        facts = news_result.content if news_result.success else ""
        if facts:
            logger.info(f"Got {len(facts)} chars of facts")
        else:
            logger.warning("No facts fetched, continuing without")

        # Step 3: Generate story series text
        logger.info("Step 3: Generating story series text...")
        text_series = self.text_generator.generate_story_series(
            topic=topic.category_name,
            subtopic=topic.subtopic,
            facts=facts,
            min_count=min_count,
            max_count=max_count,
        )

        if not text_series.success:
            logger.error(f"Story series generation failed: {text_series.error}")
            return None
        logger.info(f"Generated {len(text_series.stories)} stories")

        # Step 4: Select music (one track for all stories)
        logger.info("Step 4: Selecting music...")
        music = self.media_manager.select_music()
        if not music:
            logger.error("Failed to select music")
            return None
        logger.info(f"Selected music: {music.filename}")

        # Step 5: For each story, find photo
        logger.info("Step 5: Finding photos for each story...")
        prepared_stories = []
        used_photo_paths = []  # Track photos used in this series to avoid duplicates

        for i, story_item in enumerate(text_series.stories):
            logger.info(f"  Story {i + 1}/{len(text_series.stories)}: {story_item.angle}")

            # Try to find photo using keywords
            photo = None
            photo_source = "local"

            if self.use_image_search and self.image_searcher:
                # Use provided keywords or extract from text
                keywords = story_item.keywords
                if not keywords:
                    keywords = self.text_generator.extract_english_keywords(
                        russian_text=story_item.text,
                        max_keywords=4,
                    )

                if keywords:
                    logger.debug(f"    Keywords: {keywords}")
                    photo_path = self.image_searcher.search_by_description(
                        description=story_item.text,
                        topic=topic.category_name,
                        subtopic=topic.subtopic,
                        english_keywords=keywords,
                        location="Batumi Georgia",
                        max_attempts=3,
                    )
                    if photo_path and str(photo_path) not in used_photo_paths:
                        photo = MediaFile(
                            path=photo_path,
                            filename=photo_path.name,
                            category=topic.category_name,
                        )
                        photo_source = "online"

            # Fallback to local pool
            if not photo:
                if self.use_image_search:
                    logger.warning(f"    Online search failed for story {i + 1}, using local")
                photo = self.media_manager.select_photo(
                    category_id=topic.category_id,
                    category_name=topic.category_name,
                    subtopic=topic.subtopic,
                    exclude_paths=used_photo_paths,
                )

            if not photo:
                logger.error(f"Failed to find photo for story {i + 1}")
                return None

            # Track this photo to avoid reuse in same series
            used_photo_paths.append(str(photo.path))

            logger.info(f"    Photo ({photo_source}): {photo.filename}")

            prepared_stories.append(PreparedStory(
                order=story_item.order,
                angle=story_item.angle,
                text=story_item.text,
                keywords=story_item.keywords,
                photo=photo,
            ))

        # NO video rendering, NO history recording - that comes after moderation

        result = PreparedStorySeriesResult(
            topic=topic,
            facts=facts,
            stories=prepared_stories,
            music=music,
            ken_burns=ken_burns,
            story_duration=story_duration,
            success=True,
        )

        logger.info(f"=== STORY SERIES preparation complete ({len(prepared_stories)} stories) ===")
        return result

    def render_approved_stories(
        self,
        prepared: PreparedStorySeriesResult,
        approved_stories: list[dict],
    ) -> Optional[GeneratedStorySeriesResult]:
        """
        Render videos only for approved stories after moderation.

        Args:
            prepared: PreparedStorySeriesResult from prepare_story_series()
            approved_stories: List of dicts with approved story data:
                [{"order": 1, "text": "...", "photo_path": "..."}]

        Returns:
            GeneratedStorySeriesResult or None on failure
        """
        if not approved_stories:
            logger.warning("No approved stories to render")
            return None

        logger.info(f"=== Rendering {len(approved_stories)} approved stories ===")

        # Sort by order
        approved_stories = sorted(approved_stories, key=lambda x: x["order"])

        # Build input for video composer
        video_stories_input = [
            {"photo_path": Path(s["photo_path"]), "text": s["text"]}
            for s in approved_stories
        ]

        # Render videos
        logger.info("Composing videos...")
        try:
            video_paths = self.video_composer.compose_story_series(
                stories=video_stories_input,
                music_path=prepared.music.path,
                ken_burns=prepared.ken_burns,
                story_duration=prepared.story_duration,
            )
        except Exception as e:
            logger.error(f"Video composition failed: {e}")
            return None

        logger.info(f"Created {len(video_paths)} videos")

        # Build result items
        series_items = []
        for i, story_dict in enumerate(approved_stories):
            # Find matching prepared story for metadata
            prepared_story = None
            for ps in prepared.stories:
                if ps.order == story_dict["order"]:
                    prepared_story = ps
                    break

            series_items.append(StorySeriesItem(
                order=story_dict["order"],
                angle=prepared_story.angle if prepared_story else "",
                text=story_dict["text"],
                keywords=prepared_story.keywords if prepared_story else "",
                photo=MediaFile(
                    path=Path(story_dict["photo_path"]),
                    filename=Path(story_dict["photo_path"]).name,
                    category=prepared.topic.category_name,
                ),
                video_path=video_paths[i],
            ))

        # Record to history
        logger.info("Recording to history...")
        publication = self.history.record_story_series(
            category_id=prepared.topic.category_id,
            subtopic=prepared.topic.subtopic,
            photo_paths=[s["photo_path"] for s in approved_stories],
            music_path=str(prepared.music.path),
            texts=[s["text"] for s in approved_stories],
            status="pending",
        )

        result = GeneratedStorySeriesResult(
            topic=prepared.topic,
            facts=prepared.facts,
            stories=series_items,
            music=prepared.music,
            publication=publication,
            success=True,
        )

        logger.info(f"=== Rendered {len(series_items)} stories ===")
        return result

    def _generate_content(
        self,
        content_type: str,
        category_id: Optional[str] = None,
        ken_burns: bool = False,
    ) -> Optional[GeneratedContent]:
        """
        Internal content generation pipeline.

        Steps:
        1. Select topic
        2. Fetch facts
        3. Generate text
        4. Select media
        5. Compose video (for stories)
        6. Record to history
        """
        logger.info(f"=== Starting {content_type} generation ===")

        # Step 1: Select topic
        logger.info("Step 1: Selecting topic...")
        topic = self.topic_selector.select_random(category_id=category_id)
        if not topic:
            logger.error("Failed to select topic")
            return None
        logger.info(f"Selected: [{topic.category_name}] {topic.subtopic}")

        # Step 2: Fetch facts from Perplexity
        logger.info("Step 2: Fetching facts...")
        news_result = self.news_fetcher.search(
            topic=topic.category_name,
            subtopic=topic.subtopic,
        )
        facts = news_result.content if news_result.success else ""
        if facts:
            logger.info(f"Got {len(facts)} chars of facts")
        else:
            logger.warning("No facts fetched, continuing without")

        # Step 3: Generate text
        logger.info("Step 3: Generating text...")
        if content_type == "story":
            text = self.text_generator.generate_story(
                topic=topic.category_name,
                subtopic=topic.subtopic,
                facts=facts,
            )
        else:
            text = self.text_generator.generate_post(
                topic=topic.category_name,
                subtopic=topic.subtopic,
                facts=facts,
            )

        if not text.success:
            logger.error(f"Text generation failed: {text.error}")
            return None
        logger.info(f"Generated text: {len(text.humanized_text)} chars")

        # Step 4: Select media
        logger.info("Step 4: Selecting media...")

        # Try image search first, fallback to local pool
        photo = None
        photo_source = "local"

        if self.use_image_search and self.image_searcher:
            logger.info("Searching for image online...")

            # Extract English keywords for better search results
            english_keywords = self.text_generator.extract_english_keywords(
                russian_text=text.humanized_text,
                max_keywords=4,
            )
            if english_keywords:
                logger.info(f"English keywords: {english_keywords}")

            photo_path = self.image_searcher.search_by_description(
                description=text.humanized_text,
                topic=topic.category_name,
                subtopic=topic.subtopic,
                english_keywords=english_keywords,
                location="Batumi Georgia",
                max_attempts=4,
            )
            if photo_path:
                photo = MediaFile(
                    path=photo_path,
                    filename=photo_path.name,
                    category=topic.category_name,
                )
                photo_source = "online"
                logger.info(f"Found image online: {photo.filename}")

        # Fallback to local photo pool if search failed or disabled
        if not photo:
            if self.use_image_search:
                logger.warning("Online search failed, falling back to local pool")
            photo = self.media_manager.select_photo(
                category_id=topic.category_id,
                category_name=topic.category_name,
                subtopic=topic.subtopic,
            )

        if not photo:
            logger.error("Failed to select photo (both online and local)")
            return None

        music = self.media_manager.select_music()
        if not music:
            logger.error("Failed to select music")
            return None

        logger.info(f"Selected photo ({photo_source}): {photo.filename}")
        logger.info(f"Selected music: {music.filename}")

        # Step 5: Compose video (for stories)
        video_path = None
        if content_type == "story":
            logger.info("Step 5: Composing video...")
            try:
                # Use text overlay if enabled
                if self.use_text_overlay:
                    video_path = self.video_composer.compose_story_with_overlay(
                        photo_path=photo.path,
                        music_path=music.path,
                        text=text.humanized_text,
                        ken_burns=ken_burns,
                    )
                else:
                    video_path = self.video_composer.compose_story(
                        photo_path=photo.path,
                        music_path=music.path,
                        ken_burns=ken_burns,
                    )
                logger.info(f"Video created: {video_path}")
            except Exception as e:
                logger.error(f"Video composition failed: {e}")
                return None

        # Step 6: Record to history
        logger.info("Step 6: Recording to history...")
        publication = self.history.record_publication(
            content_type=content_type,
            category_id=topic.category_id,
            subtopic=topic.subtopic,
            photo_path=str(photo.path),
            music_path=str(music.path),
            text=text.humanized_text,
            status="pending",
        )

        # Build result
        content = GeneratedContent(
            topic=topic,
            text=text,
            facts=facts,
            photo=photo,
            music=music,
            video_path=video_path,
            content_type=content_type,
            publication=publication,
        )

        logger.info(f"=== {content_type.upper()} generation complete ===")
        return content

    def get_pending_content(self) -> list[Publication]:
        """Get all content pending moderation/publishing."""
        return self.history.get_pending_publications()

    def approve_content(self, publication: Publication, edited_text: Optional[str] = None) -> None:
        """
        Approve content for publishing.

        Args:
            publication: Publication to approve
            edited_text: Optional edited text from moderator
        """
        if edited_text:
            publication.text = edited_text

        self.history.update_publication_status(publication, "approved")
        logger.info(f"Content approved: {publication.subtopic}")

    def reject_content(self, publication: Publication) -> None:
        """Reject content (won't be published)."""
        self.history.update_publication_status(publication, "rejected")
        logger.info(f"Content rejected: {publication.subtopic}")

    def mark_published(self, publication: Publication, instagram_id: str) -> None:
        """Mark content as successfully published."""
        self.history.update_publication_status(
            publication,
            status="published",
            instagram_id=instagram_id,
        )
        logger.info(f"Content published: {publication.subtopic} -> {instagram_id}")

    def get_stats(self) -> dict:
        """Get system statistics."""
        return {
            "topics": self.topic_selector.get_stats(),
            "media": self.media_manager.get_stats(),
            "history": self.history.get_stats(),
        }

    def close(self):
        """Clean up resources."""
        self.news_fetcher.close()
        self.text_generator.close()
        if self.image_searcher:
            self.image_searcher.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
