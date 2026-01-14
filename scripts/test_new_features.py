#!/usr/bin/env python3
"""
Test new features: image search and text overlay.

Tests:
1. Image search (Unsplash API)
2. Text overlay on video
3. Full pipeline integration
"""

import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def test_image_search():
    """Test image search functionality."""
    print("\n" + "=" * 60)
    print("TEST 1: Image Search")
    print("=" * 60)

    from src.modules.image_searcher import ImageSearcher

    unsplash_key = os.getenv("UNSPLASH_ACCESS_KEY")
    if not unsplash_key:
        print("SKIP: UNSPLASH_ACCESS_KEY not configured")
        return None

    searcher = ImageSearcher(
        unsplash_key=unsplash_key,
        download_dir=PROJECT_ROOT / "output" / "test_images",
    )

    # Test search
    print("\nSearching for 'Batumi Georgia'...")
    results = searcher.search("Batumi Georgia", count=3, orientation="portrait")

    if results:
        print(f"Found {len(results)} images:")
        for r in results:
            print(f"  - {r.id}: {r.description or 'No description'}")
            print(f"    Author: {r.author}")
    else:
        print("No results found!")
        return None

    # Test download
    print("\nDownloading first image...")
    image_path = searcher.download(results[0])
    print(f"Downloaded: {image_path}")
    print(f"Size: {image_path.stat().st_size / 1024:.1f} KB")

    searcher.close()
    return image_path


def test_text_overlay(image_path: Path = None):
    """Test text overlay functionality."""
    print("\n" + "=" * 60)
    print("TEST 2: Text Overlay")
    print("=" * 60)

    from src.modules.video_composer import VideoComposer

    # Use provided image or find a test image
    if image_path is None:
        # Try to find any image in media/photos
        photos_dir = PROJECT_ROOT / "media" / "photos"
        if photos_dir.exists():
            for ext in ["*.jpg", "*.jpeg", "*.png"]:
                images = list(photos_dir.rglob(ext))
                if images:
                    image_path = images[0]
                    break

    if image_path is None or not image_path.exists():
        print("SKIP: No test image available")
        return None

    print(f"Using image: {image_path}")

    # Find a music file
    music_dir = PROJECT_ROOT / "media" / "music"
    music_path = None
    if music_dir.exists():
        for ext in ["*.mp3", "*.m4a"]:
            tracks = list(music_dir.rglob(ext))
            if tracks:
                music_path = tracks[0]
                break

    if music_path is None:
        print("SKIP: No music file available")
        return None

    print(f"Using music: {music_path}")

    # Create composer
    composer = VideoComposer(
        output_dir=PROJECT_ROOT / "output",
        fonts_dir=PROJECT_ROOT / "assets" / "fonts",
    )

    if not composer._default_font:
        print("ERROR: No fonts installed!")
        print("Run: python scripts/download_fonts.py")
        return None

    print(f"Using font: {composer._default_font.name}")

    # Test text overlay
    test_text = "В Батуми сегодня прекрасная погода! Отличный день для прогулки."

    print(f"\nCreating video with overlay...")
    print(f"Text: {test_text}")

    try:
        video_path = composer.compose_story_with_overlay(
            photo_path=image_path,
            music_path=music_path,
            text=test_text,
            ken_burns=True,
            duration=5,  # Short for testing
        )
        print(f"\nVideo created: {video_path}")
        print(f"Size: {video_path.stat().st_size / 1024 / 1024:.2f} MB")
        return video_path

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_full_pipeline():
    """Test full pipeline with new features."""
    print("\n" + "=" * 60)
    print("TEST 3: Full Pipeline")
    print("=" * 60)

    # Check required env vars
    required = ["PERPLEXITY_API_KEY", "DEEPSEEK_API_KEY"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"SKIP: Missing env vars: {', '.join(missing)}")
        return

    from main import create_orchestrator

    print("\nCreating orchestrator with new features...")
    orchestrator = create_orchestrator(
        use_image_search=True,
        use_text_overlay=True,
    )

    print(f"  Image search: {orchestrator.use_image_search}")
    print(f"  Text overlay: {orchestrator.use_text_overlay}")

    print("\nGenerating story (this may take a minute)...")

    try:
        content = orchestrator.generate_story(ken_burns=True)

        if content:
            print(f"\nGenerated content:")
            print(f"  Topic: {content.topic.category_name}")
            print(f"  Subtopic: {content.topic.subtopic}")
            print(f"  Caption: {content.caption[:100]}...")
            if content.video_path:
                print(f"  Video: {content.video_path}")
                print(f"  Size: {content.video_path.stat().st_size / 1024 / 1024:.2f} MB")
        else:
            print("ERROR: Generation failed!")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        orchestrator.close()


def main():
    print("=" * 60)
    print("NEW FEATURES TEST SUITE")
    print("=" * 60)

    # Test 1: Image search
    image_path = test_image_search()

    # Test 2: Text overlay
    video_path = test_text_overlay(image_path)

    # Test 3: Full pipeline (optional, takes time)
    if "--full" in sys.argv:
        test_full_pipeline()
    else:
        print("\n" + "-" * 60)
        print("Skipping full pipeline test (use --full flag to run)")

    print("\n" + "=" * 60)
    print("TESTS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
