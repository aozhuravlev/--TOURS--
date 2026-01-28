#!/usr/bin/env python3
"""
Test story series generation pipeline.

Tests:
1. Text generation for story series
2. Video composition with sequential music
3. Full orchestrator pipeline
"""

import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def test_text_generation():
    """Test story series text generation."""
    print("\n" + "=" * 60)
    print("TEST 1: Story Series Text Generation")
    print("=" * 60)

    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if not deepseek_key:
        print("SKIP: DEEPSEEK_API_KEY not configured")
        return None

    from src.modules.text_generator import TextGenerator

    generator = TextGenerator(
        api_key=deepseek_key,
        prompts_dir=PROJECT_ROOT / "prompts",
    )

    print("\nGenerating story series for 'Хачапури по-аджарски'...")

    try:
        result = generator.generate_story_series(
            topic="Грузинская кухня",
            subtopic="Хачапури по-аджарски",
            facts="Хачапури по-аджарски — традиционное блюдо аджарской кухни в форме лодочки с сыром и яйцом.",
            min_count=3,
            max_count=5,
        )

        if result.success:
            print(f"\nGenerated {len(result.stories)} stories:")
            for story in result.stories:
                print(f"\n  #{story.order} [{story.angle}]")
                print(f"    Text: {story.text}")
                print(f"    Keywords: {story.keywords}")
            return result
        else:
            print(f"ERROR: {result.error}")
            return None

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None

    finally:
        generator.close()


def test_video_composition():
    """Test video composition with sequential music."""
    print("\n" + "=" * 60)
    print("TEST 2: Video Composition with Sequential Music")
    print("=" * 60)

    from src.modules.video_composer import VideoComposer

    # Find test images
    photos_dir = PROJECT_ROOT / "media" / "photos"
    images = []
    if photos_dir.exists():
        for ext in ["*.jpg", "*.jpeg", "*.png"]:
            images.extend(list(photos_dir.rglob(ext)))
            if len(images) >= 3:
                break

    if len(images) < 2:
        print("SKIP: Need at least 2 test images")
        return None

    images = images[:3]  # Use up to 3 images
    print(f"Using {len(images)} test images")

    # Find music file
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

    print(f"Using music: {music_path.name}")

    # Create composer
    composer = VideoComposer(
        output_dir=PROJECT_ROOT / "output",
        fonts_dir=PROJECT_ROOT / "assets" / "fonts",
    )

    if not composer._default_font:
        print("ERROR: No fonts installed!")
        print("Run: python scripts/download_fonts.py")
        return None

    # Prepare test stories
    stories = [
        {"photo_path": images[0], "text": "Хачапури - это любовь!"},
        {"photo_path": images[1 % len(images)], "text": "Сыр тянется, сердце поет"},
        {"photo_path": images[2 % len(images)], "text": "Приезжайте в Батуми!"},
    ]

    print(f"\nComposing {len(stories)} videos with sequential music...")

    try:
        video_paths = composer.compose_story_series(
            stories=stories,
            music_path=music_path,
            motion_effects=True,
            story_duration=5,  # Short for testing
        )

        print(f"\nCreated {len(video_paths)} videos:")
        for i, vp in enumerate(video_paths):
            size = vp.stat().st_size / 1024 / 1024
            print(f"  #{i + 1}: {vp.name} ({size:.2f} MB)")

        return video_paths

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_full_pipeline():
    """Test full story series pipeline via orchestrator."""
    print("\n" + "=" * 60)
    print("TEST 3: Full Story Series Pipeline")
    print("=" * 60)

    # Check required env vars
    required = ["PERPLEXITY_API_KEY", "DEEPSEEK_API_KEY"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"SKIP: Missing env vars: {', '.join(missing)}")
        return None

    from main import create_orchestrator

    print("\nCreating orchestrator...")
    orchestrator = create_orchestrator(
        use_image_search=True,
        use_text_overlay=True,
    )

    print(f"  Image search: {orchestrator.use_image_search}")
    print(f"  Text overlay: {orchestrator.use_text_overlay}")

    print("\nGenerating story series (this may take several minutes)...")

    try:
        result = orchestrator.generate_story_series(
            motion_effects=True,
            min_count=3,
            max_count=4,  # Keep it small for testing
            story_duration=10,  # Shorter for testing
        )

        if result and result.success:
            print(f"\nGenerated story series:")
            print(f"  Topic: {result.topic.category_name}")
            print(f"  Subtopic: {result.topic.subtopic}")
            print(f"  Stories: {result.story_count}")
            print(f"\n  Videos:")
            for i, story in enumerate(result.stories):
                size = story.video_path.stat().st_size / 1024 / 1024
                print(f"    #{story.order} [{story.angle}]: {story.video_path.name} ({size:.2f} MB)")
                print(f"        Text: {story.text[:50]}...")
            return result
        else:
            error = result.error if result else "No result returned"
            print(f"ERROR: {error}")
            return None

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None

    finally:
        orchestrator.close()


def main():
    print("=" * 60)
    print("STORY SERIES TEST SUITE")
    print("=" * 60)

    # Test 1: Text generation
    text_result = test_text_generation()

    # Test 2: Video composition
    if "--skip-video" not in sys.argv:
        video_result = test_video_composition()
    else:
        print("\nSkipping video test (--skip-video flag)")

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
