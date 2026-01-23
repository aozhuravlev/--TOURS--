#!/usr/bin/env python3
"""
Download fonts for Instagram Stories text overlays.

Downloads 20 fonts used in round-robin rotation for story series.
Run this script once to set up fonts for video composition.

Usage:
    python scripts/download_fonts.py           # Download all fonts
    python scripts/download_fonts.py --check   # Check which fonts are missing
    python scripts/download_fonts.py --list    # List all fonts in rotation
"""

import sys
import argparse
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests
from config.fonts import FONT_ROTATION, FONT_FILES_LEGACY, FontConfig

# Target directory for fonts
FONTS_DIR = PROJECT_ROOT / "assets" / "fonts"


def download_font(font: FontConfig) -> bool:
    """
    Download a single font file.

    Args:
        font: FontConfig with filename and URL

    Returns:
        True if successful or already exists
    """
    dest_path = FONTS_DIR / font.filename

    # Skip if already exists
    if dest_path.exists():
        print(f"  [EXISTS] {font.name} ({font.filename})")
        return True

    print(f"  [DOWNLOAD] {font.name}...")

    try:
        response = requests.get(font.url, timeout=60, allow_redirects=True)
        response.raise_for_status()

        dest_path.write_bytes(response.content)
        size = len(response.content) / 1024
        print(f"    OK ({size:.1f} KB)")
        return True

    except Exception as e:
        print(f"    FAILED: {e}")
        return False


def download_legacy_font(filename: str, url: str) -> bool:
    """Download a legacy font file (Montserrat/OpenSans variants)."""
    dest_path = FONTS_DIR / filename

    if dest_path.exists():
        return True

    print(f"  [DOWNLOAD] {filename}...")

    try:
        response = requests.get(url, timeout=60, allow_redirects=True)
        response.raise_for_status()
        dest_path.write_bytes(response.content)
        size = len(response.content) / 1024
        print(f"    OK ({size:.1f} KB)")
        return True

    except Exception as e:
        print(f"    FAILED: {e}")
        return False


def check_fonts() -> tuple[list[FontConfig], list[FontConfig]]:
    """
    Check which fonts are installed and which are missing.

    Returns:
        Tuple of (installed, missing) font lists
    """
    installed = []
    missing = []

    for font in FONT_ROTATION:
        font_path = FONTS_DIR / font.filename
        if font_path.exists():
            installed.append(font)
        else:
            missing.append(font)

    return installed, missing


def list_fonts():
    """Print all fonts in rotation with their status."""
    print("\nFont Rotation Order (20 fonts):")
    print("=" * 60)

    for i, font in enumerate(FONT_ROTATION, 1):
        font_path = FONTS_DIR / font.filename
        status = "OK" if font_path.exists() else "MISSING"
        print(f"{i:2}. [{status:7}] {font.name:20} ({font.category})")

    print("=" * 60)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Download fonts for Instagram Stories"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check which fonts are missing without downloading"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all fonts in rotation"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Font Downloader for Instagram Stories")
    print("=" * 60)

    # List mode
    if args.list:
        list_fonts()
        return 0

    # Check mode
    if args.check:
        installed, missing = check_fonts()
        print(f"\nInstalled: {len(installed)}/{len(FONT_ROTATION)} fonts")
        if missing:
            print("\nMissing fonts:")
            for font in missing:
                print(f"  - {font.name} ({font.filename})")
            print(f"\nRun without --check to download missing fonts.")
            return 1
        else:
            print("All fonts are installed!")
            return 0

    # Download mode
    print(f"\nFonts directory: {FONTS_DIR}")

    # Create fonts directory
    FONTS_DIR.mkdir(parents=True, exist_ok=True)

    # Download rotation fonts (20 fonts)
    print(f"\n--- Rotation Fonts ({len(FONT_ROTATION)} fonts) ---")
    rotation_success = 0
    for font in FONT_ROTATION:
        if download_font(font):
            rotation_success += 1

    # Download legacy fonts (additional weights for fallback)
    print(f"\n--- Legacy Fonts ({len(FONT_FILES_LEGACY)} files) ---")
    legacy_success = 0
    for filename, url in FONT_FILES_LEGACY.items():
        if download_legacy_font(filename, url):
            legacy_success += 1

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Rotation fonts: {rotation_success}/{len(FONT_ROTATION)}")
    print(f"Legacy fonts:   {legacy_success}/{len(FONT_FILES_LEGACY)}")

    # List installed fonts
    ttf_files = sorted(FONTS_DIR.glob("*.ttf"))
    otf_files = sorted(FONTS_DIR.glob("*.otf"))
    all_fonts = ttf_files + otf_files

    if all_fonts:
        print(f"\nInstalled fonts ({len(all_fonts)} total):")
        for f in all_fonts:
            size = f.stat().st_size / 1024
            print(f"  - {f.name} ({size:.1f} KB)")
    else:
        print("\nWARNING: No fonts installed!")
        print("You may need to download fonts manually.")
        return 1

    # Check for critical failures
    if rotation_success < len(FONT_ROTATION):
        print(f"\nWARNING: {len(FONT_ROTATION) - rotation_success} rotation fonts failed!")
        print("System will fall back to available fonts.")

    print("\nDone! Fonts are ready for video composition.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
