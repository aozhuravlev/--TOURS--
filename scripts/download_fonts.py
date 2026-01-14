#!/usr/bin/env python3
"""
Download fonts for Instagram Stories text overlays.

Downloads Montserrat and Open Sans font families.
Run this script once to set up fonts for video composition.
"""

import sys
import requests
from pathlib import Path

# Target directory for fonts
FONTS_DIR = Path(__file__).parent.parent / "assets" / "fonts"

# Direct download URLs for individual font files from Google Fonts GitHub
# Using google/fonts repository on GitHub
FONT_FILES = {
    # Montserrat family
    "Montserrat-Bold.ttf": "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf",
    "Montserrat-SemiBold.ttf": "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-SemiBold.ttf",
    "Montserrat-Medium.ttf": "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Medium.ttf",
    "Montserrat-Regular.ttf": "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Regular.ttf",
    # Open Sans family (from Google Fonts repo)
    "OpenSans-Bold.ttf": "https://github.com/googlefonts/opensans/raw/main/fonts/ttf/OpenSans-Bold.ttf",
    "OpenSans-SemiBold.ttf": "https://github.com/googlefonts/opensans/raw/main/fonts/ttf/OpenSans-SemiBold.ttf",
    "OpenSans-Regular.ttf": "https://github.com/googlefonts/opensans/raw/main/fonts/ttf/OpenSans-Regular.ttf",
}


def download_font(filename: str, url: str) -> bool:
    """Download a single font file."""
    dest_path = FONTS_DIR / filename

    # Skip if already exists
    if dest_path.exists():
        print(f"  Already exists: {filename}")
        return True

    print(f"  Downloading: {filename}...")

    try:
        response = requests.get(url, timeout=60, allow_redirects=True)
        response.raise_for_status()

        dest_path.write_bytes(response.content)
        size = len(response.content) / 1024
        print(f"    OK ({size:.1f} KB)")
        return True

    except Exception as e:
        print(f"    Failed: {e}")
        return False


def main():
    """Download all required fonts."""
    print("=" * 50)
    print("Font Downloader for Instagram Stories")
    print("=" * 50)
    print()

    # Create fonts directory
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Fonts directory: {FONTS_DIR}")
    print()

    # Download each font file
    print("Downloading fonts...")
    success = 0
    for filename, url in FONT_FILES.items():
        if download_font(filename, url):
            success += 1

    print()

    # Summary
    print("=" * 50)
    print(f"Downloaded {success}/{len(FONT_FILES)} font files")

    # List installed fonts
    ttf_files = list(FONTS_DIR.glob("*.ttf"))
    if ttf_files:
        print()
        print("Installed fonts:")
        for f in sorted(ttf_files):
            size = f.stat().st_size / 1024
            print(f"  - {f.name} ({size:.1f} KB)")
    else:
        print()
        print("WARNING: No fonts installed!")
        print("You may need to download fonts manually.")
        return 1

    print()
    print("Done! Fonts are ready for video composition.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
